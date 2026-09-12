import httpx
from fastapi import APIRouter, Depends

from ..core.config import settings
from ..core.deps import require_full_auth
from ..network.db_client import db_client

router = APIRouter(prefix="/teams", tags=["teams"])


@router.get("")
async def list_teams(_: str = Depends(require_full_auth)):
    return await db_client.list_teams()


@router.get("/{team_id}/roster")
async def get_team_roster(team_id: int, _: str = Depends(require_full_auth)):
    """Current active roster for one team, fetched live from OpenDota on
    demand (not stored) — only requested for the handful of teams the UI
    actually shows a roster popover for."""
    team = await db_client.get_team(team_id)

    async with httpx.AsyncClient(base_url=settings.opendota_base_url, timeout=15.0) as od:
        r = await od.get(f"/teams/{team['opendota_team_id']}/players")
        r.raise_for_status()
        players = r.json()

    current_members = [p for p in players if p.get("is_current_team_member")]

    return {
        "team_id": team_id,
        "team_name": team["name"],
        "players": [
            {
                "name": p.get("name") or f"Player {p.get('account_id')}",
                "games_played": p.get("games_played", 0),
            }
            for p in current_members
        ],
    }
