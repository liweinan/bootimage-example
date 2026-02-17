# BIOS IVT 与 Kernel IDT 数据结构详细对比

**版本**: 1.0
**日期**: 2026-02-17
**作者**: Linux 内核启动文档项目

> 📚 **文档导航**: [返回总索引](DOCUMENT_INDEX.md) | [阅读指南](READING_GUIDE.md) | [IDT 演进](LINUX_KERNEL_IDT_EVOLUTION.md)

> **相关文档**：
> - 关于 **IVT 和 IDT 的软件中断服务程序对比**（BIOS 服务 vs 内核系统调用、硬件中断与软件中断的协作关系），请参见 [BIOS IVT 与 Kernel IDT 的软件中断服务程序对比](BIOS_IVT_VS_KERNEL_IDT.md)
> - 关于 **TSS 和 IST 机制**（IDT 中的 IST 字段用途、独立栈机制），请参见 [x86-64 任务状态段（TSS）与中断栈表（IST）详解](X86_64_TSS_AND_IST.md)
> - 关于 **idt_setup_early_handler() 函数详解**（Linux 内核如何初始化 IDT），请参见 [idt_setup_early_handler() 函数详细分析](IDT_SETUP_EARLY_HANDLER_DETAILED_ANALYSIS.md)

---

## 目录

