"""Dispatch approval API: proposal -> approval -> active list -> midday override -> close.

Runs on SQLite in tmp_path. If FIRESTORE_EMULATOR_HOST is set (gcloud emulators firestore start), every API test
also runs against Firestore, the backend used on Cloud Run.
"""
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dispatch_api.app import create_app, repo_from_env
from dispatch_api.models import CHICAGO_BOX
from dispatch_api.repos import SqliteRepo
from dispatch_api.signing import Signer
from dispatch_api.store import Store

ROOT = Path(__file__).resolve().parents[1]

PROPOSAL = {  # the shape build_dispatch_plan returns, plus the forecast it was built for
    "forecast_high_f": 98,
    "hydration_stops": [
        {"stop": 1, "latitude": 41.7796, "longitude": -87.6444, "neighborhood": "ENGLEWOOD", "predicted_offset_f": 1.4},
        {"stop": 2, "latitude": 41.8940, "longitude": -87.7650, "neighborhood": "AUSTIN", "predicted_offset_f": 1.2},
        {"stop": 3, "latitude": 41.8430, "longitude": -87.7140, "neighborhood": "SOUTH LAWNDALE"},
    ],
    "wellness_teams": [{"team": 1, "tract_geo_id": "17031681000", "latitude": 41.78, "longitude": -87.65},
                       {"team": 2, "tract_geo_id": "17031251500", "latitude": 41.89, "longitude": -87.76}],
    "dispatch_sheet_markdown": "# Heat dispatch sheet",
    "equity_audit_ran": True,
    "map": {"markers": []},
}
BACKENDS = ["sqlite"] + (["firestore"] if os.environ.get("FIRESTORE_EMULATOR_HOST") else [])


@pytest.fixture
def signer():
    return Signer(b"test-key")


@pytest.fixture(params=BACKENDS)
def store(request, tmp_path, signer):
    if request.param == "sqlite":
        return Store(SqliteRepo(tmp_path / "d.db"), signer)
    from dispatch_api.repos import FirestoreRepo
    return Store(FirestoreRepo("test-project", f"(default)"), signer)


@pytest.fixture
def client(store):
    return TestClient(create_app(store))


def _propose(client):
    r = client.post("/api/dispatches/proposals", json=PROPOSAL)
    assert r.status_code == 201, r.text
    return r.json()["proposal_id"]


def _approve(client, pid, **extra):
    body = {"proposal_id": pid, "approved_by": "Officer Miller", "approved_stops": [1, 2], **extra}
    return client.post("/api/dispatches/approve", json=body)


def _active_ids(client):
    return [d["dispatch_id"] for d in client.get("/api/dispatches/active").json()["dispatches"]]


# ---- proposals ---------------------------------------------------------------------------------------------------
def test_proposal_is_pending_review(client):
    r = client.post("/api/dispatches/proposals", json=PROPOSAL)
    assert r.status_code == 201
    j = r.json()
    assert j["status"] == "PENDING_REVIEW" and j["proposal_id"].startswith("prop-")
    assert j["hydration_stops"] == 3 and j["wellness_teams"] == 2 and j["equity_audit_ran"] is True
    assert j["proposal_id"] not in _active_ids(client)


def test_proposal_validation(client):
    bad = {**PROPOSAL, "hydration_stops": [{"stop": 1, "latitude": 40.71, "longitude": -74.0}]}
    assert client.post("/api/dispatches/proposals", json=bad).status_code == 422          # outside Chicago
    dup = {**PROPOSAL, "hydration_stops": PROPOSAL["hydration_stops"][:1] * 2}
    assert client.post("/api/dispatches/proposals", json=dup).status_code == 422          # duplicate stop numbers
    assert client.post("/api/dispatches/proposals", json={**PROPOSAL, "hydration_stops": []}).status_code == 422
    no_fc = {k: v for k, v in PROPOSAL.items() if k != "forecast_high_f"}
    assert client.post("/api/dispatches/proposals", json=no_fc).status_code == 422


# ---- approval ----------------------------------------------------------------------------------------------------
def test_approve_returns_signed_dispatch_with_only_approved_stops(client, signer):
    pid = _propose(client)
    r = _approve(client, pid, overrides={"2": {"latitude": 41.8950, "longitude": -87.7600, "reason": "hydrant work"}})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["status"] == "APPROVED" and d["dispatch_id"].startswith("disp-") and d["revision"] == 1
    assert d["approved_by"] == "Officer Miller" and d["forecast_high_f"] == 98
    assert [s["stop"] for s in d["stops"]] == [1, 2]
    moved = d["stops"][1]
    assert (moved["latitude"], moved["longitude"]) == (41.8950, -87.7600)
    assert (moved["original_latitude"], moved["original_longitude"]) == (41.8940, -87.7650)
    assert moved["neighborhood"] == "AUSTIN"                       # agent fields carried through
    assert [t["team"] for t in d["wellness_teams"]] == [1, 2]      # all teams by default
    assert [o["stage"] for o in d["overrides"]] == ["approval"] and d["overrides"][0]["reason"] == "hydrant work"
    assert d["signature_alg"] == "HMAC-SHA256" and signer.verify(d)
    tampered = {**d, "stops": [{**d["stops"][0], "latitude": 41.9}, d["stops"][1]]}
    assert not signer.verify(tampered)
    assert not Signer(b"other-key").verify(d)


