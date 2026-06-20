"""Admin utilities: change the bot's nickname, create/assign roles."""
import discord
from discord import app_commands
from discord.ext import commands

from config_store import load_config


def parse_color(s):
    """Parse a hex string like '#FF0000' or 'ff0000' into a discord.Color, or None if invalid."""
    s = s.strip().lstrip("#")
    try:
        value = int(s, 16)
    except ValueError:
        return None
    if not 0 <= value <= 0xFFFFFF:
        return None
    return discord.Color(value)


def resolve_staff_role(guild, config_key, fallback_name):
    """Find a staff role by its saved config ID, falling back to a name lookup."""
    role_id = load_config().get(str(guild.id), {}).get(config_key)
    if role_id:
        role = guild.get_role(role_id)
        if role:
            return role
    return discord.utils.get(guild.roles, name=fallback_name)


class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="botname", description="Change my nickname in this server")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.checks.bot_has_permissions(change_nickname=True)
    @app_commands.describe(name="The new nickname (leave blank to reset to my default)")
    async def botname(self, interaction: discord.Interaction, name: str = None):
        if name and len(name) > 32:
            await interaction.response.send_message(
                "❌ Nicknames can be at most 32 characters.", ephemeral=True
            )
            return
        try:
            await interaction.guild.me.edit(nick=name)
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I couldn't change my nickname — I need the **Change Nickname** permission.", ephemeral=True
            )
            return
        if name:
            await interaction.response.send_message(f"✅ My nickname is now **{name}**.", ephemeral=True)
        else:
            await interaction.response.send_message("✅ Reset my nickname to default.", ephemeral=True)

    @app_commands.command(name="makerole", description="Create a new role")
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    @app_commands.describe(
        name="Name of the role",
        color="Hex color like #3498db (optional)",
        hoist="Show members with this role separately in the sidebar",
        mentionable="Allow anyone to @mention this role",
    )
    async def makerole(self, interaction: discord.Interaction, name: str,
                       color: str = None, hoist: bool = False, mentionable: bool = False):
        if len(name) > 100:
            await interaction.response.send_message("❌ Role names can be at most 100 characters.", ephemeral=True)
            return
        role_color = discord.Color.default()
        if color:
            parsed = parse_color(color)
            if parsed is None:
                await interaction.response.send_message(
                    "❌ That's not a valid hex color. Try something like `#3498db`.", ephemeral=True
                )
                return
            role_color = parsed
        try:
            role = await interaction.guild.create_role(
                name=name, color=role_color, hoist=hoist, mentionable=mentionable,
                reason=f"Created by {interaction.user}",
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I couldn't create that role — check my permissions and role position.", ephemeral=True
            )
            return
        await interaction.response.send_message(f"✅ Created role {role.mention}.", ephemeral=True)

    @app_commands.command(name="makeadminrole", description="Create a role with Administrator permission")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.checks.bot_has_permissions(administrator=True)
    @app_commands.describe(name="Name of the admin role", color="Hex color like #e74c3c (optional)")
    async def makeadminrole(self, interaction: discord.Interaction, name: str, color: str = None):
        if len(name) > 100:
            await interaction.response.send_message("❌ Role names can be at most 100 characters.", ephemeral=True)
            return
        role_color = discord.Color.red()
        if color:
            parsed = parse_color(color)
            if parsed is None:
                await interaction.response.send_message(
                    "❌ That's not a valid hex color. Try something like `#e74c3c`.", ephemeral=True
                )
                return
            role_color = parsed
        try:
            role = await interaction.guild.create_role(
                name=name,
                color=role_color,
                hoist=True,
                permissions=discord.Permissions(administrator=True),
                reason=f"Admin role created by {interaction.user}",
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I couldn't create that role — I need the **Administrator** permission to grant it.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"✅ Created admin role {role.mention} with **Administrator** permission.\n"
            f"⚠️ This role can do anything — assign it carefully.", ephemeral=True
        )

    # ── Role assignment ────────────────────────────────────────────────────────
    async def _assign(self, interaction, member, role, *, missing_hint, check_escalation=False):
        if role is None:
            await interaction.response.send_message(
                f"❌ {missing_hint}", ephemeral=True
            )
            return
        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                f"❌ I can't assign {role.mention} — it's above (or equal to) my highest role. Move my role up.",
                ephemeral=True,
            )
            return
        if role.managed:
            await interaction.response.send_message(
                f"❌ {role.mention} is managed by an integration and can't be assigned manually.", ephemeral=True
            )
            return
        if (check_escalation and role >= interaction.user.top_role
                and interaction.user.id != interaction.guild.owner_id):
            await interaction.response.send_message(
                "❌ You can't assign a role equal to or higher than your own top role.", ephemeral=True
            )
            return
        if role in member.roles:
            await interaction.response.send_message(
                f"ℹ️ {member.mention} already has {role.mention}.", ephemeral=True
            )
            return
        try:
            await member.add_roles(role, reason=f"Assigned by {interaction.user}")
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I couldn't assign that role — check my permissions and role position.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"✅ Gave {role.mention} to {member.mention}.",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @app_commands.command(name="addmod", description="Give a member the Mod role")
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    @app_commands.describe(member="The member to make a mod")
    async def addmod(self, interaction: discord.Interaction, member: discord.Member):
        role = resolve_staff_role(interaction.guild, "mod_role", "Mod")
        await self._assign(interaction, member, role,
                           missing_hint="No **Mod** role found. Run `/setup` first or create one named `Mod`.")

    @app_commands.command(name="addadmin", description="Give a member the Admin role")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    @app_commands.describe(member="The member to make an admin")
    async def addadmin(self, interaction: discord.Interaction, member: discord.Member):
        role = resolve_staff_role(interaction.guild, "admin_role", "Admin")
        await self._assign(interaction, member, role,
                           missing_hint="No **Admin** role found. Run `/setup` first or create one named `Admin`.")

    @app_commands.command(name="addowner", description="Give a member the Owner role")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    @app_commands.describe(member="The member to make an owner")
    async def addowner(self, interaction: discord.Interaction, member: discord.Member):
        role = resolve_staff_role(interaction.guild, "owner_role", "Owner")
        await self._assign(interaction, member, role,
                           missing_hint="No **Owner** role found. Run `/setup` first or create one named `Owner`.")

    @app_commands.command(name="giverole", description="Give a member any role")
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    @app_commands.describe(member="The member to give the role to", role="The role to give")
    async def giverole(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        await self._assign(interaction, member, role, missing_hint="That role doesn't exist.", check_escalation=True)


async def setup(bot):
    await bot.add_cog(Admin(bot))
