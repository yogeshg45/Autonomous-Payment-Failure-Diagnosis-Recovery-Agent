# ============================================================
# Razorpay Real Test-Mode Data Pull — for schema validation
# Run this in Google Colab.
# ============================================================
# WHAT THIS DOES:
#   1. Creates real Orders via Razorpay's live Test Mode API
#      (genuine API calls, genuine order objects, genuine IDs)
#   2. Fetches back real Order + Payment JSON so you have
#      authentic Razorpay response schemas to validate your
#      synthetic generator against
#
# WHAT THIS DOES NOT DO:
#   Razorpay's test-mode checkout only exposes a generic
#   Success/Failure toggle on the mock bank page — it does NOT
#   let you trigger specific error codes (card_expired,
#   insufficient_funds, etc.) via the API or test cards.
#   So this script gives you real schema + a real success/fail
#   split, but NOT the granular error-code diversity — that
#   part stays honestly-labeled simulation, sourced from
#   Razorpay's own published error-code docs.
#
# SECURITY: never hardcode your key/secret in a cell you'll
# share or push to git. This uses getpass so it's typed once
# per session and not stored in the notebook file.
# ============================================================

get_ipython().system('pip install razorpay -q')

import razorpay
import json
import time
from getpass import getpass

# --- Auth (entered locally, not stored in notebook) ---
KEY_ID = getpass("Enter your Razorpay TEST Key ID (rzp_test_...): ")
KEY_SECRET = getpass("Enter your Razorpay TEST Key Secret: ")

client = razorpay.Client(auth=(KEY_ID, KEY_SECRET))

# --- Step 1: Create a batch of real test-mode orders ---
NUM_ORDERS = 20
amounts_in_rupees = [round(100 + i * 137.5, 2) for i in range(NUM_ORDERS)]

created_orders = []
for i, amt in enumerate(amounts_in_rupees):
    amount_paise = int(amt * 100)  # Razorpay amounts are in paise
    order_data = {
        "amount": amount_paise,
        "currency": "INR",
        "receipt": f"buildthon_receipt_{i:03d}",
        "notes": {
            "purpose": "razorpay_buildthon_2026_schema_validation",
            "batch_index": str(i)
        }
    }
    try:
        order = client.order.create(data=order_data)
        created_orders.append(order)
        print(f"[{i+1}/{NUM_ORDERS}] Created order {order['id']} for ₹{amt}")
    except Exception as e:
        print(f"[{i+1}/{NUM_ORDERS}] FAILED to create order: {e}")
    time.sleep(0.3)  # be polite to the API

print(f"\n✓ Created {len(created_orders)} real orders in Razorpay test mode.")

# --- Step 2: Save real order objects for schema reference ---
with open("real_razorpay_orders.json", "w") as f:
    json.dump(created_orders, f, indent=2)
print("✓ Saved real_razorpay_orders.json — genuine Razorpay Order objects")

# --- Step 3 (manual step required — read this) ---
print("""
NEXT STEP (manual, ~10-15 min, outside Colab):
Colab can't drive a real browser checkout. To get real PAYMENT
objects (not just orders), you need to:

  1. Go to https://dashboard.razorpay.com > Payment Links (Test Mode)
     and create a payment link for a couple of these orders' amounts,
     OR use the standard Checkout.js on any simple HTML page with your
     Key ID.
  2. Complete a few test payments using Razorpay's published test
     cards (Visa 4111 1111 1111 1111 or the ones in their docs),
     clicking "Success" on some and "Failure" on others in the mock
     bank page.
  3. Come back here and run Step 4 below to fetch the REAL payment
     objects Razorpay recorded for those attempts.
""")

# --- Step 4: Fetch real payments after you've made a few manually ---
def fetch_recent_payments(count=20):
    payments = client.payment.all({"count": count})
    with open("real_razorpay_payments.json", "w") as f:
        json.dump(payments, f, indent=2)
    print(f"✓ Fetched {len(payments.get('items', []))} real payment objects")
    print("✓ Saved real_razorpay_payments.json")
    return payments

# Uncomment and run after completing manual test payments:
# real_payments = fetch_recent_payments()
