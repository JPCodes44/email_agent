#!/usr/bin/env python3
"""Workflow 5a: Email Sender — send emails via SMTP with rate limiting."""

import sys, argparse, logging, smtplib, time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared import config
from shared.logging_setup import setup as setup_logging
from shared.csv_utils import read_csv, write_csv, filter_not_emailed
from shared.company_utils import normalize
from shared.job_types import resolve as resolve_job_type, infer_from_title
from shared.resume_utils import get_resume_path
from shared.template_utils import parse_template, substitute_name, find_template

log = logging.getLogger("workflows")

RATE_LIMIT_SECONDS = 5


def build_mime(to_email: str, subject: str, body: str,
               resume_path: Path | None) -> MIMEMultipart:
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


def send_email(smtp: smtplib.SMTP, msg: MIMEMultipart):
    smtp.send_message(msg)


def preview_campaign(rows: list[dict], emails_dir: Path):
    """Print campaign stats without sending."""
    total = len(rows)
    with_template = 0
    without_template = 0
    for row in rows:
        company = row.get("Company", "").strip()
        tpl = find_template(company, emails_dir) if company else None
        if tpl:
            with_template += 1
        else:
            without_template += 1

    log.info(f"Campaign preview:")
    log.info(f"  Total contacts: {total}")
    log.info(f"  With template:  {with_template}")
    log.info(f"  Missing template: {without_template}")


def main():
    parser = argparse.ArgumentParser(description="Send emails via SMTP")
    parser.add_argument("csv_path", help="Path to recruiters CSV")
    parser.add_argument("--dry-run", action="store_true", default=None, help="Preview without sending")
    parser.add_argument("--no-dry-run", action="store_true", help="Actually send emails")
    parser.add_argument("--preview", action="store_true", help="Show campaign stats only")
    parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")
    parser.add_argument("--emails-dir", type=Path, default=None, help="Template directory")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    setup_logging(args.verbose)

    # Determine dry run mode: explicit flag > .env default
    if args.no_dry_run:
        dry_run = False
    elif args.dry_run is not None:
        dry_run = args.dry_run
    else:
        dry_run = config.DRY_RUN

    emails_dir = args.emails_dir or config.OUTPUT_DIR / "emails"
    csv_path = Path(args.csv_path)

    if not csv_path.exists():
        log.error(f"CSV not found: {csv_path}")
        sys.exit(1)

    all_rows = read_csv(csv_path)
    rows = filter_not_emailed(all_rows)

    if not rows:
        log.info("No contacts to send (all marked as emailed)")
        return

    if args.preview:
        preview_campaign(rows, emails_dir)
        return

    if not dry_run and not args.yes:
        print(f"\n⚠  LIVE MODE — about to send {len(rows)} emails via SMTP.")
        confirm = input("Type 'yes' to proceed: ")
        if confirm.strip().lower() != "yes":
            print("Aborted.")
            return

    smtp = None
    if not dry_run:
        if not config.SMTP_USERNAME or not config.SMTP_PASSWORD:
            log.error("SMTP_USERNAME and SMTP_PASSWORD required in .env")
            sys.exit(1)
        smtp = smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT)
        smtp.starttls()
        smtp.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)

    sent_count = 0
    try:
        for row in rows:
            company = row.get("Company", "").strip()
            first_name = row.get("First name", "").strip()
            to_email = row.get("Email", "").strip()

            if not company or not to_email:
                continue

            try:
                tpl_path = find_template(company, emails_dir)
                if not tpl_path:
                    log.warning(f"  ⏭ {company} — no template found")
                    continue

                tpl = parse_template(tpl_path)

                # Determine job type: CSV column > template title inference > default
                job_type_raw = row.get("Job Type", "").strip()
                if job_type_raw:
                    job_type = resolve_job_type(job_type_raw)
                elif tpl["job_title"]:
                    job_type = infer_from_title(tpl["job_title"])
                else:
                    job_type = resolve_job_type(None)

                resume_path = get_resume_path(company, job_type)

                subject = substitute_name(tpl["subject"], first_name) if first_name else tpl["subject"]
                body = substitute_name(tpl["body"], first_name) if first_name else tpl["body"]

                if dry_run:
                    log.info(
                        f"  [DRY RUN] {company} → {to_email}\n"
                        f"    Subject: {subject}\n"
                        f"    Resume: {resume_path or 'none'}"
                    )
                    continue

                msg = build_mime(to_email, subject, body, resume_path)
                send_email(smtp, msg)
                sent_count += 1

                # Mark as sent in CSV
                for r in all_rows:
                    if r.get("Email", "").strip() == to_email:
                        r["Emailed?"] = "Yes"
                write_csv(csv_path, all_rows)

                log.info(f"  ✓ Sent to {to_email} ({company})")

                # Rate limit
                time.sleep(RATE_LIMIT_SECONDS)

            except Exception as e:
                log.error(f"  ✗ Failed for {company}: {e}")
    finally:
        if smtp:
            smtp.quit()

    log.info(f"Done. Sent {sent_count} emails.")


if __name__ == "__main__":
    main()
