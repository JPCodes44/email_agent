import re


def normalize(name: str) -> str:
    """Normalize a company name for matching: lowercase, strip suffixes, collapse whitespace."""
    name = name.strip().lower()
    name = re.sub(r"\s+(inc\.?|ltd\.?|llc|corp\.?|co\.?)$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[^a-z0-9]+", "_", name).strip("_")
    return name


def filename_safe(name: str) -> str:
    """Return a filesystem-safe version of a company name."""
    return re.sub(r"[^\w\s-]", "", name.strip()).replace(" ", "_")
