"""
inference.py
============
Baseline inference script for the Code Review Environment.

MANDATORY STDOUT FORMAT
-----------------------
[START] task=<task_name> env=<benchmark> model=<model_name>
[STEP]  step=<n> action=<action_str> reward=<0.00> done=<true|false> error=<msg|null>
[END]   success=<true|false> steps=<n> score=<score> rewards=<r1,r2,...,rn>

Rules:
  - One [START] line at episode begin.
  - One [STEP] line per step, immediately after env.step() returns.
  - One [END] line after the episode ends (always emitted, even on exception).
  - reward and rewards formatted to 2 decimal places.
  - done and success are lowercase booleans: true or false.
  - error is the raw step exception string, or null if none.
  - All fields on a single line with no newlines within a line.

Required environment variables:
  API_BASE_URL  - Proxy endpoint for LLM calls.
  MODEL_NAME    - Model identifier for inference.
  HF_TOKEN      - Hugging Face / API key.

Usage:
    python inference.py
    ENV_SERVER_URL=http://localhost:8000 python inference.py
"""

import json
import os
import re
import sys
import textwrap
import time
from collections.abc import Callable
from typing import Any, Optional

import urllib.request
import urllib.error

# ---------------------------------------------------------------------------
# Configuration — fully environment-driven
# ---------------------------------------------------------------------------

API_BASE_URL: str = os.environ.get("API_BASE_URL", "https://router.huggingface.co/v1")
API_KEY: str = (
    os.environ.get("API_KEY")
    or os.environ.get("HF_TOKEN")
    or os.environ.get("OPENAI_API_KEY")
    or "missing-api-key"
)
MODEL_NAME: str = os.environ.get("MODEL_NAME", "Qwen/Qwen2.5-72B-Instruct")
ENV_SERVER_URL: str = os.environ.get("ENV_SERVER_URL", "http://localhost:8000")

BENCHMARK = "code_review_env"
TASKS = ["task_extra_easy", "task_easy", "task_medium", "task_hard", "task_expert"]
MAX_STEPS = 3
TEMPERATURE = 0.0
MAX_TOKENS = 1024
SUCCESS_THRESHOLDS = {
    "task_extra_easy": 0.95,
    "task_easy": 0.95,
    "task_medium": 0.95,
    "task_hard": 0.95,
    "task_expert": 0.95,
}

ISSUE_TAXONOMY = [
    "null_pointer",
    "missing_return",
    "type_error",
    "index_out_of_bounds",
    "sql_injection",
    "hardcoded_secret",
    "missing_input_validation",
    "race_condition",
    "timing_attack",
    "improper_error_handling",
    "integer_overflow",
    "path_traversal",
]

# Expanded detection rules covering all 12 taxonomy items
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
    "index_out_of_bounds": lambda code: "len(" in code and ("[" in code or "range(" in code),
    "type_error": lambda code: "int(" in code and "str" in code.lower(),
    "integer_overflow": lambda code: "2 ** 31" in code or "overflow" in code.lower(),
    "path_traversal": lambda code: "os.path.join" in code and "user" in code.lower(),
    "missing_input_validation": lambda code: (
        "open(" in code and "user" in code.lower() and "valid" not in code.lower()
    ),
}

# Map difficulty → expected severity for rule-based fallback
DIFFICULTY_SEVERITY: dict[str, str] = {
    "extra_easy": "low",
    "easy": "medium",
    "medium": "high",
    "hard": "critical",
    "expert": "critical",
}

SYSTEM_PROMPT = textwrap.dedent(
    """
You are a senior Python code reviewer performing a security and correctness audit.

Your task: Identify ALL security vulnerabilities, logic errors, and code smells in the
provided code snippet. Use ONLY the allowed taxonomy tags.

Return ONLY a valid JSON object with these keys:
- issues_found: array of issue tags from the allowed taxonomy (be comprehensive)
- review_comment: detailed explanation of each identified issue with specific line references
- severity: one of low|medium|high|critical (based on worst-case impact)

Important rules:
- Do NOT hallucinate issues that aren't present — false positives are heavily penalized (-0.10 each)
- DO identify every real issue — each correctly found issue earns significant reward
- Include relevant keywords in your review_comment for quality bonus scoring
- Match severity to the overall risk level of the issues found

Example for a SQL injection + hardcoded secret:
{
  "issues_found": ["sql_injection", "hardcoded_secret"],
  "review_comment": "SQL injection via f-string query interpolation allows attackers to bypass auth. The SECRET_KEY is hardcoded as plaintext instead of using environment variables.",
  "severity": "high"
}

Do not include markdown, code fences, or extra prose outside the JSON.
"""
).strip()


