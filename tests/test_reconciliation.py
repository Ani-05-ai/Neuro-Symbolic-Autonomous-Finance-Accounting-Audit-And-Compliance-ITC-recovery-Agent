from decimal import Decimal

import pytest

from recoveritc import Invoice, ReconciliationStatus, reconcile_invoice


def make_invoice(
    *,
    invoice_number: str = "INV-001",
    supplier_gstin: str = "27ABCDE1234F1Z5",
    taxable_value: Decimal = Decimal("1000.00"),
    tax_value: Decimal = Decimal("180.00"),
) -> Invoice:
    return Invoice(
        invoice_number=invoice_number,
        supplier_gstin=supplier_gstin,
        taxable_value=taxable_value,
        tax_value=tax_value,
    )


def test_reconcile_invoice_matches_normalized_fields_within_tolerance() -> None:
    purchase_invoice = make_invoice(invoice_number=" inv-001 ")
    supplier_return = make_invoice(tax_value=Decimal("180.75"))

    result = reconcile_invoice(purchase_invoice, supplier_return)

    assert result.status is ReconciliationStatus.MATCHED
    assert result.reasons == ("all_fields_matched",)
    assert result.is_claimable is True


def test_reconcile_invoice_flags_missing_supplier_return() -> None:
    result = reconcile_invoice(make_invoice(), None)

    assert result.status is ReconciliationStatus.MISSING_SUPPLIER_RETURN
    assert result.reasons == ("supplier_return_missing",)
    assert result.is_claimable is False


def test_reconcile_invoice_reports_field_level_mismatches() -> None:
    purchase_invoice = make_invoice()
    supplier_return = make_invoice(
        invoice_number="INV-999",
        supplier_gstin="29ABCDE1234F1Z5",
        taxable_value=Decimal("900.00"),
        tax_value=Decimal("150.00"),
    )

    result = reconcile_invoice(purchase_invoice, supplier_return)

    assert result.status is ReconciliationStatus.MISMATCHED
    assert result.reasons == (
        "invoice_number_mismatch",
        "supplier_gstin_mismatch",
        "taxable_value_mismatch",
        "tax_value_mismatch",
    )
    assert result.is_claimable is False


def test_reconcile_invoice_respects_custom_amount_tolerance() -> None:
    purchase_invoice = make_invoice(taxable_value=Decimal("1000.00"))
    supplier_return = make_invoice(taxable_value=Decimal("1002.00"))

    result = reconcile_invoice(
        purchase_invoice,
        supplier_return,
        amount_tolerance=Decimal("2.00"),
    )

    assert result.status is ReconciliationStatus.MATCHED


def test_reconcile_invoice_rejects_negative_tolerance() -> None:
    with pytest.raises(ValueError, match="amount_tolerance must be non-negative"):
        reconcile_invoice(
            make_invoice(),
            make_invoice(),
            amount_tolerance=Decimal("-0.01"),
        )
