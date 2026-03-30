#!/usr/bin/env python3
"""Non-interactive OAuth setup for Google Chat CLI."""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

APP_HOME = Path(os.getenv("GOOGLE_CHAT_CLI_HOME", Path.home() / ".google-chat-cli"))
APP_HOME.mkdir(parents=True, exist_ok=True)
TOKEN_PATH = APP_HOME / "token.json"
CLIENT_SECRET_PATH = APP_HOME / "client_secret.json"
PENDING_AUTH_PATH = APP_HOME / "pending_oauth.json"
REDIRECT_URI = "http://localhost:1"
SCOPES = [
    "https://www.googleapis.com/auth/chat.spaces",
    "https://www.googleapis.com/auth/chat.spaces.create",
    "https://www.googleapis.com/auth/chat.messages.create",
    "https://www.googleapis.com/auth/chat.messages.readonly",
]
REQUIRED_PACKAGES = [
    "google-api-python-client",
    "google-auth-oauthlib",
    "google-auth-httplib2",
]


def install_deps() -> bool:
    try:
        import googleapiclient  # noqa: F401
        import google_auth_oauthlib  # noqa: F401
        return True
    except ImportError:
        pass

    cmd = [sys.executable, "-m", "pip", "install", "--quiet", *REQUIRED_PACKAGES]
    try:
        subprocess.check_call(cmd)
        return True
    except subprocess.CalledProcessError:
        print("ERROR: failed installing Google packages", file=sys.stderr)
        print("Run this manually:", " ".join(cmd), file=sys.stderr)
        return False


def ensure_deps() -> None:
    if not install_deps():
        sys.exit(1)


def check_auth() -> bool:
    if not TOKEN_PATH.exists():
        print(f"NOT_AUTHENTICATED: no token at {TOKEN_PATH}")
        return False

    ensure_deps()
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    try:
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    except Exception as e:
        print(f"TOKEN_CORRUPT: {e}")
        return False

    if creds.valid:
        print(f"AUTHENTICATED: {TOKEN_PATH}")
        return True

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN_PATH.write_text(creds.to_json())
            print(f"AUTHENTICATED: refreshed {TOKEN_PATH}")
            return True
        except Exception as e:
            print(f"REFRESH_FAILED: {e}")
            return False

    print("TOKEN_INVALID")
    return False


def store_client_secret(path: str) -> None:
    src = Path(path).expanduser().resolve()
    if not src.exists():
        print(f"ERROR: file not found: {src}")
        sys.exit(1)

    try:
        data = json.loads(src.read_text())
    except json.JSONDecodeError:
        print("ERROR: client secret is not valid JSON")
        sys.exit(1)

    if "installed" not in data and "web" not in data:
        print("ERROR: not a Google OAuth client secret JSON")
        sys.exit(1)

    shutil.copyfile(src, CLIENT_SECRET_PATH)
    os.chmod(CLIENT_SECRET_PATH, 0o600)
    print(str(CLIENT_SECRET_PATH))


def save_pending_auth(state: str, code_verifier: str) -> None:
    PENDING_AUTH_PATH.write_text(json.dumps({
        "state": state,
        "code_verifier": code_verifier,
        "redirect_uri": REDIRECT_URI,
    }, indent=2))
    os.chmod(PENDING_AUTH_PATH, 0o600)


def load_pending_auth() -> dict:
    if not PENDING_AUTH_PATH.exists():
        print("ERROR: no pending OAuth session, run --auth-url first")
        sys.exit(1)
    return json.loads(PENDING_AUTH_PATH.read_text())


def extract_code_and_state(value: str) -> tuple[str, str | None]:
    if not value.startswith("http"):
        return value, None
    parsed = urlparse(value)
    params = parse_qs(parsed.query)
    code = params.get("code", [None])[0]
    if not code:
        print("ERROR: no code= found in pasted URL")
        sys.exit(1)
    return code, params.get("state", [None])[0]


def get_auth_url() -> None:
    if not CLIENT_SECRET_PATH.exists():
        print("ERROR: no stored client secret, run --client-secret first")
        sys.exit(1)

    ensure_deps()
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_secrets_file(
        str(CLIENT_SECRET_PATH),
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
        autogenerate_code_verifier=True,
    )
    auth_url, state = flow.authorization_url(access_type="offline", prompt="consent")
    save_pending_auth(state, flow.code_verifier)
    print(auth_url)


def exchange_auth_code(value: str) -> None:
    if not CLIENT_SECRET_PATH.exists():
        print("ERROR: no stored client secret, run --client-secret first")
        sys.exit(1)

    pending = load_pending_auth()
    code, returned_state = extract_code_and_state(value)
    if returned_state and returned_state != pending["state"]:
        print("ERROR: OAuth state mismatch; run --auth-url again")
        sys.exit(1)

    ensure_deps()
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_secrets_file(
        str(CLIENT_SECRET_PATH),
        scopes=SCOPES,
        redirect_uri=pending.get("redirect_uri", REDIRECT_URI),
        state=pending["state"],
        code_verifier=pending["code_verifier"],
    )
    try:
        flow.fetch_token(code=code)
    except Exception as e:
        print(f"ERROR: token exchange failed: {e}")
        sys.exit(1)

    TOKEN_PATH.write_text(flow.credentials.to_json())
    os.chmod(TOKEN_PATH, 0o600)
    PENDING_AUTH_PATH.unlink(missing_ok=True)
    print(str(TOKEN_PATH))


def revoke() -> None:
    TOKEN_PATH.unlink(missing_ok=True)
    PENDING_AUTH_PATH.unlink(missing_ok=True)
    print("revoked-local")


def main() -> None:
    parser = argparse.ArgumentParser(description="Google Chat CLI OAuth helper")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--client-secret")
    group.add_argument("--auth-url", action="store_true")
    group.add_argument("--auth-code")
    group.add_argument("--install-deps", action="store_true")
    group.add_argument("--revoke", action="store_true")
    args = parser.parse_args()

    if args.check:
        sys.exit(0 if check_auth() else 1)
    if args.client_secret:
        store_client_secret(args.client_secret)
        return
    if args.auth_url:
        get_auth_url()
        return
    if args.auth_code:
        exchange_auth_code(args.auth_code)
        return
    if args.install_deps:
        sys.exit(0 if install_deps() else 1)
    if args.revoke:
        revoke()


if __name__ == "__main__":
    main()