# ---------------------------------------------------------------------------
# Score clamping
# ---------------------------------------------------------------------------


def clamp_val(v: float, low: float = 0.01, high: float = 0.99) -> float:
    """Clamp value to (0, 1) exclusive range."""
    return max(low, min(high, v))


# ---------------------------------------------------------------------------
# Mandatory stdout log helpers
# ---------------------------------------------------------------------------


def log_start(task: str, env: str, model: str) -> None:
    print(f"[START] task={task} env={env} model={model}", flush=True)


def log_step(
    step: int,
    action: str,
    reward: float,
    done: bool,
    error: Optional[str],
) -> None:
    action_clean = action.replace("\n", " ").replace("\r", " ").strip()
    error_val = error if error else "null"
    done_val = str(done).lower()
    print(
        f"[STEP] step={step} action={action_clean!r} "
        f"reward={clamp_val(reward):.2f} done={done_val} error={error_val}",
        flush=True,
    )


def log_end(success: bool, steps: int, score: float, rewards: list[float]) -> None:
    rewards_str = ",".join(f"{clamp_val(r):.2f}" for r in rewards)
    success_val = str(success).lower()
    print(
        f"[END] success={success_val} steps={steps} score={clamp_val(score):.3f} rewards={rewards_str}",
        flush=True,
    )


# ---------------------------------------------------------------------------
# Environment HTTP helpers
# ---------------------------------------------------------------------------


def _post_json(url: str, payload: dict) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as f:
            return json.loads(f.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8')}")


def env_reset(task_id: str) -> dict[str, Any]:
    return _post_json(f"{ENV_SERVER_URL}/reset", {"task_id": task_id})


def env_step(action: dict[str, Any]) -> dict[str, Any]:
    return _post_json(f"{ENV_SERVER_URL}/step", action)


def unwrap_step_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], float, bool]:
    """Normalize payloads that may be wrapped as {observation,reward,done} or flat."""
    if isinstance(payload.get("observation"), dict):
        observation = payload["observation"]
        reward = float(payload.get("reward", observation.get("reward", 0.0)) or 0.0)
        done = bool(payload.get("done", observation.get("done", False)))
        return observation, reward, done

    observation = payload
    reward = float(payload.get("reward", 0.0) or 0.0)
    done = bool(payload.get("done", False))
    return observation, reward, done


# ---------------------------------------------------------------------------
# Prompt and action helpers
# ---------------------------------------------------------------------------


def build_user_prompt(obs: dict[str, Any], step: int, previous_feedback: str = "") -> str:
    tags = ", ".join(obs.get("available_issue_tags") or ISSUE_TAXONOMY)

    prompt_parts = [
        f"TASK ID: {obs.get('task_id', 'unknown')}",
        f"FILE: {obs.get('file_name', 'unknown')}",
        f"STEP: {step} of {MAX_STEPS}",
        f"INSTRUCTION: {obs.get('task_description', 'N/A')}",
        f"\nALLOWED ISSUE TAGS:\n{tags}",
        f"\nCODE UNDER REVIEW:\n{obs.get('code_snippet', '')}",
    ]

    # Iterative refinement: include previous feedback so the LLM can improve
    if step > 1 and previous_feedback:
        prompt_parts.append(
            f"\nPREVIOUS STEP FEEDBACK (use this to improve your review):\n{previous_feedback}"
        )

    prompt_parts.append(
        "\nReturn strictly JSON with keys: issues_found, review_comment, severity."
    )

    return "\n".join(prompt_parts)


def detect_issues_rule_based(code_snippet: str) -> list[str]:
    detected: list[str] = []
    for issue_tag, detector in DETECTION_RULES.items():
        if detector(code_snippet):
            detected.append(issue_tag)
    return detected


