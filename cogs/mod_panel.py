import discord
from discord.ext import commands
from discord import app_commands
import calendar
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from collections import Counter



PANEL_DESCRIPTION = (
    "Welcome to the **Master Control Panel**. Select a feature below to execute bot commands instantly without typing.\n\n"
    "**Quick Reference:**\n"
    "**Embed Editor:** Create rich custom messages, schedule posts, and add buttons.\n"
    "**Sticky Messages:** Create sticky messages that always stay at the bottom of the chat.\n"
    "**Onboarding:** Collect new members, schedule plain-text welcome posts, and prevent duplicate tags.\n"
    "**Audit Logs:** Track key server and bot actions in a chosen channel.\n"
    "**Basic Message:** Create standard conversational text.\n"
    "**Live Stats:** Post and auto-refresh a server health dashboard.\n"
    "**TikTok Connector:** Post a guided account-connection panel for creators.\n"
    "**Weekly Report:** Run stateful weekly member growth and onboarding audits.\n"
    "**Monthly Joins:** View server join statistics and analytics for any specific month.\n"
    "**Most Engaged:** View top non-mod members by messages and reactions.\n"
)


def build_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Love in Faith Master Panel",
        description=PANEL_DESCRIPTION,
        color=0xE8C1A0,
    )
    embed.set_footer(text="Official Discord bot of Love in Faith")
    return embed


def parse_month(month_str: str) -> Optional[int]:
    month_str = month_str.strip().lower()
    if month_str.isdigit():
        val = int(month_str)
        if 1 <= val <= 12:
            return val
    for i in range(1, 13):
        name = calendar.month_name[i].lower()
        abbr = calendar.month_abbr[i].lower()
        if name and month_str == name:
            return i
        if abbr and month_str == abbr:
            return i
    if len(month_str) >= 3:
        for i in range(1, 13):
            name = calendar.month_name[i].lower()
            abbr = calendar.month_abbr[i].lower()
            if (name and month_str in name) or (abbr and month_str in abbr):
                return i
    return None


async def get_monthly_joins_embed(guild: discord.Guild, month: int, year: int) -> discord.Embed:
    if not guild.chunked:
        try:
            await guild.chunk()
        except Exception:
            pass

    matching_members = []
    for member in guild.members:
        joined_at = member.joined_at
        if joined_at is not None:
            if joined_at.year == year and joined_at.month == month:
                matching_members.append(member)

    matching_members.sort(key=lambda m: m.joined_at or datetime.min.replace(tzinfo=timezone.utc))

    total_joins = len(matching_members)
    humans = sum(1 for m in matching_members if not m.bot)
    bots = sum(1 for m in matching_members if m.bot)

    month_name = calendar.month_name[month]

    embed = discord.Embed(
        title=f"📅 Join Analytics - {month_name} {year}",
        description=f"Detailed server join statistics for **{month_name} {year}**.",
        color=0xE8C1A0,
    )

    if total_joins == 0:
        embed.description += "\n\n❌ **No members joined during this month.**"
        embed.set_footer(text=f"Server: {guild.name}")
        return embed

    day_counts = Counter(m.joined_at.day for m in matching_members if m.joined_at is not None)
    busiest_day_num, busiest_count = day_counts.most_common(1)[0]

    now = datetime.now(timezone.utc)
    if now.year == year and now.month == month:
        total_days = now.day
    else:
        _, total_days = calendar.monthrange(year, month)

    avg_joins = total_joins / total_days

    embed.add_field(name="Total Joins", value=f"👥 **{total_joins}** members", inline=True)
    embed.add_field(name="Breakdown", value=f"🧑 Humans: **{humans}**\n🤖 Bots: **{bots}**", inline=True)
    embed.add_field(name="Join Rates", value=f"📈 Avg: **{avg_joins:.1f}/day**\n🔥 Peak: **{busiest_count}** (on {month_name} {busiest_day_num})", inline=True)

    first_few = matching_members[:5]
    last_few = matching_members[-5:]

    if total_joins <= 5:
        last_few = []
    elif total_joins < 10:
        last_few = matching_members[5:]

    first_list_str = "\n".join(
        f"{idx+1}. {m.mention} (`{m.id}`) - <t:{int(m.joined_at.timestamp())}:f>"
        for idx, m in enumerate(first_few)
    )
    embed.add_field(name="🆕 First to Join", value=first_list_str or "None", inline=False)

    if last_few:
        last_list_str = "\n".join(
            f"{total_joins - len(last_few) + idx + 1}. {m.mention} (`{m.id}`) - <t:{int(m.joined_at.timestamp())}:f>"
            for idx, m in enumerate(last_few)
        )
        embed.add_field(name="🔄 Last to Join", value=last_list_str, inline=False)

    embed.set_footer(text=f"Love in Faith • Server: {guild.name}")
    return embed



