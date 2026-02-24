# x86 GDT 表结构说明（结合 SDM 与 Linux 内核代码）

本文档专门说明 **GDT（Global Descriptor Table，全局描述符表）** 的表结构：包括 SDM 中的定义、段描述符的 8 字节格式与系统描述符、GDTR、以及 Linux 内核中的对应数据结构和布局。

**参考文档**：
- **Intel® 64 and IA-32 Architectures Software Developer's Manual, Volume 3A: System Programming Guide, Part 1**（以下简称 SDM Vol 3A）。本地路径：`/Users/weli/Desktop/pdfs/64-ia-32-architectures-software-developer-vol-3a-part-1-manual.pdf`。精确表述与位图以该 PDF 为准。
- 本文中“SDM”均指该手册；具体章节在以下各节标明。

**内核代码路径**（以 Linux 源码树为基准，校对时使用例如 `~/works/linux`）：
- `arch/x86/include/asm/segment.h` — GDT 条目索引与选择子（GDT_ENTRY_*、GDT_ENTRIES、__KERNEL_CS 等）
- `arch/x86/include/asm/desc_defs.h` — 段描述符结构体（`struct desc_struct`）、类型/标志宏（DESC_*）、`struct desc_ptr`、`GDT_ENTRY_INIT`
- `arch/x86/include/asm/desc.h` — `struct gdt_page`、`native_load_gdt` / `native_store_gdt`、per-CPU GDT 操作
- `arch/x86/kernel/cpu/common.c` — per-CPU GDT 静态初始化（`DEFINE_PER_CPU_PAGE_ALIGNED(struct gdt_page, gdt_page)`）

**校对说明**：本文档已对照上述内核源码与 SDM Vol 3A 进行校对；结构体字段、宏定义及 64/32 位 GDT 布局与源码一致，SDM 章节对应见第 6 节。

---

## 1. SDM 中的 GDT 与 GDTR

### 1.1 GDTR（GDT 表寄存器）

- **SDM 位置**：Vol 3A, **Section 2.4.1, “Global Descriptor Table Register (GDTR)”**。
- **作用**：存放当前 GDT 的线性基址和界限（limit）。只有一条 GDT，由 `LGDT` 加载、`SGDT` 存储。
- **格式**：
  - **Limit**（16 位）：表字节长度 − 1（即最大有效偏移）。
  - **Base**（32 位 in 32-bit; 64 位 in 64-bit）：GDT 的线性基址。
- **内核对应**：`struct desc_ptr`（`arch/x86/include/asm/desc_defs.h`）与 `native_store_gdt()` / `native_load_gdt()` 使用的就是“limit + address”形式，对应 GDTR 的 size 与 base。

### 1.2 GDT 表本身

- **SDM 位置**：Vol 3A, **Section 3.5.1, “Segment Descriptor Tables”**。
- **要点**：
  - GDT 是线性地址空间中的一张表，每个**描述符**占 **8 字节**；在 64 位下，TSS/LDT 等**系统描述符**占 **16 字节**（两个 8 字节槽位）。
  - **第 0 个条目**必须为“空描述符”（全 0），不可被加载为段选择子。
  - 段选择子中 **Index × 8** 为描述符在 GDT 中的字节偏移；TI=0 表示使用 GDT。

---

## 2. 段描述符格式（SDM 与内核对应）

### 2.1 SDM 中的 8 字节段描述符

- **SDM 位置**：Vol 3A, **Section 3.4.5, “Segment Descriptors”**（以及 3.4.5.1 等子节）。

**32 位保护模式下的 8 字节布局**（代码/数据段）：

```
 63        56 55  52 51   48 47          40 39   32
 ┌──────────┬─────┬───────┬──────────────┬───────┐
 │ Base     │Flags│ Limit │  Access Byte  │ Base  │
 │ [31:24]  │ (4) │[19:16]│    (8 bits)  │[23:16]│
 └──────────┴─────┴───────┴──────────────┴───────┘
 31                      16 15                   0
 ┌─────────────────────────┬─────────────────────┐
 │      Base [15:0]        │    Limit [15:0]     │
 └─────────────────────────┴─────────────────────┘
```

