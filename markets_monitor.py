import hashlib
import json
import os
import re
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "markets_config.json").read_text())
STATE_PATH = ROOT / "markets_state.json"
TZ = ZoneInfo(CONFIG.get("timezone", "Australia/Brisbane"))
DISCORD_API = "https://discord.com/api/v10"
UA = "cairns-art-markets-monitor/1.0 (+GitHub Actions)"

MONTHS = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
          "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12}


def load_state():
    return json.loads(STATE_PATH.read_text())


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def now_local():
    return datetime.now(TZ)


def slugify(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:70]


def event(name, start, end, location, source_name, source_url, kind, notes, free=True, event_type="Regular"):
    base = f"{name}|{start.date().isoformat()}|{location}".lower()
    eid = f"{start.date().isoformat()}-{slugify(name)[:38]}-{hashlib.sha1(base.encode()).hexdigest()[:8]}"
    return {"id": eid, "name": name, "start": start.isoformat(), "end": end.isoformat() if end else None,
            "location": location, "source_name": source_name, "source_url": source_url,
            "kind": kind, "notes": notes, "free": free, "event_type": event_type}


def http_text(url):
    r = requests.get(url, timeout=int(CONFIG.get("request_timeout_seconds", 25)),
                     headers={"User-Agent": UA})
    r.raise_for_status()
    return r.text


def clean_lines(html):
    soup = BeautifulSoup(html, "html.parser")
    return [re.sub(r"\s+", " ", x).strip() for x in soup.get_text("\n").splitlines() if x.strip()]


def parse_named_date(text, default_year=None):
    m = re.search(r"(?i)(?:mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)?\s*,?\s*(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)(?:\s+(20\d{2}))?", text.strip())
    if not m:
        return None
    month = MONTHS.get(m.group(2).lower())
    year = int(m.group(3)) if m.group(3) else default_year
    if not month or not year:
        return None
    try:
        return date(year, month, int(m.group(1)))
    except ValueError:
        return None


def parse_clock(text, fallback=time(8, 0)):
    m = re.search(r"(?i)\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", text)
    if not m:
        return fallback
    hour = int(m.group(1)) % 12
    if m.group(3).lower() == "pm":
        hour += 12
    return time(hour, int(m.group(2) or 0))


def dt_on(d, t):
    return datetime.combine(d, t, TZ)


def discover_cairns_council():
    url = CONFIG["sources"]["cairns_council"]
    lines = clean_lines(http_text(url))
    events = []
    date_re = re.compile(r"(?i)\b(mon|tue|wed|thu|fri|sat|sun)(?:day)?\s+\d{1,2}\s+[A-Za-z]+\s+20\d{2}\b")
    for i, line in enumerate(lines):
        if not re.search(r"(?i)(market|carnival on collins)", line):
            continue
        if line.lower() in {"markets", "upcoming events", "next tanks markets"} or len(line) > 100:
            continue
        nearby = lines[i:i+8]
        d = next((parse_named_date(x) for x in nearby if date_re.search(x)), None)
        if not d:
            continue
        start_t, end_t, location = time(8, 0), None, "Cairns region"
        for x in nearby:
            if re.search(r"(?i)\d{1,2}(?::\d{2})?\s*(am|pm)", x):
                start_t = parse_clock(x, start_t)
                times = re.findall(r"(?i)(\d{1,2})(?::(\d{2}))?\s*(am|pm)", x)
                if len(times) >= 2:
                    h, m, ap = times[-1]
                    end_t = parse_clock(f"{h}:{m or '00'} {ap}")
            if any(k in x.lower() for k in ["avenue", "esplanade", "park", "centre", "center", "showground", "plaza"]):
                if len(x) < 120 and not date_re.search(x):
                    location = x
        lname = line.lower()
        if "palm cove" in lname:
            kind = "Art / handmade"
        elif "tanks" in lname or "carnival on collins" in lname:
            kind = "Art / craft / makers"
        elif "redlynch" in lname or "cottage" in lname or "smith" in lname:
            kind = "Community / craft"
        else:
            kind = "Community market"
        events.append(event(line, dt_on(d, start_t), dt_on(d, end_t) if end_t else None, location,
                            "Cairns Regional Council", url, kind, "Official Council market listing"))
    return events


