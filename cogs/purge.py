"""Purge commands: bulk-delete messages by amount, by bots, by user, or by time window.

Note: Discord only lets bots bulk-delete messages younger than 14 days. Older messages
are deleted one-by-one (slower) and very old history may not be removable.
"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import timedelta

from utils import send_log

PURGEABLE = (discord.TextChannel, discord.Thread, discord.VoiceChannel)


class Purge(commands.Cog):
    # a slash-command group: /purge <sub>
    purge = app_commands.Group(
        name="purge",
        description="Bulk-delete messages from this channel",
        guild_only=True,
        default_permissions=discord.Permissions(manage_messages=True),
    )

    def __init__(self, bot):
        self.bot = bot

    async def purge_messages(self, channel, guild, *, label, limit=None, check=None, after=None, moderator="Console"):
        """Core purge logic shared by the slash commands and the web console. -> (ok, message)."""
        if not isinstance(channel, PURGEABLE):
            return False, "❌ I can't purge messages in this kind of channel."
        kwargs = {"limit": limit, "reason": f"Purge by {moderator}"}
        if check is not None:
            kwargs["check"] = check
        if after is not None:
            kwargs["after"] = after
        try:
            deleted = await channel.purge(**kwargs)
        except discord.Forbidden:
            return False, "❌ I need the **Manage Messages** permission in this channel."
        except discord.HTTPException as e:
            return False, f"⚠️ Purge failed: {e}"

        n = len(deleted)
        embed = discord.Embed(title="🧹 Messages Purged", color=0x95A5A6, timestamp=discord.utils.utcnow())
        embed.add_field(name="Channel", value=channel.mention, inline=False)
        embed.add_field(name="Moderator", value=str(moderator), inline=False)
        embed.add_field(name="Deleted", value=f"{n} — {label}", inline=False)
        await send_log(guild, embed)
        return True, f"🧹 Deleted **{n}** message(s) — {label}."

    async def _do_purge(self, interaction, *, label, limit=None, check=None, after=None):
        if not isinstance(interaction.channel, PURGEABLE):
            await interaction.response.send_message(
                "❌ I can't purge messages in this kind of channel.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        ok, msg = await self.purge_messages(
            interaction.channel, interaction.guild, label=label, limit=limit,
            check=check, after=after, moderator=str(interaction.user),
        )
        await interaction.followup.send(msg, ephemeral=True)

    @purge.command(name="channel", description="Delete the last N messages in this channel")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.checks.bot_has_permissions(manage_messages=True)
    @app_commands.describe(amount="How many recent messages to delete (1-1000)")
    async def purge_channel(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 1000]):
        await self._do_purge(interaction, limit=amount, label=f"last {amount} messages")

    @purge.command(name="bot", description="Delete bot messages among the last N messages")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.checks.bot_has_permissions(manage_messages=True)
    @app_commands.describe(amount="How many recent messages to scan for bot messages (1-1000)")
    async def purge_bot(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 1000] = 100):
        await self._do_purge(
            interaction, limit=amount, check=lambda m: m.author.bot,
            label=f"bot messages in last {amount}",
        )

    @purge.command(name="user", description="Delete a member's messages among the last N messages")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.checks.bot_has_permissions(manage_messages=True)
    @app_commands.describe(member="Whose messages to delete", amount="How many recent messages to scan (1-1000)")
    async def purge_user(self, interaction: discord.Interaction, member: discord.Member,
                         amount: app_commands.Range[int, 1, 1000] = 100):
        await self._do_purge(
            interaction, limit=amount, check=lambda m: m.author.id == member.id,
            label=f"{member}'s messages in last {amount}",
        )

    @purge.command(name="time", description="Delete all messages from the last N minutes")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.checks.bot_has_permissions(manage_messages=True)
    @app_commands.describe(minutes="Delete messages newer than this many minutes (1-1440)")
    async def purge_time(self, interaction: discord.Interaction, minutes: app_commands.Range[int, 1, 1440]):
        after = discord.utils.utcnow() - timedelta(minutes=minutes)
        await self._do_purge(interaction, limit=None, after=after, label=f"last {minutes} min")


async def setup(bot):
    await bot.add_cog(Purge(bot))
