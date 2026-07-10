"""Synthetic GSTR-2B JSON generator.

Per Data_Sources_ITC_Recovery_Agent.pdf (DS-1) and 02_LLD_ITC_Recovery_Agent
(section 6, ingestion/gstr2b.py). Generates a GSTR-2B JSON file for a given
tenant + tax period, matching the shape the government GST portal produces:

    {"gstin": ..., "fp": "MMYYYY", "data": {"b2b": [...], "cdn": [...], "isd": [...]}}

This is dev/test fixture data only. It must never be treated as real GST data.

Usage (matches the Appendix's required invocation):
    python generate_gstr2b.py --tenant_id tenant_a --period 032025 --invoices 1000 --seed 42
"""

from __future__ import annotations

import argparse
import json
import random
import string
from pathlib import Path

from faker import Faker

# ---------------------------------------------------------------------------
# Constants driven directly by the spec documents
# ---------------------------------------------------------------------------

VALID_STATE_CODES = [f"{i:02d}" for i in range(1, 39)]  # 01-38 per DS-1
VALID_TAX_RATES = [0, 5, 12, 18, 28]  # only valid GST slabs per DS-1

# Mismatch-injection rates, per DS-1 "Rules for synthetic generation":
PCT_UNKNOWN_GSTIN = (0.10, 0.15)   # 10-15% GSTIN with no vendor match
PCT_SUPPLIER_ONLY = 0.05           # 5% present in 2B only (not in purchase reg)

# NOTE: the "5-10% of entries with invoice amounts differing by +/-5%"
# rule from DS-1 is intentionally NOT implemented here. GSTR-2B is this
# system's authoritative ground truth (per the LLD -- InvoiceFacts is
# validated against it), so it should never disagree with itself. Amount
# drift is injected exactly once, in generate_purchase_register.py, since
# amount disagreement is a property of the buyer's ledger vs. the truth,
# not the truth vs. itself.


# ---------------------------------------------------------------------------
# GSTIN synthesis
# ---------------------------------------------------------------------------


def _random_pan(rng: random.Random) -> str:
    """A syntactically valid-looking 10-char PAN: 5 letters, 4 digits, 1 letter."""
    letters1 = "".join(rng.choices(string.ascii_uppercase, k=5))
    digits = "".join(rng.choices(string.digits, k=4))
    letter2 = rng.choice(string.ascii_uppercase)
    return f"{letters1}{digits}{letter2}"


def generate_gstin(rng: random.Random) -> str:
    """[2-digit state code][10-char PAN][entity digit][Z][check digit] per DS-1."""
    state_code = rng.choice(VALID_STATE_CODES)
    pan = _random_pan(rng)
    entity_digit = rng.choice("123456789")
    check_digit = rng.choice(string.digits + string.ascii_uppercase)
    return f"{state_code}{pan}{entity_digit}Z{check_digit}"


def mutate_gstin(gstin: str, rng: random.Random) -> str:
    """Corrupt one character of a GSTIN so it no longer matches any known vendor."""
    pos = rng.randrange(2, 12)  # mutate within the PAN portion, keep state code sane
    chars = list(gstin)
    replacement = rng.choice(string.ascii_uppercase + string.digits)
    chars[pos] = replacement if replacement != chars[pos] else "X"
    return "".join(chars)


# ---------------------------------------------------------------------------
# Invoice number synthesis
# ---------------------------------------------------------------------------


def generate_invoice_number(rng: random.Random, fake: Faker) -> str:
    """Alphanumeric, up to 16 characters, per DS-1."""
    prefix = rng.choice(["INV", "BILL", "GST", "SL"])
    suffix = "".join(rng.choices(string.digits, k=rng.randint(4, 8)))
    number = f"{prefix}-{fake.year()}-{suffix}"
    return number[:16]


# ---------------------------------------------------------------------------
# Core generation
# ---------------------------------------------------------------------------


def _period_to_fp(period: str) -> str:
    """Accepts MMYYYY (spec format) and returns it unchanged; validates shape."""
    if len(period) != 6 or not period.isdigit():
        raise ValueError(f"period must be MMYYYY, got {period!r}")
    month = int(period[:2])
    if not (1 <= month <= 12):
        raise ValueError(f"invalid month in period {period!r}")
    return period


