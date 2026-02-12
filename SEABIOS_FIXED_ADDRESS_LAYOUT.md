# SeaBIOS 固定地址布局：IBM PC BIOS 兼容性规范

> **文档导航**
>
> 本文档详细讲解 SeaBIOS 中固定地址（ORG 地址）的历史由来和兼容性要求。
>
> **相关文档**：
> - **[BIOS_INTERRUPT_COMPLETE.md](BIOS_INTERRUPT_COMPLETE.md)** - BIOS 中断服务完整列表
> - **[BIOS_MEMORY_LAYOUT.md](BIOS_MEMORY_LAYOUT.md)** - BIOS 内存布局
> - **[ASM_ORG_INSTRUCTION.md](ASM_ORG_INSTRUCTION.md)** - ORG 指令详解

## 概述

这些 `.org` 地址（在 SeaBIOS 代码中写作大写的 `ORG addr` 宏）**不是随意写的，也不是汇编器随意计算出来的，而是严格按照 IBM PC/AT 兼容 BIOS 的历史遗留布局固定下来的**。

它们是 SeaBIOS（以及几乎所有传统 Legacy BIOS 实现，如 Award、AMI、Phoenix）必须遵守的**固定位置约定**，以保证操作系统、引导程序和旧软件的兼容性。

**SeaBIOS 源码参考**：
- SeaBIOS 源码路径：`~/works/seabios`
- ORG 宏定义：`src/romlayout.S`
- BIOS 入口点：`src/post.c`, `src/clock.c`, `src/kbd.c` 等

---

## 目录

