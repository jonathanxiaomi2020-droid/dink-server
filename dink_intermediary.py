import os
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

# Cargar variables de entorno desde el archivo .env
load_dotenv()

app = Flask(__name__)

# --- CONFIGURACIÓN ---
# Estas variables deben estar en tu archivo .env
# La URL real del webhook de tu canal #dink-logs en Discord
REAL_DISCORD_WEBHOOK_URL = os.getenv("REAL_DISCORD_WEBHOOK_URL")
# La URL del webhook para logs de staff (donde se notificarán IPs inválidas)
STAFF_LOG_WEBHOOK_URL = os.getenv("STAFF_LOG_WEBHOOK_URL")
# La URL del webhook para los logs de Login/Logout
LOGIN_LOGOUT_WEBHOOK_URL = os.getenv("LOGIN_LOGOUT_WEBHOOK_URL")
STAFF_LOG_WEBHOOK_URL = os.getenv("STAFF_LOG_WEBHOOK_URL")
# La contraseña secreta que tus workers pondrán en su plugin Dink
DINK_SECRET = os.getenv("DINK_SECRET")
# Lista de códigos de país permitidos (ISO 3166-1 alpha-2)
ALLOWED_COUNTRIES = ["US", "GB"] # Ejemplo: Estados Unidos y Reino Unido

@app.route('/')
def index():
    # Una página de inicio simple para saber que el servidor está vivo
    return jsonify({"status": "Dink webhook endpoint is active"})

@app.route('/api/webhooks/dink', methods=['POST', 'GET'])
def dink_webhook_handler():
    # Si entras desde el navegador (GET), mostramos un mensaje de éxito
    if request.method == 'GET':
        return jsonify({"status": "URL correcta. El endpoint está listo para recibir notificaciones (POST)."}), 200

    # --- 1. Verificación de Seguridad ---
    # El plugin Dink puede enviar una cabecera personalizada para autenticación.
    # Usaremos 'X-Dink-Secret' como ejemplo.
    received_secret = request.headers.get('X-Dink-Secret')
    if not received_secret or received_secret != DINK_SECRET:
        # Si el secreto no coincide, es una petición no autorizada.
        print(f"ALERTA: Petición rechazada por secreto inválido. IP: {request.remote_addr}")
        return jsonify({"error": "Forbidden"}), 403

    # --- 2. Obtener la IP del Cliente ---
    # Esto maneja el caso de que tu app esté detrás de un proxy (como en la mayoría de hostings)
    ip_address = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()

    # --- 3. Geolocalización de la IP ---
    country_code = None
    try:
        # Usamos una API gratuita para obtener la información de la IP
        response = requests.get(f'http://ip-api.com/json/{ip_address}?fields=countryCode,status')
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 'success':
                country_code = data.get('countryCode')
    except requests.RequestException as e:
        print(f"Error al contactar la API de geolocalización: {e}")
        # En caso de error, podrías decidir si permitir o denegar por defecto.
        # Por seguridad, lo denegaremos.
        return jsonify({"error": "Could not verify location"}), 500

    # --- 4. Lógica de Validación y Reenvío ---
    dink_payload = request.get_json()
    player_name = dink_payload.get('player_name', 'Desconocido')
    notification_type = dink_payload.get('type') # Ej: "LOGIN", "LEVEL", "LOOT"

    if country_code and country_code in ALLOWED_COUNTRIES:
        # La IP es de un país permitido. Ahora decidimos a qué webhook enviar.
        target_webhook = REAL_DISCORD_WEBHOOK_URL # Por defecto, va al canal general de dink.

        # Si la notificación es de tipo LOGIN, la redirigimos al webhook de Login/Logout.
        if notification_type == 'LOGIN' and LOGIN_LOGOUT_WEBHOOK_URL:
            target_webhook = LOGIN_LOGOUT_WEBHOOK_URL

        if not target_webhook:
            print(f"WARN: No hay un webhook de destino configurado para la notificación de '{player_name}' (tipo: {notification_type}).")
            return jsonify({"status": "ok, but no webhook configured"}), 200

        try:
            requests.post(target_webhook, json=dink_payload)
            print(f"INFO: Notificación de '{player_name}' (tipo: {notification_type}) reenviada. Ubicación: {country_code} ({ip_address})")
        except requests.RequestException as e:
            print(f"ERROR: No se pudo reenviar la notificación de '{player_name}' a Discord: {e}")
        
        return jsonify({"status": "ok"}), 200
    else:
        # La IP NO es de un país permitido. Enviamos una alerta al canal de staff.
        print(f"ALERTA: IP no autorizada detectada para '{player_name}'. Ubicación: {country_code} ({ip_address})")
        if STAFF_LOG_WEBHOOK_URL:
            alert_payload = {
                "content": f"🚨 **Alerta de IP No Autorizada** 🚨",
                "embeds": [{
                    "color": 15158332, # Rojo
                    "title": "Intento de Conexión desde Ubicación No Permitida",
                    "fields": [
                        {"name": "Jugador (RSN)", "value": f"`{player_name}`", "inline": True},
                        {"name": "Ubicación Detectada", "value": f"`{country_code or 'Desconocida'}`", "inline": True},
                        {"name": "Dirección IP", "value": f"`{ip_address}`", "inline": True}
                    ],
                    "footer": {"text": "La notificación de Dink ha sido bloqueada."}
                }]
            }
            try:
                requests.post(STAFF_LOG_WEBHOOK_URL, json=alert_payload)
            except requests.RequestException as e:
                print(f"ERROR: No se pudo enviar la alerta de staff a Discord: {e}")

        # Respondemos a Dink que todo está "ok" para que no reintente, pero no reenviamos nada.
        return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    # El puerto 5000 es un estándar para desarrollo, pero tu hosting te asignará uno.
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
