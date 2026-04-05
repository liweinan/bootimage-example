# Linux x86：`task_top_of_stack` 与 `cpu_current_top_of_stack`（集中说明）

本文档从 **`/Users/weli/works/linux`** 静态校对，把原先分散在多篇文档中的同主题内容**合并为一处**：**内核栈顶地址从哪里来**、**`task_top_of_stack` 是宏还是变量**、**per-CPU `cpu_current_top_of_stack` 谁写谁读**、**与 `TSS.sp0` 的分工**。

**相关专文（勿与本篇重复阅读同一细节时来回跳）：**

- **TSS / IST / FRED、`load_sp0` 调用链、返回用户态读 `TSS_sp0`** → [LINUX_X86_KERNEL_STACK_SYSCALL_TSS.md](LINUX_X86_KERNEL_STACK_SYSCALL_TSS.md)（该文件 §4、§6、§7.2 等）。
- **`pt_regs` 字段名、`entry_SYSCALL_64` 压栈顺序、IDT/IRQ** → [LINUX_X86_64_ENTRY_AND_PT_REGS.md](LINUX_X86_64_ENTRY_AND_PT_REGS.md)。
- **`task_struct` / `mm_struct` / `thread_struct` 组织** → [LINUX_TASK_MM_THREAD_STRUCTS.md](LINUX_TASK_MM_THREAD_STRUCTS.md)。

---

## 1. 结论先行：`sp0` 与「当前 task 内核栈顶」是两套机制（原生 x86_64）

在常见 **原生 x86_64**（非 Xen PV 特化）下：

- **`TSS.x86_tss.sp0`**：多由 **`cpu_init()`** 里 **`load_sp0((unsigned long)(cpu_entry_stack(cpu) + 1))`** 设为 **per-CPU entry trampoline / entry stack** 一侧的锚点（**`arch/x86/kernel/cpu/common.c`**），**不是**「每个用户进程的内核栈顶」在每次调度里跟着变。
- **「当前 CPU 上即将运行的 task 的内核栈顶一侧」**：由 per-CPU 变量 **`cpu_current_top_of_stack`** 表示；在 **`__switch_to()`** 里写成 **`task_top_of_stack(next_p)`**（**`arch/x86/kernel/process_64.c`**）。
- **`switch_to.h`** 中 **`update_task_stack()`** 注释写明：`sp0 always points to the entry trampoline stack, which is constant`。**原生 x86_64** 下 **`load_sp0(task_top_of_stack(task))`** 主要出现在 **Xen PV** 等分支，**不要**当成「每次 `__switch_to` 都把进程栈顶写进 `sp0`」的通用模型。

**SYSCALL 入口**不依赖硬件自动用 `sp0` 切到线程栈：汇编 **`movq PER_CPU_VAR(cpu_current_top_of_stack), %rsp`**（**`arch/x86/entry/entry_64.S`** `entry_SYSCALL_64`）。

---

## 2. `task_top_of_stack`：宏展开，不是 `task_struct` 里单独维护的字段

在 **`arch/x86/include/asm/processor.h`**：

```c
#define task_top_of_stack(task) ((unsigned long)(task_pt_regs(task) + 1))

#define task_pt_regs(task)						\
({									\
	unsigned long __ptr = (unsigned long)task_stack_page(task);	\
	__ptr += THREAD_SIZE - TOP_OF_KERNEL_STACK_PADDING;		\
	((struct pt_regs *)__ptr) - 1;					\
})
```

**`task_stack_page(task)`** 在 **`include/linux/sched/task_stack.h`**：`#define task_stack_page(task) ((void *)(task)->stack)`。

含义：

- **没有**名为 `task_top_of_stack` 的全局存储单元被单独赋值；每次在 C 里写 **`task_top_of_stack(next)`** 都是 **按当前 `task` 当场宏展开**。
- 数值由 **`task->stack`** 与 **`THREAD_SIZE` / `TOP_OF_KERNEL_STACK_PADDING`** 的几何布局 **唯一确定**；**`task->stack`** 在线程创建路径（如 **`copy_process()`** / **`alloc_thread_stack_node()`**，**`kernel/fork.c`**）里分配并赋给 **`task->stack`** 后，对该 task 而言结果通常 **固定**（栈不迁移的前提下）。

**`TOP_OF_INIT_STACK`** 与 **`init_stack`** 同文件，用于 boot 期 per-CPU 初值（见 §4）。

---

## 3. `cpu_current_top_of_stack`：写什么、谁写、谁读

### 3.1 语义

写入值表示：**即将在该 CPU 上运行的 `next` 的内核栈缓冲区中，按架构约定用于「栈顶一侧」的虚拟地址**（与 **`task_top_of_stack`** 定义一致），由 **`task->stack` + 固定布局** 推出，**不是**从别的 per-CPU 变量再拷贝一层。

### 3.2 x86_64：`__switch_to`（`arch/x86/kernel/process_64.c`）

```671:672:arch/x86/kernel/process_64.c
	raw_cpu_write(current_task, next_p);
	raw_cpu_write(cpu_current_top_of_stack, task_top_of_stack(next_p));
```

