# Integrations

## Telegram

Command group:

```bash
cv ci telegram [setup|status|send] [message]
```

### Setup

Interactive setup (prompts for bot token, auto-discovers chat id):

```bash
cv ci telegram
```

Flow:

1. Enter bot token.
2. Send `/start` to your bot.
3. CLI automatically waits for update, finds chat id, sends predefined reply message, and saves config.

Predefined setup test message:

```text
cv telegram integration connected
```

Non-interactive setup (useful in automation):

```bash
CV_TELEGRAM_BOT_TOKEN="<token>" CV_TELEGRAM_CHAT_ID="<chat_id>" cv ci telegram setup
```

Stored config path:

```text
~/.config/cv/telegram.env
```

### Status

```bash
cv ci telegram status
```

### Send Message

```bash
cv ci telegram send "Build finished"
```

Or via stdin for scripts:

```bash
echo "Deploy started for frontend" | cv ci telegram send
```

### Script API Pattern

Use the CLI as internal script API:

```bash
#!/usr/bin/env bash
set -euo pipefail

msg="CI $(date -Iseconds): ${1:-Job finished}"
cv ci telegram send "$msg"
```

### Notes

- Telegram Bot API limits message size; this integration truncates long messages to 4000 chars.
- Config file permissions are restricted to user-only when possible.
- Keep bot token secret.
