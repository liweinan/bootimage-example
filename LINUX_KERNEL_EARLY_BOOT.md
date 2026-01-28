# Linux 内核早期启动详细流程（64 位）

本文档详细说明 Linux 内核从 GRUB 跳转后的早期启动过程，包括 Setup 代码执行、模式切换（实模式 → 保护模式 → 64 位长模式）、内核解压和 `startup_64` 入口点的源代码分析。

> **相关文档**：
> - **后续阶段**：关于 `start_kernel()` 之后的内核初始化（子系统初始化、PID 0/1/2、syscall 设置），请参见 [Linux 内核初始化详解](LINUX_KERNEL_INIT.md)
> - 关于启动流程概述，请参见 [BOOT_FLOW.md](BOOT_FLOW.md)

## 内核早期启动（64 位）

**说明**：内核从 GRUB 跳转后，首先执行的是内核镜像中的 setup 代码（实模式），然后切换到保护模式，最终到达 `startup_64`。GRUB 跳转的地址是 `code32_start`，这是 setup 代码的入口点。

**重要澄清：vmlinuz 文件的压缩结构**

- **vmlinuz 文件包含两部分**：
  1. **Setup 代码**（未压缩）：可以直接执行，GRUB 只是将其从磁盘复制到内存
  2. **压缩的内核代码**（gzip 压缩）：需要由 Setup 代码解压
- **GRUB 的作用**：只是将整个 vmlinuz 文件从磁盘复制到内存，**不解压**
- **解压时机**：由内核自己的 Setup 代码完成解压，不是 GRUB

**详细执行流程：**

```
grub_relocator32_boot() 跳转到内核入口点（code32_start）
    ├─ 源代码位置：grub/grub-core/lib/i386/relocator.c
    ├─ 跳转地址：code32_start（内核头部字段，相对于 0x100000 的偏移）
    └─ 寄存器状态：
        ├─ ESI = boot_params 地址
        ├─ ESP = 栈指针
        └─ EIP = code32_start（内核入口点）
    ↓
Linux 内核 Setup 代码（实模式）
    ├─ 源代码位置：linux/arch/x86/boot/header.S
    ├─ 内存位置：0x100000（1MB）或内核指定的地址
    ├─ 运行模式：实模式（初始阶段）
    ├─ **状态说明**：Setup 代码是未压缩的，可以直接执行
    ├─ 验证内核签名（boot_flag = 0xAA55）
    ├─ 初始化基本环境
    ├─ **调用链**：
    │   ├─ `header.S`（入口点）→ 调用 `main()` 函数
    │   │   └─ 源代码位置：`linux/arch/x86/boot/main.c:main()`
    │   └─ `main()` → 调用 `go_to_protected_mode()` 函数
    │       └─ 源代码位置：`linux/arch/x86/boot/pm.c:go_to_protected_mode()`
    ├─ **切换到保护模式的关键步骤**（源代码位置：`linux/arch/x86/boot/pm.c` 和 `linux/arch/x86/boot/pmjump.S`）：
    │   ├─ 步骤 1: 调用 `go_to_protected_mode()` 函数
    │   │   └─ 源代码位置：`linux/arch/x86/boot/pm.c:go_to_protected_mode()`
    │   │   └─ **调用者**：`linux/arch/x86/boot/main.c:main()`
    │   ├─ 步骤 2: 设置 GDT（全局描述符表）
    │   │   └─ `setup_gdt()` - 设置保护模式的段描述符
    │   ├─ 步骤 3: 设置 IDT（中断描述符表）
    │   │   └─ `setup_idt()` - 设置保护模式的中断描述符
    │   ├─ 步骤 4: 启用 A20 地址线
    │   │   └─ `enable_a20()` - 允许访问 1MB 以上内存
    │   ├─ 步骤 5: 重置协处理器（如果存在）
    │   │   └─ `reset_coprocessor()` - 重置数学协处理器
    │   ├─ 步骤 6: 屏蔽所有中断
    │   │   └─ `mask_all_interrupts()` - 在模式切换期间禁用中断
    │   ├─ 步骤 7: 设置 CR0 的 PE 位（Protected Mode Enable）
    │   │   └─ `movl %cr0, %eax; orl $X86_CR0_PE, %eax; movl %eax, %cr0`
    │   └─ 步骤 8: 跳转到保护模式代码
    │       └─ `protected_mode_jump()` - 长跳转到保护模式代码段
    └─ 跳转到压缩内核解压代码（startup_32，32 位保护模式）
        ↓
**Linux 内核 Setup 代码切换到保护模式的详细代码：**

**调用链：**

```
header.S（入口点，实模式）
    ↓
