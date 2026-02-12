# Linux 内核启动与初始化（64 位，不走 Setup）

## 文档简介

本文档按**实际执行顺序**描述从 GRUB（或 UEFI）进入压缩内核到 `start_kernel()` 及之后的完整流程：
- **不走 Setup**：GRUB 按 code32_start 跳转、UEFI 按 PE 入口跳转，直接进入压缩内核
- **包含两条启动路径**：BIOS/GRUB 路径和 UEFI 路径的完整流程
- **文档特点**：每个关键函数都标注了**文件名和行号**（基于 Linux v6.x 内核源码），方便源码定位

> **注**：从扇区 0 启动时的 Setup 流程见 [LINUX_KERNEL_SETUP_FLOW.md](LINUX_KERNEL_SETUP_FLOW.md)

## 执行顺序概览

### BIOS/GRUB 启动路径

```
GRUB/入口
    ↓
【阶段 1】压缩内核 startup_32（32 位模式切换）
    ↓
【阶段 2】压缩内核 startup_64（重定位拷贝、解压）
    ↓
【阶段 3】主内核 startup_64
    ↓
x86_64_start_kernel（早期 IDT）
    ↓
start_kernel()
    ↓
setup_arch（内存接管）
    ↓
trap_init（IDT异常门 + SYSCALL/SYSENTER MSR设置）
    ↓
init_IRQ（IDT硬件中断门 + INT 0x80）
    ↓
rest_init（创建 PID 1/2）
    ↓
核心进程启动
```

### UEFI 启动路径

```
UEFI 固件
    ↓
efi_pe_entry
    ↓
efi_stub_entry
    ↓
efi_decompress_kernel（解压）
    ↓
enter_kernel
    ↓
【阶段 3】主内核 startup_64（直接跳到这里，跳过阶段 1 和 2）
    ↓
后续流程与 BIOS 路径相同
```

> **重要**：UEFI 路径**完全跳过**压缩内核的 startup_32/startup_64，直接通过 EFI stub 解压并进入主内核。详见 [UEFI_VS_BIOS_BOOT.md](UEFI_VS_BIOS_BOOT.md)。

---

