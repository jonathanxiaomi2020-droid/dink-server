import os
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import json

load_dotenv()

app = Flask(__name__)

REAL_DISCORD_WEBHOOK_URL = os.getenv("REAL_DISCORD_WEBHOOK_URL")
STAFF_LOG_WEBHOOK_URL = os.getenv("STAFF_LOG_WEBHOOK_URL")
LOGIN_LOGOUT_WEBHOOK_URL = os.getenv("LOGIN_LOGOUT_WEBHOOK_URL")

ALLOWED_COUNTRIES_STR = os.getenv("ALLOWED_COUNTRIES", "US,GB,VE,ES")
ALLOWED_COUNTRIES = [country.strip().upper() for country in ALLOWED_COUNTRIES_STR.split(',')]

@app.route('/')
def index():
    return jsonify({"status": "Dink webhook endpoint is active"})

@app.route('/api/webhooks/dink', methods=['POST', 'GET'])
@app.route('/api/proxy-destino', methods=['POST', 'GET'])
def dink_webhook_handler():
    if request.method == 'GET':
        return jsonify({"status": "URL correcta"}), 200

    print("\n--- [NUEVA PETICIÓN] ---")
    try:
        ip_address = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
        print(f"✅ IP: {ip_address}")

        country_code = None
        try:
            response = requests.get(f'http://ip-api.com/json/{ip_address}?fields=countryCode,status', timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success':
                    country_code = data.get('countryCode')
                    print(f"✅ País: {country_code}")
        except Exception as e:
            print(f"⚠️ Geo error: {e}")
        
        dink_payload = request.get_json()
        
        player_name = dink_payload.get('playerName', 'Desconocido')
        notification_type = dink_payload.get('type')
        
        print(f"👤 Jugador: {player_name}")
        print(f"📌 Tipo: {notification_type}")

        if country_code and country_code in ALLOWED_COUNTRIES:
            print(f"✅ PERMITIDO")
            
            if STAFF_LOG_WEBHOOK_URL:
                success_alert = {
                    "content": f"✅ **Actividad Autorizada**",
                    "embeds": [{
                        "color": 5763719,
                        "title": "Conexión Válida Detectada",
                        "fields": [
                            {"name": "Jugador (RSN)", "value": f"`{player_name}`", "inline": True},
                            {"name": "País", "value": f"`{country_code}`", "inline": True},
                            {"name": "IP", "value": f"`{ip_address}`", "inline": True},
                            {"name": "Tipo", "value": f"`{notification_type}`", "inline": True}
                        ]
                    }]
                }
                try:
                    print(f"📤 Enviando a STAFF_LOG_WEBHOOK...")
                    resp = requests.post(STAFF_LOG_WEBHOOK_URL, json=success_alert, timeout=5)
                    print(f"   Status: {resp.status_code}")
                    if resp.status_code not in [200, 204]:
                        print(f"   ❌ Error: {resp.text}")
                    else:
                        print(f"   ✅ Enviado")
                except Exception as e:
                    print(f"   ❌ Error: {e}")

            target_webhook = REAL_DISCORD_WEBHOOK_URL
            webhook_name = "REAL_DISCORD"
            
            if notification_type == 'LOGIN' and LOGIN_LOGOUT_WEBHOOK_URL:
                target_webhook = LOGIN_LOGOUT_WEBHOOK_URL
                webhook_name = "LOGIN_LOGOUT"
            
            if target_webhook:
                try:
                    print(f"📤 Enviando a {webhook_name}...")
                    resp = requests.post(target_webhook, json=dink_payload, timeout=10)
                    print(f"   Status: {resp.status_code}")
                    if resp.status_code not in [200, 204]:
                        print(f"   ❌ Error: {resp.text}")
                    else:
                        print(f"   ✅ Enviado")
                except Exception as e:
                    print(f"   ❌ Error: {e}")
            
            return jsonify({"status": "ok"}), 200
        
        else:
            print(f"❌ BLOQUEADO")
            
            if STAFF_LOG_WEBHOOK_URL:
                alert = {
                    "content": f"🚨 **BLOQUEADO** 🚨",
                    "embeds": [{
                        "color": 15158332,
                        "title": "Intento bloqueado",
                        "fields": [
                            {"name": "Jugador", "value": f"`{player_name}`", "inline": True},
                            {"name": "País", "value": f"`{country_code or 'Unknown'}`", "inline": True},
                            {"name": "IP", "value": f"`{ip_address}`", "inline": True}
                        ]
                    }]
                }
                try:
                    print(f"📤 Enviando alerta de bloqueo...")
                    resp = requests.post(STAFF_LOG_WEBHOOK_URL, json=alert, timeout=10)
                    print(f"   Status: {resp.status_code}")
                except Exception as e:
                    print(f"   ❌ Error: {e}")
            
            return jsonify({"status": "ok"}), 200

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": "Error"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
