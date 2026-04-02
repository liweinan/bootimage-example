# x86 内核栈、syscall 入口与 TSS / per-CPU 变量

本文档整理 Linux x86 上**用户态进入内核**时内核栈指针的来源，以及 **`cpu_current_top_of_stack`**、**TSS（及 FRED）**、**`task_top_of_stack`**、**`__switch_to`** 之间的关系与代码位置。基于当前树内源码归纳。

---

## 1. 符号与文件速查

| 主题 | 位置 |
|------|------|
| `cpu_current_top_of_stack` 定义（per-CPU） | `arch/x86/kernel/cpu/common.c`：`DEFINE_PER_CPU_CACHE_HOT(...)` |
| `cpu_current_top_of_stack` 声明 | `arch/x86/include/asm/processor.h`：`DECLARE_PER_CPU_CACHE_HOT` |
| `entry_SYSCALL_64` 汇编入口 | `arch/x86/entry/entry_64.S`：`SYM_CODE_START(entry_SYSCALL_64)` |
| `entry_SYSCALL_64` 声明 | `arch/x86/include/asm/proto.h` |
| MSR `LSTAR` 指向 syscall 入口 | `arch/x86/kernel/cpu/common.c`：`idt_syscall_init()` 内 `wrmsrq(MSR_LSTAR, …)`（由 `cpu_init()` 调用） |
| Xen 包装 | `arch/x86/xen/xen-asm.S`：`xen_entry_SYSCALL_64`，可跳到 `entry_SYSCALL_64_after_hwframe` |
| `__switch_to`（x86_64 C 实现） | `arch/x86/kernel/process_64.c` |
| `__switch_to`（i386 C 实现） | `arch/x86/kernel/process_32.c` |
| `__switch_to_asm` | `arch/x86/entry/entry_64.S` / `entry_32.S` |
| `switch_to` 宏 | `arch/x86/include/asm/switch_to.h` → 调用 `__switch_to_asm` |

---

## 2. `int` / 异常 / 中断 与 `syscall` 路径的差异（概念）

- **`syscall` 路径**：硬件**不**把 RSP 切到内核栈；入口汇编（如 `entry_SYSCALL_64`）里用  
  `movq PER_CPU_VAR(cpu_current_top_of_stack), %rsp` 等方式**软件**加载内核栈顶。
- **经 TSS 的 ring0 入口**（如部分异常/中断路径）：硬件或入口代码从 **`cpu_tss_rw` 中与 RSP0 对应的字段**取栈。x86_64 上具体布局与 **entry trampoline**、IST 等实现相关，需结合 `entry_64.S` 阅读。

注意：教学材料里常把「TSS.RSP0」与「`cpu_current_top_of_stack`」写成同一 `sp0` 的两份拷贝；**原生 x86_64 当前实现里，TSS 的 `sp0` 并不按每个进程在每次 `__switch_to` 里改成线程栈顶**，见下文第 4 节。

---

## 3. `cpu_current_top_of_stack`：谁在写、谁在读

### 3.1 写入 / 初始化（更新列表）

| 文件 | 行为 |
|------|------|
| `arch/x86/kernel/cpu/common.c` | `DEFINE_PER_CPU_CACHE_HOT(..., cpu_current_top_of_stack) = TOP_OF_INIT_STACK`（定义与初值） |
| `arch/x86/kernel/smpboot.c` | `per_cpu(cpu_current_top_of_stack, cpu) = task_top_of_stack(idle)`（AP 上 idle） |
| `arch/x86/kernel/process_64.c` | `__switch_to` 中：`raw_cpu_write(cpu_current_top_of_stack, task_top_of_stack(next_p))` |
| `arch/x86/kernel/process_32.c` | `__switch_to` 中：`this_cpu_write(cpu_current_top_of_stack, ...)`（用 `task_stack_page + THREAD_SIZE`） |

### 3.2 读取（示例）

- `arch/x86/entry/entry_64.S`、`entry_64_compat.S`、`entry_32.S`：syscall/兼容入口等处 `PER_CPU_VAR(cpu_current_top_of_stack)` 装入 RSP/ESI 等。

### 3.3 链接与常量优化

- `arch/x86/kernel/vmlinux.lds.S`：`const_cpu_current_top_of_stack` 与 `cpu_current_top_of_stack` 的别名关系（供 `current_top_of_stack()` 等路径使用，见 `processor.h`）。

