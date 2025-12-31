# BIOS 中断实现原理与学习指南

## 目录
- [一、BIOS 中断机制详解](#一bios-中断机制详解)
- [二、开源 BIOS 项目学习资源](#二开源-bios-项目学习资源)
- [三、虚拟机实现源码学习](#三虚拟机实现源码学习)
- [四、硬件文档资源](#四硬件文档资源)
- [五、学习路径与实践](#五学习路径与实践)
- [六、实用命令速查](#六实用命令速查)

## 一、BIOS 中断机制详解

### 1.1 中断向量表（IVT）的工作原理

在实模式下，BIOS 在内存低地址（0x0000-0x03FF）维护中断向量表：

- **每个中断号对应一个 4 字节的向量**（段地址:偏移地址）
- **中断 0x10 的向量位于** `0x10 * 4 = 0x0040`
- **这 4 字节指向 BIOS 视频服务例程的入口地址**

**中断向量表结构**：
```
地址范围：0x0000 - 0x03FF（1024 字节）
每个中断向量：4 字节
  - 低 2 字节：偏移地址（IP）
  - 高 2 字节：段地址（CS）

示例：INT 10h 向量
  地址 0x0040: [偏移地址低字节]
  地址 0x0041: [偏移地址高字节]
  地址 0x0042: [段地址低字节]
  地址 0x0043: [段地址高字节]
```

### 1.2 `int 0x10` 的完整执行流程

当执行 `int 0x10` 时，CPU 会执行以下步骤：

```
┌─────────────────────────────────────────────────────────┐
│ 1. 保存当前状态（CPU硬件自动完成）                        │
│    - 将标志寄存器（FLAGS）压入栈                          │
│    - 将当前代码段（CS）压入栈                             │
│    - 将下一条指令地址（IP）压入栈                         │
│    - 清除中断标志（IF）和陷阱标志（TF）                    │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ 2. 查找中断向量                                            │
│    - 从内存地址 0x0040 读取 4 字节                         │
│    - 这 4 字节包含：偏移地址（低 2 字节）+ 段地址（高 2 字节）│
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ 3. 跳转到中断处理程序                                      │
│    - 将 CS:IP 设置为向量表中的地址                         │
│    - CPU 开始执行 BIOS 的视频服务代码                      │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ 4. BIOS 处理程序执行                                       │
│    - 读取寄存器参数（如 ah=0x0E 或 ax=0x0003）            │
│    - 根据功能号执行相应的视频操作                          │
│    - 操作完成后执行 IRET（中断返回）                       │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ 5. 恢复执行                                                │
│    - IRET 指令恢复之前保存的 CS、IP 和 FLAGS              │
│    - 程序继续执行 int 指令后的下一条指令                   │
└─────────────────────────────────────────────────────────┘
```

### 1.3 引导扇区中的 INT 10h 使用示例

**示例 1：设置显示模式**
```nasm
mov ax, 0x0003      ; ah=0x00（设置模式功能），al=0x03（80x25文本模式）
int 0x10            ; 调用 BIOS 中断，设置显示模式
```

**示例 2：TTY 模式显示字符**
```nasm
mov ah, 0x0E        ; ah=0x0E（TTY模式显示字符功能）
mov al, 'H'         ; al=要显示的字符
int 0x10            ; 调用 BIOS 中断，显示字符
```

**示例 3：完整的字符串显示循环**
```nasm
mov si, msg         ; si 指向字符串
mov ah, 0x0E        ; 设置功能号
.print:
    lodsb           ; 从 [si] 加载一个字节到 al，si 自动加 1
    test al, al     ; 检查是否为字符串结束符（0）
    jz .halt        ; 如果是 0，跳转到结束
    int 0x10        ; 显示字符
    jmp .print      ; 继续循环
.halt:
    jmp $           ; 无限循环

msg db "Hello from Boot Sector!", 0
```

### 1.4 BIOS 固件实现位置

BIOS 中断处理程序位于主板 ROM 中：

- **在系统启动时由 BIOS 初始化中断向量表**
- **中断处理程序直接访问视频硬件**（如 VGA 寄存器）
- **提供统一的接口**，屏蔽底层硬件差异

**BIOS 固件的工作流程**：
```
系统启动 → BIOS 初始化 → 设置中断向量表 → 硬件就绪
    ↓
用户程序调用 int 0x10 → CPU 查找向量表 → 跳转到 BIOS 代码
    ↓
BIOS 读取寄存器参数 → 操作硬件 → 返回用户程序
```

## 二、开源 BIOS 项目学习资源

### 2.1 SeaBIOS（强烈推荐）

**项目信息**：
- **项目地址**：https://github.com/coreboot/seabios
- **说明**：开源的传统 BIOS 实现，QEMU 默认使用
- **语言**：C 语言
- **代码量**：约 10 万行代码

**关键源码文件**：

| 文件路径 | 功能说明 |
|---------|---------|
| `src/vgabios.c` | VGA BIOS 实现，包含视频硬件操作 |
| `src/bios.h` | BIOS 中断服务定义和数据结构 |
| `src/interrupts.c` | 中断处理程序，中断向量表初始化 |
| `src/vgahooks.c` | INT 10h 视频服务实现，中断入口函数 |
| `src/boot.c` | 引导加载相关代码 |
| `src/romfile.c` | ROM 文件系统处理 |

**快速开始**：
```bash
# 1. 克隆仓库
git clone https://github.com/coreboot/seabios.git
cd seabios

# 2. 查找 INT 10h 相关代码
grep -r "int.*0x10\|INT.*10h\|int10" src/ | head -20

# 3. 查看中断向量表初始化
grep -A 20 "int 0x10\|INT 10h" src/interrupts.c

# 4. 查看 VGA 相关实现
cat src/vgahooks.c | grep -A 30 "handle_int10"

# 5. 查看 VGA BIOS 实现
cat src/vgabios.c | head -100
```

**学习重点**：
1. `src/interrupts.c` - 理解中断向量表如何初始化
2. `src/vgahooks.c` - 理解 INT 10h 如何被调用和处理
3. `src/vgabios.c` - 理解如何直接操作 VGA 硬件

### 2.2 Coreboot

**项目信息**：
- **项目地址**：https://github.com/coreboot/coreboot
- **说明**：开源固件框架，SeaBIOS 可作为 payload
- **语言**：C 语言
- **学习重点**：BIOS 初始化流程、硬件抽象层

**关键目录**：
- `src/mainboard/` - 主板特定代码
- `payloads/` - 可选的 payload（如 SeaBIOS）
- `src/drivers/` - 硬件驱动

**学习路径**：
1. 先学习 SeaBIOS（更专注于 BIOS 服务）
2. 再学习 Coreboot（理解整个固件框架）

## 三、虚拟机实现源码学习

### 3.1 QEMU 源码

**项目信息**：
- **项目地址**：https://github.com/qemu/qemu
- **说明**：开源的硬件仿真器，模拟完整的计算机系统
- **语言**：C 语言
- **代码量**：超过 100 万行代码

**关键源码位置**：

| 目录/文件 | 功能说明 |
|---------|---------|
| `pc-bios/` | BIOS 镜像（SeaBIOS） |
| `hw/display/` | 显示设备模拟 |
| `hw/vga/` | VGA 硬件模拟 |
| `target/i386/` | x86 CPU 模拟（中断处理） |
| `hw/intc/` | 中断控制器模拟 |

**查看中断模拟代码**：
```bash
# 1. 克隆仓库
git clone https://github.com/qemu/qemu.git
cd qemu

# 2. 查找中断相关代码
grep -r "int.*0x10\|interrupt.*10" hw/ | head -20

# 3. 查看 VGA 硬件模拟
cat hw/vga/vga.c | grep -A 20 "int.*10"

# 4. 查看显示设备模拟
ls hw/display/
cat hw/display/vga.c | head -100
```

**使用 QEMU Monitor 调试**：
```bash
# 启动 QEMU 并进入 monitor 模式
qemu-system-x86_64 -monitor stdio -drive format=raw,file=boot.bin

# 在 monitor 中输入以下命令：
# (qemu) info registers          # 查看寄存器状态
# (qemu) x/4wx 0x40              # 查看 INT 10h 向量（地址 0x0040）
# (qemu) info mem                # 查看内存映射
# (qemu) info roms               # 查看 ROM 信息
# (qemu) help                    # 查看所有可用命令
```

**学习重点**：
1. `hw/vga/vga.c` - 理解 VGA 硬件如何被模拟
2. `target/i386/` - 理解 CPU 如何模拟中断处理
3. `hw/intc/` - 理解中断控制器的工作原理

### 3.2 DOSBox 源码（推荐初学者）

**项目信息**：
- **项目地址**：https://github.com/dosbox-staging/dosbox-staging
- **说明**：用于运行 DOS 程序的开源仿真器
- **语言**：C++ 语言
- **特点**：代码结构清晰，注释详细，易于理解

**关键源码文件**：

| 文件路径 | 功能说明 |
|---------|---------|
| `src/hardware/int10.cpp` | **INT 10h 实现（推荐从这里开始学习）** |
| `src/hardware/vga.cpp` | VGA 模拟 |
| `src/dos/dos.cpp` | DOS 中断处理 |
| `src/hardware/vga_s3.cpp` | S3 VGA 扩展 |

**查看 INT 10h 实现**：
```bash
# 1. 克隆仓库
git clone https://github.com/dosbox-staging/dosbox-staging.git
cd dosbox-staging

# 2. 查看 INT 10h 实现（代码结构清晰，有详细注释）
cat src/hardware/int10.cpp

# 3. 查看 VGA 模拟
cat src/hardware/vga.cpp | head -200

# 4. 查找特定功能实现
grep -n "SetMode\|WriteChar\|TTY" src/hardware/int10.cpp
```

**学习重点**：
1. `src/hardware/int10.cpp` - **最推荐的学习起点**
   - 代码结构清晰
   - 注释详细
   - 功能实现完整
   - 易于理解 BIOS 中断的模拟实现

2. `src/hardware/vga.cpp` - 理解 VGA 硬件模拟

3. `src/dos/dos.cpp` - 理解 DOS 中断处理机制

## 四、硬件文档资源

### 4.1 VGA 硬件规范

**VGA 寄存器文档**：
- 《VGA Hardware Programming Guide》
- 《IBM VGA Technical Reference Manual》
- 《VGA and VESA Programming Guide》

**在线资源**：
- **OSDev Wiki - VGA Hardware**：https://wiki.osdev.org/VGA_Hardware
  - 详细的 VGA 寄存器说明
  - 编程示例
  - 内存映射说明

- **Scanline VGA Programming**：https://www.scanline.ca/vga/
  - VGA 编程教程
  - 寄存器详解
  - 代码示例

**VGA 关键地址**：

| 地址范围 | 功能说明 |
|---------|---------|
| **I/O 端口 0x3C0-0x3DF** | VGA 控制寄存器 |
| **内存映射 0xA0000-0xAFFFF** | VGA 图形模式显存 |
| **内存映射 0xB0000-0xB7FFF** | 单色文本模式显存 |
| **内存映射 0xB8000-0xBFFFF** | 彩色文本模式显存 |

**VGA 寄存器分类**：
- **通用寄存器**（0x3C0-0x3CF）：属性控制器、序列器
- **CRTC 寄存器**（0x3D0-0x3DF）：CRT 控制器
- **图形控制器**（0x3CE-0x3CF）：图形模式控制

### 4.2 Intel CPU 架构手册

**文档名称**：
《Intel® 64 and IA-32 Architectures Software Developer's Manual》

**关键章节**：
- **Volume 3, Chapter 6**: "Interrupt and Exception Handling"
  - 中断和异常处理机制
  - 中断描述符表（IDT）
  - 中断优先级

- **Volume 3, Chapter 9**: "8086 Emulation"
  - 实模式中断处理
  - 中断向量表（IVT）
  - 8086 兼容性

- **Volume 1, Chapter 6**: "Procedure Calls, Interrupts, and Exceptions"
  - 过程调用机制
  - 中断调用流程

**下载地址**：
- 官方下载：https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html
- PDF 格式，共 4 卷，超过 5000 页

**学习建议**：
1. 先阅读 Volume 3, Chapter 6（中断处理）
2. 再阅读 Volume 3, Chapter 9（实模式）
3. 最后深入 Volume 1（基础概念）

### 4.3 其他硬件文档

**PC/AT 技术参考手册**：
- 《IBM PC/AT Technical Reference Manual》
- 包含 BIOS 中断服务详细说明

**VESA 标准文档**：
- VESA BIOS Extensions (VBE) 规范
- 用于理解现代显卡的 BIOS 扩展

## 五、学习路径与实践

### 5.1 阶段 1：理解中断机制（1-2 周）

**目标**：理解 BIOS 中断的基本工作原理

**学习内容**：
1. 阅读 SeaBIOS 的 `src/interrupts.c`
   - 理解中断向量表如何初始化
   - 理解中断处理程序如何注册

2. 理解中断向量表的结构
   - 查看内存地址 0x0000-0x03FF
   - 理解 4 字节向量的格式

3. 查看 `src/vgahooks.c` 中的 INT 10h 处理
   - 理解中断如何被调用
   - 理解参数如何传递

**实践任务**：
```nasm
; 编写程序查看中断向量表
org 0x7C00
bits 16

start:
    mov ax, 0
    mov es, ax
    mov si, 0x40        ; INT 10h 向量地址
    
    ; 读取并显示向量内容
    mov ax, [es:si]     ; 读取偏移地址
    mov bx, [es:si+2]   ; 读取段地址
    
    ; 这里可以添加代码显示这些值
    jmp $
```

### 5.2 阶段 2：查看具体实现（2-3 周）

**目标**：理解 BIOS 中断的具体实现代码

**推荐学习顺序**：

**第一步：DOSBox 的 `int10.cpp`（最推荐）**
- 代码结构清晰，注释详细
- 理解 BIOS 中断的模拟实现
- 查看各种 INT 10h 功能的实现

**第二步：SeaBIOS 的 `vgahooks.c`**
- 更接近真实 BIOS 的实现
- 理解中断向量表的实际使用
- 查看如何调用 VGA BIOS

**第三步：QEMU 的 VGA 硬件模拟**
- 理解硬件层面的实现
- 学习如何模拟 VGA 硬件
- 查看 `hw/vga/vga.c` 和 `hw/display/vga.c`

**实践任务**：
1. 阅读 DOSBox 的 `int10.cpp`，理解每个功能的实现
2. 对比 DOSBox 和 SeaBIOS 的实现差异
3. 尝试理解 QEMU 如何模拟 VGA 硬件

### 5.3 阶段 3：硬件层面（3-4 周）

**目标**：理解 VGA 硬件的底层操作

**学习内容**：

1. **学习 VGA 寄存器**：
   - 研究 VGA I/O 端口（0x3C0-0x3DF）
   - 理解 VGA 内存映射（0xA0000-0xBFFFF）
   - 阅读 VGA 硬件规范文档

2. **阅读硬件模拟代码**：
   - QEMU 的 `hw/vga/vga.c` - VGA 硬件模拟
   - QEMU 的 `hw/display/vga.c` - 显示逻辑

3. **实践：直接操作 VGA 寄存器**：
```nasm
; 直接操作 VGA 寄存器显示字符（绕过 BIOS）
org 0x7C00
bits 16

start:
    ; 设置文本模式（直接写寄存器）
    mov ax, 0x0003
    int 0x10
    
    ; 直接写显存显示字符
    mov ax, 0xB800      ; 文本模式显存段
    mov es, ax
    mov di, 0           ; 屏幕左上角
    
    mov ax, 0x0741      ; 属性 0x07（灰底白字）+ 字符 'A'
    stosw               ; 写入显存
    
    jmp $
```

### 5.4 阶段 4：实践项目（持续）

**项目 1：在 QEMU 中调试中断**

```bash
# 使用 QEMU monitor 查看中断向量表
qemu-system-x86_64 -monitor stdio -drive format=raw,file=boot.bin

# 在 monitor 中执行：
# (qemu) x/4wx 0x40              # 查看 INT 10h 向量
# (qemu) info registers          # 查看寄存器
# (qemu) x/16bx 0xB8000         # 查看文本模式显存
```

**项目 2：编写自己的 INT 10h 处理程序**

```nasm
; 挂钩中断向量，实现自己的 INT 10h 处理程序
org 0x7C00
bits 16

start:
    cli                     ; 关中断
    
    ; 保存原始 INT 10h 向量
    mov ax, 0
    mov es, ax
    mov ax, [es:0x10*4]     ; 保存原始偏移
    mov [old_int10_offset], ax
    mov ax, [es:0x10*4+2]   ; 保存原始段地址
    mov [old_int10_segment], ax
    
    ; 设置新的 INT 10h 向量
    mov word [es:0x10*4], my_int10_handler
    mov [es:0x10*4+2], cs
    
    sti                     ; 开中断
    
    ; 测试新的中断处理程序
    mov ah, 0x0E
    mov al, 'X'
    int 0x10                ; 调用我们的处理程序
    
    jmp $

my_int10_handler:
    ; 检查功能号
    cmp ah, 0x0E
    je .tty_output
    
    ; 其他功能调用原始处理程序
    pushf
    call far [old_int10_offset]
    iret
    
.tty_output:
    ; 实现自己的字符显示逻辑
    ; 这里可以添加自定义的显示代码
    push ax
    push bx
    push es
    
    ; 简单的显存写入实现
    mov ax, 0xB800
    mov es, ax
    mov bx, [cursor_pos]
    mov [es:bx], al         ; 写入字符
    inc bx
    mov byte [es:bx], 0x07  ; 写入属性
    inc bx
    mov [cursor_pos], bx
    
    pop es
    pop bx
    pop ax
    iret

old_int10_offset   dw 0
old_int10_segment  dw 0
cursor_pos         dw 0

times 510-($-$$) db 0
dw 0xAA55
```

**项目 3：实现简单的 VGA 图形模式**

```nasm
; 切换到图形模式并绘制像素
org 0x7C00
bits 16

start:
    ; 设置 320x200 256 色模式（模式 13h）
    mov ax, 0x0013
    int 0x10
    
    ; 绘制像素
    mov ax, 0xA000      ; 图形模式显存段
    mov es, ax
    mov di, 0           ; 屏幕左上角
    
    mov al, 15          ; 白色
    mov cx, 100         ; 绘制 100 个像素
    rep stosb           ; 重复写入
    
    jmp $

times 510-($-$$) db 0
dw 0xAA55
```

## 六、实用命令速查

### 6.1 SeaBIOS 源码查看

```bash
# 克隆仓库
git clone https://github.com/coreboot/seabios.git
cd seabios

# 查找 INT 10h 相关代码
grep -r "int.*0x10\|INT.*10h\|int10" src/

# 查看中断向量表初始化
grep -A 20 "int 0x10\|INT 10h" src/interrupts.c

# 查看 VGA 相关实现
cat src/vgahooks.c | grep -A 30 "handle_int10"

# 查找所有中断处理函数
grep -n "handle_int" src/vgahooks.c
```

### 6.2 DOSBox 源码查看

```bash
# 克隆仓库
git clone https://github.com/dosbox-staging/dosbox-staging.git
cd dosbox-staging

# 查看 INT 10h 实现
cat src/hardware/int10.cpp

# 查找特定功能
grep -n "SetMode\|WriteChar\|TTY" src/hardware/int10.cpp

# 查看 VGA 模拟
cat src/hardware/vga.cpp | head -200
```

### 6.3 QEMU 源码查看

```bash
# 克隆仓库
git clone https://github.com/qemu/qemu.git
cd qemu

# 查找 VGA 相关代码
grep -r "vga\|VGA" hw/display/ hw/vga/ | head -20

# 查看 VGA 硬件模拟
cat hw/vga/vga.c | head -100

# 查找中断相关代码
grep -r "interrupt" target/i386/ | head -20
```

### 6.4 QEMU Monitor 调试命令

```bash
# 启动 QEMU 并进入 monitor 模式
qemu-system-x86_64 -monitor stdio -drive format=raw,file=boot.bin

# 常用 monitor 命令：
# info registers          # 查看寄存器状态
# x/4wx 0x40              # 查看 INT 10h 向量（地址 0x0040）
# x/16bx 0xB8000         # 查看文本模式显存
# info mem                # 查看内存映射
# info roms               # 查看 ROM 信息
# help                    # 查看所有可用命令
# quit                    # 退出 QEMU
```

### 6.5 编译和运行引导扇区

```bash
# 编译
nasm -f bin boot.asm -o boot.bin

# 在 QEMU 中运行（图形模式）
qemu-system-x86_64 -drive format=raw,file=boot.bin

# 在 QEMU 中运行（终端模式）
qemu-system-x86_64 -display curses -drive format=raw,file=boot.bin

# 在 QEMU 中运行（带 monitor）
qemu-system-x86_64 -monitor stdio -drive format=raw,file=boot.bin
```

## 七、推荐阅读顺序总结

### 7.1 初学者路径

1. **第一步**：DOSBox 的 `int10.cpp`
   - 代码结构清晰，注释详细
   - 理解 BIOS 中断的模拟实现
   - **预计时间**：1 周

2. **第二步**：SeaBIOS 的 `vgahooks.c`
   - 更接近真实 BIOS 的实现
   - 理解中断向量表的实际使用
   - **预计时间**：1-2 周

3. **第三步**：QEMU 的 VGA 硬件模拟
   - 理解硬件层面的实现
   - 学习如何模拟 VGA 硬件
   - **预计时间**：2 周

4. **第四步**：硬件文档
   - VGA 规范文档
   - Intel CPU 架构手册
   - **预计时间**：持续参考

### 7.2 学习要点

- **从简单到复杂**：先看 DOSBox，再看 SeaBIOS，最后看 QEMU
- **理论与实践结合**：阅读源码的同时编写测试程序
- **使用调试工具**：QEMU monitor 是理解内存和寄存器的好工具
- **阅读官方文档**：硬件文档是最准确的参考资料

### 7.3 常见问题

**Q: 为什么 BIOS 代码在 ROM 中，但我们能调用它？**
A: BIOS 在系统启动时会将中断向量表初始化，指向 ROM 中的处理程序。当调用 `int 0x10` 时，CPU 会跳转到 ROM 中的代码执行。

**Q: 如何知道 BIOS 支持哪些功能？**
A: 查看 BIOS 中断服务文档，或阅读 SeaBIOS/DOSBox 的源码，了解每个功能号的实现。

**Q: 能否修改 BIOS 中断向量？**
A: 可以。在实模式下，可以直接修改中断向量表（地址 0x0000-0x03FF），但需要小心处理，避免破坏系统功能。

---

通过这份指南，你可以从最简单的 DOSBox 源码开始，逐步深入理解 BIOS 中断的实现原理，最终掌握硬件层面的知识。关键是要**动手实践**，每个概念都通过代码来验证。

