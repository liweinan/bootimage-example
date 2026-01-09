# call_boot_entry 函数详解

本文档详细解释 SeaBIOS 中 `call_boot_entry` 函数的作用和实现细节。

## 函数代码

```c
// Jump to a bootup entry point.
static void
call_boot_entry(struct segoff_s bootsegip, u8 bootdrv)
{
    dprintf(1, "Booting from %04x:%04x\n", bootsegip.seg, bootsegip.offset);
    struct bregs br;
    memset(&br, 0, sizeof(br));
    br.flags = F_IF;
    br.code = bootsegip;
    // Set the magic number in ax and the boot drive in dl.
    br.dl = bootdrv;
    br.ax = 0xaa55;
    farcall16(&br);
}
```

---

## 函数作用

**`call_boot_entry` 是 SeaBIOS 跳转到引导扇区代码执行的关键函数。**

它负责：
1. 设置跳转目标地址（CS:IP）
2. 设置引导驱动器号（DL）
3. 设置魔数（AX = 0xAA55）
4. 执行远跳转，将控制权交给引导扇区代码

---

## 逐行解析

### 1. 函数签名

```c
static void
call_boot_entry(struct segoff_s bootsegip, u8 bootdrv)
```

**参数说明：**
- **`bootsegip`**：`struct segoff_s` 类型，包含段地址和偏移地址
  - `bootsegip.seg`：段地址（例如 `0x0000`）
  - `bootsegip.offset`：偏移地址（例如 `0x7C00`）
  - 组合起来就是 `CS:IP = 0x0000:0x7C00`
  
- **`bootdrv`**：`u8` 类型，引导驱动器号
  - `0x00`：软盘
  - `0x80`：第一块硬盘
  - `0x81`：第二块硬盘
  - 等等

**调用示例：**
```c
// 从 boot_disk() 调用
call_boot_entry(SEGOFF(0x0000, 0x7C00), 0x80);
// 跳转到 CS:IP = 0x0000:0x7C00，驱动器号 = 0x80（硬盘）
```

### 2. 调试输出

```c
dprintf(1, "Booting from %04x:%04x\n", bootsegip.seg, bootsegip.offset);
```

**作用：** 输出调试信息，显示引导扇区的段:偏移地址

**输出示例：**
```
Booting from 0000:7c00
```

### 3. 初始化寄存器结构体

```c
struct bregs br;
memset(&br, 0, sizeof(br));
```

**`struct bregs`**：BIOS 寄存器结构体，包含所有 x86 寄存器

**初始化：** 将所有寄存器初始化为 0，确保干净的状态

### 4. 设置中断标志

```c
br.flags = F_IF;
```

**`F_IF`**：Interrupt Flag（中断标志）

**作用：** 允许 CPU 响应中断（IF = 1）

**为什么重要：** 引导扇区代码可能需要使用 BIOS 中断服务（如 INT 10h、INT 13h），所以必须允许中断

### 5. 设置跳转目标地址

```c
br.code = bootsegip;
```

**`br.code`**：代码段和指令指针（CS:IP）

**作用：** 设置跳转目标地址

**示例：**
```c
bootsegip.seg = 0x0000;
bootsegip.offset = 0x7C00;
// 设置后，CS:IP = 0x0000:0x7C00
```

### 6. 设置引导驱动器号

```c
br.dl = bootdrv;
```

**`DL` 寄存器：** 驱动器号

**作用：** 告诉引导扇区代码是从哪个驱动器引导的

**标准值：**
- `0x00`：软盘 A
- `0x01`：软盘 B
- `0x80`：第一块硬盘
- `0x81`：第二块硬盘
- `0x82`：第三块硬盘
- 等等

**为什么重要：** 引导扇区代码可能需要知道从哪个驱动器引导，以便加载后续的引导加载程序或操作系统

### 7. 设置魔数

```c
br.ax = 0xaa55;
```

**`AX` 寄存器：** 累加寄存器

**`0xAA55`：** 引导扇区签名魔数

**作用：** 这是 BIOS 传递给引导扇区的**验证标记**，用于确认是从 BIOS 引导的

**核心目的：**
- **验证来源：** 引导扇区代码可以检查 `AX == 0xAA55` 来确认是从 BIOS 引导的
- **防止误调用：** 如果引导扇区代码被其他方式调用（不是从 BIOS），AX 不会是 0xAA55
- **约定标志：** 这是一个 BIOS 和引导扇区之间的约定

