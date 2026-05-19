#!/usr/bin/env python3
"""Back up messages from a single Google Chat space to a JSON file."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path

from gchat import chat_service, simplify_message

APP_HOME = Path(os.getenv("GOOGLE_CHAT_CLI_HOME", Path.home() / ".google-chat-cli"))
BACKUP_DIR = APP_HOME / "backup"


def load_backup(path: Path) -> tuple[list[dict], set[str]]:
    if not path.exists():
        return [], set()
    data = json.loads(path.read_text())
    seen = {m["name"] for m in data if m.get("name")}
    return data, seen


def save_backup(path: Path, messages: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(messages, indent=2, ensure_ascii=False))
    tmp.replace(path)


def fetch_all_messages(svc, space: str) -> list[dict]:
    messages = []
    req = svc.spaces().messages().list(parent=space, pageSize=100)
    while req is not None:
        resp = req.execute()
        messages.extend(resp.get("messages", []))
        req = svc.spaces().messages().list_next(req, resp)
    return messages


def fetch_recent(svc, space: str) -> list[dict]:
    resp = svc.spaces().messages().list(parent=space, pageSize=50).execute()
    return resp.get("messages", [])


def backfill(svc, space: str, messages: list[dict], seen: set[str]) -> int:
    print("backfilling full history...")
    all_msgs = fetch_all_messages(svc, space)
    count = 0
    for msg in all_msgs:
        name = msg.get("name")
        if name and name not in seen:
            messages.append(simplify_message(msg))
            seen.add(name)
            count += 1
    return count


def poll_once(svc, space: str, messages: list[dict], seen: set[str]) -> int:
    recent = fetch_recent(svc, space)
    count = 0
    for msg in recent:
        name = msg.get("name")
        if name and name not in seen:
            simplified = simplify_message(msg)
            messages.append(simplified)
            seen.add(name)
            count += 1
            sender = simplified.get("sender", "?")
            text = (simplified.get("text") or "")[:80]
            print(f"  new: {sender}: {text}")
    return count


def main():
    parser = argparse.ArgumentParser(description="Back up a Google Chat space to JSON")
    parser.add_argument("space", help="Space ID (e.g. spaces/AAAA123)")
    parser.add_argument("--interval", type=float, default=5.0, help="Poll interval in seconds (default: 5)")
    parser.add_argument("--output", help="Output JSON file path (default: ~/.google-chat-cli/backup/<space-id>.json)")
    args = parser.parse_args()

    space_slug = args.space.replace("/", "_")
    output = Path(args.output) if args.output else BACKUP_DIR / f"{space_slug}.json"

    messages, seen = load_backup(output)
    print(f"loaded {len(messages)} existing messages from {output}")

    svc = chat_service()

    added = backfill(svc, args.space, messages, seen)
    if added:
        save_backup(output, messages)
        print(f"backfill complete: {added} new messages")
    else:
        print("backfill complete: already up to date")

    print(f"polling {args.space} every {args.interval}s — Ctrl+C to stop")

    running = True

    def handle_signal(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    while running:
        time.sleep(args.interval)
        try:
            added = poll_once(svc, args.space, messages, seen)
            if added:
                save_backup(output, messages)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"poll error: {e}", file=sys.stderr)

    save_backup(output, messages)
    print(f"\nstopped. {len(messages)} total messages saved to {output}")


if __name__ == "__main__":
    main()
