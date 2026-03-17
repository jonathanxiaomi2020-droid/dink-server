import os
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import json
import sys
import time

# Cargar variables de entorno
load_dotenv()

app = Flask(__name__)

# Forzar logs inmediatos (importante para Render)
sys.stdout.reconfigure(line_buffering=True)

# --- CONFIGURACIÓN DESDE VARIABLES DE ENTORNO ---
REAL_DISCORD_WEBHOOK_URL = os.getenv("REAL_DISCORD_WEBHOOK_URL")
STAFF_LOG_WEBHOOK_URL = os.getenv("STAFF_LOG_WEBHOOK_URL")
LOGIN_LOGOUT_WEBHOOK_URL = os.getenv("LOGIN_LOGOUT_WEBHOOK_URL")
DINK_SECRET = os.getenv("DINK_SECRET")  # Lo dejamos por si acaso, aunque no se use

# Países permitidos (ej. US, GB, VE)
ALLOWED_COUNTRIES_STR = os.getenv("ALLOWED_COUNTRIES", "US,GB")
ALLOWED_COUNTRIES = [country.strip().upper() for country in ALLOWED_COUNTRIES_STR.split(',')]

# --- Headers simulados para evitar bloqueos de Discord/Cloudflare ---
DISCORD_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

@app.route('/')
def index():
    return jsonify({"status": "Dink webhook endpoint is active"})

