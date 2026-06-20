# GD Event Bot — Claude Code Instructions

## Project Overview
This is a Discord bot built in Python using **discord.py 2.x** for hosting Geometry Dash collab events (megacollabs, decorations, etc.). The bot DMs users 3 questions when they run `/eventjoin` and posts their answers as an embed to a configurable submissions channel.

## Stack
- **Language**: Python 3.10+
- **Library**: discord.py 2.x (slash commands via `app_commands`)
- **Config storage**: `config.json` (local JSON file, one entry per guild)
- **No database** — keep it simple with JSON unless told otherwise

## File Structure
```
bot/
├── main.py             # Entry point: bot subclass, intents, loads cogs, global error handler
├── config_store.py     # load_config/save_config/guild_config + DEFAULT_QUESTIONS + TIMEOUT
├── utils.py            # send_log() + get_audit_executor() shared helpers
├── cogs/
│   ├── events.py       # /eventjoin, /setchannel, custom questions, submission role
│   ├── moderation.py   # /setlog, ban/kick/warn/warnings/clearwarns, join/leave logging
│   ├── verification.py # VerifyView (persistent button), /setverify, /verifypanel
│   ├── protection.py   # /antiraid, /antinuke, anti-raid + anti-nuke listeners
│   └── server_setup.py # /setup — auto-creates roles/category/channels + wires config
├── requirements.txt    # discord.py>=2.3.0
├── config.json         # Auto-generated, per-guild settings
└── CLAUDE.md           # This file
```

## Current Features
**Events**
- `/eventjoin` — DM flow asking the configured questions, posts an embed to the submissions channel
- `/setchannel #channel` — set the submissions channel (Manage Server)
- `/setquestions` / `/viewquestions` / `/resetquestions` — customize event questions (up to 5, `Label | prompt` format, modal-based)
- `/setsubmissionrole @role` — grant a role when a user completes a submission
- 12-hour DM timeout, duplicate-session prevention, green embed with author icon + user ID footer

**Moderation & logging**
- `/setlog #channel` — set the log channel
- `/ban` `/kick` `/warn` `/warnings` `/clearwarns` — all logged; warns stored per-guild in config.json
- Member join/leave logging to the log channel

**Verification**
- `/setverify @role` + `/verifypanel` — persistent button panel that grants a role on click

**Protection**
- `/antiraid` — auto kick/ban on rapid joins (configurable threshold/window)
- `/antinuke` + `/antinuke_whitelist` — audit-log watch on mass channel/role deletes & bans, quarantines the culprit (strips roles)

**Setup**
- `/setup` — one-shot: creates Verified + Event Participant roles, a "GD EVENTS" category with event-info/eventjoin/submissions/bot-logs/verify channels, wires the config, and posts the verify panel (idempotent)

## The 3 Event Questions
1. **Name** — GD or Discord name for deco/part credit (not real name)
2. **Gameplay Link** — Streamable or YouTube link, or "no"
3. **GMD File** — GoFile, MediaFire, or GreenCloud link to `.gmd` file (GD Share mod on Geode), or "no"

## Embed Format
```
📋 New Event Submission
Author: DisplayName (user#tag) [avatar]

1. Name        | {answer}
2. Gameplay Link | {answer}
3. GMD File    | {answer}

Footer: User ID: {id}   Timestamp: utcnow
```

## Coding Conventions
- Use `app_commands` (slash commands) for everything, no prefix commands unless asked
- Logic lives in cogs under `cogs/`; each feature area is its own cog. New cogs go in `EXTENSIONS` in `main.py`
- Config is loaded/saved via `load_config()` / `save_config()` / `guild_config()` in `config_store.py`
- Shared helpers (`send_log`, `get_audit_executor`) live in `utils.py`
- In-memory state lives on the cog instance (e.g. `self.active_sessions`, `self.recent_joins`)
- Bot token loaded from `DISCORD_TOKEN` environment variable — never hardcode it
- Use `ephemeral=True` for all user-facing error/status messages
- Always handle `discord.Forbidden` when DMing users
- Command tree is synced once in `BearBot.setup_hook()` after loading all cogs

## Environment
- Run with: `python main.py`
- Token set via env var: `DISCORD_TOKEN=your_token_here python main.py`
- Install deps: `pip install -r requirements.txt`

## Planned Features (not built yet)
- Timeout/mute command + warn-threshold auto-actions
- Message edit/delete logging
- Per-event reset (clear submissions between events)
- Reaction-role panels

## Important Notes
- This bot is for GD (Geometry Dash) collab events — keep that context in mind
- The owner goes by BearLoGT / Miles, uses they/them pronouns
- Preferred style: full file contents over snippets, casual tone, no fluff
- When adding features, keep it clean and don't break existing slash commands
- Always sync the command tree after adding new slash commands (`await tree.sync()`)
