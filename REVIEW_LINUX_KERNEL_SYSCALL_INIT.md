# Linux 内核系统调用初始化文档校对报告

> **校对时间**：2026-02-12
> **校对文档**：`LINUX_KERNEL_SYSCALL_INIT.md`
> **校对方式**：对照 Linux 源代码（/Users/weli/works/linux）
> **校对结论**：✅ **文档准确，发现少量需要说明的细节**

---

## 一、总体评价

该文档对 Linux 系统调用初始化机制的描述**整体准确**，对照源代码验证后确认：

✅ **正确的内容**：
- trap_init() → cpu_init() → syscall_init() 的调用流程准确
- MSR 寄存器配置（MSR_LSTAR、MSR_CSTAR、MSR_STAR、MSR_SYSCALL_MASK）准确
- INT 0x80 vs SYSCALL/SYSENTER 的对比准确
- entry_SYSCALL_64 入口点和实现准确
- 系统调用表的描述准确

⚠️ **需要补充说明的细节**：
1. INT 0x80 的设置时机描述需要微调
2. 64位系统上 INT 0x80 的入口函数名称
3. 32位兼容系统调用表的调用函数名称

---

## 二、逐项验证结果

### 2.1 MSR 寄存器地址验证 ✅

**文档描述**：MSR_LSTAR、MSR_CSTAR、MSR_STAR、MSR_SYSCALL_MASK 的配置

**源代码验证**（`arch/x86/include/asm/msr-index.h:10-14`）：
```c
#define MSR_STAR		0xc0000081 /* legacy mode SYSCALL target */
#define MSR_LSTAR		0xc0000082 /* long mode SYSCALL target */
#define MSR_CSTAR		0xc0000083 /* compat mode SYSCALL target */
#define MSR_SYSCALL_MASK	0xc0000084 /* EFLAGS mask for syscall */
```

**校对结论**：✅ **寄存器地址完全正确**

**补充说明 - SYSENTER MSR 寄存器**（`arch/x86/include/asm/msr-index.h:243-246`）：
```c
#define MSR_IA32_SYSENTER_CS	0x00000174
#define MSR_IA32_SYSENTER_ESP	0x00000175
#define MSR_IA32_SYSENTER_EIP	0x00000176
```

---

### 2.2 syscall_init() 实现验证 ✅

**文档描述**（第 39-62 行）：
```c
void syscall_init(void)
{
    wrmsr(MSR_STAR, 0, (__USER32_CS << 16) | __KERNEL_CS);
    if (!cpu_feature_enabled(X86_FEATURE_FRED))
        idt_syscall_init();
}
```

**源代码验证**（`arch/x86/kernel/cpu/common.c:2234-2248`）：
```c
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
}
```

**校对结论**：✅ **完全匹配，包括 FRED 特性检查**

---

### 2.3 idt_syscall_init() 实现验证 ✅

**文档描述**（第 48-62 行）：
```c
static inline void idt_syscall_init(void)
{
    wrmsrq(MSR_LSTAR, (unsigned long)entry_SYSCALL_64);  // 64 位 syscall 入口
    if (ia32_enabled()) {
        wrmsrq_cstar((unsigned long)entry_SYSCALL_compat);
        wrmsrq_safe(MSR_IA32_SYSENTER_CS, (u64)__KERNEL_CS);
        wrmsrq_safe(MSR_IA32_SYSENTER_ESP, ...);
        wrmsrq_safe(MSR_IA32_SYSENTER_EIP, (u64)entry_SYSENTER_compat);
    }
    wrmsrq(MSR_SYSCALL_MASK, X86_EFLAGS_CF|...|X86_EFLAGS_ID);
}
```

