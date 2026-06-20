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

    async def _do_purge(self, interaction, *, label, limit=None, check=None, after=None):
        channel = interaction.channel
        if not isinstance(channel, PURGEABLE):
            await interaction.response.send_message(
                "❌ I can't purge messages in this kind of channel.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        kwargs = {"limit": limit, "reason": f"Purge by {interaction.user}"}
        if check is not None:
            kwargs["check"] = check
        if after is not None:
            kwargs["after"] = after

        try:
            deleted = await channel.purge(**kwargs)
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ I need the **Manage Messages** permission in this channel.", ephemeral=True
            )
            return
        except discord.HTTPException as e:
            await interaction.followup.send(f"⚠️ Purge failed: {e}", ephemeral=True)
            return

        n = len(deleted)
        await interaction.followup.send(f"🧹 Deleted **{n}** message(s) — {label}.", ephemeral=True)

        embed = discord.Embed(title="🧹 Messages Purged", color=0x95A5A6, timestamp=discord.utils.utcnow())
        embed.add_field(name="Channel", value=channel.mention, inline=False)
        embed.add_field(name="Moderator", value=str(interaction.user), inline=False)
        embed.add_field(name="Deleted", value=f"{n} — {label}", inline=False)
        await send_log(interaction.guild, embed)

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
