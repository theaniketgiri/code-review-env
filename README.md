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

# Code Review OpenEnv Benchmark

## 🚀 Scaler March 2026 Hackathon Submission

This project was built as part of the **Scaler March 2026 Hackathon**.

**Author:** Dolphin-Syndrom  
**Type:** OpenEnv Benchmark Environment  
**Focus:** Evaluating LLM agents on security-aware code review tasks

---

## ⚡ TL;DR

A benchmark environment for evaluating LLM agents on taxonomy-driven pull-request reviews.

- 3 tasks (easy → medium → hard)
- structured actions and observations
- reward-based learning signals
- deterministic grading (0.0–1.0)
- deployable via Docker on Hugging Face Spaces
- fully OpenEnv compliant

---

> Designed to evaluate whether AI agents can perform structured, taxonomy-driven code review under constrained interaction loops.
>
> Suitable for benchmarking agent performance, reward shaping strategies, and detection accuracy without hallucinating false positives.

This environment models a real-world engineering task: pull-request review. It evaluates whether an agent can read code snippets, identify security vulnerabilities and logic errors using a fixed taxonomy, and articulate its findings clearly.

## Overview

This project is designed for OpenEnv-style agent evaluation with:

- a real-world task instead of a toy problem
- typed `Observation`, `Action`, `Reward`, and `State` models
- `step()`, `reset()`, and `state()` APIs
- three tasks with deterministic graders
- dense reward shaping for partial progress
- a reproducible baseline `inference.py`
- a FastAPI server and Dockerfile for deployment

The environment models a practical workflow engineers actually do:

- static code analysis
- vulnerability detection
- taxonomy-driven bug tagging
- code review articulation

## Environment Specification

### Objective

For each episode, the agent sees a Python code snippet containing planted issues and must make structured decisions:

1. identify issues using tags from a 12-item `ISSUE_TAXONOMY` (e.g., `null_pointer`, `sql_injection`, `race_condition`)
2. assess overall severity (`low`, `medium`, `high`, `critical`)
3. articulate its findings in a human-readable `review_comment`

Performance is measured two ways:

- dense step rewards during interaction
- final deterministic grader scores between `0.0` and `1.0`

### State

The internal environment state tracks:

- current task ID, file name, and planted issues
- episode ID and step count
- maximum allowed steps (3 per episode)

The full state is available through the OpenEnv `state()` API for debugging and validation, but the agent does not directly observe the ground-truth issues during normal play.

### Observation Space

The agent receives:

- `task_id`
- `file_name`
- `task_description`
- `code_snippet`
- `feedback` from previous grading
- `step_number`
- `available_issue_tags`

### Action Space

The environment accepts structured actions:

- `issues_found(list[str])` selected from the 12-tag `ISSUE_TAXONOMY`
- `severity(level)` where `level` is one of `low`, `medium`, `high`, `critical`
- `review_comment(text)` explaining the identified issues

Invalid or hallucinated tags are penalized as false positives.

### Episode Flow

1. `reset()` loads a task and returns the initial observation
2. the agent receives an observation with the code snippet
3. the agent acts through `step(action)`
4. the environment returns `(observation, reward, done, info)`
5. the episode ends when the score ≥ 0.95 or the maximum step limit (3) is reached

## Tasks

### Easy Task

Null Pointer & Missing Return.

- goal: evaluate `user_service.py` to catch a `.get()` missing a null check, and a missing return statement.
- grader: weighted string-matching and set intersection

### Medium Task

SQL Injection & Hardcoded Secret.

- goal: evaluate `auth.py` to identify f-string SQL injection and a plaintext secret key.
- grader: weighted string-matching and set intersection

### Hard Task

Race Condition, Error Handling & Timing Attack.

- goal: evaluate `payments.py` for non-atomic operations, bare excepts, and non-constant-time comparisons.
- grader: weighted string-matching and set intersection

## Reward Design

**Summary:** Correct behavior yields positive reward (~1.0), random strategies are penalized (negative reward), ensuring meaningful learning signals.

The benchmark uses dense, shaped rewards so agents receive signal across the full trajectory instead of only at episode end.

Core components:

