import asyncio

import pytest

from app.services.agent_tools import (
    ToolArgumentError,
    UnknownAgentTool,
    build_default_registry,
)


def test_default_registry_contains_only_read_tools() -> None:
    registry = build_default_registry()
    assert registry.names() == ["get_entity_timeline", "query_facts", "search_chunks"]


def test_unknown_tool_is_rejected() -> None:
    registry = build_default_registry()
    with pytest.raises(UnknownAgentTool):
        registry.get("run_shell")


def test_tool_arguments_are_schema_validated() -> None:
    registry = build_default_registry()
    with pytest.raises(ToolArgumentError):
        asyncio.run(
            registry.invoke(
                "search_chunks",
                {"query": "", "top_k": 999},
                context=None,  # type: ignore[arg-type]
            )
        )
