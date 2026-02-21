# DOS 如何使用 BIOS 的 INT 服务

## 简短回答

**DOS 既直接使用 BIOS 的 INT 服务，也会替换某些 BIOS 中断。具体情况取决于中断类型和 DOS 的实现策略。**

---

## DOS 与 BIOS 中断的关系

### 三种使用模式

1. **直接使用**：DOS 直接调用 BIOS 中断（如 INT 10h、INT 16h）
2. **替换实现**：DOS 用自己的实现替换 BIOS 中断（如 INT 13h）
3. **新增服务**：DOS 提供新的中断服务（如 INT 21h）

---

## 详细分析

### 1. DOS 直接使用的 BIOS 中断

**这些中断 DOS 通常直接使用，不替换：**

| 中断号 | 功能 | DOS 使用方式 | 说明 |
|--------|------|------------|------|
| **INT 10h** | 视频服务 | 直接使用 | DOS 直接调用 BIOS 的 INT 10h 进行显示操作 |
| **INT 16h** | 键盘服务 | 直接使用 | DOS 直接调用 BIOS 的 INT 16h 读取键盘输入 |
| **INT 15h** | 系统服务 | 直接使用 | DOS 使用 INT 15h 获取系统信息（如内存大小） |
| **INT 1Ah** | 实时时钟 | 直接使用 | DOS 使用 INT 1Ah 读取系统时间 |

**示例：DOS 使用 INT 10h**

```asm
; DOS 内部代码（简化示例）
; DOS 需要显示字符时，直接调用 BIOS 的 INT 10h
display_char:
    mov ah, 0x0E        ; BIOS INT 10h 功能：TTY 模式显示字符
    mov al, [char]       ; 要显示的字符
    int 0x10            ; 直接调用 BIOS 的 INT 10h
    ret
```

**为什么直接使用？**
- BIOS 的实现已经足够好
- DOS 不需要额外的功能
- 保持兼容性

### 2. DOS 替换的 BIOS 中断

**这些中断 DOS 可能会替换，用自己的实现：**

| 中断号 | 功能 | DOS 处理方式 | 说明 |
|--------|------|------------|------|
| **INT 13h** | 磁盘服务 | **可能替换** | DOS 可能用自己的磁盘驱动替换 BIOS 的 INT 13h |

**DOS 替换 INT 13h 的原因：**
1. **性能优化**：DOS 的磁盘驱动可能比 BIOS 的实现更高效
2. **功能增强**：支持更多文件系统特性（如 FAT32、长文件名）
3. **兼容性**：处理不同硬件厂商的磁盘控制器差异
4. **缓存机制**：DOS 可能实现磁盘缓存，提高性能

**DOS 替换 INT 13h 的过程：**

```asm
; IO.SYS 初始化代码（简化示例）
setup_dos_interrupts:
    ; 步骤 1: 保存原 BIOS INT 13h 向量
    mov ax, 0x3513            ; INT 21h AH=0x35：获取中断向量
    int 0x21                  ; 获取 INT 13h 的向量
    mov [bios_int13_offset], bx    ; 保存偏移地址
    mov [bios_int13_segment], es   ; 保存段地址
    
    ; 步骤 2: 设置 DOS 自己的 INT 13h 处理程序
    mov ax, 0x2513            ; INT 21h AH=0x25：设置中断向量
    mov dx, dos_int13_handler ; DOS 的 INT 13h 处理程序
    int 0x21                  ; 设置新的 INT 13h 向量
    
    ; 步骤 3: DOS 的 INT 13h 处理程序内部
    ; 如果需要，可以调用保存的 BIOS INT 13h
    ret

; DOS 的 INT 13h 处理程序（简化示例）
dos_int13_handler:
    ; DOS 自己的磁盘处理逻辑
    ; 如果需要访问底层硬件，可以调用保存的 BIOS INT 13h
    pushf
    call far [bios_int13]     ; 调用原 BIOS INT 13h（如果需要）
    ; 或者直接处理，不调用 BIOS
    iret
```

**关键点：**
- DOS 保存原 BIOS INT 13h 向量
- DOS 设置自己的 INT 13h 处理程序
- DOS 的处理程序可以选择调用原 BIOS INT 13h，或完全自己实现

### 3. DOS 新增的中断服务

**DOS 提供的新中断服务：**

| 中断号 | 功能 | 说明 |
|--------|------|------|
| **INT 21h** | DOS 功能调用 | DOS 的核心 API，提供文件操作、内存管理等 |
| **INT 20h** | 程序终止 | DOS 程序终止服务 |
| **INT 25h** | 绝对磁盘读 | DOS 磁盘读取服务 |
| **INT 26h** | 绝对磁盘写 | DOS 磁盘写入服务 |
| **INT 27h** | 终止并驻留 | DOS TSR 程序服务 |

**INT 21h 是 DOS 的核心 API：**

