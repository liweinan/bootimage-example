# 引导扇区编程示例项目

这是一个简单的引导扇区程序示例，演示了如何在裸机上运行代码。

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

