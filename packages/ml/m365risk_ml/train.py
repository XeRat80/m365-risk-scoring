from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
import matplotlib
import numpy as np
import pandas as pd
import pyarrow.dataset as pads
from matplotlib import pyplot as plt
from onnxruntime import InferenceSession
from skl2onnx import to_onnx
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.ensemble import (
    ExtraTreesClassifier,
    GradientBoostingClassifier,
    HistGradientBoostingClassifier,
    RandomForestClassifier,
)
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    precision_recall_curve,
    roc_auc_score,
    roc_curve,
)
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .dataset_compat import dataset_preflight
from .features import FEATURE_NAMES, load_spamassassin
from .scoring import HYBRID_WEIGHTS
from .v2 import V2_COMPONENT_NAMES, V2_COMPONENT_WEIGHTS

matplotlib.use("Agg")


def expected_calibration_error(
    y_true: np.ndarray, probability: np.ndarray, bins: int = 10
) -> float:
    edges = np.linspace(0, 1, bins + 1)
    total = len(y_true)
    error = 0.0
    for lower, upper in zip(edges[:-1], edges[1:], strict=True):
        mask = (probability >= lower) & (probability < upper if upper < 1 else probability <= upper)
        if mask.any():
            error += (
                mask.sum()
                / total
                * abs(float(y_true[mask].mean()) - float(probability[mask].mean()))
            )
    return error


def threshold_for_gate(y_true: np.ndarray, probability: np.ndarray) -> tuple[float, float, float]:
    precision, recall, thresholds = precision_recall_curve(y_true, probability)
    candidates = [
        (thresholds[index], precision[index], recall[index])
        for index in range(len(thresholds))
        if recall[index] >= 0.80
    ]
    if candidates:
        # Precision is the primary objective, but recall must remain useful. This
        # prevents the trivial "predict nothing" solution from appearing perfect.
        return max(candidates, key=lambda item: (item[1], item[2], item[0]))
    # If an extremely small validation fold cannot retain 80% recall, prefer F0.5
    # over F1 so the fallback still penalizes false alarms more heavily.
    beta_squared = 0.25
    f_half = (1 + beta_squared) * precision * recall / np.maximum(
        beta_squared * precision + recall, 1e-9
    )
    index = int(np.argmax(f_half))
    threshold = thresholds[min(index, len(thresholds) - 1)]
    return float(threshold), float(precision[index]), float(recall[index])


def evaluate(
    name: str,
    y_true: np.ndarray,
    probability: np.ndarray,
    threshold: float | None = None,
) -> dict[str, float | str]:
    if threshold is None:
        threshold, precision, recall = threshold_for_gate(y_true, probability)
    else:
        predictions_at_threshold = probability >= threshold
        tp_at_threshold = int((predictions_at_threshold & (y_true == 1)).sum())
        precision = tp_at_threshold / max(1, int(predictions_at_threshold.sum()))
        recall = tp_at_threshold / max(1, int((y_true == 1).sum()))
    predictions = probability >= threshold
    tn, fp, fn, tp = confusion_matrix(y_true, predictions, labels=[0, 1]).ravel()
    return {
        "name": name,
        "pr_auc": float(average_precision_score(y_true, probability)),
        "roc_auc": float(roc_auc_score(y_true, probability)),
        "brier": float(brier_score_loss(y_true, probability)),
        "ece": expected_calibration_error(y_true, probability),
        "threshold": float(threshold),
        "precision": float(precision),
        "recall": float(recall),
        "tn": int(tn),
        "fp": int(fp),
        "fn": int(fn),
        "tp": int(tp),
    }


def rules_probability(frame: pd.DataFrame) -> np.ndarray:
    score = (
        0.08
        + 0.22 * frame["missing_message_id"]
        + 0.18 * frame["reply_to_mismatch"]
        + 0.12 * frame["return_path_mismatch"]
        + 0.13 * frame["has_html_content_type"]
        + 0.08 * frame["encoded_from"]
        + 0.06 * (frame["received_hops"] > 8)
        - 0.08 * frame["has_list_id"]
    )
    return np.asarray(np.clip(score.to_numpy(dtype=float), 0, 1), dtype=float)


@lru_cache(maxsize=4)
def load_user_daily(path: Path) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        rows.extend(csv.DictReader(handle))
    return pd.DataFrame(rows)


