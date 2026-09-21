# Network steering on W1700K

The Airoha Ethernet driver has two QDMA engines with 32 RX rings and two
TX-completion NAPI contexts each. These are purpose-specific queues: their
existence does not establish RSS support. The current Airoha/mt7996 driver
stack does not expose a general RX hash indirection table. This firmware
does not enable RSS or invent a queue-to-CPU mapping from NAPI PID order.

The default policy keeps each hardware group's IRQs and threaded NAPI on
the same core:

| Hardware group | CPU | Placement |
|---|---|---|
| mt7996 Wi-Fi and mt76 NPU host RX | 0 | Wi-Fi NAPI and both NPU RX IRQs; PCIe IRQs already arrive here |
| QDMA0, driver LAN role | 1 | All four IRQ banks, RX NAPI and TX-completion NAPI |
| QDMA1, driver WAN role | 2 | All four IRQ banks, RX NAPI and TX-completion NAPI |
| Other work | Unrestricted | CPU3 remains available; ordinary processes are not isolated |

All four cores share L2, but each has private L1 caches. Keeping a group's
IRQ and NAPI together avoids unnecessarily moving its receive work between
L1 caches. It does not eliminate all shared data or cache misses.

These are hardware groups, not UCI interface names. A Wi-Fi STA used as WAN
still uses the Wi-Fi group. Multiple bands, SSIDs and AP/STA interfaces share
mt7996's NAPI infrastructure and cannot each receive an independent IRQ CPU.

The kernel patch names Ethernet threads `napi/qdma0-r0` through
`napi/qdma1-r31`, and `napi/qdma0-t0` through `napi/qdma1-t1`. It changes
identification only; ring routing and packet scheduling are unchanged.
The platform policy discovers IRQ numbers by driver names. irqbalance's
policy script excludes these IRQs from its independent balancing.

The mt7996 PCIe MSI children inherit a chained parent IRQ. This policy does
not try to write their unsupported affinity controls or change the PCIe
interrupt lifecycle. It checks that the observed PCIe interrupt counts are
confined to CPU0. This check is an observation, not an independent mechanism
for pinning that parent. A future PCIe affinity implementation needs a
separate review before choosing another Wi-Fi CPU.

## Configuration

The `network` globals option `packet_steering` selects:

| Value | Behavior |
|---|---|
| Unset or `1` | Group placement above; disable RPS and per-queue RFS on Airoha/mt7996 netdevs |
| `2` | Same IRQ/NAPI placement; explicitly enable RPS to CPUs 0–3 and both RFS tables |
| `0` | Release managed task/steerable IRQ affinity to CPUs 0–3; disable RPS and per-queue RFS |

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
retransmissions and 6 GHz reconnects after building and installing it.
Changing steering during traffic can move active work between CPUs.

The separate mt76 pending-frame optimization preserves per-frame DMA kicks,
FIFO, admission checks and per-PHY work limits. Notification batching is not
enabled.
