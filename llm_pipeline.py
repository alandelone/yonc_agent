import dspy
import os
import json
from typing import List, Dict, Any

from unlimited_llmapi import configure_dspy

try:
    # Initialize the LM using the unlimited multi-key manager
    lm = configure_dspy(model="gemini/gemini-3-flash-preview")
except Exception as e:
    print(f"Warning: Could not configure DSPy multi-key LM, falling back to basic setup: {e}")
    from config import GEMINI_API_KEY
    if GEMINI_API_KEY:
        os.environ["GEMINI_API_KEY"] = GEMINI_API_KEY
    else:
        print("Warning: GEMINI_API_KEY not found in environment.")

    try:
        # Initialize the LM using the new DSPy 2.x standard format
        lm = dspy.LM("gemini/gemini-3-flash-preview")
        dspy.configure(lm=lm)
    except Exception as inner_e:
        print(f"Warning: Could not configure fallback DSPy LM: {inner_e}")


class SplitAbstractTask(dspy.Signature):
    """你是专为 INTP + ADHD 人群设计的“前额叶代偿引擎”。你的唯一目标是：将用户输入的、引发执行功能障碍的【宏大/抽象任务】，降维打击成连草履虫都能执行的【物理肌肉动作清单】。

# Core Rules (1-2-3 Framework)
接收到用户任务后，你必须在后台严格执行以下 3 步转化，然后再输出结果：

**Step 1: 剥离抽象 (Identify & Destroy)**
- 识别并彻底抹除任务中的宏大名词与结果导向词汇（如：复习、规划、总结、大纲、完美、完成）。
- 严禁在回复中重复用户的宏大目标，切断一切可能引发“预见性焦虑”的触发点。

**Step 2: 物理降智 (Physical Translation)**
- 强制将所有“认知动作”翻译为最底层的“肌肉动作”。
- 🛑 绝对禁用词：想、决定、分类、回忆、构思、评估、整理。
- ✅ 强制使用词：走到、坐下、拿起、按下、点击、敲击、输入、翻开、撕下。

**Step 3: 纳米切割 (Nano-Slicing)**
- 确保每一个切分出的步骤耗时绝对 < 60 秒。
- 确保每一个步骤包含 **0 个决策点**（例如：不能写“找一本想看的书”，必须写“拿起左手边第一本书”）。
- 第 1 步必须是极具“侮辱性”的简单动作（如：“站起来”或“看一眼屏幕”）。

# Output Constraints (严格遵守)
1. 数量限制：每次最多只输出 5-7 个步骤。绝不要输出任务的完整计划！只提供“启动局部的第一口”。
2. 极简原则：一个序号下只能包含 1 个动词动作。严禁使用“并”、“和”、“然后”合并步骤。
3. 情绪基调：不要打鸡血，不要讲大道理（INTP 讨厌废话）。保持极度冷酷、客观、干瘪的“物理指令”风格。

# Output Format
请严格按以下模板输出（不要添加任何额外问候语）"""
    task_title = dspy.InputField(desc="需要拆解的抽象大任务")
    context = dspy.InputField(desc="Parent task context if any")
    sub_tasks: list[str] = dspy.OutputField(desc="List of concrete physical-action sub-tasks")

class TagTask(dspy.Signature):
    """Assign the best-matching tag from each config dimension."""
    task_title = dspy.InputField(desc="Task to tag")
    config_options = dspy.InputField(desc="Dict of config dimensions and their options as a JSON-like string")
from pydantic import BaseModel, Field

