# Linux 内核初始化详解

本文档详细说明 Linux 内核从 `start_kernel()` 开始的初始化过程，包括进程创建、系统调用设置等核心功能的实现。

> **相关文档**：
> - **前置阶段**：关于 GRUB 跳转后的早期启动（Setup 代码、模式切换、startup_64），请参见 [Linux 内核早期启动详细流程](LINUX_KERNEL_EARLY_BOOT.md)
> - 关于启动流程概述，请参见 [boot_flow.md](boot_flow.md)
> - 关于 GRUB 加载内核，请参见 [GRUB_KERNEL_LOADING.md](GRUB_KERNEL_LOADING.md)

## start_kernel() 初始化流程

`start_kernel()` 是 Linux 内核的主入口函数，由架构相关的启动代码（如 x86 的 `x86_64_start_kernel`）调用。

**源代码位置：** `linux/init/main.c:898-1111`

### 流程概述

```
start_kernel()（linux/init/main.c:898-1111）
    ├─ 阶段 1: 早期初始化（中断禁用）
    │   ├─ set_task_stack_end_magic()    // 设置栈保护
    │   ├─ smp_setup_processor_id()      // 设置 CPU ID
    │   ├─ cgroup_init_early()           // 早期 cgroup 初始化
    │   ├─ local_irq_disable()           // 确保中断禁用
    │   ├─ boot_cpu_init()               // 启动 CPU 初始化
    │   ├─ page_address_init()           // 页地址初始化
    │   ├─ setup_arch(&command_line)     // 架构相关设置（x86 特定）
    │   ├─ setup_command_line()          // 解析内核命令行
    │   ├─ setup_per_cpu_areas()         // 设置 per-CPU 数据区
    │   └─ parse_early_param()           // 解析早期参数
    │
    ├─ 阶段 2: 核心子系统初始化
    │   ├─ mm_core_init()                // 内存管理核心初始化
    │   ├─ sched_init()                  // 调度器初始化
    │   ├─ early_irq_init()              // 早期中断初始化
    │   ├─ init_IRQ()                    // 中断控制器初始化
    │   ├─ tick_init()                   // 时钟节拍初始化
    │   ├─ timers_init()                 // 定时器初始化
    │   ├─ hrtimers_init()               // 高精度定时器初始化
    │   ├─ softirq_init()                // 软中断初始化
    │   ├─ timekeeping_init()            // 时间记录初始化
    │   └─ local_irq_enable()            // ⚠️ 启用中断
    │
    ├─ 阶段 3: 设备和文件系统初始化
    │   ├─ console_init()                // 控制台初始化
    │   ├─ vfs_caches_init()             // VFS 缓存初始化
    │   ├─ fork_init()                   // 进程创建初始化
    │   ├─ proc_root_init()              // /proc 文件系统初始化
    │   ├─ cgroup_init()                 // cgroup 完整初始化
    │   └─ acpi_subsystem_init()         // ACPI 子系统初始化
    │
    └─ 阶段 4: 创建 init 进程
        └─ rest_init()                   // 启动用户空间
            ↓
rest_init()（linux/init/main.c:699-746）
    ├─ user_mode_thread(kernel_init, ...)  // 创建 PID 1 进程
    ├─ kernel_thread(kthreadd, ...)        // 创建 PID 2（kthreadd）
    └─ cpu_startup_entry(CPUHP_ONLINE)     // 当前 CPU 进入 idle 循环
            ↓
kernel_init()（linux/init/main.c:1465-1528）
    ├─ wait_for_completion(&kthreadd_done) // 等待 kthreadd 就绪
    ├─ kernel_init_freeable()              // 执行各种 initcall
    ├─ free_initmem()                      // 释放 __init 内存
    ├─ system_state = SYSTEM_RUNNING       // 系统进入运行状态
    │
    └─ 执行 init 进程：
        ├─ 1. run_init_process("/init")        // 优先执行 ramdisk 中的 /init
        ├─ 2. run_init_process(execute_command) // 或 init= 参数指定的程序
        ├─ 3. run_init_process("/sbin/init")   // 或标准 init
        ├─ 4. run_init_process("/etc/init")
        ├─ 5. run_init_process("/bin/init")
        └─ 6. run_init_process("/bin/sh")      // 最后尝试 shell
```

