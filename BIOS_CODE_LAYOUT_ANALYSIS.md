# BIOS 代码布局分析：128KB 映射区域内的代码与保护模式代码

本文档基于 SeaBIOS 和 QEMU 源代码，分析：
1. **哪些 BIOS 代码映射到 128KB（0xE0000-0xFFFFF）区域**（实模式可访问）
2. **哪些 BIOS 代码没有映射到 128KB 区域**（需要保护模式访问）

> **相关文档**：关于 BIOS 运行模式、内存布局、地址映射等基础概念，请参见 [BIOS 运行模式与内存访问详解](BIOS_MEMORY_MODE.md)。

## 概述

### QEMU 的 BIOS 映射机制

QEMU 将 BIOS 的最后 128KB 映射到实模式可访问的地址空间（0xE0000-0xFFFFF）。

**关键点：**
- 只有 BIOS 的**最后 128KB** 被映射到实模式可访问的地址空间（0xE0000-0xFFFFF）
- 完整的 BIOS 代码位于 4GB 顶部（例如：0xFFFF80000-0xFFFFFFFF，对于 512KB BIOS）
- 如果 BIOS 大小为 512KB，那么前 384KB（512KB - 128KB）**不在**128KB 映射区域中

**QEMU 源代码实现：**

```c
// QEMU 源代码：hw/i386/x86-common.c:1014-1025
void x86_isa_bios_init(MemoryRegion *isa_bios, MemoryRegion *isa_memory,
                       MemoryRegion *bios, bool read_only)
{
    uint64_t bios_size = memory_region_size(bios);
    uint64_t isa_bios_size = MIN(bios_size, 128 * KiB);

    // 将 BIOS 的最后 128KB 创建为别名，映射到 ISA 空间
    memory_region_init_alias(isa_bios, NULL, "isa-bios", bios,
                             bios_size - isa_bios_size, isa_bios_size);
    // 映射到 0xE0000-0xFFFFF（1MB - 128KB 到 1MB）
    memory_region_add_subregion_overlap(isa_memory, 1 * MiB - isa_bios_size,
                                        isa_bios, 1);
    memory_region_set_readonly(isa_bios, read_only);
}
```

> **详细说明**：关于 QEMU BIOS 映射机制的完整解释（包括映射 vs 复制、真实硬件对比等），请参见 [BIOS 运行模式与内存访问详解](BIOS_MEMORY_MODE.md) 中的"BIOS ROM的特殊映射"和"QEMU 软件实现 vs. 真实硬件加载 BIOS 的区别"章节。

**重要说明：4GB 顶部 vs 物理内存前 1MB**

**关键问题：BIOS 在 4GB 顶部，而实模式的 1MB 区域（IVT 等）也在"实际内存顶部"，会不会冲突？**

**答案：不会冲突。这是两个完全不同的地址范围，指向不同的物理内存区域：**

- **4GB 顶部（BIOS 位置）**：`0xFFFF80000 - 0xFFFFFFFF`（32 位地址空间的末尾）
- **物理内存前 1MB（IVT 等）**：`0x000000 - 0xFFFFF`（物理内存的开始）

**地址差值**：`0xFFFF80000 - 0xFFFFF = 0xFFF80001` ≈ 4GB，相差约 4GB，完全不会重叠。

**物理设备不同**：
- BIOS → Flash ROM 芯片（独立存储设备）
- IVT 等 → DRAM 芯片（系统 RAM）

> **详细说明**：关于 4GB 顶部与物理内存前 1MB 的区别，请参见 [BIOS 运行模式与内存访问详解](BIOS_MEMORY_MODE.md) 中的"问题 2：为什么 BIOS 存储在 4GB 地址空间顶部？"章节。

### SeaBIOS 的代码段组织

SeaBIOS 使用特殊的宏标记来组织代码段，将代码分为不同的段以便在不同模式下访问：

**主要标记：**
- **VISIBLE32FLAT**：保护模式运行时代码（`.text.runtime` 段）
- **VISIBLE32INIT**：保护模式初始化代码（`.text.init` 段）
- **VISIBLE16** / **FUNC16()**：实模式代码（`.text.asm.16` 段）
- **VAR16**：实模式可访问的数据（`.data16` 段）
- **VARFSEG**：实模式可访问的数据（`.varfseg` 段）

