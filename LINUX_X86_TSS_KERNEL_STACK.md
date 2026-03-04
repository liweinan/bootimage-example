# x86 TSS 与内核栈：Q&A 补充

本文档以 Q&A 形式补充 **x86 TSS、内核栈与用户态栈** 的关系，作为 [LINUX_KERNEL_PROCESS_AND_THREAD_STRUCT.md](LINUX_KERNEL_PROCESS_AND_THREAD_STRUCT.md) 的配套阅读。结合 **Intel® 64 and IA-32 Architectures Software Developer’s Manual, Vol 3A: System Programming Guide, Part 1**（以下简称 SDM Vol 3A）与 Linux 内核源码。源码路径以 `linux/` 表示（如 `/Users/weli/works/linux`）。

- **SDM Vol 3A**：Chapter 7（Task Management）描述 TSS；**Figure 7-2** 为 32 位 TSS 的布局（ESP0/SS0～ESP2/SS2、CR3、EIP、EFLAGS、通用寄存器、段选择子、LDT、I/O bitmap base 等）；64 位模式下硬件不再做任务切换，但仍有 64-bit TSS，含 RSP0/RSP1/RSP2、IST1～IST7、I/O map base（见 SDM 7.7 节等）。本文档中“与 SDM 对应”处均指上述章节与图表。

---

## 一、内核栈 vs 用户态栈 vs TSS

### Q1. TSS 里保存的是“用户态栈在内核里的快照”，还是“内核自己的栈”？

**答：是内核自己的栈的栈顶指针，不是用户态栈的快照。**

- **TSS.sp0** 存的是：**当前要用的内核栈的栈顶**（RSP 将要被设成的值）。
- 从用户态进内核（系统调用、中断、异常）时，CPU 用 TSS.sp0 把 RSP 切到这条内核栈上；内核再在这条栈上保存 **pt_regs**（里面才有用户态的 RSP、RIP、通用寄存器等）。
- 因此：**TSS** 只负责“切到哪条内核栈”；**用户态现场的快照** 在内核栈上的 **pt_regs** 里。

### Q2. TSS.sp0 指向的“当前要用的内核栈顶”是 per-task 还是 per-CPU？

**答：存储位置是 per-CPU，语义上是“当前在该 CPU 上运行的那个 task 的内核栈顶”（即 per-task 的栈顶）。**

- TSS 本身是 **per-CPU** 的：`DECLARE_PER_CPU_PAGE_ALIGNED(struct tss_struct, cpu_tss_rw)`，每个 CPU 一份。
- 但 **TSS.sp0 的值** 在调度切换时会更新：`switch_to` 里对下一个任务调用 `load_sp0(task_top_of_stack(next))`，把当前 CPU 的 TSS.sp0 设成 **即将运行的那个 task 的内核栈顶**。
- 所以：**sp0 的“存贮槽”是 per-CPU，里面存的值 = 当前在该 CPU 上运行的任务的内核栈顶**，即本质上是 per-task 的栈顶，只是通过 per-CPU 的 TSS 来指向它。

### Q3. 内核栈是 per-CPU 还是 per-task？

**答：进程上下文用的那条内核栈是 per-task；此外还有 per-CPU 的栈。**

- **每个 task_struct 有一条自己的内核栈**（`task_stack_page(task)`，大小 THREAD_SIZE）。调度切到某任务时，会 `load_sp0(task_top_of_stack(next))`，让 TSS.sp0 指向该任务的内核栈顶。
- **Per-CPU 的栈** 另有用途：**entry stack**（系统调用/中断入口的 trampoline）、**IRQ stack**（硬中断）、**IST 栈**（NMI、Double Fault、MCE 等）。它们是每 CPU 一份，用于入口或异常，不是“当前进程”的日常执行栈。

小结：**“当前跑进程上下文时用的那条栈” = per-task 的内核栈；TSS.sp0 指向的就是这条栈的栈顶。**

### Q4. 用户态有没有自己的 stack / stack frame？

**答：有。**

- 每个用户态任务在**用户虚拟地址空间**里有一条**用户态栈**，用户态 RSP 指向这条栈；上面有正常的函数调用 stack frame（返回地址、局部变量等）。
- 发生系统调用/中断时：**用户 RSP** 被保存进内核栈上的 **pt_regs**；CPU 通过 TSS.sp0 切到**内核栈**，内核在内核栈上继续执行。
- 因此：用户空间有自己独立的栈和 stack frame；内核栈上通过 pt_regs 保存的是“用户态 RSP/现场”的副本，而不是把用户栈搬进内核。

