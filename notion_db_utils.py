"""
Notion Database property read/write utilities.

Handles 4 property types:
  - checkbox  (bool)
  - number    (int/float or None)
  - multi_select (list of tag names)
  - rich_text (plain string)

Usage pattern:
  Read:  extract_property_value(prop_data) -> python value
  Write: build_property_payload(prop_name, prop_type, value) -> Notion API dict
"""
import requests
from typing import Any, Dict, List, Optional, Union

from config import NOTION_HEADERS

BASE_URL = "https://api.notion.com/v1"


# ── Schema introspection ────────────────────────────────────────────

def get_database_schema(database_id: str) -> Dict[str, Any]:
    """
    Fetch the database object to inspect property definitions.
    Returns the raw 'properties' dict keyed by property name.
    """
    url = f"{BASE_URL}/databases/{database_id}"
    resp = requests.get(url, headers=NOTION_HEADERS)
    resp.raise_for_status()
    return resp.json().get("properties", {})


def get_multiselect_options(database_id: str, property_name: str) -> List[Dict[str, str]]:
    """
    Returns the available options for a multi_select property.
    Each option is {"id": "...", "name": "...", "color": "..."}.
    """
    schema = get_database_schema(database_id)
    prop = schema.get(property_name)
    if not prop or prop.get("type") != "multi_select":
        raise ValueError(
            f"Property '{property_name}' is not a multi_select "
            f"(found type: {prop.get('type') if prop else 'NOT FOUND'})"
        )
    return prop.get("multi_select", {}).get("options", [])


# ── Reading (extract values from Notion response) ───────────────────

def extract_property_value(prop_data: Dict[str, Any]) -> Any:
    """
    Given a single property object from a Notion page response,
    extract the Python-native value.

    Handles: checkbox, number, multi_select, rich_text, title.
    Returns None for unrecognized types.
    """
    prop_type = prop_data.get("type")

    if prop_type == "checkbox":
        return prop_data.get("checkbox", False)

    elif prop_type == "number":
        return prop_data.get("number")  # int/float or None

    elif prop_type == "multi_select":
        return [item.get("name", "") for item in prop_data.get("multi_select", [])]

    elif prop_type == "rich_text":
        segments = prop_data.get("rich_text", [])
        return "".join(
            seg.get("text", {}).get("content", "")
            if seg.get("type") == "text"
            else seg.get("plain_text", "")
            for seg in segments
        )

    elif prop_type == "title":
        segments = prop_data.get("title", [])
        return "".join(
            seg.get("text", {}).get("content", "")
            if seg.get("type") == "text"
            else seg.get("plain_text", "")
            for seg in segments
        )

    return None


def extract_all_properties(page: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract all property values from a Notion page object.
    Returns {property_name: python_value}.
    """
    result = {}
    for name, prop_data in page.get("properties", {}).items():
        result[name] = extract_property_value(prop_data)
    return result


# ── Writing (build payloads for Notion API) ──────────────────────────

def build_checkbox_payload(value: bool) -> Dict[str, Any]:
    return {"checkbox": bool(value)}


def build_number_payload(value: Union[int, float, None]) -> Dict[str, Any]:
    if value is None:
        return {"number": None}
    return {"number": float(value) if "." in str(value) else int(value)}


def build_multiselect_payload(names: List[str]) -> Dict[str, Any]:
    """
    Build multi_select payload from a list of tag name strings.
    Uses name-based selection (simpler, works if tag names don't change).
    """
    return {"multi_select": [{"name": n} for n in names]}


def build_richtext_payload(text: str) -> Dict[str, Any]:
    """
    Build rich_text payload from a plain string.
    Wraps in a single text object (sufficient for most use cases).
    """
    return {
        "rich_text": [
            {
                "type": "text",
                "text": {"content": str(text)}
            }
        ]
    }


# Type dispatcher
_TYPE_BUILDERS = {
    "checkbox": lambda v: build_checkbox_payload(v),
    "number": lambda v: build_number_payload(v),
    "multi_select": lambda v: build_multiselect_payload(v),
    "rich_text": lambda v: build_richtext_payload(v),
}


def build_property_payload(
    prop_name: str,
    prop_type: str,
    value: Any
) -> Dict[str, Dict[str, Any]]:
    """
    Build a single-property update payload.
    Returns {"prop_name": {type_specific_payload}}.
    """
    builder = _TYPE_BUILDERS.get(prop_type)
    if not builder:
        raise ValueError(f"Unsupported property type: '{prop_type}'. "
                         f"Supported: {list(_TYPE_BUILDERS.keys())}")
    return {prop_name: builder(value)}


def build_properties_payload(
    updates: List[Dict[str, Any]],
    schema: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Build a combined properties payload for multiple property updates.

    Each update dict: {"name": "prop_name", "value": <python_value>}
    If schema is provided, prop type is auto-detected.
    Otherwise each update must also include "type": "checkbox"|"number"|etc.
    """
    payload = {}
    for upd in updates:
        name = upd["name"]
        value = upd["value"]
        if schema and name in schema:
            prop_type = schema[name].get("type")
        else:
            prop_type = upd.get("type")
        if not prop_type:
            raise ValueError(
                f"Cannot determine type for property '{name}'. "
                f"Provide schema or include 'type' in update dict."
            )
        payload.update(build_property_payload(name, prop_type, value))
    return payload


# ── Database query & page update ─────────────────────────────────────

def query_database(
    database_id: str,
    filter_payload: Dict[str, Any] = None
) -> List[Dict[str, Any]]:
    """
    Query a Notion database. Returns list of page objects.
    Handles pagination automatically.
    """
    url = f"{BASE_URL}/databases/{database_id}/query"
    body = {}
    if filter_payload:
        body["filter"] = filter_payload

    pages = []
    has_more = True
    while has_more:
        resp = requests.post(url, headers=NOTION_HEADERS, json=body)
        resp.raise_for_status()
        data = resp.json()
        pages.extend(data.get("results", []))
        has_more = data.get("has_more", False)
        next_cursor = data.get("next_cursor")
        if next_cursor:
            body["start_cursor"] = next_cursor
    return pages


def query_page_by_date(database_id: str, target_date: str = None) -> Optional[Dict[str, Any]]:
    """
    Query database for a page whose Date title contains target_date.
    Notion date-mention titles aren't matched by the title.contains filter,
    so we fetch all pages and match via plain_text client-side.
    """
    from datetime import date
    if target_date is None:
        target_date = date.today().isoformat()

    pages = query_database(database_id)
    for page in pages:
        title_prop = page.get("properties", {}).get("Date", {})
        segments = title_prop.get("title", [])
        plain = "".join(seg.get("plain_text", "") for seg in segments)
        if target_date in plain:
            return page
    return None


def update_page_properties(
    page_id: str,
    properties: Dict[str, Any]
) -> Dict[str, Any]:
    """
    PATCH a Notion page with the given properties payload.
    properties should be the result of build_properties_payload() or similar.
    """
    url = f"{BASE_URL}/pages/{page_id}"
    body = {"properties": properties}
    resp = requests.patch(url, headers=NOTION_HEADERS, json=body)
    resp.raise_for_status()
    return resp.json()
