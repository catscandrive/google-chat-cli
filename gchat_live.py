#!/usr/bin/env python3
"""Interactive live chat REPL for Google Chat."""

from __future__ import annotations

import argparse
import cmd
import json
import subprocess
import sys
import textwrap
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
GCHAT = BASE / "gchat"


def run_gchat(*args: str) -> dict | list:
    proc = subprocess.run([str(GCHAT), *args], capture_output=True, text=True)
    out = (proc.stdout or proc.stderr).strip()
    if not out:
        if proc.returncode == 0:
            return {}
        raise RuntimeError("gchat returned no output")
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        raise RuntimeError(out)
    if proc.returncode != 0:
        raise RuntimeError(json.dumps(data, indent=2, ensure_ascii=False))
    return data


def pretty_messages(messages: list[dict], known: set[str] | None = None) -> list[str]:
    lines: list[str] = []
    known = known or set()
    for msg in messages:
        name = msg.get("name") or ""
        marker = "*" if name and name not in known else " "
        sender = msg.get("sender") or "unknown"
        ts = msg.get("createTime") or ""
        text = (msg.get("text") or "").strip().replace("\n", " ")
        if len(text) > 220:
            text = text[:217] + "..."
        lines.append(f"{marker} {sender} [{ts}] {text}")
    return lines


class LiveChat(cmd.Cmd):
    intro = "Google Chat live mode. /help for commands. Type plain text to send."
    prompt = "(gchat) "

    def __init__(self, poll: float = 5.0):
        super().__init__()
        self.poll = poll
        self.space: str | None = None
        self.label: str | None = None
        self.seen: set[str] = set()
        self.last_refresh = 0.0

    def preloop(self):
        try:
            who = run_gchat("whoami")
            print(f"Authenticated: {who.get('authenticated', False)}")
            if who.get("authenticated"):
                print("Scopes:")
                for scope in who.get("scopes", []):
                    print(f"  - {scope}")
        except Exception as e:
            print(e)
            print("Run gchat-setup first.")

    def emptyline(self):
        self.do_refresh("")

    def default(self, line: str):
        raw = line.strip()
        if not raw:
            return

        if raw.startswith("/"):
            cmd_name, _, rest = raw[1:].partition(" ")
            cmd_name = cmd_name.replace("-", "_")
            handler = getattr(self, f"do_{cmd_name}", None)
            if handler is None:
                print(f"unknown command: {raw}")
                return
            handler(rest.strip())
            return

        if not self.space:
            print("No active chat. Use /dm EMAIL or /space SPACE_ID first.")
            return
        try:
            run_gchat("send-space", self.space, raw)
            print("sent")
            self.do_refresh("")
        except Exception as e:
            print(e)

    def do_dm(self, arg: str):
        """/dm person@example.com  -> open or create a DM"""
        email = arg.strip()
        if not email:
            print("usage: /dm person@example.com")
            return
        try:
            data = run_gchat("dm-resolve", email, "--create-if-missing")
            space = (data.get("space") or {}).get("name")
            if not space:
                print(json.dumps(data, indent=2))
                return
            self.space = space
            self.label = email
            self.seen = set()
            print(f"active: {email} -> {space}")
            self.do_refresh("")
        except Exception as e:
            print(e)

    def do_space(self, arg: str):
        """/space spaces/AAAA123  -> open a known space"""
        space = arg.strip()
        if not space:
            print("usage: /space spaces/AAAA123")
            return
        self.space = space
        self.label = space
        self.seen = set()
        print(f"active: {space}")
        self.do_refresh("")

    def do_list(self, arg: str):
        """/list [N] -> list spaces"""
        max_items = arg.strip() or "20"
        try:
            data = run_gchat("spaces-list", "--max", max_items)
            for item in data:
                name = item.get("name")
                display = item.get("displayName") or "(no title)"
                stype = item.get("spaceType") or "?"
                print(f"{name} | {stype} | {display}")
        except Exception as e:
            print(e)

    def do_refresh(self, _arg: str):
        """/refresh -> fetch recent messages for the active chat"""
        if not self.space:
            print("No active chat.")
            return
        try:
            msgs = run_gchat("messages-list", self.space, "--max", "20")
            for line in pretty_messages(msgs, self.seen):
                print(line)
            self.seen.update(m.get("name") for m in msgs if m.get("name"))
            self.last_refresh = time.time()
        except Exception as e:
            print(e)

    def do_watch(self, arg: str):
        """/watch [seconds] -> poll current chat for new messages"""
        if not self.space:
            print("No active chat.")
            return
        secs = float(arg.strip() or self.poll)
        print(f"watching {self.label or self.space} every {secs:.1f}s. Ctrl+C to stop.")
        try:
            while True:
                self.do_refresh("")
                time.sleep(secs)
        except KeyboardInterrupt:
            print("\nstopped")

    def do_status(self, _arg: str):
        """/status -> show active chat"""
        print(json.dumps({
            "space": self.space,
            "label": self.label,
            "seen_messages": len(self.seen),
        }, indent=2))

    def do_help(self, arg: str):
        if arg:
            return super().do_help(arg)
        print(textwrap.dedent("""
        Commands:
          /dm EMAIL       open or create a DM with someone
          /space SPACE    open a known space id
          /list [N]       list spaces
          /refresh        fetch recent messages
          /watch [secs]   live poll current chat
          /status         show active chat
          /quit           exit

        Anything without a leading slash is sent as a message to the active chat.
        """).strip())

    def do_quit(self, _arg: str):
        return True

    def do_exit(self, _arg: str):
        return True


def main():
    parser = argparse.ArgumentParser(description="Live interactive Google Chat CLI")
    parser.add_argument("--dm", help="Open this email immediately")
    parser.add_argument("--space", help="Open this space immediately")
    parser.add_argument("--watch", action="store_true", help="Start watch mode after opening the target")
    parser.add_argument("--poll", type=float, default=5.0, help="Default poll seconds for /watch")
    args = parser.parse_args()

    shell = LiveChat(poll=args.poll)
    if args.dm:
        shell.preloop()
        shell.do_dm(args.dm)
        if args.watch:
            shell.do_watch(str(args.poll))
            return
    elif args.space:
        shell.preloop()
        shell.do_space(args.space)
        if args.watch:
            shell.do_watch(str(args.poll))
            return
    shell.cmdloop()


if __name__ == "__main__":
    main()