---

## 4. TSS（及 FRED）侧：与 RSP0 / 内核入口栈相关的更新

### 4.1 实际写入 `cpu_tss_rw.x86_tss.sp0` 的核心

- **`arch/x86/include/asm/processor.h`**：`native_load_sp0()` 内  
  `this_cpu_write(cpu_tss_rw.x86_tss.sp0, sp0)`。  
  原生下 `load_sp0()` 最终走到这里（非 `CONFIG_PARAVIRT_XXL` 时内联）。

### 4.2 谁调用 `load_sp0`

| 文件 | 说明 |
|------|------|
| `arch/x86/kernel/cpu/common.c` | CPU 初始化：`load_sp0((unsigned long)(cpu_entry_stack(cpu) + 1))`，注释写明 **sp0 指向 entry trampoline 栈，与当前任务无关** |
| `arch/x86/include/asm/switch_to.h` — `update_task_stack()` | **x86_64**：若**非** FRED 且为 **Xen PV**，则 `load_sp0(task_top_of_stack(task))`；**原生 x86_64** 通常不在此处每任务更新 sp0 |
| `arch/x86/xen/enlighten_pv.c` | `xen_load_sp0`：直接写 `cpu_tss_rw.x86_tss.sp0`（PV 后端） |

### 4.3 TSS 静态初始化

- **`arch/x86/kernel/process.c`**：`DEFINE_PER_CPU_PAGE_ALIGNED(cpu_tss_rw)` 中对 `.x86_tss.sp0` 的**毒化初值**（init 路径说明在注释中）。

### 4.4 i386：`thread.sp0` 与 TSS 字段

- **`arch/x86/include/asm/switch_to.h`** — `update_task_stack()`：**32 位**下写  
  `cpu_tss_rw.x86_tss.sp1 = task->thread.sp0`（ring0 入口用的是 **sp1**，与 64 位命名习惯不同，勿与 64 位 sp0 混谈）。

### 4.5 FRED

- **`arch/x86/include/asm/fred.h`**：`fred_sync_rsp0` / `fred_update_rsp0` 维护 **`MSR_IA32_FRED_RSP0`** 与 per-cpu `fred_rsp0`，与经典 TSS RSP0 机制并存。

### 4.6 与「两份都是 next->thread.sp0」说法的对照

- **`cpu_current_top_of_stack`**：在 **`__switch_to`**（64 位）里按 **`task_top_of_stack(next)`** 更新，反映**当前运行线程**的内核栈顶（宏定义见第 5 节）。
- **原生 x86_64 的 `TSS.sp0`**：多为 **固定的 CPU entry trampoline**，不是每个进程切换都写成该进程栈顶；**Xen PV** 等路径例外。

---

## 5. `task_top_of_stack`：不是“被写入的变量”

### 5.1 定义（x86）

见 **`arch/x86/include/asm/processor.h`**：

```643:653:arch/x86/include/asm/processor.h
#define TOP_OF_INIT_STACK ((unsigned long)&init_stack + sizeof(init_stack) - \
			   TOP_OF_KERNEL_STACK_PADDING)

#define task_top_of_stack(task) ((unsigned long)(task_pt_regs(task) + 1))

#define task_pt_regs(task) \
({									\
	unsigned long __ptr = (unsigned long)task_stack_page(task);	\
	__ptr += THREAD_SIZE - TOP_OF_KERNEL_STACK_PADDING;		\
	((struct pt_regs *)__ptr) - 1;					\
})
```

含义：由 **`task_stack_page(task)`（即 `task->stack`）** 与固定 **`THREAD_SIZE` / `TOP_OF_KERNEL_STACK_PADDING`** **当场计算**；**没有**单独的存储单元在“某一刻被写入 `task_top_of_stack`”。

### 5.2 何时有意义

- **`task->stack`** 在 **`copy_process()`** 路径中由 **`alloc_thread_stack_node()`**（**`kernel/fork.c`**）赋值（`tsk->stack = stack` 或等价逻辑）。
- **init** 使用架构初始线程/栈，不经过 `alloc_thread_stack_node`，但栈基址在启动期已确定。
- **i386** 上 **`copy_thread()`** 会设 **`p->thread.sp0 = (unsigned long)(childregs + 1)`**（**`arch/x86/kernel/process.c`**），与上述几何布局一致，那是 **`thread_struct.sp0` 字段**的初始化。

