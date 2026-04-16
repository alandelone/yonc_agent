import dspy
import os
import json
import re
import time
from typing import List, Dict, Any, Optional, Set

from unlimited_llmapi import configure_dspy, configure_dspy_light

try:
    # Initialize the LM using the unlimited multi-key manager
    # Passing 'model' here ensures it's used as the primary model if config doesn't specify otherwise
    lm = configure_dspy(model="gemini/gemini-3-flash-preview")
except Exception as e:
    print(f"Critical Error: Could not configure DSPy multi-key LM: {e}")
    # Still attempt a basic setup if all else fails, but don't depend on non-existent config vars
    try:
        lm = dspy.LM("gemini/gemini-3-flash-preview")
        dspy.configure(lm=lm)
    except Exception as inner_e:
        print(f"Warning: Could not configure fallback DSPy LM: {inner_e}")

# Dedicated light-weight LM for cheap, high-frequency tasks
# (compaction / CondenseTaskDescription / CondenseTaskTitle).
# Uses the model labelled 'light_model' in api_keys.json as top priority,
# falling back to the rest of the model chain if its quota is exhausted.
try:
    light_lm = configure_dspy_light()
except Exception as e:
    print(f"Warning: Could not create light LM, will use global lm as fallback: {e}")
    light_lm = None


class SplitAbstractTask(dspy.Signature):
    """你是专为 INTP + ADHD 人群设计的“前额叶代偿引擎”。你的唯一目标是：将用户输入的、引发执行功能障碍的【宏大抽象任务】，降维打击成连草履虫都能执行的【物理肌肉动作清单】。

# Core Rules (1-2-3 Framework)
接收到用户任务后，你必须在后台严格执行以下 3 步转化，然后再输出结果：

**Step 1: 剥离抽象 (Identify & Destroy)**
- 识别并彻底抹除任务中的宏大名词与结果导向词汇（如：复习、规划、总结、大纲、完美、完成）。
- 严禁在回复中重复用户的宏大目标，切断一切可能引发“预见性焦虑”的触发点。

**Step 2: 物理降智 (Physical Translation)**
- 强制将所有“认知动作”翻译为最底层的“肌肉动作”。
- 🚫 绝对禁用词：想、决定、分类、回忆、构思、评估、整理。
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
    """
    task_title = dspy.InputField(desc="Abstract task to decompose")
    context = dspy.InputField(desc="Parent task context if any")
    sub_tasks: list[str] = dspy.OutputField(desc="List of concrete physical-action sub-tasks. Each item MUST follow the format: 'title : description'. The title is a short action name (2-6 words), the description is a one-sentence clarification.")

class TagTask(dspy.Signature):
    """Assign the best-matching tag from each config dimension."""
    task_title = dspy.InputField(desc="Task to tag")
    config_options = dspy.InputField(desc="Dict of config dimensions and their options as a JSON-like string")
    tags = dspy.OutputField(
        desc=(
            "JSON object mapping each config dimension to a chosen option text. "
            "Example: {\"Modes\": \"💻Focus\", \"Task Type\": \"🔍 Testing\"}."
        )
    )

class CondenseTaskDescription(dspy.Signature):
    """You are a bilingual Senior Software Engineer. Your task is to rewrite English technical descriptions into a highly condensed "Simplified Chinese + English Tech Jargon" format.
    
    Goal: Shorten the original text significantly to create concise, easy-to-skim notes while maintaining technical accuracy and this specific bilingual style.
    
    Instructions:
    1. Prioritize Length Over Jargon: The absolute highest priority is to minimize character count. If an English technical term or phrase consumes too many characters, forcefully translate it to its shorter Chinese equivalent (e.g., "microservices" -> "微服务", "system design" -> "系统设计").
    2. Retain Short English Acronyms: Keep well-known, concise English acronyms or terms ONLY if they save space (e.g., API, HTTP, LLM, PR, UI).
    3. Translate Connectors & Broad Concepts: Translate general descriptive words and architectural nouns into Chinese to make it shorter (e.g., central processing engine -> 中央处理引擎).
    4. Use Chinese Grammar for Brevity: Restructure the sentence to follow compact native Chinese phrasing.
    5. Format and Punctuation: Use symbols to shorten (：). When translating lists, remove filler words and use parentheses to enclose the list.
    """
    original_description = dspy.InputField(desc="The original verbose English description")
    condensed_description = dspy.OutputField(desc="The condensed bilingual text (Simplified Chinese + English Tech Jargon)")

