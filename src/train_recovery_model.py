"""
Recovery-Likelihood Model — the genuine ML component
======================================================
Unlike the root-cause classifier (which we proved is circular — see
classifier_predictions.csv experiment), THIS is a legitimate ML task:
predicting whether a specific failed transaction will recover if
retried, using features that are NOT already a 1:1 lookup of the
answer.

IMPORTANT — read before trusting these numbers:
  Your existing recovery simulation used a single flat success rate
  per bucket (60% / 75%), with ZERO dependence on amount, payment
  method, or timing. Training a model on that data would correctly
  learn "there's no signal here" and stop — a valid but useless result.

  To make this a real, learnable problem, we inject plausible
  feature-dependent structure into the simulation below (larger
  amounts face more risk-check friction; off-hours retries succeed
  less often; alternate-method retries perform differently depending
  on the original method). This is a documented, disclosed modeling
  choice — not a claim these exact numbers are empirically measured.
  Say so explicitly in your report: "recovery likelihood modeled with
  plausible real-world dependencies to give the ML layer genuine
  signal to learn, since raw error taxonomy alone carries none."
"""

import pandas as pd
import numpy as np
import random
import pickle
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import accuracy_score, roc_auc_score, classification_report

from razorpay_error_mapping import get_error_category

RNG_SEED = 2026
rng = np.random.RandomState(RNG_SEED)

STRATEGY_BASE_RATE = {
    "CUSTOMER_SIDE": 0.60,
    "SYSTEM_SIDE": 0.75,
    "MERCHANT_SIDE": 0.0,
}
MAX_RETRIES = {"CUSTOMER_SIDE": 2, "SYSTEM_SIDE": 3, "MERCHANT_SIDE": 0}


def true_recovery_probability(root_cause, amount, payment_method, hour):
    """The (disclosed, synthetic) ground-truth function used to
    simulate realistic recovery outcomes with genuine feature
    dependence, instead of a flat per-bucket coin flip."""
    base = STRATEGY_BASE_RATE[root_cause]
    if base == 0.0:
        return 0.0

    # Larger amounts face more risk-check friction on retry
    amount_adj = -0.20 * ((amount - 1000) / 9000)

    # Alternate-method retry performs differently depending on the
    # original method (card -> UPI tends to work well; UPI -> card
    # slightly less so, for CUSTOMER_SIDE failures)
    method_adj = 0.0
    if root_cause == "CUSTOMER_SIDE":
        method_adj = {"card": 0.05, "upi": -0.05}.get(payment_method, 0.0)
    elif root_cause == "SYSTEM_SIDE":
        method_adj = {"netbanking": -0.05}.get(payment_method, 0.0)

    # Off-hours (midnight-5am) retries succeed less often — fewer
    # active bank/gateway resources handling recovery traffic
    hour_adj = -0.10 if hour in range(0, 6) else 0.0

    prob = base + amount_adj + method_adj + hour_adj
    return float(np.clip(prob, 0.05, 0.95))


def simulate_recovered(root_cause, amount, payment_method, hour):
    max_retries = MAX_RETRIES[root_cause]
    if max_retries == 0:
        return False, 0
    overall_prob = true_recovery_probability(root_cause, amount, payment_method, hour)
    per_attempt = 1 - (1 - overall_prob) ** (1 / max_retries)
    for attempt in range(1, max_retries + 1):
        if rng.random() < per_attempt:
            return True, attempt
    return False, max_retries


def generate_training_corpus(n=3000):
    """Simulates a larger historical corpus of past failures for
    training — mirrors how this would actually work in production
    (train on months of history, apply the model to today's live
    batch). Training on only today's ~130 failures isn't enough data
    for any model to separate real signal from Bernoulli noise."""
    methods = ["card", "upi", "netbanking", "wallet"]
    causes_weighted = ["CUSTOMER_SIDE"] * 46 + ["SYSTEM_SIDE"] * 53 + ["MERCHANT_SIDE"] * 1

    rows = []
    for _ in range(n):
        root_cause = causes_weighted[rng.randint(0, len(causes_weighted))]
        amount = rng.randint(1000, 10001)
        method = methods[rng.randint(0, len(methods))]
        hour = rng.randint(0, 24)
        recovered, attempts = simulate_recovered(root_cause, amount, method, hour)
        rows.append({
            "amount": amount, "payment_method": method, "hour_int": hour,
            "root_cause": root_cause, "recovered": recovered, "attempts_made": attempts,
        })
    return pd.DataFrame(rows)


