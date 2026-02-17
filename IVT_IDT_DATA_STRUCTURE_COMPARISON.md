# BIOS IVT 与 Kernel IDT 数据结构详细对比

**版本**: 1.2
**日期**: 2026-02-17
**作者**: Linux 内核启动文档项目
**更新内容**:
- v1.2: 添加设计哲学对比、"门"描述符深度解释、生动类比（木门 vs 金库门）
- v1.1: 添加详细的 SeaBIOS 和 Linux kernel 源代码引用

> 📚 **文档导航**: [返回总索引](DOCUMENT_INDEX.md) | [阅读指南](READING_GUIDE.md) | [IDT 演进](LINUX_KERNEL_IDT_EVOLUTION.md)

> **相关文档**：
> - 关于 **IVT 和 IDT 的软件中断服务程序对比**（BIOS 服务 vs 内核系统调用、硬件中断与软件中断的协作关系），请参见 [BIOS IVT 与 Kernel IDT 的软件中断服务程序对比](BIOS_IVT_VS_KERNEL_IDT.md)
> - 关于 **TSS 和 IST 机制**（IDT 中的 IST 字段用途、独立栈机制），请参见 [x86-64 任务状态段（TSS）与中断栈表（IST）详解](X86_64_TSS_AND_IST.md)
> - 关于 **idt_setup_early_handler() 函数详解**（Linux 内核如何初始化 IDT），请参见 [idt_setup_early_handler() 函数详细分析](IDT_SETUP_EARLY_HANDLER_DETAILED_ANALYSIS.md)

---

## 目录