1. [概述：两种截然不同的设计](#1-概述两种截然不同的设计)
2. [BIOS IVT (Interrupt Vector Table)](#2-bios-ivt-interrupt-vector-table)
3. [Kernel IDT (Interrupt Descriptor Table)](#3-kernel-idt-interrupt-descriptor-table)
4. [数据结构详细对比](#4-数据结构详细对比)
5. [硬件处理机制对比](#5-硬件处理机制对比)
6. [初始化代码对比](#6-初始化代码对比)
7. [从 IVT 到 IDT 的演进过程](#7-从-ivt-到-idt-的演进过程)
8. [为什么 x86-64 必须使用 IDT？](#8-为什么-x86-64-必须使用-idt)

---

## 1. 概述：两种截然不同的设计

**核心差异**：

| 特性 | BIOS IVT | Kernel IDT |
|------|----------|------------|
| **CPU 模式** | 实模式（Real Mode） | 保护模式/长模式（Protected/Long Mode） |
| **架构** | 16 位 | 32 位 / 64 位 |
| **表项大小** | **4 字节** | **16 字节** |
| **表项内容** | 直接包含处理程序地址（段:偏移） | 包含门描述符（复杂结构） |
| **地址模式** | 段:偏移（20 位物理地址） | 线性地址（32/64 位） |
| **固定位置** | ✅ 是（0x00000000） | ❌ 否（由 IDTR 指定） |
| **特权级** | ❌ 无（实模式无特权级） | ✅ 有（DPL, CPL） |
| **IST 支持** | ❌ 无 | ✅ 有（x86-64） |
| **硬件设计时代** | 8086（1978年） | 80286+（1982年+） |

**关键结论**：

- **IVT**：简单的地址数组，适合实模式的简单保护需求
- **IDT**：复杂的描述符表，支持现代操作系统的安全和性能需求
- **不兼容**：两者完全不兼容，从实模式切换到保护模式必须重建中断表

---

## 2. BIOS IVT (Interrupt Vector Table)

### 2.1 IVT 的数据结构

**IVT 是一个包含 256 个 4 字节条目的数组，每个条目包含一个段:偏移地址。**

#### 单个 IVT 条目结构

```
偏移量 | 大小 | 字段     | 说明
-------|------|---------|----------------------------------------
+0     | 2B   | Offset  | 中断处理程序的偏移地址（16 位）
+2     | 2B   | Segment | 中断处理程序的段地址（16 位）

总大小：4 字节
```

**示例：IVT[0x13]（磁盘服务）**

```
地址：0x0000:0x004C（物理地址 0x4C）

+0x004C: 0x12 0x34  ← 偏移地址 = 0x3412（小端序）
+0x004E: 0x00 0xF0  ← 段地址 = 0xF000

中断处理程序地址：0xF000:0x3412
物理地址 = 0xF000 × 16 + 0x3412 = 0xF3412
```

#### 完整 IVT 布局

```
物理地址范围：0x00000 - 0x003FF（1024 字节 = 256 × 4）

地址         | 向量号 | 中断类型
-------------|--------|------------------------------------------
0x0000-0x0003| 0x00   | #DE - Divide Error
0x0004-0x0007| 0x01   | #DB - Debug Exception
0x0008-0x000B| 0x02   | NMI
0x000C-0x000F| 0x03   | #BP - Breakpoint
...          | ...    | ...
0x0020-0x0023| 0x08   | IRQ0 - Timer (硬件中断)
0x0024-0x0027| 0x09   | IRQ1 - Keyboard (硬件中断)
...          | ...    | ...
0x0040-0x0043| 0x10   | INT 10h - Video Service (BIOS 服务)
...          | ...    | ...
0x004C-0x004F| 0x13   | INT 13h - Disk Service (BIOS 服务)
...          | ...    | ...
0x03FC-0x03FF| 0xFF   | 保留
```

### 2.2 IVT 的初始化

**SeaBIOS 初始化 IVT 的代码：**

```c
// seabios/src/post.c:568-582
static void
ivt_init(void)
{
    dprintf(3, "init ivt\n");

    // 初始化异常向量（0x00-0x1F）
    int i;
    for (i=0; i<0x20; i++)
        SET_IVT(i, FUNC16(entry_iret_official));

    // 初始化硬件中断向量（IRQ0-7：0x08-0x0F，IRQ8-15：0x70-0x77）
    for (i=BIOS_HWIRQ0_VECTOR; i<BIOS_HWIRQ0_VECTOR+8; i++)
        SET_IVT(i, FUNC16(entry_hwpic1));
    for (i=BIOS_HWIRQ8_VECTOR; i<BIOS_HWIRQ8_VECTOR+8; i++)
        SET_IVT(i, FUNC16(entry_hwpic2));

    // 初始化 BIOS 软件中断服务（INT 10h, 13h 等）
    // ...
}
```

**SET_IVT 宏定义：**

```c
// seabios/src/util.h
#define SET_IVT(vector, segoff) \
    SET_FARVAR(SEG_IVT, *(struct segoff_s *)(vector*4), segoff)

// struct segoff_s 定义
struct segoff_s {
    u16 offset;  // 偏移地址
    u16 seg;     // 段地址
};
```

**实际操作：**

```c
// 设置 IVT[0x13] = 0xF000:0x12AB（INT 13h 磁盘服务）
SET_IVT(0x13, FUNC16(handle_13));

// 展开为：
*(u16 *)(0x0000 + 0x13 * 4 + 0) = 0x12AB;  // 偏移地址
*(u16 *)(0x0000 + 0x13 * 4 + 2) = 0xF000;  // 段地址
```

### 2.3 CPU 查找 IVT 的过程

**实模式下触发中断（以 INT 0x13 为例）：**

```
1. 用户程序执行：
   int 0x13

2. CPU 自动执行：
   ├─ 读取 IVT[0x13]：
   │    地址 = 0x0000:0x004C = 物理地址 0x4C
   │    读取 4 字节：
   │      偏移 = [0x4C] = 0x3412
   │      段   = [0x4E] = 0xF000
   │
   ├─ 计算物理地址：
   │    物理地址 = 0xF000 × 16 + 0x3412 = 0xF3412
   │
   ├─ 压栈（保存返回地址和标志）：
   │    push FLAGS
   │    push CS
   │    push IP
   │
   ├─ 清除中断标志：
   │    FLAGS.IF = 0（禁用中断）
   │
   └─ 跳转到处理程序：
        CS = 0xF000
        IP = 0x3412
        继续执行
```

**关键点**：

- IVT 地址**固定**在物理地址 0x00000
- CPU **直接读取** 4 字节（段:偏移）
- **没有权限检查**（实模式无特权级）
- **没有类型检查**（只是地址，不区分中断门/陷阱门）

---

## 3. Kernel IDT (Interrupt Descriptor Table)

### 3.1 IDT 的数据结构

**IDT 是一个包含 256 个 16 字节门描述符的数组，每个条目是一个复杂的结构。**

#### 单个 IDT 条目结构（x86-64）

```
偏移量 | 大小 | 字段            | 说明
-------|------|----------------|----------------------------------------
+0     | 2B   | offset_low     | 处理程序地址的低 16 位
+2     | 2B   | segment        | 代码段选择子（如 __KERNEL_CS = 0x10）
+4     | 2B   | bits           | 控制位（IST, Type, DPL, P）
+6     | 2B   | offset_middle  | 处理程序地址的中间 16 位
+8     | 4B   | offset_high    | 处理程序地址的高 32 位
+12    | 4B   | reserved       | 保留（必须为 0）

总大小：16 字节
```

**bits 字段详细结构（2 字节）：**

```
位      | 字段  | 大小 | 说明
--------|-------|------|------------------------------------------
0-2     | IST   | 3位  | Interrupt Stack Table 索引（0-7）
3-7     | zero  | 5位  | 必须为 0
8-12    | type  | 5位  | 门类型（Interrupt/Trap/Task Gate）
13-14   | DPL   | 2位  | Descriptor Privilege Level（0-3）
15      | P     | 1位  | Present 位（必须为 1）
```

**类型（type）值：**

| 值   | 类型                | 说明 |
|------|---------------------|------|
| 0xE  | Interrupt Gate（64位）| 禁用中断的门 |
| 0xF  | Trap Gate（64位）     | 不禁用中断的门 |
| 0x5  | Task Gate（已废弃）   | x86-32，x86-64 不支持 |

**Linux 内核中的结构定义：**

```c
// arch/x86/include/asm/desc_defs.h:79-91
struct gate_desc {
    u16         offset_low;      // 处理程序地址 [15:0]
    u16         segment;         // 代码段选择子
    struct idt_bits bits;        // 控制位
    u16         offset_middle;   // 处理程序地址 [31:16]
    u32         offset_high;     // 处理程序地址 [63:32]
    u32         reserved;        // 保留（必须为 0）
} __attribute__((packed));

// idt_bits 结构
struct idt_bits {
    u16     ist     : 3,    // IST 索引（0-7）
            zero    : 5,    // 必须为 0
            type    : 5,    // 门类型
            dpl     : 2,    // 特权级（0-3）
            p       : 1;    // Present
} __attribute__((packed));
```

**示例：IDT[14]（#PF - Page Fault）**

假设处理程序地址 = `0xffffffff81234567`：

```
+0:  0x45 0x67           ← offset_low = 0x4567
+2:  0x10 0x00           ← segment = 0x0010 (__KERNEL_CS)
+4:  0x8E 0x00           ← bits = 0x008E
                           ├─ IST = 0（不使用 IST）
                           ├─ type = 0xE（Interrupt Gate）
                           ├─ DPL = 0（Ring 0 only）
                           └─ P = 1（Present）
+6:  0x12 0x34           ← offset_middle = 0x1234
+8:  0x81 0xFF 0xFF 0xFF ← offset_high = 0xFFFFFF81
+12: 0x00 0x00 0x00 0x00 ← reserved = 0

处理程序地址 = 0xFFFFFF81 << 32 | 0x1234 << 16 | 0x4567
             = 0xFFFFFFFF81234567
```

### 3.2 IDT 的位置和加载

**IDT 的位置由 IDTR（IDT Register）指定，不是固定的。**

#### IDTR 寄存器结构

```
x86-64 模式：

+0     | 2B   | Limit   | IDT 表大小 - 1（字节数）
+2     | 8B   | Base    | IDT 表的 64 位线性地址

总大小：10 字节
```

**Linux 内核中的定义：**

```c
// arch/x86/include/asm/desc_defs.h:23-26
struct desc_ptr {
    unsigned short size;        // IDT 表大小 - 1
    unsigned long address;      // IDT 表的线性地址
} __attribute__((packed));
```

**示例：Linux 内核的 IDT 描述符**

```c
// arch/x86/kernel/idt.c:175-178
static struct desc_ptr idt_descr __ro_after_init = {
    .size    = IDT_TABLE_SIZE - 1,    // 4096 - 1 = 4095
    .address = (unsigned long) idt_table,  // idt_table 数组地址
};

// IDT_TABLE_SIZE = 256 * 16 = 4096 字节
```

**加载 IDT：**

```c
// arch/x86/kernel/idt.c:405-409
static inline void load_idt(const struct desc_ptr *dtr)
{
    asm volatile("lidt %0"::"m" (dtr->size));
}

// 调用：
load_idt(&idt_descr);
```

**LIDT 指令的操作：**

```asm
lidt (%rdi)   ; RDI = &idt_descr

; CPU 自动执行：
; IDTR.limit = idt_descr.size = 4095
; IDTR.base  = idt_descr.address = &idt_table
```

### 3.3 CPU 查找 IDT 的过程

**保护模式/长模式下触发中断（以 #PF 为例）：**

```
1. CPU 触发缺页异常（#PF，向量 14）

2. CPU 自动执行：
   ├─ 读取 IDTR：
   │    Base  = 0xffffffff82000000（假设）
   │    Limit = 4095
   │
   ├─ 计算 IDT 条目地址：
   │    地址 = Base + 向量号 × 16
   │         = 0xffffffff82000000 + 14 × 16
   │         = 0xffffffff820000E0
   │
   ├─ 读取 IDT[14]（16 字节门描述符）：
   │    offset_low    = 0x4567
   │    segment       = 0x0010 (__KERNEL_CS)
   │    bits.ist      = 0
   │    bits.type     = 0xE（Interrupt Gate）
   │    bits.dpl      = 0
   │    bits.p        = 1
   │    offset_middle = 0x1234
   │    offset_high   = 0xFFFFFF81
   │
   ├─ 组合处理程序地址：
   │    地址 = offset_high << 32 | offset_middle << 16 | offset_low
   │         = 0xFFFFFFFF81234567
   │
   ├─ 特权级检查：
   │    CPL（当前特权级）= 3（用户态）
   │    DPL（描述符特权级）= 0（内核态）
   │    → 允许切换（异常总是允许切换到更高特权级）
   │
   ├─ IST 检查：
   │    IST = 0（不使用独立栈）
   │    → 使用当前内核栈（或 TSS.RSP0 如果从用户态进入）
   │
   ├─ 压栈（保存返回地址和状态）：
   │    push SS        （如果特权级切换）
   │    push RSP       （如果特权级切换）
   │    push RFLAGS
   │    push CS
   │    push RIP
   │    push Error Code（#PF 会自动压入错误码）
   │
   ├─ 加载新的段和地址：
   │    CS = 0x0010 (__KERNEL_CS)
   │    RIP = 0xFFFFFFFF81234567
   │
   └─ 如果是 Interrupt Gate：
        RFLAGS.IF = 0（禁用中断）

3. 继续执行处理程序
```

**关键点**：

- IDT 地址**不固定**，由 IDTR 指定
- CPU 读取 **16 字节**复杂的门描述符
- **有权限检查**（DPL, CPL）
- **有类型区分**（Interrupt Gate vs Trap Gate）
- **支持 IST**（x86-64 独立栈机制）
- **支持跨特权级**（用户态→内核态）

---

## 4. 数据结构详细对比

### 4.1 表项结构对比

```
┌─────────────────────────────────────────────────────────────┐
│  BIOS IVT 条目（4 字节）                                     │
├─────────────────────────────────────────────────────────────┤
│  +0 (2B): Offset  ← 处理程序偏移地址（16 位）              │
│  +2 (2B): Segment ← 处理程序段地址（16 位）                │
└─────────────────────────────────────────────────────────────┘
                        ↓
            物理地址 = Segment × 16 + Offset
                        ↓
                  最大 20 位（1MB）


┌─────────────────────────────────────────────────────────────┐
│  Kernel IDT 条目（16 字节）                                 │
├─────────────────────────────────────────────────────────────┤
│  +0  (2B): offset_low     ← 地址 [15:0]                     │
│  +2  (2B): segment        ← 段选择子（查 GDT）              │
│  +4  (2B): bits           ← IST(3) | zero(5) | type(5) |    │
│            ├─ IST(3位): 0-7                  DPL(2) | P(1)  │
│            ├─ type(5位): 0xE/0xF                            │
│            ├─ DPL(2位): 0-3                                 │
│            └─ P(1位): 0/1                                   │
│  +6  (2B): offset_middle  ← 地址 [31:16]                    │
│  +8  (4B): offset_high    ← 地址 [63:32]                    │
│  +12 (4B): reserved       ← 必须为 0                        │
└─────────────────────────────────────────────────────────────┘
                        ↓
         64 位线性地址 = offset_high << 32 |
                        offset_middle << 16 |
                        offset_low
```

### 4.2 大小对比

| 特性 | BIOS IVT | Kernel IDT |
|------|----------|------------|
| **单个条目大小** | 4 字节 | 16 字节 |
| **条目数量** | 256 | 256 |
| **总大小** | 1024 字节（1KB） | 4096 字节（4KB，1 页） |
| **地址空间** | 20 位（1MB） | 64 位（16EB） |
| **对齐要求** | 无（固定地址 0x0000） | 页对齐（4KB 边界） |

### 4.3 字段对比

| 功能 | BIOS IVT | Kernel IDT |
|------|----------|------------|
| **处理程序地址** | 直接存储（段:偏移，4 字节） | 分段存储（低/中/高，8 字节） |
| **段选择子** | ❌ 无（直接段地址） | ✅ 有（2 字节，查 GDT） |
| **类型标识** | ❌ 无 | ✅ 有（Interrupt/Trap Gate） |
| **特权级** | ❌ 无 | ✅ 有（DPL，0-3） |
| **IST 支持** | ❌ 无 | ✅ 有（x86-64，3 位） |
| **Present 位** | ❌ 无 | ✅ 有（1 位） |
| **保留字段** | ❌ 无 | ✅ 有（4 字节） |

### 4.4 地址计算对比

**IVT 地址计算（实模式）：**

```
物理地址 = Segment × 16 + Offset

示例：
Segment = 0xF000
Offset  = 0x3412
物理地址 = 0xF000 × 16 + 0x3412
         = 0xF0000 + 0x3412
         = 0xF3412（20 位）

特点：
- 简单的线性计算
- 最大 20 位（1MB）
- 无需查表（GDT/LDT）
```

**IDT 地址计算（保护模式/长模式）：**

```
步骤 1：组合处理程序地址
线性地址 = offset_high << 32 | offset_middle << 16 | offset_low

示例：
offset_high   = 0xFFFFFF81
offset_middle = 0x1234
offset_low    = 0x4567
线性地址 = 0xFFFFFF81 << 32 | 0x1234 << 16 | 0x4567
         = 0xFFFFFFFF81234567（64 位）

步骤 2：查 GDT 获取段基址（保护模式，长模式下通常为 0）
段选择子 = 0x0010 (__KERNEL_CS)
查 GDT[2]（0x10 >> 3 = 2）
段基址 = 0（长模式下代码段基址总是 0）

步骤 3：计算最终地址
物理地址 = 段基址 + 线性地址
         = 0 + 0xFFFFFFFF81234567
         = 0xFFFFFFFF81234567（通过页表转换为物理地址）

特点：
- 复杂的多级查找
- 最大 64 位（理论上 16EB，实际约 48 位）
- 需要查 GDT
- 需要页表转换
```

---

## 5. 硬件处理机制对比

### 5.1 中断触发时的 CPU 行为

#### IVT（实模式）

```
1. CPU 收到中断（向量号 N）

2. 读取 IVT[N]：
   地址 = 0x0000 + N × 4
   读取 4 字节：
     Offset  = [地址 + 0]
     Segment = [地址 + 2]

3. 压栈（6 字节）：
   push FLAGS（2 字节）
   push CS（2 字节）
   push IP（2 字节）

4. 清除中断标志：
   FLAGS.IF = 0（禁用中断）
   FLAGS.TF = 0（禁用单步）

5. 跳转：
   CS = Segment
   IP = Offset

6. 继续执行处理程序
```

**栈帧布局（实模式）：**

```
高地址
┌──────────────┐
│  FLAGS（旧） │ ← 返回前的标志寄存器
├──────────────┤
│  CS（旧）    │ ← 返回地址段
├──────────────┤
│  IP（旧）    │ ← 返回地址偏移
├──────────────┤ ← SP（进入处理程序后）
│  ...          │
低地址
```

#### IDT（保护模式/长模式）

```
1. CPU 收到中断（向量号 N）

2. 读取 IDTR：
   Base  = IDTR.base
   Limit = IDTR.limit

3. 检查向量号：
   if (N × 16 > Limit) → #GP（向量号越界）

4. 读取 IDT[N]：
   地址 = Base + N × 16
   读取 16 字节门描述符

5. 检查 Present 位：
   if (P == 0) → #NP（段不存在）

6. 特权级检查：
   DPL = 门描述符的 DPL
   CPL = 当前特权级
   if (软件中断 && DPL < CPL) → #GP（特权级违规）

7. IST 检查（x86-64）：
   if (IST != 0) {
       从 TSS.IST[IST-1] 读取栈地址
       切换到独立栈
   } else if (CPL 改变) {
       从 TSS.RSP0 读取内核栈地址
       切换到内核栈
   }

8. 压栈（x86-64，可变大小）：
   if (CPL 改变) {
       push SS（8 字节）
       push RSP（8 字节）
   }
   push RFLAGS（8 字节）
   push CS（8 字节）
   push RIP（8 字节）
   if (有错误码) {
       push Error Code（8 字节）
   }

9. 加载新段和地址：
   CS = 门描述符的 segment
   RIP = 组合的 64 位地址

10. 如果是 Interrupt Gate：
    RFLAGS.IF = 0（禁用中断）
    如果是 Trap Gate：
    保持 RFLAGS.IF 不变

11. 继续执行处理程序
```

**栈帧布局（x86-64，特权级切换）：**

```
高地址
┌──────────────┐
│  SS（旧）    │ ← 用户态栈段（8 字节）
├──────────────┤
│  RSP（旧）   │ ← 用户态栈指针（8 字节）
├──────────────┤
│  RFLAGS（旧）│ ← 返回前的标志（8 字节）
├──────────────┤
│  CS（旧）    │ ← 返回代码段（8 字节）
├──────────────┤
│  RIP（旧）   │ ← 返回地址（8 字节）
├──────────────┤
│  Error Code  │ ← 错误码（如果有，8 字节）
├──────────────┤ ← RSP（进入处理程序后）
│  ...          │
低地址
```

### 5.2 关键差异

| 操作 | IVT（实模式） | IDT（保护模式/长模式） |
|------|--------------|----------------------|
| **查找表** | 固定地址 0x0000 | IDTR 指定的地址 |
| **读取大小** | 4 字节 | 16 字节 |
| **权限检查** | ❌ 无 | ✅ 有（DPL vs CPL） |
| **类型检查** | ❌ 无 | ✅ 有（Interrupt/Trap） |
| **栈切换** | ❌ 无（始终当前栈） | ✅ 有（IST, RSP0） |
| **压栈大小** | 6 字节（固定） | 40-48 字节（可变） |
| **错误码** | ❌ 不支持 | ✅ 支持（某些异常） |
| **禁用中断** | ✅ 总是（IF=0, TF=0） | ⚠️ 取决于类型（Interrupt Gate 禁用，Trap Gate 不禁用） |

---

## 6. 初始化代码对比

### 6.1 BIOS IVT 初始化

```c
// seabios/src/post.c:568-582
static void
ivt_init(void)
{
    dprintf(3, "init ivt\n");

    // 初始化所有异常向量（0x00-0x1F）
    int i;
    for (i=0; i<0x20; i++)
        SET_IVT(i, FUNC16(entry_iret_official));

    // 初始化硬件中断向量（主 PIC：0x08-0x0F）
    for (i=BIOS_HWIRQ0_VECTOR; i<BIOS_HWIRQ0_VECTOR+8; i++)
        SET_IVT(i, FUNC16(entry_hwpic1));

    // 初始化硬件中断向量（从 PIC：0x70-0x77）
    for (i=BIOS_HWIRQ8_VECTOR; i<BIOS_HWIRQ8_VECTOR+8; i++)
        SET_IVT(i, FUNC16(entry_hwpic2));
}

// SET_IVT 宏定义
#define SET_IVT(vector, segoff) \
    SET_FARVAR(SEG_IVT, *(struct segoff_s *)(vector*4), segoff)

// 示例：设置 IVT[0x13]
SET_IVT(0x13, SEGOFF(SEG_BIOS, offset_handle_13));

// 展开为：
*(u16 *)(0x0000 + 0x13 * 4 + 0) = offset_handle_13;  // 偏移
*(u16 *)(0x0000 + 0x13 * 4 + 2) = SEG_BIOS;          // 段
```

**特点**：
- **简单直接**：直接写入固定地址（0x0000）
- **无结构复杂性**：只是段:偏移地址
- **无权限设置**：实模式无特权级概念

### 6.2 Linux Kernel IDT 初始化

```c
// arch/x86/kernel/idt.c:317-331
void __init idt_setup_early_handler(void)
{
    int i;

    // 设置前 32 个异常向量
    for (i = 0; i < NUM_EXCEPTION_VECTORS; i++)
        set_intr_gate(i, early_idt_handler_array[i]);

    // 加载新的 IDT
    load_idt(&idt_descr);
}

// set_intr_gate 实现
static __init void set_intr_gate(unsigned int n, const void *addr)
{
    struct idt_data data;

    // 初始化 idt_data 结构
    init_idt_data(&data, n, addr);

    // 写入 IDT 表
    idt_setup_from_table(idt_table, &data, 1, false);
}

// init_idt_data 宏
#define init_idt_data(data, n, addr)            \
do {                                             \
    (data)->vector   = (n);                      \
    (data)->bits.ist = DEFAULT_STACK;            \  // IST = 0
    (data)->bits.type = GATE_INTERRUPT;          \  // 0xE
    (data)->bits.dpl  = DPL0;                    \  // 特权级 0
    (data)->bits.p    = 1;                       \  // Present
    (data)->addr      = (addr);                  \
    (data)->segment   = __KERNEL_CS;             \  // 内核代码段
} while (0)

// idt_setup_from_table 实现
static __init void
idt_setup_from_table(gate_desc *idt, const struct idt_data *t,
                     int size, bool sys)
{
    gate_desc desc;

    for (; size > 0; t++, size--) {
        // 构建门描述符
        idt_init_desc(&desc, t);

        // 写入 IDT
        write_idt_entry(idt, t->vector, &desc);
    }
}

// idt_init_desc 实现
static inline void idt_init_desc(gate_desc *gate,
                                  const struct idt_data *d)
{
    unsigned long addr = (unsigned long) d->addr;

    gate->offset_low    = (u16) addr;
    gate->segment       = (u16) d->segment;
    gate->bits          = d->bits;
    gate->offset_middle = (u16) (addr >> 16);
    gate->offset_high   = (u32) (addr >> 32);
    gate->reserved      = 0;
}

// write_idt_entry 实现
static inline void write_idt_entry(gate_desc *idt, int entry,
                                    const gate_desc *gate)
{
    memcpy(&idt[entry], gate, sizeof(*gate));
}
```

**特点**：
- **复杂结构**：需要构建 16 字节的门描述符
- **多层抽象**：idt_data → gate_desc → idt_table
- **权限管理**：设置 DPL, type, P 等控制位
- **类型安全**：区分 Interrupt Gate 和 Trap Gate

---

## 7. 从 IVT 到 IDT 的演进过程

### 7.1 启动时的表切换

**完整的中断表演进流程：**

```
┌─────────────────────────────────────────────────────────────┐
│  阶段 0：BIOS 控制                                           │
├─────────────────────────────────────────────────────────────┤
│  模式：实模式（16 位）                                       │
│  表：  IVT（固定地址 0x0000）                               │
│  大小：1024 字节（256 × 4）                                 │
│  作用：处理 BIOS 服务、硬件中断                             │
└─────────────────────────────────────────────────────────────┘
                        ↓
                  引导加载程序（GRUB）加载内核
                        ↓
┌─────────────────────────────────────────────────────────────┐
│  阶段 1：压缩内核的临时 IDT                                 │
├─────────────────────────────────────────────────────────────┤
│  模式：长模式（64 位）                                       │
│  表：  bringup_idt_table                                     │
│  位置：arch/x86/boot/compressed/idt_64.c                    │
│  大小：4096 字节（256 × 16）                                │
│  作用：解压内核时的基本异常处理                             │
│  特点：IST = 0（不使用独立栈）                             │
└─────────────────────────────────────────────────────────────┘
                        ↓
                  内核解压完成，跳转到主内核
                        ↓
┌─────────────────────────────────────────────────────────────┐
│  阶段 2：早期主内核 IDT（idt_setup_early_handler）         │
├─────────────────────────────────────────────────────────────┤
│  模式：长模式（64 位）                                       │
│  表：  idt_table                                             │
│  位置：arch/x86/kernel/idt.c                                │
│  大小：4096 字节（256 × 16）                                │
│  作用：处理前 32 个异常（0-31）                             │
│  特点：IST = 0（TSS 尚未初始化）                           │
└─────────────────────────────────────────────────────────────┘
                        ↓
                  TSS 初始化（cpu_init）
                        ↓
┌─────────────────────────────────────────────────────────────┐
│  阶段 3：完整的运行时 IDT（idt_setup_traps）               │
├─────────────────────────────────────────────────────────────┤
│  模式：长模式（64 位）                                       │
│  表：  idt_table（同一个表，重新填充）                      │
│  大小：4096 字节（256 × 16）                                │
│  作用：处理所有异常和中断（0-255）                          │
│  特点：关键异常使用 IST（#DF, NMI, #MC）                   │
└─────────────────────────────────────────────────────────────┘
```

### 7.2 为什么不能继续使用 IVT？

**IVT 只能在实模式下使用，原因：**

1. **地址空间限制**：
   - IVT 只支持 20 位物理地址（1MB）
   - 保护模式/长模式需要 32/64 位地址

2. **无特权级保护**：
   - 实模式无 Ring 0-3 概念
   - 保护模式需要 DPL/CPL 检查

3. **无类型区分**：
   - IVT 只是简单的地址
   - IDT 需要区分 Interrupt Gate, Trap Gate

4. **无栈切换支持**：
   - IVT 始终使用当前栈
   - IDT 支持 IST 独立栈

5. **硬件不支持**：
   - CPU 在保护模式/长模式下**强制使用 IDT**
   - IDTR 寄存器取代固定地址 0x0000

**关键代码：切换到保护模式时必须加载 IDT**

```asm
; arch/x86/boot/compressed/head_64.S
; 切换到保护模式前
lgdt gdt_ptr        ; 加载 GDT
lidt idt_ptr        ; 加载 IDT（必须，否则 CPU 异常）
mov cr0, eax        ; 启用保护模式（PE = 1）
```

---

## 8. 为什么 x86-64 必须使用 IDT？

### 8.1 x86-64 的强制要求

**Intel SDM 明确规定**（Volume 3A, Section 6.14）：

> In IA-32e mode (long mode), the processor uses the IDT structure
> described in this section. **The real-address mode IVT structure
> is not supported in IA-32e mode.**

**翻译**：在 IA-32e 模式（长模式）下，处理器使用本节描述的 IDT 结构。**实模式的 IVT 结构在 IA-32e 模式下不被支持。**

### 8.2 技术原因

**1. 64 位地址空间**

```
IVT：
┌────────────────────┐
│  段:偏移（4 字节） │
└────────────────────┘
        ↓
物理地址 = 段 × 16 + 偏移
最大 20 位（1MB）❌

IDT：
┌────────────────────┐
│  64 位线性地址     │
│  （8 字节）        │
└────────────────────┘
        ↓
64 位地址空间 ✅
```

**2. 安全性需求**

```
IVT：
- 无 DPL（特权级）检查❌
- 任何代码都可以修改 IVT
- 任何代码都可以调用任何中断

IDT：
- 有 DPL 检查✅
- 只有内核可以修改 IDT
- 用户态只能调用 DPL=3 的门
```

**3. 栈切换支持**

```
IVT：
- 始终使用当前栈❌
- 栈溢出会导致三重故障

IDT：
- 支持 TSS.RSP0（特权级切换）✅
- 支持 IST（独立栈）✅
- 栈溢出有独立的 #DF 栈
```

**4. 硬件设计**

```
x86-64 CPU 在长模式下：
1. 不查 IVT（地址 0x0000）
2. 强制查 IDTR 指定的 IDT
3. 读取 16 字节门描述符
4. 执行完整的权限和类型检查
```

### 8.3 对比总结

| 特性 | BIOS IVT | Kernel IDT | 为什么必须用 IDT？ |
|------|----------|------------|-------------------|
| **CPU 模式** | 实模式 | 保护/长模式 | x86-64 强制长模式 |
| **地址空间** | 20 位（1MB） | 64 位（16EB） | 支持大内存 |
| **安全性** | 无 | 有（DPL/CPL） | 防止权限提升 |
| **栈切换** | 无 | 有（IST/RSP0） | 防止栈溢出崩溃 |
| **类型系统** | 无 | 有（Interrupt/Trap） | 控制中断状态 |
| **错误恢复** | 无 | 有（#DF 独立栈） | 提高系统健壮性 |

---

## 9. 总结

### 9.1 核心差异

**BIOS IVT（实模式）**：
- **简单**：4 字节条目，直接段:偏移地址
- **固定**：物理地址 0x0000
- **快速**：无复杂检查
- **受限**：20 位地址空间，无安全机制
- **适用**：简单的 BIOS 环境

**Kernel IDT（保护/长模式）**：
- **复杂**：16 字节条目，包含门描述符
- **灵活**：IDTR 指定位置
- **安全**：DPL/CPL 检查，类型系统
- **强大**：64 位地址空间，IST 独立栈
- **适用**：现代操作系统

### 9.2 演进必然性

```
8086（1978）→ IVT：实模式，简单足够
                ↓
80286（1982）→ IDT：保护模式，需要安全
                ↓
80386（1985）→ IDT：32 位，需要大地址
                ↓
x86-64（2003）→ IDT：长模式，强制要求
```

### 9.3 关键要点

1. **数据结构完全不同**：
   - IVT：4 字节简单地址
   - IDT：16 字节复杂描述符

2. **硬件处理机制不同**：
   - IVT：固定地址，直接跳转
   - IDT：IDTR 指定，权限检查，栈切换

3. **不能共存**：
   - CPU 在保护/长模式下**强制使用 IDT**
   - 从实模式切换必须重建中断表

4. **设计哲学不同**：
   - IVT：简单、快速、直接
   - IDT：安全、灵活、可控

---

## 10. 参考文献

### 10.1 Intel 手册

1. **Intel 64 and IA-32 Architectures Software Developer's Manual**
   - Volume 3A, Chapter 6: Interrupt and Exception Handling
   - Volume 3A, Section 6.10: Interrupt Descriptor Table (IDT)
   - Volume 3A, Section 6.14: Exception and Interrupt Handling in 64-Bit Mode

### 10.2 Linux 内核源代码

2. **arch/x86/kernel/idt.c**
   - `idt_table` 定义
   - `idt_setup_early_handler()` 函数
   - `set_intr_gate()` 函数

3. **arch/x86/include/asm/desc_defs.h**
   - `gate_desc` 结构定义
   - `idt_bits` 结构定义

4. **arch/x86/boot/compressed/idt_64.c**
   - `bringup_idt_table` 定义

### 10.3 SeaBIOS 源代码

5. **seabios/src/post.c**
   - `ivt_init()` 函数

6. **seabios/src/util.h**
   - `SET_IVT` 宏定义

### 10.4 相关文档

7. [LINUX_KERNEL_IDT_EVOLUTION.md](LINUX_KERNEL_IDT_EVOLUTION.md)
   - Linux IDT 表的演进流程

8. [IDT_SETUP_EARLY_HANDLER_DETAILED_ANALYSIS.md](IDT_SETUP_EARLY_HANDLER_DETAILED_ANALYSIS.md)
   - `idt_setup_early_handler()` 函数详细分析

9. [X86_64_TSS_AND_IST.md](X86_64_TSS_AND_IST.md)
   - TSS 和 IST 机制详解

---

**文档结束**
