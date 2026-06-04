import discord
from discord.ext import commands
from discord import app_commands
from utils.state import EmbedScript
from typing import List, Optional

class ContentModal(discord.ui.Modal, title='Edit Content'):
    ping_content = discord.ui.TextInput(label='Message Content (Outside Embed)', style=discord.TextStyle.paragraph, required=False, max_length=2000)
    embed_title = discord.ui.TextInput(label='Embed Title', style=discord.TextStyle.short, required=False, max_length=256)
    embed_desc = discord.ui.TextInput(label='Embed Description', style=discord.TextStyle.paragraph, required=False, max_length=4000)

    def __init__(self, script: EmbedScript, view: discord.ui.View):
        super().__init__()
        self.script = script
        self.hub_view = view
        
        self.ping_content.default = self.script.content
        self.embed_title.default = self.script.title
        self.embed_desc.default = self.script.description

    async def on_submit(self, interaction: discord.Interaction):
        self.script.content = self.ping_content.value
        self.script.title = self.embed_title.value
        self.script.description = self.embed_desc.value
        await self.hub_view.update_preview(interaction)

class MediaModal(discord.ui.Modal, title='Edit Media & Color'):
    image_url = discord.ui.TextInput(label='Image/Banner URL', style=discord.TextStyle.short, required=False)
    thumb_url = discord.ui.TextInput(label='Thumbnail URL', style=discord.TextStyle.short, required=False)
    color_hex = discord.ui.TextInput(label='Color (Hex, e.g., #FF0000)', style=discord.TextStyle.short, required=False, default='#E8C1A0')

    def __init__(self, script: EmbedScript, view: discord.ui.View):
        super().__init__()
        self.script = script
        self.hub_view = view
        
        self.image_url.default = self.script.image_url
        self.thumb_url.default = self.script.thumbnail_url
        if self.script.color is not None:
            self.color_hex.default = f"#{self.script.color:06x}"

    async def on_submit(self, interaction: discord.Interaction):
        self.script.image_url = self.image_url.value
        self.script.thumbnail_url = self.thumb_url.value
        if self.color_hex.value:
            try:
                hex_str = self.color_hex.value.lstrip('#')
                self.script.color = int(hex_str, 16)
            except ValueError:
                pass
        await self.hub_view.update_preview(interaction)

class ButtonAddModal(discord.ui.Modal, title='Add Button'):
    btn_label = discord.ui.TextInput(label='Button Label', style=discord.TextStyle.short, required=True, max_length=80)
    btn_url = discord.ui.TextInput(label='Button URL', style=discord.TextStyle.short, required=True)

    def __init__(self, script: EmbedScript, view: discord.ui.View):
        super().__init__()
        self.script = script
        self.hub_view = view

    async def on_submit(self, interaction: discord.Interaction):
        if len(self.script.buttons) < 10:
            self.script.buttons.append({'label': self.btn_label.value, 'url': self.btn_url.value})
        await self.hub_view.update_preview(interaction)

class ChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, script: EmbedScript, view: discord.ui.View):
        super().__init__(placeholder="Select up to 25 channels...", max_values=25, channel_types=[discord.ChannelType.text, discord.ChannelType.news])
        self.script = script
        self.hub_view = view

    async def callback(self, interaction: discord.Interaction):
        self.script.channels = self.values
        await self.hub_view.update_preview(interaction)

