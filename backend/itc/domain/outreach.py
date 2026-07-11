"""Outreach domain models -- Layer 3 (Outreach Agent).

Per the HLD: the Outreach Agent drafts vendor emails only. A human must
approve and send manually. This module intentionally has no `send()`
method or SMTP integration -- that would violate the mandatory human
approval gate documented in the HLD's "what the LLM is never allowed to
do" list.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class EmailDraft(BaseModel):
    """The LLM's output. Nothing more than subject + body -- the LLM does
    not decide recipients, timing, or whether to send."""

    subject: str
    body: str


class OutreachDraft(BaseModel):
    """One drafted outreach item, tied back to the ReconciliationCase it
    was generated from. status is always 'pending_approval' at creation --
    there is no code path in this module that can set it to 'sent'."""

    tenant_id: str
    vendor_gstin: str
    vendor_name: str
    invoice_number: str
    email: EmailDraft
    status: str = "pending_approval"
    created_at: datetime
