# Network steering on W1700K

The Airoha Ethernet driver has two QDMA engines with 32 RX rings and two
TX-completion NAPI contexts each. These are purpose-specific queues: their
existence does not establish RSS support. The current Airoha/mt7996 driver
stack does not expose a general RX hash indirection table. This firmware
does not enable RSS or invent a queue-to-CPU mapping from NAPI PID order.

The default policy places Ethernet IRQs/NAPI and Wi-Fi NPU host RX IRQs/NAPI
on CPUs 1, 2 and 3. CPU0 retains normal OS/kernel scheduling:

| Hardware group | CPU | Placement |
|---|---|---|
| QDMA0, driver LAN role | 1 | All four IRQ banks, RX NAPI and TX-completion NAPI |
| QDMA1, driver WAN role | 2 | All four IRQ banks, RX NAPI and TX-completion NAPI |
| mt7996 Wi-Fi and mt76 NPU host RX | 3 | Wi-Fi NAPI and both `mt76-npu.0` / `mt76-npu.1` RX IRQs |
| mt7996 PCIe MSI | 0 (existing path) | Chained IRQ delivery is unchanged; see the exception below |
| OS/kernel and other work | Default scheduler | CPU0 is not assigned a managed QDMA/NPU/NAPI group; ordinary tasks are not pinned or isolated |

All four cores share L2, but each has private L1 caches. Keeping a group's
IRQ and NAPI together avoids unnecessarily moving its receive work between
L1 caches. The PCIe IRQ exception below still crosses cores, and normal OS
tasks may also run on CPUs 1-3. This policy does not eliminate all shared data
or cache misses and does not reserve CPU0 exclusively for OS work.

These are hardware groups, not UCI interface names. A Wi-Fi STA used as WAN
still uses the Wi-Fi group. Multiple bands, SSIDs and AP/STA interfaces share
mt7996's NAPI infrastructure and cannot each receive an independent IRQ CPU.

The kernel patch names Ethernet threads `napi/qdma0-r0` through
`napi/qdma1-r31`, and `napi/qdma0-t0` through `napi/qdma1-t1`. It changes
identification only; ring routing and packet scheduling are unchanged.
Names are assigned when each thread is created and retained for recreation,
so the identity read through `/proc` matches the hardware group.
The platform policy discovers IRQ numbers by driver names. irqbalance's
policy script excludes these IRQs from its independent balancing.

The mt7996 PCIe MSI children inherit a chained parent IRQ. This policy does
not try to write their unsupported affinity controls or change the PCIe
interrupt lifecycle. It checks that the observed PCIe interrupt counts are
confined to CPU0. This check is an observation, not an independent mechanism
for pinning that parent. Wi-Fi NAPI and the steerable NPU RX IRQs run on CPU3,
so PCIe work that schedules Wi-Fi NAPI can require a cross-core wakeup. This
does not move every Wi-Fi interrupt to CPU3. Moving the PCIe parent itself
would require a separate driver change and validation.

## Configuration

The `network` globals option `packet_steering` selects:

| Value | Behavior |
|---|---|
| Unset or `1` | Group placement above; disable RPS and per-queue RFS on Airoha/mt7996 netdevs |
| `2` | Same IRQ/NAPI placement; explicitly enable RPS to CPUs 0–3 and both RFS tables |
| `0` | Release managed task/steerable IRQ affinity to CPUs 0–3; disable RPS and per-queue RFS |

In LuCI, select **Packet Steering: Enabled** (`1`) and **Steering flows (RPS):
Standard: none** (empty or `0`) for the default placement with RPS/RFS off.
Mode `1` also clears previously enabled RPS masks and per-queue RFS tables;
only an explicit mode `2` enables software steering. An allocated global RFS
table alone does not enable RFS when the managed per-queue tables are zero.

irqbalance continues to exclude managed IRQs in mode `0`. Other devices and
the firewall's hardware offload settings are left under their existing
configuration. No changes to NPU firmware, DMA ownership or queue sizes are
part of this policy.

In mode `2`, `steering_flows` sets entries per RX queue (default 256, range
16–4096, rounded up to a power of two). The global RFS socket table is at
least 32768 entries and at least the sum required by these queues. An existing
larger global table is preserved. Both global and per-queue RFS support must
exist before any changes are applied. Mode `1` clears per-queue RFS tables
as well as RPS masks, since RFS can steer traffic even with an empty RPS mask.

RPS uses a flow hash; it is not packet-by-packet round-robin. RFS follows the
CPU of a local socket's application and preserves ordering during migration.
It is **not a permanent session lock**, and does not guarantee that both
directions of a NAT connection use one CPU. Forwarded router traffic usually
has no local receiving application for RFS to follow. Enable mode `2` only
after measuring a CPU bottleneck; it adds software overhead and IPIs.
See the [Linux scaling documentation](https://docs.kernel.org/networking/scaling.html)
and [threaded NAPI guidance](https://docs.kernel.org/networking/napi.html).

Inspect an explicit mode without changing any affinity:

```sh
/usr/libexec/w1700k-affinity.uc -n 1
/usr/libexec/w1700k-affinity.uc -n -l 256 2
```

To apply the configured UCI mode, reload `/etc/init.d/packet_steering`.
Boot, interface events and the netdev-add hook also run the platform policy.
The generic `/usr/libexec/network/packet-steering.uc` is not the W1700K policy;
do not invoke it directly to manage this board's affinity.

The policy requires all four CPUs online, all 68 named QDMA contexts and all
eight Ethernet IRQ banks. It rejects anonymous NAPI from older kernels and
an irqbalance process started without the matching policy. Unknown or
incomplete topology aborts before writes. Failed writes/readback trigger
best-effort restoration; a rollback failure is reported. Repeated reloads
avoid rewriting unchanged settings and resetting flow tables.

## Validation limits

Source-level checks and simulated ucode tests cover group identification,
RFS prerequisites, repeated reloads and rollback. They do not establish a
throughput gain or connection stability on a newly built image. Compare
download/upload throughput, loaded RTT p95/p99, CPU/softirq load, drops,
retransmissions and 6 GHz reconnects after building and installing it. Include
CPU3 saturation and CPU0-to-CPU3 PCIe/NAPI wakeups in that comparison.
Changing steering during traffic can move active work between CPUs.

The separate mt76 pending-frame optimization preserves per-frame DMA kicks,
FIFO, admission checks and per-PHY work limits. Notification batching is not
enabled.
