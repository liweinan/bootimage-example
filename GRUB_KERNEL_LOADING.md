# GRUB 加载 Linux 内核详细流程

本文档详细说明 GRUB 如何加载 Linux 内核镜像并跳转到内核入口点的完整过程，包括源代码分析和实现细节。

## 流程概述

从 `_start` 调用 `grub_main()` 后，GRUB 开始加载 Linux 内核的完整流程：

```
grub_main()（grub/grub-core/kern/main.c）
    ├─ 源代码位置：grub/grub-core/kern/main.c
    ├─ 解析 grub.cfg 配置文件
    ├─ 显示启动菜单（如果配置）
    ├─ 用户选择启动 Linux 内核
    └─ 执行 menuentry 中的命令：
        ↓
grub_cmd_linux()（执行 linux 命令）
    ├─ 源代码位置：grub/grub-core/loader/i386/linux.c:680-1062
    ├─ 加载内核镜像到内存（0x100000）
    ├─ 设置内核启动参数（boot_params）
    └─ 注册启动函数 grub_linux_boot()
        ↓
grub_cmd_initrd()（执行 initrd 命令，可选）
    ├─ 源代码位置：grub/grub-core/loader/i386/linux.c:1065-1166
    ├─ 读取 initrd 文件（支持多个文件和压缩格式）
    ├─ 分配内存（尽量放在高地址，4KB 对齐）
    ├─ 加载 initrd 到内存
    └─ 设置 boot_params.ramdisk_image 和 ramdisk_size
        ↓
用户按 Enter 选择启动项
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
    //   - 注册 GRUB 内核中的核心命令（仅 4 个基础命令）
    //   - 这些命令内置在 GRUB 内核中，无需加载模块即可使用
    //   - 详细说明见下方 "grub_register_core_commands() 函数详解"

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
- **注意**：`linux` 和 `initrd` 命令由 `linux.mod` 模块提供，在此步骤加载

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

**模块加载与命令注册机制：**

当执行 `insmod linux` 时，GRUB 如何知道该模块提供了哪些命令？

**1. 模块初始化宏（`GRUB_MOD_INIT`）：**

```c
// grub/include/grub/dl.h:43-46
#define GRUB_MOD_INIT(name)  \
static void grub_mod_init (grub_dl_t mod __attribute__ ((unused))) __attribute__ ((used)); \
static void \
grub_mod_init (grub_dl_t mod __attribute__ ((unused)))

// 展开后，linux.mod 中的代码：
static void grub_mod_init (grub_dl_t mod)
{
    cmd_linux = grub_register_command ("linux", grub_cmd_linux, ...);
    cmd_initrd = grub_register_command ("initrd", grub_cmd_initrd, ...);
}
```

**2. 模块加载流程（`grub_dl_load_core`）：**

```c
// grub/grub-core/kern/dl.c:805-821
grub_dl_t
grub_dl_load_core (void *addr, grub_size_t size)
{
    // 步骤 1: 解析 ELF 文件，但不初始化
    mod = grub_dl_load_core_noinit (addr, size);
    
    // 步骤 2: 调用模块初始化函数
    grub_dl_init (mod);  // ⚠️ 关键：这里调用 mod->init
    
    return mod;
}
```

**3. 符号解析（`grub_dl_resolve_symbols`）：**

```c
// grub/grub-core/kern/dl.c:437-440
// 在解析 ELF 符号表时，查找特殊函数名
if (grub_strcmp (name, "grub_mod_init") == 0)
    mod->init = (void (*) (grub_dl_t)) sym->st_value;  // 保存初始化函数地址
else if (grub_strcmp (name, "grub_mod_fini") == 0)
    mod->fini = (void (*) (void)) sym->st_value;       // 保存清理函数地址
```

**4. 模块初始化（`grub_dl_init`）：**

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

**完整调用链：**

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

**关键点：**
- **ELF 符号表**：模块是 ELF 格式文件，包含符号表
- **约定的函数名**：GRUB 通过查找固定的函数名 `grub_mod_init` 和 `grub_mod_fini` 来识别初始化/清理函数
- **自动调用**：模块加载完成后，自动调用初始化函数，初始化函数内部调用 `grub_register_command()` 注册命令

**`GRUB_MOD_INIT(name)` 的 `name` 参数说明：**

```c
// grub/include/grub/dl.h:43-46
// 动态加载模块时（insmod）：
#define GRUB_MOD_INIT(name)  \
static void grub_mod_init (grub_dl_t mod ...) ...
                ↑
        参数 name 被忽略！生成的函数名始终是 grub_mod_init
