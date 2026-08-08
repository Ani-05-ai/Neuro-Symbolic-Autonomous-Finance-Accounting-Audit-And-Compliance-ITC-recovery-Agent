"""Pydantic schemas the LLMGateway validates responses against.

Per AbstractLLMGateway.call()'s contract, response_schema must be a
BaseModel subclass and the gateway returns a validated instance of it.
Each schema here corresponds to one `task` string used in gateway.call().
"""

from pydantic import BaseModel


class VerdictExplanation(BaseModel):
    """task='explain_verdict' -- plain-English narration of an
    already-decided Rule Engine verdict. The LLM never sees this used to
    produce a decision, only to explain one that already exists."""

    explanation: str


class VendorEmailDraft(BaseModel):
    """task='draft_vendor_email' -- a drafted outreach email for a
    flagged case. Kept separate from domain/outreach.py's EmailDraft:
    this is the LLM-response validation contract, EmailDraft is the
    domain object it gets converted into. The two happen to have
    identical fields right now -- that's coincidental, not a reason to
    merge them."""

    subject: str
    body: str