**源代码验证**（`arch/x86/kernel/cpu/common.c:2198-2230`）：
```c
static inline void idt_syscall_init(void)
{
	wrmsrq(MSR_LSTAR, (unsigned long)entry_SYSCALL_64);

	if (ia32_enabled()) {
		wrmsrq_cstar((unsigned long)entry_SYSCALL_compat);
		/*
		 * This only works on Intel CPUs.
		 * On AMD CPUs these MSRs are 32-bit, CPU truncates MSR_IA32_SYSENTER_EIP.
		 * This does not cause SYSENTER to jump to the wrong location, because
		 * AMD doesn't allow SYSENTER in long mode (either 32- or 64-bit).
		 */
		wrmsrq_safe(MSR_IA32_SYSENTER_CS, (u64)__KERNEL_CS);
		wrmsrq_safe(MSR_IA32_SYSENTER_ESP,
			    (unsigned long)(cpu_entry_stack(smp_processor_id()) + 1));
		wrmsrq_safe(MSR_IA32_SYSENTER_EIP, (u64)entry_SYSENTER_compat);
	}

	wrmsrq(MSR_SYSCALL_MASK,
	       X86_EFLAGS_CF|X86_EFLAGS_PF|X86_EFLAGS_AF|
	       X86_EFLAGS_ZF|X86_EFLAGS_SF|X86_EFLAGS_TF|
	       X86_EFLAGS_IF|X86_EFLAGS_DF|X86_EFLAGS_OF|
	       X86_EFLAGS_IOPL|X86_EFLAGS_NT|X86_EFLAGS_RF|
	       X86_EFLAGS_AC|X86_EFLAGS_ID);
}
```

**校对结论**：✅ **实现准确，MSR_SYSCALL_MASK 包含的标志位正确**

**重要发现 - wrmsrq_cstar() 的特殊处理**（`arch/x86/kernel/cpu/common.c:2183-2196`）：
```c
static __always_inline void wrmsrq_cstar(unsigned long val)
{
	/*
	 * Intel CPUs do not support 32-bit SYSCALL. Writing to MSR_CSTAR
	 * is so far ignored by the CPU, but raises a #VE trap in a TDX
	 * guest. Avoid the pointless write on all Intel CPUs.
	 */
	if (boot_cpu_data.x86_vendor != X86_VENDOR_INTEL)
		wrmsrq(MSR_CSTAR, val);
}
```

**说明**：Intel CPU 不支持 32 位 SYSCALL，内核会跳过 MSR_CSTAR 的设置（避免在 TDX guest 中触发 #VE）。

---

### 2.4 调用流程验证 ✅

**文档描述**（第 28-35 行）：
```
start_kernel()
    └─ trap_init()（main.c:958 → traps.c:1561）
        └─ cpu_init()（cpu/common.c:2384）
            └─ syscall_init()
                └─ idt_syscall_init()（同文件:2198）
```

**源代码验证**：

1. **start_kernel() → trap_init()**（`init/main.c:958`）：
```c
void start_kernel(void)
{
    ...
    trap_init();  // 第 958 行
    ...
}
```

2. **trap_init() → cpu_init()**（`arch/x86/kernel/traps.c:1561-1577`）：
```c
void __init trap_init(void)
{
	/* Init cpu_entry_area before IST entries are set up */
	setup_cpu_entry_areas();

	/* Init GHCB memory pages when running as an SEV-ES guest */
	sev_es_init_vc_handling();

	/* Initialize TSS before setting up traps so ISTs work */
	cpu_init_exception_handling(true);

	/* Setup traps as cpu_init() might #GP */
	if (!cpu_feature_enabled(X86_FEATURE_FRED))
		idt_setup_traps();

	cpu_init();  // 第 1576 行
}
```

3. **cpu_init() → syscall_init()**（`arch/x86/kernel/cpu/common.c:2384-2403`）：
```c
void cpu_init(void)
{
	struct task_struct *cur = current;
	int cpu = raw_smp_processor_id();

	...

	if (IS_ENABLED(CONFIG_X86_64)) {
		loadsegment(fs, 0);
		memset(cur->thread.tls_array, 0, GDT_ENTRY_TLS_ENTRIES * 8);
		syscall_init();  // 第 2403 行
		...
	}
	...
}
```

**校对结论**：✅ **调用流程完全正确**

---

### 2.5 INT 0x80 设置验证 ⚠️ **需要微调**

