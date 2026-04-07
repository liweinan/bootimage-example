# Linux x86/x86_64：MSR 集中参考（架构 + 内核配置）

本文从 **Intel SDM** 与 **`/Users/weli/works/linux`** 主线内核出发，把 **Model-Specific Register（MSR）** 的**手册位置、地址、Linux 符号、以及在系统调用 / 长模式启动中的用法**集中在一处。其它文档涉及 MSR 时 **仅引用本文**，避免多处重复维护。

**相关专文（分工）**

| 主题 | 文档 |
|------|------|
| `trap_init`、`entry_SYSCALL_64` 完整叙事、INT 0x80 对比 | [LINUX_KERNEL_SYSCALL_INIT.md](LINUX_KERNEL_SYSCALL_INIT.md) |
| `pt_regs`、syscall 与 IDT 入口差异 | [LINUX_X86_64_ENTRY_AND_PT_REGS.md](LINUX_X86_64_ENTRY_AND_PT_REGS.md) |
| `cpu_current_top_of_stack`、TSS、`TSS_sp0` | [LINUX_X86_TASK_TOP_OF_STACK_AND_CPU_CURRENT_TOP.md](LINUX_X86_TASK_TOP_OF_STACK_AND_CPU_CURRENT_TOP.md)、[LINUX_X86_KERNEL_STACK_SYSCALL_TSS.md](LINUX_X86_KERNEL_STACK_SYSCALL_TSS.md) |
| 压缩内核阶段 `EFER.LME`、启动序 | [LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md) |
| Ring0 特权指令列表（含 `WRMSR`/`RDMSR` 一句） | [X86_RING0_PRIVILEGED_INSTRUCTIONS_AND_SYSCALL_CS.md](X86_RING0_PRIVILEGED_INSTRUCTIONS_AND_SYSCALL_CS.md) |

---

## 1. MSR 与 `RDMSR` / `WRMSR`

- **MSR**：x86 上由 **ECX（MSR 索引）** 寻址的 **模型相关 / 架构约定** 寄存器集合；具体实现与支持集合因 CPU 而异。系统软件常用 **`RDMSR`/`WRMSR`**（通常为 **CPL=0**）配置。
- **Linux 侧**：索引宏集中在 **`arch/x86/include/asm/msr-index.h`**；封装函数如 **`native_read_msr`** / **`native_write_msr`**、**`wrmsr`** / **`wrmsrq`**（见 **`arch/x86/include/asm/msr.h`** 等）。
- **Intel SDM**：各 MSR 的**位域、读写属性、复位值**以 **Vol. 4** *Model-Specific Registers* 为准；**SYSCALL/SYSRET 语义**以 **Vol. 3A §5.8.8** 为主，**Vol. 2** 为单指令级异常条件。

---

## 2. 与快速系统调用、长模式相关的 MSR 速查表

以下地址与 **Linux `msr-index.h`** 一致（以你检出的内核为准；少数平台别名可能略有差异）。

| Intel 常用名（手册） | 地址（hex） | Linux 宏（典型） | 在本文语境下的作用 |
|---------------------|------------|------------------|-------------------|
| IA32_EFER | C000_0080 | `MSR_EFER` | **SCE**：允许 SYSCALL/SYSRET；**LME/LMA** 等长模式相关位（见 §5） |
| IA32_STAR | C000_0081 | `MSR_STAR` | SYSCALL 后内核 **CS/SS 选择子**、SYSRET 后用户 **CS/SS** 的构造字段（Figure 5-14） |
| IA32_LSTAR | C000_0082 | `MSR_LSTAR` | **64 位长模式**下 `syscall` 的目标 **RIP** |
| IA32_CSTAR | C000_0083 | `MSR_CSTAR` | **兼容模式**下 `syscall` 的目标 **RIP**（Linux：`entry_SYSCALL_compat` 等） |
| IA32_FMASK | C000_0084 | `MSR_SYSCALL_MASK` | `syscall` 时对 **RFLAGS** 的掩码（置 1 的位在执行后被清除） |
| IA32_SYSENTER_CS | 174 | `MSR_IA32_SYSENTER_CS` | `sysenter` 路径段选择子基础 |
| IA32_SYSENTER_ESP | 175 | `MSR_IA32_SYSENTER_ESP` | `sysenter` 后 **RSP** |
| IA32_SYSENTER_EIP | 176 | `MSR_IA32_SYSENTER_EIP` | `sysenter` 后 **RIP** |
| IA32_FS_BASE / GS_BASE / KERNEL_GS_BASE | C000_0100–0102 | `MSR_FS_BASE` 等 | 与用户态 FS/GS、`SWAPGS` 阴影底座相关（ syscall 路径常配 `swapgs`） |

