# Linux 内存管理代码实现：源代码详解与实战调试

> **文档定位**：本文档深入Linux源代码，详细分析GDT和页表的具体实现，并提供实战调试方法。

## 文档导航

- **[理论篇](X86_MEMORY_MANAGEMENT_THEORY.md)**：硬件机制与概念
- **[演化篇](LINUX_MEMORY_MANAGEMENT_EVOLUTION.md)**：从 BIOS 到 Linux 内核的过渡
- **实现篇**（本文档）：源代码详解与实战调试

---

## 第一部分：GDT 代码详解

### 1.1 gdt_page 结构定义

**位置**：`arch/x86/include/asm/desc.h:44-46`

```c
struct gdt_page {
    struct desc_struct gdt[GDT_ENTRIES];
} __attribute__((aligned(PAGE_SIZE)));

DECLARE_PER_CPU_PAGE_ALIGNED(struct gdt_page, gdt_page);
```

**段描述符结构**：`arch/x86/include/asm/desc_defs.h:15-22`

```c
struct desc_struct {
    u16 limit0;      // Limit [15:0]
    u16 base0;       // Base [15:0]
    u16 base1: 8,    // Base [23:16]
        type: 4,     // Segment type
        s: 1,        // Descriptor type (0=system, 1=code/data)
        dpl: 2,      // Descriptor privilege level
        p: 1;        // Present
    u16 limit1: 4,   // Limit [19:16]
        avl: 1,      // Available for software
        l: 1,        // Long mode (64-bit code segment)
        d: 1,        // Default operation size
        g: 1,        // Granularity
        base2: 8;    // Base [31:24]
} __attribute__((packed));
```

### 1.2 GDT 初始化

**位置**：`arch/x86/kernel/cpu/common.c:201-244`

```c
DEFINE_PER_CPU_PAGE_ALIGNED(struct gdt_page, gdt_page) = { .gdt = {
#ifdef CONFIG_X86_64
    /*
     * We need valid kernel segments for data and code in long mode too
     * IRET will check the segment types  kkeil 2000/10/28
     * Also sysret mandates a special GDT layout
     *
     * TLS descriptors are currently at a different place compared to i386.
     * Hopefully nobody expects them at a fixed place (Wine?)
     */
    [GDT_ENTRY_KERNEL32_CS]      = GDT_ENTRY_INIT(DESC_CODE32, 0, 0xfffff),
    [GDT_ENTRY_KERNEL_CS]        = GDT_ENTRY_INIT(DESC_CODE64, 0, 0xfffff),
    [GDT_ENTRY_KERNEL_DS]        = GDT_ENTRY_INIT(DESC_DATA64, 0, 0xfffff),
    [GDT_ENTRY_DEFAULT_USER32_CS]= GDT_ENTRY_INIT(DESC_CODE32 | DESC_USER, 0, 0xfffff),
    [GDT_ENTRY_DEFAULT_USER_DS]  = GDT_ENTRY_INIT(DESC_DATA64 | DESC_USER, 0, 0xfffff),
    [GDT_ENTRY_DEFAULT_USER_CS]  = GDT_ENTRY_INIT(DESC_CODE64 | DESC_USER, 0, 0xfffff),
#endif
} };
EXPORT_PER_CPU_SYMBOL_GPL(gdt_page);
```

**GDT_ENTRY_INIT 宏展开**：

```c
#define GDT_ENTRY_INIT(flags, base, limit) \
    {                                      \
        .limit0 = (u16) (limit),           \
        .limit1 = ((limit) >> 16) & 0x0F,  \
        .base0 = (u16) (base),             \
        .base1 = ((base) >> 16) & 0xFF,    \
        .base2 = ((base) >> 24) & 0xFF,    \
        .type = (flags & 0x0f),            \
        .s = (flags >> 4) & 0x01,          \
        .dpl = (flags >> 5) & 0x03,        \
        .p = (flags >> 7) & 0x01,          \
        .avl = (flags >> 12) & 0x01,       \
        .l = (flags >> 13) & 0x01,         \
        .d = (flags >> 14) & 0x01,         \
        .g = (flags >> 15) & 0x01,         \
    }
```