1. [概述：两种截然不同的设计](#1-概述两种截然不同的设计)
   - 1.1 [设计哲学对比](#11-设计哲学对比)
   - 1.2 [生动类比：木门 vs 金库门](#12-生动类比木门-vs-金库门)
   - 1.3 [历史演进路径](#13-历史演进路径)
   - 1.4 [为什么 IDT 这么复杂？](#14-为什么-idt-这么复杂)
   - 1.5 [总结：复杂性的代价与收益](#15-总结复杂性的代价与收益)
2. [BIOS IVT (Interrupt Vector Table)](#2-bios-ivt-interrupt-vector-table)
3. [Kernel IDT (Interrupt Descriptor Table)](#3-kernel-idt-interrupt-descriptor-table)
   - 3.1 [IDT 的数据结构](#31-idt-的数据结构)
   - 3.2 [IDT 的位置和加载](#32-idt-的位置和加载)
   - 3.3 [CPU 查找 IDT 的过程](#33-cpu-查找-idt-的过程)
   - 3.4 [为什么叫"门"描述符？](#34-为什么叫门描述符)
4. [数据结构详细对比](#4-数据结构详细对比)
5. [硬件处理机制对比](#5-硬件处理机制对比)
6. [初始化代码对比](#6-初始化代码对比)
7. [从 IVT 到 IDT 的演进过程](#7-从-ivt-到-idt-的演进过程)
8. [为什么 x86-64 必须使用 IDT？](#8-为什么-x86-64-必须使用-idt)
9. [源代码索引](#9-源代码索引)

---

## 源代码快速索引

### SeaBIOS 源代码

| 数据结构/函数 | 文件路径 | 说明 |
|--------------|---------|------|
| `struct segoff_s` | seabios/src/types.h:49-52 | IVT 表项结构（段:偏移，4 字节） |
| `SET_IVT` 宏 | seabios/src/util.h:194-196 | 设置 IVT 条目的宏 |
| `ivt_init()` | seabios/src/post.c:568-650 | BIOS 启动时初始化 IVT |
| `entry_13` | seabios/src/romlayout.S:448-454 | INT 13h 磁盘服务入口 |
| `process_op()` | seabios/src/block.c:605-632 | INT 13h 磁盘操作 C 实现 |
| `SEG_IVT` | seabios/src/config.h:13 | IVT 表的段地址（0x0000） |
| `SEG_BIOS` | seabios/src/config.h:10 | BIOS 代码段地址（0xF000） |

### Linux Kernel 源代码

| 数据结构/函数 | 文件路径 | 说明 |
|--------------|---------|------|
| `struct gate_desc` | arch/x86/include/asm/desc_defs.h:79-91 | IDT 门描述符结构（16 字节） |
| `struct idt_bits` | arch/x86/include/asm/desc_defs.h:71-77 | IDT 控制位结构 |
| `struct desc_ptr` | arch/x86/include/asm/desc_defs.h:23-26 | IDTR 寄存器对应的结构 |
| `struct idt_data` | arch/x86/include/asm/desc_defs.h:105-112 | IDT 初始化中间数据结构 |
| `idt_table` | arch/x86/kernel/idt.c:45-48 | IDT 表全局数组（256 条目） |
| `idt_descr` | arch/x86/kernel/idt.c:175-178 | IDTR 描述符（用于 LIDT） |
| `idt_setup_early_handler()` | arch/x86/kernel/idt.c:317-331 | 早期 IDT 初始化函数 |
| `set_intr_gate()` | arch/x86/kernel/idt.c:237-244 | 设置中断门函数 |
| `idt_init_desc()` | arch/x86/kernel/idt.c:164-176 | 构建 16 字节门描述符 |
| `early_idt_handler_array` | arch/x86/kernel/head_64.S:357-365 | 早期异常处理程序数组 |
| `asm_exc_page_fault` | arch/x86/entry/entry_64.S:1195-1202 | Page Fault 处理程序入口 |
| `do_page_fault()` | arch/x86/mm/fault.c:1347-1355 | Page Fault C 实现 |
| `__KERNEL_CS` | arch/x86/include/asm/segment.h:203-205 | 内核代码段选择子（0x10） |
| `GATE_INTERRUPT` | arch/x86/include/asm/desc_defs.h:100-102 | Interrupt Gate 类型（0xE） |

---

## 1. 概述：两种截然不同的设计

**核心差异**：

| 特性 | BIOS IVT | Kernel IDT |
|------|----------|------------|
| **CPU 模式** | 实模式（Real Mode） | 保护模式/长模式（Protected/Long Mode） |
| **架构** | 16 位 | 32 位 / 64 位 |
| **表项大小** | **4 字节** | **16 字节** |
| **表项内容** | 直接包含处理程序地址（段:偏移） | 包含门描述符（复杂结构） |
| **地址模式** | 段:偏移（20 位物理地址） | 线性地址（32/64 位） |
| **固定位置** | ✅ 是（0x00000000） | ❌ 否（由 IDTR 指定） |
| **特权级** | ❌ 无（实模式无特权级） | ✅ 有（DPL, CPL） |
| **IST 支持** | ❌ 无 | ✅ 有（x86-64） |
| **硬件设计时代** | 8086（1978年） | 80286+（1982年+） |

**关键结论**：

- **IVT**：简单的地址数组，适合实模式的简单保护需求
- **IDT**：复杂的描述符表，支持现代操作系统的安全和性能需求
- **不兼容**：两者完全不兼容，从实模式切换到保护模式必须重建中断表

### 1.1 设计哲学对比

**IVT 的哲学："简单直接"**

```
8086 时代（1978）的假设：
- 单任务环境（一次只运行一个程序）
- 所有代码互相信任
- 内存空间小（1MB）
- 性能优先于安全

设计理念：
┌─────────────────────┐
│  简单的木门          │
│  ├─ 谁都能推开      │
│  ├─ 没有锁          │
│  └─ 直接通过        │
└─────────────────────┘
```

**IVT 实现的简单性**：

```assembly
; IVT 中的一个条目（4 字节）
[低 16 位] 偏移地址 (IP)
[高 16 位] 段地址 (CS)

; 当发生中断 N 时，CPU 直接：
IP = [0x0000 + N*4]      ; 读取偏移地址
CS = [0x0000 + N*4 + 2]  ; 读取段地址
; 然后跳转到 CS:IP

; 特点：
; - 没有权限检查：实模式下所有代码同级
; - 没有栈切换：当前用什么栈，中断来了还用什么栈
; - 没有保护：任何程序都可以直接修改 IVT（写入地址 0x0000）
```

**IDT 的哲学："隔离与控制"**

```
80286+ 时代（1982+）的需求：
- 多任务环境（多个程序同时运行）
- 用户程序不可信（需要隔离）
- 内存空间大（4GB → 16EB）
- 安全优先于简单

设计理念：
┌─────────────────────┐
│  银行金库门          │
│  ├─ 多重认证（DPL）  │
│  ├─ 自动切换通道（IST）│
│  ├─ 记录进出（压栈）  │
│  ├─ 不同类型（中断/陷阱）│
│  └─ 状态指示（Present）│
└─────────────────────┘
```

**IDT 复杂性的必要性**：

| 需求 | IVT 的缺失 | IDT 的解决 |
|------|----------|-----------|
| **权限控制** | ❌ 无特权级概念<br>用户程序可以修改 IVT | ✅ DPL/CPL 检查<br>Present 位<br>IDT 页表保护 |
| **地址空间** | ❌ 段:偏移（20 位，1MB） | ✅ 64 位线性地址<br>分散存储（low/middle/high） |
| **安全隔离** | ❌ 所有代码同一特权级 | ✅ 段选择子（确保跳转到内核代码段）<br>自动特权级切换 |
| **栈切换** | ❌ 始终使用当前栈<br>栈溢出 = 系统崩溃 | ✅ IST 独立栈<br>TSS.RSP0 特权级栈 |
| **功能细分** | ❌ 所有中断相同处理 | ✅ 中断门（关中断）<br>陷阱门（不关中断） |

### 1.2 生动类比：木门 vs 金库门

**IVT = 乡间小屋的木门**

```
┌──────────────────────┐
│   🚪 简易木门          │
│                      │
│   特点：              │
│   • 推门就能进        │
│   • 没有锁            │
│   • 谁都能开          │
│   • 随时可以卸下重装  │
│                      │
│   适用场景：          │
│   • 单身独居          │
│   • 邻里互信          │
│   • 没有贵重物品      │
└──────────────────────┘

对应 IVT：
• 4 字节简单地址
• 没有权限检查
• 任何程序可以修改
• DOS 单任务环境
```

**IDT = 银行金库门**

```
┌──────────────────────┐
│   🏦 银行金库门        │
│                      │
│   特点：              │
│   • 多重认证系统      │
│     （DPL 权限检查）  │
│   • 自动换通道        │
│     （IST 栈切换）    │
│   • 进出记录系统      │
│     （CPU 自动压栈）  │
│   • 不同类型门        │
│     （中断门/陷阱门）  │
│   • 状态指示灯        │
│     （Present 位）    │
│                      │
│   适用场景：          │
│   • 多用户环境        │
│   • 不可信访客        │
│   • 核心资产保护      │
└──────────────────────┘

对应 IDT：
• 16 字节复杂描述符
• DPL/CPL 权限检查
• 页表保护（只读）
• 现代多任务操作系统
```

### 1.3 历史演进路径

```
┌─────────────────────────────────────────────────────────────┐
│                   x86 中断表演进史                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  8086 (1978)            80286 (1982)            x86-64 (2003)│
│     ↓                       ↓                        ↓      │
│  ┌─────┐                ┌─────────┐             ┌──────────┐│
│  │ IVT │ ──保护模式引入─→ │  IDT   │ ──64位扩展─→ │ 64b IDT ││
│  │ 4B  │                │  8B    │             │  16B    ││
│  └─────┘                └─────────┘             └──────────┘│
│                                                             │
│  实模式                  保护模式                   长模式   │
│  • 段:偏移               • 段描述符                • 64位地址│
│  • 1MB 空间              • 4GB 空间                • 16EB空间│
│  • 无保护                • 4级保护环               • 同+IST │
│  • DOS 时代              • Windows 95-XP           • 现代OS │
└─────────────────────────────────────────────────────────────┘

关键转折点：
1. 1982：80286 引入保护模式 → IDT 诞生（需要权限隔离）
2. 1985：80386 扩展到 32 位 → IDT 扩展（支持 4GB 地址）
3. 2003：x86-64 长模式 → IDT 再扩展（支持 64 位 + IST 独立栈）
```

### 1.4 为什么 IDT 这么复杂？

IDT 的复杂性不是为了复杂而复杂，而是为了解决实际问题：

**问题 1：用户程序可能是恶意的**

```c
// IVT 时代的灾难（DOS 病毒常用手法）：
*(u32 *)(0x0000 + 0x21 * 4) = my_evil_handler;  // 劫持 DOS 系统调用

// IDT 的防护：
// - IDT 表受页表保护（用户态无法访问）
// - 即使内核也需要通过正规 API 修改
// - DPL 检查防止用户态跳转到任意内核代码
```

**问题 2：栈可能已经损坏**

```c
// 假设发生栈溢出，栈指针 RSP 已经指向非法地址
// IVT 时代：继续用当前栈 → 压栈失败 → 三重故障 → 重启

// IDT + IST 的解决：
IDT[8].IST = 1;  // #DF (Double Fault) 使用 IST[1] 独立栈
TSS.IST[1] = 0xfffffe0000006000;  // 预留的安全栈

// 结果：即使栈损坏，仍然可以处理异常，打印调试信息
```

**问题 3：需要区分不同中断场景**

```c
// 硬件中断（如键盘）：需要立即关中断，防止嵌套
IDT[33].type = GATE_INTERRUPT;  // 0xE，进入时 IF←0

// 异常处理（如断点）：不应关中断，保持系统响应
IDT[3].type = GATE_TRAP;        // 0xF，进入时 IF 不变
```

**问题 4：地址空间从 1MB 扩展到 16EB**

```
IVT：段(16位) + 偏移(16位) = 20位物理地址（1MB）
     ❌ 无法表示 64 位地址

IDT：offset_low(16位) + offset_middle(16位) + offset_high(32位)
     = 64位线性地址（理论 16EB，实际约 256TB）
     ✅ 满足现代操作系统需求
```

### 1.5 总结：复杂性的代价与收益

**IVT**：
- ✅ 简单快速，易于理解
- ✅ 适合单任务、可信环境
- ❌ 无安全保护，易受攻击
- ❌ 地址空间受限（1MB）
- 📅 适用时代：DOS（1981-1995）

**IDT**：
- ✅ 安全隔离，权限控制
- ✅ 支持大地址空间（64 位）
- ✅ 栈切换（IST），提高健壮性
- ✅ 功能细分（中断门/陷阱门）
- ❌ 结构复杂，初始化繁琐
- 📅 适用时代：现代操作系统（1995-至今）

**设计权衡**：

就像从**乡间小路的木栅栏**发展到**高速公路的多车道收费站**：
- 木栅栏简单，但无法应对车流量
- 收费站复杂，但能高效管理交通，防止事故

同样，IDT 的复杂性是现代操作系统多任务、多用户、高安全性需求的**必要代价**。

---

## 2. BIOS IVT (Interrupt Vector Table)

### 2.1 IVT 的数据结构

**IVT 是一个包含 256 个 4 字节条目的数组，每个条目包含一个段:偏移地址。**

#### 单个 IVT 条目结构

```
偏移量 | 大小 | 字段     | 说明
-------|------|---------|----------------------------------------
+0     | 2B   | Offset  | 中断处理程序的偏移地址（16 位）
+2     | 2B   | Segment | 中断处理程序的段地址（16 位）

总大小：4 字节
```

**示例：IVT[0x13]（磁盘服务）**

```
地址：0x0000:0x004C（物理地址 0x4C）

+0x004C: 0x12 0x34  ← 偏移地址 = 0x3412（小端序）
+0x004E: 0x00 0xF0  ← 段地址 = 0xF000

中断处理程序地址：0xF000:0x3412
物理地址 = 0xF000 × 16 + 0x3412 = 0xF3412
```

#### 完整 IVT 布局

```
物理地址范围：0x00000 - 0x003FF（1024 字节 = 256 × 4）

地址         | 向量号 | 中断类型
-------------|--------|------------------------------------------
0x0000-0x0003| 0x00   | #DE - Divide Error
0x0004-0x0007| 0x01   | #DB - Debug Exception
0x0008-0x000B| 0x02   | NMI
0x000C-0x000F| 0x03   | #BP - Breakpoint
...          | ...    | ...
0x0020-0x0023| 0x08   | IRQ0 - Timer (硬件中断)
0x0024-0x0027| 0x09   | IRQ1 - Keyboard (硬件中断)
...          | ...    | ...
0x0040-0x0043| 0x10   | INT 10h - Video Service (BIOS 服务)
...          | ...    | ...
0x004C-0x004F| 0x13   | INT 13h - Disk Service (BIOS 服务)
...          | ...    | ...
0x03FC-0x03FF| 0xFF   | 保留
```

### 2.2 IVT 的初始化

**SeaBIOS 初始化 IVT 的代码：**

```c
// seabios/src/post.c:568-582
static void
ivt_init(void)
{
    dprintf(3, "init ivt\n");

    // 初始化异常向量（0x00-0x1F）
    int i;
    for (i=0; i<0x20; i++)
        SET_IVT(i, FUNC16(entry_iret_official));

    // 初始化硬件中断向量（IRQ0-7：0x08-0x0F，IRQ8-15：0x70-0x77）
    for (i=BIOS_HWIRQ0_VECTOR; i<BIOS_HWIRQ0_VECTOR+8; i++)
        SET_IVT(i, FUNC16(entry_hwpic1));
    for (i=BIOS_HWIRQ8_VECTOR; i<BIOS_HWIRQ8_VECTOR+8; i++)
        SET_IVT(i, FUNC16(entry_hwpic2));

    // 初始化 BIOS 软件中断服务（INT 10h, 13h 等）
    // ...
}
```

**SET_IVT 宏定义：**

```c
// seabios/src/util.h:194-196
#define SET_IVT(vector, segoff) \
    SET_FARVAR(SEG_IVT, *(struct segoff_s *)(vector*4), segoff)

// seabios/src/types.h:49-52 - IVT 表项的数据结构
struct segoff_s {
    u16 offset;  // 偏移地址（16 位）
    u16 seg;     // 段地址（16 位）
} PACKED;

// seabios/src/config.h:13 - IVT 表的段地址
#define SEG_IVT  0x0000

// seabios/src/util.h:167 - FUNC16 宏：将 16 位函数地址转换为 segoff_s
#define FUNC16(func) ({                         \
    extern void func (void);                    \
    SEGOFF(SEG_BIOS, (u32)func - BUILD_BIOS_ADDR); \
})
```

**实际操作示例：INT 13h 磁盘服务**

```c
// seabios/src/post.c:635 - 设置 IVT[0x13] 指向磁盘服务处理程序
SET_IVT(0x13, FUNC16(entry_13));

// seabios/src/romlayout.S:448-454 - INT 13h 入口点（汇编代码）
ENTRY_ST(entry_13)
    ENTRY_INTO32  _cfunc32flat_process_op   // 切换到 32 位模式并调用 C 函数
    iretw                                     // 返回到调用者
ENTRY_END(entry_13)

// seabios/src/block.c:605-632 - INT 13h 的 C 函数实现
void VISIBLE32FLAT
process_op(struct disk_op_s *op)
{
    // 根据 AH 寄存器的值执行不同的磁盘操作
    switch (op->command) {
    case CMD_READ:      disk_read(op);  break;   // AH=02h：读扇区
    case CMD_WRITE:     disk_write(op); break;   // AH=03h：写扇区
    case CMD_VERIFY:    disk_verify(op); break;  // AH=04h：验证扇区
    case CMD_SEEK:      disk_seek(op);  break;   // AH=07h：寻道
    // ... 更多磁盘操作
    default:
        op->count = 0;
        disk_ret(op, DISK_RET_EPARAM);
    }
}

// 展开后的实际内存操作：
// 物理地址 0x4C（0x13 * 4）处写入：
*(u16 *)(0x0000004C) = offset_of_entry_13;  // 偏移地址（如 0x1234）
*(u16 *)(0x0000004E) = 0xF000;              // 段地址 SEG_BIOS

// 最终效果：INT 13h 处理程序地址 = 0xF000:0x1234
```

### 2.3 CPU 查找 IVT 的过程

**实模式下触发中断（以 INT 0x13 为例）：**

```
1. 用户程序执行：
   int 0x13

2. CPU 自动执行：
   ├─ 读取 IVT[0x13]：
   │    地址 = 0x0000:0x004C = 物理地址 0x4C
   │    读取 4 字节：
   │      偏移 = [0x4C] = 0x3412
   │      段   = [0x4E] = 0xF000
   │
   ├─ 计算物理地址：
   │    物理地址 = 0xF000 × 16 + 0x3412 = 0xF3412
   │
   ├─ 压栈（保存返回地址和标志）：
   │    push FLAGS
   │    push CS
   │    push IP
   │
   ├─ 清除中断标志：
   │    FLAGS.IF = 0（禁用中断）
   │
   └─ 跳转到处理程序：
        CS = 0xF000
        IP = 0x3412
        继续执行
```

**关键点**：

- IVT 地址**固定**在物理地址 0x00000
- CPU **直接读取** 4 字节（段:偏移）
- **没有权限检查**（实模式无特权级）
- **没有类型检查**（只是地址，不区分中断门/陷阱门）

---

## 3. Kernel IDT (Interrupt Descriptor Table)

### 3.1 IDT 的数据结构

**IDT 是一个包含 256 个 16 字节门描述符的数组，每个条目是一个复杂的结构。**

#### 单个 IDT 条目结构（x86-64）

```
偏移量 | 大小 | 字段            | 说明
-------|------|----------------|----------------------------------------
+0     | 2B   | offset_low     | 处理程序地址的低 16 位
+2     | 2B   | segment        | 代码段选择子（如 __KERNEL_CS = 0x10）
+4     | 2B   | bits           | 控制位（IST, Type, DPL, P）
+6     | 2B   | offset_middle  | 处理程序地址的中间 16 位
+8     | 4B   | offset_high    | 处理程序地址的高 32 位
+12    | 4B   | reserved       | 保留（必须为 0）

总大小：16 字节
```

**bits 字段详细结构（2 字节）：**

```
位      | 字段  | 大小 | 说明
--------|-------|------|------------------------------------------
0-2     | IST   | 3位  | Interrupt Stack Table 索引（0-7）
3-7     | zero  | 5位  | 必须为 0
8-12    | type  | 5位  | 门类型（Interrupt/Trap/Task Gate）
13-14   | DPL   | 2位  | Descriptor Privilege Level（0-3）
15      | P     | 1位  | Present 位（必须为 1）
```

**类型（type）值：**

| 值   | 类型                | 说明 |
|------|---------------------|------|
| 0xE  | Interrupt Gate（64位）| 禁用中断的门 |
| 0xF  | Trap Gate（64位）     | 不禁用中断的门 |
| 0x5  | Task Gate（已废弃）   | x86-32，x86-64 不支持 |

**Linux 内核中的结构定义：**

```c
// arch/x86/include/asm/desc_defs.h:79-91 - IDT 门描述符结构（x86-64）
struct gate_desc {
    u16         offset_low;      // 处理程序地址 [15:0]
    u16         segment;         // 代码段选择子
    struct idt_bits bits;        // 控制位（IST, type, DPL, P）
    u16         offset_middle;   // 处理程序地址 [31:16]
    u32         offset_high;     // 处理程序地址 [63:32]
    u32         reserved;        // 保留（必须为 0）
} __attribute__((packed));

// arch/x86/include/asm/desc_defs.h:71-77 - IDT 控制位结构
struct idt_bits {
    u16     ist     : 3,    // Interrupt Stack Table 索引（0-7，0 表示不使用）
            zero    : 5,    // 必须为 0（保留位）
            type    : 5,    // 门类型（0xE=Interrupt Gate, 0xF=Trap Gate）
            dpl     : 2,    // Descriptor Privilege Level（0-3）
            p       : 1;    // Present 位（必须为 1 表示有效）
} __attribute__((packed));

// arch/x86/include/asm/segment.h:203-205 - 内核代码段选择子
#define GDT_ENTRY_KERNEL_CS     2
#define __KERNEL_CS             (GDT_ENTRY_KERNEL_CS*8)  // 0x10

// arch/x86/include/asm/desc_defs.h:100-102 - 门类型常量（x86-64）
#define GATE_INTERRUPT          0xE  // Interrupt Gate（禁用中断）
#define GATE_TRAP               0xF  // Trap Gate（不禁用中断）
```

**示例：IDT[14]（#PF - Page Fault）**

```c
// arch/x86/kernel/idt.c:97-106 - Page Fault 处理程序的定义
static const __initconst struct idt_data def_idts[] = {
    // ...
    INTG(X86_TRAP_PF,       asm_exc_page_fault),  // 向量 14：Page Fault
    // ...
};

// arch/x86/include/asm/traps.h:19 - Page Fault 向量号常量
#define X86_TRAP_PF     14  // Page Fault 异常

// arch/x86/entry/entry_64.S:1195-1202 - Page Fault 处理程序入口（汇编）
SYM_CODE_START(asm_exc_page_fault)
    UNWIND_HINT_IRET_REGS offset=8              // 栈帧提示（有错误码）
    ASM_CLAC                                     // 清除 AC 标志
    call error_entry                             // 保存所有寄存器
    movq %rsp, %rdi                              // 第一个参数：pt_regs 指针
    movq ORIG_RAX(%rsp), %rsi                    // 第二个参数：错误码
    movq %cr2, %rdx                              // 第三个参数：CR2（缺页地址）
    call do_page_fault                           // 调用 C 函数处理
    jmp error_return                             // 返回
SYM_CODE_END(asm_exc_page_fault)

// arch/x86/mm/fault.c:1347-1355 - Page Fault 的 C 函数实现
void __visible noinline do_page_fault(struct pt_regs *regs,
                                       unsigned long error_code,
                                       unsigned long address)
{
    // 处理缺页异常：换入页面或触发 segfault
    handle_page_fault(regs, error_code, address);
}
```

**假设处理程序地址 = `0xffffffff81234567`（示例）：**

```
idt_table[14] 的内存布局（16 字节）：

+0:  0x45 0x67           ← offset_low = 0x4567（地址 [15:0]）
+2:  0x10 0x00           ← segment = 0x0010 (__KERNEL_CS)
+4:  0x8E 0x00           ← bits = 0x008E
                           ├─ IST = 0（不使用 IST，使用当前内核栈）
                           ├─ type = 0xE（Interrupt Gate，禁用中断）
                           ├─ DPL = 0（Ring 0 only，只能从内核触发）
                           └─ P = 1（Present，有效）
+6:  0x12 0x34           ← offset_middle = 0x1234（地址 [31:16]）
+8:  0x81 0xFF 0xFF 0xFF ← offset_high = 0xFFFFFF81（地址 [63:32]）
+12: 0x00 0x00 0x00 0x00 ← reserved = 0（必须为 0）

处理程序地址 = offset_high << 32 | offset_middle << 16 | offset_low
             = 0xFFFFFF81 << 32 | 0x1234 << 16 | 0x4567
             = 0xFFFFFFFF81234567（asm_exc_page_fault 的地址）
```

### 3.2 IDT 的位置和加载

**IDT 的位置由 IDTR（IDT Register）指定，不是固定的。**

#### IDTR 寄存器结构

```
x86-64 模式：

+0     | 2B   | Limit   | IDT 表大小 - 1（字节数）
+2     | 8B   | Base    | IDT 表的 64 位线性地址

总大小：10 字节
```

**Linux 内核中的定义：**

```c
// arch/x86/include/asm/desc_defs.h:23-26 - IDTR 寄存器对应的数据结构
struct desc_ptr {
    unsigned short size;        // IDT 表大小 - 1（以字节为单位）
    unsigned long address;      // IDT 表的 64 位线性地址
} __attribute__((packed));
```

**示例：Linux 内核的 IDT 描述符和表定义**

```c
// arch/x86/kernel/idt.c:45-48 - IDT 表的实际定义（256 个 16 字节条目）
gate_desc idt_table[IDT_ENTRIES] __page_aligned_bss;

// arch/x86/include/asm/desc_defs.h:348 - IDT 表大小常量
#define IDT_ENTRIES             256      // 256 个中断向量
#define IDT_TABLE_SIZE          (IDT_ENTRIES * 16)  // 4096 字节

// arch/x86/kernel/idt.c:175-178 - IDTR 描述符（用于 LIDT 指令）
static struct desc_ptr idt_descr __ro_after_init = {
    .size    = IDT_TABLE_SIZE - 1,              // 4095（IDTR.limit）
    .address = (unsigned long) idt_table,       // idt_table 数组的线性地址
};
```

**加载 IDT：**

```c
// arch/x86/kernel/idt.c:405-409
static inline void load_idt(const struct desc_ptr *dtr)
{
    asm volatile("lidt %0"::"m" (dtr->size));
}

// 调用：
load_idt(&idt_descr);
```

**LIDT 指令的操作：**

```asm
lidt (%rdi)   ; RDI = &idt_descr

; CPU 自动执行：
; IDTR.limit = idt_descr.size = 4095
; IDTR.base  = idt_descr.address = &idt_table
```

### 3.3 CPU 查找 IDT 的过程

**保护模式/长模式下触发中断（以 #PF 为例）：**

```
1. CPU 触发缺页异常（#PF，向量 14）

2. CPU 自动执行：
   ├─ 读取 IDTR：
   │    Base  = 0xffffffff82000000（假设）
   │    Limit = 4095
   │
   ├─ 计算 IDT 条目地址：
   │    地址 = Base + 向量号 × 16
   │         = 0xffffffff82000000 + 14 × 16
   │         = 0xffffffff820000E0
   │
   ├─ 读取 IDT[14]（16 字节门描述符）：
   │    offset_low    = 0x4567
   │    segment       = 0x0010 (__KERNEL_CS)
   │    bits.ist      = 0
   │    bits.type     = 0xE（Interrupt Gate）
   │    bits.dpl      = 0
   │    bits.p        = 1
   │    offset_middle = 0x1234
   │    offset_high   = 0xFFFFFF81
   │
   ├─ 组合处理程序地址：
   │    地址 = offset_high << 32 | offset_middle << 16 | offset_low
   │         = 0xFFFFFFFF81234567
   │
   ├─ 特权级检查：
   │    CPL（当前特权级）= 3（用户态）
   │    DPL（描述符特权级）= 0（内核态）
   │    → 允许切换（异常总是允许切换到更高特权级）
   │
   ├─ IST 检查：
   │    IST = 0（不使用独立栈）
   │    → 使用当前内核栈（或 TSS.RSP0 如果从用户态进入）
   │
   ├─ 压栈（保存返回地址和状态）：
   │    push SS        （如果特权级切换）
   │    push RSP       （如果特权级切换）
   │    push RFLAGS
   │    push CS
   │    push RIP
   │    push Error Code（#PF 会自动压入错误码）
   │
   ├─ 加载新的段和地址：
   │    CS = 0x0010 (__KERNEL_CS)
   │    RIP = 0xFFFFFFFF81234567
   │
   └─ 如果是 Interrupt Gate：
        RFLAGS.IF = 0（禁用中断）

3. 继续执行处理程序
```

**关键点**：

- IDT 地址**不固定**，由 IDTR 指定
- CPU 读取 **16 字节**复杂的门描述符
- **有权限检查**（DPL, CPL）
- **有类型区分**（Interrupt Gate vs Trap Gate）
- **支持 IST**（x86-64 独立栈机制）
- **支持跨特权级**（用户态→内核态）

### 3.4 为什么叫"门"描述符？

**"门"（Gate）是一个非常形象的比喻——它就像一扇带有权限检查的受控通道。**

#### 门的概念

IDT 中的每个条目被称为"门描述符"（Gate Descriptor），是因为它像一扇**有权限控制的、自动化的门**：

```
  用户态代码                 内核态中断处理
    [CPU]    ----------->    [Handler]
              ↑
              │
           🚪 门
        (IDT门描述符)
              │
        权限检查、栈切换、状态保存
```

当发生中断或异常时：
- CPU 不是直接跳转到处理程序（那样不安全）
- 而是**必须通过这扇"门"**
- 通过时，CPU 自动完成一系列安全检查和上下文切换

#### 门的三个关键功能

**1. 权限检查**：门上有"锁"（DPL 字段）

```c
// 只有满足权限要求的代码才能通过这扇门
if (软件中断 && 门的DPL < 当前CPL) {
    触发 #GP 异常（General Protection Fault）
}

// 注意：硬件中断和异常不检查 DPL
// 它们被认为是必须处理的紧急情况，无条件通过
```

**示例**：
- 用户态程序（CPL=3）执行 `int 0x80`（系统调用）
- CPU 检查 IDT[0x80] 的 DPL：
  - 如果 DPL=3：允许通过 ✅
  - 如果 DPL=0：触发 #GP ❌（用户态无权调用）

**2. 自动切换**：通过门时，CPU 自动执行一系列操作

```
通过门的自动操作（硬件完成）：
├─ 栈切换（如果需要）：
│    ├─ IST 非零：切换到 TSS.IST[IST-1] 指定的栈
│    └─ 特权级变化：切换到 TSS.RSP0（内核栈）
│
├─ 保存现场（压栈）：
│    ├─ push SS（如果特权级切换）
│    ├─ push RSP（如果特权级切换）
│    ├─ push RFLAGS
│    ├─ push CS
│    ├─ push RIP
│    └─ push Error Code（某些异常自动压入）
│
├─ 加载新的执行环境：
│    ├─ CS = 门描述符的 segment（通常是 __KERNEL_CS）
│    └─ RIP = 门描述符的 64 位地址
│
└─ 如果是 Interrupt Gate：
     RFLAGS.IF = 0（禁用中断）
```

**3. 目标固定**：门后面的处理函数地址不能被临时篡改

```c
// IDT 表通常设置为只读（__ro_after_init）
gate_desc idt_table[IDT_ENTRIES] __page_aligned_bss;

// 加载后，用户态程序无法修改 IDT
// 即使内核代码也受到页表保护的限制
```

#### 三种类型的门

x86-64 架构定义了三种门描述符，都存储在 IDT 中：

| 门类型 | Type 值 | 用途 | 进入时是否关中断 | Linux 使用场景 |
|--------|---------|------|-----------------|---------------|
| **中断门<br>（Interrupt Gate）** | 0xE | 处理硬件中断 | ✅ 是<br>（IF←0） | 硬件中断（IRQ）<br>某些异常（#PF, #DF） |
| **陷阱门<br>（Trap Gate）** | 0xF | 处理异常和系统调用 | ❌ 否<br>（IF 不变） | 大部分异常（#BP, #GP）<br>系统调用（int 0x80） |
| **任务门<br>（Task Gate）** | 0x5 | 硬件任务切换 | ✅ 是 | ❌ Linux 不使用<br>（x86-64 已废弃） |

**关键区别**：

```c
// arch/x86/include/asm/desc_defs.h:100-102
#define GATE_INTERRUPT  0xE  // 进入时：RFLAGS.IF = 0（禁用中断）
#define GATE_TRAP       0xF  // 进入时：RFLAGS.IF 保持不变

// Linux 内核的使用示例：
INTG(X86_TRAP_DE,  asm_exc_divide_error)     // 中断门：#DE（除法错误）
INTG(X86_TRAP_PF,  asm_exc_page_fault)       // 中断门：#PF（缺页异常）
SYSG(X86_TRAP_OF,  asm_exc_overflow)         // 系统门（陷阱门 + DPL=3）：#OF（溢出）
```

**为什么要区分？**

- **中断门**：关闭中断是为了防止**嵌套中断**破坏栈帧
  - 示例：处理键盘中断时，不希望被另一个键盘中断打断
  - 处理程序可以在合适的时候手动重新启用中断（`sti` 指令）

- **陷阱门**：不关中断是为了保持**响应性**
  - 示例：处理断点异常（#BP）时，仍然可以响应硬件中断
  - 处理缺页异常时可能需要很长时间（从磁盘换入页面），期间应响应中断

#### 生活化类比：办公楼门禁系统

想象一个**带门禁的办公楼**：

```
办公楼（CPU）的门禁系统（IDT 门描述符）：

┌─────────────────────────────────────┐
│  🏢 办公楼（CPU）                    │
│                                     │
│  🚪 门禁 1：普通门（DPL=3）          │
│     ├─ 任何人都能刷卡进入            │
│     └─ 用于：访客接待（系统调用）    │
│                                     │
│  🚪 门禁 2：紧急通道（Interrupt Gate）│
│     ├─ 火警时自动打开                │
│     ├─ 进入后自动锁门（关中断）      │
│     └─ 用于：火灾、地震（硬件中断）  │
│                                     │
│  🚪 门禁 3：安保通道（Trap Gate）    │
│     ├─ 发生异常时打开                │
│     ├─ 进入后不锁门（不关中断）      │
│     └─ 用于：内部维修（异常处理）    │
│                                     │
│  🏢 各个房间 = 中断处理函数           │
└─────────────────────────────────────┘
```

**紧急情况（硬件中断）发生时**：
1. 不需要刷卡（硬件中断不检查 DPL）
2. 直接推门而入
3. 门会自动通知安保（CPU 自动压栈）
4. 可能需要换鞋（切换栈）
5. 进去后自动锁门防止别人打扰（中断门关 IF）

#### 没有"门"会怎样？

如果 CPU 直接 `jmp` 到中断处理函数：

```c
// ❌ 假设没有门描述符，直接跳转
void bad_interrupt_handler() {
    // 问题 1：栈还是用户态的栈，可能很小，容易溢出
    // 问题 2：没有保存返回地址，无法返回
    // 问题 3：用户态程序可以跳转到任意内核代码（安全漏洞）
    // 问题 4：不知道是否需要关中断，可能导致嵌套中断破坏栈帧
}

// ✅ 通过门描述符
// CPU 自动完成：
// - 权限检查（DPL）
// - 栈切换（IST 或 TSS.RSP0）
// - 保存现场（SS, RSP, RFLAGS, CS, RIP）
// - 加载内核代码段和处理程序地址
// - 根据门类型决定是否关中断
```

#### 总结

**"门"（Gate）就是 CPU 从一个执行环境安全切换到另一个执行环境的受控通道。**

- **门的隐喻**：带权限检查、自动切换、状态保存的受控通道
- **门的种类**：中断门（关中断）、陷阱门（不关中断）、任务门（已废弃）
- **门的功能**：权限检查 + 自动切换 + 目标固定
- **没有门的后果**：无权限控制、无栈切换、无现场保存 = 安全漏洞 + 系统崩溃

这就是为什么 Intel 在设计 x86 保护模式时，选择了"门"（Gate）这个形象的名称——它精确地描述了这个机制的本质：**一扇需要权限、自动操作、连接两个世界的门**。

---

## 4. 数据结构详细对比

### 4.1 表项结构对比

```
┌─────────────────────────────────────────────────────────────┐
│  BIOS IVT 条目（4 字节）                                     │
├─────────────────────────────────────────────────────────────┤
│  +0 (2B): Offset  ← 处理程序偏移地址（16 位）              │
│  +2 (2B): Segment ← 处理程序段地址（16 位）                │
└─────────────────────────────────────────────────────────────┘
                        ↓
            物理地址 = Segment × 16 + Offset
                        ↓
                  最大 20 位（1MB）


┌─────────────────────────────────────────────────────────────┐
│  Kernel IDT 条目（16 字节）                                 │
├─────────────────────────────────────────────────────────────┤
│  +0  (2B): offset_low     ← 地址 [15:0]                     │
│  +2  (2B): segment        ← 段选择子（查 GDT）              │
│  +4  (2B): bits           ← IST(3) | zero(5) | type(5) |    │
│            ├─ IST(3位): 0-7                  DPL(2) | P(1)  │
│            ├─ type(5位): 0xE/0xF                            │
│            ├─ DPL(2位): 0-3                                 │
│            └─ P(1位): 0/1                                   │
│  +6  (2B): offset_middle  ← 地址 [31:16]                    │
│  +8  (4B): offset_high    ← 地址 [63:32]                    │
│  +12 (4B): reserved       ← 必须为 0                        │
└─────────────────────────────────────────────────────────────┘
                        ↓
         64 位线性地址 = offset_high << 32 |
                        offset_middle << 16 |
                        offset_low
```

### 4.2 大小对比

| 特性 | BIOS IVT | Kernel IDT |
|------|----------|------------|
| **单个条目大小** | 4 字节 | 16 字节 |
| **条目数量** | 256 | 256 |
| **总大小** | 1024 字节（1KB） | 4096 字节（4KB，1 页） |
| **地址空间** | 20 位（1MB） | 64 位（16EB） |
| **对齐要求** | 无（固定地址 0x0000） | 页对齐（4KB 边界） |

### 4.3 字段对比

| 功能 | BIOS IVT | Kernel IDT |
|------|----------|------------|
| **处理程序地址** | 直接存储（段:偏移，4 字节） | 分段存储（低/中/高，8 字节） |
| **段选择子** | ❌ 无（直接段地址） | ✅ 有（2 字节，查 GDT） |
| **类型标识** | ❌ 无 | ✅ 有（Interrupt/Trap Gate） |
| **特权级** | ❌ 无 | ✅ 有（DPL，0-3） |
| **IST 支持** | ❌ 无 | ✅ 有（x86-64，3 位） |
| **Present 位** | ❌ 无 | ✅ 有（1 位） |
| **保留字段** | ❌ 无 | ✅ 有（4 字节） |

### 4.4 地址计算对比

**IVT 地址计算（实模式）：**

```
物理地址 = Segment × 16 + Offset

示例：
Segment = 0xF000
Offset  = 0x3412
物理地址 = 0xF000 × 16 + 0x3412
         = 0xF0000 + 0x3412
         = 0xF3412（20 位）

特点：
- 简单的线性计算
- 最大 20 位（1MB）
- 无需查表（GDT/LDT）
```

**IDT 地址计算（保护模式/长模式）：**

```
步骤 1：组合处理程序地址
线性地址 = offset_high << 32 | offset_middle << 16 | offset_low

示例：
offset_high   = 0xFFFFFF81
offset_middle = 0x1234
offset_low    = 0x4567
线性地址 = 0xFFFFFF81 << 32 | 0x1234 << 16 | 0x4567
         = 0xFFFFFFFF81234567（64 位）

步骤 2：查 GDT 获取段基址（保护模式，长模式下通常为 0）
段选择子 = 0x0010 (__KERNEL_CS)
查 GDT[2]（0x10 >> 3 = 2）
段基址 = 0（长模式下代码段基址总是 0）

步骤 3：计算最终地址
物理地址 = 段基址 + 线性地址
         = 0 + 0xFFFFFFFF81234567
         = 0xFFFFFFFF81234567（通过页表转换为物理地址）

特点：
- 复杂的多级查找
- 最大 64 位（理论上 16EB，实际约 48 位）
- 需要查 GDT
- 需要页表转换
```

---

## 5. 硬件处理机制对比

### 5.1 中断触发时的 CPU 行为

#### IVT（实模式）

```
1. CPU 收到中断（向量号 N）

2. 读取 IVT[N]：
   地址 = 0x0000 + N × 4
   读取 4 字节：
     Offset  = [地址 + 0]
     Segment = [地址 + 2]

3. 压栈（6 字节）：
   push FLAGS（2 字节）
   push CS（2 字节）
   push IP（2 字节）

4. 清除中断标志：
   FLAGS.IF = 0（禁用中断）
   FLAGS.TF = 0（禁用单步）

5. 跳转：
   CS = Segment
   IP = Offset

6. 继续执行处理程序
```

**栈帧布局（实模式）：**

```
高地址
┌──────────────┐
│  FLAGS（旧） │ ← 返回前的标志寄存器
├──────────────┤
│  CS（旧）    │ ← 返回地址段
├──────────────┤
│  IP（旧）    │ ← 返回地址偏移
├──────────────┤ ← SP（进入处理程序后）
│  ...          │
低地址
```

#### IDT（保护模式/长模式）

```
1. CPU 收到中断（向量号 N）

2. 读取 IDTR：
   Base  = IDTR.base
   Limit = IDTR.limit

3. 检查向量号：
   if (N × 16 > Limit) → #GP（向量号越界）

4. 读取 IDT[N]：
   地址 = Base + N × 16
   读取 16 字节门描述符

5. 检查 Present 位：
   if (P == 0) → #NP（段不存在）

6. 特权级检查：
   DPL = 门描述符的 DPL
   CPL = 当前特权级
   if (软件中断 && DPL < CPL) → #GP（特权级违规）

7. IST 检查（x86-64）：
   if (IST != 0) {
       从 TSS.IST[IST-1] 读取栈地址
       切换到独立栈
   } else if (CPL 改变) {
       从 TSS.RSP0 读取内核栈地址
       切换到内核栈
   }

8. 压栈（x86-64，可变大小）：
   if (CPL 改变) {
       push SS（8 字节）
       push RSP（8 字节）
   }
   push RFLAGS（8 字节）
   push CS（8 字节）
   push RIP（8 字节）
   if (有错误码) {
       push Error Code（8 字节）
   }

9. 加载新段和地址：
   CS = 门描述符的 segment
   RIP = 组合的 64 位地址

10. 如果是 Interrupt Gate：
    RFLAGS.IF = 0（禁用中断）
    如果是 Trap Gate：
    保持 RFLAGS.IF 不变

11. 继续执行处理程序
```

**栈帧布局（x86-64，特权级切换）：**

```
高地址
┌──────────────┐
│  SS（旧）    │ ← 用户态栈段（8 字节）
├──────────────┤
│  RSP（旧）   │ ← 用户态栈指针（8 字节）
├──────────────┤
│  RFLAGS（旧）│ ← 返回前的标志（8 字节）
├──────────────┤
│  CS（旧）    │ ← 返回代码段（8 字节）
├──────────────┤
│  RIP（旧）   │ ← 返回地址（8 字节）
├──────────────┤
│  Error Code  │ ← 错误码（如果有，8 字节）
├──────────────┤ ← RSP（进入处理程序后）
│  ...          │
低地址
```

### 5.2 关键差异

| 操作 | IVT（实模式） | IDT（保护模式/长模式） |
|------|--------------|----------------------|
| **查找表** | 固定地址 0x0000 | IDTR 指定的地址 |
| **读取大小** | 4 字节 | 16 字节 |
| **权限检查** | ❌ 无 | ✅ 有（DPL vs CPL） |
| **类型检查** | ❌ 无 | ✅ 有（Interrupt/Trap） |
| **栈切换** | ❌ 无（始终当前栈） | ✅ 有（IST, RSP0） |
| **压栈大小** | 6 字节（固定） | 40-48 字节（可变） |
| **错误码** | ❌ 不支持 | ✅ 支持（某些异常） |
| **禁用中断** | ✅ 总是（IF=0, TF=0） | ⚠️ 取决于类型（Interrupt Gate 禁用，Trap Gate 不禁用） |

---

## 6. 初始化代码对比

### 6.1 BIOS IVT 初始化

```c
// seabios/src/post.c:568-582 - BIOS 启动时初始化 IVT
static void
ivt_init(void)
{
    dprintf(3, "init ivt\n");

    // 初始化所有异常向量（0x00-0x1F，CPU 保留的异常）
    int i;
    for (i=0; i<0x20; i++)
        SET_IVT(i, FUNC16(entry_iret_official));  // 默认处理程序：直接 IRET 返回

    // 初始化硬件中断向量（主 PIC：IRQ0-7，映射到 0x08-0x0F）
    for (i=BIOS_HWIRQ0_VECTOR; i<BIOS_HWIRQ0_VECTOR+8; i++)
        SET_IVT(i, FUNC16(entry_hwpic1));         // 主 PIC 中断处理

    // 初始化硬件中断向量（从 PIC：IRQ8-15，映射到 0x70-0x77）
    for (i=BIOS_HWIRQ8_VECTOR; i<BIOS_HWIRQ8_VECTOR+8; i++)
        SET_IVT(i, FUNC16(entry_hwpic2));         // 从 PIC 中断处理

    // 初始化 BIOS 软件中断服务（INT 10h-1Ah）
    // seabios/src/post.c:600-650
    SET_IVT(0x10, FUNC16(entry_10));  // INT 10h - 视频服务
    SET_IVT(0x13, FUNC16(entry_13));  // INT 13h - 磁盘服务
    SET_IVT(0x15, FUNC16(entry_15));  // INT 15h - 系统服务
    SET_IVT(0x16, FUNC16(entry_16));  // INT 16h - 键盘服务
    SET_IVT(0x1a, FUNC16(entry_1a));  // INT 1Ah - 时钟服务
    // ... 更多 BIOS 服务
}

// seabios/src/config.h:42-43 - 硬件中断向量号常量
#define BIOS_HWIRQ0_VECTOR  0x08  // 主 PIC 起始向量（IRQ0-7）
#define BIOS_HWIRQ8_VECTOR  0x70  // 从 PIC 起始向量（IRQ8-15）

// seabios/src/config.h:10 - BIOS 代码段地址
#define SEG_BIOS            0xF000

// SET_IVT 宏展开示例（以 INT 13h 为例）
SET_IVT(0x13, FUNC16(entry_13));

// 第一层展开（FUNC16）：
SET_IVT(0x13, SEGOFF(SEG_BIOS, (u32)entry_13 - BUILD_BIOS_ADDR));

// 第二层展开（SET_IVT）：
SET_FARVAR(SEG_IVT, *(struct segoff_s *)(0x13*4),
           SEGOFF(0xF000, offset_of_entry_13));

// 最终效果：写入物理地址 0x4C（0x13 * 4）
*(u16 *)(0x0000 + 0x13 * 4 + 0) = offset_of_entry_13;  // 偏移地址
*(u16 *)(0x0000 + 0x13 * 4 + 2) = 0xF000;              // 段地址 SEG_BIOS
```

**特点**：
- **简单直接**：直接写入固定物理地址（0x0000）
- **无结构复杂性**：只是段:偏移地址（4 字节）
- **无权限设置**：实模式无特权级概念
- **批量初始化**：循环设置异常和硬件中断向量

### 6.2 Linux Kernel IDT 初始化

```c
// arch/x86/kernel/idt.c:317-331 - 早期 IDT 初始化（内核启动时）
void __init idt_setup_early_handler(void)
{
    int i;

    // 设置前 32 个异常向量（0-31，CPU 定义的异常）
    for (i = 0; i < NUM_EXCEPTION_VECTORS; i++)
        set_intr_gate(i, early_idt_handler_array[i]);

    // 加载新的 IDT（通过 LIDT 指令）
    load_idt(&idt_descr);
}

// arch/x86/kernel/idt.c:59 - 异常向量数量常量
#define NUM_EXCEPTION_VECTORS   32  // 0-31 是 CPU 定义的异常

// arch/x86/kernel/idt.c:237-244 - 设置中断门（Interrupt Gate）
static __init void set_intr_gate(unsigned int n, const void *addr)
{
    struct idt_data data;

    // 初始化 idt_data 临时结构
    init_idt_data(&data, n, addr);

    // 将 idt_data 转换为 gate_desc 并写入 idt_table
    idt_setup_from_table(idt_table, &data, 1, false);
}

// arch/x86/kernel/idt.c:95-102 - 初始化 idt_data 结构的宏
#define init_idt_data(data, n, addr)                \
do {                                                 \
    (data)->vector   = (n);                          /* 向量号 */        \
    (data)->bits.ist = DEFAULT_STACK;                /* IST = 0（不使用独立栈） */  \
    (data)->bits.type = GATE_INTERRUPT;              /* 0xE（Interrupt Gate，禁用中断） */  \
    (data)->bits.dpl  = DPL0;                        /* 特权级 0（只能从内核调用） */  \
    (data)->bits.p    = 1;                           /* Present = 1（有效） */  \
    (data)->addr      = (addr);                      /* 处理程序地址 */  \
    (data)->segment   = __KERNEL_CS;                 /* 内核代码段选择子 0x10 */  \
} while (0)

// arch/x86/include/asm/desc_defs.h:105-112 - idt_data 中间数据结构
struct idt_data {
    unsigned int    vector;      // 中断向量号（0-255）
    unsigned int    segment;     // 代码段选择子
    struct idt_bits bits;        // 控制位（IST, type, DPL, P）
    const void      *addr;       // 处理程序地址
};

// arch/x86/kernel/idt.c:182-192 - 从 idt_data 构建 gate_desc 并写入 IDT
static __init void
idt_setup_from_table(gate_desc *idt, const struct idt_data *t,
                     int size, bool sys)
{
    gate_desc desc;

    for (; size > 0; t++, size--) {
        // 将 idt_data 转换为 gate_desc（16 字节门描述符）
        idt_init_desc(&desc, t);

        // 写入 IDT 表（memcpy）
        write_idt_entry(idt, t->vector, &desc);
    }
}

// arch/x86/kernel/idt.c:164-176 - 构建 16 字节门描述符
static inline void idt_init_desc(gate_desc *gate,
                                  const struct idt_data *d)
{
    unsigned long addr = (unsigned long) d->addr;  // 64 位处理程序地址

    gate->offset_low    = (u16) addr;              // 地址 [15:0]
    gate->segment       = (u16) d->segment;        // 段选择子（0x10）
    gate->bits          = d->bits;                 // 控制位（IST, type, DPL, P）
    gate->offset_middle = (u16) (addr >> 16);      // 地址 [31:16]
    gate->offset_high   = (u32) (addr >> 32);      // 地址 [63:32]
    gate->reserved      = 0;                       // 保留字段必须为 0
}

// arch/x86/include/asm/desc.h:146-149 - 写入 IDT 条目
static inline void write_idt_entry(gate_desc *idt, int entry,
                                    const gate_desc *gate)
{
    memcpy(&idt[entry], gate, sizeof(*gate));  // 复制 16 字节到 idt_table[entry]
}

// arch/x86/kernel/idt.c:405-409 - 加载 IDT（通过 LIDT 指令）
static inline void load_idt(const struct desc_ptr *dtr)
{
    asm volatile("lidt %0"::"m" (dtr->size));  // LIDT 指令：加载 IDTR 寄存器
}
```

**early_idt_handler_array 的定义：**

```c
// arch/x86/kernel/head_64.S:357-365 - 早期异常处理程序数组（汇编代码）
ENTRY(early_idt_handler_array)
    i = 0
    .rept NUM_EXCEPTION_VECTORS  // 重复 32 次（0-31 号异常）
    .if ((EXCEPTION_ERRCODE_MASK >> i) & 1) == 0  // 判断是否有错误码
        UNWIND_HINT_IRET_REGS                      // 无错误码：6 个寄存器（SS,RSP,RFLAGS,CS,RIP）
        pushq $0                                   // 手动压入假错误码（对齐栈帧）
    .else
        UNWIND_HINT_IRET_REGS offset=8             // 有错误码：7 个寄存器（+Error Code）
    .endif
    pushq $i                                       // 压入向量号
    jmp early_idt_handler_common                   // 跳转到通用处理程序
    i = i + 1
    .endr
END(early_idt_handler_array)

// 结果：生成 32 个函数入口，每个入口 9-12 字节（根据是否有错误码）
// 向量  0 (#DE): early_idt_handler_array[0]  → pushq $0; pushq $0; jmp ...
// 向量  8 (#DF): early_idt_handler_array[8]  → pushq $8; jmp ...（有错误码）
// 向量 14 (#PF): early_idt_handler_array[14] → pushq $14; jmp ...（有错误码）
// ...
```

**特点**：
- **复杂结构**：需要构建 16 字节的门描述符（offset_low/middle/high, segment, bits, reserved）
- **多层抽象**：idt_data（中间结构）→ gate_desc（门描述符）→ idt_table（IDT 表）
- **权限管理**：设置 DPL=0, type=0xE, P=1 等控制位
- **类型安全**：区分 Interrupt Gate（0xE）和 Trap Gate（0xF）
- **批量初始化**：循环设置 32 个异常向量，每个向量对应 early_idt_handler_array 中的处理程序
- **汇编生成**：early_idt_handler_array 是汇编代码中用 .rept 指令生成的 32 个函数入口数组

---

## 7. 从 IVT 到 IDT 的演进过程

### 7.1 启动时的表切换

**完整的中断表演进流程：**

```
┌─────────────────────────────────────────────────────────────┐
│  阶段 0：BIOS 控制                                           │
├─────────────────────────────────────────────────────────────┤
│  模式：实模式（16 位）                                       │
│  表：  IVT（固定地址 0x0000）                               │
│  大小：1024 字节（256 × 4）                                 │
│  作用：处理 BIOS 服务、硬件中断                             │
└─────────────────────────────────────────────────────────────┘
                        ↓
                  引导加载程序（GRUB）加载内核
                        ↓
┌─────────────────────────────────────────────────────────────┐
│  阶段 1：压缩内核的临时 IDT                                 │
├─────────────────────────────────────────────────────────────┤
│  模式：长模式（64 位）                                       │
│  表：  bringup_idt_table                                     │
│  位置：arch/x86/boot/compressed/idt_64.c                    │
│  大小：4096 字节（256 × 16）                                │
│  作用：解压内核时的基本异常处理                             │
│  特点：IST = 0（不使用独立栈）                             │
└─────────────────────────────────────────────────────────────┘
                        ↓
                  内核解压完成，跳转到主内核
                        ↓
┌─────────────────────────────────────────────────────────────┐
│  阶段 2：早期主内核 IDT（idt_setup_early_handler）         │
├─────────────────────────────────────────────────────────────┤
│  模式：长模式（64 位）                                       │
│  表：  idt_table                                             │
│  位置：arch/x86/kernel/idt.c                                │
│  大小：4096 字节（256 × 16）                                │
│  作用：处理前 32 个异常（0-31）                             │
│  特点：IST = 0（TSS 尚未初始化）                           │
└─────────────────────────────────────────────────────────────┘
                        ↓
                  TSS 初始化（cpu_init）
                        ↓
┌─────────────────────────────────────────────────────────────┐
│  阶段 3：完整的运行时 IDT（idt_setup_traps）               │
├─────────────────────────────────────────────────────────────┤
│  模式：长模式（64 位）                                       │
│  表：  idt_table（同一个表，重新填充）                      │
│  大小：4096 字节（256 × 16）                                │
│  作用：处理所有异常和中断（0-255）                          │
│  特点：关键异常使用 IST（#DF, NMI, #MC）                   │
└─────────────────────────────────────────────────────────────┘
```

### 7.2 为什么不能继续使用 IVT？

**IVT 只能在实模式下使用，原因：**

1. **地址空间限制**：
   - IVT 只支持 20 位物理地址（1MB）
   - 保护模式/长模式需要 32/64 位地址

2. **无特权级保护**：
   - 实模式无 Ring 0-3 概念
   - 保护模式需要 DPL/CPL 检查

3. **无类型区分**：
   - IVT 只是简单的地址
   - IDT 需要区分 Interrupt Gate, Trap Gate

4. **无栈切换支持**：
   - IVT 始终使用当前栈
   - IDT 支持 IST 独立栈

5. **硬件不支持**：
   - CPU 在保护模式/长模式下**强制使用 IDT**
   - IDTR 寄存器取代固定地址 0x0000

**关键代码：切换到保护模式时必须加载 IDT**

```asm
; arch/x86/boot/compressed/head_64.S
; 切换到保护模式前
lgdt gdt_ptr        ; 加载 GDT
lidt idt_ptr        ; 加载 IDT（必须，否则 CPU 异常）
mov cr0, eax        ; 启用保护模式（PE = 1）
```

---

## 8. 为什么 x86-64 必须使用 IDT？

### 8.1 x86-64 的强制要求

**Intel SDM 明确规定**（Volume 3A, Section 6.14）：

> In IA-32e mode (long mode), the processor uses the IDT structure
> described in this section. **The real-address mode IVT structure
> is not supported in IA-32e mode.**

**翻译**：在 IA-32e 模式（长模式）下，处理器使用本节描述的 IDT 结构。**实模式的 IVT 结构在 IA-32e 模式下不被支持。**

### 8.2 技术原因

**1. 64 位地址空间**

```
IVT：
┌────────────────────┐
│  段:偏移（4 字节） │
└────────────────────┘
        ↓
物理地址 = 段 × 16 + 偏移
最大 20 位（1MB）❌

IDT：
┌────────────────────┐
│  64 位线性地址     │
│  （8 字节）        │
└────────────────────┘
        ↓
64 位地址空间 ✅
```

**2. 安全性需求**

```
IVT：
- 无 DPL（特权级）检查❌
- 任何代码都可以修改 IVT
- 任何代码都可以调用任何中断

IDT：
- 有 DPL 检查✅
- 只有内核可以修改 IDT
- 用户态只能调用 DPL=3 的门
```

**3. 栈切换支持**

```
IVT：
- 始终使用当前栈❌
- 栈溢出会导致三重故障

IDT：
- 支持 TSS.RSP0（特权级切换）✅
- 支持 IST（独立栈）✅
- 栈溢出有独立的 #DF 栈
```

**4. 硬件设计**

```
x86-64 CPU 在长模式下：
1. 不查 IVT（地址 0x0000）
2. 强制查 IDTR 指定的 IDT
3. 读取 16 字节门描述符
4. 执行完整的权限和类型检查
```

### 8.3 对比总结

| 特性 | BIOS IVT | Kernel IDT | 为什么必须用 IDT？ |
|------|----------|------------|-------------------|
| **CPU 模式** | 实模式 | 保护/长模式 | x86-64 强制长模式 |
| **地址空间** | 20 位（1MB） | 64 位（16EB） | 支持大内存 |
| **安全性** | 无 | 有（DPL/CPL） | 防止权限提升 |
| **栈切换** | 无 | 有（IST/RSP0） | 防止栈溢出崩溃 |
| **类型系统** | 无 | 有（Interrupt/Trap） | 控制中断状态 |
| **错误恢复** | 无 | 有（#DF 独立栈） | 提高系统健壮性 |

---

## 10. 总结

### 10.1 核心差异

**BIOS IVT（实模式）**：
- **简单**：4 字节条目，直接段:偏移地址
- **固定**：物理地址 0x0000
- **快速**：无复杂检查
- **受限**：20 位地址空间，无安全机制
- **适用**：简单的 BIOS 环境

**Kernel IDT（保护/长模式）**：
- **复杂**：16 字节条目，包含门描述符
- **灵活**：IDTR 指定位置
- **安全**：DPL/CPL 检查，类型系统
- **强大**：64 位地址空间，IST 独立栈
- **适用**：现代操作系统

### 10.2 演进必然性

```
8086（1978）→ IVT：实模式，简单足够
                ↓
80286（1982）→ IDT：保护模式，需要安全
                ↓
80386（1985）→ IDT：32 位，需要大地址
                ↓
x86-64（2003）→ IDT：长模式，强制要求
```

### 10.3 关键要点

1. **数据结构完全不同**：
   - IVT：4 字节简单地址
   - IDT：16 字节复杂描述符

2. **硬件处理机制不同**：
   - IVT：固定地址，直接跳转
   - IDT：IDTR 指定，权限检查，栈切换

3. **不能共存**：
   - CPU 在保护/长模式下**强制使用 IDT**
   - 从实模式切换必须重建中断表

4. **设计哲学不同**：
   - IVT：简单、快速、直接
   - IDT：安全、灵活、可控

---

## 11. 参考文献

### 11.1 Intel 手册

1. **Intel 64 and IA-32 Architectures Software Developer's Manual**
   - Volume 3A, Chapter 6: Interrupt and Exception Handling
   - Volume 3A, Section 6.10: Interrupt Descriptor Table (IDT)
   - Volume 3A, Section 6.14: Exception and Interrupt Handling in 64-Bit Mode

### 11.2 Linux 内核源代码

2. **arch/x86/kernel/idt.c**
   - `idt_table` 定义
   - `idt_setup_early_handler()` 函数
   - `set_intr_gate()` 函数

3. **arch/x86/include/asm/desc_defs.h**
   - `gate_desc` 结构定义
   - `idt_bits` 结构定义

4. **arch/x86/boot/compressed/idt_64.c**
   - `bringup_idt_table` 定义

5. **arch/x86/kernel/head_64.S**
   - `early_idt_handler_array` 定义

6. **arch/x86/entry/entry_64.S**
   - 异常处理程序入口（如 `asm_exc_page_fault`）

7. **arch/x86/mm/fault.c**
   - Page Fault C 实现

### 11.3 SeaBIOS 源代码

8. **seabios/src/post.c**
   - `ivt_init()` 函数

9. **seabios/src/util.h**
   - `SET_IVT` 宏定义

10. **seabios/src/types.h**
    - `struct segoff_s` 定义

11. **seabios/src/romlayout.S**
    - BIOS 中断服务入口（如 `entry_13`）

12. **seabios/src/block.c**
    - INT 13h 磁盘服务 C 实现

### 11.4 相关文档

13. [LINUX_KERNEL_IDT_EVOLUTION.md](LINUX_KERNEL_IDT_EVOLUTION.md)
    - Linux IDT 表的演进流程

14. [IDT_SETUP_EARLY_HANDLER_DETAILED_ANALYSIS.md](IDT_SETUP_EARLY_HANDLER_DETAILED_ANALYSIS.md)
    - `idt_setup_early_handler()` 函数详细分析

15. [X86_64_TSS_AND_IST.md](X86_64_TSS_AND_IST.md)
    - TSS 和 IST 机制详解

---

**文档结束**
