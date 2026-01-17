# QEMU → SeaBIOS → Linux Kernel 启动流程详解

本文档详细介绍了从 QEMU 虚拟硬件启动到 Linux 内核接管系统的完整流程，包括 SeaBIOS 的加载、中断服务初始化，以及内核如何接管 BIOS 并建立自己的中断处理机制。

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

## 补充说明文档

- [BIOS 运行模式与内存访问详解](BIOS_MEMORY_MODE.md)（已拆分为：[x86 CPU 运行模式详解](X86_CPU_MODES.md)、[BIOS 内存布局与地址映射详解](BIOS_MEMORY_LAYOUT.md)、[BIOS 内存模式 Q&A](BIOS_MEMORY_QA.md)）
- [BIOS 代码布局分析：128KB 映射区域内的代码与保护模式代码](BIOS_CODE_LAYOUT_ANALYSIS.md)
- [QEMU vs 真实硬件 BIOS 加载对比](QEMU_VS_HARDWARE_BIOS.md)
- [boot.asm 与 GRUB boot.S 对比分析](BOOTSECTOR_COMPARISON.md)
- [UEFI vs BIOS 引导机制对比](UEFI_VS_BIOS_BOOT.md)
- [A20 地址线技术详解](A20_ADDRESS_LINE.md)
- [BIOS IVT vs Kernel IDT 详细对比](BIOS_IVT_VS_KERNEL_IDT.md)
- [UEFI 中断处理机制](UEFI_INTERRUPT_HANDLING.md)
- [SeaBIOS entry_13_official 实现详细分析](SEABIOS_ENTRY_13_ANALYSIS.md)
- [SeaBIOS handle_post 入口地址定义机制分析](SEABIOS_HANDLE_POST_ENTRY.md)

## 附录

- [附录A：键盘中断处理代码分析](APPENDIX_A_KEYBOARD_INTERRUPT.md)
- [附录B：应用层事件机制](APPENDIX_B_EVENT_MECHANISM.md)
- [BIOS 中断处理完整详解](BIOS_INTERRUPT_COMPLETE.md) - 整合了所有中断相关内容的完整文档
- [Linux 内核中断处理：Top Half 和 Bottom Half](LINUX_INTERRUPT_HANDLING.md)
- [Linux 用户空间内存模型详解](LINUX_USERSPACE_MEMORY.md) - Linux 用户空间内存模型、内存管理和汇编内存访问
- [BOOT_FLOW 技术细节说明](BOOT_FLOW_NOTES.md)
- [BOOT_FLOW 常见问题解答](BOOT_FLOW_QA.md)

### 最小引导扇区程序示例

