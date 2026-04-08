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
| `__KERNEL_CS` / `__USER32_CS` 数值、RPL/DPL、与 `MSR_STAR` | [LINUX_X86_KERNEL_CS_AND_USER32_CS.md](LINUX_X86_KERNEL_CS_AND_USER32_CS.md) |

---

## 1. MSR 与 `RDMSR` / `WRMSR`

- **MSR**：x86 上由 **ECX（MSR 索引）** 寻址的 **模型相关 / 架构约定** 寄存器集合；具体实现与支持集合因 CPU 而异。系统软件常用 **`RDMSR`/`WRMSR`**（通常为 **CPL=0**）配置。
- **Linux 侧**：索引宏集中在 **`arch/x86/include/asm/msr-index.h`**；封装函数如 **`native_read_msr`** / **`native_write_msr`**、**`wrmsr`** / **`wrmsrq`**（见 **`arch/x86/include/asm/msr.h`** 等）。
- **Intel SDM**：各 MSR 的**位域、读写属性、复位值**以 **Vol. 4** *Model-Specific Registers* 为准；**SYSCALL/SYSRET 语义**以 **Vol. 3A §5.8.8** 为主，**Vol. 2** 为单指令级异常条件。

### 1.1 Linux 中 `rdmsr/wrmsr` 的具体实现分层（基于 `/Users/weli/works/linux`）

下面按源码分层给出从“裸指令”到“常用宏”的路径，便于和你其它文档里的调用链对齐。

#### A) 最底层 primitive：`__rdmsr()` / `__wrmsrq()`

文件：`arch/x86/include/asm/msr.h`

- `__rdmsr(u32 msr)`：内联 `rdmsr`，输入 `ecx=msr`，输出 `edx:eax` 组装为 `u64` 返回。
- `__wrmsrq(u32 msr, u64 val)`：内联 `wrmsr`，输入 `ecx=msr`、`eax=low32`、`edx=high32`。
- 两者都挂了 `_ASM_EXTABLE_TYPE(...)`，异常表类型分别是 `EX_TYPE_RDMSR` / `EX_TYPE_WRMSR`，用于故障时的内核异常修复路径。

#### B) native 包装：`native_read_msr*` / `native_write_msr*`

同文件：

- `native_read_msr()` / `native_write_msr()`：在 primitive 基础上加 tracepoint 钩子（`read_msr` / `write_msr`）。
- `native_read_msr_safe()` / `native_write_msr_safe()`：使用 `_ASM_EXTABLE_TYPE_REG(..., EX_TYPE_*_SAFE, err)`，返回错误码而非直接异常终止。
- 对应的常用宏：
  - `rdmsr(msr, low, high)`、`rdmsrq(msr, val)`
  - `wrmsr(msr, low, high)`、`wrmsrq(msr, val)`
  - `rdmsr_safe(...)`、`rdmsrq_safe(...)`、`wrmsrq_safe(...)`

#### C) paravirt 路径：同名宏可重定向到 `pv_ops`

文件：`arch/x86/include/asm/paravirt.h`

- 在 `CONFIG_PARAVIRT_XXL` 下，`rdmsr/wrmsr/rdmsrq/wrmsrq` 宏会走：
  - `paravirt_read_msr()` / `paravirt_write_msr()`
  - 底层是 `PVOP_CALL/PVOP_VCALL(..., pv_ops.cpu.read_msr / write_msr, ...)`
- 即：调用点看起来一样，但后端可由 hypervisor 接管。

#### D) 早期/共享最简版本：`raw_rdmsr()` / `raw_wrmsr()`

文件：`arch/x86/include/asm/shared/msr.h`

- 直接内联 `rdmsr/wrmsr`，不依赖 tracepoint 与完整异常处理基础设施。
- 注释明确这是给 boot/共享场景的最简访问器，和内核正式 `rdmsr()/wrmsr()` 分工不同。

#### E) 一句话记忆（调用链）

非 paravirt 常见路径：

`wrmsrq()` → `native_write_msr()` → `native_wrmsrq()` → `__wrmsrq()` → `asm("wrmsr")`

`rdmsrq()` → `native_read_msr()` → `__rdmsr()` → `asm("rdmsr")`

safe 版本分别落到 `native_*_msr_safe()` 并返回 `err`。

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

### 4.1 `syscall_init()` 在何时执行

- **Boot / 每个上线的逻辑 CPU**：**`cpu_init()`**（**`arch/x86/kernel/cpu/common.c`**）在 **64 位**分支末尾调用 **`syscall_init()`**；从处理器调用 **`start_secondary()`** 等路径进入 AP 时也会走到 **`cpu_init()` → `syscall_init()`**（见 **`arch/x86/kernel/smpboot.c`** 对 **`cpu_init()`** 的调用）。
- **休眠唤醒、恢复处理器的上下文**：**`fix_processor_context()`**（**`arch/x86/power/cpu.c`**）在重装 TSS/GDT 相关项后再次调用 **`syscall_init()`**，注释说明用于恢复 **MSR_*STAR** 等（与休眠前可能丢失的 MSR 状态一致）。

### 4.2 `IA32_FMASK`（`MSR_SYSCALL_MASK`）的含义与 Linux 写入值

**命名**：手册名 **IA32_FMASK**，Linux **`arch/x86/include/asm/msr-index.h`** 中为 **`MSR_SYSCALL_MASK`**（地址 **0xC0000084**）。**不要**与 **`IA32_SYSENTER_CS`（0x174）** 混淆——后者属于 **`sysenter`** 路径，与 **`syscall`** 的 FMASK **无关**。

