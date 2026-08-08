# This is ingestion/gstr2b.py
"""Parse and validate GSTR-2B JSON uploads.

Per 02_LLD_ITC_Recovery_Agent (section 6):
    def parse_gstr2b(file_bytes) -> list[Gstr2bEntry]:
        '''Validate top-level gstin/fp/data.b2b[]. Row-level validation.
        Collect ALL errors, then reject the whole file if any (no partial
        commit).'''

`Gstr2bEntry` is not specified field-by-field in the LLD -- this module
defines it. GSTR-2B's real schema nests invoices under suppliers
(data.b2b[].inv[].itms[]); Gstr2bEntry flattens that to one entry per
invoice (aggregating its itms[] line items), since every downstream Rule
Engine check (Section 16(2), 16(4), 17(5), 36(4)) operates at
invoice/tax-period granularity, not per-tax-rate-line granularity.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime

from pydantic import BaseModel, Field, ValidationError

GSTIN_RE = r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$"
VALID_TAX_RATES = {0, 5, 12, 18, 28}


class Gstr2bEntry(BaseModel):
    """One government-filed invoice, flattened from GSTR-2B's supplier/inv/itms nesting."""

    tenant_gstin: str = Field(pattern=GSTIN_RE)
    tax_period: str  # MM/YYYY, normalised from GSTR-2B's raw MMYYYY "fp"
    supplier_gstin: str = Field(pattern=GSTIN_RE)
    supplier_trade_name: str
    supplier_filed_date: date
    invoice_number: str = Field(min_length=1, max_length=16)
    invoice_date: date
    invoice_value: float = Field(ge=0)
    taxable_value: float = Field(ge=0)
    tax_amount: float = Field(ge=0)
    place_of_supply: str
    itc_available: bool
    reverse_charge: bool


class Gstr2bValidationError(Exception):
    """Raised when any row in a GSTR-2B upload fails validation.

    Carries every error found (not just the first), per the LLD's "collect
    ALL errors, then reject the whole file if any (no partial commit)"
    requirement -- callers get a complete error report in one pass rather
    than fixing errors one upload attempt at a time.
    """

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(f"{len(errors)} validation error(s) in GSTR-2B upload")


def _parse_ddmmyyyy(raw: str) -> date:
    return datetime.strptime(raw, "%d-%m-%Y").date()


def _fp_to_tax_period(fp: str) -> str:
    """MMYYYY -> MM/YYYY. Raises ValueError if not a valid 6-digit period."""
    if len(fp) != 6 or not fp.isdigit():
        raise ValueError(f"fp must be MMYYYY, got {fp!r}")
    month, year = fp[:2], fp[2:]
    if not (1 <= int(month) <= 12):
        raise ValueError(f"invalid month in fp {fp!r}")
    return f"{month}/{year}"


