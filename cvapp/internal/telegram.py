from __future__ import annotations

import json
import os
import shutil
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from ..config import TELEGRAM_CONFIG_FILE, TELEGRAM_SETUP_TEST_MESSAGE
from ..errors import die
from ..strings import USAGE_CI
from ..utils import quote_env
from .env import load_env_style_file


LEGACY_TELEGRAM_CONFIG_FILE = Path.home() / ".config" / "cv" / "telegram.env"


def _migrate_legacy_config() -> None:
    if TELEGRAM_CONFIG_FILE.is_file():
        return
    if not LEGACY_TELEGRAM_CONFIG_FILE.is_file():
        return

    TELEGRAM_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(LEGACY_TELEGRAM_CONFIG_FILE), str(TELEGRAM_CONFIG_FILE))
    except Exception:
        try:
            shutil.copy2(LEGACY_TELEGRAM_CONFIG_FILE, TELEGRAM_CONFIG_FILE)
            LEGACY_TELEGRAM_CONFIG_FILE.unlink(missing_ok=True)
        except Exception:
            return


def save_config(bot_token: str, chat_id: str) -> Path:
    _migrate_legacy_config()
    TELEGRAM_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(
        [
            f"TELEGRAM_BOT_TOKEN={quote_env(bot_token.strip())}",
            f"TELEGRAM_CHAT_ID={quote_env(chat_id.strip())}",
            "",
        ]
    )
    TELEGRAM_CONFIG_FILE.write_text(content, encoding="utf-8")
    try:
        os.chmod(TELEGRAM_CONFIG_FILE, 0o600)
    except Exception:
        pass
    return TELEGRAM_CONFIG_FILE


