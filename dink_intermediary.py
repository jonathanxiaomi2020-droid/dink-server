import os
import json
import logging
import requests
import time
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

def send_to_discord(webhook_url, payload, max_retries=3):
    """Envía a Discord con reintentos y manejo de rate limits"""
    
    for attempt in range(max_retries):
        try:
            response = requests.post(webhook_url, json=payload, timeout=5)
            
            if response.status_code in [200, 204]:
                logger.info(f"✅ Mensaje enviado a Discord (HTTP {response.status_code})")
                return True, response.status_code
            
            elif response.status_code == 429:
                # Rate limit - esperar y reintentar
                retry_after = int(response.headers.get('Retry-After', 1))
                logger.warning(f"⚠️ Rate limit (429). Intento {attempt + 1}/{max_retries}. Esperando {retry_after}s...")
                time.sleep(retry_after)
                continue
            
            else:
                logger.error(f"❌ Discord error {response.status_code}: {response.text[:100]}")
                return False, response.status_code
        
        except requests.exceptions.Timeout:
            logger.error(f"❌ Timeout intento {attempt + 1}/{max_retries}")
            if attempt < max_retries - 1:
                time.sleep(1)
                continue
            return False, 504
        
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Error en request: {str(e)}")
            return False, 500
    
    logger.error(f"❌ Falló después de {max_retries} intentos")
    return False, 429

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
        
        logger.info(f"🌐 IP: {ip_address}")
        logger.info(f"🌍 País: {country_code}")
        
        # Obtener payload JSON
        payload = request.get_json()
        
        if not payload:
            logger.error("❌ Payload vacío")
            return jsonify({"status": "error", "message": "Payload vacío"}), 400
        
        # Determinar tipo de evento
        event_type = payload.get("type", "UNKNOWN").upper()
        player_name = payload.get("playerName", "Desconocido")
        
        logger.info(f"👤 Jugador: {player_name} | 📌 Tipo: {event_type}")
        
        # Verificar si el país está permitido
        is_allowed = country_code in ALLOWED_COUNTRIES
        status_text = "✅ PERMITIDO" if is_allowed else "❌ BLOQUEADO"
        logger.info(f"{status_text} - País: {country_code}")
        
        # Añadir info de IP/país al payload
        payload_to_send = payload.copy()
        payload_to_send['cf_country'] = country_code
        payload_to_send['cf_ip'] = ip_address
        payload_to_send['is_country_allowed'] = is_allowed
        
        # Seleccionar webhook según el tipo de evento
        if event_type in ['LOGIN', 'LOGOUT']:
            webhook_url = LOGIN_LOGOUT_WEBHOOK_URL
            logger.info(f"📤 Usando webhook de LOGIN/LOGOUT")
        else:
            webhook_url = REAL_DISCORD_WEBHOOK_URL
            logger.info(f"📤 Usando webhook de SKILLS/UPDATES")
        
        if not webhook_url:
            logger.error(f"❌ Webhook no configurado para {event_type}")
            return jsonify({"status": "error", "message": "Webhook no configurado"}), 500
        
        # Enviar a Discord con reintentos
        success, status_code = send_to_discord(webhook_url, payload_to_send)
        
        if success:
            return jsonify({
                "status": "ok",
                "country": country_code,
                "allowed": is_allowed,
                "message": "✅ Enviado a Discord"
            }), 200
        else:
            return jsonify({
                "status": "error",
                "country": country_code,
                "allowed": is_allowed,
                "message": f"❌ Error Discord {status_code}"
            }), status_code
    
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    logger.info(f"🚀 Servidor iniciado en puerto {PORT}...")
    app.run(host='0.0.0.0', port=PORT, debug=False)
