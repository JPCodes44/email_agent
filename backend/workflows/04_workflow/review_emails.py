#!/usr/bin/env python3
"""Workflow 4: Email Review — cross-check templates against resumes before sending."""

import sys, argparse, logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared import config
from shared.logging_setup import setup as setup_logging
from shared.csv_utils import read_csv, filter_not_emailed
from shared.company_utils import normalize, filename_safe
from shared.job_types import resolve as resolve_job_type
from shared.resume_utils import get_resume_path, extract_pdf_text, find_company_resume
from shared.template_utils import find_template, parse_template

from rich.console import Console
from rich.table import Table
from anthropic import Anthropic

log = logging.getLogger("workflows")
console = Console()


def check_pdf_pages(path: Path) -> int:
    """Return page count using pdfplumber."""
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return len(pdf.pages)


def check_pdf_clipping(path: Path) -> bool:
    """Check for text clipping using pymupdf. Returns True if no clipping detected."""
    import fitz
    doc = fitz.open(str(path))
    for page in doc:
        rect = page.rect
        blocks = page.get_text("dict")["blocks"]
        for block in blocks:
            if block.get("type") != 0:
                continue
            bbox = block["bbox"]
            # Check if text extends beyond page margins (10pt tolerance)
            if bbox[2] > rect.width + 10 or bbox[3] > rect.height + 10:
                doc.close()
                return False
    doc.close()
    return True


def claude_quality_check(client: Anthropic, email_body: str, resume_text: str) -> dict:
    """Use Claude haiku to check email quality against resume."""
    prompt = (
        f"Review this cold outreach email and the candidate's resume. Answer these questions:\n\n"
        f"EMAIL:\n{email_body}\n\n"
        f"RESUME:\n{resume_text[:3000]}\n\n"
        f"1. Does the email contain a sentence with a concrete OUTCOME (a metric, result, or measurable impact)? "
        f"Not just process (like 'built workflows') but actual results (like 'cut time from 4h to 15min'). "
        f"Answer: outcome_present = true/false\n"
        f"2. Does the resume text support the claim made in the email? Answer: resume_supports = true/false\n"
        f"3. Are there any inconsistencies between the email and resume? Answer: inconsistencies = none or describe\n\n"
        f"Return ONLY a JSON object with keys: outcome_present (bool), resume_supports (bool), inconsistencies (string)"
    )

    resp = client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text
    try:
        import json
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        return json.loads(text.strip())
    except Exception:
        return {"outcome_present": None, "resume_supports": None, "inconsistencies": text}


def main():
    parser = argparse.ArgumentParser(description="Review email templates and resumes")
    parser.add_argument("--company", default=None, help="Review a single company")
    parser.add_argument("--emails-dir", type=Path, default=None, help="Template directory")
    parser.add_argument("--output", type=Path, default=None, help="Save markdown report")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    setup_logging(args.verbose)

    emails_dir = args.emails_dir or config.OUTPUT_DIR / "emails"
    csv_path = config.WORKFLOWS_DIR / "list.csv"

    if not csv_path.exists():
        log.error(f"Recruiters CSV not found: {csv_path}")
        sys.exit(1)

    rows = filter_not_emailed(read_csv(csv_path))

    # Deduplicate by company
    seen = {}
    for row in rows:
        company = row.get("Company", "").strip()
        if not company:
            continue
        norm = normalize(company)
        if args.company and normalize(args.company) != norm:
            continue
        if norm not in seen:
            seen[norm] = row

    if not seen:
        log.info("No companies to review")
        return

    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)

    table = Table(title="Email Review", show_lines=True)
    table.add_column("Company", style="bold")
    table.add_column("Resume", justify="center")
    table.add_column("Pages", justify="center")
    table.add_column("Clip?", justify="center")
    table.add_column("[FIRST]", justify="center")
    table.add_column("Outcome", justify="center")
    table.add_column("Aligns", justify="center")
    table.add_column("Notes")

    report_lines = ["# Email Review Report\n"] if args.output else []

    for norm, row in seen.items():
        company = row["Company"]
        job_type = resolve_job_type(row.get("Job Type", ""))
        notes = []

        # Find template
        tpl_path = find_template(company, emails_dir)
        if not tpl_path:
            table.add_row(company, "—", "—", "—", "—", "—", "—", "No template found")
            continue

        tpl = parse_template(tpl_path)

        # Find resume
        resume_path = get_resume_path(company, job_type)
        resume_found = "✓" if resume_path else "✗"
        pages_str = "—"
        clip_str = "—"
        resume_text = ""

        if resume_path and resume_path.exists():
            try:
                pages = check_pdf_pages(resume_path)
                pages_str = str(pages)
                if pages != 1:
                    notes.append(f"Resume is {pages} pages (should be 1)")
            except Exception as e:
                pages_str = "err"
                notes.append(f"PDF page check failed: {e}")

            try:
                no_clip = check_pdf_clipping(resume_path)
                clip_str = "✓" if no_clip else "✗"
                if not no_clip:
                    notes.append("Text clipping detected")
            except Exception as e:
                clip_str = "err"
                notes.append(f"Clip check failed: {e}")

            try:
                resume_text = extract_pdf_text(resume_path)
            except Exception:
                pass

        # Placeholder check
        has_placeholder = "[RECRUITER_FIRST_NAME]" in tpl["raw"]
        placeholder_str = "✓" if has_placeholder else "✗"
        if not has_placeholder:
            notes.append("Missing [RECRUITER_FIRST_NAME] placeholder")

        # Claude quality check
        outcome_str = "—"
        aligns_str = "—"
        if tpl["body"] and resume_text:
            try:
                quality = claude_quality_check(client, tpl["body"], resume_text)
                outcome_str = "✓" if quality.get("outcome_present") else "✗"
                aligns_str = "✓" if quality.get("resume_supports") else "✗"
                inconsistencies = quality.get("inconsistencies", "none")
                if inconsistencies and inconsistencies.lower() != "none":
                    notes.append(f"Inconsistency: {inconsistencies}")
                if not quality.get("outcome_present"):
                    notes.append("No concrete outcome in email")
                if not quality.get("resume_supports"):
                    notes.append("Resume doesn't support email claim")
            except Exception as e:
                outcome_str = "err"
                aligns_str = "err"
                notes.append(f"Claude review failed: {e}")

        notes_str = "; ".join(notes) if notes else "OK"
        table.add_row(company, resume_found, pages_str, clip_str,
                       placeholder_str, outcome_str, aligns_str, notes_str)

        if args.output:
            status = "PASS" if not notes else "ISSUES"
            report_lines.append(f"\n## {company} — {status}\n")
            for n in notes:
                report_lines.append(f"- {n}")

    console.print(table)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text("\n".join(report_lines), encoding="utf-8")
        log.info(f"Report saved to {args.output}")


if __name__ == "__main__":
    main()