- **Access Byte (8 bits)**：  
  - **P (Present)**：存在位。  
  - **DPL**：描述符特权级。  
  - **S (Descriptor Type)**：0 = 系统描述符（TSS/LDT/门），1 = 代码/数据段。  
  - **Type (4 bits)**：段类型（可执行、可读、可写、已访问等），见 SDM 表。
- **Flags (4 bits)**：  
  - **G (Granularity)**：Limit 粒度（0=字节，1=4KB）。  
  - **DB**：默认操作大小/栈指针（32 位/16 位）。  
  - **L (Long)**：长模式代码段（64 位）。  
  - **AVL**：软件可用。

长模式下，**代码段与数据段**的 Base/Limit 被忽略（除 FS/GS 外），仅 Access Byte 与部分 Flags 有效；**TSS/LDT 描述符**在 64 位下扩展为 16 字节（高 8 字节含 Base[63:32] 等），见 SDM 3.4.5。

### 2.2 内核中的 8 字节描述符结构体

**arch/x86/include/asm/desc_defs.h**：

```c
/* 8 byte segment descriptor */
struct desc_struct {
	u16	limit0;
	u16	base0;
	u16	base1: 8, type: 4, s: 1, dpl: 2, p: 1;
	u16	limit1: 4, avl: 1, l: 1, d: 1, g: 1, base2: 8;
} __attribute__((packed));
```

与 SDM 对应关系（按位）：
- `limit0`、`limit1` → Limit [15:0]、[19:16]
- `base0`、`base1`、`base2` → Base [15:0]、[23:16]、[31:24]
- `type`、`s`、`dpl`、`p` → Access Byte（Type、S、DPL、P）
- `limit1` 的高 4 位 + `avl`、`l`、`d`、`g` → Flags（G、DB、L、AVL）

### 2.3 内核中的描述符类型与宏

**arch/x86/include/asm/desc_defs.h** 中与 GDT 段类型相关的定义（节选）：

| 宏 | 含义 | 对应 SDM |
|----|------|----------|
| `_DESC_PRESENT` | P=1 | Present |
| `_DESC_DPL(dpl)` | DPL 域 | Descriptor Privilege Level |
| `_DESC_S` | S=1，代码/数据段 | Descriptor Type |
| `_DESC_GRANULARITY_4K` | G=1 | Limit 以 4KB 为单位 |
| `_DESC_DB` | DB=1 | 32 位默认/栈 |
| `_DESC_LONG_CODE` | L=1 | 64 位代码段 |
| `DESC_CODE32` / `DESC_DATA32` | 32 位代码/数据 | Type 编码 |
| `DESC_CODE64` / `DESC_DATA64` | 64 位代码/数据 | Type + L |
| `DESC_USER` | DPL=3 | 用户态段 |
| `DESC_TSS` / `DESC_LDT` | 系统描述符类型 | System type 9 / 2 |

**GDT_ENTRY_INIT(flags, base, limit)** 用 `(flags, base, limit)` 填满一个 `struct desc_struct`，与 SDM 的 Base/Limit/Access/Flags 布局一致。

### 2.4 汇编中的 GDT 条目构造

**arch/x86/include/asm/segment.h**：

```c
#define GDT_ENTRY(flags, base, limit)			\
	((((base)  & _AC(0xff000000,ULL)) << (56-24)) |	\
	 (((flags) & _AC(0x0000f0ff,ULL)) << 40) |	\
	 (((limit) & _AC(0x000f0000,ULL)) << (48-16)) |	\
	 (((base)  & _AC(0x00ffffff,ULL)) << 16) |	\
	 (((limit) & _AC(0x0000ffff,ULL))))
```

生成的是 64 位立即数形式的 8 字节描述符，与 SDM 中“高半部分 Base/Limit/Flags、低半部分 Base/Limit”的布局一致，用于引导与汇编中直接写 GDT 表项。

---

## 3. 系统描述符（TSS / LDT）在 64 位下占两格

**GDT 里存的是什么？**  
- 保存在 GDT 里的是 **TSS 描述符** 和 **LDT 描述符**（即“指向 TSS/LDT 的指针”：基址、界限、类型等），**不是** TSS 或 LDT 的完整内容。  
- **TSS 本体**（任务状态段：寄存器镜像、I/O 位图等）和 **LDT 本体**（局部描述符表，另一张表）在各自的内存区域；CPU 通过 GDT 中的描述符找到它们（TR 选择子 → GDT 中的 TSS 描述符 → TSS 基址；LDTR 选择子 → GDT 中的 LDT 描述符 → LDT 表基址）。  
- **访问 LDT 或 TSS 时，都必须先访问 GDT**：TR/LDTR 中存的是段选择子，该选择子索引的是 GDT（TI=0）；CPU 先用选择子从 GDT 取出 TSS/LDT 描述符，得到基址与界限后，才能访问 TSS 段或 LDT 表。