```asm
; DOS 程序使用 INT 21h
mov ah, 0x09        ; 功能：显示字符串
mov dx, msg         ; 字符串地址
int 0x21            ; 调用 DOS 功能

mov ah, 0x4C        ; 功能：程序终止
mov al, 0x00        ; 返回码
int 0x21            ; 退出程序
```

**INT 21h 内部实现：**
- INT 21h 是 DOS 自己实现的
- 内部可能会调用 BIOS 中断（如 INT 10h、INT 13h）
- 提供更高层的抽象（文件操作、目录操作等）

---

## DOS 中断调用链

### 用户程序 → DOS → BIOS

```
用户程序
    ↓ INT 21h AH=0x09（显示字符串）
DOS INT 21h 处理程序
    ↓ 内部调用 INT 10h AH=0x0E（显示字符）
BIOS INT 10h 处理程序
    ↓ 直接操作硬件
显示硬件
```

**示例：DOS 显示字符串的实现**

```asm
; DOS INT 21h AH=0x09 处理程序（简化示例）
dos_int21_09:
    ; 显示字符串功能
    mov si, dx       ; 字符串地址
display_loop:
    lodsb            ; 读取一个字符
    test al, al      ; 检查是否结束
    jz done
    
    ; 调用 BIOS INT 10h 显示字符
    mov ah, 0x0E     ; BIOS INT 10h 功能：TTY 模式显示字符
    int 0x10         ; 直接调用 BIOS 的 INT 10h
    jmp display_loop
    
done:
    iret
```

### 用户程序 → BIOS（直接调用）

```
用户程序
    ↓ INT 10h（直接调用）
BIOS INT 10h 处理程序
    ↓ 直接操作硬件
显示硬件
```

**用户程序也可以直接调用 BIOS 中断：**

```asm
; 用户程序直接调用 BIOS INT 10h
mov ax, 0x0003      ; 设置显示模式
int 0x10            ; 直接调用 BIOS，不经过 DOS
```

---

## DOS 启动时的中断设置

### IO.SYS 初始化过程

```asm
; IO.SYS 初始化代码（详细示例）
org 0x0600

start:
    ; 步骤 1: 初始化硬件
    call init_disk
    call init_keyboard
    call init_display
    
    ; 步骤 2: 设置 DOS 中断向量
    call setup_dos_interrupts
    
    ; 步骤 3: 加载 MSDOS.SYS
    call load_msdos_sys
    
    ; 步骤 4: 跳转到 MSDOS.SYS
    jmp 0x0000:0x0800

setup_dos_interrupts:
    ; 保存原 BIOS 中断向量
    mov ax, 0x3513            ; 获取 INT 13h 向量
    int 0x21                  ; 注意：此时 INT 21h 可能还未设置
    ; 或者直接读取 IVT
    mov ax, 0
    mov es, ax
    mov bx, [es:0x13*4]       ; 读取 INT 13h 偏移
    mov [bios_int13_offset], bx
    mov bx, [es:0x13*4+2]     ; 读取 INT 13h 段地址
    mov [bios_int13_segment], bx
    
    ; 设置 DOS 自己的 INT 13h（如果需要）
    mov ax, 0x2513
    mov dx, dos_int13_handler
    int 0x21                  ; 或者直接写入 IVT
    
    ; 设置 DOS INT 21h
    mov ax, 0x2521
    mov dx, dos_int21_handler
    int 0x21                  ; 或者直接写入 IVT
    
    ret
```

---

## 实际使用场景

### 场景 1：DOS 显示字符串

```
用户程序：INT 21h AH=0x09
    ↓
DOS INT 21h：解析参数，调用 INT 10h
    ↓
BIOS INT 10h：直接操作显示硬件
```

### 场景 2：DOS 读取文件

```
用户程序：INT 21h AH=0x3F（读文件）
    ↓
DOS INT 21h：文件系统操作，可能需要读取磁盘
    ↓
DOS INT 13h（如果替换了）：DOS 的磁盘驱动
    ↓
BIOS INT 13h（如果需要）：底层磁盘操作
    ↓
磁盘硬件
```

### 场景 3：用户程序直接调用 BIOS

```
用户程序：INT 10h AH=0x00（设置显示模式）
    ↓
BIOS INT 10h：直接操作显示硬件
```

---

## DOS 中断使用策略总结

### DOS 直接使用的 BIOS 中断

| 中断 | 原因 |
|------|------|
| **INT 10h** | 视频服务，BIOS 实现已经足够 |
| **INT 16h** | 键盘服务，BIOS 实现已经足够 |
| **INT 15h** | 系统服务，获取硬件信息 |
| **INT 1Ah** | 实时时钟，BIOS 实现已经足够 |

### DOS 可能替换的 BIOS 中断

| 中断 | 原因 |
|------|------|
| **INT 13h** | 性能优化、功能增强、兼容性处理 |

