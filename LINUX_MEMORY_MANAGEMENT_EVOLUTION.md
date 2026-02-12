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
│ ③ 压缩   │ 长模式      │ gdt64+gdt   │ pgtable      │ Identity(VA=PA) │
│ ④ 主内核 │ 长模式      │ gdt_page    │ swapper_pg   │ Direct(VA=PA+⊿)│
└──────────┴─────────────┴─────────────┴──────────────┴─────────────────┘
```

**关键演化节点**：
- **BIOS → GRUB**：进入保护模式，启用第一套 GDT
- **GRUB → 压缩内核**：首次建立页表，进入长模式
- **压缩内核 → 主内核**：切换到完整 GDT 和高地址映射

本文档按时间线详细讲解每个阶段的演化过程。

---

## 关键概念：x86-64 地址空间布局

在阅读本文档之前，需要理解 x86-64 架构下的**低地址**和**高地址**概念，这对理解内核启动过程至关重要。

### 地址空间划分

x86-64 架构的 64 位虚拟地址空间被分为两个主要区域：

```
64 位虚拟地址空间（理论 2^64 = 16EB，实际 48/57 位）：

┌─────────────────────────────────────────────────────────┐
│ 高半部分（内核空间）                                      │
│ 0xFFFF800000000000 - 0xFFFFFFFFFFFFFFFF                 │
│ └─ 高地址（High Addresses）                              │
│                                                          │
│ 【内核区域】：                                            │
│ 0xFFFF888000000000 - 0xFFFFC87FFFFFFFFF: Direct Mapping │
│   (物理内存直接映射区，64TB)                              │
│ 0xFFFFFFFF80000000 - 0xFFFFFFFFFFFFFFFF: 内核代码/数据   │
│   (内核镜像链接地址)                                      │
└─────────────────────────────────────────────────────────┘
                        中间是非规范地址
                  (0x0000800000000000 - 0xFFFF7FFFFFFFFFFF)
                         不可使用
┌─────────────────────────────────────────────────────────┐
│ 低半部分（用户空间）                                      │
│ 0x0000000000000000 - 0x00007FFFFFFFFFFF                 │
│ └─ 低地址（Low Addresses）                               │
│                                                          │
│ 【用户区域】：                                            │
│ 0x0000000000000000 - 0x00007FFFFFFFFFFF: 用户进程空间    │
│   (代码、数据、堆、栈、共享库等)                          │
└─────────────────────────────────────────────────────────┘
```

### 术语定义

**低地址（Low Addresses）**：
- **范围**：`0x0000000000000000 - 0x00007FFFFFFFFFFF`（理论上限 128TB，实际更小）
- **用途**：用户空间（User Space）
- **特点**：
  - 地址以 `0x0000` 开头
  - 每个用户进程有独立的低地址映射
  - 不能直接访问内核数据

**高地址（High Addresses）**：
- **范围**：`0xFFFF800000000000 - 0xFFFFFFFFFFFFFFFF`
- **用途**：内核空间（Kernel Space）
- **特点**：
  - 地址以 `0xFFFF` 开头
  - 所有进程共享相同的高地址映射
  - 内核代码、数据、直接映射区都在这里

**规范地址（Canonical Address）**：
- x86-64 实际只使用 48 位或 57 位地址
- 规范地址要求：高位必须是第 47 位（或第 56 位）的符号扩展
- 低地址：bit[63:48] 全为 0
- 高地址：bit[63:48] 全为 1
- 中间地址（非规范）会触发 #GP 异常

### 内核启动过程中的地址使用

**阶段 1-2：BIOS/GRUB（无分页或低地址）**
```
物理地址直接访问，或使用扁平模式：
  - 内核镜像加载位置：通常在 1MB（0x00100000）附近
  - 地址范围：0x00000000 - 0xFFFFFFFF（32位地址空间）
```

**阶段 3：压缩内核（Identity Mapping，低地址）**
```
首次启用分页，使用恒等映射（VA = PA）：
  - 虚拟地址 = 物理地址
  - 例如：物理 0x01000000 → 虚拟 0x01000000
  - 仍在低地址范围（< 4GB）
  - 这是过渡阶段，代码运行在低地址
