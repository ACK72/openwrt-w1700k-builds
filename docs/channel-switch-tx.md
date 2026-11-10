# Channel switches and TX on the shared radio

The MT7996 runs 2.4, 5 and 6 GHz as three radios of one wiphy, and mt76 sends
host frames for all of them from one TX worker. Every channel switch, including
each step of a scan, goes through `__mt76_set_channel()`. Before patches `0022`
and `0023` that function parked the worker for the whole switch and waited up to
200 ms (`HZ/5`) for the switching radio's pending TX.

Two problems followed on 2026-11-10 (r38183):

- The wait includes the count of management (PSD) frames still in firmware, added
  upstream by mt76 447cc8c8. One frame whose TX-free record never arrived kept the
  6 GHz count above zero until the next reboot. With the 6 GHz STA scanning for a
  missing AP, every one of its 59 scan steps then stopped host TX on all bands for
  200 ms: Wi-Fi clients saw 80-150 ms average ping to the router, peaks above
  400 ms, and slow SSH echo. A scan took 17.3 s instead of about 5 s.
- Even without that, each scan step stopped the other bands for about 12 ms, the
  time of the firmware channel switch.

## Changes

`0022` stops counting a management frame two seconds after it was handed to the
firmware. These frames are sent immediately, so their record has been lost by
then. The token and its buffers stay allocated, so a late record still releases
them. The first lost frames of a burst are logged:

```
band 2: 1 management frame(s) got no TX completion (oldest 2310 ms, fc 0x00b0); channel switches no longer wait for them
```

The fanboy stack's own fix (`0006-wifi-mt76-reclaim-lost-txfree-tokens.patch`)
frees tokens of frames without status tracking after 5 s. It decrements the same
count, so all three places (completion, this expiry and that reclaim) use one
per-token flag and a token is subtracted only once. Frames that request a TX
status, such as authentication frames, are not reclaimed there.

`fc` is the 802.11 frame control of the oldest one: `0x00b0` authentication,
`0x00c0` deauthentication, `0x00d0` action, `0x0040` probe request, `0x0048` null
data and `0x00c8` QoS null. The to-DS and power-management flags add `0x0100` and
`0x1000`. Please keep these lines when reporting a problem: they show which frames
lose their completion.

`0023` parks the worker only while the switching radio's queued frames are
flushed and the radio is marked in reset. The worker already skips stations of a
radio in reset, so the other radios keep transmitting during the drain and the
firmware switch. 5 and 6 GHz share one host TX ring with NPU offload, so the
switch now waits for the frames that were queued before it started rather than
for an empty ring. A device with a single radio keeps the previous behavior.

## Reading the counters

```sh
cat /sys/kernel/debug/ieee80211/phy0/mt76/token_info
```

The last section lists each band:

| Column | Meaning |
|---|---|
| `mgmt_pending` | Management frames still waiting for their TX-free record. It should return to 0 within a fraction of a second. |
| `mgmt_expired` | Frames that `0022` stopped waiting for since boot. |
| `wait_timeouts` | Channel switches that gave up waiting after 200 ms. |

A `wait_timeouts` count that grows by about one per scan step means the switch
still waits the full time. Compare the scan length with `iw event -t`: the time
from event 33 (scan started) to event 34 (results) was 17.3 s with the stuck
count and about 4.7 s after a reboot.

## Limits

These patches were checked by applying them to the exact mt76 source of r38183;
they have not yet run on a device. `0023` changes TX during every channel change,
not only scans: off-channel work and operating channel changes such as DFS moves
also go through `__mt76_set_channel()`. If a build shows TX problems around channel
changes, drop `0023` first; `0022` does not depend on it. Neither patch explains why
the firmware record was lost.
