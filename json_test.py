import os
import json
import time
from dotenv import load_dotenv
from google import genai

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"), http_options={"timeout": 30000})

MODEL = "gemini-3.1-flash-lite"

text = "Invoice INV-101 from Acme Traders: 5 pens at 20 rupees each, 2 notebooks at 50 rupees each."

response = None
for attempt in range(1, 6):
    try:
        response = client.models.generate_content(
            model=MODEL,
            contents="Extract the invoice number, vendor and line items (name, quantity, unit_price) from this text: " + text,
            config={"response_mime_type": "application/json"},
        )
        break
    except Exception as e:
        print("Attempt", attempt, "failed:", str(e)[:120])
        time.sleep(10)

if response is None:
    print("Gemini is too busy right now. Try again later.")
else:
    data = json.loads(response.text)
    print(data)
    print("Vendor is:", data["vendor"])