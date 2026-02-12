# Linux 内核系统调用初始化详解

> **本文档为** [Linux 内核启动与初始化](LINUX_KERNEL_INIT.md) **的子文档**

本文档详细介绍 Linux 内核启动过程中系统调用机制的初始化，包括 trap_init()、syscall_init() 的实现细节，以及 INT 0x80 和 SYSCALL/SYSENTER 两种系统调用机制的对比。

**主要内容**：
1. trap_init() 调用流程与系统调用初始化
2. syscall_init() 与 MSR 寄存器配置
3. INT 0x80 vs SYSCALL/SYSENTER 详细对比
4. 32位兼容机制与 entry_SYSCALL_64 入口

**相关文档**：
- [x86 中断、异常、陷阱：Intel SDM 规范与 Linux 实现](X86_INTERRUPT_EXCEPTION_TRAP.md) - 基础概念（INT 0x80 为何在 CPU 层面是 Exception、Interrupt/Exception/Trap 区别）
- [Linux 内核启动与初始化](LINUX_KERNEL_INIT.md) - 主启动流程
- [IDT 表的演进流程详解](LINUX_KERNEL_IDT_EVOLUTION.md) - 两个 IDT 表（bringup_idt_table、idt_table）、5 个演进阶段、GDT/IDT 对比、IST 机制、中断状态管理
- [Linux 中断处理](LINUX_INTERRUPT_GUIDE.md) - 运行时中断处理
- [BIOS IVT vs Kernel IDT](BIOS_IVT_VS_KERNEL_IDT.md) - IVT 与 IDT 对比

---

## 1. trap_init() 与系统调用初始化

**cpu_init()** 在 **trap_init()** 中调用（非 setup_arch）。用户态 `syscall` 跳转到 entry_SYSCALL_64 → do_syscall_64 → sys_call_table[nr]。

**调用层级：**

```
start_kernel()
    └─ trap_init()（main.c:958 → traps.c:1561）  【内核接管 syscall】
        └─ cpu_init()（cpu/common.c:2384）
            └─ syscall_init()
                └─ idt_syscall_init()（同文件:2198）
                    └─ MSR_STAR、MSR_LSTAR(entry_SYSCALL_64)、MSR_SYSCALL_MASK 等
```

**syscall_init()**：

```c
void syscall_init(void)
{
	wrmsr(MSR_STAR, 0, (__USER32_CS << 16) | __KERNEL_CS);
	if (!cpu_feature_enabled(X86_FEATURE_FRED))
		idt_syscall_init();
}
```

**idt_syscall_init()**：

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
	wrmsrq(MSR_SYSCALL_MASK, X86_EFLAGS_CF|...|X86_EFLAGS_ID);  // syscall 时清除的 RFLAGS
}
```

entry_SYSCALL_64 在 `arch/x86/entry/entry_64.S`，保存 pt_regs 后调用 do_syscall_64；系统调用表在 `arch/x86/entry/syscall_64.c`（sys_call_table）。

### 1.1 系统调用的两种机制：IDT (INT 0x80) vs MSR (SYSCALL/SYSENTER)

Linux 内核支持**两种系统调用机制**，它们的设置阶段和实现方式完全不同：

**1. 基于 IDT 的传统机制：INT 0x80（32位兼容）**

| 特性 | 说明 |
|------|------|
| **原理** | 软件中断，查询 IDT 表第 0x80 个条目 |
| **设置时机** | `trap_init()` → `idt_setup_traps()` → `idt_setup_from_table(ia32_idt)` |
| **设置位置** | `arch/x86/kernel/idt.c` |
| **触发方式** | `int $0x80` 指令 |
| **入口函数** | `asm_int80_emulation`（64位）或 `entry_INT80_32`（32位，`arch/x86/entry/entry_32.S`） |
| **系统调用号** | %eax |
| **参数传递** | %ebx, %ecx, %edx, %esi, %edi, %ebp（32位寄存器） |
| **系统调用表** | `ia32_sys_call_table`（兼容表） |
| **性能** | 慢（需要查 IDT、特权级切换、栈切换） |
| **适用范围** | 32位程序（CONFIG_IA32_EMULATION），64位程序也可用但不推荐 |

**设置代码**（在 `trap_init()` 中）：
```c
// arch/x86/kernel/idt.c:122-128
static const struct idt_data ia32_idt[] __initconst = {
#if defined(CONFIG_IA32_EMULATION)
    SYSG(IA32_SYSCALL_VECTOR,	asm_int80_emulation),  // 64位系统
#elif defined(CONFIG_X86_32)
    SYSG(IA32_SYSCALL_VECTOR,	entry_INT80_32),       // 32位系统
#endif
};

// arch/x86/kernel/idt.c:232-238
void __init idt_setup_traps(void)
{
    idt_setup_from_table(idt_table, def_idts, ARRAY_SIZE(def_idts), true);

    if (ia32_enabled())
        idt_setup_from_table(idt_table, ia32_idt, ARRAY_SIZE(ia32_idt), true);
}
```

**2. 基于 MSR 的快速机制：SYSCALL/SYSENTER（现代方式）**

| 特性 | SYSCALL（AMD/Intel 64位） | SYSENTER（Intel 32位） |
|------|---------------------------|------------------------|
| **原理** | 专用指令，直接从 MSR 读取入口地址 | 专用指令，从 MSR 读取入口 |
| **设置时机** | `trap_init()` → `cpu_init()` → `syscall_init()`（早于 `init_IRQ()`） |
| **设置位置** | `arch/x86/kernel/cpu/common.c` |
| **MSR 寄存器** | MSR_LSTAR (入口地址)<br>MSR_STAR (段选择子)<br>MSR_SYSCALL_MASK (RFLAGS 掩码) | MSR_IA32_SYSENTER_CS<br>MSR_IA32_SYSENTER_ESP<br>MSR_IA32_SYSENTER_EIP |
| **触发方式** | `syscall` 指令 | `sysenter` 指令 |
| **入口函数** | `entry_SYSCALL_64` | `entry_SYSENTER_compat` |
| **系统调用号** | %rax | %eax |
| **参数传递** | %rdi, %rsi, %rdx, %r10, %r8, %r9（64位寄存器） | %ebx, %ecx, %edx, %esi, %edi, %ebp |
| **系统调用表** | `sys_call_table`（64位原生表） | `ia32_sys_call_table` |
| **性能** | 快（专用硬件支持，无需查表） | 快 |
| **适用范围** | 64位程序（主要使用） | 32位程序（Intel CPU） |

**设置代码**（在 `trap_init()` 中）：
```c
// arch/x86/kernel/cpu/common.c:2234
void syscall_init(void)
{
    // 设置段选择子：用户态 CS/SS、内核态 CS
    wrmsr(MSR_STAR, 0, (__USER32_CS << 16) | __KERNEL_CS);

    if (!cpu_feature_enabled(X86_FEATURE_FRED))
        idt_syscall_init();  // 设置 SYSCALL/SYSENTER 入口
}