### Q5. 每个 task 自己的内核栈里，内容有什么区别？

**答：每个任务的内核栈上保存的是“该任务上次在内核里执行时的现场与调用链”，因此内容因任务而异。**

- **共同点**：都是一块大小为 THREAD_SIZE 的内核栈；从高地址向低地址增长；栈顶由 TSS.sp0（或 thread.sp0）指向。
- **内容差异**：
  - **pt_regs**：若该任务是从用户态进内核（syscall/中断），栈上会有一份 pt_regs，里面是该任务自己的**用户态 RSP、RIP、段寄存器、通用寄存器**等，不同任务的用户态现场不同（pt_regs 的来源与恢复见 Q5.1）。
  - **调度切换帧**：若该任务被切换出去，栈顶附近会有 `switch_to` 等保存的返回地址和少量寄存器，指向该任务再次被调度时该恢复的位置。
  - **内核调用链**：该任务在内核里执行的函数调用（syscall 处理、VFS、驱动等）会在栈上形成不同的调用栈；不同任务可能处于不同的调用深度、不同的代码路径，因此栈上的帧数量和内容都不同。
- 所以：**每个 task 的内核栈“布局类型”相同（都是内核栈 + pt_regs/switch 帧等），但具体内容 = 该任务自己的用户态现场 + 该任务自己的内核调用栈**，任务之间互不相同。

### Q5.1 pt_regs 是从用户空间“拷贝”进内核的吗？切换任务时再“拷贝回”用户空间？

**答：不是。pt_regs 存的是“进内核那一刻 CPU 寄存器里的值”，是保存（store）到内核栈上，不是从用户空间内存拷数据；返回时是把这些值从 pt_regs 恢复到 CPU 寄存器，再 iret/sysret，也没有“拷贝回用户空间”。**

- **进内核时**：发生 syscall/中断时，**当前 CPU 的寄存器**里就是用户态现场（RSP 指向用户栈、RIP 指向用户代码等）。entry 汇编把这些**寄存器的值**按 pt_regs 布局**写进当前内核栈**（push 或 mov 到栈上）。并没有从用户虚拟地址空间“拷贝一块内存”到内核；只是把**寄存器内容**存到内核栈上的 pt_regs 里。用户态栈本身始终在用户空间，没有被搬动。
- **返回用户态时**：退出路径从该任务内核栈上的 pt_regs 里**读出**保存的 RIP、RSP、段寄存器、通用寄存器等，**装回 CPU 寄存器**，然后 iret 或 sysret 切回用户态。CPU 用恢复后的 RSP 继续访问用户栈。同样没有“把 pt_regs 拷贝回用户空间”——用户空间只是普通内存；我们只是**恢复 CPU 寄存器**，让 RSP 再次指向用户栈、RIP 指向用户代码。
- **任务切换时**：被换下的任务的内核栈（连同上面的 pt_regs）原样留在内核；不会把 pt_regs “拷回”该任务的用户空间。等该任务再次被调度到时，先恢复其内核栈（TSS.sp0 / thread.sp0），若它要从内核返回用户态，再按上面一步从**该任务自己的 pt_regs** 恢复寄存器并 iret。

小结：**pt_regs = 进内核时把 CPU 寄存器保存到内核栈；返回时从内核栈上的 pt_regs 恢复到 CPU 寄存器**。没有“用户空间↔内核空间”的数据拷贝。

### Q5.2 pt_regs 保存在哪里？里面都保存了哪些寄存器的值？

**答：pt_regs 保存在当前任务的内核栈上，位于内核虚拟地址空间。** 布局由 `arch/x86/include/asm/ptrace.h` 中的 `struct pt_regs` 定义。

- **位置**：`task_pt_regs(task)` 指向该 task 内核栈顶附近的 pt_regs（`arch/x86/include/asm/processor.h` 第 646–653 行）：`task_stack_page(task)` 得到该任务的内核栈页（即 `task->stack`，见 `include/linux/sched/task_stack.h`），加上 `THREAD_SIZE - TOP_OF_KERNEL_STACK_PADDING` 后向下一个 pt_regs 的偏移，得到“栈顶的 pt_regs”。因此 **pt_regs 始终在内核栈上，即内核空间**。

