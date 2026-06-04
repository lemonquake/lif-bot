import json
import os
import re
from datetime import datetime
from typing import Any, Dict, Optional

import discord
from discord import app_commands
from discord.ext import commands


DATA_FILE = os.path.join("data", "tiktok_accounts.json")
PANEL_COLOR = 0x00F2EA


def clean_url(value: Optional[str]) -> Optional[str]:
    if not value:
        return None

    value = value.strip()
    if value.startswith("https://"):
        return value
    return None


def read_int_env(name: str) -> Optional[int]:
    value = os.getenv(name, "").strip()
    if not value:
        return None

    try:
        return int(value)
    except ValueError:
        return None


def normalize_tiktok_account(value: str) -> str:
    value = value.strip()
    match = re.search(r"tiktok\.com/@([A-Za-z0-9._-]{2,24})", value, re.IGNORECASE)
    if match:
        return f"@{match.group(1)}"

    value = value.removeprefix("https://").removeprefix("http://")
    value = value.removeprefix("www.tiktok.com/")
    value = value.strip("/ ")
    if value.startswith("@"):
        value = value[1:]

    if not re.fullmatch(r"[A-Za-z0-9._-]{2,24}", value):
        raise ValueError("Enter a TikTok handle like @creatorname or a TikTok profile link.")

    return f"@{value}"


