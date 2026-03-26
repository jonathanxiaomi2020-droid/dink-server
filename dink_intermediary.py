import os
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import json
import sys
import time
from datetime import datetime
from dhooks import Webhook, Embed
import requests
import logging

load_dotenv()
app = Flask(__name__)

# --- CONFIGURACIÓN DE LOGS (NUEVO Y MEJORADO) ---
# Configura un logging más robusto que print()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- RADAR DE DIAGNÓSTICO (NUEVO) ---
# Esto imprimirá CUALQUIER cosa que llegue al servidor, sin importar la ruta.
@app.before_request
def log_every_request():
    # Usamos el logger de la app para más fiabilidad
    if request.path != '/test': # Evitar llenar el log con pruebas simples
        app.logger.info(f"🔔 [RADAR] Conexión detectada en {request.path} [{request.method}]")
        # Render/Cloudflare nos dan el país directamente en los headers
        country = request.headers.get('Cf-Ipcountry', 'Desconocido')
        real_ip = request.headers.get('Cf-Connecting-Ip') or request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
        app.logger.info(f"   -> Origen: {real_ip} ({country})")
        
        if request.method == 'POST' and request.path == '/':
            app.logger.warning("   ⚠️ ADVERTENCIA: Se recibió un POST en la raíz (/). ¿Está mal la URL en Hookdeck?")

# --- CONFIGURACIÓN ---
# Webhook para notificaciones generales (loot, niveles, quests, etc.)
REAL_DISCORD_WEBHOOK_URL = os.getenv("REAL_DISCORD_WEBHOOK_URL")
# Webhook para logs internos del staff (alertas de IP, etc.)
STAFF_LOG_WEBHOOK_URL = os.getenv("STAFF_LOG_WEBHOOK_URL")
# Webhook EXCLUSIVO para notificaciones de LOGIN y LOGOUT
LOGIN_LOGOUT_WEBHOOK_URL = os.getenv("LOGIN_LOGOUT_WEBHOOK_URL")

# Países permitidos
ALLOWED_COUNTRIES = [c.strip().upper() for c in os.getenv("ALLOWED_COUNTRIES", "US,GB,VE").split(',')]

