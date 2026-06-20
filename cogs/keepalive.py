"""Private management console + keep-alive web server (for Render).

Password-protected console (CONSOLE_PASSWORD env var) with two pages:
  • Settings    — channels/roles, anti-raid/anti-nuke, live channel browser
  • Moderation  — member actions, channel actions, purge, warnings table, nick

All moderation actions reuse the cog helpers (Moderation.mod_* / Purge.purge_messages),
so the web console and the slash commands run the exact same logic.

A public /health endpoint is kept for the keep-alive self-ping.
"""
import os
import re
import html
import hmac
import hashlib
from urllib.parse import urlencode
from datetime import timedelta

import aiohttp
from aiohttp import web
import discord
from discord import app_commands
from discord.ext import commands, tasks

from config_store import load_config, save_config, guild_config

COOKIE = "bearbot_auth"
_ID_RE = re.compile(r"\d{15,20}")


def _to_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_user_id(text):
    """Extract a user ID from a raw ID or an @mention like <@123> / <@!123>."""
    if not text:
        return None
    m = _ID_RE.search(text)
    return int(m.group()) if m else None


STYLE = """
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    background:radial-gradient(1400px 700px at 50% -10%,#2b2d5e 0%,#0f1020 55%);color:#e9eaf2;
    min-height:100vh;padding:28px}
  .wrap{max-width:900px;margin:0 auto}
  .top{display:flex;align-items:center;gap:16px;margin-bottom:18px;flex-wrap:wrap}
  .top img{width:60px;height:60px;border-radius:50%;border:3px solid #5865F2}
  .top h1{font-size:21px}
  .top .sub{color:#a6a8c0;font-size:13px;display:flex;align-items:center;gap:7px;margin-top:3px}
  .dot{width:9px;height:9px;border-radius:50%}
  .dot.on{background:#2ECC71;box-shadow:0 0 8px #2ECC71}
  .dot.off{background:#E67E22;box-shadow:0 0 8px #E67E22}
  .spacer{flex:1}
  .nav{display:flex;gap:8px}
  .navlink{color:#c9cbe0;font-size:13px;text-decoration:none;border:1px solid rgba(255,255,255,.14);
    padding:8px 14px;border-radius:10px}
  .navlink:hover{background:rgba(255,255,255,.06)}
  .navlink.active{background:#5865F2;border-color:#5865F2;color:#fff}
  .navlink.logout{color:#ff9b9b;border-color:rgba(255,107,107,.3)}
  .grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:18px}
  .stat{background:rgba(255,255,255,.05);border-radius:14px;padding:16px;text-align:center}
  .stat .num{font-size:22px;font-weight:700}
  .stat .lbl{font-size:11px;color:#a6a8c0;text-transform:uppercase;letter-spacing:.06em;margin-top:3px}
  .flash{padding:12px 16px;border-radius:12px;margin-bottom:16px;font-size:14px}
  .flash.ok{background:rgba(46,204,113,.15);border:1px solid rgba(46,204,113,.4);color:#9be7b8}
  .flash.err{background:rgba(231,76,60,.15);border:1px solid rgba(231,76,60,.4);color:#ff9b9b}
  .panel{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:16px;
    padding:22px;margin-bottom:18px}
  .panel h2{font-size:15px;margin-bottom:16px;color:#fff}
  .row{display:grid;grid-template-columns:1fr 1fr;gap:16px}
  label{display:block;font-size:12px;color:#a6a8c0;margin-bottom:6px;text-transform:uppercase;letter-spacing:.04em}
  select,input[type=number],input[type=text],input[type=password]{width:100%;padding:10px 12px;border-radius:10px;
    border:1px solid rgba(255,255,255,.12);background:rgba(0,0,0,.25);color:#fff;font-size:14px;margin-bottom:12px}
  .toggle{display:flex;align-items:center;gap:10px;margin-bottom:14px}
  .toggle input{width:18px;height:18px;margin:0}
  .toggle label{margin:0;text-transform:none;letter-spacing:0;font-size:14px;color:#e9eaf2}
  button{cursor:pointer;border:0;border-radius:10px;font-weight:700;font-size:14px;padding:11px 16px;color:#fff}
  button:hover{filter:brightness(1.08)}
  .save{background:#2ECC71;color:#08231a;padding:13px 26px;border-radius:12px;font-size:15px}
  .btn.red{background:#E74C3C}.btn.orange{background:#E67E22}.btn.green{background:#2ECC71;color:#08231a}
  .btn.yellow{background:#F1C40F;color:#3a2f00}.btn.grey{background:#5a5d78}.btn.blue{background:#5865F2}
  .btn.sm{padding:7px 12px;font-size:12px}
  .modgrid{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}
  .mini{background:rgba(0,0,0,.18);border:1px solid rgba(255,255,255,.06);border-radius:12px;padding:14px}
  .mini h3{font-size:13px;margin-bottom:10px;color:#dfe1f1}
  .mini .btn{width:100%}
  .btnrow{display:flex;gap:10px;flex-wrap:wrap}
  .btnrow button{flex:1;min-width:120px}
  .foot{color:#71738c;font-size:12px;margin-top:18px;text-align:center}
  .chcount{font-size:12px;color:#8a8ca6;margin-bottom:12px}
  .chwrap{columns:2;column-gap:22px}
  .cat{font-size:11px;color:#8a8ca6;text-transform:uppercase;letter-spacing:.06em;font-weight:700;margin:12px 0 4px;break-inside:avoid}
  .cat:first-child{margin-top:0}
  .ch{font-size:14px;color:#d7d9ec;padding:3px 0 3px 12px;break-inside:avoid}
  .muted{color:#8a8ca6}
  .search{margin-bottom:12px}
  table.warns{width:100%;border-collapse:collapse;font-size:13px}
  table.warns th,table.warns td{text-align:left;padding:9px 10px;border-bottom:1px solid rgba(255,255,255,.07)}
  table.warns th{color:#a6a8c0;text-transform:uppercase;font-size:11px;letter-spacing:.04em}
  table.warns form{margin:0}
"""

