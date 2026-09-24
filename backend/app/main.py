from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, conversations, documents, facts, health, memories, projects, runs, search, tasks, workspaces
from app.core.config import get_settings
from app.core.database import engine


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(title=get_settings().app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (health, auth, workspaces, projects, documents, search, facts, conversations, memories, tasks, runs):
    app.include_router(module.router)
