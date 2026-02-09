# Linux 内存管理演化：从 BIOS 到内核的完整过渡

> **文档定位**：本文档按时间线展示从 BIOS 启动到 Linux 内核运行的内存管理演化过程，包括 GDT 和页表的四个演化阶段。

## 文档导航

- **[理论篇](X86_MEMORY_MANAGEMENT_THEORY.md)**：硬件机制与概念
- **演化篇**（本文档）：从 BIOS 到 Linux 内核的过渡
- **[实现篇](LINUX_MEMORY_MANAGEMENT_CODE_GUIDE.md)**：源代码详解与实战调试

---

## 演化概览：四个阶段

```
时间线：BIOS → GRUB → 压缩内核 → 主内核

┌────────────────┬──────────┬──────────┬────────────┬─────────┐
│ 阶段           │ CPU模式  │ GDT      │ 页表       │ 地址映射│
├────────────────┼──────────┼──────────┼────────────┼─────────┤
│ ① BIOS         │ 实模式   │ 无       │ 无         │ 1MB直接 │
│ ② GRUB         │ 保护/长  │ GRUB GDT │ GRUB页表   │ Identity│
│ ③ 压缩内核     │ 长模式   │ 临时GDT  │ 早期页表   │ Identity│
│ ④ 主内核       │ 长模式   │ gdt_page │ 完整页表   │ Direct  │
└────────────────┴──────────┴──────────┴────────────┴─────────┘
```

---

## 阶段 ①：BIOS 阶段

### BIOS 内存布局

在计算机启动时，BIOS 建立了一个固定的内存布局，前 1MB 内存分配如下：

```
0x00000000 - 0x000003FF   IVT（中断向量表）         1KB
0x00000400 - 0x000004FF   BIOS 数据区              256B
0x00000500 - 0x00007BFF   可用 RAM                 ~30KB
0x00007C00 - 0x00007DFF   引导扇区加载位置          512B
0x00007E00 - 0x0007FFFF   可用 RAM                 ~480KB
0x00080000 - 0x0009FFFF   扩展 BIOS 数据区         128KB
0x000A0000 - 0x000BFFFF   显存（VGA）              128KB
0x000C0000 - 0x000FFFFF   BIOS ROM                 256KB
```

**关键特征**：

- **实模式**：16 位寻址，最大 1MB 地址空间
- **无 GDT**：直接使用物理地址
- **无分页**：段寄存器 * 16 + 偏移 = 物理地址

**实模式寻址示例**：

```
段:偏移 = 物理地址
0x07C0:0x0000 = 0x07C0 * 16 + 0x0000 = 0x7C00  ← 引导扇区
0xB800:0x0000 = 0xB800 * 16 + 0x0000 = 0xB8000 ← 显存
```

### E820 内存映射

BIOS 通过 INT 0x15, AX=0xE820 提供完整的物理内存映射（E820 Map）：

```c
struct e820_entry {
    uint64_t addr;   // 起始地址
    uint64_t size;   // 大小
    uint32_t type;   // 类型（可用、保留、ACPI 等）
};

// 典型的 E820 输出
dmesg | grep "BIOS-e820"
[    0.000000] BIOS-e820: [mem 0x0000000000000000-0x000000000009ffff] usable
[    0.000000] BIOS-e820: [mem 0x0000000000100000-0x00000000bffdffff] usable
[    0.000000] BIOS-e820: [mem 0x00000000bffe0000-0x00000000bfffffff] reserved
[    0.000000] BIOS-e820: [mem 0x0000000100000000-0x000000013fffffff] usable
```

**E820 的作用**：

- Linux 内核通过 E820 了解哪些物理内存可用
- 避免使用 BIOS 保留的内存区域
- 支持 4GB 以上内存（64 位系统）

---

## 阶段 ②：GRUB 阶段

GRUB（GRand Unified Bootloader）负责从 BIOS 交接到 Linux 内核，需要完成模式切换和内存管理初始化。

### GRUB 的 GDT 设置

GRUB 建立临时 GDT，用于从实模式切换到保护模式/长模式：

