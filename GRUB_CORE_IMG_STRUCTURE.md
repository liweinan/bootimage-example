# GRUB core.img 结构与构建详解

本文档详细说明 GRUB `core.img` 的内部结构、构建过程、块列表机制以及相关源代码分析。

> **相关文档**：关于 GRUB 启动流程，请参见 [BOOT_FLOW.md](BOOT_FLOW.md)。

## core.img 概述

`core.img` 不是单个源文件，而是由 `grub-mkimage` 工具组合多个源文件生成的二进制镜像。

## 1. 生成工具

```c
// grub/util/grub-mkimage.c
// 这是生成 core.img 的主要工具
// 功能：
// - 解析命令行参数（指定模块、配置文件等）
// - 收集启动汇编代码（diskboot.S, startup_raw.S）
// - 收集 C 代码模块（kern/*.c, modules/*.c）
// - 生成块列表（blocklist）
// - 压缩（如果启用 LZMA）
// - 输出 core.img 文件
```

## 2. core.img 的组成结构

```
core.img 的组成：
├─ 第一个扇区（512 字节）：
│  └─ grub/grub-core/boot/i386/pc/diskboot.S
│     └─ 源代码位置：grub/grub-core/boot/i386/pc/diskboot.S
│
├─ 第二个扇区开始：
│  ├─ grub/grub-core/boot/i386/pc/startup_raw.S
│  │  └─ 源代码位置：grub/grub-core/boot/i386/pc/startup_raw.S
│  │  └─ 入口点：LOCAL(codestart)，位于 0x8200
│  │
│  └─ C 代码部分（LZMA 压缩）：
│     ├─ grub/grub-core/kern/main.c（grub_main()）
│     ├─ grub/grub-core/kern/disk.c（磁盘驱动）
│     ├─ grub/grub-core/kern/file.c（文件操作）
│     ├─ grub/grub-core/kern/fs.c（文件系统框架）
│     └─ 其他核心模块...
```

## 3. 生成过程（grub-mkimage）

```c
// grub/util/grub-mkimage.c 的主要流程：
// 
// 1. 解析命令行参数
//    - 指定输出文件：--output /boot/grub/i386-pc/core.img
//    - 指定模块：--modules "ext2 part_msdos"
//    - 指定压缩：--compress=xz（或 lzma）
//
// 2. 收集启动代码
//    - 加载 diskboot.S（第一个扇区）
//    - 加载 startup_raw.S（第二个扇区开始）
//
// 3. 收集 C 代码模块
//    - 链接 kern/*.c 的目标文件
//    - 链接指定的模块（modules/*.c）
//
// 4. 生成块列表
//    - 调用 save_blocklists()（grub/util/setup.c）
//    - 记录每个数据块在磁盘上的位置
//    - 写入 diskboot.S 的末尾（偏移 0x1F4）
//
// 5. 压缩（如果启用）
//    - 使用 LZMA 压缩 C 代码部分
//    - 保留 diskboot.S 和 startup_raw.S 未压缩
//
// 6. 输出 core.img
//    - 写入 /boot/grub/i386-pc/core.img
```

## 4. 安装过程（grub-install）

```c
// grub/util/grub-install.c 的主要流程：
//
// 1. 读取 core.img
//    - 从 /boot/grub/i386-pc/core.img 读取
//
// 2. 确定安装位置
//    - 传统磁盘：MBR 之后（通常扇区 2048）
//    - ISO 镜像：El Torito 引导扇区（例如扇区 11916）
//
// 3. 写入 core.img
//    - 将 core.img 写入磁盘的指定扇区
//    - 记录扇区号到 boot.S 的 kernel_sector 字段
//
// 4. 写入 boot.S
//    - 将 boot.S 写入 MBR（扇区 0）或 El Torito 引导扇区
//    - 更新 kernel_sector 字段为 core.img 的实际位置
```

## 5. 源代码中的关键文件路径

| 文件 | 源代码位置 | 说明 |
|------|-----------|------|
| **生成工具** | `grub/util/grub-mkimage.c` | 生成 core.img 的工具 |
| **安装工具** | `grub/util/grub-install.c` | 安装 core.img 到磁盘的工具 |
| **块列表生成** | `grub/util/setup.c:save_blocklists()` | 生成块列表的函数 |
| **diskboot.S** | `grub/grub-core/boot/i386/pc/diskboot.S` | core.img 第一个扇区 |
| **startup_raw.S** | `grub/grub-core/boot/i386/pc/startup_raw.S` | core.img 第二个扇区开始 |
| **C 代码** | `grub/grub-core/kern/*.c` | core.img 的 C 代码部分 |

## 6. 输出文件位置

- **生成后**：`/boot/grub/i386-pc/core.img`（在构建系统中）
- **安装后**：
  - 传统磁盘：写入磁盘的 MBR 之后（例如扇区 2048）
  - ISO 镜像：嵌入到 El Torito 引导扇区中（不在文件系统里）

