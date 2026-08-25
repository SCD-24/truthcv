"""The release zip must never carry secrets or personal data.

git archive can only emit tracked files, and .env, data/ and
answers.local.yaml are all gitignored — so exclusion is structural rather
than a list someone has to maintain. The assertions here prove it stayed that
way, because the cost of getting this wrong is mailing colleagues an API key.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "release.sh"


def _forbidden_patterns() -> list[str]:
    """Parse the FORBIDDEN_PATTERNS bash array out of release.sh.

    Parsed rather than duplicated so this test guards the actual patterns the
    script runs, not a copy that could silently drift from them.
    """
    text = SCRIPT.read_text()
    match = re.search(r"FORBIDDEN_PATTERNS=\((.*?)^\)", text, re.DOTALL | re.MULTILINE)
    assert match, "FORBIDDEN_PATTERNS array not found in release.sh"
    return re.findall(r"'([^']*)'", match.group(1))


def _matches_any(pattern_strings: list[str], path: str) -> bool:
    # release.sh matches with `grep -qiE` — case-insensitive — so mirror that
    # here rather than testing a stricter comparison the script doesn't make.
    return any(re.search(p, path, re.IGNORECASE) for p in pattern_strings)


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


@pytest.mark.parametrize(
    "path,should_match",
    [
        ("truthcv-abc/.env", True),
        ("truthcv-abc/.env.backup-20260825T093000Z", True),
        ("truthcv-abc/data/applications.json", True),
        ("truthcv-abc/answers.local.yaml", True),
        ("truthcv-abc/.env.example", False),
        ("truthcv-abc/xenv", False),
        ("truthcv-abc/mydata/x", False),
        ("truthcv-abc/.ENV", True),
        ("truthcv-abc/DATA/x", True),
    ],
)
def test_forbidden_patterns_match_exactly_what_they_should(path, should_match):
    patterns = _forbidden_patterns()
    assert _matches_any(patterns, path) is should_match, (
        f"{path!r} should {'match' if should_match else 'not match'} "
        f"one of {patterns}"
    )


def test_missing_unzip_aborts_and_leaves_no_archive(tmp_path):
    """If unzip can't be found, the archive must never be shipped unverified.

    Builds a PATH containing every other external tool release.sh needs
    (git, mkdir, dirname, grep, mktemp, rm) but not unzip, so the script's
    own listing step fails the way it would if unzip were absent.
    """
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for tool in ("git", "mkdir", "dirname", "grep", "mktemp", "rm", "cat", "sh"):
        real = shutil.which(tool)
        if real is not None:
            (fake_bin / tool).symlink_to(real)
    assert not (fake_bin / "unzip").exists()

    out = tmp_path / "out"
    out.mkdir()
    env = dict(os.environ)
    env["PATH"] = str(fake_bin)
    bash = shutil.which("bash")
    assert bash is not None, "bash not found on the test runner's PATH"

    result = subprocess.run(
        [bash, str(SCRIPT), "--out", str(out)],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0, (
        f"expected a non-zero exit when unzip is unavailable, got 0. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert not list(out.glob("truthcv-*.zip")), (
        "an unverified archive was left behind when unzip was unavailable"
    )


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
