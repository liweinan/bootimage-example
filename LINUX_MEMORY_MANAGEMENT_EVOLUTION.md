# Linux 内存管理演化：从 BIOS 到内核的完整过渡

## 文档导航

本文档是 Linux x86-64 内存管理三部曲之一：

1. **[X86_MEMORY_MANAGEMENT_THEORY.md](X86_MEMORY_MANAGEMENT_THEORY.md)** - 理论篇
   - GDT 结构与段描述符位字段详解
   - 分页硬件机制（4级页表、TLB、MMU）
   - x86-64 长模式的硬件要求

2. **LINUX_MEMORY_MANAGEMENT_EVOLUTION.md** - 演化篇（本文档）
   - 启动过程中的内存管理演化时间线
   - 为什么需要多套 GDT 和页表
   - 关键演化时刻与决策原因

3. **[LINUX_MEMORY_MANAGEMENT_CODE_GUIDE.md](LINUX_MEMORY_MANAGEMENT_CODE_GUIDE.md)** - 实现篇
   - gdt_page 结构体源代码详解
   - 页表构建函数实现细节
   - 汇编代码逐行分析

---

## 演化概览：四个阶段

Linux x86-64 内核启动过程经历四个内存管理阶段，每个阶段都有不同的 CPU 模式、GDT 和页表配置：

```
┌──────────┬─────────────┬─────────────┬──────────────┬─────────────────┐
│  阶段    │  CPU 模式   │    GDT      │    页表      │    地址映射     │
├──────────┼─────────────┼─────────────┼──────────────┼─────────────────┤
│ ① BIOS   │ 实模式      │ 无          │ 无           │ 1MB 直接寻址    │
│ ② GRUB   │ 保护模式    │ GRUB GDT    │ 无(CR0.PG=0) │ 扁平模式        │
│ ③ 压缩   │ 长模式      │ boot_gdt    │ pgtable      │ Identity(VA=PA) │
│ ④ 主内核 │ 长模式      │ gdt_page    │ swapper_pg   │ Direct(VA=PA+⊿)│
└──────────┴─────────────┴─────────────┴──────────────┴─────────────────┘
```

**关键演化节点**：
- **BIOS → GRUB**：进入保护模式，启用第一套 GDT
- **GRUB → 压缩内核**：首次建立页表，进入长模式
- **压缩内核 → 主内核**：切换到完整 GDT 和高地址映射

本文档按时间线详细讲解每个阶段的演化过程。

---

## 阶段 ①：BIOS 阶段

### BIOS 内存布局

BIOS 启动时，CPU 处于 **实模式**（Real Mode）：
- **地址空间**：16位寻址，最大 1MB（0x00000 - 0xFFFFF）
- **段寄存器**：CS, DS, ES, SS 通过段基址 × 16 + 偏移计算物理地址
- **无 GDT**：实模式不需要全局描述符表
- **无分页**：物理地址直接访问

**关键内存区域**：
```
0x00000 - 0x003FF : 中断向量表（IVT）
0x00400 - 0x004FF : BIOS 数据区
0x00500 - 0x07BFF : 可用内存
0x07C00 - 0x07DFF : MBR 加载区（BIOS 加载引导扇区到这里）
0x80000 - 0x9FFFF : 扩展 BIOS 数据区
0xA0000 - 0xFFFFF : 视频内存和 ROM 区域
```

### E820 内存映射

BIOS 通过 **INT 15h, AX=E820h** 提供物理内存映射表，描述所有内存区域的类型和范围：

**E820 内存类型**：
- **Type 1**: 可用 RAM（Available）
- **Type 2**: 保留区域（Reserved）
- **Type 3**: ACPI 可回收（ACPI Reclaimable）
- **Type 4**: ACPI NVS（ACPI Non-Volatile Storage）
- **Type 5**: 坏内存（Bad Memory）

GRUB 会读取 E820 表并传递给 Linux 内核（通过 boot_params 结构）。

**演化意义**：E820 表是后续阶段内存管理的基础，内核依赖它来初始化物理内存管理器。

---

## 阶段 ②：GRUB 阶段