```c
// grub-core/lib/i386/relocator.c
static struct grub_i386_gdt_entry {
    uint64_t entry;
} __attribute__((packed));

struct grub_i386_gdt_entry grub_relocator_gdt[] = {
    [0] = { 0x0000000000000000ULL },  // NULL 描述符
    [1] = { 0x00CF9A000000FFFFULL },  // 32位代码段（Base=0, Limit=4GB）
    [2] = { 0x00CF92000000FFFFULL },  // 32位数据段（Base=0, Limit=4GB）
    [3] = { 0x00AF9A000000FFFFULL },  // 64位代码段（L=1, D=0）
    [4] = { 0x00AF92000000FFFFULL },  // 64位数据段
};
```

**GRUB GDT 特点**：

- **扁平模式**：所有段的 Base=0, Limit=4GB
- **简化设计**：只有最基本的代码段和数据段
- **临时使用**：仅在 GRUB 运行期间有效，内核会替换

### GRUB 的页表建立

**UEFI 启动路径**：GRUB 建立 4 级页表进入长模式

```c
// grub-core/kern/x86_64/efi/startup.S
// 建立临时页表（Identity Mapping）

// PML4: 一个条目
pml4:
    .quad pdpt + 0x03  // Present + R/W

// PDPT: 四个条目（映射 4GB）
pdpt:
    .quad pd0 + 0x03   // 0-1GB
    .quad pd1 + 0x03   // 1-2GB
    .quad pd2 + 0x03   // 2-3GB
    .quad pd3 + 0x03   // 3-4GB

// PD: 使用 2MB 大页
pd0:
    .rept 512
    .quad (. - pd0) * 0x200000 + 0x83  // 2MB 页 + Present + R/W + PS
    .endr
```

**GRUB 页表特点**：

- **Identity Mapping**：虚拟地址 = 物理地址
- **大页映射**：使用 2MB 页减少页表层级
- **映射范围**：至少 4GB（足够加载内核）

### 保护模式 → 长模式切换

GRUB 执行的关键步骤：

```
1. 加载 GDT（lgdt）
   ↓
2. 切换到保护模式（CR0.PE=1）
   ↓
3. 启用 PAE（CR4.PAE=1）
   ↓
4. 设置 CR3 指向页表
   ↓
5. 启用长模式（EFER.LME=1）
   ↓
6. 启用分页（CR0.PG=1）
   ↓
7. 跳转到 64 位代码段
```

**关键代码（GRUB UEFI 路径）**：

```asm
# 启用 PAE
movl %cr4, %eax
orl $CR4_PAE, %eax
movl %eax, %cr4

# 加载页表
movl $pml4, %eax
movl %eax, %cr3

# 启用长模式
movl $MSR_EFER, %ecx
rdmsr
orl $EFER_LME, %eax
wrmsr

# 启用分页
movl %cr0, %eax
orl $CR0_PG, %eax
movl %eax, %cr0

# 长跳转到 64 位代码段
ljmp $__GRUB_KERNEL_CS, $long_mode_start
```

### GRUB 加载内核

GRUB 将 Linux 内核加载到内存的固定位置：

```
压缩内核加载位置：
- 物理地址：0x100000（1MB）
- 原因：避开 BIOS 保留区域（0-1MB）

解压后内核位置：
- 物理地址：CONFIG_PHYSICAL_START（默认 0x1000000 = 16MB）
- 或：KASLR 随机地址

GRUB 交接给内核时的状态：
- CPU 模式：64 位长模式（Long Mode）
- GDT：GRUB 临时 GDT
- 页表：Identity Mapping
- %rsi：指向 boot_params 结构体（包含 E820 内存映射）
```

---

## 阶段 ③：压缩内核阶段

压缩内核（Compressed Kernel）负责解压主内核，并在解压前后管理内存。

### 压缩内核的临时 GDT

**位置**：`arch/x86/boot/compressed/head_64.S`

