#!/usr/bin/env bash

set -euo pipefail

python scripts/build_website_docs.py
rm -rf build dist
python -m build
twine check dist/*

printf '\nBuild artifacts are ready in dist/.\n'
printf 'Website docs data refreshed at website/assets/docs-data.js.\n'
printf 'Upload manually with twine or trigger the GitHub release workflow.\n'
