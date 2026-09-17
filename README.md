# W1700K OpenWrt Builder

Gemtek W1700K용 OpenWrt 펌웨어를 자동으로 빌드합니다.

[ACK72/openwrt의 `ubi2-oc` 브랜치](https://github.com/ACK72/openwrt/tree/ubi2-oc)와 [ACK72/airoha-npu-fdk](https://github.com/ACK72/airoha-npu-fdk)를 기반으로 OpenWrt와 NPU 펌웨어를 빌드합니다.

## 설치 파일과 릴리즈

[Releases](https://github.com/ACK72/openwrt-w1700k-builds/releases)에서 최신 `*-sysupgrade.itb`를 받으세요. 이 이미지는 **UBI2 파티션과 호환 chainloader를 이미 사용하는 W1700K**의 업그레이드용입니다. 순정 펌웨어에서 직접 설치하거나 다른 파티션 구성에 강제 설치하는 용도가 아닙니다.

- `main`의 빌드 관련 변경, 매일 예약 실행, 수동 실행에서 성공한 이미지를 자동으로 정식 릴리즈에 게시합니다. 별도의 `publish` 체크는 필요하지 않습니다.
- 이 workflow가 만든 릴리즈는 최신 **3개**를 유지합니다. 새 이미지와 모든 첨부 파일의 업로드·SHA-256 검증 및 공개가 끝난 후에만 오래된 릴리즈와 태그를 삭제합니다. 다른 용도의 릴리즈와 미완성 draft는 삭제하지 않습니다.
- 각 릴리즈에는 설치 이미지, `SHA256SUMS`, 실제 설정, 정확한 feeds 커밋, 빌드 manifest, 해당 이미지와 함께 서명한 APK 묶음 및 공개키가 포함됩니다. `sha256sum -c SHA256SUMS --ignore-missing`으로 받은 파일을 확인할 수 있습니다.
- `packages.tar.zst`의 APK는 해당 이미지와 함께 사용하세요. 공개 snapshot 저장소의 kmod는 커널 ABI가 다를 수 있습니다. 공개키는 각 빌드에서 생성되며, 서로 다른 릴리즈의 패키지 키를 영구적으로 신뢰하는 설정을 추가하지 않습니다.

이 프로젝트의 정식 배포 채널은 `ubi2-oc`입니다. OpenWrt 공식 stable 버전으로 기반 소스를 바꾸는 것은 아니며, CI는 실제 기기 부팅·무선·NPU 동작 검증을 대신하지 않습니다. 설치 전 현재 설정을 백업하고 기기에서 이미지 호환성 검사를 통과했는지 확인하세요.

## 빌드와 캐시

`Release W1700K ubi2-oc` workflow는 소스와 feeds를 해석한 뒤 각 커밋을 `build-manifest.json`과 `feeds.lock`에 기록합니다. 같은 fingerprint의 완전한 릴리즈가 이미 있으면 컴파일을 생략합니다. artifact만 있고 릴리즈 게시가 실패했다면 다시 빌드·게시합니다.

- `force`: 같은 입력이라도 새 릴리즈를 생성합니다. 빌드 캐시는 재사용합니다.
- `clean`: 다운로드를 제외한 NPU·컴파일·빌드 캐시를 복원하지 않고 전체를 다시 빌드합니다. 캐시 비교 검증이나 비정상 상태 복구에 사용합니다.
- `runner`: x86-64 또는 ARM64 Ubuntu 24.04를 선택합니다. 아키텍처별 캐시를 분리합니다.

BuildWrt의 빌드 상태 보존 방식을 적용해 `build_dir`와 `staging_dir`의 커널·패키지·hostpkg까지 재사용합니다. Docker registry 계정 없이 GitHub Actions 캐시를 사용합니다. 새 소스와 설정을 먼저 준비하고 **내용과 권한이 같은 입력에만** 이전 타임스탬프를 적용합니다. 삭제된 입력은 패키지 Makefile을 무효화합니다. 이전 `.config`, 소스, signing private key와 최종 이미지는 캐시에서 덮어쓰지 않습니다.

툴체인 키는 실제 빌드 의존성과 컴파일러 설정을 포함하며 일반 패키지 선택·릴리즈 문구·무관한 호스트 프로그램 업데이트에 독립적입니다. 전체 빌드 캐시는 전체 패키지/커널 설정이 호환될 때만 재사용합니다. 제품 캐시는 성공한 결과만 저장하고, 다운로드와 ccache는 실패한 컴파일에서도 재사용합니다. 새 캐시가 API에 존재하는 것을 확인한 뒤 동일 아키텍처의 이전 세대를 삭제합니다. 캐시는 GitHub의 저장 용량·만료 정책에 따라 사라질 수 있으며 자동으로 전체 빌드로 복구합니다.

실제 펌웨어는 디버그 패키지·실험 기능·테스트 커널을 기본 활성화하지 않습니다. `CONFIG_DEVEL=y`와 `CONFIG_TOOLCHAINOPTS=y`는 **호스트 GDB를 끄는 Kconfig 메뉴**에 필요하며, 설치되는 펌웨어를 debug 빌드로 만드는 옵션이 아닙니다. 타깃의 BPF/BTF 및 장애 진단에 필요한 커널 기본값은 유지합니다.

단계별 시간은 `logs/timings.tsv`, 컴파일러 캐시 통계는 `logs/ccache.log`, 캐시 복원 결과는 Actions Summary에 기록합니다. 같은 입력의 `clean` 빌드와 `force` 빌드를 비교하면 개선 효과를 측정할 수 있습니다. 릴리즈 게시에는 `GITHUB_TOKEN`의 `contents: write`, 캐시 정리에는 `actions: write`를 사용하며 추가 계정이나 토큰을 요구하지 않습니다.

## 로컬 검증

Ubuntu 24.04에서 다음 검사를 실행할 수 있습니다. CI는 추가로 실제 OpenWrt 소스와 NPU를 가져와 release profile이 Kconfig에서 그대로 유지되는지도 검사합니다.

```sh
python3 -B -m unittest discover -s tests -v
for script in tests/*.sh; do bash "$script"; done
shellcheck scripts/*.sh tests/*.sh
actionlint
```

Ubuntu 24.04의 경로에 공백이 없는 ext4 작업 디렉터리에서 `bash scripts/install-deps.sh`와 `bash scripts/build.sh all`로 로컬 빌드할 수 있습니다. 릴리즈에 포함된 `openwrt.config`와 `feeds.lock`를 `CONFIG_FILE`, `FEEDS_LOCK`로 지정하고 `OPENWRT_REF`, `NPU_REF`를 manifest의 커밋으로 고정하면 동일 소스 입력으로 재빌드할 수 있습니다.

참고 프로젝트:

- 빌드 자동화: [w1700k/builds](https://github.com/w1700k/builds) — fanboy.
- 증분 빌드 방식: [tete1030/openwrt-fastbuild-actions](https://github.com/tete1030/openwrt-fastbuild-actions) — Texot. 원본 스크립트를 복사하지 않고 빌드 상태 보존·타임스탬프 재사용 방식을 적용했습니다.
- NPU FDK: [hurryman2212/airoha-npu-fdk](https://github.com/hurryman2212/airoha-npu-fdk) — Jihong Min (`hurryman2212`).
- W1700K 지원: [OpenWRT-fanboy/OpenW1700k](https://github.com/OpenWRT-fanboy/OpenW1700k) — fanboy 및 [OpenWrt 프로젝트 기여자](https://github.com/openwrt/openwrt).