# --- WBS Core Context ---
WBS_CONTEXT = """
# The Core Definition and Multi-Dimensional Attributes of a WBS

### 1. Deliverable-Oriented
Focus on *what* is being produced, rather than the individual steps taken to produce it. Every node must represent a verifiable product, service, or result.

### 2. Hierarchical Decomposition
- **Level 1 (Goal):** Final outcome. Noun phrase. Must be SMART (Specific, Measurable, Achievable, Relevant, Time-bound).
- **Level 2 (Major Deliverables):** Core Modules. Follow 100% Rule and MECE (Mutually Exclusive, Collectively Exhaustive). Only Nouns.
- **Level 3 (Work Packages):** Lowest deliverable level. Focus on outcome (Noun). 8-80 hours effort.
- **Level 4 (Activities):** Physical Actions. Verb + Noun. Max 2 hours effort.

### 3. Golden Rules
1. **Nouns over Verbs (Levels 1-3):** Describe the "What" (deliverables), not the "How".
2. **Strict 100% Rule:** If it's not in the WBS, it's out of scope.
3. **Mutual Exclusivity:** Ensure no two work packages contain the same work.
"""

# --- Pydantic Data Models ---
class WBSClassification(BaseModel):
    rationale: str = Field(description="Step-by-step reasoning for assigning the level and type.")
    level: int = Field(description="Output EXACTLY ONE digit: 1, 2, 3, or 4 based on the definitions.")
    task_type: str = Field(description="Output 'WBS' (deterministic) or 'OKR' (exploratory) ONLY if level is 1. Else output 'N/A'.")

class L2DeliverablesList(BaseModel):
    deliverables: list[str] = Field(description="List of Level 2 Major Deliverables. Must be Nouns only.")

class OKRMilestonesList(BaseModel):
    objective: str = Field(description="The overarching Objective (O)")
    key_results: list[str] = Field(description="List of verifiable Key Results (KRs)")

class L3WorkPackagesList(BaseModel):
    work_packages: list[str] = Field(description="List of Level 3 Work Packages. Must be Nouns only.")

class ActivityDesc(BaseModel):
    title: str = Field(description="Physical action starting with a verb")
    estimated_hours: float = Field(description="Expected duration in hours. Must be <= 2.0")

class L4ActivitiesList(BaseModel):
    activities: list[ActivityDesc] = Field(description="List of physical action activities.")

class AtomicAction(BaseModel):
    action_type: str = Field(description="Category of action (e.g., Focus, Routine, Communicate, Admin)")
    estimated_hours: float = Field(description="Time prediction in hours")
    refined_action: str = Field(description="The highly specific, atomized physical action")

# --- Phase 1: Vertical Classification ---
class ClassifyTask(dspy.Signature):
    """Analyze the task syntax and scope to determine its WBS Level (1-4) and Type (WBS/OKR)."""
    task_input = dspy.InputField()
    wbs_rules_context = dspy.InputField(desc="WBS Core Rules")
    classification: WBSClassification = dspy.OutputField()

# --- Phase 2: Horizontal Refinement & Decomposition ---
class RefineL1WBS(dspy.Signature):
    """Breakdown a Level 1 Deterministic Goal into Level 2 Major Deliverables using MECE rules."""
    l1_goal = dspy.InputField(desc="The Level 1 Project Goal")
    wbs_rules_context = dspy.InputField(desc="WBS Core Rules")
    l2_output: L2DeliverablesList = dspy.OutputField()

class RefineL1OKR(dspy.Signature):
    """Translate an exploratory Level 1 Project Goal into an OKR format."""
    l1_exploratory_goal = dspy.InputField(desc="The Level 1 Exploratory Goal")
    okr_output: OKRMilestonesList = dspy.OutputField()

class RefineL2(dspy.Signature):
    """Breakdown a Level 2 Major Deliverable into Level 3 Work Packages (Deliverable-oriented)."""
    l2_deliverable = dspy.InputField(desc="The Level 2 Major Deliverable")
    wbs_rules_context = dspy.InputField(desc="WBS Core Rules")
    l3_output: L3WorkPackagesList = dspy.OutputField()

class RefineL3(dspy.Signature):
    """Breakdown a Level 3 Work Package into Level 4 Activities. Must start with Verbs."""
    l3_work_package = dspy.InputField(desc="The Level 3 Work Package")
    wbs_rules_context = dspy.InputField(desc="WBS Core Rules")
    l4_output: L4ActivitiesList = dspy.OutputField()