**FRED**（若 CPU/启用）：另有 **`MSR_IA32_FRED_*`** 一族（如 **`MSR_IA32_FRED_RSP0`**），与经典 **STAR/LSTAR** 路径并存或取代部分入口语义；详见 **`arch/x86/include/asm/msr-index.h`** 与 **`asm/fred.h`**。非 FRED 配置下 **`syscall_init`** 仍写 **STAR/LSTAR/FMASK**。

---

## 3. SYSCALL / SYSRET：硬件语义摘要（对照 SDM §5.8.8）

**_cpuid**：**CPUID.80000001H.EDX[11]=1** 表示实现 SYSCALL/SYSRET；仅在 **IA-32e 长模式**上下文中按手册含义有效。

**`syscall` 后（句级）**

- **RCX** ← 返回用户时的 **RIP**；** R11** ← **RFLAGS**。
- **RIP** ← **IA32_LSTAR**；** CS** ← **IA32_STAR[47:32]**；** SS** ← **IA32_STAR[47:32] + 8**（平坦长模式下段选择子与 GDT 布局配合）。
- **RFLAGS** ← **RFLAGS & ~IA32_FMASK**。

**`sysret`（64 位用户代码，REX.W）**（句级）

- **RIP** ← **RCX**；** RFLAGS** ← **R11**。
- 用户 **CS** ← **IA32_STAR[63:48]+16**；用户 **SS** ← **IA32_STAR[63:48]+8**（手册分区与 **Figure 5-14** 一致）。

**与 SYSENTER 的差异（手册强调）**：SYSCALL **不通过 MSR 约定 RSP**；RSP 由 **OS 入口汇编**与 **per-CPU `cpu_current_top_of_stack`** 等机制处理（见栈专文）。**IA32_FMASK** 决定清除哪些 **RFLAGS** 位。

**扩展阅读顺序**（防迷路）：**Vol. 3A §2（IA32_EFER）→ §5.8.7（对照 SYSENTER）→ §5.8.8 → Vol. 4 各 MSR 表 → Vol. 2 SYSCALL/SYSRET 指令页**。VMX 下客户机 SYSCALL 处置见 **Vol. 3A** 约 **§31.10.4.3**（仅 VMM 必读）。

---

## 4. Linux：`syscall_init()` / `idt_syscall_init()`（写入上述 MSR）

**调用链（`trap_init` 内）**

```
trap_init()
└── cpu_init()
    └── syscall_init()              arch/x86/kernel/cpu/common.c
        └── idt_syscall_init()      同文件（非 FRED 时）
            ├── wrmsr(MSR_STAR, …)
            ├── wrmsrq(MSR_LSTAR, entry_SYSCALL_64)
            ├── wrmsrq_cstar(…) / wrmsrq_safe(MSR_IA32_SYSENTER_* …)（视 ia32_enabled()）
            └── wrmsrq(MSR_SYSCALL_MASK, …)
```

**源码摘录**（以本机内核为准；行号会漂移）

