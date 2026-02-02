# Linux 内核启动与初始化（64 位，不走 Setup）

本文档按**实际执行顺序**描述从 GRUB（或 UEFI）进入压缩内核到 `start_kernel()` 及之后的完整流程：**不走 Setup**（GRUB 按 code32_start 跳转、UEFI 按 PE 入口跳转，直接进入压缩内核）。**从扇区 0 启动时的 Setup 流程**见 [LINUX_KERNEL_SETUP_FLOW.md](LINUX_KERNEL_SETUP_FLOW.md)。

> **相关文档**：[BOOT_FLOW.md](BOOT_FLOW.md) 启动概述；[GRUB_KERNEL_LOADING.md](GRUB_KERNEL_LOADING.md) GRUB 加载内核；[LINUX_KERNEL_SETUP_FLOW.md](LINUX_KERNEL_SETUP_FLOW.md) 从扇区 0 启动的 Setup；[LINUX_KERNEL_SETUP_ARCH_MEMORY.md](LINUX_KERNEL_SETUP_ARCH_MEMORY.md) setup_arch 内存接管详解。
>
> **执行顺序**：GRUB/入口 → startup_32（模式切换与解压）→ startup_64（主内核）→ x86_64_start_kernel（早期 IDT）→ start_kernel() → setup_arch → trap_init/syscall → init_IRQ → rest_init → 核心进程。

### 完整流程图（按执行顺序）

```
GRUB grub_relocator32_boot()（grub/grub-core/lib/i386/relocator.c）
    │   EIP = boot_params.hdr.code32_start，ESI = boot_params
    ↓
压缩内核 startup_32（linux/arch/x86/boot/compressed/head_64.S）
    ├─ 32 位保护模式 → 64 位长模式：身份映射、CR4.PAE、CR3、EFER.LME、CR0.PG、ljmp 64 位段
    ├─ 解压内核（gzip），解压目标 0x100000+
    └─ 跳转到主内核 startup_64
        ↓
主内核 startup_64（linux/arch/x86/kernel/head_64.S）
    ├─ 保存 boot_params（%RSI→%R15）、设栈、GS_BASE、GDT/早期 IDT、lretq 切 __KERNEL_CS
    ├─ 可选 SEV/SME、verify_cpu
    └─ 进入 C 代码
        ↓
x86_64_start_kernel()（linux/arch/x86/kernel/head64.c）
    ├─ idt_setup_early_handler()  【内核接管 INT（早期）】早期 IDT，load_idt，取代 BIOS IVT
    ├─ TDX、copy_bootdata、load_ucode_bsp、高地址映射等
    └─ x86_64_start_reservations() → start_kernel()
        ↓
start_kernel()（linux/init/main.c:898-1111）
    ├─ 阶段 1: boot_cpu_init(), page_address_init(), setup_arch(&command_line)【内核接管内存】, parse_early_param() 等
    ├─ 阶段 2: mm_core_init(), sched_init(),
    │          trap_init()→cpu_init()→syscall_init()  【内核接管 syscall】
    │          early_irq_init(), init_IRQ()  【内核接管 INT（完整）】完整 IDT、PIC、APIC、INT 0x80
    │          local_irq_enable()
    ├─ 阶段 3: console_init(), vfs_caches_init(), fork_init() 等
    └─ 阶段 4: rest_init()
            ├─ user_mode_thread(kernel_init, ...)  → PID 1（init）
            ├─ kernel_thread(kthreadd, ...)        → PID 2（kthreadd）
            ├─ complete(&kthreadd_done)
            └─ cpu_startup_entry(CPUHP_ONLINE)     → PID 0 进入 idle 循环
                    ↓
kernel_init()（main.c:1465-1528）：wait_for_completion(&kthreadd_done)→kernel_init_freeable()→free_initmem()
    → system_state=SYSTEM_RUNNING → run_init_process("/init") 或 "/sbin/init" 等
```

---

## 一、从 GRUB 到压缩内核入口

**从 GRUB 启动时**：GRUB 不执行 bzImage 内的 Setup，按 boot_params 中 **code32_start** 所存地址跳转到**压缩内核**入口（startup_32，32 位保护模式）。解压与模式切换在压缩内核内完成。vmlinuz 含 Setup（未压缩）与压缩内核（gzip）；GRUB 将镜像拷到 0x100000、自填 boot_params、**按 code32_start 跳转**，不解压、不执行 Setup。

**入口点**：BIOS/Legacy（如 GRUB）→ code32_start 处即 **startup_32**（x86_64：`arch/x86/boot/compressed/head_64.S`，`SYM_FUNC_START(startup_32)`）。UEFI → PE 的 AddressOfEntryPoint 跳转到 EFI stub（`efi_pe_entry` 等）。64 位内核用 `head_64.S`（压缩与主内核各一）；32 位用 `head_32.S`。

```
grub_relocator32_boot() → EIP = code32_start
    ↓
压缩内核 startup_32（32 位保护模式）
```

---

## 二、压缩内核：startup_32 → 模式切换与解压

**源代码位置**：`linux/arch/x86/boot/compressed/head_64.S`

