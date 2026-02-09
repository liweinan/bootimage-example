# x86 内存管理理论：分段与分页机制详解

> **文档定位**：本文档纯粹讲解 x86/x86-64 架构的内存管理硬件机制，不涉及具体实现和演化过程。

## 文档导航

- **理论篇**（本文档）：硬件机制与概念
- **[演化篇](LINUX_MEMORY_MANAGEMENT_EVOLUTION.md)**：从 BIOS 到 Linux 内核的过渡
- **[实现篇](LINUX_MEMORY_MANAGEMENT_CODE_GUIDE.md)**：源代码详解与实战调试

---

## 第一部分：分段机制 (GDT)

### 1.1 什么是 GDT？为什么需要？

**GDT（Global Descriptor Table，全局描述符表）** 是 x86 架构中用于内存分段管理的核心数据结构。

**为什么需要 GDT？**

在 x86 架构的演化过程中，GDT 的作用发生了根本性变化：

```
【保护模式（32 位）】
目的：内存隔离与保护
┌─────────────────┐
│ 逻辑地址        │ ← 程序使用的地址
│ (段选择子:偏移)  │
└────────┬────────┘
         │ GDT 查表
         ↓
┌─────────────────┐
│ 线性地址        │ ← 段基址 + 偏移
│ (Base + Offset) │
└────────┬────────┘
         │ 页表转换（可选）
         ↓
┌─────────────────┐
│ 物理地址        │
└─────────────────┘

【长模式（64 位）】
目的：权限控制与任务管理
┌─────────────────┐
│ 逻辑地址        │ ← 程序使用的地址
│ (段选择子:偏移)  │
└────────┬────────┘
         │ GDT 查表（段基址强制为 0）
         ↓
┌─────────────────┐
│ 线性地址 = 偏移 │ ← 扁平模式
└────────┬────────┘
         │ 页表转换（强制）
         ↓
┌─────────────────┐
│ 物理地址        │
└─────────────────┘
```

**关键区别**：

| 特性 | 保护模式（32 位） | 长模式（64 位） |
|------|------------------|----------------|
| **地址转换** | GDT 段式转换 + 可选分页 | GDT 扁平模式 + 强制分页 |
| **段基址** | 可以是任意值（Base ≠ 0） | 强制为 0（Base = 0） |
| **主要作用** | 内存隔离与地址转换 | 权限控制与任务管理 |
| **分页要求** | 可选（CR0.PG 可为 0） | 强制（Long Mode 要求 PG=1） |

### 1.2 段描述符结构详解

**段描述符**是 GDT 表中的一个 8 字节条目，定义了一个内存段的属性。

**32 位保护模式段描述符结构**：

```
63        56 55  52 51   48 47          40 39   32
┌──────────┬─────┬───────┬──────────────┬───────┐
│ Base     │Flags│ Limit │  Access Byte │ Base  │
│ [31:24]  │ (4) │[19:16]│    (8 bits)  │[23:16]│
└──────────┴─────┴───────┴──────────────┴───────┘
31                      16 15                   0
┌─────────────────────────┬─────────────────────┐
│      Base [15:0]        │    Limit [15:0]     │
└─────────────────────────┴─────────────────────┘

字段说明：
- Base (32 bits)：段基址，段的起始物理地址
- Limit (20 bits)：段界限，段的大小（单位：字节或 4KB）
- Flags (4 bits)：G/DB/L/AVL 标志位
- Access Byte (8 bits)：P/DPL/S/Type 标志位
```

**Access Byte 详解**：

```
Bit 7: P (Present) - 段是否存在于内存中
       1 = 存在, 0 = 不存在（访问会触发 #NP 异常）

Bit 6-5: DPL (Descriptor Privilege Level) - 特权级
         00 = Ring 0 (内核)
         01 = Ring 1 (未使用)
         10 = Ring 2 (未使用)
         11 = Ring 3 (用户)

Bit 4: S (Descriptor Type)
       1 = 代码/数据段
       0 = 系统段（TSS/LDT/Call Gate）

Bit 3-0: Type (段类型)
         代码段：Execute/Conforming/Readable/Accessed
         数据段：Write/Expand-Down/Writable/Accessed
```

