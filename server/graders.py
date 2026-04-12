from dataclasses import dataclass

from .tasks import Task


ISSUE_KEYWORDS: dict[str, list[str]] = {
    "null_pointer": ["null", "none", "not check", "missing check", "dereference"],
    "missing_return": ["return", "missing", "no return", "never returns", "none returned"],
    "sql_injection": ["sql", "injection", "f-string", "sanitize", "parameterize", "query"],
    "hardcoded_secret": ["hardcoded", "secret", "credential", "env var", "plaintext", "key"],
    "race_condition": ["race", "atomic", "concurrent", "lock", "thread", "non-atomic"],
    "timing_attack": ["timing", "constant time", "hmac", "compare_digest", "constant-time"],
    "improper_error_handling": ["except", "swallow", "silent", "bare except", "error handling"],
    "type_error": ["type", "string", "int", "cast", "convert", "parse", "non-numeric"],
    "index_out_of_bounds": ["index", "bounds", "length", "len(", "off-by-one", "range"],
    "integer_overflow": ["overflow", "integer", "wrap", "large", "max", "2^31", "negative"],
    "path_traversal": ["path", "traversal", "directory", "../", "join", "sanitize", "escape"],
    "missing_input_validation": ["validation", "validate", "input", "sanitize", "check", "untrusted"],
}

# Expected severity by difficulty level (used for severity scoring bonus)
EXPECTED_SEVERITY: dict[str, str] = {
    "extra_easy": "low",
    "easy": "medium",
    "medium": "high",
    "hard": "critical",
    "expert": "critical",
}


@dataclass(frozen=True)
class GradeBreakdown:
    score: float
    correctly_found: set[str]
    missed: set[str]
    false_positives: set[str]
    severity_correct: bool


def _comment_has_quality_signal(issue_tag: str, comment: str) -> bool:
    keywords = ISSUE_KEYWORDS.get(issue_tag, [])
    lowered_comment = comment.lower()
    return any(keyword in lowered_comment for keyword in keywords)


def grade_review(
    action_issues: list[str],
    action_comment: str,
    task: Task,
    action_severity: str = "medium",
) -> float:
    """
    Deterministic grader for code review actions.

    Formula:
        base_score = |correct| / |planted|
        quality_bonus = +0.05 for each correct issue with matching keywords in comment
        severity_bonus = +0.05 if severity matches expected level for task difficulty
        precision_penalty = -0.1 for each false-positive issue
        final = clamp(base + bonuses - penalty, 0.0, 1.0)
    """
    try:
        submitted = set(action_issues or [])
        planted = set(task.planted_issues or [])

        if not submitted or not planted:
            return 0.0

        correctly_found = submitted & planted
        false_positives = submitted - planted

        base_score = len(correctly_found) / len(planted)

        quality_bonus = 0.0
        safe_comment = action_comment or ""
        for issue_tag in correctly_found:
            if _comment_has_quality_signal(issue_tag, safe_comment):
                quality_bonus += 0.05

        # Severity scoring bonus
        severity_bonus = 0.0
        expected = EXPECTED_SEVERITY.get(task.difficulty, "medium")
        if action_severity.lower() == expected:
            severity_bonus = 0.05

        precision_penalty = 0.1 * len(false_positives)

        raw_score = base_score + quality_bonus + severity_bonus - precision_penalty
        return float(max(0.0, min(1.0, raw_score)))
    except Exception:
        return 0.0


def grade_review_with_breakdown(
    action_issues: list[str],
    action_comment: str,
    task: Task,
    action_severity: str = "medium",
) -> GradeBreakdown:
    """Utility helper for environment feedback text and endpoint diagnostics."""
    try:
        submitted = set(action_issues or [])
        planted = set(task.planted_issues or [])

        correctly_found = submitted & planted
        false_positives = submitted - planted
        missed = planted - submitted

        expected = EXPECTED_SEVERITY.get(task.difficulty, "medium")
        severity_correct = action_severity.lower() == expected

        score = grade_review(action_issues, action_comment, task, action_severity)
        return GradeBreakdown(
            score=score,
            correctly_found=correctly_found,
            missed=missed,
            false_positives=false_positives,
            severity_correct=severity_correct,
        )
    except Exception:
        return GradeBreakdown(
            score=0.0, correctly_found=set(), missed=set(),
            false_positives=set(), severity_correct=False,
        )
