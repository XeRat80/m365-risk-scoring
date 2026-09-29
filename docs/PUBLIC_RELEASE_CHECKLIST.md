# Public source release checklist

The GitHub repository distributes source and installation instructions. It does not host the scanner, the API, company data, or a production model. A fresh clone must be tested before claiming the public install works.

## Before pushing

- [ ] Create a GitHub repository and configure its exact remote URL for the release checkout.
- [ ] Review `git status --short` and stage only intended source/documentation files. Do not use `git add .` on this development checkout: it contains unrelated local reports and video assets.
- [ ] Verify `.env`, credentials, access tokens, mail responses, employee identifiers, scan exports, labels, trained models, and private meeting material are absent from both the staged diff and the commits to be pushed. `.gitignore` helps but cannot protect files already tracked or secrets in history.
- [ ] Run tests and scan the final staged content for secrets using a trusted local secret scanner. Resolve findings before push.
- [ ] From a fresh clone on another machine or disposable directory, run `./scripts/install.sh --check`, `./scripts/install.sh`, `./scripts/doctor.sh --after-start`, and `python3 scripts/scan_cli.py scan --demo --out output/scans/smoke-001`.
- [ ] Make the README's real-tenant limitation explicit. The one-command installer is currently Mock Graph only; no company tenant scan has been verified.
- [ ] For a public Kaggle demonstration, upload only the generated synthetic export and labels. Verify that the notebook uses `--public-notebook` and that its report says `source_category: generated` and `status: experimental_unapproved`.

## After publishing

Record the repository URL and commit SHA in the meeting notes. Show the CLI output and the manifest, but never expose bearer tokens or private exports while screen sharing. Do not describe synthetic holdout metrics as real-world detection precision. Real deployment requires authorized Graph consent, private storage/compute, security review, independently reviewed labels, and production model approval.