**Flags 详解**：

```
Bit 3: G (Granularity) - 粒度
       1 = Limit 单位是 4KB（最大 4GB）
       0 = Limit 单位是字节（最大 1MB）

Bit 2: DB (Default Operation Size)
       代码段：1 = 32位, 0 = 16位
       栈段：1 = ESP, 0 = SP

Bit 1: L (Long Mode)
       1 = 64位代码段（Long Mode）
       0 = 兼容模式或 32/16位段

Bit 0: AVL (Available) - 系统软件可用位
```

**64 位长模式的变化**：

在长模式下，段描述符的 **Base** 和 **Limit** 字段被忽略（除了 FS/GS 段）：

```
代码段和数据段（CS/DS/SS/ES）：
- Base 强制为 0
- Limit 忽略
- 只有 Flags 和 Access Byte 生效

FS 和 GS 段：
- Base 仍然有效（通过 MSR 设置）
- 用于 TLS（线程本地存储）和 Per-CPU 数据

TSS 描述符：
- 扩展为 16 字节（两个槽位）
- Base 字段扩展到 64 位
```

### 1.3 保护模式 vs 长模式

**保护模式（32 位）**：

```
特点：
1. 地址转换：逻辑地址 → 线性地址 → 物理地址
2. 段式内存管理：每个段有独立的 Base 和 Limit
3. 可选分页：CR0.PG 可以为 0
4. 4GB 地址空间限制

示例：
┌─────────────────────┐
│ 逻辑地址            │
│ CS:0x1234           │
└──────────┬──────────┘
           │
           ↓ GDT[CS] = {Base=0x80000000, Limit=0xFFFFFFFF}
┌─────────────────────┐
│ 线性地址            │
│ 0x80001234          │ ← Base + Offset
└──────────┬──────────┘
           │
           ↓ 页表转换（如果 CR0.PG=1）
┌─────────────────────┐
│ 物理地址            │
│ 0x12345000          │
└─────────────────────┘
```

**长模式（64 位）**：

```
特点：
1. 扁平模式：段基址强制为 0
2. 强制分页：Long Mode 必须启用 CR0.PG=1
3. 48 位虚拟地址（理论上 64 位）
4. 256TB 地址空间（实际）

示例：
┌─────────────────────┐
│ 逻辑地址            │
│ CS:0x7FFFF1234      │
└──────────┬──────────┘
           │
           ↓ GDT[CS] = {Base=0（强制）, L=1}
┌─────────────────────┐
│ 线性地址 = Offset   │
│ 0x7FFFF1234         │ ← 直接使用 Offset
└──────────┬──────────┘
           │
           ↓ 4级页表转换（强制）
┌─────────────────────┐
│ 物理地址            │
│ 0x12345000          │
└─────────────────────┘
```

**为什么长模式仍需要 GDT？**

虽然长模式下段基址为 0，但 GDT 仍然必需：

1. **权限检查**：DPL（特权级）字段用于 Ring 0-3 隔离
2. **段类型标识**：区分代码段（可执行）和数据段（可写）
3. **任务切换**：TSS（Task State Segment）描述符
4. **系统调用**：SYSCALL/SYSRET 指令依赖特定的 GDT 布局
5. **IRET 指令**：需要 CS 描述符的 L 位判断返回模式

### 1.4 段选择子与特权级

**段选择子（Segment Selector）** 是一个 16 位值，用于索引 GDT 或 LDT。

**段选择子结构**：

```
15                           3  2   0
┌───────────────────────────┬───┬───┐
│      Index (13 bits)      │TI │RPL│
└───────────────────────────┴───┴───┘

Index：GDT/LDT 中的索引（0-8191）
TI：Table Indicator（0=GDT, 1=LDT）
RPL：Requested Privilege Level（0-3）
```

**段选择子示例**：

