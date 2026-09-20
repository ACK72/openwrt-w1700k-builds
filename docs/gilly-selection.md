# Selected W1700K correctness fixes

Source review: [Gilly1970/Gemtek-W1700K-6.18 at 0aa0666](https://github.com/Gilly1970/Gemtek-W1700K-6.18/tree/0aa0666de1366b69d5d73d98c19809affc1f76ed/openwrt-patches).
The embedded patches retain their original authors and commit descriptions.

| Gilly patch | Reason for selection | Performance scope |
| --- | --- | --- |
| 034 | Prevent hard IRQ re-entry while accessing a shared register remap window | IRQ exclusion only for remapped register accesses |
| 035 | Recheck WCID pointer identity under the TX status lock | Existing locked status allocation path |
| 036 | Unpublish the WCID before reset cleanup | Reset path only; does not replace RCU lifetime rules |
| 042 | Send disassociation frames through the same queue as deauthentication | Management traffic only |
| 045 | Refresh negotiated TX aggregation timeouts for NPU offload | Extends the existing WED aggregation refresh gate |
| 048 | Guard the station pointer in EAPOL MLO address translation | Authentication traffic only |

The source pin, official linux-firmware NPU blobs, hardware offload, queue sizes,
CPU clock policy and user network settings are retained. There is no throughput
cap or software-only fallback in this selection. mt76's package release is bumped
so package and image identity reflect the changed code.

Do not import Gilly's entire board DTS, kernel config, mt76 Makefile or regulatory
database. Those files change the partition/device identity, source/dependency
model, clock policy and regulatory behavior. Its QDMA stall recovery patch 981
can continue freeing RX buffers after a DMA-busy timeout; it is excluded. Full
Wi-Fi/NPU reset patch 047 also needs explicit stop-ack/error handling before DMA
memory is reclaimed. Bounds patch 026 needs an additional AIR_TIME event case
for the ACK72 source and is excluded from this minimal selection.

An independent defect was found in the inherited PCIe PERSTOUT backport:
`en7523_reset_update()` used `val |= ...` on an uninitialized local variable.
The preceding patch changes both branches to direct assignment. This repairs
undefined behavior; it is not by itself proof of the cause of a particular
PCIe link-training failure.

Validation before image generation: all six patches applied in sequence to the
effective ACK72 mt76 source, including its existing patches, without fuzz.
Runtime acceptance requires cold and warm boots, 6 GHz STA reconnect, 2.4/5 GHz
AP operation, mwan3 failover, sustained traffic and responsive LuCI RPC calls.
Compilation or patch application alone does not establish runtime stability.
