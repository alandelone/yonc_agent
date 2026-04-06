import re
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from datetime import datetime

from notion_client import get_page_blocks
from config_reader import parse_rich_text
from config import TIMELINER_PAGE_ID

@dataclass
class TimelineEntry:
    block_id: str
    project: str
    subproject: str
    colour_subtheme: str
    status_emoji: str
    settle_date: str # ISO 8601 (YYYY-MM-DD)
    time_expected_h: Optional[float]
    percent: int
    remaining_work_days: Optional[int]
    raw_text: str

# 🟢**{colour_subtheme}** Takes `🏁dates h`{time_expected}  ||{percent}% Settle by March 30, 2026, but 🔜 {remaining_work_days}
TIMELINER_PATTERN = re.compile(
    r"^(?P<status>[🟢🔴🔥])\s*"                         
    r"\*?\*?(?P<subtheme>.+?)\*?\*?\s+"              
    r"Takes\s+`?🏁[^`\d]*`?\s*"                              
    r"(?P<time_h>[\d.]+)?\s*"                            
    r"\|\|\s*(?P<percent>\d+)%\s*"                       
    r"Settle\s+by\s+(?P<date>[A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?,\s+\d{4})"  
    r"(?:,?\s*but\s+🔜\s*(?P<remaining>\d+))?"          
)

def parse_date_to_iso(date_str: str) -> str:
    """Convert 'March 30, 2026' to '2026-03-30'."""
    # Remove ordinal suffixes if any
    clean_date = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', date_str)
    try:
        dt = datetime.strptime(clean_date, "%B %d, %Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        try:
            # fallback for short month maybe?
            dt = datetime.strptime(clean_date, "%b %d, %Y")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            return "" # Could not parse

def parse_timeliner_blocks(blocks: List[Dict[str, Any]]) -> List[TimelineEntry]:
    entries = []
    current_project = ""
    current_subproject = ""
    
    for block in blocks:
        b_type = block.get("type", "")
        b_id = block.get("id", "")
        
        # Heading 2 -> Main Project
        if b_type == "heading_2":
            rt = block.get("heading_2", {}).get("rich_text", [])
            current_project = parse_rich_text(rt).strip()
            current_subproject = "" # Reset subproject
            
        # Heading 3 -> Sub Project
        elif b_type == "heading_3":
            rt = block.get("heading_3", {}).get("rich_text", [])
            current_subproject = parse_rich_text(rt).strip()
            
        # Bulleted list item or paragraph -> Timeline entry
        elif b_type in ["bulleted_list_item", "paragraph"]:
            rt = block.get(b_type, {}).get("rich_text", [])
            raw_text = parse_rich_text(rt).strip()
            
            if not raw_text:
                continue
                
            match = TIMELINER_PATTERN.search(raw_text)
            if match:
                data = match.groupdict()
                
                time_h = data.get("time_h")
                remaining = data.get("remaining")
                
                entry = TimelineEntry(
                    block_id=b_id,
                    project=current_project,
                    subproject=current_subproject,
                    colour_subtheme=data["subtheme"].strip(),
                    status_emoji=data["status"],
                    settle_date=parse_date_to_iso(data["date"].strip()),
                    time_expected_h=float(time_h) if time_h else None,
                    percent=int(data["percent"]),
                    remaining_work_days=int(remaining) if remaining else None,
                    raw_text=raw_text
                )
                entries.append(entry)
                
    return entries

def fetch_and_parse_timeliner() -> List[TimelineEntry]:
    """Fetch the page and parse it into TimelineEntry objects."""
    blocks = get_page_blocks(TIMELINER_PAGE_ID)
    return parse_timeliner_blocks(blocks)
