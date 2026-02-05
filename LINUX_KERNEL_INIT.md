# Linux 内核启动与初始化（64 位，不走 Setup）

本文档按**实际执行顺序**描述从 GRUB（或 UEFI）进入压缩内核到 `start_kernel()` 及之后的完整流程：**不走 Setup**（GRUB 按 code32_start 跳转、UEFI 按 PE 入口跳转，直接进入压缩内核）。**从扇区 0 启动时的 Setup 流程**见 [LINUX_KERNEL_SETUP_FLOW.md](LINUX_KERNEL_SETUP_FLOW.md)。

> **相关文档**：
> - 启动流程：[BOOT_FLOW.md](BOOT_FLOW.md) 启动概述；[GRUB_KERNEL_LOADING.md](GRUB_KERNEL_LOADING.md) GRUB 加载内核；[GRUB_UEFI_LONG_MODE_ANALYSIS.md](GRUB_UEFI_LONG_MODE_ANALYSIS.md) GRUB UEFI 长模式启动分析
> - UEFI vs BIOS：[UEFI_VS_BIOS_BOOT.md](UEFI_VS_BIOS_BOOT.md) UEFI 与 BIOS 引导机制差异
> - Setup 流程：[LINUX_KERNEL_SETUP_FLOW.md](LINUX_KERNEL_SETUP_FLOW.md) 从扇区 0 启动的 Setup
> - 内存管理：[LINUX_KERNEL_SETUP_ARCH_MEMORY.md](LINUX_KERNEL_SETUP_ARCH_MEMORY.md) setup_arch 内存接管详解；[MMU_AND_PAGING.md](MMU_AND_PAGING.md) x86 MMU、分页与内核页表管理
> - 架构细节：[X86_NEAR_VS_LONG_JUMP.md](X86_NEAR_VS_LONG_JUMP.md) near/long jump 与 long mode 下 CS 的作用
> - **原地解压专题**：[SOLUTION_ICACHE_MYSTERY.md](SOLUTION_ICACHE_MYSTERY.md) 解压代码为何不被覆盖的完整解答；[WHY_RELOCATE_COMPRESSED_KERNEL.md](WHY_RELOCATE_COMPRESSED_KERNEL.md) 为什么要重定位压缩内核（KASLR 分析）；[INVESTIGATION_SUMMARY.md](INVESTIGATION_SUMMARY.md) I-cache 理论验证与调查报告
>
> **执行顺序（BIOS/GRUB 路径）**：GRUB/入口 → 【阶段1】压缩内核 startup_32（32位模式切换）→ 【阶段2】压缩内核 startup_64（重定位拷贝、解压）→ 【阶段3】主内核 startup_64 → x86_64_start_kernel（早期 IDT）→ start_kernel() → setup_arch → trap_init/syscall → init_IRQ → rest_init → 核心进程。
>
> **执行顺序（UEFI 路径）**：UEFI 固件 → efi_pe_entry → efi_stub_entry → efi_decompress_kernel（解压）→ enter_kernel → 【阶段3】主内核 startup_64（直接跳到这里，跳过阶段1和2）→ 后续与 BIOS 路径相同。详细的 UEFI 启动流程、代码分析和与 BIOS 路径的对比，请参阅 **[UEFI_VS_BIOS_BOOT.md](UEFI_VS_BIOS_BOOT.md)**。

### 完整流程图（按执行顺序）

**重要说明**：以下流程图描述的是 **BIOS/GRUB 启动路径**。**UEFI 启动路径完全不同**，不经过 compressed/head_64.S 的 startup_32/startup_64，而是直接通过 EFI stub（efi_pe_entry → efi_stub_entry → efi_decompress_kernel）解压并跳转到主内核。详见本文档的"BIOS vs UEFI 两条完全不同的启动路径"章节。

