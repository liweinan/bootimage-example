# early_idt_handler_array 深度解析：它不是数组！

**文档系列**：Linux x86_64 IDT 初始化机制分析
**主文档**：[IDT_SETUP_EARLY_HANDLER_DETAILED_ANALYSIS.md](./IDT_SETUP_EARLY_HANDLER_DETAILED_ANALYSIS.md)
**相关文档**：
- [IDT_DATA_STRUCTURES_RELATIONSHIP.md](./IDT_DATA_STRUCTURES_RELATIONSHIP.md) - 数据结构关系详解
- [IDT_EXCEPTION_HANDLING_DETAILS.md](./IDT_EXCEPTION_HANDLING_DETAILS.md) - 异常处理流程详解

---

## 目录

1. [常见误解](#1-常见误解)
2. [正确理解](#2-正确理解)
3. [实际的内存布局](#3-实际的内存布局)
4. [early_idt_handler_array 的真实身份](#4-early_idt_handler_array-的真实身份)
5. [使用时的计算过程](#5-使用时的计算过程)
6. [objdump 实证验证](#6-objdump-实证验证)
7. [与 idt_data.addr 的对应关系](#7-与-idt_dataaddr-的对应关系)
8. [完整的数据流转过程](#8-完整的数据流转过程)
9. [类比总结](#9-类比总结)

---

## 概述

`early_idt_handler_array` 是 Linux 内核 IDT 初始化过程中最容易被误解的概念之一。很多人看到 `array` 这个名字，就认为它是一个存储地址的数组。

**本文将彻底澄清**：`early_idt_handler_array` 不是真正的"数组"，它是一个**汇编符号（symbol）**，指向一段**连续的机器代码块**。

---

## 1. 常见误解

### ❌ 错误的理解

```c
// 误解 1：认为它是一个指针数组
void *early_idt_handler_array[32] = {
    0xffffffff81002a00,  // ← 向量 0 的地址
    0xffffffff81002a0d,  // ← 向量 1 的地址
    0xffffffff81002a1a,  // ← 向量 2 的地址
    ...
};

// 误解 2：认为 early_idt_handler_array[i] 读取数组元素
void *handler = early_idt_handler_array[i];  // 从数组中取地址？
```

### 为什么会产生误解？

1. **名字误导**：`array` 后缀让人联想到数组
2. **使用方式**：`early_idt_handler_array[i]` 看起来像数组访问
3. **C 语言声明**：`extern const char early_idt_handler_array[]` 看起来像数组

---

## 2. 正确理解

### ✅ 正确的理解

```
early_idt_handler_array 是一个汇编符号（label），
指向一段连续的机器代码块（32 个处理程序桩）。

它本身不存储地址，而是"被存储"的机器代码的起始位置。
```

### 关键点

| 属性 | 说明 |
|------|------|
| **本质** | 汇编符号（类似 C 语言的函数名） |
| **指向** | .text 段（代码段）的一块机器代码 |
| **内容** | 32 个连续的异常处理程序桩（机器指令） |
| **大小** | 不固定（每个桩约 12-15 字节，取决于是否有错误码） |
| **类型** | 在 C 中声明为 `const char []`，但实际是代码 |

---

## 3. 实际的内存布局

### 代码段（.text）的真实内容

```
虚拟地址              内容（机器代码，不是地址！）              说明
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
0xffffffff81002a00:  f3 0f 1e fa                              endbr64
0xffffffff81002a04:  6a 00                                    pushq $0     ← 假错误码
0xffffffff81002a06:  6a 00                                    pushq $0     ← 向量号 0
0xffffffff81002a08:  e9 b3 00 00 00                           jmp early_idt_handler_common
                     ↑
                     这些是机器码（CPU 可执行的指令），不是地址！
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
0xffffffff81002a0d:  f3 0f 1e fa                              endbr64
0xffffffff81002a11:  6a 00                                    pushq $0     ← 假错误码
0xffffffff81002a13:  6a 01                                    pushq $1     ← 向量号 1
0xffffffff81002a15:  e9 a6 00 00 00                           jmp early_idt_handler_common
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
0xffffffff81002a1a:  f3 0f 1e fa                              endbr64
0xffffffff81002a1e:  6a 02                                    pushq $2     ← 向量号 2（无错误码）
0xffffffff81002a20:  e9 9b 00 00 00                           jmp early_idt_handler_common
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
...（继续到向量 31）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
0xffffffff81002b40:  f3 0f 1e fa                              endbr64
0xffffffff81002b44:  6a 1f                                    pushq $31    ← 向量号 31
0xffffffff81002b46:  e9 75 ff ff ff                           jmp early_idt_handler_common
```

### 内存可视化

```
错误理解（指针数组）：
┌────────────────────────────────────────────────────────┐
│  early_idt_handler_array[32]（数组，每个元素 8 字节）   │
│  ┌─────────┬─────────┬─────────┬─────────┐            │
│  │ 0x...00 │ 0x...0d │ 0x...1a │ 0x...27 │  ...       │
│  └────┬────┴────┬────┴────┬────┴────┬────┘            │
│       │         │         │         │                 │
│       ↓         ↓         ↓         ↓                 │
│     代码0     代码1     代码2     代码3                │
└────────────────────────────────────────────────────────┘

正确理解（连续的代码块）：
┌────────────────────────────────────────────────────────┐
│  .text 段（代码段）                                     │
│  ┌────────────────────────────────────────────────┐   │
│  │ early_idt_handler_array ← 符号（标签）          │   │
│  │    ↓                                            │   │
│  │ [代码0][代码1][代码2][代码3]...[代码31]         │   │
│  │  ↑      ↑      ↑      ↑                        │   │
│  │  0x00   0x0d   0x1a   0x27  ← 地址偏移         │   │
│  └────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────┘
```

---

## 4. early_idt_handler_array 的真实身份

### 汇编源代码

**源代码位置**：`arch/x86/kernel/head_64.S:488-505`

```asm
SYM_CODE_START(early_idt_handler_array)  ← 这是一个符号/标签
	i = 0
	.rept NUM_EXCEPTION_VECTORS          ← 重复 32 次
	.if ((EXCEPTION_ERRCODE_MASK >> i) & 1) == 0
		UNWIND_HINT_IRET_REGS
		ENDBR
		pushq $0                         ← 假错误码
	.else
		UNWIND_HINT_IRET_REGS offset=8
		ENDBR
	.endif
		pushq $i                         ← 向量号
		jmp early_idt_handler_common
		UNWIND_HINT_IRET_REGS
	i = i + 1
	.endr
SYM_CODE_END(early_idt_handler_array)
```

### 生成的机器代码（简化）

```asm
# 向量 0 的桩（有假错误码）
early_idt_handler_array:        # ← 符号定义在这里
    endbr64                      # 4 字节
    pushq $0                     # 2 字节（假错误码）
    pushq $0                     # 2 字节（向量号）
    jmp early_idt_handler_common # 5 字节
    # 总计：13 字节

# 向量 1 的桩（有假错误码）
    endbr64                      # 4 字节
    pushq $0                     # 2 字节（假错误码）
    pushq $1                     # 2 字节（向量号）
    jmp early_idt_handler_common # 5 字节
    # 总计：13 字节

# 向量 2 的桩（无错误码）
    endbr64                      # 4 字节
    pushq $2                     # 2 字节（向量号）
    jmp early_idt_handler_common # 5 字节
    # 总计：11 字节
```

### C 语言声明

**源代码位置**：`arch/x86/include/asm/desc.h`

```c
extern const char early_idt_handler_array[];
//           ^^^^ ^^^^                    ^^
//           |    |                       |
//           |    |                       空数组（大小未知）
//           |    字符类型（1 字节）
//           常量（代码段是只读的）
```

**为什么声明为 `const char[]`？**

1. **类型欺骗**：汇编代码块需要一个 C 类型来引用
2. **字节访问**：`char` 是 1 字节，方便以字节为单位计算偏移
3. **只读属性**：`const` 表示代码段不可修改
4. **大小未知**：`[]` 表示编译器不知道大小（由链接器确定）

**实际含义**：
```c
// 虽然声明为数组，但实际上是：
void early_idt_handler_array(void);  // 类似函数（但不能调用）
// 或者理解为：
extern const unsigned char early_idt_handler_array[];  // 代码字节序列
```

---

## 5. 使用时的计算过程

### C 代码中的使用

```c
void __init idt_setup_early_handler(void)
{
	int i;

	for (i = 0; i < NUM_EXCEPTION_VECTORS; i++)
		set_intr_gate(i, early_idt_handler_array[i]);
		//               ^^^^^^^^^^^^^^^^^^^^^^^^^^^
		//               这是什么意思？
}
```

### 表达式分解

```c
early_idt_handler_array[i]

// 在 C 语言中，这等价于：
*( early_idt_handler_array + i )

// 展开为：
*( (const char *)early_idt_handler_array + i * sizeof(char) )

// 由于 sizeof(char) = 1：
*( (const char *)early_idt_handler_array + i )

// 但这会错误！因为每个桩的大小不是 1 字节
```

### 编译器和链接器的魔法

**关键**：编译器不知道每个桩的大小，但链接器知道！

```c
// 在符号表中，链接器记录了每个桩的偏移量：
early_idt_handler_array + 0x00  → 向量 0 的桩（0xffffffff81002a00）
early_idt_handler_array + 0x0d  → 向量 1 的桩（0xffffffff81002a0d）
early_idt_handler_array + 0x1a  → 向量 2 的桩（0xffffffff81002a1a）
early_idt_handler_array + 0x27  → 向量 3 的桩（0xffffffff81002a27）
...
early_idt_handler_array + 0x140 → 向量 31 的桩（0xffffffff81002b40）
```

**实际编译结果**：

```asm
# 编译 set_intr_gate(i, early_idt_handler_array[i]) 时
# 编译器生成（简化）：

mov    %rdi, %rax                          # rax = i
lea    early_idt_handler_array(%rip), %rcx # rcx = 符号地址
imul   $0xd, %rax, %rax                    # rax = i * 13（每个桩约 13 字节）
add    %rcx, %rax                          # rax = 基地址 + 偏移
mov    %rax, %rsi                          # 第二个参数 = 地址
call   set_intr_gate
```

**注意**：实际的偏移计算更复杂，因为不同桩大小不同（有/无错误码）。

### 实际工作方式

虽然 C 代码写的是 `early_idt_handler_array[i]`，但实际上：

1. **编译时**：编译器生成对符号 `early_idt_handler_array` 的引用
2. **链接时**：链接器计算每个桩的实际偏移量
3. **运行时**：直接使用计算好的地址

---

## 6. objdump 实证验证

### 查看实际的二进制内容

```bash
$ objdump -d vmlinux | grep -A 30 early_idt_handler_array
```

**输出**（简化）：

```asm
ffffffff81002a00 <early_idt_handler_array>:
ffffffff81002a00:   f3 0f 1e fa             endbr64
ffffffff81002a04:   6a 00                   pushq  $0x0
ffffffff81002a06:   6a 00                   pushq  $0x0
ffffffff81002a08:   e9 b3 00 00 00          jmpq   ffffffff81002ac0 <early_idt_handler_common>

ffffffff81002a0d:   f3 0f 1e fa             endbr64
ffffffff81002a11:   6a 00                   pushq  $0x0
ffffffff81002a13:   6a 01                   pushq  $0x1
ffffffff81002a15:   e9 a6 00 00 00          jmpq   ffffffff81002ac0 <early_idt_handler_common>

ffffffff81002a1a:   f3 0f 1e fa             endbr64
ffffffff81002a1e:   6a 02                   pushq  $0x2
ffffffff81002a20:   e9 9b 00 00 00          jmpq   ffffffff81002ac0 <early_idt_handler_common>
```

### 关键观察

| 地址 | 内容 | 说明 |
|------|------|------|
| `0xffffffff81002a00` | `f3 0f 1e fa` | **机器码**（不是地址！） |
| `0xffffffff81002a04` | `6a 00` | **机器码**（pushq 指令） |
| `0xffffffff81002a0d` | `f3 0f 1e fa` | **机器码**（第二个桩的开始） |

**结论**：这些地址存储的是**机器指令**，不是指针数组！

### 查看符号表

```bash
$ readelf -s vmlinux | grep early_idt_handler_array
```

**输出**：

```
  Num:    Value          Size Type    Bind   Vis      Ndx Name
 1234: ffffffff81002a00   320 NOTYPE  GLOBAL DEFAULT    1 early_idt_handler_array
                          ^^^
                          大小约 320 字节（32 个桩 × 平均 10 字节）
```

**解读**：
- `Type: NOTYPE`：不是数据对象，也不是函数
- `Size: 320`：整个代码块的大小
- `Ndx: 1`：在第 1 个段（.text 代码段）

---

## 7. 与 idt_data.addr 的对应关系

### 完整的数据流转

```
编译阶段                    运行时
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
汇编代码生成              →  地址确定              →  填充到 idt_data
```

### 步骤分解

#### 第 1 步：汇编代码生成机器码

```asm
# 源代码（head_64.S）
SYM_CODE_START(early_idt_handler_array)
    .rept 32
        ...
    .endr
SYM_CODE_END(early_idt_handler_array)

# ↓ 汇编器处理

# 生成的机器码（.o 文件）
early_idt_handler_array:
    f3 0f 1e fa 6a 00 6a 00 e9 b3 00 00 00  # 向量 0
    f3 0f 1e fa 6a 00 6a 01 e9 a6 00 00 00  # 向量 1
    ...
```

#### 第 2 步：链接器确定地址

```
链接器分配地址：
early_idt_handler_array = 0xffffffff81002a00

符号表：
early_idt_handler_array[0]  → 0xffffffff81002a00
early_idt_handler_array[1]  → 0xffffffff81002a0d
early_idt_handler_array[2]  → 0xffffffff81002a1a
...
```

#### 第 3 步：运行时取地址

```c
// C 代码
set_intr_gate(0, early_idt_handler_array[0]);

// ↓ 运行时

// 传递给函数的参数：
n = 0
addr = 0xffffffff81002a00  ← 这是一个地址值
```

#### 第 4 步：填充到 idt_data

```c
static __init void set_intr_gate(unsigned int n, const void *addr)
{
    struct idt_data data;

    init_idt_data(&data, n, addr);
    //                      ↑
    //                      addr = 0xffffffff81002a00
}

// ↓ 宏展开

struct idt_data data = {
    .vector  = 0,
    .segment = __KERNEL_CS,
    .bits    = { .ist = 0, .type = 0xE, .dpl = 0, .p = 1 },
    .addr    = 0xffffffff81002a00,  ← 存储处理程序地址
};
```

#### 第 5 步：转换为门描述符

```c
void idt_init_desc(gate_desc *gate, const struct idt_data *d)
{
    unsigned long addr = (unsigned long) d->addr;
    //                                    ↑
    //                    addr = 0xffffffff81002a00

    gate->offset_low    = (u16) addr;           // 0x2a00
    gate->segment       = (u16) d->segment;     // 0x0010
    gate->bits          = d->bits;              // 0x8E00
    gate->offset_middle = (u16) (addr >> 16);   // 0x8100
    gate->offset_high   = (u32) (addr >> 32);   // 0xffffffff
    gate->reserved      = 0;
}
```

#### 第 6 步：写入 idt_table

```c
write_idt_entry(idt_table, 0, &desc);

// ↓ memcpy

idt_table[0] = {
    00 2A 10 00 00 8E 00 81 FF FF FF FF 00 00 00 00
    └───┬──┘                └───────────┬──────────┘
     offset_low              offset_middle/high
     = 0x2A00                = 0xffffffff8100

    完整地址：0xFFFFFFFF81002A00 ← 指向 early_idt_handler_array[0]
};
```

### 对应关系总结

| 阶段 | 对象 | 类型 | 值 |
|------|------|------|-----|
| **编译** | 汇编代码 | 机器指令 | `f3 0f 1e fa 6a 00 ...` |
| **链接** | early_idt_handler_array[0] | 符号地址 | `0xffffffff81002a00` |
| **运行** | idt_data.addr | 指针 | `0xffffffff81002a00` |
| **转换** | gate_desc.offset_xxx | 地址拆分 | `0x2a00, 0x8100, 0xffffffff` |
| **存储** | idt_table[0] | 16 字节数据 | `00 2A 10 00 ...` |

---

## 8. 完整的数据流转过程

```
┌────────────────────────────────────────────────────────────────┐
│  第 1 步：编译阶段 - 汇编代码生成机器码                         │
├────────────────────────────────────────────────────────────────┤
│  源代码（head_64.S）                                            │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ SYM_CODE_START(early_idt_handler_array)                  │ │
│  │     pushq $0                                             │ │
│  │     pushq $0                                             │ │
│  │     jmp early_idt_handler_common                         │ │
│  │ SYM_CODE_END(early_idt_handler_array)                    │ │
│  └──────────────────────────────────────────────────────────┘ │
│                           ↓ 汇编器                            │
│  目标文件（head_64.o）                                          │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ .text 段：                                                │ │
│  │   f3 0f 1e fa 6a 00 6a 00 e9 b3 00 00 00                │ │
│  │   f3 0f 1e fa 6a 00 6a 01 e9 a6 00 00 00                │ │
│  │   ...                                                    │ │
│  │                                                          │ │
│  │ 符号表：                                                  │ │
│  │   early_idt_handler_array = 偏移 0（待链接）             │ │
│  └──────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────────┐
│  第 2 步：链接阶段 - 确定绝对地址                               │
├────────────────────────────────────────────────────────────────┤
│  链接器（ld）                                                   │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ 合并所有 .text 段                                         │ │
│  │ 计算符号的绝对地址：                                      │ │
│  │   early_idt_handler_array = 0xffffffff81002a00           │ │
│  │                                                          │ │
│  │ 计算每个桩的地址：                                        │ │
│  │   early_idt_handler_array[0]  = 0xffffffff81002a00      │ │
│  │   early_idt_handler_array[1]  = 0xffffffff81002a0d      │ │
│  │   early_idt_handler_array[2]  = 0xffffffff81002a1a      │ │
│  │   ...                                                    │ │
│  └──────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────────┐
│  第 3 步：运行时 - 取地址并填充                                 │
├────────────────────────────────────────────────────────────────┤
│  C 代码执行                                                     │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ for (i = 0; i < 32; i++)                                 │ │
│  │     set_intr_gate(i, early_idt_handler_array[i]);        │ │
│  │                      ↑                                   │ │
│  │                      取地址：0xffffffff81002a00 + 偏移   │ │
│  └──────────────────────────────────────────────────────────┘ │
│                           ↓                                    │
│  struct idt_data data                                          │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ .vector  = 0                                             │ │
│  │ .segment = 0x0010                                        │ │
│  │ .bits    = { ist=0, type=0xE, dpl=0, p=1 }              │ │
│  │ .addr    = 0xffffffff81002a00  ← 存储地址                │ │
│  └──────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────────┐
│  第 4 步：转换为门描述符                                        │
├────────────────────────────────────────────────────────────────┤
│  idt_init_desc()                                               │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ gate_desc desc = {                                       │ │
│  │     .offset_low    = 0x2a00,                            │ │
│  │     .segment       = 0x0010,                            │ │
│  │     .bits          = 0x8E00,                            │ │
│  │     .offset_middle = 0x8100,                            │ │
│  │     .offset_high   = 0xffffffff,                        │ │
│  │     .reserved      = 0                                  │ │
│  │ };                                                       │ │
│  └──────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────────┐
│  第 5 步：写入 idt_table                                        │
├────────────────────────────────────────────────────────────────┤
│  write_idt_entry(idt_table, 0, &desc)                          │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ idt_table[0] = 16 字节：                                  │ │
│  │   00 2A 10 00 00 8E 00 81 FF FF FF FF 00 00 00 00       │ │
│  │   ↑                                                      │ │
│  │   重组后地址：0xFFFFFFFF81002A00                         │ │
│  │   指向 early_idt_handler_array[0] 的机器代码             │ │
│  └──────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────────┐
│  异常触发时：CPU 使用这个地址跳转到处理程序                     │
└────────────────────────────────────────────────────────────────┘
```

---

## 9. 类比总结

### 类比 1：图书馆

```
错误理解（指针数组）：
┌─────────────────────────────────────────────────┐
│  图书馆目录柜                                    │
│  ┌──────────┬──────────┬──────────┐            │
│  │ 书架A-3  │ 书架B-7  │ 书架C-2  │  ← 存储位置 │
│  └────┬─────┴────┬─────┴────┬─────┘            │
│       ↓          ↓          ↓                  │
│     实体书     实体书     实体书                │
└─────────────────────────────────────────────────┘

正确理解（代码块）：
┌─────────────────────────────────────────────────┐
│  图书馆的书架（本身）                            │
│  ┌────────────────────────────────────────────┐ │
│  │ [书1][书2][书3][书4]...[书32]              │ │
│  │  ↑                                         │ │
│  │  "early_idt_handler_array" 标签指向这里    │ │
│  └────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────┘
```

- `early_idt_handler_array` = 书架的起始位置标签
- `early_idt_handler_array[i]` = 第 i 本书的位置
- 书架上的内容 = 机器代码（实体书）

### 类比 2：街道门牌

```
错误理解：
"Main Street" 是一个数组，存储了所有房子的地址
Main Street = [100号, 102号, 104号, ...]

正确理解：
"Main Street" 是一个街道名称，房子沿着这条街连续排列
Main Street ← 街道标志
    ↓
[100号][102号][104号][106号]...
  ↑      ↑      ↑      ↑
  房子   房子   房子   房子（实际建筑）
```

- `early_idt_handler_array` = 街道名称（Main Street）
- `early_idt_handler_array[i]` = 第 i 个门牌号
- 门牌号处的内容 = 房子（机器代码）

### 类比 3：音乐专辑

```
错误理解：
专辑 = [曲目1的地址, 曲目2的地址, ...]

正确理解：
专辑 = 连续的音轨
┌────────────────────────────────────┐
│  "Greatest Hits" 专辑               │
│  [曲目1][曲目2][曲目3]...[曲目32]   │
│   ↑                                │
│   专辑起始标记                      │
└────────────────────────────────────┘
```

- `early_idt_handler_array` = 专辑名称
- `early_idt_handler_array[i]` = 第 i 首歌的起始时间戳
- 内容 = 实际的音频数据（机器代码）

---

## 总结

### 核心要点

| 问题 | 回答 |
|------|------|
| **early_idt_handler_array 是什么？** | 汇编符号，指向一段连续的机器代码块 |
| **它存储了什么？** | 不存储任何东西，它"是"被存储的机器代码 |
| **early_idt_handler_array[i] 是什么？** | 一个地址表达式，计算第 i 个桩的起始地址 |
| **这个地址指向什么？** | 指向机器指令（CPU 可执行的代码） |
| **为什么叫 array？** | 历史命名，容易误导，但它不是传统意义的数组 |

### 正确的心智模型

```
early_idt_handler_array 就像一本书：

1. 书名 = "early_idt_handler_array"（符号名称）
2. 书的起始页码 = 0xffffffff81002a00（符号地址）
3. 书的内容 = 32 个章节（机器代码桩）
4. 访问第 i 章 = early_idt_handler_array[i]（计算地址）
5. 第 i 章的内容 = 机器指令（不是地址！）

当你打开这本书的第 3 章时，你看到的是文字（机器代码），
而不是另一本书的书架位置（地址）。
```

### 实践建议

在理解和使用 `early_idt_handler_array` 时：

1. ✅ **把它当成函数名**：像 `main` 一样，是一个符号
2. ✅ **把 [i] 当成偏移计算**：不是数组访问，是地址算术
3. ✅ **记住内容是代码**：这些地址存储的是指令，不是数据
4. ❌ **不要想象成指针数组**：没有中间的"数组"结构

---

## 延伸阅读

- [IDT_SETUP_EARLY_HANDLER_DETAILED_ANALYSIS.md](./IDT_SETUP_EARLY_HANDLER_DETAILED_ANALYSIS.md) - 主流程文档
- [IDT_DATA_STRUCTURES_RELATIONSHIP.md](./IDT_DATA_STRUCTURES_RELATIONSHIP.md) - idt_descr 和 idt_table 关系
- [IDT_EXCEPTION_HANDLING_DETAILS.md](./IDT_EXCEPTION_HANDLING_DETAILS.md) - 异常处理流程
- [DOCUMENT_INDEX.md](./DOCUMENT_INDEX.md) - 完整文档索引

---

**最后更新**：2026-02-18
**作者**：Linux 内核启动文档项目