- [为什么必须固定这些地址？](#为什么必须固定这些地址)
- [ORG 地址的含义和来源](#org-地址的含义和来源)
- [这些地址是怎么"计算"出来的？](#这些地址是怎么计算出来的)
- [代码中 ORG 宏的实现方式](#代码中-org-宏的实现方式)
- [总结](#总结)

---

## 为什么必须固定这些地址？

从 1981 年 IBM PC 5150 开始，BIOS ROM（大小通常为 128KB 或 1MB）被映射到物理内存的最高地址：**0xF0000 ~ 0xFFFFF**（有时扩展到 0xE0000 ~ 0xEFFFF）。

早期操作系统（如 DOS）和许多软件**直接硬编码跳转到这些固定地址**来调用 BIOS 服务。例如：

- DOS 的 INT 10h 视频服务会跳转到 **0xF065**（视频初始化入口）。
- INT 13h 磁盘服务会跳转到 **0xEC59**（在某些 BIOS 中）。
- 开机上电后 CPU 从 **0xFFFF0** 开始执行（reset vector）。

为了保持向后兼容，所有现代 BIOS 实现（包括 SeaBIOS、coreboot 的 payload）都必须在这些经典位置提供相同的入口点，否则大量旧软件和引导程序会崩溃。

---

## ORG 地址的含义和来源

以下是 SeaBIOS 中常见的固定地址及其历史来源：

| ORG 地址 | 物理地址 | 功能描述 | 历史来源 / 兼容要求 |
|----------|----------|----------|-------------------|
| **0xe05b** | 0xFE05B | POST（Power-On Self Test）入口，正常开机进入点 | 许多 DOS 和早期 Windows 引导程序跳转到这里 |
| **0xe2c3** | 0xFE2C3 | INT 02h（NMI 非屏蔽中断）处理入口 | IBM PC/AT 标准 |
| **0xe3fe** | 0xFE3FE | 官方 INT 13h 磁盘服务入口（跳转到实际处理） | 部分旧软件直接 jmp 这里 |
| **0xe6f2** | 0xFE6F2 | 官方 INT 19h 引导入口（引导加载程序） | 经典引导入口 |
| **0xe739** | 0xFE739 | INT 14h 串口服务入口 | IBM 标准 |
| **0xe82e** | 0xFE82E | INT 16h 键盘服务入口 | IBM 标准 |
| **0xe987** | 0xFE987 | INT 09h 键盘硬件中断入口 | IBM 标准 |
| **0xec59** | 0xFEC59 | INT 40h（磁盘重定向）入口 | 旧软盘 BIOS 重定向 |
| **0xef57** | 0xFEF57 | INT 0Eh（从盘控制器中断） | IBM 标准 |
| **0xefd2** | 0xFEFD2 | INT 17h 打印机服务入口 | IBM 标准 |
| **0xf065** | 0xFF065 | 标准 INT 10h 视频服务主入口 | **最著名的地址**，几乎所有显示操作都到这里 |
| **0xf841** | 0xFF841 | INT 12h 内存大小服务 | IBM 标准 |
| **0xf84d** | 0xFF84D | INT 11h 设备列表服务 | IBM 标准 |
| **0xf859** | 0xFF859 | INT 15h 扩展服务主入口（包括 AH=0xC0、AH=0x87 等） | IBM AT 标准 |
| **0xfea5** | 0xFFEA5 | INT 08h 系统定时器中断入口 | IBM 标准 |
| **0xff53** | 0xFFF53 | 简单的 IRET（某些中断直接返回） | 填充用途 |
| **0xff54** | 0xFFF54 | INT 05h 打印屏幕入口 | IBM 标准 |
| **0xfff0** | 0xFFFF0 | **CPU 上电复位入口（reset vector）** | **硬件硬性规定**，CPU 强制从这里开始执行 |
| **0xffff** | 0xFFFFF | 机器型号 ID（通常 0xFC 表示 AT） | IBM 标准 |

### 地址分类

#### 1. CPU 硬件强制地址

| 地址 | 说明 |
|------|------|
| **0xFFFF0** | CPU 上电后的复位向量（Reset Vector），x86 CPU 硬件强制从这里开始执行 |

#### 2. BIOS 中断服务入口

| 中断 | 地址 | 服务类型 |
|------|------|---------|
| INT 08h | 0xFEA5 | 系统定时器中断 |
| INT 09h | 0xE987 | 键盘硬件中断 |
| INT 0Eh | 0xEF57 | 磁盘控制器中断 |
| INT 10h | 0xF065 | 视频服务（最常用）|
| INT 11h | 0xF84D | 设备列表查询 |
| INT 12h | 0xF841 | 内存大小查询 |
| INT 13h | 0xE3FE | 磁盘服务 |
| INT 14h | 0xE739 | 串口服务 |
| INT 15h | 0xF859 | 扩展服务 |
| INT 16h | 0xE82E | 键盘服务 |
| INT 17h | 0xEFD2 | 打印机服务 |
| INT 19h | 0xE6F2 | 引导加载 |

#### 3. 特殊功能入口

| 地址 | 功能 |
|------|------|
| 0xE05B | POST（开机自检）入口 |
| 0xE2C3 | NMI（非屏蔽中断）处理 |
| 0xEC59 | 磁盘重定向 |
| 0xFF53 | IRET 占位符 |
| 0xFFFFF | 机器型号标识 |

---

## 这些地址是怎么"计算"出来的？

**答案：不是计算，而是历史约定 + 标准文档。**

### 来源

1. **IBM 官方文档**：
   - IBM 发布的《IBM Personal Computer Technical Reference Manual》（1981/1984）中明确列出了这些入口地址。
   - 后续 IBM PC/AT、PS/2 等机型延续并扩展了这些位置。

2. **第三方 BIOS 厂商**：
   - 第三方 BIOS 厂商（Award、AMI、Phoenix）为了兼容，也严格遵守。

3. **业界标准文档**：
   - Ralf Brown's Interrupt List（著名的中断列表）详细记录了所有这些固定地址。

### 为什么 SeaBIOS 必须遵守？

SeaBIOS 作为开源 BIOS，必须**100% 复制这些经典入口**，否则：

- ❌ DOS 游戏无法显示
- ❌ Windows 9x 引导失败
- ❌ 某些诊断工具崩溃
- ❌ 甚至一些现代引导加载器（如旧版 GRUB）也会出错

---

## 代码中 ORG 宏的实现方式

在 SeaBIOS 中，`ORG addr` 是一个自定义宏（在 `src/romlayout.S` 或类似文件中定义），作用是：

```asm
// SeaBIOS 汇编宏定义示例
.macro ORG addr
    .section .fixedaddr.\addr   // 创建一个特定名字的 section
    .org \addr                  // 强制当前位置为指定地址
.endm
```

### 链接器处理

链接器脚本（如 `src/romlayout.lds`）会把这些 `.fixedaddr.xxxx` section 精确放置到 ROM 镜像的对应偏移，从而确保最终生成的 BIOS ROM 文件在 **0xF0000 + offset** 处正好有这些入口代码。

### 示例

```asm
// 在 SeaBIOS 源码中
ORG 0xf065
entry_10:
    // INT 10h 视频服务的实现
    push %ds
    push %es
    // ...
    iret

ORG 0xfff0
reset_vector:
    // CPU 上电后的第一条指令
    jmp far 0xf000:0xe05b  // 跳转到 POST 入口
```

### 最终 ROM 布局

```
ROM 文件偏移      物理地址          内容
0x0065       →   0xF0065 (0xFF065)  INT 10h 入口代码
0x0841       →   0xF0841 (0xFF841)  INT 12h 入口代码
...
0xFFF0       →   0xFFFF0            复位向量：jmp 0xE05B
0xFFFF       →   0xFFFFF            机器型号：0xFC
```

---

## 兼容性示例

### 示例 1: DOS 调用 INT 10h

```asm
; DOS 程序
mov ah, 0x0e    ; 功能：显示字符
mov al, 'A'     ; 要显示的字符
int 0x10        ; 触发 INT 10h

; CPU 行为：
; 1. 查找 IVT[0x10]（实模式中断向量表）
; 2. 跳转到 0xF000:0xF065（物理地址 0xFF065）
; 3. 执行 SeaBIOS 的视频服务代码
```

### 示例 2: CPU 上电

```
1. CPU 上电，CS=0xF000, IP=0xFFF0
2. 物理地址 = CS << 4 + IP = 0xFFFF0
3. 执行 SeaBIOS 在 0xFFFF0 处的代码：
   ORG 0xfff0
   jmp far 0xf000:0xe05b  ; 跳转到 POST
4. 开始执行 POST（开机自检）
```

---

## 总结

你看到的这些 `ORG 0xe05b`、`ORG 0xf065`、`ORG 0xffff0` 等地址：

- **不是随意或计算出来的**
- 是 **30~40 年历史的 IBM PC BIOS 兼容性铁律**
- SeaBIOS 必须严格遵守，否则就不能称为"兼容 BIOS"
- 它们是 x86 实模式生态中少数几个真正"神圣不可侵犯"的固定地址之一（另一个著名的是引导扇区 0x7C00）

这就是为什么 SeaBIOS 代码里会出现这么多看起来"奇怪"的硬编码地址——**它们不是 bug，而是兼容性的基石**。

---

## 相关文档

### BIOS 相关

- **[BIOS_INTERRUPT_COMPLETE.md](BIOS_INTERRUPT_COMPLETE.md)** - BIOS 中断服务完整列表
- **[BIOS_MEMORY_LAYOUT.md](BIOS_MEMORY_LAYOUT.md)** - BIOS 内存布局详解
- **[BIOS_FIRST_BLOCK_ANALYSIS.md](BIOS_FIRST_BLOCK_ANALYSIS.md)** - BIOS 第一个块的分析
- **[SEABIOS_LOAD_BOOT_SECTOR.md](SEABIOS_LOAD_BOOT_SECTOR.md)** - SeaBIOS 加载引导扇区流程

### 启动相关

- **[BOOT_FLOW.md](BOOT_FLOW.md)** - x86 启动流程完整指南
- **[ORG_0x7C00_EXPLANATION.md](ORG_0x7C00_EXPLANATION.md)** - 为什么引导扇区在 0x7C00

### x86 架构

- **[X86_CPU_MODES.md](X86_CPU_MODES.md)** - x86 CPU 模式（实模式、保护模式、长模式）
- **[ASM_ORG_INSTRUCTION.md](ASM_ORG_INSTRUCTION.md)** - ORG 指令详解

---

## 参考资料

1. **IBM Personal Computer Technical Reference Manual** (1981/1984)
2. **Ralf Brown's Interrupt List** - http://www.ctyme.com/rbrown.htm
3. **SeaBIOS Source Code** - `~/works/seabios`
   - `src/romlayout.S` - ORG 宏定义和固定地址入口
   - `src/post.c` - POST 流程
   - `src/clock.c`, `src/kbd.c`, `src/disk.c` - 各种 BIOS 服务实现
4. **Phoenix BIOS Specification**
5. **Award BIOS Specification**

---

**文档版本**：1.0
**最后更新**：2026-02-13
**SeaBIOS 版本**：基于最新开源版本
**维护者**：x86 启动流程文档项目
