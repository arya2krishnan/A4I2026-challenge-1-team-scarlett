"""Smoke-run the Streamlit app with a fake backend: it must render a dispatch sheet and map without raising."""
from pathlib import Path

import backends
from streamlit.testing.v1 import AppTest

SHEET = "# Heat dispatch sheet\n| Stop |\n|---|\n| 1 |"


class FakeBackend:
    label = "fake"

    def __init__(self):
        self.sent = []

    def create_session(self, user_id, title):
        return "s1"

    def list_sessions(self, user_id, limit=30):
        return []

    def get_messages(self, user_id, session_id):
        return []

    def delete_session(self, user_id, session_id):
        pass

    def stream(self, user_id, session_id, message):
        self.sent.append(message)
        yield {"kind": "tool_call", "author": "a", "name": "build_dispatch_plan", "args": {"forecast_high_f": 102}}
        yield {"kind": "tool_result", "author": "a", "name": "build_dispatch_plan", "response": {
            "dispatch_sheet_markdown": SHEET,
            "map": {"markers": [{"lat": 41.78, "lng": -87.64, "kind": "hydration", "label": "Truck 1"}]}}}
        yield {"kind": "text", "author": "a", "text": "Here is the plan."}


def test_app_renders_plan(monkeypatch):
    fake = FakeBackend()
    monkeypatch.setattr(backends, "make_backend", lambda: fake)
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "client" / "app.py"), default_timeout=30).run()
    assert not at.exception
    at.chat_input[0].set_value("Plan tomorrow").run()
    assert not at.exception, at.exception
    assert fake.sent and fake.sent[0].startswith("[Planner context: forecast high 102°F]")
    assert any("Here is the plan." in m.value for m in at.markdown)
