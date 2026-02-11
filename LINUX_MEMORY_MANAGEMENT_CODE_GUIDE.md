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

### 1.3 startup_64_setup_gdt_idt() 实现详解

**位置**：`arch/x86/boot/startup/gdt_idt.c:49-70`

**上下文**：此函数在 `head_64.S` 中的 `startup_64` 早期被调用，目的是从压缩内核的临时GDT切换到主内核的Per-CPU GDT。

#### 代码与详细注释

```c
void __head startup_64_setup_gdt_idt(void)
{
    /*
     * 步骤 1：获取 gdt_page 符号的物理地址
     *
     * 【问题】：为什么需要 rip_rel_ptr()？
     * - 当前代码运行在 Identity Mapping（恒等映射）模式下
     * - 直接使用 &gdt_page 会得到高地址虚拟地址（如 0xffffffff81234000）
     * - 但页表还未完全建立，不能访问高地址
     * - rip_rel_ptr() 将符号地址转换为当前可访问的物理地址
     *
     * 【rip_rel_ptr() 工作原理】：
     * - 使用 RIP 相对寻址：计算符号相对于当前代码的偏移
     * - 公式：物理地址 = 当前RIP的物理地址 + (&gdt_page - 当前RIP)
     * - 结果：得到 gdt_page 的真实物理位置（如 0x01234000）
     *
     * 【gdt_page 是什么】：
     * - 这是在 common.c 中通过 DEFINE_PER_CPU_PAGE_ALIGNED() 定义的Per-CPU变量
     * - 包含 GDT_ENTRIES（32个）段描述符
     * - 在编译时已初始化好 6 个关键段（见 1.2 节）
     */
    struct gdt_page *gp = rip_rel_ptr((void *)&gdt_page);

    /*
     * 步骤 2：构建 GDT 描述符（desc_ptr）
     *
     * 【desc_ptr 结构】：
     * struct desc_ptr {
     *     unsigned short size;    // GDT表大小-1（字节）
     *     unsigned long address;  // GDT表的线性地址
     * } __attribute__((packed));
     *
     * 【为什么 size = GDT_SIZE - 1】：
     * - GDT_SIZE = 32 * 8 = 256 字节（32个8字节描述符）
     * - Intel 手册规定：GDTR.Limit = 表大小 - 1
     * - 原因：Limit表示最后一个有效字节的偏移（从0开始）
     * - 例：256字节表 → 有效偏移0-255 → Limit=255
     *
     * 【address 字段】：
     * - gp->gdt 是 gdt_page.gdt 数组的起始地址
     * - 指向第一个段描述符（GDT[0]，固定为NULL描述符）
     *
     * 【startup_gdt_descr 如何对应到 DEFINE_PER_CPU_PAGE_ALIGNED】：
     *
     * 编译时（common.c）：
     *   DEFINE_PER_CPU_PAGE_ALIGNED(struct gdt_page, gdt_page) = {
     *       .gdt = {
     *           [GDT_ENTRY_KERNEL_CS] = GDT_ENTRY_INIT(...),  // 内核代码段
     *           [GDT_ENTRY_KERNEL_DS] = GDT_ENTRY_INIT(...),  // 内核数据段
     *           // ... 共 6 个段
     *       }
     *   };
     *   ↓ 编译器处理
     *   生成一个全局符号 gdt_page，包含初始化的数据
     *   在 vmlinux 中占据 4096 字节（PAGE_SIZE，页对齐）
     *
     * 链接时：
     *   链接器将 gdt_page 放在内核镜像的 .data.percpu 段
     *   分配虚拟地址（如 0xffffffff82345000）
     *
     * 运行时（本函数）：
     *   1. rip_rel_ptr(&gdt_page) → 获取 gdt_page 的物理地址
     *      - 输入：&gdt_page = 0xffffffff82345000（链接地址）
     *      - 输出：0x02345000（当前可访问的物理地址）
     *
     *   2. gp->gdt → 指向 GDT 数组起始
     *      - gp = 0x02345000（struct gdt_page *）
     *      - gp->gdt = 0x02345000（数组起始，struct gdt_page第一个字段）
     *
     *   3. startup_gdt_descr.address = (unsigned long)gp->gdt
     *      - address = 0x02345000（GDT 表的物理地址）
     *
     *   4. lgdt 指令加载
     *      - CPU 将 GDTR 寄存器设为：{size=255, address=0x02345000}
     *      - 从此所有段选择子（如 __KERNEL_CS）查表都使用此GDT
     *
     * 【连接关系总结】：
     *   DEFINE_PER_CPU_PAGE_ALIGNED  →  编译器生成全局符号 gdt_page
     *                                →  链接器分配虚拟地址
     *                                ↓
     *   rip_rel_ptr(&gdt_page)       →  运行时解析物理地址
     *                                ↓
     *   startup_gdt_descr.address    →  指向 GDT 表物理位置
     *                                ↓
     *   lgdt                         →  CPU 加载到 GDTR 寄存器
     */
    struct desc_ptr startup_gdt_descr = {
        .address = (unsigned long)gp->gdt,  // GDT 表的物理地址
        .size = GDT_SIZE - 1                // 256 - 1 = 255（最后有效字节偏移）
    };

    /*
     * 步骤 3：加载 GDT 到 GDTR 寄存器
     *
     * 【lgdt 指令】：
     * - 操作码：0x0F 0x01 /2
     * - 操作：GDTR ← 内存操作数（10字节或6字节）
     * - 结果：GDTR.Limit = startup_gdt_descr.size (255)
     *        GDTR.Base  = startup_gdt_descr.address (0x02345000)
     *
     * 【为什么需要重新加载GDT】：
     * - 压缩内核阶段使用的是 boot_gdt（arch/x86/boot/compressed/head_64.S）
     * - boot_gdt 只有最基本的几个段，仅够压缩代码运行
     * - 主内核需要完整的 GDT，包括：
     *   * 用户态代码段/数据段（SYSCALL/SYSRET需要）
     *   * 32位兼容段（运行32位程序需要）
     *   * TSS段（任务切换需要）
     *
     * 【GDTR 寄存器结构】：
     * 79            16 15             0
     * ┌───────────────┬───────────────┐
     * │ 64-bit Base   │  16-bit Limit │
     * └───────────────┴───────────────┘
     *
     * 【加载后的状态】：
     * - CPU的所有段选择子（CS/DS/SS/ES等）仍指向旧GDT的段
     * - 需要重新加载段寄存器让它们指向新GDT（见步骤4）
     */
    native_load_gdt(&startup_gdt_descr);

    /*
     * 步骤 4：重载段寄存器
     *
     * 【为什么需要重载】：
     * - lgdt 只改变 GDTR，不改变段寄存器（CS/DS/SS/ES/FS/GS）
     * - 段寄存器的"影子缓存"（Segment Cache/Descriptor Cache）仍然是旧值
     * - 必须重新加载段选择子，让CPU从新GDT重新读取段描述符
     *
     * 【段寄存器影子缓存机制】：
     * 当执行 `mov ds, ax` 时，CPU做两件事：
     * 1. 将选择子（如 0x18）存入DS寄存器的可见部分（16位）
     * 2. 从GDT读取对应描述符，缓存到DS的不可见部分（64位）
     *
     * 可见部分：           不可见部分（影子缓存）：
     * ┌──────────┐         ┌────────────────────────┐
     * │ 0x0018   │         │ Base: 0x00000000       │
     * │(选择子)  │    ←    │ Limit: 0xFFFFF         │
     * └──────────┘  lgdt后  │ Type: Data, DPL=0      │
     *               需重载   │ ...                    │
     *                       └────────────────────────┘
     *
     * 【__KERNEL_DS 的值】：
     * - 定义：arch/x86/include/asm/segment.h
     * - #define __KERNEL_DS  (GDT_ENTRY_KERNEL_DS * 8)
     * - GDT_ENTRY_KERNEL_DS = 3（第3个GDT条目，0开始计数）
     * - 计算：3 * 8 = 0x18
     * - 二进制：0000 0000 0001 1000
     *   ├─────┬──────────┬───┘
     *   │ RPL │  Index   │ TI
     *   │ =0  │  =3      │ =0 (GDT)
     *   └─────┴──────────┴────
     *   RPL=0: Ring 0（内核特权级）
     *   Index=3: GDT第3项
     *   TI=0: 使用GDT（不是LDT）
     *
     * 【为什么只重载 DS/SS/ES】：
     * - CS（代码段）：不能用 mov 指令修改，必须用 far jmp/call/ret
     *   （实际上 head_64.S 在调用本函数后会用 lretq 重载CS）
     * - FS/GS：用于Per-CPU数据和Thread Local Storage，单独设置
     * - DS/SS/ES：数据访问段，可以统一设为 __KERNEL_DS
     *
     * 【内联汇编语法】：
     * asm volatile(
     *     "movl %%eax, %%ds\n"  // 输出模板（汇编指令）
     *     "movl %%eax, %%ss\n"  // %% 表示寄存器（GCC内联汇编约定）
     *     "movl %%eax, %%es\n"
     *     : /* 无输出操作数 */
     *     : "a"(__KERNEL_DS)     // 输入：将 __KERNEL_DS 放入 EAX
     *     : "memory"             // Clobber：告诉编译器内存可能被修改
     * );
     */
    asm volatile("movl %%eax, %%ds\n"
                 "movl %%eax, %%ss\n"
                 "movl %%eax, %%es\n"
                 : : "a"(__KERNEL_DS) : "memory");

    /*
     * 步骤 5：加载早期 IDT（中断描述符表）
     *
     * 【为什么需要早期IDT】：
     * - 在完整的中断系统初始化前，可能发生异常（如 #PF 缺页异常）
     * - 特别是 AMD SEV（Secure Encrypted Virtualization）环境：
     *   * SEV-ES（Encrypted State）要求处理 #VC 异常（VM Communication）
     *   * #VC异常用于虚拟机与Hypervisor通信（因为寄存器被加密）
     * - 如果没有IDT，任何异常都会触发 Triple Fault → CPU重启
     *
     * 【CONFIG_AMD_MEM_ENCRYPT】：
     * - 编译时配置选项（Kconfig）
     * - 启用：handler = rip_rel_ptr(vc_no_ghcb)
     *   * vc_no_ghcb：最小化的 #VC 异常处理器
     *   * GHCB（Guest-Hypervisor Communication Block）尚未建立
     *   * 只能处理最基本的 #VC 异常
     * - 禁用：handler = NULL
     *   * 不需要 #VC 处理器
     *   * startup_64_load_idt 会设置一个空的或最小的IDT
     *
     * 【startup_64_load_idt() 做什么】：
     * - 设置一个临时的 IDT，只处理关键异常
     * - 如果 handler 非空，将 #VC 异常（向量29）指向 handler
     * - 使用 lidt 指令加载 IDT 到 IDTR 寄存器
     */
    void *handler = IS_ENABLED(CONFIG_AMD_MEM_ENCRYPT) ?
                    rip_rel_ptr(vc_no_ghcb) : NULL;
    startup_64_load_idt(handler);
}
```