```

**阶段 4：主内核（Direct Mapping，高地址）**
```
切换到最终的内核地址空间布局：
  - 内核代码：0xFFFFFFFF80000000 + offset
  - 物理内存直接映射：0xFFFF888000000000 + PA
  - 所有内核代码都运行在高地址
```

### 为什么需要低地址和高地址分离？

**1. 地址隔离（安全）**
```
用户进程：
  └─ 只能访问低地址（0x0000...）
  └─ 访问高地址 → #GP 异常（权限不足）

内核：
  └─ 可以访问所有地址
  └─ 通过页表权限位控制
```

**2. 共享内核映射（效率）**
```
所有进程的高地址映射相同：
  ┌─────────────┐
  │ 进程 A 页表 │ ← PML4[256-511] 指向共享的内核页表
  ├─────────────┤
  │ 进程 B 页表 │ ← PML4[256-511] 指向相同的内核页表
  └─────────────┘

好处：
  - 进程切换不需要刷新内核映射
  - 系统调用无需切换页表（只切换特权级）
```

**3. 直接映射物理内存（便利）**
```
内核需要访问任意物理内存：
  物理地址 PA → 虚拟地址 0xFFFF888000000000 + PA

例如：
  物理 0x12345000 → 虚拟 0xFFFF888012345000
  内核可以直接通过这个虚拟地址访问
```

### 本文档中的地址术语

当我们说：
- **"低地址运行"** = 代码在 0x0000xxxx 范围执行（如 0x01000000）
- **"高地址运行"** = 代码在 0xFFFFxxxx 范围执行（如 0xFFFFFFFF81000000）
- **"切换到高地址"** = 从 Identity Mapping 切换到 Direct Mapping
- **"链接地址"** = 链接器分配的虚拟地址（通常是高地址，如 0xFFFFFFFF81000000）
- **"运行时地址"** = 代码实际执行的地址（可能是低地址）

### 关键时刻：低地址 → 高地址切换

```
启动过程中的地址转换：

T1: 压缩内核 startup_64（低地址）
    ├─ 代码位置：VA 0x01000000 = PA 0x01000000
    ├─ 映射方式：Identity Mapping（VA = PA）
    └─ 地址范围：低地址（< 4GB）

T2: 建立高地址映射
    ├─ 创建 Direct Mapping（VA = PA + 0xFFFF888000000000）
    ├─ 映射内核代码（VA = PA + 0xFFFFFFFF80000000）
    └─ 两种映射共存

T3: 跳转到高地址
    ├─ jmp 到 0xFFFFFFFF81xxxxxx
    ├─ 代码位置：VA 0xFFFFFFFF81000000 → PA 0x01000000（同一物理地址）
    └─ 地址范围：高地址

T4: 移除低地址映射
    └─ 只保留高地址映射（最终状态）
```

### 实际例子

**低地址示例**：
```c
// 压缩内核 startup_64 早期
当前 RIP = 0x0000000001000000  ← 低地址
gdt_page 物理地址 = 0x0000000001234000  ← 低地址
```

**高地址示例**：
```c
// 主内核运行时
当前 RIP = 0xFFFFFFFF81234000  ← 高地址
gdt_page 虚拟地址 = 0xFFFFFFFF82345000  ← 高地址
              ↓（页表转换）
gdt_page 物理地址 = 0x0000000001345000  ← 同一物理地址
```

**为什么需要 RIP 相对寻址**：
```
问题：代码在低地址运行，但符号链接在高地址

startup_64 早期：
  - 当前位置：0x01000000（低地址，能访问）
  - gdt_page 链接地址：0xFFFFFFFF82345000（高地址，未映射）
  - 直接用链接地址 → #PF（页面不存在）

解决方案：
  - 使用 RIP 相对寻址：leaq gdt_page(%rip), %rax
  - 计算相对偏移：offset = 0x82345000 - 0x81000000 = 0x01345000
  - 实际地址：0x01000000 + 0x01345000 = 0x02345000
  - 这是当前可访问的低地址 ✅
