"""Private management console + keep-alive web server (for Render).

Serves a password-protected console at "/" to view and edit this server's bot settings
(channels, roles, anti-raid/anti-nuke), a public "/health" check, and pings itself every
10 min so Render's free web service doesn't spin down.

The console password is read from the CONSOLE_PASSWORD env var (never hardcoded, since the
repo is public). If it's not set, the console is disabled.
"""
import os
import html
import hmac
import hashlib
import aiohttp
from aiohttp import web
import discord
from discord import app_commands
from discord.ext import commands, tasks

from config_store import load_config, save_config, guild_config

COOKIE = "bearbot_auth"


def _to_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


LOGIN_HTML = """<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>BearBot Console — Login</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    background:radial-gradient(1200px 600px at 50% -10%,#2b2d5e 0%,#0f1020 60%);color:#e9eaf2;
    min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}
  .card{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:20px;
    padding:40px;max-width:380px;width:100%;box-shadow:0 20px 60px rgba(0,0,0,.45);text-align:center}
  h1{font-size:22px;margin-bottom:6px}
  p{color:#a6a8c0;font-size:13px;margin-bottom:22px}
  input{width:100%;padding:13px 14px;border-radius:12px;border:1px solid rgba(255,255,255,.12);
    background:rgba(0,0,0,.25);color:#fff;font-size:15px;margin-bottom:14px}
  button{width:100%;padding:13px;border:0;border-radius:12px;background:#5865F2;color:#fff;
    font-weight:600;font-size:15px;cursor:pointer}
  button:hover{filter:brightness(1.1)}
  .err{color:#ff6b6b;font-size:13px;margin-bottom:14px;min-height:18px}
</style></head><body>
  <div class="card">
    <h1>🐻 BearBot Console</h1>
    <p>Enter the management password to continue.</p>
    <form method="post" action="/login">
      <div class="err">__ERR__</div>
      <input type="password" name="password" placeholder="Password" autofocus>
      <button type="submit">Unlock</button>
    </form>
  </div>
</body></html>"""

