"""Pydantic contract for POST /api/v1/ai/triage (api-contract-spec Revision 2, section 7).

Invariants (validated here, not left to the model):
- all six Draft keys always exist; unknown values are null;
- missing_fields and clarification_fields are disjoint;
- their union equals the set of unresolved fields among kind/key/sev.

"Unresolved" means null, plus kind == "other": AI-spec section 4 row 8 requires
kind "other" together with clarification_fields ["kind"], so "other" is a placeholder
for "not catalogued" rather than a resolved value (see docs/OPEN-QUESTIONS.md, Q2).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TEXT_MAX_CHARS = 2000
HISTORY_MAX_MESSAGES = 19

Kind = Literal["thermal-zone", "thermal-rack", "cpu", "psu", "other"]
Sev = Literal["crit", "warn"]
Runbook = Literal["rb-crac", "rb-cpu", "rb-psu", "rb-airflow"]

DRAFT_KEYS = ("kind", "key", "sev", "summary", "probable_cause", "runbook")
RESOLVABLE_FIELDS = ("kind", "key", "sev")


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Kind | None = None
    key: str | None = None
    sev: Sev | None = None
    summary: str | None = None
    probable_cause: str | None = None
    runbook: Runbook | None = None

    def unresolved_fields(self) -> set[str]:
        """Fields among kind/key/sev the operator still has to settle."""
        out = {f for f in RESOLVABLE_FIELDS if getattr(self, f) is None}
        if self.kind == "other":
            out.add("kind")
        return out


class HistoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str


class TriageContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hall: str
    now: str = Field(description="ISO-8601 timestamp, trailing Z")


class TriageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=TEXT_MAX_CHARS)
    draft: Draft | None = None
    history: list[HistoryMessage] = Field(default_factory=list, max_length=HISTORY_MAX_MESSAGES)
    context: TriageContext


def check_lists(draft: Draft, missing: list[str], clarification: list[str]) -> None:
    """Raise ValueError when the two lists do not account for every unresolved field exactly once."""
    allowed = set(RESOLVABLE_FIELDS)
    for name, lst in (("missing_fields", missing), ("clarification_fields", clarification)):
        if len(set(lst)) != len(lst):
            raise ValueError(f"{name} contains duplicates")
        unknown = set(lst) - allowed
        if unknown:
            raise ValueError(f"{name} names fields outside kind/key/sev: {sorted(unknown)}")
    both = set(missing) & set(clarification)
    if both:
        raise ValueError(f"fields in both lists: {sorted(both)}")
    union = set(missing) | set(clarification)
    unresolved = draft.unresolved_fields()
    if union != unresolved:
        raise ValueError(
            f"missing_fields ∪ clarification_fields = {sorted(union)} "
            f"but unresolved fields = {sorted(unresolved)}"
        )


class TriageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft: Draft
    missing_fields: list[str] = Field(default_factory=list)
    clarification_fields: list[str] = Field(default_factory=list)
    reply: str = Field(min_length=1)
    request_id: str
    model: str

    @model_validator(mode="after")
    def _invariants(self) -> TriageResponse:
        check_lists(self.draft, self.missing_fields, self.clarification_fields)
        return self