**关键地址说明**（BIOS/GRUB 路径）：
- **1MB (0x100000)**：GRUB 加载压缩内核的位置，startup_32/startup_64 最初在这里执行
- **16MB (0x1000000)**：解压后内核的目标位置（CONFIG_PHYSICAL_START 配置，或 KASLR 随机地址）
- **16MB+ (约 38MB)**：重定位后的压缩内核位置（%rbx），从这里解压内核到 16MB（详见 [WHY_RELOCATE_COMPRESSED_KERNEL.md](WHY_RELOCATE_COMPRESSED_KERNEL.md)）

```
GRUB grub_relocator32_boot()（grub/grub-core/lib/i386/relocator.c）
    │   将压缩内核加载到 0x100000 (1MB)
    │   EIP = boot_params.hdr.code32_start (0x100000)，ESI = boot_params
    ↓
【阶段1】压缩内核 startup_32（在 1MB 处执行，linux/arch/x86/boot/compressed/head_64.S:82-274，32位保护模式）
    ├─ GDT/栈/段设置（106-125行）
    ├─ verify_cpu（132-135行）
    ├─ CR4.PAE、身份映射页表（内联，200-231行）、CR3、EFER.LME、CR0.PG（167-270行）
    └─ lret → 【阶段2】压缩内核 startup_64（273行，同文件278行，仍在压缩内核代码中）
        ↓
【阶段2】压缩内核 startup_64（linux/arch/x86/boot/compressed/head_64.S:278-476，64位长模式）
    ├─ 【仍在 1MB 处执行】设置64位环境：段寄存器、栈、GDT（290-360行）
    ├─ 【仍在 1MB 处执行】load_stage1_idt、sev_enable、configure_5level_paging（376-409行）
    ├─ 【重定位拷贝】rep movsq 将压缩内核从 1MB 拷贝到 %rbx（通常 38MB，详见 [WHY_RELOCATE_COMPRESSED_KERNEL.md](WHY_RELOCATE_COMPRESSED_KERNEL.md)）（419-425行）
    ├─ 重新加载 GDT、jmp .Lrelocated（432-441行，跳到 %rbx 处的重定位后代码）
    ├─ 【现在在 %rbx 处执行】清除 BSS（450-455行）
    ├─ 【在 %rbx 处执行】load_stage2_idt、initialize_identity_maps（457-461行）
    ├─ 【在 %rbx 处执行，解压到 16MB】extract_kernel() 解压到 %rbp（0x1000000，即 16MB）（469行）
    └─ jmp *%rax → 【阶段3】主内核 startup_64（跳到 16MB 处的解压后内核）（475行）
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

**从 GRUB 启动时**：GRUB 不执行 bzImage 内的 Setup，按 boot_params 中 **code32_start** 所存地址跳转到**压缩内核**入口（startup_32，32 位保护模式）。**关键**：模式切换在压缩内核的 startup_32 中完成，解压在压缩内核的 startup_64 中完成（详见下文三个阶段）。vmlinuz 含 Setup（未压缩）与压缩内核（gzip）；GRUB 通过 relocator 机制将镜像复制到 0x100000、自填 boot_params、**按 code32_start 跳转**，不解压、不执行 Setup。GRUB 加载机制详见 [GRUB_KERNEL_LOADING.md](GRUB_KERNEL_LOADING.md)（GRUB 先读取到临时缓冲区，boot 时 relocator 复制到目标地址并跳转）。

**入口点**：BIOS/Legacy（如 GRUB）→ code32_start 处即 **startup_32**（x86_64：`arch/x86/boot/compressed/head_64.S:82`，`SYM_FUNC_START(startup_32)`）。UEFI → PE 的 AddressOfEntryPoint 跳转到 EFI stub（`efi_pe_entry` 等）。64 位内核用 `head_64.S`（压缩与主内核各一份，路径不同）；32 位用 `head_32.S`。

```
grub_relocator32_boot() → EIP = code32_start
    ↓