static inline void idt_syscall_init(void)
{
    // 64位 SYSCALL 入口
    wrmsrq(MSR_LSTAR, (unsigned long)entry_SYSCALL_64);

    // 32位兼容模式入口（如果启用）
    if (ia32_enabled()) {
        wrmsrq_cstar((unsigned long)entry_SYSCALL_compat);  // CSTAR: 32位 syscall
        wrmsrq_safe(MSR_IA32_SYSENTER_CS, (u64)__KERNEL_CS);
        wrmsrq_safe(MSR_IA32_SYSENTER_ESP, ...);
        wrmsrq_safe(MSR_IA32_SYSENTER_EIP, (u64)entry_SYSENTER_compat);
    }

    // syscall 指令执行时清除的 RFLAGS 位
    wrmsrq(MSR_SYSCALL_MASK, X86_EFLAGS_TF|X86_EFLAGS_DF|...|X86_EFLAGS_AC);
}
```

#### 设置阶段的时间线对比

```
内核启动流程中的系统调用机制设置：

start_kernel()
    │
    ├─ 阶段 2a: trap_init()  ← 系统调用机制初始化
    │       ├─ setup_cpu_entry_areas()
    │       ├─ cpu_init_exception_handling(true)
    │       ├─ idt_setup_traps()
    │       │   └─ idt_setup_from_table(idt_table, ia32_idt, ...)
    │       │       └─ idt_table[0x80] = asm_int80_emulation ✨ INT 0x80 就绪
    │       │
    │       └─ cpu_init()
    │           └─ syscall_init()
    │               └─ idt_syscall_init()
    │                   ├─ wrmsr(MSR_STAR) → 设置段选择子
    │                   ├─ wrmsr(MSR_LSTAR, entry_SYSCALL_64) ✨ SYSCALL 就绪
    │                   ├─ wrmsr(MSR_CSTAR, entry_SYSCALL_compat) → 32位 syscall
    │                   ├─ wrmsr(MSR_IA32_SYSENTER_EIP, entry_SYSENTER_compat) ✨ SYSENTER 就绪
    │                   └─ wrmsr(MSR_SYSCALL_MASK) → RFLAGS 掩码
    │       【此时所有系统调用机制（INT 0x80、SYSCALL、SYSENTER）已完全就绪】
    │
    ├─ 阶段 2b: early_irq_init()
    │
    ├─ 阶段 2c: init_IRQ()  ← 仅设置硬件中断，不涉及系统调用
    │       ├─ init_8259A() → 重编程 PIC
    │       └─ native_init_IRQ()
    │           └─ idt_setup_apic_and_irq_gates() → 设置 APIC/IRQ 门
    │       【硬件中断机制就绪】
    │
    └─ 阶段 2d: local_irq_enable()
```

#### 关键区别与设计考虑

**为什么需要两套机制？**

1. **性能差异**：
   - `INT 0x80`：需要查 IDT 表、特权级检查、栈切换，约 100-300 CPU 周期
   - `SYSCALL`：硬件优化路径，约 60-100 CPU 周期
   - 现代程序优先使用 SYSCALL/SYSENTER

2. **兼容性需求**：
   - `INT 0x80`：古老但通用，所有 x86 CPU 都支持
   - `SYSCALL`：AMD64/Intel 64位特有
   - `SYSENTER`：Intel Pentium II+ 才有
   - 老旧 32位程序仍依赖 `INT 0x80`

3. **设置时机对比**：
   - **IDT 机制（INT 0x80）**：在 `trap_init()` → `idt_setup_traps()` 中设置，**先于** MSR 机制
   - **MSR 机制（SYSCALL/SYSENTER）**：在 `trap_init()` → `cpu_init()` → `syscall_init()` 中设置
   - 两者都在同一个函数（trap_init()）中完成，INT 0x80 稍早，SYSCALL/SYSENTER 稍晚

4. **是否依赖 IDT**：
   - `SYSCALL/SYSENTER`：**不依赖 IDT**，直接从 MSR 跳转
   - `INT 0x80`：**依赖 IDT**，作为 IDT 表的一个条目（向量 0x80）

#### 系统调用表的统一与分离

虽然有多种调用机制，但**系统调用表（syscall table）是统一的**：

```c
// arch/x86/entry/syscall_64.c
asmlinkage const sys_call_ptr_t sys_call_table[] = {
    [0] = __x64_sys_read,
    [1] = __x64_sys_write,
    [2] = __x64_sys_open,
    // ... 所有系统调用
};

// arch/x86/entry/syscall_32.c (32位兼容表)
__visible const sys_call_ptr_t ia32_sys_call_table[] = {
    [0] = __ia32_sys_restart_syscall,
    [1] = __ia32_sys_exit,
    // ... 32位系统调用
};
```

**调用路径**：
```
64位程序：
    syscall → entry_SYSCALL_64 → do_syscall_64 → sys_call_table[rax]

32位程序（Intel CPU）：
    sysenter → entry_SYSENTER_compat → do_fast_syscall_32 → ia32_sys_call(switch-case)

32位程序（所有 CPU，兼容路径）：
    int $0x80 → asm_int80_emulation/entry_INT80_32 → do_int80_syscall_32 → ia32_sys_call(switch-case)
