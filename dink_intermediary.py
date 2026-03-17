import os
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import json
import sys
import time
from datetime import datetime
import threading
from queue import Queue
from dhooks import Webhook, Embed
import requests

# Cargar variables de entorno
load_dotenv()

app = Flask(__name__)

# Forzar logs inmediatos (importante para Render)
sys.stdout.reconfigure(line_buffering=True)

# --- CONFIGURACIÓN DESDE VARIABLES DE ENTORNO ---
REAL_DISCORD_WEBHOOK_URL = os.getenv("REAL_DISCORD_WEBHOOK_URL")
STAFF_LOG_WEBHOOK_URL = os.getenv("STAFF_LOG_WEBHOOK_URL")
LOGIN_LOGOUT_WEBHOOK_URL = os.getenv("LOGIN_LOGOUT_WEBHOOK_URL")

# Países permitidos (separados por comas: US,GB,VE, etc)
ALLOWED_COUNTRIES_STR = os.getenv("ALLOWED_COUNTRIES", "US,GB")
ALLOWED_COUNTRIES = [country.strip().upper() for country in ALLOWED_COUNTRIES_STR.split(',')]

# Cola para mensajes cuando hay rate limit
message_queue = Queue()
MAX_RETRIES = 3  # Número máximo de reintentos para mensajes en cola

# --- FUNCIÓN DE ENVÍO A DISCORD (CON DHOOKS) ---
def send_to_discord(webhook_url, content=None, embed=None, files=None):
    """
    Envía mensajes a Discord usando dhooks
    Retorna: True si éxito, False si falló
    """
    try:
        hook = Webhook(webhook_url)
        
        if files:
            # Si hay archivos (como imágenes), usamos requests directamente
            # porque dhooks no maneja archivos bien
            files_dict = {}
            for key, (filename, data, mime) in files.items():
                files_dict[key] = (filename, data, mime)
            
            payload = {'payload_json': json.dumps(content) if content else '{}'}
            response = requests.post(webhook_url, data=payload, files=files_dict, timeout=10)
            return response.status_code in [200, 204]
        else:
            # Si no hay archivos, usamos dhooks que es más confiable
            if embed:
                hook.send(embed=embed)
            else:
                hook.send(content)
            return True
            
    except Exception as e:
        print(f"  ❌ Error enviando a Discord: {e}")
        return False

# --- PROCESADOR DE COLA (SE EJECUTA EN SEGUNDO PLANO) ---
def queue_processor():
    """Procesa los mensajes en cola cuando Discord lo permite"""
    print("🚀 Procesador de cola iniciado...")
    while True:
        try:
            if not message_queue.empty():
                msg = message_queue.get()
                print(f"\n📦 [COLA] Procesando mensaje (Intento {msg.get('retries', 0)+1}/{MAX_RETRIES})")
                
                # Intentar enviar
                success = send_to_discord(
                    msg['webhook_url'],
                    content=msg.get('content'),
                    embed=msg.get('embed'),
                    files=msg.get('files')
                )
                
                if not success:
                    # Reintentar si no ha excedido el límite
                    if msg.get('retries', 0) < MAX_RETRIES:
                        msg['retries'] = msg.get('retries', 0) + 1
                        # Esperar más tiempo en cada reintento (backoff exponencial)
                        wait_time = 5 * (2 ** (msg['retries'] - 1))
                        print(f"  ↻ Reintento {msg['retries']}/{MAX_RETRIES} en {wait_time}s")
                        time.sleep(wait_time)
                        message_queue.put(msg)
                    else:
                        print(f"  ✗ Mensaje DESCARTADO después de {MAX_RETRIES} intentos")
                else:
                    print(f"  ✅ Mensaje enviado exitosamente desde la cola")
                
                # Pequeña pausa entre mensajes
                time.sleep(2)
            else:
                # Si la cola está vacía, esperamos 5 segundos
                time.sleep(5)
                
        except Exception as e:
            print(f"💥 Error en queue_processor: {e}")
            time.sleep(30)

