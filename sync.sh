#!/bin/zsh
set -e

branch=$(git rev-parse --abbrev-ref HEAD)
if [[ "$branch" != "development" ]]; then
  echo "Error: must be on development (currently on $branch)" >&2
  exit 1
fi

git checkout master && git merge development && git push
echo "- Updated master branch"

if [[ "$1" == "--backup" ]]; then
  git checkout backup && git merge master && git push
  echo "- Updated backup branch"
fi

git checkout development
