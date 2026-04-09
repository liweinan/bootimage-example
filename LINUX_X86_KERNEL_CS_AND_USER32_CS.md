# x86_64：`__KERNEL_CS` 与 `__USER32_CS` — 数值、选择子编码与 Ring

本文从 Linux 主线约定出发（**长模式 / `CONFIG_X86_64`**），归纳 **`__KERNEL_CS`**、**`__USER32_CS`** 的**宏展开数值**、**段选择子各位含义**，以及它们与 **GDT 描述符 DPL**、当前 **CPL（CPU ring）** 的关系。源码路径以 **`arch/x86/`** 为准（行号随内核版本漂移，以你本机树为准）。

**相关文档**：[LINUX_X86_MSR_REFERENCE.md](LINUX_X86_MSR_REFERENCE.md)（`MSR_STAR` / `syscall`）、[X86_GDT_STRUCTURE.md](X86_GDT_STRUCTURE.md)（GDT 全表与 `GDT_ENTRY_INIT`）、[LINUX_KERNEL_SYSCALL_INIT.md](LINUX_KERNEL_SYSCALL_INIT.md)（`STAR` 与 `sysret` 选择子）。

**为何不把「GDT 项与 DPL」再单开一篇**：与 **[X86_GDT_STRUCTURE.md](X86_GDT_STRUCTURE.md)** 已有分工——专文管**表结构、初始化块、Long mode 角色**；**`__KERNEL_CS` / `__USER_CS` 与 DPL 推导**与本文主题一致，故将 **`GDT_ENTRY_INIT` → `.dpl`** 的机械说明并入 **§3.1.1**，并在 **X86_GDT_STRUCTURE §5** 增加互链，避免两处维护同一推导链。

---

## 1. 宏定义位置与「初始」数值（64 位）

定义在 **`arch/x86/include/asm/segment.h`**（`#else /* 64-bit: */` 分支）：

```c
// arch/x86/include/asm/segment.h (line 169~217)
#define GDT_ENTRY_KERNEL32_CS		1
#define GDT_ENTRY_KERNEL_CS		2
#define GDT_ENTRY_KERNEL_DS		3
#define GDT_ENTRY_DEFAULT_USER32_CS	4
#define GDT_ENTRY_DEFAULT_USER_DS	5
#define GDT_ENTRY_DEFAULT_USER_CS	6

#define __KERNEL32_CS			(GDT_ENTRY_KERNEL32_CS*8)
#define __KERNEL_CS			(GDT_ENTRY_KERNEL_CS*8)
#define __KERNEL_DS			(GDT_ENTRY_KERNEL_DS*8)
#define __USER32_CS			(GDT_ENTRY_DEFAULT_USER32_CS*8 + 3)
#define __USER_DS			(GDT_ENTRY_DEFAULT_USER_DS*8 + 3)
#define __USER_CS			(GDT_ENTRY_DEFAULT_USER_CS*8 + 3)
```

### 1.1 选择子的完整二进制编码

按宏计算 **选择子常量的十六进制、十进制与二进制分解**：

| 宏 | 计算 | 十六进制 | 二进制（15:0） | 索引（15:3） | TI（2） | RPL（1:0） |
|----|------|----------|---------------|-------------|---------|-----------|
| **`__KERNEL_CS`** | `2 × 8` | **`0x0010`** | `0b0000_0000_0001_0000` | **`2`** | **`0`** (GDT) | **`0`** (ring0) |
| **`__USER32_CS`** | `4 × 8 + 3` | **`0x0023`** | `0b0000_0000_0010_0011` | **`4`** | **`0`** (GDT) | **`3`** (ring3) |

**字段含义**（参考 Intel SDM Vol.3A §3.4.2「Segment Selectors」）：
- **bit 15:3**：GDT/LDT 中的**描述符索引**（每条描述符 8 字节，故 `index × 8` 得到字节偏移）
- **bit 2**：**TI（Table Indicator）**，**0** = GDT，**1** = LDT
- **bit 1:0**：**RPL（Requested Privilege Level）**，请求特权级，**0** = ring0，**3** = ring3

