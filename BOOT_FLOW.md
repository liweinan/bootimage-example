# QEMU → SeaBIOS → Linux Kernel 启动流程详解

本文档详细介绍了从 QEMU 虚拟硬件启动到 Linux 内核接管系统的完整流程，包括 SeaBIOS 的加载、中断服务初始化，以及内核如何接管 BIOS 并建立自己的中断处理机制。

---

## 如何阅读本文档

### 快速导航

**按学习目标选择：**
- 🎯 **了解完整启动流程** → 阅读本文档各章节概述
- 🔍 **深入某个阶段** → 点击章节末尾的详细文档链接
- ⏱️ **时间线视图** → [BOOT_FLOW_TIMELINE.md](BOOT_FLOW_TIMELINE.md) - 完整执行时间线
- ❓ **常见问题** → [BOOT_FLOW_QA.md](BOOT_FLOW_QA.md) - Q&A 格式问答
- 📚 **源代码索引** → [BOOT_FLOW_SOURCE_INDEX.md](BOOT_FLOW_SOURCE_INDEX.md) - 关键源文件位置

### 文档层次结构

```
层级 1: 启动流程概述（本文档）
  ├─ QEMU 硬件初始化
  ├─ SeaBIOS 固件加载
  ├─ BIOS 引导流程
  ├─ GRUB 引导加载器
  └─ Linux 内核启动

层级 2: 详细分析文档
  ├─ GRUB_KERNEL_LOADING.md - GRUB 加载内核完整流程
  ├─ LINUX_KERNEL_INIT.md - 内核启动与初始化（不走 Setup：GRUB/压缩内核 → start_kernel → 核心进程）
  ├─ LINUX_KERNEL_SETUP_FLOW.md - 从扇区 0 启动时的 Setup 流程
  └─ LINUX_KERNEL_INIT.md - start_kernel() 初始化（含中断接管：早期 IDT、PIC、APIC、INT 0x80）

层级 3: 技术深度文档
  ├─ BOOT_FLOW_NOTES.md - 16 个技术深度说明
  ├─ X86_CPU_MODES.md - CPU 模式切换机制
  ├─ BIOS_MEMORY_LAYOUT.md - 内存布局详解
  └─ [其他专题文档 - 见下方相关文档索引]
```

**建议阅读路径：**
1. **初学者**：先读本文档概述 → 再选择感兴趣的详细文档
2. **深入研究**：本文档 → 层级 2 详细分析 → 层级 3 技术深度 → 源代码
3. **问题导向**：先查看 BOOT_FLOW_QA.md → 根据答案中的链接深入

---

## 目录

