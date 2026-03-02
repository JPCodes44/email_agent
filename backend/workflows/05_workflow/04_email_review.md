# Workflow 4: Email Review

Cross-checks every company's email template against its tailored resume and flags problems before sending. Runs both programmatic PDF checks and a Claude quality review.

**Entry point:** `review_emails.py`

---

## When to Use

- After Workflow 2 (resume tailoring) and Workflow 3 (email template generation)
- Before Workflow 4 (drafts) or Workflow 6 (sending)
- Re-run after regenerating resumes or templates to catch regressions

---

## Checks Performed

| Check                                          | How                                                         |
| ---------------------------------------------- | ----------------------------------------------------------- |
| Resume file exists in `coop/`                  | Filename match                                              |
| Resume is exactly 1 page                       | `pdfplumber` page count                                     |
| No text clipped at right/bottom margin         | `pymupdf` bounding-box vs page dimensions                   |
| `[RECRUITER_FIRST_NAME]` placeholder intact    | String search in template file                              |
| Email body has a concrete **outcome** sentence | Claude (haiku) — checks for metric/result, not just process |
| Resume text supports the email claim           | Claude cross-references extracted resume text               |
| No inconsistency between email and resume      | Claude flags mismatches                                     |

**Outcome vs Process:**

- ✓ Outcome: _"cut report consolidation from 4 hours to 15 minutes"_ — concrete result
- ✗ Process: _"built automation workflows"_ — describes activity, not impact

---

## How to Run

```bash
# Review all Emailed?=No companies
python review_emails.py

# Review a single company
python review_emails.py --company "BMO"

# Use a specific templates directory
python review_emails.py --emails-dir output/emails/my_batch

# Save a markdown report
python review_emails.py --output output/review.md

# Verbose logging
python review_emails.py -v
```

---

## Pipeline

```
recruiters/list.csv (Emailed? = blank)
         │
         ▼
  For each unique company:
    │
    ├─ Find output/emails/<Company>_TEMPLATE.txt
    ├─ Find coop/Justin_Mak_s_Resume_<Company>.pdf
    │
    ├─ Programmatic checks:
    │    • pdfplumber: page count == 1?
    │    • pymupdf: any text block beyond right/bottom margin?
    │    • string check: [RECRUITER_FIRST_NAME] still in template?
    │
    └─ Claude (haiku) quality check:
         • Is there a sentence with a concrete outcome (not just process)?
         • Does the resume text support that outcome claim?
         • Any inconsistency between email and resume?
         │
         ▼
  Rich table printed to terminal
  Optional: --output report.md
```

---

## Output Columns

| Column  | Meaning                                                 |
| ------- | ------------------------------------------------------- |
| Resume  | Company-specific PDF found in `coop/`                   |
| Pages   | Page count (must be 1)                                  |
| Clip?   | ✓ = no clipping detected                                |
| [FIRST] | `[RECRUITER_FIRST_NAME]` placeholder is still present   |
| Outcome | Email has a concrete result sentence (not just process) |
| Aligns  | Resume text supports the email's claim                  |
| Notes   | Specific issues flagged for that company                |

---

## What to Fix

| Issue                        | Fix                                                                                             |
| ---------------------------- | ----------------------------------------------------------------------------------------------- |
| Resume missing               | Run `python tailor_resume.py --company "<Name>"`                                                |
| Resume > 1 page              | Regenerate with `--overwrite`, check LaTeX for spacing issues                                   |
| Text clipped                 | Regenerate resume; check `outreach/resume/latex_builder.py` margins                             |
| No outcome sentence          | Regenerate template with `--overwrite`; or edit `output/emails/<Company>_TEMPLATE.txt` manually |
| Resume doesn't support claim | Regenerate resume with `--overwrite`; or edit template to match actual resume content           |
