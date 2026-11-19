#!/bin/sh
# Vorlage für .git/hooks/pre-push – NICHT automatisch installiert.
# Installation:  cp outputs/pre-push-beispiel.sh .git/hooks/pre-push && chmod +x .git/hooks/pre-push
# Danach läuft vor jedem Push die pytest-Suite; bei einem Fehler wird der Push abgebrochen.
set -e
cd "$(git rev-parse --show-toplevel)"
python -m pytest -q tests
