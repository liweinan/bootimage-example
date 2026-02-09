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

## 重要时间线：长模式和分页的激活顺序

**常见误解澄清**：

很多人误以为主内核的 `startup_64_setup_gdt_idt()` 执行时还未启用分页，或者还不在长模式。实际情况是：

```
❌ 错误理解：
   startup_64_setup_gdt_idt() 执行时 → 还在保护模式 → 分页未启用

✅ 正确理解：
   startup_64_setup_gdt_idt() 执行时 → 已在长模式 ✓ → 分页已启用 ✓
   使用的是压缩内核建立的临时页表（pgtable）
```

### 完整的时间线详解

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【时间点 1】压缩内核 startup_32（32位保护模式）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
位置：arch/x86/boot/compressed/head_64.S

SYM_FUNC_START(startup_32)
    # 当前状态：
    # - CPU模式：32位保护模式
    # - 分页状态：CR0.PG = 0（分页未启用）
    # - 使用：GRUB 的 GDT

    # ... 初始化代码 ...

    ┌─────────────────────────────────────────────────────┐
    │ 步骤 1：建立 4 级页表（pgtable，6 页 = 24KB）      │
    └─────────────────────────────────────────────────────┘

    # 计算页表位置
    leal    rva(pgtable)(%ebx), %edi

    # 清零 6 页
    xorl    %eax, %eax
    movl    $(BOOT_PGT_SIZE >> 2), %ecx
    rep     stosl

    # 设置 PML4[0] → PDPT
    leal    rva(pgtable)(%ebx), %edi
    leal    0x1000(%edi), %eax
    orl     $0x03, %eax
    movl    %eax, 0(%edi)

    # 设置 PDPT[0-3] → PD0-3（映射 4GB）
    leal    0x1000(%edi), %edi
    leal    0x1000(%edi), %eax
    orl     $0x03, %eax
    movl    $4, %ecx
1:  movl    %eax, 0(%edi)
    addl    $0x1000, %eax
    addl    $8, %edi
    decl    %ecx
    jnz     1b

    # 设置 PD（使用 2MB 大页）
    leal    rva(pgtable)(%ebx), %edi
    addl    $0x2000, %edi
    movl    $0x00000083, %eax     # Present + R/W + PS (2MB)
    movl    $2048, %ecx           # 2048 × 2MB = 4GB
1:  movl    %eax, 0(%edi)
    addl    $0x200000, %eax
    addl    $8, %edi
    decl    %ecx
    jnz     1b

    ✓ 页表建立完成
    ✓ 映射：Identity Mapping 0-4GB

    ┌─────────────────────────────────────────────────────┐
    │ 步骤 2：加载 CR3（页表基址寄存器）                  │
    └─────────────────────────────────────────────────────┘

    leal    rva(pgtable)(%ebx), %eax
    movl    %eax, %cr3            ← CR3 已设置

    状态更新：
    ✓ CR3 = pgtable 物理地址
    ✗ CR0.PG = 0（分页仍未启用）

    ┌─────────────────────────────────────────────────────┐
    │ 步骤 3：启用 PAE（物理地址扩展）                    │
    └─────────────────────────────────────────────────────┘

    movl    %cr4, %eax
    orl     $X86_CR4_PAE, %eax
    movl    %eax, %cr4

    状态更新：
    ✓ CR4.PAE = 1（必须，长模式要求）

    ┌─────────────────────────────────────────────────────┐
    │ 步骤 4：设置 EFER.LME = 1（Long Mode Enable）      │
    └─────────────────────────────────────────────────────┘

    movl    $MSR_EFER, %ecx
    rdmsr
    btsl    $_EFER_LME, %eax      # EFER.LME = 1
    wrmsr

    状态更新：
    ✓ EFER.LME = 1（长模式已使能，但未激活）
    ✗ EFER.LMA = 0（长模式尚未激活）

    ┌─────────────────────────────────────────────────────┐
    │ 步骤 5：启用分页 → 激活长模式！                     │
    └─────────────────────────────────────────────────────┘

    # 同时设置 PG（分页）和 PE（保护模式）
    movl    $(X86_CR0_PG | X86_CR0_PE), %eax
    movl    %eax, %cr0            ← 关键时刻！

    硬件自动操作：
    ✓ CR0.PG = 1（分页启用）
    ✓ EFER.LME=1 + CR0.PG=1 → EFER.LMA=1（长模式激活）
    ✓ CPU 从此在 IA-32e 模式（64位长模式）

    重要：从此刻起，分页一直启用，长模式一直激活！

    ┌─────────────────────────────────────────────────────┐
    │ 步骤 6：跳转到 64 位代码                             │
    └─────────────────────────────────────────────────────┘

    # 远跳转（加载 64 位代码段选择子到 CS）
    pushl   $__KERNEL_CS
    leal    startup_64(%ebp), %eax
    pushl   %eax
    lretq

    # 或者：
    ljmpl   $__KERNEL_CS, $(.Llong_mode)

.Llong_mode:
    # ← 从这里开始，已经在真正的 64 位长模式
    # ← CS.L = 1（64位代码段）
    # ← 默认操作数大小 = 64 位
    # ← 可以使用 64 位寄存器（RAX, RBX, ...）

SYM_FUNC_END(startup_32)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【时间点 2】压缩内核 startup_64（64位长模式）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
位置：arch/x86/boot/compressed/head_64.S

SYM_FUNC_START(startup_64)
    # 进入时的状态（从 startup_32 继承）：
    # ✓ CPU模式：64位长模式（EFER.LMA=1）
    # ✓ 分页状态：CR0.PG = 1（已启用）
    # ✓ 页表：pgtable（6页，Identity Mapping 0-4GB）
    # ✓ GDT：GRUB 或早期临时 GDT

    # 初始化段寄存器
    xorl    %eax, %eax
    movl    %eax, %ds
    movl    %eax, %es
    movl    %eax, %ss

    # ... 设置栈 ...

    # 解压内核
    call    extract_kernel

    # 跳转到主内核（解压后的内核）
    jmp     *%rax             # RAX = 主内核 startup_64 的地址

