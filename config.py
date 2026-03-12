import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# API Keys and Tokens
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
YONCTASK_CONFIG_PAGE_ID = os.environ.get("YONCTASK_CONFIG_PAGE_ID", "318e1eb5ce5780c7be3def64930aafbb")
TEST_MONTHLY_PAGE_ID = os.environ.get("TEST_MONTHLY_PAGE_ID", "318e1eb5ce57808ea334c9365174d477")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Notion API common headers
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

# Polling configuration
POLL_INTERVAL_SECONDS = 60
