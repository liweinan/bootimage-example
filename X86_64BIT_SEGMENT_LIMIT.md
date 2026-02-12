# x86-64 长模式下的段限长处理

本文档详细说明 64 位长模式下段限长（Segment Limit）的实际处理机制，澄清常见误解。

> **相关文档**：[X86_NEAR_VS_LONG_JUMP.md](X86_NEAR_VS_LONG_JUMP.md) - Long mode 下 CS 的作用；[X86_CPU_MODES.md](X86_CPU_MODES.md) - CPU 模式详解

---

## 核心结论

**✅ 在 64 位长模式下，CPU 完全忽略段限长（Segment Limit）**

- GDT 中设置的 limit 字段**不起作用**
- 即使写 `0xfffff`（1MB），实际可访问整个虚拟地址空间
- 真正的内存边界由**页表**和**虚拟地址空间布局**决定

---

## Intel 官方手册说明

### 来源：Intel® 64 and IA-32 Architectures Software Developer's Manual Volume 3A

#### Section 3.2.4: Segmentation in IA-32e Mode

> **In 64-bit mode, segmentation is generally (but not completely) disabled, creating a flat 64-bit linear-address space. The processor treats the segment base of CS, DS, ES, SS as zero, creating a linear address that is equal to the effective address.**
>
> The FS and GS segments are exceptions. These segment registers (which hold the segment base) can be used as additional base registers in linear address calculations.
>
> **Note that the processor does not perform segment limit checks at runtime in 64-bit mode.**

**关键要点**：
1. **基址强制为0**：CS/DS/ES/SS 的 base 被强制为 0
2. **平坦地址空间**：线性地址 = 有效地址（不再用段基址计算）
3. **限长不检查**：**CPU 不执行运行时的段限长检查**
4. **FS/GS 例外**：只有 FS 和 GS 的基址仍然有效（用于 TLS/per-CPU）

#### Section 5.3.1: Limit Checking in 64-bit Mode

> **In 64-bit mode, the processor does not perform runtime limit checking on code or data segments.** However, the processor does check descriptor-table limits.

**说明**：
- ❌ 不检查代码段和数据段的限长
- ✅ 仍然检查描述符表（GDT/LDT/IDT）的限长

---

## 段限长在不同模式下的行为

### 对比表

| 模式 | GDT 中的 limit | 实际可访问空间 | CPU 是否检查 limit |
|------|---------------|---------------|-------------------|
| **64位长模式** | 0xfffff (1MB) | 48位/57位虚拟地址空间 | ❌ **不检查** |
| **32位保护模式** | 0xfffff (4GB) | 4GB | ✅ **检查**（触发 #GP） |
| **16位实模式** | N/A | 1MB | ✅ **硬件限制** |

### 详细说明

#### 1. 64位长模式

```
段寄存器处理（64位模式）：

CS/DS/ES/SS:
    ├─ 基址（Base）      → 强制为 0 ✅
    ├─ 限长（Limit）     → CPU 完全忽略 ❌
    └─ 线性地址         → 直接等于有效地址

FS/GS（例外）:
    ├─ 基址（Base）      → 仍然有效 ✅
    │                     (通过 MSR_FS_BASE/MSR_GS_BASE)
    └─ 限长（Limit）     → 仍然忽略 ❌

虚拟地址空间：
    ├─ 48位实现：256TB (0x0000_0000_0000_0000 - 0x0000_FFFF_FFFF_FFFF)
    ├─ 57位实现：128PB
    └─ 由页表和规范地址检查控制，不是段限长
```

**实际例子**：

```c
// 即使 GDT 中设置 limit = 0xfffff (1MB)
[GDT_ENTRY_KERNEL_CS] = GDT_ENTRY_INIT(DESC_CODE64, 0, 0xfffff)

// 64位模式下，仍可访问整个虚拟地址空间
mov rax, [0x00007FFFFFFFFFFF]  // 用户空间最高地址（128TB）✅ 合法
mov rax, [0xFFFF800000000000]  // 内核空间起始 ✅ 合法
mov rax, [0xFFFFFFFFFFFFFFFF]  // 内核空间最高 ✅ 合法

// 这些地址远超 GDT 中的 0xfffff (1MB)，但 CPU 不检查
// 真正的边界由页表决定（缺页异常 vs 访问成功）
```

#### 2. 32位保护模式

```
段寄存器处理（32位模式）：

CS/DS/ES/SS:
    ├─ 基址（Base）      → 从 GDT 读取 ✅
    ├─ 限长（Limit）     → CPU 检查 ✅
    └─ 线性地址         → Base + 有效地址

访问检查：
    if (有效地址 > 段限长) {
        #GP(0)  // General Protection Fault
    }
```