startup_32：设置身份映射页表 → 启用 PAE（CR4）→ 加载 CR3 → 启用长模式（EFER.LME）→ 启用分页（CR0.PG）→ `ljmp` 到 64 位 startup_64（同文件）→ 解压内核 → 跳转到主内核 startup_64。

**模式切换顺序**：32 位保护模式 → 页表(身份映射) → CR4.PAE → CR3 → EFER.LME → CR0.PG（进入长模式）→ ljmp 64 位段 → startup_64。

**关键寄存器**：CR4.PAE=1；CR3=页表基址；EFER.LME=1；CR0.PG=1。

**startup_32 关键步骤（head_64.S 压缩内核）**：

```
startup_32（linux/arch/x86/boot/compressed/head_64.S）
    ├─ call setup_identity_mapping     // 身份映射页表
    ├─ orl $X86_CR4_PAE, %eax; movl %eax, %cr4   // CR4.PAE = 1
    ├─ movl %eax, %cr3                 // CR3 = 页表基址
    ├─ rdmsr; btsl $_EFER_LME, %eax; wrmsr       // EFER.LME = 1
    ├─ orl $X86_CR0_PG, %eax; movl %eax, %cr0    // CR0.PG = 1，激活长模式
    ├─ ljmp $__KERNEL_CS, $startup_64  // 跳转 64 位段（同文件内 64 位代码）
    └─ startup_64：设置栈/GDT → extract_kernel() 解压 → 跳转主内核 startup_64（见下「解压内核过程」）
```

**startup_32 切换到长模式的关键代码（linux/arch/x86/boot/compressed/head_64.S）**：

```asm
SYM_FUNC_START(startup_32)
	.code32
	call setup_identity_mapping    // 步骤 1: 身份映射页表
	movl	%cr4, %eax
	orl	$X86_CR4_PAE, %eax       // 步骤 2: CR4.PAE = 1
	movl	%eax, %cr4
	leal	pgtable(%ebx), %eax
	movl	%eax, %cr3              // 步骤 3: CR3 = 页表基址
	movl	$MSR_EFER, %ecx
	rdmsr
	btsl	$_EFER_LME, %eax         // 步骤 4: EFER.LME = 1
	wrmsr
	movl	%cr0, %eax
	orl	$X86_CR0_PG, %eax        // 步骤 5: CR0.PG = 1，激活长模式
	movl	%eax, %cr0
	ljmp	$__KERNEL_CS, $startup_64  // 步骤 6: 跳转 64 位段
	.code64
startup_64:
	// 压缩内核内 64 位代码：解压、跳转主内核
SYM_FUNC_END(startup_32)
```

**解压内核过程（压缩内核内 64 位代码）**

进入长模式后仍在**压缩内核**的 `head_64.S` 中：先设置段寄存器、栈与 GDT，再调用 C 函数 **extract_kernel()** 完成解压与跳转。

**调用链与解压步骤**：

```
压缩内核 startup_64（arch/x86/boot/compressed/head_64.S，.code64）
    ├─ 计算解压目标 %rbp（如 LOAD_PHYSICAL_ADDR）与重定位目标 %rbx（见下）
    ├─ 设置栈、GDT、5-level 分页等
    ├─ 【重定位拷贝】将压缩内核（startup_32～_bss）整段拷贝到 %rbx 处，再 jmp 到 .Lrelocated（新地址）  ← head_64.S:415-442
    └─ .Lrelocated 中 call extract_kernel()（misc.c）
            ├─ choose_random_location()（可选 KASLR，kaslr.c:861）更新 output 物理地址
            ├─ decompress_kernel() 解压到 output（通常 0x100000）
            ├─ 解析解压后 ELF，handle_relocations()
            └─ 跳转到主内核入口（arch/x86/kernel/head_64.S 的 startup_64），不返回
```

**重定位拷贝的代码位置（“又一次 copy”对应实现）**：**先重定位**这一步在 **head_64.S** 中完成，早于 extract_kernel()。解压目标与重定位目标在 64 位路径中由 `head_64.S` 计算：解压目标存入 **%rbp**（如 LOAD_PHYSICAL_ADDR，即 0x100000）；重定位目标 **%rbx** = %rbp + BP_init_size − rva(_end)（见 `head_64.S:327-329`）。随后（`head_64.S:415-426`）用 **rep movsq** 将整段压缩内核（从 startup_32 到 _bss）从当前地址拷贝到 **%rbx** 所指安全地址，再（`head_64.S:440-442`）**jmp** 到该处的 .Lrelocated；此后执行流在新地址运行，再调用 extract_kernel()。因此解压写入 0x100000 时，运行中的代码已在 %rbx，不会覆盖自身。之后 extract_kernel() 返回并 **jmp 到主内核 startup_64** 时，执行该跳转的也是这份已搬迁到 %rbx 的 head_64.S 副本，而不是 0x100000 处的原始加载位置。

**head_64.S 中重定位拷贝片段（linux/arch/x86/boot/compressed/head_64.S:415-442）**：

