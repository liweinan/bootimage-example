# x86_64：`syscall` 入口与 IDT 中断/异常入口对比（栈、trampoline、`pt_regs` 与传参）

本文整理 Linux x86_64 上 **系统调用** 与 **经 IDT 的中断/异常** 两条路径的差异：硬件行为、TSS / per-CPU entry 栈（trampoline）、`struct pt_regs` 的构造方式，以及进入 C 时的参数约定。代码引用来自 Linux 源码树中的常规路径（行号随内核版本可能略有偏移，以你本地树为准）。**§8** 为常见问答补充；**§9** 为 **IDT + TSS（RSP0/IST）** 路径上 **CPU 权限与合法性检查** 的步骤概览（架构手册向）。

**相关文档**：[LINUX_X86_KERNEL_STACK_SYSCALL_TSS.md](LINUX_X86_KERNEL_STACK_SYSCALL_TSS.md)（`cpu_current_top_of_stack`、`TSS.sp0`、调度与 `load_sp0` 等）、[LINUX_X86_TASK_TOP_OF_STACK_AND_CPU_CURRENT_TOP.md](LINUX_X86_TASK_TOP_OF_STACK_AND_CPU_CURRENT_TOP.md)。

**内核内建说明**：`Documentation/arch/x86/entry_64.rst`。

---

## 1. 两条路径对照（概念）

| 维度 | `syscall` / `sysenter` 类快速路径 | 经 IDT 的中断 / 异常 |
|------|-----------------------------------|----------------------|
| 进入内核的「门」 | 指令 + MSR（如 `LSTAR` → `entry_SYSCALL_64`） | 中断描述符表 IDT，按 **vector** 选处理例程 |
| 硬件是否切换 RSP | **`syscall` 不改 RSP**，仍为用户栈 | 从 ring3 进入 ring0 时，CPU 按规则选用 **TSS 中的栈**（常见为 **RSP0**；部分向量用 **IST**） |
| 硬件在栈上压什么 | **不压栈**（`rcx`/`r11` 等由约定保存返回信息） | 压 **IRET 帧**（自 ring3 进入时含 `SS`、`RSP`、`RFLAGS`、`CS`、`RIP`；部分异常多 **error code**） |
| 与 `entry_SYSCALL_64` 的类比 | **全局单一**内核入口地址（由 MSR 指向） | **每个 vector 各自**一条汇编入口（`asm_*` 多个符号），多由 **`idtentry` / `idtentry_body` 宏**生成同类代码 |
| 进入 C 时「传参」含义 | `rdi` = `pt_regs *`，`rsi` = 系统调用号（扩展后）等，见 `do_syscall_64` | `rdi` = `pt_regs *`；`has_error_code=1` 时 `rsi` = **硬件 error code** 或 IRQ 路径上的 **vector**（见下文） |

---

## 2. `syscall` 路径：MSR、不换栈、再软件切线程内核栈

文件头部注释说明 **IRET 帧** 与 **术语**（与 IDT 路径共用「`pt_regs` 里那一段」的概念）：

```13:19:/Users/weli/works/linux/arch/x86/entry/entry_64.S
 * A note on terminology:
 * - iret frame:	Architecture defined interrupt frame from SS to RIP
 *			at the top of the kernel process stack.
 *
 * Some macro usage:
 * - SYM_FUNC_START/END:Define functions in the symbol table.
 * - idtentry:		Define exception entry points.
```

**`syscall` 本身**：注释写明不压栈、不改 `rsp`，并在寄存器里约定系统调用号与参数：

```49:66:/Users/weli/works/linux/arch/x86/entry/entry_64.S
/*
 * 64-bit SYSCALL instruction entry. Up to 6 arguments in registers.
 *
 * This is the only entry point used for 64-bit system calls.  The
 * hardware interface is reasonably well designed and the register to
 * argument mapping Linux uses fits well with the registers that are
 * available when SYSCALL is used.
...
 * rflags gets masked by a value from another MSR (so CLD and CLAC
 * are not needed). SYSCALL does not save anything on the stack
 * and does not change rsp.
```

寄存器与 `do_syscall_64` 调用约定（节选）：

