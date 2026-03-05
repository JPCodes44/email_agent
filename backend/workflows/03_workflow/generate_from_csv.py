#!/usr/bin/env python3
"""Workflow 3: Email Template Generation -generate tailored _TEMPLATE.txt per company."""

import sys, json, argparse, logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared import config
from shared.logging_setup import setup as setup_logging
from shared.csv_utils import read_csv, filter_not_emailed
from shared.company_utils import normalize, filename_safe
from shared.job_types import resolve as resolve_job_type
from shared.resume_utils import get_resume_path, extract_pdf_text

from shared.llm import create_client, chat

log = logging.getLogger("workflows")

TEMPLATE_FORMAT = """\
COMPANY: {company}
RECRUITER: {recruiter_name}
EMAIL: {recruiter_email}
JOB TITLE: {job_title}
JOB URL: {job_url}

===== EMAIL TEMPLATE =====

SUBJECT: {subject}

BODY:
{body}

===== INSTRUCTIONS =====
1. Review and personalize if needed
2. Send when ready!
"""


def load_research(company: str, research_dir: Path | None) -> dict | None:
    """Try to load research JSON for a company."""
    if not research_dir or not research_dir.is_dir():
        return None
    safe = filename_safe(company)
    path = research_dir / f"{safe}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    # Try case-insensitive match
    norm = normalize(company)
    for f in research_dir.glob("*.json"):
        if normalize(f.stem) == norm:
            return json.loads(f.read_text(encoding="utf-8"))
    return None


def load_person_research(email: str, person_research_dir: Path | None) -> dict | None:
    """Try to load person research JSON by email."""
    if not person_research_dir or not person_research_dir.is_dir():
        return None
    safe = filename_safe(email.replace("@", "_at_"))
    path = person_research_dir / f"{safe}.json"
    if path.exists():
        print(f"Found person research for {email} at {path}")
        return json.loads(path.read_text(encoding="utf-8"))
        
    return None


DEFAULT_PROMPT_INSTRUCTIONS = (
    "EMAIL STRUCTURE - follow this order exactly.\n\n"

    "\"Hi [Recruiter's first name],\n\n"

    "I really [word/phrase that represents engagement towards the recruiter] your "
    "[recent activity that the recruiter did (posts activities, recent job exp etc..)] about "
    "[action that they took]. [How their journey resonates with you personally]\n\n"

    "I’m a 3rd year Nanotechnology Engineering student with a minor in Combinotorics and Optimization "
    "at the University of Waterloo in the [resume subject] niche. Having worked in the industry for "
    "over 3 years, I figured that companies like yours often face [Challenges that the company faces "
    "or you can infer from the company research] challenges. The reason for this could be [Reason you "
    "infer based on the challenges the company faces]. Having worked with A in overcoming [What you "
    "did to resolve similar challenges to what the company is facing] challenges (get from resume), "
    "I feel that I could help you do the same\n\n"

    "Do you think we can set aside 10 mins for a quick feedback session? "
    "Feel free to say no. I understand people are busy.\n\n"

    "Thanks,\n\nJustin\"\n\n"
    
    "IMPORTANT RULES:\n"
    "- Fill every bracket with specific, researched content. Never leave brackets in the output.\n"
    "- Frame everything from the recipient’s perspective - they should benefit more than Justin.\n"
    "- If the context doesn’t support strong personalization in the opening, flag it rather than fabricating.\n"
    "- DO NOT open with ‘I hope you are doing well’ or any filler pleasantry.\n\n"
    "HARD RULE: Never use em dashes anywhere in the email. Use commas, periods, or hyphens instead."
)


