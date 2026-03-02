#!/usr/bin/env python3
"""Workflow 2: Person Research — LinkedIn scraping via crawl4ai + LLM synthesis."""

import sys, json, argparse, logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared import config
from shared.logging_setup import setup as setup_logging
from shared.csv_utils import read_csv, filter_not_emailed
from shared.company_utils import filename_safe
from shared.llm import create_client, chat
from shared.crawler import find_profile_via_openclaw, scrape_linkedin_profile, directed_crawl, fetch_page

log = logging.getLogger("workflows")

_EMPTY_PATTERNS = [
    "no accessible", "no content available", "no verified", "no verifiable",
    "no concrete", "no previous roles", "not found", "no publicly",
    "not confirmed", "could not be determined", "could not be retrieved",
    "no posts or activity", "no achievements", "no profile data",
    "login page", "did not yield", "were not identified",
    "could not be identified", "no recent posts", "no information",
    "lack of accessible", "no public records", "no results found",
]

_CHECK_FIELDS = ["role", "linkedin_summary", "recent_posts", "achievements", "interests", "previous_experience"]


def _has_useful_data(data: dict) -> bool:
    """Return True if at least one key field has real content."""
    for field in _CHECK_FIELDS:
        val = data.get(field)
        if val is None:
            continue
        if isinstance(val, list):
            val = " ".join(str(v) for v in val)
        val = str(val).lower().strip()
        if val and not any(kw in val for kw in _EMPTY_PATTERNS):
            return True
    return False


PERSON_SCHEMA_STR = """\
- "role": string — their current job title/role
- "linkedin_url": string — their LinkedIn profile URL (if found)
- "linkedin_summary": string — brief summary of their LinkedIn profile, headline, and bio
- "recent_posts": string — summary of their recent LinkedIn posts (what they wrote about, shared/reposted, themes). Be specific, cite actual post content.
- "achievements": string — recent accomplishments, promotions, awards, milestones
- "interests": string — professional interests and causes based on their actual activity (not just bio)
- "previous_experience": string — notable previous roles or companies
Each value must be a plain string. If unknown, use an empty string ""."""


def research_person(llm_client, name: str, company: str, email: str) -> dict:
    """Research a person via LinkedIn scraping with directed_crawl fallback."""
    result = {}
    linkedin_url = None

    # Step 1: Find profile URL via OpenClaw Google search
    profile = find_profile_via_openclaw(email, name, company)

    if profile:
        if profile["type"] == "linkedin":
            # Step 2a: Scrape LinkedIn profile via OpenClaw
            linkedin_url = profile["url"]
            result = scrape_linkedin_profile(llm_client, linkedin_url, PERSON_SCHEMA_STR)
            if result:
                result.setdefault("linkedin_url", linkedin_url)
        else:
            # Step 2b: Non-LinkedIn profile — fetch and extract with LLM
            log.info(f"    Fetching non-LinkedIn profile: {profile['url']}")
            page_text = fetch_page(profile["url"])
            if page_text:
                from shared.llm import chat
                extract_prompt = (
                    f"Extract professional information about {name} ({email}) at {company} "
                    f"from this page:\n\n{page_text[:10_000]}\n\n"
                    f"Return ONLY a JSON object with these keys:\n{PERSON_SCHEMA_STR}"
                )
                try:
                    import json as _json
                    raw = chat(llm_client, extract_prompt, max_tokens=4096)
                    raw = raw.strip()
                    if raw.startswith("```json"): raw = raw[7:]
                    if raw.startswith("```"): raw = raw[3:]
                    if raw.endswith("```"): raw = raw[:-3]
                    result = _json.loads(raw.strip())
                    result.setdefault("profile_url", profile["url"])
                except Exception as e:
                    log.warning(f"    LLM extraction from profile page failed: {e}")

    # Step 3: Fallback to directed_crawl if LinkedIn scrape failed or was empty
    if not _has_useful_data(result):
        log.info(f"    LinkedIn scrape insufficient, falling back to directed crawl...")
        seed_queries = [
            f"{name} {company} LinkedIn",
            f"{name} {company} professional background",
        ]
        goal = (
            f"Research {name} who works at {company} (email: {email}). "
            f"Find their professional background, current role, recent activity, "
            f"achievements, and interests. Be specific and cite concrete details."
        )
        crawl_result = directed_crawl(
            llm_client,
            seed_queries=seed_queries,
            goal=goal,
            output_schema=PERSON_SCHEMA_STR,
            max_depth=2,
            max_pages=6,
        )
        # Merge crawl results into existing (LinkedIn scrape may have partial data)
        for k, v in crawl_result.items():
            if v and not result.get(k):
                result[k] = v
        if linkedin_url:
            result.setdefault("linkedin_url", linkedin_url)

    result.setdefault("name", name)
    result.setdefault("email", email)
    result.setdefault("company", company)
    return result


