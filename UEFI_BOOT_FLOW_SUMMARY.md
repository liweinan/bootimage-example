# UEFI 启动流程快速参考

> **完整文档**：[UEFI_VS_BIOS_BOOT.md](UEFI_VS_BIOS_BOOT.md)

## 一图看懂：UEFI vs BIOS

```
┌─────────────────────────────────────────────────────────────────┐
│                        BIOS 启动路径                             │
├─────────────────────────────────────────────────────────────────┤
│ GRUB (1MB)                                                      │
│    ↓                                                            │
│ arch/x86/boot/compressed/head_64.S::startup_32 (实模式→保护模式) │
│    ↓                                                            │
│ arch/x86/boot/compressed/head_64.S::startup_64 (切换长模式)     │
│    ↓                                                            │
│ rep movsq (重定位：1MB → 38MB)  ← 需要这一步！                   │
│    ↓                                                            │
│ arch/x86/boot/compressed/misc.c::extract_kernel() (解压到16MB) │
│    ↓                                                            │
│ arch/x86/kernel/head_64.S::startup_64 (主内核)                 │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                        UEFI 启动路径                             │
├─────────────────────────────────────────────────────────────────┤
│ UEFI 固件 (已在长模式)                                           │
│    ↓                                                            │
│ drivers/firmware/efi/libstub/x86-stub.c::efi_pe_entry()        │
│    ↓                                                            │
│ drivers/firmware/efi/libstub/x86-stub.c::efi_stub_entry()      │
│    ↓                                                            │
│ drivers/firmware/efi/libstub/x86-stub.c::efi_decompress_kernel()│
│   (EFI 分配内存 → 直接解压)  ← 省略重定位！                       │
│    ↓                                                            │
│ drivers/firmware/efi/libstub/x86-stub.c::enter_kernel()        │
│    ↓ (jmp 直接跳转)                                             │
│ arch/x86/kernel/head_64.S::startup_64 (主内核)                 │
└─────────────────────────────────────────────────────────────────┘
```

## 关键区别

| 特性 | BIOS 路径 | UEFI 路径 |
|------|----------|-----------|
| **模式切换** | 需要（实模式→保护模式→长模式） | 不需要（已在长模式） |
| **重定位** | 需要（rep movsq） | 不需要（EFI 分配） |
| **startup_32/64** | 必须经过 | 完全跳过 |
| **内存管理** | 手动计算 %rbx | EFI Boot Services |
| **代码路径** | 约 1000 行汇编 | 约 200 行 C 代码 |

## 为什么 UEFI 更简单？

1. ✅ 固件已在长模式，无需模式切换
2. ✅ EFI 分配内存，无需手动重定位
3. ✅ 标准 PE 格式，无大小限制
4. ✅ 内置文件系统，无需解析扇区
5. ✅ 统一接口，无需 BIOS INT 中断

## 源代码位置

**UEFI 路径**：
- 入口点：`drivers/firmware/efi/libstub/x86-stub.c:943` (efi_pe_entry)
- 主函数：`drivers/firmware/efi/libstub/x86-stub.c:808` (efi_stub_entry)
- 解压：`drivers/firmware/efi/libstub/x86-stub.c:733` (efi_decompress_kernel)
- 跳转：`drivers/firmware/efi/libstub/x86-stub.c:794` (enter_kernel)

**BIOS 路径**：
- 入口点：`arch/x86/boot/compressed/head_64.S:82` (startup_32)
- 长模式：`arch/x86/boot/compressed/head_64.S:278` (startup_64)
- 重定位：`arch/x86/boot/compressed/head_64.S:420` (rep movsq)
- 解压：`arch/x86/boot/compressed/misc.c:405` (extract_kernel)

**共同部分**：
- 解压函数：`arch/x86/boot/compressed/misc.c:342` (decompress_kernel)
- 主内核入口：`arch/x86/kernel/head_64.S:38` (startup_64)

## 相关文档

- [UEFI_VS_BIOS_BOOT.md](UEFI_VS_BIOS_BOOT.md) - UEFI 启动详细流程和代码分析
- [LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md) - BIOS/GRUB 启动详细流程
- [WHY_RELOCATE_COMPRESSED_KERNEL.md](WHY_RELOCATE_COMPRESSED_KERNEL.md) - 为什么 BIOS 需要重定位
