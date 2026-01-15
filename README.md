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
- **[BIOS_MEMORY_MODE.md](BIOS_MEMORY_MODE.md)** - BIOS 内存模式分析
- **[BIOS_MEMORY_MODE_ANALYSIS.md](BIOS_MEMORY_MODE_ANALYSIS.md)** - BIOS 内存模式详细分析
- **[BIOS_MEMORY_QA.md](BIOS_MEMORY_QA.md)** - BIOS 内存相关问答
- **[BIOS_CODE_LAYOUT_ANALYSIS.md](BIOS_CODE_LAYOUT_ANALYSIS.md)** - BIOS 代码布局分析
- **[BIOS_INTERRUPT_COMPLETE.md](BIOS_INTERRUPT_COMPLETE.md)** - BIOS 中断完整文档
- **[BIOS_IVT_VS_KERNEL_IDT.md](BIOS_IVT_VS_KERNEL_IDT.md)** - BIOS IVT 与 Linux 内核 IDT 对比
- **[bios_size.md](bios_size.md)** - BIOS 大小与映射关系详解
- **[bios_verification_report.md](bios_verification_report.md)** - BIOS 固定地址验证报告

### SeaBIOS 相关文档

- **[fill_seabios_analysis.md](fill_seabios_analysis.md)** - SeaBIOS 与 Linux 内核地址转换机制对比分析
- **[SEABIOS_PROTECTION_MODE_CODE.md](SEABIOS_PROTECTION_MODE_CODE.md)** - SeaBIOS 保护模式代码的真正用途
- **[SEABIOS_ENTRY_13_ANALYSIS.md](SEABIOS_ENTRY_13_ANALYSIS.md)** - SeaBIOS INT 13h 入口分析
- **[SEABIOS_HANDLE_POST_ENTRY.md](SEABIOS_HANDLE_POST_ENTRY.md)** - SeaBIOS handle_post 入口分析

### 启动流程文档

- **[BOOT_FLOW.md](BOOT_FLOW.md)** - 计算机启动流程详解（从 QEMU 到 Linux 内核的完整流程）
- **[BOOT_FLOW_NOTES.md](BOOT_FLOW_NOTES.md)** - 启动流程笔记
- **[BOOT_FLOW_OPTIMIZATION_ANALYSIS.md](BOOT_FLOW_OPTIMIZATION_ANALYSIS.md)** - 启动流程优化分析
- **[BOOT_FLOW_QA.md](BOOT_FLOW_QA.md)** - 启动流程问答
- **[BOOTSECTOR_COMPARISON.md](BOOTSECTOR_COMPARISON.md)** - 引导扇区对比分析
- **[SEABIOS_LOAD_BOOT_SECTOR.md](SEABIOS_LOAD_BOOT_SECTOR.md)** - SeaBIOS 如何加载引导扇区到 0x7C00
- **[DISK_TO_MEMORY_TRANSFER.md](DISK_TO_MEMORY_TRANSFER.md)** - 磁盘数据拷贝到内存的详细过程（PIO/DMA）
- **[BOOT_SECTOR_ANALYSIS.md](BOOT_SECTOR_ANALYSIS.md)** - 引导扇区代码手工分析指南
- **[CALL_BOOT_ENTRY_EXPLANATION.md](CALL_BOOT_ENTRY_EXPLANATION.md)** - call_boot_entry 函数详细解释

### GRUB 引导加载程序文档

- **[GRUB_ISO_ANALYSIS.md](GRUB_ISO_ANALYSIS.md)** - GRUB ISO 镜像引导分析（boot.S、core.img 位置、内存布局等）
- **[GRUB_ISO_BOOT_FILES.md](GRUB_ISO_BOOT_FILES.md)** - GRUB ISO 镜像中哪些文件在 boot 阶段被加载

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
- **[fill.md](fill.md)** - 内存填充相关文档

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
### 分析与优化文档

- **[BIOS_DOCS_OPTIMIZATION_ANALYSIS.md](BIOS_DOCS_OPTIMIZATION_ANALYSIS.md)** - BIOS 文档优化分析
- **[EXTRACTION_ANALYSIS.md](EXTRACTION_ANALYSIS.md)** - 提取分析文档

### 分析与验证工具

#### BIOS 分析工具

- **[verify_bios.py](verify_bios.py)** - BIOS 验证脚本
- **[verify_bios_mapping.py](verify_bios_mapping.py)** - BIOS 映射验证脚本
- **[analyze_bios_structure.py](analyze_bios_structure.py)** - BIOS 结构分析脚本
- **[verify_bios_structure.py](verify_bios_structure.py)** - BIOS 结构验证脚本（验证 128KB BIOS 中两个 64KB 块的数据分布，分析代码区域和元数据区域）

#### GRUB 分析工具

- **[analyze_grub_boot_sector.sh](analyze_grub_boot_sector.sh)** - GRUB 引导扇区分析工具
  - 自动检测标准模式和 HYBRID_BOOT 模式
  - 查找 kernel_sector 字段和 core.img 位置
  - 检测 core.img 压缩状态（LZMA 压缩 vs 未压缩）
  - 使用方法：`./analyze_grub_boot_sector.sh grub.iso`

- **[disassemble_core_img.py](disassemble_core_img.py)** - core.img 反汇编分析工具
  - 反汇编分析 core.img，识别指令模式
  - 计算数据熵值，判断压缩状态
  - 分析内存空间需求
  - 使用方法：`python3 disassemble_core_img.py grub.iso [kernel_sector]`