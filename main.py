import os
import json
import re
import time
import hashlib
from typing import Any, Dict, List, Optional, Tuple

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# ─────────────────────────────────────────────────────────────
# ENV CONFIG (Models & Speed/Quality)
# ─────────────────────────────────────────────────────────────
# Hauptmodel (fallback, wenn FAST/FULL nicht gesetzt)
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "nex-agi/deepseek-v3.1-nex-n1:free").strip()

# Optional: getrennte Models pro Mode
OPENROUTER_MODEL_FAST = os.environ.get("OPENROUTER_MODEL_FAST", "").strip()
OPENROUTER_MODEL_FULL = os.environ.get("OPENROUTER_MODEL_FULL", "").strip()

# Optional: Fallback models (komma-separiert), wenn Provider/Model kurz down ist
# Beispiel: "nex-agi/deepseek-v3.1-nex-n1:free,openai/gpt-4o-mini"
OPENROUTER_FALLBACK_MODELS = [
    m.strip() for m in os.environ.get("OPENROUTER_FALLBACK_MODELS", "").split(",") if m.strip()
]

DEFAULT_MODE = os.environ.get("DEFAULT_MODE", "fast").strip().lower()  # fast|full

FAST_MAX_TOKENS = int(os.environ.get("FAST_MAX_TOKENS", "1400"))
FULL_MAX_TOKENS = int(os.environ.get("FULL_MAX_TOKENS", "2600"))

# niedriger = stabiler/konstanter, meist weniger Gelaber => schneller
FAST_TEMPERATURE = float(os.environ.get("FAST_TEMPERATURE", "0.25"))
FULL_TEMPERATURE = float(os.environ.get("FULL_TEMPERATURE", "0.35"))

# Hard limits for safety/stability
MAX_TOKENS_CAP = int(os.environ.get("MAX_TOKENS_CAP", "6000"))

# Simple cache (best effort)
CACHE_MAX = int(os.environ.get("CACHE_MAX", "60"))
_CACHE: Dict[str, Dict[str, Any]] = {}

# Use a single Session for keep-alive (often faster)
_SESSION = requests.Session()

APP_REFERER = os.environ.get("APP_REFERER", "https://example.local")
APP_TITLE = os.environ.get("APP_TITLE", "Roblox AI Plugin Backend")


SYSTEM_PROMPT_FAST = """Du bist ein Roblox Lua Experte.
Ziel: schnelle, minimal funktionierende v1 Lösung mit sauberer Struktur.

REGELN:
- Antworte NUR als JSON (kein Text außerhalb).
- So kurz wie möglich, aber lauffähig.
- Max 3 Scripts, wenn möglich 1.
- Server validiert alles (RemoteEvents/Functions in ReplicatedStorage).
- Keine unnötigen Features/Erklärungen.

FORMAT:
[
  {"scriptName":"...","scriptType":"Script|LocalScript|ModuleScript","parent":"ServerScriptService|StarterPlayerScripts|StarterGui|ReplicatedStorage","code":"..."}
]
"""

SYSTEM_PROMPT_FULL = """Du bist ein Roblox Lua Experte.
Ziel: gute Output-Qualität, aber ohne unnötig lange Antworten.

REGELN:
- Antworte NUR als JSON (kein Text außerhalb).
- Struktur: Server-Logik (ServerScriptService), Shared Remotes (ReplicatedStorage), optional UI (StarterGui).
- Server validiert alles.
- Halte Code kompakt, aber klar.

FORMAT:
[
  {"scriptName":"...","scriptType":"Script|LocalScript|ModuleScript","parent":"ServerScriptService|StarterPlayerScripts|StarterGui|ReplicatedStorage","code":"..."}
]
"""


def _get_api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not set (set it in Koyeb Environment Variables)")
    return key


def _pick_model(mode: str) -> str:
    if mode == "fast" and OPENROUTER_MODEL_FAST:
        return OPENROUTER_MODEL_FAST
    if mode == "full" and OPENROUTER_MODEL_FULL:
        return OPENROUTER_MODEL_FULL
    return OPENROUTER_MODEL


def _cache_key(prompt: str, mode: str) -> str:
    return hashlib.sha256((mode + "\n" + prompt).encode("utf-8")).hexdigest()


def _cache_get(k: str) -> Optional[Dict[str, Any]]:
    return _CACHE.get(k)


def _cache_put(k: str, value: Dict[str, Any]) -> None:
    _CACHE[k] = value
    if len(_CACHE) > CACHE_MAX:
        first_key = next(iter(_CACHE))
        if first_key != k:
            _CACHE.pop(first_key, None)


def _normalize_scripts(parsed: Any) -> List[Dict[str, Any]]:
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        return [{
            "scriptName": "GeneratedScript",
            "scriptType": "Script",
            "parent": "ServerScriptService",
            "code": str(parsed),
        }]

    out: List[Dict[str, Any]] = []
    for s in parsed:
        if not isinstance(s, dict):
            continue
        out.append({
            "scriptName": str(s.get("scriptName", "GeneratedScript")),
            "scriptType": str(s.get("scriptType", "Script")),
            "parent": str(s.get("parent", "ServerScriptService")),
            "code": str(s.get("code", "-- empty")),
        })

    if not out:
        out = [{
            "scriptName": "GeneratedScript",
            "scriptType": "Script",
            "parent": "ServerScriptService",
            "code": "-- empty",
        }]
    return out


