# Temporary r36404 original-NPU comparison

This branch builds OpenWrt `20ed53a1d3e75555300f63a0a7c66b9466e7b671`
with the original `airoha-en7581-mt7996-npu-firmware` package from
linux-firmware 20260910. All four additional RC commits remain applied.

The source manifest, feeds and official feed metadata are pinned to the successful
RC run 35432580608. The build environment is pinned to the same container digest.
No airoha-npu-fdk source checkout, compilation or firmware replacement occurs.
Both installed NPU blobs must match the checksum-verified linux-firmware archive.

The temporary workflow uploads a diagnostic Actions artifact. It does not publish
or replace the normal RC/stable releases, change their source branches, or save
the diagnostic package state to the normal recovery registry.

The image keeps the r36404 source revision and has a `-stock-npu.itb` suffix so
it can be distinguished from the original RC. No router is flashed by this job.
