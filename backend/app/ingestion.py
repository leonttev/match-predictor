"""Data ingestion pipeline: pulls Dota 2 pro-team and pro-match data from the
public OpenDota API, stores it via the DB interaction module, then asks the
prediction engine to recompute Elo ratings / recent form for every team and
writes those back too.

This is the async orchestration piece referenced by course requirement §2.4b
(the backend coordinates network calls to external data sources, the DB
module, and the functional module without blocking on any single one).
"""

import asyncio
import logging

import httpx

from .core.config import settings
from .network.db_client import db_client
from .network.prediction_client import prediction_client

logger = logging.getLogger("ingestion")

TOP_TEAMS_LIMIT = 60
PRO_MATCHES_LIMIT = 100

# The DB module's SQLite backend serializes writes; firing dozens of upserts
# at once just queues them up behind SQLite's write lock until the HTTP
# client times out. A bounded semaphore keeps a healthy number in flight
# without collapsing back to one-at-a-time.
_DB_WRITE_CONCURRENCY = 8


async def _gather_limited(coros: list) -> list:
    if not coros:
        return []
    semaphore = asyncio.Semaphore(_DB_WRITE_CONCURRENCY)

    async def _run(coro):
        async with semaphore:
            return await coro

    return await asyncio.gather(*(_run(c) for c in coros))


async def _fetch_top_teams(client: httpx.AsyncClient) -> list[dict]:
    r = await client.get("/teams")
    r.raise_for_status()
    teams = r.json()
    return teams[:TOP_TEAMS_LIMIT]


async def _fetch_pro_matches(client: httpx.AsyncClient) -> list[dict]:
    r = await client.get("/proMatches")
    r.raise_for_status()
    return r.json()[:PRO_MATCHES_LIMIT]


async def run_ingestion() -> dict:
    async with httpx.AsyncClient(base_url=settings.opendota_base_url, timeout=20.0) as od:
        top_teams, pro_matches = await asyncio.gather(
            _fetch_top_teams(od), _fetch_pro_matches(od)
        )

    # Maps OpenDota's team_id to our own internal Team.id — the DB module's
    # Match rows reference teams by internal id, not by the upstream id.
    internal_id_by_opendota_id: dict[int, int] = {}

    async def upsert_and_remember(opendota_id: int, name: str, tag: str | None = None) -> None:
        team = await db_client.upsert_team(opendota_id, name, tag)
        internal_id_by_opendota_id[opendota_id] = team["id"]

    # Upsert the top-rated teams first so the UI has a browsable team list
    # even before any of them show up in recent pro matches.
    upsert_tasks = [
        upsert_and_remember(t["team_id"], t.get("name") or f"Team {t['team_id']}", t.get("tag"))
        for t in top_teams
        if t.get("team_id") is not None
    ]
    await _gather_limited(upsert_tasks)

    usable_matches = [
        m
        for m in pro_matches
        if m.get("radiant_team_id") and m.get("dire_team_id") and m.get("radiant_win") is not None
    ]

    # Track which opendota ids have a task scheduled (not just confirmed) —
    # the same team can appear in several matches, and scheduling two
    # concurrent upserts for the same not-yet-existing team_id races on the
    # DB module's unique constraint.
    scheduled_ids = set(internal_id_by_opendota_id)
    missing_team_tasks = []
    for m in usable_matches:
        for opendota_id, name_field in (
            (m["radiant_team_id"], "radiant_name"),
            (m["dire_team_id"], "dire_name"),
        ):
            if opendota_id not in scheduled_ids:
                scheduled_ids.add(opendota_id)
                missing_team_tasks.append(
                    upsert_and_remember(opendota_id, m.get(name_field) or f"Team {opendota_id}")
                )
    await _gather_limited(missing_team_tasks)

    match_upsert_tasks = [
        db_client.upsert_match(
            {
                "opendota_match_id": m["match_id"],
                "radiant_team_id": internal_id_by_opendota_id[m["radiant_team_id"]],
                "dire_team_id": internal_id_by_opendota_id[m["dire_team_id"]],
                "radiant_win": m["radiant_win"],
                "start_time": m["start_time"],
                "league_name": m.get("league_name"),
            }
        )
        for m in usable_matches
    ]
    await _gather_limited(match_upsert_tasks)

    ratings_summary = await recompute_ratings()

    return {
        "teams_ingested": len(internal_id_by_opendota_id),
        "matches_ingested": len(usable_matches),
        "ratings_updated": ratings_summary["teams_count"],
    }


async def recompute_ratings() -> dict:
    """Re-derives Elo ratings + recent form from full stored match history and
    persists them onto each team row via the DB module."""
    stored_matches = await db_client.list_matches(limit=10_000)
    engine_matches = [
        {
            "radiant_team_id": m["radiant_team_id"],
            "dire_team_id": m["dire_team_id"],
            "radiant_win": m["radiant_win"],
            "start_time": m["start_time"],
        }
        for m in stored_matches
    ]

    if not engine_matches:
        return {"teams_count": 0}

    result = await prediction_client.compute_ratings(engine_matches)

    update_tasks = [
        db_client.update_team_rating(
            int(team_id), rating, result["form"].get(team_id, 0.5)
        )
        for team_id, rating in result["ratings"].items()
    ]
    await _gather_limited(update_tasks)

    return {"teams_count": len(update_tasks)}
