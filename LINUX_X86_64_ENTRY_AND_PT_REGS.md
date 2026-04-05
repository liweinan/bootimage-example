# Linux x86-64：`sp0`、`cpu_current_top_of_stack` 与 `pt_regs`（入口与栈）

本文对 `/Users/weli/works/linux` 做静态对照，说明：**特权级切换时栈从哪里来**、**`pt_regs` 何时出现在内核栈上**、**系统调用与 IDT 中断/异常入口的差异**。下文默认 **原生 x86-64**（非 Xen PV 特化；FRED 另有 MSR 路径）。

---

## 阅读导读

面向：**已能区分用户态/内核态、大致知道 TSS/IDT/syscall 名词**，希望把 **Intel 手册中的 SYSCALL 行为** 与 **Linux x86-64 入口代码** 对齐阅读的读者。

**栈顶 / `task_top_of_stack` / `cpu_current_top_of_stack`** 与正文 **§1、§2** 重叠部分，可优先读 **[LINUX_X86_TASK_TOP_OF_STACK_AND_CPU_CURRENT_TOP.md](LINUX_X86_TASK_TOP_OF_STACK_AND_CPU_CURRENT_TOP.md)**，以免重复。

### 阅读目标自查

读完后应能独立回答：

1. **特权级切换时**，内核栈顶信息来自 **TSS.sp0** 还是 **per-CPU 的 `cpu_current_top_of_stack`**，各自在什么路径被使用。
2. **`SYSCALL` 指令**在硬件上保存/改写了哪些状态，与 **`pt_regs`** 里哪些字段对应。
3. **设备中断**与 **CPU 异常**路径上，`pt_regs` 是 **硬件 IRET 帧** 加 **汇编补齐** 如何得到；**`sync_regs`** 在什么叙事里出现。
4. **`entry_SYSCALL_64`** 与 **`asm_common_interrupt` / `asm_exc_*`** 在「谁压栈、谁切栈」上的差异。

若以上任一条仍模糊，按下面顺序重读正文对应节。

### 建议阅读顺序（正文章节）

| 轮次 | 章节 | 侧重点 |
|------|------|--------|
| 第一轮 | §1、§2（或先读 [LINUX_X86_TASK_TOP_OF_STACK_AND_CPU_CURRENT_TOP.md](LINUX_X86_TASK_TOP_OF_STACK_AND_CPU_CURRENT_TOP.md)） | 先建立 **sp0 ≠ 当前线程内核栈顶** 的心智模型；记住 **`cpu_current_top_of_stack` 在 `__switch_to` 更新**（专文有完整宏与调度链）。 |
| 第一轮 | §3 | **`pt_regs` 字段名是 C ABI**（`ax`/`ip`/`flags`），读内核与读 Intel 助记符时不要混用。 |
| 第二轮 | §4、§8.3 | **SYSCALL**：硬件只保证 RCX/R11 等；**完整 `pt_regs` 靠 `entry_SYSCALL_64`**；对照 SDM（见本阅读导读 **「与 Intel SDM 对照」**）。 |
| 第二轮 | §5 | 需要对照 `calling.h` 时读：**通用寄存器压栈顺序与 `struct pt_regs` 布局一致**。 |
| 第三轮 | §6、§8.1–8.2（外部 IRQ 相关行）、§8 末「IRQ 源码路径」小条 | **IDT → `irq_entries_start` → `asm_common_interrupt`**；**`orig_ax` 与向量号** 的约定。 |
| 第三轮 | §7 | **异常与 CR2 / `regs->ip` 分工**（#PF）；**`error_get_trap_addr`** 叙事（#DE）。 |
| 第四轮 | §8 总览表与出口表 | 把 **syscall / int80 / IRQ / 异常** 收口成一张「进/出**内核**」对照；需要时再进 `entry_64.S` 跟 `error_return`。 |
| 查索引 | §10、参考文件索引 | 用 **`rg`/`read_file`** 在本地内核树验证符号；正文里的路径以你检出的 `linux` 为准。 |

### 与 Intel SDM（System Programming Guide）的对照