```

不同模块展开后都生成同名函数：

```c
// linux.mod 中：
GRUB_MOD_INIT(linux) { ... }
// 展开后 → static void grub_mod_init(grub_dl_t mod) { ... }

// ext2.mod 中：
GRUB_MOD_INIT(ext2) { ... }
// 展开后 → static void grub_mod_init(grub_dl_t mod) { ... }
```

每个 `.mod` 文件是独立编译的 ELF 文件，都有自己的 `grub_mod_init` 符号，互不冲突。

**`name` 参数的用途（仅静态链接时）：**

```c
// 当模块静态链接到 GRUB 内核时（#elif defined GRUB_KERNEL）：
#define GRUB_MOD_INIT(name)  \
void grub_##name##_init (void) { grub_mod_init (0); } \
static void grub_mod_init (...)

// 此时 GRUB_MOD_INIT(linux) 展开为：
void grub_linux_init (void) { grub_mod_init(0); }  // ← 用于内核显式调用
static void grub_mod_init (...) { ... }
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

注册的命令被添加到全局链表 `grub_command_list`，执行命令时通过 `grub_command_find()` 查找并调用对应的处理函数。

**5. `grub_parser_execute()` - 执行配置文件**

**功能：**
- 解析并执行 `grub.cfg` 配置文件
- **关键**：当遇到 `linux` 命令时，会调用 `grub_cmd_linux()` 加载内核

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
#    - 加载内核到高地址（0x100000 = 1MB，不会覆盖 GRUB）
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

menuentry "Linux Kernel (Debian Installer)" {
    set root='cd0'
    linux /boot/vmlinuz root=/dev/ram0 rw console=ttyS0,115200
    initrd /boot/initrd.img
}
# 说明：
# - console=ttyS0,115200 用于串口输出（QEMU 中可用 -serial stdio 查看）
# - 脚本下载的 "linux" 保存为 "vmlinuz"，"initrd.gz" 保存为 "initrd.img"
# - GRUB 可以自动处理压缩的 initrd 文件（gzip 格式）
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

**功能：** 逐行解析并执行配置文件（如 `grub.cfg`）中的命令。

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

**执行流程图：**

```
grub_parser_execute("grub.cfg 内容")
    │
    ├─ 逐行读取配置文件
    │   ├─ "set root='hd0,1'"
    │   │   └─ grub_env_set("root", "hd0,1")  // 设置环境变量
    │   │
    │   ├─ "menuentry 'Linux' { linux /vmlinuz; initrd /initrd.img }"
    │   │   └─ grub_cmd_menuentry()  // ⚠️ 只注册 menuentry，不执行内部命令
    │   │       └─ 将 menuentry 添加到菜单列表
    │   │
    │   └─ ... 其他命令 ...
    │
    └─ 返回（配置解析完成，显示菜单）

用户按 Enter 选择 menuentry 后：
    │
    └─ GRUB 执行该 menuentry 的命令
        ├─ "linux /vmlinuz" → grub_cmd_linux()
        ├─ "initrd /initrd.img" → grub_cmd_initrd()
        └─ 隐式 boot → grub_linux_boot()
```

**关键点：**

1. **配置文件解析时机**：
   - `grub_parser_execute()` 在 `grub_main()` 中执行
   - 解析 `grub.cfg` 时，**只是注册 menuentry**，不执行其中的命令
   - 用户在菜单界面选择并按 Enter 后，才执行所选 menuentry 中的命令

2. **menuentry 执行流程**：
   - 用户按 Enter 后，执行 `linux` 命令 → `grub_cmd_linux()` 加载内核到 0x100000（1MB）
   - 执行 `initrd` 命令 → `grub_cmd_initrd()` 加载 initramfs
   - menuentry 执行完毕后，GRUB 隐式调用 boot 命令
   - boot 命令调用 `grub_linux_boot()` → `grub_relocator32_boot()` 跳转到内核

