import asyncio
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from cogs.onboarding import (
    DELIVERY_CHANNEL,
    DELIVERY_DM,
    DEFAULT_DM_MESSAGE_TEMPLATE,
    DEFAULT_PUBLIC_MESSAGE_TEMPLATE,
    OnboardingCog,
    OnboardingStore,
    parse_template_block,
)


MANILA = ZoneInfo("Asia/Manila")


class FakeMember:
    def __init__(self, member_id, guild, joined_local, display_name=None, bot=False, dm_fails=False):
        self.id = member_id
        self.guild = guild
        self.joined_at = joined_local.astimezone(timezone.utc)
        self.display_name = display_name or f"Member {member_id}"
        self.mention = f"<@{member_id}>"
        self.bot = bot
        self.dm_fails = dm_fails
        self.sent_dms = []

    def __str__(self):
        return f"{self.display_name}#0000"

    async def send(self, content):
        if self.dm_fails:
            raise RuntimeError("DM blocked")
        self.sent_dms.append(content)


class FakeGuild:
    def __init__(self, guild_id=123):
        self.id = guild_id
        self.members = []

    def get_member(self, member_id):
        for member in self.members:
            if member.id == member_id:
                return member
        return None


class FakeChannel:
    def __init__(self):
        self.sent = []

    async def send(self, **kwargs):
        self.sent.append(kwargs)


class FakeBot:
    def __init__(self, guild=None, channel=None):
        self.guild = guild
        self.channel = channel

    def get_guild(self, guild_id):
        return self.guild if self.guild and self.guild.id == guild_id else None

    def get_channel(self, channel_id):
        return self.channel

    async def fetch_channel(self, channel_id):
        return self.channel

    def get_cog(self, name):
        return None


def local_datetime(days_ago):
    return datetime(2026, 5, 15 - days_ago, 10, 0, tzinfo=MANILA)


class OnboardingStoreTests(unittest.TestCase):
    def make_store(self):
        tempdir = tempfile.TemporaryDirectory()
        path = Path(tempdir.name) / "onboarding.json"
        store = OnboardingStore(str(path))
        self.addCleanup(tempdir.cleanup)
        return store

    def test_groups_last_three_days_and_excludes_existing_welcomed(self):
        store = self.make_store()
        guild = FakeGuild()
        members = [
            FakeMember(1, guild, local_datetime(0), "Today"),
            FakeMember(2, guild, local_datetime(1), "Yesterday"),
            FakeMember(3, guild, local_datetime(2), "Two Days"),
            FakeMember(4, guild, local_datetime(3), "Three Days"),
            FakeMember(5, guild, local_datetime(4), "Outside"),
        ]
        guild.members = members
        store.settings(guild.id)["timezone"] = "Asia/Manila"
        store.record_member(members[2])
        store.mark_welcomed(guild.id, [3])

        groups = store.pending_groups(guild, now=local_datetime(0), scan=True)

        self.assertEqual([member["id"] for member in groups["2026-05-15"]], [1])
        self.assertEqual([member["id"] for member in groups["2026-05-14"]], [2])
        self.assertEqual(groups["2026-05-13"], [])
        self.assertEqual([member["id"] for member in groups["2026-05-12"]], [4])
        self.assertNotIn("2026-05-11", groups)

    def test_scan_does_not_mark_members_welcomed(self):
        store = self.make_store()
        guild = FakeGuild()
        guild.members = [FakeMember(1, guild, local_datetime(0), "Today")]

        store.pending_groups(guild, now=local_datetime(0), scan=True)

        state = store.guild_state(guild.id)
        self.assertIsNone(state["members"]["1"]["welcomed_at"])

    def test_public_templates_parse_and_default_to_glo_creatorverse(self):
        store = self.make_store()
        settings = store.settings(123)

        self.assertIn("GLO Creatorverse", settings["public_message_templates"][0])

        store.update_settings(
            123,
            channel_id=456,
            timezone_name="Asia/Manila",
            delivery_mode=DELIVERY_CHANNEL,
            public_message_templates=parse_template_block("Template A {mentions}\n---\nTemplate B"),
            dm_message_template=DEFAULT_DM_MESSAGE_TEMPLATE,
        )

        templates = store.public_templates(123)
        self.assertEqual(len(templates), 2)
        self.assertEqual(templates[0], "Template A {mentions}")
        self.assertEqual(templates[1], "Template B\n\n{mentions}")


class OnboardingSendTests(unittest.IsolatedAsyncioTestCase):
    def make_cog(self, guild, channel=None):
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        bot = FakeBot(guild=guild, channel=channel)
        cog = OnboardingCog(bot)
        cog.store = OnboardingStore(str(Path(tempdir.name) / "onboarding.json"))
        settings = cog.store.settings(guild.id)
        settings["enabled"] = True
        settings["timezone"] = "Asia/Manila"
        settings["public_message_template"] = DEFAULT_PUBLIC_MESSAGE_TEMPLATE
        settings["dm_message_template"] = DEFAULT_DM_MESSAGE_TEMPLATE
        return cog

    async def test_public_send_marks_all_members_after_successful_channel_post(self):
        guild = FakeGuild()
        channel = FakeChannel()
        guild.members = [
            FakeMember(1, guild, local_datetime(0), "Today One"),
            FakeMember(2, guild, local_datetime(0), "Today Two"),
        ]
        cog = self.make_cog(guild, channel)

        result = await cog.send_latest_group(guild, DELIVERY_CHANNEL)

        self.assertIn("tagged 2 new member", result)
        self.assertEqual(len(channel.sent), 1)
        state = cog.store.guild_state(guild.id)
        self.assertIsNotNone(state["members"]["1"]["welcomed_at"])
        self.assertIsNotNone(state["members"]["2"]["welcomed_at"])

    async def test_public_send_uses_selected_template_index(self):
        guild = FakeGuild()
        channel = FakeChannel()
        guild.members = [FakeMember(1, guild, local_datetime(0), "Today One")]
        cog = self.make_cog(guild, channel)
        cog.store.update_settings(
            guild.id,
            channel_id=456,
            timezone_name="Asia/Manila",
            delivery_mode=DELIVERY_CHANNEL,
            public_message_templates=[
                "First template {mentions}",
                "Second template for {join_day}: {mentions}",
            ],
            dm_message_template=DEFAULT_DM_MESSAGE_TEMPLATE,
        )

        result = await cog.send_latest_group(guild, DELIVERY_CHANNEL, template_index=1)

        self.assertIn("tagged 1 new member", result)
        self.assertIn("Second template", channel.sent[0]["content"])

    async def test_dm_send_marks_only_successful_members(self):
        guild = FakeGuild()
        guild.members = [
            FakeMember(1, guild, local_datetime(0), "Can DM"),
            FakeMember(2, guild, local_datetime(0), "Blocked DM", dm_fails=True),
        ]
        cog = self.make_cog(guild)

        result = await cog.send_latest_group(guild, DELIVERY_DM)
        await asyncio.sleep(0)

        self.assertIn("Sent 1 DM", result)
        self.assertIn("Failed to DM 1", result)
        state = cog.store.guild_state(guild.id)
        self.assertIsNotNone(state["members"]["1"]["welcomed_at"])
        self.assertIsNone(state["members"]["2"]["welcomed_at"])


if __name__ == "__main__":
    unittest.main()
