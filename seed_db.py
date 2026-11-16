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

def seed_database():
    try:
        connection = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        cursor = connection.cursor()
        print("Connected to PostgreSQL successfully. Starting data seeding...")

        # Clear existing data and reset IDs to 1 safely
        cursor.execute("""
            TRUNCATE TABLE audit_logs, invoices, goods_receipts, purchase_orders, vendors 
            RESTART IDENTITY CASCADE;
        """)
        print("✓ Reset existing tables.")

        # 1. Seed Vendors (5 Vendors - IDs 1 to 5)
        vendors_data = [
            ("TechCorp Supplies", "contact@techcorp.com", "+91-9876543210", "101 Silicon Valley, Jaipur"),
            ("Global Logistics Ltd", "billing@globallogistics.com", "+91-9123456789", "45 Industrial Area, Delhi"),
            ("Office Essentials Co", "sales@officeessentials.in", "+91-9988776655", "12 Market Road, Mumbai"),
            ("Apex Cloud Services", "finance@apexcloud.io", "+91-9345678901", "78 Tech Park, Bengaluru"),
            ("SecureGuard Systems", "support@secureguards.com", "+91-9765432109", "99 Defense Colony, Pune")
        ]
        
        cursor.executemany("""
            INSERT INTO vendors (name, email, phone, address) 
            VALUES (%s, %s, %s, %s);
        """, vendors_data)
        print("✓ Seeded 5 Vendors.")

        # 2. Seed Purchase Orders (POs) (10 POs mapped to vendors 1-5)
        po_data = [
            (1, 150000.00, 'APPROVED'),
            (2, 85000.00, 'APPROVED'),
            (3, 12000.00, 'APPROVED'),
            (4, 300000.00, 'APPROVED'),
            (5, 45000.00, 'APPROVED'),
            (1, 75000.00, 'APPROVED'),
            (2, 60000.00, 'APPROVED'),
            (3, 25000.00, 'APPROVED'),
            (4, 150000.00, 'APPROVED'),
            (5, 90000.00, 'APPROVED')
        ]

        cursor.executemany("""
            INSERT INTO purchase_orders (vendor_id, total_amount, status)
            VALUES (%s, %s, %s);
        """, po_data)
        print("✓ Seeded 10 Purchase Orders.")

        # 3. Seed Goods Receipts (GRNs) matching POs and valid vendor IDs (1-5)
        grn_data = [
            (1, 1, 'RECEIVED', 'All items received in good condition'),
            (2, 2, 'RECEIVED', 'Shipment complete'),
            (3, 3, 'RECEIVED', 'Delivered to office reception'),
            (4, 4, 'RECEIVED', 'Server infrastructure deployed'),
            (5, 5, 'RECEIVED', 'Security hardware installed'),
            (6, 1, 'RECEIVED', 'Partial delivery accepted'),
            (7, 2, 'RECEIVED', 'Logistics completed successfully'),
            (8, 3, 'RECEIVED', 'Stationery stock verified'),
            (9, 4, 'RECEIVED', 'Cloud credits provisioned'),
            (10, 5, 'RECEIVED', 'Cameras and sensors delivered')
        ]

        cursor.executemany("""
            INSERT INTO goods_receipts (po_id, vendor_id, status, notes)
            VALUES (%s, %s, %s, %s);
        """, grn_data)
        print("✓ Seeded 10 Goods Receipts.")

        # 4. Seed Invoices (Including Normal & Trap Cases with valid vendor IDs 1-5)
        invoice_data = [
            # Normal matching invoice (PO 1, Vendor 1)
            (1, 1, 150000.00, 'PAID', '{"items": [{"name": "Server Racks", "qty": 5, "unit_price": 30000}]}'),
            # Trap 1: Price Hike (PO 2 was 85000, Invoice is 95000, Vendor 2)
            (2, 2, 95000.00, 'PENDING', '{"items": [{"name": "Logistics Services", "qty": 1, "unit_price": 95000}]}'),
            # Normal matching invoice (PO 3, Vendor 3)
            (3, 3, 12000.00, 'PAID', '{"items": [{"name": "Printer Paper", "qty": 100, "unit_price": 120}]}'),
            # Trap 2: Quantity Mismatch (PO 4, Vendor 4)
            (4, 4, 320000.00, 'PENDING', '{"items": [{"name": "Cloud Subscriptions", "qty": 35, "unit_price": 9142.85}]}'),
            # Trap 3: Duplicate Invoice pattern (PO 5, Vendor 5)
            (5, 5, 45000.00, 'PENDING', '{"items": [{"name": "CCTV Cameras", "qty": 10, "unit_price": 4500}]}'),
            # Normal invoice (PO 6, Vendor 1)
            (6, 1, 75000.00, 'PAID', '{"items": [{"name": "Hardware Kits", "qty": 15, "unit_price": 5000}]}'),
            # Trap 4: Discrepancy case (PO 7, Vendor 2)
            (7, 2, 60000.00, 'PENDING', '{"items": [{"name": "Freight Transport", "qty": 2, "unit_price": 30000}]}'),
        ]

        cursor.executemany("""
            INSERT INTO invoices (po_id, vendor_id, total_amount, status, line_items)
            VALUES (%s, %s, %s, %s, %s);
        """, invoice_data)
        print("✓ Seeded 7 Test & Trap Invoices.")

        connection.commit()
        print("\n🚀 Database seeding completed successfully with normal records and trap cases!")

    except Exception as e:
        print(f"Error seeding database: {e}")
        if 'connection' in locals():
            connection.rollback()
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'connection' in locals(): connection.close()

if __name__ == "__main__":
    seed_database()