PAGE_SHELL = """<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>BearBot Console</title><style>__STYLE__</style></head><body>
  <div class="wrap">
    <div class="top">
      <img src="__AVATAR__" alt="">
      <div><h1>__NAME__</h1>
        <div class="sub"><span class="dot __DOT__"></span> __STATUS__ · managing <b>__GUILD__</b></div></div>
      <div class="spacer"></div>
      __NAV__
    </div>
    __FLASH__
    __BODY__
    <div class="foot">BearBot management console · changes apply immediately</div>
  </div>
</body></html>"""

LOGIN_HTML = """<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>BearBot Console — Login</title><style>__STYLE__
  .card{max-width:380px;margin:12vh auto;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);
    border-radius:20px;padding:40px;text-align:center}
  .card h1{font-size:22px;margin-bottom:6px}.card p{color:#a6a8c0;font-size:13px;margin-bottom:20px}
  .card button{width:100%;background:#5865F2;padding:13px}
  .err{color:#ff6b6b;font-size:13px;min-height:18px;margin-bottom:10px}
</style></head><body>
  <div class="card">
    <h1>🐻 BearBot Console</h1><p>Enter the management password.</p>
    <form method="post" action="/login">
      <div class="err">__ERR__</div>
      <input type="password" name="password" placeholder="Password" autofocus>
      <button type="submit">Unlock</button>
    </form>
  </div>
</body></html>"""

