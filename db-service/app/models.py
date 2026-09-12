from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opendota_team_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    tag: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # A team with no observed matches sits at the prediction engine's base
    # rating for an unknown tier (see baseRatingByTier there): it must not
    # default into the tier-1 band just because nothing is known about it.
    rating: Mapped[float] = mapped_column(Float, default=250.0)
    recent_form: Mapped[float] = mapped_column(Float, default=0.5)
    # Best league tier this team has been observed playing in ("tier1".."tier3",
    # or "unknown" when it hasn't appeared in any ingested match). Teams are
    # ranked tier-first, so a tier2 team never outranks a tier1 one.
    tier: Mapped[str] = mapped_column(String(10), default="unknown")


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opendota_match_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    radiant_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    dire_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    radiant_win: Mapped[bool] = mapped_column(Boolean)
    start_time: Mapped[int] = mapped_column(BigInteger)
    league_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    league_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    league_tier: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    team_a_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    team_b_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    team_a_win_prob: Mapped[float] = mapped_column(Float)
    model_version: Mapped[str] = mapped_column(String(50), default="elo-v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(300))
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