**历史背景：**
- `0xAA55` 是引导扇区的标准签名（存储在引导扇区的最后两个字节）
- BIOS 在调用引导扇区时，也在 AX 寄存器中设置这个值作为"调用标记"
- 引导扇区代码可以双重验证：既检查文件签名，也检查寄存器值

**实际使用示例：**

```asm
; 引导扇区代码可以这样验证
start:
    ; 验证是从 BIOS 引导的
    cmp ax, 0xAA55
    jne not_bios_boot    ; 如果不是 0xAA55，说明不是从 BIOS 引导
    
    ; 确认是从 BIOS 引导，继续执行
    mov si, msg
    ; ... 其他代码 ...
    
not_bios_boot:
    ; 处理非 BIOS 引导的情况
    ; 或者直接退出
    jmp $
```

**注意：** 
- 这个值存储在引导扇区的最后两个字节（偏移 0x1FE-0x1FF），小端序存储为 `0x55 0xAA`
- 但 AX 寄存器中的值是 `0xAA55`（大端序格式，因为寄存器是 16 位的）
- 不是所有引导扇区代码都会检查这个值，但这是一个可选的安全验证机制

### 8. 执行远跳转

```c
farcall16(&br);
```

**`farcall16`**：16 位远调用函数

**作用：** 执行远跳转，将控制权交给引导扇区代码

**内部实现（简化）：**
```c
// farcall16 的简化实现
void farcall16(struct bregs *br) {
    // 1. 保存当前状态
    // 2. 设置寄存器
    // 3. 设置 CS:IP = br->code
    // 4. 跳转到目标地址
    // 5. 引导扇区代码开始执行
}
```

**实际效果：**
- CPU 的 CS 寄存器被设置为 `bootsegip.seg`（例如 `0x0000`）
- CPU 的 IP 寄存器被设置为 `bootsegip.offset`（例如 `0x7C00`）
- CPU 跳转到 `CS:IP = 0x0000:0x7C00` 执行
- 此时，引导扇区代码的第一条指令开始执行

---

## 完整执行流程

### 调用链

```
boot_disk(0x80, 1)
    ↓
读取引导扇区到 0x7C00
    ↓
验证签名 0xAA55
    ↓
call_boot_entry(SEGOFF(0x0000, 0x7C00), 0x80)
    ↓
farcall16(&br)
    ↓
跳转到 CS:IP = 0x0000:0x7C00
    ↓
引导扇区代码开始执行
```

### 寄存器状态

当引导扇区代码开始执行时，寄存器状态如下：

| 寄存器 | 值 | 说明 |
|--------|-----|------|
| **CS** | `0x0000` | 代码段（由 bootsegip.seg 设置） |
| **IP** | `0x7C00` | 指令指针（由 bootsegip.offset 设置） |
| **DL** | `0x80` | 引导驱动器号（由 bootdrv 设置） |
| **AX** | `0xAA55` | 魔数（固定值） |
| **FLAGS** | `IF=1` | 中断标志已设置（允许中断） |
| **其他寄存器** | `0x0000` | 其他寄存器初始化为 0 |

### 内存状态

```
地址范围          内容
─────────────────────────────────────
0x7C00 - 0x7DFF  引导扇区代码（512 字节）
                 第一条指令：mov ax, 0x0003
                 最后两个字节：0x55 0xAA（签名）
```

---

## 为什么需要这些设置？

### 1. 为什么设置 CS:IP = 0x0000:0x7C00？

**原因：**
- 引导扇区代码使用 `org 0x7C00` 编译
- 代码中的地址计算基于 0x7C00
- 如果 CS:IP 不是 0x0000:0x7C00，地址计算会出错

**示例：**
```asm
; boot.asm
org 0x7C00

start:
    mov si, msg    ; msg 的地址被计算为 0x7C00 + offset
    ; 如果 CS 不是 0x0000，这个地址计算会出错
```

### 2. 为什么设置 DL = 驱动器号？

**原因：**
- 引导扇区代码可能需要知道从哪个驱动器引导
- 例如，GRUB 需要知道从哪个硬盘引导，以便加载后续的引导加载程序

**使用示例：**
```asm
; 引导扇区代码可以使用 DL 寄存器
mov [boot_drive], dl  ; 保存驱动器号
; 后续使用这个驱动器号读取更多扇区
```

### 3. 为什么设置 AX = 0xAA55？

