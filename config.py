"""
Central configuration for the Telegram video downloader.

All safety-related defaults live here. The comments explain WHY each
value is set the way it is -- these choices exist specifically to
reduce the risk of Telegram flagging or restricting your account.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# --- Credentials (from https://my.telegram.org) ---
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
PHONE = os.getenv("PHONE", "")

# --- Paths ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION_NAME = os.path.join(BASE_DIR, "sessions", "telegram")
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "download.log")
DB_PATH = os.path.join(LOG_DIR, "downloads.db")

# --- Safety / rate-limiting settings ---
# Telegram's own clients download sequentially and pace requests.
# Mimicking that behavior (instead of hammering the API) is the single
# biggest factor in avoiding FloodWaitErrors or account limitations.

# Pause (seconds) inserted between finishing one file and starting the next.
MIN_DELAY_BETWEEN_DOWNLOADS = float(os.getenv("MIN_DELAY_BETWEEN_DOWNLOADS", "2.0"))

# Keep this at 1. Telethon uses a single MTProto connection per client, and
# parallel large-file downloads on one account are what typically trigger
# aggressive flood-wait penalties. Sequential is slower but much safer.
MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "1"))

# If Telegram issues a FloodWaitError, we always sleep the FULL amount it
# asks for (plus a small buffer) rather than retrying early.
FLOOD_WAIT_BUFFER_SECONDS = 5

# How many times to retry a single file on transient network errors
# before giving up and marking it "failed" (it can be retried later
# with the `resume` command).
MAX_RETRIES_PER_FILE = 5

# Extra pause (seconds) added between retries of the same file, multiplied
# by the retry attempt number (simple linear backoff).
RETRY_BACKOFF_SECONDS = 10

# Minimum free disk space (in GB) required to start a download run.
# Since you mentioned 25-40GB total, this defaults to a safety margin.
MIN_FREE_DISK_GB = float(os.getenv("MIN_FREE_DISK_GB", "5.0"))

# Optional: skip files larger than this many GB (0 = no limit).
MAX_FILE_SIZE_GB = float(os.getenv("MAX_FILE_SIZE_GB", "0"))

# --- Which media types to download ---
# All three are on by default. Set to "false" in .env to exclude a type.
# "documents" covers PDFs, zips, audio files, etc. -- anything sent as a
# Telegram document that isn't classified as a photo or video.
DOWNLOAD_PHOTOS = os.getenv("DOWNLOAD_PHOTOS", "true").lower() == "true"
DOWNLOAD_VIDEOS = os.getenv("DOWNLOAD_VIDEOS", "true").lower() == "true"
DOWNLOAD_DOCUMENTS = os.getenv("DOWNLOAD_DOCUMENTS", "true").lower() == "true"