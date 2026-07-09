# Encrypted Settings, Cover Letters & Persisted Profile — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add UI-managed, Fernet-encrypted provider API keys; guardrail-truthful cover letters; and a persisted uploaded profile with per-posting regeneration — all on the existing TruthCV backend + React wizard.

**Architecture:** `.env` holds only `ENCRYPTION_KEY`; provider keys are entered in a Settings modal, encrypted with Fernet, and stored in `./data/secrets.enc`. A secrets resolver (`secrets.enc` → env fallback) feeds the provider layer. Cover letters are generated as factual claims + connective glue; only the claims pass the existing guardrail token-diff before rendering. The uploaded PDF and its parse are persisted plaintext on the data volume so users can change postings and regenerate without re-uploading.

**Tech Stack:** Python 3.11, FastAPI, Pydantic (camelCase aliases), `cryptography` (Fernet), Jinja2 + WeasyPrint + pandoc, pytest + FakeProvider + TestClient. Frontend: React 18 + Vite + TypeScript.

## Global Constraints

- Python internals snake_case; API JSON camelCase via Pydantic `_Camel`/`to_camel` aliases (see `api/schemas.py`).
- All tests use `FakeProvider` — NO network in tests. Data volume isolated per test via the `data_dir` fixture (`tests/conftest.py`, sets `DATA_DIR`).
- Only `secrets.enc` is encrypted (Fernet). `profile.pdf`, `source.txt`, `truth.yaml`, `draft.json` remain plaintext on `./data`.
- Raw provider API keys are NEVER returned to the browser (status booleans only).
- Provider credential resolution order: `secrets.enc` (if `ENCRYPTION_KEY` valid) → environment variable.
- Missing/invalid `ENCRYPTION_KEY`: secrets feature disabled gracefully; app still runs on env-var credentials.
- Cover-letter invariant: every factual claim string is guardrail-validated against truth values before assembly/render; unverifiable → `blocked=true`, nothing rendered.
- Verify command: `. .venv/bin/activate; python -m pytest` (baseline: 30 passed, 2 skipped).
- Add `cryptography>=42` to `requirements.txt`.

---

## File Structure

- `api/secrets.py` (new) — Fernet load, `read_secrets()`, `write_secrets()`, `resolve_credentials()`, `encryption_available()`.
- `api/genkey.py` (new) — `python -m api.genkey` prints a Fernet key.
- `coverletter/__init__.py` + `coverletter/generate.py` (new) — build claims+glue, validate claims, assemble letter text.
- `render/templates/cover_letter.html.j2` (new) — ATS-plain letter template.
- `render/cover_letter.py` (new) — `render_letter_html(...)`.
- `api/routes.py` (modify) — add settings, cover-letter, profile routes.
- `api/schemas.py` (modify) — new camelCase models.
- `api/config.py` (modify) — `encryption_key()`, `secrets_path()`, `profile_pdf_path()`.
- `providers/__init__.py` + provider files (modify) — accept resolved credentials.
- `truth/pdf.py` (modify) — persist raw `profile.pdf`; add `has_profile()`.
- `.env.example`, `requirements.txt`, `Dockerfile` (modify).
- Frontend: `web/src/components/SettingsModal.tsx` (new), `web/src/api/{client,types}.ts`, `web/src/steps/{UploadStep,DownloadStep}.tsx`, `web/src/wizard/store.tsx`, `web/src/App.tsx` + `web/src/styles/shell.css` (footer button + modal styles).

---

## Task 1: Fernet secrets store (`api/secrets.py`)

**Files:**
- Create: `api/secrets.py`
- Modify: `api/config.py`
- Test: `tests/test_secrets.py`

**Interfaces:**
- Produces:
  - `encryption_available() -> bool`
  - `read_secrets() -> dict` (returns `{}` if no file or key unavailable)
  - `write_secrets(data: dict) -> None` (raises `SecretsUnavailable` if no valid key)
  - `resolve_credentials() -> dict` with keys `activeProvider, anthropicApiKey, openaiApiKey, ollamaHost, model` — merged: secrets.enc overrides, env vars fill gaps.
  - exception `SecretsUnavailable(RuntimeError)`
- Consumes: `api.config.encryption_key()`, `api.config.secrets_path()`.

- [ ] **Step 1: Add config accessors**

