# idt_setup_early_handler() 函数详细分析

**版本**: 2.0
**日期**: 2026-02-17
**作者**: Linux 内核启动文档项目
**更新内容**:
- v2.0: 文档模块化重构，将详细内容拆分到独立文档（减少 40% 篇幅）
  - 完整向量表 → [IDT_COMPLETE_VECTOR_TABLE.md](./IDT_COMPLETE_VECTOR_TABLE.md)
  - 数据结构详解 → [IDT_DATA_STRUCTURES_RELATIONSHIP.md](./IDT_DATA_STRUCTURES_RELATIONSHIP.md)
  - 异常处理流程 → [IDT_EXCEPTION_HANDLING_DETAILS.md](./IDT_EXCEPTION_HANDLING_DETAILS.md)
- v1.3: 完成全文重组，所有章节按执行顺序组织（编译→写入→加载→使用），消除重复内容
- v1.2: 添加执行顺序总览和关键概念澄清（1.0 节），明确区分写入 vs 加载操作
- v1.1: 添加核心数据结构关系概览（2.0 节），优化三个核心变量的关系说明
- v1.0: 初始版本

> 📚 **文档导航**:
> - [返回总索引](DOCUMENT_INDEX.md) | [IDT 演进](LINUX_KERNEL_IDT_EVOLUTION.md) | [内核启动](LINUX_KERNEL_INIT.md)
> - **配套详细文档**: [完整向量表](./IDT_COMPLETE_VECTOR_TABLE.md) | [数据结构详解](./IDT_DATA_STRUCTURES_RELATIONSHIP.md) | [异常处理流程](./IDT_EXCEPTION_HANDLING_DETAILS.md)

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

### 2.1 early_idt_handler_array - 异常处理程序数组（汇编生成）

**❗ 关键澄清**：这**不是空表**，而是编译时就生成的**实际代码**！

| 对比项 | early_idt_handler_array | idt_table |
|--------|------------------------|----------|
| **性质** | 代码段（.text 段） | 数据段（.bss 段） |
| **编译后状态** | ✅ **包含完整的机器指令** | ❌ **全为 0（空数据）** |
| **内容** | 32 段汇编代码桩（每段 10-12 字节） | 256 个门描述符位置（每个 16 字节） |
| **作用** | 可执行代码（CPU 可以跳转执行） | 可写数据（运行时填充） |
| **生成时机** | 编译时由 `.rept` 宏展开 | 编译时分配空间 |
| **类比** | 已经印刷好的书籍 | 空白的书架 |

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

**编译后的实际机器码**（证明不是空表！）：

可以通过 `objdump -d vmlinux` 查看编译后的实际内容：

```
ffffffff81002a00 <early_idt_handler_array>:
ffffffff81002a00:   6a 00                   pushq  $0x0
ffffffff81002a02:   6a 00                   pushq  $0x0
ffffffff81002a04:   e9 b7 00 00 00          jmpq   ffffffff81002ac0 <early_idt_handler_common>
ffffffff81002a09:   cc                      int3
ffffffff81002a0a:   cc                      int3
ffffffff81002a0b:   cc                      int3

ffffffff81002a0c <early_idt_handler_array+0xc>:
ffffffff81002a0c:   6a 00                   pushq  $0x0
ffffffff81002a0e:   6a 01                   pushq  $0x1
ffffffff81002a10:   e9 ab 00 00 00          jmpq   ffffffff81002ac0 <early_idt_handler_common>
ffffffff81002a15:   cc                      int3
...

ffffffff81002a80 <early_idt_handler_array+0x80>:
ffffffff81002a80:   6a 0e                   pushq  $0xe    # 向量 14 (#PF)
ffffffff81002a82:   e9 39 00 00 00          jmpq   ffffffff81002ac0 <early_idt_handler_common>
ffffffff81002a87:   cc                      int3
...
```

**对比 idt_table 的编译后状态**：

```bash
# 查看 idt_table 的内容（BSS 段）
$ readelf -s vmlinux | grep idt_table
82823: ffffffff82809000  4096 OBJECT  LOCAL  DEFAULT   28 idt_table

$ objdump -s -j .bss vmlinux | grep -A5 82809000
# 输出：全部为 0x00（空数据）
ffffffff82809000 00000000 00000000 00000000 00000000  ................
ffffffff82809010 00000000 00000000 00000000 00000000  ................
...
```

**总结对比**：