main()（linux/arch/x86/boot/main.c）
    ↓
go_to_protected_mode()（linux/arch/x86/boot/pm.c）
    ↓
protected_mode_jump()（linux/arch/x86/boot/pmjump.S）
    ↓
startup_32（32 位保护模式，压缩内核解压代码）
```

**源代码位置：** `linux/arch/x86/boot/header.S`（入口点）

```asm
// linux/arch/x86/boot/header.S
// 这是 Linux 内核 Setup 代码的入口点
// GRUB 跳转到 code32_start，即这个入口点

.code16
.section ".header", "a"
.globl	hdr
hdr:
    // 内核头部结构（boot_params）
    setup_sects:    .byte 0
    root_flags:     .word ROOT_RDONLY
    syssize:        .long 0
    ram_size:       .word 0
    vid_mode:       .word SVGA_MODE
    root_dev:       .word 0
    boot_flag:      .word 0xAA55  // 引导扇区签名
    
    // ... 更多头部字段 ...
    
    // 入口点：_start
    .globl _start
_start:
    // 步骤 1: 初始化段寄存器
    movw    %cs, %ax
    movw    %ax, %ds
    movw    %ax, %es
    movw    %ax, %ss
    
    // 步骤 2: 设置栈指针
    lss     stack_start, %esp
    
    // 步骤 3: 清除方向标志（字符串操作方向）
    cld
    
    // 步骤 4: 调用 C 代码的 main() 函数
    calll   main  // ← 这里调用 main() 函数
    
    // 注意：main() 函数会调用 go_to_protected_mode()
    // 然后跳转到保护模式，不会返回到这里
