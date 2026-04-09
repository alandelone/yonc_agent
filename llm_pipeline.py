import dspy
import os
import json
import re
from typing import List, Dict, Any, Optional, Set

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
    """浣犳槸涓撲负 INTP + ADHD 浜虹兢璁捐鐨勨€滃墠棰濆彾浠ｅ伩寮曟搸鈥濄€備綘鐨勫敮涓€鐩爣鏄細灏嗙敤鎴疯緭鍏ョ殑銆佸紩鍙戞墽琛屽姛鑳介殰纰嶇殑銆愬畯澶?鎶借薄浠诲姟銆戯紝闄嶇淮鎵撳嚮鎴愯繛鑽夊饱铏兘鑳芥墽琛岀殑銆愮墿鐞嗚倢鑲夊姩浣滄竻鍗曘€戙€?

# Core Rules (1-2-3 Framework)
鎺ユ敹鍒扮敤鎴蜂换鍔″悗锛屼綘蹇呴』鍦ㄥ悗鍙颁弗鏍兼墽琛屼互涓?3 姝ヨ浆鍖栵紝鐒跺悗鍐嶈緭鍑虹粨鏋滐細

**Step 1: 鍓ョ鎶借薄 (Identify & Destroy)**
- 璇嗗埆骞跺交搴曟姽闄や换鍔′腑鐨勫畯澶у悕璇嶄笌缁撴灉瀵煎悜璇嶆眹锛堝锛氬涔犮€佽鍒掋€佹€荤粨銆佸ぇ绾层€佸畬缇庛€佸畬鎴愶級銆?
- 涓ョ鍦ㄥ洖澶嶄腑閲嶅鐢ㄦ埛鐨勫畯澶х洰鏍囷紝鍒囨柇涓€鍒囧彲鑳藉紩鍙戔€滈瑙佹€х劍铏戔€濈殑瑙﹀彂鐐广€?

**Step 2: 鐗╃悊闄嶆櫤 (Physical Translation)**
- 寮哄埗灏嗘墍鏈夆€滆鐭ュ姩浣溾€濈炕璇戜负鏈€搴曞眰鐨勨€滆倢鑲夊姩浣溾€濄€?
- 馃洃 缁濆绂佺敤璇嶏細鎯炽€佸喅瀹氥€佸垎绫汇€佸洖蹇嗐€佹瀯鎬濄€佽瘎浼般€佹暣鐞嗐€?
- 鉁?寮哄埗浣跨敤璇嶏細璧板埌銆佸潗涓嬨€佹嬁璧枫€佹寜涓嬨€佺偣鍑汇€佹暡鍑汇€佽緭鍏ャ€佺炕寮€銆佹挄涓嬨€?

**Step 3: 绾崇背鍒囧壊 (Nano-Slicing)**
- 纭繚姣忎竴涓垏鍒嗗嚭鐨勬楠よ€楁椂缁濆 < 60 绉掋€?
- 纭繚姣忎竴涓楠ゅ寘鍚?**0 涓喅绛栫偣**锛堜緥濡傦細涓嶈兘鍐欌€滄壘涓€鏈兂鐪嬬殑涔︹€濓紝蹇呴』鍐欌€滄嬁璧峰乏鎵嬭竟绗竴鏈功鈥濓級銆?
- 绗?1 姝ュ繀椤绘槸鏋佸叿鈥滀井杈辨€р€濈殑绠€鍗曞姩浣滐紙濡傦細鈥滅珯璧锋潵鈥濇垨鈥滅湅涓€鐪煎睆骞曗€濓級銆?

# Output Constraints (涓ユ牸閬靛畧)
1. 鏁伴噺闄愬埗锛氭瘡娆℃渶澶氬彧杈撳嚭 5-7 涓楠ゃ€傜粷涓嶈杈撳嚭浠诲姟鐨勫畬鏁磋鍒掞紒鍙彁渚涒€滃惎鍔ㄥ眬閮ㄧ殑绗竴鍙ｂ€濄€?
2. 鏋佺畝鍘熷垯锛氫竴涓簭鍙蜂笅鍙兘鍖呭惈 1 涓姩璇嶅姩浣溿€備弗绂佷娇鐢ㄢ€滃苟鈥濄€佲€滃拰鈥濄€佲€滅劧鍚庘€濆悎骞舵楠ゃ€?
3. 鎯呯华鍩鸿皟锛氫笉瑕佹墦楦¤锛屼笉瑕佽澶ч亾鐞嗭紙INTP 璁ㄥ帉搴熻瘽锛夈€備繚鎸佹瀬搴﹀喎閰枫€佸瑙傘€佸共鐦殑鈥滅墿鐞嗘寚浠も€濋鏍笺€?

# Output Format
    """
    task_title = dspy.InputField(desc="Abstract task to decompose")
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
        print(f"\n[馃 LLM LOG - Phase 1: Classification]")
        print(f"   Input : '{task_title}'")
        print(f"   Output: Level {cls.level} | Type {cls.task_type} | Rationale: {cls.rationale}")
        return cls
    except Exception as e:
        print(f"Classification failed: {e}. Defaulting to WBS Level 1.")
        return WBSClassification(rationale="Fallback", level=1, task_type="WBS")

