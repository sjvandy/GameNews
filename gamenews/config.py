import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))

POLL_INTERVAL_MINUTES = int(os.getenv("POLL_INTERVAL_MINUTES", "15"))
EVENT_CHECK_INTERVAL_MINUTES = int(os.getenv("EVENT_CHECK_INTERVAL_MINUTES", "2"))

# Content older than this is never posted or turned into an event candidate,
# even the first time it's seen (e.g. an old video still sitting in a
# channel's last-15-items RSS window). Prevents "new" notifications for
# things that are actually long over.
MAX_CONTENT_AGE_DAYS = int(os.getenv("MAX_CONTENT_AGE_DAYS", "30"))

NINTENDO_NEWS_URL = os.getenv(
    "NINTENDO_NEWS_URL", "https://www.nintendo.com/us/whatsnew/"
)

FRANCHISES_CONFIG_PATH = os.getenv("FRANCHISES_CONFIG_PATH", "gamenews/franchises.yaml")

DB_PATH = os.getenv("DB_PATH", "data/gamenews.sqlite3")
LEGACY_SEEN_POSTS_PATH = os.getenv("LEGACY_SEEN_POSTS_PATH", "data/seen_posts.json")
