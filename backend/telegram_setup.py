"""Print Telegram chat IDs that have messaged the configured PARK+ bot.

1. Put TELEGRAM_BOT_TOKEN (or legacy telegram_bot_token) in project-root .env.
2. Open Telegram and send /start to your bot.
3. Run: python -m backend.telegram_setup
4. Copy your numeric chat ID into TELEGRAM_CHAT_ID in backend/.env.
"""
import requests
from backend.config import Config

def main():
    token = (Config.TELEGRAM_BOT_TOKEN or "").strip()
    if not token:
        raise SystemExit("Telegram token missing. Set TELEGRAM_BOT_TOKEN in project-root .env.")
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise SystemExit(f"Could not contact Telegram: {exc}")
    if not payload.get("ok"):
        raise SystemExit(f"Telegram API error: {payload}")
    found = {}
    for update in payload.get("result", []):
        msg = update.get("message") or update.get("channel_post") or {}
        chat = msg.get("chat") or {}
        if chat.get("id") is not None:
            found[str(chat["id"])] = {
                "type": chat.get("type", ""),
                "title": chat.get("title") or chat.get("first_name") or "",
                "username": chat.get("username", ""),
            }
    if not found:
        print("No chats found. Open your bot in Telegram, press Start, send /start, then run this command again.")
        return
    print("Found Telegram chat IDs:")
    for chat_id, info in found.items():
        print(f"CHAT_ID={chat_id} | type={info['type']} | name={info['title']} | username={info['username']}")

if __name__ == "__main__":
    main()