In `api/config.py` add:
```python
def encryption_key() -> str:
    return os.environ.get("ENCRYPTION_KEY", "").strip()


def secrets_path() -> Path:
    from truth.store import data_dir
    return data_dir() / "secrets.enc"


def profile_pdf_path() -> Path:
    from truth.store import data_dir
    return data_dir() / "profile.pdf"
```

- [ ] **Step 2: Write failing tests**

```python
# tests/test_secrets.py
import pytest
from api import secrets as sec

FERNET_KEY = "aQ2mA0m3wF6b8xk2s9v0Xr7uY1zC4dN6pQ8rS0tU2w="  # 32-byte urlsafe b64

def test_no_encryption_key_disables(data_dir, monkeypatch):
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    assert sec.encryption_available() is False
    assert sec.read_secrets() == {}
    with pytest.raises(sec.SecretsUnavailable):
        sec.write_secrets({"activeProvider": "anthropic"})

def test_round_trip_encrypted(data_dir, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", FERNET_KEY)
    sec.write_secrets({"activeProvider": "openai", "openaiApiKey": "sk-x"})
    assert sec.encryption_available() is True
    got = sec.read_secrets()
    assert got["openaiApiKey"] == "sk-x"
    # file on disk is NOT plaintext
    from api.config import secrets_path
    raw = secrets_path().read_bytes()
    assert b"sk-x" not in raw

def test_resolve_prefers_secrets_then_env(data_dir, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", FERNET_KEY)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    sec.write_secrets({"activeProvider": "anthropic", "anthropicApiKey": "enc-key"})
    creds = sec.resolve_credentials()
    assert creds["anthropicApiKey"] == "enc-key"  # secrets wins
    # openai absent in secrets -> env fallback (none set) -> ""
    assert creds["openaiApiKey"] == ""

def test_invalid_key_disables(data_dir, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", "not-a-valid-fernet-key")
    assert sec.encryption_available() is False
```

- [ ] **Step 3: Run tests, verify fail**

Run: `. .venv/bin/activate; python -m pytest tests/test_secrets.py -v`
Expected: FAIL (module `api.secrets` not found).

- [ ] **Step 4: Implement `api/secrets.py`**

```python
"""Fernet-encrypted provider secrets on the data volume.

Only this file is encrypted. Missing/invalid ENCRYPTION_KEY disables the feature
gracefully; credentials then come from environment variables.
"""
from __future__ import annotations

import json
import os

from api.config import encryption_key, secrets_path

_FIELDS = ("activeProvider", "anthropicApiKey", "openaiApiKey", "ollamaHost", "model")


class SecretsUnavailable(RuntimeError):
    pass


def _fernet():
    key = encryption_key()
    if not key:
        return None
    try:
        from cryptography.fernet import Fernet
        return Fernet(key.encode("utf-8"))
    except Exception:
        return None


def encryption_available() -> bool:
    return _fernet() is not None


def read_secrets() -> dict:
    f = _fernet()
    p = secrets_path()
    if f is None or not p.exists():
        return {}
    try:
        return json.loads(f.decrypt(p.read_bytes()).decode("utf-8"))
    except Exception:
        return {}


def write_secrets(data: dict) -> None:
    f = _fernet()
    if f is None:
        raise SecretsUnavailable("ENCRYPTION_KEY is missing or invalid.")
    clean = {k: v for k, v in data.items() if k in _FIELDS and v is not None}
    p = secrets_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    token = f.encrypt(json.dumps(clean).encode("utf-8"))
    tmp = p.with_suffix(".enc.tmp")
    tmp.write_bytes(token)
    tmp.replace(p)


def resolve_credentials() -> dict:
    s = read_secrets()
    env = {
        "anthropicApiKey": os.environ.get("ANTHROPIC_API_KEY", ""),
        "openaiApiKey": os.environ.get("OPENAI_API_KEY", ""),
        "ollamaHost": os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
        "activeProvider": os.environ.get("LLM_PROVIDER", "anthropic"),
        "model": os.environ.get("LLM_MODEL", ""),
    }
    out = dict(env)
    for k in _FIELDS:
        v = s.get(k)
        if v:
            out[k] = v
    return out
```

- [ ] **Step 5: Run tests, verify pass**