**文档描述**（第 70-94 行）：
- 设置时机：`init_IRQ()` → `idt_setup_ia32_syscall_gate()`
- 入口函数：`entry_INT80_32`（`arch/x86/entry/entry_32.S` 或 `entry_64.S`）

**源代码验证**：

#### (1) INT 0x80 向量定义 ✅
（`arch/x86/include/asm/irq_vectors.h:38`）：
```c
#define IA32_SYSCALL_VECTOR		0x80
```

#### (2) IDT 表条目定义 ⚠️ **64位系统使用 asm_int80_emulation**
（`arch/x86/kernel/idt.c:122-128`）：
```c
static const struct idt_data ia32_idt[] __initconst = {
#if defined(CONFIG_IA32_EMULATION)
	SYSG(IA32_SYSCALL_VECTOR,	asm_int80_emulation),  // 64位系统
#elif defined(CONFIG_X86_32)
	SYSG(IA32_SYSCALL_VECTOR,	entry_INT80_32),       // 32位系统
#endif
};
```

**重要发现**：
- **64 位系统**（CONFIG_IA32_EMULATION）：使用 `asm_int80_emulation`
- **32 位系统**（CONFIG_X86_32）：使用 `entry_INT80_32`

#### (3) 设置时机验证 ✅
（`arch/x86/kernel/idt.c:232-238`）：
```c
void __init idt_setup_traps(void)
{
	idt_setup_from_table(idt_table, def_idts, ARRAY_SIZE(def_idts), true);

	if (ia32_enabled())
		idt_setup_from_table(idt_table, ia32_idt, ARRAY_SIZE(ia32_idt), true);
}
```

**调用时机**：`trap_init()` → `idt_setup_traps()`（而非 `init_IRQ()`）

**校对结论**：⚠️ **需要微调**

**建议修正**：
1. **设置时机**：应为 `trap_init()` → `idt_setup_traps()`，而非 `init_IRQ()` → `idt_setup_ia32_syscall_gate()`
   - `idt_setup_ia32_syscall_gate()` 函数在源代码中不存在
   - 实际是通过 `idt_setup_traps()` 调用 `idt_setup_from_table(idt_table, ia32_idt, ...)`

2. **入口函数名称**：
   - 64 位系统（CONFIG_IA32_EMULATION）：`asm_int80_emulation`
   - 32 位系统（CONFIG_X86_32）：`entry_INT80_32`

3. **文件位置**：
   - `entry_INT80_32`：`arch/x86/entry/entry_32.S:933`（仅 32 位系统）
   - `asm_int80_emulation`：通过 `DECLARE_IDTENTRY_RAW` 定义（64 位系统）

---

### 2.6 entry_SYSCALL_64 验证 ✅

**文档描述**（第 64 行）：
- entry_SYSCALL_64 在 `arch/x86/entry/entry_64.S`

**源代码验证**（`arch/x86/entry/entry_64.S:87-170`）：
```asm
/*
 * 64-bit SYSCALL instruction entry. Up to 6 arguments in registers.
 *
 * This is the only entry point used for 64-bit system calls.
 * ...
 * SYSCALL saves rip to rcx, clears rflags.RF, then saves rflags to r11,
 * then loads new ss, cs, and rip from previously programmed MSRs.
 * ...
 */

SYM_CODE_START(entry_SYSCALL_64)
	UNWIND_HINT_ENTRY
	ENDBR

	swapgs
	/* tss.sp2 is scratch space. */
	movq	%rsp, PER_CPU_VAR(cpu_tss_rw + TSS_sp2)
	SWITCH_TO_KERNEL_CR3 scratch_reg=%rsp
	movq	PER_CPU_VAR(cpu_current_top_of_stack), %rsp

	...
	call	do_syscall_64		/* returns with IRQs disabled */
	...
	sysretq
SYM_CODE_END(entry_SYSCALL_64)
```

**校对结论**：✅ **入口点位置和实现完全正确**

---

### 2.7 entry_SYSENTER_compat 验证 ✅

**文档描述**（第 58、134 行）：
- entry_SYSENTER_compat 用于 32 位 SYSENTER