#### native_load_gdt() 底层实现

**位置**：`arch/x86/include/asm/desc.h`

```c
static inline void native_load_gdt(const struct desc_ptr *dtr)
{
    /*
     * lgdt 指令：Load Global Descriptor Table Register
     *
     * 【指令格式】：lgdt m80（从内存加载80位/10字节）
     *
     * 【内存布局】（desc_ptr 结构）：
     * Offset  0  1  2  3  4  5  6  7  8  9
     *        ├──┴──┼──┴──┴──┴──┴──┴──┴──┴──┤
     *        │Limit│       Base Address    │
     *        └─────┴───────────────────────┘
     *        2 bytes        8 bytes (64-bit mode)
     *
     * 【操作】：
     * GDTR.Limit ← dtr->size
     * GDTR.Base  ← dtr->address
     *
     * 【异常】：
     * - #GP(0): 如果 Limit < 表的实际大小（会导致越界访问）
     * - #UD: 如果在实模式下使用（实模式不使用GDT）
     *
     * 【内联汇编约束】：
     * "m" (*dtr)  - 表示内存操作数，指向 desc_ptr 结构
     *   * "m" 约束告诉编译器：将 dtr 指向的内存地址传给指令
     *   * 编译器生成：lgdt (%rdi) 或 lgdt offset(%rip)
     */
    asm volatile("lgdt %0"::"m" (*dtr));
}
```