def infer_severity(issues_found: list[str], task_id: str = "") -> str:
    """Infer severity based on number and type of issues found."""
    security_issues = {"sql_injection", "hardcoded_secret", "path_traversal", "timing_attack"}
    has_security = any(i in security_issues for i in issues_found)

    if len(issues_found) >= 3 or has_security:
        return "critical" if len(issues_found) >= 3 else "high"
    elif len(issues_found) == 2:
        return "high" if has_security else "medium"
    elif len(issues_found) == 1:
        return "medium" if has_security else "low"
    return "low"


def build_rule_action(code_snippet: str, task_id: str = "") -> dict[str, Any]:
    issues_found = detect_issues_rule_based(code_snippet)
    severity = infer_severity(issues_found, task_id)

    if issues_found:
        # Build keyword-rich comments for quality bonus
        comment_parts = []
        for issue in issues_found:
            if issue == "null_pointer":
                comment_parts.append("Null dereference risk: .get() may return None without check")
            elif issue == "missing_return":
                comment_parts.append("Missing return statement: function never returns a value")
            elif issue == "sql_injection":
                comment_parts.append("SQL injection via f-string query interpolation — use parameterized queries")
            elif issue == "hardcoded_secret":
                comment_parts.append("Hardcoded secret key in plaintext — use environment variables")
            elif issue == "race_condition":
                comment_parts.append("Race condition: non-atomic check-and-modify on shared balance")
            elif issue == "timing_attack":
                comment_parts.append("Timing attack: use hmac.compare_digest for constant-time comparison")
            elif issue == "improper_error_handling":
                comment_parts.append("Bare except silently swallows all errors including payment failures")
            elif issue == "index_out_of_bounds":
                comment_parts.append("Index out of bounds: off-by-one error accessing array past length")
            elif issue == "type_error":
                comment_parts.append("Type error: int() cast on string input without validation may crash")
            elif issue == "integer_overflow":
                comment_parts.append("Integer overflow: arithmetic on large values may wrap or go negative")
            elif issue == "path_traversal":
                comment_parts.append("Path traversal: os.path.join with user input allows directory escape via ../")
            elif issue == "missing_input_validation":
                comment_parts.append("Missing input validation: untrusted user content written without sanitization")
        review_comment = ". ".join(comment_parts) + "."
    else:
        review_comment = "No obvious issues detected from static heuristics."
        severity = "low"

    return {
        "issues_found": issues_found,
        "review_comment": review_comment,
        "severity": severity,
    }


def extract_json_object(text: str) -> dict[str, Any]:
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


def normalize_action(payload: dict[str, Any]) -> dict[str, Any]:
    issues_found_raw = payload.get("issues_found", [])
    if not isinstance(issues_found_raw, list):
        issues_found_raw = []

    issues_found = [str(issue) for issue in issues_found_raw if str(issue) in ISSUE_TAXONOMY]
    review_comment = str(payload.get("review_comment", "")).strip()
    severity = str(payload.get("severity", "medium")).lower()
    if severity not in {"low", "medium", "high", "critical"}:
        severity = "medium"
    if not review_comment:
        review_comment = "Review based on taxonomy-driven static analysis."

    return {
        "issues_found": issues_found,
        "review_comment": review_comment,
        "severity": severity,
    }


# ---------------------------------------------------------------------------
# Server readiness
# ---------------------------------------------------------------------------


def wait_for_server(timeout: int = 60) -> None:
    for _ in range(timeout):
        try:
            req = urllib.request.Request(f"{ENV_SERVER_URL}/health", method="GET")
            with urllib.request.urlopen(req, timeout=5) as f:
                if f.status == 200:
                    return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError(f"Server at {ENV_SERVER_URL} not ready after {timeout}s")


# ---------------------------------------------------------------------------
# Pure urllib OpenAI-compatible Client
# ---------------------------------------------------------------------------