GRUB 的任务是加载内核并将 CPU 从实模式切换到保护模式或长模式。这个阶段开始使用 **GDT**，但仍然 **不使用分页**。

### 2.1 GRUB 的 GDT 设置

#### 为什么需要 GDT

从实模式进入保护模式或长模式，必须：
1. 创建 GDT（定义代码段和数据段）
2. 加载 GDTR 寄存器（指向 GDT 基址）
3. 设置段寄存器（CS, DS, ES, SS）指向 GDT 中的段描述符
4. 设置 CR0.PE = 1（保护模式）或继续设置长模式

#### GRUB 的两套 GDT

GRUB 根据目标内核类型准备不同的 GDT：

**1. 32位内核 GDT**（relocator32.S）：
```assembly
# grub-core/lib/i386/relocator32.S
LOCAL(gdt):
    .word   0, 0                      # NULL 段
    .byte   0, 0, 0, 0

    .word   0xffff, 0                 # 代码段（0-4GB）
    .byte   0, 0x9a, 0xcf, 0

    .word   0xffff, 0                 # 数据段（0-4GB）
    .byte   0, 0x92, 0xcf, 0
```

**2. 64位内核 GDT**（relocator64.S）：
```assembly
# grub-core/lib/x86_64/relocator64.S
LOCAL(gdt):
    .word   0, 0, 0, 0                # NULL 段

    .word   0, 0, 0, 0x9a00, 0        # 64位代码段（L=1）

    .word   0, 0, 0, 0x9200, 0        # 数据段
```

#### 关键特征

- **扁平模式**（Flat Mode）：代码段和数据段都覆盖整个 4GB 地址空间（32位）或整个地址空间（64位）
- **临时使用**：GRUB GDT 只在 GRUB 运行期间有效
- **位置**：GDT 位于 GRUB 自己的内存区域，内核启动后会被覆盖

#### 什么时候使用

- **Legacy BIOS + 32位内核**：`relocator32_boot()` 使用 32位 GDT
- **Legacy BIOS + 64位内核**：`relocator64_boot()` 使用 64位 GDT
- **UEFI 模式**：UEFI 固件已经在长模式，GRUB 直接使用 UEFI 提供的 GDT

> **详细的段描述符位字段解释请参考 [理论篇](X86_MEMORY_MANAGEMENT_THEORY.md)**

### 2.2 GRUB 的分页状态

#### GRUB 无页表

**Legacy BIOS 模式**：
- GRUB 运行在 **保护模式**（32位内核）或 **长模式**（64位内核）
- **CR0.PG = 0**：分页未启用
- 使用 **扁平模式**：线性地址 = 物理地址
- 内核被加载到物理内存的某个位置（通常 1MB 以上）

**UEFI 模式**：
- UEFI 固件已经在长模式，分页已启用
- GRUB 使用 **UEFI 固件提供的页表**
- GRUB 不自己建立或管理页表

#### Linux 内核启动时的初始状态

当 GRUB 跳转到 Linux 内核时（Legacy BIOS 模式）：
- **CPU 模式**：32位保护模式
- **CR0.PG = 0**：分页关闭
- **CS, DS**：指向 GRUB GDT 中的段
- **内核镜像**：已加载到物理内存

**演化意义**：内核必须在压缩内核阶段建立自己的页表，才能进入长模式。

---

## 阶段 ③：压缩内核阶段（关键演化）

压缩内核（arch/x86/boot/compressed/）是内核启动过程中的 **关键过渡阶段**，在这里发生两个重大演化：
1. **首次建立页表**（pgtable）
2. **首次进入长模式**

### 3.1 压缩内核的 GDT（boot_gdt）

#### 为什么要换 GDT

GRUB 的 GDT 有两个问题：
1. **位置不安全**：GRUB GDT 位于 GRUB 内存区域，内核解压时可能被覆盖
2. **生命周期不匹配**：GRUB 运行结束后，GRUB GDT 不再可靠

因此，压缩内核必须建立 **自己的 GDT**（boot_gdt）。

#### boot_gdt 的内容

boot_gdt 定义在 `arch/x86/boot/compressed/head_64.S`：

