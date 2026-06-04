import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import discord
from discord.ext import commands


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = str(PROJECT_ROOT / "data" / "engagement.json")
EXCLUDED_ROLE_IDS = {1448734834523635712, 1436388826452070481}
SWEEP_CHANNEL_IDS = [
    1441218869422461041,
    1445171480106111040,
    1448756310005780610,
    1441218957662093534,
    1452757067449503844,
]
WINDOW_OPTIONS = {
    "all": None,
    "30": 30,
    "60": 60,
    "90": 90,
}


def utc_date_key(value: Optional[datetime] = None) -> str:
    now = value or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc).date().isoformat()


def window_label(window_key: str) -> str:
    if window_key == "all":
        return "All time"
    return f"Last {WINDOW_OPTIONS[window_key]} days"


class EngagementStore:
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
        state.setdefault("members", {})
        processed = state.setdefault("processed", {})
        processed.setdefault("messages", {})
        processed.setdefault("reactions", {})
        return state

    def member_state(self, guild_id: int, member_id: int) -> Dict[str, Any]:
        members = self.guild_state(guild_id).setdefault("members", {})
        state = members.setdefault(str(member_id), {})
        state.setdefault("messages", 0)
        state.setdefault("reactions", 0)
        state.setdefault("days", {})
        return state

    def record_activity(
        self,
        guild_id: int,
        member_id: int,
        kind: str,
        *,
        at: Optional[datetime] = None,
        save: bool = True,
    ) -> None:
        if kind not in {"messages", "reactions"}:
            raise ValueError("kind must be 'messages' or 'reactions'")

        member = self.member_state(guild_id, member_id)
        member[kind] = int(member.get(kind, 0)) + 1

        date_key = utc_date_key(at)
        days = member.setdefault("days", {})
        day = days.setdefault(date_key, {"messages": 0, "reactions": 0})
        day.setdefault("messages", 0)
        day.setdefault("reactions", 0)
        day[kind] = int(day.get(kind, 0)) + 1

        self.prune_daily_buckets(now=at, save=False)
        if save:
            self.save()

    def record_message_once(
        self,
        guild_id: int,
        member_id: int,
        message_id: int,
        *,
        at: Optional[datetime] = None,
        save: bool = True,
    ) -> bool:
        processed = self.guild_state(guild_id)["processed"]["messages"]
        key = str(message_id)
        if key in processed:
            return False

        processed[key] = member_id
        self.record_activity(guild_id, member_id, "messages", at=at, save=False)
        if save:
            self.save()
        return True

    def record_reaction_once(
        self,
        guild_id: int,
        member_id: int,
        reaction_key: str,
        *,
        at: Optional[datetime] = None,
        save: bool = True,
    ) -> bool:
        processed = self.guild_state(guild_id)["processed"]["reactions"]
        if reaction_key in processed:
            return False

        processed[reaction_key] = member_id
        self.record_activity(guild_id, member_id, "reactions", at=at, save=False)
        if save:
            self.save()
        return True

    def prune_daily_buckets(self, *, now: Optional[datetime] = None, save: bool = True) -> None:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        cutoff = (current.astimezone(timezone.utc).date() - timedelta(days=89)).isoformat()

        changed = False
        for guild in self.data.setdefault("guilds", {}).values():
            for member in guild.setdefault("members", {}).values():
                days = member.setdefault("days", {})
                old_keys = [date_key for date_key in days if date_key < cutoff]
                for date_key in old_keys:
                    days.pop(date_key, None)
                    changed = True

        if changed and save:
            self.save()

    def leaderboard(
        self,
        guild: discord.Guild,
        *,
        window_days: Optional[int] = None,
        limit: int = 10,
        now: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        state = self.guild_state(guild.id)
        rows = []

        cutoff = None
        if window_days is not None:
            current = now or datetime.now(timezone.utc)
            if current.tzinfo is None:
                current = current.replace(tzinfo=timezone.utc)
            cutoff = (current.astimezone(timezone.utc).date() - timedelta(days=window_days - 1)).isoformat()

        for member_id_str, data in state.get("members", {}).items():
            try:
                member_id = int(member_id_str)
            except ValueError:
                continue

            member = guild.get_member(member_id)
            if not self._is_displayable_member(member):
                continue

            if cutoff is None:
                messages = int(data.get("messages", 0))
                reactions = int(data.get("reactions", 0))
            else:
                messages = 0
                reactions = 0
                for date_key, counts in data.get("days", {}).items():
                    if date_key < cutoff:
                        continue
                    messages += int(counts.get("messages", 0))
                    reactions += int(counts.get("reactions", 0))

            total = messages + reactions
            if total <= 0:
                continue

            rows.append(
                {
                    "member": member,
                    "member_id": member_id,
                    "messages": messages,
                    "reactions": reactions,
                    "total": total,
                }
            )

        rows.sort(key=lambda row: (-row["total"], -row["messages"], -row["reactions"], row["member_id"]))
        return rows[:limit]

    def _is_displayable_member(self, member: Optional[discord.Member]) -> bool:
        if member is None or getattr(member, "bot", False):
            return False

        member_role_ids = {getattr(role, "id", None) for role in getattr(member, "roles", [])}
        return not bool(EXCLUDED_ROLE_IDS & member_role_ids)


class EngagementWindowSelect(discord.ui.Select):
    def __init__(self, dashboard: "EngagementDashboardView"):
        self.dashboard = dashboard
        options = [
            discord.SelectOption(label="All time", value="all", default=dashboard.window_key == "all"),
            discord.SelectOption(label="Last 30 days", value="30", default=dashboard.window_key == "30"),
            discord.SelectOption(label="Last 60 days", value="60", default=dashboard.window_key == "60"),
            discord.SelectOption(label="Last 90 days", value="90", default=dashboard.window_key == "90"),
        ]
        super().__init__(placeholder="Choose leaderboard window...", options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        self.dashboard.window_key = self.values[0]
        self.dashboard.refresh_items()
        await self.dashboard.refresh(interaction)


class EngagementDashboardView(discord.ui.View):
    def __init__(self, bot: commands.Bot, cog: "EngagementCog", guild_id: int, user_id: int):
        super().__init__(timeout=900)
        self.bot = bot
        self.cog = cog
        self.guild_id = guild_id
        self.user_id = user_id
        self.window_key = "all"
        self.refresh_items()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This engagement panel belongs to another moderator.", ephemeral=True)
            return False
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("You need Manage Messages to use engagement controls.", ephemeral=True)
            return False
        return True

    def refresh_items(self):
        self.clear_items()
        self.add_item(EngagementWindowSelect(self))
        refresh_button = discord.ui.Button(label="Refresh", style=discord.ButtonStyle.gray, row=1)
        refresh_button.callback = self.refresh_button
        self.add_item(refresh_button)
        sweep_button = discord.ui.Button(label="Sweep Channels", style=discord.ButtonStyle.blurple, row=1)
        sweep_button.callback = self.sweep_button
        self.add_item(sweep_button)

    async def refresh_button(self, interaction: discord.Interaction):
        await self.refresh(interaction)

    async def sweep_button(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild or self.bot.get_guild(self.guild_id)
        if not guild:
            await interaction.followup.send("This panel must be used inside a server.", ephemeral=True)
            return

        result = await self.cog.sweep_configured_channels(guild)
        embed = self.build_embed(guild)
        await interaction.edit_original_response(embed=embed, view=self)
        await interaction.followup.send(result, ephemeral=True)

    def build_embed(self, guild: discord.Guild) -> discord.Embed:
        window_days = WINDOW_OPTIONS[self.window_key]
        rows = self.cog.store.leaderboard(guild, window_days=window_days)
        label = window_label(self.window_key)

        embed = discord.Embed(
            title="Most Engaged Members",
            description=f"Ranking non-mod members by messages sent plus reactions added.\nWindow: **{label}**",
            color=0xE8C1A0,
        )

        if not rows:
            embed.add_field(
                name="No tracked activity yet",
                value="No eligible member engagement has been recorded for this window.",
                inline=False,
            )
        else:
            lines = []
            for index, row in enumerate(rows, start=1):
                member = row["member"]
                lines.append(
                    f"**{index}.** {member.mention} - **{row['total']}** total "
                    f"({row['messages']} messages, {row['reactions']} reactions)"
                )
            embed.add_field(name="Top 10", value="\n".join(lines), inline=False)

        embed.set_footer(text="Engagement tracking starts from the deployment of this feature")
        embed.timestamp = datetime.utcnow()
        return embed

    async def refresh(self, interaction: discord.Interaction):
        guild = interaction.guild or self.bot.get_guild(self.guild_id)
        if not guild:
            await interaction.response.send_message("This panel must be used inside a server.", ephemeral=True)
            return

        embed = self.build_embed(guild)
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)


class EngagementCog(commands.Cog, name="EngagementCog"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.store = EngagementStore()

    @commands.Cog.listener()
    async def on_ready(self):
        print(f"EngagementCog: recording engagement data at {self.store.path}")

    async def launch_dashboard(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("This panel must be used inside a server.", ephemeral=True)
            return

        view = EngagementDashboardView(self.bot, self, interaction.guild_id, interaction.user.id)
        await interaction.response.send_message(embed=view.build_embed(interaction.guild), view=view, ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or getattr(message.author, "bot", False):
            return

        self.store.record_message_once(
            message.guild.id,
            message.author.id,
            message.id,
            at=getattr(message, "created_at", None),
        )

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None:
            return
        if self.bot.user and payload.user_id == self.bot.user.id:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        member = getattr(payload, "member", None) or guild.get_member(payload.user_id)
        if member is None:
            try:
                member = await guild.fetch_member(payload.user_id)
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                return

        if getattr(member, "bot", False):
            return

        reaction_key = self.reaction_key(payload.message_id, payload.emoji, member.id)
        self.store.record_reaction_once(guild.id, member.id, reaction_key)

    def reaction_key(self, message_id: int, emoji: Any, member_id: int) -> str:
        emoji_id = getattr(emoji, "id", None)
        emoji_name = getattr(emoji, "name", None)
        emoji_value = emoji_id or emoji_name or str(emoji)
        return f"{message_id}:{emoji_value}:{member_id}"

    async def sweep_configured_channels(self, guild: discord.Guild) -> str:
        if not guild.chunked:
            try:
                await guild.chunk()
            except (discord.Forbidden, discord.HTTPException):
                pass

        scanned_messages = 0
        new_messages = 0
        new_reactions = 0
        inaccessible_channels = []

        for channel_id in SWEEP_CHANNEL_IDS:
            try:
                channel = guild.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                inaccessible_channels.append(str(channel_id))
                continue

            if not hasattr(channel, "history"):
                inaccessible_channels.append(str(channel_id))
                continue

            try:
                async for message in channel.history(limit=None, oldest_first=True):
                    scanned_messages += 1

                    member = message.author if isinstance(message.author, discord.Member) else guild.get_member(message.author.id)
                    if self.should_count_member(member):
                        if self.store.record_message_once(
                            guild.id,
                            member.id,
                            message.id,
                            at=getattr(message, "created_at", None),
                            save=False,
                        ):
                            new_messages += 1

                    for reaction in message.reactions:
                        async for user in reaction.users(limit=None):
                            member = user if isinstance(user, discord.Member) else guild.get_member(user.id)
                            if not self.should_count_member(member):
                                continue

                            reaction_key = self.reaction_key(message.id, reaction.emoji, member.id)
                            if self.store.record_reaction_once(
                                guild.id,
                                member.id,
                                reaction_key,
                                at=getattr(message, "created_at", None),
                                save=False,
                            ):
                                new_reactions += 1
            except (discord.Forbidden, discord.HTTPException):
                inaccessible_channels.append(str(channel_id))

        self.store.save()

        result = (
            f"Sweep complete. Scanned **{scanned_messages}** message(s), added "
            f"**{new_messages}** message count(s) and **{new_reactions}** reaction count(s)."
        )
        if inaccessible_channels:
            result += f"\nCould not access: `{', '.join(inaccessible_channels)}`"
        return result

    def should_count_member(self, member: Optional[discord.Member]) -> bool:
        if member is None or getattr(member, "bot", False):
            return False
        member_role_ids = {getattr(role, "id", None) for role in getattr(member, "roles", [])}
        return not bool(EXCLUDED_ROLE_IDS & member_role_ids)


async def setup(bot):
    await bot.add_cog(EngagementCog(bot))
