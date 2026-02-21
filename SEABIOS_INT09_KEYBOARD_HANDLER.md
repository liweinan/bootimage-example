# SeaBIOS INT 09h 键盘中断处理程序分析

> 本文档深入分析 SeaBIOS 中 INT 09h (键盘硬件中断) 的实现，包括汇编入口点、寄存器保存机制、扫描码处理流程和键盘缓冲区管理。

## 目录

1. [概述](#1-概述)
2. [中断处理流程总览](#2-中断处理流程总览)
3. [汇编入口点 entry_09](#3-汇编入口点-entry_09)
4. [寄存器保存机制](#4-寄存器保存机制)
5. [C 函数 handle_09](#5-c-函数-handle_09)
6. [扫描码处理 process_key](#6-扫描码处理-process_key)
7. [键盘缓冲区管理](#7-键盘缓冲区管理)
8. [I/O 端口和常量定义](#8-io-端口和常量定义)
9. [与 TSR 程序的对比](#9-与-tsr-程序的对比)
10. [参考资料](#10-参考资料)

---

## 1. 概述

INT 09h 是 PC 架构中的键盘硬件中断，由 8042 键盘控制器通过 IRQ1 触发。每当用户按下或释放一个键，键盘控制器就会产生这个中断。

**SeaBIOS 的 INT 09h 处理流程:**

```
键盘按下
    │
    ▼
8042 键盘控制器 → IRQ1 → 8259A PIC → CPU 触发 INT 09h
    │
    ▼
entry_09 (汇编入口) → 保存寄存器 → handle_09 (C函数)
    │
    ▼
process_key() → __process_key() → enqueue_key()
    │
    ▼
恢复寄存器 → pic_eoi1() → iretw 返回
```

---

## 2. 中断处理流程总览

### 2.1 完整的调用链

```
┌─────────────────────────────────────────────────────────────────┐
│  1. CPU 硬件响应                                                │
│     - 自动压栈: FLAGS, CS, IP                                   │
│     - 跳转到 IVT[0x09] 指向的地址                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. entry_09 (src/romlayout.S:628)                              │
│     - 压入 handle_09 函数地址                                   │
│     - 跳转到 irqentry_extrastack                                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. irqentry_extrastack (src/romlayout.S:471)                   │
│     - 切换到 BIOS 专用栈 (ExtraStack)                          │
│     - 保存所有通用寄存器和段寄存器                              │
│     - 调用 handle_09()                                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. handle_09 (src/hw/ps2port.c:391)                            │
│     - 读取 8042 状态和扫描码                                    │
│     - 调用 process_key()                                        │
│     - 重新启用键盘                                              │
│     - 发送 EOI 给 PIC                                           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  5. process_key (src/kbd.c:582)                                 │
│     - 可选: 调用 INT 15h/AH=4Fh 钩子                           │
│     - 调用 __process_key()                                      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  6. __process_key (src/kbd.c:456)                               │
│     - 处理多字节扫描码序列 (E0/E1)                             │
│     - 更新修饰键状态 (Shift/Ctrl/Alt)                          │
│     - 处理特殊组合键 (Ctrl+Alt+Del 等)                         │
│     - 扫描码转键码，调用 enqueue_key()                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  7. enqueue_key (src/kbd.c:33)                                  │
│     - 将键码放入 BDA 键盘缓冲区                                │
│     - 更新缓冲区尾指针                                          │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. 汇编入口点 entry_09

### 3.1 IRQ_ENTRY 宏定义

```asm
; src/romlayout.S:536-541

        .macro IRQ_ENTRY num
        .global entry_\num
        entry_\num :
        pushl $ handle_\num      ; 将 C 函数地址压栈
        jmp irqentry_extrastack  ; 跳转到通用处理代码
        .endm
```

### 3.2 entry_09 的生成

```asm
; src/romlayout.S:627-628

        ORG 0xe987               ; 固定地址 (BIOS 兼容性要求)
        IRQ_ENTRY 09             ; 生成 entry_09
```

展开后等价于:

```asm
entry_09:
        pushl $ handle_09        ; 压入 C 函数地址
        jmp irqentry_extrastack  ; 跳转到寄存器保存代码
```

**地址 0xE987**: 这是 IBM PC BIOS 规范要求的 INT 09h 入口点地址，位于 ROM 的固定位置以保持兼容性。

---

## 4. 寄存器保存机制

### 4.1 irqentry_extrastack 函数

```asm
; src/romlayout.S:470-494

        DECLFUNC irqentry_extrastack
irqentry_extrastack:
        cli                              ; 关中断
        cld                              ; 清方向标志
        pushw %ds                        ; 临时保存 DS
        pushl %eax                       ; 临时保存 EAX
        
        ; 设置 DS 指向 BIOS 低端内存区
        movl $_zonelow_seg, %eax
        movl %eax, %ds
        
        ; 在 ExtraStack 上分配空间
        movl StackPos, %eax
        subl $PUSHBREGS_size+8, %eax     ; PUSHBREGS_size=32, 总共40字节
        
        SAVEBREGS_POP_DSEAX              ; 保存所有寄存器到 ExtraStack
        
        popl %ecx                        ; ECX = handle_09 地址
        movl %esp, PUSHBREGS_size(%eax)  ; 保存原 ESP
        movw %ss, PUSHBREGS_size+4(%eax) ; 保存原 SS

        ; 切换到 ExtraStack
        movw %ds, %dx
        movw %dx, %ss
        movl %eax, %esp
        
        calll *%ecx                      ; 调用 handle_09()

        ; 恢复原栈
        movl %esp, %eax
        movw PUSHBREGS_size+4(%eax), %ss
        movl PUSHBREGS_size(%eax), %esp
        
        RESTOREBREGS_DSEAX               ; 恢复所有寄存器
        iretw                            ; 中断返回
```

### 4.2 SAVEBREGS_POP_DSEAX 宏

```asm
; src/entryfuncs.S:43-53

        .macro SAVEBREGS_POP_DSEAX
        popl BREGS_eax(%eax)             ; 从临时栈弹出 EAX，保存到结构体
        popw BREGS_ds(%eax)              ; 从临时栈弹出 DS，保存到结构体
        movl %edi, BREGS_edi(%eax)       ; 保存 EDI
        movl %esi, BREGS_esi(%eax)       ; 保存 ESI
        movl %ebp, BREGS_ebp(%eax)       ; 保存 EBP
        movl %ebx, BREGS_ebx(%eax)       ; 保存 EBX
        movl %edx, BREGS_edx(%eax)       ; 保存 EDX
        movl %ecx, BREGS_ecx(%eax)       ; 保存 ECX
        movw %es, BREGS_es(%eax)         ; 保存 ES
        .endm
```

### 4.3 RESTOREBREGS_DSEAX 宏

```asm
; src/entryfuncs.S:56-67

        .macro RESTOREBREGS_DSEAX
        movl BREGS_edi(%eax), %edi       ; 恢复 EDI
        movl BREGS_esi(%eax), %esi       ; 恢复 ESI
        movl BREGS_ebp(%eax), %ebp       ; 恢复 EBP
        movl BREGS_ebx(%eax), %ebx       ; 恢复 EBX
        movl BREGS_edx(%eax), %edx       ; 恢复 EDX
        movl BREGS_ecx(%eax), %ecx       ; 恢复 ECX
        movw BREGS_es(%eax), %es         ; 恢复 ES
        pushl BREGS_eax(%eax)            ; 压入 EAX 值
        movw BREGS_ds(%eax), %ds         ; 恢复 DS
        popl %eax                        ; 恢复 EAX
        .endm
```

### 4.4 struct bregs 结构体布局

```
PUSHBREGS_size = 32 字节

偏移    字段        大小    说明
─────────────────────────────────────
0x00    DS          2       数据段寄存器
0x02    ES          2       附加段寄存器
0x04    EDI         4       目的变址寄存器
0x08    ESI         4       源变址寄存器
0x0C    EBP         4       基址指针寄存器
0x10    EBX         4       基址寄存器
0x14    EDX         4       数据寄存器
0x18    ECX         4       计数寄存器
0x1C    EAX         4       累加器
─────────────────────────────────────
+32     原 ESP      4       被中断程序的栈指针
+36     原 SS       2       被中断程序的栈段
```

### 4.5 完整的栈帧布局

```
中断发生时的栈状态:

被中断程序的栈 (原 SS:ESP)                    ExtraStack (BIOS 专用栈)
┌─────────────────────────┐                   ┌─────────────────────────┐
│  ...                    │                   │  DS        (0x00)       │
│  被中断程序的数据       │                   │  ES        (0x02)       │
├─────────────────────────┤                   │  EDI       (0x04)       │
│  FLAGS  ← CPU 自动压入  │                   │  ESI       (0x08)       │
│  CS                     │                   │  EBP       (0x0C)       │
│  IP                     │                   │  EBX       (0x10)       │
├─────────────────────────┤                   │  EDX       (0x14)       │
│  &handle_09 ← entry_09  │                   │  ECX       (0x18)       │
│  EAX (临时)             │                   │  EAX       (0x1C)       │
│  DS  (临时)             │                   ├─────────────────────────┤
└─────────────────────────┘                   │  原 ESP    (0x20)       │
        │                                     │  原 SS     (0x24)       │
        └──── 保存到 ────────────────────────►└─────────────────────────┘
                                                      │
                                                      ▼
                                              handle_09() 在此栈上运行
```

**为什么使用 ExtraStack?**

1. **安全性**: 被中断的程序可能栈空间不足或已损坏
2. **隔离性**: BIOS 代码不依赖用户程序的栈
3. **可预测性**: 固定的栈空间便于调试

---

## 5. C 函数 handle_09

```c
// src/hw/ps2port.c:389-417

// INT09h : Keyboard Hardware Service Entry Point
void VISIBLE16
handle_09(void)
{
    if (! CONFIG_PS2PORT)
        return;

    debug_isr(DEBUG_ISR_09);

    // 步骤 1: 读取 8042 控制器状态
    u8 v = inb(PORT_PS2_STATUS);        // 读端口 0x64
    
    // 步骤 2: 检查是否是鼠标数据 (不应该出现)
    if (v & I8042_STR_AUXDATA) {
        dprintf(1, "ps2 keyboard irq but found mouse data?!\n");
        goto done;
    }
    
    // 步骤 3: 读取扫描码
    v = inb(PORT_PS2_DATA);             // 读端口 0x60

    // 步骤 4: 检查键盘中断是否启用
    if (!(GET_LOW(Ps2ctr) & I8042_CTR_KBDINT))
        goto done;

    // 步骤 5: 处理按键
    process_key(v);

    // 步骤 6: 重新启用键盘 (兼容老程序)
    i8042_command(I8042_CMD_KBD_ENABLE, NULL);

done:
    // 步骤 7: 发送 EOI 给 PIC
    pic_eoi1();
}
```

### 5.1 关键步骤说明

| 步骤 | 代码 | 说明 |
|------|------|------|
| 1 | `inb(PORT_PS2_STATUS)` | 读取 8042 状态寄存器 (端口 0x64) |
| 2 | `v & I8042_STR_AUXDATA` | 检查 bit5，判断数据来自键盘还是鼠标 |
| 3 | `inb(PORT_PS2_DATA)` | 从数据端口 0x60 读取扫描码 |
| 4 | `GET_LOW(Ps2ctr) & I8042_CTR_KBDINT` | 检查键盘中断是否已启用 |
| 5 | `process_key(v)` | 调用扫描码处理函数 |
| 6 | `i8042_command(I8042_CMD_KBD_ENABLE, NULL)` | 某些老程序需要 BIOS 重新启用键盘 |
| 7 | `pic_eoi1()` | 向主 PIC 发送 EOI，允许下一个 IRQ |

### 5.2 pic_eoi1 函数

```c
// src/hw/pic.h:35-38

static inline void
pic_eoi1(void)
{
    outb(PIC1_IRQ5, PORT_PIC1_CMD);    // 向端口 0x20 写入 0x20
}
```

EOI (End Of Interrupt) 信号告诉 8259A PIC 当前中断已处理完毕，可以接受同级或更低优先级的中断。

---

## 6. 扫描码处理 process_key

### 6.1 process_key 函数

```c
// src/kbd.c:582-599

void
process_key(u8 key)
{
    if (!CONFIG_KEYBOARD)
        return;

    // INT 15h/AH=4Fh 钩子 - 允许 TSR 拦截按键
    if (CONFIG_KBD_CALL_INT15_4F) {
        struct bregs br;
        memset(&br, 0, sizeof(br));
        br.eax = (0x4f << 8) | key;     // AH=4Fh, AL=扫描码
        br.flags = F_IF|F_CF;           // 设置 CF=1
        call16_int(0x15, &br);          // 调用 INT 15h
        if (!(br.flags & F_CF))         // 如果 CF=0，按键被拦截
            return;
        key = br.eax;                   // TSR 可能修改了扫描码
    }
    __process_key(key);
}
```

**INT 15h/AH=4Fh 钩子**:

这是 BIOS 提供的官方键盘拦截接口，TSR 程序可以:
- 钩住 INT 15h
- 检查 AH=4Fh 调用
- 检查/修改 AL 中的扫描码
- 设置 CF=0 表示已处理 (阻止按键)
- 设置 CF=1 表示继续处理

### 6.2 __process_key 核心处理函数

```c
// src/kbd.c:456-579

static void
__process_key(u8 scancode)
{
    // ─────────────────────────────────────────────────────────
    // 阶段 1: 处理多字节扫描码序列
    // ─────────────────────────────────────────────────────────
    u8 flags1 = GET_BDA(kbd_flag1);
    if (scancode == 0xe0 || scancode == 0xe1) {
        // E0: 扩展键前缀 (如方向键、小键盘回车)
        // E1: Pause 键前缀 (3字节序列: E1 1D 45)
        u8 eflag = scancode == 0xe0 ? KF1_LAST_E0 : KF1_LAST_E1;
        SET_BDA(kbd_flag1, flags1 | eflag);
        return;
    }
    
    // ─────────────────────────────────────────────────────────
    // 阶段 2: 判断按下/释放
    // ─────────────────────────────────────────────────────────
    int key_release = scancode & 0x80;  // bit7=1 表示释放
    scancode &= ~0x80;                   // 清除释放标志
    
    if (flags1 & (KF1_LAST_E0|KF1_LAST_E1)) {
        if (flags1 & KF1_LAST_E1 && scancode == 0x1d)
            return;  // 忽略 Pause 键的第二字节
        SET_BDA(kbd_flag1, flags1 & ~(KF1_LAST_E0|KF1_LAST_E1));
    }

    // ─────────────────────────────────────────────────────────
    // 阶段 3: 处理修饰键
    // ─────────────────────────────────────────────────────────
    switch (scancode) {
    case 0x3a: /* Caps Lock */
        kbd_set_flag(key_release, KF0_CAPS, 0, KF0_CAPSACTIVE);
        return;
    case 0x2a: /* L Shift */
        if (flags1 & KF1_LAST_E0) return;  // 忽略假 Shift
        kbd_set_flag(key_release, KF0_LSHIFT, 0, 0);
        return;
    case 0x36: /* R Shift */
        if (flags1 & KF1_LAST_E0) return;
        kbd_set_flag(key_release, KF0_RSHIFT, 0, 0);
        return;
    case 0x1d: /* Ctrl */
        if (flags1 & KF1_LAST_E0)
            kbd_set_flag(key_release, KF0_CTRLACTIVE, KF1_RCTRL, 0);
        else
            kbd_set_flag(key_release, KF0_CTRLACTIVE | KF0_LCTRL, 0, 0);
        return;
    case 0x38: /* Alt */
        if (flags1 & KF1_LAST_E0)
            kbd_set_flag(key_release, KF0_ALTACTIVE, KF1_RALT, 0);
        else
            kbd_set_flag(key_release, KF0_ALTACTIVE | KF0_LALT, 0, 0);
        return;
    case 0x45: /* Num Lock */
        if (flags1 & KF1_LAST_E1) return;  // Pause 键
        kbd_set_flag(key_release, KF0_NUM, 0, KF0_NUMACTIVE);
        return;
    case 0x46: /* Scroll Lock */
        if (flags1 & KF1_LAST_E0) {
            kbd_ctrl_break(key_release);   // Ctrl+Break
            return;
        }
        kbd_set_flag(key_release, KF0_SCROLL, 0, KF0_SCROLLACTIVE);
        return;
    // ...
    }

    // ─────────────────────────────────────────────────────────
    // 阶段 4: 处理特殊组合键
    // ─────────────────────────────────────────────────────────
    switch (scancode) {
    case 0x37: /* * (PrtScr) */
        if (flags1 & KF1_LAST_E0) {
            kbd_prtscr(key_release);       // 生成 INT 05h
            return;
        }
        break;
    case 0x54: /* SysReq */
        kbd_sysreq(key_release);           // 生成 INT 15h/AH=85h
        return;
    case 0x53: /* Del */
        if ((GET_BDA(kbd_flag0) & (KF0_CTRLACTIVE|KF0_ALTACTIVE))
            == (KF0_CTRLACTIVE|KF0_ALTACTIVE) && !key_release) {
            SET_BDA(soft_reset_flag, 0x1234);
            reset();                       // Ctrl+Alt+Del 重启!
        }
        break;
    }

    // ─────────────────────────────────────────────────────────
    // 阶段 5: 普通按键处理
    // ─────────────────────────────────────────────────────────
    if (key_release)
        return;  // 忽略释放事件
        
    if (!scancode || scancode >= ARRAY_SIZE(scan_to_keycode)) {
        dprintf(1, "__process_key unknown scancode: 0x%02x!\n", scancode);
        return;
    }
    
    // 查表转换: 扫描码 → 键码
    struct scaninfo *info = &scan_to_keycode[scancode];
    // ... 处理扩展键 ...
    
    u16 flags0 = GET_BDA(kbd_flag0);
    u16 keycode;
    if (flags0 & KF0_ALTACTIVE) {
        keycode = GET_GLOBAL(info->alt);
    } else if (flags0 & KF0_CTRLACTIVE) {
        keycode = GET_GLOBAL(info->control);
    } else {
        u8 useshift = flags0 & (KF0_RSHIFT|KF0_LSHIFT) ? 1 : 0;
        // 处理 CapsLock 和 NumLock
        // ...
        if (useshift)
            keycode = GET_GLOBAL(info->shift);
        else
            keycode = GET_GLOBAL(info->normal);
    }
    
    // ─────────────────────────────────────────────────────────
    // 阶段 6: 放入键盘缓冲区
    // ─────────────────────────────────────────────────────────
    if (keycode)
        enqueue_key(keycode);
}
```

### 6.3 扫描码转换表

```c
// src/kbd.c:274-369

static struct scaninfo {
    u16 normal;      // 普通状态
    u16 shift;       // Shift 状态
    u16 control;     // Ctrl 状态
    u16 alt;         // Alt 状态
} scan_to_keycode[] VAR16 = {
    {   none,   none,   none,   none },     // 0x00
    { 0x011b, 0x011b, 0x011b, 0x01f0 },     // 0x01 ESC
    { 0x0231, 0x0221,   none, 0x7800 },     // 0x02 1!
    { 0x0332, 0x0340, 0x0300, 0x7900 },     // 0x03 2@
    // ...
    { 0x1071, 0x1051, 0x1011, 0x1000 },     // 0x10 Q
    { 0x1177, 0x1157, 0x1117, 0x1100 },     // 0x11 W
    // ...
    { 0x3b00, 0x5400, 0x5e00, 0x6800 },     // 0x3B F1
    { 0x3c00, 0x5500, 0x5f00, 0x6900 },     // 0x3C F2
    // ...
    { 0x8500, 0x8700, 0x8900, 0x8b00 },     // 0x57 F11
    { 0x8600, 0x8800, 0x8a00, 0x8c00 },     // 0x58 F12
};
```

**键码格式 (16位)**:
- 高字节: 扫描码
- 低字节: ASCII 码 (功能键为 0)

例如:
- ESC: 0x011B (扫描码 0x01, ASCII 0x1B)
- 'A': 0x1E41 (扫描码 0x1E, ASCII 0x41)
- F1:  0x3B00 (扫描码 0x3B, ASCII 0x00)

---

## 7. 键盘缓冲区管理

### 7.1 enqueue_key 函数

```c
// src/kbd.c:33-52

u8
enqueue_key(u16 keycode)
{
    // 获取缓冲区边界
    u16 buffer_start = GET_BDA(kbd_buf_start_offset);
    u16 buffer_end   = GET_BDA(kbd_buf_end_offset);

    // 获取当前读/写指针
    u16 buffer_head = GET_BDA(kbd_buf_head);
    u16 buffer_tail = GET_BDA(kbd_buf_tail);

    // 计算新的尾指针
    u16 temp_tail = buffer_tail;
    buffer_tail += 2;                    // 每个键码 2 字节
    if (buffer_tail >= buffer_end)
        buffer_tail = buffer_start;      // 环绕

    // 检查缓冲区是否已满
    if (buffer_tail == buffer_head)
        return 0;                        // 缓冲区满，丢弃按键

    // 写入键码
    SET_FARVAR(SEG_BDA, *(u16*)(temp_tail+0), keycode);
    SET_BDA(kbd_buf_tail, buffer_tail);
    return 1;
}
```

### 7.2 BDA 键盘缓冲区结构

```
BIOS Data Area (BDA) @ 0x0040:0000

偏移    大小    说明
─────────────────────────────────────────────────────
0x17    1       kbd_flag0 - 键盘状态标志 0
                  bit 7: Insert 状态
                  bit 6: Caps Lock 状态
                  bit 5: Num Lock 状态
                  bit 4: Scroll Lock 状态
                  bit 3: Alt 按下
                  bit 2: Ctrl 按下
                  bit 1: Left Shift 按下
                  bit 0: Right Shift 按下

0x18    1       kbd_flag1 - 键盘状态标志 1
                  bit 7: Insert 按下
                  bit 6: Caps Lock 按下
                  bit 5: Num Lock 按下
                  bit 4: Scroll Lock 按下
                  bit 3: Pause 状态
                  bit 2: SysReq 按下
                  bit 1: Left Alt 按下
                  bit 0: Left Ctrl 按下

0x1A    2       kbd_buf_head - 缓冲区读指针 (偏移)
0x1C    2       kbd_buf_tail - 缓冲区写指针 (偏移)
0x1E    32      kbd_buf - 键盘缓冲区 (16 个键码)

0x80    2       kbd_buf_start_offset - 缓冲区起始偏移
0x82    2       kbd_buf_end_offset - 缓冲区结束偏移
```

### 7.3 环形缓冲区工作原理

```
初始状态: head = tail = 0x1E (空)

写入 'A' (0x1E41):
  ┌─────┬─────┬─────┬─────┬─────┐
  │1E41 │     │     │     │ ... │
  └─────┴─────┴─────┴─────┴─────┘
    ↑
   head                    tail=0x20

写入 'B' (0x3042):
  ┌─────┬─────┬─────┬─────┬─────┐
  │1E41 │3042 │     │     │ ... │
  └─────┴─────┴─────┴─────┴─────┘
    ↑           
   head                    tail=0x22

读取一个键 (返回 0x1E41):
  ┌─────┬─────┬─────┬─────┬─────┐
  │     │3042 │     │     │ ... │
  └─────┴─────┴─────┴─────┴─────┘
          ↑
         head              tail=0x22
```

---

## 8. I/O 端口和常量定义

### 8.1 8042 键盘控制器端口

```c
// src/hw/ps2port.h:7-8

#define PORT_PS2_DATA          0x0060    // 数据端口
#define PORT_PS2_STATUS        0x0064    // 状态/命令端口
```

| 端口 | 读操作 | 写操作 |
|------|--------|--------|
| 0x60 | 读取扫描码 | 发送命令给键盘 |
| 0x64 | 读取状态寄存器 | 发送命令给控制器 |

### 8.2 状态寄存器位定义

```c
// src/hw/ps2port.h:42-50

#define I8042_STR_PARITY        0x80    // bit 7: 奇偶校验错误
#define I8042_STR_TIMEOUT       0x40    // bit 6: 超时错误
#define I8042_STR_AUXDATA       0x20    // bit 5: 数据来自鼠标
#define I8042_STR_KEYLOCK       0x10    // bit 4: 键盘锁定
#define I8042_STR_CMDDAT        0x08    // bit 3: 命令/数据标志
#define I8042_STR_MUXERR        0x04    // bit 2: MUX 错误
#define I8042_STR_IBF           0x02    // bit 1: 输入缓冲区满
#define I8042_STR_OBF           0x01    // bit 0: 输出缓冲区满 (有数据可读)
```

### 8.3 控制寄存器位定义

```c
// src/hw/ps2port.h:52-58

#define I8042_CTR_KBDINT        0x01    // bit 0: 启用键盘中断
#define I8042_CTR_AUXINT        0x02    // bit 1: 启用鼠标中断
#define I8042_CTR_IGNKEYLOCK    0x08    // bit 3: 忽略键盘锁
#define I8042_CTR_KBDDIS        0x10    // bit 4: 禁用键盘
#define I8042_CTR_AUXDIS        0x20    // bit 5: 禁用鼠标
#define I8042_CTR_XLATE         0x40    // bit 6: 扫描码转换
```

### 8.4 常用扫描码

```
主键盘区:
  ESC=01  1=02  2=03  3=04  4=05  5=06  6=07  7=08  8=09  9=0A  0=0B
  Q=10    W=11  E=12  R=13  T=14  Y=15  U=16  I=17  O=18  P=19
  A=1E    S=1F  D=20  F=21  G=22  H=23  J=24  K=25  L=26
  Z=2C    X=2D  C=2E  V=2F  B=30  N=31  M=32

修饰键:
  L-Shift=2A  R-Shift=36  L-Ctrl=1D  R-Ctrl=E0 1D
  L-Alt=38    R-Alt=E0 38
  CapsLock=3A NumLock=45  ScrollLock=46

功能键:
  F1=3B  F2=3C  F3=3D  F4=3E  F5=3F  F6=40  F7=41  F8=42  F9=43  F10=44
  F11=57 F12=58

特殊:
  Enter=1C  Backspace=0E  Tab=0F  Space=39
  释放键 = 按下扫描码 + 0x80 (如 ESC 释放 = 0x81)
```

---

## 9. 与 TSR 程序的对比

### 9.1 处理流程对比

```
┌─────────────────────────────────────────────────────────────────┐
│  键盘按下                                                        │
│      │                                                          │
│      ▼                                                          │
│  8042 → IRQ1 → PIC → CPU 触发 INT 09h                          │
│      │                                                          │
│      ▼                                                          │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  TSR 的 new_int09 (如果已安装)                           │   │
│  │    1. push 保存寄存器                                    │   │
│  │    2. in al, 60h 读取扫描码                              │   │
│  │    3. 检查是否是热键                                      │   │
│  │    4. 如果是 → 显示弹窗                                   │   │
│  │    5. pop 恢复寄存器                                      │   │
│  │    6. jmp far [old_int09] ─────────────────────────┐     │   │
│  └────────────────────────────────────────────────────│─────┘   │
│                                                        │         │
│      ┌────────────────────────────────────────────────┘         │
│      ▼                                                          │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  SeaBIOS entry_09 → irqentry_extrastack                  │   │
│  │    1. 切换到 ExtraStack                                   │   │
│  │    2. SAVEBREGS 保存所有寄存器                           │   │
│  │    3. call handle_09()                                    │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  handle_09 (C 函数)                                       │   │
│  │    1. inb(0x64) 检查状态                                  │   │
│  │    2. inb(0x60) 读取扫描码                                │   │
│  │    3. process_key() → __process_key()                    │   │
│  │    4. enqueue_key() 放入键盘缓冲区                       │   │
│  │    5. pic_eoi1() 发送 EOI                                │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  irqentry_extrastack (继续)                               │   │
│  │    1. RESTOREBREGS 恢复所有寄存器                        │   │
│  │    2. 切换回原栈                                          │   │
│  │    3. iretw 返回被中断的程序                              │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 9.2 实现对比表

| 项目 | TSR 程序 | SeaBIOS |
|------|----------|---------|
| **语言** | 纯汇编 | 汇编入口 + C 函数 |
| **栈位置** | 被中断程序的栈 | ExtraStack (BIOS 专用) |
| **保存方式** | 手动 push/pop | 宏 + 结构体 |
| **保存内容** | AX,BX,CX,DX,SI,DI,DS,ES | 同上 + EBP + 原 SS:ESP |
| **扫描码处理** | 简单比较 | 完整状态机 |
| **键盘缓冲区** | 不处理 (链式调用) | 维护 BDA 缓冲区 |
| **EOI 发送** | 由 BIOS 处理 | pic_eoi1() |
| **修饰键处理** | 不处理 | 完整的 Shift/Ctrl/Alt 状态 |

### 9.3 TSR 能工作的原因

1. **端口 0x60 可重复读取**: 扫描码保留在 8042 输出缓冲区，直到发送 EOI
2. **链式调用**: TSR 只是"偷看"扫描码，BIOS 仍然完成完整处理
3. **中断链**: 多个 TSR 可以串联，每个都有机会处理按键

---

## 10. 参考资料

### 10.1 SeaBIOS 源码文件

| 文件 | 说明 |
|------|------|
| `src/romlayout.S` | 汇编入口点和中断处理框架 |
| `src/entryfuncs.S` | 寄存器保存/恢复宏定义 |
| `src/hw/ps2port.c` | 8042 控制器驱动和 INT 09h/74h 处理 |
| `src/hw/ps2port.h` | PS/2 端口常量定义 |
| `src/kbd.c` | 键盘服务 (INT 16h) 和扫描码处理 |
| `src/hw/pic.h` | PIC 控制函数 |
| `src/biosvar.h` | BDA 结构定义 |

### 10.2 相关文档

- [DOS TSR 程序详解](DOS_TSR_EXPLAINED.md) - TSR 工作原理和示例代码
- [BIOS 中断服务](BIOS_INTERRUPT_COMPLETE.md) - BIOS 中断向量表
- [Linux 内核中断处理](LINUX_INTERRUPT_HANDLING.md) - 现代操作系统的中断处理

### 10.3 外部参考

- [OSDev Wiki - 8042 PS/2 Controller](https://wiki.osdev.org/PS/2_Controller)
- [OSDev Wiki - Keyboard](https://wiki.osdev.org/Keyboard)
- [SeaBIOS 官方文档](https://www.seabios.org/SeaBIOS)

---

**文档版本**: 1.0  
**最后更新**: 2026-01-30  
**作者**: 基于 SeaBIOS 源码分析