**源代码验证**（`arch/x86/entry/entry_64_compat.S:50-134`）：
```asm
/*
 * 32-bit SYSENTER entry.
 * ...
 */
SYM_CODE_START(entry_SYSENTER_compat)
	UNWIND_HINT_ENTRY
	ENDBR
	/* Interrupts are off on entry. */
	swapgs

	...
	movq	PER_CPU_VAR(cpu_current_top_of_stack), %rsp

	/* Construct struct pt_regs on stack */
	pushq	$__USER_DS		/* pt_regs->ss */
	pushq	$0			/* pt_regs->sp = 0 (placeholder) */
	...
SYM_CODE_END(entry_SYSENTER_compat)
```

**校对结论**：✅ **入口点位置和实现正确**

---

### 2.8 系统调用表验证 ✅

**文档描述**（第 201-216 行）：
```c
asmlinkage const sys_call_ptr_t sys_call_table[] = {
    [0] = __x64_sys_read,
    [1] = __x64_sys_write,
    [2] = __x64_sys_open,
    ...
};

__visible const sys_call_ptr_t ia32_sys_call_table[] = {
    [0] = __ia32_sys_restart_syscall,
    [1] = __ia32_sys_exit,
    ...
};
```

**源代码验证**（`arch/x86/entry/syscall_64.c:24-31`）：
```c
/*
 * The sys_call_table[] is no longer used for system calls, but
 * kernel/trace/trace_syscalls.c still wants to know the system
 * call address.
 */
#define __SYSCALL(nr, sym) __x64_##sym,
const sys_call_ptr_t sys_call_table[] = {
#include <asm/syscalls_64.h>
};
#undef  __SYSCALL
```

**重要发现**：
- `sys_call_table[]` **仅用于 tracing**，实际系统调用通过 `switch-case` 分发
- 实际实现在 `do_syscall_x64()` 中使用 switch-case

**do_syscall_x64 实现**（`arch/x86/entry/syscall_64.c:34-41`）：
```c
#define __SYSCALL(nr, sym) case nr: return __x64_##sym(regs);

static long x64_sys_call(const struct pt_regs *regs, unsigned int nr)
{
	switch (nr) {
	#include <asm/syscalls_64.h>
	default: return __x64_sys_ni_syscall(regs);
	}
}
```

**校对结论**：✅ **系统调用表定义正确，但实际调用机制已演进为 switch-case**

---

### 2.9 调用路径验证 ⚠️ **32位路径需要微调**

**文档描述**（第 218-228 行）：
```
64位程序：
    syscall → entry_SYSCALL_64 → do_syscall_64 → sys_call_table[rax]

32位程序（Intel CPU）：
    sysenter → entry_SYSENTER_compat → do_SYSENTER_32 → ia32_sys_call_table[eax]

32位程序（所有 CPU，兼容路径）：
    int $0x80 → entry_INT80_32 → do_int80_syscall_32 → ia32_sys_call_table[eax]
```

**源代码验证**：

#### (1) 64 位路径 ✅
```
syscall → entry_SYSCALL_64 → do_syscall_64 → x64_sys_call(switch-case)
```

#### (2) 32 位 SYSENTER 路径 ⚠️
（`arch/x86/entry/entry_64_compat.S:50-134`）：
- 入口：`entry_SYSENTER_compat`
- 调用函数：**do_fast_syscall_32**（而非 do_SYSENTER_32）

#### (3) 32 位 INT 0x80 路径 ✅
（`arch/x86/entry/entry_32.S:933-983`）：
```asm
SYM_FUNC_START(entry_INT80_32)
	...
	movl	%esp, %eax
	call	do_int80_syscall_32
	...
SYM_FUNC_END(entry_INT80_32)
```

**校对结论**：⚠️ **32 位 SYSENTER 调用函数名称需要修正**
- 应为 `do_fast_syscall_32`，而非 `do_SYSENTER_32`

---

### 2.10 时间线对比验证 ⚠️ **INT 0x80 设置时机需要修正**