class CondenseTaskTitle(dspy.Signature):
    """You are a bilingual Senior Software Engineer. Your task is to rewrite English task titles into a highly condensed "Simplified Chinese + English Tech Jargon" format.
    
    Goal: Shorten the original task title significantly to create a concise, easy-to-skim title while maintaining technical accuracy and this specific bilingual style.
    
    Instructions:
    1. Prioritize Length Over Jargon: If an English word or phrase is long, forcibly translate it to its shorter Chinese equivalent (e.g., "Optimization" -> "优化").
    2. Retain Short English Acronyms: Keep well-known, concise English acronyms or terms (e.g., API, HTTP, LLM, UI).
    3. Use Chinese Grammar for Brevity: Restructure the phrase to follow compact native Chinese phrasing.
    4. Maximize Brevity: Cut out unnecessary English fluff or filler words. The title should be extremely short (e.g., 2-6 words).
    """
    original_title = dspy.InputField(desc="The original verbose English title")
    condensed_title = dspy.OutputField(desc="The condensed bilingual title (Simplified Chinese + English Tech Jargon)")

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

class DeliverableItem(BaseModel):
    """通用交付物条目，包含标题和描述。"""
    title: str = Field(description="Short noun-phrase title of the deliverable (2-6 words)")
    description: str = Field(description="One-sentence clarification of what this deliverable covers")

class L2DeliverablesList(BaseModel):
    deliverables: list[DeliverableItem] = Field(description="List of Level 2 Major Deliverables. Each must have a title (Nouns only) and a description.")

class OKRMilestonesList(BaseModel):
    objective: str = Field(description="The overarching Objective (O)")
    objective_description: str = Field(description="One-sentence clarification of the objective", default="")
    key_results: list[DeliverableItem] = Field(description="List of verifiable Key Results (KRs). Each must have a title and a description.")

class L3WorkPackagesList(BaseModel):
    work_packages: list[DeliverableItem] = Field(description="List of Level 3 Work Packages. Each must have a title (Nouns only) and a description.")

class ActivityDesc(BaseModel):
    title: str = Field(description="Physical action starting with a verb (2-6 words)")
    description: str = Field(description="One-sentence clarification of this activity", default="")
    estimated_hours: float = Field(description="Expected duration in hours. Must be <= 2.0")

class L4ActivitiesList(BaseModel):
    activities: list[ActivityDesc] = Field(description="List of physical action activities. Each must have a title, description, and time estimate.")

class AtomicAction(BaseModel):
    action_type: str = Field(description="Category of action (e.g., Focus, Routine, Communicate, Admin)")
    estimated_hours: float = Field(description="Time prediction in hours")
    refined_action: str = Field(description="The highly specific, atomized physical action (2-6 words)")
    description: str = Field(description="One-sentence clarification of this atomic action", default="")

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

# 瞬态错误关键词（503 过载 / 429 限流）
_TRANSIENT_KEYWORDS = ("503", "unavailable", "overloaded", "high demand", "429", "rate")
_MAX_RETRIES = 3
_BASE_BACKOFF = 5  # 秒，实际等待为 base * 2^attempt (5, 10, 20)


def _retry_on_transient(fn, label: str, fallback, fallback_fn=None):
    """对瞬态 API 错误（503/429）自动重试，指数退避。
    
    主函数 fn 重试 _MAX_RETRIES 次后，若提供了 fallback_fn（使用不同模型），
    则切换到回退模型再重试 _MAX_RETRIES 次，全部耗尽才返回 fallback 原始值。
    """
    last_err = None
    for attempt in range(_MAX_RETRIES):
        try:
            return fn()
        except Exception as e:
            last_err = e
            msg = str(e).lower()
            if any(kw in msg for kw in _TRANSIENT_KEYWORDS):
                wait = _BASE_BACKOFF * (2 ** attempt)
                print(f"  [Retry] {label} 遇到瞬态错误 (attempt {attempt + 1}/{_MAX_RETRIES})，{wait}s 后重试...")
                time.sleep(wait)
            else:
                # 非瞬态错误，直接放弃
                print(f"Failed to {label}: {e}. Using fallback.")
                return fallback

    # 主模型重试耗尽，切换到回退模型
    if fallback_fn is not None:
        print(f"  [Retry] {label} 主模型重试耗尽，切换到回退模型...")
        for attempt in range(_MAX_RETRIES):
            try:
                return fallback_fn()
            except Exception as e:
                last_err = e
                msg = str(e).lower()
                if any(kw in msg for kw in _TRANSIENT_KEYWORDS):
                    wait = _BASE_BACKOFF * (2 ** attempt)
                    print(f"  [Retry] {label} 回退模型 (attempt {attempt + 1}/{_MAX_RETRIES})，{wait}s 后重试...")
                    time.sleep(wait)
                else:
                    print(f"Failed to {label} (fallback model): {e}. Using original.")
                    return fallback

    # 全部耗尽
    print(f"Failed to {label} after all retries: {last_err}. Using original.")
    return fallback