SYM_FUNC_END(startup_64)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【时间点 3】主内核 startup_64（64位长模式）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
位置：arch/x86/kernel/head_64.S

SYM_CODE_START(startup_64)
    # 进入时的状态（从压缩内核继承）：
    # ✓ CPU模式：64位长模式
    # ✓ 分页状态：CR0.PG = 1（仍然启用）
    # ✓ 页表：pgtable（压缩内核的临时页表）
    # ✓ GDT：压缩内核的临时 GDT

    # 清理段寄存器
    xorl    %eax, %eax
    movl    %eax, %ds
    movl    %eax, %es
    movl    %eax, %ss

    # 设置栈
    leaq    (__end_init_task - FRAME_SIZE)(%rip), %rsp

    # 清零 EFLAGS
    pushq   $0
    popfq

    ┌─────────────────────────────────────────────────────┐
    │ 关键调用：加载主内核的 GDT 和 IDT                   │
    └─────────────────────────────────────────────────────┘

    leaq    _text(%rip), %rdi
    call    startup_64_setup_gdt_idt  ← 就是这里！

    # 此时的状态（startup_64_setup_gdt_idt 执行时）：
    # ✓ CPU模式：64位长模式
    # ✓ EFER.LMA = 1
    # ✓ CR0.PG = 1（分页已启用，从步骤5开始就一直启用）
    # ✓ CR3 = pgtable（压缩内核的临时页表）
    # ✓ 页表内容：Identity Mapping 0-4GB（2MB大页）
    # ✗ 主内核的完整页表还未建立

    ┌─────────────────────────────────────────────────────┐
    │ startup_64_setup_gdt_idt() 函数内部                 │
    └─────────────────────────────────────────────────────┘

void __head startup_64_setup_gdt_idt(void)
{
    # 当前状态：
    # ✓ 长模式 ✓
    # ✓ 分页启用 ✓
    # ✓ 使用临时页表（pgtable）

    struct gdt_page *gp = rip_rel_ptr((void *)&gdt_page);
    struct desc_ptr startup_gdt_descr = {
        .address = (unsigned long)gp->gdt,
        .size = GDT_SIZE - 1
    };

    native_load_gdt(&startup_gdt_descr);  ← 你问的这里
    # ← 此时：长模式 ✓，分页 ✓，临时页表 ✓
    # ← lgdt 指令只改变 GDT，不影响分页状态
    # ← CR0.PG 仍然是 1
    # ← CR3 仍然指向 pgtable

    # 重载段寄存器
    asm volatile("movl %%eax, %%ds\n"
                 "movl %%eax, %%ss\n"
                 "movl %%eax, %%es\n"
                 : : "a"(__KERNEL_DS) : "memory");

    # 加载早期 IDT
    startup_64_load_idt(handler);
}

    ✓ GDT 已更新（从压缩内核的临时 GDT → 主内核的 gdt_page）
    ✓ 分页仍然启用（从未禁用过）
    ✓ 页表仍然是 pgtable（临时的）

    # 继续初始化
    # ...

SYM_CODE_END(startup_64)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【时间点 4】x86_64_start_kernel（C代码初始化）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
位置：arch/x86/kernel/head64.c

asmlinkage __visible void __init x86_64_start_kernel(char *real_mode_data)
{
    # 当前状态：
    # ✓ 长模式
    # ✓ 分页启用
    # ✓ GDT：gdt_page
    # ✓ 页表：pgtable（压缩内核的临时页表，仍在使用）

    # 重置早期页表（仍然是临时页表）
    reset_early_page_tables();

    # 清零 BSS
    clear_bss();

    # 清零早期页表
    clear_page(init_top_pgt);

    # ... 其他初始化 ...

    # 跳转到通用内核初始化
    x86_64_start_reservations(real_mode_data);
}

void __init x86_64_start_reservations(char *real_mode_data)
{
    # ...
    start_kernel();  ← 通用内核入口
}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【时间点 5】setup_arch() → init_mem_mapping()
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
位置：arch/x86/kernel/setup.c → arch/x86/mm/init.c

start_kernel()
    → setup_arch(&command_line)
        → init_mem_mapping()  ← 在这里才建立主内核的完整页表！

void __init init_mem_mapping(void)
{
    # 当前状态：
    # ✓ 长模式
    # ✓ 分页启用
    # ✓ 页表：pgtable（临时的，只映射 0-4GB）

    # 探测页大小（4KB/2MB/1GB）
    probe_page_size_mask();

    # 设置 KASLR（内核地址空间随机化）
    setup_arch_memory_layout();

    # 计算最大物理地址
    end = max_pfn << PAGE_SHIFT;

    # 映射所有物理内存（从高地址到低地址）
    memory_map_top_down(ISA_END_ADDRESS, end);

    # 映射低端内存（ISA 设备需要）
    if (max_pfn > ISA_END_ADDRESS >> PAGE_SHIFT)
        memory_map_bottom_up(0, ISA_END_ADDRESS);

    ┌─────────────────────────────────────────────────────┐
    │ 关键操作：切换到新的完整页表                        │
    └─────────────────────────────────────────────────────┘

    # 加载新的页表
    load_cr3(swapper_pg_dir);  ← 切换到主内核的完整页表
    __flush_tlb_all();

    ✓ 页表切换完成
    ✓ 从临时页表（pgtable，6页）→ 完整页表（swapper_pg_dir）
    ✓ 映射范围：0-4GB → 所有物理内存（可能数百GB）
    ✓ 支持：Direct Mapping、vmalloc、内核代码段映射等

    # 初始化内存映射区域
    early_memremap_init();
}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【最终状态】内核完全运行
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    # ✓ CPU模式：64位长模式
    # ✓ 分页状态：CR0.PG = 1（一直启用，从步骤5开始）
    # ✓ GDT：gdt_page（每个CPU一份）
    # ✓ 页表：swapper_pg_dir（完整的动态页表）
    # ✓ 地址映射：Direct Mapping（整个物理内存）