```c
#define __KERNEL_CS  (GDT_ENTRY_KERNEL_CS * 8)    // 0x10 = 索引 2, TI=0, RPL=0
#define __KERNEL_DS  (GDT_ENTRY_KERNEL_DS * 8)    // 0x18 = 索引 3, TI=0, RPL=0
#define __USER_CS    (GDT_ENTRY_DEFAULT_USER_CS * 8 + 3)  // 0x33 = 索引 6, RPL=3
#define __USER_DS    (GDT_ENTRY_DEFAULT_USER_DS * 8 + 3)  // 0x2B = 索引 5, RPL=3
```

**特权级检查规则**：

```
访问段时，CPU 检查：
max(CPL, RPL) ≤ DPL

CPL (Current Privilege Level)：当前代码段的特权级（CS.RPL）
RPL (Requested Privilege Level)：段选择子中的特权级
DPL (Descriptor Privilege Level)：段描述符中的特权级

示例：
- 内核代码（CPL=0）访问内核数据（DPL=0）：max(0, 0) ≤ 0 ✅
- 用户代码（CPL=3）访问用户数据（DPL=3）：max(3, 3) ≤ 3 ✅
- 用户代码（CPL=3）访问内核数据（DPL=0）：max(3, 3) ≤ 0 ❌ #GP
```

**特权级切换**：

```
用户态 → 内核态：
1. 系统调用（INT/SYSCALL）：CPL 3 → 0
2. 中断/异常：自动切换到 Ring 0
3. 切换栈：TSS 中的 RSP0（内核栈）

内核态 → 用户态：
1. IRET/SYSRET 指令：CPL 0 → 3
2. 恢复用户栈：从栈中弹出 SS:RSP
```

---

## 第二部分：分页机制

### 2.1 什么是分页？为什么需要？

**分页（Paging）** 是一种将虚拟地址空间映射到物理内存的机制，是现代操作系统内存管理的基础。

**为什么需要分页？**

```
【问题】
1. 内存碎片：进程分配/释放导致外部碎片
2. 地址空间隔离：每个进程需要独立的地址空间
3. 物理内存限制：程序可能需要超过物理内存的地址空间
4. 内存保护：防止进程访问其他进程的内存

【解决方案：分页】
1. 固定大小的页（4KB/2MB/1GB）：消除外部碎片
2. 每个进程独立页表：完全隔离地址空间
3. 按需分配（Demand Paging）：只分配实际使用的内存
4. 页表权限位（R/W/X/U）：细粒度内存保护
```

**虚拟内存的核心优势**：

```
1. 地址空间隔离
   ┌─────────────┐       ┌─────────────┐
   │ Process A   │       │ Process B   │
   │ 虚拟地址    │       │ 虚拟地址    │
   │ 0x400000    │       │ 0x400000    │ ← 相同虚拟地址
   └──────┬──────┘       └──────┬──────┘
          │                     │
          ↓ Page Table A        ↓ Page Table B
   ┌─────────────┐       ┌─────────────┐
   │ 物理地址    │       │ 物理地址    │
   │ 0x10000     │       │ 0x20000     │ ← 不同物理地址
   └─────────────┘       └─────────────┘

2. 内存超售（Overcommit）
   - 虚拟地址空间：256TB（48 位）
   - 物理内存：16GB
   - 100 个进程各自认为有 256TB 地址空间
   - 实际只分配使用的页

3. 内存保护
   - 用户页：U=1（用户可访问）
   - 内核页：U=0（仅内核可访问）
   - 只读页：W=0（不可写）
   - 不可执行页：NX=1（防止代码注入）

4. 共享内存
   ┌─────────────┐       ┌─────────────┐
   │ Process A   │       │ Process B   │
   │ VA: 0x10000 │       │ VA: 0x20000 │ ← 不同虚拟地址
   └──────┬──────┘       └──────┬──────┘
          │                     │
          └──────────┬──────────┘
                     ↓
              ┌─────────────┐
              │ 物理页      │ ← 相同物理页
              │ PA: 0x50000 │
              └─────────────┘
```

