"""Outreach Agent -- Layer 3. Drafts vendor emails from ReconciliationCases.
NEVER sends anything. Per the HLD: human approval gate is mandatory before
any email leaves the system.
"""

from __future__ import annotations

from datetime import UTC, datetime

from itc.agents.reconciliation import ReconciliationCase
from itc.domain.outreach import EmailDraft, OutreachDraft
from itc.intelligence.gateway import AbstractLLMGateway
from itc.intelligence.schemas import VendorEmailDraft


def draft_outreach(
    case: ReconciliationCase, gateway: AbstractLLMGateway
) -> OutreachDraft:
    """Draft one vendor email for a flagged case. The LLM sees the verdict
    and reason chain as fixed, already-decided input -- it explains/asks,
    it does not re-derive eligibility."""
    result = gateway.call(
        task="draft_vendor_email",
        context={
            "vendor_name": case.vendor_name,
            "invoice_number": case.invoice_number,
            "tax_period": case.tax_period,
            "verdict": case.verdict.verdict.value,
            "reason_chain": [step.message for step in case.verdict.reason_chain],
            "taxable_amount_inr": case.taxable_amount_inr,
            "gst_amount_inr": case.gst_amount_inr,
        },
        tenant_id=case.tenant_id,
        response_schema=VendorEmailDraft,
    )

    return OutreachDraft(
        tenant_id=case.tenant_id,
        vendor_gstin=case.vendor_gstin,
        vendor_name=case.vendor_name,
        invoice_number=case.invoice_number,
        email=EmailDraft(subject=result.subject, body=result.body),
        created_at=datetime.now(UTC),
    )


def draft_outreach_batch(
    cases: list[ReconciliationCase], gateway: AbstractLLMGateway
) -> list[OutreachDraft]:
    """Draft emails for every case in a list. One gateway instance should
    be reused across the batch so gateway.traces accumulates a full audit
    log of every LLM call made in this run."""
    return [draft_outreach(case, gateway) for case in cases]
