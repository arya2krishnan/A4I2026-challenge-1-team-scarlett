#!/usr/bin/env python3
"""Resolve ${VAR} / ${VAR:default} in toolbox/tools.yaml from the environment and write a deploy-ready file.

    python scripts/render_toolbox.py [--out toolbox/tools.rendered.yaml]

Fails if a placeholder without a default is unset, so a missing GOOGLE_CLOUD_PROJECT is caught before it is uploaded.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::([^}]*))?\}")


def resolve(text: str, env: dict[str, str]) -> str:
    def sub(m: re.Match) -> str:
        name, default = m.group(1), m.group(2)
        val = env.get(name) or default
        if val is None or val == "":
            raise KeyError(f"environment variable {name} is not set and has no default")
        return val
    return PLACEHOLDER.sub(sub, text)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(ROOT / "toolbox" / "tools.yaml"))
    ap.add_argument("--out", default=str(ROOT / "toolbox" / "tools.rendered.yaml"))
    args = ap.parse_args()
    try:
        out = resolve(Path(args.src).read_text(), dict(os.environ))
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    Path(args.out).write_text(out)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
