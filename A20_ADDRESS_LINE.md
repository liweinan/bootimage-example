# A20 地址线技术详解

本文档详细介绍了 x86 架构中 A20 地址线的历史背景、工作原理和启用方法。

---

## A20 地址线简介

A20（Address Line 20）是 x86 架构中的第 21 根地址线（从 0 开始计数），用于访问 1MB 以上的内存。

**历史背景：**

1. **8086/8088 的限制**：
   - 早期 8086/8088 CPU 只有 20 根地址线（A0-A19）
   - 最大寻址空间：2^20 = 1MB（0x00000 - 0xFFFFF）
   - 地址计算：段地址 × 16 + 偏移地址（最大 0xFFFF:0xFFFF = 0x10FFEF）

2. **地址回绕问题**：
   - 在 8086 上，地址 0xFFFF:0x0010 = 0x100000 会回绕到 0x00000
   - 这是为了兼容某些早期软件（如 DOS）的 bug

3. **80286 的改进**：
   - 80286 引入了 24 根地址线（A0-A23），可访问 16MB
   - 但为了兼容性，A20 地址线默认被**禁用**（强制为 0）
   - 这导致地址 0x100000 仍然回绕到 0x00000

4. **A20 Gate（A20 门）**：
   - A20 Gate 是一个硬件开关，控制 A20 地址线是否有效
   - 当 A20 被禁用时，访问 0x100000 会回绕到 0x00000
   - 当 A20 被启用时，可以正常访问 1MB 以上的内存

**为什么需要启用 A20？**

- **保护模式需求**：保护模式需要访问 1MB 以上的内存（用于内核、驱动等）
- **32 位寻址**：32 位保护模式可以寻址 4GB（0x00000000 - 0xFFFFFFFF）
- **内存管理**：现代操作系统需要管理大量内存，必须启用 A20

**A20 的启用方法：**

1. **BIOS 调用**（最可靠）：`INT 15h, AX=2401h`
2. **系统控制端口 A**（0x92）：快速方法，但可能不兼容所有硬件
3. **键盘控制器**（8042）：传统方法，兼容性好但较慢

**启用 A20 地址线：**

**源代码位置：`grub/grub-core/boot/i386/pc/startup_raw.S:135-214`**

```asm
// grub_gate_a20 - 启用 A20 地址线，允许访问 1MB 以上内存
grub_gate_a20:
    // 首先检查 A20 是否已启用
    call    gate_a20_check_state
    testb   %al, %al
    jnz     gate_a20_try_bios
    ret     // 已启用，直接返回
    
gate_a20_try_bios:
    // 方法 1: 尝试使用 BIOS 调用（INT 15h, AX=2401h）
    pushl   %ebp
    call    prot_to_real  // 临时切换回实模式
    .code16
    movw    $0x2401, %ax
    int     $0x15
    calll   real_to_prot  // 切换回保护模式
    .code32
    popl    %ebp
    
    call    gate_a20_check_state
    testb   %al, %al
    jnz     gate_a20_try_system_control_port_a
    ret
    
gate_a20_try_system_control_port_a:
    // 方法 2: 尝试使用系统控制端口 A（0x92）
    inb     $0x92
    andb    $(~0x03), %al
    orb     $0x02, %al
    outb    $0x92
    
    call    gate_a20_check_state
    testb   %al, %al
    jnz     gate_a20_try_keyboard_controller
    ret
    
gate_a20_try_keyboard_controller:
    // 方法 3: 尝试使用键盘控制器（8042）
    call    gate_a20_flush_keyboard_buffer
    
    movb    $0xd1, %al
    outb    $0x64  // 发送命令到键盘控制器
    
    // 等待键盘控制器就绪
    // ... 等待代码 ...
    
    movb    $0xdf, %al
    outb    $0x60  // 启用 A20
    
    call    gate_a20_check_state
    testb   %al, %al
    jnz     gate_a20_try_bios  // 失败，重试 BIOS 方法
    ret
```

