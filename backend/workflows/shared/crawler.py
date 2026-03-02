"""Directed crawler: LLM-guided web research using fetch + LLM."""

import json, logging, re, requests, time, threading, uuid
from bs4 import BeautifulSoup
from ddgs import DDGS
from openai import OpenAI
import websocket

log = logging.getLogger("workflows")

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": _UA})




# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _clean_html(html: str) -> str:
    """Parse HTML and return cleaned text."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "noscript", "svg", "img"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:10_000]


def _fetch_with_requests(url: str, timeout: int = 15) -> str:
    """Fetch a URL with requests (fast, for non-JS sites). No proxy — direct only."""
    try:
        resp = _SESSION.get(url, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        return _clean_html(resp.text)
    except Exception as e:
        log.warning(f"    Failed to fetch {url}: {e}")
    return ""



def find_linkedin_url(email: str) -> str | None:
    """Search DuckDuckGo for a person's LinkedIn profile URL by email."""
    query = f"site:linkedin.com/in {email}"
    log.info(f"    Searching LinkedIn URL: {query}")
    results = search_web(query, num_results=5)
    for r in results:
        url = r.get("url", "")
        if "linkedin.com/in/" in url:
            log.info(f"    Found LinkedIn URL: {url}")
            return url
    log.info(f"    No LinkedIn URL found for {email}")
    return None


# ---------------------------------------------------------------------------
# OpenClaw browser automation helpers
# ---------------------------------------------------------------------------

# Single browser tab — serialize all OpenClaw multi-step sequences
_openclaw_lock = threading.Lock()