```assembly
# 简化版本（实际定义更复杂）
    .data
boot_gdt:
    .quad   0x0000000000000000        # NULL 段
    .quad   0x00af9a000000ffff        # 64位代码段（__KERNEL_CS）
    .quad   0x00cf92000000ffff        # 数据段（__KERNEL_DS）
    .quad   0x00cf9a000000ffff        # 32位兼容代码段
```

**四个段描述符**：
1. **NULL 段**：必须存在，未使用
2. **64位代码段**：L=1（长模式），用于 startup_64
3. **数据段**：DS, ES, SS 使用
4. **32位兼容代码段**：startup_32 使用

#### boot_gdt 的生命周期

- **加载时机**：startup_32 早期加载（`lgdt boot_gdt`）
- **使用期间**：startup_32 → startup_64 → 解压内核 → 跳转到主内核早期
- **废弃时机**：主内核设置 gdt_page 后，boot_gdt 所在内存被释放

> **详细的 struct desc_struct 定义和 GDT_ENTRY_INIT 宏请参考 [实现篇](LINUX_MEMORY_MANAGEMENT_CODE_GUIDE.md)**

### 3.2 压缩内核的页表建立（首次建立）

#### 关键时刻

**这是 Linux 内核启动过程中第一次建立页表**。之前的 BIOS 和 GRUB 阶段都没有使用分页（Legacy BIOS 模式）。

#### 为什么需要页表

x86-64 长模式的 **硬件要求**：
- 进入长模式（IA-32e mode）之前，**必须**启用分页（CR0.PG = 1）
- 必须启用 PAE（CR4.PAE = 1）
- 必须设置 EFER.LME = 1

**顺序要求**：
```
1. 建立页表
2. CR4.PAE = 1
3. CR3 = 页表基址
4. EFER.LME = 1
5. CR0.PG = 1  ← 此时进入长模式
```

#### Identity Mapping 原理

压缩内核使用 **Identity Mapping**（恒等映射）：
```
Virtual Address (VA) = Physical Address (PA)
```

**为什么用 Identity Mapping**：
1. **简化过渡**：CPU 正在执行的指令地址不变，避免地址突变
2. **EIP 连续性**：启用分页后，下一条指令的地址仍然有效
3. **临时使用**：只在压缩内核阶段使用，主内核会切换到 Direct Mapping

**示例**：
```
物理地址 0x01000000 映射到 虚拟地址 0x01000000
物理地址 0x02000000 映射到 虚拟地址 0x02000000
```

#### 页表结构概述

**4级页表层次**（x86-64）：
```
CR3 → PML4 (Page Map Level 4)
        ↓
      PDPT (Page Directory Pointer Table)
        ↓
      PD (Page Directory)
        ↓
      [使用 2MB 大页，不需要 PT]
```

**关键特征**：
- **2MB 大页**：设置 PD 表项的 PS 位（Page Size = 1），直接映射 2MB 物理页
- **覆盖范围**：映射足够的内存以覆盖内核镜像和解压目标区域（通常 0-4GB）
- **临时结构**：pgtable 位于压缩内核的 .pgtable 段，后续会被释放

**页表布局**：
```
pgtable:
  ├── level4_kernel_pgt (PML4)  : 512个表项
  ├── level3_kernel_pgt (PDPT)  : 512个表项
  └── level2_kernel_pgt (PD)    : 512个表项（每个映射2MB）
```

> **详细的页表构建汇编代码和 PTE 位字段请参考：**
> - **[实现篇](LINUX_MEMORY_MANAGEMENT_CODE_GUIDE.md)**：initialize_identity_maps() 实现
> - **[理论篇](X86_MEMORY_MANAGEMENT_THEORY.md)**：页表硬件结构
> - **[X86_IDENTITY_MAPPING.md](X86_IDENTITY_MAPPING.md)**：Identity Mapping 详细分析

### 3.3 长模式和分页的激活顺序

#### 完整时间线

压缩内核从 32位保护模式进入 64位长模式的完整步骤：

