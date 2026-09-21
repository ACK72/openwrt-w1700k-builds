# FlowSense display and nft-native mwan3 integration

## Confirmed display failure

The installed eb12d8f image contained npu-jitter's S99 link in /rom, but the
active overlay had no link, no procd instance and no result file. The supplied
backup contains `/etc/uci-defaults/10_disable_services` with
`/etc/init.d/npu-jitter disable`. It runs at the next boot, after a restore-time
manual enable. The old RPC backend also derived CPU load from the missing ping
file and substituted zero, hiding the failure.

The new S98 w1700k-monitor hook runs after uci-defaults on every boot and starts
the sampler unless its UCI enabled option is explicitly zero. CPU sampling now
uses /proc/stat independently, excludes guest double counting, treats the first
or stale sample as unavailable, and reuses same-second results. A valid idle
sample remains 0%. Ping averaging, mean absolute deviation jitter, five-second
probe interval and the last 12 attempts are unchanged.

Live checks: disabling the sampler and invoking the boot hook restored S99 and
12/12 replies; CPU continued updating while the ping service was stopped. LuCI
displayed CPU 8% and `32.8ms`, with `Jitter: 14.9ms | 12/12 replies | 1.1.1.1`.
These are snapshots, not throughput or latency guarantees.

## Gilly r7 review and adaptation

Source: [Gilly commit 4a1e357](https://github.com/Gilly1970/Gemtek-W1700K-6.18/commit/4a1e35762e382dfaf2306da9b079c548e2f3d632).
The ucode parser removes hundreds of shell subprocesses and fixes the airtime
efficiency history field offset. Its RPC names and output schema are compatible
with our UI, and getJitterResult passes through our extended sampling fields.
The package include path and dependencies require adaptation to our build tree.

Do not install the native in-process plugin unchanged. It performs synchronous
nl80211 and debugfs queries inside rpcd. This device has a history of blocked
driver operations; the rpcd event-loop timeout cannot run while a syscall is
blocked. A local experiment with uloop worker isolation also failed to exit
cleanly on this runtime; the experiment was stopped and never installed as a
production plugin.

We adopt its parsing code as a ucode **exec plugin**, preserving the existing
process boundary and rpcd's exec supervision. There is exactly one FlowSense
RPC registration. This does not fix a kernel D-state hang, nor guarantee that
a blocked child can immediately be killed. The sampler and UI customizations
remain; CPU no longer depends on jitter JSON. The unused r5 shell backend is
retained outside rpcd's plugin directory as a manual fallback, as in Gilly r7.

All 16 read RPC methods passed on the device. In three consecutive 16-method
cycles, whole-system process creation deltas were 602–628 for r5 versus 119–135
for the adapted backend. Elapsed time was 2.58–2.60 s versus 1.61–1.65 s.
Background activity contributes to these counts; they demonstrate lower query
overhead, not an equivalent percentage reduction in whole-router CPU load.

## mwan3 built into the image

The requested installer selects dl12345/mwan3 and dl12345/luci-app-mwan3.
We pin both v3.6.12-1 source releases and archive SHA-256s in
configs/extra-packages.json. Recipes are installed before feed indexing and
dependency selection; nft and ucode dependencies are resolved normally. Both
packages are selected with `=y`, locally compiled, signed and included in the
image, without a boot-time download or untrusted binary APK installation.

The previously reviewed route-state refresh fix is applied to mwan3rtmon before
packaging. Local package releases become 3.6.12-r2 and 26.999.3.6.12-r2. The
extra source lock is retained in the build artifacts. Image verification checks
the nft RPC plugin, patched rtmon and the restore-safe monitor startup link.

## 5 GHz test and remaining problem

Installed firmware: eb12d8f, r36438-7bf0e980a7, official NPU firmware. PC wired
link 2.5 Gbps; Mac associated on 5 GHz channel 36 / 80 MHz, PHY about 1201 Mbps.
Four TCP streams, two-second warm-up excluded:

| Direction | 100 Mbps limit, 12 s | Unlimited, 30 s |
|---|---:|---:|
| PC to Mac | 100.18 Mbps | 952.25 Mbps |
| Mac to PC | 99.90 Mbps | 828.84 Mbps |

Mac-to-PC unlimited reported 2813 TCP retransmissions. No 5 GHz disconnect,
new kernel warning, PCIe completion timeout or reboot was detected in this
short test. It does not establish long-duration or 10 Gbps stability.

The concurrent 6 GHz STA had beacon loss at 18:51:37 and reconnected at 18:51:48.
Another beacon-loss reconnect occurred before this controlled test, at 18:40.
Therefore the shared-radio/6 GHz issue remains unresolved; these observations
do not prove that 5 GHz load alone causes it. This change does not alter the
wireless scheduler or claim to solve that remaining driver/firmware problem.

Raw logs, device configuration and packet-flow details remain outside the public
repository under the local Tests directory. Local suite: 50 tests, 47 passed,
3 skipped for unavailable jq; patch replay and JavaScript syntax were checked.
