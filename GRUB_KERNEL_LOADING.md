# GRUB 加载 Linux 内核详细流程

本文档详细说明 GRUB 如何加载 Linux 内核镜像并跳转到内核入口点的完整过程，包括源代码分析和实现细节。

## 流程概述

从 `_start` 调用 `grub_main()` 后，GRUB 开始加载 Linux 内核的完整流程。**BIOS 和 UEFI 的启动流程不同**：

### BIOS 启动流程

```
grub_main()（grub/grub-core/kern/main.c）
    ├─ 解析 grub.cfg：只注册 menuentry（grub_cmd_menuentry 把条目标题和脚本体存到 entry，不执行脚本体）
    ├─ 显示启动菜单
    └─ 用户选择某菜单项（按 Enter）
        ↓
GRUB 执行该条目的脚本体（grub_menu_execute_entry → entry->sourcecode，见 normal/menu.c:298）
        ↓
执行到 linux 命令 → grub_cmd_linux()
    ├─ 源代码位置：grub/grub-core/loader/i386/linux.c
    ├─ 加载内核镜像到临时缓冲区（通常在 16MB+，不是 0x100000 (1MB)）
    ├─ 设置内核启动参数（boot_params）
    ├─ 最终目标地址：0x100000 (1MB)（boot 时 relocator 代码会将内核复制到此）
    └─ 注册启动函数 grub_linux_boot()
        ↓
grub_cmd_initrd()（脚本中下一行 initrd 命令，可选）
    ├─ 读取 initrd 文件，分配内存，加载并设置 boot_params.ramdisk_*
    └─ （同上，均在“执行该条目脚本”阶段完成）
        ↓
脚本执行完毕；若 grub_loader_is_loaded() 则隐式执行 boot（menu.c:305-307）
        ↓
grub_linux_boot() → grub_relocator32_boot()
    ├─ 源代码位置：grub/grub-core/loader/i386/linux.c
    └─ 跳转到内核入口点（code32_start）
        ↓
grub_relocator32_boot() 跳转到内核入口点（code32_start）
    ├─ 源代码位置：grub/grub-core/lib/i386/relocator.c
    ├─ 跳转地址：code32_start（内核头部字段，相对于 0x100000 (1MB) 的偏移）
    └─ 寄存器状态：
        ├─ ESI = boot_params 地址
        ├─ ESP = 栈指针
        └─ EIP = code32_start（内核入口点）
    ↓
Linux 内核 Setup 代码（实模式）
    ├─ 源代码位置：linux/arch/x86/boot/header.S
    ├─ 内存位置：0x100000 (1MB)或内核指定的地址
    ├─ 运行模式：实模式（初始阶段）
    ├─ 验证内核签名（boot_flag = 0xAA55）
    ├─ 初始化基本环境
    ├─ 切换到保护模式
    └─ 跳转到压缩内核解压代码
```

### UEFI 启动流程

```
grub_main()（grub/grub-core/kern/main.c）
    ├─ 解析 grub.cfg：只注册 menuentry（脚本体存到 entry，不执行）
    ├─ 显示启动菜单
    └─ 用户选择某菜单项（按 Enter）
        ↓
GRUB 执行该条目的脚本体（grub_menu_execute_entry → entry->sourcecode）
        ↓
执行到 linux 命令 → grub_cmd_linux()
    ├─ 源代码位置：grub/grub-core/loader/efi/linux.c:477-600
    ├─ 验证内核格式（PE/COFF，UEFI stub 内核）
    ├─ 分配内存（使用 EFI AllocatePages）
    ├─ 加载内核镜像到内存
    ├─ 准备命令行参数（转换为 UTF-16）
    └─ 注册启动函数 grub_linux_boot()
        ↓
grub_cmd_initrd()（执行 initrd 命令，可选）
    ├─ 源代码位置：grub/grub-core/loader/efi/linux.c:400-476
    ├─ 方式 1：LoadFile2 协议（现代内核，image_version >= 1）
    │   └─ 安装 LoadFile2 协议，内核通过协议读取 initrd
    └─ 方式 2：直接加载（非 x86 架构或旧内核）
        ├─ 分配内存
        ├─ 加载 initrd 到内存
        └─ 设置 FDT（设备树）中的 initrd 信息
        ↓
用户按 Enter 选择启动项
        ↓
grub_linux_boot() → grub_arch_efi_linux_boot_image()
    ├─ 源代码位置：grub/grub-core/loader/efi/linux.c:270-280
    └─ 调用 grub_arch_efi_linux_boot_image()
        ↓
grub_arch_efi_linux_boot_image() → grub_efi_start_image()
    ├─ 源代码位置：grub/grub-core/loader/efi/linux.c:194-280
    ├─ 创建内存映射设备路径（Memory Mapped Device Path）
    ├─ 使用 EFI LoadImage 服务加载内核
    │   └─ grub_efi_load_image(image_handle, device_path, kernel_addr, size)
    ├─ 设置命令行参数（load_options，UTF-16 格式）
    └─ 使用 EFI StartImage 服务启动内核
        └─ grub_efi_start_image(image_handle, 0, NULL)
            ↓
EFI 固件执行内核（通过 StartImage 服务）
    ├─ EFI 固件负责：
    │   ├─ 设置 CPU 状态（寄存器、段、分页等）
    │   ├─ 准备内核执行环境
    │   └─ 跳转到内核入口点（PE/COFF EntryPoint）
    └─ 控制权转移到内核（GRUB 不再执行）
        ↓
Linux 内核 EFI stub 代码（保护模式/长模式）
    ├─ 源代码位置：linux/arch/x86/boot/compressed/efi_stub_64.S
    ├─ 运行模式：保护模式/长模式（UEFI 环境）
    ├─ 验证内核签名（PE/COFF 格式）
    ├─ 处理 EFI 系统表（EFI System Table）
    ├─ 处理命令行参数（从 load_options 读取）
    ├─ 处理 initrd（通过 LoadFile2 协议或 FDT）
    └─ 继续内核初始化流程
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

**关键点对比：**

| 特性 | BIOS 启动 | UEFI 启动 |
|------|----------|----------|
| **延迟执行机制** | ✅ `grub_cmd_linux()` 只负责准备，不执行跳转；跳转由脚本结束后的隐式/显式 boot 触发 | ✅ 相同 |
| **用户交互触发** | ✅ 先选菜单项，再执行该条目脚本体（此时才调用 `grub_cmd_linux()`）；脚本结束后隐式 boot | ✅ 相同 |
| **寄存器状态** | `ESI` = `boot_params` 地址<br>`EIP` = `code32_start` | 由 EFI 固件设置（通过 `StartImage` 服务） |
| **跳转方式** | relocator 代码手动跳转 | EFI `StartImage` 服务 |
| **内核格式** | bzImage（实模式 setup + 压缩内核） | PE/COFF（UEFI stub 内核） |
| **内核入口点** | `code32_start`（实模式代码） | PE/COFF EntryPoint（保护模式/长模式） |
| **模式切换** | 需要（保护模式 → 实模式） | 不需要（都在保护模式/长模式） |
| **参数传递** | `boot_params` 结构（通过 `ESI` 寄存器） | EFI System Table + 命令行参数（通过 `load_options`） |

## grub_cmd_linux() 与 grub_linux_boot() 职责划分

**触发时机不同**：解析 `grub.cfg` 时只注册 menuentry（脚本体存到 entry->sourcecode，不执行）。用户**选择该菜单项**后，GRUB 执行该条目的脚本体（`grub_menu_execute_entry` → `grub_script_execute_new_scope(entry->sourcecode)`），此时才执行到 `linux` 命令 → `grub_cmd_linux()`。`grub_linux_boot()` 在脚本执行完后由隐式或显式 `boot` 调用（loader 机制）。

| 项目 | grub_cmd_linux() | grub_linux_boot() |
|------|-------------------|--------------------|
| **调用时机** | 用户选择该菜单项后，执行该条目脚本时执行到 `linux` 命令 | 脚本执行完后隐式/显式 `boot` 时 |
| **主要动作** | 打开内核文件；解析头部；通过 relocator 分配临时缓冲区（通常 16MB+）；把内核拷到临时缓冲区；计算并设置 boot_params（含 code32_start、cmd_line_ptr、ramdisk 等）；**注册** `grub_linux_boot()`（不跳转） | 用已设好的 boot_params 填 state（esi、esp、eip=code32_start）；调用 `grub_relocator32_boot(relocator, state, 0)`，由 relocator 完成复制到 0x100000 (1MB) 并跳转内核 |
| **是否跳转** | 否，仅准备并注册 | 是，通过 grub_relocator32_boot() 最终跳入内核 |

**简要结论**：加载内核、设 boot_params、注册启动函数都在 **grub_cmd_linux()**；真正执行“复制到 0x100000 (1MB) + 跳内核”的是 **grub_linux_boot()** → **grub_relocator32_boot()**。

### 从 grub_main 到 grub_cmd_menuentry 的调用链（源码依据）

**典型路径（磁盘上的 grub.cfg）**：主菜单的 menuentry 来自** normal 模式**读取的配置文件，不是来自嵌入 core 的 config。

```
grub_main()                                    [kern/main.c:304]
  → grub_load_normal_mode()                    [kern/main.c:368]
      → grub_dl_load("normal")                  [kern/main.c:236]
      → grub_command_execute("normal", 0, 0)    [kern/main.c:242]
  → grub_cmd_normal(..., 0, 0)                 [normal/main.c:321]
      → grub_enter_normal_mode(config)          [normal/main.c:355/359/362，config 多为 prefix/grub.cfg]
  → grub_normal_execute(config, 0, 0)           [normal/main.c:310]
      → read_config_file(config)               [normal/main.c:283，打开 grub.cfg 文件]
          → while: read_config_file_getline(&line, 0, file)     [normal/main.c:182]
          → grub_normal_parse_line(line, read_config_file_getline, file)  [normal/main.c:185]
              → grub_script_parse(line, getline, file)          [script/main.c:30]
              → grub_script_execute(parsed_script)              [script/main.c:36]
              → （解析到 menuentry 时）grub_extcmd_dispatcher → grub_cmd_menuentry  [script/execute.c；commands/extcmd.c]
  → grub_cmd_menuentry(ctxt, ...)              [commands/menuentry.c:256]
      → grub_normal_add_menu_entry(..., sourcecode, ...)        [commands/menuentry.c:282-306]
          → 仅把条目标题和脚本体（大括号内字符串）存到 entry->sourcecode，不执行脚本体
```

**可选路径（嵌入 core 的 config）**：若 core 镜像内嵌了 config（OBJ_TYPE_CONFIG），会先执行一遍，再用 rescue 解析器逐行执行，其中若有 menuentry 也会走到 grub_cmd_menuentry。

```
grub_main()
  → grub_load_config()                         [kern/main.c:332，从 OBJ_TYPE_CONFIG 读出 load_config]
  → grub_parser_execute(load_config)           [kern/main.c:364]
      → 循环：grub_parser_execute_getline(&line, 0, &source)    [kern/parser.c:336]
             grub_rescue_parse_line(line, grub_parser_execute_getline, &source)  [kern/parser.c:338]
             → grub_parser_split_cmdline(...) → grub_command_find(name) → (cmd->func)(...)  [kern/rescue_parser.c]
      → 若该行是 menuentry：cmd->func = grub_extcmd_dispatch → grub_extcmd_dispatcher → grub_cmd_menuentry
```

**用户选择菜单项后**（脚本体才执行，此时才可能调用 grub_cmd_linux）：

```
用户按 Enter 选中某条
  → grub_menu_execute_entry(entry)             [normal/menu.c:206，如 347/358]
      → grub_script_execute_new_scope(entry->sourcecode, entry->argc, entry->args)  [normal/menu.c:298]
          → 执行到 linux 命令 → grub_command_find("linux") 查表 → (cmd->func)(...) = grub_cmd_linux()
          → 执行到 initrd 命令 → grub_command_find("initrd") 查表 → grub_cmd_initrd()
          → 脚本结束；若 grub_loader_is_loaded() 则隐式 grub_command_execute("boot")  [normal/menu.c:305-307]
  → grub_linux_boot() → grub_relocator32_boot()
