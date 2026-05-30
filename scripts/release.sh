#!/usr/bin/env bash

set -euo pipefail

rm -rf build dist
python -m build
twine check dist/*

printf '\nBuild artifacts are ready in dist/.\n'
printf 'Upload manually with twine or trigger the GitHub release workflow.\n'
