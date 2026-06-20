"""BearBot — GD collab event bot. Entry point: sets up the bot and loads cogs."""
import os
import sys
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from cogs.verification import VerifyView

# Windows consoles default to cp1252, which can't encode the emoji in our log prints.
# Force UTF-8 so startup logging doesn't crash.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

# load DISCORD_TOKEN (and any other vars) from a local .env file if present
load_dotenv()

# cogs to load on startup
EXTENSIONS = [
    "cogs.events",
    "cogs.moderation",
    "cogs.verification",
    "cogs.protection",
    "cogs.server_setup",
    "cogs.admin",
    "cogs.purge",
    "cogs.info",
    "cogs.utility",
    "cogs.help",
    "cogs.keepalive",
]

# ── Bot setup ────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.dm_messages = True


class BearBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # register the persistent verification button so it survives restarts
        self.add_view(VerifyView())
        for ext in EXTENSIONS:
            await self.load_extension(ext)
        # every command needs a guild (they all read interaction.guild) — block DM usage
        for command in self.tree.walk_commands():
            command.guild_only = True

        # If GUILD_ID is set, sync to that server for INSTANT command updates.
        # Otherwise sync globally (can take up to an hour to appear in Discord).
        guild_id = os.environ.get("GUILD_ID")
        if guild_id and guild_id.isdigit():
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            print(f"⚡ Synced {len(synced)} commands to guild {guild_id} (instant)")
            # Delete any leftover GLOBAL commands on Discord so they don't show as
            # duplicates alongside the guild ones. We do this via the HTTP API directly
            # so the local command tree stays intact (that's what /help reads from).
            if self.application_id:
                await self.http.bulk_upsert_global_commands(self.application_id, [])
        else:
            synced = await self.tree.sync()
            print(f"🌍 Synced {len(synced)} commands globally (may take up to 1 hour to appear)")

    async def on_ready(self):
        print(f"✅ Logged in as {self.user} (ID: {self.user.id})")


bot = BearBot()


# ── Global slash-command error handler ────────────────────────────────────────
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "❌ You don't have permission to use this command."
    elif isinstance(error, app_commands.BotMissingPermissions):
        perms = ", ".join(error.missing_permissions)
        msg = f"❌ I'm missing permissions to do that: **{perms}**."
    elif isinstance(error, app_commands.CheckFailure):
        msg = "❌ You can't use this command."
    else:
        msg = f"⚠️ Something went wrong: {error}"
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except discord.HTTPException:
        pass


# ── Run ───────────────────────────────────────────────────────────────────────
TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("No DISCORD_TOKEN found in environment variables. Set it before running.")

bot.run(TOKEN)
