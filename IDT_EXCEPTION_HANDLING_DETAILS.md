# IDT 早期异常处理流程详解

**所属文档系列**：Linux x86_64 IDT 初始化机制分析
**主文档**：[IDT_SETUP_EARLY_HANDLER_DETAILED_ANALYSIS.md](./IDT_SETUP_EARLY_HANDLER_DETAILED_ANALYSIS.md)
**相关文档**：
- [IDT_COMPLETE_VECTOR_TABLE.md](./IDT_COMPLETE_VECTOR_TABLE.md) - 完整向量表参考手册
- [IDT_DATA_STRUCTURES_RELATIONSHIP.md](./IDT_DATA_STRUCTURES_RELATIONSHIP.md) - 数据结构关系详解

---

## 目录

1. [CPU 触发异常的流程](#1-cpu-触发异常的流程)
2. [early_idt_handler_array 的桩代码](#2-early_idt_handler_array-的桩代码)
3. [early_idt_handler_common - 公共处理程序](#3-early_idt_handler_common---公共处理程序)
4. [do_early_exception() - C 语言处理](#4-do_early_exception---c-语言处理)
5. [完整执行流程示例（#PF）](#5-完整执行流程示例pf)

---

## 概述

当 CPU 触发异常时，它根据 IDTR 寄存器找到 idt_table，读取对应的门描述符，跳转到处理程序。本文档详细解析从 CPU 硬件触发异常，到最终调用 C 语言处理函数的完整流程。

---

## 1. CPU 触发异常的流程

### 示例：#PF（Page Fault，向量 14）

```
1. 用户代码访问无效地址
     ↓
2. CPU 检测到缺页异常
     ↓
3. CPU 保存上下文（RFLAGS、CS、RIP 等）
     ↓
4. CPU 读取 IDTR.base（= &idt_table）
     ↓
5. CPU 计算地址：IDTR.base + 14 × 16
     ↓
6. CPU 读取 idt_table[14]（16 字节）
     ↓
7. CPU 提取处理程序地址：
   offset = offset_high | offset_middle | offset_low
     ↓
8. CPU 跳转到该地址（early_idt_handler_array[14]）
```

### 关键硬件操作

| 步骤 | 操作 | 说明 |
|------|------|------|
| 1 | 保存现场 | CPU 自动压入 SS、RSP、RFLAGS、CS、RIP |
| 2 | 压入错误码 | 仅部分异常（如 #PF、#GP）会压入错误码 |
| 3 | 读取 IDTR | 获取 IDT 表的基地址和大小 |
| 4 | 查表 | 读取 idt_table[vector_number] |
| 5 | 特权级检查 | 验证 DPL、CPL、RPL（详见 CPU 特权级检查机制） |
| 6 | 切换栈 | 如果配置了 IST，切换到专用栈（早期未启用） |
| 7 | 跳转 | 跳转到门描述符中指定的处理程序地址 |

### CPU 自动压入的栈帧

```
异常前栈顶 → ┌─────────────────────────┐
             │  (原栈内容)               │
             └─────────────────────────┘
CPU 压入后 → ┌─────────────────────────┐ ← SS (仅在特权级切换时)
             ├─────────────────────────┤ ← RSP (仅在特权级切换时)
             ├─────────────────────────┤ ← RFLAGS
             ├─────────────────────────┤ ← CS
             ├─────────────────────────┤ ← RIP (返回地址)
             ├─────────────────────────┤ ← Error Code (部分异常)
             └─────────────────────────┘ ← 当前 RSP
```

---

## 2. early_idt_handler_array 的桩代码

### 向量 14 的桩代码

**源代码位置**：`arch/x86/kernel/head_64.S:488-505`

```asm
# early_idt_handler_array[14]:
	ENDBR                   # CET 间接分支保护
	# CPU 已经压入了 error code（缺页地址在 CR2）
	pushq $14               # 压入向量号
	jmp early_idt_handler_common  # 跳转到公共处理
```

### 栈帧状态（进入 early_idt_handler_common 前）

```
┌─────────────────────────┐ ← 异常发生前的 RSP
│  SS                      │ \
│  RSP                     │  |
│  RFLAGS                  │  | CPU 自动压入
│  CS                      │  |
│  RIP                     │  |
│  Error Code（#PF 专用）   │ /
│  Vector Number (14)      │ ← 桩代码压入
└─────────────────────────┘ ← 当前 RSP
```

### 桩代码的作用

| 作用 | 说明 |
|------|------|
| **统一接口** | 所有 32 个异常向量都跳转到同一个公共处理程序 |
| **传递向量号** | 将向量号压入栈，供 C 语言函数识别异常类型 |
| **错误码标准化** | 对于没有错误码的异常，手动压入假错误码 0 |

### 错误码压入规则

```c
// arch/x86/kernel/head_64.S:488-505
.rept NUM_EXCEPTION_VECTORS  # 重复 32 次
  .if ((EXCEPTION_ERRCODE_MASK >> i) & 1) == 0
    pushq $0  # 手动压入假错误码
  .endif
  pushq $i    # 压入向量号
  jmp early_idt_handler_common
  i = i + 1
.endr
```

**EXCEPTION_ERRCODE_MASK** = `0x00027d00`（只有 8、10、11、12、13、14、17、21 有错误码）

| 向量 | 异常名称 | 错误码 |
|------|---------|--------|
| 8 | #DF (Double Fault) | ✅ 有（总是 0） |
| 10 | #TS (Invalid TSS) | ✅ 有 |
| 11 | #NP (Segment Not Present) | ✅ 有 |
| 12 | #SS (Stack Fault) | ✅ 有 |
| 13 | #GP (General Protection) | ✅ 有 |
| 14 | #PF (Page Fault) | ✅ 有 |
| 17 | #AC (Alignment Check) | ✅ 有（总是 0） |
| 21 | #CP (Control Protection) | ✅ 有 |
| 其他 | - | ❌ 无（手动压入 0） |

---

## 3. early_idt_handler_common - 公共处理程序

### 源代码

**源代码位置**：`arch/x86/kernel/head_64.S:508-542`

```asm
SYM_CODE_START_LOCAL(early_idt_handler_common)
	UNWIND_HINT_IRET_REGS offset=16

	cld

	incl early_recursion_flag(%rip)

	/* The vector number is currently in the pt_regs->di slot. */
	pushq %rsi				/* pt_regs->si */
	movq 8(%rsp), %rsi			/* RSI = vector number */
	movq %rdi, 8(%rsp)			/* pt_regs->di = RDI */
	pushq %rdx				/* pt_regs->dx */
	pushq %rcx				/* pt_regs->cx */
	pushq %rax				/* pt_regs->ax */
	pushq %r8				/* pt_regs->r8 */
	pushq %r9				/* pt_regs->r9 */
	pushq %r10				/* pt_regs->r10 */
	pushq %r11				/* pt_regs->r11 */
	pushq %rbx				/* pt_regs->bx */
	pushq %rbp				/* pt_regs->bp */
	pushq %r12				/* pt_regs->r12 */
	pushq %r13				/* pt_regs->r13 */
	pushq %r14				/* pt_regs->r14 */
	pushq %r15				/* pt_regs->r15 */
	UNWIND_HINT_REGS

	movq %rsp,%rdi		/* RDI = pt_regs; RSI is already trapnr */
	call do_early_exception

	decl early_recursion_flag(%rip)
	jmp restore_regs_and_return_to_kernel
SYM_CODE_END(early_idt_handler_common)
```

### 功能分解

| 步骤 | 操作 | 说明 |
|------|------|------|
| 1 | `cld` | 清除方向标志（确保字符串操作向前） |
| 2 | `incl early_recursion_flag` | 递归计数器 +1（检测嵌套异常） |
| 3 | 保存所有通用寄存器 | 构建完整的 `pt_regs` 结构 |
| 4 | `movq %rsp, %rdi` | 第一个参数：pt_regs 指针 |
| 5 | `movq 8(%rsp), %rsi` | 第二个参数：向量号 |
| 6 | `call do_early_exception` | 调用 C 语言处理函数 |
| 7 | `decl early_recursion_flag` | 递归计数器 -1 |
| 8 | `jmp restore_regs_and_return_to_kernel` | 恢复寄存器并返回 |

### 栈帧布局（调用 do_early_exception 前）

```
┌─────────────────────────┐
│  SS                      │ \
│  RSP                     │  |
│  RFLAGS                  │  | CPU 自动压入
│  CS                      │  |
│  RIP                     │  |
│  Error Code              │ /
│  Vector Number (14)      │ ← 桩代码压入
│  RSI                     │ \
│  RDI                     │  |
│  RDX                     │  |
│  RCX                     │  |
│  RAX                     │  |
│  R8                      │  | early_idt_handler_common 压入
│  R9                      │  | （构成 pt_regs 结构）
│  R10                     │  |
│  R11                     │  |
│  RBX                     │  |
│  RBP                     │  |
│  R12                     │  |
│  R13                     │  |
│  R14                     │  |
│  R15                     │ /
└─────────────────────────┘ ← RSP（pt_regs 的起始地址）
```

### pt_regs 结构对应关系

```c
struct pt_regs {
	unsigned long r15;      // [RSP + 0]
	unsigned long r14;      // [RSP + 8]
	unsigned long r13;      // [RSP + 16]
	unsigned long r12;      // [RSP + 24]
	unsigned long bp;       // [RSP + 32]
	unsigned long bx;       // [RSP + 40]
	unsigned long r11;      // [RSP + 48]
	unsigned long r10;      // [RSP + 56]
	unsigned long r9;       // [RSP + 64]
	unsigned long r8;       // [RSP + 72]
	unsigned long ax;       // [RSP + 80]
	unsigned long cx;       // [RSP + 88]
	unsigned long dx;       // [RSP + 96]
	unsigned long si;       // [RSP + 104]
	unsigned long di;       // [RSP + 112]
	unsigned long orig_ax;  // [RSP + 120] ← 向量号存放位置
	unsigned long ip;       // [RSP + 128] ← CPU 压入的 RIP
	unsigned long cs;       // [RSP + 136]
	unsigned long flags;    // [RSP + 144] ← RFLAGS
	unsigned long sp;       // [RSP + 152] ← 原 RSP
	unsigned long ss;       // [RSP + 160]
};
```

---

## 4. do_early_exception() - C 语言处理

### 源代码

**源代码位置**：`arch/x86/kernel/head64.c:156-170`

```c
void __init do_early_exception(struct pt_regs *regs, int trapnr)
{
	if (trapnr == X86_TRAP_PF &&
	    early_make_pgtable(native_read_cr2()))
		return;

	if (IS_ENABLED(CONFIG_AMD_MEM_ENCRYPT) &&
	    trapnr == X86_TRAP_VC && handle_vc_boot_ghcb(regs))
		return;

	if (trapnr == X86_TRAP_VE && tdx_early_handle_ve(regs))
		return;

	early_fixup_exception(regs, trapnr);
}
```

### 函数参数

| 参数 | 寄存器 | 值 | 说明 |
|------|--------|----|----- |
| `regs` | RDI | RSP | 指向栈上的 pt_regs 结构 |
| `trapnr` | RSI | 14 | 异常向量号 |

### 功能概述

**do_early_exception() 是一个极简的应急异常处理程序**，只在内核启动最早期使用（从 x86_64_start_kernel 到 trap_init 之前）。

#### 设计原则

- ✅ **最小依赖**：不依赖任何复杂的内核子系统
- ✅ **关键任务**：只处理启动过程中必须处理的异常
- ❌ **功能有限**：大部分异常会导致 panic

#### 生命周期

```
启动早期          do_early_exception (临时使用)
  ↓
trap_init        开始被 asm_exc_* 系列函数替换
  ↓
cpu_init 完成    完全被生产级处理程序替换
```

> 📖 **详细分析**：do_early_exception 只是三代 IDT 处理程序中的第一代（Emergency Handlers），
> 完整的演进过程请参见：[IDT_HANDLER_EVOLUTION.md](./IDT_HANDLER_EVOLUTION.md)

### 异常处理分派

| 向量号 | 异常类型 | 处理函数 | 说明 |
|--------|---------|---------|------|
| 14 | #PF (Page Fault) | `early_make_pgtable()` | 动态建立页表 |
| 29 | #VC (VMM Communication) | `handle_vc_boot_ghcb()` | AMD SEV 虚拟化异常 |
| 20 | #VE (Virtualization Exception) | `tdx_early_handle_ve()` | Intel TDX 虚拟化异常 |
| 其他 | - | `early_fixup_exception()` | 尝试修复或 panic |

### 功能详解

#### 1. #PF (Page Fault) 处理

```c
if (trapnr == X86_TRAP_PF &&
    early_make_pgtable(native_read_cr2()))
	return;
```

**处理流程**：
1. 检查是否为 #PF（向量 14）
2. 调用 `native_read_cr2()` 读取缺页地址
3. 调用 `early_make_pgtable(address)` 动态建立页表
4. 如果成功返回 1，直接 return（异常已处理）
5. 如果失败返回 0，继续执行到 `early_fixup_exception()`

**early_make_pgtable() 的作用**：

```c
// arch/x86/kernel/head64.c
int __init early_make_pgtable(unsigned long address)
{
	// 1. 判断地址是否在合法范围内（内核地址空间）
	// 2. 从 _brk_end 分配新的页表页（不调用 kmalloc）
	// 3. 逐级检查和填充 PGD、P4D、PUD、PMD
	// 4. 建立 2MB 大页映射（使用 PSE 标志）
	// 5. 返回 1（成功）或 0（失败）
}
```

**功能限制**：
- ✅ 只能处理内核空间缺页（地址 >= __START_KERNEL_map）
- ✅ 只能建立 2MB 大页映射（不支持 4KB 小页）
- ❌ 不处理用户空间缺页
- ❌ 不支持按需分配（demand paging）
- ❌ 不支持写时复制（COW）
- ❌ 不支持 swap

**典型使用场景**：
- KASAN 影子内存访问
- 内核代码/数据段的初始映射
- vmalloc 区域的早期访问

#### 2. #VC (VMM Communication) 处理

```c
if (IS_ENABLED(CONFIG_AMD_MEM_ENCRYPT) &&
    trapnr == X86_TRAP_VC && handle_vc_boot_ghcb(regs))
	return;
```

**用途**：AMD SEV-ES/SEV-SNP 虚拟化环境

**背景**：
- SEV-ES（Secure Encrypted Virtualization - Encrypted State）加密虚拟机的寄存器状态
- Guest VM 执行某些敏感指令时会触发 #VC 异常
- 需要通过 GHCB（Guest-Hypervisor Communication Block）与 Hypervisor 通信

**处理流程**：
1. 检查是否启用了 AMD_MEM_ENCRYPT 配置
2. 检查是否为 #VC 异常（向量 29）
3. 调用 `handle_vc_boot_ghcb(regs)` 处理
4. 如果成功返回 true，异常已处理
5. 如果失败返回 false，继续到 early_fixup_exception

**典型触发场景**：
- CPUID 指令
- MSR 读写
- I/O 端口访问
- MMIO 访问

#### 3. #VE (Virtualization Exception) 处理

```c
if (trapnr == X86_TRAP_VE && tdx_early_handle_ve(regs))
	return;
```

**用途**：Intel TDX（Trust Domain Extensions）虚拟化环境

**背景**：
- TDX 提供硬件级别的虚拟机隔离
- TD（Trust Domain）访问某些资源时会触发 #VE 异常
- 需要通过 TDCALL 与 TDX Module 通信

**处理流程**：
1. 检查是否为 #VE 异常（向量 20）
2. 调用 `tdx_early_handle_ve(regs)` 处理
3. 如果成功返回 true，异常已处理
4. 如果失败返回 false，继续到 early_fixup_exception

**典型触发场景**：
- CPUID 指令
- I/O 端口访问
- MSR 访问
- HLT 指令

#### 4. early_fixup_exception() - 异常表修复

```c
// arch/x86/mm/extable.c
void __init early_fixup_exception(struct pt_regs *regs, int trapnr)
{
	const struct exception_table_entry *e;

	// 1. 在异常表中查找当前 IP 地址
	e = search_exception_tables(regs->ip);

	// 2. 如果找到修复代码
	if (e) {
		regs->ip = ex_fixup_addr(e);  // 跳转到修复地址
		return;
	}

	// 3. 如果未找到，打印错误信息并 panic
	early_printk("PANIC: early exception %02x rip %lx:%lx error %lx cr2 %lx\n",
	             trapnr, regs->cs, regs->ip, regs->orig_ax, read_cr2());
	die("Early exception", regs, trapnr);
}
```

**异常表机制**：
- **用途**：处理"预期的异常"（如探测性访问、用户空间拷贝）
- **结构**：编译时生成的 `exception_table_entry` 数组
- **原理**：每个可能出错的指令记录其地址和对应的修复代码地址
- **执行**：异常发生时，查表找到修复地址，修改 RIP 跳转执行

**示例**：
```c
// 内核代码可能探测性访问某个地址
asm volatile(
	"1: movl (%[ptr]), %[val]\n"
	"2:\n"
	_ASM_EXTABLE(1b, 2b)  // 如果 1b 处出错，跳转到 2b
	: [val] "=r" (val)
	: [ptr] "r" (ptr)
);
// 如果访问失败，直接跳过，不会 panic
```

**与生产级处理的区别**：
- ✅ 查异常表（两者相同）
- ❌ 不发送信号（无进程管理）
- ❌ 不生成详细 oops 报告
- ❌ 找不到修复代码时直接 panic（不尝试其他恢复方式）

### 功能对比总结

| 功能 | do_early_exception | 生产级处理 (exc_page_fault 等) |
|------|-------------------|-------------------------------|
| **代码行数** | ~20 行 | ~2000+ 行 |
| **处理异常数** | 4 类 (#PF, #VC, #VE, 其他) | 32+ 类（全部异常） |
| **#PF 功能** | 只能建立内核页表 | 完整虚拟内存管理 |
| **用户空间** | ❌ 不支持 | ✅ 支持 |
| **Demand Paging** | ❌ 不支持 | ✅ 支持 |
| **COW** | ❌ 不支持 | ✅ 支持 |
| **Swap** | ❌ 不支持 | ✅ 支持 |
| **信号发送** | ❌ 不支持 | ✅ 支持 (SIGSEGV, SIGILL) |
| **异常表** | ✅ 支持（简单） | ✅ 支持（完整） |
| **调试信息** | ❌ 最小 | ✅ 详细 oops 报告 |
| **IST 支持** | ❌ 无 | ✅ 有（关键异常） |
| **依赖** | 无 | 完整内核功能 |
| **生命周期** | 临时（启动早期） | 永久（运行时） |

---

## 5. 完整执行流程示例（#PF）

### 场景：访问未映射的内核地址

```
1. 用户访问地址 0xffff888000001000
     ↓
2. CPU 触发 #PF（向量 14）
     ↓
3. CPU 压入栈帧（SS、RSP、RFLAGS、CS、RIP、Error Code）
     ↓
4. CPU 读取 IDTR → 找到 idt_table
     ↓
5. CPU 读取 idt_table[14] → 找到 early_idt_handler_array[14]
     ↓
6. CPU 跳转到 early_idt_handler_array[14]
     ↓
7. 桩代码压入向量号 14
     ↓
8. 跳转到 early_idt_handler_common
     ↓
9. 压入所有寄存器（构建 pt_regs）
     ↓
10. 调用 do_early_exception(pt_regs, 14)
     ↓
11. do_early_exception 检测到 #PF
     ↓
12. 调用 early_make_pgtable(0xffff888000001000)
     ↓
13. 动态建立页表映射
     ↓
14. 返回到 early_idt_handler_common
     ↓
15. 恢复寄存器，执行 iret
     ↓
16. CPU 返回到触发异常的指令，重新执行
     ↓
17. 访问成功，继续执行
```

### 关键寄存器和内存状态

| 时刻 | RIP | RSP | CR2 | idt_table[14] |
|------|-----|-----|-----|---------------|
| 异常前 | 0xffffffff81234567 | 0xffffc90000003fe8 | - | early_idt_handler_array[14] |
| 异常后 | early_idt_handler_array[14] | 0xffffc90000003fc0 | 0xffff888000001000 | 不变 |
| 调用 C 函数 | do_early_exception | 0xffffc90000003f40 | 0xffff888000001000 | 不变 |
| iret 前 | early_idt_handler_array[14] | 0xffffc90000003fe8 | 0xffff888000001000 | 不变 |
| iret 后 | 0xffffffff81234567 | 0xffffc90000003fe8 | - | 不变 |

### 页表建立过程（early_make_pgtable）

```
1. 读取 CR2 = 0xffff888000001000（缺页地址）
     ↓
2. 拆分地址：
   PGD index = (0xffff888000001000 >> 39) & 0x1FF = 0x111
   P4D index = (0xffff888000001000 >> 30) & 0x1FF = 0x020
   PUD index = (0xffff888000001000 >> 21) & 0x1FF = 0x000
   PMD index = (0xffff888000001000 >> 12) & 0x1FF = 0x001
     ↓
3. 检查每级页表是否存在，不存在则分配
     ↓
4. 填充页表项（PTE）：
   PTE[0x001] = (物理地址) | PAGE_KERNEL
     ↓
5. 建立映射：0xffff888000001000 → 物理地址
     ↓
6. 返回 1（成功）
```

---

## 性能和安全考量

### 性能优化

| 优化点 | 说明 |
|--------|------|
| **最小化异常** | 早期阶段只启用必需的异常处理 |
| **无 IST 切换** | 避免栈切换开销（直接使用当前栈） |
| **简化处理** | 只处理 #PF、#VC、#VE，其他异常尽量避免 |
| **动态页表** | 按需建立页表，减少启动时间 |

### 安全加固

| 加固措施 | 说明 |
|----------|------|
| **递归检测** | `early_recursion_flag` 检测嵌套异常 |
| **异常表** | 限制可修复异常的范围 |
| **只读 IDT** | 后期将 idt_table 设为只读（防止篡改） |
| **CEA 映射** | IDT 映射到 CPU Entry Area（防止泄漏） |

---

## 返回导航

- [返回主文档](./IDT_SETUP_EARLY_HANDLER_DETAILED_ANALYSIS.md)
- [查看完整向量表](./IDT_COMPLETE_VECTOR_TABLE.md)
- [查看数据结构关系](./IDT_DATA_STRUCTURES_RELATIONSHIP.md)
- [查看文档索引](./DOCUMENT_INDEX.md)
