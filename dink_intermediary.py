import os
import json
import logging
from flask import Flask, request, jsonify
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

app = Flask(__name__)

# Configurar logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Variables de entorno
ALLOWED_COUNTRIES = [c.strip().upper() for c in os.getenv("ALLOWED_COUNTRIES", "US,GB,VE,ES").split(',')]
PORT = int(os.getenv("PORT", 5000))

# Log de inicio
logger.info(f"🎉 Servidor Render iniciado")
logger.info(f"✅ Países permitidos: {ALLOWED_COUNTRIES}")

@app.before_request
def log_request():
    """Registra todos los requests"""
    logger.info(f"📡 {request.method} {request.path}")

@app.route('/')
def index():
    return jsonify({
        "status": "🎉 Servidor Render Activo (Detector IP/País)",
        "allowed_countries": ALLOWED_COUNTRIES,
        "endpoint": "/api/proxy-destino"
    }), 200

@app.route('/test')
def test():
    return jsonify({
        "status": "✅ Test OK",
        "allowed_countries": ALLOWED_COUNTRIES
    }), 200

@app.route('/api/proxy-destino', methods=['GET', 'POST'])
def proxy_destino():
    """Recibe eventos de RuneLite, detecta IP/país, responde al bot local"""
    
    if request.method == 'GET':
        return jsonify({"status": "✅ Endpoint activo"}), 200
    
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
        
        # Crear respuesta con la info detectada
        response_data = {
            "status": "ok",
            "event_type": event_type,
            "player_name": player_name,
            "detected_country": country_code,
            "detected_ip": ip_address,
            "is_country_allowed": is_allowed
        }
        
        logger.info(f"✅ Respuesta enviada al plugin")
        
        return jsonify(response_data), 200
    
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    logger.info(f"🚀 Servidor iniciado en puerto {PORT}...")
    app.run(host='0.0.0.0', port=PORT, debug=False)
