---
title: Code Review Environment
emoji: 🧠
colorFrom: blue
colorTo: purple
sdk: docker
pinned: false
app_port: 8000
base_path: /web
tags:
  - openenv
  - reinforcement-learning
  - code-review
---

# Code Review Environment (`code-review-env`)

This OpenEnv environment simulates a real software engineering task: reviewing buggy Python code and identifying security and logic issues with fixed taxonomy tags.

## Why this environment

- Real-world utility: PR/code review is a common and valuable engineering workflow.
- RL-friendly: structured action space with dense rewards and deterministic grader.
- Progressive tasks: easy → medium → hard.

## Action space

`ReviewAction` (`models.py`):

- `review_comment` (`str`): human-readable explanation
- `issues_found` (`list[str]`): tags from `ISSUE_TAXONOMY`
- `severity` (`low|medium|high|critical`)

## Observation space

`ReviewObservation` (`models.py`):

- `task_id`, `file_name`, `task_description`
- `code_snippet` to review
- `feedback` after each step
- `step_number`, `reward`, `done`, `metadata`

## Tasks

- `task_easy`: `null_pointer`, `missing_return`
- `task_medium`: `sql_injection`, `hardcoded_secret`
- `task_hard`: `race_condition`, `improper_error_handling`, `timing_attack`

Defined in `server/tasks.py`.

## Reward and grading

Implemented in `server/graders.py`:

- `base_score = |correctly_found| / |planted_issues|`
- `quality_bonus = +0.05` per correctly found issue with comment keywords
- `precision_penalty = -0.1` per false-positive issue
- final score clamped to `[0.0, 1.0]`

## Required endpoints

- `GET /tasks`
- `POST /grader`
- `POST /baseline`
- plus OpenEnv core endpoints (`/reset`, `/step`, `/state`, `/health`, `/ws`)

## Local setup

```bash
cd /home/manvith/OpenEnv/code_review_env
pip install -e .
pip install -r server/requirements.txt
uvicorn server.app:app --host 0.0.0.0 --port 8000
```

## Manual API smoke test

```bash
curl http://localhost:8000/health
curl http://localhost:8000/tasks
curl -X POST http://localhost:8000/baseline
curl -X POST http://localhost:8000/grader \
  -H "Content-Type: application/json" \
  -d '{"task_id":"task_easy","issues_found":["null_pointer"],"review_comment":"missing null check"}'
```

## Baseline inference script

`inference.py` supports two modes:

1. LLM mode (if `OPENAI_API_KEY` is set)
2. Rule-based fallback (no key required)

```bash
# Local fallback mode
python inference.py

# Local LLM mode
OPENAI_API_KEY=sk-... OPENAI_MODEL=gpt-4o-mini python inference.py

# Against HF Space
ENV_URL=https://<your-space>.hf.space python inference.py
```

Example output shape:

```json
{
  "task_easy": {"score": 0.85, "issues_found": ["null_pointer", "missing_return"]},
  "task_medium": {"score": 0.7, "issues_found": ["sql_injection", "hardcoded_secret"]},
  "task_hard": {"score": 0.5, "issues_found": ["race_condition", "improper_error_handling"]}
}
```

## Docker

```bash
docker build -t code-review-env:latest -f server/Dockerfile .
docker run -p 8000:8000 code-review-env:latest
```

## Deploy to Hugging Face Space

```bash
openenv push --repo-id YOUR_USERNAME/code-review-env
```

## Submission links (both required)

1. GitHub repository URL
2. Hugging Face Space URL

## Folder layout

```text
code_review_env/
├── __init__.py
├── client.py
├── inference.py
├── models.py
├── openenv.yaml
├── pyproject.toml
├── README.md
└── server/
    ├── __init__.py
    ├── app.py
    ├── code_review_env_environment.py
    ├── graders.py
    ├── tasks.py
    ├── requirements.txt
    └── Dockerfile
```