正文不写满手册细节；下列条目便于你 **打开 Vol 3A** 时知道「该翻哪一节」。

| 主题 | SDM Vol 3A（典型位置） | 与本文的连接 |
|------|-------------------------|--------------|
| SYSCALL/SYSRET 设计意图与模式限制 | §5.8.8 *Fast System Calls in 64-Bit Mode* | 正文 §4、§8.3：**长模式**、**平坦模型**；**兼容/保护模式无 SYSCALL**。 |
| 使能位 | `IA32_EFER.SCE`（§2、Table 2-1） | 内核 boot 阶段会配置 EFER 与 STAR/LSTAR/FMASK（本文默认读者已知「已启用」）。 |
| 目标 RIP / CS / SS / RFLAGS 掩码 | `IA32_LSTAR`、`IA32_STAR`、`IA32_FMASK`，Figure 5-14 | **RCX←次条 RIP、R11←RFLAGS**；**内核入口地址在 LSTAR**（正文 `entry_SYSCALL_64`）。 |
| 栈 | 手册明确 **SYSCALL 不保存 RSP，SYSRET 不恢复 RSP** | 正文 §4：**用户 RSP 进 TSS.sp2 再写入 `pt_regs->sp`**；**切到 `cpu_current_top_of_stack`**。 |
| 虚拟化 | VMX 章节中 *Handling SYSCALL/SYSRET*（目录约 §31.10.4.3） | 仅在写 Hypervisor/嵌套虚拟化时需要；读本文可不读。 |

更细的 **单条指令操作**（异常码、边界条件）以 **SDM Volume 2（指令集卷）** 中 SYSCALL/SYSRET 条目为准。

### 内核树阅读提示

- **默认内核根**：`/Users/weli/works/linux`（若与你环境不一致，只替换路径，**符号名**仍以同名文件为准）。
- **syscall 入口**：`arch/x86/entry/entry_64.S` 中 `entry_SYSCALL_64`、`syscall_return_via_sysret`、`common_interrupt_return` 一带与正文 §4、§8.2 对照。
- **IRQ stub**：`arch/x86/include/asm/idtentry.h` 中 `irq_entries_start` 与正文 §6.2 一致；**不要**假设 IDT 直接指向一个大写的 `common_interrupt` 手写函数——多为 **宏展开**。
- **版本差异**：主线会调整 FRED、PTI、paranoid 等分支；本文已单列 **FRED** 与 **IST/paranoid** 的提醒，你那棵树的 `#ifdef` 以实际代码为准。

### 常见误读（读正文时可对照纠正）

1. **「sp0 = 当前进程内核栈顶」**：正文 §1、§2 说明在常见原生 x86-64 上 **不成立**；**sp0 更像 entry trampoline 锚点**。
2. **「syscall 像中断一样压 IRET 帧」**：正文 §4、§8.3：**硬件不压完整帧**；**`pt_regs` 由入口汇编搭建**。
3. **「设备 IRQ 的向量号在某个专用寄存器」**：正文 §6：**stub `push imm8` 占位，与 `pt_regs.orig_ax` 布局对齐**，C 层再解释为 `u8` 向量号。

读完正文 §1–§4 后，若愿意动手验证，可按 **§10** 在运行中的系统上看 `kallsyms` 与 `/proc/interrupts`；与静态正文互补。

---

## 1. 结论先行：`sp0` 与「当前进程内核栈顶」是两套机制

在常见 64 位配置下：

- `TSS.sp0` 长期指向 **per-CPU 的 entry trampoline / entry stack 锚点**（`cpu_init()` 里 `load_sp0((unsigned long)(cpu_entry_stack(cpu) + 1))`，见 `arch/x86/kernel/cpu/common.c`）。`native_load_sp0()` 写入 `cpu_tss_rw.x86_tss.sp0`（`arch/x86/include/asm/processor.h`）。
- **当前运行 task 的内核栈顶**由 per-CPU 变量 `cpu_current_top_of_stack` 表示，在 `__switch_to()` 里更新为 `task_top_of_stack(next_p)`（`arch/x86/kernel/process_64.c`）。
- `update_task_stack()`（`arch/x86/include/asm/switch_to.h`）的注释写明：`sp0 always points to the entry trampoline stack, which is constant`。x86-64 原生路径下 **`load_sp0(task_top_of_stack(task))` 仅在 Xen PV 等分支出现**；不要把它理解成「每次调度都把进程栈顶写进 sp0」的通用模型。

