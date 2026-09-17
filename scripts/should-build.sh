#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
[[ ${FINGERPRINT:-} =~ ^[a-f0-9]{64}$ ]] || { echo 'Invalid fingerprint' >&2; exit 1; }

if [[ ${FORCE:-false} == true ]]; then
    echo 'build=true'
else
    # An artifact upload is not a published release. Retry failed publication.
    if ! python3 "$ROOT/scripts/release.py" check "$FINGERPRINT"; then
        echo 'WARNING: Could not verify existing releases; building again.' >&2
        echo 'build=true'
    fi
fi