3. **内存布局与 Relocator 机制**：
   - GRUB 解压后也在 0x100000（1MB），与内核目标地址相同
   - 内核**先被加载到 relocator 管理的临时缓冲区**（通常在 0x1000000 = 16MB 以上）
   - `boot` 命令执行时，relocator 代码被复制到**低内存**（0x1000-0x9a000）
   - 执行 relocator：将内核从临时位置复制到 0x100000，然后跳转
   - 此时 GRUB 代码被覆盖，但已不需要

**Relocator 数据结构（`grub-core/lib/relocator.c:56-65`）：**

```c
struct grub_relocator_chunk {
    grub_phys_addr_t src;     // 当前物理地址（临时位置）
    void *srcv;               // 当前虚拟地址（GRUB 访问用）
    grub_phys_addr_t target;  // 目标物理地址（最终位置）
    grub_size_t size;         // 大小
    // ...
};
```

**Relocator 分配逻辑（`grub-core/loader/i386/linux.c:172-202`）：**

```c
if (relocatable)
{
    // ⚠️ 问题 1：为什么还要尝试 preferred_address (0x100000)？
    // 虽然 GRUB 代码在 0x100000，但尝试这个地址有以下原因：
    // 1. 代码路径统一：可重定位内核可能不需要精确在 0x100000
    // 2. 兼容性：某些特殊系统配置可能允许在 0x100000 分配
    // 3. 理论上，如果 GRUB 代码已被清理或系统内存布局特殊，可能成功
    // 4. 实际运行中，这个尝试几乎总是失败，但代码逻辑保持统一
    // 第一次尝试：在 preferred_address (0x100000) 分配
    // min_addr = max_addr = 0x100000，表示只接受这个精确地址
    err = grub_relocator_alloc_chunk_align(relocator, &ch,
                                            preferred_address,  // min_addr = 0x100000
                                            preferred_address,  // max_addr = 0x100000
                                            prot_size, 1,
                                            GRUB_RELOCATOR_PREFERENCE_LOW, 1);
    
    // ⚠️ 问题 2：如何分析代码得出 16MB？
    // 代码中直接写的是 0x1000000，这就是 16MB：
    //   0x1000000 = 16 * 1024 * 1024 = 16,777,216 字节 = 16 MB
    // 选择 16MB 的原因：
    // 1. 避开 GRUB 代码区域（0x100000 到约 0x118000，约 1.1MB）
    // 2. 避开可能的系统保留区域（如 ACPI、BIOS 数据等）
    // 3. 16MB 是一个常见的"安全边界"，确保有足够空间
    // 4. 历史原因：早期 Linux 内核解压目标地址通常是 16MB
    // 如果失败，循环尝试在 16MB 以上分配（逐步降低对齐要求）
    for (; err && *align + 1 > min_align; (*align)--)
    {
        grub_errno = GRUB_ERR_NONE;
        err = grub_relocator_alloc_chunk_align(relocator, &ch,
                                                0x1000000,           // min_addr = 16MB (硬编码)
                                                UP_TO_TOP32(prot_size), // max_addr = 4GB - size
                                                prot_size, 1 << *align,
                                                GRUB_RELOCATOR_PREFERENCE_LOW, 1);
    }
}
else
{
    // 非可重定位内核：必须精确在 preferred_address (0x100000)
    // 这种情况下，如果 0x100000 被占用，分配会直接失败
    err = grub_relocator_alloc_chunk_align(relocator, &ch,
                                            preferred_address,  // min_addr = 0x100000
                                            preferred_address,  // max_addr = 0x100000
                                            prot_size, 1,
                                            GRUB_RELOCATOR_PREFERENCE_LOW, 1);
    // 如果失败，内核无法加载（非可重定位内核必须在这个地址）
}

prot_mode_mem = get_virtual_current_address(ch);    // 临时位置（src）
prot_mode_target = get_physical_target_address(ch); // 最终位置（target = 0x100000）
```

**`grub_relocator_alloc_chunk_align()` 内部逻辑（`grub-core/lib/relocator.c:1375-1508`）：**