```

**源代码位置：** `linux/arch/x86/boot/main.c:main()`

```c
// linux/arch/x86/boot/main.c
void main(void)
{
    /* 第一步：复制引导参数 */
    // 从实模式数据区域复制 boot_params 结构
    // boot_params 包含从 GRUB 传递过来的启动参数（命令行、内存映射等）
    copy_boot_params();
    
    /* 第二步：初始化堆 */
    // 设置堆内存区域，用于动态内存分配
    // Setup 代码需要堆来分配临时缓冲区等
    init_heap();
    
    /* 第三步：设置视频模式 */
    // 检测和设置显示模式（VGA、SVGA 等）
    // 如果内核需要显示启动信息，需要先设置视频模式
    set_video();
    
    /* 第四步：查询 APM BIOS（高级电源管理） */
    // 检测系统是否支持 APM
    // APM 用于电源管理（休眠、唤醒等）
    query_apm_bios();
    
    /* 第五步：查询 EDD（Enhanced Disk Drive） */
    // 检测硬盘信息（容量、几何结构等）
    // 用于内核了解系统硬件配置
    query_edd();
    
    /* 第六步：检测内存 */
    // 检测系统内存大小和布局
    // 使用 INT 15h E820 功能获取内存映射
    detect_memory();
    
    /* 第七步：设置键盘 */
    // 初始化键盘控制器
    // 用于内核启动过程中的键盘输入
    keyboard_init();
    
    /* 第八步：查询 MCA（Micro Channel Architecture） */
    // 检测是否使用 MCA 总线（IBM PS/2 系统）
    query_mca();
    
    /* 第九步：查询 VESA（Video Electronics Standards Association） */
    // 检测 VESA BIOS 扩展（VBE）
    // 用于设置高分辨率显示模式
    query_vesa();
    
    /* 第十步：查询 PAL（Platform Abstraction Layer） */
    // 检测平台抽象层（某些特殊平台）
    query_pal();
    
    /* 第十一步：设置命令行参数 */
    // 处理内核命令行参数（如 root=、ro、quiet 等）
    // 这些参数会影响内核的启动行为
    parse_early_param();
    
    /* 第十二步：最终检查 */
    // 验证所有必要的初始化是否完成
    // 检查硬件兼容性等
    
    /* 最后：切换到保护模式 */
    // 所有初始化完成后，切换到保护模式
    // 然后跳转到压缩内核解压代码（startup_32）
    go_to_protected_mode();  // ← 这里调用 go_to_protected_mode()
    
    // 注意：go_to_protected_mode() 会跳转到保护模式代码
    // 不会返回到这里
}
```

**`main.c` 的主要工作：**

1. **引导参数处理**：
   - `copy_boot_params()`：从实模式数据区域复制 `boot_params` 结构
   - 包含从 GRUB 传递的启动参数（命令行、内存映射、initramfs 地址等）

2. **内存管理**：
   - `init_heap()`：初始化堆内存区域，用于动态内存分配
   - `detect_memory()`：检测系统内存大小和布局（使用 INT 15h E820）

3. **硬件检测**：
   - `set_video()`：设置视频显示模式
   - `query_apm_bios()`：检测高级电源管理（APM）支持
   - `query_edd()`：检测增强磁盘驱动器（EDD）信息
   - `query_mca()`：检测微通道架构（MCA）总线
   - `query_vesa()`：检测 VESA BIOS 扩展（VBE）

4. **输入设备**：
   - `keyboard_init()`：初始化键盘控制器

5. **参数处理**：
   - `parse_early_param()`：解析内核命令行参数（如 `root=`, `ro`, `quiet` 等）

6. **模式切换**：
   - `go_to_protected_mode()`：切换到保护模式，跳转到压缩内核解压代码

**关键点：**
- **所有工作都在实模式下完成**：`main.c` 中的所有函数都在实模式下执行
- **为保护模式做准备**：初始化各种子系统，为切换到保护模式做准备
- **最后一步是模式切换**：所有初始化完成后，调用 `go_to_protected_mode()` 切换到保护模式

**源代码位置：** `linux/arch/x86/boot/pm.c:go_to_protected_mode()`

```c
// linux/arch/x86/boot/pm.c
void go_to_protected_mode(void)
{
    // 步骤 1: 设置 GDT（全局描述符表）
    // 定义保护模式的段描述符（代码段、数据段等）
    setup_gdt();
    
    // 步骤 2: 设置 IDT（中断描述符表）
    // 在保护模式下，中断通过 IDT 处理
    setup_idt();
    
    // 步骤 3: 启用 A20 地址线
    // 允许访问 1MB 以上的内存（实模式限制在 1MB）
    enable_a20();
    
    // 步骤 4: 重置协处理器（如果存在）
    reset_coprocessor();
    
    // 步骤 5: 屏蔽所有中断
    // 在模式切换期间必须禁用中断
    mask_all_interrupts();
    
    // 步骤 6: 调用汇编函数执行实际的模式切换
    // 这个函数会设置 CR0.PE 位并跳转到保护模式
    protected_mode_jump(boot_params.hdr.code32_start,
                        (u32)&boot_params + (ds() << 4));
}
```

**源代码位置：** `linux/arch/x86/boot/pm.c:setup_idt()`

```c
// linux/arch/x86/boot/pm.c
// setup_idt - 设置空 IDT（在进入保护模式之前）
static void setup_idt(void)
{
    static const struct gdt_ptr null_idt = {0, 0};  // limit=0, base=0（空 IDT）
    asm volatile("lidtl %0" : : "m" (null_idt));   // 加载空 IDT 到 IDTR
}
```

**说明：**
- `setup_idt()` 在 `go_to_protected_mode()` 中被调用（在 `protected_mode_jump()` 之前）
- 设置的是**空 IDT**（limit=0, base=0），用于禁用所有中断
- 此时内核尚未建立完整的中断处理程序，使用空 IDT 可以避免未处理的中断导致系统崩溃
- 真正的 IDT 会在后续的内核初始化阶段建立（在 `startup_64` 中调用 `idt_setup_early_traps()`）

**源代码位置：** `linux/arch/x86/boot/pmjump.S:protected_mode_jump()`

```asm
// linux/arch/x86/boot/pmjump.S
// protected_mode_jump - 从实模式切换到保护模式并跳转
.code16
GLOBAL(protected_mode_jump)
    // 步骤 1: 禁用中断
    cli
    
    // 步骤 2: 禁用不可屏蔽中断（NMI）
    movl    %eax, %edx      // 保存参数
    inb     $0x70, %al      // 读取 CMOS 索引寄存器
    orl     $0x80, %eax     // 设置 NMI 禁用位
    outb    %al, $0x70      // 写回 CMOS
    
    // 步骤 3: 加载 GDT
    lgdt    gdt_descriptor  // 加载 GDT 描述符到 GDTR
    
    // 注意：IDT 已在 setup_idt() 中加载（空 IDT），此处不需要再次加载
    
    // 步骤 4: 设置 CR0 的 PE 位（Protected Mode Enable）
    movl    %cr0, %eax
    orl     $X86_CR0_PE, %eax  // 设置 PE 位 = 1
    movl    %eax, %cr0
    
    // 步骤 5: 跳转到保护模式代码段
    // 使用长跳转（ljmp）刷新预取队列并切换到保护模式
    ljmp    $__BOOT_CS, $1f  // 跳转到保护模式代码段
    
    .code32