**关键点**：内核侧选择子不带 `+ 3`，故 **RPL=0**；用户侧选择子显式 **`+ 3`**，故 **RPL=3**（见 `segment.h` 注释：*selectors also need to have a correct RPL*）。

顺带（常与同一张 GDT、`sysret` **+8/+16** 布局一起出现）：

| 宏 | 十六进制 | 二进制 | 索引 | RPL |
|----|----------|--------|------|-----|
| **`__KERNEL_DS`** | `0x0018` | `0b0000_0000_0001_1000` | 3 | 0 |
| **`__USER_DS`** | `0x002B` | `0b0000_0000_0010_1011` | 5 | 3 |
| **`__USER_CS`** | `0x0033` | `0b0000_0000_0011_0011` | 6 | 3（**64 位用户代码**） |

---

## 2. 选择子与描述符：RPL vs DPL

### 2.1 选择子的 RPL（在选择子自身）

一个 **16 位段选择子** 可拆成（参考 §1.1）：
- **bit 1:0 — RPL**（Requested Privilege Level）：**请求特权级**，存储在**选择子自身**
- **bit 2 — TI**（Table Indicator）：**0** = GDT，**1** = LDT
- **bit 15:3 — 索引**：在 GDT/LDT 中的条目号

### 2.2 描述符的 DPL（在 GDT 描述符内部）

**DPL（Descriptor Privilege Level）** 是 **GDT/LDT 里每条 8 字节描述符** 的一个**内部字段**，**不在**选择子的 16 位里；CPU 在段加载时会：
1. 根据选择子的 **索引** 从 GDT 读取对应的 **8 字节描述符**
2. 从描述符中提取 **DPL 字段**（2 位，参考 Intel SDM Vol.3A Figure 3-8「Segment Descriptor」）
3. 将描述符的 **DPL** 与选择子的 **RPL**、当前 **CPL** 一起做特权检查

**描述符的 DPL 字段位置**（64 字节 = 2 个 32 位双字，参考 SDM Figure 3-8）：
```
高 32 位双字（bit 63:32）：
┌─────────────────────────────────────────────────────────────┐
│ Base[31:24] │ G │ D/B │ L │ AVL │ Limit[19:16] │ P │ DPL │ S │ Type │ Base[23:16] │
│   (bit 63:56) │63 │ 62  │61 │ 60  │  (59:56)     │55 │54:53│52│51:48│  (47:40)    │
└─────────────────────────────────────────────────────────────┘
```
- **bit 54:53 — DPL**（2 位）：描述符特权级，**0** = ring0，**3** = ring3
- **bit 52 — S**：**1** = 代码/数据段，**0** = 系统段（TSS/LDT）
- **bit 51:48 — Type**：段类型（可执行、可写、已访问等）

在 Linux 内核中，`GDT_ENTRY_INIT` 宏（`arch/x86/include/asm/desc_defs.h:73-88`）将这些字段打包：
```c
struct desc_struct {
    u16 limit0;
    u16 base0;
    u16 base1: 8, type: 4, s: 1, dpl: 2, p: 1;  // dpl 占 2 位
    u16 limit1: 4, avl: 1, l: 1, d: 1, g: 1, base2: 8;
} __attribute__((packed));
```

**关键区分**：
- **RPL**：存储在**选择子**（16 位）的 bit 1:0，是「**请求者声明的特权级**」
- **DPL**：存储在**描述符**（64 位）的 bit 54:53，是「**该段要求的最低特权级**」
- **CPL**：存储在**当前 CS/SS 寄存器**的 bit 1:0（即 CS 寄存器的 RPL 字段），是「**CPU 当前执行的特权级**」

访问时特权检查规则（对于数据段）：**`max(CPL, RPL) ≤ DPL`** 才能访问（代码段规则更复杂，参考 SDM §5.5）。

---

## 3. GDT 初始化与选择子→描述符→CPL 的完整映射

