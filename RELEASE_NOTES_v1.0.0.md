# v1.0.0 Release Notes

## Summary
Initial public release of Clan Attendance Bot.

## Highlights
- Discord + Telegram message intake
- AI parsing with deterministic fallback
- Daily lineup generation and weekly report
- Rotation with fairness balancing
- Absence cancellation support
- Account binding via bind command
- Manual per-day overrides: force-in, force-out, clear-override
- Message idempotency by source/message_id
- Audit logging for critical actions
- Runtime language switch: admin set-language en|ru
- GitHub-ready repository setup (.gitignore, LICENSE, CI, issue/PR templates)

## Security Notes
- Secrets are excluded via .gitignore
- Use .env.example only for placeholders
- Rotate all exposed keys before public push