#### 关键概念总结

**DEFINE_PER_CPU_PAGE_ALIGNED 到 startup_gdt_descr 的完整流程**：

```
【编译时】arch/x86/kernel/cpu/common.c
    ↓
DEFINE_PER_CPU_PAGE_ALIGNED(struct gdt_page, gdt_page) = {
    .gdt = {
        [GDT_ENTRY_KERNEL_CS] = GDT_ENTRY_INIT(DESC_CODE64, 0, 0xfffff),
        [GDT_ENTRY_KERNEL_DS] = GDT_ENTRY_INIT(DESC_DATA64, 0, 0xfffff),
        ...
    }
};
    ↓ 编译器展开
.section ".data.percpu"
.align 4096                           # PAGE_SIZE 对齐
gdt_page:                             # 全局符号
    .quad 0x0000000000000000          # GDT[0]: NULL 描述符
    .quad 0x0020980000000000          # GDT[1]: KERNEL_CS
    .quad 0x0000920000000000          # GDT[2]: KERNEL_DS
    ...
    .fill 26*8, 1, 0                  # GDT[6-31]: 预留
    # 共 256 字节（32 * 8）

【链接时】链接器 (ld)
    ↓
将 gdt_page 放入 vmlinux，分配虚拟地址：
    gdt_page @ 0xffffffff82345000  （__per_cpu_start + offset）

【运行时】startup_64_setup_gdt_idt()
    ↓
1. rip_rel_ptr(&gdt_page)
   输入：0xffffffff82345000 （符号的链接地址）
   计算：当前RIP物理地址 + (链接地址 - RIP链接地址)
   输出：0x02345000 （当前可访问的物理地址）

2. struct gdt_page *gp = 0x02345000
   gp->gdt = 0x02345000 （结构体第一个字段）

3. startup_gdt_descr = {
       .address = 0x02345000,
       .size = 255
   }

4. lgdt startup_gdt_descr
   GDTR ← { Base: 0x02345000, Limit: 255 }

5. CPU 后续使用段选择子（如 __KERNEL_CS = 0x10）时：
   - 索引计算：0x10 / 8 = 2 → GDT[2]
   - 读取地址：GDTR.Base + (2 * 8) = 0x02345000 + 16 = 0x02345010
   - 加载描述符到段寄存器的影子缓存
```

