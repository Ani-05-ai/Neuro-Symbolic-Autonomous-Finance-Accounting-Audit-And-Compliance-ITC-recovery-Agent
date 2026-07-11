"""The Rule Engine -- Layer 2. A pure function: no I/O, no clock, no
randomness. Same facts + same catalogue.version => identical Verdict,
always.

Per 02_LLD_ITC_Recovery_Agent (section 3):
    Evaluation order (short-circuits on first failure):
    1. Section 17(5) blocked category -> blocked
    2. Section 16(4) time-bar -> time_barred
    3. Section 16(2)(a) registered
    4. Section 16(2)(b) goods received
    5. Section 16(2)(c) supplier filed -> ineligible if not
    6. Section 16(2)(d) tax paid (via GSTR-2B presence)
    7. Rule 36(4) provisional -> provisional
    8. all pass -> eligible

Section 4.3.1: a mandatory date-gate override. Rule 36(4) provisional ITC
was abolished 01.01.2022 (Notification 40/2021-CT). If the base
evaluation lands on PROVISIONAL and facts.tax_period >= 01/2022, the
verdict is overridden to INELIGIBLE.
"""

from __future__ import annotations

from datetime import date

from itc.domain.facts import InvoiceFacts
from itc.domain.verdict import ReasonStep, Verdict, VerdictType
from itc.rules.loader import RuleCatalogue, RuleCondition, RuleSpec

# Evaluation order, per the LLD. rule_36_4_date_gate is deliberately
# excluded -- it is applied as a wrapper override, not a catalogue rule.
EVALUATION_ORDER = [
    "section_17_5_blocked",
    "section_16_4_time_bar",
    "section_16_2_a",
    "section_16_2_b",
    "section_16_2_c",
    "section_16_2_d",
]

DATE_GATE_EFFECTIVE_PERIOD = (2022, 1)  # (year, month) -- 01/2022


def _period_key(tax_period: str) -> tuple[int, int]:
    """'MM/YYYY' -> (year, month) for correct chronological comparison.

    NOTE: the LLD's illustrative override code compares tax_period strings
    directly (facts.tax_period >= "01/2022"), which is a lexicographic
    string comparison, not a chronological one -- it would incorrectly
    treat "11/2021" as "later than" "01/2022" (since '1' > '0' in the
    first character). The LLD's own conventions note that its code is
    illustrative, not a finished implementation, so this is implemented
    correctly here rather than propagating that bug: the date gate is
    legally load-bearing and needs to be right.
    """
    month_str, year_str = tax_period.split("/")
    return (int(year_str), int(month_str))


def _financial_year_end(tax_period: str) -> tuple[int, int, int]:
    """The 30 November time-bar deadline for an invoice's tax period.

    Indian FY runs April-March. An invoice in Apr-Dec belongs to the FY
    ending the following March; an invoice in Jan-Mar belongs to the FY
    ending that same March. The Section 16(4) deadline (simplified, see
    section_16_4.yaml) is 30 November of the calendar year the FY ends in.
    """
    year, month = _period_key(tax_period)
    fy_end_year = year + 1 if month >= 4 else year
    return (fy_end_year, 11, 30)


def _evaluate_condition(cond: RuleCondition, facts: InvoiceFacts) -> bool:
    """True if the condition is satisfied (rule passes); False if it should
    trigger the rule's on_fail outcome."""
    if cond.kind == "field_equals":
        if cond.field is None:
            raise ValueError("field_equals condition must specify 'field'")
        actual = getattr(facts, cond.field)
        return bool(actual == cond.value)

    if cond.kind == "time_bar":
        deadline_year, month, day = _financial_year_end(facts.tax_period)
        deadline = date(
            deadline_year, cond.deadline_month or month, cond.deadline_day or day
        )
        return facts.as_of_date <= deadline

    if cond.kind == "keyword_block":
        description_lower = facts.item_description_clean.lower()
        keywords = cond.blocked_keywords or []
        return not any(kw.lower() in description_lower for kw in keywords)

    raise ValueError(f"unknown condition kind: {cond.kind!r}")


def _render(template: str, facts: InvoiceFacts) -> str:
    """Render a YAML reason template against InvoiceFacts + computed extras."""
    context = facts.model_dump(mode="json")
    return template.format(**context)


def _rule_passes(spec: RuleSpec, facts: InvoiceFacts) -> bool:
    return all(_evaluate_condition(cond, facts) for cond in spec.conditions)


def _catalogue_evaluate(facts: InvoiceFacts, catalogue: RuleCatalogue) -> Verdict:
    """Steps 1-8: the date-unaware base evaluation. Always produces
    PROVISIONAL (never INELIGIBLE) when an invoice is simply absent from
    GSTR-2B -- the 01.01.2022 date-gate override is applied afterwards by
    evaluate(), not here."""
    reason_chain: list[ReasonStep] = []

    for rule_id in EVALUATION_ORDER:
        spec = catalogue.rules[rule_id]
        passed = _rule_passes(spec, facts)

        if passed:
            reason_chain.append(
                ReasonStep(
                    rule_id=spec.rule_id,
                    section=spec.section,
                    passed=True,
                    message=f"{spec.section}: satisfied.",
                )
            )
            continue

        # Short-circuit: this rule failed, return immediately.
        on_fail = spec.on_fail
        if on_fail is None:
            raise ValueError(f"rule {spec.rule_id} failed but has no on_fail spec")
        reason_chain.append(
            ReasonStep(
                rule_id=spec.rule_id,
                section=spec.section,
                passed=False,
                message=_render(on_fail.reason, facts),
            )
        )
        return Verdict(
            verdict=VerdictType(on_fail.verdict),
            reason_chain=reason_chain,
            catalogue_version=catalogue.version,
        )

    # All rules in EVALUATION_ORDER passed, including section_16_2_d
    # (present_in_gstr2b == True) -> step 8, eligible.
    reason_chain.append(
        ReasonStep(
            rule_id="all_conditions_met",
            section="Section 16(2)/(4)/17(5) CGST Act 2017",
            passed=True,
            message="All eligibility conditions satisfied.",
        )
    )
    return Verdict(
        verdict=VerdictType.ELIGIBLE,
        reason_chain=reason_chain,
        catalogue_version=catalogue.version,
    )


def evaluate(facts: InvoiceFacts, catalogue: RuleCatalogue) -> Verdict:
    """Apply CGST rules to facts and return a verdict.

    CRITICAL: If the result is provisional and facts.tax_period >=
    01/2022, override to ineligible (Rule 36(4) abolished post-01.01.2022).
    """
    base_verdict = _catalogue_evaluate(facts, catalogue)  # Steps 1-8 above

    # Legal constraint: provisional ITC abolished 01.01.2022
    if (
        base_verdict.verdict == VerdictType.PROVISIONAL
        and _period_key(facts.tax_period) >= DATE_GATE_EFFECTIVE_PERIOD
    ):
        date_gate_spec = catalogue.rules["rule_36_4_date_gate"]
        if date_gate_spec.reason is None:
            raise ValueError("rule_36_4_date_gate is missing its 'reason' template")
        return Verdict(
            verdict=VerdictType.INELIGIBLE,
            reason_chain=[
                *base_verdict.reason_chain,
                ReasonStep(
                    rule_id="rule_36_4_date_gate",
                    section=date_gate_spec.section,
                    passed=False,
                    message=_render(date_gate_spec.reason, facts),
                ),
            ],
            catalogue_version=base_verdict.catalogue_version,
        )

    return base_verdict
