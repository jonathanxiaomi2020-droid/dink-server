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
import traceback

# Cargar variables de entorno
load_dotenv()

app = Flask(__name__)

# Forzar logs inmediatos (IMPORTANTE para Render)
sys.stdout.reconfigure(line_buffering=True)

# --- CONFIGURACIÓN ---
REAL_DISCORD_WEBHOOK_URL = os.getenv("REAL_DISCORD_WEBHOOK_URL")
STAFF_LOG_WEBHOOK_URL = os.getenv("STAFF_LOG_WEBHOOK_URL")
LOGIN_LOGOUT_WEBHOOK_URL = os.getenv("LOGIN_LOGOUT_WEBHOOK_URL")

# Países permitidos
ALLOWED_COUNTRIES_STR = os.getenv("ALLOWED_COUNTRIES", "US,GB")
ALLOWED_COUNTRIES = [country.strip().upper() for country in ALLOWED_COUNTRIES_STR.split(',')]

# Cola para mensajes (Thread-safe)
message_queue = Queue()
MAX_RETRIES = 5  # Aumentamos reintentos para la cola

# Headers para Discord (simulando navegador)
DISCORD_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# --- FUNCIÓN MEJORADA PARA ENVÍO A DISCORD ---
def send_to_discord(webhook_url, payload, files=None, is_retry=False):
    """Envía a Discord con manejo de errores detallado."""
    try:
        if files:
            response = requests.post(
                webhook_url,
                files=files,
                data={'payload_json': json.dumps(payload)},
                headers=DISCORD_HEADERS,
                timeout=15
            )
        else:
            response = requests.post(
                webhook_url,
                json=payload,
                headers=DISCORD_HEADERS,
                timeout=15
            )
        
        # Éxito
        if response.status_code in [200, 204]:
            print(f"  ✅ Enviado correctamente a Discord")
            return True
        
        # Rate Limit (429)
        elif response.status_code == 429:
            retry_after = 5
            try:
                retry_after = float(response.json().get('retry_after', 5))
            except:
                pass
            print(f"  ⚠️ Rate limit (429). Esperar {retry_after}s. (Reintento: {is_retry})")
            time.sleep(retry_after)  # Esperamos el tiempo que indica Discord
            return False  # Indicamos que no se envió para posible reintento
        
        # Otros errores
        else:
            print(f"  ❌ Error HTTP {response.status_code}: {response.text[:200]}")
            return False
            
    except requests.exceptions.Timeout:
        print(f"  ⚠️ Timeout en conexión a Discord")
        return False
    except Exception as e:
        print(f"  ❌ Excepción en send_to_discord: {e}")
        return False

# --- PROCESADOR DE COLA MEJORADO ---
def queue_processor():
    """Procesa la cola de mensajes con reintentos y backoff."""
    print("🚀 Procesador de cola iniciado...")
    while True:
        try:
            if not message_queue.empty():
                msg = message_queue.get()
                print(f"\n📦 [QUEUE] Procesando mensaje (Intento {msg.get('retries', 0)+1}/MAX)...")
                
                success = send_to_discord(
                    msg['webhook_url'],
                    msg['payload'],
                    msg.get('files'),
                    is_retry=True
                )
                
                if not success:
                    # Reintentar hasta MAX_RETRIES
                    if msg.get('retries', 0) < MAX_RETRIES:
                        msg['retries'] = msg.get('retries', 0) + 1
                        # Backoff exponencial: esperar más en cada reintento
                        wait_time = 5 * (2 ** (msg['retries'] - 1))
                        print(f"  ↻ Reintento {msg['retries']}/{MAX_RETRIES} en {wait_time}s")
                        time.sleep(wait_time)
                        message_queue.put(msg)  # Volver a la cola
                    else:
                        print(f"  ✗ Mensaje DESCARTADO después de {MAX_RETRIES} intentos")
                else:
                    print(f"  ✅ Mensaje procesado exitosamente desde la cola")
                
                # Pequeña pausa entre mensajes para no saturar
                time.sleep(2)
            else:
                # Si la cola está vacía, esperamos un poco antes de revisar de nuevo
                time.sleep(5)
                
        except Exception as e:
            print(f"💥 Error CRÍTICO en queue_processor: {e}")
            traceback.print_exc()
            time.sleep(30)  # Esperar más si hay error crítico

# Iniciar procesador de cola (DAEMON = True para que se cierre al apagar la app)
queue_thread = threading.Thread(target=queue_processor, daemon=True)
queue_thread.start()

# --- RUTAS DE DIAGNÓSTICO ---
@app.route('/')
def index():
    return jsonify({
        "status": "Dink webhook endpoint ACTIVE",
        "queue_size": message_queue.qsize(),
        "endpoints": {
            "webhook": "/api/webhooks/dink (POST)",
            "queue_status": "/queue",
            "test": "/test"
        }
    })

@app.route('/queue')
def queue_status():
    """Ver estado detallado de la cola"""
    return jsonify({
        "queue_size": message_queue.qsize(),
        "max_retries": MAX_RETRIES,
        "allowed_countries": ALLOWED_COUNTRIES,
        "webhooks_configured": {
            "real": bool(REAL_DISCORD_WEBHOOK_URL),
            "staff": bool(STAFF_LOG_WEBHOOK_URL),
            "login_logout": bool(LOGIN_LOGOUT_WEBHOOK_URL)
        }
    })

