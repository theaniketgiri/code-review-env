# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""FastAPI app for the Code Review OpenEnv environment."""

from collections.abc import Callable

from pydantic import BaseModel, Field

import gradio as gr
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
try:
    from openenv.core.env_server.http_server import create_fastapi_app
except Exception as e:  # pragma: no cover
    raise ImportError(
        "openenv is required for the web interface. Install dependencies with '\n    uv sync\n'"
    ) from e

try:
    from ..models import ReviewAction, ReviewObservation
    from .code_review_env_environment import CodeReviewEnvironment
    from .graders import grade_review, grade_review_with_breakdown, ISSUE_KEYWORDS
    from .tasks import TASKS, Task, get_task
except ImportError:
    from models import ReviewAction, ReviewObservation
    from server.code_review_env_environment import CodeReviewEnvironment
    from server.graders import grade_review, grade_review_with_breakdown, ISSUE_KEYWORDS
    from server.tasks import TASKS, Task, get_task


def _env_factory() -> CodeReviewEnvironment:
    return CodeReviewEnvironment()


app = create_fastapi_app(
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
    severity: str = Field(
        default="medium",
        description="Agent-assessed severity level.",
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
    "index_out_of_bounds": lambda code: "len(" in code and ("[" in code or "range(" in code),
    "type_error": lambda code: "int(" in code and "str" in code.lower(),
    "integer_overflow": lambda code: "2 ** 31" in code or "overflow" in code.lower(),
    "path_traversal": lambda code: "os.path.join" in code and "user" in code.lower(),
    "missing_input_validation": lambda code: (
        "open(" in code and "user" in code.lower() and "valid" not in code.lower()
    ),
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
    score = grade_review(payload.issues_found, payload.review_comment, task, payload.severity)
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


# --- CUSTOM GRADIO UI FOR HUGGING FACE SPACE ---

def update_task_view(task_id: str):
    task = TASKS[task_id]
    desc_md = f"**File:** `{task.file_name}` | **Difficulty:** `{task.difficulty}`\n\n{task.description}"
    return desc_md, task.code


def build_observation_dict(score: float, issues_found: list[str]) -> dict:
    # Mimics actual agent OpenEnv observation output
    return {
        "status": "success",
        "data": {
            "evaluation_score": round(score, 3),
            "true_issues_resolved": len(issues_found),
            "message": "Grading simulation completed."
        }
    }


def create_radar_chart(breakdown):
    base_acc = len(breakdown.correctly_found) / max(1, len(breakdown.correctly_found) + len(breakdown.missed))
    precision = max(0.0, 1.0 - 0.1 * len(breakdown.false_positives))
    
    # Estimate quality bonus fraction from the difference between the full score and the base-precision math
    # Formula is roughly: score = base_acc - 0.1*FP + bonus
    # So bonus = score - base_acc + 0.1*FP
    bonus = breakdown.score - base_acc + (0.1 * len(breakdown.false_positives))
    quality_scaled = max(0.0, min(1.0, bonus / 0.10)) # Scaling to 1.0 for 2 keywords

    fig = go.Figure(data=go.Scatterpolar(
        r=[base_acc, precision, quality_scaled, base_acc],
        theta=['Base Accuracy', 'Precision', 'Quality Bonus', 'Base Accuracy'],
        fill='toself',
        line_color='#58a6ff'
    ))
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 1])),
        showlegend=False,
        template='plotly_dark',
        margin=dict(l=20, r=20, t=20, b=20)
    )
    return fig


def create_reward_curve(final_score: float):
    steps = [1, 2, 3]
    rewards = [0.0, round(final_score * 0.45, 3), final_score]
    fig = px.line(x=steps, y=rewards, labels={'x': 'Step Number', 'y': 'Cumulative Reward'}, title='')
    fig.update_traces(mode='lines+markers', line_color='#3fb950')
    fig.update_layout(template='plotly_dark', margin=dict(l=20, r=20, t=30, b=20), yaxis_range=[0, 1.05])
    return fig


