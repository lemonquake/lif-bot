import asyncio
import json
import os
from typing import Any, Dict, Tuple

import discord
from discord.ext import commands

from utils.state import EmbedScript


DATA_FILE = "data/stickies.json"


class StickyDashboardView(discord.ui.View):
    def __init__(self, bot: commands.Bot, cog: "StickyMessagesCog", user_id: int):
        super().__init__(timeout=900)
        self.bot = bot
        self.cog = cog
        self.user_id = user_id
        self.refresh_ui()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This is not your session.", ephemeral=True)
            return False

        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("You need Manage Messages to use sticky controls.", ephemeral=True)
            return False

        return True

    def refresh_ui(self):
        self.clear_items()

        self.add_item(
            discord.ui.Button(
                label="Disable All Stickies",
                style=discord.ButtonStyle.red,
                custom_id="sticky:disable_all",
                row=0,
                disabled=not self.cog.global_enabled or not self.cog.stickies,
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Enable All Stickies",
                style=discord.ButtonStyle.green,
                custom_id="sticky:enable_all",
                row=0,
                disabled=not self.cog.stickies or (self.cog.global_enabled and not self.cog.has_inactive_stickies()),
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Flush All Stickies",
                style=discord.ButtonStyle.red,
                custom_id="sticky:flush_all",
                row=0,
                disabled=not self.cog.stickies,
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Create / Edit Sticky Message",
                style=discord.ButtonStyle.blurple,
                custom_id="sticky:create",
                row=1,
            )
        )

        options = []
        for channel_id_str, data in self.cog.stickies.items():
            channel = self.bot.get_channel(int(channel_id_str))
            if channel:
                status = "Active" if data.get("is_active") else "Inactive"
                options.append(
                    discord.SelectOption(
                        label=f"#{channel.name} ({status})",
                        value=channel_id_str,
                        description="Click to toggle this channel sticky",
                    )
                )

        if options:
            self.add_item(
                discord.ui.Select(
                    placeholder="Toggle one channel sticky...",
                    options=options[:25],
                    row=2,
                    custom_id="sticky:toggle",
                )
            )
        else:
            self.add_item(
                discord.ui.Button(
                    label="No Stickies Configured",
                    style=discord.ButtonStyle.gray,
                    disabled=True,
                    row=2,
                )
            )

    async def process_interaction(self, interaction: discord.Interaction):
        custom_id = interaction.data.get("custom_id")

        if custom_id == "sticky:create":
            editor_cog = self.bot.get_cog("EmbedEditorCog")
            if editor_cog:
                script = EmbedScript(user_id=interaction.user.id)
                script.is_sticky_mode = True
                await editor_cog.launch_editor_for_script(interaction, script)
            else:
                await interaction.response.send_message("Embed Editor is currently unavailable.", ephemeral=True)

        elif custom_id == "sticky:toggle":
            channel_id = interaction.data["values"][0]
            if channel_id in self.cog.stickies:
                self.cog.stickies[channel_id]["is_active"] = not self.cog.stickies[channel_id]["is_active"]
                self.cog.save_data()

                is_active = self.cog.stickies[channel_id]["is_active"]
                status = "activated" if is_active else "deactivated"
                await interaction.response.send_message(f"Sticky message {status} for <#{channel_id}>.", ephemeral=True)
                self.refresh_ui()

                if is_active and self.cog.global_enabled:
                    channel = self.bot.get_channel(int(channel_id))
                    if channel:
                        await self.cog.send_sticky(channel)

                await self.update_dashboard_message(interaction)

        elif custom_id == "sticky:disable_all":
            await interaction.response.defer(ephemeral=True)
            deleted_count = await self.cog.disable_all(delete_existing=True)
            self.refresh_ui()
            await interaction.followup.send(
                f"All sticky messages are now disabled. Removed {deleted_count} posted sticky message(s).",
                ephemeral=True,
            )
            await self.update_dashboard_message(interaction)

        elif custom_id == "sticky:enable_all":
            await interaction.response.defer(ephemeral=True)
            enabled_count = await self.cog.enable_all()
            self.refresh_ui()
            await interaction.followup.send(
                f"Enabled {enabled_count} sticky configuration(s).",
                ephemeral=True,
            )
            await self.update_dashboard_message(interaction)

        elif custom_id == "sticky:flush_all":
            await interaction.response.defer(ephemeral=True)
            config_count, deleted_count = await self.cog.flush_all()
            self.refresh_ui()
            await interaction.followup.send(
                f"Flushed {config_count} sticky configuration(s) and removed {deleted_count} posted sticky message(s).",
                ephemeral=True,
            )
            await self.update_dashboard_message(interaction)

    async def update_dashboard_message(self, interaction: discord.Interaction):
        try:
            await interaction.message.edit(embed=self.cog.build_dashboard_embed(), view=self)
        except discord.errors.NotFound:
            pass


