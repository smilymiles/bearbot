"""One-shot server setup: creates the recommended GD-event roles, category, and channels."""
import discord
from discord import app_commands
from discord.ext import commands

from config_store import load_config, save_config, guild_config
from cogs.verification import VerifyView


class ServerSetup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setup", description="Auto-create the recommended roles, category, and channels for GD events")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.checks.bot_has_permissions(manage_channels=True, manage_roles=True)
    async def setup_server(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        created = []
        existing = []
        failed = []

        async def get_or_create_role(name, **kwargs):
            role = discord.utils.get(guild.roles, name=name)
            if role:
                existing.append(f"Role **{name}**")
                return role
            try:
                role = await guild.create_role(name=name, reason="BearBot setup", **kwargs)
            except discord.Forbidden:
                # happens when granting perms (e.g. Administrator) the bot doesn't itself have
                failed.append(f"Role **{name}** — I need higher perms (Administrator) to create it")
                return None
            created.append(f"Role **{name}**")
            return role

        async def get_or_create_category(name, overwrites=None):
            cat = discord.utils.get(guild.categories, name=name)
            if cat:
                existing.append(f"Category **{name}**")
                return cat
            cat = await guild.create_category(name, overwrites=overwrites or {}, reason="BearBot setup")
            created.append(f"Category **{name}**")
            return cat

        async def get_or_create_text(name, category, overwrites=None):
            ch = discord.utils.get(guild.text_channels, name=name)
            if ch:
                existing.append(f"Channel #{name}")
                return ch
            ch = await guild.create_text_channel(name, category=category, overwrites=overwrites or {}, reason="BearBot setup")
            created.append(f"Channel #{name}")
            return ch

        # ── Staff roles (created low → high so Owner sits above Admin above Mod) ──
        mod_perms = discord.Permissions(
            kick_members=True, ban_members=True, manage_messages=True, moderate_members=True,
            manage_nicknames=True, view_audit_log=True, mute_members=True,
            deafen_members=True, move_members=True,
        )
        mod_role = await get_or_create_role("Mod", color=discord.Color(0x3498DB), hoist=True, permissions=mod_perms)
        admin_role = await get_or_create_role("Admin", color=discord.Color(0xE74C3C), hoist=True,
                                              permissions=discord.Permissions(administrator=True))
        owner_role = await get_or_create_role("Owner", color=discord.Color(0xF1C40F), hoist=True,
                                              permissions=discord.Permissions(administrator=True))

        # ── Event roles ──────────────────────────────────────────────────────────
        verified = await get_or_create_role("Verified")
        participant = await get_or_create_role("Event Participant", color=discord.Color(0x2ECC71))

        # ── Booster role ─────────────────────────────────────────────────────────
        booster_role = await get_or_create_role("Booster", color=discord.Color(0xF47FFF), hoist=True)

        # ── Category + channels ─────────────────────────────────────────────────
        everyone = guild.default_role
        category = await get_or_create_category("📋 GD EVENTS")

        info = await get_or_create_text("event-info", category)
        await get_or_create_text("eventjoin", category)

        # submissions: everyone can read, only the bot/staff post (left open for staff perms)
        submissions = await get_or_create_text("submissions", category)

        # logs: hidden from @everyone
        log_overwrites = {everyone: discord.PermissionOverwrite(view_channel=False)}
        logs = await get_or_create_text("bot-logs", category, overwrites=log_overwrites)

        # verify channel: visible to everyone so unverified members can click the button
        verify_channel = await get_or_create_text("verify", category)

        # ── Wire up config (only set what isn't already configured) ───────────────
        config = load_config()
        g = guild_config(config, guild.id)
        newly_wired = []
        already_set = []

        def wire(label, key, value):
            if value is None:
                return
            if key in g:
                already_set.append(label)
            else:
                g[key] = value
                newly_wired.append(label)

        wire(f"Submissions → {submissions.mention}", "submissions_channel", submissions.id)
        wire(f"Logs → {logs.mention}", "log_channel", logs.id)
        if verified:
            wire(f"Verify role → {verified.mention}", "verify_role", verified.id)
        if participant:
            wire(f"Submission role → {participant.mention}", "submission_role", participant.id)
        if mod_role:
            wire(f"Mod role → {mod_role.mention}", "mod_role", mod_role.id)
        if admin_role:
            wire(f"Admin role → {admin_role.mention}", "admin_role", admin_role.id)
        if owner_role:
            wire(f"Owner role → {owner_role.mention}", "owner_role", owner_role.id)
        if booster_role:
            wire(f"Booster role → {booster_role.mention}", "booster_role", booster_role.id)

        # Protection: enable out of the box, but never override settings you already have
        if "antiraid" in g:
            already_set.append("Anti-raid (kept your settings)")
        else:
            g["antiraid"] = {"enabled": True, "threshold": 5, "window": 10, "action": "kick"}
            newly_wired.append("Anti-raid → ON (5 joins / 10s → kick)")
        if "antinuke" in g:
            already_set.append("Anti-nuke (kept your settings)")
        else:
            g["antinuke"] = {"enabled": True, "threshold": 3, "window": 30, "whitelist": []}
            newly_wired.append("Anti-nuke → ON (3 actions / 30s → quarantine)")
        # always make sure whoever ran setup is whitelisted for anti-nuke
        antinuke = g["antinuke"]
        antinuke.setdefault("whitelist", [])
        if interaction.user.id not in antinuke["whitelist"]:
            antinuke["whitelist"].append(interaction.user.id)
        save_config(config)

        # ── Give the booster role to anyone already boosting ──────────────────────
        booster_applied = 0
        if booster_role:
            for member in guild.premium_subscribers:
                if booster_role not in member.roles:
                    try:
                        await member.add_roles(booster_role, reason="BearBot setup booster role")
                        booster_applied += 1
                    except discord.HTTPException:
                        pass

        # ── Post the verification panel (exactly one — clean up any old ones) ─────
        try:
            async for msg in verify_channel.history(limit=50):
                if (msg.author.id == self.bot.user.id and msg.embeds
                        and msg.embeds[0].title == "🔒 Verification"):
                    await msg.delete()
            panel = discord.Embed(
                title="🔒 Verification",
                description="Click the button below to verify and gain access to the server.",
                color=0x2ECC71,
            )
            await verify_channel.send(embed=panel, view=VerifyView())
        except discord.HTTPException:
            pass

        # ── Report ───────────────────────────────────────────────────────────────
        nothing_changed = not created and not newly_wired
        embed = discord.Embed(
            title="✅ BearBot Setup Complete",
            color=0x2ECC71,
            description=("Everything was already set up — nothing to change. ✅"
                         if nothing_changed else "Here's what I did:"),
        )
        if created:
            embed.add_field(name="🆕 Created", value="\n".join(f"• {c}" for c in created), inline=False)
        if existing:
            embed.add_field(name="♻️ Reused (already existed)", value="\n".join(f"• {e}" for e in existing), inline=False)
        if failed:
            embed.add_field(name="⚠️ Couldn't create", value="\n".join(f"• {f}" for f in failed), inline=False)
        if newly_wired:
            embed.add_field(name="🔧 Newly configured", value="\n".join(f"• {w}" for w in newly_wired), inline=False)
        if already_set:
            embed.add_field(name="✓ Already configured (left as-is)", value="\n".join(f"• {s}" for s in already_set), inline=False)

        extras = [f"Verify panel ready in {verify_channel.mention}"]
        if booster_applied:
            extras.append(f"Booster role applied to {booster_applied} current booster(s)")
        embed.add_field(name="Also", value="\n".join(f"• {e}" for e in extras), inline=False)

        embed.set_footer(text="Heads up: drag the Owner/Admin/Mod/Booster roles above other roles, and keep my role above them so I can assign them.")
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(ServerSetup(bot))