### start_kernel() 关键代码

```c
// linux/init/main.c:898-1111
void start_kernel(void)
{
    // === 阶段 1: 早期初始化（中断禁用）===
    set_task_stack_end_magic(&init_task);  // 设置 init_task 的栈保护
    smp_setup_processor_id();               // 设置当前 CPU ID
    local_irq_disable();                    // 确保中断禁用
    early_boot_irqs_disabled = true;

    boot_cpu_init();                        // 标记启动 CPU 为在线状态
    setup_arch(&command_line);              // ⚠️ 关键：架构相关初始化
    setup_command_line(command_line);       // 保存内核命令行
    parse_early_param();                    // 解析早期参数（如 console=）
    
    // === 阶段 2: 核心子系统初始化 ===
    mm_core_init();                         // 内存管理初始化
    sched_init();                           // ⚠️ 调度器初始化（此后可以调度）
    
    early_irq_init();                       // 早期中断初始化
    init_IRQ();                             // 中断控制器初始化（8259A/APIC）
    tick_init();                            // 时钟节拍初始化
    timekeeping_init();                     // 时间记录初始化
    
    local_irq_enable();                     // ⚠️ 关键：启用中断
    early_boot_irqs_disabled = false;
    
    // === 阶段 3: 设备和文件系统初始化 ===
    console_init();                         // 控制台初始化（可以输出了）
    vfs_caches_init();                      // VFS 缓存初始化
    fork_init();                            // 进程创建初始化
    
    // === 阶段 4: 创建 init 进程 ===
    rest_init();                            // ⚠️ 关键：启动用户空间
}
```

### rest_init() 代码分析

```c
// linux/init/main.c:699-746
static noinline void __ref __noreturn rest_init(void)
{
    int pid;
    
    // ⚠️ 创建 init 进程（PID 1）
    // kernel_init 是 init 进程的入口函数
    pid = user_mode_thread(kernel_init, NULL, CLONE_FS);
    
    // 创建 kthreadd（PID 2）
    // kthreadd 是所有内核线程的父进程
    pid = kernel_thread(kthreadd, NULL, NULL, CLONE_FS | CLONE_FILES);
    
    // 通知 kernel_init 可以继续了
    complete(&kthreadd_done);
    
    // 当前进程（PID 0，swapper）进入 idle 循环
    // 这是 CPU 空闲时执行的代码
    cpu_startup_entry(CPUHP_ONLINE);
}
```

### kernel_init() 执行 init 进程

```c
// linux/init/main.c:1465-1528
static int __ref kernel_init(void *unused)
{
    // 等待 kthreadd 就绪
    wait_for_completion(&kthreadd_done);
    
    // 执行各种 initcall（驱动初始化等）
    kernel_init_freeable();
    
    // 释放 __init 内存（不再需要）
    free_initmem();
    
    // 系统进入运行状态
    system_state = SYSTEM_RUNNING;
    
    // ⚠️ 关键：执行用户空间 init 进程
    // ramdisk_execute_command 默认为 "/init"
    if (ramdisk_execute_command) {
        ret = run_init_process(ramdisk_execute_command);  // 优先执行 /init
        if (!ret)
            return 0;
    }
    
    // 如果 /init 不存在，尝试其他路径
    if (execute_command) {
        ret = run_init_process(execute_command);  // init= 参数指定的程序
        if (!ret)
            return 0;
    }
    
    // 最后尝试标准路径
    if (!try_to_run_init_process("/sbin/init") ||
        !try_to_run_init_process("/etc/init") ||
        !try_to_run_init_process("/bin/init") ||
        !try_to_run_init_process("/bin/sh"))
        return 0;
    
    panic("No working init found.");
}
```

