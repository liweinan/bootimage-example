# x86-64 任务状态段（TSS）与中断栈表（IST）详解

**版本**: 3.0  
**日期**: 2026-06-21  
**作者**: Linux 内核启动文档项目

> **文档导航**: [返回总索引](DOCUMENT_INDEX.md) | [IDT 演进](LINUX_KERNEL_IDT_EVOLUTION.md) | [内核启动](LINUX_KERNEL_INIT.md)

---

## 目录

1. [概述](#1-概述)
2. [硬件：64 位 TSS 结构](#2-硬件64-位-tss-结构)
3. [硬件：IST 机制](#3-硬件ist-机制)
4. [数据栈 IST 与影子栈 SSP](#4-数据栈-ist-与影子栈-ssp)
5. [Linux 数据结构总览](#5-linux-数据结构总览)
6. [Linux 七个 IST 槽位：定义、分配与使用](#6-linux-七个-ist-槽位定义分配与使用)
7. [Linux IST 栈内存布局与分配](#7-linux-ist-栈内存布局与分配)
8. [Linux 初始化时序](#8-linux-初始化时序)
9. [Linux 异常入口路径](#9-linux-异常入口路径)
10. [IST 与 IDT 的集成](#10-ist-与-idt-的集成)
11. [为什么需要 IST](#11-为什么需要-ist)
12. [启动早期约束](#12-启动早期约束)
13. [调试与验证](#13-调试与验证)
14. [附录：TSS 角色演变与 Entry Trampoline](#14-附录tss-角色演变与-entry-trampoline)
15. [参考文献](#15-参考文献)

---

## 1. 概述

### 1.1 TSS 与 IST 各自是什么

**TSS (Task State Segment)** 在 x86-64 中是一个 104 字节的内存数据结构，由 **TR 寄存器**指向。硬件任务切换在 64 位模式下已废弃，但 TSS **必须存在**（Intel SDM Vol 3A §7.7）。

**IST (Interrupt Stack Table)** 是 TSS 中的 7 个 64 位栈指针（IST1–IST7），配合 IDT 门描述符中的 3 位 IST 索引字段，使特定中断/异常可以**强制切换到预先分配好的独立栈**。

### 1.2 三者的存储与引用关系

| 存储对象 | 物理位置 | 作用 |
|---------|---------|------|
| IST 索引（0–7） | IDT 门描述符的 3-bit 字段 | 告诉 CPU「用 TSS 中第几号 IST 指针」 |
| 数据栈指针（RSP） | TSS 的 `ist[0..6]`（对应 IST1–IST7） | 异常压栈时切换到的**数据栈** |
| 影子栈指针（SSP） | 内存中的一张表，基址由 `IA32_INTERRUPT_SSP_TABLE` MSR 指向 | CET 影子栈切换（与 TSS 中的 RSP 独立） |

IDT 里**只有 3 个比特的索引**，存不下 64 位地址；真正的大指针数组在 TSS（数据栈）和 MSR 指向的内存表（影子栈）中。

### 1.3 Per-CPU 作用域

TSS 和 IST 都是 **Per-CPU** 的：

- 每个逻辑 CPU 有独立的 TR 寄存器和 TSS 内存
- 中断路由到某个 CPU 后，**只读取该 CPU 的 TSS**
- 两个核心不能共用同一个 IST 栈（并发 NMI 会互相踩踏）

IST 是 **Per-CPU 的系统保留栈**，不是 Per-Thread——无论当前跑哪个线程，致命异常都跳到当前核心的固定 IST 栈。

### 1.4 工作流程（简图）

```
异常/中断发生
    │
    ▼
查 IDT[vector] → 读取 IST 字段
    │
    ├─ IST = 0 → 使用修改后的 legacy 栈切换（RSP0 或当前栈）
    │
    └─ IST = N (1–7) → 读 TR → TSS.ist[N-1] → RSP = 该地址
                          │
                          ▼
                    向新栈压 SS/RSP/RFLAGS/CS/RIP（64 位模式无条件压 SS:RSP）
                          │
                          ▼
                    跳转到 IDT 中的处理程序
```

---

## 2. 硬件：64 位 TSS 结构

### 2.1 SDM Figure 7-11 布局

Intel SDM Vol 3A §7.7, Figure 7-11 定义的 64-bit TSS（共 **104 字节 / 0x68**）：

| 偏移 | 字段 | 大小 |
|------|------|------|
| 0–3 | Reserved | 4 B |
| 4–11 | RSP0 | 8 B |
| 12–19 | RSP1 | 8 B |
| 20–27 | RSP2 | 8 B |
| 28–35 | Reserved | 8 B |
| 36–43 | IST1 | 8 B |
| 44–51 | IST2 | 8 B |
| 52–59 | IST3 | 8 B |
| 60–67 | IST4 | 8 B |
| 68–75 | IST5 | 8 B |
| 76–83 | IST6 | 8 B |
| 84–91 | IST7 | 8 B |
| 92–99 | Reserved | 8 B |
| 100–101 | Reserved | 2 B |
| 102–103 | I/O Map Base Address | 2 B |

Reserved 位必须为零。

### 2.2 64 位 TSS 描述符

64 位模式下 TSS 描述符占 GDT 中 **两个连续的 8 字节条目**（共 16 字节），Type 为 `1001b`（Available 64-bit TSS）或 `1011b`（Busy）。详见 SDM Vol 3A §7.2.3。

### 2.3 SDM 与 Linux `struct x86_hw_tss` 的对应

```c
// arch/x86/include/asm/processor.h
struct x86_hw_tss {
    u32     reserved1;
    u64     sp0;
    u64     sp1;
    u64     sp2;          /* Linux 用作 syscall 临时保存用户 RSP */
    u64     reserved2;
    u64     ist[7];       /* IST1–IST7 */
    u32     reserved3;
    u32     reserved4;
    u16     reserved5;
    u16     io_bitmap_base;
} __attribute__((packed));
```

字段偏移与 SDM 完全一致。Linux 对 `sp2` 的复用见 [§14.2](#142-entry-trampoline-与-sp2)。

---

## 3. 硬件：IST 机制

### 3.1 SDM 官方描述（§6.14.5）

> "The IST mechanism is only available in IA-32e mode. It is part of the 64-bit mode TSS. The motivation for the IST mechanism is to provide a method for **specific interrupts (such as NMI, double-fault, and machine-check) to always execute on a known good stack**."

要点：

- 仅在 IA-32e（64 位）模式下可用
- Legacy 任务切换在 64 位模式下不可用，IST 是其替代
- IDT 门描述符中 3-bit IST 字段引用 TSS 中的 IST1–IST7
- **IST = 0** 时使用修改后的 legacy 栈切换机制

### 3.2 栈切换优先级（SDM §6.14.4）

CPU 决定新 RSP 的逻辑：

```
IF (IDT.IST != 0) {
    RSP = TSS.IST[IDT.IST - 1]    // 注意 1-based → 0-based 转换
} ELSE IF (CPL 改变) {
    RSP = TSS.RSP0
} ELSE {
    RSP = 当前 RSP               // 同特权级，不换栈
}
```

**IST 优先级高于 RSP0**，且**无论从哪个特权级触发都生效**——这是 IST 作为「最后防线」的关键。

64 位模式下 privilege-level 切换时 **不加载新的 SS 描述符**，SS 被强制为 NULL，RPL 设为新 CPL；旧的 SS:RSP 被压到新栈上。IRET 时恢复。

### 3.3 64 位中断栈帧（SDM §6.14.2）

与 32 位模式的重要区别：

| 行为 | 32 位 | 64 位 |
|------|-------|-------|
| SS:RSP 压栈 | 仅 CPL 改变时 | **无条件**压入 |
| 每项大小 | 16 或 32 bit | 固定 8 字节 |
| RSP 对齐 | — | 压栈前 16 字节对齐 |

栈帧布局（低地址 = 新 RSP）：

```
+0   Error Code（部分异常有）
+8   RIP
+16  CS
+24  RFLAGS
+32  RSP（旧）
+40  SS（旧）
```

CPU **不会**自动保存通用寄存器；Linux 在入口汇编中手动保存。

### 3.4 编号体系：三套索引的对照

这是最容易混淆的地方：

| 命名体系 | 范围 | 用途 |
|---------|------|------|
| SDM 硬件名 | IST1 – IST7 | 手册与 Figure 7-11 |
| TSS 数组 | `ist[0]` – `ist[6]` | Linux C 代码索引 |
| IDT 门描述符 | 0 – 7 | 0 = 不用 IST；1–7 对应 IST1–IST7 |

转换关系：

```
IDT.IST = N        →  TSS.ist[N - 1]     (N = 1..7)
Linux IST_INDEX_x  →  TSS.ist[IST_INDEX_x]
IDT.IST            =  IST_INDEX_x + 1     (ISTG 宏负责 +1)
```

---

## 4. 数据栈 IST 与影子栈 SSP

Intel CET（Control-flow Enforcement Technology）引入的影子栈与 TSS 中的 IST **是两套独立机制**：

| | 数据栈 (RSP) | 影子栈 (SSP) |
|---|-------------|-------------|
| 指针存放位置 | TSS 的 IST1–IST7 | 内存表，由 `IA32_INTERRUPT_SSP_TABLE` MSR 指向 |
| 作用 | 异常帧、局部变量、C 函数调用 | 控制流完整性（返回地址保护） |
| Linux 当前使用 | 全面使用（#DF/NMI/#DB/#MC/#VC） | 需 `CONFIG_X86_CET` |

SDM Figure 6-10 中的 `IA32_INTERRUPT_SSP_TABLE` 是 **MSR**，不是 IDT 或 TSS 的一部分。操作系统分配内存表、写入 MSR；每个 CPU 有独立的 MSR 实例。

---

## 5. Linux 数据结构总览

### 5.1 层次关系

```
Per-CPU
├── cpu_tss_rw (struct tss_struct)          ← TR 指向 x86_tss 部分
│   ├── x86_hw_tss                          ← 硬件可见的 104 字节
│   └── io_bitmap                           ← I/O 权限位图（软件扩展）
│
├── exception_stacks (struct exception_stacks)  ← IST 栈物理存储（无 guard page）
├── cea_exception_stacks *                  ← 指向 CEA 中带 guard page 的映射
│
├── entry_stack_storage                     ← Entry Trampoline Stack（RSP0 用）
└── cpu_entry_area *                        ← 上述结构的 fixmap 虚拟映射
```

### 5.2 关键结构体

**`struct tss_struct`**（`arch/x86/include/asm/processor.h`）：

```c
struct tss_struct {
    struct x86_hw_tss   x86_tss;    /* 必须不跨页边界 */
    struct x86_io_bitmap io_bitmap;
} __aligned(PAGE_SIZE);
```

**`struct cpu_entry_area`**（`arch/x86/include/asm/cpu_entry_area.h`）将 GDT、entry stack、TSS、异常栈等映射到 fixmap 区域 `CPU_ENTRY_AREA`：

```c
struct cpu_entry_area {
    char gdt[PAGE_SIZE];
    struct entry_stack_page entry_stack_page;
    struct tss_struct tss;
    struct cea_exception_stacks estacks;   /* IST 栈 + guard pages */
    /* ... debug store 等 ... */
};
```

**Per-CPU 声明**（`arch/x86/kernel/process.c`）：

```c
DEFINE_PER_CPU_PAGE_ALIGNED(struct tss_struct, cpu_tss_rw) = {
    .x86_tss = {
        .sp0 = (1UL << (BITS_PER_LONG-1)) + 1,  /* 毒值，cpu_init 中覆盖 */
        .io_bitmap_base = IO_BITMAP_OFFSET_INVALID,
    },
};
```

注意：`ist[]` **不在**静态初始化器中赋值，而是在 `tss_setup_ist()` 中运行时填充。

---

## 6. Linux 七个 IST 槽位：定义、分配与使用

这是本文的核心章节。硬件提供 7 个 IST 槽位，Linux **实际使用了 5 个**，其余 2 个保留未用。

### 6.1 完整对照表

| SDM | TSS 字段 | Linux 宏 | 值 | 异常/中断 | 向量 | IDT.IST | 栈变量名 | 启用条件 |
|-----|---------|---------|-----|----------|------|---------|---------|---------|
| IST1 | `ist[0]` | `IST_INDEX_DF` | 0 | Double Fault (#DF) | 8 | 1 | `DF_stack` | 始终 |
| IST2 | `ist[1]` | `IST_INDEX_NMI` | 1 | NMI | 2 | 2 | `NMI_stack` | 始终 |
| IST3 | `ist[2]` | `IST_INDEX_DB` | 2 | Debug (#DB) | 1 | 3 | `DB_stack` | 始终 |
| IST4 | `ist[3]` | `IST_INDEX_MCE` | 3 | Machine Check (#MC) | 18 | 4 | `MCE_stack` | `CONFIG_X86_MCE` |
| IST5 | `ist[4]` | `IST_INDEX_VC` | 4 | VMM Communication (#VC) | 29 | 5 | `VC_stack` | `CONFIG_AMD_MEM_ENCRYPT` + SEV-ES |
| IST6 | `ist[5]` | — | — | **未使用** | — | — | — | — |
| IST7 | `ist[6]` | — | — | **未使用** | — | — | — | — |

常量定义（`arch/x86/include/asm/page_64_types.h`）：

```c
#define IST_INDEX_DF    0
#define IST_INDEX_NMI   1
#define IST_INDEX_DB    2
#define IST_INDEX_MCE   3
#define IST_INDEX_VC    4
/* 无 IST_INDEX_5 / IST_INDEX_6 — ist[5] 和 ist[6] 保持 0 */
```

### 6.2 TSS 中写入 IST 指针

`arch/x86/kernel/cpu/common.c`：

```c
static inline void tss_setup_ist(struct tss_struct *tss)
{
    tss->x86_tss.ist[IST_INDEX_DF]  = __this_cpu_ist_top_va(DF);
    tss->x86_tss.ist[IST_INDEX_NMI] = __this_cpu_ist_top_va(NMI);
    tss->x86_tss.ist[IST_INDEX_DB]  = __this_cpu_ist_top_va(DB);
    tss->x86_tss.ist[IST_INDEX_MCE] = __this_cpu_ist_top_va(MCE);
    tss->x86_tss.ist[IST_INDEX_VC]  = __this_cpu_ist_top_va(VC);
}
```

宏 `__this_cpu_ist_top_va(name)` 展开为 CEA 中对应异常栈的**栈顶虚拟地址**（栈向下增长，顶 = 高地址）：

```c
// arch/x86/include/asm/cpu_entry_area.h
#define __this_cpu_ist_top_va(name) \
    CEA_ESTACK_TOP(__this_cpu_read(cea_exception_stacks), name)
```

### 6.3 IDT 中绑定 IST

`arch/x86/kernel/idt.c` 的 `def_idts[]`：

```c
static const __initconst struct idt_data def_idts[] = {
    INTG(X86_TRAP_DE,  asm_exc_divide_error),               /* IST=0 */
    ISTG(X86_TRAP_NMI, asm_exc_nmi, IST_INDEX_NMI),         /* IDT.IST=2 */
    /* ... 其他 IST=0 的异常 ... */
    ISTG(X86_TRAP_DF,  asm_exc_double_fault, IST_INDEX_DF), /* IDT.IST=1 */
    ISTG(X86_TRAP_DB,  asm_exc_debug, IST_INDEX_DB),        /* IDT.IST=3 */
#ifdef CONFIG_X86_MCE
    ISTG(X86_TRAP_MC,  asm_exc_machine_check, IST_INDEX_MCE),/* IDT.IST=4 */
#endif
#ifdef CONFIG_AMD_MEM_ENCRYPT
    ISTG(X86_TRAP_VC,  asm_exc_vmm_communication, IST_INDEX_VC), /* IDT.IST=5 */
#endif
    /* ... */
};
```

`ISTG` 宏的 +1 转换（`arch/x86/kernel/idt.c`）：

```c
/*
 * The _ist index is the index in the tss.ist[] array,
 * but for the descriptor it needs to start at 1.
 */
#define ISTG(_vector, _addr, _ist) \
    G(_vector, _addr, _ist + 1, GATE_INTERRUPT, DPL0, __KERNEL_CS)
```

**常见笔误**：`X86_TRAP_DF` 在 Linux 中**一定**使用 IST（`ISTG` 宏），不是 `IST=0`。若 #DF 不使用 IST，当前栈损坏时会直接 Triple Fault。

### 6.4 软件层面的额外栈（不占硬件 IST 槽位）

Linux 还维护了一些**不对应硬件 IST6/IST7** 的软件栈：

| 栈 | 位置 | 用途 | 与硬件 IST 的关系 |
|----|------|------|------------------|
| `VC2_stack` | CEA `estacks` | #VC 嵌套时的 fallback | 复用 `IST_INDEX_VC`，运行时修改 `ist[IST_INDEX_VC]` 指向 VC2 |
| `entry_stack` | CEA `entry_stack_page` | 普通中断/异常的 RSP0 跳板 | 写入 `TSS.sp0`，**不是 IST** |
| `hardirq_stack` | 独立 per-CPU 分配 | 设备中断处理 | 软件切换，不用 IST |

**#VC 的 IST 动态调整**（`arch/x86/coco/sev/noinstr.c`）：

处理嵌套 #VC 时，内核临时修改 `cpu_tss_rw.x86_tss.ist[IST_INDEX_VC]`，使其指向 `VC2_stack` 顶部；处理完毕后恢复。这是**软件复用 IST5 槽位**，而非使用 IST6。

`VC2_stack` 在 `cpu_entry_area.c` 中仅当 SEV-ES guest 活跃时才映射：

```c
if (IS_ENABLED(CONFIG_AMD_MEM_ENCRYPT)) {
    if (cc_platform_has(CC_ATTR_GUEST_STATE_ENCRYPT)) {
        cea_map_stack(VC);
        cea_map_stack(VC2);
    }
}
```

### 6.5 各 IST 异常的设计理由

| IST | 为什么需要独立栈 |
|-----|----------------|
| **#DF** | 通常意味着当前栈已损坏（栈溢出导致 #PF 嵌套）；必须在已知良好的栈上才能压入异常帧并 panic |
| **NMI** | 不可屏蔽，可在任意时刻打断（包括正在修改栈的指令中间）；需要与被打断的栈隔离 |
| **#DB** | 调试器自身可能触发 #DB；单步执行调试器代码时不能覆盖被调试任务的栈帧 |
| **#MC** | 硬件错误，当前栈所在内存可能已损坏 |
| **#VC** | SEV-ES 虚拟化通信异常，需要支持嵌套且能在加密 guest 中安全执行 |

### 6.6 不使用 IST 的异常

大多数异常（#DE、#PF、#GP、#UD 等）的 IDT 条目中 **IST=0**。这些异常发生时栈通常完好；若栈已损坏，会级联为 #DF，由 IST1 接管。

#PF 不使用 IST 的原因：Linux 在线程栈底设置了 **Guard Page**，栈溢出先触发 #PF，#PF 处理程序在进程内核栈上检测到溢出并安全终止进程。只有 Guard Page 被跳过的极端情况才会 #DF。

### 6.7 FRED 模式下的变化

当 CPU 支持 FRED（Flexible Return and Event Delivery）时，IST 通过 IDT 的路径被替换为 **FRED event delivery**，RSP 由 FRED MSR 指定（`arch/x86/kernel/fred.c`）：

```c
wrmsrq(MSR_IA32_FRED_RSP1, __this_cpu_ist_top_va(DB));
wrmsrq(MSR_IA32_FRED_RSP2, __this_cpu_ist_top_va(NMI));
wrmsrq(MSR_IA32_FRED_RSP3, __this_cpu_ist_top_va(DF));
```

`cpu_init_exception_handling()` 在 FRED 模式下跳过 `tss_setup_ist()` 和 `idt_setup_traps()`，改走 `cpu_init_fred_exceptions()`。

---

## 7. Linux IST 栈内存布局与分配

### 7.1 异常栈在内存中的排列

`arch/x86/include/asm/cpu_entry_area.h` 用宏定义栈的物理排列顺序：

```c
enum exception_stack_ordering {
    ESTACK_DF,
    ESTACK_NMI,
    ESTACK_DB,
    ESTACK_MCE,
    ESTACK_VC,
    ESTACK_VC2,
    N_EXCEPTION_STACKS    /* = 6 */
};

struct exception_stacks {
    ESTACKS_MEMBERS(0, VC_EXCEPTION_STKSZ)
    /* 展开为 DF_stack, NMI_stack, DB_stack, MCE_stack, VC_stack, VC2_stack */
};

struct cea_exception_stacks {
    ESTACKS_MEMBERS(PAGE_SIZE, EXCEPTION_STKSZ)
    /* 每个栈前面加一个 PAGE_SIZE 的 guard page */
};
```

每个 CPU 有 **6 个软件异常栈**（对应 5 个硬件 IST + 1 个 VC2 fallback），但硬件 IST 槽位只有 5 个被赋值。

### 7.2 栈大小

```c
// arch/x86/include/asm/page_64_types.h
#define EXCEPTION_STACK_ORDER (1 + KASAN_STACK_ORDER)
#define EXCEPTION_STKSZ (PAGE_SIZE << EXCEPTION_STACK_ORDER)
```

| 配置 | 每栈大小 | 页数 |
|------|---------|------|
| 无 KASAN | 8 KB | 2 页 |
| 有 KASAN | 16 KB | 4 页 |

**所有 IST 栈（包括 #DF）大小相同**，不存在单独的 `DOUBLEFAULT_STACK_ORDER`。

### 7.3 分配与映射流程

`arch/x86/mm/cpu_entry_area.c`：

```c
static DEFINE_PER_CPU_PAGE_ALIGNED(struct exception_stacks, exception_stacks);

static void __init percpu_setup_exception_stacks(unsigned int cpu)
{
    struct exception_stacks *estacks = per_cpu_ptr(&exception_stacks, cpu);
    struct cpu_entry_area *cea = get_cpu_entry_area(cpu);

    per_cpu(cea_exception_stacks, cpu) = &cea->estacks;

    cea_map_stack(DF);
    cea_map_stack(NMI);
    cea_map_stack(DB);
    cea_map_stack(MCE);
    /* VC / VC2 条件映射，见 §6.4 */
}
```

物理页存储在 `exception_stacks`（per-CPU 数组），通过 fixmap 映射到 CEA 中带 guard page 的 `cea_exception_stacks`。TSS 中的 IST 指针指向 CEA 映射的**栈顶**。

### 7.4 内存布局示意

```
CPU N 的 CEA 异常栈区域（高地址在上）:

  ┌─────────────────────┐ ← IST1 (DF)  栈顶 = ist[IST_INDEX_DF]
  │     DF_stack        │
  ├─ guard page ────────┤
  │     NMI_stack       │ ← IST2
  ├─ guard page ────────┤
  │     DB_stack        │ ← IST3
  ├─ guard page ────────┤
  │     MCE_stack       │ ← IST4
  ├─ guard page ────────┤
  │     VC_stack        │ ← IST5
  ├─ guard page ────────┤
  │     VC2_stack       │ ← 软件 fallback（非独立硬件 IST 槽）
  └─ IST_top_guard ─────┘
```

---

## 8. Linux 初始化时序

### 8.1 正确的启动顺序

实际代码路径（`arch/x86/kernel/traps.c` 的 `trap_init()`）：

```
trap_init()
  ├─ setup_cpu_entry_areas()          // 分配并映射 CEA、异常栈、TSS
  ├─ sev_es_init_vc_handling()
  ├─ cpu_init_exception_handling(true)
  │    ├─ setup_getcpu()
  │    ├─ tss_setup_ist()              // 填充 TSS.ist[]
  │    ├─ tss_setup_io_bitmap()
  │    ├─ set_tss_desc() + load_TR_desc()  // ltr
  │    └─ load_current_idt()           // 加载 idt_table
  ├─ idt_setup_traps()                 // 写入 def_idts（含 IST 条目）
  └─ cpu_init()                        // load_sp0(entry_stack) 等
```

**关键约束**：`idt_setup_traps()`（写入 IST 条目）必须在 `cpu_init_exception_handling()`（设置 TSS + ltr）**之后**调用。在此之前 IDT 中的 IST 字段必须全为 0。

### 8.2 启动阶段 IDT 状态

| 阶段 | IDT 表 | IST 字段 | TSS/TR 状态 |
|------|--------|---------|------------|
| `startup_64_setup_gdt_idt` | `bringup_idt_table` | 全 0 | TR 未设置 |
| `idt_setup_early_handler` | 早期 handler 数组 | 全 0 | TR 未设置 |
| `idt_setup_early_traps` | `idt_table` + `early_idts` | 全 0 | TR 未设置 |
| `trap_init` → `cpu_init_exception_handling` | — | — | TSS 初始化 + ltr |
| `trap_init` → `idt_setup_traps` | `idt_table` + `def_idts` | #DF/NMI/#DB/#MC/#VC 非 0 | TR 已就绪 |

Secondary CPU 在 `start_secondary()` → `cpu_init_exception_handling(false)` 中走相同路径（`arch/x86/kernel/smpboot.c`）。

### 8.3 TR 加载

```c
// arch/x86/include/asm/desc.h
#define set_tss_desc(cpu, addr) __set_tss_desc(cpu, GDT_ENTRY_TSS, addr)

static inline void native_load_tr_desc(void)
{
    load_tr((GDT_ENTRY_TSS * 8));   // ltr 指令
}
```

TSS 描述符写入 Boot CPU 的 GDT（`GDT_ENTRY_TSS`），每个 CPU 在 `setup_cpu_entry_area()` 中映射自己的 TSS 页。

---

## 9. Linux 异常入口路径

IST 异常进入内核后，Linux 根据**来源特权级**走不同路径。核心原则（来自 `entry_64.S` 注释）：

- **用户态触发**：切换到进程内核栈（`sync_regs`），释放 IST 栈
- **内核态触发**：留在 IST 栈上，走 `paranoid_entry` / `paranoid_exit`

### 9.1 #DF — 始终 paranoid

```asm
// arch/x86/entry/entry_64.S — idtentry_df 宏
call    paranoid_entry
movq    %rsp, %rdi
call    exc_double_fault
jmp     paranoid_exit
```

#DF **不区分**用户/内核来源，始终在 IST 栈上处理（因为触发 #DF 的前提就是栈可能已损坏）。

### 9.2 #DB / #MC — 双路径

```asm
// idtentry_mce_db 宏
testb   $3, CS-ORIG_RAX(%rsp)
jnz     .Lfrom_usermode_switch_stack    // 用户态 → noist_exc_* → sync_regs
call    paranoid_entry                    // 内核态 → 留在 IST 栈
call    exc_debug / exc_machine_check
jmp     paranoid_exit
```

### 9.3 NMI — 特殊处理

NMI 入口（`asm_exc_nmi`）逻辑最复杂：

- **用户态 NMI**：`swapgs` → 切 CR3 → 复制帧到 `cpu_current_top_of_stack`（进程内核栈），类似 `sync_regs`
- **内核态 NMI**：留在 IST 栈，有嵌套 NMI 检测（`nmi_executing` 变量 + `repeat_nmi` 机制）
- NMI 处理期间**不开启 IRQ**（NMI 本身不可屏蔽）

### 9.4 #VC — IST 切换与 fallback

#VC 在 IST 栈上进入后，内核态路径会调用 `vc_switch_off_ist()` 切回被打断的栈（若安全）或 `VC2_stack`（fallback），以释放 IST 栈供嵌套 #VC 使用。详见 `entry_64.S` 的 `idtentry_vc` 宏和 `arch/x86/coco/sev/noinstr.c`。

### 9.5 paranoid_entry 做什么

`paranoid_entry`（`entry_64.S`）在 IST 栈上执行，处理：

1. 保存通用寄存器（`PUSH_AND_CLEAR_REGS`）
2. 切换到内核 CR3（PTI 场景）
3. 处理 GSBASE / SWAPGS（FSGSBASE 或 legacy 负地址约定）
4. 设置 SPEC_CTRL（IBRS 等缓解措施）

**IST 栈切换由硬件在入口汇编之前完成**；`paranoid_entry` 是软件层面的「内核态安全网」，与 Entry Trampoline Stack（RSP0）是**独立且不交集**的两套机制。

### 9.6 路径总览

```
                    硬件 IST 切换（RSP → IST 栈）
                              │
              ┌───────────────┼───────────────┐
              │               │               │
           用户态来源       内核态来源       #DF（任意来源）
              │               │               │
         sync_regs /      paranoid_entry    paranoid_entry
         切进程内核栈      留在 IST 栈        留在 IST 栈
              │               │               │
         exc_* (C)         exc_* (C)         exc_* (C)
              │               │               │
         iret 返回          paranoid_exit     panic
```

---

## 10. IST 与 IDT 的集成

### 10.1 64 位 IDT 门描述符

16 字节，IST 字段位于 byte 4 的低 3 位（SDM Figure 6-7）。Linux 结构（`arch/x86/include/asm/desc_defs.h`）：

```c
struct idt_bits {
    u16 ist  : 3,
        zero : 5,
        type : 5,
        dpl  : 2,
        p    : 1;
} __attribute__((packed));
```

64 位模式下**不支持任务门**（访问任务门触发 #GP），IST 是获得独立栈的唯一硬件机制。

### 10.2 IST 值转换示例

| 异常 | IST_INDEX | IDT.IST (ISTG+1) | TSS 字段 |
|------|-----------|-------------------|---------|
| #DF | 0 | 1 | ist[0] |
| NMI | 1 | 2 | ist[1] |
| #DB | 2 | 3 | ist[2] |
| #MC | 3 | 4 | ist[3] |
| #VC | 4 | 5 | ist[4] |

---

## 11. 为什么需要 IST

### 11.1 核心问题

没有 IST 时，所有异常（包括 #DF、NMI）都在**当前栈**上压入异常帧。若当前栈已损坏：

```
#PF（栈溢出）→ 压栈失败 → #DF → 仍在损坏的栈上压栈 → Triple Fault → CPU 复位
```

系统重启且无任何日志。

### 11.2 有 IST 时

```
#PF（栈溢出）→ 压栈失败 → #DF
    → CPU 查 IDT: IST=1 → 切换到 IST1（干净的 DF_stack）
    → 成功压栈 → exc_double_fault() → panic + oops 日志
```

### 11.3 同特权级不查 RSP0 的含义

内核态触发 IST=0 的异常（如 #PF）时，CPU **不会**读取 TSS.RSP0，而是继续使用当前 RSP。这意味着：

- 即使 TSS.RSP0 指向完全有效的栈，CPU 也不会用它
- 若 RSP 已被 bug 损坏，普通异常无法恢复
- **IST 的价值正在于此**：对 #DF/NMI/#MC/#DB，无论当前特权级，都强制换栈

---

## 12. 启动早期约束

若在 TSS 初始化（`ltr`）之前加载带 IST≠0 的 IDT，触发 #DF 时：

1. CPU 读 IDT → IST=1
2. 读 TR → TSS 未初始化或 IST 指针为 0
3. RSP = 0 → 压栈 #PF → Triple Fault → 重启

Linux 的防护：

- `bringup_idt_table` / `early_idts` / `def_idts` 在 `trap_init()` 之前**不安装**
- `idt_setup_early_traps()` 只装 IST=0 的条目
- `def_idts` 中的 IST 条目在 `cpu_init_exception_handling()` 完成 TSS 设置**之后**才通过 `idt_setup_traps()` 写入

详见 [LINUX_KERNEL_IDT_EVOLUTION.md](LINUX_KERNEL_IDT_EVOLUTION.md)。

---

## 13. 调试与验证

### 13.1 GDB 查看 TSS

```gdb
(gdb) info registers tr
(gdb) x/26xg <TSS 基址>
# +0x24: ist[0] (DF)
# +0x2c: ist[1] (NMI)
# +0x34: ist[2] (DB)
# +0x3c: ist[3] (MCE)
# +0x44: ist[4] (VC)
# +0x4c: ist[5] (应为 0)
# +0x54: ist[6] (应为 0)
```

### 13.2 查看 IDT 的 IST 字段

```gdb
(gdb) x/2xg idt_table + 8*16    # #DF, vector 8
# byte 5 的低 3 位 = IST 值（#DF 应为 1）
```

### 13.3 栈回溯识别 IST 栈

`arch/x86/kernel/dumpstack_64.c` 通过 `in_exception_stack()` 判断地址是否在 CEA 异常栈范围内，并在 oops 输出中标注栈类型（`#DF`、`NMI`、`#DB`、`#MC`、`#VC`、`#VC2`）。

---

## 14. 附录：TSS 角色演变与 Entry Trampoline

### 14.1 TSS 角色演变（简表）

| 时代 | TSS 数量 | 用途 |
|------|---------|------|
| x86-32 硬件任务切换 | 每进程一个 | CPU 自动保存/恢复全部寄存器 |
| Linux ≥ 2.4 | 每 CPU 一个 | 仅 RSP0 + IST + I/O bitmap |
| x86-64 Linux | 每 CPU 一个 | RSP0 → entry trampoline；IST → 异常专用栈 |

### 14.2 Entry Trampoline 与 sp2

64 位 Linux 中 **TSS.sp0 指向 entry trampoline stack**（固定 per-CPU 页），不是进程内核栈：

```c
// arch/x86/kernel/cpu/common.c — cpu_init()
load_sp0((unsigned long)(cpu_entry_stack(cpu) + 1));
```

普通中断/异常流程：CPU 硬件压栈到 trampoline → `sync_regs()` 复制帧到进程内核栈（`cpu_current_top_of_stack`）。

`syscall` 不经过 IDT，直接从 `cpu_current_top_of_stack` 获取内核栈；用户 RSP 临时存入 `TSS.sp2`：

```asm
// arch/x86/entry/entry_64.S — entry_SYSCALL_64
movq    %rsp, PER_CPU_VAR(cpu_tss_rw + TSS_sp2)
movq    PER_CPU_VAR(cpu_current_top_of_stack), %rsp
```

**Entry Trampoline 与 IST 完全独立**：前者服务于 IST=0 的普通异常路径；后者由硬件在异常入口前直接切换 RSP。

### 14.3 上下文切换时更新什么

进程切换（`__switch_to`）更新 `cpu_current_top_of_stack`，**不更新** TSS.sp0（标准 64 位配置）也不更新 IST 指针。IST 栈地址在 `trap_init()` 时设定后不变（#VC 嵌套时临时修改 `ist[IST_INDEX_VC]` 除外）。

---

## 15. 参考文献

### 15.1 Intel/AMD 手册

1. **Intel SDM Vol 3A**
   - §6.14.1: 64-Bit Mode IDT
   - §6.14.2: 64-Bit Mode Stack Frame
   - §6.14.4: Stack Switching in IA-32e Mode
   - §6.14.5: Interrupt Stack Table
   - §7.7: Task Management in 64-bit Mode (Figure 7-11)
   - §7.2.3: TSS Descriptor in 64-bit mode

2. **AMD64 Architecture Programmer's Manual, Volume 2** — §8.9 Long Mode Interrupt Stack

### 15.2 Linux 内核源码（IST 相关）

| 文件 | 内容 |
|------|------|
| `arch/x86/include/asm/page_64_types.h` | `IST_INDEX_*` 常量、`EXCEPTION_STKSZ` |
| `arch/x86/include/asm/processor.h` | `struct x86_hw_tss`、`struct tss_struct` |
| `arch/x86/include/asm/cpu_entry_area.h` | 异常栈布局、`__this_cpu_ist_top_va` |
| `arch/x86/mm/cpu_entry_area.c` | IST 栈分配与 CEA 映射 |
| `arch/x86/kernel/cpu/common.c` | `tss_setup_ist()`、`cpu_init_exception_handling()` |
| `arch/x86/kernel/idt.c` | `def_idts[]`、`ISTG` 宏 |
| `arch/x86/kernel/traps.c` | `trap_init()` |
| `arch/x86/entry/entry_64.S` | `paranoid_entry`、`idtentry_mce_db`、`idtentry_df`、`asm_exc_nmi` |
| `arch/x86/include/asm/idtentry.h` | `DEFINE_IDTENTRY_DF`、`DECLARE_IDTENTRY_IST` |
| `arch/x86/coco/sev/noinstr.c` | #VC IST 动态切换 |
| `arch/x86/kernel/dumpstack_64.c` | IST 栈回溯识别 |

### 15.3 相关文档

- [LINUX_KERNEL_IDT_EVOLUTION.md](LINUX_KERNEL_IDT_EVOLUTION.md) — 两阶段 IDT 设计
- [LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md) — 启动流程中 TSS 初始化时机
- [KASAN_INSTRUMENTATION_AND_INIT_ORDER.md](KASAN_INSTRUMENTATION_AND_INIT_ORDER.md) — 与 IST 独立的另一初始化约束

---

**文档结束**
