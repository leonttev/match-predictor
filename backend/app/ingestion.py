"""Data ingestion pipeline: pulls Dota 2 pro-team, league and pro-match data
from the public OpenDota API, stores it via the DB interaction module, then
asks the prediction engine to recompute Elo ratings / recent form for every
team and writes those back too.

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

TOP_TEAMS_LIMIT = 120

# One page of /proMatches covers only the ~100 most recent pro matches, which
# at any given moment is dominated by whatever low-tier qualifier is running.
# Paging back further is what makes tier-1 events (e.g. The International)
# actually appear in the data at all.
PRO_MATCHES_PAGES = 6

# OpenDota's league tiers mapped onto the tier labels the UI ranks by.
# "excluded" leagues (the bulk of OpenDota's league table) and leagues with no
# tier set carry no usable signal, so they stay "unknown" rather than being
# presented as a real tier.
TIER_BY_OPENDOTA_TIER = {
    "premium": "tier1",
    "professional": "tier2",
    "amateur": "tier3",
}
UNKNOWN_TIER = "unknown"
TIER_RANK = {"tier1": 1, "tier2": 2, "tier3": 3, UNKNOWN_TIER: 4}


async def _fetch_top_teams(client: httpx.AsyncClient) -> list[dict]:
    r = await client.get("/teams")
    r.raise_for_status()
    return r.json()[:TOP_TEAMS_LIMIT]


async def _fetch_league_tiers(client: httpx.AsyncClient) -> dict[int, str]:
    r = await client.get("/leagues")
    r.raise_for_status()
    return {
        league["leagueid"]: TIER_BY_OPENDOTA_TIER.get(league.get("tier"), UNKNOWN_TIER)
        for league in r.json()
        if league.get("leagueid") is not None
    }


async def _fetch_pro_matches(client: httpx.AsyncClient) -> list[dict]:
    """Pages back through recent pro matches. Pages are inherently sequential:
    each request needs the oldest match id from the previous page."""
    collected: list[dict] = []
    oldest_match_id: int | None = None

    for _ in range(PRO_MATCHES_PAGES):
        params = {"less_than_match_id": oldest_match_id} if oldest_match_id else {}
        r = await client.get("/proMatches", params=params)
        r.raise_for_status()
        page = r.json()
        if not page:
            break
        collected.extend(page)
        oldest_match_id = min(m["match_id"] for m in page)

    return collected


async def run_ingestion() -> dict:
    async with httpx.AsyncClient(base_url=settings.opendota_base_url, timeout=30.0) as od:
        top_teams, league_tiers, pro_matches = await asyncio.gather(
            _fetch_top_teams(od), _fetch_league_tiers(od), _fetch_pro_matches(od)
        )

    usable_matches = [
        m
        for m in pro_matches
        if m.get("radiant_team_id") and m.get("dire_team_id") and m.get("radiant_win") is not None
    ]

    # Seed the known top teams with OpenDota's own long-history rating (see
    # recompute_ratings for why), then add every other team that shows up in
    # the ingested matches so the prediction pool isn't limited to the top.
    team_payloads: dict[int, dict] = {}
    for t in top_teams:
        if t.get("team_id") is None:
            continue
        team_payloads[t["team_id"]] = {
            "opendota_team_id": t["team_id"],
            "name": t.get("name") or f"Team {t['team_id']}",
            "tag": t.get("tag"),
            "seed_rating": t.get("rating"),
        }

    for m in usable_matches:
        for opendota_id, name_field in (
            (m["radiant_team_id"], "radiant_name"),
            (m["dire_team_id"], "dire_name"),
        ):
            if opendota_id not in team_payloads:
                team_payloads[opendota_id] = {
                    "opendota_team_id": opendota_id,
                    "name": m.get(name_field) or f"Team {opendota_id}",
                    "tag": None,
                    "seed_rating": None,
                }

    stored_teams = await db_client.upsert_teams_bulk(list(team_payloads.values()))

    # The DB module's Match rows reference teams by internal id, not upstream id.
    internal_id_by_opendota_id = {t["opendota_team_id"]: t["id"] for t in stored_teams}

    match_payloads = [
        {
            "opendota_match_id": m["match_id"],
            "radiant_team_id": internal_id_by_opendota_id[m["radiant_team_id"]],
            "dire_team_id": internal_id_by_opendota_id[m["dire_team_id"]],
            "radiant_win": m["radiant_win"],
            "start_time": m["start_time"],
            "league_name": m.get("league_name"),
            "league_id": m.get("leagueid"),
            "league_tier": league_tiers.get(m.get("leagueid"), UNKNOWN_TIER),
        }
        for m in usable_matches
    ]
    await db_client.upsert_matches_bulk(match_payloads)

    ratings_summary = await recompute_ratings()

    tier1_count = sum(1 for m in match_payloads if m["league_tier"] == "tier1")
    return {
        "teams_ingested": len(stored_teams),
        "matches_ingested": len(match_payloads),
        "tier1_matches": tier1_count,
        "ratings_updated": ratings_summary["teams_count"],
    }


def _best_tier_by_team(stored_matches: list[dict]) -> dict[int, str]:
    """A team's tier is the strongest league tier it has been observed playing
    in. Teams with no observed matches keep the default unknown tier."""
    best: dict[int, str] = {}
    for m in stored_matches:
        tier = m.get("league_tier") or UNKNOWN_TIER
        for team_id in (m["radiant_team_id"], m["dire_team_id"]):
            current = best.get(team_id)
            if current is None or TIER_RANK[tier] < TIER_RANK[current]:
                best[team_id] = tier
    return best


async def recompute_ratings() -> dict:
    """Re-derives Elo ratings, recent form and tier from the full stored match
    history and persists them onto each team row via the DB module."""
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

    all_teams = await db_client.list_teams()
    initial_ratings = {str(t["id"]): t["seed_rating"] for t in all_teams}

    result = await prediction_client.compute_ratings(engine_matches, initial_ratings)
    tier_by_team = _best_tier_by_team(stored_matches)

    updates = [
        {
            "team_id": int(team_id),
            "rating": rating,
            "recent_form": result["form"].get(team_id, 0.5),
            "tier": tier_by_team.get(int(team_id), UNKNOWN_TIER),
        }
        for team_id, rating in result["ratings"].items()
    ]
    await db_client.update_teams_stats_bulk(updates)

    return {"teams_count": len(updates)}