```

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

### 3.1 压缩内核的 GDT（gdt64 + gdt）

#### 为什么要换 GDT

GRUB 的 GDT 有两个问题：
1. **位置不安全**：GRUB GDT 位于 GRUB 内存区域，内核解压时可能被覆盖
2. **生命周期不匹配**：GRUB 运行结束后，GRUB GDT 不再可靠

因此，压缩内核必须建立 **自己的 GDT**（gdt64 + gdt）。

#### 压缩内核 GDT 的内容（gdt64 + gdt）

压缩内核的 GDT 结构定义在 `arch/x86/boot/compressed/head_64.S:491-505`：

```assembly
# arch/x86/boot/compressed/head_64.S
# 结构 1：64 位 GDT 描述符（GDTR）
SYM_DATA_START_LOCAL(gdt64)
    .word   gdt_end - gdt - 1        # Limit: GDT 表大小 - 1
    .quad   gdt - gdt64               # Base: gdt 相对于 gdt64 的偏移
SYM_DATA_END(gdt64)

    .balign 8
# 结构 2：32 位 GDT 描述符 + GDT 表（巧妙的二合一设计）
SYM_DATA_START_LOCAL(gdt)
    # ===== 前 10 字节：可作为 32 位 GDTR =====
    .word   gdt_end - gdt - 1        # Limit（2 字节）
    .long   0                         # Base 低 32 位（运行时填充，4 字节）
    .word   0                         # Base 高 16 位 + 填充（2 字节）
    # 注：32 位模式只使用 6 字节（limit + base），
    #     但为了 8 字节对齐，定义了 10 字节

    # ===== 从这里开始是实际的 GDT 段描述符 =====
    .quad   0x00cf9a000000ffff       # GDT[1]: __KERNEL32_CS (32位代码段)
    .quad   0x00af9a000000ffff       # GDT[2]: __KERNEL_CS (64位代码段)
    .quad   0x00cf92000000ffff       # GDT[3]: __KERNEL_DS (数据段)
    .quad   0x0080890000000000       # GDT[4]: TS descriptor
    .quad   0x0000000000000000       # GDT[5]: TS continued
SYM_DATA_END_LABEL(gdt, SYM_L_LOCAL, gdt_end)
```

**设计巧妙之处**：

1. **gdt64 结构**（10 字节）：
   - 专门给 **64 位模式**使用的 GDTR
   - 8 字节 base 地址（64 位地址空间）
   - 使用相对偏移（`gdt - gdt64`），便于重定位

2. **gdt 结构**（自包含设计）：
   - **前 10 字节**：可以作为 **32 位模式** GDTR（6 字节有效 + 4 字节填充）
   - **第 10 字节之后**：实际的 GDT 段描述符表
   - 一个结构，两种用途！

**加载方式对比**：

```assembly
# 方式 1：32 位模式（startup_32，第 106-108 行）
leal    rva(gdt)(%ebp), %eax    # %eax = gdt 的物理地址
movl    %eax, 2(%eax)            # 填充 base 字段（gdt 结构的 2-5 字节）
lgdt    (%eax)                   # 加载：使用 gdt 前 6 字节作为 32 位 GDTR

# 方式 2：64 位模式（startup_64，第 359-361 行）
leaq    gdt64(%rip), %rax        # %rax = gdt64 的地址
addq    %rax, 2(%rax)            # 修正 base 地址（gdt64 的相对偏移改为绝对地址）
lgdt    (%rax)                   # 加载：使用 gdt64 作为 64 位 GDTR