```asm
# 压缩内核的 GDT 定义
.section ".rodata", "a"
    .balign 16
SYM_DATA_START_LOCAL(gdt)
    .word   gdt_end - gdt - 1
    .long   0
    .word   0
    .quad   0x00cf9a000000ffff    # __KERNEL32_CS（32位代码段）
    .quad   0x00af9a000000ffff    # __KERNEL_CS（64位代码段）
    .quad   0x00cf92000000ffff    # __KERNEL_DS（数据段）
SYM_DATA_END_LABEL(gdt, SYM_L_LOCAL, gdt_end)
```

**与 GRUB GDT 的对比**：

| 特性 | GRUB GDT | 压缩内核 GDT |
|------|---------|-------------|
| 定义位置 | GRUB 二进制文件 | compressed/head_64.S |
| 生命周期 | GRUB 运行期间 | 解压内核期间 |
| 段数量 | 4-5 个 | 3 个（精简）|
| 后续演化 | 被压缩内核 GDT 替换 | 被主内核 GDT 替换 |

**为什么需要新的 GDT？**

1. **独立性**：内核不依赖 GRUB 的内存布局
2. **可控性**：内核完全控制段描述符属性
3. **简化**：只保留必需的段（代码、数据）

### 压缩内核的早期页表

**位置**：`arch/x86/boot/compressed/head_64.S`

```asm
# 页表定义
.section ".pgtable", "aw", @nobits
.balign 4096
SYM_DATA_START_LOCAL(pgtable)
    .fill BOOT_PGT_SIZE, 1, 0    # 预留空间（6 页 * 4KB = 24KB）
SYM_DATA_END(pgtable)
```

**页表建立代码**：

```asm
# arch/x86/boot/compressed/head_64.S:startup_32
# 在 .bss 段中构建 4 级页表

# 1. 清零页表区域
leaq    rva(pgtable)(%ebx), %edi
xorl    %eax, %eax
movl    $(BOOT_PGT_SIZE >> 2), %ecx
rep     stosl

# 2. 填充 PML4 → PDPT
leaq    rva(pgtable)(%ebx), %edi
leaq    0x1000(%edi), %eax
orl     $0x03, %eax              # Present + R/W
movl    %eax, 0(%edi)            # PML4[0]

# 3. 填充 PDPT → PD
leaq    0x1000(%edi), %edi       # 指向 PDPT
leaq    0x1000(%edi), %eax
orl     $0x03, %eax
movl    $4, %ecx                 # 4 个 PDPT 条目
1:  movl    %eax, 0(%edi)
    addl    $0x1000, %eax
    addl    $8, %edi
    decl    %ecx
    jnz     1b

# 4. 填充 PD（使用 2MB 大页）
leaq    rva(pgtable)(%ebx), %edi
addl    $0x2000, %edi            # 指向第一个 PD
movl    $0x00000083, %eax        # 物理地址 0 + Present + R/W + PS（2MB）
movl    $2048, %ecx              # 2048 个 PD 条目（4GB / 2MB）
1:  movl    %eax, 0(%edi)
    addl    $0x200000, %eax      # 下一个 2MB 页
    addl    $8, %edi
    decl    %ecx
    jnz     1b
```

**页表结构**：

```
压缩内核页表布局（位于 pgtable）：

Offset 0x0000: PML4 表（512 条目，但只用第 1 个）
  PML4[0] → PDPT（指向 Offset 0x1000）

Offset 0x1000: PDPT 表（512 条目，但只用前 4 个）
  PDPT[0] → PD0（0-1GB，指向 Offset 0x2000）
  PDPT[1] → PD1（1-2GB，指向 Offset 0x3000）
  PDPT[2] → PD2（2-3GB，指向 Offset 0x4000）
  PDPT[3] → PD3（3-4GB，指向 Offset 0x5000）

Offset 0x2000-0x5FFF: PD 表（4 个，每个 512 条目）
  PD[0] = 0x00000000 | PS  → 2MB 页（0-2MB）
  PD[1] = 0x00200000 | PS  → 2MB 页（2-4MB）
  ...
  PD[2047] = 0xFFE00000 | PS  → 2MB 页（4094-4096MB）

映射结果：虚拟 0-4GB → 物理 0-4GB（Identity Mapping）
```

**为什么使用 2MB 大页？**