**文档描述**（第 142-171 行）：
```
start_kernel()
    │
    ├─ 阶段 2a: trap_init()  ← 第一阶段
    │       └─ cpu_init()
    │           └─ syscall_init()
    │               ...
    │       【此时 SYSCALL/SYSENTER 机制已可用，但 INT 0x80 尚未就绪】
    │
    ├─ 阶段 2c: init_IRQ()  ← 第二阶段
    │       ...
    │       └─ idt_setup_ia32_syscall_gate()
    │           └─ idt_table[0x80] = entry_INT80_32 ✨ INT 0x80 就绪
    │       【此时 INT 0x80 机制也可用，所有系统调用机制完全就绪】
```

**源代码验证**：

**实际调用顺序**（`init/main.c:958-1004`）：
```c
void start_kernel(void)
{
	...
	trap_init();  // 第 958 行
	...
	init_IRQ();   // 第 1004 行
	...
}
```

**trap_init() 内部流程**（`arch/x86/kernel/traps.c:1561-1577`）：
```c
void __init trap_init(void)
{
	setup_cpu_entry_areas();
	sev_es_init_vc_handling();
	cpu_init_exception_handling(true);

	if (!cpu_feature_enabled(X86_FEATURE_FRED))
		idt_setup_traps();  // ← 在这里设置 INT 0x80

	cpu_init();  // ← 在这里设置 SYSCALL/SYSENTER
}
```

**关键发现**：
- `idt_setup_traps()` 在 `cpu_init()` **之前**调用
- 因此 **INT 0x80 比 SYSCALL/SYSENTER 更早就绪**

**校对结论**：⚠️ **INT 0x80 的设置时机需要修正**

**建议修正**：
```
start_kernel()
    │
    ├─ trap_init()
    │   ├─ idt_setup_traps()  ← INT 0x80 在这里设置
    │   │   └─ idt_setup_from_table(idt_table, ia32_idt, ...)
    │   │       └─ idt_table[0x80] = asm_int80_emulation ✨ INT 0x80 就绪
    │   │
    │   └─ cpu_init()  ← SYSCALL/SYSENTER 在这里设置
    │       └─ syscall_init()
    │           └─ idt_syscall_init()
    │               ├─ wrmsr(MSR_LSTAR, entry_SYSCALL_64) ✨ SYSCALL 就绪
    │               └─ wrmsr(MSR_IA32_SYSENTER_EIP, entry_SYSENTER_compat) ✨ SYSENTER 就绪
    │
    └─ init_IRQ()  ← 仅设置硬件中断，不涉及系统调用
        └─ native_init_IRQ()
            └─ idt_setup_apic_and_irq_gates()
```

---

## 三、SYSCALL vs SYSENTER 对比验证 ✅

**文档描述**（第 265-282 行）：详细对比表格

**源代码验证**：完全匹配，包括：
- 指令对：`syscall/sysret` vs `sysenter/sysexit`
- MSR 配置：MSR_LSTAR vs MSR_IA32_SYSENTER_EIP
- 返回地址保存：RCX ← RIP（SYSCALL 自动）vs 手动保存（SYSENTER）
- RFLAGS 保存：R11 ← RFLAGS（SYSCALL）vs 不保存（SYSENTER）

**校对结论**：✅ **对比表格完全准确**

---

## 四、需要修正的问题汇总

### 4.1 INT 0x80 设置时机（高优先级）

**当前描述**（第 75 行）：
> 设置时机：`init_IRQ()` → `idt_setup_ia32_syscall_gate()`（IDT 演进阶段 5）

**建议修正**：
> 设置时机：`trap_init()` → `idt_setup_traps()` → `idt_setup_from_table(ia32_idt)`（早于 SYSCALL/SYSENTER）

**原因**：
- `idt_setup_ia32_syscall_gate()` 函数不存在
- INT 0x80 在 `trap_init()` 中通过 `idt_setup_traps()` 设置
- **INT 0x80 比 SYSCALL/SYSENTER 更早就绪**

---

### 4.2 64位系统 INT 0x80 入口函数名称（中优先级）

**当前描述**（第 78 行）：
> 入口函数：`entry_INT80_32`（`arch/x86/entry/entry_32.S` 或 `entry_64.S`）

