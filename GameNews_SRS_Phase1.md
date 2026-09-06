# GameNews — Software Requirements Specification
### Phase 1: Live Events & Alerts + Per-Series Content Routing
*(Project renamed from NintendoBot to GameNews)*

---

## 1. Overview

GameNews is a Discord bot for a private friends-and-family server. It currently
monitors Nintendo's YouTube channel, Instagram, and news page, and posts every
item to a single `newsroom` channel. This phase rebuilds that pipeline around
two capabilities:

1. **Live Events & Alerts** — auto-create real Discord Scheduled Events for
   in-game events and Direct/State of Play announcements, auto-start them,
   and ping the right people when they go live.
2. **Per-Series Content Routing** — route content to each game's own channel
   instead of dumping everything into `newsroom`, and expand coverage to
   PlayStation and Monster Hunter sources.

This is the phase-1 slice of a larger roadmap. Two adjacent tentpoles —
self-service channel/role creation, and Claude Haiku–powered features
(summaries, chat, personas) — are **explicitly out of scope** for this phase
(see §2.2) but this design should not make them harder to add later.

## 2. Scope

### 2.1 In scope
- Rename the project from NintendoBot to **GameNews**.
- Config-driven franchise registry (no hardcoded per-game logic in the poller).
- New content sources: official PlayStation YouTube channel, official
  Monster Hunter YouTube channel.
- Per-franchise content routing (YouTube, Instagram, news) to each game's
  Discord channel instead of a single shared `newsroom`.
- Detection and Discord Event creation for:
  - **In-game events** (Splatfests, Monster Hunter in-game events, and
    similar limited-time in-game content changes)
  - **Media events** (Nintendo Direct, PlayStation State of Play, including
    franchise-branded Directs like a "Legend of Zelda Direct")
- Auto-starting created events at their scheduled time.
- Pinging the existing franchise role for a channel when its event starts.
- A **dry-run / replay tool** Steven can run against an old YouTube video or
  Direct to see what the pipeline would generate, without touching live
  Discord state.
- An automated test suite covering everything that doesn't require a live
  Discord server, plus a documented manual checklist for what does.

### 2.2 Out of scope (do not build in this phase)
- Self-service channel creation via slash command + reaction-based auto-join
  (deferred tentpole).
- Any Claude Haiku / LLM feature: summaries, Q&A, personas, AI-assisted
  classification (deferred tentpole).
- Building new franchise roles — **the roles already exist**; this phase only
  needs to reference their IDs.

## 3. Rename: NintendoBot → GameNews

- Update repo/package name, README title, log format strings, and any
  in-code references to "NintendoBot."
- The Discord Application's bot username (Discord Developer Portal) is
  separate from the codebase — renaming it there is a manual step for
  Steven, not something in code.
- Update the bot's OAuth2 invite instructions in the README once new
  permissions are added (§7.1).

## 4. Current system summary (context for implementation)

- `bot.py`: single `discord.Client`, one `CHANNEL_ID`, polls
  `youtube.fetch()`, `nintendo_news.fetch()`, `instagram.fetch()` every
  `POLL_INTERVAL_MINUTES` via `tasks.loop`.
- `sources/`: one module per source, each returning a list of `ContentItem`.
- Dedup state: flat JSON file (`seen_posts.json`) of seen `unique_id`s.
- No command framework, no per-channel logic, no database.

This phase requires moving from a bare `discord.Client` to
`commands.Bot` (Cogs), and from a flat JSON file to a small SQLite database.

## 5. Functional requirements

### FR-1: Config-driven franchise registry
A config file (see §6) defines each franchise: its Discord channel, its
existing role, its content sources, and its event-detection keywords. Adding
a new franchise should require only a config change, no code change.

### FR-2: Per-series content routing
- Each franchise's sources feed only that franchise's channel.
- `newsroom` becomes the fallback for Nintendo/PlayStation content that
  doesn't match any franchise's keywords — not the default destination.
- A YouTube video whose title matches a franchise's keywords (e.g. a
  Splatoon 3 DLC trailer) routes to that franchise's channel even though it
  came from Nintendo's general YouTube feed.

### FR-3: New content sources
- Add the official **PlayStation** YouTube channel
  (`UC-2Y8dQb0S6DtpxNgAKoJKA`) as a source, primarily for State of Play
  coverage.
- Add the official **Monster Hunter** YouTube channel
  (`UCVS0xBpOtXBAl12rdG67-OQ`) as a source for the `monster-hunters` channel.
  ⚠️ See §8 — Capcom does not appear to run a channel specific to *Monster
  Hunter Wilds*; this is the general Monster Hunter channel covering all
  titles.