# 方式 3：64 位模式重定位后（startup_64，第 433-436 行）
leaq    rva(gdt64)(%rbx), %rax  # 重定位后的 gdt64 地址
leaq    rva(gdt)(%rbx), %rdx    # 重定位后的 gdt 地址
movq    %rdx, 2(%rax)            # 更新 gdt64 的 base 指向新的 gdt 位置
lgdt    (%rax)                   # 重新加载
```

**段选择子**：
- `__KERNEL32_CS = 0x10`：GDT[1]，32 位代码段（startup_32 使用）
- `__KERNEL_CS = 0x18`：GDT[2]，64 位代码段（startup_64 使用）
- `__KERNEL_DS = 0x20`：GDT[3]，数据段

#### 压缩内核 GDT 的生命周期

- **加载时机**：startup_32 早期加载（`lgdt gdt`，head_64.S:108）
- **使用期间**：startup_32 → startup_64 → 解压内核 → 跳转到主内核早期
- **废弃时机**：主内核调用 startup_64_setup_gdt_idt() 切换到 gdt_page 后被释放

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
- **硬编码映射**：直接映射 2048 个 2MB 页（4GB），**不依赖 E820 表**
- **临时结构**：pgtable 位于压缩内核的 .pgtable 段，后续会被释放

> **重要说明**：为什么这个阶段不需要 E820 表就可以建立页表，而主内核的 `init_mem_mapping()` 必须依赖 E820 表？详见 **[E820_MEMORY_MAP.md - E820 表与 Paging 的分阶段依赖关系](E820_MEMORY_MAP.md#e820-表与-paging分页的关系分阶段的依赖关系)**。

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
│ 1. 加载 GDT (lgdt gdt)  # 使用 gdt 结构（32位模式）        │
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
| 步骤1 | 32位保护模式 | GDTR = gdt | 切换到内核自己的 GDT (32位模式加载) |
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

**演化意义**：此时进入主内核阶段，压缩内核的 gdt/gdt64 和 pgtable 即将被废弃。

---

## 阶段 ④：主内核阶段

主内核（解压后的 vmlinux）接管控制权后，需要建立 **完整的内存管理系统**。

### 4.0 从临时页表到完整内存管理：主内核的内存初始化全过程

> **本章节回答关键问题**：在主内核启动早期（`idt_setup_early_handler()` 设置 early IDT 时），系统的内存管理处于什么状态？分页是否已启用？是否能为进程分配内存？

#### 4.0.1 背景：为什么需要关注这个问题

在 Linux 内核启动过程中，存在一个关键的演化阶段：**从压缩内核的临时页表过渡到主内核的完整内存管理系统**。这个过程涉及多个关键组件的初始化，时序错误可能导致系统崩溃。

**核心依赖关系**（来自内核源码注释）：

文件：`arch/x86/kernel/setup.c:1119-1122`
```c
init_mem_mapping();

/*
 * init_mem_mapping() relies on the early IDT page fault handling.
 * 翻译：init_mem_mapping() 依赖于 early IDT 的 page fault 处理！
 */
```

这个注释揭示了一个重要的依赖链：**early IDT → 完整内存映射 → 内存管理系统**

#### 4.0.2 代码时序证据：从分页启用到内存管理建立

根据内核源码（基于 Linux v6.x），让我们追踪从分页启用到完整内存管理建立的完整流程。

##### 时间点 1：分页启用（压缩内核阶段）

**文件**：`arch/x86/boot/compressed/head_64.S:199-241`

```asm
/* startup_32 函数中 */

/* Initialize Page tables to 0 */
leal    rva(pgtable)(%ebx), %edi
xorl    %eax, %eax
movl    $(BOOT_INIT_PGT_SIZE/4), %ecx
rep     stosl                              # 清零页表

/* Build Level 4 */
leal    rva(pgtable + 0)(%ebx), %edi
leal    0x1007 (%edi), %eax
movl    %eax, 0(%edi)
addl    %edx, 4(%edi)

/* Build Level 3 */
leal    rva(pgtable + 0x1000)(%ebx), %edi
leal    0x1007(%edi), %eax
movl    $4, %ecx
1:  movl    %eax, 0x00(%edi)
    addl    %edx, 0x04(%edi)
    addl    $0x00001000, %eax
    addl    $8, %edi
    decl    %ecx
    jnz     1b

/* Build Level 2 */
leal    rva(pgtable + 0x2000)(%ebx), %edi
movl    $0x00000183, %eax                  # Present + RW + PS (2MB页)
movl    $2048, %ecx
1:  movl    %eax, 0(%edi)
    addl    %edx, 4(%edi)
    addl    $0x00200000, %eax              # 每次增加 2MB
    addl    $8, %edi
    decl    %ecx
    jnz     1b

/* Enable the boot page tables */
leal    rva(pgtable)(%ebx), %eax
movl    %eax, %cr3                         # ← 加载页表基址

