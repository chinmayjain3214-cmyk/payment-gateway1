
import json
import tempfile
from pathlib import Path

from checks import check_line_math, check_vendor
from extract_invoice import extract_invoice, SUPPORTED_TYPES
from tools import find_po


BASE_DIR = Path(__file__).resolve().parent

INVOICE_DIR = BASE_DIR / "invoices"
CACHE_DIR = BASE_DIR / "data" / "invoices"

CACHE_VERSION = 2


def get_invoice_data(path):
    """
    Read an invoice, reuse a valid extraction cache when possible,
    and safely save newly extracted JSON.

    A cache-writing failure must not discard a successful extraction.
    """

    path = Path(path)

    # Check that the original invoice exists.
    try:
        if not path.is_file():
            print("[invoice error] File does not exist:", path)
            return None

        source_stat = path.stat()

    except OSError as e:
        print("[invoice error] Could not access file:", str(e)[:150])
        return None

    cache_file = CACHE_DIR / (path.name + ".json")

    # 1. Try reading the existing cache.
    if cache_file.exists():
        try:
            cached = json.loads(
                cache_file.read_text(encoding="utf-8")
            )

            if (
                isinstance(cached, dict)
                and cached.get("_cache_version") == CACHE_VERSION
                and cached.get("_source_size") == source_stat.st_size
                and cached.get("_source_mtime_ns") == source_stat.st_mtime_ns
            ):
                cached_data = cached.get("data")

                if isinstance(cached_data, (dict, list)):
                    return cached_data

        except (json.JSONDecodeError, OSError) as e:
            print(
                "[cache warning] Existing cache could not be read:",
                str(e)[:120]
            )

    # 2. Extract again if cache is missing or outdated.
    try:
        data = extract_invoice(str(path))

    except Exception as e:
        print(
            "[extraction error]",
            path.name,
            str(e)[:150]
        )
        return None

    if not isinstance(data, (dict, list)):
        print("[extraction error] No valid invoice data:", path.name)
        return None

    # 3. Try saving the cache without discarding extracted data.
    temporary_path = None

    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

        cache_data = {
            "_cache_version": CACHE_VERSION,
            "_source_size": source_stat.st_size,
            "_source_mtime_ns": source_stat.st_mtime_ns,
            "data": data,
        }

        # Use a temporary file and atomic replacement.
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=CACHE_DIR,
            prefix=cache_file.name + ".",
            suffix=".tmp",
            delete=False,
        ) as temp_file:

            temporary_path = Path(temp_file.name)

            json.dump(
                cache_data,
                temp_file,
                indent=2,
                ensure_ascii=False,
                default=str,
            )

        temporary_path.replace(cache_file)

    except (OSError, TypeError, ValueError) as e:
        print(
            "[cache warning] Extraction succeeded, "
            "but cache could not be saved:",
            str(e)[:150]
        )

        # Keep the extracted data even if caching failed.
        return data

    finally:
        if temporary_path is not None and temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError:
                pass

    return data


def main():
    """Process all supported invoices in the invoices folder."""

    if not INVOICE_DIR.is_dir():
        print("[error] The invoices folder does not exist.")
        return

    try:
        files = sorted(
            path
            for path in INVOICE_DIR.iterdir()
            if path.is_file()
            and path.suffix.lower() in SUPPORTED_TYPES
        )

    except OSError as e:
        print("[error] Could not list invoices:", str(e)[:150])
        return

    if not files:
        print("No supported invoice files were found.")
        return

    for path in files:

        print("=== " + path.name + " ===")

        data = get_invoice_data(path)

        if data is None:
            print("  Extraction failed -> manual review")
            continue

        # Handle a model response containing multiple invoices.
        if isinstance(data, list):
            data = data[0] if data else None

        if not isinstance(data, dict):
            print("  Invalid extraction result -> manual review")
            continue

        # 1. Check invoice arithmetic.
        try:
            issues = check_line_math(data)

            if issues:
                for issue in issues:
                    print(
                        "  ! "
                        + issue.get("type", "UNKNOWN")
                        + ": "
                        + issue.get("detail", "")
                    )
            else:
                print("  math: OK")

        except Exception as e:
            print("  math check failed:", str(e)[:150])

        # 2. Find the purchase order.
        po_number = str(
            data.get("po_number")
            or data.get("po_reference")
            or ""
        ).strip().upper()

        if not po_number:
            print("  No PO number -> manual review")
            continue

        try:
            result = find_po(po_number)

        except Exception as e:
            print("  PO lookup failed:", str(e)[:150])
            continue

        print("  extracted PO:", po_number)
        print(
            "  status:",
            result.get("status", "unknown"),
            "|",
            result.get("note", "")
        )

        # 3. Check vendor identity if the PO was found.
        po = result.get("po")

        if isinstance(po, dict):

            try:
                vendor_check = check_vendor(
                    data.get("vendor") or data.get("vendor_name"),
                    po.get("vendor") or po.get("vendor_name"),
                    invoice_vendor_id=data.get("vendor_id"),
                    po_vendor_id=po.get("vendor_id"),
                )

                print(
                    "  vendor:",
                    vendor_check["status"],
                    "|",
                    vendor_check["note"]
                )

            except Exception as e:
                print("  vendor check failed:", str(e)[:150])


if __name__ == "__main__":
    main()