```

## 核心函数详解

### grub_main() 函数

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
    // 功能：
    //   - 注册文件过滤器 GRUB_FILE_FILTER_VERIFY
    //   - 当打开文件时，自动调用验证器验证文件签名
    //   - 主要用于安全启动（Secure Boot）场景
    // 验证的文件类型（根据 lockdown_verifier）：
    //   - GRUB_FILE_TYPE_LINUX_KERNEL：Linux 内核（vmlinuz）
    //   - GRUB_FILE_TYPE_GRUB_MODULE：GRUB 模块（文件系统驱动、命令等）
    //   - GRUB_FILE_TYPE_MULTIBOOT_KERNEL：Multiboot 内核
    //   - GRUB_FILE_TYPE_XEN_HYPERVISOR：Xen 虚拟机监控程序
    //   - GRUB_FILE_TYPE_BSD_KERNEL：BSD 内核
    //   - GRUB_FILE_TYPE_XNU_KERNEL：macOS 内核
    //   - GRUB_FILE_TYPE_ACPI_TABLE：ACPI 表
    //   - GRUB_FILE_TYPE_DEVICE_TREE_IMAGE：设备树镜像
    //   - 以及其他可执行文件类型
    // 工作原理：
    //   - 当调用 grub_file_open() 打开文件时（如 grub_file_open(argv[0], GRUB_FILE_TYPE_LINUX_KERNEL)）
    //   - 文件过滤器会自动调用 grub_verifiers_open() 验证文件签名
    //   - 如果签名验证失败，文件打开会失败，阻止加载未签名的内核或模块
    // 源代码位置：grub/grub-core/kern/verifiers.c:225-228

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
    //   - 模块包括：文件系统驱动、磁盘驱动、加载器（linux.mod）、命令等
    // ⚠️ 注意：
    //   - 这一步只加载嵌入在 core.img 中的模块（构建时通过 grub-mkimage 作为位置参数指定）
    //   - insmod 命令加载的动态模块（.mod 文件）不在这一步处理
    //   - linux 命令由 linux.mod 模块提供，如果嵌入则此步骤自动加载
    // 详细说明请参见下方"核心函数详解 > grub_load_modules()"

    grub_boot_time ("After loading embedded modules.");

    // 步骤 9: 检查是否禁用 CLI（命令行界面）
    check_is_cli_disabled ();
    // 功能：
    //   - 检查 core.img 中是否有 OBJ_TYPE_DISABLE_CLI 类型的模块
    //   - 如果找到，设置 cli_disabled = true，禁用命令行界面
    // 用途：
    //   - 主要用于安全启动（Secure Boot）或系统安全策略
    //   - 防止用户通过命令行界面修改启动参数或执行未授权操作
    //   - 与 BIOS/UEFI 启动模式无关（两种模式都支持此功能）
    // 对后续执行流程的影响：
    //   1. 菜单显示（normal/menu_text.c:181）：
    //      - 如果 CLI 被禁用，不显示"按 'c' 进入命令行"的提示
    //      - 用户只能选择菜单项，无法进入命令行编辑启动参数
    //   2. 认证检查（normal/auth.c:242）：
    //      - 如果 CLI 被禁用，直接拒绝访问命令行（返回 GRUB_ACCESS_DENIED）
    //   3. Rescue 模式（kern/rescue_reader.c:82）：
    //      - 如果 CLI 被禁用，阻止进入 rescue 模式的命令行
    // 实际场景：
    //   - 企业环境：管理员可能禁用 CLI，强制用户只能选择预定义的启动项
    //   - 安全启动：配合 Secure Boot，防止恶意修改启动参数
    //   - 嵌入式系统：某些嵌入式设备可能不需要交互式命令行
    // 源代码位置：grub/grub-core/kern/main.c:263-276

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
    //   - 注册 GRUB 内核中的核心命令（仅 4 个基础命令）
    //   - 这些命令内置在 GRUB 内核中，无需加载模块即可使用
    //   - 详细说明见下方 "grub_register_core_commands() 函数详解"

    grub_boot_time ("Before execution of embedded config.");

    // 步骤 13: 执行嵌入的配置文件（如果存在）
    if (load_config)
        grub_parser_execute (load_config);
    // 功能：
    //   - 解析并执行嵌入的 grub.cfg 配置文件
    //   - 遇到 menuentry 时只注册条目（脚本体存到 entry->sourcecode，不执行脚本体）
    //   - linux 命令在用户选择该菜单项后、执行该条目脚本体时才会被调用（grub_menu_execute_entry）
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

**源代码位置：** `grub/grub-core/kern/main.c:58-75`

**功能：**
- 遍历 `core.img` 中的所有嵌入模块（OBJ_TYPE_ELF 类型）
- 使用 `grub_dl_load_core()` 从内存加载每个模块
- 模块包括：文件系统驱动、磁盘驱动、加载器（linux.mod）、命令等

**⚠️ 关键区别：两种模块加载方式**

| 特性 | grub_load_modules() | insmod 命令 |
|------|---------------------|-------------|
| **加载时机** | 启动时自动加载 | 运行时按需加载 |
| **模块位置** | 嵌入在 core.img 中 | 文件系统中的 .mod 文件 |
| **加载方式** | 从内存加载（grub_dl_load_core） | 从文件系统加载（grub_dl_load_file） |
| **配置方式** | grub-mkimage [选项] ext2 linux ... | grub.cfg 中 insmod linux |
| **典型用途** | 启动必需的基础模块 | 可选的扩展模块 |

**完整源代码：**

```c
// grub/grub-core/kern/main.c:58-75
static void
grub_load_modules (void)
{
  struct grub_module_header *header;
  FOR_MODULES (header)  // 遍历 core.img 中的所有模块
  {
    if (header->type != OBJ_TYPE_ELF)
      continue;

    // 加载所有 ELF 格式的模块
    if (! grub_dl_load_core (
          (char *) header + sizeof (struct grub_module_header),
          (header->size - sizeof (struct grub_module_header))))
      grub_fatal ("%s", grub_errmsg);
  }
}
```

**关键点：**
- `FOR_MODULES` 宏遍历 core.img 中嵌入的所有模块
- 只加载 `OBJ_TYPE_ELF` 类型的模块（ELF 格式的可执行模块）
- 使用 `grub_dl_load_core()` 从内存加载模块（不是从文件系统）

**linux.mod 模块的加载：**

`linux` 命令是由 `linux.mod` 模块提供的，该模块可以通过两种方式加载：

1. **嵌入方式**（推荐）：
   - 构建时：`grub-mkimage [选项] linux ...`
   - 启动时：`grub_load_modules()` 自动加载
   - 无需 grub.cfg 中的 `insmod linux`

2. **动态加载方式**：
   - grub.cfg 中：`insmod linux`
   - 从 `/boot/grub/i386-pc/linux.mod` 加载
   - 适用于 linux.mod 未嵌入的情况

**判断方法：**
- 如果 grub.cfg 中**没有** `insmod linux`，说明 linux.mod 已嵌入到 core.img
- 如果 grub.cfg 中**有** `insmod linux`，说明需要从文件系统动态加载

**典型嵌入模块列表：**

- **i386-pc 平台**：ext2, part_msdos, biosdisk, normal, linux, search, ls
- **x86_64-efi 平台**：ext2, part_gpt, efi_gop, normal, linux, search, ls

**模块分类参考**：详见本文档附录"GRUB 核心模块分类"

**详细分析**：关于 FOR_MODULES 宏的工作原理、模块数据结构、内存布局等，请参见 [GRUB_MODULE_LOADING_ANALYSIS.md](GRUB_MODULE_LOADING_ANALYSIS.md)

---

**3.1 `grub_dl_load_core()` - 模块加载核心函数**

**源代码位置：** `grub/grub-core/kern/dl.c:805-821`

**功能：**
- 解析 ELF 格式的模块文件
- 执行符号解析和重定位
- 调用模块初始化函数（`grub_mod_init`）
- 将模块添加到已加载模块链表

**完整源代码：**

```c
// grub/grub-core/kern/dl.c:805-821
grub_dl_t
grub_dl_load_core (void *addr, grub_size_t size)
{
    grub_dl_t mod;

    // 步骤 1: 解析 ELF 文件，但不初始化
    mod = grub_dl_load_core_noinit (addr, size);
    if (! mod)
        return 0;

    // 步骤 2: 调用模块初始化函数
    grub_dl_init (mod);  // ⚠️ 关键：这里调用 mod->init

    return mod;
}
```

**符号解析（查找初始化函数）：**

```c
// grub/grub-core/kern/dl.c:437-440
// 在解析 ELF 符号表时，查找特殊函数名
if (grub_strcmp (name, "grub_mod_init") == 0)
    mod->init = (void (*) (grub_dl_t)) sym->st_value;  // 保存初始化函数地址
else if (grub_strcmp (name, "grub_mod_fini") == 0)
    mod->fini = (void (*) (void)) sym->st_value;       // 保存清理函数地址
```

**模块初始化（调用 grub_mod_init）：**

```c
// grub/include/grub/dl.h:224-231
static inline void
grub_dl_init (grub_dl_t mod)
{
    if (mod->init)
        (mod->init) (mod);  // ⚠️ 调用 grub_mod_init()，注册命令

    mod->next = grub_dl_head;  // 添加到已加载模块链表
    grub_dl_head = mod;
}
```

**为何可知这里调用的是 `grub_mod_init`（分析依据）：**

1. **`mod->init` 的赋值来源**  
   在 `grub_dl_load_core_noinit()` 里会做 ELF 符号解析（`grub/grub-core/kern/dl.c` 中，通常在 `grub_dl_resolve_symbols()` 或遍历符号表的逻辑里）。当解析到符号名为 `"grub_mod_init"` 时，会把该符号的值（函数地址）赋给 `mod->init`，例如：
   `if (grub_strcmp (name, "grub_mod_init") == 0) mod->init = (void (*) (grub_dl_t)) sym->st_value;`  
   因此 **`mod->init` 指向的，就是该模块 ELF 里导出的名为 `grub_mod_init` 的函数的地址**。

2. **模块里谁叫 `grub_mod_init`**  
   各模块用宏 `GRUB_MOD_INIT(name)` 定义自己的初始化函数（`grub/include/grub/dl.h`）。该宏展开后定义的函数名固定为 `grub_mod_init`（宏参数 `name` 只用于别处，不改变此函数名）。因此每个 `.mod` 的 ELF 中都会有一个符号 `grub_mod_init`，对应本模块的初始化函数。

3. **结论**  
   `grub_dl_init(mod)` 里执行 `(mod->init)(mod)` 时，调用的就是上一步赋给 `mod->init` 的地址；该地址来自当前加载模块的 `grub_mod_init` 符号，故 **这里调用的就是该模块的 `grub_mod_init(mod)`**。  
   追踪路径：`(mod->init)(mod)` → `mod->init` 在符号解析时被设为模块的 `grub_mod_init` 地址 → 故调用的是 `grub_mod_init`。

**linux.mod 模块注册示例：**

```c
// grub/grub-core/loader/i386/linux.c:1171-1178
GRUB_MOD_INIT(linux)
{
    cmd_linux = grub_register_command ("linux", grub_cmd_linux, ...);
    cmd_initrd = grub_register_command ("initrd", grub_cmd_initrd, ...);
}
```

**完整调用链（insmod linux 命令）：**

```
insmod linux
    ↓
grub_core_cmd_insmod("linux")
    ↓
grub_dl_load("linux")           [kern/dl.c:874]
    ↓
grub_dl_load_file("/boot/grub/i386-pc/linux.mod")
    ↓
grub_dl_load_core(addr, size)   [kern/dl.c:805]
    ├─ grub_dl_load_core_noinit()
    │   ├─ 解析 ELF 头部
    │   ├─ grub_dl_resolve_symbols()
    │   │   └─ 找到 "grub_mod_init" 符号 → mod->init = 函数地址
    │   └─ 重定位符号
    │
    └─ grub_dl_init(mod)        [dl.h:224]
        └─ (mod->init)(mod)     // 调用 grub_mod_init()
            ↓
grub_mod_init(mod)              [linux.c:1171-1178]
    ├─ grub_register_command("linux", grub_cmd_linux, ...)
    └─ grub_register_command("initrd", grub_cmd_initrd, ...)
            ↓
命令 "linux" 和 "initrd" 被添加到 grub_command_list
```

**关键机制：**
- **ELF 符号表**：模块是 ELF 格式文件，包含符号表
- **约定的函数名**：GRUB 通过查找固定的函数名 `grub_mod_init` 和 `grub_mod_fini` 来识别初始化/清理函数
- **自动调用**：模块加载完成后，自动调用初始化函数，初始化函数内部调用 `grub_register_command()` **仅注册**命令（把命令名与处理函数登记到命令表），**不执行** `grub_cmd_linux`；`grub_cmd_linux` 在用户选择菜单项后、执行该条目脚本体并遇到 `linux` 命令时，才由解析器通过 `grub_command_find("linux")` 查表并调用

**`GRUB_MOD_INIT(name)` 宏展开：**

```c
// grub/include/grub/dl.h:43-46
// 动态加载模块时（insmod）：
#define GRUB_MOD_INIT(name)  \
static void grub_mod_init (grub_dl_t mod __attribute__ ((unused)))
                ↑
        参数 name 被忽略！生成的函数名始终是 grub_mod_init
```

不同模块展开后都生成同名函数（但在不同的 .mod 文件中）：

```c
// linux.mod 中：
GRUB_MOD_INIT(linux) { ... }
// 展开后 → static void grub_mod_init(grub_dl_t mod) { ... }

