"""Load the YAML rule catalogue into a versioned, validated in-memory form.

Per 02_LLD_ITC_Recovery_Agent (section 3, rules/loader.py):
    class RuleCatalogue(BaseModel):
        version: str  # git commit hash of the catalogue dir
        rules: dict[str, RuleSpec]
    def load_catalogue(path: str) -> RuleCatalogue: ...
    def catalogue_version(path: str) -> str:  # `git rev-parse HEAD` over the dir
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import yaml
from pydantic import BaseModel


class RuleCondition(BaseModel):
    """One condition within a rule. `kind` selects how engine.py evaluates it."""

    kind: str  # "field_equals" | "time_bar" | "keyword_block"
    field: str | None = None
    value: bool | None = None
    blocked_keywords: list[str] | None = None
    deadline_month: int | None = None
    deadline_day: int | None = None


class OnFail(BaseModel):
    verdict: str  # one of VerdictType's values
    reason: str  # template string, rendered against InvoiceFacts fields


class RuleSpec(BaseModel):
    rule_id: str
    section: str
    description: str
    version: str
    last_reviewed: str
    reviewer: str
    # `conditions`/`on_fail` are populated for generically-evaluated rules
    # (everything in EVALUATION_ORDER). rule_36_4_date_gate is the one
    # exception -- it's applied as a wrapper override in engine.py, not
    # generically evaluated, so it carries a plain `reason` template
    # instead and leaves these empty.
    conditions: list[RuleCondition] = []
    on_fail: OnFail | None = None
    reason: str | None = None
    effective_date: str | None = None


class RuleCatalogue(BaseModel):
    version: str  # git commit hash of the catalogue dir
    rules: dict[str, RuleSpec]


def catalogue_version(path: str) -> str:
    """`git rev-parse HEAD` over the catalogue directory.

    Falls back to a content hash if the directory isn't inside a git
    checkout (e.g. a fresh clone before first commit, or a test fixture
    copied outside the repo) -- this keeps load_catalogue() usable in
    those environments while still being genuinely content-addressed, so
    Verdict.catalogue_version still changes whenever the YAML changes even
    without git available.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        # Fallback: sha256 over the concatenated, sorted YAML file contents.
        hasher = hashlib.sha256()
        for yaml_file in sorted(Path(path).glob("*.yaml")):
            hasher.update(yaml_file.read_bytes())
        return f"content-hash:{hasher.hexdigest()[:12]}"


def load_catalogue(path: str) -> RuleCatalogue:
    """Load every *.yaml file in `path` into a single validated RuleCatalogue.

    Each YAML file may contain either a single rule spec (a mapping) or a
    list of rule specs (section_16_2.yaml has four sub-clauses in one
    file) -- both forms are accepted and flattened into one rules dict
    keyed by rule_id.
    """
    version = catalogue_version(path)
    rules: dict[str, RuleSpec] = {}

    for yaml_file in sorted(Path(path).glob("*.yaml")):
        content = yaml.safe_load(yaml_file.read_text())
        if content is None:
            continue
        specs = content if isinstance(content, list) else [content]
        for spec_dict in specs:
            spec = RuleSpec.model_validate(spec_dict)
            if spec.rule_id in rules:
                raise ValueError(
                    f"duplicate rule_id {spec.rule_id!r} found in "
                    f"{yaml_file} (already loaded from another file)"
                )
            rules[spec.rule_id] = spec

    return RuleCatalogue(version=version, rules=rules)
