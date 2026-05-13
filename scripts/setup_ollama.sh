#!/usr/bin/env bash
set -euo pipefail

if ! command -v ollama >/dev/null 2>&1; then
  echo "ollama is not installed"
  exit 1
fi

ollama pull llama3.1:8b
