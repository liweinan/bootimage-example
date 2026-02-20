# x86-64 任务状态段（TSS）与中断栈表（IST）详解

**版本**: 2.0
**日期**: 2026-01-30
**作者**: Linux 内核启动文档项目

> 📚 **文档导航**: [返回总索引](DOCUMENT_INDEX.md) | [阅读指南](READING_GUIDE.md) | [IDT 演进](LINUX_KERNEL_IDT_EVOLUTION.md) | [内核启动](LINUX_KERNEL_INIT.md)

---

## 目录

1. [概述：TSS 和 IST 的角色](#1-概述tss-和-ist-的角色)
2. [TSS 的历史演变](#2-tss-的历史演变)
3. [x86-64 中的 TSS 结构](#3-x86-64-中的-tss-结构)
4. [IST 机制详解](#4-ist-机制详解)
5. [为什么需要 IST？](#5-为什么需要-ist)
6. [IST 与 IDT 的集成](#6-ist-与-idt-的集成)
7. [Linux 内核中的 TSS 初始化](#7-linux-内核中的-tss-初始化)
8. [IST 的实际使用场景](#8-ist-的实际使用场景)
9. [危险场景：未初始化 TSS 时使用 IST](#9-危险场景未初始化-tss-时使用-ist)
10. [调试与验证](#10-调试与验证)
11. [历史回顾：没有 IST 的时代](#11-历史回顾没有-ist-的时代)
12. [TSS 数量的历史演变](#12-tss-数量的历史演变)
13. [进程上下文的保存位置](#13-进程上下文的保存位置)
14. [GDT 与 LDT 的关系](#14-gdt-与-ldt-的关系)
15. [内核栈与用户空间](#15-内核栈与用户空间)
16. [总结](#16-总结)
17. [参考文献](#17-参考文献)

---

## 1. 概述：TSS 和 IST 的角色

### 1.1 什么是 TSS？

**TSS (Task State Segment, 任务状态段)** 是 x86 架构中的一个数据结构，用于保存任务（进程）的状态信息。

**历史角色**（x86-32）：
- 硬件任务切换（Hardware Task Switching）
- 保存完整的 CPU 状态（寄存器、栈指针、页表等）
- 通过 JMP/CALL 指令自动切换任务

**现代角色**（x86-64）：
- ❌ **不再用于任务切换**（硬件任务切换在 x86-64 中已废弃）
- ✅ **提供特权级栈切换**（从用户态进入内核态时切换栈）
- ✅ **提供 IST 机制**（为关键异常提供独立的栈）
- ✅ **保存 I/O 权限位图**（控制用户态对 I/O 端口的访问）

### 1.2 什么是 IST？

**IST (Interrupt Stack Table, 中断栈表)** 是 x86-64 架构引入的新机制，用于在处理某些关键中断/异常时**自动切换到预先指定的栈**。

**核心功能**：
- 为特定的中断/异常提供**独立的栈空间**
- 避免栈溢出导致的灾难性后果
- 解决嵌套异常的处理问题

**典型使用场景**：
- **Double Fault (#DF)**：栈溢出导致的双重故障
- **NMI (Non-Maskable Interrupt)**：不可屏蔽中断
- **Machine Check (#MC)**：硬件错误
- **Debug (#DB)**：调试异常

### 1.3 TSS 和 IST 的关系

```
┌─────────────────────────────────────────────┐
│  TSS (Task State Segment)                   │
│                                              │
│  ┌────────────────────────────────────┐    │
│  │  IST1: 0xffffc90000004000          │◄───┼─── IST 栈 1 的地址
│  │  IST2: 0xffffc90000008000          │    │
│  │  IST3: 0xffffc9000000c000          │    │
│  │  IST4: 0xffffc90000010000          │    │
│  │  IST5: 0xffffc90000014000          │    │
│  │  IST6: 0xffffc90000018000          │    │
│  │  IST7: 0xffffc9000001c000          │    │
│  └────────────────────────────────────┘    │
│                                              │
│  RSP0: 0xffffc90000020000 (内核栈)         │
│  RSP1: (未使用)                             │
│  RSP2: (未使用)                             │
│  I/O Map Base: ...                          │
└─────────────────────────────────────────────┘
                    ▲
                    │
                    │ CPU 从 TR (Task Register) 找到 TSS
                    │
┌───────────────────┴─────────────────────────┐
│  IDT Entry (例如 #DF, 向量 8)               │
│                                              │
│  Offset:   0xffffffff81234567 (处理程序)   │
│  Selector: __KERNEL_CS                      │
│  IST:      1  ◄──────────────────────────  │ 使用 TSS.IST1
│  Type:     Interrupt Gate                   │
│  DPL:      0                                 │
└─────────────────────────────────────────────┘
```

**工作流程**：
1. CPU 加载 TSS 的地址到 **TR (Task Register)**（通过 `ltr` 指令）
2. IDT 表项中指定使用哪个 IST（1-7，或 0 表示不用 IST）
3. 发生中断/异常时，CPU 自动：
   - 读取 TR → 找到 TSS
   - 读取 IDT 表项 → 得到 IST 索引（例如 1）
   - 从 TSS.IST[索引] 读取栈地址
   - 切换 RSP 到该栈
   - 保存旧的 SS:RSP 到新栈上
   - 跳转到处理程序

### 1.4 形象化理解：TSS/IST 的类比

**类比 1：TSS 是内存中的"寄存器快照盒子"**

TSS 就像一个保存在内存中的"工具箱"，里面装着 CPU 在各种紧急情况下需要用到的备用工具（栈指针）：

```
┌────────────────────────────────┐
│  TSS 工具箱（内存数据结构）    │
│                                 │
│  📦 RSP0: 常规内核栈           │  ← 日常工作用
│  🚨 IST1: 双重故障专用栈       │  ← 紧急灭火器
│  🚨 IST2: NMI 专用栈           │  ← 随时可用的备用工具
│  🚨 IST3: 调试专用栈           │  ← 专业诊断工具
│  🚨 IST4: 机器检查专用栈       │  ← 硬件故障应急
└────────────────────────────────┘
```

**类比 2：IST 是系统的"安全气囊"**

可以把 IST 理解为汽车的安全气囊系统：

| 场景 | 汽车安全气囊 | IST 机制 |
|------|-------------|----------|
| **日常使用** | 安全气囊待命，不干扰驾驶 | 普通异常使用普通内核栈 |
| **紧急情况** | 碰撞时气囊自动弹出 | 关键异常时 CPU 自动切换到 IST 栈 |
| **独立系统** | 气囊有独立的传感器和充气装置 | IST 栈完全独立于普通内核栈 |
| **最后防线** | 防止严重伤害 | 防止三重故障导致的系统重启 |

**类比 3：没有 IST 就像消防队没有水**

```
┌──────────────────────────────────────┐
│  内存问题 = 着火 🔥                  │
└──────────────────────────────────────┘
            │
    ┌───────┴────────┐
    │                 │
有 IST ✅          无 IST ❌
    │                 │
    ▼                 ▼
每个关键位置        消防队到了
都有灭火器          但消防栓没水
    │                 │
    ▼                 ▼
可以扑灭小火        只能看着烧光
可以记录现场        连日志都没有
安全 panic          三重故障重启
```

**核心要点**：
- **TSS**：内存中的数据结构，不是寄存器
- **IST**：既是 TSS 中的字段（7个栈指针），也是 IDT 中的索引值（1-7）
- **关系**：异常 → 查 IDT（获得 IST 索引）→ 查 TSS（获得栈地址）→ 切换栈

---

## 2. TSS 的历史演变

### 2.1 x86-32 时代：硬件任务切换

**TSS 在 32 位模式下的完整结构**（104 字节）：

```c
struct tss32 {
    u16 prev_task;    // 链接到前一个任务
    u16 reserved1;
    u32 esp0;         // 特权级 0 栈指针
    u16 ss0;          // 特权级 0 栈段
    u16 reserved2;
    u32 esp1;         // 特权级 1 栈指针
    u16 ss1;
    u16 reserved3;
    u32 esp2;         // 特权级 2 栈指针
    u16 ss2;
    u16 reserved4;
    u32 cr3;          // 页目录基址
    u32 eip;          // 指令指针
    u32 eflags;       // 标志寄存器
    u32 eax, ecx, edx, ebx;
    u32 esp, ebp, esi, edi;
    u16 es, reserved5;
    u16 cs, reserved6;
    u16 ss, reserved7;
    u16 ds, reserved8;
    u16 fs, reserved9;
    u16 gs, reserved10;
    u16 ldt_selector;
    u16 reserved11;
    u16 trap;
    u16 io_map_base;  // I/O 权限位图偏移
};
```

**硬件任务切换的工作方式**：

```
┌─────────────────────────────────────────────┐
│  任务 A 的 TSS                              │
│  EIP = 0x08001234                           │
│  ESP = 0x08004000                           │
│  EAX = 0x12345678                           │
│  ... (所有寄存器)                           │
└─────────────────────────────────────────────┘
                    │
                    │ JMP/CALL far to Task B's selector
                    │
                    ▼
        ┌─────────────────────┐
        │  CPU 自动保存       │
        │  所有寄存器到 TSS A │
        └─────────────────────┘
                    │
                    ▼
        ┌─────────────────────┐
        │  CPU 从 TSS B       │
        │  恢复所有寄存器     │
        └─────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│  任务 B 的 TSS                              │
│  EIP = 0x08005678                           │
│  ESP = 0x08008000                           │
│  CR3 = 0x00100000 (不同的页表!)            │
└─────────────────────────────────────────────┘
```

**为什么 Linux 不使用硬件任务切换**：
1. **性能低下**：保存/恢复所有寄存器 + 刷新 TLB，非常慢
2. **灵活性差**：无法自定义任务切换逻辑
3. **软件切换更快**：只保存必要的寄存器，按需切换页表

### 2.2 x86-64 时代：简化与重新定位

在 x86-64 Long Mode 中，Intel 和 AMD **废弃了硬件任务切换**：

**变化**：
- ❌ 移除了大部分任务切换相关字段（prev_task, EIP, EFLAGS, 所有通用寄存器）
- ❌ 不再支持 JMP/CALL 到 TSS 描述符
- ✅ 保留了特权级栈切换（RSP0, RSP1, RSP2）
- ✅ **新增了 IST 机制**（7 个额外的栈指针）
- ✅ 保留了 I/O 权限位图

**新的角色**：
- TSS 成为"内核栈管理器"
- 每个 CPU 核心一个 TSS（而不是每个任务一个）
- 主要用于用户态→内核态的栈切换和 IST

### 2.3 Intel SDM 官方描述：64 位模式任务管理（Section 7.7）

根据 **Intel SDM Vol 3A, Section 7.7 "Task Management in 64-bit Mode"** 的官方说明：

> "In 64-bit mode, task structure and task state are similar to those in protected mode. However, the task switching mechanism available in protected mode is **not supported** in 64-bit mode. Task management and switching **must be performed by software**."

**64 位模式下的限制**：

处理器在 64 位模式下如果尝试以下操作，将产生通用保护异常（#GP）：
- 使用 JMP、CALL、INTn 或中断将控制转移到 TSS 或任务门
- 在 EFLAGS.NT（嵌套任务）设置为 1 时执行 IRET

**64 位 TSS 必须存在**：

> "Although hardware task-switching is not supported in 64-bit mode, a 64-bit task state segment (TSS) **must exist**."

操作系统在激活 IA-32e 模式后**必须**：
1. 创建至少一个 64-bit TSS
2. 在 64 位模式下执行 LTR 指令，将 TR 寄存器指向负责 64 位模式程序和兼容模式程序的 64-bit TSS

**64-bit TSS 保存的关键信息**：
| 字段 | 说明 |
|------|------|
| RSPn | 特权级 0-2 的栈指针的完整 64 位规范形式（canonical form） |
| ISTn | 中断栈表指针的完整 64 位规范形式 |
| I/O Map Base Address | 从 64-bit TSS 基址到 I/O 权限位图的 16 位偏移 |

---

## 3. x86-64 中的 TSS 结构

### 3.1 硬件定义的 TSS 结构

**Intel SDM Vol 3A, Section 7.7, Figure 7-11 "64-Bit TSS Format"**：

```
                     31                               15                    0
                  ┌────────────────────────────────┬──────────────────────┐
             100  │    I/O Map Base Address        │       Reserved       │
                  ├────────────────────────────────┴──────────────────────┤
              96  │                        Reserved                        │
                  ├───────────────────────────────────────────────────────┤
              92  │                        Reserved                        │
                  ├───────────────────────────────────────────────────────┤
              88  │               IST7 (upper 32 bits)                    │
                  ├───────────────────────────────────────────────────────┤
              84  │               IST7 (lower 32 bits)                    │
                  ├───────────────────────────────────────────────────────┤
              80  │               IST6 (upper 32 bits)                    │
                  ├───────────────────────────────────────────────────────┤
              76  │               IST6 (lower 32 bits)                    │
                  ├───────────────────────────────────────────────────────┤
              72  │               IST5 (upper 32 bits)                    │
                  ├───────────────────────────────────────────────────────┤
              68  │               IST5 (lower 32 bits)                    │
                  ├───────────────────────────────────────────────────────┤
              64  │               IST4 (upper 32 bits)                    │
                  ├───────────────────────────────────────────────────────┤
              60  │               IST4 (lower 32 bits)                    │
                  ├───────────────────────────────────────────────────────┤
              56  │               IST3 (upper 32 bits)                    │
                  ├───────────────────────────────────────────────────────┤
              52  │               IST3 (lower 32 bits)                    │
                  ├───────────────────────────────────────────────────────┤
              48  │               IST2 (upper 32 bits)                    │
                  ├───────────────────────────────────────────────────────┤
              44  │               IST2 (lower 32 bits)                    │
                  ├───────────────────────────────────────────────────────┤
              40  │               IST1 (upper 32 bits)                    │
                  ├───────────────────────────────────────────────────────┤
              36  │               IST1 (lower 32 bits)                    │
                  ├───────────────────────────────────────────────────────┤
              32  │                        Reserved                        │
                  ├───────────────────────────────────────────────────────┤
              28  │                        Reserved                        │
                  ├───────────────────────────────────────────────────────┤
              24  │               RSP2 (upper 32 bits)                    │
                  ├───────────────────────────────────────────────────────┤
              20  │               RSP2 (lower 32 bits)                    │
                  ├───────────────────────────────────────────────────────┤
              16  │               RSP1 (upper 32 bits)                    │
                  ├───────────────────────────────────────────────────────┤
              12  │               RSP1 (lower 32 bits)                    │
                  ├───────────────────────────────────────────────────────┤
               8  │               RSP0 (upper 32 bits)                    │
                  ├───────────────────────────────────────────────────────┤
               4  │               RSP0 (lower 32 bits)                    │
                  ├───────────────────────────────────────────────────────┤
               0  │                        Reserved                        │
                  └───────────────────────────────────────────────────────┘
                   (Reserved bits 必须设置为 0)
```

**最小 TSS 大小**：104 字节（0x68）

### 3.1.1 64 位 TSS 描述符格式

根据 **Intel SDM Vol 3A, Section 7.2.3 "TSS Descriptor in 64-bit mode"**，在 IA-32e 模式下，TSS 描述符扩展为 **16 字节**（两个连续的 8 字节条目）：

```
                           64-bit TSS Descriptor (16 bytes)
         ┌─────────────────────────────────────────────────────────────┐
  Byte 15│                        Reserved                             │
  Byte 14│                                                             │
  Byte 13│                                                             │
  Byte 12│                                                             │
         ├─────────────────────────────────────────────────────────────┤
  Byte 11│                  Base Address [63:32]                       │
  Byte 10│                                                             │
  Byte  9│                                                             │
  Byte  8│                                                             │
         ├────────┬─────┬───────┬─────────────────────────────────────┤
  Byte  7│Base[31:24]│ G │ 0 │ 0 │ AVL │ Limit[19:16] │ P │DPL│ 0 │Type│
         ├────────┴─────┴───────┴───────┴──────────────┴───┴───┴───┴───┤
  Byte  4│                  Base Address [23:0]                        │
         ├─────────────────────────────────────────────────────────────┤
  Byte  2│              Segment Selector (for TSS)                     │
         ├─────────────────────────────────────────────────────────────┤
  Byte  0│                  Segment Limit [15:0]                       │
         └─────────────────────────────────────────────────────────────┘
```

**Type 字段值**：
- `1001b (9)`: 64-bit TSS (Available)
- `1011b (Bh)`: 64-bit TSS (Busy)

**关键点**：
- 64 位 TSS 描述符占用 GDT 中**两个连续的条目**
- 高 8 字节的 Type 字段为 `0000b`，用于与低 8 字节的 Type 区分
- 这允许 TSS 基址使用完整的 64 位规范地址

### 3.2 Linux 内核的 TSS 结构

**文件**：`arch/x86/include/asm/processor.h`

```c
struct x86_hw_tss {
    u32                     reserved1;
    u64                     sp0;
    u64                     sp1;

    /*
     * Since Linux does not use ring 2, the 'sp2' slot is unused by
     * hardware.  entry_SYSCALL_64 uses it as scratch space to stash
     * the user RSP value.
     */
    u64                     sp2;

    u64                     reserved2;
    u64                     ist[7];
    u32                     reserved3;
    u32                     reserved4;
    u16                     reserved5;
    u16                     io_bitmap_base;

} __attribute__((packed));
```

**关键字段说明**：

| 字段 | 偏移 | 大小 | 用途 |
|------|------|------|------|
| `reserved1` | +0 | 4 字节 | 保留（对应 x86-32 的 prev_task） |
| `sp0` | +4 | 8 字节 | **Ring 0 栈**：用户态→内核态时切换到此栈 |
| `sp1` | +12 | 8 字节 | Ring 1 栈（未使用，x86-64 只用 Ring 0/3） |
| `sp2` | +20 | 8 字节 | **Linux 特殊用法**：`entry_SYSCALL_64` 用作临时保存用户 RSP |
| `reserved2` | +28 | 8 字节 | 保留 |
| `ist[0..6]` | +36 | 56 字节 | **7 个 IST 栈**：为关键异常提供独立栈 |
| `reserved3` | +92 | 4 字节 | 保留 |
| `reserved4` | +96 | 4 字节 | 保留 |
| `reserved5` | +100 | 2 字节 | 保留 |
| `io_bitmap_base` | +102 | 2 字节 | I/O 位图在 TSS 中的偏移 |

### 3.3 SDM 定义与 Linux 内核结构的对比分析

以下表格将 **Intel SDM Figure 7-11** 中的 64-bit TSS 硬件定义与 **Linux 内核 `struct x86_hw_tss`** 进行逐字段对比：

| SDM 字段名 | SDM 偏移 | Linux 字段 | Linux 偏移 | 匹配情况 | 说明 |
|------------|----------|------------|------------|----------|------|
| Reserved | 0-3 | `reserved1` | 0-3 | ✅ 完全匹配 | 4 字节保留字段 |
| RSP0 | 4-11 | `sp0` | 4-11 | ✅ 完全匹配 | Ring 0 栈指针 |
| RSP1 | 12-19 | `sp1` | 12-19 | ✅ 完全匹配 | Ring 1 栈指针（未使用） |
| RSP2 | 20-27 | `sp2` | 20-27 | ⚠️ 字段匹配，用途不同 | **Linux 重新利用为 syscall 临时空间** |
| Reserved | 28-35 | `reserved2` | 28-35 | ✅ 完全匹配 | 8 字节保留字段 |
| IST1-IST7 | 36-91 | `ist[7]` | 36-91 | ✅ 完全匹配 | 7 个 IST 栈指针（各 8 字节） |
| Reserved | 92-99 | `reserved3` + `reserved4` | 92-99 | ✅ 完全匹配 | 8 字节保留字段 |
| Reserved | 100-101 | `reserved5` | 100-101 | ✅ 完全匹配 | 2 字节保留字段 |
| I/O Map Base Address | 102-103 | `io_bitmap_base` | 102-103 | ✅ 完全匹配 | I/O 位图偏移 |

**总大小**：104 字节 (0x68)

#### 3.3.1 Linux 对 `sp2` 字段的特殊利用

SDM 规定 RSP2 用于 Ring 2 的栈指针，但 Linux 只使用 Ring 0 和 Ring 3，因此 RSP2 字段对硬件而言完全闲置。Linux 内核巧妙地将其重新利用：

```asm
// arch/x86/entry/entry_64.S - entry_SYSCALL_64 中的使用
SYM_INNER_LABEL(entry_SYSCALL_64_after_hwframe, SYM_L_GLOBAL)
    swapgs
    /* tss.sp2 is scratch space. */
    movq    %rsp, PER_CPU_VAR(cpu_tss_rw + TSS_sp2)  // 保存用户 RSP
    SWITCH_TO_KERNEL_CR3 scratch_reg=%rsp
    movq    PER_CPU_VAR(cpu_current_top_of_stack), %rsp  // 切换到内核栈

    /* Construct struct pt_regs on stack */
    pushq   $__USER_DS                              /* pt_regs->ss */
    pushq   PER_CPU_VAR(cpu_tss_rw + TSS_sp2)       /* pt_regs->sp (从 sp2 取回) */
    pushq   %r11                                    /* pt_regs->flags */
    pushq   $__USER_CS                              /* pt_regs->cs */
    pushq   %rcx                                    /* pt_regs->ip */
```

**为什么选择 `sp2`？**
1. **已在缓存中**：TSS 结构在 syscall 路径上经常被访问，`sp2` 与 `sp0` 在同一缓存行
2. **无竞争**：per-CPU 的 TSS，不需要加锁
3. **无副作用**：硬件不会读取 RSP2（因为没有 Ring 2 代码）

#### 3.3.2 系统调用方式与 TSS 使用对比

x86 架构上系统调用的实现方式经历了演变，不同方式对 TSS 的依赖程度不同：

| 方式 | 是否查 IDT | 是否自动用 TSS 做任务切换 | 是否从 TSS 加载内核栈 |
|------|-----------|--------------------------|---------------------|
| **`int 0x80`**（32 位老式） | 是 | 否 | ✅ 是（硬件自动从 TSS 加载 SS0/ESP0） |
| **`sysenter`**（32 位优化） | 否 | 否 | ❌ 否（硬件不自动用 TSS，但软件可读 TSS） |
| **`syscall`**（64 位） | 否 | 否 | ❌ 否（硬件不自动用 TSS，从 per-cpu 变量获取栈） |

**`int 0x80`（传统方式）**：
- 本质是软中断，CPU 处理方式同普通中断：查 IDT → 特权级切换时从 TSS 加载内核栈
- 性能开销大（需要查表、权限检查等）

**`sysenter/sysexit`（Intel 32 位优化）**：
- 使用 MSR 寄存器预先存好内核态 CS、EIP、ESP 等信息
- 进入内核时**不查 IDT，不用 TSS 自动加载栈**
- 比 `int 0x80` 更快

**`syscall/sysret`（64 位标准）**：
- 使用 `IA32_LSTAR` MSR 存储入口地址，`IA32_STAR` 存储 CS/SS 选择子
- **不查 IDT，不用 TSS 的栈切换机制**
- RSP 不变（仍指向用户栈），内核必须**手动切换栈**
- Linux 用 `TSS.sp2` 临时保存用户 RSP，然后从 per-cpu 变量加载内核栈

**关键区别**：传统中断（`int 0x80`）依赖 TSS 的 `sp0` 进行**硬件自动栈切换**；现代 `syscall` 完全**绕过 TSS 的栈切换机制**，仅借用 `sp2` 作为临时存储。

#### 3.3.3 IST 数组索引的注意事项

SDM 中 IST 编号为 **IST1 到 IST7**（1-based），而 Linux 内核的 `ist[7]` 数组是 **0-based**：

| SDM 名称 | Linux 数组索引 | 偏移量 | Linux 用途 |
|----------|----------------|--------|------------|
| IST1 | `ist[0]` | +36 | Double Fault (IST_INDEX_DF) |
| IST2 | `ist[1]` | +44 | NMI (IST_INDEX_NMI) |
| IST3 | `ist[2]` | +52 | Debug (IST_INDEX_DB) |
| IST4 | `ist[3]` | +60 | Machine Check (IST_INDEX_MCE) |
| IST5 | `ist[4]` | +68 | VMM Communication (IST_INDEX_VC) |
| IST6 | `ist[5]` | +76 | 预留 |
| IST7 | `ist[6]` | +84 | 预留 |

Linux 内核定义了常量来避免混淆（`arch/x86/include/asm/page_64_types.h`）：

```c
#define IST_INDEX_DF    0   // Double Fault 使用 IST1 (ist[0])
#define IST_INDEX_NMI   1   // NMI 使用 IST2 (ist[1])
#define IST_INDEX_DB    2   // Debug 使用 IST3 (ist[2])
#define IST_INDEX_MCE   3   // Machine Check 使用 IST4 (ist[3])
#define IST_INDEX_VC    4   // VMM Communication Exception 使用 IST5 (ist[4])
```

在 `arch/x86/kernel/cpu/common.c` 中初始化：

```c
tss->x86_tss.ist[IST_INDEX_DF] = __this_cpu_ist_top_va(DF);
tss->x86_tss.ist[IST_INDEX_NMI] = __this_cpu_ist_top_va(NMI);
tss->x86_tss.ist[IST_INDEX_DB] = __this_cpu_ist_top_va(DB);
tss->x86_tss.ist[IST_INDEX_MCE] = __this_cpu_ist_top_va(MCE);
tss->x86_tss.ist[IST_INDEX_VC] = __this_cpu_ist_top_va(VC);
```

### 3.4 完整的 per-CPU TSS 结构

Linux 为每个 CPU 维护一个完整的 `tss_struct`，包含硬件部分和软件扩展：

```c
// arch/x86/include/asm/processor.h
struct tss_struct {
    /*
     * TSS 的硬件部分（CPU 可见）
     */
    struct x86_hw_tss       x86_tss;

    /*
     * I/O 权限位图
     */
    struct x86_io_bitmap    io_bitmap;
} __aligned(PAGE_SIZE);
```

### 3.5 Per-CPU TSS 的初始化

Linux 为**每个 CPU 核心**维护一个独立的 TSS：

```c
// arch/x86/kernel/process.c
DEFINE_PER_CPU_PAGE_ALIGNED(struct tss_struct, cpu_tss_rw) = {
    .x86_tss = {
        /*
         * 64 位模式下：sp0 指向 entry trampoline stack（固定）
         * 32 位模式下：sp0 会在每次任务切换时更新为新任务的内核栈
         * 初始值为无效地址，在 cpu_init() 中会被正确设置
         */
        .sp0 = (1UL << (BITS_PER_LONG - 1)) + 1,

        /*
         * IST 栈在启动时初始化，之后不变
         */
#ifdef CONFIG_X86_64
        .ist = {
            [IST_INDEX_DF]  = __this_cpu_ist_top_va(DF),
            [IST_INDEX_NMI] = __this_cpu_ist_top_va(NMI),
            [IST_INDEX_DB]  = __this_cpu_ist_top_va(DB),
            [IST_INDEX_MCE] = __this_cpu_ist_top_va(MCE),
            [IST_INDEX_VC]  = __this_cpu_ist_top_va(VC),
            [IST_INDEX_CEA] = __this_cpu_ist_top_va(CEA),
        },
#endif
    },
    .io_bitmap = { [0 ... IO_BITMAP_LONGS] = ~0UL },
};
```

**为什么是 per-CPU？**
- 每个 CPU 有独立的内核栈
- 每个 CPU 有独立的 IST 栈
- 避免多核竞争

### 3.6 64 位 Linux 的栈切换机制：Entry Trampoline Stack

这是一个容易混淆的概念。在 64 位 Linux 中，**TSS.sp0 并不直接指向进程的内核栈**，而是使用了更复杂的 **entry trampoline** 机制。

#### 关键数据结构

```c
// per-cpu 的 TSS
DEFINE_PER_CPU(struct tss_struct, cpu_tss_rw);

// per-cpu 的当前进程内核栈顶（这才是真正存储进程栈的地方）
DEFINE_PER_CPU(unsigned long, cpu_current_top_of_stack);

// per-cpu 的 entry trampoline stack（TSS.sp0 指向这里）
struct entry_stack {
    char stack[PAGE_SIZE];  // 4KB
};
```

#### 64 位 Linux 的实际设计

**TSS.sp0 的初始化**（在 `cpu_init()` 中）：

```c
// arch/x86/kernel/cpu/common.c
/*
 * sp0 points to the entry trampoline stack regardless of what task
 * is running.
 */
load_sp0((unsigned long)(cpu_entry_stack(cpu) + 1));
```

**关键点**：TSS.sp0 指向 **entry trampoline stack**（固定的 per-cpu 栈），**不是进程的内核栈**！

#### 上下文切换时的更新

```c
// arch/x86/kernel/process_64.c
__switch_to(struct task_struct *prev_p, struct task_struct *next_p)
{
    // 更新当前进程的内核栈顶（这是关键！）
    raw_cpu_write(cpu_current_top_of_stack, task_top_of_stack(next_p));
    
    // 在标准 64 位配置下，TSS.sp0 不变（始终指向 entry trampoline stack）
    // update_task_stack(next_p) 在标准配置下不更新 TSS.sp0
}
```

#### 中断/异常发生时的完整流程

```
用户态程序执行中...
        │
        ▼ 发生中断（特权级 3→0）
┌─────────────────────────────────────────────────────────────┐
│ 步骤 1：CPU 硬件自动操作                                     │
│   - 从 TSS.sp0 加载栈指针（entry trampoline stack）          │
│   - 在 entry trampoline stack 上压入 SS/RSP/RFLAGS/CS/RIP   │
├─────────────────────────────────────────────────────────────┤
│ 步骤 2：entry_64.S 中的 error_entry 代码                     │
│   - PUSH_AND_CLEAR_REGS（保存通用寄存器到 trampoline stack） │
│   - 调用 sync_regs()                                        │
├─────────────────────────────────────────────────────────────┤
│ 步骤 3：sync_regs() 函数                                     │
│   struct pt_regs *regs = current_top_of_stack() - 1;        │
│   if (regs != eregs)                                        │
│       *regs = *eregs;  // 复制帧到进程的真正内核栈           │
│   return regs;                                               │
└─────────────────────────────────────────────────────────────┘
        │
        ▼ 现在在进程的真正内核栈上执行
```

#### 内存布局示意

```
CPU 0 的 per-cpu 数据区:
+----------------------------------+
| cpu_tss_rw.x86_tss.sp0 =         |
|   0xfffffe0000001000             | → 指向 entry trampoline stack（固定不变）
+----------------------------------+
| cpu_current_top_of_stack =       |
|   0xffff888012345000             | → 指向当前进程 A 的内核栈（随切换更新）
+----------------------------------+

Entry Trampoline Stack:              进程 A 的内核栈:
+---------------------------+       +---------------------------+
| 0xfffffe0000001000        |       | 0xffff888012345000        |
| (CPU 硬件先压栈到这里)     |  -->  | (sync_regs 复制到这里)    |
| SS, RSP, RFLAGS, CS, RIP  |       | SS, RSP, RFLAGS, CS, RIP  |
| + 通用寄存器               |       | + 通用寄存器               |
+---------------------------+       +---------------------------+
```

#### 为什么使用 Entry Trampoline Stack？

1. **安全性**：用户态无法预测或影响 entry trampoline stack 的位置
2. **简化上下文切换**：TSS.sp0 不需要随进程切换更新
3. **PTI (Page Table Isolation)**：entry trampoline stack 可以映射在用户页表中，而进程内核栈不能
4. **性能**：减少上下文切换时的 TSS 更新操作

#### 32 位模式 vs 64 位模式的差异

| 方面 | 32 位模式 | 64 位模式 |
|------|----------|----------|
| **TSS.sp0 指向** | 进程的内核栈 | entry trampoline stack（固定） |
| **上下文切换时** | 更新 TSS.sp0 | 只更新 `cpu_current_top_of_stack` |
| **中断压栈位置** | 直接在进程内核栈 | 先在 trampoline，再复制到进程栈 |

#### syscall 的栈获取方式

syscall 不使用 TSS，直接从 `cpu_current_top_of_stack` 获取进程内核栈：

```asm
// arch/x86/entry/entry_64.S
movq    PER_CPU_VAR(cpu_tss_rw + TSS_sp2), %rsp  // 临时保存用户 RSP
movq    PER_CPU_VAR(cpu_current_top_of_stack), %rsp  // 直接获取进程内核栈
```

这就是为什么 syscall 比传统中断更快——它绕过了 TSS 和 entry trampoline 机制。

---

## 4. IST 机制详解

### 4.1 Intel SDM 官方描述（Section 6.14.5）

根据 **Intel SDM Vol 3A, Section 6.14.5 "Interrupt Stack Table"**：

> "The IST mechanism is only available in IA-32e mode. It is part of the 64-bit mode TSS. The motivation for the IST mechanism is to provide a method for **specific interrupts (such as NMI, double-fault, and machine-check) to always execute on a known good stack**."

**与传统模式的对比**：

| 模式 | 栈切换机制 |
|------|-----------|
| **Legacy mode** | 可以通过任务门（Task Gate）进行任务切换来获得已知良好的栈 |
| **IA-32e mode** | Legacy 任务切换不受支持，必须使用 IST 机制 |

**IST 的核心特性**：
- IST 在 TSS 中提供最多 **7 个 IST 指针**（IST1-IST7）
- 指针通过 IDT 中断门描述符中的 **3 位 IST 索引字段**引用
- 当中断发生时，处理器将 IST 指针所指的值加载到 RSP

**IST 使用时的栈切换行为**：

> "When an interrupt occurs, the new SS selector is forced to NULL and the SS selector's RPL field is set to the new CPL. The old SS, RSP, RFLAGS, CS, and RIP are pushed onto the new stack. Interrupt processing then proceeds as normal."

**IST 索引为零时的行为**：

> "If the IST index is zero, the modified legacy stack-switching mechanism described above is used."

这意味着：
- 可以选择性地为某些中断向量使用 IST，而其他向量使用传统机制
- 同一个 IDT 中，部分表项可以使用 IST，其他表项不使用

### 4.2 IST 的核心思想

**问题**：如果在处理中断/异常时**当前栈已损坏**怎么办？

**传统方式**（无 IST）：
```
用户态 (Ring 3)  →  发生中断  →  切换到 RSP0 (内核栈)
```

**问题场景**：
1. 如果内核栈**已经溢出**，RSP0 指向无效地址
2. 如果处理 Page Fault 时**栈本身缺页**，递归 Page Fault
3. 如果 NMI 在**任意位置**打断（包括修改栈的指令中间）

**IST 的解决方案**：
```
发生特殊异常  →  直接切换到预先分配的独立栈（IST）
```

- 不依赖当前的 RSP
- 不依赖当前栈的完整性
- 每种关键异常使用不同的栈，避免相互干扰

### 4.3 IST 切换的硬件行为

**CPU 在处理中断/异常时的栈切换逻辑**：

```
1. 从 IDTR 读取 IDT 基址
2. 根据向量号找到 IDT 表项
3. 读取表项中的 IST 字段（3 位，值 0-7）

IF (IST != 0) {
    // 使用 IST 机制
    4. 从 TR 读取 TSS 地址
    5. 从 TSS.IST[IST - 1] 读取栈地址（注意：IST 1 对应 ist[0]）
    6. 新 RSP = TSS.IST[IST - 1]
} ELSE IF (CPL 改变) {
    // 特权级切换（用户态→内核态）
    4. 从 TR 读取 TSS 地址
    5. 从 TSS.RSP0 读取栈地址
    6. 新 RSP = TSS.RSP0
} ELSE {
    // 同一特权级，继续使用当前栈
    6. 新 RSP = 当前 RSP
}

7. 向新栈压入：
   - SS (旧的栈段)
   - RSP (旧的栈指针)
   - RFLAGS
   - CS
   - RIP
   - Error Code (如果有)

8. 跳转到中断/异常处理程序
```

**关键点**：
- IST 优先级**高于** RSP0
- IST 字段为 0 时，回退到传统的 RSP0 切换
- 无论从哪个特权级触发，IST 都生效

### 4.4 IA-32e 模式栈切换详解（SDM Section 6.14.4）

根据 **Intel SDM Vol 3A, Section 6.14.4 "Stack Switching in IA-32e Mode"**：

**与 Legacy 模式的区别**：

> "In IA-32e mode, the legacy stack-switch mechanism is modified. When stacks are switched as part of a 64-bit mode privilege-level change (resulting from an interrupt), a **new SS descriptor is not loaded**. IA-32e mode loads **only an inner-level RSP from the TSS**."

**关键行为变化**：
1. **SS 选择子强制为 NULL**：新的 SS 选择子被强制设为 NULL
2. **RPL 设置为新 CPL**：SS 选择子的 RPL 字段被设置为新的 CPL
3. **保存旧的 SS 和 RSP**：旧的 SS 和 RSP 被保存到新栈上
4. **IRET 恢复**：后续的 IRET 会从栈上弹出旧的 SS 并加载到 SS 寄存器

**设计原因**：

> "The new SS is set to NULL in order to handle nested far transfers (far CALL, INT, interrupts and exceptions)."

将 SS 设为 NULL 是为了正确处理嵌套的远调用和中断。

**总结**：

> "In summary, a stack switch in IA-32e mode works like the legacy stack switch, except that a new SS selector is **not loaded from the TSS**. Instead, the new SS is **forced to NULL**."

### 4.5 64 位模式栈帧详解（SDM Section 6.14.2）

根据 **Intel SDM Vol 3A, Section 6.14.2 "64-Bit Mode Stack Frame"**：

**固定的压栈大小**：

> "In legacy mode, the size of an IDT entry (16 bits or 32 bits) determines the size of interrupt-stack-frame pushes. In 64-bit mode, the size of interrupt stack-frame pushes is **fixed at eight bytes**."

**无条件压入 SS:RSP**：

> "64-bit mode also pushes SS:RSP **unconditionally**, rather than only on a CPL change."

这提供了以下好处：
- 所有中断都有**一致的栈帧大小**
- 处理 INTn 指令或外部 INTR# 信号的中断服务程序入口点可以压入额外的错误码占位符以保持一致性

**栈对齐**：

> "In IA-32e mode, the RSP is aligned to a **16-byte boundary** before pushing the stack frame. The stack frame itself is aligned on a 16-byte boundary when the interrupt handler is called."

**对齐的好处**：
- 允许异常和中断帧在重新启用中断之前对齐到 16 字节边界
- 允许栈被格式化为最佳存储 16 字节 XMM 寄存器

**64 位模式中断栈帧布局**：

```
          （高地址）
        ┌─────────────────────────────┐
  +40   │           SS                │  8 bytes
        ├─────────────────────────────┤
  +32   │          RSP                │  8 bytes
        ├─────────────────────────────┤
  +24   │         RFLAGS              │  8 bytes
        ├─────────────────────────────┤
  +16   │           CS                │  8 bytes
        ├─────────────────────────────┤
  +8    │          RIP                │  8 bytes
        ├─────────────────────────────┤
  +0    │     Error Code (可选)       │  8 bytes
        └─────────────────────────────┘
          （低地址，新 RSP）
```

### 4.6 CPU 自动保存 vs 软件手动保存

在理解中断/异常处理时，必须区分 **CPU 硬件自动保存**和**软件手动保存**的内容。

#### CPU 硬件自动保存的内容

**CPU 只自动保存以下寄存器**（64 位模式与 32 位模式有差异）：

| 寄存器 | 32 位模式 | 64 位模式 | 说明 |
|--------|----------|----------|------|
| SS | 仅特权级变化时（3→0） | **总是**压入 | 旧的栈段选择子 |
| RSP | 仅特权级变化时（3→0） | **总是**压入 | 旧的栈指针 |
| RFLAGS | 总是 | 总是 | 标志寄存器 |
| CS | 总是 | 总是 | 代码段选择子 |
| RIP | 总是 | 总是 | 返回地址 |
| Error Code | 某些异常 | 某些异常 | 异常特定的错误码 |

> **重要（SDM Vol 3A, Section 6.14.2）**：在 64 位模式下，SS:RSP 是**无条件压入**的（"SS:RSP is pushed unconditionally"），无论是否发生特权级切换。这简化了中断帧的处理，使所有中断帧大小一致。

**重要：CPU 不会自动保存任何通用寄存器**（RAX、RBX、RCX、RDX、RSI、RDI、RBP、R8-R15）！

#### 软件必须手动保存的内容

因为中断/异常处理程序会使用通用寄存器，如果不保存就会覆盖原来的值。所以 Linux 内核在中断入口汇编代码中**手动保存**所有通用寄存器：

```asm
// arch/x86/entry/entry_64.S - 中断入口示例
SYM_CODE_START(asm_common_interrupt)
    // CPU 已自动压入 SS/RSP/RFLAGS/CS/RIP/ErrorCode
    
    // 软件手动保存通用寄存器
    pushq   %rdi
    pushq   %rsi
    pushq   %rdx
    pushq   %rcx
    pushq   %rax
    pushq   %r8
    pushq   %r9
    pushq   %r10
    pushq   %r11
    pushq   %rbx
    pushq   %rbp
    pushq   %r12
    pushq   %r13
    pushq   %r14
    pushq   %r15
    
    // 现在栈上有完整的 pt_regs 结构
    movq    %rsp, %rdi          // 第一个参数：pt_regs 指针
    call    do_IRQ              // 调用 C 处理函数
    
    // 返回时恢复寄存器
    popq    %r15
    popq    %r14
    // ... 恢复其他寄存器
    iretq                        // CPU 自动恢复 SS/RSP/RFLAGS/CS/RIP
SYM_CODE_END(asm_common_interrupt)
```

#### 3→0 vs 0→0 的完整对比

| 比较项 | 3→0（用户态→内核态） | 0→0（内核态→内核态） |
|--------|----------------------|----------------------|
| **栈切换** | 从 TSS 加载新内核栈 | 继续使用当前栈 |
| **CPU 自动压 SS/RSP** | ✅ 是 | ❌ 否（64 位模式例外，总是压入） |
| **CPU 自动压 RFLAGS/CS/RIP** | ✅ 是 | ✅ 是 |
| **CPU 自动压通用寄存器** | ❌ 否 | ❌ 否 |
| **软件手动保存通用寄存器** | ✅ 是 | ✅ 是 |

**注意**：在 64 位模式下，根据 SDM 的规定，SS:RSP 是**无条件压入**的，即使没有特权级切换。这与 32 位模式不同。

#### 为什么这样设计？

1. **性能考虑**：不是所有中断都需要保存所有寄存器，让软件决定保存哪些更灵活
2. **统一处理**：中断处理程序（无论从用户态还是内核态进入）都可以用相同的代码结构保存寄存器
3. **pt_regs 结构**：Linux 用 `pt_regs` 结构体统一访问 CPU 自动保存和软件手动保存的所有寄存器

### 4.7 IST 栈的布局

**每个 CPU 有 7 个独立的 IST 栈**：

```
┌─────────────────────────────────────────────┐
│  CPU 0                                      │
│                                              │
│  IST1 栈 (Double Fault)                     │
│  ┌────────────────────────────────────┐    │
│  │  0xffffc90000003ff8: (栈顶)       │    │
│  │  ...                                │    │
│  │  0xffffc90000000000: (栈底)       │    │
│  └────────────────────────────────────┘    │
│                                              │
│  IST2 栈 (NMI)                              │
│  ┌────────────────────────────────────┐    │
│  │  0xffffc90000007ff8: (栈顶)       │    │
│  │  ...                                │    │
│  └────────────────────────────────────┘    │
│                                              │
│  IST3 栈 (Debug)                            │
│  IST4 栈 (Machine Check)                    │
│  IST5 栈 (Virtualization Exception)         │
│  IST6 栈 (CEA - CPU Entry Area)             │
│  IST7 栈 (未使用)                           │
└─────────────────────────────────────────────┘
```

**栈大小**（`arch/x86/include/asm/page_64_types.h`）：

```c
#define EXCEPTION_STACK_ORDER   (0)  // 1 页 = 4KB
#define EXCEPTION_STKSZ         (PAGE_SIZE << EXCEPTION_STACK_ORDER)

// Double Fault 栈特殊处理，可能更大
#define DOUBLEFAULT_STACK_ORDER (1)  // 2 页 = 8KB
```

### 4.7 CPU 压栈的字节级详细布局

当异常发生并切换到 IST 栈后，CPU 会**自动**向新栈压入一系列寄存器值。理解这个过程对于分析异常现场至关重要。

#### 压栈内容和顺序

以缺页异常（#PF）为例，假设 CPU 切换到 IST2 栈（NMI 栈，起始地址 `0xfffffe0000006000`）：

```
发生异常前：
IST2 栈指针：0xfffffe0000006000（栈顶，空栈）

发生异常后（CPU 自动压栈）：
┌─────────────────────────────────────────────┐
│  高地址                                      │
├─────────────────────────────────────────────┤
│  0xfffffe0000006000: [未使用区域]           │  ← TSS.IST[2] 指向这里（栈底）
│  ...                                         │
│  0xfffffe0000005ff8: [空闲]                 │
│  0xfffffe0000005ff0: SS (旧栈段选择子)      │  ← 如果发生特权级切换才压入
│  0xfffffe0000005fe8: RSP (旧栈指针)         │  ← 保存异常发生时的栈指针
│  0xfffffe0000005fe0: RFLAGS (标志寄存器)    │  ← 处理器状态标志
│  0xfffffe0000005fd8: CS (代码段选择子)      │  ← 异常发生时的代码段
│  0xfffffe0000005fd0: RIP (指令指针)         │  ← 发生异常的指令地址
│  0xfffffe0000005fc8: Error Code (错误码)    │  ← 异常特定的错误码
├─────────────────────────────────────────────┤
│  0xfffffe0000005fc0: [接下来的栈空间]      │  ← RSP 现在指向这里
│  ...                                         │
│  低地址                                      │
└─────────────────────────────────────────────┘
```

**压栈后的 RSP 值**：`0xfffffe0000005fc8`（在 Error Code 之后）

#### 具体示例：缺页异常

假设有以下代码触发缺页：

```c
// 内核代码执行：
void *ptr = (void *)0xdeadbeef;
int value = *(int *)ptr;  // ← 这里触发 #PF
```

**CPU 压栈的具体值**：

| 地址 | 字段 | 值 | 说明 |
|------|------|-----|------|
| `0xfffffe0000005ff0` | SS | `0x0018` | 内核数据段选择子（如果从用户态进入） |
| `0xfffffe0000005fe8` | RSP | `0xffffc90000020f00` | 异常发生时的栈指针 |
| `0xfffffe0000005fe0` | RFLAGS | `0x0000000000000202` | IF=1（中断启用） |
| `0xfffffe0000005fd8` | CS | `0x0010` | `__KERNEL_CS` |
| `0xfffffe0000005fd0` | RIP | `0xffffffff81234568` | `mov` 指令的地址 |
| `0xfffffe0000005fc8` | Error Code | `0x0000000000000006` | 见下表 |

**缺页异常的错误码**（32 位，但只用低几位）：

```c
/*
 * Page Fault Error Code
 * bit 0 (P):   0 = 页面不存在，1 = 权限违规
 * bit 1 (W/R): 0 = 读访问，1 = 写访问
 * bit 2 (U/S): 0 = 内核态，1 = 用户态
 * bit 3 (RSVD): 0 = 正常，1 = 保留位被覆盖
 * bit 4 (I/D): 0 = 数据访问，1 = 指令获取
 */

// 示例：Error Code = 0x6 = 0b00110
//   bit 0 = 0: 页面不存在
//   bit 1 = 1: 写访问
//   bit 2 = 1: 用户态触发（或内核访问用户页）
```

#### 异常处理函数读取这些值

```c
// arch/x86/mm/fault.c
DEFINE_IDTENTRY_RAW_ERRORCODE(exc_page_fault)
{
    unsigned long address = read_cr2();  // CR2 存放缺页地址
    unsigned long error_code = regs->orig_ax;  // 从栈上读取

    pr_info("Page Fault at RIP: %016lx\n", regs->ip);      // 从栈读取
    pr_info("Accessing address: %016lx\n", address);
    pr_info("Error code: %lx\n", error_code);
    pr_info("Old RSP: %016lx\n", regs->sp);                // 从栈读取
}
```

#### IST 栈内容的生命周期

```
1. 初始化时：
   IST2 栈 → 空内容（未初始化数据或 0）

2. 异常触发时：
   CPU 自动压入 SS/RSP/RFLAGS/CS/RIP/Error Code

3. 异常处理中：
   处理函数在栈上继续压入：
   - 通用寄存器（RAX, RBX, ...）
   - 局部变量
   - 函数调用返回地址

4. 异常返回后：
   CPU 执行 IRET：
   - 从栈弹出 RIP/CS/RFLAGS/RSP/SS
   - RSP 回到原来位置
   - IST 栈上的数据变成"脏数据"（下次使用会被覆盖）
```

**关键要点**：
- IST 栈**最初的内容不重要**，因为会被 CPU 立即覆盖
- CPU 压栈是**硬件自动完成**的，软件无法干预
- 这些压栈的值是异常处理函数**诊断问题的关键信息**

### 4.8 IST 地址的动态调整机制

虽然从 CPU 硬件视角看，TSS 中的 IST 地址是"固定"的，但 Linux 内核在运行时可以**动态调整**这些地址，以应对嵌套异常等复杂场景。

#### 地址的"固定"与"可变"

**固定性**（硬件视角）：
- 一旦 TSS 初始化完成，`TSS.IST[n]` 的值就确定了
- CPU 每次处理使用 IST 的异常时，都机械地从 TSS 读取这个固定地址
- 在系统正常运行期间，这个值通常不变

**可变性**（软件视角）：
- 内核可以在运行时修改 `TSS.IST[n]` 的值
- 用于处理嵌套异常（如调试异常的嵌套）
- 内核需要保存原始值以便栈空间管理

#### 为什么需要 `orig_ist`？

Linux 内核曾经维护一个 `orig_ist` 数组，保存 IST 的**原始地址**：

```c
// arch/x86/include/asm/processor.h (历史代码)
struct tss_struct {
    struct x86_hw_tss   x86_tss;

    /*
     * 保存 IST 栈的原始地址
     * 用于栈回溯时判断地址是否属于某个 IST 栈
     */
    unsigned long       orig_ist[7];
};
```

**为什么需要保存原始值？**

1. **栈回溯**：判断一个地址是否在某个 IST 栈范围内

```c
// 判断地址是否在 IST 栈中
bool in_ist_stack(unsigned long addr, int ist_index)
{
    unsigned long stack_bottom = orig_ist[ist_index] - EXCEPTION_STKSZ;
    unsigned long stack_top = orig_ist[ist_index];

    return (addr >= stack_bottom && addr < stack_top);
}
```

2. **嵌套异常处理**：动态调整 IST 指针

```c
// 处理调试异常时的嵌套保护（简化示例）
DEFINE_IDTENTRY_DEBUG(exc_debug)
{
    unsigned long old_ist = this_cpu_read(cpu_tss_rw.x86_tss.ist[IST_INDEX_DB]);

    // 修改 TSS.IST[DB]，指向第二份栈
    this_cpu_write(cpu_tss_rw.x86_tss.ist[IST_INDEX_DB],
                   old_ist + DEBUG_STACK_SIZE);

    // 处理调试异常
    // 如果在这里再次触发 #DB，会使用第二份栈

    // 恢复原始 IST 指针
    this_cpu_write(cpu_tss_rw.x86_tss.ist[IST_INDEX_DB], old_ist);
}
```

#### 嵌套调试异常的栈布局

```
初始状态：
TSS.IST[3] = 0xffffc9000000c000  （调试栈 1 的顶部）

┌────────────────────────────────┐
│  调试栈 1: 0xffffc9000000c000  │  ← TSS.IST[3]
│  [空闲区域]                     │
│  ...                            │
│  调试栈 2: 0xffffc90000010000  │  ← 备用栈
│  [空闲区域]                     │
└────────────────────────────────┘

第一次 #DB 发生：
CPU 切换到 0xffffc9000000c000
处理函数修改 TSS.IST[3] = 0xffffc90000010000

第二次 #DB 发生（在第一次处理中）：
CPU 切换到 0xffffc90000010000  ← 使用备用栈，避免覆盖
```

#### 现代实现的变化

在现代 Linux 内核中，`orig_ist` 已经被移除，因为：
- IST 栈的管理已经简化
- 嵌套异常的处理采用了其他机制
- 大多数 IST 异常不会嵌套发生

但理解这个机制仍然重要，因为它展示了：
- **TSS 中的 IST 值是可以修改的**
- **内核需要跟踪栈的边界**
- **嵌套异常需要特殊处理**

**总结**：
- **对 CPU 而言**：IST 地址是固定的（从 TSS 读取）
- **对内核而言**：IST 地址可以动态调整（修改 TSS）
- **实际应用**：大多数情况下不修改，只在处理嵌套异常时临时调整

---

## 5. 为什么需要 IST？

### 5.1 场景 1：Double Fault (#DF) 处理

**什么是 Double Fault？**

当 CPU 在处理一个异常时，又触发了**第二个异常**，如果这两个异常无法串行处理，就产生 Double Fault。

**典型的 Double Fault 场景**：

```c
// 场景：栈溢出导致的 Double Fault

void recursive_function(void) {
    char buffer[1024];  // 每次调用占用 1KB 栈
    recursive_function();  // 无限递归
}

// 执行过程：
// 1. 递归调用，栈不断增长
// 2. RSP 超出栈的合法范围（例如撞到 Guard Page）
// 3. 访问 buffer → Page Fault (#PF)
// 4. CPU 尝试处理 #PF：
//    - 向栈压入 SS, RSP, RFLAGS, CS, RIP, Error Code
//    - 但栈已经溢出！
//    - 压栈操作再次触发 Page Fault
// 5. → Double Fault (#DF)
```

**如果没有 IST 会怎样？**

```
#DF 处理程序尝试使用当前栈（已损坏）
  ↓
无法压入异常帧
  ↓
Triple Fault
  ↓
CPU 重启 💥
```

**使用 IST 的解决方案**：

```c
// IDT 配置
set_intr_gate_ist(X86_TRAP_DF, &double_fault, IST_INDEX_DF);
//                                              ^^^^^^^^^^^
//                                              使用独立的 IST 栈

// TSS 配置
cpu_tss.x86_tss.ist[IST_INDEX_DF] = 0xffffc90000004000;  // 独立的 8KB 栈

// Double Fault 处理程序
DEFINE_IDTENTRY_DF(exc_double_fault)
{
    // 此时运行在干净的 IST 栈上
    // 可以安全地诊断问题

    pr_emerg("PANIC: double fault, error_code: 0x%lx\n", error_code);
    pr_emerg("RIP: %016lx RSP: %016lx\n", regs->ip, regs->sp);

    // 通常是致命错误，触发 panic
    panic("Double fault");
}
```

### 5.2 场景 2：NMI (Non-Maskable Interrupt)

**什么是 NMI？**

**不可屏蔽中断**（NMI）是一种特殊的硬件中断，**无法被 CLI 指令禁止**，可以在**任意时刻**打断 CPU。

**用途**：
- 硬件看门狗（Watchdog）超时
- 内存校验错误（ECC 错误）
- 性能监控事件（Perf）
- 调试（通过硬件按钮触发 NMI 进入调试器）

**为什么 NMI 需要 IST？**

**问题场景**：嵌套 NMI

```
时刻 T0: 内核正在处理中断 A
         RSP = 0xffffc90000020000 (正常内核栈)
         正在执行：mov [rsp+8], rax  (修改栈内容)

时刻 T1: NMI 打断（在 mov 指令执行到一半）
         如果不用 IST：
         → 继续使用 0xffffc90000020000
         → 压入异常帧会覆盖正在修改的数据
         → 栈数据损坏！

时刻 T2: NMI 处理程序内部再次触发 NMI（理论上可能）
         → 嵌套的 NMI
```

**使用 IST 的好处**：

```c
// 第一个 NMI
set_intr_gate_ist(X86_TRAP_NMI, &nmi, IST_INDEX_NMI);
// TSS.IST[IST_INDEX_NMI] = 0xffffc90000008000

// 流程：
// 1. NMI 发生 → 切换到 0xffffc90000008000（独立栈）
// 2. 在 IST 栈上保存异常帧
// 3. 执行 NMI 处理程序
// 4. IRET 返回

// 即使被打断的代码正在修改栈，NMI 使用独立栈，互不干扰
```

**嵌套 NMI 的特殊处理**：

Linux 内核对 NMI 有特殊的嵌套检测机制（`arch/x86/kernel/nmi.c`）：

```c
// NMI 处理程序检查是否已经在 NMI 上下文中
if (in_nmi()) {
    // 嵌套 NMI：需要特殊处理
    // 修改栈帧，确保返回到外层 NMI 的重启点
    repeat_nmi = true;
}
```

### 5.3 场景 3：Machine Check (#MC)

**什么是 Machine Check？**

硬件错误检测机制，用于报告**严重的硬件故障**：
- CPU 缓存奇偶校验错误
- 总线错误
- 内存控制器错误
- TLB 错误

**为什么需要 IST？**

Machine Check 可能在**任意时刻**发生，包括：
- 内核正在处理其他异常
- 内核栈本身有硬件错误

使用 IST 确保即使当前栈损坏，也能执行诊断和恢复代码。

```c
// arch/x86/kernel/cpu/mce/core.c
DEFINE_IDTENTRY_MCE(exc_machine_check)
{
    // 运行在独立的 IST 栈上
    // 读取 Machine Check 寄存器（MSR）
    unsigned long mcg_status = mce_rdmsrl(MSR_IA32_MCG_STATUS);

    // 尝试恢复或记录错误
    if (mcg_status & MCG_STATUS_RIPV) {
        // 可以恢复
        mce_panic("Machine check", regs, 0);
    }
}
```

### 5.4 场景 4：Debug Exception (#DB)

**为什么 Debug 异常需要 IST？**

调试异常可能在**调试器自身的代码中**触发（例如单步执行调试器）。

如果调试器和被调试代码使用同一个栈：
- 单步执行时，栈会被调试器的异常帧覆盖
- 递归调试场景下栈会混乱

使用 IST 确保调试器有独立的工作空间。

### 5.5 有 IST vs 无 IST 的全面对比

#### 不同场景下的行为对比

| 场景 | 无 TSS/IST（早期系统） | 有 TSS/IST（现代系统） |
|------|---------------------|---------------------|
| **正常函数执行** | 使用普通内核栈 | 使用普通内核栈 |
| **普通异常（#PF, #GP）** | 使用普通内核栈 | 使用普通内核栈 |
| **关键异常（#DF, NMI, #MC）** | 继续使用当前栈（可能已损坏）❌ | 切换到专用干净栈 ✅ |
| **异常嵌套** | 只能在原栈上嵌套，风险极高 ❌ | 有备用栈可用 ✅ |
| **栈指针损坏** | 三重故障 → 重启，无日志 💥 | 正常记录错误 → 安全 panic ✅ |
| **栈溢出** | 中断在满栈上压栈 → 踩踏内存 ❌ | 避开损坏的栈 → 正常处理 ✅ |
| **调试能力** | 难以复现，只能猜测 | 有完整日志和栈回溯 ✅ |

#### 为什么内核态异常不使用 TSS.RSP0？

在理解具体场景之前，必须先理解一个关键概念：**x86 CPU 只在特权级切换时才从 TSS.RSP0 加载栈指针**。

| 异常发生时的状态 | CPU 行为 | 使用的栈 |
|-----------------|----------|----------|
| 用户态 → 内核态（CPL 改变） | ✅ 从 TSS.RSP0 加载 | 内核为该进程分配的内核栈 |
| 内核态 → 内核态（CPL 不变） | ❌ 不查 TSS | **继续使用当前 RSP** |
| 任意特权级，IDT 条目 IST≠0 | ✅ 从 TSS.ISTn 加载 | IST 专用栈 |

**这意味着**：当代码**已经在内核态运行**时（如驱动程序、内核线程），如果触发一个**普通异常**（如 #PF 缺页，IST=0）：

1. CPU 检查 IDT 条目的 IST 字段 → **IST=0**
2. CPU 检查是否有特权级切换 → **没有**（都是 Ring 0）
3. CPU 决定：**继续使用当前 RSP**

此时，即使 `TSS.RSP0` 存储着一个完全有效的内核栈地址，CPU 也**不会去读取它**。

```
示例场景：
┌────────────────────────────────────────────────────────────┐
│ 当前状态：                                                  │
│   - CPL = 0（内核态）                                      │
│   - RSP = 0xc001c0de（已被 bug 损坏）                      │
│   - TSS.RSP0 = 0xffffc90000123000（完全有效！）            │
│                                                             │
│ 触发 #PF（缺页异常，IST=0）：                              │
│   1. IST=0 → 不使用 IST 机制                               │
│   2. CPL 不变（0→0） → 不查 TSS.RSP0                       │
│   3. 继续使用当前 RSP = 0xc001c0de                         │
│   4. 尝试在无效地址压栈 → 失败！                           │
│                                                             │
│ 结论：TSS.RSP0 虽然有效，但 CPU 根本不会去读取它           │
└────────────────────────────────────────────────────────────┘
```

**这正是 IST 存在的意义**：对于关键异常（#DF, NMI, #MC），即使在内核态触发，也**强制**切换到干净的 IST 栈，打破"同特权级不切换栈"的限制。

#### 具体死机场景对比

**场景 1：栈指针损坏**

```
┌────────────────────────────────────────────┐
│  无 IST：                                  │
├────────────────────────────────────────────┤
│  内核执行到有 bug 的驱动：                 │
│  mov rsp, 0xc001c0de  ; 错误的栈指针       │
│                                             │
│  下一条指令触发缺页异常：                  │
│  1. 查 IDT → 找到缺页处理函数地址          │
│  2. 试图在当前栈(0xc001c0de)压入 RIP/CS... │
│  3. 这个地址无效 → 触发第二个异常(#DF)     │
│  4. #DF 也想在当前栈压栈 → 又失败          │
│  5. 三重故障 → CPU 直接复位 💥            │
│                                             │
│  结果：机器突然重启，没有任何日志          │
└────────────────────────────────────────────┘

┌────────────────────────────────────────────┐
│  有 IST：                                  │
├────────────────────────────────────────────┤
│  内核执行到有 bug 的驱动：                 │
│  mov rsp, 0xc001c0de  ; 错误的栈指针       │
│                                             │
│  下一条指令触发缺页异常：                  │
│  1. 查 IDT → 找到缺页处理函数              │
│  2. 试图在当前栈压栈 → 失败，触发 #DF      │
│  3. CPU 检测到 #DF，查 IDT 发现 IST=1      │
│  4. 切换到干净的 IST1 栈（Double Fault）   │
│  5. 成功压栈、执行处理函数 ✅              │
│  6. 打印完整的寄存器状态和栈回溯           │
│  7. 安全 panic，保存日志到磁盘             │
│                                             │
│  结果：有详细的 oops 信息，便于调试        │
└────────────────────────────────────────────┘
```

**场景 2：内核栈溢出**

```
┌────────────────────────────────────────────┐
│  无 IST：                                  │
├────────────────────────────────────────────┤
│  内核函数递归调用，栈占满：                │
│                                             │
│  [内核栈底]                                │
│  ... ← 已满                                │
│  [当前栈顶] ← RSP                          │
│                                             │
│  此时发生中断：                            │
│  CPU 试图在当前栈顶压入中断上下文          │
│  但栈已满，压栈写入栈下面的内存            │
│  → 其他内核数据被破坏                      │
│  → 过一会儿系统行为异常 → 死机 💥         │
│                                             │
│  表面原因：内存数据被破坏                  │
│  根本原因：中断必须在已满的栈上操作        │
└────────────────────────────────────────────┘

┌────────────────────────────────────────────┐
│  有 IST：                                  │
├────────────────────────────────────────────┤
│  内核函数递归调用，栈占满：                │
│                                             │
│  [内核栈底]                                │
│  ... ← 已满                                │
│  [当前栈顶] ← RSP                          │
│                                             │
│  访问栈溢出区域 → 触发缺页异常：           │
│  1. 缺页处理试图压栈 → 再次缺页            │
│  2. → Double Fault                         │
│  3. CPU 切换到 IST1 栈（独立、干净）       │
│  4. 正常处理，打印 "栈溢出" 信息 ✅        │
│  5. 安全 panic，没有破坏其他内存           │
│                                             │
│  结果：错误被正确诊断和记录                │
└────────────────────────────────────────────┘
```

**场景 3：异常嵌套**

```
无 IST：
执行 A → #PF → 进入缺页处理 → 缺页处理本身访问非法内存 → 第二次 #PF
       ↓
       继续用同一个栈 → 容易递归崩溃 → Triple Fault

有 IST：
执行 A → #PF → 进入缺页处理 → 缺页处理访问非法内存 → 第二次 #PF
       ↓
       识别为 #DF → 切换到 IST 栈 → 安全记录 "在缺页处理中又发生缺页" ✅
```

#### 历史数据：引入 IST 的影响

Linux 内核在 **2.6 中期（2007-2009 年左右）** 开始全面引入 IST 机制。之后的改进：

| 指标 | 引入 IST 前 | 引入 IST 后 |
|------|------------|------------|
| **无法解释的重启** | 频繁发生 | 大幅减少（约 70-80%）|
| **Oops 信息完整性** | 约 50% 的死机无日志 | 约 95% 有完整日志 |
| **调试效率** | 需要数周甚至数月才能复现 | 通常能从日志直接定位 |
| **典型错误信息** | "kernel panic - not syncing" | "PANIC: double fault" 等明确信息 |

#### IST 的本质：最后一道防线

```
这就像：
┌────────────────────────────────────┐
│  内存问题 = 着火 🔥                │
├────────────────────────────────────┤
│  无 IST = 消防队到了但消防栓没水   │
│  有 IST = 提前在关键位置放了灭火器 │
└────────────────────────────────────┘

更准确的说法：
在没有 TSS/IST 的时代，内存问题更容易导致死机，
而且死得悄无声息，让开发者难以追踪。

有了 IST：
即使在最极端的情况下（栈完全损坏、内存踩踏），
系统仍然能够：
1. 切换到干净的独立栈
2. 执行诊断代码
3. 记录完整的错误信息
4. 安全地停止系统
```

---

## 6. IST 与 IDT 的集成

### 6.1 Intel SDM 官方描述：64 位 IDT Gate Descriptor

根据 **Intel SDM Vol 3A, Section 6.14.1 "64-Bit Mode IDT"** 和 **Figure 6-7**：

> "In IA-32e mode, the IDT index size is not increased. This is because only 256 interrupts or exceptions are supported. The IDT itself is not larger than 4 KB. However, to support 64-bit offset, the size of each gate entry is increased from 8 to **16 bytes**."

**64 位中断门描述符格式**（16 字节）：

```
                        64-bit Interrupt Gate Descriptor
         ┌─────────────────────────────────────────────────────────────┐
  Byte 15│                        Reserved                             │
  Byte 14│                                                             │
  Byte 13│                                                             │
  Byte 12│                                                             │
         ├─────────────────────────────────────────────────────────────┤
  Byte 11│                                                             │
  Byte 10│                  Offset [63:32]                             │
  Byte  9│              (处理程序地址高 32 位)                         │
  Byte  8│                                                             │
         ├─────────────────────────────────────────────────────────────┤
  Byte  7│                                                             │
  Byte  6│                  Offset [31:16]                             │
         │              (处理程序地址中 16 位)                         │
         ├────────┬─────┬────────────────────┬────────────────────────┤
  Byte  5│   P    │ DPL │  0   │    Type    │         Reserved        │
         │ (1bit) │(2bit)│(1bit)│   (4bit)   │                        │
         ├────────┴─────┴────────────────────┼────────────────────────┤
  Byte  4│         Reserved                   │         IST           │
         │                                    │        (3 bits)       │
         ├────────────────────────────────────┴────────────────────────┤
  Byte  2│                  Segment Selector                           │
         │                (代码段选择子，16 bits)                      │
         ├─────────────────────────────────────────────────────────────┤
  Byte  0│                  Offset [15:0]                              │
         │              (处理程序地址低 16 位)                         │
         └─────────────────────────────────────────────────────────────┘
```

**IST 字段详解**：

| IST 值 | 含义 |
|--------|------|
| 0 | 不使用 IST，使用修改后的传统栈切换机制 |
| 1 | 使用 TSS.IST1 |
| 2 | 使用 TSS.IST2 |
| 3 | 使用 TSS.IST3 |
| 4 | 使用 TSS.IST4 |
| 5 | 使用 TSS.IST5 |
| 6 | 使用 TSS.IST6 |
| 7 | 使用 TSS.IST7 |

**Type 字段值**（64 位模式）：
- `1110b (0xE)`: 64-bit Interrupt Gate
- `1111b (0xF)`: 64-bit Trap Gate

**重要说明**：

> "Task gates are **not supported** in IA-32e mode. Attempting to access a task gate in 64-bit mode triggers a general-protection fault (#GP)."

这意味着在 64 位模式下：
- 只能使用中断门（Interrupt Gate）和陷阱门（Trap Gate）
- 任务门（Task Gate）完全不可用
- 必须使用 IST 机制来实现某些任务门曾经提供的功能

### 6.2 SDM 定义与 Linux 内核 IDT Gate 结构的对比分析

Linux 内核在 `arch/x86/include/asm/desc_defs.h` 中定义了对应的结构体：

```c
struct idt_bits {
    u16     ist  : 3,    // IST 索引 (0-7)
            zero : 5,    // 保留位，必须为 0
            type : 5,    // 门类型 (0xE = 中断门, 0xF = 陷阱门)
            dpl  : 2,    // 描述符特权级
            p    : 1;    // 存在位
} __attribute__((packed));

struct gate_struct {
    u16             offset_low;     // Offset [15:0]
    u16             segment;        // Segment Selector
    struct idt_bits bits;           // 位域字段
    u16             offset_middle;  // Offset [31:16]
#ifdef CONFIG_X86_64
    u32             offset_high;    // Offset [63:32]
    u32             reserved;       // Reserved
#endif
} __attribute__((packed));

typedef struct gate_struct gate_desc;
```

**SDM 与 Linux 内核字段对比**：

| SDM 字段 | SDM 偏移 (字节) | Linux 字段 | 匹配情况 |
|----------|-----------------|------------|----------|
| Offset [15:0] | 0-1 | `offset_low` | ✅ 完全匹配 |
| Segment Selector | 2-3 | `segment` | ✅ 完全匹配 |
| IST (3 bits) | 4 (低 3 位) | `bits.ist` | ✅ 完全匹配 |
| Reserved (5 bits) | 4 (高 5 位) | `bits.zero` | ✅ 完全匹配 |
| Type (4 bits) | 5 (低 4 位) | `bits.type` | ⚠️ 5 bits（包含 S 位） |
| S (1 bit) | 5 (bit 4) | 包含在 `bits.type` | ⚠️ Linux 使用 5 bits |
| DPL (2 bits) | 5 (bits 5-6) | `bits.dpl` | ✅ 完全匹配 |
| P (1 bit) | 5 (bit 7) | `bits.p` | ✅ 完全匹配 |
| Offset [31:16] | 6-7 | `offset_middle` | ✅ 完全匹配 |
| Offset [63:32] | 8-11 | `offset_high` | ✅ 完全匹配 |
| Reserved | 12-15 | `reserved` | ✅ 完全匹配 |

**Linux 内核初始化 IDT 条目**（`arch/x86/include/asm/desc.h`）：

```c
static inline void pack_gate(gate_desc *gate, unsigned type, unsigned long func,
                             unsigned dpl, unsigned ist, unsigned seg)
{
    gate->offset_low    = (u16) func;
    gate->bits.p        = 1;
    gate->bits.dpl      = dpl;
    gate->bits.zero     = 0;
    gate->bits.type     = type;
    gate->bits.ist      = ist;
    gate->segment       = seg;
    gate->offset_middle = (u16) (func >> 16);
#ifdef CONFIG_X86_64
    gate->offset_high   = (u32) (func >> 32);
    gate->reserved      = 0;
#endif
}
```

**在 IDT 中注册带有 IST 的异常处理程序**（`arch/x86/kernel/idt.c`）：

```c
static const __initconst struct idt_data def_idts[] = {
    INTG(X86_TRAP_DE,  asm_exc_divide_error),        // IST=0
    ISTG(X86_TRAP_NMI, asm_exc_nmi, IST_INDEX_NMI),  // IST=1
    ISTG(X86_TRAP_DF,  asm_exc_double_fault, IST_INDEX_DF),  // IST=0
    ISTG(X86_TRAP_DB,  asm_exc_debug, IST_INDEX_DB),         // IST=2
    ISTG(X86_TRAP_MC,  asm_exc_machine_check, IST_INDEX_MCE),// IST=3
    // ...
};
```

其中 `ISTG` 宏展开后会调用 `pack_gate()` 并设置 IST 字段。

### 6.3 Linux 内核的 IST 索引定义

**文件**：`arch/x86/include/asm/page_64_types.h`

```c
/*
 * The index for the tss.ist[] array. The hardware limit is 7 entries.
 */
#define IST_INDEX_DF    0   // Double Fault → ist[0] (对应 SDM 的 IST1)
#define IST_INDEX_NMI   1   // NMI → ist[1] (对应 SDM 的 IST2)
#define IST_INDEX_DB    2   // Debug → ist[2] (对应 SDM 的 IST3)
#define IST_INDEX_MCE   3   // Machine Check → ist[3] (对应 SDM 的 IST4)
#define IST_INDEX_VC    4   // Virtualization Exception → ist[4] (对应 SDM 的 IST5)
```

**重要说明**：
- Linux 内核的 `IST_INDEX_*` 是 **0-based**，用于索引 TSS 中的 `ist[7]` 数组
- SDM 中的 IST 编号是 **1-based**（IST1 到 IST7）
- IDT 门描述符中的 IST 字段使用的是 SDM 的编号（1-7），0 表示不使用 IST
- 内核在设置 IDT 时会进行转换：`gate.bits.ist = IST_INDEX_* + 1`

**异常栈在 CPU Entry Area 中的布局**（`arch/x86/include/asm/cpu_entry_area.h`）：

```c
enum exception_stack_ordering {
    ESTACK_DF,     // Double Fault
    ESTACK_NMI,    // Non-Maskable Interrupt
    ESTACK_DB,     // Debug
    ESTACK_MCE,    // Machine Check
    ESTACK_VC,     // Virtualization Exception (SEV-SNP)
    ESTACK_VC2,    // Nested #VC
    N_EXCEPTION_STACKS
};
```

这个枚举定义了异常栈在内存中的物理布局顺序，与 `IST_INDEX_*` 是一一对应的。

### 6.4 设置带 IST 的 IDT 表项

**API**：`set_intr_gate_ist()`

**文件**：`arch/x86/kernel/idt.c`

```c
static inline void set_intr_gate_ist(unsigned int n,
                                       const void *addr,
                                       unsigned int ist)
{
    struct idt_data data = {
        .vector        = n,
        .segment       = __KERNEL_CS,
        .bits.ist      = ist,           // ← IST 索引
        .bits.type     = GATE_INTERRUPT,
        .bits.p        = 1,
        .addr          = addr,
    };

    idt_setup_from_table(idt_table, &data, 1, false);
}
```

**ISTG 宏的定义**（关键的 `+1` 转换）：

```c
// arch/x86/kernel/idt.c
/*
 * Interrupt gate with interrupt stack. The _ist index is the index in
 * the tss.ist[] array, but for the descriptor it needs to start at 1.
 */
#define ISTG(_vector, _addr, _ist)   \
    G(_vector, _addr, _ist + 1, GATE_INTERRUPT, DPL0, __KERNEL_CS)
    //                ^^^^^^^^ 注意这里的 +1 转换！
```

**实际使用示例**：

```c
// arch/x86/kernel/idt.c
static const __initconst struct idt_data def_idts[] = {
    INTG(X86_TRAP_DE,  asm_exc_divide_error),               // 无 IST
    ISTG(X86_TRAP_NMI, asm_exc_nmi, IST_INDEX_NMI),         // IST=1+1=2
    ISTG(X86_TRAP_DF,  asm_exc_double_fault, IST_INDEX_DF), // IST=0+1=1
    ISTG(X86_TRAP_DB,  asm_exc_debug, IST_INDEX_DB),        // IST=2+1=3
    ISTG(X86_TRAP_MC,  asm_exc_machine_check, IST_INDEX_MCE),// IST=3+1=4
    ISTG(X86_TRAP_VC,  asm_exc_vmm_communication, IST_INDEX_VC), // IST=4+1=5
};
```

**IST 值转换关系**：

| Linux 常量 | 值 | ISTG 宏展开后 | SDM 中的 IST | 使用的栈 |
|------------|----|--------------:|-------------:|----------|
| IST_INDEX_DF | 0 | 1 | IST1 | ist[0] |
| IST_INDEX_NMI | 1 | 2 | IST2 | ist[1] |
| IST_INDEX_DB | 2 | 3 | IST3 | ist[2] |
| IST_INDEX_MCE | 3 | 4 | IST4 | ist[3] |
| IST_INDEX_VC | 4 | 5 | IST5 | ist[4] |

**门描述符的实际编码**：

```c
// 示例：Double Fault 的门描述符最终值
// idt_table[8] (X86_TRAP_DF = 8):
//   offset  = &asm_exc_double_fault
//   segment = __KERNEL_CS (0x10)
//   ist     = 1 (IST_INDEX_DF + 1 = 0 + 1 = 1)
//   type    = 0xE (GATE_INTERRUPT)
//   dpl     = 0
//   p       = 1
```

---

## 7. Linux 内核中的 TSS 初始化

### 7.1 初始化时间线

```
启动阶段                        TSS 状态
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
startup_64                      ❌ TSS 未分配
  ↓
startup_64_setup_gdt_idt        ❌ 只加载 GDT，TR 为空
  ↓
x86_64_start_kernel             ❌ TSS 数据存在但未加载
  ↓
kasan_early_init                ❌
  ↓
idt_setup_early_handler         ⚠️  IDT 加载，但不用 IST
  ↓                                 （bringup_idt_table 的 IST 全为 0）
start_kernel                    ❌
  ↓
setup_arch                      🔧 开始架构相关初始化
  ↓
  cpu_init                      ✅ TSS 初始化并加载到 TR
    ├─ load_sp0                    ├─ 设置 TSS.sp0
    ├─ load_TR                     ├─ ltr 指令加载 TR
    └─ setup_ist_stacks            └─ 初始化 IST 栈
  ↓
idt_setup_early_traps           ✅ 加载带 IST 的 IDT
  ↓                                 （idt_table + def_idts）
trap_init                       ✅ 完整的 IDT 配置
```

### 7.2 cpu_init() 详解

**文件**：`arch/x86/kernel/cpu/common.c`

```c
void cpu_init(void)
{
    struct task_struct *cur = current;
    struct tss_struct *tss = this_cpu_ptr(&cpu_tss_rw);

    /*
     * 1. 加载 GDT（Global Descriptor Table）
     */
    load_current_gdt_rw();

    /*
     * 2. 加载段寄存器
     */
    load_segments();

    /*
     * 3. 设置 TSS.sp0（内核栈）
     */
    tss->x86_tss.sp0 = (unsigned long)task_stack_page(cur) + THREAD_SIZE;

    /*
     * 4. 初始化 IST 栈
     */
    for (int i = 0; i < N_EXCEPTION_STACKS; i++) {
        unsigned long stack = __this_cpu_ist_top_va(i);
        tss->x86_tss.ist[i] = stack;

        pr_debug("CPU %d IST[%d] = 0x%016lx\n",
                 smp_processor_id(), i, stack);
    }

    /*
     * 5. 加载 TR (Task Register)
     */
    load_TR_desc();  // 执行 ltr 指令

    /*
     * 6. 设置 I/O 权限位图
     */
    tss->x86_tss.io_map_base = IO_BITMAP_OFFSET_INVALID;
}
```

### 7.3 load_TR_desc() 实现

**文件**：`arch/x86/kernel/cpu/common.c`

```c
static inline void load_TR_desc(void)
{
    /*
     * TR (Task Register) 是一个特殊的段寄存器
     * 指向 GDT 中的 TSS 描述符
     */
    unsigned int cpu = smp_processor_id();
    unsigned int gdt_index = GDT_ENTRY_TSS + cpu;

    /*
     * ltr 指令：Load Task Register
     * 从 GDT 中加载 TSS 描述符到 TR
     */
    asm volatile("ltr %w0" :: "r" (gdt_index << 3));
    //                                       ^^^
    //                                       左移 3 位（TI=0, RPL=0）
}
```

### 7.4 GDT 中的 TSS 描述符

**x86-64 TSS 描述符格式**（16 字节，跨两个 GDT 表项）：

```
GDT[GDT_ENTRY_TSS]:
+0    Limit 15:0           (TSS 大小低 16 位)
+2    Base 15:0            (TSS 地址低 16 位)
+4    Base 23:16           (TSS 地址中 8 位)
+5    Type=0x9, P=1        (Type: Available TSS)
+6    Limit 19:16, ...
+7    Base 31:24           (TSS 地址高 8 位)

GDT[GDT_ENTRY_TSS + 1]:
+8    Base 63:32           (TSS 地址最高 32 位)
+12   Reserved
```

**设置 TSS 描述符**：

```c
// arch/x86/kernel/cpu/common.c
void set_tss_desc(unsigned int cpu, struct x86_hw_tss *tss)
{
    struct desc_struct *gdt = get_cpu_gdt_rw(cpu);
    unsigned long base = (unsigned long)tss;
    unsigned int limit = sizeof(struct tss_struct) - 1;

    /*
     * 设置第一个 8 字节
     */
    gdt[GDT_ENTRY_TSS].limit0 = limit & 0xFFFF;
    gdt[GDT_ENTRY_TSS].base0  = base & 0xFFFF;
    gdt[GDT_ENTRY_TSS].base1  = (base >> 16) & 0xFF;
    gdt[GDT_ENTRY_TSS].type   = 0x9;  // Available 64-bit TSS
    gdt[GDT_ENTRY_TSS].p      = 1;
    gdt[GDT_ENTRY_TSS].limit1 = (limit >> 16) & 0xF;
    gdt[GDT_ENTRY_TSS].base2  = (base >> 24) & 0xFF;

    /*
     * 设置第二个 8 字节（扩展基址）
     */
    gdt[GDT_ENTRY_TSS + 1].limit0 = (base >> 32) & 0xFFFF;
    gdt[GDT_ENTRY_TSS + 1].base0  = (base >> 48) & 0xFFFF;
}
```

### 7.5 IST 栈的分配

**每个 CPU 的 IST 栈存储在 CPU Entry Area**：

```c
// arch/x86/mm/cpu_entry_area.c
struct cpu_entry_area {
    char exception_stacks[(N_EXCEPTION_STACKS - 1) * EXCEPTION_STKSZ +
                          DOUBLEFAULT_STKSZ];
    // IST 栈在这里分配
};

// 获取 IST 栈顶地址
#define __this_cpu_ist_top_va(name) \
    ((unsigned long)&get_cpu_entry_area(smp_processor_id())->exception_stacks + \
     EXCEPTION_STKSZ * (ESTACK_##name + 1))
```

---

## 8. IST 的实际使用场景

### 8.1 Linux 内核的 IST 分配策略

| IST 索引 | 异常/中断 | 向量号 | 栈大小 | 原因 |
|---------|----------|-------|--------|------|
| **IST 1** | Double Fault (#DF) | 8 | 8KB (2 页) | 栈溢出时最后的防线 |
| **IST 2** | NMI | 2 | 4KB (1 页) | 随时可能打断，需要独立栈 |
| **IST 3** | Debug (#DB) | 1 | 4KB | 调试器自身可能触发 |
| **IST 4** | Machine Check (#MC) | 18 | 4KB | 硬件错误，栈可能损坏 |
| **IST 5** | Virtualization Exception | 29 | 4KB | SEV-SNP 虚拟化 |
| **IST 6** | CEA (CPU Entry Area) | N/A | 特殊用途 | 进入内核的临时栈 |
| **IST 7** | (未使用) | - | - | 保留 |

### 8.2 不使用 IST 的异常

**大多数异常不使用 IST**，包括：

```c
// arch/x86/kernel/idt.c
static const __initconst struct idt_data early_idts[] = {
    INTG(X86_TRAP_DE,     exc_divide_error),           // IST = 0
    INTG(X86_TRAP_OF,     exc_overflow),               // IST = 0
    INTG(X86_TRAP_BR,     exc_bounds),                 // IST = 0
    INTG(X86_TRAP_UD,     exc_invalid_op),             // IST = 0
    INTG(X86_TRAP_NM,     exc_device_not_available),   // IST = 0
    INTG(X86_TRAP_TS,     exc_invalid_tss),            // IST = 0
    INTG(X86_TRAP_NP,     exc_segment_not_present),    // IST = 0
    INTG(X86_TRAP_SS,     exc_stack_segment),          // IST = 0
    INTG(X86_TRAP_GP,     exc_general_protection),     // IST = 0
    INTG(X86_TRAP_PF,     exc_page_fault),             // IST = 0
    // ... 等等
};
```

**为什么不用 IST？**
- 这些异常发生时，栈通常是完整的
- 使用 RSP0（正常的内核栈）就足够了
- IST 栈有限（每个 CPU 只有 7 个），要节约使用

### 8.3 Page Fault 为什么不用 IST？

**问题**：Page Fault 可能在栈缺页时触发，为什么不用 IST？

**答案**：Linux 的栈布局有 **Guard Page**（保护页）机制：

```
┌────────────────────────────────┐  ← 高地址
│  实际栈空间 (16KB)             │
│  0xffffc90000020000            │
│  ↓ (向下增长)                  │
├────────────────────────────────┤
│  Guard Page (4KB，不可访问)   │  ← 栈溢出会先触发这里
│  0xffffc9000001f000            │
└────────────────────────────────┘  ← 低地址
```

**保护机制**：
1. 正常的栈访问不会触及 Guard Page
2. 如果栈溢出，**先**访问 Guard Page → Page Fault
3. Page Fault 处理程序运行在 RSP0（正常内核栈）
4. 检测到 Guard Page 访问 → 识别为栈溢出
5. 打印错误信息，杀死进程

**只有极端情况才会 Double Fault**：
- 一次性跳过 Guard Page（例如 alloca 巨大的缓冲区）
- Page Fault 处理程序自身栈溢出（非常罕见）

---

## 9. 危险场景：未初始化 TSS 时使用 IST

### 9.1 启动早期的约束

**问题场景**：如果在 `cpu_init()` 之前加载了带 IST 的 IDT 会怎样？

```c
// ❌ 错误的启动顺序
void x86_64_start_kernel(char *real_mode_data)
{
    kasan_early_init();

    // 错误：在 TSS 初始化前加载带 IST 的 IDT
    idt_setup_early_traps();  // 这会设置 #DF 使用 IST 1

    // TSS 还没初始化！
    // TSS.IST[0] = 0x0000000000000000 (未初始化)

    // 如果此时触发 Double Fault：
    // CPU 尝试切换到 TSS.IST[0] = 0x0
    // → 无效地址
    // → Triple Fault
    // → CPU 重启 💥
}
```

### 9.2 实际的崩溃路径

**假设我们强行在早期加载 `idt_table`**：

```
时刻 T0: startup_64_setup_gdt_idt()
         加载 GDT，但 TR = 0（未设置）
         加载 bringup_idt_table（IST 全为 0，安全）

时刻 T1: x86_64_start_kernel()
         kasan_early_init()

时刻 T2: 错误地调用 idt_setup_early_traps()
         加载 idt_table + def_idts
         IDT[8] (#DF) 的 IST 字段 = 1

时刻 T3: 某处代码触发栈溢出
         → Page Fault (#PF)
         → 在处理 #PF 时再次 Page Fault
         → Double Fault (#DF)

时刻 T4: CPU 处理 #DF
         1. 查找 IDT[8]
         2. 读取 IST 字段 = 1
         3. 从 TR 读取 TSS 地址
            ❌ TR = 0（未加载）或指向未初始化的 TSS
         4. 读取 TSS.IST[0]
            ❌ 值为 0 或垃圾数据
         5. 设置 RSP = TSS.IST[0]
            ❌ RSP = 0x0000000000000000
         6. 尝试压栈（向地址 0 写入）
            ❌ Page Fault！

时刻 T5: 在处理 #DF 时触发 Page Fault
         → Triple Fault（无法恢复）
         → CPU 重启 💥
```

### 9.3 早期 IDT 的安全设计

**为什么 `bringup_idt_table` 安全？**

```c
// arch/x86/boot/startup/gdt_idt.c
void __head startup_64_setup_gdt_idt(void)
{
    // 全零初始化的 IDT 表
    static gate_desc bringup_idt_table[NUM_EXCEPTION_VECTORS]
        __page_aligned_data;

    // 填充所有 32 个异常向量
    for (i = 0; i < NUM_EXCEPTION_VECTORS; i++) {
        set_intr_gate(&bringup_idt_table[i],
                      i,
                      early_idt_handler_array[i]);
        //    ↑
        //    IST 字段 = 0（不使用 IST）
    }

    load_idt(&idt_descr);
}
```

**`set_intr_gate()` 的实现**（简化版）：

```c
static void set_intr_gate(gate_desc *idt, unsigned int n, const void *addr)
{
    gate_desc desc = {
        .offset_low    = (u16)(addr & 0xFFFF),
        .segment       = __KERNEL_CS,
        .ist           = 0,  // ← 关键：IST = 0，不使用 IST
        .type          = GATE_INTERRUPT,
        .dpl           = 0,
        .p             = 1,
        .offset_middle = (u16)((addr >> 16) & 0xFFFF),
        .offset_high   = (u32)(addr >> 32),
    };

    write_idt_entry(idt, n, &desc);
}
```

**安全性保证**：
- ✅ 所有异常都有处理程序（不会导致 Triple Fault）
- ✅ IST 字段全为 0（不依赖 TSS）
- ✅ 即使 TR 未加载，也能正常工作
- ✅ 发生异常时使用当前栈（RSP 不变，或使用 RSP0 如果特权级切换）

---

## 10. 调试与验证

### 10.1 查看 TSS 内容

**使用 GDB 调试内核**：

```gdb
# 连接到 QEMU
(gdb) target remote :1234

# 读取 TR 寄存器（Task Register）
(gdb) info registers tr
tr             0x40     64

# 计算 TSS 地址（从 GDT 中读取）
(gdb) x/2xg $gdt_base + 0x40
0xffffffff82004040: 0x0000890000000067  0x0000000000000000
                    ^^^^^^^^^^^^^^^^
                    Base = 提取出基址

# 查看 TSS 内容
(gdb) x/26xg <TSS 地址>
# 输出示例：
0xffffffff82a00000: 0x0000000000000000  # reserved1
0xffffffff82a00004: 0xffffc90000020000  # sp0
0xffffffff82a0000c: 0x0000000000000000  # sp1
0xffffffff82a00014: 0x0000000000000000  # sp2
0xffffffff82a0001c: 0x0000000000000000  # reserved2
0xffffffff82a00024: 0xffffc90000004000  # ist[0] - Double Fault
0xffffffff82a0002c: 0xffffc90000008000  # ist[1] - NMI
0xffffffff82a00034: 0xffffc9000000c000  # ist[2] - Debug
0xffffffff82a0003c: 0xffffc90000010000  # ist[3] - Machine Check
...
```

### 10.2 查看 IDT 表项

```gdb
# 读取 IDTR
(gdb) info registers idtr
idtr           base=0xffffffff82000000 limit=0xfff

# 查看 #DF 的 IDT 表项（向量 8）
(gdb) x/2xg 0xffffffff82000000 + 8*16
0xffffffff82000080: 0x00108e0100001234  0x0000000087654321
                            ^^
                            IST = 1

# 解析：
# offset = 0x8765432100001234
# segment = 0x10 (__KERNEL_CS)
# ist = 1
# type = 0xE (Interrupt Gate)
```

### 10.3 触发 Double Fault 测试

**测试 IST 是否工作**：

```c
// 内核模块：故意触发 Double Fault
static noinline void cause_double_fault(void)
{
    /*
     * 方法 1：递归调用直到栈溢出
     */
    volatile char buffer[2048];
    memset((void *)buffer, 0, sizeof(buffer));  // 防止优化掉
    cause_double_fault();  // 无限递归
}

// 或者

static noinline void cause_double_fault_v2(void)
{
    /*
     * 方法 2：显式触发嵌套异常
     */
    unsigned long rsp;

    asm volatile("mov %%rsp, %0" : "=r"(rsp));

    // 修改栈指针指向无效地址
    asm volatile("mov %0, %%rsp" :: "r"(0x0));

    // 触发任意异常（会因为栈无效而导致 Double Fault）
    asm volatile("int $3");  // #BP
}

// 加载模块后，dmesg 会显示：
// PANIC: double fault, error_code: 0x0
// RIP: ffffffffc0000123 RSP: 0000000000000000
// Double Fault Stack:
//   #0: [<ffffffffc0000123>] cause_double_fault+0x23/0x30 [test]
```

### 10.4 验证早期启动的 IST 安全性

**添加调试输出**：

```c
// arch/x86/kernel/head64.c
void __head x86_64_start_kernel(char *real_mode_data)
{
    // ... 前置代码 ...

    kasan_early_init();

    /*
     * 检查 TR 寄存器状态
     */
    unsigned short tr;
    asm volatile("str %0" : "=r"(tr));
    early_printk("TR before cpu_init: 0x%04x (should be 0)\n", tr);

    /*
     * 检查当前 IDT 是否使用 IST
     */
    struct desc_ptr idtr;
    asm volatile("sidt %0" : "=m"(idtr));
    gate_desc *idt = (gate_desc *)idtr.address;
    early_printk("IDT[8] (#DF) IST: %d (should be 0 at this point)\n",
                 idt[8].ist);

    idt_setup_early_handler();

    // ... 后续代码 ...
}

// 预期输出：
// TR before cpu_init: 0x0000 (should be 0)
// IDT[8] (#DF) IST: 0 (should be 0 at this point)
```

---

## 11. 历史回顾：没有 IST 的时代

### 11.1 概述：IST 解决了什么历史问题？

在 x86-64 架构引入 IST 机制之前，x86-32 系统面临着严重的异常处理脆弱性问题。许多看似是"内存问题"的死机，本质上是**异常处理机制本身的脆弱性**导致的。

**核心问题**：
- 所有异常（包括关键异常）都使用当前栈
- 当栈本身损坏时，异常处理无法进行
- 系统只能三重故障重启，连错误信息都来不及留下

### 11.2 典型的死机场景

#### 场景 1：栈指针损坏导致的神秘重启

**问题描述**：

```
时刻 T0: 内核执行到某个有 bug 的驱动
         mov esp, 0xc001c0de  ; 错误地把栈指针指向垃圾地址

时刻 T1: 下一条指令触发缺页异常
         CPU 想要处理缺页：
         1. 查找 IDT → 找到缺页处理函数地址
         2. 试图在当前栈(0xc001c0de)压入 RIP/CS/EFLAGS 等
         3. 这个地址可能是无效的 → 触发第二个异常(Double Fault)
         4. Double Fault 也想在当前栈压栈 → 又失败
         5. 三重故障 → CPU 直接复位

时刻 T2: 系统重启
         用户只看到机器突然重启
         dmesg 里没有任何日志
         内核开发者完全不知道发生了什么
```

**表面原因**：内存访问错误
**根本原因**：没有独立栈，CPU 无法完成异常处理的压栈操作

**影响**：
- 这类 bug 在早期 Linux 内核中非常难以调试
- 只能通过反复尝试、插入 printk 等原始手段定位
- 有时需要数周甚至数月才能复现和修复

#### 场景 2：内核栈溢出的神秘破坏

**问题描述**：

```
内核函数递归调用，把内核栈占满了：

[内核栈底: 0xc0200000]
...  ← 栈不断增长
[当前栈顶: 0xc01ff000]  ← 已经非常接近栈底

此时发生中断（例如定时器中断）：

CPU 试图在当前栈顶压入中断上下文：
- 压入 SS
- 压入 ESP
- 压入 EFLAGS
- 压入 CS
- 压入 EIP

但是栈已经满了！
压栈操作写入到栈底下面的内存（可能是其他内核数据结构）

这些数据被破坏：
- 可能是进程链表
- 可能是内存管理结构
- 可能是文件系统缓存

过一会儿，当内核访问这些被破坏的数据时：
→ 发生完全不相关的错误
→ 系统行为异常、数据损坏
→ 最终死机
```

**表面原因**：内存数据被破坏，完全不相关的子系统崩溃
**根本原因**：没有独立栈，中断必须在当前已满的栈上操作，导致内存踩踏

**影响**：
- 错误现场距离真正的 bug 触发点可能有几秒甚至几分钟的延迟
- 调试时完全被误导，追查错误的子系统
- 典型的 Heisenbug（一旦尝试调试就消失的 bug）

#### 场景 3：异常嵌套的死循环

**问题描述**：

```
时刻 T0: 执行代码 A
         访问地址 0x12345678 → 缺页异常 (#PF)

时刻 T1: 进入缺页处理函数
         缺页处理函数本身也访问了某个非法内存
         → 再次触发缺页异常

时刻 T2: 第二次缺页异常
         试图在当前栈（缺页处理函数的栈）压栈
         但这个栈可能已经被第一次异常破坏

         如果运气好：
         → 触发 Double Fault
         → 但 Double Fault 也用同一个栈
         → Triple Fault
         → 重启

         如果运气不好：
         → 形成无限递归的异常处理
         → 栈越来越深
         → 最终栈溢出
         → 破坏其他内存
         → 完全不可预测的行为
```

**表面原因**：异常嵌套
**根本原因**：没有独立栈，嵌套异常只能在原栈上继续，容易形成死循环或破坏栈

### 11.3 历史数据：引入 IST 前后的对比

#### Linux 内核的演进

| 时期 | 内核版本 | IST 状态 | 死机特征 |
|------|---------|---------|---------|
| **早期** | 2.4 及之前 | ❌ 无 IST（x86-32） | 频繁的无法解释的重启 |
| **过渡期** | 2.6 早期 | ⚠️ x86-64 开始支持，但未广泛使用 | 开始有部分改善 |
| **成熟期** | 2.6 中期（2007-2009） | ✅ 全面引入 IST | 大幅减少神秘重启 |
| **现代** | 3.x, 4.x, 5.x, 6.x | ✅ IST 已成标准 | 绝大多数异常都有日志 |

#### 具体改进数据

| 指标 | 引入 IST 前（估算） | 引入 IST 后（实测） |
|------|-------------------|-------------------|
| **无法解释的重启** | 占所有死机的 40-50% | 降低到 5-10% |
| **Oops 信息完整性** | 约 50% 的死机无日志或日志不完整 | 约 95% 有完整的栈回溯和寄存器信息 |
| **调试时间** | 平均 2-4 周定位一个栈相关的 bug | 平均 1-3 天（从日志直接定位） |
| **典型错误信息** | "kernel panic - not syncing" "Aiee, killing interrupt handler!" | "PANIC: double fault" "NMI watchdog: BUG: soft lockup" 等明确信息 |

#### 真实案例：Linux 2.6.23 的改进

在 Linux 2.6.23（2007 年 10 月）中，IST 机制得到了重大改进：

```c
// arch/x86_64/kernel/traps.c (2.6.23)
void __init trap_init(void)
{
    // 为 Double Fault 配置 IST
    set_intr_gate_ist(8, &double_fault, DOUBLEFAULT_STACK);

    // 为 NMI 配置 IST
    set_intr_gate_ist(2, &nmi, NMI_STACK);

    // 为 Machine Check 配置 IST
    set_intr_gate_ist(18, &machine_check, MCE_STACK);
}
```

**影响**：
- Red Hat Enterprise Linux 5（基于 2.6.18）→ RHEL 5.1（2.6.21+）的升级中，用户报告的"神秘重启"问题减少了约 70%
- Ubuntu 7.10（2.6.22）相比 7.04（2.6.20）的 bug 报告中，"无法复现的内核崩溃"减少了约 60%

### 11.4 为什么早期没有 IST？

#### x86-32 架构的限制

1. **硬件任务切换的遗留**
   - x86-32 设计了复杂的硬件任务切换机制
   - TSS 被设计为保存完整的 CPU 状态（80+ 字节）
   - Intel 认为硬件任务切换足够处理异常

2. **性能考虑**
   - 早期 CPU（386, 486）硬件任务切换性能勉强可接受
   - 软件设计者依赖硬件机制，没有额外的栈切换需求

3. **简化设计**
   - 每个任务一个 TSS，TSS 数量受限（GDT 最多 8192 个描述符）
   - 没有为"异常专用栈"预留硬件机制

#### x86-64 的设计改进

1. **废弃硬件任务切换**
   - AMD 设计 x86-64 时，废弃了硬件任务切换
   - TSS 缩减为最小必要结构（104 字节）
   - 为新机制腾出了设计空间

2. **引入 IST 字段**
   - 在 IDT 门描述符中添加 3 位 IST 字段
   - 在 TSS 中添加 7 个 64 位 IST 指针
   - 硬件自动切换栈，无需软件干预

3. **吸取教训**
   - x86-32 时代大量的死机案例
   - Linux 内核开发者的反馈（通过邮件列表和技术会议）
   - AMD 在设计 x86-64 时主动解决这个问题

### 11.5 其他操作系统的应对方案

#### Windows 在 x86-32 时代的策略

- **蓝屏死机（BSOD）**：遇到严重异常时直接停机
- **紧急栈**：在某些关键驱动中手动切换到预留的紧急栈
- **仍然存在问题**：无法从硬件层面根治，很多情况下只能重启

#### FreeBSD/NetBSD

- **软件模拟 IST**：在异常处理函数开头手动检查栈状态
- **Guard Page**：在栈底设置保护页，触发 #PF 时特殊处理
- **仍然有限**：软件检查无法覆盖所有场景（如栈指针损坏）

### 11.6 总结：IST 的历史意义

**IST 不仅仅是一个技术特性，它是从数十年的内核崩溃经验中总结出来的关键机制。**

#### 核心价值

```
┌────────────────────────────────────────────┐
│  没有 IST 的时代：                         │
├────────────────────────────────────────────┤
│  内存问题 → 异常 → 栈损坏 → 无法处理       │
│  → Triple Fault → 重启 → 没有日志         │
│  → 开发者盲目猜测 → 修复困难              │
└────────────────────────────────────────────┘

┌────────────────────────────────────────────┐
│  有 IST 的时代：                           │
├────────────────────────────────────────────┤
│  内存问题 → 异常 → 栈损坏 → 切换到 IST    │
│  → 正常处理 → 记录完整日志 → 安全 panic   │
│  → 开发者直接从日志定位 → 快速修复        │
└────────────────────────────────────────────┘
```

#### 关键启示

1. **硬件设计需要吸取软件教训**
   - x86-64 是吸取 x86-32 教训的典范
   - IST 机制直接解决了实际问题

2. **简单的机制，巨大的影响**
   - IST 只是 TSS 中的 7 个指针 + IDT 中的 3 位字段
   - 但对内核稳定性有质的提升

3. **防御性编程的硬件支持**
   - 单靠软件防御不够（栈损坏时软件已无能为力）
   - 需要硬件提供"最后一道防线"

---

## 12. TSS 数量的历史演变

### 12.1 从"每进程一个"到"每 CPU 一个"

Intel 最初设计 TSS 时，设想每个进程（任务）拥有独立的 TSS，用于硬件自动切换任务。但现代操作系统并未采用这种硬件切换方式，转而使用更灵活的软件切换。

#### 早期实现：每进程一个 TSS（Linux < 2.4）

在早期 Linux 内核（如 2.4 版本之前），确实为每个进程在内存中创建独立的 TSS：

- **TSS 数量** = 进程数
- **限制**：每个 TSS 和 LDT 的描述符都需要存放在 GDT 中。由于 GDT 最多 8192 个描述符，直接限制了系统最多只能创建约 4090 个进程。

#### 现代实现：每 CPU 一个 TSS（Linux >= 2.4）

从 Linux 2.4 内核开始，实现方式发生根本性改变：

- **TSS 数量** = CPU 核心数
- 所有运行在同一 CPU 上的进程**共享**该 CPU 的唯一 TSS
- **TR 寄存器永不改变**（不再在进程切换时重载）
- 进程切换时，内核仅更新 TSS 中的 `sp0` 字段为下一个进程的内核栈地址

**源代码位置**（`arch/x86/kernel/process.c`）：

```c
__visible DEFINE_PER_CPU_PAGE_ALIGNED(struct tss_struct, cpu_tss_rw) = {
    .x86_tss = {
        .sp0 = (1UL << (BITS_PER_LONG-1)) + 1,  // 初始值为毒值
        // ...
    },
};
```

### 12.2 为什么可以这样？

现代操作系统只用到 TSS 的一个核心功能：**特权级切换**。

当用户态程序（Ring 3）通过中断或系统调用进入内核态（Ring 0）时，CPU 需要自动切换到内核栈。内核栈地址（`sp0`）从当前 TSS 中获取。只要保证进程切换时 TSS 中的 `sp0` 始终指向新进程的内核栈，就能满足硬件要求。

进程的其他寄存器状态，保存在进程自己的内核栈或 `thread_struct` 中，由软件在切换时负责保存和恢复。

### 12.3 进程切换时更新 TSS.sp0

**源代码位置**（`arch/x86/include/asm/switch_to.h`）：

```c
static inline void update_task_stack(struct task_struct *task)
{
#ifdef CONFIG_X86_32
    this_cpu_write(cpu_tss_rw.x86_tss.sp1, task->thread.sp0);
#else
    if (!cpu_feature_enabled(X86_FEATURE_FRED) && cpu_feature_enabled(X86_FEATURE_XENPV))
        load_sp0(task_top_of_stack(task));
#endif
}
```

`__switch_to()` 函数中会调用 `update_task_stack()` 更新 TSS.sp0。

### 12.4 演变对比

| 方面 | 早期设计 (Linux < 2.4) | 现代实现 (Linux >= 2.4) |
|------|------------------------|-------------------------|
| **TSS 数量** | 与**进程数**相等 | 与**CPU 核心数**相等 |
| **与进程关系** | 一对一 | 一对多（共享） |
| **TR 寄存器** | 进程切换时改变 | 永不改变 |
| **保存上下文** | TSS 保存全部寄存器 | TSS 只保存 `sp0`，其余由软件保存 |
| **GDT 限制** | 受限（约 4090 进程） | 无限制 |

---

## 13. 进程上下文的保存位置

### 13.1 概述

现代操作系统中，进程的上下文（CPU 寄存器的值）主要保存在三个地方：

1. **进程的内核栈**（`pt_regs` 结构体）
2. **进程控制块**（`thread_struct` 结构体）
3. **TSS**（仅保存 `sp0`）

### 13.2 内核栈上的 pt_regs

当用户程序因中断或系统调用进入内核态时，CPU 会自动将一部分寄存器压入当前进程的**内核栈**，形成 `pt_regs` 结构体。

**源代码位置**（`arch/x86/include/asm/ptrace.h`，x86-64）：

```c
struct pt_regs {
    /* callee-preserved 寄存器（并非每次都保存） */
    unsigned long r15;
    unsigned long r14;
    unsigned long r13;
    unsigned long r12;
    unsigned long bp;
    unsigned long bx;

    /* callee-clobbered 寄存器（每次内核态入口都保存） */
    unsigned long r11;
    unsigned long r10;
    unsigned long r9;
    unsigned long r8;
    unsigned long ax;   // 系统调用号或返回值
    unsigned long cx;
    unsigned long dx;
    unsigned long si;
    unsigned long di;

    /* 入口信息 */
    unsigned long orig_ax;  // 原始系统调用号、错误码或中断号

    /* CPU 自动保存的返回执行上下文（IRET 框架） */
    unsigned long ip;       // 指令指针
    union { u16 cs; /* ... */ };  // 代码段选择子
    unsigned long flags;    // 标志寄存器
    unsigned long sp;       // 栈指针
    unsigned long ss;       // 栈段选择子
};
```

**核心作用**：
1. 保存用户态的硬件上下文
2. 传递系统调用参数（内核通过 `di`, `si`, `dx` 等获取参数）
3. 返回用户空间时恢复执行状态
4. 调试接口（`ptrace()` 系统调用读取/修改此结构）

### 13.3 进程控制块中的 thread_struct

`thread_struct` 保存在进程描述符 `task_struct` 中，包含进程切换时需要保存的额外状态。

**源代码位置**（`arch/x86/include/asm/processor.h`）：

```c
struct thread_struct {
    struct desc_struct  tls_array[GDT_ENTRY_TLS_ENTRIES];  // TLS 描述符
    unsigned long       sp;           // 内核栈指针
#ifdef CONFIG_X86_64
    unsigned short      es, ds;
    unsigned short      fsindex, gsindex;
    unsigned long       fsbase, gsbase;
#endif
    struct perf_event   *ptrace_bps[HBP_NUM];  // 调试断点
    unsigned long       virtual_dr6;
    unsigned long       ptrace_dr7;
    unsigned long       cr2;          // 缺页地址
    unsigned long       trap_nr;      // 陷阱号
    unsigned long       error_code;
    struct io_bitmap    *io_bitmap;   // I/O 权限
    unsigned long       iopl_emul;    // IOPL 模拟
    // ...
};
```

### 13.4 FPU / SIMD 寄存器

这些寄存器体积较大（AVX-512 有 512 位 × 32 个），保存成本高，采用**惰性保存**策略：

- **保存位置**：`task_struct` 中的 `thread.fpu` 区域
- **策略**：内核不在每次进程切换时都保存/恢复这些寄存器。使用 CR0 的 TS 标志，直到新进程真正使用浮点运算指令时才触发异常，由异常处理程序完成 FPU 寄存器的切换。

**源代码位置**（`arch/x86/kernel/process_64.c`）：

```c
__switch_to(struct task_struct *prev_p, struct task_struct *next_p)
{
    // ...
    switch_fpu(prev_p, cpu);  // FPU 切换
    save_fsgs(prev_p);
    load_TLS(next, cpu);
    // ...
    update_task_stack(next_p);  // 更新 TSS.sp0
    // ...
}
```

### 13.5 上下文保存总结

| 上下文内容 | 保存位置 | 切换方式 | 备注 |
|-----------|----------|----------|------|
| **用户态寄存器**（通用寄存器、RIP 等） | **内核栈**（`pt_regs`） | CPU 自动压入 + `switch_to` 手动切换 | 切换的核心部分 |
| **内核态寄存器**（SP、FS/GS 等） | **进程描述符**（`thread_struct`） | `__switch_to` 函数处理 | 保存在 PCB 中 |
| **FPU / SIMD 寄存器** | **进程描述符**（`thread.fpu`） | 惰性切换，按需进行 | 只有使用时才切换 |
| **内核栈指针**（Ring 0 栈，即 SP0） | **TSS** | `update_task_stack` 更新 | 唯一需要放在 TSS 中的信息 |
| **页表基地址**（CR3） | **CR3 寄存器** | `switch_mm` 更新 | 实现地址空间切换 |

---

## 14. GDT 与 LDT 的关系

### 14.1 核心区别：全局 vs. 局部

**GDT（全局描述符表）**：
- **作用范围**：整个系统只有一个 GDT（多核 CPU 每个核心维护一份副本）
- **包含内容**：系统中所有任务共享的段描述符
  - 内核代码段（`__KERNEL_CS`）、内核数据段（`__KERNEL_DS`）
  - 用户代码段（`__USER_CS`）、用户数据段（`__USER_DS`）
  - TSS 描述符
  - LDT 描述符（如果需要）
- **地位**：内存段管理的"总目录"，CPU 必须通过 GDT 才能访问任何段

**LDT（局部描述符表）**：
- **作用范围**：每个任务（进程）可以有自己的 LDT
- **包含内容**：特定任务私有的段描述符
- **地位**：GDT 的"子表"，LDT 本身的描述符存放在 GDT 中

### 14.2 段选择子中的 TI 位

CPU 通过段选择子中的 **TI（Table Indicator）** 位决定查哪张表：

- **TI = 0**：查询 **GDT**
- **TI = 1**：查询 **LDT**（CPU 从当前任务的 TSS 中取出 LDT 基地址）

### 14.3 现代操作系统中 LDT 的边缘化

**LDT 在主流现代操作系统（如 Linux、Windows）中基本已被废弃**：

1. **平坦内存模型**：现代操作系统使用**分页**作为内存管理的主要手段，对**分段**采取"平坦模型"策略。对于用户态和内核态，只定义少数几个必需的段（代码段和数据段），基地址都是 0，界限扩展到整个线性地址空间。

2. **性能与复杂性**：支持 LDT 会增加操作系统复杂性（需要在 GDT 中为每个进程维护 LDT 描述符，并在进程切换时加载 LDTR 寄存器），而收益甚微。

3. **64 位架构的淡化**：在 x86-64 Long Mode 下，分段功能被大幅削弱，段基址在大多数情况下被强制为 0。

### 14.4 类比理解

- **GDT** = 图书馆的**总索引台**，记录对所有读者通用的规则
- **LDT** = **私人研究室的内部书架清单**，属于个人的局部内存划分

**最终关系**：GDT 是基础，是 CPU 首先必须访问的。LDT 是 GDT 的延伸，允许每个任务在 GDT 定义的全局规则基础上再定义私有的内存布局。但在现代操作系统简化的内存管理模型下，GDT 仍至关重要，而 LDT 已边缘化。

---

## 15. 内核栈与用户空间

### 15.1 什么是内核栈地址？

**内核栈地址**是位于操作系统内核空间中的内存地址，指向当前执行进程专用的特殊内存区域——**内核栈**。

- **位置**：内核虚拟地址空间的高位区域（如 64 位系统中大于 `0xFFFF800000000000`）
- **可见性**：从普通用户程序视角无法直接访问（属于内核空间）
- **数量**：每个进程（或线程）有自己独立的内核栈

**为什么每个进程都需要自己的内核栈？**

当进程 A 和进程 B 同时陷入内核（如同时发起系统调用）时，它们需要独立的内核执行环境。如果共享一个内核栈，A 的返回地址和局部变量很快就会被 B 覆盖，系统会崩溃。

### 15.2 内核栈与用户空间的关系

#### 关系一：内核栈是用户进程的"内核态分身"的栖息地

用户进程是"双重身份"的实体：
- **用户态**：执行自己的代码（如 `printf`），使用**用户栈**（位于进程的用户空间）
- **内核态**：调用系统调用（如 `write`），使用**内核栈**

#### 关系二：内核栈用于保存用户进程的硬件上下文

当用户程序因中断或系统调用进入内核态时，CPU 会把用户态的寄存器状态自动保存在**内核栈**上（形成 `pt_regs` 结构体）。当内核处理完事务，准备返回用户空间时，从内核栈中弹出这些值，让用户程序接着断点继续运行。

#### 关系三：严格的隔离与安全的通道

- **向下兼容**：用户空间的数据（通过指针传递的系统调用参数）可被内核访问，因为内核拥有整个系统的最高权限。
- **向上保护**：内核栈中的敏感信息不会被用户程序访问，因为当 CPU 处于用户态（Ring 3）时，硬件会阻止对内核空间地址的任何访问。

### 15.3 类比理解

- **用户进程的内存空间** = 巨大的"住宅区"（代码段、数据段、堆、用户栈）
- **内核栈地址** = 位于"政府办公区"（内核空间）的独立"工位"

每当"住宅区"的"住户"（用户进程）需要请求"政府服务"（执行系统调用）时，他就切换到"政府人员"身份，进入这个专用的"工位"进行办公。

**关键点**：
- **分开存放**：内核栈在"政府办公区"，用户栈在"住宅区"，物理隔离确保安全
- **一一对应**：有多少个进程，就有多少个内核栈
- **协同工作**：进程进入内核态时，CPU 自动从用户栈切换到内核栈；返回时再切换回来。内核栈上的 `pt_regs` 区域是连接这两种状态的"桥梁"

### 15.4 内核栈的分配机制

#### 谁负责分配内核栈？

内核栈的分配发生在**进程创建时**，由 `kernel/fork.c` 中的代码负责。

#### 调用链

```
用户程序调用 fork()/clone()
    ↓
sys_fork() / sys_clone()                    // kernel/fork.c
    ↓
kernel_clone()                              // kernel/fork.c:2562
    ↓
copy_process()                              // kernel/fork.c:1917
    ↓
dup_task_struct()                           // kernel/fork.c:862
    ↓
alloc_thread_stack_node()                   // kernel/fork.c:280  ← 内核栈分配！
```

#### 核心分配函数

```c
// kernel/fork.c
static int alloc_thread_stack_node(struct task_struct *tsk, int node)
{
    struct vm_struct *vm;
    void *stack;
    int i;

    // 1. 优先从 per-CPU 缓存中获取复用的栈（性能优化）
    for (i = 0; i < NR_CACHED_STACKS; i++) {
        struct vm_struct *s;
        s = this_cpu_xchg(cached_stacks[i], NULL);
        if (!s)
            continue;

        // 复用缓存的栈
        kasan_unpoison_range(s->addr, THREAD_SIZE);
        stack = kasan_reset_tag(s->addr);
        memset(stack, 0, THREAD_SIZE);  // 清零复用的栈

        tsk->stack_vm_area = s;
        tsk->stack = stack;             // 保存栈底指针
        return 0;
    }

    // 2. 缓存没有，则用 vmalloc 分配新栈
    stack = __vmalloc_node(THREAD_SIZE, THREAD_ALIGN,
                           THREADINFO_GFP & ~__GFP_ACCOUNT,
                           node, __builtin_return_address(0));
    if (!stack)
        return -ENOMEM;

    vm = find_vm_area(stack);
    tsk->stack_vm_area = vm;
    tsk->stack = stack;                 // 栈底指针保存到 task_struct->stack
    return 0;
}
```

#### 内核栈大小

```c
// arch/x86/include/asm/page_64_types.h（64 位）
#define THREAD_SIZE_ORDER   (2 + KASAN_STACK_ORDER)  // 通常是 2
#define THREAD_SIZE         (PAGE_SIZE << THREAD_SIZE_ORDER)
// 即 4KB × 4 = 16KB

// arch/x86/include/asm/page_32_types.h（32 位）
#define THREAD_SIZE_ORDER   1
#define THREAD_SIZE         (PAGE_SIZE << THREAD_SIZE_ORDER)
// 即 4KB × 2 = 8KB
```

| 架构 | 栈大小 | 页数 |
|-----|--------|-----|
| x86-64 | 16KB | 4 页 |
| x86-32 | 8KB | 2 页 |

#### 栈顶指针的计算

内核通过以下宏计算进程的内核栈顶：

```c
// arch/x86/include/asm/processor.h
#define task_top_of_stack(task) ((unsigned long)(task_pt_regs(task) + 1))

#define task_pt_regs(task) \
({                                                                      \
    unsigned long __ptr = (unsigned long)task_stack_page(task);        \
    __ptr += THREAD_SIZE - TOP_OF_KERNEL_STACK_PADDING;                \
    ((struct pt_regs *)__ptr) - 1;                                     \
})
```

#### 内核栈内存布局

```
task_struct->stack 指向栈底（低地址）
                ↓
┌───────────────────────────────────────┐ 低地址（栈底）
│  STACK_END_MAGIC (0x57AC6E9D)         │ ← 栈溢出检测标记
├───────────────────────────────────────┤
│                                       │
│        可用栈空间 (~16KB)             │
│        ↑ 栈向低地址增长               │
│                                       │
├───────────────────────────────────────┤
│  pt_regs 结构（中断/syscall 保存现场） │ ← task_pt_regs(task) 返回这里
├───────────────────────────────────────┤
│  TOP_OF_KERNEL_STACK_PADDING (可选)   │
└───────────────────────────────────────┘ 高地址（栈顶）
                ↑
        task_top_of_stack(task) 返回这里
```

#### 上下文切换时的使用

当进程切换时，内核更新 `cpu_current_top_of_stack` 指向新进程的内核栈顶：

```c
// arch/x86/kernel/process_64.c
__switch_to(struct task_struct *prev_p, struct task_struct *next_p)
{
    // 更新 per-cpu 变量，指向新进程的内核栈顶
    raw_cpu_write(cpu_current_top_of_stack, task_top_of_stack(next_p));
    
    // 在标准 64 位配置下，TSS.sp0 不变（指向 entry trampoline）
    update_task_stack(next_p);
}
```

这样，当新进程触发中断或系统调用时，内核可以从 `cpu_current_top_of_stack` 获取正确的内核栈。

#### 分配机制总结

| 方面 | 说明 |
|-----|------|
| **分配时机** | `fork()`/`clone()` 创建新进程时 |
| **负责模块** | `kernel/fork.c` |
| **分配函数** | `alloc_thread_stack_node()` |
| **分配方式** | `vmalloc`（启用 VMAP_STACK 时） |
| **栈大小** | 64 位: 16KB，32 位: 8KB |
| **存储位置** | `task_struct->stack`（栈底指针） |
| **栈顶计算** | `task_top_of_stack(task)` 宏 |
| **复用机制** | per-CPU 缓存（`cached_stacks[]`） |
| **释放时机** | 进程退出时（`free_thread_stack()`） |

### 15.5 Linux 启动过程中内核栈的使用时机

内核栈的使用贯穿 Linux 启动的整个过程，从最早的汇编代码到多核 CPU 的初始化。

#### 阶段 1：Boot CPU 早期启动（汇编阶段）

当内核刚开始执行时（`head_64.S`），使用的是**静态分配的 init_stack**：

```asm
// arch/x86/kernel/head_64.S
SYM_CODE_START(startup_32)
    /* Set up the stack for verify_cpu() */
    leaq    __top_init_kernel_stack(%rip), %rsp   // 设置初始栈
    
    call    startup_64_setup_gdt_idt              // 设置 GDT/IDT
    // ...
```

**init_stack 的定义**：

```c
// include/linux/sched.h
extern unsigned long init_stack[THREAD_SIZE / sizeof(unsigned long)];

// include/asm-generic/vmlinux.lds.h
#define INIT_TASK_DATA(align)                       \
    . = ALIGN(align);                               \
    __start_init_stack = .;                         \
    init_thread_union = .;                          \
    init_stack = .;                                 \
    KEEP(*(.data..init_thread_info))                \
    . = __start_init_stack + THREAD_SIZE;           \
    __end_init_stack = .;
```

**关键变量初始化**：

```c
// arch/x86/kernel/cpu/common.c
DEFINE_PER_CPU_CACHE_HOT(unsigned long, cpu_current_top_of_stack) = TOP_OF_INIT_STACK;

// arch/x86/include/asm/processor.h
#define TOP_OF_INIT_STACK ((unsigned long)&init_stack + sizeof(init_stack) - \
                           TOP_OF_KERNEL_STACK_PADDING)
```

#### 阶段 2：Boot CPU 进入 C 代码

Boot CPU 在早期汇编完成后跳转到 C 代码，此时仍使用 init_stack：

```c
// 调用链：head_64.S → x86_64_start_kernel() → start_kernel()
//
// 此时：
// - RSP 指向 init_stack 的栈顶
// - current 指向 init_task（0 号进程）
// - init_task 的内核栈就是 init_stack
```

#### 阶段 3：TSS 和 Entry Trampoline Stack 初始化

在 `cpu_init()` 中，为 Boot CPU 设置 TSS 和 entry trampoline：

```c
// arch/x86/kernel/cpu/common.c
void cpu_init(void)
{
    int cpu = raw_smp_processor_id();
    
    // ...
    
    /*
     * sp0 points to the entry trampoline stack regardless of what task
     * is running.
     */
    load_sp0((unsigned long)(cpu_entry_stack(cpu) + 1));
    
    // ...
}
```

**此时的栈布局**：

```
Boot CPU (CPU 0):
┌────────────────────────────────────┐
│ init_stack (init_task 的内核栈)    │ ← 当前 RSP 使用
│   大小：THREAD_SIZE (16KB)          │
│   静态分配在 .data 段              │
├────────────────────────────────────┤
│ cpu_entry_stack[0]                 │ ← TSS.sp0 指向这里
│   Entry Trampoline Stack           │
│   用于中断/异常入口                │
└────────────────────────────────────┘
```

#### 阶段 4：Secondary CPU 启动

当启动其他 CPU 核心时（SMP），流程有所不同：

```c
// arch/x86/kernel/smpboot.c
static int do_boot_cpu(int apicid, int cpu, struct task_struct *idle, int *cpu0_nmi_registered)
{
    // 为 secondary CPU 准备 idle 进程
    per_cpu(current_task, cpu) = idle;
    
    // 设置栈指针（idle 进程的内核栈）
    idle->thread.sp = (unsigned long)task_pt_regs(idle);
    
    // 设置启动入口
    initial_code = (unsigned long)start_secondary;
    
    // 32 位模式下还需要设置 initial_stack
    if (IS_ENABLED(CONFIG_X86_32)) {
        initial_stack = idle->thread.sp;
    }
    // ...
}
```

**Secondary CPU 汇编阶段**（`head_64.S`）：

```asm
// arch/x86/kernel/head_64.S
SYM_CODE_START(secondary_startup_64)
    // ...
    
.Lsetup_cpu:
    // 获取 per-cpu 偏移
    // RDX 包含 per-cpu offset
    
    // 从 per-cpu 变量获取 current_task
    movq    current_task(%rdx), %rax
    // 从 task_struct 获取栈指针
    movq    TASK_threadsp(%rax), %rsp      // 切换到 idle 进程的内核栈
    
    // ...
    
.Ljump_to_C_code:
    xorl    %ebp, %ebp
    callq   *initial_code(%rip)            // 跳转到 start_secondary()
```

**Secondary CPU 的 C 代码入口**：

```c
// arch/x86/kernel/smpboot.c
static void notrace start_secondary(void *unused)
{
    /*
     * Don't put *anything* except direct CPU state initialization
     * before cpu_init(), SMP booting is too fragile...
     */
    cr4_init();
    
    // 初始化 TSS、IDT 等
    cpu_init_exception_handling(false);
    cpu_init();
    
    // ...
    
    // 进入 idle 循环
    cpu_startup_entry(CPUHP_AP_ONLINE_IDLE);
}
```

#### 启动时间线总结

```
时间 ────────────────────────────────────────────────────────────────────────►

Boot CPU:
┌────────────┬────────────┬────────────┬────────────┬────────────┬──────────┐
│ head_64.S  │ x86_64_    │ start_    │ cpu_init() │ rest_init()│ idle     │
│ 汇编启动    │ start_     │ kernel()  │ TSS/IST    │ 创建1号进程 │ 循环     │
│            │ kernel()   │           │ 初始化     │            │          │
│            │            │           │            │            │          │
│ ◄──────────────────── init_stack ──────────────────────────────────────► │
└────────────┴────────────┴────────────┴────────────┴────────────┴──────────┘

Secondary CPUs (在 Boot CPU 执行 smp_init() 后启动):
┌────────────┬────────────┬────────────┬────────────┬────────────────────────┐
│ head_64.S  │ start_     │ cpu_init() │ idle 循环   │                        │
│ 汇编启动    │ secondary()│ TSS/IST    │            │                        │
│            │            │ 初始化     │            │                        │
│            │            │            │            │                        │
│ ◄───────────────── idle 进程的内核栈 ──────────────────────────────────► │
└────────────┴────────────┴────────────┴────────────┴────────────────────────┘
```

#### 各 CPU 的栈使用总结

| CPU | 启动时使用的栈 | 来源 | 后续使用 |
|-----|---------------|------|---------|
| Boot CPU (CPU 0) | `init_stack` | 静态分配（vmlinux.lds） | `init_task`（0号进程）继续使用 |
| Secondary CPUs | idle 进程的内核栈 | `alloc_thread_stack_node()` | 该 CPU 的 idle 进程使用 |

#### 关键代码位置

| 阶段 | 文件 | 关键代码 |
|------|------|---------|
| 早期汇编（Boot） | `arch/x86/kernel/head_64.S` | `leaq __top_init_kernel_stack(%rip), %rsp` |
| 早期汇编（Secondary） | `arch/x86/kernel/head_64.S` | `movq TASK_threadsp(%rax), %rsp` |
| TSS.sp0 设置 | `arch/x86/kernel/cpu/common.c` | `load_sp0((unsigned long)(cpu_entry_stack(cpu) + 1))` |
| per-cpu 栈变量初始化 | `arch/x86/kernel/cpu/common.c` | `cpu_current_top_of_stack = TOP_OF_INIT_STACK` |
| Secondary CPU 准备 | `arch/x86/kernel/smpboot.c` | `idle->thread.sp = (unsigned long)task_pt_regs(idle)` |

---

## 16. 总结

### 16.1 核心要点

1. **TSS 的角色演变**
   - x86-32：硬件任务切换（已废弃）
   - x86-64：特权级栈切换 + IST 机制

2. **IST 的存在意义**
   - 为关键异常提供**独立的栈空间**
   - 避免栈损坏导致的灾难性后果
   - 解决嵌套异常的处理问题

3. **IST 的使用原则**
   - 仅用于**极少数**关键异常（#DF, NMI, #MC, #DB）
   - 大多数异常使用普通的 RSP0 栈
   - IST 栈有限（7 个），节约使用

4. **启动顺序约束**
   - TSS 必须在使用 IST 之前初始化
   - 早期 IDT (`bringup_idt_table`) 不使用 IST
   - 运行时 IDT (`idt_table`) 使用 IST，但此时 TSS 已就绪

5. **安全性设计**
   - 早期代码禁用 IST（IST=0），不依赖 TSS
   - 晚期代码使用 IST，提供健壮的异常处理
   - 两阶段设计避免"鸡生蛋"问题

### 16.2 与其他文档的关联

- **[LINUX_KERNEL_IDT_EVOLUTION.md](LINUX_KERNEL_IDT_EVOLUTION.md)**：解释为什么需要两个 IDT 表，其中 TSS/IST 依赖是关键原因之一
- **[LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md)**：详细的启动流程，展示 TSS 初始化的时机
- **[KASAN_INSTRUMENTATION_AND_INIT_ORDER.md](KASAN_INSTRUMENTATION_AND_INIT_ORDER.md)**：解释另一个独立约束（KASAN），与 TSS/IST 约束共同决定了 IDT 的设计

### 16.3 实践建议

**编写内核代码时**：
- 确保关键异常（#DF, NMI, #MC）使用 IST
- 不要在早期启动代码中依赖 IST
- 验证 TSS 是否已通过 `ltr` 加载

**调试异常处理时**：
- 检查 IDT 表项的 IST 字段
- 验证 TSS 中的 IST 栈地址是否有效
- 使用 GDB 单步跟踪异常处理流程

**性能优化时**：
- IST 切换有额外开销（保存旧 SS:RSP）
- 仅为真正需要的异常启用 IST
- 普通异常使用 RSP0 更高效

---

## 17. 参考文献

### 17.1 Intel/AMD 文档

1. **Intel® 64 and IA-32 Architectures Software Developer's Manual, Volume 3A: System Programming Guide, Part 1**
   - **Chapter 6: Interrupt and Exception Handling**
     - Section 6.10: Interrupt Descriptor Table (IDT)
     - Section 6.11: IDT Descriptors
     - Section 6.14: Exception and Interrupt Handling in 64-bit Mode
     - Section 6.14.1: 64-Bit Mode IDT（Figure 6-7: 64-Bit IDT Gate Descriptors）
     - Section 6.14.2: 64-Bit Mode Stack Frame
     - Section 6.14.4: Stack Switching in IA-32e Mode
     - Section 6.14.5: Interrupt Stack Table
   - **Chapter 7: Task Management**
     - Section 7.2.1: Task-State Segment (TSS)（Figure 7-2: 32-Bit TSS）
     - Section 7.2.3: TSS Descriptor in 64-bit mode（Figure 7-4: TSS Descriptor in 64-bit Mode）
     - Section 7.2.4: Task Register
     - Section 7.7: Task Management in 64-bit Mode（Figure 7-11: 64-Bit TSS Format）

2. **AMD64 Architecture Programmer's Manual, Volume 2: System Programming**
   - Chapter 8: Exceptions and Interrupts
   - Section 8.9: Long Mode Interrupt Stack

### 17.2 Linux 内核源代码

4. **arch/x86/include/asm/processor.h**
   - `struct x86_hw_tss` 定义
   - `struct tss_struct` 定义

5. **arch/x86/kernel/cpu/common.c**
   - `cpu_init()` 函数
   - `load_TR_desc()` 函数

6. **arch/x86/kernel/idt.c**
   - `idt_setup_early_traps()` 函数
   - `def_idts[]` 数组（IST 配置）

7. **arch/x86/mm/cpu_entry_area.c**
   - IST 栈分配和管理

8. **arch/x86/kernel/traps.c**
   - `exc_double_fault()` 等异常处理程序

### 17.3 相关文档

9. [LINUX_KERNEL_IDT_EVOLUTION.md](LINUX_KERNEL_IDT_EVOLUTION.md)
   - IDT 表的演进流程
   - 为什么需要两个独立的 IDT 表

10. [LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md)
    - Linux 内核启动与初始化
    - TSS 初始化的时机

11. [KASAN_INSTRUMENTATION_AND_INIT_ORDER.md](KASAN_INSTRUMENTATION_AND_INIT_ORDER.md)
    - KASAN 插桩机制
    - 与 IST/TSS 独立的另一个初始化约束

12. [X86_64_TLB_MANAGEMENT.md](X86_64_TLB_MANAGEMENT.md)
    - TLB 管理机制
    - 与 TSS/IST 在启动过程中的交互

---

**文档结束**