1:  // 保护模式代码开始
    // 步骤 6: 重新加载所有段寄存器（使用保护模式段选择子）
    movl    $__BOOT_DS, %eax
    movl    %eax, %ds
    movl    %eax, %es
    movl    %eax, %fs
    movl    %eax, %gs
    movl    %eax, %ss
    
    // 步骤 7: 设置栈指针
    leal    boot_stack_end, %esp
    
    // 步骤 8: 跳转到压缩内核解压代码（startup_32）
    // %edx 包含 code32_start 地址（从 boot_params 传递）
    jmp     *%edx  // 跳转到 startup_32（32 位保护模式代码）
```

**关键寄存器设置：**

1. **GDT**：定义保护模式的段描述符（代码段、数据段等）
2. **IDT**：定义保护模式的中断描述符表
3. **CR0.PE = 1**：启用保护模式（Protected Mode Enable）
4. **段选择子**：`__BOOT_CS`（代码段）、`__BOOT_DS`（数据段）

**模式切换顺序：**

```
实模式（Setup 代码）
    ↓
设置 GDT 和 IDT
    ↓
启用 A20 地址线
    ↓
屏蔽中断
    ↓
设置 CR0.PE = 1（启用保护模式）
    ↓
长跳转到保护模式代码段（ljmp $__BOOT_CS, $1f）
    ↓