// ext2.mod 中：
GRUB_MOD_INIT(ext2) { ... }
// 展开后 → static void grub_mod_init(grub_dl_t mod) { ... }
```

---

**4. `grub_register_core_commands()` - 注册核心命令**

**源代码位置：** `grub/grub-core/kern/corecmd.c:177-192`

**功能：**
- 注册 GRUB 内核中的 4 个核心命令
- 这些命令内置在 GRUB 内核中，无需加载模块即可使用

**完整源代码：**

```c
// grub/grub-core/kern/corecmd.c:177-192
void
grub_register_core_commands (void)
{
    grub_command_t cmd;
    
    // 1. set 命令：设置环境变量
    cmd = grub_register_command ("set", grub_core_cmd_set,
                                 N_("[ENVVAR=VALUE]"),
                                 N_("Set an environment variable."));
    if (cmd)
        cmd->flags |= GRUB_COMMAND_FLAG_EXTRACTOR;
    
    // 2. unset 命令：删除环境变量
    grub_register_command ("unset", grub_core_cmd_unset,
                           N_("ENVVAR"),
                           N_("Remove an environment variable."));
    
    // 3. ls 命令：列出设备或文件
    grub_register_command ("ls", grub_core_cmd_ls,
                           N_("[ARG]"), N_("List devices or files."));
    
    // 4. insmod 命令：加载模块
    grub_register_command ("insmod", grub_core_cmd_insmod,
                           N_("MODULE"), N_("Insert a module."));
}
```

**核心命令详解：**

| 命令 | 功能 | 使用示例 |
|------|------|----------|
| `set` | 设置/显示环境变量 | `set root=(hd0,1)` 或 `set`（显示所有） |
| `unset` | 删除环境变量 | `unset timeout` |
| `ls` | 列出设备或目录内容 | `ls` 或 `ls (hd0,1)/boot/` |
| `insmod` | 加载 GRUB 模块 | `insmod linux` 或 `insmod /boot/grub/i386-pc/ext2.mod` |

**各命令实现分析：**

**`set` 命令（`grub_core_cmd_set`）：**

```c
// grub/grub-core/kern/corecmd.c:32-60
static grub_err_t
grub_core_cmd_set (struct grub_command *cmd, int argc, char *argv[])
{
    // 无参数时：显示所有环境变量
    if (argc < 1)
    {
        struct grub_env_var *env;
        FOR_SORTED_ENV (env)
        {
            val = (char *) grub_env_get (env->name);
            grub_printf ("%s='%s'\n", env->name, val == NULL ? "" : val);
        }
        return 0;
    }

    // 有参数时：解析 ENVVAR=VALUE 并设置
    var = argv[0];
    val = grub_strchr (var, '=');
    if (! val)
        return grub_error (GRUB_ERR_BAD_ARGUMENT, "not an assignment");

    val[0] = 0;                    // 临时截断字符串
    grub_env_set (var, val + 1);   // 设置环境变量
    val[0] = '=';                  // 恢复字符串
    return 0;
}
```

**`ls` 命令（`grub_core_cmd_ls`）：**

```c
// grub/grub-core/kern/corecmd.c:114-174
static grub_err_t
grub_core_cmd_ls (struct grub_command *cmd, int argc, char *argv[])
{
    // 无参数时：列出所有设备
    if (argc < 1)
    {
        grub_device_iterate (grub_mini_print_devices, NULL);
        // 输出示例：(hd0) (hd0,msdos1) (hd0,msdos2) (cd0)
        return 0;
    }
    
    // 有参数时：列出指定路径
    device_name = grub_file_get_device_name (argv[0]);
    dev = grub_device_open (device_name);
    fs = grub_fs_probe (dev);      // 探测文件系统类型
    
    // 只指定设备时：显示文件系统类型
    // 示例：ls (hd0,1) → "(hd0,msdos1): Filesystem is ext2."
    if (! *path)
    {
        grub_printf ("(%s): Filesystem is %s.\n", device_name, fs->name);
    }
    // 指定路径时：列出目录内容
    // 示例：ls (hd0,1)/boot/ → "vmlinuz initrd.img grub/"
    else if (fs)
    {
        (fs->fs_dir) (dev, path, grub_mini_print_files, NULL);
    }
}
```

**`insmod` 命令（`grub_core_cmd_insmod`）：**

```c
// grub/grub-core/kern/corecmd.c:75-93
static grub_err_t
grub_core_cmd_insmod (struct grub_command *cmd, int argc, char *argv[])
{
    grub_dl_t mod;

    // 判断是路径还是模块名
    if (argv[0][0] == '/' || argv[0][0] == '(' || argv[0][0] == '+')
        // 路径格式：insmod /boot/grub/i386-pc/ext2.mod
        mod = grub_dl_load_file (argv[0]);
    else
        // 模块名格式：insmod linux（自动查找 $prefix/i386-pc/linux.mod）
        mod = grub_dl_load (argv[0]);

    if (mod)
        grub_dl_ref (mod);  // 增加引用计数，防止模块被卸载

    return 0;
}
```

**核心命令 vs 模块命令：**

| 类型 | 注册位置 | 示例 | 特点 |
|------|----------|------|------|
| 核心命令 | `grub_register_core_commands()` | `set`, `ls`, `insmod`, `unset` | 内置于 GRUB 内核，始终可用 |
| 模块命令 | 各模块的 `GRUB_MOD_INIT()` | `linux`, `initrd`, `boot`, `search` | 需要加载模块后才能使用 |
| | | | ⚠️ `linux` 命令由 `linux.mod` 提供（/boot/grub/i386-pc/linux.mod） |
| | | | ⚠️ `linux.mod` 可以嵌入到 core.img 中，也可以作为独立文件 |

**模块加载与命令注册机制：**

当执行 `insmod linux` 时，GRUB 如何知道该模块提供了哪些命令？

**关键机制：**

1. **模块初始化宏**：每个模块通过 `GRUB_MOD_INIT(name)` 宏定义初始化函数 `grub_mod_init()`
2. **自动调用**：`grub_dl_load_core()` 加载模块后，自动调用其 `grub_mod_init()` 函数
3. **命令注册**：初始化函数内部调用 `grub_register_command()` 注册命令

**示例（linux.mod）：**

```c
// grub/grub-core/loader/i386/linux.c:1171-1178
GRUB_MOD_INIT(linux)
{
    cmd_linux = grub_register_command ("linux", grub_cmd_linux, ...);
    cmd_initrd = grub_register_command ("initrd", grub_cmd_initrd, ...);
}
```

**完整调用链（insmod linux）：**

```
insmod linux
    ↓
grub_core_cmd_insmod("linux")
    ↓
grub_dl_load_file("/boot/grub/i386-pc/linux.mod")
    ↓
grub_dl_load_core(addr, size)
    └─ grub_dl_init(mod)
        └─ (mod->init)(mod)  // 调用 grub_mod_init()
            ↓
grub_mod_init(mod)
    ├─ grub_register_command("linux", grub_cmd_linux, ...)
    └─ grub_register_command("initrd", grub_cmd_initrd, ...)
```

> **详细说明**：关于 `grub_dl_load_core()` 的详细实现、ELF 符号解析、模块初始化流程等，请参见上方"核心函数详解 > grub_dl_load_core()"
```

**没有 `GRUB_MOD_INIT` 的库模块：**

某些模块（如 `extcmd.mod`）只提供函数供其他模块调用，不需要注册命令：

```c
// grub/include/grub/dl.h:224-231
static inline void
grub_dl_init (grub_dl_t mod)
{
    if (mod->init)          // ← 检查是否有初始化函数
        (mod->init) (mod);  // 有才调用，没有则跳过
    
    mod->next = grub_dl_head;   // 无论有没有 init，都添加到模块链表
    grub_dl_head = mod;
}
```

| 模块类型 | `mod->init` | 加载时行为 | 功能提供方式 |
|----------|-------------|------------|--------------|
| 有 `GRUB_MOD_INIT` | 函数地址 | 调用 init 注册命令/FS | 主动注册 |
| 无 `GRUB_MOD_INIT` | NULL | 跳过 init 调用 | 导出函数供其他模块调用 |

**库模块示例（extcmd.mod）：**

```c
// extcmd.mod 没有 GRUB_MOD_INIT，但导出了这些函数：
grub_extcmd_t grub_register_extcmd (...);
void grub_unregister_extcmd (...);

// 其他模块（如 search.mod）加载后可以调用：
GRUB_MOD_INIT(search)
{
    // 调用 extcmd.mod 导出的函数
    cmd = grub_register_extcmd ("search", grub_cmd_search, ...);
}
```

**命令注册机制（`grub_register_command`）：**

```c
// grub/include/grub/command.h:96-103
static inline grub_command_t
grub_register_command (const char *name,
                       grub_command_func_t func,
                       const char *summary,
                       const char *description)
{
    return grub_register_command_prio (name, func, summary, description, 0);
}
```

注册的命令被添加到全局链表 `grub_command_list`。**`grub_register_command` 仅做登记**：把命令名与处理函数（如 `grub_cmd_linux`）挂到命令表，**不会在此处执行**该处理函数。真正执行发生在脚本/解析器执行到该命令时：通过 `grub_command_find("linux")` 查表得到 `cmd`，再调用 `(cmd->func)(cmd, argc, argv)`，即 `grub_cmd_linux()`。

**5. `grub_parser_execute()` - 执行配置文件**

**功能：**
- 解析并执行 `grub.cfg` 配置文件
- **关键**：当遇到 `linux` 命令时，会调用 `grub_cmd_linux()` 加载内核
- **⚠️ 处理 `insmod` 命令**：当遇到 `insmod` 命令时，会调用 `grub_core_cmd_insmod()` 加载动态模块

**配置示例：**

**示例 1：从硬盘启动（实际系统）**

```bash
# /boot/grub/grub.cfg
menuentry "Linux 5.x.x" {
    linux /boot/vmlinuz-5.x.x root=/dev/sda1 ro quiet
    initrd /boot/initrd.img-5.x.x
}

# 用户按 Enter 选择 "Linux 5.x.x" 后，GRUB 执行 menuentry 中的命令：
# 1. 执行 linux 命令 → 调用 grub_cmd_linux()
#    - 加载内核到临时缓冲区（通常在 16MB+），boot 时复制到 0x100000 (1MB)
#    - 注册 grub_linux_boot() 作为启动函数
# 2. 执行 initrd 命令 → 调用 grub_cmd_initrd()
#    - 加载 initramfs 到高地址
# 3. menuentry 执行完毕后，GRUB 隐式调用 boot 命令
#    - 调用 grub_linux_boot() → grub_relocator32_boot()
#    - 跳转到内核入口点（code32_start）
```

**示例 2：从 ISO 启动（测试环境，如 create_grub_iso_with_kernel.sh 生成的配置）**

```bash
# iso/boot/grub/grub.cfg
set root='cd0'  # 设置根设备为 CD-ROM

# 加载必要的模块以支持 ISO 文件系统
insmod iso9660
insmod part_msdos
insmod part_gpt
insmod loopback

# ⚠️ 注意：如果 linux.mod 没有嵌入到 core.img 中，需要添加：
# insmod linux

menuentry "Linux Kernel (Debian Installer)" {
    set root='cd0'
    linux /boot/vmlinuz root=/dev/ram0 rw console=ttyS0,115200
    initrd /boot/initrd.img
}
# 说明：
# - console=ttyS0,115200 用于串口输出（QEMU 中可用 -serial stdio 查看）
# - 脚本下载的 "linux" 保存为 "vmlinuz"，"initrd.gz" 保存为 "initrd.img"
# - GRUB 可以自动处理压缩的 initrd 文件（gzip 格式）
# - 如果 grub.cfg 中没有 insmod linux，说明 linux.mod 已嵌入到 core.img 中
# - 如果 grub.cfg 中有 insmod linux，说明 linux.mod 没有嵌入，需要从文件系统加载
```

> **相关文档**：
> - 关于 `create_grub_iso_with_kernel.sh` 脚本的使用和文件命名说明，请参见 [CREATE_GRUB_ISO.md](CREATE_GRUB_ISO.md)
> - 关于 vmlinuz 和 initrd 的详细关系，请参见 [vmlinuz 和 initrd 的关系详解](VMLINUZ_INITRD_RELATIONSHIP.md)

**配置说明：**

- **硬盘启动**：`root=/dev/sda1` 表示从第一个 SATA 硬盘的第一个分区启动
- **ISO 启动**：`root=/dev/ram0` 表示使用 RAM 作为根文件系统（适用于从 ISO 或网络启动）
- **内核参数**：
  - `ro`：只读模式挂载根文件系统（启动后通常会重新挂载为读写）
  - `rw`：读写模式挂载
  - `quiet`：静默启动（减少输出）
  - `console=ttyS0,115200`：设置串口控制台（用于调试和查看启动日志）

**5. `grub_load_normal_mode()` - 加载 normal 模式**

**功能：**
- 尝试加载 `normal.mod` 模块（如果存在）
- normal 模式提供菜单显示、用户交互等功能

> **详细说明**：关于 `grub_main()` 中其他初始化函数的详细实现，请参见 [GRUB 架构设计与初始化详解](GRUB_ARCHITECTURE_AND_INIT.md)。

### grub_parser_execute() 函数

**源代码位置：** `grub/grub-core/kern/parser.c:330-344`

**功能：** 逐行解析并执行**嵌入 core 的 config 字符串**（`load_config`，来自 OBJ_TYPE_CONFIG 模块）。**注意**：磁盘上的主 `grub.cfg` 不是由此函数执行，而是由 normal 模式的 `read_config_file()` → `grub_normal_parse_line()`（脚本解析器）执行，见上文「从 grub_main 到 grub_cmd_menuentry 的调用链」。

**源代码分析：**

```c
// grub/grub-core/kern/parser.c
grub_err_t
grub_parser_execute (char *source)
{
    while (source)
    {
        char *line;
        
        // 获取下一行（遇到 \n 分割）
        grub_parser_execute_getline (&line, 0, &source);
        
        // 解析并执行该行命令
        grub_rescue_parse_line (line, grub_parser_execute_getline, &source);
        
        grub_free (line);
        grub_print_error ();
    }
    return grub_errno;
}
```

**`grub_rescue_parse_line()` 实现（`grub-core/kern/rescue_parser.c:28-90`）：**

