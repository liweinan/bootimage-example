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

# 运行
make run

# 清理
make clean
```

### 方法二：手动编译和运行

```bash
# 编译
nasm -f bin boot.asm -o boot.bin

# 在 QEMU 中运行
qemu-system-x86_64 -drive format=raw,file=boot.bin
```

## 程序说明

`boot.asm` 是一个最小的引导扇区程序，它会：

1. 设置 80x25 文本显示模式
2. 在屏幕上显示 "Hello from Boot Sector!"
3. 进入无限循环（halt）

## 退出 QEMU

在 QEMU 窗口中按 `Ctrl+Alt+G` 释放鼠标，然后按 `Ctrl+C` 或关闭窗口。

或者使用快捷键：
- `Ctrl+Alt+G` - 释放/捕获鼠标
- `Ctrl+Alt+Q` - 退出 QEMU

## 注意事项

- 这个程序在真实的物理机器上运行可能会损坏数据，请只在虚拟机中测试
- 引导扇区必须是 512 字节，最后两个字节必须是 `0xAA55`
- 程序运行在 16 位实模式下