def _random_date_in_period(period: str, rng: random.Random) -> str:
    """Return a DD-MM-YYYY date that falls within the given MMYYYY period."""
    month, year = int(period[:2]), int(period[2:])
    day = rng.randint(1, 28)  # 28 keeps every month valid, no calendar lib needed
    return f"{day:02d}-{month:02d}-{year}"


def _generate_line_item(
    item_num: int, taxable_value: float, tax_rate: int, interstate: bool
) -> dict:
    """One entry in an invoice's itms[] -- a single tax-rate slab within that invoice."""
    if interstate:
        igst_amt = round(taxable_value * tax_rate / 100, 2)
        cgst_amt = sgst_amt = 0.0
    else:
        half_rate_amt = round(taxable_value * (tax_rate / 2) / 100, 2)
        igst_amt = 0.0
        cgst_amt = sgst_amt = half_rate_amt
    return {
        "num": item_num,
        "rt": tax_rate,
        "txval": taxable_value,
        "iamt": igst_amt,
        "camt": cgst_amt,
        "samt": sgst_amt,
        "csamt": 0.0,
    }


def generate_invoice(period: str, rng: random.Random, fake: Faker) -> dict:
    """One invoice under a supplier's inv[] -- may carry multiple tax-rate line items."""
    interstate = rng.random() < 0.4
    num_line_items = rng.choices([1, 2, 3], weights=[0.7, 0.2, 0.1])[0]
    used_rates = rng.sample(VALID_TAX_RATES, k=min(num_line_items, len(VALID_TAX_RATES)))

    items = []
    for i, rate in enumerate(used_rates, start=1):
        taxable_value = round(rng.uniform(500, 100_000), 2)
        items.append(_generate_line_item(i, taxable_value, rate, interstate))

    total_txval = round(sum(it["txval"] for it in items), 2)
    total_tax = round(
        sum(it["iamt"] + it["camt"] + it["samt"] + it["csamt"] for it in items), 2
    )
    invoice_value = round(total_txval + total_tax, 2)

    return {
        "inum": generate_invoice_number(rng, fake),
        "idt": _random_date_in_period(period, rng),
        "val": invoice_value,
        "pos": rng.choice(VALID_STATE_CODES),
        "rev": "N",
        "itcavl": "Y",
        "rsn": None,
        "itms": items,
    }


def generate_supplier_entry(
    period: str,
    rng: random.Random,
    fake: Faker,
    *,
    supplier_gstin: str,
    num_invoices: int,
) -> dict:
    """One entry under data.b2b[] -- one supplier with one or more invoices nested in inv[]."""
    return {
        "ctin": supplier_gstin,
        "trdnm": fake.company(),
        "supfildt": _random_date_in_period(period, rng),
        "inv": [generate_invoice(period, rng, fake) for _ in range(num_invoices)],
    }