引导扇区（Boot Sector）是存储在磁盘第一个扇区（512 字节）的特殊程序。BIOS 完成初始化后，会调用 INT 19h 服务加载并执行引导扇区程序。前面已经详细说明了：
- BIOS 如何通过 `call_boot_entry()` 函数将驱动器号传递到 DL 寄存器（参见 [BIOS 如何传递驱动器号给引导扇区程序](#bios-如何传递驱动器号给引导扇区程序)）
- GRUB 引导扇区代码的实现和如何使用 DL 寄存器（参见 [阶段 2：GRUB 引导扇区加载 GRUB Core](#阶段-2grub-引导扇区加载-grub-core)）

以下提供一个最小化的引导扇区程序示例，帮助理解引导扇区程序的基本结构。

#### 最小引导扇区程序代码

> **相关文档**：关于最小引导扇区程序（`boot.asm`）与 GRUB 引导扇区代码（`boot.S`）的详细对比分析，请参见 [boot.asm 与 GRUB boot.S 对比分析](BOOTSECTOR_COMPARISON.md)。

```asm
; boot.asm - 最小引导扇区程序
org 0x7C00
bits 16

start:
    mov ax, 0x0003      ; 设置80x25文本模式
    int 0x10

    mov si, msg
    mov ah, 0x0E        ; BIOS 视频服务：TTY 模式显示字符

.print:
    lodsb               ; 从字符串加载一个字节到 al
    test al, al         ; 检查是否为字符串结束符
    jz .halt
    int 0x10            ; 显示字符
    jmp .print

.halt:
    jmp $               ; 无限循环

msg db "Hello from Boot Sector!", 0
times 510-($-$$) db 0   ; 填充到 510 字节
dw 0xAA55               ; 引导扇区标志
```

> **详细说明**：关于 `boot.asm` 的完整代码注释和逐行解释，请参见 [技术细节说明 - Note 5: boot.asm 完整代码注释](BOOT_FLOW_NOTES.md#note-5-bootasm-完整代码注释)。

#### 关键内存地址和中断服务

| 地址/中断 | 说明 | 用途 |
|-----------|------|------|
| `0x7C00` | 引导扇区加载地址 | BIOS 将引导扇区加载到此地址 |
| `0x07C0:0x0000` | 引导扇区段:偏移格式 | 等价于物理地址 0x7C00 |
| `INT 10h` | BIOS 视频服务 | 设置显示模式、显示字符 |
| `INT 13h` | BIOS 磁盘服务 | 读取/写入磁盘扇区 |
| `INT 19h` | BIOS 引导加载服务 | 加载并执行引导扇区 |

> **详细说明**：关于在 QEMU 中测试引导扇区的方法，请参见 [技术细节说明 - Note 6: 在 QEMU 中测试引导扇区](BOOT_FLOW_NOTES.md#note-6-在-qemu-中测试引导扇区)。

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
6. 解压后的代码入口点（grub_stub_init）
   ├─ 源代码位置：grub/grub-core/kern/i386/pc/init.c
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
   └─ 跳转到内核入口点（code32_start）
    ↓
10. 内核开始执行
    ├─ Linux 内核 Setup 代码（实模式）
    │   ├─ 源代码位置：linux/arch/x86/boot/header.S
    │   ├─ 内存位置：0x100000（1MB）或内核指定的地址
    │   ├─ 运行模式：实模式（初始阶段）
    │   ├─ 验证内核签名（boot_flag = 0xAA55）
    │   ├─ 初始化基本环境
    │   ├─ 切换到保护模式
    │   └─ 跳转到压缩内核解压代码
    │       ↓
    ├─ 压缩内核解压代码（startup_32）
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
     - 第一个条目示例（ISO 镜像）：start=11917, len=56, segment=0x0820
     - 最后一个条目 len=0 表示结束
   - 循环处理每个块列表条目：
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

**为什么需要块列表？**

在深入代码实现之前，先理解为什么需要块列表机制：

- **GRUB Core 大小限制**：GRUB Core 可能很大（几 KB 到几十 KB），跨越多个扇区，无法一次性加载
- **磁盘碎片问题**：GRUB Core 可能分散在磁盘的不同位置（由于文件系统碎片），不是连续的扇区
- **分段加载需求**：块列表记录了每个片段的位置，允许分段加载，即使数据不连续也能正确加载
- **引导扇区限制**：引导扇区只有 512 字节，无法包含完整的加载逻辑，所以将加载逻辑放在第一个 GRUB Core 扇区（diskboot.S）中

**块列表的实际代码实现：**

为了更好地理解块列表机制，下面展示块列表在源代码中的具体实现，包括数据结构定义、汇编代码中的使用方式，以及 `grub-mkimage` 工具如何生成块列表：

**1. 块列表结构定义：**

```c
// grub/include/grub/offsets.h:151-156
struct grub_pc_bios_boot_blocklist
{
    grub_uint64_t start;    // 起始扇区号（LBA，8 字节）
    grub_uint16_t len;      // 要读取的扇区数（2 字节）
    grub_uint16_t segment;  // 目标内存段地址（2 字节）
} GRUB_PACKED;
```

**2. 块列表在 diskboot.S 中的汇编定义：**

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

**3. diskboot.S 读取块列表的代码（包含跳转到 startup_raw.S）：**

以下代码展示了 `diskboot.S` 的完整执行流程：从读取块列表到跳转到 `startup_raw.S`。代码包含两个主要部分：
1. **块列表读取循环**（`LOCAL(bootloop)` - `LOCAL(bootit)` 之前）：遍历所有块列表条目，读取并复制数据
2. **跳转到 startup_raw.S**（`LOCAL(bootit)` 标签）：所有块列表处理完成后，跳转到 `startup_raw.S`

```asm
// grub/grub-core/boot/i386/pc/diskboot.S:61-320
_start:
    // 设置 %di 指向第一个块列表条目
    // 块列表在扇区末尾，文件偏移 0x1F4，内存地址 0x81F4
    movw    $LOCAL(firstlist), %di  // %di = 0x81F4（已验证）
    
LOCAL(bootloop):
    // 检查 len 字段（偏移 8 字节）
    cmpw    $0, 8(%di)
    je      LOCAL(bootit)  // 如果 len = 0，跳转到启动代码（所有块列表处理完成）
    
LOCAL(setup_sectors):
    // 读取 start 字段（偏移 0-7 字节）：起始扇区号
    movl    (%di), %ebx      // 低 32 位（例如：11917 = 0x2e8d）
    movl    4(%di), %ecx     // 高 32 位（通常为 0）
    
    // 读取 len 字段（偏移 8 字节）：要读取的扇区数
    movw    8(%di), %ax      // 读取扇区数（例如：56）
    
    // 使用 INT 13h 读取扇区到临时缓冲区（0x7000:0x0000，物理地址 0x70000）
    // ... 读取代码 ...
    
LOCAL(copy_buffer):
    // 读取 segment 字段（偏移 10 字节）：目标内存段
    movw    10(%di), %es     // 设置目标段地址（例如：0x0820）
    
    // 从临时缓冲区（0x7000:0x0000）复制数据到目标地址
    // 例如：segment=0x0820 对应物理地址 0x8200（startup_raw.S 入口点）
    // ... 复制代码 ...
    
    // 检查是否完成当前条目
    cmpw    $0, 8(%di)
    jne     LOCAL(setup_sectors)  // 如果还有剩余扇区，继续读取
    
    // 移动到下一个块列表条目（向前移动 12 字节）
    subw    $GRUB_BOOT_MACHINE_LIST_SIZE, %di
    jmp     LOCAL(bootloop)  // 继续处理下一个条目

// ========== 跳转到 startup_raw.S ==========
LOCAL(bootit):
    // 所有块列表条目处理完成，跳转到 startup_raw.S
    // startup_raw.S 位于内存地址 0x8200（段地址 0x0000，偏移 0x8200）
    // 源代码位置：grub/grub-core/boot/i386/pc/diskboot.S:310-320
    
    // 设置段寄存器
    movw    $GRUB_BOOT_MACHINE_KERNEL_SEG, %ax  // %ax = 0x0000
    movw    %ax, %ds                              // 设置数据段 = 0x0000
    movw    %ax, %ss                              // 设置栈段 = 0x0000
    
    // 跳转到 startup_raw.S 入口点（0x0000:0x8200）
    // 使用长跳转（ljmp）跳转到段地址 0x0000，偏移 0x8200
    ljmp    $GRUB_BOOT_MACHINE_KERNEL_SEG, $(GRUB_BOOT_MACHINE_KERNEL_ADDR + 0x200)
    // 等价于：ljmp $0x0000, $0x8200
    // 这会跳转到物理地址 0x8200，即 startup_raw.S 的入口点（LOCAL(codestart)）
```

**4. 块列表字段的内存布局：**

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

实际验证示例（ISO 镜像）：
- 块列表位置：文件偏移 0x1F4，内存地址 0x81F4（在 diskboot.S 扇区的末尾）
- 第一个条目：start=11917 (0x2e8d), len=56, segment=0x0820
  - start=11917：表示从扇区 11917 开始读取（kernel_sector + 1）
  - len=56：需要读取 56 个扇区（约 28KB）
  - segment=0x0820：目标内存段，对应物理地址 0x8200（startup_raw.S 入口点）
- 最后一个条目：len=0，表示块列表结束
```

**5. 块列表的生成代码（grub-install）：**

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
    
    // 更新目标段地址（每个扇区 = 32 个段单位，因为 512 字节 = 32 * 16 字节）
    bl->current_segment += seclen << (GRUB_DISK_SECTOR_BITS - 4);
}
```

**关键设计点总结：**

通过以上代码实现，可以总结出块列表机制的关键设计点：

1. **自举机制**：第一个 512 字节包含加载代码（diskboot.S），可以加载剩余的扇区
2. **块列表存储**：存储在第一个 512 字节的末尾（偏移 0x1F4），由 `grub-mkimage` 在安装时写入
3. **分段加载**：GRUB Core 可能分散在磁盘的不同位置（由于文件系统碎片），块列表记录了每个片段的位置
4. **内存布局**：
   - `0x8000-0x81F3`：diskboot.S 代码（约 0.5KB）
   - `0x81F4-0x81FF`：块列表数据（12 字节，第一个条目）
   - `0x8200+`：GRUB Core 的剩余部分（startup_raw.S、C 代码、模块等）
   - **压缩状态**（已验证）：
     - 前约 4.1KB 未压缩：diskboot.S + startup_raw.S（在 0x8000+）
     - 后约 24KB LZMA 压缩：C 代码（解压到 0x100000）

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

在 BIOS 模式下，GRUB Core 需要从实模式切换到保护模式。这个过程发生在 `startup_raw.S` 中：

**源代码位置：`grub/grub-core/boot/i386/pc/startup_raw.S:76-104`**

```asm
// startup_raw.S - GRUB Core 的实模式入口点（0x8200）
LOCAL (codestart):
    cli     // 禁用中断，准备模式切换
    
    // 设置实模式段寄存器
    xorw    %ax, %ax
    movw    %ax, %ds
    movw    %ax, %ss
    movw    %ax, %es
    
    // 设置实模式栈
    movl    $GRUB_MEMORY_MACHINE_REAL_STACK, %ebp
    movl    %ebp, %esp
    
    sti     // 重新启用中断
    
    // 保存启动驱动器号
    movb    %dl, LOCAL(boot_drive)
    
    // 重置磁盘系统
    int     $0x13
    
    // 关键步骤：从实模式切换到保护模式
    calll   real_to_prot
    
    // 切换到保护模式代码（.code32）
    .code32
    
    // 启用 A20 地址线（访问 1MB 以上内存）
    cld
    call    grub_gate_a20
    
    // 步骤 4: 处理 Reed-Solomon 错误纠正（如果启用）
    movl    LOCAL(compressed_size), %edx
    addl    $(LOCAL(decompressor_end) - LOCAL(reed_solomon_part)), %edx
    movl    reed_solomon_redundancy, %ecx
    leal    LOCAL(reed_solomon_part), %eax
    cld
    call    EXT_C (grub_reed_solomon_recover)
    jmp     post_reed_solomon

post_reed_solomon:
    // 步骤 5: 解压 GRUB Core（如果使用 LZMA 压缩）
#ifdef ENABLE_LZMA
    // 如果使用 LZMA 压缩（默认情况，已验证）：
    // **压缩状态**（通过验证脚本确认）：
    // - 前 4KB 未压缩：diskboot.S + startup_raw.S（在 0x8000+，实模式代码）
    // - 后 24KB LZMA 压缩：C 代码（需要解压到 0x100000）
    // - 解压目标地址：0x100000 (1MB)
    movl    $GRUB_MEMORY_MACHINE_DECOMPRESSION_ADDR, %edi  // 解压目标地址：0x100000 (1MB)
    movl    $LOCAL(decompressor_end), %esi                 // 解压源：压缩的代码结束位置
    pushl   %edi
    movl    LOCAL (uncompressed_size), %ecx                // 解压后的大小
    leal    (%edi, %ecx), %ebx
    push    %ecx
    call    _LzmaDecodeA                                   // 调用 LZMA 解压函数
    pop     %ecx
    popl    %esi  // %esi 指向解压后的代码入口点（0x100000）
#else
    // 注意：默认情况下 GRUB 使用 LZMA 压缩，此分支仅在特殊情况下使用
    // （例如：编译时使用 --disable-liblzma，或系统没有 LZMA 库）
    // 如果没有 LZMA 压缩（特殊情况）：
    // GRUB Core 代码没有被压缩，直接在前 1MB 中（0x8000+）
    // %esi 需要指向实际的代码入口点
    // 注意：如果没有 LZMA，代码可能已经在正确的位置，不需要解压
    // 通常，如果没有压缩，代码入口点就是 LOCAL(decompressor_end) 之后的位置
    // 或者代码已经在 0x8000+ 的位置，直接跳转即可
#endif

    // 步骤 6: 准备跳转到代码入口点
    movl    LOCAL(boot_dev), %edx        // 保存启动设备号
    movl    $prot_to_real, %edi         // 保存实模式切换函数地址
    movl    $real_to_prot, %ecx         // 保存保护模式切换函数地址
    movl    $LOCAL(realidt), %eax       // 保存实模式 IDT 地址
    
    // 步骤 7: 跳转到代码入口点
    // 默认情况（使用 LZMA 压缩）：%esi 指向解压后的代码入口点（0x100000）
    // 特殊情况（不使用 LZMA 压缩）：代码未压缩，直接在前 1MB 中（0x8000+）
    //   - 此时 %esi 可能未设置，或者指向 LOCAL(decompressor_end) 之后的位置
    //   - 代码入口点是 grub_stub_init() 函数（grub/grub-core/kern/i386/pc/init.c）
    //   - 如果没有 LZMA，代码可能已经在正确的位置，直接跳转即可
    jmp     *%esi  // 间接跳转：跳转到代码入口点（默认：0x100000，解压后的代码）
```

**关键点：**
- **第 104 行**：调用 `grub_gate_a20` 启用 A20 地址线（访问 1MB 以上内存）
- **第 116-117 行**：处理 Reed-Solomon 错误纠正，然后跳转到 `post_reed_solomon`
- **第 332-356 行**（`post_reed_solomon` 标签）：
  - **如果使用 LZMA 压缩**：
    - 解压代码到 `GRUB_MEMORY_MACHINE_DECOMPRESSION_ADDR = 0x100000`（1MB）
    - `%esi` 指向解压后的代码入口点（0x100000）
  - **如果没有 LZMA 压缩**：
    - GRUB Core 代码没有被压缩，直接在前 1MB 中（0x8000+）
    - `%esi` 指向未压缩的代码入口点（通常在 `LOCAL(decompressor_end)` 之后，或代码已经在 0x8000+ 的位置）
    - **不需要解压**：代码已经在正确的位置，直接跳转即可
- **第 356 行**：`jmp *%esi` - 跳转到代码入口点（解压后的或未压缩的）

**代码入口点（解压后或未压缩）：**

`jmp *%esi` 跳转后的代码入口点**不是直接到 `main.c` 的 `grub_main()`**，而是先到 `grub_stub_init()` 初始化函数，该函数位于解压后的 GRUB Core 代码中。

**执行顺序：**
```
startup_raw.S: jmp *%esi
    ├─ 源代码位置：grub/grub-core/boot/i386/pc/startup_raw.S
    ↓
解压后的代码入口点（grub_stub_init）
    ├─ 源代码位置：grub/grub-core/kern/i386/pc/init.c
    ├─ 内存位置：0x100000（1MB，如果使用 LZMA 压缩）或 0x8000+（如果不使用 LZMA 压缩）
    ├─ 运行模式：保护模式
    ├─ 初始化 GRUB 核心功能：
    │   ├─ 内存管理初始化（grub_mm_init）
    │   ├─ 设备驱动初始化
    │   ├─ 文件系统驱动框架初始化
    │   └─ 其他核心功能初始化
    └─ 调用 grub_main()（grub/grub-core/kern/main.c）
        ↓
grub_main() 执行
    ├─ 源代码位置：grub/grub-core/kern/main.c
    └─ 加载 Linux 内核并跳转
```

**关键点：**
- **入口点不是 `main.c`**：`jmp *%esi` 跳转到的是初始化函数，不是 `grub_main()`
- **初始化函数的作用**：在调用 `grub_main()` 之前，需要先初始化 GRUB 的核心功能（内存管理、设备驱动等）
- **`grub_main()` 的调用**：由初始化函数调用，而不是直接作为入口点

**阶段 3.5：从 startup_raw.S 到 grub_main() 的中间过程**

**源代码位置：** `grub/grub-core/kern/i386/pc/init.c`

**关键点：**
- **解压后的代码入口点**：`startup_raw.S` 的 `jmp *%esi` 跳转到解压后的代码（或未压缩的代码）入口点
- **初始化函数**：`grub_stub_init()` 函数，负责初始化 GRUB 核心功能
- **调用 grub_main()**：初始化完成后，调用 `grub_main()` 进入 GRUB 主程序

**两种情况对比：**

| 情况 | 代码位置 | 是否需要解压 | `%esi` 指向 | 使用场景 |
|------|---------|------------|-----------|---------|
| **使用 LZMA 压缩** | 压缩状态在 `0x8000+`，解压后到 `0x100000` | ✅ 需要解压 | 解压后的代码入口点（`0x100000`） | **默认情况**，大多数 GRUB 安装 |
| **不使用 LZMA 压缩** | 未压缩，直接在 `0x8000+` | ❌ 不需要解压 | 未压缩的代码入口点（`0x8000+` 或 `LOCAL(decompressor_end)` 之后） | 禁用 LZMA、嵌入式系统、调试 |

**关键点：**
- **LZMA 压缩**：代码被压缩，需要解压到 1MB 以上（`0x100000`）
- **无压缩**：代码未压缩，直接在前 1MB 中（`0x8000+`），不需要解压
- **两种情况下**：最终都通过 `jmp *%esi` 跳转到代码入口点

**关于压缩的常见问题：**

1. **前 1MB 够用吗？**
   - **如果使用 LZMA 压缩**（默认情况，已验证）：✅ 够用
     - **混合格式**（已验证）：
       - 前约 4.1KB 未压缩：diskboot.S + startup_raw.S（在 `0x8000 - 0x9063`，实模式代码）
         - diskboot.S：约 0.5KB（0x8000-0x81F3）+ 块列表 12 字节（0x81F4-0x81FF）
         - startup_raw.S：从 0x8200 开始，约 3.6KB
       - 后约 24KB LZMA 压缩：C 代码（在 `0x9063+`，需要解压到 `0x100000`）
     - 前 1MB 有约 640KB 可用空间，足够容纳压缩的代码
     - 解压后的代码在 1MB 以上（`0x100000`），有足够的空间运行
   - **如果不使用 LZMA 压缩**：⚠️ 可能不够用
     - 未压缩的 GRUB Core：约 20KB - 100KB 或更大（取决于配置）
     - 如果 GRUB Core 很大（> 100KB），前 1MB 可能不够用
     - **因此，默认情况下 GRUB 使用 LZMA 压缩**

2. **什么情况下没有压缩？**
   - **编译时禁用 LZMA**：使用 `--disable-liblzma` 配置选项
   - **系统没有 LZMA 库**：如果编译时检测不到 LZMA 库，可能不使用压缩
   - **嵌入式系统**：某些嵌入式系统可能不使用压缩以简化启动流程
   - **调试目的**：开发时可能禁用压缩以便调试

3. **是不是默认都是压缩-解压的流程？**
   - **是的，默认情况下 GRUB 使用 LZMA 压缩**（已验证）
   - **原因**：
     - GRUB Core 未压缩时可能很大（几十 KB 到几百 KB）
     - 前 1MB 空间有限（约 640KB 可用）
     - 使用压缩可以：
       - 减小 core.img 的大小（压缩后约 28KB，已验证：前约 4.1KB 未压缩 + 后约 24KB 压缩）
       - 在前 1MB 中容纳更多代码
       - 解压到 1MB 以上，避免前 1MB 空间不足
   - **压缩流程**（已验证）：
     - 编译时：GRUB Core 的 C 代码部分被 LZMA 压缩，嵌入到 core.img
     - 启动时：`startup_raw.S` 解压 C 代码部分到 `0x100000`（1MB）
     - 解压后：代码在 1MB 以上，有足够的空间运行
     - **混合格式**：前约 4.1KB 未压缩（diskboot.S + startup_raw.S），后约 24KB 压缩（C 代码）

**实际大小示例：**

| 配置 | 未压缩大小 | 压缩后大小（LZMA） | 压缩率 |
|------|-----------|------------------|--------|
| **最小配置** | 约 20KB | 约 8KB | ~40% |
| **标准配置** | 约 50KB - 100KB | 约 20KB - 32KB | ~30-40% |
| **完整配置** | 约 100KB - 200KB | 约 32KB - 64KB | ~30-40% |

**结论：**
- **默认使用 LZMA 压缩**：这是 GRUB 的标准配置
- **前 1MB 通常不够未压缩的代码**：如果 GRUB Core 很大（> 100KB），前 1MB 可能不够用
- **压缩-解压流程是默认的**：大多数 GRUB 安装都使用这个流程

> **注意**：关于 A20 地址线的详细技术说明，请参见 [A20 地址线技术详解](A20_ADDRESS_LINE.md)。

**模式切换的关键步骤（real_to_prot）：**

`startup_raw.S` 中调用的 `real_to_prot` 函数负责从实模式切换到保护模式。这个函数在 `realmode.S` 中实现：

**源代码位置：`grub/grub-core/kern/i386/realmode.S:133-195`**

```asm
// real_to_prot - 从实模式切换到保护模式
real_to_prot:
    .code16
    cli     // 禁用中断
    
    // 步骤 1: 加载全局描述符表（GDT）
    xorw    %ax, %ax
    movw    %ax, %ds
    lgdtl   gdtdesc  // 加载 GDT 描述符
    
    // 步骤 2: 设置 CR0 的 PE 位（Protected Mode Enable）
    movl    %cr0, %eax
    orl     $GRUB_MEMORY_CPU_CR0_PE_ON, %eax  // 设置 PE 位
    movl    %eax, %cr0
    
    // 步骤 3: 跳转到保护模式代码段，刷新预取队列
    ljmpl   $GRUB_MEMORY_MACHINE_PROT_MODE_CSEG, $protcseg
    
    .code32
protcseg:
    // 步骤 4: 重新加载所有段寄存器（使用保护模式段选择子）
    movw    $GRUB_MEMORY_MACHINE_PROT_MODE_DSEG, %ax
    movw    %ax, %ds
    movw    %ax, %es
    movw    %ax, %fs
    movw    %ax, %gs
    movw    %ax, %ss
    
    // 步骤 5: 切换到保护模式栈
    movl    (%esp), %eax
    movl    %eax, GRUB_MEMORY_MACHINE_REAL_STACK
    
    movl    protstack, %eax
    movl    %eax, %esp
    movl    %eax, %ebp
    
    // 步骤 6: 保存实模式 IDT，加载保护模式 IDT（空）
    sidt    LOCAL(realidt)  // 保存实模式 IDT
    lidt    protidt         // 加载保护模式 IDT（空）
    
    ret     // 返回，现在在保护模式下
```

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
0x0100000 (1MB) - ...    内核镜像（vmlinuz）← GRUB 加载
0x0200000 - ...          initramfs ← GRUB 加载
...
0xF0000 - 0xFFFFF        BIOS ROM
```

**关键步骤总结：**

以下是整个引导过程的关键步骤，从 BIOS 加载引导扇区到 GRUB 加载内核：

1. **BIOS → 引导扇区**：
   - BIOS 调用 INT 13h（AH=0x02）读取磁盘第一个扇区
   - 加载到 `0x7C00`，验证签名 `0xAA55`
   - 跳转到 `0x0000:0x7C00` 执行

2. **引导扇区 → GRUB Core**：
   - 引导扇区代码（boot.S）从 kernel_sector 读取 GRUB Core 第一个扇区（diskboot.S）
   - 加载 diskboot.S 到 `0x8000`
   - diskboot.S 使用块列表加载完整的 GRUB Core（包括 startup_raw.S）
   - 跳转到 GRUB Core（startup_raw.S 入口点 0x8200）
   
   **实模式下的内存使用分析：**
   
   - **1MB 内存是否够用？**
     - **够用**：在实模式阶段（引导扇区 → GRUB Core），所有代码和数据都在 1MB 范围内：
       - `0x7C00 - 0x7DFF`：引导扇区（512 字节）
       - `0x8000 - 0x9FFF`：GRUB Core（约 8KB）
       - `0xA000 - 0xBFFF`：GRUB 文件系统驱动（可选）
       - `0xF0000 - 0xFFFFF`：BIOS ROM（只读）
     - **总计使用**：约 10-20KB，远小于 1MB 的可用空间（约 640KB 常规 RAM）
   
   - **地址会不会冲突？**
     - **不会冲突**：内存布局是精心设计的，各组件使用不同的地址范围：
       - 引导扇区：`0x7C00 - 0x7DFF`（512 字节）
       - GRUB Core：`0x8000+`（与引导扇区不重叠）
       - BIOS ROM：`0xF0000 - 0xFFFFF`（只读，不影响）
       - 可用空间：`0x0000 - 0x7BFF`、`0x8000 - 0x9FFF` 之间等
     - **设计原则**：引导扇区选择 `0x7C00` 是为了避免与 BIOS 数据区（`0x0000 - 0x03FF`）和栈空间冲突
   
   - **为什么内核加载到 1MB 以上？**
     - 内核镜像通常较大（几 MB 到几十 MB），无法放入前 1MB
     - 因此 GRUB Core 需要**先切换到保护模式**，然后才能访问 1MB 以上的内存来加载内核
     - 这是为什么步骤 3 中需要"切换到保护模式/长模式"的原因

3. **GRUB Core → grub_main()**：
   - startup_raw.S 解压 GRUB Core（如果使用 LZMA 压缩）到 `0x100000`（1MB）
   - 跳转到解压后的代码入口点（`grub_stub_init()`）
   - 初始化函数初始化 GRUB 核心功能（内存管理、设备驱动等）
   - 调用 `grub_main()`（`grub/grub-core/kern/main.c`）
   - **此时 GRUB Core 已完全初始化，准备加载内核**

**关键内存地址：**
- `0x7C00`：引导扇区（MBR）加载地址
- `0x8000`：GRUB Core 压缩状态加载地址
- `0x100000`（1MB）：GRUB Core 解压后地址（如果使用 LZMA 压缩）
- `0xFFFFFFFF - bios_size`：BIOS ROM 地址

---

## GRUB 加载 Linux 内核

### 从 grub_main() 到内核入口点

**执行流程衔接：**

在上一节中，我们已经完成了从 BIOS 到 `grub_main()` 的完整流程：
- BIOS 加载引导扇区（boot.S）到 `0x7C00`
- boot.S 加载 GRUB Core 第一个扇区（diskboot.S）到 `0x8000`
- diskboot.S 加载完整的 GRUB Core（包括 startup_raw.S）到 `0x8200+`
- startup_raw.S 切换到保护模式，解压 GRUB Core 到 `0x100000`（如果使用 LZMA 压缩）
- 跳转到解压后的代码入口点（`grub_stub_init()`），初始化 GRUB 核心功能
- 调用 `grub_main()`（`grub/grub-core/kern/main.c`）

**本节内容：**

本节将详细说明 `grub_main()` 如何加载 Linux 内核并跳转到内核入口点：

```
grub_main()（grub/grub-core/kern/main.c）
    ├─ 源代码位置：grub/grub-core/kern/main.c
    ├─ 解析 grub.cfg 配置文件
    ├─ 显示启动菜单（如果配置）
    ├─ 用户选择启动 Linux 内核
    └─ 执行 linux 命令 → grub_cmd_linux()
        ↓
grub_cmd_linux()（grub/grub-core/loader/i386/linux.c）
    ├─ 源代码位置：grub/grub-core/loader/i386/linux.c
    ├─ 加载内核镜像到内存（0x100000）
    ├─ 设置内核启动参数（boot_params）
    └─ 注册启动函数 grub_linux_boot()
        ↓
grub_linux_boot() → grub_relocator32_boot()
    ├─ 源代码位置：grub/grub-core/loader/i386/linux.c
    └─ 跳转到内核入口点（code32_start）
        ↓
grub_relocator32_boot() 跳转到内核入口点（code32_start）
    ├─ 源代码位置：grub/grub-core/lib/i386/relocator.c
    ├─ 跳转地址：code32_start（内核头部字段，相对于 0x100000 的偏移）
    └─ 寄存器状态：
        ├─ ESI = boot_params 地址
        ├─ ESP = 栈指针
        └─ EIP = code32_start（内核入口点）
    ↓
Linux 内核 Setup 代码（实模式）
    ├─ 源代码位置：linux/arch/x86/boot/header.S
    ├─ 内存位置：0x100000（1MB）或内核指定的地址
    ├─ 运行模式：实模式（初始阶段）
    ├─ 验证内核签名（boot_flag = 0xAA55）
    ├─ 初始化基本环境
    ├─ 切换到保护模式
    └─ 跳转到压缩内核解压代码
        ↓
压缩内核解压代码（startup_32）
    ├─ 源代码位置：linux/arch/x86/boot/compressed/head_64.S
    ├─ 运行模式：32 位保护模式 → 64 位长模式
    ├─ 设置页表（身份映射：物理地址 = 线性地址）
    ├─ 切换到 64 位长模式
    ├─ 解压内核（gzip 解压）
    └─ 跳转到 startup_64
        ↓
startup_64（64 位内核入口点）
    ├─ 源代码位置：linux/arch/x86/kernel/head_64.S
    ├─ 运行模式：64 位长模式
    ├─ 保存 boot_params 结构地址（%RSI → %R15）
    ├─ 设置初始内核栈
    ├─ 设置 GS 段基址（per-CPU 数据）
    ├─ 设置 GDT 和早期 IDT
    ├─ 切换到内核代码段（__KERNEL_CS）
    ├─ 激活内存加密（SEV/SME，如果支持）
    ├─ 验证和清理 CPU 配置（verify_cpu）
    └─ 继续内核初始化流程
        ↓
内核继续初始化（x86_64_start_kernel）
    ├─ 源代码位置：linux/arch/x86/kernel/head64.c
    ├─ 设置早期中断处理程序（idt_setup_early_handler）
    │   └─ 源代码位置：linux/arch/x86/kernel/idt.c
    ├─ TDX 早期初始化（tdx_early_init，如果支持）
    ├─ 复制引导数据（copy_bootdata）
    ├─ 加载微码更新（load_ucode_boot）
    ├─ 设置内核高地址映射
    └─ 启动内核预留区域初始化（x86_64_start_reservations）
        └─ 最终调用 start_kernel()
```

### GRUB 加载内核的详细流程

**源代码位置：** `grub/grub-core/loader/i386/linux.c`

GRUB 加载 Linux 内核的过程包括以下步骤：

1. **grub_main()** 解析 `grub.cfg` 配置文件，执行 `linux` 命令
2. **grub_cmd_linux()** 打开内核文件（如 `/boot/vmlinuz-5.x.x`），解析内核头部，加载内核镜像到内存
3. **grub_linux_boot()** 设置启动参数，通过 `grub_relocator32_boot()` 跳转到内核入口点

**内核镜像结构概述：**

Linux 内核镜像（bzImage/vmlinuz）包含两部分：

1. **Setup 代码**（实模式代码）：
   - 大小：通常 4-64 个扇区（由 `setup_sects` 字段指定）
   - 功能：切换到保护模式/长模式，解压内核
   - 源代码：`linux/arch/x86/boot/header.S`

2. **压缩的内核代码**：
   - 位置：setup 代码之后
   - 格式：gzip 压缩的 vmlinux
   - 加载地址：`0x100000`（1MB）或内核指定的地址

**GRUB 加载内核的详细代码流程：**

**源代码位置：** `grub/grub-core/loader/i386/linux.c:680-725`

```c
// grub/grub-core/loader/i386/linux.c
grub_cmd_linux (grub_command_t cmd, int argc, char *argv[])
{
    // 步骤 1: 打开内核文件（如 /boot/vmlinuz-5.x.x）
    file = grub_file_open (argv[0]);
    
    // 步骤 2: 读取整个文件到内存（注意：这里只是复制文件，不解压）
    // vmlinuz 文件包含：
    //   - 内核头部（512字节，未压缩）
    //   - Setup 代码（未压缩，可以直接执行）
    //   - 压缩的内核代码（gzip 压缩的 vmlinux）
    // GRUB 只是将整个文件从磁盘复制到内存，不解压
    len = grub_file_size (file);
    kernel = grub_malloc (len);
    grub_file_read (file, kernel, len);
    
    // 步骤 3: 解析内核头部（前 512 字节）
    grub_memcpy (&lh, kernel, sizeof (lh));  // lh 是 linux_kernel_header 结构
    
    // 步骤 4: 验证内核签名
    if (lh.boot_flag != grub_cpu_to_le16 (0xAA55))
        return grub_error (GRUB_ERR_BAD_OS, "invalid kernel signature");
    
    if (lh.header != grub_cpu_to_le32 (0x53726448))  // "HdrS"
        return grub_error (GRUB_ERR_BAD_OS, "invalid kernel header");
    
    // 步骤 5: 计算 Setup 代码大小
    setup_sects = lh.setup_sects;
    if (setup_sects == 0)
        setup_sects = 4;  // 默认 4 个扇区
    setup_size = (setup_sects + 1) * 512;  // +1 是因为头部也算一个扇区
    
    // 步骤 6: 计算压缩内核代码大小
    kernel_size = len - setup_size;
    
    // 步骤 7: 计算加载地址
    preferred_address = GRUB_LINUX_BZIMAGE_ADDR;  // 0x100000
    if (lh.pref_address && relocatable)
        preferred_address = grub_le_to_cpu64 (lh.pref_address);
    
    // 步骤 8: 分配内存并加载内核
    prot_mode_target = allocate_pages (prot_size, &align, min_align, 
                                       relocatable, preferred_address);
    
    // 步骤 9: 复制 Setup 代码和压缩内核到目标地址
    // 注意：这里只是复制文件内容到内存，不解压
    // Setup 代码是未压缩的，可以直接执行
    // 压缩的内核代码需要由 Setup 代码解压
    grub_memcpy (prot_mode_mem, kernel, setup_size);  // Setup 代码（未压缩）
    grub_memcpy (prot_mode_mem + setup_size, 
                 kernel + setup_size, kernel_size);    // 压缩内核（gzip 压缩）
    
    // 步骤 10: 设置 boot_params 结构
    linux_params.code32_start = prot_mode_target + 
                                grub_le_to_cpu32 (lh.code32_start) - 
                                GRUB_LINUX_BZIMAGE_ADDR;
    linux_params.cmd_line_ptr = ...;  // 内核命令行参数
    linux_params.ramdisk_image = ...; // initramfs 地址
    
    // 步骤 11: 注册启动函数
    // 注意：这里只是注册，并不立即执行跳转
    // 当用户在 GRUB 菜单中选择启动该项时，才会调用 grub_linux_boot()
    grub_loader_set (grub_linux_boot, grub_linux_unload, 0);
}
```

**GRUB 菜单选择与启动函数的关系：**

**执行时机说明：**

1. **解析 `grub.cfg` 时**（`grub_main()` → `grub_cmd_linux()`）：
   - 当 GRUB 解析 `grub.cfg` 配置文件时，遇到 `linux` 命令会调用 `grub_cmd_linux()`
   - `grub_cmd_linux()` 加载内核镜像到内存，设置启动参数
   - **关键**：此时只是**注册**启动函数 `grub_linux_boot()`，**并不立即执行跳转**
   - 用户可以继续浏览菜单，选择其他启动项，或修改内核参数

2. **用户选择启动项时**（菜单交互 → `grub_linux_boot()`）：
   - 当用户在 GRUB 菜单中选择启动该项（按 Enter 键）时
   - GRUB 会调用之前注册的启动函数 `grub_linux_boot()`
   - `grub_linux_boot()` 通过 `grub_relocator32_boot()` 执行跳转到内核入口点

**示例 `grub.cfg` 配置：**

```bash
# /boot/grub/grub.cfg
menuentry "Linux 5.x.x" {
    linux /boot/vmlinuz-5.x.x root=/dev/sda1 ro
    # ↑ 执行 linux 命令时，调用 grub_cmd_linux()
    #   此时加载内核到内存，注册 grub_linux_boot()
    #   但不会立即跳转，用户可以继续选择或修改
    
    initrd /boot/initrd.img-5.x.x
    # ↑ 加载 initramfs（可选）
}

# 用户按 Enter 选择 "Linux 5.x.x" 时：
# → GRUB 调用 grub_linux_boot()
# → grub_linux_boot() 调用 grub_relocator32_boot()
# → 跳转到内核入口点（code32_start）
```

**关键点：**
- **延迟执行机制**：`grub_cmd_linux()` 只负责准备（加载内核、注册函数），不执行跳转
- **用户交互触发**：跳转由用户在菜单中选择启动项时触发
- **灵活性**：用户可以在加载内核后继续浏览菜单、修改参数或选择其他启动项

**步骤 12：grub_linux_boot() 执行跳转**

当用户选择启动内核时，GRUB 会调用注册的 `grub_linux_boot()` 函数，该函数通过 `grub_relocator32_boot()` 跳转到内核入口点：

**源代码位置：** `grub/grub-core/loader/i386/linux.c:446-667`

```c
// grub/grub-core/loader/i386/linux.c
grub_linux_boot (void)
{
    // 准备 boot_params 结构（包含 code32_start）
    *ctx.params = linux_params;
    
    // 设置寄存器状态
    struct grub_relocator32_state state;
    state.esi = ctx.real_mode_target;        // ESI = boot_params 地址
    state.esp = ctx.real_mode_target;        // ESP = 栈指针
    state.eip = ctx.params->code32_start;    // EIP = 内核入口点（code32_start）
    
    // 跳转到内核（通过 relocator 切换到保护模式并跳转）
    return grub_relocator32_boot (relocator, state, 0);
}
```

**步骤 13：grub_relocator32_boot() 执行跳转**

**源代码位置：** `grub/grub-core/lib/i386/relocator.c:75-117`

```c
// grub/grub-core/lib/i386/relocator.c
grub_relocator32_boot (struct grub_relocator *rel, struct grub_relocator32_state state, ...)
{
    // 设置寄存器值
    // grub_relocator32_eip 是 relocator 代码中的一个全局变量
    // 用于存储目标跳转地址，relocator 代码执行时会读取这个变量并加载到 EIP
    grub_relocator32_eip = state.eip;  // 内核入口点地址（code32_start）
    grub_relocator32_esi = state.esi;  // boot_params 地址
    
    // 准备 relocator 代码（切换到保护模式并跳转）
    // 将 relocator 代码复制到 relocator_mem 内存区域
    grub_memmove (relocator_mem, &grub_relocator32_start, ...);
    
    // 执行跳转（关闭中断，切换到保护模式，跳转到 state.eip）
    asm volatile ("cli");
    ((void (*) (void)) relst) ();  // 跳转到 relocator 代码
    // relocator 代码会：
    //   1. 切换到保护模式
    //   2. 设置 GDT
    //   3. 从 grub_relocator32_eip 读取地址并加载到 EIP 寄存器
    //   4. 跳转到内核入口点（code32_start）
    //   5. 此时 ESI 寄存器包含 boot_params 的地址
}
```

**地址来源和加载过程：**

**1. `code32_start` 的来源：**

在 `grub_cmd_linux()` 中计算（步骤 10）：

```c
// grub/grub-core/loader/i386/linux.c
// code32_start 的计算：
linux_params.code32_start = prot_mode_target + 
                            grub_le_to_cpu32 (lh.code32_start) - 
                            GRUB_LINUX_BZIMAGE_ADDR;
// 其中：
// - prot_mode_target: 内核实际加载地址（通常是 0x100000）
// - lh.code32_start: 内核头部中的字段，表示相对于 0x100000 的偏移
// - GRUB_LINUX_BZIMAGE_ADDR: 0x100000（1MB）
```

**2. `state.eip` 的设置：**

在 `grub_linux_boot()` 中设置（步骤 12）：

```c
state.eip = ctx.params->code32_start;  // 从 boot_params 中读取 code32_start
```

**3. `grub_relocator32_eip` 的存储：**

- **存储位置**：`grub_relocator32_eip` 是 relocator 代码中的一个全局变量
- **赋值时机**：在 `grub_relocator32_boot()` 中赋值（第 2353 行）
- **用途**：relocator 代码执行时会读取这个变量

**4. 何时加载到 EIP 寄存器：**

在 relocator 代码执行时（`((void (*) (void)) relst)()` 调用后）：

```asm
; relocator 代码（伪代码，实际在 grub/grub-core/lib/i386/relocator32.S）
relocator32_start:
    ; 1. 切换到保护模式
    ; 2. 设置 GDT
    ; 3. 从 grub_relocator32_eip 读取地址
    mov eax, [grub_relocator32_eip]  ; 读取目标地址
    mov [esp], eax                    ; 准备跳转
    ; 4. 跳转到内核入口点（此时 EIP = code32_start）
    jmp eax                           ; 跳转，EIP 寄存器被设置为 code32_start
```

**关键点总结：**
- **地址来源**：`code32_start` 在 `grub_cmd_linux()` 中计算，存储在 `boot_params` 中
- **传递路径**：`boot_params.code32_start` → `state.eip` → `grub_relocator32_eip`
- **加载时机**：relocator 代码执行时，从 `grub_relocator32_eip` 读取并加载到 EIP 寄存器
- **最终结果**：CPU 的 EIP 寄存器指向内核入口点（`code32_start`），开始执行内核代码

**关键点：**
- **`grub_cmd_linux()`** 只负责加载内核镜像到内存，注册启动函数，不执行跳转
- **`grub_linux_boot()`** 在用户选择启动时被调用，准备跳转参数
- **`grub_relocator32_boot()`** 实际执行跳转，切换到保护模式并跳转到内核入口点（`code32_start`）
- **寄存器状态**：跳转时 `ESI` 包含 `boot_params` 地址，`EIP` 指向内核入口点

**内存布局（加载后）：**

```
内存地址范围              内容
─────────────────────────────────────────
0x100000 (1MB) - ...     vmlinuz 镜像
├─ 0x100000 - 0x1001FF   内核头部（boot_params，512 字节）
├─ 0x100200 - ...        Setup 代码（setup_sects * 512 字节）
└─ Setup 之后           压缩的内核代码（gzip 压缩）
    ↓（解压后）
0x100000+               解压后的内核代码
├─ startup_32           32 位保护模式入口点
└─ startup_64           64 位长模式入口点
```

**内核启动参数传递：**

GRUB 通过 `boot_params` 结构（Linux Boot Protocol）向内核传递参数：

- **`code32_start`**：内核入口点地址（传递给内核，内核从这里开始执行）
- **`cmd_line_ptr`**：内核命令行参数地址（如 `root=/dev/sda1`）
- **`ramdisk_image`**：initramfs 地址
- **`ramdisk_size`**：initramfs 大小
- **`e820_map`**：系统内存映射表
- **`esi` 寄存器**：包含 `boot_params` 的地址（内核通过 `%esi` 访问）

> **详细说明**：关于 vmlinuz 文件结构的完整分析，请参见 [附录：vmlinuz 文件详细结构分析](#附录vmlinuz-文件详细结构分析)。

### 内核早期启动（64 位）

**说明**：内核从 GRUB 跳转后，首先执行的是内核镜像中的 setup 代码（实模式），然后切换到保护模式，最终到达 `startup_64`。GRUB 跳转的地址是 `code32_start`，这是 setup 代码的入口点。

**重要澄清：vmlinuz 文件的压缩结构**

- **vmlinuz 文件包含两部分**：
  1. **Setup 代码**（未压缩）：可以直接执行，GRUB 只是将其从磁盘复制到内存
  2. **压缩的内核代码**（gzip 压缩）：需要由 Setup 代码解压
- **GRUB 的作用**：只是将整个 vmlinuz 文件从磁盘复制到内存，**不解压**
- **解压时机**：由内核自己的 Setup 代码完成解压，不是 GRUB

**详细执行流程：**

```
grub_relocator32_boot() 跳转到内核入口点（code32_start）
    ├─ 源代码位置：grub/grub-core/lib/i386/relocator.c
    ├─ 跳转地址：code32_start（内核头部字段，相对于 0x100000 的偏移）
    └─ 寄存器状态：
        ├─ ESI = boot_params 地址
        ├─ ESP = 栈指针
        └─ EIP = code32_start（内核入口点）
    ↓
Linux 内核 Setup 代码（实模式）
    ├─ 源代码位置：linux/arch/x86/boot/header.S
    ├─ 内存位置：0x100000（1MB）或内核指定的地址
    ├─ 运行模式：实模式（初始阶段）
    ├─ **状态说明**：Setup 代码是未压缩的，可以直接执行
    ├─ 验证内核签名（boot_flag = 0xAA55）
    ├─ 初始化基本环境
    ├─ 切换到保护模式
    └─ 跳转到压缩内核解压代码
        ↓
压缩内核解压代码（startup_32）
    ├─ 源代码位置：linux/arch/x86/boot/compressed/head_64.S
    ├─ 运行模式：32 位保护模式 → 64 位长模式
    ├─ 设置页表（身份映射：物理地址 = 线性地址）
    ├─ 切换到 64 位长模式
    ├─ **解压内核（gzip 解压）**：
    │   ├─ 解压 vmlinuz 文件中的压缩内核代码部分
    │   ├─ 解压目标：0x100000+（覆盖压缩代码区域）
    │   └─ 这是**第一次解压**，由内核自己的代码完成
    └─ 跳转到 startup_64
        ↓
startup_64（64 位内核入口点）
    ├─ 源代码位置：linux/arch/x86/kernel/head_64.S
    ├─ 运行模式：64 位长模式
    ├─ 保存 boot_params 结构地址（%RSI → %R15）
    ├─ 设置初始内核栈
    ├─ 设置 GS 段基址（per-CPU 数据）
    ├─ 设置 GDT 和早期 IDT
    ├─ 切换到内核代码段（__KERNEL_CS）
    ├─ 激活内存加密（SEV/SME，如果支持）
    ├─ 验证和清理 CPU 配置（verify_cpu）
    └─ 继续内核初始化流程
        ↓
内核继续初始化（x86_64_start_kernel）
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

**源代码位置：`linux/arch/x86/kernel/head_64.S:38-100`**

```asm
// Linux 内核 64 位启动入口点
// 此时 CPU 已处于 64 位长模式（CS.L = 1, CS.D = 0）
// Bootloader 已经加载了身份映射页表（物理地址 = 线性地址）
SYM_CODE_START_NOALIGN(startup_64)
	UNWIND_HINT_END_OF_STACK
	
	// 步骤 1: 保存 boot_params 结构地址
	// %RSI 包含 bootloader 提供的 boot_params 物理地址
	// 保存到 %R15，避免后续 C 函数调用破坏它
	mov	%rsi, %r15

	// 步骤 2: 设置初始内核栈（用于 verify_cpu() 等函数）
	leaq	__top_init_kernel_stack(%rip), %rsp

	// 步骤 3: 设置 GS 段基址（用于 per-CPU 数据）
	// 在 SMP 系统中，启动 CPU 使用 init 数据段，直到 per-CPU 区域设置完成
	movl	$MSR_GS_BASE, %ecx  // MSR 寄存器编号
	xorl	%eax, %eax          // 清零 EAX（GS 基址低 32 位）
	xorl	%edx, %edx          // 清零 EDX（GS 基址高 32 位）
	wrmsr                      // 写入 MSR，设置 GS 基址为 0

	// 步骤 4: 设置 GDT（全局描述符表）和早期 IDT（中断描述符表）
	// 这是内核接管中断系统的第一步
	call	__pi_startup_64_setup_gdt_idt

	// 步骤 5: 切换到内核代码段（__KERNEL_CS），确保 IRET 正常工作
	pushq	$__KERNEL_CS        // 压入内核代码段选择子
	leaq	.Lon_kernel_cs(%rip), %rax  // 获取标签地址
	pushq	%rax                // 压入返回地址
	lretq                       // 长返回：弹出 CS 和 RIP，切换到内核代码段

.Lon_kernel_cs:
	ANNOTATE_NOENDBR
	UNWIND_HINT_END_OF_STACK

#ifdef CONFIG_AMD_MEM_ENCRYPT
	// 步骤 6: 激活内存加密（SEV/SME），如果支持
	// 必须在执行 CPUID 之前完成，因为需要设置 SEV-SNP CPUID 表
	movq	%r15, %rdi          // 传递 boot_params 指针作为参数
	call	__pi_sme_enable
#endif

	// 步骤 7: 验证和清理 CPU 配置
	call verify_cpu
```

**关键步骤：**
- **第 74 行**：调用 `__pi_startup_64_setup_gdt_idt` 设置 GDT 和早期 IDT
- 此时内核已切换到 64 位长模式

### 早期 IDT 设置

源代码位置：`linux/arch/x86/kernel/head64.c:276-292`

```c
	// 步骤 1: 设置早期中断处理程序
	// 建立内核自己的 IDT，取代 BIOS 的 IVT
	// 此时中断将路由到内核处理程序，而不是 BIOS
	idt_setup_early_handler();

	// 步骤 2: TDX（Trust Domain Extensions）早期初始化
	// 在调用 cc_platform_has() 之前需要完成
	tdx_early_init();

	// 步骤 3: 复制引导数据（从实模式数据区域）
	copy_bootdata(__va(real_mode_data));

	// 步骤 4: 在启动 CPU（BSP）上早期加载微码更新
	// 微码更新修复 CPU 硬件缺陷，必须在早期加载
	load_ucode_bsp();

	// 步骤 5: 设置内核高地址映射
	// 将 early_top_pgt 的最后一个条目复制到 init_top_pgt
	init_top_pgt[511] = early_top_pgt[511];

	// 步骤 6: 启动内核预留区域初始化，最终调用 start_kernel()
	x86_64_start_reservations(real_mode_data);
}
```

**关键点：**
- **第 276 行**：`idt_setup_early_handler()` 设置早期中断处理程序

源代码位置：`linux/arch/x86/kernel/idt.c:216-227`

```c
/**
 * idt_setup_early_traps - 初始化 IDT 表，设置早期陷阱处理程序
 *
 * 在 x86_64 上，这些陷阱不使用中断栈（IST），因为在 cpu_init() 调用
 * 并设置 TSS 之前无法工作。IST 变体在那之后安装。
 */
void __init idt_setup_early_traps(void)
{
	// 步骤 1: 从 early_idts 表设置 IDT 条目
	// early_idts 包含早期需要的异常处理程序（如页故障、除零等）
	idt_setup_from_table(idt_table, early_idts, ARRAY_SIZE(early_idts),
			     true);
	
	// 步骤 2: 加载 IDT 到 CPU
	// 使用 LIDT 指令将 idt_descr 加载到 IDTR 寄存器
	// 从这一刻起，CPU 使用内核的 IDT 而不是 BIOS 的 IVT
	load_idt(&idt_descr);
}
```

**说明：**
- 内核建立自己的 IDT（中断描述符表），取代 BIOS 的 IVT
- 早期陷阱处理程序用于处理 CPU 异常（如页故障、除零等）

### 中断控制器接管

#### 8259A PIC 重新编程

源代码位置：`linux/arch/x86/kernel/i8259.c:349-399`

```c
// 重新编程 8259A PIC：将硬件中断从 BIOS 的向量（0x08-0x0F, 0x70-0x77）
// 重映射到内核的向量（0x20-0x2F），避免与 CPU 异常向量（0-31）冲突
static void init_8259A(int auto_eoi)
{
	unsigned long flags;

	i8259A_auto_eoi = auto_eoi;  // 保存自动 EOI 设置

	raw_spin_lock_irqsave(&i8259A_lock, flags);  // 加锁保护

	// 步骤 1: 屏蔽主 PIC 的所有中断（0xFF = 所有位都屏蔽）
	outb(0xff, PIC_MASTER_IMR);

	// 步骤 2: 初始化主 PIC（8259A-1）
	// ICW1: 0x11 = 边沿触发、级联模式、需要 ICW4
	outb_pic(0x11, PIC_MASTER_CMD);

	// ICW2: 将主 PIC 的 IRQ0-7 映射到 ISA_IRQ_VECTOR(0)（通常是 0x20-0x27）
	// 这覆盖了 BIOS 的配置（BIOS 映射到 0x08-0x0F）
	outb_pic(ISA_IRQ_VECTOR(0), PIC_MASTER_IMR);

	// ICW3: 主 PIC 在 IR2 上有从 PIC（级联）
	outb_pic(1U << PIC_CASCADE_IR, PIC_MASTER_IMR);

	// ICW4: 设置主 PIC 的工作模式
	if (auto_eoi)
		// 自动 EOI 模式：中断处理完成后自动发送 EOI
		outb_pic(MASTER_ICW4_DEFAULT | PIC_ICW4_AEOI, PIC_MASTER_IMR);
	else
		// 正常 EOI 模式：需要手动发送 EOI
		outb_pic(MASTER_ICW4_DEFAULT, PIC_MASTER_IMR);

	// 步骤 3: 初始化从 PIC（8259A-2）
	// ICW1: 选择从 PIC 初始化
	outb_pic(0x11, PIC_SLAVE_CMD);

	// ICW2: 将从 PIC 的 IRQ8-15 映射到 ISA_IRQ_VECTOR(8)（通常是 0x28-0x2F）
	// 这覆盖了 BIOS 的配置（BIOS 映射到 0x70-0x77）
	outb_pic(ISA_IRQ_VECTOR(8), PIC_SLAVE_IMR);
	
	// ICW3: 从 PIC 连接到主 PIC 的 IR2
	outb_pic(PIC_CASCADE_IR, PIC_SLAVE_IMR);
	
	// ICW4: 设置从 PIC 的工作模式
	outb_pic(SLAVE_ICW4_DEFAULT, PIC_SLAVE_IMR);

	// 步骤 4: 根据 EOI 模式设置中断确认函数
	if (auto_eoi)
		// AEOI 模式：确认时只需屏蔽中断
		i8259A_chip.irq_mask_ack = disable_8259A_irq;
	else
		// 正常模式：确认时需要屏蔽并发送 EOI
		i8259A_chip.irq_mask_ack = mask_and_ack_8259A;

	// 步骤 5: 等待 PIC 初始化完成（硬件需要时间）
	udelay(100);

	// 步骤 6: 恢复之前保存的中断屏蔽位
	outb(cached_master_mask, PIC_MASTER_IMR);
	outb(cached_slave_mask, PIC_SLAVE_IMR);

	raw_spin_unlock_irqrestore(&i8259A_lock, flags);  // 解锁
}
```

**关键点：**
- **第 365 行**：将主 PIC 的 IRQ0-7 重映射到 `ISA_IRQ_VECTOR(0)`（通常是 0x20-0x27），避免与 CPU 异常向量（0-31）冲突
- **第 378 行**：将从 PIC 的 IRQ8-15 重映射到 `ISA_IRQ_VECTOR(8)`（通常是 0x28-0x2F）
- 这**完全覆盖了 BIOS 的 PIC 配置**，硬件中断不再路由到 BIOS 代码

#### APIC 和中断门设置

源代码位置：`linux/arch/x86/kernel/idt.c:281-315`

```c
/**
 * idt_setup_apic_and_irq_gates - 设置 APIC/SMP 和普通中断门
 * 
 * 这是内核完全接管中断系统的最后一步：
 * 1. 设置 APIC 相关的中断门
 * 2. 为所有外部中断（IRQ）设置中断门
 * 3. 加载 IDT，此时 BIOS 的 IVT 被完全取代
 */
void __init idt_setup_apic_and_irq_gates(void)
{
	int i = FIRST_EXTERNAL_VECTOR;  // 第一个外部中断向量（通常是 0x20）
	void *entry;

	// 步骤 1: 从 apic_idts 表设置 APIC 相关的中断门
	// 包括本地 APIC 中断、SMP IPI 等
	idt_setup_from_table(idt_table, apic_idts, ARRAY_SIZE(apic_idts), true);

	// 步骤 2: 为所有外部中断（IRQ）设置中断门
	// FIRST_EXTERNAL_VECTOR 到 FIRST_SYSTEM_VECTOR 是 IRQ 向量范围
	for_each_clear_bit_from(i, system_vectors, FIRST_SYSTEM_VECTOR) {
		// 计算中断入口地址：irq_entries_start + 对齐偏移
		entry = irq_entries_start + IDT_ALIGN * (i - FIRST_EXTERNAL_VECTOR);
		set_intr_gate(i, entry);  // 设置中断门（自动关闭中断）
	}

#ifdef CONFIG_X86_LOCAL_APIC
	// 步骤 3: 为系统向量设置中断门（APIC 伪中断等）
	for_each_clear_bit_from(i, system_vectors, NR_VECTORS) {
		// 不设置 system_vectors 位图中未分配的系统向量
		// 否则它们会出现在 /proc/interrupts 中
		entry = spurious_entries_start + IDT_ALIGN * (i - FIRST_SYSTEM_VECTOR);
		set_intr_gate(i, entry);
	}
#endif
	
	// 步骤 4: 将 IDT 映射到 CPU 入口区域并重新加载
	// CPU 入口区域是内核中的固定只读区域，用于存放 IDT 等关键数据结构
	idt_map_in_cea();
	load_idt(&idt_descr);  // 加载 IDT：此时 BIOS IVT 被完全取代

	// 步骤 5: 将 IDT 表设置为只读（防止被恶意修改）
	set_memory_ro((unsigned long)&idt_table, 1);

	// 步骤 6: 标记 IDT 设置完成
	idt_setup_done = true;
}
```

**说明：**
- **第 289 行**：设置 APIC 相关的中断门
- **第 291-294 行**：为外部中断（IRQ）设置中断门，指向 `irq_entries_start`
- **第 309 行**：加载新的 IDT（`load_idt(&idt_descr)`），**此时 BIOS 的 IVT 被完全取代**

> **注意**：关于 BIOS IVT 与 Kernel IDT 的详细对比，请参见 [BIOS IVT vs Kernel IDT 详细对比](BIOS_IVT_VS_KERNEL_IDT.md)。  
> 关于 UEFI 中断处理机制，请参见 [UEFI 中断处理机制](UEFI_INTERRUPT_HANDLING.md)。

### 接管完成标志

从内核加载 IDT 并重新编程 PIC 的那一刻起：

1. **硬件中断不再路由到 BIOS**：PIC 被重新编程，中断向量映射到内核的 IDT
2. **软件中断被内核接管**：所有 `INT` 指令触发的异常由内核的 IDT 处理
3. **BIOS 代码不再执行**：除了可能的 UEFI Runtime Services，BIOS 固件代码基本不再被调用

---

## 总结：完整流程时间线

以下是从 QEMU 启动到 Linux 内核完全接管系统的完整流程时间线：

```
QEMU 启动
    ↓
加载 SeaBIOS 到内存顶部（0xFFFFFFFF - bios_size）
    ↓
CPU 复位，从 0xFFFF0 开始执行 SeaBIOS
    ↓
SeaBIOS POST 初始化
    ├─ 初始化 IVT（中断向量表）
    ├─ 初始化 PIC（中断控制器）
    ├─ 初始化硬件设备
    └─ 调用 startBoot() → INT 19h
    ↓
INT 19h 处理程序（handle_19）
    ├─ 重置引导序列号
    └─ 调用 do_boot(0)
    ↓
do_boot() 选择引导设备
    ├─ 软盘（0x00）
    ├─ 硬盘（0x80）← 通常选择这个
    └─ CD-ROM 等
    ↓
boot_disk() 读取引导扇区
    ├─ 调用 INT 13h（AH=0x02）读取第一个扇区
    ├─ 加载到内存地址 0x7C00（段:偏移 = 0x07C0:0x0000）
    ├─ 验证引导扇区签名（0xAA55）
    └─ 跳转到 0x0000:0x7C00 执行，DL = 驱动器号（0x00 或 0x80 等）
    ↓
【阶段 1】boot.S（引导扇区，grub/grub-core/boot/i386/pc/boot.S）
    ├─ 磁盘位置：扇区 0（MBR）或 El Torito 引导扇区（ISO 镜像）
    ├─ 内存位置：0x7C00
    ├─ 大小：512 字节
    ├─ 引导模式：
    │   ├─ 标准模式：kernel_sector 在偏移 0x5c（传统磁盘安装）
    │   └─ HYBRID_BOOT 模式：kernel_sector 在偏移 0x1b0（ISO 镜像）
    ├─ 从 DL 寄存器读取驱动器号（BIOS 传递的）
    ├─ 保存驱动器号（pushw %dx）
    ├─ 初始化段寄存器和栈
    ├─ 检测磁盘访问模式（LBA 或 CHS）
    ├─ 从 kernel_sector 读取 GRUB Core 第一个扇区（512 字节）
    │   ├─ 标准模式：从偏移 0x5c 读取 kernel_sector
    │   ├─ HYBRID_BOOT 模式：从偏移 0x1b0 读取 kernel_sector
    │   └─ 先读到临时缓冲区 0x7000:0x0000
    ├─ 复制到最终地址 0x0000:0x8000
    └─ 跳转到 0x8000（diskboot.S 入口点）
        └─ 代码：`jmp *(LOCAL(kernel_address))`（第 886 行）
    ↓
【阶段 2】diskboot.S（GRUB Core 第一个扇区，grub/grub-core/boot/i386/pc/diskboot.S）
    ├─ 磁盘位置：其他扇区（由 kernel_sector 指定，例如扇区 2048）
    ├─ 内存位置：0x8000
    ├─ 大小：512 字节（包含 diskboot.S 代码约 0.5KB + 块列表 12 字节）
    ├─ 保存驱动器号
    ├─ 读取块列表（从 0x8000 的末尾）
    ├─ 循环读取每个块列表条目指定的扇区
    │   ├─ 使用 INT 13h 读取扇区到临时缓冲区（0x7000）
    │   └─ 复制到目标地址（块列表中的 segment）
    └─ 所有扇区加载完成后，跳转到 0x8200（startup_raw.S 入口点）
    ↓
【阶段 3】startup_raw.S（GRUB Core 实模式入口，grub/grub-core/boot/i386/pc/startup_raw.S）
    ├─ 内存位置：0x8200
    ├─ 设置实模式段寄存器和栈
    ├─ 保存启动驱动器号
    ├─ 从实模式切换到保护模式（calll real_to_prot）
    │   └─ 源代码：grub/grub-core/kern/i386/realmode.S:real_to_prot()
    ├─ 启用 A20 地址线（call grub_gate_a20）
    ├─ 处理 Reed-Solomon 错误纠正（如果启用）
    ├─ 解压 GRUB Core（如果使用 LZMA 压缩）
    │   └─ 解压到 GRUB_MEMORY_MACHINE_DECOMPRESSION_ADDR
    └─ 跳转到解压后的代码入口点（jmp *%esi）
    │   └─ %esi 指向解压后的代码（grub_stub_init()）
    ↓
【阶段 3.5】解压后的代码入口点（grub_stub_init）
    ├─ 运行模式：保护模式
    ├─ 初始化 GRUB 核心功能
    │   ├─ 内存管理（grub_mm_init）
    │   ├─ 设备驱动初始化
    │   └─ 其他核心功能
    └─ 调用 grub_main()
    ↓
【阶段 4】grub_main()（GRUB Core C 代码入口，grub/grub-core/kern/main.c）
    ├─ 运行模式：保护模式
    ├─ 初始化 GRUB 核心功能
    ├─ 解析 GRUB 配置文件（grub.cfg）
    ├─ 显示启动菜单（如果配置）
    ├─ 用户选择启动项后，执行命令处理机制
    │   └─ 调用命令处理函数（例如：`grub_cmd_linux()`）
    │       ↓
    │   【阶段 4.1】grub_cmd_linux()（grub/grub-core/loader/i386/linux.c）
    │       ├─ 打开内核文件（如 /boot/vmlinuz-5.x.x）
    │       ├─ 读取内核文件头部
    │       ├─ 计算内核加载地址（通常 0x100000，1MB）
    │       ├─ 设置内核启动参数（boot_params）
    │       ├─ 加载内核镜像到内存
    │       └─ 注册启动函数（grub_loader_set）
    │           └─ 设置 grub_linux_boot() 为启动函数
    │       ↓
    │   【阶段 4.2】grub_linux_boot()（grub/grub-core/loader/i386/linux.c）
    │       ├─ 准备 boot_params 结构（包含 code32_start）
    │       ├─ 设置寄存器状态（通过 relocator）
    │       └─ 跳转到内核入口点（code32_start）
    │           └─ 通过 grub_relocator32_boot() 执行跳转
    ├─ 加载 initramfs（如果配置，通过 grub_cmd_initrd()）
    └─ 执行启动函数（grub_linux_boot()）→ 跳转到内核入口点
    ↓
【阶段 5】Linux 内核 Setup 代码（实模式，linux/arch/x86/boot/header.S）
    ├─ 内存位置：0x100000（1MB）或内核指定的地址
    ├─ 运行模式：实模式（初始阶段）
    ├─ 验证内核签名
    ├─ 初始化基本环境
    ├─ 切换到保护模式/长模式
    └─ 跳转到压缩内核解压代码
    ↓
【阶段 6】压缩内核解压（linux/arch/x86/boot/compressed/head_64.S）
    ├─ 运行模式：长模式（64位）
    ├─ 解压内核镜像（gzip 解压）
    ├─ 设置早期页表
    └─ 跳转到解压后的内核入口点（startup_64）
    ↓
【阶段 7】startup_64（Linux 内核 64 位入口，linux/arch/x86/kernel/head_64.S）
    ├─ 运行模式：长模式（64位）
    ├─ 保存 boot_params 结构地址
    ├─ 设置初始内核栈
    ├─ 设置 GDT 和早期 IDT（__pi_startup_64_setup_gdt_idt）
    │   └─ 这是内核接管中断系统的第一步
    ├─ 切换到内核代码段
    └─ 跳转到 x86_64_start_kernel()
    ↓
【阶段 8】x86_64_start_kernel()（linux/arch/x86/kernel/head64.c）
    ├─ 设置早期中断处理程序（idt_setup_early_handler）
    │   └─ 建立内核自己的 IDT，取代 BIOS 的 IVT
    ├─ TDX 早期初始化（如果支持）
    ├─ 复制引导数据
    ├─ 早期加载微码更新
    └─ 调用 start_kernel()
    ↓
【阶段 9】start_kernel()（Linux 内核主初始化，linux/init/main.c）
    ├─ 初始化中断系统
    │   ├─ 重新编程 PIC（init_8259A）
    │   │   └─ 将硬件中断从 BIOS 的向量（0x08-0x0F）重映射到内核的向量（0x20-0x2F）
    │   ├─ 设置 APIC 和中断门（idt_setup_apic_and_irq_gates）
    │   │   └─ 为所有外部中断（IRQ）设置中断门
    │   └─ 加载 IDT（load_idt）
    │       └─ **此时 BIOS 的 IVT 被完全取代**
    ├─ 初始化内存管理
    ├─ 初始化进程管理
    ├─ 初始化设备驱动
    └─ 启动 init 进程（PID 1）
    ↓
【阶段 10】Linux 内核完全接管系统
    ├─ BIOS 的 IVT 被内核的 IDT 取代
    ├─ BIOS 的 PIC 配置被内核重新编程
    ├─ BIOS 代码基本不再执行
    └─ 系统运行在 Linux 内核控制下
```

**关键文件路径和源代码位置：**

| 阶段 | 文件 | 源代码位置 | 内存地址 | 运行模式 |
|------|------|-----------|---------|---------|
| **阶段 1** | boot.S | `grub/grub-core/boot/i386/pc/boot.S` | `0x7C00` | 实模式 |
| **阶段 2** | diskboot.S | `grub/grub-core/boot/i386/pc/diskboot.S` | `0x8000` | 实模式 |
| **阶段 3** | startup_raw.S | `grub/grub-core/boot/i386/pc/startup_raw.S` | `0x8200` | 实模式→保护模式 |
| | lzma_decode.S | `grub/grub-core/boot/i386/pc/lzma_decode.S` | `0x8200+` | 实模式→保护模式 |
| | | （通过 `#include` 包含在 startup_raw.S 中，随 startup_raw.S 一起在阶段 2 加载） | | |
| **阶段 3.5** | 解压后的代码入口点 | 解压后的代码（通常是 grub_stub_init） | 解压后地址 | 保护模式 |
| **阶段 4** | grub_main() | `grub/grub-core/kern/main.c` | 解压后地址 | 保护模式 |
| **阶段 5** | Setup 代码 | `linux/arch/x86/boot/header.S` | `0x100000` | 实模式 |
| **阶段 6** | head_64.S（解压） | `linux/arch/x86/boot/compressed/head_64.S` | `0x100000+` | 长模式 |
| **阶段 7** | startup_64 | `linux/arch/x86/kernel/head_64.S` | 解压后地址 | 长模式 |
| **阶段 8** | x86_64_start_kernel() | `linux/arch/x86/kernel/head64.c` | 内核地址空间 | 长模式 |
| **阶段 9** | start_kernel() | `linux/init/main.c` | 内核地址空间 | 长模式 |

### 关键时间节点

| 阶段 | 关键事件 | 内存地址/中断 |
|------|---------|--------------|
| **QEMU 启动** | 加载 SeaBIOS | `0xFFFFFFFF - bios_size` |
| **CPU 复位** | 开始执行 SeaBIOS | `0xFFFF0` |
| **SeaBIOS POST** | 初始化 IVT 和 PIC | IVT: `0x0000:0x0000`, PIC: `0x20/0x21` |
| **INT 19h** | 开始引导流程 | `INT 19h` |
| **读取引导扇区** | 加载到内存 | `0x7C00` |
| **引导扇区执行** | 用户代码开始运行 | `0x0000:0x7C00` |
| **GRUB 加载内核** | 内核镜像加载 | `0x100000` (1MB) |
| **内核入口** | head_64.S 开始执行 | `head_64.S` |
| **IDT 接管** | 内核建立自己的 IDT | `load_idt(&idt_descr)` |
| **PIC 重新编程** | 中断路由到内核 | `init_8259A()` |
| **完全接管** | BIOS 不再处理中断 | 所有中断由内核处理 |

---

### 附录：vmlinuz 文件详细结构分析

**文件格式概述：**

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

**1. 内核头部（boot_params 结构）**

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

**关键字段说明：**

- **`boot_flag`**（偏移 0x0000）：必须是 `0xAA55`，用于验证这是有效的内核镜像
- **`header`**（偏移 0x0004）：必须是 `"HdrS"` (0x53726448)，用于验证内核头部格式
- **`setup_sects`**（偏移 0x000E）：Setup 代码的扇区数（512 字节/扇区），通常为 4-64
- **`code32_start`**（偏移 0x0028）：32 位保护模式代码入口点，相对于 `0x100000` 的偏移
- **`pref_address`**（偏移 0x0030）：内核首选加载地址，通常为 `0x100000` (1MB)
- **`init_size`**（偏移 0x0038）：初始化代码总大小（setup + 压缩内核）

**2. Setup 代码部分**

**源代码位置：** `linux/arch/x86/boot/header.S`

Setup 代码紧跟在 512 字节头部之后，大小由 `setup_sects` 字段指定（通常 4-64 个扇区，即 2-32 KB）：

- **功能**：
  - 验证内核签名（`boot_flag = 0xAA55`）
  - 初始化基本环境（段寄存器、栈等）
  - 切换到保护模式或长模式
  - 解压压缩的内核代码
  - 跳转到解压后的内核入口点（`startup_32` 或 `startup_64`）

- **内存位置**：加载到 `0x100000` (1MB) 或内核指定的地址

**3. 压缩的内核代码部分**

**源代码位置：** `linux/arch/x86/boot/compressed/head_64.S`

压缩的内核代码位于 Setup 代码之后，是 gzip 压缩的完整 vmlinux：

- **格式**：gzip 压缩
- **内容**：完整的 vmlinux（未压缩的内核二进制文件）
- **解压目标**：`0x100000` (1MB) 或更高地址
- **解压后**：包含 `startup_32`（32 位保护模式入口）和 `startup_64`（64 位长模式入口）

**验证 vmlinuz 文件的方法：**

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

---

## 技术细节说明

> **详细说明**：本文档主线的详细技术说明和补充信息，请参见 [BOOT_FLOW 技术细节说明](BOOT_FLOW_NOTES.md)。  
> 关于 BIOS 128KB 内存映射的硬件实现（地址解码器、内存控制器），请参见 [技术细节说明 - Note 7: BIOS 128KB 内存映射的硬件实现](BOOT_FLOW_NOTES.md#note-7-bios-128kb-内存映射的硬件实现)。

---

## Q&A：常见问题解答

> **常见问题**：关于启动流程的常见问题解答，请参见 [BOOT_FLOW 常见问题解答](BOOT_FLOW_QA.md)。

### Q: MBR在什么位置？BIOS读取MBR的过程是否把程序从磁盘copy到了内存？

**A: MBR存储在磁盘的第一个扇区（扇区0，LBA地址0）。是的，这是一个从磁盘到内存的拷贝过程。BIOS通过INT 13h磁盘服务将MBR从磁盘的第一个扇区读取（拷贝）到内存地址0x7C00。**

#### MBR的位置

1. **磁盘上的物理位置**
   - **扇区号**：第 0 个扇区（LBA = 0，或 CHS = 0:0:1）
   - **大小**：512 字节（1 个扇区）
   - **存储设备**：硬盘、USB 驱动器、软盘等可引导存储设备
   - **写入方式**：由引导加载器安装程序（如 `grub-install`）写入

2. **磁盘布局**
   ```
   磁盘物理布局：
   
   扇区 0（LBA 0）：
   └─ MBR（512 字节）
      ├─ 引导代码（446 字节）
      ├─ 分区表（64 字节，4 个分区项）
      └─ 引导签名（2 字节：0xAA55）
   
   扇区 1 及以后：
   └─ 分区数据、文件系统等
   ```

3. **MBR 的访问方式**
   - **BIOS 访问**：通过 INT 13h 磁盘服务读取
   - **读取参数**：
     - 驱动器号：`DL = 0x80`（第一块硬盘）或 `0x00`（软盘）
     - 扇区号：`CL = 1`（CHS 格式，扇区从 1 开始编号）或 LBA = 0
     - 读取数量：1 个扇区（512 字节）
     - 目标地址：`0x7C00`（内存地址）

#### 是否拷贝到内存？

**答案：是的，这是一个从磁盘到内存的拷贝过程。**

1. **拷贝过程**
   ```
   磁盘扇区 0（MBR，512 字节）
   ↓ [INT 13h 磁盘读取]
   内存地址 0x7C00（512 字节）
   ```

2. **拷贝机制**
   - **读取操作**：BIOS 调用 INT 13h（AH=0x02）从磁盘读取数据
   - **数据传输**：磁盘控制器将数据从磁盘传输到内存
   - **目标地址**：数据被写入内存地址 `0x7C00 - 0x7DFF`（512 字节）
   - **这是真正的拷贝**：数据从磁盘复制到内存，磁盘上的原始数据保持不变

3. **目标地址设置的具体代码**
   
   **关键问题：数据被写入内存地址 `0x7C00 - 0x7DFF` 对应的具体代码是什么？**
   
   **答案：通过设置 `br.es = bootseg`（0x07C0）和 `br.bx = 0`（通过 memset 初始化为0），形成 ES:BX = 0x07C0:0x0000，物理地址 = 0x7C00。**
   
   **SeaBIOS 源代码分析：**
   
   ```c
   // SeaBIOS 源代码：src/boot.c:boot_disk()
   static void
   boot_disk(u8 bootdrv, int checksig)
   {
       u16 bootseg = 0x07c0;  // 引导扇区加载地址：段地址 0x07C0
                              // 物理地址 = 0x07C0 * 16 + 0x0000 = 0x7C00
   
       // 步骤 1: 使用 INT 13h 读取引导扇区（512 字节）
       struct bregs br;
       memset(&br, 0, sizeof(br));  // 初始化所有寄存器为0，包括 BX = 0
       br.flags = F_IF;      // 允许中断
       br.dl = bootdrv;      // DL = 驱动器号（0x00 软盘，0x80 硬盘）
       br.es = bootseg;      // ES = 目标段地址（0x07C0）← 关键代码1
       // br.bx = 0;         // BX = 0（通过 memset 已初始化为0）← 关键代码2
       br.ah = 2;            // AH = 0x02：读扇区功能
       br.al = 1;            // AL = 读取扇区数（1 个扇区 = 512 字节）
       br.cl = 1;            // CL = 扇区号（第 1 个扇区）
       call16_int(0x13, &br);  // 调用 INT 13h 磁盘服务
   }
   ```
   
   **目标地址计算：**
   
   ```
   ES:BX = 0x07C0:0x0000
   
   物理地址 = ES × 16 + BX
           = 0x07C0 × 16 + 0x0000
           = 0x7C00 + 0x0000
           = 0x7C00
   
   地址范围：0x7C00 - 0x7DFF（512 字节 = 0x200 字节）
   ``
   
   **INT 13h AH=0x02 的寄存器要求：**
   
   | 寄存器 | 值 | 说明 |
   |--------|-----|------|
   | **AH** | `0x02` | 功能号：读扇区 |
   | **AL** | `1` | 读取扇区数（1 个扇区 = 512 字节） |
   | **DL** | `0x80` | 驱动器号（0x80 = 第一块硬盘） |
   | **DH** | `0` | 磁头号（CHS 模式，通过 memset 初始化为0） |
   | **CH** | `0` | 柱面号低8位（CHS 模式，通过 memset 初始化为0） |
   | **CL** | `1` | 扇区号（第 1 个扇区，CHS 模式） |
   | **ES:BX** | `0x07C0:0x0000` | **目标缓冲区地址**（物理地址 0x7C00） |
   
   **关键代码行：**
   
   1. **`br.es = bootseg;`**（第621行）
      - 设置 ES 寄存器为 `0x07C0`（段地址）
      - 这是目标缓冲区的段地址
   
   2. **`memset(&br, 0, sizeof(br));`**（第618行）
      - 将 `struct bregs` 结构体所有字段初始化为 0
      - 这包括 `br.bx = 0`（BX 寄存器初始化为 0）
      - BX 是目标缓冲区的偏移地址
   
   3. **`call16_int(0x13, &br);`**（第625行）
      - 调用 INT 13h 中断服务
      - BIOS 的 INT 13h 处理程序读取 `br` 结构体中的寄存器值
      - 使用 `ES:BX = 0x07C0:0x0000` 作为目标缓冲区地址
      - 将磁盘扇区 0 的 512 字节数据拷贝到内存地址 `0x7C00 - 0x7DFF`
   
   **INT 13h 处理程序内部实现（简化）：**
   
   ```c
   // BIOS INT 13h 处理程序（简化示例）
   void int13_handler(struct bregs *br) {
       if (br->ah == 0x02) {  // 读扇区功能
           // 计算目标物理地址
           u32 target_addr = (br->es << 4) + br->bx;
           // target_addr = 0x07C0 * 16 + 0x0000 = 0x7C00
           
           // 从磁盘读取扇区
           u8 sector = br->cl;  // 扇区号
           u8 drive = br->dl;   // 驱动器号
           
           // 调用磁盘控制器读取扇区到内存
           disk_read_sector(drive, sector, target_addr, 512);
           // 将磁盘扇区0的512字节数据拷贝到内存地址0x7C00
       }
   }
   ```
   
   **数据拷贝过程：**
   
   ```
   磁盘扇区 0（512 字节）
   ↓ [磁盘控制器 DMA 传输]
   内存地址 0x7C00 - 0x7DFF（512 字节）
   
   具体过程：
   1. BIOS INT 13h 处理程序接收参数：ES:BX = 0x07C0:0x0000
   2. 计算物理地址：0x07C0 × 16 + 0x0000 = 0x7C00
   3. 调用磁盘控制器读取扇区 0
   4. 磁盘控制器通过 DMA 将数据从磁盘传输到内存地址 0x7C00
   5. 512 字节数据被写入内存地址 0x7C00 - 0x7DFF
   ```
   
   **验证代码：**
   
   ```c
   // 步骤 3: 验证引导扇区签名（0xAA55）
   if (checksig) {
       struct mbr_s *mbr = (void*)0;  // 在段 0x07C0 的偏移 0 处
       // 这相当于访问物理地址 0x7C00
       if (GET_FARVAR(bootseg, mbr->signature) != MBR_SIGNATURE) {
           printf("Boot failed: not a bootable disk\n\n");
           return;
       }
   }
   ```
   
   这段代码验证了数据确实被拷贝到了 `0x7C00`，因为它读取了该地址的签名（偏移 0x1FE 处的 0xAA55）。

4. **与BIOS ROM映射的区别**
   | 特性 | BIOS ROM | MBR（引导扇区） |
   |------|---------|----------------|
   | **存储位置** | Flash ROM芯片 | 磁盘扇区0 |
   | **访问方式** | 硬件地址映射（MMIO） | 磁盘I/O读取 |
   | **是否拷贝** | ❌ 映射，不是拷贝 | ✅ **是拷贝** |
   | **内存位置** | 映射到 `0xE0000-0xFFFFF` 和 `0xFFFF80000-0xFFFFFFFF` | 拷贝到 `0x7C00` |
   | **数据持久性** | ROM中永久存储 | 磁盘中永久存储 |
   | **可修改性** | 只读（需要特殊工具刷写） | 可读写（通过磁盘I/O） |

5. **拷贝的详细流程**
   ```
   步骤1：BIOS调用INT 13h
   ├─ 功能号：AH = 0x02（读扇区）
   ├─ 驱动器：DL = 0x80（第一块硬盘）
   ├─ 扇区号：CL = 1（CHS）或 LBA = 0
   ├─ 读取数量：AL = 1（1个扇区 = 512字节）
   └─ 目标地址：ES:BX = 0x07C0:0x0000（物理地址0x7C00）
   
   步骤2：磁盘控制器读取扇区
   ├─ 磁盘控制器定位到扇区0
   ├─ 从磁盘读取512字节数据
   └─ 通过数据总线传输到内存
   
   步骤3：数据写入内存
   ├─ 数据被写入内存地址0x7C00-0x7DFF
   ├─ 这是真正的内存拷贝（不是映射）
   └─ 磁盘上的原始数据保持不变
   
   步骤4：验证和跳转
   ├─ BIOS验证MBR签名（0xAA55）
   └─ 跳转到0x7C00执行引导代码
   ```

6. **为什么需要拷贝？**
   - **执行需求**：CPU只能执行内存中的代码，不能直接执行磁盘上的代码
   - **性能考虑**：内存访问速度远快于磁盘访问速度
   - **地址要求**：引导代码需要特定的内存地址（0x7C00）才能正确执行
   - **独立性**：拷贝后，引导代码可以在内存中独立运行，不依赖磁盘访问

7. **拷贝 vs 映射的对比**
   ```
   BIOS ROM（映射）：
   磁盘/ROM → [硬件地址映射] → CPU地址空间
   └─ 数据仍在ROM中，通过地址映射访问
   └─ 不是拷贝，是硬件路由
   
   MBR（拷贝）：
   磁盘扇区0 → [INT 13h读取] → 内存0x7C00
   └─ 数据从磁盘复制到内存
   └─ 是真正的拷贝操作
   ```

---

## 关键源代码文件索引

本文档涉及的关键源代码文件位置索引，方便快速查找：

### QEMU 源代码

| 文件路径 | 功能说明 | 相关章节 |
|---------|---------|---------|
| `qemu/hw/i386/pc_sysfw.c:215-285` | 系统固件初始化，加载 SeaBIOS | [QEMU 加载 SeaBIOS](#qemu-加载-seabios) |
| `qemu/hw/i386/x86-common.c:1027-1092` | x86 平台初始化 | [QEMU 加载 SeaBIOS](#qemu-加载-seabios) |
| `qemu/target/i386/cpu.c:9130-9149` | CPU 复位向量设置（0xFFFF0） | [QEMU 加载 SeaBIOS](#qemu-加载-seabios) |

### SeaBIOS 源代码

| 文件路径 | 功能说明 | 相关章节 |
|---------|---------|---------|
| `seabios/src/romlayout.S:687-690` | reset_vector 定义（ORG 0xfff0） | [Reset Vector 设置机制](#reset-vector-设置机制) |
| `seabios/src/romlayout.S:589-591` | ORG 宏定义 | [Reset Vector 设置机制](#reset-vector-设置机制) |
| `seabios/scripts/layoutrom.py:74-82` | 链接器脚本处理固定地址段 | [Reset Vector 设置机制](#reset-vector-设置机制) |
| `seabios/src/post.c:302-337` | POST 主入口点 | [SeaBIOS 初始化中断服务](#seabios-初始化中断服务) |
| `seabios/src/post.c:196-235` | maininit() 主初始化函数 | [SeaBIOS 初始化中断服务](#seabios-初始化中断服务) |
| `seabios/src/post.c:32-71` | ivt_init() IVT 初始化 | [SeaBIOS 初始化中断服务](#seabios-初始化中断服务) |
| `seabios/src/hw/pic.c:62-66` | pic_setup() PIC 初始化 | [SeaBIOS 初始化中断服务](#seabios-初始化中断服务) |
| `seabios/src/post.c:137-158` | interface_init() 接口初始化 | [SeaBIOS 初始化中断服务](#seabios-初始化中断服务) |
| `seabios/src/post.c:182-193` | startBoot() 启动引导 | [BIOS 引导流程：从 SeaBIOS 到引导扇区](#bios-引导流程从-seabios-到引导扇区) |
| `seabios/src/boot.c:1040-1046` | handle_19() INT 19h 处理程序 | [BIOS 引导流程：从 SeaBIOS 到引导扇区](#bios-引导流程从-seabios-到引导扇区) |
| `seabios/src/boot.c:882-917` | boot_disk() 读取引导扇区 | [BIOS 引导流程：从 SeaBIOS 到引导扇区](#bios-引导流程从-seabios-到引导扇区) |
| `seabios/src/boot.c:987-1025` | do_boot() 引导设备选择 | [BIOS 引导流程：从 SeaBIOS 到引导扇区](#bios-引导流程从-seabios-到引导扇区) |

### GRUB 源代码

| 文件路径 | 功能说明 | 相关章节 |
|---------|---------|---------|
| `grub/grub-core/boot/i386/pc/boot.S` | GRUB 引导扇区代码 | [BIOS 引导流程：从 SeaBIOS 到引导扇区](#bios-引导流程从-seabios-到引导扇区) |
| `grub/grub-core/boot/i386/pc/diskboot.S:38-341` | 磁盘引导代码 | [BIOS 引导流程：从 SeaBIOS 到引导扇区](#bios-引导流程从-seabios-到引导扇区) |
| `grub/grub-core/boot/i386/pc/startup_raw.S:76-104` | 启动代码 | [BIOS 引导流程：从 SeaBIOS 到引导扇区](#bios-引导流程从-seabios-到引导扇区) |
| `grub/grub-core/kern/i386/realmode.S:133-195` | 实模式支持代码 | [BIOS 引导流程：从 SeaBIOS 到引导扇区](#bios-引导流程从-seabios-到引导扇区) |
| `grub/grub-core/loader/i386/linux.c` | Linux 内核加载器 | [GRUB 加载 Linux 内核](#grub-加载-linux-内核) |

### Linux 内核源代码

| 文件路径 | 功能说明 | 相关章节 |
|---------|---------|---------|
| `linux/arch/x86/boot/compressed/head_64.S` | 内核早期入口点 | [GRUB 加载 Linux 内核](#grub-加载-linux-内核) |
| `linux/arch/x86/kernel/head64.c:1932` | x86_64_start_kernel() 入口 | [GRUB 加载 Linux 内核](#grub-加载-linux-内核) |
| `linux/arch/x86/kernel/idt.c:216-227` | idt_setup_early_traps() 早期 IDT 设置 | [GRUB 加载 Linux 内核](#grub-加载-linux-内核) |
| `linux/arch/x86/kernel/idt.c:281-315` | idt_setup_apic_and_irq_gates() 完成 IDT 设置 | [GRUB 加载 Linux 内核](#grub-加载-linux-内核) |
| `linux/arch/x86/kernel/i8259.c:349-399` | init_8259A() PIC 重新编程 | [GRUB 加载 Linux 内核](#grub-加载-linux-内核) |

### 用户代码示例

| 文件路径 | 功能说明 | 相关章节 |
|---------|---------|---------|
| `boot.asm` | 最小化引导扇区程序示例 | [BIOS 引导流程：从 SeaBIOS 到引导扇区](#bios-引导流程从-seabios-到引导扇区) |

### 关键数据结构

| 数据结构 | 位置 | 说明 |
|---------|------|------|
| **IVT（中断向量表）** | `0x0000:0x0000` | BIOS 中断向量表，256 个条目，每个 4 字节 |
| **IDT（中断描述符表）** | 内核内存 | 内核中断描述符表，替代 BIOS IVT |
| **GDT（全局描述符表）** | 内核内存 | 全局描述符表，用于保护模式 |
| **boot_params** | 内核内存 | Linux 内核启动参数结构 |

