"""PARK+ Telegram notifications. Telegram failures never interrupt parking operations."""
import logging
import requests
from datetime import datetime, timezone
from backend.config import Config

logger = logging.getLogger(__name__)

def send_telegram_message(message: str) -> bool:
    token = (Config.TELEGRAM_BOT_TOKEN or "").strip()
    chat_id = (Config.TELEGRAM_CHAT_ID or "").strip()
    if not token or not chat_id:
        logger.info("Telegram is not configured; notification skipped.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        response = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": message,
                "disable_web_page_preview": True,
            },
            timeout=(1, 3),
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            logger.warning("Telegram API rejected notification: %s", payload)
            return False
        return True
    except requests.RequestException as exc:
        logger.warning("Telegram notification failed (%s).", type(exc).__name__)
        return False

def format_telegram_time(value: str) -> str:
    if not value:
        return "N/A"
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return timestamp.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def format_duration(seconds: int) -> str:
    total_seconds = max(0, int(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, remaining_seconds = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if remaining_seconds or not parts:
        parts.append(f"{remaining_seconds}s")
    return " ".join(parts)

def notify_security_event(event_type: str, severity: str, description: str, event_code: str = "") -> bool:
    icon = "🚨" if severity.lower() in ("critical", "high") else "⚠️"
    message = (
        f"{icon} PARK+ SECURITY ALERT\n"
        f"Type: {event_type.replace('_', ' ').title()}\n"
        f"Severity: {severity.upper()}\n"
        f"Details: {description}"
    )
    if event_code:
        message += f"\nIncident: {event_code}"
    return send_telegram_message(message)
