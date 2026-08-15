#!/bin/sh
set -e

exec deepseek-plugin-runner \
  --host "${HOST:-0.0.0.0}" \
  --port "${PORT:-8000}" \
  --config "${CONFIG:-/app/example_config.yaml}"