## 核心进程详解

### 进程关系图

```
start_kernel() [PID 0: swapper/idle]
    │
    └─ rest_init()
        ├─ user_mode_thread(kernel_init) ──→ [PID 1: init]
        │                                        │
        │                                        └─ execve("/init") ──→ 用户空间 init
        │
        ├─ kernel_thread(kthreadd) ──────→ [PID 2: kthreadd]
        │                                        │
        │                                        └─ 管理所有内核线程
        │
        └─ cpu_startup_entry() ──────────→ [PID 0 进入 idle 循环]
```

### PID 0（swapper/idle 进程）

PID 0 是**系统中唯一静态定义的进程**，也是所有进程的最终祖先。

**1. 静态定义（`linux/init/init_task.c:66-224`）：**

```c
// PID 0 是在编译时静态定义的，不是动态创建的
struct task_struct init_task __aligned(L1_CACHE_BYTES) = {
    .__state        = 0,
    .stack          = init_stack,           // 静态分配的栈
    .flags          = PF_KTHREAD,           // 内核线程标志
    .prio           = MAX_PRIO - 20,        // 最低优先级
    .policy         = SCHED_NORMAL,
    .mm             = NULL,                  // 无用户空间内存
    .active_mm      = &init_mm,             // 使用内核内存映射
    .real_parent    = &init_task,           // 父进程是自己
    .parent         = &init_task,
    .group_leader   = &init_task,
    .comm           = INIT_TASK_COMM,       // 进程名 "swapper"
    .thread_pid     = &init_struct_pid,     // PID = 0
    // ... 更多初始化 ...
};
EXPORT_SYMBOL(init_task);
```

**2. 进入 idle 循环（`linux/kernel/sched/idle.c:417-424`）：**

```c
// rest_init() 最后调用此函数，PID 0 进入永久的 idle 循环
void cpu_startup_entry(enum cpuhp_state state)
{
    current->flags |= PF_IDLE;      // 标记为 idle 进程
    arch_cpu_idle_prepare();        // 架构相关准备
    cpuhp_online_idle(state);       // CPU 热插拔处理
    while (1)
        do_idle();                  // ⚠️ 永久循环
}
```

**3. idle 循环实现（`linux/kernel/sched/idle.c:252-360`）：**

```c
static void do_idle(void)
{
    // 检查是否需要调度其他进程
    while (!need_resched()) {
        local_irq_disable();        // 禁用中断
        
        // CPU 进入低功耗状态
        if (cpu_idle_force_poll || tick_check_broadcast_expired()) {
            cpu_idle_poll();        // 轮询模式（忙等待）
        } else {
            cpuidle_idle_call();    // ⚠️ 执行 CPU 休眠指令（如 hlt、mwait）
        }
    }
    
    // 有进程需要运行，退出 idle，调度其他进程
    preempt_set_need_resched();
    tick_nohz_idle_exit();
    // 调度器会切换到需要运行的进程
}
```

**职责：**

| 职责 | 说明 |
|------|------|
| **系统启动** | 执行 `start_kernel()` 和 `rest_init()`，创建 PID 1 和 PID 2 |
| **CPU 空闲处理** | 当没有进程需要运行时，执行 idle 循环 |
| **节能** | 调用 CPU 休眠指令（`hlt`、`mwait`），降低功耗 |
| **每 CPU 一个** | 多核系统中，每个 CPU 都有一个 idle 进程（swapper/0, swapper/1, ...） |

**多核系统的 idle 进程：**

```
CPU 0: swapper/0 (PID 0)    ← 启动 CPU，执行 start_kernel()
CPU 1: swapper/1            ← 由 CPU 0 创建
CPU 2: swapper/2            ← 由 CPU 0 创建
...
```

**PID 0 的特殊性：**