**建议修正**：
> 入口函数：
> - 64位系统（CONFIG_IA32_EMULATION）：`asm_int80_emulation`
> - 32位系统（CONFIG_X86_32）：`entry_INT80_32`（`arch/x86/entry/entry_32.S`）

**原因**：
- 64 位系统使用 `asm_int80_emulation`（通过 IDT 宏定义）
- 32 位系统使用 `entry_INT80_32`（在 entry_32.S 中）
- `entry_64.S` 中**没有** INT 0x80 相关代码

---

### 4.3 32位 SYSENTER 调用函数名称（低优先级）

**当前描述**（第 224 行）：
> sysenter → entry_SYSENTER_compat → do_SYSENTER_32 → ia32_sys_call_table[eax]

**建议修正**：
> sysenter → entry_SYSENTER_compat → do_fast_syscall_32 → ia32_sys_call(switch-case)

**原因**：
- 实际调用 `do_fast_syscall_32`，而非 `do_SYSENTER_32`
- 系统调用通过 switch-case 分发，而非直接查表

---

### 4.4 时间线对比中的 INT 0x80 位置（高优先级）

**当前描述**（第 158-168 行）：
```
trap_init()
    └─ syscall_init() ✨ SYSCALL/SYSENTER 就绪
    【此时 INT 0x80 尚未就绪】

init_IRQ()
    └─ idt_setup_ia32_syscall_gate()
        └─ idt_table[0x80] = entry_INT80_32 ✨ INT 0x80 就绪
```

**建议修正**：
```
trap_init()
    ├─ idt_setup_traps()
    │   └─ idt_table[0x80] = asm_int80_emulation ✨ INT 0x80 就绪
    │
    └─ cpu_init()
        └─ syscall_init()
            └─ idt_syscall_init()
                ├─ MSR_LSTAR ← entry_SYSCALL_64 ✨ SYSCALL 就绪
                └─ MSR_IA32_SYSENTER_EIP ← entry_SYSENTER_compat ✨ SYSENTER 就绪
    【此时所有系统调用机制已就绪】

init_IRQ()
    └─ native_init_IRQ()
        └─ idt_setup_apic_and_irq_gates()  ← 仅设置硬件中断
```

**原因**：
- `idt_setup_traps()` 在 `cpu_init()` 之前调用
- INT 0x80 **先于** SYSCALL/SYSENTER 就绪
- `init_IRQ()` 不涉及系统调用设置

---

## 五、补充说明（不影响准确性）

### 5.1 系统调用表已不再用于实际分发

**源代码注释**（`arch/x86/entry/syscall_64.c:24-26`）：
```c
/*
 * The sys_call_table[] is no longer used for system calls, but
 * kernel/trace/trace_syscalls.c still wants to know the system
 * call address.
 */
```

**实际分发机制**：switch-case（`x64_sys_call` 和 `ia32_sys_call`）

**建议**：在文档中补充说明 `sys_call_table[]` 主要用于 tracing，实际系统调用通过 switch-case 分发。

---

### 5.2 wrmsrq_cstar() 的特殊处理

**源代码发现**（`arch/x86/kernel/cpu/common.c:2183-2196`）：
```c
static __always_inline void wrmsrq_cstar(unsigned long val)
{
	/*
	 * Intel CPUs do not support 32-bit SYSCALL. Writing to MSR_CSTAR
	 * is so far ignored by the CPU, but raises a #VE trap in a TDX
	 * guest. Avoid the pointless write on all Intel CPUs.
	 */
	if (boot_cpu_data.x86_vendor != X86_VENDOR_INTEL)
		wrmsrq(MSR_CSTAR, val);
}
```

**建议**：在文档第 131 行补充说明 Intel CPU 跳过 MSR_CSTAR 设置的原因。

---

## 六、验证细节记录

### 6.1 验证文件清单