_DEFAULT_CLASSIFICATION = WBSClassification(rationale="Fallback", level=1, task_type="WBS")

def classify_task(task_title: str) -> WBSClassification:
    def _call():
        predictor = dspy.Predict(ClassifyTask)
        result = predictor(task_input=task_title, wbs_rules_context=WBS_CONTEXT)
        cls = result.classification
        print(f"\n[🤖 LLM LOG - Phase 1: Classification]")
        print(f"   Input : '{task_title}'")
        print(f"   Output: Level {cls.level} | Type {cls.task_type} | Rationale: {cls.rationale}")
        return cls

    return _retry_on_transient(_call, "classify task", _DEFAULT_CLASSIFICATION)



def _condense_description(description: str) -> str:
    """Invokes DSPy CondenseTaskDescription to compress English descriptions into bilingual jargon notes."""
    if not description.strip():
        return ""
    # Skip condensation for already-short descriptions to avoid unnecessary LLM calls.
    # LLM-generated DeliverableItem descriptions are typically one concise sentence.
    if len(description.strip()) < 60:
        return description.strip()

    def _call():
        predictor = dspy.Predict(CondenseTaskDescription)
        ctx = {"lm": light_lm} if light_lm is not None else {}
        with dspy.context(**ctx):
            res = predictor(original_description=description)
        return str(res.condensed_description).strip()

    def _call_global():
        """回退到全局 lm（主模型链）。"""
        predictor = dspy.Predict(CondenseTaskDescription)
        res = predictor(original_description=description)
        return str(res.condensed_description).strip()

    return _retry_on_transient(
        _call, "condense description", description,
        fallback_fn=_call_global if light_lm is not None else None,
    )

def _condense_title(title: str) -> str:
    """Invokes DSPy CondenseTaskTitle to compress English titles into bilingual jargon notes."""
    if not title.strip():
        return ""
    # Skip condensation for already-short titles to avoid unnecessary LLM calls.
    if len(title.strip()) < 20:
        return title.strip()

    def _call():
        predictor = dspy.Predict(CondenseTaskTitle)
        ctx = {"lm": light_lm} if light_lm is not None else {}
        with dspy.context(**ctx):
            res = predictor(original_title=title)
        return str(res.condensed_title).strip()

    def _call_global():
        """回退到全局 lm（主模型链）。"""
        predictor = dspy.Predict(CondenseTaskTitle)
        res = predictor(original_title=title)
        return str(res.condensed_title).strip()

    return _retry_on_transient(
        _call, "condense title", title,
        fallback_fn=_call_global if light_lm is not None else None,
    )

def _format_title_desc(title: str, description: str) -> str:
    """将标题和描述格式化为 '{title} : {description}' 格式。并进行双语提炼。"""
    title = str(title or "").strip()
    description = str(description or "").strip()
    
    if title:
        title = _condense_title(title)
        
    if description:
        condensed = _condense_description(description)
        return f"{title} : {condensed}"
    return title


def generate_l4_with_validation(task_title: str) -> List[str]:
    """生成 L4 活动并验证 2 小时约束，输出格式为 '{title} : {description}'。"""
    print(f"\n[🤖 LLM LOG - Phase 2.3: Refine L3 -> L4]")
    print(f"   Input (Work Package): '{task_title}'")
    
    predictor = dspy.Predict(RefineL3)
    result = predictor(l3_work_package=task_title, wbs_rules_context=WBS_CONTEXT)
    activities: List[ActivityDesc] = getattr(result.l4_output, 'activities', [])
    
    raw_acts_fmt = [f"{act.title} ({act.estimated_hours}h)" for act in activities]
    print(f"   Output: {raw_acts_fmt}")
    
    final_actions = []
    # 超过 2 小时的活动会被递归拆分
    for act in activities:
        if act.estimated_hours > 2.0:
            print(f"   [⚠️ LOG - Validation Rule Failed] Task '{act.title}' exceeds 2.0 hours limit. Forcing LLM to split further.")
            sub_predictor = dspy.Predict(RefineL3)
            sub_result = sub_predictor(l3_work_package=f"Breakdown this >2hr task: {act.title}", wbs_rules_context=WBS_CONTEXT)
            sub_acts = getattr(sub_result.l4_output, 'activities', [])
            
            sub_acts_fmt = [f"{sub.title} ({sub.estimated_hours}h)" for sub in sub_acts]
            print(f"   [🔄 LOG - Re-split Output]: {sub_acts_fmt}")
            
            for sub in sub_acts:
                 final_actions.append(_format_title_desc(sub.title, getattr(sub, 'description', '')))
        else:
            final_actions.append(_format_title_desc(act.title, getattr(act, 'description', '')))
    return final_actions

