#!/usr/bin/env python3
"""Delete all drafts from Gmail via IMAP."""

import sys, imaplib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared import config


def main():
    if not config.SMTP_USERNAME or not config.SMTP_PASSWORD:
        print("SMTP_USERNAME and SMTP_PASSWORD required in .env", file=sys.stderr)
        sys.exit(1)

    imap = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    imap.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)

    imap.select("[Gmail]/Drafts")
    status, data = imap.search(None, "ALL")

    if status == "OK" and data[0]:
        msg_ids = data[0].split()
        for msg_id in msg_ids:
            imap.store(msg_id, "+FLAGS", "\\Deleted")
        imap.expunge()
        print(f"Deleted {len(msg_ids)} drafts")
    else:
        print("No drafts to delete")

    imap.logout()


if __name__ == "__main__":
    main()