【阶段1】压缩内核 startup_32（32 位保护模式，arch/x86/boot/compressed/head_64.S:82）
```

---

## 二、压缩内核的三个阶段（源代码位置：arch/x86/boot/compressed/head_64.S）

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
| 算 %ebx | 非 RELOCATABLE：%ebx = LOAD_PHYSICAL_ADDR；RELOCATABLE：%ebx 按 BP_kernel_alignment 对齐；再 %ebx += BP_init_size − rva(_end) | **%ebx = 重定位目标地址**（通常在 16MB 以上，例如约 22MB），解压前要把压缩内核拷到这里；同时 pgtable 将建在 rva(pgtable)(%ebx)，以便拷到 %ebx 后 CR3 仍有效 |
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
| **%ebx** | **重定位目标**（解压前拷贝目标；通常约 38MB，参见 [WHY_RELOCATE_COMPRESSED_KERNEL.md](WHY_RELOCATE_COMPRESSED_KERNEL.md)） | 计算公式：%ebx = %rbp + BP_init_size − rva(_end)；页表建在 rva(pgtable)(%ebx)，以便拷贝到 %ebx 后 CR3 仍指向有效页表；后续 64 位 startup_64 里 rep movsq 目标也是 %rbx |
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
    ├─ 【重定位拷贝】将压缩内核（startup_32～_bss）整段拷贝到 %rbx 处（通常 16MB 以上的安全位置）（419-425行）
    ├─ 重新加载 GDT（432-435行）
    └─ jmp .Lrelocated（440-441行）→ 跳转到同文件内重定位后的 .Lrelocated 标签
        ↓
.Lrelocated（arch/x86/boot/compressed/head_64.S:445-476，仍在同一文件内）
    ├─ 清除 BSS（450-455行）
    ├─ load_stage2_idt（457行）
    ├─ initialize_identity_maps（461行）
    ├─ 【解压内核】call extract_kernel()（469行）← 关键：在这里解压内核！
    │       ├─ choose_random_location()（可选 KASLR）更新 output 物理地址
    │       ├─ decompress_kernel() 解压到 output（通常 0x1000000，即 16MB）
    │       ├─ 解析解压后 ELF，handle_relocations()
    │       └─ 返回主内核入口地址到 %rax
    └─ jmp *%rax（475行）→ 【阶段3】跳转到主内核 startup_64（arch/x86/kernel/head_64.S）
```

**重定位拷贝的详细说明**：

**压缩内核的位置变化（时间线）**：

```
T1: GRUB 加载阶段
    ├─ GRUB 将压缩内核（bzImage）加载到临时缓冲区（prot_mode_mem，通常在 16MB+）
    ├─ relocator 将其从临时缓冲区复制到 0x100000 (1MB)（prot_mode_target）
    └─ 跳转到 code32_start（0x100000，即 startup_32）
    └─ 说明：GRUB 使用 relocator 机制（grub_relocator32_boot）两步完成：
       先读取到 GRUB 可访问的临时缓冲区，boot 时再复制到目标地址并跳转

T2: startup_32/startup_64 执行阶段（在 1MB 处执行）
    └─ 压缩内核仍在 1MB (0x100000) 处
    └─ 计算重定位目标地址 %rbx（通常 16MB 以上，约 22MB）

T3: 重定位拷贝阶段（rep movsq，419-425行）
    └─ 将压缩内核从 1MB 拷贝到 %rbx（通常 38MB，为什么？见 [WHY_RELOCATE_COMPRESSED_KERNEL.md](WHY_RELOCATE_COMPRESSED_KERNEL.md)）
    └─ 跳转到新位置（%rbx 处）继续执行

T4: 解压阶段（在 %rbx 处执行）
    └─ 从 %rbx 处调用 extract_kernel()
    └─ 解压内核到 16MB (0x1000000)
    └─ 跳转到解压后的主内核
```

**为何需要重定位拷贝？**

**重要前提**：此重定位拷贝机制**仅适用于 BIOS/GRUB 启动路径**，UEFI 启动路径**完全不经过此流程**（详见下节"BIOS vs UEFI 两条不同的启动路径"）。

