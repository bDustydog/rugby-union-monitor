import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "config.json").read_text())
STATE_PATH = ROOT / "state.json"
MANUAL_PATH = ROOT / "data" / "manual_fixtures.json"
TZ = ZoneInfo(CONFIG.get("timezone", "Australia/Brisbane"))
DISCORD_API = "https://discord.com/api/v10"


def load_state():
    return json.loads(STATE_PATH.read_text())


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def parse_utc(value):
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def discord_headers():
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN is not configured")
    return {"Authorization": f"Bot {token}", "Content-Type": "application/json"}


def send_discord(text):
    channel_id = CONFIG["discord_channel_id"]
    chunks = []
    buf = ""
    for line in text.splitlines(True):
        if len(buf) + len(line) > 1900 and buf:
            chunks.append(buf.rstrip())
            buf = ""
        buf += line
    if buf.strip():
        chunks.append(buf.rstrip())
    for chunk in chunks:
        r = requests.post(
            f"{DISCORD_API}/channels/{channel_id}/messages",
            headers=discord_headers(),
            json={"content": chunk},
            timeout=30,
        )
        r.raise_for_status()


def get_user_messages(state):
    channel_id = CONFIG["discord_channel_id"]
    params = {"limit": 50}
    if state.get("last_discord_message_id"):
        params["after"] = state["last_discord_message_id"]
    r = requests.get(
        f"{DISCORD_API}/channels/{channel_id}/messages",
        headers=discord_headers(),
        params=params,
        timeout=30,
    )
    r.raise_for_status()
    messages = sorted(r.json(), key=lambda m: int(m["id"]))
    return [
        m for m in messages
        if m.get("author", {}).get("id") == CONFIG["discord_user_id"]
    ]


def extract_json_array(html):
    stripped = html.strip()
    if stripped.startswith("["):
        return json.loads(stripped)
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["textarea", "pre", "code"]):
        text = tag.get_text(strip=True)
        if text.startswith("[") and "MatchNumber" in text:
            return json.loads(text)
    match = re.search(r'(\[\s*\{\s*"MatchNumber".*?\}\s*\])', html, re.S)
    if match:
        return json.loads(match.group(1))
    raise ValueError("Could not locate fixture JSON in FixtureDownload response")


def fetch_fixture_download(source):
    url = f"https://fixturedownload.com/view/json/{source['slug']}"
    r = requests.get(url, timeout=30, headers={"User-Agent": "rugby-union-monitor/1.0"})
    r.raise_for_status()
    rows = extract_json_array(r.text)
    out = []
    for row in rows:
        date_raw = row.get("DateUtc")
        if not date_raw:
            continue
        dt = datetime.strptime(date_raw, "%Y-%m-%d %H:%M:%SZ").replace(tzinfo=timezone.utc)
        out.append({
            "id": f"{source['slug']}:{row.get('MatchNumber')}",
            "competition": source["competition"],
            "gender": source.get("gender", "Unknown"),
            "format": source.get("format", "15s"),
            "date_utc": dt.isoformat(),
            "home": row.get("HomeTeam") or "TBC",
            "away": row.get("AwayTeam") or "TBC",
            "location": row.get("Location") or "TBC",
            "stan": bool(source.get("stan")),
            "free_stream_au": None,
        })
    return out


def fetch_all_fixtures():
    fixtures = []
    for source in CONFIG.get("fixture_sources", []):
        try:
            fixtures.extend(fetch_fixture_download(source))
        except Exception as exc:
            print(f"WARNING: source {source['competition']} failed: {exc}", file=sys.stderr)
    fixtures.extend(json.loads(MANUAL_PATH.read_text()))
    unique = {}
    for f in fixtures:
        unique[f["id"]] = f
    return sorted(unique.values(), key=lambda f: parse_utc(f["date_utc"]))


PAGE_CACHE = {}


def official_page_text(url):
    if not url:
        return ""
    if url in PAGE_CACHE:
        return PAGE_CACHE[url]
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "rugby-union-monitor/1.1"})
        r.raise_for_status()
        text = BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True)
    except Exception as exc:
        print(f"WARNING: broadcaster check failed for {url}: {exc}", file=sys.stderr)
        text = ""
    PAGE_CACHE[url] = text
    return text


def md_link(label, url=None):
    return f"[{label}]({url})" if url else label


def add_option(options, label, url=None):
    if label not in {item[0] for item in options}:
        options.append((label, url))


def explicit_free_streams(fixture):
    raw = fixture.get("free_stream_au")
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]
    links = CONFIG.get("free_viewing_sources", {})
    options = []
    for label in raw:
        add_option(options, label, links.get(label))
    return options


