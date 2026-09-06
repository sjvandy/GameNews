# GameNews

*(renamed from NintendoBot)*

A Discord bot for a private friends-and-family server. It monitors YouTube,
Instagram, and news sources for Nintendo, PlayStation, and Monster Hunter,
routes new content to each franchise's own channel, and auto-creates Discord
Scheduled Events for Directs/State of Plays and in-game events (Splatfests,
Big Run, Eggstra Work, Monster Hunter events) - announcing each one (tagging
the franchise's role) the moment it's scheduled, auto-starting it, and
pinging again when it goes live.

Each franchise channel posts under its own in-universe reporter persona
(a distinct name + avatar, via a per-channel Discord webhook) rather than
the bot's own generic identity:

| Channel | Reporter |
|---|---|
| Splatoon 3 | **Deep Cut** (Shiver, Frye & Big Man, Splatoon 3's own Anchor news trio) |
| Monster Hunter | **Alma** |
| Legend of Zelda | **Purah** |
| Newsroom (unbranded Nintendo/PlayStation content) | **Kosuke Takagi** (a Mii) |

The bot's own Developer Portal identity ("GameNews") is separate from these
and isn't shown when content posts - see [Reporter personas](#reporter-personas) below.

## Data Sources

| Source | Method | Reliability |
|--------|--------|-------------|
| YouTube (Nintendo / PlayStation / Monster Hunter) | RSS feed (`feedparser`) | High |
| Nintendo News | `__NEXT_DATA__` scraping | Medium-High |
| Instagram | Undocumented web API | Low (may break) |
| Splatoon 3 rotations/Splatfests | [splatoon3.ink](https://splatoon3.ink) community API | High |

## Setup

### 1. Create a Discord Bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **New Application**, give it a name, and create it
3. Go to **Bot** in the sidebar
4. Click **Reset Token** and copy the token
5. Under **Privileged Gateway Intents**, enable **Message Content Intent**
   (needed to read embed URLs from channel history for dedup seeding)
6. Under **Bot > App Icon / Description**, see
   [App identity](#app-identity) below for suggested copy
7. Go to **OAuth2 > URL Generator**
8. Select both the **bot** and **applications.commands** scopes (the second
   is required for `/cleanup` and `/duplicates` to appear as slash commands)
9. Select permissions: **View Channel**, **Send Messages**, **Embed Links**,
   **Read Message History**, **Manage Events**, **Manage Webhooks**,
   **Mention @everyone, @here, and All Roles**
10. Copy the generated URL, open it in your browser, and invite the bot to
    your server (re-invite with this URL even if the bot's already in your
    server, since Discord won't let you add permissions/scopes to an
    existing install without re-authorizing)

### 2. Get Your Server, Channel, and Role IDs

1. In Discord, go to **User Settings > Advanced** and enable **Developer Mode**
2. Right-click your server's name/icon and click **Copy Server ID** (this is `GUILD_ID`)
3. Right-click each franchise channel and click **Copy Channel ID**
4. Right-click each franchise role (in Server Settings > Roles) and click **Copy Role ID**

### 3. Install & Configure

```bash
# Clone and enter the project
cd GameNews

# Create a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies (add -r requirements-dev.txt too if running tests)
pip install -r requirements.txt

# Create your config
cp .env.example .env
```

Edit `.env` and fill in your values (see [Configuration Reference](#configuration-reference)).

Edit `gamenews/franchises.yaml` to set each franchise's real `channel_id` and
`role_id`, and the `media_events.fallback_channel_id` (your `newsroom`
channel) - adding a new franchise only requires a config entry here, no code
change.

### 4. Run

```bash
python bot.py
```

On first run, the bot will:
1. Connect to Discord
2. Import any existing `data/seen_posts.json` into the new SQLite database
   (or, if that file doesn't exist either, scan the fallback/newsroom
   channel's history to avoid reposting content already there)
3. Begin polling content sources on `POLL_INTERVAL_MINUTES`, checking for due
   scheduled events on `EVENT_CHECK_INTERVAL_MINUTES`, and (if Splatoon 3's
   in-game events are enabled) polling splatoon3.ink hourly

### Dry-run / replay tool

To see what the pipeline would generate for a historical YouTube video
(a past Direct, a past event announcement) without touching live Discord
state:

```bash
python -m gamenews.tools.replay <youtube-url-or-video-id>
```

## Cleaning up old, mis-routed, or duplicate posts

Two owner-only commands, each available both as a slash command (`/cleanup`,
`/duplicates` - needs the `applications.commands` scope, see Setup step 8)
and the equivalent `!gamenews <name>` text command. Both always report what
they *would* delete first; nothing is deleted without an explicit confirm,
since message deletion is permanent and there's no automatic/background
cleanup, only these on-demand commands.

**`/cleanup channel:#monster-hunter`** - finds this bot's own messages that
are either older than `MAX_CONTENT_AGE_DAYS`, or - for YouTube-sourced posts
- no longer match the current `franchises.yaml` routing rules (useful after
changing a franchise's keywords, like the Monster Hunter "wilds" filter).

**`/duplicates channel:#newsroom`** - finds repeated posts of the *same*
link in a channel, keeping the oldest copy and flagging every later repost.
This is what you want after switching bots (or after any dedup gap) and
finding the same video posted twice - e.g. once by an earlier bot, once by
this one.

Review the dry-run list, then re-run with confirm checked
(`/cleanup channel:#monster-hunter confirm:True`) or, via text command,
`!gamenews cleanup #monster-hunter true` to actually delete what was found.

## Reporter personas

Each franchise (and the newsroom fallback) has a `reporter_name` and
optional `reporter_avatar_path` in `gamenews/franchises.yaml`. On first use,
the bot creates a webhook in that channel named after the persona; content
posts and live-event pings both go through it, so they show up under that
name/avatar instead of the bot's own.

To add artwork once you've designed it:

1. Drop a square PNG (Discord recommends 512x512, but anything roughly
   square works) into `gamenews/assets/reporters/`, matching the
   `reporter_avatar_path` already set for that franchise (e.g.
   `deep_cut.png`, `alma.png`, `purah.png`, `mii.png`).
2. Restart the bot - it detects the file and updates the webhook's avatar
   automatically. No code change needed.

Until artwork exists, the persona still posts under its name with Discord's
default webhook icon - this is expected, not an error.

Want a banner too? That's a per-server Discord feature (Server Settings >
Overview > Banner), not something a bot or webhook can set - it's a one-time
manual upload whenever you're ready.

## App identity

You decided to keep the Developer Portal application named **GameNews**
rather than giving it its own persona - it still accurately describes what
it does across all these franchises, and is separate from the per-channel
reporter personas above (nobody sees "GameNews" post anything; it's just
the account name in the Portal and the invite flow).

Suggested **About Me** text for **Bot > General Information**:

> Tracks Nintendo, PlayStation, and Monster Hunter news across YouTube,
> Instagram, and official news pages - routes it to the right channel,
> and auto-creates Discord Events for Directs, State of Plays, and
> in-game events like Splatfests and Big Run.

For the app icon: something that reads clearly at a small (Discord shrinks
it to a circle in the member list and DMs) size - a single bold shape or
mark works better than a detailed scene. Since the four reporter personas
already carry the franchise-specific visual identity, the app icon itself
can stay neutral/generic (e.g. a newspaper, a satellite dish, a megaphone)
rather than tied to any one game.

## Configuration Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `DISCORD_TOKEN` | *(required)* | Bot token from Discord Developer Portal |
| `GUILD_ID` | *(required)* | Discord server ID - Scheduled Events are guild-scoped |
| `POLL_INTERVAL_MINUTES` | `15` | How often to check content sources for new items |
| `EVENT_CHECK_INTERVAL_MINUTES` | `2` | How often to check for scheduled events due to auto-start |
| `MAX_CONTENT_AGE_DAYS` | `30` | Content older than this is never posted or turned into an event, even on first sight |
| `NINTENDO_NEWS_URL` | `https://www.nintendo.com/us/whatsnew/` | News page to scrape |
| `FRANCHISES_CONFIG_PATH` | `gamenews/franchises.yaml` | Path to the franchise registry |
| `DB_PATH` | `data/gamenews.sqlite3` | Dedup + event-tracking database |
| `LEGACY_SEEN_POSTS_PATH` | `data/seen_posts.json` | Old flat-JSON dedup file, imported once if present |

## Troubleshooting

- **Bot connects but doesn't post:** Check each franchise's `channel_id` in
  `franchises.yaml` and that the bot has Send Messages + Embed Links
  permissions there.
- **Content posts as "GameNews" instead of the persona name (e.g. Deep Cut):**
  Missing **Manage Webhooks** permission in that channel - the bot falls
  back to posting as itself rather than dropping the item. Re-invite with
  the updated permissions (see Setup step 9).
- **An old/already-over announcement got posted as if new:** Should no
  longer happen - content older than `MAX_CONTENT_AGE_DAYS` is skipped even
  on first sight. If one slipped through before this existed, use
  `/cleanup channel:#channel` to find and remove it.
- **The same video/link got posted twice (e.g. once by an old bot, once by
  this one):** Use `/duplicates channel:#channel` to find and remove the
  repeat, keeping the oldest copy.
- **Slash commands don't show up:** The bot needs the `applications.commands`
  OAuth2 scope (Setup step 8) - re-invite with the updated URL if it was
  invited before that scope was added. After a restart, check the logs for
  `Synced N slash command(s)` to confirm the sync actually ran.
- **Events aren't created:** Confirm the bot has **Manage Events** permission
  and that `GUILD_ID` is correct.
- **Events aren't auto-starting:** Check the logs from the 2-minute event
  check loop; if an event was cancelled by Discord before the bot could start
  it, `EVENT_CHECK_INTERVAL_MINUTES` may be too long relative to how far
  ahead the event was created.
- **Instagram errors (401/403/429):** The undocumented API may be blocked.
  Remove the franchise's `instagram` source from `franchises.yaml`.
- **Nintendo News returns 0 items:** The page structure may have changed.
  Check the logs for warnings.
- **Config error at startup:** `franchises.yaml` failed validation - the
  error names the offending franchise/field directly.
- **Missed content after restart:** Delete `data/gamenews.sqlite3` to
  re-seed (channel-history scanning avoids duplicate reposts on the
  newsroom/fallback channel only).