**BIOS/GRUB 路径的重定位原因**：
- **初始执行位置**：压缩内核开始执行时在 **1MB (0x100000)**（GRUB relocator 复制后的位置）
  - 注：GRUB 实际先加载到临时缓冲区（prot_mode_mem，通常 16MB+），boot 时 relocator 复制到 1MB
- **解压目标**：需要解压到 **16MB (0x1000000)**（CONFIG_PHYSICAL_ADDR 配置，可能因 KASLR 而不同）
- **为什么看起来 1MB 和 16MB 不重叠仍需重定位**：
  1. **栈和数据结构**：解压器代码在 1MB 处执行时，其栈、全局变量、临时数据都在附近
  2. **解压器代码自身**：`extract_kernel()` 函数本身在 1MB 处，解压到 16MB 时可能覆盖执行路径
  3. **CONFIG_RELOCATABLE + KASLR**：解压目标不总是 16MB，可能是任意对齐地址（见下节）
  4. **通用性设计**：重定位机制支持所有场景（固定地址、KASLR、kexec 等）
- **解决方案**：先将整个压缩内核（包括解压器代码和压缩数据）从 1MB 拷贝到安全位置（%rbx，通常在 16MB 以上，例如约 22MB），然后从那里执行解压操作

**地址计算**：
- **解压目标 %rbp**：解压后内核的最终位置（LOAD_PHYSICAL_ADDR，通常 0x1000000，即 16MB）
  - 来源：`arch/x86/boot/compressed/head_64.S:325` 设置 `%rbp = LOAD_PHYSICAL_ADDR`
  - `LOAD_PHYSICAL_ADDR` 由 `CONFIG_PHYSICAL_START` 配置（默认 0x1000000）
- **重定位目标 %rbx**：压缩内核的安全位置（计算公式见源代码328-331行）
  ```asm
  movl    BP_init_size(%rsi), %ebx     # BP_init_size：内核初始化需要的总大小
  subl    $ rva(_end), %ebx             # 减去压缩内核代码段的大小
  addq    %rbp, %rbx                    # 加上解压目标地址（16MB）
  # 结果：%rbx = 0x1000000 + BP_init_size - rva(_end)
  ```
  - **具体数值**：通常在 **16MB 以上**（例如：16MB + 8MB - 2MB = 22MB 左右）
  - **为何这样计算**：将压缩内核放在解压目标地址之后的安全位置，确保解压时不会覆盖正在执行的代码
  - **BP_init_size**：来自 boot_params，表示内核镜像初始化需要的总内存大小（包括解压后的内核 + BSS + brk）
  - **rva(_end)**：压缩内核代码段的结束位置（相对地址）

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

**拷贝到哪里？** %rbx 指向的地址，通常是 **16MB 以上**（具体位置：16MB + BP_init_size - 压缩内核大小，例如约 22MB 左右）。这个位置确保：
- 解压到 16MB 时不会覆盖正在执行的重定位后的代码
- 有足够的空间容纳整个压缩内核（几 MB）

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

**重要说明："新地址"指的是什么？**

这里的 `jmp *%rax` **不是跳转到主内核**，而是跳转到**同一个文件内**（`arch/x86/boot/compressed/head_64.S`）的 `.Lrelocated` 标签（第445行）。

**跳转目标**：`.Lrelocated`（`arch/x86/boot/compressed/head_64.S:445`）
```asm
440:    leaq    rva(.Lrelocated)(%rbx), %rax
441:    jmp    *%rax              ← 跳转到下面的 .Lrelocated
442: SYM_CODE_END(startup_64)
443:
444:    .text
445: SYM_FUNC_START_LOCAL_NOALIGN(.Lrelocated)  ← 跳转目标在这里！
446:    /* Clear BSS */
       ...
469:    call    extract_kernel      ← 在这里解压内核
       ...
475:    jmp    *%rax               ← 这里才跳转到主内核！
476: SYM_FUNC_END(.Lrelocated)
```

