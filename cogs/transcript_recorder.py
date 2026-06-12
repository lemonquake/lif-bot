import html
import re
import os
import io
import aiohttp
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import discord
from discord.ext import commands
from discord import app_commands


def get_user_avatar_color(user_id: int) -> str:
    """Select a vibrant color for the fallback avatar background based on the user's ID."""
    colors = [
        "#5865F2",  # Blurple
        "#57F287",  # Green
        "#FEE75C",  # Yellow
        "#EB459E",  # Fuchsia
        "#ED4245",  # Red
        "#3498DB",  # Blue
        "#9B59B6",  # Purple
        "#E67E22",  # Orange
        "#1ABC9C",  # Teal
        "#2ECC71",  # Emerald
    ]
    return colors[user_id % len(colors)]


def get_user_initials(name: str) -> str:
    """Generate up to a 2-character uppercase abbreviation for initials."""
    parts = name.strip().split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()[:2]
    return name[:2].upper() if name else "??"


def parse_discord_markdown(content: str, guild: Optional[discord.Guild] = None) -> str:
    """
    Parses Discord basic markdown (bold, italics, underline, strike, code, codeblock)
    and resolves mentions (<@user>, <#channel>, <@&role>) to names.
    """
    if not content:
        return ""

    # 1. Escape HTML entities to prevent HTML injection
    escaped = html.escape(content)

    # 2. Extract and stash multiline codeblocks to avoid parsing markdown/newlines inside them
    code_blocks: List[str] = []
    def stash_code_block(match):
        code_blocks.append(match.group(1))
        return f"TCODEBLOCK{len(code_blocks)-1}T"

    escaped = re.sub(
        r'```(?:[a-zA-Z0-9_-]+)?\n?(.*?)\n?```',
        stash_code_block,
        escaped,
        flags=re.DOTALL
    )

    # 3. Inline code blocks
    escaped = re.sub(r'`([^`\n]+)`', r'<code>\1</code>', escaped)

    # 4. Bold: **text**
    escaped = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', escaped)

    # 5. Italics: *text* or _text_
    escaped = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', escaped)
    escaped = re.sub(r'_([^_]+)_', r'<em>\1</em>', escaped)

    # 6. Underline: __text__
    escaped = re.sub(r'__([^_]+)__', r'<u>\1</u>', escaped)

    # 7. Strikethrough: ~~text~~
    escaped = re.sub(r'~~([^~]+)~~', r'<s>\1</s>', escaped)

    # 8. Mentions Resolution
    if guild:
        # User/Member mentions: <@123456> or <@!123456>
        def replace_user(match):
            user_id = int(match.group(1))
            member = guild.get_member(user_id)
            name = member.display_name if member else f"user-{user_id}"
            return f'<span class="mention">@{html.escape(name)}</span>'
        escaped = re.sub(r'&lt;@!?(\d+)&gt;', replace_user, escaped)

        # Channel mentions: <#123456>
        def replace_channel(match):
            channel_id = int(match.group(1))
            channel = guild.get_channel(channel_id)
            name = channel.name if channel else f"deleted-channel"
            return f'<span class="mention">#{html.escape(name)}</span>'
        escaped = re.sub(r'&lt;#(\d+)&gt;', replace_channel, escaped)

        # Role mentions: <@&123456>
        def replace_role(match):
            role_id = int(match.group(1))
            role = guild.get_role(role_id)
            name = role.name if role else f"role-{role_id}"
            return f'<span class="mention">@{html.escape(name)}</span>'
        escaped = re.sub(r'&lt;@&amp;(\d+)&gt;', replace_role, escaped)

    # 9. Convert remaining newlines to <br> tags
    escaped = escaped.replace('\n', '<br>')

    # 10. Restore codeblocks
    for idx, block_content in enumerate(code_blocks):
        escaped = escaped.replace(
            f"TCODEBLOCK{idx}T",
            f'<pre><code>{block_content}</code></pre>'
        )

    return escaped


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Transcript - #{channel_name}</title>
    <style>
        :root {
            --bg-color: #1e1f22;
            --container-bg: #2b2d31;
            --text-main: #f2f3f5;
            --text-muted: #949ba4;
            --mention-bg: rgba(88, 101, 242, 0.3);
            --mention-text: #5865f2;
            --border-color: #3f4147;
            --bot-badge: #5865f2;
            --accent: #E8C1A0;
        }
        body {
            background-color: var(--bg-color);
            color: var(--text-main);
            font-family: 'Outfit', 'Inter', 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 20px;
            display: flex;
            justify-content: center;
        }
        .container {
            width: 100%;
            max-width: 900px;
            background-color: var(--container-bg);
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2);
            border: 1px solid var(--border-color);
        }
        .header {
            padding: 30px;
            background: linear-gradient(135deg, #2b2d31 0%, #1e1f22 100%);
            border-bottom: 1px solid var(--border-color);
        }
        .header-title {
            margin: 0;
            font-size: 24px;
            font-weight: 700;
            color: var(--text-main);
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .header-title span {
            color: var(--accent);
            font-size: 20px;
            font-weight: 400;
        }
        .metadata-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }
        .metadata-item {
            background-color: rgba(0, 0, 0, 0.15);
            padding: 12px;
            border-radius: 8px;
            border: 1px solid rgba(255, 255, 255, 0.05);
        }
        .metadata-label {
            font-size: 11px;
            text-transform: uppercase;
            color: var(--text-muted);
            letter-spacing: 0.5px;
            margin-bottom: 4px;
        }
        .metadata-value {
            font-size: 14px;
            font-weight: 600;
        }
        .message-list {
            padding: 24px;
            display: flex;
            flex-direction: column;
            gap: 20px;
        }
        .message-group {
            display: flex;
            gap: 16px;
        }
        .avatar-container {
            position: relative;
            width: 40px;
            height: 40px;
            flex-shrink: 0;
        }
        .avatar {
            width: 40px;
            height: 40px;
            border-radius: 50%;
            object-fit: cover;
        }
        .avatar.fallback {
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
            color: #ffffff;
            font-size: 14px;
            text-transform: uppercase;
        }
        .message-content-wrapper {
            flex-grow: 1;
            display: flex;
            flex-direction: column;
            gap: 6px;
            min-width: 0;
        }
        .message-header {
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
        }
        .author-name {
            font-weight: 600;
            color: var(--text-main);
            font-size: 15px;
        }
        .bot-badge {
            background-color: var(--bot-badge);
            color: white;
            font-size: 9px;
            padding: 2px 4px;
            border-radius: 4px;
            font-weight: bold;
            text-transform: uppercase;
        }
        .timestamp {
            font-size: 12px;
            color: var(--text-muted);
        }
        .message-item {
            display: flex;
            flex-direction: column;
            gap: 6px;
        }
        .message-text {
            font-size: 15px;
            line-height: 1.5;
            word-break: break-word;
        }
        .mention {
            background-color: var(--mention-bg);
            color: var(--mention-text);
            padding: 1px 4px;
            border-radius: 4px;
            font-weight: 500;
        }
        code {
            background-color: #1e1f22;
            padding: 2px 4px;
            border-radius: 4px;
            font-family: Consolas, Monaco, monospace;
            font-size: 13px;
        }
        pre {
            background-color: #1e1f22;
            padding: 12px;
            border-radius: 6px;
            overflow-x: auto;
            margin: 8px 0;
            border: 1px solid var(--border-color);
        }
        pre code {
            padding: 0;
            background-color: transparent;
        }
        .embed-container {
            border-left: 4px solid var(--border-color);
            background-color: #1e1f22;
            padding: 12px 16px;
            border-radius: 4px;
            margin-top: 6px;
            max-width: 520px;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        .embed-title {
            font-weight: 600;
            font-size: 14px;
        }
        .embed-description {
            font-size: 13px;
            color: var(--text-main);
            line-height: 1.4;
        }
        .embed-field {
            font-size: 13px;
            margin-top: 4px;
        }
        .embed-field-name {
            font-weight: 600;
            color: var(--text-muted);
            margin-bottom: 2px;
        }
        .attachment-container {
            display: flex;
            align-items: center;
            gap: 10px;
            background-color: #1e1f22;
            padding: 10px;
            border-radius: 6px;
            border: 1px solid var(--border-color);
            margin-top: 6px;
            width: fit-content;
            max-width: 100%;
        }
        .attachment-icon {
            font-size: 24px;
            color: var(--text-muted);
            user-select: none;
        }
        .attachment-info {
            display: flex;
            flex-direction: column;
        }
        .attachment-name {
            font-size: 13px;
            font-weight: 600;
            color: #5865f2;
            text-decoration: none;
        }
        .attachment-name:hover {
            text-decoration: underline;
        }
        .attachment-size {
            font-size: 11px;
            color: var(--text-muted);
        }
        .attachment-image {
            max-width: 100%;
            max-height: 300px;
            border-radius: 4px;
            margin-top: 6px;
            object-fit: contain;
        }
        .footer {
            padding: 20px;
            text-align: center;
            font-size: 12px;
            color: var(--text-muted);
            border-top: 1px solid var(--border-color);
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 class="header-title">📜 Ticket Transcript <span>#{channel_name}</span></h1>
            <div class="metadata-grid">
                <div class="metadata-item">
                    <div class="metadata-label">Server</div>
                    <div class="metadata-value">{server_name}</div>
                </div>
                <div class="metadata-item">
                    <div class="metadata-label">Generated By</div>
                    <div class="metadata-value">{generated_by}</div>
                </div>
                <div class="metadata-item">
                    <div class="metadata-label">Date Generated</div>
                    <div class="metadata-value">{generated_at}</div>
                </div>
                <div class="metadata-item">
                    <div class="metadata-label">Message Count</div>
                    <div class="metadata-value">{message_count}</div>
                </div>
            </div>
        </div>
        <div class="message-list">
            {messages_html}
        </div>
        <div class="footer">
            Generated by Love in Faith Bot • Ticket Transcript Recorder
        </div>
    </div>
</body>
</html>
"""


class TranscriptRecorderCog(commands.Cog, name="TranscriptRecorderCog"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        print("TranscriptRecorderCog is active.")

    @app_commands.command(name="tran", description="Summon the Transcript Recorder to record channel history, DM a Mod, and post to Slack")
    async def tran(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("❌ This command can only be used inside a server channel.", ephemeral=True)
            return

        # Defer response since compiling transcripts and calling HTTP APIs takes time
        await interaction.response.defer(ephemeral=True, thinking=True)

        channel = interaction.channel
        guild = interaction.guild

        # 1. Fetch channel message history
        messages: List[discord.Message] = []
        try:
            async for msg in channel.history(limit=None, oldest_first=True):
                messages.append(msg)
        except discord.Forbidden:
            await interaction.followup.send("❌ I do not have permission to read message history in this channel.", ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to fetch channel history: {e}", ephemeral=True)
            return

        if not messages:
            await interaction.followup.send("❌ The channel does not contain any messages to transcript.", ephemeral=True)
            return

        # 2. Extract statistics and unique participants
        participants = set()
        for msg in messages:
            if not msg.author.bot:
                participants.add(msg.author)

        generated_at_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        
        # 3. Perform grouping of consecutive messages from same user within 3 minutes
        grouped_messages = []
        current_group = None

        for msg in messages:
            if (current_group and 
                current_group["author_id"] == msg.author.id and 
                (msg.created_at - current_group["last_timestamp"]).total_seconds() < 180):
                
                current_group["messages"].append(msg)
                current_group["last_timestamp"] = msg.created_at
            else:
                if current_group:
                    grouped_messages.append(current_group)
                
                current_group = {
                    "author_id": msg.author.id,
                    "author_name": msg.author.display_name,
                    "author_avatar": msg.author.display_avatar.url,
                    "author_bot": msg.author.bot,
                    "color": get_user_avatar_color(msg.author.id),
                    "initials": get_user_initials(msg.author.display_name),
                    "first_timestamp": msg.created_at,
                    "last_timestamp": msg.created_at,
                    "messages": [msg]
                }

        if current_group:
            grouped_messages.append(current_group)

        # 4. Generate HTML transcript body
        group_htmls = []
        for group in grouped_messages:
            avatar_url = group["author_avatar"]
            avatar_color = group["color"]
            initials = html.escape(group["initials"])
            author_name = html.escape(group["author_name"])
            bot_badge = '<span class="bot-badge">Bot</span>' if group["author_bot"] else ''
            first_timestamp_str = group["first_timestamp"].strftime("%Y-%m-%d %H:%M:%S UTC")

            items_html = []
            for m in group["messages"]:
                text_html = ""
                if m.content:
                    parsed_content = parse_discord_markdown(m.content, guild=guild)
                    text_html = f'<div class="message-text">{parsed_content}</div>'

                # Process Embeds
                embeds_html = []
                for embed in m.embeds:
                    color = f"#{embed.color.value:06x}" if embed.color else "var(--border-color)"
                    emb_title = f'<div class="embed-title">{html.escape(embed.title)}</div>' if embed.title else ''
                    emb_desc = f'<div class="embed-description">{parse_discord_markdown(embed.description, guild=guild)}</div>' if embed.description else ''
                    
                    fields_html = []
                    for field in embed.fields:
                        f_name = f'<div class="embed-field-name">{html.escape(field.name)}</div>'
                        f_val = f'<div class="embed-field-value">{parse_discord_markdown(field.value, guild=guild)}</div>'
                        fields_html.append(f'<div class="embed-field">{f_name}{f_val}</div>')
                    emb_fields = "\n".join(fields_html)

                    emb_image = ''
                    if embed.image and embed.image.url:
                        emb_image = f'<img class="attachment-image" src="{embed.image.url}" />'
                    elif embed.thumbnail and embed.thumbnail.url:
                        emb_image = f'<img class="attachment-image" src="{embed.thumbnail.url}" />'

                    embeds_html.append(f"""
                    <div class="embed-container" style="border-left-color: {color};">
                        {emb_title}
                        {emb_desc}
                        {emb_fields}
                        {emb_image}
                    </div>
                    """)

                # Process Attachments
                attachments_html = []
                for att in m.attachments:
                    is_image = any(att.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp'])
                    size_str = f"{att.size / 1024:.1f} KB" if att.size < 1024 * 1024 else f"{att.size / (1024 * 1024):.1f} MB"

                    if is_image:
                        attachments_html.append(f"""
                        <img class="attachment-image" src="{att.url}" alt="{html.escape(att.filename)}" />
                        """)
                    else:
                        attachments_html.append(f"""
                        <div class="attachment-container">
                            <div class="attachment-icon">📁</div>
                            <div class="attachment-info">
                                <a class="attachment-name" href="{att.url}" target="_blank">{html.escape(att.filename)}</a>
                                <span class="attachment-size">{size_str}</span>
                            </div>
                        </div>
                        """)

                items_html.append(f"""
                <div class="message-item">
                    {text_html}
                    {"".join(embeds_html)}
                    {"".join(attachments_html)}
                </div>
                """)

            group_htmls.append(f"""
            <div class="message-group">
                <div class="avatar-container">
                    <img class="avatar" src="{avatar_url}" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';" />
                    <div class="avatar fallback" style="background-color: {avatar_color}; display: none;">{initials}</div>
                </div>
                <div class="message-content-wrapper">
                    <div class="message-header">
                        <span class="author-name">{author_name}</span>
                        {bot_badge}
                        <span class="timestamp">{first_timestamp_str}</span>
                    </div>
                    {"".join(items_html)}
                </div>
            </div>
            """)

        full_html = (
            HTML_TEMPLATE
            .replace("{channel_name}", html.escape(channel.name))
            .replace("{server_name}", html.escape(guild.name))
            .replace("{generated_by}", html.escape(interaction.user.display_name))
            .replace("{generated_at}", generated_at_str)
            .replace("{message_count}", str(len(messages)))
            .replace("{messages_html}", "\n".join(group_htmls))
        )

        file_bytes = full_html.encode("utf-8")
        filename = f"transcript-{channel.name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.html"

        # 5. Determine the Moderator user to DM
        moderator = None
        # Check if invoker has manage_messages
        if interaction.user.guild_permissions.manage_messages:
            moderator = interaction.user
        else:
            # Check for mods in the channel
            for member in channel.members:
                if member.bot:
                    continue
                perms = channel.permissions_for(member)
                if perms.manage_messages or perms.manage_channels:
                    moderator = member
                    break
            
            # Check for mods in the server
            if not moderator:
                for member in guild.members:
                    if member.bot:
                        continue
                    perms = member.guild_permissions
                    if perms.manage_messages or perms.manage_channels:
                        moderator = member
                        break
            
            # Fallback to guild owner
            if not moderator:
                moderator = guild.owner

        # Send DM to the Moderator
        dm_status = ""
        if moderator:
            dm_embed = discord.Embed(
                title="📬 Ticket Transcript Generated",
                description=f"A new ticket transcript has been recorded from **{guild.name}**.",
                color=0xE8C1A0
            )
            dm_embed.add_field(name="Ticket Channel", value=f"#{channel.name} (<#{channel.id}>)", inline=True)
            dm_embed.add_field(name="Summoned By", value=interaction.user.mention, inline=True)
            dm_embed.add_field(name="Message Count", value=str(len(messages)), inline=True)
            dm_embed.add_field(name="Support Participants", value=str(len(participants)), inline=True)
            dm_embed.timestamp = datetime.utcnow()

            html_io = io.BytesIO(file_bytes)
            discord_file = discord.File(fp=html_io, filename=filename)

            try:
                await moderator.send(embed=dm_embed, file=discord_file)
                dm_status = f"✅ Sent transcript copy to Mod {moderator.mention} via DM."
            except discord.Forbidden:
                dm_status = f"⚠️ Could not DM Mod {moderator.mention} (DMs are closed)."
            except Exception as e:
                dm_status = f"⚠️ Error sending DM to Mod: {e}"
        else:
            dm_status = "⚠️ No Moderator found to DM."

        # 6. Dispatch to Slack channel #ticket-transcripts
        slack_status = await self.dispatch_to_slack(
            channel_name="#ticket-transcripts",
            filename=filename,
            file_bytes=file_bytes,
            interaction=interaction,
            msg_count=len(messages),
            participants_count=len(participants),
            messages=messages
        )

        # 7. Complete the interaction with status report
        response_embed = discord.Embed(
            title="✅ Transcript Recorder Complete",
            description=f"Successfully compiled **{len(messages)}** message(s) from <#{channel.id}>.",
            color=0xE8C1A0
        )
        response_embed.add_field(name="Direct Messages", value=dm_status, inline=False)
        response_embed.add_field(name="Slack Integration", value=slack_status, inline=False)
        response_embed.set_footer(text="Love in Faith Ticket Utilities")
        response_embed.timestamp = datetime.utcnow()

        await interaction.followup.send(embed=response_embed, ephemeral=True)

    async def dispatch_to_slack(
        self,
        channel_name: str,
        filename: str,
        file_bytes: bytes,
        interaction: discord.Interaction,
        msg_count: int,
        participants_count: int,
        messages: List[discord.Message]
    ) -> str:
        webhook_url = os.getenv("SLACK_WEBHOOK_URL")
        bot_token = os.getenv("SLACK_BOT_TOKEN")

        if not webhook_url and not bot_token:
            return "⚠️ Slack connection is not configured in `.env` (missing SLACK_WEBHOOK_URL or SLACK_BOT_TOKEN)."

        status_messages = []
        title = f"📜 Ticket Transcript Generated - #{interaction.channel.name}"

        # 1. Attempt upload using Bot Token
        if bot_token:
            upload_url = "https://slack.com/api/files.upload"
            headers = {
                "Authorization": f"Bearer {bot_token}"
            }
            data = aiohttp.FormData()
            data.add_field("file", file_bytes, filename=filename, content_type="text/html")
            data.add_field("channels", channel_name)
            data.add_field(
                "initial_comment",
                f"New transcript uploaded for channel **#{interaction.channel.name}** "
                f"in server **{interaction.guild.name}**.\n"
                f"Generated by: @{interaction.user.display_name} • Messages: {msg_count}"
            )

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(upload_url, headers=headers, data=data) as resp:
                        if resp.status == 200:
                            result = await resp.json()
                            if result.get("ok"):
                                status_messages.append(f"✅ Uploaded transcript file directly to Slack `{channel_name}`.")
                            else:
                                err = result.get("error", "unknown Slack API error")
                                status_messages.append(f"⚠️ Slack Bot Token upload failed: {err}")
                        else:
                            status_messages.append(f"⚠️ Slack Bot Token HTTP error (Status: {resp.status})")
            except Exception as e:
                status_messages.append(f"⚠️ Exception uploading to Slack: {e}")

        # Compile plain-text transcript log lines
        text_lines = []
        for msg in messages:
            timestamp = msg.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
            author = f"@{msg.author.display_name}"
            content = msg.content or ""
            
            # Extract embed details
            for embed in msg.embeds:
                emb_parts = []
                if embed.title:
                    emb_parts.append(f"Title: {embed.title}")
                if embed.description:
                    emb_parts.append(f"Description: {embed.description}")
                for field in embed.fields:
                    emb_parts.append(f"{field.name}: {field.value}")
                if emb_parts:
                    content += f"\n  [Embed: {' | '.join(emb_parts)}]"
            
            # Extract attachments
            for att in msg.attachments:
                content += f"\n  [Attachment: {att.filename} ({att.url})]"
                
            text_lines.append(f"[{timestamp}] {author}: {content}")
            
        text_transcript = "\n".join(text_lines)

        # Chunk text transcript to fit Slack's message size limits (approx 40,000 characters)
        # We target 38,000 characters to be safely under the limit.
        max_chars = 38000
        chunks = []
        current_chunk = []
        current_len = 0

        for line in text_lines:
            line_len = len(line) + 1
            if current_len + line_len > max_chars:
                if current_chunk:
                    chunks.append("\n".join(current_chunk))
                current_chunk = [line]
                current_len = line_len
            else:
                current_chunk.append(line)
                current_len += line_len

        if current_chunk:
            chunks.append("\n".join(current_chunk))

        # 2. Attempt fallback/summary post using Webhook URL
        if webhook_url:
            # We construct a rich Slack Block Kit layout
            payload = {
                "text": title,
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": title,
                            "emoji": True
                        }
                    },
                    {
                        "type": "section",
                        "fields": [
                            {
                                "type": "mrkdwn",
                                "text": f"*Server:*\n{interaction.guild.name}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Channel:*\n#{interaction.channel.name}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Generated By:*\n@{interaction.user.display_name}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Messages:*\n{msg_count}"
                            }
                        ]
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"The full HTML transcript has been recorded and a copy has been sent to the moderator as a Direct Message. The conversation log is attached below."
                        }
                    },
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": f"Love in Faith Bot Integration • {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
                            }
                        ]
                    }
                ]
            }

            try:
                async with aiohttp.ClientSession() as session:
                    # Send summary block
                    async with session.post(webhook_url, json=payload) as resp:
                        if resp.status in (200, 201):
                            status_messages.append("✅ Posted summary card to Slack webhook.")
                        else:
                            status_messages.append(f"⚠️ Slack webhook summary HTTP error (Status: {resp.status})")
                    
                    # Send transcript chunk messages
                    for i, chunk in enumerate(chunks):
                        part_suffix = f" (Part {i+1}/{len(chunks)})" if len(chunks) > 1 else ""
                        chunk_payload = {
                            "text": f"*Conversation Log{part_suffix}:*\n```\n{chunk}\n```"
                        }
                        async with session.post(webhook_url, json=chunk_payload) as resp:
                            if resp.status in (200, 201):
                                status_messages.append(f"✅ Sent transcript log part {i+1}/{len(chunks)} to Slack webhook.")
                            else:
                                status_messages.append(f"⚠️ Slack webhook log chunk HTTP error (Status: {resp.status})")
            except Exception as e:
                status_messages.append(f"⚠️ Exception sending Slack webhook: {e}")

        return "\n".join(status_messages)


async def setup(bot):
    await bot.add_cog(TranscriptRecorderCog(bot))
