#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Source: https://github.com/w1700k/builds/blob/9449e4ca242ab30278df20940d6654ddc1c102e8/user/default/files/etc/testgpio.sh
# Modified 2026-09-18: interpreter/license headers and whitespace normalization.
# Modified by openwrt-w1700k-builds contributors (2026): require an explicit opt-in.
if [ "${1:-}" != --allow-gpio-writes ]; then
    echo 'This hardware test changes GPIO outputs and can interrupt the device.' >&2
    echo 'Usage: testgpio.sh --allow-gpio-writes' >&2
    exit 2
fi

cd /sys/class/gpio || exit 1

for i in $(seq 512 575); do
    echo -e "\nGPIO $i"

    if ! echo $i > export; then
        echo "Cannot export"
        continue
    fi

    if ! echo out > gpio$i/direction; then
        echo "Cannot set to output"
        echo $i > unexport
        continue
    fi

    echo 0 > gpio$i/value
    sleep 1
    if iw dev phy0.2-ap0 info >/dev/null; then
        echo "Wifi still responding"
    else
        echo "Wifi down ??"
    fi

    echo 1 > gpio$i/value
    sleep 1
    if iw dev phy0.2-ap0 info >/dev/null; then
        echo "Wifi still responding"
    else
        echo "Wifi down ??"
    fi

    echo $i > unexport
done