```c
grub_err_t
grub_rescue_parse_line (char *line, grub_reader_getline_t getline, void *data)
{
    char *name;
    int n;
    grub_command_t cmd;
    char **args;
    
    // 步骤 1: 分割命令行为参数数组（处理引号、变量展开等）
    grub_parser_split_cmdline (line, getline, data, &n, &args);
    
    // 步骤 2: 处理赋值语句（如 set root='hd0,1'）
    if (n == 1) {
        char *val = grub_strchr (args[0], '=');
        if (val) {
            val[0] = 0;
            grub_env_set (args[0], val + 1);  // 设置环境变量
            return;
        }
    }
    
    // 步骤 3: 查找并执行命令
    name = args[0];  // 命令名（如 "linux", "menuentry", "set"）
    cmd = grub_command_find (name);  // 从命令表中查找
    
    if (cmd) {
        // ⚠️ 关键：调用命令的处理函数
        // 例如：linux 命令 → grub_cmd_linux()
        //       menuentry 命令 → grub_cmd_menuentry()（只注册，不执行内部命令）
        (cmd->func) (cmd, n - 1, &args[1]);
    } else {
        grub_printf ("Unknown command `%s'.\n", name);
    }
    
    grub_free (args);
    return grub_errno;
}
```

**执行流程（仅针对嵌入 config）**：`grub_parser_execute(load_config)` 用 rescue 解析器逐行执行 `load_config`；若某行为 `menuentry ... { ... }`，则 `grub_rescue_parse_line` → `grub_command_find("menuentry")` → `(cmd->func)(...)` = `grub_extcmd_dispatch` → `grub_cmd_menuentry`，仅注册条目、不执行脚本体。用户按 Enter 选择某条后，由 `grub_menu_execute_entry(entry)` 执行 `entry->sourcecode`，此时才执行到 `linux`/`initrd` 等，见上文「从 grub_main 到 grub_cmd_menuentry 的调用链」。

**⚠️ `insmod` 命令的处理时机：**

1. **在 `menuentry` 外的 `insmod` 命令**：
   - 解析 config 时**立即执行**（嵌入 config 由 `grub_parser_execute(load_config)`；磁盘 grub.cfg 由 `read_config_file` → `grub_normal_parse_line` 逐行执行）
   - 例如：config 顶部的 `insmod gfxterm` 会在显示菜单前加载模块

2. **在 `menuentry` 内的 `insmod` 命令**：
   - 解析时**不执行**（只把该条目的脚本体存到 `entry->sourcecode`）
   - 用户选择该 menuentry 并按 Enter 后，执行 `entry->sourcecode` 时**才执行**
   - 例如：`menuentry "Linux" { insmod linux; linux /vmlinuz }` 中的 `insmod linux` 只在用户选择该菜单项时执行

3. **`insmod` 命令的处理函数**：
   - **源代码位置**：`grub/grub-core/kern/corecmd.c:76-93`
   - 调用 `grub_dl_load()` 或 `grub_dl_load_file()` 从文件系统加载模块
   - 加载的模块会注册其提供的命令（如 `linux` 命令由 `linux.mod` 提供）

**关键点：**

1. **配置文件解析时机**：
   - 嵌入 config：`grub_main()` → `grub_parser_execute(load_config)`（kern/main.c:364）
   - 磁盘 grub.cfg：`grub_main()` → `grub_load_normal_mode()` → … → `read_config_file(config)` → `grub_normal_parse_line` 逐行（见上文「从 grub_main 到 grub_cmd_menuentry 的调用链」）
   - 解析时：**menuentry 外的命令**（如 `insmod gfxterm`）**立即执行**；**menuentry 内的命令**（如 `linux`）**只随脚本体存入 entry，不执行**
   - 用户选择某条并按 Enter 后，才执行该条目的脚本体（`grub_menu_execute_entry` → `grub_script_execute_new_scope(entry->sourcecode)`）

2. **`insmod` 命令的处理步骤**：
   - 解析到 `insmod` 行时：当前解析器（rescue 或 script）→ `grub_command_find("insmod")` → 对应 insmod 命令处理函数 → `grub_dl_load()`/`grub_dl_load_file()` 加载模块，模块的 `grub_mod_init()` 注册其命令

2. **menuentry 执行流程**：
   - 用户按 Enter 后，执行 `linux` 命令 → `grub_cmd_linux()` 加载内核到临时缓冲区（通常在 16MB+）
   - 执行 `initrd` 命令 → `grub_cmd_initrd()` 加载 initramfs
   - menuentry 执行完毕后，GRUB 隐式调用 boot 命令
   - boot 命令调用 `grub_linux_boot()` → `grub_relocator32_boot()` 跳转到内核

3. **内存布局与 Relocator 机制**：
   - GRUB 解压后也在 0x100000 (1MB)，与内核目标地址相同
   - 内核**先被加载到 relocator 管理的临时缓冲区 (src)**（通常在 0x1000000 (16MB) = 16MB 以上）
   - `boot` 命令执行时：
     - 构建 relocator 代码：**movers_chunk**（复制代码 + jumper）在 1MB 之上的另一块分配（如 16MB+），**安全区** (0x1000-0x9a000) 存放 relocator32 副本
     - 将 relocator32.S 副本复制到**安全区**（0x1000-0x9a000）
     - 跳转到 movers_chunk 执行：
       1. movers_chunk 将内核从临时缓冲区 (src, 16MB+) 复制到 **0x100000 (1MB) (target)**（movers_chunk 与 0x100000 为不同区域，复制不覆盖 movers_chunk）
       2. jumper 跳到安全区；安全区 relocator32 切换到实模式并 ljmp 到内核入口点（code32_start @ 0x100000 (1MB)）
   - 此时 GRUB 代码被覆盖，但已不需要

**Relocator 概要**：内核先加载到 relocator 管理的临时缓冲区 (src，通常 16MB 以上)，boot 时由 **movers_chunk**（在 1MB 之上单独分配，与 0x100000 为不同块）内的复制代码从 src 复制到 0x100000 (1MB) (target)，再 jumper 到安全区、relocator32 跳入内核。数据结构、分配逻辑、为何 0x100000 (1MB) 分配失败、内存布局等详见 [GRUB_RELOCATOR.md](GRUB_RELOCATOR.md)。

### grub_cmd_linux() 函数

**源代码位置：** `grub/grub-core/loader/i386/linux.c:680-725`

**功能：**
- 打开内核文件（如 `/boot/vmlinuz-5.x.x`）
- 解析内核头部，验证内核签名
- 通过 relocator 分配临时缓冲区（通常在 16MB 以上），加载内核到临时位置
- 设置内核启动参数（`boot_params`）
- 注册启动函数 `grub_linux_boot()`（boot 时将内核从临时位置复制到 0x100000 (1MB)）

**内核镜像结构概述：**

Linux 内核镜像（bzImage/vmlinuz）包含两部分：

1. **Setup 代码**（实模式代码）：
   - 大小：通常 4-64 个扇区（由 `setup_sects` 字段指定）
   - 功能：切换到保护模式/长模式，解压内核
   - 源代码：`linux/arch/x86/boot/header.S`

2. **压缩的内核代码**：
   - 位置：setup 代码之后
   - 格式：gzip 压缩的 vmlinux
   - 加载地址：`0x100000 (1MB)`（1MB）或内核指定的地址

**完整源代码分析：**

```c
// grub/grub-core/loader/i386/linux.c（精简示意，与源码一致）
grub_cmd_linux (grub_command_t cmd, int argc, char *argv[])
{
    // 步骤 1: 打开内核文件（如 /boot/vmlinuz-5.x.x）
    file = grub_file_open (argv[0], GRUB_FILE_TYPE_LINUX_KERNEL);
    
    // 步骤 2: 只读内核头部到 lh（无“整文件”缓冲区）
    // 源码：grub_file_read (file, &lh, sizeof (lh))
    if (grub_file_read (file, &lh, sizeof (lh)) != sizeof (lh))
        goto fail;
    
    // 步骤 3: 验证内核签名与版本（boot_flag、header、setup_sects、loadflags 等）
    if (lh.boot_flag != grub_cpu_to_le16 (0xAA55)) ...
    if (lh.header != grub_cpu_to_le32 (0x53726448)) ...  // "HdrS"
    
    // 步骤 4: 计算 setup 与“保护模式”部分大小
    real_size = setup_sects << GRUB_DISK_SECTOR_BITS;
    prot_file_size = grub_file_size (file) - real_size - GRUB_DISK_SECTOR_SIZE;
    
    // 步骤 5: 计算加载地址与对齐（preferred_address、align、min_align、relocatable）
    preferred_address = GRUB_LINUX_BZIMAGE_ADDR;  // 0x100000 (1MB)
    if (relocatable)
        preferred_address = grub_le_to_cpu64 (lh.pref_address);
    
    // 步骤 6: 通过 relocator 分配临时缓冲区（非最终 0x100000）
    allocate_pages (prot_size, &align, min_align, relocatable, preferred_address);
    // 说明：此处 "pages" 指分配的内存块/区域，非 MMU 的页。
    // 得到 prot_mode_mem（写入用，常为 16MB+）、prot_mode_target（最终 0x100000）。
    
    // 步骤 7: 将 setup 头扩展区读入 linux_params（boot_params）
    len = 0x202 + *((char *) &lh.jump + 1);
    grub_memcpy (&linux_params.hdr.setup_sects, &lh.setup_sects, len - 0x1F1);
    len -= sizeof (lh);
    if (len > 0)
        grub_file_read (file, (char *) &linux_params + sizeof (lh), len);
    
    // 步骤 8: 设置 boot_params 中 code32_start、type_of_loader、ramdisk 等
    linux_params.hdr.code32_start = prot_mode_target + lh.code32_start - GRUB_LINUX_BZIMAGE_ADDR;
    // ...
    
    // 步骤 9: 将“保护模式”部分一次性从文件读入临时缓冲区（源码无 kernel 缓冲、无两次 memcpy）
    grub_file_seek (file, real_size + GRUB_DISK_SECTOR_SIZE);
    len = prot_file_size;
    if (grub_file_read (file, prot_mode_mem, len) != len)
        ...
    
    // 步骤 10: 注册启动函数（实际跳转在 boot 时由 grub_linux_boot() 执行）
    grub_loader_set (grub_linux_boot, grub_linux_unload, 0);
}
```

### grub_cmd_initrd() 函数

**源代码位置：** `grub/grub-core/loader/i386/linux.c:1065-1166`

**功能：**
- 读取 initrd/initramfs 文件（支持多个文件，GRUB 会合并）
- 分配内存（尽量放在高地址区域，4KB 对齐）
- 加载 initrd 到内存
- 设置 `boot_params` 中的 `ramdisk_image` 和 `ramdisk_size`

**前置条件：**
- 必须先执行 `linux` 命令加载内核（`grub_cmd_linux()`）
- 如果未加载内核，会返回错误：`"you need to load the kernel first"`

**grub_cmd_initrd 如何得知内核占用与 initrd 起始地址：**

`grub_cmd_initrd` 不调用 `allocate_pages()`，也不单独申请“一整块”内存；它复用 `grub_cmd_linux()` 在同一文件内建立的**静态变量**和**同一个 relocator**：

| 来源 | 含义 |
|------|------|
| `loaded` | 由 `grub_cmd_linux()` 置 1；initrd 用 `if (! loaded)` 判断是否已加载内核，未加载则报错 `"you need to load the kernel first"`。 |
| `prot_mode_target` | 由 `grub_cmd_linux()` 在 `allocate_pages()` 里通过 relocator 得到，即内核临时缓冲区的**物理起始地址**（通常为 0x100000 或 16MB+）。 |
| `prot_init_space` | 由 `grub_cmd_linux()` 在解析内核头后计算并写入：对 2.10+ 内核用 `lh.init_size` 做页对齐，否则用 `prot_size`（或约 3 倍）做页对齐；表示内核占用的**长度**（字节）。 |
| `relocator` | 由 `grub_cmd_linux()` 在 `allocate_pages()` 里创建并保留；initrd 用**同一个** `relocator` 再调用 `grub_relocator_alloc_chunk_align(relocator, &ch, addr_min, addr, ...)` 分配一块新区间，与内核块不重叠。 |

因此：

1. **内核占用了多少内存**：initrd 不自己算，直接读已存在的静态变量 **`prot_init_space`**（由 linux 命令在分配时填好）。
2. **initrd 加载的起始位置**：**`addr_min = prot_mode_target + prot_init_space`**，即“内核临时缓冲区”的物理结束地址；initrd 必须放在该地址之后。再结合 `addr_max`（来自 `linux_params.hdr.initrd_addr_max` 或默认上限）得到允许区间 `[addr_min, addr_max]`，在区间内按“尽量高地址”选 `addr`，再用同一个 relocator 在该区间分配一块给 initrd。

**完整源代码分析：**

```c
// grub/grub-core/loader/i386/linux.c:1065-1166
static grub_err_t
grub_cmd_initrd (grub_command_t cmd, int argc, char *argv[])
{
    grub_size_t size = 0, aligned_size = 0;
    grub_addr_t addr_min, addr_max;
    grub_addr_t addr;
    struct grub_linux_initrd_context initrd_ctx = { 0, 0, 0 };

    // 步骤 1: 检查参数
    if (argc == 0)
    {
        grub_error (GRUB_ERR_BAD_ARGUMENT, N_("filename expected"));
        goto fail;
    }

    // 步骤 2: 检查内核是否已加载
    if (! loaded)
    {
        grub_error (GRUB_ERR_BAD_ARGUMENT, 
                    N_("you need to load the kernel first"));
        goto fail;
    }

    // 步骤 3: 初始化 initrd 上下文（支持多个文件）
    // grub_initrd_init 会打开所有指定的 initrd 文件
    // 支持多个文件（GRUB 会将它们合并成一个 initramfs）
    if (grub_initrd_init (argc, argv, &initrd_ctx))
        goto fail;

    // 步骤 4: 计算 initrd 总大小
    size = grub_get_initrd_size (&initrd_ctx);
    aligned_size = ALIGN_UP (size, 4096);  // 4KB 对齐

    // 步骤 5: 确定 initrd 的最大地址
    // 从内核头部读取 initrd_addr_max 字段
    if (grub_le_to_cpu16 (linux_params.hdr.version) >= 0x0203)
    {
        addr_max = grub_cpu_to_le32 (linux_params.hdr.initrd_addr_max);
        // Linux 的 initrd_addr_max 有时会设置为一个过大的值
        // 需要限制在 0x3fffffff（约 1GB）以内
        if (addr_max > GRUB_LINUX_INITRD_MAX_ADDRESS)
            addr_max = GRUB_LINUX_INITRD_MAX_ADDRESS;
    }
    else
        addr_max = GRUB_LINUX_INITRD_MAX_ADDRESS;

    // 步骤 6: 考虑用户指定的内存限制
    if (linux_mem_size != 0 && linux_mem_size < addr_max)
        addr_max = linux_mem_size;

    // 步骤 7: 避免 Linux 2.2/2.3 的内存范围检查 bug
    addr_max -= 0x10000;  // 减去 64KB

    // 步骤 8: 计算最小地址（内核加载位置之后）
    addr_min = (grub_addr_t) prot_mode_target + prot_init_space;

    // 步骤 9: 计算 initrd 加载地址（尽量放在高地址）
    // Linux 期望 initrd 在高地址区域
    addr = (addr_max - aligned_size) & ~0xFFF;  // 4KB 对齐

    if (addr < addr_min)
    {
        grub_error (GRUB_ERR_OUT_OF_RANGE, "the initrd is too big");
        goto fail;
    }

    // 步骤 10: 分配内存
    {
        grub_relocator_chunk_t ch;
        err = grub_relocator_alloc_chunk_align (relocator, &ch,
                                                addr_min, addr, aligned_size,
                                                0x1000,  // 4KB 对齐
                                                GRUB_RELOCATOR_PREFERENCE_HIGH,
                                                1);
        if (err)
            goto fail;
        initrd_mem = get_virtual_current_address (ch);
        initrd_mem_target = get_physical_target_address (ch);
    }

    // 步骤 11: 加载 initrd 到内存
    // grub_initrd_load 会读取所有 initrd 文件并合并
    if (grub_initrd_load (&initrd_ctx, initrd_mem))
        goto fail;

    // 步骤 12: 设置 boot_params 中的 initrd 信息
    // ⚠️ 关键：这些信息会传递给内核
    linux_params.hdr.ramdisk_image = initrd_mem_target;  // initrd 物理地址
    linux_params.hdr.ramdisk_size = size;                 // initrd 大小
    linux_params.hdr.root_dev = 0x0100;                   // 根设备（RAM disk）

fail:
    grub_initrd_close (&initrd_ctx);
    return grub_errno;
}
```

**关键点：**

1. **高地址优先**：initrd 尽量放在高地址区域（`GRUB_RELOCATOR_PREFERENCE_HIGH`）
   - 这样可以避免与内核解压后的代码冲突
   - Linux 期望 initrd 在高地址

2. **地址限制**：
   - 最大地址：`initrd_addr_max`（通常是 0x3fffffff，约 1GB）
   - 最小地址：内核加载位置之后（`prot_mode_target + prot_init_space`）

3. **多文件支持**：
   - `grub_initrd_init` 支持多个 initrd 文件
   - GRUB 会将它们合并成一个 initramfs
   - 语法：`initrd /boot/initrd.img /boot/extra.img`

4. **与内核的关系**：
   - `ramdisk_image` 和 `ramdisk_size` 通过 `boot_params` 传递给内核
   - 内核启动后从这些地址读取 initrd

**initrd 内存布局示例：**

```
内存地址                  内容
─────────────────────────────────────────
0x100000 (1MB) - 0x1FFFFF      内核镜像（vmlinuz）
0x200000 - ...           内核解压区域
...
0x2F000000 - 0x2FFFFFFF  initrd（尽量在高地址）
                         ↑ ramdisk_image 指向这里