1. **静态定义**：唯一在编译时定义的进程，不是 `fork()` 创建的
2. **无法被杀死**：永远存在，是调度器的基础
3. **最低优先级**：只在没有其他进程运行时才执行
4. **无用户空间**：`mm = NULL`，永远在内核态运行

### PID 1（init 进程）

init 进程是所有**用户空间进程的祖先**：

```
kernel_init()
    ↓
execve("/init") 或 execve("/sbin/init")
    ↓
成为用户空间的 init 进程（systemd / SysVinit / OpenRC 等）
```

**职责：**
- 系统的第一个用户空间进程
- 所有用户进程的祖先（直接或间接）
- **孤儿进程收养**：当父进程退出后，子进程被 init 收养
- **僵尸进程回收**：调用 `wait()` 回收孤儿僵尸进程
- 系统关机/重启时负责终止所有进程
- **特殊保护**：PID 1 不能被 `kill -9` 杀死

### PID 2（kthreadd）

kthreadd 是所有**内核线程的父进程**（内核线程工厂）：

```c
// linux/kernel/kthread.c:818-855
int kthreadd(void *unused)
{
    for (;;) {
        // 等待内核线程创建请求
        if (list_empty(&kthread_create_list))
            schedule();
        
        // 处理创建请求
        while (!list_empty(&kthread_create_list)) {
            create = list_entry(kthread_create_list.next, ...);
            create_kthread(create);  // 创建新的内核线程
        }
    }
}
```

**职责：**
- **内核线程工厂**：所有 `kthread_create()` 请求都由它处理
- 提供干净的执行上下文给子线程
- 管理内核线程的生命周期

**常见的内核线程（kthreadd 的子进程）：**

| 线程名 | 作用 |
|--------|------|
| `kworker/*` | 工作队列处理（异步任务执行） |
| `ksoftirqd/*` | 软中断处理（网络、块设备等） |
| `migration/*` | CPU 迁移（进程在 CPU 间移动） |
| `watchdog/*` | 看门狗（检测 CPU 死锁） |
| `kswapd*` | 内存交换（swap） |
| `kblockd` | 块设备 I/O |
| `irq/*` | 线程化中断处理 |

### 完整进程层次结构

```
[PID 0: swapper/idle] ← 内核启动进程，进入 idle 循环
    │
    ├─ [PID 1: init] ← 用户空间进程的祖先
    │   ├─ systemd（或其他 init 系统）
    │   │   ├─ sshd
    │   │   ├─ nginx
    │   │   └─ ...所有用户进程
    │   └─ 孤儿进程（父进程退出后被收养）
    │
    └─ [PID 2: kthreadd] ← 内核线程的父进程
        ├─ [kworker/0:0]
        ├─ [kworker/1:0]
        ├─ [ksoftirqd/0]
        ├─ [migration/0]
        ├─ [watchdog/0]
        ├─ [kswapd0]
        └─ ...所有内核线程
```

**为什么分开 PID 1 和 PID 2？**

1. **隔离性**：用户空间进程和内核线程分开管理
2. **安全性**：PID 1 有特殊保护，内核线程不需要这种保护
3. **清晰的层次**：便于调试和监控（`ps` 命令可以清晰看到进程归属）

## 系统调用初始化

系统调用是用户空间程序与内核交互的主要方式。在 x86_64 上，系统调用通过 `syscall` 指令实现。

### syscall 初始化流程

系统调用在 CPU 初始化阶段设置，由 `setup_arch()` → `cpu_init()` 调用链完成。

**调用链：**

```
start_kernel()
    ↓
setup_arch(&command_line)
    ↓
... (CPU 初始化)
    ↓
cpu_init()                      [arch/x86/kernel/cpu/common.c:2380]
    ↓
syscall_init()                  [arch/x86/kernel/cpu/common.c:2234]
    ↓
idt_syscall_init()              [arch/x86/kernel/cpu/common.c:2198]
```

### syscall_init() 源代码分析

**源代码位置：** `linux/arch/x86/kernel/cpu/common.c:2234-2248`