与 **[X86_GDT_STRUCTURE.md §5](X86_GDT_STRUCTURE.md)** 的关系：**§5** 概述 `gdt_page` 静态初始化与 `DESC_USER` 结论；**本节 §3.1** 给出「**仅看 `common.c` + `desc_defs.h` 如何机械推出 `GDT_ENTRY_KERNEL_CS` / `GDT_ENTRY_DEFAULT_USER_CS` 对应描述符的 DPL**」的推导链，避免与专文重复时两处漂移。

### 3.1 GDT 描述符的初始化（内核 vs 用户）

`DEFINE_PER_CPU_PAGE_ALIGNED(struct gdt_page, gdt_page)` 的静态初值在 **`arch/x86/kernel/cpu/common.c`**（`CONFIG_X86_64` 分支，约 210–252 行）：

```c
// arch/x86/kernel/cpu/common.c（节选）
[GDT_ENTRY_KERNEL_CS]         = GDT_ENTRY_INIT(DESC_CODE64, 0, 0xfffff),
[GDT_ENTRY_KERNEL_DS]         = GDT_ENTRY_INIT(DESC_DATA64, 0, 0xfffff),
[GDT_ENTRY_DEFAULT_USER32_CS] = GDT_ENTRY_INIT(DESC_CODE32 | DESC_USER, 0, 0xfffff),
[GDT_ENTRY_DEFAULT_USER_DS]   = GDT_ENTRY_INIT(DESC_DATA64 | DESC_USER, 0, 0xfffff),
[GDT_ENTRY_DEFAULT_USER_CS]   = GDT_ENTRY_INIT(DESC_CODE64 | DESC_USER, 0, 0xfffff),
```

#### 3.1.1 机械推导：`GDT_ENTRY_KERNEL_CS` 与 `GDT_ENTRY_DEFAULT_USER_CS` 的 DPL 为何是 **0** 与 **3**

1. **只看两条 code 项传入 `GDT_ENTRY_INIT` 的第一个参数 `flags`**：
   - **`GDT_ENTRY_KERNEL_CS`**：`flags = DESC_CODE64`（**无** `DESC_USER`）。
   - **`GDT_ENTRY_DEFAULT_USER_CS`**：`flags = DESC_CODE64 | DESC_USER`。

2. **`DESC_USER` 即把 DPL 编成 3**：在 **`arch/x86/include/asm/desc_defs.h`** 中  
   `#define DESC_USER (_DESC_DPL(3))`，而 `#define _DESC_DPL(dpl) ((dpl) << 5)`。  
   因此 **`DESC_CODE64 | DESC_USER`** 在 `flags` 里带上了 **DPL=3** 的编码；**仅 `DESC_CODE64`** 时 **不**含 `_DESC_DPL(3)`，**flags 里与 DPL 对应的两比特为 0**（一般不写显式 `_DESC_DPL(0)`，而是「未置用户 DPL」）。

3. **`GDT_ENTRY_INIT` 如何把 `flags` 写进 `struct desc_struct.dpl`**（同文件，宏体以树内为准）：

```73:88:/Users/weli/works/linux/arch/x86/include/asm/desc_defs.h
#define GDT_ENTRY_INIT(flags, base, limit)			\
	{							\
		.limit0		= ((limit) >>  0) & 0xFFFF,	\
		.limit1		= ((limit) >> 16) & 0x000F,	\
		.base0		= ((base)  >>  0) & 0xFFFF,	\
		.base1		= ((base)  >> 16) & 0x00FF,	\
		.base2		= ((base)  >> 24) & 0x00FF,	\
		.type		= ((flags) >>  0) & 0x000F,	\
		.s		= ((flags) >>  4) & 0x0001,	\
		.dpl		= ((flags) >>  5) & 0x0003,	\
		.p		= ((flags) >>  7) & 0x0001,	\
		...
	}
```

**读法**：**`.dpl = ((flags) >> 5) & 3`**，即从 `flags` 的 **第 5～6 位**取出 **2 位二进制 DPL**（0～3）。  
因此：**`DESC_CODE64` alone → DPL=0**；**`DESC_CODE64 | DESC_USER` → DPL=3**。无需在别处再手写 `gdt[...].dpl = 0/3`，初始化器已一次性写入。

