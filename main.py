from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
import re

app = Flask(__name__)
CORS(app)

# OpenRouter API Client
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key="sk-or-v1-DEIN_NEUER_API_KEY_HIER",  # <-- ERSETZE DAS!
)

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

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        "status": "online",
        "service": "Roblox AI Code Generator",
        "version": "1.0.0"
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
        completion = client.chat.completions.create(
            extra_headers={
                "HTTP-Referer": "https://roblox-ai-plugin.com",
                "X-Title": "Roblox AI Code Generator",
            },
            model="nex-agi/deepseek-v3.1-nex-n1:free",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            max_tokens=4000
        )
        
        response_text = completion.choices[0].message.content
        
        # JSON aus der Antwort extrahieren
        json_match = re.search(r'[\[\{].*[\]\}]', response_text, re.DOTALL)
        
        if json_match:
            import json
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
        
        completion = client.chat.completions.create(
            extra_headers={
                "HTTP-Referer": "https://roblox-ai-plugin.com",
                "X-Title": "Roblox AI Code Generator",
            },
            model="nex-agi/deepseek-v3.1-nex-n1:free",
            messages=[
                {
                    "role": "system", 
                    "content": "Du bist ein Roblox Lua Experte. Antworte NUR mit funktionierendem Lua Code. Keine Erklärungen, nur Code."
                },
                {"role": "user", "content": data['prompt']}
            ],
            temperature=0.7,
            max_tokens=4000
        )
        
        code = completion.choices[0].message.content
        
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

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=False)