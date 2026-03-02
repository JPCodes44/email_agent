# Workflow 3: Email Template Generation (from CSV)

Reads `recruiters/list.csv`, reads the `Job Type` column, and generates one tailored `_TEMPLATE.txt` per company using the candidate profile that matches the job type. Run this after adding contacts to the CSV and filling in their job types.

**Entry point:** `generate_from_csv.py`

This is a **standalone workflow** — it does not re-scrape jobs or mine contacts. It only generates (or regenerates) email templates.

---

## When to Use

- You added new companies/contacts to `recruiters/list.csv` and want properly tailored templates
- You want to regenerate existing templates after editing a candidate profile
- The company generation workflow (Workflow 1) created templates with the wrong job-type profile

---

## Prerequisites

`recruiters/list.csv` must exist with at minimum these columns:

```
Email, Company, Level, Country, Emailed?, First name, Job Type
```

The `Job Type` column drives which candidate profile is used:

| CSV value | Profile used | Resume attached |
|-----------|-------------|-----------------|
| `Automation` | AI/automation experience (DiaMonTech agentic, KPI, Claude) | `Justin_Mak_s_Resume_Automation (2).pdf` |
| `Coding` | Software engineering (React/TS, C++, Jest/Playwright) | `Justin_Mak_s_Resume_Coding.pdf` |
| `Data Entry` | Data analyst/entry (Excel, Google Sheets, KPI, SQL) | `Justin_Mak_s_Resume_Data_Entry.pdf` |

If `Job Type` is blank or missing the column entirely, defaults to `automation`.

Accepted aliases (case-insensitive): `auto`, `software`, `code`, `entry`, `dataentry`, `data_entry`.

---

## How to Run

```bash
# Preview what would be generated (no files written)
python generate_from_csv.py recruiters/list.csv --dry-run

# Generate templates for companies not yet in output/emails/
python generate_from_csv.py recruiters/list.csv

# Use research from a specific batch (recommended after running main.py)
python generate_from_csv.py recruiters/list.csv --research-dir output/2026-02-09/research

# Overwrite / regenerate ALL templates (including existing ones)
python generate_from_csv.py recruiters/list.csv --overwrite

# Write templates to a specific subfolder
python generate_from_csv.py recruiters/list.csv --output-dir output/emails/batch_feb

# Verbose logging
python generate_from_csv.py recruiters/list.csv -v
```

---

## How It Works

```
Read CSV
  │  deduplicate by company name (first Job Type wins per company)
  ▼
In list.csv: check if Emailed? = no, and what job type it is.
  │
  ▼
For each company:
  │
  ├─ already has template? ──► SKIP  (unless --overwrite)
  │
  └─ generate:
       load research from output/research/<Company>.json (if exists)
       load Justins Experience with the matching resume based on company name eg: Justin_Mak_s_Resume_[Company_Name].pdf in /home/jp/agent/coop
       save output/emails/<Company>_TEMPLATE.txt
```


### Template Format

Every generated file follows this structure:
```
COMPANY: <name>
JOB TITLE: <title>
JOB URL: <url or N/A>

===== EMAIL TEMPLATE =====

SUBJECT: Hi [RECRUITER_FIRST_NAME], I found you through LinkedIn and wanted to reach out!

BODY:
Hi [RECRUITER_FIRST_NAME],

<2-3 sentences about what the company is doing>

<1 sentence connecting Justin's results (outcomes are what companies care about not process!) to the company you will find this in the resume with the respective company name eg. Justin_Mak_s_Resume_[Company_Name].pdf in /home/jp/agent/coop>

My resume is attached to this chat, and if there's any possibility of an internship fit for summer, I'd love to chat with you (or whoever the right person is) for 10–15 minutes.

Thanks,
Justin

===== INSTRUCTIONS =====
1. Find the recruiter's contact information (email and name)
2. Replace [RECRUITER_FIRST_NAME] in the subject and body with their first name
3. Review and personalize if needed
4. Send when ready!
```

---

## Outputs

| Path | Description |
|------|-------------|
| `output/emails/<Company>_TEMPLATE.txt` | Tailored template for that company |

---

## Relationship to Other Workflows

- **Workflow 1** (company generation) handles job discovery and company research only. It intentionally skips template generation. This workflow is the sole place templates are produced.
- **Workflow 3** (email sender) reads the `_TEMPLATE.txt` files produced here, replaces `[RECRUITER_FIRST_NAME]`, selects the matching resume, and sends.
