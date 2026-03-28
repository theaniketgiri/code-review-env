import json
import os
import re
import sys
from collections.abc import Callable
from typing import Any

from openai import OpenAI

try:
    from .client import CodeReviewEnv
    from .models import ReviewAction
except ImportError:
    from client import CodeReviewEnv
    from models import ReviewAction


TASK_IDS = ["task_easy", "task_medium", "task_hard"]
DEFAULT_ENV_URL = "http://localhost:8000"
DEFAULT_MODEL = "gpt-4o-mini"


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


SYSTEM_PROMPT = (
    "You are a senior Python code reviewer. "
    "Return ONLY valid JSON object with keys: "
    "issues_found (array of strings), review_comment (string), severity (low|medium|high|critical). "
    "Use taxonomy tags only and avoid extra text."
)


def detect_issues_rule_based(code_snippet: str) -> list[str]:
    detected: list[str] = []
    for issue_tag, detector in DETECTION_RULES.items():
        if detector(code_snippet):
            detected.append(issue_tag)
    return detected


def build_rule_action(code_snippet: str) -> dict[str, Any]:
    issues_found = detect_issues_rule_based(code_snippet)
    if issues_found:
        review_comment = "Detected issues: " + ", ".join(issues_found)
        severity = "high" if len(issues_found) >= 2 else "medium"
    else:
        review_comment = "No obvious issues detected from static heuristics."
        severity = "low"

    return {
        "issues_found": issues_found,
        "review_comment": review_comment,
        "severity": severity,
    }


def _extract_json_object(text: str) -> dict[str, Any]:
    if not text:
        raise ValueError("Empty model response")

    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped, flags=re.IGNORECASE).strip()
        stripped = re.sub(r"```$", "", stripped).strip()

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", stripped)
        if not match:
            raise
        return json.loads(match.group(0))


def build_llm_action(
    client: OpenAI,
    model: str,
    task_id: str,
    file_name: str,
    task_description: str,
    code_snippet: str,
) -> dict[str, Any]:
    user_prompt = (
        f"Task ID: {task_id}\n"
        f"File: {file_name}\n"
        f"Instruction: {task_description}\n\n"
        f"Code:\n{code_snippet}\n\n"
        "Return strictly JSON with: issues_found, review_comment, severity."
    )

    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
    )

    raw_text = completion.choices[0].message.content or ""
    parsed = _extract_json_object(raw_text)

    issues_found = parsed.get("issues_found", [])
    if not isinstance(issues_found, list):
        issues_found = []
    issues_found = [str(issue) for issue in issues_found]

    review_comment = str(parsed.get("review_comment", ""))
    severity = str(parsed.get("severity", "medium")).lower()
    if severity not in {"low", "medium", "high", "critical"}:
        severity = "medium"

    return {
        "issues_found": issues_found,
        "review_comment": review_comment,
        "severity": severity,
    }


def run_baseline() -> dict[str, dict[str, Any]]:
    env_url = os.getenv("ENV_URL", DEFAULT_ENV_URL).rstrip("/")
    openai_api_key = os.getenv("OPENAI_API_KEY")
    openai_model = os.getenv("OPENAI_MODEL", DEFAULT_MODEL)

    openai_client = OpenAI(api_key=openai_api_key) if openai_api_key else None

    results: dict[str, dict[str, Any]] = {}

    with CodeReviewEnv(base_url=env_url).sync() as env:
        for task_id in TASK_IDS:
            reset_result = env.reset(task_id=task_id)
            observation = reset_result.observation

            code_snippet = observation.code_snippet
            file_name = observation.file_name
            task_description = observation.task_description

            action_payload: dict[str, Any]
            if openai_client:
                try:
                    action_payload = build_llm_action(
                        client=openai_client,
                        model=openai_model,
                        task_id=task_id,
                        file_name=file_name,
                        task_description=task_description,
                        code_snippet=code_snippet,
                    )
                except Exception:
                    action_payload = build_rule_action(code_snippet)
            else:
                action_payload = build_rule_action(code_snippet)

            step_result = env.step(ReviewAction.model_validate(action_payload))
            score = float(step_result.reward or 0.0)
            results[task_id] = {
                "score": score,
                "issues_found": action_payload.get("issues_found", []),
            }

    return results


def main() -> int:
    try:
        output = run_baseline()
        print(json.dumps(output, indent=2))
        return 0
    except Exception as exc:
        print(f"inference failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
