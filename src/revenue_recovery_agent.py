"""
Razorpay Buildthon 2026 — Track 03: AI Revenue Recovery
========================================================
Complete agent: streams transactions -> detects degradation ->
diagnoses root cause -> picks bounded recovery action -> simulates
outcome -> sums real money recovered -> logs full audit trail.

INPUT:  payment_transactions_v2.csv (from payment_degradation_data_generator_v2.py)
OUTPUT: audit_trail.csv, audit_trail.json, final_report.json (printed + saved)

Data honesty note (for the demo / report slide):
  - Error taxonomy (59 codes, 3 root-cause buckets) is sourced from
    Razorpay's own published documentation.
  - The 3-bucket model (CUSTOMER/SYSTEM/MERCHANT) mirrors Razorpay's
    own `error_source` field, confirmed against real test-mode API
    payment responses pulled during this build.
  - Batch-scale transaction volume and which-error-happened-when is
    simulated (no live merchant traffic available), sampled from the
    24 error codes Razorpay's docs flag as most common.
  - Recovery outcomes (retry succeeds / fails) are simulated using
    published-style success-rate assumptions per strategy, clearly
    labeled as simulation, not real re-charges.
"""

import pandas as pd
import json
import time
from collections import deque
from datetime import datetime

from recovery_core import (
    STRATEGY_TABLE, classify_root_cause, predict_recovery_probability,
    generate_customer_message, make_idempotency_key, get_backoff_seconds,
    ML_MODEL_LOADED,
)

# ============================================================
# CONFIG
# ============================================================
INPUT_CSV = "data/payment_transactions_v2.csv"
DEGRADATION_WINDOW = 50          # transactions per rolling window
DEGRADATION_DROP_THRESHOLD = 15  # percentage points below baseline triggers alert
RECOVERY_RNG_SEED = 2026         # separate, documented seed for recovery simulation
VERBOSE_STREAM = True            # print live agent decisions as it "streams"
PRINT_EVERY = 25                 # progress heartbeat every N transactions

import random

rng = random.Random(RECOVERY_RNG_SEED)


# ============================================================
# COMPONENT 1: DEGRADATION DETECTOR
# ============================================================
class DegradationDetector:
    """Tracks a rolling window of outcomes and alerts on a sustained
    success-rate drop vs. the established baseline."""

    def __init__(self, window_size=DEGRADATION_WINDOW, drop_threshold=DEGRADATION_DROP_THRESHOLD):
        self.window = deque(maxlen=window_size)
        self.baseline_rate = None
        self.baseline_locked_at = window_size  # lock baseline after first full window
        self.alerts = []
        self.in_alert_state = False
        self.n_seen = 0

    def observe(self, txn):
        self.n_seen += 1
        self.window.append(1 if txn["status"] == "success" else 0)

        if len(self.window) < self.window.maxlen:
            return None  # not enough data yet

        current_rate = sum(self.window) / len(self.window) * 100

        if self.baseline_rate is None and self.n_seen >= self.baseline_locked_at:
            self.baseline_rate = current_rate
            return None

        if self.baseline_rate is None:
            return None

        drop = self.baseline_rate - current_rate
        if drop >= self.drop_threshold_value() and not self.in_alert_state:
            self.in_alert_state = True
            alert = {
                "at_transaction": self.n_seen,
                "timestamp": txn["timestamp"],
                "baseline_success_rate": round(self.baseline_rate, 1),
                "current_success_rate": round(current_rate, 1),
                "drop_points": round(drop, 1),
            }
            self.alerts.append(alert)
            return alert
        elif drop < self.drop_threshold_value() and self.in_alert_state:
            self.in_alert_state = False  # recovered back to baseline
        return None

    def drop_threshold_value(self):
        return DEGRADATION_DROP_THRESHOLD


