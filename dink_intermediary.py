import os
import json
import logging
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

app = Flask(__name__)

# Configurar logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Variables de entorno
REAL_DISCORD_WEBHOOK_URL = os.getenv("REAL_DISCORD_WEBHOOK_URL")
LOGIN_LOGOUT_WEBHOOK_URL = os.getenv("LOGIN_LOGOUT_WEBHOOK_URL")
ALLOWED_COUNTRIES = [c.strip().upper() for c in os.getenv("ALLOWED_COUNTRIES", "US,GB,VE,ES").split(',')]
PORT = int(os.getenv("PORT", 5000))

# Log de inicio
logger.info(f"🎉 Servidor Render iniciado")
logger.info(f"✅ Webhook principal configurado: {bool(REAL_DISCORD_WEBHOOK_URL)}")
logger.info(f"✅ Webhook Login/Logout configurado: {bool(LOGIN_LOGOUT_WEBHOOK_URL)}")
logger.info(f"✅ Países permitidos: {ALLOWED_COUNTRIES}")

@app.before_request
def log_request():
    """Registra todos los requests"""
    logger.info(f"📡 {request.method} {request.path} desde {request.remote_addr}")
    if request.headers.get('Cf-Connecting-Ip'):
        logger.info(f"   → IP Cloudflare: {request.headers.get('Cf-Connecting-Ip')}")
    if request.headers.get('Cf-Ipcountry'):
        logger.info(f"   → País Cloudflare: {request.headers.get('Cf-Ipcountry')}")

@app.route('/')
def index():
    return jsonify({
        "status": "🎉 Servidor Render Activo",
        "webhook_skills": bool(REAL_DISCORD_WEBHOOK_URL),
        "webhook_login_logout": bool(LOGIN_LOGOUT_WEBHOOK_URL),
        "allowed_countries": ALLOWED_COUNTRIES,
        "endpoint": "/api/proxy-destino"
    }), 200

@app.route('/test')
def test():
    return jsonify({
        "status": "✅ Test OK",
        "allowed_countries": ALLOWED_COUNTRIES,
        "webhooks_configured": {
            "skills": bool(REAL_DISCORD_WEBHOOK_URL),
            "login_logout": bool(LOGIN_LOGOUT_WEBHOOK_URL)
        }
    }), 200

@app.route('/api/proxy-destino', methods=['GET', 'POST'])
def proxy_destino():
    """Recibe eventos de RuneLite, detecta IP/país, reenvía a Discord"""
    
    if request.method == 'GET':
        return jsonify({"status": "✅ Endpoint activo", "method": "GET"}), 200
    
    # POST - Procesar webhook
    try:
        # Extraer IP y país de headers Cloudflare
        ip_address = request.headers.get('Cf-Connecting-Ip') or request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
        country_code = request.headers.get('Cf-Ipcountry', 'XX').upper()
        
        logger.info(f"🌐 IP detectada: {ip_address}")
        logger.info(f"🌍 País detectado: {country_code}")
        
        # Obtener payload JSON
        payload = request.get_json()
        
        if not payload:
            logger.error("❌ Payload vacío")
            return jsonify({"status": "error", "message": "Payload vacío"}), 400
        
        logger.info(f"📦 Payload recibido: {json.dumps(payload, indent=2)}")
        
        # Determinar tipo de evento
        event_type = payload.get("type", "UNKNOWN").upper()
        player_name = payload.get("playerName", "Desconocido")
        
        logger.info(f"👤 Jugador: {player_name}")
        logger.info(f"📌 Tipo: {event_type}")
        
        # Verificar si el país está permitido
        is_allowed = country_code in ALLOWED_COUNTRIES
        status_text = "✅ PERMITIDO" if is_allowed else "❌ BLOQUEADO"
        
        logger.info(f"{status_text}: {country_code}")
        
        # Añadir info de IP/país al payload
        payload_to_send = payload.copy()
        payload_to_send['cf_country'] = country_code
        payload_to_send['cf_ip'] = ip_address
        payload_to_send['is_country_allowed'] = is_allowed
        
        # Seleccionar webhook según el tipo de evento
        if event_type in ['LOGIN', 'LOGOUT']:
            webhook_url = LOGIN_LOGOUT_WEBHOOK_URL
            logger.info(f"📤 Usando webhook de Login/Logout")
        else:
            webhook_url = REAL_DISCORD_WEBHOOK_URL
            logger.info(f"📤 Usando webhook principal (Skills/Updates)")
        
        if not webhook_url:
            logger.error(f"❌ No hay webhook configurado para {event_type}")
            return jsonify({"status": "error", "message": f"Webhook no configurado"}), 500
        
        # Enviar a Discord
        try:
            response = requests.post(webhook_url, json=payload_to_send, timeout=5)
            
            if response.status_code in [200, 204]:
                logger.info(f"✅ Mensaje reenviado a Discord (HTTP {response.status_code})")
                return jsonify({
                    "status": "ok",
                    "country": country_code,
                    "allowed": is_allowed,
                    "message": "Enviado a Discord"
                }), 200
            
            elif response.status_code == 429:
                logger.warning(f"⚠️ Discord respondió 429 (Rate limit). Reintentando...")
                # Reintentar una vez después de esperar
                import time
                time.sleep(1)
                response = requests.post(webhook_url, json=payload_to_send, timeout=5)
                if response.status_code in [200, 204]:
                    logger.info(f"✅ Reintento exitoso")
                    return jsonify({"status": "ok", "country": country_code, "allowed": is_allowed}), 200
                else:
                    logger.error(f"❌ Reintento falló: {response.status_code}")
                    return jsonify({"status": "error", "message": "Discord rate limit"}), 429
            
            else:
                logger.error(f"❌ Discord respondió {response.status_code}: {response.text}")
                return jsonify({"status": "error", "message": f"Discord error {response.status_code}"}), response.status_code
        
        except requests.exceptions.Timeout:
            logger.error("❌ Timeout al conectar a Discord")
            return jsonify({"status": "error", "message": "Timeout"}), 504
        
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Error en request a Discord: {str(e)}")
            return jsonify({"status": "error", "message": str(e)}), 500
    
    except Exception as e:
        logger.error(f"❌ Error general: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    logger.info(f"🚀 Iniciando en puerto {PORT}...")
    app.run(host='0.0.0.0', port=PORT, debug=False)
