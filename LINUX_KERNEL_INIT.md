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

## 中断与系统调用机制概览

**重要概念澄清**：为避免混淆，先明确 IDT 与系统调用的关系。

### IDT（中断描述符表）包含的内容

IDT 是 x86 架构的硬件机制，CPU 通过中断向量号（0-255）查询 IDT 表，跳转到对应的处理程序。

| 中断类型 | 向量范围 | 说明 | 设置阶段 |
|---------|---------|------|---------|
| **CPU 异常** | 0-31 | #DE(除零), #PF(缺页), #GP(通用保护) 等 | idt_setup_early_handler() → idt_setup_traps() |
| **硬件中断 (IRQ)** | 32-255 | 时钟、键盘、网卡等设备中断 | idt_setup_apic_and_irq_gates() |
| **软件中断** | 特定向量 | INT 0x80（32位系统调用兼容） | idt_setup_ia32_syscall_gate() |

### 系统调用的两种机制

Linux 内核支持两种系统调用机制，**它们的实现方式完全不同**：

| 机制 | 指令 | 是否使用 IDT | 设置时机 | 性能 | 适用范围 |
|------|------|-------------|---------|------|---------|
| **传统机制** | `INT 0x80` | ✅ 是（查询 IDT[0x80]） | init_IRQ() → idt_setup_ia32_syscall_gate() | 慢 | 32位兼容 |
| **现代机制** | `SYSCALL`/`SYSENTER` | ❌ 否（通过 MSR 寄存器） | trap_init() → syscall_init() | 快 | 64位主流 |

**关键区别**：
- **INT 0x80**：是 IDT 表的一个条目（向量 0x80），通过软件中断机制实现
- **SYSCALL**：是专用 CPU 指令，通过 MSR 寄存器（MSR_LSTAR 等）配置入口地址，**完全绕过 IDT**

> 详细对比见本文档第 2 节「trap_init() 与 syscall」和第 3 节「init_IRQ() 与接管 INT 服务的过程」。

---

## 完整流程图（按执行顺序）

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
【阶段1】压缩内核 startup_32（arch/x86/boot/compressed/head_64.S:82）
    │   在 1MB 处执行，32位保护模式
    ├─ GDT/栈/段设置
    ├─ verify_cpu
    ├─ CR4.PAE=1
    ├─ 构建身份映射页表（内联，head_64.S:200-231）
    ├─ CR3 = pgtable（head_64.S:234-235）
    ├─ EFER.LME = 1
    ├─ CR0.PG = 1
    └─ lret → 【阶段2】压缩内核 startup_64（head_64.S:273 跳转到 278）
        ↓
【阶段2】压缩内核 startup_64
    │   64位长模式
    ├─ 【仍在 1MB 处执行】设置64位环境：段寄存器、栈、GDT
    ├─ 【仍在 1MB 处执行】load_stage1_idt
    ├─ 【仍在 1MB 处执行】sev_enable
    ├─ 【仍在 1MB 处执行】configure_5level_paging
    ├─ 【重定位拷贝】rep movsq 拷贝到 %rbx（通常 38MB）
    ├─ 重新加载 GDT
    ├─ jmp .Lrelocated（跳到 %rbx 处）
    ├─ 【现在在 %rbx 处执行】清除 BSS
    ├─ load_stage2_idt
    ├─ initialize_identity_maps
    ├─ call extract_kernel
    │   extract_kernel()（arch/x86/boot/compressed/misc.c:334）
    │       → 解压内核到 %rbp（0x1000000，即 16MB）
    └─ jmp *%rax（head_64.S:475）
        → 【阶段3】跳转到主内核 startup_64（解压后内核的入口）
        ↓
【阶段3】主内核 startup_64
    ├─ mov %rsi, %r15
    │   → 保存 boot_params 指针到 R15
    ├─ leaq __top_init_kernel_stack(%rip), %rsp
    │   → 设置初始内核栈
    ├─ xor %rbx, %rbx; wrmsr
    │   → 清零 GS_BASE（MSR_GS_BASE）
    ├─ call startup_64_setup_gdt_idt
    │   startup_64_setup_gdt_idt()（arch/x86/boot/startup/gdt_idt.c:49）
    │       ├─ rip_rel_ptr(&gdt_page)
    │       ├─ native_load_gdt(&startup_gdt_descr)
    │       │   → 加载内核 GDT
    │       ├─ loadsegment(ds, __KERNEL_DS)
    │       ├─ loadsegment(ss, __KERNEL_DS)
    │       └─ startup_64_load_idt(handler)
    │           startup_64_load_idt()
    │               ├─ idt_init_desc(..., X86_TRAP_VC, ...)（仅 AMD SEV）
    │               └─ native_load_idt(&desc)
    ├─ pushq $__KERNEL_CS; lretq（head_64.S:77-80）
    │   → 切换到 __KERNEL_CS 代码段
    ├─ [可选] call sme_enable（CONFIG_AMD_MEM_ENCRYPT）
    ├─ call verify_cpu
    └─ jmp initial_code（head_64.S 末尾跳转表）
        → 跳转到 x86_64_start_kernel
        ↓
x86_64_start_kernel()（arch/x86/kernel/head64.c:222）
    ├─ cr4_init_shadow()
    ├─ reset_early_page_tables()
    ├─ clear_bss()
    ├─ clear_page(init_top_pgt)
    ├─ sme_early_init()
    ├─ idt_setup_early_handler()【内核接管 INT（早期）】
    │   idt_setup_early_handler()（arch/x86/kernel/idt.c:320）
    │       ├─ for (i = 0; i < NUM_EXCEPTION_VECTORS; i++)
    │       │   idt_setup_from_table(..., early_idt_handler_array, ...)
    │       └─ load_idt(&idt_descr)
    │           → 加载早期 IDT，处理 CPU 异常
    ├─ kasan_early_init()（head64.c:252）
    ├─ tdx_early_init()
    ├─ copy_bootdata(__va(real_mode_data))
    ├─ load_ucode_bsp()
    ├─ init_top_pgt[511] = __pmd(...)
    │   → 建立内核高地址映射（0xFFFFFFFF80000000）
    ├─ x86_64_start_reservations(real_mode_data)
    │   x86_64_start_reservations()
    │       ├─ copy_bootdata(__va(real_mode_data))
    │       ├─ x86_early_init_platform_quirks()
    │       └─ start_kernel()
    └─ → start_kernel()
        ↓