```

#### 实际运行时如何选择？

**用户空间库（glibc/musl）的选择逻辑**：

```c
// glibc 中的 syscall 封装（简化）
static inline long syscall(long number, ...)
{
#ifdef __x86_64__
    // 64位程序：优先使用 SYSCALL
    asm volatile("syscall" : ...);
#else
    // 32位程序
    #if defined(__i386__) && defined(USE_VSYSCALL)
        // 现代 32位：尝试 sysenter（通过 vDSO）
        return __kernel_vsyscall(...);
    #else
        // 传统 32位：回退到 int $0x80
        asm volatile("int $0x80" : ...);
    #endif
#endif
}
```

#### IDT 与系统调用机制的关联总结

| 对比维度 | IDT 表（中断描述符表） | 系统调用机制 |
|---------|----------------------|-------------|
| **主要用途** | 处理硬件中断和 CPU 异常 | 用户态进入内核态的接口 |
| **设置阶段** | 5 个阶段逐步完善（见第三节） | 2 个阶段：trap_init() 设置 MSR，init_IRQ() 设置 INT 0x80 |
| **INT 0x80 的关系** | INT 0x80 是 IDT[0x80] 的一个条目 | INT 0x80 是系统调用的一种实现方式 |
| **SYSCALL 的关系** | 完全不使用 IDT | SYSCALL 通过 MSR 实现，绕过 IDT |
| **演进时间线** | bringup_idt_table → idt_table（5 阶段） | MSR 机制先就绪 → IDT 机制后就绪 |
| **依赖关系** | 不依赖系统调用机制 | INT 0x80 依赖 IDT 表完善 |

#### SYSCALL vs SYSENTER 详细对比

虽然都是快速系统调用机制，SYSCALL 和 SYSENTER 有重要区别：

| 特性 | SYSCALL | SYSENTER |
|------|---------|----------|
| **引入者** | AMD（K6/Athlon 时代） | Intel（Pentium II） |
| **主要架构** | **64 位模式（Long Mode）** | **32 位保护模式** |
| **AMD 支持** | ✅ 原生支持（AMD64） | ✅ 支持（兼容 Intel） |
| **Intel 支持** | ✅ x86-64 后支持 | ✅ 原生支持（IA-32） |
| **指令对** | `syscall` / `sysret` | `sysenter` / `sysexit` |
| **使用场景** | 64 位程序系统调用 | 32 位程序快速系统调用 |
| **返回指令** | `sysret`（对称） | `sysexit`（对称） |
| **MSR 配置** | MSR_LSTAR（入口）<br>MSR_STAR（段选择子）<br>MSR_SYSCALL_MASK（RFLAGS 掩码） | MSR_IA32_SYSENTER_CS（段选择子）<br>MSR_IA32_SYSENTER_ESP（栈指针）<br>MSR_IA32_SYSENTER_EIP（入口地址） |
| **返回地址保存** | RCX ← RIP | 调用者需手动保存 |
| **RFLAGS 保存** | R11 ← RFLAGS | 不保存 |
| **性能** | ~60-80 周期 | ~60-80 周期 |

**硬件行为差异**：

1. **SYSCALL 自动保存返回信息**：
   ```asm
   ; 用户态执行 syscall
   syscall
   ; 硬件自动完成：
   ; RCX ← RIP（保存返回地址）
   ; R11 ← RFLAGS（保存标志位）
   ; RFLAGS ← RFLAGS & ~MSR_SYSCALL_MASK
   ; RIP ← MSR_LSTAR（跳转到内核入口）
   ; CS ← MSR_STAR[47:32]
   ; SS ← MSR_STAR[47:32] + 8
   ```

2. **SYSENTER 需要手动管理**：
   ```asm
   ; 用户态执行 sysenter（通常通过 vDSO）
   ; 调用者必须先保存 EIP 和 ESP
   push ebp
   mov ebp, esp
   sysenter
   ; 硬件完成：
   ; EIP ← MSR_IA32_SYSENTER_EIP
   ; ESP ← MSR_IA32_SYSENTER_ESP
   ; CS ← MSR_IA32_SYSENTER_CS
   ; SS ← MSR_IA32_SYSENTER_CS + 8
   ; （不保存 EFLAGS）
   ```

**Linux 内核的使用策略**：

```c
// arch/x86/kernel/cpu/common.c:2234
void syscall_init(void) {
    wrmsr(MSR_STAR, 0, (__USER32_CS << 16) | __KERNEL_CS);

    if (!cpu_feature_enabled(X86_FEATURE_FRED))
        idt_syscall_init();
}

static inline void idt_syscall_init(void) {
    // 64位 SYSCALL（主流路径）
    wrmsrq(MSR_LSTAR, (unsigned long)entry_SYSCALL_64);

    if (ia32_enabled()) {
        // 32位兼容模式 SYSCALL
        wrmsrq_cstar((unsigned long)entry_SYSCALL_compat);

        // 32位 SYSENTER（Intel CPU）
        wrmsrq_safe(MSR_IA32_SYSENTER_CS, (u64)__KERNEL_CS);
        wrmsrq_safe(MSR_IA32_SYSENTER_ESP, (unsigned long)(cpu_entry_stack(smp_processor_id()) + 1));
        wrmsrq_safe(MSR_IA32_SYSENTER_EIP, (u64)entry_SYSENTER_compat);
    }

    wrmsrq(MSR_SYSCALL_MASK, X86_EFLAGS_TF|X86_EFLAGS_DF|...|X86_EFLAGS_AC);
}
```

**用户态库的选择逻辑**：

| 程序类型 | CPU | 优先选择 | 备选 | 说明 |
|---------|-----|---------|-----|------|
| 64 位 | Intel/AMD | `syscall` | - | SYSCALL 是唯一选择 |
| 32 位 | Intel | `sysenter` (vDSO) | `int $0x80` | 通过 vDSO 提供 |
| 32 位 | AMD（旧 CPU） | `int $0x80` | - | 旧 AMD CPU 不支持 SYSENTER |
| 32 位 | AMD（新 CPU） | `sysenter` (vDSO) | `int $0x80` | 现代 AMD 已支持 |

**为什么需要 vDSO（Virtual Dynamic Shared Object）？**

SYSENTER 不保存返回地址，用户态程序无法直接使用。内核通过 vDSO 提供包装函数：

```c
// vDSO 中的 __kernel_vsyscall（简化）
__kernel_vsyscall:
    push %ecx          // 保存 ECX
    push %edx          // 保存 EDX
    push %ebp          // 保存 EBP
    mov %esp, %ebp     // 保存栈指针
    sysenter           // 进入内核
    // 内核返回到这里（通过 sysexit）
    pop %ebp
    pop %edx
    pop %ecx
    ret
