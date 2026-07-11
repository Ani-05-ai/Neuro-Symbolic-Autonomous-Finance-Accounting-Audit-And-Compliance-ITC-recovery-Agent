"""Verdict, ReasonStep, VerdictType -- the Rule Engine's output vocabulary.

Per 02_LLD_ITC_Recovery_Agent (section 2, domain/verdict.py).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class VerdictType(StrEnum):
    """CGST rule evaluation outcomes.

    NOTE: PROVISIONAL is retained for historical data only (tax_period <
    01/2022). Rule 36(4) provisional ITC was abolished effective 01
    January 2022 per Notification 40/2021-CT. For current-period invoices
    missing from GSTR-2B (tax_period >= 01/2022), the verdict is
    INELIGIBLE per Section 16(2)(aa). The Rule Engine applies a mandatory
    date-gate override (see engine.py).
    """

    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    BLOCKED = "blocked"
    TIME_BARRED = "time_barred"
    PROVISIONAL = "provisional"  # Historical only; see date gate below


class ReasonStep(BaseModel):
    rule_id: str  # e.g. "section_16_2_c"
    section: str  # human label
    passed: bool
    message: str  # rendered, e.g. "Supplier GSTIN ... not in GSTR-1 for 03/2025"


class Verdict(BaseModel):
    verdict: VerdictType
    reason_chain: list[ReasonStep]
    catalogue_version: str  # git commit hash of the YAML used
