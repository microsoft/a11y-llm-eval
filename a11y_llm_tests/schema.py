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


class PromptVariant(BaseModel):
    """Defines a prompt variant for a run.

    A run can include the implicit "control" variant plus zero or more variants that
    append custom instructions at the system prompt level.
    """

    id: str  # e.g. "control" or a stable instruction set id
    name: Optional[str] = None
    description: Optional[str] = None
    custom_instructions_path: Optional[str] = None
    n_samples_requested: Optional[int] = None


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
    screenshot_path: Optional[str]
    test_function: TestFunctionResult
    axe: Optional[AxeResult]
    result: str # PASS|FAIL|ERROR
    generation: GenerationMeta
    # Index of the sample for (test_name, model_name). 0-based. None for legacy single-sample runs.
    sample_index: Optional[int] = None
    # Prompt variant identifier. None or "control" for baseline runs.
    prompt_variant_id: Optional[str] = None


class RunSummary(BaseModel):
    run_id: str
    created_at: datetime
    results: List[ResultRecord]
    models: List[str]
    tests: List[str]


class AggregateStats(BaseModel):
    per_model: Dict[str, Dict[str, Any]]


class AggregateRecord(BaseModel):
    """Aggregate statistics for a (test_name, model_name) pair across multiple samples."""
    test_name: str
    base_test_name: Optional[str] = None
    prompt_case_id: Optional[str] = None
    prompt_dimensions: List[PromptDimensionAssignment] = []
    model_name: str
    # Prompt variant identifier. None or "control" for baseline runs.
    prompt_variant_id: Optional[str] = None
    n_samples: int
    n_applicable: Optional[int] = None
    n_not_applicable: int = 0
    n_pass: int
    pass_at_k: Dict[str, float]  # JSON-friendly string keys
    k_values: List[int]
    computed_at: datetime