---

## 6. `__switch_to` 与教学示意代码的区别

部分文档为分别说明 **int 路径**与 **syscall 路径**，把 `__switch_to` 写成“只改 TSS”或“只改 `cpu_current_top_of_stack`”两段**示意代码**。内核中 **x86_64 只有一个** `__switch_to` 实现（**`arch/x86/kernel/process_64.c`**），在同一次切换里会：

- 更新 **`current_task`**、**`cpu_current_top_of_stack`**（`task_top_of_stack(next_p)`）；
- 调用 **`update_task_stack(next_p)`**（其行为随 **32/64、Xen、FRED** 等配置变化，见第 4 节）。

**`__switch_to_asm`** 在 **`arch/x86/entry/entry_64.S`**，最后 `jmp __switch_to` 进入 C 函数。

---

## 7. 参考调用关系（syscall 快速路径）

1. 用户态 `syscall` → CPU 进内核入口 **`entry_SYSCALL_64`**（`entry_64.S`）。
2. 入口使用 **`cpu_current_top_of_stack`** 设置 RSP（见该文件中的 `PER_CPU_VAR(cpu_current_top_of_stack)`）。
3. **`cpu_current_top_of_stack`** 在每次切到该任务时由 **`__switch_to`** 写成 **`task_top_of_stack(next_p)`**。
4. **`task_top_of_stack`** 由 **`task->stack` + 固定布局** 宏展开计算；**`task->stack`** 在线程创建时分配并赋值（**`kernel/fork.c`**）。

---

## 8. Call chain：`cpu_tss_rw.x86_tss.sp0`（TSS RSP0 槽位）

以下指 Linux 镜像里 **`struct tss_struct` → `x86_tss.sp0`**（汇编里常写作 `cpu_tss_rw + TSS_sp0`）。**CPU 硬件**在 CPL 切换时若使用经典 TSS RSP0，会**自动**从当前任务的 TSS 描述符所指向的内存读该字段；下面只列**内核里显式写/显式读**的软件链。

### 8.1 写入链（软件把新值放进 `x86_tss.sp0`）

**最终写内存（原生、非 `CONFIG_PARAVIRT_XXL`）：** `load_sp0()` → `native_load_sp0()`：

```533:537:arch/x86/include/asm/processor.h
static inline void
native_load_sp0(unsigned long sp0)
{
	this_cpu_write(cpu_tss_rw.x86_tss.sp0, sp0);
}
```

```569:572:arch/x86/include/asm/processor.h
static inline void load_sp0(unsigned long sp0)
{
	native_load_sp0(sp0);
}
```

若开启 **`CONFIG_PARAVIRT_XXL`**，`load_sp0()` 走 paravirt 间接调用：

```116:119:arch/x86/include/asm/paravirt.h
static inline void load_sp0(unsigned long sp0)
{
	PVOP_VCALL1(cpu.load_sp0, sp0);
}
```

后端可为 Xen 的 `xen_load_sp0` 等，不再保证等价于内联的 `native_load_sp0`。

**调用 `load_sp0` 的典型路径：**

1. **每 CPU 初始化（BSP/AP）** — `cpu_init()`：

```2420:2424:arch/x86/kernel/cpu/common.c
	/*
	 * sp0 points to the entry trampoline stack regardless of what task
	 * is running.
	 */
	load_sp0((unsigned long)(cpu_entry_stack(cpu) + 1));
```

2. **上下文切换（仅 Xen PV + 非 FRED 的 x86_64）** — `__switch_to` → `update_task_stack`：

```668:675:arch/x86/kernel/process_64.c
	/*
	 * Switch the PDA and FPU contexts.
	 */
	raw_cpu_write(current_task, next_p);
	raw_cpu_write(cpu_current_top_of_stack, task_top_of_stack(next_p));

	/* Reload sp0. */
	update_task_stack(next_p);
```

