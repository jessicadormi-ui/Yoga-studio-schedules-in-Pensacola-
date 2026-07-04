#!/usr/bin/env python3
"""Fetch weekly class schedules from Pensacola yoga studios into schedule.json.

Covers a rolling 7-day window starting today (America/Chicago).
Studios & platforms:
  - Lovelock Healing Arts ........ Momence (public readonly API)
  - Golden Hour Yoga & Tea House . Momence (public readonly API)
  - Disko Lemonade Yoga .......... fitDEGREE (public API)
  - Florida Power Yoga ........... Zen Planner (HTML list view)
Link-only (no scraper — see CLAUDE.md for why):
  - Seek Yoga (WellnessLiving), ChiroYoga (Jane App)
"""
import json
import re
import sys
import datetime as dt
from zoneinfo import ZoneInfo

import requests

TZ = ZoneInfo("America/Chicago")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0",
      "Accept": "application/json"}
TODAY = dt.datetime.now(TZ).date()
START = TODAY
END = TODAY + dt.timedelta(days=6)

MOMENCE_API = "https://readonly-api.momence.com"


def momence(slug, fallback_host_id=None):
    """Return normalized classes for a Momence host, resolving hostId from slug."""
    host_id = fallback_host_id
    try:
        r = requests.get(f"{MOMENCE_API}/schedule/GetLatestStandalone",
                         params={"hostUrl": slug, "timezoneOffset": 0,
                                 "excludeCollections": "true"},
                         headers=UA, timeout=30)
        r.raise_for_status()
        host_id = r.json()["message"]["info"]["hostId"]
    except Exception as e:  # noqa: BLE001
        print(f"  ! slug resolution failed ({e}); using cached id {host_id}")
        if not host_id:
            raise
    r = requests.get(
        f"{MOMENCE_API}/host-plugins/host/{host_id}/host-schedule/sessions",
        params={"startDate": str(START), "endDate": str(END + dt.timedelta(days=1)),
                "pageSize": 500},
        headers=UA, timeout=30)
    r.raise_for_status()
    out = []
    for s in r.json().get("payload", []):
        starts = s.get("startsAt")
        if not starts or s.get("isCancelled"):
            continue
        local = dt.datetime.fromisoformat(starts.replace("Z", "+00:00")).astimezone(TZ)
        if not (START <= local.date() <= END):
            continue
        t = s.get("teacher")  # plain string, e.g. "Marina Hale"
        if isinstance(t, dict):
            t = " ".join(x for x in [t.get("firstName"), t.get("lastName")] if x)
        out.append({"date": str(local.date()), "time": local.strftime("%H:%M"),
                    "name": (s.get("sessionName") or "").strip(),
                    "instructor": (t or "").strip()})
    return out


def fitdegree(fitspot_id):
    """Return normalized classes from fitDEGREE. fs_event_datetime is studio-local."""
    utc_start = dt.datetime.combine(START, dt.time.min, TZ).astimezone(dt.timezone.utc)
    utc_end = dt.datetime.combine(END, dt.time.max, TZ).astimezone(dt.timezone.utc)
    r = requests.get("https://api.fitdegree.com/class-session/",
                     params={"fitspot_id": fitspot_id,
                             "event_datetime__GTE": utc_start.strftime("%Y-%m-%d %H:%M:%S"),
                             "event_datetime__LTE": utc_end.strftime("%Y-%m-%d %H:%M:%S")},
                     headers=UA, timeout=30)
    r.raise_for_status()
    items = r.json()["response"]["data"]["items"]
    out = []
    for it in items:
        if it.get("is_cancelled"):
            continue
        raw = it.get("fs_event_datetime")
        if raw:  # already studio-local
            local = dt.datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
        else:    # fall back: event_datetime is UTC
            local = (dt.datetime.strptime(it["event_datetime"], "%Y-%m-%d %H:%M:%S")
                     .replace(tzinfo=dt.timezone.utc).astimezone(TZ))
        if not (START <= local.date() <= END):
            continue
        instr = " ".join(x for x in [(it.get("instructor_first_name") or "").strip(),
                                     (it.get("instructor_last_name") or "").strip()] if x)
        out.append({"date": local.strftime("%Y-%m-%d"), "time": local.strftime("%H:%M"),
                    "name": (it.get("class_title") or "").strip(),
                    "instructor": instr})
    return out