### FR-4: In-game event detection & Discord Event creation
- Applies to franchises flagged `enable_ingame_events: true` (initially
  Splatoon 3 and Monster Hunter — see §8 on Zelda).
- A content item matching a franchise's `event_keywords` (e.g. "Splatfest",
  "event quest") triggers creation of a Discord Scheduled Event:
  - `entity_type = EXTERNAL`, with a `location` string (Discord requires one
    for external events) and both start and end time.
  - Cover image sourced from the item's thumbnail/`og:image`.
  - If a start or end time can't be confidently parsed from the source
    content, **do not create a malformed event** — log it and skip, rather
    than guess (see §8).

### FR-5: Media event detection & Discord Event creation
- Detects Nintendo Direct / PlayStation State of Play announcements from the
  Nintendo and PlayStation YouTube/news sources.
- If the Direct is franchise-branded (title contains e.g. "Zelda Direct"),
  tag it with that franchise so its role also gets pinged in addition to the
  general media-event notification.
- Same event-creation mechanics as FR-4.

### FR-6: Event auto-start
- Discord does **not** auto-activate `SCHEDULED` events, and will
  auto-**cancel** one left in `SCHEDULED` status too long past its start
  time. A recurring check (finer-grained than the 15-minute content poll —
  proposed every 1–5 minutes) must flip status to `ACTIVE` at start time.

### FR-7: Franchise role notification
- Each existing franchise role is referenced by ID in config (§6) — this
  phase does not create roles.
- When an event transitions to `ACTIVE`, the bot posts a message in that
  franchise's channel `@mentioning` its role.
- Idempotency: an event already `ACTIVE` or `COMPLETED` must not be
  re-started or re-pinged.

### FR-8: Dry-run / replay tool
- A CLI command (e.g. `python -m gamenews.tools.replay <url>`) that runs a
  historical YouTube video or Direct URL through the full parsing →
  classification → event-field-generation pipeline and prints the result
  (target channel, generated event name/description/start/end/cover image)
  **without calling any live Discord API**.
- Doubles as the mechanism for fixture-based regression tests (§9.2).

## 6. Data model / configuration schema

Proposed `franchises.yaml` (illustrative — adjust field names to taste):

```yaml
franchises:
  - key: splatoon-3
    display_name: "Splatoon 3"
    channel_id: 000000000000000000   # TODO: fill in
    role_id: 000000000000000000      # TODO: fill in (existing role)
    enable_ingame_events: true
    event_keywords: ["splatfest", "big run", "eggstra work", "in-game event"]
    sources:
      - {type: youtube, channel_id: "UCGIY_O-8vW4rfX98KlMkvRg", title_keywords: ["splatoon"]}
      - {type: instagram, username: "nintendoamerica", title_keywords: ["splatoon"]}
      - {type: news, title_keywords: ["splatoon"]}

  - key: monster-hunters
    display_name: "Monster Hunter"
    channel_id: 000000000000000000
    role_id: 000000000000000000
    enable_ingame_events: true
    event_keywords: ["event quest", "collaboration", "limited-time"]
    sources:
      - {type: youtube, channel_id: "UCVS0xBpOtXBAl12rdG67-OQ", title_keywords: ["wilds"]}

  - key: legend-of-zelda
    display_name: "Legend of Zelda"
    channel_id: 000000000000000000
    role_id: 000000000000000000
    enable_ingame_events: false      # see §8
    sources:
      - {type: news, title_keywords: ["zelda"]}
      - {type: youtube, channel_id: "UCGIY_O-8vW4rfX98KlMkvRg", title_keywords: ["zelda"]}

media_events:
  fallback_channel_id: 000000000000000000   # newsroom, unless a dedicated Directs channel is wanted
  sources:
    - {type: youtube, channel_id: "UCGIY_O-8vW4rfX98KlMkvRg", title_keywords: ["nintendo direct"]}
    - {type: youtube, channel_id: "UC-2Y8dQb0S6DtpxNgAKoJKA", title_keywords: ["state of play"]}
  franchise_branding_keywords:
    splatoon-3: ["splatoon direct"]
    monster-hunters: ["monster hunter direct"]
    legend-of-zelda: ["zelda direct"]
```

Also needed: a small SQLite schema for seen-content dedup (replacing the flat
JSON file) and tracked-event state (event ID, guild event ID, status, franchise).

## 7. Non-functional requirements