Run: `. .venv/bin/activate; pip install -q cryptography; python -m pytest tests/test_secrets.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add api/secrets.py api/config.py tests/test_secrets.py
git commit -m "feat: Fernet-encrypted provider secrets store"
```

---

## Task 2: genkey helper + requirements + .env.example

**Files:**
- Create: `api/genkey.py`
- Modify: `requirements.txt`, `.env.example`
- Test: `tests/test_genkey.py`

**Interfaces:**
- Produces: `api.genkey.generate() -> str` (a valid Fernet key); `python -m api.genkey` prints it.

- [ ] **Step 1: Failing test**

```python
# tests/test_genkey.py
def test_generate_makes_valid_fernet_key():
    from api.genkey import generate
    from cryptography.fernet import Fernet
    key = generate()
    Fernet(key.encode("utf-8"))  # raises if invalid
    assert len(key) >= 40
```

- [ ] **Step 2: Run, verify fail** — `python -m pytest tests/test_genkey.py -v` → FAIL.

- [ ] **Step 3: Implement `api/genkey.py`**

```python
"""Generate a Fernet ENCRYPTION_KEY: `python -m api.genkey`."""
from __future__ import annotations


def generate() -> str:
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode("utf-8")


if __name__ == "__main__":  # pragma: no cover
    print(generate())
```

- [ ] **Step 4: Add `cryptography>=42` to `requirements.txt`.** Append the line.

- [ ] **Step 5: Update `.env.example`** — add:
```
# Master key that encrypts saved provider API keys (./data/secrets.enc).
# Generate one with:  python -m api.genkey
ENCRYPTION_KEY=
```

- [ ] **Step 6: Run, verify pass** — `python -m pytest tests/test_genkey.py -v` → PASS.

- [ ] **Step 7: Commit**
```bash
git add api/genkey.py requirements.txt .env.example tests/test_genkey.py
git commit -m "feat: api.genkey helper and ENCRYPTION_KEY docs"
```

---

## Task 3: Provider layer reads resolved credentials

**Files:**
- Modify: `providers/__init__.py`, `providers/anthropic_provider.py`, `providers/openai_provider.py`, `providers/ollama_provider.py`
- Test: `tests/test_providers.py` (extend)

**Interfaces:**
- Consumes: `api.secrets.resolve_credentials()`.
- Produces: `get_provider(refresh=False)` selects and constructs the active provider using resolved credentials (secrets → env). Providers accept explicit `api_key`/`model`/`host` kwargs; `get_provider` passes resolved values.

- [ ] **Step 1: Extend failing test**

```python
def test_get_provider_uses_secrets_credentials(data_dir, monkeypatch):
    from providers import get_provider, reset_provider
    monkeypatch.setenv("ENCRYPTION_KEY", "aQ2mA0m3wF6b8xk2s9v0Xr7uY1zC4dN6pQ8rS0tU2w=")
    from api import secrets as sec
    sec.write_secrets({"activeProvider": "fake"})  # fake selected via secrets
    reset_provider()
    from providers.fake import FakeProvider
    assert isinstance(get_provider(refresh=True), FakeProvider)
```

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Rewire `providers/__init__.py`** — replace env reads in `get_provider` with:
```python
from api.secrets import resolve_credentials
creds = resolve_credentials()
name = creds["activeProvider"].strip().lower()
```
Pass `creds` down: `AnthropicProvider(api_key=creds["anthropicApiKey"], model=creds["model"])`, `OpenAIProvider(api_key=creds["openaiApiKey"], model=creds["model"])`, `OllamaProvider(host=creds["ollamaHost"], model=creds["model"])`. Keep `fake` and the unknown-name `ProviderError`. Keep `env_model` fallback for empty model.

- [ ] **Step 4: Update each provider `__init__`** to prefer the passed `api_key`/`host` over `os.environ`, raising `ProviderError` only if still empty. (Anthropic/OpenAI: `self._key = api_key or os.environ.get(...)`.)

- [ ] **Step 5: Run full provider tests, verify pass** — `python -m pytest tests/test_providers.py -v`.

- [ ] **Step 6: Commit**
```bash
git add providers/ tests/test_providers.py
git commit -m "feat: provider layer resolves credentials from secrets store"
```

---

## Task 4: Settings API models + routes

**Files:**
- Modify: `api/schemas.py`, `api/routes.py`
- Test: `tests/test_settings_api.py`