```c
grub_relocator_alloc_chunk_align(rel, out, min_addr, max_addr, size, align, ...)
{
    // 步骤 1: 尝试在 [min_addr, max_addr] 范围内直接分配
    // 调用 malloc_in_range() 扫描 GRUB 内存管理器的空闲块
    if (malloc_in_range(rel, min_addr, max_addr, align, size, chunk, ...))
    {
        // 成功：src = target = 分配到的地址
        chunk->target = chunk->src;
        return GRUB_ERR_NONE;
    }
    
    // 步骤 2: 如果直接分配失败，调整范围避开已分配的 chunk
    adjust_limits(rel, &min_addr2, &max_addr2, min_addr, max_addr);
    
    // 步骤 3: 在调整后的范围内分配临时位置（src）
    malloc_in_range(rel, min_addr2, max_addr2, align, size, chunk, ...);
    
    // 步骤 4: 通过 mmap 迭代器查找合适的目标位置（target）
    // target 可能与 src 不同
    grub_mmap_iterate(grub_relocator_alloc_chunk_align_iter, &ctx);
    
    // 步骤 5: 如果 src != target，记录需要的 relocator 代码大小
    if (chunk->src < chunk->target)
        rel->relocators_size += grub_relocator_backward_size;
    if (chunk->src > chunk->target)
        rel->relocators_size += grub_relocator_forward_size;
}
```

**为什么在 0x100000 分配会失败？**

关键在于 GRUB 内存初始化时**根本不会将 0x100000 区域添加到空闲内存池**。

**GRUB 内存布局（`grub-core/kern/i386/pc/init.c`）：**

```
0x100000 ─────────────────────────────────┐
│ GRUB 代码（_start 到 _edata）            │ ← GRUB_MEMORY_MACHINE_DECOMPRESSION_ADDR
│ （解压后约 20-50 KB）                    │
├─ grub_modbase ─────────────────────────┤ ← 0x100000 + (_edata - _start)
│ GRUB 内置模块数据                        │   例如：0x100000 + 0x8000 = 0x108000
│ （大小取决于加载的模块数量）              │
├─ modend ───────────────────────────────┤ ← grub_modbase + modinfo->size
│                                         │   例如：0x108000 + 0x10000 = 0x118000（约 1.1MB）
│ 空闲内存（由 grub_mm_init_region 管理）  │ ← 只有这部分被添加到内存池！
└─────────────────────────────────────────┘

注意：modend 通常在 0x100000 + 几百 KB 范围内（约 1.1-1.5 MB），
      而不是 16MB。16MB 是 relocator 分配临时缓冲区时的最小地址。
```

**内存池初始化代码（`grub-core/kern/i386/pc/init.c:259-268`）：**

```c
// grub_machine_init() 中的关键代码
modend = grub_modules_get_end ();  // 获取 GRUB 模块的结束地址

for (i = 0; i < num_regions; i++)
{
    grub_addr_t beg = mem_regions[i].addr;
    grub_addr_t fin = mem_regions[i].addr + mem_regions[i].size;
    
    // ⚠️ 关键：将起始地址调整到 modend 之后
    if (modend && beg < modend)
        beg = modend;
    
    if (beg >= fin)
        continue;
    
    // 只初始化 modend 之后的区域为空闲内存
    grub_mm_init_region ((void *) beg, fin - beg);
}
```

**两个关键问题的详细解答：**

**问题 1：既然 GRUB 代码在 0x100000，为什么还要尝试 preferred_address？**

虽然 GRUB 代码确实在 0x100000，但代码仍会尝试在这个地址分配，原因如下：

1. **代码路径统一**：
   - 可重定位内核（`relocatable = true`）理论上可以在不同地址加载
   - 代码逻辑统一处理，先尝试首选地址，失败后再回退
   - 这样代码更简洁，不需要特殊判断

2. **兼容性考虑**：
   - 某些特殊系统配置可能允许在 0x100000 分配（例如 GRUB 代码已被清理）
   - 某些嵌入式系统或特殊引导场景可能有不同的内存布局
   - 保持代码的通用性，不假设所有情况都会失败

3. **实际运行情况**：
   - **在标准 PC 系统上，这个尝试几乎总是失败**（因为 GRUB 代码占用）
   - 但代码仍会执行这个尝试，然后立即回退到 16MB 以上
   - 性能影响可忽略（只是一次内存分配尝试）

4. **非可重定位内核的情况**：
   - 如果内核不可重定位（`relocatable = false`），必须精确在 0x100000
   - 这种情况下，如果 0x100000 被占用，分配会直接失败，内核无法加载
   - 可重定位内核的优势就是可以回退到其他地址