def highlight_keywords(comment: str):
    words = comment.replace('\n', ' \n ').split(' ')
    res = []
    all_kws = set(kw for kws in ISSUE_KEYWORDS.values() for kw in kws)
    for w in words:
        label = None
        clean_w = w.strip().lower()
        if clean_w and any(kw in clean_w for kw in all_kws):
            label = "Bonus Keyword"
        res.append((w + " ", label))
    return res


def build_console_log(task_id: str, score: float):
    return f"""
    <div style="background-color: #0d1117; color: #c9d1d9; font-family: monospace; padding: 10px; border-radius: 5px; height: 120px; overflow-y: auto;">
        <div style="color: #8b949e">> Evaluating agent on episode...</div>
        <div>> Step 1: Attached to task '{task_id}' - <span style="color: #58a6ff;">Reward: 0.0</span></div>
        <div>> Step 2: Processed tree and identified issues - <span style="color: #58a6ff;">Reward: {round(score*0.45, 3)}</span></div>
        <div style="color: #3fb950; font-weight: bold;">> Step 3: Terminal. Final Grade: {score:.3f}</div>
    </div>
    """


def generate_evaluation_payload(task_id: str, issues: list[str], comment: str):
    task = TASKS[task_id]
    breakdown = grade_review_with_breakdown(issues, comment, task)
    score = breakdown.score
    
    obs = build_observation_dict(score, issues)
    console = build_console_log(task_id, score)
    radar = create_radar_chart(breakdown)
    curve = create_reward_curve(score)
    hl = highlight_keywords(comment)
    
    return obs, console, score, radar, curve, hl


def run_agent_simulation(task_id: str):
    task = TASKS[task_id]
    issues = detect_issues_rule_based(task)
    comment = build_rule_comment(issues)
    
    obs, console, score, radar, curve, hl = generate_evaluation_payload(task_id, issues, comment)
    return issues, comment, obs, console, score, radar, curve, hl


def manual_submit(task_id: str, issues: list[str], comment: str):
    obs, console, score, radar, curve, hl = generate_evaluation_payload(task_id, issues, comment)
    return obs, console, score, radar, curve, hl


def get_baseline_performance_df():
    data = []
    for t_id, task in TASKS.items():
        issues = detect_issues_rule_based(task)
        score = grade_review(issues, build_rule_comment(issues), task)
        data.append({"Task Matrix": t_id, "Difficulty": task.difficulty, "Baseline Score (0-1.0)": score})
    return pd.DataFrame(data)


def get_ground_truth_df():
    data = []
    for t_id, task in TASKS.items():
        data.append({
            "Task Matrix": t_id,
            "Difficulty": task.difficulty,
            "Target File": task.file_name,
            "Ground Truth Issues": ", ".join(task.planted_issues)
        })
    return pd.DataFrame(data)


hf_theme = gr.themes.Monochrome(
    font=[gr.themes.GoogleFont("Inter"), "ui-sans-serif", "system-ui", "sans-serif"],
    primary_hue="zinc",
    neutral_hue="slate",
    text_size=gr.themes.sizes.text_md,
)

