import discord
from discord.ext import commands
from discord import app_commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from utils.time_utils import generate_date_options, generate_hour_options, generate_minute_options, parse_schedule_time
from utils.state import EmbedScript
from datetime import datetime
import json
import os
from typing import List

class ScheduleView(discord.ui.View):
    def __init__(self, bot: commands.Bot, script: EmbedScript):
        super().__init__(timeout=900)
        self.bot = bot
        self.script = script
        self.selected_date = None
        self.selected_hour = None
        self.selected_minute = None
        self.selected_tz = None # Default is None to force timezone selection first

        self.build_ui()

    def build_ui(self):
        self.clear_items()
        
        if self.selected_tz is None:
            # Step 1: Select timezone first
            tz_select = discord.ui.Select(
                placeholder="Select Timezone...", 
                custom_id="sch:tz", 
                options=[
                    discord.SelectOption(label="Manila/Singapore Time (GMT+8)", value="Asia/Singapore"),
                    discord.SelectOption(label="EST (Eastern Time)", value="America/New_York"),
                ], 
                row=0
            )
            tz_select.callback = self.tz_callback
            self.add_item(tz_select)
        else:
            # Step 2: Show Date, Hour, Minute, and Confirm options
            # 1. Date Select
            date_opts = generate_date_options(14, self.selected_tz)
            date_select = discord.ui.Select(placeholder="Select Date...", custom_id="sch:date", options=[
                discord.SelectOption(label=l, value=v, default=(v == self.selected_date)) for l, v in date_opts
            ], row=0)
            date_select.callback = self.date_callback
            self.add_item(date_select)

            # 2. Hour Select
            hour_opts = generate_hour_options()
            hour_select = discord.ui.Select(placeholder="Select Hour...", custom_id="sch:hour", options=[
                discord.SelectOption(label=l, value=v, default=(v == self.selected_hour)) for l, v in hour_opts
            ], row=1) 
            hour_select.callback = self.hour_callback
            self.add_item(hour_select)

            # 3. Minute Select
            minute_opts = generate_minute_options()
            minute_select = discord.ui.Select(placeholder="Select Minute...", custom_id="sch:minute", options=[
                discord.SelectOption(label=l, value=v, default=(v == self.selected_minute)) for l, v in minute_opts
            ], row=2)
            minute_select.callback = self.minute_callback
            self.add_item(minute_select)

            # 4. Action Row (Confirm & Change TZ)
            confirm_btn = discord.ui.Button(label="Confirm Schedule", style=discord.ButtonStyle.green, row=3)
            confirm_btn.callback = self.confirm_callback
            self.add_item(confirm_btn)

            change_tz_btn = discord.ui.Button(label="Change Timezone", style=discord.ButtonStyle.secondary, row=3)
            change_tz_btn.callback = self.change_tz_callback
            self.add_item(change_tz_btn)

    async def date_callback(self, interaction: discord.Interaction):
        self.selected_date = interaction.data['values'][0]
        self.build_ui()
        await self.update_status(interaction)

    async def hour_callback(self, interaction: discord.Interaction):
        self.selected_hour = interaction.data['values'][0]
        self.build_ui()
        await self.update_status(interaction)

    async def minute_callback(self, interaction: discord.Interaction):
        self.selected_minute = interaction.data['values'][0]
        self.build_ui()
        await self.update_status(interaction)

    async def tz_callback(self, interaction: discord.Interaction):
        self.selected_tz = interaction.data['values'][0]
        self.build_ui()
        await self.update_status(interaction)

    async def change_tz_callback(self, interaction: discord.Interaction):
        self.selected_tz = None
        self.selected_date = None
        self.selected_hour = None
        self.selected_minute = None
        self.build_ui()
        await self.update_status(interaction)

    async def update_status(self, interaction: discord.Interaction):
        if self.selected_tz is None:
            msg = "Please select your timezone to start scheduling:"
        else:
            time_str = "None"
            if self.selected_hour is not None and self.selected_minute is not None:
                h = int(self.selected_hour)
                m = int(self.selected_minute)
                period = "AM" if h < 12 else "PM"
                dh = h if h != 0 else 12
                if dh > 12: dh -= 12
                time_str = f"{dh}:{m:02d} {period}"
                
            tz_name = "Manila/Singapore Time" if self.selected_tz == "Asia/Singapore" else "EST"
            msg = f"**Current Selection:**\nDate: {self.selected_date or 'None'}\nTime: {time_str}\nTimezone: {tz_name}"
            
        await interaction.response.edit_message(content=msg, view=self)

    async def confirm_callback(self, interaction: discord.Interaction):
        if not (self.selected_date and self.selected_hour and self.selected_minute):
            await interaction.response.send_message("Please select Date, Hour, and Minute.", ephemeral=True)
            return
            
        try:
            dt_utc = parse_schedule_time(self.selected_date, self.selected_hour, self.selected_minute, self.selected_tz)
        except Exception as e:
            await interaction.response.send_message(f"Error parsing time: {e}", ephemeral=True)
            return
        
        from datetime import timezone
        if dt_utc < datetime.now(timezone.utc):
            await interaction.response.send_message("Cannot schedule in the past!", ephemeral=True)
            return

        try:
            scheduler_cog = self.bot.get_cog("SchedulerCog")
            job_id = scheduler_cog.schedule_message(self.script.to_dict(), dt_utc)
            
            await interaction.response.edit_message(content=f"✅ Message scheduled for <t:{int(dt_utc.timestamp())}:F> (Job ID: {job_id})", view=None)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            await interaction.response.send_message(f"Failed to schedule message:\n```py\n{tb[:1900]}\n```", ephemeral=True)

