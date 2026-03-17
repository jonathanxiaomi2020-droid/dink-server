import os
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import json # Para imprimir logs más bonitos

# Cargar variables de entorno desde el archivo .env
load_dotenv()

app = Flask(__name__)

# --- CONFIGURACIÓN ---
REAL_DISCORD_WEBHOOK_URL = os.getenv("REAL_DISCORD_WEBHOOK_URL")
STAFF_LOG_WEBHOOK_URL = os.getenv("STAFF_LOG_WEBHOOK_URL")
LOGIN_LOGOUT_WEBHOOK_URL = os.getenv("LOGIN_LOGOUT_WEBHOOK_URL")
DINK_SECRET = os.getenv("DINK_SECRET")

# Carga los países considerados "Seguros" o "VPN Habitual".
# Si la conexión viene de aquí, sale en VERDE. Si no, sale en AMARILLO (pero NO se bloquea).
# Ejemplo en .env: ALLOWED_COUNTRIES=US,GB
ALLOWED_COUNTRIES_STR = os.getenv("ALLOWED_COUNTRIES", "US,GB")
ALLOWED_COUNTRIES = [country.strip().upper() for country in ALLOWED_COUNTRIES_STR.split(',')]

@app.route('/')
def index():
    return jsonify({"status": "Dink webhook endpoint is active"})

@app.route('/api/webhooks/dink', methods=['POST', 'GET'])
def dink_webhook_handler():
    if request.method == 'GET':
        return jsonify({"status": "URL correcta. El endpoint está listo para recibir notificaciones (POST)."}), 200

    # --- INICIO DEL PROCESO POST ---
    print("\n--- [NUEVA PETICIÓN RECIBIDA] ---")
    try:
        # --- 1. Verificación de Seguridad ---
        # Se ha eliminado la verificación de 'X-Dink-Secret' ya que el plugin no la envía por defecto.
        # La seguridad recae en la URL del webhook y la validación de IP.
        print(f"INFO: Procesando petición. Headers recibidos: {json.dumps(dict(request.headers), indent=2)}")

        # --- 2. Obtener la IP del Cliente ---
        ip_address = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
        print(f"INFO: IP detectada: {ip_address}")

        # --- 3. Geolocalización de la IP ---
        country_code = None
        try:
            print("INFO: Contactando API de geolocalización...")
            response = requests.get(f'http://ip-api.com/json/{ip_address}?fields=countryCode,status', timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success':
                    country_code = data.get('countryCode')
                    print(f"INFO: Ubicación detectada: {country_code}")
                else:
                    print(f"WARN: API de geolocalización respondió pero sin éxito: {data}")
            else:
                print(f"WARN: API de geolocalización devolvió un estado no-200: {response.status_code}")
        except requests.RequestException as e:
            print(f"ERROR: No se pudo contactar la API de geolocalización: {e}")
        
        # --- 4. Lógica de Validación y Reenvío ---
        dink_payload = request.get_json()
        
        # Búsqueda robusta del nombre del jugador
        player_name = dink_payload.get('playerName') # Formato estándar de Dink
        if not player_name:
            player_name = dink_payload.get('player_name') # Intento alternativo
        if not player_name:
            player_name = dink_payload.get('extra', {}).get('player_name', 'Desconocido')
            
        notification_type = dink_payload.get('type')
        print(f"INFO: Procesando notificación tipo '{notification_type}' para el jugador '{player_name}'.")
        print(f"INFO: Países permitidos: {ALLOWED_COUNTRIES}")

        print(f"INFO: Dink Payload: {json.dumps(dink_payload, indent=2)}")
        if country_code and country_code in ALLOWED_COUNTRIES:
            print(f"DECISIÓN: La IP de {country_code} está permitida. Reenviando a Discord...")
            
            # --- NUEVO: Notificar al Staff sobre conexión exitosa (IP Permitida) ---
            if STAFF_LOG_WEBHOOK_URL:
                success_alert = {
                    "content": f"✅ **Actividad Autorizada**",
                    "embeds": [{
                        "color": 5763719, # Verde (Green)
                        "title": "Conexión Válida Detectada",
                        "fields": [
                            {"name": "Jugador (RSN)", "value": f"`{player_name}`", "inline": True},
                            {"name": "País Detectado", "value": f"`{country_code}`", "inline": True},
                            {"name": "IP", "value": f"`{ip_address}`", "inline": True},
                            {"name": "Tipo", "value": f"`{notification_type or 'General'}`", "inline": True}
                        ],
                        "footer": {"text": "La notificación ha sido reenviada al canal correspondiente."}
                    }]
                }
                try:
                    # Enviamos esto rápido y sin bloquear el proceso principal
                    requests.post(STAFF_LOG_WEBHOOK_URL, json=success_alert, timeout=5)
                except Exception as e:
                    print(f"WARN: No se pudo enviar el log de éxito al staff: {e}")
            # -----------------------------------------------------------------------

            target_webhook = REAL_DISCORD_WEBHOOK_URL

            if notification_type == 'LOGIN' and LOGIN_LOGOUT_WEBHOOK_URL:
                target_webhook = LOGIN_LOGOUT_WEBHOOK_URL
                print("INFO: Notificación de LOGIN, redirigiendo a webhook de Login/Logout.")
            
            if not target_webhook:
                print(f"ERROR FATAL: No hay un webhook de destino configurado para esta notificación.")
                return jsonify({"status": "ok, but no webhook configured"}), 200

            try:
                print(f"INFO: Enviando payload a webhook de Discord...")
                post_response = requests.post(target_webhook, json=dink_payload, timeout=10)
                print(f"INFO: Discord respondió con estado: {post_response.status_code}")
                post_response.raise_for_status()
            except requests.RequestException as e:
                print(f"ERROR: No se pudo reenviar la notificación a Discord: {e}")
            
            return jsonify({"status": "ok"}), 200
        else:
            print(f"DECISIÓN: IP no autorizada. Ubicación: {country_code}. Bloqueando y enviando alerta.")
            if STAFF_LOG_WEBHOOK_URL:
                alert_payload = {
                    "content": f"🚨 **Alerta de IP No Autorizada** 🚨",
                    "embeds": [{"color": 15158332, "title": "Intento de Conexión desde Ubicación No Permitida", "fields": [{"name": "Jugador (RSN)", "value": f"`{player_name}`", "inline": True}, {"name": "Ubicación Detectada", "value": f"`{country_code or 'Desconocida'}`", "inline": True}, {"name": "Dirección IP", "value": f"`{ip_address}`", "inline": True}], "footer": {"text": "La notificación de Dink ha sido bloqueada."}}]
                }
                try:
                    print("INFO: Enviando alerta a webhook de staff...")
                    requests.post(STAFF_LOG_WEBHOOK_URL, json=alert_payload, timeout=10)
                    print("INFO: Alerta de staff enviada.")
                except requests.RequestException as e:
                    print(f"ERROR: No se pudo enviar la alerta de staff a Discord: {e}")

            return jsonify({"status": "ok"}), 200

    except Exception as e:
        print(f"--- [ERROR INESPERADO EN EL HANDLER] ---")
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": "Internal Server Error"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