/* Enable Long mode in EFER (Extended Feature Enable Register) */
movl    $MSR_EFER, %ecx
rdmsr
btsl    $_EFER_LME, %eax
wrmsr                                      # ← 启用长模式
```

**此时的系统状态**：
- ✅ 已建立**临时身份映射页表**（虚拟地址 = 物理地址）
- ✅ CR3 已加载页表基址
- ✅ EFER.LME = 1（长模式已启用）
- ✅ 接下来在 `startup_32` 末尾启用 CR0.PG（分页标志）
- ✅ 映射范围：约 4GB（2048 个 2MB 大页）

##### 时间点 2：early IDT 设置时刻

**文件**：`arch/x86/kernel/head64.c:219-289`

```c
asmlinkage __visible void __init __noreturn x86_64_start_kernel(char * real_mode_data)
{
    /* ... 编译时检查 ... */
    BUILD_BUG_ON(MODULES_VADDR < __START_KERNEL_map);
    /* ... */

    cr4_init_shadow();

    /* Kill off the identity-map trampoline */
    reset_early_page_tables();              # ← 重置早期页表

    /* ... */

    clear_bss();                            # ← 清零 BSS 段

    /* ... SME 初始化 ... */
    clear_page(init_top_pgt);

    sme_early_init();                       # ← SME（安全内存加密）初始化

    kasan_early_init();                     # ← KASAN（内核地址消毒器）初始化

    /* Flush global TLB entries */
    __native_tlb_flush_global(this_cpu_read(cpu_tlbstate.cr4));

    idt_setup_early_handler();              # ← ✨ early IDT 设置在这里！

    /* ... */

    /* set init_top_pgt kernel high mapping*/
    init_top_pgt[511] = early_top_pgt[511]; # ← 设置内核高地址映射

    x86_64_start_reservations(real_mode_data);
}
```

**此时的系统状态**：
- ✅ 分页已启用（CR0.PG = 1）
- ✅ 使用临时身份映射（VA = PA）
- ✅ early IDT 已设置（可以处理异常）
- ❌ memblock 未建立
- ❌ 完整内存映射未建立
- ❌ 不能为进程分配内存

##### 时间点 3：内存管理系统建立（晚于 early IDT）

**文件**：`init/main.c:898-940`，`arch/x86/kernel/setup.c:875-1122`

```c
/* init/main.c */
void start_kernel(void)
{
    /* ... */
    local_irq_disable();                    # 关中断
    early_boot_irqs_disabled = true;

    boot_cpu_init();
    page_address_init();
    pr_notice("%s", linux_banner);
    setup_arch(&command_line);              # ← ✨ 内存管理在这里建立！
    /* ... */
}

/* arch/x86/kernel/setup.c:875-1122 */
void __init setup_arch(char **cmdline_p)
{
    /* ... 前期准备 ... */

    /* 1062行注释：Need to conclude brk, before e820__memblock_setup() */

    e820__memblock_setup();                 # ← 1070行：建立 memblock 分配器

    /* ... */

    init_mem_mapping();                     # ← 1119行：建立完整的内存映射

    /* 1122行注释：
     * init_mem_mapping() relies on the early IDT page fault handling.
     *                      ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
     * 翻译：init_mem_mapping() 依赖于 early IDT 的 page fault 处理！
     */

    /* ... */
}
```

**关键代码 1：e820__memblock_setup()**

**文件**：`arch/x86/kernel/e820.c:1240-1279`

```c
void __init e820__memblock_setup(void)
{
    int i;
    u64 end;

    /* 1270行注释：
     * At this point only the first megabyte is mapped for sure, the
     * rest of the memory cannot be used for memblock resizing
     * 翻译：此时只有第一个 MB 被确定映射了，其余内存还不能用于 memblock 调整大小
     */
    memblock_set_current_limit(ISA_END_ADDRESS);  # 限制为 1MB

    /* 允许 memblock 调整大小（因为 EFI 可能传递超过 128 个条目） */
    memblock_allow_resize();

    /* 遍历 E820 内存映射，将 RAM 区域加入 memblock */
    for (i = 0; i < e820_table->nr_entries; i++) {
        struct e820_entry *entry = &e820_table->entries[i];

        /* ... */

        if (entry->type != E820_TYPE_RAM)
            continue;

        /* 将 RAM 区域加入 memblock.memory */
        memblock_add(entry->addr, entry->size);
    }
    /* ... */
}
```

**关键代码 2：init_mem_mapping()**

**文件**：`arch/x86/mm/init.c:758-789`

```c
void __init init_mem_mapping(void)
{
    unsigned long end;

    pti_check_boottime_disable();
    probe_page_size_mask();                 # 检测页大小（4KB/2MB/1GB）
    setup_pcid();

#ifdef CONFIG_X86_64
    end = max_pfn << PAGE_SHIFT;            # 计算最大物理地址
#else
    end = max_low_pfn << PAGE_SHIFT;
#endif

    /* the ISA range is always mapped regardless of memory holes */
    init_memory_mapping(0, ISA_END_ADDRESS, PAGE_KERNEL);  # 映射 ISA 范围

    /* Init the trampoline, possibly with KASLR memory offset */
    init_trampoline();

    /* 如果是 bottom-up 分配，则从下往上建立直接映射 */
    if (memblock_bottom_up()) {
        unsigned long kernel_end = __pa_symbol(_end);

        /* 先映射 [kernel_end, end)，这样页表可以分配在内核之上 */
        /* 然后使用这些页表映射 [ISA_END_ADDRESS, kernel_end) */
        /* ... */
    } else {
        /* 否则从上往下建立映射 */
    }
    /* ... */
}
```

**此时的系统状态**（`setup_arch()` 完成后）：
- ✅ 分页已启用
- ✅ memblock 已建立（可用于早期内存分配）
- ✅ 完整内存映射已建立（直接映射 VA = PA + __PAGE_OFFSET）
- ⚠️  只能用 memblock 分配，buddy/slab 还未初始化
- ❌ 还不能创建进程（进程调度器未初始化）

#### 4.0.3 时间线总结：从分页到完整内存管理

```
时间线：分页 → early IDT → memblock → 完整内存映射 → buddy/slab → 进程管理

