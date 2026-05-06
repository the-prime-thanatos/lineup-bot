from __future__ import annotations

import unittest
from datetime import date

from bot.parsing import MessageParser


class MessageParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = MessageParser("", "")
        self.today = date(2026, 5, 6)
        self.nicknames = ["Nickname"]

    def test_parses_absence_range_with_ot_prefix(self) -> None:
        parsed = self.parser.parse("Nickname не буду от 05.05-10.06", self.nicknames, self.today)

        self.assertEqual("absence", parsed.intent)
        self.assertEqual("Nickname", parsed.nickname)
        self.assertEqual(date(2026, 5, 5), parsed.start_date)
        self.assertEqual(date(2026, 6, 10), parsed.end_date)

    def test_parses_absence_range_with_s_prefix(self) -> None:
        parsed = self.parser.parse("Nickname отсутствую с 05.05-10.06", self.nicknames, self.today)

        self.assertEqual("absence", parsed.intent)
        self.assertEqual(date(2026, 5, 5), parsed.start_date)
        self.assertEqual(date(2026, 6, 10), parsed.end_date)

    def test_parses_until_date_as_open_ended_absence(self) -> None:
        parsed = self.parser.parse("Nickname не смогу учавствовать до 10.09", self.nicknames, self.today)

        self.assertEqual("absence", parsed.intent)
        self.assertEqual(date(2026, 5, 6), parsed.start_date)
        self.assertEqual(date(2026, 9, 10), parsed.end_date)

    def test_existing_range_phrase_still_works(self) -> None:
        parsed = self.parser.parse("Nickname не смогу 08.05-10.05", self.nicknames, self.today)

        self.assertEqual("absence", parsed.intent)
        self.assertEqual(date(2026, 5, 8), parsed.start_date)
        self.assertEqual(date(2026, 5, 10), parsed.end_date)

    def test_without_nickname_parser_stays_unknown(self) -> None:
        parsed = self.parser.parse("не буду от 05.05-10.06", self.nicknames, self.today)

        self.assertEqual("unknown", parsed.intent)


if __name__ == "__main__":
    unittest.main()