**问题 2：如何分析代码得出 16MB？**

16MB 是**硬编码在源代码中的值**，分析过程如下：

1. **源代码位置**：
   ```c
   // grub-core/loader/i386/linux.c:805
   err = grub_relocator_alloc_chunk_align(relocator, &ch,
                                           0x1000000,  // ← 这里就是 16MB
                                           UP_TO_TOP32(prot_size),
                                           ...);
   ```

2. **数值计算**：
   ```
   0x1000000 = 16 * 1024 * 1024 = 16,777,216 字节 = 16 MB
   ```

3. **为什么选择 16MB？**
   - **避开 GRUB 区域**：GRUB 代码在 0x100000 到约 0x118000（约 1.1MB），16MB 远高于此
   - **避开系统保留区域**：BIOS 可能在某些低地址区域保留内存（如 ACPI、BIOS 数据等）
   - **安全边界**：16MB 是一个常见的"安全边界"，确保有足够的连续内存空间
   - **历史原因**：早期 Linux 内核解压目标地址通常是 16MB（`CONFIG_PHYSICAL_START` 默认值）
   - **对齐考虑**：16MB 是 2^24，便于内存对齐和地址计算

4. **代码分析步骤**：
   - 在 GRUB 源代码中搜索 `0x1000000`
   - 找到 `grub-core/loader/i386/linux.c` 中的分配逻辑
   - 查看上下文，理解这是 fallback 地址
   - 计算 `0x1000000` 的十进制值：16 * 1024 * 1024 = 16 MB

5. **实际验证**：
   - 可以通过调试 GRUB 或查看内存映射来验证
   - 在 GRUB 命令行执行 `lsmem` 或查看内存布局
   - 确认临时缓冲区确实在 16MB 以上

**`grub_modules_get_end()` 实现（`grub-core/kern/main.c:44-54`）：**

```c
grub_addr_t
grub_modules_get_end (void)
{
    modinfo = (struct grub_module_info *) grub_modbase;
    if ((modinfo == 0) || modinfo->magic != GRUB_MODULE_MAGIC)
        return grub_modbase;
    return grub_modbase + modinfo->size;  // GRUB 模块结束地址
}
```

**`grub_modbase` 初始化（`grub-core/kern/i386/pc/init.c:229`）：**

```c
grub_modbase = GRUB_MEMORY_MACHINE_DECOMPRESSION_ADDR + (_edata - _start);
// = 0x100000 + GRUB 代码大小
```

**总结**：0x100000 到 `modend` 之间的区域**从未被 `grub_mm_init_region()` 添加到空闲内存池**，
所以 `malloc_in_range()` 在扫描空闲块列表时找不到这个区域，分配自然失败。

**Relocator 内存布局总结：**

| 项目 | 位置 | 说明 |
|------|------|------|
| **临时缓冲区** | 通常 0x1000000 (16MB) 以上 | 因为 GRUB 占用 0x100000 |
| **最终目标** | 0x100000 (1MB) | `GRUB_LINUX_BZIMAGE_ADDR` |
| **大小** | `prot_size`（内核压缩大小） | 由内核头部 `init_size` 字段决定 |

### grub_cmd_linux() 函数

**源代码位置：** `grub/grub-core/loader/i386/linux.c:680-725`

**功能：**
- 打开内核文件（如 `/boot/vmlinuz-5.x.x`）
- 解析内核头部，验证内核签名
- 通过 relocator 分配临时缓冲区（通常在 16MB 以上），加载内核到临时位置
- 设置内核启动参数（`boot_params`）
- 注册启动函数 `grub_linux_boot()`（boot 时将内核从临时位置复制到 0x100000）

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
    
    // 步骤 8: 通过 relocator 分配内存
    // ⚠️ 关键：内核不是直接加载到 0x100000，而是加载到临时缓冲区
    // 因为 GRUB 代码也在 0x100000，需要避免覆盖
    allocate_pages (prot_size, &align, min_align, relocatable, preferred_address);
    // allocate_pages 内部调用 grub_relocator_alloc_chunk_align()：
    //   1. 首先尝试在 preferred_address (0x100000) 分配
    //      - 对于可重定位内核：这个尝试几乎总是失败（GRUB 代码占用）
    //      - 但代码仍会尝试，保持逻辑统一和兼容性
    //   2. 如果失败，则在 0x1000000 (16MB) 以上分配
    //      - 0x1000000 = 16 * 1024 * 1024 = 16 MB（硬编码在源代码中）
    //      - 选择 16MB 的原因：避开 GRUB 区域，避开系统保留区域，历史原因
    // 返回两个地址：
    //   - prot_mode_mem：临时缓冲区地址（GRUB 用于写入数据，通常在 16MB+）
    //   - prot_mode_target：最终目标地址（0x100000，boot 时 relocator 复制到此）
    
    // 步骤 9: 复制内核到临时缓冲区（不是最终位置！）
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
0x100000 - 0x1FFFFF      内核镜像（vmlinuz）
0x200000 - ...           内核解压区域
...
0x2F000000 - 0x2FFFFFFF  initrd（尽量在高地址）
                         ↑ ramdisk_image 指向这里
