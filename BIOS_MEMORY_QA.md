# BIOS 内存模式 Q&A

本文档包含关于 BIOS 运行模式、内存布局和地址映射的常见问题解答。

## Q&A：常见问题解答

### Q: Bootloader 是运行在保护模式下吗？它被加载到内存的什么位置？

**A: Bootloader（以 GRUB 为例）采用混合模式：初始阶段在实模式下运行，后续阶段切换到保护模式。加载位置取决于阶段：引导扇区在 `0x7C00`，GRUB Core 在 `0x8000`，内核在 `0x100000`（1MB）。**

#### Bootloader 的运行模式

**GRUB Bootloader 的运行模式切换：**

1. **引导扇区阶段（实模式）**
   - **位置**：`0x7C00`（BIOS 加载）
   - **运行模式**：实模式（Real Mode）
   - **代码**：`grub/grub-core/boot/i386/pc/boot.S`
   - **功能**：读取 GRUB Core 的第一个扇区到 `0x8000`

2. **GRUB Core 初始阶段（实模式）**
   - **位置**：`0x8000`（引导扇区加载）
   - **运行模式**：实模式（Real Mode）
   - **代码**：`grub/grub-core/boot/i386/pc/diskboot.S`
   - **功能**：加载 GRUB Core 的剩余部分

3. **GRUB Core 后续阶段（切换到保护模式）**
   - **位置**：`0x8200+`（GRUB Core 的 C 代码部分）
   - **运行模式**：保护模式（Protected Mode）
   - **切换代码**：`grub/grub-core/kern/i386/realmode.S:real_to_prot()`
   - **切换时机**：在 `startup_raw.S` 中调用 `real_to_prot()`
   - **功能**：访问 1MB 以上的内存，加载内核镜像

#### 源代码分析

**GRUB Core 从实模式切换到保护模式：**

```asm
// grub/grub-core/boot/i386/pc/startup_raw.S:76-104
LOCAL (codestart):
    cli     // 禁用中断，准备模式切换
    
    // 设置实模式段寄存器
    xorw    %ax, %ax
    movw    %ax, %ds
    movw    %ax, %ss
    movw    %ax, %es
    
    // 设置实模式栈
    movl    $GRUB_MEMORY_MACHINE_REAL_STACK, %ebp
    movl    %ebp, %esp
    
    sti     // 重新启用中断
    
    // 保存启动驱动器号
    movb    %dl, LOCAL(boot_drive)
    
    // 重置磁盘系统
    int     $0x13
    
    // 关键步骤：从实模式切换到保护模式
    calll   real_to_prot
    
    // 切换到保护模式代码（.code32）
    .code32
    
    // 启用 A20 地址线（访问 1MB 以上内存）
    cld
    call    grub_gate_a20
```

**模式切换函数（real_to_prot）：**

```asm
// grub/grub-core/kern/i386/realmode.S:133-195
real_to_prot:
    .code16
    cli     // 禁用中断
    
    // 步骤 1: 加载全局描述符表（GDT）
    xorw    %ax, %ax
    movw    %ax, %ds
    lgdtl   gdtdesc  // 加载 GDT 描述符
    
    // 步骤 2: 设置 CR0 的 PE 位（Protected Mode Enable）
    movl    %cr0, %eax
    orl     $GRUB_MEMORY_CPU_CR0_PE_ON, %eax  // 设置 PE 位
    movl    %eax, %cr0
    
    // 步骤 3: 跳转到保护模式代码段，刷新预取队列
    ljmpl   $GRUB_MEMORY_MACHINE_PROT_MODE_CSEG, $protcseg
    
    .code32
protcseg:
    // 步骤 4: 重新加载所有段寄存器（使用保护模式段选择子）
    movw    $GRUB_MEMORY_MACHINE_PROT_MODE_DSEG, %ax
    movw    %ax, %ds
    movw    %ax, %es
    movw    %ax, %fs
    movw    %ax, %gs
    movw    %ax, %ss
    
    // 步骤 5: 切换到保护模式栈
    movl    (%esp), %eax
    movl    %eax, GRUB_MEMORY_MACHINE_REAL_STACK
    
    movl    protstack, %eax
    movl    %eax, %esp
    movl    %eax, %ebp
    
    // 步骤 6: 保存实模式 IDT，加载保护模式 IDT（空）
    sidt    LOCAL(realidt)  // 保存实模式 IDT
    lidt    protidt         // 加载保护模式 IDT（空）
    
    ret     // 返回，现在在保护模式下
```