def parse_gstr2b(file_bytes: bytes) -> list[Gstr2bEntry]:
    """Validate top-level gstin/fp/data.b2b[], then row-level per invoice.

    Collects every error across the whole file before deciding whether to
    reject it -- a caller sees all problems in a single pass, and either
    gets a complete, valid list of entries or nothing at all (no partial
    commit of some-but-not-all invoices).
    """
    errors: list[str] = []

    try:
        raw = json.loads(file_bytes)
    except json.JSONDecodeError as exc:
        raise Gstr2bValidationError([f"file is not valid JSON: {exc}"]) from exc

    tenant_gstin = raw.get("gstin")
    if not tenant_gstin or not re.match(GSTIN_RE, str(tenant_gstin)):
        errors.append(f"top-level 'gstin' missing or invalid: {tenant_gstin!r}")

    fp = raw.get("fp")
    tax_period: str | None = None
    if not fp:
        errors.append("top-level 'fp' (tax period) is missing")
    else:
        try:
            tax_period = _fp_to_tax_period(str(fp))
        except ValueError as exc:
            errors.append(f"top-level 'fp' invalid: {exc}")

    b2b = raw.get("data", {}).get("b2b")
    if not isinstance(b2b, list):
        errors.append("'data.b2b' missing or not a list")
        b2b = []

    entries: list[Gstr2bEntry] = []

    for supplier_idx, supplier in enumerate(b2b):
        ctin = supplier.get("ctin")
        trdnm = supplier.get("trdnm")
        supfildt_raw = supplier.get("supfildt")
        supplier_ctx = f"b2b[{supplier_idx}] (ctin={ctin!r})"

        supplier_ctin_valid = bool(ctin) and bool(re.match(GSTIN_RE, str(ctin)))

        if not ctin or not supplier_ctin_valid:
            errors.append(f"{supplier_ctx}: invalid or missing supplier GSTIN")
        if not trdnm:
            errors.append(f"{supplier_ctx}: missing supplier trade name")

        try:
            supfildt = _parse_ddmmyyyy(supfildt_raw) if supfildt_raw else None
            if supfildt is None:
                errors.append(f"{supplier_ctx}: missing supplier filing date")
        except ValueError:
            errors.append(f"{supplier_ctx}: invalid supfildt {supfildt_raw!r}")
            supfildt = None

        invoices = supplier.get("inv")
        if not isinstance(invoices, list):
            errors.append(f"{supplier_ctx}: 'inv' missing or not a list")
            continue

        for inv_idx, inv in enumerate(invoices):
            inv_ctx = f"{supplier_ctx}.inv[{inv_idx}] (inum={inv.get('inum')!r})"

            inum = inv.get("inum")
            if not inum or len(str(inum)) > 16:
                errors.append(f"{inv_ctx}: invoice number missing or >16 chars")

            try:
                idt = _parse_ddmmyyyy(inv.get("idt", ""))
            except ValueError:
                errors.append(f"{inv_ctx}: invalid invoice date {inv.get('idt')!r}")
                idt = None

            itms = inv.get("itms")
            if not isinstance(itms, list) or not itms:
                errors.append(f"{inv_ctx}: 'itms' missing or empty")
                itms = []

            taxable_value = 0.0
            tax_amount = 0.0
            for item_idx, item in enumerate(itms):
                rate = item.get("rt")
                if rate not in VALID_TAX_RATES:
                    errors.append(
                        f"{inv_ctx}.itms[{item_idx}]: invalid tax rate {rate!r}"
                    )
                txval = item.get("txval", 0)
                if not isinstance(txval, (int, float)) or txval < 0:
                    errors.append(
                        f"{inv_ctx}.itms[{item_idx}]: invalid taxable value {txval!r}"
                    )
                    txval = 0
                taxable_value += float(txval)
                tax_amount += float(item.get("iamt", 0) or 0)
                tax_amount += float(item.get("camt", 0) or 0)
                tax_amount += float(item.get("samt", 0) or 0)
                tax_amount += float(item.get("csamt", 0) or 0)

            # Skip building an entry object if this invoice already has
            # errors, or its supplier's GSTIN is invalid -- there's no
            # valid data to construct one from, and the file is being
            # rejected as a whole anyway if any errors exist at the end.
            if not supplier_ctin_valid:
                continue
            if errors and errors[-1].startswith(inv_ctx):
                continue
            if supfildt is None or idt is None:
                continue

            try:
                entries.append(
                    Gstr2bEntry(
                        tenant_gstin=tenant_gstin,
                        tax_period=tax_period or "",
                        supplier_gstin=ctin,
                        supplier_trade_name=trdnm,
                        supplier_filed_date=supfildt,
                        invoice_number=str(inum),
                        invoice_date=idt,
                        invoice_value=float(inv.get("val", 0)),
                        taxable_value=round(taxable_value, 2),
                        tax_amount=round(tax_amount, 2),
                        place_of_supply=str(inv.get("pos", "")),
                        itc_available=str(inv.get("itcavl", "N")).upper() == "Y",
                        reverse_charge=str(inv.get("rev", "N")).upper() == "Y",
                    )
                )
            except ValidationError as exc:
                errors.append(f"{inv_ctx}: {exc}")

    if errors:
        raise Gstr2bValidationError(errors)

    return entries
