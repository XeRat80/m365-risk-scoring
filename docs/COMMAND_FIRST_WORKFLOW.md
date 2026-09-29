# Command-first PFE workflow

## What is implemented

The current API/worker already collects Mock Graph mail metadata, sign-ins, MFA registration, Risky Users, roles, and optional alerts, builds V2 feature windows, and stores them per tenant. `scripts/scan_cli.py` now offers a command-line entry point and an administrator-only export of those stored features. The browser dashboards are optional for this workflow.

The real Graph adapter exists, but **a real company scan has not been verified**. The one-command installer supports only Mock Graph. This document must not be used as evidence of authorized company access.

## Scan and inspect without a Microsoft tenant

First run `./scripts/install.sh` as described in the README. Then:

```bash
python3 scripts/scan_cli.py scan --demo --out output/scans/meeting-demo
```

The command prints the synchronization job result and the exported row count. It creates `feature_windows.jsonl` and `manifest.json` in a private directory. Every row has `sample_id`, `subject_key`, `window_end`, seven low-level canonical feature values, five non-duplicated components, five availability values, and schema/model versions. It contains neither the existing risk score nor an incident label. The manifest records a SHA-256 checksum and marks the export as unlabelled and not production-eligible.

To see the **current operational scores** from the already configured runtime model, run `python3 scripts/scan_cli.py results --demo --top 5`, or add `--show-results` to the scan command. The score summary is separate from the unlabelled training export and from the experimental model trained later in this guide.

To collect again without requesting a new scan, use `collect --demo --out output/scans/another-empty-directory`. To request scanning only, use `scan --demo --scan-only`. Each export path must be new or empty; the command will not overwrite previous results.

An analyst who knows a local employee ID can resolve its latest export sample ID without placing the employee ID in the training file:

```bash
python3 scripts/scan_cli.py identify --demo --user-id user-001
```

The administrator-only lookup is for local review; do not copy the employee ID into the remote training dataset.

## Training input and remote compute

The model needs two separate files:

1. `feature_windows.jsonl`, produced by the scanner.
2. A separate labels CSV with exactly `sample_id,label` columns and `0`/`1` outcomes. For real scans, labels must come from analyst review. Never derive labels from the application's own score; that would be circular evaluation.

Transfer approved files to a remote training environment, install NumPy, scikit-learn and joblib, and run:

```bash
python -m pip install "numpy>=2,<3" "scikit-learn>=1.5,<2" "joblib>=1.4,<2"
python scripts/train_scanned.py \
  --features /private/data/feature_windows.jsonl \
  --labels /private/data/reviewed_labels.csv \
  --out /private/results/experiment-001
```

The script needs at least 30 labelled windows and at least five positive and five negative subjects. It selects between two baselines using a validation split and reports metrics on a separate subject-disjoint test split. It records that chronological validation has **not** yet been performed. `model.joblib` is an experimental artifact, not an approved model for the API. Only load model files from a trusted source.

For tomorrow's demonstration, [Kaggle Notebooks](https://www.kaggle.com/docs/notebooks) is the free remote-compute choice **only for synthetic/generated demo data and labels**. Its session limits and resource availability mean it is not a production service. To demonstrate training without inventing labels for the actual scan, generate a clearly marked synthetic dataset in the same export schema:

```bash
python3 scripts/generate_remote_training_demo.py --out output/scans/synthetic-training-demo
```

Upload its `feature_windows.jsonl`, `manifest.json`, and `generated_labels.csv` together as one Kaggle input dataset. After the source repository has actually been published, clone it in the notebook (or upload `scripts/train_scanned.py` if notebook network access is unavailable), then run:

```bash
python -m pip install "numpy>=2,<3" "scikit-learn>=1.5,<2" "joblib>=1.4,<2"
python /kaggle/working/m365-risk/scripts/train_scanned.py \
  --features /kaggle/input/YOUR_DATASET/feature_windows.jsonl \
  --labels /kaggle/input/YOUR_DATASET/generated_labels.csv \
  --out /kaggle/working/experiment-001 \
  --public-notebook
```

The path `YOUR_DATASET` is the dataset slug assigned by Kaggle. `--public-notebook` checks the supplied manifest's source category; it cannot independently prove that uploaded data is synthetic. The generator is a software-path demonstration, **not measured model quality on Microsoft 365**. Do not upload company exports, even pseudonymized ones, to a public notebook without a separate authorization and data-processing decision. For real data, run the same script on a company-controlled remote VM or private ML environment. The training report records dependency versions, source checksums and the holdout metrics; the trained artifact remains unapproved.

## What the supervisor can verify tomorrow

1. Run `scan --demo --out ...` and show a completed job and feature-export manifest.
2. Open one JSONL row: demonstrate availability flags and the absence of message content or raw employee identifiers.
3. Explain that labels come from independent analyst review, then show the training command and its grouped holdout report using generated labelled test data.
4. State the boundary plainly: Mock Graph proves the software path; real Graph permissions, company-data collection, model validity, and production promotion still need authorized tenant testing.

Publishing the source on GitHub does not publish a running API or a model endpoint. Keep `.env`, tokens, scans, label files, and trained model artifacts outside the public repository.
Before publishing any fork or new release, use the [public release checklist](PUBLIC_RELEASE_CHECKLIST.md). A public Kaggle run and a real company scan have not yet been verified.