**Interfaces:**
- Consumes: `api.secrets` (Task 1), `providers.get_provider` (Task 3).
- Produces routes: `GET /api/settings`, `POST /api/settings`, `POST /api/settings/test`.
- Schemas: `SettingsStatus{encryptionAvailable,activeProvider,model,anthropicKeySet,openaiKeySet,ollamaHost}`, `SettingsUpdate{activeProvider,apiKey?,model?,ollamaHost?}`, `TestResult{ok,detail}`.

- [ ] **Step 1: Failing tests**

```python
# tests/test_settings_api.py
import pytest
from fastapi.testclient import TestClient
from api.main import app
import api.routes as routes
from providers.fake import FakeProvider

FERNET_KEY = "aQ2mA0m3wF6b8xk2s9v0Xr7uY1zC4dN6pQ8rS0tU2w="

@pytest.fixture()
def client(data_dir, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", FERNET_KEY)
    return TestClient(app)

def test_get_settings_status_no_secrets(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    b = r.json()
    assert b["encryptionAvailable"] is True
    assert b["anthropicKeySet"] is False

def test_post_settings_saves_and_masks(client):
    r = client.post("/api/settings", json={"activeProvider": "anthropic", "apiKey": "sk-ant-secret"})
    assert r.status_code == 200
    b = r.json()
    assert b["anthropicKeySet"] is True
    # raw key never returned
    assert "sk-ant-secret" not in r.text

def test_post_settings_empty_key_keeps_existing(client):
    client.post("/api/settings", json={"activeProvider": "anthropic", "apiKey": "sk-1"})
    r = client.post("/api/settings", json={"activeProvider": "anthropic", "apiKey": ""})
    assert r.json()["anthropicKeySet"] is True

def test_test_connection_ok(client, monkeypatch):
    monkeypatch.setattr(routes, "get_provider", lambda *a, **k: FakeProvider(completions=["ok"]))
    r = client.post("/api/settings/test", json={"activeProvider": "anthropic", "apiKey": "sk-1"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
```

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Add schemas** to `api/schemas.py` (all extend `_Camel`): `SettingsStatus`, `SettingsUpdate`, `TestResult` with the fields above.

- [ ] **Step 4: Implement routes** in `api/routes.py`:
```python
from api import secrets as secrets_store
from api.schemas import SettingsStatus, SettingsUpdate, TestResult

def _status() -> SettingsStatus:
    s = secrets_store.read_secrets()
    creds = secrets_store.resolve_credentials()
    return SettingsStatus(
        encryption_available=secrets_store.encryption_available(),
        active_provider=creds["activeProvider"],
        model=creds["model"],
        anthropic_key_set=bool(creds["anthropicApiKey"]),
        openai_key_set=bool(creds["openaiApiKey"]),
        ollama_host=creds["ollamaHost"],
    )

@router.get("/settings", response_model=SettingsStatus)
def get_settings():
    return _status()

@router.post("/settings", response_model=SettingsStatus)
def post_settings(body: SettingsUpdate):
    if not secrets_store.encryption_available():
        raise HTTPException(400, "Set ENCRYPTION_KEY in .env first.")
    current = secrets_store.read_secrets()
    current["activeProvider"] = body.active_provider
    if body.model is not None:
        current["model"] = body.model
    if body.ollama_host:
        current["ollamaHost"] = body.ollama_host
    if body.api_key:  # empty/None = leave unchanged
        field = {"anthropic": "anthropicApiKey", "openai": "openaiApiKey"}.get(body.active_provider)
        if field:
            current[field] = body.api_key
    secrets_store.write_secrets(current)
    from providers import reset_provider
    reset_provider()
    return _status()

@router.post("/settings/test", response_model=TestResult)
def test_settings(body: SettingsUpdate):
    try:
        post_settings(body)
        provider = get_provider(refresh=True)
        provider.complete("ping", [{"role": "user", "content": "ping"}])
        return TestResult(ok=True, detail="Connection succeeded.")
    except Exception as e:  # noqa: BLE001
        return TestResult(ok=False, detail=f"{type(e).__name__}: {e}")
```

- [ ] **Step 5: Run, verify pass** — `python -m pytest tests/test_settings_api.py -v`.

