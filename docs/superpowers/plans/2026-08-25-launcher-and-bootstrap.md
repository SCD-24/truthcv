# Launcher and Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A colleague double-clicks one file and TruthCV starts, with `ENCRYPTION_KEY`, `AGENT_API_TOKEN` and host ports generated automatically and no terminal involved.

**Architecture:** Per-OS launcher shims contain no logic; they run a single Python bootstrap inside a `python:3-alpine` container (the one interpreter guaranteed present, since Docker is already required), then `docker compose up -d`, retrying with a bumped port if Docker refuses to bind. Bootstrap only ever creates `.env`, fills a blank assignment in place, or appends an absent key — a line carrying a value is never touched.

**Tech Stack:** Python 3 standard library only (no packages — the bootstrap image installs nothing), pytest, Docker Compose, bash/batch.

**Spec:** `docs/superpowers/specs/2026-08-25-nontechnical-distribution-design.md`

## Global Constraints

- Bootstrap must be **standard library only**. `python:3-alpine` has no packages installed and none may be added.
- **Never modify a `.env` line that carries a value**, except `set_value` on a port variable the launcher owns, and only after Docker has refused it.
- **Always back up** an existing `.env` before any write. Backups are never deleted.
- Container-internal ports stay at **8080** (app) and **7900** (noVNC) permanently. Only the host side of a compose mapping changes.
- Host-side variables are named **`APP_PORT`** and **`NOVNC_HOST_PORT`** — never `PORT` or `NOVNC_PORT`, which `Dockerfile:52` and `browser/entrypoint.sh:20` already use for container-internal ports.
- Default host ports: **`APP_PORT=5627`**, **`NOVNC_HOST_PORT=5628`**.
- Bootstrap writes human messages to **stderr** and exactly one machine-readable `KEY=value` line to **stdout**, so shims can read the port without parsing prose.

## File Structure

| File | Responsibility |
|---|---|
| `launcher/__init__.py` | Package marker. Empty. |
| `launcher/envfile.py` | Parsing, secret generation, backup, and the three permitted `.env` writes. |
| `launcher/ports.py` | Default host ports and next-candidate selection. Pure functions, no I/O. |
| `launcher/__main__.py` | CLI: normal run and `--bump`. Orchestration and reporting only. |
| `tests/test_launcher_envfile.py` | The `.env` safety rules. |
| `tests/test_launcher_ports.py` | Candidate selection. |
| `tests/test_launcher_main.py` | CLI behaviour end to end on a temp repo. |
| `docker-compose.yml` | Host-side port mappings become variables. |
| `scripts/launch/truthcv.sh` | Shared shell shim used by macOS and Linux. |
| `scripts/launch/truthcv.command` | macOS double-click entry; delegates to `truthcv.sh`. |
| `scripts/launch/truthcv.desktop` | Linux desktop entry; delegates to `truthcv.sh`. |
| `scripts/launch/truthcv.bat` | Windows double-click entry. |
| `scripts/release.sh` | Builds the distributable zip with `git archive` and asserts its contents. |
| `tests/test_release_script.py` | Proves the zip excludes secrets and personal data. |
| `SETUP.md` | Non-technical setup guide. |

`launcher/` is a top-level package like `api/`, `truth/` and `screening/`, matching the repo's existing layout, so tests import it directly with no path manipulation.

---

### Task 1: Host-side port variables in compose

**Files:**
- Modify: `docker-compose.yml:5`, `docker-compose.yml:47`

**Interfaces:**
- Consumes: nothing
- Produces: `APP_PORT` and `NOVNC_HOST_PORT` as the host-side compose variables, defaulting to 5627 and 5628

- [ ] **Step 1: Record the current published ports**

Run: `docker compose config | grep -A3 'published'`
Expected: shows `published: "8080"` and `published: "7900"`. Save this output — Step 5 compares against it.

- [ ] **Step 2: Change the app service's host port**

In `docker-compose.yml`, replace line 5:

```yaml
      - "8080:8080"
```

with:

```yaml
      # Host side only. The container keeps listening on 8080 (Dockerfile
      # `ENV PORT=8080`), which is what the agent reaches over the compose
      # network as http://app:8080/mcp — changing the left side cannot affect
      # it. Named APP_PORT, not PORT: PORT is the container-internal variable.
      - "${APP_PORT:-5627}:8080"
```

- [ ] **Step 3: Change the browser service's host port**

In `docker-compose.yml`, replace line 47:

```yaml
      - "7900:7900"
```

with:

```yaml
      # Host side only. NOVNC_HOST_PORT, deliberately NOT NOVNC_PORT —
      # browser/entrypoint.sh:20 already reads NOVNC_PORT for the port inside
      # the container, and reusing the name would move the internal port and
      # leave this mapping pointing at nothing.
      - "${NOVNC_HOST_PORT:-5628}:7900"
```

- [ ] **Step 4: Verify the defaults render**

Run: `env -u APP_PORT -u NOVNC_HOST_PORT docker compose config | grep -B2 -A3 published`
Expected: `published: "5627"` targeting `8080`, and `published: "5628"` targeting `7900`.

- [ ] **Step 5: Verify nothing container-internal moved**

Run: `docker compose config | grep -E 'TRUTHCV_MCP_URL|BROWSER_MCP_URL|target:'`
Expected: `TRUTHCV_MCP_URL` is still `http://app:8080/mcp`, `BROWSER_MCP_URL` still `http://browser:8931/mcp`, and the mapping targets are still `8080` and `7900`. If any of these changed, the edit touched the wrong side of a mapping — revert and redo.

- [ ] **Step 6: Verify an override still works**

Run: `APP_PORT=9999 docker compose config | grep -A3 published`
Expected: `published: "9999"` targeting `8080`.

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml
git commit -m "Parameterise the host side of the compose port mappings

