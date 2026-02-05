# Linux 内核启动与初始化（64 位，不走 Setup）

本文档按**实际执行顺序**描述从 GRUB（或 UEFI）进入压缩内核到 `start_kernel()` 及之后的完整流程：**不走 Setup**（GRUB 按 code32_start 跳转、UEFI 按 PE 入口跳转，直接进入压缩内核）。**从扇区 0 启动时的 Setup 流程**见 [LINUX_KERNEL_SETUP_FLOW.md](LINUX_KERNEL_SETUP_FLOW.md)。

> **相关文档**：[BOOT_FLOW.md](BOOT_FLOW.md) 启动概述；[GRUB_KERNEL_LOADING.md](GRUB_KERNEL_LOADING.md) GRUB 加载内核；[GRUB_UEFI_LONG_MODE_ANALYSIS.md](GRUB_UEFI_LONG_MODE_ANALYSIS.md) GRUB UEFI 长模式启动分析；[LINUX_KERNEL_SETUP_FLOW.md](LINUX_KERNEL_SETUP_FLOW.md) 从扇区 0 启动的 Setup；[LINUX_KERNEL_SETUP_ARCH_MEMORY.md](LINUX_KERNEL_SETUP_ARCH_MEMORY.md) setup_arch 内存接管详解；[MMU_AND_PAGING.md](MMU_AND_PAGING.md) x86 MMU、分页与内核页表管理；[X86_NEAR_VS_LONG_JUMP.md](X86_NEAR_VS_LONG_JUMP.md) near/long jump 与 long mode 下 CS 的作用。
>
> **执行顺序**：GRUB/入口 → 【阶段1】压缩内核 startup_32（32位模式切换）→ 【阶段2】压缩内核 startup_64（重定位拷贝、解压）→ 【阶段3】主内核 startup_64 → x86_64_start_kernel（早期 IDT）→ start_kernel() → setup_arch → trap_init/syscall → init_IRQ → rest_init → 核心进程。

### 完整流程图（按执行顺序）

```
GRUB grub_relocator32_boot()（grub/grub-core/lib/i386/relocator.c）
    │   EIP = boot_params.hdr.code32_start，ESI = boot_params
    ↓
【阶段1】压缩内核 startup_32（linux/arch/x86/boot/compressed/head_64.S:82-274，32位保护模式）
    ├─ GDT/栈/段设置（106-125行）
    ├─ verify_cpu（132-135行）
    ├─ CR4.PAE、身份映射页表（内联，200-231行）、CR3、EFER.LME、CR0.PG（167-270行）
    └─ lret → 【阶段2】压缩内核 startup_64（273行，同文件278行，仍在压缩内核代码中）
        ↓
【阶段2】压缩内核 startup_64（linux/arch/x86/boot/compressed/head_64.S:278-476，64位长模式）
    ├─ 设置64位环境：段寄存器、栈、GDT（290-360行）
    ├─ load_stage1_idt、sev_enable、configure_5level_paging（376-409行）
    ├─ 【重定位拷贝】rep movsq 将压缩内核拷贝到安全位置 %rbx（419-425行）
    ├─ 重新加载 GDT、jmp .Lrelocated（432-441行）
    ├─ 清除 BSS（450-455行）
    ├─ load_stage2_idt、initialize_identity_maps（457-461行）
    ├─ 【解压内核】extract_kernel() 解压到 %rbp（通常0x100000）（469行）
    └─ jmp *%rax → 【阶段3】主内核 startup_64（475行）
        ↓
【阶段3】主内核 startup_64（linux/arch/x86/kernel/head_64.S:38）
    ├─ 保存 boot_params（%RSI→%R15）、设栈、GS_BASE、startup_64_setup_gdt_idt（59-74行）
    ├─ pushq/lretq 切 __KERNEL_CS（77-80行）
    ├─ 可选 SEV/SME、verify_cpu（86-98行）
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

**从 GRUB 启动时**：GRUB 不执行 bzImage 内的 Setup，按 boot_params 中 **code32_start** 所存地址跳转到**压缩内核**入口（startup_32，32 位保护模式）。**关键**：模式切换在压缩内核的 startup_32 中完成，解压在压缩内核的 startup_64 中完成（详见下文三个阶段）。vmlinuz 含 Setup（未压缩）与压缩内核（gzip）；GRUB 将镜像拷到 0x100000、自填 boot_params、**按 code32_start 跳转**，不解压、不执行 Setup。

**入口点**：BIOS/Legacy（如 GRUB）→ code32_start 处即 **startup_32**（x86_64：`arch/x86/boot/compressed/head_64.S:82`，`SYM_FUNC_START(startup_32)`）。UEFI → PE 的 AddressOfEntryPoint 跳转到 EFI stub（`efi_pe_entry` 等）。64 位内核用 `head_64.S`（压缩与主内核各一份，路径不同）；32 位用 `head_32.S`。

```
grub_relocator32_boot() → EIP = code32_start
    ↓