def discover_tanks():
    url = CONFIG["sources"]["tanks"]
    text = "\n".join(clean_lines(http_text(url)))
    ym = re.search(r"(20\d{2})\s+Tanks Market days", text, re.I)
    year = int(ym.group(1)) if ym else now_local().year
    out, seen = [], set()
    pattern = re.compile(r"(?i)((?:Sunday|Friday)\s+\d{1,2}\s+[A-Za-z]+)(?:\s*\(([^)]*)\))?")
    for m in pattern.finditer(text):
        d = parse_named_date(m.group(1), year)
        if not d or d in seen:
            continue
        seen.add(d)
        note = (m.group(2) or "").lower()
        twilight = "twilight" in note
        carnival = "carnival" in note
        name = "Tanks Twilight Markets" if twilight else ("Carnival on Collins" if carnival else "Tanks Markets")
        start_t = time(16, 0) if twilight else time(8, 0)
        end_t = time(21, 0) if twilight else time(13, 0)
        out.append(event(name, dt_on(d, start_t), dt_on(d, end_t),
                         "Tanks Arts Centre, Collins Avenue, Edge Hill", "Tanks Arts Centre", url,
                         "Art / craft / makers", "Handmade art, craft, vintage, local makers and live music"))
    return out


def discover_palm_cove():
    url = CONFIG["sources"]["palm_cove"]
    lines = clean_lines(http_text(url))
    text = "\n".join(lines)
    ym = re.search(r"\b(20\d{2})\b", text)
    year = int(ym.group(1)) if ym else now_local().year
    out, seen = [], set()
    for line in lines:
        d = parse_named_date(line, year)
        if not d or d in seen:
            continue
        if d.year < now_local().year - 1 or d.year > now_local().year + 2:
            continue
        seen.add(d)
        out.append(event("Palm Cove Markets", dt_on(d, time(8)), dt_on(d, time(14)),
                         "Williams Esplanade, Palm Cove", "Palm Cove Markets", url,
                         "Art / handmade", "130+ stalls; local arts, crafts, gifts, produce and food"))
    return out


def discover_yungaburra():
    url = CONFIG["sources"]["yungaburra"]
    lines = clean_lines(http_text(url))
    text = "\n".join(lines)
    ym = re.search(r"Yungaburra Markets Dates\s+(20\d{2})", text, re.I)
    year = int(ym.group(1)) if ym else now_local().year
    out, seen = [], set()
    for line in lines:
        d = parse_named_date(line, year)
        if not d or d in seen or d.year != year:
            continue
        seen.add(d)
        out.append(event("Yungaburra Markets", dt_on(d, time(7, 30)), dt_on(d, time(12, 30)),
                         "Bruce Jones Market Grounds, Yungaburra", "Yungaburra Markets", url,
                         "Art / craft / country market",
                         "Large monthly market with handmade arts and crafts, local produce and food"))
    return out


def next_weekday(start_date, weekday):
    return start_date + timedelta(days=(weekday - start_date.weekday()) % 7)


def discover_port_douglas():
    url = CONFIG["sources"]["port_douglas"]
    text = BeautifulSoup(http_text(url), "html.parser").get_text(" ", strip=True).lower()
    if "sunday" not in text or "market" not in text:
        return []
    d = next_weekday(now_local().date() - timedelta(days=1), 6)
    out = []
    for _ in range(10):
        out.append(event("Port Douglas Sunday Market", dt_on(d, time(8)), dt_on(d, time(13, 30)),
                         "Market Park / ANZAC Park, Wharf Street, Port Douglas",
                         "Douglas Shire Council", url, "Art / craft / makers",
                         "Cotters market: stallholders grow, produce or make what they sell"))
        d += timedelta(days=7)
    return out


def discover_kuranda_weekend():
    if not CONFIG.get("include", {}).get("kuranda_weekend_option", True):
        return []
    url = CONFIG["sources"]["kuranda"]
    text = BeautifulSoup(http_text(url), "html.parser").get_text(" ", strip=True).lower()
    if "heritage markets" not in text or "art" not in text:
        return []
    d = next_weekday(now_local().date(), 5)
    out = []
    for _ in range(5):
        out.append(event("Kuranda Markets — weekend option", dt_on(d, time(10)), dt_on(d, time(15, 30)),
                         "Kuranda Village, Kuranda", "Kuranda Village", url,
                         "Art / craft / Indigenous art",
                         "Weekend planning marker; Heritage Markets are Wed–Sun and Original Markets daily"))
        d += timedelta(days=7)
    return out