> **详细说明**：关于 SeaBIOS 代码段组织的完整解释（包括运行时代码 vs 初始化代码、内存访问宏等），请参见 [BIOS 运行模式与内存访问详解](BIOS_MEMORY_MODE.md) 中的"BIOS代码的分段组织"章节。

## 映射到 128KB 区域的代码

### 概述

映射到 128KB（0xE0000-0xFFFFF）区域的代码必须满足以下条件：
1. **实模式可访问**：必须在实模式下能够访问和执行
2. **关键启动代码**：CPU 复位后必须能够执行
3. **中断处理入口**：BIOS 中断服务程序的入口点
4. **实模式数据**：实模式下需要访问的数据

### 1. 复位向量和启动代码

**位置：** BIOS 的最后 16 字节（0xFFFF0-0xFFFFF）

**功能：**
- CPU 复位后从 `0xFFFF0` 开始执行
- 必须位于实模式可访问的地址（0xE0000-0xFFFFF）
- 包含跳转到 POST 入口点的代码

**代码示例：**

```asm
; SeaBIOS 复位向量代码（简化）
; 位置：0xFFFF0（BIOS 的最后 16 字节）

reset_vector:
    ; CPU 复位后从这里开始执行
    jmp far 0xF000:post_entry  ; 跳转到 POST 入口点
    ; 或者
    jmp far 0xF000:handle_post  ; 跳转到 handle_post()
```

**关键点：**
- **必须位于 128KB 映射区域**：因为 CPU 复位后从 0xFFFF0 开始执行，必须在实模式可访问范围内
- **最后 16 字节**：x86 架构规定 CPU 复位后从 0xFFFFFFF0（实模式下为 0xFFFF0）开始执行
- **跳转指令**：通常是一个远跳转（far jump），跳转到 POST 入口点

### 2. 实模式中断处理程序入口（FUNC16）

**位置：** 多个源文件，使用 `FUNC16()` 或 `VISIBLE16` 标记

**功能：**
- BIOS 中断服务程序的入口点
- 在实模式下执行
- 处理软件中断（INT 指令）和硬件中断（IRQ）

**关键函数：**

#### 2.1 视频服务（INT 10h）

```asm
; SeaBIOS 源代码：src/vgasrc/vgainit.c
VISIBLE16 void
entry_10(void)
{
    // INT 10h 中断处理程序入口
    // 处理视频服务（显示字符、设置模式等）
    // 在实模式下执行
}
```

**位置：** `src/vgasrc/vgainit.c`

**功能：**
- 处理视频显示服务
- 显示字符、设置显示模式、读取光标位置等
- 通过 `int 0x10` 调用

#### 2.2 磁盘服务（INT 13h）

```asm
; SeaBIOS 源代码：src/block.c
VISIBLE16 void
entry_13(void)
{
    // INT 13h 中断处理程序入口
    // 处理磁盘 I/O 服务
    // 在实模式下执行，但可能调用保护模式代码
}
```

**位置：** `src/block.c`

**功能：**
- 处理磁盘读写操作
- 读取扇区、写入扇区、获取磁盘参数等
- 通过 `int 0x13` 调用

#### 2.3 键盘服务（INT 16h）

```asm
; SeaBIOS 源代码：src/hw/ps2port.c
VISIBLE16 void
entry_16(void)
{
    // INT 16h 中断处理程序入口
    // 处理键盘输入服务
    // 在实模式下执行
}
```

**位置：** `src/hw/ps2port.c`

**功能：**
- 处理键盘输入
- 读取按键、检查按键状态等
- 通过 `int 0x16` 调用

#### 2.4 其他 BIOS 中断服务

```asm
; 其他常见的中断处理程序入口
VISIBLE16 void entry_11(void);  // 设备检测（INT 11h）
VISIBLE16 void entry_12(void);  // 内存大小（INT 12h）
VISIBLE16 void entry_14(void);  // 串口服务（INT 14h）
VISIBLE16 void entry_15(void);  // 系统服务（INT 15h）
VISIBLE16 void entry_17(void);  // 打印机服务（INT 17h）
VISIBLE16 void entry_19(void);  // 引导服务（INT 19h）
VISIBLE16 void entry_1a(void);  // 时间服务（INT 1Ah）
```

**特点：**
- 所有使用 `VISIBLE16` 或 `FUNC16()` 标记的函数
- 位于 `.text.asm.16` 或类似的 16 位代码段
- 在实模式下执行
- 可以通过 `call16_int()` 调用保护模式代码

