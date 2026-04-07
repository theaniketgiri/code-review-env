"""
Inference Script — Code Review Environment
============================================
MANDATORY
- Before submitting, ensure the following variables are defined in your environment configuration:
    API_BASE_URL   The API endpoint for the LLM.
    MODEL_NAME     The model identifier to use for inference.
    HF_TOKEN       Your Hugging Face / API key.
    LOCAL_IMAGE_NAME The name of the local image to use for the environment if you are using from_docker_image()

- Defaults are set only for API_BASE_URL and MODEL_NAME:
    API_BASE_URL = os.getenv("API_BASE_URL", "https://router.huggingface.co/v1")
    MODEL_NAME   = os.getenv("MODEL_NAME", "Qwen/Qwen2.5-72B-Instruct")

- The inference script must be named `inference.py` and placed in the root directory of the project
- Participants must use OpenAI Client for all LLM calls using above variables

STDOUT FORMAT
- The script must emit exactly three line types to stdout, in this order:

    [START] task=<task_name> env=<benchmark> model=<model_name>
    [STEP]  step=<n> action=<action_str> reward=<0.00> done=<true|false> error=<msg|null>
    [END]   success=<true|false> steps=<n> score=<score> rewards=<r1,r2,...,rn>

  Rules:
    - One [START] line at episode begin.
    - One [STEP] line per step, immediately after env.step() returns.
    - One [END] line after env.close(), always emitted (even on exception).
    - reward and rewards are formatted to 2 decimal places.
    - done and success are lowercase booleans: true or false.
    - error is the raw last_action_error string, or null if none.
    - All fields on a single line with no newlines within a line.
    - Each task should return score in [0, 1]
"""

import asyncio
import json
import os
import re
import sys
import textwrap
import time
from collections.abc import Callable
from typing import Any, List, Optional

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

try:
    from .client import CodeReviewEnv
    from .models import ReviewAction
except ImportError:
    from client import CodeReviewEnv
    from models import ReviewAction

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
IMAGE_NAME = os.getenv("IMAGE_NAME")  # If you are using docker image
API_KEY = os.getenv("HF_TOKEN") or os.getenv("API_KEY") or os.getenv("OPENAI_API_KEY")

API_BASE_URL = os.getenv("API_BASE_URL") or "https://router.huggingface.co/v1"
MODEL_NAME = os.getenv("MODEL_NAME") or "Qwen/Qwen2.5-72B-Instruct"
ENV_URL = os.getenv("ENV_URL", "http://localhost:8000")
BENCHMARK = "code_review_env"
TASK_IDS = ["task_easy", "task_medium", "task_hard"]
MAX_STEPS = 3
SUCCESS_SCORE_THRESHOLD = 0.95


# ---------------------------------------------------------------------------
# Detection rules for rule-based fallback
# ---------------------------------------------------------------------------
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

SYSTEM_PROMPT = textwrap.dedent(
    """
    You are a senior Python code reviewer.
    Return ONLY valid JSON object with keys:
    issues_found (array of strings from the taxonomy), review_comment (string), severity (low|medium|high|critical).
    Use taxonomy tags only and avoid extra text.
    """
).strip()


# ---------------------------------------------------------------------------
# Structured stdout logging  (MANDATORY for validator)
# ---------------------------------------------------------------------------
def log_start(task: str, env: str, model: str) -> None:
    print(f"[START] task={task} env={env} model={model}", flush=True)


def log_step(step: int, action: str, reward: float, done: bool, error: Optional[str]) -> None:
    error_val = error if error else "null"
    done_val = str(done).lower()
    print(
        f"[STEP] step={step} action={action} reward={reward:.2f} done={done_val} error={error_val}",
        flush=True,
    )


def log_end(success: bool, steps: int, score: float, rewards: List[float]) -> None:
    rewards_str = ",".join(f"{r:.2f}" for r in rewards)
    print(
        f"[END] success={str(success).lower()} steps={steps} score={score:.3f} rewards={rewards_str}",
        flush=True,
    )


# ---------------------------------------------------------------------------
# Rule-based issue detection
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------
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
    client: Any,
    model: str,
    task_id: str,
    file_name: str,
    task_description: str,
    code_snippet: str,
    max_retries: int = 3,
) -> dict[str, Any]:
    user_prompt = (
        f"Task ID: {task_id}\n"
        f"File: {file_name}\n"
        f"Instruction: {task_description}\n\n"
        f"Code:\n{code_snippet}\n\n"
        "Return strictly JSON with: issues_found, review_comment, severity."
    )

    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0,
                max_tokens=512,
                stream=False,
            )
            break
        except Exception as e:
            last_error = e
            wait_time = 2 ** attempt
            print(f"[DEBUG] LLM retry task_id={task_id} attempt={attempt + 1} wait={wait_time}s error={e}", flush=True)
            time.sleep(wait_time)
    else:
        raise last_error  # type: ignore[misc]

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


def get_action(
    openai_client: Optional[Any],
    model: str,
    task_id: str,
    file_name: str,
    task_description: str,
    code_snippet: str,
) -> dict[str, Any]:
    """Get review action using LLM if available, otherwise rule-based fallback."""
    if openai_client:
        try:
            return build_llm_action(
                client=openai_client,
                model=model,
                task_id=task_id,
                file_name=file_name,
                task_description=task_description,
                code_snippet=code_snippet,
            )
        except Exception as exc:
            print(f"[DEBUG] LLM failed, falling back to rules: {exc}", flush=True)
    return build_rule_action(code_snippet)


# ---------------------------------------------------------------------------
# Main inference loop  (async, follows sample script pattern exactly)
# ---------------------------------------------------------------------------
async def main() -> None:
    openai_client = OpenAI(base_url=API_BASE_URL, api_key=API_KEY) if API_KEY and OpenAI else None

    # Connect to environment — prefer docker image, fallback to URL
    if IMAGE_NAME:
        env = await CodeReviewEnv.from_docker_image(IMAGE_NAME)
    else:
        env = CodeReviewEnv(base_url=ENV_URL)
        await env.connect()

    try:
        for task_id in TASK_IDS:
            rewards: List[float] = []
            steps_taken = 0
            score = 0.0
            success = False

            log_start(task=task_id, env=BENCHMARK, model=MODEL_NAME)

            try:
                result = await env.reset(task_id=task_id)
                observation = result.observation

                code_snippet = observation.code_snippet
                file_name = observation.file_name
                task_description = observation.task_description

                for step in range(1, MAX_STEPS + 1):
                    if result.done:
                        break

                    action_payload = get_action(
                        openai_client=openai_client,
                        model=MODEL_NAME,
                        task_id=task_id,
                        file_name=file_name,
                        task_description=task_description,
                        code_snippet=code_snippet,
                    )

                    action_str = json.dumps(action_payload, separators=(",", ":"))
                    result = await env.step(ReviewAction.model_validate(action_payload))

                    reward = float(result.reward or 0.0)
                    done = result.done
                    error = None

                    rewards.append(reward)
                    steps_taken = step

                    log_step(step=step, action=action_str, reward=reward, done=done, error=error)

                    if done:
                        break

                # Score is the last reward (single-step scoring per task)
                score = rewards[-1] if rewards else 0.0
                score = min(max(score, 0.0), 1.0)
                success = score >= SUCCESS_SCORE_THRESHOLD

            except Exception as exc:
                print(f"[DEBUG] Task {task_id} error: {exc}", flush=True)
            finally:
                log_end(success=success, steps=steps_taken, score=score, rewards=rewards)

    finally:
        try:
            await env.close()
        except Exception as e:
            print(f"[DEBUG] env.close() error: {e}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
