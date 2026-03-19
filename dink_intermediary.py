import os
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import json
import sys
import time
from datetime import datetime
from dhooks import Webhook, Embed
import requests

load_dotenv()
app = Flask(__name__)

# Forzar logs inmediatos
sys.stdout.reconfigure(line_buffering=True)

# --- CONFIGURACIÓN ---
REAL_DISCORD_WEBHOOK_URL = os.getenv("REAL_DISCORD_WEBHOOK_URL")
STAFF_LOG_WEBHOOK_URL = os.getenv("STAFF_LOG_WEBHOOK_URL")
LOGIN_LOGOUT_WEBHOOK_URL = os.getenv("LOGIN_LOGOUT_WEBHOOK_URL")

# Países permitidos
ALLOWED_COUNTRIES = [c.strip().upper() for c in os.getenv("ALLOWED_COUNTRIES", "US,GB").split(',')]

# --- ENDPOINT PARA RECIBIR DE HOOKDECK ---
@app.route('/api/proxy-destino', methods=['POST'])
def proxy_destino():
    """Recibe los webhooks desde Hookdeck"""
    print("\n" + "="*60)
    print(f"📨 RECIBIDO DE HOOKDECK - {datetime.now().isoformat()}")
    
    try:
        # Obtener IP real (Hookdeck la pasa en headers)
        ip_address = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
        print(f"🌐 IP: {ip_address}")

        # Geolocalización
        country_code = None
        try:
            geo = requests.get(f'http://ip-api.com/json/{ip_address}?fields=countryCode', timeout=3)
            if geo.status_code == 200:
                data = geo.json()
                if data.get('status') == 'success':
                    country_code = data.get('countryCode')
                    print(f"📍 País: {country_code}")
        except Exception as e:
            print(f"⚠️ Geo error: {e}")

        # Obtener payload de Dink
        payload = request.get_json()
        if not payload:
            return jsonify({"error": "No payload"}), 400

        # Extraer información del jugador
        player_name = payload.get('playerName') or payload.get('player_name', 'Desconocido')
        notification_type = payload.get('type') or payload.get('extra', {}).get('type', 'General')
        
        print(f"👤 Jugador: {player_name}")
        print(f"📌 Tipo: {notification_type}")

        # --- DECISIÓN ---
        if country_code and country_code in ALLOWED_COUNTRIES:
            print(f"✅ PAÍS PERMITIDO: {country_code}")
            
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
                    print("  ✅ Log de staff enviado")
                except Exception as e:
                    print(f"  ❌ Error enviando log: {e}")

            # Reenviar mensaje original
            target = REAL_DISCORD_WEBHOOK_URL
            if notification_type in ['LOGIN', 'LOGOUT'] and LOGIN_LOGOUT_WEBHOOK_URL:
                target = LOGIN_LOGOUT_WEBHOOK_URL
                print(f"  📨 Usando webhook específico para {notification_type}")

            if target:
                try:
                    response = requests.post(target, json=payload, timeout=5)
                    if response.status_code in [200, 204]:
                        print("  ✅ Mensaje reenviado a Discord")
                    else:
                        print(f"  ⚠️ Discord respondió {response.status_code}")
                except Exception as e:
                    print(f"  ❌ Error reenviando: {e}")

        else:
            print(f"❌ PAÍS NO PERMITIDO: {country_code or 'Desconocido'}")
            
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
                    print("  ✅ Alerta enviada")
                except Exception as e:
                    print(f"  ❌ Error enviando alerta: {e}")

        print("="*60 + "\n")
        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print(f"❌ ERROR: {e}")
        return jsonify({"error": str(e)}), 500

# --- ENDPOINT DE PRUEBA ---
@app.route('/test')
def test():
    """Prueba simple"""
    return jsonify({
        "status": "ok", 
        "message": "Servidor funcionando",
        "hookdeck_destination": "/api/proxy-destino",
        "paises_permitidos": ALLOWED_COUNTRIES
    })

@app.route('/')
def index():
    return jsonify({
        "status": "Servidor Hookdeck Activo",
        "instrucciones": {
            "1": "URL en Dink: https://hkdk.events/2q7ojdp930t4hg",
            "2": "Verifica logs en Render cuando hagas login",
            "3": "Usa /test para verificar el servidor"
        }
    })

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    print(f"\n🚀 Servidor Hookdeck iniciado en puerto {port}")
    print(f"✅ Endpoint para Hookdeck: /api/proxy-destino")
    print(f"🌍 Países permitidos: {ALLOWED_COUNTRIES}")
    app.run(host='0.0.0.0', port=port)