# IDT 完整向量表参考手册（256 个向量）

**版本**: 1.0
**日期**: 2026-02-17
**作者**: Linux 内核启动文档项目

> 📚 **文档导航**: [返回总索引](DOCUMENT_INDEX.md) | [返回主文档](IDT_SETUP_EARLY_HANDLER_DETAILED_ANALYSIS.md)

---

## 文档说明

本文档是 `idt_table[256]` 数组的**完整参考手册**，列出内核在各个初始化阶段填充的所有 256 个中断/异常向量的详细信息。

**用途**：
- 📖 查询任意向量号对应的处理程序
- 🔍 了解不同向量的门类型、DPL、IST 配置
- 📊 理解 IDT 的分阶段初始化过程

**相关文档**：
- [IDT_SETUP_EARLY_HANDLER_DETAILED_ANALYSIS.md](IDT_SETUP_EARLY_HANDLER_DETAILED_ANALYSIS.md) - 主文档，学习 IDT 初始化流程
- [IDT_DATA_STRUCTURES_RELATIONSHIP.md](IDT_DATA_STRUCTURES_RELATIONSHIP.md) - 数据结构关系详解

---

## 目录

1. [初始化阶段时间线](#初始化阶段时间线)
2. [为什么前 32 个向量要填充两次？](#为什么前-32-个向量要填充两次)
3. [完整向量表](#完整向量表)
4. [关键特性对比](#关键特性对比)
5. [数据结构示例](#数据结构示例)
6. [源代码引用](#源代码引用)

---

## 初始化阶段时间线

**重要说明**：`idt_setup_early_handler()` 只是 IDT 初始化的**第一步**，后续还有多个阶段会继续填充和覆盖 idt_table 的内容。

```
阶段 0：编译后状态
  idt_table[0..255] = 全部为 0（BSS 段）

阶段 1：idt_setup_early_handler() [最早期，x86_64_start_kernel]
  └─ 填充向量 0-31 → early_idt_handler_array[0..31]

阶段 2：idt_setup_early_traps() [trap_init() 开始]
  └─ 覆盖部分向量：#DB(1), #BP(3), #PF(14, 仅 x86-32), #VE(20)

阶段 3：idt_setup_early_pf() [仅 x86-64]
  └─ 覆盖向量 14 (#PF) → asm_exc_page_fault

阶段 4：idt_setup_traps() [trap_init() 中期]
  └─ 覆盖所有异常向量（0-31）+ INT 0x80

阶段 5：idt_setup_apic_and_irq_gates() [trap_init() 完成]
  └─ 填充向量 32-255（IRQ、APIC、系统向量）
```

---

## 为什么前 32 个向量要填充两次？

### 阶段 1 vs 阶段 4 的关键区别

| 对比项 | 阶段 1：idt_setup_early_handler() | 阶段 4：idt_setup_traps() |
|--------|----------------------------------|--------------------------|
| **调用时机** | 极早期（x86_64_start_kernel） | trap_init()（cpu_init() 之后） |
| **处理程序** | early_idt_handler_array[] | 各异常专用处理程序（asm_exc_*） |
| **处理方式** | 所有异常 → early_idt_handler_common | 每个异常有独立处理程序 |
| **IST 支持** | ❌ 不支持（TSS 未初始化） | ✅ 支持（#DF, #NMI, #MC 等使用 IST） |
| **功能** | 临时应急，仅支持基本异常处理 | 完整功能，支持复杂异常处理 |
| **主要目的** | 处理 #PF 用于早期页表建立 | 正式的生产环境异常处理 |

### 为什么需要两次？

**1. 阶段 1：临时应急（"保命"）**

- **时间点**：内核刚启动，很多子系统还未初始化
- **限制条件**：
  - TSS（Task State Segment）未建立 → 无法使用 IST
  - Per-CPU 数据结构未准备好
  - 只能使用默认内核栈
- **关键需求**：必须能处理 #PF（缺页异常）
  - 早期页表是动态建立的
  - 访问未映射的内存 → #PF → early_make_pgtable() 建立映射
- **处理程序特点**：
  ```c
  // 所有异常都跳转到这里
  early_idt_handler_common:
      保存寄存器
      调用 do_early_exception(regs, trapnr)
      恢复寄存器
      iret

  do_early_exception():
      if (trapnr == #PF)
          early_make_pgtable()  // 动态建立页表
      else
          early_fixup_exception() // 或 panic
  ```

**2. 阶段 4：正式上岗（"完整功能"）**

- **时间点**：cpu_init() 完成后，TSS、IST 都已设置好
- **完整功能**：
  - 可以使用 IST（Interrupt Stack Table）
  - 每个异常有专门的处理程序
  - 支持复杂的错误恢复、信号传递、调试等
- **关键改进**：
  ```c
  // 每个异常有独立入口
  asm_exc_page_fault:      // #PF 专用处理
      PUSH_AND_CLEAR_REGS
      call exc_page_fault   // C 函数
          handle_page_fault()
          do_user_addr_fault()
          ...复杂的页错误处理...
      POP_REGS
      iret

  asm_exc_double_fault:    // #DF 使用 IST3
      使用独立的 IST 栈（防止栈溢出导致的双重错误）
      call exc_double_fault
          panic("Double Fault")

  asm_exc_nmi:             // #NMI 使用 IST2
      使用独立的 IST 栈（防止被中断打断）
      call exc_nmi
          ...NMI 处理...
  ```

### 渐进式初始化的必要性

```
内核启动早期状态：
  ✅ 基本 C 运行环境（栈、BSS 段）
  ✅ early_idt_handler_array 汇编代码
  ❌ TSS 未初始化
  ❌ IST 不可用
  ❌ Per-CPU 数据未准备
  ❌ 异常处理子系统未初始化

         ↓ idt_setup_early_handler()
         ↓ 使用简单处理程序
         ↓
         ↓ 内核继续初始化...
         ↓ cpu_init() 设置 TSS/IST
         ↓ 各种子系统初始化
         ↓
         ↓ idt_setup_traps()
         ↓ 切换到完整处理程序

trap_init() 完成后：
  ✅ TSS 已初始化
  ✅ IST 栈已设置
  ✅ Per-CPU 数据已准备
  ✅ 异常处理子系统已就绪
  ✅ 可以使用复杂的异常处理逻辑
```

### 代码证据

```c
// arch/x86/kernel/head64.c
void __init x86_64_start_kernel(char *real_mode_data)
{
    // 极早期：只有基本环境
    kasan_early_init();
    __native_tlb_flush_global(...);

    idt_setup_early_handler();  // ← 阶段 1：临时应急

    // 此时 TSS 还未初始化，不能使用 IST！
    tdx_early_init();
    copy_bootdata(__va(real_mode_data));
    // ... 继续初始化 ...
}

// arch/x86/kernel/traps.c
void __init trap_init(void)
{
    // 此时已经过了 cpu_init()，TSS/IST 已设置好

    idt_setup_traps();  // ← 阶段 4：正式上岗

    // 替换所有异常向量，使用完整功能处理程序
    // 现在可以安全地使用 IST 了

    idt_setup_apic_and_irq_gates();
    // ...
}
```

**总结**：这是典型的"先有鸡还是先有蛋"问题的解决方案——渐进式初始化：
1. 先用简单的处理程序"保命"（处理必需的 #PF）
2. 等环境准备好后，换上完整功能的处理程序

---

## 完整向量表

### 向量 0-31：CPU 异常（最终由 idt_setup_traps 设置）

| 向量 | 助记符 | 异常名称 | 处理程序 | 门类型 | IST | DPL |
|------|-------|---------|---------|--------|-----|-----|
| 0 | #DE | Divide Error | `asm_exc_divide_error` | INT | 0 | 0 |
| 1 | #DB | Debug | `asm_exc_debug` | INT | IST1 | 0 |
| 2 | #NMI | NMI | `asm_exc_nmi` | INT | IST2 | 0 |
| 3 | #BP | Breakpoint | `asm_exc_int3` | INT | 0 | **3** |
| 4 | #OF | Overflow | `asm_exc_overflow` | INT | 0 | **3** |
| 5 | #BR | Bound Range | `asm_exc_bounds` | INT | 0 | 0 |
| 6 | #UD | Invalid Opcode | `asm_exc_invalid_op` | INT | 0 | 0 |
| 7 | #NM | Device Not Available | `asm_exc_device_not_available` | INT | 0 | 0 |
| 8 | #DF | Double Fault | `asm_exc_double_fault` (64位) / TSS (32位) | INT/TASK | IST3 | 0 |
| 9 | - | Coprocessor Overrun | `asm_exc_coproc_segment_overrun` | INT | 0 | 0 |
| 10 | #TS | Invalid TSS | `asm_exc_invalid_tss` | INT | 0 | 0 |
| 11 | #NP | Segment Not Present | `asm_exc_segment_not_present` | INT | 0 | 0 |
| 12 | #SS | Stack Fault | `asm_exc_stack_segment` | INT | 0 | 0 |
| 13 | #GP | General Protection | `asm_exc_general_protection` | INT | 0 | 0 |
| 14 | #PF | Page Fault | `asm_exc_page_fault` | INT | 0 | 0 |
| 15 | - | Spurious | `asm_exc_spurious_interrupt_bug` | INT | 0 | 0 |
| 16 | #MF | x87 FPU Error | `asm_exc_coprocessor_error` | INT | 0 | 0 |
| 17 | #AC | Alignment Check | `asm_exc_alignment_check` | INT | 0 | 0 |
| 18 | #MC | Machine Check | `asm_exc_machine_check` | INT | IST4 | 0 |
| 19 | #XF | SIMD Exception | `asm_exc_simd_coprocessor_error` | INT | 0 | 0 |
| 20 | #VE | Virtualization | `asm_exc_virtualization_exception` | INT | 0 | 0 |
| 21 | #CP | Control Protection | `asm_exc_control_protection` | INT | 0 | 0 |
| 22-28 | - | Reserved | (未使用) | - | - | - |
| 29 | #VC | VMM Communication | `asm_exc_vmm_communication` | INT | IST5 | 0 |
| 30 | - | Reserved | (未使用) | - | - | - |
| 31 | - | Reserved | (未使用) | - | - | - |

### 向量 32-127：设备中断（由 idt_setup_apic_and_irq_gates 设置）

| 向量范围 | 用途 | 处理程序 | 说明 |
|---------|------|---------|------|
| 32 (0x20) | IRQ 0 起始 | `irq_entries_start + 0` | 8259A PIC IRQ 0 |
| 33-47 | IRQ 1-15 | `irq_entries_start + n*IDT_ALIGN` | 传统 ISA IRQ |
| 48-127 | 扩展 IRQ | `irq_entries_start + n*IDT_ALIGN` | PCI/MSI 中断 |

### 向量 128：系统调用（由 idt_setup_traps 设置）

| 向量 | 用途 | 处理程序 | 门类型 | DPL | 说明 |
|------|------|---------|--------|-----|------|
| 128 (0x80) | INT 0x80 | `entry_INT80_32` (32位) / `asm_int80_emulation` (64位) | **TRAP** | **3** | 唯一的陷阱门！ |

### 向量 129-234：预留/未分配

| 向量范围 | 状态 |
|---------|------|
| 129-234 | 可分配给设备中断 |

### 向量 235-255：系统向量（由 idt_setup_apic_and_irq_gates 设置）

| 向量 | 十六进制 | 名称 | 处理程序 | 用途 |
|------|---------|------|---------|------|
| 235 | 0xEB | POSTED_MSI_NOTIFICATION | `asm_sysvec_posted_msi_notification` | Posted MSI 通知 |
| 236 | 0xEC | LOCAL_TIMER | `asm_sysvec_apic_timer_interrupt` | 本地 APIC 定时器 |
| 237 | 0xED | HYPERV_STIMER0 | (Hyper-V) | Hyper-V 定时器 |
| 238 | 0xEE | HYPERV_REENLIGHTENMENT | (Hyper-V) | Hyper-V 重新启蒙 |
| 239 | 0xEF | MANAGED_IRQ_SHUTDOWN | (动态) | 托管 IRQ 关闭 |
| 240 | 0xF0 | POSTED_INTR_NESTED | `asm_sysvec_kvm_posted_intr_nested_ipi` | KVM 嵌套中断 |
| 241 | 0xF1 | POSTED_INTR_WAKEUP | `asm_sysvec_kvm_posted_intr_wakeup_ipi` | KVM 唤醒中断 |
| 242 | 0xF2 | POSTED_INTR | `asm_sysvec_kvm_posted_intr_ipi` | KVM Posted 中断 |
| 243 | 0xF3 | HYPERVISOR_CALLBACK | (虚拟化) | Hypervisor 回调 |
| 244 | 0xF4 | DEFERRED_ERROR | `asm_sysvec_deferred_error` | AMD 延迟错误 |
| 245 | 0xF5 | (未分配) | - | - |
| 246 | 0xF6 | IRQ_WORK | `asm_sysvec_irq_work` | IRQ 工作队列 |
| 247 | 0xF7 | X86_PLATFORM_IPI | `asm_sysvec_x86_platform_ipi` | 平台特定 IPI |
| 248 | 0xF8 | REBOOT | `asm_sysvec_reboot` | 重启 IPI |
| 249 | 0xF9 | THRESHOLD_APIC | `asm_sysvec_threshold` | 阈值错误 |
| 250 | 0xFA | THERMAL_APIC | `asm_sysvec_thermal` | 热事件 |
| 251 | 0xFB | CALL_FUNCTION_SINGLE | `asm_sysvec_call_function_single` | 单核函数调用 IPI |
| 252 | 0xFC | CALL_FUNCTION | `asm_sysvec_call_function` | 多核函数调用 IPI |
| 253 | 0xFD | RESCHEDULE | `asm_sysvec_reschedule_ipi` | 重调度 IPI |
| 254 | 0xFE | ERROR_APIC | `asm_sysvec_error_interrupt` | APIC 错误 |
| 255 | 0xFF | SPURIOUS_APIC | `asm_sysvec_spurious_apic_interrupt` | 伪中断 |

---

## 关键特性对比

| 特性 | 异常向量 (0-31) | 设备中断 (32-127) | 系统向量 (235-255) | INT 0x80 (128) |
|------|----------------|------------------|-------------------|----------------|
| **门类型** | Interrupt Gate | Interrupt Gate | Interrupt Gate | **Trap Gate** |
| **DPL** | 0 (除 #BP, #OF 为 3) | 0 | 0 | **3** |
| **IST** | #DB(1), #NMI(2), #DF(3), #MC(4), #VC(5) | 0 | 0 | 0 |
| **segment** | __KERNEL_CS (0x0010) | __KERNEL_CS | __KERNEL_CS | __KERNEL_CS |
| **初始化阶段** | idt_setup_traps() | idt_setup_apic_and_irq_gates() | idt_setup_apic_and_irq_gates() | idt_setup_traps() |

---

## 数据结构示例

### 异常向量（Interrupt Gate, DPL=0）

```
idt_table[14] (#PF):
  offset_low    = 0x2a80       // asm_exc_page_fault 的地址
  segment       = 0x0010       // __KERNEL_CS
  bits          = 0x8E00       // IST=0, type=0xE, DPL=0, P=1
  offset_middle = 0x8100
  offset_high   = 0xffffffff
  reserved      = 0x00000000
```

### 系统调用（Trap Gate, DPL=3，唯一特例！）

```
idt_table[128] (INT 0x80):
  offset_low    = 0x1234       // entry_INT80_32 的地址
  segment       = 0x0010       // __KERNEL_CS
  bits          = 0xEF00       // IST=0, type=0xF (Trap!), DPL=3, P=1
  offset_middle = 0x5678
  offset_high   = 0xffffffff
  reserved      = 0x00000000
```

### 系统向量（Interrupt Gate, DPL=0）

```
idt_table[253] (RESCHEDULE_VECTOR = 0xFD):
  offset_low    = 0xabcd       // asm_sysvec_reschedule_ipi 的地址
  segment       = 0x0010       // __KERNEL_CS
  bits          = 0x8E00       // IST=0, type=0xE, DPL=0, P=1
  offset_middle = 0x9abc
  offset_high   = 0xffffffff
  reserved      = 0x00000000
```

---

## 源代码引用

```c
// arch/x86/kernel/idt.c

// 阶段 1：早期处理程序（向量 0-31）
void __init idt_setup_early_handler(void) {
    for (i = 0; i < 32; i++)
        set_intr_gate(i, early_idt_handler_array[i]);
    load_idt(&idt_descr);
}

// 阶段 2-4：异常门设置
void __init idt_setup_traps(void) {
    idt_setup_from_table(idt_table, def_idts, ARRAY_SIZE(def_idts), true);
    // def_idts[] 包含所有异常向量的最终处理程序

    if (ia32_enabled())
        idt_setup_from_table(idt_table, ia32_idt, 1, true);
    // ia32_idt[] = { SYSG(0x80, entry_INT80_32) }
}

// 阶段 5：APIC 和 IRQ 门
void __init idt_setup_apic_and_irq_gates(void) {
    // 设置 APIC 系统向量（235-255）
    idt_setup_from_table(idt_table, apic_idts, ARRAY_SIZE(apic_idts), true);

    // 设置设备中断向量（32-234）
    for (i = 32; i < 235; i++)
        set_intr_gate(i, irq_entries_start + ...);

    idt_map_in_cea();  // 映射到 CPU Entry Area
    load_idt(&idt_descr);
    set_memory_ro(&idt_table, 1);  // 设置为只读！
}
```

---

## 相关文档

- [IDT_SETUP_EARLY_HANDLER_DETAILED_ANALYSIS.md](IDT_SETUP_EARLY_HANDLER_DETAILED_ANALYSIS.md) - IDT 初始化主流程
- [IDT_DATA_STRUCTURES_RELATIONSHIP.md](IDT_DATA_STRUCTURES_RELATIONSHIP.md) - 数据结构关系详解
- [IVT_IDT_DATA_STRUCTURE_COMPARISON.md](IVT_IDT_DATA_STRUCTURE_COMPARISON.md) - IVT vs IDT 数据结构对比
- [LINUX_KERNEL_IDT_EVOLUTION.md](LINUX_KERNEL_IDT_EVOLUTION.md) - IDT 演进过程

---

**文档结束**