```

## UEFI 启动流程详解

**⚠️ 注意：** 以下内容专门针对 **UEFI 启动方式**，与 BIOS 启动方式不同。

### UEFI 启动流程概述

UEFI 启动流程与 BIOS 的主要区别：

1. **内核格式**：UEFI 使用 PE/COFF 格式的内核（UEFI stub 内核），而不是传统的 bzImage
2. **启动方式**：使用 EFI 的 `LoadImage` 和 `StartImage` 服务，而不是 relocator 代码
3. **运行模式**：GRUB 和内核都在保护模式/长模式下运行，不需要模式切换
4. **参数传递**：通过 EFI System Table 和命令行参数，而不是 `boot_params` 结构

### grub_cmd_linux() 函数（UEFI 版本）

**源代码位置：** `grub/grub-core/loader/efi/linux.c:477-600`

**功能：**
- 验证内核格式（必须是 PE/COFF 格式，UEFI stub 内核）
- 分配内存（使用 EFI `AllocatePages` 服务）
- 加载内核镜像到内存
- 准备命令行参数（转换为 UTF-16 格式）
- 注册启动函数 `grub_linux_boot()`

**完整源代码分析：**

```c
// grub/grub-core/loader/efi/linux.c:477-600
static grub_err_t
grub_cmd_linux (grub_command_t cmd, int argc, char *argv[])
{
    grub_file_t file = 0;
    struct linux_arch_kernel_header lh;
    grub_err_t err;

    // 步骤 1: 打开内核文件
    file = grub_file_open (argv[0], GRUB_FILE_TYPE_LINUX_KERNEL);
    
    // 步骤 2: 验证内核格式（必须是 PE/COFF，UEFI stub 内核）
    if (grub_arch_efi_linux_load_image_header (file, &lh) != GRUB_ERR_NONE)
    {
        // 如果不是 UEFI stub 内核，回退到传统 BIOS 加载方式（仅 x86）
        #if defined(__i386__) || defined(__x86_64__)
        return grub_cmd_linux_x86_legacy (cmd, argc, argv);
        #else
        goto fail;  // 非 x86 架构必须使用 UEFI stub 内核
        #endif
    }
    
    // 步骤 3: 分配内存（使用 EFI AllocatePages 服务）
    kernel_size = grub_file_size (file);
    kernel_addr = grub_efi_allocate_any_pages (
        GRUB_EFI_BYTES_TO_PAGES (kernel_size));
    
    // 步骤 4: 加载内核镜像到内存
    grub_file_seek (file, 0);
    grub_file_read (file, kernel_addr, kernel_size);
    
    // 步骤 5: 准备命令行参数（转换为 UTF-16）
    cmdline_size = grub_loader_cmdline_size (argc, argv) + sizeof (LINUX_IMAGE);
    linux_args = grub_malloc (cmdline_size);
    grub_create_loader_cmdline (argc, argv, linux_args, ...);
    
    // 步骤 6: 注册启动函数
    grub_loader_set (grub_linux_boot, grub_linux_unload, 0);
    loaded = 1;
}
```

**关键点：**

1. **内核格式验证**：
   - 必须包含 PE/COFF 头部（`GRUB_PE32_MAGIC`）
   - 必须是 UEFI stub 内核（编译时启用 `CONFIG_EFI_STUB`）
   - 如果不是，x86 架构会回退到传统 BIOS 加载方式

2. **内存分配**：
   - 使用 `grub_efi_allocate_any_pages()`（EFI `AllocatePages` 服务）
   - 不需要指定固定地址（如 0x100000 (1MB)），EFI 会自动分配

3. **命令行参数**：
   - 转换为 UTF-16 格式（EFI 使用 UTF-16 字符串）
   - 存储在 `linux_args` 中，后续传递给内核

### grub_cmd_initrd() 函数（UEFI 版本）

**源代码位置：** `grub/grub-core/loader/efi/linux.c:400-476`

**功能：**
- 支持两种 initrd 加载方式：
  1. **LoadFile2 协议**（现代内核，image_version >= 1）
  2. **直接加载**（非 x86 架构或旧内核）

**LoadFile2 协议方式（推荐）：**

```c
// grub/grub-core/loader/efi/linux.c:400-476
static grub_err_t
grub_cmd_initrd (grub_command_t cmd, int argc, char *argv[])
{
    // 步骤 1: 检查是否使用 LoadFile2 协议
    if (initrd_use_loadfile2)
    {
        // 安装 LoadFile2 协议
        status = b->install_multiple_protocol_interfaces (
            &initrd_lf2_handle,
            &load_file2_guid,
            &initrd_lf2,  // LoadFile2 协议接口
            &device_path_guid,
            &initrd_lf2_device_path,
            NULL);
        
        // 内核启动后，会通过 LoadFile2 协议读取 initrd
        // GRUB 不需要预先加载 initrd 到内存
        return GRUB_ERR_NONE;
    }
    
    // 步骤 2: 直接加载方式（非 x86 架构或旧内核）
    #if !defined(__i386__) && !defined(__x86_64__)
    initrd_size = grub_get_initrd_size (&initrd_ctx);
    initrd_mem = allocate_initrd_mem (initrd_pages);
    grub_initrd_load (&initrd_ctx, initrd_mem);
    
    // 设置 FDT（设备树）中的 initrd 信息
    grub_fdt_set_prop64 (fdt, node, "linux,initrd-start", initrd_start);
    grub_fdt_set_prop64 (fdt, node, "linux,initrd-end", initrd_end);
    #endif
}
```

**关键点：**

1. **LoadFile2 协议**（现代方式）：
   - GRUB 安装 LoadFile2 协议接口
   - 内核启动后，通过协议读取 initrd（延迟加载）
   - 不需要预先分配内存和加载 initrd

2. **直接加载方式**（传统方式）：
   - 预先分配内存并加载 initrd
   - 对于非 x86 架构，通过 FDT（设备树）传递 initrd 信息
   - 对于 x86 架构，回退到传统 BIOS 方式

### grub_linux_boot() 函数（UEFI 版本）

**源代码位置：** `grub/grub-core/loader/efi/linux.c:270-280`

**功能：**
- 调用 `grub_arch_efi_linux_boot_image()` 启动内核

**完整源代码分析：**

```c
// grub/grub-core/loader/efi/linux.c:270-280
static grub_err_t
grub_linux_boot (void)
{
#if !defined(__i386__) && !defined(__x86_64__)
    // 非 x86 架构：准备 FDT（设备树）
    if (finalize_params_linux () != GRUB_ERR_NONE)
        return grub_errno;
#endif

    // 调用 EFI 启动函数
    return grub_arch_efi_linux_boot_image (
        (grub_addr_t) kernel_addr,
        kernel_size,
        linux_args);
}
```

### grub_arch_efi_linux_boot_image() 函数

**源代码位置：** `grub/grub-core/loader/efi/linux.c:194-280`

**功能：**
- 创建内存映射设备路径（Memory Mapped Device Path）
- 使用 EFI `LoadImage` 服务加载内核
- 设置命令行参数（`load_options`）
- 使用 EFI `StartImage` 服务启动内核

**完整源代码分析：**

```c
// grub/grub-core/loader/efi/linux.c:194-280
grub_arch_efi_linux_boot_image (grub_addr_t addr, grub_size_t size, char *args)
{
    grub_efi_memory_mapped_device_path_t *mempath;
    grub_efi_handle_t image_handle;
    grub_efi_status_t status;
    grub_efi_loaded_image_t *loaded_image;
    
    // 步骤 1: 创建内存映射设备路径
    mempath = grub_malloc (2 * sizeof (grub_efi_memory_mapped_device_path_t));
    mempath[0].header.type = GRUB_EFI_HARDWARE_DEVICE_PATH_TYPE;
    mempath[0].header.subtype = GRUB_EFI_MEMORY_MAPPED_DEVICE_PATH_SUBTYPE;
    mempath[0].start_address = addr;  // 内核地址
    mempath[0].end_address = addr + size;
    
    // 步骤 2: 使用 EFI LoadImage 服务加载内核
    status = grub_efi_load_image (
        0,                              // boot_policy = false
        grub_efi_image_handle,         // parent_image_handle
        (grub_efi_device_path_t *) mempath,  // device_path
        (void *) addr,                  // source_buffer
        size,                           // source_size
        &image_handle);                 // image_handle (输出)
    
    // 步骤 3: 设置命令行参数（转换为 UTF-16）
    loaded_image = grub_efi_get_loaded_image (image_handle);
    args_len = grub_strlen (args);
    len = (args_len + 1) * sizeof (grub_efi_char16_t);
    loaded_image->load_options = grub_efi_allocate_any_pages (
        GRUB_EFI_BYTES_TO_PAGES (len));
    len = grub_utf8_to_utf16 (
        loaded_image->load_options, len,
        (grub_uint8_t *) args, args_len, NULL);
    loaded_image->load_options_size = len * sizeof (grub_efi_char16_t);
    
    // 步骤 4: 使用 EFI StartImage 服务启动内核
    // ⚠️ 关键：这是 EFI 固件提供的服务，负责：
    //   1. 设置 CPU 状态（寄存器、段、分页等）
    //   2. 准备内核执行环境
    //   3. 跳转到内核入口点（PE/COFF EntryPoint）
    //   4. 控制权转移到内核（GRUB 不再执行）
    status = grub_efi_start_image (image_handle, 0, NULL);
    
    // 如果成功，不会返回（控制权已转移到内核）
    // 如果返回，说明启动失败
    grub_error (GRUB_ERR_BAD_OS, "start_image() returned 0x%x", status);
}
```

**关键点：**

1. **内存映射设备路径**：
   - 告诉 EFI 固件内核在内存中的位置
   - EFI 使用设备路径（Device Path）来标识资源

2. **LoadImage 服务**：
   - EFI 固件提供的服务，用于加载可执行镜像
   - 解析 PE/COFF 头部，准备执行环境

3. **StartImage 服务**：
   - EFI 固件提供的服务，用于启动已加载的镜像
   - **不需要 relocator 代码**：EFI 固件负责所有环境准备和跳转
   - 控制权转移到内核后，GRUB 不再执行

4. **参数传递**：
   - 命令行参数通过 `load_options` 字段传递（UTF-16 格式）
   - EFI System Table 通过 EFI 环境自动传递
   - initrd 通过 LoadFile2 协议或 FDT 传递

**UEFI vs BIOS 启动对比：**

| 步骤 | BIOS 启动 | UEFI 启动 |
|------|----------|----------|
| **加载内核** | `grub_cmd_linux()` 直接读取文件到内存 | `grub_cmd_linux()` → `grub_efi_load_image()` |
| **设置参数** | `boot_params` 结构 | `load_options`（UTF-16）+ EFI System Table |
| **启动内核** | `grub_relocator32_boot()` 手动跳转 | `grub_efi_start_image()` EFI 服务 |
| **模式切换** | 保护模式 → 实模式（relocator 代码） | 不需要（都在保护模式/长模式） |
| **环境准备** | relocator 代码设置寄存器、段等 | EFI 固件自动处理 |

### GRUB loader 机制和 boot 命令

**执行流程概述：**

在 `grub_cmd_linux()` 和 `grub_cmd_initrd()` 执行完毕后，GRUB 通过 loader 机制延迟执行跳转：

```
1. grub_cmd_linux() → 注册 grub_linux_boot() 函数
2. grub_cmd_initrd() → 设置 initrd 信息
3. menuentry 结束后 → 隐式调用 boot 命令
4. boot 命令 → 调用注册的 grub_linux_boot()
5. grub_linux_boot() → grub_relocator32_boot() → 跳转到内核
```

**`grub_loader_set` 函数详解：**

`grub_loader_set` 是 GRUB 的 loader 注册机制，用于设置启动和卸载函数，供后续 `boot` 命令调用。

**grub_linux_boot 在内存中的位置：**

`grub_linux_boot` **不是**被“挂载”到某块特殊物理/虚拟地址的代码；它是 **loader 模块里注册的一个函数指针**，保存在 **boot 模块的静态变量**里：

- **实现位置**：`grub-core/commands/boot.c`（boot 模块）中的静态变量：
  - `grub_loader_boot_func`：实际被调用的入口是 **包装函数** `grub_simple_boot_hook`（见下文），不是直接存 `grub_linux_boot`。
  - `grub_loader_context`：传给上述函数的 context，即 **`&simple_loader_hooks`**（同一文件内静态结构体）。
  - `simple_loader_hooks`：静态结构体，其成员 **`.boot = grub_linux_boot`**、**.unload = grub_linux_unload** 在 `grub_loader_set()` 里被赋值。

因此，“挂载”的含义是：**函数指针 `grub_linux_boot` 被写入 boot 模块的静态数据区**（`simple_loader_hooks.boot`），而 **`grub_linux_boot` 的代码本身** 仍在 **linux 模块（或内置）的代码段** 中，即 GRUB 正常加载的模块/内核镜像所在内存，没有单独拷贝到别的地址。

**grub_loader_set 执行过程（源码：`grub-core/commands/boot.c`）：**

1. **入口**：`grub_cmd_linux()` 调用  
   `grub_loader_set (grub_linux_boot, grub_linux_unload, 0);`

2. **`grub_loader_set()`（约 163–174 行）**：
   - 调用 `grub_loader_set_ex (grub_simple_boot_hook, grub_simple_unload_hook, &simple_loader_hooks, flags)`：
     - 若已有 loader（`grub_loader_loaded && grub_loader_unload_func`），先执行 `grub_loader_unload_func (grub_loader_context)` 卸载旧内核。
     - `grub_loader_boot_func = grub_simple_boot_hook`  
     - `grub_loader_unload_func = grub_simple_unload_hook`  
     - `grub_loader_context = &simple_loader_hooks`  
     - `grub_loader_flags = flags`  
     - `grub_loader_loaded = 1`
   - 然后在本函数内：`simple_loader_hooks.boot = boot`（即 `grub_linux_boot`），`simple_loader_hooks.unload = unload`（即 `grub_linux_unload`）。

3. **后续 boot 命令触发时**：  
   `grub_cmd_boot()` → `grub_loader_boot()`（约 190–220 行）：
   - 若 `!grub_loader_loaded` 则报错 "you need to load the kernel first"。
   - 执行 `grub_machine_fini (grub_loader_flags)`，再按链表执行各 preboot 钩子。
   - **核心调用**：`err = (grub_loader_boot_func) (grub_loader_context)`  
     即 `grub_simple_boot_hook (&simple_loader_hooks)`。
   - `grub_simple_boot_hook()`（约 57–64 行）：从 context 取出 `struct grub_simple_loader_hooks *hooks`，执行 **`return hooks->boot ();`**，即 **`grub_linux_boot()`**。

**小结**：`grub_linux_boot` 的“挂载”= 其**函数指针**被存进 boot 模块的 **`simple_loader_hooks.boot`**；真正执行时通过 **`grub_loader_boot_func(grub_loader_context)` → `grub_simple_boot_hook(&simple_loader_hooks)` → `hooks->boot()`** 间接调用到 `grub_linux_boot()`。

**函数声明（`grub/include/grub/loader.h:39-41`）：**

```c
void EXPORT_FUNC (grub_loader_set) (grub_err_t (*boot) (void),
                                    grub_err_t (*unload) (void),
                                    int flags);