- **SDM**：64 位 TSS 与 LDT **描述符**为 **16 字节**（高 8 字节含 Base[63:32] 等），故在 GDT 中占**两个连续 8 字节槽位**。
- **内核**：`struct ldttss_desc`（`arch/x86/include/asm/desc_defs.h`）在 `CONFIG_X86_64` 下包含 `base3`、`zero1`，总大小为 16 字节；TSS/LDT **描述符**在 GDT 中的索引约定为“占用两个条目”（如 8–9、10–11）。

---

## 4. Linux 内核 GDT 表项数量与布局

GDT **不是**固定 7 项。表项数量由 `GDT_ENTRIES` 决定，**64 位为 16，32 位为 32**。

**arch/x86/include/asm/desc.h**：

```c
struct gdt_page {
	struct desc_struct gdt[GDT_ENTRIES];
} __attribute__((aligned(PAGE_SIZE)));
```

### 4.1 x86_64（长模式）GDT 布局

**arch/x86/include/asm/segment.h**（`#else` 分支，64-bit）：

| 索引 | 宏名 | 说明 |
|------|------|------|
| 0 | — | 空描述符（未使用宏，必须为 0） |
| 1 | GDT_ENTRY_KERNEL32_CS | 32 位内核代码（兼容） |
| 2 | GDT_ENTRY_KERNEL_CS | 64 位内核代码 |
| 3 | GDT_ENTRY_KERNEL_DS | 64 位内核数据 |
| 4 | GDT_ENTRY_DEFAULT_USER32_CS | 32 位用户代码 |
| 5 | GDT_ENTRY_DEFAULT_USER_DS | 64 位用户数据 |
| 6 | GDT_ENTRY_DEFAULT_USER_CS | 64 位用户代码 |
| 8–9 | GDT_ENTRY_TSS | TSS 描述符（占 2 条；TSS 本体在别处） |
| 10–11 | GDT_ENTRY_LDT | LDT 描述符（占 2 条；LDT 表在别处） |
| 12–14 | GDT_ENTRY_TLS_MIN … MAX | TLS（3 条） |
| 15 | GDT_ENTRY_CPUNODE | Per-CPU / VDSO 用 |

`GDT_ENTRIES == 16`。SYSCALL/SYSRET 依赖的是 **0–6 的布局**（尤其是 USER_DS、USER_CS 的相对位置），而不是“整张表只有 7 项”。

### 4.2 x86_32 GDT 布局

**arch/x86/include/asm/segment.h**（`#if defined(CONFIG_X86_32) && !defined(BUILD_VDSO32_64)` 分支）中注释的布局概要：

- 0：null  
- 1–3：保留  
- 4–5：未使用  
- 6–8：TLS（3 条）  
- 9–11：保留  
- 12：KERNEL_CS  
- 13：KERNEL_DS  
- 14：USER_CS  
- 15：USER_DS  
- 16：TSS 描述符  
- 17：LDT 描述符  
- 18–22：PNPBIOS  
- 23–25：APM BIOS  
- 26：ESPFIX_SS  
- 27：PERCPU  
- 28：CPUNODE（VDSO getcpu）  
- 29–30：未使用  
- 31：DOUBLEFAULT_TSS  

`GDT_ENTRIES == 32`。

---

## 5. 内核中的 GDT 初始化（gdt_page）

**arch/x86/kernel/cpu/common.c** 中 per-CPU GDT 的静态初始化：

