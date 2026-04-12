# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Code Review environment implementation for OpenEnv."""

from uuid import uuid4

from openenv.core.env_server.interfaces import Environment

try:
    from ..models import ReviewAction, ReviewObservation, ReviewState
    from .graders import grade_review_with_breakdown
    from .tasks import get_task
except ImportError:
    from models import ReviewAction, ReviewObservation, ReviewState
    from server.graders import grade_review_with_breakdown
    from server.tasks import get_task


MAX_STEPS = 3


class CodeReviewEnvironment(Environment):
    """Environment where an agent reviews code and tags planted issues."""

    SUPPORTS_CONCURRENT_SESSIONS: bool = True

    def __init__(self):
        default_task = get_task("task_easy")
        self._state = ReviewState(
            episode_id=str(uuid4()),
            step_count=0,
            current_task_id=default_task.task_id,
            max_steps=MAX_STEPS,
        )
        self._current_task = default_task

    def reset(self, task_id: str = "task_easy", **kwargs) -> ReviewObservation:
        """Reset episode and load selected task (fallback to task_easy)."""
        _ = kwargs
        task = get_task(task_id)
        self._current_task = task
        self._state = ReviewState(
            episode_id=str(uuid4()),
            step_count=0,
            current_task_id=task.task_id,
            max_steps=MAX_STEPS,
        )

        return ReviewObservation(
            task_id=task.task_id,
            file_name=task.file_name,
            task_description=task.description,
            code_snippet=task.code,
            feedback="Environment reset. Submit issues_found and review_comment.",
            step_number=0,
            reward=0.0,
            done=False,
            metadata={
                "difficulty": task.difficulty,
                "planted_issue_count": len(task.planted_issues),
            },
        )

    def step(self, action: ReviewAction) -> ReviewObservation:  # type: ignore[override]
        """Grade one review action and return updated observation with refinement feedback."""
        self._state.step_count += 1

        breakdown = grade_review_with_breakdown(
            action_issues=action.issues_found,
            action_comment=action.review_comment,
            task=self._current_task,
            action_severity=action.severity,
        )

        score = breakdown.score

        # Track best score across steps (iterative refinement)
        self._state.best_score = max(self._state.best_score, score)

        done = (score >= 0.95) or (self._state.step_count >= MAX_STEPS)

        correctly_found = sorted(breakdown.correctly_found)
        missed_tags = sorted(breakdown.missed)
        missed_count = len(missed_tags)
        false_positive_count = len(breakdown.false_positives)

        # Iterative refinement feedback: tell agent what to improve
        feedback_parts = [
            f"Score: {score:.3f}",
            f"Found: {correctly_found}",
            f"Missed: {missed_count} remaining",
            f"False positives: {false_positive_count}",
        ]
        if not done and missed_count > 0:
            # Give hints about missed categories without revealing exact tags
            hint_categories = []
            for tag in missed_tags:
                if tag in ("null_pointer", "missing_return", "type_error", "index_out_of_bounds"):
                    hint_categories.append("logic/type issue")
                elif tag in ("sql_injection", "hardcoded_secret", "path_traversal"):
                    hint_categories.append("security vulnerability")
                elif tag in ("race_condition", "timing_attack", "improper_error_handling"):
                    hint_categories.append("robustness/concurrency flaw")
                elif tag in ("integer_overflow", "missing_input_validation"):
                    hint_categories.append("input handling issue")
            unique_hints = sorted(set(hint_categories))
            feedback_parts.append(f"Hint: look for {', '.join(unique_hints)}")

        if not breakdown.severity_correct:
            feedback_parts.append("Severity assessment could be improved")

        feedback = " | ".join(feedback_parts)

        return ReviewObservation(
            task_id=self._current_task.task_id,
            file_name=self._current_task.file_name,
            task_description=self._current_task.description,
            code_snippet=self._current_task.code,
            feedback=feedback,
            step_number=self._state.step_count,
            reward=score,
            done=done,
            metadata={
                "correctly_found": correctly_found,
                "missed": missed_tags,
                "false_positives": sorted(breakdown.false_positives),
                "submitted_severity": action.severity,
                "severity_correct": breakdown.severity_correct,
                "best_score": self._state.best_score,
                "max_achievable_score": 1.0,
                "steps_remaining": MAX_STEPS - self._state.step_count,
            },
        )

    @property
    def state(self) -> ReviewState:
        """Return current episode state."""
        return self._state