**为什么需要这次跳转？**
- 前面的 `rep movsq`（419-425行）已将整个压缩内核拷贝到 %rbx 处（新内存位置）
- 但当前指令仍在**旧位置**执行
- 必须跳转到**新位置的 .Lrelocated** 继续执行
- 这样后续 `call extract_kernel()` 解压到 0x100000 时，不会覆盖正在执行的代码

**"新地址"的含义**：
- **不是**指主内核（`arch/x86/kernel/head_64.S`）
- **而是**指重定位后的新内存位置（%rbx 处的 `.Lrelocated`）
- 只有在 `.Lrelocated` 内执行完 `extract_kernel()` 后的 `jmp *%rax`（第475行）才真正跳转到【阶段3】主内核

**extract_kernel() 函数**（`arch/x86/boot/compressed/misc.c:405`）：

在 **重定位拷贝完成后**被调用，完成以下工作：
1. 根据 bzImage 布局找到压缩负载（input_data/input_len）
2. choose_random_location()（可选 KASLR）确定解压目标地址
3. decompress_kernel() 解压到 output（%rbp 指定，通常 0x1000000，即 16MB）
4. 解析解压后的 ELF 格式
5. handle_relocations() 处理重定位
6. 返回主内核入口地址（通过 %rax）

**与主内核的衔接**：extract_kernel() 返回后，`.Lrelocated` 中执行 `jmp *%rax`（第475行），跳转到**主内核**的 `startup_64`（`arch/x86/kernel/head_64.S:38`），此时 %rsi（即 %r15）仍保存着 boot_params 指针。

### 原地解压（In-Place Decompression）的精妙设计

> **📖 完整解答**：本节简要说明原地解压的设计，详细分析请参阅：
> - [SOLUTION_ICACHE_MYSTERY.md](SOLUTION_ICACHE_MYSTERY.md) - extract_kernel 代码为何不被覆盖的完整答案
> - [WHY_RELOCATE_COMPRESSED_KERNEL.md](WHY_RELOCATE_COMPRESSED_KERNEL.md) - 为什么要重定位压缩内核（KASLR 分析）
> - [INVESTIGATION_SUMMARY.md](INVESTIGATION_SUMMARY.md) - I-cache 理论验证与完整调查过程

#### 问题的提出

在前面的分析中，我们知道：
- 解压目标：从 16MB（%rbp）开始，向上扩展
- 压缩内核位置：重定位到 %rbx (通常 38MB ~ 48MB，由 init_size 决定)
- 解压后内核大小：通常 20MB ~ 30MB

**关键问题**：extract_kernel() 代码在解压过程中会被覆盖吗？

#### vmlinuz 文件结构（重要发现）

通过分析实际的 vmlinuz 文件（Linux 6.6.110），发现其结构与之前的理解不同：

```
vmlinuz 文件布局：

[Boot + Setup]  [.head.text]  [Payload (gzip vmlinux)]  [.text + .rodata + .data]
   16 KB          0.69 KB            9.85 MB                    55.25 KB

   0x0-0x4000    0x4000-0x42c4    0x42c4-0x9de704          0x9de704-0x9ec400
                                ↑                          ↑
                          压缩的 vmlinux              extract_kernel 等函数
```

**关键发现**：
1. **Payload** (0x42c4-0x9de704): 压缩的 vmlinux（ELF 格式），9.85 MB
2. **.text 段** (0x9de704-0x9ec400): extract_kernel、decompress_kernel 等函数，55.25 KB
3. **Payload 是压缩后的解压目标（VO）**，不包含解压程序本身

#### 运行时内存布局（基于 Linux 6.6.110）

**关键参数**：
```
init_size = 0x20de000 (32.87 MB)  // BP_init_size
ZO 总大小  = 0x9e8400 (9.91 MB)    // vmlinuz 中的压缩内核总大小
Payload  = 0x9da440 (9.85 MB)    // 其中的压缩 vmlinux
.text段   = 55.25 KB              // extract_kernel 等函数
```