CONSOLE_HTML = """<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>BearBot Console</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    background:radial-gradient(1400px 700px at 50% -10%,#2b2d5e 0%,#0f1020 55%);color:#e9eaf2;
    min-height:100vh;padding:28px}
  .wrap{max-width:860px;margin:0 auto}
  .top{display:flex;align-items:center;gap:16px;margin-bottom:24px}
  .top img{width:64px;height:64px;border-radius:50%;border:3px solid #5865F2}
  .top h1{font-size:22px}
  .top .sub{color:#a6a8c0;font-size:13px;display:flex;align-items:center;gap:7px;margin-top:3px}
  .dot{width:9px;height:9px;border-radius:50%;background:__STATUSCOLOR__;box-shadow:0 0 8px __STATUSCOLOR__}
  .spacer{flex:1}
  a.logout{color:#c9cbe0;font-size:13px;text-decoration:none;border:1px solid rgba(255,255,255,.14);
    padding:8px 14px;border-radius:10px}
  a.logout:hover{background:rgba(255,255,255,.06)}
  .grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:24px}
  .stat{background:rgba(255,255,255,.05);border-radius:14px;padding:16px;text-align:center}
  .stat .num{font-size:22px;font-weight:700}
  .stat .lbl{font-size:11px;color:#a6a8c0;text-transform:uppercase;letter-spacing:.06em;margin-top:3px}
  .flash{background:rgba(46,204,113,.15);border:1px solid rgba(46,204,113,.4);color:#9be7b8;
    padding:12px 16px;border-radius:12px;margin-bottom:18px;font-size:14px}
  .panel{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:16px;
    padding:22px;margin-bottom:18px}
  .panel h2{font-size:15px;margin-bottom:16px;color:#fff}
  .row{display:grid;grid-template-columns:1fr 1fr;gap:16px}
  label{display:block;font-size:12px;color:#a6a8c0;margin-bottom:6px;text-transform:uppercase;letter-spacing:.04em}
  select,input[type=number]{width:100%;padding:10px 12px;border-radius:10px;border:1px solid rgba(255,255,255,.12);
    background:rgba(0,0,0,.25);color:#fff;font-size:14px;margin-bottom:14px}
  .toggle{display:flex;align-items:center;gap:10px;margin-bottom:14px}
  .toggle input{width:18px;height:18px}
  .toggle label{margin:0;text-transform:none;letter-spacing:0;font-size:14px;color:#e9eaf2}
  .save{padding:13px 26px;border:0;border-radius:12px;background:#2ECC71;color:#08231a;font-weight:700;
    font-size:15px;cursor:pointer}
  .save:hover{filter:brightness(1.07)}
  .foot{color:#71738c;font-size:12px;margin-top:18px;text-align:center}
  .chcount{font-size:12px;color:#8a8ca6;margin-bottom:12px}
  .chwrap{columns:2;column-gap:22px}
  .cat{font-size:11px;color:#8a8ca6;text-transform:uppercase;letter-spacing:.06em;font-weight:700;
    margin:12px 0 4px;break-inside:avoid}
  .cat:first-child{margin-top:0}
  .ch{font-size:14px;color:#d7d9ec;padding:3px 0 3px 12px;break-inside:avoid}
  .muted{color:#8a8ca6}
</style></head><body>
  <div class="wrap">
    <div class="top">
      <img src="__AVATAR__" alt="">
      <div>
        <h1>__NAME__</h1>
        <div class="sub"><span class="dot"></span> __STATUS__ · managing <b>__GUILD__</b></div>
      </div>
      <div class="spacer"></div>
      <a class="logout" href="/logout">Log out</a>
    </div>

    <div class="grid">
      <div class="stat"><div class="num">__SERVERS__</div><div class="lbl">Servers</div></div>
      <div class="stat"><div class="num">__MEMBERS__</div><div class="lbl">Members</div></div>
      <div class="stat"><div class="num">__COMMANDS__</div><div class="lbl">Commands</div></div>
      <div class="stat"><div class="num">__UPTIME__</div><div class="lbl">Uptime</div></div>
    </div>

    __FLASH__

    <div class="panel">
      <h2>🗂️ Channels &amp; Categories</h2>
      <div class="chcount">__CHCOUNT__</div>
      <div class="chwrap">__CHANNELS__</div>
    </div>

    <form method="post" action="/save">
      <div class="panel">
        <h2>📥 Channels</h2>
        <div class="row">
          <div><label>Submissions channel</label><select name="submissions_channel">__SUB_OPTS__</select></div>
          <div><label>Log channel</label><select name="log_channel">__LOG_OPTS__</select></div>
        </div>
      </div>

      <div class="panel">
        <h2>🎭 Roles</h2>
        <div class="row">
          <div><label>Verify role</label><select name="verify_role">__VERIFY_OPTS__</select></div>
          <div><label>Submission role</label><select name="submission_role">__SUBMISSION_OPTS__</select></div>
          <div><label>Booster role</label><select name="booster_role">__BOOSTER_OPTS__</select></div>
          <div><label>Mod role</label><select name="mod_role">__MOD_OPTS__</select></div>
          <div><label>Admin role</label><select name="admin_role">__ADMIN_OPTS__</select></div>
          <div><label>Owner role</label><select name="owner_role">__OWNER_OPTS__</select></div>
        </div>
      </div>

      <div class="panel">
        <h2>🛡️ Anti-raid</h2>
        <div class="toggle"><input type="checkbox" name="ar_enabled" id="ar" __AR_ENABLED__><label for="ar">Enabled</label></div>
        <div class="row">
          <div><label>Joins threshold</label><input type="number" name="ar_threshold" min="2" value="__AR_THRESHOLD__"></div>
          <div><label>Window (seconds)</label><input type="number" name="ar_window" min="2" value="__AR_WINDOW__"></div>
          <div><label>Action</label><select name="ar_action"><option value="kick" __AR_KICK__>Kick</option><option value="ban" __AR_BAN__>Ban</option></select></div>
        </div>
      </div>

      <div class="panel">
        <h2>💣 Anti-nuke</h2>
        <div class="toggle"><input type="checkbox" name="an_enabled" id="an" __AN_ENABLED__><label for="an">Enabled</label></div>
        <div class="row">
          <div><label>Actions threshold</label><input type="number" name="an_threshold" min="2" value="__AN_THRESHOLD__"></div>
          <div><label>Window (seconds)</label><input type="number" name="an_window" min="5" value="__AN_WINDOW__"></div>
        </div>
      </div>

      <button class="save" type="submit">💾 Save changes</button>
      <div class="foot">Changes apply to the bot immediately.</div>
    </form>
  </div>
</body></html>"""

