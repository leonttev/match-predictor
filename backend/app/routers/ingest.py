from fastapi import APIRouter, Depends

from .. import ingestion
from ..core.deps import require_full_auth

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("/run")
async def run_ingestion(_: str = Depends(require_full_auth)):
    return await ingestion.run_ingestion()
