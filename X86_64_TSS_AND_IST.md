# x86-64 任务状态段（TSS）与中断栈表（IST）详解

**版本**: 1.0
**日期**: 2026-02-17
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

---

## 3. x86-64 中的 TSS 结构

### 3.1 硬件定义的 TSS 结构

**Intel SDM Vol 3A, Section 7.7**：

```
+0    Reserved
+4    RSP0 (Low 32 bits)       ┐
+8    RSP0 (High 32 bits)      ├─ Ring 0 栈指针（64 位）
+12   RSP1 (Low 32 bits)       │
+16   RSP1 (High 32 bits)      │
+20   RSP2 (Low 32 bits)       │
+24   RSP2 (High 32 bits)      │
+28   Reserved                 │
+32   Reserved                 │
+36   IST1 (Low 32 bits)       ┐
+40   IST1 (High 32 bits)      ├─ IST 栈 1（64 位）
+44   IST2 (Low 32 bits)       │
+48   IST2 (High 32 bits)      │
+52   IST3 (Low 32 bits)       │
+56   IST3 (High 32 bits)      │
+60   IST4 (Low 32 bits)       │
+64   IST4 (High 32 bits)      │
+68   IST5 (Low 32 bits)       │
+72   IST5 (High 32 bits)      │
+76   IST6 (Low 32 bits)       │
+80   IST6 (High 32 bits)      │
+84   IST7 (Low 32 bits)       │
+88   IST7 (High 32 bits)      ┘
+92   Reserved
+96   Reserved
+100  I/O Map Base Address (16 bits)
+102  [I/O Permission Bitmap]
```

**最小 TSS 大小**：104 字节（0x68）

### 3.2 Linux 内核的 TSS 结构

**文件**：`arch/x86/include/asm/processor.h`

```c
struct x86_hw_tss {
    u32                     reserved1;
    u64                     sp0;            // RSP0: Ring 0 栈（系统调用、中断）
    u64                     sp1;            // RSP1: Ring 1（未使用）
    u64                     sp2;            // RSP2: Ring 2（未使用）
    u64                     reserved2;
    u64                     ist[7];         // IST1 到 IST7
    u32                     reserved3;
    u32                     reserved4;
    u16                     reserved5;
    u16                     io_map_base;    // I/O 位图偏移
} __attribute__((packed));

/*
 * 完整的 per-CPU TSS 结构
 */
struct tss_struct {
    /*
     * TSS 的硬件部分（CPU 可见）
     */
    struct x86_hw_tss       x86_tss;

    /*
     * 软件部分（CPU 不可见，只是为了内存布局）
     */
    unsigned long           SYSENTER_stack_canary;
    unsigned long           SYSENTER_stack;

    /*
     * I/O 权限位图（紧跟在 TSS 之后）
     * 大小：8192 字节（覆盖 65536 个端口）
     */
    unsigned long           io_bitmap[IO_BITMAP_LONGS + 1];
} ____cacheline_aligned;
```

**关键字段说明**：

| 字段 | 偏移 | 大小 | 用途 |
|------|------|------|------|
| `reserved1` | +0 | 4 字节 | 保留（对应 x86-32 的 prev_task） |
| `sp0` | +4 | 8 字节 | **Ring 0 栈**：用户态→内核态时切换到此栈 |
| `sp1` | +12 | 8 字节 | Ring 1 栈（未使用，x86-64 只用 Ring 0/3） |
| `sp2` | +20 | 8 字节 | Ring 2 栈（未使用） |
| `ist[0..6]` | +36 | 56 字节 | **7 个 IST 栈**：为关键异常提供独立栈 |
| `io_map_base` | +100 | 2 字节 | I/O 位图在 TSS 中的偏移 |

### 3.3 Per-CPU 的 TSS

Linux 为**每个 CPU 核心**维护一个独立的 TSS：

```c
// arch/x86/kernel/process.c
DEFINE_PER_CPU_PAGE_ALIGNED(struct tss_struct, cpu_tss_rw) = {
    .x86_tss = {
        /*
         * sp0 会在每次任务切换时更新为新任务的内核栈
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

---

## 4. IST 机制详解

### 4.1 IST 的核心思想

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

### 4.2 IST 切换的硬件行为

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

### 4.3 IST 栈的布局

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

---

## 6. IST 与 IDT 的集成

### 6.1 IDT 门描述符中的 IST 字段

**x86-64 中断门描述符格式**（16 字节）：

```
+0    Offset 15:0          (处理程序地址低 16 位)
+2    Segment Selector     (代码段选择子)
+4    IST[2:0] | Reserved  (IST 索引: 0-7)
      ^^^^^^^^^^^
      这 3 位指定使用哪个 IST 栈
      0 = 不使用 IST
      1 = 使用 TSS.IST[0]
      2 = 使用 TSS.IST[1]
      ...
      7 = 使用 TSS.IST[6]