```asm
/* Copy the compressed kernel to the end of our buffer
 * where decompression in place becomes safe. */
	leaq	(_bss-8)(%rip), %rsi          /* 源：当前运行位置 */
	leaq	rva(_bss-8)(%rbx), %rdi       /* 目标：%rbx 处（安全地址） */
	movl	$(_bss - startup_32), %ecx
	shrl	$3, %ecx
	std
	rep	movsq                         /* 拷贝整段压缩内核 */
	cld
	/* ... 重设 GDTR 指向新位置 ... */
	leaq	rva(.Lrelocated)(%rbx), %rax
	jmp	*%rax                          /* 跳转到新地址的 .Lrelocated，此后 call extract_kernel */
```

**extract_kernel()（linux/arch/x86/boot/compressed/misc.c:405 起）**：在 **head_64.S 已完成重定位** 的前提下被调用；根据 bzImage 头部与布局找到压缩负载（input_data/input_len），调用 choose_random_location()（可选）、decompress_kernel() 解压到 output，再解析 ELF、做 handle_relocations()，最后跳转到主内核入口。解压目标通常为 **0x100000**（1MB）；启用 KASLR 时由 choose_random_location()（`kaslr.c:861`）更新 output。

**与主内核的衔接**：extract_kernel() 返回时已跳转到**主内核**的 `startup_64`（`arch/x86/kernel/head_64.S`），不再是压缩目录下的代码；主内核入口处 %rsi 为 boot_params（或由 boot protocol 约定传递）。

---

## 三、主内核 startup_64 → x86_64_start_kernel → start_kernel()

**主内核 startup_64**（`linux/arch/x86/kernel/head_64.S`）：保存 boot_params（%RSI→%R15）、设置初始栈与 GS 基址、**设置 GDT 和早期 IDT**（`__pi_startup_64_setup_gdt_idt`）、切换到 __KERNEL_CS、可选 SEV/SME、verify_cpu，然后进入 C 代码。

**主内核 startup_64 关键步骤（head_64.S）**：

```
startup_64（linux/arch/x86/kernel/head_64.S）
    ├─ mov %rsi, %r15                  // 保存 boot_params
    ├─ leaq __top_init_kernel_stack(%rip), %rsp // 初始内核栈
    ├─ wrmsr（MSR_GS_BASE）             // GS 基址
    ├─ call __pi_startup_64_setup_gdt_idt       // GDT 与早期 IDT
    ├─ pushq $__KERNEL_CS; lretq       // 切换到内核代码段
    └─ 可选 __pi_sme_enable、verify_cpu  → 进入 C 代码（x86_64_start_kernel）
```

**主内核 startup_64 源代码（linux/arch/x86/kernel/head_64.S）**：

```asm
SYM_CODE_START_NOALIGN(startup_64)
	mov	%rsi, %r15                    // 保存 boot_params
	leaq	__top_init_kernel_stack(%rip), %rsp  // 初始内核栈
	movl	$MSR_GS_BASE, %ecx
	xorl	%eax, %eax
	xorl	%edx, %edx
	wrmsr                              // GS_BASE = 0
	call	__pi_startup_64_setup_gdt_idt  // GDT 与早期 IDT
	pushq	$__KERNEL_CS
	leaq	.Lon_kernel_cs(%rip), %rax
	pushq	%rax
	lretq                              // 切换到内核代码段
.Lon_kernel_cs:
#ifdef CONFIG_AMD_MEM_ENCRYPT
	movq	%r15, %rdi
	call	__pi_sme_enable
#endif
	call	verify_cpu
	// 随后进入 x86_64_start_kernel
SYM_CODE_END(startup_64)
```

**__pi_startup_64_setup_gdt_idt 的实现**（`linux/arch/x86/boot/startup/gdt_idt.c`）：主内核入口在切换到虚拟地址和 C 环境之前需要可用的 GDT 与一个最小 IDT。`__pi_` 前缀表示该符号在链接时使用位置无关形式（KASLR 时需 rip 相对寻址）。

**为何说这里是“早期/初步”的 GDT/IDT**：**时机**上，这次 lgdt/lidt 发生在 head_64.S，尚在**切到虚拟地址之前**、**进入完整 C 内核**（setup_arch、trap_init、init_IRQ 等）之前，因而是启动顺序里**最早**的一次 GDT/IDT 设置。**GDT**：加载的是 cpu/common.c 里定义的 **gdt_page**（内核正式 GDT），之后内核一直沿用，这里只是**第一次**让 CPU 用上这张表，并非“临时表再换”。**IDT**：加载的是 **bringup_idt_table**，仅作占位或只填 #VC，属于**最小 IDT**；要等到 x86_64_start_kernel() → idt_setup_early_handler() 用 early_idt_handler_array 填满异常向量并再次 load_idt，才算“早期异常处理就绪”。因此“初步”主要指**时机最早**，以及 IDT 是**最小、后续被 early IDT 取代**；GDT 则是**一次加载、后续沿用**。

**汇编如何跳到 C 实现**：由源码与链接流程确认如下。

**实际代码依据**：