```68:121:/Users/weli/works/linux/arch/x86/entry/entry_64.S
 * Registers on entry:
 * rax  system call number
 * rcx  return address
 * r11  saved rflags (note: r11 is callee-clobbered register in C ABI)
 * rdi  arg0
 * rsi  arg1
 * rdx  arg2
 * r10  arg3 (needs to be moved to rcx to conform to C ABI)
 * r8   arg4
 * r9   arg5
...
SYM_CODE_START(entry_SYSCALL_64)
...
	movq	PER_CPU_VAR(cpu_current_top_of_stack), %rsp
...
	/* Construct struct pt_regs on stack */
	pushq	$__USER_DS				/* pt_regs->ss */
	pushq	PER_CPU_VAR(cpu_tss_rw + TSS_sp2)	/* pt_regs->sp */
...
	PUSH_AND_CLEAR_REGS rax=$-ENOSYS

	/* IRQs are off. */
	movq	%rsp, %rdi
	/* Sign extend the lower 32bit as syscall numbers are treated as int */
	movslq	%eax, %rsi
...
	call	do_syscall_64		/* returns with IRQs disabled */
```

要点：

- **业务参数**：按 ABI 已在 **`rdi`…`r9`**（及 `rax` 中的调用号）；这些是「系统调用语义」上的参数。
- **内核栈**：由 **`cpu_current_top_of_stack`** 指向的**当前线程**内核栈顶加载到 `%rsp`，再在栈上构造 **`pt_regs`**。
- **SYSRET 返回前**会临时切到 **`cpu_tss_rw` 的 `sp0`** 所指的 **trampoline 栈**做收尾（与 IDT 用的 entry 栈同属「per-CPU entry / trampoline」一类资源，见 [LINUX_X86_KERNEL_STACK_SYSCALL_TSS.md](LINUX_X86_KERNEL_STACK_SYSCALL_TSS.md)）：

```141:146:/Users/weli/works/linux/arch/x86/entry/entry_64.S
	/*
	 * Now all regs are restored except RSP and RDI.
	 * Save old stack pointer and switch to trampoline stack.
	 */
	movq	%rsp, %rdi
	movq	PER_CPU_VAR(cpu_tss_rw + TSS_sp0), %rsp
```

---

## 3. IDT 路径：硬件 IRET 帧、`idtentry_body`、进入 C 的约定

### 3.1 宏 `idtentry_body`：`error_entry`、线程栈、`pt_regs *` 与第二参数

```289:316:/Users/weli/works/linux/arch/x86/entry/entry_64.S
.macro idtentry_body cfunc has_error_code:req

	/*
	 * Call error_entry() and switch to the task stack if from userspace.
...
	ALTERNATIVE "call error_entry; movq %rax, %rsp", \
		    "call xen_error_entry", X86_FEATURE_XENPV

	ENCODE_FRAME_POINTER
	UNWIND_HINT_REGS

	movq	%rsp, %rdi			/* pt_regs pointer into 1st argument*/

	.if \has_error_code == 1
		movq	ORIG_RAX(%rsp), %rsi	/* get error code into 2nd argument*/
		movq	$-1, ORIG_RAX(%rsp)	/* no syscall to restart */
	.endif
...
	call	\cfunc

	jmp	error_return
.endm
```

- 第一参数 **`rdi`**：始终为当前栈上的 **`struct pt_regs *`**（被打断时的完整现场，含 IRET 帧与通用寄存器）。
- **`has_error_code == 1`** 时：**`rsi`** 来自栈上与「error code 槽位」对齐的位置；该槽位对**真·异常**是硬件 error code，对 **IRQ stub** 则是软件压入的 **vector**（见下一小节）。

C 侧类型声明（无 error code / 有 error code）：

```16:38:/Users/weli/works/linux/arch/x86/include/asm/idtentry.h
typedef void (*idtentry_t)(struct pt_regs *regs);

/**
 * DECLARE_IDTENTRY - Declare functions for simple IDT entry points
 *		      No error code pushed by hardware
...
#define DECLARE_IDTENTRY(vector, func)					\
	asmlinkage void asm_##func(void);				\
...
	__visible void func(struct pt_regs *regs)
```

