"""PhantomBuster API client for LinkedIn profile scraping."""

import logging
import time

import requests

log = logging.getLogger("workflows")

_BASE_URL = "https://api.phantombuster.com/api/v2"


def _headers(api_key: str) -> dict:
    return {"X-Phantombuster-Key": api_key, "Content-Type": "application/json"}


def launch_scrape(api_key: str, agent_id: str, linkedin_url: str) -> str | None:
    """Launch a PhantomBuster agent to scrape a LinkedIn profile. Returns container ID."""
    try:
        resp = requests.post(
            f"{_BASE_URL}/agents/launch",
            headers=_headers(api_key),
            json={"id": agent_id, "argument": {"sessionCookie": "from_phantom", "profileUrls": [linkedin_url]}},
            timeout=30,
        )
        resp.raise_for_status()
        container_id = resp.json().get("containerId")
        log.info(f"    PhantomBuster launched (container: {container_id})")
        return container_id
    except Exception as e:
        log.warning(f"    PhantomBuster launch failed: {e}")
        return None


def poll_result(api_key: str, agent_id: str, max_wait: int = 120, poll_interval: int = 10) -> dict:
    """Poll PhantomBuster agent output until done. Returns scraped profile data."""
    url = f"{_BASE_URL}/agents/fetch-output"
    params = {"id": agent_id}

    waited = 0
    while waited < max_wait:
        try:
            resp = requests.get(url, headers=_headers(api_key), params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            status = data.get("status")
            if status == "finished":
                output = data.get("output")
                if output:
                    # Output is typically a JSON string or a result container
                    if isinstance(output, str):
                        import json
                        try:
                            return json.loads(output)
                        except json.JSONDecodeError:
                            return {"_raw_output": output}
                    return output if isinstance(output, dict) else {"_raw_output": str(output)}

                # Check resultObject as fallback
                result_obj = data.get("resultObject")
                if result_obj:
                    return result_obj if isinstance(result_obj, dict) else {"_raw_output": str(result_obj)}

                return {}

            if status == "error":
                log.warning(f"    PhantomBuster agent errored: {data.get('output', 'unknown')}")
                return {}

            log.info(f"    PhantomBuster running... ({waited}s elapsed)")

        except Exception as e:
            log.warning(f"    PhantomBuster poll error: {e}")

        time.sleep(poll_interval)
        waited += poll_interval

    log.warning(f"    PhantomBuster timed out after {max_wait}s")
    return {}


def scrape_profile(api_key: str, agent_id: str, linkedin_url: str) -> dict:
    """Scrape a LinkedIn profile via PhantomBuster: launch + poll + return result."""
    log.info(f"    Scraping via PhantomBuster: {linkedin_url}")
    container_id = launch_scrape(api_key, agent_id, linkedin_url)
    if not container_id:
        return {}
    return poll_result(api_key, agent_id)