def _generate_talking_points(llm_client, data: dict) -> str:
    """Use LLM to generate talking points from research data."""
    name = data.get("name", "this person")
    company = data.get("company", "their company")
    role = data.get("role", "unknown role")
    linkedin_summary = data.get("linkedin_summary", "")
    recent_posts = data.get("recent_posts", "")
    achievements = data.get("achievements", "")
    interests = data.get("interests", "")

    prompt = (
        f"Based on the following research about {name} ({role} at {company}), "
        f"write a talking point paragraph that JP (a software engineering intern "
        f"interested in automation and side projects) could use in a cold email.\n\n"
        f"LinkedIn summary: {linkedin_summary}\n"
        f"Recent posts: {recent_posts}\n"
        f"Achievements: {achievements}\n"
        f"Interests: {interests}\n\n"
        f"The talking point MUST follow this exact structure:\n"
        f"\"I really [something about what they did] and [if they have posts, reference a specific post "
        f"and tie it to JP's interest in it]. [Show more enthusiasm about what you previously mentioned "
        f"in some way]. Your journey sounds amazing and is motivating me to find the time.\"\n\n"
        f"Be specific and reference concrete details from their activity. "
        f"If they have no posts, skip the post reference and focus on their role/achievements instead. "
        f"Return ONLY the talking point as a single short paragraph, no bullet points or headers."
    )

    try:
        return chat(llm_client, prompt, max_tokens=512)
    except Exception as e:
        log.warning(f"    LLM talking points failed: {e}")
        return ""


def main():
    parser = argparse.ArgumentParser(description="Research people from CSV contacts")
    parser.add_argument("csv_path", help="Path to recruiters CSV")
    parser.add_argument("--dry-run", action="store_true", help="List contacts without researching")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing research")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    setup_logging(args.verbose)
    llm_client = create_client()

    output_dir = config.OUTPUT_DIR / "person_research"
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = filter_not_emailed(read_csv(args.csv_path))
    if not rows:
        log.info("No contacts to research (all marked as emailed)")
        return

    # Deduplicate by email
    seen = {}
    for row in rows:
        email = row.get("Email", "").strip().lower()
        if email and email not in seen:
            seen[email] = row
    unique = list(seen.values())

    log.info(f"Found {len(unique)} unique contacts to research")

    if args.dry_run:
        for row in unique:
            name = f"{row.get('FirstName', '')} {row.get('LastName', '')}".strip()
            company = row.get("Company", "").strip()
            email = row.get("Email", "").strip()
            safe = filename_safe(email.replace("@", "_at_"))
            existing = (output_dir / f"{safe}.json").exists()
            log.info(f"  [DRY RUN] {name} ({email}) @ {company} | research={'✓' if existing else '✗'}")
        return

    def _research_one(row):
        name = f"{row.get('FirstName', '')} {row.get('LastName', '')}".strip()
        company = row.get("Company", "").strip()
        email = row.get("Email", "").strip()
        safe = filename_safe(email.replace("@", "_at_"))
        out_path = output_dir / f"{safe}.json"

        if out_path.exists() and not args.overwrite:
            log.info(f"  ⏭ {name} ({email}) — research exists (use --overwrite)")
            return

        try:
            log.info(f"  Researching: {name} ({email}) @ {company}")
            person_data = research_person(llm_client, name, company, email)

            if not _has_useful_data(person_data):
                log.info(f"  ⏭ {name} ({email}) — no useful data found, skipping")
                return

            log.info(f"    Generating talking points...")
            person_data["talking_points"] = _generate_talking_points(llm_client, person_data)

            out_path.write_text(json.dumps(person_data, indent=2), encoding="utf-8")
            log.info(f"  ✓ Saved {out_path.name}")
        except Exception as e:
            log.error(f"  ✗ Failed for {name} ({email}): {e}")

    for row in unique:
        _research_one(row)


if __name__ == "__main__":
    main()
