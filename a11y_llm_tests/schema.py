from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime


class AssertionResult(BaseModel):
    name: str
    status: str  # pass|fail|na
    message: Optional[str] = None
    type: str = "R"  # R = Requirement (default), BP = Best Practice

    def model_post_init(self, __context):  # type: ignore[override]
        # Normalize and validate type for backward compatibility
        t = (self.type or "R").upper()
        if t not in {"R", "BP"}:
            t = "R"
        object.__setattr__(self, "type", t)


class TestFunctionResult(BaseModel):
    status: str  # pass|fail|error|timeout
    assertions: List[AssertionResult] = []
    error: Optional[str] = None
    duration_ms: Optional[int] = None
    total_assertion_failures: int = 0
    total_assertion_bp_failures: int = 0
    total_assertion_na: int = 0
    total_assertion_bp_na: int = 0


class AxeNode(BaseModel):
    html: Optional[str]
    target: List[str] = []


class AxeFailure(BaseModel):
    id: str
    impact: Optional[str]
    description: str
    helpUrl: Optional[str]
    nodes: List[AxeNode] = []
    tags: List[str] = []


class AxeResult(BaseModel):
    failure_count: int  # WCAG failures only (affects pass/fail)
    failures: List[AxeFailure] = []  # WCAG failures only
    best_practice_count: int = 0  # Best practice failures (informational)
    best_practice_failures: List[AxeFailure] = []  # Best practice failures


class GenerationMeta(BaseModel):
    latency_s: float
    prompt_hash: str
    cached: bool
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    total_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    # Added for sampling diversity / metadata
    seed: Optional[int] = None
    temperature: Optional[float] = None
    system_prompt: Optional[str] = None
    custom_instructions: Optional[str] = None
    effective_system_prompt: Optional[str] = None
    generation_mode: Optional[str] = None
    agent_sandbox: Optional[str] = None
    agent_limit_error: Optional[str] = None
    agent_limits: Optional[Dict[str, Any]] = None


class PromptVariant(BaseModel):
    """Defines a prompt variant for a run.

    A run can include the implicit "control" variant plus zero or more variants that
    append custom instructions at the system prompt level (instruction sets) or mount
    a skill package into a sandboxed multi-turn agent (skills).
    """

    id: str  # e.g. "control", an instruction set id, or a skill id
    name: Optional[str] = None
    description: Optional[str] = None
    custom_instructions_path: Optional[str] = None
    n_samples_requested: Optional[int] = None
    generation_mode: Optional[str] = None
    agent_sandbox: Optional[str] = None
    agent_limits: Optional[Dict[str, Any]] = None
    # Variant kind. One of "control", "instruction_set", "skill". Defaults to the
    # legacy interpretation (instruction_set for non-control variants with
    # custom_instructions_path set) when None for backward compatibility.
    kind: Optional[str] = None
    # For kind == "skill": path to the skill directory on disk (host side).
    skill_path: Optional[str] = None
    # For kind == "skill": the turns definition from the skills YAML.
    # Each entry is a dict with keys: id (str), name (Optional[str]), prompt (str).
    turns: Optional[List[Dict[str, Any]]] = None


class PromptDimensionAssignment(BaseModel):
    id: str
    label: str
    value_id: str
    value_label: str


class PromptCase(BaseModel):
    id: str
    test_name: str
    base_test_name: str
    prompt_dimensions: List[PromptDimensionAssignment] = []


class ResultRecord(BaseModel):
    test_name: str
    base_test_name: Optional[str] = None
    prompt_case_id: Optional[str] = None
    prompt_dimensions: List[PromptDimensionAssignment] = []
    model_name: str
    timestamp: datetime
    generation_html_path: str
    generation_conversation_path: Optional[str] = None
    generation_eval_path: Optional[str] = None
    screenshot_path: Optional[str]
    test_function: TestFunctionResult
    axe: Optional[AxeResult]
    result: str # PASS|FAIL|ERROR
    generation: GenerationMeta
    # Index of the sample for (test_name, model_name). 0-based. None for legacy single-sample runs.
    sample_index: Optional[int] = None
    # Prompt variant identifier. None or "control" for baseline runs.
    prompt_variant_id: Optional[str] = None
    # Prompt variant kind discriminator. One of "control", "instruction_set", "skill".
    # Optional/additive for backward compatibility with older results.json files.
    prompt_variant_kind: Optional[str] = None
    # For skill variants: stable per-skill turn id (e.g. "generate", "review").
    turn_id: Optional[str] = None
    # For skill variants: 0-based turn index.
    turn_index: Optional[int] = None
    # For skill variants: total turns defined by the skill.
    turn_count_total: Optional[int] = None


class AggregateRecord(BaseModel):
    """Aggregate statistics for a (test_name, model_name) pair across multiple samples."""
    test_name: str
    base_test_name: Optional[str] = None
    prompt_case_id: Optional[str] = None
    prompt_dimensions: List[PromptDimensionAssignment] = []
    model_name: str
    # Prompt variant identifier. None or "control" for baseline runs.
    prompt_variant_id: Optional[str] = None
    # Prompt variant kind discriminator. One of "control", "instruction_set", "skill".
    prompt_variant_kind: Optional[str] = None
    # For skill variants: stable per-skill turn id (e.g. "generate", "review").
    turn_id: Optional[str] = None
    # For skill variants: 0-based turn index.
    turn_index: Optional[int] = None
    n_samples: int
    n_applicable: Optional[int] = None
    n_not_applicable: int = 0
    n_pass: int
    pass_at_k: Dict[str, float]  # JSON-friendly string keys
    k_values: List[int]
    computed_at: datetime