def generate_gstr2b(
    tenant_id: str,
    period: str,
    num_invoices: int,
    seed: int,
) -> tuple[dict, dict]:
    """Build the full GSTR-2B document for one tenant + period.

    Returns (document, sidecar_meta). `document` is the government-schema
    JSON exactly as it would come off the GST portal -- b2b[] grouped by
    supplier, each with a nested inv[] of invoices, each with a nested
    itms[] of tax-rate line items. `sidecar_meta` is POC-only bookkeeping
    (known vendor pool, supplier-only invoice numbers) that the purchase
    register generator needs but which must never be written into the
    same file as the simulated government document.

    Deterministic: same tenant_id + period + num_invoices + seed always
    produces byte-identical output, per the Appendix's hard reproducibility
    requirement.
    """
    period = _period_to_fp(period)
    rng = random.Random(seed)
    fake = Faker("en_IN")
    fake.seed_instance(seed)

    tenant_gstin = generate_gstin(rng)

    # Pre-generate a pool of "known" vendor GSTINs -- vendors that also
    # appear in the tenant's purchase register in the common (clean-match)
    # case. The purchase-register generator reuses this pool via the same
    # seed so the two fixtures are reconcilable against each other.
    num_suppliers = max(5, num_invoices // 10)
    known_gstins = [generate_gstin(rng) for _ in range(num_suppliers)]

    unknown_rate = rng.uniform(*PCT_UNKNOWN_GSTIN)

    # Distribute num_invoices across num_suppliers (at least 1 invoice each).
    remaining = num_invoices - num_suppliers
    invoices_per_supplier = [1] * num_suppliers
    for _ in range(max(0, remaining)):
        invoices_per_supplier[rng.randrange(num_suppliers)] += 1

    # Sample "known" GSTINs without replacement -- rng.choice() with
    # replacement guarantees ctin collisions at this scale (birthday
    # paradox), which is structurally invalid since ctin must be unique
    # within b2b[]. Falls back to a freshly generated GSTIN once the known
    # pool is exhausted.
    known_pool = list(known_gstins)
    rng.shuffle(known_pool)
    known_pool_iter = iter(known_pool)

    b2b_entries: list[dict] = []
    all_invoice_numbers_by_supplier: list[tuple[str, list[str]]] = []

    for supplier_idx in range(num_suppliers):
        force_unknown = rng.random() < unknown_rate
        if force_unknown:
            supplier_gstin = generate_gstin(rng)
        else:
            supplier_gstin = next(known_pool_iter, None) or generate_gstin(rng)

        entry = generate_supplier_entry(
            period,
            rng,
            fake,
            supplier_gstin=supplier_gstin,
            num_invoices=invoices_per_supplier[supplier_idx],
        )

        b2b_entries.append(entry)
        all_invoice_numbers_by_supplier.append(
            (supplier_gstin, [inv["inum"] for inv in entry["inv"]])
        )

    # 5% supplier-only invoices: exist in GSTR-2B but will deliberately be
    # excluded from the purchase register by the register generator (same
    # seed), simulating invoices the buyer never recorded -- the "blocked
    # ITC" case the whole system exists to catch.
    total_invoices = sum(len(inums) for _, inums in all_invoice_numbers_by_supplier)
    num_supplier_only = round(total_invoices * PCT_SUPPLIER_ONLY)
    flat_refs = [
        (gstin, inum) for gstin, inums in all_invoice_numbers_by_supplier for inum in inums
    ]
    supplier_only_refs = rng.sample(flat_refs, k=min(num_supplier_only, len(flat_refs)))

    document = {
        "gstin": tenant_gstin,
        "fp": period,
        "data": {
            "b2b": b2b_entries,
            "cdn": [],  # credit/debit notes -- out of scope for POC
            "isd": [],  # input service distributor entries -- out of scope
        },
    }

    sidecar_meta = {
        "tenant_id": tenant_id,
        "period": period,
        "seed": seed,
        "known_vendor_gstins": known_gstins,
        "supplier_only_invoices": [
            {"ctin": gstin, "inum": inum} for gstin, inum in supplier_only_refs
        ],
    }

    return document, sidecar_meta


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant_id", required=True, help="e.g. tenant_a")
    parser.add_argument("--period", required=True, help="MMYYYY, e.g. 032025")
    parser.add_argument("--invoices", type=int, default=500, help="min 500 per DS-1")
    parser.add_argument("--seed", type=int, required=True, help="reproducibility seed")
    parser.add_argument(
        "--out-dir",
        default="fixtures",
        help="output directory (default: fixtures/)",
    )
    args = parser.parse_args()

    document, sidecar_meta = generate_gstr2b(
        args.tenant_id, args.period, args.invoices, args.seed
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / f"gstr2b_{args.tenant_id}_{args.period}.json"
    out_path.write_text(json.dumps(document, indent=2, ensure_ascii=False))

    meta_path = out_dir / f"gstr2b_{args.tenant_id}_{args.period}.meta.json"
    meta_path.write_text(json.dumps(sidecar_meta, indent=2, ensure_ascii=False))

    num_suppliers = len(document["data"]["b2b"])
    num_invoices = sum(len(s["inv"]) for s in document["data"]["b2b"])
    print(f"Wrote {num_suppliers} suppliers / {num_invoices} invoices -> {out_path}")
    print(f"Wrote sidecar metadata -> {meta_path}")


if __name__ == "__main__":
    main()