```c
// arch/x86/kernel/cpu/common.c — syscall_init() 大意
void syscall_init(void)
{
	wrmsr(MSR_STAR, 0, (__USER32_CS << 16) | __KERNEL_CS);
	if (!cpu_feature_enabled(X86_FEATURE_FRED))
		idt_syscall_init();
}

// idt_syscall_init()：写 LSTAR / CSTAR / SYSENTER 三件套 / FMASK
static inline void idt_syscall_init(void)
{
	wrmsrq(MSR_LSTAR, (unsigned long)entry_SYSCALL_64);
	if (ia32_enabled()) {
		wrmsrq_cstar((unsigned long)entry_SYSCALL_compat);
		wrmsrq_safe(MSR_IA32_SYSENTER_CS, (u64)__KERNEL_CS);
		wrmsrq_safe(MSR_IA32_SYSENTER_ESP,
			    (unsigned long)(cpu_entry_stack(smp_processor_id()) + 1));
		wrmsrq_safe(MSR_IA32_SYSENTER_EIP, (u64)entry_SYSENTER_compat);
	} else {
		wrmsrq_cstar((unsigned long)entry_SYSCALL32_ignore);
		wrmsrq_safe(MSR_IA32_SYSENTER_CS, (u64)GDT_ENTRY_INVALID_SEG);
		wrmsrq_safe(MSR_IA32_SYSENTER_ESP, 0ULL);
		wrmsrq_safe(MSR_IA32_SYSENTER_EIP, 0ULL);
	}
	wrmsrq(MSR_SYSCALL_MASK,
	       X86_EFLAGS_CF|X86_EFLAGS_PF|X86_EFLAGS_AF|
	       X86_EFLAGS_ZF|X86_EFLAGS_SF|X86_EFLAGS_TF|
	       X86_EFLAGS_IF|X86_EFLAGS_DF|X86_EFLAGS_OF|
	       X86_EFLAGS_IOPL|X86_EFLAGS_NT|X86_EFLAGS_RF|
	       X86_EFLAGS_AC|X86_EFLAGS_ID);
}
```

**FRED**：`syscall_init` 内注释写明：除 **STAR** 外 **可不**配置经典 SYSCALL/SYSENTER MSR，由 **FRED ring3 入口与 ERETU** 等路径替代（实现以树内 **`#ifdef CONFIG_X86_FRED`** 为准）。

---

## 5. 启动路径上的 `MSR_EFER`（长模式使能）

在 **32 位保护模式→长模式** transition 中，内核会 **`rdmsr`/`wrmsr` `MSR_EFER`** 置 **LME** 等，再与 **CR0.PG** 等配合进入长模式。典型汇编片段与阶段说明见 **[LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md)**（如 **startup_32** 内 EFER 序列）；此处不重复贴全码。

**SCE（SYSCALL enable）**：通常在内核后续初始化中与其它 EFER 位一并配置；若 **SCE 未置位**，**`syscall` 将不**按长模式快速调用语义工作。

---

## 6. 读 §5.8.8 时可边读边答（自检）

1. **STAR** 的 **[47:32]** 与 **[63:48]** 分别服务 **SYSCALL 进内核** 与 **SYSRET 回用户** 的哪几段选择子？**+8 / +16** 各落在哪个段寄存器？
2. **没有 MSR 保存 RSP** 时，OS 至少要在大致哪两个时机之一保存/恢复用户 **RSP**？
3. 若希望进入内核时清 **IF**，**FMASK** 对应位应如何设？（结合 **RFLAGS & ~FMASK** 推导。）
4. **SYSRET** 前 **RCX** 须满足何种**线性地址/canonical** 约束，否则 **#GP(0)**？

---

## 7. Intel SDM 章节速查（系统调用 / MSR）

| 章节 | 页码（约，以你本地修订为准） | 主题 |
|------|------------------------------|------|
| **Vol.3A Section 5.8.7** | 5-20 ~ 5-21 | SYSENTER and SYSEXIT |
| **Vol.3A Section 5.8.7.1** | 5-21 | SYSENTER/SYSEXIT in IA-32e Mode |
| **Vol.3A Section 5.8.8** | 5-22 ~ 5-23 | Fast System Calls in 64-Bit Mode (SYSCALL/SYSRET) |
| **Vol.3A Figure 5-14** | 5-23 | MSRs Used by SYSCALL and SYSRET |
| **Vol.3A Chapter 6** | ~6-1 | Interrupt and Exception Handling（INT 0x80 归类等） |
| **Vol.4** | — | 各 **IA32_*** MSR **位域与访问属性** |

**Vol. 3A VMX §31.10.4.3**（客户机 SYSCALL/SYSRET）：仅 VMM 必读。

---

## 8. 文档说明

- **修订版 SDM** 会调整页码；引用他人时请带 **Order Number 与日期**。
- **`INTEL_SDM_SYSCALL_SYSRET_GUIDE.md`** 为指向本文的 **短入口**（旧书签仍可用）。

**文档版本**：1.0  
**最后更新**：2026-04-04  
**核对内核树**：`/Users/weli/works/linux`