### 1.3 startup_64_setup_gdt_idt() 实现

**位置**：`arch/x86/boot/startup/gdt_idt.c:49-70`

```c
void __head startup_64_setup_gdt_idt(void)
{
    // 1. 获取 gdt_page 地址（使用 RIP 相对寻址）
    struct gdt_page *gp = rip_rel_ptr((void *)&gdt_page);

    // 2. 构建 GDT 描述符
    struct desc_ptr startup_gdt_descr = {
        .address = (unsigned long)gp->gdt,
        .size = GDT_SIZE - 1
    };

    // 3. 加载 GDT
    native_load_gdt(&startup_gdt_descr);

    // 4. 重载段寄存器
    asm volatile("movl %%eax, %%ds\n"
                 "movl %%eax, %%ss\n"
                 "movl %%eax, %%es\n"
                 : : "a"(__KERNEL_DS) : "memory");

    // 5. 加载 IDT（如果需要 AMD SEV 支持）
    void *handler = IS_ENABLED(CONFIG_AMD_MEM_ENCRYPT) ?
                    rip_rel_ptr(vc_no_ghcb) : NULL;
    startup_64_load_idt(handler);
}
```

**native_load_gdt() 实现**：`arch/x86/include/asm/desc.h`

```c
static inline void native_load_gdt(const struct desc_ptr *dtr)
{
    asm volatile("lgdt %0"::"m" (*dtr));
}
```

### 1.4 Per-CPU GDT 加载

**位置**：`arch/x86/kernel/cpu/common.c`

```c
void load_direct_gdt(int cpu)
{
    struct desc_ptr gdt_descr;

    gdt_descr.address = (long)get_cpu_gdt_rw(cpu);
    gdt_descr.size = GDT_SIZE - 1;
    load_gdt(&gdt_descr);
}

// 在 cpu_init() 中调用
void cpu_init(void)
{
    int cpu = smp_processor_id();
    struct task_struct *cur = current;
    struct tss_struct *tss = &per_cpu(cpu_tss_rw, cpu);

    // 加载 Per-CPU GDT
    load_direct_gdt(cpu);

    // 设置 TSS
    set_tss_desc(cpu, &get_cpu_entry_area(cpu)->tss);
    load_TR_desc();

    // 设置内核栈
    load_sp0((unsigned long)(cpu_entry_stack(cpu) + 1));

    // 其他初始化...
}
```

---

## 第二部分：页表代码详解

### 2.1 压缩内核页表建立

**位置**：`arch/x86/boot/compressed/head_64.S`

**startup_32 中建立 4 级页表**：

```asm
SYM_FUNC_START(startup_32)
    # ... 前面的代码 ...

    # 1. 计算页表位置（使用 RIP 相对寻址）
    leal    rva(pgtable)(%ebx), %edi

    # 2. 清零页表区域（6 页）
    xorl    %eax, %eax
    movl    $(BOOT_PGT_SIZE >> 2), %ecx
    rep     stosl

    # 3. 设置 PML4 → PDPT
    leal    rva(pgtable)(%ebx), %edi     # EDI = PML4 基址
    leal    0x1000(%edi), %eax            # EAX = PDPT 基址
    orl     $0x03, %eax                   # Present + R/W
    movl    %eax, 0(%edi)                 # PML4[0] = PDPT

    # 4. 设置 PDPT → PD（4 个条目，映射 4GB）
    leal    0x1000(%edi), %edi            # EDI = PDPT 基址
    leal    0x1000(%edi), %eax            # EAX = 第一个 PD 基址
    orl     $0x03, %eax                   # Present + R/W
    movl    $4, %ecx                      # 4 个 PDPT 条目
1:  movl    %eax, 0(%edi)                 # PDPT[i] = PD
    addl    $0x1000, %eax                 # 下一个 PD
    addl    $8, %edi                      # 下一个 PDPT 条目
    decl    %ecx
    jnz     1b

    # 5. 设置 PD（使用 2MB 大页）
    leal    rva(pgtable)(%ebx), %edi
    addl    $0x2000, %edi                 # EDI = 第一个 PD 基址
    movl    $0x00000083, %eax             # 物理地址 0 + Present + R/W + PS
    movl    $2048, %ecx                   # 2048 个 PD 条目（4GB / 2MB）
1:  movl    %eax, 0(%edi)                 # PD[i] = 物理地址
    addl    $0x200000, %eax               # 下一个 2MB 页
    addl    $8, %edi                      # 下一个 PD 条目
    decl    %ecx
    jnz     1b

    # 6. 加载 CR3
    leal    rva(pgtable)(%ebx), %eax
    movl    %eax, %cr3

    # ... 后面的代码（启用分页）...
SYM_FUNC_END(startup_32)
```

