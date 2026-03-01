# Ring 0 特权指令与用户态进入内核时的段切换

本文档说明两件事：(1) 用户态程序执行 syscall 时如何“切回”内核 CS（为何不违反“仅 Ring 0 能切换段”）；(2) 根据 Intel SDM Vol 3A 与 Vol 2 整理**需要 CPL=0（Ring 0）才能执行的 CPU 指令**及在 PDF 中的查阅方式。

---

## 1. 用户态如何“切回” kernel CS？——Ring 3 → Ring 0 是 CPU 自动完成的

**“只有 Ring 0 才能切换段”** 指的是：在用户态不能执行 LGDT、LTR、或随意用远跳/远调用把 CS 加载成内核段等**特权指令**，否则会 #GP。

但 **syscall、int 0x80、异常（exception）、中断（interrupt）** 导致的段与特权级切换**不是用户或内核在“切换瞬间”执行加载 CS 的指令**，而是 **CPU 在响应这些事件时，按内核事先配好的 MSR 或 IDT 自动加载新 CS、切换 CPL 与栈**。内核只负责**事先配置**（MSR/IDT）和**切换完成后的入口逻辑**（保存现场、分发等），**不需要在切换瞬间做任何“手工”操作**。

### 1.1 哪些事件会触发自动切换？

| 触发方式 | CPU 行为（自动） | 内核事先配置 |
|----------|------------------|--------------|
| **SYSCALL** | 从 **MSR**（如 IA32_STAR）取内核 CS/SS，加载 CS，CPL→0；入口来自 IA32_LSTAR 等 | WRMSR 写 MSR |
| **INT 0x80** | 查 **IDT** 向量 0x80，从门取段选择子，加载 CS，CPL→0；若 CPL 改变则从 TSS.RSP0 取内核栈 | 填写 IDT 门 |
| **异常（exception）** | 查 **IDT** 对应向量，从门取段选择子，加载 CS；若 CPL 改变则从 TSS.RSP0 或 IST 取栈，CPL→0；并压栈保存现场 | 填写 IDT 门（含 IST 等） |
| **硬件中断（interrupt）** | 与异常相同：查 IDT、从门加载 CS、必要时 TSS 换栈、CPL→0、压中断帧 | 填写 IDT 门 |

因此：**发生 exception 时也一样**——若异常在用户态（CPL=3）发生，CPU 会查 IDT、按门描述符自动加载内核 CS、用 TSS.RSP0 或 IST 换栈，CPL 变为 0，全程由 CPU 硬件完成，无需内核在“切换瞬间”做额外操作。

### 1.2 小结

- **谁执行切换**：**CPU 自动**（在响应 syscall / int / exception / interrupt 时）。
- **谁决定目标**：**内核（Ring 0）事先**通过 MSR 或 IDT 配置好入口与段。
- **谁在切换后干活**：**内核入口代码**（保存到 pt_regs、分发、返回等）。

---

## 2. 需要 Ring 0（CPL=0）的指令：依据的 SDM 位置

### 2.1 Vol 3A（64-ia-32-architectures-software-developer-vol-3a-part-1-manual.pdf）

- **2.8 System Instruction Summary**（约 2-20 页起）
- **2.8.1 Loading and Storing System Registers**：GDTR/IDTR/LDTR/TR 的 load/store
- **2.5 Control Registers**：MOV CRn 仅允许在 **privilege level 0** 读/写
- **Table 2-3. Summary of System Instructions**：列出各系统指令是否 “Protected from Application”（即是否需 CPL 0）
- **2.8.3–2.8.5**：调试寄存器、Cache/TLB、处理器控制等

### 2.2 Vol 2（325383-090-sdm-vol-2abcd.pdf）

每条指令的 **Description / Operation / Exceptions** 中会写明：若 CPL ≠ 0 则 **#GP(0)** 等。权限信息在每条指令的 **Protected Mode Exceptions** 和 **64-Bit Mode Exceptions** 小节（Vol 2 Chapter 3 的 3.1.1.13、3.1.1.19 说明这些小节）。

---

## 3. 需要 Ring 0（CPL=0）的指令分类

### 3.1 加载/存储系统表寄存器（Vol 3A 2.8.1）

| 指令 | 作用 | 说明 |
|------|------|------|
| **LGDT** | Load GDTR | CPL≠0 → #GP(0)。仅 CPL=0 可加载 GDT 基址和界限。 |
| **LIDT** | Load IDTR | CPL≠0 → #GP(0)。仅 CPL=0 可加载 IDT。 |
| **LLDT** | Load LDTR | CPL≠0 → #GP(0)。加载 LDT 选择子及描述符。 |
| **LTR** | Load Task Register | CPL≠0 → #GP(0)。加载 TSS 选择子及描述符。 |