class BasicMessageModal(discord.ui.Modal, title="Send Basic Message"):
    channel_id = discord.ui.TextInput(label="Target channel ID", required=True, max_length=24)
    content = discord.ui.TextInput(
        label="Message",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=2000,
    )

    def __init__(self, bot: commands.Bot, default_channel_id: int):
        super().__init__()
        self.bot = bot
        self.channel_id.default = str(default_channel_id)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            target_channel_id = int(str(self.channel_id.value).strip())
            channel = self.bot.get_channel(target_channel_id) or await self.bot.fetch_channel(target_channel_id)
        except ValueError:
            await interaction.response.send_message("Channel ID must be a number.", ephemeral=True)
            return
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            await interaction.response.send_message("I cannot find or access that channel.", ephemeral=True)
            return

        if not hasattr(channel, "send"):
            await interaction.response.send_message("That channel cannot receive messages.", ephemeral=True)
            return

        await channel.send(
            str(self.content.value),
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )

        audit_cog = self.bot.get_cog("AuditLogsCog")
        if audit_cog:
            await audit_cog.log_event(
                interaction.guild_id,
                "Basic Message Sent",
                f"{interaction.user.mention} sent a basic message to <#{target_channel_id}>.",
                color=0xE8C1A0,
            )

        await interaction.response.send_message(f"Message sent to <#{target_channel_id}>.", ephemeral=True)


class MonthlyMembersModal(discord.ui.Modal, title="Detect Monthly Members"):
    month_input = discord.ui.TextInput(
        label="Month (e.g. January, May, 5, 05)",
        required=True,
        max_length=20,
        placeholder="Enter month name or number"
    )
    year_input = discord.ui.TextInput(
        label="Year (e.g. 2026)",
        required=False,
        max_length=4,
        placeholder="Leave blank for current year"
    )

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot
        self.month_input.default = datetime.now().strftime("%B")
        self.year_input.default = str(datetime.now().year)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        month_str = str(self.month_input.value).strip()
        month = parse_month(month_str)
        if not month:
            await interaction.followup.send(f"❌ Invalid month: `{month_str}`. Please enter a valid month name or number.", ephemeral=True)
            return

        year_str = str(self.year_input.value).strip()
        if not year_str:
            year = datetime.now().year
        else:
            try:
                year = int(year_str)
                if year < 2015 or year > 2050:
                    raise ValueError
            except ValueError:
                await interaction.followup.send(f"❌ Invalid year: `{year_str}`. Please enter a valid year between 2015 and 2050.", ephemeral=True)
                return

        guild = interaction.guild
        if not guild:
            await interaction.followup.send("❌ This command must be run inside a Discord server.", ephemeral=True)
            return

        try:
            embed = await get_monthly_joins_embed(guild, month, year)
            await interaction.followup.send(embed=embed, ephemeral=True)

            audit_cog = self.bot.get_cog("AuditLogsCog")
            if audit_cog:
                await audit_cog.log_event(
                    guild.id,
                    "Monthly Joins Checked",
                    f"{interaction.user.mention} checked join stats for **{calendar.month_name[month]} {year}**.",
                    color=0xE8C1A0,
                )
        except Exception as e:
            await interaction.followup.send(f"❌ An error occurred while retrieving join analytics: {e}", ephemeral=True)


