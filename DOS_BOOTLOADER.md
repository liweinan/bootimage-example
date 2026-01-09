# DOS 的引导加载程序（Bootloader）概念

## 简短回答

**是的，DOS 有 bootloader 的概念，但通常不叫 "bootloader"，而是叫 "引导程序"（Bootstrap Loader）或 "DOS 引导程序"。**

DOS 的引导流程是多阶段的，包括：
1. **引导扇区**（Boot Sector）：512 字节，由 BIOS 加载到 0x7C00
2. **DOS 引导程序**（IO.SYS / IBMBIO.COM）：由引导扇区加载
3. **DOS 内核**（MSDOS.SYS / IBMDOS.COM）：由引导程序加载
4. **命令解释器**（COMMAND.COM）：由 DOS 内核加载

---

## DOS 引导流程详解

### 完整引导链

```
BIOS 初始化
    ↓
BIOS 加载引导扇区到 0x7C00
    ↓
引导扇区代码执行（512 字节）
    ↓
引导扇区加载 IO.SYS（DOS 引导程序）
    ↓
IO.SYS 加载 MSDOS.SYS（DOS 内核）
    ↓
MSDOS.SYS 加载 COMMAND.COM（命令解释器）
    ↓
DOS 系统就绪
```

### 各阶段详解

#### 阶段 1：引导扇区（Boot Sector）

**位置：** 磁盘第一个扇区（扇区 0）  
**大小：** 512 字节  
**加载地址：** 0x7C00（由 BIOS 加载）  
**作用：** 加载 DOS 引导程序（IO.SYS）到 0x00600

**关键点：**
- **引导扇区本身**：在 0x7C00-0x7DFF（512 字节，临时位置）
- **IO.SYS 加载位置**：0x00600（与引导扇区不重叠）
- **地址关系**：0x00600 < 0x7C00，所以 IO.SYS 在引导扇区之前的内存位置

**引导扇区代码功能：**
- 查找活动分区（如果是硬盘）
- 读取根目录，查找 IO.SYS（MS-DOS）或 IBMBIO.COM（PC-DOS）
- 从磁盘读取 IO.SYS，加载到内存地址 0x00600（注意：不是 0x7C00）
- 跳转到 0x00600 执行 IO.SYS

**示例代码结构：**
```asm
; DOS 引导扇区代码（简化）
org 0x7C00

start:
    ; 初始化
    cli
    xor ax, ax
    mov ds, ax
    mov es, ax
    mov ss, ax
    mov sp, 0x7C00
    
    ; 查找 IO.SYS
    ; 读取根目录
    ; 从磁盘读取 IO.SYS，加载到 0x00600（注意：不是 0x7C00）
    ; 跳转到 IO.SYS（地址 0x00600）
    jmp 0x0000:0x0600

times 510-($-$$) db 0
dw 0xAA55
```

#### 阶段 2：DOS 引导程序（IO.SYS / IBMBIO.COM）

**文件名：**
- **MS-DOS**：`IO.SYS`
- **PC-DOS**：`IBMBIO.COM`

**加载位置：** 通常从 `0x00600` 开始  
**大小：** 约 15-20KB  
**作用：** DOS 的引导加载程序和 I/O 处理程序

**IO.SYS 的功能：**
1. **初始化硬件**：
   - 初始化磁盘驱动器
   - 初始化串口、并口
   - 初始化键盘、显示器

2. **加载 DOS 内核**：
   - 读取 `MSDOS.SYS`（MS-DOS）或 `IBMDOS.COM`（PC-DOS）
   - 加载到内存（通常从 `0x00700` 开始）
   - 跳转到 DOS 内核执行

3. **设置 DOS 中断**：
   - 设置 INT 21h（DOS 功能调用）
   - 设置 INT 13h（磁盘服务，可能替换 BIOS 的）
   - 设置其他 DOS 中断

**IO.SYS 的内存布局：**
```
0x00600 - 0x007FF：IO.SYS 代码和数据
0x00800+：DOS 内核（MSDOS.SYS）加载位置
```

#### 阶段 3：DOS 内核（MSDOS.SYS / IBMDOS.COM）