DAY_RE = re.compile(r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), "
                    r"(January|February|March|April|May|June|July|August|September|"
                    r"October|November|December) (\d{1,2}), (\d{4})$")
TIME_RE = re.compile(r"^(\d{1,2}):(\d{2}) (AM|PM)$")
SKIP_LOCATIONS = ("Remote", "Virtual", "Coming Soon")

URU_DAY_RE = re.compile(r"^\w+, (January|February|March|April|May|June|July|August|"
                        r"September|October|November|December) (\d{1,2})$")
URU_TIME_RE = re.compile(r"(\d{1,2}):(\d{2}) (am|pm)")


def uru():
    """Scrape URU's own site, which server-renders its Mindbody schedule as HTML.

    Each location page has a list-view table (class mz-schedule-filter): 'header'
    rows carry 'Saturday, July 4' (no year); class rows carry time range, name,
    instructor. Pages cover a rolling week starting today.
    """
    from bs4 import BeautifulSoup
    pages = [("uru-one-schedule", "Airport"), ("uru2-class-schedule", "Nine Mile"),
             ("uru3-gulf-breeze", "Gulf Breeze")]
    out = []
    for slug, loc in pages:
        r = requests.get(f"https://www.uruyoga.com/full-schedule/{slug}/",
                         headers={"User-Agent": UA["User-Agent"]}, timeout=30)
        r.raise_for_status()
        tables = BeautifulSoup(r.text, "html.parser").find_all(
            "table", class_="mz-schedule-filter")
        if not tables:
            continue
        cur_date = None
        for row in tables[-1].find_all("tr"):
            cls = row.get("class") or []
            cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
            if "header" in cls and cells:
                m = URU_DAY_RE.match(cells[0])
                if m:
                    d = dt.datetime.strptime(
                        f"{m.group(1)} {m.group(2)} {TODAY.year}", "%B %d %Y").date()
                    if d < TODAY - dt.timedelta(days=180):  # year rollover
                        d = d.replace(year=d.year + 1)
                    cur_date = d
            elif "mz_schedule_table" in cls and cur_date and len(cells) >= 3:
                tm = URU_TIME_RE.search(cells[0])
                if not tm or not (START <= cur_date <= END):
                    continue
                hour = int(tm.group(1)) % 12 + (12 if tm.group(3) == "pm" else 0)
                out.append({"date": str(cur_date),
                            "time": f"{hour:02d}:{tm.group(2)}",
                            "name": cells[1],
                            "instructor": f"{cells[2]} · {loc}"})
    return out


def zenplanner(subdomain):
    """Parse Zen Planner weekly LIST view. Fetch two weeks to cover a rolling window."""
    from bs4 import BeautifulSoup
    out, seen = [], set()
    for anchor in (START, START + dt.timedelta(days=7)):
        url = f"https://{subdomain}.sites.zenplanner.com/calendar.cfm"
        r = requests.get(url, params={"DATE": str(anchor), "VIEW": "LIST"},
                         headers={"User-Agent": UA["User-Agent"]}, timeout=30)
        r.raise_for_status()
        lines = [ln.strip() for ln in
                 BeautifulSoup(r.text, "html.parser").get_text("\n", strip=True).split("\n")
                 if ln.strip()]
        cur_date, i = None, 0
        while i < len(lines):
            m = DAY_RE.match(lines[i])
            if m:
                cur_date = dt.datetime.strptime(
                    f"{m.group(2)} {m.group(3)} {m.group(4)}", "%B %d %Y").date()
                i += 1
                continue
            tm = TIME_RE.match(lines[i])
            if tm and cur_date:
                hour = int(tm.group(1)) % 12 + (12 if tm.group(3) == "PM" else 0)
                name = lines[i + 1] if i + 1 < len(lines) else ""
                name = re.sub(r"\s*\(\d+/\d+\)\s*$", "", name).strip()
                instructor, loc = "", ""
                j = i + 2
                if j < len(lines) and not TIME_RE.match(lines[j]) and not DAY_RE.match(lines[j]):
                    if not lines[j].endswith("spots left)"):
                        instructor = lines[j]
                        j += 1
                if j < len(lines) and not TIME_RE.match(lines[j]) and not DAY_RE.match(lines[j]):
                    if not lines[j].endswith("spots left)"):
                        loc = lines[j]
                        j += 1
                if j < len(lines) and lines[j].endswith("spots left)"):
                    j += 1
                i = j
                if any(s in loc for s in SKIP_LOCATIONS):
                    continue
                if not (START <= cur_date <= END):
                    continue
                key = (str(cur_date), hour, tm.group(2), name)
                if key in seen:
                    continue
                seen.add(key)
                out.append({"date": str(cur_date),
                            "time": f"{hour:02d}:{tm.group(2)}",
                            "name": name, "instructor": instructor})
                continue
            i += 1
    return out