class ModPanelView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("You need Manage Messages to use the Mod Panel.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Refresh Panel", style=discord.ButtonStyle.green, custom_id="panel:refresh", row=0)
    async def refresh_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_panel(interaction)

    @discord.ui.button(label="Embed Editor", style=discord.ButtonStyle.blurple, custom_id="panel:embed_editor", row=1)
    async def embed_editor_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = self.bot.get_cog("EmbedEditorCog")
        if cog:
            await cog.start_editor(interaction)
        else:
            await interaction.response.send_message("Embed Editor is currently unavailable.", ephemeral=True)

    @discord.ui.button(label="Sticky Messages", style=discord.ButtonStyle.green, custom_id="panel:sticky_msgs", row=1)
    async def sticky_msgs_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = self.bot.get_cog("StickyMessagesCog")
        if cog:
            await cog.launch_dashboard(interaction)
        else:
            await interaction.response.send_message("Sticky Messages feature is currently unavailable.", ephemeral=True)

    @discord.ui.button(label="Onboarding", style=discord.ButtonStyle.blurple, custom_id="panel:onboarding", row=1)
    async def onboarding_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = self.bot.get_cog("OnboardingCog")
        if cog:
            await cog.launch_dashboard(interaction)
        else:
            await interaction.response.send_message("Onboarding feature is currently unavailable.", ephemeral=True)

    @discord.ui.button(label="Live Stats", style=discord.ButtonStyle.gray, custom_id="panel:live_stats", row=1)
    async def live_stats_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = self.bot.get_cog("LiveStatsCog")
        if cog:
            await cog.launch_dashboard(interaction)
        else:
            await interaction.response.send_message("Live Stats feature is currently unavailable.", ephemeral=True)

    @discord.ui.button(label="TikTok Connector", style=discord.ButtonStyle.blurple, custom_id="panel:tiktok", row=2)
    async def tiktok_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = self.bot.get_cog("TikTokConnectorCog")
        if cog:
            await cog.launch_panel(interaction)
        else:
            await interaction.response.send_message("TikTok Connector feature is currently unavailable.", ephemeral=True)

    @discord.ui.button(label="Audit Logs", style=discord.ButtonStyle.gray, custom_id="panel:audit_logs", row=2)
    async def audit_logs_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = self.bot.get_cog("AuditLogsCog")
        if cog:
            await cog.launch_dashboard(interaction)
        else:
            await interaction.response.send_message("Audit Logs feature is currently unavailable.", ephemeral=True)

    @discord.ui.button(label="Basic Message", style=discord.ButtonStyle.gray, custom_id="panel:basic_msg", row=2)
    async def basic_msg_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BasicMessageModal(self.bot, interaction.channel_id))

    @discord.ui.button(label="Tag Recent Members", style=discord.ButtonStyle.blurple, custom_id="panel:tag_recent", row=2)
    async def tag_recent_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = self.bot.get_cog("OnboardingCog")
        if cog:
            await cog.launch_dashboard(interaction)
        else:
            await interaction.response.send_message("Onboarding feature is currently unavailable.", ephemeral=True)

    @discord.ui.button(label="Monthly Joins", style=discord.ButtonStyle.blurple, custom_id="panel:monthly_joins", row=3)
    async def monthly_joins_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(MonthlyMembersModal(self.bot))

    @discord.ui.button(label="Most Engaged", style=discord.ButtonStyle.green, custom_id="panel:engagement", row=3)
    async def engagement_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = self.bot.get_cog("EngagementCog")
        if cog:
            await cog.launch_dashboard(interaction)
        else:
            await interaction.response.send_message("Engagement leaderboard is currently unavailable.", ephemeral=True)

    @discord.ui.button(label="Weekly Report", style=discord.ButtonStyle.blurple, custom_id="panel:weekly_report", row=3)
    async def weekly_report_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = self.bot.get_cog("OnboardingCog")
        if cog:
            from cogs.onboarding import WeeklyReportOptionsView
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="📊 Weekly Onboarding Growth Report Options",
                    description="Choose whether to download the report privately as a CSV, or post it publicly to a selected channel with comprehensive statistics and a breakdown.",
                    color=0xE8C1A0
                ),
                view=WeeklyReportOptionsView(cog),
                ephemeral=True
            )
        else:
            await interaction.response.send_message("Onboarding feature is currently unavailable.", ephemeral=True)

    async def update_panel(self, interaction: discord.Interaction):
        try:
            await interaction.response.edit_message(embed=build_panel_embed(), view=self)
        except discord.errors.InteractionResponded:
            await interaction.edit_original_response(embed=build_panel_embed(), view=self)


class ModPanelCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="summon", description="Summon the Love in Faith Mod Panel")
    @app_commands.default_permissions(manage_messages=True)
    async def summon(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=build_panel_embed(), view=ModPanelView(self.bot))

    @app_commands.command(name="member_count", description="Detect and analyze server joins for a specific month")
    @app_commands.describe(
        month="The month to query (e.g., January, Jan, 5, 05)",
        year="The year to query (optional, defaults to current year)"
    )
    @app_commands.default_permissions(manage_messages=True)
    async def member_count(self, interaction: discord.Interaction, month: str, year: Optional[int] = None):
        await interaction.response.defer(ephemeral=True)

        parsed_month = parse_month(month)
        if not parsed_month:
            await interaction.followup.send(f"❌ Invalid month: `{month}`. Please enter a valid month name or number.", ephemeral=True)
            return

        if year is None:
            year = datetime.now().year
        elif year < 2015 or year > 2050:
            await interaction.followup.send(f"❌ Invalid year: `{year}`. Please enter a valid year between 2015 and 2050.", ephemeral=True)
            return

        guild = interaction.guild
        if not guild:
            await interaction.followup.send("❌ This command must be run inside a Discord server.", ephemeral=True)
            return

        try:
            embed = await get_monthly_joins_embed(guild, parsed_month, year)
            await interaction.followup.send(embed=embed, ephemeral=True)

            audit_cog = self.bot.get_cog("AuditLogsCog")
            if audit_cog:
                await audit_cog.log_event(
                    guild.id,
                    "Monthly Joins Checked",
                    f"{interaction.user.mention} checked join stats for **{calendar.month_name[parsed_month]} {year}** via `/member_count`.",
                    color=0xE8C1A0,
                )
        except Exception as e:
            await interaction.followup.send(f"❌ An error occurred while retrieving join analytics: {e}", ephemeral=True)



async def setup(bot):
    bot.add_view(ModPanelView(bot))
    await bot.add_cog(ModPanelCog(bot))
