"""FastAPI app: the human-in-the-loop step between the agent's recommendation and the field crews.

    POST  /api/dispatches/proposals        agent submits its sheet          -> proposal_id, PENDING_REVIEW
    POST  /api/dispatches/approve          dispatcher approves chosen stops -> signed dispatch_id, APPROVED
    GET   /api/dispatches/active           crews / map read approved stops and wellness teams
    PATCH /api/dispatches/{id}/override    midday triage moves a stop and logs why
    POST  /api/dispatches/{id}/close       stand a dispatch down (leaves the active list)

Storage (DISPATCH_STORE): `sqlite` (default; DISPATCH_DB, else .data/dispatches.db) for local runs, `firestore`
(FIRESTORE_DATABASE, default heat-dispatch) on Cloud Run. Run locally: make api-local. Deploy: make deploy-api.
No authentication in the app: Cloud Run IAM decides who may call it (deployed with --no-allow-unauthenticated).
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .models import ApproveIn, CloseIn, OverrideIn, ProposalIn
from .repos import FirestoreRepo, Repo, SqliteRepo
from .signing import Signer
from .store import Conflict, Invalid, NotFound, Store

DEFAULT_DB = Path(__file__).resolve().parents[2] / ".data" / "dispatches.db"


def repo_from_env() -> Repo:
    kind = os.environ.get("DISPATCH_STORE", "sqlite").strip().lower()
    if kind == "firestore":
        return FirestoreRepo(os.environ.get("GOOGLE_CLOUD_PROJECT"),
                             os.environ.get("FIRESTORE_DATABASE", "heat-dispatch").strip())
    if kind == "sqlite":
        return SqliteRepo(os.environ.get("DISPATCH_DB") or DEFAULT_DB)
    raise ValueError(f"DISPATCH_STORE must be 'sqlite' or 'firestore', not {kind!r}")


def create_app(store: Store | None = None) -> FastAPI:
    store = store or Store(repo_from_env(), Signer())
    app = FastAPI(title="Chicago Heat Dispatch API", version="1.0")

    for exc, code in ((NotFound, 404), (Conflict, 409), (Invalid, 422)):
        app.add_exception_handler(exc, lambda _req, e, code=code: JSONResponse({"detail": str(e)}, status_code=code))

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.post("/api/dispatches/proposals", status_code=201)
    def submit_proposal(p: ProposalIn) -> dict:
        return store.create_proposal(p)

    @app.post("/api/dispatches/approve", status_code=201)
    def approve(a: ApproveIn) -> dict:
        return store.approve(a)

    @app.get("/api/dispatches/active")
    def active() -> dict:
        items = store.active()
        return {"count": len(items), "dispatches": items}

    @app.patch("/api/dispatches/{dispatch_id}/override")
    def override(dispatch_id: str, o: OverrideIn) -> dict:
        return store.override(dispatch_id, o)

    @app.post("/api/dispatches/{dispatch_id}/close")
    def close(dispatch_id: str, c: CloseIn) -> dict:
        return store.close(dispatch_id, c)

    return app


app = create_app()