32 位保护模式（startup_32）
```

**压缩内核解压代码（startup_32）：**
    ├─ 源代码位置：linux/arch/x86/boot/compressed/head_64.S
    ├─ 运行模式：32 位保护模式 → 64 位长模式
    ├─ **切换到 64 位长模式的关键步骤**（源代码位置：`linux/arch/x86/boot/compressed/head_64.S`）：
    │   ├─ 步骤 1: 设置页表（身份映射：物理地址 = 线性地址）
    │   ├─ 步骤 2: 启用 PAE（Physical Address Extension）
    │   │   └─ 设置 CR4.PAE = 1（必须，长模式需要 PAE）
    │   ├─ 步骤 3: 加载页表基址到 CR3
    │   │   └─ `mov %eax, %cr3`（设置页表基址）
    │   ├─ 步骤 4: 启用长模式（EFER.LME = 1）
    │   │   └─ 使用 `wrmsr` 设置 EFER MSR 寄存器
    │   ├─ 步骤 5: 启用分页（CR0.PG = 1）
    │   │   └─ `mov %eax, %cr0`（设置 CR0.PG 位）
    │   └─ 步骤 6: 跳转到 64 位代码段
    │       └─ `ljmp $__KERNEL_CS, $startup_64`（使用 64 位代码段选择子）
    ├─ **解压内核（gzip 解压）**：
    │   ├─ 解压 vmlinuz 文件中的压缩内核代码部分
    │   ├─ 解压目标：0x100000+（覆盖压缩代码区域）
    │   └─ 这是**第一次解压**，由内核自己的代码完成
    └─ 跳转到 startup_64
        ↓
startup_64（64 位内核入口点，已切换到长模式）
    ├─ 源代码位置：linux/arch/x86/kernel/head_64.S
    ├─ 运行模式：64 位长模式
    ├─ 保存 boot_params 结构地址（%RSI → %R15）
    ├─ 设置初始内核栈
    ├─ 设置 GS 段基址（per-CPU 数据）
    ├─ 设置 GDT 和早期 IDT
    ├─ 切换到内核代码段（__KERNEL_CS）
    ├─ 激活内存加密（SEV/SME，如果支持）
    ├─ 验证和清理 CPU 配置（verify_cpu）
    └─ 继续内核初始化流程
        ↓
内核继续初始化（x86_64_start_kernel）
    ├─ 源代码位置：linux/arch/x86/kernel/head64.c
    ├─ 设置早期中断处理程序（idt_setup_early_handler）
    │   └─ 源代码位置：linux/arch/x86/kernel/idt.c
    ├─ TDX 早期初始化（tdx_early_init，如果支持）
    ├─ 复制引导数据（copy_bootdata）
    ├─ 加载微码更新（load_ucode_bsp）
    ├─ 设置内核高地址映射
    └─ 启动内核预留区域初始化（x86_64_start_reservations）
        └─ 最终调用 start_kernel()
```

**Linux 内核切换到 64 位长模式的详细代码：**

**源代码位置：** `linux/arch/x86/boot/compressed/head_64.S`

切换到长模式的关键代码（伪代码，展示主要步骤）：

```asm
// linux/arch/x86/boot/compressed/head_64.S
// startup_32: 32 位保护模式入口点
SYM_CODE_START(startup_32)
	.code32  // 32 位保护模式代码
	
	// 步骤 1: 设置页表（身份映射：物理地址 = 线性地址）
	// 创建页表结构：PML4 → PDPT → PD → PT
	// 每个页表项映射 4KB 或 2MB 页面
	call setup_identity_mapping
	
	// 步骤 2: 启用 PAE（Physical Address Extension）
	// 长模式必须启用 PAE
	movl	%cr4, %eax
	orl	$X86_CR4_PAE, %eax  // 设置 CR4.PAE = 1
	movl	%eax, %cr4
	
	// 步骤 3: 加载页表基址到 CR3
	leal	pgtable(%ebx), %eax  // %ebx 包含重定位后的基址
	movl	%eax, %cr3           // 设置页表基址
	
	// 步骤 4: 启用长模式（EFER.LME = 1）
	// EFER (Extended Feature Enable Register) 是 MSR 寄存器
	movl	$MSR_EFER, %ecx      // MSR 编号
	rdmsr                        // 读取当前 EFER 值到 %edx:%eax
	btsl	$_EFER_LME, %eax     // 设置 LME 位（Long Mode Enable）
	wrmsr                        // 写回 EFER
	
	// 步骤 5: 启用分页（CR0.PG = 1）
	// 这是激活长模式的最后一步
	movl	%cr0, %eax
	orl	$X86_CR0_PG, %eax     // 设置 CR0.PG = 1（启用分页）
	movl	%eax, %cr0
	
	// 步骤 6: 跳转到 64 位代码段
	// 使用 64 位代码段选择子（CS.L = 1），跳转到 startup_64
	ljmp	$__KERNEL_CS, $startup_64  // 长跳转，切换到 64 位长模式
	
	.code64  // 从这行开始，代码是 64 位的
startup_64:
	// 此时 CPU 已处于 64 位长模式
	// 可以开始使用 64 位寄存器和指令
```