def split_task(task_title: str, context: str = "") -> List[str]:
    """使用 DSPy 4-Level WBS Pipeline 分解任务，输出格式统一为 '{title} : {description}'。"""
    try:
        # Step 1: 垂直分类
        cls_result = classify_task(task_title)
        
        # Step 2: 水平细化
        if cls_result.level == 1:
            if cls_result.task_type == "OKR":
                print(f"\n[🤖 LLM LOG - Phase 2.1: Refine L1 (OKR)]")
                print(f"   Input (Exploratory Goal): '{task_title}'")
                predictor = dspy.Predict(RefineL1OKR)
                res = predictor(l1_exploratory_goal=task_title)
                okr = res.okr_output
                obj_desc = getattr(okr, 'objective_description', '')
                print(f"   Output: Objective='{okr.objective}' | KRs={[kr.title for kr in okr.key_results]}")
                results = [_format_title_desc(okr.objective, obj_desc)]
                for kr in okr.key_results:
                    kr_title = kr.title if isinstance(kr, DeliverableItem) else str(kr)
                    kr_desc = kr.description if isinstance(kr, DeliverableItem) else ''
                    results.append(_format_title_desc(kr_title, kr_desc))
                return results
            else:
                print(f"\n[🤖 LLM LOG - Phase 2.1: Refine L1 (WBS)]")
                print(f"   Input (Deterministic Goal): '{task_title}'")
                predictor = dspy.Predict(RefineL1WBS)
                res = predictor(l1_goal=task_title, wbs_rules_context=WBS_CONTEXT)
                deliverables = res.l2_output.deliverables
                print(f"   Output: Deliverables={[d.title for d in deliverables]}")
                return [_format_title_desc(d.title, d.description) for d in deliverables]
                
        elif cls_result.level == 2:
            print(f"\n[🤖 LLM LOG - Phase 2.2: Refine L2]")
            print(f"   Input (Major Deliverable): '{task_title}'")
            predictor = dspy.Predict(RefineL2)
            res = predictor(l2_deliverable=task_title, wbs_rules_context=WBS_CONTEXT)
            work_packages = res.l3_output.work_packages
            print(f"   Output: Work Packages={[wp.title for wp in work_packages]}")
            return [_format_title_desc(wp.title, wp.description) for wp in work_packages]
            
        elif cls_result.level == 3:
            return generate_l4_with_validation(task_title)
            
        elif cls_result.level == 4:
            print(f"\n[🤖 LLM LOG - Phase 2.4: Refine L4]")
            print(f"   Input (Atomic Action): '{task_title}'")
            predictor = dspy.Predict(RefineL4)
            res = predictor(l4_action=task_title)
            atomic = res.atomic_output
            desc = getattr(atomic, 'description', '')
            print(f"   Output: Type={atomic.action_type} | Hours={atomic.estimated_hours} | Action='{atomic.refined_action}'")
            return [_format_title_desc(atomic.refined_action, desc)]
            
        else:
            return [task_title]
    except Exception as e:
        print(f"\n[🚫 LLM LOG - Pipeline Error]: {e}. Falling back to default Predict.")
        try:
            # 绝对兜底
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
    def _normalize_prediction(raw: Any) -> Dict[str, str]:
        if isinstance(raw, dict):
            data = raw
        elif isinstance(raw, str):
            text = raw.strip()
            if not text:
                return {}
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                return {}
        else:
            return {}

        cleaned: Dict[str, str] = {}
        for key in config_options.keys():
            val = data.get(key)
            if isinstance(val, str):
                val = val.strip()
                if val:
                    cleaned[key] = val
        return cleaned

    predictor = dspy.Predict(TagTask)
    result = predictor(task_title=task_title, config_options=json.dumps(config_options, ensure_ascii=False))

    # Structured output path.
    normalized = _normalize_prediction(getattr(result, "tags", None))
    if normalized:
        return normalized

    # Fallback path for providers that emit raw text into another field.
    for attr in ("answer", "output", "response", "text"):
        normalized = _normalize_prediction(getattr(result, attr, None))
        if normalized:
            return normalized

    return {}

