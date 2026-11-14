"""PARK+ Telegram notifications. Telegram failures never interrupt parking operations."""
import html
import logging
import requests
from datetime import datetime, timedelta, timezone
from backend.config import Config

logger = logging.getLogger(__name__)
INDIA_TIMEZONE = timezone(timedelta(hours=5, minutes=30))

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
                "parse_mode": "HTML",
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

def escape_telegram_html(value) -> str:
    return html.escape(str(value if value is not None else "N/A"), quote=False)

def format_telegram_time(value: str) -> str:
    if not value:
        return "N/A"
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return escape_telegram_html(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(INDIA_TIMEZONE).strftime("%d %b %Y, %I:%M %p IST")

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
        f"<b>{icon} PARK+ SECURITY ALERT</b>\n\n"
        f"<b>Type:</b> {escape_telegram_html(event_type.replace('_', ' ').title())}\n"
        f"<b>Severity:</b> {escape_telegram_html(severity.upper())}\n"
        f"<b>Time:</b> {format_telegram_time(datetime.now(timezone.utc).isoformat())}\n"
        f"<b>Details:</b> {escape_telegram_html(description)}"
    )
    if event_code:
        message += f"\n<b>Incident:</b> {escape_telegram_html(event_code)}"
    return send_telegram_message(message)