#### Bootloader 的加载位置

**内存布局（GRUB 为例）：**

| 组件 | 加载地址 | 运行模式 | 说明 |
|------|---------|---------|------|
| **引导扇区（boot.S）** | `0x7C00` | 实模式 | BIOS 通过 INT 13h 加载 |
| **GRUB Core（diskboot.S）** | `0x8000` | 实模式 | 引导扇区加载的第一个 512 字节 |
| **GRUB Core（C 代码）** | `0x8200+` | 保护模式 | 切换到保护模式后执行 |
| **内核镜像（bzImage）** | `0x100000`（1MB） | 保护模式 | 需要保护模式访问 |

**详细加载流程：**

```
1. BIOS 加载引导扇区
   ↓
   位置：0x7C00
   模式：实模式
   代码：boot.S（GRUB 引导扇区）
   ↓
2. 引导扇区加载 GRUB Core 第一个扇区
   ↓
   位置：0x8000
   模式：实模式
   代码：diskboot.S（加载剩余扇区）
   ↓
3. diskboot.S 加载 GRUB Core 剩余部分
   ↓
   位置：0x8200+
   模式：实模式（初始）→ 保护模式（切换后）
   代码：startup_raw.S → real_to_prot() → C 代码
   ↓
4. GRUB Core 切换到保护模式
   ↓
   调用：real_to_prot()
   设置：GDT、CR0.PE 位
   结果：进入保护模式
   ↓
5. GRUB Core 在保护模式下加载内核
   ↓
   位置：0x100000（1MB）
   模式：保护模式
   原因：内核镜像通常很大（几 MB 到几十 MB），需要访问 1MB 以上内存
```

#### 为什么需要切换到保护模式？

1. **访问 1MB 以上内存**
   - 实模式只能访问前 1MB（`0x000000 - 0xFFFFF`）
   - 内核镜像通常加载到 `0x100000`（1MB）或更高地址
   - 保护模式可以访问完整的 4GB 地址空间

2. **内核镜像大小限制**
   - 现代 Linux 内核镜像（bzImage）通常为几 MB 到几十 MB
   - 无法放入前 1MB 的实模式地址空间
   - 必须使用保护模式访问更大的内存

3. **内存布局设计**
   ```
   实模式可访问（前 1MB）：
   - 0x000000 - 0x09FFFF：常规 RAM（640KB）
   - 0x0A0000 - 0x0BFFFF：视频 RAM（128KB）
   - 0x0C0000 - 0x0DFFFF：扩展 ROM（128KB）
   - 0x0E0000 - 0xFFFFF：BIOS ROM 映射（128KB）
   
   保护模式可访问（1MB 以上）：
   - 0x100000 - 0xFFFFFFFF：内核镜像、initramfs 等
   ```

#### 内存地址总结

**关键内存地址：**

| 地址 | 用途 | 访问模式 | 说明 |
|------|------|---------|------|
| `0x7C00` | 引导扇区（MBR） | 实模式 | BIOS 加载，512 字节 |
| `0x8000` | GRUB Core 初始部分 | 实模式 | 引导扇区加载，第一个 512 字节 |
| `0x8200+` | GRUB Core 完整代码 | 保护模式 | 切换到保护模式后执行 |
| `0x100000` | 内核镜像（bzImage） | 保护模式 | 1MB 边界，需要保护模式访问 |

**地址空间布局：**

