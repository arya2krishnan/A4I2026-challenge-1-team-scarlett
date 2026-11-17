"""Heat Dispatch Assistant: Streamlit client. A thin UI over the agent (in-process locally, Agent Runtime when deployed).

Why Streamlit rather than `adk web` or Gemini Enterprise: the user is a duty officer working a single hot afternoon.
They need a map of where the trucks go and a dispatch sheet they can download, not a chat transcript. The agent itself
is the same either way; `make adk-web` is kept for debugging tool calls.
"""
from __future__ import annotations

import json
import pathlib
import uuid

import pandas as pd
import pydeck as pdk
import streamlit as st

from backends import make_backend

TITLE = "Heat Dispatch Assistant · Chicago"
KIND_COLORS = {"hydration": [230, 90, 20], "wellness": [110, 70, 190], "library": [30, 120, 190], "site": [200, 40, 40]}
LEGEND = {"hydration": "Hydration truck", "wellness": "Wellness-check team"}
MOCK_311_PATH = pathlib.Path(__file__).parent / "mock_311.json"
MOCK_311: list[dict] = json.loads(MOCK_311_PATH.read_text()) if MOCK_311_PATH.exists() else []

EXAMPLES = [
    ("Plan tomorrow", "Forecast high is 102. Where do 3 hydration trucks, 4 wellness-check teams and 3 library extensions go? "
                      "Check who it reaches, then write the dispatch sheet."),
    ("Senior AC outage (311)", "Midday Emergency Alert (311 Incident #311-HEAT-401): 14 calls report central AC failure at senior housing near 79th & Halsted in Chatham. Recommend immediate asset rerouting and emergency indoor cooling backup."),
    ("Why is it hot there?", "Why is Englewood (63rd and Halsted) so much hotter than the lakefront? Is that place measured or predicted?"),
    ("How rare is 102?", "How often has Chicago hit 100F or more in the last seven summers, and is it getting more common?"),
]
STATIC_NOTES = [
    "**Model.** BigQuery ML linear regression predicting how many °F hotter a ~330 m cell runs than the Chicago average "
    "(an *offset*, not a temperature). Physical features only; race is not used.",
    "**Data.** NOAA Heat Watch (one volunteer-driven afternoon), NOAA GHCN-Daily (7 years), US Census ACS (tract level), "
    "City of Chicago Cooling Centers snapshot (confirm hours).",
    "**Limits.** One day of readings; four features; tract-level demographics are estimates. Decision support, not an advisory.",
]

st.set_page_config(page_title=TITLE, page_icon="🌡️", layout="wide")
st.markdown("""<style>
.block-container {padding-top: 3rem; max-width: 1150px}
.hero {background: linear-gradient(120deg,#ffe3d0,#ffd0d0 60%,#fff0d0); border-radius: 18px; padding: 20px 26px; margin-bottom: 14px}
.hero h1 {margin:0; font-size:1.8rem} .hero p {margin:4px 0 0; opacity:.75}
</style>""", unsafe_allow_html=True)


@st.cache_resource(show_spinner="Connecting to the agent…")
def get_backend():
    return make_backend()


def render_map(m: dict) -> None:
    markers = m.get("markers") or []
    if not markers:
        return
    rows = [{"lat": k["lat"], "lng": k["lng"], "label": k.get("label", ""), "color": KIND_COLORS.get(k.get("kind"), KIND_COLORS["site"])}
            for k in markers]
    layer = pdk.Layer("ScatterplotLayer", rows, get_position="[lng, lat]", get_radius=260, radius_min_pixels=9,
                      get_fill_color="color", get_line_color=[255, 255, 255], line_width_min_pixels=2, stroked=True, pickable=True)
    lat = sum(r["lat"] for r in rows) / len(rows)
    lng = sum(r["lng"] for r in rows) / len(rows)
    st.pydeck_chart(pdk.Deck(layers=[layer], map_style="light", tooltip={"text": "{label}"},
                             initial_view_state=pdk.ViewState(latitude=lat, longitude=lng, zoom=10.3)))
    st.caption("  ·  ".join(f"● {v}" for v in LEGEND.values()))


def render_result(b: dict, key: str) -> None:
    """Draw the visual parts of a tool result: the dispatch map and sheet (download), or a compact table of rows."""
    r = b.get("response")
    if not isinstance(r, dict):
        return
    if r.get("map"):
        render_map(r["map"])
    sheet = r.get("dispatch_sheet_markdown")
    if sheet:
        with st.expander("📋 Dispatch sheet", expanded=True):
            st.markdown(sheet, unsafe_allow_html=False)
            st.download_button("Download dispatch sheet (.md)", sheet, file_name="heat_dispatch_sheet.md", key=f"dl-{key}")


