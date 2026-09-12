"""Network module (course requirement §2.5): async HTTP client the backend
uses to reach the DB interaction module over the network instead of talking
to a database directly.
"""

import httpx

from ..core.config import settings


class DbServiceClient:
    def __init__(self, base_url: str | None = None):
        self._base_url = base_url or settings.db_service_url

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._base_url, timeout=30.0)

    async def upsert_team(
        self,
        opendota_team_id: int,
        name: str,
        tag: str | None = None,
        seed_rating: float | None = None,
    ) -> dict:
        async with self._client() as c:
            r = await c.post(
                "/teams",
                json={
                    "opendota_team_id": opendota_team_id,
                    "name": name,
                    "tag": tag,
                    "seed_rating": seed_rating,
                },
            )
            r.raise_for_status()
            return r.json()

    async def list_teams(self) -> list[dict]:
        async with self._client() as c:
            r = await c.get("/teams")
            r.raise_for_status()
            return r.json()

    async def get_team(self, team_id: int) -> dict:
        async with self._client() as c:
            r = await c.get(f"/teams/{team_id}")
            r.raise_for_status()
            return r.json()

    async def update_team_rating(self, team_id: int, rating: float, recent_form: float) -> dict:
        async with self._client() as c:
            r = await c.patch(
                f"/teams/{team_id}/rating", json={"rating": rating, "recent_form": recent_form}
            )
            r.raise_for_status()
            return r.json()

    async def upsert_match(self, match: dict) -> dict:
        async with self._client() as c:
            r = await c.post("/matches", json=match)
            r.raise_for_status()
            return r.json()

    async def list_matches(self, limit: int = 100) -> list[dict]:
        async with self._client() as c:
            r = await c.get("/matches", params={"limit": limit})
            r.raise_for_status()
            return r.json()

    async def create_prediction(self, prediction: dict) -> dict:
        async with self._client() as c:
            r = await c.post("/predictions", json=prediction)
            r.raise_for_status()
            return r.json()

    async def list_predictions(self, limit: int = 50) -> list[dict]:
        async with self._client() as c:
            r = await c.get("/predictions", params={"limit": limit})
            r.raise_for_status()
            return r.json()

    async def create_user(self, username: str, email: str, hashed_password: str) -> dict:
        async with self._client() as c:
            r = await c.post(
                "/users",
                json={"username": username, "email": email, "hashed_password": hashed_password},
            )
            r.raise_for_status()
            return r.json()

    async def get_user_by_username(self, username: str) -> dict | None:
        async with self._client() as c:
            r = await c.get(f"/users/by-username/{username}")
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()

    async def update_user_totp(
        self, user_id: int, totp_secret: str | None = None, totp_enabled: bool | None = None
    ) -> dict:
        async with self._client() as c:
            r = await c.patch(
                f"/users/{user_id}/totp",
                json={"totp_secret": totp_secret, "totp_enabled": totp_enabled},
            )
            r.raise_for_status()
            return r.json()


db_client = DbServiceClient()