CREATIVE_WORDS = {
    "art", "arts", "artist", "artists", "craft", "crafts", "handcraft", "handcrafted",
    "handmade", "artisan", "artisans", "maker", "makers", "ceramic", "ceramics",
    "jewellery", "jewelry", "photography", "glass art", "vintage", "creative",
    "local stallholders", "local stall holders"
}
MARKET_WORDS = {"market", "markets", "marketplace", "bazaar", "stall", "stallholder", "stallholders"}
FOOD_WORDS = {
    "food", "foods", "street food", "food truck", "food trucks", "food van", "food vans",
    "culinary", "cuisine", "tasting", "feast", "produce", "farmers", "farmers market",
    "gourmet", "wine", "cheese", "seafood", "barbecue", "bbq"
}
FESTIVAL_WORDS = {"festival", "fest", "fiesta", "feast"}
CANDIDATE_TITLE_WORDS = {
    "market", "markets", "maker", "makers", "craft", "handcraft", "artisan",
    "bazaar", "fair", "festival", "expo", "gem", "handmade"
}


def classify_relevant_event(title, body):
    text = f"{title} {body}".lower()
    has_market = any(word in text for word in MARKET_WORDS)
    has_creative = any(word in text for word in CREATIVE_WORDS)
    has_food = any(word in text for word in FOOD_WORDS)
    has_festival = any(word in text for word in FESTIVAL_WORDS)

    if has_market and has_creative:
        return "Art / craft / makers"
    if has_food and (has_market or has_festival):
        return "Food festival / food market"
    return None


def is_creative_market(title, body):
    return classify_relevant_event(title, body) is not None


def candidate_title(title):
    lower = title.lower()
    return any(word in lower for word in CANDIDATE_TITLE_WORDS)


def parse_4ca_event_page(url, title_hint=""):
    html = http_text(url)
    lines = clean_lines(html)
    body = " ".join(lines)
    title = title_hint
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find(["h1", "h2"])
    if h1 and h1.get_text(" ", strip=True):
        title = h1.get_text(" ", strip=True)

    kind = classify_relevant_event(title, body)
    if not kind:
        return None

    date_line_index = None
    start = end = None
    full = re.compile(
        r"(?i)\b(\d{1,2}/\d{1,2}/20\d{2})\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm))\s+to\s+"
        r"(\d{1,2}/\d{1,2}/20\d{2})\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm))"
    )
    for i, line in enumerate(lines):
        m = full.search(line)
        if m:
            d1 = datetime.strptime(m.group(1), "%d/%m/%Y").date()
            d2 = datetime.strptime(m.group(3), "%d/%m/%Y").date()
            start = dt_on(d1, parse_clock(m.group(2)))
            end = dt_on(d2, parse_clock(m.group(4)))
            date_line_index = i
            break

    if not start:
        return None

    location = "Cairns / FNQ"
    if date_line_index is not None:
        for line in lines[date_line_index + 1: date_line_index + 5]:
            low = line.lower()
            if low not in {"free", "event details", "advertisement"} and len(line) <= 160:
                location = line.rstrip(".")
                break

    lower = body.lower()
    free = bool(re.search(r"\bfree\b", lower))
    regular = any(x in lower for x in ["every month", "monthly", "every 2nd", "every second", "first sunday", "second saturday"])
    etype = "Regular discovery" if regular else "Special / ad hoc"
    return event(title, start, end, location, "4CA Community Events", url, kind,
                 "Discovered from a local community-event submission; check source for organiser updates.",
                 free=free, event_type=etype)