```

**关键洞察**：
- **trap_init() 阶段**：设置 MSR，让 SYSCALL/SYSENTER 可用（不依赖 IDT）
- **init_IRQ() 阶段**：设置 IDT[0x80]，让 INT 0x80 可用（依赖 IDT 完善）
- 两者相互独立，但共同完成系统调用机制的初始化
- 现代程序主要使用 SYSCALL，INT 0x80 主要用于兼容
- **64 位程序**：只用 SYSCALL
- **32 位程序**：优先 SYSENTER（通过 vDSO），备选 INT 0x80

**与 IDT 内容的关系**：
- **IDT 表包含三类条目**：
  1. **CPU 异常**（0-31）：#DE, #PF, #GP 等 → idt_setup_early_handler() → idt_setup_traps()
  2. **硬件中断**（32+）：时钟、键盘、网卡等 IRQ → idt_setup_apic_and_irq_gates()
  3. **软件中断**（特定向量）：INT 0x80（32位系统调用兼容）→ idt_setup_ia32_syscall_gate()

- **SYSCALL/SYSENTER 不在 IDT 中**，它们通过 MSR 寄存器配置：
  - MSR_LSTAR：SYSCALL 入口地址（entry_SYSCALL_64）
  - MSR_STAR：段选择子（内核态 CS / 用户态 CS）
  - MSR_SYSCALL_MASK：RFLAGS 掩码（syscall 时清除的标志位）

## 2. init_IRQ() 与硬件中断门设置

**重要澄清**：`init_IRQ()` **不负责** INT 0x80 的设置，它仅处理**硬件中断**（IRQ）的 IDT 门设置。

**INT 0x80 的实际设置位置**（前面已详细说明）：
- **设置时机**：`trap_init()` → `idt_setup_traps()` → `idt_setup_from_table(ia32_idt)`
- **设置代码**：`arch/x86/kernel/idt.c:122-128`（ia32_idt 表）
- **入口函数**：`asm_int80_emulation`（64位）或 `entry_INT80_32`（32位）

**init_IRQ() 的真正职责**：

```c
// arch/x86/kernel/irqinit.c:75-93
void __init init_IRQ(void)
{
    int i;

    // 为 ISA IRQ 0-15 分配向量（ISA_IRQ_VECTOR(i) = 0x30-0x3f）
    for (i = 0; i < nr_legacy_irqs(); i++)
        per_cpu(vector_irq, 0)[ISA_IRQ_VECTOR(i)] = irq_to_desc(i);

    BUG_ON(irq_init_percpu_irqstack(smp_processor_id()));

    // 调用平台特定的中断初始化（通常是 native_init_IRQ）
    x86_init.irqs.intr_init();
}

// arch/x86/kernel/irqinit.c:95-112
void __init native_init_IRQ(void)
{
    // 执行平台特定的向量初始化前的准备工作
    x86_init.irqs.pre_vector_init();

    if (cpu_feature_enabled(X86_FEATURE_FRED))
        fred_complete_exception_setup();  // FRED 模式（新架构）
    else
        idt_setup_apic_and_irq_gates();   // 传统 APIC/IDT 模式 ✨ 关键！

    // 为 APIC 系统中断分配向量（如 Local Timer、Error、Spurious 等）
    lapic_assign_system_vectors();

    // 设置 PIC 级联中断（IRQ2 连接第二个 8259A）
    if (!acpi_ioapic && !of_ioapic && nr_legacy_irqs()) {
        if (request_irq(2, no_action, IRQF_NO_THREAD, "cascade", NULL))
            pr_err("%s: request_irq() failed\n", "cascade");
    }
}
```

**idt_setup_apic_and_irq_gates() 的作用**：

```c
// arch/x86/kernel/idt.c:285-303
void __init idt_setup_apic_and_irq_gates(void)
{
    int i = FIRST_EXTERNAL_VECTOR;  // 0x20（32）

    void *entry;

    // 设置 APIC 特殊中断向量（如 Local Timer、Error、Spurious 等）
    idt_setup_from_table(idt_table, apic_idts, ARRAY_SIZE(apic_idts), true);

    // 为所有外部中断（IRQ）设置默认门（32-255）
    for_each_clear_bit_from(i, system_vectors, FIRST_SYSTEM_VECTOR) {
        entry = irq_entries_start + IDT_ALIGN * (i - FIRST_EXTERNAL_VECTOR);
        set_intr_gate(i, entry);  // 设置中断门
    }

    // 设置系统向量（如 Local Timer: 0xec、Thermal: 0xfa 等）
#ifdef CONFIG_X86_LOCAL_APIC
    for_each_set_bit_from(i, system_vectors, NR_VECTORS) {
        set_bit(i, system_vectors);
        entry = spurious_entries_start + IDT_ALIGN * (i - FIRST_SYSTEM_VECTOR);
        set_intr_gate(i, entry);
    }
#endif
}
```

**时间线总结**：

```
start_kernel()
    │
    ├─ trap_init()
    │   ├─ idt_setup_traps()
    │   │   └─ idt_setup_from_table(idt_table, ia32_idt, ...)
    │   │       └─ idt_table[0x80] = asm_int80_emulation  ✨ INT 0x80 就绪
    │   │
    │   └─ cpu_init() → syscall_init() → idt_syscall_init()
    │       └─ MSR_LSTAR = entry_SYSCALL_64  ✨ SYSCALL 就绪
    │
    ├─ init_IRQ()  ← 当前位置
    │   └─ native_init_IRQ()
    │       └─ idt_setup_apic_and_irq_gates()
    │           ├─ 设置 APIC 特殊中断门（Local Timer, Error, Spurious 等）
    │           ├─ 设置 IRQ 门（向量 32-255）  ✨ 硬件中断就绪
    │           └─ 注册系统向量
    │
    └─ local_irq_enable()  ← 开启硬件中断
