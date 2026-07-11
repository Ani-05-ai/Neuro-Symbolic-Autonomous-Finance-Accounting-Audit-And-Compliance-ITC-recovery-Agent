"""Reconciliation Agent -- Layer 3. A thin orchestrator: it never makes an
eligibility decision itself, only calls the Rule Engine and acts on the
verdict.

Per 02_LLD_ITC_Recovery_Agent (section 5.1):
    @app.task(bind=True)
    def reconcile(self, tenant_id, gstr2b_id, register_id):
        for row in load_register(tenant_id, register_id):
            facts = build_facts(extract(row), resolve(...), match(...))  # Layer 1
            verdict = evaluate(facts, load_catalogue())                  # Layer 2
            audit(tenant_id, extraction, match, verdict)                 # all three
            if verdict.verdict != "eligible":
                cases_repo.create(Case.from_(facts, verdict))
    # TEST (architectural): no path creates a Case without a Verdict object
    # TEST: idempotency -- re-running with the same inputs yields the same cases + one audit set

DOCUMENTED SCOPE CUT: the real Layer 1 (intelligence/extractor.py,
resolver.py, matcher.py) does LLM-based extraction, vendor-name
resolution, and FAISS-retrieve + LLM-rerank matching -- none of which are
built yet (the LLMGateway is still a stub). This module's `match_invoice`
function is a deterministic stand-in: exact (vendor_gstin, invoice_number)
key match, falling back to fuzzy invoice-number matching within the same
vendor_gstin for typo'd/reformatted invoice numbers. This is a real
simplification, not a secret one -- it works because this system's
synthetic (and most real) purchase registers already carry the correct
vendor_gstin per row, so semantic matching on free-text descriptions
isn't actually load-bearing for the exact/fuzzy-key cases it covers. It
will NOT catch cases where the vendor_gstin itself was mistyped -- that
genuinely needs the FAISS/LLM matcher this module is standing in for.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from datetime import date

from itc.domain.facts import InvoiceFacts, MatchResult
from itc.domain.verdict import Verdict
from itc.ingestion.gstr2b import Gstr2bEntry
from itc.ingestion.purchase_register import RawRow
from itc.rules.engine import evaluate
from itc.rules.loader import RuleCatalogue

FUZZY_MATCH_THRESHOLD = 0.85  # difflib ratio; below this, treated as no_match


@dataclass
class ReconciliationCase:
    """Stand-in for the eventual `Case` domain model (domain/case.py) +
    DB persistence (cases_repo.create). Kept here rather than importing a
    not-yet-built Case model, so this Agent has a real, usable return
    value now rather than depending on unbuilt DB plumbing."""

    tenant_id: str
    vendor_gstin: str
    invoice_number: str
    tax_period: str
    taxable_amount_inr: float
    gst_amount_inr: float
    match_result: MatchResult
    facts: InvoiceFacts
    verdict: Verdict


def match_invoice(
    row: RawRow, gstr2b_by_vendor: dict[str, list[Gstr2bEntry]]
) -> MatchResult:
    """Deterministic stand-in for intelligence/matcher.py (see module
    docstring). Tries an exact (vendor_gstin, invoice_number) key match
    first, then a fuzzy invoice-number match within the same vendor_gstin.
    """
    candidates = gstr2b_by_vendor.get(row.vendor_gstin, [])

    for entry in candidates:
        if entry.invoice_number == row.invoice_number:
            return MatchResult(
                matched_gstr2b_invoice_number=entry.invoice_number,
                confidence="exact",
                method="exact_key",
                match_score=1.0,
            )

    best_score = 0.0
    best_entry: Gstr2bEntry | None = None
    for entry in candidates:
        score = difflib.SequenceMatcher(
            None, row.invoice_number, entry.invoice_number
        ).ratio()
        if score > best_score:
            best_score = score
            best_entry = entry

    if best_entry is not None and best_score >= FUZZY_MATCH_THRESHOLD:
        return MatchResult(
            matched_gstr2b_invoice_number=best_entry.invoice_number,
            confidence="fuzzy",
            method="fuzzy_invoice_number",
            match_score=round(best_score, 3),
        )

    return MatchResult(
        matched_gstr2b_invoice_number=None,
        confidence="no_match",
        method="exact_key",  # no candidate crossed the fuzzy threshold either
        match_score=best_score if best_entry is not None else None,
    )


def build_facts(
    tenant_id: str,
    row: RawRow,
    match_result: MatchResult,
    gstr2b_by_vendor: dict[str, list[Gstr2bEntry]],
    as_of_date: date,
) -> InvoiceFacts:
    """Layer 1 stand-in: combine the purchase register row + match outcome
    into InvoiceFacts. supplier_filed_gstr1 is set independently of
    present_in_gstr2b -- a vendor can have filed other invoices (proving
    they're a real, compliant supplier) while THIS specific invoice is
    still missing, which is exactly the case Rule 36(4)/date-gate exists
    to evaluate. If the vendor has no presence in GSTR-2B at all, they
    have not filed for this period.
    """
    present_in_gstr2b = match_result.matched_gstr2b_invoice_number is not None
    supplier_has_any_filing = row.vendor_gstin in gstr2b_by_vendor

    return InvoiceFacts(
        tenant_id=tenant_id,
        item_description_clean=row.item_description,
        vendor_gstin=row.vendor_gstin,
        taxable_amount_inr=row.taxable_amount,
        gst_amount_inr=row.gst_amount,
        tax_period=row.tax_period,
        present_in_gstr2b=present_in_gstr2b,
        supplier_filed_gstr1=supplier_has_any_filing,
        as_of_date=as_of_date,
    )


def reconcile(
    tenant_id: str,
    gstr2b_entries: list[Gstr2bEntry],
    register_rows: list[RawRow],
    catalogue: RuleCatalogue,
    as_of_date: date,
) -> list[ReconciliationCase]:
    """Match every purchase register row against GSTR-2B, evaluate each
    against the Rule Engine, and return a Case for every non-eligible
    verdict.

    Pure given its inputs (no I/O, no DB, no Celery) -- audit(...) and
    cases_repo.create(...) from the LLD's illustrative code are left to
    the caller (the real Celery task wrapper), which is what makes this
    function itself trivially idempotent: same inputs always produce the
    same case list, satisfying the LLD's idempotency test architecturally
    rather than needing a database to prove it.
    """
    gstr2b_by_vendor: dict[str, list[Gstr2bEntry]] = {}
    for entry in gstr2b_entries:
        gstr2b_by_vendor.setdefault(entry.supplier_gstin, []).append(entry)

    cases: list[ReconciliationCase] = []

    for row in register_rows:
        match_result = match_invoice(row, gstr2b_by_vendor)
        facts = build_facts(tenant_id, row, match_result, gstr2b_by_vendor, as_of_date)

        verdict = evaluate(facts, catalogue)  # Layer 2 -- the only place a decision is made

        # TEST (architectural): no path creates a Case without a Verdict object --
        # verdict is computed unconditionally above, for every row, before this check.
        if verdict.verdict.value != "eligible":
            cases.append(
                ReconciliationCase(
                    tenant_id=tenant_id,
                    vendor_gstin=row.vendor_gstin,
                    invoice_number=row.invoice_number,
                    tax_period=row.tax_period,
                    taxable_amount_inr=row.taxable_amount,
                    gst_amount_inr=row.gst_amount,
                    match_result=match_result,
                    facts=facts,
                    verdict=verdict,
                )
            )

    return cases
