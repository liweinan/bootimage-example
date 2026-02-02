# Linux 内核启动与初始化（64 位，不走 Setup）

本文档按**实际执行顺序**描述从 GRUB（或 UEFI）进入压缩内核到 `start_kernel()` 及之后的完整流程：**不走 Setup**（GRUB 按 code32_start 跳转、UEFI 按 PE 入口跳转，直接进入压缩内核）。**从扇区 0 启动时的 Setup 流程**见 [LINUX_KERNEL_SETUP_FLOW.md](LINUX_KERNEL_SETUP_FLOW.md)。

> **相关文档**：[BOOT_FLOW.md](BOOT_FLOW.md) 启动概述；[GRUB_KERNEL_LOADING.md](GRUB_KERNEL_LOADING.md) GRUB 加载内核；[LINUX_KERNEL_SETUP_FLOW.md](LINUX_KERNEL_SETUP_FLOW.md) 从扇区 0 启动的 Setup；[LINUX_KERNEL_SETUP_ARCH_MEMORY.md](LINUX_KERNEL_SETUP_ARCH_MEMORY.md) setup_arch 内存接管详解。
>
> **执行顺序**：GRUB/入口 → startup_32（模式切换与解压）→ startup_64（主内核）→ x86_64_start_kernel（早期 IDT）→ start_kernel() → setup_arch → trap_init/syscall → init_IRQ → rest_init → 核心进程。

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

**startup_32 关键步骤（head_64.S 压缩内核）**：`call setup_identity_mapping` → `orl $X86_CR4_PAE, %eax` 写 CR4 → `movl %eax, %cr3` 写 CR3 → `rdmsr`/`btsl $_EFER_LME`/`wrmsr` 设 EFER.LME → `orl $X86_CR0_PG, %eax` 写 CR0 → `ljmp $__KERNEL_CS, $startup_64`。

---

## 三、主内核 startup_64 → x86_64_start_kernel → start_kernel()

**主内核 startup_64**（`linux/arch/x86/kernel/head_64.S`）：保存 boot_params（%RSI→%R15）、设置初始栈与 GS 基址、**设置 GDT 和早期 IDT**（`__pi_startup_64_setup_gdt_idt`）、切换到 __KERNEL_CS、可选 SEV/SME、verify_cpu，然后进入 C 代码。

**主内核 startup_64 关键步骤（head_64.S）**：`mov %rsi, %r15` 保存 boot_params → `leaq __top_init_kernel_stack(%rip), %rsp` 设栈 → `wrmsr` 设 GS_BASE → `call __pi_startup_64_setup_gdt_idt`（GDT/早期 IDT）→ `pushq $__KERNEL_CS`/`lretq` 切到内核 CS → 可选 `__pi_sme_enable`、`verify_cpu`，然后进入 C 代码。

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

| 特性 | GDT | IDT |
|------|-----|-----|
| 用途 | 段（代码/数据/栈） | 中断/异常处理程序 |
| 访问 | 段选择子 | 向量号 0–255 |
| 寄存器 | GDTR | IDTR |

---

## 四、start_kernel() 流程概述

**源代码位置**：`linux/init/main.c:898-1111`

```
start_kernel()
    ├─ 阶段 1: 早期初始化（中断禁用）
    │   ├─ boot_cpu_init(), page_address_init()
    │   ├─ setup_arch(&command_line)     // 内存接管：e820/memblock、init_mem_mapping、paging_init
    │   └─ parse_early_param() 等
    ├─ 阶段 2: 核心子系统
    │   ├─ mm_core_init(), sched_init()
    │   ├─ trap_init()                  // → cpu_init() → syscall_init()
    │   ├─ early_irq_init(), init_IRQ() // 完整 IDT、PIC、APIC、INT 0x80
    │   └─ local_irq_enable()
    ├─ 阶段 3: 设备与文件系统（console_init, vfs_caches_init, fork_init 等）
    └─ 阶段 4: rest_init()              // kernel_init(PID 1)、kthreadd(PID 2)、idle
```

### 1. setup_arch() 与内核接管内存

**关键步骤**：`setup_arch(&command_line)`。此前仅有身份映射与 early 页表；**完整物理内存接管**在 setup_arch() 中：解析 e820/EFI、memblock、`init_mem_mapping()`、`paging_init()`。详见 [LINUX_KERNEL_SETUP_ARCH_MEMORY.md](LINUX_KERNEL_SETUP_ARCH_MEMORY.md)。

