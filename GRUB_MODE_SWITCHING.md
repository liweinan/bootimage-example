# GRUB 模式切换函数详解

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