| 步骤 | 文件 | 内容 |
|------|------|------|
| 汇编引用 | `arch/x86/kernel/head_64.S:74` | `call startup_64_setup_gdt_idt`（符号名即 `startup_64_setup_gdt_idt`，当前内核未对该符号使用 SYM_PIC_ALIAS） |
| C 声明 | `arch/x86/include/asm/setup.h:54` | `extern void startup_64_setup_gdt_idt(void);` |
| C 定义 | `arch/x86/boot/startup/gdt_idt.c:49` | `void __head startup_64_setup_gdt_idt(void) { ... }` |
| 参与链接 | `arch/x86/Makefile` | `core-y += arch/x86/boot/startup/`，与 `arch/x86/kernel/` 下 head_64.o 等一起链接进 vmlinux |

**流程树**：

```
【源码与编译】
arch/x86/kernel/head_64.S
    └─ call startup_64_setup_gdt_idt   (head_64.S:74)
    └─ 汇编 → head_64.o，产生未定义符号 startup_64_setup_gdt_idt

arch/x86/include/asm/setup.h
    └─ extern void startup_64_setup_gdt_idt(void);   (setup.h:54，供 C 编译可见)

arch/x86/boot/startup/gdt_idt.c
    └─ void __head startup_64_setup_gdt_idt(void) { ... }   (gdt_idt.c:49)
    └─ 编译 → gdt_idt.o，提供符号 startup_64_setup_gdt_idt 的定义

【链接】
arch/x86/Makefile: core-y += arch/x86/boot/startup/
    └─ head_64.o（kernel 目录）+ gdt_idt.o（boot/startup 目录）等 → 链接为 vmlinux
    └─ 链接器：将 head_64.o 中对 startup_64_setup_gdt_idt 的引用解析为 gdt_idt.o 中该函数的地址
    └─ call 指令在 vmlinux 中变为“跳转到 C 函数入口”的机器码

【运行】
startup_64（head_64.S）
    ├─ mov %rsi, %r15
    ├─ leaq __top_init_kernel_stack(%rip), %rsp
    ├─ wrmsr（MSR_GS_BASE）
    ├─ call startup_64_setup_gdt_idt   ← 跳转到 C 函数（gdt_idt.c 中实现）
    │       └─ startup_64_setup_gdt_idt() 执行（lgdt、movl %eax,%ds/%ss/%es、lidt 等）
    │       └─ ret   → 返回到 head_64.S 的下一句
    ├─ pushq $__KERNEL_CS
    ├─ lretq
    └─ .Lon_kernel_cs: ...
```

结论：汇编中的 **call** 在链接时被绑定到 C 函数地址，运行时直接跳转到 C 实现；返回时 C 函数的 **ret** 回到 head_64.S 的 **pushq $__KERNEL_CS**。无跳转表或运行时符号解析。

**gdt_idt.c 概览**（`arch/x86/boot/startup/gdt_idt.c`）：该文件仅含一张静态 IDT 表和两个函数，在 head_64.S 切到虚拟地址之前为 boot CPU 建立 GDT 与最小 IDT（bringup IDT 在 x86_64_start_kernel() → idt_setup_early_handler() 之前一直有效；早期不能用 idt.c 的 idt_table，因可能被 KASAN/tracing 等插桩）。

**调用关系树**：

```
head_64.S: call startup_64_setup_gdt_idt
    └─ startup_64_setup_gdt_idt()（gdt_idt.c:49）
            ├─ rip_rel_ptr(&gdt_page)                    // 取 GDT 表（cpu/common.c）
            ├─ native_load_gdt(&startup_gdt_descr)      // lgdt
            ├─ asm volatile("movl %%eax, %%ds\n" ...)    // DS/SS/ES = __KERNEL_DS
            ├─ [CONFIG_AMD_MEM_ENCRYPT] rip_rel_ptr(vc_no_ghcb) → handler
            └─ startup_64_load_idt(handler)              // gdt_idt.c:26
                    ├─ rip_rel_ptr(bringup_idt_table)   // 取 bringup_idt_table
                    ├─ [vc_handler] init_idt_data → idt_init_desc → native_write_idt_entry(X86_TRAP_VC)
                    └─ native_load_idt(&desc)          // lidt
```

所做之事与代码对应如下。

```c
// 静态表：早期 IDT，页对齐，NUM_EXCEPTION_VECTORS 个门（23 行附近）
static gate_desc bringup_idt_table[NUM_EXCEPTION_VECTORS] __page_aligned_data;

// 加载 bringup IDT；若 vc_handler 非空（CONFIG_AMD_MEM_ENCRYPT）则填 #VC 门，否则表为零（26-43）
void __head startup_64_load_idt(void *vc_handler)
{
	struct desc_ptr desc = { .address = (unsigned long)rip_rel_ptr(bringup_idt_table),
	                         .size = sizeof(bringup_idt_table) - 1 };
	if (vc_handler) {
		init_idt_data(&data, X86_TRAP_VC, vc_handler);
		idt_init_desc(&idt_desc, &data);
		native_write_idt_entry(..., X86_TRAP_VC, &idt_desc);
	}
	native_load_idt(&desc);   // → lidt
}

// 主入口：加载 GDT、重载 DS/SS/ES、再调 startup_64_load_idt（49-70）
void __head startup_64_setup_gdt_idt(void)
{
	struct gdt_page *gp = rip_rel_ptr((void *)&gdt_page);   // GDT 在 cpu/common.c
	struct desc_ptr startup_gdt_descr = { .address = (unsigned long)gp->gdt, .size = GDT_SIZE - 1 };
	native_load_gdt(&startup_gdt_descr);   // → lgdt
	asm volatile("movl %%eax, %%ds\n" "movl %%eax, %%ss\n" "movl %%eax, %%es\n" : : "a"(__KERNEL_DS) : "memory");
	handler = IS_ENABLED(CONFIG_AMD_MEM_ENCRYPT) ? rip_rel_ptr(vc_no_ghcb) : NULL;
	startup_64_load_idt(handler);
}
```