- recall reward (fractional points for correctly identified issues)
- quality bonus (+0.05 per correct issue with a matching keyword in the comment)
- precision penalty (-0.10 for hallucinated or false-positive issues)

This gives a better learning signal for agent training while the final graders still produce simple deterministic scores in the `0.0` to `1.0` range.

## Dataset

The built-in dataset contains 3 distinct tasks covering a range of issues:

- `task_easy`: Logic errors (`null_pointer`, `missing_return`)
- `task_medium`: Security vulnerabilities (`sql_injection`, `hardcoded_secret`)
- `task_hard`: Robustness issues (`race_condition`, `improper_error_handling`, `timing_attack`)

## Project Structure

```text
.
├── code_review_env/
│   ├── __init__.py
│   ├── client.py
│   ├── models.py
│   ├── inference.py
│   ├── openenv.yaml
│   ├── pyproject.toml
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── README.md
│   ├── scripts/
│   │   └── validate-submission.sh
│   └── server/
│       ├── __init__.py
│       ├── app.py
│       ├── code_review_env_environment.py
│       ├── graders.py
│       ├── tasks.py
│       ├── requirements.txt
│       └── Dockerfile
```

## Setup

From the repository root:

```bash
uv sync --frozen
# OR using pip:
pip install -r requirements.txt
pip install -r server/requirements.txt
```

## Local Usage

### Start the OpenEnv server

```bash
uv run uvicorn server.app:app --host 0.0.0.0 --port 8000
```
or without uv:
```bash
python -m code_review_env.server.app
```

## Baseline Inference

The baseline script uses the OpenAI Python client and reads configuration from environment variables:

- `API_BASE_URL`
- `MODEL_NAME`
- `HF_TOKEN`

Example:

```bash
export API_BASE_URL=https://router.huggingface.co/v1
export MODEL_NAME=Qwen/Qwen2.5-72B-Instruct
export HF_TOKEN=your-token
python inference.py
```

Behavior:

- tries an LLM-backed agent first
- falls back to deterministic heuristics when credentials or network access are unavailable
- emits structured `[START]`, `[STEP]`, and `[END]` logs
- safely handles rate-limit and transient LLM errors

## Validation

```bash
openenv validate .
./scripts/validate-submission.sh http://localhost:8000 .
```

## 🔌 API Usage

All endpoints are OpenEnv-compatible and return structured JSON responses.

### Health Check
GET /health

### Reset Environment
POST /reset  
Optional body:
```json
{"task_id": "task_easy"}
```

### Take Step

POST /step
Body:

```json
{
  "review_comment": "Null dereference risk on birthdate.",
  "issues_found": ["null_pointer"],
  "severity": "medium"
}
```

### Get State

GET /state

## Docker

Build and run:

```bash
docker build -t code-review-openenv -f Dockerfile .
docker run -p 8000:8000 code-review-openenv
```

## Hugging Face Spaces

This repo is structured for Docker-based deployment to Hugging Face Spaces.

Recommended setup:

- SDK: `Docker`
- hardware: CPU Basic is sufficient
- set `API_BASE_URL`, `MODEL_NAME`, and `HF_TOKEN` in Space secrets if you want the LLM baseline enabled

## 🏁 Submission Status

This environment:

- passes OpenEnv validation
- successfully deploys via Docker on Hugging Face Spaces
- supports full agent interaction through API endpoints
- was tested end-to-end including inference and grading pipeline

Built, debugged, and deployed under hackathon constraints.

---

## 🔗 Links

- GitHub Repository: https://github.com/Dolphin-Syndrom/code-review-env
- Hugging Face Space: https://huggingface.co/spaces/Dolphin-Syndrom/code-review-env

## Why This Environment Fits The Problem Statement

- real-world utility: code review is a practical daily workflow
- three tasks with deterministic graders: easy, medium, hard
- meaningful reward shaping: partial progress, articulation bonuses, and hallucination penalties
- OpenEnv-compatible API and typed models
- baseline inference script included at repo root
- containerization included for deployment

## Extensibility

Possible next steps:

- more languages such as JavaScript, Go, or Rust
- multi-file reviews and cross-file dependency analysis
- diff-based input instead of full files
- severity grading accuracy
- target exploit generation

## License

BSD-3-Clause
