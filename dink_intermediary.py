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

# Cola para mensajes
message_queue = Queue()
MAX_RETRIES = 3

# Headers para Discord
DISCORD_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

def send_to_discord(webhook_url, payload, files=None, is_retry=False):
    """Envía a Discord con manejo de errores"""
    try:
        if files:
            response = requests.post(
                webhook_url,
                files=files,
                data={'payload_json': json.dumps(payload)},
                headers=DISCORD_HEADERS,
                timeout=10
            )
        else:
            response = requests.post(
                webhook_url,
                json=payload,
                headers=DISCORD_HEADERS,
                timeout=10
            )
        
        if response.status_code in [200, 204]:
            print(f"✅ Enviado correctamente a Discord")
            return True
        elif response.status_code == 429:
            print(f"⚠️ Rate limit (429) - { 'Reintentando' if not is_retry else 'Guardando en cola'}")
            return False
        else:
            print(f"❌ Error {response.status_code}: {response.text[:200]}")
            return False
    except Exception as e:
        print(f"❌ Excepción: {e}")
        return False

def queue_processor():
    """Procesa la cola de mensajes"""
    while True:
        try:
            if not message_queue.empty():
                msg = message_queue.get()
                print(f"\n📦 Procesando mensaje de la cola...")
                
                success = send_to_discord(
                    msg['webhook_url'],
                    msg['payload'],
                    msg.get('files'),
                    is_retry=True
                )
                
                if not success:
                    # Reintentar hasta 3 veces
                    if msg.get('retries', 0) < 3:
                        msg['retries'] = msg.get('retries', 0) + 1
                        message_queue.put(msg)
                        print(f"↻ Reintento {msg['retries']}/3")
                    else:
                        print(f"✗ Mensaje descartado después de 3 intentos")
                
                time.sleep(5)  # Esperar entre mensajes
            time.sleep(10)
        except Exception as e:
            print(f"Error en queue_processor: {e}")
            time.sleep(30)

# Iniciar procesador de cola
threading.Thread(target=queue_processor, daemon=True).start()

@app.route('/')
def index():
    return jsonify({
        "status": "Dink webhook endpoint is active",
        "queue_size": message_queue.qsize(),
        "endpoints": {
            "webhook": "/api/webhooks/dink",
            "queue_status": "/queue"
        }
    })

@app.route('/queue')
def queue_status():
    """Ver estado de la cola"""
    return jsonify({
        "queue_size": message_queue.qsize(),
        "messages_pending": list(message_queue.queue) if not message_queue.empty() else []
    })

@app.route('/api/webhooks/dink', methods=['POST', 'GET'])
def dink_webhook_handler():
    if request.method == 'GET':
        return jsonify({
            "status": "URL correcta. Listo para recibir POST.",
            "queue_size": message_queue.qsize()
        }), 200

    print("\n" + "="*60)
    print(f"📨 NUEVA PETICIÓN - {datetime.now().isoformat()}")
    
    try:
        # 1. Obtener IP
        ip_address = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
        print(f"🌐 IP: {ip_address}")

        # 2. Geolocalización
        country_code = None
        try:
            geo = requests.get(
                f'http://ip-api.com/json/{ip_address}?fields=countryCode,status',
                timeout=3
            )
            if geo.status_code == 200:
                data = geo.json()
                if data.get('status') == 'success':
                    country_code = data.get('countryCode')
                    print(f"📍 País: {country_code}")
        except Exception as e:
            print(f"⚠️ Geo error: {e}")

        # 3. Obtener payload
        dink_payload = None
        files = None

        if request.is_json:
            dink_payload = request.get_json()
            print(f"📦 JSON recibido")
        elif 'multipart/form-data' in request.content_type:
            payload_str = request.form.get('payload_json')
            if payload_str:
                dink_payload = json.loads(payload_str)
            if request.files:
                files = {}
                for key, f in request.files.items():
                    files[key] = (f.filename, f.read(), f.content_type)
            print(f"📸 Multipart con {len(files or {})} archivo(s)")

        if not dink_payload:
            print("❌ No hay payload")
            return jsonify({"error": "No payload"}), 400

        # 4. Extraer info
        player_name = dink_payload.get('playerName') or dink_payload.get('player_name', 'Desconocido')
        notification_type = dink_payload.get('type') or dink_payload.get('extra', {}).get('type', 'General')
        
        print(f"👤 Jugador: {player_name}")
        print(f"📌 Tipo: {notification_type}")

        # 5. DECISIÓN
        if country_code and country_code in ALLOWED_COUNTRIES:
            print(f"✅ PAÍS PERMITIDO: {country_code}")
            
            # Enviar a staff (log de actividad permitida)
            if STAFF_LOG_WEBHOOK_URL:
                staff_msg = {
                    "content": f"✅ **Actividad Autorizada**",
                    "embeds": [{
                        "color": 5763719,
                        "title": "Conexión Válida Detectada",
                        "fields": [
                            {"name": "Jugador", "value": f"`{player_name}`", "inline": True},
                            {"name": "País", "value": f"`{country_code}`", "inline": True},
                            {"name": "IP", "value": f"`{ip_address}`", "inline": True},
                            {"name": "Tipo", "value": f"`{notification_type}`", "inline": True}
                        ]
                    }]
                }
                if not send_to_discord(STAFF_LOG_WEBHOOK_URL, staff_msg):
                    message_queue.put({
                        'webhook_url': STAFF_LOG_WEBHOOK_URL,
                        'payload': staff_msg,
                        'retries': 0
                    })
                    print(f"📥 Staff log encolado")

            # Reenviar mensaje original
            target = REAL_DISCORD_WEBHOOK_URL
            if notification_type in ['LOGIN', 'LOGOUT'] and LOGIN_LOGOUT_WEBHOOK_URL:
                target = LOGIN_LOGOUT_WEBHOOK_URL
                print(f"📨 Usando webhook específico para {notification_type}")

            if target:
                if not send_to_discord(target, dink_payload, files):
                    message_queue.put({
                        'webhook_url': target,
                        'payload': dink_payload,
                        'files': files,
                        'retries': 0
                    })
                    print(f"📥 Mensaje original encolado")

        else:
            print(f"❌ PAÍS NO PERMITIDO: {country_code or 'Desconocido'}")
            
            # Alerta a staff
            if STAFF_LOG_WEBHOOK_URL:
                alert = {
                    "content": f"🚨 **IP No Autorizada**",
                    "embeds": [{
                        "color": 15158332,
                        "title": "Intento de Conexión Bloqueado",
                        "fields": [
                            {"name": "Jugador", "value": f"`{player_name}`", "inline": True},
                            {"name": "País", "value": f"`{country_code or 'Desconocido'}`", "inline": True},
                            {"name": "IP", "value": f"`{ip_address}`", "inline": True}
                        ]
                    }]
                }
                if not send_to_discord(STAFF_LOG_WEBHOOK_URL, alert):
                    message_queue.put({
                        'webhook_url': STAFF_LOG_WEBHOOK_URL,
                        'payload': alert,
                        'retries': 0
                    })
                    print(f"📥 Alerta encolada")

        print(f"📊 Cola actual: {message_queue.qsize()} mensajes")
        print("="*60 + "\n")

        return jsonify({
            "status": "ok",
            "queue_size": message_queue.qsize()
        }), 200

    except Exception as e:
        print(f"💥 ERROR: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    print(f"\n🚀 Servidor iniciado en puerto {port}")
    print(f"✅ Países permitidos: {ALLOWED_COUNTRIES}")
    print(f"📊 Mensajes en cola: {message_queue.qsize()}")
    app.run(host='0.0.0.0', port=port)