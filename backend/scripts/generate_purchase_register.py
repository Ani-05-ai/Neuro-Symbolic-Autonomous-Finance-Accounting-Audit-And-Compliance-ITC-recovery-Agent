"""Synthetic purchase register (.xlsx) generator.

Per Data_Sources_ITC_Recovery_Agent.pdf (DS-2) and 02_LLD_ITC_Recovery_Agent
(section 6, ingestion/purchase_register.py). Generates the buyer's internal
purchase register for a tenant, reusing the same tenant's GSTR-2B fixture
(and its .meta.json sidecar) so the two files are reconcilable against each
other -- most rows correspond to real GSTR-2B invoices (clean or slightly
noisy matches), a subset are deliberately absent from GSTR-2B entirely
(the "blocked ITC" cases the whole system exists to catch), and
supplier-only invoices from the GSTR-2B meta are guaranteed to be excluded.

This is dev/test fixture data only. It must never be treated as real
tenant data.

Usage (matches the Appendix's required invocation):
    python generate_purchase_register.py --tenant_id tenant_a --period 032025 --invoices 1050 --seed 42

Prerequisite: generate_gstr2b.py must already have been run for the same
tenant_id + period (this script reads its output + sidecar meta).
"""

from __future__ import annotations

import argparse
import json
import random
import string
from pathlib import Path

from faker import Faker
from openpyxl import Workbook

# ---------------------------------------------------------------------------
# Tenant profiles, per DS-2 "Synthetic tenant profiles to generate"
# ---------------------------------------------------------------------------

TENANT_PROFILES = {
    "tenant_a": {
        "industry": "Pharma distributor",
        "column_style": "tally",
        "columns": {
            "vendor_name": "Party Name",
            "vendor_gstin": "Party GSTIN",
            "invoice_number": "Voucher No",
            "invoice_date": "Voucher Date",
            "item_description": "Item Name",
            "taxable_amount": "Taxable Value",
            "gst_amount": "GST Amount",
            "tax_period": "Period",
        },
    },
    "tenant_b": {
        "industry": "FMCG manufacturer",
        "column_style": "sap",
        "columns": {
            "vendor_name": "Vendor",
            "vendor_gstin": "Vendor Tax No",
            "invoice_number": "Document No",
            "invoice_date": "Document Date",
            "item_description": "Material Description",
            "taxable_amount": "Net Value",
            "gst_amount": "Tax Amount",
            "tax_period": "Posting Period",
        },
    },
    "tenant_c": {
        "industry": "Retail chain",
        "column_style": "manual",
        "columns": {
            "vendor_name": "Supplier",
            "vendor_gstin": "GST No",
            "invoice_number": "Bill No",
            "invoice_date": "Date",
            "item_description": "Description",
            "taxable_amount": "Amount",
            "gst_amount": "Tax",
            "tax_period": "Month",
        },
    },
}

DEFAULT_PROFILE = TENANT_PROFILES["tenant_a"]

# Canonical field order the system expects internally (DS-2 "Minimum
# required columns"), independent of each tenant's actual header names.
CANONICAL_FIELDS = [
    "vendor_name",
    "vendor_gstin",
    "invoice_number",
    "invoice_date",
    "item_description",
    "taxable_amount",
    "gst_amount",
    "tax_period",
]

# ---------------------------------------------------------------------------
# Seed item descriptions, per DS-6's "Base item descriptions" guidance
# (raw materials, packaging, consumables, office supplies, services)
# ---------------------------------------------------------------------------

