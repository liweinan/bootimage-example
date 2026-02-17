# 完整文档索引

> 本文档包含项目中所有 100+ 篇技术文档的详细分类列表。
>
> 💡 **首次访问？** 建议先查看：
> - 🚀 [快速开始指南 (QUICKSTART.md)](QUICKSTART.md) - 快速运行引导扇区示例程序
> - 📖 [文档导读指南 (READING_GUIDE.md)](READING_GUIDE.md) - 系统性的学习路径

---

## 📚 文档分类目录

- [核心概念文档](#核心概念文档)
- [BIOS 相关文档](#bios-相关文档)
- [SeaBIOS 相关文档](#seabios-相关文档)
- [启动流程文档](#启动流程文档)
- [GRUB 引导加载程序文档](#grub-引导加载程序文档)
- [Linux 内核相关文档](#linux-内核相关文档)
- [中断相关文档](#中断相关文档)
- [硬件与 I/O 文档](#硬件与-io-文档)
- [内存管理文档](#内存管理文档)
- [UEFI 相关文档](#uefi-相关文档)
- [工具与配置文档](#工具与配置文档)
- [演示程序文档](#演示程序文档)
- [DOS 相关文档](#dos-相关文档)
- [问题调查与解决方案](#问题调查与解决方案)
- [文档审查与交叉引用](#文档审查与交叉引用)
- [已归档文档](#已归档文档)
- [分析与验证工具](#分析与验证工具)

---

## 核心概念文档

### 底层编程基础

| 文档 | 描述 |
|------|------|
| [ASM_ORG_INSTRUCTION.md](ASM_ORG_INSTRUCTION.md) | ORG 汇编指令详解 |
| [ASSEMBLER_VS_COMPILER.md](ASSEMBLER_VS_COMPILER.md) | 汇编器 vs 编译器的区别 |
| [RELATIVE_JUMP_EXECUTION.md](RELATIVE_JUMP_EXECUTION.md) | 相对跳转执行详解 |
| [X86_POSITION_INDEPENDENT_CODE.md](X86_POSITION_INDEPENDENT_CODE.md) | x86 位置无关代码（PIC）详解 |

### 系统机制

| 文档 | 描述 |
|------|------|
| [GUIDE.md](GUIDE.md) | 计算机中断机制完全指南：从汇编到硬件实现 |
| [WHY_VIRTUAL_MEMORY.md](WHY_VIRTUAL_MEMORY.md) | **为什么需要虚拟内存**：从物理地址到分页的必然性<br>• 物理地址 vs 虚拟地址的权衡分析<br>• 分页解决的五大核心问题（碎片、保护、超售、共享、硬件）<br>• 碎片化的数学证明与算法分析<br>• 性能代价的实际分析（TLB、现代优化）<br>• 历史案例（RTOS、DOS、x86 分段演化） |
| [X86_CPU_MODES.md](X86_CPU_MODES.md) | x86 CPU 运行模式详解（实模式、保护模式、长模式） |
| [X86_NEAR_VS_LONG_JUMP.md](X86_NEAR_VS_LONG_JUMP.md) | x86 near jump 与 long jump（far jump）区别，long mode 下 CS 的作用（CPL、L/D 位） |
| [X86_64BIT_SEGMENT_LIMIT.md](X86_64BIT_SEGMENT_LIMIT.md) | 64位长模式下段限长处理详解（Intel手册官方说明、为何被忽略、真正的内存控制机制） |
| [X86_IDENTITY_MAPPING.md](X86_IDENTITY_MAPPING.md) | x86-64 Identity Mapping（恒等映射）实现详解（页表构建、CR3使用、与Direct Mapping区别、2MB大页设计） |
| [A20_ADDRESS_LINE.md](A20_ADDRESS_LINE.md) | A20 地址线详解 |

---

## BIOS 相关文档

| 文档 | 描述 |
|------|------|
| [BIOS_MEMORY_LAYOUT.md](BIOS_MEMORY_LAYOUT.md) | BIOS 内存布局与地址映射详解 |
| [BIOS_MEMORY_QA.md](BIOS_MEMORY_QA.md) | BIOS 内存相关问答 |
| [BIOS_MEMORY_MAPPING.md](BIOS_MEMORY_MAPPING.md) | BIOS 文件映射到物理内存的证据分析 |
| [BIOS_CODE_LAYOUT_ANALYSIS.md](BIOS_CODE_LAYOUT_ANALYSIS.md) | BIOS 代码布局分析 |
| [BIOS_FIRST_BLOCK_ANALYSIS.md](BIOS_FIRST_BLOCK_ANALYSIS.md) | BIOS 第一个块（First Block）分析 |
| [BIOS_INTERRUPT_COMPLETE.md](BIOS_INTERRUPT_COMPLETE.md) | BIOS 中断完整文档 |
| [BIOS_IVT_VS_KERNEL_IDT.md](BIOS_IVT_VS_KERNEL_IDT.md) | BIOS IVT 与 Linux 内核 IDT 的软件中断服务程序对比 |
| [IVT_IDT_DATA_STRUCTURE_COMPARISON.md](IVT_IDT_DATA_STRUCTURE_COMPARISON.md) | BIOS IVT 与 Kernel IDT 数据结构详细对比（实模式 vs 保护模式/长模式） |
| [BIOS_SIZE.md](BIOS_SIZE.md) | BIOS 大小与映射关系详解 |
| [BIOS_VERIFICATION_REPORT.md](BIOS_VERIFICATION_REPORT.md) | BIOS 固定地址验证报告 |

---

## SeaBIOS 相关文档

| 文档 | 描述 |
|------|------|
| [SEABIOS_FIXED_ADDRESS_LAYOUT.md](SEABIOS_FIXED_ADDRESS_LAYOUT.md) | SeaBIOS 固定地址布局：IBM PC BIOS 兼容性规范 |
| [FILL_SEABIOS_ANALYSIS.md](FILL_SEABIOS_ANALYSIS.md) | SeaBIOS 与 Linux 内核地址转换机制对比分析 |
| [SEABIOS_PROTECTION_MODE_CODE.md](SEABIOS_PROTECTION_MODE_CODE.md) | SeaBIOS 保护模式代码的真正用途 |
| [SEABIOS_ENTRY_13_ANALYSIS.md](SEABIOS_ENTRY_13_ANALYSIS.md) | SeaBIOS INT 13h 入口分析 |
| [SEABIOS_HANDLE_POST_ENTRY.md](SEABIOS_HANDLE_POST_ENTRY.md) | SeaBIOS handle_post 入口分析 |
| [SEABIOS_E820_CONSTRUCTION.md](SEABIOS_E820_CONSTRUCTION.md) | SeaBIOS E820 内存映射表构建流程 |
| [SEABIOS_LOAD_BOOT_SECTOR.md](SEABIOS_LOAD_BOOT_SECTOR.md) | SeaBIOS 如何加载引导扇区到 0x7C00 |

---

## 启动流程文档

| 文档 | 描述 |
|------|------|
| [BOOT_FLOW.md](BOOT_FLOW.md) | **计算机启动流程详解**（从 QEMU 到 Linux 内核的完整流程）⭐ 入门必读 |
| [BOOT_FLOW_NOTES.md](BOOT_FLOW_NOTES.md) | 启动流程笔记 |
| [BOOT_FLOW_QA.md](BOOT_FLOW_QA.md) | 启动流程问答 |
| [BOOT_FLOW_TIMELINE.md](BOOT_FLOW_TIMELINE.md) | 启动流程完整时间线（从 QEMU 启动到 Linux 内核接管的详细时间序列） |
| [BOOT_FLOW_SOURCE_INDEX.md](BOOT_FLOW_SOURCE_INDEX.md) | 启动流程关键源代码文件索引 |
| [ORG_0x7C00_EXPLANATION.md](ORG_0x7C00_EXPLANATION.md) | 为什么引导扇区加载到 0x7C00 |
| [BOOTSECTOR_EXAMPLE.md](BOOTSECTOR_EXAMPLE.md) | 最小引导扇区程序示例 |
| [BOOTSECTOR_COMPARISON.md](BOOTSECTOR_COMPARISON.md) | 引导扇区对比分析 |
| [DISK_TO_MEMORY_TRANSFER.md](DISK_TO_MEMORY_TRANSFER.md) | 磁盘数据拷贝到内存的详细过程（PIO/DMA） |
| [BOOT_SECTOR_ANALYSIS.md](BOOT_SECTOR_ANALYSIS.md) | 引导扇区代码手工分析指南 |
| [CALL_BOOT_ENTRY_EXPLANATION.md](CALL_BOOT_ENTRY_EXPLANATION.md) | call_boot_entry 函数详细解释 |

---

## GRUB 引导加载程序文档

| 文档 | 描述 |
|------|------|
| [GRUB_ARCHITECTURE_AND_INIT.md](GRUB_ARCHITECTURE_AND_INIT.md) | GRUB 架构与初始化流程 |
| [GRUB_CORE_IMG_STRUCTURE.md](GRUB_CORE_IMG_STRUCTURE.md) | GRUB core.img 结构与构建详解（grub-mkimage、块列表机制、内存布局） |
| [GRUB_ISO_ANALYSIS.md](GRUB_ISO_ANALYSIS.md) | GRUB ISO 镜像引导分析（boot.S、core.img 位置、内存布局等） |
| [GRUB_ISO_BOOT_FILES.md](GRUB_ISO_BOOT_FILES.md) | GRUB ISO 镜像中哪些文件在 boot 阶段被加载 |
| [GRUB_KERNEL_ADDR_ANALYSIS.md](GRUB_KERNEL_ADDR_ANALYSIS.md) | GRUB_BOOT_MACHINE_KERNEL_ADDR = 0x8000 的计算和设计原因分析 |
| [GRUB_RELOCATOR.md](GRUB_RELOCATOR.md) | **GRUB Relocator 模块详解** |
| [GRUB_RELOCATOR_BUILD_AND_RUNTIME.md](GRUB_RELOCATOR_BUILD_AND_RUNTIME.md) | GRUB Relocator 构建与运行时机制 |
| [GRUB_MODULE_LOADING_ANALYSIS.md](GRUB_MODULE_LOADING_ANALYSIS.md) | GRUB 模块加载机制分析 |
| [GRUB_BIOS_INTERRUPT_USAGE.md](GRUB_BIOS_INTERRUPT_USAGE.md) | GRUB 在保护模式下调用 BIOS 服务的使用场景 |
| [GRUB_MODE_SWITCHING.md](GRUB_MODE_SWITCHING.md) | GRUB 模式切换函数详解（real_to_prot、prot_to_real 实现细节） |
| [GRUB_KERNEL_LOADING.md](GRUB_KERNEL_LOADING.md) | **GRUB 加载 Linux 内核详细流程**（grub_cmd_linux、grub_linux_boot、grub_relocator32_boot 源代码分析） |
| [GRUB_STARTUP_RAW_TO_STARTUP_PROOF.md](GRUB_STARTUP_RAW_TO_STARTUP_PROOF.md) | GRUB startup_raw.S 解压后跳转到 startup.S 的证明（源代码分析、链接顺序、寄存器状态） |
| [GRUB_I386_PC_STARTUP_USAGE.md](GRUB_I386_PC_STARTUP_USAGE.md) | i386_pc_startup 变量在 GRUB 构建系统中的使用说明（如何确保 startup.S 是第一个链接的文件） |
| [CREATE_GRUB_ISO.md](CREATE_GRUB_ISO.md) | 使用 grub-mkrescue 生成 GRUB ISO 镜像教程 |

---

## Linux 内核相关文档

### 内核启动与初始化

| 文档 | 描述 |
|------|------|
| [LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md) | **Linux 内核启动与初始化**（64 位，不走 Setup）⭐ 核心文档<br>• GRUB/压缩内核、模式切换<br>• startup_32/startup_64<br>• x86_64_start_kernel、start_kernel<br>• 中断接管、系统调用<br>• PID 0/1/2、核心进程 |
| [LINUX_KERNEL_SETUP_FLOW.md](LINUX_KERNEL_SETUP_FLOW.md) | Linux 内核 Setup 流程详解 |
| [LINUX_KERNEL_ABI_COMPLIANCE_ANALYSIS.md](LINUX_KERNEL_ABI_COMPLIANCE_ANALYSIS.md) | **Linux 内核启动代码 System V ABI 遵守情况分析报告** ⭐ 新增<br>• 详细分析启动代码对 ABI 的遵守（综合评分：98%）<br>• 参数传递机制（boot_params 完整传递链）<br>• 寄存器使用规则（Caller/Callee-saved）<br>• 返回值传递、栈帧管理、Red Zone 处理<br>• asmlinkage 真相揭秘（x86-64 上为空定义）<br>• 内核特殊优化（8字节栈对齐、禁用 Red Zone）<br>• 14+ 代码示例 + 权威规范引用<br>• 30+ 交叉引用链接 |
| [LINUX_KERNEL_FUNCTION_ATTRIBUTES.md](LINUX_KERNEL_FUNCTION_ATTRIBUTES.md) | **Linux 内核函数修饰符与调用约定**（已更新 v2.0 → v2.3）<br>• x86-64/x86-32/ARM32/ARM64 调用约定详解 ⭐ 新增<br>• 函数修饰符（asmlinkage、__visible、__init、__noreturn）<br>• 调用约定 vs 二进制格式（ELF vs Mach-O）⭐ 新增<br>• Linux 内核 ABI 稳定性分析 ⭐ 新增<br>• 汇编代码交互、常见组合模式 |
| [SEABIOS_GRUB_ABI_COMPLIANCE_ANALYSIS.md](SEABIOS_GRUB_ABI_COMPLIANCE_ANALYSIS.md) | **SeaBIOS & GRUB ABI 遵从性分析报告** ⭐ 新增<br>• SeaBIOS i386 平台 ABI 分析（合规性 30%）<br>• GRUB 多架构 ABI 分析（i386/x86-64/ARM32/ARM64）<br>• 违反标准的编译器标志详解（`-mregparm=3`, `-mrtd`, `-mpreferred-stack-boundary=2`）<br>• 固件代码为何偏离标准 ABI（代码体积、性能、独立运行环境）<br>• 与 Linux 内核的异同对比<br>• 代码体积节省 10-15%、性能优化分析<br>• 附实测汇编代码对比 |
| [LINUX_ABI_BOUNDARIES_AND_TRANSITIONS.md](LINUX_ABI_BOUNDARIES_AND_TRANSITIONS.md) | **Linux ABI 边界与转换：System V ABI vs Linux Userspace ABI** ⭐ 新增<br>• 明确区分三种 ABI：System V ABI（函数调用）、Linux Userspace ABI（内核承诺）、启动协议 ABI<br>• 系统调用 ABI 详解：为何第 4 个参数用 R10 而非 RCX<br>• 启动过程中的 5 个 ABI 边界（硬件→BIOS→Bootloader→Kernel→Userspace）<br>• vDSO 与 vsyscall 机制（混合 ABI）<br>• ABI 稳定性对比（Linus："We do not break userspace"）<br>• 实际代码示例（System V 函数调用 vs Syscall） |
| [COMPRESSED_KERNEL_RELOCATION.md](COMPRESSED_KERNEL_RELOCATION.md) | **Linux 压缩内核重定位机制** |
| [WHY_RELOCATE_COMPRESSED_KERNEL.md](WHY_RELOCATE_COMPRESSED_KERNEL.md) | 为什么需要重定位压缩内核（KASLR 分析） |

### 内核镜像与 Initramfs

| 文档 | 描述 |
|------|------|
| [VMLINUZ_STRUCTURE.md](VMLINUZ_STRUCTURE.md) | vmlinuz（bzImage）文件详细结构分析（boot_params、setup code、压缩内核等） |
| [VMLINUZ_INITRD_RELATIONSHIP.md](VMLINUZ_INITRD_RELATIONSHIP.md) | vmlinuz 和 initrd 的关系详解（定义、作用机制、使用场景、必要性分析） |
| [INITRAMFS_ANALYSIS.md](INITRAMFS_ANALYSIS.md) | Initramfs 内容分析与 BusyBox 启动设置（initramfs 分析工具、BusyBox 工作原理、/init 和 /sbin/init 的关系） |
| [INITRAMFS_ANALYSIS_RESULT.md](INITRAMFS_ANALYSIS_RESULT.md) | Alpine Linux Initramfs 实际分析结果（基于 initrd-alpine-v3.19.img 的实际分析） |
| [ALPINE_INIT_PROCESS_ANALYSIS.md](ALPINE_INIT_PROCESS_ANALYSIS.md) | Alpine Linux Initramfs Init 启动过程详细分析（基于 mkinitfs 源代码的完整流程分析） |
| [BUSYBOX_SH_EXEC_INIT_DETAILS.md](BUSYBOX_SH_EXEC_INIT_DETAILS.md) | BusyBox sh 执行 /init 脚本的实现细节（Linux 内核 shebang 处理机制、binfmt_script 模块工作原理） |

---

## 中断相关文档

### 中断基础理论

| 文档 | 描述 |
|------|------|
| [X86_INTERRUPT_EXCEPTION_TRAP.md](X86_INTERRUPT_EXCEPTION_TRAP.md) | **x86 中断、异常、陷阱：Intel SDM 规范与 Linux 实现**<br>• Interrupt/Exception/Trap 定义<br>• 三者本质区别<br>• Exception 分类（Fault/Trap/Abort）<br>• 优先级、IDT 门类型<br>• Linux 实现 |
| [X86_EXCEPTION_HARDWARE_TRIGGER.md](X86_EXCEPTION_HARDWARE_TRIGGER.md) | x86 异常的硬件触发机制：Page Fault 与 Breakpoint 深入剖析 |

### Linux 中断实现

| 文档 | 描述 |
|------|------|
| [LINUX_INTERRUPT_GUIDE.md](LINUX_INTERRUPT_GUIDE.md) | Linux 中断处理机制（Top Half/Bottom Half、softirq/tasklet/workqueue） |
| [LINUX_KERNEL_IDT_EVOLUTION.md](LINUX_KERNEL_IDT_EVOLUTION.md) | **Linux 内核 IDT 表的演进流程详解**<br>• 两个 IDT 表、5 个演进阶段<br>• **IDT 中的用户态可触发门（DPL=3）详解：INT3/INTO/INT 0x80 完整对比** |
| [X86_64_TSS_AND_IST.md](X86_64_TSS_AND_IST.md) | **x86-64 任务状态段（TSS）与中断栈表（IST）详解**<br>• TSS 历史演变（硬件任务切换→栈管理器）<br>• IST 机制工作原理与必要性<br>• Double Fault/NMI/Machine Check 的 IST 使用<br>• TSS 初始化时机与启动约束<br>• 未初始化 TSS 时使用 IST 的危险场景 |
| [IDT_SETUP_EARLY_HANDLER_DETAILED_ANALYSIS.md](IDT_SETUP_EARLY_HANDLER_DETAILED_ANALYSIS.md) | **idt_setup_early_handler() 函数详细分析** ⭐ v2.0 模块化重构<br>• 四个阶段完整流程：编译时准备 → 运行时写入 → 加载到 CPU → 运行时使用<br>• 数据结构详解：`idt_table`、`idt_descr`、`gate_desc`、`desc_ptr`<br>• `early_idt_handler_array` 的汇编实现（.rept 宏、32 个处理程序桩）<br>• 逐行代码分析：为什么是 32 个向量、每次循环做了什么<br>• `set_intr_gate()` 的完整工作流程（init_idt_data → idt_setup_from_table → write_idt_entry）<br>• `load_idt()` 的底层实现（lidt 指令、IDTR 寄存器更新、原子切换）<br>• 完整的执行流程图和内存变化对比<br>• **配套详细文档**：完整向量表、数据结构详解、异常处理流程（见下方） |
| [IDT_COMPLETE_VECTOR_TABLE.md](IDT_COMPLETE_VECTOR_TABLE.md) | **IDT 完整向量表参考手册** ⭐ 新增（从主文档拆分）<br>• 完整的 256 个向量清单（0-31 异常、32-127 IRQ、128 系统调用、235-255 APIC）<br>• 五阶段初始化时间线（为什么前 32 个向量要填充两次）<br>• Emergency Handlers vs Production Handlers 对比<br>• 各向量的功能说明、处理程序地址、IST 使用情况<br>• 数据结构示例和源代码引用 |
| [IDT_DATA_STRUCTURES_RELATIONSHIP.md](IDT_DATA_STRUCTURES_RELATIONSHIP.md) | **IDT 数据结构关系详解** ⭐ 新增（从主文档拆分）<br>• idt_descr（10 字节元信息）vs idt_table（4096 字节数据）的关系<br>• 为什么需要 idt_descr？x86 lidt 指令限制详解<br>• 内存布局示例、使用流程、完整关系图<br>• 门描述符 (gate_desc) 的 16 字节十六进制数据格式<br>• bits 字段位分解（IST、type、DPL、P）<br>• 多个向量的实际数据对比 |
| [IDT_EXCEPTION_HANDLING_DETAILS.md](IDT_EXCEPTION_HANDLING_DETAILS.md) | **IDT 早期异常处理流程详解** ⭐ 新增（从主文档拆分）<br>• CPU 触发异常的硬件流程（保存上下文 → 查找 IDTR → 读取 idt_table → 跳转）<br>• early_idt_handler_array 桩代码详解（错误码标准化、EXCEPTION_ERRCODE_MASK）<br>• early_idt_handler_common 公共处理程序（栈帧布局、pt_regs 结构）<br>• do_early_exception() C 语言处理逻辑（#PF 动态建立页表、#VC/#VE 虚拟化处理）<br>• 完整执行流程示例（#PF 缺页异常）<br>• 性能优化与安全加固措施 |
| [EARLY_IDT_HANDLER_ARRAY_EXPLAINED.md](EARLY_IDT_HANDLER_ARRAY_EXPLAINED.md) | **early_idt_handler_array 深度解析：它不是数组！** ⭐ 新增<br>• 澄清常见误解：不是存储地址的数组，而是连续的机器代码块<br>• 汇编符号 vs C 数组的本质区别<br>• 实际的内存布局（objdump 实证验证）<br>• early_idt_handler_array[i] 的计算过程（编译器和链接器的魔法）<br>• 与 idt_data.addr 的对应关系<br>• 完整的数据流转过程（汇编 → 地址 → idt_data → gate_desc → idt_table）<br>• 三种类比总结（图书馆、街道门牌、音乐专辑） |
| [IDT_HANDLER_EVOLUTION.md](IDT_HANDLER_EVOLUTION.md) | **IDT 处理程序的三代演进** ⭐ 新增<br>• 为什么需要三代处理程序（Chicken-and-Egg 问题）<br>• 第 1 代：Emergency Handlers（应急，early_idt_handler_common + do_early_exception）<br>• 第 2 代：Transitional Handlers（过渡，部分替换为 asm_exc_*）<br>• 第 3 代：Production Handlers（生产，完整功能 + IST 支持）<br>• 完整的演进时间线（从 x86_64_start_kernel 到 cpu_init）<br>• 对比分析：以 #PF 为例（Emergency vs Production）<br>• early_idt_handler_common 的命运（被完全废弃）<br>• 分层初始化设计原则 |
| [LINUX_KERNEL_IDT_INTEL_SDM_COMPLIANCE.md](LINUX_KERNEL_IDT_INTEL_SDM_COMPLIANCE.md) | **Linux 内核 IDT 结构与 Intel SDM 规范符合性分析** ⭐ 新增<br>• Intel SDM 64 位门描述符规范（16 字节格式、位域详解）<br>• Linux 内核 gate_desc 结构定义（源代码分析）<br>• 逐字节符合性对比（所有字段完全匹配）<br>• idt_data（软件抽象）vs gate_desc（硬件格式）的关系<br>• 为什么需要两个结构（可读性、参数传递、硬件兼容）<br>• 完整的转换流程（idt_init_desc 函数详解）<br>• ✅ 验证结论：gate_desc 完全符合 Intel SDM 规范<br>• 实际验证方法（GDB、内核日志、pahole 工具） |
| [CALL_GATE_VS_IDT_GATE_KERNEL_STRUCTURES.md](CALL_GATE_VS_IDT_GATE_KERNEL_STRUCTURES.md) | **Call Gate vs IDT Gate：Linux 内核数据结构对比** ⭐ 新增<br>• 澄清常见困惑：为什么两种门描述符看起来很像<br>• 核心区别：存储位置（GDT/LDT vs IDT）<br>• Linux 内核数据结构对应：IDT Gate → `gate_desc`，Call Gate → `desc_struct`（不使用）<br>• Call Gate 为何被废弃（SYSCALL 指令更快）<br>• 权限检查机制对比（主动调用 vs 被动触发）<br>• 现代 Linux 的实际使用情况（只使用 IDT Gate）<br>• 完整示例对比（理论 Call Gate vs 实际 IDT Gate） |
| [KASAN_INSTRUMENTATION_AND_INIT_ORDER.md](KASAN_INSTRUMENTATION_AND_INIT_ORDER.md) | **KASAN 插桩机制与初始化顺序深度分析** ⭐ 新增<br>• 编译时插桩 vs 运行时初始化的本质区别<br>• 为什么必须先 kasan_early_init() 后 idt_setup_early_handler()<br>• `__asan_loadXX`/`__asan_storeXX` 函数工作原理<br>• 如果 KASAN 未初始化会发生什么（递归 Page Fault → Triple Fault）<br>• 内核源代码证据（head64.c 明确注释）<br>• 为什么不让 KASAN 自动跳过检查（性能、Chicken-and-Egg 问题）<br>• `__head` 和 `KASAN_SANITIZE` 的作用<br>• 影子内存（Shadow Memory）机制详解 |
| [LINUX_KERNEL_SYSCALL_INIT.md](LINUX_KERNEL_SYSCALL_INIT.md) | **Linux 系统调用初始化详解**<br>• trap_init/syscall_init<br>• INT 0x80 vs SYSCALL/SYSENTER 性能对比<br>• entry_SYSCALL_64 入口分析 |

### 中断控制器

| 文档 | 描述 |
|------|------|
| [X86_INTERRUPT_CONTROLLER_EVOLUTION.md](X86_INTERRUPT_CONTROLLER_EVOLUTION.md) | x86 中断控制器演进：从 8259 PIC 到 APIC（架构对比、性能分析、MSI/MSI-X、x2APIC） |
| [PIC_APIC_COEXISTENCE.md](PIC_APIC_COEXISTENCE.md) | PIC 与 APIC 共存机制 |

### 其他中断机制

| 文档 | 描述 |
|------|------|
| [UEFI_INTERRUPT_HANDLING.md](UEFI_INTERRUPT_HANDLING.md) | UEFI 中断处理机制 |
| [APPENDIX_A_KEYBOARD_INTERRUPT.md](APPENDIX_A_KEYBOARD_INTERRUPT.md) | 附录 A：键盘中断详解 |
| [APPENDIX_B_EVENT_MECHANISM.md](APPENDIX_B_EVENT_MECHANISM.md) | 附录 B：事件机制详解 |

---

## 硬件与 I/O 文档

| 文档 | 描述 |
|------|------|
| [KEYBOARD_CONTROLLER_IO.md](KEYBOARD_CONTROLLER_IO.md) | 键盘控制器 I/O 详解 |
| [QEMU_VS_HARDWARE_BIOS.md](QEMU_VS_HARDWARE_BIOS.md) | QEMU vs 真实硬件 BIOS 加载对比 |

---

## 内存管理文档

### 核心指南

| 文档 | 描述 |
|------|------|
| [LINUX_MEMORY_MANAGEMENT_EVOLUTION.md](LINUX_MEMORY_MANAGEMENT_EVOLUTION.md) | **Linux 内核分页机制完整指南（演化篇）** ⭐ 核心文档<br>• 第一部分：理论基础（Flat Model、GDT、MMU、页表抽象）<br>• 第二部分：Phase 1 - 早期页表（compressed kernel 身份映射）<br>• 第三部分：Phase 2 - 完整页表（E820、memblock、init_mem_mapping、zone） |

### 深入专题

| 文档 | 描述 |
|------|------|
| [X86_MEMORY_MANAGEMENT_THEORY.md](X86_MEMORY_MANAGEMENT_THEORY.md) | **GDT 详解：从保护模式到长模式（理论篇）**<br>• GDT 演化（GRUB → Compressed Kernel → Main Kernel → per-CPU）<br>• 段描述符结构详解（二进制拆解、字段含义）<br>• 长模式下的作用与分页协作<br>• GDT Identity Mapping：启动时平滑过渡机制（实模式→保护模式） |
| [LINUX_MEMORY_MANAGEMENT_CODE_GUIDE.md](LINUX_MEMORY_MANAGEMENT_CODE_GUIDE.md) | **x86-64 多级页表设计详解（实现篇）**<br>• 页表建立过程与时间线（代码级实现）<br>• 阶段 2-3 分页目的与 x86-64 硬件要求<br>• 多级页表设计原理与内存开销对比（512GB vs 68KB）<br>• MMU 硬件页表遍历伪代码（walk_virtual_address）<br>• 书籍目录类比与动态管理机制 |
| [SLAB_ALLOCATOR_EXPLAINED.md](SLAB_ALLOCATOR_EXPLAINED.md) | **Slab 分配器原理与实践**<br>• Slab 解决的问题（传统页分配器的不足）<br>• 三层架构（Cache → Slab → Object）<br>• 核心优势（性能 5-10 倍、内存利用率提升、缓存友好性）<br>• 实战使用（创建自定义缓存、监控与调试）<br>• 现代变体（SLAB/SLUB/SLOB 对比） |
| [BUDDY_ALLOCATOR_GUIDE.md](BUDDY_ALLOCATOR_GUIDE.md) | **伙伴系统与 Slab 分配器详解（源码级）**<br>• 伙伴系统原理、算法与实现<br>• Slab/SLUB 分配器源码分析与 per-CPU 缓存<br>• 从 memblock 到 buddy 的转换流程 |
| [X86_64_TLB_MANAGEMENT.md](X86_64_TLB_MANAGEMENT.md) | **x86-64 TLB 管理与页表切换详解**<br>• TLB 基础知识（ITLB/DTLB、Global 页、PCID）<br>• 四种 TLB 刷新机制（CR3、CR4.PGE、INVLPG、INVPCID）<br>• 启动过程中的页表切换（为什么需要 __native_tlb_flush_global）<br>• 运行时 TLB 管理（进程切换、KPTI、TLB Shootdown）<br>• 性能分析与优化（大页、PCID、批量刷新） |

### 子文档（技术细节）

| 文档 | 描述 |
|------|------|
| [E820_MEMORY_MAP.md](E820_MEMORY_MAP.md) | E820 内存映射表详解 |
| [SEABIOS_E820_CONSTRUCTION.md](SEABIOS_E820_CONSTRUCTION.md) | SeaBIOS E820 构建流程 |
| [BOOTLOADER_MEMORY_PASSING.md](BOOTLOADER_MEMORY_PASSING.md) | Bootloader 内存信息传递 |

### 用户空间内存

| 文档 | 描述 |
|------|------|
| [LINUX_USERSPACE_MEMORY_GUIDE.md](LINUX_USERSPACE_MEMORY_GUIDE.md) | Linux 用户空间内存管理 |
| [LINUX_PAGE_FAULT_DEMAND_PAGING.md](LINUX_PAGE_FAULT_DEMAND_PAGING.md) | Linux 缺页异常与按需分配 |
| [SEABIOS_FIXED_ADDRESS_LAYOUT.md](SEABIOS_FIXED_ADDRESS_LAYOUT.md) | SeaBIOS 固定地址布局 |

---

## UEFI 相关文档

| 文档 | 描述 |
|------|------|
| [UEFI_VS_BIOS_BOOT.md](UEFI_VS_BIOS_BOOT.md) | UEFI vs BIOS 启动对比 |
| [UEFI_BOOT_FLOW_SUMMARY.md](UEFI_BOOT_FLOW_SUMMARY.md) | UEFI 启动流程总结 |
| [GRUB_UEFI_LONG_MODE_ANALYSIS.md](GRUB_UEFI_LONG_MODE_ANALYSIS.md) | GRUB UEFI 长模式启动与 Linux Kernel 配合支持分析 |

---

## 工具与配置文档

| 文档 | 描述 |
|------|------|
| [VNC_SETUP.md](VNC_SETUP.md) | VNC 设置指南 |
| [SLEEP.md](SLEEP.md) | 睡眠/休眠相关文档 |

---

## 演示程序文档

| 文档 | 描述 |
|------|------|
| [EVENT_DEMO_README.md](EVENT_DEMO_README.md) | 事件演示程序说明 |
| [KEYBOARD_DEMO_README.md](KEYBOARD_DEMO_README.md) | 键盘演示程序说明 |
| [MANUAL_INT_README.md](MANUAL_INT_README.md) | 手动中断演示程序说明 |

---

## DOS 相关文档

| 文档 | 描述 |
|------|------|
| [DOS_BOOTLOADER.md](DOS_BOOTLOADER.md) | DOS 的引导加载程序（Bootloader）概念 |
| [DOS_BIOS_INT_USAGE.md](DOS_BIOS_INT_USAGE.md) | DOS 如何使用 BIOS 的 INT 服务 |

---

## 问题调查与解决方案

| 文档 | 描述 |
|------|------|
| [INVESTIGATION_SUMMARY.md](INVESTIGATION_SUMMARY.md) | 问题调查总结 |
| [SOLUTION_ICACHE_MYSTERY.md](SOLUTION_ICACHE_MYSTERY.md) | 指令缓存问题的解决方案 |
| [README_ICACHE_TEST.md](README_ICACHE_TEST.md) | 指令缓存测试说明 |

---

## 文档审查与交叉引用

| 文档 | 描述 |
|------|------|
| [REVIEW_BIOS_IVT_VS_KERNEL_IDT.md](REVIEW_BIOS_IVT_VS_KERNEL_IDT.md) | BIOS_IVT_VS_KERNEL_IDT.md 文档审查 |
| [REVIEW_LINUX_INTERRUPT_GUIDE.md](REVIEW_LINUX_INTERRUPT_GUIDE.md) | LINUX_INTERRUPT_GUIDE.md 文档审查 |
| [REVIEW_LINUX_KERNEL_INIT.md](REVIEW_LINUX_KERNEL_INIT.md) | LINUX_KERNEL_INIT.md 文档审查 |
| [REVIEW_LINUX_KERNEL_SYSCALL_INIT.md](REVIEW_LINUX_KERNEL_SYSCALL_INIT.md) | LINUX_KERNEL_SYSCALL_INIT.md 文档审查 |
| [LINUX_KERNEL_IDT_EVOLUTION_REVIEW.md](LINUX_KERNEL_IDT_EVOLUTION_REVIEW.md) | LINUX_KERNEL_IDT_EVOLUTION.md 文档审查 |
| [CROSS_REFERENCE_SUMMARY.md](CROSS_REFERENCE_SUMMARY.md) | 文档交叉引用总结 |

---

## 已归档文档

以下文档已被更完整、更准确的版本替代，保留仅供历史参考：

| 文档 | 说明 |
|------|------|
| [_ARCHIVED_LINUX_KERNEL_GDT_EVOLUTION.md](_ARCHIVED_LINUX_KERNEL_GDT_EVOLUTION.md) | 已归档：Linux 内核 GDT 演进<br>✅ 已被 X86_MEMORY_MANAGEMENT_THEORY.md 替代 |
| [_ARCHIVED_LINUX_PAGING_GUIDE.md](_ARCHIVED_LINUX_PAGING_GUIDE.md) | 已归档：Linux 分页指南<br>✅ 已被 LINUX_MEMORY_MANAGEMENT_EVOLUTION.md 替代 |
| [_ARCHIVED_PAGING_PHASE1_THEORY_AND_EARLY_TABLES.md](_ARCHIVED_PAGING_PHASE1_THEORY_AND_EARLY_TABLES.md) | 已归档：分页阶段 1 理论与早期页表<br>✅ 已被 LINUX_MEMORY_MANAGEMENT_EVOLUTION.md 替代 |
| [_ARCHIVED_PAGING_PHASE2_FULL_SETUP_IN_SETUP_ARCH.md](_ARCHIVED_PAGING_PHASE2_FULL_SETUP_IN_SETUP_ARCH.md) | 已归档：分页阶段 2 完整设置<br>✅ 已被 LINUX_MEMORY_MANAGEMENT_EVOLUTION.md 替代 |
| [_ARCHIVED_X86_PAGE_TABLE_DESIGN.md](_ARCHIVED_X86_PAGE_TABLE_DESIGN.md) | 已归档：x86 页表设计<br>✅ 已被 LINUX_MEMORY_MANAGEMENT_CODE_GUIDE.md 替代 |

---

## 分析与验证工具

### BIOS 固件分析工具

#### verify_bios.py

**验证对象**：BIOS 固件（bios.bin），映射到物理地址 0xF0000-0xFFFFF

⚠️ **注意**：这是验证 BIOS 固件，不是 Bootloader（Bootloader 使用 verify_boot_sector.py）

**功能**：
- 验证 BIOS ROM 文件中的关键固定地址是否正确
- 分析 BIOS 文件结构（两个 64KB 块的内容分布）
- 查找关键 BIOS 入口点
- 分析填充区域和代码模式

**使用方法**：
```bash
python3 verify_bios.py [bios_file]              # 执行所有分析（默认）
python3 verify_bios.py [bios_file] --structure  # 只执行文件结构分析
python3 verify_bios.py [bios_file] --addresses  # 只执行固定地址验证
```

**相关文档**：[BIOS_MEMORY_MAPPING.md](BIOS_MEMORY_MAPPING.md)

---

### Bootloader（引导扇区）分析工具

#### verify_boot_sector.py

**验证对象**：Bootloader（boot.bin），由 BIOS 加载到内存地址 0x7C00

⚠️ **注意**：这是验证 Bootloader，不是 BIOS 固件（BIOS 使用 verify_bios.py）

**功能**：
- 验证引导扇区文件大小（512 字节）
- 验证引导扇区签名（0xAA55）
- 验证代码内容和内存地址映射（0x7C00-0x7DFF）

**使用方法**：
```bash
python3 verify_boot_sector.py [boot_file]
```

---

### GRUB 分析工具

#### verify_grub_boot_sector.py

**验证对象**：GRUB ISO 镜像（grub.iso）的引导扇区和 core.img

**功能**：
- 自动检测标准模式和 HYBRID_BOOT 模式
- 验证引导扇区签名和关键字段（kernel_sector、kernel_address）
- 提取 core.img 并分析块列表（显示每个条目的详细信息）
- 检测 core.img 压缩状态（LZMA 压缩 vs 未压缩）
  - 数据特征分析（NOP 字节、零字节、可打印字符串统计）
  - 熵值计算和压缩评分系统
- 反汇编分析 core.img（查找 grub_stub_init 入口点）

**使用方法**：
```bash
python3 verify_grub_boot_sector.py [iso_file]
```

---

### Initramfs 分析工具

#### analyze_initramfs.sh

**功能**：解压并分析 initramfs（initrd.img）内容，查找 BusyBox 启动配置

**支持**：自动查找本地 initrd.img 文件，或从 ISO 文件中提取

**查找顺序**：
1. 当前目录的 `*.img` 文件（如 `initrd-alpine-v3.19.img`）
2. `.grub_iso_cache/` 目录中的 `initrd.img`
3. `iso/boot/` 目录中的 `initrd.img`
4. 从 ISO 文件中提取（如果存在）

**分析内容**：
- `/init` 脚本的类型和内容
- BusyBox 文件和符号链接
- `/sbin/init` 和 `/bin/sh` 的配置
- 启动配置文件（`/etc/inittab`、`/etc/init.d/rcS` 等）
- 文件系统结构

**使用方法**：
```bash
./analyze_initramfs.sh                      # 自动查找 initrd.img（优先使用当前目录的 *.img 文件）
./analyze_initramfs.sh /path/to/initrd.img  # 指定文件路径
```

**详细说明**：参见 [INITRAMFS_ANALYSIS.md](INITRAMFS_ANALYSIS.md)

---

## 🔍 快速查找

使用浏览器的查找功能（Ctrl+F 或 Cmd+F）可以快速定位特定主题的文档。

---

## 📖 推荐阅读顺序

本索引按主题分类组织。如果你不确定从哪里开始，建议查看 [文档导读指南 (READING_GUIDE.md)](READING_GUIDE.md)，其中包含：

- 🎯 按学习目标的快速导航
- 🛤️ 4 条完整学习路径（入门 → 进阶 → 专家）
- 📊 核心文档关系图
- 💡 阅读建议和学习技巧

---

**最后更新**：2026-02-18
**文档总数**：100+ 篇
**维护者**：Linux 内核启动文档项目
