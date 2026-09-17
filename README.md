# W1700K OpenWrt

Gemtek W1700K용 `ubi2-oc` 커스텀 펌웨어입니다. OpenWrt와 Airoha NPU 펌웨어를 함께 제공합니다.

**[최신 펌웨어 다운로드](https://github.com/ACK72/openwrt-w1700k-builds/releases/latest)** · [이전 릴리즈](https://github.com/ACK72/openwrt-w1700k-builds/releases)

## 지원 기기

**UBI2 파티션과 호환 chainloader를 이미 사용하는 W1700K**의 업그레이드용입니다. 순정 펌웨어나 다른 파티션 구성에서는 바로 설치할 수 없습니다.

`ubi2-oc`는 오버클럭이 적용된 비공식 펌웨어입니다. 이미지 무결성과 기기 정보를 자동 검증하지만, 각 릴리즈의 실제 기기 동작까지 검증한 것은 아닙니다.

## 업데이트

1. LuCI의 **시스템 → 백업 / 펌웨어 업데이트**에서 현재 설정을 백업합니다.
2. 릴리즈의 **Assets**에서 `*-sysupgrade.itb`와 `SHA256SUMS`를 다운로드합니다. GitHub의 `Source code` 압축 파일은 설치 이미지가 아닙니다.
3. 다운로드한 이미지의 SHA-256을 `SHA256SUMS`에 적힌 값과 비교합니다.
   - Linux: `sha256sum <다운로드한 이미지.itb>`
   - Windows PowerShell: `Get-FileHash <다운로드한 이미지.itb> -Algorithm SHA256`
4. LuCI에서 이미지를 업로드하고 호환성 검사를 통과한 뒤 업데이트합니다. 호환성 오류가 나오면 강제 설치하지 마세요.
5. 재부팅이 끝날 때까지 전원을 유지합니다.

최근 **3개 릴리즈**를 보관합니다. 복구에 사용할 이전 이미지와 설정 백업은 PC에도 저장해 두세요.

## 추가 파일

| 파일 | 용도 |
| --- | --- |
| `packages.tar.zst` | 해당 펌웨어와 함께 빌드한 추가 APK 패키지 |
| `public-key.pem` | APK 패키지 서명 검증용 공개키 |
| `build-info.tar.gz` | 문제 신고·빌드 확인에 사용하는 소스 커밋, 설정, 이미지 정보 |

추가 패키지는 **같은 릴리즈의 이미지**와 함께 사용하세요. 다른 릴리즈나 공개 snapshot 저장소의 커널 모듈(`kmod`)은 호환되지 않을 수 있습니다. 일반적인 펌웨어 업데이트에는 이 추가 파일들이 필요하지 않습니다.

문제가 생기면 [Issues](https://github.com/ACK72/openwrt-w1700k-builds/issues)에 릴리즈 이름, 기기 버전, 증상과 재현 방법을 남겨 주세요. 로그의 비밀번호·개인정보는 제거해 주세요.

## 기반 프로젝트

[ACK72/openwrt · ubi2-oc](https://github.com/ACK72/openwrt/tree/ubi2-oc), [Airoha NPU FDK](https://github.com/hurryman2212/airoha-npu-fdk), [OpenW1700k](https://github.com/OpenWRT-fanboy/OpenW1700k), [w1700k/builds](https://github.com/w1700k/builds), [BuildWrt](https://github.com/tete1030/openwrt-fastbuild-actions)의 작업을 기반으로 합니다. 라이선스는 [LICENSE](LICENSE)를 참고하세요.