#### 1.3.5 关键对比：early_gdt_descr vs startup_64_setup_gdt_idt

在主内核代码中，有**两种**方式来引用 `gdt_page`：

1. **startup_64_setup_gdt_idt()** - 使用 RIP 相对寻址（本节讨论的）
2. **early_gdt_descr** - 使用静态定义的 GDT 描述符

它们都指向同一个 `gdt_page`，但**地址计算方式完全不同**。

##### early_gdt_descr 的定义

**位置**：`arch/x86/kernel/head_64.S`

```assembly
# 早期 GDT 描述符（静态定义）
SYM_DATA_START_LOCAL(early_gdt_descr)
    .word   GDT_ENTRIES*8-1          # Limit: 256-1 = 255
SYM_DATA_END_LABEL(early_gdt_descr, SYM_L_LOCAL, early_gdt_descr_base)
SYM_DATA_START_LOCAL(early_gdt_descr_base)
    .quad   INIT_PER_CPU_VAR(gdt_page)  # Base: gdt_page 的编译时地址
SYM_DATA_END(early_gdt_descr_base)
```

**关键特征**：
- **静态数据**：在汇编时就定义好的 10 字节结构（2字节limit + 8字节base）
- **地址计算**：使用 `INIT_PER_CPU_VAR(gdt_page)` 宏，在**编译/链接时**计算
- **假设前提**：代码已运行在**最终虚拟地址**（如 0xFFFFFFFF81xxxxxx）

##### 核心区别对比表

| 特性 | startup_64_setup_gdt_idt() | early_gdt_descr |
|------|---------------------------|-----------------|
| **定义方式** | C 函数，运行时构建 | 汇编静态数据 |
| **地址计算** | `rip_rel_ptr(&gdt_page)` | `INIT_PER_CPU_VAR(gdt_page)` |
| **地址类型** | RIP 相对地址（运行时） | 链接时固定地址 |
| **使用时机** | startup_64 早期 | 切换到高地址后 |
| **适用环境** | 任何地址（低地址/高地址） | 只能在最终虚拟地址 |
| **灵活性** | 高（位置无关） | 低（依赖链接地址） |

##### 地址计算方式的关键差异

**INIT_PER_CPU_VAR(gdt_page) 宏展开**：

```c
// arch/x86/include/asm/percpu.h
#define INIT_PER_CPU_VAR(var) \
    (init_per_cpu__##var - __per_cpu_load + __per_cpu_start)
```

这是一个**编译时常量计算**：
- 在链接阶段，链接器就确定了 `gdt_page` 的虚拟地址
- 假设值：`0xFFFFFFFF82345000`
- 这个地址**直接写入** `early_gdt_descr` 的数据段

**rip_rel_ptr(&gdt_page) 运行时计算**：

```c
// 内联汇编实现
static inline void *rip_rel_ptr(void *p) {
    asm("leaq %c1(%%rip), %0" : "=r"(ptr) : "i"(p));
    // 计算：当前RIP + (符号地址 - RIP符号地址)
}
```

这是**运行时动态计算**：
- 基于当前 RIP 的位置
- 计算 `gdt_page` 相对于 RIP 的偏移
- 得到当前可访问的实际地址

##### 使用场景示例

假设：
- 内核链接地址（最终虚拟地址）：`0xFFFFFFFF81000000`
- 当前运行地址（early startup_64）：`0x0000000001000000`
- `gdt_page` 在镜像中的偏移：`+0x1345000`

**场景 1：startup_64 早期（还在低地址运行）**

```
当前状态：
  - 代码运行在物理地址：0x0000000001100000
  - 页表只映射了 Identity Mapping（VA = PA）
  - gdt_page 实际位置：0x0000000001345000

方案 A - 使用 INIT_PER_CPU_VAR(gdt_page)：
  early_gdt_descr_base = 0xFFFFFFFF82345000  ← 链接时地址
  lgdt early_gdt_descr
  ❌ 错误！此地址还未映射 → #PF (Page Fault)

方案 B - 使用 rip_rel_ptr(&gdt_page)：
  当前 RIP ≈ 0x0000000001100000
  offset = &gdt_page - &current_code = 0x1345000 - 0x1100000 = 0x245000
  实际地址 = RIP + offset = 0x0000000001100000 + 0x245000 = 0x0000000001345000
  ✅ 正确！能访问到 gdt_page
```

**场景 2：切换到高地址映射后**

