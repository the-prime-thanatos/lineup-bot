from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

import dateparser
from dateparser.search import search_dates

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None


IntentType = Literal["absence", "presence", "query", "unknown"]

_DATE_TOKEN_PATTERN = r"\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?"


@dataclass
class ParsedIntent:
    intent: IntentType
    nickname: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    raw: str = ""


class MessageParser:
    def __init__(self, openai_api_key: str, openai_model: str) -> None:
        self.openai_model = openai_model
        self.client = OpenAI(api_key=openai_api_key) if (openai_api_key and OpenAI) else None

    def parse(self, text: str, known_nicknames: list[str], today: date) -> ParsedIntent:
        raw = text.strip()
        if not raw:
            return ParsedIntent(intent="unknown", raw=text)

        ai_result = self._parse_with_ai(raw, known_nicknames)
        if ai_result:
            return ai_result

        deterministic = self._parse_deterministic(raw, known_nicknames, today)
        return deterministic

    def _parse_with_ai(self, text: str, known_nicknames: list[str]) -> ParsedIntent | None:
        if not self.client:
            return None

        prompt = {
            "role": "system",
            "content": (
                "You parse clan attendance messages in Russian/English. "
                "Return strict JSON with keys: intent, nickname, start_date, end_date. "
                "intent must be one of absence/presence/query/unknown. "
                "Dates must be ISO YYYY-MM-DD or null."
            ),
        }
        user = {
            "role": "user",
            "content": (
                f"Known nicknames: {', '.join(known_nicknames)}\n"
                f"Message: {text}"
            ),
        }

        try:
            response = self.client.responses.create(
                model=self.openai_model,
                input=[prompt, user],
                temperature=0,
            )
            output = response.output_text.strip()
            parsed = json.loads(output)

            intent = parsed.get("intent", "unknown")
            nickname = parsed.get("nickname")
            start_date = self._iso_to_date(parsed.get("start_date"))
            end_date = self._iso_to_date(parsed.get("end_date"))

            if intent not in {"absence", "presence", "query", "unknown"}:
                return None
            if intent in {"absence", "presence"} and (not nickname or not start_date):
                return None
            if intent == "query" and not start_date:
                return None

            return ParsedIntent(
                intent=intent,
                nickname=nickname,
                start_date=start_date,
                end_date=end_date or start_date,
                raw=text,
            )
        except Exception:
            return None

    def _parse_deterministic(self, text: str, known_nicknames: list[str], today: date) -> ParsedIntent:
        low = text.lower()

        if any(
            word in low
            for word in [
                "lineup",
                "calendar",
                "grid",
                "schedule",
                "week",
                "weekly",
                "сетка",
                "кто играет",
                "расписание",
                "неделя",
                "недель",
            ]
        ):
            start_date, end_date = self._extract_date_range(text, today)
            target = start_date or today
            return ParsedIntent(intent="query", start_date=target, end_date=end_date or target, raw=text)

        nickname = self._extract_nickname(text, known_nicknames)
        start_date, end_date = self._extract_date_range(text, today)

        if nickname and start_date:
            if self._is_cancellation_message(low):
                return ParsedIntent(
                    intent="presence",
                    nickname=nickname,
                    start_date=start_date,
                    end_date=end_date or start_date,
                    raw=text,
                )
            return ParsedIntent(
                intent="absence",
                nickname=nickname,
                start_date=start_date,
                end_date=end_date or start_date,
                raw=text,
            )

        return ParsedIntent(intent="unknown", raw=text)

    @staticmethod
    def _extract_nickname(text: str, known_nicknames: list[str]) -> str | None:
        low = text.lower()
        matched = [nick for nick in known_nicknames if nick.lower() in low]
        if not matched:
            return None
        return sorted(matched, key=len, reverse=True)[0]

    @staticmethod
    def _extract_date_range(text: str, today: date) -> tuple[date | None, date | None]:
        normalized = text.replace("—", "-")
        range_pattern = rf"(?:\b(?:от|с)\b\s*)?({_DATE_TOKEN_PATTERN})\s*(?:-|to|по|до)\s*({_DATE_TOKEN_PATTERN})"

        range_match = re.search(
            range_pattern,
            normalized,
            flags=re.IGNORECASE,
        )
        if range_match:
            left = MessageParser._parse_single_date(range_match.group(1), today)
            right = MessageParser._parse_single_date(range_match.group(2), today)
            if left and right:
                if range_match.group(1) and not MessageParser._token_has_year(range_match.group(2)) and right < left:
                    right = MessageParser._parse_single_date(range_match.group(2), today.replace(year=today.year + 1)) or right
                if right < left:
                    left, right = right, left
                return left, right

        until_match = re.search(
            rf"\b(?:до|по)\b\s*({_DATE_TOKEN_PATTERN})",
            normalized,
            flags=re.IGNORECASE,
        )
        if until_match:
            right = MessageParser._parse_single_date(until_match.group(1), today, prefer_future=True)
            if right:
                left = min(today, right)
                right = max(today, right)
                return left, right

        found = search_dates(
            normalized,
            languages=["ru", "en"],
            settings={
                "PREFER_DATES_FROM": "future",
                "RELATIVE_BASE": datetime.combine(today, datetime.min.time()),
            },
        )
        if found:
            dates = [item[1].date() for item in found]
            if len(dates) >= 2 and any(token in normalized.lower() for token in ["по", "to", "-"]):
                left, right = min(dates[0], dates[1]), max(dates[0], dates[1])
                return left, right
            return dates[0], dates[0]

        return None, None

    @staticmethod
    def _parse_single_date(value: str, today: date, prefer_future: bool = False) -> date | None:
        numeric = MessageParser._parse_numeric_date(value, today, prefer_future=prefer_future)
        if numeric:
            return numeric

        parsed = dateparser.parse(
            value,
            languages=["ru", "en"],
            settings={
                "PREFER_DATES_FROM": "future",
                "RELATIVE_BASE": datetime.combine(today, datetime.min.time()),
            },
        )
        return parsed.date() if parsed else None

    @staticmethod
    def _parse_numeric_date(value: str, today: date, prefer_future: bool = False) -> date | None:
        match = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?", value.strip())
        if not match:
            return None

        day = int(match.group(1))
        month = int(match.group(2))
        year_raw = match.group(3)
        year = today.year
        if year_raw:
            year = int(year_raw)
            if year < 100:
                year += 2000

        try:
            parsed = date(year, month, day)
        except ValueError:
            return None

        if not year_raw and prefer_future and parsed < today:
            try:
                parsed = date(year + 1, month, day)
            except ValueError:
                pass
        return parsed

    @staticmethod
    def _token_has_year(value: str) -> bool:
        return bool(re.fullmatch(r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}", value.strip()))

    @staticmethod
    def _iso_to_date(value: str | None) -> date | None:
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None

    @staticmethod
    def _is_cancellation_message(low_text: str) -> bool:
        cancel_markers = [
            "отмена",
            "отменяю",
            "все-таки буду",
            "всетаки буду",
            "смогу",
            "буду",
            "буду в игре",
            "буду присутствовать",
            "появлюсь",
            "will attend",
            "can attend",
            "i will be there",
        ]
        negative_markers = [
            "не буду",
            "не смогу",
            "не смогу быть",
            "not available",
            "cannot attend",
            "can't attend",
        ]
        if any(marker in low_text for marker in negative_markers):
            return False
        return any(marker in low_text for marker in cancel_markers)
