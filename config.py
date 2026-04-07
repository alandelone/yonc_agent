import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# API Keys and Tokens
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
YONCTASK_CONFIG_PAGE_ID = os.environ.get("YONCTASK_CONFIG_PAGE_ID", "318e1eb5ce5780c7be3def64930aafbb")
DFORGE_LINESV2_PAGE_ID = os.environ.get("DFORGE_LINESV2_PAGE_ID", "318e1eb5ce57808ea334c9365174d477")
TIMELINER_PAGE_ID = os.environ.get("TIMELINER_PAGE_ID", "318e1eb5ce57808ea334c9365174d477")
LIVETODAY_PAGE_ID = os.environ.get("LIVETODAY_PAGE_ID", "33ae1eb5ce578083bffad43328863da6")
# Notion API common headers
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

# Polling configuration
POLL_INTERVAL_SECONDS = 60