【阶段1】压缩内核 startup_32（32 位保护模式，arch/x86/boot/compressed/head_64.S:82）
```

---

## 二、压缩内核的三个阶段（源代码位置：arch/x86/boot/compressed/head_64.S）

**重要**：从 GRUB 到主内核需经过压缩内核的**三个阶段**，前两个阶段都在 `arch/x86/boot/compressed/head_64.S` 中：

- **【阶段1】startup_32（32位保护模式）**：模式切换，从32位切换到64位长模式
- **【阶段2】压缩内核 startup_64（64位长模式）**：重定位拷贝、解压内核
- **【阶段3】主内核 startup_64（64位长模式）**：主内核初始化（在 `arch/x86/kernel/head_64.S`）

### 【阶段1】压缩内核 startup_32 → 32位到64位的模式切换

**源代码位置**：`arch/x86/boot/compressed/head_64.S:82-274`

**模式切换顺序**：32 位保护模式 → GDT/栈/段、verify_cpu、算 %ebx → CR4.PAE → 构建身份映射页表（内联）→ CR3 → EFER.LME → CR0.PG → **lret** 到【阶段2】压缩内核 startup_64（64 位，同文件）。源码无 `setup_identity_mapping` 调用，页表在 startup_32 内内联构建（200-231行）。

**startup_32 关键步骤（head_64.S 压缩内核，与源码顺序一致）**：

实际源码中 **无** `setup_identity_mapping` 调用；身份映射页表在 startup_32 内**内联**构建（Build Level 4/3/2），且 **GDT/栈/段** 在 **CR4/页表/CR3/EFER/CR0** 之前。

```
startup_32（arch/x86/boot/compressed/head_64.S:82-274）
    ├─ cld, cli；算加载偏移 %ebp（89-103行）
    ├─ lgdt（GDT）、段寄存器 = __BOOT_DS、栈 = boot_stack_end、lretl 切到 __KERNEL32_CS（106-125行）
    ├─ [CONFIG_AMD_MEM_ENCRYPT] call startup32_load_idt（128-130行）
    ├─ call verify_cpu；计算重定位目标 %ebx（132-161行）
    ├─ CR4.PAE = 1（167-170行）
    ├─ 构建身份映射页表（内联：pgtable Level 4/3/2，rva(pgtable)(%ebx)）（200-231行）
    ├─ CR3 = pgtable 基址（234-235行）
    ├─ EFER.LME = 1；[CONFIG_AMD_MEM_ENCRYPT] call startup32_check_sev_cbit（237-252行）
    ├─ lldt/ltr（244-247行）
    ├─ push rva(startup_64); push __KERNEL_CS；CR0.PG = 1（264-270行）
    └─ lret → 【阶段2】压缩内核 startup_64（273行，跳转到同文件278行）