```

### 关键时间点总结

| 时间点 | 位置 | 长模式 | 分页 | 页表 | GDT |
|--------|------|--------|------|------|-----|
| **1** | 压缩内核 startup_32（开始） | ❌ 保护模式 | ❌ CR0.PG=0 | ❌ 无 | GRUB GDT |
| **2** | 压缩内核 startup_32（建表） | ❌ 保护模式 | ❌ CR0.PG=0 | ✅ pgtable（建立中） | GRUB GDT |
| **3** | 压缩内核 startup_32（CR3） | ❌ 保护模式 | ❌ CR0.PG=0 | ✅ pgtable（CR3已设） | GRUB GDT |
| **4** | 压缩内核 startup_32（EFER） | ⚠️ 已使能 | ❌ CR0.PG=0 | ✅ pgtable | GRUB GDT |
| **5** | 压缩内核 startup_32（PG=1） | ✅ **激活** | ✅ **启用** | ✅ pgtable | GRUB GDT |
| **6** | 压缩内核 startup_64 | ✅ 长模式 | ✅ CR0.PG=1 | ✅ pgtable | 临时 GDT |
| **7** | 主内核 startup_64 | ✅ 长模式 | ✅ CR0.PG=1 | ✅ pgtable | 临时 GDT |
| **8** | **startup_64_setup_gdt_idt()** | ✅ 长模式 | ✅ CR0.PG=1 | ✅ pgtable | **gdt_page** |
| **9** | x86_64_start_kernel() | ✅ 长模式 | ✅ CR0.PG=1 | ✅ pgtable | gdt_page |
| **10** | init_mem_mapping() | ✅ 长模式 | ✅ CR0.PG=1 | ✅ **swapper_pg_dir** | gdt_page |

**关键观察**：

1. **时间点 5 是分水岭**：从此刻起，长模式和分页一直保持启用
2. **startup_64_setup_gdt_idt() 在时间点 8**：此时长模式和分页都已启用
3. **页表演化**：pgtable（临时，6页）→ swapper_pg_dir（完整，动态）
4. **GDT 演化**：GRUB GDT → 临时 GDT → gdt_page（主内核）

### 临时页表 vs 完整页表对比

```
┌──────────────────────────────────────────────────────────────┐
│ 临时页表（pgtable）                                          │
├──────────────────────────────────────────────────────────────┤
│ 建立时机：压缩内核 startup_32                                │
│ 大小：    6 页（24KB）= 1 PML4 + 1 PDPT + 4 PD              │
│ 映射范围：0-4GB                                              │
│ 映射类型：Identity Mapping（虚拟地址 = 物理地址）           │
│ 页大小：  2MB 大页                                           │
│ 使用阶段：压缩内核 → 主内核早期（startup_64_setup_gdt_idt） │
│ 特点：    静态、预先计算、足够运行早期代码                   │
└──────────────────────────────────────────────────────────────┘
                              ↓
                   init_mem_mapping() 切换
                              ↓
┌──────────────────────────────────────────────────────────────┐
│ 完整页表（swapper_pg_dir）                                   │
├──────────────────────────────────────────────────────────────┤
│ 建立时机：init_mem_mapping()                                 │
│ 大小：    动态分配（可能数百KB）                             │
│ 映射范围：所有物理内存（可能数百GB）                         │
│ 映射类型：Direct Mapping + 内核代码映射 + vmalloc 等        │
│ 页大小：  混合（4KB + 2MB + 1GB）                           │
│ 使用阶段：内核完全运行                                       │
│ 特点：    动态、按需分配、完整的地址空间布局                 │
└──────────────────────────────────────────────────────────────┘
```

### 为什么长模式必须启用分页？

这是 Intel/AMD 架构的硬性规定：

```
【Intel SDM 规定】
进入 IA-32e 模式（64位长模式）的必要条件：
1. ✓ CR4.PAE = 1（启用物理地址扩展）
2. ✓ EFER.LME = 1（长模式使能）
3. ✓ CR0.PG = 1（分页启用）← 必须！

【违反的后果】
if (EFER.LME == 1 && CR0.PG == 0) {
    // 触发 #GP（General Protection Fault）
    // 系统无法启动
}

【在长模式下禁用分页】
不可能！长模式运行期间：
- CR0.PG 必须保持为 1
- 试图设置 CR0.PG = 0 → #GP 异常
- 长模式和分页是绑定的

【设计原因】
长模式设计为纯虚拟内存模式：
- 段基址强制为 0（扁平模式）
- 所有地址转换依赖分页机制
- 内存保护完全依赖页表权限位
- 不允许物理地址直接访问
```

### 验证方法

你可以在 GDB 中验证每个时间点的状态：

```gdb
# 在 startup_32 的 movl %eax, %cr0 之前设置断点
(gdb) break *startup_32 + 偏移
(gdb) p/x $cr0
$1 = 0x00000033    # Bit 31 (PG) = 0 → 分页未启用

# 单步执行 movl %eax, %cr0
(gdb) stepi
(gdb) p/x $cr0
$2 = 0x80050033    # Bit 31 (PG) = 1 → 分页已启用

