from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..core.deps import require_full_auth
from ..network.db_client import db_client
from ..network.prediction_client import prediction_client

router = APIRouter(prefix="/predict", tags=["predict"])


class PredictRequest(BaseModel):
    team_a_id: int
    team_b_id: int


async def _current_user(username: str) -> dict:
    user = await db_client.get_user_by_username(username)
    if not user:
        raise HTTPException(401, "user no longer exists — please log in again")
    return user


@router.post("")
async def predict_match(req: PredictRequest, username: str = Depends(require_full_auth)):
    if req.team_a_id == req.team_b_id:
        raise HTTPException(400, "team_a_id and team_b_id must differ")

    user = await _current_user(username)
    team_a = await db_client.get_team(req.team_a_id)
    team_b = await db_client.get_team(req.team_b_id)

    result = await prediction_client.predict(
        team_a_rating=team_a["rating"],
        team_a_form=team_a["recent_form"],
        team_a_tier=team_a["tier"],
        team_b_rating=team_b["rating"],
        team_b_form=team_b["recent_form"],
        team_b_tier=team_b["tier"],
    )

    stored = await db_client.create_prediction(
        {
            "user_id": user["id"],
            "team_a_id": team_a["id"],
            "team_b_id": team_b["id"],
            "team_a_win_prob": result["team_a_win_prob"],
        }
    )

    return {
        "team_a": {"id": team_a["id"], "name": team_a["name"], "tier": team_a["tier"]},
        "team_b": {"id": team_b["id"], "name": team_b["name"], "tier": team_b["tier"]},
        "team_a_win_prob": result["team_a_win_prob"],
        "elo_component": result["elo_component"],
        "form_component": result["form_component"],
        "tier_adjustment": result["tier_adjustment"],
        "prediction_id": stored["id"],
    }


@router.get("/history")
async def prediction_history(limit: int = 50, username: str = Depends(require_full_auth)):
    """The calling user's own past predictions, newest first."""
    user = await _current_user(username)
    predictions, teams = (
        await db_client.list_predictions(limit=limit, user_id=user["id"]),
        await db_client.list_teams(),
    )
    team_names = {t["id"]: t["name"] for t in teams}

    return [
        {
            "id": p["id"],
            "team_a_name": team_names.get(p["team_a_id"], "?"),
            "team_b_name": team_names.get(p["team_b_id"], "?"),
            "team_a_win_prob": p["team_a_win_prob"],
            "created_at": p["created_at"],
        }
        for p in predictions
    ]
