import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from utils.time_utils import generate_date_options, generate_hour_options, generate_minute_options, parse_schedule_time
from utils.state import EmbedScript
from datetime import datetime

class ScheduleView(discord.ui.View):
    def __init__(self, bot: commands.Bot, script: EmbedScript):
        super().__init__(timeout=900)
        self.bot = bot
        self.script = script
        self.selected_date = None
        self.selected_hour = None
        self.selected_minute = None
        self.selected_tz = "UTC" # Default

        self.build_ui()

    def build_ui(self):
        self.clear_items()
        
        # 1. Date Select
        date_opts = generate_date_options(14)
        date_select = discord.ui.Select(placeholder="Select Date...", custom_id="sch:date", options=[
            discord.SelectOption(label=l, value=v) for l, v in date_opts
        ], row=0)
        date_select.callback = self.date_callback
        self.add_item(date_select)

        # 2. Hour Select
        hour_opts = generate_hour_options()
        hour_select = discord.ui.Select(placeholder="Select Hour...", custom_id="sch:hour", options=[
            discord.SelectOption(label=l, value=v) for l, v in hour_opts
        ], row=1) 
        hour_select.callback = self.hour_callback
        self.add_item(hour_select)

        # 3. Minute Select
        minute_opts = generate_minute_options()
        minute_select = discord.ui.Select(placeholder="Select Minute...", custom_id="sch:minute", options=[
            discord.SelectOption(label=l, value=v) for l, v in minute_opts
        ], row=2)
        minute_select.callback = self.minute_callback
        self.add_item(minute_select)

        # 4. TZ Select
        tz_select = discord.ui.Select(placeholder="Timezone...", custom_id="sch:tz", options=[
            discord.SelectOption(label="UTC", value="UTC"),
            discord.SelectOption(label="Eastern Time", value="America/New_York"),
            discord.SelectOption(label="Central Time", value="America/Chicago"),
            discord.SelectOption(label="Mountain Time", value="America/Denver"),
            discord.SelectOption(label="Pacific Time (PST)", value="America/Los_Angeles"),
            discord.SelectOption(label="Singapore Time (GMT+8)", value="Asia/Singapore"),
        ], row=3)
        tz_select.callback = self.tz_callback
        self.add_item(tz_select)

        # 4. Confirm Button
        confirm_btn = discord.ui.Button(label="Confirm Schedule", style=discord.ButtonStyle.green, row=4)
        confirm_btn.callback = self.confirm_callback
        self.add_item(confirm_btn)

    async def date_callback(self, interaction: discord.Interaction):
        self.selected_date = interaction.data['values'][0]
        await self.update_status(interaction)

    async def hour_callback(self, interaction: discord.Interaction):
        self.selected_hour = interaction.data['values'][0]
        await self.update_status(interaction)

    async def minute_callback(self, interaction: discord.Interaction):
        self.selected_minute = interaction.data['values'][0]
        await self.update_status(interaction)

    async def tz_callback(self, interaction: discord.Interaction):
        self.selected_tz = interaction.data['values'][0]
        await self.update_status(interaction)

    async def update_status(self, interaction: discord.Interaction):
        time_str = "None"
        if self.selected_hour is not None and self.selected_minute is not None:
            h = int(self.selected_hour)
            m = int(self.selected_minute)
            period = "AM" if h < 12 else "PM"
            dh = h if h != 0 else 12
            if dh > 12: dh -= 12
            time_str = f"{dh}:{m:02d} {period}"
            
        msg = f"**Current Selection:**\nDate: {self.selected_date or 'None'}\nTime: {time_str}\nTimezone: {self.selected_tz}"
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
        
        if dt_utc < datetime.utcnow().replace(tzinfo=dt_utc.tzinfo):
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


class SchedulerCog(commands.Cog, name="SchedulerCog"):
    def __init__(self, bot):
        self.bot = bot
        global _bot_instance
        _bot_instance = bot
        
        jobstores = {
            'default': SQLAlchemyJobStore(url='sqlite:///data/jobstore.db')
        }
        self.scheduler = AsyncIOScheduler(jobstores=jobstores)
        self.scheduler.start()

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
            content="**Current Selection:**\nDate: None\nTime: None\nTimezone: UTC", 
            view=view, 
            ephemeral=True
        )

async def setup(bot):
    await bot.add_cog(SchedulerCog(bot))
