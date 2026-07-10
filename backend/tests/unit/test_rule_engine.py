"""Rule Engine test suite -- covers every TDD contract bullet from
02_LLD_ITC_Recovery_Agent (section 3):
 
# TEST: blocked beats everything -- a 17(5) item that is also time-barred returns `blocked`
# TEST: time-bar -- as_of_date after deadline returns `time_barred` with correct reason
# TEST: 16(2)(c) -- supplier_filed_gstr1=False returns `ineligible`, reason names GSTIN + period
# TEST: provisional (pre-2022) -- tax_period < 01/2022, not in GSTR-2B, within Rule 36(4) limit -> `provisional`
# TEST: ineligible (post-2022 date gate) -- tax_period >= 01/2022, not in GSTR-2B -> `ineligible` (override active, not provisional)
# TEST: date gate override appends "Notif 40/2021-CT" to reason_chain
# TEST: all conditions met returns `eligible`
# TEST: determinism -- same facts + version called 100x returns byte-identical Verdict
# TEST: reason template renders {vendor_gstin}/{tax_period} from facts
"""
 
from __future__ import annotations
 
import sys
from datetime import date
from pathlib import Path
 
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
 
from domain.facts import InvoiceFacts
from domain.verdict import VerdictType
from rules.engine import evaluate
from rules.loader import load_catalogue
 
CATALOGUE = load_catalogue(str(Path(__file__).resolve().parent.parent / "rules" / "catalogue"))
 
 
def make_facts(**overrides) -> InvoiceFacts:
    """A fully-compliant baseline InvoiceFacts; override individual fields per test."""
    defaults = dict(
        tenant_id="tenant_a",
        item_description_clean="HDPE Granules 20kg",
        vendor_gstin="27ABCDE1234F1Z5",
        taxable_amount_inr=10000.0,
        gst_amount_inr=1800.0,
        tax_period="03/2025",
        present_in_gstr2b=True,
        supplier_filed_gstr1=True,
        buyer_is_registered=True,
        goods_received=True,
        as_of_date=date(2025, 6, 1),
    )
    defaults.update(overrides)
    return InvoiceFacts(**defaults)
 
 
def test_blocked_beats_everything():
    """A 17(5) item that is ALSO time-barred should return blocked, not time_barred."""
    facts = make_facts(
        item_description_clean="Motor Vehicle Purchase - Company Car",
        tax_period="03/2020",  # long past its 16(4) deadline too
        as_of_date=date(2025, 6, 1),
    )
    verdict = evaluate(facts, CATALOGUE)
    assert verdict.verdict == VerdictType.BLOCKED
    assert verdict.reason_chain[0].rule_id == "section_17_5_blocked"
    print("PASS: blocked beats everything")
 
 
def test_time_bar_returns_time_barred_with_correct_reason():
    facts = make_facts(
        tax_period="03/2023",  # FY2022-23 -> deadline 30 Nov 2023
        as_of_date=date(2024, 1, 1),  # after the deadline
    )
    verdict = evaluate(facts, CATALOGUE)
    assert verdict.verdict == VerdictType.TIME_BARRED
    reason = verdict.reason_chain[-1].message
    assert "16(4)" in verdict.reason_chain[-1].section or "time-barred" in reason
    assert "03/2023" in reason
    print("PASS: time-bar returns time_barred with correct reason")
 
 
def test_section_16_2_c_supplier_not_filed():
    facts = make_facts(supplier_filed_gstr1=False, vendor_gstin="29XYZAB5678C1Z9")
    verdict = evaluate(facts, CATALOGUE)
    assert verdict.verdict == VerdictType.INELIGIBLE
    reason = verdict.reason_chain[-1].message
    assert "29XYZAB5678C1Z9" in reason
    assert "03/2025" in reason
    print("PASS: 16(2)(c) supplier_filed_gstr1=False -> ineligible, names GSTIN + period")
 
 
def test_provisional_pre_2022():
    facts = make_facts(
        tax_period="03/2021",  # pre-01/2022 -> date gate does not apply
        present_in_gstr2b=False,
        as_of_date=date(2021, 6, 1),  # within the 16(4) window (FY2020-21 -> 30 Nov 2021)
    )
    verdict = evaluate(facts, CATALOGUE)
    assert verdict.verdict == VerdictType.PROVISIONAL
    print("PASS: provisional (pre-2022, not in GSTR-2B, within 36(4) limit)")
 
 
def test_ineligible_post_2022_date_gate():
    facts = make_facts(
        tax_period="03/2025",  # >= 01/2022 -> date gate active
        present_in_gstr2b=False,
        as_of_date=date(2025, 6, 1),  # within the 16(4) window
    )
    verdict = evaluate(facts, CATALOGUE)
    assert verdict.verdict == VerdictType.INELIGIBLE
    print("PASS: ineligible (post-2022 date gate active, not provisional)")
 
 
def test_date_gate_override_appends_notif_reference():
    facts = make_facts(tax_period="03/2025", present_in_gstr2b=False, as_of_date=date(2025, 6, 1))
    verdict = evaluate(facts, CATALOGUE)
    assert any("40/2021-CT" in step.message for step in verdict.reason_chain)
    assert verdict.reason_chain[-1].rule_id == "rule_36_4_date_gate"
    print('PASS: date gate override appends "Notif 40/2021-CT" to reason_chain')
 
 
def test_all_conditions_met_returns_eligible():
    facts = make_facts()  # fully compliant baseline
    verdict = evaluate(facts, CATALOGUE)
    assert verdict.verdict == VerdictType.ELIGIBLE
    assert all(step.passed for step in verdict.reason_chain)
    print("PASS: all conditions met -> eligible")
 
 
def test_determinism_100x():
    facts = make_facts()
    verdicts = [evaluate(facts, CATALOGUE) for _ in range(100)]
    first = verdicts[0].model_dump_json()
    assert all(v.model_dump_json() == first for v in verdicts)
    print("PASS: determinism -- 100x identical Verdict")
 
 
def test_reason_template_renders_gstin_and_period():
    facts = make_facts(supplier_filed_gstr1=False, vendor_gstin="33MNOPQ4321R1Z2", tax_period="07/2025")
    verdict = evaluate(facts, CATALOGUE)
    reason = verdict.reason_chain[-1].message
    assert "33MNOPQ4321R1Z2" in reason
    assert "07/2025" in reason
    assert "{vendor_gstin}" not in reason  # template placeholder must be rendered, not literal
    assert "{tax_period}" not in reason
    print("PASS: reason template renders {vendor_gstin}/{tax_period} from facts")
 
 
if __name__ == "__main__":
    test_blocked_beats_everything()
    test_time_bar_returns_time_barred_with_correct_reason()
    test_section_16_2_c_supplier_not_filed()
    test_provisional_pre_2022()
    test_ineligible_post_2022_date_gate()
    test_date_gate_override_appends_notif_reference()
    test_all_conditions_met_returns_eligible()
    test_determinism_100x()
    test_reason_template_renders_gstin_and_period()
    print()
    print("ALL 9 TDD CONTRACT TESTS PASSED")
 