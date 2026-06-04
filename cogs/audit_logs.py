import json
import os
from datetime import datetime
from typing import Any, Dict, Optional

import discord
from discord.ext import commands


DATA_FILE = os.path.join("data", "audit_logs.json")


class AuditLogStore:
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
        return state

    def update(self, guild_id: int, *, enabled: Optional[bool] = None, channel_id: Optional[int] = None) -> None:
        settings = self.settings(guild_id)
        if enabled is not None:
            settings["enabled"] = enabled
        if channel_id is not None:
            settings["channel_id"] = channel_id
        self.save()


class AuditLogsDashboardView(discord.ui.View):
    def __init__(self, bot: commands.Bot, cog: "AuditLogsCog", guild_id: int, user_id: int):
        super().__init__(timeout=900)
        self.bot = bot
        self.cog = cog
        self.guild_id = guild_id
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This audit log panel belongs to another moderator.", ephemeral=True)
            return False
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("You need Manage Messages to use audit log controls.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Enable / Disable", style=discord.ButtonStyle.blurple, row=0)
    async def toggle_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        settings = self.cog.store.settings(interaction.guild_id)
        enabled = not bool(settings.get("enabled"))
        self.cog.store.update(interaction.guild_id, enabled=enabled)
        status = "enabled" if enabled else "disabled"
        await self.cog.log_event(
            interaction.guild_id,
            "Audit Logs Toggled",
            f"{interaction.user.mention} {status} audit logging.",
            force=True,
        )
        await self.refresh(interaction, notice=f"Audit logging is now **{status}**.")

    @discord.ui.button(label="Use This Channel", style=discord.ButtonStyle.green, row=0)
    async def channel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.cog.store.update(interaction.guild_id, channel_id=interaction.channel_id)
        await self.refresh(interaction, notice=f"Audit log channel set to <#{interaction.channel_id}>.")

    @discord.ui.button(label="Send Test Log", style=discord.ButtonStyle.gray, row=0)
    async def test_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        ok = await self.cog.log_event(
            interaction.guild_id,
            "Audit Log Test",
            f"Test log requested by {interaction.user.mention}.",
            force=True,
        )
        if ok:
            await interaction.followup.send("Test log sent.", ephemeral=True)
        else:
            await interaction.followup.send("Set an audit channel first.", ephemeral=True)

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.gray, row=1)
    async def refresh_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.refresh(interaction)

    def build_embed(self, notice: Optional[str] = None) -> discord.Embed:
        settings = self.cog.store.settings(self.guild_id)
        channel_id = settings.get("channel_id")
        description = (
            f"Status: **{'Enabled' if settings.get('enabled') else 'Disabled'}**\n"
            f"Log channel: {f'<#{channel_id}>' if channel_id else '**Not set**'}\n\n"
            "Tracks member joins/leaves, message deletes/edits, channel changes, and important bot actions."
        )
        if notice:
            description = f"{notice}\n\n{description}"

        return discord.Embed(title="Audit Logs", description=description, color=0xE8C1A0)

    async def refresh(self, interaction: discord.Interaction, notice: Optional[str] = None):
        embed = self.build_embed(notice=notice)
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)


class AuditLogsCog(commands.Cog, name="AuditLogsCog"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.store = AuditLogStore()

    async def launch_dashboard(self, interaction: discord.Interaction):
        view = AuditLogsDashboardView(self.bot, self, interaction.guild_id, interaction.user.id)
        await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)

    async def log_event(
        self,
        guild_id: int,
        title: str,
        description: str,
        *,
        color: int = 0x2B2D31,
        force: bool = False,
    ) -> bool:
        settings = self.store.settings(guild_id)
        if not force and not settings.get("enabled"):
            return False

        channel_id = settings.get("channel_id")
        if not channel_id:
            return False

        try:
            channel = self.bot.get_channel(int(channel_id)) or await self.bot.fetch_channel(int(channel_id))
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            return False

        embed = discord.Embed(title=title, description=description[:4000], color=color)
        embed.timestamp = datetime.utcnow()
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            return False
        return True

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await self.log_event(
            member.guild.id,
            "Member Joined",
            f"{member.mention} joined.\nUser ID: `{member.id}`",
            color=0x57F287,
        )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await self.log_event(
            member.guild.id,
            "Member Left",
            f"{member} left.\nUser ID: `{member.id}`",
            color=0xED4245,
        )

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return

        content = message.content or "(no text content)"
        await self.log_event(
            message.guild.id,
            "Message Deleted",
            f"Author: {message.author.mention} (`{message.author.id}`)\nChannel: {message.channel.mention}\nContent: {content[:1500]}",
            color=0xFEE75C,
        )

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not before.guild or before.author.bot or before.content == after.content:
            return

        await self.log_event(
            before.guild.id,
            "Message Edited",
            f"Author: {before.author.mention} (`{before.author.id}`)\n"
            f"Channel: {before.channel.mention}\n"
            f"Before: {(before.content or '(empty)')[:900]}\n"
            f"After: {(after.content or '(empty)')[:900]}",
            color=0x5865F2,
        )

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        label = getattr(channel, "mention", f"#{channel.name}")
        await self.log_event(channel.guild.id, "Channel Created", f"Channel: {label} (`{channel.id}`)")

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        await self.log_event(channel.guild.id, "Channel Deleted", f"Channel: `#{channel.name}` (`{channel.id}`)")


async def setup(bot):
    await bot.add_cog(AuditLogsCog(bot))
