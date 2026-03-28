# Linux x86-64：`sp0`、`cpu_current_top_of_stack` 与 `pt_regs`（入口与栈）

本文对 `/Users/weli/works/linux` 做静态对照，说明：**特权级切换时栈从哪里来**、**`pt_regs` 何时出现在内核栈上**、**系统调用与 IDT 中断/异常入口的差异**。下文默认 **原生 x86-64**（非 Xen PV 特化；FRED 另有 MSR 路径）。

---

## 1. 结论先行：`sp0` 与「当前进程内核栈顶」是两套机制

在常见 64 位配置下：

- `TSS.sp0` 长期指向 **per-CPU 的 entry trampoline / entry stack 锚点**（`cpu_init()` 里 `load_sp0((unsigned long)(cpu_entry_stack(cpu) + 1))`，见 `arch/x86/kernel/cpu/common.c`）。`native_load_sp0()` 写入 `cpu_tss_rw.x86_tss.sp0`（`arch/x86/include/asm/processor.h`）。
- **当前运行 task 的内核栈顶**由 per-CPU 变量 `cpu_current_top_of_stack` 表示，在 `__switch_to()` 里更新为 `task_top_of_stack(next_p)`（`arch/x86/kernel/process_64.c`）。
- `update_task_stack()`（`arch/x86/include/asm/switch_to.h`）的注释写明：`sp0 always points to the entry trampoline stack, which is constant`。x86-64 原生路径下 **`load_sp0(task_top_of_stack(task))` 仅在 Xen PV 等分支出现**；不要把它理解成「每次调度都把进程栈顶写进 sp0」的通用模型。

---

## 2. 用户态进程的内核栈地址：谁来记？

调度切换到 `next_p` 时：

```671:675:arch/x86/kernel/process_64.c
	raw_cpu_write(current_task, next_p);
	raw_cpu_write(cpu_current_top_of_stack, task_top_of_stack(next_p));

	/* Reload sp0. */
	update_task_stack(next_p);
```

`task_top_of_stack()` 由 `task_pt_regs(task) + 1` 计算，而 `task_pt_regs()` 基于 `task->stack` 与 `THREAD_SIZE`（`arch/x86/include/asm/processor.h`、`include/linux/sched/task_stack.h`）。  
因此：**异常/中断路径里若要把帧挪到「线程内核栈」上的标准 `pt_regs` 槽位，靠的是这个已写好的 per-CPU 栈顶**，而不是在用户态现场里临时推算。

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

### 8.2 补充：SYSCALL / 设备 IRQ / 典型异常（维度对比）

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
| 上下文切换写栈顶 | `arch/x86/kernel/process_64.c` |
| `sp0`、TSS、load_sp0 | `arch/x86/kernel/cpu/common.c`，`arch/x86/include/asm/processor.h` |
| `update_task_stack` | `arch/x86/include/asm/switch_to.h` |

---

*本文档由仓库内 `draft.txt` 整理并与上述内核路径核对；若你本地内核版本不同，请以同名符号为准用 `rg`/`read_file` 再确认一次。*
