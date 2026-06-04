import discord
from typing import Optional, List, Dict, Any
from datetime import datetime

class EmbedScript:
    """Holds the state of the embed being edited."""
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.content: Optional[str] = None
        self.embeds_data: List[Dict[str, Any]] = [{}]
        self.active_embed_index: int = 0
        
        self.buttons: List[Dict[str, str]] = []
        self.channels: List[discord.TextChannel] = []
        self.schedule_time: Optional[datetime] = None
        
        # Mode flags and references
        self.target_message: Optional[discord.Message] = None
        self.is_sticky_mode: bool = False
        self.recent_tagged_members: List[int] = []

    @property
    def current_embed(self) -> Dict[str, Any]:
        return self.embeds_data[self.active_embed_index]

    @property
    def title(self): return self.current_embed.get('title')
    @title.setter
    def title(self, val): self.current_embed['title'] = val

    @property
    def description(self): return self.current_embed.get('description')
    @description.setter
    def description(self, val): self.current_embed['description'] = val

    @property
    def color(self): return self.current_embed.get('color')
    @color.setter
    def color(self, val): self.current_embed['color'] = val

    @property
    def image_url(self): return self.current_embed.get('image_url')
    @image_url.setter
    def image_url(self, val): self.current_embed['image_url'] = val

    @property
    def thumbnail_url(self): return self.current_embed.get('thumbnail_url')
    @thumbnail_url.setter
    def thumbnail_url(self, val): self.current_embed['thumbnail_url'] = val

    def add_embed(self):
        if len(self.embeds_data) < 10:
            self.embeds_data.append({})
            self.active_embed_index = len(self.embeds_data) - 1

    def remove_embed(self):
        if len(self.embeds_data) > 1:
            self.embeds_data.pop()
            if self.active_embed_index >= len(self.embeds_data):
                self.active_embed_index = len(self.embeds_data) - 1

    def to_embeds(self, preview: bool = False) -> List[discord.Embed]:
        embeds = []
        for i, data in enumerate(self.embeds_data):
            em = discord.Embed(
                title=data.get('title'),
                description=data.get('description'),
                color=data.get('color') if data.get('color') is not None else 0x2B2D31
            )
            if data.get('image_url'): em.set_image(url=data.get('image_url'))
            if data.get('thumbnail_url'): em.set_thumbnail(url=data.get('thumbnail_url'))
            
            is_empty = not em.title and not em.description and not em.image and not em.thumbnail
            if is_empty and preview:
                em.description = f"*(Embed {i+1} is empty)*"
            elif is_empty and not preview:
                continue
            embeds.append(em)
            
        if not embeds and preview:
            embeds.append(discord.Embed(description="(No embeds configured)", color=0x2B2D31))
            
        return embeds

    def to_dict(self) -> Dict[str, Any]:
        return {
            'content': self.content,
            'embeds': self.embeds_data,
            'buttons': self.buttons,
            'channel_ids': [c.id for c in self.channels] if self.channels else [],
            'recent_tagged_members': self.recent_tagged_members
        }

    @classmethod
    def from_message(cls, message: discord.Message, user_id: int) -> "EmbedScript":
        script = cls(user_id=user_id)
        script.content = message.content
        script.target_message = message
        script.embeds_data = []
        
        for em in message.embeds:
            data = {}
            if em.title: data['title'] = em.title
            if em.description: data['description'] = em.description
            if em.color: data['color'] = em.color.value
            if em.image: data['image_url'] = em.image.url
            if em.thumbnail: data['thumbnail_url'] = em.thumbnail.url
            script.embeds_data.append(data)
            
        if not script.embeds_data:
            script.embeds_data = [{}]
            
        if message.components:
            for action_row in message.components:
                for child in action_row.children:
                    if hasattr(child, 'url') and child.url:
                        script.buttons.append({'label': getattr(child, 'label', 'Link'), 'url': child.url})
        return script

    @classmethod
    def from_dict(cls, data: dict, user_id: int, bot: discord.Client = None) -> "EmbedScript":
        script = cls(user_id=user_id)
        script.content = data.get('content')
        script.embeds_data = data.get('embeds', [{}])
        if not script.embeds_data:
            script.embeds_data = [{}]
        script.buttons = data.get('buttons', [])
        script.recent_tagged_members = data.get('recent_tagged_members', [])
        
        if bot and 'channel_ids' in data:
            for c_id in data['channel_ids']:
                ch = bot.get_channel(c_id)
                if ch:
                    script.channels.append(ch)
                    
        return script