```c
// 系统调用初始化（每个 CPU 都会调用）
void syscall_init(void)
{
    // 设置 MSR_STAR 寄存器
    // 高 16 位：用户态返回时使用的段选择子（__USER32_CS）
    // 低 16 位：内核态使用的段选择子（__KERNEL_CS）
    wrmsr(MSR_STAR, 0, (__USER32_CS << 16) | __KERNEL_CS);

    // 如果不是 FRED（Flexible Return and Event Delivery）模式
    // 则设置传统的 syscall/sysenter MSR
    if (!cpu_feature_enabled(X86_FEATURE_FRED))
        idt_syscall_init();
}
```

### idt_syscall_init() 源代码分析

**源代码位置：** `linux/arch/x86/kernel/cpu/common.c:2198-2231`

```c
static inline void idt_syscall_init(void)
{
    // ⚠️ 关键：设置 64 位系统调用入口点
    // MSR_LSTAR 保存 syscall 指令跳转的目标地址
    wrmsrq(MSR_LSTAR, (unsigned long)entry_SYSCALL_64);

    // 32 位兼容模式的系统调用
    if (ia32_enabled()) {
        // CSTAR: 兼容模式 syscall 入口点
        wrmsrq_cstar((unsigned long)entry_SYSCALL_compat);
        
        // SYSENTER 相关 MSR（仅 Intel CPU 使用）
        wrmsrq_safe(MSR_IA32_SYSENTER_CS, (u64)__KERNEL_CS);
        wrmsrq_safe(MSR_IA32_SYSENTER_ESP,
                    (unsigned long)(cpu_entry_stack(smp_processor_id()) + 1));
        wrmsrq_safe(MSR_IA32_SYSENTER_EIP, (u64)entry_SYSENTER_compat);
    } else {
        // 禁用 32 位兼容模式
        wrmsrq_cstar((unsigned long)entry_SYSCALL32_ignore);
        wrmsrq_safe(MSR_IA32_SYSENTER_CS, (u64)GDT_ENTRY_INVALID_SEG);
        wrmsrq_safe(MSR_IA32_SYSENTER_ESP, 0ULL);
        wrmsrq_safe(MSR_IA32_SYSENTER_EIP, 0ULL);
    }

    // ⚠️ 设置 syscall 时清除的标志位
    // 进入内核时自动清除这些标志，提高安全性
    wrmsrq(MSR_SYSCALL_MASK,
           X86_EFLAGS_CF|X86_EFLAGS_PF|X86_EFLAGS_AF|
           X86_EFLAGS_ZF|X86_EFLAGS_SF|X86_EFLAGS_TF|
           X86_EFLAGS_IF|X86_EFLAGS_DF|X86_EFLAGS_OF|
           X86_EFLAGS_IOPL|X86_EFLAGS_NT|X86_EFLAGS_RF|
           X86_EFLAGS_AC|X86_EFLAGS_ID);
}
```

### 关键 MSR 寄存器

| MSR 寄存器 | 作用 |
|-----------|------|
| `MSR_STAR` | syscall/sysret 使用的段选择子 |
| `MSR_LSTAR` | **64 位 syscall 入口点地址**（`entry_SYSCALL_64`） |
| `MSR_CSTAR` | 32 位兼容模式 syscall 入口点 |
| `MSR_SYSCALL_MASK` | syscall 时自动清除的 EFLAGS 位 |
| `MSR_IA32_SYSENTER_*` | SYSENTER 指令使用的 MSR（Intel 特有） |

### entry_SYSCALL_64 入口点

**源代码位置：** `linux/arch/x86/entry/entry_64.S:87-137`

