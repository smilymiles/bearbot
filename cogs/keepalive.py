"""Web server for Render: a status dashboard + keep-alive self-ping.

Serves a dashboard at "/" (bot stats + invite link), a JSON endpoint at "/stats", and a
plain "/health" check. Also pings RENDER_EXTERNAL_URL every 10 min so Render's free web
service doesn't spin down (it sleeps after ~15 min with no inbound HTTP traffic).
"""
import os
import aiohttp
from aiohttp import web
import discord
from discord import app_commands
from discord.ext import commands, tasks

GITHUB_URL = "https://github.com/smilymiles/bearbot"

# Permissions the bot needs (used to build the invite link on the dashboard).
INVITE_PERMS = discord.Permissions(
    manage_guild=True, manage_roles=True, manage_channels=True, manage_nicknames=True,
    kick_members=True, ban_members=True, moderate_members=True, manage_messages=True,
    view_audit_log=True, read_messages=True, send_messages=True, embed_links=True,
    add_reactions=True, read_message_history=True, change_nickname=True,
)

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="30">
<title>__NAME__ Dashboard</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: radial-gradient(1200px 600px at 50% -10%, #2b2d5e 0%, #0f1020 60%);
    color: #e9eaf2; min-height: 100vh; display: flex; align-items: center;
    justify-content: center; padding: 24px;
  }
  .card {
    background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08);
    border-radius: 20px; padding: 40px; max-width: 560px; width: 100%;
    box-shadow: 0 20px 60px rgba(0,0,0,0.45); backdrop-filter: blur(8px); text-align: center;
  }
  .avatar { width: 96px; height: 96px; border-radius: 50%; border: 3px solid #5865F2; }
  h1 { font-size: 28px; margin: 16px 0 4px; }
  .status { display: inline-flex; align-items: center; gap: 8px; font-size: 14px;
            color: #b9bbd0; margin-bottom: 24px; }
  .dot { width: 10px; height: 10px; border-radius: 50%; background: __STATUS_COLOR__;
         box-shadow: 0 0 10px __STATUS_COLOR__; }
  .grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; margin: 8px 0 28px; }
  .stat { background: rgba(255,255,255,0.05); border-radius: 14px; padding: 18px; }
  .stat .num { font-size: 26px; font-weight: 700; color: #fff; }
  .stat .lbl { font-size: 12px; color: #a6a8c0; text-transform: uppercase; letter-spacing: .06em; margin-top: 4px; }
  .btns { display: flex; gap: 12px; justify-content: center; flex-wrap: wrap; }
  a.btn { text-decoration: none; padding: 13px 22px; border-radius: 12px; font-weight: 600;
          font-size: 15px; transition: transform .08s ease, filter .2s ease; display: inline-block; }
  a.btn:hover { transform: translateY(-2px); filter: brightness(1.1); }
  .primary { background: #5865F2; color: #fff; }
  .ghost { background: rgba(255,255,255,0.08); color: #e9eaf2; }
  .foot { margin-top: 22px; font-size: 12px; color: #71738c; }
</style>
</head>
<body>
  <div class="card">
    <img class="avatar" src="__AVATAR__" alt="avatar">
    <h1>__NAME__</h1>
    <div class="status"><span class="dot"></span> __STATUS_TEXT__</div>
    <div class="grid">
      <div class="stat"><div class="num">__GUILDS__</div><div class="lbl">Servers</div></div>
      <div class="stat"><div class="num">__MEMBERS__</div><div class="lbl">Members</div></div>
      <div class="stat"><div class="num">__COMMANDS__</div><div class="lbl">Commands</div></div>
      <div class="stat"><div class="num">__UPTIME__</div><div class="lbl">Uptime</div></div>
    </div>
    <div class="btns">
      <a class="btn primary" href="__INVITE__" target="_blank" rel="noopener">➕ Add to Server</a>
      <a class="btn ghost" href="__GITHUB__" target="_blank" rel="noopener">⭐ GitHub</a>
    </div>
    <div class="foot">A Geometry Dash collab event bot · auto-refreshes every 30s</div>
  </div>
</body>
</html>"""


class KeepAlive(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.session = None
        self.runner = None
        self.start_time = discord.utils.utcnow()
        self.port = int(os.environ.get("PORT", 8080))
        self.ping_url = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("KEEPALIVE_URL")

    async def cog_load(self):
        self.session = aiohttp.ClientSession()
        try:
            app = web.Application()
            app.router.add_get("/", self._dashboard)
            app.router.add_get("/health", self._health)
            app.router.add_get("/stats", self._stats)
            self.runner = web.AppRunner(app)
            await self.runner.setup()
            await web.TCPSite(self.runner, "0.0.0.0", self.port).start()
            print(f"🌐 Dashboard + keep-alive server listening on port {self.port}")
        except OSError as e:
            print(f"⚠️ Web server couldn't bind port {self.port}: {e}")
        self.keep_alive.start()

    async def cog_unload(self):
        self.keep_alive.cancel()
        if self.session:
            await self.session.close()
        if self.runner:
            await self.runner.cleanup()

    # ── live stats ────────────────────────────────────────────────────────────
    def _gather_stats(self):
        bot = self.bot
        delta = discord.utils.utcnow() - self.start_time
        days, rem = divmod(int(delta.total_seconds()), 86400)
        hours, rem = divmod(rem, 3600)
        minutes = rem // 60
        return {
            "name": bot.user.name if bot.user else "BearBot",
            "avatar": bot.user.display_avatar.url if bot.user else "",
            "online": bot.is_ready(),
            "servers": len(bot.guilds),
            "members": sum((g.member_count or 0) for g in bot.guilds),
            "commands": len([c for c in bot.tree.walk_commands() if isinstance(c, app_commands.Command)]),
            "uptime": f"{days}d {hours}h {minutes}m",
            "invite": (
                f"https://discord.com/oauth2/authorize?client_id={bot.user.id}"
                f"&scope=bot+applications.commands&permissions={INVITE_PERMS.value}"
                if bot.user else "#"
            ),
        }

    async def _dashboard(self, request):
        s = self._gather_stats()
        html = (DASHBOARD_HTML
                .replace("__NAME__", s["name"])
                .replace("__AVATAR__", s["avatar"])
                .replace("__STATUS_TEXT__", "Online" if s["online"] else "Connecting…")
                .replace("__STATUS_COLOR__", "#2ECC71" if s["online"] else "#E67E22")
                .replace("__GUILDS__", str(s["servers"]))
                .replace("__MEMBERS__", f'{s["members"]:,}')
                .replace("__COMMANDS__", str(s["commands"]))
                .replace("__UPTIME__", s["uptime"])
                .replace("__INVITE__", s["invite"])
                .replace("__GITHUB__", GITHUB_URL))
        return web.Response(text=html, content_type="text/html")

    async def _stats(self, request):
        return web.json_response(self._gather_stats())

    async def _health(self, request):
        return web.Response(text="OK")

    @tasks.loop(minutes=10)
    async def keep_alive(self):
        if not self.ping_url:
            print("💓 Keep-alive heartbeat (set RENDER_EXTERNAL_URL to enable self-ping)")
            return
        try:
            async with self.session.get(self.ping_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                print(f"💓 Keep-alive pinged {self.ping_url} -> {resp.status}")
        except Exception as e:
            print(f"⚠️ Keep-alive ping failed: {e}")

    @keep_alive.before_loop
    async def before_keep_alive(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(KeepAlive(bot))
