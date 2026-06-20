"""Booster role: automatically grant a role when someone boosts the server (remove on unboost)."""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime

from config_store import load_config, save_config, guild_config
from utils import send_log


class Boosters(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setboosterrole", description="Set the role automatically given to server boosters")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    @app_commands.describe(role="The role to give boosters")
    async def setboosterrole(self, interaction: discord.Interaction, role: discord.Role):
        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                f"❌ I can't assign {role.mention} — move my role above it first.", ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        if role.managed:
            await interaction.response.send_message(
                "❌ That's an integration-managed role and can't be assigned manually. Make a normal role.",
                ephemeral=True,
            )
            return

        config = load_config()
        guild_config(config, interaction.guild.id)["booster_role"] = role.id
        save_config(config)

        # give it to everyone already boosting
        applied = 0
        for member in interaction.guild.premium_subscribers:
            if role not in member.roles:
                try:
                    await member.add_roles(role, reason="Booster role setup")
                    applied += 1
                except discord.HTTPException:
                    pass

        await interaction.response.send_message(
            f"✅ Booster role set to {role.mention}. Gave it to **{applied}** current booster(s).",
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        # only care when boosting status actually changes
        if before.premium_since == after.premium_since:
            return

        config = load_config()
        role_id = config.get(str(after.guild.id), {}).get("booster_role")
        if not role_id:
            return
        role = after.guild.get_role(role_id)
        if role is None:
            return

        started = before.premium_since is None and after.premium_since is not None
        stopped = before.premium_since is not None and after.premium_since is None

        try:
            if started and role not in after.roles:
                await after.add_roles(role, reason="Started boosting the server")
                embed = discord.Embed(
                    title="💎 New Server Booster!",
                    description=f"{after.mention} boosted the server and received {role.mention}. Thank you! 🎉",
                    color=0xF47FFF,
                    timestamp=datetime.utcnow(),
                )
                embed.set_footer(text=f"User ID: {after.id}")
                await send_log(after.guild, embed)
            elif stopped and role in after.roles:
                await after.remove_roles(role, reason="Stopped boosting the server")
                embed = discord.Embed(
                    title="💔 Booster Ended",
                    description=f"{after.mention} stopped boosting; removed {role.mention}.",
                    color=0x95A5A6,
                    timestamp=datetime.utcnow(),
                )
                embed.set_footer(text=f"User ID: {after.id}")
                await send_log(after.guild, embed)
        except discord.HTTPException:
            pass


async def setup(bot):
    await bot.add_cog(Boosters(bot))