def generate_template(client, company: str, job_type_str: str,
                      research: dict | None, resume_text: str,
                      person_research: dict | None = None,
                      recruiter_name: str = "",
                      recruiter_email: str = "",
                      instructions: str = DEFAULT_PROMPT_INSTRUCTIONS) -> dict:
    """Use Claude to generate an email template."""
    research_context = ""
    if research:
        research_context = (
            f"\nCompany research:\n"
            f"- Products/Services: {research.get('products_services', 'N/A')}\n"
            f"- Key Features: {research.get('key_features', 'N/A')}\n"
            f"- Recent News: {research.get('recent_news', 'N/A')}\n"
            f"- Summary: {research.get('summary_text', 'N/A')}\n"
        )

    person_context = ""
    if person_research:
        person_context = (
            f"\nPerson research on the recruiter:\n"
            f"- Role: {person_research.get('role', 'N/A')}\n"
            f"- Recent posts/activity: {person_research.get('recent_posts', 'N/A')}\n"
            f"- Achievements: {person_research.get('achievements', 'N/A')}\n"
            f"- Interests: {person_research.get('interests', 'N/A')}\n"
            f"- Talking points: {person_research.get('talking_points', 'N/A')}\n"
        )

    resume_context = ""
    if resume_text:
        resume_context = f"\nJustin's resume content:\n{resume_text[:4000]}\n"

    recruiter_line = f"to {recruiter_name} ({recruiter_email}) at {company}" if recruiter_name else f"to a recruiter at {company}"
    prompt = (
        f"Generate a cold outreach email template for {config.CANDIDATE_NAME} to send {recruiter_line}.\n"
        f"Job type: {job_type_str}\n"
        f"{research_context}"
        f"{person_context}"
        f"{resume_context}\n"
        f"The email should:\n"
        f"{instructions}\n\n"
        f"Return ONLY a JSON object with these keys:\n"
        f'- "subject": a short, curiosity-driven email subject line (under 8 words). '
        f'It should hint at specific value for {company} without being generic. '
        f'Good examples: "The designer you didn\'t know you needed", '
        f'"3 changes I\'d make to your data pipeline", '
        f'"thought you might find this useful". '
        f'Tailor it to the company\'s domain and the {job_type_str} role. '
        f'Do NOT mention "reaching out" or "LinkedIn".\n'
        f'- "body": the full email body\n'
        f'- "job_title": inferred job title or "N/A"\n'
    )

    text = chat(client, prompt, max_tokens=1024)
    try:
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # If JSON parsing failed, try to extract fields manually
    import re
    subject_match = re.search(r'"subject"\s*:\s*"([^"]*)"', text)
    body_match = re.search(r'"body"\s*:\s*"(.*?)"\s*[,}]', text, re.DOTALL)
    if subject_match and body_match:
        body = body_match.group(1).replace("\\n", "\n").replace('\\"', '"')
        return {
            "subject": subject_match.group(1),
            "body": body,
            "job_title": "N/A",
        }

    return {"subject": f"Hi [RECRUITER_FIRST_NAME], reaching out about {company}", "body": text, "job_title": "N/A"}


DEAI_PROMPT = (
    "You are an editor. Rewrite the email below to remove common AI writing patterns. "
    "Fix ALL of the following if present:\n"
    "- Remove em dashes. Replace with commas, periods, or short hyphens.\n"
    "- Break up repetitive sentence structures. Vary sentence length and rhythm. "
    "Do not use formulaic patterns of three (e.g. 'Fast. Simple. Effective.').\n"
    "- Remove superlative adjectives and unnecessary adverbs before nouns "
    "(e.g. 'your thoughtful strategy', 'clear messaging', 'truly impressive'). Just state the fact.\n"
    "- Remove overly formal or generic phrasing. Write like a real person, not a press release.\n"
    "- Remove surface-level personalization that sounds inserted by a template. "
    "If a personal reference doesn't feel genuine, cut it rather than keep it.\n"
    "- Remove excessive punctuation and exclamation marks.\n"
    "- Remove any opening line like 'I hope you are doing well', 'I hope this finds you well', "
    "'I hope you are having a great week', or any similar filler pleasantry. "
    "Get straight to the point instead.\n\n"
    "Keep the same structure (subject, body) and all factual content. "
    "Only change the tone and phrasing. Keep it under 150 words for the body.\n\n"
    "Return ONLY a JSON object with keys: \"subject\", \"body\", \"job_title\"\n\n"
    "Here is the draft to rewrite:\n"
)


