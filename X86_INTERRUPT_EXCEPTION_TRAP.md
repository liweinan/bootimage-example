# x86 中断、异常、陷阱：Intel SDM 规范与 Linux 实现

本文档基于 **Intel Software Developer Manual (SDM) Volume 3A Chapter 6** 和 **Linux 内核源码**，详细阐述 x86 架构中 Interrupt（中断）、Exception（异常）、Trap（陷阱）的本质区别及其在 Linux 内核中的实现。

**⚠️ 重要勘误（2026-02-14）**：

本文档经严格核对 Intel SDM Volume 3A Chapter 6 原文后，发现并修正了以下关键错误：

1. **INT n 的分类**：
   - ❌ **错误**：INT n (如 INT 0x80) 归类为 Exception
   - ✅ **正确**：INT n 归类为 **Interrupt**（Intel SDM 6.3.3 Software-Generated Interrupts）
   - 📖 **依据**：Table 6-1 明确标注 Vector 32-255 为 "Interrupt" 类型，Source: "External interrupt or INT n instruction"

2. **INT 3 / INTO 的分类**：
   - ✅ **正确**：INT 3, INTO, BOUND 归类为 **Exception**（Intel SDM 6.4.2 Software-Generated Exceptions）
   - 📖 **依据**：Table 6-1 标注 Vector 3 (#BP) 和 Vector 4 (#OF) 为 "Trap" 类型

3. **核心发现**：
   - Intel SDM 将 **INT n (通用向量)** 和 **INT 3/INTO (特殊向量)** 归入**不同类别**
   - **不能笼统地说"软件中断归类为异常"**，需要区分具体指令

**补充文档**：
- **[x86 异常的硬件触发机制：Page Fault 与 Breakpoint 深入剖析](X86_EXCEPTION_HARDWARE_TRIGGER.md)** - 通过实际案例详解异常的硬件触发流程、向量号的硬件规范、以及软件职责边界

---

## 目录

- [一、Intel SDM 官方定义](#一intel-sdm-官方定义)
- [二、三者的本质区别](#二三者的本质区别)
- [三、Exception 的三种类型](#三exception-的三种类型)
- [四、中断/异常优先级](#四中断异常优先级)
- [五、IDT 门描述符类型](#五idt-门描述符类型)
- [六、Linux 内核实现](#六linux-内核实现)
- [七、常见误解澄清](#七常见误解澄清)
- [八、相关文档](#八相关文档)

---

## 一、Intel SDM 官方定义

### 1.1 基本概念

根据 **Intel SDM Volume 3A, Section 6.1**：

> **Interrupt** - An interrupt is an asynchronous event that is typically triggered by an I/O device.
>
> **Exception** - An exception is a synchronous event that is generated when the processor detects one or more predefined conditions while executing an instruction.

**中文翻译**：
- **Interrupt（中断）**：中断是一个**异步事件**，通常由 I/O 设备触发。
- **Exception（异常）**：异常是一个**同步事件**，当处理器在执行指令时检测到一个或多个预定义条件时产生。

### 1.2 Intel SDM 分类体系

根据 **Intel SDM Volume 3A, Chapter 6** 的实际章节结构：

**6.3 SOURCES OF INTERRUPTS** (中断的来源)
- 6.3.1 **External Interrupts** - 外部硬件中断
- 6.3.2 Maskable Hardware Interrupts - 可屏蔽硬件中断
- 6.3.3 **Software-Generated Interrupts** - 软件生成的中断（`INT n` 指令）

**6.4 SOURCES OF EXCEPTIONS** (异常的来源)
- 6.4.1 **Program-Error Exceptions** - 程序错误异常
- 6.4.2 **Software-Generated Exceptions** - 软件生成的异常（`INT 3`, `INTO`, `BOUND`）

### 1.3 关键术语

| 术语 | Intel SDM 分类 | 章节位置 | 触发方式 | 示例 |
|------|---------------|---------|---------|------|
| **External Interrupt** | Interrupt | 6.3.1 | 异步，外部硬件设备 | 时钟中断、键盘中断、网卡中断 |
| **Software-Generated Interrupt** | **Interrupt** | **6.3.3** | 同步，`INT n` 指令 | **`INT 0x80`**, `INT 35` |
| **Software-Generated Exception** | **Exception** | **6.4.2** | 同步，特定指令 | **`INT 3`**, `INTO`, `BOUND` |
| **Program-Error Exception** | Exception | 6.4.1 | 同步，指令执行错误 | #PF（缺页）、#GP（保护违例）、#DE（除零） |
| **Trap** | Exception 的子类型 | 6.5 | 同步 | #BP（断点）、#OF（溢出） |
| **Fault** | Exception 的子类型 | 6.5 | 同步 | #PF（缺页）、#GP（保护违例） |
| **Abort** | Exception 的子类型 | 6.5 | 同步 | #DF（双重故障）、#MC（机器检查） |

**重要发现**（基于 **Intel SDM Volume 3A, Table 6-1**）：

1. **INT n (通用向量)** 在 Intel SDM 中被归类为 **Interrupt**（6.3.3 章节）
   - Table 6-1 明确标注：Vector 32-255, Type: **Interrupt**, Source: "External interrupt **or INT n instruction**"
   - 示例：`INT 0x80`（系统调用）、`INT 35`（自定义中断）

2. **INT 3, INTO, BOUND** 在 Intel SDM 中被归类为 **Exception**（6.4.2 章节）
   - Table 6-1 标注：Vector 3 (#BP), Type: **Trap**, Source: "INT 3 instruction"
   - Table 6-1 标注：Vector 4 (#OF), Type: **Trap**, Source: "INTO instruction"

### 1.4 Intel SDM 分类树状图

基于 **Intel SDM Volume 3A Chapter 6** 的实际章节结构：

**重要说明：Interrupt 和 Exception 是两个并列的分类，不是包含关系！**

```
Chapter 6: INTERRUPT AND EXCEPTION HANDLING
│
├─ Chapter 6.3: SOURCES OF INTERRUPTS (中断来源)
│  │
│  ├─ 6.3.1 External Interrupts (外部中断)
│  │   ├─ 通过硬件引脚或 APIC 触发，异步
│  │   ├─ **可屏蔽类型** (6.3.2 Maskable Hardware Interrupts)：
│  │   │   ├─ 通过 INTR 引脚或 APIC 传递
│  │   │   ├─ 受 EFLAGS.IF 控制（可被全局屏蔽）
│  │   │   └─ 示例：IRQ 0-15 (PIC), Vector 16-255 (APIC)
│  │   └─ **不可屏蔽类型** (NMI)：
│  │       ├─ 通过 NMI 引脚触发
│  │       ├─ Vector 2，不受 IF 控制
│  │       └─ 示例：硬件错误、系统故障
│  │
│  └─ 6.3.3 Software-Generated Interrupts (软件生成的中断) ✅ 关键！
│      ├─ INT n 指令触发，同步
│      ├─ 不受 EFLAGS.IF 控制（不可屏蔽）
│      ├─ Table 6-1 类型：Interrupt
│      └─ 示例：INT 0x80 (系统调用), INT 35 (自定义)
│
└─ Chapter 6.4: SOURCES OF EXCEPTIONS (异常来源)
   │
   ├─ 6.4.1 Program-Error Exceptions (程序错误异常)
   │   ├─ 指令执行时检测到错误
   │   ├─ 不受 EFLAGS.IF 控制（不可屏蔽）
   │   ├─ 分为三种类型（见 6.5）：
   │   │   ├─ Fault (故障) - RIP 指向引起故障的指令
   │   │   │   └─ 示例：#PF (缺页), #GP (保护违例), #DE (除零)
   │   │   ├─ Trap (陷阱) - RIP 指向下一条指令
   │   │   │   └─ 示例：#DB (调试), #BP (断点)
   │   │   └─ Abort (中止) - RIP 不可靠，不可恢复
   │   │       └─ 示例：#DF (双重故障), #MC (机器检查)
   │   └─ 向量范围：0-31 (CPU 保留)
   │
   └─ 6.4.2 Software-Generated Exceptions (软件生成的异常) ✅ 关键！
       ├─ 特定指令触发：INT 3, INTO, BOUND
       ├─ 不受 EFLAGS.IF 控制（不可屏蔽）
       ├─ Table 6-1 类型：Trap (Exception 的子类型)
       └─ 示例：
           ├─ INT 3 (断点，向量 3)
           ├─ INTO (溢出检查，向量 4)
           └─ BOUND (边界检查，向量 5)
```

**核心区别总结**：

| 指令 | Intel SDM 章节 | 分类 | Table 6-1 Type | 向量范围 | 典型用途 |
|------|---------------|------|---------------|---------|---------|
| **INT n** | 6.3.3 Software-Generated **Interrupts** | **Interrupt** | **Interrupt** | 32-255 | 系统调用 (INT 0x80) |
| **INT 3** | 6.4.2 Software-Generated **Exceptions** | **Exception** | **Trap** | 3 | 调试断点 |
| **INTO** | 6.4.2 Software-Generated **Exceptions** | **Exception** | **Trap** | 4 | 溢出检测 |
| **IRQ** | 6.3.1 External **Interrupts** | **Interrupt** | **Interrupt** | 32-255 | 硬件中断 |

---

## 二、Interrupt vs Exception 的本质区别

### 2.1 完整对比表

| 特性 | **External Interrupt**<br>（外部中断，如 IRQ） | **Software-Generated Interrupt**<br>（软件中断，INT n，如 INT 0x80） | **Software-Generated Exception**<br>（软件异常，INT 3/INTO） | **Program-Error Exception**<br>（程序错误异常，如 #PF、#GP） |
|------|--------------------------------------|------------------------------------------------|----------------------------------|----------------------------------|
| **Intel SDM 分类** | **Interrupt** (6.3.1) | **Interrupt** (6.3.3) | **Exception** (6.4.2) | **Exception** (6.4.1) |
| **触发方式** | 异步，外部硬件设备 | 同步，`INT n` 指令 | 同步，`INT 3`/`INTO`/`BOUND` 指令 | 同步，当前指令或 CPU 状态 |
| **触发时机** | 任意时刻（与指令执行无关） | 执行 `INT n` 指令时 | 执行 `INT 3`/`INTO` 指令时 | 执行特定指令或检测到错误时 |
| **受 EFLAGS.IF 控制？** | ✅ **是**（IF=0 时被屏蔽） | ❌ **否**（IF=0 时仍会触发） | ❌ **否**（IF=0 时仍会触发） | ❌ **否**（IF=0 时仍会触发） |
| **可否被屏蔽？** | 可屏蔽（Maskable）<br>NMI 不可屏蔽 | 不可屏蔽 | 不可屏蔽 | 不可屏蔽 |
| **优先级** | 低（优先级 6） | 与异常相同（优先级 10） | 高（优先级 4） | 高（优先级 7-10） |
| **向量范围** | 32-255 | 32-255（用户自定义） | 0-31（CPU 保留向量） | 0-31（CPU 保留向量） |
| **Table 6-1 Type** | **Interrupt** | **Interrupt** | **Trap** (INT 3), **Trap** (INTO) | **Fault/Trap/Abort** |
| **DPL 设置** | 通常 DPL=0（内核态） | 可设为 DPL=3（用户态可触发） | DPL=3（用户态可触发） | 多数 DPL=0，少数 DPL=3 |
| **典型示例** | IRQ 0（时钟）<br>IRQ 1（键盘）<br>IRQ 14（硬盘） | **INT 0x80**（系统调用）<br>INT 35（自定义） | **INT 3**（断点）<br>**INTO**（溢出检查） | #PF（缺页）<br>#GP（保护违例）<br>#DE（除零） |
| **Linux Event Type** | `EVENT_TYPE_EXTINT` (0) | `EVENT_TYPE_SWINT` (4) | `EVENT_TYPE_SWEXC` (6) | `EVENT_TYPE_HWEXC` (3) |

### 2.2 核心区别总结

**基于 Intel SDM Volume 3A 的分类（两个并列的顶级分类）：**

```
【分类 1】Interrupt（中断）
├─ External Interrupts (6.3.1) - 硬件触发，异步，受 IF 控制
└─ Software-Generated Interrupts (6.3.3) - INT n 指令触发，同步，不受 IF 控制

【分类 2】Exception（异常）⚠️ 与 Interrupt 并列，不是子集
├─ Program-Error Exceptions (6.4.1) - 指令执行错误，如 #PF, #GP, #DE
└─ Software-Generated Exceptions (6.4.2) - INT 3, INTO, BOUND 指令
```

**关键洞察**：

1. **INT n 和 INT 3 的分类差异**
   - **INT n (通用向量，如 INT 0x80)**：在 Intel SDM 中归类为 **Interrupt**（6.3.3）
     - Table 6-1 明确标注为 "Interrupt" 类型
     - 虽然是同步触发，但 Intel 将其归入 Interrupt 类别
   - **INT 3, INTO, BOUND**：在 Intel SDM 中归类为 **Exception**（6.4.2）
     - Table 6-1 标注为 "Trap" 类型（Exception 的子类型）
     - 特殊的软件异常，主要用于调试

2. **同步 vs 异步不是唯一分类标准**
   - **External Interrupts**：异步 + 受 IF 控制 → Interrupt
   - **INT n (如 INT 0x80)**：同步 + 不受 IF 控制 → 仍归类为 Interrupt（按 Intel SDM 6.3.3）
   - **INT 3, INTO**：同步 + 不受 IF 控制 → Exception（按 Intel SDM 6.4.2）
   - **Program Errors**：同步 + 不受 IF 控制 → Exception

3. **Trap 是 Exception 的一种子类型**
   - Trap 不是与 Interrupt/Exception 平级的概念
   - Trap 是 Exception 的三种类型之一（Fault/Trap/Abort）
   - 详见下文"Exception 的三种类型"章节

---

## 三、Exception 的三种类型

根据 **Intel SDM Volume 3A, Section 6.4**，Exception 按照**发生位置**和**可恢复性**分为三类：

### 3.1 Fault（故障）

**定义**：在引起异常的指令**执行之前**被检测到的异常。

**特征**：
- **保存的 EIP/RIP**：指向**引起故障的指令**（fault instruction）
- **可恢复性**：✅ **可恢复** - 修复问题后可以重新执行该指令
- **典型用途**：需要操作系统介入修复的条件（如缺页、权限不足）

**典型示例**：

| 向量 | 名称 | 说明 | 恢复方式 |
|------|------|------|---------|
| **#PF (14)** | Page Fault | 缺页异常 | 从磁盘加载页面，重新执行访问内存的指令 |
| **#GP (13)** | General Protection | 保护违例 | 通常无法恢复，杀死进程 |
| **#NP (11)** | Segment Not Present | 段不存在 | 加载段，重新执行 |
| **#SS (12)** | Stack Segment Fault | 栈段错误 | 修复栈，重新执行 |
| **#AC (17)** | Alignment Check | 对齐检查 | 修复对齐，重新执行 |

**示例代码**：
```c
// 缺页异常示例
int *ptr = (int *)0x1000000;  // 假设这个页面未映射
*ptr = 42;                    // 触发 #PF

// CPU 行为：
// 1. 检测到页面不存在
// 2. 触发 #PF (Fault)
// 3. 保存的 RIP 指向 "mov [ptr], 42" 指令
// 4. 跳转到 #PF 处理程序
// 5. 内核分配页面，更新页表
// 6. iret 返回，重新执行 "mov [ptr], 42" 指令
// 7. 成功执行
```

### 3.2 Trap（陷阱）

**定义**：在引起异常的指令**执行之后**立即被报告的异常。

**特征**：
- **保存的 EIP/RIP**：指向**下一条指令**（next instruction）
- **可恢复性**：✅ **可恢复** - 允许程序继续执行
- **典型用途**：调试、单步执行、条件监控

**典型示例**：

| 向量 | 名称 | 说明 | 用途 |
|------|------|------|------|
| **#BP (3)** | Breakpoint | 断点异常 | 调试器设置断点（`INT 3`） |
| **#OF (4)** | Overflow | 溢出异常 | 检测算术溢出（`INTO` 指令，32位） |
| **#DB (1)** | Debug | 调试异常（部分情况） | 单步执行、硬件断点 |

**示例代码**：
```c
// 断点异常示例（调试器使用）
int main() {
    int x = 10;
    __asm__("int3");  // 触发 #BP (Trap)
    int y = 20;       // 断点后继续执行
    return x + y;
}

// CPU 行为：
// 1. 执行 "int3" 指令
// 2. 触发 #BP (Trap)
// 3. 保存的 RIP 指向 "int y = 20;" 指令（下一条）
// 4. 跳转到 #BP 处理程序（调试器）
// 5. 调试器显示断点信息
// 6. iret 返回，继续执行 "int y = 20;"
```

### 3.3 Abort（中止）

**定义**：不总是报告引起异常的指令的精确位置，不允许重新启动引起异常的程序或任务。

**特征**：
- **保存的 EIP/RIP**：**不可靠**，可能指向任意位置
- **可恢复性**：❌ **不可恢复** - 严重错误，通常需要系统重启
- **典型用途**：硬件故障、系统崩溃

**典型示例**：

| 向量 | 名称 | 说明 | 处理方式 |
|------|------|------|---------|
| **#DF (8)** | Double Fault | 双重故障 | 通常 panic，无法恢复 |
| **#MC (18)** | Machine Check | 机器检查异常 | 硬件错误，记录日志后可能重启 |

**示例场景**：
```c
// 双重故障示例（理论场景）
// 场景：在处理 #GP 异常时，又发生了 #SS 异常（栈段错误）

void handle_gp_fault() {
    // 假设栈段有问题
    int *stack_ptr = (int *)0xBadStack;
    *stack_ptr = 42;  // 触发 #SS
}

// CPU 行为：
// 1. 处理 #GP 时触发 #SS
// 2. CPU 检测到"在处理异常时又发生异常"
// 3. 触发 #DF (Double Fault, Abort)
// 4. 保存的 RIP 不可靠
// 5. 跳转到 #DF 处理程序
// 6. 通常 kernel panic，无法恢复
```

### 3.4 三种类型对比总结

| 类型 | 保存的 EIP/RIP | 可恢复性 | 典型用途 | 示例 |
|------|---------------|---------|---------|------|
| **Fault** | 指向**引起故障的指令** | ✅ 可恢复 | 需要修复后重新执行 | #PF, #GP, #NP |
| **Trap** | 指向**下一条指令** | ✅ 可恢复 | 调试、监控 | #BP, #OF, #DB |
| **Abort** | **不可靠** | ❌ 不可恢复 | 严重错误 | #DF, #MC |

---

## 四、中断/异常优先级

根据 **Intel SDM Volume 3A, Table 6-2: Priority Among Simultaneous Exceptions and Interrupts**：

### 4.1 优先级列表（从高到低）

| 优先级 | 类别 | 说明 | 示例 |
|-------|------|------|------|
| **1** | Hardware Reset and Machine Checks | 硬件重置和机器检查 | RESET, #MC |
| **2** | Trap on Task Switch | 任务切换陷阱 | T flag in TSS |
| **3** | External Hardware Interventions | 外部硬件干预 | FLUSH, STOPCLK, SMI, INIT |
| **4** | Traps on Previous Instruction | 前一条指令的陷阱 | #DB (data breakpoint), #BP, #OF |
| **5** | Nonmaskable Interrupt (NMI) | 不可屏蔽中断 | NMI |
| **6** | Maskable Hardware Interrupts | 可屏蔽硬件中断 | **INTR（所有设备中断）** |
| **7** | Code Breakpoint Faults | 代码断点故障 | #DB (instruction breakpoint) |
| **8** | Faults from Fetching Next Instruction | 取指令时的故障 | #PF (code fetch), #GP (code fetch) |
| **9** | Faults from Decoding Next Instruction | 解码指令时的故障 | #UD, #GP (privilege check) |
| **10** | Faults on Executing an Instruction | 执行指令时的故障 | #DE, #TS, #NP, #SS, #GP, #PF (data), #AC, #XF, #CP, #VC |

### 4.2 关键要点

1. **硬件中断（IRQ）优先级为 6**
   - 可以被优先级 1-5 的事件抢占
   - 特别是会被 **异常** 抢占（优先级 7-10）

2. **异常优先级高于硬件中断**
   - 这就是为什么在内核启动早期（`cli` 关闭 IF 标志后）
   - 仍然可以处理异常（如 #PF、#VC）
   - 但不会响应硬件中断（IRQ）

3. **NMI 不可屏蔽**
   - NMI 优先级为 5，高于硬件中断
   - 即使 IF=0，NMI 仍会触发

**实际影响示例**：
```c
// arch/x86/kernel/head_64.S
startup_64:
    cli  // EFLAGS.IF = 0，关闭硬件中断

    // 此时状态：
    // ✅ 优先级 1-5：仍会触发（RESET, #MC, NMI 等）
    // ✅ 优先级 7-10：仍会触发（所有异常，如 #PF, #GP, #VC）
    // ❌ 优先级 6：被屏蔽（所有硬件中断，如 IRQ 0, IRQ 1）

    call verify_cpu  // 可能触发 #VC 异常（优先级 10）
```

---

## 五、IDT 门描述符类型

根据 **Intel SDM Volume 3A, Section 6.11**，IDT 支持三种门描述符：

### 5.1 门类型对比

| 门类型 | 类型值 | IF 标志行为 | 典型用途 | Linux 使用 |
|--------|-------|------------|---------|-----------|
| **Interrupt Gate** | 0xE (64-bit)<br>0x6 (32-bit) | **自动清除 IF**<br>（禁用硬件中断） | 硬件中断处理、大多数异常 | ✅ **主要使用**<br>所有 IRQ 和大多数异常 |
| **Trap Gate** | 0xF (64-bit)<br>0x7 (32-bit) | **保留 IF**<br>（允许嵌套中断） | 调试、系统调用（历史） | ❌ **很少使用**<br>现代 Linux 基本不用 |
| **Task Gate** | 0x5 | 任务切换 | 任务切换（386 时代） | ❌ **已废弃**<br>64 位模式不支持 |

### 5.2 Interrupt Gate vs Trap Gate 的关键区别

**Interrupt Gate**：
```
1. CPU 通过 Interrupt Gate 进入中断处理程序时
2. 自动清除 EFLAGS.IF = 0（关闭硬件中断）
3. 防止中断嵌套，确保处理程序原子执行
4. 处理程序内部可以显式 sti 重新开启中断
```

**Trap Gate**：
```
1. CPU 通过 Trap Gate 进入处理程序时
2. 保留 EFLAGS.IF 的当前值
3. 允许中断嵌套（如果 IF=1）
4. 历史上用于系统调用（现在使用 SYSCALL 指令）
```

**代码示例**：
```c
// Linux idt.c 中的门定义宏

/* Interrupt Gate - 自动关闭中断 */
#define INTG(_vector, _addr) \
    G(_vector, _addr, DEFAULT_STACK, GATE_INTERRUPT, DPL0, __KERNEL_CS)

/* Trap Gate - 保留 IF 标志（已废弃）*/
#define TRAPG(_vector, _addr) \
    G(_vector, _addr, DEFAULT_STACK, GATE_TRAP, DPL0, __KERNEL_CS)

/* System Interrupt Gate - 用户态可触发 */
#define SYSG(_vector, _addr) \
    G(_vector, _addr, DEFAULT_STACK, GATE_INTERRUPT, DPL3, __KERNEL_CS)
```

### 5.3 Linux 为什么不使用 Trap Gate？

**历史原因**：
- 在古老的 Unix 系统中，系统调用使用 Trap Gate（保留 IF，允许中断）
- 目的是允许在系统调用执行期间响应硬件中断

**现代 Linux**：
- **不再使用 Trap Gate**，所有 IDT 条目都使用 Interrupt Gate
- 系统调用使用 `SYSCALL`/`SYSENTER` 指令（通过 MSR，不走 IDT）
- `INT 0x80` 兼容路径也使用 Interrupt Gate

**原因**：
1. **安全性**：Interrupt Gate 自动关中断，防止竞态条件
2. **性能**：SYSCALL 指令比 INT 0x80 快 2-3 倍
3. **简化**：统一使用 Interrupt Gate，减少复杂性

---

## 六、Linux 内核实现

### 6.1 异常向量定义

**文件位置**：`arch/x86/include/asm/trapnr.h`

```c
/* Interrupts/Exceptions */
#define X86_TRAP_DE         0   /* Divide-by-zero */
#define X86_TRAP_DB         1   /* Debug */
#define X86_TRAP_NMI        2   /* Non-maskable Interrupt */
#define X86_TRAP_BP         3   /* Breakpoint */
#define X86_TRAP_OF         4   /* Overflow */
#define X86_TRAP_BR         5   /* Bound Range Exceeded */
#define X86_TRAP_UD         6   /* Invalid Opcode */
#define X86_TRAP_NM         7   /* Device Not Available */
#define X86_TRAP_DF         8   /* Double Fault */
#define X86_TRAP_OLD_MF     9   /* Coprocessor Segment Overrun */
#define X86_TRAP_TS        10   /* Invalid TSS */
#define X86_TRAP_NP        11   /* Segment Not Present */
#define X86_TRAP_SS        12   /* Stack Segment Fault */
#define X86_TRAP_GP        13   /* General Protection Fault */
#define X86_TRAP_PF        14   /* Page Fault */
#define X86_TRAP_SPURIOUS  15   /* Spurious Interrupt */
#define X86_TRAP_MF        16   /* x87 Floating-Point Exception */
#define X86_TRAP_AC        17   /* Alignment Check */
#define X86_TRAP_MC        18   /* Machine Check */
#define X86_TRAP_XF        19   /* SIMD Floating-Point Exception */
#define X86_TRAP_VE        20   /* Virtualization Exception */
#define X86_TRAP_CP        21   /* Control Protection Exception */
#define X86_TRAP_VC        29   /* VMM Communication Exception */
#define X86_TRAP_IRET      32   /* IRET Exception */
```

### 6.2 Event Type 分类

**文件位置**：`arch/x86/include/asm/trapnr.h`

Linux 内核使用 **Event Type Codes** 来分类中断/异常（用于 VT-x、SVM、FRED）：

```c
#define EVENT_TYPE_EXTINT       0   /* External interrupt */
#define EVENT_TYPE_NMI          2   /* NMI */
#define EVENT_TYPE_HWEXC        3   /* Hardware originated traps, exceptions */
#define EVENT_TYPE_SWINT        4   /* INT n */
#define EVENT_TYPE_PRIV_SWEXC   5   /* INT1 (ICEBP) */
#define EVENT_TYPE_SWEXC        6   /* INTO, INT3 */
#define EVENT_TYPE_OTHER        7   /* FRED SYSCALL/SYSENTER, VT-x MTF */
```

**与 Intel SDM 的对应关系**：

| Event Type | 值 | Intel SDM 分类 | 说明 | 示例 |
|-----------|---|---------------|------|------|
| `EXTINT` | 0 | **Interrupt** | 外部硬件中断 | IRQ 0-15, APIC 中断 |
| `NMI` | 2 | **Interrupt** | 不可屏蔽中断 | NMI |
| `HWEXC` | 3 | **Exception** | 硬件触发的异常 | #PF, #GP, #DE |
| `SWINT` | 4 | **Exception** | `INT n` 指令 | INT 0x80 |
| `PRIV_SWEXC` | 5 | **Exception** | 特权软件异常 | INT1 (ICEBP) |
| `SWEXC` | 6 | **Exception** | 软件异常 | INTO, INT3 |
| `OTHER` | 7 | - | 其他机制 | SYSCALL, SYSENTER |

### 6.3 IDT 向量布局

**文件位置**：`arch/x86/include/asm/irq_vectors.h`

```c
/*
 * Linux IRQ vector layout:
 *
 * Vectors   0 ...  31 : system traps and exceptions - hardcoded events
 * Vectors  32 ... 127 : device interrupts
 * Vector  128         : legacy int80 syscall interface
 * Vectors 129 ... FIRST_SYSTEM_VECTOR-1 : device interrupts
 * Vectors FIRST_SYSTEM_VECTOR ... 255   : special interrupts
 */

#define NMI_VECTOR                      0x02
#define FIRST_EXTERNAL_VECTOR           0x20   /* 32 */
#define IA32_SYSCALL_VECTOR             0x80   /* 128 */

/* System vectors (0xf0-0xff) */
#define FIRST_SYSTEM_VECTOR             0xf0
#define SPURIOUS_APIC_VECTOR            0xff
#define ERROR_APIC_VECTOR               0xfe
#define RESCHEDULE_VECTOR               0xfd
#define CALL_FUNCTION_VECTOR            0xfc
#define CALL_FUNCTION_SINGLE_VECTOR     0xfb
#define THERMAL_APIC_VECTOR             0xfa
#define THRESHOLD_APIC_VECTOR           0xf9
#define REBOOT_VECTOR                   0xf8
#define X86_PLATFORM_IPI_VECTOR         0xf7
#define IRQ_WORK_VECTOR                 0xf6
#define POSTED_INTR_VECTOR              0xf2
#define LOCAL_TIMER_VECTOR              0xec

#define NR_VECTORS                      256
```

**可视化布局**：
```
0x00 - 0x1F (0-31)    : CPU 异常（Intel 保留）
  ├─ 0x00 (#DE)       : Divide Error
  ├─ 0x01 (#DB)       : Debug
  ├─ 0x02 (NMI)       : Non-Maskable Interrupt
  ├─ 0x03 (#BP)       : Breakpoint
  ├─ 0x0D (#GP)       : General Protection
  ├─ 0x0E (#PF)       : Page Fault
  └─ ...

0x20 - 0x7F (32-127)  : 设备中断（IRQ）
  ├─ 0x20             : IRQ 0 (时钟)
  ├─ 0x21             : IRQ 1 (键盘)
  └─ ...

0x80 (128)            : INT 0x80 系统调用（32 位兼容）

0x81 - 0xEF (129-239) : 更多设备中断

0xF0 - 0xFF (240-255) : 系统向量（APIC、IPI）
  ├─ 0xEC             : Local Timer
  ├─ 0xFD             : Reschedule IPI
  └─ 0xFF             : Spurious Interrupt
```

### 6.4 IDT 初始化

**文件位置**：`arch/x86/kernel/idt.c`

#### 6.4.1 IDT 门宏定义

```c
#define DPL0         0x0  /* Kernel mode */
#define DPL3         0x3  /* User mode */
#define DEFAULT_STACK 0

/* Interrupt gate macro */
#define INTG(_vector, _addr) \
    G(_vector, _addr, DEFAULT_STACK, GATE_INTERRUPT, DPL0, __KERNEL_CS)

/* System interrupt gate (User accessible) */
#define SYSG(_vector, _addr) \
    G(_vector, _addr, DEFAULT_STACK, GATE_INTERRUPT, DPL3, __KERNEL_CS)

/* Interrupt stack table gate (64-bit only) */
#define ISTG(_vector, _addr, _ist) \
    G(_vector, _addr, _ist + 1, GATE_INTERRUPT, DPL0, __KERNEL_CS)
```

**关键点**：
- **所有门都是 Interrupt Gate**（`GATE_INTERRUPT`）
- **没有使用 Trap Gate**（`GATE_TRAP`）
- **DPL=3** 的门允许用户态触发（如 #BP, INT 0x80）

#### 6.4.2 早期 IDT 表

```c
static const __initconst struct idt_data early_idts[] = {
    INTG(X86_TRAP_DB,   asm_exc_debug),
    SYSG(X86_TRAP_BP,   asm_exc_int3),
#ifdef CONFIG_X86_32
    INTG(X86_TRAP_PF,   asm_exc_page_fault),
#endif
#ifdef CONFIG_INTEL_TDX_GUEST
    INTG(X86_TRAP_VE,   asm_exc_virtualization_exception),
#endif
};
```

**特点**：
- 只设置少数几个关键异常
- 用于内核启动早期（页表建立之前）
- 64 位模式下不包括 #PF（单独设置）

#### 6.4.3 默认异常处理表

```c
static const __initconst struct idt_data def_idts[] = {
    INTG(X86_TRAP_DE,   asm_exc_divide_error),
    ISTG(X86_TRAP_NMI,  asm_exc_nmi, IST_INDEX_NMI),
    INTG(X86_TRAP_BR,   asm_exc_bounds),
    INTG(X86_TRAP_UD,   asm_exc_invalid_op),
    INTG(X86_TRAP_NM,   asm_exc_device_not_available),
    INTG(X86_TRAP_OLD_MF, asm_exc_coproc_segment_overrun),
    INTG(X86_TRAP_TS,   asm_exc_invalid_tss),
    INTG(X86_TRAP_NP,   asm_exc_segment_not_present),
    INTG(X86_TRAP_SS,   asm_exc_stack_segment),
    INTG(X86_TRAP_GP,   asm_exc_general_protection),
    INTG(X86_TRAP_SPURIOUS, asm_exc_spurious_interrupt_bug),
    INTG(X86_TRAP_MF,   asm_exc_coprocessor_error),
    INTG(X86_TRAP_AC,   asm_exc_alignment_check),
    INTG(X86_TRAP_XF,   asm_exc_simd_coprocessor_error),

#ifdef CONFIG_X86_64
    ISTG(X86_TRAP_DF,   asm_exc_double_fault, IST_INDEX_DF),
    ISTG(X86_TRAP_DB,   asm_exc_debug, IST_INDEX_DB),
#endif

#ifdef CONFIG_X86_MCE
    ISTG(X86_TRAP_MC,   asm_exc_machine_check, IST_INDEX_MCE),
#endif

#ifdef CONFIG_X86_CET
    INTG(X86_TRAP_CP,   asm_exc_control_protection),
#endif

#ifdef CONFIG_AMD_MEM_ENCRYPT
    ISTG(X86_TRAP_VC,   asm_exc_vmm_communication, IST_INDEX_VC),
#endif

    SYSG(X86_TRAP_OF,   asm_exc_overflow),
};
```

**特点**：
- 覆盖所有 CPU 异常（0-31）
- 关键异常使用 IST（Interrupt Stack Table）
- #BP 和 #OF 设置为 DPL=3（用户态可触发）

#### 6.4.4 INT 0x80 系统调用

```c
#ifdef CONFIG_IA32_EMULATION
static const __initconst struct idt_data ia32_idt[] = {
    SYSG(IA32_SYSCALL_VECTOR, asm_int80_emulation),
};
#endif
```

**特点**：
- 向量 0x80（128）
- DPL=3（用户态可触发）
- 仅用于 32 位兼容，64 位主要使用 SYSCALL 指令

### 6.5 异常处理器定义

**文件位置**：`arch/x86/kernel/traps.c`

使用 `DEFINE_IDTENTRY*` 宏定义异常处理器：

```c
/* Divide Error - Fault */
DEFINE_IDTENTRY(exc_divide_error)
{
    do_error_trap(regs, 0, "divide error", X86_TRAP_DE, SIGFPE,
                  FPE_INTDIV, error_get_trap_addr(regs));
}

/* Debug Exception - Fault/Trap */
DEFINE_IDTENTRY_DEBUG(exc_debug)
{
    /* 调试逻辑 */
}

/* Breakpoint - Trap */
DEFINE_IDTENTRY_RAW(exc_int3)
{
    /* 断点处理 */
}

/* Page Fault - Fault */
DEFINE_IDTENTRY_ERRORCODE(exc_page_fault)
{
    unsigned long address = read_cr2();
    /* 缺页处理 */
}

/* General Protection - Fault */
DEFINE_IDTENTRY_ERRORCODE(exc_general_protection)
{
    /* 保护异常处理 */
}

/* Double Fault - Abort */
DEFINE_IDTENTRY_DF(exc_double_fault)
{
    /* 双重故障，通常 panic */
}
```

### 6.6 初始化流程

```c
// arch/x86/kernel/head_64.S
startup_64:
    call startup_64_setup_gdt_idt  // 加载早期 IDT
    call x86_64_start_kernel

// arch/x86/kernel/head64.c
void x86_64_start_kernel() {
    idt_setup_early_handler();      // 加载早期异常（#DB, #BP, #VE）
    /* ... 页表初始化 ... */
    start_kernel();
}

// init/main.c
void start_kernel() {
    setup_arch();                   // 架构初始化
    trap_init();                    // 异常和系统调用初始化
    init_IRQ();                     // 硬件中断初始化
}

// arch/x86/kernel/traps.c
void trap_init() {
    idt_setup_traps();              // 加载所有异常处理器（包括 INT 0x80）
    cpu_init();                     // 初始化 IST，设置 SYSCALL MSR
}

// arch/x86/kernel/irqinit.c
void init_IRQ() {
    idt_setup_apic_and_irq_gates(); // 加载 APIC 和设备中断
}
```

---

## 七、常见误解澄清

### 7.1 误解一：INT n 和 INT 3 都是"软件中断"，应该归为同一类

**❌ 错误理解**：
```
中断
├─ 硬件中断（Hardware Interrupt）- IRQ
└─ 软件中断（Software Interrupt）- INT n, INT 3, INTO
```

**✅ 正确理解（基于 Intel SDM Chapter 6）**：
```
CPU 事件
├─ Interrupt（中断）
│   ├─ External Interrupts (6.3.1) - 外部硬件中断（如 IRQ）
│   └─ Software-Generated Interrupts (6.3.3) - INT n 指令（如 INT 0x80, INT 35）
│       ↑ 注意：这归类为 Interrupt，不是 Exception！
└─ Exception（异常）
    ├─ Program-Error Exceptions (6.4.1)
    │   ├─ Fault（故障）- 如 #PF, #GP
    │   ├─ Trap（陷阱）- 如部分 #DB
    │   └─ Abort（中止）- 如 #DF, #MC
    └─ Software-Generated Exceptions (6.4.2)
        └─ INT 3, INTO, BOUND
            ↑ 这些归类为 Exception (Trap 类型)
```

**关键点**：

1. **INT n (通用向量) ≠ INT 3/INTO**
   - **INT n (如 INT 0x80)**：Intel SDM 6.3.3 Software-Generated **Interrupts** → 归类为 **Interrupt**
   - **INT 3, INTO, BOUND**：Intel SDM 6.4.2 Software-Generated **Exceptions** → 归类为 **Exception**

2. **为什么 Intel 这样分类？**
   - **INT n**：用户可自定义向量（32-255），功能灵活，Table 6-1 标注为 "Interrupt" 类型
   - **INT 3, INTO**：CPU 预定义向量（3, 4），专门用于调试/异常检测，Table 6-1 标注为 "Trap" 类型

3. **同步触发不等于 Exception**
   - 虽然 INT n 是同步触发（执行指令时）
   - 但 Intel SDM 仍将其归入 Interrupt 类别（6.3.3）
   - 这表明分类标准不仅仅是同步/异步

### 7.2 误解二："Trap" 是独立的中断类型

**❌ 错误理解**：
```
中断类型
├─ Interrupt（中断）
├─ Exception（异常）
└─ Trap（陷阱）← 认为是独立类型
```

**✅ 正确理解**：
```
中断类型
├─ Interrupt（中断）
└─ Exception（异常）
    ├─ Fault（故障）
    ├─ Trap（陷阱）← 这是 Exception 的子类型
    └─ Abort（中止）
```

**关键点**：
- Trap 不是与 Interrupt/Exception 平级的概念
- Trap 是 Exception 的三种类型之一
- 另外两种是 Fault 和 Abort

### 7.3 误解三：INT 0x80 通过 SYSCALL 指令实现

**❌ 错误理解**：
```c
// 用户程序
syscall();  // 认为 INT 0x80 也通过 SYSCALL 指令
```

**✅ 正确理解**：

| 机制 | 指令 | 是否使用 IDT | MSR | 性能 |
|------|------|-------------|-----|------|
| **INT 0x80** | `int $0x80` | ✅ 是（查 IDT[0x80]） | 不使用 | 慢 (~200 周期) |
| **SYSCALL** | `syscall` | ❌ 否 | ✅ MSR_LSTAR | 快 (~60 周期) |

**关键点**：
- INT 0x80 和 SYSCALL 是**两种完全不同**的系统调用机制
- INT 0x80 通过 IDT 表（软件中断方式）
- SYSCALL 通过 MSR 寄存器（专用指令）
- 详见 [LINUX_KERNEL_SYSCALL_INIT.md](LINUX_KERNEL_SYSCALL_INIT.md)

### 7.4 误解四：Trap Gate 用于系统调用

**❌ 错误理解**：
```c
// 认为 Linux 使用 Trap Gate 处理 INT 0x80
TRAPG(IA32_SYSCALL_VECTOR, asm_int80_emulation);  // ❌ 错误
```

**✅ 正确理解**：
```c
// Linux 使用 Interrupt Gate（自动关中断）
SYSG(IA32_SYSCALL_VECTOR, asm_int80_emulation);   // ✅ 正确
// SYSG 宏使用 GATE_INTERRUPT，不是 GATE_TRAP
```

**关键点**：
- 现代 Linux **不使用 Trap Gate**
- 所有 IDT 条目都使用 Interrupt Gate
- 包括 INT 0x80 系统调用

### 7.5 误解五：关闭中断后无法处理任何事件

**❌ 错误理解**：
```c
cli;  // 关闭中断后，什么都处理不了
```

**✅ 正确理解**：
```c
cli;  // EFLAGS.IF = 0

// ✅ 仍然可以处理：
// - 所有异常（Fault, Trap, Abort）
// - NMI（不可屏蔽中断）
// - Software Interrupt（INT n）

// ❌ 无法响应：
// - 可屏蔽硬件中断（IRQ）
```

**关键点**：
- `cli` 只屏蔽**可屏蔽硬件中断**（优先级 6）
- 不影响异常（优先级 7-10）和 NMI（优先级 5）
- 这就是为什么内核启动早期可以处理 #PF、#VC 等异常

---

## 八、相关文档

### 8.1 x86 架构基础

- **[X86_CPU_MODES.md](X86_CPU_MODES.md)** - x86 CPU 模式（实模式、保护模式、长模式）
- **[X86_MEMORY_MANAGEMENT_THEORY.md](X86_MEMORY_MANAGEMENT_THEORY.md)** - GDT 详解：从保护模式到长模式
- **[X86_INTERRUPT_CONTROLLER_EVOLUTION.md](X86_INTERRUPT_CONTROLLER_EVOLUTION.md)** - 中断控制器演进（8259 PIC vs APIC）

### 8.2 Linux 中断系统

- **[X86_EXCEPTION_HARDWARE_TRIGGER.md](X86_EXCEPTION_HARDWARE_TRIGGER.md)** - 异常的硬件触发机制：Page Fault 与 Breakpoint 深入剖析（本文档补充）
- **[LINUX_KERNEL_IDT_EVOLUTION.md](LINUX_KERNEL_IDT_EVOLUTION.md)** - IDT 表的演进流程详解
- **[LINUX_KERNEL_SYSCALL_INIT.md](LINUX_KERNEL_SYSCALL_INIT.md)** - 系统调用初始化详解（INT 0x80 vs SYSCALL/SYSENTER）
- **[LINUX_INTERRUPT_GUIDE.md](LINUX_INTERRUPT_GUIDE.md)** - Linux 中断处理机制（Top Half/Bottom Half）

### 8.3 Linux 内核启动

- **[LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md)** - Linux 内核启动与初始化
- **[LINUX_MEMORY_MANAGEMENT_EVOLUTION.md](LINUX_MEMORY_MANAGEMENT_EVOLUTION.md)** - Linux 内核分页机制完整指南

### 8.4 BIOS/UEFI 中断

- **[BIOS_IVT_VS_KERNEL_IDT.md](BIOS_IVT_VS_KERNEL_IDT.md)** - BIOS IVT 与 Kernel IDT 对比
- **[UEFI_INTERRUPT_HANDLING.md](UEFI_INTERRUPT_HANDLING.md)** - UEFI 中断处理机制

---

## 参考资料

1. **Intel® 64 and IA-32 Architectures Software Developer's Manual**
   - Volume 3A, Chapter 6: Interrupt and Exception Handling
   - `https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html`

2. **Linux Kernel Source Code**
   - `arch/x86/include/asm/trapnr.h` - 异常向量定义 - `https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/arch/x86/include/asm/trapnr.h`
   - `arch/x86/include/asm/irq_vectors.h` - IRQ 向量布局 - `https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/arch/x86/include/asm/irq_vectors.h`
   - `arch/x86/kernel/idt.c` - IDT 初始化 - `https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/arch/x86/kernel/idt.c`
   - `arch/x86/kernel/traps.c` - 异常处理器 - `https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/arch/x86/kernel/traps.c`

3. **AMD64 Architecture Programmer's Manual**
   - Volume 2: System Programming

---

**文档版本**：1.0
**最后更新**：2026-02-12
**基于内核版本**：Linux v6.x
