# GRUB 加载 Linux 内核详细流程

本文档详细说明 GRUB 如何加载 Linux 内核镜像并跳转到内核入口点的完整过程，包括源代码分析和实现细节。

## GRUB 加载内核的详细流程

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

