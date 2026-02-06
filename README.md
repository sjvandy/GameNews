# NintendoBot

A Discord bot that monitors Nintendo's YouTube, Instagram, and news page for new content and posts formatted embeds to a Discord channel.

## Data Sources

| Source | Method | Reliability |
|--------|--------|-------------|
| YouTube | RSS feed (`feedparser`) | High |
| Nintendo News | `__NEXT_DATA__` scraping | Medium-High |
| Instagram | Undocumented web API | Low (may break) |

## Setup

### 1. Create a Discord Bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **New Application**, give it a name, and create it
3. Go to **Bot** in the sidebar
4. Click **Reset Token** and copy the token
5. Under **Privileged Gateway Intents**, no special intents are required
6. Go to **OAuth2 > URL Generator**
7. Select the **bot** scope
8. Select permissions: **Send Messages**, **Embed Links**
9. Copy the generated URL, open it in your browser, and invite the bot to your server

### 2. Get Your Channel ID

1. In Discord, go to **User Settings > Advanced** and enable **Developer Mode**
2. Right-click the channel you want the bot to post in
3. Click **Copy Channel ID**

### 3. Install & Configure

```bash
# Clone and enter the project
cd NintendoBot

# Create a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create your config
cp .env.example .env
```

Edit `.env` and fill in your values:
```
DISCORD_TOKEN=your-bot-token-here
CHANNEL_ID=123456789012345678
```

### 4. Run

```bash
python bot.py
```

On first run, the bot will:
1. Connect to Discord
2. Fetch all sources and **seed** existing content (no messages sent)
3. Create `data/seen_posts.json` with the seeded IDs
4. Begin polling on the configured interval

After that, only genuinely new content triggers Discord messages.

## Configuration Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `DISCORD_TOKEN` | *(required)* | Bot token from Discord Developer Portal |
| `CHANNEL_ID` | *(required)* | Discord channel ID to post in |
| `POLL_INTERVAL_MINUTES` | `15` | How often to check for new content |
| `YOUTUBE_CHANNEL_ID` | `UCGIY_O-8vW4rfX98KlMkvRg` | Nintendo's YouTube channel ID |
| `NINTENDO_NEWS_URL` | `https://www.nintendo.com/us/whatsnew/` | News page to scrape |
| `ENABLE_INSTAGRAM` | `true` | Set to `false` to disable the fragile Instagram source |
| `INSTAGRAM_USERNAME` | `nintendoamerica` | Instagram account to monitor |
| `SEEN_POSTS_PATH` | `data/seen_posts.json` | Path to the dedup state file |

## Troubleshooting

- **Bot connects but doesn't post:** Check that `CHANNEL_ID` is correct and the bot has Send Messages + Embed Links permissions in that channel.
- **Instagram errors (401/403/429):** The undocumented API may be blocked. Set `ENABLE_INSTAGRAM=false` in `.env`.
- **Nintendo News returns 0 items:** The page structure may have changed. Check the logs for warnings.
- **Missed content after restart:** Delete `data/seen_posts.json` to re-seed (no duplicates will be posted on the seed run).
- **Testing quickly:** Set `POLL_INTERVAL_MINUTES=1` in `.env`, then delete a few IDs from `data/seen_posts.json` and restart.
