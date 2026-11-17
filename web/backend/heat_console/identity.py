"""Who is operating the console. IAP sets X-Goog-Authenticated-User-Email ("accounts.google.com:me@x.org").
Without IAP (Cloud Run IAM), Cloud Run has already verified the caller's ID token, so its email claim is trusted
for attribution. Locally there is neither: WEB_DEV_USER."""
from __future__ import annotations

import base64
import json

from fastapi import Request


def current_user(request: Request, dev_user: str) -> str:
    iap = request.headers.get("x-goog-authenticated-user-email")
    if iap:
        return iap.split(":", 1)[-1]
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer ") and auth.count(".") == 2:
        try:
            payload = auth.split(" ", 1)[1].split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            if claims.get("email"):
                return str(claims["email"])
        except (ValueError, IndexError):
            pass
    return dev_user
