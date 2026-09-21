#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# netifd calls this platform override on boot and interface events.
mkdir /var/run/w1700k-affinity.lock 2>/dev/null || exit 0
trap 'rmdir /var/run/w1700k-affinity.lock' EXIT
trap 'exit 1' HUP INT TERM
flows="$(uci -q get 'network.@globals[0].steering_flows')"
case "$flows" in ''|0) flows=256;; esac
/usr/libexec/w1700k-affinity.uc -l "$flows" "${1:-1}" || {
	logger -t w1700k-affinity 'Affinity unchanged or rolled back; inspect w1700k-affinity.uc -n'
	exit 1
}
