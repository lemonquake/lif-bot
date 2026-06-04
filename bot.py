import discord
from discord.ext import commands
import os


def load_env_file(path: str = ".env") -> None:
    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8-sig") as fp:
        for raw_line in fp:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            if line.lower().startswith("export "):
                line = line[7:].strip()

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'\"")

            if key and key not in os.environ:
                os.environ[key] = value


load_env_file()

TOKEN = os.getenv("DISCORD_TOKEN")
APP_ID = int(os.getenv("DISCORD_APP_ID", "1502327747832185023"))

class LoveInFaithBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guild_messages = True
        intents.guild_reactions = True
        intents.message_content = True
        intents.members = True
        
        super().__init__(
            command_prefix="!",
            intents=intents,
            application_id=APP_ID
        )

    async def setup_hook(self):
        print("Loading extensions...")
        # Load cogs
        cogs = [
            'cogs.mod_panel',
            'cogs.embed_editor',
            'cogs.scheduler',
            'cogs.sticky_messages',
            'cogs.onboarding',
            'cogs.audit_logs',
            'cogs.live_stats',
            'cogs.tiktok_connector',
            'cogs.engagement',
        ]
        for cog in cogs:
            try:
                await self.load_extension(cog)
                print(f"Loaded {cog}")
            except Exception as e:
                print(f"Failed to load {cog}: {e}")

        # Ensure data folder exists
        os.makedirs("data", exist_ok=True)

        print("Syncing command tree...")
        await self.tree.sync()
        print("Tree synced.")

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print("Love in Faith Bot is ready.")

if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN is not set. Set it as an environment variable before starting the bot.")

    bot = LoveInFaithBot()
    bot.run(TOKEN)
