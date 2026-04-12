"""Tests for the grading logic."""

import pytest

from server.graders import grade_review, grade_review_with_breakdown, GradeBreakdown
from server.tasks import TASKS, get_task


class TestGradeReview:
    """Test the deterministic grade_review function."""

    def test_perfect_score_easy(self):
        task = get_task("task_easy")
        score = grade_review(
            ["null_pointer", "missing_return"],
            "Null dereference risk and missing return statement.",
            task,
            "medium",
        )
        # base=1.0 + quality=0.10 + severity=0.05 = 1.0 (clamped)
        assert score >= 0.95

    def test_perfect_score_medium(self):
        task = get_task("task_medium")
        score = grade_review(
            ["sql_injection", "hardcoded_secret"],
            "SQL injection via f-string. Hardcoded secret key in plaintext.",
            task,
            "high",
        )
        assert score >= 0.95

    def test_perfect_score_hard(self):
        task = get_task("task_hard")
        score = grade_review(
            ["race_condition", "improper_error_handling", "timing_attack"],
            "Non-atomic race condition. Bare except swallows errors. Timing attack via non-constant-time comparison.",
            task,
            "critical",
        )
        assert score >= 0.95

    def test_empty_submission_scores_zero(self):
        task = get_task("task_easy")
        score = grade_review([], "", task)
        assert score == 0.0

    def test_no_issues_scores_zero(self):
        task = get_task("task_easy")
        score = grade_review([], "Everything looks fine.", task)
        assert score == 0.0

    def test_partial_recall(self):
        task = get_task("task_easy")
        score = grade_review(["null_pointer"], "Found null issue.", task)
        # base = 1/2 = 0.5
        assert 0.4 <= score <= 0.7

    def test_false_positive_penalty(self):
        task = get_task("task_easy")
        score_clean = grade_review(["null_pointer"], "Null check missing.", task)
        score_fp = grade_review(
            ["null_pointer", "sql_injection"],
            "Null check missing.",
            task,
        )
        # False positive should reduce score
        assert score_fp < score_clean

    def test_quality_bonus_with_keywords(self):
        task = get_task("task_easy")
        score_no_kw = grade_review(["null_pointer"], "Found an issue.", task)
        score_kw = grade_review(
            ["null_pointer"],
            "Null dereference — the .get() call may return None without a check.",
            task,
        )
        assert score_kw >= score_no_kw

    def test_severity_bonus(self):
        task = get_task("task_medium")
        score_wrong = grade_review(
            ["sql_injection"], "Issues found.", task, "low"
        )
        score_correct = grade_review(
            ["sql_injection"], "Issues found.", task, "high"
        )
        assert score_correct > score_wrong

    def test_all_false_positives_score_zero(self):
        task = get_task("task_easy")
        score = grade_review(
            ["sql_injection", "race_condition", "timing_attack"],
            "Multiple issues.",
            task,
        )
        assert score == 0.0

    def test_score_clamped_to_one(self):
        task = get_task("task_easy")
        score = grade_review(
            ["null_pointer", "missing_return"],
            "Null None check missing return statement.",
            task,
            "medium",
        )
        assert score <= 1.0

    def test_score_clamped_to_zero(self):
        task = get_task("task_hard")
        score = grade_review(
            ["null_pointer", "missing_return", "sql_injection", "hardcoded_secret"],
            "Wrong issues.",
            task,
        )
        assert score >= 0.0


class TestGradeBreakdown:
    """Test the grade_review_with_breakdown function."""

    def test_breakdown_fields(self):
        task = get_task("task_easy")
        bd = grade_review_with_breakdown(
            ["null_pointer", "sql_injection"],
            "Null issue found.",
            task,
        )
        assert isinstance(bd, GradeBreakdown)
        assert "null_pointer" in bd.correctly_found
        assert "missing_return" in bd.missed
        assert "sql_injection" in bd.false_positives

    def test_severity_correct_flag(self):
        task = get_task("task_medium")
        bd = grade_review_with_breakdown(
            ["sql_injection"], "SQL injection.", task, "high"
        )
        assert bd.severity_correct is True

        bd_wrong = grade_review_with_breakdown(
            ["sql_injection"], "SQL injection.", task, "low"
        )
        assert bd_wrong.severity_correct is False


class TestTaskCoverage:
    """Test that all tasks are properly configured."""

    def test_all_tasks_exist(self):
        expected = {"task_extra_easy", "task_easy", "task_medium", "task_hard", "task_expert"}
        assert set(TASKS.keys()) == expected

    def test_all_tasks_have_planted_issues(self):
        for task_id, task in TASKS.items():
            assert len(task.planted_issues) > 0, f"{task_id} has no planted issues"

    def test_difficulty_progression(self):
        difficulties = [TASKS[t].difficulty for t in TASKS]
        assert "extra_easy" in difficulties
        assert "easy" in difficulties
        assert "medium" in difficulties
        assert "hard" in difficulties
        assert "expert" in difficulties

    def test_planted_issue_count_increases(self):
        counts = {t: len(TASKS[t].planted_issues) for t in TASKS}
        assert counts["task_extra_easy"] <= counts["task_easy"]
        assert counts["task_easy"] <= counts["task_medium"]
        assert counts["task_medium"] <= counts["task_hard"]
        assert counts["task_hard"] <= counts["task_expert"]

    def test_get_task_fallback(self):
        task = get_task("nonexistent_task")
        assert task.task_id == "task_easy"