- **x86_32 保存的寄存器**（`arch/x86/include/asm/ptrace.h` 第 12–55 行）：通用寄存器 `ax,bx,cx,dx,si,di,bp`；段寄存器 `ds,es,fs,gs,cs,ss`（及 padding）；`orig_ax`（系统调用号/错误码）；`ip`、`flags`、`sp`。

- **x86_64 保存的寄存器**（同文件第 103–171 行）：通用 `r15,r14,r13,r12,bp,bx,r11,r10,r9,r8,ax,cx,dx,si,di`；`orig_ax`（系统调用号/错误码/中断号）；`ip`；`cs`/`csx`；`flags`；`sp`；`ss`/`ssx`。即用户态可见的通用寄存器、ip、sp、段选择子、flags 及 orig_ax。

### Q5.3 TSS 是 per-CPU 的，所以同一时间每个 CPU 只能处理一份 pt_regs / 一个任务？

**答：是的。** TSS 是 per-CPU 的（`DECLARE_PER_CPU_PAGE_ALIGNED(struct tss_struct, cpu_tss_rw)`，`arch/x86/include/asm/processor.h` 第 411 行）；**pt_regs 并不存在 TSS 里**，而是在**当前任务的内核栈**上。TSS.sp0 指向的是当前在该 CPU 上运行的任务的内核栈顶，因此每个 CPU 在同一时刻只有一个“当前任务”，也就只正在使用这一份 pt_regs（即该任务内核栈顶上的那一份）。其它任务的 pt_regs 留在各自的内核栈上，等被调度到时再使用。

### Q5.4 pt_regs 的保存能替代手工的 push/pop 吗？（例如实模式下需要自己 push/pop regs）

**答：不能替代；pt_regs 只是“保存成什么样”的标准布局，真正往里面填的还是入口汇编。** 在 x86 上，从用户态进内核时 CPU 不会自动把通用寄存器等压栈（syscall 几乎不压；中断/异常会压部分如 RIP/CS/RFLAGS/SS/RSP，但 GPR 仍要内核保存）。入口代码必须**按 pt_regs 的布局**把寄存器写进当前内核栈。

例如 64 位 syscall 入口（`arch/x86/entry/entry_64.S` 第 99–117 行）：注释写明 “Construct struct pt_regs on stack”，随后用 `pushq` 依次压入 `ss`、用户 `rsp`（从 TSS_sp2 取）、`r11`（flags）、`cs`、`rcx`（ip）、`orig_ax`，再 `PUSH_AND_CLEAR_REGS` 压入其余通用寄存器。也就是说：**仍然是“手工”把寄存器保存到栈上，只是保存的布局与 C 里的 `struct pt_regs` 一致**，便于 C 层通过 `struct pt_regs *regs` 访问。与实模式下自己 push 若干寄存器、返回前 pop 同理，只是布局被固定成 pt_regs。

### Q5.5 每个 process 都有自己的内核栈吗？

**答：更准确地说，每个 task_struct（每个调度单位）都有自己的一条内核栈。** 与 [LINUX_KERNEL_PROCESS_AND_THREAD_STRUCT.md](LINUX_KERNEL_PROCESS_AND_THREAD_STRUCT.md) 一致：用户态“进程”若只有主线程，则一个进程对应一个 task_struct，一条内核栈；若为多线程进程，则同一进程内有多个 task_struct（同组线程），**每个线程一条内核栈**，即一个多线程进程对应多条内核栈。

内核实现：每个 `task_struct` 有 `void *stack`（见 `include/linux/sched/task_stack.h` 中 `task_stack_page(task)` 即 `task->stack`）；栈大小为 `THREAD_SIZE`（x86_64 在 `arch/x86/include/asm/page_64_types.h` 中为 `PAGE_SIZE << THREAD_SIZE_ORDER`）。`task_top_of_stack(task)` 与 `task_pt_regs(task)` 均基于 `task_stack_page(task)` 与 `THREAD_SIZE` 计算（`arch/x86/include/asm/processor.h` 第 646–653 行）。

---

## 二、TSS 中哪些字段用于栈切换、哪些不用

### Q6. TSS 里哪些字段被用来切换内核栈？

**答：**