def discover_4ca_ad_hoc():
    list_url = CONFIG["sources"]["four_ca"]
    html = http_text(list_url)
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    out = []
    horizon = now_local() + timedelta(days=int(CONFIG.get("discovery_horizon_days", 90)))

    for a in soup.find_all("a", href=True):
        title = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        if not title or not candidate_title(title):
            continue
        url = urljoin(list_url, a["href"])
        parsed = urlparse(url)
        if "4ca.com.au" not in parsed.netloc or "/event" not in parsed.path:
            continue
        if url in seen:
            continue
        seen.add(url)
        try:
            item = parse_4ca_event_page(url, title)
            if item:
                start = datetime.fromisoformat(item["start"]).astimezone(TZ)
                if now_local() - timedelta(days=1) <= start <= horizon:
                    out.append(item)
        except Exception as exc:
            print(f"WARNING: 4CA detail failed {url}: {exc}", file=sys.stderr)
    return out


def find_jsonld_events(value):
    found = []
    if isinstance(value, dict):
        if value.get("@type") == "Event" or (isinstance(value.get("@type"), list) and "Event" in value.get("@type")):
            found.append(value)
        for v in value.values():
            found.extend(find_jsonld_events(v))
    elif isinstance(value, list):
        for v in value:
            found.extend(find_jsonld_events(v))
    return found


def jsonld_location(obj):
    loc = obj.get("location")
    if isinstance(loc, str):
        return loc
    if not isinstance(loc, dict):
        return "Cairns / FNQ"
    name = loc.get("name") or ""
    address = loc.get("address")
    bits = [name]
    if isinstance(address, str):
        bits.append(address)
    elif isinstance(address, dict):
        bits.extend([address.get("streetAddress"), address.get("addressLocality"), address.get("addressRegion")])
    return ", ".join(str(x).strip() for x in bits if x and str(x).strip()) or "Cairns / FNQ"


def parse_jsonld_market_page(url, source_name, title_hint=""):
    html = http_text(url)
    soup = BeautifulSoup(html, "html.parser")
    body = soup.get_text(" ", strip=True)
    objects = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            objects.extend(find_jsonld_events(json.loads(script.string or script.get_text())))
        except Exception:
            continue

    for obj in objects:
        title = obj.get("name") or title_hint
        description = BeautifulSoup(str(obj.get("description") or ""), "html.parser").get_text(" ", strip=True)
        evidence = f"{body} {description}"
        kind = classify_relevant_event(title, evidence)
        if not kind:
            continue
        raw_start = obj.get("startDate")
        if not raw_start:
            continue
        try:
            start = datetime.fromisoformat(str(raw_start).replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=TZ)
            start = start.astimezone(TZ)
        except ValueError:
            continue
        raw_end = obj.get("endDate")
        end = None
        if raw_end:
            try:
                end = datetime.fromisoformat(str(raw_end).replace("Z", "+00:00"))
                if end.tzinfo is None:
                    end = end.replace(tzinfo=TZ)
                end = end.astimezone(TZ)
            except ValueError:
                end = None
        lower = evidence.lower()
        regular = any(x in lower for x in ["monthly", "every month", "weekly", "every sunday", "every saturday"])
        etype = "Regular discovery" if regular else "Special / ad hoc"
        free = "free" in lower and "entry" in lower
        return event(title, start, end, jsonld_location(obj), source_name, url,
                     kind,
                     "Discovered from a live local events calendar; check source for organiser updates.",
                     free=free, event_type=etype)
    return None


def discover_cairns_showgrounds():
    list_url = CONFIG["sources"]["cairns_showgrounds"]
    html = http_text(list_url)
    soup = BeautifulSoup(html, "html.parser")
    horizon = now_local() + timedelta(days=int(CONFIG.get("discovery_horizon_days", 90)))
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        title = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        if not title or not candidate_title(title):
            continue
        url = urljoin(list_url, a["href"])
        parsed = urlparse(url)
        if "cairnsshow.com.au" not in parsed.netloc or "/event" not in parsed.path:
            continue
        if url in seen:
            continue
        seen.add(url)
        try:
            item = parse_jsonld_market_page(url, "Cairns Showgrounds", title)
            if item:
                start = datetime.fromisoformat(item["start"]).astimezone(TZ)
                if now_local() - timedelta(days=1) <= start <= horizon:
                    out.append(item)
        except Exception as exc:
            print(f"WARNING: Showgrounds detail failed {url}: {exc}", file=sys.stderr)
    return out


