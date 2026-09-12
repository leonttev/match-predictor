from fastapi import APIRouter, Depends

from ..core.deps import require_full_auth
from ..network.db_client import db_client

router = APIRouter(prefix="/teams", tags=["teams"])


@router.get("")
async def list_teams(_: str = Depends(require_full_auth)):
    return await db_client.list_teams()