紧接着 **`update_task_stack(next_p)`**（**`arch/x86/include/asm/switch_to.h`**），行为随 **Xen / FRED** 等配置变化，见 [LINUX_X86_KERNEL_STACK_SYSCALL_TSS.md](LINUX_X86_KERNEL_STACK_SYSCALL_TSS.md) §4。

### 3.3 i386：`__switch_to`（`arch/x86/kernel/process_32.c`）

```197:200:arch/x86/kernel/process_32.c
	this_cpu_write(cpu_current_top_of_stack,
		       (unsigned long)task_stack_page(next_p) +
		       THREAD_SIZE);
```

同函数内 **`update_task_stack`**、**`current_task`** 的写入顺序与 64 位不同，阅读时注意。

### 3.4 boot / AP

- **静态初值**：**`DEFINE_PER_CPU_CACHE_HOT(unsigned long, cpu_current_top_of_stack) = TOP_OF_INIT_STACK`**（**`arch/x86/kernel/cpu/common.c`** ~2176）。
- **仅 32 位 AP 路径**：**`common_cpu_up()`** 内 **`#ifdef CONFIG_X86_32`**：**`per_cpu(cpu_current_top_of_stack, cpu) = task_top_of_stack(idle)`**（**`arch/x86/kernel/smpboot.c`**）；**x86_64** 无对等语句。

### 3.5 读取（syscall / 兼容入口示例）

- **`arch/x86/entry/entry_64.S`** **`entry_SYSCALL_64`**：`movq PER_CPU_VAR(cpu_current_top_of_stack), %rsp`（约 95 行，以本树为准）。
- **`entry_64_compat.S`**、**`entry_32.S`** 等同理装入 RSP/ESI。
- **`current_top_of_stack()`**（**`arch/x86/include/asm/processor.h`**）：读 per-CPU 或 `const_cpu_current_top_of_stack` 别名（见 **`vmlinux.lds.S`**）。

**返回用户态**常涉及读 **`TSS_sp0`** 切 trampoline，与 **进入** syscall 时用 **`cpu_current_top_of_stack`** 不同；见 [LINUX_X86_KERNEL_STACK_SYSCALL_TSS.md](LINUX_X86_KERNEL_STACK_SYSCALL_TSS.md) §6.2。

---

## 4. `next_p` 是什么（不是「刚进内核的用户进程」）

**`next_p`** 即 **`__switch_to(..., struct task_struct *next_p)`** 里的 **`next`**：切换完成后在该 CPU 上成为 **`current`** 的 **task**。可以是 **用户任务、内核线程、idle** 等。**`__switch_to`** 始终在内核路径执行；与「**单次**用户态→内核态（syscall/异常）」不是同一叙事，勿混。

---

## 5. 与 `thread_struct.sp0`（仅 32 位字段名）

**`CONFIG_X86_64`** 下 **`struct thread_struct`** **没有** **`sp0`** 成员（仅有 **`sp`** 等）；**`sp0`** 仅在 **`CONFIG_X86_32`** 分支存在。**x86_64** 上 **`cpu_current_top_of_stack`** **不是**从 **`thread_struct.sp0`** 读出。

---

## 6. 调度链：谁调用到 `raw_cpu_write(cpu_current_top_of_stack, …)`（主干）

下列行号以 **`/Users/weli/works/linux`** 当前树为准：

| 步骤 | 位置（约） |
|------|------------|
| `schedule()` | `kernel/sched/core.c` ~6869 |
| `__schedule_loop()` | 同文件 ~6860（内调 `__schedule()`） |
| `__schedule()` | 同文件 ~6662 |
| `context_switch()` → `switch_to()` | 同文件 ~5341、`~5397` |
| `switch_to` 宏 | `arch/x86/include/asm/switch_to.h` |
| `__switch_to_asm` | `arch/x86/entry/entry_64.S` ~177，`jmp __switch_to` ~216 |
| `__switch_to()` | `arch/x86/kernel/process_64.c` ~611，`raw_cpu_write(cpu_current_top_of_stack, …)` ~672 |

---

## 7. i386 `copy_thread` 与 `thread.sp0`（与栈几何一致时的初始化）

**32 位** **`copy_thread()`** 会设 **`p->thread.sp0 = (unsigned long)(childregs + 1)`**（**`arch/x86/kernel/process.c`**），与 **`task_pt_regs` / 栈布局** 一致，那是 **`thread_struct.sp0` 字段**的初始化，与 **64 位** **`thread_struct`** 成员集合不同。

---

## 8. 源码摘录（便于对照本树）

**`entry_SYSCALL_64` 切栈（节选）** — `arch/x86/entry/entry_64.S`：

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

---

## 9. 文档说明

- 配置 **`CONFIG_XEN_PV`、`CONFIG_X86_FRED`、`CONFIG_PARAVIRT_*`** 会改变 **`update_task_stack` / `load_sp0`** 分支；细节以你树内 **`#ifdef`** 为准。
- **行号**随内核版本漂移；换分支后请用 **`rg`** / 直接打开文件核对。

**文档版本**：1.0  
**最后更新**：2026-04-04  
**校对内核树**：`/Users/weli/works/linux`