class StickyMessagesCog(commands.Cog, name="StickyMessagesCog"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.stickies: Dict[str, Dict[str, Any]] = {}
        self.global_enabled = True
        self.channel_locks: Dict[str, asyncio.Lock] = {}
        self.load_data()
        self.bot.add_listener(self.on_interaction_dashboard, "on_interaction")

    def get_lock(self, channel_id_str: str) -> asyncio.Lock:
        if channel_id_str not in self.channel_locks:
            self.channel_locks[channel_id_str] = asyncio.Lock()
        return self.channel_locks[channel_id_str]

    def load_data(self):
        if not os.path.exists(DATA_FILE):
            self.global_enabled = True
            self.stickies = {}
            return

        with open(DATA_FILE, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                self.global_enabled = True
                self.stickies = {}
                return

        if isinstance(data, dict) and "stickies" in data:
            settings = data.get("settings", {})
            self.global_enabled = bool(settings.get("enabled", True))
            self.stickies = data.get("stickies", {})
        elif isinstance(data, dict):
            self.global_enabled = True
            self.stickies = data
        else:
            self.global_enabled = True
            self.stickies = {}

    def save_data(self):
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        payload = {
            "settings": {
                "enabled": self.global_enabled,
            },
            "stickies": self.stickies,
        }
        temp_path = f"{DATA_FILE}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=4)
        os.replace(temp_path, DATA_FILE)

    def has_inactive_stickies(self) -> bool:
        return any(not data.get("is_active") for data in self.stickies.values())

    def configured_count(self) -> int:
        return len(self.stickies)

    def active_count(self) -> int:
        if not self.global_enabled:
            return 0
        return sum(1 for data in self.stickies.values() if data.get("is_active"))

    async def delete_last_sticky(self, channel_id_str: str, data: Dict[str, Any]) -> bool:
        last_msg_id = data.get("last_message_id")
        if not last_msg_id:
            return False

        try:
            channel = self.bot.get_channel(int(channel_id_str)) or await self.bot.fetch_channel(int(channel_id_str))
            message = await channel.fetch_message(int(last_msg_id))
            await message.delete()
            data["last_message_id"] = None
            return True
        except (discord.Forbidden, discord.NotFound, discord.HTTPException, ValueError):
            data["last_message_id"] = None
            return False

    async def disable_all(self, *, delete_existing: bool = False) -> int:
        self.global_enabled = False
        deleted_count = 0
        for channel_id_str, data in list(self.stickies.items()):
            data["is_active"] = False
            if delete_existing and await self.delete_last_sticky(channel_id_str, data):
                deleted_count += 1
        self.save_data()
        return deleted_count

    async def enable_all(self) -> int:
        self.global_enabled = True
        enabled_count = 0
        for channel_id_str, data in list(self.stickies.items()):
            if not data.get("is_active"):
                enabled_count += 1
            data["is_active"] = True

            channel = self.bot.get_channel(int(channel_id_str))
            if channel:
                self.bot.loop.create_task(self.send_sticky(channel))

        self.save_data()
        return enabled_count

    async def flush_all(self) -> Tuple[int, int]:
        config_count = len(self.stickies)
        deleted_count = 0
        for channel_id_str, data in list(self.stickies.items()):
            if await self.delete_last_sticky(channel_id_str, data):
                deleted_count += 1

        self.global_enabled = False
        self.stickies = {}
        self.save_data()
        return config_count, deleted_count

    async def send_sticky(self, channel: discord.TextChannel):
        if not self.global_enabled:
            return

        channel_id_str = str(channel.id)
        if channel_id_str not in self.stickies:
            return

        data = self.stickies[channel_id_str]
        if not data.get("is_active"):
            return

        script_data = data.get("script_data", {})
        script = EmbedScript.from_dict(script_data, user_id=self.bot.user.id, bot=self.bot)

        embeds = script.to_embeds()
        view = discord.ui.View()
        for button in script.buttons:
            view.add_item(
                discord.ui.Button(
                    label=button["label"],
                    url=button["url"],
                    style=discord.ButtonStyle.link,
                )
            )

        try:
            target = channel
            if not hasattr(target, "send"):
                target = self.bot.get_channel(channel.id) or await self.bot.fetch_channel(channel.id)
            msg = await target.send(content=script.content, embeds=embeds, view=view)
            self.stickies[channel_id_str]["last_message_id"] = msg.id
            self.save_data()
        except Exception as exc:
            channel_name = getattr(channel, "name", f"ID: {channel.id}")
            print(f"Failed to send sticky message in {channel_name}: {exc}")

    @commands.Cog.listener()
    async def on_ready(self):
        print("StickyMessagesCog: Refreshing stickies on startup...")
        if not self.global_enabled:
            print("StickyMessagesCog: Global sticky toggle is disabled.")
            return

        for channel_id_str, data in list(self.stickies.items()):
            if not data.get("is_active"):
                continue

            channel = self.bot.get_channel(int(channel_id_str))
            if not channel:
                continue

            last_msg_id = data.get("last_message_id")
            if last_msg_id:
                try:
                    last_message_in_channel = None
                    async for msg in channel.history(limit=1):
                        last_message_in_channel = msg

                    if last_message_in_channel and last_message_in_channel.id == last_msg_id:
                        continue

                    try:
                        old_msg = await channel.fetch_message(last_msg_id)
                        await old_msg.delete()
                    except discord.errors.NotFound:
                        pass
                except discord.errors.Forbidden:
                    pass

            await self.send_sticky(channel)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author == self.bot.user:
            return

        if not self.global_enabled:
            return

        channel_id_str = str(message.channel.id)
        if channel_id_str not in self.stickies:
            return

        data = self.stickies[channel_id_str]
        if not data.get("is_active"):
            return

        lock = self.get_lock(channel_id_str)
        async with lock:
            data = self.stickies[channel_id_str]
            last_msg_id = data.get("last_message_id")

            if last_msg_id:
                try:
                    old_msg = await message.channel.fetch_message(last_msg_id)
                    await old_msg.delete()
                except discord.errors.NotFound:
                    pass
                except discord.errors.Forbidden:
                    pass
                except Exception as exc:
                    print(f"Error deleting old sticky: {exc}")

            await self.send_sticky(message.channel)

    async def on_interaction_dashboard(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return

        custom_id = interaction.data.get("custom_id", "")
        if custom_id.startswith("sticky:"):
            view = StickyDashboardView(self.bot, self, interaction.user.id)
            await view.process_interaction(interaction)

    def save_sticky_config(self, channels: list, script: EmbedScript):
        script_data = script.to_dict()
        for channel in channels:
            channel_id_str = str(channel.id)
            self.stickies[channel_id_str] = {
                "is_active": True,
                "script_data": script_data,
                "last_message_id": None,
            }

        self.global_enabled = True
        self.save_data()

        for channel in channels:
            self.bot.loop.create_task(self.send_sticky(channel))

    def build_dashboard_embed(self):
        embed = discord.Embed(
            title="Sticky Messages Dashboard",
            description=(
                f"Global status: **{'Enabled' if self.global_enabled else 'Disabled'}**\n"
                f"Configured stickies: **{self.configured_count()}**\n"
                f"Active stickies: **{self.active_count()}**\n\n"
                "Use the global buttons to disable, enable, or flush every sticky at once."
            ),
            color=0xE8C1A0,
        )
        return embed

    async def launch_dashboard(self, interaction: discord.Interaction):
        view = StickyDashboardView(self.bot, self, interaction.user.id)
        await interaction.response.send_message(embed=self.build_dashboard_embed(), view=view, ephemeral=True)


async def setup(bot):
    await bot.add_cog(StickyMessagesCog(bot))