```69:78:arch/x86/include/asm/switch_to.h
static inline void update_task_stack(struct task_struct *task)
{
	/* sp0 always points to the entry trampoline stack, which is constant: */
#ifdef CONFIG_X86_32
	this_cpu_write(cpu_tss_rw.x86_tss.sp1, task->thread.sp0);
#else
	if (!cpu_feature_enabled(X86_FEATURE_FRED) && cpu_feature_enabled(X86_FEATURE_XENPV))
		/* Xen PV enters the kernel on the thread stack. */
		load_sp0(task_top_of_stack(task));
#endif
}
```

3. **Xen PV 后端**（在 paravirt 表项指向时由 `load_sp0` 间接调用）：

```1010:1017:arch/x86/xen/enlighten_pv.c
static void xen_load_sp0(unsigned long sp0)
{
	struct multicall_space mcs;

	mcs = xen_mc_entry(0);
	MULTI_stack_switch(mcs.mc, __KERNEL_DS, sp0);
	xen_mc_issue(XEN_LAZY_CPU);
	this_cpu_write(cpu_tss_rw.x86_tss.sp0, sp0);
}
```

**静态初值（启动早期，随后由 `cpu_init` 等覆盖）：**

```67:75:arch/x86/kernel/process.c
__visible DEFINE_PER_CPU_PAGE_ALIGNED(struct tss_struct, cpu_tss_rw) = {
	.x86_tss = {
		/*
		 * .sp0 is only used when entering ring 0 from a lower
		 * privilege level.  Since the init task never runs anything
		 * but ring 0 code, there is no need for a valid value here.
		 * Poison it.
		 */
		.sp0 = (1UL << (BITS_PER_LONG-1)) + 1,
```

### 8.2 读取链（软件从 `x86_tss.sp0` 取到寄存器或 C 变量）

1. **x86_64：`entry_SYSCALL_64` 返回用户态前切到 trampoline 栈**（`syscall_return_via_sysret`）：

```137:146:arch/x86/entry/entry_64.S
syscall_return_via_sysret:
	IBRS_EXIT
	POP_REGS pop_rdi=0

	/*
	 * Now all regs are restored except RSP and RDI.
	 * Save old stack pointer and switch to trampoline stack.
	 */
	movq	%rsp, %rdi
	movq	PER_CPU_VAR(cpu_tss_rw + TSS_sp0), %rsp
```

2. **x86_64：PTI 下经 IRET 回用户态的慢路径**（`.Lpti_restore_regs_and_return_to_usermode`）：

```582:591:arch/x86/entry/entry_64.S
.Lpti_restore_regs_and_return_to_usermode:
	POP_REGS pop_rdi=0

	/*
	 * The stack is now user RDI, orig_ax, RIP, CS, EFLAGS, RSP, SS.
	 * Save old stack pointer and switch to trampoline stack.
	 */
	movq	%rsp, %rdi
	movq	PER_CPU_VAR(cpu_tss_rw + TSS_sp0), %rsp
```

3. **C 侧读取（示例，`#DF` 等路径借用栈顶）：** `arch/x86/kernel/traps.c` 约 530、986 行：`this_cpu_read(cpu_tss_rw.x86_tss.sp0)` / `__this_cpu_read(cpu_tss_rw.x86_tss.sp0)`。

4. **i386：** `arch/x86/entry/entry_32.S` 中多处 `PER_CPU_VAR(cpu_tss_rw + TSS_sp0)`（如约 530、576、849 行，以文件为准）。

---

## 9. Call chain：`syscall` 线与 `cpu_current_top_of_stack`

### 9.1 写入链（谁在更新 per-CPU 的 `cpu_current_top_of_stack`）

**调度切换（常见入口：`schedule()`）：**  
`schedule()` → `__schedule_loop()` → `__schedule()` → `context_switch()` → **`switch_to`** → **`__switch_to_asm`** → **`__switch_to`**。

```6869:6881:kernel/sched/core.c
asmlinkage __visible void __sched schedule(void)
{
	struct task_struct *tsk = current;

#ifdef CONFIG_RT_MUTEXES
	lockdep_assert(!tsk->sched_rt_mutex);
#endif

	if (!task_is_running(tsk))
		sched_submit_work(tsk);
	__schedule_loop(SM_NONE);
	sched_update_worker(tsk);
}
```

```6860:6866:kernel/sched/core.c
static __always_inline void __schedule_loop(int sched_mode)
{
	do {
		preempt_disable();
		__schedule(sched_mode);
		sched_preempt_enable_no_resched();
	} while (need_resched());
```

