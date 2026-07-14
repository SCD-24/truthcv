"""Truth Store: owns truth.yaml, the single origin of all facts.

Nothing downstream may assert a fact that is not in this store. Facts are
grouped: experiences (role/company/dates/bullets) and education own their parts,
skills are flat. The guardrail validates every rendered draft against the facts
of the experience it belongs to.
"""

from .model import (
    Bullet,
    Education,
    Experience,
    Link,
    Profile,
    Skill,
    Truth,
    SOURCE_VALUES,
    make_id,
)
from .store import (
    load,
    save,
    validate,
    data_dir,
    truth_path,
    persist_source_hash,
    loaded_source_hash,
)

__all__ = [
    "Bullet",
    "Education",
    "Experience",
    "Link",
    "Profile",
    "Skill",
    "Truth",
    "SOURCE_VALUES",
    "make_id",
    "load",
    "save",
    "validate",
    "data_dir",
    "truth_path",
    "persist_source_hash",
    "loaded_source_hash",
]