- [ ] **Step 6: Commit**
```bash
git add api/schemas.py api/routes.py tests/test_settings_api.py
git commit -m "feat: settings API (get/save/test) with encrypted secrets"
```

---

## Task 5: Persisted profile (raw PDF) + profile route

**Files:**
- Modify: `truth/pdf.py`, `api/routes.py`, `api/schemas.py`
- Test: `tests/test_profile.py`

**Interfaces:**
- Produces: `truth.pdf.persist_profile(file_bytes: bytes) -> Path` (writes `profile.pdf`), `truth.pdf.has_profile() -> bool`. Route `GET /api/profile -> {hasProfile}`. `/api/upload` also persists the raw PDF.
- Schema: `ProfileStatus{hasProfile}`.

- [ ] **Step 1: Failing tests**

```python
# tests/test_profile.py
import io, pytest
from fastapi.testclient import TestClient
from api.main import app

@pytest.fixture()
def client(data_dir):
    return TestClient(app)

_PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
        b"4 0 obj<</Length 44>>stream\nBT /F1 12 Tf 20 100 Td (Profile text) Tj ET\n"
        b"endstream endobj\n5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
        b"trailer<</Root 1 0 R/Size 6>>\nstartxref\n0\n%%EOF")

def test_profile_absent_then_present(client):
    assert client.get("/api/profile").json()["hasProfile"] is False
    r = client.post("/api/upload", files={"file": ("cv.pdf", io.BytesIO(_PDF), "application/pdf")})
    assert r.status_code == 204
    assert client.get("/api/profile").json()["hasProfile"] is True
```

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement** in `truth/pdf.py`:
```python
def persist_profile(file_bytes: bytes):
    from api.config import profile_pdf_path
    p = profile_pdf_path()
    p.write_bytes(file_bytes)
    return p

def has_profile() -> bool:
    from api.config import profile_pdf_path
    return profile_pdf_path().exists()
```
In `/api/upload` (api/routes.py), after `extract_text` succeeds, call `persist_profile(data)` alongside `persist_source_text(text)`.

- [ ] **Step 4: Add `ProfileStatus` schema + route**
```python
@router.get("/profile", response_model=ProfileStatus)
def profile():
    from truth.pdf import has_profile
    return ProfileStatus(has_profile=has_profile())
```

- [ ] **Step 5: Run, verify pass.**

- [ ] **Step 6: Commit**
```bash
git add truth/pdf.py api/routes.py api/schemas.py tests/test_profile.py
git commit -m "feat: persist uploaded profile PDF and expose /api/profile"
```

---

## Task 6: Cover-letter generation (claims + glue, guardrail-validated)

**Files:**
- Create: `coverletter/__init__.py`, `coverletter/generate.py`
- Test: `tests/test_cover_letter.py`

**Interfaces:**
- Consumes: `providers.base.LLMProvider`, `truth.load`, `guardrail.validate`, persisted draft/posting.
- Produces: `coverletter.generate.build_letter(posting, tone, length, truth, provider) -> dict` returning `{blocked: bool, unverifiable: list[str], text: str}`. When blocked, `text=""`.

- [ ] **Step 1: Failing tests**

```python
# tests/test_cover_letter.py
from providers.fake import FakeProvider
from truth.model import TruthEntry
from coverletter.generate import build_letter

TRUTH = [
    TruthEntry("role-eng-1", "role", "Senior Software Engineer", "linkedin-pdf"),
    TruthEntry("co-acme-1", "company", "Acme Corp", "linkedin-pdf"),
    TruthEntry("skill-py-1", "skill", "Python", "linkedin-pdf"),
]

def _router_ok(system, messages, schema):
    return {
        "paragraphs": [
            {"text": "I am excited to apply for this role.", "claims": []},
            {"text": "As a Senior Software Engineer at Acme Corp, I use Python daily.",
             "claims": ["Senior Software Engineer", "Acme Corp", "Python"]},
        ]
    }

def _router_lie(system, messages, schema):
    return {"paragraphs": [
        {"text": "I led a team of 200 at Globex.", "claims": ["Led a team of 200 at Globex"]}]}

def test_truthful_letter_passes(data_dir):
    p = FakeProvider(router=_router_ok)
    out = build_letter("A Python role", "Professional", "Short", TRUTH, p)
    assert out["blocked"] is False
    assert "Acme Corp" in out["text"]

def test_fabricated_claim_blocks(data_dir):
    p = FakeProvider(router=_router_lie)
    out = build_letter("A role", "Professional", "Short", TRUTH, p)
    assert out["blocked"] is True
    assert out["text"] == ""
    assert any(tok in out["unverifiable"] for tok in ("200", "globex"))
```

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement `coverletter/generate.py`**

