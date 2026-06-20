"""Moderation: ban/kick/warn/timeout/unban + slowmode, nick, logging, and channel lock.

Core logic lives in the mod_* helper methods so both the slash commands AND the web
console can call the same code (each returns an (ok, message) tuple).
"""
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

    # ══════════════════════════════════════════════════════════════════════════
    # Core action helpers — return (ok: bool, message: str). Shared by slash + web.
    # `moderator` is a label string used in logs/audit reasons.
    # ══════════════════════════════════════════════════════════════════════════
    async def mod_ban(self, guild, user_id, reason, moderator):
        user_id = int(user_id)
        member = guild.get_member(user_id)
        if member:
            try:
                await member.send(f"You were banned from **{guild.name}**.\nReason: {reason}")
            except discord.Forbidden:
                pass
        try:
            await guild.ban(discord.Object(id=user_id), reason=f"{moderator}: {reason}")
        except discord.Forbidden:
            return False, "❌ I can't ban that user (role too high or missing perms)."
        except discord.HTTPException as e:
            return False, f"❌ Ban failed: {e}"
        await self._log(guild, "🔨 Member Banned", 0xE74C3C, member or user_id, moderator, reason=reason)
        return True, f"🔨 Banned **{member or user_id}**."

    async def mod_kick(self, guild, user_id, reason, moderator):
        member = guild.get_member(int(user_id))
        if member is None:
            return False, "❌ That user isn't in the server."
        try:
            await member.send(f"You were kicked from **{guild.name}**.\nReason: {reason}")
        except discord.Forbidden:
            pass
        try:
            await member.kick(reason=f"{moderator}: {reason}")
        except discord.Forbidden:
            return False, "❌ I can't kick that member (role too high?)."
        await self._log(guild, "👢 Member Kicked", 0xE67E22, member, moderator, reason=reason)
        return True, f"👢 Kicked **{member}**."

    async def mod_timeout(self, guild, user_id, duration_str, reason, moderator):
        member = guild.get_member(int(user_id))
        if member is None:
            return False, "❌ That user isn't in the server."
        delta = parse_duration(duration_str)
        if delta is None:
            return False, "❌ Invalid duration. Use something like `30s`, `10m`, `1h`, or `2d`."
        if delta > timedelta(days=28):
            return False, "❌ Timeouts can be at most **28 days**."
        try:
            await member.timeout(delta, reason=f"{moderator}: {reason}")
        except discord.Forbidden:
            return False, "❌ I can't time out that member (role too high?)."
        await self._log(guild, "⏲️ Member Timed Out", 0xE67E22, member, moderator, reason=reason,
                        extra=("Duration", duration_str))
        return True, f"⏲️ Timed out **{member}** for `{duration_str}`."

    async def mod_untimeout(self, guild, user_id, reason, moderator):
        member = guild.get_member(int(user_id))
        if member is None:
            return False, "❌ That user isn't in the server."
        if not member.is_timed_out():
            return False, f"ℹ️ **{member}** isn't timed out."
        try:
            await member.timeout(None, reason=f"{moderator}: {reason}")
        except discord.Forbidden:
            return False, "❌ I can't edit that member (role too high?)."
        await self._log(guild, "✅ Timeout Removed", 0x2ECC71, member, moderator)
        return True, f"✅ Removed timeout from **{member}**."

    async def mod_unban(self, guild, user_id, reason, moderator):
        try:
            await guild.unban(discord.Object(id=int(user_id)), reason=f"{moderator}: {reason}")
        except discord.NotFound:
            return False, "❌ That user isn't banned (or the ID is wrong)."
        except discord.Forbidden:
            return False, "❌ I don't have permission to unban."
        await self._log(guild, "✅ Member Unbanned", 0x2ECC71, int(user_id), moderator, reason=reason)
        return True, f"✅ Unbanned `{user_id}`."

    async def mod_warn(self, guild, user_id, reason, moderator):
        user_id = int(user_id)
        member = guild.get_member(user_id)
        if member and member.bot:
            return False, "❌ You can't warn a bot."
        config = load_config()
        g = guild_config(config, guild.id)
        user_warns = g.setdefault("warns", {}).setdefault(str(user_id), [])
        user_warns.append({"reason": reason, "mod": moderator, "time": datetime.utcnow().isoformat()})
        save_config(config)
        count = len(user_warns)
        if member:
            try:
                await member.send(f"⚠️ You were warned in **{guild.name}**.\nReason: {reason}\n"
                                  f"You now have **{count}** warning(s).")
            except discord.Forbidden:
                pass
        await self._log(guild, "⚠️ Member Warned", 0xF1C40F, member or user_id, moderator, reason=reason,
                        extra=("Total Warnings", str(count)))
        return True, f"⚠️ Warned **{member or user_id}** (now {count} warning(s))."

    async def mod_clearwarns(self, guild, user_id, moderator):
        config = load_config()
        g = guild_config(config, guild.id)
        warns = g.get("warns", {})
        existing = warns.get(str(user_id))
        if not existing:
            return False, "ℹ️ That user has no warnings to clear."
        cleared = len(existing)
        warns[str(user_id)] = []
        save_config(config)
        await self._log(guild, "🧹 Warnings Cleared", 0x95A5A6, int(user_id), moderator,
                        extra=("Cleared", str(cleared)))
        return True, f"🧹 Cleared {cleared} warning(s)."

    async def mod_nick(self, guild, user_id, nickname, moderator):
        member = guild.get_member(int(user_id))
        if member is None:
            return False, "❌ That user isn't in the server."
        if nickname and len(nickname) > 32:
            return False, "❌ Nicknames can be at most 32 characters."
        if member.top_role >= guild.me.top_role:
            return False, "❌ That member's role is too high for me to edit."
        try:
            await member.edit(nick=nickname or None, reason=f"Nick change by {moderator}")
        except discord.Forbidden:
            return False, "❌ I couldn't change that member's nickname."
        if nickname:
            return True, f"✅ Set **{member}**'s nickname to **{nickname}**."
        return True, f"✅ Reset **{member}**'s nickname."

    async def mod_slowmode(self, channel, seconds, moderator):
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return False, "❌ I can't set slowmode on this channel type."
        try:
            await channel.edit(slowmode_delay=seconds, reason=f"Slowmode by {moderator}")
        except (discord.Forbidden, discord.HTTPException):
            return False, "❌ I couldn't change slowmode here."
        if seconds == 0:
            return True, f"✅ Slowmode **disabled** for {channel.mention}."
        return True, f"🐌 Slowmode set to **{seconds}s** for {channel.mention}."

    async def mod_lock(self, guild, channel, moderator, locked):
        if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
            return False, "❌ I can't lock this channel type."
        targets = [guild.default_role]
        verify_id = load_config().get(str(guild.id), {}).get("verify_role")
        verified = guild.get_role(verify_id) if verify_id else discord.utils.get(guild.roles, name="Verified")
        if verified:
            targets.append(verified)
        value = False if locked else None
        try:
            for target in targets:
                await channel.set_permissions(
                    target, send_messages=value, send_messages_in_threads=value,
                    add_reactions=value, reason=f"{'Locked' if locked else 'Unlocked'} by {moderator}",
                )
        except discord.Forbidden:
            return False, "❌ I couldn't edit this channel — I need **Manage Roles** here."
        notice = ("🔒 This channel has been **locked**. Members can no longer send messages."
                  if locked else "🔓 This channel has been **unlocked**. Members can send messages again.")
        try:
            await channel.send(notice, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass
        embed = discord.Embed(
            title="🔒 Channel Locked" if locked else "🔓 Channel Unlocked",
            description=f"{channel.mention} by {moderator}",
            color=0xE74C3C if locked else 0x2ECC71, timestamp=datetime.utcnow(),
        )
        await send_log(guild, embed)
        return True, (f"🔒 Locked {channel.mention}." if locked else f"🔓 Unlocked {channel.mention}.")

    def warnings_summary(self, guild):
        """List every warned user for the console table: id, name, count, last reason."""
        g = load_config().get(str(guild.id), {})
        rows = []
        for uid, entries in g.get("warns", {}).items():
            if not entries:
                continue
            member = guild.get_member(int(uid))
            rows.append({
                "id": uid,
                "name": str(member) if member else None,
                "count": len(entries),
                "last": entries[-1].get("reason", ""),
            })
        return rows

    async def _log(self, guild, title, color, target, moderator, reason=None, extra=None):
        embed = discord.Embed(title=title, color=color, timestamp=datetime.utcnow())
        label = f"{target} ({target.id})" if isinstance(target, (discord.Member, discord.User)) else str(target)
        embed.add_field(name="Member", value=label, inline=False)
        embed.add_field(name="Moderator", value=str(moderator), inline=False)
        if reason is not None:
            embed.add_field(name="Reason", value=reason, inline=False)
        if extra is not None:
            embed.add_field(name=extra[0], value=extra[1], inline=False)
        await send_log(guild, embed)

    # ══════════════════════════════════════════════════════════════════════════
    # Slash commands — permission checks + invoker hierarchy, then call the helper.
    # ══════════════════════════════════════════════════════════════════════════
    @app_commands.command(name="setlog", description="Set the channel where moderation & member logs are posted")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(channel="The channel to send logs to")
    async def setlog(self, interaction: discord.Interaction, channel: discord.TextChannel):
        config = load_config()
        guild_config(config, interaction.guild.id)["log_channel"] = channel.id
        save_config(config)
        await interaction.response.send_message(f"✅ Log channel set to {channel.mention}!", ephemeral=True)

    def _outranks(self, interaction, member):
        return member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id

    @app_commands.command(name="ban", description="Ban a member from the server")
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.checks.bot_has_permissions(ban_members=True)
    @app_commands.describe(member="The member to ban", reason="Reason for the ban")
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        if self._outranks(interaction, member):
            await interaction.response.send_message("❌ You can't ban someone with a role equal to or higher than yours.", ephemeral=True)
            return
        ok, msg = await self.mod_ban(interaction.guild, member.id, reason, str(interaction.user))
        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="kick", description="Kick a member from the server")
    @app_commands.checks.has_permissions(kick_members=True)
    @app_commands.checks.bot_has_permissions(kick_members=True)
    @app_commands.describe(member="The member to kick", reason="Reason for the kick")
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        if self._outranks(interaction, member):
            await interaction.response.send_message("❌ You can't kick someone with a role equal to or higher than yours.", ephemeral=True)
            return
        ok, msg = await self.mod_kick(interaction.guild, member.id, reason, str(interaction.user))
        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="warn", description="Warn a member")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(member="The member to warn", reason="Reason for the warning")
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        ok, msg = await self.mod_warn(interaction.guild, member.id, reason, str(interaction.user))
        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="warnings", description="View a member's warnings")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(member="The member whose warnings to view")
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        user_warns = load_config().get(str(interaction.guild.id), {}).get("warns", {}).get(str(member.id), [])
        if not user_warns:
            await interaction.response.send_message(f"✅ **{member}** has no warnings.", ephemeral=True)
            return
        embed = discord.Embed(title=f"⚠️ Warnings for {member}", color=0xF1C40F, description=f"Total: **{len(user_warns)}**")
        for i, w in enumerate(user_warns, 1):
            ts = w.get("time", "")[:19].replace("T", " ")
            embed.add_field(name=f"#{i} — by {w.get('mod', 'unknown')} ({ts} UTC)", value=w.get("reason", "No reason"), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="clearwarns", description="Clear all warnings for a member")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(member="The member whose warnings to clear")
    async def clearwarns(self, interaction: discord.Interaction, member: discord.Member):
        ok, msg = await self.mod_clearwarns(interaction.guild, member.id, str(interaction.user))
        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="timeout", description="Timeout (mute) a member for a duration like 10m, 1h, 2d")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.checks.bot_has_permissions(moderate_members=True)
    @app_commands.describe(member="The member to time out", duration="How long: 30s, 10m, 1h, 2d (max 28d)", reason="Reason")
    async def timeout(self, interaction: discord.Interaction, member: discord.Member, duration: str, reason: str = "No reason provided"):
        if self._outranks(interaction, member):
            await interaction.response.send_message("❌ You can't time out someone with a role equal to or higher than yours.", ephemeral=True)
            return
        ok, msg = await self.mod_timeout(interaction.guild, member.id, duration, reason, str(interaction.user))
        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="untimeout", description="Remove a member's timeout")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.checks.bot_has_permissions(moderate_members=True)
    @app_commands.describe(member="The member to un-timeout", reason="Reason")
    async def untimeout(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        ok, msg = await self.mod_untimeout(interaction.guild, member.id, reason, str(interaction.user))
        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="unban", description="Unban a user by their ID")
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.checks.bot_has_permissions(ban_members=True)
    @app_commands.describe(user_id="The ID of the user to unban", reason="Reason")
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: str = "No reason provided"):
        if not user_id.isdigit():
            await interaction.response.send_message("❌ Give a numeric user ID.", ephemeral=True)
            return
        ok, msg = await self.mod_unban(interaction.guild, int(user_id), reason, str(interaction.user))
        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="slowmode", description="Set this channel's slowmode (0 to disable)")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.checks.bot_has_permissions(manage_channels=True)
    @app_commands.describe(seconds="Slowmode delay in seconds (0-21600)")
    async def slowmode(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600]):
        ok, msg = await self.mod_slowmode(interaction.channel, seconds, str(interaction.user))
        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="nick", description="Change or reset a member's nickname")
    @app_commands.checks.has_permissions(manage_nicknames=True)
    @app_commands.checks.bot_has_permissions(manage_nicknames=True)
    @app_commands.describe(member="The member", nickname="New nickname (leave blank to reset)")
    async def nick(self, interaction: discord.Interaction, member: discord.Member, nickname: str = None):
        ok, msg = await self.mod_nick(interaction.guild, member.id, nickname, str(interaction.user))
        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="lock", description="Lock this channel so @everyone and Verified members can't send messages")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    async def lock(self, interaction: discord.Interaction):
        ok, msg = await self.mod_lock(interaction.guild, interaction.channel, str(interaction.user), True)
        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="unlock", description="Unlock this channel so members can send messages again")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    async def unlock(self, interaction: discord.Interaction):
        ok, msg = await self.mod_lock(interaction.guild, interaction.channel, str(interaction.user), False)
        await interaction.response.send_message(msg, ephemeral=True)

    # ── member join/leave logging ─────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_join(self, member):
        embed = discord.Embed(title="📥 Member Joined", description=f"{member.mention} (`{member}`)",
                              color=0x2ECC71, timestamp=datetime.utcnow())
        embed.add_field(name="Account Created", value=member.created_at.strftime("%Y-%m-%d"), inline=False)
        embed.set_footer(text=f"User ID: {member.id} • Members: {member.guild.member_count}")
        await send_log(member.guild, embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        embed = discord.Embed(title="📤 Member Left", description=f"{member.mention} (`{member}`)",
                              color=0x95A5A6, timestamp=datetime.utcnow())
        embed.set_footer(text=f"User ID: {member.id}")
        await send_log(member.guild, embed)


async def setup(bot):
    await bot.add_cog(Moderation(bot))