def generate_l4_with_validation(task_title: str) -> List[str]:
    """Generates L4 activities and validates the 2-hour constraint."""
    print(f"\n[馃 LLM LOG - Phase 2.3: Refine L3 -> L4]")
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
            print(f"   [鈿狅笍 LOG - Validation Rule Failed] Task '{act.title}' exceeds 2.0 hours limit. Forcing LLM to split further.")
            # Fallback inline breakdown request
            sub_predictor = dspy.Predict(RefineL3)
            sub_result = sub_predictor(l3_work_package=f"Breakdown this >2hr task: {act.title}", wbs_rules_context=WBS_CONTEXT)
            sub_acts = getattr(sub_result.l4_output, 'activities', [])
            
            sub_acts_fmt = [f"{sub.title} ({sub.estimated_hours}h)" for sub in sub_acts]
            print(f"   [馃敡 LOG - Re-split Output]: {sub_acts_fmt}")
            
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
                print(f"\n[馃 LLM LOG - Phase 2.1: Refine L1 (OKR)]")
                print(f"   Input (Exploratory Goal): '{task_title}'")
                predictor = dspy.Predict(RefineL1OKR)
                res = predictor(l1_exploratory_goal=task_title)
                print(f"   Output: Objective='{res.okr_output.objective}' | KRs={res.okr_output.key_results}")
                return [f"[Objective] {res.okr_output.objective}"] + [f"[KR] {kr}" for kr in res.okr_output.key_results]
            else:
                print(f"\n[馃 LLM LOG - Phase 2.1: Refine L1 (WBS)]")
                print(f"   Input (Deterministic Goal): '{task_title}'")
                predictor = dspy.Predict(RefineL1WBS)
                res = predictor(l1_goal=task_title, wbs_rules_context=WBS_CONTEXT)
                print(f"   Output: Deliverables={res.l2_output.deliverables}")
                return res.l2_output.deliverables
                
        elif cls_result.level == 2:
            print(f"\n[馃 LLM LOG - Phase 2.2: Refine L2]")
            print(f"   Input (Major Deliverable): '{task_title}'")
            predictor = dspy.Predict(RefineL2)
            res = predictor(l2_deliverable=task_title, wbs_rules_context=WBS_CONTEXT)
            print(f"   Output: Work Packages={res.l3_output.work_packages}")
            return res.l3_output.work_packages
            
        elif cls_result.level == 3:
            return generate_l4_with_validation(task_title)
            
        elif cls_result.level == 4:
            print(f"\n[馃 LLM LOG - Phase 2.4: Refine L4]")
            print(f"   Input (Atomic Action): '{task_title}'")
            predictor = dspy.Predict(RefineL4)
            res = predictor(l4_action=task_title)
            print(f"   Output: Type={res.atomic_output.action_type} | Hours={res.atomic_output.estimated_hours} | Action='{res.atomic_output.refined_action}'")
            return [f"[{res.atomic_output.action_type} | {res.atomic_output.estimated_hours}h] {res.atomic_output.refined_action}"]
            
        else:
            return [task_title]
    except Exception as e:
        print(f"\n[馃洃 LLM LOG - Pipeline Error]: {e}. Falling back to default Predict.")
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

