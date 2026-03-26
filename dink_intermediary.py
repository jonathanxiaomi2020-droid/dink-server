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
DINK_LOG_CHANNEL_ID = 1433918805255655576
STAFF_ROLE_IDS = [938874749373804594, 938873962128089129, 1427823025163866233]
ALLOWED_COUNTRIES = ["US", "GB", "VE", "ES"]

class IPDetectorCog(commands.Cog):
    """Detects IP/Country from Dink messages"""
    
    def __init__(self, bot):
        self.bot = bot
        self.last_country = "UNKNOWN"
        self.last_ip = "UNKNOWN"
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Listen for Dink messages in the log channel"""
        
        if message.channel.id != DINK_LOG_CHANNEL_ID or not message.webhook_id:
            await self.bot.process_commands(message)
            return
        
        if not message.embeds:
            await self.bot.process_commands(message)
            return
        
        embed = message.embeds[0]
        
        if not embed.author or not embed.author.name:
            await self.bot.process_commands(message)
            return
        
        # Extract RSN
        rsn = embed.author.name.split(" on World")[0].lower().strip()
        
        # Extract country from the embed content/description
        country = self._extract_country_from_embed(embed)
        
        # Check if allowed
        is_allowed = country.upper() in ALLOWED_COUNTRIES
        
        # Notify
        await self._notify_login(rsn, country, is_allowed, message.created_at)
        
        await self.bot.process_commands(message)
    
    def _extract_country_from_embed(self, embed):
        """Extract country from embed"""
        
        # Check description
        if embed.description:
            # Look for country code patterns
            if "Cf-Ipcountry" in embed.description:
                lines = embed.description.split("\n")
                for line in lines:
                    if "Cf-Ipcountry" in line:
                        # Extract the country code
                        parts = line.split(":")
                        if len(parts) > 1:
                            country = parts[-1].strip().upper()
                            if len(country) == 2 and country.isalpha():
                                return country
        
        # Check fields
        for field in embed.fields:
            field_name = field.name.lower()
            if "país" in field_name or "country" in field_name or "ipcountry" in field_name:
                country = field.value.strip().upper()
                if len(country) == 2 and country.isalpha():
                    return country
        
        return "UNKNOWN"
    
    async def _notify_login(self, rsn: str, country: str, is_allowed: bool, timestamp: datetime):
        """Send notification"""
        
        ip_detector_channel_id = os.getenv("IP_DETECTOR_CHANNEL_ID")
        if not ip_detector_channel_id:
            return
        
        try:
            channel = self.bot.get_channel(int(ip_detector_channel_id))
        except (ValueError, TypeError):
            return
        
        if not channel:
            return
        
        # Color and status
        if is_allowed:
            color = discord.Color.green()
            status_icon = "✅"
            status_text = "PERMITIDO"
        else:
            color = discord.Color.red()
            status_icon = "⚠️"
            status_text = "BLOQUEADO"
        
        # Create embed
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
                value=f"**{rsn} intentó conectarse desde {country}**\n"
                      f"Países permitidos: {', '.join(ALLOWED_COUNTRIES)}",
                inline=False
            )
        else:
            embed.add_field(
                name="✅ VERIFICADO",
                value=f"**{rsn}** se conectó desde **{country}** ✓",
                inline=False
            )
        
        embed.set_footer(text="IP Detector - S T O N E Services")
        
        try:
            await channel.send(embed=embed)
        except Exception as e:
            print(f"Error: {e}")
    
    @app_commands.command(name="set_ip_channel", description="Configura el canal para alertas de IP")
    @app_commands.default_permissions(administrator=True)
    async def set_ip_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Configure the IP alert channel"""
        
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
            description=f"Las alertas se enviarán a {channel.mention}",
            color=discord.Color.green()
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(IPDetectorCog(bot))