def render_blocks(blocks: list[dict], key: str) -> None:
    calls = [b for b in blocks if b["kind"] == "tool_call"]
    if calls:
        with st.expander(f"🔍 {len(calls)} tool call{'s' if len(calls) != 1 else ''} (what the agent actually ran)", expanded=False):
            for b in blocks:
                if b["kind"] == "tool_call":
                    st.markdown(f"**🔧 {b['name']}**")
                    st.json(b["args"], expanded=False)
                elif b["kind"] == "tool_result":
                    raw = b.get("response") or {}
                    result = raw.get("result", raw) if isinstance(raw, dict) else raw
                    try:
                        rows = json.loads(result) if isinstance(result, str) else result
                        if isinstance(rows, dict):
                            rows = [rows]
                        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                            st.dataframe(pd.DataFrame(rows).drop(columns=["why"], errors="ignore"), width="stretch")
                    except (ValueError, TypeError):
                        pass
    for i, b in enumerate(blocks):
        if b["kind"] == "tool_result":
            render_result(b, f"{key}-{i}")
        elif b["kind"] == "text" and b.get("author") != "user" and b["text"].strip():
            st.markdown(b["text"])


ss = st.session_state
try:
    be = get_backend()
except Exception as exc:
    st.error(f"Could not connect to the agent: {exc}")
    st.stop()
if "uid" not in ss:
    ss.uid = st.query_params.get("u") or f"u-{uuid.uuid4().hex[:12]}"
    st.query_params["u"] = ss.uid
ss.setdefault("active", None)
ss.setdefault("messages", [])

picked = None

with st.sidebar:
    st.markdown("### 🌡️ Heat Dispatch")
    st.caption(f"Agent: {be.label}")
    forecast = st.number_input("Forecast high (°F)", min_value=70, max_value=125, value=102, step=1,
                               help="Sent with every message so the agent never has to guess the forecast.")
    if st.button("＋ New chat", width="stretch", type="primary"):
        ss.active, ss.messages = None, []
    
    if MOCK_311:
        with st.expander("🚨 Midday 311 Feed (Simulate)", expanded=True):
            st.caption("Click to trigger real-time disruption triage rerouting:")
            for inc in MOCK_311:
                st.markdown(f"**{inc['category']}**")
                st.caption(f"📍 {inc['location']} ({inc['neighborhood']}) · 📞 {inc['call_volume']} calls")
                if st.button(f"⚡ Triage Incident #{inc['id'][-3:]}", key=f"btn-{inc['id']}", width="stretch"):
                    picked = inc["prompt"]
                st.divider()

    st.markdown("**Recent chats**")
    try:
        for c in be.list_sessions(ss.uid):
            if st.button(c["title"][:34], key=f"open-{c['id']}", width="stretch"):
                ss.active, ss.messages = c["id"], be.get_messages(ss.uid, c["id"])
    except Exception as exc:
        st.caption(f"(history unavailable: {exc.__class__.__name__})")
    with st.expander("ℹ️ About this data & limits"):
        for n in STATIC_NOTES:
            st.markdown(n)

if not ss.messages:
    st.markdown('<div class="hero"><h1>Where does help go when it hits 102°F?</h1>'
                "<p>Hydration trucks, wellness checks and library hours, ranked by a live heat model, with the reasoning "
                "and an equity check.</p></div>", unsafe_allow_html=True)
    for col, (head, prompt) in zip(st.columns(len(EXAMPLES)), EXAMPLES):
        with col:
            if st.button(head, key=f"ex-{head}", width="stretch"):
                picked = prompt

for i, msg in enumerate(ss.messages):
    with st.chat_message(msg["role"]):
        render_blocks(msg["blocks"], f"h{i}")

prompt = st.chat_input("Ask about tomorrow's heat in Chicago…") or picked
if prompt:
    if ss.active is None:
        ss.active = be.create_session(ss.uid, prompt.replace("\n", " ")[:60])
    ss.messages.append({"role": "user", "blocks": [{"kind": "text", "author": "user", "text": prompt}]})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        blocks: list[dict] = []
        status = st.status("Working on it…", expanded=True)
        try:
            for block in be.stream(ss.uid, ss.active, f"[Planner context: forecast high {forecast}°F]\n{prompt}"):
                blocks.append(block)
                if block["kind"] == "tool_call":
                    status.write(f"🔧 {block['name']}")
                elif block["kind"] == "text" and block["text"].strip():
                    st.markdown(block["text"])
                elif block["kind"] == "tool_result":
                    render_result(block, f"live-{len(blocks)}")
            if not any(b["kind"] == "text" and b["text"].strip() for b in blocks):
                blocks.append({"kind": "text", "author": "model", "text": "The agent finished without a written answer. Please ask again."})
            status.update(label="Done", state="complete", expanded=False)
        except Exception as exc:
            blocks.append({"kind": "text", "author": "model", "text": f"⚠️ Something went wrong: {exc}"})
            status.update(label="Something went wrong", state="error", expanded=False)
            st.error(f"Something went wrong: {exc}")
    ss.messages.append({"role": "assistant", "blocks": blocks})
    st.rerun()