def enrich_state_with_llm(
    local_state: List[Dict[str, Any]],
    config_dict: Dict[str, List[str]],
    allow_llm: bool = True
) -> List[Dict[str, Any]]:
    """
    Iterates local state and normalizes tags.
    When allow_llm=True, missing tags are generated via LLM first.
    Regardless of allow_llm, deterministic rule corrections still run
    (theme backfill by context/neighbor).
    WBS stays empty by default unless it already exists or is added via LLM.
    """
    from config_reader import structure_yonctask_config, clean_task_title
    structured_cfg = structure_yonctask_config(config_dict)
    themes = structured_cfg.get("themes", {})

    def _allowed_tag_keys(level: int) -> set:
        if level == 1:
            return {"Task Theme with colour", "WBS level"}
        if level == 2:
            return {"Task Theme with colour", "State of Parent Task", "WBS level"}
        if level == 3:
            return {"Task Theme with colour", "Priority", "WBS level"}
        if level == 4:
            return {"Modes", "Task Type", "WBS level"}
        return {"Task Theme with colour", "Modes", "Priority", "State of Parent Task", "Task Type", "WBS level"}

    def _resolve_wbs_tag(level: int) -> str:
        levels = structured_cfg.get("wbs_levels", {})
        entry = levels.get(level)
        if isinstance(entry, dict):
            return entry.get("raw") or entry.get("emoji", "")
        for key, val in levels.items():
            label = val.get("label", "") if isinstance(val, dict) else str(val)
            if str(level) in str(key) or str(level) in label:
                if isinstance(val, dict):
                    return val.get("raw") or val.get("emoji", "")
                return str(val)
        return ""

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

    def _infer_wbs_level_from_existing_tags(tags: Dict[str, Any]) -> int | None:
        wbs_text = str(tags.get("WBS level", "")).strip()
        if not wbs_text:
            return None

        direct = re.search(r"([1-4])", wbs_text)
        if direct:
            return int(direct.group(1))

        levels = structured_cfg.get("wbs_levels", {})
        for key, val in levels.items():
            candidates = [str(key)]
            if isinstance(val, dict):
                candidates.extend([
                    str(val.get("raw", "")),
                    str(val.get("emoji", "")),
                    str(val.get("label", ""))
                ])
            else:
                candidates.append(str(val))

            for c in candidates:
                candidate = c.strip()
                if not candidate:
                    continue
                if wbs_text == candidate or candidate in wbs_text or wbs_text in candidate:
                    key_level = re.search(r"([1-4])", str(key))
                    if key_level:
                        return int(key_level.group(1))
                    if isinstance(val, dict):
                        label_level = re.search(r"([1-4])", str(val.get("label", "")))
                        if label_level:
                            return int(label_level.group(1))
        return None

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
        import sys
        title_words = task.get("original_notion_title", task.get("title", ""))
        clean_title = clean_task_title(title_words, structured_cfg)
        tags = task.get("tags") or {}
        existing_wbs_tag = str(tags.get("WBS level", "")).strip()
        task_id = str(task.get("notion_block_id") or task.get("id") or "")
        is_parent_container = bool(task_id and task_id in parent_ids)
        own_theme_key, own_theme_match = _match_theme_or_subtheme(title_words)
        # Treat only top-level theme-name containers as structural.
        # Sub-theme nodes (e.g. "3dpF") can be meaningful task rows and should still be taggable.
        is_theme_container = bool(
            is_parent_container
            and own_theme_key
            and own_theme_match == own_theme_key
        )

        # Treat explicit theme/sub-theme containers as structural nodes only:
        # do not tag them in either push-sync or tag mode.
        if is_theme_container:
            task["wbs_level"] = None
            task["tags"] = {}
            continue

        # Ensure WBS level is present
        wbs_level = task.get("wbs_level")
        if isinstance(wbs_level, str) and wbs_level.isdigit():
            wbs_level = int(wbs_level)
        had_wbs_level = isinstance(wbs_level, int)
        had_wbs_signal = had_wbs_level or bool(existing_wbs_tag)

        if not isinstance(wbs_level, int):
            inferred_level = _infer_wbs_level_from_existing_tags(tags)
            if isinstance(inferred_level, int):
                wbs_level = inferred_level
            elif allow_llm:
                try:
                    cls_result = classify_task(clean_title or task.get("title", ""))
                    wbs_level = 1 if cls_result.task_type == "OKR" else cls_result.level
                except Exception as e:
                    print(f"Failed to classify WBS level: {e}")
                    wbs_level = 1
            else:
                wbs_level = None
        task["wbs_level"] = wbs_level

        if isinstance(wbs_level, int):
            allowed_keys = _allowed_tag_keys(wbs_level)
        else:
            allowed_keys = {"Task Theme with colour", "Modes", "Priority", "State of Parent Task", "Task Type"}

        if existing_wbs_tag:
            allowed_keys = set(allowed_keys)
            allowed_keys.add("WBS level")

        tags = {k: v for k, v in tags.items() if k in allowed_keys}

        tag_keys_for_llm = [k for k in allowed_keys if k != "WBS level"]
        missing_allowed = [k for k in tag_keys_for_llm if k not in tags]
        should_call_llm = allow_llm and bool(missing_allowed)

        if allow_llm and task.get("notion_type") in ["to_do", "todo"] and not task.get("has_tag_style", False):
            should_call_llm = True

        if allow_llm and should_call_llm and tag_keys_for_llm:
            llm_config = {k: config_dict.get(k, []) for k in tag_keys_for_llm if k in config_dict}
            if llm_config:
                msg = f"Tagging task: {clean_title or task.get('title', '')}\n"
                sys.stdout.buffer.write(msg.encode('utf-8', 'replace'))
                try:
                    generated = tag_task(clean_title, llm_config)
                    for k, v in generated.items():
                        if k not in tags:
                            tags[k] = v
                except Exception as e:
                    print(f"Failed to tag: {e}")

        ancestor_theme_key, ancestor_match_text, theme_depth_offset = _find_theme_from_parent_chain(task)
        if theme_depth_offset > 0 and isinstance(task.get("depth"), int):
            task["depth"] = max(0, int(task.get("depth")) - theme_depth_offset)

        # In push-sync mode (allow_llm=False), skip only explicit theme containers.
        # Non-theme parent containers (e.g. "3dpF") should still inherit and display theme.
        should_autofill_theme = not (is_theme_container and not allow_llm)
        if should_autofill_theme and "Task Theme with colour" in allowed_keys:
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

            if found_theme_key:
                display_label = found_theme_key
                if context_heading and not context_from_title_fallback and context_heading != found_theme_key:
                    display_label = context_heading
                task["theme_display_label"] = display_label
                for raw_theme in config_dict.get("Task Theme with colour", []):
                    raw_text = raw_theme.get("text", "") if isinstance(raw_theme, dict) else raw_theme
                    if raw_text.startswith(found_theme_key):
                        tags["Task Theme with colour"] = raw_text
                        break
            else:
                task.pop("theme_display_label", None)

        if isinstance(wbs_level, int) and (allow_llm or had_wbs_signal):
            wbs_tag = _resolve_wbs_tag(wbs_level)
            if wbs_tag:
                tags["WBS level"] = wbs_tag
        elif not existing_wbs_tag:
            tags.pop("WBS level", None)

        task["tags"] = tags

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


