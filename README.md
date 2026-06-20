# BearBot 🐻

A Discord bot for hosting **Geometry Dash collab events** (megacollabs, decorations, etc.), with a full set of moderation, verification, and server-protection tools baked in.

Built with [discord.py](https://discordpy.readthedocs.io/) 2.x using slash commands.

## Features

- 🎮 **Event signup** — `/eventjoin` DMs users a set of customizable questions and posts their answers to a submissions channel
- ✅ **Verification** — one-click button panel that grants a role
- 🔨 **Moderation** — ban, kick, warn (with history), and channel lock/unlock, all logged
- 🛡️ **Protection** — anti-raid (rapid-join detection) and anti-nuke (mass channel/role deletes & bans)
- 👮 **Role management** — create roles, an admin role, and assign Owner/Admin/Mod
- 🛠️ **One-shot setup** — `/setup` builds the recommended roles, category, and channels automatically
- ℹ️ **`/help`** — lists every command, generated live from the command tree

Run `/help` in your server for the full, always-current command list.

## Setup

1. **Install dependencies** (Python 3.10+):
   ```bash
   pip install -r requirements.txt
   ```

2. **Create a bot** at the [Discord Developer Portal](https://discord.com/developers/applications):
   - Under **Bot**, copy the token and enable **Server Members Intent** + **Message Content Intent**
   - Invite it to your server with the `applications.commands` and `bot` scopes (give it the permissions it needs — Manage Roles, Manage Channels, Ban/Kick Members, etc.)

3. **Configure environment** — copy `.env.example` to `.env` and fill it in:
   ```bash
   cp .env.example .env
   ```
   | Variable | Required | Description |
   |---|---|---|
   | `DISCORD_TOKEN` | ✅ | Your bot token |
   | `GUILD_ID` | optional | Server ID for instant slash-command updates (otherwise global, ~1h) |
   | `RENDER_EXTERNAL_URL` | optional | Public URL for the keep-alive self-ping (auto-set on Render) |

4. **Run it**:
   ```bash
   python main.py
   ```

5. In your server, run **`/setup`** to auto-create roles/channels, then **`/help`** to see everything.

## Hosting on Render

A [`render.yaml`](render.yaml) Blueprint is included — connect the repo as a **Blueprint** and Render sets up the Web Service (build/start commands, health check, env vars) automatically. You only need to fill in `DISCORD_TOKEN` in the **Environment** tab afterward (it's intentionally not stored in the repo).

Prefer manual setup? Create a **Web Service** (free tier) with:
- **Build command:** `pip install -r requirements.txt`
- **Start command:** `python main.py`
- Set `DISCORD_TOKEN` (and optionally `GUILD_ID`) in the **Environment** tab

The built-in keep-alive web server + self-ping loop keeps the service from spinning down. (For extra reliability, point an [UptimeRobot](https://uptimerobot.com/) monitor at your Render URL.)

> ⚠️ **Persistence note:** Render's free filesystem is ephemeral — `config.json` resets on every deploy/restart. Per-server settings (channels, roles, warns) won't persist across deploys. Use a [persistent disk](https://render.com/docs/disks) (paid) or an external database if you need them to stick.

## Project structure

```
main.py             # Entry point: bot setup, cog loading, command sync, keep-alive
config_store.py     # JSON config helpers + defaults
utils.py            # Shared helpers (logging, audit-log lookup)
cogs/
  events.py         # /eventjoin + event config
  moderation.py     # ban/kick/warn, lock/unlock, logging
  verification.py   # verify button + config
  protection.py     # anti-raid + anti-nuke
  server_setup.py   # /setup
  admin.py          # role creation/assignment, /botname
  help.py           # /help
  keepalive.py      # Render keep-alive web server + self-ping
```

Config is stored per-guild in `config.json` (auto-generated, gitignored). No database.

## License

MIT