---

## 2. 用户态进程的内核栈地址：谁来记？

**`cpu_current_top_of_stack` / `task_top_of_stack`、调度切换时 `raw_cpu_write`、与 `update_task_stack` 同一次 `__switch_to` 中的顺序**，见专文 **[LINUX_X86_TASK_TOP_OF_STACK_AND_CPU_CURRENT_TOP.md](LINUX_X86_TASK_TOP_OF_STACK_AND_CPU_CURRENT_TOP.md)**。

此处只保留与 **`pt_regs` 落点**相关的结论：**异常/中断路径里若要把帧挪到「线程内核栈」上的标准 `pt_regs` 槽位，靠的是已写好的 per-CPU 栈顶**（`cpu_current_top_of_stack`），而不是在用户态现场里临时推算。

`sync_regs()`（`arch/x86/kernel/traps.c`）把入口栈上的 `pt_regs` 拷到 `(struct pt_regs *)current_top_of_stack() - 1`（与 `error_entry`/`idtentry_body` 配合，真实栈切换在 `entry_64.S`）。

---

## 3. `struct pt_regs` 与真实字段名（避免与 Intel 助记符混淆）

64 位定义在 `arch/x86/include/asm/ptrace.h`，C 侧使用 **`ax/di/si/...`、`orig_ax`、`ip`、`flags`、`sp`、`cs`、`ss`** 等，而不是 `rax/rdi`、`orig_rax`、`rip`、`rflags`。

要点摘录：

- `orig_ax`：syscall 号 / 异常的 error code（若硬件已压栈）/ 设备中断向量号（由入口压入的值解释）。
- IRET 帧从 `ip` 起：`ip`、`cs`、`flags`、`sp`、`ss`。

---

## 4. 系统调用：`entry_SYSCALL_64` 如何构造 `pt_regs`

`SYSCALL` **不会**像中断那样把完整帧压栈；硬件主要把 **RIP→RCX、RFLAGS→R11** 并跳到 `MSR_LSTAR`。内核在 `entry_SYSCALL_64` 里 **手工** 建 `pt_regs`：

```87:121:arch/x86/entry/entry_64.S
SYM_CODE_START(entry_SYSCALL_64)
	...
	swapgs
	movq	%rsp, PER_CPU_VAR(cpu_tss_rw + TSS_sp2)
	SWITCH_TO_KERNEL_CR3 scratch_reg=%rsp
	movq	PER_CPU_VAR(cpu_current_top_of_stack), %rsp
	...
	pushq	$__USER_DS				/* pt_regs->ss */
	pushq	PER_CPU_VAR(cpu_tss_rw + TSS_sp2)	/* pt_regs->sp */
	pushq	%r11					/* pt_regs->flags */
	pushq	$__USER_CS				/* pt_regs->cs */
	pushq	%rcx					/* pt_regs->ip */
	pushq	%rax					/* pt_regs->orig_ax */

	PUSH_AND_CLEAR_REGS rax=$-ENOSYS
	...
	call	do_syscall_64
```

- 用户 **RSP** 先存 **TSS.sp2**，再写入 `pt_regs->sp`。
- 切到 **`cpu_current_top_of_stack`** 后再压栈，故 **syscall 入口栈不依赖硬件读 `sp0`**。

**SYSRET 快路径**末尾会切到 `TSS_sp0`（trampoline）、`popq` 恢复用户 RSP/RDI，再 `sysretq`（同文件 `syscall_return_via_sysret` 一段）。慢路径走 `swapgs_restore_regs_and_return_to_usermode` + `iretq`（仍在 `entry_64.S` 的 `common_interrupt_return` 一带）。

