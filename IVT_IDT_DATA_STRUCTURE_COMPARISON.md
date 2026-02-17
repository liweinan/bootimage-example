# BIOS IVT 与 Kernel IDT 数据结构详细对比

**版本**: 1.6
**日期**: 2026-02-18
**作者**: Linux 内核启动文档项目
**更新内容**:
- v1.6: 添加 `segoff` 和 `segoff_s` 关系深度解析（6.1.1 节）
  - 详细解释命名关系：`segoff_s` 是类型，`segoff` 是字段
  - Union 设计的巧妙之处：同一内存的两种视图
  - 内存布局图示（小端序，4 字节）
  - 两种等价访问方式的代码示例
  - 为什么需要 union：5 大优点对比表
  - 对比不使用 union 的问题
  - 实际使用场景（构造、写入、读取 IVT）
  - 类比理解：双面手表（正面刻度 vs 背面数字）
- v1.5: 修正 SeaBIOS 源代码位置错误
  - `struct segoff_s` 位置：types.h:25-33（修正：原错误为 49-52）
  - `SET_IVT` 宏位置：biosvar.h:21-22（修正：原错误为 util.h:194-196）
  - `SEG_IVT` 位置：config.h:60（修正：原错误为 13）
  - 补充 `struct segoff_s` 的 union 设计细节
  - 添加 `struct rmode_IVT` 结构（IVT 表结构，256 个向量）
  - 修正 SET_IVT 宏展开示例（使用正确的 rmode_IVT 结构）
  - 补充相关宏定义：GET_IVT, SET_FARVAR, SEGOFF
- v1.4: 添加完整的 IDT 向量门类型列表（0-255）及内核代码引述
- v1.3: 添加三种门描述符的详细数据结构对比（bit-level布局）、Linux 内核使用场景、IST 配置说明
- v1.2: 添加设计哲学对比、"门"描述符深度解释、生动类比（木门 vs 金库门）
- v1.1: 添加详细的 SeaBIOS 和 Linux kernel 源代码引用

> 📚 **文档导航**: [返回总索引](DOCUMENT_INDEX.md) | [阅读指南](READING_GUIDE.md) | [IDT 演进](LINUX_KERNEL_IDT_EVOLUTION.md)