```
当前状态：
  - 代码运行在虚拟地址：0xFFFFFFFF81100000
  - 页表已建立 Direct Mapping
  - gdt_page 虚拟地址：0xFFFFFFFF82345000

方案 A - 使用 INIT_PER_CPU_VAR(gdt_page)：
  early_gdt_descr_base = 0xFFFFFFFF82345000
  lgdt early_gdt_descr
  ✅ 正确！链接地址有效

方案 B - 使用 rip_rel_ptr(&gdt_page)：
  当前 RIP ≈ 0xFFFFFFFF81100000
  offset = 0x1345000 - 0x1100000 = 0x245000
  实际地址 = RIP + offset = 0xFFFFFFFF81100000 + 0x245000
            = 0xFFFFFFFF81345000
  ⚠️  错误计算！应该是 0xFFFFFFFF82345000

  (实际上 rip_rel_ptr 在这种情况下也能正确工作，
   因为它考虑了符号的实际链接地址)
```

##### 时间线上的使用

```
T1: startup_64 开始
    ├─ 状态：运行在低地址 (0x01xxxxxx)
    ├─ 使用：压缩内核的 boot_gdt
    └─ 页表：只有 Identity Mapping

T2: 调用 startup_64_setup_gdt_idt()  ← 使用 rip_rel_ptr()
    ├─ 目的：切换到主内核的 gdt_page
    ├─ 问题：代码还在低地址，链接地址无效
    ├─ 解决：rip_rel_ptr() 计算当前可访问地址
    └─ 结果：lgdt 加载成功 ✅

T3: 建立高地址映射
    └─ 创建 Direct Mapping（VA = PA + PAGE_OFFSET）

T4: 跳转到高地址内核代码
    ├─ 从 0x01xxxxxx 跳转到 0xFFFFFFFF81xxxxxx
    └─ 此后代码运行在最终虚拟地址

T5: 之后的代码可以使用 early_gdt_descr
    ├─ 前提：已在高地址运行
    ├─ 优势：简单，不需要运行时计算
    └─ 示例：某些汇编代码直接 lgdt early_gdt_descr
```

##### 为什么需要两种方式？

**startup_64_setup_gdt_idt() 的必要性**：

```
问题场景：
  - startup_64 刚进入时，代码在物理地址 0x01000000 执行
  - gdt_page 在物理地址 0x01345000
  - 但链接器认为 gdt_page 在 0xFFFFFFFF82345000
  - 如果直接用链接地址 → #PF（页面不存在）

解决方案：
  - 使用 RIP 相对寻址
  - 无论代码在低地址还是高地址，都能正确找到 gdt_page
  - 这是早期启动代码的关键技术
```

**early_gdt_descr 的便利性**：

```
适用场景：
  - 内核已经运行在最终虚拟地址
  - 链接地址已经有效
  - 不需要运行时计算

优势：
  - 静态定义，编译时确定
  - 汇编代码可以直接使用：lgdt early_gdt_descr
  - 代码简单，不需要函数调用
```

##### 它们指向同一个 GDT 表吗？

**是的！** 两者最终都指向 `gdt_page` 这块内存，但：

```
物理内存中的 gdt_page：
  ┌─────────────────────────────┐
  │ 物理地址：0x01345000        │  ← 实际内存位置
  │ 内容：GDT_ENTRIES 个段描述符 │
  └─────────────────────────────┘
           ↑              ↑
           │              │
  低地址映射│              │高地址映射
  (Identity)│              │(Direct)
           │              │
  VA: 0x01345000    VA: 0xFFFFFFFF82345000
      ↑                    ↑
      │                    │
  rip_rel_ptr()      INIT_PER_CPU_VAR()
  计算结果            链接时地址
```

**关键理解**：
- `gdt_page` 只有**一块物理内存**
- 在不同时刻，可以通过**不同的虚拟地址**访问
- `rip_rel_ptr()` 适应当前地址空间
- `INIT_PER_CPU_VAR()` 使用最终地址空间

##### 实际代码验证

**使用 startup_64_setup_gdt_idt()**：

```c
// arch/x86/kernel/head_64.S
startup_64:
    // ... 早期初始化 ...
    call startup_64_setup_gdt_idt  // ← 使用 rip_rel_ptr()
    // GDT 已切换到 gdt_page
```

**使用 early_gdt_descr**：

```assembly
// 某些晚期汇编代码
some_function:
    lgdt early_gdt_descr      // ← 直接使用静态定义
    // 前提：已在高地址运行
```

##### 总结

| 方面 | startup_64_setup_gdt_idt | early_gdt_descr |
|------|-------------------------|-----------------|
| **核心技术** | RIP 相对寻址 | 链接时地址 |
| **关键优势** | 位置无关 | 简单直接 |
| **使用前提** | 无要求 | 必须在最终地址 |
| **典型用途** | 早期启动（切换GDT） | 晚期代码（重载GDT） |
| **实现方式** | C 函数 + 内联汇编 | 纯汇编数据 |

**关键要点**：
1. 两者都指向 `gdt_page`，但计算地址的方式不同
2. `startup_64_setup_gdt_idt()` 是早期启动的关键，使用 RIP 相对寻址
3. `early_gdt_descr` 是便利工具，适用于已在最终地址的代码
4. 这体现了内核启动过程中地址空间切换的复杂性