start_kernel()（init/main.c:1005）
    │
    ├─ 【阶段 1：早期初始化】
    │   ├─ set_task_stack_end_magic(&init_task)
    │   ├─ smp_setup_processor_id()
    │   ├─ debug_objects_early_init()
    │   ├─ cgroup_init_early()
    │   ├─ local_irq_disable()
    │   ├─ boot_cpu_init()
    │   ├─ page_address_init()
    │   ├─ pr_notice("%s", linux_banner)
    │   ├─ early_security_init()
    │   ├─ setup_arch(&command_line)【内核接管内存】
    │   │   setup_arch()（arch/x86/kernel/setup.c:880）
    │   │       ├─ memblock_reserve(__pa_symbol(_text), ...)
    │   │       ├─ early_reserve_memory()
    │   │       ├─ e820__memory_setup()
    │   │       │   e820__memory_setup()（arch/x86/kernel/e820.c:1354）
    │   │       │       └─ e820__memory_setup_default()
    │   │       ├─ parse_setup_data()（setup.c:978）
    │   │       ├─ e820__finish_early_params()
    │   │       ├─ max_pfn = e820__end_of_ram_pfn()
    │   │       │   e820__end_of_ram_pfn()（arch/x86/kernel/e820.c:1422）
    │   │       ├─ e820__memblock_setup()（setup.c:1055）
    │   │       │   e820__memblock_setup()（arch/x86/kernel/e820.c:1242）
    │   │       ├─ init_mem_mapping()（setup.c:1083）
    │   │       │   init_mem_mapping()（arch/x86/mm/init.c:758）
    │   │       ├─ initmem_init()（setup.c:1118）
    │   │       ├─ x86_init.paging.pagetable_init()
    │   │       │   → paging_init()（arch/x86/mm/init_64.c:819）
    │   │       └─ idt_setup_early_traps()（setup.c:1241）
    │   │           idt_setup_early_traps()（arch/x86/kernel/idt.c:336）
    │   ├─ setup_command_line(command_line)（main.c:1022）
    │   ├─ setup_nr_cpu_ids()
    │   ├─ setup_per_cpu_areas()
    │   ├─ smp_prepare_boot_cpu()
    │   ├─ boot_cpu_hotplug_init()
    │   ├─ build_all_zonelists(NULL)
    │   ├─ page_alloc_init()
    │   ├─ parse_early_param()
    │   ├─ parse_args(...)
    │   ├─ jump_label_init()
    │   ├─ setup_log_buf(0)
    │   ├─ vfs_caches_init_early()
    │   ├─ sort_main_extable()
    │   ├─ trap_init()
    │   │   trap_init()（arch/x86/kernel/traps.c:1680）
    │   │       ├─ idt_setup_traps()
    │   │       │   idt_setup_traps()（arch/x86/kernel/idt.c:264）
    │   │       ├─ idt_setup_ist_traps()（traps.c:1685）
    │   │       │   idt_setup_ist_traps()（arch/x86/kernel/idt.c:269）
    │   │       ├─ cpu_init()（traps.c:1690）
    │   │       │   cpu_init()（arch/x86/kernel/cpu/common.c:2210）
    │   │       │       ├─ load_current_idt()
    │   │       │       ├─ load_sp0(t, &current->thread)
    │   │       │       ├─ load_mm_ldt(&init_mm)
    │   │       │       └─ syscall_init()
    │   │       │           syscall_init()
    │   │       │               ├─ wrmsr(MSR_STAR, ...)
    │   │       │               ├─ wrmsrl(MSR_LSTAR, ...)
    │   │       │               └─ wrmsrl(MSR_SYSCALL_MASK, ...)
    │   │       └─ idt_setup_debuggers()（traps.c:1693）
    │   └─ mm_core_init()（main.c:1046）
    │
    ├─ 【阶段 2：内存、调度、中断初始化】
    │   ├─ poking_init()
    │   ├─ ftrace_init()
    │   ├─ early_trace_init()
    │   ├─ sched_init()
    │   │   sched_init()（kernel/sched/core.c:10056）
    │   ├─ preempt_disable()（main.c:1063）
    │   ├─ radix_tree_init()
    │   ├─ housekeeping_init()
    │   ├─ workqueue_init_early()
    │   ├─ rcu_init()
    │   │   rcu_init()（kernel/rcu/tree.c:5088）
    │   ├─ trace_init()（main.c:1076）
    │   ├─ early_irq_init()
    │   │   early_irq_init()（kernel/irq/irqdesc.c:560）
    │   ├─ init_IRQ()（main.c:1079）【内核接管 INT（完整）】
    │   │   init_IRQ()（arch/x86/kernel/irqinit.c:75）
    │   │       ├─ x86_init.irqs.intr_init()
    │   │       │   → native_init_IRQ()（arch/x86/kernel/irq.c:110）
    │   │       │       ├─ idt_setup_apic_and_irq_gates()
    │   │       │       │   idt_setup_apic_and_irq_gates()（arch/x86/kernel/idt.c:278）
    │   │       │       │       ├─ idt_setup_from_table(..., apic_idts, ...)
    │   │       │       │       └─ for (i = 0; i < nr_legacy_irqs(); i++)
    │   │       │       │           idt_set_irq(irq_to_desc(i), IDT_INDEX(i))
    │   │       │       ├─ if (!acpi_ioapic && !of_ioapic && nr_legacy_irqs())（irq.c:117）
    │   │       │       │   setup_irq(2, &irq2)
    │   │       │       │       → 设置 INT 0x80 (i8259 级联)
    │   │       │       └─ irq_ctx_init(smp_processor_id())
    │   │       ├─ irq_init_percpu_irqstack(smp_processor_id())（irqinit.c:88）
    │   │       └─ lapic_assign_system_vectors()
    │   ├─ tick_init()（main.c:1080）
    │   ├─ rcu_init_nohz()
    │   ├─ init_timers()
    │   ├─ srcu_init()
    │   ├─ hrtimers_init()
    │   ├─ softirq_init()
    │   ├─ timekeeping_init()
    │   ├─ time_init()
    │   ├─ perf_event_init()
    │   ├─ profile_init()
    │   ├─ call_function_init()
    │   ├─ local_irq_enable()
    │   │   → 首次开启中断，此后可响应硬件中断
    │   └─ kmem_cache_init_late()
    │
    ├─ 【阶段 3：控制台、文件系统、进程管理初始化】
    │   ├─ console_init()
    │   │   console_init()（drivers/tty/tty_io.c:2872）
    │   ├─ locking_selftest()（main.c:1096）
    │   ├─ mem_encrypt_init()
    │   ├─ vfs_caches_init()
    │   │   vfs_caches_init()（fs/dcache.c:3277）
    │   ├─ pagecache_init()（main.c:1102）
    │   ├─ signals_init()
    │   ├─ seq_file_init()
    │   ├─ proc_root_init()
    │   ├─ nsfs_init()
    │   ├─ cpuset_init()
    │   ├─ cgroup_init()
    │   ├─ taskstats_init_early()
    │   ├─ delayacct_init()
    │   ├─ acpi_subsystem_init()
    │   ├─ arch_post_acpi_subsys_init()
    │   ├─ kcsan_init()
    │   ├─ check_bugs()
    │   ├─ acpi_early_init()
    │   ├─ arch_call_rest_init()
    │   │   arch_call_rest_init()（arch/x86/kernel/process.c:856）
    │   │       └─ rest_init()（init/main.c:711）
    │   └─ prevent_tail_call_optimization()
    │
    └─ 【阶段 4：rest_init() - 创建 PID 1/2、PID 0 进入 idle】
        rest_init()
            ├─ rcu_scheduler_starting()
            ├─ user_mode_thread(kernel_init, NULL, CLONE_FS)
            │   user_mode_thread()（kernel/fork.c:2718）
            │       ├─ kernel_clone(&args)
            │       │   kernel_clone()
            │       │       → 创建内核线程，PID = 1
            │       └─ 返回 PID 1
            │   → 创建 PID 1（init），入口函数 kernel_init
            ├─ numa_default_policy()（main.c:717）
            ├─ kernel_thread(kthreadd, NULL, NULL, CLONE_FS | CLONE_FILES)
            │   kernel_thread()（kernel/fork.c:2697）
            │       ├─ kernel_clone(&args)
            │       │   → 创建内核线程，PID = 2
            │       └─ 返回 PID 2
            │   → 创建 PID 2（kthreadd），入口函数 kthreadd
            ├─ kthreadd_done = &kthreadd_done_completion（main.c:722）
            ├─ complete(&kthreadd_done)
            │   → 通知 PID 1：kthreadd 已就绪
            ├─ schedule_preempt_disabled()
            └─ cpu_startup_entry(CPUHP_ONLINE)
                cpu_startup_entry()（kernel/sched/idle.c:393）
                    ├─ arch_cpu_idle_prepare()
                    ├─ cpuhp_online_idle(CPUHP_AP_ONLINE_IDLE)
                    └─ do_idle()
                        do_idle()
                            → 当前进程（PID 0: swapper）进入 idle 循环，不返回
                            → 永久循环：check_preempt_curr() → schedule() → cpu_idle_loop()