```

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

**函数实现（`grub/grub-core/commands/boot.c:163-174`）：**

```c
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
    initrd /boot/initrd.img-5.x.x
}

# 用户按 Enter 选择后，执行顺序：
# 1. linux 命令 → grub_cmd_linux() 加载内核到 0x100000
# 2. initrd 命令 → grub_cmd_initrd() 加载 initramfs
# 3. menuentry 结束后隐式 boot → grub_linux_boot() → grub_relocator32_boot()
# 4. 跳转到内核入口点（code32_start）
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

**源代码位置：** `grub/grub-core/lib/i386/relocator.c:75-117`

**功能：**
- 设置寄存器值（`grub_relocator32_eip`、`grub_relocator32_esi`）
- 准备 relocator 代码（切换到实模式并跳转）
- 执行跳转到内核入口点（`code32_start`）

**完整源代码分析：**

```c
// grub/grub-core/lib/i386/relocator.c
grub_relocator32_boot (struct grub_relocator *rel, struct grub_relocator32_state state, ...)
{
    // 步骤 1: 在安全区域（0x1000-0x9a000）分配内存
    // 这个区域在 1MB 以下，不会被加载到 0x100000+ 的内核覆盖
    err = grub_relocator_alloc_chunk_align_safe (rel, &ch,
        0x1000,   // 最小地址
        0x9a000,  // 最大地址（1MB 以下的安全区域）
        RELOCATOR_SIZEOF (32),  // relocator 代码大小
        16,       // 对齐
        GRUB_RELOCATOR_PREFERENCE_LOW,
        avoid_efi_bootservices);
    
    relocator_mem = get_virtual_current_address (ch);  // 获取安全区域的虚拟地址
    
    // 步骤 2: 设置寄存器值
    // grub_relocator32_eip 是 relocator 代码中的一个全局变量
    // 用于存储目标跳转地址，relocator 代码执行时会读取这个变量并加载到 EIP
    grub_relocator32_eip = state.eip;  // 内核入口点地址（code32_start）
    grub_relocator32_esi = state.esi;  // boot_params 地址
    
    // 步骤 3: 将 relocator 代码复制到安全区域
    // ⚠️ 关键问题 1：relocator 代码具体对应哪个文件？
    // 答案：grub/grub-core/lib/i386/relocator32.S
    // 这是一个汇编文件，包含切换到实模式并跳转到内核的代码
    // &grub_relocator32_start 是这段代码在 GRUB 内存中的起始地址
    grub_memmove (relocator_mem, &grub_relocator32_start, RELOCATOR_SIZEOF (32));
    
    // 步骤 4: 执行跳转（关闭中断，跳转到安全区域的 relocator 代码）
    asm volatile ("cli");
    ((void (*) (void)) relocator_mem) ();  // 跳转到安全区域的 relocator 代码
    // relocator 代码会：
    //   1. 切换到实模式（从保护模式切换回来）
    //   2. 设置段寄存器（CS、DS、ES、SS）
    //   3. 设置栈指针（ESP）
    //   4. 从 grub_relocator32_eip 读取地址并加载到 EIP 寄存器
    //   5. 执行远跳转（ljmp）到内核入口点（code32_start）
    //   6. 此时 ESI 寄存器包含 boot_params 的地址
}
```

**⚠️ 关键问题解答：**

