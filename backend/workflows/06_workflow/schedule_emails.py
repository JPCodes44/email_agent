#!/usr/bin/env python3
"""Workflow 5b: Scheduled Email Sender — send emails at optimal local times."""

import sys, argparse, logging, smtplib, time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared import config
from shared.logging_setup import setup as setup_logging
from shared.csv_utils import read_csv, write_csv, filter_not_emailed
from shared.company_utils import normalize
from shared.job_types import resolve as resolve_job_type, infer_from_title
from shared.resume_utils import get_resume_path
from shared.template_utils import parse_template, substitute_name, find_template

import pytz
from apscheduler.schedulers.blocking import BlockingScheduler

log = logging.getLogger("workflows")

# Map country/region to timezone
TIMEZONE_MAP = {
    "california": "America/Los_Angeles",
    "new york": "America/New_York",
    "texas": "America/Chicago",
    "illinois": "America/Chicago",
    "washington": "America/Los_Angeles",
    "oregon": "America/Los_Angeles",
    "colorado": "America/Denver",
    "arizona": "America/Phoenix",
    "florida": "America/New_York",
    "georgia": "America/New_York",
    "massachusetts": "America/New_York",
    "ontario": "America/Toronto",
    "british columbia": "America/Vancouver",
    "quebec": "America/Montreal",
    "alberta": "America/Edmonton",
    "uk": "Europe/London",
    "united kingdom": "Europe/London",
    "germany": "Europe/Berlin",
    "france": "Europe/Paris",
    "india": "Asia/Kolkata",
    "australia": "Australia/Sydney",
    "japan": "Asia/Tokyo",
}


def get_timezone(country: str) -> pytz.BaseTzInfo:
    """Map a country/region string to a timezone."""
    key = country.strip().lower()
    tz_name = TIMEZONE_MAP.get(key, "America/New_York")  # default to ET
    return pytz.timezone(tz_name)


def next_business_day(dt: datetime) -> datetime:
    """Advance to the next business day (skip weekends)."""
    next_day = dt + timedelta(days=1)
    while next_day.weekday() >= 5:  # Saturday=5, Sunday=6
        next_day += timedelta(days=1)
    return next_day


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


def send_one(to_email: str, subject: str, body: str, resume_path: Path | None,
             csv_path: Path, all_rows: list[dict]):
    """Send a single email and update CSV."""
    try:
        smtp = smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT)
        smtp.starttls()
        smtp.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)

        msg = build_mime(to_email, subject, body, resume_path)
        smtp.send_message(msg)
        smtp.quit()

        # Mark as sent
        for r in all_rows:
            if r.get("Email", "").strip() == to_email:
                r["Emailed?"] = "Yes"
        write_csv(csv_path, all_rows)

        log.info(f"  ✓ Sent to {to_email}")
    except Exception as e:
        log.error(f"  ✗ Failed sending to {to_email}: {e}")


def main():
    parser = argparse.ArgumentParser(description="Schedule emails by recipient timezone")
    parser.add_argument("csv_path", help="Path to recruiters CSV")
    parser.add_argument("--dry-run", action="store_true", default=None, help="Preview scheduled times")
    parser.add_argument("--no-dry-run", action="store_true", help="Actually schedule and send")
    parser.add_argument("--preview", action="store_true", help="Show scheduled times only")
    parser.add_argument("--start-daemon", action="store_true", help="Start the scheduler daemon")
    parser.add_argument("--send-time", default="09:15", help="Target send time HH:MM (default 09:15)")
    parser.add_argument("--stagger", type=int, default=5, help="Seconds between emails in same TZ (default 5)")
    parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    setup_logging(args.verbose)

    if args.no_dry_run:
        dry_run = False
    elif args.dry_run is not None:
        dry_run = args.dry_run
    else:
        dry_run = config.DRY_RUN

    emails_dir = config.OUTPUT_DIR / "emails"
    csv_path = Path(args.csv_path)

    if not csv_path.exists():
        log.error(f"CSV not found: {csv_path}")
        sys.exit(1)

    all_rows = read_csv(csv_path)
    rows = filter_not_emailed(all_rows)

    if not rows:
        log.info("No contacts to schedule (all marked as emailed)")
        return

    # Parse send time
    send_hour, send_minute = map(int, args.send_time.split(":"))

    # Build schedule
    schedule = []
    for row in rows:
        company = row.get("Company", "").strip()
        first_name = row.get("FirstName", "").strip()
        to_email = row.get("Email", "").strip()
        country = row.get("Country", "").strip()

        if not company or not to_email:
            continue

        tpl_path = find_template(company, emails_dir)
        if not tpl_path:
            log.warning(f"  ⏭ {company} — no template found")
            continue

        tpl = parse_template(tpl_path)

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

        tz = get_timezone(country)
        now_local = datetime.now(tz)
        target_date = next_business_day(now_local)
        send_dt = tz.localize(datetime(target_date.year, target_date.month, target_date.day,
                                        send_hour, send_minute))

        schedule.append({
            "company": company,
            "to_email": to_email,
            "subject": subject,
            "body": body,
            "resume_path": resume_path,
            "send_at": send_dt,
            "timezone": str(tz),
        })

    # Stagger within same timezone
    tz_counters = {}
    for item in schedule:
        tz_key = item["timezone"]
        count = tz_counters.get(tz_key, 0)
        item["send_at"] = item["send_at"] + timedelta(seconds=count * args.stagger)
        tz_counters[tz_key] = count + 1

    # Preview
    if args.preview or dry_run:
        log.info(f"Scheduled {len(schedule)} emails:")
        for item in schedule:
            log.info(
                f"  {item['company']} → {item['to_email']}\n"
                f"    Send at: {item['send_at'].strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
                f"    Resume: {item['resume_path'] or 'none'}"
            )
        if dry_run or args.preview:
            return

    if not args.start_daemon:
        log.error("--start-daemon required for live sends")
        sys.exit(1)

    if not args.yes:
        print(f"\n⚠  LIVE MODE — scheduling {len(schedule)} emails.")
        confirm = input("Type 'yes' to proceed: ")
        if confirm.strip().lower() != "yes":
            print("Aborted.")
            return

    if not config.SMTP_USERNAME or not config.SMTP_PASSWORD:
        log.error("SMTP_USERNAME and SMTP_PASSWORD required in .env")
        sys.exit(1)

    scheduler = BlockingScheduler()

    for item in schedule:
        scheduler.add_job(
            send_one,
            "date",
            run_date=item["send_at"],
            args=[item["to_email"], item["subject"], item["body"],
                  item["resume_path"], csv_path, all_rows],
            id=f"send_{item['to_email']}",
        )
        log.info(f"  Scheduled: {item['company']} → {item['send_at'].strftime('%Y-%m-%d %H:%M:%S %Z')}")

    log.info(f"\nDaemon running. Press Ctrl+C to stop.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