---

## 块列表机制详解

### 为什么需要块列表？

在深入代码实现之前，先理解为什么需要块列表机制：

- **GRUB Core 大小限制**：GRUB Core 可能很大（几 KB 到几十 KB），跨越多个扇区，无法一次性加载
- **磁盘碎片问题**：GRUB Core 可能分散在磁盘的不同位置（由于文件系统碎片），不是连续的扇区
- **分段加载需求**：块列表记录了每个片段的位置，允许分段加载，即使数据不连续也能正确加载
- **引导扇区限制**：引导扇区只有 512 字节，无法包含完整的加载逻辑，所以将加载逻辑放在第一个 GRUB Core 扇区（diskboot.S）中

### 块列表结构定义

```c
// grub/include/grub/offsets.h:151-156
struct grub_pc_bios_boot_blocklist
{
    grub_uint64_t start;    // 起始扇区号（LBA，8 字节）
    grub_uint16_t len;      // 要读取的扇区数（2 字节）
    grub_uint16_t segment;  // 目标内存段地址（2 字节）
} GRUB_PACKED;
```

### GRUB_BOOT_MACHINE_LIST_SIZE 的计算

`GRUB_BOOT_MACHINE_LIST_SIZE` 宏定义为块列表结构体的大小：

1. **结构体字段大小**：
   - `grub_uint64_t start`：64 位无符号整数 = **8 字节**
   - `grub_uint16_t len`：16 位无符号整数 = **2 字节**
   - `grub_uint16_t segment`：16 位无符号整数 = **2 字节**

2. **`GRUB_PACKED` 的作用**：
   - `GRUB_PACKED` 是一个编译器属性（`__attribute__((packed))`），确保结构体字段紧密排列，**无填充字节**

3. **计算结果**：
   ```
   GRUB_BOOT_MACHINE_LIST_SIZE = 8 + 2 + 2 = 12 字节
   ```

### 块列表在 diskboot.S 中的汇编定义

```asm
// grub/grub-core/boot/i386/pc/diskboot.S:409-423
.org 0x200 - GRUB_BOOT_MACHINE_LIST_SIZE  // 定位到扇区末尾（512 - 12 = 500 字节处）
LOCAL(firstlist):  // 块列表起始位置
    // 第一个块列表条目的默认值（由 grub-mkimage 在安装时填充）
blocklist_default_start:
    .long 2, 0      // start: 低 32 位和高 32 位扇区号（8 字节）
blocklist_default_len:
    .word 0         // len: 要读取的扇区数（2 字节）
blocklist_default_seg:
    .word (GRUB_BOOT_MACHINE_KERNEL_SEG + 0x20)  // segment: 目标内存段（2 字节）
    // 后续块列表条目紧接其后，每个条目 12 字节
    // 最后一个条目 len = 0 表示结束
```

### diskboot.S 的实际大小和内存布局

**编译后的二进制文件大小**：正好 512 字节（一个扇区）

```
diskboot.S 编译后的二进制文件（正好 512 字节）：
├─ 文件偏移 0x0000 - 0x01F3：diskboot.S 代码（约 500 字节）
└─ 文件偏移 0x01F4 - 0x01FF：块列表数据（12 字节）← .org 0x200 - 12

加载到内存后（boot.S 读取第一个扇区到 0x8000）：
├─ 内存地址 0x8000 - 0x81F3：diskboot.S 代码（约 500 字节）
└─ 内存地址 0x81F4 - 0x81FF：块列表数据（12 字节）

startup_raw.S 的位置（diskboot.S 加载第二个扇区开始）：
└─ 内存地址 0x8200+：startup_raw.S（从第二个扇区开始加载）
```

**关键点：**

1. **`diskboot.S` 正好是 512 字节**：代码部分约 500 字节，块列表 12 字节
2. **块列表的位置**：在第一个扇区的末尾（偏移 0x1F4-0x1FF）
3. **startup_raw.S 的位置**：从 `0x8200` 开始（第二个扇区）

### diskboot.S 读取块列表的代码

```asm
// grub/grub-core/boot/i386/pc/diskboot.S:61-320
_start:
    // 设置 %di 指向第一个块列表条目
    movw    $LOCAL(firstlist), %di  // %di = 0x81F4
    
LOCAL(bootloop):
    // 检查 len 字段（偏移 8 字节）
    cmpw    $0, 8(%di)
    je      LOCAL(bootit)  // 如果 len = 0，跳转到启动代码
    
LOCAL(setup_sectors):
    // 读取 start 字段：起始扇区号
    movl    (%di), %ebx      // 低 32 位
    movl    4(%di), %ecx     // 高 32 位
    
    // 读取 len 字段：要读取的扇区数
    movw    8(%di), %ax
    
    // 使用 INT 13h 读取扇区到临时缓冲区
    // ... 读取代码 ...
    
LOCAL(copy_buffer):
    // 读取 segment 字段：目标内存段
    movw    10(%di), %es
    
    // 从临时缓冲区复制数据到目标地址
    // ... 复制代码 ...
    
    // 移动到下一个块列表条目（向前移动 12 字节）
    subw    $GRUB_BOOT_MACHINE_LIST_SIZE, %di
    jmp     LOCAL(bootloop)
```

