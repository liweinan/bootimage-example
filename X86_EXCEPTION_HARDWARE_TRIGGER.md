# x86 异常的硬件触发机制：Page Fault 与 Breakpoint 深入剖析

> **本文档为** [x86 中断、异常、陷阱：Intel SDM 规范与 Linux 实现](X86_INTERRUPT_EXCEPTION_TRAP.md) **的补充文档**

本文档通过 Page Fault (#PF) 和 Breakpoint (#BP) 两个典型异常，深入剖析 x86 CPU 的硬件异常触发机制，解答以下核心问题：

1. **异常处理是否需要软件主动调用？**
2. **向量号是 CPU 硬件固定的还是软件编码实现的？**
3. **内核如何实现断点服务？如何触发？**

**参考资料**：
- **Intel® 64 and IA-32 Architectures Software Developer's Manual, Volume 3A, Chapter 6**
  - `/Users/weli/Desktop/64-ia-32-architectures-software-developer-vol-3a-part-1-manual.pdf`
- **Linux Kernel Source Code** (v6.x)
  - `/Users/weli/works/linux/arch/x86/include/asm/trapnr.h`
  - `/Users/weli/works/linux/arch/x86/kernel/idt.c`
  - `/Users/weli/works/linux/arch/x86/kernel/traps.c`
  - `/Users/weli/works/linux/arch/x86/mm/fault.c`

---

## 目录

- [一、核心结论](#一核心结论)
- [二、CPU 硬件异常触发机制](#二cpu-硬件异常触发机制)
- [三、案例 1：Page Fault 的完整流程](#三案例-1page-fault-的完整流程)
- [四、案例 2：Breakpoint 的实现与触发](#四案例-2breakpoint-的实现与触发)
- [五、向量号的硬件规范](#五向量号的硬件规范)
- [六、软件的职责边界](#六软件的职责边界)
- [七、常见问题](#七常见问题)
- [八、实验验证](#八实验验证)

---

## 一、核心结论

### 1.1 三个关键问题的答案

| 问题 | 答案 | 说明 |
|------|------|------|
| **异常处理是否需要软件主动调用？** | ❌ **不需要** | CPU 硬件自动检测异常并通过 IDT 跳转到处理函数 |
| **向量号是软件编码实现的吗？** | ❌ **不是** | 向量号由 **Intel SDM 规范**定义，CPU 硬件电路实现 |
| **软件能改变异常向量号吗？** | ❌ **不能** | 向量 0-31 由 Intel 保留，所有 x86 CPU 必须遵守 |

### 1.2 硬件 vs 软件的职责划分

```
┌─────────────────────────────────────────────────────────────┐
│                    CPU 硬件（不可改变）                        │
├─────────────────────────────────────────────────────────────┤
│ 1. 检测异常条件（如访问无效页面）                              │
│ 2. 确定异常向量号（#PF = 14）                                │
│ 3. 保存现场（RIP、RFLAGS、CS、SS、RSP、错误码）                │
│ 4. 查找 IDT[vector] 获取处理函数地址                          │
│ 5. 切换特权级（如果需要）                                      │
│ 6. 跳转到处理函数                                             │
└─────────────────────────────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────┐
│                    软件（可配置部分）                          │
├─────────────────────────────────────────────────────────────┤
│ 1. 构建 IDT 表（256 个门描述符）                               │
│ 2. 在 IDT[14] 填入 Page Fault 处理函数地址                     │
│ 3. 实现处理函数（如 do_page_fault）                           │
│ 4. 修复问题（如分配页面）                                      │
│ 5. 返回（IRET 指令）                                          │
└─────────────────────────────────────────────────────────────┘
```

**关键洞察**：
- CPU 硬件负责**检测**和**分发**异常（向量号硬编码）
- 软件只负责**注册处理函数**和**实现处理逻辑**
- 软件**无法改变** CPU 使用的向量号，只能在对应位置填入处理函数

---

## 二、CPU 硬件异常触发机制

### 2.1 Intel SDM 规定的异常向量

根据 **Intel SDM Volume 3A, Section 6.3.1: Protected-Mode Exceptions and Interrupts**，CPU 硬件保留了向量 0-31 用于异常：

| 向量 | 助记符 | 异常名称 | 类型 | 错误码 | 说明 |
|------|--------|---------|------|--------|------|
| 0 | #DE | Divide Error | Fault | No | 除零或除法溢出 |
| 1 | #DB | Debug | Fault/Trap | No | 调试异常 |
| 2 | - | NMI | Interrupt | No | 不可屏蔽中断 |
| **3** | **#BP** | **Breakpoint** | **Trap** | **No** | **INT 3 指令** |
| 4 | #OF | Overflow | Trap | No | INTO 指令检测到溢出 |
| 5 | #BR | Bound Range Exceeded | Fault | No | BOUND 指令范围检查 |
| 6 | #UD | Invalid Opcode | Fault | No | 无效指令 |
| 7 | #NM | Device Not Available | Fault | No | FPU 不可用 |
| 8 | #DF | Double Fault | Abort | Yes (0) | 处理异常时又发生异常 |
| 9 | - | Coprocessor Segment Overrun | Fault | No | (已废弃) |
| 10 | #TS | Invalid TSS | Fault | Yes | TSS 无效 |
| 11 | #NP | Segment Not Present | Fault | Yes | 段不存在 |
| 12 | #SS | Stack-Segment Fault | Fault | Yes | 栈段错误 |
| 13 | #GP | General Protection | Fault | Yes | 通用保护错误 |
| **14** | **#PF** | **Page Fault** | **Fault** | **Yes** | **页面错误** |
| 15 | - | (Reserved) | - | - | Intel 保留 |
| 16 | #MF | x87 FPU Error | Fault | No | 浮点错误 |
| 17 | #AC | Alignment Check | Fault | Yes (0) | 对齐检查 |
| 18 | #MC | Machine Check | Abort | No | 硬件错误 |
| 19 | #XM/#XF | SIMD FPU Exception | Fault | No | SIMD 浮点错误 |
| 20 | #VE | Virtualization Exception | Fault | No | 虚拟化异常 |
| 21 | #CP | Control Protection | Fault | Yes | CET 控制流保护 |
| 22-28 | - | (Reserved) | - | - | Intel 保留 |
| 29 | #VC | VMM Communication | Fault | Yes | AMD SEV-SNP 通信 |
| 30-31 | - | (Reserved) | - | - | Intel 保留 |

> **来源**：Intel SDM Volume 3A, Table 6-1: Protected-Mode Exceptions and Interrupts

### 2.2 CPU 硬件异常处理流程

当 CPU 检测到异常时，**硬件电路自动执行**以下步骤（Intel SDM Volume 3A, Section 6.12）：

```
步骤 1: 检测异常条件
    └─ CPU 执行指令时检测到预定义的错误条件
       例如：访问页面时发现页表项 Present 位 = 0

步骤 2: 确定异常向量号
    └─ CPU 硬件逻辑根据异常类型确定向量号
       例如：Page Fault → vector = 14 (硬编码在 CPU 微码中)

步骤 3: 检查 IDT 限制
    └─ 读取 IDTR 寄存器（包含 IDT 基地址和限制）
    └─ 验证：vector × 16 < IDT limit
    └─ 如果越界 → 触发 #GP(vector × 8 + 2)

步骤 4: 读取门描述符
    └─ 计算地址：IDT_base + (vector × 16)
    └─ 读取 16 字节的门描述符
    └─ 验证门类型（Interrupt Gate/Trap Gate/Task Gate）

步骤 5: 特权级检查
    └─ 检查 CPL ≤ DPL（门描述符特权级）
    └─ 检查目标代码段 DPL ≤ CPL
    └─ 如果违反 → 触发 #GP

步骤 6: 保存现场
    └─ 如果切换栈（CPL 改变）：
        ├─ 从 TSS 获取新的 SS:RSP
        ├─ 压栈旧的 SS:RSP
    └─ 压栈 RFLAGS、CS、RIP
    └─ 如果异常有错误码 → 压栈错误码

步骤 7: 更新 CPU 状态
    └─ 清除 RFLAGS.TF（Trap Flag）
    └─ 如果是 Interrupt Gate → 清除 RFLAGS.IF（关中断）
    └─ 清除 RFLAGS.RF（Resume Flag）
    └─ 清除 RFLAGS.NT（Nested Task）

步骤 8: 跳转到处理函数
    └─ CS:RIP = 门描述符中的段选择子:偏移量
    └─ 开始执行处理函数
```

**关键点**：
- ✅ 整个过程**完全由 CPU 硬件自动完成**
- ✅ 向量号**硬编码在 CPU 微码中**，软件无法改变
- ✅ 软件只能通过 IDT 表**注册处理函数**
- ❌ 软件**无法干预** CPU 选择哪个向量号

### 2.3 Linux 内核中的向量号定义

**文件位置**：`arch/x86/include/asm/trapnr.h`

```c
/* SPDX-License-Identifier: GPL-2.0 */
#ifndef _ASM_X86_TRAPNR_H
#define _ASM_X86_TRAPNR_H

/*
 * Event type codes used by FRED, Intel VT-x and AMD SVM
 */
#define EVENT_TYPE_EXTINT       0       // External interrupt
#define EVENT_TYPE_NMI          2       // NMI
#define EVENT_TYPE_HWEXC        3       // Hardware originated traps, exceptions
#define EVENT_TYPE_SWINT        4       // INT n
#define EVENT_TYPE_PRIV_SWEXC   5       // INT1
#define EVENT_TYPE_SWEXC        6       // INTO, INT3
#define EVENT_TYPE_OTHER        7       // FRED SYSCALL/SYSENTER, VT-x MTF

/* Interrupts/Exceptions */

#define X86_TRAP_DE              0      /* Divide-by-zero */
#define X86_TRAP_DB              1      /* Debug */
#define X86_TRAP_NMI             2      /* Non-maskable Interrupt */
#define X86_TRAP_BP              3      /* Breakpoint */
#define X86_TRAP_OF              4      /* Overflow */
#define X86_TRAP_BR              5      /* Bound Range Exceeded */
#define X86_TRAP_UD              6      /* Invalid Opcode */
#define X86_TRAP_NM              7      /* Device Not Available */
#define X86_TRAP_DF              8      /* Double Fault */
#define X86_TRAP_OLD_MF          9      /* Coprocessor Segment Overrun */
#define X86_TRAP_TS             10      /* Invalid TSS */
#define X86_TRAP_NP             11      /* Segment Not Present */
#define X86_TRAP_SS             12      /* Stack Segment Fault */
#define X86_TRAP_GP             13      /* General Protection Fault */
#define X86_TRAP_PF             14      /* Page Fault */
#define X86_TRAP_SPURIOUS       15      /* Spurious Interrupt */
#define X86_TRAP_MF             16      /* x87 Floating-Point Exception */
#define X86_TRAP_AC             17      /* Alignment Check */
#define X86_TRAP_MC             18      /* Machine Check */
#define X86_TRAP_XF             19      /* SIMD Floating-Point Exception */
#define X86_TRAP_VE             20      /* Virtualization Exception */
#define X86_TRAP_CP             21      /* Control Protection Exception */
#define X86_TRAP_VC             29      /* VMM Communication Exception */
#define X86_TRAP_IRET           32      /* IRET Exception */

#endif
```

**代码说明**：
- 这些 `#define` **不是定义向量号**，而是**给 Intel 规定的向量号起名字**
- 就像 `const int PAGE_SIZE = 4096;`，4096 是硬件规定的，变量名只是方便引用
- 即使 Linux 写成 `#define X86_TRAP_PF 99`，CPU 检测到缺页仍会查找 IDT[14]

---

## 三、案例 1：Page Fault 的完整流程

### 3.1 触发场景

```c
// 用户程序代码
int main() {
    int *ptr = (int *)0x1000000;  // 假设这个虚拟地址未映射
    *ptr = 42;                    // ← 触发 #PF 的位置
    return 0;
}
```

### 3.2 CPU 硬件的自动行为

```
指令：mov DWORD PTR [0x1000000], 42
  ↓
步骤 1: CPU 执行指令，访问虚拟地址 0x1000000
  ↓
步骤 2: MMU（内存管理单元）查找页表
  ├─ 查找 PML4 → PDPT → PD → PT
  └─ 发现 PTE (Page Table Entry) 的 Present 位 = 0
  ↓
步骤 3: MMU 触发 #PF 异常信号
  ↓
步骤 4: CPU 硬件确定向量号
  └─ vector = 14 (X86_TRAP_PF)  ← 硬编码在 CPU 中
  ↓
步骤 5: 保存错误信息
  ├─ CR2 寄存器 ← 0x1000000（出错的虚拟地址）
  └─ 错误码 ← 构造错误码（P=0, W/R=1, U/S=1 等）
  ↓
步骤 6: 查找 IDT
  ├─ 读取 IDTR 寄存器
  ├─ 计算：IDT_base + (14 × 16) = IDT[14]
  └─ 读取门描述符
  ↓
步骤 7: 保存现场
  ├─ 压栈 SS（用户态栈段）
  ├─ 压栈 RSP（用户态栈指针）
  ├─ 压栈 RFLAGS
  ├─ 压栈 CS（用户态代码段）
  ├─ 压栈 RIP（指向 "mov [0x1000000], 42"）
  └─ 压栈错误码（Page Fault 错误码）
  ↓
步骤 8: 切换到内核态
  ├─ CPL: 3 → 0（用户态 → 内核态）
  ├─ SS:RSP: 用户栈 → 内核栈（从 TSS 获取）
  ├─ CS:RIP: 用户代码 → asm_exc_page_fault（从 IDT[14] 获取）
  └─ RFLAGS.IF ← 0（Interrupt Gate 自动关中断）
  ↓
步骤 9: 跳转到处理函数
  └─ 开始执行 asm_exc_page_fault
```

**关键洞察**：
- ✅ 步骤 1-9 **完全由 CPU 硬件自动完成**，不需要软件干预
- ✅ 向量号 14 是 CPU 硬件决定的，软件无法改变
- ✅ 软件只需在 IDT[14] 填入处理函数地址即可

### 3.3 Linux 内核的软件处理

#### IDT 表的设置

**文件位置**：`arch/x86/kernel/idt.c:63-76`

```c
/*
 * The IDT entries which are set up in trap_init() prior to cpu_init(). On
 * 64-bit systems the #PF entry cannot be used early due to IST requirements
 * and usage of paranoid_entry/exit.
 */
static const __initconst struct idt_data early_idts[] = {
    INTG(X86_TRAP_DB,  asm_exc_debug),
    SYSG(X86_TRAP_BP,  asm_exc_int3),

#ifdef CONFIG_X86_32
    /*
     * Not possible on 64-bit. See idt_setup_early_pf() for details.
     */
    INTG(X86_TRAP_PF,  asm_exc_page_fault),  // ← 32 位在早期阶段设置
#endif
#ifdef CONFIG_INTEL_TDX_GUEST
    INTG(X86_TRAP_VE,  asm_exc_virtualization_exception),
#endif
};
```

**64 位系统在 trap_init() 阶段设置**：

**文件位置**：`arch/x86/kernel/idt.c:84-120`

```c
/*
 * The default IDT entries which are set up in trap_init() before
 * cpu_init() is invoked. Interrupt stacks cannot be used at that point and
 * the traps which use them are reinitialized with IST after cpu_init() has
 * set up TSS.
 */
static const __initconst struct idt_data def_idts[] = {
    INTG(X86_TRAP_DE,   asm_exc_divide_error),
    ISTG(X86_TRAP_NMI,  asm_exc_nmi, IST_INDEX_NMI),
    INTG(X86_TRAP_BR,   asm_exc_bounds),
    INTG(X86_TRAP_UD,   asm_exc_invalid_op),
    INTG(X86_TRAP_NM,   asm_exc_device_not_available),
    INTG(X86_TRAP_OLD_MF, asm_exc_coproc_segment_overrun),
    INTG(X86_TRAP_TS,   asm_exc_invalid_tss),
    INTG(X86_TRAP_NP,   asm_exc_segment_not_present),
    INTG(X86_TRAP_SS,   asm_exc_stack_segment),
    INTG(X86_TRAP_GP,   asm_exc_general_protection),
    // 注意：#PF 在 64 位系统不在这里设置，而是单独设置
    INTG(X86_TRAP_SPURIOUS, asm_exc_spurious_interrupt_bug),
    INTG(X86_TRAP_MF,   asm_exc_coprocessor_error),
    INTG(X86_TRAP_AC,   asm_exc_alignment_check),
    INTG(X86_TRAP_XF,   asm_exc_simd_coprocessor_error),

#ifdef CONFIG_X86_64
    ISTG(X86_TRAP_DF,   asm_exc_double_fault, IST_INDEX_DF),
    ISTG(X86_TRAP_DB,   asm_exc_debug, IST_INDEX_DB),
#endif

#ifdef CONFIG_X86_MCE
    ISTG(X86_TRAP_MC,   asm_exc_machine_check, IST_INDEX_MCE),
#endif

#ifdef CONFIG_X86_CET
    INTG(X86_TRAP_CP,   asm_exc_control_protection),
#endif

#ifdef CONFIG_AMD_MEM_ENCRYPT
    ISTG(X86_TRAP_VC,   asm_exc_vmm_communication, IST_INDEX_VC),
#endif

    SYSG(X86_TRAP_OF,   asm_exc_overflow),
};
```

**宏定义说明**：

```c
// arch/x86/kernel/idt.c
#define DPL0         0x0  /* Kernel mode */
#define DPL3         0x3  /* User mode */
#define DEFAULT_STACK 0

/* Interrupt gate macro */
#define INTG(_vector, _addr) \
    G(_vector, _addr, DEFAULT_STACK, GATE_INTERRUPT, DPL0, __KERNEL_CS)

/*
 * INTG 宏的含义：
 * - _vector: 向量号（如 X86_TRAP_PF = 14）
 * - _addr: 处理函数地址（如 asm_exc_page_fault）
 * - GATE_INTERRUPT: Interrupt Gate（进入时自动清除 IF）
 * - DPL0: 特权级 0（只有内核态能触发，用户态触发会 #GP）
 * - __KERNEL_CS: 内核代码段选择子
 */
```

**IDT[14] 的实际内容**：

```
┌─────────────────────────────────────────────────────────────┐
│              IDT[14] 门描述符（16 字节）                       │
├─────────────────────────────────────────────────────────────┤
│ Offset 15:0    = asm_exc_page_fault & 0xFFFF                │
│ Segment Sel    = __KERNEL_CS                                │
│ IST            = 0 (不使用 IST)                              │
│ Type           = 0xE (Interrupt Gate, 64-bit)               │
│ DPL            = 0 (内核态)                                  │
│ P              = 1 (Present)                                │
│ Offset 31:16   = (asm_exc_page_fault >> 16) & 0xFFFF        │
│ Offset 63:32   = (asm_exc_page_fault >> 32) & 0xFFFFFFFF    │
│ Reserved       = 0                                          │
└─────────────────────────────────────────────────────────────┘
```

#### 处理函数实现

**汇编入口**：`arch/x86/entry/entry_64.S`

```asm
idtentry asm_exc_page_fault exc_page_fault has_error_code=1
```

**C 语言处理函数**：`arch/x86/mm/fault.c:1488-1524`

```c
DEFINE_IDTENTRY_RAW_ERRORCODE(exc_page_fault)
{
    irqentry_state_t state;
    unsigned long address;

    /* 读取 CR2 寄存器获取出错地址 */
    address = cpu_feature_enabled(X86_FEATURE_FRED) ?
              fred_event_data(regs) : read_cr2();

    /*
     * KVM uses #PF vector to deliver 'page not present' events to guests
     * (asynchronous page fault mechanism). The event happens when a
     * userspace task is trying to access some valid (from guest's point of
     * view) memory which is not currently mapped by the host (e.g. the
     * memory is swapped out). Note, the corresponding "page ready" event
     * which is injected when the memory becomes available, is delivered via
     * an interrupt mechanism and not a #PF exception (so the event is not
     * handled by exc_page_fault() but by the interrupt handler).
     */
    if (kvm_handle_async_pf(regs, (u32)address))
        return;

    /* Enter the fault handling code */
    state = irqentry_enter(regs);

    instrumentation_begin();
    /* 实际的缺页处理逻辑 */
    handle_page_fault(regs, error_code, address);
    instrumentation_end();

    irqentry_exit(regs, state);
}
```

**缺页处理主逻辑**：`arch/x86/mm/fault.c:1464-1486`

```c
static __always_inline void
handle_page_fault(struct pt_regs *regs, unsigned long error_code,
                  unsigned long address)
{
    trace_page_fault_entries(regs, error_code, address);

    if (unlikely(kmmio_fault(regs, address)))
        return;

    /* Was the fault on kernel-controlled part of the address space? */
    if (unlikely(fault_in_kernel_space(address))) {
        do_kern_addr_fault(regs, error_code, address);  // 内核地址缺页
    } else {
        do_user_addr_fault(regs, error_code, address);  // 用户地址缺页
        /*
         * User address page fault handling might have reenabled
         * interrupts. Fixing up all potential exit points of
         * do_user_addr_fault() and its leaf functions is just not
         * doable w/o creating an unholy mess or turning the code
         * upside down.
         */
        local_irq_disable();  // 重新关中断
    }
}
```

**用户地址缺页处理**：`arch/x86/mm/fault.c`

```c
static inline void do_user_addr_fault(struct pt_regs *regs,
                                       unsigned long error_code,
                                       unsigned long address)
{
    struct vm_area_struct *vma;
    struct task_struct *tsk = current;
    struct mm_struct *mm = tsk->mm;
    vm_fault_t fault;
    unsigned int flags = FAULT_FLAG_DEFAULT;

    // 1. 检查地址是否在合法的 VMA 范围内
    vma = find_vma(mm, address);
    if (!vma) {
        // 非法地址，发送 SIGSEGV 信号
        force_sig_fault(SIGSEGV, SEGV_MAPERR, address);
        return;
    }

    // 2. 检查权限（读/写/执行）
    if (error_code & X86_PF_WRITE) {
        if (!(vma->vm_flags & VM_WRITE)) {
            force_sig_fault(SIGSEGV, SEGV_ACCERR, address);
            return;
        }
    }

    // 3. 调用通用缺页处理（分配物理页面、读取文件、COW 等）
    fault = handle_mm_fault(vma, address, flags, regs);

    // 4. 处理结果
    if (fault & VM_FAULT_ERROR) {
        // 错误情况：发送信号
        if (fault & VM_FAULT_OOM)
            do_sigbus(regs, error_code, address);  // 内存不足
        else
            force_sig_fault(SIGSEGV, ...);          // 其他错误
    }

    // 5. 成功：IRET 返回，重新执行触发缺页的指令
}
```

### 3.4 完整流程总结

```
┌──────────────────────────────────────────────────────────────┐
│ 1. 用户程序：*ptr = 42;                                        │
└──────────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────────┐
│ 2. CPU 硬件：检测到 PTE.P = 0                                  │
│    - 自动确定向量号 = 14                                       │
│    - CR2 ← 出错地址                                           │
│    - 查找 IDT[14]                                             │
│    - 跳转到 asm_exc_page_fault                                │
└──────────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────────┐
│ 3. 内核处理：exc_page_fault                                    │
│    - 读取 CR2 获取地址                                         │
│    - 调用 handle_page_fault                                   │
│      └─ do_user_addr_fault                                    │
│         ├─ find_vma：查找 VMA                                 │
│         ├─ 检查权限                                            │
│         └─ handle_mm_fault：分配页面、更新页表                 │
└──────────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────────┐
│ 4. 返回：IRET 指令                                             │
│    - 恢复用户态现场（RSP、RFLAGS、CS、RIP）                    │
│    - RIP 指向触发缺页的指令（"mov [ptr], 42"）                 │
│    - 重新执行指令，这次页表已存在 → 成功                       │
└──────────────────────────────────────────────────────────────┘
```

**关键点**：
1. **CPU 自动触发**：检测到缺页 → 自动使用向量 14 → 自动查 IDT[14]
2. **软件无需调用**：不需要 `call page_fault_handler()`
3. **向量号固定**：14 是 Intel 规定的，Linux 无法改变
4. **软件职责**：只需在 IDT[14] 填入处理函数地址，并实现处理逻辑

---

## 四、案例 2：Breakpoint 的实现与触发

### 4.1 断点的硬件支持

#### Intel SDM 规定

根据 **Intel SDM Volume 3A, Section 6.3.1**：

- **向量号**：3 (#BP)
- **异常类型**：Trap（陷阱）
- **触发方式**：INT 3 指令（操作码 `0xCC`）
- **保存的 RIP**：指向**下一条指令**（而非 INT 3 本身）
- **用途**：调试器设置断点

#### Trap 与 Fault 的区别

| 特性 | Trap (#BP, #OF) | Fault (#PF, #GP) |
|------|-----------------|------------------|
| **保存的 RIP** | 下一条指令 | 触发异常的指令 |
| **返回后行为** | 继续执行下一条 | 重新执行触发异常的指令 |
| **典型用途** | 调试、监控 | 修复错误后重试 |

**示例**：

```c
// Breakpoint (Trap)
address:  mov eax, 10     // RIP = 0x1000
address:  int3            // RIP = 0x1002，触发 #BP
address:  mov ebx, 20     // RIP = 0x1003 ← 保存的 RIP 指向这里

// Page Fault (Fault)
address:  mov eax, 10     // RIP = 0x2000
address:  mov [0x5000], eax  // RIP = 0x2002，触发 #PF
                             // 保存的 RIP = 0x2002（触发异常的指令）
                             // 修复后 IRET → 重新执行 mov [0x5000], eax
```

### 4.2 Linux 内核的断点实现

#### IDT 表设置

**文件位置**：`arch/x86/kernel/idt.c:63-76`

```c
static const __initconst struct idt_data early_idts[] = {
    INTG(X86_TRAP_DB,  asm_exc_debug),    // 调试异常（向量 1）
    SYSG(X86_TRAP_BP,  asm_exc_int3),     // 断点异常（向量 3）← 这里
    // ...
};
```

**SYSG 宏定义**：

```c
/* System interrupt gate (User accessible) */
#define SYSG(_vector, _addr) \
    G(_vector, _addr, DEFAULT_STACK, GATE_INTERRUPT, DPL3, __KERNEL_CS)
    //                                                ^^^^
    //                                                DPL = 3：用户态可触发
```

**关键区别**：
- `INTG`：DPL = 0（只有内核态能触发）
- `SYSG`：DPL = 3（用户态也能触发）

**为什么断点需要 DPL=3？**

用户程序需要能够执行 `INT 3` 指令来设置断点：

```c
// 用户程序（CPL = 3）
int main() {
    int x = 10;
    __asm__("int3");  // 如果 IDT[3].DPL = 0，这里会触发 #GP
    int y = 20;       // 如果 IDT[3].DPL = 3，可以正常触发 #BP
    return x + y;
}
```

**特权级检查规则**（Intel SDM Volume 3A, Section 5.5）：

```
当前特权级（CPL）≤ 门描述符特权级（DPL）才能通过 INT n 触发
```

| IDT[3].DPL | 用户态 (CPL=3) | 内核态 (CPL=0) | 说明 |
|-----------|----------------|----------------|------|
| 0 | ❌ 触发 #GP | ✅ 正常 | 只有内核能用 |
| 3 | ✅ 正常 | ✅ 正常 | 用户和内核都能用 |

#### 处理函数实现

**文件位置**：`arch/x86/kernel/traps.c:883-915`

```c
DEFINE_IDTENTRY_RAW(exc_int3)
{
    /*
     * smp_text_poke_int3_handler() is completely self contained code; it does (and
     * must) *NOT* call out to anything, lest it hits upon yet another
     * INT3.
     */
    if (smp_text_poke_int3_handler(regs))
        return;  // ← 用于内核代码热补丁（kprobes）

    /*
     * irqentry_enter_from_user_mode() uses static_branch_{,un}likely()
     * and therefore can trigger INT3, hence smp_text_poke_int3_handler() must
     * be done before. If the entry came from kernel mode, then use
     * nmi_enter() because the INT3 could have been hit in any context
     * including NMI.
     */
    if (user_mode(regs)) {
        irqentry_enter_from_user_mode(regs);
        instrumentation_begin();
        do_int3_user(regs);  // ← 用户态断点处理
        instrumentation_end();
        irqentry_exit_to_user_mode(regs);
    } else {
        irqentry_state_t irq_state = irqentry_nmi_enter(regs);

        instrumentation_begin();
        if (!do_int3(regs))  // ← 内核态断点处理
            die("int3", regs, 0);  // 如果处理失败 → 内核崩溃
        instrumentation_end();
        irqentry_nmi_exit(regs, irq_state);
    }
}
```

**用户态断点处理**（简化版）：

```c
static void do_int3_user(struct pt_regs *regs)
{
    /*
     * 发送 SIGTRAP 信号给当前进程
     * 调试器（如 GDB）会捕获这个信号
     */
    force_sig_fault(SIGTRAP, TRAP_BRKPT,
                    (void __user *)regs->ip - 1);
    /*
     * 注意：regs->ip - 1
     * - Trap 类型：保存的 RIP 指向下一条指令
     * - 调试器需要知道断点的实际位置（INT 3 的地址）
     * - 所以减去 INT 3 指令的长度（1 字节）
     */
}
```

### 4.3 断点的两种触发方式

#### 方式 1：直接使用 INT 3 指令

```c
#include <stdio.h>

int main() {
    int x = 10;
    printf("Before breakpoint: x = %d\n", x);

    __asm__ volatile("int3");  // ← 触发断点

    int y = 20;
    printf("After breakpoint: y = %d\n", y);
    return x + y;
}
```

**编译和执行**：

```bash
$ gcc -g -o test test.c
$ ./test
Before breakpoint: x = 10
Trace/breakpoint trap (core dumped)  # ← SIGTRAP 信号导致程序终止
```

**在 GDB 中运行**：

```bash
$ gdb ./test
(gdb) run
Before breakpoint: x = 10

Program received signal SIGTRAP, Trace/breakpoint trap.
0x000055555555517a in main () at test.c:8
8           int y = 20;
(gdb) print x
$1 = 10
(gdb) continue
After breakpoint: y = 20
[Inferior 1 (process 12345) exited normally]
```

#### 方式 2：调试器动态插入断点

**GDB 的断点原理**：

```c
// 原始代码和机器码
int foo() {
    return 42;         // 地址 0x400500: mov eax, 0x2a
                       //                ret
}

// 用户在 GDB 中设置断点：
(gdb) break foo

// GDB 的操作：
// 1. 读取 0x400500 处的原始字节：mov eax, 0x2a（机器码：b8 2a 00 00 00）
// 2. 保存原始字节到内部数据结构
// 3. 使用 ptrace(PTRACE_POKETEXT) 写入 0xCC（INT 3 指令）
// 4. 现在 0x400500 的内容是：0xCC 2a 00 00 00

// 程序执行到断点：
// 1. CPU 执行到 0x400500
// 2. 遇到 0xCC（INT 3 指令）
// 3. 触发 #BP 异常（向量 3）
// 4. 内核发送 SIGTRAP 信号给进程
// 5. GDB（作为父进程）通过 ptrace 捕获信号
// 6. GDB 停止程序，显示断点信息

// 用户继续执行：
(gdb) continue

// GDB 的操作：
// 1. 恢复原始字节：0x400500 ← b8 2a 00 00 00
// 2. 将 RIP 减 1（因为 Trap 类型保存的是下一条指令）
// 3. 单步执行恢复的指令（mov eax, 0x2a）
// 4. 重新插入 0xCC
// 5. 让程序继续运行
```

**ptrace 系统调用示例**：

```c
#include <sys/ptrace.h>
#include <sys/wait.h>
#include <unistd.h>
#include <stdio.h>

int main() {
    pid_t child = fork();

    if (child == 0) {
        // 子进程：被调试程序
        ptrace(PTRACE_TRACEME, 0, NULL, NULL);
        execl("./target", "target", NULL);
    } else {
        // 父进程：调试器
        int status;
        wait(&status);  // 等待子进程启动

        // 读取目标地址的原始指令
        long addr = 0x400500;
        long original = ptrace(PTRACE_PEEKTEXT, child, addr, NULL);

        // 插入断点（INT 3 = 0xCC）
        long breakpoint = (original & ~0xFF) | 0xCC;
        ptrace(PTRACE_POKETEXT, child, addr, breakpoint);

        // 继续执行
        ptrace(PTRACE_CONT, child, NULL, NULL);
        wait(&status);  // 等待断点触发（收到 SIGTRAP）

        // 断点命中！
        printf("Breakpoint hit!\n");

        // 恢复原始指令
        ptrace(PTRACE_POKETEXT, child, addr, original);

        // ... 继续调试 ...
    }

    return 0;
}
```

### 4.4 断点的完整流程

```
┌──────────────────────────────────────────────────────────────┐
│ 1. 用户设置断点：(gdb) break main                             │
│    - GDB 在 main 函数入口写入 0xCC（INT 3）                   │
└──────────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────────┐
│ 2. 程序执行到断点                                              │
│    - CPU 执行 INT 3 指令（0xCC）                              │
└──────────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────────┐
│ 3. CPU 硬件处理                                               │
│    - 识别 INT 3 指令 → 向量号 = 3                             │
│    - 保存 RIP（指向下一条指令）                                │
│    - 查找 IDT[3]                                              │
│    - 跳转到 asm_exc_int3                                      │
└──────────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────────┐
│ 4. 内核处理：exc_int3                                          │
│    - 检测到用户态 → do_int3_user                              │
│    - 发送 SIGTRAP 信号给进程                                   │
└──────────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────────┐
│ 5. GDB 捕获信号                                                │
│    - ptrace 捕获 SIGTRAP                                      │
│    - 停止程序执行                                              │
│    - 显示断点位置和上下文                                       │
│    - 等待用户命令（continue/step/print 等）                    │
└──────────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────────┐
│ 6. 用户继续执行：(gdb) continue                                │
│    - GDB 恢复原始指令                                          │
│    - 单步执行                                                  │
│    - 重新插入断点                                              │
│    - 程序继续运行                                              │
└──────────────────────────────────────────────────────────────┘
```

---

## 五、向量号的硬件规范

### 5.1 Intel 的强制保留

根据 **Intel SDM Volume 3A, Section 6.15: Exception and Interrupt Reference**：

> Intel has reserved vectors 0-31 for current and future exception types. These vectors may not be used for external interrupt vectors (INTR pin or I/O APIC).

**中文翻译**：
Intel 保留了向量 0-31 用于当前和未来的异常类型。这些向量不得用于外部中断向量（INTR 引脚或 I/O APIC）。

### 5.2 向量号分配表

| 向量范围 | 用途 | 分配者 | 可否修改 | 说明 |
|---------|------|--------|---------|------|
| **0-31** | **CPU 异常** | **Intel** | **❌ 否** | **硬件规范，所有 x86 CPU 必须遵守** |
| 32-255 | 用户定义 | 操作系统 | ✅ 是 | 可用于硬件中断、系统调用等 |

### 5.3 为什么向量号不能改？

#### 原因 1：二进制兼容性

```c
// 在 1985 年编译的 MS-DOS 程序
int divide(int a, int b) {
    return a / b;  // 如果 b = 0，CPU 触发 #DE（向量 0）
}

// 在 2026 年的 Intel CPU 上运行
// 仍然使用向量 0，因为这是 Intel 保证的硬件规范
```

如果 Intel 在新 CPU 上把除零异常改成向量 99：
- 所有旧程序的 IDT 仍然在向量 0 设置处理函数
- 新 CPU 触发向量 99 → IDT[99] 为空 → Triple Fault → 重启
- **所有旧软件都无法运行** ❌

#### 原因 2：硬件实现

CPU 的异常检测逻辑**硬编码在微码（microcode）**中：

```
CPU 微码伪代码：
if (division_by_zero_detected) {
    vector = 0;  // ← 硬编码！
    trigger_exception(vector);
}

if (page_fault_detected) {
    vector = 14;  // ← 硬编码！
    CR2 = faulting_address;
    trigger_exception(vector);
}

if (int3_instruction_executed) {
    vector = 3;  // ← 硬编码！
    trigger_exception(vector);
}
```

这些向量号是 CPU **硬件电路的一部分**，无法通过软件修改。

#### 原因 3：多 CPU 厂商兼容

所有 x86 兼容 CPU（Intel、AMD、VIA、Centaur）都必须遵守 Intel SDM 规范：

```
Intel CPU:   #PF = 14
AMD CPU:     #PF = 14  ← 必须相同
VIA CPU:     #PF = 14  ← 必须相同

否则：
- 操作系统无法在不同 CPU 上运行
- 需要为每个 CPU 厂商编译不同版本的内核
- x86 生态系统崩溃
```

### 5.4 软件可以控制的部分

虽然向量号不能改，但软件可以控制：

```c
// ✅ 可以控制：IDT[14] 指向哪个函数
INTG(X86_TRAP_PF, my_custom_page_fault_handler);  // 自定义处理函数

// ✅ 可以控制：硬件中断的向量号（32-255）
outb(0x30, 0x21);  // PIC: IRQ 0（时钟）映射到向量 0x30
outb(0x38, 0xA1);  // PIC: IRQ 8（RTC）映射到向量 0x38

// ✅ 可以控制：系统调用的向量号（如果使用 INT 指令）
SYSG(0x80, asm_int80_emulation);  // INT 0x80 系统调用

// ❌ 不能控制：CPU 检测到缺页时使用的向量号
// CPU 硬件永远使用向量 14，这是不可改变的
```

---

## 六、软件的职责边界

### 6.1 硬件 vs 软件的职责划分

| 职责 | 硬件（CPU） | 软件（内核） |
|------|-------------|-------------|
| **检测异常条件** | ✅ 硬件检测（如 PTE.P = 0） | ❌ 不参与 |
| **确定向量号** | ✅ 硬编码在微码中 | ❌ 无法改变 |
| **保存错误信息** | ✅ CR2、错误码 | ❌ 不参与 |
| **查找 IDT** | ✅ 硬件自动查找 | ❌ 不参与 |
| **保存现场** | ✅ 压栈 SS/RSP/RFLAGS/CS/RIP | ❌ 不参与 |
| **切换特权级** | ✅ 从 TSS 获取内核栈 | ✅ 提前设置 TSS |
| **跳转到处理函数** | ✅ 使用 IDT 中的地址 | ❌ 不参与 |
| **构建 IDT 表** | ❌ 不参与 | ✅ 填充 256 个门描述符 |
| **注册处理函数** | ❌ 不参与 | ✅ 在 IDT[vector] 填入地址 |
| **实现处理逻辑** | ❌ 不参与 | ✅ 如 do_page_fault |
| **修复问题** | ❌ 不参与 | ✅ 分配页面、发送信号等 |
| **返回** | ✅ IRET 指令恢复现场 | ✅ 执行 IRET 指令 |

### 6.2 Linux 内核的实现方式

#### IDT 表的构建

```c
// arch/x86/kernel/idt.c

// 1. 定义 IDT 表（256 个条目）
static gate_desc idt_table[IDT_ENTRIES] __page_aligned_bss;

// 2. 定义异常处理器映射
static const struct idt_data def_idts[] = {
    INTG(X86_TRAP_DE,   asm_exc_divide_error),       // 向量 0
    ISTG(X86_TRAP_DB,   asm_exc_debug, IST_INDEX_DB),  // 向量 1
    // ... 省略 ...
    INTG(X86_TRAP_GP,   asm_exc_general_protection),  // 向量 13
    // #PF (向量 14) 在 64 位单独设置
    // ... 省略 ...
};

// 3. 初始化 IDT
void __init idt_setup_traps(void)
{
    // 将 def_idts 数组中的条目写入 idt_table
    idt_setup_from_table(idt_table, def_idts, ARRAY_SIZE(def_idts), true);
}

// 4. 加载 IDT
void load_idt(const struct desc_ptr *dtr)
{
    asm volatile("lidt %0"::"m" (*dtr));
    // lidt 指令：将 IDT 基地址和限制加载到 IDTR 寄存器
}
```

#### 处理函数的实现

```c
// arch/x86/mm/fault.c

DEFINE_IDTENTRY_RAW_ERRORCODE(exc_page_fault)
{
    unsigned long address = read_cr2();  // 读取出错地址

    // 实际处理逻辑
    handle_page_fault(regs, error_code, address);

    // 返回（IRET 由汇编入口自动处理）
}
```

### 6.3 不同操作系统的实现对比

| 特性 | Linux | Windows | FreeBSD | 说明 |
|------|-------|---------|---------|------|
| **向量号** | 14 | 14 | 14 | 由 Intel SDM 固定 ✅ |
| **处理函数** | exc_page_fault | KiPageFault | trap_pfault | 各自实现 ✅ |
| **缺页策略** | demand paging | demand paging | demand paging | 各自实现 ✅ |
| **信号机制** | SIGSEGV | SEH Exception | SIGSEGV | 各自实现 ✅ |

**关键点**：
- ✅ 所有操作系统**必须**在 IDT[14] 设置 Page Fault 处理函数
- ✅ 处理函数的**实现细节**可以不同
- ❌ 无法把 Page Fault 映射到其他向量号（如 99）

---

## 七、常见问题

### Q1: 软件能否主动调用异常处理函数？

**A1: 可以，但通常不这样做。**

```c
// ✅ 技术上可行（但不推荐）
extern void exc_page_fault(struct pt_regs *regs, unsigned long error_code);

void some_function() {
    struct pt_regs fake_regs = { ... };
    exc_page_fault(&fake_regs, 0);  // 直接调用
}

// ❌ 问题：
// 1. 绕过了 CPU 的现场保存机制
// 2. 无法正确恢复（IRET 需要特定的栈布局）
// 3. 可能导致内核崩溃
```

**正确做法**：
- 如果需要主动触发异常：使用 `INT n` 指令
- 如果需要处理缺页：调用内存管理函数（如 `get_user_pages`）

### Q2: 为什么 INT 3 是单字节指令？

**A2: 为了方便调试器插入断点。**

```c
// 假设 INT 3 是双字节指令（如 0xCD 0x03）
int foo() {
    return 42;  // 机器码：mov eax, 0x2a (b8 2a 00 00 00)
}              //         ret              (c3)

// 调试器插入断点：
// 原始：b8 2a 00 00 00 c3
// 插入：cd 03 00 00 00 c3  ← 需要覆盖 2 字节
//       ^^^^^ INT 3 指令
// 问题：覆盖了部分 mov 指令，无法恢复

// 实际 INT 3 是单字节 0xCC：
// 原始：b8 2a 00 00 00 c3
// 插入：cc 2a 00 00 00 c3  ← 只覆盖 1 字节
//       ^^ INT 3 指令
// 恢复：b8 2a 00 00 00 c3  ← 完美恢复
```

### Q3: 为什么 #BP 的 DPL 是 3 而 #PF 的 DPL 是 0？

**A3: 安全考虑。**

```c
// #BP (DPL = 3)：用户程序需要能设置断点
int user_program() {
    __asm__("int3");  // ✅ 允许（用于调试）
}

// #PF (DPL = 0)：禁止用户主动触发
int user_program() {
    __asm__("int $14");  // ❌ 触发 #GP（安全问题）
}

// 为什么禁止？
// 1. 安全：用户可以伪造错误码和 CR2，攻击内核
// 2. 不需要：缺页会自动触发，无需手动
```

**例外**：
- #BP (3)：DPL = 3（用户可触发）
- #OF (4)：DPL = 3（用户可触发 INTO 指令）
- 其他异常：DPL = 0（只有内核可触发）

### Q4: 如果 IDT 中没有设置处理函数会怎样？

**A4: 触发 Double Fault (#DF) 或 Triple Fault。**

```
场景 1: IDT[14] 为空（全零）
    ↓
触发 #PF → CPU 查找 IDT[14]
    ↓
发现门描述符 Present 位 = 0（无效）
    ↓
触发 #GP(14 × 8 + 2) = #GP(114)
    ↓
查找 IDT[13] (#GP 的处理函数)
    ↓
如果 IDT[13] 也为空 → 触发 #DF(0)
    ↓
查找 IDT[8] (#DF 的处理函数)
    ↓
如果 IDT[8] 也为空 → Triple Fault → CPU 重启 💥
```

**这就是为什么内核启动早期需要设置基本的异常处理函数。**

### Q5: 不同 CPU 厂商的向量号是否一致？

**A5: 完全一致。**

| 异常 | Intel CPU | AMD CPU | VIA CPU | Hygon CPU |
|------|-----------|---------|---------|-----------|
| #DE | 0 | 0 | 0 | 0 |
| #BP | 3 | 3 | 3 | 3 |
| #PF | 14 | 14 | 14 | 14 |
| #VC | 29 | 29 | - | 29 |

**原因**：
- AMD、VIA 等厂商实现的是 **x86 兼容 CPU**
- 必须遵守 Intel x86 架构规范（或 AMD64 规范）
- 否则无法运行 x86 软件，失去市场竞争力

---

## 八、实验验证

### 8.1 验证向量号的硬件固定性

```c
// test_vector.c
#include <stdio.h>
#include <signal.h>
#include <setjmp.h>

sigjmp_buf env;

void sigsegv_handler(int sig) {
    printf("Caught SIGSEGV (triggered by #PF)\n");
    siglongjmp(env, 1);
}

int main() {
    signal(SIGSEGV, sigsegv_handler);

    if (sigsetjmp(env, 1) == 0) {
        // 触发缺页异常
        int *ptr = (int *)0x1000000;  // 未映射地址
        *ptr = 42;  // ← CPU 自动使用向量 14
    }

    printf("Returned from signal handler\n");

    // 即使我们修改内核代码也无法改变向量号
    // 因为向量号是 CPU 硬件决定的

    return 0;
}
```

**编译和运行**：

```bash
$ gcc -o test_vector test_vector.c
$ ./test_vector
Caught SIGSEGV (triggered by #PF)
Returned from signal handler
```

### 8.2 验证断点的 DPL=3

```c
// test_breakpoint.c
#include <stdio.h>
#include <signal.h>

void sigtrap_handler(int sig) {
    printf("Caught SIGTRAP (triggered by #BP)\n");
    _exit(0);  // 退出，避免循环
}

int main() {
    signal(SIGTRAP, sigtrap_handler);

    printf("Before INT 3\n");
    __asm__ volatile("int3");  // 用户态触发 INT 3
    printf("After INT 3 (won't reach here)\n");

    return 0;
}
```

**运行结果**：

```bash
$ gcc -o test_bp test_breakpoint.c
$ ./test_bp
Before INT 3
Caught SIGTRAP (triggered by #BP)
```

**验证 DPL 检查**：

```c
// test_page_fault_int.c
#include <stdio.h>

int main() {
    printf("Before INT 14\n");
    __asm__ volatile("int $14");  // 尝试触发 INT 14 (#PF)
    printf("After INT 14 (won't reach here)\n");
    return 0;
}
```

**运行结果**：

```bash
$ gcc -o test_pf test_page_fault_int.c
$ ./test_pf
Before INT 14
Segmentation fault (core dumped)  # ← 触发 #GP，然后被内核转换为 SIGSEGV
```

**解释**：
- INT 3：IDT[3].DPL = 3 → 用户态可触发 → SIGTRAP ✅
- INT 14：IDT[14].DPL = 0 → 用户态触发 → #GP → SIGSEGV ❌

### 8.3 使用 GDB 观察 IDT

```bash
# 在 QEMU 中运行 Linux，使用 GDB 调试
$ qemu-system-x86_64 -kernel vmlinuz -s -S

# 在另一个终端
$ gdb vmlinux
(gdb) target remote :1234
(gdb) break start_kernel
(gdb) continue

# 查看 IDTR 寄存器
(gdb) info registers idtr
idtr           {base=0xfffffe0000000000, limit=0xfff}

# 查看 IDT[14] 的内容（#PF）
(gdb) x/2xg 0xfffffe0000000000 + 14 * 16
0xfffffe00000000e0:     0x8e0000100000abcd     0x00000000ffffffff

# 解析门描述符
# Offset = 0xffffffff0000abcd (asm_exc_page_fault 地址)
# Type = 0xE (Interrupt Gate)
# DPL = 0 (内核态)
# P = 1 (Present)
```

---

## 总结

### 核心要点

1. **异常处理不需要软件主动调用**
   - CPU 硬件自动检测异常条件
   - CPU 硬件自动查找 IDT 并跳转到处理函数
   - 软件只需在 IDT 中注册处理函数地址

2. **向量号由 Intel SDM 规范固定**
   - 向量 0-31 硬编码在 CPU 微码中
   - 所有 x86 兼容 CPU 必须遵守
   - 软件无法改变向量号，只能在对应位置填入处理函数

3. **软件职责边界清晰**
   - 硬件：检测、分发、保存现场、切换特权级
   - 软件：构建 IDT、注册处理函数、实现处理逻辑、修复问题

4. **断点机制的特殊性**
   - INT 3 是单字节指令（0xCC），方便调试器插入
   - #BP 的 DPL = 3，允许用户态触发
   - Trap 类型：保存的 RIP 指向下一条指令

### 相关文档

- **[x86 中断、异常、陷阱：Intel SDM 规范与 Linux 实现](X86_INTERRUPT_EXCEPTION_TRAP.md)** - 基础概念和分类
- **[Linux 内核 IDT 表的演进流程详解](LINUX_KERNEL_IDT_EVOLUTION.md)** - IDT 初始化流程
- **[系统调用初始化详解](LINUX_KERNEL_SYSCALL_INIT.md)** - INT 0x80 vs SYSCALL
- **[Linux 中断处理机制](LINUX_INTERRUPT_GUIDE.md)** - 运行时中断处理

---

**文档版本**：1.0
**最后更新**：2026-02-12
**基于内核版本**：Linux v6.x
**维护者**：Linux 内核启动文档项目
