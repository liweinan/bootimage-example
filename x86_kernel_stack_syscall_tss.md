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

### 3.4 写入值的含义：来自「next 的内核栈顶」的虚拟地址

`cpu_current_top_of_stack` 里写入的**数值**表示：**即将在该 CPU 上运行的 `next` 任务的内核栈布局中的「栈顶一侧」虚拟地址**（与 `task_top_of_stack` 的几何定义一致）。该值由架构侧用**固定栈布局**从 `task->stack` **当场宏展开算出**，并不是从别的 per-CPU 变量再拷贝一层。

#### `next_p` 指什么

`next_p` 是 `__switch_to` 形参 **`struct task_struct *next`** 在本函数体内的名字，表示**本次上下文切换完成之后**，在该 CPU 上即将成为 **`current`** 的那一个 **`task_struct`**（由调度器选出的「下一个」可运行实体）。

它**不等同于**「当前正在从用户态进入内核的那一个用户进程」：`__switch_to` 始终在内核路径上被调用；`next` 可以是**有用户态的普通进程/线程**，也可以是**只在内核运行的内核线程**、**idle**，或其它由 `task_struct` 表示的对象。若 `next` 确实有用户态映射，则之后当该 CPU **返回到用户态**时，才会执行到**那个**任务的用户地址空间。

**归纳：** `next_p` 就是**下一个被调度到该 CPU 上运行的** `task`，用来更新 **`current_task`**、**`cpu_current_top_of_stack`** 等，使 per-CPU 状态与**即将**被运行的那条线程的**内核栈**几何一致。不能把它说成「指向当前切换到 kernel space 的用户程序进程」——那是把「**调度换线程**」和「**单次用户态→内核态**」混在一起了。

#### x86_64（`__switch_to`，`arch/x86/kernel/process_64.c`）

```671:672:arch/x86/kernel/process_64.c
	raw_cpu_write(current_task, next_p);
	raw_cpu_write(cpu_current_top_of_stack, task_top_of_stack(next_p));
```

因此来源就是 `task_top_of_stack(next_p)`。

`task_top_of_stack` 与 `task_pt_regs` 定义在 **`arch/x86/include/asm/processor.h`**（`task_stack_page` 来自 **`include/linux/sched/task_stack.h`**：`task_stack_page(task)` 为 `(task)->stack`）：

```646:653:arch/x86/include/asm/processor.h
#define task_top_of_stack(task) ((unsigned long)(task_pt_regs(task) + 1))

#define task_pt_regs(task) \
({									\
	unsigned long __ptr = (unsigned long)task_stack_page(task);	\
	__ptr += THREAD_SIZE - TOP_OF_KERNEL_STACK_PADDING;		\
	((struct pt_regs *)__ptr) - 1;					\
})
```

含义：`task_pt_regs(task)` 指向该线程栈末尾附近的 `struct pt_regs`；`task_pt_regs(task) + 1` 为指针算术，指向 **`pt_regs` 对象紧上方** 的地址，即该线程内核栈缓冲区**高地址端**一侧，用作「栈顶」相关的约定地址。`task->stack` 在 **`fork` / `kthread`** 等路径里分配并赋给 `task->stack`（见 **`kernel/fork.c`** 等）。**结论：** 该 per-CPU 值由 **`next` 的 `task->stack` 与 `THREAD_SIZE` / `TOP_OF_KERNEL_STACK_PADDING` 共同决定**，不是从 `thread.sp0` 读入——在 **`CONFIG_X86_64` 下 `struct thread_struct` 根本没有 `sp0` 成员**（仅有 `sp` 等；`sp0` 仅在 **`CONFIG_X86_32`** 分支中存在，见同文件 `thread_struct` 定义）。

#### i386（`__switch_to`，`arch/x86/kernel/process_32.c`）

写的是 **`task_stack_page(next_p) + THREAD_SIZE`**（与 64 位同一思想：指向该线程内核栈缓冲区的上端），见：

```197:200:arch/x86/kernel/process_32.c
	this_cpu_write(cpu_current_top_of_stack,
		       (unsigned long)task_stack_page(next_p) +
		       THREAD_SIZE);
```

（同函数中 **`update_task_stack`**、`current_task` 的写入顺序与 64 位不同，阅读时注意上下文。）

#### boot 初值与其它写入

- **per-CPU 静态初值**：`TOP_OF_INIT_STACK`（`arch/x86/kernel/cpu/common.c`：`DEFINE_PER_CPU_CACHE_HOT(..., cpu_current_top_of_stack) = TOP_OF_INIT_STACK`）。
- **仅 32 位、AP 启动路径**：`common_cpu_up()` 里在 **`#ifdef CONFIG_X86_32`** 下执行 `per_cpu(cpu_current_top_of_stack, cpu) = task_top_of_stack(idle)`（`arch/x86/kernel/smpboot.c`）；**x86_64 AP 不经此赋值**（同文件该段在 `#ifdef` 外无对等语句）。

