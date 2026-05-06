from __future__ import annotations

import unittest

from bot.platforms.discord_bot import _is_weekly_day_heading, _split_discord_message


class DiscordSplittingTests(unittest.TestCase):
    def test_weekly_report_is_split_by_day(self) -> None:
        weekly = "\n".join(
            [
                "**Недельный отчёт**",
                "Период: Пн, 4 мая 2026 - Вс, 10 мая 2026",
                "━━━━━━━━━━━━━━━━━━",
                "",
                "**Чт, 7 мая 2026 [OK]**",
                "- Squad A: 5/5 | Playing: A1, A2, A3, A4, A5",
                "",
                "**Пт, 8 мая 2026 [WARN]**",
                "- Squad A: 4/5 | Playing: A1, A2, A3, A4",
                "",
                "**Сб, 9 мая 2026 [OFF]**",
                "Tournament is cancelled for this date",
            ]
        )

        chunks = _split_discord_message(weekly)

        self.assertEqual(3, len(chunks))
        self.assertTrue(chunks[0].startswith("**Недельный отчёт**"))
        self.assertIn("**Пт, 8 мая 2026 [WARN]**", chunks[1])
        self.assertIn("**Сб, 9 мая 2026 [OFF]**", chunks[2])

    def test_non_weekly_message_falls_back_to_length_split(self) -> None:
        text = "A" * 2105

        chunks = _split_discord_message(text, limit=2000)

        self.assertEqual(2, len(chunks))
        self.assertEqual(2000, len(chunks[0]))
        self.assertEqual(105, len(chunks[1]))

    def test_weekly_heading_detection_supports_pretty_dates(self) -> None:
        self.assertTrue(_is_weekly_day_heading("**Пт, 8 мая 2026 [OK]**"))
        self.assertTrue(_is_weekly_day_heading("**Fri, May 8, 2026 [WARN]**"))
        self.assertFalse(_is_weekly_day_heading("**Недельный отчёт**"))


if __name__ == "__main__":
    unittest.main()