**硬件语义**（**Vol. 3A §5.8.8**）：执行 **`syscall`** 时，**`RFLAGS ← RFLAGS & ~IA32_FMASK`**，即 **FMASK 中为 1 的位在进入内核时被清除**；原 **`RFLAGS`** 已由硬件存入 **`R11`**，返回用户态时 **`sysret`** 可用 **`R11`** 恢复用户标志（见 **§3**）。

**Linux `idt_syscall_init()` 中写入的掩码**（与上一节源码一致）：清除 **CF、PF、AF、ZF、SF、TF、DF、IF、OF、IOPL、NT、RF、AC、ID**。内核注释意图是 **尽量多清**，减轻用户态 **RFLAGS** 对内核路径的干扰。

**手册依据**（你本地的 *Intel® 64 and IA-32 Architectures Software Developer’s Manual, Volume 3A: System Programming Guide, Part 1*，Order Number **253668**，例如 **September 2016** 版）：

- **§2.3** *System Flags and Fields in the EFLAGS Register*：**TF、IF、IOPL、NT、RF、AC、VIF、VIP、ID** 等系统类位的定义与 **Figure 2-5** 位图。
- **§2.3.1** *System Flags and Fields in IA-32e Mode*：长模式下 **RFLAGS** 高 32 位保留；并写明 **SYSCALL/SYSRET** 可用可编程方式指定 **RFLAGS/EFLAGS** 中哪些位被清除/保存恢复（与 **IA32_FMASK** 协议一致）。

**算术/方向类状态位**（**CF、PF、AF、ZF、SF、DF、OF**）：在 **Figure 2-5** 中与系统位同图展示位序；逐位语义以 **Vol. 1**（Basic Architecture）*EFLAGS/RFLAGS* 及 **Vol. 2** 各指令对标志位的影响说明为准（Vol. 3A §2.3 侧重系统控制类位的文字定义）。

下表将 **FMASK 置 1 从而经 `RFLAGS & ~FMASK` 被清除** 的位，与 **Vol. 3A §2.3** 的表述对齐（摘意，翻译以手册原文为准），并保留一句 **Linux 侧**常见动机。

| 位 / 域 | Vol. 3A §2.3 含义（摘意） | Linux 侧（FMASK）的典型动机（句级） |
|--------|---------------------------|-------------------------------------|
| **CF, PF, AF, ZF, SF, OF** | 算术与逻辑指令产生的**状态标志**（与 Figure 2-5 低位区对应；细节见 Vol. 1 / Vol. 2）。 | 进入 `syscall` 时不携带用户态上次运算残留的标志，减少内核里对**未定义“用户标志依赖”**的假设冲突。 |
| **DF**（bit 10） | **方向标志**：与字符串等指令的变址方向相关（Figure 2-5 中与 OF、IF 相邻；修改见 Vol. 2 `CLD`/`STD` 等）。 | 清 **DF** 等价于约定内核路径以**递增方向**为主，与常见 **`cld`** 惯例一致，避免用户 **`std`** 遗留在内核。 |
| **TF**（bit 8） | **Trap**：置位则启用单步调试，处理器在**每条指令后**可能产生 debug 异常（§2.3 原文 *single-step mode*）。 | 避免用户单步状态直接延续到内核入口，带来意外的 **#DB** 行为链。 |
| **IF**（bit 9） | **Interrupt enable**：置位则响应**可屏蔽硬件中断**；**不**影响异常与 **NMI**（§2.3；并见 Vol. 3A 对 maskable interrupt 的章节交叉引用）。 | 与 **`syscall` 入口常关中断**的设计配合，由内核在明确位置再 `sti` / 恢复（见 `entry_SYSCALL_64` 相关注释与出口路径）。 |
| **IOPL**（bits 12–13） | **I/O 特权级**：当前任务/程序的 I/O 权限级别；**CPL ≤ IOPL** 才可视情况访问 **I/O 地址空间**；**POPF/IRET** 仅在 **CPL=0** 时允许改此域（§2.3）。 | 清零后相当于 **IOPL=0**，避免用户曾抬高的 **IOPL** 在内核继续生效，影响 **I/O** 与 **IF** 修改许可等语义。 |
| **NT**（bit 14） | **Nested task**：用于被中断/调用链起来的任务链接；**IRET** 会检查此位（§2.3）。 | 清除嵌套任务语义，避免 **`syscall` 进内核**时夹着「任务链」状态引发异常路径（IA-32e 下 **IRET** 对 **NT** 还有额外约束，见 §2.3.1）。 |
| **RF**（bit 16） | **Resume**：置位时**抑制**由**指令断点**导致的 **#DB**；用于调试后单步恢复（§2.3）。 | 避免用户或调试器留下的 **RF** 干扰内核入口调试/断点行为。 |
| **AC**（bit 18） | **Alignment check / access control**：与 **CR0.AM**、用户态对齐检查及 **CR4.SMAP** 下显式 supervisor 访问用户页的规则相关（§2.3）。 | 清除用户随带的对齐/SMAP 相关影响，内核自用 **AC** 时再按需要设置。 |
| **ID**（bit 21） | **Identification**：能否置位/清除表示是否支持 **CPUID**（§2.3）。 | 与「清外部带入状态」同一策略下一并清零；**CPUID 能力**由 CPU 本身决定，不依赖此位“粘”在用户给定状态上。 |

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
| **Vol.3A Section 2.3** | ~2-9 ~ 2-10 | *System Flags and Fields in the EFLAGS Register*；**Figure 2-5** |
| **Vol.3A Section 2.3.1** | ~2-11 | *IA-32e Mode* 下 RFLAGS、SYSCALL/SYSRET 对标志的可编程处理 |
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

**文档版本**：1.3  
**最后更新**：2026-04-08  
**核对内核树**：`/Users/weli/works/linux`
