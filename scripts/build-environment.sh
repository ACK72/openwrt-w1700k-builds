#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -Eeuo pipefail
[[ $(uname -m) == aarch64 ]] || { echo 'An ARM64 runner is required.' >&2; exit 1; }
image="ghcr.io/${GITHUB_REPOSITORY,,}/build-environment"
key=$(cat containers/build-environment.Dockerfile configs/build-packages.txt | sha256sum | cut -d' ' -f1)
tag="$image:arm64-$key"
if [[ ${REFRESH_ENVIRONMENT:-false} == true ]] || ! docker pull "$tag"; then
    docker build --pull --no-cache --platform linux/arm64 \
        --build-arg "SOURCE_URL=https://github.com/$GITHUB_REPOSITORY" \
        -f containers/build-environment.Dockerfile -t "$tag" .
    docker push "$tag"
    docker pull "$tag"
fi
# A job always uses an immutable digest, including while the named image refreshes.
digest=$(docker image inspect "$tag" --format '{{index .RepoDigests 0}}')
[[ $digest == "$image@sha256:"* ]] || exit 1
echo "image=$digest" >> "$GITHUB_OUTPUT"

