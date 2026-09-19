# SPDX-License-Identifier: GPL-2.0-only
FROM ubuntu:24.04@sha256:008173c23f95b170204355c12626cb5a965d779a7e1283b09e9cffbb1bf33ca3
ARG SOURCE_URL
LABEL org.opencontainers.image.source=$SOURCE_URL
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8 LC_ALL=C.UTF-8
COPY configs/build-packages.txt /tmp/build-packages.txt
RUN test "$(dpkg --print-architecture)" = arm64 \
    && apt-get update \
    && xargs -a /tmp/build-packages.txt apt-get install -y --no-install-recommends \
       squashfs-tools nodejs sudo procps openssh-client \
    && rm -rf /var/lib/apt/lists/* /tmp/build-packages.txt
# A checksummed OCI client stores recovery artifacts independently of Actions.
RUN curl -fsSL https://github.com/oras-project/oras/releases/download/v1.3.4/oras_1.3.4_linux_arm64.tar.gz -o /tmp/oras.tar.gz \
    && echo '15702c6e3a4a56a8bd8ac5c17efdbcab56d9bada661ccbcf017f5b10c1d89399  /tmp/oras.tar.gz' | sha256sum -c - \
    && tar -xzf /tmp/oras.tar.gz -C /usr/local/bin oras \
    && rm /tmp/oras.tar.gz
# Ubuntu's packaged gh predates --slurp, which release and cache queries require.
RUN curl -fsSL https://github.com/cli/cli/releases/download/v2.101.0/gh_2.101.0_linux_arm64.tar.gz -o /tmp/gh.tar.gz \
    && echo 'b57e8063f18862647c9d22727c32e9da1b963f8bf9db648fe123a6975695640f  /tmp/gh.tar.gz' | sha256sum -c - \
    && tar -xzf /tmp/gh.tar.gz -C /usr/local/bin --strip-components=2 gh_2.101.0_linux_arm64/bin/gh \
    && rm /tmp/gh.tar.gz \
    && gh api --help | grep -q -- --slurp
# Go's historical C bootstrap cannot run on ARM64. OpenWrt uses this verified
# native compiler to build its own host Go without the unsupported Go 1.4 stage.
RUN curl -fsSL https://go.dev/dl/go1.27.1.linux-arm64.tar.gz -o /tmp/go.tar.gz \
    && echo '3450b45a3f9ee8568792736a5c5e70a1f2e9b36c35a8f74958c03e51d7d92bec  /tmp/go.tar.gz' | sha256sum -c - \
    && mkdir -p /opt/go-bootstrap \
    && tar -xzf /tmp/go.tar.gz -C /opt/go-bootstrap --strip-components=1 \
    && rm /tmp/go.tar.gz \
    && /opt/go-bootstrap/bin/go version
ENV GOLANG_BOOTSTRAP_ROOT=/opt/go-bootstrap GOTOOLCHAIN=local
ENV FORCE_UNSAFE_CONFIGURE=1
