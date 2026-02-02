# 引导扇区编程示例项目

这是一个简单的引导扇区程序示例，演示了如何在裸机上运行代码。

<img width="2296" height="1410" alt="fe4f9ff229c104aee6d03f53d2dbee6c" src="https://github.com/user-attachments/assets/170fbdec-6b11-4e7a-8272-fccfcdb35d1e" />


## 前置要求

在 Ubuntu Linux 上，需要安装以下工具：

```bash
# 安装 NASM 汇编器
sudo apt update
sudo apt install nasm

# 安装 QEMU 虚拟机
sudo apt install qemu-system-x86
```

## 使用方法

### 方法一：使用 Makefile（推荐）

```bash
# 编译
make build

# 运行（图形窗口模式，如果有图形界面）
make run
# 或者
make run-gui

# 运行（终端模式，适合 SSH 或无图形界面）
make run-term

# 清理
make clean
```

### 方法二：手动编译和运行

```bash
# 编译
nasm -f bin boot.asm -o boot.bin

# 在 QEMU 图形窗口中运行
# 在 VNC 环境中，需要先设置 DISPLAY 环境变量：
# export DISPLAY=:1
qemu-system-x86_64 -drive format=raw,file=boot.bin

# 在终端中运行（适合 SSH 或无图形界面）
qemu-system-x86_64 -display curses -drive format=raw,file=boot.bin
```

## 程序说明

`boot.asm` 是一个最小的引导扇区程序，它会：

1. 设置 80x25 文本显示模式
2. 在屏幕上显示 "Hello from Boot Sector!"
3. 进入无限循环（halt）

## 查看输出

### 图形窗口模式
如果使用 `make run` 或 `make run-gui`，QEMU 会打开一个图形窗口显示输出。

**在 VNC 环境中运行：**
如果使用 VNC server（如 `vncserver :1`），需要设置 DISPLAY 环境变量：
```bash
export DISPLAY=:1
make run-gui
```

或者在启动 VNC 后，在同一个终端会话中直接运行：
```bash
DISPLAY=:1 make run-gui
```

**如果看不到窗口：**
- 检查 DISPLAY 环境变量：`echo $DISPLAY`（应该显示 `:1` 或类似值）
- 检查是否有图形界面（X11/Wayland）
- 如果在 SSH 会话中，需要 X11 转发（`ssh -X`）
- 或者使用终端模式：`make run-term`

### 终端模式
如果使用 `make run-term` 或 `-display curses` 选项，输出会直接显示在终端中，适合：
- SSH 远程连接
- 无图形界面的服务器
- 需要直接在终端查看输出的情况

## 退出 QEMU

### 图形窗口模式
- 按 `Ctrl+Alt+G` 释放鼠标，然后关闭窗口
- 或按 `Ctrl+Alt+Q` 退出 QEMU

### 终端模式
**退出方法（重要）：**
1. **按 `Ctrl+A`，然后松开，再按 `X`（大写）** - 这是最常用的退出方法
2. **如果方法1不起作用，尝试：**
   - 按 `Ctrl+A`，然后按 `C` 进入 QEMU 监控器，输入 `quit` 后按回车
   - 或者按 `Ctrl+A`，然后按 `H` 查看帮助信息

**注意：** 
- 必须先按 `Ctrl+A`，松开后再按其他键
- `X` 必须是大写（Shift+X）
- 如果终端没有响应，可能需要先按 `Ctrl+A` 来"唤醒" QEMU 监控模式

## 注意事项

- 这个程序在真实的物理机器上运行可能会损坏数据，请只在虚拟机中测试
- 引导扇区必须是 512 字节，最后两个字节必须是 `0xAA55`
- 程序运行在 16 位实模式下

## 文档目录

本项目包含大量关于 BIOS、中断、内存管理等底层系统编程的详细文档：

### 核心概念文档

- **[GUIDE.md](GUIDE.md)** - 计算机中断机制完全指南：从汇编到硬件实现
- **[X86_CPU_MODES.md](X86_CPU_MODES.md)** - x86 CPU 运行模式详解（实模式、保护模式、长模式）
- **[A20_ADDRESS_LINE.md](A20_ADDRESS_LINE.md)** - A20 地址线详解

### BIOS 相关文档