```86:89:/Users/weli/works/linux/arch/x86/include/asm/idtentry.h
#define DECLARE_IDTENTRY_ERRORCODE(vector, func)			\
	asmlinkage void asm_##func(void);				\
	asmlinkage void xen_asm_##func(void);				\
	__visible void func(struct pt_regs *regs, unsigned long error_code)
```

### 3.2 硬件中断：`idtentry_irq` 把 vector 塞进「error code 位置」

```367:378:/Users/weli/works/linux/arch/x86/entry/entry_64.S
/*
 * Interrupt entry/exit.
 *
 + The interrupt stubs push (vector) onto the stack, which is the error_code
 * position of idtentry exceptions, and jump to one of the two idtentry points
 * (common/spurious).
 *
 * common_interrupt is a hotpath, align it to a cache line
 */
.macro idtentry_irq vector cfunc
	.p2align CONFIG_X86_L1_CACHE_SHIFT
	idtentry \vector asm_\cfunc \cfunc has_error_code=1
.endm
```

因此：**中断处理函数的 `rsi`（若原型带 `error_code`）在此路径上表示 vector**，不是外设「数据寄存器」含义上的参数；设备状态需 handler 内再读 MMIO / APIC 等。

### 3.3 与 `syscall` 传参的本质区别

- **`syscall`**：`rdi`/`rsi`/… 在用户态约定下就是 **系统调用参数**；进入内核后再把它们连同其它寄存器一起收进 **`pt_regs`**，并以 `pt_regs *` + 调用号调 `do_syscall_64`。
- **中断/异常**：用户态当时的 **`rdi`/`rsi`/… 不是「传给中断的参数」**，而是 **被中断打断的现场**，统一躺在 **`pt_regs`** 里；C  handler 主要通过 **`pt_regs *`** 访问（外加 error code / vector）。

---

## 4. 「统一 trampoline 栈」与「每 vector 一个入口地址」为何不矛盾

- **统一**的是：在 **从 ring3 进入、且使用 TSS 的 RSP0**（非 IST）时，CPU 先把 IRET 帧压在 **同一条 per-CPU entry / trampoline 栈**上（与 `cpu_init` 里 `load_sp0(cpu_entry_stack(cpu)+1)` 等初始化一致，详见 [LINUX_X86_KERNEL_STACK_SYSCALL_TSS.md](LINUX_X86_KERNEL_STACK_SYSCALL_TSS.md)）。
- **不统一**的是：IDT 里 **256 个向量各自对应不同的门目标 RIP**，即 **多条 `asm_*` 入口**（宏展开后代码结构相似，但不是「一个物理地址对应所有向量」）。这与 **`syscall` 仅由 `LSTAR` 指向单一 `entry_SYSCALL_64`** 不同。

---

## 5. `iret frame` 注释与「进程内核栈」：时间线（两段栈）

`entry_64.S` 文件头写 **iret frame 在 kernel process stack 顶部**，容易与「刚中断时一定在线程栈上」混淆。实际顺序是：

1. **硬件**：从用户态经 IDT 进入且走 RSP0 时，帧先在 **per-CPU entry / trampoline 栈**。
2. **`error_entry`（用户态来源）**：`PUSH_AND_CLEAR_REGS` 等补全现场后，**尾跳到 `sync_regs`**，把 **`pt_regs` 挪到当前线程内核栈**上的槽位（`current_top_of_stack() - 1`），并返回新的 `pt_regs *`；外层汇编再 **`movq %rax, %rsp`** 切栈。
3. **之后**：从内核逻辑看，IRET 帧作为 **`pt_regs` 的一部分** 位于 **当前线程的内核栈** 顶端附近——与文件头注释的描述一致。

`error_entry` 用户路径与 `sync_regs` 注释（节选）：

```1004:1027:/Users/weli/works/linux/arch/x86/entry/entry_64.S
SYM_CODE_START(error_entry)
...
	testb	$3, CS+8(%rsp)
	jz	.Lerror_kernelspace
...
	swapgs
...
	SWITCH_TO_KERNEL_CR3 scratch_reg=%rax
...
	leaq	8(%rsp), %rdi			/* arg0 = pt_regs pointer */
	/* Put us onto the real thread stack. */
	jmp	sync_regs
```