### 2.2 多级页表设计原理

**为什么不使用单级页表？**

**单级页表的问题**：

```
假设：
- 虚拟地址空间：48 位（256TB）
- 页大小：4KB（2^12）
- 需要的页表项数：2^48 / 2^12 = 2^36 = 68,719,476,736 个
- 每个页表项：8 字节
- 页表大小：2^36 * 8 = 512GB

问题：
1. 内存浪费：每个进程需要 512GB 页表（即使只用 1MB 内存）
2. 连续内存：需要 512GB 连续物理内存（不可能）
3. 稀疏地址空间：大部分虚拟地址未使用，但仍需页表项
```

**多级页表的解决方案**：

```
x86-64 四级页表结构：

48 位虚拟地址拆分：
┌───────┬───────┬───────┬───────┬────────────┐
│ PML4  │ PDPT  │  PD   │  PT   │   Offset   │
│ [47:39]│[38:30]│[29:21]│[20:12]│   [11:0]   │
│ 9 bits │ 9 bits│ 9 bits│ 9 bits│  12 bits   │
└───┬───┴───┬───┴───┬───┴───┬───┴─────┬──────┘
    │       │       │       │         │
    ↓       ↓       ↓       ↓         ↓
  CR3 → PML4 → PDPT → PD → PT → 物理页框
       (L4)   (L3)   (L2)  (L1)

每级页表：
- 512 个条目（2^9）
- 每个条目 8 字节
- 页表大小：4KB（正好一页）
```

**内存节省示例**：

```
场景：进程使用 4MB 内存（连续虚拟地址 0x00400000 - 0x007FFFFF）

单级页表：
- 需要 512GB 页表（即使只用 4MB）

四级页表：
- PML4：1 页（4KB）
- PDPT：1 页（4KB）
- PD：1 页（4KB）
- PT：1024 页（4MB / 4KB）× 4KB/页表 = 4KB
- 总计：16KB（vs 512GB）

节省：512GB / 16KB = 32,000,000 倍！
```

**稀疏地址空间支持**：

```
进程地址空间（典型布局）：

0x00000000_00000000   ┌──────────────┐
                      │  未映射      │ ← 不需要页表
0x00000000_00400000   ├──────────────┤
                      │  .text 代码  │ ← 需要页表
0x00000000_00500000   ├──────────────┤
                      │  未映射      │ ← 不需要页表（几十 GB 空洞）
0x00007FFF_FF000000   ├──────────────┤
                      │  栈          │ ← 需要页表
0x00007FFF_FFFF0000   ├──────────────┤
                      │  未映射      │
0x0000FFFF_FFFFFFFF   └──────────────┘

四级页表：
- 只为实际使用的区域分配页表
- 未映射区域：PML4/PDPT/PD 条目为 0，不分配下级页表
- 动态按需分配：malloc() 时才分配新的 PT 页
```

### 2.3 页表项结构详解

**页表项（Page Table Entry, PTE）** 是一个 64 位值，定义了虚拟页到物理页的映射及其属性。

**PTE 结构（x86-64）**：

```
63  62  59  52 51            12 11  9  8  7  6  5  4  3  2  1  0
┌───┬──┬─────┬────────────────┬─────┬──┬──┬──┬──┬──┬──┬──┬──┬──┐
│NX │Res│SW  │ Physical Page  │ AVL │G │PS│D │A │CD│WT│U │W │P │
│   │   │Use │  Frame [51:12] │     │  │  │  │  │  │  │S │R │  │
└───┴──┴─────┴────────────────┴─────┴──┴──┴──┴──┴──┴──┴──┴──┴──┘

字段说明：
Bit 0: P (Present) - 页是否在内存中
       1 = 在内存中, 0 = 不在内存（触发 #PF 缺页异常）

Bit 1: R/W (Read/Write) - 读写权限
       1 = 可读写, 0 = 只读

Bit 2: U/S (User/Supervisor) - 特权级
       1 = 用户可访问（CPL=3）, 0 = 仅内核可访问（CPL=0）

Bit 3: PWT (Page Write-Through) - 写穿透缓存
Bit 4: PCD (Page Cache Disable) - 禁用缓存
Bit 5: A (Accessed) - 是否被访问过
Bit 6: D (Dirty) - 是否被写过
Bit 7: PS (Page Size) - 页大小
       0 = 4KB 页, 1 = 大页（2MB 或 1GB）

Bit 8: G (Global) - 全局页（TLB 不刷新）
Bit 11-9: AVL (Available) - 系统软件可用

Bit 51-12: Physical Page Frame - 物理页框号（40 位，支持 1PB 物理内存）

Bit 62-52: Reserved / Software Use
Bit 63: NX (No Execute) - 禁止执行（需要 EFER.NXE=1）
```