**实际例子**：

```c
// GDT 中设置 limit = 0xfffff, G=1 (粒度=4KB)
// 实际限长 = 0xfffff * 4KB = 4GB

// 32位模式下
mov eax, [0x00000000]  // ✅ 合法（在限长内）
mov eax, [0xFFFFFFFF]  // ✅ 合法（刚好到限长）
mov eax, [0x100000000] // ❌ #GP（超出32位地址空间）

// 如果 limit = 0x00fff (4KB)
mov eax, [0x00000FFF]  // ✅ 合法
mov eax, [0x00001000]  // ❌ #GP（超出限长）
```

---

## 为什么 GDT 中还要写 limit？

虽然 64 位模式下 limit 不起作用，GDT 描述符中仍需填写 limit 字段：

### 原因

| 原因 | 说明 |
|------|------|
| **1. 格式要求** | 段描述符格式固定（8字节），必须填充所有字段 |
| **2. 32位兼容模式** | 当运行 32 位兼容代码时，limit 才真正生效 |
| **3. 代码复用** | 初始化宏统一处理两种模式，简化代码 |
| **4. 向后兼容** | 保持与旧 CPU 和旧代码的兼容性 |
| **5. 描述符表限长** | GDT/LDT/IDT 的限长仍然被检查 |

### Linux 内核的 GDT 定义示例

```c
// arch/x86/include/asm/segment.h
#define GDT_ENTRY_INIT(flags, base, limit)              \
{                                                        \
    .limit0     = (u16) (limit),                        \
    .limit1     = ((limit) >> 16) & 0x0F,               \
    .base0      = (u16) (base),                         \
    .base1      = ((base) >> 16) & 0xFF,                \
    .base2      = ((base) >> 24) & 0xFF,                \
    .type       = (flags & 0x0f),                       \
    .s          = (flags >> 4) & 0x01,                  \
    .dpl        = (flags >> 5) & 0x03,                  \
    .p          = (flags >> 7) & 0x01,                  \
    .avl        = (flags >> 12) & 0x01,                 \
    .l          = (flags >> 13) & 0x01,  ← L=1：64位代码段
    .d          = (flags >> 14) & 0x01,                 \
    .g          = (flags >> 15) & 0x01,                 \
}

// arch/x86/kernel/head_64.S
gdt64:
    .word   gdt64_end - gdt64 - 1
    .quad   0
gdt64_start:
    .quad   0x0000000000000000      ; NULL descriptor
    .quad   0x00af9a000000ffff      ; __KERNEL_CS (64位代码段)
            ; ^^^^                   ; limit = 0xfffff ← 在64位下被忽略
            ;   ^^                   ; L=1, G=1
    .quad   0x00cf92000000ffff      ; __KERNEL_DS
            ; ^^^^                   ; limit = 0xfffff ← 在64位下被忽略
```

**解析 `0x00af9a000000ffff`**：

```
位段           值    含义
────────────────────────────────────
[15:0]     0xffff   Limit[15:0]   ← 64位下忽略
[31:16]    0x0000   Base[15:0]    ← 强制为0
[39:32]    0x00     Base[23:16]   ← 强制为0
[43:40]    0xa      Type (1010 = Code, Execute/Read)
[44]       1        S = 1 (代码/数据段)
[46:45]    0        DPL = 0 (Ring 0)
[47]       1        P = 1 (Present)
[51:48]    0xf      Limit[19:16]  ← 64位下忽略
[52]       0        AVL
[53]       1        L = 1 ← **64位代码段标志**
[54]       0        D = 0 (L=1时必须为0)
[55]       1        G = 1 (粒度=4KB，但64位下忽略)
[63:56]    0x00     Base[31:24]   ← 强制为0
```

**关键点**：
- `limit = 0xfffff, G=1` → 理论限长 4GB
- `L=1` → 64 位代码段
- **实际效果**：CPU 忽略 limit，可访问整个 48/57 位地址空间

---

## 真正的内存访问控制机制

### 64 位系统不靠段限长，而靠：

#### 1. 页表机制（主要手段）

```
虚拟地址 → 物理地址转换：

CR3 (页表基址寄存器)
    ↓
PGD (Page Global Directory)
    ↓
PUD (Page Upper Directory)
    ↓
PMD (Page Middle Directory)
    ↓
PTE (Page Table Entry)
    ↓
物理页 (4KB/2MB/1GB)

每一级页表项有标志位：
    ├─ P (Present)        : 页是否存在
    ├─ RW (Read/Write)    : 读写权限
    ├─ US (User/Supervisor): 用户/内核权限
    ├─ NX (No Execute)    : 执行权限
    └─ 等...

缺页异常（Page Fault）：
    ├─ 访问不存在的页 (P=0)
    ├─ 权限不足 (RW/US/NX)
    └─ 这才是真正的内存边界控制
```

