"""DB interaction module — the sole owner of the database connection.

Nothing outside this service touches SQLAlchemy or the DB driver directly;
the backend and the ingestion script both go through this HTTP API. That
split is what the course architecture calls out as a distinct
"модуль взаимодействия с базой данных" separate from "бэкенд" and "БД".

Endpoints are plain `def` (not `async def`): FastAPI runs sync endpoints in
a worker threadpool, which is how this service overlaps concurrent DB calls
without depending on SQLAlchemy's greenlet-based asyncio mode (see
database.py for why).
"""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models, schemas
from .database import get_session, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="db-service", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "service": "db-service"}


# --- Teams -----------------------------------------------------------------


@app.post("/teams", response_model=schemas.TeamOut)
def upsert_team(team: schemas.TeamIn, session: Session = Depends(get_session)):
    existing = session.scalar(
        select(models.Team).where(models.Team.opendota_team_id == team.opendota_team_id)
    )
    if existing:
        existing.name = team.name
        existing.tag = team.tag
        session.commit()
        session.refresh(existing)
        return existing

    row = models.Team(
        opendota_team_id=team.opendota_team_id,
        name=team.name,
        tag=team.tag,
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        # Lost a race with a concurrent upsert of the same opendota_team_id.
        session.rollback()
        existing = session.scalar(
            select(models.Team).where(models.Team.opendota_team_id == team.opendota_team_id)
        )
        if not existing:
            raise
        return existing
    session.refresh(row)
    return row


@app.post("/teams/bulk", response_model=list[schemas.TeamOut])
def upsert_teams_bulk(teams: list[schemas.TeamIn], session: Session = Depends(get_session)):
    """Upserts many teams in a single transaction.

    Ingestion refreshes hundreds of teams and matches at once; doing that as
    one HTTP call + one commit per row made a data refresh take tens of
    seconds and hammered SQLite's write lock.
    """
    incoming_ids = [t.opendota_team_id for t in teams]
    existing_rows = session.scalars(
        select(models.Team).where(models.Team.opendota_team_id.in_(incoming_ids))
    ).all()
    by_opendota_id = {row.opendota_team_id: row for row in existing_rows}

    result: list[models.Team] = []
    for team in teams:
        row = by_opendota_id.get(team.opendota_team_id)
        if row:
            row.name = team.name
            row.tag = team.tag
        else:
            row = models.Team(
                opendota_team_id=team.opendota_team_id,
                name=team.name,
                tag=team.tag,
            )
            session.add(row)
            by_opendota_id[team.opendota_team_id] = row
        result.append(row)

    session.commit()
    for row in result:
        session.refresh(row)
    return result


@app.patch("/teams/bulk/stats", response_model=list[schemas.TeamOut])
def update_teams_stats_bulk(
    updates: list[schemas.TeamStatsUpdate], session: Session = Depends(get_session)
):
    rows = session.scalars(
        select(models.Team).where(models.Team.id.in_([u.team_id for u in updates]))
    ).all()
    by_id = {row.id: row for row in rows}

    updated: list[models.Team] = []
    for update in updates:
        row = by_id.get(update.team_id)
        if not row:
            continue
        row.rating = update.rating
        row.recent_form = update.recent_form
        if update.tier is not None:
            row.tier = update.tier
        updated.append(row)

    session.commit()
    for row in updated:
        session.refresh(row)
    return updated


@app.get("/teams", response_model=list[schemas.TeamOut])
def list_teams(session: Session = Depends(get_session)):
    result = session.scalars(select(models.Team).order_by(models.Team.name))
    return list(result.all())


@app.get("/teams/{team_id}", response_model=schemas.TeamOut)
def get_team(team_id: int, session: Session = Depends(get_session)):
    row = session.get(models.Team, team_id)
    if not row:
        raise HTTPException(404, "team not found")
    return row


@app.patch("/teams/{team_id}/rating", response_model=schemas.TeamOut)
def update_team_rating(
    team_id: int, update: schemas.TeamRatingUpdate, session: Session = Depends(get_session)
):
    row = session.get(models.Team, team_id)
    if not row:
        raise HTTPException(404, "team not found")
    row.rating = update.rating
    row.recent_form = update.recent_form
    if update.tier is not None:
        row.tier = update.tier
    session.commit()
    session.refresh(row)
    return row


# --- Matches -----------------------------------------------------------------


@app.post("/matches", response_model=schemas.MatchOut)
def upsert_match(match: schemas.MatchIn, session: Session = Depends(get_session)):
    existing = session.scalar(
        select(models.Match).where(models.Match.opendota_match_id == match.opendota_match_id)
    )
    if existing:
        for field, value in match.model_dump().items():
            setattr(existing, field, value)
        session.commit()
        session.refresh(existing)
        return existing

    row = models.Match(**match.model_dump())
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


@app.post("/matches/bulk", response_model=dict)
def upsert_matches_bulk(matches: list[schemas.MatchIn], session: Session = Depends(get_session)):
    """Upserts many matches in a single transaction (see upsert_teams_bulk)."""
    incoming_ids = [m.opendota_match_id for m in matches]
    existing_rows = session.scalars(
        select(models.Match).where(models.Match.opendota_match_id.in_(incoming_ids))
    ).all()
    by_match_id = {row.opendota_match_id: row for row in existing_rows}

    created = 0
    for match in matches:
        row = by_match_id.get(match.opendota_match_id)
        if row:
            for field, value in match.model_dump().items():
                setattr(row, field, value)
        else:
            row = models.Match(**match.model_dump())
            session.add(row)
            by_match_id[match.opendota_match_id] = row
            created += 1

    session.commit()
    return {"received": len(matches), "created": created}


@app.get("/matches", response_model=list[schemas.MatchOut])
def list_matches(
    limit: int = 100, tier: str | None = None, session: Session = Depends(get_session)
):
    query = select(models.Match)
    if tier:
        query = query.where(models.Match.league_tier == tier)
    result = session.scalars(query.order_by(models.Match.start_time.desc()).limit(limit))
    return list(result.all())


# --- Predictions ---------------------------------------------------------


@app.post("/predictions", response_model=schemas.PredictionOut)
def create_prediction(prediction: schemas.PredictionIn, session: Session = Depends(get_session)):
    row = models.Prediction(**prediction.model_dump())
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


@app.get("/predictions", response_model=list[schemas.PredictionOut])
def list_predictions(
    limit: int = 50, user_id: int | None = None, session: Session = Depends(get_session)
):
    query = select(models.Prediction)
    if user_id is not None:
        query = query.where(models.Prediction.user_id == user_id)
    result = session.scalars(
        query.order_by(models.Prediction.created_at.desc()).limit(limit)
    )
    return list(result.all())


# --- Users -----------------------------------------------------------------


@app.post("/users", response_model=schemas.UserOut)
def create_user(user: schemas.UserIn, session: Session = Depends(get_session)):
    existing = session.scalar(select(models.User).where(models.User.username == user.username))
    if existing:
        raise HTTPException(409, "username already exists")
    row = models.User(**user.model_dump())
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


@app.get("/users/by-username/{username}", response_model=schemas.UserOut)
def get_user_by_username(username: str, session: Session = Depends(get_session)):
    row = session.scalar(select(models.User).where(models.User.username == username))
    if not row:
        raise HTTPException(404, "user not found")
    return row


@app.patch("/users/{user_id}/totp", response_model=schemas.UserOut)
def update_user_totp(
    user_id: int, update: schemas.UserTotpUpdate, session: Session = Depends(get_session)
):
    row = session.get(models.User, user_id)
    if not row:
        raise HTTPException(404, "user not found")
    if update.totp_secret is not None:
        row.totp_secret = update.totp_secret
    if update.totp_enabled is not None:
        row.totp_enabled = update.totp_enabled
    session.commit()
    session.refresh(row)
    return row
