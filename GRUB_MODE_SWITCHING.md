# GRUB 模式切换函数详解

**重要说明：本文档主要描述 GRUB 在 BIOS 模式（i386_pc）下的模式切换机制。UEFI 模式（i386_efi/x86_64_efi）的实现完全不同，不需要模式切换。详见本文档的 [UEFI 模式说明](#uefi-模式说明)。**

## 从实模式到保护模式的切换

**模式切换的关键步骤（real_to_prot）：**

`startup_raw.S` 中调用的 `real_to_prot` 函数负责从实模式切换到保护模式。这个函数在 `realmode.S` 中实现：

**源代码位置：`grub/grub-core/kern/i386/realmode.S:133-195`**

```asm
// real_to_prot - 从实模式切换到保护模式
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
    // 注意：此时中断仍然是禁用的（cli），不会重新启用（sti）
    // 这是必要的，因为空 IDT 无法处理任何中断，如果发生中断会导致系统崩溃
    
    ret     // 返回，现在在保护模式下（中断禁用）
```

**IDT 定义（源代码位置：`grub/grub-core/kern/i386/realmode.S:119-124`）：**

```asm
LOCAL(realidt):
    .word 0x400    // 实模式 IDT 界限（1024 字节 = 256 个中断向量 × 4 字节）
    .long 0        // 实模式 IDT 基址（0x0000:0000，即 IVT 位置）

protidt:
    .word 0        // 保护模式 IDT 界限（0 = 空 IDT）
    .long 0        // 保护模式 IDT 基址（0 = 空 IDT）
```

**重要说明：`LOCAL(realidt)` 和 `protidt` 的内存位置**

**关键点：这两个数据结构只是存储 IDT 描述符（limit 和 base），不是 IDT 表本身**

1. **数据结构的位置**：
   - `realmode.S` 被包含在 `startup_raw.S` 中（`startup_raw.S:119`：`#include "../../../kern/i386/realmode.S"`）
   - `startup_raw.S` 被加载到内存地址 `0x8200`
   - 因此，`LOCAL(realidt)` 和 `protidt` 这两个数据结构位于 `0x8200+` 的某个位置（作为 `startup_raw.S` 的一部分）
   - 每个数据结构占 6 字节（2 字节 limit + 4 字节 base）

2. **IDT 表本身的位置**：
   - **`protidt`**：base=0，limit=0，表示**空 IDT**（没有实际的 IDT 表）
   - **`LOCAL(realidt)`**：保存的是实模式的 IVT 信息，base=0（IVT 固定位置 `0x0000:0000`）
   - 实际的 IDT 表位置由 IDTR 寄存器中的 base 地址决定
   - 对于 `protidt`，由于 base=0，limit=0，CPU 不会访问任何实际的 IDT 表

3. **与解压程序的重叠问题**：
   - **不会重叠**：`LOCAL(realidt)` 和 `protidt` 位于 `0x8200+`（前 1MB 范围内）
   - 解压程序（LZMA 解压后的 GRUB Core）位于 `0x100000`（1MB）以上
   - 两者位于不同的内存区域，不会发生重叠

4. **内存布局总结**：

```
前 1MB 内存（实模式阶段）：
0x8200 - 0x9063：startup_raw.S（包含 realmode.S）
    ├─ 0x8200+：startup_raw.S 代码
    ├─ 0x8200+（某个偏移）：LOCAL(realidt)（6 字节）
    └─ 0x8200+（某个偏移）：protidt（6 字节）

1MB 以上内存（保护模式阶段）：
0x100000+：解压后的 GRUB Core（LZMA 解压后）
```

**结论：`LOCAL(realidt)` 和 `protidt` 作为 `startup_raw.S` 的一部分，位于前 1MB 范围内（约 `0x8200+`），不会与解压程序（位于 `0x100000+`）重叠。**

**GRUB 在保护模式下处理 IDT 的策略：**

1. **禁用中断（关键安全措施）**：
   - 在 `real_to_prot` 函数开始时执行 `cli`（第 135 行），禁用所有中断
   - **重要**：加载空 IDT 后，**不会重新启用中断**（没有 `sti` 指令）
   - 这意味着 GRUB 在保护模式下**始终禁用中断**，直到需要调用 BIOS 服务时切换回实模式

2. **加载空 IDT**：
   - `protidt` 是一个"空"的 IDT（limit=0，base=0）
   - 在保护模式下，如果发生中断且 IDT 为空，CPU 会触发异常（通常导致系统挂起）
   - **因此必须禁用中断**：这是为什么 GRUB 在保护模式下保持中断禁用的原因

3. **保存实模式 IDT（IVT）**：
   - `LOCAL(realidt)` 保存实模式的 IDT 信息（实际上是 IVT）
   - 界限为 0x400（1024 字节），基址为 0（IVT 固定位置）

4. **需要调用 BIOS 服务时的处理**：
   - 当 GRUB 需要调用 BIOS 服务（如 INT 13h 读取磁盘）时，通过 `prot_to_real` 切换回实模式
   - `prot_to_real` 会恢复实模式的 IDT（IVT），然后调用 BIOS 服务
   - 调用完成后，再次通过 `real_to_prot` 切换回保护模式

**⚠️ 关键问题：保护模式下发生硬件中断怎么办？**

**问题：如果 GRUB 在保护模式下运行时，发生了硬件中断（如键盘按键、定时器中断等）怎么办？**

**答案：GRUB 在保护模式下不需要处理硬件中断，原因如下：**

1. **中断被禁用（`cli`）**：
   - GRUB 在保护模式下执行 `cli` 禁用中断
   - CPU 的 IF（Interrupt Flag）标志被清除
   - **硬件中断请求会被 PIC（可编程中断控制器）记录，但 CPU 不会响应**
   - 中断请求会保持"挂起"（pending）状态，直到中断被重新启用

2. **中断挂起机制**：
   - 当硬件设备（如键盘、定时器）产生中断请求时，PIC 会记录这个请求
   - 如果 CPU 的 IF 标志为 0（中断禁用），PIC 会保持中断请求为挂起状态
   - **中断不会丢失**：当重新启用中断时（`sti`），挂起的中断会被立即处理

3. **GRUB 不需要处理硬件中断**：
   - **GRUB 是引导加载程序**，不是操作系统，不需要响应实时硬件事件
   - GRUB 的主要任务是：
     - 加载配置文件（`grub.cfg`）
     - 显示启动菜单（等待用户选择）
     - 加载 Linux 内核
   - **关键点：用户交互（键盘输入）的处理方式**：
     - **菜单显示循环**：运行在保护模式下（`grub-core/normal/menu.c`）
     - **键盘输入读取**：通过 `grub_getkey()` → `grub_console_getkey()` → `grub_bios_interrupt (0x16, &regs)` 实现
     - **BIOS 服务调用**：`grub_bios_interrupt` 会切换到实模式，调用 BIOS 的 INT 16h 服务读取键盘
     - **BIOS 处理中断**：在实模式下，BIOS 的 INT 16h 服务会处理键盘硬件中断（IRQ 1）
     - **切换回保护模式**：读取完成后，切换回保护模式继续菜单循环
   - **因此**：GRUB 不需要自己处理键盘硬件中断，而是通过 BIOS 服务间接获取键盘输入

4. **切换到实模式时的处理**：
   - 当 GRUB 需要调用 BIOS 服务（如读取磁盘）时，会通过 `prot_to_real` 切换回实模式
   - `prot_to_real` 函数在返回前会执行 `sti`（第 275 行），重新启用中断
   - **此时，任何挂起的中断会被处理**：
     - 如果挂起的是键盘中断，BIOS 会处理它
     - 如果挂起的是定时器中断，BIOS 会处理它
     - 这些中断由 BIOS 的 IVT 处理程序处理，GRUB 不需要关心

5. **设计优势**：
   - **简化代码**：GRUB 不需要实现中断处理程序
   - **减少复杂性**：不需要管理 IDT、中断优先级等
   - **快速执行**：保护模式下的代码执行时间短，中断禁用的时间窗口很小
   - **安全性**：避免在空 IDT 状态下处理中断导致系统崩溃

**总结：GRUB 在保护模式下禁用中断，硬件中断请求会被挂起。当切换到实模式并重新启用中断时，挂起的中断会由 BIOS 处理。GRUB 本身不需要处理任何硬件中断。**

**📝 详细说明：GRUB 菜单显示和键盘输入的处理流程**

**源代码分析：**

1. **菜单显示循环**（`grub-core/normal/menu.c:615-644`）：
   ```c
   // 菜单循环在保护模式下运行
   while (1) {
       int key;
       key = grub_getkey_noblock ();  // 非阻塞读取键盘
       if (key != GRUB_TERM_NO_KEY) {
           // 处理按键
       }
       // ... 其他逻辑
   }
   ```

2. **键盘输入读取**（`grub-core/term/i386/pc/console.c:203-239`）：
   ```c
   static int
   grub_console_getkey (struct grub_term_input *term)
   {
       struct grub_bios_int_registers regs;
       
       // 步骤 1: 检查是否有按键等待（INT 16h, AH=0x01）
       regs.eax = 0x0100;
       regs.flags = GRUB_CPU_INT_FLAGS_DEFAULT;
       grub_bios_interrupt (0x16, &regs);  // 切换到实模式，调用 BIOS
       
       if (regs.flags & GRUB_CPU_INT_FLAGS_ZERO)
           return GRUB_TERM_NO_KEY;  // 没有按键
       
       // 步骤 2: 读取按键（INT 16h, AH=0x00）
       regs.eax = 0x0000;
       regs.flags = GRUB_CPU_INT_FLAGS_DEFAULT;
       grub_bios_interrupt (0x16, &regs);  // 切换到实模式，调用 BIOS
       
       // 返回按键值
       return regs.eax & 0xff;
   }
   ```

3. **BIOS 中断调用**（`grub-core/kern/i386/int.S:19-134`）：
   ```asm
   FUNCTION(grub_bios_interrupt)
       // 步骤 1: 保存寄存器（在保护模式下）
       pushf
       cli
       popf
       // ... 保存其他寄存器
       
       // 步骤 2: 准备 BIOS 中断参数
       movb %al, intno  // 中断号（如 0x16）
       // ... 准备寄存器值
       
       // 步骤 3: 切换到实模式
       PROT_TO_REAL     // 调用 prot_to_real
       .code16          // 现在在实模式下
       
       // 步骤 4: 执行 BIOS 中断调用
       .byte 0xcd       // INT 指令的操作码
   intno:
       .byte 0          // 中断号（如 0x16）
       // ⚠️ 关键：此时在实模式下，CPU 使用 IVT
       // BIOS 的 INT 16h 处理程序会：
       //   1. 处理键盘硬件中断（IRQ 1）
       //   2. 从键盘缓冲区读取扫描码
       //   3. 返回 ASCII 字符和扫描码
       
       // 步骤 5: 切换回保护模式
       REAL_TO_PROT     // 调用 real_to_prot
       .code32          // 现在在保护模式下
       
       // 步骤 6: 恢复寄存器并返回
       // ... 恢复寄存器
       ret
   ```

**完整流程：**

```
保护模式（菜单循环，menu.c）
    ↓
调用 grub_getkey_noblock()
    ↓
调用 grub_console_getkey()
    ↓
调用 grub_bios_interrupt (0x16, &regs)
    ↓
PROT_TO_REAL（prot_to_real）
    ├─ 保存保护模式 IDT（空）
    ├─ 恢复实模式 IDT（IVT）
    ├─ 清除 CR0.PE 位（退出保护模式）
    └─ 执行 sti（重新启用中断）
    ↓
实模式（CPU 现在使用 IVT，中断已启用）
    ↓
执行 INT 16h 指令
    ├─ CPU 使用 IVT[0x16] 查找 BIOS 处理程序
    ├─ 跳转到 BIOS 的 INT 16h 处理程序
    ├─ BIOS 处理程序：
    │   ├─ 如果键盘缓冲区为空，等待键盘中断（IRQ 1）
    │   ├─ 键盘硬件中断发生时，BIOS 处理程序处理中断
    │   ├─ 从键盘缓冲区读取扫描码
    │   └─ 返回 ASCII 字符和扫描码
    └─ BIOS 返回，CPU 继续执行
    ↓
REAL_TO_PROT（real_to_prot）
    ├─ 保存实模式 IDT（IVT）
    ├─ 加载保护模式 IDT（空）
    ├─ 设置 CR0.PE 位（进入保护模式）
    └─ 执行 cli（禁用中断）
    ↓
保护模式（菜单循环继续，获得按键值）
```

**关键点：**

1. **菜单循环在保护模式下运行**：菜单显示、超时处理、选择逻辑等都在保护模式下执行

2. **键盘输入通过 BIOS 服务获取**：
   - 每次读取键盘时，都会切换到实模式
   - 在实模式下调用 BIOS 的 INT 16h 服务
   - BIOS 服务会处理键盘硬件中断（IRQ 1）
   - 返回按键值后，切换回保护模式

3. **不需要 GRUB 处理硬件中断**：
   - GRUB 不需要实现键盘中断处理程序
   - BIOS 的 INT 16h 服务已经处理了所有键盘硬件中断
   - GRUB 只需要调用 BIOS 服务，然后获取结果

4. **中断处理的时机和按键存储机制**：
   - **保护模式下按键发生时**：
     - 键盘硬件产生中断请求（IRQ 1）
     - 由于保护模式下中断被禁用（`cli`），中断请求被 PIC 挂起（pending）
     - **按键数据不会立即存入缓冲区**（因为 BIOS 的键盘中断处理程序还没有执行）
   - **切换到实模式后**：
     - `prot_to_real` 执行 `sti`，重新启用中断
     - **挂起的中断会被立即处理**：BIOS 的键盘中断处理程序（INT 09h）会执行
     - BIOS 处理程序从键盘控制器读取扫描码，转换为按键码，存入 BIOS 的键盘缓冲区（BDA）
   - **调用 INT 16h 读取按键**：
     - 如果缓冲区为空，INT 16h 会等待键盘中断（此时挂起的中断会被处理）
     - 如果缓冲区有数据，直接从缓冲区读取并返回
   - **关键理解**：
     - **不是 CPU 保存按键状态**，而是 **BIOS 的键盘缓冲区**保存按键数据
     - **按键数据在切换到实模式后才被处理**：挂起的中断在实模式下被处理，数据存入缓冲区
     - **GRUB 通过主动调用 BIOS 服务来读取**：程序循环调用 `grub_getkey()`，切换到实模式，调用 INT 16h，从缓冲区读取按键

**📝 详细说明：挂起的中断保存在哪里？**

**答案：挂起的中断保存在 PIC（8259A 可编程中断控制器）的内部寄存器中。**

**PIC 的内部寄存器结构：**

8259A PIC 有三个重要的内部寄存器，用于管理中断请求：

1. **IRR（Interrupt Request Register，中断请求寄存器）**：
   - **位置**：PIC 芯片内部（硬件寄存器）
   - **大小**：8 位（主 PIC 和从 PIC 各有一个）
   - **作用**：记录哪些 IRQ 线有**挂起的中断请求**
   - **工作原理**：
     - 当硬件设备（如键盘）产生中断请求时，PIC 会在 IRR 中设置相应的位
     - 例如：键盘（IRQ1）产生中断时，IRR 的第 1 位（bit 1）被设置为 1
     - **即使 CPU 的 IF 标志为 0（中断禁用），IRR 中的位仍然会被设置**
     - 这就是"挂起"（pending）状态的存储位置

2. **ISR（In-Service Register，正在服务寄存器）**：
   - **位置**：PIC 芯片内部（硬件寄存器）
   - **大小**：8 位（主 PIC 和从 PIC 各有一个）
   - **作用**：记录哪些中断**正在被 CPU 处理**
   - **工作原理**：
     - 当 PIC 向 CPU 发送中断信号，CPU 响应后，PIC 会将 IRR 中的位清除，并在 ISR 中设置相应的位
     - 中断处理完成后，需要发送 EOI（End of Interrupt）给 PIC，PIC 才会清除 ISR 中的位

3. **IMR（Interrupt Mask Register，中断屏蔽寄存器）**：
   - **位置**：PIC 芯片内部（硬件寄存器）
   - **大小**：8 位（主 PIC 和从 PIC 各有一个）
   - **作用**：记录哪些 IRQ 被**软件屏蔽**（禁用）
   - **工作原理**：
     - 如果某个 IRQ 在 IMR 中被屏蔽，即使硬件产生中断请求，PIC 也不会在 IRR 中设置相应的位
     - 这是软件层面的屏蔽，与 CPU 的 IF 标志（`cli`/`sti`）不同

**挂起中断的存储机制：**

```
保护模式下按键发生时：
    ↓
键盘硬件产生中断请求（IRQ1）
    ↓
PIC 在 IRR 中设置 bit 1（IRR[1] = 1）
    ↓
PIC 检查 CPU 的 IF 标志（通过 INTA 信号）
    ↓
IF = 0（中断禁用）→ PIC 不向 CPU 发送中断信号
    ↓
IRR[1] = 1 保持设置状态（挂起状态）
    ↓
切换到实模式后：
    ↓
执行 sti（IF = 1，中断启用）
    ↓
PIC 检测到 IF = 1，向 CPU 发送中断信号
    ↓
CPU 响应中断，PIC 清除 IRR[1]，设置 ISR[1]
    ↓
CPU 跳转到 BIOS 的键盘中断处理程序（INT 09h）
    ↓
BIOS 处理程序读取扫描码，存入键盘缓冲区
    ↓
发送 EOI 给 PIC，PIC 清除 ISR[1]
```

**关键点：**

1. **挂起状态存储在 PIC 的 IRR 寄存器中**：
   - IRR 是 PIC 芯片内部的硬件寄存器
   - 每个 IRQ 对应 IRR 中的一个位
   - 当硬件产生中断请求时，PIC 会在 IRR 中设置相应的位
   - **即使 CPU 中断被禁用，IRR 中的位仍然会被设置**

2. **PIC 与 CPU 的交互**：
   - PIC 通过 INTR 引脚向 CPU 发送中断信号
   - CPU 通过 IF 标志控制是否响应中断
   - 如果 IF = 0，PIC 不会发送中断信号，但 IRR 中的位仍然保持设置

3. **中断处理的时机**：
   - 当 IF 从 0 变为 1（执行 `sti`）时，PIC 会检查 IRR
   - 如果 IRR 中有设置的位，PIC 会立即向 CPU 发送中断信号
   - CPU 响应后，PIC 会清除 IRR 中的位，设置 ISR 中的位

4. **PIC 寄存器访问**：
   - PIC 的寄存器通过 I/O 端口访问（主 PIC：0x20-0x21，从 PIC：0xA0-0xA1）
   - 可以通过 `inb`/`outb` 指令读取/写入 PIC 寄存器
   - 但通常不需要直接访问，PIC 会自动管理 IRR 和 ISR

**总结：**
- **挂起的中断保存在 PIC 的 IRR（Interrupt Request Register）寄存器中**
- **IRR 是 PIC 芯片内部的硬件寄存器**，每个 IRQ 对应一个位
- **即使 CPU 中断被禁用（`cli`），IRR 中的位仍然会被设置**
- **当重新启用中断（`sti`）时，PIC 会检查 IRR，如果有挂起的中断，会立即发送给 CPU**

**📝 详细说明：中断挂起时，具体的按键值保存在哪里？**

**答案：按键值（扫描码）保存在键盘控制器（8042/PS2）的输出缓冲区（Output Buffer）中。**

**键盘控制器的物理位置：**

1. **历史实现（IBM PC/AT，1984 年）**：
   - 8042 是一个**独立的芯片**，直接焊接在主板上
   - 物理位置：主板上，通常靠近键盘接口（PS/2 接口）
   - 芯片型号：Intel 8042 或兼容芯片（如 VIA VT82C42、Winbond W83C42、Holtek HT6542 等）

2. **现代实现（1990 年代至今）**：
   - 8042 的功能已经**集成到芯片组（Chipset）**中
   - 物理位置：芯片组内部（如南桥芯片或 I/O 控制器）
   - **不再是独立的芯片**，而是芯片组的一部分
   - 功能完全兼容：软件接口（I/O 端口 0x60、0x64）保持不变

3. **关键点**：
   - **无论物理实现如何，软件接口都是相同的**（I/O 端口 0x60、0x64）
   - 从软件角度看，键盘控制器的行为完全一致
   - 物理位置的变化不影响编程接口

**键盘控制器的输出缓冲区：**

1. **位置**：键盘控制器（8042）内部（无论是独立芯片还是芯片组集成）
2. **大小**：通常只能保存**1 个字节**（一个扫描码）
3. **访问方式**：通过 I/O 端口 0x60 读取
4. **状态指示**：通过 I/O 端口 0x64 的状态寄存器中的 OBF（Output Buffer Full）位表示

**完整的数据流：**

```
用户按下键盘
    ↓
键盘硬件产生扫描码
    ↓
键盘控制器（8042）接收扫描码
    ↓
键盘控制器将扫描码存入输出缓冲区（1 字节）
    ↓
键盘控制器设置状态寄存器的 OBF 位（bit 0 = 1）
    ↓
键盘控制器通过 IRQ1 向 PIC 发送中断请求
    ↓
PIC 在 IRR[1] 中设置位（IRR[1] = 1）
    ↓
如果 CPU 中断被禁用（IF = 0）：
    ├─ PIC 不向 CPU 发送中断信号
    ├─ IRR[1] = 1 保持设置（挂起状态）
    └─ 扫描码留在键盘控制器的输出缓冲区中
    ↓
切换到实模式，执行 sti（IF = 1）
    ↓
PIC 检测到 IF = 1，向 CPU 发送中断信号
    ↓
CPU 响应中断，跳转到 BIOS 键盘中断处理程序（INT 09h）
    ↓
BIOS 处理程序：
    ├─ 读取状态端口（0x64）检查 OBF 位
    ├─ 从数据端口（0x60）读取扫描码（从键盘控制器的输出缓冲区读取）
    ├─ 处理扫描码，转换为按键码
    └─ 存入 BIOS 的键盘缓冲区（BDA）
```

**关键点：**

1. **扫描码保存在键盘控制器的输出缓冲区中**：
   - 键盘控制器（8042）有一个内部的输出缓冲区
   - 当按键发生时，扫描码会被存入这个缓冲区
   - 缓冲区大小通常只有 1 字节（一个扫描码）
   - 通过 I/O 端口 0x60 可以读取这个缓冲区中的扫描码

2. **状态寄存器（0x64）的 OBF 位**：
   - OBF（Output Buffer Full）= 1：表示输出缓冲区有数据可读
   - OBF = 0：表示输出缓冲区为空
   - BIOS 中断处理程序会检查这个位，确认是否有数据可读

3. **连续按键的处理**：
   - **键盘控制器的输出缓冲区只能保存 1 个扫描码**
   - 如果连续按多个键：
     - 第一个扫描码在输出缓冲区中
     - 后续的扫描码会等待，直到第一个被读取
     - 或者可能会丢失（取决于键盘控制器的设计）
   - **键盘控制器会通过 IRQ1 持续发送中断请求**，直到所有扫描码被读取

4. **中断挂起时的状态**：
   - **PIC 的 IRR[1] = 1**：表示有键盘中断请求（挂起状态）
   - **键盘控制器的输出缓冲区**：包含一个扫描码（等待读取）
   - **状态寄存器的 OBF 位 = 1**：表示输出缓冲区有数据

5. **切换到实模式后的处理**：
   - 中断被重新启用（`sti`）
   - PIC 发送中断信号
   - BIOS 中断处理程序执行
   - 从键盘控制器的输出缓冲区（端口 0x60）读取扫描码
   - 处理扫描码，存入 BIOS 的键盘缓冲区

**源代码证据：**

**BIOS 键盘中断处理程序（`seabios/src/kbd.c:1558-1589`）：**
```c
void VISIBLE16
handle_09(void)
{
    // 读取键盘控制器状态（检查 OBF 位）
    u8 v = inb(PORT_PS2_STATUS);  // PORT_PS2_STATUS = 0x64
    
    // 从键盘控制器读取扫描码（从输出缓冲区读取）
    v = inb(PORT_PS2_DATA);  // PORT_PS2_DATA = 0x60
    
    // 处理扫描码
    process_key(v);
}
```

**关键理解：**

- **PIC 的 IRR**：只记录"有中断请求"（位图），不保存具体的按键值
- **键盘控制器的输出缓冲区**：保存具体的扫描码（1 字节）
- **BIOS 的键盘缓冲区**：保存处理后的按键码（16 个按键码，每个 2 字节）

**数据存储层次：**

```
层次 1：键盘控制器输出缓冲区（硬件）
  ├─ 位置：8042 芯片内部
  ├─ 大小：1 字节（一个扫描码）
  └─ 访问：I/O 端口 0x60

层次 2：PIC 的 IRR 寄存器（硬件）
  ├─ 位置：8259A PIC 芯片内部
  ├─ 大小：8 位（位图）
  └─ 作用：记录"有中断请求"（不保存具体值）

层次 3：BIOS 键盘缓冲区（软件）
  ├─ 位置：BDA（BIOS Data Area）
  ├─ 大小：32 字节（16 个按键码）
  └─ 访问：通过 BDA 指针访问
```

**总结：**
- **中断挂起时，具体的按键值（扫描码）保存在键盘控制器（8042）的输出缓冲区中**
- **输出缓冲区通过 I/O 端口 0x60 访问**
- **状态寄存器（0x64）的 OBF 位指示是否有数据可读**
- **键盘控制器的输出缓冲区通常只能保存 1 个扫描码**
- **连续按键时，后续扫描码会等待或可能丢失**

**⚠️ 重要限制：连续按键的保存能力**

**问题：如果按了一堆按键，全都能保存吗？**

**答案：不能全部保存，有两个层面的限制：**

**1. PIC 的 IRR 寄存器限制：**

- **IRR 是位图寄存器**：每个 IRQ 对应一个位（0 或 1）
- **只能表示"有"或"没有"**：IRR[1] = 1 表示"有键盘中断请求"，但不能表示"有多少个按键"
- **连续按键的处理**：
  - 每个按键都会触发一次 IRQ1 中断请求
  - 如果中断被禁用，每个中断请求都会在 IRR[1] 中设置位
  - **但由于是同一个 IRQ，IRR[1] 只能保持为 1**（不能累加）
  - 当切换到实模式并启用中断后，**只会处理一个中断**（第一个挂起的中断）
  - 处理完成后，如果键盘控制器还在发送中断请求，会再次触发中断

**2. BIOS 键盘缓冲区的限制：**

- **缓冲区大小**：32 字节（16 个按键码，每个按键码占 2 字节）
- **位置**：BDA（BIOS Data Area）中的 `kbd_buf` 字段
- **循环缓冲区**：使用 `kbd_buf_head` 和 `kbd_buf_tail` 指针管理
- **缓冲区满的处理**：
  ```c
  // seabios/src/kbd.c:32-52
  u8 enqueue_key(u16 keycode)
  {
      // ...
      if (buffer_tail == buffer_head)
          return 0;  // 缓冲区满，返回失败
      // ...
  }
  ```
  - 如果缓冲区满了（`buffer_tail == buffer_head`），`enqueue_key()` 会返回 0
  - **新的按键数据会丢失**（不会被存入缓冲区）

**实际场景分析：**

**场景 1：保护模式下快速按多个键**

```
保护模式（中断禁用）：
按键 1 → IRR[1] = 1（挂起）
按键 2 → IRR[1] = 1（仍然是 1，不能累加）
按键 3 → IRR[1] = 1（仍然是 1，不能累加）
...
按键 N → IRR[1] = 1（仍然是 1，不能累加）

切换到实模式（中断启用）：
    ↓
PIC 检测到 IRR[1] = 1 → 发送中断信号
    ↓
CPU 响应中断 → BIOS 键盘中断处理程序执行
    ↓
读取键盘控制器 → 获取扫描码（可能是按键 1、2、3... 中的任意一个）
    ↓
转换为按键码 → 存入键盘缓冲区
    ↓
发送 EOI → PIC 清除 IRR[1]
    ↓
如果键盘控制器还有数据 → 再次触发 IRQ1 → IRR[1] = 1
    ↓
重复上述过程，直到键盘控制器的数据被读取完
```

**关键点：**
- **PIC 的 IRR 只能记录"有中断请求"，不能记录"有多少个"**
- **每个按键都会触发一次中断**，但中断被禁用时，这些中断请求会被"合并"（IRR[1] 保持为 1）
- **切换到实模式后，会逐个处理这些中断**，但处理速度取决于中断处理程序的执行速度

**场景 2：缓冲区满的情况**

```
保护模式下按了 20 个键：
    ↓
切换到实模式，开始处理中断
    ↓
前 16 个按键 → 成功存入缓冲区
    ↓
第 17 个按键 → 缓冲区满（buffer_tail == buffer_head）
    ↓
enqueue_key() 返回 0 → 按键丢失
    ↓
第 18、19、20 个按键 → 全部丢失
```

**关键点：**
- **BIOS 键盘缓冲区只能保存 16 个按键**
- **如果缓冲区满了，新的按键会丢失**
- **GRUB 需要及时读取缓冲区**，避免缓冲区满导致按键丢失

**GRUB 的处理策略：**

1. **频繁轮询**：
   - GRUB 的菜单循环会频繁调用 `grub_getkey_noblock()`（非阻塞读取）
   - 这样可以及时从缓冲区读取按键，避免缓冲区满

2. **快速处理**：
   - 每次切换到实模式读取键盘时，会尽可能快地处理
   - 减少在保护模式下的时间，增加切换到实模式的频率

3. **实际限制**：
   - 如果用户在保护模式下快速按了很多键（超过 16 个），部分按键可能会丢失
   - 但在实际使用中，GRUB 的菜单循环会频繁切换到实模式读取键盘，通常不会出现缓冲区满的情况

**总结：**
- **PIC 的 IRR 寄存器**：只能记录"有中断请求"（位图），不能记录"有多少个"
- **BIOS 键盘缓冲区**：只能保存 16 个按键（32 字节）
- **连续按键的处理**：会逐个处理，但如果缓冲区满了，新的按键会丢失
- **实际使用**：GRUB 的频繁轮询机制通常可以避免按键丢失

**⚠️ 重要风险：空 IDT 与 CPU 异常处理**

**关键问题：禁用中断（`cli`）只能防止硬件中断，无法防止 CPU 异常**

1. **硬件中断 vs CPU 异常的区别**：
   - **硬件中断**：由外部设备触发（如键盘、定时器、磁盘等），可以通过 `cli` 禁用
   - **CPU 异常**：由 CPU 内部触发（如除零错误、页错误、无效操作码等），**无法通过 `cli` 禁用**

2. **空 IDT 的风险**：
   - 如果 GRUB 在保护模式下发生 CPU 异常（如页错误、除零错误、无效操作码等），CPU 会尝试通过 IDT 查找异常处理程序
   - 但 IDT 是空的（limit=0），CPU 无法找到异常处理程序
   - 这会导致 CPU 触发"双重故障"（Double Fault，向量 8）
   - 如果双重故障也无法处理（因为 IDT 仍然是空的），CPU 会触发"三重故障"（Triple Fault），导致系统立即重启或挂起

3. **GRUB 的保护措施**：
   - **代码简单**：GRUB 在保护模式下的代码相对简单，主要是内存操作、解压缩等
   - **不使用分页**：GRUB 使用平坦内存模型（flat memory model），不启用分页，避免页错误异常
   - **避免危险操作**：
     - 避免除零操作
     - 避免无效的内存访问（通过仔细的内存管理）
     - 避免无效的操作码（使用标准汇编指令）
   - **快速执行**：GRUB 在保护模式下的执行时间尽可能短，减少出错窗口

4. **设计权衡**：
   - **优点**：简化代码，不需要实现完整的 IDT 和异常处理机制
   - **缺点**：必须非常小心地编写代码，任何错误都可能导致系统崩溃
   - **适用场景**：GRUB 作为引导加载程序，代码相对简单且执行时间短，这种权衡是合理的

5. **与 Linux 内核的对比**：
   - **Linux 内核**：在保护模式下建立完整的 IDT，为所有 CPU 异常设置专门的处理程序
   - **GRUB**：使用空 IDT，依赖代码正确性来避免异常
   - **原因**：GRUB 是引导加载程序，代码简单且执行时间短；Linux 内核是操作系统，需要完整的异常处理机制

**总结：GRUB 在保护模式下使用空 IDT 是一个高风险的设计选择，必须通过代码正确性和简单性来降低风险。任何代码错误（如除零、无效内存访问等）都可能导致系统立即崩溃。**

## 从保护模式到实模式的切换

**prot_to_real 函数（源代码位置：`grub/grub-core/kern/i386/realmode.S:217-279`）：**

```asm
prot_to_real:
    // 步骤 1: 设置 GDT
    lgdt    gdtdesc
    
    // 步骤 2: 保存保护模式 IDT，恢复实模式 IDT（IVT）
    sidt    protidt         // 保存保护模式 IDT（空）
    lidt    LOCAL(realidt)  // 恢复实模式 IDT（IVT）
    
    // 步骤 3: 保存保护模式栈
    movl    %esp, %eax
    movl    %eax, protstack
    
    // 步骤 4: 保存返回地址（关键！）
    movl    (%esp), %eax
    movl    %eax, GRUB_MEMORY_MACHINE_REAL_STACK  // 保存到 1MB 以下的内存
    
    // 步骤 5-6: 切换到实模式（清除 CR0.PE 位等）
    // ...
    
    // 步骤 7: 恢复中断
    sti
    
    retl    // 返回，现在在实模式下
```

**⚠️ 关键问题：prot_to_real 执行后，GRUB 程序运行在 1MB 以上，如何解决？**

**问题描述：**
- GRUB 的解压后代码位于 `0x100000+`（1MB 以上）
- 当从保护模式的代码（在 1MB 以上）调用 `prot_to_real` 时，返回地址指向 1MB 以上的代码
- 切换到实模式后，实模式只能访问 1MB 以下的内存（`0x00000 - 0xFFFFF`）
- **问题**：如何返回到 1MB 以上的代码？

**解决方案：**

1. **`prot_to_real` 和 `real_to_prot` 本身位于 1MB 以下**：
   - 这两个函数被包含在 `startup_raw.S` 中（`startup_raw.S:119`：`#include "../../../kern/i386/realmode.S"`）
   - `startup_raw.S` 被加载到内存地址 `0x8200`（1MB 以下）
   - 因此，`prot_to_real` 和 `real_to_prot` 的代码本身位于 1MB 以下，可以在实模式下执行

2. **返回地址的保存和恢复机制**：
   - **`prot_to_real`**：保存返回地址到 `GRUB_MEMORY_MACHINE_REAL_STACK`（位于 1MB 以下，`0x2000 - 0x10`）
   - **切换到实模式**：执行 BIOS 调用（在实模式下）
   - **`real_to_prot`**：从 `GRUB_MEMORY_MACHINE_REAL_STACK` 恢复返回地址
   - **切换回保护模式**：返回到保护模式的代码（此时已经在保护模式下，可以访问 1MB 以上的代码）

**返回地址保存和恢复的源代码详解：**

**1. GRUB_MEMORY_MACHINE_REAL_STACK 定义（源代码位置：`grub/include/grub/i386/memory_raw.h:29`）：**

```c
#define GRUB_MEMORY_MACHINE_REAL_STACK	(0x2000 - 0x10)
```

- **地址**：`0x1FF0`（1MB 以下，实模式可访问）
- **用途**：临时存储返回地址，用于模式切换

**2. prot_to_real 保存返回地址（源代码位置：`grub/grub-core/kern/i386/realmode.S:228-235`）：**

```asm
prot_to_real:
    // ... (设置 GDT、IDT 等)
    
    // 步骤 1: 保存保护模式栈
    movl    %esp, %eax
    movl    %eax, protstack
    
    // 步骤 2: 保存返回地址到 1MB 以下的内存（关键！）
    movl    (%esp), %eax                    // 从栈顶读取返回地址（指向 1MB 以上的代码）
    movl    %eax, GRUB_MEMORY_MACHINE_REAL_STACK  // 保存到 0x1FF0（1MB 以下）
    
    // 步骤 3: 设置新的栈（使用 GRUB_MEMORY_MACHINE_REAL_STACK 作为栈）
    movl    $GRUB_MEMORY_MACHINE_REAL_STACK, %eax
    movl    %eax, %esp                      // 栈指针指向 0x1FF0
    movl    %eax, %ebp
    
    // ... (切换到实模式)
    
    retl    // 返回到实模式代码（grub_bios_interrupt 的实模式部分）
```

**3. real_to_prot 恢复返回地址（源代码位置：`grub/grub-core/kern/i386/realmode.S:175-186`）：**

```asm
real_to_prot:
    .code16
    cli
    
    // ... (加载 GDT、设置 CR0.PE 位、跳转到保护模式)
    
    .code32
protcseg:
    // ... (重新加载段寄存器)
    
    // 步骤 1: 保存返回地址到 1MB 以下的内存（从实模式栈读取）
    movl    (%esp), %eax                    // 从栈顶读取返回地址（实模式代码的返回地址）
    movl    %eax, GRUB_MEMORY_MACHINE_REAL_STACK  // 保存到 0x1FF0
    
    // 步骤 2: 切换到保护模式栈
    movl    protstack, %eax                  // 恢复保护模式栈指针
    movl    %eax, %esp
    movl    %eax, %ebp
    
    // 步骤 3: 恢复返回地址到保护模式栈（关键！）
    movl    GRUB_MEMORY_MACHINE_REAL_STACK, %eax  // 从 0x1FF0 读取返回地址
    movl    %eax, (%esp)                    // 将返回地址放到保护模式栈顶
    
    // ... (加载空 IDT)
    
    ret     // 返回到保护模式代码（1MB 以上，此时已在保护模式下，可以访问）
```

**4. grub_bios_interrupt 完整实现（源代码位置：`grub/grub-core/kern/i386/int.S:19-134`）：**

```asm
FUNCTION(grub_bios_interrupt)
    // 步骤 1: 保存寄存器（在保护模式下）
    pushf
    cli
    popf
    pushl    %ebp
    pushl    %ecx
    pushl    %eax
    pushl    %ebx
    pushl    %esi
    pushl    %edi
    pushl    %edx
    
    // 步骤 2: 准备 BIOS 中断参数（在保护模式下）
    movb     %al, intno                    // 保存中断号到 intno 位置（第 87 行）
    movl     (%edx), %eax                  // 从参数结构读取 EAX 值
    movl     %eax, LOCAL(bios_register_eax)  // 保存到局部变量
    movw     4(%edx), %ax                  // 读取 ES 值
    movw     %ax, LOCAL(bios_register_es)
    movw     6(%edx), %ax                  // 读取 DS 值
    movw     %ax, LOCAL(bios_register_ds)
    movw     8(%edx), %ax                  // 读取 FLAGS 值
    movw     %ax, LOCAL(bios_register_flags)
    
    movl     12(%edx), %ebx                // 读取 EBX 值
    movl     16(%edx), %ecx                // 读取 ECX 值
    movl     20(%edx), %edi                // 读取 EDI 值
    movl     24(%edx), %esi                // 读取 ESI 值
    movl     28(%edx), %edx                // 读取 EDX 值
    
    // 步骤 3: 切换到实模式（调用 prot_to_real）
    PROT_TO_REAL                // 宏展开为：call prot_to_real
    .code16                      // 现在在实模式下（16 位代码）
    
    // 步骤 4: 设置 BIOS 中断所需的寄存器（在实模式下）
    pushf
    cli
    mov     %ds, %ax
    push    %ax
    
    // 设置 ES 寄存器
    .byte   0xb8                // movw imm16, %ax 的操作码
LOCAL(bios_register_es):
    .short  0                   // ES 值（在保护模式下已设置）
    movw    %ax, %es
    
    // 设置 DS 寄存器
    .byte   0xb8                // movw imm16, %ax 的操作码
LOCAL(bios_register_ds):
    .short  0                   // DS 值（在保护模式下已设置）
    movw    %ax, %ds
    
    // 设置 FLAGS 寄存器
    .byte   0xb8                // movw imm16, %ax 的操作码
LOCAL(bios_register_flags):
    .short  0                   // FLAGS 值（在保护模式下已设置）
    push    %ax
    popf                        // 恢复 FLAGS
    
    // 设置 EAX 寄存器
    .byte   0x66, 0xb8          // movl imm32, %eax 的操作码（0x66 是 32 位操作数前缀）
LOCAL(bios_register_eax):
    .long   0                   // EAX 值（在保护模式下已设置）
    
    // 步骤 5: 执行 BIOS 中断调用（在实模式下，关键！）
    .byte   0xcd                // INT 指令的操作码
intno:                          // 中断号位置（在保护模式下第 31 行已设置）
    .byte   0                   // 中断号（如 0x13，会被 movb %al, intno 修改）
    // ⚠️ 注意：这里执行的是实际的 BIOS 中断调用
    // CPU 会查找 IVT[intno]，跳转到 BIOS 处理程序，执行 BIOS 服务，然后返回
    
    // 步骤 6: 保存 BIOS 返回的寄存器值（在实模式下）
    movl    %eax, %cs:LOCAL(bios_register_eax)  // 保存 BIOS 返回的 EAX
    movw    %ds, %ax
    movw    %ax, %cs:LOCAL(bios_register_ds)    // 保存 BIOS 返回的 DS
    pop     %ax
    mov     %ax, %ds
    pushf
    pop     %ax
    movw    %ax, LOCAL(bios_register_flags)     // 保存 BIOS 返回的 FLAGS
    mov     %es, %ax
    movw    %ax, LOCAL(bios_register_es)        // 保存 BIOS 返回的 ES
    
    popf
    
    // 步骤 7: 切换回保护模式（调用 real_to_prot）
    REAL_TO_PROT                // 宏展开为：calll real_to_prot
    .code32                     // 现在在保护模式下（32 位代码）
    
    // 步骤 8: 恢复寄存器并返回（在保护模式下）
    popl    %eax                // 恢复参数结构指针
    
    // 将 BIOS 返回的寄存器值写回参数结构
    movl    %ebx, 12(%eax)      // 保存 EBX
    movl    %ecx, 16(%eax)      // 保存 ECX
    movl    %edi, 20(%eax)      // 保存 EDI
    movl    %esi, 24(%eax)      // 保存 ESI
    movl    %edx, 28(%eax)      // 保存 EDX
    
    movl    %eax, %edx          // %edx 指向参数结构
    
    // 从局部变量读取 BIOS 返回的值
    movl    LOCAL(bios_register_eax), %eax
    movl    %eax, (%edx)        // 保存 EAX 返回值
    movw    LOCAL(bios_register_es), %ax
    movw    %ax, 4(%edx)       // 保存 ES 返回值
    movw    LOCAL(bios_register_ds), %ax
    movw    %ax, 6(%edx)       // 保存 DS 返回值
    movw    LOCAL(bios_register_flags), %ax
    movw    %ax, 8(%edx)       // 保存 FLAGS 返回值
    
    // 恢复所有寄存器
    popl    %edi
    popl    %esi
    popl    %ebx
    popl    %eax
    popl    %ecx
    popl    %ebp
    ret                         // 返回到调用者（1MB 以上的保护模式代码）
```

**BIOS 调用的关键代码（第 85-88 行）：**

```asm
// 执行 BIOS 中断调用
.byte   0xcd                // INT 指令的操作码（x86 指令：INT imm8）
intno:                      // 中断号标签（地址位置）
    .byte   0               // 中断号（如 0x13，在保护模式下第 31 行已设置）
```

**执行流程：**

1. **第 31 行**：`movb %al, intno` - 将中断号（从 `%al` 寄存器）写入 `intno` 位置（第 87 行）
2. **第 85-88 行**：执行 `INT` 指令
   - `0xcd` 是 `INT imm8` 指令的操作码
   - `intno` 位置存储中断号（如 0x13）
   - CPU 执行 `INT 0x13` 时：
     - 查找 IVT[0x13]（实模式中断向量表）
     - 跳转到 BIOS 的 INT 13h 处理程序
     - BIOS 执行磁盘服务（如读取扇区）
     - BIOS 返回，CPU 继续执行第 90 行

**为什么使用 `.byte` 而不是 `int $0x13`？**

- 中断号是**动态的**（从 `%al` 寄存器传入）
- 使用 `.byte` 可以在运行时修改中断号
- `int $0x13` 是静态的，只能调用固定的中断号

**`imm8` 的含义：**

- **`imm8`** = **immediate 8-bit**（8 位立即数）
  - `imm` = immediate（立即数，直接编码在指令中的常量值）
  - `8` = 8 位（1 字节，范围 0-255）
- **`INT imm8`** 指令格式：
  - 操作码：`0xCD`（1 字节）
  - 中断号：`imm8`（1 字节，0-255）
  - 总长度：2 字节
- **为什么是 8 位？**
  - x86 中断向量表（IVT）有 256 个条目（0x00-0xFF）
  - 8 位可以表示 0-255，正好对应 256 个中断向量
  - 因此 `INT` 指令使用 8 位立即数作为中断号

**其他立即数格式：**
- **`imm16`**：16 位立即数（2 字节，范围 0-65535）
- **`imm32`**：32 位立即数（4 字节，范围 0-4294967295）

**示例：**
```asm
int $0x13        // INT imm8：中断号 0x13（静态，编译时确定）
.byte 0xcd       // INT 指令操作码
.byte 0x13       // imm8：中断号 0x13（等同于 int $0x13）

// 动态中断号（GRUB 使用的方式）
.byte 0xcd       // INT 指令操作码
intno:
.byte 0          // imm8：中断号（运行时修改，如 movb %al, intno）
```

**关键点说明：**

1. **返回地址的保存时机**：
   - `prot_to_real`：在切换到实模式**之前**保存返回地址（第 229-230 行）
   - `real_to_prot`：在切换到保护模式**之后**恢复返回地址（第 185-186 行）

2. **内存位置的重要性**：
   - `GRUB_MEMORY_MACHINE_REAL_STACK = 0x1FF0`（1MB 以下）
   - 实模式和保护模式都可以访问此地址
   - 作为临时存储位置，确保返回地址在模式切换过程中不丢失

3. **栈的使用**：
   - `prot_to_real`：将栈指针设置为 `GRUB_MEMORY_MACHINE_REAL_STACK`，返回地址就存储在这个位置
   - `real_to_prot`：从 `GRUB_MEMORY_MACHINE_REAL_STACK` 读取返回地址，放到保护模式栈顶

4. **完整的地址流程**：
   ```
   保护模式代码（1MB 以上，如 0x100123）
       ↓
   调用 grub_bios_interrupt()
       ↓
   调用 prot_to_real
       ├─ 返回地址 0x100123 保存到 0x1FF0
       └─ 切换到实模式
       ↓
   grub_bios_interrupt 实模式部分（1MB 以下，0x8200+）
       ↓
   执行 BIOS 调用（INT 13h 等）
       ↓
   调用 real_to_prot
       ├─ 从 0x1FF0 读取返回地址 0x100123
       ├─ 切换到保护模式
       └─ 将返回地址放到保护模式栈顶
       ↓
   返回到保护模式代码（1MB 以上，0x100123）
   ```

**完整流程：**

```
保护模式代码（1MB 以上，0x100000+）
    ↓
调用 grub_bios_interrupt()
    ↓
调用 prot_to_real（位于 1MB 以下，0x8200+）
    ├─ 保存返回地址到 GRUB_MEMORY_MACHINE_REAL_STACK（1MB 以下）
    ├─ 切换到实模式
    └─ 返回到 grub_bios_interrupt() 的实模式部分（位于 1MB 以下）
        ↓
执行 BIOS 调用（INT 13h 等，在实模式下）
    ↓
调用 real_to_prot（位于 1MB 以下，0x8200+）
    ├─ 从 GRUB_MEMORY_MACHINE_REAL_STACK 恢复返回地址
    ├─ 切换到保护模式
    └─ 返回到 grub_bios_interrupt() 的保护模式部分（位于 1MB 以上）
        ↓
返回到保护模式代码（1MB 以上，0x100000+）
```

**关键点总结：**

| 组件 | 内存位置 | 运行模式 | 说明 |
|------|---------|---------|------|
| **prot_to_real / real_to_prot** | `0x8200+`（1MB 以下） | 实模式/保护模式 | 模式切换函数本身位于 1MB 以下 |
| **grub_bios_interrupt** | `0x100000+`（1MB 以上） | 保护模式 | 但包含实模式代码段（`.code16`） |
| **返回地址保存位置** | `GRUB_MEMORY_MACHINE_REAL_STACK`（`0x2000 - 0x10`，1MB 以下） | - | 临时存储返回地址 |
| **GRUB Core 解压后代码** | `0x100000+`（1MB 以上） | 保护模式 | 主代码运行位置 |

**设计优势：**
- **模式切换函数位于 1MB 以下**：可以在实模式下执行
- **返回地址保存在 1MB 以下**：实模式可以访问
- **代码分段组织**：`grub_bios_interrupt` 包含保护模式和实模式代码段，通过模式切换函数连接

## 重要澄清：保护模式下不能直接使用 BIOS 的 IVT

**关键点：**
1. **保护模式下 CPU 使用 IDT，不使用 IVT**：
   - 在保护模式下，CPU 只使用 IDT（中断描述符表），不会使用 IVT（中断向量表）
   - IVT 只在实模式下有效（固定位置 0x0000:0000）
   - 即使 IVT 仍然存在于内存中，保护模式下的 CPU 也不会访问它

2. **GRUB 在保护模式下使用空 IDT**：
   - GRUB 在保护模式下加载的是空 IDT（limit=0，base=0）
   - 如果保护模式下发生中断，CPU 会尝试访问 IDT，但由于 IDT 为空，会导致异常
   - 因此 GRUB 在保护模式下禁用中断（`cli`），避免触发中断

3. **调用 BIOS 服务必须切换回实模式**：
   - 当 GRUB 需要调用 BIOS 服务（如 INT 13h 读取磁盘）时，**必须切换回实模式**
   - 切换回实模式后，CPU 才会使用 IVT，此时才能调用 BIOS 中断服务

**GRUB 调用 BIOS 服务的完整流程（源代码位置：`grub/grub-core/kern/i386/int.S:19-134`）：**

```asm
// grub_bios_interrupt - 在保护模式下调用 BIOS 中断服务
FUNCTION(grub_bios_interrupt)
    // 步骤 1: 保存寄存器（在保护模式下）
    pushf
    cli
    popf
    pushl    %ebp
    pushl    %ecx
    pushl    %eax
    // ... 保存其他寄存器
    
    // 步骤 2: 准备 BIOS 中断参数
    movb     %al, intno        // 中断号（如 0x13）
    movl     (%edx), %eax
    movl     %eax, LOCAL(bios_register_eax)
    // ... 准备其他寄存器值
    
    // 步骤 3: 切换到实模式
    PROT_TO_REAL                // 调用 prot_to_real
    .code16                      // 现在在实模式下
    
    // 步骤 4: 设置 BIOS 中断所需的寄存器
    movw     LOCAL(bios_register_es), %ax
    movw     %ax, %es
    movw     LOCAL(bios_register_ds), %ax
    movw     %ax, %ds
    // ... 设置其他寄存器
    
    // 步骤 5: 调用 BIOS 中断服务（在实模式下）
    .byte   0xcd                // INT 指令的操作码
intno:
    .byte   0                   // 中断号（如 0x13）
    
    // 步骤 6: 保存 BIOS 返回的寄存器值
    movl    %eax, %cs:LOCAL(bios_register_eax)
    movw    %ds, %ax
    movw    %ax, %cs:LOCAL(bios_register_ds)
    // ... 保存其他寄存器
    
    // 步骤 7: 切换回保护模式
    REAL_TO_PROT                // 调用 real_to_prot
    .code32                     // 现在在保护模式下
    
    // 步骤 8: 恢复寄存器并返回（在保护模式下）
    popl    %eax
    // ... 恢复其他寄存器
    ret
```

**流程总结：**

```
保护模式（GRUB 主代码）
    ↓
需要调用 BIOS 服务（如 INT 13h）
    ↓
调用 grub_bios_interrupt()
    ↓
PROT_TO_REAL（prot_to_real）
    ├─ 保存保护模式 IDT（空）
    ├─ 恢复实模式 IDT（IVT）
    ├─ 清除 CR0.PE 位（退出保护模式）
    └─ 切换到实模式
    ↓
实模式（CPU 现在使用 IVT）
    ↓
执行 INT 指令（如 INT 13h）
    ├─ CPU 使用 IVT[0x13] 查找处理程序
    ├─ 跳转到 BIOS 处理程序
    └─ BIOS 执行服务并返回
    ↓
REAL_TO_PROT（real_to_prot）
    ├─ 保存实模式 IDT（IVT）
    ├─ 加载保护模式 IDT（空）
    ├─ 设置 CR0.PE 位（进入保护模式）
    └─ 切换到保护模式
    ↓
保护模式（GRUB 主代码继续执行）
```

**关键结论：**

| 模式 | CPU 使用的中断表 | GRUB 的 IDT/IVT 状态 | 能否调用 BIOS 服务 |
|------|----------------|---------------------|-------------------|
| **实模式** | IVT（固定 0x0000:0000） | 使用 BIOS 的 IVT | ✅ 可以直接调用（INT 指令） |
| **保护模式** | IDT（由 IDTR 指定） | 使用空 IDT（limit=0） | ❌ **不能直接调用**，必须切换回实模式 |

**关键点总结：**

| 组件 | 运行模式 | 中断表类型 | 中断表位置 | 处理策略 |
|------|---------|-----------|-----------|---------|
| **BIOS** | 实模式 | IVT | 固定 0x0000:0000 | 提供中断服务 |
| **GRUB（保护模式）** | 保护模式 | IDT（空） | 可配置（但设为空） | **禁用中断（cli）**，需要时切换回实模式 |
| **GRUB（调用 BIOS）** | 实模式 | IVT | 固定 0x0000:0000 | 恢复 IVT，调用 BIOS 服务 |
| **Linux 内核** | 保护模式/长模式 | IDT | 内核内存（可配置） | 建立完整的 IDT，接管所有中断 |

> **注意**：关于 A20 地址线的详细技术说明，请参见 [A20 地址线技术详解](A20_ADDRESS_LINE.md)。

> **相关文档**：关于 `grub_bios_interrupt` 的使用场景和调用时机，请参见 [GRUB 在保护模式下调用 BIOS 服务的使用场景](GRUB_BIOS_INTERRUPT_USAGE.md)。

---

## UEFI 模式说明

**重要：本文档前面描述的模式切换机制（`real_to_prot`、`prot_to_real`、`grub_bios_interrupt`）仅适用于 BIOS 模式（i386_pc）。UEFI 模式（i386_efi/x86_64_efi）的实现完全不同。**

### UEFI 模式的关键差异

**1. UEFI 固件已经在保护模式/长模式下运行：**

- **UEFI 固件本身**：在保护模式（32位）或长模式（64位）下运行
- **GRUB 启动时**：直接以保护模式/长模式启动，**不需要模式切换**
- **无需 `real_to_prot`**：GRUB 启动时已经在保护模式/长模式下
- **无需 `prot_to_real`**：不需要切换回实模式

**2. 使用 EFI 服务而不是 BIOS 中断：**

- **BIOS 模式**：通过 `grub_bios_interrupt()` 调用 BIOS 中断服务（INT 10h, INT 13h, INT 16h 等）
- **UEFI 模式**：直接调用 EFI 服务（函数调用接口）
- **无需模式切换**：EFI 服务在保护模式/长模式下直接可用

**3. GRUB 源代码对比：**

**BIOS 模式（i386_pc）的启动代码**（`grub-core/kern/i386/pc/startup.S`）：
```asm
_start:
    // 接收参数（通过寄存器）
    // %esi = 解压后的代码基址（0x100000）
    // %edi = prot_to_real 函数地址
    // %ecx = real_to_prot 函数地址
    // %eax = realidt 地址
    // %edx = 启动设备号
    
    // 保存模式切换函数地址
    movl %ecx, (LOCAL(real_to_prot_addr) - _start) (%esi)
    movl %edi, (LOCAL(prot_to_real_addr) - _start) (%esi)
    // ... 清理 BSS、调用 grub_main()
```

**UEFI 模式（i386_efi）的启动代码**（`grub-core/kern/i386/efi/startup.S`）：
```asm
_start:
    /*
     * EFI_SYSTEM_TABLE * and EFI_HANDLE are passed on the stack.
     */
    movl 4(%esp), %eax
    movl %eax, EXT_C(grub_efi_image_handle)
    movl 8(%esp), %eax
    movl %eax, EXT_C(grub_efi_system_table)
    call EXT_C(grub_main)
    ret
```

**关键差异：**
- **BIOS 模式**：需要保存 `real_to_prot` 和 `prot_to_real` 函数地址，用于后续模式切换
- **UEFI 模式**：直接保存 `EFI_SYSTEM_TABLE` 和 `EFI_HANDLE`，用于调用 EFI 服务
- **UEFI 模式没有模式切换函数**：因为不需要切换模式

**4. 键盘输入的实现对比：**

**BIOS 模式**（`grub-core/term/i386/pc/console.c:203-239`）：
```c
static int
grub_console_getkey (struct grub_term_input *term)
{
    struct grub_bios_int_registers regs;
    
    // 检查是否有按键等待（INT 16h, AH=0x01）
    regs.eax = 0x0100;
    grub_bios_interrupt (0x16, &regs);  // 切换到实模式，调用 BIOS
    
    // 读取按键（INT 16h, AH=0x00）
    regs.eax = 0x0000;
    grub_bios_interrupt (0x16, &regs);  // 切换到实模式，调用 BIOS
    
    return regs.eax & 0xff;
}
```

**UEFI 模式**（`grub-core/term/efi/console.c:240-253`）：
```c
static int
grub_console_getkey_con (struct grub_term_input *term)
{
    grub_efi_simple_input_interface_t *i;
    grub_efi_input_key_t key;
    grub_efi_status_t status;
    
    // 直接从 EFI_SYSTEM_TABLE 获取输入接口
    i = grub_efi_system_table->con_in;
    
    // 直接调用 EFI 服务（函数调用，无需模式切换）
    status = i->read_key_stroke (i, &key);
    
    if (status != GRUB_EFI_SUCCESS)
        return GRUB_TERM_NO_KEY;
    
    return grub_efi_translate_key(key);
}
```

**关键差异：**
- **BIOS 模式**：需要调用 `grub_bios_interrupt()`，内部会切换到实模式
- **UEFI 模式**：直接调用 EFI 服务（`read_key_stroke()`），**无需模式切换**

**5. 磁盘访问的实现对比：**

**BIOS 模式**（`grub-core/disk/i386/pc/biosdisk.c`）：
```c
// 读取磁盘扇区
regs.eax = 0x4200;  // AH=0x42: Extended Read
regs.edx = drive;
// ... 设置其他寄存器
grub_bios_interrupt (0x13, &regs);  // 切换到实模式，调用 BIOS INT 13h
```

**UEFI 模式**（`grub-core/disk/efi/efidisk.c:542-607`）：
```c
static grub_efi_status_t
grub_efidisk_readwrite (struct grub_disk *disk, grub_disk_addr_t sector,
                        grub_size_t size, char *buf, int wr)
{
    struct grub_efidisk_data *d;
    grub_efi_block_io_t *bio;
    grub_efi_status_t status;
    
    d = disk->data;
    bio = d->block_io;  // 从 EFI 协议获取 Block I/O 接口
    
    // 直接调用 EFI Block I/O 服务（函数调用，无需模式切换）
    if (wr)
        status = bio->write_blocks (bio, bio->media->media_id, sector, 
                                     num_bytes, buf);
    else
        status = bio->read_blocks (bio, bio->media->media_id, sector, 
                                   num_bytes, buf);
    
    return status;
}
```

**关键差异：**
- **BIOS 模式**：需要调用 `grub_bios_interrupt (0x13, &regs)`，内部会切换到实模式
- **UEFI 模式**：直接调用 EFI Block I/O 协议的服务（`read_blocks()`/`write_blocks()`），**无需模式切换**

**6. 源代码验证：**

**验证 UEFI 模式不使用模式切换函数：**
```bash
# 在 UEFI 平台代码中搜索模式切换函数
$ grep -rn "real_to_prot\|prot_to_real\|grub_bios_interrupt" \
    grub-core/kern/i386/efi/ \
    grub-core/term/efi/ \
    grub-core/disk/efi/
# 结果：没有找到任何匹配
```

**验证 UEFI 模式使用 EFI 服务：**
```bash
# 在 UEFI 平台代码中搜索 EFI 服务调用
$ grep -rn "grub_efi_system_table\|EFI_SYSTEM_TABLE\|read_key_stroke\|read_blocks" \
    grub-core/term/efi/ \
    grub-core/disk/efi/
# 结果：找到大量 EFI 服务调用
```

**7. 平台特定的代码组织：**

**GRUB 的构建系统**（`grub-core/Makefile.core.def`）：
```def
kernel = {
  name = kernel;
  
  // BIOS 平台
  i386_pc_startup = kern/i386/pc/startup.S;
  
  // UEFI 平台
  i386_efi_startup = kern/i386/efi/startup.S;
  x86_64_efi_startup = kern/x86_64/efi/startup.S;
  
  // 平台特定的源文件
  i386_pc = kern/i386/pc/init.c;      // BIOS 初始化
  i386_efi = kern/i386/efi/init.c;    // UEFI 初始化
  
  // 平台特定的终端驱动
  i386_pc = term/i386/pc/console.c;   // BIOS 控制台（使用 INT 16h）
  efi = term/efi/console.c;          // UEFI 控制台（使用 EFI 服务）
  
  // 平台特定的磁盘驱动
  i386_pc = disk/i386/pc/biosdisk.c;  // BIOS 磁盘（使用 INT 13h）
  efi = disk/efi/efidisk.c;           // UEFI 磁盘（使用 EFI Block I/O）
}
```

**关键点：**
- **不同的平台使用不同的源文件**：`i386_pc` vs `i386_efi`
- **不同的服务接口**：BIOS 中断 vs EFI 服务
- **不同的实现方式**：模式切换 vs 直接函数调用

**8. 总结对比：**

| 特性 | BIOS 模式（i386_pc） | UEFI 模式（i386_efi/x86_64_efi） |
|------|---------------------|--------------------------------|
| **启动模式** | 实模式 → 保护模式（需要切换） | 保护模式/长模式（直接启动） |
| **模式切换函数** | `real_to_prot`、`prot_to_real` | **不需要** |
| **BIOS 中断调用** | `grub_bios_interrupt()` | **不使用** |
| **键盘输入** | `grub_bios_interrupt (0x16, &regs)` | `grub_efi_system_table->con_in->read_key_stroke()` |
| **磁盘访问** | `grub_bios_interrupt (0x13, &regs)` | `bio->read_blocks()` / `bio->write_blocks()` |
| **视频输出** | `grub_bios_interrupt (0x10, &regs)` | `grub_efi_system_table->con_out->output_string()` |
| **中断处理** | 禁用中断，需要时切换回实模式 | **不需要处理**（UEFI 已建立 IDT） |
| **代码复杂度** | 需要实现模式切换机制 | **更简单**（直接函数调用） |

**结论：**

- **你的理解完全正确**：UEFI 已经运行在保护模式/长模式下，所以不需要 `real_to_prot` 和 `prot_to_real` 的来回切换
- **GRUB 对 UEFI 有完全不同的支持**：
  - 使用不同的启动代码（`kern/i386/efi/startup.S`）
  - 使用不同的服务接口（EFI 服务而不是 BIOS 中断）
  - 使用不同的驱动实现（`term/efi/console.c`、`disk/efi/efidisk.c`）
- **UEFI 模式的优势**：
  - **更简单**：不需要模式切换，直接函数调用
  - **更安全**：UEFI 已建立完整的 IDT，可以处理中断
  - **更现代**：使用标准接口（EFI 协议），而不是硬件特定的中断