```

**参数说明：**
- `boot`：启动函数指针，执行实际的内核跳转（如 `grub_linux_boot`）
- `unload`：卸载函数指针，用于清理已加载的内核资源（如 `grub_linux_unload`）
- `flags`：标志位，控制启动行为：
  - `GRUB_LOADER_FLAG_NORETURN = 1`：启动函数不返回
  - `GRUB_LOADER_FLAG_PXE_NOT_UNLOAD = 2`：不卸载 PXE 资源
  - `GRUB_LOADER_FLAG_EFI_KEEP_ALLOCATED_MEMORY = 4`：保持 EFI 分配的内存

**函数实现（`grub/grub-core/commands/boot.c:140-180`）：**

```c
void
grub_loader_set_ex (grub_err_t (*boot) (void *context),
                    grub_err_t (*unload) (void *context),
                    void *context,
                    int flags)
{
    // ⚠️ 关键：如果已经加载了内核，先卸载之前的内核
    if (grub_loader_loaded && grub_loader_unload_func)
        grub_loader_unload_func (grub_loader_context);
    
    // 设置新的 loader
    grub_loader_boot_func = boot;
    grub_loader_unload_func = unload;
    grub_loader_context = context;
    grub_loader_flags = flags;
    grub_loader_loaded = 1;
}

void
grub_loader_set (grub_err_t (*boot) (void),
                 grub_err_t (*unload) (void),
                 int flags)
{
    // 调用扩展版本，包装简单的 boot/unload 函数
    grub_loader_set_ex (grub_simple_boot_hook,
                        grub_simple_unload_hook,
                        &simple_loader_hooks,
                        flags);

    // 保存 boot 和 unload 函数到静态结构体
    simple_loader_hooks.boot = boot;      // 保存 grub_linux_boot
    simple_loader_hooks.unload = unload;  // 保存 grub_linux_unload
}
```

**⚠️ 多个内核加载的处理：**

**问题：如果加载多个内核会怎样？需要复制多个内核吗？**

**答案：** 不需要！GRUB 的 loader 机制确保**只有最后一个内核是活动的**，之前的内核会被自动卸载。

**详细说明：**

1. **自动卸载机制**：
   - `grub_loader_set_ex()` 在设置新的 loader 之前，会先调用之前的 `unload` 函数
   - 这意味着如果执行两次 `linux` 命令，第一次加载的内核会被卸载

2. **卸载过程分析**：

   **`grub_linux_unload()` 函数**（`grub/grub-core/loader/i386/linux.c`）：
   ```c
   static grub_err_t
   grub_linux_unload (void)
   {
       grub_dl_unref (my_mod);      // 减少模块引用计数
       loaded = 0;                   // 清除加载标志
       grub_free (linux_cmdline);    // 释放命令行参数字符串
       linux_cmdline = 0;
       return GRUB_ERR_NONE;
   }
   ```
   
   **⚠️ 关键点**：`grub_linux_unload()` **不直接释放临时缓冲区内存**（`prot_mode_mem`）。
   
   **实际的资源释放机制**：
   
   临时缓冲区内存的释放是在**加载新内核时自动完成的**，通过 `allocate_pages()` 函数：
   
   ```c
   // grub/grub-core/loader/i386/linux.c
   static void
   free_pages (void)
   {
       grub_relocator_unload (relocator);  // 释放 relocator 和所有 chunk
       relocator = NULL;
       prot_mode_mem = initrd_mem = 0;     // 清除指针
       prot_mode_target = initrd_mem_target = 0;
   }
   
   static grub_err_t
   allocate_pages (grub_size_t prot_size, ...)
   {
       // ⚠️ 关键：在分配新页面之前，先释放旧的
       free_pages ();  // 释放之前内核的临时缓冲区
       
       // 然后分配新的临时缓冲区
       relocator = grub_relocator_new ();
       // ... 分配新的内存 ...
   }
   ```
   
   **完整的卸载流程**：
   
   **注意**：以下步骤均发生在**加载阶段**（再次执行 `linux` 命令时），而非用户按 Enter **启动**时。allocate_pages 每次执行 `linux` 命令时都会在加载阶段被调用；旧缓冲区的释放是在**本次加载新内核**的过程中触发的。
   
   当加载新内核时（执行第二个 `linux` 命令）：
   ```
   1. grub_loader_set_ex() 检测到已有内核加载
      ↓
   2. 调用 grub_linux_unload()
      - 释放 linux_cmdline
      - 设置 loaded = 0
      ↓
   3. grub_cmd_linux() 开始加载新内核
      ↓
   4. allocate_pages() 被调用
      ↓
   5. free_pages() 自动释放之前内核的临时缓冲区
      - grub_relocator_unload (relocator)
      - 释放 prot_mode_mem（临时缓冲区，16MB+）
      - 释放 initrd_mem（如果存在）
      ↓
   6. 分配新内核的临时缓冲区
   ```
   
   **为什么这样设计？**
   - **简化卸载函数**：`grub_linux_unload()` 只负责清理轻量级资源
   - **自动资源管理**：临时缓冲区在分配新缓冲区时自动释放，避免重复释放
   - **错误处理**：如果新内核加载失败，旧的内核资源仍然可用

3. **实际场景示例**：
   
   **重要**：GRUB 不会在读取 cfg 时预先把所有 menuentry 的内核都加载到内存。解析 cfg 时只**注册**各 menuentry（把条目加入菜单）；menuentry **内部的命令**（如 `linux`、`initrd`）是在**用户选中该条目**（或该条目被自动执行）时才运行的。因此“再次执行 linux”只会在以下两种情况下出现：
   
   ```bash
   # 场景 1：在同一个 menuentry 中写了两条 linux（少见）
   # 用户选中本条目后，会依次执行两条 linux，第二条会触发卸载第一条
   menuentry "Test" {
       linux /boot/vmlinuz-5.10 root=/dev/sda1    # 先加载 5.10
       linux /boot/vmlinuz-5.15 root=/dev/sda1    # 再加载 5.15（5.10 被卸载）
       boot  # 启动 5.15
   }
   
   # 场景 2：两个 menuentry，用户先选一个再改选另一个（未按 boot 前切回菜单重选）
   # 用户先选 "Linux 5.10" → 执行该条目体 → linux 5.10 被加载
   # 用户再按 Esc/箭头切回菜单，选 "Linux 5.15" → 执行该条目体 → linux 5.15 被调用，5.10 被卸载
   menuentry "Linux 5.10" {
       linux /boot/vmlinuz-5.10 root=/dev/sda1
   }
   menuentry "Linux 5.15" {
       linux /boot/vmlinuz-5.15 root=/dev/sda1
   }
   ```
   
   若用户只选一次且直接 boot（最常见），则整个过程中只会执行**一次** `linux`，只加载一个内核。

4. **内存布局（加载多个内核时）**：
   ```
   第一次加载内核：
   0x1000000 (16MB)+ → 内核 1 临时缓冲区（prot_mode_mem）
   
   第二次加载内核（第一个被卸载）：
   0x1000000 (16MB)+ → 内核 2 临时缓冲区（prot_mode_mem）
   （内核 1 的内存已被释放）
   
   boot 时：
   0x100000 (1MB) → 内核 2（从临时缓冲区复制到此）
   ```

4. **⚠️ 多内核时也需要复制吗？**
   
   **答案：是的，但只有最后一个内核会被复制并启动。**
   
   **详细说明**：
   - **每个内核**在加载时都会：
     1. 分配临时缓冲区（通常在 16MB+）
     2. 将内核镜像复制到临时缓冲区
     3. 设置 `boot_params`
     4. 注册启动函数
   
   - **当加载新内核时**：
     1. `grub_loader_set_ex()` 检测到已有内核，调用 `grub_linux_unload()`
        - 释放 `linux_cmdline` 字符串
        - 设置 `loaded = 0`
     2. `grub_cmd_linux()` 开始加载新内核
     3. `allocate_pages()` 被调用，首先调用 `free_pages()`
        - 释放之前内核的临时缓冲区（`prot_mode_mem`，16MB+）
        - 释放 relocator 和所有 chunk
     4. 为新内核分配新的临时缓冲区
   
   - **boot 时**：
     1. 只有**最后一个加载的内核**会被复制到 0x100000 (1MB)
     2. 之前的内核已经被卸载，不会参与启动过程
     3. relocator 代码只复制最后一个内核
   
   **示例流程**：
   ```bash
   # 用户执行：
   linux /boot/vmlinuz-5.10 root=/dev/sda1    # 内核 1 加载到临时缓冲区（16MB+）
   linux /boot/vmlinuz-5.15 root=/dev/sda1    # 内核 2 加载到临时缓冲区（16MB+），内核 1 被卸载
   boot
   
   # boot 时执行：
   grub_linux_boot() → grub_relocator32_boot()
     ↓
   relocator 代码执行：
     1. 复制内核 2 从临时缓冲区（16MB+）→ 0x100000 (1MB)
     2. 切换到实模式
     3. 跳转到内核 2 的 code32_start @ 0x100000 (1MB)
   
   # 内核 1 不会被复制，因为它已经被卸载
   ```

5. **⚠️ 为什么必须卸载内核？不卸载可以吗？**

   **答案：必须卸载！** 如果不卸载，会导致严重问题。

   **如果不卸载会发生什么？**

   假设不卸载之前的内核，直接加载新内核：

   ```c
   // ❌ 错误做法：不卸载之前的内核
   void grub_loader_set_ex (...)
   {
       // 不调用 grub_loader_unload_func()
       // 直接设置新的 loader
       grub_loader_boot_func = boot;
       grub_loader_unload_func = unload;
   }
   ```

   **问题 1：内存浪费**
   - 每个内核占用**16MB+ 的临时缓冲区**（`prot_mode_mem`）
   - 如果加载 3 个内核，会占用 48MB+ 的内存
   - 这些内存永远不会被释放（直到系统重启）
   - 在内存受限的系统上，可能导致后续操作失败

   **问题 2：状态混乱**
   - 如果有多个内核，哪个会被启动？
   - `grub_loader_boot_func` 只能指向一个函数
   - 如果覆盖了之前的函数指针，之前的内核就无法启动
   - 但之前的内核内存仍然占用，造成资源浪费

   **问题 3：资源泄漏**
   
   **⚠️ 关键澄清**：你的理解部分正确，但不完全正确。
   
   **内存布局分析**：
   - **临时缓冲区位置**：`prot_mode_mem` 通常在 **16MB+**（0x1000000 (16MB)+）
   - **内核最终位置**：
     - 内核被复制到 **0x100000 (1MB)**（1MB）← 这会覆盖 GRUB 代码
     - 内核解压后的代码通常在 **0x1000000 (16MB)+**（16MB+）← 与临时缓冲区在同一区域
   
   **两种情况**：
   
   1. **如果临时缓冲区在内核解压后的代码区域**：
      - 临时缓冲区会被内核解压后的代码**覆盖**
      - 但这不是"释放"，而是"覆盖"
      - 覆盖后，临时缓冲区的内容被破坏，但物理内存仍然被占用（只是被内核使用）
   
   2. **如果临时缓冲区不在内核解压后的代码区域**：
      - 临时缓冲区**不会被覆盖**
      - 会一直占用物理内存
      - **⚠️ 关键澄清**：内核启动后如何处理这些内存？
   
   **内核的内存管理机制**：
   
   内核**不会检查内存中是否有数据**，而是根据 **E820 内存映射表**来管理内存：
   
   ```c
   // grub/grub-core/loader/i386/linux.c:593-596
   ctx.e820_num = 0;
   if (grub_mmap_iterate (grub_linux_boot_mmap_fill, &ctx))
       return grub_errno;
   ctx.params->e820_entries = ctx.e820_num;
   ```
   
   **E820 表构建过程**：
   - GRUB 通过 `grub_mmap_iterate()` 遍历 BIOS E820 表
   - 将每个内存区域添加到 `boot_params.e820_table`
   - 内核启动后，从 `boot_params.e820_table` 读取内存映射
   - 内核根据 E820 表的类型（`E820_RAM` = 可用，`E820_RESERVED` = 保留）来管理内存
   
   **关键点**：
   - **内核不会检查内存内容**：内核不会扫描内存看是否有数据
   - **内核只根据 E820 表**：如果 E820 表标记为"可用"（`E820_RAM`），内核就将其视为可用内存
   - **临时缓冲区的处理**：
     - 如果临时缓冲区在 E820 表标记为"可用"的区域，内核会将其视为可用内存
     - 内核会将这些内存添加到内存管理系统中（如 memblock、page allocator）
     - 内核可以分配和使用这些内存，**不管里面是否有 GRUB 的临时数据**
   
   **实际效果**：
   - 如果临时缓冲区在 E820 表标记为"可用"的区域：
     - 内核会将其视为可用内存
     - 内核可以分配和使用这些内存
     - 临时缓冲区中的 GRUB 数据会被后续的内核数据覆盖
     - **这不是"浪费"，而是"被重用"**
   
   **但是，为什么还要卸载？**
   
   即使内核启动后会重用临时缓冲区，**在 GRUB 阶段（内核启动前）**仍然需要卸载：
   - **GRUB 阶段的内存管理**：GRUB 有自己的内存管理器，临时缓冲区被 GRUB 分配和占用
   - **如果加载多个内核**：每个内核都会占用一个临时缓冲区（16MB+）
   - **在用户选择启动项之前**：这些内存一直占用，无法被 GRUB 的其他操作使用
   - **可能导致失败**：如果系统内存有限，可能导致后续操作失败（如加载 initrd 失败）
   
   **总结**：
   - **内核启动后**：临时缓冲区会被内核重用（如果 E820 表标记为可用），不是"浪费"
   - **GRUB 阶段**：必须卸载，避免在 GRUB 阶段占用过多内存
   - **内核不会检查内存内容**：只根据 E820 表来管理内存
   
   **更重要的是：GRUB 阶段的问题**
   
   即使内核启动后会覆盖临时缓冲区，**在 GRUB 阶段（内核启动前）**，如果不卸载：
   - 多个内核会占用多个临时缓冲区（每个 16MB+）
   - 在用户选择启动项之前，这些内存一直占用
   - 如果用户加载了 3 个内核，会占用 48MB+ 内存
   - 在内存受限的系统上，可能导致后续操作失败（如加载 initrd 失败）
   
   **实际场景**：
   ```bash
   # 用户在 GRUB 菜单中：
   menuentry "Test" {
       linux /boot/vmlinuz-5.10    # 占用 16MB+ 临时缓冲区
       linux /boot/vmlinuz-5.15    # 再占用 16MB+（如果不卸载）
       linux /boot/vmlinuz-5.20    # 再占用 16MB+（如果不卸载）
       # 此时总共占用 48MB+ 内存（在 GRUB 阶段）
       # 如果系统只有 128MB 内存，可能导致后续操作失败
   }
   ```
   
   **结论**：
   - **GRUB 阶段**：如果不卸载，多个内核会占用多个临时缓冲区，造成内存浪费
   - **内核启动后**：临时缓冲区可能被覆盖，但这不是"释放"，而是"覆盖"
   - **最佳实践**：在 GRUB 阶段就卸载不需要的内核，避免内存浪费

   **问题 4：错误恢复困难**
   - 如果新内核加载失败，旧的内核资源仍然占用
   - 无法回退到之前的内核
   - 内存碎片化，可能导致后续分配失败

   **实际场景示例**：

   ```bash
   # 场景：用户尝试加载多个内核
   menuentry "Test" {
       linux /boot/vmlinuz-5.10 root=/dev/sda1    # 内核 1：占用 16MB+
       linux /boot/vmlinuz-5.15 root=/dev/sda1    # 内核 2：再占用 16MB+
       linux /boot/vmlinuz-5.20 root=/dev/sda1    # 内核 3：再占用 16MB+
       # 如果不卸载：总共占用 48MB+ 内存
       # 如果卸载：只占用 16MB+ 内存（最后一个内核）
   }
   ```

   **为什么这样设计？**
   - **简化管理**：只保留一个内核，避免内存浪费
   - **明确行为**：用户明确知道哪个内核会被启动
   - **资源清理**：自动释放不需要的内核内存
   - **错误恢复**：如果新内核加载失败，可以回退到之前的状态
   - **内存效率**：避免内存碎片化和资源泄漏

**全局状态变量（`grub/grub-core/commands/boot.c:30-33`）：**

```c
static grub_err_t (*grub_loader_boot_func) (void *context);   // 启动函数指针
static grub_err_t (*grub_loader_unload_func) (void *context); // 卸载函数指针
static void *grub_loader_context;                              // 上下文数据
static int grub_loader_flags;                                  // 标志位
static int grub_loader_loaded;                                 // 是否已加载 loader
```

**`boot` 命令的执行流程（`grub/grub-core/commands/boot.c:190-220`）：**

```c
grub_err_t
grub_loader_boot (void)
{
    grub_err_t err = GRUB_ERR_NONE;
    struct grub_preboot *cur;

    // 检查是否已加载内核
    if (! grub_loader_loaded)
        return grub_error (GRUB_ERR_NO_KERNEL,
                           N_("you need to load the kernel first"));

    // ⚠️ 关键：清理 GRUB 使用的硬件资源
    // 包括：关闭中断、停止定时器、卸载模块等
    grub_machine_fini (grub_loader_flags);

    // 执行 preboot hooks（如果有注册的话）
    for (cur = preboots_head; cur; cur = cur->next)
    {
        err = cur->preboot_func (grub_loader_flags);
        if (err)
        {
            // 出错时恢复
            for (cur = cur->prev; cur; cur = cur->prev)
                cur->preboot_rest_func ();
            return err;
        }
    }

    // ⚠️ 核心：调用注册的启动函数（如 grub_linux_boot）
    err = (grub_loader_boot_func) (grub_loader_context);

    // 执行 preboot 恢复函数（通常不会执行到这里，因为已跳转到内核）
    for (cur = preboots_tail; cur; cur = cur->prev)
        if (! err)
            err = cur->preboot_rest_func ();
        else
            cur->preboot_rest_func ();

    return err;
}
```

**完整调用链：**

```
用户选择菜单项（按 Enter）
    ↓