def main():
    import os
    os.makedirs('models', exist_ok=True)
    os.makedirs('outputs', exist_ok=True)

    # --- Historical training corpus (simulated, larger sample) ---
    print("=" * 70)
    print("GENERATING SIMULATED HISTORICAL TRAINING CORPUS")
    print("=" * 70)
    historical = generate_training_corpus(n=3000)
    print(f"Generated {len(historical)} historical failure records for training")
    print(historical.groupby("root_cause")["recovered"].agg(["sum", "count", "mean"]))
    print()

    # --- Today's live batch (what the agent will actually score) ---
    df = pd.read_csv("data/payment_transactions_v2.csv")
    failed = df[df["status"] == "failed"].copy()
    failed["root_cause"] = failed["error_code"].apply(get_error_category)
    failed["hour_int"] = pd.to_datetime(failed["timestamp"]).dt.hour

    # --- Simulate outcomes with genuine feature dependence ---
    recovered_list, attempts_list = [], []
    for _, row in failed.iterrows():
        rec, att = simulate_recovered(row["root_cause"], row["amount"], row["payment_method"], row["hour_int"])
        recovered_list.append(rec)
        attempts_list.append(att)
    failed["recovered"] = recovered_list
    failed["attempts_made"] = attempts_list

    print("=" * 70)
    print("SIMULATED RECOVERY OUTCOMES (feature-dependent, not flat-rate)")
    print("=" * 70)
    print(failed.groupby("root_cause")["recovered"].agg(["sum", "count", "mean"]))
    print()

    # --- Train on the HISTORICAL corpus (this is the legitimate ML step) ---
    trainable = historical[historical["root_cause"] != "MERCHANT_SIDE"].copy()

    le_method = LabelEncoder()
    le_cause = LabelEncoder()
    trainable["method_enc"] = le_method.fit_transform(trainable["payment_method"])
    trainable["cause_enc"] = le_cause.fit_transform(trainable["root_cause"])

    X = trainable[["amount", "method_enc", "hour_int", "cause_enc"]]
    y = trainable["recovered"].astype(int)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=RNG_SEED, stratify=y
    )

    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s = scaler.transform(X_test)

    # --- Baseline: always predict the bucket's flat historical rate ---
    baseline_by_cause = trainable.groupby("cause_enc")["recovered"].mean()
    baseline_pred = X_test["cause_enc"].map(lambda c: 1 if baseline_by_cause[c] > 0.5 else 0)
    baseline_acc = accuracy_score(y_test, baseline_pred)

    print(f"Training on {len(X_train)} historical examples, testing on {len(X_test)} held out")
    print("-" * 70)
    print(f"Flat baseline accuracy (predict bucket's majority class): {baseline_acc:.1%}")
    print()

    model = LogisticRegression(max_iter=1000, C=0.5, random_state=RNG_SEED)
    model.fit(X_train_s, y_train)
    y_pred = model.predict(X_test_s)
    y_proba = model.predict_proba(X_test_s)[:, 1]

    acc = accuracy_score(y_test, y_pred)
    auc = roc_auc_score(y_test, y_proba)

    print(f"Trained model (Logistic Regression) held-out accuracy: {acc:.1%}")
    print(f"Trained model held-out AUC: {auc:.3f}")
    print(f"Lift over flat baseline: {(acc - baseline_acc) * 100:+.1f} points")
    print()

    # --- Theoretical ceiling: AUC if the model knew the EXACT true
    # probability for every transaction (not an estimate). Shows
    # whether a lower AUC reflects underfitting or irreducible noise.
    true_probs_test = [
        true_recovery_probability(le_cause.inverse_transform([row.cause_enc])[0], row.amount,
                                   le_method.inverse_transform([row.method_enc])[0], row.hour_int)
        for row in X_test.itertuples()
    ]
    theoretical_ceiling_auc = roc_auc_score(y_test, true_probs_test)
    print(f"Theoretical ceiling AUC (perfect knowledge of true probability): {theoretical_ceiling_auc:.3f}")
    print(f"Gap to ceiling: {theoretical_ceiling_auc - auc:.3f} "
          f"({'near-optimal — residual is irreducible randomness, not underfitting' if theoretical_ceiling_auc - auc < 0.03 else 'room to improve'})")
    print()

    coef_importance = dict(zip(["amount", "payment_method", "hour", "root_cause"], np.abs(model.coef_[0])))
    total_w = sum(coef_importance.values())
    print("Feature weight (|coefficient|, higher = more influence):")
    for name, w in coef_importance.items():
        pct = w / total_w
        print(f"  {name:15} {pct:.1%} {'█' * int(pct * 50)}")
    print()
    print(classification_report(y_test, y_pred, target_names=["not_recovered", "recovered"]))

    # --- Score today's live batch with the trained model ---
    live_trainable = failed[failed["root_cause"] != "MERCHANT_SIDE"].copy()
    live_trainable["method_enc"] = live_trainable["payment_method"].apply(
        lambda m: le_method.transform([m])[0] if m in le_method.classes_ else 0
    )
    live_trainable["cause_enc"] = le_cause.transform(live_trainable["root_cause"])
    X_live = live_trainable[["amount", "method_enc", "hour_int", "cause_enc"]]
    X_live_s = scaler.transform(X_live)
    live_trainable["predicted_recovery_prob"] = model.predict_proba(X_live_s)[:, 1]
    print(f"\nScored {len(live_trainable)} live-batch transactions with the trained model")
    print(live_trainable[["transaction_id", "root_cause", "amount", "predicted_recovery_prob"]].head(10).to_string(index=False))

    # --- Save everything for integration into the main agent ---
    with open("models/recovery_likelihood_model.pkl", "wb") as f:
        pickle.dump({"model": model, "scaler": scaler, "le_method": le_method, "le_cause": le_cause}, f)

    failed.to_csv("outputs/simulated_training_data.csv", index=False)
    print("Saved: recovery_likelihood_model.pkl, simulated_training_data.csv")


if __name__ == "__main__":
    main()