```917:928:/Users/weli/works/linux/arch/x86/kernel/traps.c
/*
 * Help handler running on a per-cpu (IST or entry trampoline) stack
 * to switch to the normal thread stack if the interrupted code was in
 * user mode. The actual stack switch is done in entry_64.S
 */
asmlinkage __visible noinstr struct pt_regs *sync_regs(struct pt_regs *eregs)
{
	struct pt_regs *regs = (struct pt_regs *)current_top_of_stack() - 1;
	if (regs != eregs)
		*regs = *eregs;
	return regs;
}
```

因此：**注释强调的是「稳定状态下 `pt_regs` 在线程栈上的布局」**；**不否定** 此前经过 **trampoline / IST 栈** 的阶段。

---

## 6. IST 与「非 RSP0」路径（边界）

部分异常/中断使用 **IST**（Interrupt Stack Table），硬件选择的 **不是 RSP0** 那条 per-CPU entry 栈，而是 TSS 中 **IST1…** 等指向的栈。此类路径仍会通过 **`sync_regs` 等** 在适当时机把现场整理到线程可继续使用的栈布局上，但**不能**再说「一律先落在 sp0 trampoline」。具体向量与宏（如 `idtentry_mce_db`、`paranoid_entry` 等）见 `entry_64.S` 其余节与 [LINUX_X86_KERNEL_STACK_SYSCALL_TSS.md](LINUX_X86_KERNEL_STACK_SYSCALL_TSS.md) 对 IST 的索引。

---

## 7. 源码位置速查

| 内容 | 文件与符号 |
|------|------------|
| `syscall` 入口与 `pt_regs` 构造、`do_syscall_64` 调用 | `arch/x86/entry/entry_64.S`：`entry_SYSCALL_64` |
| IDT 通用体、IRQ vector 语义 | `arch/x86/entry/entry_64.S`：`idtentry`、`idtentry_body`、`idtentry_irq` |
| 用户态 IDT 入口切线程栈 | `arch/x86/entry/entry_64.S`：`error_entry`；`arch/x86/kernel/traps.c`：`sync_regs` |
| C 侧 IDT 声明宏 | `arch/x86/include/asm/idtentry.h`：`DECLARE_IDTENTRY*`、`DEFINE_IDTENTRY*` |
| MSR `LSTAR` 与 syscall 初始化 | `arch/x86/kernel/cpu/common.c`：`idt_syscall_init()` 等（见栈文档索引） |

---

## 8. 常见问答（与上文讨论对齐）

本节把对话中反复出现的辨析集中写进本文，避免与 §1–§7 重复时可交叉引用。

### 8.1 `sp0` 具体指向什么？

在 **原生 Linux x86_64** 上，BSP/AP 初始化里通常执行  
`load_sp0((unsigned long)(cpu_entry_stack(cpu) + 1))`：  
**`cpu_tss_rw.x86_tss.sp0`（硬件 RSP0）** 指向 **该 CPU 的 per-CPU entry / trampoline 内核栈** 的栈顶一侧，注释里常称 **entry trampoline 栈**，**与当前 `task` 无关**。  
**Xen PV** 等路径下可能按任务更新 `sp0`（如 `load_sp0(task_top_of_stack(task))`），见 [LINUX_X86_KERNEL_STACK_SYSCALL_TSS.md](LINUX_X86_KERNEL_STACK_SYSCALL_TSS.md) §4。

### 8.2 `sp0` 是不是「用户进程的内核空间地址」？「trampoline」指什么？

- **`sp0` 里存的是内核可用的线性地址**（落在内核管理、通常长期映射的内存上），**不是**用户态映射里的 VA。  
- 但它**一般不是**「当前这个进程那条线程内核栈（`task->stack` / `cpu_current_top_of_stack`）」：原生 64 位下多是 **`cpu_entry_stack` 那条 per-CPU 专用栈**。  
- **Trampoline（entry trampoline）**：指这条 **per-CPU entry 栈** 以及其上的**过渡逻辑**——从 ring3 经 **RSP0** 进来时，CPU 先把 **IRET 帧**压在这条栈上，入口汇编在这条**浅而固定**的栈上跑一小段（`swapgs`、切 CR3、补 `pt_regs`），用户态场景下再通过 **`sync_regs`** 把现场迁到 **当前线程真实内核栈**；**SYSRET 返回前**也会临时切到 **`TSS.sp0` 所指栈**做收尾（见 §2 中 `syscall_return_via_sysret` 引用）。

