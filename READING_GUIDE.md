# 文档导读指南

> **本项目包含 100+ 篇技术文档，涵盖从 BIOS 到 Linux 内核的完整启动流程**
>
> 本导读将帮助你根据学习目标和背景快速找到合适的文档

---

## 📚 目录

- [🎯 快速导航：我想了解...](#-快速导航我想了解)
- [🛤️ 学习路径推荐](#️-学习路径推荐)
- [📊 核心文档关系图](#-核心文档关系图)
- [🔍 主题索引](#-主题索引)
- [📖 完整文档列表](#-完整文档列表)

---

## 🎯 快速导航：我想了解...

### 🚀 计算机如何启动？

**从零开始理解完整启动流程**：

| 需求 | 推荐文档 | 难度 |
|------|---------|------|
| **动手实践**（编译运行引导扇区程序） | [QUICKSTART.md](QUICKSTART.md) ⭐ 新增 | ⭐ 入门 |
| **最简概览**（10分钟快速了解） | [BOOT_FLOW.md](BOOT_FLOW.md) | ⭐ 入门 |
| **完整时间线**（QEMU → BIOS → GRUB → Linux） | [BOOT_FLOW_TIMELINE.md](BOOT_FLOW_TIMELINE.md) | ⭐⭐ 进阶 |
| **引导扇区是什么？**（0x7C00 的秘密） | [ORG_0x7C00_EXPLANATION.md](ORG_0x7C00_EXPLANATION.md) | ⭐ 入门 |
| **GRUB 如何工作？** | [GRUB_KERNEL_LOADING.md](GRUB_KERNEL_LOADING.md) | ⭐⭐⭐ 深入 |
| **Linux 内核如何初始化？** | [LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md) | ⭐⭐⭐⭐ 核心 |

**学习路径**：
```
1. BOOT_FLOW.md（了解全局流程）
   ↓
2. ORG_0x7C00_EXPLANATION.md（理解引导扇区）
   ↓
3. GRUB_KERNEL_LOADING.md（理解 GRUB 加载机制）
   ↓
4. LINUX_KERNEL_INIT.md（理解内核启动）
```

---

### 💾 内存管理机制

**从虚拟内存理论到 Linux 实现**：

| 需求 | 推荐文档 | 难度 |
|------|---------|------|
| **为什么需要虚拟内存？** | [WHY_VIRTUAL_MEMORY.md](WHY_VIRTUAL_MEMORY.md) | ⭐ 入门 |
| **Linux 内存管理完整指南** | [LINUX_MEMORY_MANAGEMENT_EVOLUTION.md](LINUX_MEMORY_MANAGEMENT_EVOLUTION.md) | ⭐⭐⭐⭐ 核心 |
| **GDT 是什么？** | [X86_MEMORY_MANAGEMENT_THEORY.md](X86_MEMORY_MANAGEMENT_THEORY.md) | ⭐⭐⭐ 深入 |
| **多级页表如何设计？** | [LINUX_MEMORY_MANAGEMENT_CODE_GUIDE.md](LINUX_MEMORY_MANAGEMENT_CODE_GUIDE.md) | ⭐⭐⭐ 深入 |
| **Buddy 系统与 Slab 分配器** | [BUDDY_ALLOCATOR_GUIDE.md](BUDDY_ALLOCATOR_GUIDE.md) | ⭐⭐⭐ 深入 |
| **用户空间内存管理** | [LINUX_USERSPACE_MEMORY_GUIDE.md](LINUX_USERSPACE_MEMORY_GUIDE.md) | ⭐⭐ 进阶 |
| **Page Fault 如何处理？** | [LINUX_PAGE_FAULT_DEMAND_PAGING.md](LINUX_PAGE_FAULT_DEMAND_PAGING.md) | ⭐⭐ 进阶 |

**推荐阅读顺序**（内存管理专题）：
```
1. WHY_VIRTUAL_MEMORY.md（理论基础）
   ↓
2. LINUX_MEMORY_MANAGEMENT_EVOLUTION.md（完整演化）
   ├─ 第一部分：理论基础
   ├─ 第二部分：Phase 1 - 早期页表
   └─ 第三部分：Phase 2 - 完整页表
   ↓
3. X86_MEMORY_MANAGEMENT_THEORY.md（GDT 专题）
   ↓
4. LINUX_MEMORY_MANAGEMENT_CODE_GUIDE.md（页表实现）
   ↓
5. BUDDY_ALLOCATOR_GUIDE.md（物理内存分配）
   ↓
6. LINUX_USERSPACE_MEMORY_GUIDE.md（用户空间）
   ↓
7. LINUX_PAGE_FAULT_DEMAND_PAGING.md（运行时机制）
```

---

### ⚡ 中断与系统调用

**从硬件中断到系统调用的完整链路**：

| 需求 | 推荐文档 | 难度 |
|------|---------|------|
| **中断、异常、陷阱有什么区别？** | [X86_INTERRUPT_EXCEPTION_TRAP.md](X86_INTERRUPT_EXCEPTION_TRAP.md) | ⭐⭐ 进阶 |
| **Exception 是否可被屏蔽？** | [EXCEPTION_MASKABILITY_ANALYSIS.md](EXCEPTION_MASKABILITY_ANALYSIS.md) | ⭐⭐ 进阶 |
| **异常硬件触发机制详解** | [X86_EXCEPTION_HARDWARE_TRIGGER.md](X86_EXCEPTION_HARDWARE_TRIGGER.md) | ⭐⭐⭐ 深入 |
| **IDT 表如何演进？** | [LINUX_KERNEL_IDT_EVOLUTION.md](LINUX_KERNEL_IDT_EVOLUTION.md) | ⭐⭐⭐ 深入 |
| **为什么只有 INT3/INTO/INT 0x80 是 DPL=3？** | [LINUX_KERNEL_IDT_EVOLUTION.md#idt-中的用户态可触发门dpl3-门详解](LINUX_KERNEL_IDT_EVOLUTION.md#idt-中的用户态可触发门dpl3-门详解) | ⭐⭐ 进阶 |
| **INT 0x80 vs SYSCALL 性能对比** | [LINUX_KERNEL_SYSCALL_INIT.md](LINUX_KERNEL_SYSCALL_INIT.md) | ⭐⭐⭐ 深入 |
| **entry_SYSCALL_64 汇编分析** | [LINUX_KERNEL_SYSCALL_INIT.md#3-entry_syscall_64-入口点详解](LINUX_KERNEL_SYSCALL_INIT.md#3-entry_syscall_64-入口点详解) | ⭐⭐⭐⭐ 核心 |
| **中断控制器演进（PIC → APIC）** | [X86_INTERRUPT_CONTROLLER_EVOLUTION.md](X86_INTERRUPT_CONTROLLER_EVOLUTION.md) | ⭐⭐⭐ 深入 |
| **PIC 与 APIC 共存机制** | [PIC_APIC_COEXISTENCE.md](PIC_APIC_COEXISTENCE.md) | ⭐⭐⭐ 深入 |
| **Linux 中断处理机制** | [LINUX_INTERRUPT_GUIDE.md](LINUX_INTERRUPT_GUIDE.md) | ⭐⭐⭐ 深入 |

**学习路径**（中断与系统调用专题）：
```
1. X86_INTERRUPT_EXCEPTION_TRAP.md（基础概念）
   ├─ Intel SDM 分类体系
   ├─ Interrupt vs Exception 本质区别
   ├─ Fault/Trap/Abort 三种类型
   └─ NMI 详解
   ↓
2. EXCEPTION_MASKABILITY_ANALYSIS.md（可屏蔽性深入分析）⭐ 新增
   ├─ Exception 不受 EFLAGS.IF 控制
   ├─ "Non-Maskable" 术语精确性
   ├─ 实际应用场景（内核启动、SEV-SNP、GDB）
   └─ 项目文档覆盖情况
   ↓
3. X86_EXCEPTION_HARDWARE_TRIGGER.md（硬件触发机制）⭐ 新增
   ├─ #BP 和 #PF 的完整流程
   ├─ CPU 微码级别的硬件行为
   └─ GDB 断点实现原理
   ↓
4. LINUX_KERNEL_IDT_EVOLUTION.md（IDT 演进）
   ├─ 两个 IDT 表的设计
   ├─ 5 个演进阶段
   └─ DPL=3 门详解（INT3/INTO/INT 0x80）
   ↓
5. LINUX_KERNEL_SYSCALL_INIT.md（系统调用详解）
   ├─ INT 0x80 机制
   ├─ SYSCALL/SYSENTER 机制
   └─ 性能对比
   ↓
6. X86_INTERRUPT_CONTROLLER_EVOLUTION.md（中断控制器演进）
   ├─ 8259 PIC 架构
   ├─ APIC 架构（LAPIC + IOAPIC）
   └─ 演进过程
   ↓
7. PIC_APIC_COEXISTENCE.md（PIC 与 APIC 共存）⭐ 新增
   ├─ 为什么需要共存
   ├─ 共存期间的中断路由
   └─ 禁用 PIC 的过程
   ↓
8. LINUX_INTERRUPT_GUIDE.md（Linux 中断处理）
   ├─ 中断处理流程
   ├─ 软中断机制
   └─ 工作队列
```

---

### 🔨 内核编程与代码规范

**理解内核代码的编写规范和约定**：

| 需求 | 推荐文档 | 难度 |
|------|---------|------|
| **Linux 启动代码是否遵守 ABI？** | [LINUX_KERNEL_ABI_COMPLIANCE_ANALYSIS.md](LINUX_KERNEL_ABI_COMPLIANCE_ANALYSIS.md) ⭐ 新增 | ⭐⭐⭐⭐ 核心 |
| **函数修饰符详解（asmlinkage, __visible, __init...）** | [LINUX_KERNEL_FUNCTION_ATTRIBUTES.md](LINUX_KERNEL_FUNCTION_ATTRIBUTES.md) | ⭐⭐ 进阶 |
| **x86 调用约定（Calling Convention）** | [LINUX_KERNEL_FUNCTION_ATTRIBUTES.md#一x86-调用约定基础](LINUX_KERNEL_FUNCTION_ATTRIBUTES.md#一x86-调用约定基础) | ⭐⭐ 进阶 |
| **ARM 调用约定（AAPCS/AAPCS64）** | [LINUX_KERNEL_FUNCTION_ATTRIBUTES.md#14-不同平台调用约定对比](LINUX_KERNEL_FUNCTION_ATTRIBUTES.md#14-不同平台调用约定对比) | ⭐⭐ 进阶 |
| **调用约定 vs 二进制格式（ELF vs Mach-O）** | [LINUX_KERNEL_FUNCTION_ATTRIBUTES.md#16-调用约定与二进制格式的区别](LINUX_KERNEL_FUNCTION_ATTRIBUTES.md#16-调用约定与二进制格式的区别) | ⭐⭐⭐ 深入 |
| **Linux 内核 ABI 稳定性** | [LINUX_KERNEL_FUNCTION_ATTRIBUTES.md#17-linux-内核的-abi-稳定性](LINUX_KERNEL_FUNCTION_ATTRIBUTES.md#17-linux-内核的-abi-稳定性) | ⭐⭐⭐ 深入 |
| **与汇编代码交互** | [LINUX_KERNEL_FUNCTION_ATTRIBUTES.md#六与汇编代码交互](LINUX_KERNEL_FUNCTION_ATTRIBUTES.md#六与汇编代码交互) | ⭐⭐⭐ 深入 |
| **常见组合模式** | [LINUX_KERNEL_FUNCTION_ATTRIBUTES.md#五常见组合模式](LINUX_KERNEL_FUNCTION_ATTRIBUTES.md#五常见组合模式) | ⭐⭐ 进阶 |

**学习路径**（内核编程专题）：
```
1. 阅读 x86/ARM 调用约定基础（LINUX_KERNEL_FUNCTION_ATTRIBUTES.md）
   ├─ x86-64 System V ABI（Linux 标准）
   ├─ x86-32 cdecl 约定
   ├─ ARM32 AAPCS（前4个参数用r0-r3）
   ├─ ARM64 AAPCS64（前8个参数用x0-x7）⭐ 新增
   └─ 调用约定 vs 二进制格式（ELF vs Mach-O）⭐ 新增
   ↓
2. 深入理解 Linux 内核 ABI（LINUX_KERNEL_FUNCTION_ATTRIBUTES.md 1.7节）⭐ 新增
   ├─ 硬件/编译器 ABI（调用约定，长期稳定）
   ├─ 用户空间 ABI（系统调用，严格稳定）
   └─ 内核内部 ABI（函数/数据结构，无稳定性保证）
   ↓
3. **分析启动代码 ABI 遵守情况**（LINUX_KERNEL_ABI_COMPLIANCE_ANALYSIS.md）⭐ 新增
   ├─ 参数传递机制（boot_params 完整传递链）
   ├─ 寄存器使用规则（Caller-saved vs Callee-saved）
   ├─ 返回值传递（RAX 寄存器）
   ├─ 栈帧管理与对齐（8字节 vs 16字节）
   ├─ Red Zone 处理（-mno-red-zone）
   └─ asmlinkage 真相（x86-64 上为空定义）
   ↓
4. 理解各函数修饰符的作用（LINUX_KERNEL_FUNCTION_ATTRIBUTES.md）
   ├─ asmlinkage: 强制栈传参（仅x86-32有效）
   ├─ __visible: 防止 LTO 删除
   ├─ __init: 初始化后释放
   └─ __noreturn: 永不返回
   ↓
5. 查看实际代码示例
   ├─ x86_64_start_kernel 分析
   ├─ start_kernel 分析
   └─ 系统调用表分析
   ↓
6. 学习与汇编代码交互
   ├─ 从汇编调用 C 函数
   └─ 从 C 调用汇编函数
```

**为什么重要？**
- ✅ 理解内核入口函数（`x86_64_start_kernel`, `start_kernel`）的签名
- ✅ 理解系统调用表（`sys_call_table`）的定义
- ✅ 理解为什么需要这些修饰符（与汇编兼容、内存优化等）
- ✅ 能够阅读和编写与汇编交互的 C 代码
- ✅ **理解 Linux 启动代码如何遵守 System V ABI 标准** ⭐ 新增
- ✅ **区分调用约定（编译器层面）vs 内核 ABI（实现层面）** ⭐ 新增

---

### 🔧 GRUB 引导加载程序

**理解 GRUB 的工作机制**：

| 需求 | 推荐文档 | 难度 |
|------|---------|------|
| **GRUB 架构概览** | [GRUB_ARCHITECTURE_AND_INIT.md](GRUB_ARCHITECTURE_AND_INIT.md) | ⭐⭐ 进阶 |
| **core.img 结构** | [GRUB_CORE_IMG_STRUCTURE.md](GRUB_CORE_IMG_STRUCTURE.md) | ⭐⭐⭐ 深入 |
| **GRUB 如何加载 Linux 内核？** | [GRUB_KERNEL_LOADING.md](GRUB_KERNEL_LOADING.md) | ⭐⭐⭐ 深入 |
| **Relocator 模块** | [GRUB_RELOCATOR.md](GRUB_RELOCATOR.md) | ⭐⭐⭐⭐ 核心 |
| **模式切换机制** | [GRUB_MODE_SWITCHING.md](GRUB_MODE_SWITCHING.md) | ⭐⭐⭐ 深入 |
| **GRUB 如何调用 BIOS 服务？** | [GRUB_BIOS_INTERRUPT_USAGE.md](GRUB_BIOS_INTERRUPT_USAGE.md) | ⭐⭐⭐ 深入 |

---

### 🖥️ BIOS 与 UEFI

**理解固件工作原理**：

| 需求 | 推荐文档 | 难度 |
|------|---------|------|
| **BIOS 内存布局** | [BIOS_MEMORY_LAYOUT.md](BIOS_MEMORY_LAYOUT.md) | ⭐⭐ 进阶 |
| **SeaBIOS 固定地址布局** | [SEABIOS_FIXED_ADDRESS_LAYOUT.md](SEABIOS_FIXED_ADDRESS_LAYOUT.md) ⭐ 新增 | ⭐⭐⭐ 深入 |
| **BIOS IVT vs Kernel IDT** | [BIOS_IVT_VS_KERNEL_IDT.md](BIOS_IVT_VS_KERNEL_IDT.md) | ⭐⭐ 进阶 |
| **SeaBIOS 如何构建 E820 表？** | [SEABIOS_E820_CONSTRUCTION.md](SEABIOS_E820_CONSTRUCTION.md) | ⭐⭐⭐ 深入 |
| **SeaBIOS 如何加载引导扇区？** | [SEABIOS_LOAD_BOOT_SECTOR.md](SEABIOS_LOAD_BOOT_SECTOR.md) | ⭐⭐ 进阶 |
| **UEFI vs BIOS 对比** | [UEFI_VS_BIOS_BOOT.md](UEFI_VS_BIOS_BOOT.md) | ⭐⭐ 进阶 |
| **UEFI 启动流程** | [UEFI_BOOT_FLOW_SUMMARY.md](UEFI_BOOT_FLOW_SUMMARY.md) | ⭐⭐ 进阶 |

---

### 🔬 深入专题

**特定技术的深入研究**：

| 专题 | 推荐文档 | 难度 |
|------|---------|------|
| **压缩内核重定位** | [COMPRESSED_KERNEL_RELOCATION.md](COMPRESSED_KERNEL_RELOCATION.md) | ⭐⭐⭐⭐ 核心 |
| **KASLR 原理** | [WHY_RELOCATE_COMPRESSED_KERNEL.md](WHY_RELOCATE_COMPRESSED_KERNEL.md) | ⭐⭐⭐ 深入 |
| **I-cache 解压之谜** | [SOLUTION_ICACHE_MYSTERY.md](SOLUTION_ICACHE_MYSTERY.md) | ⭐⭐⭐⭐ 核心 |
| **Identity Mapping** | [X86_IDENTITY_MAPPING.md](X86_IDENTITY_MAPPING.md) | ⭐⭐⭐ 深入 |
| **位置无关代码（__pi_）** | [X86_POSITION_INDEPENDENT_CODE.md](X86_POSITION_INDEPENDENT_CODE.md) | ⭐⭐⭐⭐ 核心 |
| **Initramfs 分析** | [INITRAMFS_ANALYSIS.md](INITRAMFS_ANALYSIS.md) | ⭐⭐ 进阶 |
| **vmlinuz 结构** | [VMLINUZ_STRUCTURE.md](VMLINUZ_STRUCTURE.md) | ⭐⭐⭐ 深入 |

---

## 🛤️ 学习路径推荐

### 📘 路径 1：入门路径（理解启动流程）

**适合人群**：刚开始学习操作系统、想快速了解计算机启动流程

**预计时间**：2-3 天

```
第 1 天：启动流程概览
├─ BOOT_FLOW.md（1小时）
├─ ORG_0x7C00_EXPLANATION.md（30分钟）
└─ BOOTSECTOR_EXAMPLE.md（30分钟）
   动手：编译运行示例引导扇区

第 2 天：GRUB 与内核加载
├─ GRUB_KERNEL_LOADING.md（2小时）
└─ LINUX_KERNEL_INIT.md（2小时）
   ├─ 只读概览部分
   └─ 理解主要流程

第 3 天：中断与系统调用基础
├─ X86_INTERRUPT_EXCEPTION_TRAP.md（1小时）
└─ LINUX_KERNEL_SYSCALL_INIT.md（1小时）
   └─ 只读对比部分
```

**学习成果**：
- ✅ 理解从开机到 Linux 内核启动的完整流程
- ✅ 知道引导扇区、GRUB、内核的作用
- ✅ 了解中断和系统调用的基本概念

---

### 📗 路径 2：进阶路径（深入内存管理）

**适合人群**：有操作系统基础、想深入理解内存管理机制

**预计时间**：1-2 周

**前置知识**：
- 了解虚拟内存基本概念
- 熟悉 C 语言
- 了解 x86 汇编基础

```
第 1-2 天：理论基础
├─ WHY_VIRTUAL_MEMORY.md（1小时）
└─ LINUX_MEMORY_MANAGEMENT_EVOLUTION.md - 第一部分（2小时）

第 3-5 天：早期页表（Phase 1）
├─ LINUX_MEMORY_MANAGEMENT_EVOLUTION.md - 第二部分（4小时）
├─ X86_IDENTITY_MAPPING.md（1小时）
└─ COMPRESSED_KERNEL_RELOCATION.md（2小时）

第 6-8 天：完整页表（Phase 2）
├─ LINUX_MEMORY_MANAGEMENT_EVOLUTION.md - 第三部分（6小时）
├─ E820_MEMORY_MAP.md（1小时）
└─ SEABIOS_E820_CONSTRUCTION.md（2小时）

第 9-10 天：GDT 与段机制
└─ X86_MEMORY_MANAGEMENT_THEORY.md（4小时）
   ├─ GDT 演化（4阶段）
   └─ 与分页的协作

第 11-12 天：页表实现细节
└─ LINUX_MEMORY_MANAGEMENT_CODE_GUIDE.md（4小时）
   ├─ MMU 遍历伪代码
   └─ 实战计算示例

第 13-14 天：物理内存分配
├─ BUDDY_ALLOCATOR_GUIDE.md（3小时）
└─ SLAB_ALLOCATOR_EXPLAINED.md（3小时）
```

**学习成果**：
- ✅ 深入理解 Linux 内存管理演化过程
- ✅ 掌握 GDT、页表、MMU 的工作机制
- ✅ 了解 Buddy 系统和 Slab 分配器原理

---

### 📕 路径 3：专家路径（中断与系统调用）

**适合人群**：想深入理解内核中断处理和系统调用机制

**预计时间**：1 周

**前置知识**：
- 熟悉 x86-64 汇编
- 了解特权级、DPL 概念
- 熟悉 Linux 内核代码

```
第 1 天：基础概念
├─ X86_INTERRUPT_EXCEPTION_TRAP.md（2小时）
└─ X86_EXCEPTION_HARDWARE_TRIGGER.md（1小时）

第 2-3 天：IDT 演进
├─ LINUX_KERNEL_IDT_EVOLUTION.md（4小时）
│  ├─ 两个 IDT 表的设计原理
│  ├─ 5 个演进阶段
│  └─ DPL=3 门详解
└─ 验证：查看内核源码 arch/x86/kernel/idt.c

第 4-5 天：系统调用机制
├─ LINUX_KERNEL_SYSCALL_INIT.md（6小时）
│  ├─ trap_init() 流程
│  ├─ syscall_init() MSR 配置
│  ├─ entry_SYSCALL_64 汇编分析
│  └─ 32位兼容机制
└─ 动手：编写简单的系统调用程序

第 6 天：中断控制器
└─ X86_INTERRUPT_CONTROLLER_EVOLUTION.md（3小时）
   ├─ 8259 PIC vs APIC
   └─ MSI/MSI-X

第 7 天：运行时中断处理
└─ LINUX_INTERRUPT_GUIDE.md（3小时）
   ├─ Top Half / Bottom Half
   ├─ softirq / tasklet / workqueue
   └─ 实际案例分析
```

**学习成果**：
- ✅ 掌握 IDT 表的完整演进过程
- ✅ 理解 INT 0x80 vs SYSCALL 的差异和性能对比
- ✅ 能够阅读和分析 entry_SYSCALL_64 汇编代码
- ✅ 了解中断处理的完整链路

---

### 📙 路径 4：GRUB 专题路径

**适合人群**：想深入理解 GRUB 工作机制

**预计时间**：5-7 天

```
第 1 天：GRUB 架构
├─ GRUB_ARCHITECTURE_AND_INIT.md（2小时）
└─ GRUB_CORE_IMG_STRUCTURE.md（1小时）

第 2 天：模式切换
├─ GRUB_MODE_SWITCHING.md（2小时）
└─ GRUB_BIOS_INTERRUPT_USAGE.md（1小时）

第 3-4 天：内核加载
├─ GRUB_KERNEL_LOADING.md（4小时）
└─ GRUB_RELOCATOR.md（2小时）

第 5 天：模块系统
├─ GRUB_MODULE_LOADING_ANALYSIS.md（2小时）
└─ GRUB_RELOCATOR_BUILD_AND_RUNTIME.md（1小时）

第 6-7 天：实战分析
├─ GRUB_ISO_ANALYSIS.md（2小时）
├─ GRUB_STARTUP_RAW_TO_STARTUP_PROOF.md（2小时）
└─ 动手：使用 grub-mkrescue 创建自定义 ISO
```

---

## 📊 核心文档关系图

### 启动流程主线

```
                    计算机启动流程
                          │
          ┌───────────────┼───────────────┐
          │               │               │
       BIOS/UEFI        GRUB         Linux Kernel
          │               │               │
          ├─ BIOS_MEMORY_LAYOUT.md       │
          ├─ SEABIOS_LOAD_BOOT_SECTOR.md│
          ├─ UEFI_VS_BIOS_BOOT.md       │
          │               │               │
          │               ├─ GRUB_KERNEL_LOADING.md
          │               ├─ GRUB_RELOCATOR.md
          │               ├─ GRUB_MODE_SWITCHING.md
          │               │               │
          │               │               ├─ LINUX_KERNEL_INIT.md ★
          │               │               ├─ COMPRESSED_KERNEL_RELOCATION.md
          │               │               ├─ LINUX_MEMORY_MANAGEMENT_EVOLUTION.md ★
          │               │               ├─ LINUX_KERNEL_IDT_EVOLUTION.md ★
          │               │               └─ LINUX_KERNEL_SYSCALL_INIT.md ★
          │               │
          └───────────────┴───────────────┘
                          │
                    BOOT_FLOW.md
                    (全局概览)
```

**图例**：
- ★ 表示核心必读文档
- 箭头表示依赖关系
- 同一层级的文档可以并行阅读

---

### 内存管理知识图谱

```
                    内存管理体系
                          │
          ┌───────────────┼───────────────┐
          │               │               │
       理论基础        内核空间        用户空间
          │               │               │
          │               │               │
  WHY_VIRTUAL_MEMORY.md  │               │
          │               │               │
          │      LINUX_MEMORY_MANAGEMENT_EVOLUTION.md ★
          │               │               │
          │       ┌───────┼───────┐       │
          │       │       │       │       │
          │     GDT     页表    分配器    │
          │       │       │       │       │
          │       │       │       │       │
    X86_MEMORY_   │  LINUX_  BUDDY_      │
    MANAGEMENT_   │  MEMORY_ ALLOCATOR_  │
    THEORY.md     │  MANAGE- GUIDE.md    │
                  │  MENT_               │
                  │  CODE_               │
                  │  GUIDE.md            │
                  │                       │
                  └───────────────────────┤
                                          │
                                  LINUX_USERSPACE_
                                  MEMORY_GUIDE.md
                                          │
                                  LINUX_PAGE_FAULT_
                                  DEMAND_PAGING.md
```

---

### 中断与系统调用知识图谱

```
                中断与系统调用体系
                        │
        ┌───────────────┼───────────────┐
        │               │               │
     基础概念         IDT表         系统调用
        │               │               │
        │               │               │
 X86_INTERRUPT_        │               │
 EXCEPTION_TRAP.md     │               │
        │               │               │
        │      LINUX_KERNEL_           │
        │      IDT_EVOLUTION.md ★      │
        │               │               │
        │       ┌───────┼───────┐       │
        │       │       │       │       │
        │   演进阶段  DPL=3  IST机制   │
        │       │       │       │       │
        │       │       │       │       │
        │       │   INT3/INTO/         │
        │       │   INT 0x80            │
        │       │       │               │
        │       └───────┼───────────────┤
        │               │               │
        │               │      LINUX_KERNEL_
        │               │      SYSCALL_INIT.md ★
        │               │               │
        │               │       ┌───────┼───────┐
        │               │       │       │       │
        │               │   trap_  syscall_ entry_
        │               │   init   init     SYSCALL_64
        │               │                   │
        └───────────────┼───────────────────┤
                        │                   │
            X86_INTERRUPT_         LINUX_INTERRUPT_
            CONTROLLER_            GUIDE.md
            EVOLUTION.md
```

---

## 🔍 主题索引

### A - B

| 主题 | 相关文档 |
|------|---------|
| **A20 地址线** | [A20_ADDRESS_LINE.md](A20_ADDRESS_LINE.md) |
| **ABI（应用程序二进制接口）** | [LINUX_KERNEL_ABI_COMPLIANCE_ANALYSIS.md](LINUX_KERNEL_ABI_COMPLIANCE_ANALYSIS.md) ⭐ 新增, [LINUX_KERNEL_FUNCTION_ATTRIBUTES.md](LINUX_KERNEL_FUNCTION_ATTRIBUTES.md) |
| **APIC** | [X86_INTERRUPT_CONTROLLER_EVOLUTION.md](X86_INTERRUPT_CONTROLLER_EVOLUTION.md), [PIC_APIC_COEXISTENCE.md](PIC_APIC_COEXISTENCE.md) |
| **ARM 调用约定（AAPCS/AAPCS64）** | [LINUX_KERNEL_FUNCTION_ATTRIBUTES.md#14-不同平台调用约定对比](LINUX_KERNEL_FUNCTION_ATTRIBUTES.md#14-不同平台调用约定对比) ⭐ 新增 |
| **ASM ORG 指令** | [ASM_ORG_INSTRUCTION.md](ASM_ORG_INSTRUCTION.md) |
| **asmlinkage 修饰符** | [LINUX_KERNEL_FUNCTION_ATTRIBUTES.md#21-asmlinkage](LINUX_KERNEL_FUNCTION_ATTRIBUTES.md#21-asmlinkage), [LINUX_KERNEL_ABI_COMPLIANCE_ANALYSIS.md#71-asmlinkage-在-x86-64-上的真相](LINUX_KERNEL_ABI_COMPLIANCE_ANALYSIS.md#71-asmlinkage-在-x86-64-上的真相) ⭐ 新增 |
| **汇编器 vs 编译器** | [ASSEMBLER_VS_COMPILER.md](ASSEMBLER_VS_COMPILER.md) |
| **BIOS** | [BIOS_MEMORY_LAYOUT.md](BIOS_MEMORY_LAYOUT.md), [BIOS_IVT_VS_KERNEL_IDT.md](BIOS_IVT_VS_KERNEL_IDT.md), [SEABIOS_E820_CONSTRUCTION.md](SEABIOS_E820_CONSTRUCTION.md) |
| **引导扇区** | [BOOTSECTOR_EXAMPLE.md](BOOTSECTOR_EXAMPLE.md), [ORG_0x7C00_EXPLANATION.md](ORG_0x7C00_EXPLANATION.md) |
| **启动流程** | [BOOT_FLOW.md](BOOT_FLOW.md), [BOOT_FLOW_TIMELINE.md](BOOT_FLOW_TIMELINE.md) |
| **Buddy 系统** | [BUDDY_ALLOCATOR_GUIDE.md](BUDDY_ALLOCATOR_GUIDE.md) |
| **BusyBox** | [BUSYBOX_SH_EXEC_INIT_DETAILS.md](BUSYBOX_SH_EXEC_INIT_DETAILS.md) |

### C - E

| 主题 | 相关文档 |
|------|---------|
| **Calling Convention（调用约定）** | [LINUX_KERNEL_FUNCTION_ATTRIBUTES.md#一x86-调用约定基础](LINUX_KERNEL_FUNCTION_ATTRIBUTES.md#一x86-调用约定基础), [LINUX_KERNEL_ABI_COMPLIANCE_ANALYSIS.md](LINUX_KERNEL_ABI_COMPLIANCE_ANALYSIS.md) ⭐ 新增 |
| **压缩内核重定位** | [COMPRESSED_KERNEL_RELOCATION.md](COMPRESSED_KERNEL_RELOCATION.md), [WHY_RELOCATE_COMPRESSED_KERNEL.md](WHY_RELOCATE_COMPRESSED_KERNEL.md) |
| **DPL=3 门** | [LINUX_KERNEL_IDT_EVOLUTION.md#idt-中的用户态可触发门dpl3-门详解](LINUX_KERNEL_IDT_EVOLUTION.md) |
| **E820 内存映射** | [E820_MEMORY_MAP.md](E820_MEMORY_MAP.md), [SEABIOS_E820_CONSTRUCTION.md](SEABIOS_E820_CONSTRUCTION.md) |
| **ELF vs Mach-O** | [LINUX_KERNEL_FUNCTION_ATTRIBUTES.md#16-调用约定与二进制格式的区别](LINUX_KERNEL_FUNCTION_ATTRIBUTES.md#16-调用约定与二进制格式的区别) ⭐ 新增 |
| **异常与中断** | [X86_INTERRUPT_EXCEPTION_TRAP.md](X86_INTERRUPT_EXCEPTION_TRAP.md), [X86_EXCEPTION_HARDWARE_TRIGGER.md](X86_EXCEPTION_HARDWARE_TRIGGER.md) |

### G - I

| 主题 | 相关文档 |
|------|---------|
| **GDT** | [X86_MEMORY_MANAGEMENT_THEORY.md](X86_MEMORY_MANAGEMENT_THEORY.md) |
| **GRUB** | [GRUB_KERNEL_LOADING.md](GRUB_KERNEL_LOADING.md), [GRUB_RELOCATOR.md](GRUB_RELOCATOR.md), [GRUB_CORE_IMG_STRUCTURE.md](GRUB_CORE_IMG_STRUCTURE.md) |
| **I-cache** | [SOLUTION_ICACHE_MYSTERY.md](SOLUTION_ICACHE_MYSTERY.md) |
| **IDT** | [LINUX_KERNEL_IDT_EVOLUTION.md](LINUX_KERNEL_IDT_EVOLUTION.md), [BIOS_IVT_VS_KERNEL_IDT.md](BIOS_IVT_VS_KERNEL_IDT.md) |
| **Identity Mapping** | [X86_IDENTITY_MAPPING.md](X86_IDENTITY_MAPPING.md) |
| **Initramfs** | [INITRAMFS_ANALYSIS.md](INITRAMFS_ANALYSIS.md), [ALPINE_INIT_PROCESS_ANALYSIS.md](ALPINE_INIT_PROCESS_ANALYSIS.md) |
| **INT 0x80** | [LINUX_KERNEL_SYSCALL_INIT.md](LINUX_KERNEL_SYSCALL_INIT.md), [LINUX_KERNEL_IDT_EVOLUTION.md](LINUX_KERNEL_IDT_EVOLUTION.md) |
| **中断控制器** | [X86_INTERRUPT_CONTROLLER_EVOLUTION.md](X86_INTERRUPT_CONTROLLER_EVOLUTION.md) |

### K - P

| 主题 | 相关文档 |
|------|---------|
| **KASLR** | [WHY_RELOCATE_COMPRESSED_KERNEL.md](WHY_RELOCATE_COMPRESSED_KERNEL.md) |
| **键盘中断** | [APPENDIX_A_KEYBOARD_INTERRUPT.md](APPENDIX_A_KEYBOARD_INTERRUPT.md) |
| **Linux 内核启动** | [LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md), [LINUX_KERNEL_SETUP_FLOW.md](LINUX_KERNEL_SETUP_FLOW.md) |
| **内存管理** | [LINUX_MEMORY_MANAGEMENT_EVOLUTION.md](LINUX_MEMORY_MANAGEMENT_EVOLUTION.md), [LINUX_USERSPACE_MEMORY_GUIDE.md](LINUX_USERSPACE_MEMORY_GUIDE.md) |
| **Page Fault** | [LINUX_PAGE_FAULT_DEMAND_PAGING.md](LINUX_PAGE_FAULT_DEMAND_PAGING.md) |
| **页表** | [LINUX_MEMORY_MANAGEMENT_CODE_GUIDE.md](LINUX_MEMORY_MANAGEMENT_CODE_GUIDE.md) |
| **PIC** | [X86_INTERRUPT_CONTROLLER_EVOLUTION.md](X86_INTERRUPT_CONTROLLER_EVOLUTION.md) |
| **位置无关代码** | [X86_POSITION_INDEPENDENT_CODE.md](X86_POSITION_INDEPENDENT_CODE.md) |

### S - Z

| 主题 | 相关文档 |
|------|---------|
| **SeaBIOS** | [SEABIOS_LOAD_BOOT_SECTOR.md](SEABIOS_LOAD_BOOT_SECTOR.md), [SEABIOS_E820_CONSTRUCTION.md](SEABIOS_E820_CONSTRUCTION.md) |
| **Slab 分配器** | [SLAB_ALLOCATOR_EXPLAINED.md](SLAB_ALLOCATOR_EXPLAINED.md), [BUDDY_ALLOCATOR_GUIDE.md](BUDDY_ALLOCATOR_GUIDE.md) |
| **系统调用** | [LINUX_KERNEL_SYSCALL_INIT.md](LINUX_KERNEL_SYSCALL_INIT.md) |
| **SYSCALL 指令** | [LINUX_KERNEL_SYSCALL_INIT.md](LINUX_KERNEL_SYSCALL_INIT.md) |
| **UEFI** | [UEFI_VS_BIOS_BOOT.md](UEFI_VS_BIOS_BOOT.md), [UEFI_BOOT_FLOW_SUMMARY.md](UEFI_BOOT_FLOW_SUMMARY.md) |
| **虚拟内存** | [WHY_VIRTUAL_MEMORY.md](WHY_VIRTUAL_MEMORY.md) |
| **vmlinuz** | [VMLINUZ_STRUCTURE.md](VMLINUZ_STRUCTURE.md) |

---

## 📖 完整文档列表

完整的文档列表请参见 [README.md](README.md#文档目录)。

---

## 💡 使用建议

### 如何选择学习路径？

1. **我是初学者**
   - 从"入门路径"开始
   - 重点阅读 BOOT_FLOW.md 和 LINUX_KERNEL_INIT.md
   - 不要跳过基础概念

2. **我想深入某个专题**
   - 直接查看"快速导航"找到相关文档
   - 按推荐顺序阅读
   - 结合源码验证理解

3. **我想系统学习**
   - 按"学习路径推荐"的顺序阅读
   - 每个阶段做好笔记
   - 动手实践验证

4. **我想查找特定内容**
   - 使用"主题索引"快速定位
   - 查看文档间的交叉引用
   - 利用浏览器搜索功能

### 阅读文档的技巧

1. **先看概览，再看细节**
   - 每个文档通常有"概览"或"时间线"章节
   - 先理解全局，再深入细节

2. **结合源码阅读**
   - 文档中标注了源码位置（文件名:行号）
   - 对照源码理解更深入

3. **画图理解**
   - 复杂的流程可以自己画流程图
   - 内存布局可以画内存图

4. **做笔记和总结**
   - 记录关键概念
   - 总结文档间的联系

5. **动手实践**
   - 编写示例代码验证理解
   - 使用 QEMU 调试内核启动

---

## 🤝 贡献与反馈

如果你发现：
- 文档有错误或不清楚的地方
- 想要新增某个主题的文档
- 对学习路径有建议

欢迎提交 Issue 或 Pull Request！

---

**最后更新**：2026-02-17
**文档数量**：100+ 篇
**维护者**：Linux 内核启动文档项目

**最新更新**：
- ⭐ 新增 [LINUX_KERNEL_ABI_COMPLIANCE_ANALYSIS.md](LINUX_KERNEL_ABI_COMPLIANCE_ANALYSIS.md) - Linux 内核 ABI 合规性分析（98% 符合）
- ⭐ 扩展 [LINUX_KERNEL_FUNCTION_ATTRIBUTES.md](LINUX_KERNEL_FUNCTION_ATTRIBUTES.md) - 新增 ARM 调用约定、ELF vs Mach-O、内核 ABI 稳定性分析