**文件名：**
- **MS-DOS**：`MSDOS.SYS`
- **PC-DOS**：`IBMDOS.COM`

**加载位置：** 通常从 `0x00800` 开始  
**大小：** 约 10-15KB  
**作用：** DOS 内核，提供文件系统、内存管理等核心功能

**MSDOS.SYS 的功能：**
1. **文件系统管理**：
   - FAT12/FAT16 文件系统支持
   - 目录管理
   - 文件读写

2. **内存管理**：
   - 内存分配和释放
   - 程序加载

3. **进程管理**：
   - 程序执行
   - 程序终止

4. **加载命令解释器**：
   - 读取 `COMMAND.COM`
   - 加载到内存
   - 跳转到 COMMAND.COM 执行

#### 阶段 4：命令解释器（COMMAND.COM）

**文件名：** `COMMAND.COM`（MS-DOS 和 PC-DOS 相同）  
**加载位置：** 通常从 `0x01000` 或更高地址开始  
**大小：** 约 50-60KB  
**作用：** DOS 命令解释器，提供命令行界面

**COMMAND.COM 的功能：**
- 解析和执行用户命令
- 提供内部命令（如 DIR、CD、COPY 等）
- 加载和执行外部程序（.EXE、.COM 文件）
- 显示命令提示符

---

## DOS vs 现代 Bootloader 对比

### 术语对比

| DOS 时代 | 现代 Linux |
|---------|-----------|
| **引导扇区**（Boot Sector） | **引导扇区**（Boot Sector / MBR） |
| **DOS 引导程序**（IO.SYS） | **Bootloader**（GRUB Stage 1.5） |
| **DOS 内核**（MSDOS.SYS） | **Linux 内核**（vmlinuz） |
| **命令解释器**（COMMAND.COM） | **Init 进程**（systemd/sysvinit） |

### 功能对比

| 特性 | DOS 引导程序（IO.SYS） | 现代 Bootloader（GRUB） |
|------|---------------------|----------------------|
| **加载位置** | 0x00600 | 0x8000（GRUB Core） |
| **大小** | 15-20KB | 几十到几百 KB |
| **功能** | 加载 DOS 内核 | 加载 Linux 内核 |
| **配置文件** | 无（硬编码） | grub.cfg |
| **多系统支持** | 不支持 | 支持（菜单选择） |
| **文件系统支持** | FAT12/FAT16 | 多种文件系统 |

---

## DOS 引导程序的历史演进

### 早期 DOS（DOS 1.0 - DOS 2.0，1981-1983）

- **引导扇区**：简单的引导程序，直接加载 IO.SYS
- **IO.SYS**：约 8-10KB，功能简单
- **MSDOS.SYS**：约 5-8KB，基础文件系统

### 中期 DOS（DOS 3.0 - DOS 5.0，1984-1991）

- **引导扇区**：支持硬盘分区（MBR）
- **IO.SYS**：约 15-20KB，支持更多硬件
- **MSDOS.SYS**：约 10-15KB，增强文件系统

### 后期 DOS（DOS 6.0 - DOS 6.22，1993-1994）

- **引导扇区**：支持压缩磁盘（DoubleSpace/DriveSpace）
- **IO.SYS**：约 20-25KB，支持即插即用
- **MSDOS.SYS**：约 15-20KB，优化性能

---

## DOS 引导程序的内存布局

### 完整内存布局（DOS 启动后）

```
0x00000 - 0x003FF：IVT（中断向量表，1KB）
0x00400 - 0x004FF：BDA（BIOS 数据区，256 字节）
0x00500 - 0x005FF：DOS 通信区（256 字节）
0x00600 - 0x007FF：IO.SYS（DOS 引导程序，约 30KB）
0x00800 - 0x01FFF：MSDOS.SYS（DOS 内核，约 30KB）
0x02000 - 0x0FFFF：COMMAND.COM 和用户程序（约 600KB）
0x10000 - 0x9FFFF：扩展内存（如果可用）
0xA0000 - 0xBFFFF：视频 RAM（128KB）
0xC0000 - 0xDFFFF：扩展 ROM（128KB）
0xE0000 - 0xFFFFF：BIOS ROM 映射（128KB）
```