---

## 5. `PUSH_AND_CLEAR_REGS`：通用寄存器压栈顺序

定义在 `arch/x86/entry/calling.h`。`PUSH_REGS` 压栈顺序（与 `struct pt_regs` 中 **自栈顶向高地址** 的生长方向一致）为：**di, si, dx, cx, ax, r8, r9, r10, r11, rbx, rbp, r12, r13, r14, r15**；随后 `CLEAR_REGS` 清零敏感寄存器。**不是**随意 `push r15…rax` 那种与头文件不一致的顺序。

---

## 6. 设备中断：IDT、`irq_entries_start`、C 层 `common_interrupt`

### 6.1 IDT 如何指向各 stub

- 异常/系统向量等：`def_idts[]`、`apic_idts[]` 等表，`idt_setup_from_table()` 写入 `idt_table`（`arch/x86/kernel/idt.c`）。
- **外部设备向量** `FIRST_EXTERNAL_VECTOR .. FIRST_SYSTEM_VECTOR-1`：`idt_setup_apic_and_irq_gates()` 中按位分配，入口地址为  
  `irq_entries_start + IDT_ALIGN * (vector - FIRST_EXTERNAL_VECTOR)`（同文件）。

### 6.2 每个向量 stub 如何压「向量号」

`irq_entries_start` 由 `asm/idtentry.h` 在 inclusion 时展开（被 `entry_64.S` `#include <asm/idtentry.h>`），典型形态为 **单字节 `push imm8`** + `jmp asm_common_interrupt`：

```551:562:arch/x86/include/asm/idtentry.h
SYM_CODE_START(irq_entries_start)
    vector=FIRST_EXTERNAL_VECTOR
    .rept NR_EXTERNAL_VECTORS
	...
	.byte	0x6a, vector
	jmp	asm_common_interrupt
	...
	vector = vector+1
    .endr
SYM_CODE_END(irq_entries_start)
```

该 push 占 **`pt_regs.orig_ax` 位置**（与带 error code 的异常布局对齐）；C 侧 `DEFINE_IDTENTRY_IRQ` 将 `error_code` 截断为 `u8` 得到向量号。

### 6.3 统一汇编入口名与 C 处理函数

- 汇编：由 `DECLARE_IDTENTRY_IRQ(common_interrupt)` 生成 **`asm_common_interrupt`**，经 `idtentry_body` 调用 `error_entry` 等后进入 **`common_interrupt(struct pt_regs *regs, unsigned long error_code)`**（`arch/x86/kernel/irq.c`：`DEFINE_IDTENTRY_IRQ(common_interrupt)`）。

---

## 7. 异常：缺页与除零（与 `pt_regs`）

### 7.1 #PF（缺页）

- IDT：`def_idts` / 早期 `early_pf_idts` 指向 **`asm_exc_page_fault`**（`arch/x86/kernel/idt.c`）。
- C：`DEFINE_IDTENTRY_RAW_ERRORCODE(exc_page_fault)` 在 **`arch/x86/mm/fault.c`**：`read_cr2()`（或 FRED 下 `fred_event_data(regs)`）得到 fault 地址，`handle_page_fault(regs, error_code, address)`，用户态不可恢复路径上会 `force_sig_fault(SIGSEGV, ...)` 等。  
**故障线性地址** 主要来自 **CR2**，**`regs->ip` 是故障指令 IP**，用于诊断/日志/VDSO 修复等，不是 CR2 的替代品。

### 7.2 #DE（除零）

- `DEFINE_IDTENTRY(exc_divide_error)` 在 **`arch/x86/kernel/traps.c`**：`do_error_trap(..., SIGFPE, FPE_INTDIV, error_get_trap_addr(regs))`。  
`error_get_trap_addr()` 封装 `uprobe_get_trap_addr(regs)`，注释说明 **`si_addr` 通常对应 `regs->ip`**（uprobe XOL 时会映射回原指令地址）。

异常 stub 由 `idtentry`/`idtentry_body` 宏生成，**不是**手写的 `SYM_CODE_START(asm_exc_page_fault); call exc_page_fault` 那种简化伪代码。

