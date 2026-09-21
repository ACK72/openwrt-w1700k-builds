# W1700K OpenWrt

**[Release firmware](../../releases/latest)** · [RC firmware](../../releases)

Custom `w1700k-oc` firmware for the Gemtek W1700K HW2.1.\
This project builds images that include OpenWrt, Airoha NPU firmware, and additional packages.

In LuCI's **Attended Sysupgrade**, use **Check for GitHub firmware** to select and install a stable or RC image.

See [network steering](docs/network-steering.md) for IRQ/NAPI placement and optional RPS/RFS configuration.
See [Frame Engine counters](docs/frame-engine.md) for cumulative traffic totals and timed drop measurements.

## Based on

Based on the work of [OpenW1700k](https://github.com/OpenWRT-fanboy/OpenW1700k), [Gemtek-W1700K-6.18](https://github.com/Gilly1970/Gemtek-W1700K-6.18), and [w1700k/builds](https://github.com/w1700k/builds).