```c
DEFINE_PER_CPU_PAGE_ALIGNED(struct gdt_page, gdt_page) = { .gdt = {
#ifdef CONFIG_X86_64
	[GDT_ENTRY_KERNEL32_CS]		= GDT_ENTRY_INIT(DESC_CODE32, 0, 0xfffff),
	[GDT_ENTRY_KERNEL_CS]		= GDT_ENTRY_INIT(DESC_CODE64, 0, 0xfffff),
	[GDT_ENTRY_KERNEL_DS]		= GDT_ENTRY_INIT(DESC_DATA64, 0, 0xfffff),
	[GDT_ENTRY_DEFAULT_USER32_CS]	= GDT_ENTRY_INIT(DESC_CODE32 | DESC_USER, 0, 0xfffff),
	[GDT_ENTRY_DEFAULT_USER_DS]	= GDT_ENTRY_INIT(DESC_DATA64 | DESC_USER, 0, 0xfffff),
	[GDT_ENTRY_DEFAULT_USER_CS]	= GDT_ENTRY_INIT(DESC_CODE64 | DESC_USER, 0, 0xfffff),
#else
	// 32-bit: KERNEL_CS/DS, USER_CS/DS, PNPBIOS, APMBIOS, ESPFIX_SS, PERCPU 等
	...
#endif
} };
```

- **Limit** 使用 `0xfffff` 且配合 `DESC_*` 中的 G 位，表示 4KB 粒度、满 4GB。  
- **Base** 为 0（长模式下代码/数据段基址被忽略；TSS/LDT 的 Base 在运行时由 `write_gdt_entry` / `set_tss_desc` 等写入）。  
- **DESC_USER** 即 DPL=3，用于用户态段。

TSS、LDT、TLS、PERCPU、CPUNODE 等条目在启动或进程切换时由 `arch/x86/kernel/cpu/common.c` 和 `arch/x86/include/asm/desc.h` 中的接口写入，而不是全部在静态初始化中填满。

### 5.1 GDT、TSS、LDT 是 per-CPU 还是 per-task？

| 对象 | 归属 | 内核依据 |
|------|------|----------|
| **GDT** | **per-CPU** | `DEFINE_PER_CPU_PAGE_ALIGNED(struct gdt_page, gdt_page)`（`arch/x86/kernel/cpu/common.c`）；`get_cpu_gdt_rw(cpu)` 返回该 CPU 的 GDT。每个 CPU 一张独立的 GDT。 |
| **TSS** | **per-CPU** | `DEFINE_PER_CPU_PAGE_ALIGNED(struct tss_struct, cpu_tss_rw)`（`arch/x86/kernel/process.c`）。每个 CPU 一个 TSS，用于该 CPU 上的内核栈指针（如 `sp0`）、IST、I/O 位图等；GDT 中的 TSS 描述符指向本 CPU 的 TSS。 |
| **LDT** | **per-task（per 地址空间）** | LDT 挂在 `mm_struct->context.ldt`（`struct ldt_struct`，见 `arch/x86/include/asm/mmu_context.h`）。每个进程可有自己的 LDT（如 Wine）；切换进程时通过 `load_mm_ldt()` 等更新**当前 CPU 的 GDT** 中 LDT 描述符槽位，使其指向当前进程的 LDT。故 LDT **内容**是 per-task，**GDT 中的 LDT 描述符槽位**在每 CPU 的 GDT 里只有一份，其指向随当前运行任务变化。 |

因此：**GDT 和 TSS 是 per-CPU 的；LDT 是 per-task 的**（每个 CPU 的 GDT 里只有一个 LDT 描述符，该描述符指向当前在该 CPU 上运行的任务的 LDT）。

### 5.2 IDT 与 GDT 是否独立？Long mode 下 LDT 还用吗？

**1. IDT 和 GDT 是互相独立的。**

- **寄存器**：IDT 用 **IDTR**，GDT 用 **GDTR**，两者各自保存各自表的基址与界限。
- **加载指令**：`LIDT` / `SIDT` 与 `LGDT` / `SGDT` 分开；内核里分别用 `native_load_idt()` / `native_load_gdt()`（`arch/x86/include/asm/desc.h`），底层对应不同的 `struct desc_ptr`（如 KVM 里 GUEST_GDTR_* 与 GUEST_IDTR_* 也是分开的）。
- **用途**：GDT 存段描述符（代码/数据/TSS/LDT 等）；IDT 存门描述符（中断/陷阱/任务门）。二者在内存中是两张独立的表，互不包含。

**2. Long mode（64 位）下 LDT 已经很少用。**