def confirmed_free_options(fixture):
    """Return official free Australian viewing options we can support with current rules/pages."""
    options = explicit_free_streams(fixture)
    teams = {fixture.get("home"), fixture.get("away")}
    competition = fixture.get("competition", "").lower()
    sources = CONFIG.get("free_viewing_sources", {})
    pages = CONFIG.get("official_broadcast_pages", {})

    # Rugby Australia confirms Wallabies home Tests and matches against New Zealand
    # are free on the Nine Network / 9Now in Australia.
    if (
        fixture.get("gender") == "Men"
        and "Australia" in teams
        and (fixture.get("home") == "Australia" or "New Zealand" in teams)
    ):
        evidence_url = pages.get("rugby_australia_watch")
        text = official_page_text(evidence_url).lower()
        if (
            not text
            or (
                "all wallabies home games" in text
                and "new zealand" in text
                and "9now" in text
            )
        ):
            add_option(options, "9Now", sources.get("9Now"))
            add_option(options, "Nine Network", evidence_url)

    # World Rugby's Nations Cup site explicitly advertises every match live and free
    # on RugbyPass TV. Keep this separate from the elite Nations Championship.
    if "world rugby nations cup" in competition:
        evidence_url = pages.get("world_rugby_nations_cup")
        text = official_page_text(evidence_url).lower()
        if "live for free on rugbypass tv" in text or "watch live for free on rugbypass tv" in text:
            add_option(options, "RugbyPass TV", sources.get("RugbyPass TV"))

    # Current Australian Rugby World Cup rights include free Nine/9Now coverage
    # for Australian national-team matches. This rule is only used when such
    # fixtures are added to the tracker.
    if "rugby world cup" in competition and "Australia" in teams:
        add_option(options, "9Now", sources.get("9Now"))
        add_option(options, "Nine Network", pages.get("rugby_australia_watch"))

    return options


def free_fallback_checks(fixture):
    """Official free services worth checking when a match is not confirmed free in Australia."""
    competition = fixture.get("competition", "").lower()
    sources = CONFIG.get("free_viewing_sources", {})
    checks = []

    # WXV has a current Australia-specific broadcaster page naming Stan Sport for
    # all matches, so don't imply RugbyPass TV is a free Australian option there.
    if "wxv" in competition:
        return checks

    # Rugby Australia says HSBC SVNS is exclusive to Stan Sport in Australia.
    if "svns" in competition or "sevens" in competition:
        return checks

    # RugbyPass TV and World Rugby YouTube frequently carry official free rugby,
    # but rights can be geo-restricted. They are fallbacks, not "confirmed free",
    # unless a competition-specific rule above confirms them.
    for label in ("RugbyPass TV", "World Rugby YouTube"):
        add_option(checks, label, sources.get(label))
    return checks


def broadcast_lines(fixture, prefix=""):
    paid_url = CONFIG.get("paid_viewing_sources", {}).get("Stan Sport")
    paid = md_link("Stan Sport", paid_url) if fixture.get("stan") else "Check official broadcaster"

    confirmed = confirmed_free_options(fixture)
    checks = free_fallback_checks(fixture)

    lines = [f"{prefix}📺 Paid: {paid}"]
    if confirmed:
        free_text = " · ".join(md_link(label, url) for label, url in confirmed)
        lines.append(f"{prefix}🆓 FREE confirmed in Australia: {free_text}")
    else:
        lines.append(f"{prefix}🆓 FREE in Australia: none confirmed")

    if checks:
        check_text = " · ".join(md_link(label, url) for label, url in checks)
        lines.append(
            f"{prefix}🔎 Official free checks: {check_text} "
            "(live rights vary by event/territory)"
        )
    return "\n".join(lines)


def broadcast_text(fixture):
    """Compact version retained for compatibility."""
    return broadcast_lines(fixture).replace("\n", " | ")


def upcoming(fixtures, now=None):
    now = now or datetime.now(timezone.utc)
    end = now + timedelta(days=int(CONFIG.get("lookahead_days", 8)))
    return [f for f in fixtures if now <= parse_utc(f["date_utc"]) <= end]


def fixture_line(number, fixture):
    local = parse_utc(fixture["date_utc"]).astimezone(TZ)
    when = (
        f"{local:%a %d %b} | Event match times TBC"
        if fixture.get("time_tbc")
        else f"{local:%a %d %b, %I:%M %p} AEST"
    )
    return (
        f"{number}. **{fixture['home']} v {fixture['away']}** "
        f"— {fixture['gender']} {fixture['format']}\n"
        f"   {when} | {fixture['competition']}\n"
        f"{broadcast_lines(fixture, prefix='   ')}"
    )


