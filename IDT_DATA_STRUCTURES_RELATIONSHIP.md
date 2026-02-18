# IDT 数据结构关系详解

**所属文档系列**：Linux x86_64 IDT 初始化机制分析
**主文档**：[IDT_SETUP_EARLY_HANDLER_DETAILED_ANALYSIS.md](./IDT_SETUP_EARLY_HANDLER_DETAILED_ANALYSIS.md)
**相关文档**：
- [IDT_COMPLETE_VECTOR_TABLE.md](./IDT_COMPLETE_VECTOR_TABLE.md) - 完整向量表参考手册

---

## 目录

1. [idt_descr 和 idt_table 的关系](#1-idt_descr-和-idt_table-的关系)
   - [核心关系：指针 vs 数据](#核心关系指针-vs-数据)
   - [详细对比](#详细对比)
   - [内存布局示例](#内存布局示例)
   - [使用流程](#使用流程)
   - [为什么需要 idt_descr](#为什么需要-idt_descr)
   - [完整关系图](#完整关系图)
2. [门描述符 (gate_desc) 的十六进制数据格式](#2-门描述符-gate_desc-的十六进制数据格式)
   - [16 字节内存布局](#16-字节内存布局)
   - [bits 字段位分解](#bits-字段位分解)
   - [完整的 16 字节十六进制数据示例](#完整的-16-字节十六进制数据示例)
   - [多个向量的实际数据对比](#多个向量的实际数据对比)

---

## 1. idt_descr 和 idt_table 的关系

### 核心关系：指针 vs 数据

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

### 详细对比

| 对比项 | idt_table | idt_descr |
|--------|----------|-----------|
| **数据类型** | `gate_desc[256]` | `struct desc_ptr` |
| **大小** | 4096 字节 (256 × 16) | 10 字节 (2 + 8) |
| **作用** | 存储 256 个门描述符（实际数据） | 存储 idt_table 的地址和大小（元信息） |
| **内容** | 256 个异常/中断处理程序的详细信息 | `.size = 4095`, `.address = &idt_table` |
| **被谁使用** | CPU 硬件（通过 IDTR 访问） | `lidt` 指令（用于加载 IDTR） |
| **可修改性** | 运行时可写入（后期设为只读） | 编译时初始化（后期设为只读） |
| **类比** | 图书馆的书架和书籍 | 图书馆的地址和规模 |

### 内存布局示例

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

### 使用流程

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

### 为什么需要 idt_descr？

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

### 完整关系图

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

## 2. 门描述符 (gate_desc) 的十六进制数据格式

### 16 字节内存布局

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

### bits 字段位分解

**bits 字段的实际值: 0x8E00 (小端序存储)**

```
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

### 完整的 16 字节十六进制数据示例

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

### 多个向量的实际数据对比

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

---

## 相关源代码

### idt_init_desc() - 构建门描述符

**源代码位置**：`arch/x86/include/asm/desc.h:418-430`

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

### write_idt_entry() - 原子写入 idt_table

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

---

## 返回导航

- [返回主文档](./IDT_SETUP_EARLY_HANDLER_DETAILED_ANALYSIS.md)
- [查看完整向量表](./IDT_COMPLETE_VECTOR_TABLE.md)
- [查看文档索引](./DOCUMENT_INDEX.md)