```

**关键区别**：

| 中断类型 | 设置函数 | 设置内容 | 作用 |
|---------|---------|---------|------|
| **系统调用（INT 0x80）** | `trap_init()` → `idt_setup_traps()` | `idt_table[0x80] = asm_int80_emulation` | 32位程序兼容系统调用 |
| **系统调用（SYSCALL）** | `trap_init()` → `syscall_init()` | `MSR_LSTAR = entry_SYSCALL_64` | 64位程序快速系统调用 |
| **硬件中断（IRQ）** | `init_IRQ()` → `idt_setup_apic_and_irq_gates()` | `idt_table[32-255] = irq_entries_start + offset` | 时钟、键盘、网卡等硬件中断 |
| **CPU 异常** | `trap_init()` → `idt_setup_traps()` | `idt_table[0-31] = page_fault, divide_error 等` | #PF、#GP、#DE 等 CPU 异常 |

**向量分配总览**：

```
IDT 向量分配（x86-64）：
┌─────────────────────────────────────────────────────────┐
│ 0-31   : CPU 异常（#DE, #PF, #GP 等）                    │ ← idt_setup_traps()
│ 32-127 : 外部硬件中断（IRQ 0-95）                        │ ← idt_setup_apic_and_irq_gates()
│ 128    : IA32_SYSCALL_VECTOR (0x80, INT 0x80)           │ ← idt_setup_traps() (ia32_idt)
│ 129-236: 保留/可分配 IRQ                                 │ ← idt_setup_apic_and_irq_gates()
│ 237-255: 系统向量（Local Timer, IPI, Thermal 等）        │ ← idt_setup_apic_and_irq_gates()
└─────────────────────────────────────────────────────────┘
```

**常见误解澄清**：
- ❌ **错误认知**：init_IRQ() 设置 INT 0x80
- ✅ **实际情况**：INT 0x80 在 trap_init() 中设置，init_IRQ() 只设置硬件中断（IRQ）

## 3. entry_SYSCALL_64 入口点详解

`entry_SYSCALL_64` 是 64 位程序系统调用的汇编入口点，负责：
1. 从用户态切换到内核态（切换栈、切换页表）
2. 构造 `struct pt_regs` 保存用户态寄存器
3. 调用 C 函数 `do_syscall_64` 执行系统调用
4. 优化返回路径（SYSRET vs IRET）

### 3.1 完整汇编代码注解

```asm
// arch/x86/entry/entry_64.S:87-170
SYM_CODE_START(entry_SYSCALL_64)
    UNWIND_HINT_ENTRY
    ENDBR

    // ========== 阶段 1: 切换到内核环境 ==========
    swapgs                              // 交换 GS 段（用户 GS ↔ 内核 GS）
    /* tss.sp2 is scratch space. */
    movq    %rsp, PER_CPU_VAR(cpu_tss_rw + TSS_sp2)  // 保存用户栈指针到 TSS.sp2
    SWITCH_TO_KERNEL_CR3 scratch_reg=%rsp            // 切换页表（CR3）到内核页表
    movq    PER_CPU_VAR(cpu_current_top_of_stack), %rsp  // 切换到内核栈

SYM_INNER_LABEL(entry_SYSCALL_64_safe_stack, SYM_L_GLOBAL)
    ANNOTATE_NOENDBR

    // ========== 阶段 2: 构造 struct pt_regs ==========
    /* Construct struct pt_regs on stack */
    pushq   $__USER_DS                  // pt_regs->ss（用户态 SS）
    pushq   PER_CPU_VAR(cpu_tss_rw + TSS_sp2)  // pt_regs->sp（用户态 RSP）
    pushq   %r11                        // pt_regs->flags（SYSCALL 自动保存到 R11）
    pushq   $__USER_CS                  // pt_regs->cs（用户态 CS）
    pushq   %rcx                        // pt_regs->ip（SYSCALL 自动保存返回地址到 RCX）
SYM_INNER_LABEL(entry_SYSCALL_64_after_hwframe, SYM_L_GLOBAL)
    pushq   %rax                        // pt_regs->orig_ax（系统调用号）

    PUSH_AND_CLEAR_REGS rax=$-ENOSYS    // 保存所有通用寄存器（RDI, RSI, RDX, R10, R8, R9 等）

    // ========== 阶段 3: 调用 C 函数处理系统调用 ==========
    /* IRQs are off. */
    movq    %rsp, %rdi                  // 第一个参数：struct pt_regs *regs
    /* Sign extend the lower 32bit as syscall numbers are treated as int */
    movslq  %eax, %rsi                  // 第二个参数：int nr（系统调用号，符号扩展）

    /* clobbers %rax, make sure it is after saving the syscall nr */
    IBRS_ENTER                          // Spectre v2 缓解
    UNTRAIN_RET                         // Retpoline 缓解
    CLEAR_BRANCH_HISTORY                // 分支历史清除

    call    do_syscall_64               // 调用 C 函数（返回值在 AL：true=SYSRET, false=IRET）

    // ========== 阶段 4: 选择返回路径 ==========
    /*
     * Try to use SYSRET instead of IRET if we're returning to
     * a completely clean 64-bit userspace context.  If we're not,
     * go to the slow exit path.
     * In the Xen PV case we must use iret anyway.
     */

    ALTERNATIVE "testb %al, %al; jz swapgs_restore_regs_and_return_to_usermode", \
        "jmp swapgs_restore_regs_and_return_to_usermode", X86_FEATURE_XENPV
        // 如果 do_syscall_64 返回 false（AL=0），跳转到慢速路径（IRET）
        // XEN PV 虚拟化环境总是使用 IRET

    // ========== 快速路径: SYSRET 返回 ==========
    /*
     * We win! This label is here just for ease of understanding
     * perf profiles. Nothing jumps here.
     */
syscall_return_via_sysret:
    IBRS_EXIT                           // 退出 Spectre 缓解
    POP_REGS pop_rdi=0                  // 恢复所有寄存器（除了 RSP 和 RDI）

    /*
     * Now all regs are restored except RSP and RDI.
     * Save old stack pointer and switch to trampoline stack.
     */
    movq    %rsp, %rdi                  // RDI = 当前内核栈指针
    movq    PER_CPU_VAR(cpu_tss_rw + TSS_sp0), %rsp  // 切换到 trampoline 栈
    UNWIND_HINT_END_OF_STACK

    pushq   RSP-RDI(%rdi)               // 保存用户 RSP 到 trampoline 栈
    pushq   (%rdi)                      // 保存用户 RDI 到 trampoline 栈

    /*
     * We are on the trampoline stack.  All regs except RDI are live.
     * We can do future final exit work right here.
     */
    STACKLEAK_ERASE_NOCLOBBER           // 栈清除（安全特性）

    SWITCH_TO_USER_CR3_STACK scratch_reg=%rdi  // 切换回用户页表

    popq    %rdi                        // 恢复 RDI
    popq    %rsp                        // 恢复用户栈指针
SYM_INNER_LABEL(entry_SYSRETQ_unsafe_stack, SYM_L_GLOBAL)
    ANNOTATE_NOENDBR
    swapgs                              // 恢复用户 GS
    CLEAR_CPU_BUFFERS                   // CPU 缓冲区清除（安全特性）
    sysretq                             // 快速返回用户态 ✨
    // 硬件自动完成：RIP ← RCX, RFLAGS ← R11, CS/SS 恢复

SYM_INNER_LABEL(entry_SYSRETQ_end, SYM_L_GLOBAL)
    ANNOTATE_NOENDBR
    int3                                // 不应该执行到这里（调试断点）
