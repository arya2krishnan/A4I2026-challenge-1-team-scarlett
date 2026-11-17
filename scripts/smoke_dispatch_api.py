#!/usr/bin/env python3
"""End-to-end check of the dispatch approval API against a running server (Cloud Run or `make api-local`).

    python scripts/smoke_dispatch_api.py                    # DISPATCH_API_URL from .env, gcloud identity token
    python scripts/smoke_dispatch_api.py --url http://127.0.0.1:8080 --no-auth

Walks the whole lifecycle (propose -> approve -> active -> override -> close), the error codes, and two concurrent
approvals of one proposal (exactly one may win). Everything it creates is tagged submitted_by=smoke-test and CLOSED
at the end, so it never leaves a test dispatch on the field crews' active list. Exit code 0 = all checks passed.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

Call = Callable[[str, str, Any], "tuple[int, Any]"]
TAG = "smoke-test"

PROPOSAL = {
    "forecast_high_f": 97,
    "submitted_by": TAG,
    "hydration_stops": [
        {"stop": 1, "latitude": 41.7796, "longitude": -87.6444, "neighborhood": "ENGLEWOOD"},
        {"stop": 2, "latitude": 41.8940, "longitude": -87.7650, "neighborhood": "AUSTIN"},
        {"stop": 3, "latitude": 41.8430, "longitude": -87.7140, "neighborhood": "SOUTH LAWNDALE"},
    ],
    "wellness_teams": [{"team": 1, "tract_geo_id": "17031681000", "latitude": 41.78, "longitude": -87.65}],
    "dispatch_sheet_markdown": "# smoke test (not a real plan)",
    "equity_audit_ran": False,
}


class Check:
    def __init__(self, log: Callable[[str], None]) -> None:
        self.log, self.failures = log, []

    def __call__(self, ok: bool, what: str, detail: Any = "") -> bool:
        self.log(f"  {'PASS' if ok else 'FAIL'}  {what}" + ("" if ok else f"  -> {detail}"))
        if not ok:
            self.failures.append(what)
        return ok


def run_smoke(call: Call, log: Callable[[str], None] = print) -> list[str]:
    """Returns the names of failed checks (empty = success)."""
    check, created = Check(log), []

    def propose() -> str | None:
        st, j = call("POST", "/api/dispatches/proposals", PROPOSAL)
        return j.get("proposal_id") if check(st == 201 and j.get("status") == "PENDING_REVIEW",
                                             "proposal saved as PENDING_REVIEW", (st, j)) else None

    def approve(pid: str, **extra: Any) -> tuple[int, Any]:
        return call("POST", "/api/dispatches/approve",
                    {"proposal_id": pid, "approved_by": f"{TAG} officer", "approved_stops": [1, 2], **extra})

    try:
        st, j = call("GET", "/healthz", None)
        check(st == 200, "healthz", (st, j))

        st, j = call("POST", "/api/dispatches/proposals",
                     {**PROPOSAL, "hydration_stops": [{"stop": 1, "latitude": 40.71, "longitude": -74.0}]})
        check(st == 422, "proposal outside Chicago rejected (422)", (st, j))

        pid = propose()
        if not pid:
            return check.failures
        st, j = approve(pid, approved_stops=[1, 9])
        check(st == 422, "approval naming an unknown stop rejected (422)", (st, j))

        st, d = approve(pid, overrides={"2": {"latitude": 41.8950, "longitude": -87.7600, "reason": "smoke: hydrant"}})
        if not check(st == 201 and d.get("status") == "APPROVED", "approval returns APPROVED dispatch", (st, d)):
            return check.failures
        did = d["dispatch_id"]
        created.append(did)
        check([s["stop"] for s in d["stops"]] == [1, 2], "only approved stops kept", d["stops"])
        check(len(d.get("signature", "")) == 64 and d.get("signature_alg") == "HMAC-SHA256", "dispatch is signed", d)
        check(d["stops"][1]["latitude"] == 41.8950 and d["stops"][1]["original_latitude"] == 41.8940,
              "approval override applied, original kept", d["stops"][1])

        st, j = approve(pid)
        check(st == 409, "second approval of same proposal refused (409)", (st, j))

        st, j = call("GET", "/api/dispatches/active", None)
        check(st == 200 and did in [x["dispatch_id"] for x in j.get("dispatches", [])], "dispatch is active", (st, j))

        body = {"stop": 2, "latitude": 41.8960, "longitude": -87.7660, "reason": "smoke: intersection blocked",
                "requested_by": f"{TAG} dispatcher"}
        st, o = call("PATCH", f"/api/dispatches/{did}/override", body)
        check(st == 200 and o.get("revision") == 2 and o.get("signature") != d["signature"]
              and [x["stage"] for x in o.get("overrides", [])] == ["approval", "triage"],
              "midday override moves stop, logs reason, re-signs", (st, o))
        st, j = call("PATCH", f"/api/dispatches/{did}/override", {**body, "stop": 3})
        check(st == 422, "override of a stop not in the dispatch rejected (422)", (st, j))
        st, j = call("PATCH", "/api/dispatches/disp-doesnotexist/override", body)
        check(st == 404, "override of unknown dispatch is 404", (st, j))

        # Two dispatchers approve the same proposal at once: the transaction must let exactly one through.
        pid2 = propose()
        if pid2:
            with ThreadPoolExecutor(2) as ex:
                results = list(ex.map(lambda _: approve(pid2), range(2)))
            codes = sorted(st for st, _ in results)
            created += [j["dispatch_id"] for st, j in results if st == 201]
            check(codes == [201, 409], "concurrent approvals: exactly one wins", codes)

        st, c = call("POST", f"/api/dispatches/{did}/close", {"closed_by": TAG, "reason": "smoke test cleanup"})
        check(st == 200 and c.get("status") == "CLOSED", "close stands the dispatch down", (st, c))
        st, j = call("GET", "/api/dispatches/active", None)
        check(did not in [x["dispatch_id"] for x in j.get("dispatches", [])], "closed dispatch left the active list", j)
        st, j = call("PATCH", f"/api/dispatches/{did}/override", body)
        check(st == 409, "override of a closed dispatch refused (409)", (st, j))
    finally:
        for did in created:   # never leave smoke dispatches active, even after a failure
            call("POST", f"/api/dispatches/{did}/close", {"closed_by": TAG, "reason": "smoke test cleanup"})
    return check.failures


def http_caller(base: str, token: str | None) -> Call:
    def call(method: str, path: str, body: Any) -> tuple[int, Any]:
        req = urllib.request.Request(base.rstrip("/") + path, method=method,
                                     data=None if body is None else json.dumps(body).encode())
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, {"raw": raw.decode(errors="replace")[:300]}
    return call


def _env_url() -> str:
    env = Path(__file__).resolve().parents[1] / ".env"
    if env.is_file():
        for line in env.read_text().splitlines():
            if line.startswith("DISPATCH_API_URL="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("DISPATCH_API_URL", "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=None, help="API base URL (default: DISPATCH_API_URL in .env)")
    ap.add_argument("--no-auth", action="store_true", help="do not send a gcloud identity token (local server)")
    args = ap.parse_args()
    url = args.url or _env_url()
    if not url:
        print("No URL: pass --url or run `make deploy-api` (it saves DISPATCH_API_URL to .env).", file=sys.stderr)
        return 2
    token = None if args.no_auth else subprocess.run(
        ["gcloud", "auth", "print-identity-token"], check=True, capture_output=True, text=True).stdout.strip()
    print(f">> smoke-testing {url}")
    failures = run_smoke(http_caller(url, token))
    print(f">> {'ALL PASSED' if not failures else f'{len(failures)} FAILED: ' + '; '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