### 3. 实模式可访问的数据（VAR16 和 VARFSEG）

**位置：** 多个源文件，使用 `VAR16` 或 `VARFSEG` 标记

**功能：**
- 实模式下需要访问的全局变量
- BIOS 配置数据
- 中断处理程序使用的数据结构

**关键数据：**

#### 3.1 中断向量表相关数据

```c
// SeaBIOS 源代码：src/post.c
// 中断向量表的初始化数据
// 使用 VAR16 或 VARFSEG 标记
```

#### 3.2 BIOS 数据区（BDA）相关数据

```c
// SeaBIOS 源代码：src/biosvar.h
// BIOS 数据区的变量
// 使用 VAR16 标记
```

#### 3.3 VGA 相关数据

```c
// SeaBIOS 源代码：vgasrc/vgabios.c
char VERSION[] VAR16 = BUILD_VERSION;
char BUILDINFO[] VAR16 = BUILD_TOOLS;
struct video_func_static static_functionality VAR16 = {
    // VGA 功能数据
};
```

**位置：** `vgasrc/vgabios.c`, `vgasrc/vgaversion.c`

**功能：**
- VGA BIOS 版本信息
- VGA 功能配置数据
- 实模式下可访问的 VGA 相关变量

#### 3.4 磁盘驱动相关数据

```c
// SeaBIOS 源代码：src/block.c
u8 FloppyCount VARFSEG;
struct drive_s *IDMap[3][BUILD_MAX_EXTDRIVE] VARFSEG;
u8 *bounce_buf_fl VARFSEG;
```

**位置：** `src/block.c`

**功能：**
- 磁盘驱动器数量
- 磁盘驱动器映射表
- 磁盘 I/O 缓冲区

### 4. 模式切换辅助代码

**位置：** `src/stacks.c`

**功能：**
- 实模式和保护模式之间的切换代码
- `call16()` 和 `call32()` 函数的部分代码
- 栈管理相关代码

**关键函数：**

```c
// SeaBIOS 源代码：src/stacks.c
// 实模式和保护模式切换的辅助数据结构
struct {
    u8 method;
    u8 cmosindex;
    u8 a20;
    u16 ss, fs, gs;
    u32 cr0;
    struct descloc_s gdt;
} Call16Data VARLOW;  // 位于实模式可访问区域
```

**特点：**
- 使用 `VARLOW` 标记，位于实模式可访问区域
- 存储模式切换时的状态信息
- 在实模式和保护模式之间切换时使用

### 5. 代码段组织总结

**映射到 128KB 区域的代码段：**

| 代码段 | 标记 | 位置 | 功能 |
|--------|------|------|------|
| **复位向量** | - | 0xFFFF0 | CPU 复位后从这里开始执行 |
| **16位代码段** | `VISIBLE16`, `FUNC16()` | `.text.asm.16` | 实模式中断处理程序入口 |
| **16位数据段** | `VAR16` | `.data16` | 实模式可访问的数据 |
| **F段数据** | `VARFSEG` | `.varfseg` | 实模式可访问的数据（F段） |
| **低地址数据** | `VARLOW` | `.varlow` | 实模式可访问的数据（低地址） |

**代码大小估算：**

对于典型的 512KB BIOS：
- **复位向量**：16 字节（0xFFFF0-0xFFFFF）
- **中断处理程序入口**：约 2-4KB（所有 INT 入口点）
- **实模式数据**：约 4-8KB（VAR16、VARFSEG 数据）
- **模式切换代码**：约 1-2KB（call16/call32 相关）
- **总计**：约 8-15KB（远小于 128KB）

**关键点：**
- 128KB 映射区域主要包含**关键的启动代码**和**中断处理程序入口**
- 大部分 BIOS 代码（保护模式代码）不在映射区域中
- 映射区域中的代码通常很小，但非常重要

## 未映射到 128KB 的保护模式代码

### 1. POST 初始化代码（VISIBLE32INIT）

**位置：** `src/post.c`

**关键函数：**