Default host ports become 5627 (app) and 5628 (noVNC). Only the left
side of each mapping changes; the containers keep listening on 8080 and
7900, so the agent's in-network path to http://app:8080/mcp is
untouched.

Named APP_PORT and NOVNC_HOST_PORT rather than PORT and NOVNC_PORT,
which Dockerfile:52 and browser/entrypoint.sh:20 already use for the
container-internal ports."
```

---

### Task 2: `.env` reading and safe writing

**Files:**
- Create: `launcher/__init__.py`, `launcher/envfile.py`
- Test: `tests/test_launcher_envfile.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `parse(text: str) -> dict[str, str]`
  - `generate_encryption_key() -> str`
  - `generate_agent_token() -> str`
  - `backup(path: Path) -> Path`
  - `EnsureResult` dataclass with fields `created: bool`, `filled: list[str]`, `appended: list[str]`, `backup_path: Path | None`, `values: dict[str, str]`
  - `ensure(env_path: Path, example_path: Path, required: dict[str, str]) -> EnsureResult`
  - `set_value(env_path: Path, key: str, value: str) -> Path`
  - `MANAGED_HEADER: str`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_launcher_envfile.py`:

```python
"""The .env safety rules.

These are the tests that matter most in this plan: a bug here destroys a
real configuration file that the user cannot reconstruct.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from launcher import envfile

EXAMPLE = """# Which provider
LLM_PROVIDER=anthropic

# Master key
ENCRYPTION_KEY=

# Shared secret
AGENT_API_TOKEN=
"""


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / ".env.example").write_text(EXAMPLE, encoding="utf-8")
    return tmp_path


def test_parse_skips_comments_and_blanks():
    parsed = envfile.parse("# note\n\nA=1\nB = 2\nnot-a-pair\n")
    assert parsed == {"A": "1", "B": "2"}


def test_generated_encryption_key_is_a_valid_fernet_key():
    from cryptography.fernet import Fernet

    Fernet(envfile.generate_encryption_key().encode())


def test_generated_agent_token_is_64_hex_chars():
    token = envfile.generate_agent_token()
    assert len(token) == 64
    int(token, 16)


def test_creates_env_from_example_when_absent(repo: Path):
    result = envfile.ensure(
        repo / ".env", repo / ".env.example", {"ENCRYPTION_KEY": "k", "AGENT_API_TOKEN": "t"}
    )
    assert result.created is True
    assert result.backup_path is None
    written = (repo / ".env").read_text(encoding="utf-8")
    assert "ENCRYPTION_KEY=k" in written
    assert "AGENT_API_TOKEN=t" in written
    assert "LLM_PROVIDER=anthropic" in written


def test_complete_env_is_never_opened_for_writing(repo: Path):
    env = repo / ".env"
    original = "ENCRYPTION_KEY=mine\nAGENT_API_TOKEN=also-mine\n"
    env.write_text(original, encoding="utf-8")
    before = env.stat().st_mtime_ns

    result = envfile.ensure(
        env, repo / ".env.example", {"ENCRYPTION_KEY": "new", "AGENT_API_TOKEN": "new"}
    )

    assert result.created is False
    assert result.filled == []
    assert result.appended == []
    assert result.backup_path is None
    assert env.read_text(encoding="utf-8") == original
    assert env.stat().st_mtime_ns == before


def test_blank_assignment_is_filled_in_place(repo: Path):
    env = repo / ".env"
    env.write_text("# my note\nLLM_PROVIDER=openai\nENCRYPTION_KEY=\n", encoding="utf-8")

    result = envfile.ensure(env, repo / ".env.example", {"ENCRYPTION_KEY": "generated"})

    assert result.filled == ["ENCRYPTION_KEY"]
    assert result.appended == []
    lines = env.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "# my note"
    assert lines[1] == "LLM_PROVIDER=openai"
    assert lines[2] == "ENCRYPTION_KEY=generated"
    assert envfile.MANAGED_HEADER not in env.read_text(encoding="utf-8")


def test_blank_assignment_does_not_produce_a_duplicate_key(repo: Path):
    env = repo / ".env"
    env.write_text("ENCRYPTION_KEY=\n", encoding="utf-8")

    envfile.ensure(env, repo / ".env.example", {"ENCRYPTION_KEY": "generated"})

    text = env.read_text(encoding="utf-8")
    assert text.count("ENCRYPTION_KEY=") == 1


def test_absent_key_is_appended_under_a_marked_header(repo: Path):
    env = repo / ".env"
    env.write_text("LLM_PROVIDER=openai\n", encoding="utf-8")

    result = envfile.ensure(env, repo / ".env.example", {"AGENT_API_TOKEN": "tok"})

    assert result.appended == ["AGENT_API_TOKEN"]
    assert result.filled == []
    text = env.read_text(encoding="utf-8")
    assert text.startswith("LLM_PROVIDER=openai\n")
    assert envfile.MANAGED_HEADER in text
    assert text.rstrip().endswith("AGENT_API_TOKEN=tok")


def test_existing_values_and_comments_survive_byte_for_byte(repo: Path):
    env = repo / ".env"
    original = "# careful\nLLM_PROVIDER=openai   # trailing note\n\nOPENAI_API_KEY=sk-real\n"
    env.write_text(original, encoding="utf-8")

    envfile.ensure(env, repo / ".env.example", {"AGENT_API_TOKEN": "tok"})

    text = env.read_text(encoding="utf-8")
    assert text.startswith(original)


def test_backup_written_before_any_change(repo: Path):
    env = repo / ".env"
    original = "LLM_PROVIDER=openai\n"
    env.write_text(original, encoding="utf-8")

    result = envfile.ensure(env, repo / ".env.example", {"AGENT_API_TOKEN": "tok"})

    assert result.backup_path is not None
    assert result.backup_path.read_text(encoding="utf-8") == original
    assert result.backup_path.name.startswith(".env.backup-")


def test_rerunning_on_a_complete_env_is_a_noop(repo: Path):
    env = repo / ".env"
    envfile.ensure(env, repo / ".env.example", {"ENCRYPTION_KEY": "k", "AGENT_API_TOKEN": "t"})
    after_first = env.read_text(encoding="utf-8")

    result = envfile.ensure(
        env, repo / ".env.example", {"ENCRYPTION_KEY": "other", "AGENT_API_TOKEN": "other"}
    )

    assert result.filled == []
    assert result.appended == []
    assert env.read_text(encoding="utf-8") == after_first


def test_set_value_replaces_a_valued_line_and_backs_up(repo: Path):
    env = repo / ".env"
    env.write_text("# note\nAPP_PORT=5627\nLLM_PROVIDER=openai\n", encoding="utf-8")

    backup_path = envfile.set_value(env, "APP_PORT", "5629")

    assert backup_path.read_text(encoding="utf-8").count("APP_PORT=5627") == 1
    lines = env.read_text(encoding="utf-8").splitlines()
    assert lines == ["# note", "APP_PORT=5629", "LLM_PROVIDER=openai"]


def test_set_value_appends_when_the_key_is_absent(repo: Path):
    env = repo / ".env"
    env.write_text("LLM_PROVIDER=openai\n", encoding="utf-8")

    envfile.set_value(env, "APP_PORT", "5629")

    assert "APP_PORT=5629" in env.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_launcher_envfile.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'launcher'`.

- [ ] **Step 3: Create the package marker**

Create `launcher/__init__.py`:

```python
"""Bootstrap run by the per-OS launcher scripts before the stack starts.

