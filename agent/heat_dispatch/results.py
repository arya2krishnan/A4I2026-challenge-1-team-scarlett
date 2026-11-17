"""Turn whatever a tool hands back into a list of row dicts.

MCP Toolbox returns a STRING: one JSON object (one row), a JSON array (several rows), or "null" (none).
Other paths may hand us lists/dicts already. Never raise: an unparseable result is an empty list.
"""
from __future__ import annotations

import json
from typing import Any


def parse_rows(resp: Any) -> list[dict]:
    if resp is None:
        return []
    if isinstance(resp, str):
        text = resp.strip()
        if not text or text == "null":
            return []
        try:
            resp = json.loads(text)
        except ValueError:
            return _parse_concatenated(text)
    if isinstance(resp, dict):
        for key in ("rows", "result", "results", "data"):
            if key in resp:
                return parse_rows(resp[key])
        return [resp]
    if isinstance(resp, list):
        out: list[dict] = []
        for item in resp:
            out.extend(parse_rows(item) if not isinstance(item, dict) else [item])
        return out
    return []


def _parse_concatenated(text: str) -> list[dict]:
    """'{...}{...}' (several objects, no separator) -> list of dicts."""
    dec, i, rows = json.JSONDecoder(), 0, []
    while i < len(text):
        while i < len(text) and text[i] in " \r\n\t,":
            i += 1
        if i >= len(text):
            break
        try:
            obj, i = dec.raw_decode(text, i)
        except ValueError:
            break
        if isinstance(obj, dict):
            rows.append(obj)
    return rows