### 8.3 能否从 `sp0`「算出」`task->stack` / `cpu_current_top_of_stack`？

**不能。** `sp0` 与 **`cpu_current_top_of_stack`** 无换算关系：前者是 **硬件第一步**用的 **per-CPU entry 栈**；后者在 **`__switch_to`** 里为 **当前运行线程**更新。  
**接法**：**syscall** 入口直接 `mov … cpu_current_top_of_stack → %rsp`；**IDT 从用户态**先落 entry 栈，再 **`error_entry` → `sync_regs`**，内部用 **`current_top_of_stack()`**（读 **`cpu_current_top_of_stack`** 一类槽位）在线程栈上摆好 `pt_regs` 并切 `%rsp`。依赖 **`current` 已是被打断的任务** 且切换时已写好 per-CPU 顶栈，**不是**从 `sp0` 解码任务。

### 8.4 TSS 进来和 syscall 进来，`current_top_of_stack()` / `cpu_current_top_of_stack` 是否同一套？

**是同一套 per-CPU 信息**（「当前 CPU 上正在跑的那条线程的内核栈顶」），**不**按「syscall 一套、IDT 一套」分两套变量。  
差别只在 **何时、如何用**：syscall **立刻**切到线程栈；IDT 用户态路径 **先**在 entry 栈，**再**经 `sync_regs` 用 `current_top_of_stack()` 接到线程栈。

### 8.5 为何 syscall 入口「不需要」trampoline？

**`syscall` 指令不改 `RSP`**，进内核时 `%rsp` 仍是**用户栈**；内核不信任用它长正式帧，于是用 **`cpu_current_top_of_stack` 直接装 `%rsp`**，在线程栈上就地构造 `pt_regs`，只需把用户 `RSP` 等暂存到 **`TSS.sp2` scratch** 等少量辅助。  
**IDT** 路径下 CPU **会**按特权级切换选用 **RSP0/IST**，**强制**先在 **entry 栈**上压硬件帧，因此呈现「先 trampoline、再迁线程栈」的两段式。  
**注意**：syscall **返回**走 SYSRET 时仍可能用到 **`sp0` 那条栈**（见 §2），故「全程与 trampoline 无关」不准确，应区分 **入口**与**出口**。

### 8.6 「硬件已把你放到 RSP0 这条栈」为何不等于 `cpu_current_top_of_stack`？

**RSP0 / `sp0`**：CPU 从 ring3 经 **会走 TSS RSP0** 的路径进来时，**硬件**把 `%rsp` 设为 TSS 中该值 → **per-CPU entry 栈**。CPU **不知道** `cpu_current_top_of_stack`。  
**`cpu_current_top_of_stack`**：内核维护的 **当前线程内核栈顶**。二者地址**通常不同**；接线程栈靠软件（`sync_regs` 等），不是从 `sp0` 推导。

### 8.7 trampoline 上「多压」的东西，syscall 没压，为何仍能工作？

**不是** syscall 缺了「只有 trampoline 才有的神秘数据」。  
- **IDT**：CPU **自动**在新 `%rsp`（entry/IST 栈）上压 **IRET 帧**（及约定下的 error code），这是**手册规定的进内核一步**；再经 `PUSH_AND_CLEAR_REGS` 等补成完整 **`pt_regs`**。  
- **syscall**：CPU **不压** IRET 帧、**不换**栈；返回地址在 **`rcx`**、rflags 在 **`r11`**、调用号在 **`rax`**，用户 **`RSP`** 在换栈前记入 **scratch**（如 `TSS.sp2`），入口用 **`push` + `PUSH_AND_CLEAR_REGS`** 在**线程栈**上**手工**搭出**同一语义**的 `pt_regs`。  
两类路径最终都要 **`pt_regs` 信息类别一致**（返回点、flags、用户栈、通用寄存器），只是 **IDT 先由硬件在 entry 栈摆 IRET 帧**，**syscall 在寄存器里带着等价信息在线程栈上现搭**。

### 8.8 `TSS → sp0` 这条线上，压栈是不是 CPU 自动完成的？

