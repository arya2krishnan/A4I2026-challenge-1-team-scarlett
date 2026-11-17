"""HMAC-SHA256 over the parts of a dispatch a field crew acts on (who approved it, where each stop is)."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
from typing import Any

log = logging.getLogger(__name__)
ALG = "HMAC-SHA256"


def _payload(d: dict[str, Any]) -> bytes:
    core = {
        "dispatch_id": d["dispatch_id"], "proposal_id": d["proposal_id"], "approved_by": d["approved_by"],
        "approved_at": d["approved_at"], "revision": d["revision"],
        "stops": [[s["stop"], s["latitude"], s["longitude"]] for s in d["stops"]],
        "teams": [[t["team"], t.get("tract_geo_id"), t["latitude"], t["longitude"]] for t in d["wellness_teams"]],
    }
    return json.dumps(core, sort_keys=True, separators=(",", ":")).encode()


class Signer:
    def __init__(self, key: bytes | None = None) -> None:
        if key is None:
            env = os.environ.get("DISPATCH_SIGNING_KEY", "").strip()
            if env:
                key = env.encode()
            elif os.environ.get("K_SERVICE"):   # set by Cloud Run: each instance would sign with a different key
                raise RuntimeError("DISPATCH_SIGNING_KEY is required on Cloud Run (mount it from Secret Manager).")
            else:
                log.warning("DISPATCH_SIGNING_KEY is not set: using a random key, so signatures will not verify "
                            "after a restart. Set it (e.g. from Secret Manager) for anything but local testing.")
                key = secrets.token_bytes(32)
        self._key = key

    def sign(self, dispatch: dict[str, Any]) -> str:
        return hmac.new(self._key, _payload(dispatch), hashlib.sha256).hexdigest()

    def verify(self, dispatch: dict[str, Any]) -> bool:
        return hmac.compare_digest(self.sign(dispatch), dispatch.get("signature", ""))
