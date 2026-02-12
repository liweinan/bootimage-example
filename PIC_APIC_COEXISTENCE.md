# PIC 与 APIC 的共存：为什么现代系统仍需初始化 PIC？

## 文档简介

虽然现代 x86 系统都配备了 APIC（Advanced Programmable Interrupt Controller），但 Linux 内核仍然会初始化传统的 8259A PIC。本文档详细解释这一看似矛盾行为背后的深刻技术原因。

**核心问题**：既然已经有 APIC，为什么还要初始化 PIC？

**主要内容**：
- 硬件兼容性原因（Timer IRQ、Mixed Mode）
- ExtINT 级联机制（PIC → APIC LINT0）
- 内核代码依赖（nr_legacy_irqs、has_legacy_pic）
- Legacy PIC 抽象层（default_legacy_pic vs null_legacy_pic）
- Virtual Wire Mode（SMP 启动早期）
- PIC 初始化后被 Mask（初始化 ≠ 使用）

**相关文档**：
- [x86 中断控制器演进：从 8259 PIC 到 APIC](X86_INTERRUPT_CONTROLLER_EVOLUTION.md) - 主文档，PIC 和 APIC 的详细对比
- [Linux 内核初始化](LINUX_KERNEL_INIT.md) - init_IRQ() 调用流程
- [Linux 中断处理](LINUX_INTERRUPT_GUIDE.md) - 运行时中断处理

**Linux Kernel 源码参考**（基于 `/Users/weli/works/linux`）：
- `arch/x86/kernel/irqinit.c:54-112` - init_ISA_irqs(), init_IRQ(), native_init_IRQ()
- `arch/x86/kernel/i8259.c:50-57, 312-318, 345-441` - PIC 初始化和抽象层
- `arch/x86/kernel/apic/io_apic.c:2198-2207` - ExtINT 级联机制
- `arch/x86/kernel/apic/apic.c:1605-1610` - LINT0 ExtINT 配置
- `arch/x86/kernel/acpi/boot.c:1410` - ACPI 切换到 null_legacy_pic
- `arch/x86/kernel/jailhouse.c:219` - Jailhouse 虚拟化

---

### 3.6 PIC 与 APIC 的共存：为什么现代系统仍需初始化 PIC？

虽然现代 x86 系统都配备了 APIC（Advanced Programmable Interrupt Controller），但 Linux 内核仍然会初始化传统的 8259A PIC。这看似矛盾的行为背后有深刻的技术原因。

#### 3.6.1 问题的提出

观察 Linux 内核启动过程，会发现即使系统有 APIC，也会执行 PIC 初始化：

```c
// arch/x86/kernel/irqinit.c:75-112
void __init init_IRQ(void)
{
    int i;

    // 为 ISA IRQ 0-15 分配向量
    for (i = 0; i < nr_legacy_irqs(); i++)
        per_cpu(vector_irq, 0)[ISA_IRQ_VECTOR(i)] = irq_to_desc(i);

    BUG_ON(irq_init_percpu_irqstack(smp_processor_id()));

    x86_init.irqs.intr_init();  // 调用 native_init_IRQ()
}

void __init native_init_IRQ(void)
{
    /* Execute any quirks before the call gates are initialised: */
    x86_init.irqs.pre_vector_init();  // ⭐ 这里会初始化 PIC！

    if (cpu_feature_enabled(X86_FEATURE_FRED))
        fred_complete_exception_setup();
    else
        idt_setup_apic_and_irq_gates();  // 设置 APIC 中断门

    lapic_assign_system_vectors();

    if (!acpi_ioapic && !of_ioapic && nr_legacy_irqs()) {
        /* IRQ2 is cascade interrupt to second interrupt controller */
        if (request_irq(2, no_action, IRQF_NO_THREAD, "cascade", NULL))
            pr_err("%s: request_irq() failed\n", "cascade");
    }
}
```

**疑问**：既然已经有 APIC，为什么 `pre_vector_init()` 还要初始化 PIC？