def test_approve_errors(client):
    assert _approve(client, "prop-missing").status_code == 404
    pid = _propose(client)
    assert _approve(client, pid, approved_stops=[1, 9]).status_code == 422
    assert _approve(client, pid, approved_stops=[]).status_code == 422
    assert _approve(client, pid, approved_teams=[5]).status_code == 422
    assert _approve(client, pid, overrides={"3": {"latitude": 41.8, "longitude": -87.7, "reason": "x"}}).status_code == 422
    assert _approve(client, pid, overrides={"1": {"latitude": 42.5, "longitude": -87.7, "reason": "x"}}).status_code == 422
    assert _approve(client, pid, overrides={"1": {"latitude": 41.8, "longitude": -87.7, "reason": ""}}).status_code == 422
    assert _approve(client, pid, approved_by="").status_code == 422
    assert _approve(client, pid).status_code == 201                 # failed attempts left it pending
    assert _approve(client, pid).status_code == 409                 # no double approval


def test_concurrent_approvals_only_one_wins(client):
    pid = _propose(client)
    with ThreadPoolExecutor(4) as ex:
        codes = sorted(r.status_code for r in ex.map(lambda _: _approve(client, pid), range(4)))
    assert codes == [201, 409, 409, 409]
    assert len(_active_ids(client)) == 1


# ---- active ------------------------------------------------------------------------------------------------------
def test_active_lists_approved_dispatches_with_teams(client):
    _propose(client)                                                 # pending: not active
    first = _approve(client, _propose(client), approved_teams=[2]).json()["dispatch_id"]
    second = _approve(client, _propose(client), approved_stops=[3]).json()["dispatch_id"]
    j = client.get("/api/dispatches/active").json()
    assert j["count"] == 2 and [d["dispatch_id"] for d in j["dispatches"]] == [first, second]   # oldest first
    d = j["dispatches"][0]
    assert d["forecast_high_f"] == 98 and d["overrides"] == []
    assert [t["team"] for t in d["wellness_teams"]] == [2]


# ---- midday override ---------------------------------------------------------------------------------------------
def test_override_moves_stop_logs_reason_and_resigns(client, signer):
    d0 = _approve(client, _propose(client)).json()
    did = d0["dispatch_id"]
    body = {"stop": 2, "latitude": 41.8960, "longitude": -87.7660, "reason": "intersection blocked by crash",
            "requested_by": "Dispatcher Ruiz"}
    r = client.patch(f"/api/dispatches/{did}/override", json=body)
    assert r.status_code == 200, r.text
    d = r.json()
    s2 = next(s for s in d["stops"] if s["stop"] == 2)
    assert (s2["latitude"], s2["longitude"]) == (41.8960, -87.7660)
    assert (s2["original_latitude"], s2["original_longitude"]) == (41.8940, -87.7650)
    assert s2["override_reason"] == "intersection blocked by crash"
    assert next(s for s in d["stops"] if s["stop"] == 1) == d0["stops"][0]       # other stops untouched
    assert d["revision"] == 2 and d["signature"] != d0["signature"] and signer.verify(d)
    log = d["overrides"]
    assert len(log) == 1 and log[0]["stage"] == "triage" and log[0]["requested_by"] == "Dispatcher Ruiz"
    assert (log[0]["old_latitude"], log[0]["new_latitude"]) == (41.8940, 41.8960)

    # a second move keeps the ORIGINAL point, not the intermediate one
    d2 = client.patch(f"/api/dispatches/{did}/override", json={**body, "latitude": 41.8970, "reason": "still blocked"}).json()
    s2 = next(s for s in d2["stops"] if s["stop"] == 2)
    assert s2["original_latitude"] == 41.8940 and s2["latitude"] == 41.8970 and d2["revision"] == 3
    assert [o["old_latitude"] for o in d2["overrides"]] == [41.8940, 41.8960]
    assert client.get("/api/dispatches/active").json()["dispatches"][0]["revision"] == 3


def test_override_errors(client):
    body = {"stop": 1, "latitude": 41.8, "longitude": -87.7, "reason": "blocked", "requested_by": "R"}
    assert client.patch("/api/dispatches/disp-nope/override", json=body).status_code == 404
    did = _approve(client, _propose(client)).json()["dispatch_id"]
    assert client.patch(f"/api/dispatches/{did}/override", json={**body, "stop": 3}).status_code == 422  # not approved
    assert client.patch(f"/api/dispatches/{did}/override", json={**body, "latitude": 43.0}).status_code == 422
    assert client.patch(f"/api/dispatches/{did}/override", json={**body, "reason": ""}).status_code == 422
    assert client.patch(f"/api/dispatches/{did}/override", json={**body, "requested_by": ""}).status_code == 422