**权限检查规则**：

```
访问页时，CPU 检查所有级别的权限位（与操作）：

R/W 权限：
- PML4.W=1 AND PDPT.W=1 AND PD.W=1 AND PT.W=1 → 可写
- 任何一级 W=0 → 只读

U/S 权限：
- PML4.U=1 AND PDPT.U=1 AND PD.U=1 AND PT.U=1 → 用户可访问
- 任何一级 U=0 → 仅内核可访问

示例：
PML4[0].U=1, PDPT[0].U=1, PD[0].U=1, PT[0].U=0
→ 结果：仅内核可访问（最严格的生效）
```

**大页（Huge Page）支持**：

```
2MB 大页（PD 级别）：
PML4 → PDPT → PD.PS=1 → 2MB 物理页
                  ↑
                  不需要 PT 级别

1GB 大页（PDPT 级别）：
PML4 → PDPT.PS=1 → 1GB 物理页
            ↑
            不需要 PD 和 PT 级别

优点：
1. 减少页表层级：更少的内存访问
2. TLB 覆盖范围更大：512 个 2MB 页 = 1GB
3. 减少页表内存占用

缺点：
1. 内存碎片：必须连续 2MB/1GB 物理内存
2. 浪费：小文件也占用完整大页
3. 灵活性降低：不能精细控制权限
```

### 2.4 MMU 硬件遍历机制

**MMU（Memory Management Unit）** 是 CPU 中的硬件单元，负责自动执行虚拟地址到物理地址的转换。

**MMU 遍历页表的伪代码**：

```c
// 输入：48位虚拟地址
// 输出：物理地址
uint64_t mmu_translate(uint64_t virt_addr) {
    // 1. 拆分虚拟地址
    uint64_t pml4_index = (virt_addr >> 39) & 0x1FF;  // [47:39]
    uint64_t pdpt_index = (virt_addr >> 30) & 0x1FF;  // [38:30]
    uint64_t pd_index   = (virt_addr >> 21) & 0x1FF;  // [29:21]
    uint64_t pt_index   = (virt_addr >> 12) & 0x1FF;  // [20:12]
    uint64_t offset     = virt_addr & 0xFFF;          // [11:0]

    // 2. 从 CR3 获取 PML4 基址
    uint64_t pml4_base = read_cr3() & ~0xFFF;  // 清除低 12 位标志

    // 3. 读取 PML4 条目
    uint64_t *pml4 = (uint64_t *)pml4_base;
    uint64_t pml4_entry = pml4[pml4_index];
    if (!(pml4_entry & PAGE_PRESENT)) {
        raise_page_fault();  // #PF 异常
    }

    // 4. 读取 PDPT 条目
    uint64_t pdpt_base = pml4_entry & 0xFFFFFFFFF000;
    uint64_t *pdpt = (uint64_t *)pdpt_base;
    uint64_t pdpt_entry = pdpt[pdpt_index];
    if (!(pdpt_entry & PAGE_PRESENT)) {
        raise_page_fault();
    }
    if (pdpt_entry & PAGE_SIZE) {
        // 1GB 大页
        uint64_t phys_base = pdpt_entry & 0xFFFFC0000000;
        return phys_base + (virt_addr & 0x3FFFFFFF);
    }

    // 5. 读取 PD 条目
    uint64_t pd_base = pdpt_entry & 0xFFFFFFFFF000;
    uint64_t *pd = (uint64_t *)pd_base;
    uint64_t pd_entry = pd[pd_index];
    if (!(pd_entry & PAGE_PRESENT)) {
        raise_page_fault();
    }
    if (pd_entry & PAGE_SIZE) {
        // 2MB 大页
        uint64_t phys_base = pd_entry & 0xFFFFFFE00000;
        return phys_base + (virt_addr & 0x1FFFFF);
    }

    // 6. 读取 PT 条目
    uint64_t pt_base = pd_entry & 0xFFFFFFFFF000;
    uint64_t *pt = (uint64_t *)pt_base;
    uint64_t pt_entry = pt[pt_index];
    if (!(pt_entry & PAGE_PRESENT)) {
        raise_page_fault();
    }

    // 7. 获取物理页框并加上偏移
    uint64_t phys_page = pt_entry & 0xFFFFFFFFF000;
    return phys_page + offset;
}
```