#### 3.6.2 原因一：硬件兼容性 - Timer IRQ 的特殊情况

**关键代码注释**：

```c
// arch/x86/kernel/i8259.c:50-57
/*
 * Not all IRQs can be routed through the IO-APIC, eg. on certain (older)
 * boards the timer interrupt is not really connected to any IO-APIC pin,
 * it's fed to the master 8259A's IR0 line only.
 *
 * Any '1' bit in this mask means the IRQ is routed through the IO-APIC.
 * this 'mixed mode' IRQ handling costs nothing because it's only used
 * at IRQ setup time.
 */
unsigned long io_apic_irqs;  // Bitmask: '1' = routed through IO-APIC
```

**硬件现实**：
- **某些老旧主板**的 Timer Interrupt（IRQ 0）只连接到 8259A PIC 的 IR0 引脚
- 这些主板的 Timer 并未连接到 IO-APIC 的任何引脚
- 即使系统有 IO-APIC，Timer 中断仍必须通过 PIC 处理

**混合模式（Mixed Mode）**：
```c
// linux/arch/x86/kernel/i8259.c
unsigned long io_apic_irqs;  // Bitmask: '1' = routed through IO-APIC

// 检查某个 IRQ 是否通过 IO-APIC
if (io_apic_irqs & (1 << irq)) {
    // 使用 IO-APIC 处理
} else {
    // 使用 PIC 处理（如 Timer IRQ 0）
}
```

#### 3.6.3 原因二：ExtINT 模式 - PIC 级联到 APIC

**ExtINT（External Interrupt）机制**：

```c
// arch/x86/kernel/apic/io_apic.c:2198-2207
/*
 * This interrupt regardless. The pin may be left unconnected, but
 * typically it will be reused as an ExtINT cascade interrupt for
 * the master 8259A. In the MPS case such a pin will normally be
 * reported as an ExtINT interrupt in the MP table. With ACPI
 * there is no provision for ExtINT interrupts, and in the absence
 * of an override it would be treated as an ordinary ISA I/O APIC
 * interrupt.
 *
 * Some systems make use of an INTA cycle for each local APIC
 * of the NMI watchdog and sometimes IRQ0 of the 8254 timer using
 * the same ExtINT cascade interrupt to drive the local APIC of the
 * bootstrap processor.
 */
```

**ExtINT 工作原理**：

```
传统 ISA 设备（键盘、串口等）
    ↓
8259A PIC（处理 IRQ 0-15）
    ↓ ExtINT 信号
Local APIC LINT0 引脚（接收 ExtINT）
    ↓
CPU 核心
```

**Local APIC 的 ExtINT 配置**：

```c
// arch/x86/kernel/apic/apic.c:1605-1610
if (enabled_via_apicbase) {
    value = APIC_DM_EXTINT;  // ⭐ ExtINT 传递模式
    apic_pr_verbose("Enabled ExtINT on CPU#%d\n", cpu);
} else {
    value = APIC_DM_EXTINT | APIC_LVT_MASKED;
    apic_pr_verbose("Masked ExtINT on CPU#%d\n", cpu);
}
apic_write(APIC_LVT0, value);  // 配置 LINT0 为 ExtINT 模式
```

**为什么需要 ExtINT？**
- 传统 ISA 设备（键盘 IRQ1、串口 IRQ3/IRQ4）只能连接到 PIC
- 在 SMP 系统启动早期，APIC 工作在 **Virtual Wire Mode**
- 此模式下 APIC 通过 ExtINT 从 PIC 接收中断

#### 3.6.4 原因三：内核代码依赖

**Kernel 开发者的坦诚注释**：

```c
// arch/x86/kernel/i8259.c:312-318
/*
 * Right now this causes problems as quite some code depends on
 * nr_legacy_irqs() > 0 or has_legacy_pic() == true. This is silly
 * when the system has an IO/APIC because then PIC is not required
 * at all, except for really old machines where the timer interrupt
 * must be routed through the PIC. So just pretend that the PIC is
 * there and let legacy_pic->init() initialize it for nothing.
 */
if (pcat_compat)
    return nr_legacy_irqs();  // 假装 PIC 存在
```

