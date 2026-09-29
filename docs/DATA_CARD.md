# Data card

SpamAssassin supplies public ham/spam labels for email-header threat experiments. Enron supplies normal sender-recipient and temporal metadata for early-history behavior baselines. Deterministic synthetic daily user data supplies compromise windows, posture, privilege, Entra risk, and user-level evaluation.

Only RFC headers are parsed. Processed Parquet is partitioned by dataset, UTC date, and tenant; identities/domains are salted hashes. Forbidden content fields are absent. Corpus checksums and source URLs are recorded in `data/DATASET_MANIFEST.json` and `data/SHA256SUMS`.

Splits are grouped chronological 60/20/20 within SpamAssassin archives. Threshold/model selection uses validation; the final email metrics use an untouched holdout. Hybrid weights are tuned on a synthetic validation time range and must retain their lift on a final time holdout. Enron baselines fit only the earliest 80% of observed history.

The active `0.3.1-precision` bundle compares rules, calibrated logistic regression, random forest, extremely randomized trees, gradient boosting, and histogram gradient boosting. Selection maximizes validation precision subject to recall >= 0.80 and portable ONNX export. The selected random forest uses a 0.7289 threshold. Untouched holdout results are precision 0.8770, recall 0.8470, PR-AUC 0.8735, ROC-AUC 0.9296, Brier 0.0730, with 45 false positives and 58 false negatives over 1,209 messages. These are corpus results, not a claim about live Microsoft 365 performance.

Limitations include old public corpora, anti-spam rather than compromise labels, synthetic attack distributions, incomplete demographic/fairness attributes, and no customer-specific language/routing patterns. Data must be revalidated for every real tenant and jurisdiction.

V2 preflight classifies datasets as `imported`, `generated`, or `real_labelled`, rejects prohibited content fields, and reports missing canonical columns before ingestion. Legacy SpamAssassin rows adapt with SPF/DKIM/DMARC marked unknown; those values are never fabricated. Metrics are reported separately by source category. Imported or generated data may support development, but only compatible, privacy-reviewed, labelled Microsoft 365 data can make a model production-eligible.
