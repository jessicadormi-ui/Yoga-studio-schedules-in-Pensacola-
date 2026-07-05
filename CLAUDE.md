# Gulf Coast Yoga Week — project notes for Claude Code

A static dashboard showing this week's classes across Pensacola-area yoga and
pilates studios.
Built and verified on 2026-07-04 (yoga scrapers returned live data: 82 classes);
Wild Lemon Pilates (Momence) added 2026-07-05.

## Discipline tagging
Every class carries a `discipline` field — `yoga`, `pilates`, or `other` —
set by `classify_discipline()` in `fetch_schedules.py`. It keyword-matches the
class name (pilates terms checked first), and only UNAMBIGUOUS words are in the
keyword lists; ambiguous ones (flow, sculpt, power, barre…) are left out so they
fall back to the studio's own `discipline` default. Each studio dict therefore
has a `discipline` key (its default). Net effect: a class named "Reformer" at any
studio is pilates, "Vinyasa" is yoga, and an unlabeled class inherits the
studio's default (so everything at a pilates studio reads pilates unless the name
says otherwise). `index.html` renders a "Class type" filter row (shown only when
>1 discipline is present) alongside the studio pills.

## Files
- `fetch_schedules.py` — pulls a rolling 7-day window into `schedule.json`. No API keys. Deps: `requests`, `beautifulsoup4`.
- `index.html` — static page that fetches `schedule.json` and renders a weekly grid. No build step, no framework.
- `.github/workflows/refresh.yml` — ready-made daily refresh Action (see Deploy).

## The user's goal
Host this as a free, self-refreshing website (GitHub Pages + scheduled Action).
When asked to deploy: create a public repo, enable Pages (deploy from branch, root),
push, and confirm the Action has `contents: write` permission so it can commit
the refreshed `schedule.json`.

## How each scraper works (and how to fix it when it breaks)

### Momence — Lovelock Healing Arts (host 14136) & Golden Hour (host 123215)
Public, unauthenticated, JSON:
1. Resolve page slug → hostId:
   `GET https://readonly-api.momence.com/schedule/GetLatestStandalone?hostUrl={slug}&timezoneOffset=0&excludeCollections=true`
   → `message.info.hostId`. (Slugs: `lovelock-healing-arts-WO7t6K`, `golden-hour-yoga-and-tea-house-qDBgJS`.)
2. `GET https://readonly-api.momence.com/host-plugins/host/{hostId}/host-schedule/sessions?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD&pageSize=500`
   → `payload[]` with `sessionName`, `startsAt` (UTC ISO), `teacher` (plain string), `isCancelled`.
These routes were mined from `https://momence.com/plugin/host-schedule/host-schedule.js`
and the host-landing bundle at `static.momence.com/host-landing/static/js/main.*.chunk.js` —
re-mine those bundles if routes 404 someday.

### Momence — Wild Lemon Pilates (host 42021: Scott St / 12th Ave / Gulf Breeze)
One Momence host serves all three physical studios; the sessions feed carries a
per-session `location` string. `momence()` takes two optional args for this:
`location_filter` (keep only sessions whose `location` contains the substring —
`"Scott St"`, `"12th Ave"`, `"Gulf Breeze"`) and `strip_prefix` (session names are
prefixed `"Scott St • Reformer"`, so drop everything up to the `•` for a clean
pill). Slug `wild-lemon-qXgxVr` → hostId 42021. Each location is its own studio
entry/pill (URU-style: three entries, one source). Verified 2026-07-05.

### fitDEGREE — Disko Lemonade Yoga (fitspot_id 74)
Public, unauthenticated:
`GET https://api.fitdegree.com/class-session/?fitspot_id=74&event_datetime__GTE=YYYY-MM-DD HH:MM:SS&event_datetime__LTE=...`
→ `response.data.items[]` with `class_title`, `instructor_first_name/last_name`,
`is_cancelled`, `event_datetime` (UTC) and `fs_event_datetime` (**studio-local — use this**).
Gotchas: the trailing slash matters (`/class-session` without it = "Endpoint not found");
Django-style `__GTE/__LTE` filters; without them it dumps ~10k historical rows.
Endpoint names came from `api_endpoint="..."` strings in
`https://widget.fitdegree.com/{version}/main.*.js` (check `<base href>` for the version path).

### Zen Planner — Florida Power Yoga
No JSON; the list view is clean HTML:
`GET https://floridapoweryogapensacola.sites.zenplanner.com/calendar.cfm?DATE=YYYY-MM-DD&VIEW=LIST`
shows the full calendar week containing DATE, so the script fetches two anchors
(today and today+7) and de-dupes. Parsed from the text as repeating
[time, title, instructor, location] runs under "Weekday, Month D, YYYY" headers.
Titles may carry a "(0/45)" suffix (stripped); "(N spots left)" lines are skipped;
locations containing Remote/Virtual/"Coming Soon" are filtered out
(they list other/planned locations in the same calendar).