**MMU 遍历的关键点**：

```
1. 硬件自动执行：
   - 每次内存访问都触发 MMU
   - CPU 不需要软件干预
   - 对程序透明

2. 多次内存访问：
   - 4 级页表 = 4 次内存访问
   - 加上最终数据访问 = 5 次
   - 性能影响：TLB 缓存缓解

3. 权限检查：
   - 每一级都检查 P/W/U 位
   - 违反权限 → #PF 异常
   - 内核处理缺页或终止进程

4. TLB 加速：
   - 缓存虚拟地址 → 物理地址映射
   - 命中率 90-99%
   - TLB 未命中才走完整页表遍历
```

**TLB（Translation Lookaside Buffer）**：

```
TLB 是 MMU 中的缓存，存储最近使用的页表映射。

结构：
┌────────────────┬───────────────┬────────┐
│  Virtual Page  │ Physical Page │ Flags  │
├────────────────┼───────────────┼────────┤
│ 0x00400000     │ 0x10000000    │ U=1,W=1│
│ 0x00401000     │ 0x10001000    │ U=1,W=1│
│ 0x7FFFFF0000   │ 0x20000000    │ U=1,W=1│
│ ...            │ ...           │ ...    │
└────────────────┴───────────────┴────────┘

命中流程：
1. CPU 访问虚拟地址 0x00400100
2. 查询 TLB：0x00400000 命中 → 物理页 0x10000000
3. 直接计算：0x10000000 + 0x100 = 0x10000100
4. 访问物理地址（1 次内存访问）

未命中流程：
1. TLB 查询失败
2. MMU 走完整页表遍历（4 次内存访问）
3. 更新 TLB（替换最久未使用的条目）
4. 返回物理地址

TLB 刷新：
- 进程切换：刷新所有非全局页（G=0）
- 修改页表：invlpg 指令刷新单个页
- 修改 CR3：刷新所有 TLB（除了 G=1 的页）
```

---

## 第三部分：GDT 与分页的协作

### 3.1 段 + 页的二级转换

x86 架构的地址转换是一个二级过程：先通过 GDT 进行段式转换，再通过页表进行分页转换。

**完整地址转换流程**：

```
保护模式（32 位）：
┌──────────────┐
│ 逻辑地址     │ ← 程序使用的地址
│ CS:0x1234    │
└──────┬───────┘
       │
       │ ① 段式转换（GDT）
       ↓
┌──────────────┐
│ 线性地址     │ ← 段基址 + 偏移
│ 0x80001234   │
└──────┬───────┘
       │
       │ ② 分页转换（Page Table）
       ↓
┌──────────────┐
│ 物理地址     │
│ 0x12345234   │
└──────────────┘

长模式（64 位）：
┌──────────────┐
│ 逻辑地址     │ ← 程序使用的地址
│ CS:0x1234    │
└──────┬───────┘
       │
       │ ① 段式转换（GDT，Base=0）
       ↓
┌──────────────┐
│ 线性地址     │ ← 等于偏移
│ 0x1234       │
└──────┬───────┘
       │
       │ ② 分页转换（Page Table，强制）
       ↓
┌──────────────┐
│ 物理地址     │
│ 0x12345234   │
└──────────────┘
```

