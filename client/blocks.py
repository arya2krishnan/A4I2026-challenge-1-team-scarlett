"""Normalise ADK events into UI blocks and rebuild chat history from stored session events."""
from __future__ import annotations

from typing import Iterator


def blocks_from_event(event: dict) -> Iterator[dict]:
    """One ADK event dict (snake_case or camelCase) -> blocks: text | tool_call | tool_result."""
    author = event.get("author")
    for part in (event.get("content") or {}).get("parts") or []:
        if part.get("thought"):
            continue
        call = part.get("function_call") or part.get("functionCall")
        resp = part.get("function_response") or part.get("functionResponse")
        if call:
            yield {"kind": "tool_call", "author": author, "name": call.get("name"), "args": call.get("args") or {}}
        elif resp:
            yield {"kind": "tool_result", "author": author, "name": resp.get("name"), "response": resp.get("response") or {}}
        elif part.get("text"):
            yield {"kind": "text", "author": author, "text": part["text"]}


def messages_from_events(events: list[dict]) -> list[dict]:
    """Rebuild [{role, blocks}] from stored events (tool-response events are not user messages)."""
    messages: list[dict] = []
    for ev in events:
        blocks = list(blocks_from_event(ev))
        if not blocks:
            continue
        if ev.get("author") == "user":
            messages.append({"role": "user", "blocks": blocks})
        elif messages and messages[-1]["role"] == "assistant":
            messages[-1]["blocks"].extend(blocks)
        else:
            messages.append({"role": "assistant", "blocks": blocks})
    return messages