#### 3.1.2 `DESC_*` 标志展开（便于对照）

（`arch/x86/include/asm/desc_defs.h` 中与 code/data 相关的组合宏，节选意）

```c
#define _DESC_DPL(dpl)       ((dpl) << 5)
#define DESC_USER            (_DESC_DPL(3))

#define DESC_CODE64          (_DESC_CODE | _DESC_GRANULARITY_4K | _DESC_LONG_CODE)
#define DESC_CODE32          (_DESC_CODE | _DESC_GRANULARITY_4K | _DESC_DB)
#define DESC_DATA64          (_DESC_DATA | _DESC_GRANULARITY_4K | _DESC_DB)
```

**小结**：

| GDT 槽位（宏名） | `GDT_ENTRY_INIT` 的 `flags` | 推出 `.dpl` |
|------------------|----------------------------|-------------|
| `GDT_ENTRY_KERNEL_CS` | `DESC_CODE64` | **0** |
| `GDT_ENTRY_DEFAULT_USER_CS` | `DESC_CODE64 \| DESC_USER` | **3** |

### 3.2 选择子 → GDT 描述符 → CPL 的映射表

| 选择子宏 | 选择子值 | GDT 索引 | 选择子 RPL | 描述符 flags | **描述符 DPL** | **加载后 CPL** | Ring |
|---------|---------|---------|----------|-------------|--------------|---------------|------|
| **`__KERNEL_CS`** | `0x0010` | **2** | **0** | `DESC_CODE64` | **0** | **0** | **ring0** |
| **`__USER32_CS`** | `0x0023` | **4** | **3** | `DESC_CODE32 \| DESC_USER` | **3** | **3** | **ring3** |
| **`__KERNEL_DS`** | `0x0018` | **3** | **0** | `DESC_DATA64` | **0** | （SS 加载时 CPL=0） | ring0 |
| **`__USER_DS`** | `0x002B` | **5** | **3** | `DESC_DATA64 \| DESC_USER` | **3** | （SS 加载时 CPL=3） | ring3 |
| **`__USER_CS`** | `0x0033` | **6** | **3** | `DESC_CODE64 \| DESC_USER` | **3** | **3** | **ring3** |

**CPL 的定义**（参考 Intel SDM Vol.3A §5.5「Privilege Levels」）：
- **CPL（Current Privilege Level）** 存储在 **当前 CS 寄存器**的 **bit 1:0**（即选择子的 RPL 字段）
- **CS 加载时**，CPU 从 GDT 读取描述符，检查 **`CPL` 与描述符的 `DPL` 是否匹配**（代码段要求 `CPL == DPL`，除非是 conforming 段），然后将选择子写入 CS
- **加载后**，**CPU 的 CPL = CS.RPL**（即 CS 寄存器当前值的 bit 1:0）

**关键点**（在「当前 **CS** 指向该段且已完成加载」的语境下）：
1. **内核态**：`CS = 0x0010` → **CPL = 0**（从 CS 的 bit 1:0 提取）
2. **用户态**：`CS = 0x0023` 或 `0x0033` → **CPL = 3**
3. **`syscall` 切换**：硬件将 `CS ← MSR_STAR[47:32]`（即 `__KERNEL_CS = 0x10`），故 **CPL 从 3 变为 0**
4. **`sysret` 切换**：硬件将 `CS ← MSR_STAR[63:48] + 16`（即 `0x23 + 16 = 0x33`），故 **CPL 从 0 变为 3**

### 3.3 长模式平坦模型下的简化

在 **64 位长模式 + 平坦内存模型**（Linux 默认配置）下：
- **段基址**（`base`）：GDT 中所有段的 `base = 0`
- **段限制**（`limit`）：所有段的 `limit = 0xfffff`，配合 `G=1`（4KB 粒度）→ 有效范围 **0 到 4GB**（但长模式忽略此限制）
- **段寄存器不参与地址计算**：线性地址 = 虚拟地址（段基址总为 0）
- **分页机制主导**：通过页表实现内存隔离，**段机制仅用于特权级检查**

