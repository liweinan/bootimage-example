# GRUB 加载 Linux 内核详细流程

本文档详细说明 GRUB 如何加载 Linux 内核镜像并跳转到内核入口点的完整过程，包括源代码分析和实现细节。

## GRUB 加载内核的完整流程概述

从 `_start` 调用 `grub_main()` 后，GRUB 开始加载 Linux 内核的完整流程：

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

**关键点：**
- **延迟执行机制**：`grub_cmd_linux()` 只负责准备（加载内核、注册函数），不执行跳转
- **用户交互触发**：跳转由用户在菜单中选择启动项时触发
- **寄存器状态**：跳转时 `ESI` 包含 `boot_params` 地址，`EIP` 指向内核入口点（`code32_start`）

## grub_main() 函数详细讲解

**源代码位置：** `grub/grub-core/kern/main.c:304-370`

`grub_main()` 是 GRUB Core 的主入口函数，由 `startup.S` 的 `_start` 函数调用。它负责初始化 GRUB 核心功能、解析配置文件、加载模块、显示菜单，并最终执行用户选择的启动项。

**函数签名：**

```c
void __attribute__ ((noreturn))
grub_main (void)
```

**关键特性：**
- **不返回**：`noreturn` 属性表示函数不会返回（会加载内核并跳转）
- **主入口点**：GRUB Core C 代码的入口点
- **运行模式**：保护模式（32 位）

**完整源代码分析：**

```c
// grub/grub-core/kern/main.c:304-370
void __attribute__ ((noreturn))
grub_main (void)
{
#ifdef GRUB_STACK_PROTECTOR
    // 步骤 1: 更新栈保护（如果启用）
    grub_update_stack_guard ();
#endif

    // 步骤 2: 初始化机器相关功能
    grub_machine_init ();
    // 功能：
    //   - 初始化平台特定的硬件（如 i386_pc 平台的磁盘、内存映射等）
    //   - 设置终端（控制台输入/输出）
    //   - 初始化时间服务（RTC）
    // 源代码位置：grub/grub-core/kern/i386/pc/init.c:grub_machine_init()

    grub_boot_time ("After machine init.");

#ifndef GRUB_MACHINE_EFI
    // 步骤 3: 显示欢迎信息（仅 BIOS 模式）
    grub_setcolorstate (GRUB_TERM_COLOR_HIGHLIGHT);
    grub_printf ("Welcome to GRUB!\n\n");
    grub_setcolorstate (GRUB_TERM_COLOR_STANDARD);
#endif

    // 步骤 4: 初始化验证器 API（用于验证文件签名）
    grub_verifiers_init ();

    // 步骤 5: 加载嵌入的配置文件（grub.cfg）
    grub_load_config ();
    // 功能：
    //   - 从 core.img 中查找嵌入的配置文件（OBJ_TYPE_CONFIG 类型的模块）
    //   - 将配置文件内容加载到内存（load_config 变量）
    //   - 配置文件通常是在构建时嵌入到 core.img 中的
    // 源代码位置：grub/grub-core/kern/main.c:80-100

    grub_boot_time ("Before loading embedded modules.");

    // 步骤 6: 注册导出的符号（用于模块链接）
    grub_register_exported_symbols ();

#ifdef GRUB_LINKER_HAVE_INIT
    // 步骤 7: 初始化链接器（如果支持）
    grub_arch_dl_init_linker ();
#endif

    // 步骤 8: 加载嵌入的模块
    grub_load_modules ();
    // 功能：
    //   - 遍历 core.img 中的所有模块（OBJ_TYPE_ELF 类型）
    //   - 使用 grub_dl_load_core() 加载每个模块
    //   - 模块包括：文件系统驱动（ext2, fat, iso9660 等）、磁盘驱动、命令等
    // 源代码位置：grub/grub-core/kern/main.c:58-75

    grub_boot_time ("After loading embedded modules.");

    // 步骤 9: 检查是否禁用 CLI（命令行界面）
    check_is_cli_disabled ();

    // 步骤 10: 设置根设备和前缀路径
    grub_set_prefix_and_root ();
    // 功能：
    //   - 确定 GRUB 的根设备（通常是包含 /boot/grub 的设备）
    //   - 设置 prefix 路径（通常是 /boot/grub）
    //   - 这些信息用于查找 grub.cfg 文件和其他资源
    grub_env_export ("root");    // 导出 root 环境变量
    grub_env_export ("prefix");  // 导出 prefix 环境变量

    // 步骤 11: 回收模块占用的空间
    reclaim_module_space ();
    // 功能：
    //   - 模块加载后，可以回收模块占用的内存空间
    //   - 释放内存用于后续操作（如加载内核）

    grub_boot_time ("After reclaiming module space.");

    // 步骤 12: 注册核心命令
    grub_register_core_commands ();
    // 功能：
    //   - 注册 GRUB 的核心命令（如 linux, initrd, set, insmod 等）
    //   - 这些命令可以在 grub.cfg 或命令行中使用

    grub_boot_time ("Before execution of embedded config.");

    // 步骤 13: 执行嵌入的配置文件（如果存在）
    if (load_config)
        grub_parser_execute (load_config);
    // 功能：
    //   - 解析并执行嵌入的 grub.cfg 配置文件
    //   - 执行配置文件中的命令（如 menuentry, linux, initrd 等）
    //   - 当遇到 linux 命令时，会调用 grub_cmd_linux() 加载内核
    // 源代码位置：grub/grub-core/commands/parser.c:grub_parser_execute()

    grub_boot_time ("After execution of embedded config. Attempt to go to normal mode");

    // 步骤 14: 加载 normal 模式（菜单显示和交互）
    grub_load_normal_mode ();
    // 功能：
    //   - 加载 normal.mod 模块（如果存在）
    //   - normal 模式提供菜单显示、用户交互等功能
    //   - 如果 normal.mod 不存在或加载失败，会进入 rescue 模式
    // 源代码位置：grub/grub-core/kern/main.c:233-250

    // 步骤 15: 运行 rescue 模式（如果 normal 模式不可用）
    grub_rescue_run ();
    // 功能：
    //   - 如果 normal 模式不可用，进入 rescue 模式
    //   - rescue 模式提供基本的命令行界面
    //   - 用户可以手动输入命令（如 linux, initrd 等）
    // 注意：如果 normal 模式成功加载，通常不会执行到这里
}
```