@app.route('/test')
def test_discord():
    """Ruta de prueba para verificar conexión con Discord"""
    if not STAFF_LOG_WEBHOOK_URL:
        return jsonify({"error": "STAFF_LOG_WEBHOOK_URL no configurado"}), 500
    
    test_payload = {
        "content": "🧪 **Mensaje de prueba** desde el servidor",
        "embeds": [{
            "color": 5763719,
            "title": "Prueba de Conexión",
            "description": f"Timestamp: {datetime.now().isoformat()}"
        }]
    }
    
    success = send_to_discord(STAFF_LOG_WEBHOOK_URL, test_payload)
    if success:
        return jsonify({"status": "ok", "message": "Mensaje de prueba enviado"})
    else:
        return jsonify({"status": "error", "message": "Falló el envío"}), 500

# --- WEBHOOK PRINCIPAL ---
@app.route('/api/webhooks/dink', methods=['POST', 'GET'])
def dink_webhook_handler():
    if request.method == 'GET':
        return jsonify({
            "status": "URL correcta. Listo para recibir POST.",
            "queue_size": message_queue.qsize()
        }), 200

    print("\n" + "="*70)
    print(f"📨 NUEVA PETICIÓN - {datetime.now().isoformat()}")
    
    try:
        # 1. Obtener IP
        ip_address = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
        print(f"🌐 IP: {ip_address}")

        # 2. Geolocalización MEJORADA
        country_code = None
        geo_failed = False
        try:
            geo = requests.get(
                f'http://ip-api.com/json/{ip_address}?fields=status,countryCode',
                timeout=3
            )
            if geo.status_code == 200:
                data = geo.json()
                if data.get('status') == 'success':
                    country_code = data.get('countryCode')
                    print(f"📍 País: {country_code}")
                else:
                    geo_failed = True
                    print(f"⚠️ Geo: API sin éxito")
            else:
                geo_failed = True
                print(f"⚠️ Geo: HTTP {geo.status_code}")
        except Exception as e:
            geo_failed = True
            print(f"⚠️ Geo error: {e}")

        # 3. Obtener payload (JSON o Multipart)
        dink_payload = None
        files = None

        if request.is_json:
            dink_payload = request.get_json()
            print(f"📦 JSON recibido")
        elif 'multipart/form-data' in request.content_type:
            payload_str = request.form.get('payload_json')
            if payload_str:
                try:
                    dink_payload = json.loads(payload_str)
                except:
                    print(f"⚠️ Error parseando payload_json")
            if request.files:
                files = {}
                for key, f in request.files.items():
                    files[key] = (f.filename, f.read(), f.content_type)
            print(f"📸 Multipart con {len(files or {})} archivo(s)")

        if not dink_payload:
            print("❌ No hay payload válido")
            return jsonify({"error": "No valid payload"}), 400

        # 4. Extraer info del jugador
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
                    print(f"  📥 Staff log ENCOLADO (Total cola: {message_queue.qsize()+1})")

            # Reenviar mensaje original
            target = REAL_DISCORD_WEBHOOK_URL
            if notification_type in ['LOGIN', 'LOGOUT'] and LOGIN_LOGOUT_WEBHOOK_URL:
                target = LOGIN_LOGOUT_WEBHOOK_URL
                print(f"  📨 Usando webhook específico para {notification_type}")

            if target:
                if not send_to_discord(target, dink_payload, files):
                    message_queue.put({
                        'webhook_url': target,
                        'payload': dink_payload,
                        'files': files,
                        'retries': 0
                    })
                    print(f"  📥 Mensaje original ENCOLADO (Total cola: {message_queue.qsize()+1})")

        else:
            motivo = "DESCONOCIDO" if geo_failed or not country_code else f"{country_code} (No permitido)"
            print(f"❌ PAÍS NO PERMITIDO: {motivo}")
            
            # Alerta a staff
            if STAFF_LOG_WEBHOOK_URL:
                alert = {
                    "content": f"🚨 **IP No Autorizada**",
                    "embeds": [{
                        "color": 15158332,
                        "title": "Intento de Conexión Bloqueado",
                        "fields": [
                            {"name": "Jugador", "value": f"`{player_name}`", "inline": True},
                            {"name": "País Detectado", "value": f"`{country_code or 'Desconocido'}`", "inline": True},
                            {"name": "IP", "value": f"`{ip_address}`", "inline": True},
                            {"name": "Tipo", "value": f"`{notification_type}`", "inline": True}
                        ],
                        "footer": {"text": "Notificación de Dink bloqueada"}
                    }]
                }
                if not send_to_discord(STAFF_LOG_WEBHOOK_URL, alert):
                    message_queue.put({
                        'webhook_url': STAFF_LOG_WEBHOOK_URL,
                        'payload': alert,
                        'retries': 0
                    })
                    print(f"  📥 Alerta ENCOLADA (Total cola: {message_queue.qsize()+1})")

        print(f"📊 Cola actual: {message_queue.qsize()} mensajes")
        print("="*70 + "\n")

        return jsonify({
            "status": "ok",
            "queue_size": message_queue.qsize()
        }), 200

    except Exception as e:
        print(f"💥 ERROR CRÍTICO en handler: {e}")
        traceback.print_exc()
        return jsonify({"error": "Internal Server Error"}), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    print(f"\n{'='*50}")
    print(f"🚀 Servidor iniciado en puerto {port}")
    print(f"✅ Países permitidos: {ALLOWED_COUNTRIES}")
    print(f"📊 Mensajes en cola inicial: {message_queue.qsize()}")
    print(f"🔄 Procesador de cola: ACTIVO")
    print(f"{'='*50}\n")
    app.run(host='0.0.0.0', port=port, debug=False)  # debug=False para producción