#### 2. 虚拟地址空间布局

```
64位 Linux 虚拟地址空间（48位实现）：

0x0000_0000_0000_0000
    ↓
用户空间（128TB）
    ├─ 程序代码段 (.text)
    ├─ 数据段 (.data/.bss)
    ├─ 堆 (heap)
    ├─ 共享库
    ├─ 栈 (stack)
    └─ ...
    ↓
0x0000_7FFF_FFFF_FFFF  ← 用户空间最高地址
    ↓
非规范地址区域（不可访问）
    ├─ 0x0000_8000_0000_0000 - 0xFFFF_7FFF_FFFF_FFFF
    └─ 任何访问触发 #GP（General Protection Fault）
    ↓
0xFFFF_8000_0000_0000  ← 内核空间起始
    ↓
内核空间（128TB）
    ├─ 直接映射区
    ├─ vmalloc 区
    ├─ 内核代码
    ├─ 内核数据
    └─ ...
    ↓
0xFFFF_FFFF_FFFF_FFFF  ← 内核空间最高地址
```

**规范地址检查**：
- 48位实现：地址的 [63:47] 位必须全为 0 或全为 1
- 57位实现：地址的 [63:56] 位必须全为 0 或全为 1
- 违反规范形式 → #GP（General Protection Fault）

#### 3. 对比：段限长 vs 页表

| 特性 | 段限长（32位模式） | 页表（64位模式） |
|------|------------------|-----------------|
| **粒度** | 字节级（或4KB级） | 4KB/2MB/1GB |
| **控制方式** | 段描述符中的 limit 字段 | 页表项（PTE）的标志位 |
| **检查时机** | 每次内存访问（硬件检查） | MMU 翻译时（硬件检查） |
| **异常类型** | #GP (General Protection) | #PF (Page Fault) |
| **权限控制** | 有限（读/写/执行） | 精细（P/RW/US/NX/...） |
| **64位是否使用** | ❌ 否（被忽略） | ✅ 是（主要机制） |

---

## 常见问题解答

### Q1: 为什么内核可以访问 TB 级内存，GDT 里却写着 1MB 限长？

**A:** 因为在 64 位长模式下，CPU **完全忽略** GDT 中的 limit 字段。

- GDT 中的 `0xfffff` 只是**格式要求**
- 真正的内存访问范围由**页表**和**虚拟地址空间**决定
- 48位实现可访问 256TB，57位实现可访问 128PB

### Q2: 既然 limit 不起作用，为什么还要在 GDT 中设置？

**A:** 主要原因：

1. **段描述符格式固定**：8字节结构，必须填充所有字段
2. **32位兼容模式**：运行 32 位代码时，limit 才真正生效
3. **代码简洁性**：初始化宏统一处理，不需特殊判断
4. **向后兼容**：保持与旧代码和文档的一致性

### Q3: 如果 limit 不起作用，内核如何防止越界访问？

**A:** 通过**页表**和**虚拟地址空间布局**：

```
内存访问检查流程（64位）：

1. 规范地址检查
   ├─ 48位：地址[63:47]全0或全1
   └─ 违反 → #GP

2. 页表查找（MMU）
   ├─ CR3 → PGD → PUD → PMD → PTE
   └─ 检查 P/RW/US/NX 标志

3. 权限检查
   ├─ P=0 → #PF（页不存在）
   ├─ 用户访问内核页 → #PF
   ├─ 写只读页 → #PF
   └─ 执行 NX 页 → #PF

段限长完全不参与这个过程 ❌
```

### Q4: FS 和 GS 段是例外吗？

**A:** 部分例外：

- ✅ **基址有效**：FS.base 和 GS.base 通过 MSR 设置，参与地址计算
- ❌ **限长仍忽略**：FS 和 GS 的 limit 仍然不检查
- **用途**：
  - FS：线程局部存储（TLS）
  - GS：per-CPU 变量

```c
// 设置 FS/GS 基址（通过 MSR）
wrmsr(MSR_FS_BASE, thread->fsbase);  // FS用于TLS
wrmsr(MSR_GS_BASE, per_cpu_offset);  // GS用于per-CPU变量

// 使用 FS/GS 段
mov rax, fs:[0x10]  // 线性地址 = FS.base + 0x10
mov rbx, gs:[0x20]  // 线性地址 = GS.base + 0x20
```