**原因：**
- **验证来源：** 这是 BIOS 传递给引导扇区的验证标记
- **确认调用者：** 引导扇区代码可以检查 `AX == 0xAA55` 来确认是从 BIOS 引导的
- **防止误调用：** 如果引导扇区代码被其他方式调用，AX 不会是 0xAA55
- **约定标志：** 与引导扇区签名（0xAA55）保持一致，形成双重验证

**验证示例：**
```asm
; 引导扇区代码可以这样验证
start:
    ; 验证是从 BIOS 引导的
    cmp ax, 0xAA55
    jne not_bios_boot    ; 如果不是 BIOS 调用，跳转到错误处理
    
    ; 确认是从 BIOS 引导，继续执行
    mov si, msg
    ; ... 正常引导流程 ...
    
not_bios_boot:
    ; 处理非 BIOS 引导的情况
    mov si, error_msg
    call print_string
    jmp $
```

**实际意义：**
- 这是一个**可选的验证机制**，不是所有引导扇区代码都会检查
- 但对于需要安全性的引导扇区代码，这是一个有用的验证手段
- 可以防止引导扇区代码被意外或恶意调用

### 4. 为什么允许中断（IF = 1）？

**原因：**
- 引导扇区代码可能需要使用 BIOS 中断服务
- 例如：INT 10h（视频服务）、INT 13h（磁盘服务）、INT 16h（键盘服务）

**使用示例：**
```asm
; boot.asm 中使用 INT 10h
mov ax, 0x0003
int 0x10    ; 设置显示模式，需要中断可用
```

---

## farcall16 内部实现（简化）

```c
// farcall16 的简化实现
void farcall16(struct bregs *br) {
    // 1. 保存当前状态（如果需要）
    
    // 2. 设置所有寄存器
    // 从 br 结构体复制到实际 CPU 寄存器
    
    // 3. 设置段寄存器
    // CS = br->code.seg
    // IP = br->code.offset
    
    // 4. 设置标志寄存器
    // FLAGS = br->flags
    
    // 5. 执行远跳转
    // 跳转到 CS:IP
    // 这通常通过修改栈并执行 RETF（远返回）实现
    // 或者直接修改 CS:IP 寄存器
    
    // 6. 引导扇区代码开始执行
}
```

**关键点：**
- `farcall16` 是一个复杂的函数，需要切换到 16 位模式
- 它需要正确设置所有寄存器，包括段寄存器
- 最终通过远跳转将控制权交给引导扇区代码

---

## 实际执行示例

假设引导扇区代码是 `boot.asm`：

```asm
; boot.asm
org 0x7C00
bits 16

start:
    mov ax, 0x0003      ; 设置显示模式
    int 0x10            ; 调用 BIOS 视频服务
    
    mov si, msg
    mov ah, 0x0E
.print:
    lodsb
    test al, al
    jz .halt
    int 0x10
    jmp .print
.halt:
    jmp $

msg db "Hello from Boot Sector!", 0
times 510-($-$$) db 0
dw 0xAA55
```

**执行流程：**

1. **SeaBIOS 调用 `call_boot_entry`**
   ```c
   call_boot_entry(SEGOFF(0x0000, 0x7C00), 0x80);
   ```

2. **设置寄存器**
   - CS = 0x0000
   - IP = 0x7C00
   - DL = 0x80
   - AX = 0xAA55
   - FLAGS.IF = 1

3. **执行 `farcall16`**
   - 跳转到 CS:IP = 0x0000:0x7C00

4. **引导扇区代码开始执行**
   - 第一条指令：`mov ax, 0x0003`（地址 0x7C00）
   - 执行后续指令
   - 显示 "Hello from Boot Sector!"
   - 进入无限循环

---

## 关键要点总结

1. **`call_boot_entry` 是跳转函数**：将控制权从 SeaBIOS 交给引导扇区代码

2. **设置关键寄存器**：
   - CS:IP = 跳转目标地址（0x0000:0x7C00）
   - DL = 引导驱动器号
   - AX = 魔数 0xAA55

3. **允许中断**：确保引导扇区代码可以使用 BIOS 中断服务

4. **远跳转**：通过 `farcall16` 执行远跳转，切换到引导扇区代码

5. **引导扇区代码开始执行**：从地址 0x7C00 开始执行第一条指令

---

## 相关文档

- [SEABIOS_LOAD_BOOT_SECTOR.md](SEABIOS_LOAD_BOOT_SECTOR.md) - SeaBIOS 加载引导扇区的完整流程
- [BOOT_FLOW.md](BOOT_FLOW.md) - 完整的引导流程分析
- [boot.asm](boot.asm) - 引导扇区代码示例