def theme_pass(local_state: List[Dict[str, Any]], config_dict: Dict[str, List[Any]]) -> List[Dict[str, Any]]:
    """
    L1 deterministic pass:
    - infer and normalize theme assignment
    - keep only theme tag visible at this stage
    """
    from config_reader import structure_yonctask_config
    import re
    
    structured_cfg = structure_yonctask_config(config_dict)
    themes = structured_cfg.get("themes", {})

    def _normalize_title_for_theme_match(text: str) -> str:
        t = str(text or "").strip()
        if not t:
            return ""
        # strip old generated wrappers and markdown-like markers
        t = re.sub(r'^\[.*?\]\s*', '', t).strip()
        t = t.replace("`", "").replace("*", "").strip()
        # strip a leading emoji block (e.g., stale WBS prefix)
        t = re.sub(r'^(?:[^\w\s\x00-\x7F\|()\[\]\-:.,]|[\d*#]\uFE0F?\u20E3)+\s*', '', t).strip()
        return t

    def _match_theme_or_subtheme(text: str) -> tuple[str | None, str | None]:
        raw = str(text or "").strip()
        normalized = _normalize_title_for_theme_match(raw)

        for t_name, t_data in themes.items():
            if raw == t_name or normalized == t_name:
                return (t_name, t_name)
            for st in t_data.get("sub_themes", []):
                if raw == st or normalized == st:
                    return (t_name, st)
        return (None, None)

    def _extract_theme_prefixed_label(text: str) -> tuple[str | None, str | None]:
        normalized = _normalize_title_for_theme_match(text)
        for t_name in themes.keys():
            prefix = f"{t_name} "
            if normalized.startswith(prefix):
                suffix = normalized[len(prefix):].strip()
                if suffix:
                    return (t_name, suffix)
        return (None, None)

    def _find_theme_from_ancestor_prefix(task: Dict[str, Any]) -> tuple[str | None, str | None]:
        """
        Infer theme from flattened ancestor prefix in task["title"].
        Example title: "PhDSettle✒ Review Sustainable ..."
        original_notion_title: "Sustainable ..."
        ancestor prefix becomes "PhDSettle✒ Review", and we pick the nearest
        matching theme/sub-theme from the right side.
        """
        full_title = str(task.get("title", "") or "").strip()
        original_title = str(task.get("original_notion_title", "") or "").strip()
        if not full_title or not original_title:
            return (None, None)

        if full_title.endswith(original_title):
            ancestor_prefix = full_title[:-len(original_title)].strip()
        else:
            ancestor_prefix = full_title
            
        search_target = ancestor_prefix if ancestor_prefix else original_title
        if not search_target:
            return (None, None)

        best_sub_match = None
        best_main_match = None

        for t_name, t_data in themes.items():
            # 1. Search subthemes first
            for st in t_data.get("sub_themes", []):
                ct = str(st or "").strip()
                if not ct: continue
                pos = search_target.find(ct)
                if pos >= 0:
                    key = (-pos, len(ct))
                    if (best_sub_match is None) or (key > (best_sub_match[0], best_sub_match[1])):
                        best_sub_match = (pos, len(ct), t_name, ct)
                        
            # 2. Search main themes fallback
            ct = str(t_name or "").strip()
            if ct:
                pos = search_target.find(ct)
                if pos >= 0:
                    key = (-pos, len(ct))
                    if (best_main_match is None) or (key > (best_main_match[0], best_main_match[1])):
                        best_main_match = (pos, len(ct), t_name, ct)

        if best_sub_match:
            return (best_sub_match[2], best_sub_match[3])
        if best_main_match:
            return (best_main_match[2], best_main_match[3])
        return (None, None)

    parent_ids = {
        str(t.get("parent_id"))
        for t in local_state
        if t.get("parent_id")
    }
    task_by_id: Dict[str, Dict[str, Any]] = {}
    for t in local_state:
        tid = str(t.get("notion_block_id") or t.get("id") or "")
        if tid:
            task_by_id[tid] = t

    def _find_theme_from_parent_chain(task: Dict[str, Any]) -> tuple[str | None, str | None, int]:
        """
        Walk parent -> parent of parent ... and return:
        (theme_key, matched_text, consecutive_theme_ancestor_count_from_direct_parent)
        """
        first_theme_key = None
        first_match_text = None
        consecutive_theme_ancestors = 0
        counting_consecutive = True

        parent_id = str(task.get("parent_id") or "")
        seen = set()
        while parent_id and parent_id not in seen:
            seen.add(parent_id)
            parent = task_by_id.get(parent_id)
            if not parent:
                break

            parent_title = parent.get("original_notion_title", parent.get("title", ""))
            matched_theme_key, matched_text = _match_theme_or_subtheme(parent_title)
            if not matched_theme_key:
                matched_theme_key, matched_text = _extract_theme_prefixed_label(parent_title)

            if matched_theme_key and first_theme_key is None:
                first_theme_key = matched_theme_key
                first_match_text = matched_text

            if counting_consecutive:
                if matched_theme_key:
                    consecutive_theme_ancestors += 1
                else:
                    counting_consecutive = False

            parent_id = str(parent.get("parent_id") or "")

        return (first_theme_key, first_match_text, consecutive_theme_ancestors)

    for idx, task in enumerate(local_state):
        title_words = task.get("original_notion_title", task.get("title", ""))
        tags = task.get("tags") or {}
        task_id = str(task.get("notion_block_id") or task.get("id") or "")
        is_parent_container = bool(task_id and task_id in parent_ids)
        own_theme_key, own_theme_match = _match_theme_or_subtheme(title_words)
        
        is_theme_container = bool(
            is_parent_container
            and own_theme_key
            and own_theme_match == own_theme_key
        )

        if is_theme_container:
            task["wbs_level"] = None
            task["tags"] = {}
            continue

        ancestor_theme_key, ancestor_match_text, theme_depth_offset = _find_theme_from_parent_chain(task)
        if theme_depth_offset > 0 and isinstance(task.get("depth"), int):
            task["depth"] = max(0, int(task.get("depth")) - theme_depth_offset)

        context_heading = task.get("context_heading", "")
        context_from_title_fallback = False

        found_theme_key = None

        # Priority 1: direct parent -> parent of parent chain
        if ancestor_theme_key:
            found_theme_key = ancestor_theme_key
            if ancestor_match_text:
                context_heading = ancestor_match_text
                context_from_title_fallback = False

        # Priority 2: explicit context heading parsing from the string natively
        if not found_theme_key:
            ancest_theme_key, ancest_match_text = _find_theme_from_ancestor_prefix(task)
            if ancest_theme_key:
                found_theme_key = ancest_theme_key
                if ancest_match_text:
                    context_heading = ancest_match_text
                    context_from_title_fallback = False

        # Priority 3: explicitly given context heading
        if not found_theme_key and context_heading:
            for t_name, t_data in themes.items():
                if context_heading == t_name or context_heading in t_data.get("sub_themes", []):
                    found_theme_key = t_name
                    break

        if not found_theme_key:
            for offset in [1, -1, 2, -2]:
                neighbor_idx = idx + offset
                if 0 <= neighbor_idx < len(local_state):
                    neighbor = local_state[neighbor_idx]
                    if neighbor.get("type") == "paragraph":
                        neighbor_title = neighbor.get("title", "").strip()
                        if not neighbor_title:
                            continue
                        for t_name, t_data in themes.items():
                            if neighbor_title == t_name or neighbor_title in t_data.get("sub_themes", []):
                                found_theme_key = t_name
                                context_heading = neighbor_title
                                context_from_title_fallback = False
                                break
                        if found_theme_key:
                            break

        new_tags: Dict[str, Any] = {}
        if found_theme_key:
            display_label = found_theme_key
            if context_heading and not context_from_title_fallback and context_heading != found_theme_key:
                display_label = context_heading
            task["theme_display_label"] = display_label
            for raw_theme in config_dict.get("Task Theme with colour", []):
                raw_text = raw_theme.get("text", "") if isinstance(raw_theme, dict) else raw_theme
                if raw_text.startswith(found_theme_key):
                    new_tags["Task Theme with colour"] = raw_text
                    break
        else:
            task.pop("theme_display_label", None)
            if "Task Theme with colour" in tags:
                new_tags["Task Theme with colour"] = tags["Task Theme with colour"]

        task["tags"] = new_tags


    return local_state