@app.route('/api/webhooks/dink', methods=['POST', 'GET'])
def dink_webhook_handler():
    if request.method == 'GET':
        return jsonify({"status": "URL correcta. Listo para recibir POST."}), 200

    # --- INICIO DEL PROCESO POST ---
    print("\n--- [NUEVA PETICIÓN RECIBIDA] ---")
    
    try:
        # --- 1. Obtener IP del cliente ---
        ip_address = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
        print(f"INFO: IP detectada: {ip_address}")

        # --- 2. Geolocalización de la IP ---
        country_code = None
        try:
            print("INFO: Consultando API ip-api.com...")
            response = requests.get(
                f'http://ip-api.com/json/{ip_address}?fields=countryCode,status', 
                timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success':
                    country_code = data.get('countryCode')
                    print(f"INFO: País detectado: {country_code}")
                else:
                    print(f"WARN: API respondió pero sin éxito: {data}")
            else:
                print(f"WARN: API respondió con código {response.status_code}")
        except Exception as e:
            print(f"ERROR: Fallo en geolocalización: {e}")

        # --- 3. Extraer payload de Dink (soporte para JSON y Multipart) ---
        dink_payload = None
        files_to_forward = None

        if request.is_json:
            dink_payload = request.get_json()
        elif request.content_type and 'multipart/form-data' in request.content_type:
            payload_str = request.form.get('payload_json')
            if payload_str:
                try:
                    dink_payload = json.loads(payload_str)
                except json.JSONDecodeError:
                    print("ERROR: JSON malformado en payload_json")
            
            if request.files:
                files_to_forward = {}
                for key, f in request.files.items():
                    files_to_forward[key] = (f.filename, f.read(), f.content_type)

        if not dink_payload:
            dink_payload = request.get_json(force=True, silent=True)

        if not dink_payload:
            print("ERROR: No se pudo obtener payload JSON.")
            return jsonify({"error": "No JSON payload"}), 400

        # --- 4. Extraer información del jugador y tipo de evento ---
        player_name = dink_payload.get('playerName') or dink_payload.get('player_name') or 'Desconocido'
        
        # Intentar obtener el tipo desde la estructura de Dink
        notification_type = dink_payload.get('type')
        # Si no viene en 'type', buscar en 'extra' (como en tus logs)
        if not notification_type:
            notification_type = dink_payload.get('extra', {}).get('type', 'General')
        
        print(f"INFO: Procesando: Jugador={player_name}, Tipo={notification_type}, País={country_code}")

        # --- 5. LÓGICA PRINCIPAL: PAÍS PERMITIDO O NO ---
        if country_code and country_code in ALLOWED_COUNTRIES:
            # --- CASO: PAÍS PERMITIDO ---
            print(f"DECISIÓN: País {country_code} PERMITIDO. Reenviando...")

            # Enviar alerta al STAFF (solo informativa de que se permitió)
            if STAFF_LOG_WEBHOOK_URL:
                staff_alert = {
                    "content": f"✅ **Actividad Autorizada**",
                    "embeds": [{
                        "color": 5763719,  # Verde
                        "title": "Conexión Válida Detectada",
                        "fields": [
                            {"name": "Jugador (RSN)", "value": f"`{player_name}`", "inline": True},
                            {"name": "País Detectado", "value": f"`{country_code}`", "inline": True},
                            {"name": "IP", "value": f"`{ip_address}`", "inline": True},
                            {"name": "Tipo", "value": f"`{notification_type}`", "inline": True}
                        ],
                        "footer": {"text": "La notificación ha sido reenviada al canal correspondiente."}
                    }]
                }
                try:
                    requests.post(STAFF_LOG_WEBHOOK_URL, json=staff_alert, headers=DISCORD_HEADERS, timeout=5)
                except Exception as e:
                    print(f"WARN: No se pudo enviar log de éxito a staff: {e}")

            # Determinar a qué webhook final reenviar el mensaje original
            target_webhook = REAL_DISCORD_WEBHOOK_URL
            if notification_type in ['LOGIN', 'LOGOUT'] and LOGIN_LOGOUT_WEBHOOK_URL:
                target_webhook = LOGIN_LOGOUT_WEBHOOK_URL
                print(f"INFO: Redirigiendo {notification_type} a webhook específico.")

            if target_webhook:
                try:
                    print(f"INFO: Reenviando a Discord final...")
                    
                    # Preparar el envío (con o sin archivos)
                    if files_to_forward:
                        # Si hay imágenes, las reenviamos
                        post_response = requests.post(
                            target_webhook,
                            files=files_to_forward,
                            data={'payload_json': json.dumps(dink_payload)},
                            headers=DISCORD_HEADERS,
                            timeout=20
                        )
                    else:
                        # Si es solo JSON
                        post_response = requests.post(
                            target_webhook,
                            json=dink_payload,
                            headers=DISCORD_HEADERS,
                            timeout=20
                        )
                    
                    # Si hay rate limit, solo lo informamos pero no reintentamos en bucle
                    if post_response.status_code == 429:
                        print(f"WARN: Rate limit de Discord (429), el mensaje podría no haberse entregado.")
                    else:
                        print(f"INFO: Discord respondió con código {post_response.status_code}")
                        post_response.raise_for_status()
                        
                except Exception as e:
                    print(f"ERROR: Fallo al reenviar a Discord: {e}")
            else:
                print(f"ERROR: No hay webhook de destino configurado.")

        else:
            # --- CASO: PAÍS NO PERMITIDO O DESCONOCIDO ---
            print(f"DECISIÓN: País {country_code} NO PERMITIDO. Bloqueando.")

            # Enviar ALERTA ROJA al STAFF
            if STAFF_LOG_WEBHOOK_URL:
                alert_payload = {
                    "content": f"🚨 **Alerta de IP No Autorizada** 🚨",
                    "embeds": [{
                        "color": 15158332,  # Rojo
                        "title": "Intento de Conexión desde Ubicación No Permitida",
                        "fields": [
                            {"name": "Jugador (RSN)", "value": f"`{player_name}`", "inline": True},
                            {"name": "Ubicación Detectada", "value": f"`{country_code or 'Desconocida'}`", "inline": True},
                            {"name": "Dirección IP", "value": f"`{ip_address}`", "inline": True}
                        ],
                        "footer": {"text": "La notificación de Dink ha sido bloqueada."}
                    }]
                }
                try:
                    print("INFO: Enviando alerta de bloqueo a staff...")
                    requests.post(STAFF_LOG_WEBHOOK_URL, json=alert_payload, headers=DISCORD_HEADERS, timeout=10)
                except Exception as e:
                    print(f"ERROR: No se pudo enviar alerta de staff: {e}")

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print(f"--- [ERROR INESPERADO] ---")
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": "Internal Server Error"}), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port)