STUDIOS = [
    {"name": "Lovelock Healing Arts", "area": "Downtown Pensacola",
     "platform": "Momence", "color": "#B76E79",
     "booking_url": "https://momence.com/u/lovelock-healing-arts-WO7t6K",
     "fetch": lambda: momence("lovelock-healing-arts-WO7t6K", 14136)},
    {"name": "Golden Hour Yoga & Tea House", "area": "East Hill, Pensacola",
     "platform": "Momence", "color": "#D99A3D",
     "booking_url": "https://momence.com/u/golden-hour-yoga-and-tea-house-qDBgJS",
     "fetch": lambda: momence("golden-hour-yoga-and-tea-house-qDBgJS", 123215)},
    {"name": "Disko Lemonade Yoga", "area": "Downtown Pensacola",
     "platform": "fitDEGREE", "color": "#7C6BC4",
     "booking_url": "https://app.fitdegree.com/t/dashboard/fitspot/74",
     "fetch": lambda: fitdegree(74)},
    {"name": "URU Yoga & Beyond", "area": "Pensacola & Gulf Breeze (3 locations)",
     "platform": "Mindbody (via uruyoga.com)", "color": "#3E7CB1",
     "booking_url": "https://clients.mindbodyonline.com/classic/ws?studioid=43474",
     "fetch": uru},
    {"name": "Florida Power Yoga", "area": "N Davis Hwy, Pensacola",
     "platform": "Zen Planner", "color": "#4E8F6B",
     "booking_url": "https://floridapoweryogapensacola.sites.zenplanner.com/calendar.cfm",
     "fetch": lambda: zenplanner("floridapoweryogapensacola")},
]

LINK_ONLY = [
    {"name": "Emerald Coast Yoga & Expressive Arts", "area": "East Hill, Pensacola",
     "platform": "GoDaddy bookings",
     "booking_url": "https://emeraldcoastyoga.org/online-appointments",
     "note": "Schedule sits behind GoDaddy's sign-in booking system — register on their site."},
    {"name": "Seek Yoga", "area": "East Lee St, Pensacola", "platform": "WellnessLiving",
     "booking_url": "https://www.seekyoga.com/seekclasses",
     "note": "Schedule lives in a WellnessLiving widget (signed API) — open their page."},
    {"name": "ChiroYoga Wellness Clinic", "area": "Pensacola Beach", "platform": "Jane App",
     "booking_url": "https://chiroyoga.janeapp.com",
     "note": "Appointment slots rather than a class timetable — book on Jane."},
]


def main():
    result = {"generated_at": dt.datetime.now(TZ).isoformat(timespec="minutes"),
              "week_start": str(START), "week_end": str(END),
              "timezone": "America/Chicago", "studios": [], "link_only": LINK_ONLY}
    failures = 0
    for s in STUDIOS:
        print(f"Fetching {s['name']} ({s['platform']}) ...")
        entry = {k: s[k] for k in ("name", "area", "platform", "color", "booking_url")}
        try:
            classes = sorted(s["fetch"](), key=lambda c: (c["date"], c["time"]))
            entry["classes"] = classes
            entry["error"] = None
            print(f"  ok: {len(classes)} classes")
        except Exception as e:  # noqa: BLE001
            failures += 1
            entry["classes"] = []
            entry["error"] = str(e)[:200]
            print(f"  FAILED: {e}")
        result["studios"].append(entry)
    with open("schedule.json", "w") as f:
        json.dump(result, f, indent=1)
    total = sum(len(s["classes"]) for s in result["studios"])
    print(f"\nWrote schedule.json — {total} classes, {failures} studio failure(s).")
    sys.exit(1 if failures == len(STUDIOS) else 0)


if __name__ == "__main__":
    main()
