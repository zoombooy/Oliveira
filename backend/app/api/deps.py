from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models.tables import User

_DEMO_USERNAME = "demo"


async def get_current_user(db: AsyncSession = Depends(get_session)) -> User:
    """M0′/M1′ 单用户模式；M2′ 引入认证后替换实现。"""
    user = (
        await db.execute(select(User).where(User.username == _DEMO_USERNAME))
    ).scalar_one_or_none()
    if user is None:
        user = User(username=_DEMO_USERNAME, display_name="Demo User")
        db.add(user)
        await db.flush()
    return user
