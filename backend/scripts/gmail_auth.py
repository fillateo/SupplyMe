"""One-time Gmail OAuth, and starting the push watch.

Gmail is the only integration that needs a human to sign in. The token is
written to secrets/gmail_token.json, which is gitignored; in the cloud, put the
same JSON in Secret Manager and mount it.

    python scripts/gmail_auth.py --client-secret client_secret.json
    python scripts/gmail_auth.py --watch projects/PROJECT/topics/vds-gmail
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TOKEN_PATH = Path("secrets/gmail_token.json")


def authorize(client_secret: Path) -> None:
    from google_auth_oauthlib.flow import InstalledAppFlow

    from app.adapters.gmail_provider import SCOPES

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
    credentials = flow.run_local_server(port=8765)
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(credentials.to_json())
    TOKEN_PATH.chmod(0o600)
    print(f"Token written to {TOKEN_PATH}. It is gitignored; keep it that way.")


async def start_watch(topic: str) -> None:
    from app.adapters.gmail_provider import GmailProvider, credentials_from_dict
    from app.config import get_settings

    if not TOKEN_PATH.exists():
        raise SystemExit("No token. Run with --client-secret first.")
    provider = GmailProvider(
        get_settings(), credentials_from_dict(json.loads(TOKEN_PATH.read_text()))
    )
    history_id = await provider.watch(topic)
    print(f"Gmail will now push to {topic}. Current historyId: {history_id}")
    print("Gmail watches expire after 7 days — re-run this to renew.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-secret", type=Path, help="OAuth client secret JSON")
    parser.add_argument("--watch", help="Pub/Sub topic to receive push notifications")
    args = parser.parse_args()

    if args.client_secret:
        authorize(args.client_secret)
    if args.watch:
        asyncio.run(start_watch(args.watch))
    if not args.client_secret and not args.watch:
        parser.print_help()
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