**归纳：** 写入 `cpu_current_top_of_stack` 的值**在语义上**就是当前 CPU 接下来要跑的那个 **`task` 所对应的「内核栈顶一侧」地址**；x86_64 上由 **`task_top_of_stack(next)`** 根据 **`next->stack`** 与线程栈布局计算，**不是**从 **`thread_struct.sp0`** 取得（且 64 位 **`thread_struct` 无 `sp0` 字段**）。

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

**共性：真正写 `cpu_tss_rw.x86_tss.sp0` 的内联路径**

```
native_load_sp0()                         arch/x86/include/asm/processor.h:534
└── this_cpu_write(cpu_tss_rw.x86_tss.sp0, sp0)   processor.h:536
```

```
load_sp0()                                arch/x86/include/asm/processor.h:569
└── native_load_sp0()                     arch/x86/include/asm/processor.h:571
```

- 若 **`CONFIG_PARAVIRT_XXL`**：`load_sp0()` 在 **`arch/x86/include/asm/paravirt.h:116`**，经 **`PVOP_VCALL1(cpu.load_sp0, sp0)`**（`:118`）进入 hypervisor 后端，未必落到上面的 `native_load_sp0`。

**分支 A — BSP/AP 初始化（原生 trampoline sp0）**

```
cpu_init()                                arch/x86/kernel/cpu/common.c:2384
└── load_sp0(cpu_entry_stack(cpu) + 1)    arch/x86/kernel/cpu/common.c:2424
    └── (见上 load_sp0 → native_load_sp0)
```

**分支 B — 上下文切换（仅 x86_64 且 Xen PV、非 FRED：`update_task_stack` 内调 `load_sp0`）**

```
__switch_to()                             arch/x86/kernel/process_64.c:611
└── update_task_stack(next_p)             arch/x86/kernel/process_64.c:675
    └── update_task_stack() [inline]       arch/x86/include/asm/switch_to.h:69
        └── load_sp0(task_top_of_stack(task))   switch_to.h:77
            └── (见上 load_sp0 → native_load_sp0 或 paravirt)
```

**分支 C — Xen PV `load_sp0` 后端（表项指向时）**

```
xen_load_sp0()                            arch/x86/xen/enlighten_pv.c:1010
├── MULTI_stack_switch / xen_mc_issue     enlighten_pv.c:1014–1016
└── this_cpu_write(cpu_tss_rw.x86_tss.sp0, sp0)   enlighten_pv.c:1017
```

**静态初值（毒化，随后由 `cpu_init` 等覆盖）**

```
DEFINE_PER_CPU_PAGE_ALIGNED(cpu_tss_rw)   arch/x86/kernel/process.c:67
└── .x86_tss.sp0 = …                      arch/x86/kernel/process.c:75
```

### 8.2 读取链（软件从 `x86_tss.sp0` 取到寄存器或 C 变量）

**分支 A — x86_64：`entry_SYSCALL_64` 经 SYSRET 返回前切 trampoline**

```
syscall_return_via_sysret                 arch/x86/entry/entry_64.S:137
└── movq PER_CPU_VAR(cpu_tss_rw+TSS_sp0), %rsp   entry_64.S:146
```

**分支 B — x86_64：PTI 下 IRET 回用户态慢路径**

```
.Lpti_restore_regs_and_return_to_usermode arch/x86/entry/entry_64.S:582
└── movq PER_CPU_VAR(cpu_tss_rw+TSS_sp0), %rsp   entry_64.S:591
```

**分支 C — C 内读 `sp0`（示例：双故障等路径）**

```
(异常处理逻辑)                            arch/x86/kernel/traps.c:530
└── this_cpu_read(cpu_tss_rw.x86_tss.sp0)

(另一处借用栈顶)                          arch/x86/kernel/traps.c:986
└── __this_cpu_read(cpu_tss_rw.x86_tss.sp0)
```

**分支 D — i386 入口汇编**

```
PER_CPU_VAR(cpu_tss_rw+TSS_sp0) → 寄存器   arch/x86/entry/entry_32.S:530
PER_CPU_VAR(cpu_tss_rw+TSS_sp0) → 寄存器   arch/x86/entry/entry_32.S:576
PER_CPU_VAR(cpu_tss_rw+TSS_sp0) → 寄存器   arch/x86/entry/entry_32.S:849
```

---

## 9. Call chain：`syscall` 线与 `cpu_current_top_of_stack`

### 9.1 写入链（谁在更新 per-CPU 的 `cpu_current_top_of_stack`）

**主链 — 调度切换（常见入口 `schedule()`；亦可经抢占等直接进入 `__schedule()`，自 `context_switch` 起以下相同）**