class RefineL4(dspy.Signature):
    """Atomize a Level 4 Action. Analyze the type of action and predict exact execution time."""
    l4_action = dspy.InputField(desc="The Level 4 Activity")
    atomic_output: AtomicAction = dspy.OutputField()

# Fallback TypedPredictors in case local DSPy doesn't have TypedPredictor properly exposed,
# though we try to use the modern typing format directly in the Signature output annotations.
# DSPy 2.x natively supports output typing.

def classify_task(task_title: str) -> WBSClassification:
    try:
        predictor = dspy.Predict(ClassifyTask)
        result = predictor(task_input=task_title, wbs_rules_context=WBS_CONTEXT)
        cls = result.classification
        print(f"\n[🤖 LLM LOG - Phase 1: Classification]")
        print(f"   Input : '{task_title}'")
        print(f"   Output: Level {cls.level} | Type {cls.task_type} | Rationale: {cls.rationale}")
        return cls
    except Exception as e:
        print(f"Classification failed: {e}. Defaulting to WBS Level 1.")
        return WBSClassification(rationale="Fallback", level=1, task_type="WBS")

def generate_l4_with_validation(task_title: str) -> List[str]:
    """Generates L4 activities and validates the 2-hour constraint."""
    print(f"\n[🤖 LLM LOG - Phase 2.3: Refine L3 -> L4]")
    print(f"   Input (Work Package): '{task_title}'")
    
    predictor = dspy.Predict(RefineL3)
    result = predictor(l3_work_package=task_title, wbs_rules_context=WBS_CONTEXT)
    activities: List[ActivityDesc] = getattr(result.l4_output, 'activities', [])
    
    raw_acts_fmt = [f"{act.title} ({act.estimated_hours}h)" for act in activities]
    print(f"   Output: {raw_acts_fmt}")
    
    final_actions = []
    # If any activity > 2 hours, recursively break it down or simply stringify it with a warning.
    for act in activities:
        if act.estimated_hours > 2.0:
            print(f"   [⚠️ LOG - Validation Rule Failed] Task '{act.title}' exceeds 2.0 hours limit. Forcing LLM to split further.")
            # Fallback inline breakdown request
            sub_predictor = dspy.Predict(RefineL3)
            sub_result = sub_predictor(l3_work_package=f"Breakdown this >2hr task: {act.title}", wbs_rules_context=WBS_CONTEXT)
            sub_acts = getattr(sub_result.l4_output, 'activities', [])
            
            sub_acts_fmt = [f"{sub.title} ({sub.estimated_hours}h)" for sub in sub_acts]
            print(f"   [🔧 LOG - Re-split Output]: {sub_acts_fmt}")
            
            for sub in sub_acts:
                 final_actions.append(f"[{sub.estimated_hours}h] {sub.title}")
        else:
            final_actions.append(f"[{act.estimated_hours}h] {act.title}")
    return final_actions

