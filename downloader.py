"""
Core downloader logic: connecting, scanning a channel for videos,
and downloading them safely (sequential, rate-limited, resumable,
flood-wait aware).
"""

import asyncio
import logging
import os
import re
import shutil
import time

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.types import DocumentAttributeVideo

import config
import db

logger = logging.getLogger("tgdown")


def setup_logging():
    os.makedirs(config.LOG_DIR, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def sanitize_filename(name: str) -> str:
    """Strip characters that are unsafe for filenames across OSes."""
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    return name.strip() or "unnamed"


def classify_message(message):
    """
    Returns 'photo', 'video', 'document', or None (no relevant media).

    Voice notes, video notes (round messages), and stickers/GIFs are
    treated as 'document' by mime-type fallback unless they clearly
    match photo/video attributes -- they're still downloadable, just
    grouped generically.
    """
    if message.photo:
        return "photo"

    if message.video:
        return "video"

    if message.document:
        mime = message.document.mime_type or ""
        if mime.startswith("video/"):
            return "video"
        if mime.startswith("image/"):
            return "photo"
        for attr in message.document.attributes:
            if isinstance(attr, DocumentAttributeVideo):
                return "video"
        return "document"

    return None


def is_wanted_media(message) -> bool:
    media_type = classify_message(message)
    if media_type == "photo":
        return config.DOWNLOAD_PHOTOS
    if media_type == "video":
        return config.DOWNLOAD_VIDEOS
    if media_type == "document":
        return config.DOWNLOAD_DOCUMENTS
    return False


def get_message_size(message) -> int:
    try:
        if message.file:
            return message.file.size or 0
    except Exception:
        pass
    return 0


def check_free_disk_space(path: str, required_gb: float):
    os.makedirs(path, exist_ok=True)
    total, used, free = shutil.disk_usage(path)
    free_gb = free / (1024 ** 3)
    if free_gb < required_gb:
        raise RuntimeError(
            f"Not enough free disk space. {free_gb:.2f} GB free, "
            f"but {required_gb:.2f} GB minimum is required. "
            f"Free up space or lower MIN_FREE_DISK_GB in config.py / .env."
        )
    return free_gb


class TelegramVideoDownloader:
    def __init__(self):
        os.makedirs(os.path.dirname(config.SESSION_NAME), exist_ok=True)
        os.makedirs(config.DOWNLOAD_DIR, exist_ok=True)
        os.makedirs(config.LOG_DIR, exist_ok=True)
        self.client = TelegramClient(config.SESSION_NAME, config.API_ID, config.API_HASH)
        self.db_conn = db.get_connection()
        self._semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_DOWNLOADS)

    async def connect(self):
        if not config.API_ID or not config.API_HASH:
            raise RuntimeError(
                "API_ID / API_HASH are not set. Copy .env.example to .env and fill them in "
                "using credentials from https://my.telegram.org."
            )
        await self.client.start(phone=config.PHONE)
        me = await self.client.get_me()
        logger.info(f"Logged in as {me.first_name} (id={me.id})")

    async def resolve_channel(self, channel_input: str):
        channel_input = channel_input.strip()
        if channel_input.startswith("https://t.me/"):
            channel_input = channel_input.split("https://t.me/")[-1]
        channel_input = channel_input.lstrip("@")
        entity = await self.client.get_entity(channel_input)
        return entity

    def _channel_key(self, entity) -> str:
        """Stable key used in the DB / folder name for this channel."""
        return str(getattr(entity, "username", None) or getattr(entity, "id"))

    async def scan(self, entity):
        """Count how many wanted media messages exist, without downloading."""
        counts = {"photo": 0, "video": 0, "document": 0}
        total_seen = 0
        async for message in self.client.iter_messages(entity, reverse=True):
            total_seen += 1
            media_type = classify_message(message)
            if media_type and is_wanted_media(message):
                counts[media_type] += 1
            if total_seen % 2000 == 0:
                logger.info(f"Scanned {total_seen} messages so far, {sum(counts.values())} matching media found...")
        logger.info(f"Scan complete: {total_seen} messages scanned. Breakdown: {counts}")
        return counts, total_seen

    async def _download_one(self, message, base_folder, channel_key):
        size_bytes = get_message_size(message)
        media_type = classify_message(message)

        # Group into subfolders: downloads/ChannelName/{photos,videos,documents}/
        folder = os.path.join(base_folder, f"{media_type}s" if media_type else "other")
        os.makedirs(folder, exist_ok=True)

        if config.MAX_FILE_SIZE_GB > 0 and size_bytes > 0:
            size_gb = size_bytes / (1024 ** 3)
            if size_gb > config.MAX_FILE_SIZE_GB:
                logger.info(f"Skipping message {message.id}: {size_gb:.2f} GB exceeds MAX_FILE_SIZE_GB")
                db.mark_status(self.db_conn, channel_key, message.id, "skipped", size_bytes=size_bytes, media_type=media_type)
                return "skipped"

        attempt = 0
        while attempt < config.MAX_RETRIES_PER_FILE:
            attempt += 1
            try:
                def progress(current, total):
                    if total:
                        percent = current * 100 / total
                        print(f"\r  [{message.id}] {percent:5.1f}% ({current/1024/1024:.1f}MB/{total/1024/1024:.1f}MB)", end="")

                path = await message.download_media(file=folder + os.sep, progress_callback=progress)
                print()  # newline after progress bar
                if path:
                    logger.info(f"Downloaded message {message.id} ({media_type}) -> {os.path.basename(path)}")
                    db.mark_status(self.db_conn, channel_key, message.id, "done", filename=os.path.basename(path), size_bytes=size_bytes, media_type=media_type)
                    return "done"
                else:
                    logger.warning(f"Message {message.id} had no downloadable media at download time.")
                    db.mark_status(self.db_conn, channel_key, message.id, "skipped", size_bytes=size_bytes, media_type=media_type)
                    return "skipped"

            except FloodWaitError as e:
                wait_time = e.seconds + config.FLOOD_WAIT_BUFFER_SECONDS
                logger.warning(f"FloodWaitError: Telegram asked us to wait {e.seconds}s. Sleeping {wait_time}s...")
                await asyncio.sleep(wait_time)
                # Don't count flood waits as a failed attempt against the retry limit
                attempt -= 1
                continue

            except Exception as e:
                logger.error(f"Error downloading message {message.id} (attempt {attempt}): {e}")
                if attempt < config.MAX_RETRIES_PER_FILE:
                    backoff = config.RETRY_BACKOFF_SECONDS * attempt
                    logger.info(f"Retrying message {message.id} in {backoff}s...")
                    await asyncio.sleep(backoff)
                else:
                    db.mark_status(self.db_conn, channel_key, message.id, "failed", size_bytes=size_bytes, media_type=media_type)
                    return "failed"

        return "failed"

    async def download_all(self, entity, only_message_ids=None):
        channel_key = self._channel_key(entity)
        channel_name = getattr(entity, "title", None) or getattr(entity, "username", None) or channel_key
        folder = os.path.join(config.DOWNLOAD_DIR, sanitize_filename(channel_name))
        os.makedirs(folder, exist_ok=True)

        check_free_disk_space(config.DOWNLOAD_DIR, config.MIN_FREE_DISK_GB)

        stats = {"found": 0, "downloaded": 0, "skipped": 0, "failed": 0}
        only_set = set(only_message_ids) if only_message_ids else None

        logger.info(f"Starting download for '{channel_name}' -> {folder}")
        logger.info(
            f"Safety settings: {config.MAX_CONCURRENT_DOWNLOADS} concurrent, "
            f"{config.MIN_DELAY_BETWEEN_DOWNLOADS}s delay between files."
        )

        async for message in self.client.iter_messages(entity, reverse=True):
            if not is_wanted_media(message):
                continue
            if only_set is not None and message.id not in only_set:
                continue

            stats["found"] += 1

            if db.is_processed(self.db_conn, channel_key, message.id):
                stats["skipped"] += 1
                continue

            async with self._semaphore:
                result = await self._download_one(message, folder, channel_key)

            if result == "done":
                stats["downloaded"] += 1
            elif result == "skipped":
                stats["skipped"] += 1
            else:
                stats["failed"] += 1

            logger.info(
                f"Progress -> found: {stats['found']} | downloaded: {stats['downloaded']} | "
                f"skipped: {stats['skipped']} | failed: {stats['failed']}"
            )

            # Pace ourselves between files regardless of success/failure.
            await asyncio.sleep(config.MIN_DELAY_BETWEEN_DOWNLOADS)

        logger.info(f"Finished. Final stats: {stats}")
        return stats

    async def resume(self, entity):
        channel_key = self._channel_key(entity)
        failed_ids = db.list_failed(self.db_conn, channel_key)
        if not failed_ids:
            logger.info("No failed downloads recorded — running a normal pass to catch anything new.")
            return await self.download_all(entity)
        logger.info(f"Retrying {len(failed_ids)} previously failed messages...")
        return await self.download_all(entity, only_message_ids=failed_ids)

    def print_stats(self, entity):
        channel_key = self._channel_key(entity)
        stats = db.get_stats(self.db_conn, channel_key)
        gb_downloaded = stats["total_bytes"] / (1024 ** 3)
        print("=" * 50)
        print(f"Channel: {channel_key}")
        print(f"Downloaded : {stats['done']}")
        print(f"Skipped    : {stats['skipped']}")
        print(f"Failed     : {stats['failed']}")
        print(f"Data saved : {gb_downloaded:.2f} GB")
        if stats["by_type"]:
            print("By type:")
            for media_type, count in stats["by_type"].items():
                print(f"  {media_type:<10}: {count}")
        print("=" * 50)

    async def close(self):
        await self.client.disconnect()
        self.db_conn.close()