import os
import json
import logging
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

LOGIN_LOGOUT_WEBHOOK_URL = os.getenv("LOGIN_LOGOUT_WEBHOOK_URL")
ALLOWED_COUNTRIES = [c.strip().upper() for c in os.getenv("ALLOWED_COUNTRIES", "US,GB,VE,ES").split(',')]
PORT = int(os.getenv("PORT", 5000))

logger.info(f"🎉 Servidor iniciado")
logger.info(f"✅ Webhook configurado: {bool(LOGIN_LOGOUT_WEBHOOK_URL)}")
logger.info(f"✅ Países permitidos: {ALLOWED_COUNTRIES}")

@app.route('/')
def index():
    return jsonify({"status": "🎉 Activo"}), 200

@app.route('/test')
def test():
    return jsonify({"status": "✅ Test OK", "allowed_countries": ALLOWED_COUNTRIES}), 200

@app.route('/api/proxy-destino', methods=['GET', 'POST'])
def proxy_destino():
    if request.method == 'GET':
        return jsonify({"status": "✅ OK"}), 200
    
    try:
        # Obtener IP y país de Cloudflare
        ip_address = request.headers.get('Cf-Connecting-Ip') or request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
        country_code = request.headers.get('Cf-Ipcountry', 'XX').upper()
        
        logger.info(f"🌐 IP: {ip_address} | 🌍 País: {country_code}")
        
        # Obtener payload
        payload = request.get_json()
        
        if not payload:
            logger.error("❌ Payload vacío")
            return jsonify({"status": "error"}), 400
        
        event_type = payload.get("type", "UNKNOWN").upper()
        player_name = payload.get("playerName", "Desconocido")
        
        logger.info(f"👤 Jugador: {player_name} | 📌 Tipo: {event_type}")
        
        # Verificar si está permitido
        is_allowed = country_code in ALLOWED_COUNTRIES
        status_text = "✅ PERMITIDO" if is_allowed else "❌ BLOQUEADO"
        logger.info(f"{status_text} - País: {country_code}")
        
        # Añadir IP y país al payload
        payload['detected_country'] = country_code
        payload['detected_ip'] = ip_address
        payload['is_country_allowed'] = is_allowed
        
        # Reenviar a Discord
        if LOGIN_LOGOUT_WEBHOOK_URL:
            try:
                response = requests.post(LOGIN_LOGOUT_WEBHOOK_URL, json=payload, timeout=5)
                logger.info(f"✅ Reenviado a Discord: {response.status_code}")
            except Exception as e:
                logger.error(f"❌ Error: {e}")
        
        return jsonify({
            "status": "ok",
            "detected_country": country_code,
            "detected_ip": ip_address,
            "is_country_allowed": is_allowed
        }), 200
    
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        return jsonify({"status": "error"}), 500

if __name__ == '__main__':
    logger.info(f"🚀 Iniciado en puerto {PORT}...")
    app.run(host='0.0.0.0', port=PORT, debug=False)