┌─────────────────────────────────────────────────────────────────┐
│ 压缩内核 startup_32 (arch/x86/boot/compressed/head_64.S)        │
├─────────────────────────────────────────────────────────────────┤
│ ✅ 构建临时页表（199-231行）                                      │
│ ✅ CR3 = pgtable (234-235行)                                    │
│ ✅ EFER.LME = 1 (237-241行)                                     │
│ ✅ CR0.PG = 1（启用分页，约 250行）                               │
│                                                                  │
│ 状态：分页已启用（身份映射：VA = PA）                              │
│       映射范围：约 4GB（2048 个 2MB 页）                          │
└─────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│ 主内核 x86_64_start_kernel (arch/x86/kernel/head64.c:219)      │
├─────────────────────────────────────────────────────────────────┤
│ reset_early_page_tables()       (238行) - 重置页表              │
│ clear_bss()                     (246行) - 清零BSS               │
│ sme_early_init()                (259行) - SME初始化              │
│ kasan_early_init()              (261行) - KASAN初始化            │
│ __native_tlb_flush_global()     (271行) - 刷新TLB               │
│ ✨ idt_setup_early_handler()    (273行) ← 关键时刻！             │
│                                                                  │
│ 状态：✅ 分页已启用                                               │
│       ❌ memblock 未建立                                         │
│       ❌ 完整内存映射未建立                                       │
│       ❌ 不能为进程分配内存                                       │
└─────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│ start_kernel() → setup_arch() (init/main.c:920)                │
├─────────────────────────────────────────────────────────────────┤
│ ✨ e820__memblock_setup()       (setup.c:1070)                  │
│    └─ 将 E820 RAM 区域加入 memblock.memory                       │
│    └─ 此时只有第一个 MB 被确定映射（e820.c:1273注释）              │
│                                                                  │
│ ✨ init_mem_mapping()            (setup.c:1119)                 │
│    └─ 为所有 RAM 建立直接映射页表                                 │
│    └─ 依赖 early IDT 的 #PF 处理（setup.c:1122注释）             │
│                                                                  │
│ 状态：✅ 分页已启用                                               │
│       ✅ memblock 已建立（可用于早期内存分配）                     │
│       ✅ 完整内存映射已建立                                       │
│       ⚠️  只能用 memblock 分配，buddy/slab 还未初始化             │
│       ❌ 还不能创建进程（进程调度器未初始化）                       │
└─────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│ start_kernel() 后续初始化                                        │
├─────────────────────────────────────────────────────────────────┤
│ mm_init()           - 初始化 buddy 和 slab 分配器                 │
│ sched_init()        - 初始化进程调度器                            │
│ rest_init()         - 创建第一个进程（PID 1）                     │
│                                                                  │
│ 状态：✅ 完整内存管理系统就绪                                      │
│       ✅ 可以创建进程                                             │
└─────────────────────────────────────────────────────────────────┘
```

#### 4.0.4 为什么 early IDT 必须先于 init_mem_mapping()？

根据 `setup.c:1122` 的注释，`init_mem_mapping()` **依赖于 early IDT 的 page fault 处理**。原因分析：

**1. 页表构建过程可能触发 #PF**

```c
/* init_mem_mapping() 内部调用 */
void init_memory_mapping(unsigned long start, unsigned long end, pgprot_t prot)
{
    /* 分配新的页表页 */
    pte_t *pte = alloc_low_page();  // ← 可能访问未映射的内存

    /* 设置页表项 */
    *pte = __pte(pfn | prot_val);   // ← 可能触发 #PF
}
```

**2. 内存访问模式变化**

- 从身份映射（VA = PA）
- 切换到直接映射（VA = PA + __PAGE_OFFSET）
- 过渡期间可能访问到未映射区域

**3. 如果没有 early IDT 的后果**

```
init_mem_mapping() 访问未映射内存
    ↓