### 7.1 Permissions
- Bot needs `MANAGE_EVENTS` added in the Discord Developer Portal (current
  scope only has Send Messages + Embed Links).
- Confirm the bot can `@mention` the existing franchise roles in their
  channels (via the role's mentionable setting or the bot's own mention
  permission) — flagged as a **setup checklist item**, not something code
  can guarantee on its own.

### 7.2 Reliability
- Source fetch failures must not block other sources (existing
  `asyncio.gather(..., return_exceptions=True)` pattern should carry over).
- Event-state tracking must survive a bot restart (hence SQLite, not
  in-memory).

### 7.3 Extensibility
- Adding a franchise = adding a config entry, not touching routing/event code.

## 8. Assumptions & open questions

Flagging these explicitly rather than guessing silently — worth a quick
confirm before/while Claude Code builds:

- **Zelda + in-game events**: Zelda is mostly single-player and doesn't have
  live-service-style limited-time events the way Splatoon/Monster Hunter do,
  so `enable_ingame_events: false` is the default here. Branded Directs
  still apply to Zelda via FR-5 regardless.
- **Monster Hunter Wilds channel**: no separate Wilds-only YouTube channel
  appears to exist — the config above uses the general Monster Hunter
  channel with an optional `"wilds"` title filter. Let me know if you'd
  rather ingest *all* Monster Hunter content instead of filtering to Wilds.
- **Unparseable event dates**: since event creation is fully automatic
  (no approval step), the safest default is to skip auto-creation and log
  a flagged item when a start/end time can't be confidently parsed, rather
  than create a malformed public event. Worth confirming this is the
  behavior you want.
- **Directs channel**: still open whether Directs get a dedicated channel
  or fall back to `newsroom`/franchise channels per FR-5 — config above
  defaults to the fallback-channel approach.

## 9. Test plan

### 9.1 Automated unit tests (no live Discord required)

| ID | Description | Input | Expected result |
|----|--------------|-------|------------------|
| TC-1 | Franchise keyword match | Video title "Splatoon 3 Side Order DLC Trailer" | Routes to `splatoon-3` |
| TC-2 | No keyword match | Video title "Super Mario Kart World amiibo unboxing" | Falls back to `newsroom` |
| TC-3 | Valid in-game event → payload | Announcement with clear dates for a Splatfest | Generates a valid `EXTERNAL` event payload: name, location, start/end time, cover image present |
| TC-4 | Unparseable event dates | Announcement text with no clear start/end date | No event created; item logged as flagged, not silently guessed |
| TC-5 | Branded Direct detection | Title "The Legend of Zelda Direct — 9.4.2026" | Classified as media event AND tagged franchise `legend-of-zelda` |
| TC-6 | Scheduler starts due event (mocked Discord) | Tracked event with `status=SCHEDULED`, `start_time <= now` | `event.start()` called once; role-ping message sent |
| TC-7 | Idempotency | Tracked event with `status=ACTIVE` | `event.start()` NOT called again; no duplicate ping |
| TC-8 | Config loader validation | Franchise entry missing `role_id` | Raises a clear config error at startup, not a silent `None` |

### 9.2 Fixture-based regression tests (via the FR-8 replay tool)

- Curate 3–5 historical URLs (a past Splatfest announcement, a past Monster
  Hunter event, a past Nintendo Direct) as fixtures.
- Run each through the replay tool, review the output once, and save it as
  the expected reference.
- Regression test asserts future pipeline changes still produce matching
  output for these fixtures (catches accidental breakage from refactors).

### 9.3 Manual verification checklist (requires a live Discord server)

- [ ] A created event's cover image actually renders correctly in Discord's UI (aspect ratio/sizing).
- [ ] An event created well ahead of its start time does **not** get auto-cancelled by Discord before the bot flips it to `ACTIVE`.
- [ ] The role ping at event-start actually notifies members of that role.
- [ ] A real new franchise-specific trailer posts to the correct channel end-to-end, not `newsroom`.
- [ ] A real Direct/State of Play creates its event and pings correctly, including a branded Direct pinging the extra franchise role.

## 10. Definition of done

- [ ] Project renamed to GameNews across code, README, and config.
- [ ] Franchise registry is config-driven; adding a franchise requires no code change.
- [ ] PlayStation and Monster Hunter sources are live and routing correctly.
- [ ] In-game events and media events both create, auto-start, and ping correctly.
- [ ] Replay tool exists and produces inspectable output for a historical URL.
- [ ] All TC-1 through TC-8 automated tests pass in CI.
- [ ] Manual checklist (§9.3) completed once in `bot-testing` before going live in real channels.