def theme_pass(local_state: List[Dict[str, Any]], config_dict: Dict[str, List[Any]]) -> List[Dict[str, Any]]:
    """
    L1 deterministic pass:
    - infer and normalize theme assignment
    - keep only theme tag visible at this stage
    """
    enriched = enrich_state_with_llm(local_state, config_dict, allow_llm=False)
    for task in enriched:
        tags = task.get("tags") or {}
        new_tags: Dict[str, Any] = {}
        if "Task Theme with colour" in tags:
            new_tags["Task Theme with colour"] = tags["Task Theme with colour"]
        task["tags"] = new_tags
    return enriched


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
            else:
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
    - overwrite Priority for scoped tasks by TIMELINER rank
    - quartile mapping (top rank gets highest priority option)
    """
    scoped_ids = scoped_ids or set()
    rank_by_task_id = rank_by_task_id or {}
    priority_options = _extract_priority_options_in_order(config_dict)
    if not priority_options:
        return local_state

    scoped_tasks: List[Dict[str, Any]] = []
    for task in local_state:
        task_id = str(task.get("notion_block_id") or task.get("id") or "")
        if task_id and task_id in scoped_ids:
            scoped_tasks.append(task)

    scoped_tasks.sort(
        key=lambda t: (
            rank_by_task_id.get(str(t.get("notion_block_id") or t.get("id") or ""), 10**9),
            int(t.get("depth", 0)) if str(t.get("depth", 0)).isdigit() else 0,
            str(t.get("notion_block_id") or t.get("id") or ""),
        )
    )

    total = len(scoped_tasks)
    if total == 0:
        return local_state

    for idx, task in enumerate(scoped_tasks):
        band = min(3, (idx * 4) // total)
        mapped_idx = min(band, len(priority_options) - 1)
        priority_val = priority_options[mapped_idx]
        tags = task.get("tags") or {}
        tags["Priority"] = priority_val
        task["tags"] = tags

    return local_state
