from pathlib import Path
from shared import config
from shared.job_types import JobType


# Map each JobType to the actual resume filename in the resumes directory
_RESUME_FILENAMES = {
    JobType.AUTOMATION: "Justin_Mak_s_Resume_Automation (2).pdf",
    JobType.CODING: "Justin_Mak_s_Resume_Coding.pdf",
    JobType.DATA_ENTRY: "Justin_Mak_s_Resume_Data_Entry.pdf",
}


def get_resume_path(company: str, job_type: JobType) -> Path | None:
    """Select the resume that matches the job type."""
    filename = _RESUME_FILENAMES.get(job_type)
    if not filename:
        return None
    path = config.COOP_DIR / filename
    return path if path.exists() else None


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
