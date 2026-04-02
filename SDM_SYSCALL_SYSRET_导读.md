# Intel® SDM：SYSCALL / SYSRET 机制导读

本文是 **《Intel 64 and IA-32 Architectures Software Developer’s Manual》** 中与 **快速系统调用（SYSCALL / SYSRET）** 相关的 **阅读路线与要点索引**，便于在纸质目录或 PDF 书签里定位。  
行文中的 **章节号** 以常见卷次为准：**Vol. 3A = System Programming Guide, Part 1**（Order Number 253668 一类）；若你本地的修订版调整了页码，以 **章节标题** 为准。

---

## 1. 涉及哪些卷

| 卷 | 常见 Order / 名称 | 与 SYSCALL 的关系 |
|----|-------------------|-------------------|
| **Vol. 2** | 253666 / 326018 等，*Instruction Set Reference* | **单条指令**的合法操作数、模式、标志位受影响情况、异常条件（如 `#UD`）等 **操作级** 描述。 |
| **Vol. 3A** | 253668，*System Programming Guide, Part 1* | **保护模型 + 快速系统调用在 OS 视角下的语义**：段选择子如何从 MSR 推出、`RFLAGS` 掩码、栈职责、`SYSRET` 与 canonical RIP 等 **机制级** 描述；**§5.8.8** 为主体。 |
| **Vol. 3A**（后部） | 同卷，VMX 相关章 | 客户机执行 SYSCALL/SYSRET 时 VMM 侧 **MSR / 指令** 的处置思路（如 **§31.10.4.3** *Handling the SYSCALL and SYSRET Instructions*，目录约在 **31-16** 页一带）。 |
| **Vol. 4** | *Model-Specific Registers* | **IA32_EFER、IA32_STAR、IA32_LSTAR、IA32_FMASK** 的 **地址、域定义、访问权限**；与 Vol. 3A 正文交叉阅读。 |

仅关心「内核如何配置 MSR、用户态如何进 ring 0」，**Vol. 3A §5.8.8 + Vol. 4 MSR 表** 通常足够；要写仿真器或处理 `#GP` 细节，再补 **Vol. 2** 指令页。

---

## 2. 建议阅读顺序（机制线）

1. **Vol. 3A §2**（系统架构概览）  
   - **Figure 2-4 / Table 2-1：`IA32_EFER`**  
   - **位 0（文档中称 SYSCALL Enable / SCE）**：在 **64 位模式**下 **允许 SYSCALL/SYSRET**（手册表述为启用该指令对）。  
   - 同卷 **§2.3.1** *System Flags and Fields in IA-32e Mode*：说明协议下 **SYSCALL/SYSRET 对 RFLAGS/EFLAGS 的可编程清位方式**，并强调 **保存/恢复** 与该指令对的关系。

2. **Vol. 3A §5.8 总览**  
   - **§5.8.7** *Performing Fast Calls to System Procedures with SYSENTER and SYSEXIT*：**对照** SYSCALL 的另一套快速调用；手册将 SYSCALL/SYSRET 明确与 **IA-32e / 平坦模型** 场景放在一起讨论。  
   - **§5.8.8** *Fast System Calls in 64-Bit Mode*：**核心本节**——下面 §3 逐项对应。

3. **Vol. 3A §5.8.8 精读时的抓手**  
   - **支持性检测**：**CPUID.80000001H.EDX[11] = 1** 表示实现 SYSCALL/SYSRET；并注明 **不支持** 于 **兼容模式** 与 **保护模式**（仅 **IA-32e 上下文** 中有意义）。  
   - **权限角色**：SYSCALL：**CPL 3 → 0**；SYSRET：**CPL 0 → 3**（手册用语为 privilege level 3 与 0）。  
   - **与 SYSENTER 路径的差异**（句级要点）：**栈指针不由 MSR 约定**；**RFLAGS 中哪些位被清除** 由 **`IA32_FMASK`** 编程决定；**SYSCALL/SYSRET 保存并恢复 RFLAGS**（与 SYSENTER/SYSEXIT 的固定 IF 清除等叙述形成对比）。  
   - **SYSCALL 执行后的硬件状态**（需能在纸上推一遍）：  
     - **R11 ← RFLAGS**；**RCX ← 下一条指令的 RIP**；  
     - **CPL 0 代码段**：来自 **`IA32_STAR[47:32]`** 的非 NULL 选择子；  
     - **CPL 0 栈段**：**`IA32_STAR[47:32] + 8`**（手册给出的推导关系）；  
     - **RIP**：来自 **`IA32_LSTAR`**（手册说明 **WRMSR** 侧对写入值 **canonical** 的约束语境）；  
     - **RFLAGS**：**与 `~IA32_FMASK` 按位与**（即 FMASK 为 1 的位在 SYSCALL 时被清）。  
   - **SYSRET 两条返回形态**（务必分开记）：  
     - **使用 REX.W 返回 64 位用户代码**：用户 **CS** 来自 **`IA32_STAR[63:48] + 16`**；**RIP ← RCX**；用户 **SS** 为 **`IA32_STAR[63:48] + 8`**；**RFLAGS ← R11**。  
     - **32 位操作数大小返回 32 位用户代码**：**CS** 来自 **`IA32_STAR[63:48]`**；**EIP ← ECX**；**SS** 仍为 **`IA32_STAR[63:48] + 8`**；**EFLAGS ← R11**。  
   - **Figure 5-14** *MSRs Used by SYSCALL and SYSRET*：**STAR / LSTAR / FMASK** 各字段在图中的分区（SYSCALL 用 CS/SS、SYSRET 用 CS/SS、LSTAR 存目标 RIP、FMASK 存 RFLAGS 掩码）。