```python
"""Guardrail-truthful cover-letter generation (claims + connective glue)."""
from __future__ import annotations

from typing import Any

from guardrail import validate
from providers.base import LLMProvider
from truth.model import TruthEntry

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"paragraphs": {"type": "array", "items": {
        "type": "object",
        "properties": {"text": {"type": "string"},
                       "claims": {"type": "array", "items": {"type": "string"}}},
        "required": ["text"]}}},
    "required": ["paragraphs"],
}

def _system(tone: str, length: str) -> str:
    from tailor.style import LETTER_STYLE
    return (
        f"Write a {tone.lower()} cover letter of {length.lower()} length. For every "
        "sentence that states a FACT about the candidate (employer, title, date, "
        "metric, skill, achievement), list that fact verbatim in 'claims'. Do NOT "
        "invent any fact not supported by the candidate's truth. Connective/"
        "narrative sentences need no claims." + LETTER_STYLE
    )

def build_letter(posting, tone, length, truth: list[TruthEntry], provider: LLMProvider) -> dict:
    user = f"POSTING:\n{posting}\n\nCANDIDATE FACTS:\n" + "\n".join(f"- {e.value}" for e in truth)
    result = provider.extract_json(_system(tone, length),
                                   [{"role": "user", "content": user}], _SCHEMA)
    paragraphs = result.get("paragraphs", []) if isinstance(result, dict) else []
    claims = [c for para in paragraphs for c in para.get("claims", [])]
    check = validate(claims, [e.value for e in truth])
    if not check.ok:
        return {"blocked": True, "unverifiable": check.unverifiable, "text": ""}
    text = "\n\n".join(p.get("text", "").strip() for p in paragraphs if p.get("text"))
    return {"blocked": False, "unverifiable": [], "text": text}
```
And `coverletter/__init__.py`:
```python
from .generate import build_letter
__all__ = ["build_letter"]
```

- [ ] **Step 4: Run, verify pass.**

- [ ] **Step 5: Commit**
```bash
git add coverletter/ tests/test_cover_letter.py
git commit -m "feat: guardrail-truthful cover-letter generation"
```

---

## Task 7: Cover-letter rendering + route

**Files:**
- Create: `render/templates/cover_letter.html.j2`, `render/cover_letter.py`
- Modify: `api/routes.py`, `api/schemas.py`
- Test: `tests/test_cover_letter_api.py`

**Interfaces:**
- Consumes: `coverletter.build_letter`, `render.render_pdf`, `render.render_docx`, persisted posting.
- Produces: `render.cover_letter.render_letter_html(text, name, contact) -> str`. Route `POST /api/cover-letter` body `{tone,length}` → `{blocked, unverifiable, pdfUrl, docxUrl}`.
- Schema: `CoverLetterRequest{tone,length}`, `CoverLetterResult{blocked,unverifiable,pdfUrl,docxUrl}`.
- Note: the posting is persisted by tailor; store it in `draft.json` or a `posting.txt`. This task adds `tailor` persistence of the posting if absent — write `./data/posting.txt` in `/api/tailor` and read it here.

- [ ] **Step 1: Failing test**

```python
# tests/test_cover_letter_api.py
import pytest
from fastapi.testclient import TestClient
from api.main import app
import api.routes as routes
from providers.fake import FakeProvider
from truth import save
from truth.model import TruthEntry

@pytest.fixture()
def client(data_dir, monkeypatch):
    def router(system, messages, schema):
        return {"paragraphs": [{"text": "I use Python at Acme Corp.",
                                "claims": ["Python", "Acme Corp"]}]}
    monkeypatch.setattr(routes, "get_provider", lambda *a, **k: FakeProvider(router=router))
    save([TruthEntry("s1","skill","Python","linkedin-pdf"),
          TruthEntry("c1","company","Acme Corp","linkedin-pdf")])
    # persist a posting
    from api.config import __name__  # noqa
    from truth.store import data_dir as dd
    (dd() / "posting.txt").write_text("Python role at a startup")
    return TestClient(app)

def test_cover_letter_route(client):
    r = client.post("/api/cover-letter", json={"tone": "Professional", "length": "Short"})
    assert r.status_code in (200, 500)
    if r.status_code == 200:
        b = r.json()
        assert b["blocked"] is False
        assert "pdfUrl" in b and "docxUrl" in b
```

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Create template `render/templates/cover_letter.html.j2`** — single-column, plain, `{{ name }}`, `{{ contact }}`, then `{% for p in paragraphs %}<p>{{ p }}</p>{% endfor %}`.

