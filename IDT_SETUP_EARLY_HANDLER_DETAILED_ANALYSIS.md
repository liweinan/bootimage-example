# idt_setup_early_handler() 函数详细分析

**版本**: 1.3
**日期**: 2026-02-17
**作者**: Linux 内核启动文档项目
**更新内容**:
- v1.3: 完成全文重组，所有章节按执行顺序组织（编译→写入→加载→使用），消除重复内容
- v1.2: 添加执行顺序总览和关键概念澄清（1.0 节），明确区分写入 vs 加载操作
- v1.1: 添加核心数据结构关系概览（2.0 节），优化三个核心变量的关系说明
- v1.0: 初始版本

> 📚 **文档导航**: [返回总索引](DOCUMENT_INDEX.md) | [IDT 演进](LINUX_KERNEL_IDT_EVOLUTION.md) | [内核启动](LINUX_KERNEL_INIT.md)

---

## 目录

1. [执行顺序总览](#1-执行顺序总览)
2. [阶段 1：编译时准备](#2-阶段-1编译时准备)
3. [阶段 2：运行时写入 idt_table](#3-阶段-2运行时写入-idt_table)
4. [阶段 3：加载 IDT 到 CPU](#4-阶段-3加载-idt-到-cpu)
5. [阶段 4：运行时使用](#5-阶段-4运行时使用)
6. [完整代码调用链](#6-完整代码调用链)
7. [为什么是 32 个向量？](#7-为什么是-32-个向量)

---

## 1. 执行顺序总览

### 1.1 时间线概览

**关键纠正**：很多文档容易混淆"写入 idt_table"和"加载 IDT"，这是两个完全不同的操作！

```
┌─────────────────────────────────────────────────────────────────┐
│  阶段 1：编译时准备（内核编译阶段）                              │
├─────────────────────────────────────────────────────────────────┤
│  🎯 目的：在编译阶段准备好所有必需的数据结构                     │
│           使得运行时可以快速初始化 IDT                           │
│                                                                  │
│  ① early_idt_handler_array[32] 由汇编代码 .rept 生成            │
│     位置：arch/x86/kernel/head_64.S                              │
│     结果：32 个函数入口（地址在链接时确定）                       │
│                                                                  │
│  ② idt_table[256] 定义为全局数组                                │
│     位置：arch/x86/kernel/idt.c:173                              │
│     结果：分配 4096 字节（BSS 段，初始全为 0）                    │
│                                                                  │
│  ③ idt_descr 定义并初始化                                       │
│     位置：arch/x86/kernel/idt.c:175-178                          │
│     结果：.address = &idt_table, .size = 4095                   │
└─────────────────────────────────────────────────────────────────┘
                        ↓  内核启动
┌─────────────────────────────────────────────────────────────────┐
│  阶段 2：运行时写入 idt_table（idt_setup_early_handler 执行）    │
├─────────────────────────────────────────────────────────────────┤
│  🎯 目的：在内核启动早期填充 IDT 表，使 CPU 能够处理异常         │
│           特别是 #PF（缺页异常），用于动态建立页表               │
│                                                                  │
│  调用时机：x86_64_start_kernel() → idt_setup_early_handler()    │
│                                                                  │
│  ④ for (i = 0; i < 32; i++)                                     │
│       set_intr_gate(i, early_idt_handler_array[i])              │
│         │                                                        │
│         └─→ init_idt_data(&data, i, addr)                       │
│              └─ 创建临时结构：vector=i, addr=..., type=0xE      │
│         │                                                        │
│         └─→ idt_setup_from_table(idt_table, &data, 1, false)    │
│              └─→ idt_init_desc(&desc, &data)                    │
│                   └─ 构建 16 字节的 gate_desc                    │
│              │                                                   │
│              └─→ write_idt_entry(idt_table, i, &desc)           │
│                   └─ idt_table[i] = desc  ← 关键！写入内存！     │
│                                                                  │
│  结果：idt_table[0..31] 现在包含 32 个完整的门描述符            │
└─────────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────────┐
│  阶段 3：加载 IDT 到 CPU（仍在 idt_setup_early_handler 中）      │
├─────────────────────────────────────────────────────────────────┤
│  🎯 目的：通知 CPU 新的 IDT 位置                                 │
│           从此刻起 CPU 使用 idt_table 处理所有异常               │
│                                                                  │
│  ⑤ load_idt(&idt_descr)                                         │
│       │                                                          │
│       └─→ asm volatile("lidt %0"::"m" (idt_descr.size))         │
│            │                                                     │
│            └─ CPU 执行 lidt 指令：                               │
│                IDTR.base  = idt_descr.address = &idt_table      │
│                IDTR.limit = idt_descr.size = 4095               │
│                                                                  │
│  结果：CPU 的 IDTR 寄存器现在指向 idt_table                      │
│  注意：这一步不修改 idt_table，只是告诉 CPU 在哪里找它！         │
└─────────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────────┐
│  阶段 4：运行时使用（异常/中断发生时）                           │
├─────────────────────────────────────────────────────────────────┤
│  🎯 目的：当异常发生时，CPU 自动查询 IDT 并跳转到处理程序        │
│           实现异常的自动分发和处理                               │
│                                                                  │
│  ⑥ CPU 触发异常（如 #PF，向量 14）                              │
│       │                                                          │
│       ├─ 读取 IDTR.base（= &idt_table）                         │
│       ├─ 计算地址：IDTR.base + 14 × 16                          │
│       ├─ 读取 idt_table[14]（16 字节）                          │
│       ├─ 提取处理程序地址：offset_high | offset_middle | low    │
│       └─ 跳转到该地址（early_idt_handler_array[14]）            │
│                                                                  │
│  结果：CPU 执行异常处理代码                                      │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 关键概念澄清

| 操作 | 谁执行 | 对什么操作 | 结果 |
|------|-------|----------|------|
| **写入** idt_table | `write_idt_entry()` | idt_table[i] | 内存中的 idt_table 被填充 |
| **加载** IDT | `lidt` 指令 | IDTR 寄存器 | CPU 知道 idt_table 在哪里 |
| **读取** idt_table | CPU 硬件 | idt_table[向量号] | 获取处理程序地址 |

**常见误解**：
- ❌ `load_idt()` 写入 idt_table
- ✅ `write_idt_entry()` 写入 idt_table
- ✅ `load_idt()` 只是告诉 CPU idt_table 的位置

### 1.3 函数源代码

**`idt_setup_early_handler()` 源代码**（`arch/x86/kernel/idt.c:317-331`）：

```c
void __init idt_setup_early_handler(void)
{
	int i;

	// 步骤 1：写入 idt_table（阶段 2）
	for (i = 0; i < NUM_EXCEPTION_VECTORS; i++)
		set_intr_gate(i, early_idt_handler_array[i]);  // ← 写入操作
#ifdef CONFIG_X86_32
	for ( ; i < NR_VECTORS; i++)
		set_intr_gate(i, early_ignore_irq);
#endif

	// 步骤 2：加载到 IDTR（阶段 3）
	load_idt(&idt_descr);  // ← 加载操作，不是写入！
}
```

### 1.4 调用时机

```c
// arch/x86/kernel/head64.c:273
asmlinkage __visible void __init __noreturn x86_64_start_kernel(char *real_mode_data)
{
    kasan_early_init();
    __native_tlb_flush_global(...);

    idt_setup_early_handler();  // ← 在这里调用（早期内核初始化）

    tdx_early_init();
    // ...
}
```

---

## 2. 阶段 1：编译时准备

在内核编译阶段，以下三个核心数据结构被定义并分配内存：

###2.1 early_idt_handler_array - 异常处理程序数组（汇编生成）

**源代码**（`arch/x86/kernel/head_64.S:488-505`）：

```asm
SYM_CODE_START(early_idt_handler_array)
	i = 0
	.rept NUM_EXCEPTION_VECTORS      # 重复 32 次
	.if ((EXCEPTION_ERRCODE_MASK >> i) & 1) == 0
		pushq $0                 # 手动压入假错误码
	.endif
	pushq $i                         # 压入向量号
	jmp early_idt_handler_common     # 跳转到公共处理
	i = i + 1
	.fill early_idt_handler_array + i*EARLY_IDT_HANDLER_SIZE - ., 1, 0xcc
	.endr
SYM_CODE_END(early_idt_handler_array)

// 常量定义
#define NUM_EXCEPTION_VECTORS  32
#define EARLY_IDT_HANDLER_SIZE 10  // 或 12 字节（取决于是否有错误码）
```

**核心特点**：

| 属性 | 值 | 说明 |
|------|-----|------|
| **数量** | 32 个 | 对应向量 0-31（CPU 异常） |
| **类型** | 汇编代码桩 | 每个桩跳转到 `early_idt_handler_common` |
| **大小** | 每个 10-12 字节 | 固定大小，便于数组寻址 |
| **生成方式** | `.rept` 宏 | **编译时生成**，不是运行时 |
| **作用** | 统一栈帧 + 跳转 | 提供统一的异常入口 |

**数组布局**：

```
地址                              | 内容
----------------------------------|----------------------------------
early_idt_handler_array[0]        | 向量 0 的桩（10-12 字节）
early_idt_handler_array[1]        | 向量 1 的桩（10-12 字节）
...                               | ...
early_idt_handler_array[31]       | 向量 31 的桩（10-12 字节）
```

**错误码处理机制**：

```
向量号 | 异常名称 | CPU 自动压入错误码？ | 桩的行为
-------|---------|-------------------|----------
0      | #DE     | 否                | 手动 pushq $0
1      | #DB     | 否                | 手动 pushq $0
8      | #DF     | 是（总是 0）       | 不压入
10     | #TS     | 是                | 不压入
11     | #NP     | 是                | 不压入
12     | #SS     | 是                | 不压入
13     | #GP     | 是                | 不压入
14     | #PF     | 是                | 不压入
17     | #AC     | 是                | 不压入
```

**示例代码**：

```asm
# early_idt_handler_array[0] (#DE - Divide Error):
	ENDBR                   # 3 字节（如果启用 CET）
	pushq $0                # 2 字节（Dummy error code）
	pushq $0                # 2 字节（Vector number）
	jmp early_idt_handler_common  # 5 字节

# early_idt_handler_array[14] (#PF - Page Fault):
	ENDBR                   # 3 字节
	# CPU 已经压入了 error code，不需要手动压入
	pushq $14               # 2 字节（Vector number）
	jmp early_idt_handler_common  # 5 字节
```

**关键常量**：

```c
// arch/x86/include/asm/irq_vectors.h
#define NUM_EXCEPTION_VECTORS  32  // CPU 异常向量数量

// arch/x86/kernel/head_64.S
#define EARLY_IDT_HANDLER_SIZE 10  // 或 12，取决于 CET
```

### 2.2 idt_table - IDT 表本体（BSS 段分配）

**源代码**（`arch/x86/kernel/idt.c:173`）：

```c
/* Must be page-aligned because the real IDT is used in the cpu entry area */
static gate_desc idt_table[IDT_ENTRIES] __page_aligned_bss;

// 常量定义
#define IDT_ENTRIES  256
```

**属性说明**：

| 属性 | 值 | 说明 |
|------|-----|------|
| **类型** | `gate_desc[256]` | 门描述符数组 |
| **大小** | 4096 字节 | 256 × 16 = 1 个内存页 |
| **对齐** | `__page_aligned_bss` | 必须页对齐（4KB 边界） |
| **段** | BSS | **编译时分配，初始值全为 0** |
| **可见性** | `static` | 文件内部可见 |

**gate_desc 结构定义**（`arch/x86/include/asm/desc_defs.h:79-91`）：

```c
struct gate_desc {
	u16		offset_low;      // 处理程序地址的低 16 位
	u16		segment;         // 代码段选择子（__KERNEL_CS）
	struct idt_bits	bits;    // 控制位（IST、DPL、Type、P）
	u16		offset_middle;   // 处理程序地址的中间 16 位
	u32		offset_high;     // 处理程序地址的高 32 位
	u32		reserved;        // 保留，必须为 0
} __attribute__((packed));
```

**idt_bits 结构**：

```c
struct idt_bits {
	u16		ist	: 3,    // Interrupt Stack Table 索引（0-7）
			zero	: 5,    // 必须为 0
			type	: 5,    // 门类型（Interrupt/Trap/Task）
			dpl	: 2,    // Descriptor Privilege Level（0 或 3）
			p	: 1;    // Present 位（必须为 1）
} __attribute__((packed));
```

**内存布局**（单个 gate_desc，共 16 字节）：

```
偏移量 | 大小 | 字段               | 说明
-------|------|--------------------|-----------------------------------------
+0     | 2B   | offset_low         | 处理程序地址 [15:0]
+2     | 2B   | segment            | __KERNEL_CS = 0x0010
+4     | 2B   | bits (IST/Type/DPL/P) | 控制位
+6     | 2B   | offset_middle      | 处理程序地址 [31:16]
+8     | 4B   | offset_high        | 处理程序地址 [63:32]
+12    | 4B   | reserved           | 必须为 0
```

**编译时状态**：

```
idt_table[0..255] = 全部为 0（BSS 段特性）
```

### 2.3 idt_descr - IDT 描述符（编译时初始化）

**源代码**（`arch/x86/kernel/idt.c:175-178`）：

```c
static struct desc_ptr idt_descr __ro_after_init = {
	.size		= IDT_TABLE_SIZE - 1,    // 4095
	.address	= (unsigned long) idt_table,
};

// 常量定义
#define IDT_TABLE_SIZE  (IDT_ENTRIES * sizeof(gate_desc))  // 4096
```

**desc_ptr 结构**（`arch/x86/include/asm/desc_defs.h:23-26`）：

```c
struct desc_ptr {
	unsigned short size;        // IDT 表大小 - 1（limit）
	unsigned long address;      // IDT 表的线性地址（base）
} __attribute__((packed));
```

**编译时初始化的实际值**：

| 字段 | 值 | 对应 IDTR 字段 | 说明 |
|------|-----|---------------|------|
| `size` | **4095** | IDTR.limit | 最大可访问偏移量 |
| `address` | `&idt_table` | IDTR.base | 链接时确定地址 |

**为什么 size = 4095 而不是 4096？**

x86 硬件规定：IDTR.limit = 表的**最大可访问偏移量** = 字节数 - 1
- 表范围：0 ~ 4095（共 4096 字节）
- limit = 4095（最大偏移）

**`__ro_after_init` 属性**：
- 编译时可写（用于初始化）
- 运行时初始化完成后设置为只读（安全加固）

### 2.4 idt_descr 和 idt_table 的关系详解

#### 核心关系：指针 vs 数据

```
┌─────────────────────────────────────────────────────────────────┐
│  idt_descr（10 字节的"元信息"）                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ struct desc_ptr {                                         │   │
│  │     unsigned short size;     // 4095                     │   │
│  │     unsigned long address;   // &idt_table               │   │
│  │ };                                                        │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  作用：告诉 CPU "IDT 表在哪里，有多大"                           │
│  类比：图书馆的地址和规模信息                                     │
└─────────────────────────────────────────────────────────────────┘
                           │
                           │ .address 字段指向
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│  idt_table[256]（4096 字节的"实际数据"）                         │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ [0]   = gate_desc { offset, segment, bits, ... }  (16B) │   │
│  │ [1]   = gate_desc { offset, segment, bits, ... }  (16B) │   │
│  │ [2]   = gate_desc { offset, segment, bits, ... }  (16B) │   │
│  │ ...                                                       │   │
│  │ [255] = gate_desc { offset, segment, bits, ... }  (16B) │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  作用：存储 256 个中断/异常的实际处理程序信息                     │
│  类比：图书馆里的实际书架和书籍                                   │
└─────────────────────────────────────────────────────────────────┘
```

#### 详细对比

| 对比项 | idt_table | idt_descr |
|--------|----------|-----------|
| **数据类型** | `gate_desc[256]` | `struct desc_ptr` |
| **大小** | 4096 字节 (256 × 16) | 10 字节 (2 + 8) |
| **作用** | 存储 256 个门描述符（实际数据） | 存储 idt_table 的地址和大小（元信息） |
| **内容** | 256 个异常/中断处理程序的详细信息 | `.size = 4095`, `.address = &idt_table` |
| **被谁使用** | CPU 硬件（通过 IDTR 访问） | `lidt` 指令（用于加载 IDTR） |
| **可修改性** | 运行时可写入（后期设为只读） | 编译时初始化（后期设为只读） |
| **类比** | 图书馆的书架和书籍 | 图书馆的地址和规模 |

#### 内存布局示例

假设 `idt_table` 的地址是 `0xffffffff82000000`：

```
内存地址                    内容
-----------------------------------------------------------------
idt_descr 所在位置（假设 0xffffffff81fff000）:
  +0x00  0x0F 0xFF           ← size = 4095 (2 字节)
  +0x02  0x00 0x00 0x20 0x82 ← address = 0xffffffff82000000 (8 字节)
         0xFF 0xFF 0xFF 0xFF

-----------------------------------------------------------------

idt_table 所在位置（0xffffffff82000000）:
  +0x0000  [16 字节]  ← idt_table[0]   (向量 0: #DE)
  +0x0010  [16 字节]  ← idt_table[1]   (向量 1: #DB)
  +0x0020  [16 字节]  ← idt_table[2]   (向量 2: #NMI)
  ...
  +0x0E00  [16 字节]  ← idt_table[14]  (向量 14: #PF)
  ...
  +0x0FF0  [16 字节]  ← idt_table[255] (向量 255: SPURIOUS_APIC)
```

#### 使用流程

```
1. 编译时：
   idt_descr.address = &idt_table;  // 指向 idt_table
   idt_descr.size = 4095;            // idt_table 的大小 - 1

2. 运行时写入：
   write_idt_entry(idt_table, 14, &desc);  // 直接写入 idt_table[14]

3. 加载到 CPU：
   load_idt(&idt_descr);  // 将 idt_descr 的内容加载到 IDTR

   CPU 执行：lidt (idt_descr)
   结果：
     IDTR.limit = idt_descr.size = 4095
     IDTR.base  = idt_descr.address = &idt_table

4. CPU 使用：
   异常发生 → CPU 读取 IDTR.base → 找到 idt_table → 读取对应条目
```

#### 为什么需要 idt_descr？

**不能直接加载 idt_table 的原因**：

1. **x86 指令限制**：
   - `lidt` 指令要求一个 10 字节的内存操作数
   - 格式：2 字节 limit + 8 字节 base address
   - 不能直接传递 idt_table 数组

2. **分离关注点**：
   - `idt_table` = 数据（可以被修改、替换）
   - `idt_descr` = 元信息（指向数据的位置）
   - 允许在不同场景下使用不同的 IDT 表

3. **CPU 硬件设计**：
   - IDTR 寄存器本身就是 10 字节（2 字节 limit + 8 字节 base）
   - `lidt` 指令就是为了填充 IDTR 而设计的

#### 完整关系图

```
编译阶段完成的准备：

┌─────────────────────────────────────────────────────────┐
│ early_idt_handler_array[32]                              │
│ ├─ [0] = 向量 0 的汇编桩（地址如 0xffffffff81002a00）    │
│ ├─ [1] = 向量 1 的汇编桩                                 │
│ └─ [31] = 向量 31 的汇编桩                               │
└─────────────────────────────────────────────────────────┘
                     ↓ 运行时写入
┌─────────────────────────────────────────────────────────┐
│ idt_table[256] ⟸ 实际数据（4096 字节）                   │
│ ├─ [0..255] = 全部为 0（BSS 段，等待填充）               │
└─────────────────────────────────────────────────────────┘
                     ↑ .address 指向
┌─────────────────────────────────────────────────────────┐
│ idt_descr ⟸ 元信息（10 字节）                            │
│ ├─ .size = 4095                                          │
│ └─ .address = &idt_table                                 │
└─────────────────────────────────────────────────────────┘
                     ↓ lidt 指令读取
┌─────────────────────────────────────────────────────────┐
│ IDTR 寄存器（CPU 硬件，10 字节）                          │
│ ├─ .limit = 4095（从 idt_descr.size 复制）               │
│ └─ .base = &idt_table（从 idt_descr.address 复制）       │
└─────────────────────────────────────────────────────────┘
```

---

## 3. 阶段 2：运行时写入 idt_table

当 `idt_setup_early_handler()` 函数运行时，通过循环调用 `set_intr_gate()` 将 32 个异常处理程序地址写入 `idt_table`。

### 3.1 主循环：设置 32 个异常向量

**源代码**（`arch/x86/kernel/idt.c:323-324`）：

```c
void __init idt_setup_early_handler(void)
{
	int i;

	for (i = 0; i < NUM_EXCEPTION_VECTORS; i++)
		set_intr_gate(i, early_idt_handler_array[i]);  // ← 写入操作
	// ...
}
```

**循环过程**：

```
迭代 0: set_intr_gate(0, early_idt_handler_array[0])   → 写入 idt_table[0]
迭代 1: set_intr_gate(1, early_idt_handler_array[1])   → 写入 idt_table[1]
迭代 2: set_intr_gate(2, early_idt_handler_array[2])   → 写入 idt_table[2]
...
迭代 31: set_intr_gate(31, early_idt_handler_array[31]) → 写入 idt_table[31]
```

### 3.2 set_intr_gate() - 封装层

**源代码位置**：`arch/x86/kernel/idt.c:206-213`

```c
static __init void set_intr_gate(unsigned int n, const void *addr)
{
	struct idt_data data;

	init_idt_data(&data, n, addr);

	idt_setup_from_table(idt_table, &data, 1, false);
}
```

**功能**：
1. 创建临时的 `idt_data` 结构
2. 填充向量号和处理程序地址
3. 调用 `idt_setup_from_table()` 执行实际写入

### 3.3 init_idt_data() - 初始化 idt_data 结构

**idt_data 结构**（`arch/x86/include/asm/desc.h`）：

```c
struct idt_data {
	unsigned int	vector;      // 向量号（0-255）
	unsigned int	segment;     // 代码段选择子
	struct idt_bits	bits;        // 控制位
	const void	*addr;       // 处理程序地址
};
```

**init_idt_data() 宏**：

```c
#define init_idt_data(data, n, addr)			\
do {							\
	(data)->vector	= (n);				\
	(data)->bits.ist = DEFAULT_STACK;		\
	(data)->bits.type = GATE_INTERRUPT;		\
	(data)->bits.dpl = DPL0;			\
	(data)->bits.p	= 1;				\
	(data)->addr	= (addr);			\
	(data)->segment	= __KERNEL_CS;			\
} while (0)
```

**示例：设置向量 14（#PF）**

```c
// 调用：set_intr_gate(14, early_idt_handler_array[14]);

// 步骤 1：初始化 idt_data
struct idt_data data;
init_idt_data(&data, 14, early_idt_handler_array[14]);

// 展开后：
data.vector   = 14;
data.bits.ist = 0;                              // 不使用 IST
data.bits.type = GATE_INTERRUPT;                // 0xE
data.bits.dpl  = DPL0;                          // 0（只能从 Ring 0 触发）
data.bits.p    = 1;                             // Present
data.addr      = early_idt_handler_array[14];   // 处理程序地址
data.segment   = __KERNEL_CS;                   // 0x0010
```

### 3.4 idt_setup_from_table() - 批量写入

**源代码位置**：`arch/x86/kernel/idt.c:193-204`

```c
static __init void
idt_setup_from_table(gate_desc *idt, const struct idt_data *t, int size, bool sys)
{
	gate_desc desc;

	for (; size > 0; t++, size--) {
		idt_init_desc(&desc, t);
		write_idt_entry(idt, t->vector, &desc);
		if (sys)
			set_bit(t->vector, system_vectors);
	}
}
```

**参数**：
- `idt` = `idt_table`（目标 IDT 表）
- `t` = `&data`（idt_data 结构指针）
- `size` = 1（只写入 1 个条目）
- `sys` = `false`（不是系统门，DPL = 0）

**步骤**：
1. 调用 `idt_init_desc()` 构建门描述符
2. 调用 `write_idt_entry()` 写入 idt_table

**实际写入的数据**：

每次调用 `idt_setup_from_table()` 会向 `idt_table[i]` 写入 **16 字节**的门描述符数据：

```
idt_table 内存布局（每个条目 16 字节）：

偏移   字段                大小    内容示例（向量 14, #PF）
-----  -----------------  ------  ----------------------------------
+0     offset_low          2 字节  0x2a80 （处理程序地址低 16 位）
+2     segment             2 字节  0x0010 （__KERNEL_CS）
+4     bits (IST/type/DPL) 2 字节  0x8E00 （详见下方位字段分解）
+6     offset_middle       2 字节  0x8100 （处理程序地址中 16 位）
+8     offset_high         4 字节  0xffffffff （处理程序地址高 32 位）
+12    reserved            4 字节  0x00000000 （必须为 0）

总计：16 字节
```

**bits 字段位分解**（偏移 +4 的 2 字节 = 0x8E00）：

```
bits 的实际值: 0x8E00 (小端序存储)

二进制表示: 1000 1110 0000 0000
            ││││ ││││ │││└─┴─ IST[2:0]  = 000 (不使用 IST)
            ││││ ││││ ││└──── zero[4:3] = 00  (必须为 0)
            ││││ ││││ │└───── zero[2:0] = 000 (必须为 0)
            ││││ │││└─┴────── type[4:0] = 01110 (0xE, Interrupt Gate)
            ││││ ││└───────── DPL[1:0]  = 00 (Ring 0)
            ││││ │└────────── P          = 1  (Present)
            ││││ └─────────── (高字节的高 7 位未使用)
            │││└─────────────
            ││└──────────────
            │└───────────────
            └────────────────

关键值：
- type = 0xE (14): Interrupt Gate（中断门）
- DPL  = 0:       Ring 0 特权级（内核态）
- P    = 1:       Present（有效）
- IST  = 0:       不使用 IST（普通内核栈）
```

**完整的 16 字节十六进制数据示例**：

假设 `early_idt_handler_array[14]` 的地址是 `0xffffffff81002a80`：

```
idt_table[14] 的 16 字节内容（小端序）：

地址偏移  +0  +1  +2  +3  +4  +5  +6  +7  +8  +9  +A  +B  +C  +D  +E  +F
数据     80  2A  10  00  00  8E  00  81  FF  FF  FF  FF  00  00  00  00
         └──┬──┘ └──┬──┘ └──┬──┘ └──┬──┘ └─────┬─────┘ └─────┬─────┘
         offset  segment  bits   offset    offset_high   reserved
          _low             (IST)  _middle
                          (type)
                          (DPL)
                           (P)

字段解释：
[+0..+1] 0x2A80       = offset_low    (地址 [15:0])
[+2..+3] 0x0010       = segment       (__KERNEL_CS)
[+4..+5] 0x8E00       = bits          (IST=0, type=0xE, DPL=0, P=1)
[+6..+7] 0x8100       = offset_middle (地址 [31:16])
[+8..+B] 0xFFFFFFFF   = offset_high   (地址 [63:32])
[+C..+F] 0x00000000   = reserved      (必须为 0)

完整地址重组：
0xFFFFFFFF (高32位) | 0x8100 (中16位) | 0x2A80 (低16位)
= 0xFFFFFFFF81002A80 ← 这就是 early_idt_handler_array[14] 的地址
```

**多个向量的实际数据对比**：

```
向量 0 (#DE): idt_table[0] = 16 字节
  处理程序地址: 0xffffffff81002a00
  80 2A 10 00 00 8E 00 81 FF FF FF FF 00 00 00 00

向量 1 (#DB): idt_table[1] = 16 字节
  处理程序地址: 0xffffffff81002a0c (偏移 +12 字节)
  0C 2A 10 00 00 8E 0C 81 FF FF FF FF 00 00 00 00

向量 14 (#PF): idt_table[14] = 16 字节
  处理程序地址: 0xffffffff81002a80
  80 2A 10 00 00 8E 00 81 FF FF FF FF 00 00 00 00

向量 31: idt_table[31] = 16 字节
  处理程序地址: 0xffffffff81002b40
  40 2B 10 00 00 8E 40 81 FF FF FF FF 00 00 00 00

所有向量的共同点：
- segment 都是 0x0010 (__KERNEL_CS)
- bits 都是 0x8E00 (Interrupt Gate, DPL=0, P=1)
- reserved 都是 0x00000000
- 只有 offset 字段不同（指向不同的处理程序）
```

### 3.5 idt_init_desc() - 构建门描述符

**源代码位置**：`arch/x86/kernel/idt.c:64-73`

```c
static inline void idt_init_desc(gate_desc *gate, const struct idt_data *d)
{
	unsigned long addr = (unsigned long) d->addr;

	gate->offset_low	= (u16) addr;
	gate->segment		= (u16) d->segment;
	gate->bits		= d->bits;
	gate->offset_middle	= (u16) (addr >> 16);
	gate->offset_high	= (u32) (addr >> 32);
	gate->reserved		= 0;
}
```

**功能**：将 64 位处理程序地址拆分成三个字段：

```c
// 假设 early_idt_handler_array[14] 的地址是 0xffffffff81002a80

gate_desc desc;

desc.offset_low    = 0x2a80;           // 地址 [15:0]
desc.segment       = 0x0010;           // __KERNEL_CS
desc.bits.ist      = 0;
desc.bits.type     = 0xE;              // Interrupt Gate
desc.bits.dpl      = 0;                // Ring 0 only
desc.bits.p        = 1;                // Present
desc.offset_middle = 0x8100;           // 地址 [31:16]
desc.offset_high   = 0xffffffff;       // 地址 [63:32]
desc.reserved      = 0;
```

### 3.6 write_idt_entry() - 原子写入 idt_table

**源代码位置**：`arch/x86/include/asm/desc.h:177-180`

```c
static inline void write_idt_entry(gate_desc *idt, int entry, const gate_desc *gate)
{
	memcpy(&idt[entry], gate, sizeof(*gate));
}
```

**等价于**：

```c
idt_table[14] = desc;  // 原子地拷贝 16 字节
```

**关键点**：
- ✅ 这是**真正的写入操作**
- ✅ 写入目标：`idt_table[entry]`（内存）
- ✅ 写入大小：16 字节（一个 gate_desc）
- ❌ **不是** load_idt()（那是加载到 IDTR）

### 3.7 32 位系统的额外处理

```c
#ifdef CONFIG_X86_32
for ( ; i < NR_VECTORS; i++)
	set_intr_gate(i, early_ignore_irq);
#endif
```

**仅在 32 位系统（x86-32）上编译**：
- `NR_VECTORS` = 256
- 将剩余的向量（32-255）都指向 `early_ignore_irq`

**为什么 64 位系统不需要？**
- 64 位系统在此阶段**硬件中断仍然禁用**
- 不会收到 IRQ 32-255
- 这些向量会在后续的 `idt_setup_apic_and_irq_gates()` 中填充

### 3.8 阶段 2 完成后的状态

```
idt_table[0]  → early_idt_handler_array[0]  (#DE)
idt_table[1]  → early_idt_handler_array[1]  (#DB)
idt_table[2]  → early_idt_handler_array[2]  (NMI)
...
idt_table[13] → early_idt_handler_array[13] (#GP)
idt_table[14] → early_idt_handler_array[14] (#PF)
...
idt_table[31] → early_idt_handler_array[31] (Reserved)
idt_table[32..255] → 0（尚未设置，64 位）或 early_ignore_irq（32 位）
```

**完整调用链**：

```
set_intr_gate(i, early_idt_handler_array[i])
    ↓
init_idt_data(&data, i, addr)
    ↓
idt_setup_from_table(idt_table, &data, 1, false)
    ↓
idt_init_desc(&desc, &data)  ← 构建门描述符
    ↓
write_idt_entry(idt_table, i, &desc)  ← 写入 idt_table[i]
    ↓
idt_table[i] = desc  ← 内存写入完成
```

### 3.9 完整的 IDT 表内容清单（256 个向量）

**重要说明**：`idt_setup_early_handler()` 只是 IDT 初始化的**第一步**，后续还有多个阶段会继续填充和覆盖 idt_table 的内容。

#### 初始化阶段时间线

```
阶段 0：编译后状态
  idt_table[0..255] = 全部为 0（BSS 段）

阶段 1：idt_setup_early_handler() [最早期，x86_64_start_kernel]
  └─ 填充向量 0-31 → early_idt_handler_array[0..31]

阶段 2：idt_setup_early_traps() [trap_init() 开始]
  └─ 覆盖部分向量：#DB(1), #BP(3), #PF(14, 仅 x86-32), #VE(20)

阶段 3：idt_setup_early_pf() [仅 x86-64]
  └─ 覆盖向量 14 (#PF) → asm_exc_page_fault

阶段 4：idt_setup_traps() [trap_init() 中期]
  └─ 覆盖所有异常向量（0-31）+ INT 0x80

阶段 5：idt_setup_apic_and_irq_gates() [trap_init() 完成]
  └─ 填充向量 32-255（IRQ、APIC、系统向量）
```

#### ❓ 为什么前 32 个向量要填充两次？

**阶段 1 vs 阶段 4 的关键区别**：

| 对比项 | 阶段 1：idt_setup_early_handler() | 阶段 4：idt_setup_traps() |
|--------|----------------------------------|--------------------------|
| **调用时机** | 极早期（x86_64_start_kernel） | trap_init()（cpu_init() 之后） |
| **处理程序** | early_idt_handler_array[] | 各异常专用处理程序（asm_exc_*） |
| **处理方式** | 所有异常 → early_idt_handler_common | 每个异常有独立处理程序 |
| **IST 支持** | ❌ 不支持（TSS 未初始化） | ✅ 支持（#DF, #NMI, #MC 等使用 IST） |
| **功能** | 临时应急，仅支持基本异常处理 | 完整功能，支持复杂异常处理 |
| **主要目的** | 处理 #PF 用于早期页表建立 | 正式的生产环境异常处理 |

**为什么需要两次？**

1. **阶段 1：临时应急（"保命"）**
   - **时间点**：内核刚启动，很多子系统还未初始化
   - **限制条件**：
     - TSS（Task State Segment）未建立 → 无法使用 IST
     - Per-CPU 数据结构未准备好
     - 只能使用默认内核栈
   - **关键需求**：必须能处理 #PF（缺页异常）
     - 早期页表是动态建立的
     - 访问未映射的内存 → #PF → early_make_pgtable() 建立映射
   - **处理程序特点**：
     ```c
     // 所有异常都跳转到这里
     early_idt_handler_common:
         保存寄存器
         调用 do_early_exception(regs, trapnr)
         恢复寄存器
         iret

     do_early_exception():
         if (trapnr == #PF)
             early_make_pgtable()  // 动态建立页表
         else
             early_fixup_exception() // 或 panic
     ```

2. **阶段 4：正式上岗（"完整功能"）**
   - **时间点**：cpu_init() 完成后，TSS、IST 都已设置好
   - **完整功能**：
     - 可以使用 IST（Interrupt Stack Table）
     - 每个异常有专门的处理程序
     - 支持复杂的错误恢复、信号传递、调试等
   - **关键改进**：
     ```c
     // 每个异常有独立入口
     asm_exc_page_fault:      // #PF 专用处理
         PUSH_AND_CLEAR_REGS
         call exc_page_fault   // C 函数
             handle_page_fault()
             do_user_addr_fault()
             ...复杂的页错误处理...
         POP_REGS
         iret

     asm_exc_double_fault:    // #DF 使用 IST3
         使用独立的 IST 栈（防止栈溢出导致的双重错误）
         call exc_double_fault
             panic("Double Fault")

     asm_exc_nmi:             // #NMI 使用 IST2
         使用独立的 IST 栈（防止被中断打断）
         call exc_nmi
             ...NMI 处理...
     ```

**渐进式初始化的必要性**：

```
内核启动早期状态：
  ✅ 基本 C 运行环境（栈、BSS 段）
  ✅ early_idt_handler_array 汇编代码
  ❌ TSS 未初始化
  ❌ IST 不可用
  ❌ Per-CPU 数据未准备
  ❌ 异常处理子系统未初始化

         ↓ idt_setup_early_handler()
         ↓ 使用简单处理程序
         ↓
         ↓ 内核继续初始化...
         ↓ cpu_init() 设置 TSS/IST
         ↓ 各种子系统初始化
         ↓
         ↓ idt_setup_traps()
         ↓ 切换到完整处理程序

trap_init() 完成后：
  ✅ TSS 已初始化
  ✅ IST 栈已设置
  ✅ Per-CPU 数据已准备
  ✅ 异常处理子系统已就绪
  ✅ 可以使用复杂的异常处理逻辑
```

**代码证据**：

```c
// arch/x86/kernel/head64.c
void __init x86_64_start_kernel(char *real_mode_data)
{
    // 极早期：只有基本环境
    kasan_early_init();
    __native_tlb_flush_global(...);

    idt_setup_early_handler();  // ← 阶段 1：临时应急

    // 此时 TSS 还未初始化，不能使用 IST！
    tdx_early_init();
    copy_bootdata(__va(real_mode_data));
    // ... 继续初始化 ...
}

// arch/x86/kernel/traps.c
void __init trap_init(void)
{
    // 此时已经过了 cpu_init()，TSS/IST 已设置好

    idt_setup_traps();  // ← 阶段 4：正式上岗

    // 替换所有异常向量，使用完整功能处理程序
    // 现在可以安全地使用 IST 了

    idt_setup_apic_and_irq_gates();
    // ...
}
```

**总结**：这是典型的"先有鸡还是先有蛋"问题的解决方案——渐进式初始化：
1. 先用简单的处理程序"保命"（处理必需的 #PF）
2. 等环境准备好后，换上完整功能的处理程序

#### 完整向量表（按初始化阶段分组）

**向量 0-31：CPU 异常（最终由 idt_setup_traps 设置）**

| 向量 | 助记符 | 异常名称 | 处理程序 | 门类型 | IST | DPL |
|------|-------|---------|---------|--------|-----|-----|
| 0 | #DE | Divide Error | `asm_exc_divide_error` | INT | 0 | 0 |
| 1 | #DB | Debug | `asm_exc_debug` | INT | IST1 | 0 |
| 2 | #NMI | NMI | `asm_exc_nmi` | INT | IST2 | 0 |
| 3 | #BP | Breakpoint | `asm_exc_int3` | INT | 0 | **3** |
| 4 | #OF | Overflow | `asm_exc_overflow` | INT | 0 | **3** |
| 5 | #BR | Bound Range | `asm_exc_bounds` | INT | 0 | 0 |
| 6 | #UD | Invalid Opcode | `asm_exc_invalid_op` | INT | 0 | 0 |
| 7 | #NM | Device Not Available | `asm_exc_device_not_available` | INT | 0 | 0 |
| 8 | #DF | Double Fault | `asm_exc_double_fault` (64位) / TSS (32位) | INT/TASK | IST3 | 0 |
| 9 | - | Coprocessor Overrun | `asm_exc_coproc_segment_overrun` | INT | 0 | 0 |
| 10 | #TS | Invalid TSS | `asm_exc_invalid_tss` | INT | 0 | 0 |
| 11 | #NP | Segment Not Present | `asm_exc_segment_not_present` | INT | 0 | 0 |
| 12 | #SS | Stack Fault | `asm_exc_stack_segment` | INT | 0 | 0 |
| 13 | #GP | General Protection | `asm_exc_general_protection` | INT | 0 | 0 |
| 14 | #PF | Page Fault | `asm_exc_page_fault` | INT | 0 | 0 |
| 15 | - | Spurious | `asm_exc_spurious_interrupt_bug` | INT | 0 | 0 |
| 16 | #MF | x87 FPU Error | `asm_exc_coprocessor_error` | INT | 0 | 0 |
| 17 | #AC | Alignment Check | `asm_exc_alignment_check` | INT | 0 | 0 |
| 18 | #MC | Machine Check | `asm_exc_machine_check` | INT | IST4 | 0 |
| 19 | #XF | SIMD Exception | `asm_exc_simd_coprocessor_error` | INT | 0 | 0 |
| 20 | #VE | Virtualization | `asm_exc_virtualization_exception` | INT | 0 | 0 |
| 21 | #CP | Control Protection | `asm_exc_control_protection` | INT | 0 | 0 |
| 22-28 | - | Reserved | (未使用) | - | - | - |
| 29 | #VC | VMM Communication | `asm_exc_vmm_communication` | INT | IST5 | 0 |
| 30 | - | Reserved | (未使用) | - | - | - |
| 31 | - | Reserved | (未使用) | - | - | - |

**向量 32-127：设备中断（由 idt_setup_apic_and_irq_gates 设置）**

| 向量范围 | 用途 | 处理程序 | 说明 |
|---------|------|---------|------|
| 32 (0x20) | IRQ 0 起始 | `irq_entries_start + 0` | 8259A PIC IRQ 0 |
| 33-47 | IRQ 1-15 | `irq_entries_start + n*IDT_ALIGN` | 传统 ISA IRQ |
| 48-127 | 扩展 IRQ | `irq_entries_start + n*IDT_ALIGN` | PCI/MSI 中断 |

**向量 128：系统调用（由 idt_setup_traps 设置）**

| 向量 | 用途 | 处理程序 | 门类型 | DPL | 说明 |
|------|------|---------|--------|-----|------|
| 128 (0x80) | INT 0x80 | `entry_INT80_32` (32位) / `asm_int80_emulation` (64位) | **TRAP** | **3** | 唯一的陷阱门！ |

**向量 129-234：预留/未分配**

| 向量范围 | 状态 |
|---------|------|
| 129-234 | 可分配给设备中断 |

**向量 235-255：系统向量（由 idt_setup_apic_and_irq_gates 设置）**

| 向量 | 十六进制 | 名称 | 处理程序 | 用途 |
|------|---------|------|---------|------|
| 235 | 0xEB | POSTED_MSI_NOTIFICATION | `asm_sysvec_posted_msi_notification` | Posted MSI 通知 |
| 236 | 0xEC | LOCAL_TIMER | `asm_sysvec_apic_timer_interrupt` | 本地 APIC 定时器 |
| 237 | 0xED | HYPERV_STIMER0 | (Hyper-V) | Hyper-V 定时器 |
| 238 | 0xEE | HYPERV_REENLIGHTENMENT | (Hyper-V) | Hyper-V 重新启蒙 |
| 239 | 0xEF | MANAGED_IRQ_SHUTDOWN | (动态) | 托管 IRQ 关闭 |
| 240 | 0xF0 | POSTED_INTR_NESTED | `asm_sysvec_kvm_posted_intr_nested_ipi` | KVM 嵌套中断 |
| 241 | 0xF1 | POSTED_INTR_WAKEUP | `asm_sysvec_kvm_posted_intr_wakeup_ipi` | KVM 唤醒中断 |
| 242 | 0xF2 | POSTED_INTR | `asm_sysvec_kvm_posted_intr_ipi` | KVM Posted 中断 |
| 243 | 0xF3 | HYPERVISOR_CALLBACK | (虚拟化) | Hypervisor 回调 |
| 244 | 0xF4 | DEFERRED_ERROR | `asm_sysvec_deferred_error` | AMD 延迟错误 |
| 245 | 0xF5 | (未分配) | - | - |
| 246 | 0xF6 | IRQ_WORK | `asm_sysvec_irq_work` | IRQ 工作队列 |
| 247 | 0xF7 | X86_PLATFORM_IPI | `asm_sysvec_x86_platform_ipi` | 平台特定 IPI |
| 248 | 0xF8 | REBOOT | `asm_sysvec_reboot` | 重启 IPI |
| 249 | 0xF9 | THRESHOLD_APIC | `asm_sysvec_threshold` | 阈值错误 |
| 250 | 0xFA | THERMAL_APIC | `asm_sysvec_thermal` | 热事件 |
| 251 | 0xFB | CALL_FUNCTION_SINGLE | `asm_sysvec_call_function_single` | 单核函数调用 IPI |
| 252 | 0xFC | CALL_FUNCTION | `asm_sysvec_call_function` | 多核函数调用 IPI |
| 253 | 0xFD | RESCHEDULE | `asm_sysvec_reschedule_ipi` | 重调度 IPI |
| 254 | 0xFE | ERROR_APIC | `asm_sysvec_error_interrupt` | APIC 错误 |
| 255 | 0xFF | SPURIOUS_APIC | `asm_sysvec_spurious_apic_interrupt` | 伪中断 |

#### 关键特性对比

| 特性 | 异常向量 (0-31) | 设备中断 (32-127) | 系统向量 (235-255) | INT 0x80 (128) |
|------|----------------|------------------|-------------------|----------------|
| **门类型** | Interrupt Gate | Interrupt Gate | Interrupt Gate | **Trap Gate** |
| **DPL** | 0 (除 #BP, #OF 为 3) | 0 | 0 | **3** |
| **IST** | #DB(1), #NMI(2), #DF(3), #MC(4), #VC(5) | 0 | 0 | 0 |
| **segment** | __KERNEL_CS (0x0010) | __KERNEL_CS | __KERNEL_CS | __KERNEL_CS |
| **初始化阶段** | idt_setup_traps() | idt_setup_apic_and_irq_gates() | idt_setup_apic_and_irq_gates() | idt_setup_traps() |

#### 数据结构示例对比

**异常向量（Interrupt Gate, DPL=0）**：
```
idt_table[14] (#PF):
  offset_low    = 0x2a80       // asm_exc_page_fault 的地址
  segment       = 0x0010       // __KERNEL_CS
  bits          = 0x8E00       // IST=0, type=0xE, DPL=0, P=1
  offset_middle = 0x8100
  offset_high   = 0xffffffff
  reserved      = 0x00000000
```

**系统调用（Trap Gate, DPL=3，唯一特例！）**：
```
idt_table[128] (INT 0x80):
  offset_low    = 0x1234       // entry_INT80_32 的地址
  segment       = 0x0010       // __KERNEL_CS
  bits          = 0xEF00       // IST=0, type=0xF (Trap!), DPL=3, P=1
  offset_middle = 0x5678
  offset_high   = 0xffffffff
  reserved      = 0x00000000
```

**系统向量（Interrupt Gate, DPL=0）**：
```
idt_table[253] (RESCHEDULE_VECTOR = 0xFD):
  offset_low    = 0xabcd       // asm_sysvec_reschedule_ipi 的地址
  segment       = 0x0010       // __KERNEL_CS
  bits          = 0x8E00       // IST=0, type=0xE, DPL=0, P=1
  offset_middle = 0x9abc
  offset_high   = 0xffffffff
  reserved      = 0x00000000
```

#### 源代码引用

```c
// arch/x86/kernel/idt.c

// 阶段 1：早期处理程序（向量 0-31）
void __init idt_setup_early_handler(void) {
    for (i = 0; i < 32; i++)
        set_intr_gate(i, early_idt_handler_array[i]);
    load_idt(&idt_descr);
}

// 阶段 2-4：异常门设置
void __init idt_setup_traps(void) {
    idt_setup_from_table(idt_table, def_idts, ARRAY_SIZE(def_idts), true);
    // def_idts[] 包含所有异常向量的最终处理程序

    if (ia32_enabled())
        idt_setup_from_table(idt_table, ia32_idt, 1, true);
    // ia32_idt[] = { SYSG(0x80, entry_INT80_32) }
}

// 阶段 5：APIC 和 IRQ 门
void __init idt_setup_apic_and_irq_gates(void) {
    // 设置 APIC 系统向量（235-255）
    idt_setup_from_table(idt_table, apic_idts, ARRAY_SIZE(apic_idts), true);

    // 设置设备中断向量（32-234）
    for (i = 32; i < 235; i++)
        set_intr_gate(i, irq_entries_start + ...);

    idt_map_in_cea();  // 映射到 CPU Entry Area
    load_idt(&idt_descr);
    set_memory_ro(&idt_table, 1);  // 设置为只读！
}
```

---

## 4. 阶段 3：加载 IDT 到 CPU

在填充完 idt_table 的前 32 个条目后，`idt_setup_early_handler()` 调用 `load_idt()` 将 IDT 的位置告诉 CPU。

### 4.1 load_idt() 函数调用

**源代码**（`arch/x86/kernel/idt.c:331`）：

```c
void __init idt_setup_early_handler(void)
{
	int i;

	for (i = 0; i < NUM_EXCEPTION_VECTORS; i++)
		set_intr_gate(i, early_idt_handler_array[i]);

	load_idt(&idt_descr);  // ← 加载到 IDTR
}
```

### 4.2 load_idt() 的底层实现

**源代码位置**：`arch/x86/include/asm/desc.h:122-125`

```c
static inline void load_idt(const struct desc_ptr *dtr)
{
	asm volatile("lidt %0"::"m" (dtr->size));
}
```

**等价的汇编代码**：

```asm
lidt (%rdi)   ; RDI = &idt_descr
```

### 4.3 lidt 指令的操作

**Intel SDM 定义**（Vol. 2A, LIDT 指令）：

> **LIDT** - Load Interrupt Descriptor Table Register
>
> **Operation**（64-bit Mode）:
> ```
> IDTR.Limit ← SRC[0:15];
> IDTR.Base  ← SRC[16:79];
> ```

**x86-64 模式下的实际操作**：

```c
// 执行前：
IDTR.limit = （旧值，可能是 bringup_idt_table 的大小）
IDTR.base  = （旧值，可能是 &bringup_idt_table）

// 执行：lidt (&idt_descr)
// idt_descr 的内容：
//   .size = 4095
//   .address = &idt_table

// 执行后：
IDTR.limit = 4095         // idt_descr.size
IDTR.base  = &idt_table   // idt_descr.address
```

### 4.4 内存布局

**idt_descr 在内存中的布局**（10 字节）：

```
偏移 | 字段      | 值
-----|----------|------------------
+0   | size     | 0x0FFF (4095)
+2   | address  | &idt_table（8 字节）
```

**lidt 指令读取过程**：

```
1. 读取 idt_descr[0..1]（2 字节）→ IDTR.limit = 4095
2. 读取 idt_descr[2..9]（8 字节）→ IDTR.base = &idt_table
3. CPU 内部 IDTR 寄存器更新完成
```

### 4.5 原子切换

**关键特性**：
- `lidt` 指令是**原子操作**
- 执行完毕后，CPU **立即使用**新的 IDT
- 从**下一条指令**开始，所有中断/异常都查询 `idt_table`

**时间点对比**：

```
时刻 T0：执行 lidt 指令之前
    CPU 使用：bringup_idt_table（32 条目的早期 IDT）

时刻 T1：lidt 指令执行中
    CPU 内部更新 IDTR

时刻 T2：lidt 指令执行完毕
    CPU 使用：idt_table ← 从此刻开始！
    bringup_idt_table 被废弃，成为垃圾数据
```

### 4.6 与写入操作的对比

| 操作 | 谁执行 | 对什么操作 | 结果 |
|------|-------|----------|------|
| **写入** idt_table | `write_idt_entry()` | idt_table[i]（内存） | idt_table 被填充 |
| **加载** IDT | `lidt` 指令 | IDTR 寄存器（CPU） | CPU 知道 idt_table 在哪里 |
| **读取** idt_table | CPU 硬件 | idt_table[向量号] | 获取处理程序地址 |

**常见误解**：
- ❌ `load_idt()` 写入 idt_table
- ✅ `write_idt_entry()` 写入 idt_table
- ✅ `load_idt()` 只是告诉 CPU idt_table 的位置

---

## 5. 阶段 4：运行时使用

当 CPU 触发异常时，它根据 IDTR 寄存器找到 idt_table，读取对应的门描述符，跳转到处理程序。

### 5.1 CPU 触发异常的流程

**示例：#PF（Page Fault，向量 14）**

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

### 5.2 early_idt_handler_array 的桩代码

**向量 14 的桩**（`arch/x86/kernel/head_64.S:488-505`）：

```asm
# early_idt_handler_array[14]:
	ENDBR                   # CET 间接分支保护
	# CPU 已经压入了 error code（缺页地址在 CR2）
	pushq $14               # 压入向量号
	jmp early_idt_handler_common  # 跳转到公共处理
```

**栈帧状态**（进入 early_idt_handler_common 前）：

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

### 5.3 early_idt_handler_common - 公共处理程序

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

**功能**：
1. 保存所有通用寄存器（构建完整的 pt_regs）
2. 调用 C 函数 `do_early_exception(regs, trapnr)`
3. 恢复寄存器并返回

**栈帧布局**（调用 do_early_exception 前）：

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

### 5.4 do_early_exception() - C 语言处理

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

**参数**：
- `RDI = pt_regs`（指向栈上的寄存器快照）
- `RSI = trapnr`（异常向量号，14）

**关键处理**：

| 向量号 | 异常类型 | 处理函数 | 说明 |
|--------|---------|---------|------|
| 14 | #PF | `early_make_pgtable()` | 动态建立页表 |
| 29 | #VC | `handle_vc_boot_ghcb()` | AMD SEV 虚拟化异常 |
| 20 | #VE | `tdx_early_handle_ve()` | Intel TDX 虚拟化异常 |
| 其他 | - | `early_fixup_exception()` | 尝试修复或 panic |

**#PF 的特殊处理**：
- 读取 CR2 寄存器（缺页地址）
- 调用 `early_make_pgtable()` 动态映射页表
- 成功则返回，失败则 panic

### 5.5 完整执行流程示例（#PF）

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

---

## 6. 完整代码调用链

### 6.1 总体流程图

```
┌─────────────────────────────────────────────────────────────┐
│ x86_64_start_kernel()                                        │
│   ├─ kasan_early_init()                                      │
│   ├─ __native_tlb_flush_global()                             │
│   ├─ idt_setup_early_handler()  ← 本函数                     │
│   └─ tdx_early_init()                                        │
└─────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│ idt_setup_early_handler()                                    │
│   ├─ for (i = 0; i < 32; i++)                               │
│   │     set_intr_gate(i, early_idt_handler_array[i])         │
│   └─ load_idt(&idt_descr)                                    │
└─────────────────────────────────────────────────────────────┘
        ↓                                   ↓
┌───────────────────────────┐   ┌───────────────────────────┐
│ set_intr_gate(i, addr)    │   │ load_idt(&idt_descr)       │
│   ├─ init_idt_data()      │   │   └─ lidt 指令             │
│   └─ idt_setup_from_table│   │       └─ IDTR.base =       │
└───────────────────────────┘   │           &idt_table       │
        ↓                       └───────────────────────────┘
┌───────────────────────────┐
│ idt_setup_from_table()    │
│   ├─ idt_init_desc()      │
│   └─ write_idt_entry()    │
└───────────────────────────┘
        ↓
┌───────────────────────────┐
│ write_idt_entry()         │
│   └─ idt_table[i] = desc  │  ← 内存写入
└───────────────────────────┘
```

### 6.2 数据流

```
early_idt_handler_array[i]  ← 编译时生成的地址
        ↓
set_intr_gate(i, early_idt_handler_array[i])
        ↓
init_idt_data(&data, i, addr)  ← 构建临时结构
        ↓
idt_init_desc(&desc, &data)  ← 构建门描述符
        ↓
write_idt_entry(idt_table, i, &desc)  ← 写入 idt_table[i]
        ↓
load_idt(&idt_descr)  ← 加载 IDTR.base = &idt_table
        ↓
CPU 触发异常 → 读取 idt_table[i] → 跳转到 early_idt_handler_array[i]
```

### 6.3 文件位置总结

| 组件 | 源代码位置 | 说明 |
|------|----------|------|
| `idt_setup_early_handler()` | `arch/x86/kernel/idt.c:317-331` | 主函数 |
| `set_intr_gate()` | `arch/x86/kernel/idt.c:206-213` | 设置中断门 |
| `init_idt_data()` | `arch/x86/include/asm/desc.h` | 初始化 idt_data 宏 |
| `idt_setup_from_table()` | `arch/x86/kernel/idt.c:193-204` | 批量写入 |
| `idt_init_desc()` | `arch/x86/kernel/idt.c:64-73` | 构建门描述符 |
| `write_idt_entry()` | `arch/x86/include/asm/desc.h:177-180` | 原子写入 |
| `load_idt()` | `arch/x86/include/asm/desc.h:122-125` | 加载 IDTR |
| `idt_table` | `arch/x86/kernel/idt.c:173` | IDT 表定义 |
| `idt_descr` | `arch/x86/kernel/idt.c:175-178` | IDT 描述符 |
| `early_idt_handler_array` | `arch/x86/kernel/head_64.S:488-505` | 异常桩数组 |
| `early_idt_handler_common` | `arch/x86/kernel/head_64.S:508-542` | 公共处理程序 |
| `do_early_exception()` | `arch/x86/kernel/head64.c:156-170` | C 语言处理 |

---

## 7. 为什么是 32 个向量？

### 7.1 x86 架构的异常定义

**Intel SDM** 定义了 **32 个保留的异常向量**（0-31）：

| 向量号 | 助记符 | 异常名称 | 错误码？ |
|--------|--------|---------|---------|
| 0      | #DE    | Divide Error | 否 |
| 1      | #DB    | Debug Exception | 否 |
| 2      | -      | NMI Interrupt | 否 |
| 3      | #BP    | Breakpoint | 否 |
| 4      | #OF    | Overflow | 否 |
| 5      | #BR    | BOUND Range Exceeded | 否 |
| 6      | #UD    | Invalid Opcode | 否 |
| 7      | #NM    | Device Not Available | 否 |
| 8      | #DF    | Double Fault | **是**（总是 0） |
| 9      | -      | Coprocessor Segment Overrun（保留） | 否 |
| 10     | #TS    | Invalid TSS | **是** |
| 11     | #NP    | Segment Not Present | **是** |
| 12     | #SS    | Stack-Segment Fault | **是** |
| 13     | #GP    | General Protection | **是** |
| 14     | #PF    | Page Fault | **是** |
| 15     | -      | （保留） | 否 |
| 16     | #MF    | x87 FPU Error | 否 |
| 17     | #AC    | Alignment Check | **是** |
| 18     | #MC    | Machine Check | 否 |
| 19     | #XM/#XF| SIMD Floating-Point Exception | 否 |
| 20     | #VE    | Virtualization Exception | 否 |
| 21     | #CP    | Control Protection Exception | **是** |
| 22-27  | -      | （保留） | - |
| 28     | #HV    | Hypervisor Injection Exception | 否 |
| 29     | #VC    | VMM Communication Exception | **是** |
| 30     | #SX    | Security Exception | **是** |
| 31     | -      | （保留） | - |

### 7.2 NUM_EXCEPTION_VECTORS 的定义

**源代码**（`arch/x86/include/asm/irq_vectors.h`）：

```c
#define NUM_EXCEPTION_VECTORS  32
```

### 7.3 为什么只设置 32 个？

**原因 1：x86 架构规范**
- Intel SDM 明确保留向量 0-31 用于 CPU 异常
- 向量 32-255 用于外部中断和软件中断

**原因 2：启动阶段的需求**
- 此时**硬件中断仍然禁用**（`cli` 指令）
- 不会收到 IRQ（32-255）
- 只需要处理 CPU 异常（0-31）

**原因 3：避免过早初始化**
- IRQ 的处理需要 APIC、PIC 等中断控制器的初始化
- 这些在后续的 `init_IRQ()` 中完成
- 过早设置 IRQ 门可能导致硬件配置不一致

**原因 4：统一的早期处理**
- 所有 32 个异常都指向统一的 `early_idt_handler_array`
- 简化了早期异常处理逻辑
- 后续会用更专门的处理程序替换（`idt_setup_traps()`）

### 7.4 向量 32-255 的后续初始化

```c
// arch/x86/kernel/idt.c

// 第二阶段：设置陷阱门（exceptions with specific handlers）
idt_setup_traps();

// 第三阶段：设置 APIC 和 IRQ 门（32-255）
idt_setup_apic_and_irq_gates();
```

**完整 IDT 初始化流程**：

```
启动阶段 1：idt_setup_early_handler()
    └─ 设置向量 0-31（early_idt_handler_array）

启动阶段 2：idt_setup_traps()
    └─ 替换向量 0-31（专门的异常处理程序，如 asm_exc_page_fault）

启动阶段 3：idt_setup_apic_and_irq_gates()
    └─ 设置向量 32-255（IRQ、APIC、IPI 等）

启动完成：256 个向量全部初始化完毕
```

---

## 8. 参考文献

### 8.1 Linux 内核源代码

1. **arch/x86/kernel/idt.c**
   - `idt_setup_early_handler()` 函数（行 317-331）
   - `set_intr_gate()` 函数（行 206-213）
   - `idt_table` 定义（行 173）
   - `idt_descr` 定义（行 175-178）

2. **arch/x86/kernel/head_64.S**
   - `early_idt_handler_array` 定义（行 488-505）
   - `early_idt_handler_common` 实现（行 508-542）

3. **arch/x86/kernel/head64.c**
   - `x86_64_start_kernel()` 函数（行 219-289）
   - `do_early_exception()` 函数（行 156-170）

4. **arch/x86/include/asm/desc_defs.h**
   - `gate_desc` 结构定义（行 79-91）
   - `desc_ptr` 结构定义（行 23-26）

### 8.2 Intel 手册

5. **Intel 64 and IA-32 Architectures Software Developer's Manual**
   - Volume 3A, Chapter 6: Interrupt and Exception Handling
   - Volume 2A, LIDT 指令描述

### 8.3 相关文档

6. [LINUX_KERNEL_IDT_EVOLUTION.md](LINUX_KERNEL_IDT_EVOLUTION.md)
   - IDT 表的演进流程详解

7. [LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md)
   - Linux 内核启动与初始化

8. [KASAN_INSTRUMENTATION_AND_INIT_ORDER.md](KASAN_INSTRUMENTATION_AND_INIT_ORDER.md)
   - KASAN 插桩机制与初始化顺序

---

**文档结束**