# 检查 EFER 寄存器
(gdb) p/x $msr_efer
$3 = 0x500         # Bit 8 (LME)=1, Bit 10 (LMA)=1 → 长模式已激活

# 在 startup_64_setup_gdt_idt 设置断点
(gdb) break startup_64_setup_gdt_idt
(gdb) continue
(gdb) p/x $cr0
$4 = 0x80050033    # PG=1，分页仍然启用
(gdb) p/x $cr3
$5 = 0x102000      # 指向 pgtable（临时页表）

# 在 init_mem_mapping 的 load_cr3 设置断点
(gdb) break load_cr3
(gdb) continue
(gdb) p/x swapper_pg_dir
$6 = 0xffffffff82012000    # 新的页表地址
(gdb) continue
(gdb) p/x $cr3
$7 = 0x02012000    # CR3 已切换到新页表
```

### 常见误解纠正

| 误解 | 正确理解 |
|------|---------|
| ❌ "startup_64_setup_gdt_idt() 执行时还在保护模式" | ✅ 已经在长模式（从压缩内核就进入了） |
| ❌ "startup_64_setup_gdt_idt() 执行时分页未启用" | ✅ 分页已启用（CR0.PG=1，从压缩内核就启用了） |
| ❌ "主内核启动时才建立页表" | ✅ 压缩内核就建立了临时页表（pgtable） |
| ❌ "lgdt 会影响分页状态" | ✅ lgdt 只改变 GDT，不影响 CR0.PG 和 CR3 |
| ❌ "长模式可以不启用分页" | ✅ 长模式强制要求分页，无法禁用 |
| ❌ "只有一套页表" | ✅ 有两套：临时页表（pgtable）→ 完整页表（swapper_pg_dir） |

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

## 三套 GDT 详细对比：源代码级分析

### 为什么有三套 GDT？

在 Linux 内核启动过程中，GDT 经历了三次演化：

```
GRUB GDT → 压缩内核 boot_gdt → 主内核 gdt_page

【为什么不能一套 GDT 用到底？】

问题1：GRUB GDT 为什么不能继续用？
- GRUB GDT 在 GRUB 控制的内存区域
- 内核解压和加载会覆盖这块内存
- 不在内核控制范围内，不可靠

问题2：压缩内核 boot_gdt 为什么不能用到最后？
- boot_gdt 太简单：只有 3-4 个段描述符
- 缺少用户态段（USER_CS, USER_DS）
- 缺少 TSS（任务状态段）
- 不支持 Per-CPU（每个 CPU 需要独立的 GDT）
- 不支持系统调用（SYSCALL/SYSRET 需要特定布局）

问题3：为什么需要 Per-CPU GDT？
- 每个 CPU 需要独立的 TSS
- 每个 CPU 需要独立的内核栈
- 支持 SMP（对称多处理器）
```

### GDT 1：GRUB 的 GDT

**源代码位置**：`grub-core/lib/i386/relocator.c`（GRUB 源代码）

```c
/* GRUB 的 GDT 定义 */
static struct grub_relocator64_gdt_ent {
    grub_uint64_t entry;
} __attribute__ ((packed));

static struct grub_relocator64_gdt_ent grub_relocator_gdt[] = {
    /* GDT[0]: NULL 描述符 */
    { .entry = 0x0000000000000000ULL },

    /* GDT[1]: 32位代码段 */
    { .entry = 0x00CF9A000000FFFFULL },
    /*
     * 详细解析：
     * Base:  0x00000000 (段基址)
     * Limit: 0xFFFFF (段界限, 4GB)
     * G:     1 (粒度 4KB)
     * D:     1 (32位默认操作数)
     * L:     0 (不是64位段)
     * P:     1 (存在)
     * DPL:   0 (Ring 0)
     * S:     1 (代码/数据段)
     * Type:  0xA (1010, 代码段, 可执行, 可读)
     */

    /* GDT[2]: 32位数据段 */
    { .entry = 0x00CF92000000FFFFULL },
    /*
     * 详细解析：
     * Base:  0x00000000
     * Limit: 0xFFFFF (4GB)
     * G:     1 (粒度 4KB)
     * D:     1 (32位)
     * L:     0
     * P:     1
     * DPL:   0 (Ring 0)
     * S:     1
     * Type:  0x2 (0010, 数据段, 可读写)
     */

    /* GDT[3]: 64位代码段 */
    { .entry = 0x00AF9A000000FFFFULL },
    /*
     * 详细解析：
     * Base:  0x00000000
     * Limit: 0xFFFFF (在长模式下被忽略)
     * G:     1
     * D:     0 (64位段必须为0)
     * L:     1 ← 关键！标识64位代码段
     * P:     1
     * DPL:   0 (Ring 0)
     * S:     1
     * Type:  0xA (代码段, 可执行, 可读)
     */

    /* GDT[4]: 64位数据段 */
    { .entry = 0x00AF92000000FFFFULL },
    /*
     * 详细解析：
     * Base:  0x00000000
     * Limit: 0xFFFFF (被忽略)
     * G:     1
     * D:     0
     * L:     1 ← 64位数据段
     * P:     1
     * DPL:   0 (Ring 0)
     * S:     1
     * Type:  0x2 (数据段, 可读写)
     */
};

/* GRUB 加载 GDT */
static void
grub_relocator64_boot (struct grub_relocator64_state state)
{
    /* 设置 GDTR */
    struct {
        grub_uint16_t limit;
        grub_uint64_t base;
    } __attribute__ ((packed)) gdtr = {
        .limit = sizeof(grub_relocator_gdt) - 1,
        .base = (grub_uint64_t) grub_relocator_gdt
    };

    asm volatile ("lgdt %0" : : "m" (gdtr));

    /* 跳转到内核 */
    /* CS = GDT[3] (64位代码段) */
    /* DS/SS/ES = GDT[4] (64位数据段) */
}
```

**GRUB GDT 特点**：

```
段数量：5 个（NULL + 32位CS/DS + 64位CS/DS）
使用时期：GRUB → 压缩内核 startup_32 早期
段选择子：
  - 0x08: 32位代码段
  - 0x10: 32位数据段
  - 0x18: 64位代码段
  - 0x20: 64位数据段

