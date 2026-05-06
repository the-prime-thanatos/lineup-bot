from __future__ import annotations

import json
import unittest
from datetime import date
from types import SimpleNamespace

from bot.scheduler import Scheduler


class SchedulerTests(unittest.TestCase):
    def test_build_day_schedule_separates_absent_and_forced_out(self) -> None:
        target_date = date(2026, 5, 8)
        saved_payload: dict | None = None

        def save_snapshot(_target_date: date, payload: dict) -> None:
            nonlocal saved_payload
            saved_payload = payload

        repo = SimpleNamespace(
            get_snapshot=lambda _target_date: None,
            load_squads_with_players=lambda: [
                SimpleNamespace(
                    name="Squad A",
                    players=[
                        SimpleNamespace(id=1, nickname="A1", order_index=0),
                        SimpleNamespace(id=2, nickname="A2", order_index=1),
                        SimpleNamespace(id=3, nickname="A3", order_index=2),
                    ],
                    rotation_index=0,
                )
            ],
            get_player_override=lambda player_id, _target_date: "out" if player_id == 2 else None,
            is_player_absent=lambda player_id, _target_date: player_id == 3,
            count_recent_starts=lambda ids, _target_date: {player_id: 0 for player_id in ids},
            save_snapshot=save_snapshot,
        )

        payload = Scheduler().build_day_schedule(repo, target_date, advance_rotation=False)

        self.assertEqual(["A1"], payload["squads"][0]["starters"])
        self.assertEqual(["A3"], payload["squads"][0]["absent"])
        self.assertEqual(["A2"], payload["squads"][0]["forced_out"])
        self.assertEqual(payload, saved_payload)

    def test_legacy_snapshot_without_forced_out_is_rebuilt(self) -> None:
        target_date = date(2026, 5, 8)
        legacy_payload = {
            "date": target_date.isoformat(),
            "squads": [
                {
                    "name": "Squad A",
                    "starters": ["A1"],
                    "bench": [],
                    "absent": [],
                    "missing_slots": 4,
                }
            ],
        }
        saved_payload: dict | None = None

        def save_snapshot(_target_date: date, payload: dict) -> None:
            nonlocal saved_payload
            saved_payload = payload

        repo = SimpleNamespace(
            get_snapshot=lambda _target_date: SimpleNamespace(payload_json=json.dumps(legacy_payload)),
            load_squads_with_players=lambda: [
                SimpleNamespace(
                    name="Squad A",
                    players=[SimpleNamespace(id=1, nickname="A1", order_index=0)],
                    rotation_index=0,
                )
            ],
            get_player_override=lambda player_id, _target_date: None,
            is_player_absent=lambda player_id, _target_date: False,
            count_recent_starts=lambda ids, _target_date: {player_id: 0 for player_id in ids},
            save_snapshot=save_snapshot,
        )

        payload = Scheduler().build_day_schedule(repo, target_date, advance_rotation=False)

        self.assertIn("forced_out", payload["squads"][0])
        self.assertEqual([], payload["squads"][0]["forced_out"])
        self.assertEqual(payload, saved_payload)

    def test_complete_snapshot_is_reused(self) -> None:
        target_date = date(2026, 5, 8)
        complete_payload = {
            "date": target_date.isoformat(),
            "squads": [
                {
                    "name": "Squad A",
                    "starters": ["A1"],
                    "bench": [],
                    "absent": [],
                    "forced_out": [],
                    "missing_slots": 4,
                }
            ],
        }

        repo = SimpleNamespace(
            get_snapshot=lambda _target_date: SimpleNamespace(payload_json=json.dumps(complete_payload)),
            load_squads_with_players=lambda: self.fail("load_squads_with_players should not be called"),
            save_snapshot=lambda _target_date, payload: self.fail("save_snapshot should not be called"),
        )

        payload = Scheduler().build_day_schedule(repo, target_date, advance_rotation=False)

        self.assertEqual(complete_payload, payload)


if __name__ == "__main__":
    unittest.main()