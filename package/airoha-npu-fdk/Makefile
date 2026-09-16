# SPDX-License-Identifier: GPL-2.0-only
include $(TOPDIR)/rules.mk

PKG_NAME:=airoha-npu-fdk
PKG_VERSION:=@NPU_VERSION@
PKG_RELEASE:=1
PKG_LICENSE:=MIT
PKG_LICENSE_FILES:=LICENSE
PKGARCH:=all

include $(INCLUDE_DIR)/package.mk

# These are freestanding RV32/data images, not target userspace ELF files.
RSTRIP:=:
STRIP:=:

define Package/airoha-en7581-mt7996-npu-firmware
  SECTION:=firmware
  CATEGORY:=Firmware
  TITLE:=Airoha AN7581/MT7996 NPU firmware built from ACK72 FDK
  URL:=https://github.com/ACK72/airoha-npu-fdk
  DEPENDS:=@TARGET_airoha_an7581
endef

define Build/Prepare
	$(INSTALL_DIR) $(PKG_BUILD_DIR)
	$(CP) ./files/* $(PKG_BUILD_DIR)/
endef

define Build/Configure
endef

define Build/Compile
endef

define Package/airoha-en7581-mt7996-npu-firmware/install
	$(INSTALL_DIR) $(1)/lib/firmware/airoha
	$(INSTALL_DATA) $(PKG_BUILD_DIR)/en7581_MT7996_npu_rv32.bin $(1)/lib/firmware/airoha/
	$(INSTALL_DATA) $(PKG_BUILD_DIR)/en7581_MT7996_npu_data.bin $(1)/lib/firmware/airoha/
	$(INSTALL_DIR) $(1)/usr/share/licenses/airoha-npu-fdk
	$(INSTALL_DATA) $(PKG_BUILD_DIR)/LICENSE $(1)/usr/share/licenses/airoha-npu-fdk/
endef

$(eval $(call BuildPackage,airoha-en7581-mt7996-npu-firmware))