```
0x000000 - 0x09FFFF (640KB)
└─ 常规 RAM
   ├─ 0x0000 - 0x03FF：IVT
   ├─ 0x0400 - 0x04FF：BDA
   └─ 0x7C00 - 0x7DFF：引导扇区

0x0A0000 - 0x0BFFFF (128KB)
└─ 视频 RAM

0x0C0000 - 0x0DFFFF (128KB)
└─ 扩展 ROM

0x0E0000 - 0xFFFFF (128KB)
└─ BIOS ROM 映射

0x8000 - 0x9FFF (约 8KB)
└─ GRUB Core（实模式阶段）

0x100000 - ... (1MB 以上)
└─ 内核镜像（保护模式访问）
```

#### 总结

1. **Bootloader 运行模式**：
   - **初始阶段**：实模式（引导扇区、GRUB Core 初始部分）
   - **后续阶段**：保护模式（GRUB Core 加载内核时）
   - **切换时机**：在 `startup_raw.S` 中调用 `real_to_prot()` 切换到保护模式

2. **加载位置**：
   - **引导扇区**：`0x7C00`（实模式可访问）
   - **GRUB Core**：`0x8000`（实模式可访问，初始阶段）
   - **内核镜像**：`0x100000`（1MB，需要保护模式访问）

3. **为什么需要保护模式**：
   - 内核镜像通常很大（几 MB 到几十 MB），无法放入前 1MB
   - 保护模式可以访问完整的 4GB 地址空间
   - 必须切换到保护模式才能加载内核到 1MB 以上的内存

