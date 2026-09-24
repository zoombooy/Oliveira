from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_project_access
from app.core.database import get_session
from app.models.tables import User
from app.schemas.search import SearchIn, SearchOut, SearchResultOut
from app.services.llm import get_llm_for_project
from app.services.retrieval import search

router = APIRouter(prefix="/api/v1", tags=["search"])


@router.post("/projects/{project_id}/search", response_model=SearchOut)
async def project_search(
    project_id: UUID,
    body: SearchIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> SearchOut:
    await require_project_access(project_id, user, db)
    llm = await get_llm_for_project(db, project_id)
    embedding = await llm.embed([body.query])
    results = await search(
        db,
        project_id,
        body.query,
        top_k=body.top_k,
        query_embedding=embedding[0] if embedding else None,
        version_id=body.version_id,
    )
    return SearchOut(
        query=body.query,
        results=[
            SearchResultOut(
                chunk_id=result.chunk_id,
                document_id=result.document_id,
                document_version_id=result.document_version_id,
                document_title=result.document_title,
                page_number=result.page_number,
                paragraph_index=result.paragraph_index,
                snippet=result.snippet,
                vector_score=result.vector_score,
                keyword_score=result.keyword_score,
                final_score=result.score,
                methods=result.methods,
            )
            for result in results
        ],
    )