---

## 8. syscall / IRQ / 异常 / `int 0x80`：入口与 `pt_regs` 总览

以下按 **x86-64 Linux** 主线（`/Users/weli/works/linux`）归纳；**纯 32 位内核** 的 `int 0x80` 单独一行。进到通用 C 路径时都会以 **`struct pt_regs *`** 表示现场；差别在 **走 MSR（`syscall`）还是走 IDT**，以及 **`pt_regs` 是 syscall 入口纯手工搭**，还是 **INT/IRQ/异常在硬件 IRET 帧上由 `error_entry` 等补齐（用户态常经 `sync_regs`）**。

### 8.1 总览表

| 类型 | 怎么进内核 | 内核汇编入口（符号） | 主要 C 路径 | 是否形成可用的 `struct pt_regs` |
|------|------------|----------------------|-------------|--------------------------------|
| **64 位 `syscall`** | 用户执行 `syscall`，`MSR_IA32_LSTAR` 指向入口 | `entry_SYSCALL_64`（`arch/x86/entry/entry_64.S`） | `do_syscall_64`（`arch/x86/entry/syscall_64.c`） | **是**：在线程内核栈上按布局 `push` + `PUSH_AND_CLEAR_REGS`，无 CPU 自动压完整 IRET 帧 |
| **`int 0x80`（64 位内核 + `CONFIG_IA32_EMULATION`）** | 向量 `0x80`，走 IDT | IDT 登记 **`asm_int80_emulation`**（由 `DECLARE_IDTENTRY_RAW(IA32_SYSCALL_VECTOR, int80_emulation)` 展开，`asm/idtentry.h`）；另有跳板 **`int80_emulation`** → `jmp do_int80_emulation`（`entry_64_compat.S`） | **`do_int80_emulation`**（`arch/x86/entry/syscall_32.c`）；启用 FRED 时另有 `fred_int80_emulation` / `DEFINE_FREDENTRY_RAW(int80_emulation)` 分支 | **是**：走 **`idtentry` → `error_entry` → `PUSH_AND_CLEAR_REGS` 等**；用户态通常经 **`sync_regs`** 落到线程栈上标准 `pt_regs` |
| **`int 0x80`（仅 32 位内核）** | 向量 `0x80` | **`entry_INT80_32`**（`arch/x86/entry/entry_32.S`） | **`do_int80_syscall_32`**（`syscall_32.c`） | **是**：由 32 位 entry 建栈帧后向 C 传入 `pt_regs` |
| **外部 IRQ** | PIC/MSI/APIC 等，向量 ≥ `FIRST_EXTERNAL_VECTOR` | **`irq_entries_start`**（`arch/x86/include/asm/idtentry.h`，由 `arch/x86/entry/entry_64.S` `#include` 展开）→ **`asm_common_interrupt`**（同头文件 `DECLARE_IDTENTRY_IRQ(common_interrupt)` 经 `idtentry` 宏生成，汇编进 `entry_64.S`；见下节） | **`common_interrupt`** → **`call_irq_handler`**（`arch/x86/kernel/irq.c`） | **是** |
| **CPU 异常（#PF/#DE/…）** | CPU 查 IDT | **`asm_exc_*`**（`idtentry` 等在 `entry_64.S` + `idtentry.h` 生成；IDT 在 `idt.c`） | 如 **`exc_page_fault`** → `handle_page_fault`（`fault.c`），**`exc_divide_error`** → `do_error_trap`（`traps.c`）等 | **是**：硬件先压 IRET 帧（± error code），再 **`error_entry` + `PUSH_AND_CLEAR_REGS`**；用户态常见 **`sync_regs`**（IST/paranoid 等路径例外） |

### 8.2 返回用户态（出口）总览表