```6783:6787:kernel/sched/core.c
		trace_sched_switch(preempt, prev, next, prev_state);

		/* Also unlocks the rq: */
		rq = context_switch(rq, prev, next, &rf);
```

```5394:5397:kernel/sched/core.c
	prepare_lock_switch(rq, next, rf);

	/* Here we just switch the register state and the stack. */
	switch_to(prev, next, prev);
```

```49:52:arch/x86/include/asm/switch_to.h
#define switch_to(prev, next, last)					\
do {									\
	((last) = __switch_to_asm((prev), (next)));			\
} while (0)
```

```177:217:arch/x86/entry/entry_64.S
SYM_FUNC_START(__switch_to_asm)
	ANNOTATE_NOENDBR
	/*
	 * Save callee-saved registers
	 * This must match the order in inactive_task_frame
	 */
	pushq	%rbp
	pushq	%rbx
	pushq	%r12
	pushq	%r13
	pushq	%r14
	pushq	%r15

	/* switch stack */
	movq	%rsp, TASK_threadsp(%rdi)
	movq	TASK_threadsp(%rsi), %rsp

#ifdef CONFIG_STACKPROTECTOR
	movq	TASK_stack_canary(%rsi), %rbx
	movq	%rbx, PER_CPU_VAR(__stack_chk_guard)
#endif

	/*
	 * When switching from a shallower to a deeper call stack
	 * the RSB may either underflow or use entries populated
	 * with userspace addresses. On CPUs where those concerns
	 * exist, overwrite the RSB with entries which capture
	 * speculative execution to prevent attack.
	 */
	FILL_RETURN_BUFFER %r12, RSB_CLEAR_LOOPS, X86_FEATURE_RSB_CTXSW

	/* restore callee-saved registers */
	popq	%r15
	popq	%r14
	popq	%r13
	popq	%r12
	popq	%rbx
	popq	%rbp

	jmp	__switch_to
SYM_FUNC_END(__switch_to_asm)
```

**在 `__switch_to` 中写入 `cpu_current_top_of_stack`（x86_64）：**

```671:675:arch/x86/kernel/process_64.c
	raw_cpu_write(current_task, next_p);
	raw_cpu_write(cpu_current_top_of_stack, task_top_of_stack(next_p));

	/* Reload sp0. */
	update_task_stack(next_p);
```

说明：`__schedule()` 也可由抢占、`cond_resched` 等路径调用，不一定经过 `schedule()`；但只要发生**真正的上下文切换**，仍会落到 **`context_switch` → `switch_to` → `__switch_to_asm` → `__switch_to`**。

**per-CPU 初值：**

```2176:2176:arch/x86/kernel/cpu/common.c
DEFINE_PER_CPU_CACHE_HOT(unsigned long, cpu_current_top_of_stack) = TOP_OF_INIT_STACK;
```

**仅 `CONFIG_X86_32`：AP 启动 idle 时额外赋值**（整段在 `#ifdef CONFIG_X86_32` 内；**x86_64 无此赋值**）：

```832:835:arch/x86/kernel/smpboot.c
#ifdef CONFIG_X86_32
	/* Stack for startup_32 can be just as for start_secondary onwards */
	per_cpu(cpu_current_top_of_stack, cpu) = task_top_of_stack(idle);
#endif
```

**i386 `__switch_to` 中的写入：**

```196:200:arch/x86/kernel/process_32.c
	update_task_stack(next_p);
	refresh_sysenter_cs(next);
	this_cpu_write(cpu_current_top_of_stack,
		       (unsigned long)task_stack_page(next_p) +
		       THREAD_SIZE);
```

### 9.2 读取链（syscall 相关：进入内核时把该 per-CPU 值装进 RSP）

**MSR `LSTAR` 与 64 位入口**（调用链：`cpu_init()` → `syscall_init()` →（非 FRED 时）`idt_syscall_init()`）：

```2400:2403:arch/x86/kernel/cpu/common.c
	if (IS_ENABLED(CONFIG_X86_64)) {
		loadsegment(fs, 0);
		memset(cur->thread.tls_array, 0, GDT_ENTRY_TLS_ENTRIES * 8);
		syscall_init();
```

