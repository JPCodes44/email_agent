#!/usr/bin/env python3
"""Workflow 3: Email Drafter — create Gmail drafts via IMAP APPEND."""

import sys, argparse, logging, imaplib, email
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared import config
from shared.logging_setup import setup as setup_logging
from shared.csv_utils import read_csv, write_csv, filter_not_emailed
from shared.company_utils import normalize
from shared.job_types import resolve as resolve_job_type
from shared.resume_utils import get_resume_path
from shared.template_utils import parse_template, substitute_name, find_template

log = logging.getLogger("workflows")

IMAP_SERVER = "imap.gmail.com"
IMAP_PORT = 993


def build_mime(to_email: str, subject: str, body: str,
               resume_path: Path | None) -> MIMEMultipart:
    """Build a MIME message with optional PDF attachment."""
    msg = MIMEMultipart()
    msg["From"] = f"{config.FROM_NAME} <{config.FROM_EMAIL}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    if resume_path and resume_path.exists():
        with open(resume_path, "rb") as f:
            att = MIMEApplication(f.read(), _subtype="pdf")
            att.add_header("Content-Disposition", "attachment", filename=resume_path.name)
            msg.attach(att)

    return msg


def append_to_drafts(imap: imaplib.IMAP4_SSL, msg: MIMEMultipart) -> str | None:
    """APPEND a message to Gmail's Drafts folder and return the Gmail draft URL."""
    result = imap.append("[Gmail]/Drafts", "", imaplib.Time2Internaldate(email.utils.localtime()), msg.as_bytes())

    # result looks like ('OK', [b'[APPENDUID 1 12345] (Success)'])
    # Extract the UID to build a Gmail URL
    if result[0] == "OK" and result[1]:
        import re
        match = re.search(r"APPENDUID \d+ (\d+)", result[1][0].decode())
        if match:
            uid = match.group(1)
            # Gmail draft URL format: search for the draft by message ID
            msg_id = msg.get("Message-ID", "").strip("<>")
            if msg_id:
                return f"https://mail.google.com/mail/u/0/#drafts?compose={msg_id}"
            return f"https://mail.google.com/mail/u/0/#drafts"

    return "https://mail.google.com/mail/u/0/#drafts"


def main():
    parser = argparse.ArgumentParser(description="Create Gmail drafts from templates")
    parser.add_argument("--dry-run", action="store_true", help="Preview without creating drafts")
    parser.add_argument("--company", default=None, help="Draft for a single company only")
    parser.add_argument("--emails-dir", type=Path, default=None, help="Template directory")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    setup_logging(args.verbose)

    emails_dir = args.emails_dir or config.OUTPUT_DIR / "emails"
    csv_path = config.WORKFLOWS_DIR / "list.csv"

    if not csv_path.exists():
        log.error(f"Recruiters CSV not found: {csv_path}")
        sys.exit(1)

    all_rows = read_csv(csv_path)
    contacts = filter_not_emailed(all_rows)
    if not contacts:
        log.info("No contacts to draft (all marked as emailed)")
        return

    if args.company:
        contacts = [r for r in contacts if normalize(r.get("Company", "")) == normalize(args.company)]

    log.info(f"Drafting emails for {len(contacts)} contacts")

    imap = None
    if not args.dry_run:
        if not config.SMTP_USERNAME or not config.SMTP_PASSWORD:
            log.error("SMTP_USERNAME and SMTP_PASSWORD required in .env")
            sys.exit(1)
        imap = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        imap.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)

    # Build a lookup so we can update draft links in all_rows
    email_to_row = {}
    for row in all_rows:
        email_to_row[row.get("Email", "").strip()] = row

    csv_changed = False

    try:
        for row in contacts:
            company = row.get("Company", "").strip()
            first_name = row.get("FirstName", "").strip()
            to_email = row.get("Email", "").strip()

            if not to_email:
                log.warning(f"  ⏭ {company} — no email address")
                continue

            try:
                tpl_path = find_template(company, emails_dir)
                if not tpl_path:
                    log.warning(f"  ⏭ {company} — no template found in {emails_dir}")
                    continue

                tpl = parse_template(tpl_path)
                subject = substitute_name(tpl["subject"], first_name) if first_name else tpl["subject"]
                body = substitute_name(tpl["body"], first_name) if first_name else tpl["body"]

                job_type = resolve_job_type(row.get("JobType", ""))
                resume_path = get_resume_path(company, job_type)

                if args.dry_run:
                    log.info(
                        f"  [DRY RUN] {company} → {to_email}\n"
                        f"    Subject: {subject}\n"
                        f"    Resume: {resume_path or 'none'}"
                    )
                    continue

                msg = build_mime(to_email, subject, body, resume_path)
                draft_url = append_to_drafts(imap, msg)
                log.info(f"  ✓ Draft created for {company} → {to_email}")

                # Update the draft link in the CSV row
                if to_email in email_to_row:
                    email_to_row[to_email]["EmailLink"] = draft_url or ""
                    csv_changed = True

            except Exception as e:
                log.error(f"  ✗ Failed for {company}: {e}")
    finally:
        if imap:
            imap.logout()

    # Write updated CSV with draft links
    if csv_changed:
        # Ensure EmailLink column exists in all rows
        for r in all_rows:
            r.setdefault("EmailLink", "")
        write_csv(csv_path, all_rows)
        log.info(f"  ✓ Updated {csv_path.name} with draft links")


if __name__ == "__main__":
    main()
