# Google Chat CLI

Interactive Google Chat CLI for sending DMs, posting to spaces, and running a live terminal chat shell as your authenticated Google account.

Features:
- resolve an existing DM by email
- create a DM if one does not exist
- send a DM
- send a message to a known space
- list spaces
- list recent messages in a space
- run an interactive live shell with polling

Files:
- `gchat-setup` — OAuth setup helper
- `gchat` — main non-interactive CLI
- `gchat-live` — interactive live chat shell
- `setup.py` — underlying setup script
- `gchat.py` — main non-interactive implementation
- `gchat_live.py` — interactive REPL/watch mode

## One-time setup

1. Create a Google OAuth desktop client in Google Cloud Console.
2. Enable the Google Chat API for that project.
3. Download the OAuth client JSON.
4. Store it:
   `~/docs/google-chat-cli/gchat-setup --client-secret /path/to/client_secret.json`
5. Get auth URL:
   `~/docs/google-chat-cli/gchat-setup --auth-url`
6. Open it, approve, then paste back the full redirected URL.
7. Exchange it:
   `~/docs/google-chat-cli/gchat-setup --auth-code 'PASTE_FULL_REDIRECT_URL_HERE'`
8. Verify:
   `~/docs/google-chat-cli/gchat-setup --check`

Important: if you authenticated before the live CLI existed, re-run auth once so the token includes message read scope:
`~/docs/google-chat-cli/gchat-setup --auth-url`
then
`~/docs/google-chat-cli/gchat-setup --auth-code 'PASTE_FULL_REDIRECT_URL_HERE'`

Stored auth lives in `~/.google-chat-cli/`.

## Usage

List spaces:
`~/docs/google-chat-cli/gchat spaces-list --max 20`

Resolve a DM by email:
`~/docs/google-chat-cli/gchat dm-resolve person@example.com --create-if-missing`

Send a DM:
`~/docs/google-chat-cli/gchat send-dm person@example.com 'hey, quick note'`

List recent messages in a space:
`~/docs/google-chat-cli/gchat messages-list spaces/AAAA1234567 --max 20`

Send to a known space:
`~/docs/google-chat-cli/gchat send-space spaces/AAAA1234567 'status update here'`

Interactive live shell:
`~/docs/google-chat-cli/gchat-live`

Jump straight into a DM and watch:
`~/docs/google-chat-cli/gchat-live --dm person@example.com --watch`

## Notes

- This uses user OAuth and sends messages as you.
- DM creation relies on Google Chat API `spaces.setup` and `spaces.findDirectMessage`.
- If the other person blocks you, or org policy forbids it, DM creation will fail.
- If you use multiple Google accounts, authorize the right one. Google will happily let you shoot yourself in the foot.