- **[BIOS_MEMORY_LAYOUT.md](BIOS_MEMORY_LAYOUT.md)** - BIOS 内存布局与地址映射详解
- **[BIOS_MEMORY_QA.md](BIOS_MEMORY_QA.md)** - BIOS 内存相关问答
- **[BIOS_CODE_LAYOUT_ANALYSIS.md](BIOS_CODE_LAYOUT_ANALYSIS.md)** - BIOS 代码布局分析
- **[BIOS_INTERRUPT_COMPLETE.md](BIOS_INTERRUPT_COMPLETE.md)** - BIOS 中断完整文档
- **[BIOS_IVT_VS_KERNEL_IDT.md](BIOS_IVT_VS_KERNEL_IDT.md)** - BIOS IVT 与 Linux 内核 IDT 对比
- **[BIOS_SIZE.md](BIOS_SIZE.md)** - BIOS 大小与映射关系详解
- **[BIOS_VERIFICATION_REPORT.md](BIOS_VERIFICATION_REPORT.md)** - BIOS 固定地址验证报告

### SeaBIOS 相关文档

- **[FILL_SEABIOS_ANALYSIS.md](FILL_SEABIOS_ANALYSIS.md)** - SeaBIOS 与 Linux 内核地址转换机制对比分析
- **[SEABIOS_PROTECTION_MODE_CODE.md](SEABIOS_PROTECTION_MODE_CODE.md)** - SeaBIOS 保护模式代码的真正用途
- **[SEABIOS_ENTRY_13_ANALYSIS.md](SEABIOS_ENTRY_13_ANALYSIS.md)** - SeaBIOS INT 13h 入口分析
- **[SEABIOS_HANDLE_POST_ENTRY.md](SEABIOS_HANDLE_POST_ENTRY.md)** - SeaBIOS handle_post 入口分析

### 启动流程文档

- **[BOOT_FLOW.md](BOOT_FLOW.md)** - 计算机启动流程详解（从 QEMU 到 Linux 内核的完整流程）
- **[BOOT_FLOW_NOTES.md](BOOT_FLOW_NOTES.md)** - 启动流程笔记
- **[BOOT_FLOW_QA.md](BOOT_FLOW_QA.md)** - 启动流程问答
- **[BOOT_FLOW_TIMELINE.md](BOOT_FLOW_TIMELINE.md)** - 启动流程完整时间线（从 QEMU 启动到 Linux 内核接管的详细时间序列）
- **[BOOT_FLOW_SOURCE_INDEX.md](BOOT_FLOW_SOURCE_INDEX.md)** - 启动流程关键源代码文件索引
- **[BOOTSECTOR_EXAMPLE.md](BOOTSECTOR_EXAMPLE.md)** - 最小引导扇区程序示例
- **[BOOTSECTOR_COMPARISON.md](BOOTSECTOR_COMPARISON.md)** - 引导扇区对比分析
- **[SEABIOS_LOAD_BOOT_SECTOR.md](SEABIOS_LOAD_BOOT_SECTOR.md)** - SeaBIOS 如何加载引导扇区到 0x7C00
- **[DISK_TO_MEMORY_TRANSFER.md](DISK_TO_MEMORY_TRANSFER.md)** - 磁盘数据拷贝到内存的详细过程（PIO/DMA）
- **[BOOT_SECTOR_ANALYSIS.md](BOOT_SECTOR_ANALYSIS.md)** - 引导扇区代码手工分析指南
- **[CALL_BOOT_ENTRY_EXPLANATION.md](CALL_BOOT_ENTRY_EXPLANATION.md)** - call_boot_entry 函数详细解释

### GRUB 引导加载程序文档

- **[GRUB_CORE_IMG_STRUCTURE.md](GRUB_CORE_IMG_STRUCTURE.md)** - GRUB core.img 结构与构建详解（grub-mkimage、块列表机制、内存布局）
- **[GRUB_ISO_ANALYSIS.md](GRUB_ISO_ANALYSIS.md)** - GRUB ISO 镜像引导分析（boot.S、core.img 位置、内存布局等）
- **[GRUB_ISO_BOOT_FILES.md](GRUB_ISO_BOOT_FILES.md)** - GRUB ISO 镜像中哪些文件在 boot 阶段被加载
- **[GRUB_KERNEL_ADDR_ANALYSIS.md](GRUB_KERNEL_ADDR_ANALYSIS.md)** - GRUB_BOOT_MACHINE_KERNEL_ADDR = 0x8000 的计算和设计原因分析
- **[GRUB_BIOS_INTERRUPT_USAGE.md](GRUB_BIOS_INTERRUPT_USAGE.md)** - GRUB 在保护模式下调用 BIOS 服务的使用场景
- **[GRUB_MODE_SWITCHING.md](GRUB_MODE_SWITCHING.md)** - GRUB 模式切换函数详解（real_to_prot、prot_to_real 实现细节）
- **[GRUB_KERNEL_LOADING.md](GRUB_KERNEL_LOADING.md)** - GRUB 加载 Linux 内核详细流程（grub_cmd_linux、grub_linux_boot、grub_relocator32_boot 源代码分析）
- **[GRUB_STARTUP_RAW_TO_STARTUP_PROOF.md](GRUB_STARTUP_RAW_TO_STARTUP_PROOF.md)** - GRUB startup_raw.S 解压后跳转到 startup.S 的证明（源代码分析、链接顺序、寄存器状态）
- **[GRUB_I386_PC_STARTUP_USAGE.md](GRUB_I386_PC_STARTUP_USAGE.md)** - i386_pc_startup 变量在 GRUB 构建系统中的使用说明（如何确保 startup.S 是第一个链接的文件）
- **[CREATE_GRUB_ISO.md](CREATE_GRUB_ISO.md)** - 使用 grub-mkrescue 生成 GRUB ISO 镜像教程

