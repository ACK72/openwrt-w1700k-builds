# SPDX-License-Identifier: GPL-2.0-only
FROM ubuntu:24.04@sha256:008173c23f95b170204355c12626cb5a965d779a7e1283b09e9cffbb1bf33ca3
ARG SOURCE_URL
LABEL org.opencontainers.image.source=$SOURCE_URL
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8 LC_ALL=C.UTF-8
COPY configs/build-packages.txt /tmp/build-packages.txt
RUN test "$(dpkg --print-architecture)" = arm64 \
    && apt-get update \
    && xargs -a /tmp/build-packages.txt apt-get install -y --no-install-recommends \
       squashfs-tools gh nodejs sudo procps openssh-client \
    && rm -rf /var/lib/apt/lists/* /tmp/build-packages.txt
# A checksummed OCI client stores recovery artifacts independently of Actions.
RUN curl -fsSL https://github.com/oras-project/oras/releases/download/v1.3.4/oras_1.3.4_linux_arm64.tar.gz -o /tmp/oras.tar.gz \
    && echo '15702c6e3a4a56a8bd8ac5c17efdbcab56d9bada661ccbcf017f5b10c1d89399  /tmp/oras.tar.gz' | sha256sum -c - \
    && tar -xzf /tmp/oras.tar.gz -C /usr/local/bin oras \
    && rm /tmp/oras.tar.gz
ENV FORCE_UNSAFE_CONFIGURE=1