+5    Type, DPL, P         (类型、特权级、存在位)
+6    Offset 31:16         (处理程序地址中 16 位)
+8    Offset 63:32         (处理程序地址高 32 位)
+12   Reserved
```

### 6.2 Linux 内核的 IST 索引定义

**文件**：`arch/x86/include/asm/cpu_entry_area.h`

```c
enum exception_stack_ordering {
    ESTACK_DF,     // Double Fault
    ESTACK_NMI,    // Non-Maskable Interrupt
    ESTACK_DB,     // Debug
    ESTACK_MCE,    // Machine Check
    ESTACK_VC,     // Virtualization Exception (SEV-SNP)
    ESTACK_CEA,    // CPU Entry Area
    N_EXCEPTION_STACKS
};

// IST 索引（从 1 开始，0 表示不使用 IST）
#define IST_INDEX_DF    (ESTACK_DF + 1)     // = 1
#define IST_INDEX_NMI   (ESTACK_NMI + 1)    // = 2
#define IST_INDEX_DB    (ESTACK_DB + 1)     // = 3
#define IST_INDEX_MCE   (ESTACK_MCE + 1)    // = 4
#define IST_INDEX_VC    (ESTACK_VC + 1)     // = 5
#define IST_INDEX_CEA   (ESTACK_CEA + 1)    // = 6
```

### 6.3 设置带 IST 的 IDT 表项

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

**实际使用示例**：

```c
// arch/x86/kernel/idt.c
static const __initconst struct idt_data def_idts[] = {
    // 向量 8: Double Fault，使用 IST 1
    ISTG(X86_TRAP_DF,  exc_double_fault,  IST_INDEX_DF),

    // 向量 2: NMI，使用 IST 2
    ISTG(X86_TRAP_NMI, exc_nmi,           IST_INDEX_NMI),

    // 向量 1: Debug，使用 IST 3
    ISTG(X86_TRAP_DB,  exc_debug,         IST_INDEX_DB),

    // 向量 18: Machine Check，使用 IST 4
    ISTG(X86_TRAP_MC,  exc_machine_check, IST_INDEX_MCE),
};
```

**门描述符的实际编码**：

```c
// 示例：Double Fault 的门描述符
gate_desc idt_table[256];

// idt_table[8] (Double Fault):
// offset  = &exc_double_fault
// segment = __KERNEL_CS (0x10)
// ist     = 1 (IST_INDEX_DF)
// type    = 0xE (Interrupt Gate)
// dpl     = 0
// p       = 1

// 编码为：
idt_table[8].offset_low    = (u16)(addr & 0xFFFF);
idt_table[8].segment       = 0x10;
idt_table[8].ist           = 1;           // ← IST 字段
idt_table[8].type_attr     = 0x8E;        // P=1, DPL=0, Type=E
idt_table[8].offset_middle = (u16)((addr >> 16) & 0xFFFF);
idt_table[8].offset_high   = (u32)(addr >> 32);
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

## 11. 总结

### 11.1 核心要点

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

### 11.2 与其他文档的关联

- **[LINUX_KERNEL_IDT_EVOLUTION.md](LINUX_KERNEL_IDT_EVOLUTION.md)**：解释为什么需要两个 IDT 表，其中 TSS/IST 依赖是关键原因之一
- **[LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md)**：详细的启动流程，展示 TSS 初始化的时机
- **[KASAN_INSTRUMENTATION_AND_INIT_ORDER.md](KASAN_INSTRUMENTATION_AND_INIT_ORDER.md)**：解释另一个独立约束（KASAN），与 TSS/IST 约束共同决定了 IDT 的设计

### 11.3 实践建议

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

## 12. 参考文献

### 12.1 Intel/AMD 文档

1. **Intel® 64 and IA-32 Architectures Software Developer's Manual, Volume 3A**
   - Chapter 7: Task Management
   - Section 7.7: Task Management in 64-bit Mode

2. **Intel® 64 and IA-32 Architectures Software Developer's Manual, Volume 3A**
   - Chapter 6: Interrupt and Exception Handling
   - Section 6.14.5: Interrupt Stack Table

3. **AMD64 Architecture Programmer's Manual, Volume 2**
   - Chapter 8: Exceptions and Interrupts
   - Section 8.9: Long Mode Interrupt Stack

### 12.2 Linux 内核源代码

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

### 12.3 相关文档

9. [LINUX_KERNEL_IDT_EVOLUTION.md](LINUX_KERNEL_IDT_EVOLUTION.md)
   - IDT 表的演进流程
   - 为什么需要两个独立的 IDT 表

10. [LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md)
    - Linux 内核启动与初始化
    - TSS 初始化的时机

11. [KASAN_INSTRUMENTATION_AND_INIT_ORDER.md](KASAN_INSTRUMENTATION_AND_INIT_ORDER.md)
    - KASAN 插桩机制
    - 与 IST/TSS 独立的另一个初始化约束

---

**文档结束**