def _openclaw_invoke(action: str, args: dict, timeout: int = 30) -> dict:
    """POST to OpenClaw /tools/invoke and return the JSON response.

    Returns {} on any failure (network, auth, browser not running, etc).
    """
    from shared import config

    if not config.OPENCLAW_URL or not config.OPENCLAW_TOKEN:
        log.warning("    OPENCLAW_URL / OPENCLAW_TOKEN not set in .env")
        return {}

    url = f"{config.OPENCLAW_URL}/tools/invoke"
    headers = {
        "Authorization": f"Bearer {config.OPENCLAW_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "tool": "browser",
        "action": action,
        "args": {**args, "profile": "chrome"},
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log.warning(f"    OpenClaw {action} failed: {e}")
        return {}


def _openclaw_navigate(target_url: str) -> dict:
    """Navigate OpenClaw browser to a URL."""
    log.info(f"    OpenClaw navigate → {target_url}")
    return _openclaw_invoke("navigate", {"targetUrl": target_url}, timeout=45)


def _openclaw_snapshot() -> str:
    """Take an AI-readable text snapshot of the current page. Returns page text or ''."""
    resp = _openclaw_invoke("snapshot", {}, timeout=30)
    if not resp:
        return ""

    # Response structure: {"ok": true, "result": {"content": [{"type": "text", "text": "..."}]}}
    # Navigate to the innermost content, handling multiple nesting levels
    obj = resp
    # Unwrap .result if present
    if isinstance(obj.get("result"), dict):
        obj = obj["result"]

    # Extract text from MCP-style content blocks
    if isinstance(obj.get("content"), list):
        parts = []
        for block in obj["content"]:
            if isinstance(block, dict) and block.get("text"):
                parts.append(block["text"])
        if parts:
            return "\n".join(parts)

    # Fallback: check for direct string fields
    for key in ("content", "text", "snapshot"):
        if key in obj and isinstance(obj[key], str):
            return obj[key]

    return ""


def _clean_linkedin_snapshot(snap: str) -> str:
    """Strip LinkedIn navigation chrome from a snapshot, keeping only page content.

    LinkedIn snapshots have ~3-5k chars of nav/header before the actual content.
    The main content typically starts after 'main' region or 'Experience' heading.
    """
    # Try to find the main content region
    for marker in ['region "main"', 'main [ref=', 'heading "Experience"',
                    'heading "About"', 'heading "Activity"']:
        idx = snap.find(marker)
        if idx > 0:
            return snap[idx:]
    # Fallback: skip first 4000 chars (nav chrome is typically ~3-5k)
    if len(snap) > 6000:
        return snap[4000:]
    return snap


def _openclaw_click(ref: str) -> dict:
    """Click an element by its ref number in the OpenClaw browser."""
    log.info(f"    OpenClaw click → ref={ref}")
    return _openclaw_invoke("click", {"ref": ref})


def _openclaw_agent(message: str, timeout: int = 180) -> str:
    """Send a high-level task to the OpenClaw agent and return its text response.

    Uses the WebSocket RPC gateway. The agent has its own LLM (qwen2.5:7b)
    and full browser control — no tokens burned on our side.
    Returns '' on any failure.
    """
    from shared import config

    if not config.OPENCLAW_URL or not config.OPENCLAW_TOKEN:
        log.warning("    OPENCLAW_URL / OPENCLAW_TOKEN not set in .env")
        return ""

    # Convert http URL to ws URL
    ws_url = config.OPENCLAW_URL.replace("http://", "ws://").replace("https://", "wss://")

    try:
        ws = websocket.create_connection(ws_url, timeout=15)
    except Exception as e:
        log.warning(f"    OpenClaw WebSocket connect failed: {e}")
        return ""

    try:
        # Step 1: Ignore challenge
        ws.recv()

        # Step 2: Authenticate
        req_id = str(uuid.uuid4())
        ws.send(json.dumps({
            "type": "req", "id": req_id, "method": "connect",
            "params": {
                "minProtocol": 3, "maxProtocol": 3,
                "client": {"id": "cli", "version": "1.0.0", "platform": "linux", "mode": "backend"},
                "role": "operator",
                "auth": {"token": config.OPENCLAW_TOKEN}
            }
        }))

        # Read until connect response (skip health events)
        ws.settimeout(10)
        connected = False
        for _ in range(10):
            frame = json.loads(ws.recv())
            if frame.get("type") == "res" and frame.get("id") == req_id:
                if not frame.get("ok"):
                    log.warning(f"    OpenClaw connect rejected: {frame}")
                    return ""
                connected = True
                break
        if not connected:
            log.warning("    OpenClaw connect: no response")
            return ""

        # Step 3: Send agent task
        agent_req_id = str(uuid.uuid4())
        ws.send(json.dumps({
            "type": "req", "id": agent_req_id, "method": "agent",
            "params": {
                "message": message,
                "idempotencyKey": str(uuid.uuid4()),
                "sessionKey": "main"
            }
        }))
        log.info(f"    OpenClaw agent task sent: {message[:80]}...")

        # Step 4: Collect text responses until done
        ws.settimeout(30)  # per-frame timeout (not total)
        text_parts = []
        idle_count = 0
        for frame_num in range(500):
            try:
                raw = ws.recv()
                if not raw:
                    continue
                frame = json.loads(raw)
            except websocket.WebSocketTimeoutException:
                idle_count += 1
                if idle_count >= 3:
                    log.warning(f"    OpenClaw agent: no activity for 90s, giving up")
                    break
                log.info(f"    OpenClaw agent: waiting... ({idle_count * 30}s)")
                continue
            except (json.JSONDecodeError, Exception):
                continue

            idle_count = 0  # reset on any valid frame
            evt = frame.get("event", "")
            ftype = frame.get("type", "")

            # Skip noise
            if evt in ("health", "tick"):
                continue

            # Agent events
            if evt == "agent":
                payload = frame.get("payload", {})
                stream = payload.get("stream", "")
                data = payload.get("data", "")

                if stream == "text" and isinstance(data, str):
                    text_parts.append(data)
                elif stream == "lifecycle":
                    phase = data.get("phase", "") if isinstance(data, dict) else ""
                    log.info(f"    OpenClaw agent lifecycle: {phase}")
                    if phase == "done":
                        break
                elif stream == "tool_use":
                    tool_name = data.get("name", "") if isinstance(data, dict) else ""
                    log.info(f"    OpenClaw agent using tool: {tool_name}")
                elif stream == "tool_result":
                    log.info(f"    OpenClaw agent got tool result")
                else:
                    log.info(f"    OpenClaw agent/{stream}")
                continue

            # Response frame
            if ftype == "res" and frame.get("id") == agent_req_id:
                status = frame.get("payload", {}).get("status", "")
                if status == "error":
                    err = frame.get("payload", {}).get("error", "unknown")
                    log.warning(f"    OpenClaw agent error: {err}")
                    break
                continue

            # Log unexpected events for debugging
            if evt and evt not in ("health", "tick"):
                log.info(f"    OpenClaw event: {evt}")

        result = "".join(text_parts).strip()
        log.info(f"    OpenClaw agent response: {len(result)} chars")
        return result

    except Exception as e:
        log.warning(f"    OpenClaw agent failed: {e}")
        return ""
    finally:
        try:
            ws.close()
        except Exception:
            pass


def find_profile_via_openclaw(email: str, name: str, company: str) -> dict | None:
    """Google the email via OpenClaw browser, use our LLM to pick the best profile URL.

    Returns {"url": "...", "type": "linkedin"|"other"} or None.
    """
    from shared.llm import create_client, chat
    from urllib.parse import quote_plus

    query = quote_plus(email)
    search_url = f"https://www.google.com/search?q={query}"

    # Lock the browser for navigate→snapshot sequence
    with _openclaw_lock:
        nav = _openclaw_navigate(search_url)
        if not nav:
            log.warning("    OpenClaw Google navigate failed")
            return None

        time.sleep(2)

        snap = _openclaw_snapshot()
        if not snap:
            log.warning("    OpenClaw Google snapshot empty")
            return None

    log.info(f"    Google snapshot: {len(snap)} chars")

    # Extract profile URLs with regex first (zero tokens)
    # LinkedIn profiles
    linkedin_urls = re.findall(r"https?://[^\s\"'<>]*linkedin\.com/in/[^\s\"'<>]+", snap)
    # Personal/profile sites (twitter, github, personal domains)
    profile_patterns = [
        r"https?://[^\s\"'<>]*twitter\.com/[^\s\"'<>]+",
        r"https?://[^\s\"'<>]*x\.com/[^\s\"'<>]+",
        r"https?://[^\s\"'<>]*github\.com/[^\s\"'<>]+",
    ]
    other_urls = []
    for pat in profile_patterns:
        other_urls.extend(re.findall(pat, snap))

    # Deduplicate
    seen = set()
    unique_linkedin = []
    for u in linkedin_urls:
        clean = u.rstrip("/.,;)")
        if clean not in seen:
            seen.add(clean)
            unique_linkedin.append(clean)

    unique_other = []
    for u in other_urls:
        clean = u.rstrip("/.,;)")
        if clean not in seen:
            seen.add(clean)
            unique_other.append(clean)

    # If exactly one LinkedIn URL, use it directly (no LLM needed)
    if len(unique_linkedin) == 1:
        url = unique_linkedin[0]
        log.info(f"    Single LinkedIn URL found (no LLM needed): {url}")
        return {"url": url, "type": "linkedin"}

    # If multiple LinkedIn URLs, use LLM to pick (but only send the URLs, not the full snapshot)
    if len(unique_linkedin) > 1:
        from shared.llm import create_client, chat
        llm_client = create_client()
        url_list = "\n".join(f"  {i+1}. {u}" for i, u in enumerate(unique_linkedin))
        prompt = (
            f"Which LinkedIn URL best matches '{name}' at '{company}' (email: {email})?\n\n"
            f"{url_list}\n\n"
            f"Return ONLY the number, or 'none'."
        )
        try:
            answer = chat(llm_client, prompt, max_tokens=16).strip()
            if "none" not in answer.lower():
                num_match = re.search(r"\d+", answer)
                if num_match:
                    idx = int(num_match.group(0)) - 1
                    if 0 <= idx < len(unique_linkedin):
                        log.info(f"    LLM picked LinkedIn URL: {unique_linkedin[idx]}")
                        return {"url": unique_linkedin[idx], "type": "linkedin"}
        except Exception as e:
            log.warning(f"    LLM pick failed: {e}")
        # Fallback to first
        log.info(f"    Defaulting to first LinkedIn URL: {unique_linkedin[0]}")
        return {"url": unique_linkedin[0], "type": "linkedin"}

    # No LinkedIn — use first other profile URL if any
    if unique_other:
        url = unique_other[0]
        log.info(f"    No LinkedIn, using other profile: {url}")
        return {"url": url, "type": "other"}

    # Nothing found via regex
    log.info(f"    No profile URLs found in Google results for {email}")
    return None


def scrape_linkedin_profile(
    client: OpenAI,
    linkedin_url: str,
    output_schema: str,
    max_depth: int = 3,
    max_pages: int = 6,
) -> dict:
    """Scrape a LinkedIn profile using OpenClaw browser + our LLM.

    1. Navigate to profile → snapshot → LLM extracts data
    2. Navigate to /details/experience/ → snapshot → LLM extracts experience
    3. Navigate to /recent-activity/all/ → snapshot → LLM extracts activity
    4. Merge everything

    Falls back gracefully: returns {} if OpenClaw is unreachable.
    """
    from shared.llm import create_client, chat

    log.info(f"    LinkedIn scrape via OpenClaw: {linkedin_url}")

    with _openclaw_lock:
        # --- Step 1: Profile page (contains everything — profile, experience, activity) ---
        nav_result = _openclaw_navigate(linkedin_url)
        if not nav_result:
            log.warning("    OpenClaw navigation failed — falling back")
            return {}

        time.sleep(3)
        profile_text = _openclaw_snapshot()
        if not profile_text:
            log.warning("    OpenClaw snapshot returned empty — falling back")
            return {}
        log.info(f"    Profile snapshot: {len(profile_text)} chars")

        # --- Step 2: Activity page (separate page for recent posts) ---
        base_url = linkedin_url.rstrip("/")
        _openclaw_navigate(f"{base_url}/recent-activity/all/")
        time.sleep(3)
        activity_text = _openclaw_snapshot()
        if activity_text:
            log.info(f"    Activity snapshot: {len(activity_text)} chars")

    # --- LLM extraction (outside lock — doesn't need browser) ---
    llm_client = create_client()
    profile_data = {}

    # The main profile page is huge (~80k chars). Split into sections.
    clean_profile = _clean_linkedin_snapshot(profile_text)

    # Extract profile basics from first portion (header, about, headline)
    profile_prompt = (
        f"Extract structured data from this LinkedIn profile page.\n\n"
        f"Page content:\n{clean_profile[:15_000]}\n\n"
        f"Extract: full name, headline, current role/title, company, location, "
        f"about/summary, achievements. Be specific, cite actual text.\n"
        f"Do NOT make anything up. If not found, use empty string.\n\n"
        f"Return ONLY a JSON object with these keys:\n{output_schema}"
    )
    try:
        profile_data = _parse_json(chat(llm_client, profile_prompt, max_tokens=4096))
        log.info("    Profile data extracted")
    except Exception as e:
        log.warning(f"    Profile extraction failed: {e}")

    # Extract experience from the experience section of the same snapshot
    # Find where the Experience section starts
    exp_start = clean_profile.find('heading "Experience"')
    if exp_start < 0:
        exp_start = clean_profile.find("Experience")
    if exp_start > 0:
        exp_section = clean_profile[exp_start:exp_start + 15_000]
        exp_prompt = (
            f"Extract work experience from this LinkedIn profile section.\n\n"
            f"Content:\n{exp_section}\n\n"
            f"Extract ALL previous and current roles: company name, job title, dates, duration.\n"
            f"Be specific, cite actual text. Do NOT make anything up.\n\n"
            f'Return JSON: {{"previous_experience": "all roles with company, title, dates", "role": "current/most recent title"}}'
        )
        try:
            exp_data = _parse_json(chat(llm_client, exp_prompt, max_tokens=3000))
            if exp_data.get("previous_experience"):
                profile_data["previous_experience"] = exp_data["previous_experience"]
            if exp_data.get("role") and not profile_data.get("role"):
                profile_data["role"] = exp_data["role"]
            log.info("    Experience data extracted")
        except Exception as e:
            log.warning(f"    Experience extraction failed: {e}")
    else:
        log.info("    No Experience section found in profile snapshot")

    # Extract from activity page
    if activity_text and len(activity_text) > 100:
        clean_activity = _clean_linkedin_snapshot(activity_text)
        activity_prompt = (
            f"Extract recent LinkedIn activity from this page.\n\n"
            f"Page content:\n{clean_activity[:12_000]}\n\n"
            f"Extract: recent posts content, topics they post about, professional interests.\n"
            f"Be specific, cite actual post content. Do NOT make anything up.\n\n"
            f'Return JSON: {{"recent_posts": "post summaries", "interests": "professional interests"}}'
        )
        try:
            activity_data = _parse_json(chat(llm_client, activity_prompt, max_tokens=3000))
            if activity_data.get("recent_posts"):
                profile_data["recent_posts"] = activity_data["recent_posts"]
            if activity_data.get("interests"):
                existing = profile_data.get("interests", "")
                if existing:
                    profile_data["interests"] = f"{existing}; {activity_data['interests']}"
                else:
                    profile_data["interests"] = activity_data["interests"]
            log.info("    Activity data extracted")
        except Exception as e:
            log.warning(f"    Activity extraction failed: {e}")

    if not profile_data:
        log.warning("    No data extracted from LinkedIn")
        return {}

    log.info(f"    LinkedIn scrape complete — {len(profile_data)} fields")
    return profile_data


def fetch_page(url: str, timeout: int = 15) -> str:
    """Fetch a URL — skips LinkedIn (requires auth), uses requests for everything else."""
    if "linkedin.com" in url:
        log.info(f"    Skipping LinkedIn URL (no active session): {url}")
        return ""
    return _fetch_with_requests(url, timeout)


def search_web(query: str, num_results: int = 10) -> list[dict]:
    """Search DuckDuckGo via the ddgs library and return [{url, title, snippet}, ...].
    No proxy — DuckDuckGo doesn't need one and the proxy causes 612 errors."""
    try:
        raw = DDGS().text(query, max_results=num_results)
        return [
            {"url": r["href"], "title": r["title"], "snippet": r["body"]}
            for r in raw
        ]
    except Exception as e:
        log.warning(f"    Search failed for '{query}': {e}")
    return []


def _ask_llm(client: OpenAI, prompt: str, max_tokens: int = 2048) -> str:
    from shared.llm import chat
    return chat(client, prompt, max_tokens)


def _parse_json(text: str):
    """Extract JSON from a Claude response that may have markdown fences."""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return json.loads(text.strip())


# ---------------------------------------------------------------------------
# Main directed crawl
# ---------------------------------------------------------------------------

def directed_crawl(
    client: OpenAI,
    seed_queries: list[str],
    goal: str,
    output_schema: str,
    max_depth: int = 2,
    max_pages: int = 8,
) -> dict:
    """
    LLM-guided directed crawl.

    1. Run seed queries on DuckDuckGo
    2. Claude picks the most relevant URLs
    3. Fetch each page → Claude extracts info + suggests deeper links
    4. Repeat for max_depth rounds
    5. Claude synthesizes everything into output_schema JSON
    """
    visited: set[str] = set()
    extractions: list[str] = []

    # ── Step 1: search ────────────────────────────────────────────────────
    search_results: list[dict] = []
    for i, query in enumerate(seed_queries):
        if i > 0:
            time.sleep(3)  # avoid rate limits between queries
        log.info(f"    Searching: {query}")
        results = search_web(query)
        log.info(f"    Got {len(results)} results")
        search_results.extend(results)

    if not search_results:
        log.warning("    No search results found")
        return {}

    # ── Step 2: Claude picks URLs ─────────────────────────────────────────
    listing = "\n".join(
        f"{i+1}. [{r['title']}]({r['url']})\n   {r['snippet']}"
        for i, r in enumerate(search_results)
    )
    pick_text = _ask_llm(
        client,
        f"GOAL: {goal}\n\n"
        f"Search results:\n{listing}\n\n"
        f"Pick up to {max_pages} URLs most likely to contain useful information. "
        f"Return ONLY a JSON array of URL strings ordered by relevance.",
        max_tokens=1024,
    )
    try:
        urls_to_visit = _parse_json(pick_text)
    except json.JSONDecodeError:
        urls_to_visit = re.findall(r"https?://[^\s\"'\\]+", pick_text)
    urls_to_visit = urls_to_visit[:max_pages]
    log.info(f"    Claude selected {len(urls_to_visit)} URLs")

    # ── Step 3: fetch → extract → deepen ──────────────────────────────────
    for depth in range(max_depth):
        next_urls: list[str] = []

        for url in urls_to_visit:
            if url in visited or len(visited) >= max_pages:
                continue
            visited.add(url)

            log.info(f"    [{depth+1}/{max_depth}] Fetching: {url}")
            page_text = fetch_page(url)
            if not page_text:
                continue

            extract_text = _ask_llm(
                client,
                f"GOAL: {goal}\n\n"
                f"Page content from {url}:\n{page_text[:8000]}\n\n"
                f"1. Extract any information relevant to the goal. "
                f"Be specific — cite names, dates, numbers, details.\n"
                f"2. If you see links on this page that would contain MORE useful "
                f"information, list them.\n\n"
                f"Return JSON:\n"
                f'{{"extracted": "relevant info here", "follow_urls": ["url1", ...]}}',
            )

            try:
                parsed = _parse_json(extract_text)
                if parsed.get("extracted"):
                    extractions.append(f"From {url}:\n{parsed['extracted']}")
                if depth < max_depth - 1:
                    for follow in parsed.get("follow_urls", [])[:3]:
                        if follow.startswith("http") and follow not in visited:
                            next_urls.append(follow)
            except json.JSONDecodeError:
                extractions.append(f"From {url}:\n{extract_text}")

        urls_to_visit = next_urls
        if not urls_to_visit:
            break

    if not extractions:
        log.warning("    No useful information extracted")
        return {}

    # ── Step 4: synthesize ────────────────────────────────────────────────
    combined = "\n\n---\n\n".join(extractions)
    final_text = _ask_llm(
        client,
        f"GOAL: {goal}\n\n"
        f"Here is all the information gathered from web research:\n\n"
        f"{combined[:15000]}\n\n"
        f"Synthesize this into a JSON object. Be specific — cite concrete details, "
        f"names, dates, and facts. Do NOT make anything up.\n\n"
        f"Return ONLY a JSON object with these keys:\n{output_schema}",
        max_tokens=4096,
    )

    try:
        return _parse_json(final_text)
    except json.JSONDecodeError:
        log.warning("    Could not parse final synthesis JSON")
        return {"_raw": final_text}
