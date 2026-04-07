# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""FastAPI app for the Code Review OpenEnv environment."""

from collections.abc import Callable

from pydantic import BaseModel, Field

try:
    from openenv.core.env_server.http_server import create_app
except Exception as e:  # pragma: no cover
    raise ImportError(
        "openenv is required for the web interface. Install dependencies with '\n    uv sync\n'"
    ) from e

try:
    from ..models import ReviewAction, ReviewObservation
    from .code_review_env_environment import CodeReviewEnvironment
    from .graders import grade_review
    from .tasks import TASKS, Task, get_task
except ImportError:
    from models import ReviewAction, ReviewObservation
    from server.code_review_env_environment import CodeReviewEnvironment
    from server.graders import grade_review
    from server.tasks import TASKS, Task, get_task


def _env_factory() -> CodeReviewEnvironment:
    return CodeReviewEnvironment()


app = create_app(
    _env_factory,
    ReviewAction,
    ReviewObservation,
    max_concurrent_envs=1,
)


class GraderRequest(BaseModel):
    task_id: str = Field(..., description="Task identifier to score against.")
    issues_found: list[str] = Field(
        default_factory=list,
        description="Issue tags submitted by the agent.",
    )
    review_comment: str = Field(
        default="",
        description="Free-text review comment submitted by the agent.",
    )


class GraderResponse(BaseModel):
    task_id: str
    score: float


DETECTION_RULES: dict[str, Callable[[str], bool]] = {
    "null_pointer": lambda code: ".get(" in code or "= None" in code,
    "missing_return": lambda code: "# todo: return" in code.lower(),
    "sql_injection": lambda code: (
        "f\"select" in code.lower()
        or "f'select" in code.lower()
        or "username='{" in code
    ),
    "hardcoded_secret": lambda code: (
        "secret_key =" in code.lower() or '= "supersecret' in code.lower()
    ),
    "race_condition": lambda code: "balance -=" in code or "balance +=" in code,
    "timing_attack": lambda code: "if expected ==" in code or "== actual" in code,
    "improper_error_handling": lambda code: "except:\n" in code or "except:\r\n" in code,
}


def detect_issues_rule_based(task: Task) -> list[str]:
    detected: list[str] = []
    for issue_tag, detector in DETECTION_RULES.items():
        if detector(task.code):
            detected.append(issue_tag)
    return detected


def build_rule_comment(issues_found: list[str]) -> str:
    if not issues_found:
        return "No obvious issues detected."
    return "Detected issues: " + ", ".join(issues_found)


@app.get("/tasks")
def list_tasks() -> dict:
    return {
        "tasks": [
            {
                "task_id": task.task_id,
                "difficulty": task.difficulty,
                "description": task.description,
                "file_name": task.file_name,
            }
            for task in TASKS.values()
        ],
        "action_schema": ReviewAction.model_json_schema(),
    }


@app.post("/grader", response_model=GraderResponse)
def grade_endpoint(payload: GraderRequest) -> GraderResponse:
    task = get_task(payload.task_id)
    score = grade_review(payload.issues_found, payload.review_comment, task)
    return GraderResponse(task_id=task.task_id, score=score)


@app.post("/baseline")
def run_baseline() -> dict:
    baseline_scores: dict[str, dict] = {}

    for task_id, task in TASKS.items():
        issues_found = detect_issues_rule_based(task)
        review_comment = build_rule_comment(issues_found)
        score = grade_review(issues_found, review_comment, task)
        baseline_scores[task_id] = {
            "score": score,
            "issues_found": issues_found,
        }

    return {"baseline_scores": baseline_scores}


def main(host: str = "0.0.0.0", port: int = 8000):
    """
    Entry point for direct execution via uv run or python -m.

    This function enables running the server without Docker:
        uv run --project . server
        uv run --project . server --port 8001
        python -m code_review_env.server.app

    Args:
        host: Host address to bind to (default: "0.0.0.0")
        port: Port number to listen on (default: 8000)

    For production deployments, consider using uvicorn directly with
    multiple workers:
        uvicorn code_review_env.server.app:app --workers 4
    """
    import uvicorn

    uvicorn.run(app, host=host, port=port)


if __name__ == '__main__':
    main()
