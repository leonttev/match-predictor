"""Backend (course requirement §2.4): authorization/authentication + 2FA,
async orchestration across the DB module and the functional module, and
the data-ingestion pipeline."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import auth, ingest, matches, predict, teams

app = FastAPI(title="match-predictor backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(teams.router)
app.include_router(matches.router)
app.include_router(predict.router)
app.include_router(ingest.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "backend"}
