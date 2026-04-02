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
| MSR `LSTAR` 指向 syscall 入口 | `arch/x86/kernel/cpu/common.c`：`wrmsrq(MSR_LSTAR, (unsigned long)entry_SYSCALL_64)` |
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

```c
#define task_top_of_stack(task) ((unsigned long)(task_pt_regs(task) + 1))

#define task_pt_regs(task) ({						\
	unsigned long __ptr = (unsigned long)task_stack_page(task);	\
	__ptr += THREAD_SIZE - TOP_OF_KERNEL_STACK_PADDING;		\
	((struct pt_regs *)__ptr) - 1;					\
})
```

位置：**`arch/x86/include/asm/processor.h`**。

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

```
load_sp0(sp0)                         [paravirt 时经 PVOP → xen_load_sp0]
    → native_load_sp0(sp0)          arch/x86/include/asm/processor.h
        → this_cpu_write(cpu_tss_rw.x86_tss.sp0, sp0)
```

**谁调用 `load_sp0`（典型）：**

1. **每 CPU 初始化（BSP/AP）**  
   `cpu_init()`（`arch/x86/kernel/cpu/common.c`）  
   → `load_sp0((unsigned long)(cpu_entry_stack(cpu) + 1))`  
   注释含义：**sp0 恒为当前 CPU 的 entry trampoline 栈顶**，与当前 `task` 无关（原生 x86_64 常见形态）。

2. **上下文切换里（条件极窄）**  
   `__switch_to()`（`arch/x86/kernel/process_64.c`）  
   → `update_task_stack(next_p)`（`arch/x86/include/asm/switch_to.h`）  
   → 当 **`X86_FEATURE_XENPV` 且未启用 FRED** 时：`load_sp0(task_top_of_stack(task))`  
   即 **Xen PV** 下会把 **sp0 设成即将运行线程的内核栈顶**。

3. **Xen paravirt 后端**  
   `load_sp0` 可落到 **`xen_load_sp0()`**（`arch/x86/xen/enlighten_pv.c`）  
   → 同样写 `cpu_tss_rw.x86_tss.sp0`。

**静态初值（随后仍会被 `cpu_init` 等覆盖）：**  
`DEFINE_PER_CPU_PAGE_ALIGNED(cpu_tss_rw)`（`arch/x86/kernel/process.c`）里对 `.x86_tss.sp0` 的毒化初值。

### 8.2 读取链（软件从 `x86_tss.sp0` 取到寄存器或 C 变量）

1. **syscall 返回：切到 trampoline 栈（x86_64）**  
   `entry_SYSCALL_64`（`arch/x86/entry/entry_64.S`）  
   - `syscall_return_via_sysret`：`movq PER_CPU_VAR(cpu_tss_rw + TSS_sp0), %rsp`  
   - PTI 慢路径 `.Lpti_restore_regs_and_return_to_usermode`：同上指令。

2. **32 位入口汇编**  
   `arch/x86/entry/entry_32.S` 中多处 `PER_CPU_VAR(cpu_tss_rw + TSS_sp0)` 装入寄存器。

3. **C 里按址当栈用（示例）**  
   `arch/x86/kernel/traps.c`：`this_cpu_read(cpu_tss_rw.x86_tss.sp0)` 等，用于在特定异常路径下构造/借用栈帧。

---

## 9. Call chain：`syscall` 线与 `cpu_current_top_of_stack`

### 9.1 写入链（谁在更新 per-CPU 的 `cpu_current_top_of_stack`）

```
__schedule() …
  → context_switch()                    kernel/sched/core.c
      → switch_to(prev, next, prev)      arch/x86/include/asm/switch_to.h
          → __switch_to_asm(prev, next)  arch/x86/entry/entry_64.S
              → __switch_to()            arch/x86/kernel/process_64.c
                  → raw_cpu_write(cpu_current_top_of_stack,
                                  task_top_of_stack(next_p))
```

**其它写入：**

- **per-CPU 初值**：`DEFINE_PER_CPU_CACHE_HOT(..., cpu_current_top_of_stack) = TOP_OF_INIT_STACK`（`arch/x86/kernel/cpu/common.c`）。
- **仅 `CONFIG_X86_32`**：`common_cpu_up()`（`arch/x86/kernel/smpboot.c`）里  
  `per_cpu(cpu_current_top_of_stack, cpu) = task_top_of_stack(idle)`（64 位 AP 路径无此赋值，依赖后续第一次 `__switch_to` 等到 idle/任务时写入）。

**32 位 `__switch_to`：** `arch/x86/kernel/process_32.c` 内 `this_cpu_write(cpu_current_top_of_stack, task_stack_page(...) + THREAD_SIZE)`，调用关系同样是调度 → `context_switch` → `switch_to` → `__switch_to_asm` → `__switch_to`。

### 9.2 读取链（syscall 相关：进入内核时把该 per-CPU 值装进 RSP）

**主路径（64 位用户态 syscall）：**

```
用户态 syscall 指令
  → CPU 根据 STAR/LSTAR 等进入内核 RIP
      → entry_SYSCALL_64                 arch/x86/entry/entry_64.S
          → movq PER_CPU_VAR(cpu_current_top_of_stack), %rsp
          → … 随后在栈上构建 pt_regs，进入 C：`do_syscall_64` 等
```

**IA-32 兼容 syscall（若配置启用）：**  
`entry_64_compat.S` 中同样 `movq PER_CPU_VAR(cpu_current_top_of_stack), %rsp`（与 `entry_SYSCALL_64` 平行的一条 compat 入口线）。

**32 位内核：** `entry_32.S` 中 `PER_CPU_VAR(cpu_current_top_of_stack)` → `%esp` / `%esi`（依具体标签分支而定）。

**与「syscall 返回」的衔接：** 从用户线程栈退回时，常见会先 **`movq … TSS_sp0, %rsp`** 切到 **trampoline**（见第 8.2 节），再通过 `SYSRET`/`IRET` 回用户态；**读 `cpu_current_top_of_stack` 发生在「进内核」一侧**，**读 `TSS_sp0` 常发生在「准备回用户态」一侧**（x86_64 原生）。

**C 代码侧读（非 entry 汇编主路径，但同属该变量语义）：**  
`current_top_of_stack()`（`arch/x86/include/asm/processor.h`）→ `this_cpu_read(_stable/const)(cpu_current_top_of_stack)`，用于判断是否在线程栈上等。

---

## 10. 文档说明

- 本文仅作内核阅读索引与概念对齐，**具体行为以当前配置（`CONFIG_XEN_PV`、`CONFIG_X86_FRED`、`CONFIG_VMAP_STACK` 等）下的源码为准**。
- 若升级内核版本，请以 `grep` / 阅读上述路径为准核对行号与条件编译分支。