【PID 1：kernel_init 线程】
kernel_init()（init/main.c:1569）
    ├─ kernel_init_freeable()
    │   kernel_init_freeable()
    │       ├─ wait_for_completion(&kthreadd_done)
    │       │   → 等待 kthreadd 就绪
    │       ├─ workqueue_init()
    │       ├─ init_mm_internals()
    │       ├─ rcu_init_tasks_generic()
    │       ├─ do_pre_smp_initcalls()
    │       ├─ smp_init()
    │       ├─ sched_init_smp()
    │       ├─ padata_init()
    │       ├─ page_alloc_init_late()
    │       ├─ do_basic_setup()
    │       │   do_basic_setup()
    │       │       ├─ driver_init()
    │       │       ├─ init_irq_proc()
    │       │       └─ do_initcalls()
    │       ├─ console_on_rootfs()
    │       ├─ rcu_end_inkernel_boot()
    │       └─ system_state = SYSTEM_RUNNING
    ├─ numa_default_policy()
    ├─ rcu_end_inkernel_boot()
    ├─ do_sysctl_args()
    ├─ if (!ramdisk_execute_command)
    │   ramdisk_execute_command = "/init"
    ├─ if (!try_to_run_init_process(ramdisk_execute_command))
    │   try_to_run_init_process()
    │       └─ run_init_process(init_filename)
    │           run_init_process()
    │               ├─ argv_init[0] = init_filename
    │               └─ kernel_execve(init_filename, argv_init, envp_init)
    │                   → 执行用户空间 init 程序（如 /init, /sbin/init）
    └─ → 成功执行用户空间 init，不返回

【PID 2：kthreadd 线程】
kthreadd()（kernel/kthread.c:815）
    ├─ set_task_comm(tsk, "kthreadd")
    ├─ ignore_signals(tsk)
    ├─ set_cpus_allowed_ptr(tsk, housekeeping_cpumask(...))
    ├─ set_mems_allowed(node_states[N_MEMORY])
    ├─ current->flags |= PF_NOFREEZE
    ├─ cgroup_init_kthreadd()
    └─ for (;;)
        └─ 永久循环：等待创建新内核线程请求，负责创建所有后续内核线程
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
| 构建页表 | 在 rva(pgtable)(%ebx) 处内联建 4 级页表（L4/L3/L2），身份映射前 4G；CONFIG_AMD_MEM_ENCRYPT 时 %edx 为加密位掩码 | 开启分页后需有效页表；身份映射保证当前指令与数据在开 PG 后仍可访问。MMU 与分页概念见 [PAGING_PHASE1_THEORY_AND_EARLY_TABLES.md](PAGING_PHASE1_THEORY_AND_EARLY_TABLES.md) |
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
    │       └─ 为何重定位？见 [COMPRESSED_KERNEL_RELOCATION.md](COMPRESSED_KERNEL_RELOCATION.md)
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

**源代码位置**：`linux/arch/x86/kernel/head_64.S:38`

**重要**：这是第二个 startup_64（【阶段3】主内核），与【阶段2】压缩内核中的 startup_64（`arch/x86/boot/compressed/head_64.S:278`）是**不同的文件**。注：【阶段1】是 startup_32，不是 startup_64。

> **关于 `__pi_` 前缀与位置无关代码**：
>
> 在主内核 startup_64 的早期阶段（如 `call startup_64_setup_gdt_idt`），内核尚未完全建立虚拟地址映射，此时需要使用**位置无关代码（Position Independent Code, PIC）**来访问全局符号。你可能会在代码中看到带 `__pi_` 前缀的符号（如 `__pi_startup_64_setup_gdt_idt`），这些符号是通过 `objcopy --prefix-symbols=__pi_` 自动生成的 PIC 版本。
>
> 详细的实现机制（包括 `-fPIC` 编译选项、`objcopy` 符号前缀处理、RIP 相对寻址、`rip_rel_ptr()` 宏、`SYM_PIC_ALIAS` 宏等）请参阅：
> - **[POSITION_INDEPENDENT_CODE.md](POSITION_INDEPENDENT_CODE.md)** - 位置无关代码完整分析

**主内核 startup_64**：保存 boot_params（%RSI→%R15）、设置初始栈与 GS 基址、**设置 GDT 和早期 IDT**（`startup_64_setup_gdt_idt`）、切换到 __KERNEL_CS、可选 SEV/SME、verify_cpu，然后进入 C 代码。

**主内核 startup_64 关键步骤**：

