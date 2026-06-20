"""Utility commands: say, poll."""
import discord
from discord import app_commands
from discord.ext import commands


class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="say", description="Make me send a message in this channel")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.describe(message="What I should say")
    async def say(self, interaction: discord.Interaction, message: str):
        # block @everyone/@here/role pings to prevent abuse; allow user mentions
        await interaction.channel.send(
            message[:2000],
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True),
        )
        await interaction.response.send_message("✅ Sent.", ephemeral=True)

    @app_commands.command(name="poll", description="Create a quick reaction poll")
    @app_commands.describe(question="The poll question", options="Up to 10 choices separated by | (optional)")
    async def poll(self, interaction: discord.Interaction, question: str, options: str = None):
        choices = [o.strip() for o in options.split("|") if o.strip()][:10] if options else []
        embed = discord.Embed(title="📊 " + question[:250], color=0x5865F2)
        embed.set_footer(text=f"Poll by {interaction.user.display_name}")
        if choices:
            letters = [chr(0x1F1E6 + i) for i in range(len(choices))]  # 🇦, 🇧, 🇨 ...
            embed.description = "\n".join(f"{letters[i]} {choices[i]}" for i in range(len(choices)))
            reactions = letters
        else:
            reactions = ["👍", "👎"]
        await interaction.response.send_message(embed=embed)
        msg = await interaction.original_response()
        for r in reactions:
            try:
                await msg.add_reaction(r)
            except discord.HTTPException:
                pass


async def setup(bot):
    await bot.add_cog(Utility(bot))
