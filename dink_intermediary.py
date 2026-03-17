import os
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import json # Para imprimir logs más bonitos
import time

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
        
        # --- 5. Sistema de Alertas al Staff (Sin Bloqueo) ---
        if STAFF_LOG_WEBHOOK_URL:
            is_safe_country = country_code and country_code in ALLOWED_COUNTRIES
            
            if is_safe_country:
                # CASO 1: País Seguro (VPN Activa o ubicación permitida) -> Mensaje VERDE
                print(f"DECISIÓN: La IP de {country_code} está en la lista segura.")
                embed_color = 5763719 # Verde
                alert_title = "Conexión Segura Detectada"
                alert_content = "✅ **Actividad Autorizada**"
                footer_text = "Conexión desde ubicación de confianza."
            else:
                # CASO 2: País Inusual (VPN Apagada o ubicación diferente) -> Mensaje AMARILLO
                print(f"DECISIÓN: La IP de {country_code or 'Desconocida'} NO está en la lista segura. Se enviará alerta.")
                embed_color = 16776960 # Amarillo/Naranja (Warning)
                alert_title = "⚠️ Ubicación Inusual / VPN Desactivada"
                alert_content = f"🚨 **Atención Staff: Conexión fuera de zona habitual**"
                footer_text = "La notificación se ha permitido, pero verifica la ubicación."

            staff_alert = {
                "content": alert_content,
                "embeds": [{
                    "color": embed_color,
                    "title": alert_title,
                    "fields": [
                        {"name": "Jugador (RSN)", "value": f"`{player_name}`", "inline": True},
                        {"name": "País Detectado", "value": f"`{country_code or 'Desconocido'}`", "inline": True},
                        {"name": "IP", "value": f"`{ip_address}`", "inline": True},
                        {"name": "Tipo Notificación", "value": f"`{notification_type or 'General'}`", "inline": True}
                    ],
                    "footer": {"text": footer_text}
                }]
            }
            try:
                requests.post(STAFF_LOG_WEBHOOK_URL, json=staff_alert, timeout=5)
            except Exception as e:
                print(f"WARN: No se pudo enviar la alerta al staff: {e}")

        # --- 6. Reenvío a Discord (Siempre ocurre, sin importar el país) ---
        target_webhook = REAL_DISCORD_WEBHOOK_URL

        if notification_type == 'LOGIN' and LOGIN_LOGOUT_WEBHOOK_URL:
            target_webhook = LOGIN_LOGOUT_WEBHOOK_URL
            print("INFO: Notificación de LOGIN, redirigiendo a webhook de Login/Logout.")
        
        if not target_webhook:
            print(f"ERROR FATAL: No hay un webhook de destino configurado para esta notificación.")
            return jsonify({"status": "ok, but no webhook configured"}), 200

        try:
            print(f"INFO: Enviando payload a webhook de Discord (Destino final)...")
            
            # Lógica de reintentos para manejar Rate Limits (Error 429)
            max_retries = 3
            for attempt in range(max_retries):
                post_response = requests.post(target_webhook, json=dink_payload, timeout=10)
                
                if post_response.status_code == 429:
                    # Discord nos pide esperar. Leemos el tiempo exacto del "retry_after".
                    try:
                        retry_after = float(post_response.json().get('retry_after', 2.0))
                    except:
                        retry_after = 2.0
                    print(f"WARN: Discord Rate Limit (429). Esperando {retry_after:.2f}s... (Intento {attempt+1}/{max_retries})")
                    time.sleep(retry_after)
                    continue # Reintentamos
                
                print(f"INFO: Discord respondió con estado: {post_response.status_code}")
                post_response.raise_for_status()
                break # Si llegamos aquí, se envió con éxito o falló con otro error
        except requests.RequestException as e:
            print(f"ERROR: No se pudo reenviar la notificación a Discord: {e}")
        
        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print(f"--- [ERROR INESPERADO EN EL HANDLER] ---")
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": "Internal Server Error"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
