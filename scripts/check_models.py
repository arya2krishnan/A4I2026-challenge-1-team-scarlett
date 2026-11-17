"""Does MODEL answer for this project via ADC?  (make check-models)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
from google import genai  # noqa: E402
from heat_dispatch.config import get_settings  # noqa: E402

s = get_settings()
print(f"project={s.project}")
try:
    c = genai.Client(vertexai=True, project=s.project, location=s.model_location)
    r = c.models.generate_content(model=s.model, contents="Reply with the word: ok")
    print(f"OK   {s.model} @ {s.model_location}: {(r.text or '').strip()[:20]}")
except Exception as e:
    print(f"FAIL {s.model} @ {s.model_location}: {str(e)[:200]}\nAdjust MODEL / MODEL_LOCATION in .env.")
    sys.exit(1)