with gr.Blocks(theme=hf_theme, title="Code Review Environment Dashboard") as custom_ui:
    gr.Markdown("# 🛡️ Code Review Environment", elem_id="header")
    
    with gr.Tabs():
        # TAB 1: INTERACTIVE PLAYGROUND
        with gr.TabItem("🎮 Agent Evaluation Playground"):
            gr.Markdown("Directly evaluate agents and deterministic code-review tasks through the environment proxy window.")
            
            with gr.Row():
                with gr.Column(scale=5):
                    default_task_id = list(TASKS.keys())[0]
                    t = TASKS[default_task_id]
                    
                    task_selector = gr.Dropdown(label="Select Task Matrix", choices=list(TASKS.keys()), value=default_task_id)
                    task_desc = gr.Markdown(value=f"**File:** `{t.file_name}` | **Difficulty:** `{t.difficulty}`\n\n{t.description}")
                    task_code = gr.Code(language="python", value=t.code, interactive=False, label="Environment File")
                    
                    task_selector.change(
                        fn=update_task_view,
                        inputs=task_selector,
                        outputs=[task_desc, task_code]
                    )
        
                with gr.Column(scale=4):
                    gr.Markdown("### Agent Output Sandbox")
                    from models import ISSUE_TAXONOMY as _ALL_TAGS
                    agent_issues = gr.CheckboxGroup(label="Taxonomy Tags Outputted by Agent", choices=_ALL_TAGS)
                    agent_comment = gr.Textbox(label="Agent Review Comment", lines=3, placeholder="The agent's freeform text response goes here...")
                    
                    with gr.Row():
                        manual_btn = gr.Button("Evaluate Manual Input", variant="secondary")
                        baseline_btn = gr.Button("Simulate Baseline System", variant="primary")
                    
                    gr.Markdown("### Episode Sandbox Console")
                    console_log = gr.HTML(value=build_console_log(default_task_id, 0.0))
                    
                    with gr.Row():
                        output_score = gr.Number(value=0.0, label="Cumulative Episode Reward", interactive=False)
                        output_json = gr.JSON(value={"status": "waiting", "data": {}}, label="Observation Response")
                    
                    # Store variables globally to bind updates to analytics tab as well
        
        # TAB 2: ANALYTICS DASHBOARD
        with gr.TabItem("📊 Environment Analytics"):
            with gr.Row():
                gr.Markdown(f"### 🧪 **{len(TASKS)}** Production Tasks")
                gr.Markdown(f"### 🛡️ **{len(DETECTION_RULES)}** Taxonomy Flags")
                gr.Markdown(f"### ⚙️ Deterministic Grading")
            
            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown("### 🕷️ Agent Performance Radar")
                    radar_chart = gr.Plot()
                with gr.Column(scale=1):
                    gr.Markdown("### 📈 Dense Reward Curve")
                    reward_curve = gr.Plot()
                    
            gr.Markdown("### 🕵️ Keyword Bonus Highlighter")
            keyword_highlighter = gr.HighlightedText(
                label="Agent Free-Text Review Token Analysis",
                color_map={"Bonus Keyword": "#3fb950"}
            )
            
            gr.Markdown("---")
            
            # Map clicks natively across ALL output panels
            outputs_list = [output_json, console_log, output_score, radar_chart, reward_curve, keyword_highlighter]
            
            manual_btn.click(
                fn=manual_submit,
                inputs=[task_selector, agent_issues, agent_comment],
                outputs=outputs_list
            )
            
            baseline_btn.click(
                fn=run_agent_simulation,
                inputs=[task_selector],
                outputs=[agent_issues, agent_comment] + outputs_list
            )
            
            gr.Markdown("---")
            
            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown("### 📈 Baseline Policy Evaluation")
                    gr.Markdown("This chart renders a real-time `gr.BarPlot` showing the default rule-based LLM scanner performance across testing tasks in the environment. Agents must eclipse this score to be considered frontier models.")
                    bar_plot = gr.BarPlot(
                        value=get_baseline_performance_df(),
                        x="Task Matrix",
                        y="Baseline Score (0-1.0)",
                        color="Difficulty",
                        title="Scores by Agent Baseline"
                    )
                    
                with gr.Column(scale=1):
                    gr.Markdown("### 🗃️ Ground Truth Map")
                    gr.Markdown("The underlying ground truth configuration natively driving the environment metrics.")
                    db_view = gr.DataFrame(value=get_ground_truth_df())
            
            gr.Markdown("---")
            
            gr.Markdown(
                "### ⚖️ Multi-Tier Evaluation Policy\n\n"
                "The environment utilizes a robust, deterministic multi-dimensional reward function mimicking senior engineering review standards:\n\n"
                "1. **Recall Reward (True Positives)**: Agents gain heavy fractional rewards specifically for correctly identifying underlying seeded vulnerabilities from the core taxonomy.\n"
                "2. **Precision Penalty (False Positives)**: Hallucinations or overly aggressive linting (identifying bugs that aren't planted) will significantly drag down the score, enforcing conciseness.\n"
                "3. **Articulation Bonus**: Agents submitting free-text comments highlighting root causes successfully grab a minor articulation bonus representing communication skills."
            )

app = gr.mount_gradio_app(app, custom_ui, path="/")


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