SYM_CODE_END(entry_SYSCALL_64)
```

### 3.2 关键硬件行为：SYSCALL 指令

**用户态执行 `syscall` 指令时，CPU 自动完成**：

```
硬件自动操作（SYSCALL 指令）：
┌──────────────────────────────────────────────────────┐
│ RCX ← RIP（保存返回地址）                             │
│ R11 ← RFLAGS（保存标志寄存器）                        │
│ RFLAGS ← RFLAGS & ~MSR_SYSCALL_MASK                  │
│   （清除 TF/DF/IF/IOPL/AC/NT 等标志位）               │
│ RIP ← MSR_LSTAR（跳转到 entry_SYSCALL_64）           │
│ CS ← MSR_STAR[47:32]（切换到内核代码段）              │
│ SS ← MSR_STAR[47:32] + 8（切换到内核栈段）            │
└──────────────────────────────────────────────────────┘
```

**注意**：
- **SYSCALL 不保存栈指针**（RSP）和段寄存器（SS），软件需手动处理
- **SYSCALL 不切换栈**，entry_SYSCALL_64 的第一件事就是切换到内核栈
- **中断自动关闭**（IF 标志位被清除），entry_SYSCALL_64 全程在关中断状态下执行

### 3.3 do_syscall_64() C 函数实现

```c
// arch/x86/entry/syscall_64.c:87-119
/* Returns true to return using SYSRET, or false to use IRET */
__visible noinstr bool do_syscall_64(struct pt_regs *regs, int nr)
{
    add_random_kstack_offset();                    // 内核栈随机化（安全特性）
    nr = syscall_enter_from_user_mode(regs, nr);   // 进入系统调用前的通用处理

    instrumentation_begin();

    // 尝试执行 64 位系统调用或 x32 系统调用
    if (!do_syscall_x64(regs, nr) && !do_syscall_x32(regs, nr) && nr != -1) {
        /* Invalid system call, but still a system call. */
        regs->ax = __x64_sys_ni_syscall(regs);     // 无效系统调用号
    }

    instrumentation_end();
    syscall_exit_to_user_mode(regs);               // 退出系统调用的通用处理

    // ========== 检查是否可以使用 SYSRET 快速返回 ==========
    /*
     * Check that the register state is valid for using SYSRET to exit
     * to userspace.  Otherwise use the slower but fully capable IRET
     * exit path.
     */

    /* XEN PV guests always use the IRET path */
    if (cpu_feature_enabled(X86_FEATURE_XENPV))
        return false;

    /* SYSRET requires RCX == RIP and R11 == EFLAGS */
    if (unlikely(regs->cx != regs->ip || regs->r11 != regs->flags))
        return false;                              // 寄存器被修改（如信号处理），必须用 IRET

    /* CS and SS must match the values set in MSR_STAR */
    if (unlikely(regs->cs != __USER_CS || regs->ss != __USER_DS))
        return false;                              // 段寄存器被修改，必须用 IRET

    // 所有检查通过，可以使用 SYSRET 快速返回
    return true;
}
```

**SYSRET vs IRET 选择逻辑**：

| 条件 | SYSRET | IRET |
|------|--------|------|
| **返回值** | `do_syscall_64` 返回 `true` | `do_syscall_64` 返回 `false` |
| **性能** | 快（~10 周期） | 慢（~50-100 周期） |
| **限制条件** | RCX=RIP, R11=RFLAGS<br>CS=__USER_CS, SS=__USER_DS | 无限制，可处理任意寄存器状态 |
| **典型场景** | 正常系统调用返回 | 信号处理后返回<br>调试陷阱后返回<br>段寄存器被修改 |
| **使用路径** | `sysretq` 指令 | `swapgs_restore_regs_and_return_to_usermode` → `iretq` |

### 3.4 struct pt_regs 的布局

```c
// arch/x86/include/asm/ptrace.h
struct pt_regs {
    unsigned long r15;       // 通用寄存器
    unsigned long r14;
    unsigned long r13;
    unsigned long r12;
    unsigned long bp;
    unsigned long bx;
    unsigned long r11;       // SYSCALL 保存的 RFLAGS
    unsigned long r10;
    unsigned long r9;
    unsigned long r8;
    unsigned long ax;        // 系统调用返回值
    unsigned long cx;        // SYSCALL 保存的返回地址（RIP）
    unsigned long dx;
    unsigned long si;
    unsigned long di;
    unsigned long orig_ax;   // 原始系统调用号
    unsigned long ip;        // 返回地址（RIP）
    unsigned long cs;        // 代码段选择子
    unsigned long flags;     // RFLAGS
    unsigned long sp;        // 栈指针（RSP）
    unsigned long ss;        // 栈段选择子
};
```

**系统调用参数传递**（Linux x86-64 ABI）：

```
系统调用约定：
┌──────────────────────────────────────────────────────┐
│ 系统调用号：RAX                                       │
│ 参数 1：   RDI                                        │
│ 参数 2：   RSI                                        │
│ 参数 3：   RDX                                        │
│ 参数 4：   R10（注意：不是 RCX，因为 SYSCALL 会破坏）  │
│ 参数 5：   R8                                         │
│ 参数 6：   R9                                         │
│ 返回值：   RAX                                        │
└──────────────────────────────────────────────────────┘
```

**为什么第 4 个参数用 R10 而不是 RCX？**
- SYSCALL 指令会将返回地址保存到 RCX
- 用户态库（glibc）会先将 RCX 复制到 R10，再执行 syscall
- 内核从 R10 读取第 4 个参数

## 4. 32 位兼容机制详解

64 位 Linux 内核支持运行 32 位程序（CONFIG_IA32_EMULATION），需要三套系统调用入口：

### 4.1 三种 32 位系统调用机制

| 机制 | 入口函数 | 触发指令 | CPU 支持 | 性能 | 用途 |
|------|---------|---------|---------|------|------|
| **INT 0x80** | `asm_int80_emulation` | `int $0x80` | 所有 x86 | 慢 | 兼容所有 32 位程序 |
| **SYSENTER** | `entry_SYSENTER_compat` | `sysenter` | Intel Pentium II+ | 快 | Intel CPU 32 位程序 |
| **SYSCALL** | `entry_SYSCALL_compat` | `syscall` | AMD64 兼容模式 | 快 | AMD CPU 32 位程序 |

### 4.2 entry_SYSENTER_compat 详解

**SYSENTER 的特殊性**：
- **不保存返回地址**（EIP）和栈指针（ESP）
- **不保存 EFLAGS**
- **必须通过 vDSO 提供的 `__kernel_vsyscall` 函数调用**

```asm
// arch/x86/entry/entry_64_compat.S:50-134
SYM_CODE_START(entry_SYSENTER_compat)
    UNWIND_HINT_ENTRY
    ENDBR
    /* Interrupts are off on entry. */
    swapgs                              // 切换到内核 GS

    pushq   %rax
    SWITCH_TO_KERNEL_CR3 scratch_reg=%rax  // 切换页表
    popq    %rax

    movq    PER_CPU_VAR(cpu_current_top_of_stack), %rsp  // 切换到内核栈

    /* Construct struct pt_regs on stack */
    pushq   $__USER_DS              // pt_regs->ss
    pushq   $0                      // pt_regs->sp = 0（占位符，vDSO 会修复）

    /*
     * Push flags.  This is nasty.  First, interrupts are currently
     * off, but we need pt_regs->flags to have IF set.  Second, if TS
     * was set in usermode, it's still set, and we're singlestepping
     * through this code.  do_SYSENTER_32() will fix up IF.
     */
    pushfq                          // pt_regs->flags (except IF = 0)
    pushq   $__USER32_CS            // pt_regs->cs
    pushq   $0                      // pt_regs->ip = 0（占位符，vDSO 会修复）
