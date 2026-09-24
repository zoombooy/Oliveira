"""Oliveira Agent 的只读工具注册表。

工具层不接触 HTTP 请求，也不允许任意 SQL 或代码执行。每个工具只通过
ToolContext 取得当前 project scope，并返回结构化结果和可核验 evidence。
"""

import re
from dataclasses import dataclass
from time import monotonic
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.tables import Fact, FactVersion
from app.services.llm import get_llm_for_project
from app.services.retrieval import RetrievedChunk, search


class UnknownAgentTool(ValueError):
    pass


class ToolArgumentError(ValueError):
    pass


@dataclass(frozen=True)
class ToolContext:
    db: AsyncSession
    project_id: UUID
    run_id: UUID


@dataclass
class ToolResult:
    output: dict[str, Any]
    evidence: list[dict[str, Any]]
    elapsed_ms: int


def citation_payload(item: RetrievedChunk) -> dict[str, Any]:
    return {
        "chunk_id": item.chunk_id,
        "document_id": item.document_id,
        "document_version_id": item.document_version_id,
        "document_title": item.document_title,
        "page_number": item.page_number,
        "paragraph_index": item.paragraph_index,
        "snippet": item.snippet[:500],
        "score": item.score,
        "method": item.method,
    }


class SearchChunksArgs(BaseModel):
    query: str = Field(min_length=1, max_length=8000)
    top_k: int = Field(default=8, ge=1, le=50)
    version_id: UUID | None = None


class QueryFactsArgs(BaseModel):
    query: str = Field(min_length=1, max_length=8000)
    limit: int = Field(default=20, ge=1, le=50)


class EntityTimelineArgs(BaseModel):
    subject: str = Field(min_length=1, max_length=500)
    predicate: str | None = Field(default=None, max_length=500)
    limit: int = Field(default=50, ge=1, le=100)


class AgentTool:
    name: str
    description: str
    args_model: type[BaseModel]
    side_effect = "none"

    async def invoke(self, arguments: BaseModel, context: ToolContext) -> ToolResult:
        raise NotImplementedError


def _terms(value: str) -> list[str]:
    terms = re.findall(r"[\w\u4e00-\u9fff]{2,}", value.lower())
    return list(dict.fromkeys(terms))[:8] or [value.strip().lower()]


class SearchChunksTool(AgentTool):
    name = "search_chunks"
    description = "在当前项目中执行向量与关键词混合检索，返回可引用的原文证据。"
    args_model = SearchChunksArgs

    async def invoke(self, arguments: SearchChunksArgs, context: ToolContext) -> ToolResult:
        started = monotonic()
        llm = await get_llm_for_project(context.db, context.project_id)
        embedded = await llm.embed([arguments.query])
        results = await search(
            context.db,
            context.project_id,
            arguments.query,
            top_k=arguments.top_k,
            query_embedding=embedded[0] if embedded else None,
            version_id=arguments.version_id,
        )
        evidence = [citation_payload(item) for item in results]
        return ToolResult(
            output={"results": evidence, "count": len(evidence)},
            evidence=evidence,
            elapsed_ms=round((monotonic() - started) * 1000),
        )


async def _fact_rows(
    db: AsyncSession,
    project_id: UUID,
    *,
    query: str | None = None,
    subject: str | None = None,
    predicate: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    stmt = (
        select(Fact, FactVersion)
        .join(FactVersion, Fact.current_version_id == FactVersion.id)
        .where(Fact.project_id == project_id, Fact.status.in_(["asserted", "derived"]))
        .order_by(FactVersion.valid_from, FactVersion.recorded_at)
    )
    rows = (await db.execute(stmt)).all()
    terms = _terms(query) if query else []
    subject_value = subject.lower() if subject else None
    predicate_value = predicate.lower() if predicate else None
    results: list[dict[str, Any]] = []
    for fact, version in rows:
        searchable = f"{version.subject_text} {version.predicate} {version.object_text}".lower()
        if terms and not any(term in searchable for term in terms):
            continue
        if subject_value and subject_value not in version.subject_text.lower():
            continue
        if predicate_value and predicate_value not in version.predicate.lower():
            continue
        results.append(
            {
                "fact_id": str(fact.id),
                "subject": version.subject_text,
                "predicate": version.predicate,
                "object": version.object_text,
                "valid_from": version.valid_from.isoformat() if version.valid_from else None,
                "valid_to": version.valid_to.isoformat() if version.valid_to else None,
                "recorded_at": version.recorded_at.isoformat(),
                "evidence_ref_id": str(version.evidence_ref_id) if version.evidence_ref_id else None,
            }
        )
    return results[:limit]


class QueryFactsTool(AgentTool):
    name = "query_facts"
    description = "查询当前项目中已经审核通过的结构化事实。"
    args_model = QueryFactsArgs

    async def invoke(self, arguments: QueryFactsArgs, context: ToolContext) -> ToolResult:
        started = monotonic()
        facts = await _fact_rows(
            context.db,
            context.project_id,
            query=arguments.query,
            limit=arguments.limit,
        )
        return ToolResult(
            output={"facts": facts, "count": len(facts)},
            evidence=[],
            elapsed_ms=round((monotonic() - started) * 1000),
        )


class GetEntityTimelineTool(AgentTool):
    name = "get_entity_timeline"
    description = "按主体和可选谓词读取已审核事实的业务时间与记录时间演变。"
    args_model = EntityTimelineArgs

    async def invoke(self, arguments: EntityTimelineArgs, context: ToolContext) -> ToolResult:
        started = monotonic()
        facts = await _fact_rows(
            context.db,
            context.project_id,
            subject=arguments.subject,
            predicate=arguments.predicate,
            limit=arguments.limit,
        )
        return ToolResult(
            output={"timeline": facts, "count": len(facts)},
            evidence=[],
            elapsed_ms=round((monotonic() - started) * 1000),
        )


class ToolRegistry:
    def __init__(self, tools: list[AgentTool] | None = None) -> None:
        self._tools = {item.name: item for item in (tools or [])}

    def register(self, tool: AgentTool) -> None:
        if tool.side_effect != "none":
            raise ValueError("M0-M3 Agent 只允许注册无副作用工具")
        self._tools[tool.name] = tool

    def get(self, name: str) -> AgentTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise UnknownAgentTool(f"未知 Agent 工具: {name}") from exc

    def names(self) -> list[str]:
        return sorted(self._tools)

    async def invoke(self, name: str, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        tool = self.get(name)
        try:
            parsed = tool.args_model.model_validate(arguments)
        except Exception as exc:
            raise ToolArgumentError(f"工具 {name} 参数无效: {exc}") from exc
        return await tool.invoke(parsed, context)


def build_default_registry() -> ToolRegistry:
    settings = get_settings()
    # 读取配置时保留上限的单一来源；工具自身还会通过 schema 做更小的参数校验。
    _ = settings.max_tool_output_chars
    registry = ToolRegistry()
    registry.register(SearchChunksTool())
    registry.register(QueryFactsTool())
    registry.register(GetEntityTimelineTool())
    return registry
