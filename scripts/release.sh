#!/bin/bash

source .venv/bin/activate

# dirty
VERSION=$(grep -E '^version[[:space:]]*=' pyproject.toml | sed -E 's/.*=[[:space:]]*"([^"]+)".*/\1/')
TAG_NAME=$(git describe --exact-match --tags HEAD)

if [[ "$VERSION" != "$TAG_NAME" ]]; then
    echo "Tag and version do not match!"
    echo "Tag: $TAG_NAME, Version: $VERSION"
    exit 1
fi

if [ -z "$PYPI_TOKEN" ]; then
  echo "PYPI_TOKEN is not set. Can't authenticate to upload"
  exit 1
fi

ARTIFACTS=(
  "dist/pillow_degas-$VERSION-py3-none-any.whl"
  "dist/pillow_degas-$VERSION.tar.gz"
)

for artifact in "${ARTIFACTS[@]}"; do
  if [ ! -f "$artifact" ]; then
    echo "Missing release artifact: $artifact"
    exit 1
  fi
done

python3 -m twine upload "${ARTIFACTS[@]}" --user=__token__ --password="$PYPI_TOKEN"
