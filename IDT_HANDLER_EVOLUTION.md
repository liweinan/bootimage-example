# IDT 处理程序的三代演进

**文档系列**：Linux x86_64 IDT 初始化机制分析
**主文档**：[IDT_SETUP_EARLY_HANDLER_DETAILED_ANALYSIS.md](./IDT_SETUP_EARLY_HANDLER_DETAILED_ANALYSIS.md)
**相关文档**：
- [IDT_COMPLETE_VECTOR_TABLE.md](./IDT_COMPLETE_VECTOR_TABLE.md) - 完整向量表参考
- [IDT_EXCEPTION_HANDLING_DETAILS.md](./IDT_EXCEPTION_HANDLING_DETAILS.md) - 异常处理流程详解
- [LINUX_KERNEL_IDT_EVOLUTION.md](./LINUX_KERNEL_IDT_EVOLUTION.md) - IDT 表的整体演进

---

## 目录

1. [概述：为什么需要三代处理程序](#1-概述为什么需要三代处理程序)
2. [第 1 代：Emergency Handlers（应急处理程序）](#2-第-1-代emergency-handlers应急处理程序)
3. [第 2 代：Transitional Handlers（过渡处理程序）](#3-第-2-代transitional-handlers过渡处理程序)
4. [第 3 代：Production Handlers（生产级处理程序）](#4-第-3-代production-handlers生产级处理程序)
5. [演进时间线](#5-演进时间线)
6. [对比分析：以 #PF 为例](#6-对比分析以-pf-为例)
7. [early_idt_handler_common 的命运](#7-early_idt_handler_common-的命运)
8. [Chicken-and-Egg 问题](#8-chicken-and-egg-问题)

---

## 1. 概述：为什么需要三代处理程序

### 核心问题

**问题**：生产级异常处理程序需要完整的内核功能，但在这些功能初始化完成之前，就可能触发异常！

```
矛盾：
┌────────────────────────────────────────────────────┐
│  生产级处理程序需要：                               │
│  ├─ TSS/IST（中断栈表）                            │
│  ├─ 完整的内存管理（vmalloc、slab、buddy）         │
│  ├─ 进程管理（task_struct、调度器）                │
│  ├─ 信号机制（SIGSEGV、SIGILL）                    │
│  └─ 复杂的数据结构（VMA、页表、锁）                │
└────────────────────────────────────────────────────┘
              ↑
              │ 但这些功能还没初始化！
              ↓
┌────────────────────────────────────────────────────┐
│  启动早期就可能触发异常：                           │
│  ├─ 内存映射阶段 → #PF (Page Fault)                │
│  ├─ KASAN 检查 → #PF                               │
│  ├─ 硬件探测 → #GP, #UD                            │
│  └─ GDT/页表切换 → #PF, #DF                        │
└────────────────────────────────────────────────────┘
```

### 解决方案：分阶段初始化

```
阶段 1：Emergency Handlers（应急）
  └─ 极简设计，无依赖，只处理关键异常

阶段 2：Transitional Handlers（过渡）
  └─ 部分替换，逐步引入完整功能

阶段 3：Production Handlers（生产）
  └─ 完整功能，支持所有特性
```

---

## 2. 第 1 代：Emergency Handlers（应急处理程序）

### 使用时间

**从**：`x86_64_start_kernel()` 早期
**到**：`trap_init()` 开始前

### 处理程序链

```
异常触发
    ↓
CPU 查找 idt_table[vector]
    ↓
跳转到 early_idt_handler_array[vector]
    ↓
压入向量号，跳转到 early_idt_handler_common
    ↓
保存所有寄存器，构建 pt_regs
    ↓
调用 do_early_exception(pt_regs, trapnr)
    ↓
根据向量号进行简单处理
```

### 关键代码

**汇编桩**（`arch/x86/kernel/head_64.S`）：

```asm
SYM_CODE_START(early_idt_handler_array)
    i = 0
    .rept NUM_EXCEPTION_VECTORS  # 32 次
        .if ((EXCEPTION_ERRCODE_MASK >> i) & 1) == 0
            pushq $0  # 假错误码
        .endif
        pushq $i      # 向量号
        jmp early_idt_handler_common
        i = i + 1
    .endr
SYM_CODE_END(early_idt_handler_array)

SYM_CODE_START_LOCAL(early_idt_handler_common)
    # 保存所有寄存器
    pushq %rsi
    pushq %rdi
    pushq %rdx
    # ... (所有通用寄存器)

    movq %rsp, %rdi  # 第一个参数：pt_regs
    # RSI 已经是 trapnr
    call do_early_exception

    # 恢复寄存器
    jmp restore_regs_and_return_to_kernel
SYM_CODE_END(early_idt_handler_common)
```

**C 处理函数**（`arch/x86/kernel/head64.c`）：

```c
void __init do_early_exception(struct pt_regs *regs, int trapnr)
{
    // 1. 处理 #PF（缺页异常）
    if (trapnr == X86_TRAP_PF &&
        early_make_pgtable(native_read_cr2()))
        return;

    // 2. 处理 AMD SEV 虚拟化异常
    if (IS_ENABLED(CONFIG_AMD_MEM_ENCRYPT) &&
        trapnr == X86_TRAP_VC && handle_vc_boot_ghcb(regs))
        return;

    // 3. 处理 Intel TDX 虚拟化异常
    if (trapnr == X86_TRAP_VE && tdx_early_handle_ve(regs))
        return;

    // 4. 其他异常：尝试修复或 panic
    early_fixup_exception(regs, trapnr);
}
```

### 特点

| 特性 | 支持 | 说明 |
|------|------|------|
| **依赖** | ✅ 无 | 不需要 TSS、进程管理等 |
| **IST** | ❌ 否 | 使用当前栈，无专用栈 |
| **#PF 处理** | ⚠️ 有限 | 只能动态建立页表 |
| **其他异常** | ❌ 否 | 大部分会 panic |
| **用户态** | ❌ 否 | 不支持用户空间异常 |
| **信号** | ❌ 否 | 无法发送 SIGSEGV |
| **调试** | ❌ 否 | 无详细诊断信息 |

### 只处理 4 类异常

```c
1. #PF (Page Fault, 向量 14)
   └─ early_make_pgtable() - 动态建立内核页表

2. #VC (VMM Communication, 向量 29)
   └─ handle_vc_boot_ghcb() - AMD SEV 虚拟化

3. #VE (Virtualization Exception, 向量 20)
   └─ tdx_early_handle_ve() - Intel TDX 虚拟化

4. 其他异常
   └─ early_fixup_exception() - 查异常表或 panic
```

---

## 3. 第 2 代：Transitional Handlers（过渡处理程序）

### 使用时间

**从**：`trap_init()` 开始
**到**：`cpu_init()` 完成（TSS 初始化）

### 部分覆盖

**阶段 2**：`idt_setup_early_traps()`

```c
// arch/x86/kernel/idt.c
static const __initconst struct idt_data early_idts[] = {
    INTG(X86_TRAP_DB,   asm_exc_debug),          // 向量 1: #DB
    SYSG(X86_TRAP_BP,   asm_exc_int3),           // 向量 3: #BP

#ifdef CONFIG_X86_32
    INTG(X86_TRAP_PF,   asm_exc_page_fault),     // 向量 14: #PF (仅 32 位)
#endif
#ifdef CONFIG_INTEL_TDX_GUEST
    INTG(X86_TRAP_VE,   asm_exc_virtualization_exception),  // 向量 20: #VE
#endif
};

void __init idt_setup_early_traps(void)
{
    idt_setup_from_table(idt_table, early_idts, ARRAY_SIZE(early_idts), true);
    load_idt(&idt_descr);
}
```

**阶段 3**：`idt_setup_early_pf()`（仅 x86-64）

```c
#ifdef CONFIG_X86_64
static const __initconst struct idt_data early_pf_idts[] = {
    INTG(X86_TRAP_PF,   asm_exc_page_fault),     // 向量 14: #PF
};

void __init idt_setup_early_pf(void)
{
    idt_setup_from_table(idt_table, early_pf_idts,
                         ARRAY_SIZE(early_pf_idts), true);
}
#endif
```

### 覆盖对比

| 向量 | 异常名 | 第 1 代 | 第 2 代 |
|------|--------|---------|---------|
| 1 | #DB (Debug) | early_idt_handler_array[1] | asm_exc_debug |
| 3 | #BP (Breakpoint) | early_idt_handler_array[3] | asm_exc_int3 |
| 14 | #PF (Page Fault) | early_idt_handler_array[14] | asm_exc_page_fault |
| 20 | #VE (Virt Exception) | early_idt_handler_array[20] | asm_exc_virtualization_exception |
| 其他 | - | early_idt_handler_array[i] | 仍使用第 1 代 |

### 特点

| 特性 | 支持 | 说明 |
|------|------|------|
| **依赖** | ⚠️ 部分 | 可以使用内存管理，但不完整 |
| **IST** | ❌ 否 | 仍然不使用 IST（TSS 未初始化） |
| **#PF 处理** | ✅ 完整 | 可以处理各种缺页情况 |
| **调试异常** | ✅ 是 | #DB, #BP 可以正常工作 |
| **其他异常** | ❌ 部分 | 大部分仍使用第 1 代 |

---

## 4. 第 3 代：Production Handlers（生产级处理程序）

### 使用时间

**从**：`cpu_init()` 完成后
**到**：内核运行结束

### 完全覆盖

**阶段 4**：`idt_setup_traps()`

```c
// arch/x86/kernel/idt.c
static const __initconst struct idt_data def_idts[] = {
    INTG(X86_TRAP_DE,       asm_exc_divide_error),               // 0: #DE
    ISTG(X86_TRAP_NMI,      asm_exc_nmi, IST_INDEX_NMI),         // 2: #NMI (IST)
    INTG(X86_TRAP_BR,       asm_exc_bounds),                     // 5: #BR
    INTG(X86_TRAP_UD,       asm_exc_invalid_op),                 // 6: #UD
    INTG(X86_TRAP_NM,       asm_exc_device_not_available),       // 7: #NM
    INTG(X86_TRAP_OLD_MF,   asm_exc_coproc_segment_overrun),     // 9: #MF_OLD
    INTG(X86_TRAP_TS,       asm_exc_invalid_tss),                // 10: #TS
    INTG(X86_TRAP_NP,       asm_exc_segment_not_present),        // 11: #NP
    INTG(X86_TRAP_SS,       asm_exc_stack_segment),              // 12: #SS
    INTG(X86_TRAP_GP,       asm_exc_general_protection),         // 13: #GP
    INTG(X86_TRAP_SPURIOUS, asm_exc_spurious_interrupt_bug),     // 15: SPURIOUS
    INTG(X86_TRAP_MF,       asm_exc_coprocessor_error),          // 16: #MF
    INTG(X86_TRAP_AC,       asm_exc_alignment_check),            // 17: #AC
    INTG(X86_TRAP_XF,       asm_exc_simd_coprocessor_error),     // 19: #XF

#ifdef CONFIG_X86_32
    TSKG(X86_TRAP_DF,       GDT_ENTRY_DOUBLEFAULT_TSS),          // 8: #DF (TSS)
#else
    ISTG(X86_TRAP_DF,       asm_exc_double_fault, IST_INDEX_DF), // 8: #DF (IST)
#endif
    ISTG(X86_TRAP_DB,       asm_exc_debug, IST_INDEX_DB),        // 1: #DB (IST)

#ifdef CONFIG_X86_MCE
    ISTG(X86_TRAP_MC,       asm_exc_machine_check, IST_INDEX_MCE), // 18: #MC (IST)
#endif

#ifdef CONFIG_X86_CET
    INTG(X86_TRAP_CP,       asm_exc_control_protection),         // 21: #CP
#endif

#ifdef CONFIG_AMD_MEM_ENCRYPT
    ISTG(X86_TRAP_VC,       asm_exc_vmm_communication, IST_INDEX_VC), // 29: #VC (IST)
#endif

    SYSG(X86_TRAP_OF,       asm_exc_overflow),                   // 4: #OF
};

void __init idt_setup_traps(void)
{
    idt_setup_from_table(idt_table, def_idts, ARRAY_SIZE(def_idts), true);

    if (ia32_enabled())
        idt_setup_from_table(idt_table, ia32_idt, ARRAY_SIZE(ia32_idt), true);
}
```

### 特点

| 特性 | 支持 | 说明 |
|------|------|------|
| **依赖** | ✅ 完整 | 所有内核功能可用 |
| **IST** | ✅ 是 | 关键异常使用专用栈 |
| **#PF 处理** | ✅ 完整 | 支持 COW、swap、demand paging |
| **调试** | ✅ 完整 | kprobes、perf、ftrace 等 |
| **用户态** | ✅ 是 | 可以处理用户空间异常 |
| **信号** | ✅ 是 | 可以发送 SIGSEGV、SIGILL 等 |
| **诊断** | ✅ 完整 | oops 报告、stack trace |

### IST 使用情况

| 向量 | 异常名 | IST 索引 | 原因 |
|------|--------|----------|------|
| 1 | #DB (Debug) | IST_INDEX_DB | 避免递归调试异常 |
| 2 | #NMI | IST_INDEX_NMI | 不可屏蔽，需要独立栈 |
| 8 | #DF (Double Fault) | IST_INDEX_DF | 栈溢出时的最后防线 |
| 18 | #MC (Machine Check) | IST_INDEX_MCE | 硬件错误，关键处理 |
| 29 | #VC (VMM Comm) | IST_INDEX_VC | 虚拟化环境，避免嵌套 |

---

## 5. 演进时间线

```
启动时间轴                    向量 0-31 的处理程序                      特性
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
启动最早期
  ↓
reset_early_page_tables()     （页表准备）
  ↓
x86_64_start_kernel()
  ├─ kasan_early_init()
  ├─ __native_tlb_flush_global()
  ↓
idt_setup_early_handler()     第 1 代：Emergency Handlers
  ├─ 向量 0-31                → early_idt_handler_array[i]           无依赖
  │                           → early_idt_handler_common              无 IST
  │                           → do_early_exception                    极简功能
  └─ load_idt()
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ↓
tdx_early_init()
copy_bootdata(__va(real_mode_data))
  ↓
x86_64_start_reservations()
  ↓
start_kernel()
  ├─ setup_arch()
  ├─ setup_per_cpu_areas()
  ├─ build_all_zonelists()
  ↓
trap_init()
  ↓
idt_setup_early_traps()       第 2 代：Transitional Handlers (部分)
  ├─ 向量 1                   → asm_exc_debug                        部分功能
  ├─ 向量 3                   → asm_exc_int3                         仍无 IST
  ├─ 向量 20                  → asm_exc_virtualization_exception
  └─ 其他向量                 → (仍使用第 1 代)
  ↓
idt_setup_early_pf()          第 2 代：Transitional Handlers (x86-64)
  └─ 向量 14 (x86-64)         → asm_exc_page_fault
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ↓
cpu_init()                    TSS/IST 初始化完成！
  ├─ load_sp0()
  ├─ load_TR_desc()
  └─ IST 栈设置
  ↓
idt_setup_traps()             第 3 代：Production Handlers (完全覆盖)
  ├─ 向量 0                   → asm_exc_divide_error                 完整功能
  ├─ 向量 1                   → asm_exc_debug (IST)                  支持 IST
  ├─ 向量 2                   → asm_exc_nmi (IST)                    完整诊断
  ├─ 向量 8                   → asm_exc_double_fault (IST)
  ├─ 向量 13                  → asm_exc_general_protection
  ├─ 向量 14                  → asm_exc_page_fault
  ├─ ...                      → ...
  └─ 向量 31                  → (最后一个异常)
  ↓
idt_setup_apic_and_irq_gates()  设置 IRQ 和 APIC 向量
  ├─ 向量 32-234              → IRQ 处理程序
  └─ 向量 235-255             → APIC 系统向量
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
后续运行                      第 3 代：Production Handlers              不再变化
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 6. 对比分析：以 #PF 为例

### 第 1 代：do_early_exception()

**源代码**：`arch/x86/kernel/head64.c`

```c
void __init do_early_exception(struct pt_regs *regs, int trapnr)
{
    if (trapnr == X86_TRAP_PF &&
        early_make_pgtable(native_read_cr2()))
        return;

    // 其他情况会 panic
    early_fixup_exception(regs, trapnr);
}
```

**功能**：
- ✅ 动态建立页表（early_make_pgtable）
  - 读取 CR2（缺页地址）
  - 分配页表页
  - 建立 2MB 大页映射
- ❌ 不处理用户空间缺页
- ❌ 不支持按需分配（demand paging）
- ❌ 不支持写时复制（COW）
- ❌ 不支持 swap
- ❌ 没有详细的错误报告

**适用场景**：
- 内核映射阶段的缺页
- KASAN 访问影子内存的缺页
- 内核代码段/数据段的初始映射

### 第 3 代：exc_page_fault()

**源代码**：`arch/x86/mm/fault.c`

```c
DEFINE_IDTENTRY_RAW_ERRORCODE(exc_page_fault)
{
    unsigned long address = read_cr2();
    unsigned long error_code = regs->orig_ax;

    handle_page_fault(regs, error_code, address);
}

static void handle_page_fault(struct pt_regs *regs,
                               unsigned long error_code,
                               unsigned long address)
{
    struct vm_area_struct *vma;
    struct task_struct *tsk = current;
    struct mm_struct *mm = tsk->mm;

    // 1. 检查异常来源
    if (unlikely(fault_in_kernel_space(address))) {
        // 内核空间缺页
        do_kern_addr_fault(regs, error_code, address);
    } else {
        // 用户空间缺页
        do_user_addr_fault(regs, error_code, address);
    }
}
```

**功能**：
- ✅ **用户空间**：
  - 查找 VMA（虚拟内存区域）
  - 检查访问权限
  - 按需分配页面（demand paging）
  - 写时复制（COW）
  - Swap in（从交换空间读取）
  - 文件映射（mmap）
  - 发送 SIGSEGV 信号（非法访问）

- ✅ **内核空间**：
  - vmalloc 区域的缺页处理
  - 内核模块加载的缺页
  - kprobes、ftrace 的缺页
  - 异常表查找（exception table）
  - 详细的 oops 报告

- ✅ **性能优化**：
  - TLB 管理
  - 大页（Huge Pages）支持
  - NUMA 优化
  - 缓存行对齐

- ✅ **调试支持**：
  - 详细的栈追踪（stack trace）
  - 寄存器状态打印
  - 代码上下文（code context）
  - 符号解析（symbol resolution）

### 对比表

| 特性 | Emergency (第 1 代) | Production (第 3 代) |
|------|-------------------|---------------------|
| **代码行数** | ~20 行 | ~2000+ 行 |
| **动态建立页表** | ✅ 是 | ✅ 是 |
| **用户空间缺页** | ❌ 否 | ✅ 是 |
| **Demand Paging** | ❌ 否 | ✅ 是 |
| **COW** | ❌ 否 | ✅ 是 |
| **Swap** | ❌ 否 | ✅ 是 |
| **文件映射** | ❌ 否 | ✅ 是 |
| **信号发送** | ❌ 否 | ✅ 是 (SIGSEGV) |
| **异常表** | ✅ 简单 | ✅ 完整 |
| **Oops 报告** | ❌ 否 | ✅ 是 |
| **栈追踪** | ❌ 否 | ✅ 是 |
| **TLB 管理** | ❌ 否 | ✅ 是 |
| **NUMA 优化** | ❌ 否 | ✅ 是 |

---

## 7. early_idt_handler_common 的命运

### 被完全废弃

```c
// early_idt_handler_common 只在启动早期使用
// trap_init() 完成后，idt_table 中所有引用都被替换

// 但代码仍然存在于 .text 段（未被删除）
// 原因：
// 1. 删除会增加复杂性（链接脚本、符号管理）
// 2. 代码很小（几百字节），不值得删除
// 3. 可能在特殊调试场景下有用
```

### 验证方法

**方法 1：查看运行时的 idt_table**

```bash
# 在运行的系统上
$ sudo cat /proc/interrupts
           CPU0       CPU1
  0:        123          0   IO-APIC   2-edge      timer
  1:          9          0   IO-APIC   1-edge      i8042
...

# 或者用 gdb 调试内核
(gdb) x/256xg idt_table
# 你会看到所有向量都指向 asm_exc_* 函数
# 没有一个指向 early_idt_handler_array
```

**方法 2：查看符号表**

```bash
$ readelf -s vmlinux | grep early_idt_handler
  1234: ffffffff81002a00   320 NOTYPE  GLOBAL DEFAULT    1 early_idt_handler_array
  1235: ffffffff81002ac0    80 NOTYPE  LOCAL  DEFAULT    1 early_idt_handler_common

# 符号仍然存在，但不再被 idt_table 引用
```

**方法 3：反汇编验证**

```bash
$ objdump -d vmlinux | grep -A 5 "^ffffffff81002a00"
ffffffff81002a00 <early_idt_handler_array>:
ffffffff81002a00:   f3 0f 1e fa             endbr64
ffffffff81002a04:   6a 00                   pushq  $0x0
...

# 代码存在，但不再被使用
```

### 内存占用

```
early_idt_handler_array:  约 320 字节 (32 个桩 × 10 字节)
early_idt_handler_common: 约 80 字节

总计：约 400 字节（在 .text 段，只读）
```

---

## 8. Chicken-and-Egg 问题

### 问题描述

```
循环依赖：
┌──────────────────────────────────────────────────────┐
│  生产级异常处理需要：                                 │
│  ├─ 完整的内存管理                                   │
│  │  └─ 需要异常处理（#PF 缺页）                      │
│  │     └─ 需要内存管理（分配页表页）← 循环！          │
│  │                                                   │
│  ├─ 进程管理                                         │
│  │  └─ 需要内存分配                                  │
│  │     └─ 需要异常处理                               │
│  │                                                   │
│  └─ 中断栈表（IST）                                  │
│     └─ 需要 TSS 初始化                               │
│        └─ 需要 per-CPU 变量                          │
│           └─ 需要内存分配                            │
└──────────────────────────────────────────────────────┘
```

### 解决方案：分层初始化

```
层次 1：最小依赖（Emergency）
  ├─ 功能：只处理 #PF 的页表建立
  ├─ 依赖：无（直接操作页表）
  └─ 限制：不能处理用户空间、不能 swap

层次 2：部分功能（Transitional）
  ├─ 功能：可以使用基本内存管理
  ├─ 依赖：memblock、早期页表
  └─ 限制：仍然不能使用 IST

层次 3：完整功能（Production）
  ├─ 功能：所有异常处理特性
  ├─ 依赖：完整内存管理、TSS/IST、进程管理
  └─ 限制：无
```

### 关键设计原则

1. **最小化早期依赖**
   ```c
   // early_make_pgtable() 不依赖任何子系统
   // 直接操作页表数据结构
   int __init early_make_pgtable(unsigned long address)
   {
       // 不调用 kmalloc、vmalloc 等
       // 直接从 _brk_end 分配页表页
       pmd_t *pmd = fixup_pointer(level2_kernel_pgt, physaddr);
       // ...
   }
   ```

2. **渐进式功能增强**
   ```
   阶段 1: 能处理内核缺页
   阶段 2: 能处理调试异常
   阶段 3: 能处理所有异常
   ```

3. **延迟 IST 使用**
   ```
   问题：IST 需要 TSS，TSS 需要 per-CPU，per-CPU 需要内存分配
   解决：早期不用 IST，cpu_init() 后才启用
   ```

---

## 总结

### 三代处理程序对比

| 对比项 | Emergency | Transitional | Production |
|--------|-----------|--------------|------------|
| **时间** | 最早期 | trap_init 开始 | cpu_init 后 |
| **覆盖范围** | 向量 0-31 | 部分向量 (1,3,14,20) | 全部向量 0-31 |
| **IST 支持** | ❌ 否 | ❌ 否 | ✅ 是 |
| **代码量** | ~100 行 | ~500 行 | ~5000+ 行 |
| **功能** | 极简 | 部分 | 完整 |
| **依赖** | 无 | 部分 | 完整 |
| **调试** | 无 | 基本 | 完整 |
| **性能** | 低 | 中 | 高 |

### 关键要点

1. ✅ **early_idt_handler_common 会被完全替换**
   - trap_init() 中被 asm_exc_* 系列函数替换
   - 代码仍存在，但不再被引用

2. ✅ **do_early_exception 只是临时的**
   - 只处理 #PF、#VC、#VE 三类异常
   - 其他异常基本都 panic
   - 被 exc_page_fault 等完整处理程序替换

3. ✅ **三代演进是必需的**
   - 解决 Chicken-and-Egg 问题
   - 渐进式初始化，降低复杂度
   - 确保启动早期的异常能被处理

4. ✅ **IST 是关键区别**
   - 早期无法使用（TSS 未初始化）
   - 生产级必须使用（避免栈溢出、递归异常）

---

## 延伸阅读

- [IDT_SETUP_EARLY_HANDLER_DETAILED_ANALYSIS.md](./IDT_SETUP_EARLY_HANDLER_DETAILED_ANALYSIS.md) - 主流程文档
- [IDT_EXCEPTION_HANDLING_DETAILS.md](./IDT_EXCEPTION_HANDLING_DETAILS.md) - 异常处理详解（含 do_early_exception 功能分析）
- [IDT_COMPLETE_VECTOR_TABLE.md](./IDT_COMPLETE_VECTOR_TABLE.md) - 完整向量表
- [LINUX_KERNEL_IDT_EVOLUTION.md](./LINUX_KERNEL_IDT_EVOLUTION.md) - IDT 表整体演进
- [X86_64_TSS_AND_IST.md](./X86_64_TSS_AND_IST.md) - TSS 和 IST 详解

---

**最后更新**：2026-02-18
**作者**：Linux 内核启动文档项目
