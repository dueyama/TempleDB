#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/local/sbin:${PATH}"

exec ./bin/run_product.sh --open-browser