**代码依赖示例**：

```c
// 许多内核代码检查 legacy PIC 是否存在
if (nr_legacy_irqs() > 0) {
    // 初始化 legacy IRQ 路由
    setup_legacy_irq_routes();
}

if (has_legacy_pic()) {
    // 处理 PIC 级联中断
    setup_cascade_irq();
}
```

**Kernel 开发者也承认**：这很 **silly**，但为了避免大规模代码重构，保留了这个假设。

#### 3.6.5 原因四：Legacy PIC 抽象层

Linux 内核通过 **legacy_pic** 抽象层实现了两种 PIC 模式：

```c
// arch/x86/kernel/i8259.c:415-441
struct legacy_pic null_legacy_pic = {
    .nr_legacy_irqs = 0,          // 无 legacy IRQ
    .chip = &dummy_irq_chip,
    .mask = legacy_pic_uint_noop,
    .unmask = legacy_pic_uint_noop,
    .mask_all = legacy_pic_noop,
    .restore_mask = legacy_pic_noop,
    .init = legacy_pic_int_noop,  // ⭐ 空操作（不初始化）
    .probe = legacy_pic_probe,
    .irq_pending = legacy_pic_irq_pending_noop,
    .make_irq = legacy_pic_uint_noop,
};

struct legacy_pic default_legacy_pic = {
    .nr_legacy_irqs = NR_IRQS_LEGACY,  // 16 个 legacy IRQ
    .chip  = &i8259A_chip,
    .mask  = mask_8259A_irq,
    .unmask = unmask_8259A_irq,
    .mask_all = mask_8259A,
    .restore_mask = unmask_8259A,
    .init  = init_8259A,  // ⭐ 真实初始化 PIC
    .probe = probe_8259A,
    .irq_pending = i8259A_irq_pending,
    .make_irq = make_8259A_irq,
};

// 默认使用真实 PIC
struct legacy_pic *legacy_pic = &default_legacy_pic;
EXPORT_SYMBOL(legacy_pic);
```

**何时切换到 null_legacy_pic？**

```c
// 1. ACPI 表明系统无 PIC（arch/x86/kernel/acpi/boot.c:1410）
if (acpi_madt_has_no_pic()) {
    x86_init.timers.timer_init = x86_init_noop;
    x86_init.irqs.pre_vector_init = x86_init_noop;
    legacy_pic = &null_legacy_pic;  // ⭐ 切换到空 PIC
}

// 2. Jailhouse 虚拟化环境（arch/x86/kernel/jailhouse.c:219）
legacy_pic = &null_legacy_pic;

// 3. Hyper-V 虚拟化环境（arch/x86/kernel/cpu/mshyperv.c:416）
x86_init.irqs.pre_vector_init = x86_init_noop;  // 跳过 PIC 初始化
```

**抽象层的优势**：
- 物理机：使用 `default_legacy_pic` 真实初始化 PIC
- 虚拟机：使用 `null_legacy_pic` 跳过 PIC 初始化（性能优化）
- 代码统一：调用方无需关心底层是真实 PIC 还是虚拟 PIC

#### 3.6.6 原因五：Virtual Wire Mode

**APIC 启动模式演进**：

```c
// arch/x86/kernel/irqinit.c:54-73
void __init init_ISA_irqs(void)
{
    struct irq_chip *chip = legacy_pic->chip;
    int i;

    /*
     * Try to set up the through-local-APIC virtual wire mode earlier.
     *
     * On some 32-bit UP machines, whose APIC has been disabled by BIOS
     * and then got re-enabled by "lapic", it hangs at boot time without this.
     */
    init_bsp_APIC();  // ⭐ 初始化 BSP 的 Local APIC（Virtual Wire Mode）

    legacy_pic->init(0);  // 初始化 PIC（或 noop）

    for (i = 0; i < nr_legacy_irqs(); i++) {
        irq_set_chip_and_handler(i, chip, handle_level_irq);
        irq_set_status_flags(i, IRQ_LEVEL);
    }
}
```

