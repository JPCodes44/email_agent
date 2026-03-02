## Workflow Orchestration

### 1. Plan Node Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately – don't keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent Strategy
- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One task per subagent for focused execution

### 3. Self-Improvement Loop
- After ANY correction from the user: update `tasks/lessons.md` with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review lessons at session start for relevant project

### 4. Verification Before Done
- Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

### 5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes – don't over-engineer
- Challenge your own work before presenting it

### 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests – then resolve them
- Zero context switching required from the user
- Go fix failing CI tests without being told how

## Task Management

1. **Plan First**: Write plan to `tasks/todo.md` with checkable items
2. **Verify Plan**: Check in before starting implementation
3. **Track Progress**: Mark items complete as you go
4. **Explain Changes**: High-level summary at each step
5. **Document Results**: Add review section to `tasks/todo.md`
6. **Capture Lessons**: Update `tasks/lessons.md` after corrections

## Core Principles

- **Simplicity First**: Make every change as simple as possible. Impact minimal code.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- **Minimal Impact**: Changes should only touch what's necessary. Avoid introducing bugs.

## Architecture Decisions

### LLM Providers
- **Primary LLM**: Groq (`llama-3.3-70b-versatile`) via OpenAI-compatible API — configured in `.env` as `LLM_MODEL`, `LLM_BASE_URL`, `LLM_API_KEY`
- **Ollama cloud** (`qwen3-coder-next:cloud`): weekly rate limit hit, not currently usable
- **Gemini free tier**: quota exhausted, not currently usable
- **Anthropic**: credit balance too low, not currently usable
- **Perplexity** (`sonar-pro`): used for company research (workflow 01) — good for web search + synthesis in one call
- All providers use OpenAI-compatible API via `shared/llm.py`

### Workflow 01 (Company Research)
- Uses **Perplexity** — single deep research prompt per company
- No web scraping needed, Perplexity handles search internally
- Runs companies in parallel (3 workers)

### Workflow 02 (Person Research)
- Uses **DuckDuckGo** email search → **Playwright + SmartProxy** LinkedIn scrape → **Groq LLM** extraction
- Fallback: `directed_crawl` (DuckDuckGo + requests + LLM synthesis)
- **Known issues**: proxy tunnel failures, wrong person matches from email search, captcha/authwall blocking
- **Considering**: OpenClaw for autonomous browser-based LinkedIn navigation (handles captcha, clicks, scrolls like a real user)

### Proxy Setup
- SmartProxy rotating residential proxy in `.env` as `PROXY_URL`
- Rotating proxies = same URL, different IP per TCP connection
- Only used for LinkedIn Playwright scraping — DuckDuckGo and regular web fetches go direct (proxy causes 612 errors on non-LinkedIn sites)

### LinkedIn Scraping
- Perplexity does NOT pull LinkedIn data well — need actual browser navigation
- Anonymous proxy scraping hits authwalls and captchas
- Logged-in session scraping exists (`ensure_linkedin_session`) but not currently wired to `scrape_linkedin_profile`
- Fresh temp dir per Playwright context = new proxy IP each time

### Frontend
- Background process killer: fixed to verify PIDs are alive via `process.kill(pid, 0)` before reporting
- Kill endpoint no longer removes from `runningProcs` immediately — waits for process to actually die

### Python Environment
- Project uses a venv at `/home/jp/email_agent/.venv/`
- Install packages with `/home/jp/email_agent/.venv/bin/pip3 install`
- crawl4ai 0.8.0 is installed but not currently used

## Lessons (mistakes to never repeat)

- **Always verify model names exist before using them**: Run `ollama list` (or equivalent) to check available models. Don't assume model names — `qwen3.5:cloud` vs `qwen3-coder-next:cloud` caused a 404.
- **Test API connectivity immediately after swapping providers**: Don't let the user discover failures. Run a quick smoke test (`chat("say hello")`) before declaring done.
- **Check stale sessions before blaming code**: LinkedIn Playwright session was expired, not a code bug. When crawled data comes back empty, check auth/session state first.
- **Free tier APIs have aggressive rate limits**: 25 companies × 5+ LLM calls each will blow through free tier quotas fast. Warn the user about rate limits when using free tiers with high-volume workflows.
- **Don't use proxy for non-LinkedIn fetches**: SmartProxy causes 612 tunnel errors on many sites. DuckDuckGo and regular web fetches work fine direct.
- **JSON schema format matters**: Passing `{"type": "string", "description": "..."}` as output schema causes LLMs to mimic the schema structure instead of returning plain values. Use plain text descriptions instead.
- **Install into the correct Python environment**: The project uses a venv — `pip install` goes to the wrong place. Always use `/home/jp/email_agent/.venv/bin/pip3`.
- **Check all free tier quotas before switching providers**: Ollama cloud, Gemini, and Anthropic all hit limits in the same session. Have a fallback ready (Groq worked).