**关键寄存器设置：**

1. **CR4.PAE = 1**：启用物理地址扩展（长模式必需）
2. **CR3**：页表基址（指向 PML4 表）
3. **EFER.LME = 1**：启用长模式（但此时还未激活，需要 CR0.PG）
4. **CR0.PG = 1**：启用分页（激活长模式，CPU 进入 64 位长模式）

**模式切换顺序：**

```
32 位保护模式
    ↓
设置页表（身份映射）
    ↓
启用 PAE（CR4.PAE = 1）
    ↓
加载页表基址（CR3）
    ↓
启用长模式（EFER.LME = 1）
    ↓
启用分页（CR0.PG = 1）← 此时 CPU 进入 64 位长模式
    ↓
跳转到 64 位代码段（ljmp $__KERNEL_CS, $startup_64）
    ↓
64 位长模式（startup_64）
```

**源代码位置：`linux/arch/x86/kernel/head_64.S:38-100`**

```asm
// Linux 内核 64 位启动入口点
// 此时 CPU 已处于 64 位长模式（CS.L = 1, CS.D = 0）
// Bootloader 已经加载了身份映射页表（物理地址 = 线性地址）
SYM_CODE_START_NOALIGN(startup_64)
	UNWIND_HINT_END_OF_STACK
	
	// 步骤 1: 保存 boot_params 结构地址
	// %RSI 包含 bootloader 提供的 boot_params 物理地址
	// 保存到 %R15，避免后续 C 函数调用破坏它
	// ↑ 使用 64 位寄存器（%RSI, %R15）表明这是 64 位长模式
	mov	%rsi, %r15

	// 步骤 2: 设置初始内核栈（用于 verify_cpu() 等函数）
	// ↑ 使用 %rip 相对寻址（leaq ...(%rip)），这是 64 位长模式特有
	// ↑ 使用 64 位寄存器 %rsp
	leaq	__top_init_kernel_stack(%rip), %rsp

	// 步骤 3: 设置 GS 段基址（用于 per-CPU 数据）
	// 在 SMP 系统中，启动 CPU 使用 init 数据段，直到 per-CPU 区域设置完成
	// ↑ 使用 wrmsr 指令写入 64 位 MSR 寄存器（GS_BASE）
	movl	$MSR_GS_BASE, %ecx  // MSR 寄存器编号
	xorl	%eax, %eax          // 清零 EAX（GS 基址低 32 位）
	xorl	%edx, %edx          // 清零 EDX（GS 基址高 32 位）
	wrmsr                      // 写入 MSR，设置 GS 基址为 0

	// 步骤 4: 设置 GDT（全局描述符表）和早期 IDT（中断描述符表）
	// 这是内核接管中断系统的第一步
	call	__pi_startup_64_setup_gdt_idt

	// 步骤 5: 切换到内核代码段（__KERNEL_CS），确保 IRET 正常工作
	// ↑ 使用 pushq（64 位压栈）和 lretq（64 位长返回）
	// ↑ __KERNEL_CS 是 64 位代码段选择子（CS.L = 1）
	pushq	$__KERNEL_CS        // 压入内核代码段选择子
	leaq	.Lon_kernel_cs(%rip), %rax  // 获取标签地址（%rip 相对寻址）
	pushq	%rax                // 压入返回地址
	lretq                       // 长返回：弹出 CS 和 RIP，切换到内核代码段

.Lon_kernel_cs:
	ANNOTATE_NOENDBR
	UNWIND_HINT_END_OF_STACK

#ifdef CONFIG_AMD_MEM_ENCRYPT
	// 步骤 6: 激活内存加密（SEV/SME），如果支持
	// 必须在执行 CPUID 之前完成，因为需要设置 SEV-SNP CPUID 表
	// ↑ 使用 movq（64 位移动）和 64 位寄存器 %r15, %rdi
	movq	%r15, %rdi          // 传递 boot_params 指针作为参数
	call	__pi_sme_enable
#endif

	// 步骤 7: 验证和清理 CPU 配置
	call verify_cpu
```