Standard library only: this package executes inside a bare `python:3-alpine`
container that installs no packages.
"""
```

- [ ] **Step 4: Write the implementation**

Create `launcher/envfile.py`:

```python
"""Read and safely update the project's .env file.

Bootstrap runs before the stack starts and must never destroy an existing
configuration — the maintainer's own or a colleague's. Only three writes are
performed: creating the file when it is absent, filling a blank assignment in
place, and appending a key that is absent entirely. A line carrying a value is
never touched, so comments, ordering and formatting survive byte-for-byte.

`set_value` is the single exception, reserved for the port variables the
launcher owns; see its docstring for why that is safe.
"""

from __future__ import annotations

import base64
import os
import secrets
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

MANAGED_HEADER = "# --- added by the TruthCV launcher ---"


def parse(text: str) -> dict[str, str]:
    """KEY=VALUE pairs from .env text; comments and blank lines ignored."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    return values


def generate_encryption_key() -> str:
    """A Fernet key, identical in construction to `api.genkey`'s output."""
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


def generate_agent_token() -> str:
    """The shared secret the app and agent authenticate to each other with."""
    return secrets.token_hex(32)


def backup(path: Path) -> Path:
    """Copy `path` beside itself with a UTC timestamp; returns the copy."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = path.with_name(f"{path.name}.backup-{stamp}")
    shutil.copy2(path, destination)
    return destination


@dataclass
class EnsureResult:
    """What `ensure` did, so the caller can report it precisely."""

    created: bool = False
    filled: list[str] = field(default_factory=list)
    appended: list[str] = field(default_factory=list)
    backup_path: Path | None = None
    values: dict[str, str] = field(default_factory=dict)


def ensure(env_path: Path, example_path: Path, required: dict[str, str]) -> EnsureResult:
    """Guarantee every key in `required` has a non-blank value in `.env`.

    `required` maps each key to the value to use *only if* it is missing or
    blank. A key that already carries a value keeps it, and the supplied value
    is discarded — re-running never rotates a live secret.
    """
    if not env_path.exists():
        lines = example_path.read_text(encoding="utf-8").splitlines()
        filled, appended = _apply(lines, required)
        text = "\n".join(lines) + "\n"
        env_path.write_text(text, encoding="utf-8")
        return EnsureResult(created=True, filled=filled, appended=appended, values=parse(text))

    original = env_path.read_text(encoding="utf-8")
    existing = parse(original)
    missing = {key: value for key, value in required.items() if not existing.get(key)}
    if not missing:
        # Nothing to do, and the file is not opened for writing at all.
        return EnsureResult(values=existing)

    backup_path = backup(env_path)
    lines = original.splitlines()
    filled, appended = _apply(lines, missing)
    text = "\n".join(lines) + "\n"
    env_path.write_text(text, encoding="utf-8")
    return EnsureResult(
        filled=filled, appended=appended, backup_path=backup_path, values=parse(text)
    )


def set_value(env_path: Path, key: str, value: str) -> Path:
    """Rewrite one key's line in place, backing the file up first.

    This is the only function that changes a line carrying a value. It is
    reserved for the port variables the launcher owns, and is called only after
    Docker itself has refused to bind the current port — so the value being
    replaced is already known not to work. Returns the backup's path.
    """
    backup_path = backup(env_path)
    lines = env_path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        if stripped.partition("=")[0].strip() == key:
            lines[index] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return backup_path


def _apply(lines: list[str], required: dict[str, str]) -> tuple[list[str], list[str]]:
    """Fill blank assignments in place and append keys absent entirely.

    Mutates `lines`. Returns (filled keys, appended keys). Filling in place
    rather than appending is what keeps each key appearing exactly once: the
    shipped `.env.example` carries blank `ENCRYPTION_KEY=` and
    `AGENT_API_TOKEN=` lines, and appending past them would emit each key
    twice and make correctness depend on compose resolving duplicates.
    """
    filled: list[str] = []
    appended: list[str] = []
    for key, value in required.items():
        index = _blank_assignment_index(lines, key)
        if index is None:
            appended.append(key)
        else:
            lines[index] = f"{key}={value}"
            filled.append(key)
    if appended:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(MANAGED_HEADER)
        lines.extend(f"{key}={required[key]}" for key in appended)
    return filled, appended


def _blank_assignment_index(lines: list[str], key: str) -> int | None:
    """Index of a `KEY=` line carrying no value, or None."""
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        if name.strip() == key and not value.strip():
            return index
    return None
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_launcher_envfile.py -v`
Expected: PASS, 13 tests.

- [ ] **Step 6: Commit**

```bash
git add launcher/__init__.py launcher/envfile.py tests/test_launcher_envfile.py
git commit -m "Add append-safe .env handling for the launcher

Three writes only: create when absent, fill a blank assignment in
place, append a key that is absent entirely. A line carrying a value is
never touched, and an existing file is always backed up first.

Filling blanks in place rather than appending past them is what keeps
each key appearing exactly once — .env.example ships blank
ENCRYPTION_KEY= and AGENT_API_TOKEN= lines, and appending would emit
both keys twice."
```

---

### Task 3: Port defaults and next-candidate selection

**Files:**
- Create: `launcher/ports.py`
- Test: `tests/test_launcher_ports.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `DEFAULTS: dict[str, int]` — `{"APP_PORT": 5627, "NOVNC_HOST_PORT": 5628}`
  - `MAX_PORT: int`
  - `default_for(key: str) -> int`
  - `bump(current: int, reserved: set[int]) -> int`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_launcher_ports.py`:

```python
"""Host port defaults and next-candidate selection.