DISABLED_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>Console disabled</title>
<style>body{font-family:sans-serif;background:#0f1020;color:#e9eaf2;display:flex;min-height:100vh;
align-items:center;justify-content:center;text-align:center;padding:24px}</style></head>
<body><div><h1>🔒 Console disabled</h1>
<p>Set the <code>CONSOLE_PASSWORD</code> environment variable to enable the management console.</p></div></body></html>"""

SEARCH_JS = """<script>
function filterWarns(){
  var q=document.getElementById('warnsearch').value.toLowerCase();
  document.querySelectorAll('#warnstable tbody tr').forEach(function(r){
    r.style.display = r.innerText.toLowerCase().indexOf(q)>-1 ? '' : 'none';
  });
}
</script>"""


class KeepAlive(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.session = None
        self.runner = None
        self.start_time = discord.utils.utcnow()
        self.port = int(os.environ.get("PORT", 8080))
        self.ping_url = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("KEEPALIVE_URL")
        self.password = os.environ.get("CONSOLE_PASSWORD")
        self.auth_token = (hashlib.sha256(("bearbot::" + self.password).encode()).hexdigest()
                           if self.password else None)

    async def cog_load(self):
        self.session = aiohttp.ClientSession()
        try:
            app = web.Application(middlewares=[self._auth_middleware])
            app.router.add_get("/", self._settings_page)
            app.router.add_post("/save", self._save)
            app.router.add_get("/moderation", self._moderation_page)
            app.router.add_post("/mod/ban", self._mod_ban)
            app.router.add_post("/mod/kick", self._mod_kick)
            app.router.add_post("/mod/timeout", self._mod_timeout)
            app.router.add_post("/mod/untimeout", self._mod_untimeout)
            app.router.add_post("/mod/unban", self._mod_unban)
            app.router.add_post("/mod/warn", self._mod_warn)
            app.router.add_post("/mod/clearwarns", self._mod_clearwarns)
            app.router.add_post("/mod/channel", self._mod_channel)
            app.router.add_post("/mod/purge", self._mod_purge)
            app.router.add_post("/mod/nick", self._mod_nick)
            app.router.add_get("/login", self._login_page)
            app.router.add_post("/login", self._login_submit)
            app.router.add_get("/logout", self._logout)
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
        return web.Response(text=LOGIN_HTML.replace("__STYLE__", STYLE).replace("__ERR__", ""),
                            content_type="text/html")

    async def _login_submit(self, request):
        if not self.password:
            return web.Response(text=DISABLED_HTML, content_type="text/html")
        data = await request.post()
        if hmac.compare_digest(str(data.get("password", "")), self.password):
            resp = web.HTTPFound("/")
            resp.set_cookie(COOKIE, self.auth_token, httponly=True, samesite="Lax", max_age=7 * 86400)
            return resp
        return web.Response(text=LOGIN_HTML.replace("__STYLE__", STYLE).replace("__ERR__", "Wrong password"),
                            content_type="text/html")

    async def _logout(self, request):
        resp = web.HTTPFound("/login")
        resp.del_cookie(COOKIE)
        return resp

    # ── shared rendering ──────────────────────────────────────────────────────
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

    def _nav(self, active):
        items = [("/", "Settings", "settings"), ("/moderation", "Moderation", "moderation")]
        links = "".join(
            f'<a class="navlink{" active" if key == active else ""}" href="{href}">{label}</a>'
            for href, label, key in items
        )
        return f'<div class="nav">{links}<a class="navlink logout" href="/logout">Log out</a></div>'

    def _flash(self, request):
        if request.query.get("ok"):
            return f'<div class="flash ok">✅ {html.escape(request.query["ok"])}</div>'
        if request.query.get("err"):
            return f'<div class="flash err">⚠️ {html.escape(request.query["err"])}</div>'
        return ""

    def _page(self, active, guild, body, flash=""):
        s = self._stats()
        return (PAGE_SHELL
                .replace("__STYLE__", STYLE)
                .replace("__AVATAR__", s["avatar"])
                .replace("__NAME__", html.escape(s["name"]))
                .replace("__DOT__", "on" if s["online"] else "off")
                .replace("__STATUS__", "Online" if s["online"] else "Connecting…")
                .replace("__GUILD__", html.escape(guild.name))
                .replace("__NAV__", self._nav(active))
                .replace("__FLASH__", flash)
                .replace("__BODY__", body))

    @staticmethod
    def _opts(items, current, include_none=True):
        out = ['<option value="">— none —</option>'] if include_none else []
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
        def render(channels):
            return "".join(f'<div class="ch">{self._channel_icon(c)} {html.escape(c.name)}</div>'
                           for c in sorted(channels, key=lambda c: c.position))
        parts = []
        uncategorized = [c for c in guild.channels
                         if c.category is None and not isinstance(c, discord.CategoryChannel)]
        if uncategorized:
            parts.append('<div class="cat">📂 No category</div>' + render(uncategorized))
        for category in guild.categories:
            parts.append(f'<div class="cat">📁 {html.escape(category.name)}</div>' + render(category.channels))
        return "".join(parts) or '<div class="muted">No channels found.</div>'

    # ── settings page ─────────────────────────────────────────────────────────
    def _settings_body(self, guild):
        cfg = load_config().get(str(guild.id), {})
        ar, an = cfg.get("antiraid", {}), cfg.get("antinuke", {})
        channels = [(c.id, "#" + c.name) for c in guild.text_channels]
        roles = [(r.id, r.name) for r in sorted(guild.roles, key=lambda r: r.position, reverse=True)
                 if not r.is_default() and not r.managed]
        s = self._stats()
        role_field = lambda label, key: f'<div><label>{label}</label><select name="{key}">{self._opts(roles, cfg.get(key))}</select></div>'
        return f"""
    <div class="grid">
      <div class="stat"><div class="num">{s['servers']}</div><div class="lbl">Servers</div></div>
      <div class="stat"><div class="num">{s['members']:,}</div><div class="lbl">Members</div></div>
      <div class="stat"><div class="num">{s['commands']}</div><div class="lbl">Commands</div></div>
      <div class="stat"><div class="num">{s['uptime']}</div><div class="lbl">Uptime</div></div>
    </div>
    <div class="panel"><h2>🗂️ Channels &amp; Categories</h2>
      <div class="chcount">{len(guild.categories)} categories · {len(guild.channels) - len(guild.categories)} channels</div>
      <div class="chwrap">{self._channel_tree(guild)}</div></div>
    <form method="post" action="/save">
      <div class="panel"><h2>📥 Channels</h2><div class="row">
        <div><label>Submissions channel</label><select name="submissions_channel">{self._opts(channels, cfg.get('submissions_channel'))}</select></div>
        <div><label>Log channel</label><select name="log_channel">{self._opts(channels, cfg.get('log_channel'))}</select></div>
      </div></div>
      <div class="panel"><h2>🎭 Roles</h2><div class="row">
        {role_field('Verify role', 'verify_role')}{role_field('Submission role', 'submission_role')}
        {role_field('Booster role', 'booster_role')}{role_field('Mod role', 'mod_role')}
        {role_field('Admin role', 'admin_role')}{role_field('Owner role', 'owner_role')}
      </div></div>
      <div class="panel"><h2>🛡️ Anti-raid</h2>
        <div class="toggle"><input type="checkbox" name="ar_enabled" id="ar" {'checked' if ar.get('enabled') else ''}><label for="ar">Enabled</label></div>
        <div class="row">
          <div><label>Joins threshold</label><input type="number" name="ar_threshold" min="2" value="{ar.get('threshold', 5)}"></div>
          <div><label>Window (seconds)</label><input type="number" name="ar_window" min="2" value="{ar.get('window', 10)}"></div>
          <div><label>Action</label><select name="ar_action"><option value="kick" {'selected' if ar.get('action', 'kick') == 'kick' else ''}>Kick</option><option value="ban" {'selected' if ar.get('action') == 'ban' else ''}>Ban</option></select></div>
        </div></div>
      <div class="panel"><h2>💣 Anti-nuke</h2>
        <div class="toggle"><input type="checkbox" name="an_enabled" id="an" {'checked' if an.get('enabled') else ''}><label for="an">Enabled</label></div>
        <div class="row">
          <div><label>Actions threshold</label><input type="number" name="an_threshold" min="2" value="{an.get('threshold', 3)}"></div>
          <div><label>Window (seconds)</label><input type="number" name="an_window" min="5" value="{an.get('window', 30)}"></div>
        </div></div>
      <button class="save" type="submit">💾 Save changes</button>
    </form>"""

    async def _settings_page(self, request):
        guild = self._guild()
        if guild is None:
            return web.Response(text="<h1>Bot isn't connected to a server yet.</h1>", content_type="text/html")
        flash = '<div class="flash ok">✅ Settings saved.</div>' if request.query.get("saved") else self._flash(request)
        return web.Response(text=self._page("settings", guild, self._settings_body(guild), flash),
                            content_type="text/html")

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

    # ── moderation page ───────────────────────────────────────────────────────
    def _moderation_body(self, guild):
        mod = self.bot.get_cog("Moderation")
        channels = [(c.id, "#" + c.name) for c in guild.text_channels]
        chan_opts = self._opts(channels, None, include_none=False)
        members = sorted(guild.members, key=lambda m: m.display_name.lower())[:1000]
        member_opts = "".join(f'<option value="{m.id}">{html.escape(m.display_name)} ({m.id})</option>' for m in members)

        rows = ""
        for w in (mod.warnings_summary(guild) if mod else []):
            name = html.escape(w["name"]) if w["name"] else '<span class="muted">left server</span>'
            rows += (f'<tr><td>{w["id"]}</td><td>{name}</td><td>{w["count"]}</td>'
                     f'<td class="muted">{html.escape(w["last"])}</td>'
                     f'<td><form method="post" action="/mod/clearwarns"><input type="hidden" name="user_id" value="{w["id"]}">'
                     f'<button class="btn grey sm">Clear</button></form></td></tr>')
        if not rows:
            rows = '<tr><td colspan="5" class="muted">No warnings on record.</td></tr>'

        return f"""
    <div class="panel"><h2>👤 Member Actions</h2><div class="modgrid">
      <div class="mini"><h3>🔨 Ban</h3><form method="post" action="/mod/ban">
        <input type="text" name="user_id" placeholder="User ID or @mention" required>
        <input type="text" name="reason" placeholder="Reason (optional)">
        <button class="btn red">Ban</button></form></div>
      <div class="mini"><h3>👢 Kick</h3><form method="post" action="/mod/kick">
        <input type="text" name="user_id" placeholder="User ID or @mention" required>
        <input type="text" name="reason" placeholder="Reason (optional)">
        <button class="btn orange">Kick</button></form></div>
      <div class="mini"><h3>⏲️ Timeout</h3><form method="post" action="/mod/timeout">
        <input type="text" name="user_id" placeholder="User ID or @mention" required>
        <input type="text" name="duration" placeholder="10m / 1h / 2d" required>
        <input type="text" name="reason" placeholder="Reason (optional)">
        <button class="btn orange">Timeout</button></form></div>
      <div class="mini"><h3>✅ Remove Timeout</h3><form method="post" action="/mod/untimeout">
        <input type="text" name="user_id" placeholder="User ID or @mention" required>
        <input type="text" name="reason" placeholder="Reason (optional)">
        <button class="btn green">Remove Timeout</button></form></div>
      <div class="mini"><h3>♻️ Unban</h3><form method="post" action="/mod/unban">
        <input type="text" name="user_id" placeholder="User ID" required>
        <input type="text" name="reason" placeholder="Reason (optional)">
        <button class="btn green">Unban</button></form></div>
      <div class="mini"><h3>⚠️ Warn</h3><form method="post" action="/mod/warn">
        <input type="text" name="user_id" placeholder="User ID or @mention" required>
        <input type="text" name="reason" placeholder="Reason (optional)">
        <button class="btn yellow">Warn</button></form></div>
      <div class="mini"><h3>🧹 Clear Warnings</h3><form method="post" action="/mod/clearwarns">
        <input type="text" name="user_id" placeholder="User ID or @mention" required>
        <button class="btn grey">Clear Warnings</button></form></div>
    </div></div>

    <div class="panel"><h2>🔧 Channel Actions</h2><form method="post" action="/mod/channel">
      <label>Channel</label><select name="channel">{chan_opts}</select>
      <label>Slowmode (seconds, 0 = off)</label><input type="number" name="seconds" min="0" max="21600" value="0">
      <div class="btnrow">
        <button class="btn red" name="action" value="lock">Lock</button>
        <button class="btn green" name="action" value="unlock">Unlock</button>
        <button class="btn blue" name="action" value="slowmode">Set Slowmode</button>
      </div></form></div>

    <div class="panel"><h2>🧹 Purge Messages</h2><form method="post" action="/mod/purge">
      <label>Channel</label><select name="channel">{chan_opts}</select>
      <div class="row">
        <div><label>Amount (messages)</label><input type="number" name="amount" min="1" max="1000" value="100"></div>
        <div><label>Minutes (for time purge)</label><input type="number" name="minutes" min="1" max="1440" value="10"></div>
      </div>
      <label>User ID (for purge-by-user)</label><input type="text" name="user_id" placeholder="User ID or @mention">
      <div class="btnrow">
        <button class="btn red" name="action" value="amount">Purge N</button>
        <button class="btn orange" name="action" value="user">Purge by user</button>
        <button class="btn orange" name="action" value="time">Purge N minutes</button>
        <button class="btn grey" name="action" value="bot">Purge bot messages</button>
      </div></form></div>

    <div class="panel"><h2>✏️ Nickname</h2><form method="post" action="/mod/nick">
      <label>Member</label><select name="member">{member_opts}</select>
      <label>New nickname (leave blank to reset)</label><input type="text" name="nickname" placeholder="New nickname">
      <div class="btnrow">
        <button class="btn blue" name="action" value="set">Set Nickname</button>
        <button class="btn grey" name="action" value="reset">Reset</button>
      </div></form></div>

    <div class="panel"><h2>⚠️ Warnings</h2>
      <input class="search" id="warnsearch" type="text" placeholder="Search by user ID or name…" onkeyup="filterWarns()">
      <table class="warns" id="warnstable">
        <thead><tr><th>User ID</th><th>Username</th><th>Count</th><th>Last Reason</th><th></th></tr></thead>
        <tbody>{rows}</tbody></table></div>
    {SEARCH_JS}"""

    async def _moderation_page(self, request):
        guild = self._guild()
        if guild is None:
            return web.Response(text="<h1>Bot isn't connected to a server yet.</h1>", content_type="text/html")
        return web.Response(text=self._page("moderation", guild, self._moderation_body(guild), self._flash(request)),
                            content_type="text/html")

    # ── moderation action handlers (reuse cog helpers) ────────────────────────
    def _redirect(self, ok, msg):
        key = "ok" if ok else "err"
        clean = msg.replace("**", "").replace("`", "")
        raise web.HTTPFound("/moderation?" + urlencode({key: clean}))

    def _mod_cog(self):
        return self.bot.get_cog("Moderation")

    async def _mod_ban(self, request):
        guild, data = self._guild(), await request.post()
        uid = _parse_user_id(data.get("user_id"))
        if not guild or not uid:
            self._redirect(False, "Invalid user ID or mention.")
        ok, msg = await self._mod_cog().mod_ban(guild, uid, (data.get("reason") or "No reason provided").strip(), "Console")
        self._redirect(ok, msg)

    async def _mod_kick(self, request):
        guild, data = self._guild(), await request.post()
        uid = _parse_user_id(data.get("user_id"))
        if not guild or not uid:
            self._redirect(False, "Invalid user ID or mention.")
        ok, msg = await self._mod_cog().mod_kick(guild, uid, (data.get("reason") or "No reason provided").strip(), "Console")
        self._redirect(ok, msg)

    async def _mod_timeout(self, request):
        guild, data = self._guild(), await request.post()
        uid = _parse_user_id(data.get("user_id"))
        if not guild or not uid:
            self._redirect(False, "Invalid user ID or mention.")
        ok, msg = await self._mod_cog().mod_timeout(guild, uid, (data.get("duration") or "").strip(),
                                                    (data.get("reason") or "No reason provided").strip(), "Console")
        self._redirect(ok, msg)

    async def _mod_untimeout(self, request):
        guild, data = self._guild(), await request.post()
        uid = _parse_user_id(data.get("user_id"))
        if not guild or not uid:
            self._redirect(False, "Invalid user ID or mention.")
        ok, msg = await self._mod_cog().mod_untimeout(guild, uid, (data.get("reason") or "No reason provided").strip(), "Console")
        self._redirect(ok, msg)

    async def _mod_unban(self, request):
        guild, data = self._guild(), await request.post()
        uid = _parse_user_id(data.get("user_id"))
        if not guild or not uid:
            self._redirect(False, "Invalid user ID.")
        ok, msg = await self._mod_cog().mod_unban(guild, uid, (data.get("reason") or "No reason provided").strip(), "Console")
        self._redirect(ok, msg)

    async def _mod_warn(self, request):
        guild, data = self._guild(), await request.post()
        uid = _parse_user_id(data.get("user_id"))
        if not guild or not uid:
            self._redirect(False, "Invalid user ID or mention.")
        ok, msg = await self._mod_cog().mod_warn(guild, uid, (data.get("reason") or "No reason provided").strip(), "Console")
        self._redirect(ok, msg)

    async def _mod_clearwarns(self, request):
        guild, data = self._guild(), await request.post()
        uid = _parse_user_id(data.get("user_id"))
        if not guild or not uid:
            self._redirect(False, "Invalid user ID or mention.")
        ok, msg = await self._mod_cog().mod_clearwarns(guild, uid, "Console")
        self._redirect(ok, msg)

    async def _mod_channel(self, request):
        guild, data = self._guild(), await request.post()
        ch = guild.get_channel(_to_int(data.get("channel"), 0)) if guild else None
        if not ch:
            self._redirect(False, "Pick a channel.")
        mod, action = self._mod_cog(), data.get("action")
        if action == "lock":
            ok, msg = await mod.mod_lock(guild, ch, "Console", True)
        elif action == "unlock":
            ok, msg = await mod.mod_lock(guild, ch, "Console", False)
        elif action == "slowmode":
            ok, msg = await mod.mod_slowmode(ch, max(0, min(21600, _to_int(data.get("seconds"), 0))), "Console")
        else:
            ok, msg = False, "Unknown action."
        self._redirect(ok, msg)

    async def _mod_purge(self, request):
        guild, data = self._guild(), await request.post()
        ch = guild.get_channel(_to_int(data.get("channel"), 0)) if guild else None
        if not ch:
            self._redirect(False, "Pick a channel.")
        purge = self.bot.get_cog("Purge")
        action = data.get("action")
        amount = max(1, min(1000, _to_int(data.get("amount"), 100)))
        if action == "amount":
            ok, msg = await purge.purge_messages(ch, guild, label=f"last {amount} messages", limit=amount, moderator="Console")
        elif action == "bot":
            ok, msg = await purge.purge_messages(ch, guild, label=f"bot messages in last {amount}", limit=amount,
                                                 check=lambda m: m.author.bot, moderator="Console")
        elif action == "user":
            uid = _parse_user_id(data.get("user_id"))
            if not uid:
                self._redirect(False, "Enter a user ID for purge-by-user.")
            ok, msg = await purge.purge_messages(ch, guild, label=f"user {uid} in last {amount}", limit=amount,
                                                 check=lambda m: m.author.id == uid, moderator="Console")
        elif action == "time":
            minutes = max(1, min(1440, _to_int(data.get("minutes"), 10)))
            after = discord.utils.utcnow() - timedelta(minutes=minutes)
            ok, msg = await purge.purge_messages(ch, guild, label=f"last {minutes} min", limit=None, after=after, moderator="Console")
        else:
            ok, msg = False, "Unknown action."
        self._redirect(ok, msg)

    async def _mod_nick(self, request):
        guild, data = self._guild(), await request.post()
        uid = _parse_user_id(data.get("member"))
        if not guild or not uid:
            self._redirect(False, "Pick a member.")
        nickname = "" if data.get("action") == "reset" else (data.get("nickname") or "").strip()
        ok, msg = await self._mod_cog().mod_nick(guild, uid, nickname or None, "Console")
        self._redirect(ok, msg)

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
