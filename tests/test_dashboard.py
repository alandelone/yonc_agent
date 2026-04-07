"""
dashboard 模块的单元测试。
验证分组逻辑和 Notion block 生成结构。
"""
import pytest

from dashboard import (
    group_tasks_by_mode,
    group_tasks_by_task_type,
    get_theme_tag,
    build_dashboard_blocks,
)


# ── mock 配置和任务数据 ───────────────────────────────────────

def _mock_cfg():
    """模拟 structured_cfg"""
    return {
        "modes": [
            {"mode_name": "💻Focus", "level": 3, "description": "...", "annotations": {}},
            {"mode_name": "Handy🤘🏻", "level": 3, "description": "...", "annotations": {}},
        ],
        "task_types": {
            "🔍": {"name_cn": "测试", "description": "Stress & Load Testing"},
            "❓": {"name_cn": "", "description": "Unknown TYPE"},
        },
        "themes": {
            "PhDSettle✒": {"name": "PhDSettle✒", "sub_themes": [], "color": "red"},
            "鍛造Lab": {"name": "鍛造Lab", "sub_themes": [], "color": "purple"},
        }
    }


def _mock_flat_state():
    """模拟 flat_state 任务列表，包含不同 tag 组合"""
    return [
        {
            "id": "t1", "title": "Task Focus A",
            "original_notion_title": "Task Focus A",
            "tags": {
                "Modes": "💻Focus",
                "Task Theme with colour": "PhDSettle✒ Research",
            }
        },
        {
            "id": "t2", "title": "Task Focus B",
            "original_notion_title": "Task Focus B",
            "tags": {
                "Modes": "💻Focus",
                "Task Theme with colour": "鍛造Lab Maker",
            }
        },
        {
            "id": "t3", "title": "Task Handy",
            "original_notion_title": "Task Handy",
            "tags": {
                "Modes": "Handy🤘🏻",
                "Task Type": "🔍 测试",
                "Task Theme with colour": "PhDSettle✒ Dev",
            }
        },
        {
            "id": "t4", "title": "Untagged Task",
            "original_notion_title": "Untagged Task",
            "tags": {}
        },
        {
            "id": "t5", "title": "Only Theme Task",
            "original_notion_title": "Only Theme Task",
            "tags": {
                "Task Theme with colour": "PhDSettle✒ Thesis",
            }
        },
    ]


# ── group_tasks_by_mode ───────────────────────────────────────

class TestGroupByMode:
    def test_with_mode_tags(self):
        """有 mode tag 的任务被正确分组"""
        cfg = _mock_cfg()
        state = _mock_flat_state()
        groups = group_tasks_by_mode(state, cfg)

        assert "💻Focus" in groups
        assert len(groups["💻Focus"]) == 2

        assert "Handy🤘🏻" in groups
        assert len(groups["Handy🤘🏻"]) == 1

    def test_unassigned(self):
        """无 mode tag 的任务归入 Unassigned"""
        cfg = _mock_cfg()
        state = _mock_flat_state()
        groups = group_tasks_by_mode(state, cfg)

        assert "Unassigned" in groups
        # t4 和 t5 没有 Modes tag
        assert len(groups["Unassigned"]) == 2

    def test_empty_state(self):
        """空状态返回空字典"""
        groups = group_tasks_by_mode([], _mock_cfg())
        assert groups == {}


# ── group_tasks_by_task_type ──────────────────────────────────

class TestGroupByTaskType:
    def test_with_type_tags(self):
        """task type 分组正确"""
        cfg = _mock_cfg()
        state = _mock_flat_state()
        groups = group_tasks_by_task_type(state, cfg)

        # t3 有 Task Type = "🔍 测试"
        matching_keys = [k for k in groups if "🔍" in k]
        assert len(matching_keys) == 1
        assert len(groups[matching_keys[0]]) == 1

    def test_unassigned_type(self):
        """无 type tag 归入 Unassigned"""
        cfg = _mock_cfg()
        state = _mock_flat_state()
        groups = group_tasks_by_task_type(state, cfg)

        assert "Unassigned" in groups
        # t1, t2, t4, t5 没有 Task Type
        assert len(groups["Unassigned"]) == 4


# ── get_theme_tag ─────────────────────────────────────────────

class TestGetThemeTag:
    def test_extracts_theme_name(self):
        """正确提取主题名"""
        task = {"tags": {"Task Theme with colour": "PhDSettle✒ Research"}}
        assert get_theme_tag(task) == "PhDSettle✒"

    def test_no_theme(self):
        """没有主题时返回空字符串"""
        task = {"tags": {}}
        assert get_theme_tag(task) == ""

    def test_no_tags(self):
        """没有 tags 字典时返回空字符串"""
        task = {}
        assert get_theme_tag(task) == ""


# ── build_dashboard_blocks ────────────────────────────────────

class TestBuildDashboardBlocks:
    def test_structure_has_headings(self):
        """生成的 blocks 包含 heading_2 主标题"""
        cfg = _mock_cfg()
        state = _mock_flat_state()
        blocks = build_dashboard_blocks(state, cfg)

        heading_blocks = [b for b in blocks if b.get("type") == "heading_2"]
        assert len(heading_blocks) == 2

        # 第一个是 "By Modes"
        h1_text = heading_blocks[0]["heading_2"]["rich_text"][0]["text"]["content"]
        assert h1_text == "By Modes"

        # 第二个是 "By Task Type"
        h2_text = heading_blocks[1]["heading_2"]["rich_text"][0]["text"]["content"]
        assert h2_text == "By Task Type"

    def test_headings_have_blue_background(self):
        """主标题使用 blue_background"""
        blocks = build_dashboard_blocks(_mock_flat_state(), _mock_cfg())
        heading_blocks = [b for b in blocks if b.get("type") == "heading_2"]
        for hb in heading_blocks:
            assert hb["heading_2"]["color"] == "blue_background"

    def test_subheadings_bold_blue(self):
        """子标题（mode/type 名称）使用 bold + blue_background"""
        blocks = build_dashboard_blocks(_mock_flat_state(), _mock_cfg())
        sub_headings = [
            b for b in blocks
            if b.get("type") == "paragraph"
            and b["paragraph"].get("color") == "blue_background"
        ]
        assert len(sub_headings) > 0
        for sh in sub_headings:
            annos = sh["paragraph"]["rich_text"][0].get("annotations", {})
            assert annos.get("bold") is True

    def test_global_numbering(self):
        """任务编号全局连续"""
        blocks = build_dashboard_blocks(_mock_flat_state(), _mock_cfg())
        numbered_blocks = [
            b for b in blocks
            if b.get("type") == "numbered_list_item"
        ]

        # 提取 [N] 编号
        numbers = []
        for nb in numbered_blocks:
            text = nb["numbered_list_item"]["rich_text"][0]["text"]["content"]
            # 格式: "[N] task title"
            if text.startswith("["):
                num_str = text.split("]")[0][1:]
                numbers.append(int(num_str))

        # 编号应该从 1 开始，连续递增
        assert numbers == list(range(1, len(numbers) + 1))

    def test_empty_state_still_has_headings(self):
        """即使无任务，仍应有两个主标题"""
        blocks = build_dashboard_blocks([], _mock_cfg())
        heading_blocks = [b for b in blocks if b.get("type") == "heading_2"]
        assert len(heading_blocks) == 2
