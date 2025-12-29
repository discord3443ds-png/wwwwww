import os
import json
import re
from typing import Any, Dict, List, Union

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = os.environ.get("OPENROUTER_MODEL", "nex-agi/deepseek-v3.1-nex-n1:free")

SYSTEM_PROMPT = """Du bist ein Experte für Roblox Lua Programmierung.
Du generierst NUR funktionierenden Roblox Lua Code basierend auf der Benutzeranfrage.

WICHTIGE REGELN:
1. Antworte NUR mit Lua Code - keine Erklärungen
2. Der Code muss sofort in Roblox Studio funktionieren
3. Nutze moderne Roblox Best Practices
4. Füge hilfreiche Kommentare im Code hinzu
5. Strukturiere den Code sauber

ANTWORT FORMAT:
Du musst deine Antwort in diesem JSON Format geben:
{
  "scriptName": "NameDesScripts",
  "scriptType": "Script|LocalScript|ModuleScript",
  "parent": "ServerScriptService|StarterPlayerScripts|StarterCharacterScripts|ReplicatedStorage|Workspace|StarterGui|ServerStorage",
  "code": "-- Der Lua Code hier"
}

Wenn mehrere Scripts benötigt werden, gib ein Array zurück:
[
  {"scriptName": "...", "scriptType": "...", "parent": "...", "code": "..."},
  {"scriptName": "...", "scriptType": "...", "parent": "...", "code": "..."}
]
"""


def _get_api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    return key


def call_openrouter(messages: List[Dict[str, str]]) -> str:
    api_key = _get_api_key()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        # optional, aber ok:
        "HTTP-Referer": os.environ.get("APP_REFERER", "https://example.local"),
        "X-Title": os.environ.get("APP_TITLE", "Roblox AI Plugin Backend"),
    }

    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 3500,
    }

    r = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=120)
    # Wenn OpenRouter Fehler liefert, wollen wir die Details sehen:
    if r.status_code >= 400:
        raise RuntimeError(f"OpenRouter HTTP {r.status_code}: {r.text[:500]}")

    data = r.json()
    return data["choices"][0]["message"]["content"]


def extract_scripts(ai_text: str) -> List[Dict[str, Any]]:
    """
    Erwartet JSON (objekt oder array) irgendwo im Text.
    Wenn kein JSON parsebar ist, fallback: ein Script mit raw code.
    """
    # Versuche JSON Block zu finden
    m = re.search(r"(\[.*\]|\{.*\})", ai_text, re.DOTALL)
    if m:
        candidate = m.group(1)
        try:
            parsed: Union[Dict[str, Any], List[Dict[str, Any]]] = json.loads(candidate)
            if isinstance(parsed, dict):
                parsed = [parsed]
            # Basic cleanup
            out: List[Dict[str, Any]] = []
            for s in parsed:
                out.append({
                    "scriptName": s.get("scriptName", "GeneratedScript"),
                    "scriptType": s.get("scriptType", "Script"),
                    "parent": s.get("parent", "ServerScriptService"),
                    "code": s.get("code", "-- empty"),
                })
            return out
        except json.JSONDecodeError:
            pass

    # Fallback: raw text als Script-Code
    return [{
        "scriptName": "GeneratedScript",
        "scriptType": "Script",
        "parent": "ServerScriptService",
        "code": ai_text.strip(),
    }]


@app.get("/")
def root():
    return jsonify({
        "ok": True,
        "service": "roblox-ai-plugin-backend",
        "model": MODEL,
        "endpoints": {
            "health": "/health",
            "generate": "/generate (POST)",
            "generate_simple": "/generate-simple (POST)",
        }
    })


@app.get("/health")
def health():
    # Health darf NICHT OpenRouter callen (sonst wird es langsam/instabil)
    return jsonify({"status": "healthy"})


@app.post("/generate")
def generate():
    try:
        body = request.get_json(silent=True) or {}
        prompt = (body.get("prompt") or "").strip()
        if not prompt:
            return jsonify({"success": False, "error": "prompt fehlt"}), 400

        ai_text = call_openrouter([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ])

        scripts = extract_scripts(ai_text)
        return jsonify({"success": True, "scripts": scripts})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.post("/generate-simple")
def generate_simple():
    try:
        body = request.get_json(silent=True) or {}
        prompt = (body.get("prompt") or "").strip()
        if not prompt:
            return jsonify({"success": False, "error": "prompt fehlt"}), 400

        ai_text = call_openrouter([
            {"role": "system", "content": "Du bist ein Roblox Lua Experte. Antworte NUR mit funktionierendem Lua Code. Keine Erklärungen, nur Code."},
            {"role": "user", "content": prompt},
        ])

        # Entferne evtl. Markdown Codefences
        ai_text = re.sub(r"^\s*```(?:lua)?\s*", "", ai_text)
        ai_text = re.sub(r"\s*```\s*$", "", ai_text)

        return jsonify({"success": True, "code": ai_text.strip()})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port)
