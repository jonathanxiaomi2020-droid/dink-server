import discord
from discord.ext import commands
from discord import app_commands
import os
import requests
import json
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Configuration
DINK_LOG_CHANNEL_ID = 1433918805255655576  # Where Dink sends raw data
STAFF_ROLE_IDS = [938874749373804594, 938873962128089129, 1427823025163866233]
ALLOWED_COUNTRIES = ["US", "GB", "VE"]  # Allowed countries

class IPDetectorCog(commands.Cog):
    """A cog to detect and log IP/Country information from Dink webhook messages."""
    
    def __init__(self, bot):
        self.bot = bot
        self.tracked_logins = {}
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Listen for Dink webhook messages and extract Country data."""
        
        # Only process messages in the Dink log channel from webhooks
        if message.channel.id != DINK_LOG_CHANNEL_ID or not message.webhook_id:
            await self.bot.process_commands(message)
            return
        
        if not message.embeds:
            await self.bot.process_commands(message)
            return
        
        embed = message.embeds[0]
        
        # Dink includes player name in the author field
        if not embed.author or not embed.author.name:
            await self.bot.process_commands(message)
            return
        
        # Extract RSN from "Player Name on World 123" format
        rsn = embed.author.name.split(" on World")[0].lower().strip()
        
        # Detectar país desde el embed o desde Cloudflare
        country = await self._extract_country_from_embed(embed)
        
        # Check if country is allowed
        is_allowed = country.upper() in ALLOWED_COUNTRIES
        
        # Notify in the IP detector channel (if configured)
        await self._notify_login(rsn, country, is_allowed, message.created_at, embed)
        
        await self.bot.process_commands(message)
    
    async def _extract_country_from_embed(self, embed):
        """Extract country from the embed."""
        
        # Buscar en la descripción del embed
        if embed.description:
            lines = embed.description.split("\n")
            for line in lines:
                # Buscar el patrón: "Cf-Ipcountry: XX"
                if "ipcountry" in line.lower():
                    # Extraer el código del país (últimas 2 caracteres)
                    parts = line.split(":")
                    if len(parts) > 1:
                        country_code = parts[-1].strip().upper()
                        # Validar que sea un código de país (2 letras)
                        if len(country_code) == 2 and country_code.isalpha():
                            return country_code
        
        # Buscar en los fields del embed
        for field in embed.fields:
            field_name = field.name.lower()
            if "país" in field_name or "country" in field_name:
                country_code = field.value.strip().upper()
                if len(country_code) == 2 and country_code.isalpha():
                    return country_code
        
        # Si no encontramos nada, retornar UNKNOWN
        return "UNKNOWN"
    
    async def _notify_login(self, rsn: str, country: str, is_allowed: bool, timestamp: datetime, original_embed):
        """Send a notification to the IP detector channel."""
        
        # Get the channel ID from environment
        ip_detector_channel_id = os.getenv("IP_DETECTOR_CHANNEL_ID")
        if not ip_detector_channel_id:
            print(f"⚠️ IP_DETECTOR_CHANNEL_ID no configurado. Configure en .env")
            return
        
        try:
            channel = self.bot.get_channel(int(ip_detector_channel_id))
        except (ValueError, TypeError):
            print(f"❌ IP_DETECTOR_CHANNEL_ID inválido: {ip_detector_channel_id}")
            return
        
        if not channel:
            print(f"⚠️ IP Detector channel no encontrado (ID: {ip_detector_channel_id})")
            return
        
        # Determine color and icon based on country allowance
        if is_allowed:
            color = discord.Color.green()
            status_icon = "✅"
            status_text = "PERMITIDO"
        else:
            color = discord.Color.red()
            status_icon = "⚠️"
            status_text = "BLOQUEADO"
        
        # Create the embed
        embed = discord.Embed(
            title=f"{status_icon} Login Detectado - {rsn.upper()}",
            color=color,
            timestamp=timestamp
        )
        
        embed.add_field(name="👤 Cuenta", value=f"`{rsn}`", inline=True)
        embed.add_field(name="🌍 País", value=f"`{country}`", inline=True)
        embed.add_field(name="✅ Estado", value=status_text, inline=True)
        
        if not is_allowed:
            embed.add_field(
                name="⚠️ ALERTA",
                value=f"**{rsn} se conectó desde {country}**\n"
                      f"Países permitidos: {', '.join(ALLOWED_COUNTRIES)}",
                inline=False
            )
        else:
            embed.add_field(
                name="✅ VERIFICADO",
                value=f"**{rsn} se conectó desde {country}** ✓\n"
                      f"País permitido.",
                inline=False
            )
        
        embed.set_footer(text="IP Detector - S T O N E Services")
        
        try:
            await channel.send(embed=embed)
        except Exception as e:
            print(f"❌ Error enviando notificación: {e}")
    
    @app_commands.command(name="set_ip_channel", description="Configura el canal para alertas de IP.")
    @app_commands.default_permissions(administrator=True)
    async def set_ip_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Staff command para configurar el canal de detección de IP."""
        
        env_file = ".env"
        
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                env_content = f.read()
        except FileNotFoundError:
            env_content = ""
        
        lines = env_content.split("\n")
        found = False
        new_lines = []
        
        for line in lines:
            if line.startswith("IP_DETECTOR_CHANNEL_ID="):
                new_lines.append(f"IP_DETECTOR_CHANNEL_ID={channel.id}")
                found = True
            else:
                new_lines.append(line)
        
        if not found:
            new_lines.append(f"IP_DETECTOR_CHANNEL_ID={channel.id}")
        
        with open(env_file, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines))
        
        os.environ["IP_DETECTOR_CHANNEL_ID"] = str(channel.id)
        
        embed = discord.Embed(
            title="✅ Canal Configurado",
            description=f"Las alertas de IP se enviarán a {channel.mention}",
            color=discord.Color.green()
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    """Setup function to load this cog."""
    await bot.add_cog(IPDetectorCog(bot))