SYM_INNER_LABEL(entry_SYSENTER_compat_after_hwframe, SYM_L_GLOBAL)

    /*
     * User tracing code (ptrace or signal handlers) might assume that
     * the saved RAX contains a 32-bit number when we're invoking a 32-bit
     * syscall.  Just in case the high bits are nonzero, zero-extend
     * the syscall number.  (This could almost certainly be deleted
     * with no ill effects.)
     */
    movl    %eax, %eax              // 零扩展系统调用号到 64 位

    pushq   %rax                    // pt_regs->orig_ax
    PUSH_AND_CLEAR_REGS rax=$-ENOSYS  // 保存寄存器
    UNWIND_HINT_REGS

    cld

    /*
     * SYSENTER doesn't filter flags, so we need to clear NT and AC
     * ourselves.  To save a few cycles, we can check whether
     * either was set instead of doing an unconditional popfq.
     * This needs to happen before enabling interrupts so that
     * we don't get preempted with NT set.
     */
    testl   $X86_EFLAGS_NT|X86_EFLAGS_AC|X86_EFLAGS_TF, EFLAGS(%rsp)
    jnz     .Lsysenter_fix_flags
.Lsysenter_flags_fixed:

    /*
     * CPU bugs mitigations mechanisms can call other functions. They
     * should be invoked after making sure TF is cleared because
     * single-step is ignored only for instructions inside the
     * entry_SYSENTER_compat function.
     */
    IBRS_ENTER
    UNTRAIN_RET
    CLEAR_BRANCH_HISTORY

    movq    %rsp, %rdi              // 第一个参数：struct pt_regs *regs
    call    do_SYSENTER_32          // 调用 C 函数
    jmp     sysret32_from_system_call  // 返回路径

.Lsysenter_fix_flags:
    pushq   $X86_EFLAGS_FIXED
    popfq
    jmp     .Lsysenter_flags_fixed
SYM_INNER_LABEL(__end_entry_SYSENTER_compat, SYM_L_GLOBAL)
SYM_CODE_END(entry_SYSENTER_compat)
```

**vDSO 的 `__kernel_vsyscall` 包装函数**：

```asm
// vDSO 中的 32 位系统调用包装（简化示例）
__kernel_vsyscall:
    push    %ecx                    // 保存 ECX（SYSENTER 会破坏）
    push    %edx                    // 保存 EDX（SYSENTER 会破坏）
    push    %ebp                    // 保存 EBP
    mov     %esp, %ebp              // 保存栈指针到 EBP（供内核恢复）
    sysenter                        // 进入内核 → entry_SYSENTER_compat
    // 内核通过 SYSEXIT 返回到这里
    pop     %ebp
    pop     %edx
    pop     %ecx
    ret
```

### 4.3 entry_SYSCALL_compat 详解

**32 位兼容模式 SYSCALL**（AMD64）：

```asm
// arch/x86/entry/entry_64_compat.S:136-220（简化）
/*
 * 32-bit SYSCALL entry.
 *
 * 32-bit system calls through the vDSO's __kernel_vsyscall enter here
 * on 64-bit kernels running on AMD CPUs.
 *
 * The SYSCALL instruction, in principle, should *only* occur in the
 * vDSO.  In practice, it appears that this really is the case.
 */
SYM_CODE_START(entry_SYSCALL_compat)
    UNWIND_HINT_ENTRY
    ENDBR

    swapgs
    movq    %rsp, PER_CPU_VAR(cpu_tss_rw + TSS_sp2)
    SWITCH_TO_KERNEL_CR3 scratch_reg=%rsp
    movq    PER_CPU_VAR(cpu_current_top_of_stack), %rsp

SYM_INNER_LABEL(entry_SYSCALL_compat_safe_stack, SYM_L_GLOBAL)
    /* Construct struct pt_regs on stack */
    pushq   $__USER32_DS            // 注意：使用 __USER32_DS
    pushq   PER_CPU_VAR(cpu_tss_rw + TSS_sp2)
    pushq   %r11                    // SYSCALL 保存的 EFLAGS
    pushq   $__USER32_CS            // 注意：使用 __USER32_CS
    pushq   %rcx                    // SYSCALL 保存的返回地址

    pushq   %rax                    // pt_regs->orig_ax
    PUSH_AND_CLEAR_REGS rax=$-ENOSYS

    movq    %rsp, %rdi              // 第一个参数：struct pt_regs *regs
    call    do_fast_syscall_32      // 调用 C 函数
    jmp     sysret32_from_system_call  // 返回路径
