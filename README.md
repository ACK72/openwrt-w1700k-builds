# W1700K OpenWrt

Gemtek W1700K HW2.1 `w1700k-oc` 커스텀 펌웨어입니다.
OpenWrt, Airoha NPU 펌웨어와 기본 패키지가 포함된 이미지가 빌드됩니다.

**[정식 펌웨어 다운로드](../../releases/latest)** · [정식·RC 펌웨어](../../releases)

정식 `w1700k-oc`와 시험용 `w1700k-oc-rc` 펌웨어를 각각 최대 1개 제공합니다.
두 파일 모두 W1700K **UBI2 파티션 구성**에 사용하는 sysupgrade용 ITB입니다.
RC는 파일명에 `-rc-`가 표시되며 GitHub에서 Pre-release로 구분됩니다.
정식 버전은 빌드가 성공한 RC와 동일한 이미지이며 파일명만 다릅니다.

펌웨어의 **Check for GitHub firmware**에서 정식 또는 RC 이미지를 선택할 수 있습니다.
RC를 선택하면 시험용 이미지라는 경고가 표시됩니다. 설치 전에 설정을 백업하고,
이미지 검증이 끝난 뒤 설치 여부와 설정 유지 여부를 확인하세요.
이 이미지는 제조사 순정 펌웨어에서 직접 설치하는 용도가 아닙니다.

## 기반 프로젝트

[OpenWrt](https://github.com/openwrt/openwrt), [OpenW1700k](https://github.com/OpenWRT-fanboy/OpenW1700k), [w1700k/builds](https://github.com/w1700k/builds), [BuildWrt](https://github.com/tete1030/openwrt-fastbuild-actions)의 작업을 기반으로 합니다.
라이선스는 [LICENSE](LICENSE)를 참고하세요.

## NPU 펌웨어

OpenWrt의 `linux-firmware` 패키지가 제공하는 공식 Airoha MT7996 NPU 바이너리를 사용합니다.
FDK 저장소를 내려받거나 NPU 코드를 다시 컴파일하지 않습니다. 프로그램(`rv32`)과 데이터(`data`)는
같은 공식 배포본에서 가져오며, 패키지 정의·배포본 SHA256·이미지 루트 파일시스템의 두 바이너리를 검증합니다.
FDK 시절의 패키지 빌드 캐시는 재사용하지 않으며, 호환되는 컴파일러 캐시는 유지합니다.

검증: `python3 -m unittest discover -s tests -v`