### 3.2 为什么长模式仍需要 GDT？

虽然长模式下段基址强制为 0，但 **GDT 仍然是必需的**，原因如下：

**1. 权限控制（DPL）**

```c
// GDT 中的段描述符定义特权级
GDT[KERNEL_CS].DPL = 0;  // Ring 0（内核）
GDT[USER_CS].DPL = 3;    // Ring 3（用户）

// CPU 检查权限
if (current_CPL != target_DPL) {
    raise_general_protection_fault();  // #GP 异常
}
```

**2. 段类型标识**

```c
// 区分代码段和数据段
GDT[KERNEL_CS].Type = CODE_EXECUTE_READ;  // 可执行
GDT[KERNEL_DS].Type = DATA_READ_WRITE;    // 可读写

// CPU 检查操作合法性
if (executing_from_data_segment) {
    raise_general_protection_fault();  // #GP 异常
}
```

**3. 长模式标志（L 位）**

```c
// 标识 64 位代码段
GDT[KERNEL_CS].L = 1;  // Long Mode
GDT[KERNEL_CS].D = 0;  // 必须为 0（64 位）

// CPU 根据 CS.L 位决定指令解码模式
if (CS.L == 1) {
    decode_64bit_instruction();
} else {
    decode_32bit_or_16bit_instruction();
}
```

**4. TSS（Task State Segment）**

```c
// TSS 描述符在 GDT 中
GDT[TSS_INDEX] = {
    .base = (uint64_t)&tss,
    .limit = sizeof(tss) - 1,
    .type = TSS_AVAILABLE,
};

// 特权级切换时，CPU 从 TSS 读取内核栈
user_to_kernel_transition() {
    RSP = TSS.RSP0;  // 切换到内核栈
    SS = __KERNEL_DS;
}
```

**5. SYSCALL/SYSRET 指令依赖**

```c
// SYSCALL 指令硬编码 GDT 索引
// MSR_STAR 寄存器定义系统调用时使用的段选择子
MSR_STAR = {
    .SYSRET_CS = __USER_CS,        // 返回用户态时的 CS
    .SYSCALL_CS = __KERNEL_CS,     // 进入内核时的 CS
};

// SYSCALL 指令自动：
// CS = MSR_STAR.SYSCALL_CS;
// SS = MSR_STAR.SYSCALL_CS + 8;
```

### 3.3 GDT Identity Mapping 机制

**Identity Mapping** 是一种特殊的 GDT 设置，使虚拟地址等于物理地址。

**为什么需要 Identity Mapping？**

```
问题场景：启用分页时的平滑过渡

┌────────────────────────────────┐
│ 1. 分页关闭（CR0.PG=0）        │
│    线性地址 = 物理地址         │
│    CPU 执行地址：0x100000      │
└────────────────────────────────┘
                ↓
┌────────────────────────────────┐
│ 2. 写 CR0.PG=1（开启分页）     │
│    下一条指令地址：0x100004    │
│    问题：分页已启用，但页表中  │
│          没有 0x100004 的映射！│
│    结果：#PF 异常（系统崩溃）  │
└────────────────────────────────┘

解决方案：Identity Mapping

┌────────────────────────────────┐
│ 页表设置：                     │
│ 虚拟 0x100000 → 物理 0x100000  │
│ 虚拟 0x101000 → 物理 0x101000  │
│ ...                            │
└────────────────────────────────┘
                ↓
┌────────────────────────────────┐
│ 1. 分页关闭：PC=0x100000       │
│    执行地址：物理 0x100000     │
│ 2. 开启分页：CR0.PG=1          │
│ 3. 下一条指令：PC=0x100004     │
│    MMU 转换：0x100004→0x100004 │
│    执行地址：物理 0x100004     │
│ 结果：✅ 平滑过渡，无异常      │
└────────────────────────────────┘
```

