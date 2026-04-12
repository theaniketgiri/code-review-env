"""Tests for the environment lifecycle."""

import pytest

from server.code_review_env_environment import CodeReviewEnvironment
from models import ReviewAction, ReviewObservation


class TestEnvironmentReset:
    """Test environment reset behavior."""

    def test_reset_returns_observation(self):
        env = CodeReviewEnvironment()
        obs = env.reset(task_id="task_easy")
        assert isinstance(obs, ReviewObservation)
        assert obs.task_id == "task_easy"
        assert obs.code_snippet != ""
        assert obs.done is False
        assert obs.reward == 0.0

    def test_reset_different_tasks(self):
        env = CodeReviewEnvironment()
        for task_id in ["task_extra_easy", "task_easy", "task_medium", "task_hard", "task_expert"]:
            obs = env.reset(task_id=task_id)
            assert obs.task_id == task_id
            assert obs.step_number == 0

    def test_reset_unknown_task_falls_back(self):
        env = CodeReviewEnvironment()
        obs = env.reset(task_id="nonexistent")
        assert obs.task_id == "task_easy"

    def test_reset_clears_state(self):
        env = CodeReviewEnvironment()
        obs = env.reset(task_id="task_easy")
        action = ReviewAction(
            review_comment="test",
            issues_found=["null_pointer"],
            severity="medium",
        )
        env.step(action)
        assert env.state.step_count == 1

        obs = env.reset(task_id="task_medium")
        assert env.state.step_count == 0
        assert env.state.best_score == 0.0


class TestEnvironmentStep:
    """Test environment step behavior."""

    def test_step_increments_count(self):
        env = CodeReviewEnvironment()
        env.reset(task_id="task_easy")
        action = ReviewAction(
            review_comment="Found issues.",
            issues_found=["null_pointer"],
            severity="medium",
        )
        obs = env.step(action)
        assert obs.step_number == 1
        assert env.state.step_count == 1

    def test_perfect_step_gives_high_reward(self):
        env = CodeReviewEnvironment()
        env.reset(task_id="task_easy")
        action = ReviewAction(
            review_comment="Null pointer dereference and missing return statement.",
            issues_found=["null_pointer", "missing_return"],
            severity="medium",
        )
        obs = env.step(action)
        assert obs.reward >= 0.95

    def test_wrong_issues_give_low_reward(self):
        env = CodeReviewEnvironment()
        env.reset(task_id="task_easy")
        action = ReviewAction(
            review_comment="SQL injection found.",
            issues_found=["sql_injection"],
            severity="high",
        )
        obs = env.step(action)
        assert obs.reward == 0.0

    def test_episode_terminates_at_max_steps(self):
        env = CodeReviewEnvironment()
        env.reset(task_id="task_easy")
        action = ReviewAction(
            review_comment="test",
            issues_found=[],
            severity="low",
        )
        for _ in range(3):
            obs = env.step(action)
        assert obs.done is True

    def test_early_termination_on_high_score(self):
        env = CodeReviewEnvironment()
        env.reset(task_id="task_easy")
        action = ReviewAction(
            review_comment="Null pointer None check and missing return statement.",
            issues_found=["null_pointer", "missing_return"],
            severity="medium",
        )
        obs = env.step(action)
        assert obs.done is True  # score >= 0.95

    def test_best_score_tracking(self):
        env = CodeReviewEnvironment()
        env.reset(task_id="task_easy")

        action1 = ReviewAction(
            review_comment="Found null issue.",
            issues_found=["null_pointer"],
            severity="low",
        )
        obs1 = env.step(action1)
        first_score = obs1.reward

        action2 = ReviewAction(
            review_comment="test",
            issues_found=[],
            severity="low",
        )
        obs2 = env.step(action2)

        # best_score should be the max across all steps
        assert obs2.metadata["best_score"] >= first_score

    def test_feedback_contains_refinement_hints(self):
        env = CodeReviewEnvironment()
        env.reset(task_id="task_easy")
        action = ReviewAction(
            review_comment="test",
            issues_found=["null_pointer"],
            severity="low",
        )
        obs = env.step(action)
        # Should contain hint about what was missed
        assert "Hint" in obs.feedback or obs.done


class TestEnvironmentMetadata:
    """Test observation metadata richness."""

    def test_metadata_fields(self):
        env = CodeReviewEnvironment()
        env.reset(task_id="task_easy")
        action = ReviewAction(
            review_comment="test",
            issues_found=["null_pointer"],
            severity="medium",
        )
        obs = env.step(action)
        assert "correctly_found" in obs.metadata
        assert "missed" in obs.metadata
        assert "false_positives" in obs.metadata
        assert "severity_correct" in obs.metadata
        assert "best_score" in obs.metadata
        assert "max_achievable_score" in obs.metadata
        assert "steps_remaining" in obs.metadata

    def test_steps_remaining_decreases(self):
        env = CodeReviewEnvironment()
        env.reset(task_id="task_easy")
        action = ReviewAction(review_comment="test", issues_found=[], severity="low")

        obs1 = env.step(action)
        assert obs1.metadata["steps_remaining"] == 2

        obs2 = env.step(action)
        assert obs2.metadata["steps_remaining"] == 1
