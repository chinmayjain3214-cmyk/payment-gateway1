import os
import psycopg2
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

DB_NAME = os.getenv("DB_NAME", "invoice_db")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")

def generate_audit_report():
    try:
        connection = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        cursor = connection.cursor()
        print("==================================================")
        print("          AI AP AGENT - AUDIT DISCREPANCY REPORT   ")
        print("==================================================\n")

        # Query audit logs joined with invoices and vendors
        query = """
            SELECT 
                a.id AS audit_id,
                a.invoice_id,
                v.name AS vendor_name,
                a.discrepancy_type,
                a.details,
                a.flagged_at
            FROM audit_logs a
            JOIN invoices i ON a.invoice_id = i.id
            JOIN vendors v ON i.vendor_id = v.id
            ORDER BY a.flagged_at DESC;
        """
        cursor.execute(query)
        logs = cursor.fetchall()

        if not logs:
            print("✨ No discrepancies found! All invoices passed verification.")
            return

        for log in logs:
            audit_id, invoice_id, vendor_name, disc_type, details, flagged_at = log
            print(f"🚨 Audit Record #{audit_id}")
            print(f"   • Vendor: {vendor_name}")
            print(f"   • Invoice ID: #{invoice_id}")
            print(f"   • Discrepancy Type: [{disc_type}]")
            print(f"   • Details: {details}")
            print(f"   • Timestamp: {flagged_at}")
            print("-" * 50)

        print(f"\nTotal Flagged Discrepancies Reviewed: {len(logs)}")

    except Exception as e:
        print(f"Error generating audit report: {e}")
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'connection' in locals(): connection.close()

if __name__ == "__main__":
    generate_audit_report()