```

**关键步骤说明**（与源码 head_64.S 对应）：

| 步骤 | 做什么 | 为何需要 |
|------|--------|----------|
| cld, cli | 清方向标志、关可屏蔽中断 | 后续用 rep/stosl 和栈，避免中断打断 |
| 算 %ebp | call 1f; popl %ebp; subl $ rva(1b), %ebp。%esi 为 boot_params（引导传入） | **%ebp = 当前运行地址相对 startup_32 的偏移**（加载基址），后面用 rva(…)(%ebp) 得到 gdt、栈、startup_64 等的运行地址 |
| lgdt / 段 / 栈 / lret | leal rva(gdt)(%ebp) 填 GDT 描述符并 lgdt；DS/ES/FS/GS/SS = __BOOT_DS；ESP = rva(boot_stack_end)(%ebp)；push __KERNEL32_CS + rva(1f)(%ebp)；lret | 用“当前加载基址”下的 GDT 和栈，并切到 GDT 里的 32 位代码段，为后续 verify_cpu、建页表等提供正确段与栈 |
| verify_cpu | 检查 CPU 是否支持长模式 | 不支持则跳到 .Lno_longmode，不继续解压 |
| 算 %ebx | 非 RELOCATABLE：%ebx = LOAD_PHYSICAL_ADDR；RELOCATABLE：%ebx 按 BP_kernel_alignment 对齐；再 %ebx += BP_init_size − rva(_end) | **%ebx = 重定位目标地址**（解压前要把压缩内核拷到这里），同时 pgtable 将建在 rva(pgtable)(%ebx)，以便拷到 %ebx 后 CR3 仍有效 |
| CR4.PAE | orl $X86_CR4_PAE, %cr4 | 开启物理地址扩展，长模式分页前提 |
| 构建页表 | 在 rva(pgtable)(%ebx) 处内联建 4 级页表（L4/L3/L2），身份映射前 4G；CONFIG_AMD_MEM_ENCRYPT 时 %edx 为加密位掩码 | 开启分页后需有效页表；身份映射保证当前指令与数据在开 PG 后仍可访问。MMU 与分页概念见 [MMU_AND_PAGING.md](MMU_AND_PAGING.md) |
| CR3 | movl rva(pgtable)(%ebx), %cr3 | 让 CPU 使用刚建好的页表 |
| EFER.LME | rdmsr MSR_EFER；btsl LME；wrmsr | 允许长模式；与 CR0.PG 一起生效后进入长模式（先为 32 位兼容子模式） |
| lldt / ltr | 清 LDTR；TR = __BOOT_TSS（GDT 中） | 进入长模式前 TSS 需有效，供后续 64 位栈等使用 |
| CR0.PG + lret | movl $CR0_STATE, %cr0；此前已 push __KERNEL_CS、rva(startup_64)(%ebp)；lret | 开启分页并进入长模式；lret 弹出 CS:EIP，**CS = __KERNEL_CS（64 位段）** 后真正进入 64 位，EIP = startup_64 |

**关键寄存器用途**（startup_32 阶段）：

| 寄存器 | 含义 | 使用方式 |
|--------|------|----------|
| **%esi** | 引导程序传入的 **boot_params** 指针（物理地址） | BP_scratch（临时栈）、BP_init_size、BP_kernel_alignment 等；只读使用 |
| **%ebp** | **当前加载基址**（startup_32 所在运行地址；由 call/popl/subl 算出） | 所有 rva(…)(%ebp)：GDT、boot_stack_end、startup_64、pgtable 等在当前镜像中的运行地址 |
| **%ebx** | **重定位目标**（解压前拷贝目标；由 BP_init_size、_end、对齐等算出） | 页表建在 rva(pgtable)(%ebx)，以便拷贝到 %ebx 后 CR3 仍指向有效页表；后续 64 位 startup_64 里 rep movsq 目标也是 %rbx |
| **CR4** | PAE = 1 | 启用物理地址扩展 |
| **CR3** | 页表基址 | 指向 rva(pgtable)(%ebx)（当前即 %ebx + rva(pgtable)） |
| **EFER** | LME = 1 | 长模式使能（与 CR0.PG 同时生效） |
| **CR0** | PG = 1（CR0_STATE） | 开启分页；与 EFER.LME 一起使 CPU 进入长模式 |

**startup_32 内“构建页表 → CR3 → EFER → CR0 → lret”片段（head_64.S，与源码一致）**：

```asm
	/* Enable PAE mode */
	movl	%cr4, %eax
	orl	$X86_CR4_PAE, %eax
	movl	%eax, %cr4
	/* Build early 4G boot pagetable (identity mapping, inline) */
	leal	rva(pgtable)(%ebx), %edi
	/* ... Level 4/3/2 填入 pgtable ... */
	leal	rva(pgtable)(%ebx), %eax
	movl	%eax, %cr3
	movl	$MSR_EFER, %ecx
	rdmsr
	btsl	$_EFER_LME, %eax
	wrmsr
	/* ... 可选 startup32_check_sev_cbit ... */
	leal	rva(startup_64)(%ebp), %eax
	pushl	$__KERNEL_CS
	pushl	%eax
	movl	$CR0_STATE, %eax
	movl	%eax, %cr0
	lret                    /* 远返到 startup_64，进入 64 位 */
