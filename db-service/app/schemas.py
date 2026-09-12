from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TeamIn(BaseModel):
    opendota_team_id: int
    name: str
    tag: str | None = None
    # Prior strength from an external source (OpenDota's own long-history
    # rating), used as the Elo starting point instead of a flat default —
    # see db-service/app/main.py::upsert_team for how it's applied.
    seed_rating: float | None = None


class TeamOut(TeamIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    rating: float
    recent_form: float
    tier: str


class TeamRatingUpdate(BaseModel):
    rating: float
    recent_form: float
    tier: str | None = None


class TeamStatsUpdate(TeamRatingUpdate):
    team_id: int


class MatchIn(BaseModel):
    opendota_match_id: int
    radiant_team_id: int
    dire_team_id: int
    radiant_win: bool
    start_time: int
    league_name: str | None = None
    league_id: int | None = None
    league_tier: str | None = None


class MatchOut(MatchIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class PredictionIn(BaseModel):
    team_a_id: int
    team_b_id: int
    team_a_win_prob: float
    model_version: str = "elo-v1"


class PredictionOut(PredictionIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


class UserIn(BaseModel):
    username: str
    email: str
    hashed_password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    email: str
    hashed_password: str
    totp_secret: str | None
    totp_enabled: bool


class UserTotpUpdate(BaseModel):
    totp_secret: str | None = None
    totp_enabled: bool | None = None
