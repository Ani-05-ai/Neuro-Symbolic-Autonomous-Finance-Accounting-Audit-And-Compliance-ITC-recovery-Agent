# backend/tests/test_gateway_smoke.py -- run manually: python test_gateway_smoke.py
import asyncio
from domain.llm import LLMTask, SummariseOut
from intelligence.gateway import LLMGateway
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from domain.llm import LLMTask, SummariseOut
from intelligence.gateway import LLMGateway
async def main():
    gw = LLMGateway()
    context = {
        "vendor_gstin": "27ABCDE1234F1Z5",
        "invoice_number": "INV-2025-001",
        "tax_period": "03/2025",
        "taxable_amount_inr": 100000.0,
        "verdict": "ineligible",
        "reason_chain_text": "[FAIL] Section 16(2)(c): Supplier GSTIN 27ABCDE1234F1Z5 not found in GSTR-1 for period 03/2025.",
    }
    result = await gw.call(LLMTask.SUMMARISE, context, "tenant_a", SummariseOut)
    print(result.model_dump_json(indent=2))
    print(f"\ntrace count: {len(gw.traces)}, last trace success: {gw.traces[-1].success}")

asyncio.run(main())