```
┌─────────────────────────────────────────────────────────────┐
│ startup_32 (32位保护模式，CR0.PG=0)                         │
└─────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│ 1. 加载 boot_gdt (lgdt boot_gdt)                            │
└─────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. 建立 pgtable (initialize_identity_maps)                  │
│    - 分配 PML4, PDPT, PD                                    │
│    - 设置 Identity Mapping (VA = PA)                        │
│    - 使用 2MB 大页                                          │
└─────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. 启用 PAE (CR4.PAE = 1)                                   │
└─────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│ 4. 加载页表基址 (CR3 = pgtable)                             │
└─────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│ 5. 启用长模式 (EFER.LME = 1)                                │
└─────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│ 6. 启用分页 (CR0.PG = 1)                                    │
│    ← 此刻进入长模式！                                       │
└─────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│ 7. lret 跳转到 startup_64 (64位长模式)                      │
└─────────────────────────────────────────────────────────────┘
```

#### 关键时间点总结

| 步骤 | CPU 状态 | 关键寄存器 | 说明 |
|------|---------|-----------|------|
| 步骤1 | 32位保护模式 | GDTR = boot_gdt | 切换到内核自己的 GDT |
| 步骤2 | 32位保护模式 | - | 页表已存在但未激活 |
| 步骤3-4 | 32位保护模式 | CR4.PAE=1, CR3=pgtable | PAE 已启用，页表已加载 |
| 步骤5 | 32位保护模式 | EFER.LME=1 | 长模式已启用但未激活 |
| 步骤6 | **长模式** | CR0.PG=1 | **分页启用，长模式激活** |
| 步骤7 | 64位长模式 | RIP, CS | 开始执行 64位代码 |

> **详细的汇编代码分析请参考 [实现篇](LINUX_MEMORY_MANAGEMENT_CODE_GUIDE.md) 中的 startup_32/startup_64 章节**

### 3.4 重定位与解压过程（简要）

#### 压缩内核重定位

- **为什么重定位**：内核被加载的位置可能不是最终运行位置
- **重定位目标**：将压缩内核移动到安全位置（避免解压时覆盖自己）
- **代码实现**：startup_64 中的 memcpy 循环

#### 解压主内核

- **解压器**：使用内置的解压缩算法（gzip/bzip2/lzma/xz/lz4/zstd）
- **目标位置**：解压到内核最终运行位置（通常是 `CONFIG_PHYSICAL_START`）
- **函数调用**：`extract_kernel()` 执行解压

#### 跳转到主内核

解压完成后：
```c
// arch/x86/boot/compressed/head_64.S
jmp *%rax  // 跳转到解压后的主内核入口（startup_64）
```

**演化意义**：此时进入主内核阶段，boot_gdt 和 pgtable 即将被废弃。

---

## 阶段 ④：主内核阶段

主内核（解压后的 vmlinux）接管控制权后，需要建立 **完整的内存管理系统**。

### 4.1 主内核的 GDT（gdt_page）

#### 为什么再次换 GDT

压缩内核的 boot_gdt 有三个限制：
1. **段数量少**：只有 4 个段，不足以支持完整功能
2. **不支持 Per-CPU**：单一 GDT 无法支持多 CPU
3. **会被释放**：boot_gdt 所在内存（压缩内核段）会被释放回收

主内核需要 **gdt_page**：
- **Per-CPU 架构**：每个 CPU 有自己的 GDT
- **完整段表**：32 个段描述符（支持用户态、TSS、LDT 等）
- **永久使用**：运行期间一直有效

#### gdt_page 的关键特征

**1. Per-CPU 架构**

每个 CPU 有独立的 gdt_page：
```c
DEFINE_PER_CPU_PAGE_ALIGNED(struct gdt_page, gdt_page) = { .gdt = {
    // 32个段描述符
} };
```

**为什么需要 Per-CPU GDT**：
- **TSS（Task State Segment）**：每个 CPU 需要独立的 TSS 来保存寄存器状态
- **内核栈**：每个 CPU 的内核栈地址不同，TSS 中保存
- **并发安全**：多 CPU 并发运行时避免 GDT 竞争

**2. 支持用户态段**

