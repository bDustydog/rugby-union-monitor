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


def free_stream_for(fixture):
    if fixture.get("free_stream_au"):
        return fixture["free_stream_au"]
    teams = {fixture.get("home"), fixture.get("away")}
    # Rugby Australia: Wallabies home Tests and Bledisloe matches are live on Nine/9Now.
    if "Australia" in teams and (
        fixture.get("home") == "Australia" or "New Zealand" in teams
    ) and fixture.get("gender") == "Men":
        return "9Now"
    return None


def broadcast_text(fixture):
    paid = "Stan Sport" if fixture.get("stan") else "Check official broadcaster"
    free = free_stream_for(fixture)
    return f"{paid}" + (f" | FREE: {free}" if free else " | Free AU stream: none confirmed")


def upcoming(fixtures, now=None):
    now = now or datetime.now(timezone.utc)
    end = now + timedelta(days=int(CONFIG.get("lookahead_days", 8)))
    return [f for f in fixtures if now <= parse_utc(f["date_utc"]) <= end]


def fixture_line(number, fixture):
    local = parse_utc(fixture["date_utc"]).astimezone(TZ)
    return (
        f"{number}. **{fixture['home']} v {fixture['away']}** "
        f"— {fixture['gender']} {fixture['format']}\n"
        f"   {local:%a %d %b, %I:%M %p} AEST | {fixture['competition']}\n"
        f"   📺 Where to watch: {broadcast_text(fixture)}"
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
                rows.append(f"• {f['home']} v {f['away']} — {local:%a %d %b %I:%M %p}")
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
        kickoff = parse_utc(f["date_utc"])
        hours = (kickoff - now).total_seconds() / 3600
        if 0 < hours <= 12:
            local = kickoff.astimezone(TZ)
            send_discord(
                f"⏰ <@{CONFIG['discord_user_id']}> **Rugby reminder**\n"
                f"**{f['home']} v {f['away']}**\n"
                f"{local:%A %d %B, %I:%M %p} AEST\n"
                f"{f['competition']} | {f['gender']} {f['format']}\n"
                f"📺 Where to watch: {broadcast_text(f)}"
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