### 2. trap_init() 与 syscall

**cpu_init()** 在 **trap_init()** 中调用（非 setup_arch）。trap_init() → cpu_init() → **syscall_init()**：写 MSR_STAR、MSR_LSTAR（entry_SYSCALL_64）、MSR_SYSCALL_MASK 等，用户态 `syscall` 即跳转到 entry_SYSCALL_64 → do_syscall_64 → sys_call_table[nr]。源码：`arch/x86/kernel/cpu/common.c`（syscall_init/idt_syscall_init）、`arch/x86/entry/entry_64.S`、`syscall_64.c`。

### 3. init_IRQ() 与完整 INT 服务

**早期 INT** 已在上文「x86_64_start_kernel」中设置（仅异常）。**完整 INT/IRQ** 在 **init_IRQ()** 中：idt_setup_traps() 补全异常门；init_8259A() 将 PIC IRQ 从 0x08–0x0F/0x70–0x77 重映射到 0x20–0x2F；idt_setup_apic_and_irq_gates() 设置 APIC/IRQ 门并再次 load_idt；若启用 32 位兼容则 idt_setup_ia32_syscall_gate() 设置 INT 0x80。**接管所有中断服务**的起点为 init_IRQ() 返回之后（load_idt 执行完毕）；硬件 IRQ 实际交付需等 local_irq_enable()。

- **8259A PIC**：`i8259.c`，ICW2 重映射到 0x20–0x2F。
- **APIC/IRQ 门**：`idt.c` 中 idt_setup_apic_and_irq_gates()。
- **INT 0x80**：entry_INT80_32 → do_int80_syscall_32 → ia32_sys_call。

> 运行时中断模型见 [LINUX_INTERRUPT_HANDLING.md](LINUX_INTERRUPT_HANDLING.md)；BIOS IVT 与 Kernel IDT 见 [BIOS_IVT_VS_KERNEL_IDT.md](BIOS_IVT_VS_KERNEL_IDT.md)。

### start_kernel() 关键代码（节选）

```c
void start_kernel(void)
{
	boot_cpu_init();
	setup_arch(&command_line);
	// ...
	trap_init();      // cpu_init() → syscall_init()
	mm_core_init();
	sched_init();
	early_irq_init();
	init_IRQ();
	// ...
	local_irq_enable();
	// ...
	rest_init();
}
```

### 4. rest_init() 与 kernel_init()

**rest_init()**（`main.c:699-746`）：`user_mode_thread(kernel_init, ...)` → PID 1；`kernel_thread(kthreadd, ...)` → PID 2；`complete(&kthreadd_done)`；`cpu_startup_entry(CPUHP_ONLINE)` → 当前进程（PID 0）进入 idle 循环。

**kernel_init()**（`main.c:1465-1528`）：`wait_for_completion(&kthreadd_done)`；`kernel_init_freeable()`；`free_initmem()`；`system_state = SYSTEM_RUNNING`；`run_init_process(ramdisk_execute_command)` 或 execute_command、"/sbin/init" 等，失败则 panic。

---

## 五、核心进程详解

- **PID 0（swapper/idle）**：`init_task` 静态定义（`init_task.c`），mm=NULL，执行 start_kernel/rest_init 后 `cpu_startup_entry()` → `do_idle()`（need_resched() 为假时 `cpuidle_idle_call()`，hlt/mwait）。每 CPU 一个（swapper/0, swapper/1, …）。
- **PID 1（init）**：kernel_init → execve("/init") 或 "/sbin/init"，用户空间进程祖先，孤儿收养、僵尸回收，不可 kill -9。
- **PID 2（kthreadd）**：`kthread.c` 中循环处理 `kthread_create_list`，创建 kworker、ksoftirqd、migration、watchdog、kswapd 等内核线程。

**层次**：PID 0 → rest_init 创建 PID 1、PID 2；PID 0 进入 idle；PID 1 启动用户空间；PID 2 管理内核线程。

> **更多**：[BOOT_FLOW.md](BOOT_FLOW.md)、[GRUB_KERNEL_LOADING.md](GRUB_KERNEL_LOADING.md)、[VMLINUZ_STRUCTURE.md](VMLINUZ_STRUCTURE.md)、[INITRAMFS_ANALYSIS.md](INITRAMFS_ANALYSIS.md)。