优点：
✓ 支持从保护模式到长模式的过渡
✓ 同时有32位和64位段
✓ 扁平模式（Base=0）

缺点：
✗ 只有内核态段（DPL=0）
✗ 没有用户态段
✗ 没有 TSS
✗ 位于 GRUB 内存区域，不可靠
✗ 内核无法控制
```

### GDT 2：压缩内核的 boot_gdt

**源代码位置**：`arch/x86/boot/compressed/head_64.S`（Linux 内核源代码）

```asm
/*
 * 压缩内核的 GDT 定义
 * 位置：.rodata 段（只读数据）
 */
    .section ".rodata", "a"
    .balign 16
SYM_DATA_START_LOCAL(gdt64)
    /* GDTR 结构（10字节） */
    .word   gdt_end - gdt - 1           /* Limit: GDT大小 - 1 */
    .long   0                           /* Base低32位（运行时修正） */
    .word   0                           /* Base高16位 */

    /* GDT 表内容 */
SYM_DATA_START_LOCAL(gdt)
    /* GDT[0]: NULL 描述符 */
    .quad   0x0000000000000000

    /* GDT[1]: __KERNEL32_CS (32位代码段) */
    .quad   0x00cf9a000000ffff
    /*
     * 二进制详解：
     *   63    56 55  52 51   48 47     40 39  32
     *   00 cf 9a 00 00 00 ff ff
     *
     *   Base[31:24] = 0x00
     *   G  = 1 (4KB granularity)
     *   D  = 1 (32-bit)
     *   L  = 0 (not 64-bit) ← 关键
     *   AVL= 0
     *   Limit[19:16] = 0xF
     *   P  = 1 (Present)
     *   DPL= 0 (Ring 0)
     *   S  = 1 (code/data)
     *   Type = 0xA (1010, code, exec, read)
     *   Base[23:16] = 0x00
     *   Base[15:0]  = 0x0000
     *   Limit[15:0] = 0xFFFF
     *
     *   段基址 = 0x00000000
     *   段界限 = 0xFFFFF (4GB)
     *
     * 用途：在 startup_32 中使用，进入长模式前的代码段
     */

    /* GDT[2]: __KERNEL_CS (64位代码段) */
    .quad   0x00af9a000000ffff
    /*
     * 二进制详解：
     *   63    56 55  52 51   48 47     40 39  32
     *   00 af 9a 00 00 00 ff ff
     *
     *   Base[31:24] = 0x00
     *   G  = 1
     *   D  = 0 (must be 0 for 64-bit) ← 关键
     *   L  = 1 (64-bit code segment) ← 关键
     *   AVL= 0
     *   Limit[19:16] = 0xF (被忽略)
     *   P  = 1
     *   DPL= 0 (Ring 0)
     *   S  = 1
     *   Type = 0xA (code, exec, read)
     *   Base[23:16] = 0x00
     *   Base[15:0]  = 0x0000 (强制为0)
     *   Limit[15:0] = 0xFFFF (被忽略)
     *
     *   段基址 = 0x00000000 (长模式强制)
     *   段界限 = 被忽略
     *
     * 用途：进入长模式后的代码段
     *       压缩内核 startup_64 使用
     *       主内核 startup_64 使用（直到 startup_64_setup_gdt_idt）
     */

    /* GDT[3]: __KERNEL_DS (数据段) */
    .quad   0x00cf92000000ffff
    /*
     * 二进制详解：
     *   63    56 55  52 51   48 47     40 39  32
     *   00 cf 92 00 00 00 ff ff
     *
     *   Base[31:24] = 0x00
     *   G  = 1
     *   D  = 1
     *   L  = 0
     *   AVL= 0
     *   Limit[19:16] = 0xF
     *   P  = 1
     *   DPL= 0 (Ring 0)
     *   S  = 1
     *   Type = 0x2 (0010, data, read/write)
     *   Base[23:16] = 0x00
     *   Base[15:0]  = 0x0000
     *   Limit[15:0] = 0xFFFF
     *
     *   段基址 = 0x00000000
     *   段界限 = 0xFFFFF (4GB, 在长模式下被忽略)
     *
     * 用途：DS/SS/ES 数据段
     *       压缩内核和主内核早期使用
     */
SYM_DATA_END_LABEL(gdt, SYM_L_LOCAL, gdt_end)
SYM_DATA_END(gdt64)

/*
 * 在 startup_32 中加载 boot_gdt
 */
SYM_FUNC_START(startup_32)
    /* ... 前面的代码 ... */

    /*
     * 加载 GDT
     * 需要修正 GDT 基址（因为使用 RIP 相对寻址）
     */
    leal    rva(gdt)(%ebp), %eax        /* 计算 gdt 的物理地址 */
    movl    %eax, 2(%eax)               /* 修正 gdt64 结构中的 Base 字段 */
    lgdt    (%eax)                      /* 加载 GDTR */

    /* 重新加载段寄存器 */
    movl    $__KERNEL_DS, %eax          /* EAX = 0x18 (GDT[3]) */
    movl    %eax, %ds
    movl    %eax, %es
    movl    %eax, %ss

    /* ... 建立页表、进入长模式 ... */

    /*
     * 跳转到 64 位代码
     * CS 将被设置为 __KERNEL_CS (0x10, GDT[2])
     */
    pushl   $__KERNEL_CS
    leal    startup_64(%ebp), %eax
    pushl   %eax
    lretq                               /* 远返回，切换到 64 位 */