### Linux 内核相关文档

- **[LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md)** - Linux 内核初始化详解（start_kernel、中断接管：早期 IDT/PIC/APIC/INT 0x80、系统调用、PID 0/1/2、init 进程）
- **[VMLINUZ_STRUCTURE.md](VMLINUZ_STRUCTURE.md)** - vmlinuz（bzImage）文件详细结构分析（boot_params、setup code、压缩内核等）
- **[VMLINUZ_INITRD_RELATIONSHIP.md](VMLINUZ_INITRD_RELATIONSHIP.md)** - vmlinuz 和 initrd 的关系详解（定义、作用机制、使用场景、必要性分析）
- **[LINUX_KERNEL_EARLY_BOOT.md](LINUX_KERNEL_EARLY_BOOT.md)** - Linux 内核早期启动详细流程（64 位）（Setup 代码、模式切换、startup_32、startup_64 源代码分析）
- **[INITRAMFS_ANALYSIS.md](INITRAMFS_ANALYSIS.md)** - Initramfs 内容分析与 BusyBox 启动设置（initramfs 分析工具、BusyBox 工作原理、/init 和 /sbin/init 的关系）
- **[INITRAMFS_ANALYSIS_RESULT.md](INITRAMFS_ANALYSIS_RESULT.md)** - Alpine Linux Initramfs 实际分析结果（基于 initrd-alpine-v3.19.img 的实际分析）
- **[ALPINE_INIT_PROCESS_ANALYSIS.md](ALPINE_INIT_PROCESS_ANALYSIS.md)** - Alpine Linux Initramfs Init 启动过程详细分析（基于 mkinitfs 源代码的完整流程分析）
- **[BUSYBOX_SH_EXEC_INIT_DETAILS.md](BUSYBOX_SH_EXEC_INIT_DETAILS.md)** - BusyBox sh 执行 /init 脚本的实现细节（Linux 内核 shebang 处理机制、binfmt_script 模块工作原理）

### 中断相关文档

- **[LINUX_INTERRUPT_HANDLING.md](LINUX_INTERRUPT_HANDLING.md)** - Linux 中断处理机制
- **[UEFI_INTERRUPT_HANDLING.md](UEFI_INTERRUPT_HANDLING.md)** - UEFI 中断处理机制
- **[APPENDIX_A_KEYBOARD_INTERRUPT.md](APPENDIX_A_KEYBOARD_INTERRUPT.md)** - 附录 A：键盘中断详解
- **[APPENDIX_B_EVENT_MECHANISM.md](APPENDIX_B_EVENT_MECHANISM.md)** - 附录 B：事件机制详解

### 硬件与 I/O 文档

- **[KEYBOARD_CONTROLLER_IO.md](KEYBOARD_CONTROLLER_IO.md)** - 键盘控制器 I/O 详解
- **[QEMU_VS_HARDWARE_BIOS.md](QEMU_VS_HARDWARE_BIOS.md)** - QEMU vs 真实硬件 BIOS 加载对比

### 内存管理文档

- **[LINUX_USERSPACE_MEMORY.md](LINUX_USERSPACE_MEMORY.md)** - Linux 用户空间内存管理
- **[FILL.md](FILL.md)** - 内存填充相关文档

### UEFI 相关文档

- **[UEFI_VS_BIOS_BOOT.md](UEFI_VS_BIOS_BOOT.md)** - UEFI vs BIOS 启动对比

### 工具与配置文档

- **[VNC_SETUP.md](VNC_SETUP.md)** - VNC 设置指南
- **[SLEEP.md](SLEEP.md)** - 睡眠/休眠相关文档