grub_cmd_boot()                    [grub-core/commands/boot.c:224]
    ↓
grub_loader_boot()                 [grub-core/commands/boot.c:190]
    ├─ grub_machine_fini()         // 清理硬件资源
    └─ grub_loader_boot_func()     // 调用注册的启动函数
        ↓
grub_linux_boot()                  [grub-core/loader/i386/linux.c]
    ↓
grub_relocator32_boot()            // 跳转到内核入口点
    ↓
内核 code32_start
```

**隐式执行 boot 的代码与流程：**

脚本体执行完后**不会自动**执行 boot，只有在「无错误且已加载 loader」时才隐式执行 boot。

1. **触发位置**（`grub-core/normal/menu.c:303-307`）：
   ```c
   grub_script_execute_new_scope (entry->sourcecode, entry->argc, entry->args);

   if (grub_errno == GRUB_ERR_NONE && grub_loader_is_loaded ())
       /* Implicit execution of boot, only if something is loaded.  */
       grub_command_execute ("boot", 0, 0);
   ```
   即：脚本体（`entry->sourcecode`）执行返回后，若当前无错误且 `grub_loader_is_loaded()` 为真，则调用 `grub_command_execute ("boot", 0, 0)`，相当于执行一次 boot 命令。

2. **`grub_loader_is_loaded()`**（`grub-core/commands/boot.c:80-84`）：
   ```c
   int grub_loader_is_loaded (void)
   {
     return grub_loader_loaded;
   }
   ```
   `grub_loader_loaded` 在 `grub_loader_set()` / `grub_loader_set_ex()` 里被置 1；`grub_cmd_linux()` 里调用 `grub_loader_set (grub_linux_boot, grub_linux_unload, 0)` 时就会置 1，表示「已加载内核并注册了启动函数」。

3. **隐式 boot 的调用链**（与用户显式输入 `boot` 相同）：
   ```
   grub_command_execute ("boot", 0, 0)
       → grub_command_find ("boot") 查表 → (cmd->func)(...) = grub_cmd_boot()
       → grub_cmd_boot()  [commands/boot.c:224]
       → grub_loader_boot()  [commands/boot.c:190]
       → (grub_loader_boot_func)(grub_loader_context) 即 grub_linux_boot()
       → grub_relocator32_boot()
   ```

**关键点：**
- **延迟执行机制**：`grub_cmd_linux()` 只负责准备（加载内核、注册函数），不执行跳转；跳转由脚本执行完毕后的隐式或显式 `boot` 触发
- **用户交互触发**：先由用户选择菜单项（按 Enter），GRUB 才执行该条目的脚本体（此时才调用 `grub_cmd_linux()`）；脚本执行完后若已加载 loader 则隐式 `boot`
- **灵活性**：解析 cfg 时只注册条目、不加载内核；只有被选中的条目的脚本体会执行，因此同一时刻最多只有一个内核被加载（除非同一条目内写多条 `linux` 或用户改选另一条目）

**GRUB 菜单选择与启动函数的关系（与源码一致）：**

执行时机与调用链见上文「从 grub_main 到 grub_cmd_menuentry 的调用链」与「grub_cmd_linux() 与 grub_linux_boot() 职责划分」：解析 config 时只注册 menuentry（脚本体存到 `entry->sourcecode`）；用户选择该条后执行 `entry->sourcecode`，此时才调用 `grub_cmd_linux()`；脚本结束后隐式或显式 `boot` → `grub_linux_boot()` → `grub_relocator32_boot()`。

**示例 `grub.cfg` 配置：**

```bash
# /boot/grub/grub.cfg
menuentry "Linux 5.x.x" {
    linux /boot/vmlinuz-5.x.x root=/dev/sda1 ro
    initrd /boot/initrd.img-5.x.x
}

# 用户按 Enter 选择该条目后，GRUB 执行该条目的脚本体，顺序为：
# 1. linux 命令 → grub_cmd_linux() 加载内核到临时缓冲区（通常在 16MB+）、注册 grub_linux_boot()
# 2. initrd 命令 → grub_cmd_initrd() 加载 initramfs
# 3. 脚本体执行完毕；若 grub_loader_is_loaded() 则隐式 boot → grub_linux_boot() → grub_relocator32_boot()
#    - 构建 relocator 代码（包含复制内核的代码 + 跳转代码）
#    - 将 relocator 代码复制到安全区域（0x1000-0x9a000）
#    - 执行 relocator 代码：
#      a. 将内核从临时缓冲区（16MB+）复制到 0x100000 (1MB)
#      b. 切换到实模式
#      c. 跳转到内核入口点（code32_start @ 0x100000 (1MB)）
```

### grub_linux_boot() 函数

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

### grub_relocator32_boot() 函数

**概要**：在安全区 (0x1000-0x9a000) 分配 chunk，拷贝 relocator32 副本，调用 `grub_relocator_prepare_relocs()` 生成 movers_chunk（复制内核 + jumper），再跳转到 movers_chunk；执行顺序、两处代码来源、为何动态生成、为何必须复制等详见 [GRUB_RELOCATOR.md](GRUB_RELOCATOR.md)。

**⚠️ 关键问题解答（简要）**：relocator 代码对应 relocator32.S（安全区）与 relocator_asm.S/relocator_common_c.c（movers_chunk）；复制到安全区是因 GRUB 在 0x100000 (1MB)+ 会被内核覆盖；不能直接跳 code32_start 因需先切实模式、设段与寄存器。详述见 [GRUB_RELOCATOR.md](GRUB_RELOCATOR.md)。

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
// - prot_mode_target: 内核实际加载地址（通常是 0x100000 (1MB)）
// - lh.code32_start: 内核头部中的字段，表示相对于 0x100000 (1MB) 的偏移
// - GRUB_LINUX_BZIMAGE_ADDR: 0x100000 (1MB)
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
├─ 0x100000 (1MB) - 0x1001FF   内核头部（boot_params，512 字节）
├─ 0x100200 - ...        Setup 代码（setup_sects * 512 字节）
└─ Setup 之后           压缩的内核代码（gzip 压缩）
    ↓（解压后）
0x100000 (1MB)+               解压后的内核代码
├─ startup_32           32 位保护模式入口点
└─ startup_64           64 位长模式入口点
```