def humanize_template(client, draft: dict) -> dict:
    """Second pass: rewrite the draft to remove AI-isms."""
    draft_text = f"Subject: {draft.get('subject', '')}\nBody: {draft.get('body', '')}"
    text = chat(client, DEAI_PROMPT + draft_text, max_tokens=1024)
    try:
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        result = json.loads(text.strip())
        # Preserve job_title from original draft
        result["job_title"] = draft.get("job_title", "N/A")
        return result
    except (json.JSONDecodeError, KeyError):
        # If parsing fails, return the original draft
        return strip_em_dashes(draft)
    return strip_em_dashes(result)


def strip_em_dashes(draft: dict) -> dict:
    """Third pass: hard replace any remaining em dashes."""
    for key in ("subject", "body"):
        if key in draft:
            draft[key] = draft[key].replace("\u2014", ", ").replace("\u2013", "-")
    return draft


REQUIRED_CLOSING = (
    "Do you think we can set aside 10 mins for a quick feedback session? "
    "Feel free to say no. I understand people are busy.\n\n"
    "Thanks,\nJustin Mak"
)


_CTA_PATTERNS = [
    "10-15 minute", "10–15 minute", "15 minute", "10 mins", "10 minutes",
    "quick chat", "quick call", "brief call", "brief chat",
    "happy to chat", "love to chat", "grab a call", "set aside",
    "feedback session", "would love to connect",
    "Thanks,", "Best,", "Cheers,", "Warm regards,", "Best regards,",
    "Sincerely,", "Kind regards,",
    "Justin Mak", "Justin",
]


def enforce_closing(draft: dict) -> dict:
    """Fourth pass: strip any AI-generated CTA/sign-off, then append the exact required closing."""
    body = draft.get("body", "")
    if not body:
        return draft

    # Split into lines and remove any that look like a duplicate CTA or sign-off
    lines = body.split("\n")
    cleaned = []
    for line in lines:
        lower = line.strip().lower()
        if any(pat.lower() in lower for pat in _CTA_PATTERNS):
            continue
        cleaned.append(line)

    # Remove trailing blank lines
    while cleaned and not cleaned[-1].strip():
        cleaned.pop()

    body = "\n".join(cleaned).rstrip() + "\n\n" + REQUIRED_CLOSING
    draft["body"] = body
    return draft


DEDUP_PROMPT = (
    "You are an editor. The email below may contain repeated or redundant text, "
    "especially near the closing. For example, there might be two calls-to-action "
    "(e.g. 'Worth a 10-minute call?' followed by 'Do you think we can set aside 10 mins...'), "
    "or a duplicate sign-off, or repeated sentences conveying the same idea.\n\n"
    "Your job:\n"
    "1. Remove ANY duplicate or redundant sentences/phrases that convey the same meaning.\n"
    "2. Keep the LAST/required closing intact: 'Do you think we can set aside 10 mins for a quick feedback session? "
    "Feel free to say no. I understand people are busy.\\n\\nThanks,\\nJustin Mak'\n"
    "3. Do NOT change any other content, tone, or wording.\n"
    "4. Do NOT add anything new.\n\n"
    "Return ONLY a JSON object with keys: \"subject\", \"body\", \"job_title\"\n\n"
    "Here is the email:\n"
)


def remove_duplicates(client, draft: dict) -> dict:
    """Post-processing pass: use LLM to detect and remove repeated/redundant text."""
    draft_text = (
        f"Subject: {draft.get('subject', '')}\n"
        f"Body: {draft.get('body', '')}\n"
        f"Job Title: {draft.get('job_title', 'N/A')}"
    )
    text = chat(client, DEDUP_PROMPT + draft_text, max_tokens=1024)
    try:
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        result = json.loads(text.strip())
        result["job_title"] = draft.get("job_title", "N/A")
        return result
    except (json.JSONDecodeError, KeyError):
        return draft