- **startup_64_setup_gdt_idt()**：rip_rel_ptr 取 gdt_page（定义在 cpu/common.c）→ **lgdt** → 段寄存器 **DS/SS/ES = __KERNEL_DS** → 若启用 SEV 则 handler = vc_no_ghcb → **startup_64_load_idt(handler)**。
- **startup_64_load_idt()**：用 **bringup_idt_table** 做描述符，可选填 #VC 门 → **lidt**。lgdt/lidt/段寄存器内联汇编的展开形式见下「汇编侧说明」。

**汇编侧说明**：

- **head_64.S 中的调用**（`arch/x86/kernel/head_64.S`）：在 **call** 之前，%r15 已存 boot_params，栈指针已设为 __top_init_kernel_stack，MSR_GS_BASE 已写。**call startup_64_setup_gdt_idt** 返回后，紧接着 **pushq $__KERNEL_CS** 与 **lretq**：将 __KERNEL_CS 压栈并远返回，使 CS 切换到 GDT 中的内核代码段，此后取指、IRET 等均使用新 GDT。

- **C 函数展开成的指令**：`native_load_gdt()` / `native_load_idt()` 在 `arch/x86/include/asm/desc.h` 中为内联函数，编译后即一条 **lgdt** / **lidt**；GDT/IDT 描述符（基址 + 界限）由 C 侧填入 `struct desc_ptr`，再以内存操作数形式传给指令。

```c
// arch/x86/include/asm/desc.h
static inline void native_load_gdt(const struct desc_ptr *dtr)
{
	asm volatile("lgdt %0"::"m" (*dtr));   // 加载 GDT，操作数为 6 字节描述符（界限 2B + 基址 4/8B）
}
static __always_inline void native_load_idt(const struct desc_ptr *dtr)
{
	asm volatile("lidt %0"::"m" (*dtr));   // 加载 IDT，格式同上
}
```

- **段寄存器重载**（gdt_idt.c:61-64）：GDT 加载后必须显式刷新数据段选择子，否则 DS/SS/ES 仍为旧值。代码用内联汇编把 **__KERNEL_DS**（内核数据段选择子）写入 **DS、SS、ES**：

```c
// arch/x86/boot/startup/gdt_idt.c
	asm volatile("movl %%eax, %%ds\n"
		     "movl %%eax, %%ss\n"
		     "movl %%eax, %%es\n" : : "a"(__KERNEL_DS) : "memory");
```

**64 位长模式代码特征**：使用 64 位寄存器（%RSI、%R15、%RSP 等）、`movq`/`leaq`/`pushq`/`lretq`、`%rip` 相对寻址、`__KERNEL_CS`（CS.L=1）、wrmsr 写 GS_BASE。

**x86_64_start_kernel()**（`head64.c`）：调用 **idt_setup_early_handler()**，用 early_idt_handler_array 填充 IDT 并 **load_idt(&idt_descr)**，此后 CPU 使用内核 IDT 取代 BIOS IVT（仅 CPU 异常，尚无硬件 IRQ 与 INT 0x80）。随后 TDX、copy_bootdata、load_ucode_bsp、高地址映射等，最终 **x86_64_start_reservations() → start_kernel()**。

```c
// idt.c
void __init idt_setup_early_handler(void)
{
	for (i = 0; i < NUM_EXCEPTION_VECTORS; i++)
		set_intr_gate(i, early_idt_handler_array[i]);
	load_idt(&idt_descr);
}
```

**GDT 与 IDT**：GDT 定义段（代码/数据/栈）；IDT 定义中断/异常时跳转目标。早期 IDT 在此阶段设置，完整 IRQ/INT 0x80 在 start_kernel() 的 init_IRQ() 中设置（见下）。

| 特性 | GDT（全局描述符表） | IDT（中断描述符表） |
|------|---------------------|---------------------|
| 用途 | 定义内存段（代码段、数据段等） | 定义中断/异常处理程序 |
| 访问方式 | 段选择子（Segment Selector） | 中断向量号（0–255） |
| 寄存器 | GDTR（GDT 基址与界限） | IDTR（IDT 基址与界限） |
| 加载指令 | LGDT | LIDT |
| 条目内容 | 段描述符（基址、界限、权限等） | 中断门/陷阱门（处理程序地址） |
| 主要功能 | 内存分段和保护 | 中断与异常处理 |

---

## 四、start_kernel() 流程概述

**源代码位置**：`linux/init/main.c:898-1111`