```
startup_64
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

> **相关文档**：
> - [POSITION_INDEPENDENT_CODE.md](POSITION_INDEPENDENT_CODE.md)：详细分析了 `__pi_` 前缀的含义、位置无关代码编译机制（-fPIC、objcopy --prefix-symbols）、RIP 相对寻址、SYM_PIC_ALIAS 宏的实现原理，以及 `startup_64_setup_gdt_idt()` 如何通过 `rip_rel_ptr()` 访问符号

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
startup_64
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

- **startup_64_setup_gdt_idt()**：rip_rel_ptr 取 gdt_page→ **lgdt** → 段寄存器 **DS/SS/ES = __KERNEL_DS** → 若启用 SEV 则 handler = vc_no_ghcb → **startup_64_load_idt(handler)**。
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

**GDT 与 IDT**：GDT 定义段（代码/数据/栈）；IDT 定义中断/异常时跳转目标。早期 IDT 在此阶段设置（仅CPU异常），完整 IDT（包括硬件中断和 INT 0x80）在 start_kernel() 的 init_IRQ() 中设置。**注**：现代系统调用（SYSCALL/SYSENTER）不通过 IDT，而是在 trap_init() 中通过 MSR 寄存器配置（见本文档开头的「中断与系统调用机制概览」）。

| 特性 | GDT（全局描述符表） | IDT（中断描述符表） |
|------|---------------------|---------------------|
| 用途 | 定义内存段（代码段、数据段等） | 定义中断/异常处理程序 |
| 访问方式 | 段选择子（Segment Selector） | 中断向量号（0–255） |
| 寄存器 | GDTR（GDT 基址与界限） | IDTR（IDT 基址与界限） |
| 加载指令 | LGDT | LIDT |
| 条目内容 | 段描述符（基址、界限、权限等） | 中断门/陷阱门（处理程序地址） |
| 主要功能 | 内存分段和保护 | 中断与异常处理 |

### IDT 表的演进流程：从临时表到运行时表

Linux 内核使用**两个独立的 IDT 表**，有明确的切换和逐步完善过程。这是为了避免早期启动代码被 tracing/KASAN instrumentation 干扰。

#### 两个 IDT 表

**1. bringup_idt_table（临时表，极早期）**

定义在 `arch/x86/boot/startup/gdt_idt.c:24`：
```c
static gate_desc bringup_idt_table[NUM_EXCEPTION_VECTORS] __page_aligned_data;
```

- **大小**：只有 32 个异常向量（`NUM_EXCEPTION_VECTORS`）
- **使用时机**：主内核 startup_64 汇编代码中（`head_64.S:74`）
- **加载位置**：`startup_64_setup_gdt_idt()` → `startup_64_load_idt()`
- **用途**：极早期阶段，只能处理 #VC (VMM Communication Exception)
- **限制**：内容几乎为空（除非启用 AMD SEV），仅作为占位，避免 CPU 访问无效 IDT

**为什么需要临时表？** 注释（`gdt_idt.c:12-23`）说明：
> The bringup-IDT is used until the idt_table takes over. The idt_table can't be used that early because all the code modifying it is in idt.c and can be **instrumented by tracing or KASAN**, which both don't work during early CPU bringup. Also the idt_table has the runtime vectors configured which require certain CPU state to be setup already (like TSS), which also hasn't happened yet in early CPU bringup.

#### bringup_idt_table 的具体内容定义

**初始化方式**：

```c
// arch/x86/boot/startup/gdt_idt.c:24
static gate_desc bringup_idt_table[NUM_EXCEPTION_VECTORS] __page_aligned_data;
```

- `__page_aligned_data` 宏定义（`include/linux/linkage.h:39`）：
  ```c
  #define __page_aligned_data __section(".data..page_aligned") __aligned(PAGE_SIZE)
  ```
- 放在 `.data..page_aligned` section 中，页对齐
- **初始化为全零**（静态变量，编译器自动清零）

**运行时填充**：

```c
// arch/x86/boot/startup/gdt_idt.c:27-44
void startup_64_load_idt(void *vc_handler)
{
    struct desc_ptr desc = {
        .address = (unsigned long)rip_rel_ptr(bringup_idt_table),
        .size    = sizeof(bringup_idt_table) - 1,
    };
    struct idt_data data;
    gate_desc idt_desc;

    /* @vc_handler is set only for a VMM Communication Exception */
    if (vc_handler) {
        init_idt_data(&data, X86_TRAP_VC, vc_handler);      // 初始化 #VC 数据
        idt_init_desc(&idt_desc, &data);                    // 创建门描述符
        native_write_idt_entry((gate_desc *)desc.address, X86_TRAP_VC, &idt_desc);
    }

    native_load_idt(&desc);  // lidt 指令加载
}
```

**表的内容总结**：

| 条件 | IDT 内容 | 说明 |
|------|---------|------|
| **默认情况**（大多数系统） | 32 个全零的 gate_desc 条目 | 所有条目都是无效门描述符 |
| **启用 AMD SEV**（虚拟化环境） | 只有 `IDT[29]` (#VC 异常) 被填充 | 其他 31 个条目仍为 0 |
| **任何情况** | 没有硬件中断门 | 因为此时中断已关闭（见下文） |

**为什么几乎为空是安全的？**

1. **中断已关闭**：早期启动阶段 `EFLAGS.IF = 0`，不会响应硬件中断
2. **代码非常简单**：从 `startup_64_setup_gdt_idt()` 到 `idt_setup_early_handler()` 之间的代码很少，几乎不会触发异常
3. **如果触发未处理的异常**：
   - CPU 查找 `bringup_idt_table[vector]`
   - 发现是全零（无效门描述符）
   - 触发 **Double Fault (#DF)**
   - #DF 也没有处理函数 → **Triple Fault** → CPU 重启
4. **这是可接受的**：如果在这个简单阶段触发异常，说明有严重错误，重启是合理的

**2. idt_table（运行时表，最终表）**

定义在 `arch/x86/kernel/idt.c:173`：
```c
static gate_desc idt_table[IDT_ENTRIES] __page_aligned_bss;
```

- **大小**：256 个条目（`IDT_ENTRIES`）
- **使用范围**：从 `idt_setup_early_handler()` 开始，一直到内核运行结束
- **完全替换** `bringup_idt_table`，而不是在其基础上添加

#### 切换时机和逐步完善流程

**完整的 IDT 演进时间线**：

```
阶段 0: 汇编启动阶段（head_64.S）
    └─ startup_64_setup_gdt_idt() → startup_64_load_idt()
       ├─ 加载 bringup_idt_table（临时表）
       ├─ 只填充 #VC 向量（如果启用 AMD SEV）
       └─ lidt → CPU 开始使用 bringup_idt_table
       【bringup_idt_table 生效期：从此处到下一个 lidt】

阶段 1: x86_64_start_kernel() → idt_setup_early_handler()
    └─ idt_setup_early_handler()（idt.c:320-331）
       ├─ 遍历 NUM_EXCEPTION_VECTORS（32 个异常向量）
       ├─ 每个向量调用 set_intr_gate(i, early_idt_handler_array[i])
       │       └─ 直接写入 idt_table[i]  ✨ 第一次写入 idt_table
       ├─ load_idt(&idt_descr) → lidt
       └─ 【切换点】从此处开始，bringup_idt_table 被废弃！
       【idt_table 生效期：从此处开始，一直到内核运行结束】

       填充内容：
       - 所有 CPU 异常向量（0-31）→ early_idt_handler_array
       - 作用：处理启动早期的异常（#PF, #DE, #GP 等）
       - 限制：尚无 IST（中断栈），尚无硬件 IRQ 门，尚无 INT 0x80

