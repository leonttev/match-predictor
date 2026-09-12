"""Network module: async HTTP client to the Go prediction-engine (functional
module, course requirement §2.6)."""

import httpx

from ..core.config import settings


class PredictionEngineClient:
    def __init__(self, base_url: str | None = None):
        self._base_url = base_url or settings.prediction_engine_url

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._base_url, timeout=15.0)

    async def compute_ratings(
        self, matches: list[dict], initial_ratings: dict[str, float] | None = None
    ) -> dict:
        async with self._client() as c:
            r = await c.post(
                "/ratings",
                json={"matches": matches, "initial_ratings": initial_ratings or {}},
            )
            r.raise_for_status()
            return r.json()

    async def predict(
        self, team_a_rating: float, team_a_form: float, team_b_rating: float, team_b_form: float
    ) -> dict:
        async with self._client() as c:
            r = await c.post(
                "/predict",
                json={
                    "team_a_rating": team_a_rating,
                    "team_a_form": team_a_form,
                    "team_b_rating": team_b_rating,
                    "team_b_form": team_b_form,
                },
            )
            r.raise_for_status()
            return r.json()


prediction_client = PredictionEngineClient()
