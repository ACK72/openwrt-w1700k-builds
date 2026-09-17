# w1700k/builds와의 빌드 비교

비교 기준은 [w1700k/builds@9449e4c의 ubi2-oc 설정](https://github.com/w1700k/builds/blob/9449e4ca242ab30278df20940d6654ddc1c102e8/user/ubi2-oc/config.diff)입니다. `ubi2`도 같은 패키지 설정을 사용하며, `SNAPSHOT`은 별도 구성입니다.

## 패키지와 이미지

기준 설정의 명시적 패키지 선택 **72개(이미지 포함 71개, 별도 빌드 1개)**를 동일하게 적용했습니다. MT7996 NPU 패키지는 양쪽 모두 W1700K의 기본 패키지이며, 이 저장소에서는 포함 여부를 추가로 명시하고 검사합니다. 패키지의 버전과 자동 의존성은 각 OpenWrt 소스 및 feed 리비전에 따라 달라질 수 있습니다.

이전 이미지에서 빠졌던 파일 관리자(`luci-app-filemanager`), 웹 터미널(`luci-app-ttyd`, `ttyd`), 속도 측정(`luci-app-netspeedtest`, `librespeed-go`), 시스템 정보(`fastfetch`), 업그레이드 도구(`luci-app-attendedsysupgrade`, `owut`), 릴레이(`relayd`, `luci-proto-relay`), Footstrap 테마와 필요한 라이브러리를 포함합니다. APK 관리자는 기준과 같은 `apk-openssl`을 사용합니다.

`=y` 패키지는 OpenWrt가 루트 파일시스템에 설치하고 커널과 함께 FIT/ITB에 넣습니다. APK 압축 파일을 ITB 뒤에 이어 붙이지 않습니다. 빌드 후 실제 루트 파일시스템의 패키지 목록을 검사합니다.

기준과 같은 `CONFIG_ALL_KMODS=y`도 적용합니다. 이는 사용 가능한 커널 모듈을 별도 패키지로 빌드하는 옵션이며, 모든 모듈을 이미지에 설치한다는 뜻은 아닙니다. 기준의 `airoha-en7581-npu-firmware=m` 역시 별도 빌드 대상이며, W1700K 이미지에는 MT7996용 펌웨어를 넣습니다. 별도 APK는 릴리즈에 올리지 않습니다. 전체 커널 모듈 빌드는 필요한 모듈만 빌드하던 이전 구성보다 첫 빌드의 시간과 저장 공간을 더 사용합니다.

## 남아 있는 차이

| 항목 | w1700k/builds | 이 저장소 |
| --- | --- | --- |
| OpenWrt 소스 | OpenWRT-fanboy/OpenW1700k의 `ubi2-oc` | ACK72/openwrt의 `ubi2-oc`; 소스 브랜치는 유지 |
| NPU | 소스 트리의 MT7996 펌웨어 | ACK72/airoha-npu-fdk에서 RV32·데이터 펌웨어를 함께 빌드 |
| 패키지 서명 | 개별 패키지 서명 비활성화 | 패키지 및 인덱스 서명 유지 |
| 커스텀 파일 | 업그레이드 화면·단일 wiphy 패치·진단 스크립트 추가 | 별도 화면 패치 및 외부 업데이트 다운로드 스크립트는 추가하지 않음 |
| 커널 패키지 저장소 | 공개 snapshot distfeeds와 vermagic 파일을 이미지에 복사 | 외부 vermagic 파일을 주입하지 않고 현재 빌드의 커널 ABI 사용 |
| 실행 환경 | ARM64 Docker 컨테이너, GHCR와 Actions 캐시 | Ubuntu 24.04 직접 빌드, x86_64 기본·ARM64 선택 가능 |
| 재사용 | 컨테이너·staging·ccache 재사용 | 소스·설정·호스트 호환성 검사 후 도구 체인·커널·패키지·ccache 재사용 |
| Go 부트스트랩 | 컨테이너의 `/usr/lib/go/` 사용 | OpenWrt의 자체 부트스트랩 사용 |
| 릴리즈 | 종류별 기존 릴리즈를 지우고 새 ITB 공개 | 검증된 ITB 공개 후 최신 3개 유지; 다음 빌드 시작 시 이전 빌드의 draft 삭제 |
| 파일명 | 원래 `*-sysupgrade.itb` | `openwrt-airoha-an7581-gemtek_w1700k-ubi-squashfs-sysupgrade-r숫자.itb` |

릴리즈 본문은 버전 제목과 변경 기록만 표시합니다. 빌드 설정·로그 등 진단 자료는 Actions artifact에 보관하고, 릴리즈에는 ITB 하나만 업로드합니다. GitHub가 자동으로 표시하는 Source code 압축 파일은 업로드한 펌웨어 자산이 아닙니다.

자동 빌드·패키지 포함·이미지 무결성 검사는 실제 W1700K에서의 부팅 및 무선 동작 시험을 대신하지 않습니다.