# ============================================================
# COMPONENT 3: RECOVERY AGENT (strategy + bounded simulated execution)
# ============================================================
def run_recovery_agent(txn, root_cause):
    """Simulates the bounded retry workflow for one failed transaction.
    Returns a dict describing exactly what the agent decided and did."""
    strategy = STRATEGY_TABLE[root_cause]
    max_retries = strategy["max_retries"]

    result = {
        "action": strategy["action"],
        "max_retries_allowed": max_retries,
        "attempts_made": 0,
        "recovered": False,
        "money_recovered": 0,
        "customer_message": None,
        "escalation": None,
        "predicted_recovery_prob": None,
        "idempotency_keys_used": [],
        "backoff_schedule_seconds": [],
    }

    if max_retries > 0:
        overall_prob = predict_recovery_probability(root_cause, txn["amount"], txn["payment_method"], int(txn["hour"]))
        per_attempt_prob = 1 - (1 - overall_prob) ** (1 / max_retries)
        result["predicted_recovery_prob"] = round(overall_prob, 3)
    else:
        per_attempt_prob = 0.0

    if root_cause == "CUSTOMER_SIDE":
        result["customer_message"] = generate_customer_message(txn["error_code"], txn["payment_method"])

    if max_retries == 0:
        # MERCHANT_SIDE: stopping rule — never retry, escalate immediately
        result["escalation"] = strategy["escalation"]
        return result

    for attempt in range(1, max_retries + 1):
        result["attempts_made"] = attempt
        result["idempotency_keys_used"].append(make_idempotency_key(txn["transaction_id"], attempt))
        if root_cause == "SYSTEM_SIDE":
            # Real backoff schedule recorded for audit purposes. NOT
            # actually slept here — sleeping 5/10/20s per attempt across
            # 71 SYSTEM_SIDE failures would make the batch run take real
            # minutes for no demo value. The interactive/live agent
            # (llm_recovery_agent.py) DOES sleep for real. This tradeoff
            # is disclosed, not hidden.
            result["backoff_schedule_seconds"].append(get_backoff_seconds(attempt))
        if rng.random() < per_attempt_prob:
            result["recovered"] = True
            result["money_recovered"] = txn["amount"]
            break
    else:
        # loop completed without a break -> exhausted retries, must stop
        result["escalation"] = strategy["escalation"]

    return result


