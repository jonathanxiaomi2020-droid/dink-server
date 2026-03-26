import os
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import json
import sys
import time
from datetime import datetime
import requests
import logging

load_dotenv()
app = Flask(__name__)

# --- CONFIGURACIÓN DE LOGS (MEJORADO) ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)  # Asegura que salga a stdout para Render
    ]
)

# --- RADAR DE DIAGNÓSTICO ---
@app.before_request
def log_every_request():
    app.logger.info(f"🔔 [RADAR] {request.method} {request.path}")
    app.logger.info(f"   -> IP: {request.remote_addr}")
    app.logger.info(f"   -> Headers: {dict(request.headers)}")
    
    # Mostrar el body si es POST
    if request.method == 'POST':
        try:
            body = request.get_json()
            app.logger.info(f"   -> Body: {json.dumps(body, indent=2)}")
        except:
            app.logger.info(f"   -> Body (raw): {request.data}")

# --- CONFIGURACIÓN DE WEBHOOKS ---
REAL_DISCORD_WEBHOOK_URL = os.getenv("REAL_DISCORD_WEBHOOK_URL")
STAFF_LOG_WEBHOOK_URL = os.getenv("STAFF_LOG_WEBHOOK_URL")
LOGIN_LOGOUT_WEBHOOK_URL = os.getenv("LOGIN_LOGOUT_WEBHOOK_URL")

# Países permitidos
ALLOWED_COUNTRIES = [c.strip().upper() for c in os.getenv("ALLOWED_COUNTRIES", "US,GB,VE").split(',')]

app.logger.info(f"✅ Webhooks configurados:")
app.logger.info(f"   - Main: {'✅' if REAL_DISCORD_WEBHOOK_URL else '❌'}")
app.logger.info(f"   - Staff: {'✅' if STAFF_LOG_WEBHOOK_URL else '❌'}")
app.logger.info(f"   - Login: {'✅' if LOGIN_LOGOUT_WEBHOOK_URL else '❌'}")
app.logger.info(f"✅ Países permitidos: {ALLOWED_COUNTRIES}")

# --- ENDPOINT PRINCIPAL ---
@app.route('/api/proxy-destino', methods=['GET', 'POST'], strict_slashes=False)
def proxy_destino():
    """Recibe los webhooks desde Hookdeck"""
    
    app.logger.info("\n" + "="*70)
    app.logger.info("📨 SOLICITUD RECIBIDA EN /api/proxy-destino")
    app.logger.info("="*70)
    
    # Si es GET, responder con status
    if request.method == 'GET':
        app.logger.info("✅ GET recibido (health check de Hookdeck)")
        return jsonify({"status": "online", "endpoint": "/api/proxy-destino"}), 200

    # Si es POST, procesar datos
    try:
        # Obtener IP y País
        ip_address = request.headers.get('Cf-Connecting-Ip') or \
                    request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
        country_code = request.headers.get('Cf-Ipcountry', 'XX').upper()
        
        app.logger.info(f"🌐 IP: {ip_address}")
        app.logger.info(f"📍 País: {country_code}")

        # Obtener payload
        payload = request.get_json()
        
        if not payload:
            app.logger.error("❌ No hay payload JSON")
            return jsonify({"error": "No payload"}), 400

        app.logger.info(f"📦 Payload recibido: {json.dumps(payload, indent=2)}")

        # Extraer información
        player_name = payload.get('playerName') or payload.get('player_name', 'Desconocido')
        notification_type = payload.get('type') or payload.get('extra', {}).get('type', 'General')
        
        app.logger.info(f"👤 Jugador: {player_name}")
        app.logger.info(f"📌 Tipo: {notification_type}")

        # Verificar país
        is_allowed = country_code in ALLOWED_COUNTRIES if country_code else True
        
        if is_allowed:
            app.logger.info(f"✅ PAÍS PERMITIDO: {country_code}")
            
            # Determinar webhook de destino
            if notification_type in ['LOGIN', 'LOGOUT'] and LOGIN_LOGOUT_WEBHOOK_URL:
                target_webhook = LOGIN_LOGOUT_WEBHOOK_URL
                app.logger.info(f"📌 Usando webhook de LOGIN/LOGOUT")
            else:
                target_webhook = REAL_DISCORD_WEBHOOK_URL
                app.logger.info(f"📌 Usando webhook principal")

            if not target_webhook:
                app.logger.error("❌ ERROR: No hay webhook configurado")
                return jsonify({"error": "No webhook configured"}), 500

            # Enviar a Discord
            app.logger.info(f"📤 Enviando a Discord...")
            response = requests.post(target_webhook, json=payload, timeout=10)
            
            app.logger.info(f"📡 Discord respondió: {response.status_code}")
            
            if response.status_code in [200, 204]:
                app.logger.info("✅ ¡Mensaje enviado a Discord correctamente!")
            elif response.status_code == 429:
                app.logger.warning("⚠️ Discord Rate Limit (429) - Esperando...")
                time.sleep(2)
                response = requests.post(target_webhook, json=payload, timeout=10)
                app.logger.info(f"🔄 Reintento: {response.status_code}")
            else:
                app.logger.warning(f"⚠️ Discord respondió {response.status_code}: {response.text}")

        else:
            app.logger.warning(f"❌ PAÍS NO PERMITIDO: {country_code}")
            # Aquí puedes añadir lógica de bloqueo

        app.logger.info("="*70 + "\n")
        return jsonify({"status": "ok"}), 200

    except Exception as e:
        app.logger.error(f"❌ EXCEPCIÓN: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

# --- ENDPOINT DE PRUEBA ---
@app.route('/test')
def test():
    return jsonify({
        "status": "ok",
        "message": "Servidor funcionando correctamente",
        "endpoint": "/api/proxy-destino",
        "paises_permitidos": ALLOWED_COUNTRIES,
        "webhooks": {
            "Main": "✅" if REAL_DISCORD_WEBHOOK_URL else "❌",
            "Staff": "✅" if STAFF_LOG_WEBHOOK_URL else "❌",
            "Login": "✅" if LOGIN_LOGOUT_WEBHOOK_URL else "❌"
        }
    })

@app.route('/')
def index():
    return jsonify({
        "status": "Servidor Hookdeck Activo",
        "instrucciones": {
            "1": "URL en Dink: https://hkdk.events/knvi5xshnnwno6",
            "2": "Endpoint: /api/proxy-destino",
            "3": "Test: /test"
        }
    })

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.logger.info(f"\n🚀 SERVIDOR INICIADO")
    app.logger.info(f"   Puerto: {port}")
    app.logger.info(f"   Endpoint: /api/proxy-destino")
    app.logger.info(f"   Países: {ALLOWED_COUNTRIES}\n")
    
    app.run(host='0.0.0.0', port=port)
