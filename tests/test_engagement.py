import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from cogs.engagement import EngagementStore


class FakeRole:
    def __init__(self, role_id):
        self.id = role_id


class FakeMember:
    def __init__(self, member_id, *, bot=False, role_ids=None):
        self.id = member_id
        self.bot = bot
        self.roles = [FakeRole(role_id) for role_id in (role_ids or [])]
        self.mention = f"<@{member_id}>"


class FakeGuild:
    def __init__(self, guild_id=123):
        self.id = guild_id
        self._members = {}

    def add_member(self, member):
        self._members[member.id] = member

    def get_member(self, member_id):
        return self._members.get(member_id)


def utc_date(year, month, day):
    return datetime(year, month, day, 12, 0, tzinfo=timezone.utc)


class EngagementStoreTests(unittest.TestCase):
    def make_store(self):
        tempdir = tempfile.TemporaryDirectory()
        path = Path(tempdir.name) / "engagement.json"
        store = EngagementStore(str(path))
        self.addCleanup(tempdir.cleanup)
        return store

    def test_records_messages_and_reactions_for_all_time(self):
        store = self.make_store()
        guild = FakeGuild()
        guild.add_member(FakeMember(1))

        store.record_activity(guild.id, 1, "messages", at=utc_date(2026, 5, 1))
        store.record_activity(guild.id, 1, "reactions", at=utc_date(2026, 5, 1))
        store.record_activity(guild.id, 1, "reactions", at=utc_date(2026, 5, 2))

        rows = store.leaderboard(guild, now=utc_date(2026, 5, 30))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["messages"], 1)
        self.assertEqual(rows[0]["reactions"], 2)
        self.assertEqual(rows[0]["total"], 3)

    def test_aggregates_windowed_activity(self):
        store = self.make_store()
        guild = FakeGuild()
        guild.add_member(FakeMember(1))

        store.record_activity(guild.id, 1, "messages", at=utc_date(2026, 2, 20))
        store.record_activity(guild.id, 1, "messages", at=utc_date(2026, 3, 15))
        store.record_activity(guild.id, 1, "reactions", at=utc_date(2026, 4, 20))
        store.record_activity(guild.id, 1, "reactions", at=utc_date(2026, 5, 20))

        now = utc_date(2026, 5, 30)

        last_30 = store.leaderboard(guild, window_days=30, now=now)
        last_60 = store.leaderboard(guild, window_days=60, now=now)
        last_90 = store.leaderboard(guild, window_days=90, now=now)
        all_time = store.leaderboard(guild, now=now)

        self.assertEqual(last_30[0]["total"], 1)
        self.assertEqual(last_60[0]["total"], 2)
        self.assertEqual(last_90[0]["total"], 3)
        self.assertEqual(all_time[0]["total"], 4)

    def test_excludes_bots_mod_roles_and_missing_members(self):
        store = self.make_store()
        guild = FakeGuild()
        guild.add_member(FakeMember(1))
        guild.add_member(FakeMember(2, bot=True))
        guild.add_member(FakeMember(3, role_ids=[1448734834523635712]))
        guild.add_member(FakeMember(4, role_ids=[1436388826452070481]))

        for member_id in [1, 2, 3, 4, 5]:
            store.record_activity(guild.id, member_id, "messages", at=utc_date(2026, 5, 1))

        rows = store.leaderboard(guild, now=utc_date(2026, 5, 30))

        self.assertEqual([row["member_id"] for row in rows], [1])

    def test_sorts_by_total_then_messages(self):
        store = self.make_store()
        guild = FakeGuild()
        for member_id in [1, 2, 3]:
            guild.add_member(FakeMember(member_id))

        store.record_activity(guild.id, 1, "reactions", at=utc_date(2026, 5, 1))
        store.record_activity(guild.id, 1, "reactions", at=utc_date(2026, 5, 1))
        store.record_activity(guild.id, 2, "messages", at=utc_date(2026, 5, 1))
        store.record_activity(guild.id, 2, "messages", at=utc_date(2026, 5, 1))
        store.record_activity(guild.id, 3, "messages", at=utc_date(2026, 5, 1))
        store.record_activity(guild.id, 3, "reactions", at=utc_date(2026, 5, 1))
        store.record_activity(guild.id, 3, "reactions", at=utc_date(2026, 5, 1))

        rows = store.leaderboard(guild, now=utc_date(2026, 5, 30))

        self.assertEqual([row["member_id"] for row in rows], [3, 2, 1])

    def test_once_helpers_do_not_double_count_swept_items(self):
        store = self.make_store()
        guild = FakeGuild()
        guild.add_member(FakeMember(1))

        self.assertTrue(store.record_message_once(guild.id, 1, 100, at=utc_date(2026, 5, 1)))
        self.assertFalse(store.record_message_once(guild.id, 1, 100, at=utc_date(2026, 5, 1)))
        self.assertTrue(store.record_reaction_once(guild.id, 1, "100:heart:1", at=utc_date(2026, 5, 1)))
        self.assertFalse(store.record_reaction_once(guild.id, 1, "100:heart:1", at=utc_date(2026, 5, 1)))

        rows = store.leaderboard(guild, now=utc_date(2026, 5, 30))

        self.assertEqual(rows[0]["messages"], 1)
        self.assertEqual(rows[0]["reactions"], 1)
        self.assertEqual(rows[0]["total"], 2)


if __name__ == "__main__":
    unittest.main()
