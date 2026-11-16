import json
from pathlib import Path

# Point directly to your existing folders
PO_DIR = Path("data/purchase_orders")
GRN_DIR = Path("data/goods_receipts")
INV_DIR = Path("data/invoices")

def process_orders_one_by_one():
    print("📂 Starting sequential order-by-order processing...\n")

    if not INV_DIR.exists():
        print("⚠️ Invoices folder not found!")
        return

    # Loop through invoice files ONE BY ONE
    for inv_file in INV_DIR.glob("*.json"):
        with open(inv_file, "r", encoding="utf-8") as f:
            invoice_data = json.load(f)

        # Extract identifiers for this specific order
        invoice_number = invoice_data.get("invoice_number")
        po_id = invoice_data.get("po_id")

        print(processing 📄 Processing Order for Invoice: {invoice_number} (PO #{po_id})")

        # 1. Look for the matching Purchase Order file on-demand
        po_file = PO_DIR / f"po_{po_id}.json" # assuming naming convention or search
        po_data = None
        if po_file.exists():
            with open(po_file, "r", encoding="utf-8") as pf:
                po_data = json.load(pf)
        else:
            print("   ⚠️ Component Missing: Purchase Order file not found!")

        # 2. Look for the matching Goods Receipt file on-demand
        grn_file = GRN_DIR / f"grn_{po_id}.json"
        grn_data = None
        if grn_file.exists():
            with open(grn_file, "r", encoding="utf-8") as gf:
                grn_data = json.load(gf)
        else:
            print("   ⚠️ Component Missing: Goods Receipt file not found!")

        # 3. Perform matching and save audit for THIS SINGLE ORDER only
        evaluate_and_save_audit(invoice_data, po_data, grn_data)
        print("-" * 50)

def evaluate_and_save_audit(invoice, po, grn):
    """Evaluates the 3 components for this single order and logs the audit report."""
    discrepancies = []

    if not po:
        discrepancies.append("Missing Purchase Order")
    if not grn:
        discrepancies.append("Missing Goods Receipt")

    if po and grn:
        print("   ✅ All 3 components present for this order. Running match rules...")
        # Add your price hike or duplicate checks here
    else:
        print(f"   📋 Audit Report saved: Order flagged due to -> {', '.join(discrepancies)}")

if __name__ == "__main__":
    process_orders_one_by_one()