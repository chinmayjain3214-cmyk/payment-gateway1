import os
import json
import psycopg2
from dotenv import load_dotenv
from matcher import run_three_way_matching

# Load environment variables from .env
load_dotenv()

DB_NAME = os.getenv("DB_NAME", "invoice_db")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")

def ingest_incoming_invoice(invoice_payload):
    """
    Takes Person A's incoming JSON invoice payload, inserts it into 
    the invoices table, and automatically triggers the 3-way matching engine.
    """
    try:
        connection = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        cursor = connection.cursor()

        # Unpack Person A's JSON contract
        vendor_id = invoice_payload.get("vendor_id")
        po_id = invoice_payload.get("po_id")
        total_amount = invoice_payload.get("total_amount")
        status = invoice_payload.get("status", "PENDING")
        line_items = json.dumps(invoice_payload.get("line_items", []))

        # Insert into PostgreSQL and capture the new ID
        cursor.execute("""
            INSERT INTO invoices (po_id, vendor_id, total_amount, status, line_items)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id;
        """, (po_id, vendor_id, total_amount, status, line_items))
        
        new_invoice_id = cursor.fetchone()[0]
        connection.commit()
        print(f"📥 [INGESTION SUCCESS] Invoice #{new_invoice_id} received from API and saved to DB.")

        # Immediately trigger the matching engine
        print("\n⚡ Automatically triggering 3-Way Matching Engine...")
        run_three_way_matching()

    except Exception as e:
        print(f"Error ingesting invoice: {e}")
        if 'connection' in locals():
            connection.rollback()
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'connection' in locals(): connection.close()

if __name__ == "__main__":
    # Example test payload simulating what Person A's parser API sends over
    sample_api_payload = {
        "vendor_id": 3,
        "po_id": 3,
        "total_amount": 12000.00,
        "status": "PENDING",
        "line_items": [
            {
                "name": "Printer Paper",
                "qty": 100,
                "unit_price": 120.00
            }
        ]
    }
    
    ingest_incoming_invoice(sample_api_payload)