### 演示程序文档

- **[EVENT_DEMO_README.md](EVENT_DEMO_README.md)** - 事件演示程序说明
- **[KEYBOARD_DEMO_README.md](KEYBOARD_DEMO_README.md)** - 键盘演示程序说明
- **[MANUAL_INT_README.md](MANUAL_INT_README.md)** - 手动中断演示程序说明


### DOS 相关文档

- **[DOS_BOOTLOADER.md](DOS_BOOTLOADER.md)** - DOS 的引导加载程序（Bootloader）概念
- **[DOS_BIOS_INT_USAGE.md](DOS_BIOS_INT_USAGE.md)** - DOS 如何使用 BIOS 的 INT 服务

### 分析与验证工具

#### BIOS 固件分析工具

- **[verify_bios.py](verify_bios.py)** - BIOS 固件验证脚本（统一版本）
  - **验证对象**：BIOS 固件（bios.bin），映射到物理地址 0xF0000-0xFFFFF
  - **注意**：这是验证 BIOS 固件，不是 Bootloader（Bootloader 使用 verify_boot_sector.py）
  - 验证 BIOS ROM 文件中的关键固定地址是否正确
  - 分析 BIOS 文件结构（两个 64KB 块的内容分布）
  - 查找关键 BIOS 入口点
  - 分析填充区域和代码模式
  - 使用方法：
    - `python3 verify_bios.py [bios_file]` - 执行所有分析（默认）
    - `python3 verify_bios.py [bios_file] --structure` - 只执行文件结构分析
    - `python3 verify_bios.py [bios_file] --addresses` - 只执行固定地址验证

- **[BIOS_MEMORY_MAPPING.md](BIOS_MEMORY_MAPPING.md)** - BIOS 文件映射到物理内存的证据分析文档

#### Bootloader（引导扇区）分析工具

- **[verify_boot_sector.py](verify_boot_sector.py)** - 引导扇区验证脚本
  - **验证对象**：Bootloader（boot.bin），由 BIOS 加载到内存地址 0x7C00
  - **注意**：这是验证 Bootloader，不是 BIOS 固件（BIOS 使用 verify_bios.py）
  - 验证引导扇区文件大小（512 字节）
  - 验证引导扇区签名（0xAA55）
  - 验证代码内容和内存地址映射（0x7C00-0x7DFF）
  - 使用方法：`python3 verify_boot_sector.py [boot_file]`

#### GRUB 分析工具

- **[verify_grub_boot_sector.py](verify_grub_boot_sector.py)** - GRUB ISO 镜像验证脚本（统一版本）
  - **验证对象**：GRUB ISO 镜像（grub.iso）的引导扇区和 core.img
  - 自动检测标准模式和 HYBRID_BOOT 模式
  - 验证引导扇区签名和关键字段（kernel_sector、kernel_address）
  - 提取 core.img 并分析块列表（显示每个条目的详细信息）
  - 检测 core.img 压缩状态（LZMA 压缩 vs 未压缩）
    - 数据特征分析（NOP 字节、零字节、可打印字符串统计）
    - 熵值计算和压缩评分系统
  - 反汇编分析 core.img（查找 grub_stub_init 入口点）
  - 使用方法：`python3 verify_grub_boot_sector.py [iso_file]`

#### Initramfs 分析工具

- **[analyze_initramfs.sh](analyze_initramfs.sh)** - Initramfs 内容分析脚本
  - **功能**：解压并分析 initramfs（initrd.img）内容，查找 BusyBox 启动配置
  - **支持**：自动查找本地 initrd.img 文件，或从 ISO 文件中提取
  - **查找顺序**：
    1. 当前目录的 `*.img` 文件（如 `initrd-alpine-v3.19.img`）
    2. `.grub_iso_cache/` 目录中的 `initrd.img`
    3. `iso/boot/` 目录中的 `initrd.img`
    4. 从 ISO 文件中提取（如果存在）
  - **分析内容**：
    - `/init` 脚本的类型和内容
    - BusyBox 文件和符号链接
    - `/sbin/init` 和 `/bin/sh` 的配置
    - 启动配置文件（`/etc/inittab`、`/etc/init.d/rcS` 等）
    - 文件系统结构
  - **使用方法**：
    - `./analyze_initramfs.sh` - 自动查找 initrd.img（优先使用当前目录的 `*.img` 文件）
    - `./analyze_initramfs.sh /path/to/initrd.img` - 指定文件路径
  - **详细说明**：参见 [INITRAMFS_ANALYSIS.md](INITRAMFS_ANALYSIS.md)