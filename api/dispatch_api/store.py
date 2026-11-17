"""The dispatch lifecycle, independent of the database: PENDING_REVIEW -> APPROVED -> (overrides) -> CLOSED.

Every state change runs inside repo.run(...) and reads before it writes, so it is atomic on SQLite and Firestore.
"""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from .models import ApproveIn, CloseIn, OverrideIn, ProposalIn
from .repos import Repo, Tx
from .signing import ALG, Signer

PENDING, APPROVED, CLOSED = "PENDING_REVIEW", "APPROVED", "CLOSED"
PROPOSALS, DISPATCHES = "proposals", "dispatches"


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


class Invalid(Exception):
    pass


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds")


class Store:
    def __init__(self, repo: Repo, signer: Signer) -> None:
        self.repo, self.signer = repo, signer

    # ---- proposals ------------------------------------------------------------------------------------------------
    def create_proposal(self, p: ProposalIn) -> dict[str, Any]:
        pid, now = f"prop-{uuid.uuid4().hex[:12]}", _now()
        doc = {"proposal_id": pid, "status": PENDING, "submitted_by": p.submitted_by, "created_at": now,
               "body": p.model_dump(mode="json")}
        self.repo.run(lambda tx: tx.set(PROPOSALS, pid, doc))
        return {"proposal_id": pid, "status": PENDING, "created_at": now,
                "hydration_stops": len(p.hydration_stops), "wellness_teams": len(p.wellness_teams),
                "equity_audit_ran": p.equity_audit_ran}

    # ---- approval -------------------------------------------------------------------------------------------------
    def approve(self, a: ApproveIn) -> dict[str, Any]:
        def fn(tx: Tx) -> dict[str, Any]:
            prop = tx.get(PROPOSALS, a.proposal_id)
            if prop is None:
                raise NotFound(f"proposal {a.proposal_id} not found")
            if prop["status"] != PENDING:
                raise Conflict(f"proposal {a.proposal_id} is {prop['status']}, not {PENDING}")
            body = prop["body"]
            stops_by_no = {s["stop"]: s for s in body["hydration_stops"]}
            teams_by_no = {t["team"]: t for t in body["wellness_teams"]}
            _require_subset("approved_stops", a.approved_stops, stops_by_no)
            team_nos = list(teams_by_no) if a.approved_teams is None else a.approved_teams
            _require_subset("approved_teams", team_nos, teams_by_no)
            stray = sorted(set(a.overrides) - set(a.approved_stops))
            if stray:
                raise Invalid(f"overrides name stops that are not approved: {stray}")

            now, did = _now(), f"disp-{uuid.uuid4().hex[:12]}"
            stops, log = [], []
            for n in sorted(set(a.approved_stops)):
                s = dict(stops_by_no[n])
                if n in a.overrides:
                    o = a.overrides[n]
                    log.append(_log_entry("approval", n, s, o.latitude, o.longitude, o.reason, a.approved_by, now))
                    s = _move(s, o.latitude, o.longitude, o.reason)
                stops.append(s)
            d = {"dispatch_id": did, "proposal_id": a.proposal_id, "status": APPROVED, "approved_by": a.approved_by,
                 "approved_at": now, "updated_at": now, "revision": 1, "forecast_high_f": body["forecast_high_f"],
                 "stops": stops, "wellness_teams": [teams_by_no[n] for n in sorted(set(team_nos))],
                 "overrides": log}
            d["signature"] = self.signer.sign(d)
            tx.set(PROPOSALS, a.proposal_id, {**prop, "status": APPROVED, "dispatch_id": did})
            tx.set(DISPATCHES, did, d)
            return d
        return _out(self.repo.run(fn))

    # ---- reads ----------------------------------------------------------------------------------------------------
    def active(self) -> list[dict[str, Any]]:
        return [_out(d) for d in sorted(self.repo.find(DISPATCHES, APPROVED), key=lambda d: d["approved_at"])]

    # ---- midday triage --------------------------------------------------------------------------------------------
    def override(self, dispatch_id: str, o: OverrideIn) -> dict[str, Any]:
        def fn(tx: Tx) -> dict[str, Any]:
            d = _approved(tx, dispatch_id)
            idx = next((i for i, s in enumerate(d["stops"]) if s["stop"] == o.stop), None)
            if idx is None:
                raise Invalid(f"stop {o.stop} is not part of dispatch {dispatch_id} "
                              f"(approved stops: {[s['stop'] for s in d['stops']]})")
            now, old = _now(), d["stops"][idx]
            stops = list(d["stops"])
            stops[idx] = _move(old, o.latitude, o.longitude, o.reason)
            d = {**d, "stops": stops, "revision": d["revision"] + 1, "updated_at": now,
                 "overrides": [*d["overrides"], _log_entry("triage", o.stop, old, o.latitude, o.longitude, o.reason,
                                                           o.requested_by, now)]}
            d["signature"] = self.signer.sign(d)
            tx.set(DISPATCHES, dispatch_id, d)
            return d
        return _out(self.repo.run(fn))

    def close(self, dispatch_id: str, c: CloseIn) -> dict[str, Any]:
        def fn(tx: Tx) -> dict[str, Any]:
            d = _approved(tx, dispatch_id)
            now = _now()
            d = {**d, "status": CLOSED, "updated_at": now, "closed_at": now, "closed_by": c.closed_by,
                 "close_reason": c.reason}
            tx.set(DISPATCHES, dispatch_id, d)
            return d
        return _out(self.repo.run(fn))


def _approved(tx: Tx, dispatch_id: str) -> dict[str, Any]:
    d = tx.get(DISPATCHES, dispatch_id)
    if d is None:
        raise NotFound(f"dispatch {dispatch_id} not found")
    if d["status"] != APPROVED:
        raise Conflict(f"dispatch {dispatch_id} is {d['status']}, not {APPROVED}")
    return d


def _require_subset(label: str, nums: list[int], known: dict[int, Any]) -> None:
    missing = sorted(set(nums) - set(known))
    if missing:
        raise Invalid(f"{label} {missing} not in the proposal (it has {sorted(known)})")


def _move(stop: dict, lat: float, lon: float, reason: str) -> dict:
    """New coordinates for a stop; the first original point is kept so the map can show what moved."""
    s = dict(stop)
    s.setdefault("original_latitude", stop["latitude"])
    s.setdefault("original_longitude", stop["longitude"])
    s.update(latitude=lat, longitude=lon, override_reason=reason)
    return s


def _log_entry(stage: str, n: int, old: dict, lat: float, lon: float, reason: str, who: str, at: str) -> dict:
    return {"stage": stage, "stop": n, "old_latitude": old["latitude"], "old_longitude": old["longitude"],
            "new_latitude": lat, "new_longitude": lon, "reason": reason, "requested_by": who, "at": at}


def _out(d: dict[str, Any]) -> dict[str, Any]:
    return {**d, "signature_alg": ALG}
