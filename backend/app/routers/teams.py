import asyncio

import httpx
from fastapi import APIRouter, Depends

from ..core.config import settings
from ..core.deps import require_full_auth
from ..network.db_client import db_client

router = APIRouter(prefix="/teams", tags=["teams"])


@router.get("")
async def list_teams(_: str = Depends(require_full_auth)):
    return await db_client.list_teams()


ROSTER_SIZE = 5


@router.get("/{team_id}/roster")
async def get_team_roster(team_id: int, _: str = Depends(require_full_auth)):
    """Active roster for one team, fetched live from OpenDota on demand (not
    stored) — only requested for the handful of teams the UI shows a roster
    popover for.

    OpenDota's `is_current_team_member` flag is unreliable: for many teams it
    marks fewer than the five players a Dota 2 squad actually fields (2 for
    some, 0 for others), and occasionally more. So flagged members come first,
    then the roster is topped up with the team's most-played remaining players
    until it holds five.
    """
    team = await db_client.get_team(team_id)

    async with httpx.AsyncClient(base_url=settings.opendota_base_url, timeout=15.0) as od:
        r = await od.get(f"/teams/{team['opendota_team_id']}/players")
        r.raise_for_status()
        players = r.json()

        by_games_played = sorted(players, key=lambda p: p.get("games_played") or 0, reverse=True)
        flagged = [p for p in by_games_played if p.get("is_current_team_member")]
        rest = [p for p in by_games_played if not p.get("is_current_team_member")]
        roster = (flagged + rest)[:ROSTER_SIZE]

        # The team endpoint leaves `name` empty for some accounts; their
        # nickname has to be looked up per player. Only the missing ones are
        # fetched, concurrently.
        missing = [p for p in roster if not p.get("name") and p.get("account_id")]
        resolved_names = dict(
            zip(
                (p["account_id"] for p in missing),
                await asyncio.gather(
                    *(_fetch_persona_name(od, p["account_id"]) for p in missing)
                ),
            )
        )

    def display_name(player: dict) -> str:
        account_id = player.get("account_id")
        return (
            player.get("name")
            or resolved_names.get(account_id)
            or f"Player {account_id}"
        )

    return {
        "team_id": team_id,
        "team_name": team["name"],
        "players": [
            {"name": display_name(p), "games_played": p.get("games_played") or 0}
            for p in roster
        ],
    }


async def _fetch_persona_name(client: httpx.AsyncClient, account_id: int) -> str | None:
    try:
        r = await client.get(f"/players/{account_id}")
        r.raise_for_status()
        return (r.json().get("profile") or {}).get("personaname")
    except httpx.HTTPError:
        return None
