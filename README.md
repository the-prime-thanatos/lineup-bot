# Clan Attendance Bot (Discord + Telegram)

## English

Smart clan bot for Discord and Telegram.
It tracks attendance messages, keeps roster data, builds daily lineups, and generates weekly tournament reports.

### Features

- Discord + Telegram message intake
- AI parser with deterministic fallback
- SQLite persistence for roster, absences, snapshots, overrides, identities, and audit logs
- Message idempotency (duplicate message id is not applied twice)
- Account binding via `bind <nickname>`
- Fairness-aware starter selection (lower recent playtime gets priority)
- Manual daily overrides (`force-in`, `force-out`, `clear-override`) - admin can force include/exclude a player for a specific date regardless of regular absence records.
- Weekly report with deficit highlighting
- Optional single-channel Discord lock
- Runtime language switch: `admin set-language en|ru`

### Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
copy .env.example .env
python main.py
```

### Key .env fields

- `DISCORD_TOKEN`
- `TELEGRAM_BOT_TOKEN`
- `OPENAI_API_KEY`
- `ROSTER_FILE`
- `TOURNAMENT_WEEKDAYS` (default `3,4,5`)
- `DISCORD_CHANNEL_ID` (optional)
- `BOT_LANGUAGE` (default `en`)

### Player commands

Binding

- `help` - show short player command help.
- `bind <nickname>` - link your Discord/Telegram account to a roster nickname.

Attendance

- `Nickname cannot attend 2026-05-08` - mark absence for a specific date.
- `Nickname cannot attend 08.05-10.05` - mark absence for a date range.
- `Nickname cancellation 2026-05-08` - remove previously submitted absence for date/range.

Reports

- `lineup 2026-05-09` - generate lineup for the requested tournament day.
- `week` - generate weekly tournament report for configured tournament weekdays.

### Admin commands

General

- `admin help` - show administrator command help.
- `admin set-language en|ru` - switch bot response language at runtime.
- `admin set-channel` - lock bot replies to current Discord channel.

Tournament schedule

- `admin tournament show` - show active tournament weekdays and cancelled dates.
- `admin tournament weekdays wed,thu,sat` - set recurring tournament weekdays (also supports numbers `0..6`).
- `admin tournament cancel 2026-05-07` - cancel tournament for a concrete date.

- `admin tournament uncancel 2026-05-07` - remove cancellation for a concrete date.

Roster import/export

- `admin roster reload` - reload roster from `ROSTER_FILE` on disk.
- `admin roster template` - download JSON template file for roster import.
- `admin roster export` - download current roster JSON from database.
- `admin roster upload` + attach `.json` - replace roster using uploaded file.

Roster management

- `admin list` - show roster grouped by squads.
- `admin add-player "Squad A" NewNick` - add player to squad.
- `admin remove-player NewNick` - remove player from roster.
- `admin move-player NewNick "Squad B"` - move player to another squad.
- `admin set-rotation "Squad A" 3` - set squad rotation index manually.

Attendance corrections

- `admin no-show Nickname 2026-05-07` - post-factum mark player as absent for that day.
- `admin force-in NewNick 2026-05-08` - force player into lineup for date.
- `admin force-out NewNick 2026-05-08` - force player out of lineup for date.
- `admin clear-override NewNick 2026-05-08` - clear manual override for date.

## Русский

Бот для клана в Discord и Telegram.
Собирает отписки, ведет составы и формирует сетку на день/неделю.

### Возможности

- Прием сообщений из Discord и Telegram
- AI-разбор сообщений + fallback-парсер
- SQLite-хранение состава, отписок, снапшотов, override, привязок и аудита
- Идемпотентность сообщений (дубликат message id не применяется повторно)
- Привязка аккаунта через `bind <nickname>`
- Fairness-логика старта (кто меньше играл недавно, тот выше в приоритете)
- Ручные override на день (`force-in`, `force-out`, `clear-override`) - админ может принудительно включить/исключить игрока на конкретную дату независимо от обычных отписок.
- Недельный отчет с подсветкой дефицита
- Ограничение бота одним Discord-каналом (опционально)
- Смена языка на лету: `admin set-language en|ru`

### Установка

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
copy .env.example .env
python main.py
```

### Основные поля .env

- `DISCORD_TOKEN`
- `TELEGRAM_BOT_TOKEN`
- `OPENAI_API_KEY`
- `ROSTER_FILE`
- `TOURNAMENT_WEEKDAYS` (по умолчанию `3,4,5`)
- `DISCORD_CHANNEL_ID` (опционально)
- `BOT_LANGUAGE` (по умолчанию `en`)

### Команды игроков

Привязка

- `help` - показать краткую справку игрока.
- `bind <nickname>` - привязать аккаунт Discord/Telegram к нику в ростере.

Отсутствия

- `Nickname не смогу 2026-05-08` - отметить отсутствие на конкретную дату.
- `Nickname не смогу 08.05-10.05` - отметить отсутствие на диапазон дат.
- `Nickname отмена 2026-05-08` - отменить ранее отправленную отписку.

Отчеты

- `lineup 2026-05-09` - построить сетку на указанный турнирный день.
- `week` / `расписание недели` - получить недельный отчет по турнирным дням.

### Админ-команды

Общее

- `admin help` - показать справку администратора.
- `admin set-language en|ru` - сменить язык ответов бота на лету.
- `admin set-channel` - зафиксировать ответы бота только в текущем Discord-канале.

Расписание турниров

- `admin tournament show` - показать активные турнирные дни и отмененные даты.
- `admin tournament weekdays ср,чт,сб` - задать регулярные дни турнира (также поддерживаются числа `0..6`).
- `admin tournament cancel 2026-05-07` - отменить турнир на конкретную дату.
- `admin tournament uncancel 2026-05-07` - снять отмену турнира с конкретной даты.

Импорт и экспорт ростера

- `admin roster reload` - перезагрузить ростер из `ROSTER_FILE`.
- `admin roster template` - скачать JSON-шаблон для импорта ростера.
- `admin roster export` - скачать текущий ростер из базы в JSON.
- `admin roster upload` + приложить `.json` - полностью заменить ростер по загруженному файлу.

Управление составом

- `admin list` - показать текущий состав по отрядам.
- `admin add-player "Squad A" NewNick` - добавить игрока в отряд.
- `admin remove-player NewNick` - удалить игрока из ростера.
- `admin move-player NewNick "Squad B"` - переместить игрока в другой отряд.
- `admin set-rotation "Squad A" 3` - вручную задать индекс ротации отряда.

Корректировки посещаемости

- `admin no-show Nickname 2026-05-07` - постфактум отметить, что игрок не пришел в этот день.
- `admin force-in NewNick 2026-05-08` - принудительно включить игрока в состав на дату.
- `admin force-out NewNick 2026-05-08` - принудительно исключить игрока из состава на дату.
- `admin clear-override NewNick 2026-05-08` - убрать ручной override на дату.