**Identity Mapping 的实现**：

```c
// arch/x86/boot/compressed/head_64.S
// 建立 Identity Mapping（1:1 映射）

// 映射低端 4GB 物理内存
for (uint64_t phys = 0; phys < 4GB; phys += 2MB) {
    pde[phys / 2MB] = phys | PAGE_PRESENT | PAGE_RW | PAGE_SIZE;
}

// 页表项示例：
// PD[0] = 0x00000000 | PAGE_PRESENT | PAGE_RW | PAGE_SIZE  // 虚拟 0MB → 物理 0MB
// PD[1] = 0x00200000 | PAGE_PRESENT | PAGE_RW | PAGE_SIZE  // 虚拟 2MB → 物理 2MB
// PD[2] = 0x00400000 | PAGE_PRESENT | PAGE_RW | PAGE_SIZE  // 虚拟 4MB → 物理 4MB
// ...
```

**Identity Mapping 的生命周期**：

```
阶段 1：压缩内核（Compressed Kernel）
┌─────────────────────────────────┐
│ Identity Mapping                │
│ 虚拟 0-4GB → 物理 0-4GB         │
│ 目的：启用分页后代码仍可运行    │
└─────────────────────────────────┘
                ↓
阶段 2：主内核早期（Main Kernel Early）
┌─────────────────────────────────┐
│ Identity Mapping +              │
│ Direct Mapping (High Address)   │
│ 虚拟 0-1GB → 物理 0-1GB         │
│ 虚拟 0xFFFF888000000000+offset  │
│        → 物理 0x00000000+offset │
└─────────────────────────────────┘
                ↓
阶段 3：运行时（Runtime）
┌─────────────────────────────────┐
│ Direct Mapping Only             │
│ 移除 Identity Mapping           │
│ 虚拟 0xFFFF888000000000+offset  │
│        → 物理 0x00000000+offset │
│ 目的：内核运行在高地址          │
│       用户空间使用低地址        │
└─────────────────────────────────┘
```

**为什么最终移除 Identity Mapping？**

```
1. 安全性：
   - Identity Mapping 使低地址可直接访问物理内存
   - 用户程序可能利用这个漏洞访问内核内存
   - 移除后，低地址留给用户空间

2. 地址空间隔离：
   - 内核：0xFFFF800000000000 - 0xFFFFFFFFFFFFFFFF（高地址）
   - 用户：0x0000000000000000 - 0x00007FFFFFFFFFFF（低地址）
   - 清晰的边界，防止误操作

3. KASLR（内核地址空间随机化）：
   - 内核加载地址随机化
   - Identity Mapping 会暴露实际物理地址
   - 移除后增强安全性
```

---

## 总结

### 核心概念回顾

1. **GDT 的角色演变**
   - 保护模式：地址转换 + 权限控制
   - 长模式：仅权限控制（段基址强制为 0）

2. **分页的核心优势**
   - 地址空间隔离
   - 内存保护
   - 按需分配
   - 共享内存

3. **多级页表的设计**
   - 节省内存（512GB → 几十 KB）
   - 支持稀疏地址空间
   - 动态按需分配

4. **GDT 与分页的协作**
   - 二级转换：GDT（段）→ Page Table（页）
   - 长模式简化：扁平模式 + 强制分页
   - Identity Mapping：平滑过渡机制

### 深入阅读

- **[演化篇](LINUX_MEMORY_MANAGEMENT_EVOLUTION.md)**：了解 BIOS → GRUB → 内核的内存管理过渡
- **[实现篇](LINUX_MEMORY_MANAGEMENT_CODE_GUIDE.md)**：深入 Linux 源代码实现细节
- **[Linux 内核启动](LINUX_KERNEL_INIT.md)**：查看 GDT 和页表在启动流程中的作用

---

**文档版本**：v1.0
**最后更新**：2026-02
**维护者**：Linux 内核文档项目