```2234:2247:arch/x86/kernel/cpu/common.c
void syscall_init(void)
{
	/* The default user and kernel segments */
	wrmsr(MSR_STAR, 0, (__USER32_CS << 16) | __KERNEL_CS);

	/*
	 * Except the IA32_STAR MSR, there is NO need to setup SYSCALL and
	 * SYSENTER MSRs for FRED, because FRED uses the ring 3 FRED
	 * entrypoint for SYSCALL and SYSENTER, and ERETU is the only legit
	 * instruction to return to ring 3 (both sysexit and sysret cause
	 * #UD when FRED is enabled).
	 */
	if (!cpu_feature_enabled(X86_FEATURE_FRED))
		idt_syscall_init();
```

```2198:2203:arch/x86/kernel/cpu/common.c
static inline void idt_syscall_init(void)
{
	wrmsrq(MSR_LSTAR, (unsigned long)entry_SYSCALL_64);

	if (ia32_enabled()) {
		wrmsrq_cstar((unsigned long)entry_SYSCALL_compat);
```

**64 位用户态 `syscall` → `entry_SYSCALL_64`：**

```87:95:arch/x86/entry/entry_64.S
SYM_CODE_START(entry_SYSCALL_64)
	UNWIND_HINT_ENTRY
	ENDBR

	swapgs
	/* tss.sp2 is scratch space. */
	movq	%rsp, PER_CPU_VAR(cpu_tss_rw + TSS_sp2)
	SWITCH_TO_KERNEL_CR3 scratch_reg=%rsp
	movq	PER_CPU_VAR(cpu_current_top_of_stack), %rsp
```

随后在同文件中 `call do_syscall_64`（约 121 行）。

**IA-32 兼容 64 位 syscall 入口 `entry_SYSCALL_compat`：**

```183:196:arch/x86/entry/entry_64_compat.S
SYM_CODE_START(entry_SYSCALL_compat)
	UNWIND_HINT_ENTRY
	ENDBR
	/* Interrupts are off on entry. */
	swapgs

	/* Stash user ESP */
	movl	%esp, %r8d

	/* Use %rsp as scratch reg. User ESP is stashed in r8 */
	SWITCH_TO_KERNEL_CR3 scratch_reg=%rsp

	/* Switch to the kernel stack */
	movq	PER_CPU_VAR(cpu_current_top_of_stack), %rsp
```

**32 位兼容 SYSENTER 入口 `entry_SYSENTER_compat`（同样加载 `cpu_current_top_of_stack`）：**

```50:60:arch/x86/entry/entry_64_compat.S
SYM_CODE_START(entry_SYSENTER_compat)
	UNWIND_HINT_ENTRY
	ENDBR
	/* Interrupts are off on entry. */
	swapgs

	pushq	%rax
	SWITCH_TO_KERNEL_CR3 scratch_reg=%rax
	popq	%rax

	movq	PER_CPU_VAR(cpu_current_top_of_stack), %rsp
```

**i386 内核：** `arch/x86/entry/entry_32.S` 中 `PER_CPU_VAR(cpu_current_top_of_stack)`（如约 1156、1220 行）。

**与返回用户态的衔接：** 进内核时读 **`cpu_current_top_of_stack`**；返回前常先 **`movq … TSS_sp0, %rsp`** 切到 trampoline（第 8.2 节），再 `SYSRET`/`IRET`。

**C 侧读 `cpu_current_top_of_stack`：** `current_top_of_stack()`：

```546:557:arch/x86/include/asm/processor.h
static __always_inline unsigned long current_top_of_stack(void)
{
	/*
	 *  We can't read directly from tss.sp0: sp0 on x86_32 is special in
	 *  and around vm86 mode and sp0 on x86_64 is special because of the
	 *  entry trampoline.
	 */
	if (IS_ENABLED(CONFIG_USE_X86_SEG_SUPPORT))
		return this_cpu_read_const(const_cpu_current_top_of_stack);

	return this_cpu_read_stable(cpu_current_top_of_stack);
}
```

---

## 10. 文档说明

- 本文仅作内核阅读索引与概念对齐，**具体行为以当前配置（`CONFIG_XEN_PV`、`CONFIG_X86_FRED`、`CONFIG_VMAP_STACK`、`CONFIG_STACKPROTECTOR` 等）下的源码为准**。
- 文中 **行号均按本仓库当前文件** 校对；换分支或版本后请以实际文件为准。
