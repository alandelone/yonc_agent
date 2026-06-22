import json
import os
import re
from dataclasses import dataclass, field
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
    priority: Optional[int] = None
    scope_section: str = ""
    tags: Dict[str, str] = field(default_factory=dict)
    task_title: str = ""
    description: str = ""
    wbs_level: Optional[int] = None


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
    if not normalized:
        return "empty"
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


def _structured_config() -> Dict[str, Any]:
    try:
        from config_reader import load_config, structure_yonctask_config

        return structure_yonctask_config(load_config())
    except Exception:
        return {
            "themes": {},
            "modes": [],
            "priorities": {},
            "task_types": {},
            "wbs_levels": {},
        }


def _theme_tag_for_label(label: str, structured_cfg: Dict[str, Any]) -> str:
    needle = str(label or "").strip()
    if not needle:
        return ""
    for theme_name, data in structured_cfg.get("themes", {}).items():
        if needle == theme_name:
            sub_themes = data.get("sub_themes", [])
            return f"{theme_name}|{'|'.join(sub_themes)}" if sub_themes else theme_name
        if needle in data.get("sub_themes", []):
            return f"{theme_name}|{needle}"
    return ""


def _parse_title_description(text: str) -> tuple[str, str]:
    raw = str(text or "").strip()
    if ":" not in raw:
        return raw, ""
    title, desc = raw.split(":", 1)
    return title.strip(), desc.strip()


def _extract_leading_token(
    text: str,
    candidates: Dict[str, str],
) -> tuple[str, str, str]:
    raw = str(text or "").lstrip()
    if not raw or not candidates:
        return "", "", raw
    for label in sorted(candidates.keys(), key=len, reverse=True):
        if not label:
            continue
        if raw == label or raw.startswith(label + " "):
            return label, candidates[label], raw[len(label):].lstrip()
        if raw.startswith(label):
            next_char = raw[len(label):len(label) + 1]
            if next_char and not re.match(r"[\w\s]", next_char):
                return label, candidates[label], raw[len(label):].lstrip()
    return "", "", raw


def _parse_prefixed_tags_and_task(
    text: str,
    structured_cfg: Dict[str, Any],
) -> tuple[Dict[str, str], str, str, Optional[int]]:
    tags: Dict[str, str] = {}
    rest = str(text or "").strip()
    wbs_level: Optional[int] = None

    wbs_candidates: Dict[str, tuple[int, str]] = {}
    for level, entry in structured_cfg.get("wbs_levels", {}).items():
        if not isinstance(entry, dict):
            continue
        emoji = str(entry.get("emoji") or "").strip()
        raw = str(entry.get("raw") or emoji).strip()
        if emoji:
            try:
                level_int = int(level)
            except (TypeError, ValueError):
                level_int = None
            if level_int is not None:
                wbs_candidates[emoji] = (level_int, raw)

    while rest:
        consumed = False

        for emoji in sorted(wbs_candidates.keys(), key=len, reverse=True):
            if rest.startswith(emoji):
                level_int, raw = wbs_candidates[emoji]
                tags["WBS level"] = raw
                wbs_level = level_int
                rest = rest[len(emoji):].lstrip()
                consumed = True
                break
        if consumed:
            continue

        priority_candidates = {
            str(emoji).strip(): f"{emoji} | ({level})"
            for emoji, level in structured_cfg.get("priorities", {}).items()
            if str(emoji).strip()
        }
        label, value, new_rest = _extract_leading_token(rest, priority_candidates)
        if label:
            tags["Priority"] = value
            rest = new_rest
            continue

        task_type_candidates: Dict[str, str] = {}
        for key, entry in structured_cfg.get("task_types", {}).items():
            emoji = str(key).split("|", 1)[0].strip()
            if emoji:
                task_type_candidates[emoji] = str(key).strip()
        label, value, new_rest = _extract_leading_token(rest, task_type_candidates)
        if label:
            tags["Task Type"] = value
            rest = new_rest
            continue

        mode_candidates = {
            str(mode.get("mode_name") or "").strip(): str(mode.get("mode_name") or "").strip()
            for mode in structured_cfg.get("modes", [])
            if str(mode.get("mode_name") or "").strip()
        }
        label, value, new_rest = _extract_leading_token(rest, mode_candidates)
        if label:
            tags["Modes"] = value
            rest = new_rest
            continue

        break

    task_title, description = _parse_title_description(rest)
    return tags, task_title, description, wbs_level


