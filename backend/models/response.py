"""Response schemas (Pydantic v2)."""

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ActivityIndicator = Literal["active", "slow", "stale"]

STATUS_METRIC_KEYS = {"is_locked", "activity_indicator", "last_comment_date"}
CHECKLIST_KEYS = {"step_number", "task", "is_completed"}


def validate_status_metrics(value: Dict[str, Any]) -> Dict[str, Any]:
    if set(value) != STATUS_METRIC_KEYS:
        raise ValueError(f"status_metrics must have exactly the keys {sorted(STATUS_METRIC_KEYS)}")
    if not isinstance(value["is_locked"], bool):
        raise ValueError("status_metrics.is_locked must be a boolean")
    if value["activity_indicator"] not in ("active", "slow", "stale"):
        raise ValueError("status_metrics.activity_indicator must be active, slow or stale")
    try:
        date.fromisoformat(str(value["last_comment_date"]))
    except ValueError as exc:
        raise ValueError("status_metrics.last_comment_date must be an ISO date (YYYY-MM-DD)") from exc
    return value


def validate_checklist(value: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    for position, item in enumerate(value, start=1):
        if set(item) != CHECKLIST_KEYS:
            raise ValueError(f"each checklist item must have exactly the keys {sorted(CHECKLIST_KEYS)}")
        step = item["step_number"]
        if isinstance(step, bool) or not isinstance(step, int) or step != position:
            raise ValueError("checklist step_number values must be sequential integers starting at 1")
        if not isinstance(item["task"], str) or not item["task"].strip():
            raise ValueError("checklist task must be a non-empty string")
        if not isinstance(item["is_completed"], bool):
            raise ValueError("checklist is_completed must be a boolean")
    return value


class IssueCard(BaseModel):
    """A GitHub issue researched live and mapped into a card."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(..., min_length=1, max_length=40, description="The GitHub issue id.")
    title: str = Field(..., min_length=1)
    repo_name: str = Field(..., min_length=1)
    repo_owner: str = Field(..., min_length=1)
    programming_language: str = Field(..., min_length=1, max_length=60)
    topics: List[str]
    github_issue_url: str
    contributing_guidelines_url: str
    status_metrics: Dict[str, Any]
    difficulty_rating: int = Field(..., ge=1, le=5)
    context_summary: str
    actionable_checklist: List[Dict[str, Any]]
    # Where in the repository the change will happen, and who is active on the thread.
    affected_paths: List[str] = Field(default_factory=list)
    active_handles: List[str] = Field(default_factory=list)
    state: Literal["open", "closed"] = "open"
    assignee_count: int = Field(0, ge=0)
    comment_count: int = Field(0, ge=0)

    @field_validator("status_metrics")
    @classmethod
    def _check_status_metrics(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        return validate_status_metrics(value)

    @field_validator("actionable_checklist")
    @classmethod
    def _check_checklist(cls, value: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return validate_checklist(value)


class HealthBadge(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    label: str
    state: Literal["good", "warn", "bad"]
    detail: str


class VerifyResponse(BaseModel):
    """Result of checking an issue's health (the CHECK pillar)."""

    model_config = ConfigDict(extra="forbid", strict=True)

    github_url: str
    issue_id: str
    health_state: Literal["healthy", "caution", "blocked"]
    health_score: int = Field(..., ge=0, le=100)
    badges: List[HealthBadge]
    checked_at: str
    issue: IssueCard


class PlanResponse(BaseModel):
    """A contribution plan (the GET STARTED pillar)."""

    model_config = ConfigDict(extra="forbid", strict=True)

    issue_id: str
    title: str
    repo_full_name: str
    github_issue_url: str
    contributing_guidelines_url: str
    context_summary: str
    actionable_checklist: List[Dict[str, Any]]

    @field_validator("actionable_checklist")
    @classmethod
    def _check_checklist(cls, value: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return validate_checklist(value)


class FacetsResponse(BaseModel):
    """What the filter panel can offer, plus whether GitHub calls are authenticated."""

    languages: List[str]
    topics: List[str]
    github_authenticated: bool


class BookmarkOut(BaseModel):
    """A saved issue as stored in SQLite."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    repo_name: str
    repo_owner: str
    programming_language: str
    github_issue_url: str
    bookmarked_at: datetime

    @field_validator("bookmarked_at")
    @classmethod
    def _as_utc(cls, value: datetime) -> datetime:
        # SQLite drops the timezone; everything we store is UTC.
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class BookmarkConfirmation(BaseModel):
    status: Literal["saved"] = "saved"
    created: bool
    bookmark: BookmarkOut


class BookmarkDeleted(BaseModel):
    status: Literal["deleted"] = "deleted"
    id: str
