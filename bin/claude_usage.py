#!/usr/bin/env python3
"""
claude_usage.py — fetch live usage data from claude.ai/settings/usage.

Calls https://claude.ai/api/organizations/<uuid>/usage with the user's
sessionKey + Cloudflare cookies (saved in ~/.config/c3r/config.env). The
data returned is the EXACT same numbers shown on the user's
claude.ai/settings/usage page — utilization percentages and reset
timestamps for the 5-hour, 7-day, and per-model windows.

Auth setup:
  Run `c3r usage-auth` once to capture cookies from a browser curl.
  Cookies expire (cf_clearance is ~30 min, sessionKey ~weeks). Re-run
  `c3r usage-auth` if usage queries start failing with 403.

Plan tier is fetched from the live API at api.anthropic.com/api/oauth/account
(NOT the stale ~/.claude/.credentials.json), cached for 1 hour.

Caching:
  /tmp/c3r_claude_usage.json — live usage, 30s TTL
  /tmp/c3r_plan.json         — plan info, 1h TTL

Output schema:
  {
    "plan": "max-20x",
    "plan_source": "live_api" | "credentials" | "unknown",
    "five_hour":  {"utilization": 6.0,  "resets_at": "..."},
    "seven_day":  {"utilization": 41.0, "resets_at": "..."},
    "seven_day_opus":   {...} | null,
    "seven_day_sonnet": {...} | null,
    "extra_usage":      {...},
    "source": "claude.ai_live" | "credentials_fallback" | "unavailable",
    "error": null | "string explaining why fallback was used",
    "computed_at": <unix>,
  }
"""
from __future__ import annotations
import gzip, json, os, sys, time, urllib.error, urllib.request
from pathlib import Path

CRED_PATH = Path.home() / ".claude/.credentials.json"
CONFIG_PATH = Path.home() / ".config/c3r/config.env"
CACHE_PATH = Path("/tmp/c3r_claude_usage.json")
PLAN_CACHE_PATH = Path("/tmp/c3r_plan.json")
CACHE_TTL = 30          # live usage: re-fetch every 30s
PLAN_CACHE_TTL = 3600   # plan: re-fetch every hour

def load_config_var(name: str) -> str | None:
    """Read an exported variable from ~/.config/c3r/config.env without sourcing."""
    if not CONFIG_PATH.exists(): return None
    for line in CONFIG_PATH.read_text().splitlines():
        line = line.strip()
        if line.startswith(f"export {name}="):
            v = line[len(f"export {name}="):]
            return v.strip().strip('"').strip("'") or None
    return None

def fetch_live_plan() -> tuple[str, str]:
    """(plan_name, source). Hits live oauth API; falls back to (stale) creds."""
    if PLAN_CACHE_PATH.exists():
        try:
            cached = json.loads(PLAN_CACHE_PATH.read_text())
            if time.time() - cached.get("ts", 0) < PLAN_CACHE_TTL:
                return cached["plan"], cached.get("source", "cache")
        except Exception: pass

    plan, source = "unknown", "unknown"
    try:
        token = json.loads(CRED_PATH.read_text())["claudeAiOauth"]["accessToken"]
        req = urllib.request.Request(
            "https://api.anthropic.com/api/oauth/account",
            headers={"Authorization": f"Bearer {token}",
                     "User-Agent": "c3r-claude-usage/0.2"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        TIER_RANK = {
            "default_claude_max_20x": 5, "default_claude_max_5x": 4,
            "default_claude_pro": 3, "default_claude_team": 3,
            "default_claude_free": 2, "default_claude_ai": 1,
            "auto_api_evaluation": 0,
        }
        best_tier, best_rank = None, -1
        for m in data.get("memberships", []):
            tier = (m.get("organization") or {}).get("rate_limit_tier", "")
            r = TIER_RANK.get(tier, 0)
            if r > best_rank: best_rank, best_tier = r, tier
        if best_tier:
            if "max_20x" in best_tier: plan = "max-20x"
            elif "max_5x" in best_tier: plan = "max-5x"
            elif "pro" in best_tier or "team" in best_tier: plan = "pro"
            elif "free" in best_tier or "claude_ai" in best_tier: plan = "free"
            else: plan = best_tier
            source = "live_api"
    except Exception:
        try:
            cred = json.loads(CRED_PATH.read_text())["claudeAiOauth"]
            tier = cred.get("rateLimitTier", "")
            if "max_20x" in tier: plan = "max-20x"
            elif "max_5x" in tier: plan = "max-5x"
            elif "pro" in tier: plan = "pro"
            else: plan = tier or "unknown"
            source = "credentials"
        except Exception: pass

    try:
        PLAN_CACHE_PATH.write_text(json.dumps({"plan": plan, "source": source, "ts": time.time()}))
    except Exception: pass
    return plan, source

def fetch_live_usage() -> tuple[dict, str | None]:
    """Hit claude.ai/api/organizations/<uuid>/usage. Returns (data, error_message_or_None)."""
    sk  = load_config_var("CLAUDE_AI_SESSION_KEY")
    cfc = load_config_var("CLAUDE_AI_CF_CLEARANCE")
    cfb = load_config_var("CLAUDE_AI_CF_BM")
    org = load_config_var("CLAUDE_AI_ORG_UUID")
    if not (sk and org):
        return {}, "no claude.ai cookies in config (run: c3r usage-auth)"

    url = f"https://claude.ai/api/organizations/{org}/usage"
    cookie_parts = [f"sessionKey={sk}", f"lastActiveOrg={org}"]
    if cfc: cookie_parts.append(f"cf_clearance={cfc}")
    if cfb: cookie_parts.append(f"__cf_bm={cfb}")

    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:139.0) Gecko/20100101 Firefox/139.0",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "Referer": "https://claude.ai/settings/usage",
        "anthropic-client-platform": "web_claude_ai",
        "Cookie": "; ".join(cookie_parts),
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            ct = r.headers.get("Content-Type", "")
            if "json" not in ct:
                return {}, f"non-JSON response (CT={ct}); cookies likely expired"
            return json.loads(raw), None
    except urllib.error.HTTPError as e:
        return {}, f"HTTP {e.code} from claude.ai/api/.../usage — re-run 'c3r usage-auth'"
    except Exception as e:
        return {}, f"fetch error: {e}"

def main() -> int:
    # Cache check
    if CACHE_PATH.exists():
        try:
            cached = json.loads(CACHE_PATH.read_text())
            if time.time() - cached.get("computed_at", 0) < CACHE_TTL:
                print(json.dumps(cached))
                return 0
        except Exception: pass

    plan, plan_source = fetch_live_plan()
    usage, err = fetch_live_usage()

    if err:
        out = {
            "plan": plan, "plan_source": plan_source,
            "source": "unavailable", "error": err,
            "computed_at": time.time(),
        }
    else:
        out = {
            "plan": plan, "plan_source": plan_source,
            "five_hour":         usage.get("five_hour"),
            "seven_day":         usage.get("seven_day"),
            "seven_day_opus":    usage.get("seven_day_opus"),
            "seven_day_sonnet":  usage.get("seven_day_sonnet"),
            "seven_day_oauth_apps": usage.get("seven_day_oauth_apps"),
            "extra_usage":       usage.get("extra_usage"),
            "source": "claude.ai_live",
            "error": None,
            "computed_at": time.time(),
        }
    try:
        tmp = str(CACHE_PATH) + ".tmp"
        Path(tmp).write_text(json.dumps(out))
        os.replace(tmp, CACHE_PATH)
    except Exception: pass
    print(json.dumps(out))
    return 0

if __name__ == "__main__":
    sys.exit(main())
