"""Protection: anti-raid (rapid joins) and anti-nuke (mass destructive actions)."""
import time
import discord
from discord import app_commands
from discord.ext import commands
from collections import defaultdict
from datetime import datetime

from config_store import load_config, save_config, guild_config
from utils import send_log, get_audit_executor


class Protection(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.recent_joins = defaultdict(list)                       # guild_id -> [join timestamps]
        self.raid_alert_cooldown = {}                               # guild_id -> last alert timestamp
        self.nuke_tracker = defaultdict(lambda: defaultdict(list))  # guild_id -> user_id -> [timestamps]

    # ── Anti-raid config ──────────────────────────────────────────────────────
    @app_commands.command(name="antiraid", description="Configure raid protection (auto-action on rapid joins)")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        enabled="Turn anti-raid on or off",
        joins="How many joins within the window triggers it (default 5)",
        seconds="The time window in seconds (default 10)",
        action="What to do to raiders: kick or ban (default kick)",
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="kick", value="kick"),
        app_commands.Choice(name="ban", value="ban"),
    ])
    async def antiraid(self, interaction: discord.Interaction, enabled: bool, joins: int = 5,
                       seconds: int = 10, action: app_commands.Choice[str] = None):
        config = load_config()
        g = guild_config(config, interaction.guild.id)
        g["antiraid"] = {
            "enabled": enabled,
            "threshold": max(2, joins),
            "window": max(2, seconds),
            "action": action.value if action else g.get("antiraid", {}).get("action", "kick"),
        }
        save_config(config)
        state = "ON" if enabled else "OFF"
        await interaction.response.send_message(
            f"🛡️ Anti-raid is now **{state}** — {g['antiraid']['action']} when **{g['antiraid']['threshold']}** "
            f"members join within **{g['antiraid']['window']}s**.",
            ephemeral=True,
        )

    # ── Anti-nuke config ──────────────────────────────────────────────────────
    @app_commands.command(name="antinuke", description="Configure nuke protection (auto-quarantine mass destructive actions)")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        enabled="Turn anti-nuke on or off",
        actions="How many destructive actions within the window triggers it (default 3)",
        seconds="The time window in seconds (default 30)",
    )
    async def antinuke(self, interaction: discord.Interaction, enabled: bool, actions: int = 3, seconds: int = 30):
        config = load_config()
        g = guild_config(config, interaction.guild.id)
        existing = g.get("antinuke", {})
        g["antinuke"] = {
            "enabled": enabled,
            "threshold": max(2, actions),
            "window": max(5, seconds),
            "whitelist": existing.get("whitelist", []),
        }
        save_config(config)
        state = "ON" if enabled else "OFF"
        await interaction.response.send_message(
            f"💣 Anti-nuke is now **{state}** — quarantines anyone (besides the owner, me, or whitelisted users) "
            f"who does **{g['antinuke']['threshold']}** destructive actions within **{g['antinuke']['window']}s**.\n"
            f"⚠️ I need **View Audit Log** + **Manage Roles** for this to work.",
            ephemeral=True,
        )

    @app_commands.command(name="antinuke_whitelist", description="Add or remove a user from the anti-nuke whitelist")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(member="The trusted member", remove="Set true to remove instead of add")
    async def antinuke_whitelist(self, interaction: discord.Interaction, member: discord.Member, remove: bool = False):
        config = load_config()
        g = guild_config(config, interaction.guild.id)
        an = g.setdefault("antinuke", {"enabled": False, "threshold": 3, "window": 30, "whitelist": []})
        wl = an.setdefault("whitelist", [])
        if remove:
            if member.id in wl:
                wl.remove(member.id)
                msg = f"➖ Removed **{member}** from the anti-nuke whitelist."
            else:
                msg = f"**{member}** wasn't on the whitelist."
        else:
            if member.id not in wl:
                wl.append(member.id)
            msg = f"➕ Added **{member}** to the anti-nuke whitelist."
        save_config(config)
        await interaction.response.send_message(msg, ephemeral=True)

    # ── Anti-nuke engine ──────────────────────────────────────────────────────
    async def handle_destructive(self, guild, action, label):
        """Attribute a destructive action and quarantine the culprit if over threshold."""
        config = load_config()
        g = config.get(str(guild.id), {})
        an = g.get("antinuke", {})
        if not an.get("enabled"):
            return
        executor = await get_audit_executor(guild, action)
        if executor is None:
            return
        if executor.id == self.bot.user.id or executor.id == guild.owner_id or executor.id in an.get("whitelist", []):
            return
        now = time.time()
        window = an.get("window", 30)
        times = [t for t in self.nuke_tracker[guild.id][executor.id] if now - t <= window]
        times.append(now)
        self.nuke_tracker[guild.id][executor.id] = times
        if len(times) < an.get("threshold", 3):
            return
        # Over threshold -> quarantine
        self.nuke_tracker[guild.id][executor.id] = []
        member = guild.get_member(executor.id)
        stripped = False
        if member is not None:
            # skip @everyone, managed (bot/integration/booster) roles, and anything above me
            removable = [r for r in member.roles
                         if r != guild.default_role and not r.managed and r < guild.me.top_role]
            if removable:
                try:
                    await member.remove_roles(*removable, reason="Anti-nuke: mass destructive actions")
                    stripped = True
                except (discord.Forbidden, discord.HTTPException):
                    pass
        embed = discord.Embed(
            title="💣 Anti-Nuke Triggered",
            color=0xE74C3C,
            timestamp=datetime.utcnow(),
            description=(
                f"**{executor}** (`{executor.id}`) exceeded the destructive-action limit "
                f"(last action: {label}).\n"
                + ("🔒 Their roles were stripped (quarantined)." if stripped
                   else "⚠️ I couldn't strip their roles — check my permissions / role position.")
            ),
        )
        await send_log(guild, embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        await self.handle_destructive(channel.guild, discord.AuditLogAction.channel_delete, "channel deleted")

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        await self.handle_destructive(role.guild, discord.AuditLogAction.role_delete, "role deleted")

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        await self.handle_destructive(guild, discord.AuditLogAction.ban, "member banned")

    # ── Anti-raid engine ──────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_join(self, member):
        guild = member.guild
        config = load_config()
        ar = config.get(str(guild.id), {}).get("antiraid", {})
        if not ar.get("enabled"):
            return
        now = time.time()
        window = ar.get("window", 10)
        self.recent_joins[guild.id] = [t for t in self.recent_joins[guild.id] if now - t <= window]
        self.recent_joins[guild.id].append(now)
        if len(self.recent_joins[guild.id]) < ar.get("threshold", 5):
            return

        action = ar.get("action", "kick")
        try:
            if action == "ban":
                await member.ban(reason="Anti-raid: rapid joins detected")
            else:
                await member.kick(reason="Anti-raid: rapid joins detected")
        except (discord.Forbidden, discord.HTTPException):
            pass

        # alert at most once per window
        if now - self.raid_alert_cooldown.get(guild.id, 0) > window:
            self.raid_alert_cooldown[guild.id] = now
            verb = "banned" if action == "ban" else "kicked"
            alert = discord.Embed(
                title="🚨 Raid Detected",
                color=0xE74C3C,
                timestamp=datetime.utcnow(),
                description=(
                    f"**{len(self.recent_joins[guild.id])}** members joined within **{window}s**. "
                    f"New joiners are being **{verb}**."
                ),
            )
            await send_log(guild, alert)


async def setup(bot):
    await bot.add_cog(Protection(bot))
