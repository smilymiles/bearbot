"""Moderation: ban/kick/warn/timeout/unban + slowmode, nick, logging, and channel lock."""
import re
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta

from config_store import load_config, save_config, guild_config
from utils import send_log

_DURATION_RE = re.compile(r"(\d+)\s*([smhd])", re.IGNORECASE)
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(text):
    """Parse a duration like '10m', '1h30m', '2d' into a timedelta. None if nothing valid."""
    matches = _DURATION_RE.findall(text or "")
    if not matches:
        return None
    seconds = sum(int(value) * _UNIT_SECONDS[unit.lower()] for value, unit in matches)
    return timedelta(seconds=seconds) if seconds > 0 else None


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setlog", description="Set the channel where moderation & member logs are posted")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(channel="The channel to send logs to")
    async def setlog(self, interaction: discord.Interaction, channel: discord.TextChannel):
        config = load_config()
        guild_config(config, interaction.guild.id)["log_channel"] = channel.id
        save_config(config)
        await interaction.response.send_message(
            f"✅ Log channel set to {channel.mention}!", ephemeral=True
        )

    @app_commands.command(name="ban", description="Ban a member from the server")
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.checks.bot_has_permissions(ban_members=True)
    @app_commands.describe(member="The member to ban", reason="Reason for the ban")
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message(
                "❌ You can't ban someone with a role equal to or higher than yours.", ephemeral=True
            )
            return
        try:
            await member.send(f"You were banned from **{interaction.guild.name}**.\nReason: {reason}")
        except discord.Forbidden:
            pass
        try:
            await member.ban(reason=f"{interaction.user}: {reason}")
        except discord.Forbidden:
            await interaction.response.send_message("❌ I can't ban that member (role too high?).", ephemeral=True)
            return
        await interaction.response.send_message(f"🔨 Banned **{member}**.\nReason: {reason}", ephemeral=True)
        embed = discord.Embed(title="🔨 Member Banned", color=0xE74C3C, timestamp=datetime.utcnow())
        embed.add_field(name="Member", value=f"{member} ({member.id})", inline=False)
        embed.add_field(name="Moderator", value=str(interaction.user), inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        await send_log(interaction.guild, embed)

    @app_commands.command(name="kick", description="Kick a member from the server")
    @app_commands.checks.has_permissions(kick_members=True)
    @app_commands.checks.bot_has_permissions(kick_members=True)
    @app_commands.describe(member="The member to kick", reason="Reason for the kick")
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message(
                "❌ You can't kick someone with a role equal to or higher than yours.", ephemeral=True
            )
            return
        try:
            await member.send(f"You were kicked from **{interaction.guild.name}**.\nReason: {reason}")
        except discord.Forbidden:
            pass
        try:
            await member.kick(reason=f"{interaction.user}: {reason}")
        except discord.Forbidden:
            await interaction.response.send_message("❌ I can't kick that member (role too high?).", ephemeral=True)
            return
        await interaction.response.send_message(f"👢 Kicked **{member}**.\nReason: {reason}", ephemeral=True)
        embed = discord.Embed(title="👢 Member Kicked", color=0xE67E22, timestamp=datetime.utcnow())
        embed.add_field(name="Member", value=f"{member} ({member.id})", inline=False)
        embed.add_field(name="Moderator", value=str(interaction.user), inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        await send_log(interaction.guild, embed)

    @app_commands.command(name="warn", description="Warn a member")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(member="The member to warn", reason="Reason for the warning")
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        if member.bot:
            await interaction.response.send_message("❌ You can't warn a bot.", ephemeral=True)
            return
        config = load_config()
        g = guild_config(config, interaction.guild.id)
        warns = g.setdefault("warns", {})
        user_warns = warns.setdefault(str(member.id), [])
        user_warns.append({
            "reason": reason,
            "mod": str(interaction.user),
            "mod_id": interaction.user.id,
            "time": datetime.utcnow().isoformat(),
        })
        save_config(config)
        count = len(user_warns)
        try:
            await member.send(
                f"⚠️ You were warned in **{interaction.guild.name}**.\nReason: {reason}\nYou now have **{count}** warning(s)."
            )
        except discord.Forbidden:
            pass
        await interaction.response.send_message(
            f"⚠️ Warned **{member}** (now {count} warning(s)).\nReason: {reason}", ephemeral=True
        )
        embed = discord.Embed(title="⚠️ Member Warned", color=0xF1C40F, timestamp=datetime.utcnow())
        embed.add_field(name="Member", value=f"{member} ({member.id})", inline=False)
        embed.add_field(name="Moderator", value=str(interaction.user), inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Total Warnings", value=str(count), inline=False)
        await send_log(interaction.guild, embed)

    @app_commands.command(name="warnings", description="View a member's warnings")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(member="The member whose warnings to view")
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        config = load_config()
        g = config.get(str(interaction.guild.id), {})
        user_warns = g.get("warns", {}).get(str(member.id), [])
        if not user_warns:
            await interaction.response.send_message(f"✅ **{member}** has no warnings.", ephemeral=True)
            return
        embed = discord.Embed(
            title=f"⚠️ Warnings for {member}",
            color=0xF1C40F,
            description=f"Total: **{len(user_warns)}**",
        )
        for i, w in enumerate(user_warns, 1):
            ts = w.get("time", "")[:19].replace("T", " ")
            embed.add_field(
                name=f"#{i} — by {w.get('mod', 'unknown')} ({ts} UTC)",
                value=w.get("reason", "No reason"),
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="clearwarns", description="Clear all warnings for a member")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(member="The member whose warnings to clear")
    async def clearwarns(self, interaction: discord.Interaction, member: discord.Member):
        config = load_config()
        g = guild_config(config, interaction.guild.id)
        warns = g.get("warns", {})
        if str(member.id) not in warns or not warns[str(member.id)]:
            await interaction.response.send_message(f"✅ **{member}** has no warnings to clear.", ephemeral=True)
            return
        cleared = len(warns[str(member.id)])
        warns[str(member.id)] = []
        save_config(config)
        await interaction.response.send_message(f"🧹 Cleared {cleared} warning(s) for **{member}**.", ephemeral=True)
        embed = discord.Embed(title="🧹 Warnings Cleared", color=0x95A5A6, timestamp=datetime.utcnow())
        embed.add_field(name="Member", value=f"{member} ({member.id})", inline=False)
        embed.add_field(name="Moderator", value=str(interaction.user), inline=False)
        embed.add_field(name="Cleared", value=str(cleared), inline=False)
        await send_log(interaction.guild, embed)

    @app_commands.command(name="timeout", description="Timeout (mute) a member for a duration like 10m, 1h, 2d")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.checks.bot_has_permissions(moderate_members=True)
    @app_commands.describe(member="The member to time out", duration="How long: 30s, 10m, 1h, 2d (max 28d)", reason="Reason")
    async def timeout(self, interaction: discord.Interaction, member: discord.Member,
                      duration: str, reason: str = "No reason provided"):
        if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message(
                "❌ You can't time out someone with a role equal to or higher than yours.", ephemeral=True
            )
            return
        delta = parse_duration(duration)
        if delta is None:
            await interaction.response.send_message(
                "❌ Invalid duration. Use something like `30s`, `10m`, `1h`, or `2d`.", ephemeral=True
            )
            return
        if delta > timedelta(days=28):
            await interaction.response.send_message("❌ Timeouts can be at most **28 days**.", ephemeral=True)
            return
        try:
            await member.timeout(delta, reason=f"{interaction.user}: {reason}")
        except discord.Forbidden:
            await interaction.response.send_message("❌ I can't time out that member (role too high?).", ephemeral=True)
            return
        await interaction.response.send_message(f"⏲️ Timed out **{member}** for `{duration}`.\nReason: {reason}", ephemeral=True)
        embed = discord.Embed(title="⏲️ Member Timed Out", color=0xE67E22, timestamp=datetime.utcnow())
        embed.add_field(name="Member", value=f"{member} ({member.id})", inline=False)
        embed.add_field(name="Moderator", value=str(interaction.user), inline=False)
        embed.add_field(name="Duration", value=duration, inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        await send_log(interaction.guild, embed)

    @app_commands.command(name="untimeout", description="Remove a member's timeout")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.checks.bot_has_permissions(moderate_members=True)
    @app_commands.describe(member="The member to un-timeout", reason="Reason")
    async def untimeout(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        if not member.is_timed_out():
            await interaction.response.send_message(f"ℹ️ **{member}** isn't timed out.", ephemeral=True)
            return
        try:
            await member.timeout(None, reason=f"{interaction.user}: {reason}")
        except discord.Forbidden:
            await interaction.response.send_message("❌ I can't edit that member (role too high?).", ephemeral=True)
            return
        await interaction.response.send_message(f"✅ Removed timeout from **{member}**.", ephemeral=True)
        embed = discord.Embed(title="✅ Timeout Removed", color=0x2ECC71, timestamp=datetime.utcnow())
        embed.add_field(name="Member", value=f"{member} ({member.id})", inline=False)
        embed.add_field(name="Moderator", value=str(interaction.user), inline=False)
        await send_log(interaction.guild, embed)

    @app_commands.command(name="unban", description="Unban a user by their ID")
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.checks.bot_has_permissions(ban_members=True)
    @app_commands.describe(user_id="The ID of the user to unban", reason="Reason")
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: str = "No reason provided"):
        if not user_id.isdigit():
            await interaction.response.send_message("❌ Give a numeric user ID.", ephemeral=True)
            return
        try:
            await interaction.guild.unban(discord.Object(id=int(user_id)), reason=f"{interaction.user}: {reason}")
        except discord.NotFound:
            await interaction.response.send_message("❌ That user isn't banned (or the ID is wrong).", ephemeral=True)
            return
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to unban.", ephemeral=True)
            return
        await interaction.response.send_message(f"✅ Unbanned `{user_id}`.", ephemeral=True)
        embed = discord.Embed(title="✅ Member Unbanned", color=0x2ECC71, timestamp=datetime.utcnow())
        embed.add_field(name="User ID", value=user_id, inline=False)
        embed.add_field(name="Moderator", value=str(interaction.user), inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        await send_log(interaction.guild, embed)

    @app_commands.command(name="slowmode", description="Set this channel's slowmode (0 to disable)")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.checks.bot_has_permissions(manage_channels=True)
    @app_commands.describe(seconds="Slowmode delay in seconds (0-21600)")
    async def slowmode(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600]):
        if not isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
            await interaction.response.send_message("❌ I can't set slowmode on this channel type.", ephemeral=True)
            return
        try:
            await interaction.channel.edit(slowmode_delay=seconds)
        except (discord.Forbidden, discord.HTTPException):
            await interaction.response.send_message("❌ I couldn't change slowmode here.", ephemeral=True)
            return
        if seconds == 0:
            await interaction.response.send_message("✅ Slowmode **disabled** for this channel.", ephemeral=True)
        else:
            await interaction.response.send_message(f"🐌 Slowmode set to **{seconds}s** for this channel.", ephemeral=True)

    @app_commands.command(name="nick", description="Change or reset a member's nickname")
    @app_commands.checks.has_permissions(manage_nicknames=True)
    @app_commands.checks.bot_has_permissions(manage_nicknames=True)
    @app_commands.describe(member="The member", nickname="New nickname (leave blank to reset)")
    async def nick(self, interaction: discord.Interaction, member: discord.Member, nickname: str = None):
        if nickname and len(nickname) > 32:
            await interaction.response.send_message("❌ Nicknames can be at most 32 characters.", ephemeral=True)
            return
        if member.top_role >= interaction.guild.me.top_role:
            await interaction.response.send_message("❌ That member's role is too high for me to edit.", ephemeral=True)
            return
        try:
            await member.edit(nick=nickname)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I couldn't change that member's nickname.", ephemeral=True)
            return
        if nickname:
            await interaction.response.send_message(f"✅ Set **{member}**'s nickname to **{nickname}**.", ephemeral=True)
        else:
            await interaction.response.send_message(f"✅ Reset **{member}**'s nickname.", ephemeral=True)

    @app_commands.command(name="lock", description="Lock this channel so @everyone and Verified members can't send messages")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    async def lock(self, interaction: discord.Interaction):
        await self._set_lock(interaction, locked=True)

    @app_commands.command(name="unlock", description="Unlock this channel so members can send messages again")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    async def unlock(self, interaction: discord.Interaction):
        await self._set_lock(interaction, locked=False)

    async def _set_lock(self, interaction, locked: bool):
        channel = interaction.channel
        guild = interaction.guild
        # @everyone plus the Verified role (so verified members can't bypass via a role allow)
        targets = [guild.default_role]
        verify_id = load_config().get(str(guild.id), {}).get("verify_role")
        verified = guild.get_role(verify_id) if verify_id else discord.utils.get(guild.roles, name="Verified")
        if verified:
            targets.append(verified)

        # locked -> deny sending; unlocked -> clear the override (None) back to default
        value = False if locked else None
        try:
            for target in targets:
                await channel.set_permissions(
                    target, send_messages=value, send_messages_in_threads=value,
                    add_reactions=value, reason=f"{'Locked' if locked else 'Unlocked'} by {interaction.user}",
                )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I couldn't edit this channel — I need **Manage Roles** permission here.", ephemeral=True
            )
            return

        if locked:
            text = "🔒 This channel has been **locked**. Members can no longer send messages."
        else:
            text = "🔓 This channel has been **unlocked**. Members can send messages again."
        await interaction.response.send_message(text, allowed_mentions=discord.AllowedMentions.none())
        embed = discord.Embed(
            title="🔒 Channel Locked" if locked else "🔓 Channel Unlocked",
            description=f"{channel.mention} by {interaction.user.mention}",
            color=0xE74C3C if locked else 0x2ECC71,
            timestamp=datetime.utcnow(),
        )
        await send_log(guild, embed)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        embed = discord.Embed(
            title="📥 Member Joined",
            description=f"{member.mention} (`{member}`)",
            color=0x2ECC71,
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="Account Created", value=member.created_at.strftime("%Y-%m-%d"), inline=False)
        embed.set_footer(text=f"User ID: {member.id} • Members: {member.guild.member_count}")
        await send_log(member.guild, embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        embed = discord.Embed(
            title="📤 Member Left",
            description=f"{member.mention} (`{member}`)",
            color=0x95A5A6,
            timestamp=datetime.utcnow(),
        )
        embed.set_footer(text=f"User ID: {member.id}")
        await send_log(member.guild, embed)


async def setup(bot):
    await bot.add_cog(Moderation(bot))
