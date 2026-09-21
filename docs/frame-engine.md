# Frame Engine counters

The NPU and FlowSense pages use the same Frame Engine collector and drop-rate calculation.

- **GDM TX/RX and drop totals** come from the Ethernet driver's cumulative interface statistics. Physical device-tree ports identify the interfaces, including renamed interfaces and NBQ children. The collector does not read, select or reset raw GDM MIB counters. Totals follow the lifetime of the driver/interface; they are not instantaneous rates.
- **PSE port drops** show the total counter plus the increase, elapsed interval and drops per second. A nonzero historical total does not mean drops are still occurring. P7/CDM4 includes the Wi-Fi path; it does not identify a particular radio, station or drop reason.
- **FlowSense Drop counters** reports PSE and CDM HWF drop rates separately. “Drops observed” means counters increased. It does not diagnose shared-buffer exhaustion. Shared-buffer occupancy remains a separate instantaneous measurement on the NPU page.
- **N/A** means a sample is unavailable, incomplete or needs a baseline. Failed samples retain the last valid baseline. Reboot detection uses the boot ID and rate intervals use router uptime, avoiding wall-clock changes. Counter decreases are treated conservatively as a reset or wrap and establish a new baseline; the page does not invent a large increase.

The first valid sample establishes a baseline. A later sample provides a rate over the displayed interval, including gaps between successful queries. This interval average cannot reveal bursts shorter than the sampling interval.

The CDM **HW Offload** percentage remains the ratio of that CDM's RX HWF and RX CPU counters, not the router's overall current acceleration percentage. Wi-Fi percentages on the NPU page describe retries, not CPU utilization.

These monitoring changes do not alter IRQ/NAPI placement, RPS/RFS, hardware forwarding, DMA ring sizes or NAPI budgets.