- **SDM**：IA-32e 模式下 LDT 仍被支持（LDTR、TI=1 的选择子仍有效），但在 64 位模式下**段描述符的 Base 和 Limit 基本被忽略**，段式寻址退化为“扁平”线性空间。LDT 的传统用途（每任务不同段基址/界限）在 64 位下几乎失去意义。
- **内核**：
  - LDT 支持由 **CONFIG_MODIFY_LDT_SYSCALL** 控制（`arch/x86/Kconfig`），默认 `y`，但在 **EXPERT** 下可关掉；Kconfig 说明用于“16-bit or segmented code such as DOSEMU or some Wine programs”以及“very old threading libraries”，并建议嵌入式/服务器内核可设为 `N` 以减小攻击面。
  - `arch/x86/kernel/ldt.c` 中注释写明：*“modify_ldt() is mostly used by **legacy code and emulators**”*（`switch_ldt()` 附近）。
- **结论**：长模式下 LDT 机制仍存在，但日常 64 位程序几乎不用；只有依赖 `modify_ldt(2)` 的旧代码或模拟器（如 Wine、DOSEMU）会用到，且该功能可整块关闭。

### 5.3 Long mode 下 GDT 的功能是否被弱化？

**是的，在 long mode 下 GDT 的“分段寻址”功能被明显弱化，但 GDT 仍然必需，只是角色从“地址转换+保护”变为“权限与类型 + 系统结构”。**

- **被弱化的部分**（SDM：64 位模式下对 CS/DS/SS/ES）：
  - **段基址 Base** 被强制为 0，GDT 不再参与“逻辑地址 → 线性地址”的段式转换；有效地址就是线性地址（再由分页转换）。
  - **段界限 Limit** 被忽略，不再做基于段的边界检查。
  - 因此，GDT 在 32 位保护模式下的核心作用——**用不同段的 Base/Limit 做内存隔离与转换**——在 long mode 下基本消失。

- **仍然保留、且不可省的部分**：
  - **特权与类型**：描述符中的 **DPL** 仍用于权限检查（CPL/RPL 与 DPL 的比较）；**Type**（代码/数据、可执行/可写等）仍被 CPU 检查。内核/用户、代码/数据的区分仍依赖 GDT。这些 **DPL 是固定值**：在建立 GDT 时由软件写入（内核段 DPL=0、用户段 DPL=3，如 `DESC_USER` = `_DESC_DPL(3)`），之后**不会随运行更新**；CPU 不修改描述符，只有软件在写 GDT 表项时才会改（内核仅在初始化/写 TSS 等时写一次，不动态改代码/数据段的 DPL）。
  - **SYSCALL/SYSRET**：依赖固定的 GDT 布局（KERNEL_CS/DS、USER_CS/DS 的位置），不能没有 GDT。
  - **TSS 描述符**：必须放在 GDT 中，用于特权级切换时的内核栈（如 `sp0`）、IST、I/O 位图等。
  - **LDT 描述符**：槽位仍在，供少数需要 LDT 的进程使用。

**小结**：Long mode 下 GDT 的“分段寻址”能力被弱化，但**权限与类型检查**以及**承载 TSS/LDT 描述符**的作用仍在，所以 GDT 表不能取消，只是从“强分段”退化为“扁平段 + 权限与系统结构”。

---

## 6. 与 SDM 的章节对应小结

| 内容 | SDM Vol 3A 章节 |
|------|-------------------------------|
| GDTR 格式与 LGDT/SGDT | Section 2.4.1 |
| 段描述符 8 字节格式 | Section 3.4.5 |
| 代码/数据段 Type 与 Access Byte | Section 3.4.5.1 |
| GDT/LDT 表组织 | Section 3.5.1 |
| 64 位 TSS/LDT 描述符（16 字节） | Section 3.4.5（系统描述符） |

本文档中的位图与字段解释与上述章节一致；实现细节以 **arch/x86** 下 `segment.h`、`desc_defs.h`、`desc.h`、`cpu/common.c` 为准。SDM 的精确措辞与图表请以本地 PDF（见文首路径）为准；若 PDF 版本不同，章节号可能略有差异。

---

## 7. 相关文档

- **[X86_MEMORY_MANAGEMENT_THEORY.md](X86_MEMORY_MANAGEMENT_THEORY.md)** — 分段与 GDT 在地址转换、SYSCALL/SYSRET 中的作用。  
- **[LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md)** — 启动过程中 GDT 的加载与切换（early_gdt_descr、gdt_page、per-CPU GDT）。