```asm
SYM_CODE_START(entry_SYSCALL_64)
    ENDBR
    
    swapgs                              ; 切换 GS 段（用户 GS ↔ 内核 GS）
    movq    %rsp, PER_CPU_VAR(...)      ; 保存用户栈指针
    SWITCH_TO_KERNEL_CR3                ; 切换到内核页表（KPTI）
    movq    PER_CPU_VAR(cpu_current_top_of_stack), %rsp  ; 切换到内核栈
    
    ; 构建 pt_regs 结构（保存用户态寄存器）
    pushq   $__USER_DS                  ; pt_regs->ss
    pushq   用户栈指针                   ; pt_regs->sp
    pushq   %r11                        ; pt_regs->flags（syscall 保存在 r11）
    pushq   $__USER_CS                  ; pt_regs->cs
    pushq   %rcx                        ; pt_regs->ip（syscall 保存在 rcx）
    pushq   %rax                        ; pt_regs->orig_ax（系统调用号）
    
    PUSH_AND_CLEAR_REGS                 ; 保存其他寄存器
    
    movq    %rsp, %rdi                  ; 第一个参数：pt_regs 指针
    movslq  %eax, %rsi                  ; 第二个参数：系统调用号
    
    call    do_syscall_64               ; ⚠️ 调用 C 函数处理系统调用
    
    ; 返回用户空间
    ; 尝试使用 SYSRET（快速路径），否则使用 IRET
    ...
SYM_CODE_END(entry_SYSCALL_64)
```

### 系统调用处理流程

```
用户空间程序调用 syscall 指令
    │
    ├─ CPU 自动执行：
    │   ├─ RCX = 下一条指令地址（返回地址）
    │   ├─ R11 = RFLAGS
    │   ├─ RFLAGS &= ~MSR_SYSCALL_MASK（清除指定标志）
    │   ├─ CS = __KERNEL_CS（从 MSR_STAR 读取）
    │   └─ RIP = MSR_LSTAR（跳转到 entry_SYSCALL_64）
    │
    ↓
entry_SYSCALL_64（汇编入口）
    ├─ swapgs                           ; 切换到内核 GS
    ├─ 保存用户态寄存器到 pt_regs
    └─ call do_syscall_64
            ↓
do_syscall_64()（C 函数）
    ├─ 从系统调用表查找处理函数
    │   sys_call_table[syscall_nr]
    ├─ 调用对应的 sys_xxx() 函数
    └─ 返回结果
            ↓
entry_SYSCALL_64（返回路径）
    ├─ 恢复用户态寄存器
    ├─ swapgs                           ; 切换回用户 GS
    └─ sysret 或 iret                   ; 返回用户空间
            ↓
用户空间程序继续执行
```

### 系统调用表

**源代码位置：** `linux/arch/x86/entry/syscall_64.c`

```c
// 系统调用表定义
const sys_call_ptr_t sys_call_table[] = {
    [0]   = sys_read,
    [1]   = sys_write,
    [2]   = sys_open,
    [3]   = sys_close,
    // ... 更多系统调用
};
```

系统调用号定义在 `linux/arch/x86/include/generated/uapi/asm/unistd_64.h`。

### 系统调用示例

以 `write()` 系统调用为例：

```
用户程序：write(fd, buf, count)
    │
    ├─ glibc 包装函数
    │   ├─ RAX = 1（write 的系统调用号）
    │   ├─ RDI = fd
    │   ├─ RSI = buf
    │   ├─ RDX = count
    │   └─ syscall 指令
    │
    ↓
entry_SYSCALL_64
    ↓
do_syscall_64(regs, 1)
    ↓
sys_call_table[1] = sys_write
    ↓
sys_write(fd, buf, count)
    ↓
内核执行写操作
    ↓
返回写入的字节数（RAX）
    ↓
sysret 返回用户空间
```

## 相关文档

- [boot_flow.md](boot_flow.md) - 完整启动流程概述
- [GRUB_KERNEL_LOADING.md](GRUB_KERNEL_LOADING.md) - GRUB 加载内核详解
- [VMLINUZ_STRUCTURE.md](VMLINUZ_STRUCTURE.md) - vmlinuz 文件结构分析
- [INITRAMFS_ANALYSIS.md](INITRAMFS_ANALYSIS.md) - initramfs 分析