| 字段 | 架构 | 用途 |
|------|------|------|
| **sp0** | 32/64 位 | 从低特权级进 ring 0 时，CPU 用 TSS.sp0 作为新 RSP。调度时 `load_sp0(task_top_of_stack(next))` 更新；entry 从 `PER_CPU_VAR(cpu_tss_rw + TSS_sp0)` 取栈。 |
| **ss0** | 仅 32 位 | 进 ring 0 时 SS 由硬件从 TSS 读取。 |
| **sp1** | 仅 32 位 | 内核在此保存当前任务的 `thread.sp0`，供 entry 等取“当前任务内核栈顶”；不用于 ring 1 栈。 |
| **ist[0..4]** | 仅 64 位 | Double Fault、NMI、Debug、MCE、#VC 的 IST 栈顶；对应异常时 CPU 用其切换栈。 |

### Q7. TSS 里哪些字段不再用于任务/栈切换？

**答：**

- **32 位**：back_link；sp2/ss2（不用 ring 2）；__cr3、ip、flags、通用寄存器、段寄存器、ldt、trace（硬件任务切换未用）；ss1 仅作 MSR_IA32_SYSENTER_CS 缓存。
- **64 位**：sp1（不用 ring 1）；sp2 仅作 entry_SYSCALL_64 的 scratch（存用户 RSP）；reserved*；ist[5]、ist[6] 未用。
- **与栈无关但在用**：io_bitmap_base（I/O 权限位图偏移）。

### Q8. 内核里的 TSS 结构长什么样？

**答：** 每 CPU 一个 `struct tss_struct`，内含硬件可见的 `struct x86_hw_tss x86_tss` 与 `struct x86_io_bitmap io_bitmap`。

**x86_64**（`arch/x86/include/asm/processor.h` 第 308–327 行）：

```c
struct x86_hw_tss {
	u32			reserved1;
	u64			sp0;
	u64			sp1;
	u64			sp2;	/* entry_SYSCALL_64 用作 scratch */
	u64			reserved2;
	u64			ist[7];
	u32			reserved3;
	u32			reserved4;
	u16			reserved5;
	u16			io_bitmap_base;
} __attribute__((packed));
```

**x86_32**（同文件，第 262–305 行）：含 back_link、sp0/ss0、sp1/ss1、sp2/ss2、__cr3、ip、flags、通用寄存器、段选择子、ldt、trace、io_bitmap_base 等，与 **SDM Vol 3A Figure 7-2**（32-bit TSS layout）一一对应。

---

## 三、简要对照表

| 类别 | 32 位 | 64 位 |
|------|--------|--------|
| **用于内核栈切换** | sp0、ss0、sp1（存 thread.sp0） | sp0、ist[0..4] |
| **不再用于栈/任务切换** | back_link、sp2/ss2、cr3/ip/标志/通用寄存器/段/ldt/trace；ss1 仅作 SYSENTER_CS 缓存 | sp1、sp2（仅 scratch）、reserved*、ist[5]/ist[6] |
| **其他在用** | io_bitmap_base | io_bitmap_base |

---

## 四、参考源码路径与 SDM

**Linux 内核（linux 树）**

- `arch/x86/include/asm/processor.h` — `struct x86_hw_tss`、`struct tss_struct`、`DECLARE_PER_CPU_PAGE_ALIGNED(cpu_tss_rw)`、`task_pt_regs()`/`task_top_of_stack()`、`native_load_sp0()`
- `arch/x86/include/asm/ptrace.h` — `struct pt_regs`（32 位约 12–55 行，64 位约 103–171 行）
- `include/linux/sched/task_stack.h` — `task_stack_page()`（即 `task->stack`）
- `arch/x86/include/asm/page_64_types.h` — `THREAD_SIZE`、`IST_INDEX_*`
- `arch/x86/include/asm/switch_to.h` — `load_sp0()`、sp1/thread.sp0 的更新
- `arch/x86/entry/entry_64.S` — `entry_SYSCALL_64` 中 “Construct struct pt_regs on stack”、TSS_sp0/TSS_sp2 的用法
- `arch/x86/entry/entry_32.S` — 32 位 entry 对 TSS_sp0 的使用
- `arch/x86/kernel/cpu/common.c` — `tss_setup_ist()`、`load_sp0()` 初始化、`tss_setup_io_bitmap()`
- `arch/x86/kernel/asm-offsets_32.c` — sp1 与 entry stack 的偏移
- `arch/x86/kernel/idt.c` — IST 向量的定义

**Intel SDM**

- **Intel® 64 and IA-32 Architectures Software Developer’s Manual, Volume 3A: System Programming Guide, Part 1**
- Chapter 7（Task Management）、**Figure 7-2**（32-bit TSS layout）、7.7 节（64-bit TSS）