**简化后的关注点**：
1. **DPL**：决定该段是 ring0（内核）还是 ring3（用户）
2. **CPL**：决定 CPU 当前运行在哪个 ring
3. **L 位**：决定代码段是 64 位模式（`L=1`，即 `DESC_CODE64` 的 `_DESC_LONG_CODE`）还是兼容模式（`L=0, D=1`，即 `DESC_CODE32` 的 `_DESC_DB`）

#### 内核 GDT 的实际初始化值（`arch/x86/kernel/cpu/common.c:210-252`）

在 **`CONFIG_X86_64`** 分支下，`gdt_page` 的静态初值（仅列出前 7 个条目）：

| 索引 | 条目名称 | flags | **base** | **limit** | **DPL** | L | D/B | G | Ring | 用途 |
|------|---------|-------|---------|----------|---------|---|-----|---|------|------|
| 0 | `NULL` | （空条目） | `0x00000000` | `0x00000` | - | 0 | 0 | 0 | - | CPU 不使用索引 0 |
| 1 | `GDT_ENTRY_KERNEL32_CS` | `DESC_CODE32` | **`0x00000000`** | `0xfffff` | **`0`** | 0 | 1 | 1 | **ring0** | 32 位内核代码（兼容模式） |
| 2 | `GDT_ENTRY_KERNEL_CS` | `DESC_CODE64` | **`0x00000000`** | `0xfffff` | **`0`** | 1 | 0 | 1 | **ring0** | 64 位内核代码（长模式） |
| 3 | `GDT_ENTRY_KERNEL_DS` | `DESC_DATA64` | **`0x00000000`** | `0xfffff` | **`0`** | 0 | 1 | 1 | **ring0** | 内核数据段 |
| 4 | `GDT_ENTRY_DEFAULT_USER32_CS` | `DESC_CODE32 \| DESC_USER` | **`0x00000000`** | `0xfffff` | **`3`** | 0 | 1 | 1 | **ring3** | 32 位用户代码（兼容模式） |
| 5 | `GDT_ENTRY_DEFAULT_USER_DS` | `DESC_DATA64 \| DESC_USER` | **`0x00000000`** | `0xfffff` | **`3`** | 0 | 1 | 1 | **ring3** | 用户数据段 |
| 6 | `GDT_ENTRY_DEFAULT_USER_CS` | `DESC_CODE64 \| DESC_USER` | **`0x00000000`** | `0xfffff` | **`3`** | 1 | 0 | 1 | **ring3** | 64 位用户代码（长模式） |

**内核源码**（`arch/x86/kernel/cpu/common.c`）：
```c
DEFINE_PER_CPU_PAGE_ALIGNED(struct gdt_page, gdt_page) = { .gdt = {
#ifdef CONFIG_X86_64
    [GDT_ENTRY_KERNEL32_CS]       = GDT_ENTRY_INIT(DESC_CODE32, 0, 0xfffff),
    [GDT_ENTRY_KERNEL_CS]         = GDT_ENTRY_INIT(DESC_CODE64, 0, 0xfffff),
    [GDT_ENTRY_KERNEL_DS]         = GDT_ENTRY_INIT(DESC_DATA64, 0, 0xfffff),
    [GDT_ENTRY_DEFAULT_USER32_CS] = GDT_ENTRY_INIT(DESC_CODE32 | DESC_USER, 0, 0xfffff),
    [GDT_ENTRY_DEFAULT_USER_DS]   = GDT_ENTRY_INIT(DESC_DATA64 | DESC_USER, 0, 0xfffff),
    [GDT_ENTRY_DEFAULT_USER_CS]   = GDT_ENTRY_INIT(DESC_CODE64 | DESC_USER, 0, 0xfffff),
#endif
} };
```

**关键观察**：
1. **所有条目的 `base = 0x00000000`**：平坦模型，**线性地址 = 虚拟地址**
2. **所有条目的 `limit = 0xfffff`**：配合 `G=1`（4KB 粒度）→ 有效范围 **0 到 4GB**（长模式下被忽略）
3. **DPL 决定 ring**：
   - **内核条目**（索引 1-3）：`DESC_CODE64`/`DESC_CODE32`/`DESC_DATA64` **不含** `DESC_USER` → **DPL=0** → **ring0**
   - **用户条目**（索引 4-6）：`DESC_CODE32 | DESC_USER` 等 **包含** `DESC_USER` → **DPL=3** → **ring3**
