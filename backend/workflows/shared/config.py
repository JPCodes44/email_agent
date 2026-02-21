import os
from pathlib import Path
from dotenv import load_dotenv

WORKFLOWS_DIR = Path(__file__).resolve().parent.parent
load_dotenv(WORKFLOWS_DIR / ".env")


def get(key: str, default: str | None = None, required: bool = False) -> str | None:
    val = os.getenv(key, default)
    if required and not val:
        raise EnvironmentError(f"Missing required env var: {key}")
    return val


ANTHROPIC_API_KEY = get("ANTHROPIC_API_KEY", required=True)
CANDIDATE_NAME = get("CANDIDATE_NAME", "Justin Mak")

SMTP_SERVER = get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(get("SMTP_PORT", "587"))
SMTP_USERNAME = get("SMTP_USERNAME", "")
SMTP_PASSWORD = get("SMTP_PASSWORD", "")
FROM_EMAIL = get("FROM_EMAIL", "")
FROM_NAME = get("FROM_NAME", CANDIDATE_NAME)

DRY_RUN = get("DRY_RUN", "true").lower() in ("true", "1", "yes")

RESUME_PATH = get("RESUME_PATH", "")
RESUME_PATH_CODING = get("RESUME_PATH_CODING", "")
RESUME_PATH_AUTOMATION = get("RESUME_PATH_AUTOMATION", "")
RESUME_PATH_DATA_ENTRY = get("RESUME_PATH_DATA_ENTRY", "")

OUTPUT_DIR = WORKFLOWS_DIR / "output"
COOP_DIR = WORKFLOWS_DIR / "resumes"
