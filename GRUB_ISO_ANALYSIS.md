# GRUB ISO 镜像引导分析

本文档详细分析 GRUB ISO 镜像的引导结构，包括 boot.S、core.img 的位置、对应的 GRUB 源代码、内存加载位置等。

## 概述

GRUB ISO 镜像使用 **HYBRID_BOOT 模式**，引导扇区结构与传统磁盘安装不同。`core.img` 不在 ISO 文件系统中，而是嵌入在 ISO 镜像的特定扇区位置。

## 分析工具

本项目提供了两个分析工具：

1. **`verify_grub_boot_sector.py`** - GRUB ISO 镜像验证脚本（统一版本），整合了所有 GRUB 分析功能
   - 分析引导扇区，查找 kernel_sector 字段和 core.img 位置
   - 反汇编分析 core.img，判断压缩状态和代码特征
   - 数据特征分析（NOP 字节、零字节、可打印字符串统计）
   - 熵值计算和压缩评分系统

### 使用方法

```bash
# 分析引导扇区
python3 verify_grub_boot_sector.py grub.iso

# 反汇编分析 core.img
python3 verify_grub_boot_sector.py grub.iso
```

## boot.S 分析

### 磁盘位置

- **扇区号**：0（ISO 镜像的第一个扇区，El Torito 引导扇区）
- **大小**：512 字节
- **格式**：HYBRID_BOOT 模式

### 内存位置

- **加载地址**：`0x7C00`（由 BIOS 通过 INT 13h 加载）
- **段:偏移格式**：`0x0000:0x7C00` 或 `0x07C0:0x0000`

### 关键字段位置

在 HYBRID_BOOT 模式下，`kernel_sector` 字段的位置与标准模式不同：

| 模式 | kernel_sector 偏移 | kernel_sector_high 偏移 | 用途 |
|------|-------------------|------------------------|------|
| **标准模式** | 0x5c (92 字节) | 0x60 (96 字节) | 传统磁盘安装 |
| **HYBRID_BOOT 模式** | 0x1b0 (432 字节) | 0x1b4 (436 字节) | ISO 镜像、混合引导 |

### 源代码位置

- **文件**：`grub/grub-core/boot/i386/pc/boot.S`
- **编译选项**：`-DHYBRID_BOOT=1`（参见 `grub/grub-core/Makefile.core.def:478`）

### 关键代码

```asm
// grub/grub-core/boot/i386/pc/boot.S

// HYBRID_BOOT 模式：kernel_sector 在偏移 0x1b0
#ifdef HYBRID_BOOT
    .org 0x1b0
LOCAL(kernel_sector):
    .long   1               // 初始值，安装时被覆盖
LOCAL(kernel_sector_high):
    .long   0
#endif

// 读取 GRUB Core 第一个扇区
LOCAL(lba_mode):
    movl    LOCAL(kernel_sector), %ebx      // 从偏移 0x1b0 读取
    movl    %ebx, 8(%si)                    // 写入 DAP
    movl    LOCAL(kernel_sector_high), %ebx
    movl    %ebx, 12(%si)
    movb    $0x42, %ah                      // INT 13h 功能 0x42：扩展读
    int     $0x13                           // 读取到 0x7000:0x0000

// 跳转到 GRUB Core
jmp     *(LOCAL(kernel_address))            // 跳转到 0x8000
```

### 实际分析结果

对于 `grub.iso`：
- **kernel_sector**：11916 (0x2e8c) - 位于偏移 0x1b0
- **kernel_sector_high**：0
- **引导模式**：HYBRID_BOOT 模式

## core.img 分析

### 磁盘位置

- **起始扇区**：11916 (0x2e8c) - 由 boot.S 的 `kernel_sector` 字段指定
- **大小**：56 扇区 = 28,672 字节 = 28.0 KB
- **块列表**：存储在第一个扇区的末尾（偏移 0x1F4，500 字节）

### 内存加载位置

#### 阶段 1：实模式加载（压缩状态）

- **diskboot.S**：`0x8000`（第一个扇区，512 字节）
- **startup_raw.S**：`0x8200`（第二个扇区开始，约 3.5KB）
- **C 代码（压缩）**：`0x9000+`（约 24KB，LZMA 压缩状态）
- **总大小**：28.0 KB（压缩状态）

#### 阶段 2：保护模式解压（默认使用 LZMA 压缩）

> **注意**：默认情况下 GRUB 使用 LZMA 压缩，这是标准配置。

- **解压目标**：`0x100000` (1MB)
- **解压函数**：`_LzmaDecodeA`（在 `startup_raw.S` 中调用）
- **解压后大小**：约 50-100 KB（取决于 GRUB 配置）

### 区域组成

