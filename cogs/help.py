"""/help — lists every command, grouped by category, built dynamically from the command tree."""
import discord
from discord import app_commands
from discord.ext import commands

# cog class name -> (friendly title, display order). Anything not listed lands in "Other".
CATEGORIES = {
    "ServerSetup": "🛠️ Setup",
    "Events": "🎮 Events",
    "Verification": "✅ Verification",
    "Moderation": "🔨 Moderation",
    "Admin": "👮 Roles & Bot",
    "Protection": "🛡️ Protection",
    "Help": "ℹ️ Info",
}
ORDER = list(CATEGORIES.keys())


class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show all of BearBot's commands")
    async def help_cmd(self, interaction: discord.Interaction):
        # group commands by the cog they belong to
        groups = {}
        for cmd in self.bot.tree.walk_commands():
            if not isinstance(cmd, app_commands.Command):
                continue
            cog_name = cmd.binding.__cog_name__ if cmd.binding else "Other"
            groups.setdefault(cog_name, []).append(cmd)

        embed = discord.Embed(
            title="📋 BearBot Commands",
            description="Everything I can do, grouped by category. Most commands need a server permission to use.",
            color=0x2ECC71,
        )

        # listed categories first (in order), then any leftovers
        ordered = [c for c in ORDER if c in groups] + [c for c in groups if c not in ORDER]
        for cog_name in ordered:
            cmds = sorted(groups[cog_name], key=lambda c: c.name)
            title = CATEGORIES.get(cog_name, f"📦 {cog_name}")
            value = "\n".join(f"`/{c.name}` — {c.description}" for c in cmds)
            embed.add_field(name=title, value=value[:1024], inline=False)

        embed.set_footer(text=f"{sum(len(v) for v in groups.values())} commands • made for GD collab events")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Help(bot))
