"""Keep-alive for Render: a tiny web server + a self-ping loop so the service doesn't sleep.

Render free web services spin down after ~15 min with no inbound HTTP traffic. We bind an
HTTP server to $PORT (required for a web service anyway) and ping our own public URL every
10 minutes so there's always recent inbound traffic.

Set RENDER_EXTERNAL_URL (Render provides this automatically) to enable the self-ping.
"""
import os
import aiohttp
from aiohttp import web
from discord.ext import commands, tasks


class KeepAlive(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.session = None
        self.runner = None
        self.port = int(os.environ.get("PORT", 8080))
        # Render exposes the public URL here; fall back to a manual override if set.
        self.ping_url = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("KEEPALIVE_URL")

    async def cog_load(self):
        self.session = aiohttp.ClientSession()
        try:
            app = web.Application()
            app.router.add_get("/", self._handle)
            app.router.add_get("/health", self._handle)
            self.runner = web.AppRunner(app)
            await self.runner.setup()
            await web.TCPSite(self.runner, "0.0.0.0", self.port).start()
            print(f"🌐 Keep-alive web server listening on port {self.port}")
        except OSError as e:
            # e.g. port already in use locally — not fatal, the bot still runs
            print(f"⚠️ Keep-alive web server couldn't bind port {self.port}: {e}")
        self.keep_alive.start()

    async def cog_unload(self):
        self.keep_alive.cancel()
        if self.session:
            await self.session.close()
        if self.runner:
            await self.runner.cleanup()

    async def _handle(self, request):
        return web.Response(text="BearBot is alive! 🐻")

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