SEED_ITEMS = [
    ("HDPE Granules 20kg", "raw_material"),
    ("Steel Pipe 5mm IS 1161", "raw_material"),
    ("Aluminium Sheet 5mm IS 2062", "raw_material"),
    ("Copper Wire 2.5mm", "raw_material"),
    ("PVC Resin 25kg", "raw_material"),
    ("Caustic Soda Flakes 50kg", "raw_material"),
    ("Sulphuric Acid 98% 200L Drum", "raw_material"),
    ("Polypropylene Granules 25kg", "raw_material"),
    ("Mild Steel Rod 12mm", "raw_material"),
    ("Zinc Ingot 25kg", "raw_material"),
    ("Corrugated Box 12x12x12", "packaging"),
    ("BOPP Tape 48mm", "packaging"),
    ("Stretch Film Roll 500mm", "packaging"),
    ("HDPE Bag 50kg Capacity", "packaging"),
    ("Bubble Wrap Roll 1m x 100m", "packaging"),
    ("Wooden Pallet Standard", "packaging"),
    ("Paper Label Roll A4", "packaging"),
    ("Industrial Gloves Nitrile Box of 100", "consumable"),
    ("Safety Helmet ISI Marked", "consumable"),
    ("Welding Rod 3.15mm 5kg", "consumable"),
    ("Cutting Disc 4 inch", "consumable"),
    ("Lubricant Oil 20L Can", "consumable"),
    ("Cleaning Solvent 5L Can", "consumable"),
    ("Industrial Bearing 6205ZZ", "consumable"),
    ("V-Belt A-52", "consumable"),
    ("A4 Copier Paper Ream", "office_supply"),
    ("Ball Point Pen Box of 50", "office_supply"),
    ("Printer Toner Cartridge", "office_supply"),
    ("Stapler Heavy Duty", "office_supply"),
    ("File Folder Box of 25", "office_supply"),
    ("Whiteboard Marker Set", "office_supply"),
    ("Freight Charges - Local Transport", "service"),
    ("Freight Charges - Interstate Transport", "service"),
    ("Loading and Unloading Labour Charges", "service"),
    ("Annual Maintenance Contract - Machinery", "service"),
    ("Security Services - Monthly", "service"),
    ("Housekeeping Services - Monthly", "service"),
    ("CHA Charges - Import Clearance", "service"),
    ("Courier Charges - Domestic", "service"),
    ("Steel Pipe 8mm IS 1161", "raw_material"),  # near-miss of a 5mm variant
    ("HDPE Granules 25kg", "raw_material"),  # near-miss of the 20kg variant
]

# A tiny transliteration table (illustrative, not linguistically exhaustive)
# for the Hindi-transliteration noise transformation per DS-2/DS-6.
TRANSLITERATIONS = {
    "steel": "stīl",
    "pipe": "pāip",
    "iron": "lohā",
    "wire": "tār",
    "oil": "tel",
    "paper": "kāgaz",
    "box": "dibbā",
}


def _abbreviate(text: str, rng: random.Random) -> str:
    """Drop vowels from a random word and shorten common terms."""
    words = text.split()
    idx = rng.randrange(len(words))
    word = words[idx]
    if len(word) > 4 and word.isalpha():
        words[idx] = word[:4].rstrip("aeiouAEIOU") or word[:3]
    replacements = {"Granules": "Gran", "Charges": "Chgs", "Standard": "Std"}
    words = [replacements.get(w, w) for w in words]
    return " ".join(words)


def _transliterate(text: str, rng: random.Random) -> str:
    words = text.split()
    out = []
    for w in words:
        key = w.lower().strip(string.punctuation)
        out.append(TRANSLITERATIONS.get(key, w))
    return " ".join(out)


def _unit_variation(text: str, rng: random.Random) -> str:
    if "kg" in text:
        return text.replace("kg", rng.choice(["000g", " Kilograms"]))
    if "mm" in text and rng.random() < 0.5:
        return text.replace("mm", " Millimeter")
    return text


def _brand_prefix(text: str, rng: random.Random, fake: Faker) -> str:
    brand = rng.choice(["Supreme", "Tata", "Reliance", "JSW", "UltraTech", "Apollo"])
    return f"{brand} {text}"