> **注**：关于 IDT 包含的内容（CPU 异常、硬件中断、软件中断）和系统调用的两种机制（INT 0x80 vs SYSCALL/SYSENTER），详见 [Linux 中断处理指南 - IDT 与中断类型概览](LINUX_INTERRUPT_GUIDE.md#idt-与中断类型概览)。

---

## 完整流程图（按执行顺序）

**重要说明**：以下流程图描述的是 **BIOS/GRUB 启动路径**。**UEFI 启动路径完全不同**，不经过 compressed/head_64.S 的 startup_32/startup_64，而是直接通过 EFI stub（efi_pe_entry → efi_stub_entry → efi_decompress_kernel）解压并跳转到主内核。详见本文档的"BIOS vs UEFI 两条完全不同的启动路径"章节。

**关键地址说明**（BIOS/GRUB 路径）：
- **1MB (0x100000)**：GRUB 加载压缩内核的位置，startup_32/startup_64 最初在这里执行
- **16MB (0x1000000)**：解压后内核的目标位置（CONFIG_PHYSICAL_START 配置，或 KASLR 随机地址）
- **16MB+ (约 38MB)**：重定位后的压缩内核位置（%rbx），从这里解压内核到 16MB（详见 [WHY_RELOCATE_COMPRESSED_KERNEL.md](WHY_RELOCATE_COMPRESSED_KERNEL.md)）

```
GRUB grub_relocator32_boot()（grub/grub-core/lib/i386/relocator.c）
    ↓
【阶段1】压缩内核 startup_32（arch/x86/boot/compressed/head_64.S:82）
    │   32位保护模式，位于 1MB 处
    ├─ 设置 GDT/栈/段寄存器
    ├─ 构建身份映射页表
    ├─ 启用 PAE、长模式、分页（CR4.PAE=1, EFER.LME=1, CR0.PG=1）
    └─ lret → 切换到 64 位长模式
        ↓
【阶段2】压缩内核 startup_64（arch/x86/boot/compressed/head_64.S:278）
    │   64位长模式
    ├─ 设置 64 位环境（段寄存器、栈、GDT）
    ├─ 重定位拷贝到高地址（约 38MB，详见 WHY_RELOCATE_COMPRESSED_KERNEL.md）
    ├─ 解压内核到 16MB
    │   extract_kernel()（arch/x86/boot/compressed/misc.c:334）
    └─ 跳转到主内核入口
        ↓
【阶段3】主内核 startup_64（arch/x86/kernel/head_64.S）
    ├─ 设置内核栈和 GS_BASE
    ├─ 加载内核 GDT 和早期 IDT
    │   startup_64_setup_gdt_idt()（arch/x86/boot/startup/gdt_idt.c:49）
    └─ 跳转到 x86_64_start_kernel
        ↓
x86_64_start_kernel()（arch/x86/kernel/head64.c:222）
    ├─ 重置页表（reset_early_page_tables）
    ├─ 清除 BSS（clear_bss）
    ├─ 设置早期 IDT【内核接管异常处理】
    │   idt_setup_early_handler()（arch/x86/kernel/idt.c:320）
    ├─ 建立内核高地址映射（0xFFFFFFFF80000000）
    └─ 调用 start_kernel()
        ↓
start_kernel()（init/main.c:898）
    ├─ 【早期初始化】
    │   ├─ local_irq_disable()
    │   ├─ boot_cpu_init()
    │   ├─ setup_arch()（arch/x86/kernel/setup.c:880）【内核接管物理内存，详见 LINUX_MEMORY_MANAGEMENT_EVOLUTION.md】
    │   │   ├─ e820__memory_setup()（arch/x86/kernel/e820.c:1354）
    │   │   ├─ e820__memblock_setup()（arch/x86/kernel/e820.c:1242）
    │   │   ├─ init_mem_mapping()（arch/x86/mm/init.c:758）
    │   │   └─ paging_init()（arch/x86/mm/init_64.c:819）
    │   ├─ build_all_zonelists()
    │   └─ trap_init()（arch/x86/kernel/traps.c:1561）【设置完整 IDT 和系统调用入口】
    │       ├─ setup_cpu_entry_areas()
    │       ├─ sev_es_init_vc_handling()
    │       ├─ cpu_init_exception_handling(true)【设置 IST】
    │       ├─ idt_setup_traps()（arch/x86/kernel/idt.c:232）
    │       └─ cpu_init() → syscall_init()（arch/x86/kernel/cpu/common.c:2234）
    │
    ├─ 【调度与中断初始化】
    │   ├─ sched_init()（kernel/sched/core.c:10056）
    │   ├─ init_IRQ()（arch/x86/kernel/irqinit.c:75）【设置硬件中断门】
    │   │   └─ idt_setup_apic_and_irq_gates()（arch/x86/kernel/idt.c:284）
    │   └─ local_irq_enable()
    │
    ├─ 【子系统初始化】
    │   ├─ console_init()（drivers/tty/tty_io.c:2872）
    │   ├─ vfs_caches_init()（fs/dcache.c:3277）
    │   └─ rest_init()（init/main.c:699）
    │
    └─ rest_init()
        ├─ 创建 PID 1（kernel_init）（kernel/fork.c:2718） → 启动用户空间 init
        ├─ 创建 PID 2（kthreadd）（kernel/fork.c:2697） → 管理内核线程
        └─ PID 0 进入 idle 循环（kernel/sched/idle.c:393）
```

### 文件路径约定

- `head_64.S` = `arch/x86/boot/compressed/head_64.S`（压缩内核）或 `arch/x86/kernel/head_64.S`（主内核）
- `head64.c` = `arch/x86/kernel/head64.c`
- `main.c` = `init/main.c`
- `setup.c` = `arch/x86/kernel/setup.c`
- `traps.c` = `arch/x86/kernel/traps.c`
- `idt.c` = `arch/x86/kernel/idt.c`
- `common.c` = `arch/x86/kernel/cpu/common.c`
- `irqinit.c` = `arch/x86/kernel/irqinit.c`
- `irq.c` = `arch/x86/kernel/irq.c`

### 行号说明

- 行号基于 Linux v6.x 内核源码
- 不同内核版本行号可能略有差异
- 行号用于定位函数，精确到函数起始行

### 三个关键进程

- **PID 0 (swapper/idle)**：内核初始化进程，最终进入 idle 循环，处理器空闲时运行
- **PID 1 (init)**：用户空间第一个进程，负责启动所有用户空间服务
- **PID 2 (kthreadd)**：内核线程守护进程，负责创建所有后续内核线程

---

## 一、从 GRUB 到压缩内核入口

**从 GRUB 启动时**：GRUB 不执行 bzImage 内的 Setup，按 boot_params 中 **code32_start** 所存地址跳转到**压缩内核**入口（startup_32，32 位保护模式）。**关键**：模式切换在压缩内核的 startup_32 中完成，解压在压缩内核的 startup_64 中完成（详见下文三个阶段）。vmlinuz 含 Setup（未压缩）与压缩内核（gzip）；GRUB 通过 relocator 机制将镜像复制到 0x100000、自填 boot_params、**按 code32_start 跳转**，不解压、不执行 Setup。GRUB 加载机制详见 [GRUB_KERNEL_LOADING.md](GRUB_KERNEL_LOADING.md)（GRUB 先读取到临时缓冲区，boot 时 relocator 复制到目标地址并跳转）。

**入口点**：BIOS/Legacy（如 GRUB）→ code32_start 处即 **startup_32**（x86_64：`arch/x86/boot/compressed/head_64.S:82`，`SYM_FUNC_START(startup_32)`）。UEFI → PE 的 AddressOfEntryPoint 跳转到 EFI stub（`efi_pe_entry` 等）。64 位内核用 `head_64.S`（压缩与主内核各一份，路径不同）；32 位用 `head_32.S`。

```
grub_relocator32_boot() → EIP = code32_start
    ↓
【阶段1】压缩内核 startup_32（32 位保护模式，arch/x86/boot/compressed/head_64.S:82）
```

---

## 二、压缩内核的三个阶段

**重要说明**：以下三个阶段**仅适用于 BIOS/GRUB 启动路径**。**UEFI 启动路径完全跳过【阶段1】和【阶段2】**，直接通过 EFI stub 解压并跳转到【阶段3】主内核 startup_64。详见"BIOS vs UEFI 两条完全不同的启动路径"章节。

**BIOS/GRUB 启动的三个阶段**：从 GRUB 到主内核需经过压缩内核的**三个阶段**，前两个阶段都在 `arch/x86/boot/compressed/head_64.S` 中：

- **【阶段1】startup_32（32位保护模式）**：模式切换，从32位切换到64位长模式
- **【阶段2】压缩内核 startup_64（64位长模式）**：重定位拷贝、解压内核
- **【阶段3】主内核 startup_64（64位长模式）**：主内核初始化（在 `arch/x86/kernel/head_64.S`）← UEFI 和 BIOS 路径在此汇合

### 【阶段1】压缩内核 startup_32 → 32位到64位的模式切换

**源代码位置**：`arch/x86/boot/compressed/head_64.S:82-274`

**模式切换顺序**：32 位保护模式 → GDT/栈/段、verify_cpu、算 %ebx → CR4.PAE → 构建身份映射页表（内联）→ CR3 → EFER.LME → CR0.PG → **lret** 到【阶段2】压缩内核 startup_64（64 位，同文件）。源码无 `setup_identity_mapping` 调用，页表在 startup_32 内内联构建（200-231行）。

**startup_32 关键步骤（head_64.S 压缩内核，与源码顺序一致）**：

实际源码中 **无** `setup_identity_mapping` 调用；身份映射页表在 startup_32 内**内联**构建（Build Level 4/3/2），且 **GDT/栈/段** 在 **CR4/页表/CR3/EFER/CR0** 之前。

```
startup_32
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
| 算 %ebx | 非 RELOCATABLE：%ebx = LOAD_PHYSICAL_ADDR；RELOCATABLE：%ebx 按 BP_kernel_alignment 对齐；再 %ebx += BP_init_size − rva(_end) | **%ebx = 重定位目标地址**（通常在 16MB 以上，例如约 22MB），解压前要把压缩内核拷到这里；同时 pgtable 将建在 rva(pgtable)(%ebx)，以便拷到 %ebx 后 CR3 仍有效 |
| CR4.PAE | orl $X86_CR4_PAE, %cr4 | 开启物理地址扩展，长模式分页前提 |
| 构建页表 | 在 rva(pgtable)(%ebx) 处内联建 4 级页表（L4/L3/L2），身份映射前 4G；CONFIG_AMD_MEM_ENCRYPT 时 %edx 为加密位掩码 | 开启分页后需有效页表；身份映射保证当前指令与数据在开 PG 后仍可访问。MMU 与分页概念见 [Linux 内核分页机制完整指南](LINUX_MEMORY_MANAGEMENT_EVOLUTION.md) |
| CR3 | movl rva(pgtable)(%ebx), %cr3 | 让 CPU 使用刚建好的页表 |
| EFER.LME | rdmsr MSR_EFER；btsl LME；wrmsr | 允许长模式；与 CR0.PG 一起生效后进入长模式（先为 32 位兼容子模式） |
| lldt / ltr | 清 LDTR；TR = __BOOT_TSS（GDT 中） | 进入长模式前 TSS 需有效，供后续 64 位栈等使用 |
| CR0.PG + lret | movl $CR0_STATE, %cr0；此前已 push __KERNEL_CS、rva(startup_64)(%ebp)；lret | 开启分页并进入长模式；lret 弹出 CS:EIP，**CS = __KERNEL_CS（64 位段）** 后真正进入 64 位，EIP = startup_64 |

**关键寄存器用途**（startup_32 阶段）：

| 寄存器 | 含义 | 使用方式 |
|--------|------|----------|
| **%esi** | 引导程序传入的 **boot_params** 指针（物理地址） | BP_scratch（临时栈）、BP_init_size、BP_kernel_alignment 等；只读使用 |
| **%ebp** | **当前加载基址**（startup_32 所在运行地址；由 call/popl/subl 算出） | 所有 rva(…)(%ebp)：GDT、boot_stack_end、startup_64、pgtable 等在当前镜像中的运行地址 |
| **%ebx** | **重定位目标**（解压前拷贝目标；通常约 38MB，参见 [WHY_RELOCATE_COMPRESSED_KERNEL.md](WHY_RELOCATE_COMPRESSED_KERNEL.md)） | 计算公式：%ebx = %rbp + BP_init_size − rva(_end)；页表建在 rva(pgtable)(%ebx)，以便拷贝到 %ebx 后 CR3 仍指向有效页表；后续 64 位 startup_64 里 rep movsq 目标也是 %rbx |
| **CR4** | PAE = 1 | 启用物理地址扩展 |
| **CR3** | 页表基址 | 指向 rva(pgtable)(%ebx)（当前即 %ebx + rva(pgtable)） |
| **EFER** | LME = 1 | 长模式使能（与 CR0.PG 同时生效） |
| **CR0** | PG = 1（CR0_STATE） | 开启分页；与 EFER.LME 一起使 CPU 进入长模式 |

**startup_32 内“构建页表 → CR3 → EFER → CR0 → lret”片段（与源码一致）**：

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

> **📖 详细分析**：重定位拷贝与原地解压的完整技术细节请参阅：[COMPRESSED_KERNEL_RELOCATION.md](COMPRESSED_KERNEL_RELOCATION.md)
> - 为何需要重定位拷贝
> - 地址计算公式（%rbp、%rbx）
> - vmlinuz 文件结构分析
> - 原地解压的精妙设计
> - extract_kernel 为何不被覆盖

**压缩内核 startup_64 关键步骤**：

```
压缩内核 startup_64（.code64）
    ├─ cld, cli；设置段寄存器（290-299行）
    ├─ 计算解压目标 %rbp（LOAD_PHYSICAL_ADDR，通常 16MB）与重定位目标 %rbx（通常 38MB）（314-331行）
    ├─ 设置栈（334行）
    ├─ 加载 GDT、lretq 切换到 __KERNEL_CS（357-366行）
    ├─ 保存 boot_params 到 %r15（374行）
    ├─ load_stage1_idt（376行）
    ├─ sev_enable（390行，CONFIG_AMD_MEM_ENCRYPT）
    ├─ configure_5level_paging（409行）
    ├─ 【重定位拷贝】rep movsq：将压缩内核从 1MB 拷贝到 %rbx（通常 38MB）（419-425行）
    │       └─ 为何重定位？见 COMPRESSED_KERNEL_RELOCATION.md
    ├─ 重新加载 GDT（432-435行）
    └─ jmp .Lrelocated（440-441行）→ 跳转到重定位后的 .Lrelocated 标签
        ↓
.Lrelocated
    ├─ 清除 BSS（450-455行）
    ├─ load_stage2_idt（457行）
    ├─ initialize_identity_maps（461行）
    ├─ 【解压内核】call extract_kernel()（469行）← 关键：在这里解压内核！
    │       ├─ 从 %rbx (38MB) 处读取压缩数据
    │       ├─ 向 %rbp (16MB) 处写入解压数据
    │       ├─ choose_random_location()（可选 KASLR）
    │       ├─ decompress_kernel() 解压到 output（通常 0x1000000）
    │       ├─ 解析解压后 ELF，handle_relocations()
    │       └─ 返回主内核入口地址到 %rax
    └─ jmp *%rax（475行）→ 【阶段3】跳转到主内核 startup_64
```

**关键地址说明**：
- **1MB (0x100000)**：GRUB 加载压缩内核的初始位置
- **16MB (0x1000000)**：解压目标地址（%rbp，CONFIG_PHYSICAL_START）
- **38MB (约 0x2600000)**：重定位后的压缩内核位置（%rbx，计算公式见详细文档）

**重定位的核心原因**：
1. **避免自解压覆盖**：解压器代码和压缩数据都在同一个 bzImage 中，如果不重定位，解压到 16MB 可能覆盖 1MB 处正在执行的代码
2. **支持 KASLR**：解压目标可能是任意地址，重定位确保在所有场景下都安全
3. **原地解压优化**：重定位后 VO（解压目标）和 ZO（压缩源）完全分离，实现高效的原地解压

**地址计算公式**（详见 [COMPRESSED_KERNEL_RELOCATION.md](COMPRESSED_KERNEL_RELOCATION.md)）：
```
%rbp = LOAD_PHYSICAL_ADDR (通常 0x1000000，即 16MB)
%rbx = %rbp + BP_init_size - rva(_end)
     = 16MB + 初始化总大小 - 压缩内核大小
     = 16MB + 32.87MB - 9.91MB ≈ 38.96MB
```

### BIOS vs UEFI 两条完全不同的启动路径

**关键发现**：UEFI 启动路径**完全不经过** `arch/x86/boot/compressed/head_64.S` 的 `startup_32` 和 `startup_64`！

#### BIOS/GRUB 启动路径

```
GRUB relocator
    ↓
压缩内核 @ 1MB (0x100000)
    ↓
arch/x86/boot/compressed/head_64.S::startup_32 ← 32位保护模式入口
    ├─ 设置 GDT、栈、段
    ├─ CR4.PAE、构建身份映射页表、CR3
    ├─ EFER.LME、CR0.PG
    └─ lret → startup_64（压缩内核）
    ↓
arch/x86/boot/compressed/head_64.S::startup_64 ← 64位长模式，在 1MB 处执行
    ├─ 计算 %rbp（解压目标，通常 16MB 或 KASLR 随机地址）
    ├─ 计算 %rbx（重定位目标，通常 38MB）
    ├─ rep movsq：拷贝压缩内核从 1MB → %rbx (38MB)（为什么？见 [WHY_RELOCATE_COMPRESSED_KERNEL.md](WHY_RELOCATE_COMPRESSED_KERNEL.md)）
    ├─ jmp .Lrelocated：跳到 %rbx 处继续执行
    ├─ call extract_kernel()：从 %rbx 处解压到 %rbp (16MB)（不覆盖执行代码，见 [SOLUTION_ICACHE_MYSTERY.md](SOLUTION_ICACHE_MYSTERY.md)）
    │       ├─ input_data 在 %rbx 处（重定位后的压缩数据）
    │       ├─ outbuf = %rbp (16MB)
    │       ├─ __decompress(input_data, ..., outbuf, ...)
    │       ├─ parse_elf(outbuf) → 返回 startup_64 入口
    │       └─ return entry
    └─ jmp *%rax → 跳到主内核 startup_64
    ↓
arch/x86/kernel/head_64.S::startup_64 ← 主内核入口
```

#### UEFI 启动路径

```
UEFI 固件加载 PE 格式的压缩内核 @ 任意地址（如 300MB）
    ↓
efi_pe_entry() ← UEFI PE 入口点（在压缩镜像中）
    ↓
efi_stub_entry() ← EFI stub 主函数
    ↓
efi_decompress_kernel(&kernel_entry, boot_params)
    ├─ virt_addr = LOAD_PHYSICAL_ADDR (16MB，KASLR 时会调整)
    ├─ alloc_size = max(output_len, kernel_total_size)
    ├─ 【KASLR】virt_addr += (range * seed[1]) >> 32
    ├─ efi_random_alloc(..., &addr, ...) ← 分配内存 @ 16MB~512MB
    │       └─ addr 可能是 16MB、180MB、300MB 等任意对齐地址
    ├─ decompress_kernel((void *)addr, virt_addr, error)
    │       ├─ input_data 仍在原地址 300MB（压缩镜像中的压缩数据）
    │       ├─ outbuf = (void *)addr（EFI 分配的新地址）
    │       ├─ __decompress(input_data, input_len, ..., outbuf, output_len, ...)
    │       ├─ parse_elf(outbuf) → 返回 vmlinux 的 e_entry
    │       │       └─ e_entry 指向 arch/x86/kernel/head_64.S::startup_64
    │       ├─ handle_relocations(outbuf, output_len, virt_addr)
    │       └─ return entry
    ├─ kernel_entry = addr + entry
    └─ return kernel_entry
    ↓
exit_boot(boot_params, handle) ← 退出 EFI boot services
    ↓
sev_enable(boot_params) ← SEV 初始化
    ↓
efi_5level_switch() ← 5级页表切换（如需要）
    ↓
enter_kernel(kernel_entry, boot_params)
    ├─ asm("jmp *%0"::"r"(kernel_addr), "S"(boot_params))
    └─ 直接跳转到主内核 startup_64
    ↓
arch/x86/kernel/head_64.S::startup_64 ← 主内核入口
    ↓
完全跳过了 compressed/head_64.S 的 startup_32 和 startup_64！
```

#### 关键区别总结

| 特性 | BIOS/GRUB 路径 | UEFI 路径 |
|------|---------------|-----------|
| **压缩内核初始位置** | 1MB (0x100000)，GRUB relocator 复制到此 | 任意地址（如 300MB），UEFI 固件直接加载 PE 文件 |
| **是否经过 compressed/head_64.S** | ✅ 是，startup_32 → startup_64 | ❌ **否**，完全跳过 |
| **模式切换** | startup_32 中从 32位切换到 64位 | UEFI 固件已在 64位长模式，无需切换 |
| **是否需要重定位拷贝** | ✅ 需要（rep movsq 从 1MB → %rbx，参见 [WHY_RELOCATE_COMPRESSED_KERNEL.md](WHY_RELOCATE_COMPRESSED_KERNEL.md)） | ❌ 不需要，EFI stub 直接分配内存并解压 |
| **解压器在哪里** | compressed/head_64.S::startup_64 调用 extract_kernel() | efi_stub_entry() 调用 efi_decompress_kernel() |
| **解压函数** | arch/x86/boot/compressed/misc.c::extract_kernel() | 同一个 decompress_kernel()，但由 EFI stub 调用（详见 [UEFI_VS_BIOS_BOOT.md](UEFI_VS_BIOS_BOOT.md)） |
| **input_data 位置** | 重定位后的 %rbx 处（22MB） | 原始 PE 文件中（300MB） |
| **outbuf 位置** | %rbp (16MB，或 KASLR 随机) | EFI 分配的 addr (16MB~512MB) |
| **跳转到主内核** | jmp *%rax（从 .Lrelocated） | jmp *kernel_entry（从 enter_kernel） |
| **最终目标** | arch/x86/kernel/head_64.S::startup_64 | 同上（两条路径在此汇合） |

#### 源代码验证

**vmlinux 的 ELF 入口点**（`arch/x86/kernel/vmlinux.lds.S:127`）：
```lds
phys_startup_64 = ABSOLUTE(startup_64 - LOAD_OFFSET);
ENTRY(phys_startup_64)
```

**arch/x86/kernel/head_64.S:50-51 的注释**：
```c
/*
 * We come here either directly from a 64bit bootloader, or from
 * arch/x86/boot/compressed/head_64.S.
 */
```
明确说明了两条路径：
- BIOS/GRUB：从 `arch/x86/boot/compressed/head_64.S` 来
- UEFI：直接从 64位 bootloader（UEFI 固件）来

#### 为什么 UEFI 不需要重定位拷贝？

**UEFI 路径的优势**：
1. **内存管理更灵活**：通过 `efi_random_alloc()` 分配目标内存
2. **压缩数据和解压目标天然隔离**：
   - 压缩数据：在 UEFI 加载的 PE 文件中（如 300MB）
   - 解压目标：EFI 分配的新内存（如 180MB）
   - 两者由 EFI 内存管理器保证不重叠
3. **不需要自解压**：
   - BIOS 路径：解压器代码在压缩内核中，自己解压自己，必须先移走
   - UEFI 路径：EFI stub 在压缩镜像中，但解压时已分配好目标内存，直接解压即可

**BIOS 路径为什么需要重定位**：
1. **自解压困境**：解压器代码和压缩数据都在 1MB 处
2. **栈和数据在解压路径上**：即使解压到 16MB，栈和临时数据可能在 1MB~2MB 之间
3. **支持 CONFIG_RELOCATABLE**：解压目标可能是任意地址（KASLR、kexec）
   - 场景：当前在 32MB，解压到 32MB，必须先移走
4. **通用性设计**：一套代码支持所有启动场景

**结论**：重定位拷贝机制是 BIOS/GRUB 路径的特有需求，UEFI 路径通过 EFI boot services 的内存管理完全避免了这个问题。

### 为什么解压后的内核要放到 0x1000000 (16MB) 而不是原地解压？

**关键理解**：有两个不同的地址概念：
- **压缩内核加载地址**：0x100000 (1MB) - GRUB 将 bzImage 加载到这里
- **解压后内核目标地址**：0x1000000 (16MB) - CONFIG_PHYSICAL_START 的默认值

**为什么不能原地解压（在 1MB 处解压）？**

1. **大小问题**：解压后的内核远大于压缩内核
   - 压缩的 bzImage：通常几 MB
   - 解压后的 vmlinux：通常几十 MB（包含 .text、.data、.bss、.brk 等）
   - 如果在 1MB 处原地解压，可能会覆盖其他重要内存区域

2. **安全隔离**：避免覆盖正在执行的代码
   - 虽然已经通过重定位拷贝将压缩内核移到安全位置
   - 但如果解压目标也在 1MB 附近，仍可能发生冲突

3. **内核配置**：`CONFIG_PHYSICAL_START` 决定解压目标
   - **默认值**：`0x1000000` (16MB)（[arch/x86/Kconfig](https://github.com/torvalds/linux/blob/master/arch/x86/Kconfig)）
   - **配置说明**：
     ```
     config PHYSICAL_START
         hex "Physical address where the kernel is loaded"
         default "0x1000000"
         help
           This gives the physical address where the kernel is loaded.

           If the kernel is not relocatable (CONFIG_RELOCATABLE=n) then
           bzImage will decompress itself to above physical address and
           run from there.
     ```
   - **LOAD_PHYSICAL_ADDR** 宏定义：
     - 位置：[arch/x86/include/asm/page_types.h:32](https://github.com/torvalds/linux/blob/master/arch/x86/include/asm/page_types.h#L32)
     - 定义：`LOAD_PHYSICAL_ADDR = __ALIGN_KERNEL_MASK(CONFIG_PHYSICAL_START, CONFIG_PHYSICAL_ALIGN - 1)`

4. **源代码中的体现**（`arch/x86/boot/compressed/head_64.S:314-326`）：
   ```asm
   /* Start with the delta to where the kernel will run at. */
   #ifdef CONFIG_RELOCATABLE
       leaq    startup_32(%rip), %rbp
       movl    BP_kernel_alignment(%rsi), %eax
       decl    %eax
       addq    %rax, %rbp
       notq    %rax
       andq    %rax, %rbp
       cmpq    $LOAD_PHYSICAL_ADDR, %rbp
       jae     1f
   #endif
       movq    $LOAD_PHYSICAL_ADDR, %rbp    # ← 设置解压目标为 LOAD_PHYSICAL_ADDR
   1:
   ```
   - `%rbp` 被设置为 `LOAD_PHYSICAL_ADDR`（通常 16MB）
   - 然后传给 `extract_kernel(rmode, output)` 作为 output 参数

5. **原地解压（in-place decompression）的限制**：
   - 从 `arch/x86/boot/compressed/misc.c:389-404` 的注释可以看到：
     ```c
     /*
      * The compressed kernel image (ZO), has been moved so that its position
      * is against the end of the buffer used to hold the uncompressed kernel
      * image (VO) and the execution environment (.bss, .brk), which makes sure
      * there is room to do the in-place decompression.
      */
     ```
   - 即使支持原地解压，也需要精心计算位置以避免覆盖

**总结**：解压到 16MB 而不是 1MB 是为了：
- ✅ 提供足够的空间容纳解压后的大内核
- ✅ 避免与低地址的其他用途冲突
- ✅ 遵循 `CONFIG_PHYSICAL_START` 的配置约定
- ✅ 支持可重定位内核（CONFIG_RELOCATABLE）和 KASLR 的灵活性

### 为什么压缩内核必须加载到 0x100000 (1MB)？

**历史约定与内存布局限制**：

根据 **Linux Boot Protocol** 官方文档（[Documentation/arch/x86/boot.rst](https://github.com/torvalds/linux/blob/master/Documentation/arch/x86/boot.rst)），**压缩内核（bzImage）加载到 0x100000** 的原因是：

**1. 前 1MB 内存布局限制**

```
0x000000 - 0x09FFFF (640KB)  常规 RAM（Conventional Memory）
    ├─ 0x000000 - 0x003FF：IVT（中断向量表）
    ├─ 0x000400 - 0x004FF：BDA（BIOS 数据区）
    ├─ 0x007C00 - 0x007DFF：引导扇区加载位置
    └─ 其余部分：可用 RAM（但只有约 640KB）

0x0A0000 - 0x0FFFFF (384KB)  I/O 内存洞（I/O Memory Hole）
    ├─ 0x0A0000 - 0x0BFFFF：显存（VGA Video Memory）
    ├─ 0x0C0000 - 0x0EFFFF：设备 ROM（如网卡、SCSI 卡等）
    └─ 0x0F0000 - 0x0FFFFF：BIOS ROM 映射（系统 BIOS）

0x100000+ (1MB 以上)         扩展内存（Extended Memory/High Memory）
    └─ 第一个可用的大块连续物理内存区域
```

**2. Boot Protocol 明确规定**（[Documentation/arch/x86/boot.rst:120-125](https://github.com/torvalds/linux/blob/master/Documentation/arch/x86/boot.rst#L120-L125)）

> When using bzImage, the protected-mode kernel was relocated to
> 0x100000 ("high memory"), and the kernel real-mode block (boot sector,
> setup, and stack/heap) was made relocatable to any address between
> 0x10000 and end of low memory.
>
> — Linux Boot Protocol 官方文档

**3. 为什么选择 0x100000？**

- ✅ **避开 I/O 内存洞**：0x0A0000-0x0FFFFF 被硬件设备（显卡、ROM）占用，不能用于加载内核
- ✅ **扩展内存的起始位置**：0x100000 是扩展内存的第一个地址，是第一个可用的大块连续内存
- ✅ **保护模式可访问**：在保护模式下，0x100000+ 的内存可以被线性访问
- ✅ **历史约定**：从 Linux 内核早期开始，bzImage 格式就规定保护模式内核必须放在 0x100000

**4. 代码中的定义**

- **内核配置**：`CONFIG_PHYSICAL_START` 通常默认为 `0x1000000` (16MB) 或可配置
  - 配置文件：[arch/x86/Kconfig](https://github.com/torvalds/linux/blob/master/arch/x86/Kconfig)
- **加载地址**：`LOAD_PHYSICAL_ADDR` = `__ALIGN_KERNEL_MASK(CONFIG_PHYSICAL_START, CONFIG_PHYSICAL_ALIGN - 1)`
  - 定义在：[arch/x86/include/asm/page_types.h:32](https://github.com/torvalds/linux/blob/master/arch/x86/include/asm/page_types.h#L32)
- **Boot protocol 约定**：bzImage 的压缩内核部分加载到 `0x100000`（`GRUB_LINUX_BZIMAGE_ADDR`）
  - GRUB 代码：[grub-core/loader/i386/linux.c](https://github.com/rhboot/grub2/blob/fedora-38/grub-core/loader/i386/linux.c)

**5. 现代内核的灵活性**

- **KASLR（Kernel Address Space Layout Randomization）**：现代内核支持随机化加载地址，但仍以 0x100000 为基准
- **可重定位内核**：从 Boot Protocol 2.05 开始，内核支持重定位（relocatable_kernel），但默认仍使用 0x100000

**总结**：0x100000 (1MB) 是 x86 架构上**第一个可用的大块连续物理内存地址**，避开了前 640KB 的常规 RAM 和 640KB-1MB 的 I/O 内存洞，因此成为 Linux Boot Protocol 规定的保护模式内核加载地址。

> **相关文档**：
> - [BIOS_MEMORY_LAYOUT.md](BIOS_MEMORY_LAYOUT.md) - 详细的 BIOS 内存布局说明（包括前 1MB 内存分配、I/O 内存洞等）
> - [GRUB_KERNEL_LOADING.md](GRUB_KERNEL_LOADING.md) - GRUB 如何将内核加载到 0x100000
> - Linux Boot Protocol: [Documentation/arch/x86/boot.rst](https://github.com/torvalds/linux/blob/master/Documentation/arch/x86/boot.rst)

---

## 三、【阶段3】主内核 startup_64 → x86_64_start_kernel → start_kernel()

### 3.1 startup_64 执行流程概览

**源代码位置**：`arch/x86/kernel/head_64.S:38`

**重要**：这是第二个 startup_64（【阶段3】主内核），与【阶段2】压缩内核中的 startup_64（`arch/x86/boot/compressed/head_64.S:278`）是**不同的文件**。

**主内核 startup_64 的主要任务**：
1. 保存 boot_params（%RSI → %R15）
2. 设置初始内核栈（__top_init_kernel_stack）
3. 清零 GS 基址（MSR_GS_BASE）
4. **调用 startup_64_setup_gdt_idt 设置 GDT 和早期 IDT**
5. 切换到内核代码段（__KERNEL_CS）
6. 可选：AMD SEV/SME 支持（sme_enable）
7. CPU 兼容性检查（verify_cpu）
8. 进入 C 代码（x86_64_start_kernel）

**执行流程图**：

```
startup_64
    ├─ mov %rsi, %r15                           // 保存 boot_params
    ├─ leaq __top_init_kernel_stack(%rip), %rsp // 设置初始内核栈
    ├─ wrmsr（MSR_GS_BASE）                      // GS 基址清零
    ├─ call startup_64_setup_gdt_idt            // ★ 设置 GDT 和早期 IDT
    ├─ pushq $__KERNEL_CS; lretq                // 切换到内核代码段
    ├─ 可选 sme_enable（CONFIG_AMD_MEM_ENCRYPT）
    ├─ call verify_cpu
    └─ 进入 C 代码（x86_64_start_kernel）
```

**startup_64 完整源代码**（`arch/x86/kernel/head_64.S:38-98`）：

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

**为何说这里是"早期"的 GDT/IDT**：
- **时机最早**：这是主内核启动后第一次设置 GDT 和 IDT，发生在进入完整 C 内核之前
- **功能最小**：只提供基本的段描述符和临时 IDT，后续会被完善和替换
- **目的单一**：确保在最小环境下能正常运行，避免 tracing/KASAN 等机制干扰

---

### 3.2 startup_64_setup_gdt_idt 实现详解

**源代码位置**：`arch/x86/boot/startup/gdt_idt.c:49-70`

这个 C 函数在主内核 startup_64 中被汇编代码调用，负责设置早期 GDT 和 IDT。

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

**执行步骤**（按顺序）：

#### 步骤 1：加载 GDT（lgdt）

```c
// 1. 主入口：加载 GDT、重载 DS/SS/ES、再调 startup_64_load_idt（49-70）
void __head startup_64_setup_gdt_idt(void)
{
	struct gdt_page *gp = rip_rel_ptr((void *)&gdt_page);   // GDT 在 cpu/common.c
	struct desc_ptr startup_gdt_descr = { 
		.address = (unsigned long)gp->gdt, 
		.size = GDT_SIZE - 1 
	};
	native_load_gdt(&startup_gdt_descr);   // → lgdt
	// ...
}

// native_load_gdt() 是内联函数，编译后展开为一条 lgdt 指令
static inline void native_load_gdt(const struct desc_ptr *dtr)
{
	asm volatile("lgdt %0"::"m" (*dtr));   // 加载 GDT
}
```

**lgdt 指令**：
- 将 GDT 描述符（6 字节：2 字节界限 + 4/8 字节基址）加载到 GDTR 寄存器
- CPU 后续的段选择子引用都将查询这个 GDT

#### 步骤 2：重载段寄存器（DS/SS/ES）

```c
// GDT 加载后必须显式刷新数据段选择子
asm volatile("movl %%eax, %%ds\n"
	     "movl %%eax, %%ss\n"
	     "movl %%eax, %%es\n" 
	     : : "a"(__KERNEL_DS) : "memory");
```

**为何需要重载**：
- lgdt 指令只更新 GDTR，不自动更新段寄存器的缓存描述符
- 必须显式写入段选择子，触发 CPU 从新 GDT 中重新加载段描述符
- DS/SS/ES 都设置为 __KERNEL_DS（内核数据段选择子）

#### 步骤 3：加载 IDT（lidt）

```c
void __head startup_64_load_idt(void *vc_handler)
{
	struct desc_ptr desc = { 
		.address = (unsigned long)rip_rel_ptr(bringup_idt_table),
		.size = sizeof(bringup_idt_table) - 1 
	};
	
	// 可选：为 AMD SEV 填充 #VC 向量
	if (vc_handler) {
		init_idt_data(&data, X86_TRAP_VC, vc_handler);
		idt_init_desc(&idt_desc, &data);
		native_write_idt_entry(..., X86_TRAP_VC, &idt_desc);
	}
	
	native_load_idt(&desc);   // → lidt
}

// native_load_idt() 同样是内联函数，展开为一条 lidt 指令
static __always_inline void native_load_idt(const struct desc_ptr *dtr)
{
	asm volatile("lidt %0"::"m" (*dtr));   // 加载 IDT
}

// 静态 IDT 表：早期使用，大部分为空
static gate_desc bringup_idt_table[NUM_EXCEPTION_VECTORS] __page_aligned_data;
```

**lidt 指令**：
- 将 IDT 描述符加载到 IDTR 寄存器
- CPU 后续的中断/异常将查询这个 IDT

#### 步骤 4：调用返回后

**call startup_64_setup_gdt_idt** 返回到 head_64.S 后，执行：

```asm
pushq	$__KERNEL_CS       # 压入内核代码段选择子
leaq	.Lon_kernel_cs(%rip), %rax
pushq	%rax               # 压入返回地址
lretq                      # 远返回，CS ← __KERNEL_CS，RIP ← .Lon_kernel_cs
```

**lretq 的作用**：
- 从栈弹出返回地址和代码段选择子
- 同时更新 CS 寄存器，触发 CPU 从新 GDT 加载代码段描述符
- 此后所有代码都在新 GDT 的 __KERNEL_CS 段中执行

**汇编调用 C 函数的机制**：

通过链接时的符号解析，将汇编中的 `call startup_64_setup_gdt_idt` 指令绑定到 C 函数的入口地址。运行时直接跳转，C 函数执行完毕后 `ret` 返回到汇编的下一条指令。

---

### 3.3 GDT（全局描述符表）深入解析

#### 3.3.1 加载的 GDT 内容

**GDT 来源**：通过 **early_gdt_descr**（arch/x86/kernel/head_64.S）引用的 **gdt_page**（arch/x86/kernel/cpu/common.c）

**early_gdt_descr 定义**（arch/x86/kernel/head_64.S）：
```asm
early_gdt_descr:
    .word   GDT_ENTRIES*8-1
early_gdt_descr_base:
    .quad   INIT_PER_CPU_VAR(gdt_page)  # 指向 gdt_page
```

**GDT 表的具体内容**（arch/x86/kernel/cpu/common.c:201-243）：

```c
DEFINE_PER_CPU_PAGE_ALIGNED(struct gdt_page, gdt_page) = { .gdt = {
#ifdef CONFIG_X86_64
    [GDT_ENTRY_KERNEL32_CS]      = GDT_ENTRY_INIT(DESC_CODE32, 0, 0xfffff),  // 索引 1
    [GDT_ENTRY_KERNEL_CS]        = GDT_ENTRY_INIT(DESC_CODE64, 0, 0xfffff),  // 索引 2
    [GDT_ENTRY_KERNEL_DS]        = GDT_ENTRY_INIT(DESC_DATA64, 0, 0xfffff),  // 索引 3
    [GDT_ENTRY_DEFAULT_USER32_CS]= GDT_ENTRY_INIT(DESC_CODE32|DESC_USER, 0, 0xfffff), // 索引 4
    [GDT_ENTRY_DEFAULT_USER_DS]  = GDT_ENTRY_INIT(DESC_DATA64|DESC_USER, 0, 0xfffff), // 索引 5
    [GDT_ENTRY_DEFAULT_USER_CS]  = GDT_ENTRY_INIT(DESC_CODE64|DESC_USER, 0, 0xfffff), // 索引 6
#endif
} };
```

#### 3.3.2 x86_64 GDT 布局详解

| 索引 | 段选择子 | 描述 | 用途 |
|------|----------|------|------|
| 0 | - | NULL 描述符 | 必须为 0，访问会触发 #GP |
| 1 | `__KERNEL32_CS` | 32位内核代码段 | 兼容模式代码（IRET 需要） |
| 2 | `__KERNEL_CS` | **64位内核代码段** | **主要的内核代码段（CS.L=1）** |
| 3 | `__KERNEL_DS` | **内核数据段** | **DS/SS/ES 使用** |
| 4 | `__USER32_CS` | 32位用户代码段 | 32位用户程序（兼容模式） |
| 5 | `__USER_DS` | 用户数据段 | 用户空间 DS/SS |
| 6 | `__USER_CS` | 64位用户代码段 | 64位用户程序 |
| 8-9 | - | TSS 描述符（两个槽位） | 任务状态段（稍后设置） |
| 10-11 | - | LDT 描述符（两个槽位） | 局部描述符表（如果使用） |

**为何这样布局？** （arch/x86/include/asm/segment.h:173-186）

这个布局是为了支持 **SYSCALL/SYSRET 指令**的硬编码要求：

```
SYSRET 指令硬编码选择子：
- 返回 32位用户空间：CS = STAR.SYSRET_CS (索引 4)
- 返回 64位用户空间：CS = STAR.SYSRET_CS+16 (索引 6)
- SS = STAR.SYSRET_CS+8 (索引 5，在任何情况下)

因此用户数据段（索引 5）必须在 32位和 64位用户代码段之间！
```

**在 startup_64_setup_gdt_idt 中实际使用的段**：
- **CS**：索引 2（`__KERNEL_CS`），在后续的 `pushq $__KERNEL_CS; lretq` 中切换
- **DS/SS/ES**：索引 3（`__KERNEL_DS`），在 `asm volatile("movl %%eax, %%ds\n"...)` 中设置
- **TSS**：此阶段尚未设置，在后续 `cpu_init()` 中设置

#### 3.3.3 GDT 演化过程

GDT 在内核启动过程中经历 **4 个阶段**的演化（详见 [GDT 详解：从保护模式到长模式](X86_MEMORY_MANAGEMENT_THEORY.md)）：

| 阶段 | GDT 名称 | 位置 | 使用时机 | 特点 |
|------|---------|------|---------|------|
| **1** | GRUB GDT | grub-core/lib/i386/relocator.c | GRUB 加载内核前 | 临时 GDT，仅供引导 |
| **2** | 压缩内核 GDT | arch/x86/boot/compressed/head_64.S::gdt | startup_32/startup_64 | 临时 GDT，支持长模式切换 |
| **3** | 主内核早期 GDT | arch/x86/kernel/head_64.S::early_gdt_descr | startup_64_setup_gdt_idt | ← **当前阶段**，全局共享 |
| **4** | 运行时 per-CPU GDT | arch/x86/kernel/cpu/common.c::gdt_page | cpu_init() | 每个 CPU 独立，支持多核 |

**演化原因**：
- **阶段 1→2**：从 GRUB 环境进入内核环境，需要重新设置 GDT
- **阶段 2→3**：从压缩内核进入主内核，切换到主内核的 GDT
- **阶段 3→4**：从全局共享 GDT 切换到 per-CPU GDT，支持多核并发
  - 每个 CPU 需要独立的 TSS 描述符（指向该 CPU 的内核栈）
  - 避免多个 CPU 同时修改共享 GDT 导致的竞态条件
  - 支持 CPU 热插拔和动态配置

---

### 3.4 IDT（中断描述符表）深入解析

#### 3.4.1 加载的 IDT 内容

**IDT 来源**：**bringup_idt_table**（arch/x86/boot/startup/gdt_idt.c），静态定义的最小 IDT

```c
// 静态表：早期 IDT，页对齐，NUM_EXCEPTION_VECTORS 个门
static gate_desc bringup_idt_table[NUM_EXCEPTION_VECTORS] __page_aligned_data;
```

**IDT 特点**：
- 大小：仅 **32 个异常向量**（0-31），不包含硬件中断向量
- 内容：**大部分为空**（全零），仅在需要时填充 #VC 向量（AMD SEV）
- 用途：**临时占位**，确保在最小环境下不会因 IDT 无效而崩溃

#### 3.4.2 为何早期不能用完整 IDT

**关键原因**：避免 tracing/KASAN instrumentation 干扰

- 完整的 idt_table（arch/x86/kernel/idt.c）包含复杂的中断处理逻辑
- 早期启动阶段可能被 KASAN（内核地址消毒）、tracing 等机制插桩
- 这些插桩代码依赖完整的 C 运行环境，但早期环境尚未就绪
- 使用简单的 bringup_idt_table 确保在最小环境下可用

#### 3.4.3 IDT 演化过程

IDT 在内核启动过程中经历 **5 个阶段**的演化（详见 [IDT 表的演进流程详解](LINUX_KERNEL_IDT_EVOLUTION.md)）：

**两个 IDT 表**：

| IDT 表 | 大小 | 使用时机 | 用途 |
|--------|------|---------|------|
| **bringup_idt_table** | 32 个异常向量 | 极早期（startup_64 汇编） | 临时表，避免 tracing/KASAN 干扰 |
| **idt_table** | 256 个向量 | start_kernel 之后 | 运行时表，支持全部中断/异常 |

**5 个演进阶段**：

| 阶段 | 函数 | 时机 | 覆盖范围 | 状态 |
|------|------|------|---------|------|
| **阶段 0** | startup_64_load_idt() | 主内核 startup_64 | bringup_idt_table（几乎为空） | ← **当前阶段** |
| **阶段 1** | idt_setup_early_handler() | x86_64_start_kernel | 切换到 idt_table，填充早期异常向量 | 早期异常处理 |
| **阶段 2** | idt_setup_early_traps() | setup_arch | 补充 DB, BP, PF 等（带 IST） | 支持页表初始化 |
| **阶段 3** | idt_setup_traps() | trap_init | 补全所有异常向量并设置 IST | 完整异常处理 |
| **阶段 4** | idt_setup_apic_and_irq_gates() | init_IRQ | 填充 APIC/IRQ 并设为只读 | **IDT 完全就绪** |

**关键设计**：
- **临时表**：避免早期启动代码被 tracing/KASAN instrumentation 干扰
- **渐进完善**：从异常处理 → 硬件中断 → 软件中断（INT 0x80）
- **IST 机制**：关键异常（#DF, #NMI, #MC）使用独立栈，避免栈溢出

**启动过程中的中断状态**：
- startup_64 → x86_64_start_kernel：中断关闭（IF=0）
- start_kernel → trap_init：中断关闭（IF=0）
- trap_init → init_IRQ：中断关闭（IF=0）
- init_IRQ 之后：调用 local_irq_enable() 开启中断（IF=1）

---

### 3.5 GDT 与 IDT 对比总结

#### 3.5.1 演进对比

**GDT 演进**：
- **2 次加载**（early_gdt_descr → per-CPU GDT）
- **替换原因**：多核并发需求，每个 CPU 需要独立的 TSS

**IDT 演进**：
- **5 次演进**（bringup → early → early_traps → traps → apic_and_irq）
- **演进原因**：逐步完善功能，从异常处理到硬件中断

#### 3.5.2 核心区别

| 特性 | GDT（全局描述符表） | IDT（中断描述符表） |
|------|---------------------|---------------------|
| **用途** | 定义内存段（代码段、数据段等） | 定义中断/异常处理程序 |
| **访问方式** | 段选择子（Segment Selector） | 中断向量号（0–255） |
| **寄存器** | GDTR（GDT 基址与界限） | IDTR（IDT 基址与界限） |
| **加载指令** | LGDT | LIDT |
| **条目内容** | 段描述符（基址、界限、权限等） | 中断门/陷阱门（处理程序地址） |
| **主要功能** | 内存分段和保护 | 中断与异常处理 |
| **在启动阶段的状态** | 早期加载全局共享 GDT | 早期加载临时 bringup_idt_table |
| **后续演化** | 替换为 per-CPU GDT | 逐步完善为 idt_table |

**关键理解**：
- GDT 定义"段"（代码/数据/栈）的属性和边界
- IDT 定义"中断/异常"发生时跳转到哪里
- 早期 IDT 仅设置 CPU 异常，完整 IDT（包括硬件中断和 INT 0x80）在 init_IRQ() 中设置
- 现代系统调用（SYSCALL/SYSENTER）不通过 IDT，而是通过 MSR 寄存器配置（详见 [Linux 中断处理指南 - IDT 与中断类型概览](LINUX_INTERRUPT_GUIDE.md#idt-与中断类型概览)）

---

### 3.6 后续步骤与补充说明

#### 3.6.1 x86_64_start_kernel() 概述

startup_64 执行完毕后，进入 C 代码 **x86_64_start_kernel()**（`arch/x86/kernel/head64.c`）：

```c
void __init x86_64_start_kernel(void)
{
	// 切换到运行时 IDT（idt_table）
	idt_setup_early_handler();   // 填充早期异常向量
	load_idt(&idt_descr);         // 加载 idt_table
	
	// 后续初始化
	// - TDX 支持
	// - copy_bootdata
	// - load_ucode_bsp（加载微码）
	// - 建立内核高地址映射
	
	// 最终调用 start_kernel()
	x86_64_start_reservations() → start_kernel();
}
```

**idt_setup_early_handler() 的作用**：

```c
// arch/x86/kernel/idt.c
void __init idt_setup_early_handler(void)
{
	for (i = 0; i < NUM_EXCEPTION_VECTORS; i++)
		set_intr_gate(i, early_idt_handler_array[i]);
	load_idt(&idt_descr);
}
```

- 切换到运行时 IDT（idt_table，256 个向量）
- 填充早期异常处理程序（early_idt_handler_array）
- 此时 CPU 使用内核 IDT 取代 bringup_idt_table
- 注意：此时仅有 CPU 异常，尚无硬件 IRQ 和 INT 0x80

#### 3.6.2 位置无关代码（PIC）与 `__pi_` 前缀

**背景**：在 startup_64 早期阶段，内核尚未完全建立虚拟地址映射，需要使用**位置无关代码（Position Independent Code, PIC）**来访问全局符号。

**`__pi_` 前缀的含义**：

代码中的 `__pi_` 前缀符号（如 `__pi_startup_64_setup_gdt_idt`）是通过 `objcopy --prefix-symbols=__pi_` 自动生成的 PIC 版本。

**实现机制**：
- **编译时**：使用 `-fPIC` 选项编译，生成位置无关代码
- **链接时**：使用 `objcopy --prefix-symbols=__pi_` 为符号添加前缀
- **运行时**：通过 RIP 相对寻址访问全局符号，使用 `rip_rel_ptr()` 宏计算实际地址

**为何需要 PIC**：
- 早期阶段页表尚未完全建立，虚拟地址映射可能不完整
- 代码可能在不同的物理地址运行（如 KASLR 随机化）
- 需要通过相对寻址而非绝对地址访问全局数据

> **详细内容**：位置无关代码的完整实现机制（`-fPIC` 编译选项、`objcopy` 符号前缀处理、RIP 相对寻址、`rip_rel_ptr()` 宏、`SYM_PIC_ALIAS` 宏、以及 `startup_64_setup_gdt_idt()` 如何访问全局符号等），请参见 **[X86_POSITION_INDEPENDENT_CODE.md](X86_POSITION_INDEPENDENT_CODE.md)**。

#### 3.6.3 相关文档

本章涉及的核心机制详解：

- **[X86_MEMORY_MANAGEMENT_THEORY.md](X86_MEMORY_MANAGEMENT_THEORY.md)** - 内存管理理论篇 - 分段机制（GDT）、分页机制、多级页表设计原理、GDT 与分页的协作
- **[LINUX_MEMORY_MANAGEMENT_EVOLUTION.md](LINUX_MEMORY_MANAGEMENT_EVOLUTION.md)** - 内存管理演化篇 - 从 BIOS 到内核的完整过渡（BIOS → GRUB → 压缩内核 → 主内核）、GDT 和页表的四阶段演化
- **[LINUX_MEMORY_MANAGEMENT_CODE_GUIDE.md](LINUX_MEMORY_MANAGEMENT_CODE_GUIDE.md)** - 内存管理实现篇 - GDT 代码详解、页表代码详解、内存管理子系统、实战调试方法
- **[LINUX_KERNEL_IDT_EVOLUTION.md](LINUX_KERNEL_IDT_EVOLUTION.md)** - IDT 表的演进流程详解 - 两个 IDT 表（bringup_idt_table、idt_table）、5 个演进阶段、GDT/IDT 对比、IST 机制、中断状态管理
- **[X86_POSITION_INDEPENDENT_CODE.md](X86_POSITION_INDEPENDENT_CODE.md)** - 位置无关代码完整分析 - `__pi_` 前缀的含义、位置无关代码编译机制（-fPIC、objcopy --prefix-symbols）、RIP 相对寻址、`rip_rel_ptr()` 宏、`SYM_PIC_ALIAS` 宏的实现原理

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

**关键步骤**：`setup_arch(&command_line)`。此前仅有身份映射与 early 页表；**完整物理内存接管**在 setup_arch() 中：解析 e820/EFI、memblock、`init_mem_mapping()`、`paging_init()`。详见 [Linux 内核分页机制完整指南](LINUX_MEMORY_MANAGEMENT_EVOLUTION.md)。


### 2. trap_init() 与系统调用初始化

**trap_init()** 在 start_kernel() 阶段 2 被调用，主要完成：
1. 设置 CPU entry areas（setup_cpu_entry_areas()）
2. 初始化 IST 异常栈（cpu_init_exception_handling(true)）
3. 补全 IDT 异常门（idt_setup_traps()）
4. **初始化系统调用入口**（cpu_init() → syscall_init()）

**调用层级**：

```
start_kernel()
    └─ trap_init()（arch/x86/kernel/traps.c:1561）
        ├─ setup_cpu_entry_areas()
        │   └─ 为每个 CPU 设置 entry area（包括 IDT、GDT、TSS、异常栈等）
        ├─ sev_es_init_vc_handling()
        │   └─ SEV-ES 虚拟化支持（AMD 加密虚拟机）
        ├─ cpu_init_exception_handling(true)【设置 IST】
        │   ├─ 分配 per-CPU 异常栈（IST 栈）
        │   ├─ 配置 TSS.IST[] 数组
        │   └─ 加载 TR（Task Register）
        ├─ if (!cpu_feature_enabled(X86_FEATURE_FRED))
        │   └─ idt_setup_traps()（arch/x86/kernel/idt.c:232）
        │       ├─ 设置所有 CPU 异常向量（0-31）
        │       └─ 若启用 ia32，设置 INT 0x80（通过 ia32_idt）
        └─ cpu_init()
            └─ syscall_init()（arch/x86/kernel/cpu/common.c:2234）【内核接管 syscall】
                ├─ wrmsr(MSR_STAR, ...)           // 段选择子
                └─ if (!cpu_feature_enabled(X86_FEATURE_FRED))
                    └─ idt_syscall_init()
                        ├─ wrmsrq(MSR_LSTAR, entry_SYSCALL_64)   // SYSCALL 入口
                        ├─ wrmsrq_cstar(entry_SYSCALL_compat)     // 32位兼容入口
                        └─ wrmsrq_safe(MSR_IA32_SYSENTER_*)       // SYSENTER 支持
```

**系统调用的两种机制**：

| 机制 | 指令 | 是否使用 IDT | 设置时机 | 性能 | 适用 |
|------|------|-------------|---------|------|------|
| **传统** | `INT 0x80` | ✅ 是（IDT[0x80]） | init_IRQ() | 慢 | 32位兼容 |
| **现代** | `SYSCALL`/`SYSENTER` | ❌ 否（MSR） | trap_init() | 快 | 64位主流 |

**关键区别**：
- **INT 0x80**：软件中断，查询 IDT 表第 0x80 个条目，由 init_IRQ() 中的 idt_setup_ia32_syscall_gate() 设置
- **SYSCALL**：专用 CPU 指令，通过 MSR 寄存器（MSR_LSTAR）配置入口地址，**完全绕过 IDT**
- **MSR_LSTAR**：存储 entry_SYSCALL_64 的地址，用户态执行 `syscall` 指令时 CPU 直接跳转到此地址

**流程**：
```
用户态程序
    ↓ syscall 指令
CPU 读取 MSR_LSTAR
    ↓ 跳转
entry_SYSCALL_64（arch/x86/entry/entry_64.S）
    ↓ 保存 pt_regs
do_syscall_64
    ↓ 查表
sys_call_table[nr]（系统调用表）
    ↓ 执行
具体系统调用（如 sys_read）
```

> **详细内容**：完整的 syscall_init() 代码、INT 0x80 vs SYSCALL/SYSENTER 详细对比、MSR 寄存器配置、entry_SYSCALL_64 入口机制、32位兼容机制，请参见 **[系统调用初始化详解](LINUX_KERNEL_SYSCALL_INIT.md)**。


### 3. init_IRQ() 与接管 INT 服务的过程

**"接管 INT 服务"** 指：CPU 发生中断或异常时，按向量号查 **IDT** 跳转到内核注册的处理函数，而不再交给 BIOS/固件（IVT）。完整的 IDT 演进流程参见第三节「IDT 表的演进流程」。本段重点说明 **init_IRQ()** 的作用。

**init_IRQ()：IDT 表的最终完善（异常 + 硬件 IRQ + INT 0x80）**

```
start_kernel() 阶段 2（main.c）
    └─ init_IRQ()（在 trap_init、early_irq_init 之后）  【内核接管 INT（完整）】
        ├─ idt_setup_traps()（linux/arch/x86/kernel/idt.c）
        │   └─ def_idts 等补全/更新 IDT 异常门（对应 IDT 演进阶段 3）
        ├─ init_8259A()（linux/arch/x86/kernel/i8259.c:349）
        │   └─ PIC 重编程：硬件 IRQ 0x08–0x0F/0x70–0x77 → 0x20–0x2F
        │       （主 PIC ICW2=ISA_IRQ_VECTOR(0)，从 PIC ICW2=ISA_IRQ_VECTOR(8)）
        ├─ idt_setup_apic_and_irq_gates()（linux/arch/x86/kernel/idt.c）
        │   ├─ apic_idts 表设置 APIC 相关门，IRQ 向量 → irq_entries_start 等
        │   ├─ 填充所有外部中断和系统中断向量（对应 IDT 演进阶段 4）
        │   ├─ idt_map_in_cea() → 映射 IDT 到 CPU entry area（只读）
        │   ├─ load_idt(&idt_descr)  → 完整 IDT 已加载
        │   ├─ set_memory_ro(&idt_table, 1) → IDT 表设为只读
        │   └─ idt_setup_done = true  → BIOS IVT 被完全取代
        └─ idt_setup_ia32_syscall_gate()（若 CONFIG_IA32_EMULATION）
            └─ IDT[0x80]=entry_INT80_32  → INT 0x80 → do_int80_syscall_32 → ia32_sys_call
```

**IDT 演进回顾**（详见第三节）：
- **阶段 0**：`startup_64_setup_gdt_idt()` 加载 `bringup_idt_table`（临时表，几乎为空）
- **阶段 1**：`idt_setup_early_handler()` 切换到 `idt_table` 并填充早期异常向量（无 IST）
- **阶段 2**：`idt_setup_early_traps()` 补充 DB, BP, PF 等（setup_arch 中）
- **阶段 3**：`idt_setup_traps()` 补全所有异常向量并设置 IST（trap_init 中）← 本函数调用
- **阶段 4**：`idt_setup_apic_and_irq_gates()` 填充 APIC/IRQ 并设为只读（本函数调用）← **IDT 完全就绪**

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

> 运行时中断模型见 [LINUX_INTERRUPT_GUIDE.md](LINUX_INTERRUPT_GUIDE.md)；BIOS IVT 与 Kernel IDT 见 [BIOS_IVT_VS_KERNEL_IDT.md](BIOS_IVT_VS_KERNEL_IDT.md)；8259 PIC 与 APIC 架构对比见 [X86_INTERRUPT_CONTROLLER_EVOLUTION.md](X86_INTERRUPT_CONTROLLER_EVOLUTION.md)。

### 4. VFS 与文件系统初始化

文件系统的初始化贯穿内核启动的多个阶段，从 VFS 基础设施的初始化到 initramfs 的解压，再到真正根文件系统的挂载，是一个复杂的多步骤过程。

#### 文件系统初始化时间线总览

```
start_kernel()
    │
    ├─ 阶段 1-2: 内存、调度器、中断初始化
    │
    ├─ 阶段 3: vfs_caches_init()         ⭐ VFS 基础设施初始化
    │       └─ mnt_init()
    │           ├─ init_rootfs()         ⭐ 注册 rootfs 文件系统类型
    │           └─ init_mount_tree()     ⭐ 挂载第一个 rootfs (空的 tmpfs)
    │
    └─ rest_init()
        └─ kernel_init() (PID 1)
            └─ kernel_init_freeable()
                ├─ do_basic_setup()
                │   └─ do_initcalls()
                │       └─ populate_rootfs()  ⭐ 解压 initramfs 到 rootfs
                │
                ├─ wait_for_initramfs()       ⭐ 等待解压完成
                │
                ├─ prepare_namespace()        ⭐ (可选) 挂载真正的根设备
                │
                └─ run_init_process("/init")  ⭐ 执行用户空间 init
```

#### 阶段 1: VFS 缓存初始化与 rootfs 挂载

**时机**：`start_kernel()` 阶段 3 → `vfs_caches_init()`
**文件**：`fs/dcache.c:3261`

```c
// init/main.c - start_kernel() 阶段 3
void start_kernel(void)
{
    // ...
    console_init();         // 控制台初始化
    vfs_caches_init();      // ⭐ VFS 初始化和 rootfs 挂载
    fork_init();            // 进程创建初始化
    // ...
    rest_init();
}
```

**vfs_caches_init() 完整流程**：

```c
// fs/dcache.c:3261
void __init vfs_caches_init(void)
{
    // 1. 创建路径名缓存（用于存储文件路径）
    names_cachep = kmem_cache_create_usercopy("names_cache", PATH_MAX, 0,
                                              SLAB_HWCACHE_ALIGN|SLAB_PANIC, 0, PATH_MAX, NULL);

    // 2. 初始化 dentry 缓存（目录项缓存）
    dcache_init();

    // 3. 初始化 inode 缓存（索引节点缓存）
    inode_init();

    // 4. 初始化文件表
    files_init();
    files_maxfiles_init();

    // 5. ⭐ 关键：挂载文件系统
    mnt_init();

    // 6. 初始化块设备和字符设备缓存
    bdev_cache_init();
    chrdev_init();
}
```

**mnt_init() - 挂载子系统初始化**：

```c
// fs/namespace.c:6114
void __init mnt_init(void)
{
    int err;

    // 1. 创建挂载缓存（用于存储 mount 结构）
    mnt_cache = kmem_cache_create("mnt_cache", sizeof(struct mount),
                                  0, SLAB_HWCACHE_ALIGN|SLAB_PANIC|SLAB_ACCOUNT, NULL);

    // 2. 分配挂载哈希表（用于快速查找挂载点）
    mount_hashtable = alloc_large_system_hash("Mount-cache",
                                sizeof(struct hlist_head),
                                mhash_entries, 19, HASH_ZERO,
                                &m_hash_shift, &m_hash_mask, 0, 0);

    // 3. 分配挂载点哈希表
    mountpoint_hashtable = alloc_large_system_hash("Mountpoint-cache",
                                sizeof(struct hlist_head),
                                mphash_entries, 19, HASH_ZERO,
                                &mp_hash_shift, &mp_hash_mask, 0, 0);

    if (!mount_hashtable || !mountpoint_hashtable)
        panic("Failed to allocate mount hash table\n");

    // 4. 初始化内核文件系统（用于 sysfs）
    kernfs_init();

    // 5. 初始化 sysfs 文件系统
    err = sysfs_init();
    if (err)
        printk(KERN_WARNING "%s: sysfs_init error: %d\n", __func__, err);

    // 6. 创建 /sys 的 kobject
    fs_kobj = kobject_create_and_add("fs", NULL);
    if (!fs_kobj)
        printk(KERN_WARNING "%s: kobj create error\n", __func__);

    // 7. 初始化 tmpfs/shmem 文件系统
    shmem_init();

    // 8. ⭐ 注册 rootfs 文件系统类型
    init_rootfs();

    // 9. ⭐ 挂载第一个 rootfs 到根目录 /
    init_mount_tree();
}
```

**init_mount_tree() - 创建初始挂载树**：

```c
// fs/namespace.c:6082
static void __init init_mount_tree(void)
{
    struct vfsmount *mnt;
    struct mount *m;
    struct mnt_namespace *ns;
    struct path root;

    // ⭐ 挂载 rootfs 文件系统（类型为 tmpfs/ramfs）
    // rootfs_fs_type 由 init_rootfs() 注册
    mnt = vfs_kern_mount(&rootfs_fs_type, 0, "rootfs", NULL);
    if (IS_ERR(mnt))
        panic("Can't create rootfs");

    // 创建初始挂载命名空间
    ns = alloc_mnt_ns(&init_user_ns, true);
    if (IS_ERR(ns))
        panic("Can't allocate initial namespace");

    ns->seq = atomic64_inc_return(&mnt_ns_seq);
    ns->ns.inum = PROC_MNT_INIT_INO;
    m = real_mount(mnt);
    ns->root = m;
    ns->nr_mounts = 1;
    mnt_add_to_ns(ns, m);

    // ⭐ 设置 init_task (PID 0) 的挂载命名空间
    init_task.nsproxy->mnt_ns = ns;
    get_mnt_ns(ns);

    // ⭐ 设置 init_task 的根目录和当前目录
    root.mnt = mnt;
    root.dentry = mnt->mnt_root;
    mnt->mnt_flags |= MNT_LOCKED;

    set_fs_pwd(current->fs, &root);   // 当前目录 = /
    set_fs_root(current->fs, &root);  // 根目录 = /
}
```

**此阶段完成后的状态**：
- ✅ VFS 子系统完全初始化（dentry cache、inode cache 等）
- ✅ 第一个 rootfs (tmpfs/ramfs) 已挂载到 `/`
- ✅ init_task (PID 0) 的根目录和当前目录都指向这个 rootfs
- ❌ 但此时 rootfs 是**空的**，没有任何文件或目录

#### 阶段 2: initramfs 解压到 rootfs

**时机**：`do_initcalls()` → `populate_rootfs()` (rootfs_initcall)
**文件**：`init/initramfs.c:781`

在 `kernel_init()` 执行 `kernel_init_freeable()` 时，会调用 `do_basic_setup()` → `do_initcalls()`，这会触发所有注册的 initcall 函数，其中就包括 `populate_rootfs()`。

**populate_rootfs() - 调度解压任务**：

```c
// init/initramfs.c:781
static int __init populate_rootfs(void)
{
    // ⭐ 异步调度解压任务到 initramfs_domain
    initramfs_cookie = async_schedule_domain(do_populate_rootfs, NULL,
                                             &initramfs_domain);

    // 启用用户模式助手（usermodehelper）
    usermodehelper_enable();

    // 如果不是异步模式，立即等待解压完成
    if (!initramfs_async)
        wait_for_initramfs();

    return 0;
}
rootfs_initcall(populate_rootfs);  // 通过 initcall 机制注册
```

**do_populate_rootfs() - 实际解压 initramfs**：

```c
// init/initramfs.c:717
static void __init do_populate_rootfs(void *unused, async_cookie_t cookie)
{
    // 1. ⭐ 解压内核内置的 initramfs
    //    __initramfs_start 和 __initramfs_size 是链接器定义的符号
    //    指向编译时打包进内核的 cpio 归档
    char *err = unpack_to_rootfs(__initramfs_start, __initramfs_size);
    if (err)
        panic_show_mem("%s", err); // 内置 initramfs 解压失败是致命错误

    // 2. 如果 bootloader 提供了外部 initrd，也解压到 rootfs
    if (!initrd_start || IS_ENABLED(CONFIG_INITRAMFS_FORCE))
        goto done;

    if (IS_ENABLED(CONFIG_BLK_DEV_RAM))
        printk(KERN_INFO "Trying to unpack rootfs image as initramfs...\n");
    else
        printk(KERN_INFO "Unpacking initramfs...\n");

    // ⭐ 解压外部 initrd（bootloader 传递的）
    err = unpack_to_rootfs((char *)initrd_start, initrd_end - initrd_start);
    if (err) {
#ifdef CONFIG_BLK_DEV_RAM
        // 如果不是 cpio 格式，尝试作为 ramdisk 镜像处理
        populate_initrd_image(err);
#else
        printk(KERN_EMERG "Initramfs unpacking failed: %s\n", err);
#endif
    }

done:
    // 3. 通知安全子系统 initramfs 已填充
    security_initramfs_populated();

    // 4. ⭐ 释放 initrd 占用的内存（如果不需要保留）
    if (!do_retain_initrd && initrd_start && !kexec_free_initrd()) {
        free_initrd_mem(initrd_start, initrd_end);
    } else if (do_retain_initrd && initrd_start) {
        // 如果需要保留，在 sysfs 中创建 /sys/firmware/initrd
        bin_attr_initrd.size = initrd_end - initrd_start;
        bin_attr_initrd.private = (void *)initrd_start;
        if (sysfs_create_bin_file(firmware_kobj, &bin_attr_initrd))
            pr_err("Failed to create initrd sysfs file");
    }

    initrd_start = 0;
    initrd_end = 0;

    init_flush_fput();
}
```

**unpack_to_rootfs() 的工作原理**：
- 解析 cpio 归档格式
- 对每个文件/目录：
  - 创建对应的 inode
  - 写入文件内容
  - 设置权限、所有者等属性
- 支持压缩格式（gzip、bzip2、lzma、xz 等）

**此阶段完成后的状态**：
- ✅ rootfs 中已有文件和目录（来自 initramfs）
- ✅ 通常包含：
  - `/init` - 用户空间初始化程序
  - `/bin`, `/sbin` - 基本命令工具
  - `/lib`, `/lib64` - 必要的共享库
  - `/dev` - 设备节点
  - 驱动模块（`.ko` 文件）

#### 阶段 3: 等待 initramfs 完成

**时机**：`kernel_init_freeable()` → `wait_for_initramfs()`
**文件**：`init/main.c:1588`

```c
// init/main.c:1555
static noinline void __init kernel_init_freeable(void)
{
    // 调度器完全设置好，可以进行阻塞分配
    gfp_allowed_mask = __GFP_BITS_MASK;
    set_mems_allowed(node_states[N_MEMORY]);

    cad_pid = get_pid(task_pid(current));

    // SMP 初始化
    smp_prepare_cpus(setup_max_cpus);
    workqueue_init();
    init_mm_internals();

    do_pre_smp_initcalls();
    lockup_detector_init();

    smp_init();
    sched_init_smp();

    workqueue_init_topology();
    async_init();
    padata_init();
    page_alloc_init_late();

    // 执行各种 initcall（包括 populate_rootfs）
    do_basic_setup();

    kunit_run_all_tests();

    // ⭐ 等待 initramfs 解压完成
    wait_for_initramfs();

    // 在 rootfs 上重新打开控制台
    console_on_rootfs();

    // ⭐ 检查是否有 /init（来自 initramfs）
    if (init_eaccess(ramdisk_execute_command) != 0) {
        // 如果 /init 不存在，说明需要挂载真正的根文件系统
        ramdisk_execute_command = NULL;
        prepare_namespace();  // 挂载 root= 指定的设备
    }

    // ...
}
```

**wait_for_initramfs() 实现**：

```c
// init/initramfs.c:765
void wait_for_initramfs(void)
{
    if (!initramfs_cookie) {
        // 如果在 rootfs_initcall 之前调用，发出警告
        pr_warn_once("wait_for_initramfs() called before rootfs_initcalls\n");
        return;
    }

    // ⭐ 同步等待异步任务完成
    async_synchronize_cookie_domain(initramfs_cookie + 1, &initramfs_domain);
}
```

#### 阶段 4: 挂载真正的根文件系统（可选）

**时机**：`kernel_init_freeable()` → `prepare_namespace()`
**条件**：如果 rootfs 中没有 `/init`

这一步是**可选的**，取决于系统的配置：

**场景 1：使用 initramfs 的 /init**（现代系统常见）
```
rootfs (tmpfs)
    ├─ /init              ← 执行这个
    ├─ /bin
    ├─ /lib
    └─ ...

不需要 prepare_namespace()，直接执行 /init
```

**场景 2：挂载真正的根设备**（传统方式）
```
rootfs (tmpfs) → 被替换为真正的文件系统

prepare_namespace() 执行：
    1. 等待根设备准备好（root_wait()）
    2. 挂载 root= 指定的设备（如 /dev/sda1）
    3. pivot_root 或 mount --move 切换根
    4. 执行 /sbin/init
```

**prepare_namespace() 主要工作**：
1. `wait_for_device_probe()` - 等待设备探测完成
2. `md_run_setup()` - 如果是 RAID，启动 RAID 阵列
3. `mount_root()` - 挂载根设备
4. `devtmpfs_mount()` - 挂载 /dev
5. `init_mount()` - 将新根移动到 /
6. `init_chroot()` - chroot 到新根

#### 文件系统初始化流程图

```
┌─────────────────────────────────────────────────────────────┐
│ start_kernel() 阶段 3                                       │
│                                                             │
│  vfs_caches_init()                                          │
│    ├─ dcache_init()         // dentry 缓存                 │
│    ├─ inode_init()          // inode 缓存                  │
│    └─ mnt_init()                                            │
│        ├─ shmem_init()      // tmpfs 文件系统              │
│        ├─ init_rootfs()     // 注册 rootfs 类型            │
│        └─ init_mount_tree() // ⭐ 挂载空的 rootfs 到 /    │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ rest_init() → kernel_init() → kernel_init_freeable()       │
│                                                             │
│  do_basic_setup()                                           │
│    └─ do_initcalls()                                        │
│        └─ populate_rootfs()                                 │
│            └─ async_schedule_domain(do_populate_rootfs)     │
│                └─ unpack_to_rootfs()  // ⭐ 解压 initramfs│
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  wait_for_initramfs()       // ⭐ 等待解压完成            │
│  console_on_rootfs()        // 在 rootfs 上打开控制台     │
└─────────────────────────────────────────────────────────────┘
                           ↓
                    ┌──────┴──────┐
                    │             │
            有 /init?          无 /init?
                    │             │
                    ↓             ↓
        ┌───────────────┐  ┌─────────────────┐
        │ 直接执行      │  │ prepare_namespace()│
        │ /init         │  │   挂载真正的根   │
        └───────────────┘  └─────────────────┘
```

#### 关键数据结构

**struct mount** - 挂载点信息：
```c
struct mount {
    struct hlist_node mnt_hash;       // 挂载哈希链表节点
    struct mount *mnt_parent;         // 父挂载点
    struct dentry *mnt_mountpoint;    // 挂载点 dentry
    struct vfsmount mnt;              // VFS 挂载信息
    struct mnt_namespace *mnt_ns;     // 所属挂载命名空间
    // ...
};
```

**struct file_system_type** - 文件系统类型：
```c
struct file_system_type {
    const char *name;                 // 文件系统名称（如 "rootfs", "ext4"）
    int fs_flags;                     // 文件系统标志
    struct dentry *(*mount)(...);     // 挂载方法
    void (*kill_sb)(...);             // 卸载方法
    struct module *owner;             // 所属模块
    struct file_system_type *next;    // 链表指针
    // ...
};
```

#### 总结：文件系统加载的关键步骤

| 阶段 | 时机 | 函数 | 作用 | 文件 |
|------|------|------|------|------|
| **1** | start_kernel() 阶段 3 | `vfs_caches_init()` | VFS 初始化 | fs/dcache.c:3261 |
| **1.1** | vfs_caches_init() | `mnt_init()` | 挂载子系统初始化 | fs/namespace.c:6114 |
| **1.2** | mnt_init() | `init_rootfs()` | 注册 rootfs 类型 | init/do_mounts.c |
| **1.3** | mnt_init() | `init_mount_tree()` | 挂载空 rootfs 到 / | fs/namespace.c:6082 |
| **2** | do_initcalls() | `populate_rootfs()` | 调度解压任务 | init/initramfs.c:781 |
| **2.1** | populate_rootfs() | `do_populate_rootfs()` | 解压 initramfs 到 rootfs | init/initramfs.c:717 |
| **3** | kernel_init_freeable() | `wait_for_initramfs()` | 等待解压完成 | init/initramfs.c:765 |
| **4** | kernel_init_freeable() | `prepare_namespace()` | (可选) 挂载真正的根 | init/do_mounts.c |

**关键点**：
1. ⭐ **VFS 初始化**发生在 `start_kernel()` 阶段 3 的 `vfs_caches_init()` 中
2. ⭐ **第一个 rootfs** 在 `mnt_init()` → `init_mount_tree()` 中挂载（空的 tmpfs）
3. ⭐ **initramfs 解压**通过 initcall 机制异步执行，在 `kernel_init()` 中完成
4. ⭐ **等待完成**在 `wait_for_initramfs()` 中同步
5. ⭐ **真正的根文件系统**（如果需要）在 `prepare_namespace()` 中挂载

### 5. rest_init() 与 kernel_init()

**从 start_kernel 到 rest_init / kernel_init 的调用链**：

```
start_kernel()（main.c:898）
    ├─ 阶段 1: setup_arch(), parse_early_param() 等
    ├─ 阶段 2: mm_core_init(), sched_init(), trap_init(), init_IRQ(), local_irq_enable() 等
    ├─ 阶段 3: console_init(), vfs_caches_init(), fork_init() 等
    └─ rest_init()  【创建 PID 1/2、PID 0 进入 idle】
            ├─ user_mode_thread(kernel_init, NULL, CLONE_FS)
            │       → 创建内核线程，入口函数 kernel_init，即 PID 1（init）；该线程稍后执行 kernel_init()
            ├─ kernel_thread(kthreadd, NULL, NULL, CLONE_FS | CLONE_FILES)
            │       → 创建内核线程，入口函数 kthreadd，即 PID 2；该线程稍后执行 kthreadd()
            ├─ complete(&kthreadd_done)   // 通知 PID 1：kthreadd 已就绪
            └─ cpu_startup_entry(CPUHP_ONLINE)
                    → 当前进程（PID 0: swapper）进入 idle 循环，不返回
```

执行顺序：rest_init() 先创建 PID 1 和 PID 2 两个线程（此时它们已可被调度，但 rest_init 仍在 PID 0 上运行），complete 后 PID 0 调用 cpu_startup_entry 进入 idle；PID 1 的 kernel_init() 会在 wait_for_completion(&kthreadd_done) 处等到 kthreadd 就绪后再继续。

**rest_init()**：

```c
static noinline void __ref __noreturn rest_init(void)
{
	pid = user_mode_thread(kernel_init, NULL, CLONE_FS);   // PID 1
	pid = kernel_thread(kthreadd, NULL, NULL, CLONE_FS | CLONE_FILES);  // PID 2
	complete(&kthreadd_done);
	cpu_startup_entry(CPUHP_ONLINE);   // 当前进程（PID 0）进入 idle 循环
}
```

**kernel_init()**：由 rest_init() 通过 user_mode_thread 创建，作为 **PID 1** 的入口函数；执行完 kernel_init_freeable、free_initmem 后，通过 run_init_process / try_to_run_init_process 执行用户空间 init（/init 或 /sbin/init）。

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

调用链见第五节「rest_init() 与 kernel_init()」开头的树形图。

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

---

## 常见问题

### Q: Linux 是否只提供 INT 0x80 软件中断服务？

**A: 不是。** Linux 提供了多个用户态可触发的软件中断向量：

#### 用户态可触发的异常/中断（DPL=3）

| 向量 | 名称 | CPU 分类 | 用途 | 现代使用情况 |
|------|------|---------|------|------------|
| **0x80** | INT 0x80 | 软件中断 | 32位系统调用 | 32位兼容，64位很少用 |
| **3** | #BP | **异常** | 断点调试 | ✅ 调试器（gdb）使用 |
| **4** | #OF | **异常** | 溢出检测 | ❌ 64位已废弃（INTO 指令） |

**重要区分**：
- **#BP (INT 3)**：虽然可通过 `int 3` 指令触发，但 CPU 将其归类为**异常**（Breakpoint Exception）
- **INT 0x80**：通过 `int $0x80` 指令触发，用于系统调用，习惯上称为"软件中断"
- **共同点**：都是同步的（由当前指令触发）、不受 EFLAGS.IF 控制（不可屏蔽）

**源码证据**（`arch/x86/kernel/idt.c`）：

```c
// SYSG = System Gate (DPL=3，用户态可触发)
static const __initconst struct idt_data early_idts[] = {
    SYSG(X86_TRAP_BP,  asm_exc_int3),      // INT 3：断点
    SYSG(X86_TRAP_OF,  asm_exc_overflow),  // INTO：溢出（32位）
};

static const struct idt_data ia32_idt[] __initconst = {
    SYSG(IA32_SYSCALL_VECTOR,  asm_int80_emulation),  // 0x80：系统调用
};
```

#### 其他向量

- **异常向量（0-31）**：DPL=0，用户态不能主动触发（如 #PF、#GP、#UD）
- **硬件中断（32-255）**：DPL=0，外部硬件触发（如 IRQ 0、IRQ 1）
- **APIC 中断**：DPL=0，CPU 间通信、时钟等

---

### Q: 硬件中断、软件中断、异常有什么本质区别？

**A: 参见 [X86_INTERRUPT_EXCEPTION_TRAP.md - x86 中断、异常、陷阱：Intel SDM 规范与 Linux 实现](X86_INTERRUPT_EXCEPTION_TRAP.md)。**

该文档详细说明了：
- Intel SDM 官方定义（Interrupt vs Exception）
- 三者的完整对比表（触发方式、是否受 IF 控制、CPU 分类、优先级等）
- Exception 的三种类型（Fault/Trap/Abort）及其区别
- 中断/异常优先级（为什么异常优先于硬件中断）
- IDT 门描述符类型（Interrupt Gate vs Trap Gate）
- Linux 内核源码实现（异常向量、Event Type、IDT 初始化）
- 常见误解澄清（为什么软件中断在 CPU 层面实际上是异常）

**简短答案**：
- **核心区别**：触发方式（同步/异步）+ 是否受 EFLAGS.IF 控制
- **硬件中断（IRQ）**：异步 + 受 IF 控制（IF=0 时被屏蔽）
- **软件中断/异常**：同步 + 不受 IF 控制（IF=0 时仍会触发）
- **关键洞察**：Software Interrupt 在 Intel SDM 中归类为 Exception，不是 Interrupt

这个区别在内核早期启动阶段非常重要：内核在 `cli`（IF=0）后仍然可以处理异常（如 #PF、#VC），但不会响应硬件中断（IRQ）。

---

### Q: 现代系统调用使用 SYSCALL 还是 SYSENTER？

**A: 取决于架构和兼容性需求。**

| 机制 | 架构 | 性能 | 实现方式 | 主要用途 |
|------|------|------|---------|---------|
| **SYSCALL** | AMD64/Intel 64位 | 快（~60-80 周期） | MSR（MSR_LSTAR） | **64位主流** |
| **SYSENTER** | Intel 32位 | 快（~60-80 周期） | MSR（MSR_IA32_SYSENTER_EIP） | 32位快速系统调用 |
| **INT 0x80** | x86（32/64位通用） | 慢（~100-200 周期） | IDT[0x80] | 32位兼容 |

**SYSCALL vs SYSENTER 的关键区别**：

1. **CPU 支持**：
   - SYSCALL：AMD 在 K6/Athlon 时代引入，Intel 在 x86-64 才支持
   - SYSENTER：Intel 在 Pentium II 时代引入，AMD 也支持

2. **架构差异**：
   - SYSCALL：主要用于 **64 位模式**（Long Mode）
   - SYSENTER：主要用于 **32 位保护模式**

3. **Linux 内核的使用策略**：
   ```c
   // arch/x86/kernel/cpu/common.c:2234
   void syscall_init(void) {
       // 64位 SYSCALL 入口
       wrmsrq(MSR_LSTAR, (unsigned long)entry_SYSCALL_64);

       // 32位兼容模式
       if (ia32_enabled()) {
           wrmsrq_cstar((unsigned long)entry_SYSCALL_compat);
           // 32位 SYSENTER 入口
           wrmsrq_safe(MSR_IA32_SYSENTER_EIP, (u64)entry_SYSENTER_compat);
       }
   }
   ```

4. **实际使用情况**：
   - **64 位程序**：使用 `syscall` 指令 → entry_SYSCALL_64
   - **32 位程序（Intel CPU）**：使用 `sysenter` 指令 → entry_SYSENTER_compat
   - **32 位程序（兼容路径）**：使用 `int $0x80` → entry_INT80_32

> **详细对比**：完整的 SYSCALL/SYSENTER/INT 0x80 对比、MSR 配置、性能分析，请参见 [系统调用初始化详解](LINUX_KERNEL_SYSCALL_INIT.md)。

---

## 相关文档

### 启动流程

- **[BOOT_FLOW.md](BOOT_FLOW.md)** - 启动概述
- **[GRUB_KERNEL_LOADING.md](GRUB_KERNEL_LOADING.md)** - GRUB 加载内核详解
- **[GRUB_UEFI_LONG_MODE_ANALYSIS.md](GRUB_UEFI_LONG_MODE_ANALYSIS.md)** - GRUB UEFI 长模式启动分析
- **[UEFI_VS_BIOS_BOOT.md](UEFI_VS_BIOS_BOOT.md)** - UEFI 与 BIOS 引导机制差异
- **[LINUX_KERNEL_SETUP_FLOW.md](LINUX_KERNEL_SETUP_FLOW.md)** - 从扇区 0 启动的 Setup 流程

### 内存管理

**理论基础**：
- **[WHY_VIRTUAL_MEMORY.md](WHY_VIRTUAL_MEMORY.md)** - 为什么需要虚拟内存 - 从物理地址的缺陷到分页的必然性、碎片化问题的数学分析、工作集理论与局部性原理、性能代价分析、历史案例对比

**内核空间内存管理**：
- **[LINUX_MEMORY_MANAGEMENT_EVOLUTION.md](LINUX_MEMORY_MANAGEMENT_EVOLUTION.md)** - Linux 内核分页机制完整指南 - 理论基础、Phase 1 早期页表、Phase 2 完整页表（E820/memblock/zone）
- **[E820_MEMORY_MAP.md](E820_MEMORY_MAP.md)** - E820 内存映射表详解 - E820 数据结构、内核接收流程、与分页机制的分阶段依赖关系（为何早期不需要 E820、后期必须依赖 E820）、驱动页表初始化的详细代码分析
- **[X86_MEMORY_MANAGEMENT_THEORY.md](X86_MEMORY_MANAGEMENT_THEORY.md)** - GDT 详解：从保护模式到长模式 - GDT 演化（4阶段）、段描述符详解、与分页的协作、GDT Identity Mapping 机制
- **[LINUX_MEMORY_MANAGEMENT_CODE_GUIDE.md](LINUX_MEMORY_MANAGEMENT_CODE_GUIDE.md)** - x86-64 多级页表设计详解 - 页表建立过程、硬件要求、多级设计原理、MMU 遍历伪代码、实战计算示例

**物理内存分配**：
- **[BUDDY_ALLOCATOR_GUIDE.md](BUDDY_ALLOCATOR_GUIDE.md)** - 伙伴系统与 Slab 分配器详解 - 伙伴系统原理与实现、Slab/SLUB 分配器、从 memblock 到 buddy 的转换
- **[SLAB_ALLOCATOR_EXPLAINED.md](SLAB_ALLOCATOR_EXPLAINED.md)** - Slab 分配器专题深入 - 三层架构详解、性能优化、SLUB/SLUB_TINY、安全加固特性、实战使用与调试

**运行时内存管理**：
- **[LINUX_PAGE_FAULT_DEMAND_PAGING.md](LINUX_PAGE_FAULT_DEMAND_PAGING.md)** - 缺页异常与按需分配 - Page Fault 完整流程、TLB/MMU 工作机制、错误码分析、内核处理路径
- **[LINUX_USERSPACE_MEMORY_GUIDE.md](LINUX_USERSPACE_MEMORY_GUIDE.md)** - 用户空间内存模型 - 虚拟地址空间布局、VMA 管理、brk/mmap 系统调用、FS/GS 寄存器、地址转换完整流程

**补充技术细节**（可选深入阅读）：
- **[SEABIOS_E820_CONSTRUCTION.md](SEABIOS_E820_CONSTRUCTION.md)** - SeaBIOS E820 构建流程 - POST 阶段、CPU 模式切换、E820 表构建机制、内存探测策略、QEMU fw_cfg 接口
- **[BOOTLOADER_MEMORY_PASSING.md](BOOTLOADER_MEMORY_PASSING.md)** - Bootloader 内存信息传递 - GRUB 读取 E820 表、UEFI GetMemoryMap()、EFI 内存类型映射、boot_params 统一接口
- **[BIOS_MEMORY_LAYOUT.md](BIOS_MEMORY_LAYOUT.md)** - BIOS 内存布局与地址映射 - BIOS ROM 映射机制、实模式地址空间、保护模式访问、特殊内存区域
- **[BIOS_MEMORY_MAPPING.md](BIOS_MEMORY_MAPPING.md)** - BIOS 文件映射到物理内存的证据分析 - SeaBIOS 源码验证、qemu.log 分析、内存映射关系
- **[BIOS_MEMORY_QA.md](BIOS_MEMORY_QA.md)** - BIOS 内存相关问答 - Bootloader 运行模式、加载位置、模式切换时机

### 架构细节

- **[X86_NEAR_VS_LONG_JUMP.md](X86_NEAR_VS_LONG_JUMP.md)** - near/long jump 与 long mode 下 CS 的作用
- **[X86_POSITION_INDEPENDENT_CODE.md](X86_POSITION_INDEPENDENT_CODE.md)** - 位置无关代码（`__pi_` 前缀）实现机制

### 中断与系统调用

- **[X86_INTERRUPT_EXCEPTION_TRAP.md](X86_INTERRUPT_EXCEPTION_TRAP.md)** - x86 中断、异常、陷阱：Intel SDM 规范与 Linux 实现（基础概念、三者区别、Exception 分类、优先级、IDT 门类型）
- **[LINUX_KERNEL_IDT_EVOLUTION.md](LINUX_KERNEL_IDT_EVOLUTION.md)** - IDT 表的演进流程详解 - 两个 IDT 表（bringup_idt_table、idt_table）、5 个演进阶段、GDT/IDT 对比、IST 机制、中断状态管理
- **[LINUX_KERNEL_SYSCALL_INIT.md](LINUX_KERNEL_SYSCALL_INIT.md)** - 系统调用初始化详解（trap_init、syscall_init、INT 0x80 vs SYSCALL/SYSENTER 对比、MSR 配置）
- **[LINUX_INTERRUPT_GUIDE.md](LINUX_INTERRUPT_GUIDE.md)** - Linux 中断处理机制（Top Half/Bottom Half、softirq/tasklet/workqueue）
- **[X86_INTERRUPT_CONTROLLER_EVOLUTION.md](X86_INTERRUPT_CONTROLLER_EVOLUTION.md)** - x86 中断控制器演进（8259 PIC vs APIC）
- **[BIOS_IVT_VS_KERNEL_IDT.md](BIOS_IVT_VS_KERNEL_IDT.md)** - BIOS IVT 与 Kernel IDT 对比

### 重定位与解压专题

- **[COMPRESSED_KERNEL_RELOCATION.md](COMPRESSED_KERNEL_RELOCATION.md)** - 压缩内核重定位与原地解压详解
- **[SOLUTION_ICACHE_MYSTERY.md](SOLUTION_ICACHE_MYSTERY.md)** - 解压代码为何不被覆盖的完整解答
- **[WHY_RELOCATE_COMPRESSED_KERNEL.md](WHY_RELOCATE_COMPRESSED_KERNEL.md)** - 为什么要重定位压缩内核（KASLR 分析）
- **[INVESTIGATION_SUMMARY.md](INVESTIGATION_SUMMARY.md)** - I-cache 理论验证与调查报告

### 其他相关文档

- **[VMLINUZ_STRUCTURE.md](VMLINUZ_STRUCTURE.md)** - vmlinuz 文件结构分析
- **[INITRAMFS_ANALYSIS.md](INITRAMFS_ANALYSIS.md)** - initramfs 分析