1. **减少页表层级**：不需要 PT 级别，节省内存
2. **简化建立**：2048 个 PD 条目 vs 1,048,576 个 PT 条目
3. **足够映射**：4GB 足够覆盖压缩内核和解压后的主内核

### 重定位与解压过程

**为什么要重定位压缩内核？**

```
问题：
1. GRUB 将压缩内核加载到 1MB（0x100000）
2. 解压后的内核要放在 16MB（0x1000000）
3. 如果直接在 1MB 解压，会覆盖自己的代码和数据！

解决方案：将压缩内核重定位到更高地址（约 38MB）

┌────────────────────────────────┐
│ 0x100000: 压缩内核（原始位置） │ ← GRUB 加载
└────────────────────────────────┘
                ↓ 拷贝
┌────────────────────────────────┐
│ ~0x2600000: 压缩内核（重定位） │ ← 约 38MB
└────────────────────────────────┘
                ↓ 解压
┌────────────────────────────────┐
│ 0x1000000: 主内核（解压后）    │ ← 16MB
└────────────────────────────────┘
```

**解压流程**：

```c
// arch/x86/boot/compressed/misc.c:extract_kernel()
asmlinkage __visible void *extract_kernel(
    void *rmode,
    unsigned char *output,   // 解压目标地址（16MB）
    unsigned long output_len,
    unsigned long run_size
) {
    // 1. 初始化
    initialize_identity_maps();  // 确保页表有效

    // 2. 解压（使用 gzip/bzip2/lzma/xz 等）
    __decompress(
        input_data,     // 压缩数据起始地址
        input_len,      // 压缩数据长度
        NULL,           // 输入函数（NULL=直接内存）
        NULL,           // 填充函数
        output,         // 输出缓冲区（16MB）
        output_len,     // 输出缓冲区大小
        NULL,           // 错误处理
        error           // 错误回调
    );

    // 3. 返回解压后内核的入口地址
    return output;
}
```

**关键点**：

- 解压期间页表必须有效（Identity Mapping）
- 解压后跳转到主内核的 startup_64（不同于压缩内核的 startup_64）

---

## 阶段 ④：主内核阶段

主内核（Main Kernel）建立完整的内存管理体系，包括最终的 GDT 和动态页表。

### 主内核的 GDT 演化

主内核的 GDT 经历两次演化：

**4.1 早期 GDT（early_gdt_descr）**

**位置**：`arch/x86/kernel/head_64.S`

```asm
# 早期 GDT 描述符
SYM_DATA_START_LOCAL(early_gdt_descr)
    .word   GDT_ENTRIES*8-1
SYM_DATA_END_LABEL(early_gdt_descr, SYM_L_LOCAL, early_gdt_descr_base)
SYM_DATA_START_LOCAL(early_gdt_descr_base)
    .quad   INIT_PER_CPU_VAR(gdt_page)
SYM_DATA_END(early_gdt_descr_base)
```

**加载时机**：`startup_64_setup_gdt_idt()`（arch/x86/boot/startup/gdt_idt.c）

```c
void __head startup_64_setup_gdt_idt(void) {
    struct gdt_page *gp = rip_rel_ptr((void *)&gdt_page);
    struct desc_ptr startup_gdt_descr = {
        .address = (unsigned long)gp->gdt,
        .size = GDT_SIZE - 1
    };
    native_load_gdt(&startup_gdt_descr);  // lgdt

    // 重载段寄存器
    asm volatile("movl %%eax, %%ds\n"
                 "movl %%eax, %%ss\n"
                 "movl %%eax, %%es\n" : : "a"(__KERNEL_DS) : "memory");
}
```

**GDT 内容**（arch/x86/kernel/cpu/common.c）：