### 2.2 主内核early页表

**位置**：`arch/x86/kernel/head_64.S`

```asm
# 早期页表定义
.section ".init.data", "aw"
.balign 4096
SYM_DATA(early_top_pgt, .fill 512, 8, 0)

# 动态页表（启动时分配）
SYM_DATA(early_dynamic_pgts, .fill 512*EARLY_DYNAMIC_PAGE_TABLES, 8, 0)
```

**x86_64_start_kernel() 中重置页表**：`arch/x86/kernel/head64.c`

```c
asmlinkage __visible void __init x86_64_start_kernel(char *real_mode_data)
{
    // 1. 重置早期页表
    reset_early_page_tables();

    // 2. 清零 BSS
    clear_bss();

    // 3. 清零页表（防止未初始化内存）
    clear_page(init_top_pgt);

    // 4. 设置早期 IDT
    idt_setup_early_handler();

    // 5. 拷贝 boot_params
    copy_bootdata(__va(real_mode_data));

    // 6. 加载微码
    load_ucode_bsp();

    // 7. 建立内核高地址映射
    init_top_pgt[511] = early_top_pgt[511];

    // 8. 继续启动
    x86_64_start_reservations(real_mode_data);
}
```

**reset_early_page_tables() 实现**：`arch/x86/kernel/head64.c`

```c
void __head reset_early_page_tables(void)
{
    // 清零 PML4
    memset(early_top_pgt, 0, sizeof(early_top_pgt));
    memset(early_dynamic_pgts, 0, sizeof(early_dynamic_pgts));

    // 重新设置 Identity Mapping 和 Direct Mapping
    next_early_pgt = 0;

    // 写入 CR3（加载新页表）
    write_cr3(__sme_pa_nodebug(early_top_pgt));
}
```

### 2.3 init_mem_mapping() 完整页表建立

**位置**：`arch/x86/mm/init.c:758`

```c
void __init init_mem_mapping(void)
{
    unsigned long end;

    // 1. 探测页大小（4KB / 2MB / 1GB）
    probe_page_size_mask();

    // 2. 设置 KASLR（如果启用）
    setup_arch_memory_layout();

    // 3. 计算最大物理地址
    end = max_pfn << PAGE_SHIFT;

    // 4. 映射所有物理内存（从高地址到低地址）
    //    避免覆盖低地址的重要数据
    memory_map_top_down(ISA_END_ADDRESS, end);

    // 5. 映射低端内存（ISA 设备需要）
    if (max_pfn > ISA_END_ADDRESS >> PAGE_SHIFT)
        memory_map_bottom_up(0, ISA_END_ADDRESS);

    // 6. 加载新的页表
    load_cr3(swapper_pg_dir);
    __flush_tlb_all();

    // 7. 初始化内存映射区域
    early_memremap_init();
}
```

**memory_map_top_down() 实现**：

```c
static void __init memory_map_top_down(unsigned long map_start,
                                       unsigned long map_end)
{
    unsigned long real_end, start, last_start;
    unsigned long step_size;
    unsigned long addr;
    unsigned long mapped_ram_size = 0;

    // 设置步长（2MB 或 1GB）
    step_size = PMD_SIZE;
    max_pfn_mapped = 0;

    // 从高地址向低地址映射
    real_end = map_end;
    addr = real_end - step_size;
    real_end = addr + step_size;

    while (last_start > map_start) {
        // 调用 kernel_physical_mapping_init() 建立映射
        init_range_memory_mapping(start, last_start);
        last_start = start;
        start -= step_size;

        // 检查是否完成
        if (start < map_start)
            start = map_start;
    }
}
```