def _parse_structured_prefix(
    subtheme_text: str,
    structured_cfg: Dict[str, Any],
) -> tuple[str, Dict[str, str], str, str, Optional[int]]:
    raw = _clean_subtheme_label(subtheme_text)
    if not raw:
        return "", {}, "", "", None

    theme_candidates: Dict[str, str] = {}
    for theme_name, data in structured_cfg.get("themes", {}).items():
        theme_candidates[str(theme_name).strip()] = _theme_tag_for_label(theme_name, structured_cfg)
        for sub_theme in data.get("sub_themes", []):
            theme_candidates[str(sub_theme).strip()] = _theme_tag_for_label(sub_theme, structured_cfg)

    label, theme_tag, rest = _extract_leading_token(raw, theme_candidates)
    if not label:
        return raw, {}, "", "", None

    tags, task_title, description, wbs_level = _parse_prefixed_tags_and_task(rest, structured_cfg)
    # Keep legacy section rows like "科研人 RstV4" intact. Without an explicit
    # tag or a task description separator, that shape is more likely to be
    # "<project> <timeline item>" than the new structured row.
    if not tags and not description:
        return raw, {}, "", "", None
    if theme_tag:
        tags["Task Theme with colour"] = theme_tag
    return label, tags, task_title, description, wbs_level


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
    structured_cfg = _structured_config()

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

            if b_type == "heading_1":
                current_has_heading_context = True
                heading_text = _block_text(block, "heading_1")
                detected = _detect_section_kind(heading_text)
                if detected in ("main", "sub"):
                    current_section_kind = detected
                    if detected == "sub":
                        current_subproject = ""
                elif detected == "empty" or not heading_text.strip():
                    current_section_kind = None
                    current_project = ""
                    current_subproject = ""
                else:
                    current_project = heading_text
                    current_subproject = ""
                    current_section_kind = "main"

            elif b_type == "heading_2":
                current_has_heading_context = True
                heading_text = _block_text(block, "heading_2")
                detected = _detect_section_kind(heading_text)
                if detected in ("main", "sub"):
                    current_section_kind = detected
                    continue
                elif detected == "empty" or not heading_text.strip():
                    current_section_kind = None
                    current_project = ""
                    current_subproject = ""
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
                        if current_section_kind not in ("main", "sub"):
                            continue
                        data = match.groupdict()

                        takes_seg = data.get("takes_seg", "")
                        status_emoji, subtheme = _parse_prefix(data.get("prefix", ""))
                        subtheme, tags, task_title, description, wbs_level = _parse_structured_prefix(
                            subtheme,
                            structured_cfg,
                        )
                        remaining = data.get("remaining")
                        if not subtheme:
                            continue

                        resolved_project = current_project
                        resolved_subproject = current_subproject

                        # For section-style pages without explicit project/subproject headers,
                        # infer the leading label from entry prefix:
                        # - Main section: "<project> <task>"
                        # - Sub section: "<subproject> <task>"
                        # Use a loop to strip ALL leading duplicate prefixes
                        # (the sync writes badge_label back, so re-read can
                        #  produce "Thesis Thesis Phd Logic").
                        lead, rest = _split_leading_label(subtheme)
                        if current_section_kind == "main":
                            if not resolved_project and lead and rest:
                                # First entry: discover the project name.
                                # Accept unconditionally — the first entry always
                                # has format "<Project> <Task>" from the sync.
                                resolved_project = lead
                                subtheme = rest
                            elif resolved_project and lead and rest and lead.lower() == resolved_project.lower():
                                # Project already known; strip matching prefix.
                                subtheme = rest
                            # Strip any remaining leading duplicates of the project name.
                            # Only strip when the remainder is multi-word to avoid
                            # over-stripping names like "thesis writing" → "writing".
                            while resolved_project:
                                l2, r2 = _split_leading_label(subtheme)
                                if l2 and r2 and l2.lower() == resolved_project.lower() and " " in r2:
                                    subtheme = r2
                                else:
                                    break
                        elif current_section_kind == "sub":
                            if not resolved_subproject and lead and rest:
                                resolved_subproject = lead
                                subtheme = rest
                            elif not resolved_subproject and not lead and task_title:
                                # Single-word subtheme (e.g. "SolarMan") that
                                # _split_leading_label can't split, but
                                # _parse_structured_prefix extracted a task_title
                                # (e.g. "SolarMan Apparatus Learning").
                                # Use the subtheme as subproject and task_title
                                # as the colour_subtheme.
                                resolved_subproject = subtheme
                                subtheme = task_title
                            while resolved_subproject:
                                l2, r2 = _split_leading_label(subtheme)
                                if l2 and r2 and l2.lower() == resolved_subproject.lower() and " " in r2:
                                    subtheme = r2
                                else:
                                    break


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
                            priority=None,
                            scope_section=str(current_section_kind or ""),
                            tags=tags,
                            task_title=task_title,
                            description=description,
                            wbs_level=wbs_level,
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