def user_risk_metrics(
    path: Path,
    weights: dict[str, float] | None = None,
    frame: pd.DataFrame | None = None,
) -> dict[str, float]:
    frame = (frame if frame is not None else load_user_daily(path)).copy()
    frame["label"] = pd.to_numeric(frame["label"])
    components = pd.DataFrame(
        {
            "email": pd.to_numeric(frame["email_risk_max"], errors="coerce"),
            "behaviour": pd.to_numeric(frame["behaviour_anomaly_score"], errors="coerce"),
            "entra": frame["entra_risk_level"].map(
                {"none": 0.0, "low": 0.3, "medium": 0.65, "high": 1.0}
            ),
            "posture": frame["is_mfa_registered"].map({"true": 0.0, "false": 1.0}),
            "privilege": frame["is_admin"].map({"true": 1.0, "false": 0.0}),
        },
        index=frame.index,
    )
    active_weights = weights or HYBRID_WEIGHTS
    weight_series = pd.Series(active_weights, dtype=float)
    availability = components.notna().astype(float)
    available_weight = availability.mul(weight_series, axis="columns").sum(axis=1)
    threat_names = ["email", "behaviour", "entra", "posture"]
    weighted_risk = (
        components[threat_names]
        .fillna(0)
        .mul(weight_series[threat_names], axis="columns")
        .sum(axis=1)
    )
    privilege_multiplier = 1 + components["privilege"].fillna(0) * active_weights["privilege"]
    frame["score"] = 100 * weighted_risk.mul(privilege_multiplier).where(
        available_weight >= 0.60
    )
    cutoff = frame["score"].quantile(0.90)
    top = frame["score"].notna() & (frame["score"] >= cutoff)
    positives = frame["label"] == 1
    recall = float((top & positives).sum() / max(1, positives.sum()))
    per_user = frame.groupby(["tenant_id", "user_id"], as_index=False).agg(
        compromised=("label", "max"), max_score=("score", "max")
    )
    safe_users = per_user[per_user["compromised"] == 0]
    false_alerts = float(100 * (safe_users["max_score"] >= 50).mean())
    delays: list[int] = []
    for _, user in frame.groupby(["tenant_id", "user_id"]):
        ordered = user.sort_values("date").reset_index(drop=True)
        positive_indexes = ordered.index[ordered["label"] == 1]
        if not len(positive_indexes):
            continue
        first_positive = int(positive_indexes[0])
        detected = ordered.index[(ordered["score"] >= 50) & (ordered.index >= first_positive)]
        if len(detected):
            delays.append(int(detected[0] - first_positive))
    return {
        "top_10_recall": recall,
        "false_alerts_per_100": false_alerts,
        "median_detection_delay_days": float(np.median(delays)) if delays else 999.0,
        "scored_rows": float(frame["score"].notna().sum()),
        "insufficient_data_rows": float(frame["score"].isna().sum()),
        "mean_available_weight": float(available_weight.mean()),
    }