**kernel_physical_mapping_init() 核心函数**：`arch/x86/mm/init_64.c`

```c
unsigned long __meminit
kernel_physical_mapping_init(unsigned long paddr_start,
                             unsigned long paddr_end,
                             unsigned long page_size_mask)
{
    unsigned long vaddr, vaddr_start, vaddr_end, vaddr_next;
    unsigned long paddr_last = paddr_end;
    pgd_t *pgd;
    p4d_t *p4d;
    pud_t *pud;
    pmd_t *pmd;
    pte_t *pte;

    // 计算虚拟地址范围
    vaddr = (unsigned long)__va(paddr_start);
    vaddr_end = (unsigned long)__va(paddr_end);
    vaddr_start = vaddr;

    // 遍历地址范围
    for (; vaddr < vaddr_end; vaddr = vaddr_next) {
        // 1. 获取 PGD 条目
        pgd = pgd_offset_k(vaddr);
        if (pgd_none(*pgd)) {
            // 分配新的 P4D 页
            p4d = (p4d_t *)alloc_low_page();
            set_pgd(pgd, __pgd(__pa(p4d) | _KERNPG_TABLE));
        }

        // 2. 获取 P4D 条目
        p4d = p4d_offset(pgd, vaddr);
        if (p4d_none(*p4d)) {
            // 分配新的 PUD 页
            pud = (pud_t *)alloc_low_page();
            set_p4d(p4d, __p4d(__pa(pud) | _KERNPG_TABLE));
        }

        // 3. 获取 PUD 条目
        pud = pud_offset(p4d, vaddr);
        if (page_size_mask & (1 << PG_LEVEL_1G)) {
            // 使用 1GB 大页
            set_pud(pud, __pud(paddr | _PAGE_PSE | _KERNPG_TABLE));
            vaddr_next = (vaddr & PUD_MASK) + PUD_SIZE;
            continue;
        }

        if (pud_none(*pud)) {
            // 分配新的 PMD 页
            pmd = (pmd_t *)alloc_low_page();
            set_pud(pud, __pud(__pa(pmd) | _KERNPG_TABLE));
        }

        // 4. 获取 PMD 条目
        pmd = pmd_offset(pud, vaddr);
        if (page_size_mask & (1 << PG_LEVEL_2M)) {
            // 使用 2MB 大页
            set_pmd(pmd, __pmd(paddr | _PAGE_PSE | _KERNPG_TABLE));
            vaddr_next = (vaddr & PMD_MASK) + PMD_SIZE;
            continue;
        }

        // 5. 使用 4KB 小页
        if (pmd_none(*pmd)) {
            // 分配新的 PTE 页
            pte = (pte_t *)alloc_low_page();
            set_pmd(pmd, __pmd(__pa(pte) | _KERNPG_TABLE));
        }
        pte = pte_offset_kernel(pmd, vaddr);
        set_pte(pte, __pte(paddr | _KERNPG_TABLE));
        vaddr_next = (vaddr & PAGE_MASK) + PAGE_SIZE;
    }

    return paddr_last;
}
```

---

## 第三部分：内存管理子系统

### 3.1 E820 处理

**位置**：`arch/x86/kernel/e820.c`

```c
// 解析 E820 内存映射
void __init e820__memory_setup(void)
{
    char *who = "BIOS-e820";

    // 从 boot_params 读取 E820 表
    e820__memory_setup_default();

    // 打印 E820 信息
    e820__print_table(who);
}

// 将 E820 转换为 memblock
void __init e820__memblock_setup(void)
{
    int i;
    struct e820_entry *entry = e820_table->entries;

    // 遍历 E820 表
    for (i = 0; i < e820_table->nr_entries; i++, entry++) {
        u64 start = entry->addr;
        u64 end = start + entry->size;

        // 如果是可用内存，添加到 memblock
        if (entry->type != E820_TYPE_RAM &&
            entry->type != E820_TYPE_RESERVED_KERN)
            continue;

        memblock_add(start, entry->size);
    }

    // 标记保留区域
    e820__reserve_setup_data();
}
```

