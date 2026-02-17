# idt_setup_early_handler() 函数详细分析

**版本**: 1.0
**日期**: 2026-02-17
**作者**: Linux 内核启动文档项目

> 📚 **文档导航**: [返回总索引](DOCUMENT_INDEX.md) | [IDT 演进](LINUX_KERNEL_IDT_EVOLUTION.md) | [内核启动](LINUX_KERNEL_INIT.md)

---

## 目录

1. [函数概览](#1-函数概览)
2. [数据结构详解](#2-数据结构详解)
3. [逐行代码分析](#3-逐行代码分析)
4. [early_idt_handler_array 的实现](#4-early_idt_handler_array-的实现)
5. [set_intr_gate() 的工作流程](#5-set_intr_gate-的工作流程)
6. [load_idt() 的底层实现](#6-load_idt-的底层实现)
7. [完整的执行流程](#7-完整的执行流程)
8. [为什么是 32 个向量？](#8-为什么是-32-个向量)

---

## 1. 函数概览

### 1.1 函数签名与位置

**源代码位置**：`arch/x86/kernel/idt.c:317-331`

```c
/**
 * idt_setup_early_handler - Initializes the idt table with early handlers
 */
void __init idt_setup_early_handler(void)
{
	int i;

	for (i = 0; i < NUM_EXCEPTION_VECTORS; i++)
		set_intr_gate(i, early_idt_handler_array[i]);
#ifdef CONFIG_X86_32
	for ( ; i < NR_VECTORS; i++)
		set_intr_gate(i, early_ignore_irq);
#endif
	load_idt(&idt_descr);
}
```

### 1.2 调用时机

在 `x86_64_start_kernel()` 中被调用（`arch/x86/kernel/head64.c:273`）：

```c
asmlinkage __visible void __init __noreturn x86_64_start_kernel(char *real_mode_data)
{
    // ... 前置步骤 ...
    kasan_early_init();              // ← 必须先初始化 KASAN

    __native_tlb_flush_global(...);

    idt_setup_early_handler();       // ← 在这里调用

    tdx_early_init();
    // ... 后续步骤 ...
}
```

### 1.3 函数的核心作用

1. **切换 IDT 表**：从临时的 `bringup_idt_table` 切换到正式的 `idt_table`
2. **填充异常处理程序**：为前 32 个 CPU 异常向量设置统一的早期处理函数
3. **加载新 IDT**：通过 `lidt` 指令使新的 IDT 生效

### 1.4 调用链概览（如何连接到 idt_table）

**关键问题**：`idt_setup_early_handler()` 中的 `set_intr_gate()` 如何将数据写入 `idt_table`？

**完整调用链**：

```
idt_setup_early_handler()
    │
    ├─ 步骤 1：填充 IDT 表
    │     │
    │     └─ for (i = 0; i < 32; i++)
    │           set_intr_gate(i, early_idt_handler_array[i])
    │             │
    │             ├─ 创建临时的 idt_data 结构
    │             │    └─ init_idt_data(&data, i, addr)
    │             │         └─ data.vector = i
    │             │         └─ data.addr = early_idt_handler_array[i]
    │             │         └─ data.bits.type = GATE_INTERRUPT (0xE)
    │             │         └─ data.bits.ist = 0
    │             │         └─ data.bits.dpl = 0
    │             │         └─ data.bits.p = 1
    │             │
    │             └─ idt_setup_from_table(idt_table, &data, 1, false)
    │                   │
    │                   ├─ idt_init_desc(&desc, &data)
    │                   │    └─ 将 idt_data 转换为 16 字节的 gate_desc
    │                   │         └─ desc.offset_low = addr[15:0]
    │                   │         └─ desc.offset_middle = addr[31:16]
    │                   │         └─ desc.offset_high = addr[63:32]
    │                   │         └─ desc.segment = __KERNEL_CS
    │                   │         └─ desc.bits = data.bits
    │                   │
    │                   └─ write_idt_entry(idt_table, i, &desc)
    │                        └─ idt_table[i] = desc  ← 写入全局 idt_table！
    │
    └─ 步骤 2：加载 IDT 表
          │
          └─ load_idt(&idt_descr)
                │
                └─ lidt指令：将 idt_descr 中的地址和大小加载到 IDTR
                     └─ IDTR.base = idt_descr.address = &idt_table  ← 指向 idt_table！
                     └─ IDTR.limit = idt_descr.size = 4095
```

**关键连接点**：

1. **`idt_table` 是全局静态数组**（arch/x86/kernel/idt.c:173）
   - 存储 256 个 16 字节的门描述符
   - 初始为空（BSS 段，全 0）

2. **`idt_descr` 结构指向 `idt_table`**（arch/x86/kernel/idt.c:175-178）
   - `idt_descr.address = (unsigned long) idt_table`
   - `idt_descr.size = 4095`（4096 - 1）

3. **`set_intr_gate()` 通过多层调用最终写入 `idt_table`**
   - `set_intr_gate()` → `idt_setup_from_table()` → `write_idt_entry()` → `idt_table[i] = desc`

4. **`load_idt()` 将 `idt_table` 的地址加载到 IDTR**
   - CPU 的 IDTR 寄存器现在指向 `idt_table`
   - 后续所有中断/异常都会查找 `idt_table`

**为什么需要这么多层？**

- **类型安全**：idt_data（高层抽象）→ gate_desc（底层硬件格式）
- **灵活性**：可以批量初始化（传入数组）
- **可维护性**：将复杂的位操作封装在函数中

---

## 2. 数据结构详解

**注意**：现在你应该理解为什么这一节要详细介绍 `idt_table`、`idt_descr` 等结构——它们是上述调用链中的核心数据！

### 2.1 idt_table - 运行时 IDT 表

**定义**（`arch/x86/kernel/idt.c:173`）：

```c
/* Must be page-aligned because the real IDT is used in the cpu entry area */
static gate_desc idt_table[IDT_ENTRIES] __page_aligned_bss;
```

**详细信息**：

| 属性 | 值/说明 |
|------|---------|
| **类型** | `gate_desc` 数组 |
| **元素数量** | `IDT_ENTRIES` = 256 |
| **大小** | 256 × 16 字节 = 4096 字节（1 个页面） |
| **对齐** | 页对齐（4KB 边界） |
| **初始状态** | BSS 段，初始值全为 0 |
| **属性** | `__page_aligned_bss` - 页对齐的 BSS 段 |

**gate_desc 结构**（`arch/x86/include/asm/desc_defs.h:79-91`）：

```c
struct gate_desc {
	u16		offset_low;      // 处理程序地址的低 16 位
	u16		segment;         // 代码段选择子（__KERNEL_CS）
	struct idt_bits	bits;    // 控制位（IST、DPL、Type、P）
	u16		offset_middle;   // 处理程序地址的中间 16 位
	u32		offset_high;     // 处理程序地址的高 32 位
	u32		reserved;        // 保留，必须为 0
} __attribute__((packed));
```

**idt_bits 结构**：

```c
struct idt_bits {
	u16		ist	: 3,    // Interrupt Stack Table 索引（0-7）
			zero	: 5,    // 必须为 0
			type	: 5,    // 门类型（Interrupt/Trap/Task）
			dpl	: 2,    // Descriptor Privilege Level（0 或 3）
			p	: 1;    // Present 位（必须为 1）
} __attribute__((packed));
```

**内存布局示例**（单个 gate_desc，共 16 字节）：

```
偏移量 | 大小 | 字段               | 说明
-------|------|--------------------|-----------------------------------------
+0     | 2B   | offset_low         | 处理程序地址 [15:0]
+2     | 2B   | segment            | __KERNEL_CS = 0x0010
+4     | 2B   | bits (IST/Type/DPL/P) | 控制位
+6     | 2B   | offset_middle      | 处理程序地址 [31:16]
+8     | 4B   | offset_high        | 处理程序地址 [63:32]
+12    | 4B   | reserved           | 必须为 0
```

### 2.2 idt_descr - IDT 描述符

**定义**（`arch/x86/kernel/idt.c:175-178`）：

```c
static struct desc_ptr idt_descr __ro_after_init = {
	.size		= IDT_TABLE_SIZE - 1,
	.address	= (unsigned long) idt_table,
};
```

**desc_ptr 结构**（`arch/x86/include/asm/desc_defs.h:23-26`）：

```c
struct desc_ptr {
	unsigned short size;        // IDT 表大小 - 1（字节数）
	unsigned long address;      // IDT 表的线性地址
} __attribute__((packed));
```

**实际值**：

| 字段 | 值 | 说明 |
|------|-----|------|
| `size` | `IDT_TABLE_SIZE - 1` = 4096 - 1 = **4095** | IDT 表大小 - 1 |
| `address` | `(unsigned long) idt_table` | idt_table 数组的地址 |

**为什么 size 是 4095 而不是 4096？**

这是 x86 架构的规定：
- `LIDT` 指令需要的是**表的字节数减 1**
- 因为表从偏移量 0 开始，实际能访问到的最大偏移是 4095
- 256 个条目 × 16 字节/条目 = 4096 字节
- IDTR.limit = 4096 - 1 = 4095

**`__ro_after_init` 属性**：
- 初始化后设置为只读
- 防止运行时被恶意修改
- 安全防护措施

### 2.3 early_idt_handler_array - 早期 IDT 处理程序数组

**定义**（`arch/x86/kernel/head_64.S:488-505`）：

```asm
	__INIT
SYM_CODE_START(early_idt_handler_array)
	i = 0
	.rept NUM_EXCEPTION_VECTORS      # 重复 32 次
	.if ((EXCEPTION_ERRCODE_MASK >> i) & 1) == 0
		UNWIND_HINT_IRET_REGS
		ENDBR
		pushq $0	# Dummy error code, to make stack frame uniform
	.else
		UNWIND_HINT_IRET_REGS offset=8
		ENDBR
	.endif
	pushq $i		# 72(%rsp) Vector number
	jmp early_idt_handler_common
	UNWIND_HINT_IRET_REGS
	i = i + 1
	.fill early_idt_handler_array + i*EARLY_IDT_HANDLER_SIZE - ., 1, 0xcc
	.endr
SYM_CODE_END(early_idt_handler_array)
	ANNOTATE_NOENDBR // early_idt_handler_array[NUM_EXCEPTION_VECTORS]
```

**工作原理**：
1. 使用汇编宏 `.rept` 重复生成 32 个几乎相同的处理程序桩（stub）
2. 每个桩的大小固定为 `EARLY_IDT_HANDLER_SIZE`（通常是 10 或 12 字节）
3. 每个桩做三件事：
   - 如果异常不自动压入错误码，则手动 `pushq $0`（统一栈帧）
   - 压入异常向量号 `pushq $i`
   - 跳转到公共处理程序 `jmp early_idt_handler_common`

**EXCEPTION_ERRCODE_MASK**（`arch/x86/include/asm/trapnr.h`）：

这是一个 32 位掩码，指示哪些异常会自动压入错误码：

```c
/*
 * Bit 14 = 0x4000, 3 = 0x0008, 1 = 0x0002, 0 = 0x0001
 * DF = 8, TS = 10, NP = 11, SS = 12, GP = 13, PF = 14, AC = 17
 */
#define EXCEPTION_ERRCODE_MASK  0x00027d00
```

**二进制分解**：

```
向量号 | 十进制 | 异常名称 | 错误码？ | MASK 中对应位
-------|--------|---------|---------|-------------
0      | 0      | #DE     | 否      | 0
1      | 1      | #DB     | 否      | 0
...    | ...    | ...     | ...     | ...
8      | 8      | #DF     | 是      | 1  (bit 8)
10     | 10     | #TS     | 是      | 1  (bit 10)
11     | 11     | #NP     | 是      | 1  (bit 11)
12     | 12     | #SS     | 是      | 1  (bit 12)
13     | 13     | #GP     | 是      | 1  (bit 13)
14     | 14     | #PF     | 是      | 1  (bit 14)
17     | 17     | #AC     | 是      | 1  (bit 17)
```

**示例：向量 0（#DE - Divide Error）的桩**：

```asm
# early_idt_handler_array[0]:
	ENDBR                   # 3 字节（如果启用 CET）
	pushq $0                # 2 字节（Dummy error code）
	pushq $0                # 2 字节（Vector number）
	jmp early_idt_handler_common  # 5 字节
	# 总计：10-12 字节
```

**示例：向量 14（#PF - Page Fault）的桩**：

```asm
# early_idt_handler_array[14]:
	ENDBR                   # 3 字节
	# 不压入 dummy error code（CPU 会自动压入）
	pushq $14               # 2 字节（Vector number）
	jmp early_idt_handler_common  # 5 字节
	# 总计：10 字节
```

**数组布局**：

```
地址                              | 内容
----------------------------------|----------------------------------
early_idt_handler_array[0]        | 向量 0 的桩（10-12 字节）
early_idt_handler_array[1]        | 向量 1 的桩（10-12 字节）
...                               | ...
early_idt_handler_array[31]       | 向量 31 的桩（10-12 字节）
```

**关键常量**：

```c
#define NUM_EXCEPTION_VECTORS  32  // CPU 异常向量数量
#define EARLY_IDT_HANDLER_SIZE 10  // 或 12，取决于 CET
```

---

## 3. 逐行代码分析

### 3.1 函数声明

```c
void __init idt_setup_early_handler(void)
```

**`__init` 修饰符**：
- 表示这是初始化代码，只在启动时运行一次
- 链接时放入 `.init.text` section
- 启动完成后，整个 `.init` section 会被释放，节省内存

### 3.2 循环变量声明

```c
int i;
```

**用途**：
- 循环计数器
- 作为异常向量号（0-31）
- 作为 `idt_table` 数组的索引

### 3.3 主循环：设置 32 个异常向量

```c
for (i = 0; i < NUM_EXCEPTION_VECTORS; i++)
	set_intr_gate(i, early_idt_handler_array[i]);
```

**逐步分解**：

#### 第 1 次迭代（i = 0）

```c
set_intr_gate(0, early_idt_handler_array[0]);
```

**含义**：
- 向量号：`0`（#DE - Divide Error）
- 处理程序地址：`early_idt_handler_array[0]`（第 1 个桩的地址）
- 操作：在 `idt_table[0]` 中写入一个中断门描述符

**实际效果**：

```c
// 伪代码表示
idt_table[0].offset_low    = (early_idt_handler_array[0] & 0xFFFF);
idt_table[0].offset_middle = ((early_idt_handler_array[0] >> 16) & 0xFFFF);
idt_table[0].offset_high   = (early_idt_handler_array[0] >> 32);
idt_table[0].segment       = __KERNEL_CS;  // 0x0010
idt_table[0].bits.type     = GATE_INTERRUPT;  // 0xE
idt_table[0].bits.dpl      = DPL0;  // 0
idt_table[0].bits.p        = 1;  // Present
idt_table[0].bits.ist      = 0;  // 不使用 IST
```

#### 第 2 次迭代（i = 1）

```c
set_intr_gate(1, early_idt_handler_array[1]);
```

设置 `idt_table[1]` 对应 `#DB`（Debug Exception）。

#### ...以此类推，直到 i = 31

```c
set_intr_gate(31, early_idt_handler_array[31]);
```

设置 `idt_table[31]`（保留的异常向量）。

**循环结束后的状态**：

```
idt_table[0]  → early_idt_handler_array[0]  (#DE)
idt_table[1]  → early_idt_handler_array[1]  (#DB)
idt_table[2]  → early_idt_handler_array[2]  (NMI)
...
idt_table[13] → early_idt_handler_array[13] (#GP)
idt_table[14] → early_idt_handler_array[14] (#PF)
...
idt_table[31] → early_idt_handler_array[31] (Reserved)
idt_table[32] → 0（尚未设置）
...
idt_table[255] → 0（尚未设置）
```

### 3.4 32 位系统的额外处理

```c
#ifdef CONFIG_X86_32
for ( ; i < NR_VECTORS; i++)
	set_intr_gate(i, early_ignore_irq);
#endif
```

**仅在 32 位系统（x86-32）上编译**：
- `NR_VECTORS` = 256
- 将剩余的向量（32-255）都指向 `early_ignore_irq`

**early_ignore_irq**（`arch/x86/kernel/head_32.S`）：
```asm
early_ignore_irq:
	cld
	pushl %eax
	pushl %edx
	movl $0x80000000, %eax   # ACK IRQ
	outl %eax, $0x80
	popl %edx
	popl %eax
	iret
```

**为什么 64 位系统不需要？**
- 64 位系统在此阶段**硬件中断仍然禁用**
- 不会收到 IRQ 32-255
- 这些向量会在后续的 `idt_setup_apic_and_irq_gates()` 中填充

### 3.5 加载新的 IDT

```c
load_idt(&idt_descr);
```

**作用**：
- 执行 `lidt` 指令
- 使 CPU 从此刻开始使用 `idt_table`
- 废弃之前的 `bringup_idt_table`

**详细流程**（见第 6 节）。

---

## 4. early_idt_handler_array 的实现

### 4.1 公共处理程序：early_idt_handler_common

**源代码位置**：`arch/x86/kernel/head_64.S:508-542`

```asm
SYM_CODE_START_LOCAL(early_idt_handler_common)
	UNWIND_HINT_IRET_REGS offset=16
	/*
	 * The stack is the hardware frame, an error code or zero, and the
	 * vector number.
	 */
	cld

	incl early_recursion_flag(%rip)

	/* The vector number is currently in the pt_regs->di slot. */
	pushq %rsi				/* pt_regs->si */
	movq 8(%rsp), %rsi			/* RSI = vector number */
	movq %rdi, 8(%rsp)			/* pt_regs->di = RDI */
	pushq %rdx				/* pt_regs->dx */
	pushq %rcx				/* pt_regs->cx */
	pushq %rax				/* pt_regs->ax */
	pushq %r8				/* pt_regs->r8 */
	pushq %r9				/* pt_regs->r9 */
	pushq %r10				/* pt_regs->r10 */
	pushq %r11				/* pt_regs->r11 */
	pushq %rbx				/* pt_regs->bx */
	pushq %rbp				/* pt_regs->bp */
	pushq %r12				/* pt_regs->r12 */
	pushq %r13				/* pt_regs->r13 */
	pushq %r14				/* pt_regs->r14 */
	pushq %r15				/* pt_regs->r15 */
	UNWIND_HINT_REGS

	movq %rsp,%rdi		/* RDI = pt_regs; RSI is already trapnr */
	call do_early_exception

	decl early_recursion_flag(%rip)
	jmp restore_regs_and_return_to_kernel
SYM_CODE_END(early_idt_handler_common)
```

### 4.2 栈帧布局

**当 CPU 触发异常时**（以 #PF 为例）：

```
步骤 1：CPU 自动压栈（异常发生时）
┌─────────────────────────┐ ← RSP（异常发生前）
│  SS                      │
│  RSP                     │
│  RFLAGS                  │
│  CS                      │
│  RIP                     │
│  Error Code (for #PF)    │ ← RSP（进入 IDT 处理程序后）
└─────────────────────────┘

步骤 2：early_idt_handler_array[14] 压栈
┌─────────────────────────┐
│  ...                     │
│  Error Code              │
│  Vector Number (14)      │ ← RSP（进入 early_idt_handler_common 后）
└─────────────────────────┘

步骤 3：early_idt_handler_common 压栈
┌─────────────────────────┐
│  ...                     │
│  Error Code              │
│  Vector Number (14)      │
│  RSI                     │
│  RDI                     │
│  RDX                     │
│  RCX                     │
│  RAX                     │
│  R8                      │
│  R9                      │
│  R10                     │
│  R11                     │
│  RBX                     │
│  RBP                     │
│  R12                     │
│  R13                     │
│  R14                     │
│  R15                     │ ← RSP（调用 do_early_exception 前）
└─────────────────────────┘
  ↑
  pt_regs 结构
```

### 4.3 调用 do_early_exception

**函数签名**（`arch/x86/kernel/head64.c:156-170`）：

```c
void __init do_early_exception(struct pt_regs *regs, int trapnr)
{
	if (trapnr == X86_TRAP_PF &&
	    early_make_pgtable(native_read_cr2()))
		return;

	if (IS_ENABLED(CONFIG_AMD_MEM_ENCRYPT) &&
	    trapnr == X86_TRAP_VC && handle_vc_boot_ghcb(regs))
		return;

	if (trapnr == X86_TRAP_VE && tdx_early_handle_ve(regs))
		return;

	early_fixup_exception(regs, trapnr);
}
```

**参数**：
- `RDI = pt_regs`（指向栈上的寄存器快照）
- `RSI = trapnr`（异常向量号）

**关键处理**：
1. **#PF（缺页异常）**：调用 `early_make_pgtable()` 动态建立页表
2. **#VC（虚拟化异常）**：AMD SEV 特定处理
3. **#VE（Intel TDX 异常）**：Intel TDX 特定处理
4. **其他异常**：调用 `early_fixup_exception()` 尝试修复

---

## 5. set_intr_gate() 的工作流程

### 5.1 函数定义

**源代码位置**：`arch/x86/kernel/idt.c:206-213`

```c
static __init void set_intr_gate(unsigned int n, const void *addr)
{
	struct idt_data data;

	init_idt_data(&data, n, addr);

	idt_setup_from_table(idt_table, &data, 1, false);
}
```

### 5.2 init_idt_data() - 初始化 idt_data 结构

**idt_data 结构**（`arch/x86/include/asm/desc.h`）：

```c
struct idt_data {
	unsigned int	vector;      // 向量号（0-255）
	unsigned int	segment;     // 代码段选择子
	struct idt_bits	bits;        // 控制位
	const void	*addr;       // 处理程序地址
};
```

**init_idt_data() 宏**：

```c
#define init_idt_data(data, n, addr)			\
do {							\
	(data)->vector	= (n);				\
	(data)->bits.ist = DEFAULT_STACK;		\
	(data)->bits.type = GATE_INTERRUPT;		\
	(data)->bits.dpl = DPL0;			\
	(data)->bits.p	= 1;				\
	(data)->addr	= (addr);			\
	(data)->segment	= __KERNEL_CS;			\
} while (0)
```

**示例：设置向量 14（#PF）**

```c
// 调用：set_intr_gate(14, early_idt_handler_array[14]);

// 步骤 1：初始化 idt_data
struct idt_data data;
init_idt_data(&data, 14, early_idt_handler_array[14]);

// 展开后：
data.vector   = 14;
data.bits.ist = 0;                              // 不使用 IST
data.bits.type = GATE_INTERRUPT;                // 0xE
data.bits.dpl  = DPL0;                          // 0（只能从 Ring 0 触发）
data.bits.p    = 1;                             // Present
data.addr      = early_idt_handler_array[14];   // 处理程序地址
data.segment   = __KERNEL_CS;                   // 0x0010
```

### 5.3 idt_setup_from_table() - 写入 IDT 表

**源代码位置**：`arch/x86/kernel/idt.c:193-204`

```c
static __init void
idt_setup_from_table(gate_desc *idt, const struct idt_data *t, int size, bool sys)
{
	gate_desc desc;

	for (; size > 0; t++, size--) {
		idt_init_desc(&desc, t);
		write_idt_entry(idt, t->vector, &desc);
		if (sys)
			set_bit(t->vector, system_vectors);
	}
}
```

**参数**：
- `idt` = `idt_table`（目标 IDT 表）
- `t` = `&data`（idt_data 结构指针）
- `size` = 1（只写入 1 个条目）
- `sys` = `false`（不是系统门，DPL = 0）

**步骤 1：idt_init_desc() - 构建门描述符**

```c
static inline void idt_init_desc(gate_desc *gate, const struct idt_data *d)
{
	unsigned long addr = (unsigned long) d->addr;

	gate->offset_low	= (u16) addr;
	gate->segment		= (u16) d->segment;
	gate->bits		= d->bits;
	gate->offset_middle	= (u16) (addr >> 16);
	gate->offset_high	= (u32) (addr >> 32);
	gate->reserved		= 0;
}
```

**示例：向量 14 的门描述符**

假设 `early_idt_handler_array[14]` 的地址是 `0xffffffff81002a80`：

```c
gate_desc desc;

desc.offset_low    = 0x2a80;           // 地址 [15:0]
desc.segment       = 0x0010;           // __KERNEL_CS
desc.bits.ist      = 0;
desc.bits.type     = 0xE;              // Interrupt Gate
desc.bits.dpl      = 0;                // Ring 0 only
desc.bits.p        = 1;                // Present
desc.offset_middle = 0x8100;           // 地址 [31:16]
desc.offset_high   = 0xffffffff;       // 地址 [63:32]
desc.reserved      = 0;
```

**步骤 2：write_idt_entry() - 原子写入**

```c
static inline void write_idt_entry(gate_desc *idt, int entry, const gate_desc *gate)
{
	memcpy(&idt[entry], gate, sizeof(*gate));
}
```

**等价于**：

```c
idt_table[14] = desc;  // 原子地拷贝 16 字节
```

---

## 6. load_idt() 的底层实现

### 6.1 函数调用链

```c
load_idt(&idt_descr)
    ↓
static inline void load_idt(const struct desc_ptr *dtr)
{
	asm volatile("lidt %0"::"m" (dtr->size));
}
```

**等价的汇编代码**：

```asm
lidt (%rdi)   ; RDI = &idt_descr
```

### 6.2 lidt 指令的操作

**Intel SDM 定义**（Vol. 2A, LIDT 指令）：

> **LIDT** - Load Interrupt Descriptor Table Register
>
> **Operation**:
> ```
> IF instruction is LIDT
> THEN
>     IF OperandSize = 16
>     THEN
>         IDTR.Limit ← SRC[0:15];
>         IDTR.Base  ← SRC[16:47] AND 00FFFFFFH;
>     ELSIF OperandSize = 32
>     THEN
>         IDTR.Limit ← SRC[0:15];
>         IDTR.Base  ← SRC[16:47];
>     ELSE (* 64-bit Mode *)
>         IDTR.Limit ← SRC[0:15];
>         IDTR.Base  ← SRC[16:79];
>     FI;
> FI;
> ```

**x86-64 模式下**：

```c
// 加载前：
IDTR.limit = （未知，之前是 bringup_idt_table 的大小）
IDTR.base  = （未知，之前是 bringup_idt_table 的地址）

// 执行：lidt (&idt_descr)

// 加载后：
IDTR.limit = idt_descr.size     = 4095（0x0FFF）
IDTR.base  = idt_descr.address  = &idt_table
```

### 6.3 原子切换

**关键特性**：
- `lidt` 指令是**原子操作**
- 执行完毕后，CPU **立即使用**新的 IDT
- 从**下一条指令**开始，所有中断/异常都查询 `idt_table`

**时间点对比**：

```
时刻 T0：执行 lidt 指令之前
    CPU 使用：bringup_idt_table

时刻 T1：lidt 指令执行中
    CPU 内部更新 IDTR

时刻 T2：lidt 指令执行完毕
    CPU 使用：idt_table ← 从此刻开始！
    bringup_idt_table 被废弃，成为垃圾数据
```

---

## 7. 完整的执行流程

### 7.1 流程图

```
┌─────────────────────────────────────────────────────────────┐
│ idt_setup_early_handler() 调用                               │
└─────────────────────────────────────────────────────────────┘
                        ↓
    ┌───────────────────────────────────────────────┐
    │ for (i = 0; i < 32; i++)                      │
    │     set_intr_gate(i, early_idt_handler_array[i]) │
    └───────────────────────────────────────────────┘
                        ↓
    ┌───────────────────────────────────────────────┐
    │ i = 0: 设置向量 0 (#DE)                       │
    │   ├─ init_idt_data(&data, 0, early_idt_handler_array[0]) │
    │   │      └─ 初始化 idt_data 结构              │
    │   └─ idt_setup_from_table(idt_table, &data, 1, false) │
    │          ├─ idt_init_desc(&desc, &data)       │
    │          │      └─ 构建 gate_desc 结构        │
    │          └─ write_idt_entry(idt_table, 0, &desc) │
    │                 └─ idt_table[0] = desc        │
    └───────────────────────────────────────────────┘
                        ↓
    ┌───────────────────────────────────────────────┐
    │ i = 1: 设置向量 1 (#DB)                       │
    │   └─ idt_table[1] = ...                       │
    └───────────────────────────────────────────────┘
                        ↓
                     ... ↓ ...
                        ↓
    ┌───────────────────────────────────────────────┐
    │ i = 31: 设置向量 31 (Reserved)                │
    │   └─ idt_table[31] = ...                      │
    └───────────────────────────────────────────────┘
                        ↓
    ┌───────────────────────────────────────────────┐
    │ load_idt(&idt_descr)                          │
    │   └─ lidt (%rdi)  ; RDI = &idt_descr         │
    │          ├─ IDTR.limit = 4095                 │
    │          └─ IDTR.base = &idt_table            │
    └───────────────────────────────────────────────┘
                        ↓
    ┌───────────────────────────────────────────────┐
    │ 返回 x86_64_start_kernel()                    │
    └───────────────────────────────────────────────┘
```

### 7.2 内存变化

**执行前**（使用 bringup_idt_table）：

```
idt_table[0..255]     = 全部为 0（BSS 段）
IDTR.limit            = bringup_idt_table 的大小
IDTR.base             = &bringup_idt_table
```

**执行后**（使用 idt_table）：

```
idt_table[0]          = 指向 early_idt_handler_array[0]  (#DE)
idt_table[1]          = 指向 early_idt_handler_array[1]  (#DB)
...
idt_table[14]         = 指向 early_idt_handler_array[14] (#PF)
...
idt_table[31]         = 指向 early_idt_handler_array[31] (Reserved)
idt_table[32..255]    = 仍然为 0（尚未填充）

IDTR.limit            = 4095
IDTR.base             = &idt_table
```

---

## 8. 为什么是 32 个向量？

### 8.1 x86 架构的异常定义

**Intel SDM** 定义了 **32 个保留的异常向量**（0-31）：

| 向量号 | 助记符 | 异常名称 | 错误码？ |
|--------|--------|---------|---------|
| 0      | #DE    | Divide Error | 否 |
| 1      | #DB    | Debug Exception | 否 |
| 2      | -      | NMI Interrupt | 否 |
| 3      | #BP    | Breakpoint | 否 |
| 4      | #OF    | Overflow | 否 |
| 5      | #BR    | BOUND Range Exceeded | 否 |
| 6      | #UD    | Invalid Opcode | 否 |
| 7      | #NM    | Device Not Available | 否 |
| 8      | #DF    | Double Fault | **是**（总是 0） |
| 9      | -      | Coprocessor Segment Overrun（保留） | 否 |
| 10     | #TS    | Invalid TSS | **是** |
| 11     | #NP    | Segment Not Present | **是** |
| 12     | #SS    | Stack-Segment Fault | **是** |
| 13     | #GP    | General Protection | **是** |
| 14     | #PF    | Page Fault | **是** |
| 15     | -      | （保留） | 否 |
| 16     | #MF    | x87 FPU Error | 否 |
| 17     | #AC    | Alignment Check | **是** |
| 18     | #MC    | Machine Check | 否 |
| 19     | #XM/#XF| SIMD Floating-Point Exception | 否 |
| 20     | #VE    | Virtualization Exception | 否 |
| 21     | #CP    | Control Protection Exception | **是** |
| 22-27  | -      | （保留） | - |
| 28     | #HV    | Hypervisor Injection Exception | 否 |
| 29     | #VC    | VMM Communication Exception | **是** |
| 30     | #SX    | Security Exception | **是** |
| 31     | -      | （保留） | - |

### 8.2 NUM_EXCEPTION_VECTORS 的定义

**源代码**（`arch/x86/include/asm/irq_vectors.h`）：

```c
#define NUM_EXCEPTION_VECTORS  32
```

### 8.3 为什么只设置 32 个？

**原因 1：x86 架构规范**
- Intel SDM 明确保留向量 0-31 用于 CPU 异常
- 向量 32-255 用于外部中断和软件中断

**原因 2：启动阶段的需求**
- 此时**硬件中断仍然禁用**（`cli` 指令）
- 不会收到 IRQ（32-255）
- 只需要处理 CPU 异常（0-31）

**原因 3：避免过早初始化**
- IRQ 的处理需要 APIC、PIC 等中断控制器的初始化
- 这些在后续的 `init_IRQ()` 中完成
- 过早设置 IRQ 门可能导致硬件配置不一致

**原因 4：统一的早期处理**
- 所有 32 个异常都指向统一的 `early_idt_handler_array`
- 简化了早期异常处理逻辑
- 后续会用更专门的处理程序替换（`idt_setup_traps()`）

---

## 9. 参考文献

### 9.1 Linux 内核源代码

1. **arch/x86/kernel/idt.c**
   - `idt_setup_early_handler()` 函数（行 317-331）
   - `set_intr_gate()` 函数（行 206-213）
   - `idt_table` 定义（行 173）
   - `idt_descr` 定义（行 175-178）

2. **arch/x86/kernel/head_64.S**
   - `early_idt_handler_array` 定义（行 488-505）
   - `early_idt_handler_common` 实现（行 508-542）

3. **arch/x86/kernel/head64.c**
   - `x86_64_start_kernel()` 函数（行 219-289）
   - `do_early_exception()` 函数（行 156-170）

4. **arch/x86/include/asm/desc_defs.h**
   - `gate_desc` 结构定义（行 79-91）
   - `desc_ptr` 结构定义（行 23-26）

### 9.2 Intel 手册

5. **Intel 64 and IA-32 Architectures Software Developer's Manual**
   - Volume 3A, Chapter 6: Interrupt and Exception Handling
   - Volume 2A, LIDT 指令描述

### 9.3 相关文档

6. [LINUX_KERNEL_IDT_EVOLUTION.md](LINUX_KERNEL_IDT_EVOLUTION.md)
   - IDT 表的演进流程详解

7. [LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md)
   - Linux 内核启动与初始化

8. [KASAN_INSTRUMENTATION_AND_INIT_ORDER.md](KASAN_INSTRUMENTATION_AND_INIT_ORDER.md)
   - KASAN 插桩机制与初始化顺序

---

**文档结束**