```c
DEFINE_PER_CPU_PAGE_ALIGNED(struct gdt_page, gdt_page) = { .gdt = {
    [GDT_ENTRY_KERNEL32_CS] = GDT_ENTRY_INIT(DESC_CODE32, 0, 0xfffff),
    [GDT_ENTRY_KERNEL_CS]   = GDT_ENTRY_INIT(DESC_CODE64, 0, 0xfffff),
    [GDT_ENTRY_KERNEL_DS]   = GDT_ENTRY_INIT(DESC_DATA64, 0, 0xfffff),
    [GDT_ENTRY_DEFAULT_USER32_CS] = GDT_ENTRY_INIT(DESC_CODE32|DESC_USER, 0, 0xfffff),
    [GDT_ENTRY_DEFAULT_USER_DS]   = GDT_ENTRY_INIT(DESC_DATA64|DESC_USER, 0, 0xfffff),
    [GDT_ENTRY_DEFAULT_USER_CS]   = GDT_ENTRY_INIT(DESC_CODE64|DESC_USER, 0, 0xfffff),
}};
```

**4.2 Per-CPU GDT**

**加载时机**：`cpu_init()`（arch/x86/kernel/cpu/common.c）

```c
void cpu_init(void) {
    int cpu = smp_processor_id();
    struct tss_struct *tss = &per_cpu(cpu_tss_rw, cpu);

    // 加载 Per-CPU GDT
    load_direct_gdt(cpu);

    // 设置 TSS
    set_tss_desc(cpu, &get_cpu_entry_area(cpu)->tss);
    load_TR_desc();

    // 设置其他 Per-CPU 数据
    ...
}
```

**为什么需要 Per-CPU GDT？**

```
原因：
1. TSS 独立性：每个 CPU 需要独立的 TSS（存储内核栈指针）
2. 避免竞态：多个 CPU 同时修改共享 GDT 会导致竞态条件
3. 热插拔支持：CPU 热插拔时需要动态分配/释放 GDT

早期 GDT（全局共享）：
CPU0 ──┐
CPU1 ──┼──→ gdt_page（共享）
CPU2 ──┘

Per-CPU GDT（独立）：
CPU0 ──→ gdt_page_cpu0
CPU1 ──→ gdt_page_cpu1
CPU2 ──→ gdt_page_cpu2
```

### 主内核的页表建立

主内核的页表建立经历多个阶段：

**4.3 早期页表（early_top_pgt）**

**位置**：`arch/x86/kernel/head_64.S`

```asm
# 早期页表（静态定义）
.section ".init.data", "aw"
.balign 4096
SYM_DATA(early_top_pgt, .fill 512, 8, 0)
SYM_DATA(early_dynamic_pgts, .fill 512*EARLY_DYNAMIC_PAGE_TABLES, 8, 0)
```

**建立时机**：`x86_64_start_kernel()`（arch/x86/kernel/head64.c）

```c
asmlinkage __visible void __init x86_64_start_kernel(char *real_mode_data) {
    // 重置早期页表
    reset_early_page_tables();

    // 清零 BSS
    clear_bss();

    // 设置早期 IDT
    idt_setup_early_handler();

    // 继续启动
    x86_64_start_reservations(real_mode_data);
}

void __init reset_early_page_tables(void) {
    // 清零早期页表
    memset(early_top_pgt, 0, sizeof(early_top_pgt));
    memset(early_dynamic_pgts, 0, sizeof(early_dynamic_pgts));

    // 建立 Identity Mapping 和 Direct Mapping
    __early_make_pgtable(...);
}
```

**4.4 完整页表建立（init_mem_mapping）**

**位置**：`arch/x86/mm/init.c`

```c
// setup_arch() → init_mem_mapping()
void __init init_mem_mapping(void) {
    unsigned long end = max_pfn << PAGE_SHIFT;

    // 1. 初始化内存范围
    probe_page_size_mask();

    // 2. 映射所有物理内存到内核空间
    //    物理 0 → 虚拟 __PAGE_OFFSET（0xFFFF888000000000）
    memory_map_top_down(ISA_END_ADDRESS, end);

    // 3. 加载新的页表
    load_cr3(swapper_pg_dir);
    __flush_tlb_all();
}
```

**Direct Mapping 布局**：

