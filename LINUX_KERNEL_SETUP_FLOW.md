# Linux 内核 Setup 流程（从扇区 0 启动）

本文档详细说明 **仅从扇区 0 启动时**执行的 Linux 内核 Setup 流程：从实模式入口 `header.S` 经 `main()`、`go_to_protected_mode()`、`protected_mode_jump()` 切换到保护模式，并跳转到压缩内核入口（startup_32）。**从 GRUB 或 UEFI 启动时不执行本流程**，参见 [Linux 内核启动与初始化（不走 Setup）](LINUX_KERNEL_INIT.md)。

> **相关文档**：
> - **不走 Setup 的路径**：GRUB 按 code32_start 跳转、UEFI 按 PE 入口跳转，见 [LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md)
> - **UEFI 启动详解**：GRUB 和 Linux kernel 的 UEFI 长模式启动实现，见 [GRUB_UEFI_LONG_MODE_ANALYSIS.md](GRUB_UEFI_LONG_MODE_ANALYSIS.md)
> - 启动流程概述见 [BOOT_FLOW.md](BOOT_FLOW.md)

## 调用链（仅从扇区 0 启动时）

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

## 执行流程概览

```
Linux 内核 Setup 代码（实模式，仅从扇区 0 启动时执行）
    ├─ 源代码位置：linux/arch/x86/boot/header.S
    ├─ 内存位置：0x100000（1MB）或内核指定的地址
    ├─ 运行模式：实模式（初始阶段）
    ├─ Setup 代码是未压缩的，可以直接执行
    ├─ 验证内核签名（boot_flag = 0xAA55）
    ├─ 初始化基本环境
    ├─ 调用链：header.S（入口点）→ main() → go_to_protected_mode()
    ├─ 切换到保护模式的关键步骤（pm.c / pmjump.S）：
    │   ├─ 设置 GDT、IDT
    │   ├─ 启用 A20、屏蔽中断、设置 CR0.PE
    │   └─ protected_mode_jump() 长跳转到保护模式
    └─ 跳转到压缩内核解压代码（startup_32，32 位保护模式）
```

## 源代码：header.S（入口点）

**源代码位置：** `linux/arch/x86/boot/header.S`（仅从扇区 0 启动时由此进入）

```asm
// linux/arch/x86/boot/header.S
// 从 GRUB 启动时：GRUB 按 boot_params 中 code32_start 字段所存地址跳转，不经过此处

.code16
.section ".header", "a"
.globl	hdr
hdr:
    setup_sects:    .byte 0
    root_flags:     .word ROOT_RDONLY
    syssize:        .long 0
    ram_size:       .word 0
    vid_mode:       .word SVGA_MODE
    root_dev:       .word 0
    boot_flag:      .word 0xAA55  // 引导扇区签名
    
    // ... 更多头部字段 ...
    
    .globl _start
_start:
    movw    %cs, %ax
    movw    %ax, %ds
    movw    %ax, %es
    movw    %ax, %ss
    lss     stack_start, %esp
    cld
    calll   main  // ← 调用 main()，最终进入保护模式并跳转到 startup_32
```

## 源代码：main.c

**源代码位置：** `linux/arch/x86/boot/main.c:main()`

```c
// linux/arch/x86/boot/main.c
void main(void)
{
    copy_boot_params();
    init_heap();
    set_video();
    query_apm_bios();
    query_edd();
    detect_memory();
    keyboard_init();
    query_mca();
    query_vesa();
    query_pal();
    parse_early_param();
    /* 最后：切换到保护模式，跳转到压缩内核（startup_32） */
    go_to_protected_mode();
}
```

**main.c 的主要工作：**

1. **引导参数**：`copy_boot_params()` 复制 `boot_params`
2. **内存**：`init_heap()`、`detect_memory()`（INT 15h E820）
3. **硬件检测**：`set_video()`、`query_apm_bios()`、`query_edd()`、`query_mca()`、`query_vesa()`
4. **输入**：`keyboard_init()`
5. **参数**：`parse_early_param()` 解析内核命令行
6. **模式切换**：`go_to_protected_mode()` 切换到保护模式并跳转到 startup_32

所有工作均在实模式下完成；最后通过 `go_to_protected_mode()` 跳转到保护模式，不会返回。

## 源代码：go_to_protected_mode()

**源代码位置：** `linux/arch/x86/boot/pm.c:go_to_protected_mode()`

```c
// linux/arch/x86/boot/pm.c
void go_to_protected_mode(void)
{
    setup_gdt();
    setup_idt();
    enable_a20();
    reset_coprocessor();
    mask_all_interrupts();
    protected_mode_jump(boot_params.hdr.code32_start,
                        (u32)&boot_params + (ds() << 4));
}
```

## 源代码：setup_idt()

**源代码位置：** `linux/arch/x86/boot/pm.c:setup_idt()`

```c
// linux/arch/x86/boot/pm.c
static void setup_idt(void)
{
    static const struct gdt_ptr null_idt = {0, 0};
    asm volatile("lidtl %0" : : "m" (null_idt));
}
```

说明：Setup 阶段加载的是空 IDT（limit=0, base=0），用于在进入保护模式前后禁用中断。完整 IDT 在后续内核初始化（如 startup_64 / idt_setup_early_traps）中建立。

## 源代码：protected_mode_jump()

**源代码位置：** `linux/arch/x86/boot/pmjump.S:protected_mode_jump()`

```asm
// linux/arch/x86/boot/pmjump.S
.code16
GLOBAL(protected_mode_jump)
    cli
    movl    %eax, %edx
    inb     $0x70, %al
    orl     $0x80, %eax
    outb    %al, $0x70
    lgdt    gdt_descriptor
    movl    %cr0, %eax
    orl     $X86_CR0_PE, %eax
    movl    %eax, %cr0
    ljmp    $__BOOT_CS, $1f
    .code32
1:
    movl    $__BOOT_DS, %eax
    movl    %eax, %ds
    movl    %eax, %es
    movl    %eax, %fs
    movl    %eax, %gs
    movl    %eax, %ss
    leal    boot_stack_end, %esp
    jmp     *%edx  // %edx = code32_start 字段的值，跳转到 startup_32
```

**关键寄存器设置：** GDT 通过 `lgdt` 加载；CR0.PE = 1 启用保护模式；段选择子 `__BOOT_CS`、`__BOOT_DS`；跳转目标由 `code32_start` 指定（压缩内核入口，如 startup_32）。

## 模式切换顺序（从扇区 0 启动时）

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
32 位保护模式（startup_32，压缩内核）
```

此后流程与“不走 Setup”路径汇合：压缩内核 startup_32 解压并切换到 64 位长模式，详见 [LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md)。