```
start_kernel()
    ├─ 阶段 1: 早期初始化（中断禁用）
    │   ├─ boot_cpu_init(), page_address_init()
    │   ├─ setup_arch(&command_line)     【内核接管内存】e820/memblock、init_mem_mapping、paging_init
    │   └─ parse_early_param() 等
    ├─ 阶段 2: 核心子系统
    │   ├─ mm_core_init(), sched_init()
    │   ├─ trap_init()→cpu_init()→syscall_init()  【内核接管 syscall】
    │   ├─ early_irq_init(), init_IRQ()  【内核接管 INT（完整）】完整 IDT、PIC、APIC、INT 0x80
    │   └─ local_irq_enable()
    ├─ 阶段 3: 设备与文件系统（console_init, vfs_caches_init, fork_init 等）
    └─ 阶段 4: rest_init()              【创建 PID 1/2、PID 0 进入 idle】kernel_init、kthreadd、idle
```

**start_kernel() 关键代码（按执行顺序：阶段 1 → 2 → 3 → 4，linux/init/main.c:898-1111）**：

```c
void start_kernel(void)
{
	set_task_stack_end_magic(&init_task);
	smp_setup_processor_id();
	cgroup_init_early();
	local_irq_disable();
	early_boot_irqs_disabled = true;

	boot_cpu_init();
	page_address_init();
	setup_arch(&command_line);        // 阶段 1：【内核接管内存】
	setup_command_line(command_line);
	setup_per_cpu_areas();
	parse_early_param();

	mm_core_init();                   // 阶段 2
	sched_init();
	early_irq_init();
	init_IRQ();                       // 阶段 2：【内核接管 INT（完整）】
	tick_init();
	timekeeping_init();
	local_irq_enable();
	early_boot_irqs_disabled = false;

	console_init();                   // 阶段 3
	vfs_caches_init();
	fork_init();
	// ... 其他子系统 ...

	rest_init();                      // 阶段 4：【创建 PID 1/2、PID 0 进入 idle】
}
```

以下按执行顺序分别展开各关键步骤。

### 1. setup_arch() 与内核接管内存

**关键步骤**：`setup_arch(&command_line)`。此前仅有身份映射与 early 页表；**完整物理内存接管**在 setup_arch() 中：解析 e820/EFI、memblock、`init_mem_mapping()`、`paging_init()`。详见 [LINUX_KERNEL_SETUP_ARCH_MEMORY.md](LINUX_KERNEL_SETUP_ARCH_MEMORY.md)。

### 2. trap_init() 与 syscall

**cpu_init()** 在 **trap_init()** 中调用（非 setup_arch）。用户态 `syscall` 跳转到 entry_SYSCALL_64 → do_syscall_64 → sys_call_table[nr]。

**调用层级：**

```
start_kernel()（main.c:898）
    └─ trap_init()（main.c:958 → traps.c:1561）  【内核接管 syscall】
        └─ cpu_init()（cpu/common.c:2384）
            └─ syscall_init()（cpu/common.c:2234）
                └─ idt_syscall_init()（同文件:2198）
                    └─ MSR_STAR、MSR_LSTAR(entry_SYSCALL_64)、MSR_SYSCALL_MASK 等
```

**syscall_init()（linux/arch/x86/kernel/cpu/common.c:2234）**：

```c
void syscall_init(void)
{
	wrmsr(MSR_STAR, 0, (__USER32_CS << 16) | __KERNEL_CS);
	if (!cpu_feature_enabled(X86_FEATURE_FRED))
		idt_syscall_init();
}
```

**idt_syscall_init()（linux/arch/x86/kernel/cpu/common.c:2198）**：

```c
static inline void idt_syscall_init(void)
{
	wrmsrq(MSR_LSTAR, (unsigned long)entry_SYSCALL_64);  // 64 位 syscall 入口
	if (ia32_enabled()) {
		wrmsrq_cstar((unsigned long)entry_SYSCALL_compat);
		wrmsrq_safe(MSR_IA32_SYSENTER_CS, (u64)__KERNEL_CS);
		wrmsrq_safe(MSR_IA32_SYSENTER_ESP, ...);
		wrmsrq_safe(MSR_IA32_SYSENTER_EIP, (u64)entry_SYSENTER_compat);
	}
	wrmsrq(MSR_SYSCALL_MASK, X86_EFLAGS_CF|...|X86_EFLAGS_ID);  // syscall 时清除的 RFLAGS
}
```

entry_SYSCALL_64 在 `arch/x86/entry/entry_64.S`，保存 pt_regs 后调用 do_syscall_64；系统调用表在 `arch/x86/entry/syscall_64.c`（sys_call_table）。

### 3. init_IRQ() 与接管 INT 服务的过程

**“接管 INT 服务”** 指：CPU 发生中断或异常时，按向量号查 **IDT** 跳转到内核注册的处理函数，而不再交给 BIOS/固件（IVT）。分两段完成：**阶段一（早期 INT）** 在 **x86_64_start_kernel** 中（见第三节），**阶段二（完整 INT/IRQ）** 即本段的 **init_IRQ()**。

**阶段二：完整 INT/IRQ（异常 + 硬件 IRQ + INT 0x80）**

