from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_project_access, require_workspace_member
from app.core.database import get_session
from app.core.config import get_settings
from app.models.tables import Conversation, Message, Run, User
from app.schemas.conversations import (
    AskIn,
    AskAcceptedOut,
    ConversationCreate,
    ConversationOut,
    MessageOut,
)
from app.services.run_events import append_run_event
from app.services.tasks import enqueue_task

router = APIRouter(prefix="/api/v1", tags=["conversations"])

async def _load_conversation(db: AsyncSession, conversation_id) -> Conversation:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conversation


async def _require_conversation_scope(
    conversation: Conversation,
    user: User,
    db: AsyncSession,
):
    await require_workspace_member(conversation.workspace_id, user, db)
    if conversation.project_id is None:
        return None
    project = await require_project_access(conversation.project_id, user, db)
    if project.workspace_id != conversation.workspace_id:
        raise HTTPException(status_code=409, detail="会话作用域与项目工作空间不一致")
    return project


async def _create_conversation(
    workspace_id: UUID,
    project_id: UUID | None,
    body: ConversationCreate | None,
    user: User,
    db: AsyncSession,
) -> Conversation:
    await require_workspace_member(workspace_id, user, db)
    if project_id is not None:
        project = await require_project_access(project_id, user, db)
        if project.workspace_id != workspace_id:
            raise HTTPException(status_code=400, detail="项目不属于该工作空间")
    conversation = Conversation(
        workspace_id=workspace_id,
        project_id=project_id,
        user_id=user.id,
        title=(body.title if body else None) or "新对话",
    )
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


@router.post("/workspaces/{workspace_id}/conversations", response_model=ConversationOut)
async def create_workspace_conversation(
    workspace_id: UUID,
    body: ConversationCreate | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> Conversation:
    return await _create_conversation(workspace_id, None, body, user, db)


@router.get("/workspaces/{workspace_id}/conversations", response_model=list[ConversationOut])
async def list_workspace_conversations(
    workspace_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> list[Conversation]:
    await require_workspace_member(workspace_id, user, db)
    stmt = (
        select(Conversation)
        .where(Conversation.workspace_id == workspace_id)
        .order_by(Conversation.updated_at.desc())
    )
    return list((await db.execute(stmt)).scalars())


@router.post("/projects/{project_id}/conversations", response_model=ConversationOut)
async def create_conversation(
    project_id: UUID,
    body: ConversationCreate | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> Conversation:
    project = await require_project_access(project_id, user, db)
    return await _create_conversation(project.workspace_id, project_id, body, user, db)


@router.get("/projects/{project_id}/conversations", response_model=list[ConversationOut])
async def list_conversations(
    project_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> list[Conversation]:
    await require_project_access(project_id, user, db)
    return list(
        (
            await db.execute(
                select(Conversation)
                .where(Conversation.project_id == project_id)
                .order_by(Conversation.updated_at.desc())
            )
        ).scalars()
    )


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def list_messages(
    conversation_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> list[MessageOut]:
    conversation = await _load_conversation(db, conversation_id)
    await _require_conversation_scope(conversation, user, db)
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    return list((await db.execute(stmt)).scalars())


@router.post("/conversations/{conversation_id}/messages", response_model=AskAcceptedOut, status_code=status.HTTP_202_ACCEPTED)
async def ask(
    conversation_id: UUID,
    body: AskIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> AskAcceptedOut:
    conversation = await _load_conversation(db, conversation_id)
    await _require_conversation_scope(conversation, user, db)
    run = Run(
        workspace_id=conversation.workspace_id,
        project_id=conversation.project_id,
        conversation_id=conversation.id,
        kind="chat",
        status="queued",
        input={"question": body.content},
    )
    user_message = Message(conversation_id=conversation.id, role="user", content=body.content)
    db.add_all([run, user_message])
    await db.flush()
    await append_run_event(db, run.id, "queued", {"question_length": len(body.content)})
    await enqueue_task(
        db,
        workspace_id=conversation.workspace_id,
        project_id=conversation.project_id,
        kind="agent_run",
        payload={"run_id": str(run.id), "conversation_id": str(conversation.id)},
    )
    total_chars = (
        await db.execute(
            select(func.coalesce(func.sum(func.length(Message.content)), 0)).where(
                Message.conversation_id == conversation.id
            )
        )
    ).scalar_one()
    if total_chars >= get_settings().max_context_tokens * 3:
        await enqueue_task(
            db,
            workspace_id=conversation.workspace_id,
            project_id=conversation.project_id,
            kind="conversation_summarize",
            payload={"conversation_id": str(conversation.id)},
            max_attempts=2,
        )
    await db.commit()
    return AskAcceptedOut(run_id=run.id, user_message_id=user_message.id, status="queued")