### 块列表字段的内存布局

```
块列表条目在内存中的布局（12 字节）：
┌─────────────────────────────────────┐
│ 偏移 0-3:   start (低 32 位)        │  4 字节
│ 偏移 4-7:   start (高 32 位)        │  4 字节
│ 偏移 8-9:   len (扇区数)             │  2 字节
│ 偏移 10-11: segment (目标段地址)     │  2 字节
└─────────────────────────────────────┘

访问方式：
- (%di)      → start 低 32 位
- 4(%di)     → start 高 32 位
- 8(%di)     → len
- 10(%di)    → segment
```

### 块列表条目的数量和存储限制

**实际使用中只有一个条目的原因：**

1. **存储限制**：第一个扇区只有 12 字节空间（0x81F4-0x81FF），只能存储一个块列表条目
2. **grub-mkimage 的行为**：尽量将 core.img 放在连续扇区中，避免需要多个条目
3. **循环逻辑**：虽然代码中有处理多个条目的循环逻辑，但由于存储限制，实际上用不上

### 块列表的生成代码（save_blocklists）

```c
// grub/util/setup.c:147-199
static void
save_blocklists (grub_disk_addr_t sector, unsigned offset, unsigned length,
                 void *data)
{
    struct blocklists *bl = data;
    struct grub_boot_blocklist *prev = bl->block + 1;
    
    // 计算需要读取的扇区数
    grub_uint64_t seclen = (length + GRUB_DISK_SECTOR_SIZE - 1) >> GRUB_DISK_SECTOR_BITS;
    
    // 如果与前一个条目连续，合并它们
    if (bl->block != bl->first_block
        && (grub_target_to_host64 (prev->start) + grub_target_to_host16 (prev->len)) == sector)
    {
        // 合并到前一个条目
        prev->len = grub_host_to_target16 (t + seclen);
    }
    else
    {
        // 创建新的块列表条目
        bl->block->start = grub_host_to_target64 (sector);
        bl->block->len = grub_host_to_target16 (seclen);
        bl->block->segment = grub_host_to_target16 (bl->current_segment);
        bl->block--;  // 移动到下一个条目位置
    }
    
    // 更新目标段地址
    bl->current_segment += seclen << (GRUB_DISK_SECTOR_BITS - 4);
}
```

### 结构体字段说明

1. **`start`（grub_uint64_t，8 字节）**：
   - 存储要读取的数据在磁盘上的起始扇区号（LBA）
   - 支持大容量磁盘（最大 2^64 扇区）
   - 示例：11917（0x2e8d）

2. **`len`（grub_uint16_t，2 字节）**：
   - 存储要读取的扇区数量
   - 最大支持 65535 个扇区（约 32MB）
   - `len = 0` 表示块列表结束

3. **`segment`（grub_uint16_t，2 字节）**：
   - 存储目标内存段地址（实模式下的段地址）
   - 物理地址 = segment × 16
   - 示例：0x0820 对应物理地址 0x8200

---

## 实模式下的内存使用分析

- **1MB 内存是否够用？**
  - **够用**：在实模式阶段，所有代码和数据都在 1MB 范围内：
    - `0x7C00 - 0x7DFF`：引导扇区（512 字节）
    - `0x8000 - 0x9FFF`：GRUB Core（约 8KB）
    - `0xF0000 - 0xFFFFF`：BIOS ROM（只读）
  - **总计使用**：约 10-20KB，远小于 1MB 的可用空间

- **地址会不会冲突？**
  - **不会冲突**：内存布局是精心设计的
  - 引导扇区：`0x7C00 - 0x7DFF`
  - GRUB Core：`0x8000+`（与引导扇区不重叠）

- **为什么需要切换到保护模式？**
  - 内核镜像通常较大（几 MB 到几十 MB），无法放入前 1MB
  - GRUB Core 解压后也需要 1MB 以上的空间
  - 因此需要先切换到保护模式，才能访问 1MB 以上的内存

---

## 相关文档

- [BOOT_FLOW.md](BOOT_FLOW.md) - GRUB 启动流程
- [GRUB_ARCHITECTURE_AND_INIT.md](GRUB_ARCHITECTURE_AND_INIT.md) - GRUB 架构设计与初始化
- [GRUB_MODE_SWITCHING.md](GRUB_MODE_SWITCHING.md) - GRUB 模式切换函数详解
