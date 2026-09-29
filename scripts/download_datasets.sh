#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SPAM_DIR="$ROOT_DIR/data/raw/spamassassin"
ENRON_DIR="$ROOT_DIR/data/raw/enron"

mkdir -p "$SPAM_DIR" "$ENRON_DIR"

download() {
  local url="$1"
  local output="$2"
  local remote_size
  local local_size
  remote_size="$(curl -fsIL "$url" | awk 'tolower($1) == "content-length:" {gsub("\\r", "", $2); size=$2} END {print size}')"
  if [[ -f "$output" ]]; then
    local_size="$(stat -f '%z' "$output" 2>/dev/null || stat -c '%s' "$output")"
    if [[ -n "$remote_size" && "$local_size" == "$remote_size" ]]; then
      echo "Already complete: $output"
      return
    fi
  fi
  curl -fL --retry 10 --retry-delay 5 --retry-all-errors -C - -o "$output" "$url"
}

base="https://spamassassin.apache.org/old/publiccorpus"
for file in \
  20030228_easy_ham.tar.bz2 \
  20030228_easy_ham_2.tar.bz2 \
  20030228_hard_ham.tar.bz2 \
  20030228_spam.tar.bz2 \
  20030228_spam_2.tar.bz2 \
  readme.html
do
  download "$base/$file" "$SPAM_DIR/$file"
done

download \
  "https://www.cs.cmu.edu/~enron/enron_mail_20150507.tar.gz" \
  "$ENRON_DIR/enron_mail_20150507.tar.gz"

(cd "$ROOT_DIR" && shasum -a 256 -c data/SHA256SUMS)
echo "Datasets downloaded and verified against the committed checksums."