```

Near jump 与 long jump 的区别、long mode 下 CS 仍起的作用（CPL、L/D 位）见 [X86_NEAR_VS_LONG_JUMP.md](X86_NEAR_VS_LONG_JUMP.md)。

### 【阶段2】压缩内核 startup_64 → 重定位拷贝与解压

**源代码位置**：`arch/x86/boot/compressed/head_64.S:278-476`

**关键**：阶段1通过 lret 跳转到这里时，仍在**压缩内核代码**中（`arch/x86/boot/compressed/head_64.S`），还没有解压，也还没有跳转到主内核。这个阶段完成：设置64位环境、重定位拷贝压缩内核到安全位置、解压内核、跳转到主内核。

**压缩内核 startup_64 关键步骤**：

```
压缩内核 startup_64（arch/x86/boot/compressed/head_64.S:278-476，.code64）
    ├─ cld, cli；设置段寄存器（290-299行）
    ├─ 计算解压目标 %rbp（如 LOAD_PHYSICAL_ADDR）与重定位目标 %rbx（314-331行）
    ├─ 设置栈（334行）
    ├─ 加载 GDT、lretq 切换到 __KERNEL_CS（357-366行）
    ├─ 保存 boot_params 到 %r15（374行）
    ├─ load_stage1_idt（376行）
    ├─ sev_enable（390行，CONFIG_AMD_MEM_ENCRYPT）
    ├─ configure_5level_paging（409行）
    ├─ 【重定位拷贝】将压缩内核（startup_32～_bss）整段拷贝到 %rbx 处（419-425行）
    ├─ 重新加载 GDT（432-435行）
    └─ jmp .Lrelocated（440-441行）→ 跳转到新地址继续执行
        ↓
.Lrelocated（arch/x86/boot/compressed/head_64.S:445-476）
    ├─ 清除 BSS（450-455行）
    ├─ load_stage2_idt（457行）
    ├─ initialize_identity_maps（461行）
    ├─ 【解压内核】call extract_kernel()（469行）← 关键：在这里解压内核！
    │       ├─ choose_random_location()（可选 KASLR）更新 output 物理地址
    │       ├─ decompress_kernel() 解压到 output（通常 0x100000）
    │       ├─ 解析解压后 ELF，handle_relocations()
    │       └─ 返回主内核入口地址到 %rax
    └─ jmp *%rax（475行）→ 【阶段3】跳转到主内核 startup_64（arch/x86/kernel/head_64.S）
```

**重定位拷贝的详细说明**：

**为何需要重定位拷贝？** 解压器需要将压缩的内核数据解压到目标地址（通常是 0x100000），如果解压器代码和压缩数据本身就在目标地址附近，解压过程会覆盖正在执行的代码。因此必须先将整个压缩内核（包括解压器代码和压缩数据）拷贝到一个安全的位置（%rbx），然后从那里执行解压操作。

**地址计算**：
- **解压目标 %rbp**：解压后内核的最终位置（如 LOAD_PHYSICAL_ADDR，即 0x100000）
- **重定位目标 %rbx**：压缩内核的安全位置 = %rbp + BP_init_size − rva(_end)（见源代码328-331行）

**拷贝过程**（`arch/x86/boot/compressed/head_64.S:419-425`）：

```asm
/* Copy the compressed kernel to the end of our buffer
 * where decompression in place becomes safe. */
	leaq	(_bss-8)(%rip), %rsi          /* 源：当前运行位置 */
	leaq	rva(_bss-8)(%rbx), %rdi       /* 目标：%rbx 处（安全地址） */
	movl	$(_bss - startup_32), %ecx    /* 大小：整个压缩内核 */
	shrl	$3, %ecx                      /* 转换为8字节单位 */
	std                                   /* 方向标志：向下拷贝（避免覆盖） */
	rep	movsq                             /* 执行拷贝 */
	cld                                   /* 清除方向标志 */