def split_task(task_title: str, context: str = "") -> List[str]:
    """Uses DSPy to meticulously decompose a task into sub-tasks using the 4-Level WBS Pipeline."""
    try:
        # Step 1: Vertical Classification
        cls_result = classify_task(task_title)
        
        # Step 2: Horizontal Refinement
        if cls_result.level == 1:
            if cls_result.task_type == "OKR":
                print(f"\n[🤖 LLM LOG - Phase 2.1: Refine L1 (OKR)]")
                print(f"   Input (Exploratory Goal): '{task_title}'")
                predictor = dspy.Predict(RefineL1OKR)
                res = predictor(l1_exploratory_goal=task_title)
                print(f"   Output: Objective='{res.okr_output.objective}' | KRs={res.okr_output.key_results}")
                return [f"[Objective] {res.okr_output.objective}"] + [f"[KR] {kr}" for kr in res.okr_output.key_results]
            else:
                print(f"\n[🤖 LLM LOG - Phase 2.1: Refine L1 (WBS)]")
                print(f"   Input (Deterministic Goal): '{task_title}'")
                predictor = dspy.Predict(RefineL1WBS)
                res = predictor(l1_goal=task_title, wbs_rules_context=WBS_CONTEXT)
                print(f"   Output: Deliverables={res.l2_output.deliverables}")
                return res.l2_output.deliverables
                
        elif cls_result.level == 2:
            print(f"\n[🤖 LLM LOG - Phase 2.2: Refine L2]")
            print(f"   Input (Major Deliverable): '{task_title}'")
            predictor = dspy.Predict(RefineL2)
            res = predictor(l2_deliverable=task_title, wbs_rules_context=WBS_CONTEXT)
            print(f"   Output: Work Packages={res.l3_output.work_packages}")
            return res.l3_output.work_packages
            
        elif cls_result.level == 3:
            return generate_l4_with_validation(task_title)
            
        elif cls_result.level == 4:
            print(f"\n[🤖 LLM LOG - Phase 2.4: Refine L4]")
            print(f"   Input (Atomic Action): '{task_title}'")
            predictor = dspy.Predict(RefineL4)
            res = predictor(l4_action=task_title)
            print(f"   Output: Type={res.atomic_output.action_type} | Hours={res.atomic_output.estimated_hours} | Action='{res.atomic_output.refined_action}'")
            return [f"[{res.atomic_output.action_type} | {res.atomic_output.estimated_hours}h] {res.atomic_output.refined_action}"]
            
        else:
            return [task_title]
    except Exception as e:
        print(f"\n[🛑 LLM LOG - Pipeline Error]: {e}. Falling back to default Predict.")
        try:
            # Absolute fallback
            predictor = dspy.Predict(SplitAbstractTask)
            return getattr(predictor(task_title=task_title, context=context), 'sub_tasks', [])
        except:
            return []

# --- Phase 3: Mathematical Critical Path Routing (CPM) ---
class CalculateCPM(dspy.Signature):
    """Write Python to calculate the Critical Path and task order."""
    task_graph = dspy.InputField(desc="JSON of activities, durations, and dependencies")
    cpm_python_code = dspy.OutputField(desc="Executable Python script to find the longest path")
    chronological_order = dspy.OutputField(desc="Numbered list of sequential tasks")
    critical_path = dspy.OutputField(desc="Tasks on the critical path (RED tag)")

# PoT will execute the code. If a circular dependency throws a Python error, 
# it catches the traceback and rewrites the logic to fix it.
try:
    cpm_engine = dspy.ProgramOfThought(CalculateCPM) 
except AttributeError:
    cpm_engine = dspy.ChainOfThought(CalculateCPM)

# --- Phase 4: The Asynchronous Data Flywheel (Self-Improvement) ---
THRESHOLD = 50
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

QUEUE_FILE = os.path.join(DATA_DIR, 'pending_human_edits.jsonl')
CURRENT_MODEL = os.path.join(DATA_DIR, 'production_l4_generator.json')

def trigger_batch_optimization():
    if not os.path.exists(QUEUE_FILE):
        return

    with open(QUEUE_FILE, 'r') as f:
        lines = f.readlines()

    # 1. Threshold Check
    if len(lines) < THRESHOLD:
        print(f"Only {len(lines)} edits. Waiting for {THRESHOLD}.")
        return

    # 2. Format Data for DSPy
    trainset = []
    for line in lines:
        data = json.loads(line)
        trainset.append(dspy.Example(
            work_package=data["inputs"]["work_package"],
            activities=data["human_edited"],
            feedback_diff=data["diff"] # GEPA uses this diff to learn WHY it failed
        ).with_inputs('work_package', 'feedback_diff'))

    # 3. Run GEPA Optimization
    def human_alignment(example, pred, trace=None):
        return 1.0 if pred.activities == example.activities else 0.0

    try:
        from dspy.teleprompt import GEPA
        current_generator = RefineL3
        if hasattr(current_generator, 'load') and os.path.exists(CURRENT_MODEL):
            current_generator.load(CURRENT_MODEL)

        optimizer = GEPA(metric=human_alignment, track_stats=True)
        
        print("Compiling and reflecting on human diffs...")
        optimized_generator = optimizer.compile(student=current_generator, trainset=trainset)

        # 4. Deploy New Model & Clear Queue
        optimized_generator.save(CURRENT_MODEL)
        open(QUEUE_FILE, 'w').close() 
        print("Optimization complete. Smarter model deployed.")
    except Exception as e:
        print(f"Optimization error: {e}")


