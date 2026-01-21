# vmlinuz 文件详细结构分析

> **相关文档**：本文档是 [BOOT_FLOW.md](BOOT_FLOW.md) 的补充文档，详细说明了 Linux 内核镜像文件（vmlinuz/bzImage）的二进制格式和结构。

## 文件格式概述

`vmlinuz`（或 `bzImage`）是 Linux 内核的压缩镜像文件，采用特殊的二进制格式，包含引导所需的所有信息。文件结构如下：

```
vmlinuz 文件结构：
┌─────────────────────────────────────────┐
│ 偏移 0x0000 - 0x01FF (512 字节)        │
│ 内核头部（boot_params 结构）             │
│ ├─ boot_flag: 0xAA55（引导扇区签名）    │
│ ├─ header: "HdrS" (0x53726448)         │
│ ├─ setup_sects: Setup 代码扇区数        │
│ ├─ code32_start: 32 位代码入口点偏移    │
│ ├─ pref_address: 首选加载地址          │
│ └─ 其他启动参数...                      │
├─────────────────────────────────────────┤
│ 偏移 0x0200 - (setup_sects * 512)      │
│ Setup 代码（实模式代码）                 │
│ ├─ 源代码：linux/arch/x86/boot/header.S │
│ ├─ 验证内核签名                         │
│ ├─ 初始化基本环境                       │
│ ├─ 切换到保护模式/长模式                │
│ └─ 跳转到压缩内核解压代码               │
├─────────────────────────────────────────┤
│ Setup 代码之后                          │
│ 压缩的内核代码（gzip 压缩的 vmlinux）   │
│ ├─ 格式：gzip 压缩                      │
│ ├─ 内容：完整的 vmlinux（未压缩的内核） │
│ ├─ 解压目标：0x100000 (1MB) 或更高      │
│ └─ 解压后：startup_32 → startup_64     │
└─────────────────────────────────────────┘
```

## 1. 内核头部（boot_params 结构）

**源代码位置：** `linux/arch/x86/include/uapi/asm/bootparam.h`

内核文件的前 512 字节包含 `boot_params` 结构（也称为 `zero_page`），这是引导加载程序和内核之间的通信接口：

```c
// linux/arch/x86/include/uapi/asm/bootparam.h
struct boot_params {
    // 偏移 0x0000: 引导扇区签名
    __u8  boot_flag;        // 0xAA55（小端序：0x55 0xAA）
    
    // 偏移 0x0001-0x0003: 保留
    __u8  pad1[3];
    
    // 偏移 0x0004-0x0007: 内核头部签名
    __u32 header;           // "HdrS" (0x53726448)
    
    // 偏移 0x0008-0x000B: 内核版本
    __u16 version;          // 内核头部版本
    __u16 compat_version;   // 兼容版本
    
    // 偏移 0x000C-0x000D: 实模式加载地址
    __u16 loader_type;     // 引导加载程序类型（GRUB = 0x72）
    __u16 loadflags;       // 加载标志
    
    // 偏移 0x000E-0x000F: 实模式代码大小
    __u16 setup_sects;     // Setup 代码扇区数（通常 4-64）
    
    // 偏移 0x0010-0x0013: 根设备号
    __u16 root_dev;        // 根设备号（已废弃）
    __u16 boot_flag_old;   // 旧引导标志（已废弃）
    
    // 偏移 0x0014-0x0017: 内核命令行
    __u32 cmd_line_ptr;    // 内核命令行参数地址（实模式地址）
    
    // 偏移 0x0018-0x001B: RAM 磁盘信息
    __u32 ramdisk_image;   // initramfs 地址
    __u32 ramdisk_size;    // initramfs 大小
    
    // 偏移 0x001C-0x001F: 硬件子架构
    __u32 hardware_subarch; // 硬件子架构（x86_64 = 0）
    
    // 偏移 0x0020-0x0023: 硬件子架构数据
    __u64 hardware_subarch_data;
    
    // 偏移 0x0028-0x002B: 32 位代码入口点
    __u32 code32_start;     // 32 位保护模式代码入口点（相对于 0x100000 的偏移）
    
    // 偏移 0x002C-0x002F: 64 位代码入口点
    __u64 code64_start;     // 64 位长模式代码入口点（相对于 0x100000 的偏移）
    
    // 偏移 0x0030-0x0037: 首选加载地址
    __u64 pref_address;     // 内核首选加载地址（通常 0x100000）
    
    // 偏移 0x0038-0x003B: 初始化大小
    __u32 init_size;        // 初始化代码大小（包括 setup + 压缩内核）
    
    // 偏移 0x003C-0x003F: 握手
    __u32 handover_offset;  // 握手偏移（用于 EFI 启动）
    
    // ... 更多字段（总共 4096 字节，但前 512 字节最重要）
};
```

### 关键字段说明

- **`boot_flag`**（偏移 0x0000）：必须是 `0xAA55`，用于验证这是有效的内核镜像
- **`header`**（偏移 0x0004）：必须是 `"HdrS"` (0x53726448)，用于验证内核头部格式
- **`setup_sects`**（偏移 0x000E）：Setup 代码的扇区数（512 字节/扇区），通常为 4-64
- **`code32_start`**（偏移 0x0028）：32 位保护模式代码入口点，相对于 `0x100000` 的偏移
- **`pref_address`**（偏移 0x0030）：内核首选加载地址，通常为 `0x100000` (1MB)
- **`init_size`**（偏移 0x0038）：初始化代码总大小（setup + 压缩内核）

## 2. Setup 代码部分

**源代码位置：** `linux/arch/x86/boot/header.S`

Setup 代码紧跟在 512 字节头部之后，大小由 `setup_sects` 字段指定（通常 4-64 个扇区，即 2-32 KB）：

- **功能**：
  - 验证内核签名（`boot_flag = 0xAA55`）
  - 初始化基本环境（段寄存器、栈等）
  - 切换到保护模式或长模式
  - 解压压缩的内核代码
  - 跳转到解压后的内核入口点（`startup_32` 或 `startup_64`）

- **内存位置**：加载到 `0x100000` (1MB) 或内核指定的地址

## 3. 压缩的内核代码部分

**源代码位置：** `linux/arch/x86/boot/compressed/head_64.S`

压缩的内核代码位于 Setup 代码之后，是 gzip 压缩的完整 vmlinux：

- **格式**：gzip 压缩
- **内容**：完整的 vmlinux（未压缩的内核二进制文件）
- **解压目标**：`0x100000` (1MB) 或更高地址
- **解压后**：包含 `startup_32`（32 位保护模式入口）和 `startup_64`（64 位长模式入口）

## 验证 vmlinuz 文件的方法

可以使用以下命令验证 vmlinuz 文件结构：

```bash
# 1. 检查文件大小
ls -lh /boot/vmlinuz-*

# 2. 查看前 512 字节（内核头部）
hexdump -C /boot/vmlinuz-* | head -20

# 3. 验证引导扇区签名（偏移 0x1FE-0x1FF 应该是 55 AA）
dd if=/boot/vmlinuz-* bs=1 skip=510 count=2 | od -An -tx1

# 4. 验证头部签名（偏移 0x0004-0x0007 应该是 "HdrS"）
dd if=/boot/vmlinuz-* bs=1 skip=4 count=4 | od -An -tx1

# 5. 查看 setup_sects 字段（偏移 0x000E-0x000F）
dd if=/boot/vmlinuz-* bs=1 skip=14 count=2 | od -An -tu2
```