### 引导过程中的内存使用

**阶段 1：引导扇区（0x7C00）**
```
0x7C00 - 0x7DFF：引导扇区代码（512 字节）
   └─ 执行：读取 IO.SYS，加载到 0x00600
```

**阶段 2：IO.SYS 加载后**
```
0x00600 - 0x007FF：IO.SYS 代码（DOS 引导程序）
0x00800+：准备加载 MSDOS.SYS
0x7C00 - 0x7DFF：引导扇区（已执行完毕，可能被覆盖）
```

**阶段 3：MSDOS.SYS 加载后**
```
0x00600 - 0x007FF：IO.SYS
0x00800 - 0x01FFF：MSDOS.SYS
0x02000+：准备加载 COMMAND.COM
```

**阶段 4：DOS 完全启动**
```
0x00600 - 0x01FFF：DOS 内核（IO.SYS + MSDOS.SYS）
0x02000 - 0x0FFFF：COMMAND.COM 和用户程序
```

---

## DOS 引导程序的关键代码

### 引导扇区加载 IO.SYS

```asm
; DOS 引导扇区代码（简化示例）
org 0x7C00

start:
    ; 初始化段寄存器
    cli
    xor ax, ax
    mov ds, ax
    mov es, ax
    mov ss, ax
    mov sp, 0x7C00
    sti
    
    ; 查找 IO.SYS 在根目录
    mov ax, 0x0201        ; 读取 1 个扇区
    mov cx, 0x0002        ; 从扇区 2 开始（根目录）
    mov dx, 0x0080        ; 驱动器 0x80（第一块硬盘）
    mov bx, 0x0500        ; 读取到 0x0500
    int 0x13              ; 调用 BIOS 磁盘服务
    
    ; 在根目录中查找 "IO      SYS"
    mov si, 0x0500        ; 根目录缓冲区
    mov di, io_sys_name   ; "IO      SYS" 文件名
    mov cx, 11            ; 文件名长度（8+3）
    repe cmpsb            ; 比较文件名
    
    ; 如果找到，加载 IO.SYS
    jne not_found
    ; 读取 IO.SYS 的第一个簇
    ; 加载到 0x00600
    ; 跳转到 0x00600
    
not_found:
    ; 显示错误信息
    mov si, error_msg
    call print_string
    jmp $

io_sys_name db "IO      SYS"
error_msg db "Non-System disk or disk error", 0

times 510-($-$$) db 0
dw 0xAA55
```

### IO.SYS 加载 MSDOS.SYS

```asm
; IO.SYS 代码（简化示例）
org 0x0600

start:
    ; 初始化硬件
    call init_disk
    call init_keyboard
    call init_display
    
    ; 查找 MSDOS.SYS
    ; 读取根目录
    ; 加载 MSDOS.SYS 到 0x00800
    
    ; 跳转到 MSDOS.SYS
    jmp 0x0000:0x0800
```

---

## 关键要点总结

1. **DOS 确实有 bootloader 概念**：
   - 引导扇区：第一阶段引导程序
   - IO.SYS：第二阶段引导程序（DOS 的 bootloader）
   - MSDOS.SYS：DOS 内核
   - COMMAND.COM：命令解释器

2. **DOS 引导程序的特点**：
   - **简单**：功能单一，只负责加载 DOS 内核
   - **硬编码**：没有配置文件，路径和参数硬编码
   - **单系统**：不支持多系统引导
   - **小尺寸**：约 15-20KB

3. **与现代 bootloader 的区别**：
   - **现代 bootloader**（如 GRUB）：功能复杂，支持多系统、配置文件、图形界面
   - **DOS 引导程序**：功能简单，只负责加载 DOS 内核

4. **历史意义**：
   - DOS 的引导程序是现代 bootloader 的前身
   - 奠定了多阶段引导的基础
   - 影响了后续操作系统的设计

---

## 相关文档

- [BOOT_FLOW.md](BOOT_FLOW.md) - 完整的引导流程分析
- [BIOS_MEMORY_QA.md](BIOS_MEMORY_QA.md) - DOS 时代内存使用情况
- [GUIDE.md](GUIDE.md) - DOS 中断编程指南
