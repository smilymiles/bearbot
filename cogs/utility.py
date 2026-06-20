"""Utility commands: say, poll."""
import discord
from discord import app_commands
from discord.ext import commands


class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def do_say(self, channel, message, allow_pings=False):
        """Send a message to a channel as the bot. Shared by /say and the web console. -> (ok, msg)."""
        message = (message or "").strip()
        if not message:
            return False, "❌ Message is empty."
        if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
            return False, "❌ I can't send messages to that channel."
        mentions = (discord.AllowedMentions.all() if allow_pings
                    else discord.AllowedMentions(everyone=False, roles=False, users=True))
        try:
            await channel.send(message[:2000], allowed_mentions=mentions)
        except discord.Forbidden:
            return False, "❌ I don't have permission to send messages in that channel."
        except discord.HTTPException as e:
            return False, f"❌ Send failed: {e}"
        return True, f"✅ Message sent to {channel.mention}."

    @app_commands.command(name="say", description="Make me send a message in this channel")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.describe(message="What I should say")
    async def say(self, interaction: discord.Interaction, message: str):
        # block @everyone/@here/role pings to prevent abuse; allow user mentions
        ok, msg = await self.do_say(interaction.channel, message, allow_pings=False)
        await interaction.response.send_message(msg if not ok else "✅ Sent.", ephemeral=True)

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