# Global reference for the scheduled function to access
_bot_instance = None

async def run_scheduled_event(payload: dict):
    bot = _bot_instance
    if not bot:
        print("Scheduled event failed: Bot instance not initialized.")
        return
        
    channel_ids = payload.get('channel_ids', [])
    content = payload.get('content')
    embeds_data = payload.get('embeds', [])
    buttons = payload.get('buttons', [])
    
    embeds = []
    for data in embeds_data:
        em = discord.Embed(
            title=data.get('title'),
            description=data.get('description'),
            color=data.get('color') if data.get('color') is not None else 0x2B2D31
        )
        if data.get('image_url'): em.set_image(url=data.get('image_url'))
        if data.get('thumbnail_url'): em.set_thumbnail(url=data.get('thumbnail_url'))
        embeds.append(em)

    view = discord.ui.View()
    for b in buttons:
        view.add_item(discord.ui.Button(label=b['label'], url=b['url'], style=discord.ButtonStyle.link))

    for channel_id in channel_ids:
        channel = bot.get_channel(channel_id)
        if not channel:
            try:
                channel = await bot.fetch_channel(channel_id)
            except Exception:
                pass
        
        if channel:
            try:
                await channel.send(content=content, embeds=embeds, view=view)
            except Exception as e:
                print(f"Failed to send scheduled message to {channel_id}: {e}")


async def run_weekly_reminder_event(rem_payload: dict):
    bot = _bot_instance
    if not bot:
        print("Weekly reminder failed: Bot instance not initialized.")
        return
        
    channel_id = rem_payload.get('channel_id')
    content = rem_payload.get('content')
    if not channel_id or not content:
        print("Weekly reminder failed: Missing channel_id or content.")
        return
        
    try:
        channel = bot.get_channel(int(channel_id)) or await bot.fetch_channel(int(channel_id))
        if channel:
            await channel.send(content=content)
            print(f"Weekly reminder '{rem_payload.get('name')}' sent successfully to channel {channel_id}.")
        else:
            print(f"Weekly reminder failed: Channel {channel_id} not found.")
    except Exception as e:
        print(f"Failed to send weekly reminder {rem_payload.get('id')}: {e}")


