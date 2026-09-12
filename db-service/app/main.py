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

    row = models.Team(**team.model_dump())
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


@app.get("/matches", response_model=list[schemas.MatchOut])
def list_matches(limit: int = 100, session: Session = Depends(get_session)):
    result = session.scalars(
        select(models.Match).order_by(models.Match.start_time.desc()).limit(limit)
    )
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
def list_predictions(limit: int = 50, session: Session = Depends(get_session)):
    result = session.scalars(
        select(models.Prediction).order_by(models.Prediction.created_at.desc()).limit(limit)
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
