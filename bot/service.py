from __future__ import annotations

import json
import shlex
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from bot.config import Settings
from bot.db import Database
from bot.parsing import MessageParser
from bot.repository import Repository
from bot.scheduler import Scheduler


class ClanBotService:
    _WEEKDAY_TOKENS = {
        "0": 0,
        "mon": 0,
        "monday": 0,
        "пн": 0,
        "пон": 0,
        "понедельник": 0,
        "1": 1,
        "tue": 1,
        "tues": 1,
        "tuesday": 1,
        "вт": 1,
        "вторник": 1,
        "2": 2,
        "wed": 2,
        "wednesday": 2,
        "ср": 2,
        "среда": 2,
        "3": 3,
        "thu": 3,
        "thur": 3,
        "thurs": 3,
        "thursday": 3,
        "чт": 3,
        "четверг": 3,
        "4": 4,
        "fri": 4,
        "friday": 4,
        "пт": 4,
        "пятница": 4,
        "5": 5,
        "sat": 5,
        "saturday": 5,
        "сб": 5,
        "суббота": 5,
        "6": 6,
        "sun": 6,
        "sunday": 6,
        "вс": 6,
        "воскресенье": 6,
    }

    _WEEKDAY_NAMES_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    _WEEKDAY_NAMES_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    _MONTH_NAMES_EN = [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ]
    _MONTH_NAMES_RU = [
        "января",
        "февраля",
        "марта",
        "апреля",
        "мая",
        "июня",
        "июля",
        "августа",
        "сентября",
        "октября",
        "ноября",
        "декабря",
    ]

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db = Database(settings.database_url)
        self.db.create_all()

        self.parser = MessageParser(settings.openai_api_key, settings.openai_model)
        self.scheduler = Scheduler()

        with self.db.session() as session:
            repo = Repository(session)
            repo.seed_roster_if_empty(settings.roster_file)

    def handle_message(self, source: str, text: str) -> str:
        return self.handle_message_event(source=source, text=text)

    @staticmethod
    def roster_template_json() -> str:
        return json.dumps(Repository.roster_template(), ensure_ascii=False, indent=2)

    def roster_export_json(self) -> str:
        with self.db.session() as session:
            repo = Repository(session)
            return json.dumps(repo.roster_payload(), ensure_ascii=False, indent=2)

    def handle_message_event(
        self,
        source: str,
        text: str,
        user_id: str | None = None,
        username: str | None = None,
        message_id: str | None = None,
        attachment_name: str | None = None,
        attachment_text: str | None = None,
    ) -> str:
        today = datetime.now(ZoneInfo(self.settings.timezone)).date()
        stripped = text.strip()
        lowered = stripped.lower()

        with self.db.session() as session:
            repo = Repository(session)
            lang = self._resolve_language(repo)

            if lowered in {"help", "/help", "!help", "помощь", "команды"}:
                return self._player_help(lang)

            actor_user_id = user_id or "unknown"
            actor_username = username or "unknown"

            if message_id and repo.is_message_processed(source, message_id):
                return self._ok(
                    self._t(lang, "Сообщение уже обработано", "Message already processed"),
                    [self._t(lang, "Повторно ничего не меняю.", "No changes were applied again.")],
                )

            bind_response = self._handle_player_bind_command(
                repo,
                source,
                actor_user_id,
                actor_username,
                stripped,
            )
            if bind_response is not None:
                if message_id:
                    repo.mark_message_processed(source, message_id)
                return bind_response

            admin_response = self._handle_admin_command(
                repo,
                stripped,
                source,
                actor_user_id,
                attachment_name=attachment_name,
                attachment_text=attachment_text,
            )
            if admin_response is not None:
                if message_id:
                    repo.mark_message_processed(source, message_id)
                return admin_response

            weekly_response = self._handle_weekly_query(repo, stripped, today, lang)
            if weekly_response is not None:
                repo.add_audit_log(source, actor_user_id, "weekly_query", {"text": stripped})
                if message_id:
                    repo.mark_message_processed(source, message_id)
                return weekly_response

            nicknames = repo.all_nicknames()
            bound_player = repo.find_player_by_identity(source, actor_user_id)
            parse_text = text
            if bound_player and bound_player.nickname.lower() not in lowered:
                parse_text = f"{bound_player.nickname} {text}"

            intent = self.parser.parse(parse_text, nicknames, today)

            if intent.intent == "absence" and intent.nickname and intent.start_date and intent.end_date:
                player = repo.find_player_by_nickname(intent.nickname)
                if not player:
                    return self._error(
                        self._t(lang, "Игрок не найден", "Player not found"),
                        [
                            f"{self._t(lang, 'Ник', 'Nickname')}: {intent.nickname}",
                            self._t(lang, "Проверь ник в составе или используй admin list.", "Check the roster nickname or use admin list."),
                        ],
                    )

                repo.add_absence(
                    player_id=player.id,
                    start_date=intent.start_date,
                    end_date=intent.end_date,
                    source=source,
                    raw_text=intent.raw,
                )
                removed = repo.delete_snapshots_between(intent.start_date, intent.end_date)
                repo.add_audit_log(
                    source,
                    actor_user_id,
                    "absence_add",
                    {
                        "player": player.nickname,
                        "start": intent.start_date.isoformat(),
                        "end": intent.end_date.isoformat(),
                        "by": actor_username,
                    },
                )
                if message_id:
                    repo.mark_message_processed(source, message_id)
                return self._ok(
                    self._t(lang, "Отсутствие сохранено", "Absence saved"),
                    [
                        f"{self._t(lang, 'Игрок', 'Player')}: {player.nickname}",
                        f"{self._t(lang, 'Период', 'Period')}: {intent.start_date.isoformat()} -> {intent.end_date.isoformat()}",
                        f"{self._t(lang, 'Сброшено снапшотов', 'Snapshots invalidated')}: {removed}",
                    ],
                )

            if intent.intent == "presence" and intent.nickname and intent.start_date and intent.end_date:
                player = repo.find_player_by_nickname(intent.nickname)
                if not player:
                    return self._error(
                        self._t(lang, "Игрок не найден", "Player not found"),
                        [
                            f"{self._t(lang, 'Ник', 'Nickname')}: {intent.nickname}",
                            self._t(lang, "Проверь ник в составе или используй admin list.", "Check the roster nickname or use admin list."),
                        ],
                    )

                deleted = repo.remove_absences_for_player_range(
                    player_id=player.id,
                    start_date=intent.start_date,
                    end_date=intent.end_date,
                )
                removed = repo.delete_snapshots_between(intent.start_date, intent.end_date)
                repo.add_audit_log(
                    source,
                    actor_user_id,
                    "absence_cancel",
                    {
                        "player": player.nickname,
                        "start": intent.start_date.isoformat(),
                        "end": intent.end_date.isoformat(),
                        "deleted": deleted,
                        "by": actor_username,
                    },
                )
                if message_id:
                    repo.mark_message_processed(source, message_id)
                return self._ok(
                    self._t(lang, "Отмена отсутствия сохранена", "Absence cancellation saved"),
                    [
                        f"{self._t(lang, 'Игрок', 'Player')}: {player.nickname}",
                        f"{self._t(lang, 'Период', 'Period')}: {intent.start_date.isoformat()} -> {intent.end_date.isoformat()}",
                        f"{self._t(lang, 'Удалено отписок', 'Removed absence records')}: {deleted}",
                        f"{self._t(lang, 'Сброшено снапшотов', 'Snapshots invalidated')}: {removed}",
                    ],
                )

            if intent.intent == "query":
                target_date = intent.start_date or self._next_tournament_day(repo, today)
                if not self._is_tournament_day(repo, target_date):
                    nearest = self._upcoming_tournament_days(target_date, count=3)
                    nearest_text = ", ".join(day.isoformat() for day in nearest)
                    if message_id:
                        repo.mark_message_processed(source, message_id)
                    return self._error(
                        self._t(lang, "На эту дату турнир не проводится", "No tournament on this date"),
                        [
                            f"{self._t(lang, 'Запрошено', 'Requested')}: {target_date.isoformat()}",
                            f"{self._t(lang, 'Ближайшие турнирные дни', 'Nearest tournament dates')}: {nearest_text}",
                            self._t(lang, "Используй одну из этих дат в команде lineup.", "Use one of these dates in lineup command."),
                        ],
                    )
                payload = self.scheduler.build_day_schedule(repo, target_date, advance_rotation=True)
                repo.add_audit_log(source, actor_user_id, "day_query", {"date": target_date.isoformat()})
                if message_id:
                    repo.mark_message_processed(source, message_id)
                return self._format_schedule(payload, lang)

            if message_id:
                repo.mark_message_processed(source, message_id)

        return self._error(
            self._t(lang, "Не удалось разобрать сообщение", "Could not parse message"),
            self._parse_examples(lang),
        )

    def _resolve_language(self, repo: Repository) -> str:
        saved = (repo.get_setting("language") or "").strip().lower()
        base = saved or self.settings.bot_language or "en"
        return "ru" if base == "ru" else "en"

    @staticmethod
    def _t(lang: str, ru_text: str, en_text: str) -> str:
        return ru_text if lang == "ru" else en_text

    def _handle_player_bind_command(
        self,
        repo: Repository,
        source: str,
        user_id: str,
        username: str,
        text: str,
    ) -> str | None:
        lowered = text.lower()
        if not (
            lowered.startswith("bind ")
            or lowered.startswith("/bind ")
            or lowered.startswith("привязать ")
        ):
            return None

        try:
            parts = shlex.split(text)
        except ValueError:
            return self._error("Invalid command format", ["Use: bind <nickname>"])

        if len(parts) < 2:
            return self._error("Invalid command format", ["Use: bind <nickname>"])

        nickname = parts[1]
        ok, msg = repo.bind_identity(source, user_id, username, nickname)
        if ok:
            repo.add_audit_log(source, user_id, "bind_identity", {"nickname": nickname})
            return self._ok("Binding completed", [msg, "You can now send attendance messages without nickname."])
        return self._error("Failed to bind account", [msg])

    def _handle_admin_command(
        self,
        repo: Repository,
        text: str,
        actor_source: str,
        actor_user_id: str,
        attachment_name: str | None = None,
        attachment_text: str | None = None,
    ) -> str | None:
        lang = self._resolve_language(repo)
        if not text:
            return None

        lowered = text.lower()
        if not (lowered.startswith("admin") or lowered.startswith("/admin") or lowered.startswith("!admin")):
            return None

        try:
            parts = shlex.split(text)
        except ValueError:
            return self._error(
                self._t(lang, "Неверный формат админ-команды", "Invalid admin command format"),
                [self._t(lang, "Используй: admin help", "Use: admin help")],
            )

        if not parts:
            return self._admin_help(lang)

        if parts[0].lower() in {"/admin", "!admin"}:
            parts[0] = "admin"

        if len(parts) == 1:
            return self._admin_help(lang)

        command = parts[1].lower()

        if command == "help":
            return self._admin_help(lang)

        if command == "tournament" and len(parts) >= 3:
            subcommand = parts[2].lower()

            if subcommand in {"show", "list", "status"}:
                weekdays = self._get_tournament_weekdays(repo)
                cancelled = sorted(repo.get_cancelled_tournament_dates())
                weekday_names = self._format_weekdays(weekdays, lang)
                lines = [
                    f"{self._t(lang, 'Дни недели', 'Weekdays')}: {weekday_names}",
                    f"{self._t(lang, 'Отменённые даты', 'Cancelled dates')}: {', '.join(d.isoformat() for d in cancelled) if cancelled else self._t(lang, 'нет', 'none')}",
                ]
                return self._ok(self._t(lang, "Настройки турнира", "Tournament settings"), lines)

            if subcommand in {"weekdays", "days", "set-days", "set-weekdays"}:
                if len(parts) < 4:
                    return self._error(
                        self._t(lang, "Не указаны дни турнира", "Tournament weekdays are missing"),
                        [self._t(lang, "Пример: admin tournament weekdays ср,чт,сб", "Example: admin tournament weekdays wed,thu,sat")],
                    )

                weekdays = self._parse_weekdays_input(" ".join(parts[3:]))
                if not weekdays:
                    return self._error(
                        self._t(lang, "Не удалось распознать дни", "Could not parse weekdays"),
                        [self._t(lang, "Используй: mon,tue или пн,вт или 0,1", "Use: mon,tue or пн,вт or 0,1")],
                    )

                repo.set_tournament_weekdays(weekdays)
                repo.clear_all_snapshots()
                repo.add_audit_log(actor_source, actor_user_id, "admin_tournament_weekdays", {"weekdays": sorted(weekdays)})
                return self._ok(
                    self._t(lang, "Турнирные дни обновлены", "Tournament weekdays updated"),
                    [f"{self._t(lang, 'Новые дни', 'New days')}: {self._format_weekdays(weekdays, lang)}"],
                )

            if subcommand in {"cancel", "skip", "off"} and len(parts) >= 4:
                target_date = self._parse_command_date(parts[3])
                if not target_date:
                    return self._error(
                        self._t(lang, "Неверная дата", "Invalid date"),
                        [self._t(lang, "Используй формат YYYY-MM-DD или DD-MM-YYYY", "Use format YYYY-MM-DD or DD-MM-YYYY")],
                    )

                added = repo.add_cancelled_tournament_date(target_date)
                repo.add_audit_log(actor_source, actor_user_id, "admin_tournament_cancel", {"date": target_date.isoformat(), "added": added})
                if not added:
                    return self._ok(
                        self._t(lang, "Дата уже отменена", "Date already cancelled"),
                        [target_date.isoformat()],
                    )
                return self._ok(
                    self._t(lang, "Турнир на дату отменен", "Tournament date cancelled"),
                    [target_date.isoformat()],
                )

            if subcommand in {"uncancel", "unskip", "on", "restore"} and len(parts) >= 4:
                target_date = self._parse_command_date(parts[3])
                if not target_date:
                    return self._error(
                        self._t(lang, "Неверная дата", "Invalid date"),
                        [self._t(lang, "Используй формат YYYY-MM-DD или DD-MM-YYYY", "Use format YYYY-MM-DD or DD-MM-YYYY")],
                    )

                removed = repo.remove_cancelled_tournament_date(target_date)
                repo.add_audit_log(actor_source, actor_user_id, "admin_tournament_uncancel", {"date": target_date.isoformat(), "removed": removed})
                if not removed:
                    return self._ok(
                        self._t(lang, "Дата не была в отменах", "Date was not cancelled"),
                        [target_date.isoformat()],
                    )
                return self._ok(
                    self._t(lang, "Отмена турнира на дату снята", "Tournament date cancellation removed"),
                    [target_date.isoformat()],
                )

            return self._error(
                self._t(lang, "Неизвестная команда турнира", "Unknown tournament command"),
                [
                    "admin tournament show",
                    "admin tournament weekdays wed,thu,sat",
                    "admin tournament cancel 2026-05-07",
                    "admin tournament uncancel 2026-05-07",
                ],
            )

        if command in {"set-language", "lang"} and len(parts) >= 3:
            value = parts[2].lower()
            if value not in {"en", "ru"}:
                return self._error(
                    self._t(lang, "Неверный язык", "Invalid language"),
                    ["Use: admin set-language en|ru"],
                )
            repo.set_setting("language", value)
            repo.add_audit_log(actor_source, actor_user_id, "admin_set_language", {"language": value})
            return self._ok(
                self._t(value, "Язык обновлен", "Language updated"),
                ["Current language: Russian" if value == "ru" else "Current language: English"],
            )

        if command == "roster" and len(parts) >= 3 and parts[2].lower() in {"reload", "import"}:
            try:
                squads, players = repo.replace_roster_from_file(self.settings.roster_file)
                repo.add_audit_log(actor_source, actor_user_id, "admin_roster_reload", {"squads": squads, "players": players})
                return self._ok(
                    self._t(lang, "Состав загружен из файла", "Roster imported from file"),
                    [
                        f"{self._t(lang, 'Отрядов', 'Squads')}: {squads}",
                        f"{self._t(lang, 'Игроков', 'Players')}: {players}",
                    ],
                )
            except FileNotFoundError:
                return self._error(self._t(lang, "Файл состава не найден", "Roster file not found"), [self.settings.roster_file])
            except Exception as exc:
                return self._error(self._t(lang, "Ошибка загрузки состава", "Roster import failed"), [str(exc)])

        if command == "roster" and len(parts) >= 3 and parts[2].lower() in {"template", "download"}:
            template_json = self.roster_template_json()
            title = self._t(lang, "Шаблон ростера", "Roster template")
            tip = self._t(
                lang,
                "Сохрани это в .json и загрузи командой: admin roster upload",
                "Save this as .json and upload with: admin roster upload",
            )
            return f"{title}\n{tip}\n```json\n{template_json}\n```"

        if command == "roster" and len(parts) >= 3 and parts[2].lower() in {"export", "dump"}:
            export_json = self.roster_export_json()
            title = self._t(lang, "Текущий ростер", "Current roster")
            tip = self._t(
                lang,
                "Это текущий ростер из базы. Его можно загрузить обратно через: admin roster upload",
                "This is the current roster from DB. You can upload it back via: admin roster upload",
            )
            return f"{title}\n{tip}\n```json\n{export_json}\n```"

        if command == "roster" and len(parts) >= 3 and parts[2].lower() in {"upload", "replace", "import-json"}:
            payload_text = attachment_text

            if not payload_text:
                return self._error(
                    self._t(lang, "Не передан JSON ростера", "Roster JSON is missing"),
                    [
                        self._t(
                            lang,
                            "Приложи .json файл к сообщению: admin roster upload",
                            "Attach a .json file with: admin roster upload",
                        )
                    ],
                )

            try:
                squads, players = repo.replace_roster_from_json_text(payload_text)
                repo.add_audit_log(
                    actor_source,
                    actor_user_id,
                    "admin_roster_upload",
                    {"squads": squads, "players": players, "attachment": attachment_name or "inline"},
                )
                return self._ok(
                    self._t(lang, "Ростер обновлен", "Roster updated"),
                    [
                        f"{self._t(lang, 'Отрядов', 'Squads')}: {squads}",
                        f"{self._t(lang, 'Игроков', 'Players')}: {players}",
                    ],
                )
            except Exception as exc:
                return self._error(self._t(lang, "Ошибка загрузки ростера", "Roster upload failed"), [str(exc)])

        if command == "list":
            squads = repo.load_squads_with_players()
            lines = [self._t(lang, "Состав по отрядам:", "Roster by squads:")]
            for squad in squads:
                players = ", ".join([p.nickname for p in sorted(squad.players, key=lambda x: x.order_index)])
                lines.append(f"- {squad.name} ({len(squad.players)}): {players}")
            return self._block(self._t(lang, "Текущий состав", "Current roster"), lines)

        if command == "add-player" and len(parts) >= 4:
            squad_name = parts[2]
            nickname = parts[3]
            ok, msg = repo.add_player(squad_name, nickname)
            if ok:
                repo.add_audit_log(actor_source, actor_user_id, "admin_add_player", {"squad": squad_name, "nickname": nickname})
                return self._ok(
                    self._t(lang, "Игрок добавлен", "Player added"),
                    [f"{self._t(lang, 'Отряд', 'Squad')}: {squad_name}", f"{self._t(lang, 'Ник', 'Nickname')}: {nickname}"],
                )
            return self._error(self._t(lang, "Не удалось добавить игрока", "Could not add player"), [msg])

        if command == "remove-player" and len(parts) >= 3:
            ok, msg = repo.remove_player(parts[2])
            if ok:
                repo.add_audit_log(actor_source, actor_user_id, "admin_remove_player", {"nickname": parts[2]})
                return self._ok(self._t(lang, "Игрок удален", "Player removed"), [f"{self._t(lang, 'Ник', 'Nickname')}: {parts[2]}"])
            return self._error(self._t(lang, "Не удалось удалить игрока", "Could not remove player"), [msg])

        if command == "move-player" and len(parts) >= 4:
            nickname = parts[2]
            squad_name = parts[3]
            ok, msg = repo.move_player(nickname, squad_name)
            if ok:
                repo.add_audit_log(actor_source, actor_user_id, "admin_move_player", {"nickname": nickname, "squad": squad_name})
                return self._ok(
                    self._t(lang, "Игрок перемещен", "Player moved"),
                    [
                        f"{self._t(lang, 'Ник', 'Nickname')}: {nickname}",
                        f"{self._t(lang, 'Новый отряд', 'New squad')}: {squad_name}",
                    ],
                )
            return self._error(self._t(lang, "Не удалось переместить игрока", "Could not move player"), [msg])

        if command == "set-rotation" and len(parts) >= 4:
            squad_name = parts[2]
            try:
                index = int(parts[3])
            except ValueError:
                return self._error(
                    self._t(lang, "Неверный индекс ротации", "Invalid rotation index"),
                    [self._t(lang, "Индекс должен быть целым числом.", "Index must be an integer.")],
                )
            ok, msg = repo.set_rotation_index(squad_name, index)
            if ok:
                repo.add_audit_log(actor_source, actor_user_id, "admin_set_rotation", {"squad": squad_name, "index": index})
                return self._ok(self._t(lang, "Ротация обновлена", "Rotation updated"), [f"{self._t(lang, 'Отряд', 'Squad')}: {squad_name}", msg])
            return self._error(self._t(lang, "Не удалось задать ротацию", "Could not update rotation"), [msg])

        if command in {"no-show", "noshow", "did-not-come", "postfactum-absence"} and len(parts) >= 4:
            nickname = parts[2]
            player = repo.find_player_by_nickname(nickname)
            if not player:
                return self._error(self._t(lang, "Игрок не найден", "Player not found"), [f"{self._t(lang, 'Ник', 'Nickname')}: {nickname}"])

            target_date = self._parse_command_date(parts[3])
            if not target_date:
                return self._error(
                    self._t(lang, "Неверная дата", "Invalid date"),
                    [self._t(lang, "Используй формат YYYY-MM-DD или DD-MM-YYYY", "Use format YYYY-MM-DD or DD-MM-YYYY")],
                )

            # Replace overlapping single-day absence to keep post-factum edits idempotent.
            removed_absences = repo.remove_absences_for_player_range(player.id, target_date, target_date)
            repo.add_absence(
                player_id=player.id,
                start_date=target_date,
                end_date=target_date,
                source=actor_source,
                raw_text=f"admin no-show {nickname} {target_date.isoformat()}",
            )
            removed_snapshots = repo.delete_snapshots_between(target_date, target_date)
            repo.add_audit_log(
                actor_source,
                actor_user_id,
                "admin_no_show",
                {
                    "nickname": nickname,
                    "date": target_date.isoformat(),
                    "replaced_absences": removed_absences,
                    "snapshots_invalidated": removed_snapshots,
                },
            )
            return self._ok(
                self._t(lang, "Неявка зафиксирована", "No-show recorded"),
                [
                    f"{self._t(lang, 'Игрок', 'Player')}: {player.nickname}",
                    f"{self._t(lang, 'Дата', 'Date')}: {target_date.isoformat()}",
                    f"{self._t(lang, 'Сброшено снапшотов', 'Snapshots invalidated')}: {removed_snapshots}",
                ],
            )

        if command == "force-in" and len(parts) >= 4:
            nickname = parts[2]
            player = repo.find_player_by_nickname(nickname)
            if not player:
                return self._error(self._t(lang, "Игрок не найден", "Player not found"), [f"{self._t(lang, 'Ник', 'Nickname')}: {nickname}"])
            try:
                target_date = date.fromisoformat(parts[3])
            except ValueError:
                return self._error(self._t(lang, "Неверная дата", "Invalid date"), ["Use format YYYY-MM-DD"])
            repo.set_player_override(player.id, target_date, "in")
            repo.add_audit_log(actor_source, actor_user_id, "admin_force_in", {"nickname": nickname, "date": target_date.isoformat()})
            return self._ok(self._t(lang, "Override установлен", "Override set"), [f"{nickname}: IN {target_date.isoformat()}"])

        if command == "force-out" and len(parts) >= 4:
            nickname = parts[2]
            player = repo.find_player_by_nickname(nickname)
            if not player:
                return self._error(self._t(lang, "Игрок не найден", "Player not found"), [f"{self._t(lang, 'Ник', 'Nickname')}: {nickname}"])
            try:
                target_date = date.fromisoformat(parts[3])
            except ValueError:
                return self._error(self._t(lang, "Неверная дата", "Invalid date"), ["Use format YYYY-MM-DD"])
            repo.set_player_override(player.id, target_date, "out")
            repo.add_audit_log(actor_source, actor_user_id, "admin_force_out", {"nickname": nickname, "date": target_date.isoformat()})
            return self._ok(self._t(lang, "Override установлен", "Override set"), [f"{nickname}: OUT {target_date.isoformat()}"])

        if command == "clear-override" and len(parts) >= 4:
            nickname = parts[2]
            player = repo.find_player_by_nickname(nickname)
            if not player:
                return self._error(self._t(lang, "Игрок не найден", "Player not found"), [f"{self._t(lang, 'Ник', 'Nickname')}: {nickname}"])
            try:
                target_date = date.fromisoformat(parts[3])
            except ValueError:
                return self._error(self._t(lang, "Неверная дата", "Invalid date"), ["Use format YYYY-MM-DD"])
            removed = repo.clear_player_override(player.id, target_date)
            repo.add_audit_log(actor_source, actor_user_id, "admin_clear_override", {"nickname": nickname, "date": target_date.isoformat(), "removed": removed})
            return self._ok(
                self._t(lang, "Override очищен", "Override cleared"),
                [f"{nickname}: {target_date.isoformat()}", f"{self._t(lang, 'Удалено записей', 'Removed records')}: {removed}"],
            )

        return self._admin_help(lang)

    def get_allowed_discord_channel(self) -> int | None:
        env_channel = self.settings.discord_channel_id
        if env_channel:
            return env_channel
        with self.db.session() as session:
            repo = Repository(session)
            value = repo.get_setting("discord_channel_id")
            return int(value) if value and value.isdigit() else None

    def handle_message_discord(
        self,
        channel_id: int,
        text: str,
        user_id: str,
        username: str,
        message_id: str,
        attachment_name: str | None = None,
        attachment_text: str | None = None,
    ) -> str | None:
        allowed = self.get_allowed_discord_channel()
        if allowed and channel_id != allowed:
            if text.strip().lower().startswith(("admin set-channel", "/admin set-channel", "!admin set-channel")):
                pass
            else:
                return None

        stripped = text.strip()
        if stripped.lower().startswith(("admin set-channel", "/admin set-channel", "!admin set-channel")):
            with self.db.session() as session:
                repo = Repository(session)
                lang = self._resolve_language(repo)
                repo.set_setting("discord_channel_id", str(channel_id))
            return self._ok(
                self._t(lang, "Канал бота установлен", "Bot channel updated"),
                [
                    f"{self._t(lang, 'Канал', 'Channel')}: <#{channel_id}>",
                    self._t(lang, "Теперь отвечаю только здесь.", "I will reply only here now."),
                ],
            )

        return self.handle_message_event(
            source="discord",
            text=text,
            user_id=user_id,
            username=username,
            message_id=message_id,
            attachment_name=attachment_name,
            attachment_text=attachment_text,
        )

    def _handle_weekly_query(self, repo: Repository, text: str, today: date, lang: str) -> str | None:
        lowered = text.lower()
        triggers = ["week", "weekly", "недел", "турнир неделя", "сетк", "расписание недели"]
        if not any(trigger in lowered for trigger in triggers):
            return None

        week_start = self._monday_of_week(today)
        week_end = week_start + timedelta(days=6)
        lines = [
            f"**{self._t(lang, 'Недельный отчёт', 'Weekly report')}**",
            f"{self._t(lang, 'Период', 'Period')}: {self._format_date_range(week_start, week_end, lang)}",
            "━━━━━━━━━━━━━━━━━━",
        ]
        generated = False

        weekdays = self._get_tournament_weekdays(repo)
        cancelled = repo.get_cancelled_tournament_dates()
        for weekday in sorted(weekdays):
            target_date = week_start + timedelta(days=weekday)
            if target_date in cancelled:
                lines.append(f"\n**{self._format_report_date(target_date, lang)} [OFF]**")
                lines.append(self._t(lang, "Турнир отменен на эту дату", "Tournament is cancelled for this date"))
                generated = True
                continue
            payload = self.scheduler.build_day_schedule(repo, target_date)
            total_missing = sum(item["missing_slots"] for item in payload["squads"])
            status = "WARN" if total_missing > 0 else "OK"
            lines.append(f"\n**{self._format_report_date(target_date, lang)} [{status}]**")
            for squad in payload["squads"]:
                missing = squad["missing_slots"]
                prefix = "!" if missing > 0 else "-"
                lines.append(f"{prefix} {squad['name']}: {len(squad['starters'])}/5 | {self._t(lang, 'Playing', 'Playing')}: {', '.join(squad['starters']) or self._t(lang, 'нет', 'none')}")
                if missing > 0:
                    lines.append(f"  {self._t(lang, 'Дефицит', 'Deficit')}: {missing}")
                lines.append(f"  {self._t(lang, 'Отсутствуют', 'Absent')}: {', '.join(squad.get('absent', [])) or self._t(lang, 'нет', 'none')}")
                lines.append(f"  {self._t(lang, 'Исключены вручную', 'Manually excluded')}: {', '.join(squad.get('forced_out', [])) or self._t(lang, 'нет', 'none')}")
                lines.append(f"  {self._t(lang, 'Очередь', 'Bench')}: {', '.join(squad['bench']) or self._t(lang, 'нет', 'none')}")
            generated = True

        if not generated:
            return self._error(
                self._t(lang, "Турнирные дни не настроены", "Tournament weekdays are not configured"),
                [self._t(lang, "Используй admin tournament weekdays ...", "Use admin tournament weekdays ...")],
            )
        return "\n".join(lines)

    @staticmethod
    def _monday_of_week(target: date) -> date:
        return target - timedelta(days=target.weekday())

    @staticmethod
    def _admin_help(lang: str) -> str:
        if lang == "ru":
            return (
                "**Справка администратора**\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "**Общее**\n"
                "• `admin set-language en|ru` — сменить язык ответов бота\n"
                "• `admin set-channel` — зафиксировать текущий Discord-канал\n"
                "\n**Расписание турниров**\n"
                "• `admin tournament show` — показать турнирные дни и отмененные даты\n"
                "• `admin tournament weekdays ср,чт,сб` — задать регулярные дни турнира\n"
                "• `admin tournament cancel 2026-05-07` — отменить турнир на дату\n"
                "• `admin tournament uncancel 2026-05-07` — снять отмену с даты\n"
                "\n**Импорт и экспорт ростера**\n"
                "• `admin roster reload` — загрузить ростер из файла\n"
                "• `admin roster template` — скачать JSON-шаблон ростера\n"
                "• `admin roster export` — выгрузить текущий ростер из базы\n"
                "• `admin roster upload` — загрузить новый ростер из `.json`\n"
                "\n**Управление составом**\n"
                "• `admin list` — показать текущий состав по отрядам\n"
                "• `admin add-player \"Squad A\" NewNick` — добавить игрока\n"
                "• `admin remove-player NewNick` — удалить игрока\n"
                "• `admin move-player NewNick \"Squad B\"` — переместить игрока\n"
                "• `admin set-rotation \"Squad A\" 3` — вручную задать индекс ротации\n"
                "\n**Корректировки посещаемости**\n"
                "• `admin no-show Nickname 2026-05-07` — отметить неявку постфактум\n"
                "• `admin force-in NewNick 2026-05-08` — принудительно включить игрока\n"
                "• `admin force-out NewNick 2026-05-08` — принудительно исключить игрока\n"
                "• `admin clear-override NewNick 2026-05-08` — убрать ручной override"
            )
        return (
            "**Administrator Help**\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "**General**\n"
            "• `admin set-language en|ru` — switch bot response language\n"
            "• `admin set-channel` — lock bot to current Discord channel\n"
            "\n**Tournament schedule**\n"
            "• `admin tournament show` — show tournament weekdays and cancelled dates\n"
            "• `admin tournament weekdays wed,thu,sat` — set recurring tournament weekdays\n"
            "• `admin tournament cancel 2026-05-07` — cancel tournament for a date\n"
            "• `admin tournament uncancel 2026-05-07` — remove cancellation from a date\n"
            "\n**Roster import/export**\n"
            "• `admin roster reload` — reload roster from file\n"
            "• `admin roster template` — download roster JSON template\n"
            "• `admin roster export` — export current roster from database\n"
            "• `admin roster upload` — upload new roster from `.json`\n"
            "\n**Roster management**\n"
            "• `admin list` — show current roster grouped by squads\n"
            "• `admin add-player \"Squad A\" NewNick` — add a player\n"
            "• `admin remove-player NewNick` — remove a player\n"
            "• `admin move-player NewNick \"Squad B\"` — move player to another squad\n"
            "• `admin set-rotation \"Squad A\" 3` — set squad rotation index manually\n"
            "\n**Attendance corrections**\n"
            "• `admin no-show Nickname 2026-05-07` — record a post-factum no-show\n"
            "• `admin force-in NewNick 2026-05-08` — force player into lineup\n"
            "• `admin force-out NewNick 2026-05-08` — force player out of lineup\n"
            "• `admin clear-override NewNick 2026-05-08` — clear manual override"
        )

    @staticmethod
    def _player_help(lang: str) -> str:
        if lang == "ru":
            return (
                "**Справка игрока**\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "**Привязка**\n"
                "• `help` — показать эту справку\n"
                "• `bind <nickname>` — привязать аккаунт к нику в ростере\n"
                "\n**Отсутствия**\n"
                "• `Nickname не смогу 2026-05-08` — отметить отсутствие на дату\n"
                "• `Nickname не смогу 08.05-10.05` — отметить отсутствие на диапазон\n"
                "• `Nickname отмена 2026-05-08` — отменить ранее отправленную отписку\n"
                "• `Nickname буду 08.05-10.05` — сообщить, что будешь на диапазон дат\n"
                "\n**Отчеты**\n"
                "• `lineup 2026-05-09` — показать сетку на турнирный день\n"
                "• `week` / `расписание недели` — показать недельный отчет"
            )
        return (
            "**Player Help**\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "**Binding**\n"
            "• `help` — show this help\n"
            "• `bind <nickname>` — link your account to roster nickname\n"
            "\n**Attendance**\n"
            "• `Nickname cannot attend 2026-05-08` — mark absence for a date\n"
            "• `Nickname cannot attend 08.05-10.05` — mark absence for a date range\n"
            "• `Nickname cancellation 2026-05-08` — cancel previously submitted absence\n"
            "• `Nickname will attend 08.05-10.05` — confirm presence for a date range\n"
            "\n**Reports**\n"
            "• `lineup 2026-05-09` — show lineup for a tournament day\n"
            "• `week` — show weekly report"
        )

    @staticmethod
    def _parse_examples(lang: str) -> list[str]:
        if lang == "ru":
            return [
                "Примеры:",
                "Nickname не смогу 2026-05-08",
                "Nickname не смогу 08.05-10.05",
                "Nickname отмена 2026-05-08",
                "Nickname буду 08.05-10.05",
                "lineup 2026-05-09",
                "week",
                "help",
                "admin help",
            ]
        return [
            "Examples:",
            "Nickname cannot attend 2026-05-08",
            "Nickname cannot attend 08.05-10.05",
            "Nickname cancellation 2026-05-08",
            "Nickname will attend 08.05-10.05",
            "lineup 2026-05-09",
            "week",
            "help",
            "admin help",
        ]

    def _next_tournament_day(self, repo: Repository, start: date) -> date:
        current = start
        for _ in range(14):
            if self._is_tournament_day(repo, current):
                return current
            current += timedelta(days=1)
        return start

    def _upcoming_tournament_days(self, start: date, count: int = 3) -> list[date]:
        days: list[date] = []
        with self.db.session() as session:
            repo = Repository(session)
            weekdays = self._get_tournament_weekdays(repo)
            cancelled = repo.get_cancelled_tournament_dates()
        current = start
        for _ in range(30):
            if current.weekday() in weekdays and current not in cancelled:
                days.append(current)
                if len(days) >= count:
                    break
            current += timedelta(days=1)
        return days

    def _get_tournament_weekdays(self, repo: Repository) -> set[int]:
        return repo.get_tournament_weekdays(self.settings.tournament_weekdays)

    def _is_tournament_day(self, repo: Repository, target_date: date) -> bool:
        weekdays = self._get_tournament_weekdays(repo)
        if target_date.weekday() not in weekdays:
            return False
        return target_date not in repo.get_cancelled_tournament_dates()

    def _parse_weekdays_input(self, value: str) -> set[int]:
        cleaned = value.replace(";", ",").replace("/", ",").replace("|", ",")
        tokens = [token.strip().lower() for token in cleaned.replace(" ", ",").split(",") if token.strip()]
        parsed = {self._WEEKDAY_TOKENS[token] for token in tokens if token in self._WEEKDAY_TOKENS}
        return {day for day in parsed if 0 <= day <= 6}

    @staticmethod
    def _parse_command_date(raw: str) -> date | None:
        value = raw.strip()
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        return None

    def _format_weekdays(self, weekdays: set[int], lang: str) -> str:
        labels = self._WEEKDAY_NAMES_RU if lang == "ru" else self._WEEKDAY_NAMES_EN
        values = [labels[day] for day in sorted(weekdays) if 0 <= day <= 6]
        return ", ".join(values) if values else self._t(lang, "не задано", "not set")

    @classmethod
    def _format_report_date(cls, target_date: date, lang: str) -> str:
        weekday = (cls._WEEKDAY_NAMES_RU if lang == "ru" else cls._WEEKDAY_NAMES_EN)[target_date.weekday()]
        months = cls._MONTH_NAMES_RU if lang == "ru" else cls._MONTH_NAMES_EN
        month = months[target_date.month - 1]
        if lang == "ru":
            return f"{weekday}, {target_date.day} {month} {target_date.year}"
        return f"{weekday}, {month} {target_date.day}, {target_date.year}"

    @classmethod
    def _format_date_range(cls, start_date: date, end_date: date, lang: str) -> str:
        if start_date == end_date:
            return cls._format_report_date(start_date, lang)
        return f"{cls._format_report_date(start_date, lang)} - {cls._format_report_date(end_date, lang)}"

    @staticmethod
    def _format_schedule(payload: dict, lang: str) -> str:
        target_date = datetime.strptime(payload["date"], "%Y-%m-%d").date()
        pretty_date = ClanBotService._format_report_date(target_date, lang)
        lines = [f"{('Сетка' if lang == 'ru' else 'Lineup')} {('на' if lang == 'ru' else 'for')} {pretty_date}", "------------------------------"]
        for squad in payload["squads"]:
            starters = ", ".join(squad["starters"]) if squad["starters"] else ("нет игроков" if lang == "ru" else "no players")
            bench = ", ".join(squad["bench"]) if squad["bench"] else ("нет" if lang == "ru" else "none")
            absent = ", ".join(squad.get("absent", [])) if squad.get("absent") else ("нет" if lang == "ru" else "none")
            forced_out = ", ".join(squad.get("forced_out", [])) if squad.get("forced_out") else ("нет" if lang == "ru" else "none")
            lines.append(f"\n[{squad['name']}]")
            lines.append(f"  {('Играют' if lang == 'ru' else 'Playing')}: {starters}")
            lines.append(f"  {('Отсутствуют' if lang == 'ru' else 'Absent')}: {absent}")
            lines.append(f"  {('Исключены вручную' if lang == 'ru' else 'Manually excluded')}: {forced_out}")
            lines.append(f"  {('Очередь замен' if lang == 'ru' else 'Bench queue')}: {bench}")
            if squad["missing_slots"] > 0:
                lines.append(f"  {('Не хватает игроков' if lang == 'ru' else 'Missing slots')}: {squad['missing_slots']}")
        return "\n".join(lines)

    @staticmethod
    def _block(title: str, lines: list[str]) -> str:
        if not lines:
            return title
        formatted = "\n".join(f"- {line}" for line in lines)
        return f"{title}\n{formatted}"

    @staticmethod
    def _ok(title: str, lines: list[str]) -> str:
        return ClanBotService._block(title, lines)

    @staticmethod
    def _error(title: str, lines: list[str]) -> str:
        return ClanBotService._block(title, lines)