```c
// POST 初始化：代码重定位和初始化
// VISIBLE32INIT: 在 32 位初始化代码段中可见
void VISIBLE32INIT
dopost(void)
{
    code_mutable_preinit();

    // 检测 RAM 并设置内部内存分配器
    qemu_preinit();        // QEMU 平台特定初始化
    coreboot_preinit();    // Coreboot 平台特定初始化
    malloc_preinit();      // 初始化内存分配器

    // 重定位初始化代码并调用主初始化函数
    reloc_preinit(maininit, NULL);
}
```

**特点：**
- 使用 `VISIBLE32INIT` 标记，位于 `.text.init` 段
- 在保护模式下执行
- 不在 128KB 映射区域中
- 执行硬件检测、内存检测、PCI 初始化等

**相关代码：**
- `src/post.c:303-315` - `dopost()`
- `src/post.c:254-286` - `reloc_preinit()` - 重定位初始化代码
- `src/stacks.c` - 栈管理相关代码

### 2. 运行时 BIOS 服务代码（VISIBLE32FLAT）

**位置：** 多个源文件

**关键函数：**

#### 2.1 POST 入口点

```c
// POST 入口点：BIOS 初始化阶段
// 此函数使 0xc0000-0xfffff 内存区域可读写，然后调用 dopost()
// VISIBLE32FLAT: 在 32 位平坦地址空间中可见
void VISIBLE32FLAT
handle_post(void)
{
    if (!CONFIG_QEMU && !CONFIG_COREBOOT)
        return;

    serial_debug_preinit();
    debug_banner();

    // 检查是否在 Xen 下运行
    xen_preinit();

    // 允许写入 BIOS 区域（0xf0000）
    make_bios_writable();

    // 现在内存可读写 - 开始 POST 过程
    dopost();
}
```

**位置：** `src/post.c:320-337`

#### 2.2 磁盘访问服务

```c
int VISIBLE32FLAT
process_op(struct disk_op_s *op)
{
    // 处理磁盘操作（读/写）
    // 在保护模式下执行，可以访问大内存缓冲区
}
```

**位置：** `src/block.c`

**功能：**
- 处理磁盘 I/O 操作
- 支持多种存储设备（ATA、AHCI、USB、NVMe 等）
- 需要访问大内存缓冲区（超过 1MB）

#### 2.3 系统管理模式（SMM）

```c
void VISIBLE32FLAT
smm_setup(void)
{
    // 设置系统管理模式
    // 用于高级电源管理和安全功能
}
```

**位置：** `src/fw/smm.c`

#### 2.4 引导加载代码

```c
void VISIBLE32FLAT
boot_disk(u8 bootdrv, int checksig)
{
    // 从磁盘加载引导扇区
    // 在保护模式下执行，可以访问大内存
}
```

**位置：** `src/boot.c`

#### 2.5 TPM（可信平台模块）支持

```c
void VISIBLE32FLAT
tpm_*()
{
    // TPM 相关功能
}
```

**位置：** `src/tcgbios.c`

#### 2.6 USB 扩展主机控制器接口（xHCI）

```c
int VISIBLE32FLAT
process_xhci_op(struct disk_op_s *op)
{
    // 处理 USB 3.0 xHCI 控制器操作
}
```

**位置：** `src/hw/usb-xhci.c`

#### 2.7 多处理器支持

```c
void VISIBLE32FLAT
smp_setup(void)
{
    // 设置多处理器环境
}
```

**位置：** `src/fw/smp.c`

#### 2.8 兼容性支持模块（CSM）

```c
void VISIBLE32INIT
csm_init(void)
{
    // 初始化兼容性支持模块
    // 用于 UEFI 环境下的传统 BIOS 兼容
}
```

**位置：** `src/fw/csm.c`

### 3. 代码重定位机制

SeaBIOS 使用代码重定位机制来访问初始化代码：

```c
// 重定位初始化代码并调用函数
void __noreturn
reloc_preinit(void *f, void *arg)
{
    // 分配空间用于初始化代码
    u32 initsize = SYMBOL(code32init_end) - SYMBOL(code32init_start);
    u32 codealign = SYMBOL(_reloc_min_align);
    void *codedest = memalign_tmp(codealign, initsize);
    void *codesrc = VSYMBOL(code32init_start);
    
    // 复制代码并更新重定位信息
    memcpy(codedest, codesrc, initsize);
    updateRelocs(codedest, ...);
    
    // 调用重定位后的函数
    func(arg);
}
```

**位置：** `src/post.c:254-286`

