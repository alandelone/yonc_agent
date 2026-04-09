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
    settle_date: str  # ISO 8601 (YYYY-MM-DD)
    time_expected_h: Optional[float]
    percent: int
    remaining_work_days: Optional[int]
    raw_text: str
    in_heading_scope: bool = False


# Supports settle dates in both long form and ISO form.
TIMELINER_PATTERN = re.compile(
    r"^(?P<prefix>.*?)\s+"
    r"Takes\s+(?P<takes_seg>.*?)\s*"
    r"\|\|\s*(?P<percent>\d*)%\s*"
    r"Settle\s+by\s+(?P<date>@?\d{4}-\d{2}-\d{2}|@?[A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?,\s+\d{4})"
    r"(?:,?\s*but\s+\S+\s*(?P<remaining>\d+))?",
    re.IGNORECASE,
)


def _detect_section_kind(text: str) -> Optional[str]:
    """
    Detect whether a heading text is a section marker for main/sub projects.
    Returns: "main", "sub", or None
    """
    normalized = re.sub(r"[\s_\-]+", "", (text or "").strip().lower())
    if not normalized:
        return None

    if normalized in {"mainprojects", "mainproject"}:
        return "main"
    if normalized in {"subprojects", "subproject"}:
        return "sub"
    return None


def _clean_subtheme_label(raw: str) -> str:
    txt = (raw or "").strip()
    # Remove leading group/theme label fragments that should not be part of subtheme.
    txt = re.sub(r"^\*{1,2}`([^`]+)`\*{1,2}\s*", r"\1 ", txt).strip()
    txt = re.sub(r"^`[^`]+`\s*", "", txt)
    txt = re.sub(r"^\S+\s+(?:m?ain|ain|sub)\s+projects?\s+", "", txt, flags=re.IGNORECASE)
    txt = re.sub(r"^(?:m?ain|ain|sub)\s+projects?\s+", "", txt, flags=re.IGNORECASE)

    txt = txt.strip("`").strip()
    # Support **subtheme** / *subtheme* wrappers around the final value.
    txt = re.sub(r"^\*{1,2}(.*?)\*{1,2}$", r"\1", txt).strip()
    return txt


def _extract_time_expected_h(takes_segment: str) -> Optional[float]:
    seg = (takes_segment or "").strip()
    if not seg:
        return None

    # Prefer h{number} / h {number}.
    m = re.search(r"h\s*(\d+(?:\.\d+)?)", seg, flags=re.IGNORECASE)
    if not m:
        # Fallback: first standalone number in the segment.
        m = re.search(r"(\d+(?:\.\d+)?)", seg)
    if not m:
        return None

    try:
        return float(m.group(1))
    except (TypeError, ValueError):
        return None


def _split_leading_label(text: str) -> tuple[str, str]:
    """
    Split "<label> <rest>" into (label, rest). If no split is possible, return ("", text).
    """
    txt = (text or "").strip()
    if not txt:
        return "", ""
    parts = txt.split(None, 1)
    if len(parts) == 2 and parts[0] and parts[1]:
        return parts[0].strip(), parts[1].strip()
    return "", txt


def _parse_prefix(prefix: str) -> tuple[str, str]:
    txt = (prefix or "").strip()
    status = "🟢"

    # If the line starts like "<status>**...**", peel status by marker position.
    bold_idx = txt.find("**")
    if bold_idx in (1, 2):
        extracted = txt[:bold_idx].strip()
        if extracted:
            status = extracted
        txt = txt[bold_idx:].strip()

    # Most lines start with a status emoji/symbol.
    elif txt and re.match(r"^[^\w\s`*]", txt):
        status = txt[0]
        txt = txt[1:].strip()

    subtheme = _clean_subtheme_label(txt)
    return status, subtheme


