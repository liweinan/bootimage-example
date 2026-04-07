# x86 内核栈、syscall 入口与 TSS / per-CPU 变量

本文档整理 Linux x86 上**用户态进入内核**时内核栈指针的来源，以及 **`cpu_current_top_of_stack`**、**TSS（及 FRED）**、**`task_top_of_stack`**、**`__switch_to`** 之间的关系与代码位置。基于当前树内源码归纳。

**`task_top_of_stack` / `cpu_current_top_of_stack` 的集中说明**（宏展开、`next_p`、调度链、与 `sp0` 分工、`entry_SYSCALL_64` 节选）见专文 **[LINUX_X86_TASK_TOP_OF_STACK_AND_CPU_CURRENT_TOP.md](LINUX_X86_TASK_TOP_OF_STACK_AND_CPU_CURRENT_TOP.md)**，本文 **§3** 仅留索引，避免与专文重复。

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

## 3. `cpu_current_top_of_stack` / `task_top_of_stack`（索引）

专文 **[LINUX_X86_TASK_TOP_OF_STACK_AND_CPU_CURRENT_TOP.md](LINUX_X86_TASK_TOP_OF_STACK_AND_CPU_CURRENT_TOP.md)**：写入语义、`next_p`、`task_top_of_stack` 宏与 `task->stack`、boot/i386、**`thread_struct.sp0`** 对照、调度链、`entry_SYSCALL_64` 切栈节选。

**`vmlinux.lds.S`** 中 **`const_cpu_current_top_of_stack`** 别名、**`current_top_of_stack()`** 读法，见专文 §3.5 与 **`processor.h`**。

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

- **`cpu_current_top_of_stack`**：在 **`__switch_to`**（64 位）里按 **`task_top_of_stack(next)`** 更新，反映**当前运行线程**的内核栈顶（宏与数据链见 [LINUX_X86_TASK_TOP_OF_STACK_AND_CPU_CURRENT_TOP.md](LINUX_X86_TASK_TOP_OF_STACK_AND_CPU_CURRENT_TOP.md) §2–§3）。
- **原生 x86_64 的 `TSS.sp0`**：多为 **固定的 CPU entry trampoline**，不是每个进程切换都写成该进程栈顶；**Xen PV** 等路径例外。

---

## 5.（原 §5–§7 已合并）`__switch_to` / syscall 快速路径

**`task_top_of_stack` 宏、`__switch_to` 与 `update_task_stack` 同一次切换中的关系**、**syscall 数步摘要**，见 **[LINUX_X86_TASK_TOP_OF_STACK_AND_CPU_CURRENT_TOP.md](LINUX_X86_TASK_TOP_OF_STACK_AND_CPU_CURRENT_TOP.md)** §1–§6 与 §8。

---

## 6. Call chain：`cpu_tss_rw.x86_tss.sp0`（TSS RSP0 槽位）

以下指 Linux 镜像里 **`struct tss_struct` → `x86_tss.sp0`**（汇编里常写作 `cpu_tss_rw + TSS_sp0`）。**CPU 硬件**在 CPL 切换时若使用经典 TSS RSP0，会**自动**从当前任务的 TSS 描述符所指向的内存读该字段；下面只列**内核里显式写/显式读**的软件链。

### 6.1 写入链（软件把新值放进 `x86_tss.sp0`）

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

### 6.2 读取链（软件从 `x86_tss.sp0` 取到寄存器或 C 变量）

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

## 7. Call chain：`syscall` 线与 `cpu_current_top_of_stack`

### 7.1 写入 per-CPU `cpu_current_top_of_stack`（调度侧）

**`schedule()` → `__schedule_loop()` → `__schedule()` → `context_switch()` → `switch_to` → `__switch_to_asm` → `__switch_to`** → **`raw_cpu_write(cpu_current_top_of_stack, task_top_of_stack(next_p))`** 的表格式行号与 **boot/i386** 说明见 **[LINUX_X86_TASK_TOP_OF_STACK_AND_CPU_CURRENT_TOP.md](LINUX_X86_TASK_TOP_OF_STACK_AND_CPU_CURRENT_TOP.md) §6**。

### 7.2 读取链（syscall 相关：进入内核时把该 per-CPU 值装进 RSP）

**`MSR_LSTAR`/`STAR`/`FMASK` 的设定与 `idt_syscall_init()`**：见 **[LINUX_X86_MSR_REFERENCE.md](LINUX_X86_MSR_REFERENCE.md)**。下列为 **Call chain 速查**（非 FRED）。

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

**与返回用户态：** 进内核侧读 **`cpu_current_top_of_stack`**；返回前常读 **`TSS_sp0` 切 trampoline**（见上文 **§6.2**），再 **`SYSRET`/`IRET`**。

---

## 8. 文档说明

- 本文仅作内核阅读索引与概念对齐，**具体行为以当前配置（`CONFIG_XEN_PV`、`CONFIG_X86_FRED`、`CONFIG_VMAP_STACK`、`CONFIG_STACKPROTECTOR` 等）下的源码为准**。
- 文中 **行号均按本仓库当前文件** 校对；换分支或版本后请以实际文件为准。