**对。** 走 **TSS RSP0**（或该门绑定的 **IST**）从 ring3 进 ring0 时：  
1. **换栈**：CPU 从 TSS 取 **RSP0**（或对应 IST）作为新 **`%rsp`**。  
2. **压 IRET 帧**（及有 error code 的向量上硬件 error code）：由 **CPU 按手册顺序自动压**到新栈。  
其后内核汇编的 **`PUSH_AND_CLEAR_REGS` 等**是在硬件已压好的帧**之后**补通用寄存器、形成完整 `pt_regs`，**不替代** CPU 压最上面那截 IRET 帧。

---

## 9. IDT + TSS（RSP0 / IST）路径上的权限与合法性：谁检查、步骤是什么

本节说明 **经 IDT 进入 ring0 并使用 TSS 换栈** 时，**CPU 自动完成** 的检查与大致顺序（x86-64 长模式；细节以 Intel SDM / AMD APM 为准）。**`sp0` 本身不是单独一道「权限检查」**，而是 **在门与目标代码段等已通过或同步进行的前提下**，为 **0 级入口** 提供的 **初始 `RSP`**。

### 9.1 是否由 CPU 自动做「权限相关」行为？

**是。** 这是 **保护模式 / 长模式下中断与异常投递** 的一部分，由 **微架构按手册** 执行，不是内核先手动「批准」再换栈。若 **门、段、TSS、栈指针** 等不合法，会 **#GP / #NP / #TS / #SS** 等，而不是静默使用非法栈。

### 9.2 典型步骤（从用户态经 IDT 到 ring0，使用 RSP0 或 IST）

下列顺序为教学用归纳，与实现细节以手册章节为准。

1. **定位 IDT 项**  
   用 **IDTR** 基址 + **向量 × 16** 取对应 **64 位中断/陷阱门**（16 字节）。

2. **检查门描述符**  
   - **P=1**，类型为合法的中断门/陷阱门等。  
   - **由 `INT n` / `INTO` 等软件触发**时：要求 **CPL ≤ 门 DPL**，否则 **#GP**（与向量相关，见手册编码）。  
   - **硬件异常、外部中断、NMI** 等（非用户 `INT n` 语义）：**不按软件 `INT` 那套对「CPL vs 门 DPL」拦 ring3**，否则无法从用户态正常进入内核 IRQ/异常处理。

3. **从门中取目标代码段选择子并准备加载 CS**  
   门内含有 **目标 CS 选择子** 与 **RIP 偏移**。CPU 在 GDT/LDT 中取 **代码段描述符**，检查 **存在、可执行、与长模式一致** 等；目标为 **DPL=0** 的非一致性代码段且 **CPL=3** 时构成 **特权级提升**。

4. **若发生向外到内的特权级变化（如 3→0），则换栈**  
   **长模式**下新 **RSP** 来自 **当前 TSS**：门中 **IST=0** 时用 **RSP0**（即 **`TSS.sp0`**）；**IST≠0** 时用 **ISTn** 对应槽。对 **RSP** 等有 **规范地址（canonical）** 等约束；TSS/栈无效 → **#TS / #GP / #SS** 等（依场景）。

5. **在新栈上由硬件压 IRET 帧**  
   压 **SS、RSP、RFLAGS、CS、RIP**（及该向量要求的 **error code**）。中断门/陷阱门对 **IF** 等副作用按手册处理。

6. **转入处理程序**  
   **RIP** ← 门中偏移，**CS** ← 门中选择子（此前已完成描述符加载与特权相关检查）。

### 9.3 与 `syscall` 的对比

- **`syscall` / `sysret`**：**不经 IDT**，**不用**上述 **门 + TSS RSP0** 的换栈与检查序列，而是 **MSR（如 STAR/LSTAR）** 约定的另一套路径。  
- **`iret` 返回**：对栈上返回帧与选择子另有 **对称的合法性检查**，与「进内核」分列。

### 9.4 小结

**`TSS → sp0` 这条线**上，**换栈与压 IRET 帧**由 **CPU 自动完成**；**权限与合法性**分散在 **IDT 门（含软件 `INT` 时的 DPL）、目标代码段、TSS/IST/RSP** 等步骤中，**统一由硬件在投递过程中检查**，失败则异常中止，而不是仅靠 `sp0` 一个字段「单独做权限判断」。
