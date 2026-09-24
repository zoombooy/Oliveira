import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_session
from app.models.tables import Conversation, Message, Run
from app.schemas.conversations import (
    AskIn,
    AskOut,
    CitationOut,
    ConversationCreate,
    ConversationOut,
    MessageOut,
)
from app.services.llm import LLMNotConfigured, get_llm
from app.services.retrieval import search

router = APIRouter(prefix="/api/v1", tags=["conversations"])

_ANSWER_SYSTEM_PROMPT = (
    "你是 Oliveira 知识助手。只依据提供的资料回答问题，"
    "并在引用资料时标注来源编号，如 [1]。资料不足以回答时明确说明，不要编造。"
)


async def _load_conversation(db: AsyncSession, conversation_id) -> Conversation:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conversation


@router.post("/projects/{project_id}/conversations", response_model=ConversationOut)
async def create_conversation(
    project_id,
    body: ConversationCreate | None = None,
    db: AsyncSession = Depends(get_session),
) -> Conversation:
    from app.models.tables import Project

    if await db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    conversation = Conversation(
        project_id=project_id, title=(body.title if body else None) or "新对话"
    )
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def list_messages(
    conversation_id, db: AsyncSession = Depends(get_session)
) -> list[MessageOut]:
    await _load_conversation(db, conversation_id)
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    return list((await db.execute(stmt)).scalars())


@router.post("/conversations/{conversation_id}/messages", response_model=AskOut)
async def ask(
    conversation_id,
    body: AskIn,
    db: AsyncSession = Depends(get_session),
) -> AskOut:
    conversation = await _load_conversation(db, conversation_id)
    settings = get_settings()
    llm = get_llm()

    run = Run(
        project_id=conversation.project_id,
        conversation_id=conversation.id,
        kind="chat",
        status="running",
        input={"question": body.content},
        started_at=datetime.datetime.now(datetime.UTC),
    )
    user_message = Message(conversation_id=conversation.id, role="user", content=body.content)
    db.add_all([run, user_message])
    await db.flush()

    query_embedding = await llm.embed([body.content])
    query_embedding = query_embedding[0] if query_embedding else None
    retrieved = await search(
        db,
        conversation.project_id,
        body.content,
        top_k=settings.retrieval_top_k,
        query_embedding=query_embedding,
    )

    context_block = "\n\n".join(
        f"[{i}] 来源: {r.document_title}"
        + (f" 第{r.page_number}页" if r.page_number else "")
        + f"\n{r.snippet}"
        for i, r in enumerate(retrieved, start=1)
    )
    prompt = (
        f"资料：\n{context_block}\n\n问题：{body.content}"
        if context_block
        else f"问题：{body.content}\n\n（资料库中没有检索到相关内容）"
    )

    try:
        answer = await llm.chat(
            [
                {"role": "system", "content": _ANSWER_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
        )
    except LLMNotConfigured as exc:
        run.status = "failed"
        run.error = str(exc)
        run.finished_at = datetime.datetime.now(datetime.UTC)
        await db.commit()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        run.status = "failed"
        run.error = f"模型调用失败: {exc}"
        run.finished_at = datetime.datetime.now(datetime.UTC)
        await db.commit()
        raise HTTPException(status_code=502, detail=f"模型调用失败: {exc}") from exc

    citations = [
        CitationOut(
            chunk_id=r.chunk_id,
            document_id=r.document_id,
            document_title=r.document_title,
            page_number=r.page_number,
            score=r.score,
            method=r.method,
            snippet=r.snippet[:300],
        )
        for r in retrieved
    ]
    assistant_message = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=answer,
        run_id=run.id,
    )
    run.status = "completed"
    run.output = {
        "citations": [c.chunk_id for c in citations],
        "retrieved": len(citations),
        "retrieval_method": citations[0].method if citations else "none",
    }
    run.finished_at = datetime.datetime.now(datetime.UTC)
    conversation.updated_at = run.finished_at
    db.add(assistant_message)
    await db.commit()
    await db.refresh(assistant_message)

    return AskOut(
        conversation_id=conversation.id,
        message=MessageOut(
            id=assistant_message.id,
            role=assistant_message.role,
            content=assistant_message.content,
            run_id=assistant_message.run_id,
            created_at=assistant_message.created_at,
        ),
        citations=citations,
        run_id=run.id,
    )
