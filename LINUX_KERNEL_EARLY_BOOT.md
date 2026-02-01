# Linux 内核早期启动详细流程（64 位，不走 Setup）

本文档**只讲解不走 Setup 的流程**：从 GRUB 按 code32_start 字段所存地址跳转、或从 UEFI 按 PE 入口跳转，直接进入压缩内核（如 startup_32），不执行 bzImage 内的 Setup 代码。内容包括模式切换（保护模式 → 64 位长模式）、内核解压和 `startup_64` 入口点的源代码分析。**从扇区 0 启动时的 Setup 流程**（header.S → main → go_to_protected_mode → protected_mode_jump）见 [Linux 内核 Setup 流程](LINUX_KERNEL_SETUP_FLOW.md)。

> **相关文档**：
> - **从扇区 0 启动的 Setup 流程**：见 [LINUX_KERNEL_SETUP_FLOW.md](LINUX_KERNEL_SETUP_FLOW.md)
> - **后续阶段**：`start_kernel()` 之后见 [LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md)；启动概述见 [BOOT_FLOW.md](BOOT_FLOW.md)
>
> **阅读说明**：本系列三篇文档按启动顺序为 EARLY_BOOT → INTERRUPT_TAKEOVER → INIT；时间线简表见 [BOOT_FLOW.md 相关文档索引](BOOT_FLOW.md#相关文档索引)。

## 内核早期启动（64 位）

**说明**：**从 GRUB 启动时**，GRUB 不执行 bzImage 内的 Setup 代码，而是按 boot_params 中 **code32_start 字段所存地址**跳转，该地址处为**压缩内核**入口（如 startup_32，32 位保护模式），解压与模式切换在压缩内核内完成，最终到达 `startup_64`。**从扇区 0 启动时**才会先执行 Setup 代码（实模式），再在 pm.c 中 `protected_mode_jump(boot_params.hdr.code32_start, ...)` 读取 code32_start 字段值并跳转到压缩内核。code32_start 是 boot protocol 头中的**数据字段**（仅一个 32 位值），存 32 位入口物理地址，不是“入口点”本身。

**重要澄清：vmlinuz 文件的压缩结构与两条启动路径**

- **vmlinuz 文件包含两部分**：
  1. **Setup 代码**（未压缩）：仅**从扇区 0 启动**时执行；GRUB 启动时不执行
  2. **压缩的内核代码**（gzip 压缩）：**从 GRUB 启动时**由 GRUB 直接跳到该部分入口（code32_start 字段所存地址）；从扇区 0 启动时由 Setup 在保护模式切换后跳转
- **GRUB 的作用**：将 vmlinuz 复制到 0x100000，自填 boot_params，**按 code32_start 字段所存地址跳转**，不解压、不执行 Setup
- **解压时机**：在压缩内核（startup_32 等）内完成，不是 GRUB，也不是 Setup 解压

**详细执行流程（从 GRUB 启动时的实际路径）：**

```
grub_relocator32_boot() 按 code32_start 字段所存地址跳转
    ├─ 源代码位置：grub/grub-core/lib/i386/relocator.c
    ├─ 跳转目标：EIP = boot_params.hdr.code32_start 的值（该字段是数据，存 32 位入口物理地址）
    └─ 寄存器状态：
        ├─ ESI = boot_params 地址
        ├─ ESP = 栈指针
        └─ EIP = code32_start 字段的值（即 32 位入口物理地址）
    ↓
压缩内核入口（code32_start 字段所存地址处的代码，32 位保护模式，如 startup_32）
    ↓
（从扇区 0 启动时先执行 Setup 再进入压缩内核，详见 [LINUX_KERNEL_SETUP_FLOW.md](LINUX_KERNEL_SETUP_FLOW.md)）
```

**不走 Setup 时的实际入口点**  
- **BIOS/Legacy（如 GRUB）**：按 code32_start 字段所存地址跳转，该地址处是**压缩内核**的第一条指令，即 **startup_32**：
  - **x86_64**：`linux/arch/x86/boot/compressed/head_64.S` 第 **82** 行，`SYM_FUNC_START(startup_32)`
  - **x86_32**：`linux/arch/x86/boot/compressed/head_32.S` 第 **46** 行，`SYM_FUNC_START(startup_32)`  
  header.S 的 code32_start 仅是数据字段（默认 0x100000）；压缩内核链接时 startup_32 在偏移 0，故加载到 0x100000 后该地址即为 startup_32。
- **UEFI**：固件按 PE/COFF 头的 **AddressOfEntryPoint** 跳转，**不经过** code32_start；入口为 **EFI stub**：
  - **x86_64**：`linux/drivers/firmware/efi/libstub/x86-stub.c` 第 **943** 行，`efi_pe_entry(handle, sys_table_arg)`（再调 `efi_stub_entry`）
  - **x86_32（CONFIG_EFI_MIXED）**：`linux/arch/x86/boot/startup/efi-mixed.S` 第 **219** 行，`SYM_FUNC_START(efi32_pe_entry)`  
  PE 头中 AddressOfEntryPoint 在 header.S 中设为 `setup_size + ZO_efi_pe_entry`（64 位）或 `.compat` 中 `setup_size + ZO_efi32_pe_entry`（32 位）。

**压缩内核解压代码（startup_32）→ startup_64 → x86_64_start_kernel：**

```
压缩内核解压代码（startup_32）
    ├─ 源代码位置：linux/arch/x86/boot/compressed/head_64.S
    ├─ 运行模式：32 位保护模式 → 64 位长模式
    ├─ 切换到 64 位长模式的关键步骤（head_64.S）：
    │   ├─ 步骤 1: 设置页表（身份映射：物理地址 = 线性地址）
    │   ├─ 步骤 2: 启用 PAE（CR4.PAE = 1）
    │   ├─ 步骤 3: 加载页表基址到 CR3
    │   ├─ 步骤 4: 启用长模式（EFER.LME = 1）
    │   ├─ 步骤 5: 启用分页（CR0.PG = 1）
    │   └─ 步骤 6: 跳转到 64 位代码段（ljmp $__KERNEL_CS, $startup_64）
    ├─ 解压内核（gzip 解压）：解压目标 0x100000+，由内核代码完成
    └─ 跳转到 startup_64
        ↓
startup_64（64 位内核入口点，已切换到长模式）
    ├─ 源代码位置：linux/arch/x86/kernel/head_64.S
    ├─ 运行模式：64 位长模式
    ├─ 保存 boot_params（%RSI → %R15）、设置初始内核栈、GS 段基址
    ├─ 设置 GDT 和早期 IDT、切换到内核代码段（__KERNEL_CS）
    ├─ 激活内存加密（SEV/SME，若支持）、验证 CPU（verify_cpu）
    └─ 继续内核初始化流程
        ↓
x86_64_start_kernel（head64.c）：早期 IDT、TDX、copy_bootdata、微码、高地址映射等
    → x86_64_start_reservations → start_kernel()
```

（早期 IDT 详见 [LINUX_KERNEL_INTERRUPT_TAKEOVER.md](LINUX_KERNEL_INTERRUPT_TAKEOVER.md)；start_kernel() 详见 [LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md)）

**Linux 内核切换到 64 位长模式的详细代码：**

**源代码位置：** `linux/arch/x86/boot/compressed/head_64.S`

切换到长模式的关键代码（伪代码，展示主要步骤）：

```asm
// linux/arch/x86/boot/compressed/head_64.S
// startup_32: 32 位保护模式入口点
SYM_CODE_START(startup_32)
	.code32  // 32 位保护模式代码
	
	// 步骤 1: 设置页表（身份映射：物理地址 = 线性地址）
	// 创建页表结构：PML4 → PDPT → PD → PT
	// 每个页表项映射 4KB 或 2MB 页面
	call setup_identity_mapping
	
	// 步骤 2: 启用 PAE（Physical Address Extension）
	// 长模式必须启用 PAE
	movl	%cr4, %eax
	orl	$X86_CR4_PAE, %eax  // 设置 CR4.PAE = 1
	movl	%eax, %cr4
	
	// 步骤 3: 加载页表基址到 CR3
	leal	pgtable(%ebx), %eax  // %ebx 包含重定位后的基址
	movl	%eax, %cr3           // 设置页表基址
	
	// 步骤 4: 启用长模式（EFER.LME = 1）
	// EFER (Extended Feature Enable Register) 是 MSR 寄存器
	movl	$MSR_EFER, %ecx      // MSR 编号
	rdmsr                        // 读取当前 EFER 值到 %edx:%eax
	btsl	$_EFER_LME, %eax     // 设置 LME 位（Long Mode Enable）
	wrmsr                        // 写回 EFER
	
	// 步骤 5: 启用分页（CR0.PG = 1）
	// 这是激活长模式的最后一步
	movl	%cr0, %eax
	orl	$X86_CR0_PG, %eax     // 设置 CR0.PG = 1（启用分页）
	movl	%eax, %cr0
	
	// 步骤 6: 跳转到 64 位代码段
	// 使用 64 位代码段选择子（CS.L = 1），跳转到 startup_64
	ljmp	$__KERNEL_CS, $startup_64  // 长跳转，切换到 64 位长模式
	
	.code64  // 从这行开始，代码是 64 位的
startup_64:
	// 此时 CPU 已处于 64 位长模式
	// 可以开始使用 64 位寄存器和指令
```

**关键寄存器设置：**

1. **CR4.PAE = 1**：启用物理地址扩展（长模式必需）
2. **CR3**：页表基址（指向 PML4 表）
3. **EFER.LME = 1**：启用长模式（但此时还未激活，需要 CR0.PG）
4. **CR0.PG = 1**：启用分页（激活长模式，CPU 进入 64 位长模式）

**模式切换顺序：**

```
32 位保护模式
    ↓
设置页表（身份映射）
    ↓
启用 PAE（CR4.PAE = 1）
    ↓
加载页表基址（CR3）
    ↓
启用长模式（EFER.LME = 1）
    ↓
启用分页（CR0.PG = 1）← 此时 CPU 进入 64 位长模式
    ↓
跳转到 64 位代码段（ljmp $__KERNEL_CS, $startup_64）
    ↓
64 位长模式（startup_64）
```

**源代码位置：`linux/arch/x86/kernel/head_64.S:38-100`**

```asm
// Linux 内核 64 位启动入口点
// 此时 CPU 已处于 64 位长模式（CS.L = 1, CS.D = 0）
// Bootloader 已经加载了身份映射页表（物理地址 = 线性地址）
SYM_CODE_START_NOALIGN(startup_64)
	UNWIND_HINT_END_OF_STACK
	
	// 步骤 1: 保存 boot_params 结构地址
	// %RSI 包含 bootloader 提供的 boot_params 物理地址
	// 保存到 %R15，避免后续 C 函数调用破坏它
	// ↑ 使用 64 位寄存器（%RSI, %R15）表明这是 64 位长模式
	mov	%rsi, %r15

	// 步骤 2: 设置初始内核栈（用于 verify_cpu() 等函数）
	// ↑ 使用 %rip 相对寻址（leaq ...(%rip)），这是 64 位长模式特有
	// ↑ 使用 64 位寄存器 %rsp
	leaq	__top_init_kernel_stack(%rip), %rsp

	// 步骤 3: 设置 GS 段基址（用于 per-CPU 数据）
	// 在 SMP 系统中，启动 CPU 使用 init 数据段，直到 per-CPU 区域设置完成
	// ↑ 使用 wrmsr 指令写入 64 位 MSR 寄存器（GS_BASE）
	movl	$MSR_GS_BASE, %ecx  // MSR 寄存器编号
	xorl	%eax, %eax          // 清零 EAX（GS 基址低 32 位）
	xorl	%edx, %edx          // 清零 EDX（GS 基址高 32 位）
	wrmsr                      // 写入 MSR，设置 GS 基址为 0

	// 步骤 4: 设置 GDT（全局描述符表）和早期 IDT（中断描述符表）
	// 这是内核接管中断系统的第一步
	call	__pi_startup_64_setup_gdt_idt

	// 步骤 5: 切换到内核代码段（__KERNEL_CS），确保 IRET 正常工作
	// ↑ 使用 pushq（64 位压栈）和 lretq（64 位长返回）
	// ↑ __KERNEL_CS 是 64 位代码段选择子（CS.L = 1）
	pushq	$__KERNEL_CS        // 压入内核代码段选择子
	leaq	.Lon_kernel_cs(%rip), %rax  // 获取标签地址（%rip 相对寻址）
	pushq	%rax                // 压入返回地址
	lretq                       // 长返回：弹出 CS 和 RIP，切换到内核代码段

.Lon_kernel_cs:
	ANNOTATE_NOENDBR
	UNWIND_HINT_END_OF_STACK

#ifdef CONFIG_AMD_MEM_ENCRYPT
	// 步骤 6: 激活内存加密（SEV/SME），如果支持
	// 必须在执行 CPUID 之前完成，因为需要设置 SEV-SNP CPUID 表
	// ↑ 使用 movq（64 位移动）和 64 位寄存器 %r15, %rdi
	movq	%r15, %rdi          // 传递 boot_params 指针作为参数
	call	__pi_sme_enable
#endif

	// 步骤 7: 验证和清理 CPU 配置
	call verify_cpu
```

**64 位长模式的代码特征：**

1. **64 位寄存器**：
   - `%RSI`, `%R15`, `%RSP`, `%RAX`, `%RDX`, `%RCX`, `%RDI` 等（R 前缀表示 64 位）
   - 与 32 位模式的区别：32 位使用 `%ESI`, `%EAX` 等（E 前缀）

2. **64 位指令**：
   - `movq`（64 位移动）、`leaq`（64 位地址加载）、`pushq`（64 位压栈）、`lretq`（64 位长返回）
   - 与 32 位模式的区别：32 位使用 `movl`, `leal`, `pushl`, `lretl` 等

3. **%rip 相对寻址**：
   - `leaq __top_init_kernel_stack(%rip), %rsp` - 使用 `%rip` 相对寻址
   - 这是 64 位长模式特有的寻址方式，简化了位置无关代码（PIC）

4. **64 位代码段选择子**：
   - `__KERNEL_CS` 是 64 位代码段选择子，其描述符的 `CS.L = 1`（Long mode）
   - 与 32 位模式的区别：32 位代码段选择子的 `CS.L = 0`

5. **64 位 MSR 寄存器访问**：
   - `wrmsr` 指令写入 64 位 MSR 寄存器（`GS_BASE`）
   - 使用 `%EAX`（低 32 位）和 `%EDX`（高 32 位）组合成 64 位值

**关键步骤（体现 64 位长模式）：**
- **第 2550 行**：使用 64 位寄存器 `%RSI`, `%R15`（R 前缀表示 64 位）
- **第 2553-2556 行**：使用 `%rip` 相对寻址（`leaq ...(%rip)`），这是 64 位长模式特有
- **第 2560-2564 行**：使用 `wrmsr` 指令写入 64 位 MSR 寄存器（`GS_BASE`）
- **第 2568 行**：调用 `__pi_startup_64_setup_gdt_idt` 设置 GDT 和早期 IDT
- **第 2571-2576 行**：使用 `pushq` 和 `lretq`（64 位指令），使用 `__KERNEL_CS`（64 位代码段选择子）
- **第 2585-2586 行**：使用 `movq`（64 位移动）和 64 位寄存器 `%r15`, `%rdi`
- 此时内核已切换到 64 位长模式

**GDT 和 IDT 的区别：**

| 特性 | GDT（全局描述符表） | IDT（中断描述符表） |
|------|------------------|------------------|
| **全称** | Global Descriptor Table | Interrupt Descriptor Table |
| **用途** | 定义内存段（代码段、数据段等） | 定义中断处理程序 |
| **访问方式** | 通过段选择子（Segment Selector） | 通过中断向量号（0-255） |
| **寄存器** | GDTR（GDT 基址和界限） | IDTR（IDT 基址和界限） |
| **加载指令** | `LGDT` | `LIDT` |
| **条目内容** | 段描述符（基址、界限、权限等） | 中断门/陷阱门/任务门（处理程序地址） |
| **主要功能** | 内存分段和保护 | 中断处理和异常处理 |
| **使用场景** | 代码段、数据段、栈段的定义 | CPU 异常、硬件中断、软件中断的处理 |

**简单理解：**
- **GDT**：定义"内存段是什么"（代码段在哪里、数据段在哪里、权限如何）
- **IDT**：定义"中断发生时跳转到哪里"（INT 10h 跳到哪里、页故障跳到哪里）

