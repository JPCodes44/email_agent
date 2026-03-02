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


ANTHROPIC_API_KEY = get("ANTHROPIC_API_KEY")
CANDIDATE_NAME = get("CANDIDATE_NAME", "Justin Mak")

LLM_MODEL = get("LLM_MODEL", "qwen3-coder-next:cloud")
LLM_BASE_URL = get("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_API_KEY = get("LLM_API_KEY", "ollama")

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

LINKEDIN_EMAIL = get("LINKEDIN_EMAIL", "")
LINKEDIN_PASSWORD = get("LINKEDIN_PASSWORD", "")

# Rotating proxy — format: http://user:pass@host:port
PROXY_URL = get("PROXY_URL", "")

# PhantomBuster LinkedIn scraping
PHANTOMBUSTER_API_KEY = get("PHANTOMBUSTER_API_KEY", "")
PHANTOMBUSTER_AGENT_ID = get("PHANTOMBUSTER_AGENT_ID", "")

# Exa AI search
EXA_API_KEY = get("EXA_API_KEY", "")

# OpenClaw browser automation
OPENCLAW_URL = get("OPENCLAW_URL", "")
OPENCLAW_TOKEN = get("OPENCLAW_TOKEN", "")

# Perplexity AI search
PERPLEXITY_API_KEY = get("PERPLEXITY_API_KEY", "")

OUTPUT_DIR = WORKFLOWS_DIR / "output"
COOP_DIR = WORKFLOWS_DIR / "resumes"