**功能：**
- 将初始化代码从 BIOS ROM 复制到 RAM
- 更新代码中的地址引用（重定位）
- 允许在保护模式下执行初始化代码

## 代码段布局总结

### 在 128KB 映射区域中的代码

1. **复位向量和启动代码**
   - CPU 复位后从 `0xFFFF0` 开始执行
   - 必须位于实模式可访问的地址
   - 包含跳转到 POST 入口点的代码

2. **实模式中断处理程序入口**
   - 使用 `FUNC16()` 或 `VISIBLE16` 标记的函数
   - 例如：`entry_10()`, `entry_13()`, `entry_16()` 等
   - 位于 `.text.asm.16` 段
   - 处理 BIOS 中断服务（INT 10h, INT 13h, INT 16h 等）

3. **实模式可访问的数据**
   - 使用 `VAR16` 或 `VARFSEG` 标记的变量
   - 例如：中断向量表、BIOS 数据区、VGA 配置数据等
   - 位于 `.data16` 或 `.varfseg` 段

4. **模式切换辅助代码**
   - `call16()` 和 `call32()` 函数的部分代码
   - 模式切换时的状态数据结构（VARLOW）

### 不在 128KB 映射区域中的代码（需要保护模式访问）

1. **初始化代码（.text.init 段）**
   - 使用 `VISIBLE32INIT` 标记
   - 包括：`dopost()`, `maininit()`, `csm_init()` 等
   - 在 POST 阶段执行，完成后可能被丢弃或覆盖

2. **运行时服务代码（.text.runtime 段）**
   - 使用 `VISIBLE32FLAT` 标记
   - 包括：
     - `handle_post()` - POST 入口点
     - `process_op()` - 磁盘操作
     - `boot_disk()` - 引导加载
     - `smm_setup()` - SMM 设置
     - `smp_setup()` - 多处理器设置
     - `tpm_*()` - TPM 功能
     - USB xHCI 支持
     - 其他高级功能

3. **代码重定位机制**
   - `reloc_preinit()` - 重定位初始化代码
   - 允许在保护模式下访问完整的 BIOS 代码

## 访问流程

### 代码访问流程概述

**映射到 128KB 区域的代码：**
- 在实模式下直接访问（通过 0xE0000-0xFFFFF）
- 包括：复位向量、中断处理程序入口、实模式数据

**未映射到 128KB 区域的代码：**
- 需要切换到保护模式访问（通过 4GB 顶部地址）
- 包括：POST 初始化代码、运行时服务代码

**模式切换：**
- SeaBIOS 使用 `call32()` 和 `call16()` 函数在实模式和保护模式之间切换
- 实模式中断处理程序可以通过 `call16_int()` 调用保护模式代码

> **详细说明**：关于完整 BIOS 执行流程和模式切换机制的详细解释，请参见 [BIOS 运行模式与内存访问详解](BIOS_MEMORY_MODE.md) 中的"完整的BIOS执行流程"和"模式切换机制"章节。

## 总结

### 关键发现

1. **只有最后 128KB 映射到实模式地址空间**
   - QEMU 的 `x86_isa_bios_init()` 只映射最后 128KB
   - 对于 512KB BIOS，前 384KB 不在映射区域中

2. **大部分 BIOS 代码需要保护模式访问**
   - POST 初始化代码（VISIBLE32INIT）
   - 运行时服务代码（VISIBLE32FLAT）
   - 这些代码位于 4GB 顶部，不在 128KB 映射区域

3. **代码重定位机制**
   - SeaBIOS 使用 `reloc_preinit()` 将初始化代码复制到 RAM
   - 允许在保护模式下访问完整的 BIOS 代码

4. **模式切换机制**
   - BIOS 在实模式和保护模式之间快速切换
   - 使用 `call32()` 和 `call16()` 函数进行模式切换

### 设计优势

1. **兼容性**：保持与传统实模式 BIOS 的兼容
2. **灵活性**：可以在保护模式下访问更多内存和执行复杂操作
3. **效率**：关键的中断处理程序在实模式下快速响应
4. **可扩展性**：可以添加更多保护模式功能而不受 128KB 限制

### 相关文档

- [BIOS 运行模式与内存访问详解](BIOS_MEMORY_MODE.md)
- [QEMU vs 真实硬件 BIOS 加载对比](QEMU_VS_HARDWARE_BIOS.md)
- [BIOS 启动流程详解](BOOT_FLOW.md)