4. **§5.8.8 后半：软件职责与异常**  
   - **SYSCALL 不保存 RSP，SYSRET 不恢复 RSP**：**由软件**在用户栈与内核栈之间保存/恢复 **RSP**（手册列举可放在用户侧或 OS 侧的时机）。  
   - **在 SYSRET 前若恢复用户栈**：为避免 **中断/异常** 落到错误栈，手册讨论 **清 IF**、**NMI 用 IST**、以及 **SYSRET 因 RCX 非 canonical 产生 #GP(0)** 时的应对（确认 RCX、分页约束、或对 #GP 使用 IST）。  

5. **Vol. 4**  
   对照 **`IA32_EFER`、`IA32_STAR`、`IA32_LSTAR`、`IA32_FMASK`** 的 **完整位域、读写属性、复位值**（以你使用的 SDM 修订版为准）。

6. **Vol. 2**  
   打开 **SYSCALL** 与 **SYSRET** 独立条目，核对：**长模式 / 兼容模式**下的 **#UD**、操作数大小对 SYSRET 行为的影响、与 **RIPL** 等相关标志的精确叙述，并与 Vol. 3A §5.8.8 的 **系统编程级** 故事对齐。

7. **（可选）Vol. 3A VMX §31.10.4.3**  
   仅在编写 **VMM** 或审计 **嵌套虚拟化** 时必读；与 **通用操作系统内核** 读法可分轨。

---

## 3. 读 §5.8.8 时可边读边答的问题（自检）

1. **STAR 的高 16 位与低 16 位（32:47 与 48:63）分别服务 SYSCALL 还是 SYSRET？** 各自加 **8** 或 **16** 后对应 **哪个段寄存器**？  
2. **若没有 MSR 保存 RSP，OS 最小要在哪两个时刻之一保存用户 RSP？**  
3. **FMASK 典型用法**（思考题）：若希望用户态 **IF** 在进入内核时被清掉，应在 FMASK 对应位如何设置？（需结合「与补码按位与」的语义自己推导。）  
4. **SYSRET 前 RCX 必须满足什么线性地址性质**，否则会 **#GP(0)**？

---

## 4. 与手册其它概念的衔接（扩展阅读）

- **§5** *Protection* 前后文：门、调用门、**直接_far_call** 等与 **SYSCALL「非门控快速转移」** 的对照（Vol. 3A 在介绍 **JMP/CALL/RET/SYSENTER/SYSCALL…** 时会把 SYSCALL/SYSRET 归为一类 **无调用门的控制转移** 叙述——可搜正文中的 *SYSCALL* 交叉引用）。  
- **分页与执行权限**：与 **`NX` / `EFER.NXE`**（Vol. 3A §4、§2）同属系统使能，读内核引导代码时常见同一阶段配置。

---

## 5. 版本说明

不同 **修订版**（你本地 PDF 例如 **253668-060US，September 2016**）会调整 **勘误、页码、小节编号**；**§5.8.8**、**Figure 5-14**、**IA32_EFER.SCE** 等标题在多版中保持稳定。若引用给他人，建议注明 **手册 Order Number 与修订日期**。

---

*本导读仅索引官方架构手册中的概念位置，**不构成**对具体 CPU 步进或 errata 的保证；生产级行为以实现与最新 **SDM + 产品规格** 为准。*
