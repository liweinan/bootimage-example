# Linux 内核 IDT 表的演进流程详解

> **本文档为** [Linux 内核启动与初始化](LINUX_KERNEL_INIT.md) **的子文档**

本文档详细介绍 Linux 内核启动过程中 IDT（中断描述符表）的演进流程，包括两个 IDT 表的切换、5 个演进阶段、以及内核启动过程中的中断状态管理。

**主要内容**：
1. 两个 IDT 表：bringup_idt_table vs idt_table
2. IDT 表的 5 个演进阶段详解
3. GDT 与 IDT 的对比
4. IST（Interrupt Stack Table）机制
5. 内核启动过程的中断状态（IF 标志）
6. 早期 INT vs 完整 INT 对比

**相关文档**：
- [Linux 内核启动与初始化](LINUX_KERNEL_INIT.md) - 主启动流程
- [系统调用初始化](LINUX_KERNEL_SYSCALL_INIT.md) - syscall 初始化详解
- [Linux 中断处理](LINUX_INTERRUPT_HANDLING.md) - 运行时中断处理
- [BIOS IVT vs Kernel IDT](BIOS_IVT_VS_KERNEL_IDT.md) - IVT 与 IDT 对比

---

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

#### 为什么 #VC 是唯一需要的异常？

**关键问题**：既然中断已关闭（IF=0），为什么还要设置 #VC 处理函数？

**答案**：`EFLAGS.IF` 只控制**硬件中断**，不控制**异常**。

**中断 vs 异常的根本区别**：

| 类型 | 触发方式 | 受 IF 控制？ | 示例 |
|------|---------|------------|------|
| **硬件中断** | 异步，外部硬件 | ✅ 是（IF=0 时被屏蔽） | IRQ 0（时钟）、IRQ 1（键盘） |
| **异常** | 同步，当前指令 | ❌ 否（IF=0 时仍会触发） | #PF、#GP、#VC |

**#VC 的特殊性（AMD SEV-SNP 环境）**：

在 SEV-SNP 虚拟化环境中，**CPUID 指令会自动触发 #VC 异常**，用于虚拟机与 Hypervisor 通信：

```c
// arch/x86/kernel/head_64.S
startup_64:
    // ...
    call verify_cpu  // ← 内部执行 CPUID 检测 CPU 特性

    // SEV-SNP 环境下：
    // 1. CPUID 指令 → 自动触发 #VC 异常（向量 29）
    // 2. 即使 IF=0 也会触发（异常不受 IF 控制）
    // 3. CPU 查找 IDT[29]
    // 4. 如果没有处理函数 → Triple Fault → 重启 💥
```

**为什么其他异常不需要？**

| 异常 | 极早期是否可能触发？ | 原因 |
|------|------------------|------|
| **#VC** | ✅ 是（SEV 环境） | `verify_cpu` 等代码会执行 CPUID |
| #PF | ❌ 否 | 页表已建立，内存访问有效 |
| #GP | ❌ 否 | 段选择子正确，特权级正确 |
| #UD | ❌ 否 | 代码都是标准 x86-64 指令 |
| #DF | ❌ 否 | 无嵌套异常场景 |

**#VC 处理函数的简化实现**（`arch/x86/boot/startup/sev-shared.c`）：

```c
void do_vc_no_ghcb(struct pt_regs *regs, unsigned long exit_code)
{
    /* Only CPUID is supported via MSR protocol */
    if (exit_code != SVM_EXIT_CPUID)
        goto fail;  // ← 只处理 CPUID，其他操作直接失败

    // ... 通过 MSR 与 Hypervisor 通信获取 CPUID 结果 ...

    regs->ip += 2;  // ← 跳过 CPUID 指令（2 字节）
    return;

fail:
    sev_es_terminate(...);  // ← 终止虚拟机
}
```

**总结**：#VC 是**唯一**需要在极早期设置的异常，因为：
1. SEV-SNP 环境下 CPUID 必定触发 #VC
2. 启动代码必须执行 CPUID（检测 CPU 特性）
3. 异常不受 `EFLAGS.IF` 控制，即使关中断也会触发
4. 如果没有处理函数，系统无法启动

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
