from enum import Enum


class JobType(Enum):
    AUTOMATION = "automation"
    CODING = "coding"
    DATA_ENTRY = "data_entry"


ALIASES = {
    "automation": JobType.AUTOMATION,
    "auto": JobType.AUTOMATION,
    "coding": JobType.CODING,
    "code": JobType.CODING,
    "software": JobType.CODING,
    "data entry": JobType.DATA_ENTRY,
    "data_entry": JobType.DATA_ENTRY,
    "dataentry": JobType.DATA_ENTRY,
    "entry": JobType.DATA_ENTRY,
}


def resolve(raw: str | None) -> JobType:
    """Resolve a raw string to a JobType enum. Defaults to AUTOMATION."""
    if not raw:
        return JobType.AUTOMATION
    return ALIASES.get(raw.strip().lower(), JobType.AUTOMATION)


def infer_from_title(title: str) -> JobType:
    """Infer job type from a job title string."""
    t = title.lower()
    if any(kw in t for kw in ("data entry", "clerk", "data analyst")):
        return JobType.DATA_ENTRY
    if any(kw in t for kw in ("software", "engineer", "developer", "programmer")):
        return JobType.CODING
    return JobType.AUTOMATION