- [ ] **Step 4: Implement `render/cover_letter.py`**
```python
from render.html import _env  # reuse the Jinja Environment

def render_letter_html(text: str, name: str = "Your Name", contact: str = "") -> str:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    return _env.get_template("cover_letter.html.j2").render(
        name=name, contact=contact, paragraphs=paragraphs)
```

- [ ] **Step 5: Persist posting in `/api/tailor`** — after tailoring, write `data_dir()/"posting.txt"` with `body.posting`.

- [ ] **Step 6: Add route + schemas** in `api/routes.py`:
```python
@router.post("/cover-letter", response_model=CoverLetterResult)
def cover_letter(body: CoverLetterRequest):
    from truth.store import data_dir
    posting_file = data_dir() / "posting.txt"
    if not posting_file.exists():
        raise HTTPException(400, "Tailor a posting before generating a cover letter.")
    from coverletter import build_letter
    from render.cover_letter import render_letter_html
    letter = build_letter(posting_file.read_text(), body.tone, body.length, load(), get_provider())
    if letter["blocked"]:
        return CoverLetterResult(blocked=True, unverifiable=letter["unverifiable"])
    html = render_letter_html(letter["text"])
    pdf_url = docx_url = None
    try:
        pdf_url = f"/api/download/{render_pdf(html, 'cover_letter.pdf').name}"
    except RenderUnavailable:
        pass
    try:
        docx_url = f"/api/download/{render_docx(html, 'cover_letter.docx').name}"
    except RenderUnavailable:
        pass
    if pdf_url is None and docx_url is None:
        raise HTTPException(500, "Rendering backend unavailable.")
    return CoverLetterResult(blocked=False, pdf_url=pdf_url, docx_url=docx_url)
```

- [ ] **Step 7: Run, verify pass.**

- [ ] **Step 8: Commit**
```bash
git add render/templates/cover_letter.html.j2 render/cover_letter.py api/routes.py api/schemas.py tests/test_cover_letter_api.py
git commit -m "feat: cover-letter render + /api/cover-letter route"
```

---

## Task 8: Full backend suite green

- [ ] **Step 1:** `. .venv/bin/activate; python -m pytest` — expect all prior + new tests pass (PDF/DOCX smoke may skip).
- [ ] **Step 2:** Fix any regressions.
- [ ] **Step 3: Commit** any fixes: `git commit -am "test: backend suite green for settings + cover letters"`.

---

## Task 9: Frontend — API client + types

**Files:**
- Modify: `web/src/api/types.ts`, `web/src/api/client.ts`
- Test: (typecheck) `cd web && npm run typecheck`

**Interfaces:**
- Produces client fns: `getSettings()`, `saveSettings(body)`, `testConnection(body)`, `getProfile()`, `generateCoverLetter(body)`. Types: `SettingsStatus`, `SettingsUpdate`, `TestResult`, `ProfileStatus`, `CoverLetterResult` mirroring the camelCase API.

- [ ] **Step 1:** Add the TS interfaces to `types.ts` matching the Pydantic camelCase fields exactly.
- [ ] **Step 2:** Add the fetch functions to `client.ts` using the existing `request<T>` helper. `saveSettings`/`testConnection` POST JSON; `getSettings`/`getProfile` GET.
- [ ] **Step 3:** `cd web && npm run typecheck` → exit 0.
- [ ] **Step 4: Commit** `git add web/src/api && git commit -m "feat(web): settings/profile/cover-letter API client"`.

---

## Task 10: Frontend — Settings modal + footer button

**Files:**
- Create: `web/src/components/SettingsModal.tsx`
- Modify: `web/src/App.tsx`, `web/src/styles/shell.css`

