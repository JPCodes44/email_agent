from pathlib import Path
from shared import config
from shared.job_types import JobType
from shared.company_utils import normalize


def find_company_resume(company: str) -> Path | None:
    """Look for a company-specific resume in the coop directory."""
    coop = config.COOP_DIR
    if not coop.is_dir():
        return None
    norm = normalize(company)
    for f in coop.glob("Justin_Mak_s_Resume_*.pdf"):
        # Strip prefix and .pdf, then normalize
        stem = f.stem.replace("Justin_Mak_s_Resume_", "")
        if normalize(stem) == norm:
            return f
    return None


def get_resume_path(company: str, job_type: JobType) -> Path | None:
    """Select the best resume: company-specific > job-type > fallback."""
    # 1. Company-specific
    company_resume = find_company_resume(company)
    if company_resume and company_resume.exists():
        return company_resume

    # 2. Job-type specific
    type_map = {
        JobType.CODING: config.RESUME_PATH_CODING,
        JobType.AUTOMATION: config.RESUME_PATH_AUTOMATION,
        JobType.DATA_ENTRY: config.RESUME_PATH_DATA_ENTRY,
    }
    typed = type_map.get(job_type, "")
    if typed:
        p = Path(typed) if Path(typed).is_absolute() else config.COOP_DIR / typed
        if p.exists():
            return p

    # 3. Fallback
    if config.RESUME_PATH:
        p = Path(config.RESUME_PATH) if Path(config.RESUME_PATH).is_absolute() else config.COOP_DIR / config.RESUME_PATH
        if p.exists():
            return p

    return None


def extract_pdf_text(path: Path) -> str:
    """Extract text from a PDF file using pdfplumber."""
    import pdfplumber
    text = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text.append(t)
    return "\n".join(text)