CPU 触发 #PF（向量 14）
    ↓
查找 IDT[14] → 如果为空或未设置
    ↓
触发 Double Fault (#DF, 向量 8)
    ↓
查找 IDT[8] → 如果为空
    ↓
Triple Fault → CPU 重启 💥
```

**4. 有了 early IDT 的保护**

```
init_mem_mapping() 访问未映射内存
    ↓
CPU 触发 #PF（向量 14）
    ↓
查找 IDT[14] → early_idt_handler_array[14]
    ↓
进入 page_fault 处理函数
    ↓
处理异常（打印错误信息或修复）
    ↓
如果是合法的延迟分配 → 分配页面、更新页表、返回
如果是真正的错误 → 打印错误、停止系统（受控停止）
```

#### 4.0.5 状态对比表：各阶段的内存管理能力

| 时刻 | CR0.PG | 页表 | memblock | 完整映射 | buddy/slab | 进程管理 | 能否为进程分配内存 |
|------|--------|------|----------|---------|-----------|---------|------------------|
| **startup_32 开始** | 0 | 无 | ❌ 无 | ❌ 无 | ❌ 无 | ❌ 无 | ❌ 不能 |
| **startup_32 末尾** | 1 | 临时身份映射 | ❌ 无 | ❌ 无 | ❌ 无 | ❌ 无 | ❌ 不能 |
| **early_idt_handler_array 设置时** | 1 | 临时身份映射 | ❌ 无 | ❌ 无 | ❌ 无 | ❌ 无 | ❌ 不能 |
| **e820__memblock_setup 后** | 1 | 临时身份映射 | ✅ 有（1MB限制） | ❌ 无 | ❌ 无 | ❌ 无 | ⚠️  只能用 memblock |
| **init_mem_mapping 后** | 1 | 完整直接映射 | ✅ 有（完整） | ✅ 有 | ❌ 无 | ❌ 无 | ⚠️  只能用 memblock |
| **mm_init 后** | 1 | 完整直接映射 | ✅ 有 | ✅ 有 | ✅ 有 | ❌ 无 | ✅ 可以（buddy/slab） |
| **sched_init 后** | 1 | 完整直接映射 | ✅ 有 | ✅ 有 | ✅ 有 | ✅ 有 | ✅ 可以 |
| **rest_init 后** | 1 | 完整直接映射 | ✅ 有 | ✅ 有 | ✅ 有 | ✅ 有 | ✅ 可以创建进程 |

#### 4.0.6 核心结论

**在 `idt_setup_early_handler()` 被调用时（设置 `early_idt_handler_array`）：**

✅ **分页机制已启用**
- CR0.PG = 1
- CR3 指向临时页表
- 使用身份映射（VA = PA）
- 映射范围约 4GB

❌ **没有完整的内存管理系统**
- memblock 分配器未建立
- 完整的内存映射未建立
- buddy 和 slab 分配器未初始化
- 进程调度器未初始化

❌ **不能为进程分配内存**
- 进程管理系统尚未初始化
- 只能进行静态内存访问（如访问内核代码和数据段）
- 不能使用动态内存分配（kmalloc、vmalloc 等）

✨ **early IDT 的关键作用**
- 保护后续的内存初始化过程（特别是 `init_mem_mapping()`）
- 提供基本的异常处理能力
- 防止未处理的异常导致 Triple Fault 重启

这就是为什么内核在 `setup.c:1122` 添加注释强调 "init_mem_mapping() relies on the early IDT page fault handling" 的原因。

---

### 4.1 主内核的 GDT（gdt_page）

#### 为什么再次换 GDT

压缩内核的 GDT (gdt64 + gdt) 有三个限制：
1. **段数量少**：只有 5 个显式段（GDT[1-5]），不足以支持完整功能
2. **不支持 Per-CPU**：单一 GDT 无法支持多 CPU
3. **会被释放**：gdt/gdt64 所在内存（压缩内核段）会被释放回收

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
// arch/x86/kernel/head_64.S:74
SYM_CODE_START_NOALIGN(startup_64)
    call startup_64_setup_gdt_idt  // 设置早期 GDT
```

**GDT 描述符的构建方式**：
```c
// arch/x86/boot/startup/gdt_idt.c:49-70
void __head startup_64_setup_gdt_idt(void)
{
    // 使用 RIP 相对寻址获取 gdt_page 地址
    struct gdt_page *gp = rip_rel_ptr((void *)&gdt_page);

    // 在栈上动态构建 GDT 描述符
    struct desc_ptr startup_gdt_descr = {
        .address = (unsigned long)gp->gdt,
        .size = GDT_SIZE - 1
    };

    // 加载 GDT
    native_load_gdt(&startup_gdt_descr);

    // 重载段寄存器...
}
```

**特点**：
- **动态构建**：在栈上构建 `desc_ptr` 结构（不是静态定义的数据）
- **RIP 相对寻址**：使用 `rip_rel_ptr()` 计算 gdt_page 的当前可访问地址
- 使用 gdt_page 结构，但此时还是单一的（BSP 的 gdt_page）
- 所有 CPU 共享同一个 GDT（Per-CPU 机制尚未建立）

> **架构说明**：64 位内核（x86_64）不使用静态的 `early_gdt_descr` 数据结构。`early_gdt_descr` 只存在于 32 位内核（i386）的 `arch/x86/kernel/head_32.S` 中。64 位内核通过 `startup_64_setup_gdt_idt()` 函数动态构建 GDT 描述符，使用 **RIP 相对寻址**来适应启动早期的低地址环境。详细的技术细节请参考 **[实现篇 1.3.5节](LINUX_MEMORY_MANAGEMENT_CODE_GUIDE.md#135-64位vs32位gdt描述符加载方式)**。

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
│  GRUB GDT   │ →   │ gdt64+gdt   │ →   │  gdt_page   │
│  (GRUB区)   │     │  (内核镜像) │     │  (Per-CPU)  │
└─────────────┘     └─────────────┘     └─────────────┘
  GRUB 运行期       压缩→主内核早期      主内核运行期
```

#### 三套 GDT 对比表

| 特性 | GRUB GDT | 压缩内核 GDT (gdt64+gdt) | gdt_page |
|------|---------|----------|----------|
| **段数量** | 4个（NULL + CS + DS + 32位CS） | 5个显式段（GDT[1-5]: 32位CS + 64位CS + DS + TSS） | 32个（内核/用户/TSS/LDT...） |
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

**2. 压缩内核 GDT (gdt64 + gdt)**：
- **必要性**：GRUB GDT 会被覆盖，需要内核自己的 GDT
- **局限性**：段数量少（仅5个），不支持 Per-CPU 和用户态

**3. gdt_page**：
- **必要性**：压缩内核 GDT 被释放，需要永久 GDT
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
| **③ 压缩内核** | 长模式 | gdt64+gdt | pgtable | Identity (VA=PA) | 首次启用分页 |
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
| 压缩内核 | gdt 地址 | 47 (6个GDT项 × 8 - 1) | 内核镜像 .data |
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