There is no probing here, and that is deliberate: bootstrap runs inside a
container, where binding a socket tests the container's network namespace
rather than the host's. Docker's own bind attempt is the only authoritative
signal, so these functions just decide what to try next.
"""

from __future__ import annotations

import pytest

from launcher import ports


def test_defaults_are_5627_and_5628():
    assert ports.DEFAULTS == {"APP_PORT": 5627, "NOVNC_HOST_PORT": 5628}


def test_default_for_returns_the_configured_port():
    assert ports.default_for("APP_PORT") == 5627
    assert ports.default_for("NOVNC_HOST_PORT") == 5628


def test_bump_advances_by_one():
    assert ports.bump(5627, set()) == 5628


def test_bump_skips_reserved_ports():
    """An app port advancing past 5627 must not land on the noVNC default."""
    assert ports.bump(5627, {5628}) == 5629


def test_bump_skips_a_run_of_reserved_ports():
    assert ports.bump(5627, {5628, 5629, 5630}) == 5631


def test_bump_raises_past_the_maximum():
    with pytest.raises(ValueError):
        ports.bump(ports.MAX_PORT, set())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_launcher_ports.py -v`
Expected: FAIL with `ImportError: cannot import name 'ports' from 'launcher'`.

- [ ] **Step 3: Write the implementation**

Create `launcher/ports.py`:

```python
"""Host port assignment for the compose stack.

Bootstrap does not probe for a free port, and cannot: it runs inside a
container, where binding a socket tests the container's network namespace
rather than the host's, and `--network host` does not exist on Docker Desktop
for macOS or Windows. A probe from in there would report ports free that the
host has bound.

Docker's own bind attempt is the authoritative signal. The launcher runs
compose, and calls `bump` only when compose reports a port conflict — so a
port already recorded in .env is never moved speculatively.
"""

from __future__ import annotations

DEFAULTS: dict[str, int] = {"APP_PORT": 5627, "NOVNC_HOST_PORT": 5628}

MAX_PORT = 65535


def default_for(key: str) -> int:
    """The shipped default for a host port variable."""
    return DEFAULTS[key]


def bump(current: int, reserved: set[int]) -> int:
    """The next candidate above `current`, skipping `reserved`.

    `reserved` carries the ports already assigned to the other host variables,
    so an app port advancing past 5627 cannot land on the noVNC default.
    """
    candidate = current + 1
    while candidate in reserved:
        candidate += 1
    if candidate > MAX_PORT:
        raise ValueError(f"No port available above {current}.")
    return candidate
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_launcher_ports.py -v`
Expected: PASS, 6 tests.

- [ ] **Step 5: Commit**

```bash
git add launcher/ports.py tests/test_launcher_ports.py
git commit -m "Add host port defaults and next-candidate selection

Defaults are 5627 for the app and 5628 for noVNC. No probing: bootstrap
runs inside a container where a socket bind tests the container's
network namespace, not the host's, so Docker's own bind attempt is the
only authoritative signal. bump() skips ports already assigned to the
other variable."
```

---

### Task 4: The bootstrap CLI

**Files:**
- Create: `launcher/__main__.py`
- Test: `tests/test_launcher_main.py`

**Interfaces:**
- Consumes: `launcher.envfile` (`ensure`, `set_value`, `parse`, `generate_encryption_key`, `generate_agent_token`, `EnsureResult`), `launcher.ports` (`DEFAULTS`, `default_for`, `bump`)
- Produces: `main(argv: list[str] | None = None) -> int`, invoked as `python -m launcher --repo <path> [--bump VAR]`. Writes human messages to stderr and exactly one `KEY=value` line to stdout.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_launcher_main.py`:

```python
"""The bootstrap CLI, exercised against a temp repository.

stdout carries exactly one machine-readable KEY=value line so the per-OS
shims can read the port without parsing prose; everything a human reads goes
to stderr.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from launcher import __main__ as bootstrap
from launcher import envfile

EXAMPLE = """LLM_PROVIDER=anthropic
ENCRYPTION_KEY=
AGENT_API_TOKEN=
"""


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / ".env.example").write_text(EXAMPLE, encoding="utf-8")
    return tmp_path