| 区域 | 大小 | 压缩状态 | 熵值 | 说明 |
|------|------|---------|------|------|
| **diskboot.S** | 512 字节 | 未压缩 | 5.03 bits/byte | 块列表加载代码 |
| **startup_raw.S** | 约 3.5KB | 未压缩 | 6.90 bits/byte | 模式切换、解压代码 |
| **C 代码** | 约 24KB | LZMA 压缩 | 7.99 bits/byte | GRUB 核心功能 |

### 块列表结构

块列表存储在 diskboot.S 的末尾（偏移 0x1F4），每个条目 12 字节：

```
偏移 0x1F4 (500 字节) - 块列表起始位置
├─ 条目 0:
│  ├─ start (低 32 位): 11917 (0x2e8d)
│  ├─ start (高 32 位): 0
│  ├─ len: 56 扇区
│  └─ segment: 0x0820 (目标内存段)
└─ 条目 1: len=0 (结束标记)
```

### 源代码位置

- **diskboot.S**：`grub/grub-core/boot/i386/pc/diskboot.S`
- **startup_raw.S**：`grub/grub-core/boot/i386/pc/startup_raw.S`
- **块列表定义**：`grub/include/grub/offsets.h:151-156`

### 关键代码

```asm
// grub/grub-core/boot/i386/pc/diskboot.S
// 块列表结构
.org 0x200 - GRUB_BOOT_MACHINE_LIST_SIZE  // 偏移 0x1F4 (500 字节)
LOCAL(firstlist):
    .long 2, 0      // start: 低 32 位和高 32 位
    .word 0         // len: 扇区数
    .word 0x0820    // segment: 目标内存段

// 读取块列表
LOCAL(bootloop):
    cmpw    $0, 8(%di)      // 检查 len 字段
    je      LOCAL(bootit)   // len=0 表示结束
    movl    (%di), %ebx     // 读取 start 低 32 位
    movl    4(%di), %ecx    // 读取 start 高 32 位
    movw    8(%di), %ax     // 读取 len
    // ... 使用 INT 13h 读取扇区 ...
```

```asm
// grub/grub-core/boot/i386/pc/startup_raw.S
// 解压 GRUB Core（如果使用 LZMA 压缩）
#ifdef ENABLE_LZMA
    movl    $GRUB_MEMORY_MACHINE_DECOMPRESSION_ADDR, %edi  // 0x100000
    movl    $LOCAL(decompressor_end), %esi
    pushl   %edi
    movl    LOCAL (uncompressed_size), %ecx
    call    _LzmaDecodeA
    popl    %esi  // %esi 指向解压后的代码入口点
#endif
    jmp     *%esi  // 跳转到代码入口点
```

## 内存布局

### 实模式阶段（前 1MB）

```
内存地址范围              内容
─────────────────────────────────────────
0x0000 - 0x03FF      IVT（中断向量表）
0x0400 - 0x04FF      BDA（BIOS 数据区）
0x0500 - 0x7BFF      可用空间
0x7C00 - 0x7DFF      引导扇区（boot.S）← BIOS 加载
0x7E00 - 0x7FFF      引导扇区栈
0x8000 - 0x81FF      diskboot.S（512 字节）← boot.S 加载
0x8200 - 0x8FFF      startup_raw.S（约 3.5KB）← diskboot.S 加载
0x9000 - 0xCFFF      C 代码（压缩状态，约 24KB）← diskboot.S 加载
0xD000 - 0xFFFF      可用空间
0xF0000 - 0xFFFFF     BIOS ROM
```

### 保护模式阶段（1MB 以上）

```
内存地址范围              内容
─────────────────────────────────────────
0x100000 (1MB) - ...  解压后的 GRUB Core（如果使用 LZMA 压缩）
                      约 50-100 KB（取决于 GRUB 配置）
                      ← startup_raw.S 解压
```

## 加载流程

### 阶段 1：BIOS 加载引导扇区

1. **BIOS 调用 INT 19h**
2. **读取扇区 0**（boot.S）到 `0x7C00`
3. **跳转到 `0x0000:0x7C00`**，DL 寄存器包含驱动器号

### 阶段 2：boot.S 加载 GRUB Core 第一个扇区

1. **读取 kernel_sector 字段**（偏移 0x1b0，值 = 11916）
2. **使用 INT 13h 扩展读**（AH=0x42）读取扇区 11916
3. **先读到临时缓冲区** `0x7000:0x0000`
4. **复制到最终地址** `0x0000:0x8000`
5. **跳转到 `0x8000`**（diskboot.S 入口点）

### 阶段 3：diskboot.S 加载完整的 GRUB Core