```
schedule()                                kernel/sched/core.c:6869
└── __schedule_loop()                     kernel/sched/core.c:6860
    └── __schedule()                      kernel/sched/core.c:6662
        └── context_switch()              kernel/sched/core.c:5341
            └── switch_to(prev,next,prev) kernel/sched/core.c:5397
                └── switch_to 宏展开      arch/x86/include/asm/switch_to.h:49
                    └── __switch_to_asm() arch/x86/entry/entry_64.S:177
                        ├── 切换 threadsp  arch/x86/entry/entry_64.S:191–192
                        ├── FILL_RETURN_BUFFER（若适用） entry_64.S:206
                        └── jmp __switch_to                arch/x86/entry/entry_64.S:216
                            └── __switch_to()              arch/x86/kernel/process_64.c:611
                                └── raw_cpu_write(cpu_current_top_of_stack, task_top_of_stack(next_p))   process_64.c:672
```

- **i386** 同一调度链直到 `__switch_to`：`arch/x86/entry/entry_32.S` 中 **`__switch_to_asm`**（约 **`672`** 行起，以文件为准）→ **`arch/x86/kernel/process_32.c:155`** `__switch_to` → **`this_cpu_write(cpu_current_top_of_stack, …)`** **`process_32.c:198`**。

**其它写入（非每次调度）**

```
DEFINE_PER_CPU_CACHE_HOT(cpu_current_top_of_stack)=TOP_OF_INIT_STACK   arch/x86/kernel/cpu/common.c:2176
```

```
common_cpu_up()                           arch/x86/kernel/smpboot.c:817
└── per_cpu(cpu_current_top_of_stack,cpu)=task_top_of_stack(idle)   smpboot.c:834
    （整段仅在 #ifdef CONFIG_X86_32 内；x86_64 AP 无此赋值）
```

### 9.2 读取链（syscall 相关：进入内核时把该 per-CPU 值装进 RSP）

**配置链 — MSR `LSTAR` 指向 64 位 syscall 入口（非 FRED 时）**

```
cpu_init()                                arch/x86/kernel/cpu/common.c:2384
└── syscall_init()  /* 调用点 */          arch/x86/kernel/cpu/common.c:2403
```

```
syscall_init()  /* 定义 */                arch/x86/kernel/cpu/common.c:2234
└── idt_syscall_init()  /* 调用点 */       arch/x86/kernel/cpu/common.c:2247
```

```
idt_syscall_init()  /* 定义起 */         arch/x86/kernel/cpu/common.c:2198
├── wrmsrq(MSR_LSTAR, entry_SYSCALL_64)   arch/x86/kernel/cpu/common.c:2200
└── wrmsrq_cstar(entry_SYSCALL_compat)    arch/x86/kernel/cpu/common.c:2203
    （后者在 `ia32_enabled()` 为真时执行）
```

（**FRED** 时 **`syscall_init`** 内 **不**调用 **`idt_syscall_init`**，见 **`common.c:2246–2247`**。）

**运行链 — 64 位用户态 `syscall`**

```
用户态 syscall（CPU 硬件）               (入口 RIP 由 LSTAR 等决定)
└── entry_SYSCALL_64                      arch/x86/entry/entry_64.S:87
    └── movq PER_CPU_VAR(cpu_current_top_of_stack), %rsp   entry_64.S:95
        └── call do_syscall_64            arch/x86/entry/entry_64.S:121
            └── do_syscall_64()           arch/x86/entry/syscall_64.c:87
```

**运行链 — IA-32 兼容 syscall（`entry_SYSCALL_compat`）**

```
entry_SYSCALL_compat                      arch/x86/entry/entry_64_compat.S:183
└── movq PER_CPU_VAR(cpu_current_top_of_stack), %rsp   entry_64_compat.S:196
```

**运行链 — IA-32 兼容 SYSENTER（`entry_SYSENTER_compat`）**

```
entry_SYSENTER_compat                     arch/x86/entry/entry_64_compat.S:50
└── movq PER_CPU_VAR(cpu_current_top_of_stack), %rsp   entry_64_compat.S:60
```

**i386 内核入口（示例行号）**

```
PER_CPU_VAR(cpu_current_top_of_stack)→%esp   arch/x86/entry/entry_32.S:1156
PER_CPU_VAR(cpu_current_top_of_stack)→%esi  arch/x86/entry/entry_32.S:1220
```

**C 侧读（非 syscall 汇编主路径）**

```
current_top_of_stack()                    arch/x86/include/asm/processor.h:546
├── this_cpu_read_const(const_cpu_current_top_of_stack)   processor.h:554  (CONFIG_USE_X86_SEG_SUPPORT)
└── this_cpu_read_stable(cpu_current_top_of_stack)       processor.h:556
```

**与返回用户态：** 进内核侧读 **`cpu_current_top_of_stack`**；返回前常读 **`TSS_sp0` 切 trampoline**（见 **§8.2**），再 **`SYSRET`/`IRET`**。

---

## 10. 文档说明

- 本文仅作内核阅读索引与概念对齐，**具体行为以当前配置（`CONFIG_XEN_PV`、`CONFIG_X86_FRED`、`CONFIG_VMAP_STACK`、`CONFIG_STACKPROTECTOR` 等）下的源码为准**。
- 文中 **行号均按本仓库当前文件** 校对；换分支或版本后请以实际文件为准。