> **相关章节**：
> - **1.3** - startup_64_setup_gdt_idt() 详细实现
> - **演化篇 4.1** - 主内核 GDT 演化过程
> - **理论篇 1.2** - GDT 描述符结构

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

### 2.1 压缩内核页表建立详解

**位置**：`arch/x86/boot/compressed/head_64.S`

**上下文**：startup_32 在保护模式（32位）下运行，负责建立初始的4级页表，然后切换到长模式（64位）。

#### 页表内存布局规划

在深入代码前，先了解页表在内存中的布局：

```
【pgtable 内存布局】（6 页 = 24KB）

偏移 0x0000:  ┌─────────────────────────────┐
              │ PML4（Page Map Level 4）    │  1 页（4KB）
              │ - 512 个 8 字节条目          │  只使用 PML4[0]
偏移 0x1000:  ├─────────────────────────────┤
              │ PDPT（Page Directory        │  1 页（4KB）
              │       Pointer Table）       │  使用 PDPT[0-3]（映射4GB）
偏移 0x2000:  ├─────────────────────────────┤
              │ PD0（Page Directory 0）     │  1 页（4KB）
              │ - 映射 0-1GB                │  512 个 2MB 大页
偏移 0x3000:  ├─────────────────────────────┤
              │ PD1（Page Directory 1）     │  1 页（4KB）
              │ - 映射 1-2GB                │  512 个 2MB 大页
偏移 0x4000:  ├─────────────────────────────┤
              │ PD2（Page Directory 2）     │  1 页（4KB）
              │ - 映射 2-3GB                │  512 个 2MB 大页
偏移 0x5000:  ├─────────────────────────────┤
              │ PD3（Page Directory 3）     │  1 页（4KB）
              │ - 映射 3-4GB                │  512 个 2MB 大页
              └─────────────────────────────┘

【为什么这样设计】：
1. 使用 2MB 大页（不需要 PT 级别）：
   - 简化页表结构（只需 3 级）
   - 减少 TLB Miss（一个 TLB 条目覆盖 2MB）
   - 足够映射压缩内核需要的内存（通常 < 100MB）

2. 映射完整 4GB：
   - Identity Mapping：虚拟地址 = 物理地址
   - 允许访问低端内存（BIOS、设备、启动参数等）
   - 为后续代码提供简单的地址转换

3. 页表布局连续：
   - 方便用一个 rva(pgtable) 符号定位
   - 简化地址计算（基址 + 偏移）
```

#### 详细代码注释

