#!/usr/bin/env python3
"""Ask the agent from the terminal (in-process, real Gemini + real Toolbox). Prints tool calls and the answer.

    TOOLBOX_URL=http://127.0.0.1:5000 python scripts/ask.py "Forecast high is 102. Where do 3 trucks go?" [more questions in the same chat]
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402
from heat_dispatch.agent import root_agent  # noqa: E402


async def main(questions: list[str]) -> None:
    runner = InMemoryRunner(agent=root_agent, app_name="ask")
    s = await runner.session_service.create_session(app_name="ask", user_id="cli")
    for q in questions:
        print(f"\n=== USER: {q}")
        async for ev in runner.run_async(user_id="cli", session_id=s.id, new_message=types.Content(role="user", parts=[types.Part(text=q)])):
            for p in (ev.content.parts if ev.content else []):
                if p.function_call:
                    print(f"  [tool] {p.function_call.name} {json.dumps(dict(p.function_call.args or {}), default=str)[:200]}")
                elif p.function_response:
                    r = str(p.function_response.response)
                    print(f"  [result] {p.function_response.name}: {r[:160]}{'...' if len(r) > 160 else ''}")
                elif p.text and not p.thought and ev.author != "user":
                    print(f"\n{p.text}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
