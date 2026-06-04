import json
import os
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands

from utils.time_utils import parse_schedule_time


DATA_FILE = os.path.join("data", "onboarding.json")
DEFAULT_TIMEZONE = "Asia/Manila"
DEFAULT_WELCOME_CHANNEL_ID = 1468019695352545400
DEFAULT_SCAN_DAYS = 3
DELIVERY_CHANNEL = "channel"
DELIVERY_DM = "dm"
DELIVERY_SPLIT = "split"
TEMPLATE_SEPARATOR = "\n---\n"

DEFAULT_PUBLIC_MESSAGE_TEMPLATE = (
    "Welcome to the family, everyone! 🥳 We are so hyped to have you here in the GLO Creatorverse! 🚀 "
    "This is your space to connect, grow, and shine, so please introduce yourself below and let us know "
    "where you are joining from. ✨\n\n"
    "Make sure your very first stop is the "
    "https://discord.com/channels/1396983723651498146/1468019695352545400 because we have outlined "
    "everything you need to know right there. 🔗 All the essential info to get you started is waiting "
    "for you in that channel! You can also head over to get your Creator Discount Code here: "
    "https://discord.com/channels/1396983723651498146/1458238523579830445🙏🧥🙌💖☀️\n\n"
    "{mentions}"
)

