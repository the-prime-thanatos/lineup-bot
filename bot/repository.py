from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import and_, delete, func, select
from sqlalchemy.orm import Session, joinedload

from bot.models import Absence, Player, ScheduleSnapshot, Squad
from bot.models import BotSetting
from bot.models import AuditLog, PlayerIdentity, PlayerOverride, ProcessedMessage


class Repository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def seed_roster_if_empty(self, roster_file: str) -> bool:
        squad_count = self.session.scalar(select(func.count()).select_from(Squad))
        if squad_count and squad_count > 0:
            return False

        data = json.loads(Path(roster_file).read_text(encoding="utf-8"))
        for squad_data in data.get("squads", []):
            squad = Squad(name=squad_data["name"], rotation_index=0)
            self.session.add(squad)
            self.session.flush()
            for idx, nick in enumerate(squad_data.get("players", [])):
                self.session.add(Player(nickname=nick, squad_id=squad.id, order_index=idx))
        return True

    def replace_roster_from_file(self, roster_file: str) -> tuple[int, int]:
        data = json.loads(Path(roster_file).read_text(encoding="utf-8"))
        self._validate_roster_payload(data)
        return self.replace_roster_from_payload(data)

    def replace_roster_from_json_text(self, json_text: str) -> tuple[int, int]:
        data = json.loads(json_text)
        self._validate_roster_payload(data)
        return self.replace_roster_from_payload(data)

    def replace_roster_from_payload(self, data: dict[str, Any]) -> tuple[int, int]:
        self.session.execute(delete(Player))
        self.session.execute(delete(Squad))
        self.session.execute(delete(ScheduleSnapshot))

        squads_created = 0
        players_created = 0
        for squad_data in data.get("squads", []):
            squad = Squad(name=squad_data["name"], rotation_index=0)
            self.session.add(squad)
            self.session.flush()
            squads_created += 1
            for idx, nick in enumerate(squad_data.get("players", [])):
                self.session.add(Player(nickname=nick, squad_id=squad.id, order_index=idx))
                players_created += 1

        return squads_created, players_created

    @staticmethod
    def roster_template() -> dict[str, Any]:
        return {
            "squads": [
                {
                    "name": "Squad A",
                    "players": ["PlayerOne", "PlayerTwo", "PlayerThree", "PlayerFour", "PlayerFive"],
                },
                {
                    "name": "Squad B",
                    "players": ["PlayerSix", "PlayerSeven", "PlayerEight", "PlayerNine", "PlayerTen"],
                },
            ]
        }

    def roster_payload(self) -> dict[str, Any]:
        squads = self.load_squads_with_players()
        payload: dict[str, Any] = {"squads": []}
        for squad in squads:
            players = [p.nickname for p in sorted(squad.players, key=lambda x: x.order_index)]
            payload["squads"].append({"name": squad.name, "players": players})
        return payload

    @staticmethod
    def _validate_roster_payload(data: dict[str, Any]) -> None:
        squads = data.get("squads")
        if not isinstance(squads, list) or not squads:
            raise ValueError("Invalid roster format: 'squads' must be a non-empty list.")

        seen_nicknames: set[str] = set()
        for squad in squads:
            if not isinstance(squad, dict):
                raise ValueError("Invalid roster format: each squad must be an object.")

            name = squad.get("name")
            players = squad.get("players")
            if not isinstance(name, str) or not name.strip():
                raise ValueError("Invalid roster format: each squad must have a non-empty 'name'.")
            if not isinstance(players, list) or not players:
                raise ValueError("Invalid roster format: each squad must have a non-empty 'players' list.")

            for nick in players:
                if not isinstance(nick, str) or not nick.strip():
                    raise ValueError("Invalid roster format: player nickname must be a non-empty string.")
                normalized = nick.strip().lower()
                if normalized in seen_nicknames:
                    raise ValueError(f"Duplicate nickname in roster: {nick}")
                seen_nicknames.add(normalized)

    def all_nicknames(self) -> list[str]:
        rows = self.session.scalars(select(Player.nickname).order_by(Player.nickname)).all()
        return list(rows)

    def find_player_by_nickname(self, nickname: str) -> Player | None:
        nick = nickname.strip().lower()
        query = select(Player).where(func.lower(Player.nickname) == nick)
        return self.session.scalar(query)

    def find_player_by_identity(self, source: str, external_user_id: str) -> Player | None:
        stmt = (
            select(Player)
            .join(PlayerIdentity, PlayerIdentity.player_id == Player.id)
            .where(
                and_(
                    PlayerIdentity.source == source,
                    PlayerIdentity.external_user_id == external_user_id,
                )
            )
        )
        return self.session.scalar(stmt)

    def bind_identity(
        self,
        source: str,
        external_user_id: str,
        external_username: str,
        nickname: str,
    ) -> tuple[bool, str]:
        player = self.find_player_by_nickname(nickname)
        if not player:
            return False, "Игрок с таким ником не найден."

        existing = self.session.scalar(
            select(PlayerIdentity).where(
                and_(
                    PlayerIdentity.source == source,
                    PlayerIdentity.external_user_id == external_user_id,
                )
            )
        )
        if existing:
            existing.player_id = player.id
            existing.external_username = external_username
        else:
            self.session.add(
                PlayerIdentity(
                    source=source,
                    external_user_id=external_user_id,
                    external_username=external_username,
                    player_id=player.id,
                )
            )
        return True, f"Аккаунт привязан к нику {player.nickname}."

    def is_message_processed(self, source: str, external_message_id: str) -> bool:
        stmt = select(ProcessedMessage.id).where(
            and_(
                ProcessedMessage.source == source,
                ProcessedMessage.external_message_id == external_message_id,
            )
        )
        return self.session.scalar(stmt) is not None

    def mark_message_processed(self, source: str, external_message_id: str) -> None:
        self.session.add(
            ProcessedMessage(source=source, external_message_id=external_message_id)
        )

    def list_squads(self) -> list[Squad]:
        stmt = select(Squad).order_by(Squad.name)
        return list(self.session.scalars(stmt).all())

    def find_squad_by_name(self, squad_name: str) -> Squad | None:
        name = squad_name.strip().lower()
        stmt = select(Squad).where(func.lower(Squad.name) == name)
        return self.session.scalar(stmt)

    def add_player(self, squad_name: str, nickname: str) -> tuple[bool, str]:
        if self.find_player_by_nickname(nickname):
            return False, "Игрок с таким ником уже существует."

        squad = self.find_squad_by_name(squad_name)
        if not squad:
            return False, "Отряд не найден."

        current_max = self.session.scalar(
            select(func.max(Player.order_index)).where(Player.squad_id == squad.id)
        )
        next_index = (current_max + 1) if current_max is not None else 0
        self.session.add(Player(nickname=nickname.strip(), squad_id=squad.id, order_index=next_index))
        self.session.execute(delete(ScheduleSnapshot))
        return True, "Игрок добавлен."

    def remove_player(self, nickname: str) -> tuple[bool, str]:
        player = self.find_player_by_nickname(nickname)
        if not player:
            return False, "Игрок не найден."

        squad_id = player.squad_id
        self.session.delete(player)
        self._normalize_order_indices(squad_id)
        self.session.execute(delete(ScheduleSnapshot))
        return True, "Игрок удален."

    def move_player(self, nickname: str, squad_name: str) -> tuple[bool, str]:
        player = self.find_player_by_nickname(nickname)
        if not player:
            return False, "Игрок не найден."

        target_squad = self.find_squad_by_name(squad_name)
        if not target_squad:
            return False, "Целевой отряд не найден."

        old_squad_id = player.squad_id
        max_index = self.session.scalar(
            select(func.max(Player.order_index)).where(Player.squad_id == target_squad.id)
        )
        player.squad_id = target_squad.id
        player.order_index = (max_index + 1) if max_index is not None else 0

        self._normalize_order_indices(old_squad_id)
        self.session.execute(delete(ScheduleSnapshot))
        return True, "Игрок перемещен."

    def set_rotation_index(self, squad_name: str, index: int) -> tuple[bool, str]:
        squad = self.find_squad_by_name(squad_name)
        if not squad:
            return False, "Отряд не найден."

        count = self.session.scalar(select(func.count()).select_from(Player).where(Player.squad_id == squad.id)) or 0
        if count <= 0:
            squad.rotation_index = 0
        else:
            squad.rotation_index = index % count
        self.session.execute(delete(ScheduleSnapshot))
        return True, f"Индекс ротации установлен: {squad.rotation_index}."

    def add_absence(
        self,
        player_id: int,
        start_date: date,
        end_date: date,
        source: str,
        raw_text: str,
    ) -> None:
        self.session.add(
            Absence(
                player_id=player_id,
                start_date=start_date,
                end_date=end_date,
                source=source,
                raw_text=raw_text,
            )
        )

    def remove_absences_for_player_range(self, player_id: int, start_date: date, end_date: date) -> int:
        stmt = delete(Absence).where(
            and_(
                Absence.player_id == player_id,
                Absence.start_date <= end_date,
                Absence.end_date >= start_date,
            )
        )
        result = self.session.execute(stmt)
        return result.rowcount or 0

    def set_player_override(self, player_id: int, match_date: date, force_state: str) -> None:
        row = self.session.scalar(
            select(PlayerOverride).where(
                and_(
                    PlayerOverride.player_id == player_id,
                    PlayerOverride.match_date == match_date,
                )
            )
        )
        if row:
            row.force_state = force_state
        else:
            self.session.add(
                PlayerOverride(player_id=player_id, match_date=match_date, force_state=force_state)
            )
        self.session.execute(delete(ScheduleSnapshot).where(ScheduleSnapshot.match_date == match_date))

    def clear_player_override(self, player_id: int, match_date: date) -> int:
        result = self.session.execute(
            delete(PlayerOverride).where(
                and_(
                    PlayerOverride.player_id == player_id,
                    PlayerOverride.match_date == match_date,
                )
            )
        )
        self.session.execute(delete(ScheduleSnapshot).where(ScheduleSnapshot.match_date == match_date))
        return result.rowcount or 0

    def get_player_override(self, player_id: int, match_date: date) -> str | None:
        stmt = select(PlayerOverride.force_state).where(
            and_(
                PlayerOverride.player_id == player_id,
                PlayerOverride.match_date == match_date,
            )
        )
        return self.session.scalar(stmt)

    def delete_snapshots_between(self, start_date: date, end_date: date) -> int:
        stmt = delete(ScheduleSnapshot).where(
            and_(
                ScheduleSnapshot.match_date >= start_date,
                ScheduleSnapshot.match_date <= end_date,
            )
        )
        result = self.session.execute(stmt)
        return result.rowcount or 0

    def load_squads_with_players(self) -> list[Squad]:
        stmt = (
            select(Squad)
            .options(joinedload(Squad.players))
            .order_by(Squad.name)
        )
        return list(self.session.scalars(stmt).unique().all())

    def clear_all_snapshots(self) -> int:
        result = self.session.execute(delete(ScheduleSnapshot))
        return result.rowcount or 0

    def is_player_absent(self, player_id: int, target_date: date) -> bool:
        stmt = select(Absence.id).where(
            and_(
                Absence.player_id == player_id,
                Absence.start_date <= target_date,
                Absence.end_date >= target_date,
            )
        )
        return self.session.scalar(stmt) is not None

    def get_snapshot(self, target_date: date) -> ScheduleSnapshot | None:
        stmt = select(ScheduleSnapshot).where(ScheduleSnapshot.match_date == target_date)
        return self.session.scalar(stmt)

    def save_snapshot(self, target_date: date, payload: dict) -> None:
        snapshot = ScheduleSnapshot(
            match_date=target_date,
            payload_json=json.dumps(payload, ensure_ascii=False),
        )
        self.session.add(snapshot)

    def count_recent_starts(self, player_ids: list[int], before_date: date, days_window: int = 42) -> dict[int, int]:
        if not player_ids:
            return {}

        since = before_date - timedelta(days=days_window)
        rows = self.session.scalars(
            select(ScheduleSnapshot)
            .where(
                and_(
                    ScheduleSnapshot.match_date < before_date,
                    ScheduleSnapshot.match_date >= since,
                )
            )
            .order_by(ScheduleSnapshot.match_date.desc())
        ).all()

        counts = {pid: 0 for pid in player_ids}
        nick_to_id = {
            player.nickname: player.id
            for player in self.session.scalars(select(Player).where(Player.id.in_(player_ids))).all()
        }

        for row in rows:
            payload = json.loads(row.payload_json)
            for squad in payload.get("squads", []):
                for nickname in squad.get("starters", []):
                    pid = nick_to_id.get(nickname)
                    if pid is not None:
                        counts[pid] += 1
        return counts

    def add_audit_log(self, actor_source: str, actor_user_id: str, action: str, details: dict) -> None:
        self.session.add(
            AuditLog(
                actor_source=actor_source,
                actor_user_id=actor_user_id,
                action=action,
                details_json=json.dumps(details, ensure_ascii=False),
            )
        )

    def _normalize_order_indices(self, squad_id: int) -> None:
        players = self.session.scalars(
            select(Player).where(Player.squad_id == squad_id).order_by(Player.order_index, Player.id)
        ).all()
        for idx, player in enumerate(players):
            player.order_index = idx

    def get_setting(self, key: str) -> str | None:
        row = self.session.scalar(select(BotSetting).where(BotSetting.key == key))
        return row.value if row else None

    def set_setting(self, key: str, value: str) -> None:
        row = self.session.scalar(select(BotSetting).where(BotSetting.key == key))
        if row:
            row.value = value
        else:
            self.session.add(BotSetting(key=key, value=value))

    def get_tournament_weekdays(self, default_weekdays: set[int]) -> set[int]:
        raw = (self.get_setting("tournament_weekdays") or "").strip()
        if not raw:
            return set(default_weekdays)
        weekdays = {
            int(day.strip())
            for day in raw.split(",")
            if day.strip().isdigit() and 0 <= int(day.strip()) <= 6
        }
        return weekdays or set(default_weekdays)

    def set_tournament_weekdays(self, weekdays: set[int]) -> None:
        value = ",".join(str(day) for day in sorted(weekdays))
        self.set_setting("tournament_weekdays", value)

    def get_cancelled_tournament_dates(self) -> set[date]:
        raw = (self.get_setting("tournament_skip_dates") or "").strip()
        if not raw:
            return set()

        result: set[date] = set()
        for token in raw.split(","):
            value = token.strip()
            if not value:
                continue
            try:
                result.add(date.fromisoformat(value))
            except ValueError:
                continue
        return result

    def set_cancelled_tournament_dates(self, dates: set[date]) -> None:
        value = ",".join(d.isoformat() for d in sorted(dates))
        self.set_setting("tournament_skip_dates", value)

    def add_cancelled_tournament_date(self, target_date: date) -> bool:
        dates = self.get_cancelled_tournament_dates()
        if target_date in dates:
            return False
        dates.add(target_date)
        self.set_cancelled_tournament_dates(dates)
        self.session.execute(delete(ScheduleSnapshot).where(ScheduleSnapshot.match_date == target_date))
        return True

    def remove_cancelled_tournament_date(self, target_date: date) -> bool:
        dates = self.get_cancelled_tournament_dates()
        if target_date not in dates:
            return False
        dates.remove(target_date)
        self.set_cancelled_tournament_dates(dates)
        self.session.execute(delete(ScheduleSnapshot).where(ScheduleSnapshot.match_date == target_date))
        return True
