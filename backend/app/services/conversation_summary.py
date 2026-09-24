from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import Conversation, ConversationSummary, Message, Task
from app.services.llm import get_llm_for_project


async def execute_conversation_summary(db: AsyncSession, task: Task) -> dict:
    conversation_id = task.payload.get("conversation_id")
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise ValueError("摘要目标会话不存在")
    messages = list(
        (
            await db.execute(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(Message.created_at)
            )
        ).scalars()
    )
    if len(messages) < 4:
        return {"summarized": False, "reason": "message_count_below_threshold"}
    llm = await get_llm_for_project(db, conversation.project_id)
    transcript = "\n".join(f"{item.role}: {item.content}" for item in messages[:-4])
    result = await llm.chat(
        [
            {"role": "system", "content": "你是对话摘要器，保留关键事实、用户约束、Run ID 和证据编号。"},
            {"role": "user", "content": f"请用中文压缩以下早期对话，不要添加原文没有的信息：\n{transcript}"},
        ],
        temperature=0,
    )
    summary = ConversationSummary(
        conversation_id=conversation.id,
        covered_until_message_id=messages[-5].id,
        content=result,
        token_estimate=max(len(result) // 3, 1),
    )
    db.add(summary)
    await db.commit()
    return {"summarized": True, "summary_id": str(summary.id), "covered_messages": len(messages) - 4}