**内存布局计算**：
```
%rbp = 0x1000000 (16 MB)           // 解压目标起始
%rbx = %rbp + init_size - ZO_size
     = 0x1000000 + 0x20de000 - 0x9e8400
     = 0x26f5c00 (38.96 MB)        // ZO 重定位位置
```

**ZO 在运行时的布局**（重定位到 38.96 MB后）：

```
38.96 MB (%rbx) ──┬─── ZO_startup_32 (.head.text 起始)
                  │    0.69 KB
38.96 MB + 0x2c4 ─┼─── Payload 起始 (压缩的 vmlinux)
                  │    9.85 MB
48.81 MB ─────────┼─── .text 段起始 (extract_kernel 代码)
                  │    55.25 KB
48.87 MB ─────────┴─── ZO__end
```

#### 解压过程详细分析

**关键理解**：init_size 不等于解压后的内核大小（VO_size）！

```
init_size (32.87 MB) 包含：
1. VO (解压后的 vmlinux)：约 22.96 MB
2. ZO (压缩内核)：9.91 MB
3. 安全间隔空间
```

**解压目标大小**（VO_size）：
```
VO_size ≈ init_size - ZO_size
        = 32.87 MB - 9.91 MB
        = 22.96 MB
```

**实际内存布局**：

```
16 MB (%rbp) ──────┬─── VO__text (解压目标起始)
                   │
                   │    解压写入区域
                   │    (output_len ≈ 22.96 MB)
                   │
38.96 MB ──────────┼─── VO__end (解压结束位置)
                   │
                   │    安全间隔
                   │
38.96 MB (%rbx) ───┼─── ZO_startup_32 (.head.text)
                   │    0.69 KB
                   ├─── Payload (压缩 vmlinux)
                   │    9.85 MB
48.81 MB ──────────┼─── .text 段 (extract_kernel 代码)
                   │    55.25 KB
48.87 MB ──────────┴─── ZO__end
```

**解压过程**：
1. 从 Payload (38.96-48.81 MB) 读取压缩数据
2. 向 output (16-38.96 MB) 写入解压数据
3. 解压结束于 38.96 MB

**结论**：
- ✅ **extract_kernel 代码（48.81-48.87 MB）完全不在解压范围（16-38.96 MB）内**
- ✅ **解压过程不会覆盖 extract_kernel 代码**
- ✅ **这是通过精确的内存布局计算实现的**

#### 设计精妙之处

**源代码注释**（`arch/x86/boot/compressed/misc.c:389-403`）：

```c
/*
 * The compressed kernel image (ZO), has been moved so that its position
 * is against the end of the buffer used to hold the uncompressed kernel
 * image (VO) and the execution environment (.bss, .brk), which makes sure
 * there is room to do the in-place decompression.
 *
 *                             |-----compressed kernel image------|
 *                             V                                  V
 * 0                       extract_offset                      +INIT_SIZE
 * |-----------|---------------|-------------------------|--------|
 *             |               |                         |        |
 *           VO__text      startup_32 of ZO          VO__end    ZO__end
 *             ^                                         ^
 *             |-------uncompressed kernel image---------|
 */
```

**关键点**：
1. **ZO 放在缓冲区末尾**：确保 VO 和 ZO 有合理的间隔
2. **VO_size < init_size**：解压目标小于总缓冲区大小
3. **extract_kernel 在 ZO 的最后**：位于 Payload 之后，完全在 VO 范围外

**INIT_SIZE 的计算**（`arch/x86/boot/header.S:502-509`）：

```c
#define ZO_INIT_SIZE    (ZO__end - ZO_startup_32 + ZO_z_min_extract_offset)
#define VO_INIT_SIZE    (VO__end - VO__text)
#if ZO_INIT_SIZE > VO_INIT_SIZE
# define INIT_SIZE ZO_INIT_SIZE  ← 通常取这个值
#else
# define INIT_SIZE VO_INIT_SIZE
#endif
```

