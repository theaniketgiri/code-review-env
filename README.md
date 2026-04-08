---
title: Code Review Environment
emoji: 🛡️
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 8000
pinned: false
license: bsd-3-clause
short_description: AI agent code review environment benchmark
tags:
  - openenv
  - reinforcement-learning
  - code-review
---

<!-- Banner -->
<div align="center">

# Code Review Environment

### An OpenEnv Benchmark for AI-Driven Pull-Request Review

[![OpenEnv](https://img.shields.io/badge/OpenEnv-compliant-blue?style=for-the-badge&logo=meta)](https://github.com/meta-pytorch/OpenEnv)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://hub.docker.com)
[![License](https://img.shields.io/badge/license-BSD--3-green?style=for-the-badge)](LICENSE)

---

**🚀 Scaler March 2026 Hackathon Submission**

**Author:** [Dolphin-Syndrom](https://github.com/Dolphin-Syndrom) &nbsp;|&nbsp; **Type:** OpenEnv Benchmark &nbsp;|&nbsp; **Focus:** Security-Aware Code Review

</div>

---

## ⚡ TL;DR

A benchmark environment that evaluates whether an LLM agent can review buggy Python code, identify security vulnerabilities and logic errors using a fixed taxonomy, and articulate its findings — just like a senior engineer doing a pull-request review.

- **3 progressive tasks** — easy → medium → hard
- **12-tag issue taxonomy** — from `null_pointer` to `timing_attack`
- **Deterministic multi-dimensional grading** — recall + precision + articulation quality
- **Dense reward shaping** — signal at every step, not just episode end
- **Structured actions & observations** — typed Pydantic models with full schema
- **Dual inference modes** — LLM-backed or rule-based fallback
- **Deployable** via Docker on Hugging Face Spaces
- **Fully OpenEnv compliant** — passes `openenv validate`

---

> *Designed to evaluate whether AI agents can perform structured, taxonomy-driven code review under constrained interaction loops — a high-value, real-world software engineering workflow.*

---

## 📑 Table of Contents

- [Environment Description](#-environment-description)
- [Why This Domain?](#-why-this-domain)
- [Action Space](#-action-space)
- [Observation Space](#-observation-space)
- [Reward Function](#-reward-function)
- [Tasks](#-tasks)
- [Setup & Usage](#-setup--usage)
- [Running the Baseline](#-running-the-baseline)
- [Baseline Scores](#-baseline-scores)
- [Deployment (HF Spaces + Docker)](#-deployment)

---

## 🧠 Environment Description

This OpenEnv environment simulates a real software engineering task: **reviewing buggy Python code and identifying security and logic issues** using a fixed taxonomy of tags.

Each episode presents the agent with a Python code snippet containing **planted vulnerabilities**. The agent must:

1. **Identify** the issues using tags from a 12-item taxonomy
2. **Assess** overall severity (`low` / `medium` / `high` / `critical`)
3. **Articulate** its findings in a human-readable review comment

Performance is measured by a **deterministic, multi-dimensional grader** that scores recall, penalizes false positives, and rewards articulation quality — producing a final score in `[0.0, 1.0]`.

### Episode Flow

```
┌─────────┐     ┌──────────────┐     ┌────────────┐     ┌────────────┐
│  reset() │────▶│  Observation  │────▶│  Agent Act  │────▶│  Grading   │
│ (task_id)│     │ code_snippet  │     │ issues_found│     │ score/done │
└─────────┘     │ file_name     │     │ comment     │     └─────┬──────┘
                │ description   │     │ severity    │           │
                └──────────────┘     └────────────┘     ┌─────▼──────┐
                                                         │  Feedback   │
                                                         │ + next obs  │
                                                         └────────────┘
```

- `reset(task_id)` loads a task and returns the initial observation
- `step(action)` grades the agent's review and returns `(observation, reward, done)`
- Episode ends when score ≥ 0.95 **or** the step limit (3) is reached

### Internal State

The environment tracks:
- Current task ID, file name, and planted issues
- Episode ID and step count
- Maximum allowed steps (3 per episode)

The full state is available through the OpenEnv `state()` API for debugging, but the agent **does not** observe the ground-truth issues during normal play.

---

## 🎯 Why This Domain?

| Criteria | How Code Review Fits |
|----------|---------------------|
| **Real-world utility** | PR review is a daily, high-value engineering workflow |
| **RL-friendly** | Structured action space with dense rewards and a deterministic grader |
| **Progressive difficulty** | Easy → Medium → Hard with increasing issue complexity |
| **Measurable precision** | False positives are explicitly penalized — no reward hacking |
| **Articulation matters** | Bonus for explaining *why* an issue exists, not just tagging it |
| **Security relevance** | Covers OWASP-style vulnerabilities (SQLi, hardcoded secrets, timing attacks) |

---

## 🕹️ Action Space

The agent submits a `ReviewAction` (defined in `models.py`) with three fields:

| Field | Type | Description |
|-------|------|-------------|
| `review_comment` | `str` | Human-readable explanation of identified issues and suggested fixes |
| `issues_found` | `list[str]` | Issue tags selected from the 12-tag `ISSUE_TAXONOMY` |
| `severity` | `"low"` \| `"medium"` \| `"high"` \| `"critical"` | Overall severity assessment |

### Issue Taxonomy (12 Tags)

```
┌──────────────────────┬──────────────────────────┬────────────────────────┐
│   Logic Errors       │   Security Vulns         │   Robustness           │
├──────────────────────┼──────────────────────────┼────────────────────────┤
│  null_pointer        │  sql_injection           │  race_condition        │
│  missing_return      │  hardcoded_secret        │  timing_attack         │
│  type_error          │  path_traversal          │  improper_error_       │
│  index_out_of_bounds │  missing_input_          │    handling            │
│                      │    validation            │  integer_overflow      │
└──────────────────────┴──────────────────────────┴────────────────────────┘
```

### Example Action

```json
{
  "review_comment": "The function uses .get() for birthdate but doesn't guard against None before arithmetic. Also, the function builds a profile dict but never returns it.",
  "issues_found": ["null_pointer", "missing_return"],
  "severity": "high"
}
```

---

## 👁️ Observation Space

The agent receives a `ReviewObservation` (defined in `models.py`) after every `reset()` and `step()`:

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | `str` | Task identifier (`task_easy`, `task_medium`, `task_hard`) |
| `file_name` | `str` | Simulated file under review (e.g., `auth.py`) |
| `task_description` | `str` | Instructions for the agent |
| `code_snippet` | `str` | Python source code containing planted bugs |
| `feedback` | `str` | Grading breakdown after each step |
| `step_number` | `int` | Current step in the episode (0-indexed) |
| `available_issue_tags` | `list[str]` | Full taxonomy for reference |
| `reward` | `float` | Score from the grader (0.0 – 1.0) |
| `done` | `bool` | Whether the episode has ended |
| `metadata` | `dict` | Diagnostics: correctly found, missed, false positives |

---

## 📊 Reward Function

The environment uses a **deterministic, multi-dimensional** reward function implemented in `server/graders.py`. Agents receive dense signal at every step.

### Formula

```
base_score       = |correctly_found ∩ planted| / |planted|
quality_bonus    = +0.05  ×  (# correct issues with keyword match in comment)
precision_penalty = −0.10  ×  (# false-positive issues)

final_score = clamp(base_score + quality_bonus − precision_penalty,  0.0,  1.0)
```

### Components Explained

| Component | Value | Purpose |
|-----------|-------|---------|
| **Recall Reward** | `|correct| / |planted|` | Primary signal — find what's actually broken |
| **Quality Bonus** | `+0.05` per issue | Rewards articulation — mentioning *why* an issue matters |
| **Precision Penalty** | `−0.10` per FP | Discourages hallucinated / over-aggressive flagging |

### Keyword Bonus Examples

| Issue Tag | Triggering Keywords |
|-----------|-------------------|
| `sql_injection` | sql, injection, f-string, sanitize, parameterize |
| `hardcoded_secret` | hardcoded, secret, credential, env var, plaintext |
| `race_condition` | race, atomic, concurrent, lock, thread |
| `timing_attack` | timing, constant time, hmac, compare_digest |
| `improper_error_handling` | except, swallow, silent, bare except |

> **Design rationale:** Random or naive strategies produce low scores (missed issues + penalties). Agents must demonstrate both *detection accuracy* and *communication quality* to score well.

---

## 📝 Tasks

Three tasks with progressive difficulty. Each task presents a different Python file with distinct planted vulnerabilities.

### `task_easy` — User Service (`user_service.py`)

| Property | Value |
|----------|-------|
| **Planted Issues** | `null_pointer`, `missing_return` |
| **Difficulty** | Easy |
| **Description** | Review a function that uses `.get()` without null-guarding and never returns its result |
| **Grader** | Deterministic — recall + quality bonus − FP penalty |

<details>
<summary>📄 Code Snippet</summary>

```python
def get_user_age(user):
    # Returns age in years from user profile dict
    birthdate = user.get("birthdate")
    if user.get("is_active"):
        account_label = f"active:{user.get('id')}"
    else:
        account_label = "inactive"

    age = (datetime.now() - birthdate).days // 365
    profile = {"label": account_label, "age": age}
    # TODO: return something
```

</details>

---

### `task_medium` — Auth Module (`auth.py`)

| Property | Value |
|----------|-------|
| **Planted Issues** | `sql_injection`, `hardcoded_secret` |
| **Difficulty** | Medium |
| **Description** | Review an authentication function with f-string SQL interpolation and a plaintext secret key |
| **Grader** | Deterministic — recall + quality bonus − FP penalty |

<details>
<summary>📄 Code Snippet</summary>

```python
SECRET_KEY = "supersecret123"   # used for JWT signing

def authenticate_user(db_conn, username, password):
    query = f"SELECT * FROM users WHERE username='{username}' AND password='{password}'"
    result = db_conn.execute(query)
    user = result.fetchone()

    if user:
        audit_line = f"auth ok for {username}"
        token = jwt.encode({"user_id": user.id}, SECRET_KEY)
        return token
```

</details>

---

### `task_hard` — Payment Processing (`payments.py`)

| Property | Value |
|----------|-------|
| **Planted Issues** | `race_condition`, `improper_error_handling`, `timing_attack` |
| **Difficulty** | Hard |
| **Description** | Review a payment function for non-atomic balance ops, silently swallowed exceptions, and non-constant-time comparisons |
| **Grader** | Deterministic — recall + quality bonus − FP penalty |

<details>
<summary>📄 Code Snippet</summary>

```python
def process_payment(user_id, amount, card_token):
    user = db.get_user(user_id)
    if user.balance >= amount:
        user.balance -= amount    # checked and modified non-atomically
        db.save_user(user)

        try:
            charge_result = payment_gateway.charge(card_token, amount)
        except:
            pass  # silently swallow all payment errors

        expected = db.get_token_hash(card_token)
        actual = hash(card_token)
        if expected == actual:    # non-constant-time comparison
            return {"status": "success", "charge": charge_result}
```

</details>

---

## 🔧 Setup & Usage

### Prerequisites

- Python ≥ 3.10
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

### Install Dependencies

```bash
# Clone the repository
git clone https://github.com/Dolphin-Syndrom/code-review-env.git
cd code-review-env

# Using uv (recommended)
uv sync

# Or using pip
pip install -e .
```

### Start the Server

```bash
# Using uv
uv run uvicorn server.app:app --host 0.0.0.0 --port 8000

# Or using pip-installed packages
uvicorn server.app:app --host 0.0.0.0 --port 8000
```

### Verify It's Running

```bash
# Health check
curl http://localhost:8000/health

# List all tasks
curl http://localhost:8000/tasks

# Run the built-in baseline
curl -X POST http://localhost:8000/baseline

# Score a custom submission
curl -X POST http://localhost:8000/grader \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "task_easy",
    "issues_found": ["null_pointer", "missing_return"],
    "review_comment": "Null dereference risk on birthdate and missing return statement"
  }'
```

---

## 🤖 Running the Baseline

The baseline script (`inference.py`) supports two modes and follows the **mandatory OpenEnv stdout format**.

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `API_BASE_URL` | No | `https://router.huggingface.co/v1` | LLM API endpoint |
| `MODEL_NAME` | No | `Qwen/Qwen2.5-72B-Instruct` | Model identifier |
| `HF_TOKEN` | For LLM mode | — | Hugging Face / API key |
| `ENV_URL` | No | `http://localhost:8000` | Environment server URL |
| `IMAGE_NAME` | No | — | Docker image name (if using `from_docker_image()`) |

### Run Locally

```bash
# Rule-based fallback (no API key needed)
python inference.py

# LLM-backed mode
API_BASE_URL=https://router.huggingface.co/v1 \
MODEL_NAME=Qwen/Qwen2.5-72B-Instruct \
HF_TOKEN=hf_your_token_here \
python inference.py

# Against a deployed HF Space
ENV_URL=https://your-space.hf.space python inference.py
```

### Structured Stdout Output (Mandatory)

The script emits exactly three line types for the OpenEnv validator:

```
[START] task=task_easy env=code_review_env model=Qwen/Qwen2.5-72B-Instruct
[STEP]  step=1 action={"issues_found":["null_pointer","missing_return"],...} reward=1.00 done=true error=null
[END]   success=true steps=1 score=1.000 rewards=1.00
```

**Rules:**
- One `[START]` at episode begin
- One `[STEP]` per step, immediately after `env.step()` returns
- One `[END]` after episode completes (always emitted, even on exception)
- `reward` and `rewards` formatted to 2 decimal places
- `done` and `success` are lowercase booleans
- Each task score must be in `(0.0, 1.0)` — strictly between, not exactly 0 or 1

---

## 📈 Baseline Scores

Performance of the built-in rule-based baseline (no LLM required):

| Task | Difficulty | Issues Detected | Score |
|------|-----------|----------------|-------|
| `task_easy` | 🟢 Easy | `null_pointer`, `missing_return` | **1.00** |
| `task_medium` | 🟡 Medium | `sql_injection`, `hardcoded_secret` | **1.00** |
| `task_hard` | 🔴 Hard | `race_condition`, `timing_attack`, `improper_error_handling` | **1.00** |

> The rule-based baseline uses pattern-matching heuristics (e.g., detecting `.get(` for null pointers, `f"select` for SQL injection). LLM agents are expected to **match or exceed** these scores while providing richer, more actionable review comments.

---

## 🚀 Deployment

### Docker

```bash
# Build
docker build -t code-review-env:latest .

# Run
docker run -p 8000:8000 code-review-env:latest
```

### Hugging Face Spaces

This repo is structured for Docker-based deployment to HF Spaces.

```bash
# Using the OpenEnv CLI
openenv push --repo-id Dolphin-Syndrom/code-review-env
```

**Recommended Space Settings:**
- **SDK:** Docker
- **Hardware:** CPU Basic (sufficient)
- **Secrets:** Set `API_BASE_URL`, `MODEL_NAME`, `HF_TOKEN` if you want LLM baseline enabled

### Pre-Validation

Run the validation script before submitting:

```bash
./scripts/validate-submission.sh https://Dolphin-Syndrom-code-review-env.hf.space .
```

---

## 🔌 API Reference

All endpoints are OpenEnv-compatible and return structured JSON.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/tasks` | List all tasks with schemas |
| `POST` | `/reset` | Reset episode for a given task |
| `POST` | `/step` | Submit a review action |
| `GET` | `/state` | Get current episode state |
| `POST` | `/grader` | Score an action against a task |
| `POST` | `/baseline` | Run built-in rule-based baseline across all tasks |
| `WS` | `/ws` | WebSocket for real-time interaction |

---

## 📁 Project Structure

```
code-review-env/
├── __init__.py                          # Package exports
├── client.py                            # CodeReviewEnv — WebSocket client (EnvClient subclass)
├── models.py                            # ReviewAction, ReviewObservation, ReviewState, ISSUE_TAXONOMY
├── inference.py                         # Baseline inference (LLM + rule-based fallback)
├── openenv.yaml                         # OpenEnv manifest with grader blocks
├── pyproject.toml                       # Project metadata & dependencies
├── Dockerfile                           # Production container
├── README.md
├── scripts/
│   └── validate-submission.sh           # Pre-submission validator
└── server/
    ├── __init__.py
    ├── app.py                           # FastAPI server + Gradio dashboard
    ├── code_review_env_environment.py   # Environment implementation (reset/step/state)
    ├── graders.py                       # Deterministic grading logic
    ├── tasks.py                         # Task definitions with planted issues
    ├── requirements.txt
    └── Dockerfile
```

---

## 🏁 Submission Checklist

| # | Check | Status |
|---|-------|--------|
| 1 | Docker build succeeds | ✅ |
| 2 | `POST /reset` returns 200 | ✅ |
| 3 | 3 tasks with `grader:` blocks in `openenv.yaml` | ✅ |
| 4 | `inference.py` exits with code 0 | ✅ |
| 5 | `[START]`, `[STEP]`, `[END]` in stdout | ✅ |
| 6 | LLM calls via `API_BASE_URL` proxy | ✅ |
| 7 | All task scores strictly in `(0.0, 1.0)` | ✅ |

### Submission Links (Both Required)

1. **GitHub Repository:** [Dolphin-Syndrom/code-review-env](https://github.com/Dolphin-Syndrom/code-review-env)
2. **Hugging Face Space:** [Dolphin-Syndrom/code-review-env](https://huggingface.co/spaces/Dolphin-Syndrom/code-review-env)

---

## 🔮 Extensibility

Possible next steps for this benchmark:

- **More languages** — Extend beyond Python to JavaScript, Go, Rust
- **Multi-file reviews** — Cross-file dependency analysis
- **Diff-based input** — Review git diffs instead of full files
- **Severity grading** — Score severity accuracy, not just issue detection
- **Exploit generation** — Ask agents to produce PoC exploits for found vulnerabilities
- **Agentic tool use** — Let agents run linters, type checkers, or tests as sub-actions

---

<div align="center">

**Built with [OpenEnv](https://github.com/meta-pytorch/OpenEnv) by Meta** &nbsp;·&nbsp; **Deployed on [Hugging Face Spaces](https://huggingface.co/spaces)**

</div>
