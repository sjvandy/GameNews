import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
POLL_INTERVAL_MINUTES = int(os.getenv("POLL_INTERVAL_MINUTES", "15"))

YOUTUBE_CHANNEL_ID = os.getenv(
    "YOUTUBE_CHANNEL_ID", "UCGIY_O-8vW4rfX98KlMkvRg"
)
YOUTUBE_RSS_URL = (
    f"https://www.youtube.com/feeds/videos.xml?channel_id={YOUTUBE_CHANNEL_ID}"
)

NINTENDO_NEWS_URL = os.getenv(
    "NINTENDO_NEWS_URL", "https://www.nintendo.com/us/whatsnew/"
)

ENABLE_INSTAGRAM = os.getenv("ENABLE_INSTAGRAM", "true").lower() == "true"
INSTAGRAM_USERNAME = os.getenv("INSTAGRAM_USERNAME", "nintendoamerica")

SEEN_POSTS_PATH = os.getenv("SEEN_POSTS_PATH", "data/seen_posts.json")