def _load_entries_from_state_file() -> List[TimelineEntry]:
    """
    Reconstruct TimelineEntry objects from the locally-cached timeliner_state.json.
    This file is written by `main.py timeliner` (sync_timeliner).  Reading it avoids
    a second live Notion call during the flow pipeline and gives correct results even
    when the Notion page structure cannot be parsed by the regex.
    """
    _DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
    state_path = os.path.join(_DATA_DIR, "timeliner_state.json")
    if not os.path.exists(state_path):
        return []
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []

    if not isinstance(data, dict):
        return []

    entries: List[TimelineEntry] = []
    for section_key, section_kind in [("main_projects", "main"), ("sub_projects", "sub")]:
        group = data.get(section_key, {})
        if not isinstance(group, dict):
            continue

        # Sort by priority so ordered_keys in build_timeliner_scope reflects priority rank.
        items = sorted(
            group.items(),
            key=lambda x: x[1].get("priority", 999) if isinstance(x[1], dict) else 999,
        )

        for title, meta in items:
            if not isinstance(meta, dict):
                continue

            scope_key = str(meta.get("scope_key", "")).strip()
            settle_date = str(meta.get("settle_date", "")).strip()
            if not scope_key or not settle_date:
                continue

            # Parse scope_key: "project::subproject::subtheme"
            parts = scope_key.split("::")
            if len(parts) >= 3:
                project = parts[0].strip()
                subproject = parts[1].strip()
                colour_subtheme = "::".join(parts[2:]).lstrip(":").strip()
            elif len(parts) == 2:
                project = parts[0].strip()
                subproject = ""
                colour_subtheme = parts[1].strip()
            else:
                project = ""
                subproject = ""
                colour_subtheme = scope_key

            if not colour_subtheme:
                continue

            entries.append(
                TimelineEntry(
                    block_id="",
                    project=project,
                    subproject=subproject,
                    colour_subtheme=colour_subtheme,
                    status_emoji="🟢",
                    settle_date=settle_date,
                    time_expected_h=None,
                    percent=0,
                    remaining_work_days=None,
                    raw_text=title,
                    in_heading_scope=True,
                    priority=(
                        int(meta.get("priority"))
                        if str(meta.get("priority", "")).strip().isdigit()
                        else None
                    ),
                    scope_section=section_kind,
                    tags=meta.get("tags") if isinstance(meta.get("tags"), dict) else {},
                    task_title=str(meta.get("task_title", "") or "").strip(),
                    description=str(meta.get("description", "") or "").strip(),
                    wbs_level=(
                        int(meta.get("wbs_level"))
                        if str(meta.get("wbs_level", "")).strip().isdigit()
                        else None
                    ),
                )
            )

    return entries


def fetch_and_parse_timeliner(force_live: bool = False) -> List[TimelineEntry]:
    """
    Return TimelineEntry objects for the flow pipeline.

    Strategy (state-file-first):
    1. Try loading from the locally-cached timeliner_state.json.
       This file is written by ``main.py timeliner`` and avoids a redundant
       Notion call that may return 0 results when the page structure doesn't
       match the regex.
    2. Fall back to a live Notion fetch + regex parse only when the state file
       is absent or contains no entries.
    """
    if not force_live:
        entries = _load_entries_from_state_file()
        if entries:
            return entries

    # Fallback: live Notion fetch.
    blocks = get_page_blocks(TIMELINER_PAGE_ID)
    return parse_timeliner_blocks(blocks)
