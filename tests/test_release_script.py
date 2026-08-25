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
