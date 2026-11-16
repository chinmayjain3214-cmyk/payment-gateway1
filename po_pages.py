"""Purchase-order management with PO-based JSON record persistence.

Canonical saved PO path: data/purchase_orders/po_<po_id>.json
Existing reference_data.json records remain read-only fixtures. New POs are
saved separately and merged into this page for subsequent viewing.

Department and cost-centre choices are fictional demo mappings. They are
saved on newly created POs so the budget-validation workflow can resolve the
PO's department; they do not represent actual university financial data.
"""

import json
import math
from pathlib import Path

import streamlit as st

from record_store import (
    RecordStoreError,
    normalize_po_id,
    save_purchase_order,
)


BASE_DIR = Path(__file__).resolve().parent
REFERENCE_FILE = BASE_DIR / "dataset" / "reference_data.json"
PO_DATA_DIR = BASE_DIR / "data" / "purchase_orders"

# Department IDs and names are read from dataset/reference_data.json.
# These are demo reference records, not verified university finance data.


# ==================================================
# DATA HELPERS
# ==================================================


def _load_saved_purchase_orders(base_dir=None):
    """Load records already saved as data/purchase_orders/po_<id>.json."""
    root = Path(base_dir) if base_dir is not None else BASE_DIR
    directory = root / "data" / "purchase_orders"
    if not directory.is_dir():
        return []

    records = []
    for path in sorted(directory.glob("po_*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(record, dict):
                continue
            po_id = normalize_po_id(record.get("po_id") or path.stem[3:])
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue

        record.setdefault("po_id", po_id)
        record.setdefault("record_id", f"po_{po_id}")
        record.setdefault("po_number", f"PO-{po_id}")
        records.append(record)

    return records


def merge_saved_purchase_orders(reference, base_dir=None):
    """Merge saved PO records over fixtures without duplicating PO numbers."""
    data = dict(reference) if isinstance(reference, dict) else {}
    reference_pos = data.get("purchase_orders", [])
    if not isinstance(reference_pos, list):
        reference_pos = []

    purchase_orders = [po for po in reference_pos if isinstance(po, dict)]
    positions = {
        str(po.get("po_number") or ""): index
        for index, po in enumerate(purchase_orders)
        if po.get("po_number")
    }

    for saved in _load_saved_purchase_orders(base_dir=base_dir):
        po_number = str(saved.get("po_number") or "")
        if not po_number:
            continue
        if po_number in positions:
            index = positions[po_number]
            purchase_orders[index] = {**purchase_orders[index], **saved}
        else:
            positions[po_number] = len(purchase_orders)
            purchase_orders.append(saved)

    data["purchase_orders"] = purchase_orders
    return data


def get_next_po_id(purchase_orders, base_dir=None):
    """Choose the next numeric PO ID, including fixture and saved PO records.

    The current reference dataset uses PO-101 through PO-118 and has no
    separate po_id field. Therefore the numeric PO-number suffix is used as
    the fallback PO ID until the database backend supplies its own ID.
    """
    candidates = []

    for po in purchase_orders if isinstance(purchase_orders, list) else []:
        if not isinstance(po, dict):
            continue
        for value in (po.get("po_id"), po.get("id"), po.get("po_number")):
            if value is None or value == "":
                continue
            try:
                candidates.append(normalize_po_id(value))
                break
            except (TypeError, ValueError):
                continue

    root = Path(base_dir) if base_dir is not None else BASE_DIR
    directory = root / "data" / "purchase_orders"
    if directory.is_dir():
        for path in directory.glob("po_*.json"):
            try:
                candidates.append(normalize_po_id(path.stem[3:]))
            except (TypeError, ValueError):
                continue

    # The supplied demonstration dataset starts at PO-101. In a blank local
    # folder, continue that convention rather than creating PO-1 unexpectedly.
    return max(candidates, default=100) + 1


def load_procurement_data():
    """Load reference fixtures and merge any saved canonical PO records."""
    try:
        with REFERENCE_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, dict):
            raise ValueError("Invalid procurement reference data.")

        return merge_saved_purchase_orders(data)

    except FileNotFoundError:
        st.error("dataset/reference_data.json was not found.")
        return {"purchase_orders": [], "vendors": []}

    except (OSError, json.JSONDecodeError, ValueError) as exc:
        st.error("Could not load procurement data.")
        st.caption(str(exc)[:200])
        return {"purchase_orders": [], "vendors": []}


def get_po_vendor(po):
    return po.get("vendor_name") or po.get("vendor") or "Unknown vendor"


def get_po_number(po):
    return str(po.get("po_number") or "Not assigned")


def get_po_department(po):
    return str(po.get("department") or "UNASSIGNED")


def get_po_department_id(po):
    return str(po.get("department_id") or "UNASSIGNED")


def get_po_cost_center(po):
    return str(po.get("cost_center") or "UNASSIGNED")


def get_department_options(reference):
    """Return valid department master records from the dataset reference."""
    departments = reference.get("departments", []) if isinstance(reference, dict) else []
    if not isinstance(departments, list):
        return []

    options = []
    seen_ids = set()
    for row in departments:
        if not isinstance(row, dict):
            continue
        department_id = str(row.get("department_id") or "").strip()
        name = str(row.get("name") or "").strip()
        if not department_id or not name or department_id in seen_ids:
            continue
        seen_ids.add(department_id)
        options.append({
            "department_id": department_id,
            "name": name,
            # A cost centre is only populated if the reference master supplies it.
            "cost_center": str(row.get("cost_center") or "").strip() or None,
        })

    return sorted(options, key=lambda item: (item["name"].casefold(), item["department_id"]))


def get_status(po):
    return str(po.get("status") or "UNKNOWN").upper()


def get_items(po):
    items = po.get("items") or []
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def format_amount(value, currency="INR"):
    try:
        return f"{currency} {float(value):,.2f}"
    except (ValueError, TypeError):
        return "Not specified"


def parse_positive_number(value, field_name, item_number):
    """Parse a required positive number from a blank text input."""
    raw = str(value or "").strip().replace(",", "")
    if not raw:
        raise ValueError(f"Enter {field_name.lower()} for item {item_number}.")
    try:
        number = float(raw)
    except (TypeError, ValueError):
        raise ValueError(
            f"{field_name} for item {item_number} must be a valid number."
        ) from None
    if not math.isfinite(number) or number <= 0:
        raise ValueError(
            f"{field_name} for item {item_number} must be greater than zero."
        )
    return number


def get_vendor_options(reference):
    vendors = reference.get("vendors", [])
    names = set()

    if isinstance(vendors, list):
        for vendor in vendors:
            if isinstance(vendor, dict):
                name = vendor.get("name") or vendor.get("vendor_name")
                if name:
                    names.add(str(name))

    purchase_orders = reference.get("purchase_orders", [])
    if isinstance(purchase_orders, list):
        for po in purchase_orders:
            if isinstance(po, dict):
                names.add(str(get_po_vendor(po)))

    names.discard("Unknown vendor")
    return sorted(names)


def get_vendor_id(reference, vendor_name):
    """Resolve vendor ID from the internal vendor reference, not user input."""
    vendors = reference.get("vendors", [])
    if isinstance(vendors, list):
        for vendor in vendors:
            if not isinstance(vendor, dict):
                continue
            name = vendor.get("name") or vendor.get("vendor_name")
            if str(name or "").strip() == str(vendor_name or "").strip():
                return vendor.get("vendor_id") or vendor.get("id")

    purchase_orders = reference.get("purchase_orders", [])
    for po in purchase_orders if isinstance(purchase_orders, list) else []:
        if (
            isinstance(po, dict)
            and str(get_po_vendor(po)).strip() == str(vendor_name).strip()
        ):
            return po.get("vendor_id")

    return None


def render_status(status):
    status = str(status).upper()

    if status == "APPROVED":
        st.success(status)
    elif status in ("PENDING", "SUBMITTED", "DRAFT"):
        st.warning(status)
    elif status in ("CANCELLED", "REJECTED"):
        st.error(status)
    elif status in ("COMPLETED", "CLOSED"):
        st.info(status)
    else:
        st.caption(status)


def get_dataframe_height(row_count, max_height=900):
    """Calculate table height based on the number of rows."""
    return min(max_height, max(200, 38 * (row_count + 1)))


# ==================================================
# PO DETAILS
# ==================================================


def render_po_details(po):
    st.markdown("### Purchase order details")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("PO Number", get_po_number(po))
    with col2:
        st.metric("Vendor", get_po_vendor(po))
    with col3:
        st.metric("Line items", len(get_items(po)))

    currency = str(po.get("currency") or "INR")
    st.markdown("**Order information**")

    info1, info2, info3 = st.columns(3)
    with info1:
        st.write("**Vendor ID**")
        st.write(str(po.get("vendor_id") or "-"))
    with info2:
        st.write("**Currency**")
        st.write(currency)
    with info3:
        st.write("**Price tolerance**")
        tolerance = po.get("price_tolerance_percent")
        st.write(str(tolerance) + "%" if tolerance is not None else "-")

    st.markdown("**Department and budget mapping**")
    mapping1, mapping2, mapping3 = st.columns(3)
    with mapping1:
        st.write("**Department**")
        st.write(get_po_department(po))
    with mapping2:
        st.write("**Department ID**")
        st.write(get_po_department_id(po))
    with mapping3:
        st.write("**Cost centre**")
        st.write(get_po_cost_center(po))
    if get_po_department(po) == "UNASSIGNED":
        st.caption("Budget validation cannot be completed until this PO is mapped.")

    st.markdown("**Order status**")
    render_status(get_status(po))
    st.divider()
    st.markdown("### Ordered items")

    items = get_items(po)
    if not items:
        st.info("No line items are recorded for this purchase order.")
        return

    rows = []
    for item in items:
        rows.append({
            "Description": item.get("description") or "-",
            "Quantity ordered": item.get("quantity_ordered", "-"),
            "Approved unit price": format_amount(item.get("approved_unit_price"), currency),
            "Tax rate": (
                str(item.get("tax_percent")) + "%"
                if item.get("tax_percent") is not None
                else "Not specified"
            ),
        })

    st.dataframe(
        rows,
        use_container_width=True,
        hide_index=True,
        height=get_dataframe_height(len(rows)),
    )


# ==================================================
# DASHBOARD
# ==================================================


def render_po_dashboard(purchase_orders):
    st.markdown("### Procurement overview")

    total = len(purchase_orders)
    approved = sum(1 for po in purchase_orders if get_status(po) == "APPROVED")
    pending = sum(
        1 for po in purchase_orders
        if get_status(po) in ("PENDING", "SUBMITTED", "DRAFT")
    )
    cancelled = sum(
        1 for po in purchase_orders
        if get_status(po) in ("CANCELLED", "REJECTED")
    )

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total purchase orders", total)
    col2.metric("Approved", approved)
    col3.metric("Pending", pending)
    col4.metric("Cancelled / rejected", cancelled)

    st.divider()
    st.markdown("### All purchase orders")

    if not purchase_orders:
        st.info("No purchase orders are available.")
        return

    rows = []
    for po in purchase_orders:
        rows.append({
            "PO Number": get_po_number(po),
            "Vendor": get_po_vendor(po),
            "Department": get_po_department(po),
            "Department ID": get_po_department_id(po),
            "Cost centre": get_po_cost_center(po),
            "Status": get_status(po),
            "Currency": po.get("currency") or "-",
            "Line items": len(get_items(po)),
        })

    st.caption(f"Showing all {len(rows)} purchase orders.")
    st.dataframe(
        rows,
        use_container_width=True,
        hide_index=True,
        height=get_dataframe_height(len(rows)),
    )


# ==================================================
# PURCHASE ORDER LIST
# ==================================================


def render_po_list(purchase_orders):
    st.markdown("### All purchase orders")

    search = st.text_input(
        "Search purchase orders",
        placeholder="Search PO number or vendor...",
        key="po_search",
    ).strip().lower()

    statuses = sorted({get_status(po) for po in purchase_orders})
    status_options = ["All statuses"] + statuses
    selected_status = st.selectbox(
        "Filter by status", status_options, key="po_status_filter"
    )

    vendors = sorted({get_po_vendor(po) for po in purchase_orders})
    vendor_options = ["All vendors"] + vendors
    selected_vendor = st.selectbox(
        "Filter by vendor", vendor_options, key="po_vendor_filter"
    )

    filtered = []
    for po in purchase_orders:
        po_number = get_po_number(po).lower()
        vendor = get_po_vendor(po).lower()
        if search and search not in po_number and search not in vendor:
            continue
        if selected_status != "All statuses" and get_status(po) != selected_status:
            continue
        if selected_vendor != "All vendors" and get_po_vendor(po) != selected_vendor:
            continue
        filtered.append(po)

    st.caption(f"{len(filtered)} purchase orders found.")
    if not filtered:
        st.info("No purchase orders match your filters.")
        return

    table = []
    for po in filtered:
        table.append({
            "PO Number": get_po_number(po),
            "Vendor": get_po_vendor(po),
            "Department": get_po_department(po),
            "Department ID": get_po_department_id(po),
            "Cost centre": get_po_cost_center(po),
            "Status": get_status(po),
            "Currency": po.get("currency") or "-",
            "Line items": len(get_items(po)),
        })

    st.dataframe(
        table,
        use_container_width=True,
        hide_index=True,
        height=get_dataframe_height(len(table)),
    )

    st.divider()
    po_numbers = [get_po_number(po) for po in filtered]
    selected_po = st.selectbox(
        "Select a PO to inspect", po_numbers, key="po_detail_selection"
    )
    selected_record = next(
        po for po in filtered if get_po_number(po) == selected_po
    )
    render_po_details(selected_record)


# ==================================================
# CREATE PURCHASE ORDER - PREVIEW + SAVE
# ==================================================


def render_create_po(reference, user=None):
    st.markdown("### Create a purchase order")
    st.info(
        "Prepare a PO preview, then save it as a structured JSON record. "
        "New records use data/purchase_orders/po_<po_id>.json. Newly created POs "
        "start as PENDING and are not eligible for goods receipt until approved."
    )

    vendor_options = get_vendor_options(reference)
    if not vendor_options:
        st.warning(
            "No vendor records were found. You can still enter a vendor name "
            "for this temporary preview."
        )

    item_count = st.number_input(
        "Number of line items",
        min_value=1,
        max_value=8,
        value=1,
        step=1,
        key="po_item_count",
    )

    with st.form("create_po_preview_form"):
        st.markdown("#### 1. Vendor details")
        if vendor_options:
            vendor_name = st.selectbox("Select vendor", vendor_options)
        else:
            vendor_name = st.text_input("Vendor name")

        currencies = sorted({
            str(po.get("currency") or "INR")
            for po in reference.get("purchase_orders", [])
            if isinstance(po, dict)
        })
        if not currencies:
            currencies = ["INR"]
        if "INR" not in currencies:
            currencies.insert(0, "INR")

        currency = st.selectbox("Currency", currencies)
        tolerance = st.number_input(
            "Price tolerance (%)",
            min_value=0.0,
            max_value=100.0,
            value=1.0,
            step=0.25,
        )

        st.divider()
        st.markdown("#### 2. Department and budget mapping")
        st.caption(
            "Select a department from dataset/reference_data.json. The department "
            "ID is saved on the PO so the budget checker can resolve it. The "
            "department budgets in this dataset are demonstration figures, not "
            "verified university financial data."
        )
        department_options = get_department_options(reference)
        selected_department = None
        if department_options:
            department_labels = {
                f"{item['name']} ({item['department_id']})": item
                for item in department_options
            }
            selected_label = st.selectbox(
                "Department",
                options=list(department_labels),
                key="po_department",
            )
            selected_department = department_labels[selected_label]
            department = selected_department["name"]
            department_id = selected_department["department_id"]
            cost_center = selected_department.get("cost_center")
            st.caption(f"Department ID: {department_id}")
            if cost_center:
                st.caption(f"Cost centre: {cost_center}")
            else:
                st.caption("Cost-centre master data is not available; left unassigned.")
        else:
            department = None
            department_id = None
            cost_center = None
            st.warning(
                "No department records with IDs were found in the reference data. "
                "This PO cannot be created with a verified department mapping."
            )
            st.selectbox(
                "Department",
                options=["No department records available"],
                disabled=True,
                key="po_department_unavailable",
            )

        st.divider()
        st.markdown("#### 3. Purchase order items")
        st.caption(
            "Enter the agreed unit price from the vendor quotation. Quantity and price "
            "start blank, so you do not need to clear default numbers."
        )
        st.info(
            "Tax is not guessed or manually set here. It should come from the approved "
            "vendor quotation or the item's tax/HSN master data. Until that data is "
            "connected, this PO stores a pre-tax subtotal and GST-rate matching is not "
            "available for this newly created PO."
        )
        draft_items = []

        for index in range(int(item_count)):
            st.markdown(f"**Item {index + 1}**")
            description = st.text_input(
                "Item description",
                key=f"po_item_description_{index}",
            )
            col1, col2 = st.columns(2)
            with col1:
                quantity_input = st.text_input(
                    "Quantity",
                    placeholder="Enter quantity",
                    key=f"po_item_quantity_text_{index}",
                )
            with col2:
                unit_price_input = st.text_input(
                    "Unit price",
                    placeholder="Enter agreed unit price",
                    key=f"po_item_price_text_{index}",
                )

            draft_items.append({
                "description": description.strip(),
                "quantity_input": quantity_input,
                "unit_price_input": unit_price_input,
            })
            st.divider()

        submitted = st.form_submit_button(
            "Generate PO preview",
            type="primary",
            use_container_width=True,
        )

    if submitted:
        # Remove an older preview before validating the newly submitted form.
        st.session_state.pop("po_draft_preview", None)
        vendor_name = str(vendor_name or "").strip()
        if not vendor_name:
            st.error("Please provide a vendor name.")
        else:
            try:
                normalized_items = []
                for item_number, item in enumerate(draft_items, start=1):
                    description = item["description"]
                    if not description:
                        raise ValueError(
                            f"Enter an item description for item {item_number}."
                        )
                    quantity = parse_positive_number(
                        item["quantity_input"], "Quantity", item_number
                    )
                    unit_price = parse_positive_number(
                        item["unit_price_input"], "Unit price", item_number
                    )
                    normalized_items.append({
                        "description": description,
                        "quantity_ordered": quantity,
                        "approved_unit_price": unit_price,
                    })
            except ValueError as exc:
                st.error(str(exc))
            else:
                subtotal = sum(
                    item["quantity_ordered"] * item["approved_unit_price"]
                    for item in normalized_items
                )
                po_id = get_next_po_id(reference.get("purchase_orders", []))
                if not isinstance(selected_department, dict):
                    st.error(
                        "A department ID from the reference data is required. "
                        "The PO preview was not created."
                    )
                    return

                st.session_state["po_draft_preview"] = {
                    "po_id": po_id,
                    "po_number": f"PO-{po_id}",
                    "vendor": vendor_name,
                    "vendor_id": get_vendor_id(reference, vendor_name),
                    "department": department,
                    "department_id": department_id,
                    "cost_center": cost_center,
                    "currency": currency,
                    "tolerance": tolerance,
                    "items": normalized_items,
                    "subtotal": subtotal,
                    "tax": None,
                    "total": subtotal,
                }

    draft = st.session_state.get("po_draft_preview")
    if draft:
        st.divider()
        st.markdown("### Purchase order preview")
        st.warning(
            "This is not saved yet. Use Save purchase order to create "
            f"po_{draft['po_id']}.json."
        )

        c1, c2, c3 = st.columns(3)
        c1.metric("PO Number", draft["po_number"])
        c2.metric("Vendor", draft["vendor"])
        c3.metric("Line items", len(draft["items"]))
        st.caption(
            f"PO ID: {draft['po_id']} · Price tolerance: {draft['tolerance']}% "
            "· Status after save: PENDING"
        )
        st.write(f"**Department:** {draft.get('department', 'UNASSIGNED')}")
        st.write(f"**Department ID:** {draft.get('department_id', 'UNASSIGNED')}")
        st.write(f"**Cost centre:** {draft.get('cost_center') or 'UNASSIGNED'}")

        st.markdown("**Items**")
        preview_rows = []
        for item in draft["items"]:
            preview_rows.append({
                "Description": item["description"],
                "Quantity": item["quantity_ordered"],
                "Unit price": format_amount(
                    item["approved_unit_price"], draft["currency"]
                ),
                "Tax": "Not specified",
            })
        st.dataframe(
            preview_rows,
            use_container_width=True,
            hide_index=True,
            height=get_dataframe_height(len(preview_rows)),
        )

        st.markdown("**Financial summary**")
        st.write(
            "PO subtotal before tax: "
            + format_amount(draft["subtotal"], draft["currency"])
        )
        st.write("Tax: Not specified — use the approved quotation or item tax master.")
        st.subheader(
            "PO subtotal (tax not included): "
            + format_amount(draft["total"], draft["currency"])
        )

        save_col, clear_col = st.columns(2)
        if save_col.button(
            f"Save purchase order as po_{draft['po_id']}.json",
            type="primary",
            use_container_width=True,
            key="save_po_record",
        ):
            try:
                # Recheck IDs immediately before writing so a stale preview
                # cannot replace a PO created by another session.
                latest_reference = load_procurement_data()
                latest_next_id = get_next_po_id(
                    latest_reference.get("purchase_orders", [])
                )
                if latest_next_id != int(draft["po_id"]):
                    st.error(
                        f"The next PO ID is now {latest_next_id}. Clear this preview "
                        "and generate it again to avoid an ID collision."
                    )
                else:
                    po_record = {
                        "po_id": int(draft["po_id"]),
                        "record_id": f"po_{int(draft['po_id'])}",
                        "po_number": draft["po_number"],
                        "vendor_id": draft.get("vendor_id"),
                        "vendor": draft["vendor"],
                        "vendor_name": draft["vendor"],
                        "department": draft.get("department"),
                        "department_id": draft.get("department_id"),
                        "cost_center": draft.get("cost_center"),
                        "currency": draft["currency"],
                        "price_tolerance_percent": float(draft["tolerance"]),
                        "status": "PENDING",
                        "items": draft["items"],
                        "subtotal": float(draft["subtotal"]),
                        "tax": None,
                        "tax_status": "NOT_SPECIFIED",
                        "total_amount": float(draft["total"]),
                        "total_amount_includes_tax": False,
                        "total_amount_basis": "PRE_TAX_SUBTOTAL",
                        "created_by": (user or {}).get("username"),
                    }
                    saved_path = save_purchase_order(draft["po_id"], po_record)
                    relative_path = saved_path.relative_to(BASE_DIR)
                    st.session_state["po_saved_message"] = (
                        "Purchase order saved successfully: "
                        + str(relative_path)
                        + " · " + draft["po_number"]
                    )
                    st.session_state.pop("po_draft_preview", None)
                    st.rerun()
            except (RecordStoreError, TypeError, ValueError) as exc:
                st.error("The purchase order was not saved. " + str(exc))

        if clear_col.button(
            "Clear PO preview",
            use_container_width=True,
            key="clear_po_preview",
        ):
            st.session_state.pop("po_draft_preview", None)
            st.rerun()


# ==================================================
# MAIN PO PAGE
# ==================================================


def render_po_page(user):
    """Render the purchase order management interface."""
    role = str(user.get("role") or "").strip().lower()
    if role != "procurement_officer":
        st.error("You do not have permission to manage purchase orders.")
        st.caption("Detected role: " + repr(role))
        return

    st.title("Purchase order management")
    st.caption("Create, inspect and track university purchase orders.")

    saved_message = st.session_state.pop("po_saved_message", None)
    if saved_message:
        st.success(saved_message)

    st.info(
        "Existing procurement records are read from the reference dataset. "
        "New purchase orders are saved separately using the requested "
        "po_<po_id>.json naming format."
    )

    reference = load_procurement_data()
    purchase_orders = reference.get("purchase_orders", [])
    if not isinstance(purchase_orders, list):
        purchase_orders = []
    purchase_orders = [po for po in purchase_orders if isinstance(po, dict)]

    dashboard_tab, orders_tab, create_tab = st.tabs(
        ["Dashboard", "All purchase orders", "Create purchase order"]
    )
    with dashboard_tab:
        render_po_dashboard(purchase_orders)
    with orders_tab:
        render_po_list(purchase_orders)
    with create_tab:
        render_create_po(reference, user=user)