def _extract_scripts(ai_text: str) -> List[Dict[str, Any]]:
    # 1) strict JSON parse
    try:
        return _normalize_scripts(json.loads(ai_text))
    except Exception:
        pass

    # 2) find JSON blob inside text
    m = re.search(r"(\[.*\]|\{.*\})", ai_text, re.DOTALL)
    if m:
        try:
            return _normalize_scripts(json.loads(m.group(1)))
        except Exception:
            pass

    # 3) fallback raw
    return [{
        "scriptName": "GeneratedScript",
        "scriptType": "Script",
        "parent": "ServerScriptService",
        "code": ai_text.strip(),
    }]


def _call_openrouter_once(model: str, messages: List[Dict[str, str]], temperature: float, max_tokens: int) -> str:
    headers = {
        "Authorization": f"Bearer {_get_api_key()}",
        "Content-Type": "application/json",
        "HTTP-Referer": APP_REFERER,
        "X-Title": APP_TITLE,
    }

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    r = _SESSION.post(OPENROUTER_URL, headers=headers, json=payload, timeout=120)
    if r.status_code >= 400:
        raise RuntimeError(f"OpenRouter HTTP {r.status_code}: {r.text[:600]}")
    data = r.json()
    return data["choices"][0]["message"]["content"]


def call_openrouter_with_fallback(mode: str, prompt: str, max_tokens_override: Optional[int]) -> Tuple[str, str]:
    if mode not in ("fast", "full"):
        mode = DEFAULT_MODE if DEFAULT_MODE in ("fast", "full") else "fast"

    system = SYSTEM_PROMPT_FAST if mode == "fast" else SYSTEM_PROMPT_FULL
    temperature = FAST_TEMPERATURE if mode == "fast" else FULL_TEMPERATURE
    default_tokens = FAST_MAX_TOKENS if mode == "fast" else FULL_MAX_TOKENS

    max_tokens = default_tokens
    if isinstance(max_tokens_override, int):
        max_tokens = max(200, min(MAX_TOKENS_CAP, max_tokens_override))

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]

    primary_model = _pick_model(mode)
    models_to_try = [primary_model] + [m for m in OPENROUTER_FALLBACK_MODELS if m != primary_model]

    last_err: Optional[Exception] = None
    for m in models_to_try:
        try:
            text = _call_openrouter_once(m, messages, temperature=temperature, max_tokens=max_tokens)
            return text, m
        except Exception as e:
            last_err = e

    raise RuntimeError(str(last_err) if last_err else "Unknown error calling OpenRouter")


@app.get("/")
def root():
    return jsonify({
        "ok": True,
        "service": "roblox-ai-plugin-backend",
        "default_mode": DEFAULT_MODE,
        "models": {
            "OPENROUTER_MODEL": OPENROUTER_MODEL,
            "OPENROUTER_MODEL_FAST": OPENROUTER_MODEL_FAST or None,
            "OPENROUTER_MODEL_FULL": OPENROUTER_MODEL_FULL or None,
            "OPENROUTER_FALLBACK_MODELS": OPENROUTER_FALLBACK_MODELS,
        }
    })


@app.get("/health")
def health():
    return jsonify({"status": "healthy"})


@app.post("/generate")
def generate():
    start = time.time()
    try:
        body = request.get_json(silent=True) or {}

        prompt = (body.get("prompt") or "").strip()
        if not prompt:
            return jsonify({"success": False, "error": "prompt fehlt"}), 400

        mode = (body.get("mode") or DEFAULT_MODE).strip().lower()
        if mode not in ("fast", "full"):
            mode = DEFAULT_MODE if DEFAULT_MODE in ("fast", "full") else "fast"

        max_tokens_override = body.get("max_tokens", None)
        if isinstance(max_tokens_override, (int, float)):
            max_tokens_override = int(max_tokens_override)
        else:
            max_tokens_override = None

        ck = _cache_key(prompt, mode)
        cached = _cache_get(ck)
        if cached:
            cached2 = dict(cached)
            cached2["cached"] = True
            cached2["elapsed_ms"] = int((time.time() - start) * 1000)
            return jsonify(cached2)

        ai_text, used_model = call_openrouter_with_fallback(mode=mode, prompt=prompt, max_tokens_override=max_tokens_override)
        scripts = _extract_scripts(ai_text)

        resp = {
            "success": True,
            "mode": mode,
            "model": used_model,
            "cached": False,
            "scripts": scripts,
            "elapsed_ms": int((time.time() - start) * 1000),
        }
        _cache_put(ck, resp)
        return jsonify(resp)

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "elapsed_ms": int((time.time() - start) * 1000),
        }), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port)
