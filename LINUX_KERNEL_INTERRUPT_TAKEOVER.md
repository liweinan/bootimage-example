# Linux 内核中断系统接管详细流程

本文档详细说明 Linux 内核如何从 BIOS 接管中断系统，包括早期 IDT 设置、8259A PIC 重新编程、APIC 和中断门设置，以及 INT 0x80 系统调用的完整实现路径。

> **相关文档**：启动流程概述见 [BOOT_FLOW.md](BOOT_FLOW.md)；GRUB 跳转与 code32_start 字段、压缩内核入口见 [GRUB_KERNEL_LOADING.md](GRUB_KERNEL_LOADING.md)、[LINUX_KERNEL_EARLY_BOOT.md](LINUX_KERNEL_EARLY_BOOT.md)；start_kernel() 之后初始化见 [LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md)。若需了解内核**运行时**的中断处理模型（Top Half/Bottom Half、softirq/tasklet/workqueue），见 [Linux 内核中断处理：Top Half 和 Bottom Half](LINUX_INTERRUPT_HANDLING.md)。
>
> **阅读说明**：本系列三篇文档按启动顺序为 EARLY_BOOT → INTERRUPT_TAKEOVER → INIT；时间线简表见 [BOOT_FLOW.md 相关文档索引](BOOT_FLOW.md#相关文档索引)。

## 早期 IDT 设置

**调用时机**：`x86_64_start_kernel()`（early boot 末尾，见 [LINUX_KERNEL_EARLY_BOOT.md](LINUX_KERNEL_EARLY_BOOT.md)）。

源代码位置：`linux/arch/x86/kernel/head64.c:276-292`

```c
	// 步骤 1: 设置早期中断处理程序
	// 建立内核自己的 IDT，取代 BIOS 的 IVT
	// 此时中断将路由到内核处理程序，而不是 BIOS
	idt_setup_early_handler();

	// 步骤 2: TDX（Trust Domain Extensions）早期初始化
	// 在调用 cc_platform_has() 之前需要完成
	tdx_early_init();

	// 步骤 3: 复制引导数据（从实模式数据区域）
	copy_bootdata(__va(real_mode_data));

	// 步骤 4: 在启动 CPU（BSP）上早期加载微码更新
	// 微码更新修复 CPU 硬件缺陷，必须在早期加载
	load_ucode_bsp();

	// 步骤 5: 设置内核高地址映射
	// 将 early_top_pgt 的最后一个条目复制到 init_top_pgt
	init_top_pgt[511] = early_top_pgt[511];

	// 步骤 6: 启动内核预留区域初始化，最终调用 start_kernel()
	x86_64_start_reservations(real_mode_data);
}
```

**关键点：**
- **第 276 行**：`idt_setup_early_handler()` 设置早期中断处理程序

源代码位置：`linux/arch/x86/kernel/idt.c:216-227`

```c
/**
 * idt_setup_early_traps - 初始化 IDT 表，设置早期陷阱处理程序
 *
 * 在 x86_64 上，这些陷阱不使用中断栈（IST），因为在 cpu_init() 调用
 * 并设置 TSS 之前无法工作。IST 变体在那之后安装。
 */
void __init idt_setup_early_traps(void)
{
	// 步骤 1: 从 early_idts 表设置 IDT 条目
	// early_idts 包含早期需要的异常处理程序（如页故障、除零等）
	idt_setup_from_table(idt_table, early_idts, ARRAY_SIZE(early_idts),
			     true);
	
	// 步骤 2: 加载 IDT 到 CPU
	// 使用 LIDT 指令将 idt_descr 加载到 IDTR 寄存器
	// 从这一刻起，CPU 使用内核的 IDT 而不是 BIOS 的 IVT
	load_idt(&idt_descr);
}
```

**说明：**
- 内核建立自己的 IDT（中断描述符表），取代 BIOS 的 IVT
- 早期陷阱处理程序用于处理 CPU 异常（如页故障、除零等）

### 中断控制器接管

#### 8259A PIC 重新编程

源代码位置：`linux/arch/x86/kernel/i8259.c:349-399`

```c
// 重新编程 8259A PIC：将硬件中断从 BIOS 的向量（0x08-0x0F, 0x70-0x77）
// 重映射到内核的向量（0x20-0x2F），避免与 CPU 异常向量（0-31）冲突
static void init_8259A(int auto_eoi)
{
	unsigned long flags;

	i8259A_auto_eoi = auto_eoi;  // 保存自动 EOI 设置

	raw_spin_lock_irqsave(&i8259A_lock, flags);  // 加锁保护

	// 步骤 1: 屏蔽主 PIC 的所有中断（0xFF = 所有位都屏蔽）
	outb(0xff, PIC_MASTER_IMR);

	// 步骤 2: 初始化主 PIC（8259A-1）
	// ICW1: 0x11 = 边沿触发、级联模式、需要 ICW4
	outb_pic(0x11, PIC_MASTER_CMD);

	// ICW2: 将主 PIC 的 IRQ0-7 映射到 ISA_IRQ_VECTOR(0)（通常是 0x20-0x27）
	// 这覆盖了 BIOS 的配置（BIOS 映射到 0x08-0x0F）
	outb_pic(ISA_IRQ_VECTOR(0), PIC_MASTER_IMR);

	// ICW3: 主 PIC 在 IR2 上有从 PIC（级联）
	outb_pic(1U << PIC_CASCADE_IR, PIC_MASTER_IMR);

	// ICW4: 设置主 PIC 的工作模式
	if (auto_eoi)
		// 自动 EOI 模式：中断处理完成后自动发送 EOI
		outb_pic(MASTER_ICW4_DEFAULT | PIC_ICW4_AEOI, PIC_MASTER_IMR);
	else
		// 正常 EOI 模式：需要手动发送 EOI
		outb_pic(MASTER_ICW4_DEFAULT, PIC_MASTER_IMR);

	// 步骤 3: 初始化从 PIC（8259A-2）
	// ICW1: 选择从 PIC 初始化
	outb_pic(0x11, PIC_SLAVE_CMD);

	// ICW2: 将从 PIC 的 IRQ8-15 映射到 ISA_IRQ_VECTOR(8)（通常是 0x28-0x2F）
	// 这覆盖了 BIOS 的配置（BIOS 映射到 0x70-0x77）
	outb_pic(ISA_IRQ_VECTOR(8), PIC_SLAVE_IMR);
	
	// ICW3: 从 PIC 连接到主 PIC 的 IR2
	outb_pic(PIC_CASCADE_IR, PIC_SLAVE_IMR);
	
	// ICW4: 设置从 PIC 的工作模式
	outb_pic(SLAVE_ICW4_DEFAULT, PIC_SLAVE_IMR);

	// 步骤 4: 根据 EOI 模式设置中断确认函数
	if (auto_eoi)
		// AEOI 模式：确认时只需屏蔽中断
		i8259A_chip.irq_mask_ack = disable_8259A_irq;
	else
		// 正常模式：确认时需要屏蔽并发送 EOI
		i8259A_chip.irq_mask_ack = mask_and_ack_8259A;

	// 步骤 5: 等待 PIC 初始化完成（硬件需要时间）
	udelay(100);

	// 步骤 6: 恢复之前保存的中断屏蔽位
	outb(cached_master_mask, PIC_MASTER_IMR);
	outb(cached_slave_mask, PIC_SLAVE_IMR);

	raw_spin_unlock_irqrestore(&i8259A_lock, flags);  // 解锁
}
```

**关键点：**
- **第 365 行**：将主 PIC 的 IRQ0-7 重映射到 `ISA_IRQ_VECTOR(0)`（通常是 0x20-0x27），避免与 CPU 异常向量（0-31）冲突
- **第 378 行**：将从 PIC 的 IRQ8-15 重映射到 `ISA_IRQ_VECTOR(8)`（通常是 0x28-0x2F）
- 这**完全覆盖了 BIOS 的 PIC 配置**，硬件中断不再路由到 BIOS 代码

#### APIC 和中断门设置

**重要说明：APIC vs 8259A PIC**

- **8259A PIC**：外部芯片，用于处理硬件中断（IRQ0-15），已在前面重新编程
- **Local APIC**：CPU 内部集成的中断控制器，用于：
  - 多处理器系统中的处理器间中断（IPI）
  - 本地定时器中断
  - 性能计数器中断
  - 热中断等
- **两者关系**：在现代系统中，Local APIC 可以替代或配合 8259A PIC 工作

源代码位置：`linux/arch/x86/kernel/idt.c:281-315`

```c
/**
 * idt_setup_apic_and_irq_gates - 设置 APIC/SMP 和普通中断门
 * 
 * 这是内核完全接管中断系统的最后一步：
 * 1. 设置 APIC 相关的中断门（Local APIC，CPU 内部集成）
 * 2. 为所有外部中断（IRQ）设置中断门
 * 3. 加载 IDT，此时 BIOS 的 IVT 被完全取代
 */
void __init idt_setup_apic_and_irq_gates(void)
{
	int i = FIRST_EXTERNAL_VECTOR;  // 第一个外部中断向量（通常是 0x20）
	void *entry;

	// 步骤 1: 从 apic_idts 表设置 APIC 相关的中断门
	// 包括本地 APIC 中断（CPU 内部集成）、SMP IPI 等
	// 注意：这是 Local APIC，不是 8259A PIC
	idt_setup_from_table(idt_table, apic_idts, ARRAY_SIZE(apic_idts), true);

	// 步骤 2: 为所有外部中断（IRQ）设置中断门
	// FIRST_EXTERNAL_VECTOR 到 FIRST_SYSTEM_VECTOR 是 IRQ 向量范围
	for_each_clear_bit_from(i, system_vectors, FIRST_SYSTEM_VECTOR) {
		// 计算中断入口地址：irq_entries_start + 对齐偏移
		entry = irq_entries_start + IDT_ALIGN * (i - FIRST_EXTERNAL_VECTOR);
		set_intr_gate(i, entry);  // 设置中断门（自动关闭中断）
	}

#ifdef CONFIG_X86_LOCAL_APIC
	// 步骤 3: 为系统向量设置中断门（APIC 伪中断等）
	for_each_clear_bit_from(i, system_vectors, NR_VECTORS) {
		// 不设置 system_vectors 位图中未分配的系统向量
		// 否则它们会出现在 /proc/interrupts 中
		entry = spurious_entries_start + IDT_ALIGN * (i - FIRST_SYSTEM_VECTOR);
		set_intr_gate(i, entry);
	}
#endif
	
	// 步骤 4: 将 IDT 映射到 CPU 入口区域并重新加载
	// CPU 入口区域是内核中的固定只读区域，用于存放 IDT 等关键数据结构
	idt_map_in_cea();
	load_idt(&idt_descr);  // 加载 IDT：此时 BIOS IVT 被完全取代
```

**`load_idt` 函数定义：**

**源代码位置：** `linux/arch/x86/include/asm/desc.h:112-115`

```c
// load_idt 是一个宏定义，实际调用 native_load_idt
#define load_idt(dtr)    native_load_idt(dtr)
```

**源代码位置：** `linux/arch/x86/include/asm/desc.h:213-216`

```c
// native_load_idt - 加载 IDT 到 CPU 的 IDTR 寄存器
static __always_inline void native_load_idt(const struct desc_ptr *dtr)
{
    asm volatile("lidt %0"::"m" (*dtr));  // 执行 LIDT 指令
}
```

**`desc_ptr` 结构定义：**

**源代码位置：** `linux/arch/x86/include/asm/desc_defs.h:164-167`

```c
// desc_ptr - 描述符表指针结构（用于 GDT 和 IDT）
struct desc_ptr {
    unsigned short size;      // 表的大小（字节数 - 1）
    unsigned long address;     // 表的基址
} __attribute__((packed));
```

**`idt_table` 和 `idt_descr` 定义：**

**源代码位置：** `linux/arch/x86/kernel/idt.c:173-178`

```c
// idt_table - IDT 表本身（256 个条目，每个 16 字节，共 4KB）
static gate_desc idt_table[IDT_ENTRIES] __page_aligned_bss;

// idt_descr - IDT 描述符（包含 IDT 的基址和大小）
static struct desc_ptr idt_descr __ro_after_init = {
    .size    = IDT_TABLE_SIZE - 1,           // IDT 大小 - 1（4096 - 1 = 4095）
    .address = (unsigned long) idt_table,    // IDT 表的基址
};
```

**`gate_desc` 结构定义（中断描述符）：**

**源代码位置：** `linux/arch/x86/include/asm/desc_defs.h:134-143`

```c
// gate_struct - 中断门描述符结构（64位）
struct gate_struct {
    u16         offset_low;      // 处理程序地址的低 16 位
    u16         segment;         // 段选择子（通常是 __KERNEL_CS）
    struct idt_bits bits;         // 中断门属性（类型、DPL、P 位等）
    u16         offset_middle;   // 处理程序地址的中 16 位
    u32         offset_high;     // 处理程序地址的高 32 位（64位模式）
    u32         reserved;         // 保留字段
} __attribute__((packed));

typedef struct gate_struct gate_desc;
```

**`idt_bits` 结构定义（中断门属性）：**

**源代码位置：** `linux/arch/x86/include/asm/desc_defs.h:119-125`

```c
// idt_bits - 中断描述符的属性位
struct idt_bits {
    u16 ist   : 3,    // IST（Interrupt Stack Table）索引
    zero  : 5,    // 保留位
    type  : 5,    // 门类型（中断门、陷阱门、任务门）
    dpl   : 2,    // 描述符特权级（0=内核，3=用户）
    p     : 1;    // 存在位（1=有效，0=无效）
} __attribute__((packed));
```

**`idt_table` 的内容填充：**

`idt_table` 的内容不是静态定义的，而是通过函数动态填充的：

**源代码位置：** `linux/arch/x86/kernel/idt.c:193-204`

```c
// idt_setup_from_table - 从 idt_data 表填充 IDT
static __init void
idt_setup_from_table(gate_desc *idt, const struct idt_data *t, int size, bool sys)
{
    gate_desc desc;
    
    for (; size > 0; t++, size--) {
        idt_init_desc(&desc, t);              // 将 idt_data 转换为 gate_desc
        write_idt_entry(idt, t->vector, &desc); // 写入到 idt_table[t->vector]
        if (sys)
            set_bit(t->vector, system_vectors);
    }
}
```

**填充 `idt_table` 的数据源：**

1. **早期陷阱（early_idts）**：
   - **源代码位置：** `linux/arch/x86/kernel/idt.c:63-76`
   - 包含：调试异常（X86_TRAP_DB）、断点异常（X86_TRAP_BP）等
   - 在 `idt_setup_early_traps()` 中使用

2. **默认陷阱（def_idts）**：
   - **源代码位置：** `linux/arch/x86/kernel/idt.c:84-109`
   - 包含：除零错误、页故障、通用保护错误等所有 CPU 异常
   - 在 `idt_setup_traps()` 中使用

3. **APIC 中断（apic_idts）**：
   - **源代码位置：** `linux/arch/x86/kernel/idt.c:112-169`
   - 包含：Local APIC 相关的中断
   - 在 `idt_setup_apic_and_irq_gates()` 中使用

4. **IRQ 中断（动态设置）**：
   - 在 `idt_setup_apic_and_irq_gates()` 中通过循环动态设置
   - 为每个 IRQ 向量设置中断门，指向 `irq_entries_start`

5. **系统调用（INT 0x80）**：
   - **源代码位置：** `linux/arch/x86/kernel/idt.c:122-128`
   - 在 `ia32_idt[]` 表中定义：`SYSG(IA32_SYSCALL_VECTOR, entry_INT80_32)`
   - `IA32_SYSCALL_VECTOR` = 0x80（定义在 `arch/x86/include/asm/irq_vectors.h:38`）
   - 在 `idt_setup_ia32_syscall_gate()` 中设置到 IDT[0x80]

**INT 0x80 系统调用的完整实现路径：**

**1. IDT 设置（源代码位置：`linux/arch/x86/kernel/idt.c:122-128`）：**

```c
// ia32_idt - 32位系统调用 IDT 条目
static const struct idt_data ia32_idt[] __initconst = {
#if defined(CONFIG_IA32_EMULATION)
    SYSG(IA32_SYSCALL_VECTOR, asm_int80_emulation),  // 64位内核的 32位兼容模式
#elif defined(CONFIG_X86_32)
    SYSG(IA32_SYSCALL_VECTOR, entry_INT80_32),      // 32位内核
#endif
};
```

**2. 汇编入口点（源代码位置：`linux/arch/x86/entry/entry_32.S:933-983`）：**

```asm
// entry_INT80_32 - INT 0x80 系统调用的汇编入口点
SYM_FUNC_START(entry_INT80_32)
    ASM_CLAC
    pushl   %eax                    // 保存系统调用号（orig_ax）
    
    SAVE_ALL pt_regs_ax=$-ENOSYS switch_stacks=1  // 保存所有寄存器到 pt_regs
    
    movl    %esp, %eax              // 传递 pt_regs 指针
    call    do_int80_syscall_32     // 调用 C 处理函数
    
    // 恢复用户态并返回
    RESTORE_REGS pop=4
    CLEAR_CPU_BUFFERS
    iret                            // 返回到用户空间
SYM_FUNC_END(entry_INT80_32)
```

**3. C 处理函数（源代码位置：`linux/arch/x86/entry/syscall_32.c:246-263`）：**

```c
// do_int80_syscall_32 - INT 0x80 的 C 处理函数
__visible noinstr void do_int80_syscall_32(struct pt_regs *regs)
{
    int nr = syscall_32_enter(regs);  // 获取系统调用号（从 regs->orig_ax）
    
    // 系统调用入口处理（审计、跟踪等）
    nr = syscall_enter_from_user_mode(regs, nr);
    
    // 执行系统调用
    do_syscall_32_irqs_on(regs, nr);
    
    // 系统调用退出处理
    syscall_exit_to_user_mode(regs);
}
```

**4. 系统调用分发（源代码位置：`linux/arch/x86/entry/syscall_32.c:73-87`）：**

```c
// do_syscall_32_irqs_on - 执行 32 位系统调用
static __always_inline void do_syscall_32_irqs_on(struct pt_regs *regs, int nr)
{
    unsigned int unr = nr;
    
    if (likely(unr < IA32_NR_syscalls)) {
        unr = array_index_nospec(unr, IA32_NR_syscalls);
        regs->ax = ia32_sys_call(regs, unr);  // 调用实际的系统调用函数
    } else {
        regs->ax = __ia32_sys_ni_syscall(regs);  // 无效的系统调用号
    }
}
```

**5. 系统调用表（源代码位置：`linux/arch/x86/entry/syscall_32.c:44-50`）：**

```c
// ia32_sys_call - 根据系统调用号分发到具体函数
long ia32_sys_call(const struct pt_regs *regs, unsigned int nr)
{
    switch (nr) {
        #include <asm/syscalls_32.h>  // 包含所有系统调用的 case 语句
        // 例如：case 1: return __ia32_sys_exit(regs);
        //      case 3: return __ia32_sys_read(regs);
        //      ...
        default: return __ia32_sys_ni_syscall(regs);  // 无效的系统调用
    }
}
```

**INT 0x80 系统调用的完整流程：**

```
用户空间程序执行 INT 0x80
    ↓
CPU 查找 IDT[0x80]（在 idt_table 中）
    ↓
跳转到 entry_INT80_32（汇编入口点）
    ├─ 保存寄存器到 pt_regs
    ├─ 切换到内核栈
    └─ 调用 do_int80_syscall_32(regs)
        ↓
do_int80_syscall_32（C 处理函数）
    ├─ 获取系统调用号（regs->orig_ax）
    ├─ 系统调用入口处理（审计、跟踪等）
    ├─ 调用 do_syscall_32_irqs_on(regs, nr)
    │   └─ 调用 ia32_sys_call(regs, nr)
    │       └─ switch(nr) 分发到具体的系统调用函数
    │           └─ 例如：__ia32_sys_read(regs)
    └─ 系统调用退出处理
        ↓
返回到 entry_INT80_32
    ├─ 恢复寄存器
    ├─ 切换到用户栈
    └─ iret 返回到用户空间
```

**关键点：**
- **IDT[0x80]** 指向 `entry_INT80_32`（汇编入口点）
- **系统调用号**：存储在 `%eax` 寄存器中（通过 `regs->orig_ax` 访问）
- **参数传递**：通过寄存器传递（`%ebx`, `%ecx`, `%edx`, `%esi`, `%edi`, `%ebp`）
- **返回值**：通过 `%eax` 寄存器返回

**`load_idt` 的工作原理：**

1. **参数**：`&idt_descr` 是一个指向 `desc_ptr` 结构的指针
2. **结构内容**：
   - `size`：IDT 表的大小减 1（4095，表示 4096 字节）
   - `address`：`idt_table` 数组的基址
3. **执行**：调用 `native_load_idt()`，执行 `lidt` 指令
4. **结果**：将 IDT 的基址和大小加载到 CPU 的 IDTR 寄存器
5. **效果**：从这一刻起，CPU 使用内核的 IDT，不再使用 BIOS 的 IVT

**关键点：**
- `load_idt()` 是一个内联函数，直接执行 `lidt` 汇编指令
- `idt_descr` 包含 IDT 表的完整信息（基址和大小）
- 加载 IDT 后，所有中断（包括硬件中断和软件中断）都路由到内核的处理程序

	// 步骤 5: 将 IDT 表设置为只读（防止被恶意修改）
	set_memory_ro((unsigned long)&idt_table, 1);

	// 步骤 6: 标记 IDT 设置完成
	idt_setup_done = true;
}
```

**说明：**
- **第 2748 行**：设置 Local APIC 相关的中断门（CPU 内部集成的 APIC，不是 8259A PIC）
- **第 2752-2756 行**：为外部中断（IRQ）设置中断门，指向 `irq_entries_start`
- **第 2771 行**：加载新的 IDT（`load_idt(&idt_descr)`），**此时 BIOS 的 IVT 被完全取代**

> **注意**：关于 BIOS IVT 与 Kernel IDT 的详细对比，请参见 [BIOS IVT vs Kernel IDT 详细对比](BIOS_IVT_VS_KERNEL_IDT.md)。  
> 关于 UEFI 中断处理机制，请参见 [UEFI 中断处理机制](UEFI_INTERRUPT_HANDLING.md)。

