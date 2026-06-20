"""Shared config storage + constants for BearBot."""
import json
import os

CONFIG_FILE = "config.json"
TIMEOUT = 12 * 3600  # 12 hours in seconds, for the /eventjoin DM flow

# Default event questions (used until an admin customizes them via /setquestions)
DEFAULT_QUESTIONS = [
    {"label": "Name", "prompt": "What is your GD or Discord name? *(This is for deco/part credit, not your real name)*"},
    {"label": "Gameplay Link", "prompt": "Do you have gameplay?\n- If **no**, just type `no`\n- If **yes**, paste a link to your **Streamable or YouTube** video"},
    {"label": "GMD File", "prompt": "Do you have a `.gmd` file with the gameplay in it? *(using GD Share mod on Geode)*\n- If **no**, just type `no`\n- If **yes**, paste a **GoFile, MediaFire, or GreenCloud** link"},
]


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}


def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)


def guild_config(config, guild_id):
    """Return (and create) the config dict for a guild."""
    gid = str(guild_id)
    if gid not in config:
        config[gid] = {}
    return config[gid]
