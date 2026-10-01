#!/usr/bin/env bash
# One-time setup for macOS / Linux. Run from the project folder:  ./scripts/setup.sh
set -e
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
[ -f .env ] || cp .env.example .env
echo
echo "Setup finished."
echo "  1) Switch the environment on:   source .venv/bin/activate"
echo "  2) Check everything:            python -m app doctor"
echo "  3) Try it (no key needed):      python -m app --offline"
echo "  4) For the real model, open .env and paste your NVIDIA key after NVIDIA_API_KEY="
