# 关键源代码文件索引

> **相关文档**：本文档是 [BOOT_FLOW.md](BOOT_FLOW.md) 的补充文档，提供了启动流程中涉及的关键源代码文件位置索引，方便快速查找。

本文档涉及的关键源代码文件位置索引，方便快速查找：

## QEMU 源代码

| 文件路径 | 功能说明 | 相关章节 |
|---------|---------|---------|
| `qemu/hw/i386/pc_sysfw.c:215-285` | 系统固件初始化，加载 SeaBIOS | [QEMU 加载 SeaBIOS](BOOT_FLOW.md#qemu-加载-seabios) |
| `qemu/hw/i386/x86-common.c:1027-1092` | x86 平台初始化 | [QEMU 加载 SeaBIOS](BOOT_FLOW.md#qemu-加载-seabios) |
| `qemu/target/i386/cpu.c:9130-9149` | CPU 复位向量设置（0xFFFF0） | [QEMU 加载 SeaBIOS](BOOT_FLOW.md#qemu-加载-seabios) |

## SeaBIOS 源代码

| 文件路径 | 功能说明 | 相关章节 |
|---------|---------|---------|
| `seabios/src/romlayout.S:687-690` | reset_vector 定义（ORG 0xfff0） | [Reset Vector 设置机制](BOOT_FLOW.md#reset-vector-设置机制) |
| `seabios/src/romlayout.S:589-591` | ORG 宏定义 | [Reset Vector 设置机制](BOOT_FLOW.md#reset-vector-设置机制) |
| `seabios/scripts/layoutrom.py:74-82` | 链接器脚本处理固定地址段 | [Reset Vector 设置机制](BOOT_FLOW.md#reset-vector-设置机制) |
| `seabios/src/post.c:302-337` | POST 主入口点 | [SeaBIOS 初始化中断服务](BOOT_FLOW.md#seabios-初始化中断服务) |
| `seabios/src/post.c:196-235` | maininit() 主初始化函数 | [SeaBIOS 初始化中断服务](BOOT_FLOW.md#seabios-初始化中断服务) |
| `seabios/src/post.c:32-71` | ivt_init() IVT 初始化 | [SeaBIOS 初始化中断服务](BOOT_FLOW.md#seabios-初始化中断服务) |
| `seabios/src/hw/pic.c:62-66` | pic_setup() PIC 初始化 | [SeaBIOS 初始化中断服务](BOOT_FLOW.md#seabios-初始化中断服务) |
| `seabios/src/post.c:137-158` | interface_init() 接口初始化 | [SeaBIOS 初始化中断服务](BOOT_FLOW.md#seabios-初始化中断服务) |
| `seabios/src/post.c:182-193` | startBoot() 启动引导 | [BIOS 引导流程：从 SeaBIOS 到引导扇区](BOOT_FLOW.md#bios-引导流程从-seabios-到引导扇区) |
| `seabios/src/boot.c:1040-1046` | handle_19() INT 19h 处理程序 | [BIOS 引导流程：从 SeaBIOS 到引导扇区](BOOT_FLOW.md#bios-引导流程从-seabios-到引导扇区) |
| `seabios/src/boot.c:882-917` | boot_disk() 读取引导扇区 | [BIOS 引导流程：从 SeaBIOS 到引导扇区](BOOT_FLOW.md#bios-引导流程从-seabios-到引导扇区) |
| `seabios/src/boot.c:987-1025` | do_boot() 引导设备选择 | [BIOS 引导流程：从 SeaBIOS 到引导扇区](BOOT_FLOW.md#bios-引导流程从-seabios-到引导扇区) |

## GRUB 源代码

| 文件路径 | 功能说明 | 相关章节 |
|---------|---------|---------|
| `grub/grub-core/boot/i386/pc/boot.S` | GRUB 引导扇区代码 | [BIOS 引导流程：从 SeaBIOS 到引导扇区](BOOT_FLOW.md#bios-引导流程从-seabios-到引导扇区) |
| `grub/grub-core/boot/i386/pc/diskboot.S:38-341` | 磁盘引导代码 | [BIOS 引导流程：从 SeaBIOS 到引导扇区](BOOT_FLOW.md#bios-引导流程从-seabios-到引导扇区) |
| `grub/grub-core/boot/i386/pc/startup_raw.S:76-104` | 启动代码 | [BIOS 引导流程：从 SeaBIOS 到引导扇区](BOOT_FLOW.md#bios-引导流程从-seabios-到引导扇区) |
| `grub/grub-core/kern/i386/realmode.S:133-195` | 实模式支持代码 | [BIOS 引导流程：从 SeaBIOS 到引导扇区](BOOT_FLOW.md#bios-引导流程从-seabios-到引导扇区) |
| `grub/grub-core/loader/i386/linux.c` | Linux 内核加载器 | [GRUB 加载 Linux 内核](BOOT_FLOW.md#grub-加载-linux-内核) |

## Linux 内核源代码

| 文件路径 | 功能说明 | 相关章节 |
|---------|---------|---------|
| `linux/arch/x86/boot/compressed/head_64.S` | 内核早期入口点 | [GRUB 加载 Linux 内核](BOOT_FLOW.md#grub-加载-linux-内核) |
| `linux/arch/x86/kernel/head64.c:1932` | x86_64_start_kernel() 入口 | [GRUB 加载 Linux 内核](BOOT_FLOW.md#grub-加载-linux-内核) |
| `linux/arch/x86/kernel/idt.c:216-227` | idt_setup_early_traps() 早期 IDT 设置 | [GRUB 加载 Linux 内核](BOOT_FLOW.md#grub-加载-linux-内核) |
| `linux/arch/x86/kernel/idt.c:281-315` | idt_setup_apic_and_irq_gates() 完成 IDT 设置 | [GRUB 加载 Linux 内核](BOOT_FLOW.md#grub-加载-linux-内核) |
| `linux/arch/x86/kernel/i8259.c:349-399` | init_8259A() PIC 重新编程 | [GRUB 加载 Linux 内核](BOOT_FLOW.md#grub-加载-linux-内核) |

## 用户代码示例

| 文件路径 | 功能说明 | 相关章节 |
|---------|---------|---------|
| `boot.asm` | 最小化引导扇区程序示例 | [BIOS 引导流程：从 SeaBIOS 到引导扇区](BOOT_FLOW.md#bios-引导流程从-seabios-到引导扇区) |

## 关键数据结构

| 数据结构 | 位置 | 说明 |
|---------|------|------|
| **IVT（中断向量表）** | `0x0000:0x0000` | BIOS 中断向量表，256 个条目，每个 4 字节 |
| **IDT（中断描述符表）** | 内核内存 | 内核中断描述符表，替代 BIOS IVT |
| **GDT（全局描述符表）** | 内核内存 | 全局描述符表，用于保护模式 |
| **boot_params** | 内核内存 | Linux 内核启动参数结构 |
