# Gulf Coast Yoga Week — project notes for Claude Code

A static dashboard showing this week's classes across Pensacola-area yoga studios.
Built and verified on 2026-07-04 (all four scrapers returned live data: 82 classes).

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

### Link-only studios (intentionally not scraped)
- **Seek Yoga** — WellnessLiving embeds (`k_skin=186912` on seekyoga.com). WL's API
  requires HMAC-signed requests; bundles are obfuscated CloudFront blobs. Not worth it.
- **ChiroYoga** — Jane App (`chiroyoga.janeapp.com`). Jane exposes clean JSON
  (`/api/v2/locations`, `/api/v2/disciplines`, `/api/v2/treatments`) but it's
  appointment *openings*, not a class timetable; their group classes actually run
  inside Lovelock's Momence schedule. Card links out instead.

## Other context worth knowing
- All studios are in **America/Chicago**; the page renders local times and says so.
- goldenhourpensacola.com (the studio's own domain) currently serves gambling spam —
  appears hijacked. Never link it; use the Momence profile URL.
- `fetch_schedules.py` exits 1 only if *all* studios fail, so a single broken
  scraper won't fail the cron run; per-studio errors are written into
  `schedule.json` and rendered as a notice with a fallback link.
- If the user wants more studios later: URU Yoga uses Mindbody (studioid=43474) —
  bot-protected and API is paid; treat as link-only unless that changes.

## Deploy (what the user will ask for)
```bash
git init && git add -A && git commit -m "Yoga week dashboard"
gh repo create yoga-week --public --source . --push
# Enable Pages: Settings → Pages → deploy from branch main, / (root)
```
The included workflow refreshes daily at 11:00 UTC (6am Central) and commits
`schedule.json` when it changes. It needs Settings → Actions → General →
Workflow permissions → "Read and write permissions".
