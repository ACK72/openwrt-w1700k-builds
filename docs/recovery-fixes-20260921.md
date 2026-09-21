# Wireless recovery and selected correctness fixes

This implements the concrete defects in `wifi-recovery-review-20260921.md`.
It retains the official NPU blobs, ring sizes, clocks, offload and RX page-pool
path. It does not claim to repair an electrically or logically unresponsive
PCIe endpoint or to identify the first cause of command 0x34 timing out.

## Changes

- Complete accepted scan and ROC requests exactly once even during MCU reset.
  Suppress RF restoration during reset, not the mac80211 software completion.
  Stop scanning after a channel error, without sending probes or scheduling
  another channel. Cancel same-radio scan/ROC work before context changes.
- Roll back cached channel/context state after a failed update. Keep TX stopped
  if a channel command initiated MCU recovery. Do not requeue the MAC worker
  after failed channel setup. Report the failed channel TLV tag, band, channels,
  width, reason, scan/ROC flags, duration and errno at a bounded rate.
- Check the existing official-NPU stop protocol before any reset ring cleanup:
  SET index 4, GET index 3 until idle, then SET index 6. Do not treat interrupt
  masking as DMA quiescence. A failed stop retains the buffers and stopped TX.
- Give full reset the NPU-owned NAPI exclusions and NPU reinitialization missing
  from the previous code. Check NPU reinitialization and each L1 handshake.
  Perform one full restart attempt, instead of ten while holding `mt76.mutex`.
  A failed recovery keeps reset flags and stopped queues, fails later MCU
  requests promptly, and does not wake queues or request a fake mac80211 restart.
  NAPI enable/disable remains balanced. The terminal state requires a device
  restart; a persistent PCIe fault can still require power removal.
- Survey queries return a bounded error while the device mutex is busy/resetting,
  preventing the observed `rpcd -> mt76_get_survey -> mutex_lock` indefinite wait.
- Beacon monitoring skips reset downtime and refreshes its timestamp after a
  successful L1 recovery. Keep the seven-interval loss threshold. Error-only
  diagnostics record beacon age, band/link, scan/ROC flags and outstanding tokens.
  This does not prove the separate 6GHz STA beacon-loss episodes were caused by
  5GHz load; previous AP throughput tests did not validate the STA/WWAN role.

## Gilly selection

`0008` ports 026/044 with all four station-event tags, including AIR_TIME, and
with event-header validation before the countdown band's first dereference.
It also ports 949 (PPE SRAM error propagation), 957 (TX pointer/BQL cleanup),
and 980 (route RX_NO_CPU_DSCP interrupts to NAPI in both banks and rearm them).
`0009` adapts 047 with checked stop/reinitialization and failure containment.
Attribution and the exact reviewed Gilly commit are preserved in the patches.

Conditional 027/032/033/039/046/963 recommendations remain conditional for the
ABI, synchronization and counter-semantics reasons in `gilly-followup-20260921.md`.
No entire configuration, DTS, prebuilt NPU or regulatory patch set is imported.

## Validation scope

The nested patches were replayed on the previously deployed effective source.
The resulting mt76 files match the implementation tree after LF normalization.
The existing 30 local tests pass, including new tests executing the actual C
function bodies extracted from the patches with mocked kernel boundaries:

- Full reset success and stop/firmware/NPU/EEPROM/TXBF/radio failures, with NPU
  and WED queue ownership represented (14 cases).
- L1 success and stop/NPU/all three handshake failures (6 cases).
- Scan completion during reset, duplicate completion, RF restoration failure,
  scan channel failures, and ROC completion (9 cases).
- All four station tags, truncated headers/payloads, oversized/zero counts,
  unknown tags and malformed/countdown TLVs (34 cases).

These tests check control flow and ownership, not hardware DMA/AER behavior.
Full ARM64 compilation and router acceptance are recorded separately when done.
No dangerous PCIe fault injection or unvalidated AER callback is included.

## NPU memory investigation

Current reservations are 10 MiB firmware, 32 + 16 MiB QDMA, 44 MiB WLAN RX packet
storage, 64 MiB WLAN TX packet storage, 26 KiB TX buffer IDs and 2 MiB BA storage.
The driver passes the WLAN regions' start addresses to the official firmware;
it does not pass their `resource_size()` as a usable capacity. The memory map
can be edited in DTS, but increasing the reservation alone does not increase
firmware pool counts and can overlap adjacent regions. Shrinking a firmware
pool without the matching ABI can permit out-of-range DMA.

The SoC PSE shared-page pool is a separate hardware resource. The observed
12064 free pages are not those DRAM reservations. Enlarging reserved DRAM
does not enlarge PSE or the 8192 hardware token pool. Ring/packet metadata
counts and address/layout contracts would need independent validation.

At the first fresh read, Linux had about 1.55 GiB MemAvailable. Earlier 6GHz AP
tests exceeded 1.5 Gbit/s in both directions. Neither result excludes short
buffer-pressure bursts, but neither supports a DRAM-reservation shortage as
the cause of the earlier 250 Mbit/s failure. Post-fault PSE=0 cannot establish
the pre-fault high-water mark. No capacity change is justified by these data.

## Latency CPU measurement

On 2026-09-21, three 60-second periods with five seconds of settling yielded:

| Sampler | Total CPU busy, all four cores | Sampler plus reaped children |
| --- | ---: | ---: |
| on, first | 3.546% | 39 / 24086 ticks = 0.162% |
| off | 4.681% | absent |
| on, second | 1.604% | 36 / 24072 ticks = 0.150% |

The whole-system variation is not a controlled causal estimate: background
traffic/UI polling varied. `rpcd` plus its children accounted for 496, 780 and
124 ticks respectively, much more variable than the sampler. Independent
`/proc/stat` and process accounting do not show the sampler causing a material
CPU regression. The existing dashboard reads `cpu_pct` from this sampler's
JSON and falls back to zero without it, so enabling it also changes a missing
measurement into a real CPU reading. Preserve the current mean RTT/jitter
algorithm and five-second probe interval.
