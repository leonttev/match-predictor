from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..core.deps import require_full_auth
from ..network.db_client import db_client
from ..network.prediction_client import prediction_client

router = APIRouter(prefix="/predict", tags=["predict"])


class PredictRequest(BaseModel):
    team_a_id: int
    team_b_id: int


@router.post("")
async def predict_match(req: PredictRequest, _: str = Depends(require_full_auth)):
    if req.team_a_id == req.team_b_id:
        raise HTTPException(400, "team_a_id and team_b_id must differ")

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