def test_creates_env_with_every_required_key(repo: Path, capsys):
    assert bootstrap.main(["--repo", str(repo)]) == 0

    values = envfile.parse((repo / ".env").read_text(encoding="utf-8"))
    assert len(values["ENCRYPTION_KEY"]) > 0
    assert len(values["AGENT_API_TOKEN"]) == 64
    assert values["APP_PORT"] == "5627"
    assert values["NOVNC_HOST_PORT"] == "5628"


def test_prints_the_app_port_as_the_only_stdout_line(repo: Path, capsys):
    bootstrap.main(["--repo", str(repo)])

    captured = capsys.readouterr()
    assert captured.out.strip() == "APP_PORT=5627"
    assert captured.err != ""


def test_does_not_rotate_existing_secrets(repo: Path):
    env = repo / ".env"
    env.write_text(
        "ENCRYPTION_KEY=mine\nAGENT_API_TOKEN=also-mine\nAPP_PORT=9999\n"
        "NOVNC_HOST_PORT=9998\n",
        encoding="utf-8",
    )
    original = env.read_text(encoding="utf-8")

    bootstrap.main(["--repo", str(repo)])

    assert env.read_text(encoding="utf-8") == original


def test_reports_the_stored_port_not_the_default(repo: Path, capsys):
    (repo / ".env").write_text(
        "ENCRYPTION_KEY=k\nAGENT_API_TOKEN=t\nAPP_PORT=9999\nNOVNC_HOST_PORT=9998\n",
        encoding="utf-8",
    )

    bootstrap.main(["--repo", str(repo)])

    assert capsys.readouterr().out.strip() == "APP_PORT=9999"


def test_bump_advances_the_named_port(repo: Path, capsys):
    bootstrap.main(["--repo", str(repo)])
    capsys.readouterr()

    assert bootstrap.main(["--repo", str(repo), "--bump", "APP_PORT"]) == 0

    values = envfile.parse((repo / ".env").read_text(encoding="utf-8"))
    # 5628 is the noVNC default, so the app port skips it.
    assert values["APP_PORT"] == "5629"
    assert values["NOVNC_HOST_PORT"] == "5628"
    assert capsys.readouterr().out.strip() == "APP_PORT=5629"


def test_bump_leaves_secrets_untouched(repo: Path):
    bootstrap.main(["--repo", str(repo)])
    before = envfile.parse((repo / ".env").read_text(encoding="utf-8"))

    bootstrap.main(["--repo", str(repo), "--bump", "APP_PORT"])

    after = envfile.parse((repo / ".env").read_text(encoding="utf-8"))
    assert after["ENCRYPTION_KEY"] == before["ENCRYPTION_KEY"]
    assert after["AGENT_API_TOKEN"] == before["AGENT_API_TOKEN"]


def test_bump_rejects_an_unknown_variable(repo: Path):
    bootstrap.main(["--repo", str(repo)])
    assert bootstrap.main(["--repo", str(repo), "--bump", "NOPE"]) == 2


