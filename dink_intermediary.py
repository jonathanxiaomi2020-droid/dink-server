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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

@app.before_request
def log_every_request():
    app.logger.info(f"🔔 [RADAR] {request.method} {request.path}")
    country = request.headers.get('Cf-Ipcountry', 'XX')
    ip = request.headers.get('Cf-Connecting-Ip', request.remote_addr)
    app.logger.info(f"   -> País: {country} | IP: {ip}")

REAL_DISCORD_WEBHOOK_URL = os.getenv("REAL_DISCORD_WEBHOOK_URL")
LOGIN_LOGOUT_WEBHOOK_URL = os.getenv("LOGIN_LOGOUT_WEBHOOK_URL")
ALLOWED_COUNTRIES = [c.strip().upper() for c in os.getenv("ALLOWED_COUNTRIES", "US,GB,VE").split(',')]

@app.route('/api/proxy-destino', methods=['GET', 'POST'], strict_slashes=False)
def proxy_destino():
    
    if request.method == 'GET':
        return jsonify({"status": "online"}), 200

    try:
        country_code = request.headers.get('Cf-Ipcountry', 'XX').upper()
        ip_address = request.headers.get('Cf-Connecting-Ip', request.remote_addr)
        
        app.logger.info(f"📨 SOLICITUD RECIBIDA | País: {country_code} | IP: {ip_address}")
        
        payload = request.get_json()
        if not payload:
            return jsonify({"error": "No payload"}), 400

        player_name = payload.get('playerName', 'Desconocido')
        notification_type = payload.get('type', 'General')
        
        app.logger.info(f"👤 Jugador: {player_name} | Tipo: {notification_type}")

        # Determinar si país es permitido
        is_allowed = country_code in ALLOWED_COUNTRIES
        status_text = "✅ PERMITIDO" if is_allowed else "❌ BLOQUEADO"
        
        app.logger.info(f"{status_text} - País: {country_code}")

        # Seleccionar webhook
        if notification_type in ['LOGIN', 'LOGOUT'] and LOGIN_LOGOUT_WEBHOOK_URL:
            target_webhook = LOGIN_LOGOUT_WEBHOOK_URL
        else:
            target_webhook = REAL_DISCORD_WEBHOOK_URL

        if not target_webhook:
            return jsonify({"error": "No webhook configured"}), 500

        # IMPORTANTE: Añadir el país al payload para que Discord lo vea
        payload_to_send = payload.copy()
        payload_to_send['cf_country'] = country_code
        payload_to_send['cf_ip'] = ip_address

        app.logger.info(f"📤 Enviando a Discord...")
        response = requests.post(target_webhook, json=payload_to_send, timeout=10)
        
        app.logger.info(f"✅ Discord respondió: {response.status_code}")

        return jsonify({
            "status": "ok",
            "country": country_code,
            "allowed": is_allowed
        }), 200

    except Exception as e:
        app.logger.error(f"❌ Error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route('/test')
def test():
    return jsonify({"status": "ok", "message": "Server is working"}), 200

@app.route('/')
def index():
    return jsonify({"status": "Server is running"}), 200

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