```asm
SYM_FUNC_START(startup_32)
    # ... 前面的代码（GDT 设置、进入保护模式等）...

    /*
     * 步骤 1：计算页表位置
     *
     * 【rva() 宏】：Relocatable Virtual Address（可重定位虚拟地址）
     * - 定义：#define rva(X) ((X) - __START_KERNEL_map)
     * - 作用：将链接地址转换为相对地址
     *
     * 【为什么需要 rva()】：
     * - pgtable 符号的链接地址是高地址（如 0xffffffff81234000）
     * - 但当前运行在低地址物理内存（如 0x01000000）
     * - rva(pgtable) 计算出相对于内核起始的偏移
     * - 加上 %ebx（内核加载的物理基址）得到真实物理地址
     *
     * 【寄存器状态】：
     * %ebx = 内核镜像的物理加载基址（由 GRUB 传入，如 0x01000000）
     * %edi = pgtable 的物理地址（如 0x01234000）
     */
    leal    rva(pgtable)(%ebx), %edi

    /*
     * 步骤 2：清零页表区域
     *
     * 【为什么清零】：
     * - 页表区域可能包含随机数据（内存未初始化）
     * - 页表项的 P 位（bit 0）如果是 1，CPU 会认为页存在
     * - 必须全部清零，然后只设置需要的条目
     *
     * 【BOOT_PGT_SIZE】：
     * - 定义：6 * 4096 = 24576 字节
     * - 包含：1 PML4 + 1 PDPT + 4 PD
     *
     * 【rep stosl 指令】：
     * - 功能：重复执行 stosl（Store String Long）
     * - stosl：将 EAX 存入 [EDI]，然后 EDI += 4
     * - rep：重复 ECX 次
     * - 结果：将 24576 字节（6144 个双字）全部写 0
     *
     * 【计算】：
     * BOOT_PGT_SIZE >> 2 = 24576 / 4 = 6144（双字数）
     */
    xorl    %eax, %eax                    # EAX = 0（要写入的值）
    movl    $(BOOT_PGT_SIZE >> 2), %ecx   # ECX = 6144（循环次数）
    rep     stosl                         # 将 6144 个双字（0）写入 [EDI]

    /*
     * 步骤 3：设置 PML4[0] 指向 PDPT
     *
     * 【页表层次结构】：
     * CR3 → PML4[0] → PDPT[0-3] → PD0-3[0-511] → 2MB 物理页
     *
     * 【PML4 表项格式】（只设置关键位）：
     * Bit 63-12: 物理页框号（PDPT 的物理地址 / 4096）
     * Bit 11-2:  保留/可用
     * Bit 1:     R/W = 1（可读写）
     * Bit 0:     P = 1（存在）
     *
     * 【地址计算】：
     * PML4 基址 = pgtable 物理地址（如 0x01234000）
     * PDPT 基址 = PML4 基址 + 0x1000 = 0x01235000
     *
     * 【0x03 标志位】：
     * 0x03 = 0000 0011（二进制）
     *      = P(1) | R/W(1)
     * - Bit 0 (P=1):   页存在于内存
     * - Bit 1 (R/W=1): 可读写
     * - Bit 2 (U/S=0): 超级用户（内核）模式（隐含，未设置）
     */
    leal    rva(pgtable)(%ebx), %edi     # EDI = PML4 基址
    leal    0x1000(%edi), %eax            # EAX = PDPT 基址（PML4 + 4KB）
    orl     $0x03, %eax                   # EAX |= 0x03（Present + R/W）
    movl    %eax, 0(%edi)                 # PML4[0] = PDPT 地址 | 0x03

    /*
     * 步骤 4：设置 PDPT[0-3] 指向 4 个 PD 表
     *
     * 【为什么需要 4 个 PDPT 条目】：
     * - 每个 PDPT 条目覆盖：512 × 512 × 2MB = 512GB（如果用小页）
     * - 但这里用 2MB 大页，每个 PD 条目直接映射 2MB
     * - 每个 PDPT 条目管理一个 PD（512 个 2MB 页 = 1GB）
     * - 4 个 PDPT 条目 → 4 个 PD → 4GB 物理内存
     *
     * 【循环结构】：
     * for (i = 0; i < 4; i++) {
     *     PDPT[i] = (PD_base + i * 4096) | 0x03;
     * }
     *
     * 【地址布局】：
     * PDPT[0] → PD0（偏移 0x2000，映射 0-1GB）
     * PDPT[1] → PD1（偏移 0x3000，映射 1-2GB）
     * PDPT[2] → PD2（偏移 0x4000，映射 2-3GB）
     * PDPT[3] → PD3（偏移 0x5000，映射 3-4GB）
     */
    leal    0x1000(%edi), %edi            # EDI = PDPT 基址（PML4 + 4KB）
    leal    0x1000(%edi), %eax            # EAX = 第一个 PD 基址（PDPT + 4KB）
    orl     $0x03, %eax                   # EAX |= 0x03（Present + R/W）
    movl    $4, %ecx                      # ECX = 4（循环 4 次）
1:  movl    %eax, 0(%edi)                 # PDPT[i] = PD 地址 | 0x03
    addl    $0x1000, %eax                 # EAX += 4096（下一个 PD）
    addl    $8, %edi                      # EDI += 8（下一个 PDPT 条目）
    decl    %ecx                          # ECX--
    jnz     1b                            # 如果 ECX != 0，跳转到标签 1

    /*
     * 步骤 5：设置 4 个 PD 表，每个包含 512 个条目（2MB 大页）
     *
     * 【2MB 大页模式】：
     * - 不使用 PT（Page Table）级别
     * - PD 条目直接指向 2MB 物理页框
     * - 通过 PS 位（Page Size，Bit 7）启用
     *
     * 【PD 表项格式（2MB 大页）】：
     * Bit 63:    NX（No Execute，需要 EFER.NXE=1）
     * Bit 51-21: 物理页框号（2MB 对齐，21 位页内偏移）
     * Bit 12-9:  AVL（可用）
     * Bit 8:     G（Global，TLB 不刷新）
     * Bit 7:     PS = 1（2MB 大页）
     * Bit 6:     D（Dirty）
     * Bit 5:     A（Accessed）
     * Bit 4:     PCD（Cache Disable）
     * Bit 3:     PWT（Write-Through）
     * Bit 2:     U/S（User/Supervisor）
     * Bit 1:     R/W = 1（可读写）
     * Bit 0:     P = 1（存在）
     *
     * 【0x00000083 标志位】：
     * 0x83 = 1000 0011（二进制）
     *      = PS(1) | R/W(1) | P(1)
     * - Bit 0 (P=1):   页存在
     * - Bit 1 (R/W=1): 可读写
     * - Bit 7 (PS=1):  2MB 大页
     *
     * 【循环计算】：
     * - 2048 个 PD 条目（4 个 PD × 512 条目/PD）
     * - 每个条目映射 2MB
     * - 总计：2048 × 2MB = 4096MB = 4GB
     *
     * 【Identity Mapping】：
     * 虚拟地址           PD 条目                物理地址
     * 0x00000000  →  PD0[0] = 0x00000083  →  0x00000000
     * 0x00200000  →  PD0[1] = 0x00200083  →  0x00200000
     * 0x00400000  →  PD0[2] = 0x00400083  →  0x00400000
     * ...
     * 0x3FE00000  →  PD1[511]= 0x3FE00083  →  0x3FE00000
     * 0x40000000  →  PD2[0] = 0x40000083  →  0x40000000
     * ...
     * 0xFFE00000  →  PD3[511]= 0xFFE00083  →  0xFFE00000
     */
    leal    rva(pgtable)(%ebx), %edi
    addl    $0x2000, %edi                 # EDI = 第一个 PD 基址（pgtable + 8KB）
    movl    $0x00000083, %eax             # EAX = 物理地址 0 | PS | R/W | P
    movl    $2048, %ecx                   # ECX = 2048（4 个 PD × 512 条目）
1:  movl    %eax, 0(%edi)                 # PD[i] = 物理地址 | 0x83
    addl    $0x200000, %eax               # EAX += 2MB（下一个 2MB 页）
    addl    $8, %edi                      # EDI += 8（下一个 PD 条目）
    decl    %ecx                          # ECX--
    jnz     1b                            # 如果 ECX != 0，继续循环

    /*
     * 步骤 6：加载 CR3 寄存器
     *
     * 【CR3 寄存器】（Control Register 3）：
     * - 也称为 PDBR（Page Directory Base Register）
     * - 存储 PML4 表的物理基址
     * - 只有高 52 位有效（低 12 位必须为 0，因为页对齐）
     *
     * 【CR3 格式】（x86-64）：
     * Bit 63-52: 保留（必须为 0）
     * Bit 51-12: PML4 表的物理地址（4KB 对齐）
     * Bit 11-5:  保留（忽略）
     * Bit 4:     PCD（Page-level Cache Disable）
     * Bit 3:     PWT（Page-level Write-Through）
     * Bit 2-0:   保留（忽略）
     *
     * 【加载 CR3 的效果】：
     * 1. CPU 的 MMU 从此使用新页表
     * 2. TLB（Translation Lookaside Buffer）被刷新
     * 3. 后续所有内存访问都会通过页表转换
     *
     * 【注意】：
     * - 此时分页还未启用（CR0.PG = 0）
     * - 需要在后续代码中设置 CR0.PG = 1 才真正启用分页
     * - 但 CR3 必须在启用分页之前设置好
     */
    leal    rva(pgtable)(%ebx), %eax     # EAX = PML4 物理基址
    movl    %eax, %cr3                    # CR3 = PML4 基址

    # ... 后面的代码（设置 EFER.LME、启用分页、跳转到 64 位代码）...
SYM_FUNC_END(startup_32)
```

