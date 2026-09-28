# STA control diagnostics

The firmware includes two separate mt76 changes:

- `0017`: optional host-side timing diagnostics. Recording is **off by default**.
- `0018`: device-wide STA statistics polling shared by the active PHYs. Per-radio
  survey and MAC counters retain their existing work cycle.

These changes were introduced in mt76 package release 12. They do not move
authentication or reconnection into the NPU. The diagnostic patch retains beacon thresholds,
watchdog ordering, RX budgets, DMA ownership and recovery behavior.

Patch `0017` includes the NAPI admission correction introduced in mt76 release 14.
Earlier builds
recorded scheduling attempts even when NAPI rejected them, which could leave
a stale timestamp and overstate a later wait. Treat earlier wait maxima as
provisional; they do not by themselves prove CPU contention or a stalled queue.

## Enable and read

The files are under the shared radio's mt76 debugfs directory. Verify the PHY
name on your device before using this example. The kernel needs debugfs;
kernel ftrace support is not required.

```sh
diag=/sys/kernel/debug/ieee80211/phy0/mt76
echo 1 > "$diag/sta_control_diag_enable"
cat "$diag/sta_control_diag"
```

Record snapshots during a short reproduction window. To stop recording and
retain the final snapshot:

```sh
echo 0 > "$diag/sta_control_diag_enable"
cat "$diag/sta_control_diag"
```

A transition from disabled to enabled clears the previous session. Writing 1
while already enabled does not clear it. The enable file accepts only 0 or 1.
The buffer holds 256 events, about 9 KiB including queue counters per device.
Older events are overwritten; `total` and `overwritten` expose this explicitly.
Read periodically if the observation must cover a longer reconnect sequence.
Reads copy a coherent snapshot without consuming it. Recording adds timing and
locking overhead while enabled, so compare results with recording disabled too.

No packet payload, SSID, MAC address, key or password is stored in this buffer.
Normal wpa_supplicant/kernel logs may still contain peer identifiers. Keep raw
captures local and include the image identity and collection time. Collect both
SSH logs and UART console output for a router investigation, noting any transport
failure. Compare `ts_ns` with monotonic uptime, not an NTP-adjusted wall clock.

## Output

The header gives the recording state, monotonic session start, event count and
overwritten count. Each queue row contains:

`queue polls budget_hits wait_max_us run_max_us`

`budget_hits` counts polls that consumed their budget; it is not a drop counter.
With patch `0017`, wait time starts after an instrumented scheduling request acquires
NAPI ownership, before dispatch to the poller, or at the previous budget-exhausted
poll. Rejected attempts do not start or change a timestamp. A fresh accepted
request replaces any timestamp left by a cancelled instance. This order also
prevents a threaded poll on another CPU from starting before its timestamp.
It excludes time before the IRQ/tasklet reaches the request. An internal repoll
without an instrumented admission or a budget timestamp contributes no wait
sample; a zero wait maximum does not prove zero scheduling latency. Pauses for
recovery can also contribute to a wait and must be correlated with reset logs.
Run time measures the poll body before completion/IRQ re-enable, including any
preemption during it. Wait/run events enter the ring only at 2,000 us or above;
the counters and maxima also cover shorter polls.

For the pinned mt76 version, relevant queue IDs include 0 (main RX), 1 (WM MCU),
2 (WA MCU), 6 (band2 RX), 18 (RRO RXDMAD completion), and 19/20 (NPU host RX).
Use `enum mt76_rxq_id` when comparing another driver version. An MCU event queue
must not be assumed to carry every received beacon or EAPOL frame.

Event columns are:

`seq ts_ns event band a b c result`

`band=-1` means a device-wide or queue event. `ts_ns` is the host's observation
time, not a timestamp measured over the air. Event meanings are:

| ID | Event | a | b | c | result |
|---|---|---|---|---|---|
| 1 | Matching associated STA beacon RX | link ID | 0 | 0 | 0 |
| 2 | Beacon-loss decision | link ID | age ms | threshold ms | 0 |
| 3 | MAC work entry | 0 | 0 | 0 | 0 |
| 4 | MAC work before beacon check | initial device mutex wait us | work elapsed after initial lock acquisition us | 0 | 0; `-ECANCELED` if MCU reset caused an early return |
| 5 | MCU command completion | command ID | MCU mutex wait us | preparation/send/response/retry us | command return code |
| 6 | Slow NAPI admission | queue ID | wait us | 0 | 0 |
| 7 | Slow NAPI poll | queue ID | run us | processed count | budget |
| 8 | Control TX submitted to mt76 | frame control | link ID | EAPOL flag | 0 |
| 9 | Control RX decoded | frame control | RX flags | 0 | 0 |
| 10 | STA state callback requested | old state | new state | interface type | 0 |
| 11 | Device-wide STA poll completed | elapsed us | 0 | 0 | first query error, or 0 |

TX/RX control events cover authentication, association/reassociation and
deauthentication/disassociation at the instrumented driver paths. TX also marks
EAPOL when it reaches that callback. They do not prove RF delivery, successful
authentication, reception of every EAPOL frame or completion of the requested
STA state change. Use wpa_supplicant and mac80211 events for the full protocol
timeline. MCU timings cover the common skb-based command path, not an
independent firmware-side clock or every chipset-specific transport.

## Device-wide polling

The first PHY whose statistics cycle is due performs the global rate, airtime
and RSSI requests. Byte and packet requests are enabled with either WED or NPU.
Other PHYs share a deadline at least five watchdog ticks after that sequence
finishes. The next request may be later because it still runs on an eligible
PHY's normal statistics cycle. No dedicated primary PHY is required.

Errors also advance this deadline, preventing an immediate retry by each other
PHY. The next eligible cycle retries. The existing MCU serialization and
per-radio counter collection remain in place. Compared with repeated global
queries from multiple PHYs, the global sampling frequency is lower; verify
airtime accounting and RSSI/rate update responsiveness during device testing.

Starting with mt76 package release 16, only the solicited RSSI response wait
releases the device mutex. A device-wide in-flight flag prevents another PHY
from starting a duplicate poll. Each requested WCID carries a host-side lifetime
snapshot; samples crossing that station's removal/reallocation are discarded.
Unrelated station changes do not discard valid samples. MCU reset cancels the
reply, and no station pointer is retained for use across the wait.
Rate, airtime and traffic-counter requests retain their asynchronous protocol
and counter semantics. An invalidated RSSI sample is retried on the next normal
cycle, without extending the configured polling interval.

Event 4's second duration includes this unlocked RSSI wait and subsequent lock
reacquisition. It is elapsed work time, not continuous mutex ownership. Event 11
also measures elapsed time; completion of asynchronous ALL_STA requests does
not establish that every firmware statistics event has already arrived.

Disabled collectors are gated at their call sites by a shared static key and
a per-device enable flag. Enabling another adapter does not enable this one's
collector. On kernels with jump labels, the globally disabled gate avoids the
out-of-line collector call and per-device flag load. Kernels without jump labels
use the normal conditional fallback. Teardown drops the device's key reference.

The buffer can show where host processing waited. It cannot by itself establish
whether a missing beacon originated at the AP, over the air, in firmware, or in
the host RX path. Firmware build and device A/B tests are still required before
claiming that these changes resolve a specific disconnect.
