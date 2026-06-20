"""Info commands: userinfo, serverinfo, avatar, roleinfo."""
import discord
from discord import app_commands
from discord.ext import commands


class Info(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="userinfo", description="Show info about a member")
    @app_commands.describe(member="The member (defaults to you)")
    async def userinfo(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        roles = [r.mention for r in reversed(member.roles) if r != interaction.guild.default_role]
        embed = discord.Embed(title=f"User Info — {member}", color=member.color)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="ID", value=member.id, inline=True)
        embed.add_field(name="Bot?", value="Yes" if member.bot else "No", inline=True)
        embed.add_field(name="Nickname", value=member.nick or "—", inline=True)
        embed.add_field(name="Account Created", value=discord.utils.format_dt(member.created_at, "R"), inline=True)
        if member.joined_at:
            embed.add_field(name="Joined Server", value=discord.utils.format_dt(member.joined_at, "R"), inline=True)
        if member.is_timed_out():
            embed.add_field(name="Timed out until", value=discord.utils.format_dt(member.timed_out_until, "R"), inline=True)
        embed.add_field(name=f"Roles ({len(roles)})", value=(" ".join(roles)[:1024] or "None"), inline=False)
        embed.set_footer(text=f"Requested by {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="serverinfo", description="Show info about this server")
    async def serverinfo(self, interaction: discord.Interaction):
        g = interaction.guild
        embed = discord.Embed(title=g.name, color=0x5865F2)
        if g.icon:
            embed.set_thumbnail(url=g.icon.url)
        embed.add_field(name="ID", value=g.id, inline=True)
        embed.add_field(name="Owner", value=f"<@{g.owner_id}>", inline=True)
        embed.add_field(name="Members", value=g.member_count, inline=True)
        embed.add_field(name="Channels", value=len(g.channels), inline=True)
        embed.add_field(name="Roles", value=len(g.roles), inline=True)
        embed.add_field(name="Boosts", value=f"{g.premium_subscription_count} (Tier {g.premium_tier})", inline=True)
        embed.add_field(name="Created", value=discord.utils.format_dt(g.created_at, "R"), inline=True)
        embed.set_footer(text=f"Requested by {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="avatar", description="Show a member's avatar")
    @app_commands.describe(member="The member (defaults to you)")
    async def avatar(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        embed = discord.Embed(title=f"{member.display_name}'s avatar", color=member.color)
        embed.set_image(url=member.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="roleinfo", description="Show info about a role")
    @app_commands.describe(role="The role")
    async def roleinfo(self, interaction: discord.Interaction, role: discord.Role):
        embed = discord.Embed(title=f"Role — {role.name}", color=role.color)
        embed.add_field(name="ID", value=role.id, inline=True)
        embed.add_field(name="Color", value=str(role.color), inline=True)
        embed.add_field(name="Members", value=len(role.members), inline=True)
        embed.add_field(name="Mentionable", value="Yes" if role.mentionable else "No", inline=True)
        embed.add_field(name="Displayed separately", value="Yes" if role.hoist else "No", inline=True)
        embed.add_field(name="Position", value=role.position, inline=True)
        embed.add_field(name="Created", value=discord.utils.format_dt(role.created_at, "R"), inline=True)
        embed.set_footer(text=f"Requested by {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Info(bot))