def test_bump_without_an_env_file_fails_clearly(repo: Path, capsys):
    assert bootstrap.main(["--repo", str(repo), "--bump", "APP_PORT"]) == 2
    assert "run without --bump first" in capsys.readouterr().err
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_launcher_main.py -v`
Expected: FAIL with `ImportError: cannot import name '__main__' from 'launcher'`.

- [ ] **Step 3: Write the implementation**

Create `launcher/__main__.py`:

```python
"""Prepare .env so `docker compose up` can start the stack.

Run inside a container by the per-OS launcher scripts:

    docker run --rm -v "<repo>:/work" -w /work python:3-alpine \\
        python -m launcher --repo /work

Standard library only — the image installs no packages.

Output contract: everything a human reads goes to stderr, and stdout carries
exactly one machine-readable KEY=value line, so a shell shim can read the port
with a single `cut` and never has to parse prose.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import envfile, ports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="launcher")
    parser.add_argument("--repo", default=".", help="Repository root holding .env")
    parser.add_argument(
        "--bump",
        metavar="VAR",
        default="",
        help="Advance this host port variable to its next candidate",
    )
    args = parser.parse_args(argv)

    repo = Path(args.repo)
    env_path = repo / ".env"

    if args.bump:
        return _bump(env_path, args.bump)

    required = {
        "ENCRYPTION_KEY": envfile.generate_encryption_key(),
        "AGENT_API_TOKEN": envfile.generate_agent_token(),
        "APP_PORT": str(ports.default_for("APP_PORT")),
        "NOVNC_HOST_PORT": str(ports.default_for("NOVNC_HOST_PORT")),
    }
    result = envfile.ensure(env_path, repo / ".env.example", required)
    _report(result)
    print(f"APP_PORT={result.values.get('APP_PORT', '')}")
    return 0


def _bump(env_path: Path, variable: str) -> int:
    """Advance one host port variable past a port Docker refused to bind."""
    if variable not in ports.DEFAULTS:
        print(f"Unknown port variable: {variable}", file=sys.stderr)
        return 2
    if not env_path.exists():
        print("No .env to bump — run without --bump first.", file=sys.stderr)
        return 2

    values = envfile.parse(env_path.read_text(encoding="utf-8"))
    current = int(values.get(variable) or ports.default_for(variable))
    reserved = {
        int(value)
        for key, value in values.items()
        if key in ports.DEFAULTS and key != variable and value.isdigit()
    }
    try:
        advanced = ports.bump(current, reserved)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2

    backup_path = envfile.set_value(env_path, variable, str(advanced))
    print(
        f"{variable} {current} was already in use; trying {advanced}. "
        f"Previous .env saved to {backup_path.name}.",
        file=sys.stderr,
    )
    print(f"{variable}={advanced}")
    return 0


def _report(result: envfile.EnsureResult) -> None:
    """Say exactly what changed, so nothing happens to .env silently."""
    if result.created:
        print("Created .env from .env.example.", file=sys.stderr)
    if result.backup_path is not None:
        print(f"Existing .env saved to {result.backup_path.name}.", file=sys.stderr)
    for key in result.filled:
        print(f"Filled in {key} (it was blank).", file=sys.stderr)
    for key in result.appended:
        print(f"Added {key}.", file=sys.stderr)
    if not (result.created or result.filled or result.appended):
        print("Configuration already complete; nothing changed.", file=sys.stderr)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_launcher_main.py -v`
Expected: PASS, 8 tests.

- [ ] **Step 5: Verify it runs in the real bootstrap image**

Run:

```bash
docker run --rm -v "$(pwd):/work" -w /work python:3-alpine python -m launcher --help
```

Expected: the argparse help text, proving the package imports with no third-party packages available.

- [ ] **Step 6: Commit**

```bash
git add launcher/__main__.py tests/test_launcher_main.py
git commit -m "Add the bootstrap CLI

Generates ENCRYPTION_KEY, AGENT_API_TOKEN and the host port defaults
into .env before the stack starts, and advances a port with --bump when
Docker refuses to bind it. Existing values are never rotated.

Human output goes to stderr; stdout carries exactly one KEY=value line
so the per-OS shims read the port with a single cut."
```

---

### Task 5: The per-OS launcher shims

**Files:**
- Create: `scripts/launch/truthcv.sh`, `scripts/launch/truthcv.command`, `scripts/launch/truthcv.desktop`, `scripts/launch/truthcv.bat`

**Interfaces:**
- Consumes: `python -m launcher --repo /work [--bump APP_PORT]` and its stdout contract from Task 4; `APP_PORT` / `NOVNC_HOST_PORT` from Task 1
- Produces: a running stack and an opened browser. No other task depends on these.

- [ ] **Step 1: Write the shared shell shim**

Create `scripts/launch/truthcv.sh`:

```bash
#!/usr/bin/env bash
# Shared launcher for macOS and Linux. truthcv.command and truthcv.desktop
# both delegate here so there is one implementation, not three.
#
# All real logic lives in `python -m launcher`, run inside a container: macOS
# and Linux ship Python 3 but Windows does not, and Docker is already a hard
# requirement, so it is the one interpreter guaranteed present everywhere.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO"

BOOTSTRAP_IMAGE="python:3-alpine"
MAX_PORT_ATTEMPTS=10

fail() { printf '\n%s\n' "$1" >&2; read -r -p "Press Enter to close." _; exit 1; }

if ! command -v docker >/dev/null 2>&1; then
  fail "TruthCV needs Docker Desktop, which isn't installed.
Download it from https://docs.docker.com/get-docker/ then run this again."
fi

if ! docker info >/dev/null 2>&1; then
  fail "Docker Desktop isn't running. Start it, wait for the whale icon to
settle, then run this again."
fi

# Files the container creates must belong to the user, not root — otherwise
# the generated .env reproduces the PermissionError the README documents for
# the data volume.
run_bootstrap() {
  docker run --rm \
    --user "$(id -u):$(id -g)" \
    -v "$REPO:/work" -w /work \
    "$BOOTSTRAP_IMAGE" python -m launcher --repo /work "$@"
}

APP_PORT="$(run_bootstrap | cut -d= -f2)"

if [ ! -d api/static/assets ]; then
  printf '%s\n' "Setting up TruthCV for the first time.
This takes about 10 minutes and only happens once."
fi

attempt=1
until docker compose up -d --build 2>compose.err; do
  if ! grep -qiE 'port is already allocated|address already in use|bind for' compose.err; then
    cat compose.err >&2
    fail "TruthCV couldn't start. The log above says why; compose.err has the full text."
  fi
  if [ "$attempt" -ge "$MAX_PORT_ATTEMPTS" ]; then
    fail "Tried $MAX_PORT_ATTEMPTS ports and every one was busy. Something
unusual is holding them — restart the machine and try again."
  fi
  APP_PORT="$(run_bootstrap --bump APP_PORT | cut -d= -f2)"
  attempt=$((attempt + 1))
done
rm -f compose.err

URL="http://localhost:${APP_PORT}"
printf '%s\n' "TruthCV is starting at $URL"

for _ in $(seq 1 60); do
  if curl -fsS -o /dev/null "$URL"; then break; fi
  sleep 2
done

if command -v open >/dev/null 2>&1; then open "$URL"
elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"
else printf '%s\n' "Open $URL in your browser."
fi
```

- [ ] **Step 2: Make it executable and write the macOS entry**

Run: `chmod +x scripts/launch/truthcv.sh`

Create `scripts/launch/truthcv.command` (macOS double-click opens `.command` in Terminal):

```bash
#!/usr/bin/env bash
# macOS double-click entry. Finder runs .command files in Terminal; all logic
# lives in truthcv.sh so there is one implementation to maintain.
exec "$(dirname "${BASH_SOURCE[0]}")/truthcv.sh"
```

Run: `chmod +x scripts/launch/truthcv.command`

- [ ] **Step 3: Write the Linux desktop entry**

Create `scripts/launch/truthcv.desktop`:

```ini
[Desktop Entry]
Type=Application
Name=TruthCV
Comment=Start TruthCV and open it in your browser
Exec=sh -c '"$(dirname "%k")/truthcv.sh"'
Terminal=true
Categories=Office;
```

- [ ] **Step 4: Write the Windows entry**

Create `scripts/launch/truthcv.bat`:

```bat
@echo off
REM Windows double-click entry. Mirrors truthcv.sh; Windows ships no shell
REM the other two can share, so this is the one place logic is duplicated.
REM Keep it in step with truthcv.sh when either changes.
setlocal enabledelayedexpansion
cd /d "%~dp0..\.."

where docker >nul 2>&1
if errorlevel 1 (
  echo TruthCV needs Docker Desktop, which isn't installed.
  echo Download it from https://docs.docker.com/get-docker/ then run this again.
  pause & exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
  echo Docker Desktop isn't running. Start it, wait for the whale icon to
  echo settle, then run this again.
  pause & exit /b 1
)

REM No --user here: Docker Desktop for Windows maps ownership itself, and
REM there is no id command to read a uid from.
for /f "delims=" %%p in ('docker run --rm -v "%CD%:/work" -w /work python:3-alpine python -m launcher --repo /work') do set "PORTLINE=%%p"
for /f "tokens=2 delims==" %%v in ("!PORTLINE!") do set "APP_PORT=%%v"

if not exist "api\static\assets" (
  echo Setting up TruthCV for the first time.
  echo This takes about 10 minutes and only happens once.
)

set /a ATTEMPT=1
:up
docker compose up -d --build 2>compose.err
if not errorlevel 1 goto ready
findstr /i /c:"port is already allocated" /c:"address already in use" /c:"bind for" compose.err >nul
if errorlevel 1 (
  type compose.err
  echo TruthCV couldn't start. The log above says why.
  pause & exit /b 1
)
if !ATTEMPT! GEQ 10 (
  echo Tried 10 ports and every one was busy. Restart the machine and try again.
  pause & exit /b 1
)
for /f "delims=" %%p in ('docker run --rm -v "%CD%:/work" -w /work python:3-alpine python -m launcher --repo /work --bump APP_PORT') do set "PORTLINE=%%p"
for /f "tokens=2 delims==" %%v in ("!PORTLINE!") do set "APP_PORT=%%v"
set /a ATTEMPT+=1
goto up

:ready
del /q compose.err 2>nul
echo TruthCV is starting at http://localhost:!APP_PORT!
timeout /t 20 /nobreak >nul
start "" "http://localhost:!APP_PORT!"
```

- [ ] **Step 5: Smoke-test the shell shim on this machine**

Run: `./scripts/launch/truthcv.sh`
Expected: reports what it did to `.env` (nothing, since yours is complete), brings the stack up, prints the URL, opens the browser. Confirm with `docker compose ps` that all three services are up, and that your `.env` is unchanged: `git diff --stat` shows nothing and no `.env.backup-*` file was created.

- [ ] **Step 6: Commit**

```bash
git add scripts/launch/
git commit -m "Add per-OS launcher shims

Preflight Docker, run the bootstrap container, compose up, retry with a
bumped port when Docker refuses to bind, then open the browser.

macOS and Linux share truthcv.sh; Windows has no shell they can share,
so truthcv.bat duplicates the flow and says so in a comment."
```

---

### Task 6: The release script

**Files:**
- Create: `scripts/release.sh`
- Test: `tests/test_release_script.py`

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces: `dist/truthcv-<ref>.zip`. No other task depends on it.

- [ ] **Step 1: Write the failing test**

Create `tests/test_release_script.py`:

```python
"""The release zip must never carry secrets or personal data.

