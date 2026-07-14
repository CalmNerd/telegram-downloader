# Telegram Channel Video Downloader

A resumable, rate-limited downloader for **photos, videos, and documents**
in Telegram channels you're already a member of, built on Telethon.

## Files

```
telegram-downloader/
├── main.py            # CLI entry point (login/scan/download/resume/stats)
├── downloader.py       # Core download logic, flood-wait handling, retries
├── db.py               # SQLite tracking of downloaded messages (resume support)
├── config.py           # All settings, including safety/rate-limit defaults
├── requirements.txt
├── .env.example        # Copy to .env and fill in your credentials
├── downloads/          # Files land here: downloads/ChannelName/{photos,videos,documents}/
├── sessions/            # Telethon session file (created after first login)
└── logs/
    ├── download.log     # Full run log
    └── downloads.db      # SQLite DB tracking per-message status
```

## Setup

1. Get API credentials from https://my.telegram.org → "API Development Tools".
2. `python -m venv venv && source venv/bin/activate` (or `venv\Scripts\activate` on Windows)
3. `pip install -r requirements.txt`
4. `cp .env.example .env` and fill in `API_ID`, `API_HASH`, `PHONE`.
5. `python main.py login` — enter the code Telegram sends you. This creates
   `sessions/telegram.session` so you won't need to log in again.

## Usage

```bash
python main.py scan @channelname       # count videos, no downloading
python main.py download @channelname   # download everything
python main.py resume @channelname     # retry failed files + continue
python main.py stats @channelname      # see progress / data downloaded
```

> **Windows PowerShell users:** quote the channel name — `@name` is
> splatting syntax in PowerShell and will be swallowed before Python sees
> it. Use `python main.py scan "@channelname"` instead. Command Prompt
> (`cmd.exe`) doesn't have this issue.

You can stop at any time with Ctrl+C — progress is saved after every file,
so re-running `download` or `resume` picks up exactly where you left off.

## Running on a new device

The repo intentionally does **not** include `.env` or `sessions/` (see
`.gitignore`), so moving to a new machine needs a few manual steps:

1. **Clone and install:**
   ```bash
   git clone <your-repo-url>
   cd tele-downloader
   python -m venv venv
   venv\Scripts\activate        # Windows
   # source venv/bin/activate   # Linux/macOS
   pip install -r requirements.txt
   ```
2. **Recreate `.env`:**
   ```bash
   copy .env.example .env       # Windows
   # cp .env.example .env       # Linux/macOS
   ```
   Fill in the same `API_ID`, `API_HASH`, `PHONE` as before — these
   belong to your Telegram API app, not to a specific device.
3. **Log in again on this device:**
   ```bash
   python main.py login
   ```
   Telegram sends a fresh login code to this device; entering it creates
   a new local `sessions/telegram.session`. This is the same as opening
   Telegram on any new phone or computer — normal and expected.
4. **(Optional) Carry over resume progress.** To avoid re-downloading
   everything from scratch on the new device, copy these from the old
   device into the same relative paths on the new one:
   - `logs/downloads.db` — the resume/tracking database
   - `downloads/` — the actual files, if you want them local too

   Skipping this just means the new device starts a fresh run and
   re-downloads everything, since it has no record of prior progress.

Avoid running large downloads from two devices' sessions on the same
account at the same time — keeping total request volume low is part of
what keeps the account safe.

## How this protects your account (given a 25-40GB download)

Downloading large volumes of media on a personal account carries some risk
of triggering Telegram's abuse detection if done carelessly. This tool is
deliberately conservative:

- **Sequential downloads only** (`MAX_CONCURRENT_DOWNLOADS = 1`). Parallel
  large-file downloads on one account are the most common trigger for
  flood-wait penalties or temporary restrictions.
- **A pause between files** (`MIN_DELAY_BETWEEN_DOWNLOADS`, default 2s),
  so requests are spaced out like a normal client rather than hammering
  the API back-to-back.
- **Full compliance with `FloodWaitError`** — if Telegram says "wait N
  seconds," the tool always sleeps the entire N seconds (+ a small buffer)
  rather than retrying early or ignoring it.
- **Streaming, not bulk-loading** — messages are iterated one at a time
  (`iter_messages`), so memory stays low even on channels with 100k+ posts.
- **Disk-space check** before each run, so a 25-40GB job doesn't fail
  midway from running out of space (`MIN_FREE_DISK_GB` in `config.py`).
- **Resumable via SQLite** — every message's status (done/failed/skipped)
  is recorded, so nothing is re-downloaded and nothing is silently lost
  on interruption.

### Things worth doing yourself for a 25-40GB run

- Run it on a stable connection; avoid stopping/restarting repeatedly,
  since each fresh scan still has to iterate message history from the start.
- If you hit repeated `FloodWaitError`s even with the defaults, increase
  `MIN_DELAY_BETWEEN_DOWNLOADS` in `.env` (e.g. to `4.0` or `5.0`) — slower
  but safer.
- Only run this against channels you're actually a member of and have
  the right to save content from — this respects Telegram's Terms of
  Service and the rights of the content's creators.

## Choosing which media types to download

By default all three types are downloaded. To exclude a type, set it to
`false` in `.env`:

```
DOWNLOAD_PHOTOS=true
DOWNLOAD_VIDEOS=true
DOWNLOAD_DOCUMENTS=true
```

"Documents" covers anything sent as a Telegram file that isn't a photo or
video -- PDFs, zips, audio files, etc.

## Adjusting safety settings

All of the above are configurable in `.env` (or directly in `config.py`):

```
MIN_DELAY_BETWEEN_DOWNLOADS=2.0
MAX_CONCURRENT_DOWNLOADS=1
MIN_FREE_DISK_GB=5.0
MAX_FILE_SIZE_GB=0
```