**Virtual Wire Mode 的作用**：

```
启动阶段：
    ┌────────────────────────────────────────────┐
    │  Stage 1: BIOS 阶段                        │
    │  - PIC 处理所有中断                        │
    │  - APIC 未激活                             │
    └────────────────────────────────────────────┘
              ↓
    ┌────────────────────────────────────────────┐
    │  Stage 2: Virtual Wire Mode（内核早期）   │
    │  - Local APIC LINT0 接收 PIC ExtINT        │
    │  - I/O APIC 未初始化                       │
    │  - BSP 通过 PIC 接收中断                   │
    └────────────────────────────────────────────┘
              ↓
    ┌────────────────────────────────────────────┐
    │  Stage 3: Symmetric I/O Mode（多核启动后）│
    │  - I/O APIC 接管所有 IRQ 路由              │
    │  - PIC 被 mask（不再使用）                 │
    │  - 所有 CPU 核心平等接收中断               │
    └────────────────────────────────────────────┘
```

**代码验证**：

```c
// arch/x86/kernel/apic/io_apic.c:1282-1315
static void __init setup_ExtINT_IRQ0_pin(unsigned int apic, unsigned int pin)
{
    struct IO_APIC_route_entry entry;

    // 检查是否已经配置为 ExtINT 模式
    for_each_ioapic_pin(apic, pin) {
        /* See if any of the pins is in ExtINT mode */
        struct IO_APIC_route_entry entry = ioapic_read_entry(apic, pin);

        if (entry.delivery_mode == dest_ExtINT) {
            ioapic_i8259.apic = apic;
            ioapic_i8259.pin  = pin;
            goto found_ext_int;
        }
    }

    /*
     * Look to see what if the MP table has reported the ExtINT
     */
    i8259_pin  = find_isa_irq_pin(0, mp_ExtINT);
    i8259_apic = find_isa_irq_apic(0, mp_ExtINT);

    if ((ioapic_i8259.pin == -1) && (i8259_pin >= 0)) {
        pr_warn("ExtINT not setup in hardware but reported by MP table\n");
        ioapic_i8259.pin  = i8259_pin;
        ioapic_i8259.apic = i8259_apic;
    }

found_ext_int:
    // 配置 ExtINT 引脚连接到 PIC
    // ...
}
```

#### 3.6.7 原因六：PIC 初始化后被 Mask

**关键洞察**：PIC 初始化 ≠ PIC 被使用

```c
// arch/x86/kernel/i8259.c:345-395
static void init_8259A(int auto_eoi)
{
    unsigned long flags;

    i8259A_auto_eoi = auto_eoi;

    raw_spin_lock_irqsave(&i8259A_lock, flags);

    outb(0xff, PIC_MASTER_IMR);  // ⭐ mask 所有主 PIC 中断

    /*
     * outb_pic - this has to work on a wide range of PC hardware.
     */
    outb_pic(0x11, PIC_MASTER_CMD);  /* ICW1: select 8259A-1 init */

    /* ICW2: 8259A-1 IR0-7 mapped to ISA_IRQ_VECTOR(0) */
    outb_pic(ISA_IRQ_VECTOR(0), PIC_MASTER_IMR);

    /* 8259A-1 (the master) has a slave on IR2 */
    outb_pic(1U << PIC_CASCADE_IR, PIC_MASTER_IMR);

    if (auto_eoi)  /* master does Auto EOI */
        outb_pic(MASTER_ICW4_DEFAULT | PIC_ICW4_AEOI, PIC_MASTER_IMR);
    else           /* master expects normal EOI */
        outb_pic(MASTER_ICW4_DEFAULT, PIC_MASTER_IMR);

    // 从 PIC 初始化...
    outb_pic(0x11, PIC_SLAVE_CMD);
    outb_pic(ISA_IRQ_VECTOR(8), PIC_SLAVE_IMR);
    outb_pic(PIC_CASCADE_IR, PIC_SLAVE_IMR);
    outb_pic(SLAVE_ICW4_DEFAULT, PIC_SLAVE_IMR);

    if (auto_eoi)
        i8259A_chip.irq_mask_ack = disable_8259A_irq;
    else
        i8259A_chip.irq_mask_ack = mask_and_ack_8259A;

    udelay(100);  /* wait for 8259A to initialize */

    outb(cached_master_mask, PIC_MASTER_IMR);  // ⭐ 恢复 mask（通常是 0xff）
    outb(cached_slave_mask, PIC_SLAVE_IMR);    // ⭐ 恢复 mask（通常是 0xff）

    raw_spin_unlock_irqrestore(&i8259A_lock, flags);
}
```