```
编译完成后的内核映像（vmlinux）中：

early_idt_handler_array:
  段：.text（代码段）
  内容：✅ 完整的机器指令（6a 00, 6a 00, e9 ..., cc）
  状态：可执行，CPU 可以直接跳转到这些地址执行
  大小：约 320-384 字节（32 × 10-12 字节）

idt_table:
  段：.bss（未初始化数据段）
  内容：❌ 全部为 0x00
  状态：可写，等待运行时填充
  大小：4096 字节（256 × 16 字节）
```

**关键常量**：

```c
// arch/x86/include/asm/irq_vectors.h
#define NUM_EXCEPTION_VECTORS  32  // CPU 异常向量数量

// arch/x86/kernel/head_64.S
#define EARLY_IDT_HANDLER_SIZE 10  // 或 12，取决于 CET
```

### 2.2 idt_table - IDT 表本体（BSS 段分配）

**✅ 这个才是"空表"**：编译后全为 0，等待运行时填充！

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

### 2.4 idt_descr 和 idt_table 的关系

**核心关系**：
- `idt_descr`（10 字节）：存储 idt_table 的地址和大小（元信息）
- `idt_table`（4096 字节）：存储 256 个门描述符（实际数据）
- `lidt` 指令读取 idt_descr，将其内容加载到 IDTR 寄存器

**为什么需要两个结构？**
- x86 `lidt` 指令要求 10 字节操作数（2 字节 limit + 8 字节 base）
- idt_descr 作为中间层，指向实际的 idt_table
- 允许灵活切换不同的 IDT 表（如虚拟化场景）

> 📖 **详细说明**：完整的数据结构关系图、内存布局示例、使用流程和十六进制数据格式请参见：
> [IDT_DATA_STRUCTURES_RELATIONSHIP.md](./IDT_DATA_STRUCTURES_RELATIONSHIP.md)

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

**写入的数据格式**：

每个门描述符占 **16 字节**，包含：
- offset_low/middle/high（8 字节总计）：处理程序地址的三部分
- segment（2 字节）：代码段选择子（__KERNEL_CS = 0x0010）
- bits（2 字节）：IST、type、DPL、P 等标志位（early stage 为 0x8E00）
- reserved（4 字节）：必须为 0

> 📖 **十六进制数据详解**：完整的 16 字节内存布局、bits 字段位分解、多个向量的数据对比请参见：
> [IDT_DATA_STRUCTURES_RELATIONSHIP.md](./IDT_DATA_STRUCTURES_RELATIONSHIP.md)

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

### 3.9 完整的 IDT 表内容（256 个向量）

**关键概念**：`idt_setup_early_handler()` 只是第一步，填充了向量 0-31。完整的 256 向量 IDT 表需要多个阶段逐步填充：

1. **阶段 1** (早期)：向量 0-31 → `early_idt_handler_array`
2. **阶段 2-4** (trap_init)：覆盖向量 0-31 → 具名处理程序（如 `asm_exc_page_fault`）
3. **阶段 5** (后期)：向量 32-255 → IRQ、APIC、系统向量

**为什么要填充两次？**
- 第一次（emergency handlers）：简单桩代码，无需 TSS/IST 支持
- 第二次（production handlers）：完整功能处理程序，使用 IST 专用栈

> 📖 **完整向量表参考手册**：包含全部 256 个向量的详细列表、初始化阶段时间线、数据结构示例和源代码引用，请参见：
> [IDT_COMPLETE_VECTOR_TABLE.md](./IDT_COMPLETE_VECTOR_TABLE.md)

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

**早期异常处理流程摘要**：

1. **CPU 硬件操作**：保存上下文 → 查找 IDTR → 读取 idt_table[vector] → 跳转到处理程序
2. **桩代码 (early_idt_handler_array)**：压入向量号 → 跳转到公共处理程序
3. **公共处理程序 (early_idt_handler_common)**：保存所有寄存器 → 调用 C 函数
4. **C 语言处理 (do_early_exception)**：
   - #PF（向量 14）→ 动态建立页表 (early_make_pgtable)
   - #VC（向量 29）→ AMD SEV 虚拟化处理
   - #VE（向量 20）→ Intel TDX 虚拟化处理
   - 其他 → 尝试修复或 panic
5. **返回**：恢复寄存器 → iret → 重新执行触发异常的指令

> 📖 **详细的异常处理流程分析**：包含 CPU 硬件操作、栈帧布局、pt_regs 结构、完整执行流程示例等，请参见：
> [IDT_EXCEPTION_HANDLING_DETAILS.md](./IDT_EXCEPTION_HANDLING_DETAILS.md)

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