```

**这次拷贝包含什么？** 只拷贝**压缩内核**这一段（startup_32～_bss，即解压器代码 + 压缩的内核数据），**不包含 initrd**。initrd 由引导程序（如 GRUB）单独加载到另一块内存，不在 bzImage 镜像内。

**跳转到新位置**（`arch/x86/boot/compressed/head_64.S:432-441`）：

```asm
	/* 重新加载 GDT，指向新位置 */
	leaq	rva(gdt64)(%rbx), %rax
	leaq	rva(gdt)(%rbx), %rdx
	movq	%rdx, 2(%rax)
	lgdt	(%rax)

	/* 跳转到新地址的 .Lrelocated */
	leaq	rva(.Lrelocated)(%rbx), %rax
	jmp	*%rax
```

之后执行流在新地址（%rbx）运行，调用 extract_kernel() 时，解压写入 0x100000 不会覆盖正在执行的代码。

**extract_kernel() 函数**（`arch/x86/boot/compressed/misc.c:405`）：

在 **重定位拷贝完成后**被调用，完成以下工作：
1. 根据 bzImage 布局找到压缩负载（input_data/input_len）
2. choose_random_location()（可选 KASLR）确定解压目标地址
3. decompress_kernel() 解压到 output（通常 0x100000）
4. 解析解压后的 ELF 格式
5. handle_relocations() 处理重定位
6. 返回主内核入口地址（通过 %rax）

**与主内核的衔接**：extract_kernel() 返回后，`.Lrelocated` 中执行 `jmp *%rax`（第475行），跳转到**主内核**的 `startup_64`（`arch/x86/kernel/head_64.S:38`），此时 %rsi（即 %r15）仍保存着 boot_params 指针。

---

## 三、【阶段3】主内核 startup_64 → x86_64_start_kernel → start_kernel()

**源代码位置**：`linux/arch/x86/kernel/head_64.S:38`

**重要**：这是第三个 startup_64，与前面压缩内核中的 startup_64（`arch/x86/boot/compressed/head_64.S:278`）是**不同的文件**。

**主内核 startup_64**：保存 boot_params（%RSI→%R15）、设置初始栈与 GS 基址、**设置 GDT 和早期 IDT**（`startup_64_setup_gdt_idt`）、切换到 __KERNEL_CS、可选 SEV/SME、verify_cpu，然后进入 C 代码。

**主内核 startup_64 关键步骤**：

```
startup_64（arch/x86/kernel/head_64.S:38-98）
    ├─ mov %rsi, %r15                           // 保存 boot_params（59行）
    ├─ leaq __top_init_kernel_stack(%rip), %rsp // 初始内核栈（62行）
    ├─ wrmsr（MSR_GS_BASE）                      // GS 基址清零（69-72行）
    ├─ call startup_64_setup_gdt_idt            // GDT 与早期 IDT（74行）
    ├─ pushq $__KERNEL_CS; lretq                // 切换到内核代码段（77-80行）
    ├─ 可选 sme_enable（86-95行，CONFIG_AMD_MEM_ENCRYPT）
    ├─ call verify_cpu（98行）
    └─ 后续进入 C 代码（x86_64_start_kernel）
```

**主内核 startup_64 源代码**（`arch/x86/kernel/head_64.S:38-98`）：

```asm
	.code64
