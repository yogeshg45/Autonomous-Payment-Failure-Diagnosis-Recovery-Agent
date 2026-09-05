"""
Panel Transaction Entries — one plain-English card per error code
====================================================================
WHY THIS EXISTS:
A judging panel does not read 750 audit-trail rows. They read a
short, honest catalog: "here are the distinct ways revenue leaked in
this batch, here's what each one means in plain English, here's what
the agent did, here's how much money it involves." That's what this
script builds.

EFFICIENCY, ON PURPOSE:
This calls the LLM (Groq/GPT-OSS by default) ONCE PER UNIQUE ERROR
CODE that actually occurred in the batch — typically 15-25 codes,
never per transaction. A 750-row batch costs at most ~25 LLM calls
total, run once, then cached to disk. This is the fix for "API keeps
breaking / rate limit exceeded": the live demo never depends on a
live call happening at all, because the explanations already exist
in outputs/transaction_entries.json before anyone asks a question.

INPUT:  outputs/audit_trail.json (produced by revenue_recovery_agent.py)
OUTPUT: outputs/transaction_entries.json — one entry per error code:
        {
          "error_code": "...",
          "root_cause": "CUSTOMER_SIDE" | "SYSTEM_SIDE" | "MERCHANT_SIDE",
          "technical_description": "...",       # from Razorpay's own taxonomy
          "plain_english": "...",                # LLM or rule-based, panel-facing
          "action_taken": "...",
          "occurrences": 41,
          "amount_at_risk_inr": 205000,
          "amount_recovered_inr": 123000,
          "recovery_rate_pct": 60.0,
          "sample_transaction_ids": ["txn_000012", ...],
          "explained_by": "groq" | "rule_based"
        }

Run standalone any time after the batch agent has produced an audit
trail: python3 src/panel_transaction_entries.py
"""

import os
import json
import sys

sys.path.insert(0, os.path.dirname(__file__))

from razorpay_error_mapping import RAZORPAY_ERROR_MAPPING
from llm_provider import explain_error_for_panel, active_provider

AUDIT_TRAIL_PATH = "outputs/audit_trail.json"
OUTPUT_PATH = "outputs/transaction_entries.json"
MAX_SAMPLE_IDS = 3


def _lookup_description(error_code):
    for cat_data in RAZORPAY_ERROR_MAPPING.values():
        if error_code in cat_data["errors"]:
            return cat_data["errors"][error_code]["description"]
    return "No description on file."


def build_entries(audit_trail_path=AUDIT_TRAIL_PATH, use_llm=True):
    with open(audit_trail_path) as f:
        records = json.load(f)

    by_error = {}
    for r in records:
        by_error.setdefault(r["error_code"], []).append(r)

    entries = []
    provider_in_use = active_provider() if use_llm else "rule_based"

    for error_code, rows in sorted(by_error.items(), key=lambda kv: -len(kv[1])):
        root_cause = rows[0]["root_cause"]
        action_taken = rows[0]["action_taken"]
        occurrences = len(rows)
        amount_at_risk = sum(r["amount"] for r in rows)
        amount_recovered = sum(r["money_recovered"] for r in rows)
        recovered_count = sum(1 for r in rows if r["recovered"])
        description = _lookup_description(error_code)

        if use_llm:
            plain_english, explained_by = explain_error_for_panel(
                error_code, description, root_cause, action_taken,
                occurrences, amount_at_risk, amount_recovered,
            )
        else:
            from llm_provider import _rule_based_panel_entry
            plain_english = _rule_based_panel_entry(
                error_code, description, root_cause, action_taken,
                occurrences, amount_at_risk, amount_recovered,
            )
            explained_by = "rule_based"

        entries.append({
            "error_code": error_code,
            "root_cause": root_cause,
            "technical_description": description,
            "plain_english": plain_english,
            "action_taken": action_taken,
            "occurrences": occurrences,
            "amount_at_risk_inr": amount_at_risk,
            "amount_recovered_inr": amount_recovered,
            "recovery_rate_pct": round(recovered_count / occurrences * 100, 1) if occurrences else 0.0,
            "sample_transaction_ids": [r["transaction_id"] for r in rows[:MAX_SAMPLE_IDS]],
            "explained_by": explained_by,
        })

    return entries, provider_in_use


def main():
    if not os.path.exists(AUDIT_TRAIL_PATH):
        print(f"ERROR: {AUDIT_TRAIL_PATH} not found. Run src/revenue_recovery_agent.py first.")
        return

    print("=" * 72)
    print("BUILDING PANEL-FRIENDLY TRANSACTION ENTRY CATALOG")
    print("=" * 72)
    print(f"LLM provider in use: {active_provider()}  "
          f"(falls back to rule_based automatically per entry if a call fails)\n")

    entries, provider_in_use = build_entries()

    os.makedirs("outputs", exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump({
            "provider_configured": provider_in_use,
            "total_unique_error_codes": len(entries),
            "entries": entries,
        }, f, indent=2)

    for e in entries:
        icon = {"CUSTOMER_SIDE": "🧍", "SYSTEM_SIDE": "🌐", "MERCHANT_SIDE": "🏪"}.get(e["root_cause"], "❓")
        print(f"{icon} {e['error_code']}  ({e['occurrences']}x, ₹{e['amount_at_risk_inr']:,} at risk, "
              f"explained_by={e['explained_by']})")
        print(f"   {e['plain_english']}")
        print()

    print(f"Saved {len(entries)} entries -> {OUTPUT_PATH}")
    print(f"Total LLM calls made this run: at most {len(entries)} (one per unique error code, not per transaction)")


if __name__ == "__main__":
    main()