以下与 **§8.1** 各行对应；**C 侧**在返回汇编前统一做完 signal/调度/TIF 等（`syscall_exit_to_user_mode()` 见 `include/linux/entry-common.h`；**IDT 路径**上返回到用户时多为 `irqentry_exit()` → `irqentry_exit_to_user_mode()`，实现见 `kernel/entry/common.c`）。**汇编**侧：系统调用可走 **`sysretq`** 快路径或汇入与中断共用的 **`swapgs_restore_regs_and_return_to_usermode`**；凡经 `idtentry_body` 的 IDT 处理函数 **`ret` 后**都会执行 **`jmp error_return`**（`arch/x86/entry/entry_64.S` 中 `.macro idtentry_body` 展开）。

| 类型 | 主要 C 出口路径（函数） | 汇编符号 / 指令 | 文件 |
|------|-------------------------|-----------------|------|
| **64 位 `syscall`** | `do_syscall_64()`（`arch/x86/entry/syscall_64.c`）内调用 **`syscall_exit_to_user_mode()`**；通用出口逻辑在 **`exit_to_user_mode()`** / **`exit_to_user_mode_prepare()`**（`kernel/entry/common.c`，经 `entry-common.h` 内联） | 若 `do_syscall_64` 返回真：进入 **`syscall_return_via_sysret`** → **`POP_REGS`**（`arch/x86/entry/calling.h`）→ trampoline 栈 → **`swapgs`** → **`sysretq`**；若返回假：**`swapgs_restore_regs_and_return_to_usermode`**（`SYM_CODE_START_LOCAL(common_interrupt_return)` 内全局标签）→ **`POP_REGS`** → **`iretq`**（经 **`.Lnative_iret`** / **`native_irq_return_iret`**） | `syscall_64.c`，`entry_64.S`，`calling.h`，`entry-common.h`，`kernel/entry/common.c` |
| **`int 0x80`（64 位内核 + `CONFIG_IA32_EMULATION`）** | **`do_int80_emulation()`**（`arch/x86/entry/syscall_32.c`）末尾 **`syscall_exit_to_user_mode()`** | **`asm_int80_emulation`**（`idtentry` 在 `entry_64.S` 展开）：**`idtentry_body`** 内 **`call int80_emulation`**（跳板在 **`arch/x86/entry/entry_64_compat.S`**：`jmp do_int80_emulation`）→ C **`ret` 后** 落到 **`jmp error_return`** → **`swapgs_restore_regs_and_return_to_usermode`** → **`iretq`** | `syscall_32.c`，`entry_64_compat.S`，`entry_64.S`，`idtentry.h` |
| **`int 0x80`（仅 32 位内核）** | **`do_int80_syscall_32()`**（`arch/x86/entry/syscall_32.c`）末尾 **`syscall_exit_to_user_mode()`** | **`entry_INT80_32`** 中 **`restore_all_switch_stack`** → **`.Lirq_return`** → **`iret`** | `syscall_32.c`，`arch/x86/entry/entry_32.S` |
| **外部 IRQ** | **`common_interrupt()`**（`arch/x86/kernel/irq.c`，`DEFINE_IDTENTRY_IRQ` 展开）内 **`irqentry_exit()`** → 若 `user_mode(regs)` 则 **`irqentry_exit_to_user_mode()`**（`kernel/entry/common.c`） | **`idtentry_body`**：`call common_interrupt` → **`jmp error_return`** → **`swapgs_restore_regs_and_return_to_usermode`** → **`iretq`** | `irq.c`，`idtentry.h`（宏），`kernel/entry/common.c`，`entry_64.S` |
| **CPU 异常（#PF/#DE/…）** | 视宏而定：`DEFINE_IDTENTRY` 包装体内 **`irqentry_exit()`**；**`DEFINE_IDTENTRY_RAW_ERRORCODE(exc_page_fault)`** 在 **`exc_page_fault()`**（`arch/x86/mm/fault.c`）内显式 **`irqentry_enter()` / `irqentry_exit()`** | 典型：**`jmp error_return`** → 返用户：**`swapgs_restore_regs_and_return_to_usermode`** → **`iretq`**；返内核：**`restore_regs_and_return_to_kernel`** → **`iretq`**（**`error_return`** 依 **`CS(%rsp)`** 选择） | `fault.c`，`traps.c`，`idtentry.h`，`kernel/entry/common.c`，`entry_64.S` |
| **补充：IST/paranoid、PTI** | 与普通 IDT 相同由 C 侧 **`irqentry_exit()`** 等收尾 | 从异常栈返内核：**`paranoid_exit`**（`entry_64.S`）→ **`restore_regs_and_return_to_kernel`**；开 PTI 返用户可先 **`jmp .Lpti_restore_regs_and_return_to_usermode`** 再汇入 **`swapgs`** + **`iretq`** | `entry_64.S` |

