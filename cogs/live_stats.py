import json
import os
from datetime import datetime
from typing import Any, Dict, Optional

import discord
from discord.ext import commands, tasks


DATA_FILE = os.path.join("data", "live_stats.json")


class LiveStatsStore:
    def __init__(self, path: str = DATA_FILE):
        self.path = path
        self.data = self._load()

    def _load(self) -> Dict[str, Any]:
        if not os.path.exists(self.path):
            return {"guilds": {}}

        with open(self.path, "r", encoding="utf-8") as fp:
            try:
                data = json.load(fp)
            except json.JSONDecodeError:
                return {"guilds": {}}

        if not isinstance(data, dict):
            return {"guilds": {}}

        data.setdefault("guilds", {})
        return data

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        temp_path = f"{self.path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as fp:
            json.dump(self.data, fp, indent=2)
        os.replace(temp_path, self.path)

    def settings(self, guild_id: int) -> Dict[str, Any]:
        state = self.data.setdefault("guilds", {}).setdefault(str(guild_id), {})
        state.setdefault("enabled", False)
        state.setdefault("channel_id", None)
        state.setdefault("message_id", None)
        return state

    def update(
        self,
        guild_id: int,
        *,
        enabled: Optional[bool] = None,
        channel_id: Optional[int] = None,
        message_id: Optional[int] = None,
    ) -> None:
        settings = self.settings(guild_id)
        if enabled is not None:
            settings["enabled"] = enabled
        if channel_id is not None:
            settings["channel_id"] = channel_id
        if message_id is not None:
            settings["message_id"] = message_id
        self.save()


class LiveStatsDashboardView(discord.ui.View):
    def __init__(self, bot: commands.Bot, cog: "LiveStatsCog", guild_id: int, user_id: int):
        super().__init__(timeout=900)
        self.bot = bot
        self.cog = cog
        self.guild_id = guild_id
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This live stats panel belongs to another moderator.", ephemeral=True)
            return False
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("You need Manage Messages to use live stats controls.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Post / Refresh", style=discord.ButtonStyle.green, row=0)
    async def post_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        result = await self.cog.post_or_refresh(interaction.guild, interaction.channel_id)
        await interaction.followup.send(result, ephemeral=True)

    @discord.ui.button(label="Auto Refresh On / Off", style=discord.ButtonStyle.blurple, row=0)
    async def auto_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        settings = self.cog.store.settings(interaction.guild_id)
        enabled = not bool(settings.get("enabled"))
        self.cog.store.update(interaction.guild_id, enabled=enabled)
        status = "enabled" if enabled else "disabled"
        await self.cog.log_action(interaction.guild_id, f"{interaction.user.mention} {status} live stats auto refresh.")
        await self.refresh(interaction, notice=f"Live stats auto refresh is now **{status}**.")

    @discord.ui.button(label="Use This Channel", style=discord.ButtonStyle.gray, row=0)
    async def channel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.cog.store.update(interaction.guild_id, channel_id=interaction.channel_id)
        await self.refresh(interaction, notice=f"Live stats channel set to <#{interaction.channel_id}>.")

    @discord.ui.button(label="Refresh Panel", style=discord.ButtonStyle.gray, row=1)
    async def refresh_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.refresh(interaction)

    def build_embed(self, notice: Optional[str] = None) -> discord.Embed:
        settings = self.cog.store.settings(self.guild_id)
        channel_id = settings.get("channel_id")
        message_id = settings.get("message_id")

        description = (
            f"Auto refresh: **{'Enabled' if settings.get('enabled') else 'Disabled'}**\n"
            f"Stats channel: {f'<#{channel_id}>' if channel_id else '**Not set**'}\n"
            f"Stats message ID: `{message_id}`\n\n"
            "Posts one clean server-health message that moderators can refresh from here."
        )
        if notice:
            description = f"{notice}\n\n{description}"

        return discord.Embed(title="Live Stats", description=description, color=0xE8C1A0)

    async def refresh(self, interaction: discord.Interaction, notice: Optional[str] = None):
        embed = self.build_embed(notice=notice)
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)


class LiveStatsCog(commands.Cog, name="LiveStatsCog"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.store = LiveStatsStore()
        self.refresh_loop.start()

    async def cog_unload(self):
        self.refresh_loop.cancel()

    async def launch_dashboard(self, interaction: discord.Interaction):
        view = LiveStatsDashboardView(self.bot, self, interaction.guild_id, interaction.user.id)
        await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)

    def build_stats_embed(self, guild: discord.Guild) -> discord.Embed:
        human_count = sum(1 for member in guild.members if not member.bot)
        bot_count = sum(1 for member in guild.members if member.bot)
        text_channels = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)

        onboarding_cog = self.bot.get_cog("OnboardingCog")
        pending_onboarding = "Unavailable"
        onboarding_status = "Unavailable"
        if onboarding_cog:
            pending_onboarding = str(len(onboarding_cog.store.pending_members(guild.id)))
            onboarding_status = "Enabled" if onboarding_cog.store.is_enabled(guild.id) else "Disabled"

        embed = discord.Embed(
            title=f"{guild.name} Live Stats",
            description="Server health snapshot for the moderation team.",
            color=0xE8C1A0,
        )
        embed.add_field(name="Members", value=f"Total: **{guild.member_count or len(guild.members)}**\nHumans: **{human_count}**\nBots: **{bot_count}**")
        embed.add_field(name="Channels", value=f"Text: **{text_channels}**\nVoice: **{voice_channels}**\nRoles: **{len(guild.roles)}**")
        embed.add_field(name="Onboarding", value=f"Status: **{onboarding_status}**\nPending today: **{pending_onboarding}**")
        embed.set_footer(text="Auto refreshes every 30 minutes when enabled")
        embed.timestamp = datetime.utcnow()
        return embed

    async def post_or_refresh(self, guild: discord.Guild, fallback_channel_id: Optional[int] = None) -> str:
        settings = self.store.settings(guild.id)
        channel_id = settings.get("channel_id") or fallback_channel_id
        if not channel_id:
            return "Choose a channel first."

        try:
            channel = self.bot.get_channel(int(channel_id)) or await self.bot.fetch_channel(int(channel_id))
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            return f"Could not access channel `{channel_id}`."

        embed = self.build_stats_embed(guild)
        message_id = settings.get("message_id")
        message = None

        if message_id:
            try:
                message = await channel.fetch_message(int(message_id))
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                message = None

        if message:
            await message.edit(embed=embed)
            action = "refreshed"
        else:
            message = await channel.send(embed=embed)
            self.store.update(guild.id, channel_id=int(channel_id), message_id=message.id)
            action = "posted"

        await self.log_action(guild.id, f"Live stats {action} in <#{channel_id}>.")
        return f"Live stats {action} in <#{channel_id}>."

    async def log_action(self, guild_id: int, description: str):
        audit_cog = self.bot.get_cog("AuditLogsCog")
        if audit_cog:
            await audit_cog.log_event(guild_id, "Live Stats", description, color=0xE8C1A0)

    @tasks.loop(minutes=30)
    async def refresh_loop(self):
        for guild in self.bot.guilds:
            settings = self.store.settings(guild.id)
            if settings.get("enabled") and settings.get("channel_id"):
                await self.post_or_refresh(guild)

    @refresh_loop.before_loop
    async def before_refresh_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(LiveStatsCog(bot))