def tag_task(task_title: str, config_options: Dict[str, List[str]]) -> Dict[str, str]:
    """Uses DSPy to assign emoji tags to a task based on available configs."""
    predictor = dspy.Predict(TagTask)
    result = predictor(task_title=task_title, config_options=json.dumps(config_options, ensure_ascii=False))
    return result.tags

def enrich_state_with_llm(local_state: List[Dict[str, Any]], config_dict: Dict[str, List[str]]) -> List[Dict[str, Any]]:
    """
    Example runner: iterates through local state, runs tagging and splitting if needed.
    """
    for idx, task in enumerate(local_state):
        # Example: Tag if tags are empty
        if not task.get("tags"):
            import sys
            msg = f"Tagging task: {task['title']}\n"
            sys.stdout.buffer.write(msg.encode('utf-8', 'replace'))
            try:
                tags = tag_task(task["title"], config_dict)
                
                # 确定性覆盖 Theme：优先使用 context_heading 和 邻近 paragraph 匹配
                from config_reader import structure_yonctask_config, clean_task_title
                structured_cfg = structure_yonctask_config(config_dict)
                themes = structured_cfg.get("themes", {})
                
                context_heading = task.get("context_heading", "")
                
                # 清理标题：去掉已有标签、mode、emoji 等，提取纯文字
                title_words = task.get("original_notion_title", task["title"])
                clean_title = clean_task_title(title_words, structured_cfg)
                
                first_word = clean_title.split()[0].strip() if clean_title else ""
                
                # Fallback 1: 标题首词匹配
                if not context_heading and first_word:
                    context_heading = first_word
                
                found_theme_key = None
                
                # Priority 1: 用 context_heading 匹配主/子主题
                if context_heading:
                    for t_name, t_data in themes.items():
                        if context_heading == t_name or context_heading in t_data.get("sub_themes", []):
                            found_theme_key = t_name
                            break
                
                # Fallback 2: 如果仍未找到主题，向前/向后查找相邻的 paragraph 块作为 context
                if not found_theme_key:
                    for offset in [1, -1, 2, -2]:
                        neighbor_idx = idx + offset
                        if 0 <= neighbor_idx < len(local_state):
                            neighbor = local_state[neighbor_idx]
                            if neighbor.get("type") == "paragraph":
                                neighbor_title = neighbor.get("title", "").strip()
                                if not neighbor_title:
                                    continue
                                # 检查这个 paragraph 的 title 是否是某个主题的名称或子主题
                                for t_name, t_data in themes.items():
                                    if neighbor_title == t_name or neighbor_title in t_data.get("sub_themes", []):
                                        found_theme_key = t_name
                                        context_heading = neighbor_title
                                        break
                                if found_theme_key:
                                    break
                            
                # Re-build the full theme string if found (e.g., "关系 恋爱 | 婚姻 | 家庭")
                if found_theme_key:
                    for raw_theme in config_dict.get("Task Theme with colour", []):
                        raw_text = raw_theme.get("text", "") if isinstance(raw_theme, dict) else raw_theme
                        if raw_text.startswith(found_theme_key):
                            tags["Task Theme with colour"] = raw_text
                            break
                
                task["tags"] = tags
            except Exception as e:
                print(f"Failed to tag: {e}")
                
        # Example: Split if depth is shallow and it has no obvious children 
        # (This is a simplified trigger logic)
        # In a real sync engine, you'd insert these children into Notion and update the state.
        
    return local_state