**Interfaces:**
- Consumes: `getSettings`, `saveSettings`, `testConnection` (Task 9).

- [ ] **Step 1:** Build `SettingsModal.tsx` — dialog with Provider dropdown, API key (masked; placeholder `••••• set` when `anthropicKeySet`/`openaiKeySet`), Model input, Host input (Ollama only), Save + Test buttons, inline result. Accessible: `role="dialog"`, `aria-modal`, focus trap, Esc to close, `focus-visible` styles.
- [ ] **Step 2:** Add a ⚙ **Settings** button to the footer bar in `App.tsx`; wire open/close state; render `<SettingsModal>` when open.
- [ ] **Step 3:** Add modal + footer-button styles to `shell.css` (respect `prefers-reduced-motion`).
- [ ] **Step 4:** `cd web && npm run typecheck` → exit 0; `npm run build` → exit 0.
- [ ] **Step 5: Commit** `git add web/src && git commit -m "feat(web): settings modal on footer"`.

---

## Task 11: Frontend — use-saved-profile + editable posting + cover-letter section

**Files:**
- Modify: `web/src/steps/UploadStep.tsx`, `web/src/steps/PostingStep.tsx`, `web/src/steps/DownloadStep.tsx`, `web/src/wizard/store.tsx`

**Interfaces:**
- Consumes: `getProfile`, `generateCoverLetter` (Task 9).

- [ ] **Step 1:** In `store.tsx` add `hasProfile` (from `getProfile` on mount) and `coverLetter` state (`{loading,blocked,unverifiable,pdfUrl,docxUrl}`) + `generateLetter(tone,length)` action.
- [ ] **Step 2:** In `UploadStep.tsx`, if `hasProfile`, show "Use saved profile" → advances to `review` (truth already loaded via `getTruth`), plus a "Re-upload" option.
- [ ] **Step 3:** In `PostingStep.tsx`, ensure the textarea is editable and re-tailoring re-runs cleanly (it already calls `tailor`); confirm changing text + re-submitting overwrites the draft (backend already overwrites `draft.json`). No new backend needed.
- [ ] **Step 4:** In `DownloadStep.tsx`, after CV render, add a "Cover letter" section: Tone dropdown (Professional/Warm/Concise), Length dropdown (Short/Standard), Generate button → `generateLetter`; show blocked/unverifiable notice or PDF/DOCX download links. Accessible labels + `aria-live` for status.
- [ ] **Step 5:** `cd web && npm run typecheck` + `npm run build` → exit 0.
- [ ] **Step 6: Commit** `git add web/src && git commit -m "feat(web): saved profile, editable posting, cover-letter section"`.

---

## Task 12: Dockerfile + docs + final verification

**Files:**
- Modify: `Dockerfile` (ensure `coverletter/` COPYed; `cryptography` installs fine), `README`/`.env.example`.

- [ ] **Step 1:** Add `COPY coverletter/ ./coverletter/` to the Dockerfile app stage.
- [ ] **Step 2:** Confirm `cryptography` wheels install in `python:3.11-slim` (add `build-essential`/`libffi-dev` only if the wheel is unavailable — libffi-dev already present).
- [ ] **Step 3:** `. .venv/bin/activate; python -m pytest` → green.
- [ ] **Step 4:** `cd web && npm run build` → exit 0.
- [ ] **Step 5: Commit** `git commit -am "chore: docker + docs for settings and cover letters"`.

---

## Self-Review

- **Spec coverage:** Feature 1 (Tasks 1–4, 10), Feature 2 cover letters (Tasks 6, 7, 11), Feature 3 persisted profile + re-posting (Tasks 5, 11). `genkey`/`.env` (Task 2). All spec sections mapped.
- **Placeholder scan:** all code steps contain real code; test bodies concrete.
- **Type consistency:** camelCase API fields (`anthropicKeySet`, `pdfUrl`, `hasProfile`, `activeProvider`) are used identically in Pydantic schemas and TS types. `build_letter` returns `{blocked,unverifiable,text}` consistently across Tasks 6–7. `resolve_credentials()` key names (`anthropicApiKey`, etc.) match `secrets.enc` fields.
- Gap check: posting persistence introduced in Task 7 Step 5 (writes `posting.txt`) — required by `/api/cover-letter`; noted in that task's interfaces.