**初始化后的状态**：
```c
// 初始化完成后，PIC 的 IMR（Interrupt Mask Register）通常是：
cached_master_mask = 0xFF;  // 所有中断被 mask
cached_slave_mask  = 0xFF;  // 所有中断被 mask
```

**实际效果**：
- PIC 硬件被正确配置（中断向量重映射、级联设置）
- 但所有中断都被 mask，PIC 不会触发任何中断
- I/O APIC 接管实际的中断路由

#### 3.6.8 完整的初始化流程

```c
start_kernel()
  └─ init_IRQ()  // arch/x86/kernel/irqinit.c:75
      └─ x86_init.irqs.intr_init() = native_init_IRQ()  // irqinit.c:95
          ├─ x86_init.irqs.pre_vector_init() = init_ISA_irqs()  // irqinit.c:54
          │   ├─ init_bsp_APIC()  // 初始化 BSP 的 Local APIC（Virtual Wire Mode）
          │   │   └─ 配置 LINT0 为 ExtINT 模式（接收 PIC 级联中断）
          │   │
          │   └─ legacy_pic->init(0)  // 调用 PIC 初始化（或 noop）
          │       ├─ default_legacy_pic.init = init_8259A()  // 物理机
          │       │   ├─ 重映射中断向量（0x08→0x20, 0x70→0x28）
          │       │   ├─ 配置级联（Master IR2 连接 Slave）
          │       │   └─ Mask 所有中断（IMR = 0xFF）
          │       │
          │       └─ null_legacy_pic.init = noop  // 虚拟机（无操作）
          │
          ├─ idt_setup_apic_and_irq_gates()  // 设置 APIC 中断门
          │   ├─ 为 IRQ 32-255 设置 IDT 条目
          │   └─ 配置 I/O APIC RTE（Route Table Entry）
          │
          └─ lapic_assign_system_vectors()  // 分配系统向量（Timer, Error, Spurious）
```

#### 3.6.9 PIC 与 APIC 共存策略总结

| 场景 | PIC 初始化 | PIC 使用 | APIC 状态 | 说明 |
|------|-----------|---------|----------|------|
| **老旧物理机（无 IO-APIC）** | ✅ 真实初始化 | ✅ 使用 | ❌ 未启用 | Timer IRQ 只能通过 PIC |
| **老旧物理机（有 IO-APIC，Timer 连 PIC）** | ✅ 真实初始化 | ⚠️ 部分使用 | ✅ 启用 | Mixed Mode：Timer 走 PIC，其他走 APIC |
| **现代物理机（完整 APIC 支持）** | ✅ 真实初始化 | ❌ 不使用（全部 mask） | ✅ 启用 | 代码兼容性，初始化后立即 mask |
| **虚拟化环境（KVM/Xen/Hyper-V）** | ❌ noop（null_legacy_pic） | ❌ 不使用 | ✅ 启用（虚拟 APIC） | 虚拟机管理器提供虚拟 APIC |
| **Jailhouse 分区虚拟化** | ❌ noop（null_legacy_pic） | ❌ 不使用 | ✅ 启用 | 分区隔离，无需 PIC |

#### 3.6.10 如何判断系统是否使用 PIC？

**方法 1：检查 /proc/interrupts**