gdt_page 包含用户态段描述符：
```c
[GDT_ENTRY_KERNEL_CS]     = GDT_ENTRY_INIT(0xa09a, 0, 0xfffff),  // 内核代码段
[GDT_ENTRY_KERNEL_DS]     = GDT_ENTRY_INIT(0xc092, 0, 0xfffff),  // 内核数据段
[GDT_ENTRY_DEFAULT_USER_CS] = GDT_ENTRY_INIT(0xa0fa, 0, 0xfffff),  // 用户代码段
[GDT_ENTRY_DEFAULT_USER_DS] = GDT_ENTRY_INIT(0xc0f2, 0, 0xfffff),  // 用户数据段
```

**为什么需要用户态段**：
- **系统调用**：用户态程序通过 SYSCALL 指令进入内核
- **上下文切换**：进程切换时需要加载用户态段寄存器
- **权限隔离**：用户态段 DPL=3，内核段 DPL=0

**3. SYSCALL/SYSRET 要求**

x86-64 的 SYSCALL/SYSRET 指令对 GDT 布局有 **硬性要求**：
```
SYSCALL:
  - 加载 MSR_STAR[47:32] 到 CS (内核代码段)
  - 加载 MSR_STAR[47:32] + 8 到 SS (内核数据段)

SYSRET:
  - 加载 MSR_STAR[63:48] + 16 到 CS (用户代码段)
  - 加载 MSR_STAR[63:48] + 8 到 SS (用户数据段)
```

因此 gdt_page 的段布局必须满足：
```
__KERNEL_CS   = 0x10  (段选择子)
__KERNEL_DS   = 0x18  (= __KERNEL_CS + 8)
__USER_DS     = 0x28  (= __USER_CS - 8)
__USER_CS     = 0x30
```

#### GDT 演化过程

主内核启动时的 GDT 演化：

**1. 早期 GDT（startup_64_setup_gdt_idt）**

入口：
```c
// arch/x86/kernel/head_64.S
SYM_CODE_START_NOALIGN(startup_64)
    call startup_64_setup_gdt_idt  // 设置早期 GDT
```

加载 **early_gdt_descr**：
```assembly
early_gdt_descr:
    .word   GDT_ENTRIES*8-1
    .quad   INIT_PER_CPU_VAR(gdt_page)
```

**特点**：
- 使用 gdt_page 结构，但此时还是单一的（BSP 的 gdt_page）
- 所有 CPU 共享同一个 GDT（Per-CPU 机制尚未建立）