| 文件路径 | 验证内容 | 结果 |
|---------|---------|------|
| `arch/x86/include/asm/msr-index.h` | MSR 寄存器地址定义 | ✅ 完全匹配 |
| `arch/x86/kernel/cpu/common.c` | syscall_init() 和 idt_syscall_init() | ✅ 实现准确 |
| `arch/x86/kernel/traps.c` | trap_init() 调用流程 | ✅ 流程正确 |
| `arch/x86/kernel/idt.c` | INT 0x80 IDT 条目设置 | ⚠️ 函数名不存在 |
| `arch/x86/entry/entry_64.S` | entry_SYSCALL_64 实现 | ✅ 实现准确 |
| `arch/x86/entry/entry_64_compat.S` | entry_SYSENTER_compat 实现 | ✅ 实现准确 |
| `arch/x86/entry/entry_32.S` | entry_INT80_32 实现 | ✅ 实现准确 |
| `arch/x86/entry/syscall_64.c` | 系统调用表和分发机制 | ✅ 定义准确 |
| `init/main.c` | trap_init() 和 init_IRQ() 调用顺序 | ✅ 顺序正确 |

---

### 6.2 关键代码位置汇总

| 描述 | 文件 | 行号 |
|-----|------|------|
| MSR 寄存器定义 | `arch/x86/include/asm/msr-index.h` | 11-14, 243-246 |
| syscall_init() | `arch/x86/kernel/cpu/common.c` | 2234-2248 |
| idt_syscall_init() | `arch/x86/kernel/cpu/common.c` | 2198-2230 |
| wrmsrq_cstar() 特殊处理 | `arch/x86/kernel/cpu/common.c` | 2183-2196 |
| cpu_init() | `arch/x86/kernel/cpu/common.c` | 2384-2434 |
| trap_init() | `arch/x86/kernel/traps.c` | 1561-1577 |
| idt_setup_traps() | `arch/x86/kernel/idt.c` | 232-238 |
| ia32_idt 定义 | `arch/x86/kernel/idt.c` | 122-128 |
| entry_SYSCALL_64 | `arch/x86/entry/entry_64.S` | 87-170 |
| entry_SYSENTER_compat | `arch/x86/entry/entry_64_compat.S` | 50-134 |
| entry_INT80_32 | `arch/x86/entry/entry_32.S` | 933-983 |
| do_syscall_64 | `arch/x86/entry/syscall_64.c` | 87-101 |
| sys_call_table | `arch/x86/entry/syscall_64.c` | 29-31 |
| x64_sys_call (switch-case) | `arch/x86/entry/syscall_64.c` | 34-41 |

---

## 七、总体建议

### 7.1 必须修正的问题
1. **INT 0x80 设置时机**：从 `init_IRQ()` 修正为 `trap_init()` → `idt_setup_traps()`
2. **时间线对比**：INT 0x80 **先于** SYSCALL/SYSENTER 就绪，需要调整顺序
3. **64位 INT 0x80 入口**：从 `entry_INT80_32` 修正为 `asm_int80_emulation`

### 7.2 可选补充的内容
1. 说明 `sys_call_table[]` 仅用于 tracing，实际使用 switch-case 分发
2. 补充 Intel CPU 跳过 MSR_CSTAR 设置的原因（TDX guest #VE trap）
3. 说明 `do_SYSENTER_32` 应为 `do_fast_syscall_32`

---

## 八、校对结论

✅ **文档质量评价：优秀**

**优点**：
- MSR 寄存器配置描述准确
- syscall_init() 和 idt_syscall_init() 实现准确
- SYSCALL vs SYSENTER 对比详细且准确
- entry_SYSCALL_64 入口点验证正确
- 系统调用表结构描述准确

**需要改进**：
- INT 0x80 设置时机的描述（高优先级）
- 时间线对比中的顺序调整（高优先级）
- 64位系统 INT 0x80 入口函数名称（中优先级）
- 32位 SYSENTER 调用函数名称（低优先级）

**建议**：
修正上述 4 个问题后，该文档将成为**完全准确**的 Linux 系统调用初始化参考资料。

---

**校对人员签名**：Claude Sonnet 4.5
**校对日期**：2026-02-12
**校对方法**：源代码对照验证
**校对状态**：✅ 完成