def load_config() -> dict[str, str]:
    _migrate_legacy_config()
    values = load_env_style_file(TELEGRAM_CONFIG_FILE)
    token = (values.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (values.get("TELEGRAM_CHAT_ID") or "").strip()
    return {"bot_token": token, "chat_id": chat_id}


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + ("*" * (len(value) - 8)) + value[-4:]


def send_message(bot_token: str, chat_id: str, message: str) -> tuple[bool, str]:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = urllib.parse.urlencode({"chat_id": chat_id, "text": message}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response_text = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return False, str(exc)

    try:
        parsed = json.loads(response_text)
    except json.JSONDecodeError:
        parsed = {}

    if isinstance(parsed, dict) and parsed.get("ok") is True:
        result = parsed.get("result") if isinstance(parsed.get("result"), dict) else {}
        message_id = result.get("message_id") if isinstance(result, dict) else None
        if message_id is None:
            return True, "ok"
        return True, f"message_id={message_id}"

    if isinstance(parsed, dict) and parsed.get("description"):
        return False, str(parsed.get("description"))
    return False, response_text[:500]


def fetch_updates(bot_token: str, offset: int | None = None, timeout_seconds: int = 10) -> tuple[bool, dict[str, Any], str]:
    params: dict[str, str] = {"timeout": str(timeout_seconds)}
    if offset is not None:
        params["offset"] = str(offset)

    url = f"https://api.telegram.org/bot{bot_token}/getUpdates?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, method="GET")

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds + 5) as response:
            response_text = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return False, {}, str(exc)

    try:
        parsed = json.loads(response_text)
    except json.JSONDecodeError:
        return False, {}, "Invalid JSON response from Telegram"

    if not isinstance(parsed, dict):
        return False, {}, "Unexpected response from Telegram"
    if parsed.get("ok") is not True:
        return False, parsed, str(parsed.get("description") or "Telegram API error")
    return True, parsed, ""


def extract_start_chat_id(payload: dict[str, Any]) -> tuple[str | None, int | None]:
    updates = payload.get("result") if isinstance(payload.get("result"), list) else []
    best_offset: int | None = None

    for item in updates:
        if not isinstance(item, dict):
            continue

        update_id = item.get("update_id")
        if isinstance(update_id, int):
            candidate_offset = update_id + 1
            if best_offset is None or candidate_offset > best_offset:
                best_offset = candidate_offset

        message = item.get("message") if isinstance(item.get("message"), dict) else None
        if message is None:
            continue

        text = str(message.get("text") or "").strip().lower()
        if not text.startswith("/start"):
            continue

        chat = message.get("chat") if isinstance(message.get("chat"), dict) else None
        if chat is None:
            continue

        chat_id = chat.get("id")
        if chat_id is None:
            continue
        return str(chat_id), best_offset

    return None, best_offset


def discover_chat_id(bot_token: str) -> tuple[bool, str, str]:
    print("Send /start to your bot now.")
    print("Waiting up to ~60 seconds for update...")

    ok, initial_payload, error = fetch_updates(bot_token, offset=None, timeout_seconds=2)
    if not ok:
        return False, "", error

    _, offset = extract_start_chat_id(initial_payload)

    for _attempt in range(8):
        ok, payload, error = fetch_updates(bot_token, offset=offset, timeout_seconds=8)
        if not ok:
            return False, "", error

        chat_id, next_offset = extract_start_chat_id(payload)
        if next_offset is not None:
            offset = next_offset
        if chat_id:
            return True, chat_id, ""

    return False, "", "Could not find /start update in time. Send /start and retry."


def cmd_ci_telegram(args: list[str]) -> int:
    action = args[0].strip().lower() if args else "setup"

    if action in {"setup", "config", "configure"}:
        token = os.environ.get("CV_TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            token = input("Telegram bot token: ").strip()
        if not token:
            die("Telegram bot token required")

        chat_id = os.environ.get("CV_TELEGRAM_CHAT_ID", "").strip()
        if not chat_id:
            ok, discovered_chat_id, discover_error = discover_chat_id(token)
            if not ok:
                die(f"Telegram chat id auto-discovery failed: {discover_error}")
            chat_id = discovered_chat_id
        if not chat_id:
            die("Telegram chat id required")

        ok, detail = send_message(token, chat_id, TELEGRAM_SETUP_TEST_MESSAGE)
        if not ok:
            die(f"Telegram /start auto-reply failed: {detail}")

        config_path = save_config(token, chat_id)
        print("Telegram integration configured.")
        print(f"Detected chat id: {chat_id}")
        print(f"Auto-reply message: {TELEGRAM_SETUP_TEST_MESSAGE}")
        print(f"Reply result: {detail}")
        print(f"Config file: {config_path}")
        return 0

    if action == "status":
        config = load_config()
        token = config.get("bot_token", "")
        chat_id = config.get("chat_id", "")
        if not token or not chat_id:
            print("Telegram integration: not configured")
            print("Run: cv ci telegram")
            return 0

        print("Telegram integration: configured")
        print(f"Bot token: {mask_secret(token)}")
        print(f"Chat id: {chat_id}")
        print(f"Config file: {TELEGRAM_CONFIG_FILE}")
        return 0

    if action == "send":
        config = load_config()
        token = config.get("bot_token", "")
        chat_id = config.get("chat_id", "")
        if not token or not chat_id:
            die("Telegram integration not configured. Run: cv ci telegram")

        if len(args) > 1:
            message = " ".join(args[1:]).strip()
        else:
            message = sys.stdin.read().strip()

        if not message:
            die("Usage: cv ci telegram send <message> or pipe message via stdin")

        if len(message) > 4000:
            message = message[:4000]

        ok, detail = send_message(token, chat_id, message)
        if not ok:
            die(f"Telegram send failed: {detail}")

        print("Telegram message sent.")
        print(f"Result: {detail}")
        return 0

    die(USAGE_CI)
    return 1


def cmd_ci(args: list[str]) -> int:
    if not args:
        die(USAGE_CI)

    provider = args[0].strip().lower()
    if provider == "telegram":
        return cmd_ci_telegram(args[1:])

    die(USAGE_CI)
    return 1