def tune_hybrid_weights(path: Path) -> tuple[dict[str, float], dict[str, float], dict[str, object]]:
    full = load_user_daily(path).copy()
    full["date"] = pd.to_datetime(full["date"], utc=True)
    dates = np.sort(full["date"].unique())
    validation_start = dates[max(1, int(len(dates) * 0.60))]
    test_start = dates[max(2, int(len(dates) * 0.80))]
    validation = full[(full["date"] >= validation_start) & (full["date"] < test_start)]
    test = full[full["date"] >= test_start]
    baseline_validation = user_risk_metrics(path, dict(HYBRID_WEIGHTS), validation)
    baseline_test = user_risk_metrics(path, dict(HYBRID_WEIGHTS), test)
    rng = np.random.default_rng(365)
    names = list(HYBRID_WEIGHTS)
    candidates: list[tuple[dict[str, float], dict[str, float]]] = []
    for vector in rng.dirichlet(np.asarray([7, 4, 4, 3, 2], dtype=float), size=48):
        weights = {name: round(float(value), 8) for name, value in zip(names, vector, strict=True)}
        candidates.append((weights, user_risk_metrics(path, weights, validation)))
    eligible = [
        item
        for item in candidates
        if item[1]["top_10_recall"] >= baseline_validation["top_10_recall"] + 0.05
        and item[1]["false_alerts_per_100"] <= baseline_validation["false_alerts_per_100"]
    ]
    if not eligible:
        return (
            dict(HYBRID_WEIGHTS),
            baseline_test,
            {
                "promoted": False,
                "reason": "No candidate improved top-10 recall by five points without increasing false alerts.",
                "validation_baseline": baseline_validation,
                "test_baseline": baseline_test,
                "split": {"validation_start": str(validation_start), "test_start": str(test_start)},
            },
        )
    selected_weights, selected_validation_metrics = max(
        eligible,
        key=lambda item: (item[1]["top_10_recall"], -item[1]["false_alerts_per_100"]),
    )
    selected_test_metrics = user_risk_metrics(path, selected_weights, test)
    # A validation winner is still rejected if its final holdout regresses alerts or
    # fails to retain the required recall lift.
    if (
        selected_test_metrics["top_10_recall"] < baseline_test["top_10_recall"] + 0.05
        or selected_test_metrics["false_alerts_per_100"] > baseline_test["false_alerts_per_100"]
    ):
        return (
            dict(HYBRID_WEIGHTS),
            baseline_test,
            {
                "promoted": False,
                "reason": "Validation winner did not retain its improvement on the final holdout.",
                "validation_baseline": baseline_validation,
                "validation_candidate": selected_validation_metrics,
                "test_baseline": baseline_test,
                "test_candidate": selected_test_metrics,
            },
        )
    return (
        selected_weights,
        selected_test_metrics,
        {
            "promoted": True,
            "reason": "Tuned non-negative weights passed the promotion rule.",
            "validation_baseline": baseline_validation,
            "validation_candidate": selected_validation_metrics,
            "test_baseline": baseline_test,
            "test_candidate": selected_test_metrics,
        },
    )


