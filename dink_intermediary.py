import os
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import json
import sys
import time
from datetime import datetime
import threading
from queue import Queue
import hashlib

# Cargar variables de entorno
load_dotenv()

app = Flask(__name__)

# Forzar logs inmediatos
sys.stdout.reconfigure(line_buffering=True)

# --- CONFIGURACIÓN ---
REAL_DISCORD_WEBHOOK_URL = os.getenv("REAL_DISCORD_WEBHOOK_URL")
STAFF_LOG_WEBHOOK_URL = os.getenv("STAFF_LOG_WEBHOOK_URL")
LOGIN_LOGOUT_WEBHOOK_URL = os.getenv("LOGIN_LOGOUT_WEBHOOK_URL")

# Países permitidos
ALLOWED_COUNTRIES_STR = os.getenv("ALLOWED_COUNTRIES", "US,GB")
ALLOWED_COUNTRIES = [country.strip().upper() for country in ALLOWED_COUNTRIES_STR.split(',')]

# Cola para reintentos (evita perder mensajes por rate limit)
message_queue = Queue()
MAX_RETRIES = 3

# Headers para Discord
DISCORD_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

def send_to_discord_with_retry(webhook_url, payload, files=None, retry_count=0):
    """
    Envía a Discord con reintentos inteligentes y backoff exponencial
    """
    try:
        print(f"INFO: Intentando enviar a Discord (Intento {retry_count + 1})...")
        
        if files:
            response = requests.post(
                webhook_url,
                files=files,
                data={'payload_json': json.dumps(payload)},
                headers=DISCORD_HEADERS,
                timeout=20
            )
        else:
            response = requests.post(
                webhook_url,
                json=payload,
                headers=DISCORD_HEADERS,
                timeout=20
            )
        
        # Si es exitoso
        if response.status_code == 200 or response.status_code == 204:
            print(f"✅ INFO: Mensaje enviado correctamente a Discord")
            return True
            
        # Si hay rate limit
        elif response.status_code == 429:
            retry_after = 5  # Por defecto 5 segundos
            
            # Intentar obtener el tiempo de espera de Discord
            try:
                data = response.json()
                retry_after = float(data.get('retry_after', 5))
            except:
                pass
                
            print(f"⚠️  WARN: Rate limit (429). Esperando {retry_after}s...")
            
            if retry_count < MAX_RETRIES:
                # Esperar y reintentar
                time.sleep(retry_after + 1)
                return send_to_discord_with_retry(webhook_url, payload, files, retry_count + 1)
            else:
                # Si ya no quedan reintentos, guardar en cola
                print(f"❌ ERROR: Máximo de reintentos alcanzado. Guardando en cola para después.")
                message_queue.put({
                    'webhook_url': webhook_url,
                    'payload': payload,
                    'files': files,
                    'timestamp': time.time()
                })
                return False
        
        # Otros errores
        else:
            print(f"❌ ERROR: Discord respondió con código {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ ERROR: Excepción al enviar a Discord: {e}")
        if retry_count < MAX_RETRIES:
            time.sleep(2 ** retry_count)  # Backoff exponencial
            return send_to_discord_with_retry(webhook_url, payload, files, retry_count + 1)
        return False

def process_queue():
    """
    Hilo que procesa la cola de mensajes pendientes
    """
    while True:
        try:
            if not message_queue.empty():
                message = message_queue.get()
                
                # Si el mensaje tiene más de 5 minutos, lo descartamos
                if time.time() - message['timestamp'] > 300:  # 5 minutos
                    print(f"INFO: Descartando mensaje antiguo de la cola")
                    continue
                
                print(f"INFO: Procesando mensaje de la cola de respaldo...")
                send_to_discord_with_retry(
                    message['webhook_url'],
                    message['payload'],
                    message['files']
                )
            
            time.sleep(10)  # Revisar cada 10 segundos
            
        except Exception as e:
            print(f"ERROR en process_queue: {e}")
            time.sleep(30)

# Iniciar el hilo de la cola
queue_thread = threading.Thread(target=process_queue, daemon=True)
queue_thread.start()

@app.route('/')
def index():
    return jsonify({
        "status": "Dink webhook endpoint is active",
        "queue_size": message_queue.qsize()
    })