def _extract_priority_options_in_order(config_dict: Dict[str, List[Any]]) -> List[str]:
    ordered: List[str] = []
    for item in config_dict.get("Priority", []):
        text = item.get("text", "") if isinstance(item, dict) else str(item)
        text = str(text or "").strip()
        if not text:
            continue
        ordered.append(text)
    return ordered


def _extract_priority_options_by_level(config_dict: Dict[str, List[Any]]) -> Dict[str, str]:
    by_level: Dict[str, str] = {}
    for raw in _extract_priority_options_in_order(config_dict):
        text = str(raw or "").strip()
        if not text:
            continue
        match = re.search(r"\((P[^)]+)\)", text, flags=re.IGNORECASE)
        if match:
            by_level[str(match.group(1)).strip().upper()] = text
            continue

        inline = re.search(r"\b(P\d+)\b", text, flags=re.IGNORECASE)
        if inline:
            by_level[str(inline.group(1)).strip().upper()] = text
    return by_level


def _resolve_wbs_tag_from_struct(structured_cfg: Dict[str, Any], level: int) -> str:
    levels = structured_cfg.get("wbs_levels", {})
    entry = levels.get(level)
    if isinstance(entry, dict):
        return str(entry.get("raw") or entry.get("emoji") or "").strip()
    for key, val in levels.items():
        if str(level) in str(key):
            if isinstance(val, dict):
                return str(val.get("raw") or val.get("emoji") or "").strip()
            return str(val).strip()
    return ""


