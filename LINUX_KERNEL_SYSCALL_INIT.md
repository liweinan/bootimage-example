# Linux 内核系统调用初始化详解

> **本文档为** [Linux 内核启动与初始化](LINUX_KERNEL_INIT.md) **的子文档**

本文档详细介绍 Linux 内核启动过程中系统调用机制的初始化，包括 trap_init()、syscall_init() 的实现细节，以及 INT 0x80 和 SYSCALL/SYSENTER 两种系统调用机制的对比。

**主要内容**：
1. trap_init() 调用流程与系统调用初始化
2. syscall_init() 与 MSR 寄存器配置
3. INT 0x80 vs SYSCALL/SYSENTER 详细对比
4. 32位兼容机制与 entry_SYSCALL_64 入口

**相关文档**：
- [Linux 内核启动与初始化](LINUX_KERNEL_INIT.md) - 主启动流程
- [IDT 表的演进流程详解](LINUX_KERNEL_IDT_EVOLUTION.md) - 两个 IDT 表（bringup_idt_table、idt_table）、5 个演进阶段、GDT/IDT 对比、IST 机制、中断状态管理
- [Linux 中断处理](LINUX_INTERRUPT_HANDLING.md) - 运行时中断处理
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
| **设置时机** | `init_IRQ()` → `idt_setup_ia32_syscall_gate()`（IDT 演进阶段 5） |
| **设置位置** | `arch/x86/kernel/idt.c` |
| **触发方式** | `int $0x80` 指令 |
| **入口函数** | `entry_INT80_32`（`arch/x86/entry/entry_32.S` 或 `entry_64.S`） |
| **系统调用号** | %eax |
| **参数传递** | %ebx, %ecx, %edx, %esi, %edi, %ebp（32位寄存器） |
| **系统调用表** | `ia32_sys_call_table`（兼容表） |
| **性能** | 慢（需要查 IDT、特权级切换、栈切换） |
| **适用范围** | 32位程序（CONFIG_IA32_EMULATION），64位程序也可用但不推荐 |

**设置代码**（在 `init_IRQ()` 之后）：
```c
// arch/x86/kernel/idt.c
#ifdef CONFIG_IA32_EMULATION
static inline void idt_setup_ia32_syscall_gate(void) {
    idt_setup_from_table(idt_table, &ia32_syscall, 1, true);
    // ia32_syscall = {.vector = IA32_SYSCALL_VECTOR (0x80), .addr = entry_INT80_32}
}
#endif
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
    ├─ 阶段 2a: trap_init()  ← 第一阶段
    │       └─ cpu_init()
    │           └─ syscall_init()
    │               └─ idt_syscall_init()
    │                   ├─ wrmsr(MSR_STAR) → 设置段选择子
    │                   ├─ wrmsr(MSR_LSTAR, entry_SYSCALL_64) ✨ 64位 syscall 就绪
    │                   ├─ wrmsr(MSR_CSTAR, entry_SYSCALL_compat) → 32位 syscall
    │                   ├─ wrmsr(MSR_IA32_SYSENTER_EIP, entry_SYSENTER_compat) ✨ sysenter 就绪
    │                   └─ wrmsr(MSR_SYSCALL_MASK) → RFLAGS 掩码
    │       【此时 SYSCALL/SYSENTER 机制已可用，但 INT 0x80 尚未就绪】
    │
    ├─ 阶段 2b: early_irq_init()
    │
    ├─ 阶段 2c: init_IRQ()  ← 第二阶段
    │       ├─ idt_setup_traps() → 补全异常向量
    │       ├─ init_8259A() → 重编程 PIC
    │       ├─ idt_setup_apic_and_irq_gates() → 设置 APIC/IRQ 门
    │       └─ idt_setup_ia32_syscall_gate()
    │           └─ idt_table[0x80] = entry_INT80_32 ✨ INT 0x80 就绪
    │       【此时 INT 0x80 机制也可用，所有系统调用机制完全就绪】
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

3. **设置时机不同**：
   - **MSR 机制（SYSCALL/SYSENTER）**：在 `trap_init()` 中设置，**早于** IDT 的完善
   - **IDT 机制（INT 0x80）**：在 `init_IRQ()` 中设置，作为 IDT 表的一部分
   - 原因：MSR 写入简单（几条 wrmsr），IDT 需要完整的中断框架就绪

4. **是否依赖 IDT**：
   - `SYSCALL/SYSENTER`：**不依赖 IDT**，直接从 MSR 跳转
   - `INT 0x80`：**依赖 IDT**，必须等 IDT 表完善后才能使用

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
    sysenter → entry_SYSENTER_compat → do_SYSENTER_32 → ia32_sys_call_table[eax]

32位程序（所有 CPU，兼容路径）：
    int $0x80 → entry_INT80_32 → do_int80_syscall_32 → ia32_sys_call_table[eax]
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

**关键洞察**：
- **trap_init() 阶段**：设置 MSR，让 SYSCALL/SYSENTER 可用（不依赖 IDT）
- **init_IRQ() 阶段**：设置 IDT[0x80]，让 INT 0x80 可用（依赖 IDT 完善）
- 两者相互独立，但共同完成系统调用机制的初始化
- 现代程序主要使用 SYSCALL，INT 0x80 主要用于兼容

**与 IDT 内容的关系**：
- **IDT 表包含三类条目**：
  1. **CPU 异常**（0-31）：#DE, #PF, #GP 等 → idt_setup_early_handler() → idt_setup_traps()
  2. **硬件中断**（32+）：时钟、键盘、网卡等 IRQ → idt_setup_apic_and_irq_gates()
  3. **软件中断**（特定向量）：INT 0x80（32位系统调用兼容）→ idt_setup_ia32_syscall_gate()

- **SYSCALL/SYSENTER 不在 IDT 中**，它们通过 MSR 寄存器配置：
  - MSR_LSTAR：SYSCALL 入口地址（entry_SYSCALL_64）
  - MSR_STAR：段选择子（内核态 CS / 用户态 CS）
  - MSR_SYSCALL_MASK：RFLAGS 掩码（syscall 时清除的标志位）

## 2. init_IRQ() 与 INT 0x80 设置
