# 完整流程时间线

以下是从 QEMU 启动到 Linux 内核完全接管系统的完整流程时间线：

> **相关文档**：本文档是 [BOOT_FLOW.md](BOOT_FLOW.md) 的补充文档，详细说明了从 QEMU 到 Linux 内核的完整执行流程。

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
    │   └─ %esi 指向解压后的代码（_start）
    ↓
【阶段 3.5】解压后的代码入口点（_start）
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

## 关键文件路径和源代码位置

| 阶段 | 文件 | 源代码位置 | 内存地址 | 运行模式 |
|------|------|-----------|---------|---------|
| **阶段 1** | boot.S | `grub/grub-core/boot/i386/pc/boot.S` | `0x7C00` | 实模式 |
| **阶段 2** | diskboot.S | `grub/grub-core/boot/i386/pc/diskboot.S` | `0x8000` | 实模式 |
| **阶段 3** | startup_raw.S | `grub/grub-core/boot/i386/pc/startup_raw.S` | `0x8200` | 实模式→保护模式 |
| | lzma_decode.S | `grub/grub-core/boot/i386/pc/lzma_decode.S` | `0x8200+` | 实模式→保护模式 |
| | | （通过 `#include` 包含在 startup_raw.S 中，随 startup_raw.S 一起在阶段 2 加载） | | |
| **阶段 3.5** | 解压后的代码入口点 | 解压后的代码（通常是 _start） | 解压后地址 | 保护模式 |
| **阶段 4** | grub_main() | `grub/grub-core/kern/main.c` | 解压后地址 | 保护模式 |
| **阶段 5** | Setup 代码 | `linux/arch/x86/boot/header.S` | `0x100000` | 实模式 |
| **阶段 6** | head_64.S（解压） | `linux/arch/x86/boot/compressed/head_64.S` | `0x100000+` | 长模式 |
| **阶段 7** | startup_64 | `linux/arch/x86/kernel/head_64.S` | 解压后地址 | 长模式 |
| **阶段 8** | x86_64_start_kernel() | `linux/arch/x86/kernel/head64.c` | 内核地址空间 | 长模式 |
| **阶段 9** | start_kernel() | `linux/init/main.c` | 内核地址空间 | 长模式 |

## 关键时间节点

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
