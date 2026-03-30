#!/usr/bin/env python3
"""Google Chat CLI for sending DMs and posting in spaces."""

import argparse
import json
import os
import sys
from pathlib import Path

APP_HOME = Path(os.getenv("GOOGLE_CHAT_CLI_HOME", Path.home() / ".google-chat-cli"))
TOKEN_PATH = APP_HOME / "token.json"
SCOPES = [
    "https://www.googleapis.com/auth/chat.spaces",
    "https://www.googleapis.com/auth/chat.spaces.create",
    "https://www.googleapis.com/auth/chat.messages.create",
    "https://www.googleapis.com/auth/chat.messages.readonly",
]


def get_credentials():
    if not TOKEN_PATH.exists():
        print(json.dumps({
            "error": "not_authenticated",
            "hint": "Run setup.py --check / --client-secret / --auth-url / --auth-code first",
            "token_path": str(TOKEN_PATH),
        }, indent=2))
        sys.exit(1)

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json())
    if not creds.valid:
        print(json.dumps({"error": "invalid_token", "token_path": str(TOKEN_PATH)}, indent=2))
        sys.exit(1)
    return creds


def chat_service():
    from googleapiclient.discovery import build
    return build("chat", "v1", credentials=get_credentials(), cache_discovery=False)


def normalize_http_error(err: Exception) -> dict:
    out = {"error": str(err)}
    status = getattr(getattr(err, "resp", None), "status", None)
    if status is not None:
        out["status"] = status
    content = getattr(err, "content", None)
    if content:
        try:
            body = json.loads(content.decode("utf-8", "ignore"))
            out["details"] = body
        except Exception:
            out["details_raw"] = content.decode("utf-8", "ignore")
    return out


def print_json(data):
    print(json.dumps(data, indent=2, ensure_ascii=False))


def cmd_whoami(_args):
    if not TOKEN_PATH.exists():
        print_json({
            "authenticated": False,
            "token_path": str(TOKEN_PATH),
            "hint": "Run gchat-setup first",
        })
        sys.exit(1)

    from google.oauth2.credentials import Credentials
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    print_json({
        "authenticated": True,
        "token_path": str(TOKEN_PATH),
        "scopes": sorted(list(set(creds.scopes or []))),
        "client_id": creds.client_id,
        "quota_project_id": creds.quota_project_id,
    })


def cmd_spaces_list(args):
    svc = chat_service()
    req = svc.spaces().list(pageSize=args.max)
    spaces = []
    while req is not None and len(spaces) < args.max:
        resp = req.execute()
        spaces.extend(resp.get("spaces", []))
        req = svc.spaces().list_next(req, resp)
    trimmed = spaces[:args.max]
    print_json([
        {
            "name": s.get("name"),
            "displayName": s.get("displayName"),
            "spaceType": s.get("spaceType"),
            "spaceThreadingState": s.get("spaceThreadingState"),
            "singleUserBotDm": s.get("singleUserBotDm"),
        }
        for s in trimmed
    ])


def find_dm(email: str):
    svc = chat_service()
    return svc.spaces().findDirectMessage(name=f"users/{email}").execute()


def setup_dm(email: str):
    svc = chat_service()
    body = {
        "space": {
            "spaceType": "DIRECT_MESSAGE",
            "singleUserBotDm": False,
        },
        "memberships": [
            {
                "member": {
                    "name": f"users/{email}",
                    "type": "HUMAN",
                }
            }
        ],
    }
    return svc.spaces().setup(body=body).execute()


def ensure_dm(email: str):
    try:
        dm = find_dm(email)
        return dm, False
    except Exception as e:
        status = getattr(getattr(e, "resp", None), "status", None)
        if status != 404:
            raise
    dm = setup_dm(email)
    return dm, True


def cmd_dm_resolve(args):
    try:
        dm, created = ensure_dm(args.email) if args.create_if_missing else (find_dm(args.email), False)
        print_json({
            "created": created,
            "space": dm,
        })
    except Exception as e:
        print_json(normalize_http_error(e))
        sys.exit(1)


def simplify_message(msg: dict) -> dict:
    sender = ((msg.get("sender") or {}).get("displayName") or
              ((msg.get("sender") or {}).get("name") or "").split("/")[-1])
    create_time = msg.get("createTime") or msg.get("lastUpdateTime")
    return {
        "name": msg.get("name"),
        "text": msg.get("text", ""),
        "sender": sender,
        "createTime": create_time,
        "thread": (msg.get("thread") or {}).get("name"),
    }


def list_messages(space: str, page_size: int = 50):
    svc = chat_service()
    resp = svc.spaces().messages().list(parent=space, pageSize=page_size).execute()
    return resp.get("messages", [])


def cmd_messages_list(args):
    try:
        msgs = list_messages(args.space, args.max)
        print_json([simplify_message(m) for m in msgs])
    except Exception as e:
        print_json(normalize_http_error(e))
        sys.exit(1)


def cmd_send_space(args):
    svc = chat_service()
    try:
        res = svc.spaces().messages().create(parent=args.space, body={"text": args.message}).execute()
        print_json({
            "status": "sent",
            "space": args.space,
            "message": res,
        })
    except Exception as e:
        print_json(normalize_http_error(e))
        sys.exit(1)


def cmd_send_dm(args):
    try:
        dm, created = ensure_dm(args.email)
        space = dm["name"]
        svc = chat_service()
        res = svc.spaces().messages().create(parent=space, body={"text": args.message}).execute()
        print_json({
            "status": "sent",
            "created_dm": created,
            "space": space,
            "message": res,
        })
    except Exception as e:
        print_json(normalize_http_error(e))
        sys.exit(1)


def build_parser():
    parser = argparse.ArgumentParser(description="Google Chat CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    whoami = sub.add_parser("whoami")
    whoami.set_defaults(func=cmd_whoami)

    spaces = sub.add_parser("spaces-list")
    spaces.add_argument("--max", type=int, default=50)
    spaces.set_defaults(func=cmd_spaces_list)

    dm = sub.add_parser("dm-resolve")
    dm.add_argument("email")
    dm.add_argument("--create-if-missing", action="store_true")
    dm.set_defaults(func=cmd_dm_resolve)

    messages = sub.add_parser("messages-list")
    messages.add_argument("space")
    messages.add_argument("--max", type=int, default=20)
    messages.set_defaults(func=cmd_messages_list)

    send_dm = sub.add_parser("send-dm")
    send_dm.add_argument("email")
    send_dm.add_argument("message")
    send_dm.set_defaults(func=cmd_send_dm)

    send_space = sub.add_parser("send-space")
    send_space.add_argument("space")
    send_space.add_argument("message")
    send_space.set_defaults(func=cmd_send_space)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
