"""Request/response models with camelCase JSON aliases.

Python stays snake_case internally; the wire contract matches exactly what the
frontend client (web/src/api/types.ts) expects.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class TruthEntryModel(_Camel):
    id: str
    kind: str
    value: str
    source: str


class EntriesResponse(_Camel):
    entries: list[TruthEntryModel]


class PutTruthRequest(_Camel):
    entries: list[TruthEntryModel]


class JobFetchRequest(_Camel):
    url: str


class JobFetchResponse(_Camel):
    text: str


class TailorRequest(_Camel):
    posting: str


class InferenceModel(_Camel):
    id: str
    claim: str
    rationale: str = ""


class TailorResult(_Camel):
    keywords: list[str]
    inferences: list[InferenceModel]


class ConfirmInferencesRequest(_Camel):
    approved_ids: list[str] = Field(default_factory=list)


class AtsWarning(_Camel):
    code: str
    message: str


class RenderResult(_Camel):
    blocked: bool
    unverifiable: list[str] = Field(default_factory=list)
    ats_warnings: list[AtsWarning] = Field(default_factory=list)
    pdf_url: str | None = None
    docx_url: str | None = None


class SettingsStatus(_Camel):
    encryption_available: bool
    active_provider: str
    model: str = ""
    anthropic_key_set: bool = False
    openai_key_set: bool = False
    ollama_host: str = ""


class SettingsUpdate(_Camel):
    active_provider: str
    api_key: str | None = None
    model: str | None = None
    ollama_host: str | None = None


class TestResult(_Camel):
    ok: bool
    detail: str = ""


class ProfileStatus(_Camel):
    has_profile: bool


class CoverLetterRequest(_Camel):
    tone: str = "Professional"
    length: str = "Standard"


class CoverLetterResult(_Camel):
    blocked: bool
    unverifiable: list[str] = Field(default_factory=list)
    pdf_url: str | None = None
    docx_url: str | None = None