def _ocr_noise(text: str, rng: random.Random) -> str:
    swaps = {"e": "3", "l": "1", "o": "0", "i": "1", "s": "5"}
    chars = list(text)
    num_swaps = max(1, len(text) // 25)
    positions = rng.sample(range(len(chars)), k=min(num_swaps, len(chars)))
    for pos in positions:
        low = chars[pos].lower()
        if low in swaps:
            chars[pos] = swaps[low]
    return "".join(chars)


def _whitespace_punct(text: str, rng: random.Random) -> str:
    return rng.choice([text.replace(" ", "-"), text.replace(" ", "")])


def _case_variation(text: str, rng: random.Random) -> str:
    return rng.choice([text.lower(), text.upper()])


NOISE_TRANSFORMATIONS = [
    _abbreviate,
    _transliterate,
    _unit_variation,
    _ocr_noise,
    _whitespace_punct,
    _case_variation,
]


def messy_item_description(rng: random.Random, fake: Faker) -> str:
    """Pick a seed item and apply zero or more DS-2 noise transformations."""
    base, _category = rng.choice(SEED_ITEMS)
    text = base
    if rng.random() < 0.15:
        text = _brand_prefix(text, rng, fake)
    if rng.random() < 0.55:
        transform = rng.choice(NOISE_TRANSFORMATIONS)
        text = transform(text, rng)
    return text


# ---------------------------------------------------------------------------
# Vendor name noise -- manual entry of a supplier's trdnm is rarely exact
# ---------------------------------------------------------------------------


def noisy_vendor_name(trade_name: str, rng: random.Random) -> str:
    if rng.random() < 0.7:
        return trade_name  # most manual entries are still faithful
    suffixes = [" Pvt Ltd", " Private Limited", " & Co", " Enterprises"]
    if any(trade_name.endswith(s.strip()) for s in ["Ltd", "Inc", "LLC"]):
        return trade_name
    return trade_name + rng.choice(suffixes)


# ---------------------------------------------------------------------------
# Row construction
# ---------------------------------------------------------------------------


def build_matched_row(
    supplier_ctin: str,
    supplier_trdnm: str,
    invoice: dict,
    period: str,
    rng: random.Random,
    fake: Faker,
    *,
    amount_drift_rate: float,
) -> dict:
    """A purchase-register row corresponding to a real GSTR-2B invoice."""
    txval = sum(item["txval"] for item in invoice["itms"])
    gst_amt = sum(
        item["iamt"] + item["camt"] + item["samt"] + item["csamt"]
        for item in invoice["itms"]
    )

    # Independently perturb the amount on a subset of matched rows, per
    # DS-1's "5-10% of entries with invoice amounts differing by +/-5%
    # from the purchase register" -- simulating the buyer's own ledger
    # disagreeing with what the government portal shows.
    if rng.random() < amount_drift_rate:
        drift = 1 + rng.choice([1, -1]) * 0.05
        txval = round(txval * drift, 2)
        gst_amt = round(gst_amt * drift, 2)

    idt = invoice["idt"]  # DD-MM-YYYY -> reformat to DD/MM/YYYY per DS-2
    invoice_date = idt.replace("-", "/")

    return {
        "vendor_name": noisy_vendor_name(supplier_trdnm, rng),
        "vendor_gstin": supplier_ctin,
        "invoice_number": invoice["inum"],
        "invoice_date": invoice_date,
        "item_description": messy_item_description(rng, fake),
        "taxable_amount": round(txval, 2),
        "gst_amount": round(gst_amt, 2),
        "tax_period": f"{period[:2]}/{period[2:]}",
    }


def build_unmatched_row(
    period: str,
    rng: random.Random,
    fake: Faker,
    actual_supplier_gstins: list[str],
) -> dict:
    """A row with no corresponding GSTR-2B invoice -- the blocked-ITC case.

    Reuses a GSTIN that genuinely appears in GSTR-2B's data.b2b[] (the
    supplier exists and has other filed invoices, but this particular
    invoice was never filed by them) rather than meta["known_vendor_gstins"],
    which can contain GSTINs pre-generated but never actually assigned to
    any real supplier in the document -- drawing from that oversized pool
    would silently produce a different Rule Engine test case (GSTIN wholly
    absent from GSTR-2B, not "invoice unfiled by an otherwise-present
    supplier").
    """
    prefix = rng.choice(["INV", "BILL", "GST", "SL"])
    suffix = "".join(rng.choices(string.digits, k=rng.randint(4, 8)))
    invoice_number = f"{prefix}-{fake.year()}-{suffix}"[:16]
    month, year = int(period[:2]), int(period[2:])
    day = rng.randint(1, 28)

    return {
        "vendor_name": fake.company(),
        "vendor_gstin": rng.choice(actual_supplier_gstins),
        "invoice_number": invoice_number,
        "invoice_date": f"{day:02d}/{month:02d}/{year}",
        "item_description": messy_item_description(rng, fake),
        "taxable_amount": round(rng.uniform(500, 100_000), 2),
        "gst_amount": round(rng.uniform(0, 15_000), 2),
        "tax_period": f"{period[:2]}/{period[2:]}",
    }


# ---------------------------------------------------------------------------
# Core generation
# ---------------------------------------------------------------------------


def generate_purchase_register(
    tenant_id: str,
    period: str,
    num_invoices: int,
    seed: int,
    gstr2b_dir: Path,
) -> list[dict]:
    """Build the purchase register rows for one tenant + period.

    Deterministic given the same tenant_id + period + num_invoices + seed
    AND the same GSTR-2B fixture (which is itself deterministic from its
    own seed). Rows are canonical-field dicts; the caller maps them to the
    tenant's column style when writing the .xlsx.
    """
    rng = random.Random(seed)
    fake = Faker("en_IN")
    fake.seed_instance(seed)

    doc_path = gstr2b_dir / f"gstr2b_{tenant_id}_{period}.json"
    meta_path = gstr2b_dir / f"gstr2b_{tenant_id}_{period}.meta.json"
    if not doc_path.exists() or not meta_path.exists():
        raise FileNotFoundError(
            f"Expected GSTR-2B fixture + meta at {doc_path} / {meta_path}. "
            "Run generate_gstr2b.py for this tenant_id/period first."
        )

    document = json.loads(doc_path.read_text())
    meta = json.loads(meta_path.read_text())

    known_gstins = meta["known_vendor_gstins"]
    actual_supplier_gstins = [s["ctin"] for s in document["data"]["b2b"]]
    supplier_only = {
        (ref["ctin"], ref["inum"]) for ref in meta["supplier_only_invoices"]
    }

    # Collect every invoice belonging to a known-vendor supplier, excluding
    # supplier-only invoices (which must never appear in the register).
    eligible_invoices: list[tuple[str, str, dict]] = []
    for supplier in document["data"]["b2b"]:
        ctin = supplier["ctin"]
        if ctin not in known_gstins:
            continue  # unknown-vendor suppliers are naturally never matched
        for inv in supplier["inv"]:
            if (ctin, inv["inum"]) in supplier_only:
                continue
            eligible_invoices.append((ctin, supplier["trdnm"], inv))

    rng.shuffle(eligible_invoices)

    # Target more invoices than GSTR-2B has, per DS-1: "The --invoices count
    # for the purchase register should be slightly higher than GSTR-2B (to
    # ensure some unmatched rows exist as test cases)."
    num_unmatched = max(1, round(num_invoices * 0.05))
    num_matched = max(0, num_invoices - num_unmatched)
    num_matched = min(num_matched, len(eligible_invoices))

    amount_drift_rate = rng.uniform(0.05, 0.10)  # per DS-1

    rows: list[dict] = []
    for ctin, trdnm, inv in eligible_invoices[:num_matched]:
        rows.append(
            build_matched_row(
                ctin, trdnm, inv, period, rng, fake, amount_drift_rate=amount_drift_rate
            )
        )

    for _ in range(num_unmatched):
        rows.append(build_unmatched_row(period, rng, fake, actual_supplier_gstins))

    rng.shuffle(rows)  # don't leave all unmatched rows clustered at the end

    if len(rows) != num_invoices:
        print(
            f"NOTE: requested {num_invoices} rows but only {len(rows)} were "
            f"produced -- the referenced GSTR-2B fixture only has "
            f"{len(eligible_invoices)} eligible known-vendor invoices to "
            f"match against. Regenerate that fixture with a higher "
            f"--invoices count if you need more matched rows."
        )

    return rows


def write_xlsx(rows: list[dict], profile: dict, out_path: Path) -> None:
    """Write rows to .xlsx using the tenant profile's column-naming style."""
    columns = profile["columns"]
    wb = Workbook()
    ws = wb.active
    ws.title = "Purchase Register"

    headers = [columns[field] for field in CANONICAL_FIELDS]
    ws.append(headers)

    for row in rows:
        ws.append([row[field] for field in CANONICAL_FIELDS])

    wb.save(out_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant_id", required=True, help="e.g. tenant_a")
    parser.add_argument("--period", required=True, help="MMYYYY, e.g. 032025")
    parser.add_argument(
        "--invoices", type=int, default=550, help="target row count (>GSTR-2B count)"
    )
    parser.add_argument("--seed", type=int, required=True, help="reproducibility seed")
    parser.add_argument(
        "--gstr2b-dir",
        default="fixtures",
        help="directory containing the tenant's GSTR-2B fixture (default: fixtures/)",
    )
    parser.add_argument(
        "--out-dir",
        default="fixtures",
        help="output directory (default: fixtures/)",
    )
    args = parser.parse_args()

    profile = TENANT_PROFILES.get(args.tenant_id, DEFAULT_PROFILE)

    rows = generate_purchase_register(
        args.tenant_id,
        args.period,
        args.invoices,
        args.seed,
        Path(args.gstr2b_dir),
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"purchase_register_{args.tenant_id}.xlsx"
    write_xlsx(rows, profile, out_path)

    print(
        f"Wrote {len(rows)} rows ({profile['column_style']}-style headers) -> {out_path}"
    )


if __name__ == "__main__":
    main()