def main():
    parser = argparse.ArgumentParser(description="Generate email templates from CSV")
    parser.add_argument("csv_path", help="Path to recruiters CSV")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing files")
    parser.add_argument("--research-dir", type=Path, default=None, help="Path to research JSON directory")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing templates")
    parser.add_argument("--output-dir", type=Path, default=None, help="Output directory for templates")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    parser.add_argument("--prompt-instructions", type=str, default=DEFAULT_PROMPT_INSTRUCTIONS,
                        help="Custom instructions for email generation prompt")
    args = parser.parse_args()

    setup_logging(args.verbose)

    output_dir = args.output_dir or config.OUTPUT_DIR / "emails"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Find latest research dir if not specified
    research_dir = args.research_dir
    if not research_dir:
        # Try to find most recent research output
        if config.OUTPUT_DIR.exists():
            batches = sorted([d for d in config.OUTPUT_DIR.iterdir() if (d / "research").is_dir()])
            if batches:
                research_dir = batches[-1] / "research"
                log.info(f"Using research from: {research_dir}")

    # Auto-detect person research directory
    person_research_dir = config.OUTPUT_DIR / "person_research"
    if person_research_dir.is_dir():
        log.info(f"Using person research from: {person_research_dir}")
    else:
        person_research_dir = None

    rows = filter_not_emailed(read_csv(args.csv_path))
    if not rows:
        log.info("No contacts to process (all marked as emailed)")
        return

    log.info(f"Processing {len(rows)} recruiters")

    if args.dry_run:
        for row in rows:
            company = row.get("Company", "").strip()
            email = row.get("Email", "").strip()
            recruiter_name = row.get("FirstName", "").strip()
            job_type = resolve_job_type(row.get("Job Type", ""))
            resume = get_resume_path(company, job_type)
            research = load_research(company, research_dir)
            person = load_person_research(email, person_research_dir)
            log.info(
                f"  [DRY RUN] {company} | {recruiter_name} <{email}> | type={job_type.value} | "
                f"resume={'✓' if resume else '✗'} | research={'✓' if research else '✗'} | "
                f"person={'✓' if person else '✗'}"
            )
        return

    client = create_client()

    for row in rows:
        company = row.get("Company", "").strip()
        email = row.get("Email", "").strip()
        recruiter_name = row.get("FirstName", "").strip()
        safe_name = filename_safe(company)
        safe_email = filename_safe(email)
        out_path = output_dir / f"{safe_name}_TEMPLATE_{safe_email}.txt"

        if out_path.exists() and not args.overwrite:
            log.info(f"  ⏭ {company} ({email}) - template exists (use --overwrite)")
            continue

        try:
            job_type = resolve_job_type(row.get("Job Type", ""))
            research = load_research(company, research_dir)
            person = load_person_research(email, person_research_dir)
            resume_path = get_resume_path(company, job_type)
            resume_text = extract_pdf_text(resume_path) if resume_path else ""

            log.info(f"  Generating template for: {company} / {recruiter_name} <{email}> (type={job_type.value})")
            result = generate_template(client, company, job_type.value, research, resume_text,
                                       person_research=person,
                                       recruiter_name=recruiter_name,
                                       recruiter_email=email,
                                       instructions=args.prompt_instructions)

            log.info(f"  Humanizing template for: {company} / {recruiter_name}")
            result = humanize_template(client, result)
            result = enforce_closing(result)

            log.info(f"  Dedup check for: {company} / {recruiter_name}")
            result = remove_duplicates(client, result)

            content = TEMPLATE_FORMAT.format(
                company=company,
                recruiter_name=recruiter_name,
                recruiter_email=email,
                job_title=result.get("job_title", "N/A"),
                job_url=result.get("job_url", "N/A"),
                subject=result.get("subject", ""),
                body=result.get("body", ""),
            )
            out_path.write_text(content, encoding="utf-8")
            log.info(f"  ✓ Saved {out_path.name}")
        except Exception as e:
            log.error(f"  ✗ Failed for {company} ({email}): {e}")


if __name__ == "__main__":
    main()