### URU (3 studio entries: Airport / Nine Mile / Gulf Breeze) — Mindbody, scraped via their own website
Each location is its own studio entry/pill on the dashboard.
Mindbody's API is paid/bot-protected, BUT uruyoga.com server-renders the full
Mindbody schedule as plain HTML. Three location pages, each covering a rolling
week starting today:
`https://www.uruyoga.com/full-schedule/{uru-one-schedule|uru2-class-schedule|uru3-gulf-breeze}/`
Parse the LAST `table.mz-schedule-filter` on each page (the first is a grid view):
rows with class `header` carry the date ("Saturday, July 4" — no year, so infer
year with a rollover check); rows with class `mz_schedule_table` carry
[time range, class name, instructor]. If this breaks, check whether their site still embeds the "mz" (healcode/Mindbody)
widget server-side; if they switch to the JS widget, URU becomes link-only.

### Emerald Coast Yoga — recurring schedule parsed from prose
Their live calendar/booking (GoDaddy Websites+Marketing) is JS-rendered behind a
lazy-loaded widget with no reachable public API. Instead, `emerald_coast()` parses
the advertised weekly schedule from the prose on https://emeraldcoastyoga.org/classes
(h4 titles + "5:30-6:30 pm - Tuesdays" style text; sections are duplicated for
responsive layouts, so times pair with nearby day words and titles are corrected
by word overlap). IMPORTANT: these entries are the published recurring schedule,
not live availability — one-off cancellations won't show. If their prose format
changes and parsing yields odd results, demote ECY to a link-only card.

### Link-only studios (intentionally not scraped)
- **Seek Yoga** — WellnessLiving embeds (`k_skin=186912` on seekyoga.com). WL's API
  requires HMAC-signed requests; bundles are obfuscated CloudFront blobs. Not worth it.
- **ChiroYoga** — Jane App (`chiroyoga.janeapp.com`). Jane exposes clean JSON
  (`/api/v2/locations`, `/api/v2/disciplines`, `/api/v2/treatments`) but it's
  appointment *openings*, not a class timetable; their group classes actually run
  inside Lovelock's Momence schedule. Card links out instead.
- **The Gadsden Studio** (pilates) — 1300 E Gadsden St. Booking is an **Arketa**
  (Sutra) React SPA embedded client-side (iframe
  `app.arketa.co/iframe/thegadsdenstudio/schedule`). No server-rendered HTML and
  no public GET feed: the public schedule reads the Firestore `classes` collection
  directly via the Firebase JS SDK (project `sutra-prod`, anonymous auth), and
  Arketa's documented Partner API (`us-central1-sutra-prod.cloudfunctions.net/partnerApi/v0`,
  `GET /{partnerId}/classes`) requires the studio's own API key. Reverse-engineering
  the anon-auth Firestore query would be brittle (same call we made for Seek Yoga),
  so it's link-only. To make it live later: get an Arketa Partner API key from the
  studio, or capture the widget's live XHR (`widget-api-tkaeguucxq-uc.a.run.app`) in
  a real browser.
- **Pure Pilates** (pilates; Downtown 426 S Palafox + Gulf Breeze 221 Gulf Breeze
  Pkwy) — **WellnessLiving** (business `k_business=252337`), the same platform as
  Seek Yoga: JS-only widget, no server-rendered schedule, signed API. Link-only for
  the same reason. NOTE: only **two** real locations exist — the "third" seen in
  WellnessLiving's directory is an auto-generated duplicate stub, not a studio.

## Other context worth knowing
- All studios are in **America/Chicago**; the page renders local times and says so.
- goldenhourpensacola.com (the studio's own domain) currently serves gambling spam —
  appears hijacked. Never link it; use the Momence profile URL.
- `fetch_schedules.py` exits 1 only if *all* studios fail, so a single broken
  scraper won't fail the cron run; per-studio errors are written into
  `schedule.json` and rendered as a notice with a fallback link.

## Deploy (what the user will ask for)
```bash
git init && git add -A && git commit -m "Yoga week dashboard"
gh repo create yoga-week --public --source . --push
# Enable Pages: Settings → Pages → deploy from branch main, / (root)
```
The included workflow refreshes daily at 11:00 UTC (6am Central) and commits
`schedule.json` when it changes. It needs Settings → Actions → General →
Workflow permissions → "Read and write permissions".
