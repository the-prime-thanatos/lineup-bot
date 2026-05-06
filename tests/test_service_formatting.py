from __future__ import annotations

import unittest

from bot.service import ClanBotService


class ServiceFormattingTests(unittest.TestCase):
    def test_format_report_date_in_russian(self) -> None:
        formatted = ClanBotService._format_report_date(__import__("datetime").date(2026, 5, 8), "ru")

        self.assertEqual("Пт, 8 мая 2026", formatted)

    def test_format_report_date_in_english(self) -> None:
        formatted = ClanBotService._format_report_date(__import__("datetime").date(2026, 5, 8), "en")

        self.assertEqual("Fri, May 8, 2026", formatted)

    def test_format_date_range_in_russian(self) -> None:
        formatted = ClanBotService._format_date_range(
            __import__("datetime").date(2026, 5, 4),
            __import__("datetime").date(2026, 5, 10),
            "ru",
        )

        self.assertEqual("Пн, 4 мая 2026 - Вс, 10 мая 2026", formatted)

    def test_format_schedule_uses_pretty_date_and_forced_out_line(self) -> None:
        payload = {
            "date": "2026-05-08",
            "squads": [
                {
                    "name": "Squad A",
                    "starters": ["A1", "A2"],
                    "bench": ["A3"],
                    "absent": ["A4"],
                    "forced_out": ["A5"],
                    "missing_slots": 3,
                }
            ],
        }

        formatted = ClanBotService._format_schedule(payload, "ru")

        self.assertIn("Сетка на Пт, 8 мая 2026", formatted)
        self.assertIn("Отсутствуют: A4", formatted)
        self.assertIn("Исключены вручную: A5", formatted)


if __name__ == "__main__":
    unittest.main()