这确保了：
- `init_size` 足够大，包含 VO + ZO + 安全间隔
- VO 不会扩展到 ZO 的范围

#### 原地解压（In-Place Decompression）示意图

```
源代码注释中的图（arch/x86/boot/compressed/misc.c:389-403）：

                             |-----compressed kernel image------|
                             V                                  V
 0                       extract_offset                      +INIT_SIZE
 |-----------|---------------|-------------------------|--------|
             |               |                         |        |
           VO__text      startup_32 of ZO          VO__end    ZO__end
             ^                                         ^
             |-------uncompressed kernel image---------|

实际内存地址（Linux 6.6.110）：

16 MB        38.96 MB    48.81 MB     48.87 MB
 |------------|-----------|-----------|
 |            |           |           |
 VO__text     VO__end     .text段     ZO__end
 (%rbp)                   (extract_kernel)

 |←  VO  →| 安全间隔  |←     ZO     →|
 |← 22.96MB →|        |← 9.91 MB  →|

 解压写入: 16MB → 38.96MB (不会到达 extract_kernel)
           ↑
         output_len ≈ 22.96 MB
```

**关键设计**：
- VO 结束于 38.96 MB
- ZO 开始于 38.96 MB
- extract_kernel 代码在 48.81-48.87 MB（ZO 的最后 55 KB）
- **解压写入永远不会到达 extract_kernel 代码区域**

#### 总结：精妙的内存布局设计

**核心设计原理**：

1. **分离 VO 和 ZO**：
   - `init_size` 的计算确保 VO + ZO 可以共存
   - VO（解压目标）在前，ZO（压缩源）在后
   - 两者有明确的边界

2. **extract_kernel 代码的安全位置**：
   - 位于 Payload（压缩的 vmlinux）之后
   - 完全在 VO 范围之外
   - **永远不会被解压过程覆盖**

3. **不需要任何特殊机制**：
   - ❌ 不依赖 CPU 指令缓存
   - ❌ 不需要特殊的编译器指令
   - ✅ 纯粹通过数学计算保证安全

**实际数据验证**（Linux 6.6.110）：
```
vmlinuz 结构：
  .head.text:   0.69 KB
  Payload:      9.85 MB  (压缩的 vmlinux)
  .text段:      55.25 KB (extract_kernel 等函数)

运行时布局：
  解压目标 (VO):   16 MB - 38.96 MB (22.96 MB)
  压缩源 (ZO):     38.96 MB - 48.87 MB (9.91 MB)
  extract_kernel:  48.81 MB - 48.87 MB (55 KB)

结论：完全不重叠！
```

**参考资料**：
- Linux 源代码：`arch/x86/boot/compressed/misc.c:389-403`
- Linux 源代码：`arch/x86/boot/header.S:428-509`
- 详细分析专题：
  - [SOLUTION_ICACHE_MYSTERY.md](SOLUTION_ICACHE_MYSTERY.md) - 完整答案：为什么 extract_kernel 不被覆盖
  - [WHY_RELOCATE_COMPRESSED_KERNEL.md](WHY_RELOCATE_COMPRESSED_KERNEL.md) - KASLR 与重定位的必要性
  - [INVESTIGATION_SUMMARY.md](INVESTIGATION_SUMMARY.md) - 调查过程与实验验证

### BIOS vs UEFI 两条完全不同的启动路径

**关键发现**：UEFI 启动路径**完全不经过** `arch/x86/boot/compressed/head_64.S` 的 `startup_32` 和 `startup_64`！

#### BIOS/GRUB 启动路径（经过 compressed/head_64.S）

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

#### UEFI 启动路径（绕过 compressed/head_64.S）

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

**源代码位置**：`linux/arch/x86/kernel/head_64.S:38`

**重要**：这是第二个 startup_64（【阶段3】主内核），与【阶段2】压缩内核中的 startup_64（`arch/x86/boot/compressed/head_64.S:278`）是**不同的文件**。注：【阶段1】是 startup_32，不是 startup_64。

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
