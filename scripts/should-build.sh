#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
marker="$ROOT/.cache/success"
[[ ${FINGERPRINT:-} =~ ^[a-f0-9]{64}$ ]] || { echo 'Invalid fingerprint' >&2; exit 1; }

# A success cache outlives its downloadable artifact. Only skip if both still
# match; a missing/expired artifact or an API failure must trigger a new build.
if [[ ${FORCE:-false} != true && ${PUBLISH:-false} != true &&
      -f $marker/fingerprint && -f $marker/artifact-id ]] &&
   [[ $(cat "$marker/fingerprint") == "$FINGERPRINT" ]]; then
    artifact_id=$(cat "$marker/artifact-id")
    if [[ $artifact_id =~ ^[0-9]+$ ]] &&
       available=$(gh api "repos/${GH_REPO:?}/actions/artifacts/$artifact_id" \
           --jq '.expired == false and .size_in_bytes > 0' 2>/dev/null) &&
       [[ $available == true ]]; then
        echo 'build=false'
        exit 0
    fi
fi
echo 'build=true'