### DOS 新增的中断服务

| 中断 | 功能 |
|------|------|
| **INT 21h** | DOS 核心 API（文件操作、内存管理等） |
| **INT 20h** | 程序终止 |
| **INT 25h/26h** | 绝对磁盘读写 |
| **INT 27h** | 终止并驻留（TSR） |

---

## INT 21h 与 Linux 系统调用对比

DOS 的 **INT 21h** 与 Linux 的 **INT 80h / syscall** 在概念和设计思路上**高度一致**，都是用户程序进入操作系统内核的**大门**。

### 核心作用：系统调用的入口

| 系统 | 入口 | 作用 |
|------|------|------|
| **DOS** | INT 21h | 程序将功能号放入 AH，设置参数后执行 `INT 21h`，触发软中断，进入 DOS 内核（实模式下逻辑上进入内核）执行相应功能（读文件、显示字符等）。 |
| **Linux** | INT 80h / syscall | 程序将系统调用号放入 eax，设置参数后执行 `INT 80h` 或 `syscall`，切换到内核态（Ring 0），执行内核中的系统调用处理函数。 |

### 工作流程对比

| 步骤 | DOS（INT 21h） | Linux（INT 80h） |
|------|----------------|------------------|
| **1. 准备** | 功能号（如 09h 打印字符串）放入 AH，字符串地址放入 DX。 | 系统调用号（如 4 表示 write）放入 eax，fd、缓冲区等放入 ebx、ecx 等。 |
| **2. 触发** | 执行 `INT 21h`。 | 执行 `INT 80h` 或 `syscall`。 |
| **3. 查表** | CPU 查**中断向量表（IVT）**，取 21h 对应处理程序地址并跳转。 | CPU 查**中断描述符表（IDT）**或 MSR（syscall），取对应入口并跳转。 |
| **4. 分发** | DOS 根据 AH 中的功能号在函数表中查找，跳转到具体实现（如打印、读文件）。 | 内核根据 eax 中的系统调用号在 `sys_call_table` 中查找，跳转到具体实现（如 `sys_write`）。 |
| **5. 返回** | 执行完后 `iret` 返回用户程序。 | 执行完后 `iret` 或 `sysret` 返回用户程序。 |

### 主要区别

| 方面 | DOS（INT 21h） | Linux（INT 80h / syscall） |
|------|----------------|----------------------------|
| **调用方式与性能** | 唯一入口，单任务下中断开销可接受。 | 早期用 INT 80h；x86-64 上多用 **syscall**，专为系统调用设计，比 `int` 更快。 |
| **参数传递** | 主要用**寄存器**（功能简单、参数少）。 | 参数多时用**寄存器 + 用户栈**，内核需从用户栈拷贝并做合法性检查。 |
| **安全与保护** | **几乎无检查**：若通过 INT 21h 要求“把磁盘读到 0x1234”，DOS 会照做，不检查该地址是否属于调用者、是否覆盖系统。 | **严格检查**：内核检查指针是否在用户空间、文件权限等，防止破坏系统或其他进程。 |

**总结**：INT 21h 之于 DOS，如同 INT 80h / syscall 之于 Linux；都是用户态（或非特权态）进入内核态（或特权态）的桥梁，通过**中断/异常号 + 功能号**调用内核提供的服务。DOS 的 INT 21h 是早期 PC 上系统调用思想的典型体现，Linux 的 INT 80h / syscall 继承并大大强化了这一思想（保护、多任务、多参数、高性能入口）。

---

## 关键要点

1. **DOS 既直接使用 BIOS 中断，也会替换某些中断**
   - 直接使用：INT 10h、INT 16h 等
   - 可能替换：INT 13h（取决于 DOS 版本和配置）

2. **DOS 提供自己的中断服务**
   - INT 21h 是 DOS 的核心 API
   - 内部可能会调用 BIOS 中断

3. **用户程序可以同时使用 DOS 和 BIOS 中断**
   - 通过 INT 21h 使用 DOS 服务（高层抽象）
   - 直接调用 INT 10h、INT 13h 等使用 BIOS 服务（底层控制）

4. **DOS 启动时会保存 BIOS 中断向量**
   - 即使替换了某些中断，也会保存原向量
   - 可以在需要时调用原 BIOS 中断

---

## 相关文档

- [GUIDE.md](GUIDE.md) - DOS 中断编程指南
- [DOS_BOOTLOADER.md](DOS_BOOTLOADER.md) - DOS 引导加载程序
- [BIOS_INTERRUPT_COMPLETE.md](BIOS_INTERRUPT_COMPLETE.md) - BIOS 中断处理完整指南
- [LINUX_KERNEL_SYSCALL_INIT.md](LINUX_KERNEL_SYSCALL_INIT.md) - Linux 系统调用初始化（INT 80h / syscall 实现）