DEFAULT_DM_MESSAGE_TEMPLATE = (
    "Welcome to the family, {member_display_name}! 🥳 We are so hyped to have you "
    "here in the GLO Creatorverse! 🚀"
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_template_block(raw_value: Any) -> List[str]:
    if isinstance(raw_value, list):
        templates = [str(item).strip() for item in raw_value if str(item).strip()]
        return templates or [DEFAULT_PUBLIC_MESSAGE_TEMPLATE]

    if not raw_value:
        return [DEFAULT_PUBLIC_MESSAGE_TEMPLATE]

    templates = []
    current_lines = []
    for line in str(raw_value).splitlines():
        if line.strip() == "---":
            template = "\n".join(current_lines).strip()
            if template:
                templates.append(template)
            current_lines = []
            continue
        current_lines.append(line)

    template = "\n".join(current_lines).strip()
    if template:
        templates.append(template)
    return templates or [DEFAULT_PUBLIC_MESSAGE_TEMPLATE]


def serialize_template_block(templates: List[str]) -> str:
    return TEMPLATE_SEPARATOR.join(template.strip() for template in templates if template.strip())


def ensure_public_mentions(template: str) -> str:
    template = template.strip()
    if "{mentions}" not in template:
        template = f"{template}\n\n{{mentions}}"
    return template


class OnboardingStore:
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

    def guild_state(self, guild_id: int) -> Dict[str, Any]:
        guilds = self.data.setdefault("guilds", {})
        state = guilds.setdefault(str(guild_id), {})
        state.setdefault("settings", {})
        state.setdefault("members", {})

        settings = state["settings"]
        settings.setdefault("enabled", False)
        settings.setdefault("welcome_channel_id", DEFAULT_WELCOME_CHANNEL_ID)
        settings.setdefault("scan_days", DEFAULT_SCAN_DAYS)
        settings.setdefault("timezone", DEFAULT_TIMEZONE)
        settings.setdefault("delivery_mode", DELIVERY_CHANNEL)

        old_template = settings.get("message_template") or settings.get("public_message_template")
        templates = parse_template_block(settings.get("public_message_templates") or old_template)
        templates = [ensure_public_mentions(template) for template in templates]
        settings["public_message_templates"] = templates
        selected_index = int(settings.get("selected_public_template_index", 0) or 0)
        selected_index = max(0, min(selected_index, len(templates) - 1))
        settings["selected_public_template_index"] = selected_index
        settings["public_message_template"] = templates[selected_index]
        settings.setdefault("dm_message_template", DEFAULT_DM_MESSAGE_TEMPLATE)
        settings.setdefault("default_posts", 1)
        settings.setdefault("last_report_checkpoint", None)
        settings.setdefault("report_channel_id", None)
        return state

    def settings(self, guild_id: int) -> Dict[str, Any]:
        return self.guild_state(guild_id)["settings"]

    def is_enabled(self, guild_id: int) -> bool:
        return bool(self.settings(guild_id).get("enabled", False))

    def set_enabled(self, guild_id: int, enabled: bool) -> None:
        self.settings(guild_id)["enabled"] = enabled
        self.save()

    def timezone(self, guild_id: int) -> ZoneInfo:
        timezone_name = self.settings(guild_id).get("timezone", DEFAULT_TIMEZONE)
        try:
            return ZoneInfo(timezone_name)
        except Exception:
            return ZoneInfo(DEFAULT_TIMEZONE)

    def today_key(self, guild_id: int, now: Optional[datetime] = None) -> str:
        local_now = now.astimezone(self.timezone(guild_id)) if now else datetime.now(self.timezone(guild_id))
        return local_now.strftime("%Y-%m-%d")

    def date_keys_for_scan(self, guild_id: int, now: Optional[datetime] = None) -> List[str]:
        settings = self.settings(guild_id)
        scan_days = int(settings.get("scan_days", DEFAULT_SCAN_DAYS))
        local_now = now.astimezone(self.timezone(guild_id)) if now else datetime.now(self.timezone(guild_id))
        return [(local_now.date() - timedelta(days=offset)).isoformat() for offset in range(scan_days + 1)]

    def join_date_key(self, member: discord.Member) -> Optional[str]:
        joined_at = getattr(member, "joined_at", None)
        if not joined_at:
            return None

        if joined_at.tzinfo is None:
            joined_at = joined_at.replace(tzinfo=timezone.utc)
        return joined_at.astimezone(self.timezone(member.guild.id)).date().isoformat()

    def record_member(self, member: discord.Member) -> bool:
        if getattr(member, "bot", False):
            return False

        join_date = self.join_date_key(member) or self.today_key(member.guild.id)
        state = self.guild_state(member.guild.id)
        members = state["members"]
        member_id = str(member.id)
        existing = members.get(member_id, {})

        if existing.get("welcomed_at"):
            return False

        joined_at = getattr(member, "joined_at", None)
        if joined_at is None:
            joined_at_value = existing.get("joined_at") or utc_now_iso()
        else:
            if joined_at.tzinfo is None:
                joined_at = joined_at.replace(tzinfo=timezone.utc)
            joined_at_value = joined_at.astimezone(timezone.utc).isoformat()

        members[member_id] = {
            "id": member.id,
            "username": str(member),
            "display_name": member.display_name,
            "mention": member.mention,
            "joined_at": joined_at_value,
            "join_date": join_date,
            "welcomed_at": None,
        }
        self.save()
        return True

    def scan_guild_members(self, guild: discord.Guild, now: Optional[datetime] = None) -> int:
        date_keys = set(self.date_keys_for_scan(guild.id, now))
        recorded = 0

        for member in guild.members:
            if getattr(member, "bot", False):
                continue
            if self.join_date_key(member) not in date_keys:
                continue
            if self.record_member(member):
                recorded += 1

        return recorded

    def pending_members(self, guild_id: int, date_key: str) -> List[Dict[str, Any]]:
        state = self.guild_state(guild_id)
        members = []
        for member in state["members"].values():
            if member.get("join_date") == date_key and not member.get("welcomed_at"):
                members.append(member)
        return sorted(members, key=lambda item: item.get("joined_at", ""))

    def pending_groups(
        self,
        guild: discord.Guild,
        now: Optional[datetime] = None,
        scan: bool = True,
    ) -> "OrderedDict[str, List[Dict[str, Any]]]":
        if scan:
            self.scan_guild_members(guild, now)

        groups: "OrderedDict[str, List[Dict[str, Any]]]" = OrderedDict()
        for date_key in self.date_keys_for_scan(guild.id, now):
            groups[date_key] = self.pending_members(guild.id, date_key)
        return groups

    def latest_pending_group(
        self,
        guild: discord.Guild,
        now: Optional[datetime] = None,
        scan: bool = True,
    ) -> tuple[Optional[str], List[Dict[str, Any]]]:
        for date_key, members in self.pending_groups(guild, now, scan).items():
            if members:
                return date_key, members
        return None, []

    def mark_welcomed(self, guild_id: int, member_ids: List[int]) -> None:
        state = self.guild_state(guild_id)
        now = utc_now_iso()
        for member_id in member_ids:
            member = state["members"].get(str(member_id))
            if member:
                member["welcomed_at"] = now
        self.save()

    def update_settings(
        self,
        guild_id: int,
        channel_id: int,
        timezone_name: str,
        delivery_mode: str,
        public_message_templates: List[str],
        dm_message_template: str,
        report_channel_id: Optional[int],
    ) -> None:
        settings = self.settings(guild_id)
        templates = [ensure_public_mentions(template) for template in public_message_templates]
        if not templates:
            templates = [DEFAULT_PUBLIC_MESSAGE_TEMPLATE]
        selected_index = int(settings.get("selected_public_template_index", 0) or 0)
        selected_index = max(0, min(selected_index, len(templates) - 1))

        settings["welcome_channel_id"] = channel_id
        settings["scan_days"] = DEFAULT_SCAN_DAYS
        settings["timezone"] = timezone_name
        settings["delivery_mode"] = delivery_mode
        settings["public_message_templates"] = templates
        settings["selected_public_template_index"] = selected_index
        settings["public_message_template"] = templates[selected_index]
        settings["dm_message_template"] = dm_message_template.strip() or DEFAULT_DM_MESSAGE_TEMPLATE
        settings["report_channel_id"] = report_channel_id
        self.save()

    def public_templates(self, guild_id: int) -> List[str]:
        settings = self.settings(guild_id)
        templates = parse_template_block(settings.get("public_message_templates"))
        templates = [ensure_public_mentions(template) for template in templates]
        if not templates:
            templates = [DEFAULT_PUBLIC_MESSAGE_TEMPLATE]
        return templates

    def selected_public_template_index(self, guild_id: int) -> int:
        templates = self.public_templates(guild_id)
        settings = self.settings(guild_id)
        selected_index = int(settings.get("selected_public_template_index", 0) or 0)
        return max(0, min(selected_index, len(templates) - 1))

    def selected_public_template(self, guild_id: int, template_index: Optional[int] = None) -> str:
        templates = self.public_templates(guild_id)
        if template_index is None:
            template_index = self.selected_public_template_index(guild_id)
        template_index = max(0, min(int(template_index), len(templates) - 1))
        return templates[template_index]

    def set_selected_public_template_index(self, guild_id: int, template_index: int) -> None:
        templates = self.public_templates(guild_id)
        template_index = max(0, min(template_index, len(templates) - 1))
        settings = self.settings(guild_id)
        settings["selected_public_template_index"] = template_index
        settings["public_message_template"] = templates[template_index]
        self.save()


class WeeklyReportOptionsView(discord.ui.View):
    def __init__(self, cog: "OnboardingCog"):
        super().__init__(timeout=300)
        self.cog = cog

    @discord.ui.button(label="Download Private CSV", style=discord.ButtonStyle.blurple)
    async def download_csv_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await self.cog.run_weekly_report(interaction, channel=None)

    @discord.ui.button(label="Post to Public Channel", style=discord.ButtonStyle.green)
    async def post_channel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        settings = self.cog.store.settings(interaction.guild_id)
        default_id = settings.get("report_channel_id") or interaction.channel_id
        await interaction.response.send_modal(WeeklyReportModal(self.cog, default_channel_id=default_id))


class WeeklyReportModal(discord.ui.Modal, title="Run Weekly Growth Report"):
    channel_id = discord.ui.TextInput(
        label="Post publicly to Channel ID",
        required=False,
        max_length=24,
        placeholder="Enter channel ID, or leave blank for this channel."
    )

    def __init__(self, cog: "OnboardingCog", default_channel_id: Optional[int] = None):
        super().__init__()
        self.cog = cog
        if default_channel_id:
            self.channel_id.default = str(default_channel_id)
        else:
            settings = cog.store.settings(cog.bot.guilds[0].id) if cog.bot.guilds else {}
            saved_id = settings.get("report_channel_id") if settings else None
            if saved_id:
                self.channel_id.default = str(saved_id)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        target_channel_id = str(self.channel_id.value).strip()
        if target_channel_id:
            try:
                channel_id = int(target_channel_id)
                channel = interaction.guild.get_channel(channel_id) or await interaction.guild.fetch_channel(channel_id)
            except Exception:
                await interaction.followup.send("❌ Invalid channel ID. Please provide a valid channel ID.", ephemeral=True)
                return
        else:
            channel = interaction.channel

        if not channel or not hasattr(channel, "send"):
            await interaction.followup.send("❌ I cannot find or access that channel, or it cannot receive messages.", ephemeral=True)
            return

        settings = self.cog.store.settings(interaction.guild_id)
        settings["report_channel_id"] = channel.id
        self.cog.store.save()

        await self.cog.run_weekly_report(interaction, channel)


class OnboardingSettingsModal(discord.ui.Modal, title="Onboarding Settings"):
    channel_id = discord.ui.TextInput(label="Welcome lands in channel ID", required=True, max_length=24)
    timezone_name = discord.ui.TextInput(label="Timezone", required=True, max_length=64)
    delivery_mode = discord.ui.TextInput(label="Default delivery: channel, dm, split", required=True, max_length=7)
    public_message_template = discord.ui.TextInput(
        label="Public templates, separate with ---",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=4000,
    )
    dm_message_template = discord.ui.TextInput(
        label="DM welcome message",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1800,
    )

    def __init__(self, cog: "OnboardingCog", view: "OnboardingDashboardView"):
        super().__init__()
        self.cog = cog
        self.view = view
        settings = cog.store.settings(view.guild_id)
        self.channel_id.default = str(settings.get("welcome_channel_id", DEFAULT_WELCOME_CHANNEL_ID))
        self.timezone_name.default = settings.get("timezone", DEFAULT_TIMEZONE)
        self.delivery_mode.default = settings.get("delivery_mode", DELIVERY_CHANNEL)
        self.public_message_template.default = serialize_template_block(cog.store.public_templates(view.guild_id))
        self.dm_message_template.default = settings.get("dm_message_template", DEFAULT_DM_MESSAGE_TEMPLATE)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            channel_id = int(str(self.channel_id.value).strip())
            timezone_name = str(self.timezone_name.value).strip()
            ZoneInfo(timezone_name)
        except ValueError:
            await interaction.response.send_message("Channel ID must be a number.", ephemeral=True)
            return
        except Exception:
            await interaction.response.send_message("Timezone is invalid. Example: Asia/Manila", ephemeral=True)
            return

        delivery_mode = str(self.delivery_mode.value).strip().lower()
        if delivery_mode not in {DELIVERY_CHANNEL, DELIVERY_DM, DELIVERY_SPLIT}:
            await interaction.response.send_message("Default delivery must be `channel`, `dm`, or `split`.", ephemeral=True)
            return

        public_templates = parse_template_block(str(self.public_message_template.value))

        settings = self.cog.store.settings(interaction.guild_id)
        report_channel_id = settings.get("report_channel_id")

        self.cog.store.update_settings(
            interaction.guild_id,
            channel_id,
            timezone_name,
            delivery_mode,
            public_templates,
            str(self.dm_message_template.value).strip(),
            report_channel_id,
        )
        self.view.delivery_mode = delivery_mode
        self.view.selected_template_index = self.cog.store.selected_public_template_index(interaction.guild_id)
        await self.view.refresh(interaction, notice="Onboarding settings saved.")


class OnboardingScheduleModal(discord.ui.Modal, title="Schedule Latest Welcome"):
    date = discord.ui.TextInput(label="Date (YYYY-MM-DD)", required=True, max_length=10)
    time = discord.ui.TextInput(label="Time (HH:MM)", required=True, max_length=5)
    period = discord.ui.TextInput(label="AM or PM", required=True, max_length=2)

    def __init__(self, cog: "OnboardingCog", view: "OnboardingDashboardView"):
        super().__init__()
        self.cog = cog
        self.view = view
        self.date.default = cog.store.today_key(view.guild_id)
        self.time.default = "07:00"
        self.period.default = "PM"

    async def on_submit(self, interaction: discord.Interaction):
        if not self.cog.store.is_enabled(interaction.guild_id):
            await interaction.response.send_message("Enable onboarding before scheduling welcome posts.", ephemeral=True)
            return

        settings = self.cog.store.settings(interaction.guild_id)
        period = str(self.period.value).strip().upper()
        if period not in {"AM", "PM"}:
            await interaction.response.send_message("Period must be AM or PM.", ephemeral=True)
            return

        try:
            run_time = parse_schedule_time(
                str(self.date.value).strip(),
                str(self.time.value).strip(),
                period,
                settings.get("timezone", DEFAULT_TIMEZONE),
            )
        except Exception as exc:
            await interaction.response.send_message(f"Could not schedule onboarding: {exc}", ephemeral=True)
            return

        if run_time <= datetime.now(timezone.utc).astimezone(run_time.tzinfo):
            await interaction.response.send_message("Choose a future date and time.", ephemeral=True)
            return

        job_id = self.cog.schedule_welcome(guild_id=interaction.guild_id, run_time=run_time)
        await self.view.refresh(
            interaction,
            notice=f"Scheduled latest onboarding group for <t:{int(run_time.timestamp())}:F>. Job ID: {job_id}",
        )


class OnboardingGroupSelect(discord.ui.Select):
    def __init__(self, view: "OnboardingDashboardView"):
        self.dashboard_view = view
        groups = view.group_snapshot()
        options = []
        for date_key, members in groups.items():
            label = view.cog.group_label(view.guild_id, date_key)
            options.append(
                discord.SelectOption(
                    label=f"{label} ({len(members)})",
                    value=date_key,
                    description=f"{len(members)} unwelcomed member(s)",
                    default=date_key == view.selected_date_key,
                )
            )

        super().__init__(
            placeholder="Select onboarding group...",
            min_values=1,
            max_values=1,
            options=options,
            row=2,
        )

    async def callback(self, interaction: discord.Interaction):
        self.dashboard_view.selected_date_key = self.values[0]
        await self.dashboard_view.refresh(interaction, notice=f"Selected {self.dashboard_view.cog.group_label(interaction.guild_id, self.values[0])}.")


class OnboardingTemplateSelect(discord.ui.Select):
    def __init__(self, view: "OnboardingDashboardView"):
        self.dashboard_view = view
        templates = view.cog.store.public_templates(view.guild_id)
        options = []
        for index, template in enumerate(templates[:25]):
            first_line = next((line.strip() for line in template.splitlines() if line.strip()), f"Template {index + 1}")
            options.append(
                discord.SelectOption(
                    label=f"Template {index + 1}",
                    value=str(index),
                    description=first_line[:100],
                    default=index == view.selected_template_index,
                )
            )

        super().__init__(
            placeholder="Select public welcome template...",
            min_values=1,
            max_values=1,
            options=options,
            row=4,
        )

    async def callback(self, interaction: discord.Interaction):
        self.dashboard_view.selected_template_index = int(self.values[0])
        self.dashboard_view.cog.store.set_selected_public_template_index(
            interaction.guild_id,
            self.dashboard_view.selected_template_index,
        )
        await self.dashboard_view.refresh(interaction, notice=f"Selected public template {self.dashboard_view.selected_template_index + 1}.")


class OnboardingDashboardView(discord.ui.View):
    def __init__(self, bot: commands.Bot, cog: "OnboardingCog", guild_id: int, user_id: int):
        super().__init__(timeout=900)
        self.bot = bot
        self.cog = cog
        self.guild_id = guild_id
        self.user_id = user_id
        settings = cog.store.settings(guild_id)
        self.delivery_mode = settings.get("delivery_mode", DELIVERY_CHANNEL)
        self.selected_date_key: Optional[str] = None
        self.selected_template_index = cog.store.selected_public_template_index(guild_id)
        self.refresh_ui_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This onboarding panel belongs to another moderator.", ephemeral=True)
            return False
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("You need Manage Messages to use onboarding controls.", ephemeral=True)
            return False
        return True

    def group_snapshot(self) -> "OrderedDict[str, List[Dict[str, Any]]]":
        guild = self.bot.get_guild(self.guild_id)
        if not guild:
            return OrderedDict((date_key, []) for date_key in self.cog.store.date_keys_for_scan(self.guild_id))
        return self.cog.store.pending_groups(guild, scan=True)

    def refresh_ui_components(self):
        self.clear_items()
        if self.delivery_mode == DELIVERY_CHANNEL:
            self.delivery_button.label = "Use DM"
        elif self.delivery_mode == DELIVERY_DM:
            self.delivery_button.label = "Use Split"
        else:
            self.delivery_button.label = "Use Channel"
        self.add_item(self.scan_button)
        self.add_item(self.toggle_button)
        self.add_item(self.delivery_button)
        self.add_item(self.send_latest_button)
        self.add_item(self.send_selected_button)
        self.add_item(self.monday_report_button)
        self.add_item(self.make_checkpoint_button)
        self.add_item(OnboardingGroupSelect(self))
        self.add_item(self.schedule_button)
        self.add_item(self.settings_button)
        self.add_item(self.preview_button)
        self.add_item(OnboardingTemplateSelect(self))

    @discord.ui.button(label="Scan / Refresh", style=discord.ButtonStyle.gray, row=0)
    async def scan_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.refresh(interaction, notice="Scan complete.")

    @discord.ui.button(label="Enable / Disable", style=discord.ButtonStyle.blurple, row=0)
    async def toggle_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        enabled = not self.cog.store.is_enabled(interaction.guild_id)
        self.cog.store.set_enabled(interaction.guild_id, enabled)
        status = "enabled" if enabled else "disabled"
        await self.cog.log_action(interaction.guild_id, "Onboarding Toggled", f"{interaction.user.mention} {status} onboarding.")
        await self.refresh(interaction, notice=f"Onboarding is now **{status}**.")

    @discord.ui.button(label="Use Channel", style=discord.ButtonStyle.blurple, row=0)
    async def delivery_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.delivery_mode == DELIVERY_CHANNEL:
            self.delivery_mode = DELIVERY_DM
        elif self.delivery_mode == DELIVERY_DM:
            self.delivery_mode = DELIVERY_SPLIT
        else:
            self.delivery_mode = DELIVERY_CHANNEL
        await self.refresh(interaction, notice=f"This run will use **{self.delivery_mode}** delivery.")

    @discord.ui.button(label="Send Latest Group", style=discord.ButtonStyle.green, row=1)
    async def send_latest_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        result = await self.cog.send_latest_group(interaction.guild, self.delivery_mode, self.selected_template_index)
        await interaction.followup.send(result, ephemeral=True)

    @discord.ui.button(label="Send Selected Group", style=discord.ButtonStyle.green, row=1)
    async def send_selected_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        if not self.selected_date_key:
            await interaction.followup.send("Select a group first.", ephemeral=True)
            return
        result = await self.cog.send_group(
            interaction.guild,
            self.selected_date_key,
            self.delivery_mode,
            template_index=self.selected_template_index,
        )
        await interaction.followup.send(result, ephemeral=True)

    @discord.ui.button(label="Monday Weekly Report", style=discord.ButtonStyle.blurple, row=1)
    async def monday_report_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=discord.Embed(
                title="📊 Weekly Onboarding Growth Report Options",
                description="Choose whether to download the report privately as a CSV, or post it publicly to a selected channel with comprehensive statistics and a breakdown.",
                color=0xE8C1A0
            ),
            view=WeeklyReportOptionsView(self.cog),
            ephemeral=True
        )

    @discord.ui.button(label="Make Checkpoint", style=discord.ButtonStyle.gray, row=1)
    async def make_checkpoint_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        checkpoint_time = datetime.now(timezone.utc)
        settings = self.cog.store.settings(interaction.guild_id)
        settings["last_report_checkpoint"] = checkpoint_time.isoformat()
        self.cog.store.save()
        
        # Log to audit logs
        tz = self.cog.store.timezone(interaction.guild_id)
        local_time_str = checkpoint_time.astimezone(tz).strftime('%Y-%m-%d %I:%M %p %Z')
        await self.cog.log_action(
            interaction.guild_id,
            "Reporting Checkpoint Created",
            f"{interaction.user.mention} set a reporting checkpoint at {local_time_str}."
        )
        
        # Respond and refresh dashboard
        await self.refresh(interaction, notice=f"✅ Checkpoint created at **{local_time_str}**. Next report starts counting from here.")

    @discord.ui.button(label="Schedule Latest Group", style=discord.ButtonStyle.blurple, row=3)
    async def schedule_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(OnboardingScheduleModal(self.cog, self))

    @discord.ui.button(label="Settings", style=discord.ButtonStyle.gray, row=3)
    async def settings_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(OnboardingSettingsModal(self.cog, self))

    @discord.ui.button(label="Preview Message", style=discord.ButtonStyle.gray, row=3)
    async def preview_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        groups = self.cog.store.pending_groups(interaction.guild, scan=True)
        date_key = self.selected_date_key
        members = groups.get(date_key, []) if date_key else []
        if not members:
            date_key, members = self.cog.store.latest_pending_group(interaction.guild, scan=False)

        if not date_key or not members:
            sample_member = {
                "id": interaction.user.id,
                "username": str(interaction.user),
                "display_name": interaction.user.display_name,
                "mention": interaction.user.mention,
            }
            date_key = self.cog.store.today_key(interaction.guild_id)
            members = [sample_member]

        content = self.cog.preview_message(
            interaction.guild_id,
            date_key,
            members,
            self.delivery_mode,
            self.selected_template_index,
        )
        await interaction.response.send_message(content[:2000], ephemeral=True)

    def build_embed(self, notice: Optional[str] = None) -> discord.Embed:
        groups = self.group_snapshot()
        settings = self.cog.store.settings(self.guild_id)
        latest_date, latest_members = self.cog.store.latest_pending_group(
            self.bot.get_guild(self.guild_id),
            scan=False,
        ) if self.bot.get_guild(self.guild_id) else (None, [])
        channel_id = settings.get("welcome_channel_id", DEFAULT_WELCOME_CHANNEL_ID)
        enabled = self.cog.store.is_enabled(self.guild_id)
        template_count = len(self.cog.store.public_templates(self.guild_id))
        
        checkpoint_val = settings.get("last_report_checkpoint")
        tz = self.cog.store.timezone(self.guild_id)
        if checkpoint_val:
            try:
                dt = datetime.fromisoformat(checkpoint_val)
                checkpoint_str = dt.astimezone(tz).strftime('%Y-%m-%d %I:%M %p %Z')
            except Exception:
                checkpoint_str = "Invalid format"
        else:
            checkpoint_str = "None (will use 7-day fallback on next report run)"

        if self.selected_date_key not in groups:
            self.selected_date_key = latest_date

        description = (
            f"Status: **{'Enabled' if enabled else 'Disabled'}**\n"
            f"Delivery for this run: **{self.delivery_mode}**\n"
            f"Default delivery: **{settings.get('delivery_mode', DELIVERY_CHANNEL)}**\n"
            f"Public welcome channel: <#{channel_id}>\n"
            f"Public template: **{self.selected_template_index + 1} of {template_count}**\n"
            f"Scan window: **Today through {settings.get('scan_days', DEFAULT_SCAN_DAYS)} day(s) ago**\n"
            f"Timezone: **{settings.get('timezone', DEFAULT_TIMEZONE)}**\n"
            f"Report Checkpoint: **{checkpoint_str}**\n"
            f"Latest group: **{self.cog.group_label(self.guild_id, latest_date) if latest_date else 'None'}** "
            f"({len(latest_members)} member(s))\n\n"
            "Scanning is safe: members are only marked welcomed after a successful channel post or successful DM."
        )
        if notice:
            description = f"{notice}\n\n{description}"

        embed = discord.Embed(
            title="GLO Creatorverse Onboarding",
            description=description,
            color=0xE8C1A0,
        )

        for date_key, members in groups.items():
            label = self.cog.group_label(self.guild_id, date_key)
            if members:
                preview = "\n".join(
                    f"- {member.get('display_name') or member.get('username')} (`{member.get('id')}`)"
                    for member in members[:8]
                )
                if len(members) > 8:
                    preview += f"\n- ...and {len(members) - 8} more"
            else:
                preview = "No unwelcomed members."
            embed.add_field(name=f"{label} - {len(members)}", value=preview, inline=False)

        return embed

    async def refresh(self, interaction: discord.Interaction, notice: Optional[str] = None):
        self.refresh_ui_components()
        embed = self.build_embed(notice=notice)
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)


