from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import re
import json
import os

app = Flask(__name__)
CORS(app)

# ⚠️ WICHTIG: Ersetze mit deinem API Key!
API_KEY = os.environ.get("OPENROUTER_API_KEY", "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")
API_URL = "https://openrouter.ai/api/v1/chat/completions"

# System Prompt für Roblox Lua Code Generation
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
    "parent": "ServerScriptService|StarterPlayerScripts|ReplicatedStorage|Workspace",
    "code": "-- Der Lua Code hier"
}

Wenn mehrere Scripts benötigt werden, gib ein Array zurück:
[
    {"scriptName": "...", "scriptType": "...", "parent": "...", "code": "..."},
    {"scriptName": "...", "scriptType": "...", "parent": "...", "code": "..."}
]
"""

def call_ai(messages):
    """Ruft die OpenRouter API direkt auf"""
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://roblox-ai-plugin.com",
        "X-Title": "Roblox AI Code Generator"
    }
    
    data = {
        "model": "nex-agi/deepseek-v3.1-nex-n1:free",
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 4000
    }
    
    response = requests.post(API_URL, headers=headers, json=data, timeout=120)
    response.raise_for_status()
    return response.json()

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        "status": "online",
        "service": "Roblox AI Code Generator",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "generate": "/generate (POST)",
            "generate_simple": "/generate-simple (POST)"
        }
    })

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy"})

@app.route('/generate', methods=['POST'])
def generate_code():
    try:
        # Daten vom Roblox Plugin empfangen
        data = request.get_json()
        
        if not data or 'prompt' not in data:
            return jsonify({
                "success": False,
                "error": "Kein Prompt angegeben"
            }), 400
        
        user_prompt = data['prompt']
        
        # AI Request
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ]
        
        result = call_ai(messages)
        response_text = result['choices'][0]['message']['content']
        
        # JSON aus der Antwort extrahieren
        json_match = re.search(r'[\[\{].*[\]\}]', response_text, re.DOTALL)
        
        if json_match:
            try:
                scripts_data = json.loads(json_match.group())
                # Einzelnes Objekt in Liste umwandeln
                if isinstance(scripts_data, dict):
                    scripts_data = [scripts_data]
                    
                return jsonify({
                    "success": True,
                    "scripts": scripts_data
                })
            except json.JSONDecodeError:
                # Fallback: Raw Code zurückgeben
                return jsonify({
                    "success": True,
                    "scripts": [{
                        "scriptName": "GeneratedScript",
                        "scriptType": "Script",
                        "parent": "ServerScriptService",
                        "code": response_text
                    }]
                })
        else:
            # Fallback: Raw Code
            return jsonify({
                "success": True,
                "scripts": [{
                    "scriptName": "GeneratedScript",
                    "scriptType": "Script",
                    "parent": "ServerScriptService",
                    "code": response_text
                }]
            })
            
    except requests.exceptions.Timeout:
        return jsonify({
            "success": False,
            "error": "AI Request timeout - bitte erneut versuchen"
        }), 504
    except requests.exceptions.RequestException as e:
        return jsonify({
            "success": False,
            "error": f"API Fehler: {str(e)}"
        }), 502
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/generate-simple', methods=['POST'])
def generate_simple():
    """Einfacher Endpoint der nur Code zurückgibt"""
    try:
        data = request.get_json()
        
        if not data or 'prompt' not in data:
            return jsonify({"success": False, "error": "Kein Prompt"}), 400
        
        messages = [
            {
                "role": "system", 
                "content": "Du bist ein Roblox Lua Experte. Antworte NUR mit funktionierendem Lua Code. Keine Erklärungen, nur Code."
            },
            {"role": "user", "content": data['prompt']}
        ]
        
        result = call_ai(messages)
        code = result['choices'][0]['message']['content']
        
        # Code-Block Markdown entfernen falls vorhanden
        code = re.sub(r'^```lua\n?', '', code)
        code = re.sub(r'^```\n?', '', code)
        code = re.sub(r'\n?```$', '', code)
        
        return jsonify({
            "success": True,
            "code": code.strip()
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/test-ai', methods=['GET'])
def test_ai():
    """Test endpoint um AI Verbindung zu prüfen"""
    try:
        messages = [
            {"role": "user", "content": "Say 'Hello Roblox!' and nothing else."}
        ]
        result = call_ai(messages)
        return jsonify({
            "success": True,
            "response": result['choices'][0]['message']['content']
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=False)