```bash
# PIC 模式（所有中断发往 CPU0）
$ cat /proc/interrupts
           CPU0       CPU1       CPU2       CPU3
  0:    1000000          0          0          0   XT-PIC-XT        timer
  1:      10000          0          0          0   XT-PIC-XT        i8042

# APIC 模式（中断可分布到多核）
$ cat /proc/interrupts
           CPU0       CPU1       CPU2       CPU3
  0:    1000000      50000     100000      75000   IO-APIC-edge      timer
  1:      10000       2000       3000       5000   IO-APIC-edge      i8042
```

**方法 2：检查内核启动日志**

```bash
# PIC 模式
$ dmesg | grep -E 'PIC|APIC'
[    0.000000] Using legacy PIC

# APIC 模式
$ dmesg | grep -E 'PIC|APIC'
[    0.000000] Using APIC driver default
[    0.123456] APIC: Switch to symmetric I/O mode setup
[    0.234567] Enabling APIC mode:  Flat. Using 1 I/O APICs
```

**方法 3：检查内核配置**

```bash
$ cat /proc/cmdline
# 如果有 noapic 参数，强制使用 PIC
BOOT_IMAGE=/vmlinuz root=/dev/sda1 noapic

# 如果有 nolapic 参数，禁用 Local APIC
BOOT_IMAGE=/vmlinuz root=/dev/sda1 nolapic
```

#### 3.6.11 为什么不彻底移除 PIC 代码？

**技术债务的三个维度**：

1. **硬件兼容性债务**
   - 10+ 年前的老旧服务器（Timer IRQ 仍连接 PIC）
   - 某些嵌入式 x86 系统（如工控机）仍依赖 PIC
   - BIOS/固件在启动阶段依赖 PIC 中断

2. **软件架构债务**
   ```c
   // 数百处代码依赖 nr_legacy_irqs()
   if (nr_legacy_irqs() > 0) {
       // 初始化 legacy 路由
   }

   // 数百处代码依赖 has_legacy_pic()
   if (has_legacy_pic()) {
       // 处理 PIC 特殊情况
   }
   ```
   **移除成本**：需要重构数百个文件，风险极高

3. **向后兼容债务**
   - 用户可能通过 `noapic` 内核参数强制使用 PIC
   - 某些驱动程序假设 PIC 存在
   - 虚拟化环境（如 QEMU）可能模拟 PIC

**未来趋势**：
- **Intel FRED**（Flexible Return and Event Delivery）架构可能完全移除 PIC 依赖
- **ARM64** 从未有过 PIC，证明现代架构可以不需要 legacy 支持
- **RISC-V** 使用 PLIC（Platform-Level Interrupt Controller），无 PIC 包袱

#### 3.6.12 关键代码索引

| 文件 | 行号 | 功能 |
|------|------|------|
| **arch/x86/kernel/irqinit.c** | 54-73 | init_ISA_irqs() - PIC 和 APIC 初始化入口 |
| **arch/x86/kernel/irqinit.c** | 75-93 | init_IRQ() - 中断系统总入口 |
| **arch/x86/kernel/irqinit.c** | 95-112 | native_init_IRQ() - 调用 pre_vector_init |
| **arch/x86/kernel/i8259.c** | 50-57 | 注释：Mixed Mode（部分 IRQ 走 PIC） |
| **arch/x86/kernel/i8259.c** | 312-318 | 注释：代码依赖 nr_legacy_irqs() |
| **arch/x86/kernel/i8259.c** | 345-395 | init_8259A() - PIC 初始化实现 |
| **arch/x86/kernel/i8259.c** | 415-441 | legacy_pic 抽象层定义 |
| **arch/x86/kernel/apic/io_apic.c** | 2198-2207 | 注释：ExtINT 级联机制 |
| **arch/x86/kernel/apic/apic.c** | 1605-1610 | 配置 LINT0 为 ExtINT 模式 |
| **arch/x86/kernel/acpi/boot.c** | 1410 | ACPI 系统切换到 null_legacy_pic |
| **arch/x86/kernel/jailhouse.c** | 219 | Jailhouse 切换到 null_legacy_pic |

---