SYM_FUNC_END(startup_32)
```

**boot_gdt 特点**：

```
段数量：4 个（NULL + KERNEL32_CS + KERNEL_CS + KERNEL_DS）
使用时期：压缩内核 startup_32
         → 压缩内核 startup_64
         → 主内核 startup_64（直到 startup_64_setup_gdt_idt）
段选择子：
  - 0x08: 32位代码段（__KERNEL32_CS）
  - 0x10: 64位代码段（__KERNEL_CS）← 长模式使用
  - 0x18: 数据段（__KERNEL_DS）

设计特点：
✓ 极简设计：只有进入长模式必需的段
✓ 位于内核镜像内：随内核一起加载，可控
✓ 使用 RIP 相对寻址：位置无关
✓ 支持 32→64 位过渡

优点：
✓ 足够压缩内核运行
✓ 足够主内核早期初始化
✓ 静态定义，编译时确定
✓ 不依赖外部内存分配

缺点：
✗ 只有内核态段（DPL=0）
✗ 没有用户态段（无法运行用户进程）
✗ 没有 TSS（无法任务切换、系统调用）
✗ 不是 Per-CPU（不支持 SMP）
✗ 不满足 SYSCALL/SYSRET 的 GDT 布局要求
```

### GDT 3：主内核的 gdt_page

**源代码位置**：`arch/x86/kernel/cpu/common.c`（Linux 内核源代码）

```c
/*
 * 主内核的 GDT 定义
 * 这是完整的、Per-CPU 的 GDT
 */

/* GDT 结构定义 */
struct gdt_page {
    struct desc_struct gdt[GDT_ENTRIES];  /* 32 个段描述符 */
} __attribute__((aligned(PAGE_SIZE)));    /* 页对齐（4096字节） */

/*
 * Per-CPU GDT 定义
 * 每个 CPU 都有独立的一份
 */
DEFINE_PER_CPU_PAGE_ALIGNED(struct gdt_page, gdt_page) = { .gdt = {
    /*
     * GDT[0]: NULL 描述符
     * 访问 NULL 段选择子会触发异常
     */
    [GDT_ENTRY_NULL] = GDT_ENTRY_INIT(0, 0, 0),

    /*
     * GDT[1]: 保留（以前是 KERNEL32_CS）
     * 现代内核不使用
     */

    /*
     * GDT[2]: __KERNEL_CS (64位内核代码段)
     * 段选择子 = 0x10
     */
    [GDT_ENTRY_KERNEL_CS] = GDT_ENTRY_INIT(DESC_CODE64, 0, 0xfffff),
    /*
     * DESC_CODE64 展开：
     *   .type = 0xA (代码段, 可执行, 可读)
     *   .s = 1 (代码/数据段)
     *   .dpl = 0 (Ring 0)
     *   .p = 1 (存在)
     *   .l = 1 (64位) ← 关键
     *   .d = 0 (must be 0 for 64-bit)
     *   .g = 1 (4KB granularity)
     *
     * Base = 0 (长模式强制)
     * Limit = 0xfffff (被忽略)
     *
     * 用途：内核态代码执行
     */

    /*
     * GDT[3]: __KERNEL_DS (内核数据段)
     * 段选择子 = 0x18
     */
    [GDT_ENTRY_KERNEL_DS] = GDT_ENTRY_INIT(DESC_DATA64, 0, 0xfffff),
    /*
     * DESC_DATA64 展开：
     *   .type = 0x2 (数据段, 可读写)
     *   .s = 1
     *   .dpl = 0 (Ring 0)
     *   .p = 1
     *   .l = 0
     *   .d = 1
     *   .g = 1
     *
     * Base = 0
     * Limit = 0xfffff (被忽略)
     *
     * 用途：DS/SS/ES 数据段
     */

    /*
     * GDT[4]: __USER32_CS (32位用户代码段)
     * 段选择子 = 0x23 (索引4, RPL=3)
     */
    [GDT_ENTRY_DEFAULT_USER32_CS] = GDT_ENTRY_INIT(DESC_CODE32 | DESC_USER, 0, 0xfffff),
    /*
     * DESC_CODE32 | DESC_USER 展开：
     *   .type = 0xA (代码段)
     *   .s = 1
     *   .dpl = 3 (Ring 3) ← 用户态
     *   .p = 1
     *   .l = 0 (32位)
     *   .d = 1 (32位默认)
     *   .g = 1
     *
     * 用途：运行 32 位用户程序（兼容模式）
     */

    /*
     * GDT[5]: __USER_DS (用户数据段)
     * 段选择子 = 0x2B (索引5, RPL=3)
     */
    [GDT_ENTRY_DEFAULT_USER_DS] = GDT_ENTRY_INIT(DESC_DATA64 | DESC_USER, 0, 0xfffff),
    /*
     * DESC_DATA64 | DESC_USER 展开：
     *   .type = 0x2 (数据段)
     *   .s = 1
     *   .dpl = 3 (Ring 3) ← 用户态
     *   .p = 1
     *   .l = 0
     *   .d = 1
     *   .g = 1
     *
     * 用途：用户态数据段（DS/SS/ES）
     */

    /*
     * GDT[6]: __USER_CS (64位用户代码段)
     * 段选择子 = 0x33 (索引6, RPL=3)
     */
    [GDT_ENTRY_DEFAULT_USER_CS] = GDT_ENTRY_INIT(DESC_CODE64 | DESC_USER, 0, 0xfffff),
    /*
     * DESC_CODE64 | DESC_USER 展开：
     *   .type = 0xA (代码段)
     *   .s = 1
     *   .dpl = 3 (Ring 3) ← 用户态
     *   .p = 1
     *   .l = 1 (64位) ← 关键
     *   .d = 0
     *   .g = 1
     *
     * 用途：运行 64 位用户程序
     */

    /*
     * GDT[7-11]: TSS (Task State Segment)
     * 每个 CPU 的 TSS（动态设置）
     *
     * 注意：TSS 在 64 位模式下占用两个 GDT 条目（16字节）
     */

    /*
     * GDT[12-14]: LDT (Local Descriptor Table)
     * 现代 Linux 很少使用 LDT
     */

    /*
     * GDT[15-31]: 其他用途
     * - TLS (Thread Local Storage) 段
     * - 其他系统段
     */
} };
EXPORT_PER_CPU_SYMBOL_GPL(gdt_page);