阶段 2: setup_arch() → idt_setup_early_traps()
    └─ idt_setup_early_traps()
       ├─ idt_setup_from_table(idt_table, early_idts, ...)
       │       └─ 写入 early_idts[]：DB, BP, PF (x86_32), VE
       ├─ load_idt(&idt_descr)
       └─ 继续完善 idt_table（仍是同一个表）

阶段 3: trap_init() → idt_setup_traps()
    └─ idt_setup_traps()
       ├─ idt_setup_from_table(idt_table, def_idts, ...)
       │       └─ 写入 def_idts[]：DE, NMI, BR, UD, NM, DF, GP, AC, MF, MC 等
       │       └─ 这次会设置 IST（中断栈）：NMI, DF, DB, MC, VC 等使用独立栈
       └─ 继续完善 idt_table（仍是同一个表）

阶段 4: init_IRQ() → idt_setup_apic_and_irq_gates()
    └─ idt_setup_apic_and_irq_gates()
       ├─ idt_setup_from_table(idt_table, apic_idts, ...)
       │       └─ 写入 apic_idts[]：RESCHEDULE, CALL_FUNCTION, LOCAL_TIMER 等
       ├─ 填充外部中断向量（FIRST_EXTERNAL_VECTOR - FIRST_SYSTEM_VECTOR）
       │       └─ for_each_clear_bit: set_intr_gate(i, irq_entries_start + ...)
       ├─ 填充系统中断向量（FIRST_SYSTEM_VECTOR - NR_VECTORS）
       ├─ idt_map_in_cea() → 映射 IDT 到 CPU entry area（只读）
       ├─ load_idt(&idt_descr)
       ├─ set_memory_ro(&idt_table, 1) → 设置 IDT 表为只读
       └─ idt_setup_done = true  ✨ IDT 完全就绪！

       填充内容：
       - APIC 中断：IPI、timer、spurious 等
       - 外部硬件 IRQ：0x20-0x2F（8259A PIC）等
       - 所有剩余向量
       - 【此后 CPU 拥有完整的中断处理能力】

阶段 5（可选）: idt_setup_ia32_syscall_gate()
    └─ 如果启用 CONFIG_IA32_EMULATION
       └─ 填充 INT 0x80 → entry_INT80_32
```

#### 关键代码证据

**idt_setup_from_table**（`idt.c:194-204`）每次都是**直接写入** `idt_table`：
```c
static __init void
idt_setup_from_table(gate_desc *idt, const struct idt_data *t, int size, bool sys)
{
    gate_desc desc;
    for (; size > 0; t++, size--) {
        idt_init_desc(&desc, t);
        write_idt_entry(idt, t->vector, &desc);  // 直接写入指定向量
        if (sys)
            set_bit(t->vector, system_vectors);
    }
}
```

每次调用都传入 `idt_table` 作为目标：
- `idt_setup_early_handler()` → `set_intr_gate()` → 写入 `idt_table`
- `idt_setup_early_traps()` → `idt_setup_from_table(idt_table, early_idts, ...)`
- `idt_setup_traps()` → `idt_setup_from_table(idt_table, def_idts, ...)`
- `idt_setup_apic_and_irq_gates()` → `idt_setup_from_table(idt_table, apic_idts, ...)`

#### 总结

**答案**：`bringup_idt_table` **会被完全替换**（准确说是被 `idt_table` 取代），后续所有的 IDT 设置都是在新的 `idt_table` 基础上逐步**填充新的服务**。

| 对比项 | bringup_idt_table | idt_table |
|--------|-------------------|-----------|
| **定义位置** | `arch/x86/boot/startup/gdt_idt.c:24` | `arch/x86/kernel/idt.c:173` |
| **大小** | 32 个条目（`NUM_EXCEPTION_VECTORS`） | 256 个条目（`IDT_ENTRIES`） |
| **生效期** | 从 `startup_64_setup_gdt_idt()` 到 `idt_setup_early_handler()` | 从 `idt_setup_early_handler()` 到内核运行结束 |
| **内容** | 几乎为空（只有可选的 #VC） | 逐步填充所有中断/异常向量 |
| **用途** | 临时占位，避免 CPU 访问无效 IDT | 运行时中断处理 |
| **是否可被 instrumentation** | 否（设计目标） | 是（在 idt.c 中，可被 KASAN/tracing） |
| **内存关系** | 完全独立的内存区域 | 完全独立的内存区域 |

**设计原因**：
- 避免早期启动代码被 tracing/KASAN instrumentation 干扰
- 早期阶段 CPU 状态不完整（TSS 未设置，无法使用 IST）
- 临时表设计简单，只需应对极少数早期异常
- 正式表功能完整，支持所有运行时需求

### 内核启动过程的中断状态

**核心结论：内核在早期启动阶段一直处于关中断状态，直到 `local_irq_enable()` 才第一次开启中断。**

#### 中断关闭的完整时间线

```
【压缩内核 startup_32】(arch/x86/boot/compressed/head_64.S)
    ├─ cli (90行)  ← 第一次关中断 (EFLAGS.IF = 0)
    └─ 切换到 64 位长模式

【压缩内核 startup_64】(arch/x86/boot/compressed/head_64.S)
    ├─ cli (291行) ← 再次确保关中断
    ├─ 重定位拷贝
    ├─ 解压内核
    └─ 跳转到主内核 startup_64

【主内核 startup_64】(arch/x86/kernel/head_64.S)
    ├─ pushq $0; popfq (408-410行) ← 清零 RFLAGS（包括 IF 位）
    ├─ startup_64_setup_gdt_idt()  ← 加载 bringup_idt_table
    │       └─ 此时：中断关闭 + IDT 几乎为空 = 双重保护
    └─ 进入 x86_64_start_kernel()

【x86_64_start_kernel()】(arch/x86/kernel/head64.c)
    ├─ 仍处于关中断状态
    ├─ idt_setup_early_handler() ← 切换到 idt_table（填充早期异常向量）
    │       └─ 此时：中断关闭 + IDT 有异常处理 = 可处理同步异常
    └─ start_kernel()

【start_kernel()】(init/main.c)
    ├─ setup_arch()       ← 中断仍关闭
    ├─ trap_init()        ← 中断仍关闭，设置 SYSCALL/SYSENTER
    ├─ init_IRQ()         ← 中断仍关闭，完善 IDT、初始化 PIC/APIC
    │       └─ idt_setup_apic_and_irq_gates() ← IDT 完全就绪
    └─ local_irq_enable() ← ✨ 第一次开中断！(main.c:1071)
            asm volatile("sti": : :"memory");