# ---- close -------------------------------------------------------------------------------------------------------
def test_close_removes_from_active_and_freezes_dispatch(client):
    did = _approve(client, _propose(client)).json()["dispatch_id"]
    r = client.post(f"/api/dispatches/{did}/close", json={"closed_by": "Officer Miller", "reason": "heat day over"})
    assert r.status_code == 200 and r.json()["status"] == "CLOSED" and r.json()["close_reason"] == "heat day over"
    assert did not in _active_ids(client)
    body = {"stop": 1, "latitude": 41.8, "longitude": -87.7, "reason": "x", "requested_by": "R"}
    assert client.patch(f"/api/dispatches/{did}/override", json=body).status_code == 409
    assert client.post(f"/api/dispatches/{did}/close", json={"closed_by": "x", "reason": "y"}).status_code == 409
    assert client.post("/api/dispatches/disp-nope/close", json={"closed_by": "x", "reason": "y"}).status_code == 404
    assert client.post(f"/api/dispatches/{did}/close", json={"closed_by": "", "reason": "y"}).status_code == 422


def test_data_survives_a_new_app_instance(tmp_path, signer):
    """A restart (or a second instance) sees the same dispatches: nothing lives only in memory."""
    a = TestClient(create_app(Store(SqliteRepo(tmp_path / "d.db"), signer)))
    did = _approve(a, _propose(a)).json()["dispatch_id"]
    b = TestClient(create_app(Store(SqliteRepo(tmp_path / "d.db"), signer)))
    assert _active_ids(b) == [did]


# ---- the live smoke test, run here against an in-process server -------------------------------------------------
def test_smoke_script_passes_against_in_process_api(client):
    from smoke_dispatch_api import run_smoke

    def call(method, path, body):
        r = client.request(method, path, json=body)
        return r.status_code, r.json()

    lines = []
    assert run_smoke(call, lines.append) == [], "\n".join(lines)
    assert len(lines) >= 15 and all("PASS" in ln for ln in lines)
    assert client.get("/api/dispatches/active").json()["count"] == 0     # cleaned up after itself


def test_smoke_script_reports_failures(client):
    from smoke_dispatch_api import run_smoke

    def broken(method, path, body):                                       # a server that 500s everything
        return 500, {"detail": "boom"}

    assert run_smoke(broken, lambda _: None)                              # non-empty list of failures


# ---- configuration and deploy files ------------------------------------------------------------------------------
def test_repo_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DISPATCH_STORE", "sqlite")
    monkeypatch.setenv("DISPATCH_DB", str(tmp_path / "x.db"))
    assert isinstance(repo_from_env(), SqliteRepo)
    monkeypatch.setenv("DISPATCH_STORE", "postgres")
    with pytest.raises(ValueError):
        repo_from_env()


def test_signer_requires_key_on_cloud_run(monkeypatch):
    monkeypatch.delenv("DISPATCH_SIGNING_KEY", raising=False)
    monkeypatch.setenv("K_SERVICE", "heat-dispatch-api")
    with pytest.raises(RuntimeError):
        Signer()
    monkeypatch.setenv("DISPATCH_SIGNING_KEY", "abc")
    d = {"dispatch_id": "d", "proposal_id": "p", "approved_by": "a", "approved_at": "t", "revision": 1,
         "stops": [], "wellness_teams": []}
    assert Signer().sign(d) == Signer(b"abc").sign(d)


def test_chicago_box_matches_agent():
    src = (ROOT / "agent/heat_dispatch/places.py").read_text()   # read, not imported: importing pulls in ADK
    m = re.search(r"CHICAGO_BOX = \(([^)]*)\)", src)
    assert tuple(float(x) for x in m.group(1).split(",")) == CHICAGO_BOX


def test_dockerfile_and_requirements_cover_the_app():
    docker = (ROOT / "api/Dockerfile").read_text()
    assert "dispatch_api.app:app" in docker and "${PORT:-8080}" in docker and "DISPATCH_STORE=firestore" in docker
    assert "USER app" in docker
    reqs = (ROOT / "api/requirements.txt").read_text()
    for pkg in ("fastapi", "pydantic", "uvicorn", "google-cloud-firestore"):
        assert pkg in reqs
    assert "-r api/requirements.txt" in (ROOT / "requirements-dev.txt").read_text()


def test_deploy_script_is_valid_and_private():
    script = ROOT / "scripts/deploy_api.sh"
    assert subprocess.run(["bash", "-n", str(script)], capture_output=True).returncode == 0
    s = script.read_text()
    assert "--no-allow-unauthenticated" in s and "--source \"$ROOT/api\"" in s
    assert "--set-secrets \"DISPATCH_SIGNING_KEY=" in s                    # key from Secret Manager, not env text
    assert "DISPATCH_STORE=firestore" in s and "roles/datastore.user" in s
    assert "save_env DISPATCH_API_URL" in s
    mk = (ROOT / "Makefile").read_text()
    assert "deploy-api:" in mk and "smoke-api:" in mk