/*
 * 在 startup_64_setup_gdt_idt() 中加载
 */
void __head startup_64_setup_gdt_idt(void)
{
    /* 获取当前 CPU 的 gdt_page 地址 */
    struct gdt_page *gp = rip_rel_ptr((void *)&gdt_page);

    /* 构建 GDTR 结构 */
    struct desc_ptr startup_gdt_descr = {
        .address = (unsigned long)gp->gdt,
        .size = GDT_SIZE - 1                /* 32 * 8 - 1 = 255 */
    };

    /* 加载 GDT */
    native_load_gdt(&startup_gdt_descr);    /* lgdt 指令 */

    /* 重新加载段寄存器 */
    asm volatile("movl %%eax, %%ds\n"
                 "movl %%eax, %%ss\n"
                 "movl %%eax, %%es\n"
                 : : "a"(__KERNEL_DS) : "memory");

    /* 从此使用主内核的 gdt_page */
}

/*
 * 每个 CPU 初始化时加载自己的 GDT
 */
void cpu_init(void)
{
    int cpu = smp_processor_id();

    /* 加载 Per-CPU GDT */
    load_direct_gdt(cpu);

    /* 设置 TSS */
    struct tss_struct *tss = &per_cpu(cpu_tss_rw, cpu);
    set_tss_desc(cpu, &get_cpu_entry_area(cpu)->tss);
    load_TR_desc();

    /* 设置内核栈 */
    load_sp0((unsigned long)(cpu_entry_stack(cpu) + 1));

    /* ... 其他初始化 ... */
}
```

**gdt_page 特点**：

```
段数量：32 个（GDT_ENTRIES）
使用时期：startup_64_setup_gdt_idt() → 内核完全运行
段选择子：
  内核态：
    - 0x10: __KERNEL_CS (64位内核代码)
    - 0x18: __KERNEL_DS (内核数据)
  用户态：
    - 0x23: __USER32_CS (32位用户代码)
    - 0x2B: __USER_DS (用户数据)
    - 0x33: __USER_CS (64位用户代码)
  系统：
    - TSS 段（每个CPU不同）
    - LDT 段（可选）
    - TLS 段

设计特点：
✓ 完整功能：支持内核态和用户态
✓ Per-CPU：每个 CPU 独立的 GDT
✓ 支持系统调用：满足 SYSCALL/SYSRET 布局要求
✓ 支持任务切换：包含 TSS
✓ 支持 SMP：多处理器支持
✓ 支持线程：TLS 段

优点：
✓ 功能完整
✓ 支持所有内核特性
✓ Per-CPU 隔离
✓ 性能优化

缺点：
✗ 复杂（32个段）
✗ 需要动态初始化（Per-CPU）
```

### 三套 GDT 详细对比表

```
┌─────────────────┬──────────────┬───────────────┬──────────────┐
│ 特性            │ GRUB GDT     │ boot_gdt      │ gdt_page     │
├─────────────────┼──────────────┼───────────────┼──────────────┤
│ 段描述符数量    │ 5 个         │ 4 个          │ 32 个        │
├─────────────────┼──────────────┼───────────────┼──────────────┤
│ NULL 描述符     │ ✓ GDT[0]     │ ✓ GDT[0]      │ ✓ GDT[0]     │
│ 32位代码段      │ ✓ GDT[1]     │ ✓ GDT[1]      │ ✗ (废弃)     │
│ 64位代码段      │ ✓ GDT[3]     │ ✓ GDT[2]      │ ✓ GDT[2]     │
│ 数据段          │ ✓ GDT[2,4]   │ ✓ GDT[3]      │ ✓ GDT[3]     │
│ 用户代码段      │ ✗            │ ✗             │ ✓ GDT[4,6]   │
│ 用户数据段      │ ✗            │ ✗             │ ✓ GDT[5]     │
│ TSS             │ ✗            │ ✗             │ ✓ GDT[7-11]  │
│ LDT             │ ✗            │ ✗             │ ✓ GDT[12-14] │
│ TLS             │ ✗            │ ✗             │ ✓ GDT[15-31] │
├─────────────────┼──────────────┼───────────────┼──────────────┤
│ 支持内核态      │ ✓            │ ✓             │ ✓            │
│ 支持用户态      │ ✗            │ ✗             │ ✓            │
│ 支持系统调用    │ ✗            │ ✗             │ ✓            │
│ 支持任务切换    │ ✗            │ ✗             │ ✓            │
│ 支持 SMP        │ ✗            │ ✗             │ ✓ Per-CPU    │
│ 支持线程        │ ✗            │ ✗             │ ✓ TLS        │
├─────────────────┼──────────────┼───────────────┼──────────────┤
│ 定义位置        │ relocator.c  │ head_64.S     │ common.c     │
│ 存储位置        │ GRUB 内存    │ 内核镜像      │ Per-CPU 区域 │
│ 加载方式        │ GRUB lgdt    │ startup_32    │ startup_64_  │
│                 │              │   lgdt        │   setup_gdt  │
│ 使用时期        │ GRUB 运行时  │ 压缩→主内核   │ 主内核运行   │
│                 │              │   早期        │              │
├─────────────────┼──────────────┼───────────────┼──────────────┤
│ 段基址(Base)    │ 0x00000000   │ 0x00000000    │ 0x00000000   │
│ 段界限(Limit)   │ 0xFFFFF      │ 0xFFFFF       │ 0xFFFFF      │
│                 │ (4GB)        │ (4GB, 忽略)   │ (忽略)       │
│ 扁平模式        │ ✓            │ ✓             │ ✓            │
│ 长模式兼容      │ ✓            │ ✓             │ ✓            │
├─────────────────┼──────────────┼───────────────┼──────────────┤
│ 主要目的        │ GRUB 加载    │ 进入长模式    │ 完整内核     │
│                 │ 内核         │ 解压内核      │ 运行         │
├─────────────────┼──────────────┼───────────────┼──────────────┤
│ 优点            │ 简单         │ 最小化        │ 功能完整     │
│                 │ 支持32/64位  │ 位置无关      │ Per-CPU      │
│                 │              │ 可控          │ 支持所有特性 │
├─────────────────┼──────────────┼───────────────┼──────────────┤
│ 缺点            │ 不可靠       │ 功能有限      │ 复杂         │
│                 │ 内核不可控   │ 无用户态      │ 需要初始化   │
│                 │              │ 无 TSS        │              │
└─────────────────┴──────────────┴───────────────┴──────────────┘
```

### 段选择子对比

```
【GRUB GDT 的段选择子】
NULL:       0x00 (GDT[0])
32位CS:     0x08 (GDT[1])
32位DS:     0x10 (GDT[2])
64位CS:     0x18 (GDT[3]) ← GRUB 用这个进入长模式
64位DS:     0x20 (GDT[4])