```
内核虚拟地址空间布局（x86-64）：

0x0000000000000000   用户空间开始
    ...              用户空间（0-128TB）
0x00007FFFFFFFFFFF   用户空间结束
                     ↓ Canonical Address Hole（禁止访问）
0xFFFF800000000000   内核空间开始
    ...              内核代码/数据
0xFFFF888000000000   Direct Mapping 开始 ← PAGE_OFFSET
    ...              所有物理内存直接映射
0xFFFFC87FFFFFFFFF   Direct Mapping 结束
    ...              vmalloc/ioremap 区域
0xFFFFFFFFFFFFFFFF   内核空间结束

Direct Mapping 示例：
物理地址 0x00000000 → 虚拟地址 0xFFFF888000000000
物理地址 0x10000000 → 虚拟地址 0xFFFF888010000000
物理地址 0xBFFFFFFF → 虚拟地址 0xFFFF8880BFFFFFFF
```

### 内存管理子系统初始化

**4.5 E820 → memblock**

**位置**：`arch/x86/kernel/setup.c:setup_arch()`

```c
void __init setup_arch(char **cmdline_p) {
    // 1. 解析 E820 内存映射
    e820__memory_setup();

    // 2. 初始化 memblock
    e820__memblock_setup();

    // 3. 建立完整页表
    init_mem_mapping();

    // 4. 初始化 NUMA
    x86_numa_init();

    // 5. 其他初始化
    ...
}
```

**4.6 memblock → buddy allocator**

**位置**：`init/main.c:start_kernel()`

```c
asmlinkage __visible void __init start_kernel(void) {
    ...
    setup_arch(&command_line);
    ...
    mm_core_init();  // 初始化内存管理核心
    ...
}

// mm/mm_init.c
void __init mm_core_init(void) {
    // 1. 初始化页分配器
    page_alloc_init();

    // 2. 从 memblock 转换到 buddy
    memblock_free_all();

    // 3. 初始化 Slab/SLUB
    kmem_cache_init();

    // 4. 初始化 vmalloc
    vmalloc_init();
}
```

**内存管理演化总结**：

```
BIOS E820
    ↓
memblock（早期内存分配器，固定大小数组）
    ↓
buddy allocator（运行时页分配器，伙伴系统）
    ↓
Slab/SLUB（小对象分配器）
    ↓
kmalloc/vmalloc（内核 API）
    ↓
malloc/mmap（用户空间 API）
```

---

## 总结：四阶段演化对比

| 阶段 | GDT | GDT 来源 | 页表 | 页表来源 | 地址映射 | 主要目的 |
|------|-----|---------|------|---------|---------|---------|
| **BIOS** | 无 | - | 无 | - | 直接物理地址 | BIOS 服务 |
| **GRUB** | GRUB GDT | relocator.c | GRUB 页表 | startup.S | Identity (0-4GB) | 加载内核 |
| **压缩内核** | 临时 GDT | compressed/head_64.S::gdt | 早期页表 | compressed/head_64.S::pgtable | Identity (0-4GB) | 解压主内核 |
| **主内核早期** | early GDT | cpu/common.c::gdt_page | early_top_pgt | head_64.S | Identity + Direct | 启动过渡 |
| **主内核运行** | Per-CPU GDT | Per-CPU gdt_page | swapper_pg_dir | mm/init.c | Direct Mapping | 完整内存管理 |

**关键演化点**：

1. **GDT 简化**：从 BIOS 无 GDT → GRUB 临时 GDT → 压缩内核精简 GDT → 主内核完整 GDT → Per-CPU GDT
2. **页表扩展**：从 BIOS 无分页 → GRUB Identity Mapping → 压缩内核 Identity Mapping → 主内核 Direct Mapping
3. **地址映射转换**：从物理地址 → Identity Mapping（虚拟=物理）→ Direct Mapping（内核高地址）
4. **内存分配器演化**：无 → E820 → memblock → buddy → Slab/SLUB

---

## 深入阅读

- **[理论篇](X86_MEMORY_MANAGEMENT_THEORY.md)**：理解 GDT 和分页的硬件原理
- **[实现篇](LINUX_MEMORY_MANAGEMENT_CODE_GUIDE.md)**：深入源代码实现细节
- **[Linux 内核启动](LINUX_KERNEL_INIT.md)**：查看完整的启动流程

---

**文档版本**：v1.0
**最后更新**：2026-02
**维护者**：Linux 内核文档项目