### Q5: 描述符表（GDT/IDT）的限长还检查吗？

**A:** 是的！

```
GDT/LDT/IDT 的限长检查（64位仍然有效）：

GDTR/LDTR/IDTR 寄存器：
    ├─ Base：描述符表基址（64位）
    └─ Limit：描述符表限长（16位）

访问检查：
    if (选择子索引 * 8 > GDTR.Limit) {
        #GP(选择子)  // 超出描述符表范围
    }

例子：
    GDTR.Limit = 0x7F  // 128字节 = 16个描述符
    lgdt [gdtr]
    
    mov ax, 0x08   // 选择子索引=1 → 8*1=8   ✅ 合法
    mov ax, 0x80   // 选择子索引=16 → 8*16=128 ❌ #GP（超出限长）
```

---

## 实际验证

### 测试程序（用户空间）

```c
#include <stdio.h>
#include <stdint.h>

int main() {
    uint64_t addr;
    
    // 测试1：访问用户空间高地址（接近128TB）
    addr = 0x00007FFFFFFF0000ULL;  // 接近用户空间顶部
    printf("尝试访问: 0x%016lx\n", addr);
    // 是否成功取决于页表，不是段限长
    
    // 测试2：访问非规范地址（会触发 #GP）
    addr = 0x0000800000000000ULL;  // 非规范区域
    // *(uint64_t*)addr;  // 取消注释会 segfault (#GP)
    
    // 测试3：访问内核空间（会触发 #PF）
    addr = 0xFFFF800000000000ULL;  // 内核空间起始
    // *(uint64_t*)addr;  // 取消注释会 segfault (#PF - 权限不足)
    
    return 0;
}
```

### 内核示例

```c
// Linux内核可以访问整个内核空间
void *kernel_ptr = (void *)0xFFFFFFFF81000000;  // 内核代码区
uint64_t value = *(uint64_t *)kernel_ptr;  // ✅ 合法（如果页存在）

// 即使 GDT 中 limit = 0xfffff (1MB)
// 这个地址远超 1MB，但访问成功
// 因为 CPU 不检查段限长，只检查页表
```

---

## 总结

### 核心要点

| 说法 | 是否正确 | 说明 |
|------|---------|------|
| "64位模式下段限长被忽略" | ✅ 正确 | CPU 不执行运行时检查 |
| "GDT 中的 limit 不起作用" | ✅ 正确 | 对代码/数据段而言 |
| "可以访问所有内存" | ⚠️ 部分正确 | 受页表和虚拟地址布局限制 |
| "不需要在 GDT 中写 limit" | ❌ 错误 | 格式要求，必须填充 |
| "段机制完全废除" | ❌ 错误 | CPL/L位/FS/GS 仍然有效 |

### Intel 官方确认

> "In 64-bit mode, the processor does not perform runtime limit checking on code or data segments."  
> — Intel® 64 and IA-32 Architectures SDM Vol. 3A, Section 5.3.1

### 实际机制

```
64位模式下的内存访问控制：

段限长 ❌ → 被忽略
    ↓
页表检查 ✅ → 主要机制
    ├─ Present bit
    ├─ Read/Write bit
    ├─ User/Supervisor bit
    ├─ NX bit
    └─ 缺页异常
    ↓
虚拟地址空间 ✅ → 布局控制
    ├─ 用户空间：0 - 128TB
    ├─ 非规范：128TB - (2^64-128TB)
    └─ 内核空间：(2^64-128TB) - 2^64
    ↓
规范地址检查 ✅ → 硬件验证
    └─ 地址[63:47]全0或全1
```

---

## 相关文档

- [X86_NEAR_VS_LONG_JUMP.md](X86_NEAR_VS_LONG_JUMP.md) - Long mode 下 CS 的作用（CPL、L/D 位）
- [X86_CPU_MODES.md](X86_CPU_MODES.md) - x86 CPU 运行模式详解
- [LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md) - Linux 内核启动流程（GDT 初始化）

## 参考资料

1. Intel® 64 and IA-32 Architectures Software Developer's Manual Volume 3A
   - Section 3.2.4: Segmentation in IA-32e Mode
   - Section 5.3.1: Limit Checking in 64-bit Mode
   - `https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html`

2. Linux Kernel Source
   - `arch/x86/kernel/head_64.S` - 内核 GDT 定义 - `https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/arch/x86/kernel/head_64.S`
   - `arch/x86/include/asm/segment.h` - 段定义和宏 - `https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/arch/x86/include/asm/segment.h`