**关键函数说明：**

**1. `grub_machine_init()` - 机器初始化**

**源代码位置：** `grub/grub-core/kern/i386/pc/init.c:grub_machine_init()`

**功能：**
- 初始化平台特定的硬件（如 i386_pc 平台的磁盘、内存映射等）
- 设置终端（控制台输入/输出）
- 初始化时间服务（RTC）
- 初始化 GRUB 的内存分配器

> **详细说明**：关于 `grub_machine_init()` 的详细实现、为什么 GRUB 需要自己的抽象层、跨平台支持机制等，请参见 [GRUB 架构设计与初始化详解](GRUB_ARCHITECTURE_AND_INIT.md)。

**2. `grub_load_config()` - 加载配置文件**

**功能：**
- 从 `core.img` 中查找嵌入的配置文件（`grub.cfg`）
- 将配置文件内容加载到内存

**3. `grub_load_modules()` - 加载嵌入的模块**

**功能：**
- 遍历 `core.img` 中的所有模块（文件系统驱动、磁盘驱动、命令模块等）
- 使用 `grub_dl_load_core()` 加载每个模块

**4. `grub_parser_execute()` - 执行配置文件**

**功能：**
- 解析并执行 `grub.cfg` 配置文件
- **关键**：当遇到 `linux` 命令时，会调用 `grub_cmd_linux()` 加载内核

**配置示例：**

```bash
# /boot/grub/grub.cfg
menuentry "Linux 5.x.x" {
    linux /boot/vmlinuz-5.x.x root=/dev/sda1 ro quiet
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

**5. `grub_load_normal_mode()` - 加载 normal 模式**

**功能：**
- 尝试加载 `normal.mod` 模块（如果存在）
- normal 模式提供菜单显示、用户交互等功能

> **详细说明**：关于 `grub_main()` 中其他初始化函数的详细实现，请参见 [GRUB 架构设计与初始化详解](GRUB_ARCHITECTURE_AND_INIT.md)。

**关键点：**

1. **配置文件执行时机**：
   - `grub_parser_execute()` 在 `grub_main()` 中执行
   - 执行 `grub.cfg` 时，遇到 `linux` 命令会调用 `grub_cmd_linux()`
   - **此时只是加载内核到内存，注册启动函数，不立即跳转**

2. **延迟执行机制**：
   - `grub_cmd_linux()` 只负责准备（加载内核、注册函数）
   - 跳转由用户在菜单中选择启动项时触发
   - 用户可以继续浏览菜单、修改参数或选择其他启动项

## GRUB 加载内核的详细流程

本章节详细说明 GRUB 加载内核的各个步骤，包括源代码分析和实现细节。

### grub_cmd_linux() 函数详细讲解

**源代码位置：** `grub/grub-core/loader/i386/linux.c:680-725`

**功能：**
- 打开内核文件（如 `/boot/vmlinuz-5.x.x`）
- 解析内核头部，验证内核签名
- 加载内核镜像到内存（`0x100000`）
- 设置内核启动参数（`boot_params`）
- 注册启动函数 `grub_linux_boot()`

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

**完整源代码分析：**

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

**关键点：**
- **延迟执行机制**：`grub_cmd_linux()` 只负责准备（加载内核、注册函数），不执行跳转
- **用户交互触发**：跳转由用户在菜单中选择启动项时触发
- **灵活性**：用户可以在加载内核后继续浏览菜单、修改参数或选择其他启动项

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

### grub_linux_boot() 函数详细讲解

**源代码位置：** `grub/grub-core/loader/i386/linux.c:446-667`

**功能：**
- 准备 `boot_params` 结构（包含 `code32_start`）
- 设置寄存器状态（ESI、ESP、EIP）
- 通过 `grub_relocator32_boot()` 跳转到内核入口点

**完整源代码分析：**

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

### grub_relocator32_boot() 函数详细讲解

**源代码位置：** `grub/grub-core/lib/i386/relocator.c:75-117`

**功能：**
- 设置寄存器值（`grub_relocator32_eip`、`grub_relocator32_esi`）
- 准备 relocator 代码（切换到保护模式并跳转）
- 执行跳转到内核入口点（`code32_start`）

**完整源代码分析：**

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

### code32_start 地址的来源和传递过程

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

### 内存布局和启动参数

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