- [QEMU 加载 SeaBIOS](#qemu-加载-seabios)
- [SeaBIOS 初始化中断服务](#seabios-初始化中断服务)
- [BIOS 引导流程：从 SeaBIOS 到引导扇区](#bios-引导流程从-seabios-到引导扇区)
- [GRUB 加载 Linux 内核](#grub-加载-linux-内核)
- [总结：完整流程时间线](#总结完整流程时间线)
- [技术细节说明](#技术细节说明)
- [Q&A：常见问题解答](#qa常见问题解答)
- [关键源代码文件索引](#关键源代码文件索引)
- [附录](#附录)

## 相关文档索引

### 核心参考文档（各阶段详细分析）

这些文档提供各启动阶段的完整源代码分析和实现细节：

**阅读说明（三篇内核文档按启动顺序）**：

| 顺序 | 文档 | 对应的大致时机 |
|------|------|----------------|
| 1 | LINUX_KERNEL_INIT.md | GRUB/入口 → startup_32 → startup_64 → x86_64_start_kernel（早期 IDT）→ start_kernel() → 核心进程 |
| 2 | LINUX_KERNEL_INIT.md | start_kernel() 及之后（含早期 IDT、PIC/APIC、INT 0x80，见文档内「中断系统接管详细流程」） |

按启动先后：**早期启动与内核初始化** 已合并为 [LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md)（GRUB/压缩内核 → start_kernel → 核心进程，含早期 IDT 与 init_IRQ）。

- 📖 [GRUB 加载 Linux 内核详细流程](GRUB_KERNEL_LOADING.md) - grub_main() 到内核入口点完整分析
- 📖 [Linux 内核启动与初始化（64 位，不走 Setup）](LINUX_KERNEL_INIT.md) - GRUB/压缩内核、模式切换、startup_32/startup_64、start_kernel、核心进程
- 📖 [Linux 内核 Setup 流程（从扇区 0 启动）](LINUX_KERNEL_SETUP_FLOW.md) - header.S → main → go_to_protected_mode → startup_32
- 📖 [Linux 内核初始化详解](LINUX_KERNEL_INIT.md) - start_kernel()、中断接管（IDT/PIC/APIC/INT 0x80）、系统调用、PID 0/1/2、init 进程
- 📖 [BIOS 中断处理完整详解](BIOS_INTERRUPT_COMPLETE.md) - IVT、中断服务程序、硬件初始化

### 系统层次专题文档

**BIOS / 固件层：**
- [x86 CPU 运行模式详解](X86_CPU_MODES.md) - 实模式、保护模式、长模式切换机制
- [BIOS 内存布局与地址映射详解](BIOS_MEMORY_LAYOUT.md) - 内存映射、地址空间、ROM 映射
- [BIOS 内存模式 Q&A](BIOS_MEMORY_QA.md) - 常见内存相关问题解答
- [BIOS 代码布局分析](BIOS_CODE_LAYOUT_ANALYSIS.md) - 128KB 映射区域与保护模式代码
- [BIOS IVT vs Kernel IDT 详细对比](BIOS_IVT_VS_KERNEL_IDT.md) - 中断向量表对比

**SeaBIOS 实现：**
- [SeaBIOS entry_13_official 实现详细分析](SEABIOS_ENTRY_13_ANALYSIS.md) - INT 13h 磁盘服务实现
- [SeaBIOS handle_post 入口地址定义机制](SEABIOS_HANDLE_POST_ENTRY.md) - POST 入口点机制

**GRUB 引导加载器：**
- [GRUB Core 镜像结构与构建](GRUB_CORE_IMG_STRUCTURE.md) - core.img 结构、块列表、内存布局
- [GRUB 模式切换机制](GRUB_MODE_SWITCHING.md) - real_to_prot、prot_to_real 实现
- [GRUB BIOS 中断使用场景](GRUB_BIOS_INTERRUPT_USAGE.md) - 保护模式下调用 BIOS 服务

**Linux 内核：**
- [Linux 内核中断处理机制](LINUX_INTERRUPT_HANDLING.md) - Top Half 和 Bottom Half
- [Linux 用户空间内存模型](LINUX_USERSPACE_MEMORY.md) - 内存管理、汇编内存访问
- [vmlinuz 文件结构详解](VMLINUZ_STRUCTURE.md) - bzImage 格式、boot_params、Setup 代码
- [Initramfs 分析](INITRAMFS_ANALYSIS.md) - initrd 内容、BusyBox 启动

### 对比分析文档

- [QEMU vs 真实硬件 BIOS 加载对比](QEMU_VS_HARDWARE_BIOS.md)
- [UEFI vs BIOS 引导机制对比](UEFI_VS_BIOS_BOOT.md)
- [boot.asm vs GRUB boot.S 对比](BOOTSECTOR_COMPARISON.md)
- [UEFI 中断处理机制](UEFI_INTERRUPT_HANDLING.md)

### 技术深度与参考资料

- [BOOT_FLOW 技术细节说明](BOOT_FLOW_NOTES.md) - 16 个技术深度说明
- [BOOT_FLOW 常见问题解答](BOOT_FLOW_QA.md) - Q&A 格式问答
- [BOOT_FLOW 完整时间线](BOOT_FLOW_TIMELINE.md) - 从 QEMU 到内核的执行时间线
- [BOOT_FLOW 源代码文件索引](BOOT_FLOW_SOURCE_INDEX.md) - 关键源代码文件位置
- [A20 地址线技术详解](A20_ADDRESS_LINE.md) - 历史背景、启用机制

### 示例与扩展

- [最小引导扇区程序示例](BOOTSECTOR_EXAMPLE.md) - 完整代码示例、内存地址、中断服务
- [附录A：键盘中断处理代码分析](APPENDIX_A_KEYBOARD_INTERRUPT.md)
- [附录B：应用层事件机制](APPENDIX_B_EVENT_MECHANISM.md)

---

## QEMU 加载 SeaBIOS

### 系统固件初始化入口

QEMU 在创建 PC 虚拟机时，会调用系统固件初始化函数来加载 BIOS。源代码位置：`qemu/hw/i386/pc_sysfw.c:215-285`

```c
// QEMU 系统固件初始化函数：决定如何加载 BIOS（SeaBIOS）
void pc_system_firmware_init(PCMachineState *pcms,
                             MemoryRegion *rom_memory)
{
    PCMachineClass *pcmc = PC_MACHINE_GET_CLASS(pcms);
    int i;
    BlockBackend *pflash_blk[ARRAY_SIZE(pcms->flash)];  // pflash 块设备数组

    // 如果 PCI 未启用（老式 PC），直接加载 BIOS ROM
    if (!pcmc->pci_enabled) {
        // 如果没有指定 IGVM 文件，则加载默认的 bios.bin（SeaBIOS）
        if (!X86_MACHINE(pcms)->igvm) {
            x86_bios_rom_init(X86_MACHINE(pcms), "bios.bin", rom_memory, true);
        }
        return;
    }

    // 将传统的 -drive if=pflash 命令行参数映射到机器属性
    for (i = 0; i < ARRAY_SIZE(pcms->flash); i++) {
        pflash_cfi01_legacy_drive(pcms->flash[i],
                                  drive_get(IF_PFLASH, 0, i));
        pflash_blk[i] = pflash_cfi01_get_blk(pcms->flash[i]);  // 获取块设备指针
    }

    // 检查 pflash 配置：不允许有间隙（如果 pflash1 存在，pflash0 必须存在）
    for (i = 1; i < ARRAY_SIZE(pcms->flash); i++) {
        if (pflash_blk[i] && !pflash_blk[i - 1]) {
            error_report("pflash%d requires pflash%d", i, i - 1);
            exit(1);
        }
    }

    // 如果没有配置 pflash0，使用 ROM 模式加载 BIOS
    if (!pflash_blk[0]) {
        // 除非使用 IGVM，否则加载默认的 bios.bin
        if (!X86_MACHINE(pcms)->igvm) {
            x86_bios_rom_init(X86_MACHINE(pcms), "bios.bin", rom_memory, false);
        }
    } else {
        // 如果配置了 pflash，检查 KVM 是否支持只读内存执行
        if (kvm_enabled() && !kvm_readonly_mem_enabled()) {
            // 旧版 KVM 无法从设备内存执行代码，需要只读内存支持
            error_report("pflash with kvm requires KVM readonly memory support");
            exit(1);
        }

        // 映射 flash 内存区域
        pc_system_flash_map(pcms, rom_memory);
    }

    // 清理未使用的 flash 设备
    pc_system_flash_cleanup_unused(pcms);

    // 使用 IGVM 时不应该配置 pflash 设备
    if (X86_MACHINE(pcms)->igvm) {
        for (i = 0; i < ARRAY_SIZE(pcms->flash); i++) {
            if (pcms->flash[i]) {
                error_report("pflash devices cannot be configured when "
                             "using IGVM");
                exit(1);
            }
        }
    }
}
```

**关键点：**
- 第 228 行或 254 行：如果没有配置 pflash，调用 `x86_bios_rom_init()` 加载默认的 `bios.bin`（SeaBIOS）
- 第 267 行：如果配置了 pflash，则映射 flash 内存区域

### BIOS ROM 加载实现

源代码位置：`qemu/hw/i386/x86-common.c:1027-1092`

```c
// 实际加载 BIOS ROM 文件到内存的函数
void x86_bios_rom_init(X86MachineState *x86ms, const char *default_firmware,
                       MemoryRegion *rom_memory, bool isapc_ram_fw)
{
    const char *bios_name;
    char *filename;
    int bios_size;
    ssize_t ret;

    // 步骤 1: 确定 BIOS 文件名（优先使用用户指定的，否则使用默认的 "bios.bin"）
    bios_name = MACHINE(x86ms)->firmware ?: default_firmware;
    
    // 步骤 2: 查找 BIOS 文件路径
    filename = qemu_find_file(QEMU_FILE_TYPE_BIOS, bios_name);
    if (filename) {
        bios_size = get_image_size(filename, NULL);  // 获取文件大小
    } else {
        bios_size = -1;  // 文件未找到
    }
    
    // 步骤 3: 验证 BIOS 文件大小（必须大于 0 且是 64KB 的倍数）
    if (bios_size <= 0 ||
        (bios_size % 65536) != 0) {
        goto bios_error;
    }
    
    // 步骤 4: 初始化 BIOS 内存区域
    if (machine_require_guest_memfd(MACHINE(x86ms))) {
        // 使用 guest_memfd（用于安全虚拟机，如 TDX）
        memory_region_init_ram_guest_memfd(&x86ms->bios, NULL, "pc.bios",
                                           bios_size, &error_fatal);
        if (is_tdx_vm()) {
            tdx_set_tdvf_region(&x86ms->bios);  // TDX 特殊配置
        }
    } else {
        // 普通 RAM 内存区域
        memory_region_init_ram(&x86ms->bios, NULL, "pc.bios",
                               bios_size, &error_fatal);
    }
    
    // 步骤 5: 加载 BIOS 文件到内存
    if (sev_enabled() || is_tdx_vm()) {
        // 机密计算环境（SEV/TDX）：直接加载文件，不支持复位
        void *ptr = memory_region_get_ram_ptr(&x86ms->bios);
        load_image_size(filename, ptr, bios_size);  // 直接加载文件内容
        x86_firmware_configure(0x100000000ULL - bios_size, ptr, bios_size);
    } else {
        // 普通环境：注册为 ROM，支持复位时重新加载
        memory_region_set_readonly(&x86ms->bios, !isapc_ram_fw);
        // 将 BIOS 文件添加到 ROM，地址为 0xFFFFFFFF - bios_size（内存顶部）
        ret = rom_add_file_fixed(bios_name, (uint32_t)(-bios_size), -1);
        if (ret != 0) {
            goto bios_error;
        }
    }
    g_free(filename);

    // 步骤 6: 将 BIOS 的最后 128KB 映射到 ISA 空间（0xE0000-0xFFFFF）
    if (!machine_require_guest_memfd(MACHINE(x86ms))) {
        x86_isa_bios_init(&x86ms->isa_bios, rom_memory, &x86ms->bios,
                          !isapc_ram_fw);
    }

    // 步骤 7: 将整个 BIOS 映射到内存顶部（ROM 内存区域）
    memory_region_add_subregion(rom_memory,
                                (uint32_t)(-bios_size),  // 地址：4GB - bios_size
                                &x86ms->bios);
    return;

bios_error:
    fprintf(stderr, "qemu: could not load PC BIOS '%s'\n", bios_name);
    exit(1);
}
```

**关键步骤：**
1. **第 1036 行**：确定 BIOS 文件名（默认 `bios.bin`，即 SeaBIOS）
2. **第 1037-1042 行**：查找并获取 BIOS 文件大小
3. **第 1054-1055 行**：初始化 BIOS 内存区域（`pc.bios`）
4. **第 1070 行**：将 BIOS 文件加载到内存顶部（`0x100000000 - bios_size`，即 4GB 以下）
5. **第 1084-1086 行**：将 BIOS 内存区域映射到 ROM 内存空间

**内存布局：**
- BIOS 被映射到物理地址 `0xFFFFFFFF - bios_size` 到 `0xFFFFFFFF`
- 最后 128KB 同时映射到 ISA 空间 `0xE0000-0xFFFFF`
- CPU 复位后从 `0xFFFF0`（BIOS 入口点）开始执行

> **注意**：关于 BIOS 运行模式（实模式/保护模式）、内存布局、地址映射等详细内容，请参见 [x86 CPU 运行模式详解](X86_CPU_MODES.md)、[BIOS 内存布局与地址映射详解](BIOS_MEMORY_LAYOUT.md) 和 [BIOS 内存模式 Q&A](BIOS_MEMORY_QA.md)。  
> 关于 QEMU 软件实现与真实硬件加载 BIOS 的区别，请参见 [QEMU vs 真实硬件 BIOS 加载对比](QEMU_VS_HARDWARE_BIOS.md)。  
> 关于哪些 BIOS 代码映射到 128KB 区域，哪些需要保护模式访问的详细分析，请参见 [BIOS 代码布局分析：128KB 映射区域内的代码与保护模式代码](BIOS_CODE_LAYOUT_ANALYSIS.md)。

---


## SeaBIOS 初始化中断服务

### Reset Vector 设置机制

CPU 复位后必须从物理地址 `0xFFFF0` 开始执行，这是 x86 架构的硬件要求。SeaBIOS 通过 ORG 宏和链接器脚本确保 `reset_vector` 代码被放置在正确的位置。

#### 源代码定义

**源代码位置：`seabios/src/romlayout.S:687-690`**

```asm
ORG 0xfff0 // Power-up Entry Point
.global reset_vector
reset_vector:
    ljmpw $SEG_BIOS, $entry_post
```

**关键点：**
- `ORG 0xfff0` 指定代码在 BIOS ROM 内的偏移地址（相对于 `0xF0000`）
- `reset_vector` 是全局符号，可以被链接器识别
- `ljmpw $SEG_BIOS, $entry_post` 跳转到 POST 入口点（`0xFE05B`）

#### ORG 宏机制

**源代码位置：`seabios/src/romlayout.S:589-591`**

```asm
.macro ORG addr
.section .fixedaddr.\addr
.endm
```

**工作原理：**
- `ORG 0xfff0` 创建一个名为 `.fixedaddr.fff0` 的链接器 section
- 链接器脚本会识别这个 section 并从中提取地址 `0xfff0`
- 这是 SeaBIOS 实现固定地址入口点的核心机制

#### 链接器脚本处理

**源代码位置：`seabios/scripts/layoutrom.py:74-82`**

```python
def fitSections(sections, fillsections):
    fixedsections = []
    for section in sections:
        if section.name.startswith('.fixedaddr.'):
            addr = int(section.name[11:], 16)  # 从 '.fixedaddr.fff0' 提取 'fff0'
            section.finalloc = addr + BUILD_BIOS_ADDR  # 0xfff0 + 0xf0000 = 0xffff0
            section.finalsegloc = addr  # 0xfff0（段内偏移）
            fixedsections.append((addr, section))
```

**地址计算过程：**

1. **识别固定地址段**：链接器脚本扫描所有 section，找到以 `.fixedaddr.` 开头的段
2. **提取地址**：从段名 `.fixedaddr.fff0` 中提取十六进制地址 `0xfff0`
3. **计算最终地址**：
   ```
   BUILD_BIOS_ADDR = 0xf0000  (scripts/layoutrom.py:64)
   最终物理地址 = 0xfff0 + 0xf0000 = 0xffff0
   ```
4. **段内偏移**：`finalsegloc = 0xfff0`（用于实模式段地址计算）

#### 地址映射关系

**物理地址计算：**
```
ROM 偏移地址：0xfff0（ORG 宏指定）
BIOS ROM 基地址：0xf0000（BUILD_BIOS_ADDR）
最终物理地址：0xfff0 + 0xf0000 = 0xffff0
```

**实模式段地址表示：**
```
段地址：SEG_BIOS = 0xf000 (src/config.h:62)
偏移地址：0xfff0
物理地址 = 0xf000 × 16 + 0xfff0 = 0xffff0
```

**文件偏移（对于 128KB bios.bin）：**
```
文件偏移 = 0x10000 + 0xfff0 = 0x1fff0
（在第二个 64KB 块内）
```

#### 完整设置流程

```
1. 源代码编译
   ORG 0xfff0 → 创建 .fixedaddr.fff0 section
   ↓
2. 链接器处理
   识别 .fixedaddr.fff0 → 提取地址 0xfff0
   ↓
3. 地址计算
   0xfff0 + BUILD_BIOS_ADDR (0xf0000) = 0xffff0
   ↓
4. 代码放置
   将 reset_vector 代码放在物理地址 0xffff0
   ↓
5. CPU 复位
   硬件自动跳转到 0xffff0
   ↓
6. 执行 reset_vector
   ljmpw $0xF000, $entry_post → 跳转到 0xFE05B
```

#### 关键配置常量

**源代码位置：`seabios/scripts/layoutrom.py:64-65`**

```python
BUILD_BIOS_ADDR = 0xf0000  # BIOS ROM 基地址
BUILD_BIOS_SIZE = 0x10000  # BIOS ROM 大小（64KB）
```

**源代码位置：`seabios/src/config.h:62`**

```c
#define SEG_BIOS     0xf000  // BIOS 段地址（实模式）
```

#### 验证方法

可以通过以下方式验证 reset_vector 的位置：

1. **检查编译后的二进制文件**：
   ```bash
   # 查看文件偏移 0x1FFF0 的内容（对应物理地址 0xFFFF0）
   hexdump -C bios.bin | grep -A 5 "1fff0"
   ```

2. **使用 verify_bios.py 脚本**：
   ```bash
   python3 verify_bios.py --addresses
   # 会显示 reset_vector 的物理地址、文件偏移和内容
   ```

3. **反汇编验证**：
   ```bash
   # 反汇编 reset_vector 代码
   objdump -D -b binary -m i386 bios.bin --start-address=0x1fff0 --stop-address=0x1fff5
   ```

**预期结果：**
- 文件偏移 `0x1FFF0` 处应该是 `0xEA`（far jump 操作码）
- 接下来的 4 字节应该是跳转目标：`0x5B 0xE0 0x00 0xF0`
- 解析后：跳转到 `0xF000:0xE05B` = 物理地址 `0xFE05B`（entry_post）

### POST 入口点

CPU 复位后，从 `0xFFFF0` 跳转到 SeaBIOS 的 POST（Power-On Self-Test）入口。源代码位置：`seabios/src/post.c:302-337`

> **详细说明**：关于 `handle_post` 如何被定义到固定入口地址 `0xe05b`、CPU 启动流程、地址映射机制等详细内容，请参见 [SeaBIOS handle_post 入口地址定义机制分析](SEABIOS_HANDLE_POST_ENTRY.md)。

```c
// POST 初始化：代码重定位和初始化
// VISIBLE32INIT: 在 32 位初始化代码段中可见
void VISIBLE32INIT
dopost(void)
{
    // 标记代码为可变（允许修改）
    code_mutable_preinit();

    // 检测 RAM 并设置内部内存分配器
    qemu_preinit();        // QEMU 平台特定初始化
    coreboot_preinit();    // Coreboot 平台特定初始化
    malloc_preinit();      // 初始化内存分配器

    // 重定位初始化代码并调用主初始化函数
    reloc_preinit(maininit, NULL);
}

// POST 入口点：BIOS 初始化阶段
// 此函数使 0xc0000-0xfffff 内存区域可读写，然后调用 dopost()
// VISIBLE32FLAT: 在 32 位平坦地址空间中可见
void VISIBLE32FLAT
handle_post(void)
{
    // 只在 QEMU 或 Coreboot 环境下执行
    if (!CONFIG_QEMU && !CONFIG_COREBOOT)
        return;

    // 初始化串口调试输出
    serial_debug_preinit();
    debug_banner();  // 打印调试横幅

    // 检查是否在 Xen 虚拟化环境下运行
    xen_preinit();

    // 允许写入 BIOS 区域（0xf0000），以便修改 BIOS 代码
    make_bios_writable();

    // 现在内存可读写，开始 POST 处理流程
    dopost();
}
```

### 主初始化流程

源代码位置：`seabios/src/post.c:196-235`

```c
// SeaBIOS 主初始化函数：按顺序初始化所有子系统
static void
maininit(void)
{
    // 阶段 1: 初始化内部接口（包括中断向量表 IVT）
    // interface_init() 内部会调用 ivt_init() 初始化中断向量表
    interface_init();  // 初始化 IVT、BDA、EBDA 等
                      // 调用链：interface_init() → ivt_init()（第 113 行）
                      // 
                      // **为什么 IVT 必须先于 PIC 初始化？**
                      // 1. IVT 是 CPU 查找中断处理程序的表，位于内存 0x0000:0000
                      // 2. 即使 PIC 未初始化，CPU 仍可能收到中断（NMI、硬件故障等）
                      // 3. 如果 IVT 未初始化，CPU 可能跳转到随机地址，导致系统崩溃
                      // 4. PIC 初始化过程中可能触发中断，需要 IVT 中有有效的处理程序

    // 阶段 2: 设置平台硬件（PIC、定时器等）
    platform_hardware_setup();  // 初始化 8259A PIC、定时器、时钟
                                // 
                                // **IVT 与 PIC 的关系：**
                                // 1. IVT 提供中断处理程序地址表（基础设施）
                                // 2. PIC 配置中断向量映射（ICW2），将硬件 IRQ 映射到 CPU 向量
                                // 3. PIC 配置的向量（如 0x08-0x0F）必须对应 IVT 中的有效处理程序
                                // 4. 当硬件中断发生时：硬件 → PIC → CPU → 查找 IVT → 执行处理程序

    // 阶段 3: 硬件设备初始化（根据配置决定是否并行执行）
    // 如果允许在 option ROM 期间使用线程，则提前启动硬件初始化
    if (threads_during_optionroms())
        device_hardware_setup();  // 并行初始化设备（USB、磁盘等）

    // 阶段 4: 初始化显示系统
    vgarom_setup();         // 设置 VGA ROM
    sercon_setup();         // 设置串口控制台
    enable_vga_console();    // 启用 VGA 控制台

    // 阶段 5: 同步硬件初始化（如果之前没有并行执行）
    if (!threads_during_optionroms()) {
        device_hardware_setup();  // 同步初始化所有硬件设备
        wait_threads();           // 等待所有线程完成
    }

    // 阶段 6: 运行 Option ROM（扩展卡固件，如网卡、RAID 卡等）
    optionrom_setup();

    // 阶段 7: 显示交互式启动菜单（允许用户选择启动顺序）
    interactive_bootmenu();
    wait_threads();

    // 阶段 8: 准备引导（最终化数据结构）
    prepareboot();  // 准备 E820 内存映射、CD-ROM 等

    // 阶段 9: 写保护 BIOS 内存（防止后续修改）
    make_bios_readonly();

    // 阶段 10: 调用 INT 19h 启动引导过程（加载引导扇区）
    startBoot();  // 跳转到 INT 19h 处理程序
}
```

**关键步骤：**
1. **第 200 行**：调用 `interface_init()` 初始化接口（包括中断向量表）
2. **第 203 行**：调用 `platform_hardware_setup()` 设置平台硬件（包括 PIC）
3. **第 234 行**：调用 `startBoot()` 启动引导过程

### 中断向量表（IVT）初始化

**调用时机：** `ivt_init()` 在 SeaBIOS POST 初始化流程中被调用，具体调用链如下：

```
CPU 复位 → 0xFFFF0（BIOS 入口点）
    ↓
handle_post()（POST 入口函数）
    ↓
dopost()（POST 处理函数）
    ↓
reloc_preinit(maininit, NULL)（代码重定位后调用主初始化）
    ↓
maininit()（主初始化函数）
    ↓
interface_init()（接口初始化函数，第 200 行调用）
    ↓
ivt_init()（中断向量表初始化，第 113 行调用）← 这里！
```

**调用位置：** `seabios/src/post.c:113`（在 `interface_init()` 函数中）

**调用时机说明：**
- `ivt_init()` 在 SeaBIOS POST 的**早期阶段**被调用
- 在 `maininit()` 函数的**第一个阶段**（接口初始化阶段）执行
- 在硬件初始化（PIC、定时器等）**之前**完成，因为后续硬件初始化可能需要使用中断服务
- 在代码重定位完成后调用，确保所有函数地址已正确

源代码位置：`seabios/src/post.c:32-71`

```c
// 初始化中断向量表（IVT）：设置所有 256 个中断向量的处理程序
// IVT 位于物理内存 0x0000:0000，每个向量占 4 字节（段:偏移）
// 调用时机：在 interface_init() 中被调用，属于 POST 早期初始化阶段
static void
ivt_init(void)
{
    dprintf(3, "init ivt\n");

    // 步骤 1: 将所有 256 个中断向量初始化为默认处理程序
    // entry_iret_official: 直接执行 IRET 返回，不做任何处理
    int i;
    for (i=0; i<256; i++)
        SET_IVT(i, FUNC16(entry_iret_official));

    // 步骤 2: 预先为 8259A PIC 的硬件中断向量设置处理程序
    // 注意：此时 PIC 还没有初始化，但先设置好处理程序，为后续 PIC 初始化做准备
    // BIOS_HWIRQ0_VECTOR 通常是 0x08（IRQ0-7，主 PIC）
    for (i=BIOS_HWIRQ0_VECTOR; i<BIOS_HWIRQ0_VECTOR+8; i++)
        SET_IVT(i, FUNC16(entry_hwpic1));  // 主 PIC 硬件中断处理程序（向量 0x08-0x0F）
    
    // BIOS_HWIRQ8_VECTOR 通常是 0x70（IRQ8-15，从 PIC）
    for (i=BIOS_HWIRQ8_VECTOR; i<BIOS_HWIRQ8_VECTOR+8; i++)
        SET_IVT(i, FUNC16(entry_hwpic2));  // 从 PIC 硬件中断处理程序（向量 0x70-0x77）
    // 
    // 关键点：这些处理程序在 PIC 初始化之前就已经设置好了
    // 这样当 pic_setup() 初始化 PIC 时，如果发生中断，IVT 中已经有有效的处理程序

    // 步骤 3: 初始化软件中断处理程序（BIOS 服务）
    // **重要：BIOS 不仅设置硬件中断处理程序，还设置软件中断服务程序**
    // 这些软件中断是 BIOS 提供给引导程序和早期系统软件的 API
    SET_IVT(0x02, FUNC16(entry_02));        // NMI（不可屏蔽中断）
    SET_IVT(0x05, FUNC16(entry_05));        // INT 05h: 打印屏幕服务
    SET_IVT(0x10, FUNC16(entry_10));        // INT 10h: 视频服务（显示字符、图形等）
    SET_IVT(0x11, FUNC16(entry_11));        // INT 11h: 获取设备列表
    SET_IVT(0x12, FUNC16(entry_12));        // INT 12h: 获取内存大小
    SET_IVT(0x13, FUNC16(entry_13_official)); // INT 13h: 磁盘服务（读/写扇区）
    // 详细实现分析：参见 [SeaBIOS entry_13_official 实现详细分析](SEABIOS_ENTRY_13_ANALYSIS.md)
    SET_IVT(0x14, FUNC16(entry_14));        // INT 14h: 串口服务
    SET_IVT(0x15, FUNC16(entry_15_official)); // INT 15h: 系统服务（APM、内存等）
    SET_IVT(0x16, FUNC16(entry_16));        // INT 16h: 键盘服务（读取按键）
    SET_IVT(0x17, FUNC16(entry_17));        // INT 17h: 打印机服务
    SET_IVT(0x18, FUNC16(entry_18));        // INT 18h: 启动 ROM BASIC（已废弃）
    SET_IVT(0x19, FUNC16(entry_19_official)); // INT 19h: 引导加载服务（加载引导扇区）
    SET_IVT(0x1a, FUNC16(entry_1a_official)); // INT 1Ah: 实时时钟服务
    SET_IVT(0x40, FUNC16(entry_40));        // INT 40h: 软盘服务（重定向到 INT 13h）
    //
    // **BIOS 软件中断服务程序总结：**
    // - INT 10h: 视频服务（显示字符、设置显示模式等）
    // - INT 13h: 磁盘服务（读取/写入扇区，这是引导加载程序最常用的服务）
    // - INT 15h: 系统服务（APM 电源管理、内存检测等）
    // - INT 16h: 键盘服务（读取按键输入）
    // - INT 19h: 引导加载服务（加载并执行引导扇区）
    // - 等等...
    // 这些软件中断是 BIOS 提供给引导程序和早期系统软件的标准 API
    //
    // **对比：Linux 内核的 IDT 也设置软件中断服务程序（系统调用）**
    // - 内核的 IDT 不仅设置硬件中断处理程序（IRQ），还设置系统调用入口
    // - 传统方式（32位）：INT 0x80 - 系统调用中断（通过 IDT）
    // - 现代方式（64位）：syscall/sysenter 指令（不通过 IDT，使用 MSR）
    // - 参见：linux/arch/x86/kernel/idt.c 和 linux/arch/x86/entry/entry_64.S
    //
    // **总结：BIOS IVT 和 Kernel IDT 都设置软件中断服务程序**
    // 1. BIOS IVT：设置 BIOS 服务（INT 10h, INT 13h, INT 15h 等）
    // 2. Kernel IDT：设置系统调用（INT 0x80，或通过 syscall 指令）
    // 两者都不仅处理硬件中断，还提供软件中断服务接口
    //
    // **重要说明：中断向量号 vs 内存地址**
    // - 这些数字（0x02, 0x10, 0x13 等）是中断向量号，不是内存地址
    // - 中断向量号是 IVT 的索引（0-255），由 x86 CPU 硬件约定
    // - IVT 位于物理内存 0x0000:0000，每个向量占 4 字节（段:偏移，各 2 字节）
    // - 向量号对应的 IVT 条目地址 = 0x0000:0000 + (向量号 × 4)
    //   例如：向量 0x10 的 IVT 条目在内存地址 0x0000:0040（0x10 × 4 = 0x40）
    // - 这是 x86 CPU 的硬件约定，在实模式下固定使用
    // - UEFI 在启动时也使用实模式和 IVT，但之后切换到保护模式/长模式，使用 IDT

    // 步骤 4: INT 60h-66h 保留给用户中断（设置为空，覆盖默认值）
    for (i=0x60; i<=0x66; i++)
        SET_IVT(i, SEGOFF(0, 0));  // 段:偏移 = 0:0（无效地址）

    // 步骤 5: 将向量 0x79 设置为 0（用于某些保护系统，覆盖默认值）
    SET_IVT(0x79, SEGOFF(0, 0));
    //
    // **总结：ivt_init() 为所有 256 个中断向量都设置了条目**
    // 1. 首先全部初始化为默认处理程序（entry_iret_official）
    // 2. 然后为特定的中断设置具体的处理程序（覆盖默认值）
    // 3. 有些向量被设置为空（0x60-0x66, 0x79），表示不使用
    // 4. 未明确设置的中断向量保持默认处理程序（entry_iret_official）
    //
    // **默认处理程序何时被替换为实际处理程序？**
    // 
    // 有两个层面的替换：
    // 
    // 1. BIOS 内部替换（在 ivt_init() 函数内部）：
    //    - 步骤 1：先为所有 256 个向量设置默认处理程序 entry_iret_official
    //    - 步骤 2-5：立即为特定的中断（BIOS 服务）设置实际处理程序，覆盖默认值
    //    - 所以对于 BIOS 服务中断（如 INT 10h, INT 13h），在 ivt_init() 执行完成后
    //      就已经是实际处理程序了（entry_10, entry_13_official 等）
    // 
    // 2. 内核接管替换（内核加载后）：
    //    - 内核早期启动时（startup_64）调用 idt_setup_early_traps() 建立 IDT
    //    - 内核建立自己的 IDT（中断描述符表），完全替换 BIOS 的 IVT
    //    - 此时所有中断都路由到内核的处理程序，BIOS 的 IVT 不再使用
    //    - 参见：linux/arch/x86/kernel/idt.c:216-227 (idt_setup_early_traps)
    //    - 参见：linux/arch/x86/kernel/idt.c:281-315 (idt_setup_apic_and_irq_gates)
}
```

**关键点：**
- **第 39-40 行**：**为所有 256 个中断向量都设置条目**，初始化为默认处理程序 `entry_iret_official`
  - `entry_iret_official`：直接执行 `IRET` 指令返回，不做任何处理
  - 这确保了即使发生未预期的中断，CPU 也能安全返回，不会崩溃
- **第 43-46 行**：**预先为 8259A PIC 的硬件中断向量设置处理程序**（覆盖默认值）
  - 向量 0x08-0x0F（IRQ0-7）→ `entry_hwpic1`（主 PIC 处理程序）
  - 向量 0x70-0x77（IRQ8-15）→ `entry_hwpic2`（从 PIC 处理程序）
  - **注意**：此时 PIC 还没有初始化，但先设置好处理程序，确保后续 PIC 初始化时如果发生中断，IVT 中已有有效处理程序
- **第 49-62 行**：设置软件中断处理程序（覆盖默认值），包括：
  - `INT 10h`：视频服务
  - `INT 13h`：磁盘服务（第 54 行）
  - `INT 15h`：系统服务
  - `INT 16h`：键盘服务
  - `INT 19h`：引导加载服务
  - 等等

> **详细说明**：关于 IVT 初始化的详细技术说明（包括初始化策略、默认处理程序、替换时机等），请参见 [BIOS 中断处理完整详解 - IVT 初始化详细说明](BIOS_INTERRUPT_COMPLETE.md#3-bios-中断向量表ivt初始化)。

**中断向量号 vs 内存地址：**

这些数字（如 `0x02`, `0x10`, `0x13`）是**中断向量号**（中断向量表的索引），不是内存地址。中断向量号对应的 IVT 条目地址计算公式为：`IVT 条目内存地址 = 0x0000:0000 + (中断向量号 × 4)`。

> **详细说明**：关于中断向量号与内存地址的详细解释（包括计算公式、示例、IVT 条目 vs 中断服务代码、内存布局示意等），请参见 [BIOS 中断处理完整详解 - 中断向量号 vs 内存地址详解](BIOS_INTERRUPT_COMPLETE.md#5-中断向量号-vs-内存地址详解)。

### 平台硬件设置（PIC 初始化）

**调用时机：** `platform_hardware_setup()` 在 `maininit()` 的"阶段 2"中被调用，位于 IVT 初始化之后、引导流程之前。

**调用位置：** `seabios/src/post.c:203`（在 `maininit()` 函数中）

**为什么 IVT 必须先于 PIC 初始化？**

IVT（中断向量表）和 PIC（可编程中断控制器）之间存在依赖关系，必须按正确顺序初始化：IVT 是中断处理的基础设施，PIC 初始化过程中可能触发中断，因此 IVT 必须先初始化。8259A PIC 只处理硬件中断（IRQ0-15），映射到向量 0x08-0x0F 和 0x70-0x77，而 CPU 有 256 个中断向量，其他中断（CPU 异常、软件中断、NMI 等）不经过 PIC。

> **详细说明**：关于 IVT 与 PIC 关系的详细解释（包括初始化顺序、协作关系、8259A PIC 覆盖范围、代码证据等），请参见 [BIOS 中断处理完整详解 - IVT 与 PIC 的关系详解](BIOS_INTERRUPT_COMPLETE.md#6-ivt-与-pic-的关系详解)。

源代码位置：`seabios/src/post.c:137-158`

```c
// 平台硬件设置：初始化 PC 基本硬件组件
// 这些函数按顺序执行，每个函数初始化特定的硬件子系统
static void
platform_hardware_setup(void)
{
    // 步骤 1: 设置 DMA（直接内存访问）控制器
    dma_setup();

    // 步骤 2: 初始化基础 PC 硬件
    pic_setup();      // 初始化 8259A 可编程中断控制器（PIC）
    thread_setup();   // 设置多线程支持
    mathcp_setup();   // 初始化数学协处理器（FPU）

    // 步骤 3: 平台特定设置
    qemu_platform_setup();      // QEMU 虚拟化平台特定初始化
    coreboot_platform_setup();   // Coreboot 固件平台特定初始化

    // 步骤 4: 设置定时器和周期性时钟中断
    timer_setup();   // 初始化定时器（8254 PIT）
    clock_setup();   // 设置时钟中断（IRQ0），每 55ms 触发一次

    // 步骤 5: 初始化 TPM（可信平台模块）
    tpm_setup();
}
```

> **详细说明**：关于 `platform_hardware_setup()` 的详细执行流程和函数调用顺序，请参见 [技术细节说明 - Note 4: platform_hardware_setup() 执行流程详解](BOOT_FLOW_NOTES.md#note-4-platform_hardware_setup-执行流程详解)。

**关键依赖关系：**
- `clock_setup()` **依赖** `timer_setup()` 和 `pic_setup()`（需要定时器和中断控制器已就绪）
- `qemu_platform_setup()` **依赖** 基础硬件已初始化（可能需要访问 I/O 端口）
- 所有函数**依赖** `dma_setup()`（避免 DMA 冲突）

**关键点：**
- `dma_setup()` 必须在最前面执行，避免 DMA 冲突
- `pic_setup()` 初始化中断控制器，后续中断相关初始化都依赖它
- `timer_setup()` 和 `clock_setup()` 必须按顺序执行，时钟中断依赖定时器

---

## BIOS 引导流程：从 SeaBIOS 到引导扇区

### BIOS 引导流程概述

SeaBIOS 完成初始化后，通过 INT 19h 引导加载服务启动引导过程，读取引导扇区并跳转执行。本节详细说明从 BIOS 到引导扇区的流程。

> **完整启动顺序**：这是简化版的高层概述。详细的完整流程（包含所有关键文件和源代码位置）请参见 [总结：完整流程时间线](#总结完整流程时间线) 部分。

```
SeaBIOS POST 完成
    ↓
调用 startBoot() → INT 19h
    ↓
INT 19h 处理程序（handle_19）
    ↓
选择引导设备（软盘/硬盘/CD-ROM）
    ↓
读取引导扇区到 0x7C00
    ↓
执行引导扇区代码（boot.S）
    ↓
引导扇区加载 GRUB Core（diskboot.S → startup_raw.S）
    ↓
GRUB Core 加载内核镜像
    ↓
跳转到内核入口点
```

### INT 19h 引导加载服务

**源代码位置：`seabios/src/post.c:182-193`**

```c
// 开始引导过程：在 16 位模式下调用 INT 19h
void VISIBLE32FLAT
startBoot(void)
{
    // 清除低内存分配（PMM 规范要求）
    memset((void*)BUILD_STACK_ADDR, 0, BUILD_EBDA_MINIMUM - BUILD_STACK_ADDR);

    dprintf(3, "Jump to int19\n");
    struct bregs br;
    memset(&br, 0, sizeof(br));
    br.flags = F_IF;  // 设置中断标志（允许中断）
    call16_int(0x19, &br);  // 调用 INT 19h 引导加载服务
}
```

**源代码位置：`seabios/src/boot.c:1040-1046`**

```c
// INT 19h 引导加载服务入口点
void VISIBLE32FLAT
handle_19(void)
{
    debug_enter(NULL, DEBUG_HDL_19);
    BootSequence = 0;  // 重置引导序列号
    do_boot(0);        // 从第一个引导设备开始尝试
}
```

### 引导设备选择和扇区读取

**源代码位置：`seabios/src/boot.c:882-917`**

```c
// 从磁盘引导（软盘或硬盘）
static void
boot_disk(u8 bootdrv, int checksig)
{
    u16 bootseg = 0x07c0;  // 引导扇区加载地址：段地址 0x07C0
                           // 物理地址 = 0x07C0 * 16 + 0x0000 = 0x7C00

    // 步骤 1: 使用 INT 13h 读取引导扇区（512 字节）
    struct bregs br;
    memset(&br, 0, sizeof(br));
    br.flags = F_IF;      // 允许中断
    br.dl = bootdrv;      // DL = 驱动器号（0x00 软盘，0x80 硬盘）
    br.es = bootseg;      // ES = 目标段地址（0x07C0）
    br.ah = 2;            // AH = 0x02：读扇区功能
    br.al = 1;            // AL = 读取扇区数（1 个扇区 = 512 字节）
    br.cl = 1;            // CL = 扇区号（第 1 个扇区）
    call16_int(0x13, &br);  // 调用 INT 13h 磁盘服务

    // 步骤 2: 检查读取是否成功
    if (br.flags & F_CF) {  // CF（进位标志）表示错误
        printf("Boot failed: could not read the boot disk\n\n");
        return;
    }

    // 步骤 3: 验证引导扇区签名（0xAA55）
    if (checksig) {
        struct mbr_s *mbr = (void*)0;  // 在段 0x07C0 的偏移 0 处
        if (GET_FARVAR(bootseg, mbr->signature) != MBR_SIGNATURE) {
            printf("Boot failed: not a bootable disk\n\n");
            return;
        }
    }

    // 步骤 4: 跳转到引导扇区程序执行（0x0000:0x7C00）
    u16 bootip = (bootseg & 0x0fff) << 4;
    bootseg &= 0xf000;
    call_boot_entry(SEGOFF(bootseg, bootip), bootdrv);
}
```

### BIOS 如何传递驱动器号给引导扇区程序

**关键点：** BIOS 在跳转到引导扇区时，需要将驱动器号传递给引导扇区程序，以便引导扇区程序知道从哪个存储设备加载后续代码。

**实现机制：** 通过 `call_boot_entry()` 函数将驱动器号设置到 DL 寄存器中。

**源代码位置：`seabios/src/boot.c:987-1000`**

```c
// 跳转到引导扇区入口点
static void
call_boot_entry(struct segoff_s bootsegip, u8 bootdrv)
{
    dprintf(1, "Booting from %04x:%04x\n", bootsegip.seg, bootsegip.offset);
    struct bregs br;
    memset(&br, 0, sizeof(br));
    br.flags = F_IF;        // 设置中断标志（允许中断）
    br.code = bootsegip;    // 设置跳转目标地址（CS:IP = 0x0000:0x7C00）
    br.dl = bootdrv;        // ← 关键：将驱动器号设置到 DL 寄存器
    br.ax = 0xaa55;         // 设置魔数（可选，用于验证）
    farcall16(&br);         // 执行远跳转，DL 寄存器包含驱动器号
}
```

**关键步骤：**

1. **第 1004 行**：`br.dl = bootdrv;` - 将驱动器号参数设置到 DL 寄存器
2. **第 1005 行**：`br.ax = 0xaa55;` - 设置魔数（引导扇区签名，用于验证）
3. **第 1006 行**：`farcall16(&br);` - 执行远跳转，此时 DL 寄存器已包含驱动器号

**驱动器号约定：**

| DL 值 | 存储设备类型 |
|-------|------------|
| `0x00` | 软盘 A（Floppy A） |
| `0x01` | 软盘 B（Floppy B） |
| `0x80` | 第一块硬盘 |
| `0x81` | 第二块硬盘 |
| `0x82` | 第三块硬盘 |
| ... | ... |

**引导扇区程序接收驱动器号：**

当引导扇区代码开始执行时，DL 寄存器已经包含了驱动器号：

```asm
// GRUB 引导扇区代码：grub/grub-core/boot/i386/pc/boot.S
_start:
    // BIOS 跳转到这里时，DL 寄存器包含驱动器号
    // 例如：DL = 0x80（第一块硬盘）
    
    // 保存启动驱动器号
    pushw   %dx             // 保存 DL（驱动器号）到栈
    
    // ... 后续代码使用保存的驱动器号读取 GRUB Core ...
    
    popw    %dx             // 恢复驱动器号到 DL
    movb    $0x42, %ah      // INT 13h 功能 0x42：扩展读
    int     $0x13           // 使用 DL 中的驱动器号读取扇区
```

**完整传递流程：**

```
boot_disk(0x80, 1)  // 调用时传入驱动器号 0x80
    ↓
call_boot_entry(SEGOFF(0x0000, 0x7C00), 0x80)
    ↓
br.dl = 0x80  // 将驱动器号设置到 DL 寄存器
    ↓
farcall16(&br)  // 执行远跳转
    ↓
跳转到 CS:IP = 0x0000:0x7C00
    ↓
引导扇区代码开始执行，DL = 0x80（驱动器号已传递）
```

**为什么需要传递驱动器号？**

1. **读取剩余代码**：引导扇区只有 512 字节，需要从同一个存储设备读取剩余的代码（如 GRUB Core）
2. **多设备支持**：系统可能有多个存储设备（硬盘、USB、软盘等），需要知道从哪个设备读取
3. **BIOS 协议约定**：这是 x86 BIOS 引导协议的标准约定，所有引导扇区程序都依赖这个约定

### BIOS 如何加载 Bootloader

引导扇区程序（512 字节）通常太小，无法直接加载内核，因此采用多阶段引导。本节详细说明 BIOS 如何加载 bootloader（以 GRUB 为例）。

**阶段 1：BIOS 加载引导扇区（MBR）**

**MBR 概述：**

- **位置**：MBR（Master Boot Record，主引导记录）存储在存储设备的第一个扇区（扇区0，LBA地址0）
- **大小**：512 字节（1 个扇区）
- **加载地址**：BIOS 通过 INT 13h 磁盘服务将引导扇区从存储设备读取到内存地址 `0x7C00`
- **加载方式**：这是**从存储设备到内存的拷贝过程**，不是映射

**不同存储设备的引导逻辑：**

| 存储设备类型 | 引导函数 | 加载地址 | 说明 |
|------------|---------|---------|------|
| **硬盘（Hard Disk）** | `boot_disk(0x80, 1)` | `0x7C00` | 固定地址，使用 INT 13h AH=0x02 |
| **软盘（Floppy）** | `boot_disk(0x00, CheckFloppySig)` | `0x7C00` | 固定地址，使用 INT 13h AH=0x02 |
| **USB 闪存（USB Flash Drive）** | `boot_disk(drive, 1)` | `0x7C00` | 被识别为可移动磁盘，逻辑与硬盘相同 |
| **光驱（CD-ROM）** | `boot_cdrom(drive)` | `CDEmu.load_segment`（通常是 `0x7C00`） | 使用 El Torito 标准，加载地址由标准指定 |

**关键点：**

1. **硬盘、软盘、USB 闪存**：
   - 都使用 `boot_disk()` 函数
   - 固定加载到 `0x7C00`
   - 使用 INT 13h AH=0x02（读扇区）从扇区 0 读取 512 字节
   - 这是**从存储设备到内存的拷贝过程**

2. **光驱（CD-ROM）**：
   - 使用 `boot_cdrom()` 函数
   - 遵循 El Torito 标准
   - 加载地址由 El Torito 引导记录中的 `load_segment` 字段指定
   - 通常也是 `0x7C00`，但可能不同（由光盘制作时指定）
   - 同样是从光盘到内存的拷贝过程

**SeaBIOS 源代码证据：**

```c
// SeaBIOS 源代码：src/boot.c:do_boot()
static void
do_boot(int seq_nr)
{
    struct bev_s *ie = &BEV[seq_nr];
    switch (ie->type) {
    case IPL_TYPE_FLOPPY:
        boot_disk(0x00, CheckFloppySig);  // 软盘：固定 0x7C00
        break;
    case IPL_TYPE_HARDDISK:
        boot_disk(0x80, 1);               // 硬盘：固定 0x7C00
        break;
    case IPL_TYPE_CDROM:
        boot_cdrom((void*)ie->vector);    // 光驱：由 El Torito 指定
        break;
    }
}

// 光驱引导：src/boot.c:boot_cdrom()
static void
boot_cdrom(struct drive_s *drive)
{
    cdrom_boot(drive);  // 读取 El Torito 引导记录
    u16 bootseg = CDEmu.load_segment;  // 加载地址由 El Torito 指定
    // ... 跳转到 bootseg:0x0000
}
```

> **详细说明**：关于 MBR 的位置、拷贝机制、目标地址设置的具体代码等详细内容，请参见 [Q&A：MBR在什么位置？BIOS读取MBR的过程是否把程序从磁盘copy到了内存？](#q-mbr在什么位置bios读取mbr的过程是否把程序从磁盘copy到了内存)

**MBR 结构（512 字节）：**
```
偏移      大小    内容
0x000     446     引导代码（第一阶段 bootloader）
0x1BE     16      分区表项 1
0x1CE     16      分区表项 2
0x1DE     16      分区表项 3
0x1EE     16      分区表项 4
0x1FE     2       引导签名（0xAA55）
```

**阶段 2：GRUB 引导扇区加载 GRUB Core**

**重要说明：** 引导扇区代码**不是 SeaBIOS 的一部分**。它是由 GRUB 安装程序（`grub-install`）写入磁盘第一个扇区的。SeaBIOS 只负责通过 INT 13h 读取这个扇区到 `0x7C00`，然后跳转执行。

**GRUB Core 加载流程：**

> **完整启动顺序**：请参见 [总结：完整流程时间线](#总结完整流程时间线) 部分。

```
1. BIOS 读取引导扇区（boot.S）到 0x7C00
    ↓
2. boot.S 读取第一个 GRUB Core 扇区（diskboot.S）到 0x8000
   ├─ 包含 diskboot.S 代码（约 0.5KB）
   └─ 包含块列表数据（12 字节，在末尾）
    ↓
3. boot.S 跳转到 0x8000（diskboot.S 入口）
    ↓
4. diskboot.S 执行（第一个 512 字节）
   ├─ 读取块列表（知道需要读取哪些扇区）
   ├─ 循环读取每个块列表条目指定的扇区
   │   ├─ 使用 INT 13h 读取扇区到临时缓冲区（0x7000）
   │   └─ 复制到目标地址（块列表中的 segment）
   └─ 所有扇区加载完成后，跳转到 0x8200
    ↓
5. startup_raw.S 执行（0x8200）
   ├─ 源代码位置：grub/grub-core/boot/i386/pc/startup_raw.S
   ├─ 切换到保护模式（calll real_to_prot）
   │   └─ 源代码位置：grub/grub-core/kern/i386/realmode.S
   ├─ 启用 A20 地址线（call grub_gate_a20）
   ├─ 处理 Reed-Solomon 错误纠正（如果启用）
   ├─ 解压 GRUB Core（如果使用 LZMA 压缩）
   │   └─ 调用 _LzmaDecodeA（lzma_decode.S 中的函数）
   │       ├─ 源代码位置：grub/grub-core/boot/i386/pc/lzma_decode.S
   │       └─ **lzma_decode.S 的加载时机**：
   │           - lzma_decode.S 通过 `#include "lzma_decode.S"` 被包含到 startup_raw.S 中
   │           - 编译时，lzma_decode.S 的代码被编译到 startup_raw.S 的目标文件中
   │           - 因此，lzma_decode.S 在**阶段 2**（diskboot.S 加载 GRUB Core）时
   │             随 startup_raw.S 一起被加载到内存 0x8200+
   │           - 包含位置：grub/grub-core/boot/i386/pc/startup_raw.S:359（include 语句）
   └─ 跳转到解压后的代码入口点（jmp *%esi）
    ↓
6. 解压后的代码入口点（_start，startup.S）
   ├─ 源代码位置：grub/grub-core/kern/i386/pc/startup.S
   ├─ 内存位置：0x100000（1MB，如果使用 LZMA 压缩）或 0x8000+（如果不使用 LZMA 压缩）
   ├─ 运行模式：保护模式
   ├─ 初始化 GRUB 核心功能：
   │   ├─ 内存管理初始化（grub_mm_init）
   │   ├─ 设备驱动初始化
   │   ├─ 文件系统驱动框架初始化
   │   └─ 其他核心功能初始化
   └─ 调用 grub_main()（grub/grub-core/kern/main.c）
    ↓
7. grub_main() 执行
   ├─ 源代码位置：grub/grub-core/kern/main.c
   ├─ 解析 grub.cfg 配置文件
   ├─ 显示启动菜单（如果配置）
   ├─ 用户选择启动 Linux 内核
   └─ 执行 linux 命令 → grub_cmd_linux()（grub/grub-core/loader/i386/linux.c）
    ↓
8. grub_cmd_linux() 加载内核镜像
   ├─ 源代码位置：grub/grub-core/loader/i386/linux.c
   ├─ 加载内核镜像到内存（0x100000）
   ├─ 设置内核启动参数（boot_params）
   └─ 注册启动函数 grub_linux_boot()
    ↓
9. grub_linux_boot() → grub_relocator32_boot()
   ├─ 源代码位置：grub/grub-core/loader/i386/linux.c
   └─ 按 boot_params 中 code32_start 字段所存地址跳转
    ↓
10. 内核开始执行
   ⚠️ **从 GRUB 启动时不执行 Setup**：GRUB 自填 boot_params 后按 code32_start 字段所存地址跳转（该地址处为压缩内核入口，32 位保护模式）。Setup（arch/x86/boot/）仅在**从扇区 0 启动**时执行；此时流程为：Setup（实模式）→ 切保护模式 → 读取 code32_start 字段值并跳转。
    ├─ 压缩内核入口（code32_start 字段所存地址处的代码，32 位保护模式）
    │   ├─ 源代码位置：linux/arch/x86/boot/compressed/head_64.S（如 startup_32）
    │   ├─ 内存位置：0x100000（1MB）+ 头部偏移
    │   ├─ 运行模式：32 位保护模式（GRUB/relocator 已设好 GDT、段、关分页）
    │   └─ 从 GRUB 进入时即由此处开始，不经过 Setup
    │       ↓
    ├─ 压缩内核解压代码（startup_32 等）
    │   ├─ 源代码位置：linux/arch/x86/boot/compressed/head_64.S
    │   ├─ 运行模式：32 位保护模式 → 64 位长模式
    │   ├─ 设置页表（身份映射：物理地址 = 线性地址）
    │   ├─ 切换到 64 位长模式
    │   ├─ 解压内核（gzip 解压）
    │   └─ 跳转到 startup_64
    │       ↓
    ├─ startup_64（64 位内核入口点）
    │   ├─ 源代码位置：linux/arch/x86/kernel/head_64.S
    │   ├─ 运行模式：64 位长模式
    │   ├─ 保存 boot_params 结构地址（%RSI → %R15）
    │   ├─ 设置初始内核栈
    │   ├─ 设置 GS 段基址（per-CPU 数据）
    │   ├─ 设置 GDT 和早期 IDT
    │   ├─ 切换到内核代码段（__KERNEL_CS）
    │   ├─ 激活内存加密（SEV/SME，如果支持）
    │   └─ 验证和清理 CPU 配置（verify_cpu）
    │       ↓
    └─ 内核继续初始化（x86_64_start_kernel）
        ├─ 源代码位置：linux/arch/x86/kernel/head64.c
        ├─ 设置早期中断处理程序（idt_setup_early_handler）
        │   └─ 源代码位置：linux/arch/x86/kernel/idt.c
        ├─ TDX 早期初始化（tdx_early_init，如果支持）
        ├─ 复制引导数据（copy_bootdata）
        ├─ 加载微码更新（load_ucode_bsp）
        ├─ 设置内核高地址映射
        └─ 启动内核预留区域初始化（x86_64_start_reservations）
            └─ 最终调用 start_kernel()
```

**GRUB 引导扇区代码的主要任务：**

**源代码位置：`grub/grub-core/boot/i386/pc/boot.S`**

1. **初始化环境**：设置段寄存器、栈指针
2. **检测磁盘访问模式**：尝试使用 LBA 模式，失败则回退到 CHS 模式
3. **读取 GRUB Core 第一个扇区**：从磁盘的特定扇区（`kernel_sector`）读取 GRUB Core 的第一个扇区（diskboot.S）到内存 `0x8000`
4. **跳转到 GRUB Core**：将控制权交给 GRUB Core（diskboot.S）

**boot.S 如何知道 GRUB Core 的位置？**

boot.S 通过 `kernel_sector` 字段知道 GRUB Core 第一个扇区的位置，然后通过两阶段机制加载完整的 GRUB Core：

**阶段 1：boot.S 读取 GRUB Core 第一个扇区（diskboot.S）**

1. **kernel_sector 字段**：
   - boot.S 中有一个 `kernel_sector` 字段，存储了 GRUB Core 第一个扇区的 LBA 扇区号
   - **字段位置**：
     - **标准模式**：偏移 0x5c（92 字节）
     - **HYBRID_BOOT 模式**：偏移 0x1b0（432 字节，用于 ISO 镜像）
   - **初始值**：编译时默认值为 `1`（占位符），实际安装时由 `grub-install` 覆盖为真实位置
   - **实际值示例**：
     - 传统磁盘安装：通常为扇区 2048 或更大
     - ISO 镜像（HYBRID_BOOT 模式）：例如扇区 11916（已验证）
   - **安装流程**：
     ```
     grub-install 安装流程：
     1. 编译 GRUB Core 镜像（core.img）
     2. 将 core.img 写入磁盘的特定扇区（例如传统磁盘为扇区 2048，ISO 镜像为扇区 11916）
     3. 记录这个扇区号（例如 2048 或 11916）
     4. 将扇区号写入 boot.S 的 kernel_sector 字段（覆盖默认值 1）
     5. 将修改后的 boot.S 写入磁盘第一个扇区（MBR 或 ISO 引导扇区）
     ```

2. **boot.S 读取 GRUB Core 的第一个扇区**：
   - boot.S 从 `kernel_sector` 字段读取扇区号
   - **读取流程（两阶段）**：
     1. **临时缓冲区**：使用 INT 13h 读取扇区到临时缓冲区 `0x7000:0x0000`（物理地址 `0x70000`）
     2. **最终地址**：从临时缓冲区复制到最终地址 `0x0000:0x8000`（物理地址 `0x8000`）
   - 这 512 字节包含：
     - `diskboot.S` 代码（约 0.5KB）
     - 块列表数据（12 字节，在末尾，文件偏移 `0x1F4-0x1FF`，对应内存地址 `0x81F4-0x81FF`）

**阶段 2：diskboot.S 使用块列表加载完整的 GRUB Core**

1. **块列表机制**：
   - GRUB Core 第一个扇区的末尾包含块列表（blocklist）
   - 块列表记录了 GRUB Core 镜像所有片段的物理扇区位置
   - 包括 startup_raw.S、C 代码、模块等所有组件的位置
   - 由 `grub-mkimage` 在安装时写入

2. **diskboot.S 加载流程**：
   - diskboot.S 读取块列表（从内存地址 `0x81F4` 开始，对应文件偏移 `0x1F4`）
   - **块列表结构**（已验证）：
     - 每个条目 12 字节：start（8 字节，LBA 扇区号）+ len（2 字节，扇区数）+ segment（2 字节，目标段地址）
     - **实际只有一个条目**（由于第一个扇区只有 12 字节空间，详见下文）
     - 条目示例（ISO 镜像）：start=11917, len=56, segment=0x0820
   - 处理块列表条目：
     - 读取条目指定的扇区（使用 INT 13h，先读到临时缓冲区 `0x7000:0x0000`）
     - 复制到目标内存地址（由 segment 字段指定，例如 segment=0x0820 对应物理地址 `0x8200`）
   - 所有扇区加载完成后，跳转到 0x8200（startup_raw.S 入口点）
   - **关键代码验证**（通过 objdump 反汇编确认）：
     - `mov di,0x81f4`：设置 DI 指向块列表位置
     - `int 0x13`：调用 INT 13h 读取扇区
     - `jmp 0x0:0x8200`：跳转到 startup_raw.S 入口点

**关键点总结：**
- **boot.S 只知道 GRUB Core 第一个扇区的位置**：通过 `kernel_sector` 字段（由 grub-install 写入）
- **GRUB Core 第一个扇区包含块列表**：记录了完整的 GRUB Core 位置（包括 startup_raw.S）
- **diskboot.S 使用块列表**：加载完整的 GRUB Core，包括 startup_raw.S
- **这是两阶段机制**：boot.S → diskboot.S → startup_raw.S，每个阶段知道下一阶段的位置

**GRUB 引导扇区代码实现：**

**关键代码解析：**

```asm
// grub/grub-core/boot/i386/pc/boot.S:124-483

_start:
start:
    // GRUB 引导扇区从 0x7C00 开始执行
    // BIOS 跳转到这里时：CS:IP = 0:0x7C00
    // **重要：此时 DL 寄存器包含驱动器号（BIOS 传递的）**
    // DL = 0x00（软盘）或 0x80（第一块硬盘）等
    
    // 步骤 1: 关闭中断，设置段寄存器
    cli                     // 关闭中断（此时还不安全）
    
    // 修复某些 BIOS 的 bug：如果 DL 寄存器值不正确，设置为 0x80（第一个硬盘）
    // **注意：这里访问 DL 寄存器，说明引导扇区程序知道驱动器号**
    testb   $0x80, %dl      // 检查是否是硬盘（0x80-0x8F）
    jz      2f
    testb   $0x70, %dl      // 忽略无效的驱动器号
    jz      1f
2:
    movb    $0x80, %dl      // 强制设置为第一个硬盘
1:
    // 长跳转：修复某些 BIOS 跳转到 07C0:0000 而不是 0000:7C00 的问题
    ljmp    $0, $real_start

real_start:
    // 步骤 2: 设置数据段和栈段
    xorw    %ax, %ax
    movw    %ax, %ds        // 数据段 = 0
    movw    %ax, %ss        // 栈段 = 0
    movw    $GRUB_BOOT_MACHINE_STACK_SEG, %sp  // 栈指针 = 0x2000
    sti                     // 重新启用中断
    
    // 步骤 3: 保存启动驱动器号
    // **关键：保存 DL 寄存器中的驱动器号，后续读取 GRUB Core 时需要用到**
    pushw   %dx             // 保存 DL（驱动器号）到栈
    
    // 步骤 4: 显示 "GRUB " 消息
    MSG(notification_string)  // 调用消息打印函数
    
    // 步骤 5: 检测是否支持 LBA 模式
    // **注意：此时 DL 寄存器仍包含 BIOS 传递的驱动器号（pushw %dx 只是保存到栈，不改变 DL）**
    movw    $disk_address_packet, %si  // 设置磁盘地址包指针
    movb    $0x41, %ah      // INT 13h 功能 0x41：检查扩展磁盘访问
    movw    $0x55aa, %bx    // 签名
    int     $0x13           // **使用 DL 中的驱动器号检测 LBA 支持**
    
    jc      LOCAL(chs_mode)  // 如果失败，使用 CHS 模式
    cmpw    $0xaa55, %bx    // 验证签名
    jne     LOCAL(chs_mode)  // 如果不匹配，使用 CHS 模式
    
    // 步骤 6: 使用 LBA 模式读取 GRUB Core
LOCAL(lba_mode):
    // 准备磁盘地址包（Disk Address Packet, DAP）
    movw    $0x0010, (%si)  // DAP 大小 = 16 字节
    movw    $1, 2(%si)      // 读取 1 个扇区
    movw    $GRUB_BOOT_MACHINE_BUFFER_SEG, 6(%si)  // 缓冲区段 = 0x7000
    
    // 设置要读取的扇区号（从引导扇区的 kernel_sector 字段读取）
    movl    LOCAL(kernel_sector), %ebx      // 低 32 位扇区号
    movl    %ebx, 8(%si)                    // 写入 DAP
    movl    LOCAL(kernel_sector_high), %ebx // 高 32 位扇区号
    movl    %ebx, 12(%si)                   // 写入 DAP
    
    // 调用 INT 13h 扩展读（AH=0x42）
    // **注意：此时 DL 寄存器仍包含驱动器号（之前保存的）**
    movb    $0x42, %ah      // INT 13h 功能 0x42：扩展读
    int     $0x13           // **使用 DL 中的驱动器号读取扇区到 0x7000:0x0000**
    
    jc      LOCAL(chs_mode)  // 如果失败，回退到 CHS 模式
    movw    $GRUB_BOOT_MACHINE_BUFFER_SEG, %bx
    jmp     LOCAL(copy_buffer)
    
    // 步骤 7: 使用 CHS 模式读取（如果 LBA 不支持）
LOCAL(chs_mode):
    // 获取磁盘几何信息（柱面、磁头、扇区数）
    movb    $8, %ah         // INT 13h 功能 0x08：获取磁盘参数
    int     $0x13
    jnc     LOCAL(final_init)
    
    // 如果失败且是软盘，尝试软盘探测
    popw    %dx
    testb   %dl, %dl        // DL = 0 表示软盘
    jnb     LOCAL(floppy_probe)
    
    // 硬盘探测失败，显示错误
    ERR(hd_probe_error_string)

LOCAL(final_init):
    // 计算 CHS 地址（柱面、磁头、扇区）
    // 将 kernel_sector（LBA）转换为 CHS 格式
    movl    LOCAL(kernel_sector), %eax
    xorl    %edx, %edx
    divl    (%si)           // 除以每柱面扇区数，得到扇区号
    movb    %dl, %cl        // 保存扇区号（在 CL 的低 6 位）
    
    xorw    %dx, %dx
    divl    4(%si)          // 除以磁头数，得到柱面号
    movb    %al, %ch        // 柱面号的低 8 位
    movb    %dl, %dh        // 磁头号
    
    // 调用 INT 13h 标准读（AH=0x02）
    popw    %dx             // **恢复驱动器号到 DL，用于 INT 13h 读取**
    movw    $GRUB_BOOT_MACHINE_BUFFER_SEG, %bx
    movw    %bx, %es        // 设置目标段
    xorw    %bx, %bx        // 偏移 = 0
    movw    $0x0201, %ax    // 功能 0x02，读取 1 个扇区
    int     $0x13           // **使用 DL 中的驱动器号读取扇区到 0x7000:0x0000**
    
    jc      LOCAL(read_error)
    movw    %es, %bx

    // 步骤 8: 将 GRUB Core 从缓冲区复制到最终地址
LOCAL(copy_buffer):
    // **关键：两阶段读取流程（已验证）**
    // 阶段 1：INT 13h 读取到临时缓冲区 0x7000:0x0000（物理地址 0x70000）
    // 阶段 2：从临时缓冲区复制到最终地址 0x0000:0x8000（物理地址 0x8000）
    // 
    // 从 0x7000:0x0000 复制到 0x0000:0x8000（GRUB_BOOT_MACHINE_KERNEL_ADDR）
    pusha
    pushw   %ds
    
    movw    $0x100, %cx     // 复制 512 字节（0x100 字）
    movw    %bx, %ds        // 源段 = 0x7000（临时缓冲区段）
    xorw    %si, %si        // 源偏移 = 0
    movw    $GRUB_BOOT_MACHINE_KERNEL_ADDR, %di  // 目标偏移 = 0x8000
    movw    %si, %es        // 目标段 = 0x0000
    
    cld                     // 方向标志：向前
    rep movsw               // 重复复制字（DS:SI -> ES:DI）
                           // 从 0x7000:0x0000 复制到 0x0000:0x8000
    
    popw    %ds
    popa
    
    // 步骤 9: 跳转到 GRUB Core
    // **关键代码：跳转到 0x8000（GRUB Core 入口点）**
    jmp     *(LOCAL(kernel_address))  // 间接跳转：从 LOCAL(kernel_address) 读取地址并跳转
                                       // 等价于：jmp 0x8000
                                       // 此时 GRUB Core 的第一个扇区（diskboot.S）已加载到 0x8000
                                       //
                                       // **跳转指令执行过程：**
                                       // 1. CPU 读取 LOCAL(kernel_address) 标签处的内存值（0x8000）
                                       //    - LOCAL(kernel_address) 是一个标签，指向内存中的一个位置
                                       //    - 这个位置存储的值是 GRUB_BOOT_MACHINE_KERNEL_ADDR（0x8000）
                                       // 2. CPU 跳转到该地址（0x8000）
                                       // 3. 此时 CS:IP = 0x0000:0x8000（物理地址 0x8000）
                                       // 4. diskboot.S 代码从 0x8000 开始执行
                                       //
                                       // **标签 vs 存储值的区别：**
                                       // - LOCAL(kernel_address)：标签（内存地址），指向存储值的位置
                                       // - GRUB_BOOT_MACHINE_KERNEL_ADDR：存储的值（0x8000），是跳转目标地址
                                       // - jmp *(LOCAL(kernel_address))：间接跳转，从标签指向的位置读取值，然后跳转

// 关键数据定义
LOCAL(kernel_address):
    .word   GRUB_BOOT_MACHINE_KERNEL_ADDR  // 0x8000：GRUB Core 加载地址
                                           // **这个值定义了跳转目标地址**
                                           // GRUB_BOOT_MACHINE_KERNEL_ADDR 宏定义为 0x8000
                                           // 跳转指令从内存中读取这个值（0x8000），然后跳转到该地址
                                           //
                                           // **为什么选择 0x8000 作为 GRUB Core 加载地址？**
                                           // 1. 避免与引导扇区冲突：
                                           //    - 引导扇区在 0x7C00-0x7DFF（512 字节）
                                           //    - 0x8000 紧接引导扇区之后，不重叠
                                           // 2. 内存布局设计：
                                           //    - 0x0000-0x7BFF：BIOS 数据区、栈等（已使用）
                                           //    - 0x7C00-0x7DFF：引导扇区（512 字节）
                                           //    - 0x8000+：GRUB Core（可用空间）
                                           // 3. 实模式地址空间限制：
                                           //    - 实模式只能访问前 1MB（0x000000-0xFFFFF）
                                           //    - 0x8000 在实模式可访问范围内
                                           //    - 0x8000-0x9FFF 提供约 8KB 空间，足够 GRUB Core 初始阶段使用
                                           // 4. 历史约定：
                                           //    - 这是 x86 BIOS 引导协议的标准约定
                                           //    - 许多 bootloader 都使用 0x8000 作为第二阶段加载地址
                                           //
                                           // **内存布局：**
                                           // 这个 .word 指令在编译时会在引导扇区中分配 2 字节
                                           // 存储值 0x8000（小端序：0x00 0x80）
                                           // 跳转指令读取这 2 字节，得到地址 0x8000，然后跳转

LOCAL(kernel_sector):
    .long   1               // GRUB Core 第一个扇区号（LBA，由 grub-install 写入）
                            // **初始值说明：**
                            // - 编译时默认值为 1，表示第二个扇区（扇区 0 是 boot.S 自己）
                            // - LBA 扇区号从 0 开始：扇区 0 = 第一个扇区，扇区 1 = 第二个扇区
                            // - 这个初始值只是占位符，实际安装时会被 grub-install 覆盖
                            // - grub-install 会将 GRUB Core 的实际扇区号（例如 2048）写入此字段
                            // **关键：这是 boot.S 如何知道 GRUB Core 位置的机制**
                            // 1. grub-install 安装时，将 GRUB Core 写入磁盘的特定扇区
                            // 2. grub-install 记录这个扇区号，写入 boot.S 的 kernel_sector 字段
                            // 3. boot.S 读取这个字段，知道从哪个扇区读取 GRUB Core 的第一个扇区
                            // 4. 第一个扇区包含 diskboot.S 和块列表，块列表记录了完整的 GRUB Core 位置
LOCAL(kernel_sector_high):
    .long   0               // 高 32 位扇区号（用于大磁盘，支持超过 2TB 的磁盘）

notification_string:
    .asciz "GRUB "          // 启动时显示的消息
```

**关键地址和常量：**

- **`GRUB_BOOT_MACHINE_KERNEL_ADDR`**：`0x8000` - GRUB Core 加载地址
- **`GRUB_BOOT_MACHINE_BUFFER_SEG`**：`0x7000` - 临时缓冲区段（读取扇区时使用）
- **`GRUB_BOOT_MACHINE_STACK_SEG`**：`0x2000` - 栈段地址
- **`kernel_sector`**：GRUB Core 第一个扇区号（由 `grub-install` 在安装时写入）

**HYBRID_BOOT 模式说明：**

GRUB 支持两种引导模式，`kernel_sector` 字段的位置不同：

1. **标准模式（非 HYBRID_BOOT）**：
   - `kernel_sector` 字段位于偏移 **0x5c**（92 字节）
   - 用于传统的磁盘安装（硬盘、USB 驱动器等）
   - 这是默认模式

2. **HYBRID_BOOT 模式**：
   - `kernel_sector` 字段位于偏移 **0x1b0**（432 字节）
   - 用于 ISO 镜像、混合引导等特殊场景
   - 编译时通过 `-DHYBRID_BOOT=1` 启用（参见 `grub/grub-core/Makefile.core.def:478`）

**源代码位置：`grub/grub-core/boot/i386/pc/boot.S`**

```asm
// 标准模式：kernel_sector 在偏移 0x5c
#ifndef HYBRID_BOOT
    .org GRUB_BOOT_MACHINE_KERNEL_SECTOR  // 0x5c
LOCAL(kernel_sector):
    .long   1
LOCAL(kernel_sector_high):
    .long   0
#endif

// HYBRID_BOOT 模式：kernel_sector 在偏移 0x1b0
#ifdef HYBRID_BOOT
    .org 0x1b0
LOCAL(kernel_sector):
    .long   1
LOCAL(kernel_sector_high):
    .long   0
#endif
```

**为什么需要 HYBRID_BOOT 模式？**

- **ISO 镜像引导**：ISO 镜像使用 El Torito 标准，引导扇区结构与传统 MBR 不同
- **混合引导**：支持同时从磁盘和 ISO 镜像引导
- **字段位置冲突**：标准位置的 `kernel_sector` 可能与 ISO 镜像的其他数据结构冲突，因此需要放在不同的位置（0x1b0）

**如何判断使用哪种模式？**

- 检查引导扇区偏移 0x5c 和 0x1b0 的值
- 如果偏移 0x1b0 有有效的扇区号（1-100000），且偏移 0x5c 为 0，则使用 HYBRID_BOOT 模式
- ISO 镜像通常使用 HYBRID_BOOT 模式

**从 boot.S 到 diskboot.S 的过渡：**

`boot.S` 读取 `kernel_sector` 后，会使用 BIOS INT 13h 将 GRUB Core 的第一个扇区（`diskboot.S`）加载到内存地址 `0x8000`，然后跳转到该地址执行。

**diskboot.S 的作用：**

`diskboot.S` 是 GRUB Core 的第一个扇区（512 字节），它的主要任务是：

1. **加载 core.img 的剩余部分**：`boot.S` 只加载了 `core.img` 的第一个扇区，`diskboot.S` 需要加载剩余的扇区
2. **使用块列表定位数据**：由于 `core.img` 可能分散在磁盘的不同位置（不连续），`diskboot.S` 使用**块列表（blocklist）**机制来定位和加载这些扇区
3. **跳转到 startup_raw.S**：加载完成后，跳转到 `startup_raw.S`（位于 `0x8200`）继续执行

**diskboot.S 跳转到 startup_raw.S 的代码：**

**源代码位置：** `grub/grub-core/boot/i386/pc/diskboot.S:310-320`

当所有块列表条目处理完成后（遇到 `len = 0` 的结束标记），`diskboot.S` 会跳转到 `LOCAL(bootit)` 标签，执行跳转到 `startup_raw.S` 的代码：

```asm
// grub/grub-core/boot/i386/pc/diskboot.S:310-320
LOCAL(bootit):
    // 所有块列表条目处理完成，准备跳转到 startup_raw.S
    // startup_raw.S 位于内存地址 0x8200
    // GRUB_BOOT_MACHINE_KERNEL_SEG = 0x0000
    // GRUB_BOOT_MACHINE_KERNEL_ADDR = 0x8000
    // startup_raw.S 入口点 = 0x8000 + 0x200 = 0x8200
    
    // 设置段寄存器
    movw    $GRUB_BOOT_MACHINE_KERNEL_SEG, %ax  // %ax = 0x0000
    movw    %ax, %ds                              // 数据段 = 0x0000
    movw    %ax, %ss                              // 栈段 = 0x0000
    
    // 跳转到 startup_raw.S 入口点（0x0000:0x8200）
    // 使用长跳转（ljmp）跳转到段地址 0x0000，偏移 0x8200
    ljmp    $GRUB_BOOT_MACHINE_KERNEL_SEG, $(GRUB_BOOT_MACHINE_KERNEL_ADDR + 0x200)
    // 等价于：ljmp $0x0000, $0x8200
    // 这会跳转到物理地址 0x8200，即 startup_raw.S 的入口点（LOCAL(codestart)）
```

**关键点：**
- **跳转目标**：`0x0000:0x8200`（物理地址 `0x8200`）
- **对应代码**：`startup_raw.S` 的 `LOCAL(codestart)` 标签
- **跳转方式**：使用 `ljmp`（长跳转）指令，同时设置代码段和指令指针
- **执行时机**：所有块列表条目处理完成后，所有 `core.img` 的剩余部分都已加载到内存

**diskboot.S 的最终执行目的：**

`diskboot.S` 的最终目的是将完整的 `core.img` 加载到内存中，然后跳转到 `startup_raw.S` 执行。`startup_raw.S` 会切换到保护模式、启用 A20 地址线、解压 LZMA 压缩的 C 代码，最终启动 GRUB 的核心功能。

**diskboot.S 的内部执行顺序：**

1. **初始化**：设置段寄存器，准备读取块列表
2. **遍历块列表**：从扇区末尾（偏移 0x1F4）读取块列表，逐个处理每个条目
3. **读取数据块**：对每个块列表条目：
   - 读取 `start` 字段获取起始扇区号
   - 读取 `len` 字段获取要读取的扇区数
   - 使用 BIOS INT 13h 读取扇区到临时缓冲区（`0x7000:0x0000`）
   - 读取 `segment` 字段获取目标内存段地址
   - 将数据从临时缓冲区复制到目标地址
4. **检查结束**：如果 `len = 0`，表示块列表结束
5. **跳转执行**：跳转到 `startup_raw.S`（`0x8200`）继续执行

**块列表机制：**

块列表存储在 `diskboot.S` 扇区的末尾（偏移 0x1F4-0x1FF），每个条目包含：
- **起始扇区号**（LBA）：要读取的数据在磁盘上的起始位置
- **扇区数**：要读取的扇区数量
- **目标内存段地址**：数据加载到内存的哪个段地址

`diskboot.S` 会遍历块列表，使用 BIOS INT 13h 逐个读取每个块，直到遇到 `len = 0` 的条目（表示块列表结束）。

**块列表中的数据内容：**

块列表中指向的扇区包含 `core.img` 的剩余部分，具体包括：
- **startup_raw.S**：实模式启动代码，负责切换到保护模式、启用 A20、解压 LZMA 压缩代码
- **LZMA 压缩的 C 代码**：GRUB 的核心功能代码（文件系统驱动、命令解析器等），压缩后约 24KB
- **其他模块和数据**：GRUB 运行时需要的其他二进制数据

这些数据在编译时由 `grub-mkimage` 工具打包成 `core.img`，并生成相应的块列表条目，记录每个数据块在磁盘上的位置和目标内存地址。

> **详细说明**：关于 `core.img` 的内部结构、`grub-mkimage` 构建过程、块列表机制的详细分析，请参见 [GRUB_CORE_IMG_STRUCTURE.md](GRUB_CORE_IMG_STRUCTURE.md)。

**如何从源代码推断入口点是 startup_raw.S：**

虽然 `setup.c` 中没有明确的注释说明"这就是 startup_raw.S 的入口点"，但可以通过以下方式推断：

**1. diskboot.S 的跳转目标：**

```asm
// grub/grub-core/boot/i386/pc/diskboot.S:310-320
ljmp    $GRUB_BOOT_MACHINE_KERNEL_SEG, $(GRUB_BOOT_MACHINE_KERNEL_ADDR + 0x200)
// 等价于：ljmp $0x0000, $0x8200
// 跳转到物理地址 0x8200
```

**2. startup_raw.S 的入口点定义：**

```asm
// grub/grub-core/boot/i386/pc/startup_raw.S:76-104
LOCAL (codestart):  // 这是 startup_raw.S 的入口点
    cli     // 禁用中断，准备模式切换
    // ...
```

**为什么 `LOCAL(codestart)` 标签位于 0x8200：**

`LOCAL(codestart)` 位于 0x8200 的原因是由 `core.img` 的文件布局和加载地址决定的：

**1. core.img 的文件布局（由 grub-mkimage 构建）：**

```
core.img 文件布局：
├─ 文件偏移 0x0000 - 0x01FF（第一个扇区，512 字节）：
│  └─ diskboot.S 代码 + 块列表
│
└─ 文件偏移 0x0200+（第二个扇区开始）：
   └─ startup_raw.S（LOCAL(codestart) 标签在文件偏移 0x0200）
      └─ 紧接其后：C 代码部分（LZMA 压缩）
```

**2. core.img 加载到内存后的地址映射：**

```
core.img 加载到内存 0x8000 后：
├─ 内存地址 0x8000 - 0x81FF（对应文件偏移 0x0000 - 0x01FF）：
│  └─ diskboot.S 代码 + 块列表
│
└─ 内存地址 0x8200+（对应文件偏移 0x0200+）：
   └─ startup_raw.S（LOCAL(codestart) 标签在内存地址 0x8200）
```

**3. 地址计算过程：**

- **core.img 加载地址**：`GRUB_BOOT_MACHINE_KERNEL_ADDR = 0x8000`
- **startup_raw.S 在 core.img 中的文件偏移**：0x0200（第二个扇区开始）
- **startup_raw.S 在内存中的地址**：0x8000 + 0x0200 = **0x8200**
- **`LOCAL(codestart)` 标签**：位于 `startup_raw.S` 的开头，所以也在 0x8200

**4. 在源代码中的体现：**

虽然 `startup_raw.S` 源代码中没有明确的 ORG 指令指定它在 0x8200，但通过以下方式可以确定：

**方法 1：通过 diskboot.S 的跳转目标**

```asm
// grub/grub-core/boot/i386/pc/diskboot.S:310-320
ljmp    $GRUB_BOOT_MACHINE_KERNEL_SEG, $(GRUB_BOOT_MACHINE_KERNEL_ADDR + 0x200)
// 跳转到：0x8000 + 0x200 = 0x8200
```

- `diskboot.S` 跳转到 `GRUB_BOOT_MACHINE_KERNEL_ADDR + 0x200 = 0x8200`
- 说明下一个代码段（startup_raw.S）从 0x8200 开始

**方法 2：通过 core.img 的文件布局**

- `diskboot.S` 是 `core.img` 的第一个扇区（文件偏移 0x0000-0x01FF）
- `startup_raw.S` 紧接其后（文件偏移 0x0200+）
- 加载到内存 0x8000 后，文件偏移对应内存偏移
- 所以 `startup_raw.S` 在内存中的地址 = 0x8000 + 0x0200 = 0x8200

**方法 3：通过块列表的 segment 字段**

```c
// grub/util/setup.c
bl->current_segment = GRUB_BOOT_MACHINE_KERNEL_SEG + 0x20;  // 0x0820
// segment = 0x0820 → 物理地址 = 0x0820 × 16 = 0x8200
```

- 块列表的 segment = 0x0820，对应物理地址 0x8200
- 这正好是 `startup_raw.S` 的入口点位置

**结论：**

`LOCAL(codestart)` 位于 0x8200 是因为：
1. **`core.img` 的文件布局**：`startup_raw.S` 在文件偏移 0x0200（第二个扇区开始）
2. **加载地址**：`core.img` 加载到内存 0x8000
3. **地址映射**：文件偏移 0x0200 → 内存地址 0x8000 + 0x0200 = 0x8200
4. **标签位置**：`LOCAL(codestart)` 位于 `startup_raw.S` 的开头，所以也在 0x8200

这是由 `grub-mkimage` 构建 `core.img` 时的文件布局和加载地址共同决定的，而不是 `startup_raw.S` 源代码中的明确指定。

**源代码确认：**

通过查看 GRUB 源代码，可以确认 `startup_raw.S` 位于 0x8200 是**源代码中明确指定的**：

**1. `startup_raw.S` 源代码中的明确说明：**

```asm
// grub/grub-core/boot/i386/pc/startup_raw.S:26
#define ABS(x)	((x) - LOCAL (base) + GRUB_BOOT_MACHINE_KERNEL_ADDR + 0x200)
```

这个宏定义明确显示了地址计算：`GRUB_BOOT_MACHINE_KERNEL_ADDR + 0x200`，也就是 `0x8000 + 0x200 = 0x8200`。

```asm
// grub/grub-core/boot/i386/pc/startup_raw.S:41
/*
 *  Guarantee that "main" is loaded at 0x0:0x8200.
 */
```

这个注释明确说明了 `startup_raw.S` 被保证加载到 `0x8200`。

**2. `diskboot.S` 源代码中的跳转目标：**

```asm
// grub/grub-core/boot/i386/pc/diskboot.S:301
ljmp	$0, $(GRUB_BOOT_MACHINE_KERNEL_ADDR + 0x200)
```

这确认了 `diskboot.S` 跳转到 `0x8200`。

**3. `grub-mkimage` 源代码中的验证：**

```c
// grub/util/mkimage.c:1367-1369
assert (block->segment
        == grub_host_to_target16 (GRUB_BOOT_I386_PC_KERNEL_SEG
                                  + (GRUB_DISK_SECTOR_SIZE >> 4)));
```

这个断言验证了块列表的 segment 字段必须是 `GRUB_BOOT_I386_PC_KERNEL_SEG + 0x20`（因为 `GRUB_DISK_SECTOR_SIZE >> 4 = 512 >> 4 = 32 = 0x20`）。

如果 `GRUB_BOOT_I386_PC_KERNEL_SEG = 0x0000`（对应物理地址 0x8000），那么 segment = 0x0820，对应物理地址 0x8200。

**4. `grub-mkimage` 源代码中的大小检查：**

```c
// grub/util/mkimage.c:1221
if ((image_target->id == IMAGE_I386_PC
     || image_target->id == IMAGE_I386_PC_PXE
     || image_target->id == IMAGE_I386_PC_ELTORITO)
    && decompress_size > GRUB_KERNEL_I386_PC_LINK_ADDR - 0x8200)
  grub_util_error ("%s", _("Decompressor is too big"));
```

这里明确使用了 `0x8200` 作为地址边界进行检查。

**结论：**

`startup_raw.S` 位于 0x8200 **不是推断，而是源代码中明确指定的**：
1. `startup_raw.S` 源代码中的宏定义和注释明确说明了 0x8200 的地址
2. `diskboot.S` 源代码中的跳转目标明确指向 0x8200
3. `grub-mkimage` 源代码中的断言和检查明确使用了 0x8200 作为地址边界

因此，`LOCAL(codestart)` 位于 0x8200 是由源代码设计决定的，而不是通过推断得出的。

**3. 如何推断 startup_raw.S 在第二个扇区开始：**

**方法 1：通过 diskboot.S 的跳转目标推断**

```asm
// grub/grub-core/boot/i386/pc/diskboot.S:310-320
ljmp    $GRUB_BOOT_MACHINE_KERNEL_SEG, $(GRUB_BOOT_MACHINE_KERNEL_ADDR + 0x200)
// 跳转到：0x8000 + 0x200 = 0x8200
```

- **0x200 = 512 字节 = 一个扇区**
- **0x8200 = 0x8000 + 0x200** = 第一个扇区结束 + 第二个扇区开始
- **diskboot.S 跳转到 0x8200**，说明下一个代码段从 0x8200 开始

**方法 2：通过内存布局推断**

```
core.img 的内存布局（加载到 0x8000 后）：
├─ 第一个扇区（512 字节 = 0x200）：
│  └─ 0x8000 - 0x81FF：diskboot.S 代码 + 块列表
│
└─ 第二个扇区开始：
   └─ 0x8200+：startup_raw.S（LOCAL(codestart) 标签）
```

- **第一个扇区**：0x8000-0x81FF（512 字节）
- **第二个扇区开始**：0x8200 = 0x8000 + 0x200
- **startup_raw.S 的入口点**：`LOCAL(codestart)` 位于 0x8200

**方法 3：通过块列表的 segment 字段推断**

```c
// grub/util/setup.c
bl->current_segment = GRUB_BOOT_MACHINE_KERNEL_SEG + 0x20;  // 0x0820
// segment = 0x0820 → 物理地址 = 0x0820 × 16 = 0x8200
```

- **块列表的 segment = 0x0820**，对应物理地址 0x8200
- **0x8200 = 0x8000 + 0x200**，正好是第二个扇区开始

**结论：**

虽然 `startup_raw.S` 源代码中没有明确的注释说明"这是第二个扇区开始"，但可以通过以下证据推断：

1. **diskboot.S 跳转到**：`0x8200`（`GRUB_BOOT_MACHINE_KERNEL_ADDR + 0x200`）
2. **0x200 = 512 字节 = 一个扇区**，所以 0x8200 是第一个扇区（0x8000-0x81FF）之后的位置
3. **startup_raw.S 的入口点**：`LOCAL(codestart)` 标签，位于 0x8200
4. **块列表 segment**：0x0820，对应物理地址 0x8200

因此，**startup_raw.S 的入口点确实在第二个扇区开始（0x8200）**，这是通过地址计算和跳转目标推断出来的。

**4. 地址对应关系：**

- **diskboot.S 跳转目标**：`GRUB_BOOT_MACHINE_KERNEL_ADDR + 0x200 = 0x8000 + 0x200 = 0x8200`
- **startup_raw.S 入口点**：`LOCAL(codestart)` 标签，位于 `core.img` 的第二个扇区开始
- **内存布局**：
  - 第一个扇区（diskboot.S）：0x8000-0x81FF（512 字节）
  - 第二个扇区开始（startup_raw.S）：0x8200+（正好是 `0x8000 + 0x200`）

**4. 块列表的 segment 字段：**

```c
// grub/util/setup.c
bl->current_segment = GRUB_BOOT_MACHINE_KERNEL_SEG + 0x20;  // 0x0820
bl->block->segment = grub_host_to_target16 (bl->current_segment);  // 0x0820
// segment = 0x0820 → 物理地址 = 0x0820 × 16 = 0x8200
```

**结论：**

虽然源代码中没有明确的注释说明"segment = 0x0820 就是 startup_raw.S 的入口点"，但通过以下证据可以推断：

1. **diskboot.S 跳转到**：`0x8200`（`GRUB_BOOT_MACHINE_KERNEL_ADDR + 0x200`）
2. **startup_raw.S 入口点**：`LOCAL(codestart)`，位于 `core.img` 第二个扇区开始（0x8200）
3. **块列表 segment**：0x0820，对应物理地址 0x8200
4. **内存布局**：0x8200 正好是第一个扇区（512 字节 = 0x200）之后的位置

因此，**0x8200 就是 startup_raw.S 的入口点**，这是通过地址计算和跳转目标推断出来的，而不是源代码中的明确注释。

**计算过程：**
- **物理地址**：0x8200（即 `GRUB_BOOT_MACHINE_KERNEL_ADDR + 0x200`）
- **段地址计算**：物理地址 ÷ 16 = 0x8200 ÷ 16 = 0x0820
- **验证**：0x0820 × 16 = 0x8200 ✓

**2. 更新逻辑：**

每次处理完一个块列表条目后，`current_segment` 会更新：

```c
// 更新目标段地址
// seclen：刚处理的扇区数（例如：56）
// GRUB_DISK_SECTOR_BITS = 9（因为 512 字节 = 2^9）
// 计算：seclen << (9 - 4) = seclen << 5 = seclen × 32
bl->current_segment += seclen << (GRUB_DISK_SECTOR_BITS - 4);
```

**计算原理：**
- **每个扇区 = 512 字节 = 32 × 16 字节**
- **段地址单位**：每个段单位 = 16 字节
- **扇区对应的段单位数**：512 ÷ 16 = 32
- **位运算**：`seclen << 5` = `seclen × 32`（左移 5 位等于乘以 32）

**示例计算：**

假设第一个条目读取了 56 个扇区：
```
初始 current_segment = 0x0820
处理 56 个扇区后：
  current_segment += 56 << 5
  current_segment += 56 × 32
  current_segment += 1792 (0x700)
  current_segment = 0x0820 + 0x700 = 0x0F20
```

**物理地址验证：**
- 第一个条目：segment = 0x0820 → 物理地址 = 0x0820 × 16 = 0x8200 ✓
- 如果有第二个条目：segment = 0x0F20 → 物理地址 = 0x0F20 × 16 = 0xF200

**3. 在代码中的使用流程：**

```c
// 步骤 1：初始化（在调用 save_blocklists 之前）
bl->current_segment = GRUB_BOOT_MACHINE_KERNEL_SEG + 0x20;  // 0x0820

// 步骤 2：为每个块列表条目设置 segment
bl->block->segment = grub_host_to_target16 (bl->current_segment);  // 0x0820

// 步骤 3：更新 current_segment 为下一个条目的起始地址
bl->current_segment += seclen << (GRUB_DISK_SECTOR_BITS - 4);
// 例如：0x0820 + (56 << 5) = 0x0820 + 0x700 = 0x0F20
```

**关键点总结：**

1. **初始值**：`current_segment = GRUB_BOOT_MACHINE_KERNEL_SEG + 0x20 = 0x0820`
   - 对应物理地址 0x8200（startup_raw.S 入口点）

2. **更新公式**：`current_segment += seclen × 32`
   - 每个扇区（512 字节）对应 32 个段单位（16 字节/单位）

3. **段地址到物理地址**：物理地址 = segment × 16
   - 例如：segment = 0x0820 → 物理地址 = 0x8200

4. **实际使用**：由于只有一个条目，`current_segment` 只设置一次（0x0820），不会更新

**关键设计点总结：**

通过以上代码实现，可以总结出块列表机制的关键设计点：

1. **自举机制**：第一个 512 字节包含加载代码（diskboot.S），可以加载剩余的扇区
2. **块列表存储**：存储在第一个 512 字节的末尾（偏移 0x1F4，内存地址 0x81F4），由 `grub-mkimage` 在安装时写入
3. **连续加载**：虽然代码支持多个条目，但由于存储限制，实际只有一个条目，`grub-mkimage` 会确保 `core.img` 连续存放
4. **内存布局**（详见上文）：
   - `0x8000-0x81F3`：diskboot.S 代码（约 0.5KB）
   - `0x81F4-0x81FF`：块列表数据（12 字节，一个条目）
   - `0x8200+`：GRUB Core 的剩余部分（startup_raw.S、C 代码、模块等）

**boot.S 和 diskboot.S 的区别：**

| 特性 | boot.S（引导扇区） | diskboot.S（GRUB Core 第一个扇区） |
|------|------------------|----------------------------------|
| **磁盘位置** | 扇区 0（MBR） | 其他扇区（由 kernel_sector 指定，例如扇区 2048） |
| **内存位置** | `0x7C00` | `0x8000` |
| **大小** | 512 字节 | 512 字节 |
| **功能** | 读取 GRUB Core 第一个扇区 | 加载 GRUB Core 剩余部分 |
| **代码来源** | `grub/grub-core/boot/i386/pc/boot.S` | `grub/grub-core/boot/i386/pc/diskboot.S` |
| **加载者** | BIOS（通过 INT 13h） | boot.S（通过 INT 13h） |
| **包含内容** | 引导代码（约 446 字节）+ 引导签名（2 字节） | diskboot.S 代码（约 0.5KB）+ 块列表（12 字节） |

**为什么 boot.S 和 diskboot.S 要分成两个文件，不能合并？**

**原因 1：磁盘位置限制**

- **boot.S** 必须位于**扇区 0（MBR）**，这是 BIOS 的硬件规范，不能改变
- **diskboot.S** 位于**其他扇区**（由 `kernel_sector` 指定），通常不在扇区 0
- **物理限制**：两个扇区在磁盘上的位置不同，无法合并到同一个 512 字节扇区

**原因 2：内存布局限制**

- **boot.S** 加载到 `0x7C00`（BIOS 标准，不能改变）
- **diskboot.S** 加载到 `0x8000`（GRUB 设计，需要与 boot.S 分离）
- **内存冲突**：如果合并，两个代码段会占用相同的内存区域，导致冲突

**原因 3：功能分离和模块化**

- **boot.S** 的职责：读取 GRUB Core 第一个扇区（diskboot.S）
- **diskboot.S** 的职责：加载 GRUB Core 剩余部分（使用块列表）
- **设计原则**：每个阶段只负责一个任务，便于维护和调试

**原因 4：兼容性考虑**

- **MBR 限制**：扇区 0（MBR）的前 446 字节是引导代码，后 64 字节是分区表，最后 2 字节是引导签名
- **空间不足**：MBR 的引导代码区域只有 446 字节，无法容纳完整的 GRUB Core 加载逻辑
- **块列表机制**：diskboot.S 需要存储块列表（12 字节），这些数据在安装时由 `grub-mkimage` 写入

**原因 5：安装和更新灵活性**

- **boot.S** 写入 MBR（扇区 0），更新频率低
- **diskboot.S** 是 `core.img` 的一部分，可以独立更新
- **分离设计**：允许在不重写 MBR 的情况下更新 GRUB Core

**总结：**

虽然两个文件都是 512 字节，但它们：
1. **位于不同的磁盘扇区**（扇区 0 vs 其他扇区）
2. **加载到不同的内存地址**（0x7C00 vs 0x8000）
3. **功能不同**（读取第一个扇区 vs 加载剩余部分）
4. **设计目的不同**（BIOS 兼容 vs GRUB Core 加载）

因此，**必须分成两个文件**，这是由硬件限制、内存布局和设计原则共同决定的。

**关键点：**
- **boot.S 和 diskboot.S 各占 512 字节，但它们是两个不同的扇区**
- boot.S 存储在磁盘扇区 0（MBR），由 BIOS 加载到 0x7C00
- diskboot.S 存储在磁盘的其他扇区（由 kernel_sector 指定，例如 ISO 镜像为扇区 11916），由 boot.S 加载到 0x8000
- **boot.S 读取流程**（已验证）：
  1. 从 kernel_sector 字段读取扇区号（例如 11916）
  2. 使用 INT 13h 读取扇区到临时缓冲区 `0x7000:0x0000`（物理地址 `0x70000`）
  3. 从临时缓冲区复制到最终地址 `0x0000:0x8000`（物理地址 `0x8000`）
  4. 跳转到 0x8000 执行 diskboot.S
- boot.S 负责读取 diskboot.S，diskboot.S 负责加载完整的 GRUB Core
- **块列表机制**：diskboot.S 使用块列表（存储在第一个 512 字节的末尾，文件偏移 0x1F4，内存地址 0x81F4）加载完整的 GRUB Core，包括 startup_raw.S、C 代码等所有组件
- **块列表中的扇区**：是 GRUB Core 镜像在磁盘上的物理存储位置，包含编译后的二进制代码和数据（startup_raw.S、C 代码、模块等）
- **验证结果**：通过 objdump 反汇编确认 diskboot.S 的关键代码特征（块列表读取、INT 13h 调用、跳转到 startup_raw.S）

**从 diskboot.S 到 startup_raw.S 的过渡：**

当 `diskboot.S` 完成所有块列表条目的读取后，会将控制权转移到 `startup_raw.S`。具体过程如下：

1. **diskboot.S 完成加载**：`diskboot.S` 遍历完所有块列表条目（遇到 `len = 0` 的结束标记）后，所有 `core.img` 的剩余部分都已加载到内存中
2. **内存布局**：此时内存中的布局为：
   - `0x8000-0x81F3`：diskboot.S 代码
   - `0x81F4-0x81FF`：块列表数据
   - `0x8200+`：startup_raw.S 和压缩的 C 代码（已加载但未解压）
3. **跳转执行**：`diskboot.S` 执行 `jmp` 指令跳转到 `0x8200`，这是 `startup_raw.S` 的入口点（`LOCAL(codestart)`）
4. **startup_raw.S 接管**：`startup_raw.S` 开始执行，负责切换到保护模式、启用 A20、解压 LZMA 压缩代码等任务

**阶段 3：GRUB Core 从实模式切换到保护模式（仅 BIOS）**

> **注意**：这里的"阶段 3"是指 GRUB Core 内部的阶段，与前面的"阶段 1"（BIOS 加载引导扇区）和"阶段 2"（引导扇区加载 GRUB Core）不同。

**startup_raw.S 的总体功能：**

`startup_raw.S` 是 GRUB Core 的实模式入口点，负责完成从实模式到保护模式的转换，并准备执行解压后的 GRUB Core 代码。其主要功能包括：

1. **初始化实模式环境**：设置段寄存器、栈指针，保存启动驱动器号
2. **切换到保护模式**：调用 `real_to_prot` 完成模式切换
3. **启用 A20 地址线**：允许访问 1MB 以上的内存
4. **错误纠正**：处理 Reed-Solomon 错误纠正（如果启用）
5. **解压 LZMA 压缩代码**：将压缩的 C 代码部分解压到 1MB 以上（`0x100000`）
   - **解压目标地址定义**：`GRUB_MEMORY_MACHINE_DECOMPRESSION_ADDR = 0x100000`
   - **源代码位置**：`grub/include/grub/i386/pc/memory.h:36`
   - **代码使用**：`startup_raw.S:335` 使用 `movl $GRUB_MEMORY_MACHINE_DECOMPRESSION_ADDR, %edi`
6. **跳转到解压后的代码**：执行 `jmp *%esi` 跳转到 `_start` 入口点（`startup.S`）

**源代码位置：`grub/grub-core/boot/i386/pc/startup_raw.S:76-104`**

```asm
// startup_raw.S - GRUB Core 的实模式入口点（0x8200）
LOCAL (codestart):
    cli
    xorw    %ax, %ax
    movw    %ax, %ds
    movw    %ax, %ss
    movw    %ax, %es
    movl    $GRUB_MEMORY_MACHINE_REAL_STACK, %ebp
    movl    %ebp, %esp
    sti
    movb    %dl, LOCAL(boot_drive)
    int     $0x13
    calll   real_to_prot
    
    .code32
    cld
    call    grub_gate_a20
    
    // Reed-Solomon 错误纠正
    movl    LOCAL(compressed_size), %edx
    addl    $(LOCAL(decompressor_end) - LOCAL(reed_solomon_part)), %edx
    movl    reed_solomon_redundancy, %ecx
    leal    LOCAL(reed_solomon_part), %eax
    cld
    call    EXT_C (grub_reed_solomon_recover)
    jmp     post_reed_solomon

post_reed_solomon:
    // LZMA 解压：将压缩的 C 代码解压到 0x100000 (1MB)
    // 压缩状态：前约 4.1KB 未压缩（diskboot.S + startup_raw.S），后约 24KB LZMA 压缩（C 代码）
    movl    $GRUB_MEMORY_MACHINE_DECOMPRESSION_ADDR, %edi  // 解压目标：0x100000
    movl    $LOCAL(decompressor_end), %esi                 // 解压源：压缩代码位置
    pushl   %edi
    movl    LOCAL (uncompressed_size), %ecx
    leal    (%edi, %ecx), %ebx
    push    %ecx
    call    _LzmaDecodeA
    pop     %ecx
    popl    %esi  // %esi 指向解压后的代码入口点（0x100000）

    // 准备跳转到解压后的代码
    movl    LOCAL(boot_dev), %edx
    movl    $prot_to_real, %edi
    movl    $real_to_prot, %ecx
    movl    $LOCAL(realidt), %eax
    jmp     *%esi  // 跳转到 _start（startup.S，0x100000）
```

**LZMA 解压流程：**

1. **压缩状态**（在 `0x8000+`）：
   - 前约 4.1KB 未压缩：diskboot.S + startup_raw.S（实模式代码）
   - 后约 24KB LZMA 压缩：C 代码部分

2. **解压过程**：
   - 解压目标地址：`0x100000`（1MB）
   - 调用 `_LzmaDecodeA` 解压函数
   - `%esi` 指向解压后的代码入口点（`0x100000`）

3. **跳转执行**：
   - 执行 `jmp *%esi` 跳转到解压后的代码
   - 入口点是 `_start`（`startup.S`）函数

**执行流程：**

```
startup_raw.S（实模式入口点，0x8200）
    ├─ 源代码位置：`grub/grub-core/boot/i386/pc/startup_raw.S`
    ├─ 运行模式：实模式
    ├─ 步骤 1: 初始化实模式环境
    │   ├─ 设置段寄存器（ds, ss, es）
    │   ├─ 设置实模式栈
    │   └─ 保存启动驱动器号
    ├─ 步骤 2: 重置磁盘系统（INT 13h, AH=0）
    │   └─ **目的**：重置磁盘控制器状态，将读写头移动到磁道 0，清除之前的错误状态
    │   └─ **原因**：确保后续磁盘操作从干净状态开始，提高磁盘 I/O 的可靠性
    ├─ 步骤 3: 切换到保护模式（calll real_to_prot）
    │   └─ 调用 real_to_prot() 完成模式切换
    │   └─ **注意**：此时 A20 尚未启用，但暂时不需要访问 1MB 以上内存
    │   └─ **中断状态分析**：
    │       ├─ **调用前**：中断是启用的（startup_raw.S:89 执行了 sti）
    │       ├─ **real_to_prot() 内部**：执行 cli 禁用中断（realmode.S:135）
    │       ├─ **real_to_prot() 返回时**：**不会重新启用中断**（没有 sti 指令）
    │       └─ **返回后**：中断保持禁用状态，直到需要调用 BIOS 服务时切换回实模式
    │       └─ **为什么 startup_raw.S 中没有显式的 cli**：因为中断已经在 real_to_prot() 内部被禁用，并且没有被重新启用
    ├─ 步骤 4: 启用 A20 地址线（call grub_gate_a20）
    │   └─ **顺序说明**：GRUB 在保护模式下启用 A20（而非在实模式下）
    │   └─ **实现细节**：如果使用 BIOS 方法（INT 15h），函数内部会临时切换回实模式，启用 A20 后再切换回保护模式
    │   └─ **原因**：在解压之前不需要访问 1MB 以上内存，解压目标地址（0x100000）需要 A20 已启用
    ├─ 步骤 5: Reed-Solomon 错误纠正（如果启用）
    │   └─ **Reed-Solomon 错误纠正**：一种前向纠错码（FEC），用于检测和纠正数据中的错误
    │   └─ **作用**：保护 GRUB Core 镜像的完整性，即使存储介质（如闪存、磁盘）出现部分损坏，也能通过纠错码恢复数据
    │   └─ **原理**：在数据中添加冗余的校验符号，可以纠正一定数量的符号错误（取决于编码参数）
    ├─ 步骤 6: LZMA 解压（post_reed_solomon）
    │   ├─ 解压目标：0x100000（1MB）
    │   ├─ 调用 _LzmaDecodeA 解压函数
    │   └─ %esi 指向解压后的代码入口点
    ├─ 步骤 7: 准备跳转参数
    │   ├─ 保存启动设备号
    │   ├─ 保存模式切换函数地址（prot_to_real, real_to_prot）
    │   └─ 保存实模式 IDT 地址
    └─ 步骤 8: 跳转到解压后的代码（jmp *%esi）
        ├─ **源代码位置**：`startup_raw.S:356`
        ├─ **跳转指令**：`jmp *%esi`（间接跳转）
        ├─ **%esi 的值**：`0x100000`（解压后的代码基址）
        ├─ **跳转目标**：解压后的代码入口点 `_start`（`startup.S`）
        └─ **传递的参数**（通过寄存器）：
            ├─ `%edx` = 启动设备号（`LOCAL(boot_dev)`）
            ├─ `%edi` = `prot_to_real` 函数地址
            ├─ `%ecx` = `real_to_prot` 函数地址
            └─ `%eax` = `LOCAL(realidt)` 地址（实模式 IDT 地址）
        > **详细证明**：关于 `startup_raw.S` 解压后如何跳转到 `startup.S` 的完整证明过程（包括链接地址、运行地址、位置无关代码等），请参见 [GRUB startup_raw.S 解压后跳转到 startup.S 的证明](GRUB_STARTUP_RAW_TO_STARTUP_PROOF.md)。关于构建系统如何确保 `startup.S` 是第一个链接的文件，请参见 [i386_pc_startup 变量在 GRUB 构建系统中的使用说明](GRUB_I386_PC_STARTUP_USAGE.md)。
        ↓
startup.S（_start，解压后的代码入口点，0x100000）
    ├─ **源代码位置**：`grub/grub-core/kern/i386/pc/startup.S:56-124`
    ├─ **内存位置**：`0x100000`（1MB，解压后的位置）
    ├─ **运行模式**：保护模式（32 位）
    ├─ **函数签名**：`void _start(grub_addr_t esi, grub_addr_t edi, grub_addr_t ecx, grub_addr_t eax, grub_addr_t edx)`
    ├─ **执行步骤**：
    │   ├─ **步骤 1**：保存模式切换函数地址和 realidt 地址
    │   │   ├─ `movl %ecx, (LOCAL(real_to_prot_addr) - _start) (%esi)` - 保存 real_to_prot 地址
    │   │   ├─ `movl %edi, (LOCAL(prot_to_real_addr) - _start) (%esi)` - 保存 prot_to_real 地址
    │   │   └─ `movl %eax, (EXT_C(grub_realidt) - _start) (%esi)` - 保存 realidt 地址
    │   ├─ **步骤 2**：复制解压后的代码（除了模块部分）
    │   │   └─ 使用 `rep movsb` 从 `%esi`（0x100000）复制到 `_start` 位置（也是 0x100000，通常冗余）
    │   ├─ **步骤 3**：清理 BSS 段（未初始化的全局变量）
    │   │   └─ 使用 `rep stosb` 将 BSS 段清零
    │   ├─ **步骤 4**：保存启动设备号
    │   │   └─ `movl %edx, EXT_C(grub_boot_device)`
    │   └─ **步骤 5**：调用 `grub_main()`
    │       └─ `call EXT_C(grub_main)`
    └─ **调用链**：`_start` → `grub_main()` → 初始化 GRUB 核心功能 → 加载内核
        ↓
grub_main() 执行
    ├─ 源代码位置：grub/grub-core/kern/main.c
    └─ 加载 Linux 内核并跳转
```

**关键点：**
- **入口点**：`jmp *%esi` 跳转到 `_start`（`startup.S`），而不是直接到 `grub_main()`
- **初始化**：`_start` 负责保存模式切换函数地址、清理 BSS 段，然后调用 `grub_main()`
- **压缩格式**：前约 4.1KB 未压缩 + 后约 24KB LZMA 压缩，解压到 1MB 以上
- > **详细证明**：关于 `startup_raw.S` 解压后如何跳转到 `startup.S` 的完整证明过程（包括链接地址、运行地址、位置无关代码、链接器工作原理等），请参见 [GRUB startup_raw.S 解压后跳转到 startup.S 的证明](GRUB_STARTUP_RAW_TO_STARTUP_PROOF.md)。
- > **构建系统说明**：关于 `i386_pc_startup` 变量如何在 GRUB 构建系统中确保 `startup.S` 是第一个链接的文件，请参见 [i386_pc_startup 变量在 GRUB 构建系统中的使用说明](GRUB_I386_PC_STARTUP_USAGE.md)。

**步骤 8 的详细源代码分析：**

**1. 跳转指令（源代码位置：`grub/grub-core/boot/i386/pc/startup_raw.S:352-356`）：**

```asm
// startup_raw.S:352-356
post_reed_solomon:
    // ... (LZMA 解压代码，%esi 指向解压后的代码入口点 0x100000)
    
    // 准备跳转参数（通过寄存器传递）
    movl    LOCAL(boot_dev), %edx          // %edx = 启动设备号
    movl    $prot_to_real, %edi            // %edi = prot_to_real 函数地址（1MB 以下，0x8200+）
    movl    $real_to_prot, %ecx            // %ecx = real_to_prot 函数地址（1MB 以下，0x8200+）
    movl    $LOCAL(realidt), %eax          // %eax = realidt 地址（实模式 IDT 地址，1MB 以下，0x8200+）
    
    jmp     *%esi                          // 间接跳转到 %esi 指向的地址（0x100000）
    // ⚠️ 注意：这是间接跳转，%esi 的值是 0x100000（解压后的代码基址）
    // 跳转目标：startup.S 中的 _start 函数
```

**2. 解压后代码入口点 `_start`（源代码位置：`grub/grub-core/kern/i386/pc/startup.S:56-124`）：**

```asm
// startup.S - 解压后的代码入口点
.globl  start, _start, __start
start:
_start:
__start:
    .code32                                 // 32 位保护模式代码
    
    // 步骤 1: 保存模式切换函数地址和 realidt 地址
    // 这些地址需要保存到解压后的代码中，供后续使用（如 grub_bios_interrupt）
    // ⚠️ 注意：此时 %esi = 0x100000（解压后的代码基址），_start 也在 0x100000
    movl    %ecx, (LOCAL(real_to_prot_addr) - _start) (%esi)  // 保存 real_to_prot 地址
    movl    %edi, (LOCAL(prot_to_real_addr) - _start) (%esi)  // 保存 prot_to_real 地址
    movl    %eax, (EXT_C(grub_realidt) - _start) (%esi)       // 保存 realidt 地址
    
    // 步骤 2: 复制解压后的代码（除了模块部分）
    // ⚠️ 注意：%esi = 0x100000，_start 也在 0x100000，所以这是自己复制自己
    // 这个复制操作可能是为了处理重定位或确保代码完整性，但通常代码已经解压到正确位置
    movl    $(_edata - _start), %ecx       // 复制长度（代码段大小，不包括 BSS 和模块）
    movl    $(_start), %edi                 // 目标地址（_start 位置，即 0x100000）
    rep                                     // 重复执行 movsb
    movsb                                   // 从 %esi（0x100000）复制到 %edi（0x100000），每次 1 字节
    
    // 步骤 3: 清理 BSS 段（未初始化的全局变量）
    // BSS（Block Started by Symbol）段包含未初始化的全局变量，需要清零
    movl    $BSS_START_SYMBOL, %edi        // BSS 段起始地址
    movl    $END_SYMBOL, %ecx               // BSS 段结束地址
    subl    %edi, %ecx                     // BSS 段长度
    xorl    %eax, %eax                     // 清零 %eax
    cld                                     // 清除方向标志（向前复制）
    rep                                     // 重复执行 stosb
    stosb                                   // 将 %al（0）存储到 %edi，每次 1 字节
    
    // 步骤 4: 保存启动设备号
    movl    %edx, EXT_C(grub_boot_device)  // 保存启动设备号到全局变量
    
    // 步骤 5: 调用 grub_main()
    call    EXT_C(grub_main)               // 调用 GRUB 主函数
    // ⚠️ 注意：grub_main() 不会返回（它会加载内核并跳转）
```

**3. 跳转过程的详细说明：**

**寄存器状态和参数传递：**

| 寄存器 | 值 | 说明 |
|--------|-----|------|
| `%esi` | `0x100000` | 解压后的代码基址（跳转目标） |
| `%edi` | `prot_to_real` 地址 | 模式切换函数地址（1MB 以下，`0x8200+`） |
| `%ecx` | `real_to_prot` 地址 | 模式切换函数地址（1MB 以下，`0x8200+`） |
| `%eax` | `LOCAL(realidt)` 地址 | 实模式 IDT 地址（1MB 以下，`0x8200+`） |
| `%edx` | 启动设备号 | 从 `LOCAL(boot_dev)` 读取 |

**执行流程：**

```
startup_raw.S（1MB 以下，0x8200+）
    ↓
LZMA 解压完成，%esi = 0x100000
    ↓
准备跳转参数（设置 %edx, %edi, %ecx, %eax）
    ↓
jmp *%esi（间接跳转）
    ↓
startup.S（_start，解压后的代码入口点，0x100000，32 位保护模式）
    ├─ 保存模式切换函数地址（供后续使用）
    ├─ 复制代码（从 %esi=0x100000 到 _start=0x100000，通常冗余）
    ├─ 清理 BSS 段
    ├─ 保存启动设备号
    └─ call grub_main()
        ↓
grub_main()（1MB 以上，0x100000+）
    └─ 初始化 GRUB 核心功能，加载内核
```

**关键设计点：**

1. **为什么使用间接跳转 `jmp *%esi`**：
   - 解压后的代码地址是动态的（`0x100000`）
   - 使用间接跳转可以在运行时确定跳转目标
   - 如果使用直接跳转（如 `jmp $0x100000`），需要链接器在编译时知道地址

2. **为什么需要保存模式切换函数地址**：
   - `prot_to_real` 和 `real_to_prot` 位于 1MB 以下（`0x8200+`）
   - 解压后的代码（`0x100000+`）需要调用这些函数来访问 BIOS 服务
   - 因此需要保存这些函数的地址，供后续使用（如 `grub_bios_interrupt`）

3. **为什么需要清理 BSS 段**：
   - BSS 段包含未初始化的全局变量
   - 这些变量在内存中的初始值是随机的
   - 需要清零，确保这些变量有正确的初始值（0 或 NULL）

> **注意**：关于 `startup_raw.S` 中的中断状态变化、`real_to_prot` 和 `prot_to_real` 函数的详细实现说明、返回地址处理机制等，请参见 [GRUB 模式切换函数详解](GRUB_MODE_SWITCHING.md)。

### 引导过程的完整内存布局

**完整内存布局（引导过程）：**

以下是整个引导过程中内存的使用情况，从 BIOS 加载引导扇区到 GRUB 加载内核：

```
内存地址范围              内容
─────────────────────────────────────────
0x000000 - 0x0003FF      IVT（中断向量表）
0x000400 - 0x0004FF      BDA（BIOS 数据区）
0x000500 - 0x0007FF      可用空间
0x000800 - 0x0009FF      引导扇区栈空间
0x000A00 - 0x000BFF      可用空间
0x000C00 - 0x000FFF      可用空间
0x001000 - 0x001FFF      可用空间
...
0x007C00 - 0x007DFF      引导扇区（MBR）← BIOS 加载到这里
0x007E00 - 0x007FFF      引导扇区栈
0x008000 - 0x0081F3      diskboot.S 代码（约 0.5KB）← boot.S 加载
0x0081F4 - 0x0081FF      块列表数据（12 字节，文件偏移 0x1F4）
0x008200 - 0x009063      startup_raw.S（未压缩，约 3.6KB）← diskboot.S 加载
0x009000 - 0x00CFFF      C 代码（LZMA 压缩状态，约 24KB，已验证）← diskboot.S 加载
0x00D000 - 0x00FFFF      可用空间
...
0x0100000 (1MB) - ...    GRUB Core 解压后（如果使用 LZMA 压缩）← startup_raw.S 解压
                        内核镜像（vmlinuz）← GRUB 加载
0x0200000 - ...          initramfs ← GRUB 加载
...
0xF0000 - 0xFFFFF        BIOS ROM
```

**关键内存地址：**
- `0x7C00`：引导扇区（MBR）加载地址
- `0x8000`：GRUB Core 压缩状态加载地址
- `0x8200`：startup_raw.S 入口点
- `0x100000`（1MB）：GRUB Core 解压后地址（如果使用 LZMA 压缩）、内核镜像加载地址
- `0xF0000 - 0xFFFFF`：BIOS ROM

---

## GRUB 加载 Linux 内核

### GRUB 加载内核流程概述

GRUB 从 `grub_main()` 开始加载 Linux 内核的关键步骤：

**1. 内核加载 (grub_cmd_linux)**
- 解析 grub.cfg 配置文件
- 加载内核镜像到内存 (0x100000)
- 设置 boot_params 结构（内核启动参数）
- 加载 initramfs (如果存在)

**2. 跳转到内核 (grub_relocator32_boot)**
- 切换到保护模式
- 设置寄存器状态：
  - ESI = boot_params 结构地址
  - CS = 内核代码段
  - EIP = code32_start 字段的值（32 位入口物理地址）
- 按 code32_start 字段所存地址跳转（该地址处为压缩内核入口，32 位保护模式）；**从 GRUB 启动时不经过 Setup**

**3. 文档覆盖范围**

```
GRUB_KERNEL_LOADING.md              LINUX_KERNEL_INIT.md
───────────────────────             ────────────────────────────        ────────────────────
grub_main()                         
    ↓                               
grub_cmd_linux()                    
    ↓                               
grub_relocator32_boot() ────────→   code32_start 字段所存地址处的代码（压缩内核入口，32 位保护模式；从 GRUB 不经过 Setup）
                                        ↓
                                    解压 / 模式切换
                                        ↓
                                    startup_64 ────────────────────→    start_kernel()
                                        ↓                                   ↓
                                    x86_64_start_kernel()               子系统初始化
                                                                            ↓
                                                                        PID 0/1/2 创建
```

> 📖 **详细分析文档**：
> - [GRUB 加载 Linux 内核详细流程](GRUB_KERNEL_LOADING.md) - 完整的源代码分析、内存布局、参数传递机制
> - [GRUB Core 镜像结构与构建](GRUB_CORE_IMG_STRUCTURE.md) - core.img 结构、块列表机制
> - [vmlinuz 文件详细结构分析](VMLINUZ_STRUCTURE.md) - bzImage 格式、Setup 代码、压缩内核结构


### 内核早期启动（64 位）

内核从 GRUB 跳转后，经历以下关键阶段：

⚠️ **从 GRUB 启动时不执行 Setup**：GRUB 按 **code32_start** 字段所存的地址跳转（32 位保护模式入口），不经过 bzImage 内的实模式 Setup（arch/x86/boot/）。Setup 仅在**从扇区 0 启动**时执行；此时才会先跑 Setup（硬件检测、go_to_protected_mode()），再由 **pm.c** 调用 `protected_mode_jump(boot_params.hdr.code32_start, ...)`，**读取该字段的值**后跳转到该地址。详见 [GRUB_KERNEL_LOADING.md](GRUB_KERNEL_LOADING.md)、[GRUB_RELOCATOR.md](GRUB_RELOCATOR.md)。

**code32_start 在 Linux 源码中的定义与用法（与上文一致）**
- **定义**：`code32_start` 是 boot protocol 头中的**数据字段**（仅一个 32 位值）。`arch/x86/boot/header.S` 第 271 行，标签 `code32_start:`，默认值 `.long 0x100000`（"here loaders can put a different start address for 32-bit code"）。boot protocol 头中偏移 0x214/4，类型为“boot loader 可修改”；该字段**存储** 32 位保护模式入口的**物理地址**。
- **从扇区 0 启动时**：Setup（实模式）在 `arch/x86/boot/pm.c` 中调用 `protected_mode_jump(boot_params.hdr.code32_start, ...)`，**读取该字段的值**后切保护模式并跳转到该地址。
- **该地址处的代码**：在 `arch/x86/boot/compressed/head_64.S`（如 startup_32），即压缩内核入口；**不是** setup.S 的代码。

**1. 压缩内核入口（code32_start 字段所存地址处的代码，32 位保护模式）— 从 GRUB 进入时由此开始**
- 源代码：linux/arch/x86/boot/compressed/head_64.S（如 startup_32）
- GRUB/relocator 已设好 GDT、段、关分页，CPU 已处于 32 位保护模式
- 此处完成解压与向 64 位长模式的切换

**2. 解压内核（32 位保护模式 → 64 位长模式）**
- 源代码：linux/arch/x86/boot/compressed/head_64.S (startup_32)
- 关键步骤：
  - 设置页表（身份映射）
  - 启用 PAE (CR4.PAE = 1)
  - 启用长模式 (EFER.LME = 1)
  - 启用分页 (CR0.PG = 1) ← CPU 进入 64 位长模式
  - 解压内核（gzip）

**3. 64 位内核入口（startup_64）**
- 源代码：linux/arch/x86/kernel/head_64.S
- 初始化 64 位环境：
  - 保存 boot_params 地址 (%RSI → %R15)
  - 设置内核栈、GS 段基址
  - 设置 GDT 和早期 IDT
  - 调用 x86_64_start_kernel() → start_kernel()

**4. vmlinuz 文件结构说明**

vmlinuz（bzImage）包含：**Setup 代码**（未压缩，实模式）+ **压缩的内核代码**（gzip）。**从 GRUB 启动时**：GRUB 自填 boot_params，按 code32_start 字段所存地址跳转（该地址处为压缩内核入口），解压在 head_64.S 的 startup_32 等中完成；**从扇区 0 启动时**：先执行 Setup 再切保护模式，读取 code32_start 字段值并跳转。

> 📖 **详细分析文档**：
> - [Linux 内核启动与初始化（不走 Setup）](LINUX_KERNEL_INIT.md) - GRUB/压缩内核、模式切换、start_kernel、核心进程
> - [Linux 内核 Setup 流程（从扇区 0 启动）](LINUX_KERNEL_SETUP_FLOW.md) - Setup 代码、go_to_protected_mode
> - [vmlinuz 文件详细结构分析](VMLINUZ_STRUCTURE.md) - bzImage 格式、boot_params 结构
> - [Linux 内核初始化详解](LINUX_KERNEL_INIT.md) - start_kernel() 之后的初始化流程


### 内核中断系统接管

内核通过以下步骤接管 BIOS 的中断系统：

**1. 早期 IDT 设置 (x86_64_start_kernel)**
- 源代码：linux/arch/x86/kernel/head64.c
- 调用 `idt_setup_early_handler()` 建立内核 IDT
- 建立早期陷阱处理程序（处理 CPU 异常）
- 此时内核 IDT 替代 BIOS IVT

**2. 8259A PIC 重新编程**
- 源代码：linux/arch/x86/kernel/i8259.c
- 重映射硬件中断向量：
  - BIOS: IRQ0-7 → 0x08-0x0F, IRQ8-15 → 0x70-0x77
  - 内核: IRQ0-7 → 0x20-0x27, IRQ8-15 → 0x28-0x2F
- 避免与 CPU 异常向量 (0-31) 冲突

**3. APIC 和中断门设置**
- 源代码：linux/arch/x86/kernel/idt.c
- 调用 `idt_setup_apic_and_irq_gates()`：
  - 设置 Local APIC 中断门
  - 为所有外部中断 (IRQ) 设置中断门
  - 调用 `load_idt(&idt_descr)` 加载内核 IDT

**4. 接管完成标志**

从 `load_idt()` 执行后：
- ✅ 硬件中断路由到内核（PIC 重编程 + IDT 加载）
- ✅ 软件中断由内核接管（INT 指令触发内核 IDT）
- ✅ BIOS 代码不再执行（除 UEFI Runtime Services）

> 📖 **详细分析文档**：
> - [Linux 内核初始化详解](LINUX_KERNEL_INIT.md#中断系统接管详细流程) - 中断接管（早期 IDT、PIC、APIC、INT 0x80）
> - [BIOS IVT vs Kernel IDT 详细对比](BIOS_IVT_VS_KERNEL_IDT.md) - 中断向量表对比
> - [Linux 内核中断处理机制](LINUX_INTERRUPT_HANDLING.md) - Top Half 和 Bottom Half


## 总结：完整流程时间线

> **详细说明**：关于从 QEMU 启动到 Linux 内核完全接管系统的完整流程时间线，请参见 [完整流程时间线](BOOT_FLOW_TIMELINE.md)。

---

### 附录：vmlinuz 文件详细结构分析

> **详细说明**：关于 vmlinuz（bzImage）文件格式的详细结构分析，包括 boot_params 结构、Setup 代码和压缩内核代码的说明，请参见 [vmlinuz 文件详细结构分析](VMLINUZ_STRUCTURE.md)。

---

## 技术细节说明

> **详细说明**：本文档主线的详细技术说明和补充信息，请参见 [BOOT_FLOW 技术细节说明](BOOT_FLOW_NOTES.md)。  
> 关于 BIOS 128KB 内存映射的硬件实现（地址解码器、内存控制器），请参见 [技术细节说明 - Note 7: BIOS 128KB 内存映射的硬件实现](BOOT_FLOW_NOTES.md#note-7-bios-128kb-内存映射的硬件实现)。

---

## Q&A：常见问题解答

> **常见问题**：关于启动流程的常见问题解答，请参见 [BOOT_FLOW 常见问题解答](BOOT_FLOW_QA.md)。

---

## 关键源代码文件索引

> **详细说明**：关于本文档涉及的关键源代码文件位置索引，请参见 [关键源代码文件索引](BOOT_FLOW_SOURCE_INDEX.md)。

---

## 附录：GRUB 在保护模式下调用 BIOS 服务的使用场景

> **详细说明**：关于 GRUB 在保护模式下调用 BIOS 服务的使用场景，包括 `grub_bios_interrupt` 函数的使用位置、主要使用场景、调用时机和关键点，请参见 [GRUB 在保护模式下调用 BIOS 服务的使用场景](GRUB_BIOS_INTERRUPT_USAGE.md)。

---

## 附录：GRUB 模式切换函数详解

> **详细说明**：关于 GRUB 模式切换函数的详细说明，包括 `real_to_prot`、`prot_to_real` 的实现细节、返回地址处理机制、空 IDT 风险分析等，请参见 [GRUB 模式切换函数详解](GRUB_MODE_SWITCHING.md)。