4. **L 位区分 64 位 vs 兼容模式**：
   - **`DESC_CODE64`**（索引 2、6）：**L=1**，CPU 执行 64 位指令
   - **`DESC_CODE32`**（索引 1、4）：**L=0, D=1**，CPU 执行 32 位指令（兼容模式）

#### 特权级检查示例

**示例：用户态进程访问内核段**（必然失败）：
- 用户进程的 **CPL=3**（从当前 `CS = 0x0033` 提取）
- 尝试加载 **`__KERNEL_DS`**（`0x0018`，指向 GDT 索引 3，**base=0, DPL=0**）
- CPU 检查：**`max(CPL=3, RPL=0) = 3 > DPL=0`** → **#GP（通用保护异常）**

**示例：内核态访问用户段**（允许）：
- 内核代码的 **CPL=0**（从当前 `CS = 0x0010` 提取）
- 加载 **`__USER_DS`**（`0x002B`，指向 GDT 索引 5，**base=0, DPL=3**）
- CPU 检查：**`max(CPL=0, RPL=3) = 3 == DPL=3`** → **允许**

反之，内核态访问用户段是允许的（配合页表的 `U/S` 位），这也是内核能读写用户空间的原因（如 `copy_to_user`/`copy_from_user`）。

---

## 4. 为何 64 位要同时有 `__USER32_CS` 与 `__USER_CS`

长模式下仍可能跑 **兼容模式 32 位用户代码** 与 **64 位用户代码**，需要 **两条用户 code 描述符**（`DESC_CODE32|DESC_USER` 与 `DESC_CODE64|DESC_USER`），**DPL 虽都是 3**，但 **L/D/B 等属性不同**，不能共用一个描述符。

`segment.h` 中注释还指出：**`SYSCALL`/`SYSRET` 对 `STAR` 的 +8/+16 硬编码** 要求 **32 位用户 CS、USER_DS、64 位用户 CS** 在 GDT 里 **相邻布局**（索引 4、5、6），以便用 **`STAR[63:48]`** 作为 **基点** 算出 **`sysret`** 时的 **SS** 与 **CS**：

```173:186:/Users/weli/works/linux/arch/x86/include/asm/segment.h
/*
 * We cannot use the same code segment descriptor for user and kernel mode,
 * not even in long flat mode, because of different DPL.
 *
 * GDT layout to get 64-bit SYSCALL/SYSRET support right. SYSRET hardcodes
 * selectors:
 *
 *   if returning to 32-bit userspace: cs = STAR.SYSRET_CS,
 *   if returning to 64-bit userspace: cs = STAR.SYSRET_CS+16,
 *
 * ss = STAR.SYSRET_CS+8 (in either case)
 *
 * thus USER_DS should be between 32-bit and 64-bit code selectors:
 */
```

---

## 5. `MSR_STAR` 初值的一行：两枚选择子的实际应用

### 5.1 `syscall_init()` 中的 `wrmsr`

**`arch/x86/kernel/cpu/common.c`** 中的 **`syscall_init()`** 函数：

```c
wrmsr(MSR_STAR, 0, (__USER32_CS << 16) | __KERNEL_CS);
```

**展开计算**（带入 §1.1 的具体值）：
```c
__KERNEL_CS = 0x0010
__USER32_CS = 0x0023

高 32 位 = (__USER32_CS << 16) | __KERNEL_CS
        = (0x0023 << 16) | 0x0010
        = 0x00230010

// wrmsr 的两个参数：low=0, high=0x00230010
// 写入 MSR_STAR[31:0]  = 0x00000000
// 写入 MSR_STAR[63:32] = 0x00230010
```

### 5.2 `MSR_STAR` 的字段布局