def _infer_wbs_from_text(value: str) -> Optional[int]:
    if not value:
        return None
    match = re.search(r"([1-4])", str(value))
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None

def wbs_pass(
    local_state: List[Dict[str, Any]],
    config_dict: Dict[str, List[Any]],
    scoped_ids: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """
    L2.1 pass:
    - assign WBS only for scoped tasks
    - parent-first propagation
    - preserve manual WBS when present
    """
    from block_info_reader import build_block_info_for_state
    from config_reader import clean_task_title, structure_yonctask_config

    scoped_ids = scoped_ids or set()
    structured_cfg = structure_yonctask_config(config_dict)
    by_id: Dict[str, Dict[str, Any]] = {}
    for task in local_state:
        task_id = str(task.get("notion_block_id") or task.get("id") or "")
        if task_id:
            by_id[task_id] = task

    tasks_sorted = sorted(
        local_state,
        key=lambda t: (
            int(t.get("depth", 0)) if str(t.get("depth", 0)).isdigit() else 0,
            str(t.get("notion_block_id") or t.get("id") or ""),
        ),
    )

    for task in tasks_sorted:
        task_id = str(task.get("notion_block_id") or task.get("id") or "")
        if not task_id or task_id not in scoped_ids:
            continue

        tags = task.get("tags") or {}
        existing_level = task.get("wbs_level")
        if isinstance(existing_level, str) and existing_level.isdigit():
            existing_level = int(existing_level)

        existing_wbs_tag = str(tags.get("WBS level", "")).strip()
        inferred_existing = _infer_wbs_from_text(existing_wbs_tag)
        manual_level = existing_level if isinstance(existing_level, int) else inferred_existing

        parent = by_id.get(str(task.get("parent_id") or ""))
        parent_level = None
        if parent:
            pl = parent.get("wbs_level")
            if isinstance(pl, str) and pl.isdigit():
                pl = int(pl)
            if isinstance(pl, int):
                parent_level = pl

        depth = task.get("depth")
        try:
            depth = int(depth)
        except (TypeError, ValueError):
            depth = 0

        if isinstance(manual_level, int):
            level = manual_level
            source = "manual"
        else:
            if depth == 0:
                level = 1
            elif depth == 1:
                level = None
                title_words = task.get("original_notion_title", task.get("title", ""))
                clean_title = clean_task_title(title_words, structured_cfg)
                try:
                    block_info = build_block_info_for_state(local_state, task, max_chars=3500)
                    context = json.dumps(block_info, ensure_ascii=False)
                except Exception:
                    context = ""

                try:
                    cls = classify_task(f"{clean_title}\n{context}" if context else clean_title)
                    level = 1 if cls.task_type == "OKR" else cls.level
                except Exception as exc:
                    print(f"Failed to classify WBS for {task_id}: {exc}")
                    level = None
            else:
                # depth > 1: Skip LLM classification and rely entirely on parent level fallback
                level = None

            if not isinstance(level, int):
                if isinstance(parent_level, int):
                    level = min(4, max(1, parent_level + 1))
                else:
                    level = 1
            source = "auto"

        if isinstance(parent_level, int) and level <= parent_level:
            level = min(4, parent_level + 1)

        level = max(1, min(4, int(level)))
        task["wbs_level"] = level
        task["wbs_source"] = source

        wbs_tag = _resolve_wbs_tag_from_struct(structured_cfg, level)
        if wbs_tag:
            tags["WBS level"] = wbs_tag
        task["tags"] = tags

    return local_state


def mode_tasktype_pass(
    local_state: List[Dict[str, Any]],
    config_dict: Dict[str, List[Any]],
    scoped_ids: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """
    L3 pass:
    - assign Modes + Task Type for scoped tasks at WBS>=3.
    """
    from config_reader import clean_task_title, structure_yonctask_config

    scoped_ids = scoped_ids or set()
    structured_cfg = structure_yonctask_config(config_dict)

    llm_options: Dict[str, List[Any]] = {}
    if "Modes" in config_dict:
        llm_options["Modes"] = config_dict.get("Modes", [])
    if "Task Type" in config_dict:
        llm_options["Task Type"] = config_dict.get("Task Type", [])
    if not llm_options:
        return local_state

    for task in local_state:
        task_id = str(task.get("notion_block_id") or task.get("id") or "")
        if not task_id or task_id not in scoped_ids:
            continue

        level = task.get("wbs_level")
        if isinstance(level, str) and level.isdigit():
            level = int(level)
        if not isinstance(level, int) or level < 3:
            continue

        tags = task.get("tags") or {}
        raw_title = task.get("original_notion_title", task.get("title", ""))
        clean_title = clean_task_title(raw_title, structured_cfg)

        try:
            generated = tag_task(clean_title, llm_options)
            mode_val = generated.get("Modes")
            type_val = generated.get("Task Type")
            if mode_val:
                tags["Modes"] = mode_val
            if type_val:
                tags["Task Type"] = type_val
        except Exception as exc:
            print(f"Failed mode/task-type tagging for {task_id}: {exc}")

        task["tags"] = tags

    return local_state


def priority_pass(
    local_state: List[Dict[str, Any]],
    config_dict: Dict[str, List[Any]],
    scoped_ids: Optional[Set[str]] = None,
    rank_by_task_id: Optional[Dict[str, int]] = None,
) -> List[Dict[str, Any]]:
    """
    L2.3 pass:
    - overwrite Priority only for scoped tasks under TIMELINER main_projects
    - use timeliner_state priority order and map to fixed buckets:
      idx 0 -> P0, idx 1-2 -> P1, idx >=3 -> P2
    """
    scoped_ids = scoped_ids or set()
    rank_by_task_id = rank_by_task_id or {}
    priority_options = _extract_priority_options_in_order(config_dict)
    if not priority_options:
        return local_state

    by_level = _extract_priority_options_by_level(config_dict)
    p0_val = by_level.get("P0") or (priority_options[1] if len(priority_options) > 1 else priority_options[0])
    p1_val = by_level.get("P1") or (priority_options[2] if len(priority_options) > 2 else priority_options[-1])
    p2_val = by_level.get("P2") or (priority_options[3] if len(priority_options) > 3 else priority_options[-1])

    def _to_int(value: Any, default: int = 10**9) -> int:
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        return default

    emoji_pattern = re.compile(r'(?:[^\w\s\x00-\x7F\|()\[\]\-:.,]|[\d*#]\uFE0F?\u20E3)+')
    def _extract_emoji(val: Any) -> str:
        match = emoji_pattern.search(str(val))
        return match.group() if match else ""

    # Parse manual priorities from Notion title for ALL tasks
    for task in local_state:
        title = task.get("original_notion_title", task.get("title", ""))
        tags = task.get("tags") or {}
        found_p = None
        for opt in priority_options:
            e = _extract_emoji(opt)
            if e and e in title:
                found_p = opt
                break
        if found_p is not None:
            tags["Priority"] = found_p
            task["tags"] = tags

    main_scoped_tasks: List[Dict[str, Any]] = []
    for task in local_state:
        task_id = str(task.get("notion_block_id") or task.get("id") or "")
        section = str(task.get("timeliner_section", "") or "").strip().lower()
        is_root = _to_int(task.get("depth", 0), 0) == 0
        if task_id and task_id in scoped_ids and section == "main" and is_root:
            main_scoped_tasks.append(task)

    # Fallback for runs without state-file section metadata:
    # if no explicit "main" tasks are available, treat blank-section non-subproject
    # tasks as main projects so Priority can still be assigned deterministically.
    if not main_scoped_tasks:
        for task in local_state:
            task_id = str(task.get("notion_block_id") or task.get("id") or "")
            section = str(task.get("timeliner_section", "") or "").strip().lower()
            is_subproject = bool(task.get("timeliner_is_subproject"))
            is_root = _to_int(task.get("depth", 0), 0) == 0
            if task_id and task_id in scoped_ids and not section and not is_subproject and is_root:
                main_scoped_tasks.append(task)

    main_scoped_tasks.sort(
        key=lambda t: (
            _to_int(t.get("timeliner_priority")),
            rank_by_task_id.get(str(t.get("notion_block_id") or t.get("id") or ""), 10**9),
            _to_int(t.get("depth", 0), 0),
            str(t.get("notion_block_id") or t.get("id") or ""),
        )
    )

    for idx, task in enumerate(main_scoped_tasks):
        if idx == 0:
            priority_val = p0_val
        elif idx in (1, 2):
            priority_val = p1_val
        else:
            priority_val = p2_val
        tags = task.get("tags") or {}
        tags["Priority"] = priority_val
        task["tags"] = tags

    return local_state