class EditReminderModal(discord.ui.Modal):
    channel_input = discord.ui.TextInput(label="Channel ID", required=True, max_length=24)
    content_input = discord.ui.TextInput(
        label="Message Content",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=2000
    )

    def __init__(self, cog, reminder_dict: dict):
        super().__init__(title=f"Edit {reminder_dict.get('name')[:20]}")
        self.cog = cog
        self.reminder_id = reminder_dict.get('id')
        self.channel_input.default = str(reminder_dict.get('channel_id', ''))
        self.content_input.default = reminder_dict.get('content', '')

    async def on_submit(self, interaction: discord.Interaction):
        try:
            chan_id = int(str(self.channel_input.value).strip())
        except ValueError:
            await interaction.response.send_message("Channel ID must be a valid number.", ephemeral=True)
            return
            
        path = "data/reminders.json"
        if not os.path.exists(path):
            await interaction.response.send_message("Reminders file not found.", ephemeral=True)
            return
            
        try:
            with open(path, "r", encoding="utf-8") as f:
                reminders = json.load(f)
        except Exception as e:
            await interaction.response.send_message(f"Error reading reminders: {e}", ephemeral=True)
            return
            
        found = False
        for rem in reminders:
            if rem.get("id") == self.reminder_id:
                rem["channel_id"] = chan_id
                rem["content"] = str(self.content_input.value)
                found = True
                break
                
        if not found:
            await interaction.response.send_message("Reminder not found.", ephemeral=True)
            return
            
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(reminders, f, indent=4)
        except Exception as e:
            await interaction.response.send_message(f"Failed to save changes: {e}", ephemeral=True)
            return
            
        # Re-sync scheduled jobs
        self.cog.sync_weekly_reminders()
        
        # Log to audit logs
        audit_cog = self.cog.bot.get_cog("AuditLogsCog")
        if audit_cog:
            await audit_cog.log_event(
                interaction.guild_id,
                "Weekly Reminder Edited",
                f"{interaction.user.mention} updated the weekly reminder `{self.reminder_id}`.",
                color=0xE8C1A0
            )
            
        await interaction.response.send_message(f"✅ Weekly reminder `{self.reminder_id}` updated and rescheduled successfully!", ephemeral=True)