`MSR_STAR`（Model-Specific Register 0xC0000081）的 64 位布局（参考 Intel SDM Vol.2B「SYSCALL」与 [LINUX_X86_MSR_REFERENCE.md](LINUX_X86_MSR_REFERENCE.md) §3）：

| 字段 | 位范围 | Linux 初值 | 含义 |
|------|--------|-----------|------|
| **`SYSCALL_CS`** | **47:32** | **`0x0010`** | **`syscall` 时加载到 CS 的选择子**（`__KERNEL_CS`） |
| **`SYSRET_CS`** | **63:48** | **`0x0023`** | **`sysret` 时推导用户 CS/SS 的基点**（`__USER32_CS`） |
| Reserved | 31:0 | `0x00000000` | 未使用（EIP 保存到 `RCX`，不用此字段） |

### 5.3 `syscall` 与 `sysret` 如何使用

**`syscall` 指令**（用户态 ring3 → 内核态 ring0）：
1. `CS ← STAR[47:32] & 0xFFFC`（即 `0x0010`，**CPL 变为 0**）
2. `SS ← STAR[47:32] + 8`（即 `0x0018 = __KERNEL_DS`）
3. `RIP ← MSR_LSTAR`（跳转到内核 syscall 入口）

**`sysret` 指令**（内核态 ring0 → 用户态 ring3，**64 位用户代码**）：
1. `CS ← (STAR[63:48] + 16) | 3`（即 `(0x0023 + 16) | 3 = 0x0033 | 3 = 0x0033`，**CPL 变为 3**）
2. `SS ← (STAR[63:48] + 8) | 3`（即 `(0x0023 + 8) | 3 = 0x002B`）
3. `RIP ← RCX`（返回用户态保存的 RIP）

**关键点**：
- **`STAR[63:48] = 0x0023`**（即 `__USER32_CS`）是**基点**，`sysret` 通过 **+16** 得到 **`__USER_CS = 0x0033`**（64 位用户代码），通过 **+8** 得到 **`__USER_DS = 0x002B`**
- 这要求 GDT 布局必须满足 **索引 4、5、6 相邻**（即 `__USER32_CS`、`__USER_DS`、`__USER_CS`），参考 §4 的 `segment.h` 注释
- **`| 3`** 操作确保返回用户态时 **RPL=3**（即使原始基点的 RPL 不是 3）

### 5.4 完整映射汇总

| 场景 | CS 值 | GDT 索引 | 描述符 DPL | CS.RPL | **CPL** | Ring |
|------|-------|---------|-----------|--------|---------|------|
| **`syscall` 后（内核态）** | `0x0010` | 2 | 0 | 0 | **0** | ring0 |
| **`sysret` 后（64 位用户态）** | `0x0033` | 6 | 3 | 3 | **3** | ring3 |
| **`sysret` 后（32 位用户态，罕见）** | `0x0023` | 4 | 3 | 3 | **3** | ring3 |

**验证**：两枚选择子的 **数值、RPL、GDT 索引** 见 §1.1；对应的 **GDT 描述符 DPL、加载后 CPL** 见 §3.2。

---

## 6. 长模式平坦模型下的完整映射速查表

在 **x86_64 长模式 + 平坦内存模型**（`CONFIG_X86_64`，段基址=0，段限制=0xfffff）下，段机制**仅用于特权级检查**，地址计算由分页机制主导。以下速查表归纳了**选择子 → GDT 描述符 → CPL → Ring** 的完整映射：

### 6.1 内核态 vs 用户态的完整对比

