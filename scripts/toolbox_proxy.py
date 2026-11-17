#!/usr/bin/env python3
"""Local authenticated proxy to the PRIVATE Cloud Run Toolbox, so local tools (agent, adk web, smoke) can use it.

    python scripts/toolbox_proxy.py            # forwards 127.0.0.1:5000 -> $TOOLBOX_URL with your gcloud identity token

Equivalent of `gcloud run services proxy` without installing a gcloud component. Your gcloud user needs run.invoker
(project owners have it). Deployed agents do not use this: they send their own ID token (see agent/heat_dispatch/toolbox.py).
"""
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

TARGET = os.environ.get("TOOLBOX_URL", "").rstrip("/")
PORT = int(os.environ.get("PROXY_PORT", "5000"))
_tok = {"v": "", "t": 0.0}
_lock = threading.Lock()


def token() -> str:
    with _lock:
        if time.time() - _tok["t"] > 2400:        # identity tokens last an hour
            _tok["v"] = subprocess.run(["gcloud", "auth", "print-identity-token"], capture_output=True, text=True,
                                       check=True).stdout.strip()
            _tok["t"] = time.time()
        return _tok["v"]


class H(BaseHTTPRequestHandler):
    def _fwd(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)) or None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "authorization", "content-length")}
        headers["Authorization"] = f"Bearer {token()}"
        r = requests.request(self.command, TARGET + self.path, data=body, headers=headers, timeout=120)
        self.send_response(r.status_code)
        for k, v in r.headers.items():
            if k.lower() not in ("content-encoding", "transfer-encoding", "content-length", "connection"):
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(r.content)))
        self.end_headers()
        self.wfile.write(r.content)

    do_GET = do_POST = do_DELETE = do_PUT = do_OPTIONS = _fwd

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    if not TARGET.startswith("https://"):
        sys.exit("TOOLBOX_URL must be the deployed https URL (run make deploy-toolbox first)")
    print(f"proxy 127.0.0.1:{PORT} -> {TARGET}")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