**问题 1：relocator 代码具体对应哪个文件？**

**答案：** `grub/grub-core/lib/i386/relocator32.S`

这是一个汇编源文件，包含以下关键功能：
- 从保护模式切换到实模式
- 设置段寄存器（CS、DS、ES、SS）为实模式值
- 设置栈指针（ESP）
- 从全局变量读取目标地址（`grub_relocator32_eip`）
- 执行远跳转（`ljmp`）到内核入口点

**源代码位置：** `grub/grub-core/lib/i386/relocator32.S`

**问题 2：为什么要复制？**

**答案：** 因为 GRUB 的代码在 0x100000+，会被内核覆盖，必须复制到安全区域。

**详细原因：**

1. **GRUB 代码位置问题**：
   - GRUB 解压后的代码在 `0x100000+`（1MB 以上）
   - 内核镜像也加载到 `0x100000`（1MB）
   - **内核会覆盖 GRUB 的代码区域**

2. **执行时机问题**：
   - `grub_relocator32_boot()` 在保护模式下执行（GRUB 的 C 代码）
   - 需要切换到实模式才能跳转到内核（内核入口点是实模式代码）
   - 切换代码本身也在 `0x100000+`，如果直接执行，执行过程中可能被覆盖

**⚠️ UEFI 启动方式完全不同：**

**UEFI 不需要 relocator 机制**，原因如下：

1. **运行模式不同**：
   - **BIOS 启动**：GRUB 在保护模式下运行，内核入口点是实模式代码，需要模式切换
   - **UEFI 启动**：GRUB 和内核都在保护模式/长模式下运行，不需要模式切换

2. **启动方式不同**：
   - **BIOS 启动**：使用 relocator 代码手动跳转到内核入口点
   - **UEFI 启动**：使用 EFI 的 `StartImage` 服务（`grub_efi_system_table->boot_services->start_image()`）

3. **源代码位置**：
   - **BIOS 启动**：`grub/grub-core/loader/i386/linux.c` → `grub_relocator32_boot()`
   - **UEFI 启动**：`grub/grub-core/loader/efi/linux.c` → `grub_arch_efi_linux_boot_image()` → `grub_efi_start_image()`

4. **UEFI 启动流程**（`grub/grub-core/loader/efi/linux.c:194-280`）：
   ```c
   grub_arch_efi_linux_boot_image (grub_addr_t addr, grub_size_t size, char *args)
   {
       // 步骤 1: 创建内存映射设备路径
       mempath = grub_malloc (2 * sizeof (grub_efi_memory_mapped_device_path_t));
       mempath[0].start_address = addr;  // 内核地址
       mempath[0].end_address = addr + size;
       
       // 步骤 2: 使用 EFI LoadImage 服务加载内核
       status = grub_efi_load_image (0, grub_efi_image_handle,
                                     (grub_efi_device_path_t *) mempath,
                                     (void *) addr, size, &image_handle);
       
       // 步骤 3: 设置命令行参数（转换为 UTF-16）
       loaded_image = grub_efi_get_loaded_image (image_handle);
       loaded_image->load_options = ...;  // 内核命令行参数
       
       // 步骤 4: 使用 EFI StartImage 服务启动内核
       // ⚠️ 关键：这是 EFI 固件提供的服务，不需要 relocator
       status = grub_efi_start_image (image_handle, 0, NULL);
       // 如果成功，不会返回（控制权转移到内核）
   }
   ```

5. **为什么 UEFI 不需要 relocator？**
   - **EFI 服务处理**：`StartImage` 服务由 EFI 固件实现，负责：
     - 设置正确的 CPU 状态（寄存器、段、分页等）
     - 准备内核执行环境
     - 跳转到内核入口点
   - **内存管理**：EFI 使用 `ExitBootServices()` 将内存控制权交给内核，GRUB 代码可以被覆盖
   - **标准协议**：UEFI 定义了标准的启动协议，内核以 EFI 可执行文件格式加载

6. **对比总结**：

| 特性 | BIOS 启动 | UEFI 启动 |
|------|----------|----------|
| **GRUB 运行模式** | 保护模式 | 保护模式/长模式 |
| **内核入口点模式** | 实模式 | 保护模式/长模式 |
| **是否需要模式切换** | ✅ 是（保护→实） | ❌ 否 |
| **跳转方式** | relocator 代码手动跳转 | EFI `StartImage` 服务 |
| **relocator 机制** | ✅ 需要 | ❌ 不需要 |
| **源代码文件** | `loader/i386/linux.c` | `loader/efi/linux.c` |
| **关键函数** | `grub_relocator32_boot()` | `grub_efi_start_image()` |

