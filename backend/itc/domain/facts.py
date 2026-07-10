"""InvoiceFacts -- the validated facts the Rule Engine consumes.
 
Per 02_LLD_ITC_Recovery_Agent (section 2, domain/facts.py). Built by
Layer 1 (extraction/resolution/matching); consumed as a pure input by
Layer 2 (rules/engine.py). Field list and validation constraints are
copied verbatim from the LLD -- this file does not add or remove fields.
"""
 
from __future__ import annotations
 
from datetime import date
 
from pydantic import BaseModel, Field
 
GSTIN_RE = r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$"
 
 
class MatchResult(BaseModel):
    """Outcome of matching one purchase-register row against GSTR-2B.
 
    Per the LLD (intelligence/matcher.py), the real implementation does
    FAISS top-5 retrieval + LLM re-rank (SentenceTransformer embeddings,
    confidence scoring). That layer isn't built yet -- this POC's
    Reconciliation Agent (agents/reconciliation.py) populates this via
    deterministic (vendor_gstin, invoice_number) matching instead, with a
    fuzzy invoice-number fallback. `method` records which path was used so
    it's never ambiguous which matcher actually ran.
    """
 
    matched_gstr2b_invoice_number: str | None
    confidence: str  # "exact" | "fuzzy" | "no_match" (real matcher adds LLM confidence bands)
    method: str  # "exact_key" | "fuzzy_invoice_number" | "faiss_llm_rerank" (not yet implemented)
    match_score: float | None = None  # similarity score, when fuzzy/FAISS
 
 
class InvoiceFacts(BaseModel):
    """The validated facts the Rule Engine consumes. Built by Layer 1."""
 
    tenant_id: str
    item_description_clean: str
    quantity: float | None = None
    unit: str | None = None
    vendor_gstin: str = Field(pattern=GSTIN_RE)
    taxable_amount_inr: float = Field(gt=0)
    gst_amount_inr: float = Field(ge=0)
    tax_period: str = Field(pattern=r"^(0[1-9]|1[0-2])/[0-9]{4}$")  # MM/YYYY
 
    # match outcome, set by the matcher:
    present_in_gstr2b: bool
    supplier_filed_gstr1: bool
    buyer_is_registered: bool = True
    goods_received: bool = True
    as_of_date: date  # supplied by the caller, NOT datetime.now() inside the engine
 