> **详细说明**：关于 GRUB bootloader 的完整加载流程和模式切换机制，请参见 [BOOT_FLOW.md - 引导扇区程序](BOOT_FLOW.md#引导扇区程序从-seabios-到用户代码的执行) 章节。

### Q: DOS 时代 16 位机只有 1MB 内存，算上 BIOS 使用的 128KB，1MB 都用掉了，那么在哪里加载 DOS？DOS 占用多少内存？位于什么位置？

**A: DOS 加载在 640KB 常规 RAM 中，从低地址开始（通常从 `0x00600` 开始）。BIOS 的 128KB 是映射的 ROM，不占用 RAM 空间，因此 DOS 可以使用完整的 640KB 常规 RAM。**

#### 关键澄清：BIOS 的 128KB 不占用 RAM

**重要概念：映射 vs 占用**

1. **BIOS 的 128KB 是映射，不是占用**
   - **地址范围**：`0xE0000 - 0xFFFFF`（128KB）
   - **物理存储**：BIOS Flash ROM 芯片（独立存储设备）
   - **映射方式**：硬件地址映射（MMIO）
   - **关键点**：**不占用 DRAM 空间**，这是 ROM 的映射，不是 RAM

2. **640KB 常规 RAM 完全可用**
   - **地址范围**：`0x000000 - 0x09FFFF`（640KB）
   - **物理存储**：DRAM 芯片（真正的 RAM）
   - **可用性**：**完全可用于 DOS 和用户程序**
   - **不受 BIOS 映射影响**：BIOS 映射在 `0xE0000-0xFFFFF`，不影响 `0x000000-0x09FFFF`

#### DOS 时代的内存布局（16 位机，1MB 地址空间）

**完整内存布局：**

```
前 1MB 地址空间（0x000000 - 0xFFFFF）：

0x000000 - 0x003FF (1KB)
└─ 中断向量表（IVT）
   └─ 256 个中断向量，每个 4 字节

0x00400 - 0x004FF (256 字节)
└─ BIOS 数据区（BDA）
   └─ 系统配置信息、硬件状态等

0x00500 - 0x005FF (256 字节)
└─ DOS 通信区（可选）
   └─ DOS 内部使用

0x00600 - 0x09FFFF (约 640KB - 1.5KB)
└─ DOS 和用户程序区域（常规 RAM）
   ├─ 0x00600 - 0x07BFF：DOS 内核（IO.SYS/MSDOS.SYS）
   │  └─ DOS 核心代码和数据
   ├─ 0x07C00 - 0x07DFF：引导扇区（临时，DOS 启动后可能被覆盖）
   ├─ 0x07E00 - 0x09FFFF：用户程序、TSR、设备驱动程序等
   │  └─ COMMAND.COM、应用程序、常驻程序等
   └─ 可用内存：约 640KB - 1.5KB（减去 IVT、BDA、DOS 内核等）

0x0A0000 - 0x0BFFFF (128KB)
└─ 视频 RAM（VGA 显存）
   └─ 硬件映射到显卡，不占用 RAM

0x0C0000 - 0x0DFFFF (128KB)
└─ 扩展 ROM（可选 ROM）
   └─ 网卡、显卡等扩展卡的 ROM，硬件映射，不占用 RAM

0x0E0000 - 0x0FFFFF (128KB)
└─ BIOS ROM 映射
   └─ 硬件映射到 BIOS Flash ROM，不占用 RAM
   └─ 这是映射，不是占用！
```

#### DOS 的加载位置和大小

**DOS 的典型加载位置：**

| 组件 | 地址范围 | 大小 | 说明 |
|------|---------|------|------|
| **IVT** | `0x0000 - 0x03FF` | 1KB | 中断向量表 |
| **BDA** | `0x0400 - 0x04FF` | 256 字节 | BIOS 数据区 |
| **DOS 通信区** | `0x0500 - 0x05FF` | 256 字节 | DOS 内部使用 |
| **DOS 内核** | `0x0600 - 0x07BFF` | 约 30KB | IO.SYS/MSDOS.SYS |
| **引导扇区** | `0x7C00 - 0x7DFF` | 512 字节 | 临时，DOS 启动后可能被覆盖 |
| **COMMAND.COM** | `0x07E00+` | 约 50-60KB | DOS 命令解释器 |
| **用户程序** | `0x07E00+` | 可变 | 应用程序、TSR 等 |
| **可用内存** | `0x07E00 - 0x09FFFF` | 约 600KB | 用户程序可用空间 |

**DOS 内核大小：**

- **IO.SYS**：约 15-20KB（I/O 处理）
- **MSDOS.SYS**：约 10-15KB（文件系统、内存管理）
- **总计**：约 25-35KB

**COMMAND.COM 大小：**

- **DOS 6.22**：约 54KB
- **DOS 3.3**：约 25KB
- **不同版本大小不同**

#### 为什么 DOS 可以使用 640KB？

**关键原因：BIOS 的 128KB 是映射，不是占用**

1. **地址空间分配**
   ```
   前 1MB 地址空间分配：
   - 0x000000 - 0x09FFFF：640KB 常规 RAM（真正的 DRAM）
   - 0x0A0000 - 0x0BFFFF：128KB 视频 RAM（硬件映射到显卡）
   - 0x0C0000 - 0x0DFFFF：128KB 扩展 ROM（硬件映射到扩展卡）
   - 0x0E0000 - 0x0FFFFF：128KB BIOS ROM 映射（硬件映射到 Flash ROM）
   
   总计：640KB + 128KB + 128KB + 128KB = 1024KB = 1MB
   ```

2. **物理内存 vs 地址空间**
   - **物理 RAM（DRAM）**：只有 640KB（`0x000000 - 0x09FFFF`）
   - **地址空间**：1MB（`0x000000 - 0xFFFFF`）
   - **其他 384KB**：硬件映射的设备（VGA、ROM、BIOS），不是 RAM

3. **DOS 可用的内存**
   - **总可用 RAM**：640KB（`0x000000 - 0x09FFFF`）
   - **系统占用**：约 1.5KB（IVT、BDA、DOS 通信区）
   - **DOS 内核**：约 30KB（IO.SYS/MSDOS.SYS）
   - **COMMAND.COM**：约 50-60KB
   - **用户程序可用**：约 550-560KB（取决于 DOS 版本和配置）

#### DOS 内存布局示例（DOS 6.22）

**实际内存使用：**

```
0x000000 - 0x003FF (1KB)
└─ IVT（中断向量表）

0x00400 - 0x004FF (256 字节)
└─ BDA（BIOS 数据区）

0x00500 - 0x005FF (256 字节)
└─ DOS 通信区

0x00600 - 0x07BFF (约 30KB)
└─ DOS 内核
   ├─ IO.SYS（I/O 处理）
   └─ MSDOS.SYS（文件系统）

0x07C00 - 0x07DFF (512 字节)
└─ 引导扇区（临时，可能被覆盖）

0x07E00 - 0x09FFFF (约 600KB)
└─ 用户程序区域
   ├─ COMMAND.COM（约 54KB）
   ├─ 设备驱动程序（如 HIMEM.SYS、EMM386.EXE）
   ├─ TSR 程序（常驻内存程序）
   └─ 应用程序（如 EDIT.COM、DEBUG.EXE）
```

**内存使用统计：**

- **系统占用**：约 1.5KB（IVT + BDA + DOS 通信区）
- **DOS 内核**：约 30KB（IO.SYS + MSDOS.SYS）
- **COMMAND.COM**：约 54KB
- **可用内存**：约 550KB（用于用户程序）

#### 为什么是 640KB 限制？

**历史原因：IBM PC/AT 的设计**

1. **IBM PC/AT 的内存布局设计**
   - **前 640KB**：常规 RAM（用户程序）
   - **后 384KB**：系统保留区域（视频、ROM、BIOS）
   - **设计原因**：为硬件设备预留地址空间

2. **640KB 限制的影响**
   - DOS 和用户程序只能使用前 640KB
   - 超过 640KB 的内存需要特殊技术访问（如 EMS、XMS）
   - 这是 DOS 时代的经典限制

3. **突破 640KB 限制的技术**
   - **EMS（Expanded Memory Specification）**：通过页框映射访问扩展内存
   - **XMS（Extended Memory Specification）**：通过保护模式访问 1MB 以上内存
   - **HIMEM.SYS**：XMS 驱动程序
   - **EMM386.EXE**：EMS 模拟器（使用 XMS 模拟 EMS）

#### 总结

1. **DOS 加载位置**：
   - **DOS 内核**：`0x00600 - 0x07BFF`（约 30KB）
   - **COMMAND.COM**：`0x07E00+`（约 50-60KB）
   - **用户程序**：`0x07E00 - 0x09FFFF`（约 550-560KB 可用）

2. **DOS 占用内存**：
   - **DOS 内核**：约 30KB
   - **COMMAND.COM**：约 50-60KB
   - **总计**：约 80-90KB

3. **关键澄清**：
   - **BIOS 的 128KB 是映射，不是占用**：`0xE0000-0xFFFFF` 映射到 BIOS Flash ROM，不占用 RAM
   - **DOS 可以使用完整的 640KB 常规 RAM**：`0x000000 - 0x09FFFF`
   - **640KB 限制是地址空间分配的结果**：后 384KB 分配给硬件设备（VGA、ROM、BIOS）

4. **内存布局**：
   - **640KB 常规 RAM**：DOS 和用户程序
   - **128KB 视频 RAM**：VGA 显存（硬件映射）
   - **128KB 扩展 ROM**：扩展卡 ROM（硬件映射）
   - **128KB BIOS ROM 映射**：BIOS Flash ROM（硬件映射）

---

## 相关文档

- [x86 CPU 运行模式详解](X86_CPU_MODES.md)
- [BIOS 内存布局与地址映射详解](BIOS_MEMORY_LAYOUT.md)
- [Linux 用户空间内存模型详解](LINUX_USERSPACE_MEMORY.md) - Linux 用户空间的内存模型和汇编内存访问
- [BIOS 中断处理完整指南](BIOS_INTERRUPT_COMPLETE.md)