git archive can only emit tracked files, and .env, data/ and
answers.local.yaml are all gitignored — so exclusion is structural rather
than a list someone has to maintain. The assertions here prove it stayed that
way, because the cost of getting this wrong is mailing colleagues an API key.
"""

from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "release.sh"


@pytest.fixture(scope="module")
def built_zip(tmp_path_factory) -> zipfile.ZipFile:
    out = tmp_path_factory.mktemp("release")
    subprocess.run(
        ["bash", str(SCRIPT), "--out", str(out)], cwd=REPO, check=True, capture_output=True
    )
    archives = list(out.glob("truthcv-*.zip"))
    assert len(archives) == 1, f"expected one zip, found {archives}"
    return zipfile.ZipFile(archives[0])


def test_zip_excludes_the_env_file(built_zip):
    assert not [n for n in built_zip.namelist() if Path(n).name == ".env"]


def test_zip_excludes_the_data_directory(built_zip):
    assert not [n for n in built_zip.namelist() if "/data/" in n or n.endswith("/data")]


def test_zip_excludes_personal_answers(built_zip):
    assert not [n for n in built_zip.namelist() if n.endswith("answers.local.yaml")]


def test_zip_contains_what_a_colleague_needs(built_zip):
    names = {"/".join(n.split("/")[1:]) for n in built_zip.namelist()}
    for required in (
        "docker-compose.yml",
        "Dockerfile",
        ".env.example",
        "SETUP.md",
        "launcher/__main__.py",
        "scripts/launch/truthcv.sh",
        "scripts/launch/truthcv.bat",
    ):
        assert required in names, f"{required} missing from the release zip"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_release_script.py -v`
Expected: FAIL — `scripts/release.sh` does not exist, so `subprocess.run(..., check=True)` raises.

- [ ] **Step 3: Write the script**

Create `scripts/release.sh`:

```bash
#!/usr/bin/env bash
# Build the distributable zip.
#
# Uses `git archive`, which can only emit tracked files. .env, data/ and
# answers.local.yaml are all gitignored, so they are excluded structurally
# rather than by a list someone has to keep correct. A plain `zip -r` of the
# working directory would ship the maintainer's API keys, ledger and
# secrets.enc; this cannot, and the assertions below prove it.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

OUT_DIR="$REPO/dist"
REF="HEAD"
while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT_DIR="$2"; shift 2 ;;
    --ref) REF="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

mkdir -p "$OUT_DIR"
SHORT="$(git rev-parse --short "$REF")"
ARCHIVE="$OUT_DIR/truthcv-$SHORT.zip"

git archive --format=zip --prefix="truthcv-$SHORT/" -o "$ARCHIVE" "$REF"

# git archive should make these impossible. Assert anyway: this is the one
# failure in the project that cannot be walked back once the zip is sent.
for forbidden in '.env' 'data/' 'answers.local.yaml'; do
  if unzip -Z1 "$ARCHIVE" | grep -qE "(^|/)${forbidden%/}(/|$)"; then
    rm -f "$ARCHIVE"
    echo "ABORT: $forbidden found in the archive. Not shipping it." >&2
    exit 1
  fi
done

echo "Built $ARCHIVE"
```

- [ ] **Step 4: Make it executable and run the test**

Run: `chmod +x scripts/release.sh && .venv/bin/python -m pytest tests/test_release_script.py -v`
Expected: PASS, 4 tests. (`SETUP.md` arrives in Task 7 — if that task has not run yet, `test_zip_contains_what_a_colleague_needs` fails on `SETUP.md` alone. Run Task 7 first, or re-run this test after it.)

- [ ] **Step 5: Confirm by hand that your own secrets are absent**

Run: `bash scripts/release.sh && unzip -Z1 dist/truthcv-*.zip | grep -cE '\.env$|/data/' || echo "clean"`
Expected: `clean`.

- [ ] **Step 6: Commit**

```bash
git add scripts/release.sh tests/test_release_script.py
git commit -m "Add the release script

Builds the distributable zip with git archive, which can only emit
tracked files — so the maintainer's .env, data/ and answers.local.yaml
are excluded structurally rather than by a maintained list. Asserts
their absence afterwards and refuses to ship the archive otherwise."
```

---

### Task 7: The non-technical setup guide

**Files:**
- Create: `SETUP.md`

**Interfaces:**
- Consumes: the launcher filenames from Task 5, the default port 5627 from Task 1
- Produces: nothing other tasks depend on

- [ ] **Step 1: Write the guide**

Create `SETUP.md`:

```markdown
# Setting up TruthCV

Three steps. You will not need to type any commands.

## 1. Install Docker Desktop

TruthCV runs inside Docker, so install that first:
<https://docs.docker.com/get-docker/>

Download the version for your computer, run the installer, then start
Docker Desktop and wait for its whale icon to stop animating.

## 2. Unzip TruthCV

Unzip the file you were sent, somewhere you will find it again — your
Documents folder is fine. Keep the whole folder together; TruthCV needs
the files next to each other.

## 3. Start it

Open the `scripts/launch` folder inside it and double-click:

- **macOS** — `truthcv.command`
- **Windows** — `truthcv.bat`
- **Linux** — `truthcv.desktop`

The first start takes about ten minutes, because your computer is
building TruthCV. That happens once. Every start after it takes a few
seconds.

When it is ready your browser opens at <http://localhost:5627>. If your
computer was already using that address TruthCV picks another one and
tells you which.

## Finishing setup in the browser

TruthCV walks you through the rest:

1. **Connect Claude** — sign in with your Claude account. You do not need
   an API key.
2. **Upload your LinkedIn PDF** — this becomes your truth file, the only
   source of facts TruthCV is allowed to use.
3. **Fill in your details** — name, email, phone and the other questions
   job applications always ask.
4. **Choose target companies** — only needed if you want TruthCV to apply
   for you.

## If something goes wrong

**"Docker Desktop isn't running"** — start Docker Desktop, wait for the
whale icon to settle, then double-click the launcher again.

**Nothing opens** — open <http://localhost:5627> yourself. It may still
be starting.

**Stopping TruthCV** — quit Docker Desktop. Your data stays where it is.

Your CVs, applications and sign-ins never leave your computer.
```

- [ ] **Step 2: Verify the release zip now carries it**

Run: `bash scripts/release.sh && unzip -Z1 dist/truthcv-*.zip | grep -c 'SETUP.md'`
Expected: `1`.

- [ ] **Step 3: Run the whole suite**

Run: `.venv/bin/python -m pytest --ignore=tests/test_company_boards_store.py`
Expected: all pass. `tests/test_company_boards_store.py` is excluded because it fails on the container-owned `data/` directory for reasons that predate this work.

- [ ] **Step 4: Commit**

```bash
git add SETUP.md
git commit -m "Add a non-technical setup guide

Install Docker Desktop, unzip, double-click. No commands. README.md is
unchanged and stays the maintainer's document."
```

---

## Self-review

**Spec coverage**

| Spec section | Task |
|---|---|
| Bootstrap runs in a container | 4 (step 5 proves it), 5 (invokes it) |
| `.env` handling, all five rules | 2 |
| Why `AGENT_API_TOKEN` cannot come from the UI | 4 (generates it before compose starts) |
| Who supplies what | 2, 4 |
| Ports, host side only | 1 |
| Name collision | 1 (step 3 comment), Global Constraints |
| Verified non-breakages | 1 (step 5) |
| Port selection and `--bump` | 3, 4, 5 |
| First-run wizard | **Separate plan** — `2026-08-25-first-run-wizard.md` |
| Distribution | 6, 7 |
| Error handling | 5 |
| Testing | 2, 3, 4, 6 |

**Known gap:** the spec's error-handling table lists "Build fails — keeps the log". `truthcv.sh` writes `compose.err` and prints it, but does not preserve it after a successful retry. That is deliberate: a stale error log from a recovered port conflict is more confusing than no log. The failure path does keep it.

**Type consistency:** `ensure`, `set_value`, `parse`, `backup`, `EnsureResult`, `DEFAULTS`, `default_for` and `bump` are named identically in their defining task, in `__main__.py`, and in every test.

**Not covered here:** `compose.err` is written into the repository root and removed on success. It is not gitignored; if that proves untidy, add it in a follow-up rather than expanding this plan.
