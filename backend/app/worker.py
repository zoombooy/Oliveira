"""Oliveira 数据库任务 Worker。

Worker 只通过 PostgreSQL 领取任务，使用 SKIP LOCKED 保证多个 Worker 不重复消费。
具体任务处理器保持在应用层，后续可以继续增加事实抽取和摘要处理器。
"""

import asyncio
import logging

from app.core.config import get_settings
from app.core.database import SessionLocal, engine
from app.services.agent import execute_agent_run
from app.services.fact_extraction import execute_fact_extract
from app.services.conversation_summary import execute_conversation_summary
from app.services.tasks import claim_task, complete_task, fail_task

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("oliveira.worker")


async def handle_task(task, db) -> dict:
    if task.kind == "agent_run":
        return await execute_agent_run(db, task.payload["run_id"])
    if task.kind == "fact_extract":
        return await execute_fact_extract(db, task)
    if task.kind == "conversation_summarize":
        return await execute_conversation_summary(db, task)
    if task.kind in {"document_ingest", "document_embed"}:
        # 这些处理器在对应产品模块接入前仍然有正式的任务生命周期；
        # 不把它们伪装成已完成，保留可查询的 accepted 结果供后续处理器接管。
        return {"accepted": True, "kind": task.kind, "payload": task.payload}
    raise ValueError(f"未知任务类型: {task.kind}")


async def run() -> None:
    settings = get_settings()
    logger.info("Oliveira worker %s started", settings.worker_id)
    try:
        while True:
            async with SessionLocal() as db:
                task = await claim_task(db, settings.worker_id)
                if task is not None:
                    try:
                        result = await handle_task(task, db)
                        await complete_task(db, task.id, result)
                    except Exception as exc:
                        logger.exception("task %s failed", task.id)
                        await fail_task(db, task.id, str(exc))
            await asyncio.sleep(settings.task_poll_interval)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