**Store 类（SGDT/SIDT/SLDT/STR）**：不修改系统表，默认在任意 CPL 可执行。若 **CR4.UMIP=1**（User-Mode Instruction Prevention），则 SGDT、SIDT、SLDT、SMSW、STR 在 CPL>0 时会产生 #GP。

### 3.2 控制寄存器（Vol 3A 2.5）

- **MOV** 读写 **CR0、CR1、CR2、CR3、CR4、CR8**：在保护模式下仅允许在 **privilege level 0** 读/写；否则 #GP。
- **LMSW**（Load Machine Status Word）：写 CR0 低 16 位，需 CPL=0。
- **CLTS**（Clear TS flag in CR0）：清除 CR0.TS，需 CPL=0。

### 3.3 调试寄存器（Vol 3A 2.8.3）

- **MOV** 读写 **DR0–DR7**：需 CPL=0（否则 #GP）。

### 3.4 MSR（Vol 3A 2.8.7）

- **WRMSR**：写 MSR，需 CPL=0（否则 #GP）。
- **RDMSR**：读 MSR；是否允许 CPL 3 由 CR4 等控制（如 TSD、PCE），并非一律 CPL 0。
- **XSETBV**：写 XCR0（扩展状态控制），需 CPL=0。

### 3.5 Cache / TLB（Vol 3A 2.8.4）

| 指令 | 作用 | 说明 |
|------|------|------|
| **INVD** | Invalidate caches, no writeback | CPL≠0 → #GP(0)。 |
| **WBINVD** | Invalidate caches with writeback | CPL≠0 → #GP(0)。 |
| **INVLPG** | Invalidate TLB entry | CPL≠0 → #GP(0)。 |

### 3.6 处理器控制等（Vol 3A 2.8.5）

- **HLT**（Halt）：在 CPL>0 执行会 #GP(0)。
- **RSM**（Return from SMM）：从 SMM 返回，需 CPL=0。

### 3.7 段/门与“敏感”操作

- 使用 **CALL FAR / JMP FAR** 通过**调用门**或**任务门**切换到更高特权级（或加载非一致代码段到 CS）时，会做 DPL/CPL 检查；若违反则 #GP。
- 加载 **CS/SS** 时，若选择子指向的段 DPL 与 CPL 不满足访问规则，会 #GP；只有 CPL=0 才能加载 DPL=0 的代码段（即“切换段”到内核代码段只能由内核或 CPU 在门/异常/syscall 路径上完成）。

---

## 4. 简要列表（需 CPL=0 的指令）

- **表寄存器加载**：LGDT、LIDT、LLDT、LTR
- **控制寄存器**：MOV CRn、LMSW、CLTS
- **调试寄存器**：MOV DRn
- **MSR/扩展状态**：WRMSR、XSETBV
- **Cache/TLB**：INVD、WBINVD、INVLPG
- **其它**：HLT、RSM

（SGDT/SIDT/SLDT/STR/SMSW 在 **CR4.UMIP=1** 时在 CPL>0 下也会 #GP。）

---

## 5. 在 PDF 中如何查阅

- **Vol 3A**：看 **Chapter 2 → 2.8 System Instruction Summary** 和 **Table 2-3**，以及 **2.5 Control Registers**、**2.8.1–2.8.5** 各小节。
- **Vol 2**：用目录或搜索 LGDT、LIDT、LTR、MOV（CR/DR）、WRMSR、INVD、WBINVD、INVLPG、HLT、RSM 等，在**每条指令**的 **Exceptions** 下查 **Protected Mode Exceptions** 和 **64-Bit Mode Exceptions** 中的 “#GP(0)” 或 “If the current privilege level is not 0”。

理论框架和“是否受应用保护”在 Vol 3A 2.8 与 Table 2-3；具体 #GP 条件在 Vol 2 每条指令的 Exceptions。

---

## 相关文档

- [X86_SYSCALL_VS_INT80_ENTRY_AND_PT_REGS.md](X86_SYSCALL_VS_INT80_ENTRY_AND_PT_REGS.md) — SYSCALL 与 INT 0x80 入口、TSS、pt_regs
- [X86_MEMORY_MANAGEMENT_THEORY.md](X86_MEMORY_MANAGEMENT_THEORY.md) — CPL、DPL、特权检查
- [X86_TSS_STACK_SWITCH_AND_DESIGN.md](X86_TSS_STACK_SWITCH_AND_DESIGN.md) — TSS、GDT、RSP0/sp2