class OnboardingCog(commands.Cog, name="OnboardingCog"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.store = OnboardingStore()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not self.store.is_enabled(member.guild.id):
            return

        if self.store.record_member(member):
            print(f"Onboarding: recorded {member} ({member.id}) for guild {member.guild.id}")

    def schedule_welcome(self, guild_id: int, run_time: datetime, *legacy_args: Any, **legacy_kwargs: Any) -> str:
        scheduler_cog = self.bot.get_cog("SchedulerCog")
        if not scheduler_cog:
            raise RuntimeError("SchedulerCog is unavailable.")

        job = scheduler_cog.scheduler.add_job(
            self.execute_scheduled_welcome,
            "date",
            run_date=run_time,
            args=[guild_id],
        )
        return job.id

    async def execute_scheduled_welcome(self, guild_id: int, *legacy_args: Any):
        guild = self.bot.get_guild(guild_id)
        if not guild:
            print(f"Onboarding scheduled welcome: guild {guild_id} is unavailable.")
            return

        settings = self.store.settings(guild_id)
        result = await self.send_latest_group(guild, settings.get("delivery_mode", DELIVERY_CHANNEL))
        print(f"Onboarding scheduled welcome: {result}")

    async def log_action(self, guild_id: int, title: str, description: str):
        audit_cog = self.bot.get_cog("AuditLogsCog")
        if audit_cog:
            await audit_cog.log_event(guild_id, title, description, color=0xE8C1A0)

    async def launch_dashboard(self, interaction: discord.Interaction):
        view = OnboardingDashboardView(self.bot, self, interaction.guild_id, interaction.user.id)
        await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)

    def group_label(self, guild_id: int, date_key: Optional[str]) -> str:
        if not date_key:
            return "None"

        keys = self.store.date_keys_for_scan(guild_id)
        if date_key in keys:
            offset = keys.index(date_key)
            if offset == 0:
                return "Today"
            if offset == 1:
                return "1 day ago"
            return f"{offset} days ago"
        return date_key

    def _format_template(self, template: str, values: Dict[str, Any], fallback: str) -> str:
        try:
            return template.format(**values)
        except (KeyError, ValueError):
            return fallback.format(**values)

    def build_public_message(self, template: str, members: List[Dict[str, Any]], join_day: str) -> str:
        if "{mentions}" not in template:
            template = f"{template}\n\n{{mentions}}"

        values = {
            "mentions": " ".join(f"<@{member['id']}>" for member in members),
            "count": len(members),
            "join_day": join_day,
        }
        return self._format_template(template, values, DEFAULT_PUBLIC_MESSAGE_TEMPLATE)

    def build_dm_message(
        self,
        template: str,
        member: Dict[str, Any],
        group_members: List[Dict[str, Any]],
        join_day: str,
    ) -> str:
        values = {
            "member_mention": f"<@{member['id']}>",
            "member_name": member.get("username") or member.get("display_name") or str(member["id"]),
            "member_display_name": member.get("display_name") or member.get("username") or str(member["id"]),
            "count": len(group_members),
            "join_day": join_day,
        }
        return self._format_template(template, values, DEFAULT_DM_MESSAGE_TEMPLATE)

    def preview_message(
        self,
        guild_id: int,
        date_key: str,
        members: List[Dict[str, Any]],
        delivery_mode: str,
        template_index: Optional[int] = None,
    ) -> str:
        settings = self.store.settings(guild_id)
        join_day = self.group_label(guild_id, date_key)
        dm_msg = self.build_dm_message(
            settings.get("dm_message_template", DEFAULT_DM_MESSAGE_TEMPLATE),
            members[0],
            members,
            join_day,
        )
        pub_msg = self.build_public_message(
            self.store.selected_public_template(guild_id, template_index),
            members,
            join_day,
        )

        if delivery_mode == DELIVERY_DM:
            return dm_msg
        elif delivery_mode == DELIVERY_SPLIT:
            return f"**--- Public Post Preview ---**\n{pub_msg}\n\n**--- DM Preview ---**\n{dm_msg}"
        return pub_msg

    def split_members_for_posts(
        self,
        members: List[Dict[str, Any]],
        template: str,
        join_day: str,
    ) -> List[List[Dict[str, Any]]]:
        chunks = []
        current = []
        for member in members:
            candidate = current + [member]
            if current and len(self.build_public_message(template, candidate, join_day)) > 2000:
                chunks.append(current)
                current = [member]
            else:
                current = candidate

        if current:
            chunks.append(current)
        return chunks

    async def send_latest_group(
        self,
        guild: discord.Guild,
        delivery_mode: str,
        template_index: Optional[int] = None,
    ) -> str:
        date_key, members = self.store.latest_pending_group(guild, scan=True)
        if not date_key or not members:
            return "No unwelcomed members found in the last 3 days."
        return await self.send_group(
            guild,
            date_key,
            delivery_mode,
            members=members,
            scan=False,
            template_index=template_index,
        )

    async def send_group(
        self,
        guild: discord.Guild,
        date_key: str,
        delivery_mode: str,
        members: Optional[List[Dict[str, Any]]] = None,
        scan: bool = True,
        template_index: Optional[int] = None,
    ) -> str:
        settings = self.store.settings(guild.id)
        if not self.store.is_enabled(guild.id):
            return "Onboarding is disabled. Enable it from the Onboarding panel before sending welcome messages."

        if scan:
            self.store.scan_guild_members(guild)
        pending = members if members is not None else self.store.pending_members(guild.id, date_key)
        if not pending:
            return f"No unwelcomed members found for {self.group_label(guild.id, date_key)}."

        if delivery_mode == DELIVERY_SPLIT:
            channel_res = await self.send_channel_group(guild, date_key, pending, template_index)
            dm_res = await self.send_dm_group(guild, date_key, pending)
            return f"{channel_res} | {dm_res}"
        elif delivery_mode == DELIVERY_DM:
            return await self.send_dm_group(guild, date_key, pending)
        return await self.send_channel_group(guild, date_key, pending, template_index)

    async def send_channel_group(
        self,
        guild: discord.Guild,
        date_key: str,
        members: List[Dict[str, Any]],
        template_index: Optional[int] = None,
    ) -> str:
        settings = self.store.settings(guild.id)
        channel_id = int(settings.get("welcome_channel_id", DEFAULT_WELCOME_CHANNEL_ID))
        try:
            channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
        except (discord.Forbidden, discord.NotFound):
            return f"Welcome channel `{channel_id}` could not be found or the bot cannot access it."
        except discord.HTTPException as exc:
            return f"Discord rejected the channel lookup for `{channel_id}`: {exc}"

        if not channel or not hasattr(channel, "send"):
            return f"Welcome channel `{channel_id}` could not receive messages."

        template = self.store.selected_public_template(guild.id, template_index)
        join_day = self.group_label(guild.id, date_key)
        chunks = self.split_members_for_posts(members, template, join_day)
        welcomed_ids = []

        try:
            for chunk in chunks:
                content = self.build_public_message(template, chunk, join_day)
                if len(content) > 2000:
                    return "The public welcome message is too long for Discord after adding mentions."
                await channel.send(
                    content=content,
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )
                welcomed_ids.extend(member["id"] for member in chunk)
        except discord.HTTPException as exc:
            return f"Discord rejected the welcome post before all members could be marked: {exc}"
        except discord.Forbidden:
            return "The bot does not have permission to send the welcome post."

        self.store.mark_welcomed(guild.id, welcomed_ids)
        await self.log_action(
            guild.id,
            "Onboarding Welcome Sent",
            f"Sent {len(chunks)} public welcome post(s) and tagged {len(welcomed_ids)} new member(s).",
        )
        return f"Sent {len(chunks)} public welcome post(s) and tagged {len(welcomed_ids)} new member(s)."

    async def send_dm_group(self, guild: discord.Guild, date_key: str, members: List[Dict[str, Any]]) -> str:
        settings = self.store.settings(guild.id)
        template = settings.get("dm_message_template", DEFAULT_DM_MESSAGE_TEMPLATE)
        join_day = self.group_label(guild.id, date_key)
        sent_ids = []
        failed = []

        for member_record in members:
            member = guild.get_member(int(member_record["id"]))
            if not member:
                failed.append(str(member_record["id"]))
                continue

            content = self.build_dm_message(template, member_record, members, join_day)
            if len(content) > 2000:
                failed.append(member.display_name)
                continue

            try:
                await member.send(content)
                sent_ids.append(member.id)
            except Exception:
                failed.append(member.display_name)

        if sent_ids:
            self.store.mark_welcomed(guild.id, sent_ids)

        await self.log_action(
            guild.id,
            "Onboarding DM Welcome Sent",
            f"Sent {len(sent_ids)} DM welcome message(s). Failed: {len(failed)}.",
        )

        result = f"Sent {len(sent_ids)} DM welcome message(s)."
        if failed:
            result += f" Failed to DM {len(failed)} member(s): {', '.join(failed[:10])}."
        return result

    async def send_welcome_batch(
        self,
        guild_id: int,
        date_key: Optional[str] = None,
        post_count: Optional[int] = None,
    ) -> str:
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return f"Guild `{guild_id}` is unavailable."

        settings = self.store.settings(guild_id)
        if date_key:
            return await self.send_group(guild, date_key, settings.get("delivery_mode", DELIVERY_CHANNEL))
        return await self.send_latest_group(guild, settings.get("delivery_mode", DELIVERY_CHANNEL))

    async def run_weekly_report(self, interaction: discord.Interaction, channel: Optional[discord.abc.Messageable] = None):
        # Scan first to ensure we have up-to-date data
        guild = interaction.guild
        if not guild:
            await interaction.followup.send("Guild not found.", ephemeral=True)
            return

        self.store.scan_guild_members(guild)
        
        settings = self.store.settings(interaction.guild_id)
        checkpoint_str = settings.get("last_report_checkpoint")
        tz = self.store.timezone(interaction.guild_id)
        current_run_time = datetime.now(timezone.utc)
        
        if checkpoint_str:
            try:
                checkpoint_dt = datetime.fromisoformat(checkpoint_str)
                period_desc = "Stateful Checkpoint-based"
            except Exception:
                checkpoint_dt = current_run_time - timedelta(days=7)
                period_desc = "Past 7 Days (Fallback)"
        else:
            checkpoint_dt = current_run_time - timedelta(days=7)
            period_desc = "Past 7 Days (Fallback)"
            
        start_local = checkpoint_dt.astimezone(tz)
        end_local = current_run_time.astimezone(tz)
        
        start_str = start_local.strftime('%Y-%m-%d %I:%M %p %Z')
        end_str = end_local.strftime('%Y-%m-%d %I:%M %p %Z')
        
        state = self.store.guild_state(interaction.guild_id)
        members = state.get("members", {})
        
        report_members = []
        welcomed_count = 0
        pending_count = 0
        daily_counts = {}
        
        for m in members.values():
            joined_at_str = m.get("joined_at")
            if not joined_at_str:
                continue
            try:
                joined_at_dt = datetime.fromisoformat(joined_at_str)
            except Exception:
                continue
                
            if checkpoint_dt < joined_at_dt <= current_run_time:
                report_members.append(m)
                if m.get("welcomed_at"):
                    welcomed_count += 1
                else:
                    pending_count += 1
                
                local_joined = joined_at_dt.astimezone(tz)
                join_date_str = local_joined.strftime('%Y-%m-%d')
                daily_counts[join_date_str] = daily_counts.get(join_date_str, 0) + 1
                
        if not report_members:
            # Advance checkpoint even when empty to mark this period as checked
            settings["last_report_checkpoint"] = current_run_time.isoformat()
            self.store.save()
            await interaction.followup.send(
                f"No new members found for reporting period **{start_str}** to **{end_str}** ({period_desc}).\n"
                f"Checkpoint has been advanced to **{end_str}**.",
                ephemeral=True
            )
            return
            
        # Sort by join time
        report_members.sort(key=lambda x: x.get("joined_at", ""))
        
        # Build daily breakdown message
        breakdown_lines = []
        for day in sorted(daily_counts.keys()):
            breakdown_lines.append(f"- **{day}**: {daily_counts[day]} new members")
        breakdown_msg = "\n".join(breakdown_lines)
        
        # Determine peak day
        peak_day = max(daily_counts, key=daily_counts.get)
        peak_count = daily_counts[peak_day]
        
        # Generate CSV in memory
        import io
        import csv
        
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        writer.writerow(["Discord ID", "Username", "Display Name", "Join Date", "Joined At", "Welcomed At"])
        for m in report_members:
            writer.writerow([
                m.get("id"),
                m.get("username"),
                m.get("display_name"),
                m.get("join_date"),
                m.get("joined_at"),
                m.get("welcomed_at") or "Not Welcomed"
            ])
            
        csv_data = csv_buffer.getvalue()
        csv_buffer.close()
        
        # Name it with the date
        report_date_str = end_local.strftime('%Y-%m-%d')
        filename = f"weekly_report_{report_date_str}.csv"
        
        # Persist report in data/reports directory
        reports_dir = os.path.join("data", "reports")
        os.makedirs(reports_dir, exist_ok=True)
        persisted_path = os.path.join(reports_dir, filename)
        with open(persisted_path, "w", encoding="utf-8", newline="") as f:
            f.write(csv_data)
            
        # Create discord file attachment
        discord_file = discord.File(
            fp=io.BytesIO(csv_data.encode('utf-8')),
            filename=filename
        )
        
        # Embed/Message formatting
        embed = discord.Embed(
            title="📊 Monday Weekly Onboarding Report",
            description=(
                f"**Reporting Period:** {start_str} to {end_str}\n"
                f"**Type:** {period_desc}\n\n"
                f"👥 **Total New Members:** {len(report_members)}\n"
                f"✅ **Welcomed:** {welcomed_count}\n"
                f"⏳ **Pending Welcome:** {pending_count}\n"
                f"🔥 **Peak Signup Day:** {peak_day} ({peak_count} signups)\n\n"
                f"📁 A copy of the CSV was saved to `{persisted_path}`."
            ),
            color=0xE8C1A0
        )
        if breakdown_msg:
            embed.add_field(name="📅 Daily Registration Breakdown", value=breakdown_msg, inline=False)
            
        # Save checkpoint to the store
        settings["last_report_checkpoint"] = current_run_time.isoformat()
        self.store.save()
            
        if channel:
            # Send publicly
            await channel.send(embed=embed, file=discord_file)
            # Confirm ephemerally
            await interaction.followup.send(f"📊 Weekly Growth Report generated and posted to {channel.mention}.", ephemeral=True)
        else:
            # Send privately (ephemerally)
            await interaction.followup.send(embed=embed, file=discord_file, ephemeral=True)
        
        # Log to audit logs
        await self.log_action(
            interaction.guild_id,
            "Weekly Report Generated",
            f"Generated weekly report for {start_str} to {end_str} with {len(report_members)} members."
        )


async def setup(bot):
    await bot.add_cog(OnboardingCog(bot))