```
start_kernel() 阶段 2（main.c）
    └─ init_IRQ()（在 trap_init、early_irq_init 之后）  【内核接管 INT（完整）】
        ├─ idt_setup_traps()（linux/arch/x86/kernel/idt.c）
        │   └─ def_idts 等补全/更新 IDT 异常门
        ├─ init_8259A()（linux/arch/x86/kernel/i8259.c:349）
        │   └─ PIC 重编程：硬件 IRQ 0x08–0x0F/0x70–0x77 → 0x20–0x2F
        │       （主 PIC ICW2=ISA_IRQ_VECTOR(0)，从 PIC ICW2=ISA_IRQ_VECTOR(8)）
        ├─ idt_setup_apic_and_irq_gates()（linux/arch/x86/kernel/idt.c）
        │   ├─ apic_idts 表设置 APIC 相关门，IRQ 向量 → irq_entries_start 等
        │   └─ load_idt(&idt_descr)  → 完整 IDT 已加载，BIOS IVT 被完全取代
        └─ idt_setup_ia32_syscall_gate()（若 CONFIG_IA32_EMULATION）
            └─ IDT[0x80]=entry_INT80_32  → INT 0x80 → do_int80_syscall_32 → ia32_sys_call
```

**阶段一**（早于 start_kernel，在 x86_64_start_kernel 中）：idt_setup_early_handler() 用 early_idt_handler_array 填 IDT 异常向量并 load_idt，仅 CPU 异常（#PF、#DE 等），无硬件 IRQ 门、无 INT 0x80。参见第三节「x86_64_start_kernel()」与「主内核 startup_64 关键步骤」树中的 GDT 与早期 IDT。

**两步区别（早期 INT vs 完整 INT）**

| 对比项 | 早期 INT（idt_setup_early_handler） | 完整 INT（init_IRQ） |
|--------|-------------------------------------|----------------------|
| **时机** | x86_64_start_kernel()，早于 start_kernel() | start_kernel() 阶段 2，在 trap_init、early_irq_init 之后 |
| **覆盖范围** | 仅 **CPU 异常**（#PF、#DE、#GP 等，向量 0–31） | **CPU 异常 + 硬件 IRQ + 软件 INT 0x80**（所有 IDT 向量） |
| **做的具体工作** | 用 early_idt_handler_array 填 IDT 异常向量，**load_idt(&idt_descr)**，取代 BIOS IVT 对异常的处理 | ① idt_setup_traps() 补全/更新 IDT 异常门；② **init_8259A()** 对 8259A PIC 重编程（IRQ 重映射到 0x20–0x2F）；③ **idt_setup_apic_and_irq_gates()** 设 APIC/IRQ 门并再次 **load_idt**；④ 若启用 32 位兼容则 **idt_setup_ia32_syscall_gate()** 设 INT 0x80 |
| **尚未具备的能力** | 无硬件 IRQ 门、无 INT 0x80，硬件中断仍走 BIOS/固件 | 无（完整 IDT 已加载，此后 local_irq_enable() 即可响应硬件 IRQ） |
| **为何需要** | setup_arch() 前就要处理缺页等异常（如 init_mem_mapping 依赖 #PF），必须先让 CPU 查 IDT 时进内核 | 让键盘、时钟等硬件 IRQ 和 INT 0x80 系统调用都由内核处理，完全取代 BIOS IVT |

**何时算“接管了所有中断服务”？**  
从 **init_IRQ() 返回之后**（具体是 idt_setup_apic_and_irq_gates() 中 **load_idt(&idt_descr)** 执行完毕之后）：所有向量（CPU 异常、硬件 IRQ、INT 0x80）都指向内核处理程序，CPU 查 IDT 只会进入内核。硬件 IRQ 是否真正交付 CPU 还受 **IF** 控制，需等 **local_irq_enable()** 后才会响应，但中断的**路由权**在 init_IRQ() 完成后已完全在内核。

- **8259A PIC**：`linux/arch/x86/kernel/i8259.c`，ICW2 重映射到 0x20–0x2F。  
- **APIC/IRQ 门**：`linux/arch/x86/kernel/idt.c` 中 idt_setup_apic_and_irq_gates()。  
- **INT 0x80**：entry_INT80_32 → do_int80_syscall_32 → ia32_sys_call（系统调用号在 %eax）。

> 运行时中断模型见 [LINUX_INTERRUPT_HANDLING.md](LINUX_INTERRUPT_HANDLING.md)；BIOS IVT 与 Kernel IDT 见 [BIOS_IVT_VS_KERNEL_IDT.md](BIOS_IVT_VS_KERNEL_IDT.md)。

### 4. rest_init() 与 kernel_init()

**从 start_kernel 到 rest_init / kernel_init 的调用链**：

