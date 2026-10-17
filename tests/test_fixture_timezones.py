"""Regression tests for daylight saving and published venue-local kickoff times."""

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import monitor


class FixtureTimezoneTests(unittest.TestCase):
    def test_bledisloe_sydney_october_converts_to_queensland_correctly(self):
        rows = json.loads((Path(__file__).resolve().parents[1] / "data/manual_fixtures.json").read_text())
        fixture = next(f for f in rows if f["id"] == "wallabies-2026-10-17-new-zealand")
        self.assertEqual(fixture["kickoff_local"], "2026-10-17T15:45:00")
        self.assertEqual(fixture["kickoff_timezone"], "Australia/Sydney")
        self.assertTrue(fixture.get("kickoff_source", "").startswith("https://www.rugby.com.au/"))
        normalized = monitor.normalize_manual_fixture(fixture)
        when_utc = monitor.parse_utc(normalized["date_utc"])
        self.assertEqual(when_utc, datetime(2026, 10, 17, 4, 45, tzinfo=timezone.utc))
        self.assertEqual(when_utc.astimezone(ZoneInfo("Australia/Brisbane")).strftime("%I:%M %p"), "02:45 PM")

    def test_reject_conflicting_local_and_utc_times(self):
        fixture = {
            "id": "bad-fixture",
            "kickoff_local": "2026-10-17T15:45:00",
            "kickoff_timezone": "Australia/Sydney",
            "date_utc": "2026-10-17T05:45:00Z",
        }
        with self.assertRaisesRegex(ValueError, "Conflicting UTC"):
            monitor.normalize_manual_fixture(fixture)

    def test_reject_dst_transition_ambiguities(self):
        for date_string in ("2026-10-04T02:30:00", "2026-04-05T02:30:00"):
            with self.subTest(date_string=date_string):
                fixture = {"id": "ambiguous", "kickoff_local": date_string, "kickoff_timezone": "Australia/Sydney"}
                with self.assertRaisesRegex(ValueError, "Ambiguous or nonexistent"):
                    monitor.normalize_manual_fixture(fixture)

    def test_every_manual_fixture_has_a_valid_kickoff(self):
        rows = json.loads((Path(__file__).resolve().parents[1] / "data/manual_fixtures.json").read_text())
        for fixture in rows:
            with self.subTest(fixture=fixture["id"]):
                normalized = monitor.normalize_manual_fixture(fixture)
                self.assertIsNotNone(monitor.parse_utc(normalized["date_utc"]))
                # New confirmed fixtures must carry evidence and a venue-local timestamp.
                if not fixture.get("time_tbc") and monitor.parse_utc(normalized["date_utc"]) >= datetime(2026, 10, 17, tzinfo=timezone.utc):
                    self.assertTrue(fixture.get("kickoff_local"), fixture["id"])
                    self.assertTrue(fixture.get("kickoff_timezone"), fixture["id"])
                    self.assertTrue(fixture.get("kickoff_source"), fixture["id"])


if __name__ == "__main__":
    unittest.main()