class TikTokAccountStore:
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

    def guild_accounts(self, guild_id: int) -> Dict[str, Any]:
        return self.data.setdefault("guilds", {}).setdefault(str(guild_id), {})

    def get_account(self, guild_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        return self.guild_accounts(guild_id).get(str(user_id))

    def save_account(
        self,
        guild_id: int,
        user: discord.abc.User,
        handle: str,
        note: str,
    ) -> None:
        accounts = self.guild_accounts(guild_id)
        accounts[str(user.id)] = {
            "discord_user_id": user.id,
            "discord_name": str(user),
            "display_name": getattr(user, "display_name", user.name),
            "handle": handle,
            "profile_url": f"https://www.tiktok.com/{handle}",
            "note": note.strip(),
            "connected_at": datetime.utcnow().isoformat(),
            "status": "connected",
        }
        self.save()


class TikTokConnectModal(discord.ui.Modal, title="Connect TikTok"):
    account = discord.ui.TextInput(
        label="TikTok handle or profile link",
        placeholder="@creatorname or https://www.tiktok.com/@creatorname",
        required=True,
        max_length=120,
    )
    note = discord.ui.TextInput(
        label="Optional note",
        placeholder="Main account, shop account, ministry account, etc.",
        required=False,
        max_length=200,
    )

    def __init__(self, cog: "TikTokConnectorCog"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            handle = normalize_tiktok_account(str(self.account.value))
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        self.cog.store.save_account(
            interaction.guild_id,
            interaction.user,
            handle,
            str(self.note.value or ""),
        )

        await interaction.response.send_message(
            f"Your TikTok account is connected as **{handle}**.\n"
            f"Profile: https://www.tiktok.com/{handle}",
            ephemeral=True,
        )


class TikTokConnectorView(discord.ui.View):
    def __init__(
        self,
        cog: "TikTokConnectorCog",
        *,
        connect_url: Optional[str],
        help_url: Optional[str],
        privacy_url: Optional[str],
        support_channel_id: Optional[int],
    ):
        super().__init__(timeout=900)
        self.cog = cog
        self.connect_url = connect_url
        self.help_url = help_url
        self.privacy_url = privacy_url
        self.support_channel_id = support_channel_id

        if connect_url:
            self.add_item(
                discord.ui.Button(
                    label="Connect TikTok",
                    style=discord.ButtonStyle.link,
                    url=connect_url,
                    row=0,
                )
            )

    @discord.ui.button(label="Connect TikTok", style=discord.ButtonStyle.green, custom_id="tiktok:connect", row=0)
    async def connect_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.connect_url:
            await interaction.response.send_message(
                "Use the **Connect TikTok** link button above to open the secure TikTok authorization page.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(TikTokConnectModal(self.cog))

    @discord.ui.button(label="My Status", style=discord.ButtonStyle.blurple, custom_id="tiktok:status", row=0)
    async def status_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        account = self.cog.store.get_account(interaction.guild_id, interaction.user.id)
        if not account:
            await interaction.response.send_message(
                "No TikTok account is connected yet. Press **Connect TikTok** to add your handle or profile link.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"Connected TikTok: **{account.get('handle')}**\n"
            f"Profile: {account.get('profile_url')}\n"
            f"Status: **{account.get('status', 'connected').title()}**",
            ephemeral=True,
        )

    @discord.ui.button(label="Show Steps", style=discord.ButtonStyle.gray, custom_id="tiktok:steps", row=1)
    async def steps_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.connect_url:
            steps = (
                "1. Press the **Connect TikTok** link button.\n"
                "2. Sign in to the correct TikTok account.\n"
                "3. Review TikTok's permissions and approve.\n"
                "4. Return to Discord after the success page."
            )
        else:
            steps = (
                "1. Press **Connect TikTok**.\n"
                "2. Paste your TikTok handle or profile link.\n"
                "3. Submit the form.\n"
                "4. Use **My Status** anytime to check what is connected."
            )

        await interaction.response.send_message(f"**How to connect TikTok**\n{steps}", ephemeral=True)

    @discord.ui.button(label="Fix a Problem", style=discord.ButtonStyle.gray, custom_id="tiktok:troubleshoot", row=1)
    async def troubleshoot_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        support_line = (
            f"\n\nStill stuck? Post a screenshot in <#{self.support_channel_id}> and a team member can help."
            if self.support_channel_id
            else "\n\nStill stuck? Ask a moderator for help and include a screenshot of the issue."
        )
        await interaction.response.send_message(
            "**Quick fixes**\n"
            "- Paste your full profile link if the handle is not accepted.\n"
            "- Make sure the account is public if the team needs to review it.\n"
            "- If you connected the wrong account, press **Connect TikTok** again and submit the correct one."
            f"{support_line}",
            ephemeral=True,
        )

    @discord.ui.button(label="What Gets Shared?", style=discord.ButtonStyle.gray, custom_id="tiktok:privacy", row=2)
    async def privacy_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "**Privacy basics**\n"
            "This panel stores your Discord user ID, Discord name, TikTok handle, TikTok profile link, optional note, "
            "and the time you connected. Do not paste your TikTok password into Discord.",
            ephemeral=True,
        )


class TikTokConnectorCog(commands.Cog, name="TikTokConnectorCog"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.store = TikTokAccountStore()

    @property
    def connect_url(self) -> Optional[str]:
        return clean_url(os.getenv("TIKTOK_CONNECT_URL"))

    @property
    def help_url(self) -> Optional[str]:
        return clean_url(os.getenv("TIKTOK_HELP_URL"))

    @property
    def privacy_url(self) -> Optional[str]:
        return clean_url(os.getenv("TIKTOK_PRIVACY_URL"))

    @property
    def support_channel_id(self) -> Optional[int]:
        return read_int_env("TIKTOK_SUPPORT_CHANNEL_ID")

    def build_embed(self) -> discord.Embed:
        if self.connect_url:
            description = (
                "Connect your TikTok account in a few guided clicks. Start with the button below, sign in on TikTok, "
                "approve the connection, then come right back here."
            )
            step_one = "Press **Connect TikTok** to open the secure TikTok authorization page."
        else:
            description = (
                "Connect your TikTok account without needing to know Discord commands. Press the button below, paste "
                "your TikTok handle or profile link, and the bot will save it for this server."
            )
            step_one = "Press **Connect TikTok** and enter your TikTok handle or profile link."

        embed = discord.Embed(
            title="Connect Your TikTok",
            description=description,
            color=PANEL_COLOR,
        )
        embed.add_field(name="Step 1: Start", value=step_one, inline=False)
        embed.add_field(name="Step 2: Confirm", value="Review what you entered and submit the form.", inline=False)
        embed.add_field(name="Step 3: Check", value="Use **My Status** anytime to confirm your connected account.", inline=False)
        embed.add_field(
            name="Need help?",
            value="Use **Show Steps**, **Fix a Problem**, or **What Gets Shared?** for private guidance.",
            inline=False,
        )
        embed.set_footer(text="Love in Faith TikTok Connector")
        return embed

    def build_view(self) -> TikTokConnectorView:
        return TikTokConnectorView(
            self,
            connect_url=self.connect_url,
            help_url=self.help_url,
            privacy_url=self.privacy_url,
            support_channel_id=self.support_channel_id,
        )

    async def launch_panel(self, interaction: discord.Interaction, *, ephemeral: bool = False):
        await interaction.response.send_message(
            embed=self.build_embed(),
            view=self.build_view(),
            ephemeral=ephemeral,
        )

    @app_commands.command(name="tiktok", description="Open the guided TikTok account connection panel")
    @app_commands.describe(private="Show the connector only to you")
    async def tiktok(self, interaction: discord.Interaction, private: bool = False):
        await self.launch_panel(interaction, ephemeral=private)


async def setup(bot):
    await bot.add_cog(TikTokConnectorCog(bot))