1. **读取块列表**（从 `0x8000` 的末尾，偏移 0x1F4）
2. **循环读取每个块列表条目**：
   - 使用 INT 13h 读取指定扇区到临时缓冲区 `0x7000`
   - 复制到目标地址（由 segment 字段指定）
3. **所有扇区加载完成后**，跳转到 `0x8200`（startup_raw.S 入口点）

### 阶段 4：startup_raw.S 解压和执行

1. **切换到保护模式**（`calll real_to_prot`）
2. **启用 A20 地址线**（`call grub_gate_a20`）
3. **处理 Reed-Solomon 错误纠正**（如果启用）
4. **解压 GRUB Core**（如果使用 LZMA 压缩）：
   - 解压目标：`0x100000` (1MB)
   - 解压函数：`_LzmaDecodeA`
5. **跳转到解压后的代码入口点**（`jmp *%esi`）

## 压缩状态分析

### 检测方法

1. **熵值分析**：
   - 压缩数据：熵值 > 7.0 bits/byte
   - 未压缩代码：熵值 < 6.5 bits/byte

2. **指令模式分析**：
   - 未压缩代码：包含大量 x86 指令（MOV, PUSH, POP, CALL, INT 等）
   - 压缩数据：指令比例较低

3. **字符串检测**：
   - 未压缩代码：包含可打印字符串（如 "loading", "Error"）
   - 压缩数据：字符串较少

### 实际分析结果

对于 `grub.iso` 的 core.img：

| 区域 | 大小 | 熵值 | 指令比例 | 压缩状态 |
|------|------|------|---------|---------|
| diskboot.S | 512 字节 | 5.03 | 11.7% | 未压缩 ✅ |
| startup_raw.S | 3.5KB | 6.90 | 11.9% | 未压缩 ✅ |
| C 代码 | 24KB | 7.99 | 6.1% | LZMA 压缩 ✅ |

**结论**：core.img 是混合格式
- 前 4KB：未压缩的汇编代码
- 后 24KB：LZMA 压缩的 C 代码

## 内存空间分析

### 1MB 空间是否够用？

**压缩状态（加载时）**：
- core.img 大小：28.0 KB
- 1MB 空间可用：640 KB
- **结论**：✅ 可以加载到 1MB 空间内（0x8000+）
- 剩余空间：612.0 KB

**解压后（执行时）**：
- 解压后大小：约 50-100 KB（取决于 GRUB 配置）
- 解压位置：`0x100000` (1MB) 以上
- **结论**：✅ 解压到 1MB 以上，有足够空间

### 为什么需要解压？

1. **空间限制**：虽然压缩状态只有 28KB，但解压后可能达到 50-100KB
2. **内存布局**：前 1MB 空间有限（约 640KB 可用），需要为其他组件留出空间
3. **设计选择**：解压到 1MB 以上，避免前 1MB 空间不足

## 关键地址总结

| 组件 | 磁盘位置 | 内存位置（实模式） | 内存位置（保护模式） |
|------|---------|------------------|-------------------|
| **boot.S** | 扇区 0 | `0x7C00` | - |
| **diskboot.S** | 扇区 11916 | `0x8000` | - |
| **startup_raw.S** | 扇区 11917+ | `0x8200` | - |
| **C 代码（压缩）** | 扇区 11917+ | `0x9000+` | - |
| **C 代码（解压后）** | - | - | `0x100000+` |

## 与标准磁盘安装的对比

| 特性 | 标准磁盘安装 | ISO 镜像（HYBRID_BOOT） |
|------|------------|----------------------|
| **kernel_sector 位置** | 偏移 0x5c | 偏移 0x1b0 |
| **core.img 位置** | MBR 之后或分区间隙 | ISO 镜像特定扇区（不在文件系统） |
| **引导扇区** | MBR（扇区 0） | El Torito 引导扇区（扇区 0） |
| **块列表** | 在 core.img 第一个扇区末尾 | 在 core.img 第一个扇区末尾 |

## 相关文档

- [BOOT_FLOW.md](BOOT_FLOW.md) - 完整的启动流程详解
- [GRUB_ISO_BOOT_FILES.md](GRUB_ISO_BOOT_FILES.md) - GRUB ISO 镜像中哪些文件在 boot 阶段被加载
- [BIOS_MEMORY_LAYOUT.md](BIOS_MEMORY_LAYOUT.md) - BIOS 内存布局详解

## 分析工具

- **`verify_grub_boot_sector.py`** - GRUB ISO 镜像验证脚本（统一版本），整合了所有 GRUB 分析功能
  - 分析引导扇区，查找 kernel_sector 和 core.img 位置
  - 反汇编分析 core.img，判断压缩状态
  - 数据特征分析和压缩评分系统