> **关键技术细节**：`startup_64_setup_gdt_idt()` 函数使用 **RIP 相对寻址**（`rip_rel_ptr(&gdt_page)`）来计算 gdt_page 的地址，而不是直接使用 `early_gdt_descr` 的链接时地址。这是因为在 startup_64 早期，代码可能还在低地址运行，链接时地址（高地址）还未映射。详细的地址计算方式对比请参考 **[实现篇 1.3.5节](LINUX_MEMORY_MANAGEMENT_CODE_GUIDE.md#135-关键对比early_gdt_descr-vs-startup_64_setup_gdt_idt)**。

**2. Per-CPU GDT（setup_per_cpu_areas）**

时机：
```c
// init/main.c
start_kernel()
    → setup_per_cpu_areas()  // 建立 Per-CPU 区域
    → trap_init()
        → cpu_init()  // 每个 CPU 加载自己的 GDT
```

每个 CPU 加载自己的 gdt_page：
```c
void cpu_init(void) {
    load_direct_gdt(cpu);  // 加载当前 CPU 的 gdt_page
    load_percpu_segment(cpu);
}
```

**特点**：
- 每个 CPU 有独立的 gdt_page 副本
- GDTR 指向当前 CPU 的 gdt_page
- 真正的 Per-CPU GDT 建立完成

> **详细的 gdt_page 结构定义和初始化代码请参考 [实现篇](LINUX_MEMORY_MANAGEMENT_CODE_GUIDE.md)**

### 4.2 主内核的页表

#### 为什么换页表

压缩内核的 Identity Mapping（VA = PA）有两个问题：
1. **地址冲突**：内核和用户空间都使用低地址（0-4GB），会冲突
2. **扩展性差**：无法映射超过 4GB 的物理内存

主内核使用 **Direct Mapping**（直接映射）：
```
VA = PA + PAGE_OFFSET
```

其中 `PAGE_OFFSET = 0xffff888000000000`（x86-64）。

**好处**：
- **地址隔离**：内核使用高地址（0xffff8880...），用户使用低地址（0x0000...）
- **全物理内存映射**：可以映射所有物理内存（TB 级别）
- **简化内核开发**：内核可以直接访问任意物理内存（PA = VA - PAGE_OFFSET）

#### early_top_pgt 的作用

主内核入口（startup_64）使用 **early_top_pgt**：
```assembly
// arch/x86/kernel/head_64.S
SYM_CODE_START_NOALIGN(startup_64)
    leaq _text(%rip), %rdi
    // 此时 CR3 仍指向压缩内核的 pgtable

    // 稍后切换到 early_top_pgt
    movq $(early_top_pgt - __START_KERNEL_map), %rax
    addq phys_base(%rip), %rax
    movq %rax, %cr3
```

**early_top_pgt 特点**：
- **静态定义**：编译时定义在内核镜像中
- **双映射**：同时支持 Identity Mapping 和 Direct Mapping
  - Identity：VA = PA（兼容启动代码）
  - Direct：VA = PA + PAGE_OFFSET（内核运行）
- **临时使用**：在 `init_mem_mapping()` 建立完整页表前使用

#### Direct Mapping 原理

**映射公式**：
```
Virtual Address = Physical Address + PAGE_OFFSET
```

**示例**（x86-64）：
```
Physical Address        Virtual Address
0x00000000             → 0xffff888000000000
0x00100000             → 0xffff888000100000
0x80000000             → 0xffff888080000000
```

**内核地址空间布局**（简化）：
```
0xffff888000000000 - 0xffffc87fffffffff : Direct mapping (64TB)
0xffffc90000000000 - 0xffffe8ffffffffff : vmalloc/ioremap (32TB)
0xffff888000000000 + phys_base          : 内核代码段（_text, _data）
```

#### 页表演化：pgtable → early_top_pgt → swapper_pg_dir

**完整演化路径**：

```
┌──────────────────────────────────────────────────────────┐
│ 1. pgtable (压缩内核)                                    │
│    - Identity Mapping (VA = PA)                          │
│    - 覆盖 0-4GB                                          │
│    - 2MB 大页                                            │
└──────────────────────────────────────────────────────────┘
                        ↓
        startup_64 切换 CR3
                        ↓
┌──────────────────────────────────────────────────────────┐
│ 2. early_top_pgt (主内核早期)                            │
│    - 双映射：Identity + Direct                           │
│    - 静态定义                                            │
│    - 支持早期启动代码                                    │
└──────────────────────────────────────────────────────────┘
                        ↓
        init_mem_mapping() 构建完整页表
                        ↓
┌──────────────────────────────────────────────────────────┐
│ 3. swapper_pg_dir (主内核运行期)                         │
│    - Direct Mapping (VA = PA + PAGE_OFFSET)              │
│    - 映射所有物理内存                                    │
│    - 动态构建                                            │
│    - 支持完整内存管理                                    │
└──────────────────────────────────────────────────────────┘
```

**关键函数调用链**：
```c
start_kernel()
  → setup_arch()
      → init_mem_mapping()  // 构建 Direct Mapping
          → kernel_physical_mapping_init()  // 填充页表
              → __kernel_physical_mapping_init()  // 实际构建
```

> **详细的 init_mem_mapping() 实现和页表构建代码请参考 [实现篇](LINUX_MEMORY_MANAGEMENT_CODE_GUIDE.md)**

---

## 总结：GDT 和页表演化对比

### GDT 演化全程

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  GRUB GDT   │ →   │  boot_gdt   │ →   │  gdt_page   │
│  (GRUB区)   │     │  (内核镜像) │     │  (Per-CPU)  │
└─────────────┘     └─────────────┘     └─────────────┘
  GRUB 运行期       压缩→主内核早期      主内核运行期
```

#### 三套 GDT 对比表

| 特性 | GRUB GDT | boot_gdt | gdt_page |
|------|---------|----------|----------|
| **段数量** | 4个（NULL + CS + DS + 32位CS） | 4个（NULL + 64位CS + DS + 32位CS） | 32个（内核/用户/TSS/LDT...） |
| **生命周期** | GRUB 运行期 | 压缩内核 → 主内核早期 | 主内核运行期（永久） |
| **位置** | GRUB 内存区 | 内核镜像 .data 段 | Per-CPU 区域 |
| **CPU 支持** | 单 CPU | 单 CPU（BSP） | Per-CPU（每个 CPU 独立） |
| **用户态支持** | 无 | 无 | 有（__USER_CS, __USER_DS） |
| **TSS 支持** | 无 | 无 | 有（每 CPU 一个 TSS） |
| **目的** | GRUB 启动内核 | 进入长模式 | 完整内核功能 |

#### 为什么需要三套 GDT

**1. GRUB GDT**：
- **必要性**：从实模式进入保护/长模式必须有 GDT
- **局限性**：位于 GRUB 内存，内核运行后不可靠

**2. boot_gdt**：
- **必要性**：GRUB GDT 会被覆盖，需要内核自己的 GDT
- **局限性**：段数量少，不支持 Per-CPU 和用户态

**3. gdt_page**：
- **必要性**：boot_gdt 被释放，需要永久 GDT
- **完整功能**：Per-CPU、用户态、TSS、系统调用

### 页表演化全程

```
┌─────────────┐     ┌──────────────────┐     ┌──────────────────┐
│   无分页    │ →   │ Identity Mapping │ →   │ Direct Mapping   │
│ (CR0.PG=0)  │     │   (VA = PA)      │     │ (VA = PA + ⊿)    │
└─────────────┘     └──────────────────┘     └──────────────────┘
  BIOS/GRUB        压缩内核(pgtable)        主内核(swapper_pg_dir)
```

#### 页表演化对比表

| 阶段 | 页表 | 映射方式 | 覆盖范围 | 页大小 | 目的 |
|------|------|---------|---------|--------|------|
| **BIOS/GRUB** | 无 | 扁平模式 | - | - | 简化启动 |
| **压缩内核** | pgtable | Identity (VA=PA) | 0-4GB | 2MB | 进入长模式 |
| **主内核早期** | early_top_pgt | Identity + Direct | 0-512MB | 2MB | 过渡页表 |
| **主内核运行** | swapper_pg_dir | Direct (VA=PA+⊿) | 所有物理内存 | 4KB/2MB | 完整内存管理 |

#### 为什么需要换页表

**1. 压缩内核建立 pgtable**：
- **硬件要求**：进入长模式必须启用分页（CR0.PG = 1）
- **Identity Mapping**：简化过渡，EIP 地址连续性

**2. 主内核切换到 Direct Mapping**：
- **地址隔离**：内核高地址，用户低地址，避免冲突
- **全内存映射**：支持 TB 级物理内存
- **简化开发**：内核可直接访问任意物理内存

### 四阶段综合对比

| 阶段 | CPU 模式 | GDT | 页表 | 地址映射 | 关键特征 |
|------|---------|-----|------|---------|---------|
| **① BIOS** | 实模式 | 无 | 无 | 1MB 直接寻址 | 段基址 × 16 + 偏移 |
| **② GRUB** | 保护模式 | GRUB GDT | 无(CR0.PG=0) | 扁平模式 | 线性地址 = 物理地址 |
| **③ 压缩内核** | 长模式 | boot_gdt | pgtable | Identity (VA=PA) | 首次启用分页 |
| **④ 主内核** | 长模式 | gdt_page | swapper_pg_dir | Direct (VA=PA+⊿) | 完整内存管理 |

**关键演化时刻**：
- **BIOS → GRUB**：启用 GDT，进入保护模式
- **GRUB → 压缩内核**：建立页表，启用分页，进入长模式
- **压缩内核 → 主内核**：切换到 Per-CPU GDT 和高地址映射

---

## 深入阅读

### 理论基础
- **[X86_MEMORY_MANAGEMENT_THEORY.md](X86_MEMORY_MANAGEMENT_THEORY.md)** - 理论篇
  - GDT 段描述符详细位字段（G, D/B, L, AVL, P, DPL, S, Type）
  - 分页硬件机制（4级页表结构、TLB、MMU 工作原理）
  - x86-64 长模式的硬件要求和限制

### 实现细节
- **[LINUX_MEMORY_MANAGEMENT_CODE_GUIDE.md](LINUX_MEMORY_MANAGEMENT_CODE_GUIDE.md)** - 实现篇
  - struct gdt_page 和 struct desc_struct 源代码定义
  - GDT_ENTRY_INIT 宏详细展开
  - startup_32/startup_64 汇编代码逐行分析
  - initialize_identity_maps() 页表构建详细实现
  - init_mem_mapping() 完整调用链

### 专题文档
- **[X86_IDENTITY_MAPPING.md](X86_IDENTITY_MAPPING.md)** - Identity Mapping 专题
  - 为什么需要 Identity Mapping
  - 页表构建详细步骤
  - 从 Identity 到 Direct 的切换过程

- **[LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md)** - 内核启动流程
  - start_kernel() 完整调用链
  - 内存管理初始化时间线
  - Per-CPU 机制建立过程

### GRUB 相关
- **[grub-boot-comparison.md](grub-boot-comparison.md)** - GRUB 启动模式对比
  - Legacy BIOS vs UEFI 启动差异
  - GRUB relocator 机制

- **[GRUB_PAGE_TABLE_CORRECTIONS.md](GRUB_PAGE_TABLE_CORRECTIONS.md)** - GRUB 分页说明
  - GRUB 在不同模式下的分页状态
  - UEFI 固件页表使用

---

## 附录：关键寄存器状态追踪

### GDTR 寄存器演化

| 阶段 | GDTR.Base | GDTR.Limit | 说明 |
|------|-----------|-----------|------|
| BIOS | - | - | 实模式无 GDTR |
| GRUB | GRUB GDT 地址 | 23 (3个段 × 8 - 1) | GRUB 内存区 |
| 压缩内核 | boot_gdt 地址 | 31 (4个段 × 8 - 1) | 内核镜像 .data |
| 主内核早期 | gdt_page 地址 | 255 (32个段 × 8 - 1) | 共享 gdt_page |
| 主内核运行 | Per-CPU gdt_page | 255 | 每 CPU 独立 |

### CR0/CR3/CR4 寄存器演化

| 阶段 | CR0.PG | CR0.PE | CR3 | CR4.PAE | 说明 |
|------|--------|--------|-----|---------|------|
| BIOS | 0 | 0 | - | - | 实模式 |
| GRUB | 0 | 1 | - | 0 | 保护模式，无分页 |
| 压缩内核(startup_32) | 0 | 1 | - | 0 | 建立 pgtable |
| 压缩内核(启用分页前) | 0 | 1 | pgtable | 1 | PAE 已启用 |
| 压缩内核(启用分页后) | 1 | 1 | pgtable | 1 | **长模式激活** |
| 主内核早期 | 1 | 1 | early_top_pgt | 1 | 双映射 |
| 主内核运行 | 1 | 1 | swapper_pg_dir | 1 | Direct Mapping |

### EFER 寄存器演化

| 阶段 | EFER.LME | EFER.LMA | 说明 |
|------|----------|----------|------|
| BIOS/GRUB | 0 | 0 | 未启用长模式 |
| 压缩内核(启用分页前) | 1 | 0 | 长模式已启用但未激活 |
| 压缩内核(启用分页后) | 1 | 1 | **长模式激活**（CPU 自动设置 LMA） |
| 主内核 | 1 | 1 | 长模式运行 |

**关键观察**：
- **EFER.LME**：软件设置（WRMSR）
- **EFER.LMA**：硬件自动设置（CR0.PG = 1 时，如果 LME=1，则 LMA 自动变为 1）

---

**文档版本**：v1.0
**最后更新**：2026-02-11
**作者**：Linux 内核内存管理三部曲