```

#### EFLAGS.IF 位的状态跟踪

| 阶段 | IF 位 | 代码位置 | 说明 |
|------|-------|---------|------|
| GRUB 跳转前 | 0 | GRUB relocator | GRUB 在跳转前执行 `cli` |
| startup_32 | 0 | compressed/head_64.S:90 | `cli` 指令 |
| startup_64（压缩） | 0 | compressed/head_64.S:291 | `cli` 指令 |
| startup_64（主内核） | 0 | kernel/head_64.S:408-410 | `pushq $0; popfq` |
| x86_64_start_kernel | 0 | head64.c | 继承 |
| start_kernel 前期 | 0 | main.c | 继承 |
| setup_arch() | 0 | setup.c | 仍关闭 |
| trap_init() | 0 | traps.c | 仍关闭 |
| init_IRQ() | 0 | irqinit.c | 仍关闭 |
| **local_irq_enable()** | **1** | main.c:1071 | ✨ **第一次开启** |

#### 为什么要关中断这么久？

**原因 1：硬件中断处理机制未就绪**

- **PIC/APIC 未初始化**：
  - 8259A PIC 的 ICW（Initialization Command Words）还没有设置
  - Local APIC 还没有使能和配置
  - 中断向量映射还没有建立（PIC 默认映射 0x08-0x0F 与 CPU 异常冲突）

- **IDT 不完整**：
  - `bringup_idt_table` 几乎为空，无法处理硬件中断
  - 早期的 `idt_table` 只有异常向量，没有硬件 IRQ 门
  - 直到 `idt_setup_apic_and_irq_gates()` 才填充硬件中断向量

- **没有中断栈**：
  - IST（Interrupt Stack Table）还没有设置
  - TSS（Task State Segment）还没有初始化
  - 中断处理可能栈溢出

**原因 2：CPU 状态不稳定**

- **GDT 可能在切换**：`startup_64_setup_gdt_idt()` 正在加载新的 GDT
- **页表在建立中**：`init_mem_mapping()` 正在建立完整页表
- **栈在切换**：从临时栈切换到内核栈
- **如果此时发生中断**：可能访问无效的段、页表或栈，导致 Triple Fault

**原因 3：内存管理未就绪**

- **memblock 未初始化**：`setup_arch()` 才建立 memblock
- **buddy 系统未初始化**：`mm_core_init()` 才建立伙伴系统
- **如果中断处理需要分配内存**：会导致系统崩溃

**原因 4：并发安全**

- 早期初始化代码**不是并发安全的**
- 没有锁机制保护
- 如果中断打断，可能导致数据竞争
- 例如：全局变量正在初始化，中断处理函数读取到不一致的值

**原因 5：调试和可预测性**

- 关中断保证了启动过程的**确定性**
- 不会被异步中断打断，便于调试
- 启动顺序完全可控

#### 中断关闭期间可能发生的异常

虽然硬件中断被关闭，但以下**同步异常**仍可能发生（通过 IDT 处理）：

| 异常类型 | 向量 | 何时可能发生 | 处理方式 |
|---------|------|-------------|---------|
| **#PF (Page Fault)** | 14 | `init_mem_mapping()` 建立页表时 | `idt_setup_early_handler()` 后有处理函数 |
| **#GP (General Protection)** | 13 | 访问无效段或特权级错误 | `idt_setup_early_handler()` 后有处理函数 |
| **#UD (Invalid Opcode)** | 6 | CPU 不支持的指令 | `idt_setup_early_handler()` 后有处理函数 |
| **#DF (Double Fault)** | 8 | 异常处理时又发生异常 | `idt_setup_traps()` 后有处理函数 + IST |
| **#VC (VMM Communication)** | 29 | SEV-SNP 虚拟化环境 | `bringup_idt_table` 中就有处理函数 |

**关键点**：
- 这些都是**同步异常**，由当前执行的指令触发
- 不受 `EFLAGS.IF` 影响
- 可以通过 IDT 处理（如果有处理函数）
- 如果 IDT 中没有处理函数 → Double Fault → Triple Fault → 重启

#### 何时真正开始响应硬件中断？

```c
// init/main.c
asmlinkage __visible __init __no_sanitize_address __noreturn __no_stack_protector
void start_kernel(void)
{
    ...
    trap_init();               // 设置完整的 IDT + SYSCALL
    init_IRQ();                // 初始化 PIC/APIC + 填充硬件中断向量
    ...
    /* Do the rest non-__init'ed, we're now alive */
    local_irq_enable();        // ← main.c:1071，第一次开中断 ✨
    ...
    rest_init();               // 创建 init 和 kthreadd 进程
}
```

**`local_irq_enable()` 的实现**：

```c
// include/linux/irqflags.h
#define local_irq_enable() \
    do { \
        asm volatile("sti": : :"memory"); \
    } while (0)
```

**开中断后的状态**：
- ✅ IDT 完全就绪（所有 256 个向量）
- ✅ PIC/APIC 已初始化
- ✅ TSS 和 IST 已设置
- ✅ 内存管理系统就绪
- ✅ 可以安全响应硬件中断（时钟、键盘、网卡等）

#### 总结：双重保护机制

内核启动早期采用**双重保护**策略：

1. **关中断（EFLAGS.IF = 0）**：
   - 防止硬件中断打断
   - 确保启动流程的确定性

2. **空 IDT（bringup_idt_table 几乎为空）**：
   - 即使误开中断或发生异常
   - 也会因为无效门描述符导致 Triple Fault 重启
   - 而不是进入未知状态

这种设计确保了**启动过程的稳定性和可预测性**，只有在所有硬件和软件机制都就绪后，才开启中断，开始响应外部事件。

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

**关键步骤**：`setup_arch(&command_line)`。此前仅有身份映射与 early 页表；**完整物理内存接管**在 setup_arch() 中：解析 e820/EFI、memblock、`init_mem_mapping()`、`paging_init()`。详见 [PAGING_PHASE2_FULL_SETUP_IN_SETUP_ARCH.md](PAGING_PHASE2_FULL_SETUP_IN_SETUP_ARCH.md)。

### 2. trap_init() 与 syscall

**cpu_init()** 在 **trap_init()** 中调用（非 setup_arch）。用户态 `syscall` 跳转到 entry_SYSCALL_64 → do_syscall_64 → sys_call_table[nr]。

**调用层级：**

```
start_kernel()
    └─ trap_init()（main.c:958 → traps.c:1561）  【内核接管 syscall】
        └─ cpu_init()（cpu/common.c:2384）
            └─ syscall_init()
                └─ idt_syscall_init()（同文件:2198）
                    └─ MSR_STAR、MSR_LSTAR(entry_SYSCALL_64)、MSR_SYSCALL_MASK 等