def make_digest(fixtures, state):
    matches = upcoming(fixtures)
    if not matches:
        state["latest_fixture_index"] = {}
        return "🏉 **Rugby this week**\nNo tracked international fixtures in the next 8 days."
    state["latest_fixture_index"] = {
        str(i): f["id"] for i, f in enumerate(matches, start=1)
    }
    body = "\n\n".join(fixture_line(i, f) for i, f in enumerate(matches, start=1))
    return (
        "🏉 **Rugby this week — choose what you want reminders for**\n"
        + body
        + "\n\nReply: `!watch 1 3 5` or `!watch all`. "
          "Use `!list` to see your watch list."
    )


def fixture_by_id(fixtures):
    return {f["id"]: f for f in fixtures}


def process_command(content, fixtures, state):
    content = content.strip().lower()
    # Be forgiving in Discord: "watch 1 3" and "list" work as well as "!watch 1 3" and "!list".
    first = content.split()[0] if content else ""
    if first in {"watch", "unwatch", "list", "fixtures", "help"}:
        content = "!" + content
    index = state.get("latest_fixture_index", {})
    watched = set(state.get("watched_fixture_ids", []))
    by_id = fixture_by_id(fixtures)

    if content == "!help":
        return "Commands: `!fixtures`, `!watch 1 3`, `!watch all`, `!unwatch 3`, `!list`."

    if content == "!fixtures":
        return make_digest(fixtures, state)

    if content.startswith("!watch"):
        bits = content.split()[1:]
        if bits == ["all"]:
            watched.update(index.values())
        else:
            for bit in bits:
                if bit in index:
                    watched.add(index[bit])
        state["watched_fixture_ids"] = sorted(watched)
        return f"✅ Watching {len(watched)} fixture(s). I’ll remind you before kick-off."

    if content.startswith("!unwatch"):
        for bit in content.split()[1:]:
            fixture_id = index.get(bit)
            if fixture_id:
                watched.discard(fixture_id)
        state["watched_fixture_ids"] = sorted(watched)
        return f"✅ Watch list updated: {len(watched)} fixture(s)."

    if content == "!list":
        rows = []
        for fid in state.get("watched_fixture_ids", []):
            f = by_id.get(fid)
            if f:
                local = parse_utc(f["date_utc"]).astimezone(TZ)
                when = f"{local:%a %d %b} — times TBC" if f.get("time_tbc") else f"{local:%a %d %b %I:%M %p}"
                rows.append(
                    f"• {f['home']} v {f['away']} — {when}\n"
                    f"{broadcast_lines(f, prefix='  ')}"
                )
        return "👀 **Your rugby watch list**\n" + ("\n".join(rows) if rows else "Nothing selected yet.")

    return None


def process_discord_commands(fixtures, state):
    messages = get_user_messages(state)
    for message in messages:
        response = process_command(message.get("content", ""), fixtures, state)
        state["last_discord_message_id"] = message["id"]
        if response:
            send_discord(response)


def send_due_reminders(fixtures, state):
    now = datetime.now(timezone.utc)
    by_id = fixture_by_id(fixtures)
    sent = set(state.get("sent_reminders", []))
    for fid in state.get("watched_fixture_ids", []):
        f = by_id.get(fid)
        if not f or fid in sent:
            continue
        if f.get("time_tbc"):
            continue
        kickoff = parse_utc(f["date_utc"])
        hours = (kickoff - now).total_seconds() / 3600
        if 0 < hours <= 12:
            local = kickoff.astimezone(TZ)
            send_discord(
                f"⏰ <@{CONFIG['discord_user_id']}> **Rugby reminder**\n"
                f"**{f['home']} v {f['away']}**\n"
                f"{local:%A %d %B, %I:%M %p} AEST\n"
                f"{f['competition']} | {f['gender']} {f['format']}\n"
                f"{broadcast_lines(f)}"
            )
            sent.add(fid)
    state["sent_reminders"] = sorted(sent)


def run_weekly(fixtures, state):
    message = make_digest(fixtures, state)
    send_discord(message)
    state["last_weekly_digest"] = datetime.now(timezone.utc).isoformat()


def main():
    mode = (sys.argv[1] if len(sys.argv) > 1 else "poll").lower()
    fixtures = fetch_all_fixtures()
    state = load_state()

    if mode == "weekly":
        run_weekly(fixtures, state)
    elif mode == "poll":
        process_discord_commands(fixtures, state)
        send_due_reminders(fixtures, state)
    elif mode == "preview":
        print(make_digest(fixtures, state))
    else:
        raise SystemExit("Usage: python monitor.py [weekly|poll|preview]")

    save_state(state)


if __name__ == "__main__":
    main()