3. **安全区域选择**：
   - 安全区域：`0x1000-0x9a000`（1MB 以下的常规内存）
   - 这个区域不会被加载到 `0x100000+` 的内核覆盖
   - 复制 relocator 代码到这里，确保执行时不会被覆盖

4. **自包含代码**：
   - relocator 代码是自包含的，包含完整的 GDT 和跳转指令
   - 不依赖 GRUB 的其他代码，可以独立执行
   - 复制后，即使原始代码被覆盖也不影响执行

**问题 3：直接跳转到内核入口点地址（code32_start）不行吗？**

**答案：** 不行。原因如下：

1. **运行模式不匹配**：
   - GRUB 在**保护模式**下运行（32 位保护模式）
   - 内核入口点（`code32_start`）是**实模式**代码
   - 不能直接从保护模式跳转到实模式代码，需要先切换模式

2. **段寄存器状态不正确**：
   - 保护模式下，段寄存器是段选择子（指向 GDT 中的段描述符）
   - 实模式下，段寄存器是段基址（直接用于地址计算）
   - 跳转前必须设置正确的段寄存器值

3. **分页可能启用**：
   - GRUB 可能启用了分页（页表映射）
   - 内核入口点期望在实模式下运行（无分页）
   - 需要禁用分页

4. **栈和寄存器状态**：
   - 内核期望特定的寄存器状态（如 `ESI` 包含 `boot_params` 地址）
   - 需要设置正确的栈指针（ESP）
   - relocator 代码负责设置这些状态

**relocator 代码的作用：**

relocator 代码是一个"桥梁"，负责：
1. **模式切换**：从保护模式切换到实模式
2. **环境准备**：设置段寄存器、栈指针、寄存器状态
3. **安全跳转**：从安全区域执行，确保不被覆盖
4. **参数传递**：确保 `ESI` 寄存器包含 `boot_params` 地址

**如果直接跳转会发生什么？**

```c
// ❌ 错误做法：直接跳转
asm volatile ("jmp *%0" : : "r" (code32_start));

// 问题：
// 1. 仍在保护模式下，段寄存器是选择子，不是实模式段基址
// 2. 如果启用了分页，地址映射可能不正确
// 3. 寄存器状态（ESI、ESP）可能不正确
// 4. 内核期望实模式环境，但仍在保护模式下
// 结果：系统崩溃或不可预测的行为
```

**正确的流程：**

```
GRUB 保护模式代码（0x100000+）
    ↓
复制 relocator 代码到安全区域（0x1000-0x9a000）
    ↓
跳转到安全区域的 relocator 代码
    ↓
relocator 代码执行：
    1. 切换到实模式
    2. 设置段寄存器（CS、DS、ES、SS）
    3. 设置栈指针（ESP）
    4. 设置 ESI = boot_params 地址
    5. 执行 ljmp 跳转到 code32_start
    ↓
内核入口点（code32_start @ 0x100000，实模式）
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

**⚠️ 关键问题：内核覆盖 GRUB 代码后如何完成跳转？**

内核被加载到 0x100000+，这与 GRUB 解压后的代码区域重叠。GRUB 通过 **relocator 机制** 解决这个问题：

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
内核入口点（code32_start @ 0x100000）
```

**内存布局关键点：**

```
0x0000 - 0x03FF      IVT（中断向量表）
0x0400 - 0x04FF      BDA（BIOS 数据区）
0x1000 - 0x9A000     ⚠️ 安全区域（relocator 代码在此执行）
0x7C00 - 0x7DFF      引导扇区
0x8000 - 0xFFFF      GRUB 实模式代码（startup_raw.S 等）
0x100000+            GRUB 保护模式代码（会被内核覆盖）
0x100000+            内核镜像（覆盖 GRUB 代码）
```

**为什么这个机制有效：**

1. **安全区域选择**：0x1000-0x9a000 是 1MB 以下的常规内存，不会被加载到 0x100000+ 的内核覆盖
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