> **相关文档**：
> - 关于 **IVT 和 IDT 的软件中断服务程序对比**（BIOS 服务 vs 内核系统调用、硬件中断与软件中断的协作关系），请参见 [BIOS IVT 与 Kernel IDT 的软件中断服务程序对比](BIOS_IVT_VS_KERNEL_IDT.md)
> - 关于 **TSS 和 IST 机制**（IDT 中的 IST 字段用途、独立栈机制），请参见 [x86-64 任务状态段（TSS）与中断栈表（IST）详解](X86_64_TSS_AND_IST.md)
> - 关于 **idt_setup_early_handler() 函数详解**（Linux 内核如何初始化 IDT），请参见 [idt_setup_early_handler() 函数详细分析](IDT_SETUP_EARLY_HANDLER_DETAILED_ANALYSIS.md)
> - 关于 **Call Gate vs IDT Gate 的区别**（为什么看起来很像但存储位置不同、Linux 内核数据结构对应），请参见 [Call Gate vs IDT Gate：Linux 内核数据结构对比](CALL_GATE_VS_IDT_GATE_KERNEL_STRUCTURES.md)

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
   - 6.1.1 [深入理解：segoff 和 segoff_s 的关系](#611-深入理解segoff-和-segoff_s-的关系)
7. [从 IVT 到 IDT 的演进过程](#7-从-ivt-到-idt-的演进过程)
8. [为什么 x86-64 必须使用 IDT？](#8-为什么-x86-64-必须使用-idt)
9. [源代码索引](#9-源代码索引)

---

## 源代码快速索引

### SeaBIOS 源代码

| 数据结构/函数 | 文件路径 | 说明 |
|--------------|---------|------|
| `struct segoff_s` | seabios/src/types.h:25-33 | IVT 表项结构（段:偏移，4 字节，union 设计） |
| `struct rmode_IVT` | seabios/src/std/bda.h:13-15 | IVT 表结构（256 个 segoff_s） |
| `SET_IVT` 宏 | seabios/src/biosvar.h:21-22 | 设置 IVT 条目的宏 |
| `GET_IVT` 宏 | seabios/src/biosvar.h:20 | 读取 IVT 条目的宏 |
| `ivt_init()` | seabios/src/post.c:568-650 | BIOS 启动时初始化 IVT |
| `entry_13` | seabios/src/romlayout.S:448-454 | INT 13h 磁盘服务入口 |
| `process_op()` | seabios/src/block.c:605-632 | INT 13h 磁盘操作 C 实现 |
| `SEG_IVT` | seabios/src/config.h:60 | IVT 表的段地址（0x0000） |
| `SEG_BIOS` | seabios/src/config.h:10 | BIOS 代码段地址（0xF000） |
| `SEGOFF` 宏 | seabios/src/farptr.h:199 | 构造 segoff_s 结构的辅助宏 |
| `SET_FARVAR` 宏 | seabios/src/farptr.h:181-182 | 写入远指针变量的宏 |

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
| `GATE_TRAP` | arch/x86/include/asm/desc_defs.h:100-102 | Trap Gate 类型（0xF） |
| `GATE_TASK` | arch/x86/include/asm/desc_defs.h:100-102 | Task Gate 类型（0x5，已废弃） |
| `def_idts` | arch/x86/kernel/idt.c:97-130 | IDT 初始化数据（异常门定义） |
| `ist_idts` | arch/x86/kernel/cpu/common.c:2066-2091 | IST 异常定义（#DF, #NMI, #MC, #DB） |
| `IST_INDEX_*` | arch/x86/include/asm/cpu_entry_area.h | IST 索引常量（1-4） |
| `INTG` 宏 | arch/x86/kernel/idt.c:253-258 | 中断门初始化宏 |
| `SYSG` 宏 | arch/x86/kernel/idt.c:253-258 | 系统门初始化宏（陷阱门+DPL=3） |

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

**IVT 相关数据结构和宏定义：**

```c
// seabios/src/types.h:25-33 - IVT 表项的数据结构
struct segoff_s {
    union {
        struct {
            u16 offset;  // 偏移地址（16 位）
            u16 seg;     // 段地址（16 位）
        };
        u32 segoff;      // 也可以作为 32 位整体访问
    };
};

// seabios/src/std/bda.h:13-15 - IVT 表结构
struct rmode_IVT {
    struct segoff_s ivec[256];  // 256 个中断向量
};

// seabios/src/biosvar.h:21-22 - SET_IVT 宏定义
#define SET_IVT(vector, segoff)                                         \
    SET_FARVAR(SEG_IVT, ((struct rmode_IVT *)0)->ivec[vector], segoff)

// seabios/src/biosvar.h:20 - GET_IVT 宏定义
#define GET_IVT(vector) \
    GET_FARVAR(SEG_IVT, ((struct rmode_IVT *)0)->ivec[vector])

// seabios/src/config.h:60 - IVT 表的段地址
#define SEG_IVT  0x0000

// seabios/src/farptr.h:181-182 - SET_FARVAR 宏定义
#define SET_FARVAR(seg, var, val) \
    do { GET_FARVAR((seg), (var)) = (val); } while (0)

// seabios/src/farptr.h:199 - SEGOFF 宏：构造 segoff_s 结构
#define SEGOFF(s,o) ({struct segoff_s __so; __so.offset=(o); __so.seg=(s); __so;})

// seabios/src/biosvar.h:24-27 - FUNC16 宏：将 16 位函数地址转换为 segoff_s
#define FUNC16(func) ({                                 \
        ASSERT32FLAT();                                 \
        extern void func (void);                        \
        SEGOFF(SEG_BIOS, (u32)func - BUILD_BIOS_ADDR);  \
    })
```

#### 6.1.1 深入理解：`segoff` 和 `segoff_s` 的关系

**关键概念澄清**：

| 名称 | 类型 | 说明 |
|------|------|------|
| **`segoff_s`** | 结构体类型名 | `struct segoff_s`，`_s` 后缀表示 struct |
| **`segoff`** | u32 字段名 | `struct segoff_s` 内部的 union 字段 |

**Union 设计的巧妙之处**：

`struct segoff_s` 使用 **union**，使得**同一块 4 字节内存可以用两种方式访问**：

```
┌─────────────────────────────────────────────────────────┐
│           内存布局（4 字节，小端序）                      │
├─────────────────────────────────────────────────────────┤
│  字节偏移:  +0    +1    +2    +3                        │
│  内存内容:  FE    E3    00    F0                        │
│                                                          │
│  视图 1 (分字段访问):                                    │
│    offset = 0xE3FE  ← 字节 0-1                          │
│    seg    = 0xF000  ← 字节 2-3                          │
│                                                          │
│  视图 2 (整体访问):                                      │
│    segoff = 0xF000E3FE  ← 字节 0-3 作为 u32             │
└─────────────────────────────────────────────────────────┘
```

**两种等价的访问方式**：

```c
struct segoff_s addr;

// 方式 1：分字段设置
addr.offset = 0xE3FE;
addr.seg    = 0xF000;
// 此时 addr.segoff 自动等于 0xF000E3FE（通过 union 同步）

// 方式 2：整体设置
addr.segoff = 0xF000E3FE;
// 此时 addr.offset 自动等于 0xE3FE（通过 union 同步）
// 此时 addr.seg    自动等于 0xF000（通过 union 同步）
```

**为什么需要 union？**

| 优点 | 说明 | 代码示例 |
|------|------|---------|
| **灵活访问** | 按需选择访问方式 | `addr.seg = 0xF000` 或 `addr.segoff = 0xF000E3FE` |
| **节省内存** | 两种方式共享同一块内存 | 只占 4 字节（不是 8 字节） |
| **自动同步** | 编译器自动同步两种视图 | 修改 `offset` 会自动更新 `segoff` |
| **方便传参** | 可以整体传递 32 位值 | `write_ivt(addr.segoff)` 更高效 |
| **类型安全** | 编译器检查类型 | 避免手动位操作出错 |

**对比：如果不使用 union**

```c
// 不使用 union（需要手动同步，容易出错）
struct segoff_bad {
    u16 offset;
    u16 seg;
    u32 segoff;  // ❌ 需要手动同步
};

// 使用时的问题：
addr.offset = 0xE3FE;
addr.seg    = 0xF000;
addr.segoff = (addr.seg << 16) | addr.offset;  // ❌ 需要手动计算

// 而使用 union（自动同步）：
struct segoff_s addr;
addr.offset = 0xE3FE;
addr.seg    = 0xF000;
// addr.segoff 自动等于 0xF000E3FE ✅ 无需手动计算
```

**实际使用场景**：

```c
// 场景 1：构造 IVT 表项（使用 SEGOFF 宏）
struct segoff_s handler = SEGOFF(0xF000, 0xE3FE);
// 内部执行：
//   handler.seg    = 0xF000;
//   handler.offset = 0xE3FE;
//   handler.segoff = 0xF000E3FE (自动生成)

// 场景 2：写入 IVT（两种等价方式）
// 方式 A：分字段写入
*(u16 *)(0x0000 + vector * 4 + 0) = handler.offset;
*(u16 *)(0x0000 + vector * 4 + 2) = handler.seg;

// 方式 B：整体写入（更高效，只需一次内存写入）
*(u32 *)(0x0000 + vector * 4) = handler.segoff;

// 场景 3：读取 IVT 表项
u32 ivt_entry = *(u32 *)(0x0000 + vector * 4);
struct segoff_s addr;
addr.segoff = ivt_entry;
// 现在可以直接访问：
printf("seg:offset = %04X:%04X\n", addr.seg, addr.offset);
```

**类比理解：双面手表**

可以把 `struct segoff_s` 想象成一个**双面手表**：

- **正面刻度**（分字段视图）：
  - 时针 = `seg`（高 16 位）
  - 分针 = `offset`（低 16 位）

- **背面数字**（整体视图）：
  - 数字显示 = `segoff`（32 位整数）

**两面共享同一个机芯（内存）**，转动一面，另一面自动同步！

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

**类型（type）值**（Intel SDM Vol. 3A, Table 3-2 "System-Segment and Gate-Descriptor Types", Section 3.5, 第 3-13 页）：

| 值   | 类型                | 说明 |
|------|---------------------|------|
| 0xE  | Interrupt Gate（64位）| 自动清除 IF 标志，禁用中断（防止嵌套） |
| 0xF  | Trap Gate（64位）     | 不修改 IF 标志，允许中断嵌套 |
| 0x5  | Task Gate（已废弃）   | x86-32，x86-64 不支持 |

**关键区别**（Intel SDM Vol. 3A, Section 6.12.1.2 "Flag Usage By Exception- or Interrupt-Handler Procedure"）：
- **Interrupt Gate (0xE)**：CPU 在跳转到处理程序时自动执行 `CLI`（清除 EFLAGS.IF），禁用中断
  - 用于硬件中断处理（避免嵌套中断导致栈溢出）
- **Trap Gate (0xF)**：CPU 不修改 IF 标志，允许中断嵌套
  - 用于异常处理（如 #PF Page Fault，允许在处理缺页时响应中断）

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

#### Intel x86 架构中的所有"门"类型

**重要说明**：Intel SDM 中的"门描述符"（Gate Descriptors）是一个**总称**，不同类型的门存储在不同的表中：

```
门描述符（Gate Descriptors）分类
│
├── 存储在 GDT/LDT 中的门：
│   └── Call Gate（调用门）              ← Intel SDM Section 5.8.3
│       • 用途：跨特权级函数调用
│       • 触发：CALL FAR 指令
│       • 现代用途：几乎不用（64位用 SYSCALL 代替）
│
└── 存储在 IDT 中的门：                    ← Intel SDM Section 6.14.1
    ├── Interrupt Gate（中断门）
    │   • 用途：处理硬件中断和某些异常
    │   • 特点：自动禁用中断（IF←0）
    │
    ├── Trap Gate（陷阱门）
    │   • 用途：处理异常和系统调用
    │   • 特点：不修改 IF 标志
    │
    └── Task Gate（任务门）
        • 用途：硬件任务切换
        • 状态：x86-64 已废弃
```

**关键区别**：

| 特性 | Call Gate | IDT Gate (Interrupt/Trap) |
|------|-----------|--------------------------|
| **位置** | GDT 或 LDT | **IDT** |
| **SDM 章节** | Section 5.8.3 | Section 6.14.1 |
| **用途** | 跨特权级调用 | 中断/异常处理 |
| **触发方式** | `CALL FAR` 指令 | `INT n`、硬件中断、CPU 异常 |
| **64位支持** | 支持（16字节） | 支持（16字节） |
| **Linux 使用** | ❌ 几乎不用 | ✅ 广泛使用 |

**注意**：本文档主要讨论的是 **IDT 中的门描述符**（Interrupt Gate 和 Trap Gate），不涉及 Call Gate。

#### IDT 中的三种门类型

x86-64 架构在 **IDT** 中定义了三种门描述符：

| 门类型 | Type 值 | 用途 | 进入时是否关中断 | Linux 使用场景 |
|--------|---------|------|-----------------|---------------|
| **中断门<br>（Interrupt Gate）** | 0xE | 处理硬件中断和某些异常 | ✅ 是<br>（IF←0） | 硬件中断（IRQ）<br>某些异常（#PF, #DF, #NMI, #MC） |
| **陷阱门<br>（Trap Gate）** | 0xF | 处理大部分异常和系统调用 | ❌ 否<br>（IF 不变） | 大部分异常（#BP, #GP, #DE）<br>系统调用（int 0x80, syscall） |
| **任务门<br>（Task Gate）** | 0x5 | 硬件任务切换 | ✅ 是 | ❌ Linux 不使用<br>（x86-64 已废弃） |

#### 三种门的数据结构详细对比

**关键发现：三种门的数据结构完全不同！虽然都占用16字节（x86-64），但字段含义和布局截然不同。**

**1. 中断门（Interrupt Gate）—— 包含完整地址 + IST**

```
x86-64 中断门（16 字节）：

127                                64  ← 高 64 位
+------------------------------------+
|         Offset 63..32              |  处理程序地址的高 32 位
+------------------------------------+

63      48 47   45 44  40 39     32  ← 低 64 位的高 32 位
+--------+-------+------+-----+-----+
| Offset |  IST  | zero | Type| DPL |P|
| 31..16 | (0-7) | (000)|(1110)|     |
+--------+-------+------+-----+-----+
   ↑        ↑       ↑      ↑
   |        |       |      └─ 类型 = 0xE（中断门）
   |        |       └─ 必须为 0（保留位）
   |        └─ IST 索引（0=不用，1-7=TSS.IST[IST-1]）
   └─ 处理程序地址的中间 16 位

31                16 15             0  ← 低 64 位的低 32 位
+-------------------+----------------+
| Segment Selector  | Offset 15..0   |
+-------------------+----------------+
   ↑                   ↑
   |                   └─ 处理程序地址的低 16 位
   └─ 代码段选择子（如 __KERNEL_CS = 0x10）

关键字段：
• Offset (64位): offset_high(32) + offset_middle(16) + offset_low(16)
• Segment (16位): 代码段选择子
• IST (3位): 0-7，指定使用哪个 IST 栈（0 表示不使用）
• Type (4位): 1110 (0xE)
• DPL (2位): 描述符特权级
• P (1位): Present 位
```

**2. 陷阱门（Trap Gate）—— 几乎和中断门一样**

```
x86-64 陷阱门（16 字节）：

结构与中断门完全相同，唯一区别：

47      45 44  40
+-------+------+
|  IST  | Type |
| (0-7) |(1111)|  ← Type = 0xF（陷阱门，不是 0xE）
+-------+------+

关键区别：
• Type = 0xF（1111）vs 中断门的 0xE（1110）
• CPU 行为：进入时不关中断（RFLAGS.IF 保持不变）
• 其他字段完全相同（包括 IST 字段）
```

**3. 任务门（Task Gate）—— 完全不同的结构**

```
x86-64 任务门（16 字节）：

127                                64  ← 高 64 位
+------------------------------------+
|         Reserved (must be 0)       |  必须为 0
+------------------------------------+

63      48 47   45 44  40 39     32  ← 低 64 位的高 32 位
+--------+-------+------+-----+-----+
|Reserved| zero  | zero | Type| DPL |P|
| (全0)  | (000) | (000)|(0101)|     |
+--------+-------+------+-----+-----+
   ↑        ↑       ↑      ↑
   |        |       |      └─ 类型 = 0x5（任务门）
   |        |       └─ 必须为 0
   |        └─ 没有 IST 字段！
   └─ 保留（未使用）

31                16 15             0  ← 低 64 位的低 32 位
+-------------------+----------------+
|   TSS Selector    |   Reserved (0) |
+-------------------+----------------+
   ↑                   ↑
   |                   └─ 保留（必须为 0）
   └─ TSS 段选择子（指向要切换到的任务）

关键字段：
• TSS Selector (16位): 指向 GDT 中的 TSS 描述符
• Type (4位): 0101 (0x5)
• DPL (2位): 描述符特权级
• P (1位): Present 位
• 没有 Offset 字段！（不需要代码地址）
• 没有 IST 字段！（整个任务切换，不需要栈切换）
```

**数据结构对比总结：**

| 字段 | 中断门 | 陷阱门 | 任务门 |
|------|--------|--------|--------|
| **Offset (64位)** | ✅ 有 | ✅ 有 | ❌ 无 |
| **Segment (16位)** | ✅ 有<br>（代码段） | ✅ 有<br>（代码段） | ✅ 有<br>（TSS段） |
| **IST (3位)** | ✅ 有<br>（0-7） | ✅ 有<br>（0-7） | ❌ 无 |
| **Type (4位)** | 0xE (1110) | 0xF (1111) | 0x5 (0101) |
| **工作方式** | 跳转到代码地址<br>可用 IST 栈 | 跳转到代码地址<br>可用 IST 栈 | 硬件切换整个任务<br>从 TSS 加载所有寄存器 |

**为什么数据结构不同？**

因为三者的**工作方式完全不同**：

```
中断门/陷阱门的工作流程：
1. CPU 读取门描述符中的 Offset 和 Segment
2. 如果 IST ≠ 0：切换到 TSS.IST[IST-1] 指定的栈
3. 压栈保存返回地址（SS, RSP, RFLAGS, CS, RIP）
4. 跳转到 Segment:Offset
5. 如果是中断门：RFLAGS.IF = 0（关中断）

任务门的工作流程：
1. CPU 读取门描述符中的 TSS Selector
2. 通过 TSS Selector 从 GDT 中获取 TSS 描述符
3. 保存当前任务的所有寄存器到当前 TSS
4. 从新 TSS 中加载所有寄存器（CS, RIP, RSP, CR3, 等等）
5. 完成硬件任务切换（不需要 Offset，因为 RIP 在 TSS 里）
```

**Linux 内核中的门类型定义和使用：**

```c
// arch/x86/include/asm/desc_defs.h:100-102 - 门类型常量
#define GATE_INTERRUPT  0xE  // 中断门：进入时 RFLAGS.IF = 0（禁用中断）
#define GATE_TRAP       0xF  // 陷阱门：进入时 RFLAGS.IF 保持不变
#define GATE_CALL       0xC  // 调用门（x86-64 很少用）
#define GATE_TASK       0x5  // 任务门（x86-64 已废弃，Linux 不使用）

// arch/x86/kernel/idt.c:97-130 - Linux 内核的 IDT 初始化（摘录）
static const __initconst struct idt_data def_idts[] = {
    // 大部分异常使用中断门（关中断，保护栈帧）
    INTG(X86_TRAP_DE,       asm_exc_divide_error),        // #DE：除法错误
    INTG(X86_TRAP_NMI,      asm_exc_nmi),                 // #NMI：不可屏蔽中断
    INTG(X86_TRAP_DF,       asm_exc_double_fault),        // #DF：双重故障
    INTG(X86_TRAP_TS,       asm_exc_invalid_tss),         // #TS：无效 TSS
    INTG(X86_TRAP_NP,       asm_exc_segment_not_present), // #NP：段不存在
    INTG(X86_TRAP_SS,       asm_exc_stack_segment),       // #SS：栈段错误
    INTG(X86_TRAP_GP,       asm_exc_general_protection),  // #GP：通用保护错误
    INTG(X86_TRAP_PF,       asm_exc_page_fault),          // #PF：缺页异常
    INTG(X86_TRAP_MF,       asm_exc_coprocessor_error),   // #MF：浮点错误
    INTG(X86_TRAP_AC,       asm_exc_alignment_check),     // #AC：对齐检查
    INTG(X86_TRAP_MC,       asm_exc_machine_check),       // #MC：机器检查
    INTG(X86_TRAP_XF,       asm_exc_simd_coprocessor_error), // #XF：SIMD 错误

    // 少数异常使用陷阱门（不关中断，保持响应）
    // 注意：早期内核版本中 #BP, #OF 等用陷阱门，现代内核改用中断门

    // 系统调用门（陷阱门 + DPL=3，允许用户态调用）
    SYSG(X86_TRAP_OF,       asm_exc_overflow),            // #OF：溢出（用户态可触发）

    // 任务门：Linux 完全不使用！
    // x86-64 架构虽然支持，但 Linux 使用软件任务切换（更灵活）
};

// arch/x86/kernel/idt.c:253-258 - 宏定义
#define INTG(_vector, _addr)    \
    { .vector = _vector, .bits.type = GATE_INTERRUPT, \
      .bits.ist = DEFAULT_STACK, .bits.p = 1, .bits.dpl = 0, \
      .addr = _addr }

#define SYSG(_vector, _addr)    \
    { .vector = _vector, .bits.type = GATE_TRAP, \
      .bits.ist = DEFAULT_STACK, .bits.p = 1, .bits.dpl = 3, \
      .addr = _addr }
```

**Linux 内核中硬件中断的门类型：**

```c
// arch/x86/kernel/apic/vector.c - 硬件中断向量分配
// 所有硬件中断（IRQ）都使用中断门（GATE_INTERRUPT）

// 示例：键盘中断（IRQ1，向量 33）
IDT[33] = {
    .type = GATE_INTERRUPT,  // 0xE（关中断）
    .ist  = 0,               // 不使用 IST，用常规内核栈
    .dpl  = 0,               // Ring 0 only
    .addr = common_interrupt_handler,  // 通用中断处理入口
};
```

**使用 IST 的特殊异常（需要独立栈）：**

```c
// arch/x86/kernel/cpu/common.c:2066-2091 - TSS 初始化时设置 IST
static const __initconst struct idt_data ist_idts[] = {
    ISTG(X86_TRAP_DB,   asm_exc_debug,          IST_INDEX_DB),   // #DB：IST1
    ISTG(X86_TRAP_NMI,  asm_exc_nmi,            IST_INDEX_NMI),  // #NMI：IST2
    ISTG(X86_TRAP_DF,   asm_exc_double_fault,   IST_INDEX_DF),   // #DF：IST3
    ISTG(X86_TRAP_MC,   asm_exc_machine_check,  IST_INDEX_MC),   // #MC：IST4
};

// IST 索引定义（arch/x86/include/asm/cpu_entry_area.h）
#define IST_INDEX_DB    1  // Debug：需要独立栈防止递归
#define IST_INDEX_NMI   2  // NMI：不可屏蔽，必须有独立栈
#define IST_INDEX_DF    3  // Double Fault：栈已损坏，必须独立栈
#define IST_INDEX_MC    4  // Machine Check：硬件严重错误，独立栈
```

**Linux 内核使用总结表：**

| 中断/异常类型 | 门类型 | IST | DPL | 典型示例 | 原因 |
|--------------|--------|-----|-----|---------|------|
| **硬件中断**<br>(IRQ) | 中断门<br>0xE | 0 | 0 | 键盘、网卡、定时器 | 需要关中断防止嵌套 |
| **关键异常**<br>(需要独立栈) | 中断门<br>0xE | 1-4 | 0 | #DF, #NMI, #MC, #DB | 栈可能已损坏<br>或需要防止递归 |
| **普通异常**<br>(栈安全) | 中断门<br>0xE | 0 | 0 | #PF, #GP, #DE, #TS | 需要关中断保护栈帧 |
| **系统调用**<br>(用户可触发) | 陷阱门<br>0xF | 0 | 3 | int 0x80, syscall | 用户态可调用<br>不关中断保持响应 |
| **任务切换** | 任务门<br>0x5 | N/A | - | 无（Linux 不使用） | Linux 用软件任务切换 |

#### 完整的 IDT 向量门类型列表（0-255）

**注意**：本列表基于 Linux 内核 6.x 版本。

**向量 0-31：CPU 定义的异常（全部使用中断门）**

```c
// arch/x86/kernel/idt.c:97-130 - 异常处理程序的完整定义
static const __initconst struct idt_data def_idts[] = {
    INTG(X86_TRAP_DE,       asm_exc_divide_error),           // 0:  #DE 除法错误
    INTG(X86_TRAP_DB,       asm_exc_debug),                  // 1:  #DB 调试异常*
    INTG(X86_TRAP_NMI,      asm_exc_nmi),                    // 2:  #NMI 不可屏蔽中断*
    INTG(X86_TRAP_BP,       asm_exc_int3),                   // 3:  #BP 断点
    INTG(X86_TRAP_OF,       asm_exc_overflow),               // 4:  #OF 溢出
    INTG(X86_TRAP_BR,       asm_exc_bounds),                 // 5:  #BR 边界检查
    INTG(X86_TRAP_UD,       asm_exc_invalid_op),             // 6:  #UD 无效操作码
    INTG(X86_TRAP_NM,       asm_exc_device_not_available),   // 7:  #NM 设备不可用（FPU）
    INTG(X86_TRAP_DF,       asm_exc_double_fault),           // 8:  #DF 双重故障*
    INTG(X86_TRAP_OLD_MF,   asm_exc_coproc_segment_overrun), // 9:  协处理器段溢出
    INTG(X86_TRAP_TS,       asm_exc_invalid_tss),            // 10: #TS 无效 TSS
    INTG(X86_TRAP_NP,       asm_exc_segment_not_present),    // 11: #NP 段不存在
    INTG(X86_TRAP_SS,       asm_exc_stack_segment),          // 12: #SS 栈段错误
    INTG(X86_TRAP_GP,       asm_exc_general_protection),     // 13: #GP 通用保护错误
    INTG(X86_TRAP_PF,       asm_exc_page_fault),             // 14: #PF 缺页异常
    INTG(X86_TRAP_SPURIOUS, asm_exc_spurious_interrupt_bug), // 15: 伪中断
    INTG(X86_TRAP_MF,       asm_exc_coprocessor_error),      // 16: #MF x87 FPU 错误
    INTG(X86_TRAP_AC,       asm_exc_alignment_check),        // 17: #AC 对齐检查
    INTG(X86_TRAP_MC,       asm_exc_machine_check),          // 18: #MC 机器检查*
    INTG(X86_TRAP_XF,       asm_exc_simd_coprocessor_error), // 19: #XF SIMD 浮点异常
    INTG(X86_TRAP_VE,       asm_exc_virtualization_exception), // 20: #VE 虚拟化异常
    INTG(X86_TRAP_CP,       asm_exc_control_protection),      // 21: #CP 控制流保护
    // 22-28: Intel 保留
    INTG(X86_TRAP_VC,       asm_exc_vmm_communication),       // 29: #VC VMM 通信（SEV-ES）
    INTG(X86_TRAP_SECURITY, asm_exc_security_exception),      // 30: #SX 安全异常（SEV）
    // 31: Intel 保留
};

// 注：标记 * 的异常会被 ist_idts 覆盖，设置 IST 字段
```

**门类型定义（INTG 宏）：**

```c
// arch/x86/kernel/idt.c:253-258
#define INTG(_vector, _addr)                    \
    {                                           \
        .vector     = _vector,                  \
        .bits.type  = GATE_INTERRUPT,  /* 0xE */\
        .bits.ist   = DEFAULT_STACK,   /* 0   */\
        .bits.p     = 1,                        \
        .bits.dpl   = 0,               /* Ring 0 */ \
        .addr       = _addr,                    \
    }

// DEFAULT_STACK = 0（不使用 IST）
```

**使用 IST 的特殊异常（覆盖上述默认设置）：**

```c
// arch/x86/kernel/cpu/common.c:2066-2091
static const __initconst struct idt_data ist_idts[] = {
    ISTG(X86_TRAP_DB,  asm_exc_debug,         IST_INDEX_DB),   // 1:  #DB → IST1
    ISTG(X86_TRAP_NMI, asm_exc_nmi,           IST_INDEX_NMI),  // 2:  #NMI → IST2
    ISTG(X86_TRAP_DF,  asm_exc_double_fault,  IST_INDEX_DF),   // 8:  #DF → IST3
    ISTG(X86_TRAP_MC,  asm_exc_machine_check, IST_INDEX_MC),   // 18: #MC → IST4
};

// arch/x86/include/asm/cpu_entry_area.h
#define IST_INDEX_DB    1  // Debug：防止递归调试
#define IST_INDEX_NMI   2  // NMI：不可屏蔽，需要独立栈
#define IST_INDEX_DF    3  // Double Fault：栈已损坏时的最后防线
#define IST_INDEX_MC    4  // Machine Check：硬件严重错误
```

**向量 32-127：设备中断（IRQ，全部使用中断门）**

```c
// arch/x86/include/asm/irq_vectors.h
#define FIRST_EXTERNAL_VECTOR   0x20  // 32：第一个外部中断向量

// arch/x86/kernel/apic/vector.c - 动态分配 IRQ 向量
// 所有设备中断（键盘、网卡、磁盘等）都使用中断门

// 示例 IRQ 分配（传统 8259 PIC 模式）：
// 向量 32 (IRQ0):  系统定时器
// 向量 33 (IRQ1):  键盘
// 向量 34 (IRQ2):  级联（从 PIC）
// 向量 35 (IRQ3):  COM2/COM4
// 向量 36 (IRQ4):  COM1/COM3
// 向量 37 (IRQ5):  LPT2（或声卡）
// 向量 38 (IRQ6):  软盘
// 向量 39 (IRQ7):  LPT1
// 向量 40 (IRQ8):  实时时钟（RTC）
// 向量 41 (IRQ9):  ACPI
// 向量 42 (IRQ10): 可用
// 向量 43 (IRQ11): 可用
// 向量 44 (IRQ12): PS/2 鼠标
// 向量 45 (IRQ13): 数学协处理器
// 向量 46 (IRQ14): 主 IDE
// 向量 47 (IRQ15): 从 IDE

// 现代系统（APIC 模式）：向量动态分配到 32-127 范围
// 门类型：全部 GATE_INTERRUPT (0xE)
// IST: 0
// DPL: 0
```

**向量 128 (0x80)：传统系统调用（唯一的陷阱门）**

```c
// arch/x86/kernel/idt.c:141-145
#ifdef CONFIG_IA32_EMULATION
    SYSG(IA32_SYSCALL_VECTOR, entry_INT80_compat),  // 128 (0x80)
#endif

// SYSG 宏定义（系统门 = 陷阱门 + DPL=3）
#define SYSG(_vector, _addr)                    \
    {                                           \
        .vector     = _vector,                  \
        .bits.type  = GATE_TRAP,       /* 0xF */\
        .bits.ist   = DEFAULT_STACK,   /* 0   */\
        .bits.p     = 1,                        \
        .bits.dpl   = 3,               /* Ring 3 可调用 */ \
        .addr       = _addr,                    \
    }

// 注意：现代 Linux (x86-64) 主要使用 syscall/sysenter 指令
// 向量 0x80 仅为 32 位兼容性保留
```

**向量 129-238：高级中断向量（主要未使用，保留给设备）**

```c
// 这些向量可以动态分配给 PCI/PCIe 设备
// 门类型：GATE_INTERRUPT (0xE)
// IST: 0
// DPL: 0
```

**向量 239-255：APIC 和系统管理向量（全部使用中断门）**

```c
// arch/x86/include/asm/irq_vectors.h:89-115
#define FIRST_SYSTEM_VECTOR     0xef  // 239

// 系统向量定义（从高到低）：
#define SPURIOUS_APIC_VECTOR            0xff  // 255: APIC 伪中断
#define ERROR_APIC_VECTOR               0xfe  // 254: APIC 错误
#define RESCHEDULE_VECTOR               0xfd  // 253: 重新调度 IPI
#define CALL_FUNCTION_VECTOR            0xfc  // 252: 函数调用 IPI
#define CALL_FUNCTION_SINGLE_VECTOR     0xfb  // 251: 单 CPU 函数调用
#define THERMAL_APIC_VECTOR             0xfa  // 250: CPU 温度警告
#define THRESHOLD_APIC_VECTOR           0xf9  // 249: MCE 阈值中断
#define REBOOT_VECTOR                   0xf8  // 248: 重启 IPI
#define X86_PLATFORM_IPI_VECTOR         0xf7  // 247: 平台 IPI
#define IRQ_WORK_VECTOR                 0xf6  // 246: IRQ work
#define UV_BAU_MESSAGE                  0xf5  // 245: UV BAU 消息
#define DEFERRED_ERROR_VECTOR           0xf4  // 244: AMD 延迟错误
#define HYPERVISOR_CALLBACK_VECTOR      0xf3  // 243: Hypervisor 回调
#define POSTED_INTR_VECTOR              0xf2  // 242: Posted interrupt
#define POSTED_INTR_WAKEUP_VECTOR       0xf1  // 241: Posted int wakeup
#define POSTED_INTR_NESTED_VECTOR       0xf0  // 240: Posted int nested
#define LOCAL_TIMER_VECTOR              0xef  // 239: APIC 定时器

// 所有系统向量：GATE_INTERRUPT (0xE), IST=0, DPL=0
```

**IDT 0-255 完整总结表：**

| 向量范围 | 数量 | 门类型 | IST | DPL | 用途 | 内核代码引用 |
|---------|------|--------|-----|-----|------|-------------|
| **0-31** | 32 | 中断门<br>0xE | 0 | 0 | CPU 异常 | `arch/x86/kernel/idt.c:97-130`<br>`def_idts[]` |
| **1,2,8,18** | 4 | 中断门<br>0xE | 1-4 | 0 | IST 异常覆盖 | `arch/x86/kernel/cpu/common.c:2066-2091`<br>`ist_idts[]` |
| **32-127** | 96 | 中断门<br>0xE | 0 | 0 | 设备中断 IRQ | `arch/x86/kernel/apic/vector.c`<br>`irq_matrix_*()` |
| **128 (0x80)** | 1 | **陷阱门<br>0xF** | 0 | **3** | 32位系统调用 | `arch/x86/kernel/idt.c:141-145`<br>`SYSG()` 宏 |
| **129-238** | 110 | 中断门<br>0xE | 0 | 0 | 未分配<br>（可用于设备） | - |
| **239-255** | 17 | 中断门<br>0xE | 0 | 0 | APIC/IPI 系统向量 | `arch/x86/include/asm/irq_vectors.h:89-115` |

**关键结论：**

1. **中断门（0xE）占绝对主导**：256 个向量中，只有 **1 个**使用陷阱门（向量 0x80）
2. **陷阱门（0xF）极其罕见**：仅用于 32 位兼容系统调用，现代 64 位系统已不常用
3. **任务门（0x5）完全不用**：Linux 内核从不使用任务门
4. **IST 只用于 4 个关键异常**：#DB (IST1), #NMI (IST2), #DF (IST3), #MC (IST4)
5. **用户态只能触发 1 个向量**：0x80 (DPL=3)，其他 255 个全部 DPL=0（内核专用）
6. **现代系统调用不通过 IDT**：x86-64 使用 `syscall` 指令，绕过 IDT 直接跳转到 MSR 指定的地址

**为什么要区分中断门和陷阱门？**

- **中断门（0xE）**：关闭中断是为了防止**嵌套中断**破坏栈帧
  - 示例：处理键盘中断时，不希望被另一个键盘中断打断
  - 示例：处理 #PF（缺页异常）时，虽然可能很慢（换页），但仍需要关中断保护栈帧的完整性
  - 处理程序可以在合适的时候手动重新启用中断（`sti` 指令）

- **陷阱门（0xF）**：不关中断是为了保持**响应性**
  - 历史：早期内核中 #BP（断点）、#OF（溢出）等使用陷阱门
  - 现状：现代 Linux 内核几乎全部改用中断门（更安全）
  - 主要用于：系统调用（int 0x80）需要 DPL=3 + 不关中断

**为什么任务门在 Linux 中被废弃？**

```c
// 任务门的问题：
// 1. 硬件任务切换非常慢（保存/恢复所有寄存器）
// 2. 灵活性差（无法自定义切换哪些寄存器）
// 3. x86-64 长模式已不支持（Intel SDM 明确规定）

// Linux 的替代方案：软件任务切换
// arch/x86/kernel/process_64.c:__switch_to()
// - 只保存/恢复必要的寄存器
// - 可以自定义调度策略
// - 支持更复杂的线程模型（NPTL）
```

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
SET_FARVAR(SEG_IVT, ((struct rmode_IVT *)0)->ivec[0x13],
           SEGOFF(0xF000, offset_of_entry_13));

// 第三层展开（SET_FARVAR）：
GET_FARVAR(SEG_IVT, ((struct rmode_IVT *)0)->ivec[0x13]) =
    SEGOFF(0xF000, offset_of_entry_13);

// 最终效果：写入物理地址 0x4C（0x13 * 4）
// ((struct rmode_IVT *)0)->ivec[0x13] 计算偏移 = 0x13 * 4 = 0x4C
// 段地址 SEG_IVT = 0x0000
// 物理地址 = 0x0000 << 4 + 0x4C = 0x0004C
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

   **Volume 3A: System Programming Guide, Part 1**

   **Chapter 5: Protection**
   - Section 5.8: Control Transfers
   - **Section 5.8.3: Call Gates** (调用门，GDT/LDT 中的门描述符)
     - Call-Gate Descriptor 结构
     - 跨特权级函数调用机制
     - 与 IDT Gate 的区别

   **Chapter 6: Interrupt and Exception Handling**
   - Section 6.1: Interrupt and Exception Overview
   - **Section 6.10: Interrupt Descriptor Table (IDT)**
     - IDT 的基本概念和作用
   - **Section 6.11: IDT Descriptors**
     - **Figure 6-2**: IDT Gate Descriptors (32-bit mode)
     - Interrupt Gate、Trap Gate、Task Gate 的区别
   - **Section 6.14: Exception and Interrupt Handling in 64-Bit Mode**
   - **Section 6.14.1: 64-Bit Mode IDT** ⭐ **核心章节**
     - **Figure 6-7**: 64-Bit IDT Gate Descriptors (16 字节结构)
     - IST (Interrupt Stack Table) 机制
     - 64-bit mode 下的门描述符格式
   - Section 6.14.2: 64-Bit Mode Stack Frame
   - Section 6.14.5: Interrupt Stack Table

   **Chapter 7: Task Management**
   - **Section 7.2.5: Task-Gate Descriptor** (已废弃，64位模式不支持)

   **Chapter 3: Protected-Mode Memory Management**
   - **Section 3.5**: System Descriptor Types（第 3-13 页）
   - **Table 3-2**: System-Segment and Gate-Descriptor Types（第 3-13 页）
     - 列出所有门描述符的 Type 字段值
     - Type 0x5 = Task Gate（64位不支持）
     - Type 0xC = Call Gate（64位支持但不常用）
     - Type 0xE = Interrupt Gate（自动清除 IF 标志）
     - Type 0xF = Trap Gate（不修改 IF 标志）

   **下载地址**：
   - Intel 官方：https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html
   - Order Number: 325462 (Combined Volumes)

   **关键概念澄清**：
   - **Gate Descriptors（门描述符）** 是一个总称，包括：
     - **Call Gate**：放在 GDT/LDT，用于跨特权级调用（Section 5.8.3）
     - **Interrupt Gate**：放在 IDT，用于中断处理（Section 6.14.1）
     - **Trap Gate**：放在 IDT，用于异常/陷阱处理（Section 6.14.1）
     - **Task Gate**：已废弃（Section 7.2.5）

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

9. **seabios/src/biosvar.h**
   - `SET_IVT` 宏定义（21-22 行）
   - `GET_IVT` 宏定义（20 行）

10. **seabios/src/types.h**
    - `struct segoff_s` 定义（25-33 行，union 设计）

11. **seabios/src/std/bda.h**
    - `struct rmode_IVT` 定义（13-15 行，IVT 表结构）

12. **seabios/src/farptr.h**
    - `SET_FARVAR` 宏定义（181-182 行）
    - `SEGOFF` 宏定义（199 行）

13. **seabios/src/config.h**
    - `SEG_IVT` 定义（60 行）
    - `SEG_BIOS` 定义（10 行）

14. **seabios/src/romlayout.S**
    - BIOS 中断服务入口（如 `entry_13`）

15. **seabios/src/block.c**
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
