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

print(f"\n[INIT] Variables cargadas:")
print(f"  REAL_DISCORD_WEBHOOK_URL: {bool(REAL_DISCORD_WEBHOOK_URL)}")
print(f"  STAFF_LOG_WEBHOOK_URL: {bool(STAFF_LOG_WEBHOOK_URL)}")
print(f"  LOGIN_LOGOUT_WEBHOOK_URL: {bool(LOGIN_LOGOUT_WEBHOOK_URL)}")
print(f"  ALLOWED_COUNTRIES: {ALLOWED_COUNTRIES}\n")

@app.route('/')
def index():
    return jsonify({"status": "Dink webhook endpoint is active"}), 200

@app.route('/api/webhooks/dink', methods=['POST', 'GET'])
def dink_webhook_handler():
    if request.method == 'GET':
        return jsonify({"status": "URL correcta"}), 200

    print("\n--- [NUEVA PETICIÓN] ---")
    try:
        # Obtener IP
        ip_address = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
        print(f"✅ IP: {ip_address}")

        # Geolocalización
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
        
        # Obtener payload
        dink_payload = request.get_json()
        
        player_name = dink_payload.get('playerName', 'Desconocido')
        notification_type = dink_payload.get('type')
        
        print(f"👤 Jugador: {player_name}")
        print(f"📌 Tipo: {notification_type}")

        # Validar país
        if country_code and country_code in ALLOWED_COUNTRIES:
            print(f"✅ PERMITIDO")
            
            # Enviar alerta de éxito al staff
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
                    print(f"📤 Enviando a STAFF_LOG_WEBHOOK_URL...")
                    response = requests.post(STAFF_LOG_WEBHOOK_URL, json=success_alert, timeout=5)
                    print(f"  ↳ Respuesta: {response.status_code} {response.text[:100]}")
                except Exception as e:
                    print(f"  ❌ Error: {e}")
            else:
                print(f"⚠️ STAFF_LOG_WEBHOOK_URL no configurado")

            # Enviar a Discord
            target_webhook = REAL_DISCORD_WEBHOOK_URL
            webhook_name = "REAL_DISCORD_WEBHOOK_URL"
            
            if notification_type == 'LOGIN' and LOGIN_LOGOUT_WEBHOOK_URL:
                target_webhook = LOGIN_LOGOUT_WEBHOOK_URL
                webhook_name = "LOGIN_LOGOUT_WEBHOOK_URL"
                print(f"📍 Usando {webhook_name}")
            
            if target_webhook:
                try:
                    print(f"📤 Reenviando a {webhook_name}...")
                    print(f"  Payload: {json.dumps(dink_payload, indent=2)[:200]}...")
                    response = requests.post(target_webhook, json=dink_payload, timeout=10)
                    print(f"  ↳ Respuesta: {response.status_code} {response.text[:100]}")
                except Exception as e:
                    print(f"  ❌ Error: {e}")
            else:
                print(f"❌ No hay webhook configurado para {notification_type}")
            
            return jsonify({"status": "ok"}), 200
        
        else:
            print(f"❌ BLOQUEADO")
            
            # Enviar alerta de bloqueo
            if STAFF_LOG_WEBHOOK_URL:
                alert = {
                    "content": f"🚨 **BLOQUEADO** 🚨",
                    "embeds": [{
                        "color": 15158332,
                        "title": "Intento desde ubicación no permitida",
                        "fields": [
                            {"name": "Jugador", "value": f"`{player_name}`", "inline": True},
                            {"name": "País", "value": f"`{country_code or 'Unknown'}`", "inline": True},
                            {"name": "IP", "value": f"`{ip_address}`", "inline": True}
                        ]
                    }]
                }
                try:
                    print(f"📤 Enviando alerta de bloqueo...")
                    response = requests.post(STAFF_LOG_WEBHOOK_URL, json=alert, timeout=10)
                    print(f"  ↳ Respuesta: {response.status_code}")
                except Exception as e:
                    print(f"  ❌ Error: {e}")
            
            return jsonify({"status": "ok"}), 200

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": "Error"}), 500

@app.route('/api/proxy-destino', methods=['POST', 'GET'])
def proxy_destino():
    """Alias"""
    return dink_webhook_handler()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