SYM_CODE_END(entry_SYSCALL_compat)
```

### 4.4 32 位系统调用表

**32 位程序使用独立的系统调用表**：

```c
// arch/x86/entry/syscall_32.c（简化）
__visible const sys_call_ptr_t ia32_sys_call_table[] = {
    [0] = __ia32_sys_restart_syscall,  // 32 位系统调用 0
    [1] = __ia32_sys_exit,             // 32 位系统调用 1
    [2] = __ia32_sys_fork,
    [3] = __ia32_sys_read,
    [4] = __ia32_sys_write,
    // ... 400+ 系统调用
};
```

**32 位与 64 位系统调用号的差异**：

```
示例：exit 系统调用
┌───────────────────────────────────────────────────┐
│ 64 位：sys_call_table[60] = __x64_sys_exit        │
│ 32 位：ia32_sys_call_table[1] = __ia32_sys_exit   │
└───────────────────────────────────────────────────┘
```

### 4.5 32 位参数转换

**32 位程序传递参数**（寄存器映射）：

| 参数 | INT 0x80 | SYSENTER | SYSCALL（32位） |
|------|----------|----------|-----------------|
| 系统调用号 | EAX | EAX | EAX |
| 参数 1 | EBX | EBX | EBX |
| 参数 2 | ECX | ECX | ECX |
| 参数 3 | EDX | EDX | EDX |
| 参数 4 | ESI | ESI | ESI |
| 参数 5 | EDI | EDI | EDI |
| 参数 6 | EBP | EBP | EBP |

**内核如何处理 32 位参数**：

```c
// 32 位系统调用包装器（简化示例）
__ia32_sys_read(struct pt_regs *regs)
{
    // 从 32 位寄存器读取参数（零扩展到 64 位）
    unsigned int fd = regs->bx & 0xFFFFFFFF;      // EBX
    char __user *buf = (void *)(regs->cx & 0xFFFFFFFF);  // ECX
    size_t count = regs->dx & 0xFFFFFFFF;         // EDX

    // 调用内核实现
    return ksys_read(fd, buf, count);
}
```

### 4.6 32 位系统调用选择逻辑总结

```
用户态 32 位程序的系统调用路径选择：

┌────────────────────────────────────────────────────────────┐
│ glibc/musl 检测 CPU 特性和内核版本                          │
└────────────────────────────────────────────────────────────┘
                │
                ├─ Intel CPU + SYSENTER 支持
                │   → 使用 vDSO.__kernel_vsyscall → sysenter
                │       → entry_SYSENTER_compat → do_SYSENTER_32
                │
                ├─ AMD CPU + SYSCALL 支持
                │   → 使用 vDSO.__kernel_vsyscall → syscall（32位模式）
                │       → entry_SYSCALL_compat → do_fast_syscall_32
                │
                └─ 旧 CPU 或兼容模式
                    → int $0x80
                        → asm_int80_emulation → do_int80_syscall_32
```

## 5. 总结与关键要点

### 5.1 系统调用机制演进时间线

```
系统调用机制演进：
┌──────────────────────────────────────────────────────────────┐
│ 1. INT 0x80（1991，Linux 0.01）                              │
│    - 唯一机制，所有架构通用                                   │
│    - 性能：100-300 CPU 周期                                   │
│                                                              │
│ 2. SYSENTER/SYSEXIT（1997，Intel Pentium II）               │
│    - 32 位快速系统调用                                        │
│    - 性能：60-80 CPU 周期                                     │
│    - 需要 vDSO 包装                                           │
│                                                              │
│ 3. SYSCALL/SYSRET（2003，AMD64）                            │
│    - 64 位快速系统调用                                        │
│    - 性能：60-80 CPU 周期                                     │
│    - 自动保存返回地址和 RFLAGS                                │
│                                                              │
│ 4. FRED（2023+，Intel）                                     │
│    - 新一代中断/异常/系统调用机制                             │
│    - 统一处理路径，更高性能                                   │
└──────────────────────────────────────────────────────────────┘
```

### 5.2 关键初始化时间点

```
start_kernel() 启动流程中的系统调用初始化：

1. trap_init()
   ├─ idt_setup_traps()
   │   ├─ 设置 CPU 异常处理（#PF, #GP, #DE 等）
   │   └─ 设置 INT 0x80（idt_table[0x80] = asm_int80_emulation）✨
   │
   └─ cpu_init() → syscall_init() → idt_syscall_init()
       ├─ MSR_LSTAR = entry_SYSCALL_64         ✨ 64位 SYSCALL
       ├─ MSR_CSTAR = entry_SYSCALL_compat     ✨ 32位 SYSCALL
       └─ MSR_IA32_SYSENTER_EIP = entry_SYSENTER_compat  ✨ SYSENTER

2. init_IRQ() → native_init_IRQ() → idt_setup_apic_and_irq_gates()
   └─ 设置硬件中断门（IRQ 32-255）✨

【此时所有系统调用机制已就绪】
```

### 5.3 三种机制对比总结

| 特性 | INT 0x80 | SYSCALL | SYSENTER |
|------|----------|---------|----------|
| **设置方式** | IDT 表条目 | MSR 寄存器 | MSR 寄存器 |
| **依赖** | 依赖 IDT 完善 | 不依赖 IDT | 不依赖 IDT |
| **保存返回地址** | 自动（栈） | 自动（RCX） | 不保存 |
| **保存 RFLAGS** | 自动（栈） | 自动（R11） | 不保存 |
| **切换栈** | 自动（TSS） | 手动（软件） | 手动（软件） |
| **性能开销** | 100-300 周期 | 60-80 周期 | 60-80 周期 |
| **主要用途** | 32位兼容 | 64位主流 | 32位快速路径 |
| **vDSO 需求** | 不需要 | 不需要 | 必须（包装返回地址） |

### 5.4 关键源码文件索引

| 文件 | 作用 |
|------|------|
| **arch/x86/entry/entry_64.S** | entry_SYSCALL_64（64位系统调用入口） |
| **arch/x86/entry/entry_64_compat.S** | entry_SYSENTER_compat, entry_SYSCALL_compat（32位兼容入口） |
| **arch/x86/entry/syscall_64.c** | do_syscall_64, sys_call_table |
| **arch/x86/entry/syscall_32.c** | ia32_sys_call_table（32位系统调用表） |
| **arch/x86/kernel/cpu/common.c** | syscall_init(), idt_syscall_init()（MSR 配置） |
| **arch/x86/kernel/idt.c** | idt_setup_traps(), idt_setup_apic_and_irq_gates() |
| **arch/x86/kernel/irqinit.c** | init_IRQ(), native_init_IRQ() |
| **arch/x86/kernel/traps.c** | trap_init() |

---

**相关文档**：
- [x86 中断、异常、陷阱：Intel SDM 规范与 Linux 实现](X86_INTERRUPT_EXCEPTION_TRAP.md) - 基础概念（INT 0x80 为何在 CPU 层面是 Exception、Interrupt/Exception/Trap 区别）
- [Linux 内核启动与初始化](LINUX_KERNEL_INIT.md) - 主启动流程
- [IDT 表的演进流程详解](LINUX_KERNEL_IDT_EVOLUTION.md) - IDT 初始化的 5 个演进阶段
- [BIOS IVT vs Kernel IDT](BIOS_IVT_VS_KERNEL_IDT.md) - 实模式 IVT 与保护模式 IDT 对比