```
start_kernel()（main.c:898）
    ├─ 阶段 1: setup_arch(), parse_early_param() 等
    ├─ 阶段 2: mm_core_init(), sched_init(), trap_init(), init_IRQ(), local_irq_enable() 等
    ├─ 阶段 3: console_init(), vfs_caches_init(), fork_init() 等
    └─ rest_init()（main.c:699）  【创建 PID 1/2、PID 0 进入 idle】
            ├─ user_mode_thread(kernel_init, NULL, CLONE_FS)
            │       → 创建内核线程，入口函数 kernel_init，即 PID 1（init）；该线程稍后执行 kernel_init()
            ├─ kernel_thread(kthreadd, NULL, NULL, CLONE_FS | CLONE_FILES)
            │       → 创建内核线程，入口函数 kthreadd，即 PID 2；该线程稍后执行 kthreadd()
            ├─ complete(&kthreadd_done)   // 通知 PID 1：kthreadd 已就绪
            └─ cpu_startup_entry(CPUHP_ONLINE)
                    → 当前进程（PID 0: swapper）进入 idle 循环，不返回
```

执行顺序：rest_init() 先创建 PID 1 和 PID 2 两个线程（此时它们已可被调度，但 rest_init 仍在 PID 0 上运行），complete 后 PID 0 调用 cpu_startup_entry 进入 idle；PID 1 的 kernel_init() 会在 wait_for_completion(&kthreadd_done) 处等到 kthreadd 就绪后再继续。

**rest_init()（linux/init/main.c:699-746）**：

```c
static noinline void __ref __noreturn rest_init(void)
{
	pid = user_mode_thread(kernel_init, NULL, CLONE_FS);   // PID 1
	pid = kernel_thread(kthreadd, NULL, NULL, CLONE_FS | CLONE_FILES);  // PID 2
	complete(&kthreadd_done);
	cpu_startup_entry(CPUHP_ONLINE);   // 当前进程（PID 0）进入 idle 循环
}
```

**kernel_init()（linux/init/main.c:1465-1528）**：由 rest_init() 通过 user_mode_thread 创建，作为 **PID 1** 的入口函数；执行完 kernel_init_freeable、free_initmem 后，通过 run_init_process / try_to_run_init_process 执行用户空间 init（/init 或 /sbin/init）。

```c
static int __ref kernel_init(void *unused)
{
	wait_for_completion(&kthreadd_done);
	kernel_init_freeable();
	free_initmem();
	system_state = SYSTEM_RUNNING;

	if (ramdisk_execute_command)
		ret = run_init_process(ramdisk_execute_command);  // 优先 /init
	if (execute_command)
		ret = run_init_process(execute_command);
	if (!try_to_run_init_process("/sbin/init") || ...)
		return 0;
	panic("No working init found.");
}
```

---

## 五、核心进程详解

调用链见第四节「rest_init() 与 kernel_init()」开头的树形图。

**进程关系图（按 PID）**：

```
[PID 0: swapper/idle]  ← start_kernel() 所在进程，rest_init() 末尾进入 cpu_startup_entry()
    ├─ [PID 1: init]   ← user_mode_thread(kernel_init)，入口 kernel_init() → execve("/init") 或 "/sbin/init"
    └─ [PID 2: kthreadd] ← kernel_thread(kthreadd)，入口 kthreadd() → 管理 kthread_create_list，创建各类内核线程
```

### PID 0（swapper/idle）

**静态定义（linux/init/init_task.c）**：`init_task` 是编译时静态定义的 task_struct，mm=NULL，stack=init_stack，comm="swapper"，thread_pid 对应 PID 0。不是 fork() 创建。

**进入 idle（linux/kernel/sched/idle.c:417）**：

```c
void cpu_startup_entry(enum cpuhp_state state)
{
	current->flags |= PF_IDLE;
	arch_cpu_idle_prepare();
	cpuhp_online_idle(state);
	while (1)
		do_idle();
}
```

**do_idle()**：在 `!need_resched()` 时调用 `cpuidle_idle_call()`（hlt/mwait 等），否则调度其他进程。每 CPU 一个（swapper/0, swapper/1, …）。

### PID 1（init）

kernel_init() 经 run_init_process 执行 execve("/init") 或 "/sbin/init"，成为用户空间 init（systemd/SysVinit 等）。职责：第一个用户空间进程、所有用户进程祖先、孤儿收养、僵尸回收、不可 kill -9。

### PID 2（kthreadd）

**源代码（linux/kernel/kthread.c:818）**：

```c
int kthreadd(void *unused)
{
	for (;;) {
		if (list_empty(&kthread_create_list))
			schedule();
		while (!list_empty(&kthread_create_list)) {
			create = list_entry(kthread_create_list.next, ...);
			create_kthread(create);
		}
	}
}
```

职责：处理 kthread_create() 请求，创建 kworker、ksoftirqd、migration、watchdog、kswapd、kblockd、irq/* 等内核线程。

### 完整进程层次结构

```
[PID 0: swapper/idle]
    ├─ [PID 1: init] → systemd/init → 所有用户进程
    └─ [PID 2: kthreadd] → kworker/*, ksoftirqd/*, migration/*, watchdog/*, kswapd*, ...
```

> **更多**：[BOOT_FLOW.md](BOOT_FLOW.md)、[GRUB_KERNEL_LOADING.md](GRUB_KERNEL_LOADING.md)、[VMLINUZ_STRUCTURE.md](VMLINUZ_STRUCTURE.md)、[INITRAMFS_ANALYSIS.md](INITRAMFS_ANALYSIS.md)。