```

**syscall_init()**：

```c
void syscall_init(void)
{
	wrmsr(MSR_STAR, 0, (__USER32_CS << 16) | __KERNEL_CS);
	if (!cpu_feature_enabled(X86_FEATURE_FRED))
		idt_syscall_init();
}
```

**idt_syscall_init()**：

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

#### 系统调用的两种机制：IDT (INT 0x80) vs MSR (SYSCALL/SYSENTER)

Linux 内核支持**两种系统调用机制**，它们的设置阶段和实现方式完全不同：

**1. 基于 IDT 的传统机制：INT 0x80（32位兼容）**

| 特性 | 说明 |
|------|------|
| **原理** | 软件中断，查询 IDT 表第 0x80 个条目 |
| **设置时机** | `init_IRQ()` → `idt_setup_ia32_syscall_gate()`（IDT 演进阶段 5） |
| **设置位置** | `arch/x86/kernel/idt.c` |
| **触发方式** | `int $0x80` 指令 |
| **入口函数** | `entry_INT80_32`（`arch/x86/entry/entry_32.S` 或 `entry_64.S`） |
| **系统调用号** | %eax |
| **参数传递** | %ebx, %ecx, %edx, %esi, %edi, %ebp（32位寄存器） |
| **系统调用表** | `ia32_sys_call_table`（兼容表） |
| **性能** | 慢（需要查 IDT、特权级切换、栈切换） |
| **适用范围** | 32位程序（CONFIG_IA32_EMULATION），64位程序也可用但不推荐 |

**设置代码**（在 `init_IRQ()` 之后）：
```c
// arch/x86/kernel/idt.c
#ifdef CONFIG_IA32_EMULATION
static inline void idt_setup_ia32_syscall_gate(void) {
    idt_setup_from_table(idt_table, &ia32_syscall, 1, true);
    // ia32_syscall = {.vector = IA32_SYSCALL_VECTOR (0x80), .addr = entry_INT80_32}
}
#endif
```

**2. 基于 MSR 的快速机制：SYSCALL/SYSENTER（现代方式）**

| 特性 | SYSCALL（AMD/Intel 64位） | SYSENTER（Intel 32位） |
|------|---------------------------|------------------------|
| **原理** | 专用指令，直接从 MSR 读取入口地址 | 专用指令，从 MSR 读取入口 |
| **设置时机** | `trap_init()` → `cpu_init()` → `syscall_init()`（早于 `init_IRQ()`） |
| **设置位置** | `arch/x86/kernel/cpu/common.c` |
| **MSR 寄存器** | MSR_LSTAR (入口地址)<br>MSR_STAR (段选择子)<br>MSR_SYSCALL_MASK (RFLAGS 掩码) | MSR_IA32_SYSENTER_CS<br>MSR_IA32_SYSENTER_ESP<br>MSR_IA32_SYSENTER_EIP |
| **触发方式** | `syscall` 指令 | `sysenter` 指令 |
| **入口函数** | `entry_SYSCALL_64` | `entry_SYSENTER_compat` |
| **系统调用号** | %rax | %eax |
| **参数传递** | %rdi, %rsi, %rdx, %r10, %r8, %r9（64位寄存器） | %ebx, %ecx, %edx, %esi, %edi, %ebp |
| **系统调用表** | `sys_call_table`（64位原生表） | `ia32_sys_call_table` |
| **性能** | 快（专用硬件支持，无需查表） | 快 |
| **适用范围** | 64位程序（主要使用） | 32位程序（Intel CPU） |

**设置代码**（在 `trap_init()` 中）：
```c
// arch/x86/kernel/cpu/common.c:2234
void syscall_init(void)
{
    // 设置段选择子：用户态 CS/SS、内核态 CS
    wrmsr(MSR_STAR, 0, (__USER32_CS << 16) | __KERNEL_CS);

    if (!cpu_feature_enabled(X86_FEATURE_FRED))
        idt_syscall_init();  // 设置 SYSCALL/SYSENTER 入口
}

static inline void idt_syscall_init(void)
{
    // 64位 SYSCALL 入口
    wrmsrq(MSR_LSTAR, (unsigned long)entry_SYSCALL_64);

    // 32位兼容模式入口（如果启用）
    if (ia32_enabled()) {
        wrmsrq_cstar((unsigned long)entry_SYSCALL_compat);  // CSTAR: 32位 syscall
        wrmsrq_safe(MSR_IA32_SYSENTER_CS, (u64)__KERNEL_CS);
        wrmsrq_safe(MSR_IA32_SYSENTER_ESP, ...);
        wrmsrq_safe(MSR_IA32_SYSENTER_EIP, (u64)entry_SYSENTER_compat);
    }

    // syscall 指令执行时清除的 RFLAGS 位
    wrmsrq(MSR_SYSCALL_MASK, X86_EFLAGS_TF|X86_EFLAGS_DF|...|X86_EFLAGS_AC);
}
```

#### 设置阶段的时间线对比

```
内核启动流程中的系统调用机制设置：

start_kernel()
    │
    ├─ 阶段 2a: trap_init()  ← 第一阶段
    │       └─ cpu_init()
    │           └─ syscall_init()
    │               └─ idt_syscall_init()
    │                   ├─ wrmsr(MSR_STAR) → 设置段选择子
    │                   ├─ wrmsr(MSR_LSTAR, entry_SYSCALL_64) ✨ 64位 syscall 就绪
    │                   ├─ wrmsr(MSR_CSTAR, entry_SYSCALL_compat) → 32位 syscall
    │                   ├─ wrmsr(MSR_IA32_SYSENTER_EIP, entry_SYSENTER_compat) ✨ sysenter 就绪
    │                   └─ wrmsr(MSR_SYSCALL_MASK) → RFLAGS 掩码
    │       【此时 SYSCALL/SYSENTER 机制已可用，但 INT 0x80 尚未就绪】
    │
    ├─ 阶段 2b: early_irq_init()
    │
    ├─ 阶段 2c: init_IRQ()  ← 第二阶段
    │       ├─ idt_setup_traps() → 补全异常向量
    │       ├─ init_8259A() → 重编程 PIC
    │       ├─ idt_setup_apic_and_irq_gates() → 设置 APIC/IRQ 门
    │       └─ idt_setup_ia32_syscall_gate()
    │           └─ idt_table[0x80] = entry_INT80_32 ✨ INT 0x80 就绪
    │       【此时 INT 0x80 机制也可用，所有系统调用机制完全就绪】
    │
    └─ 阶段 2d: local_irq_enable()
```

#### 关键区别与设计考虑

**为什么需要两套机制？**

1. **性能差异**：
   - `INT 0x80`：需要查 IDT 表、特权级检查、栈切换，约 100-300 CPU 周期
   - `SYSCALL`：硬件优化路径，约 60-100 CPU 周期
   - 现代程序优先使用 SYSCALL/SYSENTER

2. **兼容性需求**：
   - `INT 0x80`：古老但通用，所有 x86 CPU 都支持
   - `SYSCALL`：AMD64/Intel 64位特有
   - `SYSENTER`：Intel Pentium II+ 才有
   - 老旧 32位程序仍依赖 `INT 0x80`

3. **设置时机不同**：
   - **MSR 机制（SYSCALL/SYSENTER）**：在 `trap_init()` 中设置，**早于** IDT 的完善
   - **IDT 机制（INT 0x80）**：在 `init_IRQ()` 中设置，作为 IDT 表的一部分
   - 原因：MSR 写入简单（几条 wrmsr），IDT 需要完整的中断框架就绪

4. **是否依赖 IDT**：
   - `SYSCALL/SYSENTER`：**不依赖 IDT**，直接从 MSR 跳转
   - `INT 0x80`：**依赖 IDT**，必须等 IDT 表完善后才能使用

#### 系统调用表的统一与分离

虽然有多种调用机制，但**系统调用表（syscall table）是统一的**：

```c
// arch/x86/entry/syscall_64.c
asmlinkage const sys_call_ptr_t sys_call_table[] = {
    [0] = __x64_sys_read,
    [1] = __x64_sys_write,
    [2] = __x64_sys_open,
    // ... 所有系统调用
};

