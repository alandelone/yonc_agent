"""
tests/test_block_reader.py — Unit tests for pipeline.block_reader.BlockReader
"""
import pytest
from pipeline.block_reader import BlockReader


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_task(id_, parent_id=None, title="Task", depth=0, block_type="bulleted_list_item"):
    return {
        "id": id_,
        "notion_block_id": id_,
        "parent_id": parent_id,
        "title": title,
        "original_notion_title": title,
        "depth": depth,
        "type": block_type,
        "notion_type": block_type,
    }


@pytest.fixture
def simple_tree():
    """
    root
    ├── child_a
    │   ├── grandchild_1
    │   └── grandchild_2
    └── child_b
    """
    root       = make_task("root", parent_id=None,   title="Root",        depth=0)
    child_a    = make_task("ca",   parent_id="root",  title="Child A",     depth=1)
    child_b    = make_task("cb",   parent_id="root",  title="Child B",     depth=1)
    grand1     = make_task("g1",   parent_id="ca",    title="Grandchild1", depth=2)
    grand2     = make_task("g2",   parent_id="ca",    title="Grandchild2", depth=2)
    flat = [root, child_a, child_b, grand1, grand2]
    task_by_id = {t["id"]: t for t in flat}
    return flat, task_by_id


@pytest.fixture
def reader(simple_tree):
    flat, task_by_id = simple_tree
    return BlockReader(flat, task_by_id), flat, task_by_id


# ── location_in_list ──────────────────────────────────────────────────────────

def test_location_root_only_one(reader):
    r, flat, _ = reader
    root = flat[0]
    # root has no parent → counted among root-level siblings
    idx, total = r.location_in_list(root)
    assert idx == 1
    assert total == 1  # only one root-level task

def test_location_child_among_siblings(reader):
    r, flat, _ = reader
    child_a = flat[1]  # first child of root
    child_b = flat[2]  # second child of root
    idx_a, total_a = r.location_in_list(child_a)
    idx_b, total_b = r.location_in_list(child_b)
    assert total_a == 2
    assert total_b == 2
    assert idx_a == 1
    assert idx_b == 2

def test_location_grandchild(reader):
    r, flat, _ = reader
    grand1 = flat[3]
    grand2 = flat[4]
    idx1, total1 = r.location_in_list(grand1)
    idx2, total2 = r.location_in_list(grand2)
    assert total1 == 2
    assert total2 == 2
    assert idx1 == 1
    assert idx2 == 2


# ── ancestors ─────────────────────────────────────────────────────────────────

def test_ancestors_grandchild(reader):
    r, flat, _ = reader
    grand1 = flat[3]
    ancs = r.ancestors(grand1)
    assert len(ancs) == 2
    assert ancs[0]["id"] == "ca"
    assert ancs[1]["id"] == "root"

def test_ancestors_root(reader):
    r, flat, _ = reader
    root = flat[0]
    ancs = r.ancestors(root)
    assert ancs == []

def test_ancestors_child(reader):
    r, flat, _ = reader
    child_b = flat[2]
    ancs = r.ancestors(child_b)
    assert len(ancs) == 1
    assert ancs[0]["id"] == "root"


# ── direct_children ───────────────────────────────────────────────────────────

def test_direct_children_root(reader):
    r, flat, _ = reader
    root = flat[0]
    kids = r.direct_children(root)
    assert {k["id"] for k in kids} == {"ca", "cb"}

def test_direct_children_leaf(reader):
    r, flat, _ = reader
    grand1 = flat[3]
    assert r.direct_children(grand1) == []


# ── all_descendants ───────────────────────────────────────────────────────────

def test_all_descendants_root(reader):
    r, flat, _ = reader
    root = flat[0]
    descs = r.all_descendants(root)
    assert {d["id"] for d in descs} == {"ca", "cb", "g1", "g2"}

def test_all_descendants_child_a(reader):
    r, flat, _ = reader
    child_a = flat[1]
    descs = r.all_descendants(child_a)
    assert {d["id"] for d in descs} == {"g1", "g2"}


# ── is_leaf ───────────────────────────────────────────────────────────────────

def test_is_leaf_grandchild(reader):
    r, flat, _ = reader
    assert r.is_leaf(flat[3]) is True

def test_is_leaf_root(reader):
    r, flat, _ = reader
    assert r.is_leaf(flat[0]) is False


# ── description ───────────────────────────────────────────────────────────────

def test_description_uses_original_notion_title(reader):
    r, flat, _ = reader
    task = {"id": "x", "title": "Fallback", "original_notion_title": "Primary"}
    assert r.description(task) == "Primary"

def test_description_falls_back_to_title(reader):
    r, flat, _ = reader
    task = {"id": "x", "title": "Fallback"}
    assert r.description(task) == "Fallback"


# ── summary ───────────────────────────────────────────────────────────────────

def test_summary_structure(reader):
    r, flat, _ = reader
    grand1 = flat[3]
    s = r.summary(grand1)
    assert s["block_id"] == "g1"
    assert s["sibling_total"] == 2
    assert "Child A" in s["parent_titles"]
    assert "Root" in s["parent_titles"]
    assert s["child_count"] == 0
