# x86_64：`syscall` 入口与 IDT 中断/异常入口对比（栈、trampoline、`pt_regs` 与传参）

本文整理 Linux x86_64 上 **系统调用** 与 **经 IDT 的中断/异常** 两条路径的差异：硬件行为、TSS / per-CPU entry 栈（trampoline）、`struct pt_regs` 的构造方式，以及进入 C 时的参数约定。代码引用来自 Linux 源码树中的常规路径（行号随内核版本可能略有偏移，以你本地树为准）。

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
