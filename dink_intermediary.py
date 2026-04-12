import os
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from flask_sqlalchemy import SQLAlchemy
import json
import time
from datetime import datetime
import logging
import sys

load_dotenv()

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///dink_logs.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Configurar logs para Render
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)

# --- Modelos de Base de Datos ---
class DinkEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    player_name = db.Column(db.String(50))
    event_type = db.Column(db.String(20))
    ip_address = db.Column(db.String(45))
    country = db.Column(db.String(5))
    details = db.Column(db.Text)

with app.app_context():
    db.create_all()

# --- Configuración ---
REAL_DISCORD_WEBHOOK_URL = os.getenv("REAL_DISCORD_WEBHOOK_URL")
STAFF_LOG_WEBHOOK_URL = os.getenv("STAFF_LOG_WEBHOOK_URL")
LOGIN_LOGOUT_WEBHOOK_URL = os.getenv("LOGIN_LOGOUT_WEBHOOK_URL")

ALLOWED_COUNTRIES_STR = os.getenv("ALLOWED_COUNTRIES", "US,GB,VE,ES")
ALLOWED_COUNTRIES = [country.strip().upper() for country in ALLOWED_COUNTRIES_STR.split(',')]

@app.route('/')
def index():
    return jsonify({
        "status": "Online - S T O N E Intermediary",
        "file": "dink_intermediary.py",
        "dashboard": "/dashboard",
        "webhooks": ["/api/proxy-destino", "/api/webhooks/dink"]
    })

# --- Web Dashboard ---
@app.route('/dashboard', strict_slashes=False)
def dashboard():
    logs = DinkEvent.query.order_by(DinkEvent.timestamp.desc()).limit(100).all()
    html = """
    <html>
    <head>
        <title>S T O N E | Dink Monitor</title>
        <meta http-equiv="refresh" content="30">
        <style>
            body { font-family: sans-serif; background: #1a1a1a; color: white; padding: 20px; }
            table { width: 100%; border-collapse: collapse; margin-top: 20px; }
            th, td { padding: 12px; text-align: left; border-bottom: 1px solid #333; }
            th { background: #333; color: #00ff9f; }
            tr:hover { background: #252525; }
            .LOGIN { color: #00ff9f; }
            .LEVEL { color: #ffae00; }
            .BLOQUEADO { color: #ff4e4e; font-weight: bold; }
        </style>
    </head>
    <body>
        <h1>💎 S T O N E | Panel de Notificaciones</h1>
        <p>Mostrando los últimos 100 eventos (Auto-refresh 30s)</p>
        <table>
            <tr>
                <th>Fecha (UTC)</th><th>Jugador</th><th>Evento</th><th>País</th><th>IP</th>
            </tr>
    """
    for log in logs:
        html += f"<tr><td>{log.timestamp.strftime('%H:%M:%S')}</td><td>{log.player_name}</td>"
        html += f"<td class='{log.event_type}'>{log.event_type}</td>"
        html += f"<td>{log.country}</td><td>{log.ip_address}</td></tr>"
    
    html += "</table></body></html>"
    return html

@app.route('/api/webhooks/dink', methods=['POST', 'GET'])
@app.route('/api/proxy-destino', methods=['POST', 'GET'])
def dink_webhook_handler():
    if request.method == 'GET':
        return jsonify({"status": "URL correcta"}), 200

    try:
        # silent=True evita que Flask lance una excepción 400 si el cuerpo está vacío o mal formado
        dink_payload = request.get_json(force=True, silent=True)
        
        if not dink_payload:
            app.logger.warning(f"⚠️ Petición recibida sin cuerpo JSON válido. Data cruda: {request.data.decode('utf-8')[:100]}")
            return jsonify({"error": "No payload"}), 400

        app.logger.info(f"--- [NUEVA PETICIÓN: {dink_payload.get('type', 'UNKNOWN')}] ---")

        ip_address = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()

        country_code = None
        try:
            response = requests.get(f'http://ip-api.com/json/{ip_address}?fields=countryCode,status', timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success':
                    country_code = data.get('countryCode')
                    app.logger.info(f"✅ País: {country_code}")
        except Exception as e:
            app.logger.warning(f"⚠️ Geo error: {e}")
        
        player_name = dink_payload.get('playerName', 'Desconocido')
        # El tipo puede estar en la raíz o dentro de 'extra'
        notification_type = dink_payload.get('type') or dink_payload.get('extra', {}).get('type', 'Unknown')
        
        app.logger.info(f"👤 Jugador: {player_name} | Tipo: {notification_type} | IP: {ip_address}")

        # --- GUARDAR SIEMPRE EN BASE DE DATOS ---
        new_log = DinkEvent(
            player_name=player_name,
            event_type=notification_type,
            ip_address=ip_address,
            country=country_code or "??",
            details=json.dumps(dink_payload)
        )

        # --- LÓGICA DE FILTRADO Y ENVÍO ---
        # Normalizar el código de país a mayúsculas para comparar
        current_country = country_code.upper() if country_code else None
        
        # Permitimos si el país está en la lista O si no se pudo detectar (None)
        is_allowed = (current_country in ALLOWED_COUNTRIES) or (current_country is None)

        if is_allowed:
            app.logger.info(f"✅ ACTIVIDAD PERMITIDA (País: {current_country or 'Desconocido'})")

            # Determinar a qué webhook enviar
            target_webhook = None
            
            if notification_type in ['LOGIN', 'LOGOUT']:
                # Solo enviamos logins a Discord si configuraste LOGIN_LOGOUT_WEBHOOK_URL en Render
                target_webhook = LOGIN_LOGOUT_WEBHOOK_URL
                if not target_webhook:
                    app.logger.warning(f"⚠️ {notification_type} detectado pero la variable LOGIN_LOGOUT_WEBHOOK_URL está vacía en Render.")
            else:
                # Updates normales (Level, Quest, Loot) van al webhook principal
                target_webhook = REAL_DISCORD_WEBHOOK_URL

            if target_webhook:
                try:
                    app.logger.info(f"📤 Reenviando {notification_type} a Discord...")
                    # Logueamos los últimos 10 caracteres del webhook para verificar que existe
                    app.logger.info(f"   Webhook destino termina en: ...{target_webhook[-10:]}")
                    
                    resp = requests.post(target_webhook, json=dink_payload, timeout=10)
                    app.logger.info(f"   Discord respondió: {resp.status_code}")
                    
                    if resp.status_code == 429:
                        app.logger.warning("   ⚠️ Discord bloqueó el mensaje por spam (Rate Limit 429).")
                except Exception as e:
                    app.logger.error(f"   ❌ Error de red enviando a Discord: {e}")
            else:
                if notification_type not in ['LOGIN', 'LOGOUT']:
                    app.logger.error(f"❌ ERROR: No se puede reenviar {notification_type} porque REAL_DISCORD_WEBHOOK_URL no está configurada.")

            db.session.add(new_log)
            db.session.commit()
            return jsonify({"status": "ok"}), 200
        
        else:
            app.logger.warning(f"❌ PAÍS BLOQUEADO: {country_code}. No se envía a Discord.")
            new_log.event_type = 'BLOQUEADO'
            db.session.add(new_log)
            db.session.commit()
            return jsonify({"status": "ok"}), 200

    except Exception as e:
        app.logger.error(f"❌ Error General: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": "Error"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
