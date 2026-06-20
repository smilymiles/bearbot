"""Verification: a persistent button panel that grants a configured role."""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime

from config_store import load_config, guild_config, save_config
from utils import send_log


class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="✅ Verify", style=discord.ButtonStyle.success, custom_id="bearbot:verify")
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = load_config()
        g = config.get(str(interaction.guild.id), {})
        role_id = g.get("verify_role")
        if not role_id:
            await interaction.response.send_message(
                "❌ Verification isn't set up yet. An admin needs to run `/setverify`.", ephemeral=True
            )
            return
        role = interaction.guild.get_role(role_id)
        if role is None:
            await interaction.response.send_message(
                "❌ The verification role no longer exists. Tell an admin.", ephemeral=True
            )
            return
        if role in interaction.user.roles:
            await interaction.response.send_message("✅ You're already verified!", ephemeral=True)
            return
        try:
            await interaction.user.add_roles(role, reason="Verification button")
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I couldn't give you the role — my role may be too low. Tell an admin.", ephemeral=True
            )
            return
        await interaction.response.send_message(f"✅ Verified! You now have {role.mention}.", ephemeral=True)
        embed = discord.Embed(
            title="✅ Member Verified",
            description=f"{interaction.user.mention} (`{interaction.user}`) verified.",
            color=0x2ECC71,
            timestamp=datetime.utcnow(),
        )
        embed.set_footer(text=f"User ID: {interaction.user.id}")
        await send_log(interaction.guild, embed)


class Verification(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setverify", description="Set the role given to members when they verify")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(role="The role to grant on verification")
    async def setverify(self, interaction: discord.Interaction, role: discord.Role):
        config = load_config()
        guild_config(config, interaction.guild.id)["verify_role"] = role.id
        save_config(config)
        await interaction.response.send_message(
            f"✅ Verification role set to {role.mention}. Run `/verifypanel` to post the button.",
            ephemeral=True,
        )

    @app_commands.command(name="verifypanel", description="Post the verification panel with a button in this channel")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def verifypanel(self, interaction: discord.Interaction):
        config = load_config()
        g = config.get(str(interaction.guild.id), {})
        if "verify_role" not in g:
            await interaction.response.send_message(
                "❌ Set a verification role first with `/setverify`.", ephemeral=True
            )
            return
        embed = discord.Embed(
            title="🔒 Verification",
            description="Click the button below to verify and gain access to the server.",
            color=0x2ECC71,
        )
        await interaction.channel.send(embed=embed, view=VerifyView())
        await interaction.response.send_message("✅ Verification panel posted!", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Verification(bot))
