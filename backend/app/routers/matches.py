from fastapi import APIRouter, Depends

from ..core.deps import require_full_auth
from ..network.db_client import db_client

router = APIRouter(prefix="/matches", tags=["matches"])


@router.get("")
async def list_matches(
    limit: int = 50, tier: str | None = None, _: str = Depends(require_full_auth)
):
    matches, teams = (
        await db_client.list_matches(limit=limit, tier=tier),
        await db_client.list_teams(),
    )
    team_names = {t["id"]: t["name"] for t in teams}

    return [
        {
            **m,
            "radiant_team_name": team_names.get(m["radiant_team_id"], "?"),
            "dire_team_name": team_names.get(m["dire_team_id"], "?"),
        }
        for m in matches
    ]
