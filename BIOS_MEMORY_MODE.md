# BIOS 运行模式与内存访问详解

本文档已拆分为三个更聚焦的文档，以提供更好的阅读体验：

## 文档结构

1. **[x86 CPU 运行模式详解](X86_CPU_MODES.md)**
   - 实模式（Real Mode）与保护模式（Protected Mode）的详细说明
   - 模式特性、地址计算、段寄存器使用
   - 模式切换机制
   - 长模式（Long Mode）简介

2. **[BIOS 内存布局与地址映射详解](BIOS_MEMORY_LAYOUT.md)**
   - BIOS 内存布局与地址映射
   - 为什么 BIOS 映射到实模式内存空间只有 128KB
   - BIOS 存储在 4GB 地址空间顶部的原因
   - BIOS ROM 的特殊映射机制
   - QEMU 和 SeaBIOS 如何支持更大内存的虚拟机
   - 64 位虚拟机如何支持 32 位内存地址
   - 实际硬件（64位CPU）如何支持32位内存地址

3. **[BIOS 内存模式 Q&A](BIOS_MEMORY_QA.md)**
   - Bootloader 运行模式和加载位置
   - DOS 时代内存使用情况
   - BIOS 大小限制和历史演进
   - 其他常见问题解答

## 相关文档

- [QEMU vs 真实硬件 BIOS 加载对比](QEMU_VS_HARDWARE_BIOS.md)
- [BIOS 中断处理完整指南](BIOS_INTERRUPT_COMPLETE.md)
- [SeaBIOS INT 13h 实现分析](SEABIOS_ENTRY_13_ANALYSIS.md)
- [SeaBIOS handle_post 入口地址分析](SEABIOS_HANDLE_POST_ENTRY.md)
- [Linux 用户空间内存模型详解](LINUX_USERSPACE_MEMORY.md) - Linux 用户空间的内存模型、内存管理和汇编内存访问（从 BIOS 内存模型到 Linux 用户空间内存模型的完整视角）
