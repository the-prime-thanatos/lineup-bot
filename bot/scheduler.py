from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from bot.repository import Repository


@dataclass
class SquadDayResult:
    squad_name: str
    starters: list[str]
    bench: list[str]
    absent: list[str]
    forced_out: list[str]
    missing_slots: int


class Scheduler:
    def __init__(self) -> None:
        pass

    def build_day_schedule(self, repo: Repository, target_date: date, advance_rotation: bool = True) -> dict:
        existing = repo.get_snapshot(target_date)
        if existing:
            import json

            payload = json.loads(existing.payload_json)
            if all("absent" in squad and "forced_out" in squad for squad in payload.get("squads", [])):
                return payload

        squads = repo.load_squads_with_players()
        daily_results: list[SquadDayResult] = []

        for squad in squads:
            roster = sorted(squad.players, key=lambda p: p.order_index)
            if not roster:
                daily_results.append(
                    SquadDayResult(
                        squad_name=squad.name,
                        starters=[],
                        bench=[],
                        absent=[],
                        forced_out=[],
                        missing_slots=5,
                    )
                )
                continue

            available = []
            absent: list[str] = []
            forced_out: list[str] = []
            for player in roster:
                override = repo.get_player_override(player.id, target_date)
                if override == "out":
                    forced_out.append(player.nickname)
                    continue
                if override == "in":
                    available.append(player)
                    continue
                is_absent = repo.is_player_absent(player.id, target_date)
                if is_absent:
                    absent.append(player.nickname)
                    continue
                available.append(player)

            if len(available) <= 5:
                starters = [p.nickname for p in available]
                bench: list[str] = []
                missing_slots = max(0, 5 - len(available))
            else:
                ordered = self._rotate(roster, squad.rotation_index)
                counts = repo.count_recent_starts([p.id for p in roster], target_date)
                starters, bench = self._pick_starters_and_bench_fair(ordered, {p.id for p in available}, counts)
                missing_slots = 0

                if advance_rotation:
                    squad.rotation_index = (squad.rotation_index + 5) % len(roster)

            daily_results.append(
                SquadDayResult(
                    squad_name=squad.name,
                    starters=starters,
                    bench=bench,
                    absent=absent,
                    forced_out=forced_out,
                    missing_slots=missing_slots,
                )
            )

        payload = {
            "date": target_date.isoformat(),
            "squads": [
                {
                    "name": item.squad_name,
                    "starters": item.starters,
                    "bench": item.bench,
                    "absent": item.absent,
                    "forced_out": item.forced_out,
                    "missing_slots": item.missing_slots,
                }
                for item in daily_results
            ],
        }
        repo.save_snapshot(target_date, payload)
        return payload

    @staticmethod
    def _rotate(roster: list, index: int) -> list:
        if not roster:
            return roster
        pivot = index % len(roster)
        return roster[pivot:] + roster[:pivot]

    @staticmethod
    def _pick_starters_and_bench_fair(
        ordered_roster: list,
        available_ids: set[int],
        recent_start_counts: dict[int, int],
    ) -> tuple[list[str], list[str]]:
        available_players = [p for p in ordered_roster if p.id in available_ids]
        indexed = list(enumerate(available_players))

        # Fairness (EN): fewer recent starts -> higher priority for starters; rotation breaks ties.
        # Справедливость (RU): кто меньше играл в последнее время, тот выше в приоритете; равенство решает ротация.
        ranked = sorted(indexed, key=lambda item: (recent_start_counts.get(item[1].id, 0), item[0]))
        starter_ids = {player.id for _, player in ranked[:5]}

        starters = [p.nickname for p in available_players if p.id in starter_ids]
        bench = [p.nickname for p in available_players if p.id not in starter_ids]
        return starters, bench
