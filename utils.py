"""Shared helpers used across cogs."""
import discord

from config_store import load_config


async def send_log(guild, embed):
    """Post an embed to the guild's configured log channel, if any."""
    config = load_config()
    g = config.get(str(guild.id), {})
    channel_id = g.get("log_channel")
    if not channel_id:
        return
    channel = guild.get_channel(channel_id)
    if channel is None:
        return
    try:
        await channel.send(embed=embed)
    except discord.Forbidden:
        pass


async def get_audit_executor(guild, action):
    """Return the user who most recently performed an audit-log action, or None."""
    try:
        async for entry in guild.audit_logs(limit=1, action=action):
            return entry.user
    except (discord.Forbidden, discord.HTTPException):
        return None
    return None
