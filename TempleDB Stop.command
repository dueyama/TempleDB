#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")"
exec ./bin/stop_product.sh