### 3.2 memblock 实现

**位置**：`mm/memblock.c`

```c
// memblock 结构
struct memblock {
    bool bottom_up;  // 从低地址还是高地址分配
    phys_addr_t current_limit;
    struct memblock_type memory;    // 可用内存
    struct memblock_type reserved;  // 已保留内存
};

// 添加内存区域
int __init_memblock memblock_add(phys_addr_t base, phys_addr_t size)
{
    phys_addr_t end = base + size - 1;

    memblock_dbg("%s: [%pa-%pa] %pS\n", __func__,
                 &base, &end, (void *)_RET_IP_);

    return memblock_add_range(&memblock.memory, base, size, MAX_NUMNODES, 0);
}

// 分配内存
phys_addr_t __init memblock_alloc_range(phys_addr_t size, phys_addr_t align,
                                        phys_addr_t start, phys_addr_t end)
{
    phys_addr_t found;

    if (!align)
        align = SMP_CACHE_BYTES;

    // 从 memblock 中找到合适的区域
    found = memblock_find_in_range(start, end, size, align);
    if (!found)
        return 0;

    // 标记为已使用
    memblock_reserve(found, size);

    return found;
}
```

### 3.3 buddy allocator 实现

**位置**：`mm/page_alloc.c`

```c
// 从 memblock 转换到 buddy
void __init memblock_free_all(void)
{
    unsigned long pages;

    // 重置 memblock 分配器
    reset_all_zones_managed_pages();

    // 释放所有页到 buddy allocator
    pages = free_low_memory_core_early();

    totalram_pages_add(pages);
}

// 分配页（buddy allocator 核心函数）
struct page *__alloc_pages_nodemask(gfp_t gfp_mask, unsigned int order,
                                    int preferred_nid,
                                    nodemask_t *nodemask)
{
    struct page *page;
    unsigned int alloc_flags = ALLOC_WMARK_LOW;
    gfp_t alloc_mask;
    struct alloc_context ac = { };

    // 准备分配上下文
    prepare_alloc_pages(gfp_mask, order, preferred_nid, nodemask,
                       &ac, &alloc_mask, &alloc_flags);

    // 快速路径：从 Per-CPU 页缓存分配
    page = get_page_from_freelist(alloc_mask, order, alloc_flags, &ac);
    if (likely(page))
        goto out;

    // 慢速路径：从伙伴系统分配
    alloc_mask = current_gfp_context(gfp_mask);
    page = __alloc_pages_slowpath(alloc_mask, order, &ac);

out:
    return page;
}
```

---

## 第四部分：实战调试

### 4.1 使用 GDB 查看 GDT

**启动 QEMU + GDB**：

```bash
# 启动 QEMU（暂停在启动前）
qemu-system-x86_64 -kernel vmlinuz -S -s

# 在另一个终端启动 GDB
gdb vmlinux
(gdb) target remote :1234
(gdb) break startup_64_setup_gdt_idt
(gdb) continue
```

**查看 GDTR 寄存器**：

```gdb
# 读取 GDTR
(gdb) info registers gdtr
gdtr           {base=0xffffffff82f2d000, limit=0x7f}

# 查看 GDT 内容
(gdb) x/10gx 0xffffffff82f2d000
0xffffffff82f2d000:  0x0000000000000000  0x00cf9a000000ffff
0xffffffff82f2d010:  0x00af9a000000ffff  0x00cf92000000ffff
0xffffffff82f2d020:  0x00cffb000000ffff  0x00cff2000000ffff
0xffffffff82f2d030:  0x00affa000000ffff  0x0000000000000000
0xffffffff82f2d040:  0x0000000000000000  0x0000000000000000

# 解析段描述符
(gdb) set $gdt = 0xffffffff82f2d000
(gdb) printf "KERNEL_CS: %#lx\n", *((unsigned long*)($gdt + 2*8))
KERNEL_CS: 0x00af9a000000ffff

# 查看当前 CS
(gdb) info registers cs
cs             0x10  16
# CS = 0x10 = 段选择子（索引2, TI=0, RPL=0）→ GDT[2] = KERNEL_CS
```

