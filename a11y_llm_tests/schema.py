from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime


class AssertionResult(BaseModel):
    name: str
    status: str  # pass|fail
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


class AxeNode(BaseModel):
    html: Optional[str]
    target: List[str] = []


class AxeViolation(BaseModel):
    id: str
    impact: Optional[str]
    description: str
    helpUrl: Optional[str]
    nodes: List[AxeNode] = []
    tags: List[str] = []


class AxeResult(BaseModel):
    violation_count: int
    violations: List[AxeViolation] = []


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


class ResultRecord(BaseModel):
    test_name: str
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
    model_name: str
    n_samples: int
    n_pass: int
    pass_at_k: Dict[str, float]  # JSON-friendly string keys
    k_values: List[int]
    computed_at: datetime

