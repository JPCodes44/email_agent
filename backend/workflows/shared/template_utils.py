import re
from pathlib import Path


def parse_template(path: Path) -> dict:
    """Parse a _TEMPLATE.txt file and return its components."""
    content = path.read_text(encoding="utf-8")
    result = {
        "company": "",
        "job_title": "",
        "job_url": "",
        "subject": "",
        "body": "",
        "raw": content,
    }

    # Header fields
    for line in content.split("\n"):
        if line.startswith("COMPANY:"):
            result["company"] = line.split(":", 1)[1].strip()
        elif line.startswith("JOB TITLE:"):
            result["job_title"] = line.split(":", 1)[1].strip()
        elif line.startswith("JOB URL:"):
            result["job_url"] = line.split(":", 1)[1].strip()

    # Subject
    m = re.search(r"SUBJECT:\s*(.+)", content)
    if m:
        result["subject"] = m.group(1).strip()

    # Body — everything between BODY: and ===== INSTRUCTIONS =====
    m = re.search(r"BODY:\s*\n(.*?)(?=\n===== INSTRUCTIONS =====|\Z)", content, re.DOTALL)
    if m:
        result["body"] = m.group(1).strip()

    return result


def substitute_name(text: str, first_name: str) -> str:
    """Replace [RECRUITER_FIRST_NAME] placeholder with the actual name."""
    return text.replace("[RECRUITER_FIRST_NAME]", first_name)


def find_template(company: str, emails_dir: Path) -> Path | None:
    """Find a template file for a company (case-insensitive)."""
    from shared.company_utils import normalize
    norm = normalize(company)
    for f in emails_dir.glob("*_TEMPLATE.txt"):
        stem = f.stem.replace("_TEMPLATE", "")
        if normalize(stem) == norm:
            return f
    return None
