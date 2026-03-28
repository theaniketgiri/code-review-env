# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Client for the Code Review OpenEnv environment."""

from typing import Any

from openenv.core import EnvClient
from openenv.core.client_types import StepResult

try:
    from .models import ReviewAction, ReviewObservation, ReviewState
except ImportError:
    from models import ReviewAction, ReviewObservation, ReviewState


class CodeReviewEnv(EnvClient[ReviewAction, ReviewObservation, ReviewState]):
    """WebSocket client for interacting with the code review environment."""

    def _step_payload(self, action: ReviewAction) -> dict[str, Any]:
        return {
            "review_comment": action.review_comment,
            "issues_found": action.issues_found,
            "severity": action.severity,
        }

    def _parse_result(self, payload: dict[str, Any]) -> StepResult[ReviewObservation]:
        obs_data = payload.get("observation", {})
        observation = ReviewObservation(
            task_id=obs_data.get("task_id", "task_easy"),
            file_name=obs_data.get("file_name", ""),
            task_description=obs_data.get("task_description", ""),
            code_snippet=obs_data.get("code_snippet", ""),
            feedback=obs_data.get("feedback", ""),
            step_number=obs_data.get("step_number", 0),
            available_issue_tags=obs_data.get("available_issue_tags", []),
            done=payload.get("done", False),
            reward=payload.get("reward"),
            metadata=obs_data.get("metadata", {}),
        )
        return StepResult(
            observation=observation,
            reward=payload.get("reward"),
            done=payload.get("done", False),
        )

    def _parse_state(self, payload: dict[str, Any]) -> ReviewState:
        return ReviewState(
            episode_id=payload.get("episode_id", ""),
            step_count=payload.get("step_count", 0),
            current_task_id=payload.get("current_task_id", "task_easy"),
            max_steps=payload.get("max_steps", 3),
        )