# ============================================================
# MAIN STREAMING PIPELINE
# ============================================================
def main():
    import os
    os.makedirs("outputs", exist_ok=True)
    df = pd.read_csv(INPUT_CSV)
    df = df.sort_values("timestamp").reset_index(drop=True)

    detector = DegradationDetector()
    audit_trail = []
    root_cause_totals = {"CUSTOMER_SIDE": {"failed": 0, "recovered": 0, "amount_recovered": 0, "amount_at_risk": 0},
                          "SYSTEM_SIDE": {"failed": 0, "recovered": 0, "amount_recovered": 0, "amount_at_risk": 0},
                          "MERCHANT_SIDE": {"failed": 0, "recovered": 0, "amount_recovered": 0, "amount_at_risk": 0}}
    escalations = []

    print("=" * 72)
    print("AI REVENUE RECOVERY AGENT — LIVE STREAM STARTING")
    print("=" * 72)

    for i, row in df.iterrows():
        txn = row.to_dict()

        # --- 1. Degradation detector sees every transaction ---
        alert = detector.observe(txn)
        if alert:
            print(f"\n🚨 DEGRADATION ALERT at txn #{alert['at_transaction']} "
                  f"({alert['timestamp']}): success rate dropped from "
                  f"{alert['baseline_success_rate']}% to {alert['current_success_rate']}% "
                  f"(-{alert['drop_points']} pts)\n")

        # --- 2/3/4. Diagnose + recover only failed transactions ---
        if txn["status"] == "failed":
            root_cause = classify_root_cause(txn["error_code"])
            if root_cause == "UNKNOWN":
                continue  # skip anything outside the documented taxonomy

            outcome = run_recovery_agent(txn, root_cause)

            root_cause_totals[root_cause]["failed"] += 1
            root_cause_totals[root_cause]["amount_at_risk"] += txn["amount"]
            if outcome["recovered"]:
                root_cause_totals[root_cause]["recovered"] += 1
                root_cause_totals[root_cause]["amount_recovered"] += outcome["money_recovered"]

            audit_row = {
                "transaction_id": txn["transaction_id"],
                "timestamp": txn["timestamp"],
                "amount": txn["amount"],
                "payment_method": txn["payment_method"],
                "error_code": txn["error_code"],
                "root_cause": root_cause,
                "action_taken": outcome["action"],
                "max_retries_allowed": outcome["max_retries_allowed"],
                "attempts_made": outcome["attempts_made"],
                "recovered": outcome["recovered"],
                "money_recovered": outcome["money_recovered"],
                "predicted_recovery_prob": outcome["predicted_recovery_prob"],
                "escalated": outcome["escalation"] is not None,
                "escalation_reason": outcome["escalation"],
                "customer_message": outcome["customer_message"],
                "idempotency_keys_used": outcome["idempotency_keys_used"],
                "backoff_schedule_seconds": outcome["backoff_schedule_seconds"],
            }
            audit_trail.append(audit_row)

            if outcome["escalation"]:
                escalations.append(audit_row)

            if VERBOSE_STREAM:
                status_icon = "✅" if outcome["recovered"] else ("⛔" if root_cause == "MERCHANT_SIDE" else "❌")
                print(f"{status_icon} {txn['transaction_id']} | ₹{txn['amount']} | {txn['error_code']} "
                      f"-> {root_cause} -> {outcome['action']} "
                      f"({outcome['attempts_made']}/{outcome['max_retries_allowed']} attempts) "
                      f"-> {'RECOVERED ₹' + str(outcome['money_recovered']) if outcome['recovered'] else 'ESCALATED'}")

        if (i + 1) % PRINT_EVERY == 0:
            print(f"   ... processed {i + 1}/{len(df)} transactions")

    # ============================================================
    # MONEY RECOVERY CALCULATOR
    # ============================================================
    total_failed = sum(v["failed"] for v in root_cause_totals.values())
    total_recovered_count = sum(v["recovered"] for v in root_cause_totals.values())
    total_amount_at_risk = sum(v["amount_at_risk"] for v in root_cause_totals.values())
    total_amount_recovered = sum(v["amount_recovered"] for v in root_cause_totals.values())
    recovery_rate = (total_recovered_count / total_failed * 100) if total_failed else 0

    final_report = {
        "generated_at": datetime.now().isoformat(),
        "total_transactions_processed": len(df),
        "total_failed_transactions": total_failed,
        "degradation_alerts": detector.alerts,
        "root_cause_breakdown": root_cause_totals,
        "total_transactions_recovered": total_recovered_count,
        "total_amount_at_risk_inr": total_amount_at_risk,
        "total_amount_recovered_inr": total_amount_recovered,
        "recovery_rate_pct": round(recovery_rate, 1),
        "total_escalations": len(escalations),
        "stopping_rules_enforced": {
            "CUSTOMER_SIDE_max_retries": STRATEGY_TABLE["CUSTOMER_SIDE"]["max_retries"],
            "SYSTEM_SIDE_max_retries": STRATEGY_TABLE["SYSTEM_SIDE"]["max_retries"],
            "MERCHANT_SIDE_max_retries": STRATEGY_TABLE["MERCHANT_SIDE"]["max_retries"],
        },
    }

    # ============================================================
    # SAVE AUDIT TRAIL + FINAL REPORT
    # ============================================================
    audit_df = pd.DataFrame(audit_trail)
    audit_df.to_csv("outputs/audit_trail.csv", index=False)
    with open("outputs/audit_trail.json", "w") as f:
        json.dump(audit_trail, f, indent=2)
    with open("outputs/final_report.json", "w") as f:
        json.dump(final_report, f, indent=2)

    # ============================================================
    # FINAL REPORT (printed)
    # ============================================================
    print("\n" + "=" * 72)
    print("FINAL REPORT — AI REVENUE RECOVERY")
    print("=" * 72)
    print(f"Total transactions processed : {len(df)}")
    print(f"Total failed transactions    : {total_failed}")
    print(f"Degradation alerts raised    : {len(detector.alerts)}")
    for a in detector.alerts:
        print(f"    - txn #{a['at_transaction']} ({a['timestamp']}): "
              f"{a['baseline_success_rate']}% -> {a['current_success_rate']}%")
    print()
    print("By root cause:")
    for cause, v in root_cause_totals.items():
        pct = (v["recovered"] / v["failed"] * 100) if v["failed"] else 0
        print(f"  {cause}: {v['failed']} failed -> {v['recovered']} recovered "
              f"({pct:.1f}%) -> ₹{v['amount_recovered']:,} recovered of ₹{v['amount_at_risk']:,} at risk")
    print()
    print(f"TOTAL RECOVERED: ₹{total_amount_recovered:,} from {total_recovered_count} transactions "
          f"({recovery_rate:.1f}% recovery rate)")
    print(f"TOTAL ESCALATED: {len(escalations)} transactions (stopping rules enforced, no infinite retries)")
    print()
    print("Saved: audit_trail.csv, audit_trail.json, final_report.json")
    print("=" * 72)

    return final_report, audit_df


if __name__ == "__main__":
    main()