**⚠️ 关键问题：内核覆盖 GRUB 代码后如何完成跳转？**

内核被加载到 0x100000 (1MB)+，这与 GRUB 解压后的代码区域重叠。GRUB 通过 **relocator 机制** 解决这个问题：

**Relocator 机制（`grub/grub-core/lib/i386/relocator.c`）：**

```c
// grub_relocator32_boot() 在 0x1000-0x9a000 范围内分配安全区域
// 这是 1MB 以下的常规内存，不会被内核覆盖
err = grub_relocator_alloc_chunk_align_safe (rel, &ch,
    0x1000,   // 最小地址
    0x9a000,  // 最大地址（1MB 以下的安全区域）
    RELOCATOR_SIZEOF (32),  // relocator 代码大小
    16,       // 对齐
    GRUB_RELOCATOR_PREFERENCE_LOW,
    avoid_efi_bootservices);

// 将跳转代码复制到安全区域
grub_memmove (get_virtual_current_address (ch),
              &grub_relocator32_start,
              RELOCATOR_SIZEOF (32));
```

**Relocator 跳转代码（`grub/grub-core/lib/i386/relocator32.S`）：**

```asm
VARIABLE(grub_relocator32_start)
    // ... 设置段寄存器、禁用分页 ...
    
    // 设置寄存器（从预设的变量中读取）
    movl    grub_relocator32_esp, %esp
    movl    grub_relocator32_esi, %esi  // boot_params 地址
    // ... 其他寄存器 ...
    
    // ⚠️ 核心：远跳转到内核入口点
    .byte   0xea                        // ljmp 指令
VARIABLE(grub_relocator32_eip)
    .long   0                           // 跳转目标（内核 code32_start）
    .word   CODE_SEGMENT                // 代码段选择子
VARIABLE(grub_relocator32_end)
```

**完整的跳转流程：**

```
grub_linux_boot()
    ↓
grub_relocator32_boot()
    ├─ 1. 在 0x1000-0x9a000 分配安全区域（不会被内核覆盖）
    ├─ 2. 将 relocator 代码复制到安全区域
    ├─ 3. 设置 grub_relocator32_eip = code32_start（内核入口点）
    └─ 4. 跳转到安全区域执行
            ↓
安全区域的 relocator 代码
    ├─ 5. 设置寄存器（esp, esi, eax 等）
    ├─ 6. 禁用分页，准备 32 位保护模式环境
    └─ 7. 执行 ljmp 跳转到内核 code32_start
            ↓
内核入口点（code32_start @ 0x100000 (1MB)）
```

**内存布局关键点：**

```
0x0000 - 0x03FF      IVT（中断向量表）
0x0400 - 0x04FF      BDA（BIOS 数据区）
0x1000 - 0x9A000     ⚠️ 安全区域（relocator 代码在此执行）
0x7C00 - 0x7DFF      引导扇区
0x8000 - 0xFFFF      GRUB 实模式代码（startup_raw.S 等）
0x100000 (1MB)+            GRUB 保护模式代码（会被内核覆盖）
0x100000 (1MB)+            内核镜像（覆盖 GRUB 代码）
```

**为什么这个机制有效：**

1. **安全区域选择**：0x1000-0x9a000 是 1MB 以下的常规内存，不会被加载到 0x100000 (1MB)+ 的内核覆盖
2. **代码复制**：跳转代码被复制到安全区域，原始代码被覆盖不影响执行
3. **单向跳转**：一旦跳转到内核，GRUB 代码不再需要，被覆盖无关紧要
4. **自包含代码**：relocator 代码包含完整的 GDT 和跳转指令，不依赖外部代码

**内核启动参数传递：**

GRUB 通过 `boot_params` 结构（Linux Boot Protocol）向内核传递参数：

- **`code32_start`**：内核入口点地址（传递给内核，内核从这里开始执行）
- **`cmd_line_ptr`**：内核命令行参数地址（如 `root=/dev/sda1`）
- **`ramdisk_image`**：initramfs 地址（由 GRUB 的 `grub_cmd_initrd()` 设置）
- **`ramdisk_size`**：initramfs 大小（由 GRUB 的 `grub_cmd_initrd()` 设置）
- **`e820_map`**：系统内存映射表
- **`esi` 寄存器**：包含 `boot_params` 的地址（内核通过 `%esi` 访问）

**initrd 加载流程总结：**

> **详细说明**：关于 `grub_cmd_initrd()` 函数的完整源代码分析，请参见 [grub_cmd_initrd() 函数详细讲解](#grub_cmd_initrd-函数详细讲解)。

**内核读取 initrd：**
- 内核启动后，从 `boot_params.ramdisk_image` 和 `ramdisk_size` 获取 initrd 位置和大小
- 将 initrd 挂载为临时根文件系统（initramfs）
- 加载驱动模块，初始化硬件，最后切换到真正的根文件系统

> **详细说明**：关于 vmlinuz 文件结构的完整分析，请参见 [附录：vmlinuz 文件详细结构分析](#附录vmlinuz-文件详细结构分析)。

---

## 附录：GRUB 核心模块分类

本附录详细列出 GRUB 支持的各类模块，帮助理解 `grub_load_modules()` 加载的模块类型。

### 模块分类（i386-pc 平台典型配置）

#### 1. 文件系统驱动模块（fs/）

| 模块名 | 功能 | 使用场景 |
|--------|------|----------|
| `ext2` | ext2/ext3/ext4 文件系统支持 | Linux 系统分区（最常用） |
| `fat` | FAT12/FAT16/FAT32 文件系统支持 | UEFI ESP 分区、Windows 兼容 |
| `iso9660` | ISO 9660 文件系统支持 | CD/DVD 镜像引导 |
| `btrfs` | Btrfs 文件系统支持 | Linux 高级文件系统 |
| `xfs` | XFS 文件系统支持 | RHEL/CentOS 默认文件系统 |
| `ntfs` | NTFS 文件系统支持 | Windows 系统分区 |
| `hfs/hfsplus` | HFS/HFS+ 文件系统支持 | macOS 系统分区 |
| `minix` | Minix 文件系统支持 | Minix 操作系统 |
| `jfs` | JFS 文件系统支持 | AIX/Linux 文件系统 |
| `f2fs` | F2FS 文件系统支持 | 闪存优化文件系统 |
| `erofs` | EROFS 文件系统支持 | 只读压缩文件系统 |

#### 2. 分区表模块（partmap/）

| 模块名 | 功能 | 使用场景 |
|--------|------|----------|
| `part_msdos` | MBR 分区表支持 | 传统 BIOS 启动（最常用） |
| `part_gpt` | GPT 分区表支持 | UEFI 启动（推荐） |
| `part_apple` | Apple 分区表支持 | macOS 系统 |
| `part_sun` | Sun 分区表支持 | SPARC 架构 |
| `part_plan` | Plan 9 分区表支持 | Plan 9 操作系统 |

#### 3. 磁盘驱动模块（disk/）

| 模块名 | 功能 | 使用场景 |
|--------|------|----------|
| `biosdisk` | BIOS 磁盘驱动（INT 13h） | 传统 BIOS 模式（必需） |
| `ahci` | AHCI SATA 控制器驱动 | 现代 SATA 硬盘 |
| `ata` | ATA/IDE 控制器驱动 | IDE 硬盘 |
| `pata` | PATA（并行 ATA）驱动 | 老式 IDE 硬盘 |
| `scsi` | SCSI 磁盘驱动 | SCSI 硬盘 |
| `usbms` | USB 大容量存储设备驱动 | U 盘、移动硬盘 |
| `lvm` | LVM（逻辑卷管理）支持 | Linux LVM 分区 |
| `mdraid_linux` | Linux 软件 RAID 支持 | Linux RAID 阵列 |
| `cryptodisk` | 加密磁盘支持（LUKS） | 加密分区 |
| `luks/luks2` | LUKS 加密支持 | Linux 加密分区 |
| `geli` | GELI 加密支持 | FreeBSD 加密分区 |

#### 4. 加载器模块（loader/）

| 模块名 | 功能 | 使用场景 |
|--------|------|----------|
| `linux` | Linux 内核加载器 | 启动 Linux 系统（提供 `linux` 和 `initrd` 命令） |
| `multiboot` | Multiboot 规范加载器 | 启动 Multiboot 兼容内核（如 Xen） |
| `multiboot2` | Multiboot2 规范加载器 | Multiboot 规范第二版 |
| `xnu` | macOS XNU 内核加载器 | 启动 macOS 系统 |
| `chain` | 链式加载器 | 加载其他引导加载程序（如 Windows bootmgr） |
| `efi` | EFI 应用加载器 | UEFI 模式下加载 EFI 应用 |

#### 5. 命令模块（commands/）

| 模块名 | 提供命令 | 功能 |
|--------|----------|------|
| `normal` | `menuentry`, `submenu` 等 | normal 模式（菜单显示、用户交互） |
| `search` | `search` | 查找文件系统、设备 |
| `ls` | `ls` | 列出文件（注：也有核心 ls 命令） |
| `cat` | `cat` | 显示文件内容 |
| `configfile` | `configfile` | 加载配置文件 |
| `boot` | `boot` | 启动已加载的内核 |
| `reboot` | `reboot` | 重启系统 |
| `halt` | `halt` | 关机 |

**⚠️ 注意**：`set`、`unset`、`ls`、`insmod` 是核心命令（由 `grub_register_core_commands()` 注册），不需要加载模块。

#### 6. 终端模块（term/）

| 模块名 | 功能 | 使用场景 |
|--------|------|----------|
| `gfxterm` | 图形终端支持 | VGA、framebuffer 图形显示 |
| `vga_text` | VGA 文本模式终端 | 传统 VGA 文本模式 |
| `serial` | 串口终端支持 | 串口调试、远程控制 |
| `at_keyboard` | AT 键盘驱动 | PS/2 键盘 |
| `usb_keyboard` | USB 键盘驱动 | USB 键盘 |

#### 7. 视频模块（video/）

| 模块名 | 功能 | 使用场景 |
|--------|------|----------|
| `vbe` | VBE（VESA BIOS Extensions）支持 | BIOS 模式图形显示 |
| `vga` | VGA 视频支持 | 基本 VGA 图形 |
| `efi_gop` | EFI GOP（Graphics Output Protocol）支持 | UEFI 模式图形显示 |
| `efi_uga` | EFI UGA（Universal Graphics Adapter）支持 | 老式 UEFI 图形支持 |

#### 8. 其他模块

| 模块名 | 功能 | 使用场景 |
|--------|------|----------|
| `relocator` | 代码重定位器 | 内核加载时的内存重定位 |
| `verifiers` | 文件签名验证器 | Secure Boot 签名验证 |
| `gzio` | gzip 压缩/解压支持 | 处理 gzip 压缩文件 |
| `xzio` | xz 压缩/解压支持 | 处理 xz 压缩文件 |
| `lzopio` | lzop 压缩/解压支持 | 处理 lzop 压缩文件 |
| `font` | 字体加载支持 | 加载图形终端字体 |
| `gettext` | 国际化支持 | 多语言界面 |

### 典型平台配置

**i386-pc 平台（传统 BIOS）：**
```bash
grub-mkimage -O i386-pc -o core.img -d /usr/lib/grub/i386-pc \
  ext2 part_msdos biosdisk normal linux search ls
```

**x86_64-efi 平台（UEFI）：**
```bash
grub-mkimage -O x86_64-efi -o core.efi -d /usr/lib/grub/x86_64-efi \
  ext2 part_gpt efi_gop normal linux search ls
```

### 模块定义文件

所有模块的定义位于构建系统配置文件中：

**源代码位置：** `grub/grub-core/Makefile.core.def`

**示例模块定义：**

```def
# ext2 模块
module = {
  name = ext2;
  common = fs/ext2.c;
};

# biosdisk 模块（仅 i386-pc 平台）
module = {
  name = biosdisk;
  i386_pc = disk/i386/pc/biosdisk.c;
  enable = i386_pc;
};

# linux 模块（x86 平台）
module = {
  name = linux;
  x86 = loader/i386/linux.c;
  i386_pc = lib/i386/pc/vesa_modes_table.c;
  ...
};
```

### 如何查看可用模块

**查看源代码目录：**

```bash
# 文件系统模块（42 个）
ls /path/to/grub/grub-core/fs/*.c

# 磁盘驱动模块（24 个）
ls /path/to/grub/grub-core/disk/*.c

# 分区表模块（11 个）
ls /path/to/grub/grub-core/partmap/*.c

# 加载器模块
ls /path/to/grub/grub-core/loader/*.c

# 命令模块
ls /path/to/grub/grub-core/commands/*.c
```

**查看已安装模块：**

```bash
ls /boot/grub/i386-pc/*.mod
```

### 相关文档

- **模块加载机制详解**：[GRUB_MODULE_LOADING_ANALYSIS.md](GRUB_MODULE_LOADING_ANALYSIS.md)
- **模块定义文件**：`grub/grub-core/Makefile.core.def`
- **模块加载代码**：`grub/grub-core/kern/main.c:58-75`
- **FOR_MODULES 宏**：`grub/include/grub/kernel.h:104-110`
- **数据结构**：`grub/include/grub/kernel.h:39-69`