**64 位长模式的代码特征：**

1. **64 位寄存器**：
   - `%RSI`, `%R15`, `%RSP`, `%RAX`, `%RDX`, `%RCX`, `%RDI` 等（R 前缀表示 64 位）
   - 与 32 位模式的区别：32 位使用 `%ESI`, `%EAX` 等（E 前缀）

2. **64 位指令**：
   - `movq`（64 位移动）、`leaq`（64 位地址加载）、`pushq`（64 位压栈）、`lretq`（64 位长返回）
   - 与 32 位模式的区别：32 位使用 `movl`, `leal`, `pushl`, `lretl` 等

3. **%rip 相对寻址**：
   - `leaq __top_init_kernel_stack(%rip), %rsp` - 使用 `%rip` 相对寻址
   - 这是 64 位长模式特有的寻址方式，简化了位置无关代码（PIC）

4. **64 位代码段选择子**：
   - `__KERNEL_CS` 是 64 位代码段选择子，其描述符的 `CS.L = 1`（Long mode）
   - 与 32 位模式的区别：32 位代码段选择子的 `CS.L = 0`

5. **64 位 MSR 寄存器访问**：
   - `wrmsr` 指令写入 64 位 MSR 寄存器（`GS_BASE`）
   - 使用 `%EAX`（低 32 位）和 `%EDX`（高 32 位）组合成 64 位值

**关键步骤（体现 64 位长模式）：**
- **第 2550 行**：使用 64 位寄存器 `%RSI`, `%R15`（R 前缀表示 64 位）
- **第 2553-2556 行**：使用 `%rip` 相对寻址（`leaq ...(%rip)`），这是 64 位长模式特有
- **第 2560-2564 行**：使用 `wrmsr` 指令写入 64 位 MSR 寄存器（`GS_BASE`）
- **第 2568 行**：调用 `__pi_startup_64_setup_gdt_idt` 设置 GDT 和早期 IDT
- **第 2571-2576 行**：使用 `pushq` 和 `lretq`（64 位指令），使用 `__KERNEL_CS`（64 位代码段选择子）
- **第 2585-2586 行**：使用 `movq`（64 位移动）和 64 位寄存器 `%r15`, `%rdi`
- 此时内核已切换到 64 位长模式

**GDT 和 IDT 的区别：**

| 特性 | GDT（全局描述符表） | IDT（中断描述符表） |
|------|------------------|------------------|
| **全称** | Global Descriptor Table | Interrupt Descriptor Table |
| **用途** | 定义内存段（代码段、数据段等） | 定义中断处理程序 |
| **访问方式** | 通过段选择子（Segment Selector） | 通过中断向量号（0-255） |
| **寄存器** | GDTR（GDT 基址和界限） | IDTR（IDT 基址和界限） |
| **加载指令** | `LGDT` | `LIDT` |
| **条目内容** | 段描述符（基址、界限、权限等） | 中断门/陷阱门/任务门（处理程序地址） |
| **主要功能** | 内存分段和保护 | 中断处理和异常处理 |
| **使用场景** | 代码段、数据段、栈段的定义 | CPU 异常、硬件中断、软件中断的处理 |

**简单理解：**
- **GDT**：定义"内存段是什么"（代码段在哪里、数据段在哪里、权限如何）
- **IDT**：定义"中断发生时跳转到哪里"（INT 10h 跳到哪里、页故障跳到哪里）

