"""Deterministic reconciliation rules for GST purchase invoices."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class ReconciliationStatus(StrEnum):
    """Possible outcomes when matching a purchase invoice to supplier data."""

    MATCHED = "matched"
    MISMATCHED = "mismatched"
    MISSING_SUPPLIER_RETURN = "missing_supplier_return"


@dataclass(frozen=True, slots=True)
class Invoice:
    """Minimal invoice fields needed for deterministic ITC matching."""

    invoice_number: str
    supplier_gstin: str
    taxable_value: Decimal
    tax_value: Decimal


@dataclass(frozen=True, slots=True)
class MatchResult:
    """Reconciliation outcome plus field-level reasons for audit trails."""

    status: ReconciliationStatus
    reasons: tuple[str, ...]

    @property
    def is_claimable(self) -> bool:
        """Return whether ITC can be claimed for the matched invoice."""
        return self.status is ReconciliationStatus.MATCHED


def reconcile_invoice(
    purchase_invoice: Invoice,
    supplier_return: Invoice | None,
    *,
    amount_tolerance: Decimal = Decimal("1.00"),
) -> MatchResult:
    """Reconcile one purchase invoice against supplier return data.

    The comparison is deterministic and auditable: invoice number and supplier GSTIN
    must match exactly after normalization, while amount fields may differ within the
    configured absolute tolerance.
    """
    if amount_tolerance < Decimal("0.00"):
        msg = "amount_tolerance must be non-negative"
        raise ValueError(msg)

    if supplier_return is None:
        return MatchResult(
            status=ReconciliationStatus.MISSING_SUPPLIER_RETURN,
            reasons=("supplier_return_missing",),
        )

    reasons: list[str] = []

    if _normalize_invoice_number(purchase_invoice.invoice_number) != _normalize_invoice_number(
        supplier_return.invoice_number
    ):
        reasons.append("invoice_number_mismatch")

    if _normalize_gstin(purchase_invoice.supplier_gstin) != _normalize_gstin(
        supplier_return.supplier_gstin
    ):
        reasons.append("supplier_gstin_mismatch")

    if _is_outside_tolerance(
        purchase_invoice.taxable_value,
        supplier_return.taxable_value,
        amount_tolerance,
    ):
        reasons.append("taxable_value_mismatch")

    if _is_outside_tolerance(
        purchase_invoice.tax_value,
        supplier_return.tax_value,
        amount_tolerance,
    ):
        reasons.append("tax_value_mismatch")

    if reasons:
        return MatchResult(status=ReconciliationStatus.MISMATCHED, reasons=tuple(reasons))

    return MatchResult(status=ReconciliationStatus.MATCHED, reasons=("all_fields_matched",))


def _normalize_invoice_number(value: str) -> str:
    return value.strip().upper()


def _normalize_gstin(value: str) -> str:
    return value.strip().upper()


def _is_outside_tolerance(left: Decimal, right: Decimal, tolerance: Decimal) -> bool:
    return abs(left - right) > tolerance