DISABLED_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>Console disabled</title>
<style>body{font-family:sans-serif;background:#0f1020;color:#e9eaf2;display:flex;min-height:100vh;
align-items:center;justify-content:center;text-align:center;padding:24px}</style></head>
<body><div><h1>🔒 Console disabled</h1>
<p>Set the <code>CONSOLE_PASSWORD</code> environment variable to enable the management console.</p></div></body></html>"""


class KeepAlive(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.session = None
        self.runner = None
        self.start_time = discord.utils.utcnow()
        self.port = int(os.environ.get("PORT", 8080))
        self.ping_url = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("KEEPALIVE_URL")
        self.password = os.environ.get("CONSOLE_PASSWORD")
        self.auth_token = (
            hashlib.sha256(("bearbot::" + self.password).encode()).hexdigest()
            if self.password else None
        )

    async def cog_load(self):
        self.session = aiohttp.ClientSession()
        try:
            app = web.Application(middlewares=[self._auth_middleware])
            app.router.add_get("/", self._console)
            app.router.add_get("/login", self._login_page)
            app.router.add_post("/login", self._login_submit)
            app.router.add_get("/logout", self._logout)
            app.router.add_post("/save", self._save)
            app.router.add_get("/health", self._health)
            self.runner = web.AppRunner(app)
            await self.runner.setup()
            await web.TCPSite(self.runner, "0.0.0.0", self.port).start()
            state = "enabled" if self.password else "DISABLED (set CONSOLE_PASSWORD)"
            print(f"🌐 Console + keep-alive server on port {self.port} — console {state}")
        except OSError as e:
            print(f"⚠️ Web server couldn't bind port {self.port}: {e}")
        self.keep_alive.start()

    async def cog_unload(self):
        self.keep_alive.cancel()
        if self.session:
            await self.session.close()
        if self.runner:
            await self.runner.cleanup()

    # ── auth ────────────────────────────────────────────────────────────────
    def _is_authed(self, request):
        token = request.cookies.get(COOKIE)
        return bool(token) and bool(self.auth_token) and hmac.compare_digest(token, self.auth_token)

    @web.middleware
    async def _auth_middleware(self, request, handler):
        # public endpoints
        if request.path in ("/health", "/login"):
            return await handler(request)
        if not self.password:
            return web.Response(text=DISABLED_HTML, content_type="text/html")
        if not self._is_authed(request):
            raise web.HTTPFound("/login")
        return await handler(request)

    async def _login_page(self, request):
        if not self.password:
            return web.Response(text=DISABLED_HTML, content_type="text/html")
        if self._is_authed(request):
            raise web.HTTPFound("/")
        return web.Response(text=LOGIN_HTML.replace("__ERR__", ""), content_type="text/html")

    async def _login_submit(self, request):
        if not self.password:
            return web.Response(text=DISABLED_HTML, content_type="text/html")
        data = await request.post()
        if hmac.compare_digest(str(data.get("password", "")), self.password):
            resp = web.HTTPFound("/")
            resp.set_cookie(COOKIE, self.auth_token, httponly=True, samesite="Lax", max_age=7 * 86400)
            return resp
        return web.Response(text=LOGIN_HTML.replace("__ERR__", "Wrong password"), content_type="text/html")

    async def _logout(self, request):
        resp = web.HTTPFound("/login")
        resp.del_cookie(COOKIE)
        return resp

    # ── data helpers ──────────────────────────────────────────────────────────
    def _guild(self):
        gid = os.environ.get("GUILD_ID")
        if gid and gid.isdigit():
            g = self.bot.get_guild(int(gid))
            if g:
                return g
        return self.bot.guilds[0] if self.bot.guilds else None

    def _stats(self):
        delta = discord.utils.utcnow() - self.start_time
        days, rem = divmod(int(delta.total_seconds()), 86400)
        hours, rem = divmod(rem, 3600)
        return {
            "name": self.bot.user.name if self.bot.user else "BearBot",
            "avatar": self.bot.user.display_avatar.url if self.bot.user else "",
            "online": self.bot.is_ready(),
            "servers": len(self.bot.guilds),
            "members": sum((g.member_count or 0) for g in self.bot.guilds),
            "commands": len([c for c in self.bot.tree.walk_commands() if isinstance(c, app_commands.Command)]),
            "uptime": f"{days}d {hours}h {rem // 60}m",
        }

    @staticmethod
    def _opts(items, current):
        out = ['<option value="">— none —</option>']
        for iid, name in items:
            sel = " selected" if str(current) == str(iid) else ""
            out.append(f'<option value="{iid}"{sel}>{html.escape(name)}</option>')
        return "".join(out)

    @staticmethod
    def _channel_icon(ch):
        if isinstance(ch, discord.VoiceChannel):
            return "🔊"
        if isinstance(ch, discord.StageChannel):
            return "🎤"
        if isinstance(ch, discord.ForumChannel):
            return "🗨️"
        return "#"

    def _channel_tree(self, guild):
        """Render every category and its channels (plus uncategorized) as a read-only tree."""
        def render(channels):
            rows = ""
            for c in sorted(channels, key=lambda c: c.position):
                rows += f'<div class="ch">{self._channel_icon(c)} {html.escape(c.name)}</div>'
            return rows

        parts = []
        uncategorized = [c for c in guild.channels
                         if c.category is None and not isinstance(c, discord.CategoryChannel)]
        if uncategorized:
            parts.append('<div class="cat">📂 No category</div>' + render(uncategorized))
        for category in guild.categories:
            parts.append(f'<div class="cat">📁 {html.escape(category.name)}</div>' + render(category.channels))
        return "".join(parts) or '<div class="muted">No channels found.</div>'

    def _render_console(self, guild, flash=""):
        cfg = load_config().get(str(guild.id), {})
        ar, an = cfg.get("antiraid", {}), cfg.get("antinuke", {})
        channels = [(c.id, "#" + c.name) for c in guild.text_channels]
        roles = [(r.id, r.name) for r in sorted(guild.roles, key=lambda r: r.position, reverse=True)
                 if not r.is_default() and not r.managed]
        s = self._stats()
        repl = {
            "__NAME__": html.escape(s["name"]),
            "__AVATAR__": s["avatar"],
            "__GUILD__": html.escape(guild.name),
            "__STATUS__": "Online" if s["online"] else "Connecting…",
            "__STATUSCOLOR__": "#2ECC71" if s["online"] else "#E67E22",
            "__SERVERS__": str(s["servers"]),
            "__MEMBERS__": f'{s["members"]:,}',
            "__COMMANDS__": str(s["commands"]),
            "__UPTIME__": s["uptime"],
            "__FLASH__": flash,
            "__CHCOUNT__": f"{len(guild.categories)} categories · {len(guild.channels) - len(guild.categories)} channels",
            "__CHANNELS__": self._channel_tree(guild),
            "__SUB_OPTS__": self._opts(channels, cfg.get("submissions_channel")),
            "__LOG_OPTS__": self._opts(channels, cfg.get("log_channel")),
            "__VERIFY_OPTS__": self._opts(roles, cfg.get("verify_role")),
            "__SUBMISSION_OPTS__": self._opts(roles, cfg.get("submission_role")),
            "__BOOSTER_OPTS__": self._opts(roles, cfg.get("booster_role")),
            "__MOD_OPTS__": self._opts(roles, cfg.get("mod_role")),
            "__ADMIN_OPTS__": self._opts(roles, cfg.get("admin_role")),
            "__OWNER_OPTS__": self._opts(roles, cfg.get("owner_role")),
            "__AR_ENABLED__": "checked" if ar.get("enabled") else "",
            "__AR_THRESHOLD__": str(ar.get("threshold", 5)),
            "__AR_WINDOW__": str(ar.get("window", 10)),
            "__AR_KICK__": "selected" if ar.get("action", "kick") == "kick" else "",
            "__AR_BAN__": "selected" if ar.get("action") == "ban" else "",
            "__AN_ENABLED__": "checked" if an.get("enabled") else "",
            "__AN_THRESHOLD__": str(an.get("threshold", 3)),
            "__AN_WINDOW__": str(an.get("window", 30)),
        }
        out = CONSOLE_HTML
        for k, v in repl.items():
            out = out.replace(k, str(v))
        return out

    # ── routes ────────────────────────────────────────────────────────────────
    async def _console(self, request):
        guild = self._guild()
        if guild is None:
            return web.Response(text="<h1>Bot isn't connected to a server yet.</h1>", content_type="text/html")
        flash = ('<div class="flash">✅ Settings saved.</div>' if request.query.get("saved") else "")
        return web.Response(text=self._render_console(guild, flash), content_type="text/html")

    async def _save(self, request):
        guild = self._guild()
        if guild is None:
            raise web.HTTPFound("/")
        data = await request.post()
        config = load_config()
        g = guild_config(config, guild.id)

        for key in ("submissions_channel", "log_channel", "verify_role", "submission_role",
                    "booster_role", "mod_role", "admin_role", "owner_role"):
            value = data.get(key)
            if value:
                g[key] = int(value)
            else:
                g.pop(key, None)

        g["antiraid"] = {
            "enabled": data.get("ar_enabled") == "on",
            "threshold": max(2, _to_int(data.get("ar_threshold"), 5)),
            "window": max(2, _to_int(data.get("ar_window"), 10)),
            "action": data.get("ar_action") if data.get("ar_action") in ("kick", "ban") else "kick",
        }
        g["antinuke"] = {
            "enabled": data.get("an_enabled") == "on",
            "threshold": max(2, _to_int(data.get("an_threshold"), 3)),
            "window": max(5, _to_int(data.get("an_window"), 30)),
            "whitelist": g.get("antinuke", {}).get("whitelist", []),
        }
        save_config(config)
        raise web.HTTPFound("/?saved=1")

    async def _health(self, request):
        return web.Response(text="OK")

    # ── keep-alive ──────────────────────────────────────────────────────────
    @tasks.loop(minutes=10)
    async def keep_alive(self):
        if not self.ping_url:
            print("💓 Keep-alive heartbeat (set RENDER_EXTERNAL_URL to enable self-ping)")
            return
        url = self.ping_url.rstrip("/") + "/health"
        try:
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                print(f"💓 Keep-alive pinged {url} -> {resp.status}")
        except Exception as e:
            print(f"⚠️ Keep-alive ping failed: {e}")

    @keep_alive.before_loop
    async def before_keep_alive(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(KeepAlive(bot))