### 4.2 使用 GDB 查看页表

**查看 CR3**：

```gdb
# 读取 CR3（页表基址）
(gdb) info registers cr3
cr3            0x102e000  16961536

# CR3 指向 PML4 表
(gdb) set $pml4 = 0x102e000

# 查看 PML4 条目
(gdb) x/512gx $pml4
# 找到非零条目
(gdb) x/gx $pml4
0x102e000:  0x0000000000a04067

# 解析 PML4[0]
# 物理地址：0x0000000000a04000
# 标志位：0x067 = Present(1) + R/W(1) + U/S(1) + Accessed(1)
```

**遍历页表（虚拟地址 0xFFFF888000000000）**：

```gdb
# 1. 拆分虚拟地址
# 0xFFFF888000000000
# PML4 index = (0xFFFF888000000000 >> 39) & 0x1FF = 0x111 = 273
# PDPT index = (0xFFFF888000000000 >> 30) & 0x1FF = 0x020 = 32
# PD index = 0
# PT index = 0

# 2. 读取 PML4[273]
(gdb) x/gx ($pml4 + 273*8)
0x102e888:  0x0000000001025067

# 3. 读取 PDPT[32]
(gdb) set $pdpt = 0x1025000
(gdb) x/gx ($pdpt + 32*8)
0x1025100:  0x0000000001026067

# 4. 读取 PD[0]
(gdb) set $pd = 0x1026000
(gdb) x/gx $pd
0x1026000:  0x00000000000000e3

# 5. 解析 PD[0]（2MB 大页）
# 物理地址：0x00000000
# 标志位：0x0E3 = Present + R/W + PS(2MB页) + G(全局)
```

### 4.3 dmesg 内存信息分析

**E820 内存映射**：

```bash
$ dmesg | grep "BIOS-e820"
[    0.000000] BIOS-e820: [mem 0x0000000000000000-0x000000000009ffff] usable
[    0.000000] BIOS-e820: [mem 0x0000000000100000-0x00000000bffdffff] usable
[    0.000000] BIOS-e820: [mem 0x00000000bffe0000-0x00000000bfffffff] reserved
```

**memblock 信息**：

```bash
$ dmesg | grep "memblock"
[    0.000000] MEMBLOCK configuration:
[    0.000000]  memory size = 0xbfee0000 reserved size = 0x2234567
[    0.000000]  memory.cnt  = 0x2
[    0.000000]  memory[0x0]     [0x0000000000001000-0x000000000009efff], 0x000000000009e000 bytes flags: 0x0
[    0.000000]  memory[0x1]     [0x0000000000100000-0x00000000bffdffff], 0x00000000bfee0000 bytes flags: 0x0
```

**Direct Mapping 信息**：

```bash
$ dmesg | grep "Direct mapping"
[    0.000000] Direct mapping pfn 0x1000 - 0xc0000 (1MB - 3GB)
```

---

## 总结

本文档详细分析了 Linux 内核中 GDT 和页表的实现代码，包括：

1. **GDT 实现**：从数据结构定义到加载过程
2. **页表实现**：从早期页表到完整页表建立
3. **内存管理子系统**：E820、memblock、buddy allocator
4. **实战调试**：使用 GDB 和 dmesg 分析内存管理

**深入阅读**：
- **[理论篇](X86_MEMORY_MANAGEMENT_THEORY.md)**：理解硬件机制
- **[演化篇](LINUX_MEMORY_MANAGEMENT_EVOLUTION.md)**：了解演化过程
- **Linux 源代码**：`arch/x86/kernel/`, `arch/x86/mm/`, `mm/`

---

**文档版本**：v1.0
**最后更新**：2026-02
**维护者**：Linux 内核文档项目
