# Linux x86-64: `sp0`、`cpu_current_top_of_stack` 与 `pt_regs` 入口路径分析

本文基于 `linux` 源码目录（`/Users/weli/works/linux`）做静态代码追踪，聚焦三个问题：

1. CPU 何时读取 `TSS.sp0`
2. `cpu_current_top_of_stack` 如何得到当前进程内核栈位置
3. `pt_regs` 何时、如何被填充

---

## 1. 先结论：x86-64 原生路径里，`sp0` 与“当前进程内核栈顶”是两套机制

在现代 Linux x86-64（非 Xen PV 特殊路径）中：

- `TSS.sp0` 主要用于 **entry trampoline stack / entry stack** 相关切换，不等价于“当前 task 线程栈顶”
- “当前 task 的内核栈顶”由每 CPU 变量 `cpu_current_top_of_stack` 维护
- 该 per-cpu 变量在上下文切换时（`__switch_to`）更新为 `task_top_of_stack(next_p)`

关键注释（`arch/x86/include/asm/switch_to.h`）已直接写明：

- `sp0 always points to the entry trampoline stack, which is constant`

---

## 2. `TSS.sp0` 在何时被读

### 2.1 IDT 中断/异常从用户态进入内核时

这条路径下，**CPU 硬件在 CPL3->CPL0 切换时读取 TSS 的 RSP0/SP0**。  
这是硬件行为，因此你不会在内核代码里看到“显式读取 TSS.sp0 的指令”来完成这一步。

Linux 代码中能看到的是“谁写 `sp0`”：

- `arch/x86/include/asm/processor.h` 的 `native_load_sp0()`
- 早期 CPU 初始化中将其设置为 entry stack 顶部：
  - `arch/x86/kernel/cpu/common.c` 中 `load_sp0((unsigned long)(cpu_entry_stack(cpu) + 1));`

这说明内核预先准备好 `sp0`，真正读取发生在 CPU 进入门控时。

### 2.2 SYSCALL 从用户态进入内核时

`SYSCALL` 在 x86-64 下 **不会**自动按 TSS.sp0 切栈。  
入口汇编 `entry_SYSCALL_64` 直接手工把 `%rsp` 切到 per-cpu 的 `cpu_current_top_of_stack`：

- 文件：`arch/x86/entry/entry_64.S`
- 逻辑：`movq PER_CPU_VAR(cpu_current_top_of_stack), %rsp`

因此 SYSCALL 入口切栈依赖的是 per-cpu 当前任务栈顶，而非硬件自动读取 `sp0`。

---

## 3. `cpu_current_top_of_stack` 如何知道“当前进程 kernel stack”

### 3.1 在调度切换里写入

`__switch_to()` 中执行：

- `raw_cpu_write(current_task, next_p);`
- `raw_cpu_write(cpu_current_top_of_stack, task_top_of_stack(next_p));`

文件：`arch/x86/kernel/process_64.c`

也就是：调度器已经选定 `next_p`，架构切换代码直接把“下一任务的栈顶”写到本 CPU 的 per-cpu 变量。

### 3.2 `task_top_of_stack(next_p)` 从哪里来

定义在 `arch/x86/include/asm/processor.h`：

- `task_top_of_stack(task) ((unsigned long)(task_pt_regs(task) + 1))`
- `task_pt_regs(task)` 由 `task_stack_page(task)` + `THREAD_SIZE` - padding 推导

`task_stack_page(task)` 在 `include/linux/sched/task_stack.h` 中返回 `task->stack`。

因此数据来源链路是：

`task->stack` -> `task_pt_regs(task)` -> `task_top_of_stack(task)` -> `cpu_current_top_of_stack`（per-cpu）

这是一条纯软件维护链路，不依赖“读 TSS.sp0”来推断当前任务栈。

---

## 4. `pt_regs` 何时被填充

`struct pt_regs` 定义见：

- `arch/x86/include/asm/ptrace.h`

注意该结构在注释里区分了：

- 某些寄存器总是保存（callee-clobbered）
- 某些寄存器在某些入口路径按需补齐

### 4.1 SYSCALL 路径（`entry_SYSCALL_64`）

在 `arch/x86/entry/entry_64.S` 中：

1. 先压入 IRET frame 对应字段（`ss/sp/flags/cs/ip`）
2. 压入 `orig_ax`（系统调用号）
3. 调用 `PUSH_AND_CLEAR_REGS` 将通用寄存器压栈并清理