**`error_return`**（`entry_64.S`）：若 **`CS`** 表明返内核，跳 **`restore_regs_and_return_to_kernel`**；否则 **`jmp swapgs_restore_regs_and_return_to_usermode`**。

#### 外部 IRQ：源码路径（与上表「外部 IRQ」行对应）

1. **IDT 填门（每个外部向量指向不同短桩）**  
   `idt_setup_apic_and_irq_gates()`（`arch/x86/kernel/idt.c`）对满足条件的向量 `i` 调用 `set_intr_gate(i, entry)`，其中  
   `entry = irq_entries_start + IDT_ALIGN * (i - FIRST_EXTERNAL_VECTOR)`（同文件约 291–294 行）。即 **每个设备向量各自落在 `irq_entries_start` 数组里的一段对齐 stub**，再统一跳到 **`asm_common_interrupt`**。

2. **每个向量 stub（压向量号 + 跳转）**  
   `SYM_CODE_START(irq_entries_start)`（`arch/x86/include/asm/idtentry.h`，由 `entry_64.S` `#include <asm/idtentry.h>` 展开）对每个向量生成 **单字节 `push imm8`**（汇编写作 `.byte 0x6a, vector`，避免 GCC 把 `pushq $vector` 扩成 5 字节）和 **`jmp asm_common_interrupt`**；`.rept NR_EXTERNAL_VECTORS` 覆盖外部向量范围。注释说明：该 push **符号扩展**，C 入口用 **`(u32)(u8)error_code`** 还原向量号（见下第 4 步 `DEFINE_IDTENTRY_IRQ`）。

3. **统一汇编入口 `asm_common_interrupt`（由宏生成，非手写单文件）**  
   `DECLARE_IDTENTRY_IRQ(X86_TRAP_OTHER, common_interrupt)`（`idtentry.h` 约 692–693 行）在汇编侧经 `idtentry_irq` → `idtentry` 生成 **`SYM_CODE_START(asm_common_interrupt)`**。占位向量 **`X86_TRAP_OTHER (0xFFFF)`** 使宏不套用 #BP 等特殊分支，得到「通用」`idtentry` 体；**`has_error_code=1`** 与 stub 压入的「伪 error_code」在栈布局上与 `pt_regs.orig_ax` 槽对齐。

4. **`idtentry_body`（`arch/x86/entry/entry_64.S`）**  
   调用 **`error_entry`**（原生路径；Xen PV 走 `xen_error_entry` 替代）→ 此时 **`%rsp` 指向完整 `pt_regs`** → `movq %rsp, %rdi`；若 `has_error_code==1`，从 **`ORIG_RAX(%rsp)`** 取第二参数（此处即向量号）到 **`%rsi`**，并把 **`orig_ax` 置 `-1`**（表示非 syscall 重启语义）→ **`call common_interrupt`** → **`jmp error_return`**（约 289–316 行宏展开）。

5. **C 层封装与设备处理**  
   `DEFINE_IDTENTRY_IRQ(common_interrupt)`（`arch/x86/include/asm/idtentry.h` 约 206–220 行）展开为：先 **`irqentry_enter(regs)`**，再 **`run_irq_on_irqstack_cond(__common_interrupt, regs, vector)`**，其中 **`vector = (u32)(u8)error_code`**。  
   实际处理体在 **`arch/x86/kernel/irq.c`**：`DEFINE_IDTENTRY_IRQ(common_interrupt)` 的内联函数体（约 285–296 行）里 **`set_irq_regs(regs)`** → **`call_irq_handler(vector, regs)`**（同文件约 259–278 行：按 **`vector_irq[vector]`** 取 **`irq_desc`**，再 **`handle_irq` → `generic_handle_irq_desc`**）→ 必要时 **`apic_eoi()`** → **`set_irq_regs` 恢复**。

