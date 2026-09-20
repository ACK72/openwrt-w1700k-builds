# Gilly follow-up review, 2026-09-21

`origin/main` was fetched again from Gilly1970/Gemtek-W1700K-6.18. Its HEAD
remains `0aa0666de1366b69d5d73d98c19809affc1f76ed`, the revision used in
[the earlier selection](gilly-selection.md). There are no new main-branch
commits since that review. Patch numbers below refer to its `openwrt-patches`.
This is a recommendation list, not an additional kernel patch import.

## Highest-value next changes

| Change | Current ACK72 evidence | Recommendation |
| --- | --- | --- |
| 026 ALL_STA_INFO bounds | Effective `mt7996/mcu.c` still trusts `sta_num`, and handles `UNI_ALL_STA_TXRX_AIR_TIME` in addition to Gilly's three tags | Port the length/count checks with the AIR_TIME element size included. Test truncated headers, oversized counts and all four valid events. Gilly's original default-return would silently discard airtime reports. |
| 044 IE-countdown TLV bounds | Effective parser reads a TLV payload before checking that its complete length is present | Port the bounds checks, adding a check for the MCU/event header before reading `hdr->band`. The Gilly patch only hardens the subsequent TLV loop. This is defensive parsing, not evidence that a malformed event caused the observed PCIe timeout. |
| 949 PPE error propagation | Backport 099-08 declares outer `err = 0` and then shadows it inside the SRAM-flush loop | Remove the inner declaration so commit failures propagate to the caller. Check that no later source update has already fixed the function before applying. This is an initialization/error-path fix with no normal packet-path cost. |
| 047 full-reset NPU lifecycle | A new real failure followed a 6GHz configuration change: channel-switch MCU timeout, PCIe completion timeouts, repeated failed full resets; a warm reboot did not recover Wi-Fi | Adapt the idea, not the patch unchanged: verify NPU DMA-stop acknowledgement before reclaiming/rebuilding rings; propagate stop failure; quiesce scan/NAPI/work queues consistently; only resume traffic after successful NPU/ring handoff. The supplied patch ignores the return from `mt7996_npu_hw_stop()`. It does not explain the initiating channel-switch/PCIe failure by itself. |

## Useful with separate compatibility validation

- **039 + 046 statistics:** integrate polling with ACK72's existing AIR_TIME/RSSI
  work instead of inserting duplicate periodic MCU queries. Verify that firmware
  counters are cumulative or interval counters, and that switching from software
  counters on zero values does not make totals jump/backtrack after reset. This
  can improve offloaded station statistics; it cannot measure network latency.
- **032 small BlockAck windows:** a focused Apple-client compatibility experiment
  if a failing station actually negotiates a window below 64. Gilly's hardware
  limitation statement is an author claim, not independently proven by our tests.
  Preserve offload for ordinary bulk queues and record negotiated BA parameters.
- **033 session teardown:** resolve synchronization between asynchronous status
  events and teardown, valid session ID zero, stale events, and MLO link selection
  before use. A mutex held only by the reader is not sufficient synchronization.
- **027 NPU station bitmap clear:** confirm the stock firmware message ABI, valid
  WCID/TID range and completion/failure semantics before index reuse. Its prose
  says TIDs 0–7 but the loop sends 0–8, and failures are silently skipped.
- **957 BQL/UAF and 980 RX_NO_CPU_DSCP IRQ:** audit against the fully prepared
  kernel, not patch filenames alone. These address shared QDMA lifetime and a
  possible missed RX wakeup, respectively. The present wired throughput test is
  not proof that either proposed change is needed, safe, or the cause of the
  separate Wi-Fi PCIe error.
- **963 MIB collection:** removing periodic reset can avoid counter loss, but
  review 64-bit high/low read consistency, reset detection, wrap and multiple
  devices per GDM. Prefer consuming kernel-exported software totals in dashboards
  over changing hardware accounting merely to make raw-MMIO graphs look stable.

## Already present or unsuitable as a blanket import

Effective mt76 already has the 019 boundary `break`, the 037 twelve-byte delete
event layout, 041 `INVALID_REG_ADDR`, and 043 teardown/ALTX handling. The six
selected fixes 034/035/036/042/045/048 are already included. The kernel already
contains the queue-31 RX_DONE fix corresponding to 976 and uses `NETIF_F_GRO_HW`;
do not import the entire 975/977 series over it.

981 remains unsuitable as written: its timeout path can reclaim RX buffers
without confirmed DMA stop, and its work-disable/re-enable lifecycle needs
review. Whole DTS, kernel config, mt76 Makefile, regulatory DB, interface
defaults and prebuilt NPU files should not be copied. They change the board
identity, source/dependency model, clocks, recovery logging, regulatory behavior
or user network configuration alongside the intended fix.

FlowSense's missing latency was independently traced to its disabled sampler.
This builder now uses a low-rate, bounded RTT sampler and displays the mean,
loss and stale state. No packet-path kernel patch is required for that fix.

Source: https://github.com/Gilly1970/Gemtek-W1700K-6.18/tree/0aa0666de1366b69d5d73d98c19809affc1f76ed/openwrt-patches
