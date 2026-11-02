"""Response schemas (Pydantic v2)."""

from datetime import UTC, date, datetime
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


class IssueSummary(BaseModel):
    """A GitHub issue mapped into a card, without its checklist. This is what the issue list returns."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(..., min_length=1, max_length=40, description="The GitHub issue id.")
    title: str = Field(..., min_length=1, max_length=1000)
    repo_name: str = Field(..., min_length=1, max_length=200)
    repo_owner: str = Field(..., min_length=1, max_length=100)
    programming_language: str = Field(..., min_length=1, max_length=60)
    topics: List[str] = Field(default_factory=list, max_length=10)
    github_issue_url: str = Field(..., max_length=500)
    contributing_guidelines_url: str = Field(..., max_length=500)
    status_metrics: Dict[str, Any]
    difficulty_rating: int = Field(..., ge=1, le=5)
    context_summary: str = Field(..., max_length=700)
    # Where in the repository the change will happen, and who is active on the thread.
    affected_paths: List[str] = Field(default_factory=list, max_length=10)
    active_handles: List[str] = Field(default_factory=list, max_length=10)
    state: Literal["open", "closed"] = "open"
    assignee_count: int = Field(0, ge=0)
    comment_count: int = Field(0, ge=0)
    opened_date: str = Field("", max_length=10, description="ISO date the issue was opened.")
    # Only filled by the live check (verify): open pull requests that mention the issue, and people who said they are on it.
    linked_prs: List[str] = Field(default_factory=list, max_length=10)
    claimed_by: List[str] = Field(default_factory=list, max_length=10)

    @field_validator("status_metrics")
    @classmethod
    def _check_status_metrics(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        return validate_status_metrics(value)


class IssueCard(IssueSummary):
    """An issue summary plus its contribution checklist."""

    actionable_checklist: List[Dict[str, Any]] = Field(..., max_length=50)

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


class ChecklistResponse(BaseModel):
    """The steps for an issue, built without calling GitHub."""

    repo_full_name: str
    actionable_checklist: List[Dict[str, Any]]


class GuideResponse(BaseModel):
    """Rules quoted from a repository's CONTRIBUTING guide (empty when there is none or it could not be read)."""

    highlights: List[str] = Field(default_factory=list)
    source_url: str = ""


class FacetsResponse(BaseModel):
    """What the page needs to start: filter options, step count, and which integrations are on."""

    languages: List[str]
    topics: List[str]
    sorts: List[str]
    checklist_length: int
    github_authenticated: bool
    tinyfish_enabled: bool = False
    # True only when a developer is running Trailbit without a GitHub token; never shown to the public.
    show_token_hint: bool = False


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
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class BookmarkConfirmation(BaseModel):
    status: Literal["saved"] = "saved"
    created: bool
    bookmark: BookmarkOut


class BookmarkDeleted(BaseModel):
    status: Literal["deleted"] = "deleted"
    id: str