**小结**：硬件先压 **IRET 帧**；stub 再压 **向量号**；**`error_entry`** 补全 **`PUSH_AND_CLEAR_REGS`** 等并得到 **`pt_regs *`**；**`common_interrupt`** 只在 **已构造好的 `regs`** 上做 **RCU/IRQ 栈/具体 IRQ 分发**。

### 8.3 补充：SYSCALL / 设备 IRQ / 典型异常（维度对比）

| 项目 | SYSCALL | 设备 IRQ（`irq_entries_start`） | 典型异常（如 #PF / #DE） |
|------|---------|--------------------------------|--------------------------|
| 开门方式 | `MSR_LSTAR` → `entry_SYSCALL_64` | IDT → `asm_common_interrupt` → … | IDT → `asm_exc_*` → … |
| 硬件压栈 | 无完整 IRET 帧；RIP/RFLAGS 在 RCX/R11 | 用户态：SS/RSP/RFLAGS/CS/RIP；内核态：无 SS/RSP | 视向量与 CPL；#PF 有 error code |
| `pt_regs` | 入口汇编全手工 + `PUSH_AND_CLEAR_REGS` | `error_entry` + `PUSH_AND_CLEAR_REGS` 等 + 可能 `sync_regs` | 同左（IST/paranoid 路径例外） |
| 返回 | 常为 `sysretq` 或 IRET 慢路径 | 通常为 `iretq` 系列 | `iretq` / paranoid 路径 |

---

## 9. 用户态现场如何进内核栈

用户态 **不写入内核栈**。用户只把寄存器置好；**CPU 与内核入口代码** 在内核栈上生成与 `struct pt_regs` 布局一致的内存，`struct pt_regs *regs` 只是指向这块内核栈内存。

---

## 10. 调试线索（可选）

```bash
grep -E 'asm_exc_|irq_entries' /proc/kallsyms | head
cat /proc/interrupts
```

---

## 参考文件索引（内核树）

| 主题 | 路径 |
|------|------|
| syscall 入口 | `arch/x86/entry/entry_64.S` |
| `int 0x80`（ia32 仿真） | `arch/x86/entry/entry_64_compat.S`，`arch/x86/entry/syscall_32.c` |
| 寄存器压栈宏 | `arch/x86/entry/calling.h` |
| `pt_regs` | `arch/x86/include/asm/ptrace.h` |
| syscall 分发 | `arch/x86/entry/syscall_64.c` |
| `sync_regs`、#DE | `arch/x86/kernel/traps.c` |
| #PF | `arch/x86/mm/fault.c` |
| IDT 安装 | `arch/x86/kernel/idt.c` |
| IRQ stub 生成、`irq_entries_start` | `arch/x86/include/asm/idtentry.h` |
| `common_interrupt` C | `arch/x86/kernel/irq.c` |
| `syscall_exit_to_user_mode` / `irqentry_exit`（通用出口） | `include/linux/entry-common.h`，`include/linux/irq-entry-common.h`，`kernel/entry/common.c` |
| 上下文切换写栈顶、`task_top_of_stack` | [LINUX_X86_TASK_TOP_OF_STACK_AND_CPU_CURRENT_TOP.md](LINUX_X86_TASK_TOP_OF_STACK_AND_CPU_CURRENT_TOP.md)，`arch/x86/kernel/process_64.c` |
| `sp0`、TSS、load_sp0 | `arch/x86/kernel/cpu/common.c`，`arch/x86/include/asm/processor.h` |
| `update_task_stack` | `arch/x86/include/asm/switch_to.h` |

---

*本文档由仓库内 `draft.txt` 整理并与上述内核路径核对；若你本地内核版本不同，请以同名符号为准用 `rg`/`read_file` 再确认一次。*
