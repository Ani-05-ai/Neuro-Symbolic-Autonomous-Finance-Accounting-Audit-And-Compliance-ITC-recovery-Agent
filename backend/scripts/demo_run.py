# scripts/demo_run.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from datetime import date

from itc.ingestion.gstr2b import parse_gstr2b
from itc.ingestion.purchase_register import parse_register, mapping_from_tenant_profile
from itc.rules.loader import load_catalogue
from itc.agents.reconciliation import reconcile
from itc.intelligence.ollama_gateway import OllamaLLMGateway
from itc.intelligence.schemas import VerdictExplanation

catalogue = load_catalogue("itc/rules/catalogue")
gstr2b_entries = parse_gstr2b(open("fixtures/gstr2b_tenant_a_062026.json", "rb").read())
mapping = mapping_from_tenant_profile("tenant_a", {
    "vendor_name": "Party Name",
    "vendor_gstin": "Party GSTIN",
    "invoice_number": "Voucher No",
    "invoice_date": "Voucher Date",
    "item_description": "Item Name",
    "taxable_amount": "Taxable Value",
    "gst_amount": "GST Amount",
    "tax_period": "Period",
})
register = parse_register(open("fixtures/purchase_register_tenant_a.xlsx", "rb").read(), mapping)

cases = reconcile("tenant_a", gstr2b_entries, register.rows, catalogue, as_of_date=date.today())

gateway = OllamaLLMGateway()

for case in cases:
    print(f"\n{case.invoice_number} → {case.verdict.verdict.value}")
    explanation = gateway.call(
        task="explain_verdict",
        context={
            "invoice_number": case.invoice_number,
            "verdict": case.verdict.verdict.value,
            "reason_chain": [r.message for r in case.verdict.reason_chain],
        },
        tenant_id=case.tenant_id,
        response_schema=VerdictExplanation,
    )
    print(explanation.explanation)

# OUTSIDE the loop, same indentation as "for case in cases:"
print(f"\n{len(cases)} flagged out of {len(register.rows)} total invoices "
      f"({len(register.rows) - len(cases)} eligible, not shown)")