class EmbedEditorHub(discord.ui.View):
    def __init__(self, bot: commands.Bot, script: EmbedScript, user_id: int):
        super().__init__(timeout=900) # 15 minutes timeout
        self.bot = bot
        self.script = script
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This is not your editor session.", ephemeral=True)
            return False
        return True

    def build_action_row(self) -> discord.ui.View:
        # We recreate the view components based on state
        self.clear_items()
        
        # Row 0: Editors
        self.add_item(discord.ui.Button(label="Edit Content", style=discord.ButtonStyle.blurple, custom_id="ed:content", row=0))
        self.add_item(discord.ui.Button(label="Edit Media & Color", style=discord.ButtonStyle.blurple, custom_id="ed:media", row=0))
        self.add_item(discord.ui.Button(label="Add Link Button", style=discord.ButtonStyle.gray, custom_id="ed:add_btn", row=0, disabled=len(self.script.buttons) >= 10))
        self.add_item(discord.ui.Button(label="Clear Buttons", style=discord.ButtonStyle.red, custom_id="ed:clear_btn", row=0, disabled=len(self.script.buttons) == 0))
        
        # Row 1: Embed Management
        self.add_item(discord.ui.Button(label="Save & Add Another Embed", style=discord.ButtonStyle.green, custom_id="ed:add_embed", row=1, disabled=len(self.script.embeds_data) >= 9))
        self.add_item(discord.ui.Button(label="Clear All Embeds", style=discord.ButtonStyle.red, custom_id="ed:clear_embeds", row=1, disabled=len(self.script.embeds_data) == 0 and not (self.script.title or self.script.description)))
        
        # Row 2: Channels
        self.add_item(ChannelSelect(self.script, self))
        
        # Row 3: Execution
        self.add_item(discord.ui.Button(label="Send Now", style=discord.ButtonStyle.green, custom_id="ed:send", row=3, disabled=len(self.script.channels) == 0))
        self.add_item(discord.ui.Button(label="Schedule", style=discord.ButtonStyle.primary, custom_id="ed:schedule", row=3, disabled=len(self.script.channels) == 0))

    async def update_preview(self, interaction: discord.Interaction):
        self.build_action_row()
        
        preview_text = f"**TARGET CHANNELS ({len(self.script.channels)}):**\n"
        if self.script.channels:
            preview_text += " ".join(c.mention for c in self.script.channels)
        else:
            preview_text += "*None selected. Please select channels below.*"
            
        preview_text += f"\n\n**EMBEDS SAVED:** {len(self.script.embeds_data)}\n"
        preview_text += f"\n**BUTTONS:** {len(self.script.buttons)}\n"
            
        embeds = self.script.to_embeds(preview=True)
        content = self.script.content or ""
        
        # We send preview text outside the embed, or inside a separate tracking message
        content_preview = f"{preview_text}\n\n**--- PREVIEW ---**\n{content}"
        
        # Construct components for preview
        view_preview = discord.ui.View()
        if self.script.buttons:
            for b in self.script.buttons:
                view_preview.add_item(discord.ui.Button(label=b['label'], url=b['url'], style=discord.ButtonStyle.link))
                
        # Attach the hub controls to the view_preview
        for item in self.children:
            view_preview.add_item(item)

        try:
            await interaction.response.edit_message(content=content_preview, embeds=embeds, view=view_preview)
        except discord.errors.InteractionResponded:
            await interaction.edit_original_response(content=content_preview, embeds=embeds, view=view_preview)

    # Note: discord.py handles button callbacks via the `interaction.data['custom_id']` pattern
    # Alternatively we can use dynamic button handling in an interaction check or via persistent view logic.
    # Since we dynamically rebuild, we can handle it in `interaction_check` or a general listener, 
    # but the simplest is to override `interaction_check` or add callbacks to the buttons.
    # We will attach callbacks during `build_action_row` in a real app, but let's do it cleanly:

    async def process_button(self, interaction: discord.Interaction, custom_id: str):
        if custom_id == "ed:content":
            await interaction.response.send_modal(ContentModal(self.script, self))
        elif custom_id == "ed:media":
            await interaction.response.send_modal(MediaModal(self.script, self))
        elif custom_id == "ed:add_btn":
            await interaction.response.send_modal(ButtonAddModal(self.script, self))
        elif custom_id == "ed:clear_btn":
            self.script.buttons = []
            await self.update_preview(interaction)
        elif custom_id == "ed:add_embed":
            self.script.save_current_embed()
            await self.update_preview(interaction)
        elif custom_id == "ed:clear_embeds":
            self.script.embeds_data = []
            self.script.title = None
            self.script.description = None
            self.script.image_url = None
            self.script.thumbnail_url = None
            await self.update_preview(interaction)
        elif custom_id == "ed:send":
            await self.execute_send(interaction)
        elif custom_id == "ed:schedule":
            scheduler = self.bot.get_cog("SchedulerCog")
            if scheduler:
                await scheduler.start_schedule_workflow(interaction, self.script)
            else:
                await interaction.response.send_message("Scheduler is unavailable.", ephemeral=True)

    async def execute_send(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        embeds = self.script.to_embeds()
        content = self.script.content
        
        view = discord.ui.View()
        for b in self.script.buttons:
            view.add_item(discord.ui.Button(label=b['label'], url=b['url'], style=discord.ButtonStyle.link))
            
        success = 0
        for channel in self.script.channels:
            try:
                await channel.send(content=content, embeds=embeds, view=view)
                success += 1
            except Exception as e:
                print(f"Failed to send to {channel.name}: {e}")
                
        await interaction.followup.send(f"Successfully sent to {success}/{len(self.script.channels)} channels.")

class EmbedEditorCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type == discord.InteractionType.component:
            custom_id = interaction.data.get('custom_id', '')
            if custom_id.startswith("ed:"):
                # Find the view in cache if possible. For dynamic views built with add_item,
                # we usually need to have it cached. Since it's attached to the message,
                # discord.py's View system will route it if the View is still in memory.
                # However, because we rebuild the view, we must handle routing if we use custom_ids without decorated callbacks.
                pass 
                
    # Since dynamic buttons lose their `self` reference easily without a persistent view store,
    # let's refactor `EmbedEditorHub` to use decorated buttons to guarantee routing.
    # WAIT! The better way is to define them directly. Let me fix that.

class ActiveEmbedSelect(discord.ui.Select):
    def __init__(self, script: EmbedScript, view: discord.ui.View):
        options = [
            discord.SelectOption(
                label=f"Embed {i+1} {'(Currently Editing)' if i == script.active_embed_index else ''}", 
                value=str(i), 
                default=(i == script.active_embed_index)
            )
            for i in range(len(script.embeds_data))
        ]
        super().__init__(placeholder="Select Embed to Edit...", options=options, row=1)
        self.script = script
        self.hub_view = view

    async def callback(self, interaction: discord.Interaction):
        self.script.active_embed_index = int(self.values[0])
        await self.hub_view.update_preview(interaction)

class EmbedEditorHubV2(discord.ui.View):
    def __init__(self, bot: commands.Bot, script: EmbedScript, user_id: int):
        super().__init__(timeout=900)
        self.bot = bot
        self.script = script
        self.user_id = user_id
        self.channel_select = ChannelSelect(self.script, self)
        self.channel_select.row = 2
        
        self.refresh_ui_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This is not your editor session.", ephemeral=True)
            return False
        return True

    def save_tagged_members(self, member_ids: list[int]):
        import json
        import os
        path = os.path.join("data", "tagged_recent_members.json")
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = {"tagged": []}
        except Exception:
            data = {"tagged": []}
            
        data["tagged"] = list(set(data.get("tagged", []) + member_ids))
        
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    @discord.ui.button(label="Edit Content", style=discord.ButtonStyle.blurple, row=0)
    async def btn_content(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ContentModal(self.script, self))

    @discord.ui.button(label="Edit Media", style=discord.ButtonStyle.blurple, row=0)
    async def btn_media(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(MediaModal(self.script, self))

    @discord.ui.button(label="➕ Add Embed", style=discord.ButtonStyle.green, row=0)
    async def btn_add_embed(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.script.add_embed()
        await self.update_preview(interaction)

    @discord.ui.button(label="➖ Remove Embed", style=discord.ButtonStyle.red, row=0)
    async def btn_rem_embed(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.script.remove_embed()
        await self.update_preview(interaction)

    @discord.ui.button(label="Add Link Button", style=discord.ButtonStyle.gray, row=0)
    async def btn_add_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ButtonAddModal(self.script, self))

    @discord.ui.button(label="Send Normal Message", style=discord.ButtonStyle.blurple, row=3)
    async def btn_send_normal(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.script.channels:
            await interaction.response.send_message("You must select at least one channel.", ephemeral=True)
            return
            
        await interaction.response.defer(ephemeral=True)
        embeds = self.script.to_embeds()
        if not embeds and not self.script.content:
            await interaction.followup.send("Cannot send a completely empty message.", ephemeral=True)
            return
            
        content = self.script.content
        view = discord.ui.View()
        for b in self.script.buttons:
            view.add_item(discord.ui.Button(label=b['label'], url=b['url'], style=discord.ButtonStyle.link))
            
        success = 0
        for channel in self.script.channels:
            try:
                target = channel
                if not hasattr(target, 'send'):
                    target = self.bot.get_channel(channel.id) or await self.bot.fetch_channel(channel.id)
                
                await target.send(content=content, embeds=embeds, view=view)
                success += 1
            except Exception as e:
                channel_name = getattr(channel, 'name', f"ID: {channel.id}")
                print(f"Failed to send to {channel_name}: {e}")
                
        if success > 0 and getattr(self.script, "recent_tagged_members", []):
            self.save_tagged_members(self.script.recent_tagged_members)
            
        await interaction.followup.send(f"Successfully sent normal message to {success}/{len(self.script.channels)} channels.", ephemeral=True)

    @discord.ui.button(label="Send Now", style=discord.ButtonStyle.green, row=3)
    async def btn_send(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.script.target_message:
            await interaction.response.defer(ephemeral=True)
            embeds = self.script.to_embeds()
            if not embeds and not self.script.content:
                await interaction.followup.send("Cannot update to a completely empty message.", ephemeral=True)
                return
            
            content = self.script.content
            view = discord.ui.View()
            for b in self.script.buttons:
                view.add_item(discord.ui.Button(label=b['label'], url=b['url'], style=discord.ButtonStyle.link))
                
            try:
                await self.script.target_message.edit(content=content, embeds=embeds, view=view)
                await interaction.followup.send("Message updated successfully.", ephemeral=True)
                if getattr(self.script, "recent_tagged_members", []):
                    self.save_tagged_members(self.script.recent_tagged_members)
            except Exception as e:
                await interaction.followup.send(f"Failed to update message: {e}", ephemeral=True)
            return
            
        if not self.script.channels:
            await interaction.response.send_message("You must select at least one channel.", ephemeral=True)
            return
            
        if self.script.is_sticky_mode:
            sticky_cog = self.bot.get_cog("StickyMessagesCog")
            if sticky_cog:
                sticky_cog.save_sticky_config(self.script.channels, self.script)
                await interaction.response.send_message("Sticky configuration saved and enabled for selected channels!", ephemeral=True)
            else:
                await interaction.response.send_message("Sticky feature unavailable.", ephemeral=True)
            return
            
        await interaction.response.defer(ephemeral=True)
        embeds = self.script.to_embeds()
        if not embeds:
            await interaction.followup.send("Cannot send a completely empty message.", ephemeral=True)
            return
            
        content = self.script.content
        view = discord.ui.View()
        for b in self.script.buttons:
            view.add_item(discord.ui.Button(label=b['label'], url=b['url'], style=discord.ButtonStyle.link))
            
        success = 0
        for channel in self.script.channels:
            try:
                target = channel
                if not hasattr(target, 'send'):
                    target = self.bot.get_channel(channel.id) or await self.bot.fetch_channel(channel.id)
                
                await target.send(content=content, embeds=embeds, view=view)
                success += 1
            except Exception as e:
                channel_name = getattr(channel, 'name', f"ID: {channel.id}")
                print(f"Failed to send to {channel_name}: {e}")
                
        if success > 0 and getattr(self.script, "recent_tagged_members", []):
            self.save_tagged_members(self.script.recent_tagged_members)
            
        await interaction.followup.send(f"Successfully sent to {success}/{len(self.script.channels)} channels.", ephemeral=True)

    @discord.ui.button(label="Schedule", style=discord.ButtonStyle.primary, row=3)
    async def btn_schedule(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.script.channels:
            await interaction.response.send_message("You must select at least one channel.", ephemeral=True)
            return
        scheduler = self.bot.get_cog("SchedulerCog")
        if scheduler:
            await scheduler.start_schedule_workflow(interaction, self.script)
        else:
            await interaction.response.send_message("Scheduler is unavailable.", ephemeral=True)

    @discord.ui.button(label="Clear Buttons", style=discord.ButtonStyle.red, row=3)
    async def btn_clr_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.script.buttons = []
        await self.update_preview(interaction)

    def refresh_ui_components(self):
        self.clear_items()
        
        self.btn_add_embed.disabled = len(self.script.embeds_data) >= 10
        self.btn_rem_embed.disabled = len(self.script.embeds_data) <= 1
        self.btn_add_btn.disabled = len(self.script.buttons) >= 10
        self.btn_clr_btn.disabled = len(self.script.buttons) == 0

        self.add_item(self.btn_content)
        self.add_item(self.btn_media)
        self.add_item(self.btn_add_embed)
        self.add_item(self.btn_rem_embed)
        self.add_item(self.btn_add_btn)
        
        self.add_item(ActiveEmbedSelect(self.script, self))
        
        if not self.script.target_message:
            self.add_item(self.channel_select)
        
        if self.script.is_sticky_mode:
            self.btn_send.label = "Save & Enable Stickies"
            self.btn_send.style = discord.ButtonStyle.green
            self.add_item(self.btn_send)
            self.add_item(self.btn_send_normal)
            # Hide schedule in sticky mode
        elif self.script.target_message:
            self.btn_send.label = "Update Message"
            self.btn_send.style = discord.ButtonStyle.green
            self.add_item(self.btn_send)
            # Hide schedule in edit mode
        else:
            self.btn_send.label = "Send Now"
            self.btn_send.style = discord.ButtonStyle.green
            self.add_item(self.btn_send)
            self.add_item(self.btn_schedule)
            
        self.add_item(self.btn_clr_btn)
        
        for b in self.script.buttons:
            self.add_item(discord.ui.Button(label=b['label'], url=b['url'], style=discord.ButtonStyle.link, row=4))

    async def update_preview(self, interaction: discord.Interaction):
        self.refresh_ui_components()
        
        preview_text = f"**TARGET CHANNELS ({len(self.script.channels)}):**\n"
        if self.script.channels:
            preview_text += " ".join(c.mention for c in self.script.channels)
        else:
            preview_text += "*None selected. Please select channels below.*"
            
        preview_text += f"\n\n**EMBEDS:** {len(self.script.embeds_data)} (Currently Editing: Embed {self.script.active_embed_index + 1})\n"
        preview_text += f"**BUTTONS:** {len(self.script.buttons)}\n"
            
        embeds = self.script.to_embeds(preview=True)
        content = self.script.content or ""
        content_preview = f"{preview_text}\n\n**--- PREVIEW ---**\n{content}"
        
        try:
            await interaction.response.edit_message(content=content_preview, embeds=embeds, view=self)
        except discord.errors.InteractionResponded:
            await interaction.edit_original_response(content=content_preview, embeds=embeds, view=self)

class EmbedEditorCogFinal(commands.Cog, name="EmbedEditorCog"):
    def __init__(self, bot):
        self.bot = bot
        self.ctx_menu = app_commands.ContextMenu(
            name='Edit via Panel',
            callback=self.edit_message_context,
        )
        self.bot.tree.add_command(self.ctx_menu)

    async def cog_unload(self):
        self.bot.tree.remove_command(self.ctx_menu.name, type=self.ctx_menu.type)

    @app_commands.default_permissions(manage_messages=True)
    async def edit_message_context(self, interaction: discord.Interaction, message: discord.Message):
        if message.author != self.bot.user:
            await interaction.response.send_message("I can only edit my own messages.", ephemeral=True)
            return
            
        script = EmbedScript.from_message(message, interaction.user.id)
        await self.launch_editor_for_script(interaction, script)

    async def start_editor(self, interaction: discord.Interaction):
        script = EmbedScript(user_id=interaction.user.id)
        await self.launch_editor_for_script(interaction, script)

    async def launch_editor_for_script(self, interaction: discord.Interaction, script: EmbedScript):
        view = EmbedEditorHubV2(self.bot, script, interaction.user.id)
        
        embeds = script.to_embeds(preview=True)
        
        if script.target_message:
            preview_text = f"**EDITING EXISTING MESSAGE:** {script.target_message.jump_url}\n"
        else:
            preview_text = f"**TARGET CHANNELS ({len(script.channels)}):**\n"
            if script.channels:
                preview_text += " ".join(c.mention for c in script.channels)
            else:
                preview_text += "*None selected. Please select channels below.*\n"
                
        preview_text += f"\n**EMBEDS SAVED:** {len(script.embeds_data)}\n**BUTTONS:** {len(script.buttons)}\n\n**--- PREVIEW ---**\n{script.content or ''}"
        
        # We need a proper response whether it's deferred or not
        try:
            await interaction.response.send_message(content=preview_text, embeds=embeds, view=view, ephemeral=True)
        except discord.errors.InteractionResponded:
            await interaction.followup.send(content=preview_text, embeds=embeds, view=view, ephemeral=True)

async def setup(bot):
    await bot.add_cog(EmbedEditorCogFinal(bot))