class SchedulerDashboardView(discord.ui.View):
    def __init__(self, cog: "SchedulerCog", user_id: int):
        super().__init__(timeout=900)
        self.cog = cog
        self.user_id = user_id
        
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This dashboard belongs to another moderator.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="List Reminders", style=discord.ButtonStyle.blurple, row=0)
    async def btn_list(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.reminders_list.callback(self.cog, interaction)

    @discord.ui.button(label="Edit Reminder", style=discord.ButtonStyle.green, row=0)
    async def btn_edit(self, interaction: discord.Interaction, button: discord.ui.Button):
        path = "data/reminders.json"
        if not os.path.exists(path):
            await interaction.response.send_message("No reminders configured.", ephemeral=True)
            return
            
        try:
            with open(path, "r", encoding="utf-8") as f:
                reminders = json.load(f)
        except Exception:
            await interaction.response.send_message("Error loading reminders.", ephemeral=True)
            return
            
        view = discord.ui.View()
        select = discord.ui.Select(placeholder="Select a reminder to edit...")
        for rem in reminders:
            select.add_option(label=rem.get("name", rem["id"]), value=rem["id"])
            
        async def select_callback(inter: discord.Interaction):
            reminder_id = select.values[0]
            target = next((r for r in reminders if r["id"] == reminder_id), None)
            if target:
                await inter.response.send_modal(EditReminderModal(self.cog, target))
            else:
                await inter.response.send_message("Reminder not found.", ephemeral=True)
                
        select.callback = select_callback
        view.add_item(select)
        await interaction.response.send_message("Select a weekly reminder to edit:", view=view, ephemeral=True)

    @discord.ui.button(label="Toggle Reminder", style=discord.ButtonStyle.gray, row=0)
    async def btn_toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        path = "data/reminders.json"
        if not os.path.exists(path):
            await interaction.response.send_message("No reminders configured.", ephemeral=True)
            return
            
        try:
            with open(path, "r", encoding="utf-8") as f:
                reminders = json.load(f)
        except Exception:
            await interaction.response.send_message("Error loading reminders.", ephemeral=True)
            return
            
        view = discord.ui.View()
        select = discord.ui.Select(placeholder="Select a reminder to toggle...")
        for rem in reminders:
            status = "ON" if rem.get("enabled", True) else "OFF"
            select.add_option(label=f"{rem.get('name', rem['id'])} (Currently: {status})", value=rem["id"])
            
        async def select_callback(inter: discord.Interaction):
            reminder_id = select.values[0]
            found = False
            new_status = False
            for rem in reminders:
                if rem.get("id") == reminder_id:
                    rem["enabled"] = not rem.get("enabled", True)
                    new_status = rem["enabled"]
                    found = True
                    break
            if found:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(reminders, f, indent=4)
                self.cog.sync_weekly_reminders()
                status_text = "enabled" if new_status else "disabled"
                await inter.response.send_message(f"✅ Weekly reminder `{reminder_id}` has been **{status_text}**.", ephemeral=True)
                try:
                    await interaction.edit_original_response(embed=self.cog.build_dashboard_embed(), view=self)
                except Exception:
                    pass
            else:
                await inter.response.send_message("Reminder not found.", ephemeral=True)
                
        select.callback = select_callback
        view.add_item(select)
        await interaction.response.send_message("Select a weekly reminder to toggle:", view=view, ephemeral=True)

    @discord.ui.button(label="Schedule New Embed", style=discord.ButtonStyle.blurple, row=1)
    async def btn_schedule_embed(self, interaction: discord.Interaction, button: discord.ui.Button):
        editor_cog = self.cog.bot.get_cog("EmbedEditorCog")
        if editor_cog:
            await editor_cog.start_editor(interaction)
        else:
            await interaction.response.send_message("Embed Editor is currently unavailable.", ephemeral=True)


class SchedulerCog(commands.Cog, name="SchedulerCog"):
    reminders_group = app_commands.Group(name="reminders", description="Manage weekly reminders")

    def __init__(self, bot):
        self.bot = bot
        global _bot_instance
        _bot_instance = bot
        
        jobstores = {
            'default': SQLAlchemyJobStore(url='sqlite:///data/jobstore.db')
        }
        self.scheduler = AsyncIOScheduler(jobstores=jobstores)
        self.scheduler.start()
        
        # Initialize defaults and sync weekly reminders cron
        self.load_default_reminders()
        self.sync_weekly_reminders()

    def load_default_reminders(self):
        path = "data/reminders.json"
        defaults = [
            {
                "id": "monday_830_manila",
                "name": "Tuesday 8:30 AM Call Reminder (Manila)",
                "enabled": True,
                "channel_id": 1484627545834913793,
                "day_of_week": "tue",
                "hour": 8,
                "minute": 30,
                "timezone": "Asia/Manila",
                "content": "@everyone \n# 30 MINUTES LEFT! \n## Creator Training call at 6pm PST/9pm EST\nGoogle Meet joining info\nVideo call link: https://meet.google.com/upt-wyzu-kvh\nOr dial: (US) +1 320-336-0126 PIN: 371 357 523#\nMore phone numbers: https://tel.meet/upt-wyzu-kvh?pin=6054757020416"
            },
            {
                "id": "monday_855_manila",
                "name": "Tuesday 8:55 AM Call Reminder (Manila)",
                "enabled": True,
                "channel_id": 1484627545834913793,
                "day_of_week": "tue",
                "hour": 8,
                "minute": 55,
                "timezone": "Asia/Manila",
                "content": "@everyone \n# 5 MINUTES LEFT! \n## Creator Training call at 6pm PST/9pm EST\nGoogle Meet joining info\nVideo call link: https://meet.google.com/upt-wyzu-kvh\nOr dial: (US) +1 320-336-0126 PIN: 371 357 523#\nMore phone numbers: https://tel.meet/upt-wyzu-kvh?pin=6054757020416"
            }
        ]
        
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(defaults, f, indent=4)

    def sync_weekly_reminders(self):
        # Remove existing weekly reminder jobs from APScheduler to avoid duplicates
        for job in list(self.scheduler.get_jobs()):
            if job.id.startswith("rem:"):
                try:
                    self.scheduler.remove_job(job.id)
                except Exception:
                    pass
                    
        # Load from file and add to APScheduler
        path = "data/reminders.json"
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    reminders = json.load(f)
            except Exception as e:
                print(f"Error loading reminders from file: {e}")
                return
                
            for rem in reminders:
                if not rem.get("enabled", True):
                    continue
                    
                self.scheduler.add_job(
                    run_weekly_reminder_event,
                    'cron',
                    day_of_week=rem.get("day_of_week", "tue"),
                    hour=rem.get("hour", 8),
                    minute=rem.get("minute", 30),
                    timezone=rem.get("timezone", "Asia/Manila"),
                    id=f"rem:{rem['id']}",
                    args=[rem]
                )

    def schedule_message(self, script_dict: dict, run_time: datetime) -> str:
        job = self.scheduler.add_job(
            run_scheduled_event,
            'date',
            run_date=run_time,
            args=[script_dict]
        )
        return job.id

    async def start_schedule_workflow(self, interaction: discord.Interaction, script: EmbedScript):
        view = ScheduleView(self.bot, script)
        await interaction.response.send_message(
            content="Please select your timezone to start scheduling:", 
            view=view, 
            ephemeral=True
        )

    # Autocomplete helper for reminder IDs
    async def reminder_id_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        path = "data/reminders.json"
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                reminders = json.load(f)
        except Exception:
            return []
            
        return [
            app_commands.Choice(name=rem.get("name", rem["id"]), value=rem["id"])
            for rem in reminders
            if current.lower() in rem["id"].lower() or current.lower() in rem.get("name", "").lower()
        ][:25]

    async def launch_dashboard(self, interaction: discord.Interaction):
        embed = self.build_dashboard_embed()
        view = SchedulerDashboardView(self, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    def build_dashboard_embed(self) -> discord.Embed:
        path = "data/reminders.json"
        reminders = []
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    reminders = json.load(f)
            except Exception:
                pass
                
        embed = discord.Embed(
            title="⏰ Scheduled Messaging Dashboard",
            description=(
                "Manage recurring weekly call reminders and other scheduled announcements.\n\n"
                "Use the controls below to configure, toggle, or schedule new announcements."
            ),
            color=0xE8C1A0
        )
        
        weekly_lines = []
        for rem in reminders:
            status = "🟢 Enabled" if rem.get("enabled", True) else "🔴 Disabled"
            time_str = f"Every {rem.get('day_of_week', 'tue').upper()} at {rem.get('hour', 8):02d}:{rem.get('minute', 30):02d} in {rem.get('timezone', 'Asia/Manila')}"
            weekly_lines.append(f"- **{rem.get('name')}** (`{rem.get('id')}`)\n  Schedule: {time_str}\n  Channel: <#{rem.get('channel_id')}>\n  Status: {status}")
            
        embed.add_field(
            name="📅 Weekly Call Reminders", 
            value="\n".join(weekly_lines) if weekly_lines else "No weekly reminders configured.", 
            inline=False
        )
        
        one_off_jobs = [j for j in self.scheduler.get_jobs() if not j.id.startswith("rem:")]
        embed.add_field(
            name="✉️ Active One-Off Scheduled Announcements",
            value=f"There are currently **{len(one_off_jobs)}** active one-off announcements scheduled in the database.",
            inline=False
        )
        
        return embed

    @reminders_group.command(name="list", description="List all weekly reminders")
    @app_commands.default_permissions(manage_messages=True)
    async def reminders_list(self, interaction: discord.Interaction):
        path = "data/reminders.json"
        if not os.path.exists(path):
            await interaction.response.send_message("No reminders found.", ephemeral=True)
            return
            
        try:
            with open(path, "r", encoding="utf-8") as f:
                reminders = json.load(f)
        except Exception as e:
            await interaction.response.send_message(f"Error loading reminders: {e}", ephemeral=True)
            return
            
        embed = discord.Embed(
            title="📅 Weekly Call Reminders",
            description="The following weekly reminders are configured. You can edit their contents via `/reminders edit`.",
            color=0xE8C1A0
        )
        
        for rem in reminders:
            status = "✅ Enabled" if rem.get("enabled", True) else "❌ Disabled"
            time_str = f"Every {rem.get('day_of_week', 'tue').upper()} at {rem.get('hour', 8):02d}:{rem.get('minute', 30):02d} in {rem.get('timezone', 'Asia/Manila')}"
            channel_mention = f"<#{rem.get('channel_id')}>"
            
            value = (
                f"**Status:** {status}\n"
                f"**Schedule:** {time_str}\n"
                f"**Channel:** {channel_mention}\n"
                f"**Content Preview:**\n```\n{rem.get('content', '')[:200]}...\n```"
            )
            embed.add_field(name=f"🔔 {rem.get('name')} (ID: `{rem.get('id')}`)", value=value, inline=False)
            
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @reminders_group.command(name="edit", description="Edit a weekly reminder by ID")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.describe(reminder_id="The ID of the reminder to edit (e.g. monday_830_manila, monday_855_manila)")
    async def reminders_edit(self, interaction: discord.Interaction, reminder_id: str):
        path = "data/reminders.json"
        if not os.path.exists(path):
            await interaction.response.send_message("No reminders configured.", ephemeral=True)
            return
            
        try:
            with open(path, "r", encoding="utf-8") as f:
                reminders = json.load(f)
        except Exception as e:
            await interaction.response.send_message(f"Error reading reminders: {e}", ephemeral=True)
            return
            
        target = None
        for rem in reminders:
            if rem.get("id") == reminder_id:
                target = rem
                break
                
        if not target:
            await interaction.response.send_message(f"❌ Reminder with ID `{reminder_id}` not found.", ephemeral=True)
            return
            
        await interaction.response.send_modal(EditReminderModal(self, target))

    @reminders_edit.autocomplete("reminder_id")
    async def reminders_edit_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        return await self.reminder_id_autocomplete(interaction, current)

    @reminders_group.command(name="toggle", description="Toggle a weekly reminder on or off")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.describe(reminder_id="The ID of the reminder to toggle")
    async def reminders_toggle(self, interaction: discord.Interaction, reminder_id: str):
        path = "data/reminders.json"
        if not os.path.exists(path):
            await interaction.response.send_message("No reminders configured.", ephemeral=True)
            return
            
        try:
            with open(path, "r", encoding="utf-8") as f:
                reminders = json.load(f)
        except Exception as e:
            await interaction.response.send_message(f"Error reading reminders: {e}", ephemeral=True)
            return
            
        found = False
        new_status = False
        for rem in reminders:
            if rem.get("id") == reminder_id:
                rem["enabled"] = not rem.get("enabled", True)
                new_status = rem["enabled"]
                found = True
                break
                
        if not found:
            await interaction.response.send_message(f"❌ Reminder with ID `{reminder_id}` not found.", ephemeral=True)
            return
            
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(reminders, f, indent=4)
        except Exception as e:
            await interaction.response.send_message(f"Failed to save changes: {e}", ephemeral=True)
            return
            
        self.sync_weekly_reminders()
        
        status_text = "enabled" if new_status else "disabled"
        await interaction.response.send_message(f"✅ Weekly reminder `{reminder_id}` has been **{status_text}**.", ephemeral=True)

    @reminders_toggle.autocomplete("reminder_id")
    async def reminders_toggle_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        return await self.reminder_id_autocomplete(interaction, current)


async def setup(bot):
    await bot.add_cog(SchedulerCog(bot))
