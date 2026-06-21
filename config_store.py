"""Shared config storage + constants for BearBot."""
import asyncio
import json
import os

import aiohttp

CONFIG_FILE = os.environ.get("CONFIG_PATH", "config.json")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

TIMEOUT = 12 * 3600  # 12 hours in seconds, for the /eventjoin DM flow

DEFAULT_QUESTIONS = [
    {"label": "Name", "prompt": "What is your GD or Discord name? *(This is for deco/part credit, not your real name)*"},
    {"label": "Gameplay Link", "prompt": "Do you have gameplay?\n- If **no**, just type `no`\n- If **yes**, paste a link to your **Streamable or YouTube** video"},
    {"label": "GMD File", "prompt": "Do you have a `.gmd` file with the gameplay in it? *(using GD Share mod on Geode)*\n- If **no**, just type `no`\n- If **yes**, paste a **GoFile, MediaFire, or GreenCloud** link"},
]

# In-memory cache — populated from Supabase on startup, persisted on every save
_config: dict = {}


def load_config() -> dict:
    return _config


def save_config(data: dict) -> None:
    global _config
    _config = data
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_push_to_supabase(data))
        except RuntimeError:
            pass
    else:
        with open(CONFIG_FILE, "w") as f:
            json.dump(data, f, indent=2)


def guild_config(config, guild_id) -> dict:
    """Return (and create) the config dict for a guild."""
    gid = str(guild_id)
    if gid not in config:
        config[gid] = {}
    return config[gid]


async def load_from_supabase() -> None:
    """Fetch config from Supabase into the in-memory cache. Called once at startup."""
    global _config
    if not (SUPABASE_URL and SUPABASE_KEY):
        # No Supabase configured — fall back to local JSON file
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                _config = json.load(f)
        print("⚠️  SUPABASE_URL/SUPABASE_KEY not set — using local config.json")
        return

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }
    url = f"{SUPABASE_URL}/rest/v1/bot_config?key=eq.config&select=value"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    rows = await resp.json()
                    if rows:
                        _config = rows[0]["value"]
                        print(f"✅ Loaded config from Supabase ({len(_config)} guild(s))")
                    else:
                        print("⚠️  bot_config row missing — starting fresh (run the SQL setup)")
                else:
                    text = await resp.text()
                    print(f"⚠️  Supabase load failed ({resp.status}): {text}")
    except Exception as e:
        print(f"⚠️  Supabase load error: {e}")


async def _push_to_supabase(data: dict) -> None:
    """Upsert the full config dict to Supabase."""
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }
    url = f"{SUPABASE_URL}/rest/v1/bot_config"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=[{"key": "config", "value": data}]) as resp:
                if resp.status not in (200, 201):
                    text = await resp.text()
                    print(f"⚠️  Supabase save failed ({resp.status}): {text}")
    except Exception as e:
        print(f"⚠️  Supabase save error: {e}")
