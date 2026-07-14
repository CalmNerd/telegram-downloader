import os
from dotenv import load_dotenv
from telethon import TelegramClient

load_dotenv()

api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
phone = os.getenv("PHONE")

client = TelegramClient(
    "sessions/telegram",
    api_id,
    api_hash
)

async def main():
    await client.start(phone=phone)
    print("✅ Logged in successfully!")

with client:
    client.loop.run_until_complete(main())