【boot_gdt 的段选择子】
NULL:       0x00 (GDT[0])
32位CS:     0x08 (GDT[1], __KERNEL32_CS)
64位CS:     0x10 (GDT[2], __KERNEL_CS) ← 长模式主要使用
数据段:     0x18 (GDT[3], __KERNEL_DS)

【gdt_page 的段选择子】
NULL:       0x00 (GDT[0])
保留:       0x08 (GDT[1])
内核CS:     0x10 (GDT[2], __KERNEL_CS)   ← 内核态代码
内核DS:     0x18 (GDT[3], __KERNEL_DS)   ← 内核态数据
用户32CS:   0x23 (GDT[4], __USER32_CS, RPL=3)
用户DS:     0x2B (GDT[5], __USER_DS, RPL=3) ← 用户态数据
用户64CS:   0x33 (GDT[6], __USER_CS, RPL=3)  ← 用户态代码
TSS:        动态分配（GDT[7-11]）
LDT:        可选（GDT[12-14]）
TLS:        线程相关（GDT[15-31]）
```

### SYSCALL/SYSRET 的 GDT 布局要求

这解释了为什么 gdt_page 必须有特定的布局：

```c
/*
 * SYSCALL/SYSRET 指令对 GDT 布局的硬性要求
 */

/* IA32_STAR MSR 寄存器设置 */
wrmsrl(MSR_STAR,
       ((u64)__USER32_CS << 48) |      /* SYSRET 用户态 CS 基值 */
       ((u64)__KERNEL_CS << 32));      /* SYSCALL 内核态 CS */

/*
 * SYSCALL 指令（用户态 → 内核态）
 * 硬件自动操作：
 */
CS = MSR_STAR[47:32] + 0  = __KERNEL_CS (0x10)  // GDT[2]
SS = MSR_STAR[47:32] + 8  = __KERNEL_DS (0x18)  // GDT[3]
                                         ↑
                            必须紧跟在 __KERNEL_CS 后面！

/*
 * SYSRET 指令（内核态 → 用户态）
 * 硬件自动操作：
 */
CS = MSR_STAR[63:48] + 16 = __USER_CS (0x33)    // GDT[6]
SS = MSR_STAR[63:48] + 8  = __USER_DS (0x2B)    // GDT[5]
                                         ↑
                            __USER_DS 必须在 __USER_CS 前面！

/*
 * 这就是为什么 gdt_page 必须有这个布局：
 * GDT[2] = __KERNEL_CS
 * GDT[3] = __KERNEL_DS  ← 必须紧跟
 * GDT[4] = __USER32_CS
 * GDT[5] = __USER_DS
 * GDT[6] = __USER_CS    ← __USER_DS 必须在前
 *
 * boot_gdt 不满足这个要求，所以无法支持系统调用！
 */
```

### GDT 演化的原因总结

```
【为什么需要三套 GDT？】

阶段1：GRUB GDT
原因：
- GRUB 需要从实模式进入保护模式/长模式
- GRUB 需要加载内核到内存
问题：
- 位于 GRUB 控制的内存区域
- 内核解压会覆盖这块内存
- 内核无法控制
解决：→ 切换到 boot_gdt

阶段2：boot_gdt（压缩内核）
原因：
- 需要可控的 GDT（在内核镜像内）
- 需要支持进入长模式（L=1 的代码段）
- 需要解压内核
问题：
- 太简单：只有 3-4 个段
- 无用户态段：无法运行用户进程
- 无 TSS：无法系统调用、任务切换
- 不是 Per-CPU：无法支持 SMP
- 不满足 SYSCALL/SYSRET 布局
解决：→ 切换到 gdt_page

阶段3：gdt_page（主内核）
原因：
- 需要完整功能：内核态 + 用户态
- 需要系统调用：SYSCALL/SYSRET
- 需要任务切换：TSS
- 需要 SMP：Per-CPU GDT
- 需要线程：TLS 段
结果：
✓ 功能完整
✓ 一直使用到系统关机
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
