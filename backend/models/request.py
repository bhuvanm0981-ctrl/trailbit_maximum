"""Request schemas (Pydantic v2)."""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..utils import parse_github_url

ISSUE_URL_HINT = "Expected an issue URL: https://github.com/<owner>/<repo>/issues/<number>"


class ResearchRequest(BaseModel):
    """Body for endpoints that research a single GitHub issue."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    github_url: str = Field(
        ...,
        min_length=1,
        max_length=300,
        description="https://github.com/<owner>/<repo>/issues/<number>",
        examples=["https://github.com/octocat/Hello-World/issues/1"],
    )

    @field_validator("github_url")
    @classmethod
    def _must_be_issue_url(cls, value: str) -> str:
        try:
            _, _, number = parse_github_url(value)
        except ValueError as exc:
            raise ValueError(ISSUE_URL_HINT) from exc
        if number is None:
            raise ValueError(ISSUE_URL_HINT)
        return value