@app.route('/api/webhooks/dink', methods=['POST', 'GET'])
def dink_webhook_handler():
    if request.method == 'GET':
        return jsonify({
            "status": "URL correcta. Listo para recibir POST.",
            "queue_size": message_queue.qsize()
        }), 200

    print("\n--- [NUEVA PETICIÓN RECIBIDA] ---")
    request_id = hashlib.md5(str(time.time()).encode()).hexdigest()[:8]
    print(f"📋 Request ID: {request_id}")
    
    try:
        # --- 1. Obtener IP del cliente ---
        ip_address = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
        print(f"🌐 IP detectada: {ip_address}")

        # --- 2. Geolocalización ---
        country_code = None
        try:
            print("🔍 Consultando API ip-api.com...")
            response = requests.get(
                f'http://ip-api.com/json/{ip_address}?fields=countryCode,status', 
                timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success':
                    country_code = data.get('countryCode')
                    print(f"📍 País detectado: {country_code}")
                else:
                    print(f"⚠️  WARN: API sin éxito: {data}")
        except Exception as e:
            print(f"⚠️  WARN: Fallo en geolocalización: {e}")

        # --- 3. Extraer payload ---
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
                    print("❌ ERROR: JSON malformado")
            
            if request.files:
                files_to_forward = {}
                for key, f in request.files.items():
                    files_to_forward[key] = (f.filename, f.read(), f.content_type)

        if not dink_payload:
            dink_payload = request.get_json(force=True, silent=True)

        if not dink_payload:
            print("❌ ERROR: No se pudo obtener payload")
            return jsonify({"error": "No JSON payload"}), 400

        # --- 4. Extraer información ---
        player_name = dink_payload.get('playerName') or dink_payload.get('player_name') or 'Desconocido'
        
        notification_type = dink_payload.get('type')
        if not notification_type:
            notification_type = dink_payload.get('extra', {}).get('type', 'General')
        
        print(f"👤 Jugador: {player_name}")
        print(f"📌 Tipo: {notification_type}")
        print(f"🌍 País: {country_code or 'Desconocido'}")

        # --- 5. LÓGICA PRINCIPAL ---
        if country_code and country_code in ALLOWED_COUNTRIES:
            # ✅ PAÍS PERMITIDO
            print(f"✅ DECISIÓN: País {country_code} PERMITIDO")

            # Enviar log al staff (sin bloquear)
            if STAFF_LOG_WEBHOOK_URL:
                staff_alert = {
                    "content": f"✅ **Actividad Autorizada**",
                    "embeds": [{
                        "color": 5763719,
                        "title": "Conexión Válida Detectada",
                        "fields": [
                            {"name": "Jugador (RSN)", "value": f"`{player_name}`", "inline": True},
                            {"name": "País Detectado", "value": f"`{country_code}`", "inline": True},
                            {"name": "IP", "value": f"`{ip_address}`", "inline": True},
                            {"name": "Tipo", "value": f"`{notification_type}`", "inline": True}
                        ],
                        "footer": {"text": f"ID: {request_id}"}
                    }]
                }
                # Envío en segundo plano (no esperamos respuesta)
                threading.Thread(
                    target=send_to_discord_with_retry,
                    args=(STAFF_LOG_WEBHOOK_URL, staff_alert, None)
                ).start()

            # Determinar webhook final
            target_webhook = REAL_DISCORD_WEBHOOK_URL
            if notification_type in ['LOGIN', 'LOGOUT'] and LOGIN_LOGOUT_WEBHOOK_URL:
                target_webhook = LOGIN_LOGOUT_WEBHOOK_URL
                print(f"📨 Redirigiendo {notification_type} a webhook específico")

            # Reenviar mensaje original
            if target_webhook:
                threading.Thread(
                    target=send_to_discord_with_retry,
                    args=(target_webhook, dink_payload, files_to_forward)
                ).start()
                print("📤 Mensaje enviado a cola de procesamiento")

        else:
            # ❌ PAÍS NO PERMITIDO
            print(f"❌ DECISIÓN: País {country_code} NO PERMITIDO")

            # Alerta roja al staff
            if STAFF_LOG_WEBHOOK_URL:
                alert_payload = {
                    "content": f"🚨 **Alerta de IP No Autorizada** 🚨",
                    "embeds": [{
                        "color": 15158332,
                        "title": "Intento de Conexión desde Ubicación No Permitida",
                        "fields": [
                            {"name": "Jugador (RSN)", "value": f"`{player_name}`", "inline": True},
                            {"name": "Ubicación Detectada", "value": f"`{country_code or 'Desconocida'}`", "inline": True},
                            {"name": "Dirección IP", "value": f"`{ip_address}`", "inline": True}
                        ],
                        "footer": {"text": f"ID: {request_id} | Notificación bloqueada"}
                    }]
                }
                threading.Thread(
                    target=send_to_discord_with_retry,
                    args=(STAFF_LOG_WEBHOOK_URL, alert_payload, None)
                ).start()
                print("🚨 Alerta de seguridad enviada")

        return jsonify({
            "status": "ok",
            "request_id": request_id,
            "queue_size": message_queue.qsize()
        }), 200

    except Exception as e:
        print(f"💥 ERROR INESPERADO: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    print(f"🚀 Servidor iniciado en puerto {port}")
    print(f"✅ Países permitidos: {ALLOWED_COUNTRIES}")
    print(f"📊 Cola de respaldo activa")
    app.run(host='0.0.0.0', port=port)