def grouped_time_split(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Split every archive chronologically so each corpus contributes to all folds."""
    train: list[int] = []
    validation: list[int] = []
    test: list[int] = []
    for _, group in frame.groupby("archive", sort=False):
        first = max(1, round(len(group) * 0.60))
        second = max(first + 1, round(len(group) * 0.80))
        second = min(second, len(group) - 1)
        train.extend(group.index[:first])
        validation.extend(group.index[first:second])
        test.extend(group.index[second:])
    return np.asarray(train), np.asarray(validation), np.asarray(test)


def fit_enron_baseline(data_root: Path) -> dict[str, object]:
    root = data_root / "processed" / "email_metadata_v1"
    dataset = pads.dataset(root, format="parquet", partitioning="hive")
    table = dataset.to_table(
        filter=pads.field("dataset") == "enron",
        columns=[
            "sender_hash",
            "recipient_hash",
            "received_at",
            "recipient_count",
            "received_hops",
        ],
    )
    frame = table.to_pandas().sort_values("received_at")
    if frame.empty:
        raise ValueError("Enron processed metadata is required for behavior baselines")
    cutoff = frame["received_at"].quantile(0.80)
    training = frame[frame["received_at"] <= cutoff].copy()
    training["day"] = training["received_at"].dt.floor("D")
    daily = training.groupby("day").agg(
        message_count=("sender_hash", "size"),
        unique_senders=("sender_hash", "nunique"),
        unique_recipients=("recipient_hash", "nunique"),
        median_recipient_count=("recipient_count", "median"),
        median_received_hops=("received_hops", "median"),
    )

    def robust(values: pd.Series) -> dict[str, float]:
        median = float(values.median())
        mad = float((values - median).abs().median())
        return {"median": median, "mad": max(mad, 1e-6)}

    common_routes = (
        training.groupby(["sender_hash", "recipient_hash"])
        .size()
        .sort_values(ascending=False)
        .head(100)
    )
    return {
        "version": "UserDailyFeaturesV1",
        "fit_rows": int(len(training)),
        "fit_end_utc": pd.Timestamp(cutoff).isoformat(),
        "statistics": {column: robust(daily[column]) for column in daily.columns},
        "common_route_hashes": [
            hashlib.sha256(f"{sender}:{recipient}".encode()).hexdigest()[:24]
            for sender, recipient in common_routes.index
        ],
    }


def plot_report(y_true: np.ndarray, probabilities: dict[str, np.ndarray], output: Path) -> None:
    figure, axes = plt.subplots(1, 2, figsize=(12, 5))
    for name, probability in probabilities.items():
        precision, recall, _ = precision_recall_curve(y_true, probability)
        axes[0].plot(
            recall, precision, label=f"{name} ({average_precision_score(y_true, probability):.3f})"
        )
        fpr, tpr, _ = roc_curve(y_true, probability)
        axes[1].plot(fpr, tpr, label=f"{name} ({roc_auc_score(y_true, probability):.3f})")
    axes[0].set(title="Precision-recall", xlabel="Recall", ylabel="Precision")
    axes[1].set(title="ROC", xlabel="False positive rate", ylabel="True positive rate")
    for axis in axes:
        axis.grid(alpha=0.25)
        axis.legend()
    figure.tight_layout()
    figure.savefig(output / "model_comparison.png", dpi=180)
    plt.close(figure)


def plot_diagnostics(
    y_true: np.ndarray,
    probabilities: dict[str, np.ndarray],
    evaluations: list[dict[str, float | str]],
    coefficients: pd.DataFrame,
    selected_name: str,
    output: Path,
) -> None:
    figure, axes = plt.subplots(1, 2, figsize=(12, 5))
    for name, probability in probabilities.items():
        observed, predicted = calibration_curve(y_true, probability, n_bins=10, strategy="quantile")
        axes[0].plot(predicted, observed, marker="o", label=name)
    axes[0].plot([0, 1], [0, 1], linestyle="--", color="gray")
    axes[0].set(title="Calibration", xlabel="Mean predicted probability", ylabel="Observed rate")
    metrics_frame = pd.DataFrame(evaluations).set_index("name")
    metrics_frame[["brier", "ece"]].plot.bar(ax=axes[1])
    axes[1].set(title="Brier score and expected calibration error", ylabel="Error")
    for axis in axes:
        axis.grid(alpha=0.25)
    axes[0].legend()
    figure.tight_layout()
    figure.savefig(output / "calibration_brier_ece.png", dpi=180)
    plt.close(figure)

    figure, axes = plt.subplots(1, len(probabilities), figsize=(5 * len(probabilities), 4))
    if not isinstance(axes, np.ndarray):
        axes = np.asarray([axes])
    by_name = {str(item["name"]): item for item in evaluations}
    for axis, (name, probability) in zip(axes, probabilities.items(), strict=True):
        metrics = by_name[name]
        matrix = confusion_matrix(y_true, probability >= float(metrics["threshold"]), labels=[0, 1])
        image = axis.imshow(matrix, cmap="Blues")
        for row in range(2):
            for column in range(2):
                axis.text(column, row, str(matrix[row, column]), ha="center", va="center")
        axis.set(title=f"{name} confusion matrix", xlabel="Predicted", ylabel="Actual")
        figure.colorbar(image, ax=axis, fraction=0.046)
    figure.tight_layout()
    figure.savefig(output / "confusion_matrices.png", dpi=180)
    plt.close(figure)

    selected_probability = probabilities[selected_name]
    precision, recall, thresholds = precision_recall_curve(y_true, selected_probability)
    figure, axis = plt.subplots(figsize=(8, 5))
    axis.plot(thresholds, precision[:-1], label="precision")
    axis.plot(thresholds, recall[:-1], label="recall")
    axis.axvline(float(by_name[selected_name]["threshold"]), color="red", linestyle="--")
    axis.set(title="Decision threshold sensitivity", xlabel="Threshold", ylabel="Metric")
    axis.grid(alpha=0.25)
    axis.legend()
    figure.tight_layout()
    figure.savefig(output / "threshold_curves.png", dpi=180)
    plt.close(figure)

    ordered = coefficients.assign(abs_value=coefficients["coefficient"].abs()).nlargest(
        14, "abs_value"
    )
    figure, axis = plt.subplots(figsize=(9, 6))
    axis.barh(ordered["feature"], ordered["coefficient"])
    axis.set(title="Feature importance / calibrated coefficients", xlabel="Coefficient")
    axis.grid(axis="x", alpha=0.25)
    figure.tight_layout()
    figure.savefig(output / "feature_importance.png", dpi=180)
    plt.close(figure)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _calibrated_logistic() -> Pipeline:
    base = LogisticRegression(class_weight="balanced", max_iter=2000, random_state=365)
    calibrated = CalibratedClassifierCV(
        base,
        method="sigmoid",
        cv=StratifiedKFold(n_splits=3, shuffle=True, random_state=365),
    )
    return Pipeline([("scale", StandardScaler()), ("model", calibrated)])


def _logistic_coefficients(model: Pipeline) -> np.ndarray:
    calibrated = model.named_steps["model"]
    estimators = [item.estimator for item in calibrated.calibrated_classifiers_]
    return np.asarray(np.mean([estimator.coef_[0] for estimator in estimators], axis=0))


def _feature_importance(model: object, selected_name: str) -> np.ndarray:
    if selected_name == "logistic":
        return _logistic_coefficients(model)
    values = getattr(model, "feature_importances_", None)
    if values is None:
        raise RuntimeError(f"Selected model {selected_name} does not expose feature importance")
    return np.asarray(values, dtype=float)


def train(data_root: Path, output: Path, version: str | None = None) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    version = version or os.getenv("MODEL_VERSION", "0.1.0-demo")
    feature_cache = output / "email_features.parquet"
    if feature_cache.exists():
        frame = pd.read_parquet(feature_cache)
    else:
        frame = load_spamassassin(data_root / "raw" / "spamassassin")
        frame.to_parquet(feature_cache, index=False)
    train_index, validation_index, test_index = grouped_time_split(frame)
    x = frame[FEATURE_NAMES].astype(np.float32)
    y = frame["label"].to_numpy(dtype=int)
    x_train, x_validation, x_test = (
        x.loc[train_index],
        x.loc[validation_index],
        x.loc[test_index],
    )
    y_train, y_validation, y_test = y[train_index], y[validation_index], y[test_index]
    candidate_factories = {
        "logistic": _calibrated_logistic,
        "random_forest": lambda: RandomForestClassifier(
            n_estimators=500,
            min_samples_leaf=2,
            max_features=None,
            class_weight="balanced_subsample",
            random_state=365,
            n_jobs=-1,
        ),
        "extra_trees": lambda: ExtraTreesClassifier(
            n_estimators=500,
            min_samples_leaf=1,
            max_features="sqrt",
            class_weight="balanced",
            random_state=365,
            n_jobs=-1,
        ),
        "gradient_boosting": lambda: GradientBoostingClassifier(
            n_estimators=180,
            learning_rate=0.05,
            max_depth=3,
            min_samples_leaf=5,
            random_state=365,
        ),
        "hist_gradient_boosting": lambda: HistGradientBoostingClassifier(
            max_iter=180,
            learning_rate=0.06,
            max_leaf_nodes=24,
            l2_regularization=0.5,
            random_state=365,
        ),
    }
    validation_probability = {"rules": rules_probability(x_validation)}
    validation_metrics = [evaluate("rules", y_validation, validation_probability["rules"])]
    for name, factory in candidate_factories.items():
        model = factory()  # type: ignore[no-untyped-call]
        model.fit(x_train.to_numpy(dtype=np.float32), y_train)
        validation_probability[name] = model.predict_proba(x_validation.to_numpy(dtype=np.float32))[
            :, 1
        ]
        validation_metrics.append(evaluate(name, y_validation, validation_probability[name]))
    eligible_validation = [
        item for item in validation_metrics[1:] if float(item["recall"]) >= 0.80
    ]
    ranked_validation = sorted(
        eligible_validation or validation_metrics[1:],
        key=lambda item: (
            float(item["precision"]),
            float(item["pr_auc"]),
            float(item["recall"]),
        ),
        reverse=True,
    )

    combined_index = np.concatenate([train_index, validation_index])
    x_fit, y_fit = x.loc[combined_index], y[combined_index]
    models: dict[str, object] = {}
    probabilities = {"rules": rules_probability(x_test)}
    thresholds = {str(item["name"]): float(item["threshold"]) for item in validation_metrics}
    evaluations = [evaluate("rules", y_test, probabilities["rules"], thresholds["rules"])]
    for name, factory in candidate_factories.items():
        model = factory()  # type: ignore[no-untyped-call]
        model.fit(x_fit.to_numpy(dtype=np.float32), y_fit)
        models[name] = model
        probabilities[name] = model.predict_proba(x_test.to_numpy(dtype=np.float32))[:, 1]
        evaluations.append(evaluate(name, y_test, probabilities[name], thresholds[name]))
    pd.DataFrame({"label": y_test, **probabilities}).to_parquet(
        output / "evaluation_predictions.parquet", index=False
    )
    conversion_failures: list[str] = []
    selected_name = ""
    selected: object | None = None
    onnx_model: Any | None = None
    for validation_candidate in ranked_validation:
        candidate_name = str(validation_candidate["name"])
        candidate = models[candidate_name]
        try:
            converted = to_onnx(
                candidate,
                x_fit.iloc[:1].to_numpy(dtype=np.float32),
                target_opset=18,
            )
        except (RuntimeError, TypeError, ValueError) as error:
            conversion_failures.append(f"{candidate_name}: {type(error).__name__}")
            continue
        selected_name = candidate_name
        selected = candidate
        onnx_model = converted
        break
    if selected is None or onnx_model is None:
        raise RuntimeError("No precision-ranked candidate produced a portable ONNX artifact")
    selected_metrics = next(item for item in evaluations if item["name"] == selected_name)
    selection_note = (
        "Highest validation precision candidate with recall >= 0.80 and portable ONNX export."
    )
    if conversion_failures:
        selection_note += " Skipped " + ", ".join(conversion_failures) + "."
    rules_metrics = evaluations[0]
    hybrid_weights, user_metrics, weight_selection = tune_hybrid_weights(
        data_root / "synthetic" / "m365_user_daily.csv.gz"
    )
    real_m365_labelled_rows = 0
    approved = bool(
        real_m365_labelled_rows > 0
        and float(selected_metrics["pr_auc"]) >= 0.90
        and float(selected_metrics["pr_auc"]) >= float(rules_metrics["pr_auc"]) + 0.03
        and float(selected_metrics["precision"]) >= 0.85
        and float(selected_metrics["recall"]) >= 0.80
        and float(selected_metrics["brier"]) <= 0.10
        and float(selected_metrics["ece"]) <= 0.05
        and user_metrics["top_10_recall"] >= 0.80
        and user_metrics["false_alerts_per_100"] <= 5
        and user_metrics["median_detection_delay_days"] <= 1
    )
    joblib.dump(selected, output / "pipeline.joblib")
    (output / "model.onnx").write_bytes(onnx_model.SerializeToString())
    onnx_session = InferenceSession(str(output / "model.onnx"), providers=["CPUExecutionProvider"])
    onnx_outputs = onnx_session.run(
        None, {onnx_session.get_inputs()[0].name: x_test.iloc[:100].to_numpy(dtype=np.float32)}
    )
    onnx_probability = onnx_outputs[-1]
    if isinstance(onnx_probability, list):
        onnx_probability = np.asarray([item[1] for item in onnx_probability])
    else:
        onnx_probability = np.asarray(onnx_probability)[:, 1]
    parity = float(
        np.max(
            np.abs(
                selected.predict_proba(x_test.iloc[:100].to_numpy(dtype=np.float32))[:, 1]  # type: ignore[attr-defined]
                - onnx_probability
            )
        )
    )
    allowed_parity = 1e-5 if selected_name == "logistic" else 1e-4
    approved = approved and parity <= allowed_parity
    metrics = {
        "split": {
            "strategy": "grouped chronological 60/20/20 by SpamAssassin archive",
            "train_rows": int(len(train_index)),
            "validation_rows": int(len(validation_index)),
            "test_rows": int(len(test_index)),
        },
        "validation_models": validation_metrics,
        "email_models": evaluations,
        "selected": selected_metrics,
        "user_risk": user_metrics,
        "onnx_max_abs_difference": parity,
        "selection_note": selection_note,
        "hybrid_weight_selection": weight_selection,
        "performance_by_source_category": {
            "imported": {
                "dataset": "SpamAssassin Public Corpus (2003)",
                "rows": int(len(frame)),
                "metrics": selected_metrics,
            },
            "generated": {
                "dataset": "Synthetic Microsoft 365 user daily risk",
                "metrics": user_metrics,
            },
            "real_labelled": {
                "rows": real_m365_labelled_rows,
                "status": "not_available",
                "metrics": None,
            },
        },
    }
    compatibility = dataset_preflight(
        frame.columns,
        dataset_kind="email",
        source_category="imported",
        labelled=True,
    )
    (output / "dataset_compatibility_v2.json").write_text(
        json.dumps(compatibility.__dict__, indent=2) + "\n"
    )
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    (output / "feature_schema.json").write_text(
        json.dumps({"version": "EmailMetadataV1", "features": FEATURE_NAMES}, indent=2) + "\n"
    )
    availability_schema = {
        "version": "RiskComponentAvailabilityV2",
        "components": list(V2_COMPONENT_NAMES),
        "weights": V2_COMPONENT_WEIGHTS,
        "minimum_available_weight": 0.60,
        "encoded_features": [
            feature
            for name in V2_COMPONENT_NAMES
            for feature in (
                f"{name}__value",
                f"{name}__available",
                f"{name}__insufficient_history",
            )
        ],
    }
    (output / "availability_schema_v2.json").write_text(
        json.dumps(availability_schema, indent=2) + "\n"
    )
    (output / "hybrid_weights.json").write_text(json.dumps(hybrid_weights, indent=2) + "\n")
    (output / "thresholds.json").write_text(
        json.dumps(
            {
                "email_probability": selected_metrics["threshold"],
                "low": 25,
                "high": 50,
                "critical": 75,
            },
            indent=2,
        )
        + "\n"
    )
    coefficient_values = _feature_importance(selected, selected_name)
    coefficients = pd.DataFrame({"feature": FEATURE_NAMES, "coefficient": coefficient_values})
    coefficients.to_csv(output / "coefficients.csv", index=False)
    behavior_baseline = fit_enron_baseline(data_root)
    (output / "behavior_baseline.json").write_text(json.dumps(behavior_baseline, indent=2) + "\n")
    plot_report(y_test, probabilities, output)
    plot_diagnostics(y_test, probabilities, evaluations, coefficients, selected_name, output)
    manifest: dict[str, object] = {
        "version": version,
        "created_at": datetime.now(UTC).isoformat(),
        "approved": approved,
        "status": "approved" if approved else "demo",
        "selected_model": selected_name,
        "selection_note": selection_note,
        "feature_version": "EmailMetadataV1",
        "behavior_feature_version": "UserDailyFeaturesV1",
        "data_checksums": {
            "dataset_manifest": sha256(data_root / "DATASET_MANIFEST.json"),
            "synthetic_user_daily": sha256(data_root / "synthetic" / "m365_user_daily.csv.gz"),
        },
        "metrics": metrics,
        "artifacts": {},
    }
    (output / "model_card.md").write_text(
        "# M365 email header risk model\n\n"
        f"- Status: **{manifest['status']}**\n- Selected: `{selected_name}`\n"
        f"- PR-AUC: {float(selected_metrics['pr_auc']):.4f}\n- Brier: {float(selected_metrics['brier']):.4f}\n"
        f"- Selection: {selection_note}\n"
        "- Validation: grouped chronological model selection and threshold fitting; final metrics use an untouched holdout.\n"
        "- Selection objective: highest validation precision while retaining at least 80% recall.\n"
        "- Behavior baseline: Enron sender/recipient metadata, fitted on the earliest 80% of history only.\n"
        "- Inputs: headers and metadata only; body, subject and attachments are excluded.\n"
        "- Intended use: prioritizing analyst review; never an autonomous account-blocking decision.\n"
        "- Limitations: SpamAssassin is an anti-spam corpus, not Microsoft 365 compromise ground truth.\n"
        "- V2 compatibility: SPF, DKIM and DMARC outcome fields are unavailable in the legacy corpus and remain unknown.\n"
        "- Promotion block: no privacy-reviewed, labelled Microsoft 365 validation set is present.\n"
    )
    artifact_names = [
        "pipeline.joblib",
        "model.onnx",
        "feature_schema.json",
        "availability_schema_v2.json",
        "hybrid_weights.json",
        "thresholds.json",
        "metrics.json",
        "coefficients.csv",
        "behavior_baseline.json",
        "dataset_compatibility_v2.json",
        "model_card.md",
    ]
    manifest["artifacts"] = {name: sha256(output / name) for name in artifact_names}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/models/current"))
    parser.add_argument("--version")
    args = parser.parse_args()
    print(json.dumps(train(args.data_root, args.output, args.version), indent=2))


if __name__ == "__main__":
    main()
