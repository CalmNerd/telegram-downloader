"""
CLI entry point.

Usage:
    python main.py login
    python main.py scan     <channel>
    python main.py download <channel>
    python main.py resume   <channel>
    python main.py stats    <channel>

<channel> can be:
    https://t.me/somechannel
    @somechannel
    somechannel
"""

import argparse
import asyncio
import sys

from downloader import TelegramVideoDownloader, setup_logging


async def run(args):
    setup_logging()
    dl = TelegramVideoDownloader()
    try:
        await dl.connect()

        if args.command == "login":
            print("Login successful. Session saved in sessions/telegram.session")
            return

        entity = await dl.resolve_channel(args.channel)

        if args.command == "scan":
            counts, total = await dl.scan(entity)
            print(f"\nOut of {total} messages scanned:")
            print(f"  Photos    : {counts['photo']}")
            print(f"  Videos    : {counts['video']}")
            print(f"  Documents : {counts['document']}")
            print(f"  Total     : {sum(counts.values())}")

        elif args.command == "download":
            stats = await dl.download_all(entity)
            print(f"\nDone. {stats}")

        elif args.command == "resume":
            stats = await dl.resume(entity)
            print(f"\nDone. {stats}")

        elif args.command == "stats":
            dl.print_stats(entity)

    finally:
        await dl.close()


def main():
    parser = argparse.ArgumentParser(description="Telegram channel video downloader (Telethon-based)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("login", help="Log in once and create a session file")

    p_scan = sub.add_parser("scan", help="Count videos in a channel without downloading")
    p_scan.add_argument("channel", help="Channel URL, @username, or username")

    p_dl = sub.add_parser("download", help="Download all videos from a channel")
    p_dl.add_argument("channel", help="Channel URL, @username, or username")

    p_resume = sub.add_parser("resume", help="Retry failed downloads, then continue any remaining")
    p_resume.add_argument("channel", help="Channel URL, @username, or username")

    p_stats = sub.add_parser("stats", help="Show download stats for a channel")
    p_stats.add_argument("channel", help="Channel URL, @username, or username")

    args = parser.parse_args()

    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nInterrupted. Progress has been saved — just re-run the same command to resume.")
        sys.exit(0)
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()