# --- ENDPOINT PARA RECIBIR DE HOOKDECK ---
@app.route('/api/proxy-destino', methods=['GET', 'POST'], strict_slashes=False)
def proxy_destino():
    """Recibe los webhooks desde Hookdeck"""
    # Si entras desde el navegador (GET), mostramos un mensaje de estado
    if request.method == 'GET':
        return jsonify({"status": "online", "message": "Este endpoint está esperando datos POST de Hookdeck."}), 200

    app.logger.info("\n" + "="*60)
    app.logger.info(f"📨 RECIBIDO DE HOOKDECK - {datetime.now().isoformat()}")
    
    try:
        # Obtener IP y País desde los headers de Cloudflare/Render (más rápido y confiable)
        ip_address = request.headers.get('Cf-Connecting-Ip') or request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
        country_code = request.headers.get('Cf-Ipcountry', 'XX').upper()
        
        app.logger.info(f"🌐 IP: {ip_address}")
        app.logger.info(f"📍 País detectado: {country_code}")

        # Obtener payload de Dink
        payload = request.get_json()
        if not payload:
            return jsonify({"error": "No payload"}), 400

        # Extraer información del jugador
        player_name = payload.get('playerName') or payload.get('player_name', 'Desconocido')
        notification_type = payload.get('type') or payload.get('extra', {}).get('type', 'General')
        
        app.logger.info(f"👤 Jugador: {player_name}")
        app.logger.info(f"📌 Tipo: {notification_type}")

        # --- DECISIÓN ---
        # Si no se pudo detectar el país, asumimos que es seguro para no romper la prueba (puedes cambiar esto luego)
        is_allowed = False
        if country_code and country_code in ALLOWED_COUNTRIES:
            is_allowed = True
        elif country_code is None:
            app.logger.warning("⚠️ No se pudo detectar país. Permitido por defecto para pruebas.")
            is_allowed = True

        if is_allowed:
            app.logger.info(f"✅ PAÍS PERMITIDO: {country_code}")
            
            # Enviar LOG al staff
            if STAFF_LOG_WEBHOOK_URL:
                try:
                    hook = Webhook(STAFF_LOG_WEBHOOK_URL)
                    embed = Embed(
                        title='✅ Actividad Autorizada',
                        color=0x00ff00,
                        timestamp=datetime.now().isoformat()
                    )
                    embed.add_field(name='Jugador', value=f'`{player_name}`', inline=True)
                    embed.add_field(name='País', value=f'`{country_code}`', inline=True)
                    embed.add_field(name='IP', value=f'`{ip_address}`', inline=True)
                    embed.add_field(name='Tipo', value=f'`{notification_type}`', inline=True)
                    embed.add_field(name='Fuente', value='`Hookdeck`', inline=True)
                    hook.send(embed=embed)
                    app.logger.info("  ✅ Log de staff enviado")
                except Exception as e:
                    app.logger.error(f"  ❌ Error enviando log: {e}")

            # --- LÓGICA DE ENRUTAMIENTO DE WEBHOOKS ---
            # Por defecto, todas las notificaciones van al webhook principal.
            target = REAL_DISCORD_WEBHOOK_URL

            # Si el tipo de notificación es LOGIN o LOGOUT, y tienes configurado un webhook específico para ello,
            # cambiamos el destino a ese webhook.
            if notification_type in ['LOGIN', 'LOGOUT'] and LOGIN_LOGOUT_WEBHOOK_URL:
                target = LOGIN_LOGOUT_WEBHOOK_URL
                app.logger.info(f"  📨 Tipo {notification_type} detectado. Usando webhook de Login/Logout.")

            if not target:
                app.logger.error("❌ ERROR CRÍTICO: No hay URL de Webhook configurada en las variables de entorno.")
                app.logger.error("   -> Asegúrate de configurar REAL_DISCORD_WEBHOOK_URL en Render.")
                return jsonify({"error": "Server misconfiguration"}), 500

            if target:
                try:
                    app.logger.info(f"  📤 Reenviando a Discord (Webhook termina en: ...{target[-10:]})")
                    # Reenviamos el payload JSON original que nos envió Dink al webhook de Discord correspondiente.
                    response = requests.post(target, json=payload, timeout=5)
                    if response.status_code in [200, 204]:
                        app.logger.info("  ✅ Mensaje reenviado a Discord")
                    else:
                        app.logger.warning(f"  ⚠️ Discord respondió {response.status_code}")
                except Exception as e:
                    app.logger.error(f"  ❌ Error reenviando: {e}")

        else:
            app.logger.warning(f"❌ PAÍS NO PERMITIDO: {country_code or 'Desconocido'}")
            
            # Alerta al staff
            if STAFF_LOG_WEBHOOK_URL:
                try:
                    hook = Webhook(STAFF_LOG_WEBHOOK_URL)
                    embed = Embed(
                        title='🚨 IP No Autorizada - Intento Bloqueado',
                        color=0xff0000,
                        timestamp=datetime.now().isoformat()
                    )
                    embed.add_field(name='Jugador', value=f'`{player_name}`', inline=True)
                    embed.add_field(name='País', value=f'`{country_code or "Desconocido"}`', inline=True)
                    embed.add_field(name='IP', value=f'`{ip_address}`', inline=True)
                    embed.add_field(name='Tipo', value=f'`{notification_type}`', inline=True)
                    embed.add_field(name='Fuente', value='`Hookdeck`', inline=True)
                    hook.send(embed=embed)
                    app.logger.info("  ✅ Alerta enviada")
                except Exception as e:
                    app.logger.error(f"  ❌ Error enviando alerta: {e}")

        app.logger.info("="*60 + "\n")
        return jsonify({"status": "ok"}), 200

    except Exception as e:
        app.logger.error(f"❌ ERROR: {e}")
        return jsonify({"error": str(e)}), 500

# --- ENDPOINT DE PRUEBA ---
@app.route('/test')
def test():
    """Prueba simple"""
    return jsonify({
        "status": "ok", 
        "message": "Servidor funcionando",
        "hookdeck_destination": "/api/proxy-destino",
        "paises_permitidos": ALLOWED_COUNTRIES,
        "webhooks_configurados": {
            "Main": "✅ SI" if REAL_DISCORD_WEBHOOK_URL else "❌ NO (Falta Variable)",
            "Staff": "✅ SI" if STAFF_LOG_WEBHOOK_URL else "❌ NO (Opcional)",
            "Login": "✅ SI" if LOGIN_LOGOUT_WEBHOOK_URL else "❌ NO (Opcional)"
        }
    })

@app.route('/')
def index():
    return jsonify({
        "status": "Servidor Hookdeck Activo",
        "instrucciones": {
            "1": "URL en Dink: https://hkdk.events/knvi5xshnnwno6",
            "2": "Verifica logs en Render cuando hagas login",
            "3": "Usa /test para verificar el servidor"
        }
    })

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.logger.info(f"🚀 Servidor Hookdeck iniciado en puerto {port}")
    app.logger.info(f"✅ Endpoint para Hookdeck: /api/proxy-destino")
    app.logger.info(f"🌍 Países permitidos: {ALLOWED_COUNTRIES}")
    
    if not REAL_DISCORD_WEBHOOK_URL:
        app.logger.warning("ADVERTENCIA: 'REAL_DISCORD_WEBHOOK_URL' no está configurado.")
        app.logger.warning("El servidor recibirá datos pero NO PODRÁ enviarlos a Discord.")
        app.logger.warning("Ve al panel de Render -> Environment y añade la variable.")
        
    app.run(host='0.0.0.0', port=port)