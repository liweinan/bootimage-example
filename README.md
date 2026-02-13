# 引导扇区编程示例项目

这是一个简单的引导扇区程序示例，演示了如何在裸机上运行代码。

<img width="2296" height="1410" alt="fe4f9ff229c104aee6d03f53d2dbee6c" src="https://github.com/user-attachments/assets/170fbdec-6b11-4e7a-8272-fccfcdb35d1e" />

---

## 📚 文档导读

**本项目包含 100+ 篇技术文档，涵盖从 BIOS 到 Linux 内核的完整启动流程。**

👉 **首次访问？请先阅读** [📖 文档导读指南 (READING_GUIDE.md)](READING_GUIDE.md)

导读包含：
- 🎯 **快速导航**：我想了解...（按主题快速定位）
- 🛤️ **学习路径推荐**：入门 → 进阶 → 专家（4条完整学习路径）
- 📊 **核心文档关系图**：理解文档间的依赖关系
- 🔍 **主题索引**：A-Z 快速查找

**推荐学习路径**：
- 💡 **入门**：启动流程基础（2-3天） → [查看路径](READING_GUIDE.md#-路径-1入门路径理解启动流程)
- 🧠 **进阶**：深入内存管理（1-2周） → [查看路径](READING_GUIDE.md#-路径-2进阶路径深入内存管理)
- 🔬 **专家**：中断与系统调用（1周） → [查看路径](READING_GUIDE.md#-路径-3专家路径中断与系统调用)
- 🔧 **专题**：GRUB 详解（5-7天） → [查看路径](READING_GUIDE.md#-路径-4grub-专题路径)

---


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

---

## 📚 完整文档索引

本项目包含 100+ 篇技术文档，涵盖 BIOS、启动流程、中断、内存管理、GRUB、Linux 内核等各个主题。

完整的文档分类索引请查看：**[📑 文档索引 (DOCUMENT_INDEX.md)](DOCUMENT_INDEX.md)**