#### 页表建立后的内存映射

```
【虚拟地址到物理地址的转换示例】

虚拟地址：0x01234567（18MB + 偏移）

拆分虚拟地址（4 级页表索引）：
┌─────────┬─────────┬─────────┬─────────┬─────────────┐
│ PML4    │ PDPT    │ PD      │ PT      │   Offset    │
│ [47:39] │ [38:30] │ [29:21] │ [20:12] │   [11:0]    │
│    0    │    0    │    9    │   26    │   0x567     │
└─────────┴─────────┴─────────┴─────────┴─────────────┘
（注：PT 索引在 2MB 大页模式下被合并到 Offset）

实际转换（2MB 大页）：
┌─────────┬─────────┬─────────┬───────────────────────┐
│ PML4    │ PDPT    │ PD      │  Offset (21 bits)     │
│ [47:39] │ [38:30] │ [29:21] │      [20:0]           │
│    0    │    0    │    9    │     0x034567          │
└─────────┴─────────┴─────────┴───────────────────────┘

转换步骤：
1. CR3 → PML4 基址：0x01234000
2. PML4[0] → PDPT 基址：0x01235000（PML4[0] & ~0xFFF）
3. PDPT[0] → PD0 基址：0x01236000（PDPT[0] & ~0xFFF）
4. PD0[9] → 2MB 页基址：0x01200000（9 × 2MB = 18MB）
   （PD0[9] = 0x01200083，物理页框号 = 0x01200000）
5. 物理地址 = 0x01200000 + 0x034567 = 0x01234567

结果：虚拟地址 0x01234567 → 物理地址 0x01234567（Identity Mapping）
```

#### 关键设计决策总结

| 设计决策 | 原因 |
|---------|------|
| **使用 2MB 大页** | 简化页表（3级而非4级），减少 TLB Miss，足够覆盖压缩内核 |
| **映射完整 4GB** | 简化地址计算，兼容性（访问低端设备和BIOS数据） |
| **Identity Mapping** | 启用分页前后代码无缝运行（物理地址=虚拟地址） |
| **静态页表布局** | 编译时确定大小（6页），避免动态分配的复杂性 |
| **只使用 PML4[0]** | 4GB 内存只需一个 PML4 条目，其他 511 个条目保留 |

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