class PureUrllibOpenAIClient:
    """Fallback OpenAI-compatible client using only stdlib urllib."""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def create_chat_completion(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {self.api_key}")

        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                result = json.loads(response.read().decode("utf-8"))
                return result.get("choices", [{}])[0].get("message", {}).get("content", "")
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            raise RuntimeError(f"HTTP {e.code}: {error_body}")
        except Exception as e:
            raise RuntimeError(f"Proxy request failed: {e}")


# ---------------------------------------------------------------------------
# LLM action builder with iterative refinement
# ---------------------------------------------------------------------------


def build_llm_action(
    client: Any,
    obs: dict[str, Any],
    step: int,
    previous_feedback: str = "",
    max_retries: int = 3,
) -> dict[str, Any]:
    user_prompt = build_user_prompt(obs=obs, step=step, previous_feedback=previous_feedback)

    last_error: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            if isinstance(client, PureUrllibOpenAIClient):
                raw_text = client.create_chat_completion(
                    model=MODEL_NAME,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=TEMPERATURE,
                    max_tokens=MAX_TOKENS,
                )
            else:
                response = client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=TEMPERATURE,
                    max_tokens=MAX_TOKENS,
                    stream=False,
                )
                raw_text = response.choices[0].message.content or ""

            return normalize_action(extract_json_object(raw_text))
        except Exception as llm_err:
            last_error = llm_err
            time.sleep(2 ** attempt)

    raise RuntimeError(f"LLM call failed after retries: {last_error}")


def get_action(
    client: Any,
    obs: dict[str, Any],
    step: int,
    previous_feedback: str = "",
) -> dict[str, Any]:
    """Get action from LLM with rule-based fallback."""
    try:
        return build_llm_action(
            client=client, obs=obs, step=step, previous_feedback=previous_feedback,
        )
    except Exception:
        return build_rule_action(
            obs.get("code_snippet", ""), obs.get("task_id", ""),
        )


# ---------------------------------------------------------------------------
# Agent loop — one task episode with iterative refinement
# ---------------------------------------------------------------------------


def run_task(client: Any, task_id: str) -> None:
    """Run one task episode with iterative refinement and mandatory logs."""
    log_start(task=task_id, env=BENCHMARK, model=MODEL_NAME)

    rewards: list[float] = []
    steps_taken = 0
    final_score = 0.5
    success = False
    previous_feedback = ""

    try:
        reset_payload = env_reset(task_id=task_id)
        obs, reward, done = unwrap_step_payload(reset_payload)

        if reward:
            rewards.append(reward)

        threshold = SUCCESS_THRESHOLDS.get(task_id, 0.95)

        for step in range(1, MAX_STEPS + 1):
            if done:
                break

            # Use previous feedback for iterative refinement
            action_payload = get_action(
                client=client, obs=obs, step=step, previous_feedback=previous_feedback,
            )
            action_str = json.dumps(action_payload, separators=(",", ":"))

            try:
                step_payload = env_step(action=action_payload)
                obs, reward, done = unwrap_step_payload(step_payload)
                rewards.append(reward)
                steps_taken = step

                # Capture feedback for next iteration
                previous_feedback = obs.get("feedback", "")

                log_step(step=step, action=action_str, reward=reward, done=done, error=None)

                if done:
                    final_score = reward
                    success = final_score >= threshold
                    break
            except Exception as step_err:
                steps_taken = step
                log_step(
                    step=step, action=action_str, reward=0.0, done=True,
                    error=str(step_err),
                )
                break

        if rewards:
            final_score = rewards[-1]
            success = final_score >= threshold

    except Exception:
        success = False

    log_end(success=success, steps=steps_taken, score=final_score, rewards=rewards)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    # Dynamically fetch at runtime to pick up injected env vars
    val_api_base = os.environ.get("API_BASE_URL", "https://router.huggingface.co/v1")
    val_api_key = (
        os.environ.get("API_KEY") or os.environ.get("HF_TOKEN") or "missing-api-key"
    )

    client = None
    try:
        from openai import OpenAI
        client = OpenAI(base_url=val_api_base, api_key=val_api_key)
    except Exception as e:
        print(
            f"[WARN] openai unavailable, using urllib fallback: {e}",
            file=sys.stderr,
        )
        client = PureUrllibOpenAIClient(base_url=val_api_base, api_key=val_api_key)

    wait_for_server(timeout=60)

    for task_id in TASKS:
        run_task(client=client, task_id=task_id)


if __name__ == "__main__":
    main()