// arch/x86/entry/syscall_32.c (32位兼容表)
__visible const sys_call_ptr_t ia32_sys_call_table[] = {
    [0] = __ia32_sys_restart_syscall,
    [1] = __ia32_sys_exit,
    // ... 32位系统调用
};
```

**调用路径**：
```
64位程序：
    syscall → entry_SYSCALL_64 → do_syscall_64 → sys_call_table[rax]

32位程序（Intel CPU）：
    sysenter → entry_SYSENTER_compat → do_SYSENTER_32 → ia32_sys_call_table[eax]

32位程序（所有 CPU，兼容路径）：
    int $0x80 → entry_INT80_32 → do_int80_syscall_32 → ia32_sys_call_table[eax]
```

#### 实际运行时如何选择？

**用户空间库（glibc/musl）的选择逻辑**：

```c
// glibc 中的 syscall 封装（简化）
static inline long syscall(long number, ...)
{
#ifdef __x86_64__
    // 64位程序：优先使用 SYSCALL
    asm volatile("syscall" : ...);
#else
    // 32位程序
    #if defined(__i386__) && defined(USE_VSYSCALL)
        // 现代 32位：尝试 sysenter（通过 vDSO）
        return __kernel_vsyscall(...);
    #else
        // 传统 32位：回退到 int $0x80
        asm volatile("int $0x80" : ...);
    #endif
#endif
}
```

#### IDT 与系统调用机制的关联总结

| 对比维度 | IDT 表（中断描述符表） | 系统调用机制 |
|---------|----------------------|-------------|
| **主要用途** | 处理硬件中断和 CPU 异常 | 用户态进入内核态的接口 |
| **设置阶段** | 5 个阶段逐步完善（见第三节） | 2 个阶段：trap_init() 设置 MSR，init_IRQ() 设置 INT 0x80 |
| **INT 0x80 的关系** | INT 0x80 是 IDT[0x80] 的一个条目 | INT 0x80 是系统调用的一种实现方式 |
| **SYSCALL 的关系** | 完全不使用 IDT | SYSCALL 通过 MSR 实现，绕过 IDT |
| **演进时间线** | bringup_idt_table → idt_table（5 阶段） | MSR 机制先就绪 → IDT 机制后就绪 |
| **依赖关系** | 不依赖系统调用机制 | INT 0x80 依赖 IDT 表完善 |

**关键洞察**：
- **trap_init() 阶段**：设置 MSR，让 SYSCALL/SYSENTER 可用（不依赖 IDT）
- **init_IRQ() 阶段**：设置 IDT[0x80]，让 INT 0x80 可用（依赖 IDT 完善）
- 两者相互独立，但共同完成系统调用机制的初始化
- 现代程序主要使用 SYSCALL，INT 0x80 主要用于兼容

**与 IDT 内容的关系**：
- **IDT 表包含三类条目**：
  1. **CPU 异常**（0-31）：#DE, #PF, #GP 等 → idt_setup_early_handler() → idt_setup_traps()
  2. **硬件中断**（32+）：时钟、键盘、网卡等 IRQ → idt_setup_apic_and_irq_gates()
  3. **软件中断**（特定向量）：INT 0x80（32位系统调用兼容）→ idt_setup_ia32_syscall_gate()

- **SYSCALL/SYSENTER 不在 IDT 中**，它们通过 MSR 寄存器配置：
  - MSR_LSTAR：SYSCALL 入口地址（entry_SYSCALL_64）
  - MSR_STAR：段选择子（内核态 CS / 用户态 CS）
  - MSR_SYSCALL_MASK：RFLAGS 掩码（syscall 时清除的标志位）

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

> 运行时中断模型见 [LINUX_INTERRUPT_HANDLING.md](LINUX_INTERRUPT_HANDLING.md)；BIOS IVT 与 Kernel IDT 见 [BIOS_IVT_VS_KERNEL_IDT.md](BIOS_IVT_VS_KERNEL_IDT.md)。

### 4. rest_init() 与 kernel_init()

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

---

## 相关文档

### 启动流程

- **[BOOT_FLOW.md](BOOT_FLOW.md)** - 启动概述
- **[GRUB_KERNEL_LOADING.md](GRUB_KERNEL_LOADING.md)** - GRUB 加载内核详解
- **[GRUB_UEFI_LONG_MODE_ANALYSIS.md](GRUB_UEFI_LONG_MODE_ANALYSIS.md)** - GRUB UEFI 长模式启动分析
- **[UEFI_VS_BIOS_BOOT.md](UEFI_VS_BIOS_BOOT.md)** - UEFI 与 BIOS 引导机制差异
- **[LINUX_KERNEL_SETUP_FLOW.md](LINUX_KERNEL_SETUP_FLOW.md)** - 从扇区 0 启动的 Setup 流程

### 内存管理

- **[PAGING_PHASE1_THEORY_AND_EARLY_TABLES.md](PAGING_PHASE1_THEORY_AND_EARLY_TABLES.md)** - 阶段 1：分页理论与早期页表（startup_32/64）
- **[PAGING_PHASE2_FULL_SETUP_IN_SETUP_ARCH.md](PAGING_PHASE2_FULL_SETUP_IN_SETUP_ARCH.md)** - 阶段 2：setup_arch 完整页表建立（E820、memblock、init_mem_mapping）

### 架构细节

- **[X86_NEAR_VS_LONG_JUMP.md](X86_NEAR_VS_LONG_JUMP.md)** - near/long jump 与 long mode 下 CS 的作用
- **[POSITION_INDEPENDENT_CODE.md](POSITION_INDEPENDENT_CODE.md)** - 位置无关代码（`__pi_` 前缀）实现机制

### 重定位与解压专题

- **[COMPRESSED_KERNEL_RELOCATION.md](COMPRESSED_KERNEL_RELOCATION.md)** - 压缩内核重定位与原地解压详解
- **[SOLUTION_ICACHE_MYSTERY.md](SOLUTION_ICACHE_MYSTERY.md)** - 解压代码为何不被覆盖的完整解答
- **[WHY_RELOCATE_COMPRESSED_KERNEL.md](WHY_RELOCATE_COMPRESSED_KERNEL.md)** - 为什么要重定位压缩内核（KASLR 分析）
- **[INVESTIGATION_SUMMARY.md](INVESTIGATION_SUMMARY.md)** - I-cache 理论验证与调查报告

### 其他相关文档

- **[VMLINUZ_STRUCTURE.md](VMLINUZ_STRUCTURE.md)** - vmlinuz 文件结构分析
- **[INITRAMFS_ANALYSIS.md](INITRAMFS_ANALYSIS.md)** - initramfs 分析