| 项目 | **内核态（Kernel Space）** | **用户态（User Space，64 位）** | **用户态（User Space，32 位兼容）** |
|------|-------------------------|---------------------------|------------------------------|
| **代码段选择子** | `__KERNEL_CS = 0x0010` | `__USER_CS = 0x0033` | `__USER32_CS = 0x0023` |
| **数据段选择子** | `__KERNEL_DS = 0x0018` | `__USER_DS = 0x002B` | `__USER_DS = 0x002B` |
| **选择子二进制** | `0b0000_0000_0001_0000` | `0b0000_0000_0011_0011` | `0b0000_0000_0010_0011` |
| **GDT 索引（CS）** | 2 | 6 | 4 |
| **选择子 RPL（CS）** | 0 | 3 | 3 |
| **描述符 flags** | `DESC_CODE64` | `DESC_CODE64 \| DESC_USER` | `DESC_CODE32 \| DESC_USER` |
| **描述符 DPL** | **0** | **3** | **3** |
| **描述符 L 位** | 1（64 位代码） | 1（64 位代码） | 0（兼容模式 32 位代码） |
| **加载后 CPL** | **0** | **3** | **3** |
| **Ring** | **ring0（内核态）** | **ring3（用户态）** | **ring3（用户态）** |
| **进入方式** | `syscall`、中断/异常 | `sysret`、`iret` | `sysret`（指定 32 位模式） |

### 6.2 关键概念的三层映射

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. 选择子层（16 位，存储在段寄存器 CS/SS/DS/ES/FS/GS 中）        │
├─────────────────────────────────────────────────────────────────┤
│ __KERNEL_CS (0x0010)     __USER32_CS (0x0023)                   │
│ └─ 索引=2, TI=0, RPL=0   └─ 索引=4, TI=0, RPL=3                 │
│                                                                 │
│         ↓ CPU 根据索引查找 GDT                                   │
│                                                                 │
│ 2. 描述符层（8 字节，存储在 GDT[索引] 中）                       │
├─────────────────────────────────────────────────────────────────┤
│ GDT[2]: DESC_CODE64           GDT[4]: DESC_CODE32|DESC_USER    │
│ └─ DPL=0, L=1, S=1, Type=0xA  └─ DPL=3, L=0, D=1, S=1, Type=0xA│
│                                                                 │
│         ↓ CPU 加载描述符到段寄存器的隐藏部分                      │
│                                                                 │
│ 3. CPL 层（2 位，从当前 CS 寄存器的 bit 1:0 提取）              │
├─────────────────────────────────────────────────────────────────┤
│ CPL = CS.RPL = 0 (ring0)     CPL = CS.RPL = 3 (ring3)          │
│ └─ 内核态，可访问所有资源     └─ 用户态，受页表 U/S 位限制       │
└─────────────────────────────────────────────────────────────────┘
```

### 6.3 特权级检查的完整规则

**数据段访问**（加载 DS/ES/FS/GS 时）：
```
max(CPL, 选择子.RPL) ≤ 描述符.DPL  →  允许访问
否则  →  #GP（通用保护异常）
```

**代码段跳转**（`jmp`/`call` 到非特权转移门时）：
```
对于非 conforming 代码段：CPL == 描述符.DPL && 选择子.RPL ≤ CPL
对于 conforming 代码段：  CPL ≥ 描述符.DPL
```

**`syscall`/`sysret` 的硬编码行为**：
- `syscall`：**硬件强制将 CS 设为 `MSR_STAR[47:32]`**（Linux 设为 `0x0010`），**CPL 变为 0**（从 CS.RPL 提取）
- `sysret`：**硬件强制将 CS 设为 `(MSR_STAR[63:48] + 16) | 3`**（计算得 `0x0033`），**CPL 变为 3**

**示例验证**：
- 用户进程（CPL=3）尝试加载 `__KERNEL_DS`（`0x0018`，RPL=0，DPL=0）：  
  **`max(3, 0) = 3 > 0`** → **#GP**（无法访问内核段）
- 内核代码（CPL=0）访问 `__USER_DS`（`0x002B`，RPL=3，DPL=3）：  
  **`max(0, 3) = 3 ≤ 3`** → **允许**（内核可读写用户空间，配合页表 `U/S` 位）

---

## 7. 文档版本

**最后更新**：以仓库中 Git 提交日期为准；**对齐内核树**：`/Users/weli/works/linux`（若路径不同，请替换为你的检出根）。**参考 SDM**：`/Users/weli/Desktop/pdfs/64-ia-32-architectures-software-developer-vol-3a-part-1-manual.pdf` §3.4「Segment Descriptors」、§3.4.3「Segment Registers」、§5.5「Privilege Levels」。
