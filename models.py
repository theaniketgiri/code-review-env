# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""
Typed models for the Code Review environment.

These models define the contract between the agent/client and server.
"""

from typing import Literal

from openenv.core.env_server.types import Action, Observation, State
from pydantic import Field


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


class ReviewAction(Action):
    """Action submitted by the agent after reviewing a code snippet."""

    review_comment: str = Field(
        ...,
        description="Human-readable review explaining identified issues and suggested fixes.",
    )
    issues_found: list[str] = Field(
        default_factory=list,
        description="List of issue tags found by the agent, chosen from ISSUE_TAXONOMY.",
    )
    severity: Literal["low", "medium", "high", "critical"] = Field(
        default="medium",
        description="Overall severity level assessed by the agent for this review.",
    )


class ReviewObservation(Observation):
    """Observation returned by the environment before/after a review step."""

    task_id: str = Field(
        default="task_easy",
        description="Current task identifier such as task_easy, task_medium, or task_hard.",
    )
    file_name: str = Field(
        default="",
        description="File name associated with the code snippet under review.",
    )
    task_description: str = Field(
        default="",
        description="Instructions describing what the agent should review and return.",
    )
    code_snippet: str = Field(
        default="",
        description="Python code snippet containing planted issues for review.",
    )
    feedback: str = Field(
        default="",
        description="Grading feedback for the most recent action or startup guidance after reset.",
    )
    step_number: int = Field(
        default=0,
        description="Current step number within the episode (starts at 0 right after reset).",
    )
    available_issue_tags: list[str] = Field(
        default_factory=lambda: ISSUE_TAXONOMY.copy(),
        description="Allowed issue tags that the agent can use in issues_found.",
    )


class ReviewState(State):
    """Episode-level internal state for the environment."""

    current_task_id: str = Field(
        default="task_easy",
        description="Task currently loaded in the episode.",
    )
    max_steps: int = Field(
        default=3,
        description="Maximum number of review attempts allowed in one episode.",
    )
    best_score: float = Field(
        default=0.0,
        description="Highest score achieved across all steps in this episode.",
    )


# Backward-compatible aliases while migrating scaffolded files.
CodeReviewAction = ReviewAction
CodeReviewObservation = ReviewObservation
CodeReviewState = ReviewState
