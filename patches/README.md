# Patch organization

`w1700k/series.json` is the ordered input to source composition. The composer
applies each mail patch with `git am`; the resulting OpenWrt tree contains the
kernel and mt76 patches used by the package build. Changes belong here, not in
the generated OpenWrt branches. Existing numeric IDs remain stable, so gaps in
the series are intentional.

Related ACK72 changes are consolidated as follows. Each combined inner patch
applies the final implementation directly, without installing and then replacing
an intermediate implementation.

| Current W1700K patch | Included former patches | Responsibility |
| --- | --- | --- |
| `0004` | `0004`, `0012`, `0017`, subsequent release hunks | Set mt76 release 16 and hostapd release 4 once |
| `0013` | `0013`, `0027` | NPU RX descriptor/page ownership and validated single-buffer path |
| `0016` | `0016`, `0028` | Shared-radio pending TX fairness and ordinary doorbell batching |
| `0019` | `0019`, `0022`, `0029` | Opt-in diagnostics, accepted NAPI timing, static-key gating and cleanup |
| `0020` | `0020`, `0023`, `0030` | Device-wide station polling, NPU counters and unlocked RSSI waits |
| `0024` | `0024`, `0026` | Reference-counted IPv6 source-MAC slots and checked idle-slot reuse |

Other ACK72 changes retain separate responsibilities: `0005` initializes
PERSTOUT, `0014` validates firmware events and Ethernet handling, `0015` handles
channel/recovery lifecycle, `0018` provides the kernel named-NAPI API, `0021`
names Wi-Fi queues, `0025` manages shared QDMA GRO, `0031` reduces MMIO/power-table
overhead, and `0032` reduces guarded Ethernet/NPU control-path overhead.
Keep `0018` before `0021`; they affect different source layers.

In `flowsense/`, `0001` combines the previous `0001` and `0003` display fixes:
sampled RTT, stale measurements and CPU availability. `0002` remains the separate
backend/RPC adaptation. The LuCI missing-device guard remains separate.

The imported W1700K patches `0001`–`0003` and `0006`–`0011` are unchanged. Their
original author, date, message, attribution and individual commits must be
preserved by source composition and promotion. ACK72 adaptations retain their
`Adapted-from` and `Source` references. The LuCI channel-analysis and mwan3
route-state patches have no `From:` header and were not folded into ACK72 groups.

Use a fresh source composition after changing the series. The final driver code,
package releases and FlowSense package contents are unchanged by this
consolidation. The complete FlowSense stack remains safe to apply again; a tree
with only part of a retired patch sequence should be recreated from clean inputs.