SYM_CODE_START_NOALIGN(startup_64)
	UNWIND_HINT_END_OF_STACK
	/*
	 * At this point the CPU runs in 64bit mode CS.L = 1 CS.D = 0,
	 * and someone has loaded an identity mapped page table
	 * for us.  These identity mapped page tables map all of the
	 * kernel pages and possibly all of memory.
	 *
	 * %RSI holds the physical address of the boot_params structure
	 * provided by the bootloader. Preserve it in %R15 so C function calls
	 * will not clobber it.
	 *
	 * We come here either directly from a 64bit bootloader, or from
	 * arch/x86/boot/compressed/head_64.S.
	 */
	mov	%rsi, %r15                    // 保存 boot_params

	/* Set up the stack for verify_cpu() */
	leaq	__top_init_kernel_stack(%rip), %rsp  // 初始内核栈

	/* Set up GSBASE. */
	movl	$MSR_GS_BASE, %ecx
	xorl	%eax, %eax
	xorl	%edx, %edx
	wrmsr                              // GS_BASE = 0

	call	startup_64_setup_gdt_idt  // GDT 与早期 IDT

	/* Now switch to __KERNEL_CS so IRET works reliably */
	pushq	$__KERNEL_CS
	leaq	.Lon_kernel_cs(%rip), %rax
	pushq	%rax
	lretq                              // 切换到内核代码段

.Lon_kernel_cs:
	ANNOTATE_NOENDBR
	UNWIND_HINT_END_OF_STACK

#ifdef CONFIG_AMD_MEM_ENCRYPT
	movq	%r15, %rdi
	call	sme_enable
#endif

	/* Sanitize CPU configuration */
	call verify_cpu
	// 随后进入 x86_64_start_kernel
SYM_CODE_END(startup_64)
```

**startup_64_setup_gdt_idt 的实现**（`arch/x86/boot/startup/gdt_idt.c`）：主内核入口在切换到虚拟地址和 C 环境之前需要可用的 GDT 与一个最小 IDT。

**为何说这里是"早期/初步"的 GDT/IDT**：
- **时机**：这次 lgdt/lidt 发生在 head_64.S，尚在**切到虚拟地址之前**、**进入完整 C 内核**（setup_arch、trap_init、init_IRQ 等）之前，因而是启动顺序里**最早**的一次 GDT/IDT 设置。
- **GDT**：加载的是 cpu/common.c 里定义的 **gdt_page**（内核正式 GDT），之后内核一直沿用，这里只是**第一次**让 CPU 用上这张表，并非"临时表再换"。
- **IDT**：加载的是 **bringup_idt_table**，仅作占位或只填 #VC，属于**最小 IDT**；要等到 x86_64_start_kernel() → idt_setup_early_handler() 用 early_idt_handler_array 填满异常向量并再次 load_idt，才算"早期异常处理就绪"。

因此"初步"主要指**时机最早**，以及 IDT 是**最小、后续被 early IDT 取代**；GDT 则是**一次加载、后续沿用**。

**汇编如何调用 C 函数**：通过链接时的符号解析。

**调用流程**：

```
【源码】
arch/x86/kernel/head_64.S:74
    └─ call startup_64_setup_gdt_idt   ← 汇编中的 call 指令

arch/x86/boot/startup/gdt_idt.c:49
    └─ void __head startup_64_setup_gdt_idt(void) { ... }   ← C 函数定义

【链接】
链接器将 head_64.o 和 gdt_idt.o 链接时：
    └─ 将 call 指令的目标地址解析为 C 函数的入口地址

【运行】
startup_64（arch/x86/kernel/head_64.S）
    ├─ mov %rsi, %r15
    ├─ leaq __top_init_kernel_stack(%rip), %rsp
    ├─ wrmsr（MSR_GS_BASE）
    ├─ call startup_64_setup_gdt_idt   ← 直接跳转到 C 函数
    │       └─ startup_64_setup_gdt_idt() 执行（lgdt、设置段寄存器、lidt）
    │       └─ ret   → 返回到下一条指令
    ├─ pushq $__KERNEL_CS
    └─ lretq
```

结论：汇编中的 **call** 在链接时绑定到 C 函数地址，运行时直接跳转；C 函数执行 **ret** 后返回到汇编的下一条指令。

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