`PUSH_AND_CLEAR_REGS` 定义在 `arch/x86/entry/calling.h`，按 `pt_regs` 布局顺序构造寄存器帧。关键代码如下：

```asm
.macro PUSH_REGS rdx=%rdx rcx=%rcx rax=%rax save_ret=0 unwind_hint=1
	.if \save_ret
	pushq	%rsi		/* pt_regs->si */
	movq	8(%rsp), %rsi	/* temporarily store the return address in %rsi */
	movq	%rdi, 8(%rsp)	/* pt_regs->di (overwriting original return address) */
	.else
	pushq   %rdi		/* pt_regs->di */
	pushq   %rsi		/* pt_regs->si */
	.endif
	pushq	\rdx		/* pt_regs->dx */
	pushq   \rcx		/* pt_regs->cx */
	pushq   \rax		/* pt_regs->ax */
	pushq   %r8		/* pt_regs->r8 */
	pushq   %r9		/* pt_regs->r9 */
	pushq   %r10		/* pt_regs->r10 */
	pushq   %r11		/* pt_regs->r11 */
	pushq	%rbx		/* pt_regs->rbx */
	pushq	%rbp		/* pt_regs->rbp */
	pushq	%r12		/* pt_regs->r12 */
	pushq	%r13		/* pt_regs->r13 */
	pushq	%r14		/* pt_regs->r14 */
	pushq	%r15		/* pt_regs->r15 */
.endm

.macro PUSH_AND_CLEAR_REGS rdx=%rdx rcx=%rcx rax=%rax save_ret=0 clear_bp=1 unwind_hint=1
	PUSH_REGS rdx=\rdx, rcx=\rcx, rax=\rax, save_ret=\save_ret unwind_hint=\unwind_hint
	CLEAR_REGS clear_bp=\clear_bp
.endm
```

这条路径里，`pt_regs` 是入口汇编在当前内核栈上主动构造出来的。

### 4.2 中断/异常 IDT 路径

在 `arch/x86/entry/entry_64.S` 的 `idtentry_body` / `error_entry` 路径里：

- 通过 `PUSH_AND_CLEAR_REGS save_ret=1` 先形成入口寄存器帧
- 若来自用户态，进入 `sync_regs`（`arch/x86/kernel/traps.c`）
- `sync_regs` 将入口栈/IST 上的 `pt_regs` 同步复制到线程栈顶标准位置（`current_top_of_stack() - 1`）

因此“填充”可以分成两段：

1. 汇编入口先压栈形成初始 `pt_regs`
2. 必要时由 `sync_regs` 拷贝到线程栈规范位置，供后续 C 处理链使用

---

## 5. 为什么会看到 `sp0` 与 `cpu_current_top_of_stack` 同时存在

因为它们服务不同入口阶段：

- `cpu_current_top_of_stack`：SYSCALL 等路径快速切到“当前 task 线程栈”
- `sp0`：硬件特权切换与 trampoline/entry 场景依赖的入口栈锚点

在 `entry_64.S` 里还能看到返回路径临近 `SYSRET` 时切到 `TSS_sp0` 的片段，体现 entry trampoline 栈的用途。

---

## 6. Xen PV 与 FRED 相关分支（边界说明）

源码中存在 feature 分支：

- Xen PV：`update_task_stack()` 在 x86-64 可能用 `load_sp0(task_top_of_stack(task))`
- FRED：涉及 `fred_rsp0` 与相关 MSR，同传统 IDT/SYSCALL 细节不同

本文主线结论针对“常规 x86-64 原生（非 Xen PV 特化）IDT + SYSCALL 入口”。

---

## 7. 对“sp0 里是不是保存 process kernel stack”的精确定义

在 Linux x86-64 当前设计语境里，更准确的说法是：

- “当前进程（task）的内核栈顶”由 `cpu_current_top_of_stack` 维护并在 `__switch_to` 更新
- `TSS.sp0` 在原生路径不作为“每次调度都跟随 task 变化的线程栈顶”使用；其主要角色是 entry/trampoline 栈相关机制

这样就能解释：

- 为什么 SYSCALL 入口直接读 `cpu_current_top_of_stack`
- 为什么代码注释明确写 `sp0` 指向 constant entry trampoline stack

