# QEMU → SeaBIOS → Linux Kernel 启动流程详解

本文档详细介绍了从 QEMU 虚拟硬件启动到 Linux 内核接管系统的完整流程，包括 SeaBIOS 的加载、中断服务初始化，以及内核如何接管 BIOS 并建立自己的中断处理机制。

---

## 目录

- [QEMU 加载 SeaBIOS](#qemu-加载-seabios)
- [SeaBIOS 初始化中断服务](#seabios-初始化中断服务)
- [引导扇区程序：从 SeaBIOS 到用户代码的执行](#引导扇区程序从-seabios-到用户代码的执行)
- [Linux 内核接管 BIOS](#linux-内核接管-bios)
- [总结：完整流程时间线](#总结完整流程时间线)
- [关键源代码文件索引](#关键源代码文件索引)

## 补充说明文档

- [BIOS 运行模式与内存访问详解](BIOS_MEMORY_MODE.md)
- [BIOS 代码布局分析：128KB 映射区域内的代码与保护模式代码](BIOS_CODE_LAYOUT_ANALYSIS.md)
- [QEMU vs 真实硬件 BIOS 加载对比](QEMU_VS_HARDWARE_BIOS.md)
- [boot.asm 与 GRUB boot.S 对比分析](BOOTSECTOR_COMPARISON.md)
- [UEFI vs BIOS 引导机制对比](UEFI_VS_BIOS_BOOT.md)
- [A20 地址线技术详解](A20_ADDRESS_LINE.md)
- [BIOS IVT vs Kernel IDT 详细对比](BIOS_IVT_VS_KERNEL_IDT.md)
- [UEFI 中断处理机制](UEFI_INTERRUPT_HANDLING.md)

## 附录

- [附录A：键盘中断处理代码分析](APPENDIX_A_KEYBOARD_INTERRUPT.md)
- [附录B：应用层事件机制](APPENDIX_B_EVENT_MECHANISM.md)
- [中断处理详解](INTERRUPT_HANDLING.md)

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

> **注意**：关于 BIOS 运行模式（实模式/保护模式）、内存布局、地址映射等详细内容，请参见 [BIOS 运行模式与内存访问详解](BIOS_MEMORY_MODE.md)。  
> 关于 QEMU 软件实现与真实硬件加载 BIOS 的区别，请参见 [QEMU vs 真实硬件 BIOS 加载对比](QEMU_VS_HARDWARE_BIOS.md)。  
> 关于哪些 BIOS 代码映射到 128KB 区域，哪些需要保护模式访问的详细分析，请参见 [BIOS 代码布局分析：128KB 映射区域内的代码与保护模式代码](BIOS_CODE_LAYOUT_ANALYSIS.md)。

---


## SeaBIOS 初始化中断服务

### POST 入口点

CPU 复位后，从 `0xFFFF0` 跳转到 SeaBIOS 的 POST（Power-On Self-Test）入口。源代码位置：`seabios/src/post.c:302-337`

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

**ivt_init() 为所有 256 个中断向量都设置了条目**

是的，`ivt_init()` **为所有 256 个中断向量都设置了条目**，采用"先全部初始化，再覆盖特定向量"的策略：

- **步骤 1**
  - **向量范围**: 0-255（全部）
  - **处理程序**: `entry_iret_official`
  - **说明**: 默认处理程序：直接执行 IRET 返回

- **步骤 2**
  - **向量范围**: 0x08-0x0F, 0x70-0x77
  - **处理程序**: `entry_hwpic1/entry_hwpic2`
  - **说明**: 硬件中断处理程序（覆盖默认值）

- **步骤 3**
  - **向量范围**: 0x02, 0x05, 0x10-0x1A, 0x40
  - **处理程序**: 具体处理程序
  - **说明**: BIOS 软件中断服务（覆盖默认值）

- **步骤 4**
  - **向量范围**: 0x60-0x66
  - **处理程序**: `SEGOFF(0, 0)`
  - **说明**: 用户中断保留区（设置为空）

- **步骤 5**
  - **向量范围**: 0x79
  - **处理程序**: `SEGOFF(0, 0)`
  - **说明**: 保护系统保留（设置为空）

- **最终状态**
  - **向量范围**: 其他未设置的向量
  - **处理程序**: `entry_iret_official`
  - **说明**: 保持默认处理程序

**为什么需要为所有向量设置条目？**

1. **安全性**：即使发生未预期的中断（如硬件故障、软件错误），CPU 也能安全返回，不会跳转到随机地址导致系统崩溃
2. **CPU 要求**：x86 CPU 要求 IVT 必须包含所有 256 个向量，每个向量都必须有有效的地址（即使是默认处理程序）
3. **防御性编程**：为所有向量设置默认处理程序，确保系统的健壮性

**默认处理程序 `entry_iret_official` 的作用：**

```asm
// seabios/src/romlayout.S:680-682
entry_iret_official:
    iretw    // 直接返回，不做任何处理
```

- 当发生未处理的中断时，CPU 会跳转到 `entry_iret_official`
- 该函数直接执行 `IRET` 指令，返回到中断发生前的状态
- 这确保了即使是不应该发生的中断，也不会导致系统崩溃

**初始化流程总结：**

```
ivt_init() 执行
    ↓
步骤 1: 为所有 256 个向量设置默认处理程序（entry_iret_official）
    ├─ 向量 0 → entry_iret_official
    ├─ 向量 1 → entry_iret_official
    ├─ ...
    └─ 向量 255 → entry_iret_official
    ↓
步骤 2: 覆盖硬件中断向量（0x08-0x0F, 0x70-0x77）
    ├─ 向量 0x08 → entry_hwpic1
    ├─ ...
    └─ 向量 0x77 → entry_hwpic2
    ↓
步骤 3: 覆盖软件中断向量（0x02, 0x05, 0x10-0x1A, 0x40）
    ├─ 向量 0x10 → entry_10
    ├─ 向量 0x13 → entry_13_official
    └─ ...
    ↓
步骤 4-5: 设置保留向量为空（0x60-0x66, 0x79）
    ↓
最终结果: 所有 256 个向量都有条目
    ├─ 已设置具体处理程序的向量：使用具体处理程序（BIOS 服务）
    ├─ 设置为空的向量：SEGOFF(0, 0)
    └─ 其他向量：保持默认处理程序（entry_iret_official）
    ↓
【BIOS 阶段完成，IVT 初始化完成】
    ↓
【内核加载后】
    ↓
内核早期启动（startup_64）
    ↓
调用 idt_setup_early_traps() 建立 IDT
    ├─ 建立内核的 IDT（中断描述符表）
    ├─ 设置早期陷阱处理程序（CPU 异常）
    └─ 加载 IDT 到 CPU（load_idt）
    ↓
【从这一刻起，CPU 使用内核的 IDT，BIOS 的 IVT 不再使用】
    ↓
内核继续初始化
    ├─ 重新编程 PIC（init_8259A）
    ├─ 设置 APIC 中断门（idt_setup_apic_and_irq_gates）
    └─ 完成中断系统接管
```

**默认处理程序何时被替换为实际处理程序？**

有两个层面的替换：

1. **BIOS 内部替换（在 `ivt_init()` 函数内部）**：
   - **步骤 1**：先为所有 256 个向量设置默认处理程序 `entry_iret_official`
   - **步骤 2-5**：立即为特定的中断（BIOS 服务）设置实际处理程序，覆盖默认值
   - **结果**：对于 BIOS 服务中断（如 INT 10h, INT 13h），在 `ivt_init()` 执行完成后就已经是实际处理程序了（`entry_10`, `entry_13_official` 等）
   - **时机**：BIOS POST 初始化阶段，在 `interface_init()` 中调用

2. **内核接管替换（内核加载后）**：
   - **时机**：内核早期启动时（`startup_64`）调用 `idt_setup_early_traps()` 建立 IDT
   - **过程**：
     - 内核建立自己的 IDT（中断描述符表），完全替换 BIOS 的 IVT
     - 使用 `load_idt(&idt_descr)` 加载 IDT 到 CPU 的 IDTR 寄存器
     - 从这一刻起，CPU 使用内核的 IDT，BIOS 的 IVT 不再使用
   - **源代码位置**：
     - `linux/arch/x86/kernel/head_64.S:1897` - 调用 `__pi_startup_64_setup_gdt_idt`
     - `linux/arch/x86/kernel/head64.c:1932` - 调用 `idt_setup_early_handler()`
     - `linux/arch/x86/kernel/idt.c:216-227` - `idt_setup_early_traps()` 实现
     - `linux/arch/x86/kernel/idt.c:281-315` - `idt_setup_apic_and_irq_gates()` 完成接管

**替换时机总结：**

- **BIOS 服务中断**（INT 10h, INT 13h 等）
  - **默认处理程序替换时机**: 在 `ivt_init()` 内部立即替换
  - **实际处理程序**: `entry_10`, `entry_13_official` 等
  - **说明**: BIOS POST 阶段完成

- **硬件中断**（IRQ0-15）
  - **默认处理程序替换时机**: 在 `ivt_init()` 内部立即替换
  - **实际处理程序**: `entry_hwpic1`, `entry_hwpic2`
  - **说明**: BIOS POST 阶段完成

- **其他未设置的中断**
  - **默认处理程序替换时机**: 保持默认处理程序，直到内核加载
  - **实际处理程序**: `entry_iret_official`
  - **说明**: 内核加载后由 IDT 接管

- **所有中断**
  - **默认处理程序替换时机**: 内核加载后，建立 IDT 完全替换 IVT
  - **实际处理程序**: 内核的处理程序
  - **说明**: 内核早期启动阶段

**关键点：**
1. **BIOS 服务中断**：在 `ivt_init()` 执行完成后就已经是实际处理程序了，**不需要等到内核加载**
2. **内核接管**：内核加载后建立 IDT，完全替换 BIOS 的 IVT，此时所有中断都路由到内核处理程序
3. **默认处理程序的作用**：为未设置的中断提供安全的后备处理，防止系统崩溃，直到内核接管

**中断向量号 vs 内存地址：**

这些数字（如 `0x02`, `0x10`, `0x13`）是**中断向量号**（中断向量表的索引），不是内存地址：

| 概念 | 说明 | 示例 |
|------|------|------|
| **中断向量号** | IVT 的索引（0-255），由 x86 CPU 硬件约定 | `0x10`, `0x13`, `0x19` |
| **IVT 位置** | 物理内存固定地址 `0x0000:0000`（段:偏移格式） | `0x0000:0000` |
| **IVT 条目地址** | 向量号对应的 IVT 条目在内存中的地址 | 向量 `0x10` → 内存地址 `0x0000:0040`（`0x10 × 4`） |
| **IVT 条目内容** | 每个条目 4 字节：段地址（2 字节）+ 偏移地址（2 字节） | `段:偏移` 格式的处理程序地址 |

**计算公式：**
```
IVT 条目内存地址 = 0x0000:0000 + (中断向量号 × 4)
```

**示例：**
- 向量 `0x10`（INT 10h）的 IVT 条目在内存地址 `0x0000:0040`（`0x10 × 4 = 0x40`）
- 向量 `0x13`（INT 13h）的 IVT 条目在内存地址 `0x0000:004C`（`0x13 × 4 = 0x4C`）
- 向量 `0x19`（INT 19h）的 IVT 条目在内存地址 `0x0000:0064`（`0x19 × 4 = 0x64`）

**重要澄清：IVT 条目 vs 中断服务代码**

**IVT 条目不是中断服务代码本身，而是指向中断服务代码的地址（指针）**：

| 概念 | 说明 | 位置 |
|------|------|------|
| **IVT 条目** | 存储中断处理程序的地址（段:偏移，4 字节） | 内存 `0x0000:0000` 开始的 IVT 表 |
| **中断服务代码** | 实际的处理程序代码（机器指令） | BIOS 代码段（如 `0xF000:xxxx`） |

**工作流程：**
```
1. 发生中断（如 INT 10h）
   ↓
2. CPU 查找 IVT 条目（内存地址 0x0000:0040）
   ↓
3. 读取 IVT 条目内容（例如：段=0xF000, 偏移=0x1234）
   ↓
4. CPU 跳转到该地址（0xF000:0x1234）执行中断服务代码
   ↓
5. 执行实际的处理程序代码（entry_10 函数）
```

**代码示例：**

```c
// seabios/src/post.c:ivt_init() - 第 51 行
SET_IVT(0x10, FUNC16(entry_10));
// ↑ 这行代码的作用：
//   1. 找到 IVT 条目（内存地址 0x0000:0040）
//   2. 将 entry_10 函数的地址（段:偏移）写入该条目
//   3. entry_10 函数本身位于 BIOS 代码段（如 0xF000:xxxx）
//   4. IVT 条目只存储地址，不存储代码

// 当程序执行 INT 10h 时：
//   1. CPU 读取内存 0x0000:0040 处的 IVT 条目
//   2. 获取 entry_10 的地址（例如 0xF000:0x1234）
//   3. 跳转到 0xF000:0x1234 执行 entry_10 函数的代码
```

**内存布局示意：**

```
内存地址          内容                    说明
─────────────────────────────────────────────────────────
0x0000:0000      [IVT 条目 0]             向量 0 的地址（4 字节）
0x0000:0004      [IVT 条目 1]             向量 1 的地址（4 字节）
...
0x0000:0040      [IVT 条目 0x10]          向量 0x10 的地址（段:偏移）
                ├─ 偏移低字节 (0x34)      entry_10 的偏移地址
                ├─ 偏移高字节 (0x12)
                ├─ 段低字节 (0x00)        entry_10 的段地址
                └─ 段高字节 (0xF0)
...
0xF000:1234      [entry_10 代码]          实际的中断服务代码（机器指令）
                ├─ push bp               处理程序的开始
                ├─ mov bp, sp
                └─ ...                   实际的视频服务代码
```

**这是 x86 CPU 的硬件约定：**
- **实模式**：CPU 固定从内存 `0x0000:0000` 读取 IVT
- **保护模式/长模式**：使用 IDT（中断描述符表），位置由 IDTR 寄存器指定，不固定
- **UEFI 环境**：
  - **启动阶段**（实模式）：使用 IVT，位于 `0x0000:0000`，与 BIOS 相同
  - **运行阶段**（保护模式/长模式）：切换到 IDT，位置由 UEFI 固件或操作系统指定
  - **中断向量号约定**：软件中断向量号（如 `0x10`, `0x13`）在 UEFI 中通常不使用，因为 UEFI 使用函数调用而非中断服务

### 平台硬件设置（PIC 初始化）

**调用时机：** `platform_hardware_setup()` 在 `maininit()` 的"阶段 2"中被调用，位于 IVT 初始化之后、引导流程之前。

**调用位置：** `seabios/src/post.c:203`（在 `maininit()` 函数中）

**为什么 IVT 必须先于 PIC 初始化？**

IVT（中断向量表）和 PIC（可编程中断控制器）之间存在依赖关系，必须按正确顺序初始化：

1. **IVT 是中断处理的基础设施**：
   - IVT 位于内存 `0x0000:0000`，包含 256 个中断向量（每个 4 字节）
   - CPU 在收到中断时，会查找 IVT 获取中断处理程序的地址
   - **即使 PIC 未初始化，CPU 仍可能收到中断**（如 NMI、硬件故障、调试中断等）

2. **PIC 初始化可能触发中断**：
   - PIC 初始化过程中需要配置硬件寄存器（发送 ICW1-ICW4）
   - 如果此时发生硬件中断，CPU 会查找 IVT
   - 如果 IVT 未初始化，CPU 可能跳转到随机地址，导致系统崩溃

3. **PIC 配置依赖 IVT**：
   - PIC 通过 ICW2 配置中断向量基址（如 0x08-0x0F 对应 IRQ0-7）
   - 这些向量必须已经在 IVT 中有有效的处理程序
   - IVT 在初始化时已经为硬件中断向量（0x08-0x0F, 0x70-0x77）设置了默认处理程序

4. **中断处理流程**：
   ```
   硬件设备 → PIC（8259A）→ CPU（INTR 引脚）→ 查找 IVT → 执行处理程序
   ```
   - PIC 负责将硬件 IRQ 转换为 CPU 中断向量
   - CPU 使用该向量在 IVT 中查找处理程序地址
   - 如果 IVT 未初始化，整个中断处理链会失败

**IVT 与 PIC 的协作关系：**

- **IVT**
  - **作用**: 提供中断处理程序地址表
  - **初始化顺序**: 第 1 步
  - **依赖关系**: 无依赖，是基础设施

- **PIC**
  - **作用**: 将硬件 IRQ 路由到 CPU 向量
  - **初始化顺序**: 第 2 步
  - **依赖关系**: 依赖 IVT 已初始化

**重要说明：8259A PIC 只处理部分中断**

8259A PIC **并没有覆盖所有中断**，它只处理**硬件中断（IRQ0-15）**：

- **CPU 异常**
  - **向量范围**: 0-31
  - **8259A PIC 是否处理**: ❌ 否
  - **说明**: CPU 内部异常（除零、页错误、调试等），不经过 PIC

- **NMI（不可屏蔽中断）**
  - **向量范围**: 0x02
  - **8259A PIC 是否处理**: ❌ 否
  - **说明**: 硬件故障、内存校验错误等，直接到 CPU，不经过 PIC

- **8259A 硬件中断**
  - **向量范围**: 0x08-0x0F, 0x70-0x77
  - **8259A PIC 是否处理**: ✅ 是
  - **说明**: IRQ0-15，由 PIC 路由到 CPU

- **软件中断（BIOS 服务）**
  - **向量范围**: 0x10, 0x13, 0x15 等
  - **8259A PIC 是否处理**: ❌ 否
  - **说明**: 由 `INT` 指令触发，不经过 PIC

- **用户中断**
  - **向量范围**: 0x60-0x66
  - **8259A PIC 是否处理**: ❌ 否
  - **说明**: 保留给用户程序使用

- **其他向量**
  - **向量范围**: 其他
  - **8259A PIC 是否处理**: ❌ 否
  - **说明**: 未使用或保留

**8259A PIC 覆盖的中断：**

- **IRQ0-7**（主 PIC）→ 映射到向量 **0x08-0x0F**
  - IRQ0：系统定时器
  - IRQ1：键盘
  - IRQ2：从 PIC 级联
  - IRQ3：串口 COM2
  - IRQ4：串口 COM1
  - IRQ5：并行口 LPT2（或声卡）
  - IRQ6：软盘控制器
  - IRQ7：并行口 LPT1

- **IRQ8-15**（从 PIC）→ 映射到向量 **0x70-0x77**
  - IRQ8：实时时钟（RTC）
  - IRQ9：重定向到 IRQ2（兼容性）
  - IRQ10-12：保留或 PCI 设备
  - IRQ13：数学协处理器
  - IRQ14：主 IDE 控制器
  - IRQ15：从 IDE 控制器

**8259A PIC 不处理的中断示例：**

1. **CPU 异常**（向量 0-31）：
   - 向量 0：除零错误
   - 向量 1：调试异常
   - 向量 3：断点异常
   - 向量 14：页错误
   - 等等

2. **软件中断**（由 `INT` 指令触发）：
   - `INT 10h`：视频服务（不经过 PIC）
   - `INT 13h`：磁盘服务（不经过 PIC）
   - `INT 15h`：系统服务（不经过 PIC）
   - `INT 19h`：引导加载服务（不经过 PIC）

3. **NMI**（向量 0x02）：
   - 不可屏蔽中断，直接到 CPU，不经过 PIC

**代码证据：**

```c
// seabios/src/hw/pic.h:31-32
#define BIOS_HWIRQ0_VECTOR 0x08  // 主 PIC：IRQ0-7 → 向量 0x08-0x0F
#define BIOS_HWIRQ8_VECTOR 0x70   // 从 PIC：IRQ8-15 → 向量 0x70-0x77

// seabios/src/post.c:ivt_init() - 第 43-46 行
// IVT 初始化时，只为 PIC 的 16 个硬件中断向量设置处理程序
for (i=BIOS_HWIRQ0_VECTOR; i<BIOS_HWIRQ0_VECTOR+8; i++)  // 0x08-0x0F
    SET_IVT(i, FUNC16(entry_hwpic1));
for (i=BIOS_HWIRQ8_VECTOR; i<BIOS_HWIRQ8_VECTOR+8; i++)  // 0x70-0x77
    SET_IVT(i, FUNC16(entry_hwpic2));

// 但 IVT 有 256 个向量，其他向量用于：
// - CPU 异常（0-31）
// - 软件中断（0x10, 0x13, 0x15 等）
// - NMI（0x02）
// - 用户中断（0x60-0x66）
```

**总结：**

- **8259A PIC 只处理 16 个硬件中断**（IRQ0-15），映射到向量 0x08-0x0F 和 0x70-0x77
- **CPU 有 256 个中断向量**，PIC 只覆盖其中的 16 个
- **其他中断**（CPU 异常、软件中断、NMI 等）**不经过 PIC**，直接由 CPU 处理
- **IVT 必须初始化所有 256 个向量**，因为任何向量都可能被使用，而不仅仅是 PIC 处理的 16 个

**代码证据：**

```c
// seabios/src/post.c:ivt_init() - 第 43-46 行
// IVT 初始化时，预先为 PIC 的中断向量设置处理程序（此时 PIC 还未初始化）
for (i=BIOS_HWIRQ0_VECTOR; i<BIOS_HWIRQ0_VECTOR+8; i++)
    SET_IVT(i, FUNC16(entry_hwpic1));  // 主 PIC 处理程序（向量 0x08-0x0F）
for (i=BIOS_HWIRQ8_VECTOR; i<BIOS_HWIRQ8_VECTOR+8; i++)
    SET_IVT(i, FUNC16(entry_hwpic2));  // 从 PIC 处理程序（向量 0x70-0x77）
// ↑ 关键：这些处理程序在 PIC 初始化之前就已经设置好了

// seabios/src/hw/pic.c:pic_setup() - 第 62-66 行
// PIC 初始化时，配置中断向量基址，这些向量已经在 IVT 中有处理程序了
void pic_setup(void)
{
    pic_reset(BIOS_HWIRQ0_VECTOR, BIOS_HWIRQ8_VECTOR);
    // ↑ 配置 PIC 将 IRQ0-7 映射到向量 0x08-0x0F，IRQ8-15 映射到 0x70-0x77
    //   这些向量已经在 ivt_init() 中预先设置了处理程序（entry_hwpic1/entry_hwpic2）
    //   所以即使 PIC 初始化过程中发生中断，IVT 中也有有效的处理程序
}
```

**初始化顺序总结：**

```
1. ivt_init() 执行（在 interface_init() 中）
   ├─ 初始化所有 256 个向量为默认处理程序
   ├─ 预先为 PIC 向量（0x08-0x0F, 0x70-0x77）设置处理程序 ← 关键步骤
   │   └─ entry_hwpic1（主 PIC）和 entry_hwpic2（从 PIC）
   └─ 设置软件中断处理程序（INT 10h, INT 13h 等）

2. pic_setup() 执行（在 platform_hardware_setup() 中）
   ├─ 配置 PIC 将 IRQ0-7 映射到向量 0x08-0x0F
   ├─ 配置 PIC 将 IRQ8-15 映射到向量 0x70-0x77
   └─ 这些向量在步骤 1 中已经设置了处理程序，所以是安全的
```

**为什么这样设计？**

- **安全考虑**：如果 PIC 初始化过程中发生硬件中断，IVT 中必须有有效的处理程序
- **依赖关系**：PIC 配置的向量必须对应 IVT 中已存在的处理程序
- **初始化顺序**：先建立基础设施（IVT），再配置硬件（PIC）

源代码位置：`seabios/src/post.c:137-158`

```c
// 平台硬件设置：初始化 PC 基本硬件组件
// 这些函数按顺序执行，每个函数初始化特定的硬件子系统
static void
platform_hardware_setup(void)
{
    // 步骤 1: 设置 DMA（直接内存访问）控制器
    // 确保传统 DMA 不在运行，避免冲突
    // 执行顺序：必须在其他硬件初始化之前
    dma_setup();
    // 示例：dma_setup() 内部会：
    //   - 禁用所有 DMA 通道
    //   - 重置 DMA 控制器寄存器
    //   - 配置 DMA 页面寄存器

    // 步骤 2: 初始化基础 PC 硬件
    // 执行顺序：DMA 设置后，基础硬件初始化
    pic_setup();      // 初始化 8259A 可编程中断控制器（PIC）
                      // 配置 IRQ0-7 映射到向量 0x08-0x0F，IRQ8-15 映射到 0x70-0x77
                      // 示例执行流程：
                      //   1. 屏蔽所有中断（outb(0xff, PIC_MASTER_IMR)）
                      //   2. 发送 ICW1-ICW4 初始化命令序列
                      //   3. 配置中断向量映射
                      //   4. 恢复中断屏蔽位
    
    thread_setup();   // 设置多线程支持
                      // 示例：初始化线程数据结构，设置线程调度器
    
    mathcp_setup();   // 初始化数学协处理器（FPU）
                      // 示例：检测 FPU 存在，初始化 FPU 控制寄存器

    // 步骤 3: 平台特定设置
    // 执行顺序：基础硬件初始化后，平台特定初始化
    qemu_platform_setup();      // QEMU 虚拟化平台特定初始化
                                 // 示例：检测 QEMU 环境，初始化 fw_cfg 接口
                                 //       设置虚拟硬件参数
    
    coreboot_platform_setup();   // Coreboot 固件平台特定初始化
                                 // 示例：读取 Coreboot 表，初始化 CBFS

    // 步骤 4: 设置定时器和周期性时钟中断
    // 执行顺序：平台设置后，定时器初始化（依赖 PIC 已初始化）
    timer_setup();   // 初始化定时器（8254 PIT）
                     // 示例执行流程：
                     //   1. 配置 PIT 通道 0（系统时钟）
                     //   2. 设置定时器频率（通常 18.2 Hz，约 55ms）
                     //   3. 配置定时器模式
    
    clock_setup();   // 设置时钟中断（IRQ0），每 55ms 触发一次
                     // 示例执行流程：
                     //   1. 注册 IRQ0 中断处理程序
                     //   2. 启用定时器中断
                     //   3. 初始化系统时钟计数器
                     //   注意：依赖 timer_setup() 和 pic_setup() 已完成

    // 步骤 5: 初始化 TPM（可信平台模块）
    // 执行顺序：最后初始化，因为不是关键路径
    tpm_setup();
    // 示例：检测 TPM 设备，初始化 TPM 接口
}
```

**函数执行顺序示例：**

假设系统启动时调用 `platform_hardware_setup()`，执行顺序如下：

```
platform_hardware_setup() 被调用
    ↓
1. dma_setup()
   ├─ 禁用 DMA 通道 0-7
   ├─ 重置 DMA 控制器
   └─ 配置 DMA 页面寄存器
    ↓
2. pic_setup()
   ├─ 屏蔽所有中断（0xFF → PIC_MASTER_IMR）
   ├─ 发送 ICW1（0x11 → PIC_MASTER_CMD）
   ├─ 发送 ICW2（0x08 → PIC_MASTER_IMR）映射 IRQ0-7 到向量 0x08-0x0F
   ├─ 发送 ICW3（级联配置）
   ├─ 发送 ICW4（工作模式）
   └─ 重复上述步骤配置从 PIC（IRQ8-15 → 0x70-0x77）
    ↓
3. thread_setup()
   └─ 初始化线程管理数据结构
    ↓
4. mathcp_setup()
   └─ 检测并初始化 FPU
    ↓
5. qemu_platform_setup()
   └─ 初始化 QEMU 特定接口（fw_cfg）
    ↓
6. timer_setup()
   ├─ 配置 PIT 通道 0
   └─ 设置定时器频率（18.2 Hz）
    ↓
7. clock_setup()
   ├─ 注册 IRQ0 处理程序（依赖 PIC 和定时器已初始化）
   └─ 启用时钟中断
    ↓
8. tpm_setup()
   └─ 初始化 TPM（如果存在）
    ↓
函数返回，硬件初始化完成
```

**关键依赖关系：**
- `clock_setup()` **依赖** `timer_setup()` 和 `pic_setup()`（需要定时器和中断控制器已就绪）
- `qemu_platform_setup()` **依赖** 基础硬件已初始化（可能需要访问 I/O 端口）
- 所有函数**依赖** `dma_setup()`（避免 DMA 冲突）

**关键点：**
- `dma_setup()` 必须在最前面执行，避免 DMA 冲突
- `pic_setup()` 初始化中断控制器，后续中断相关初始化都依赖它
- `timer_setup()` 和 `clock_setup()` 必须按顺序执行，时钟中断依赖定时器

### BIOS 加载内核的完整流程

SeaBIOS 完成初始化后，通过 INT 19h 引导加载服务启动引导过程，最终加载操作系统内核。本节详细说明从 BIOS 到内核加载的完整流程。

#### 引导流程概述

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
执行引导扇区代码
    ↓
引导扇区加载 Bootloader（如 GRUB）
    ↓
Bootloader 加载内核镜像
    ↓
跳转到内核入口点
```

#### INT 19h 引导加载服务

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

#### 引导设备选择和扇区读取

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

#### BIOS 如何加载 Bootloader

引导扇区程序（512 字节）通常太小，无法直接加载内核，因此采用多阶段引导。本节详细说明 BIOS 如何加载 bootloader（以 GRUB 为例）。

**阶段 1：BIOS 加载引导扇区（MBR）**

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

**GRUB 引导扇区代码的真实实现：**

**源代码位置：`grub/grub-core/boot/i386/pc/boot.S`**

GRUB 引导扇区代码的主要任务：

1. **初始化环境**：设置段寄存器、栈指针
2. **检测磁盘访问模式**：尝试使用 LBA 模式，失败则回退到 CHS 模式
3. **读取 GRUB Core**：从磁盘的特定扇区（`kernel_sector`）读取 GRUB Core 到内存 `0x8000`
4. **跳转到 GRUB Core**：将控制权交给 GRUB Core

**关键代码解析：**

```asm
// grub/grub-core/boot/i386/pc/boot.S:124-483

_start:
start:
    // GRUB 引导扇区从 0x7C00 开始执行
    // BIOS 跳转到这里时：CS:IP = 0:0x7C00
    
    // 步骤 1: 关闭中断，设置段寄存器
    cli                     // 关闭中断（此时还不安全）
    
    // 修复某些 BIOS 的 bug：如果 DL 寄存器值不正确，设置为 0x80（第一个硬盘）
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
    pushw   %dx             // 保存 DL（驱动器号）
    
    // 步骤 4: 显示 "GRUB " 消息
    MSG(notification_string)  // 调用消息打印函数
    
    // 步骤 5: 检测是否支持 LBA 模式
    movw    $disk_address_packet, %si  // 设置磁盘地址包指针
    movb    $0x41, %ah      // INT 13h 功能 0x41：检查扩展磁盘访问
    movw    $0x55aa, %bx    // 签名
    int     $0x13           // 调用 BIOS
    
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
    movb    $0x42, %ah      // INT 13h 功能 0x42：扩展读
    int     $0x13           // 读取扇区到 0x7000:0x0000
    
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
    popw    %dx             // 恢复驱动器号
    movw    $GRUB_BOOT_MACHINE_BUFFER_SEG, %bx
    movw    %bx, %es        // 设置目标段
    xorw    %bx, %bx        // 偏移 = 0
    movw    $0x0201, %ax    // 功能 0x02，读取 1 个扇区
    int     $0x13           // 读取到 0x7000:0x0000
    
    jc      LOCAL(read_error)
    movw    %es, %bx

    // 步骤 8: 将 GRUB Core 从缓冲区复制到最终地址
LOCAL(copy_buffer):
    // 从 0x7000:0x0000 复制到 0x0000:0x8000（GRUB_BOOT_MACHINE_KERNEL_ADDR）
    pusha
    pushw   %ds
    
    movw    $0x100, %cx     // 复制 512 字节（0x100 字）
    movw    %bx, %ds        // 源段 = 0x7000
    xorw    %si, %si        // 源偏移 = 0
    movw    $GRUB_BOOT_MACHINE_KERNEL_ADDR, %di  // 目标偏移 = 0x8000
    movw    %si, %es        // 目标段 = 0x0000
    
    cld                     // 方向标志：向前
    rep movsw               // 重复复制字（DS:SI -> ES:DI）
    
    popw    %ds
    popa
    
    // 步骤 9: 跳转到 GRUB Core
    jmp     *(LOCAL(kernel_address))  // 跳转到 0x8000（GRUB Core 入口点）

// 关键数据定义
LOCAL(kernel_address):
    .word   GRUB_BOOT_MACHINE_KERNEL_ADDR  // 0x8000：GRUB Core 加载地址

LOCAL(kernel_sector):
    .long   1               // GRUB Core 所在的扇区号（由 grub-setup 写入）
LOCAL(kernel_sector_high):
    .long   0               // 高 32 位扇区号（用于大磁盘）

notification_string:
    .asciz "GRUB "          // 启动时显示的消息
```

**关键地址和常量：**

- **`GRUB_BOOT_MACHINE_KERNEL_ADDR`**：`0x8000` - GRUB Core 加载地址
- **`GRUB_BOOT_MACHINE_BUFFER_SEG`**：`0x7000` - 临时缓冲区段（读取扇区时使用）
- **`GRUB_BOOT_MACHINE_STACK_SEG`**：`0x2000` - 栈段地址
- **`kernel_sector`**：GRUB Core 所在的扇区号（由 `grub-setup` 在安装时写入）

**GRUB 引导扇区的工作流程：**

```
SeaBIOS 读取 MBR 到 0x7C00
    ↓
GRUB 引导扇区代码开始执行（0x7C00）
    ├─ 初始化段寄存器和栈
    ├─ 检测磁盘访问模式（LBA 或 CHS）
    ├─ 从 kernel_sector 读取 GRUB Core（512 字节）
    │   └─ 先读到临时缓冲区 0x7000:0x0000
    ├─ 复制到最终地址 0x0000:0x8000
    └─ 跳转到 0x8000（GRUB Core 入口点）
    ↓
GRUB Core 开始执行
```

**注意：** GRUB 引导扇区只读取第一个 512 字节的 GRUB Core。完整的 GRUB Core 可能跨越多个扇区，后续的加载由 GRUB Core 自身完成。

**GRUB 如何从 512 字节限制跨越到加载完整 GRUB Core？**

GRUB 使用了一个巧妙的设计，通过"块列表"（blocklist）机制实现从 512 字节限制到加载完整 GRUB Core 的跨越：

**设计原理：**

1. **引导扇区只读取第一个 512 字节**：
   - 引导扇区（`boot.S`）读取第一个扇区到 `0x8000`
   - 这 512 字节包含 `diskboot.S` 的代码（约 400 字节）和块列表数据（12 字节）

2. **第一个 512 字节的结构**：
   ```
   0x8000 - 0x81F3: diskboot.S 代码（加载剩余扇区的代码）
   0x81F4 - 0x81FF: 块列表（blocklist）数据
   ```

3. **块列表（blocklist）机制**：
   - 块列表存储在第一个 512 字节的末尾（`0x200 - 12` 字节处）
   - 每个块列表条目 12 字节，包含：
     - `start`（8 字节）：起始扇区号（LBA）
     - `len`（2 字节）：要读取的扇区数
     - `segment`（2 字节）：目标内存段地址
   - 由 `grub-mkimage` 在安装时写入，记录了 GRUB Core 的所有扇区位置

4. **diskboot.S 加载剩余扇区**：
   - `diskboot.S` 读取块列表，知道需要读取哪些扇区
   - 循环读取每个块列表条目指定的扇区
   - 将读取的扇区复制到目标内存地址

**源代码位置：`grub/grub-core/boot/i386/pc/diskboot.S:38-341`**

```asm
// diskboot.S - GRUB Core 的第一个 512 字节，负责加载剩余的扇区
start:
_start:
    // 这个代码被加载到 0x8000，是 GRUB Core 的第一个 512 字节
    
    // 步骤 1: 保存驱动器号
    pushw   %dx
    
    // 步骤 2: 显示 "loading" 消息
    MSG(notification_string)  // 显示 "loading"
    
    // 步骤 3: 设置块列表指针
    movw    $LOCAL(firstlist), %di  // 指向第一个块列表条目
    
    // 步骤 4: 循环读取块列表中的每个扇区块
LOCAL(bootloop):
    // 检查是否还有扇区要读取
    cmpw    $0, 8(%di)  // 检查 len 字段（偏移 8）
    je      LOCAL(bootit)  // 如果为 0，跳转到启动代码
    
LOCAL(setup_sectors):
    // 检测使用 LBA 还是 CHS 模式
    cmpb    $0, -1(%si)
    je      LOCAL(chs_mode)
    
    // LBA 模式：使用 INT 13h 扩展读（AH=0x42）
LOCAL(lba_mode):
    // 从块列表读取扇区信息
    movl    (%di), %ebx      // start 低 32 位（偏移 0）
    movl    4(%di), %ecx     // start 高 32 位（偏移 4）
    movw    8(%di), %ax      // len（偏移 8）
    
    // 准备磁盘地址包（DAP）
    movw    $0x0010, (%si)   // DAP 大小 = 16 字节
    movw    %ax, 2(%si)      // 扇区数
    movl    %ebx, 8(%si)     // 起始扇区（低 32 位）
    movl    %ecx, 12(%si)    // 起始扇区（高 32 位）
    movw    $GRUB_BOOT_MACHINE_BUFFER_SEG, 6(%si)  // 缓冲区段 = 0x7000
    
    // 调用 INT 13h 扩展读
    movb    $0x42, %ah
    int     $0x13
    
    jc      LOCAL(read_error)
    
    // 步骤 5: 将读取的扇区复制到目标地址
LOCAL(copy_buffer):
    // 从临时缓冲区（0x7000:0x0000）复制到目标段（块列表中的 segment）
    movw    10(%di), %es     // 目标段（偏移 10）
    // ... 复制代码 ...
    
    // 步骤 6: 更新块列表指针，继续下一个块
    subw    $GRUB_BOOT_MACHINE_LIST_SIZE, %di  // 移动到下一个块列表条目
    jmp     LOCAL(bootloop)   // 继续循环
    
LOCAL(bootit):
    // 所有扇区加载完成，跳转到 GRUB Core 的 C 代码入口点
    ljmp    $0, $(GRUB_BOOT_MACHINE_KERNEL_ADDR + 0x200)
    // ↑ 跳转到 0x8200（0x8000 + 0x200），这是 startup.S 的入口点
```

**块列表结构：**

```c
// grub/include/grub/offsets.h:151-156
struct grub_pc_bios_boot_blocklist
{
    grub_uint64_t start;    // 起始扇区号（LBA，8 字节）
    grub_uint16_t len;      // 要读取的扇区数（2 字节）
    grub_uint16_t segment;  // 目标内存段地址（2 字节）
} GRUB_PACKED;
```

**完整加载流程：**

```
1. BIOS 读取引导扇区到 0x7C00
    ↓
2. 引导扇区读取第一个 GRUB Core 扇区到 0x8000
   ├─ 包含 diskboot.S 代码（~400 字节）
   └─ 包含块列表数据（12 字节，在末尾）
    ↓
3. 引导扇区跳转到 0x8000（diskboot.S 入口）
    ↓
4. diskboot.S 执行（第一个 512 字节）
   ├─ 读取块列表（知道需要读取哪些扇区）
   ├─ 循环读取每个块列表条目指定的扇区
   │   ├─ 使用 INT 13h 读取扇区到临时缓冲区（0x7000）
   │   └─ 复制到目标地址（块列表中的 segment）
   └─ 所有扇区加载完成后，跳转到 0x8200
    ↓
5. 跳转到 0x8200（GRUB Core 的 C 代码入口点，startup.S）
   └─ 此时完整的 GRUB Core 已加载到内存
    ↓
6. startup.S 调用 grub_main()，GRUB Core 开始执行
```

**关键设计点：**

1. **自举机制**：第一个 512 字节包含加载代码（diskboot.S），可以加载剩余的扇区
2. **块列表**：存储在第一个 512 字节的末尾，由 `grub-mkimage` 在安装时写入
3. **分段加载**：GRUB Core 可能分散在磁盘的不同位置（由于文件系统碎片），块列表记录了每个片段的位置
4. **内存布局**：
   - `0x8000-0x81FF`：第一个 512 字节（diskboot.S + 块列表）
   - `0x8200+`：GRUB Core 的剩余部分（C 代码、模块等）

**为什么需要块列表？**

- GRUB Core 可能很大（几 KB 到几十 KB），跨越多个扇区
- GRUB Core 可能分散在磁盘的不同位置（文件系统碎片）
- 块列表记录了每个片段的位置，允许分段加载
- 引导扇区只有 512 字节，无法包含完整的加载逻辑，所以将加载逻辑放在第一个 GRUB Core 扇区中

**阶段 3：GRUB Core 从实模式切换到保护模式（仅 BIOS）**

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
```

> **注意**：关于 A20 地址线的详细技术说明，请参见 [A20 地址线技术详解](A20_ADDRESS_LINE.md)。

**模式切换的关键步骤（real_to_prot）：**

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


**模式切换的完整流程（BIOS）：**

**跳转流程：**

```
grub_linux_boot() 被调用
    ↓
分配实模式内存（boot_params）
    ↓
准备 boot_params 结构
    ├─ code32_start: 内核入口点地址
    ├─ cmd_line_ptr: 内核命令行参数地址
    ├─ ramdisk_image: initramfs 地址
    └─ e820_map: 内存映射表
    ↓
设置寄存器状态
    ├─ ESI = boot_params 地址（传递给内核）
    ├─ ESP = 栈指针
    └─ EIP = code32_start（内核入口点）
    ↓
grub_relocator32_boot()
    ├─ 切换到保护模式（如果还在实模式）
    ├─ 设置 GDT
    └─ 跳转到 EIP（内核入口点）
    ↓
内核开始执行（startup_32 或 startup_64）
```

**完整内存布局（引导过程）：**

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
0x008000 - 0x009FFF      GRUB Core（第二阶段）← 引导扇区加载
0x00A000 - 0x00BFFF      GRUB 文件系统驱动
...
0x0100000 (1MB) - ...    内核镜像（vmlinuz）← GRUB 加载
0x0200000 - ...          initramfs ← GRUB 加载
...
0xF0000 - 0xFFFFF        BIOS ROM
```

**关键步骤总结：**

1. **BIOS → 引导扇区**：
   - BIOS 调用 INT 13h（AH=0x02）读取磁盘第一个扇区
   - 加载到 `0x7C00`，验证签名 `0xAA55`
   - 跳转到 `0x0000:0x7C00` 执行

2. **引导扇区 → GRUB Core**：
   - 引导扇区代码读取活动分区的引导扇区
   - 加载 GRUB Core 到 `0x8000` 或更高地址
   - 跳转到 GRUB Core

3. **GRUB Core → 内核**：
   - GRUB 初始化文件系统，读取配置文件
   - 使用 INT 13h 扩展读（AH=0x42）或文件系统驱动读取内核文件
   - 加载内核到 `0x100000`（1MB），initramfs 到更高地址
   - 切换到保护模式/长模式
   - 跳转到内核入口点

**关键内存地址：**
- `0x7C00`：引导扇区（MBR）加载地址
- `0x8000`：GRUB Core 通常加载地址
- `0x100000`（1MB）：内核镜像加载地址
- `0xFFFFFFFF - bios_size`：BIOS ROM 地址

---

## 引导扇区程序：从 SeaBIOS 到用户代码的执行

### 引导扇区程序概述

引导扇区（Boot Sector）是存储在磁盘第一个扇区（512 字节）的特殊程序。BIOS 完成初始化后，会调用 INT 19h 服务加载并执行引导扇区程序。本节通过一个最小化的引导扇区程序，详细说明 QEMU 和 SeaBIOS 如何协作完成引导过程。

### 最小引导扇区程序代码

> **相关文档**：关于最小引导扇区程序（`boot.asm`）与 GRUB 引导扇区代码（`boot.S`）的详细对比分析，请参见 [boot.asm 与 GRUB boot.S 对比分析](BOOTSECTOR_COMPARISON.md)。

```asm
; boot.asm - 最小引导扇区程序
; 这是一个 512 字节的引导扇区程序，BIOS 会将其加载到内存地址 0x7C00 处执行

org 0x7C00
; org 指令：设置程序的起始地址为 0x7C00
; BIOS 会将引导扇区加载到内存地址 0x7C00 处，所以程序需要知道这个地址
; 这样后续的标签和变量地址才能正确计算

bits 16
; bits 指令：指定汇编器生成 16 位代码
; 引导扇区程序运行在实模式下，使用 16 位寄存器

start:
; start 标签：程序的入口点
; BIOS 会从引导扇区的第一个字节开始执行，所以这里就是程序的开始

    mov ax, 0x0003      ; 设置80x25文本模式
; mov 指令：将立即数 0x0003 移动到寄存器 ax
; ax 是累加寄存器（16位），0x0003 表示设置显示模式为 80x25 文本模式
; 这是 BIOS 视频服务（INT 0x10）的功能号

    int 0x10
; int 指令：调用 BIOS 中断 0x10（视频服务中断）
; 配合 ax=0x0003，这个中断调用会设置显示模式为 80 列 x 25 行的文本模式
; 清空屏幕并准备显示文本

    mov si, msg
; mov 指令：将 msg 标签的地址移动到寄存器 si
; si 是源索引寄存器（Source Index），用于字符串操作
; msg 是后面定义的消息字符串的地址

    mov ah, 0x0E
; mov 指令：将 0x0E 移动到寄存器 ah（ax 的高 8 位）
; ah=0x0E 是 BIOS 视频服务的功能号，表示"在 TTY 模式下显示字符"
; 这个功能会在当前光标位置显示字符，并自动移动光标

.print:
; .print 标签：打印循环的开始
; 点号（.）表示这是一个局部标签，属于 start 标签的作用域

    lodsb
; lodsb 指令：Load String Byte，从字符串加载一个字节
; 从 si 寄存器指向的内存地址读取一个字节到 al 寄存器，然后 si 自动加 1
; al 是 ax 的低 8 位，用于存储单个字符

    test al, al
; test 指令：测试 al 寄存器的值
; test al, al 会检查 al 是否为零（通过 al AND al 操作）
; 如果 al 为零，零标志位（ZF）会被设置

    jz .halt
; jz 指令：Jump if Zero，如果零标志位被设置则跳转
; 如果 al 为零（字符串结束符），跳转到 .halt 标签
; 否则继续执行下一条指令

    int 0x10
; int 指令：再次调用 BIOS 中断 0x10
; 此时 ah=0x0E（之前设置的），al 包含要显示的字符
; 这个中断调用会在屏幕上显示 al 中的字符

    jmp .print
; jmp 指令：无条件跳转到 .print 标签
; 继续循环，读取并显示下一个字符

.halt:
; .halt 标签：程序结束，进入无限循环
; 当字符串打印完成后，程序跳转到这里

    jmp $
; jmp 指令：跳转到当前地址（$ 表示当前地址）
; 这是一个无限循环，程序会一直在这里执行
; 引导扇区程序执行完后应该进入无限循环，等待用户操作或加载操作系统

msg db "Hello from Boot Sector!", 0
; db 指令：Define Byte，定义字节数据
; msg 是标签，指向这个字符串的起始地址
; "Hello from Boot Sector!" 是要显示的字符串
; 0 是字符串结束符（null terminator），用于标识字符串的结束

times 510-($-$$) db 0
; times 指令：重复指定次数的操作
; 
; 为什么是 510 字节？
; - 引导扇区的总大小必须是 512 字节（一个扇区的大小）
; - 最后 2 字节（第 511-512 字节）必须存储引导扇区标志 0xAA55
; - 因此，程序代码和数据部分最多只能占用前 510 字节（第 1-510 字节）
;
; 计算过程：
; - $ 表示当前地址（msg 字符串定义后的地址）
; - $$ 表示程序起始地址（org 0x7C00，即 0x7C00）
; - ($-$$) 计算从程序开始到当前位置已经使用的字节数
; - 510-($-$$) 计算还需要填充多少个 0 字节，才能让程序部分正好是 510 字节
;
; 示例：如果程序已经用了 50 字节，那么 510-50=460，需要填充 460 个 0
; 这样：50 字节程序 + 460 字节填充 = 510 字节，再加上 2 字节标志 = 512 字节

dw 0xAA55          ; 引导扇区标志
; dw 指令：Define Word，定义一个字（2 字节）的数据
; 0xAA55 是引导扇区的魔数（magic number）
; BIOS 会检查引导扇区的最后两个字节是否为 0xAA55
; 如果不是这个值，BIOS 会认为这不是有效的引导扇区，不会执行
; 注意：x86 是小端序，所以 0x55 在低地址，0xAA 在高地址
```

### SeaBIOS 如何加载引导扇区

#### INT 19h 引导加载服务

当 SeaBIOS 完成 POST 初始化后，会调用 `startBoot()` 函数触发 INT 19h，开始引导过程。

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

#### INT 19h 处理程序

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

#### 引导设备选择

**源代码位置：`seabios/src/boot.c:987-1025`**

```c
// 确定下一个引导方法并尝试引导
static void
do_boot(int seq_nr)
{
    if (! CONFIG_BOOT)
        panic("Boot support not compiled in.\n");

    if (seq_nr >= BEVCount)
        boot_fail();  // 所有设备都失败

    // 引导指定的 BEV（Boot Execution Vector）类型
    struct bev_s *ie = &BEV[seq_nr];
    switch (ie->type) {
    case IPL_TYPE_FLOPPY:
        printf("Booting from Floppy...\n");
        boot_disk(0x00, CheckFloppySig);  // 从软盘引导（驱动器 0x00）
        break;
    case IPL_TYPE_HARDDISK:
        printf("Booting from Hard Disk...\n");
        boot_disk(0x80, 1);  // 从硬盘引导（驱动器 0x80）
        break;
    case IPL_TYPE_CDROM:
        boot_cdrom((void*)ie->vector);
        break;
    // ... 其他引导类型
    }

    // 引导失败：调用 INT 18h 恢复函数（尝试下一个设备）
    struct bregs br;
    memset(&br, 0, sizeof(br));
    br.flags = F_IF;
    call16_int(0x18, &br);
}
```

#### 读取引导扇区到内存

**源代码位置：`seabios/src/boot.c:882-917`**

```c
// 从磁盘引导（软盘或硬盘）
static void
boot_disk(u8 bootdrv, int checksig)
{
    u16 bootseg = 0x07c0;  // 引导扇区加载地址：段地址 0x07C0
                           // 物理地址 = 0x07C0 * 16 + 0x0000 = 0x7C00

    // 步骤 1: 使用 INT 13h 读取引导扇区
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

    // 步骤 3: 验证引导扇区签名（可选）
    if (checksig) {
        struct mbr_s *mbr = (void*)0;  // 在段 0x07C0 的偏移 0 处
        // 检查最后两个字节是否为 0xAA55
        if (GET_FARVAR(bootseg, mbr->signature) != MBR_SIGNATURE) {
            printf("Boot failed: not a bootable disk\n\n");
            return;
        }
    }

    // 步骤 4: 规范化段:偏移地址格式
    // bootseg:bootip = 0x07C0:0x0000 → 0x0000:0x7C00
    u16 bootip = (bootseg & 0x0fff) << 4;  // 提取偏移部分
    bootseg &= 0xf000;                      // 提取段部分

    // 步骤 5: 跳转到引导扇区程序执行
    call_boot_entry(SEGOFF(bootseg, bootip), bootdrv);
    // 实际执行：跳转到 0x0000:0x7C00，开始执行引导扇区代码
}
```

**关键点说明：**

1. **内存地址计算**：
   - 段地址 `0x07C0` × 16 + 偏移 `0x0000` = 物理地址 `0x7C00`
   - 这是 BIOS 规范规定的引导扇区加载地址

2. **INT 13h 调用参数**：
   - `AH=0x02`：读扇区功能
   - `AL=1`：读取 1 个扇区（512 字节）
   - `DL`：驱动器号（0x00=软盘A，0x80=第一个硬盘）
   - `ES:BX`：目标缓冲区地址（0x07C0:0x0000）

3. **引导扇区验证**：
   - 检查最后两个字节是否为 `0xAA55`
   - 如果不是，BIOS 认为这不是有效的引导扇区

### 完整引导流程

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
    └─ 跳转到 0x0000:0x7C00 执行
    ↓
引导扇区程序执行（boot.asm）
    ├─ 设置显示模式（INT 10h, AH=0x00, AL=0x03）
    ├─ 打印消息（INT 10h, AH=0x0E）
    └─ 进入无限循环（jmp $）
    ↓
（实际引导扇区会加载操作系统或更复杂的 bootloader）
```

### 关键内存地址和中断服务

| 地址/中断 | 说明 | 用途 |
|-----------|------|------|
| `0x7C00` | 引导扇区加载地址 | BIOS 将引导扇区加载到此地址 |
| `0x07C0:0x0000` | 引导扇区段:偏移格式 | 等价于物理地址 0x7C00 |
| `INT 10h` | BIOS 视频服务 | 设置显示模式、显示字符 |
| `INT 13h` | BIOS 磁盘服务 | 读取/写入磁盘扇区 |
| `INT 19h` | BIOS 引导加载服务 | 加载并执行引导扇区 |

### 在 QEMU 中测试引导扇区

要测试这个引导扇区程序，可以按以下步骤操作：

1. **编译引导扇区程序**：
```bash
nasm -f bin boot.asm -o boot.bin
```

2. **创建虚拟磁盘并写入引导扇区**：
```bash
dd if=/dev/zero of=disk.img bs=512 count=2880  # 创建 1.44MB 软盘镜像
dd if=boot.bin of=disk.img bs=512 count=1 conv=notrunc  # 写入引导扇区
```

3. **在 QEMU 中启动**：
```bash
qemu-system-x86_64 -fda disk.img
```

4. **预期结果**：
   - QEMU 窗口显示 "Hello from Boot Sector!"
   - 程序进入无限循环，等待用户操作

### 总结

本节通过一个最小化的引导扇区程序，详细说明了：

1. **引导扇区的结构**：512 字节，最后 2 字节必须是 `0xAA55`
2. **SeaBIOS 的引导流程**：从 INT 19h 到读取引导扇区的完整过程
3. **内存布局**：引导扇区被加载到固定的 `0x7C00` 地址
4. **BIOS 服务调用**：使用 INT 10h 显示文本，INT 13h 读取磁盘

这个简单的引导扇区程序展示了 BIOS 和用户代码之间的交互：BIOS 提供底层硬件服务（通过中断），用户代码通过调用这些服务完成基本功能。在实际系统中，引导扇区会加载更复杂的 bootloader（如 GRUB），然后由 bootloader 加载操作系统内核。

---

## 附录

- [附录A：键盘中断处理代码分析](APPENDIX_A_KEYBOARD_INTERRUPT.md)
- [附录B：应用层事件机制](APPENDIX_B_EVENT_MECHANISM.md)
- [中断处理详解](INTERRUPT_HANDLING.md)

## Linux 内核接管 BIOS

### GRUB 如何加载内核到 head_64.S 入口点

在 GRUB 跳转到内核之前，需要完成以下步骤：

**源代码位置：`grub/grub-core/loader/i386/linux.c`**

#### 内核镜像结构

Linux 内核镜像（bzImage）包含两部分：

1. **Setup 代码**（实模式代码）：
   - 大小：通常 4-64 个扇区（由 `setup_sects` 字段指定）
   - 功能：切换到保护模式/长模式，解压内核

2. **压缩的内核代码**：
   - 位置：setup 代码之后
   - 格式：gzip 压缩的 vmlinux
   - 加载地址：`0x100000`（1MB）或内核指定的地址

#### GRUB 加载内核的完整流程

**步骤 1：读取内核文件头部**

```c
// grub/grub-core/loader/i386/linux.c:680-725
grub_cmd_linux (grub_command_t cmd, int argc, char *argv[])
{
    // 打开内核文件（如 /boot/vmlinuz-5.x.x）
    file = grub_file_open (argv[0]);
    
    // 读取整个文件到内存
    len = grub_file_size (file);
    kernel = grub_malloc (len);
    grub_file_read (file, kernel, len);
    
    // 解析内核头部（前 512+ 字节）
    grub_memcpy (&lh, kernel, sizeof (lh));
    
    // 验证内核签名
    // lh.header 必须是 "HdrS" (0x53726448)
    // lh.boot_flag 必须是 0xAA55
}
```

**步骤 2：计算内核加载地址**

```c
// grub/grub-core/loader/i386/linux.c:691-823
// 默认加载地址：0x100000 (1MB)
grub_uint64_t preferred_address = GRUB_LINUX_BZIMAGE_ADDR;  // 0x100000

// 如果内核支持重定位，使用内核指定的地址
if (relocatable)
    preferred_address = grub_le_to_cpu64 (lh.pref_address);
else
    preferred_address = GRUB_LINUX_BZIMAGE_ADDR;

// 分配内存并加载内核
allocate_pages (prot_size, &align, min_align, relocatable, preferred_address);
// prot_mode_target 是内核实际加载的物理地址
```

**步骤 3：设置内核启动参数**

```c
// grub/grub-core/loader/i386/linux.c:820-823
// code32_start 是内核的入口点地址
// lh.code32_start 是内核头部中的字段，表示相对于 0x100000 的偏移
linux_params.code32_start = prot_mode_target + lh.code32_start - GRUB_LINUX_BZIMAGE_ADDR;

// 设置其他参数
linux_params.type_of_loader = GRUB_LINUX_BOOT_LOADER_TYPE;  // 0x72
linux_params.cmd_line_ptr = ...;  // 内核命令行参数
linux_params.ramdisk_image = ...;  // initramfs 地址
```

**步骤 4：复制内核镜像到目标地址**

```c
// grub/grub-core/loader/i386/linux.c:1037-1039
// 将内核镜像（压缩部分）复制到目标地址
len = prot_file_size;
grub_memcpy (prot_mode_mem, kernel + kernel_offset, len);
// prot_mode_mem 指向 prot_mode_target（通常是 0x100000）
```

**步骤 5：跳转到内核入口点**

```c
// grub/grub-core/loader/i386/linux.c:446-667
grub_linux_boot (void)
{
    // 准备 boot_params 结构（包含 code32_start）
    *ctx.params = linux_params;
    
    // 设置寄存器状态
    struct grub_relocator32_state state;
    state.esi = ctx.real_mode_target;        // ESI = boot_params 地址
    state.esp = ctx.real_mode_target;        // ESP = 栈指针
    state.eip = ctx.params->code32_start;    // EIP = 内核入口点
    
    // 跳转到内核（通过 relocator 切换到保护模式并跳转）
    return grub_relocator32_boot (relocator, state, 0);
}
```

**步骤 6：Relocator 执行跳转**

```c
// grub/grub-core/lib/i386/relocator.c:75-117
grub_relocator32_boot (struct grub_relocator *rel, struct grub_relocator32_state state, ...)
{
    // 设置寄存器值
    grub_relocator32_eip = state.eip;  // 内核入口点地址
    grub_relocator32_esi = state.esi;  // boot_params 地址
    
    // 准备 relocator 代码（切换到保护模式并跳转）
    grub_memmove (relocator_mem, &grub_relocator32_start, ...);
    
    // 执行跳转（关闭中断，切换到保护模式，跳转到 state.eip）
    asm volatile ("cli");
    ((void (*) (void)) relst) ();  // 跳转到 relocator 代码
    // relocator 代码会：
    //   1. 切换到保护模式
    //   2. 设置 GDT
    //   3. 跳转到 state.eip（内核入口点）
}
```

**内核入口点说明：**

- **`code32_start`**：内核头部字段，表示内核入口点相对于 `0x100000` 的偏移
- **实际入口地址**：`prot_mode_target + code32_start - 0x100000`
- **对于 64 位内核**：入口点通常是 `startup_32`（32 位保护模式代码），然后切换到长模式，最终跳转到 `startup_64`

#### 内核启动参数传递

GRUB 通过 `boot_params` 结构（Linux Boot Protocol）向内核传递参数：

- **`code32_start`**：内核入口点地址（传递给内核，内核从这里开始执行）
- **`cmd_line_ptr`**：内核命令行参数地址（如 `root=/dev/sda1`）
- **`ramdisk_image`**：initramfs 地址
- **`ramdisk_size`**：initramfs 大小
- **`e820_map`**：系统内存映射表
- **`esi` 寄存器**：包含 `boot_params` 的地址（内核通过 `%esi` 访问）

### 内核早期启动（64 位）

**说明**：内核从 GRUB 跳转后，首先执行的是内核镜像中的 setup 代码（实模式），然后切换到保护模式，最终到达 `startup_64`。GRUB 跳转的地址是 `code32_start`，这是 setup 代码的入口点。

源代码位置：`linux/arch/x86/kernel/head_64.S:38-100`

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
    └─ 跳转到 0x0000:0x7C00 执行
    ↓
引导扇区程序执行（boot.asm 或 GRUB boot.S）
    ├─ 设置显示模式（INT 10h, AH=0x00, AL=0x03）
    ├─ 加载 GRUB Core（如果使用 GRUB）
    └─ 跳转到 GRUB Core 或操作系统加载器
    ↓
GRUB Core 执行（如果使用 GRUB）
    ├─ 解析配置文件
    ├─ 加载 Linux 内核镜像（bzImage）
    ├─ 设置内核启动参数（boot_params）
    └─ 跳转到内核入口点（head_64.S）
    ↓
Linux 内核早期初始化（head_64.S）
    ├─ 设置早期页表
    ├─ 切换到长模式（64位）
    └─ 跳转到 x86_64_start_kernel()
    ↓
x86_64_start_kernel()
    ├─ 设置早期 IDT（idt_setup_early_handler）
    ├─ 初始化微码更新
    └─ 调用 start_kernel()
    ↓
start_kernel()（Linux 内核主初始化）
    ├─ 初始化中断系统
    │   ├─ 重新编程 PIC（init_8259A）
    │   ├─ 设置 APIC 和中断门（idt_setup_apic_and_irq_gates）
    │   └─ 加载 IDT（load_idt）
    ├─ 初始化内存管理
    ├─ 初始化进程管理
    └─ 启动 init 进程
    ↓
Linux 内核完全接管系统
    ├─ BIOS 的 IVT 被内核的 IDT 取代
    ├─ BIOS 的 PIC 配置被内核重新编程
    └─ BIOS 代码基本不再执行
```

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
| `seabios/src/post.c:302-337` | POST 主入口点 | [SeaBIOS 初始化中断服务](#seabios-初始化中断服务) |
| `seabios/src/post.c:196-235` | maininit() 主初始化函数 | [SeaBIOS 初始化中断服务](#seabios-初始化中断服务) |
| `seabios/src/post.c:32-71` | ivt_init() IVT 初始化 | [SeaBIOS 初始化中断服务](#seabios-初始化中断服务) |
| `seabios/src/hw/pic.c:62-66` | pic_setup() PIC 初始化 | [SeaBIOS 初始化中断服务](#seabios-初始化中断服务) |
| `seabios/src/post.c:137-158` | interface_init() 接口初始化 | [SeaBIOS 初始化中断服务](#seabios-初始化中断服务) |
| `seabios/src/post.c:182-193` | startBoot() 启动引导 | [引导扇区程序](#引导扇区程序从-seabios-到用户代码的执行) |
| `seabios/src/boot.c:1040-1046` | handle_19() INT 19h 处理程序 | [引导扇区程序](#引导扇区程序从-seabios-到用户代码的执行) |
| `seabios/src/boot.c:882-917` | boot_disk() 读取引导扇区 | [引导扇区程序](#引导扇区程序从-seabios-到用户代码的执行) |
| `seabios/src/boot.c:987-1025` | do_boot() 引导设备选择 | [引导扇区程序](#引导扇区程序从-seabios-到用户代码的执行) |

### GRUB 源代码

| 文件路径 | 功能说明 | 相关章节 |
|---------|---------|---------|
| `grub/grub-core/boot/i386/pc/boot.S` | GRUB 引导扇区代码 | [引导扇区程序](#引导扇区程序从-seabios-到用户代码的执行) |
| `grub/grub-core/boot/i386/pc/diskboot.S:38-341` | 磁盘引导代码 | [引导扇区程序](#引导扇区程序从-seabios-到用户代码的执行) |
| `grub/grub-core/boot/i386/pc/startup_raw.S:76-104` | 启动代码 | [引导扇区程序](#引导扇区程序从-seabios-到用户代码的执行) |
| `grub/grub-core/kern/i386/realmode.S:133-195` | 实模式支持代码 | [引导扇区程序](#引导扇区程序从-seabios-到用户代码的执行) |
| `grub/grub-core/loader/i386/linux.c` | Linux 内核加载器 | [Linux 内核接管 BIOS](#linux-内核接管-bios) |

### Linux 内核源代码

| 文件路径 | 功能说明 | 相关章节 |
|---------|---------|---------|
| `linux/arch/x86/boot/compressed/head_64.S` | 内核早期入口点 | [Linux 内核接管 BIOS](#linux-内核接管-bios) |
| `linux/arch/x86/kernel/head64.c:1932` | x86_64_start_kernel() 入口 | [Linux 内核接管 BIOS](#linux-内核接管-bios) |
| `linux/arch/x86/kernel/idt.c:216-227` | idt_setup_early_traps() 早期 IDT 设置 | [Linux 内核接管 BIOS](#linux-内核接管-bios) |
| `linux/arch/x86/kernel/idt.c:281-315` | idt_setup_apic_and_irq_gates() 完成 IDT 设置 | [Linux 内核接管 BIOS](#linux-内核接管-bios) |
| `linux/arch/x86/kernel/i8259.c:349-399` | init_8259A() PIC 重新编程 | [Linux 内核接管 BIOS](#linux-内核接管-bios) |

### 用户代码示例

| 文件路径 | 功能说明 | 相关章节 |
|---------|---------|---------|
| `boot.asm` | 最小化引导扇区程序示例 | [引导扇区程序](#引导扇区程序从-seabios-到用户代码的执行) |

### 关键数据结构

| 数据结构 | 位置 | 说明 |
|---------|------|------|
| **IVT（中断向量表）** | `0x0000:0x0000` | BIOS 中断向量表，256 个条目，每个 4 字节 |
| **IDT（中断描述符表）** | 内核内存 | 内核中断描述符表，替代 BIOS IVT |
| **GDT（全局描述符表）** | 内核内存 | 全局描述符表，用于保护模式 |
| **boot_params** | 内核内存 | Linux 内核启动参数结构 |