def nth_weekday_of_month(year, month, weekday, n):
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(days=7 * (n - 1))


def last_weekday_of_month(year, month, weekday):
    if month == 12:
        d = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        d = date(year, month + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def fallback_cairns_council():
    """Official recurring schedules used when Cairns Council blocks GitHub Actions."""
    today = now_local().date()
    horizon = today + timedelta(days=100)
    out = []
    cursor = date(today.year, today.month, 1)
    while cursor <= horizon:
        y, m = cursor.year, cursor.month

        # Gordonvale Cottage Markets: first Saturday monthly, 7am-1pm.
        d = nth_weekday_of_month(y, m, 5, 1)
        if today - timedelta(days=1) <= d <= horizon:
            out.append(event(
                "Gordonvale Cottage Markets", dt_on(d, time(7)), dt_on(d, time(13)),
                "Norman Park, Gordonvale", "Cairns Council recurring schedule",
                CONFIG["sources"]["cairns_council"], "Community / craft",
                "Official recurring schedule: first Saturday monthly; homemade crafts, local produce and food"))

        # Smithy Community Markets: second Saturday monthly, 8:30am-2:30pm.
        d = nth_weekday_of_month(y, m, 5, 2)
        if today - timedelta(days=1) <= d <= horizon:
            out.append(event(
                "Smithy Community Markets", dt_on(d, time(8, 30)), dt_on(d, time(14, 30)),
                "Smithfield Shopping Centre", "Cairns Council recurring schedule",
                CONFIG["sources"]["cairns_council"], "Community market",
                "Official recurring schedule: second Saturday monthly; local stallholders and diverse products"))

        cursor = date(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 1)
    return out


def fallback_tanks():
    """Tanks' published recurring pattern when its site returns HTTP 403 to Actions."""
    today = now_local().date()
    horizon = today + timedelta(days=120)
    out = []
    for year in range(today.year, horizon.year + 1):
        for month in range(4, 12):
            if month == 8:
                continue
            d = last_weekday_of_month(year, month, 6)
            if today - timedelta(days=1) <= d <= horizon:
                out.append(event(
                    "Tanks Markets", dt_on(d, time(8)), dt_on(d, time(13)),
                    "Tanks Arts Centre, Collins Avenue, Edge Hill",
                    "Tanks published recurring schedule", CONFIG["sources"]["tanks"],
                    "Art / craft / makers",
                    "Official pattern: last Sunday Apr-Nov except August; local art, craft, vintage and makers"))
        # Carnival on Collins replaces the August market and is held on Father's Day.
        d = nth_weekday_of_month(year, 9, 6, 1)
        if today - timedelta(days=1) <= d <= horizon:
            out.append(event(
                "Carnival on Collins", dt_on(d, time(9)), dt_on(d, time(15)),
                "Collins Avenue, Edge Hill",
                "Tanks published recurring schedule", CONFIG["sources"]["tanks"],
                "Art / craft / makers",
                "Father's Day market/festival on Collins Avenue; verify times on the official listing"))
    return out


def discover_all():
    discoverers = [discover_cairns_council, discover_tanks, discover_palm_cove,
                   discover_yungaburra, discover_port_douglas, discover_kuranda_weekend,
                   discover_4ca_ad_hoc, discover_cairns_showgrounds]
    found = []
    for fn in discoverers:
        try:
            found.extend(fn())
        except Exception as exc:
            print(f"WARNING: {fn.__name__} failed: {exc}", file=sys.stderr)
            if fn is discover_cairns_council:
                print("INFO: using official recurring Cairns Council market schedules", file=sys.stderr)
                found.extend(fallback_cairns_council())
            elif fn is discover_tanks:
                print("INFO: using Tanks published recurring schedule", file=sys.stderr)
                found.extend(fallback_tanks())
    merged = {}
    priority = {"Cairns Showgrounds": 8, "4CA Community Events": 7,
                "Tanks Arts Centre": 6, "Palm Cove Markets": 6, "Yungaburra Markets": 6,
                "Douglas Shire Council": 6, "Kuranda Village": 5, "Cairns Regional Council": 4}
    for e in found:
        d = datetime.fromisoformat(e["start"]).date().isoformat()
        family = re.sub(r"\s+-\s+(september|october|november|december|january|february|march|april|may|june|july|august).*$",
                        "", e["name"], flags=re.I)
        key = (slugify(family), d)
        old = merged.get(key)
        if not old or priority.get(e["source_name"], 0) > priority.get(old["source_name"], 0):
            merged[key] = e
    result = sorted(merged.values(), key=lambda e: datetime.fromisoformat(e["start"]))
    specials = [e for e in result if "Special" in e.get("event_type", "")]
    print(
        f"INFO: discovered {len(result)} market dates across sources; "
        f"{len(specials)} special/ad-hoc date(s).",
        file=sys.stderr,
    )
    for e in specials[:12]:
        print(f"INFO: special -> {e['name']} | {e['start']} | {e['source_name']}", file=sys.stderr)
    return result


def discord_headers():
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN is not configured")
    return {"Authorization": f"Bot {token}", "Content-Type": "application/json"}


def channel_id():
    return os.environ.get("MARKETS_DISCORD_CHANNEL_ID") or CONFIG.get("discord_channel_id") or ""


def send_discord(text):
    cid = channel_id()
    if not cid:
        raise RuntimeError("Market Discord channel ID is not configured")
    chunks, buf = [], ""
    for line in text.splitlines(True):
        if len(buf) + len(line) > 1900 and buf:
            chunks.append(buf.rstrip())
            buf = ""
        buf += line
    if buf.strip():
        chunks.append(buf.rstrip())
    for chunk in chunks:
        r = requests.post(f"{DISCORD_API}/channels/{cid}/messages", headers=discord_headers(),
                          json={"content": chunk}, timeout=30)
        r.raise_for_status()


def get_user_messages(state):
    cid = channel_id()
    if not cid:
        return []
    params = {"limit": 50}
    if state.get("last_discord_message_id"):
        params["after"] = state["last_discord_message_id"]
    r = requests.get(f"{DISCORD_API}/channels/{cid}/messages", headers=discord_headers(),
                     params=params, timeout=30)
    r.raise_for_status()
    messages = sorted(r.json(), key=lambda m: int(m["id"]))
    return [m for m in messages if m.get("author", {}).get("id") == CONFIG["discord_user_id"]]


def upcoming(events):
    now = now_local()
    end = now + timedelta(days=int(CONFIG.get("digest_days", 14)))
    return [e for e in events if now <= datetime.fromisoformat(e["start"]).astimezone(TZ) <= end]


def fmt_event(n, e):
    start = datetime.fromisoformat(e["start"]).astimezone(TZ)
    end = datetime.fromisoformat(e["end"]).astimezone(TZ) if e.get("end") else None
    when = f"{start:%a %d %b, %-I:%M %p}"
    if end:
        when += f"–{end:%-I:%M %p}"
    return (f"{n}. **{e['name']}**\n"
            f"   📅 {when} AEST | 📍 {e['location']}\n"
            f"   {'🍴' if 'Food' in e['kind'] else '🎨'} {e['kind']} | {'✨' if 'Special' in e.get('event_type', '') else '🔁'} {e.get('event_type', 'Regular')} | 💰 {'FREE' if e.get('free') else 'Check listing'}\n"
            f"   {e['notes']}\n"
            f"   🔗 {e['source_url']}")


def make_digest(events, state):
    rows = upcoming(events)
    if not rows:
        state["latest_market_index"] = {}
        return "🎨 **Cairns art & maker markets — next 14 days**\nNo tracked markets found."
    state["latest_market_index"] = {str(i): e["id"] for i, e in enumerate(rows, 1)}
    body = "\n\n".join(fmt_event(i, e) for i, e in enumerate(rows, 1))
    return ("🎨 **Cairns / FNQ art & maker markets — next 14 days**\n"
            "Choose the ones you want. Selected markets get reminders **7 days out, 1 day out and on the day**.\n\n"
            + body + "\n\nReply: !watch 1 3 5 or !watch all · !unwatch 3 · !list · !markets")


def by_id(events):
    return {e["id"]: e for e in events}


def process_command(content, events, state):
    content = content.strip().lower()
    if not content:
        return None
    first = content.split()[0]
    if first in {"watch", "unwatch", "list", "markets", "fixtures", "help"}:
        content = "!" + content
    if content == "!help":
        return "Commands: !markets, !watch 1 3, !watch all, !unwatch 3, !list."
    if content in {"!markets", "!fixtures"}:
        return make_digest(events, state)
    index = state.get("latest_market_index", {})
    watched = set(state.get("watched_market_ids", []))
    if content.startswith("!watch"):
        bits = content.split()[1:]
        watched.update(index.values() if bits == ["all"] else [index[x] for x in bits if x in index])
        state["watched_market_ids"] = sorted(watched)
        return f"✅ Watching {len(watched)} market date(s). Reminders: 7 days, 1 day and day-of."
    if content.startswith("!unwatch"):
        for x in content.split()[1:]:
            if x in index:
                watched.discard(index[x])
        state["watched_market_ids"] = sorted(watched)
        return f"✅ Market watch list updated: {len(watched)} selected."
    if content == "!list":
        lookup = by_id(events)
        rows = []
        for eid in state.get("watched_market_ids", []):
            e = lookup.get(eid)
            if e:
                start = datetime.fromisoformat(e["start"]).astimezone(TZ)
                rows.append(f"• **{e['name']}** — {start:%a %d %b, %-I:%M %p} — {e['location']}")
        return "👀 **Your selected markets**\n" + ("\n".join(rows) if rows else "Nothing selected yet.")
    return None


def process_discord_commands(events, state):
    for m in get_user_messages(state):
        response = process_command(m.get("content", ""), events, state)
        state["last_discord_message_id"] = m["id"]
        if response:
            send_discord(response)


def reminder_due(start, label, now):
    days = (start.date() - now.date()).days
    cfg = CONFIG.get("reminders", {})
    if label == "7d":
        return days == 7 and now.hour >= int(cfg.get("seven_days_hour", 8))
    if label == "1d":
        return days == 1 and now.hour >= int(cfg.get("one_day_hour", 8))
    if label == "day":
        return days == 0 and now.hour >= int(cfg.get("day_of_hour", 6)) and now < start
    return False


def send_due_reminders(events, state):
    now = now_local()
    lookup = by_id(events)
    sent = state.setdefault("sent_reminders", {})
    for eid in state.get("watched_market_ids", []):
        e = lookup.get(eid)
        if not e:
            continue
        start = datetime.fromisoformat(e["start"]).astimezone(TZ)
        already = set(sent.get(eid, []))
        for label, title in [("7d", "7 days to go"), ("1d", "Tomorrow"), ("day", "Today")]:
            if label not in already and reminder_due(start, label, now):
                send_discord(
                    f"⏰ <@{CONFIG['discord_user_id']}> **Market reminder — {title}**\n"
                    f"**{e['name']}**\n📅 {start:%A %d %B, %-I:%M %p} AEST\n"
                    f"📍 {e['location']}\n{'🍴' if 'Food' in e['kind'] else '🎨'} {e['kind']} · {e.get('event_type', 'Regular')}\n🔗 {e['source_url']}")
                already.add(label)
        sent[eid] = sorted(already)


def prune_state(events, state):
    lookup = by_id(events)
    cutoff = now_local() - timedelta(days=1)
    state["watched_market_ids"] = sorted(
        eid for eid in set(state.get("watched_market_ids", []))
        if eid in lookup and datetime.fromisoformat(lookup[eid]["start"]).astimezone(TZ) >= cutoff)
    state["sent_reminders"] = {k: v for k, v in state.get("sent_reminders", {}).items() if k in lookup}


def main():
    mode = (sys.argv[1] if len(sys.argv) > 1 else "poll").lower()
    events = discover_all()
    state = load_state()
    prune_state(events, state)
    if mode == "preview":
        print(make_digest(events, state))
    elif mode == "weekly":
        send_discord(make_digest(events, state))
        state["last_weekly_digest"] = now_local().isoformat()
    elif mode == "poll":
        process_discord_commands(events, state)
        send_due_reminders(events, state)
    else:
        raise SystemExit("Usage: python markets_monitor.py [preview|weekly|poll]")
    save_state(state)


if __name__ == "__main__":
    main()