# Iniciar el procesador de cola
threading.Thread(target=queue_processor, daemon=True).start()

# --- RUTAS DE DIAGNÓSTICO ---
@app.route('/')
def index():
    return jsonify({
        "status": "Dink Proxy Activo",
        "queue_size": message_queue.qsize(),
        "allowed_countries": ALLOWED_COUNTRIES,
        "endpoints": {
            "webhook": "/api/webhooks/dink (POST)",
            "test": "/test (GET)"
        }
    })

@app.route('/test')
def test_discord():
    """Ruta para probar la conexión con Discord"""
    if not STAFF_LOG_WEBHOOK_URL:
        return jsonify({"error": "STAFF_LOG_WEBHOOK_URL no configurado"}), 500
    
    try:
        # Crear un embed de prueba
        embed = Embed(
            title='🧪 Prueba de Conexión Exitosa',
            description=f'Servidor funcionando correctamente',
            color=0x00ff00,
            timestamp=datetime.now().isoformat()
        )
        embed.add_field(name='Países Permitidos', value=', '.join(ALLOWED_COUNTRIES))
        embed.add_field(name='Cola', value=str(message_queue.qsize()))
        
        # Enviar
        hook = Webhook(STAFF_LOG_WEBHOOK_URL)
        hook.send(embed=embed)
        
        return jsonify({"status": "ok", "message": "Prueba enviada correctamente"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/queue')
def queue_status():
    """Ver estado de la cola"""
    return jsonify({
        "queue_size": message_queue.qsize(),
        "max_retries": MAX_RETRIES,
        "queue_contents": list(message_queue.queue) if not message_queue.empty() else []
    })

# --- WEBHOOK PRINCIPAL (DONDE DINK ENVÍA LOS DATOS) ---
@app.route('/api/webhooks/dink', methods=['POST', 'GET'])
def dink_webhook_handler():
    if request.method == 'GET':
        return jsonify({
            "status": "Webhook activo",
            "queue_size": message_queue.qsize(),
            "message": "Envía POST aquí con las notificaciones de Dink"
        }), 200

    # --- PROCESAR POST ---
    print("\n" + "="*70)
    print(f"📨 NUEVA PETICIÓN - {datetime.now().isoformat()}")
    
    try:
        # 1. Obtener IP del cliente
        ip_address = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
        print(f"🌐 IP: {ip_address}")

        # 2. Geolocalización
        country_code = None
        try:
            geo_response = requests.get(
                f'http://ip-api.com/json/{ip_address}?fields=status,countryCode',
                timeout=3
            )
            if geo_response.status_code == 200:
                geo_data = geo_response.json()
                if geo_data.get('status') == 'success':
                    country_code = geo_data.get('countryCode')
                    print(f"📍 País detectado: {country_code}")
                else:
                    print(f"⚠️ Geolocalización: API sin éxito")
            else:
                print(f"⚠️ Geolocalización: HTTP {geo_response.status_code}")
        except Exception as e:
            print(f"⚠️ Geolocalización: Error - {e}")

        # 3. Obtener payload de Dink (JSON o Multipart)
        dink_payload = None
        files = None

        if request.is_json:
            dink_payload = request.get_json()
            print(f"📦 Formato: JSON")
        elif 'multipart/form-data' in request.content_type:
            payload_str = request.form.get('payload_json')
            if payload_str:
                try:
                    dink_payload = json.loads(payload_str)
                except:
                    print(f"⚠️ Error parseando payload_json")
            
            if request.files:
                files = {}
                for key, file in request.files.items():
                    files[key] = (file.filename, file.read(), file.content_type)
            print(f"📸 Formato: Multipart con {len(files or [])} archivo(s)")

        if not dink_payload:
            print("❌ No se recibió payload válido")
            return jsonify({"error": "No valid payload"}), 400

        # 4. Extraer información del jugador
        player_name = dink_payload.get('playerName') or dink_payload.get('player_name', 'Desconocido')
        notification_type = dink_payload.get('type') or dink_payload.get('extra', {}).get('type', 'General')
        
        print(f"👤 Jugador: {player_name}")
        print(f"📌 Tipo: {notification_type}")

        # 5. LÓGICA DE DECISIÓN
        if country_code and country_code in ALLOWED_COUNTRIES:
            print(f"✅ DECISIÓN: País {country_code} PERMITIDO")
            
            # --- Enviar LOG al staff (actividad permitida) ---
            if STAFF_LOG_WEBHOOK_URL:
                # Crear embed para el log de staff
                staff_embed = Embed(
                    title='✅ Actividad Autorizada',
                    color=0x00ff00,
                    timestamp=datetime.now().isoformat()
                )
                staff_embed.add_field(name='Jugador', value=f'`{player_name}`', inline=True)
                staff_embed.add_field(name='País', value=f'`{country_code}`', inline=True)
                staff_embed.add_field(name='IP', value=f'`{ip_address}`', inline=True)
                staff_embed.add_field(name='Tipo', value=f'`{notification_type}`', inline=True)
                
                # Intentar enviar, si falla, encolar
                if not send_to_discord(STAFF_LOG_WEBHOOK_URL, embed=staff_embed):
                    message_queue.put({
                        'webhook_url': STAFF_LOG_WEBHOOK_URL,
                        'embed': staff_embed,
                        'retries': 0
                    })
                    print(f"  📥 Staff log ENCOLADO")

            # --- Reenviar mensaje original a su destino final ---
            target_webhook = REAL_DISCORD_WEBHOOK_URL
            if notification_type in ['LOGIN', 'LOGOUT'] and LOGIN_LOGOUT_WEBHOOK_URL:
                target_webhook = LOGIN_LOGOUT_WEBHOOK_URL
                print(f"  📨 Usando webhook específico para {notification_type}")

            if target_webhook:
                if not send_to_discord(target_webhook, content=dink_payload, files=files):
                    message_queue.put({
                        'webhook_url': target_webhook,
                        'content': dink_payload,
                        'files': files,
                        'retries': 0
                    })
                    print(f"  📥 Mensaje original ENCOLADO")

        else:
            motivo = "DESCONOCIDO" if not country_code else f"{country_code} (NO permitido)"
            print(f"❌ DECISIÓN: País {motivo} - BLOQUEADO")
            
            # --- Enviar ALERTA al staff (intento bloqueado) ---
            if STAFF_LOG_WEBHOOK_URL:
                alert_embed = Embed(
                    title='🚨 IP No Autorizada - Intento Bloqueado',
                    color=0xff0000,
                    timestamp=datetime.now().isoformat()
                )
                alert_embed.add_field(name='Jugador', value=f'`{player_name}`', inline=True)
                alert_embed.add_field(name='País Detectado', value=f'`{country_code or "Desconocido"}`', inline=True)
                alert_embed.add_field(name='IP', value=f'`{ip_address}`', inline=True)
                alert_embed.add_field(name='Tipo', value=f'`{notification_type}`', inline=True)
                
                if not send_to_discord(STAFF_LOG_WEBHOOK_URL, embed=alert_embed):
                    message_queue.put({
                        'webhook_url': STAFF_LOG_WEBHOOK_URL,
                        'embed': alert_embed,
                        'retries': 0
                    })
                    print(f"  📥 Alerta ENCOLADA")

        print(f"📊 Cola actual: {message_queue.qsize()} mensajes")
        print("="*70 + "\n")

        return jsonify({
            "status": "ok",
            "queue_size": message_queue.qsize()
        }), 200

    except Exception as e:
        print(f"💥 ERROR CRÍTICO: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": "Internal Server Error"}), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    print(f"\n{'='*50}")
    print(f"🚀 Servidor Dink Proxy iniciado")
    print(f"📡 Puerto: {port}")
    print(f"✅ Países permitidos: {ALLOWED_COUNTRIES}")
    print(f"📊 Cola de respaldo: ACTIVA")
    print(f"🔄 Procesador de cola: ACTIVO")
    print(f"{'='*50}\n")
    app.run(host='0.0.0.0', port=port, debug=False)