def parse_date_to_iso(date_str: str) -> str:
    """Convert a supported date string to ISO 8601 (YYYY-MM-DD)."""
    clean_date = date_str.strip().lstrip("@")

    # Already ISO.
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", clean_date):
        return clean_date

    # Remove ordinal suffixes if any.
    clean_date = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", clean_date, flags=re.IGNORECASE)

    try:
        dt = datetime.strptime(clean_date, "%B %d, %Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        try:
            dt = datetime.strptime(clean_date, "%b %d, %Y")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            return ""


def parse_timeliner_blocks(blocks: List[Dict[str, Any]]) -> List[TimelineEntry]:
    entries: List[TimelineEntry] = []

    entry_block_types = {"bulleted_list_item", "paragraph", "numbered_list_item", "to_do", "toggle"}

    def _block_text(block: Dict[str, Any], b_type: str) -> str:
        rt = block.get(b_type, {}).get("rich_text", [])
        return parse_rich_text(rt).strip()

    def walk(
        current_blocks: List[Dict[str, Any]],
        project: str,
        subproject: str,
        depth: int = 0,
        section_kind: Optional[str] = None,
        has_heading_context: bool = False,
    ) -> None:
        current_project = project
        current_subproject = subproject
        current_section_kind = section_kind
        current_has_heading_context = has_heading_context

        for block in current_blocks:
            b_type = block.get("type", "")
            b_id = block.get("id", "")

            # Heading 1 -> Main Project
            if b_type == "heading_1":
                current_has_heading_context = True
                heading_text = _block_text(block, "heading_1")
                detected = _detect_section_kind(heading_text)
                if detected:
                    current_section_kind = detected
                    if detected == "sub":
                        current_subproject = ""
                else:
                    current_project = heading_text
                    current_subproject = ""
                    current_section_kind = "main"

            # Heading 2 -> section marker OR Main Project (top-level) OR Sub Project
            elif b_type == "heading_2":
                current_has_heading_context = True
                heading_text = _block_text(block, "heading_2")
                detected = _detect_section_kind(heading_text)
                if detected:
                    current_section_kind = detected
                    continue

                if current_section_kind == "sub" and current_project:
                    current_subproject = heading_text
                elif depth == 0 or not current_project:
                    current_project = heading_text
                    current_subproject = ""
                else:
                    current_subproject = heading_text

            # Heading 3 -> Sub Project
            elif b_type == "heading_3":
                current_has_heading_context = True
                current_subproject = _block_text(block, "heading_3")

            # Toggle with children can act as Sub Project container.
            elif b_type == "toggle" and block.get("has_children"):
                toggle_text = _block_text(block, "toggle")
                if toggle_text:
                    current_subproject = toggle_text

            # Timeline entry blocks
            if b_type in entry_block_types:
                raw_text = _block_text(block, b_type)

                if raw_text:
                    match = TIMELINER_PATTERN.search(raw_text)
                    if match:
                        data = match.groupdict()

                        takes_seg = data.get("takes_seg", "")
                        status_emoji, subtheme = _parse_prefix(data.get("prefix", ""))
                        remaining = data.get("remaining")
                        if not subtheme:
                            continue

                        resolved_project = current_project
                        resolved_subproject = current_subproject

                        # For section-style pages without explicit project/subproject headers,
                        # infer the leading label from entry prefix:
                        # - Main section: "<project> <task>"
                        # - Sub section: "<subproject> <task>"
                        lead, rest = _split_leading_label(subtheme)
                        if current_section_kind == "main" and not resolved_project and lead and rest:
                            resolved_project = lead
                            subtheme = rest
                        elif current_section_kind == "sub" and not resolved_subproject and lead and rest:
                            resolved_subproject = lead
                            subtheme = rest

                        entry = TimelineEntry(
                            block_id=b_id,
                            project=resolved_project,
                            subproject=resolved_subproject,
                            colour_subtheme=subtheme,
                            status_emoji=status_emoji,
                            settle_date=parse_date_to_iso(data["date"].strip()),
                            time_expected_h=_extract_time_expected_h(takes_seg),
                            percent=int(data["percent"]) if data.get("percent") else 0,
                            remaining_work_days=int(remaining) if remaining else None,
                            raw_text=raw_text,
                            in_heading_scope=current_has_heading_context,
                        )
                        entries.append(entry)

            children = block.get("children_blocks", [])
            if children:
                walk(
                    children,
                    current_project,
                    current_subproject,
                    depth + 1,
                    current_section_kind,
                    current_has_heading_context,
                )

    walk(blocks, "", "", 0, None, False)
    return entries


def fetch_and_parse_timeliner() -> List[TimelineEntry]:
    """Fetch the page and parse it into TimelineEntry objects."""
    blocks = get_page_blocks(TIMELINER_PAGE_ID)
    return parse_timeliner_blocks(blocks)
