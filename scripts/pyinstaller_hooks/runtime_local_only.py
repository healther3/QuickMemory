"""Keep bundled SDK initialization offline before the application imports it."""
import os
import sys

os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
os.environ["LITELLM_TELEMETRY"] = "False"
os.environ["LITELLM_MODE"] = "PRODUCTION"
os.environ["DO_NOT_TRACK"] = "1"
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")
