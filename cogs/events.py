"""Event signup: /eventjoin DM flow, submissions channel, custom questions, submission role."""
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime

from config_store import load_config, save_config, guild_config, DEFAULT_QUESTIONS, TIMEOUT


class QuestionsModal(discord.ui.Modal, title="Edit Event Questions"):
    def __init__(self, current):
        super().__init__()
        self.inputs = []
        for i in range(5):
            existing = current[i] if i < len(current) else None
            default = f"{existing['label']} | {existing['prompt']}" if existing else None
            ti = discord.ui.TextInput(
                label=f"Question {i + 1}" + ("" if i == 0 else " (optional)"),
                style=discord.TextStyle.paragraph,
                required=(i == 0),
                default=default,
                placeholder="Short Label | Full question text shown in DM",
                max_length=1000,
            )
            self.inputs.append(ti)
            self.add_item(ti)

    async def on_submit(self, interaction: discord.Interaction):
        questions = []
        for ti in self.inputs:
            raw = (ti.value or "").strip()
            if not raw:
                continue
            if "|" in raw:
                label, prompt = raw.split("|", 1)
                label, prompt = label.strip(), prompt.strip()
            else:
                label, prompt = f"Question {len(questions) + 1}", raw
            questions.append({"label": label or f"Question {len(questions) + 1}", "prompt": prompt})
        config = load_config()
        guild_config(config, interaction.guild.id)["questions"] = questions
        save_config(config)
        await interaction.response.send_message(
            f"✅ Saved **{len(questions)}** question(s) for this server's events.", ephemeral=True
        )


class Events(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_sessions = set()  # users currently in the /eventjoin flow

    @app_commands.command(name="setchannel", description="Set the channel where event submissions are posted")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(channel="The channel to send submissions to")
    async def setchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        config = load_config()
        guild_config(config, interaction.guild.id)["submissions_channel"] = channel.id
        save_config(config)
        await interaction.response.send_message(
            f"✅ Submissions channel set to {channel.mention}!", ephemeral=True
        )

    @app_commands.command(name="setsubmissionrole", description="Set a role to grant users after they complete /eventjoin")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(role="The role to grant on submission")
    async def setsubmissionrole(self, interaction: discord.Interaction, role: discord.Role):
        config = load_config()
        guild_config(config, interaction.guild.id)["submission_role"] = role.id
        save_config(config)
        await interaction.response.send_message(
            f"✅ Members will get {role.mention} after submitting an event entry.", ephemeral=True
        )

    @app_commands.command(name="setquestions", description="Customize the event signup questions (up to 5)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setquestions(self, interaction: discord.Interaction):
        config = load_config()
        g = config.get(str(interaction.guild.id), {})
        current = g.get("questions", DEFAULT_QUESTIONS)
        await interaction.response.send_modal(QuestionsModal(current))

    @app_commands.command(name="viewquestions", description="View the current event signup questions")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def viewquestions(self, interaction: discord.Interaction):
        config = load_config()
        g = config.get(str(interaction.guild.id), {})
        questions = g.get("questions", DEFAULT_QUESTIONS)
        embed = discord.Embed(title="📋 Event Questions", color=0x2ECC71)
        for i, q in enumerate(questions, 1):
            embed.add_field(name=f"{i}. {q['label']}"[:256], value=q["prompt"][:1024], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="resetquestions", description="Reset the event questions back to the defaults")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def resetquestions(self, interaction: discord.Interaction):
        config = load_config()
        guild_config(config, interaction.guild.id)["questions"] = DEFAULT_QUESTIONS
        save_config(config)
        await interaction.response.send_message("🔄 Event questions reset to defaults.", ephemeral=True)

    @app_commands.command(name="eventjoin", description="Join the current GD event by answering the questions via DM")
    async def eventjoin(self, interaction: discord.Interaction):
        config = load_config()
        guild_id = str(interaction.guild.id)
        g = config.get(guild_id, {})

        if "submissions_channel" not in g:
            await interaction.response.send_message(
                "❌ No submissions channel set. An admin needs to run `/setchannel` first.", ephemeral=True
            )
            return

        if interaction.user.id in self.active_sessions:
            await interaction.response.send_message(
                "⚠️ You're already in the middle of signing up! Check your DMs.", ephemeral=True
            )
            return

        try:
            await interaction.user.send("Starting event signup...")
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I can't DM you! Please enable DMs from server members and try again.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            "📬 Check your DMs! I've sent you the signup questions.", ephemeral=True
        )

        self.active_sessions.add(interaction.user.id)
        questions = g.get("questions", DEFAULT_QUESTIONS)
        total = len(questions)
        answers = []

        def check(m):
            return m.author.id == interaction.user.id and isinstance(m.channel, discord.DMChannel)

        try:
            for i, q in enumerate(questions, 1):
                await interaction.user.send(f"**Question {i}/{total} — {q['label']}**\n{q['prompt']}")
                msg = await self.bot.wait_for("message", check=check, timeout=TIMEOUT)
                answers.append(msg.content)
        except asyncio.TimeoutError:
            self.active_sessions.discard(interaction.user.id)
            try:
                await interaction.user.send(
                    "⏰ You took too long to respond (12 hour limit). Run `/eventjoin` again in the server if you still want to sign up."
                )
            except discord.Forbidden:
                pass
            return

        self.active_sessions.discard(interaction.user.id)

        submissions_channel = self.bot.get_channel(g["submissions_channel"])
        if submissions_channel is None:
            try:
                await interaction.user.send(
                    "⚠️ Your answers were received but the submissions channel couldn't be found. Contact a server admin."
                )
            except discord.Forbidden:
                pass
            return

        embed = discord.Embed(title="📋 New Event Submission", color=0x2ECC71, timestamp=datetime.utcnow())
        embed.set_author(
            name=f"{interaction.user.display_name} ({interaction.user})",
            icon_url=interaction.user.display_avatar.url,
        )
        for i, (q, a) in enumerate(zip(questions, answers), 1):
            # Discord caps field names at 256 chars and values at 1024
            embed.add_field(name=f"{i}. {q['label']}"[:256], value=(a or "—")[:1024], inline=False)
        embed.set_footer(text=f"User ID: {interaction.user.id}")
        await submissions_channel.send(embed=embed)

        # role assignment on submission
        role_id = g.get("submission_role")
        role_note = ""
        if role_id:
            role = interaction.guild.get_role(role_id)
            if role is not None:
                try:
                    await interaction.user.add_roles(role, reason="Completed event submission")
                    role_note = f"\nYou've been given the **{role.name}** role."
                except (discord.Forbidden, discord.HTTPException):
                    pass

        try:
            await interaction.user.send(f"✅ Your submission has been received! Good luck with the event 🎮{role_note}")
        except discord.Forbidden:
            pass


async def setup(bot):
    await bot.add_cog(Events(bot))
