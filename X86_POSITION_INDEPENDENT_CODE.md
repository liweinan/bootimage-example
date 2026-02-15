# Linux 内核启动代码的 Position Independent Code（位置无关代码）机制

本文档深入分析 Linux 内核启动过程中 `__pi_` 前缀的含义、Position Independent Code（位置无关代码）的实现机制及其设计原理。

> **相关文档**：
> - 主流程：[LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md) - Linux 内核启动与初始化完整流程
> - IDT 初始化：[LINUX_KERNEL_INIT.md#IDT-表的演进流程](LINUX_KERNEL_INIT.md#idt-表的演进流程)
> - RIP 相对寻址：x86-64 架构使用 %rip 相对寻址实现位置无关

---

## 一、什么是 `__pi_` 前缀？

### 1. 基本概念

**`__pi_` = Position Independent（位置无关）**

在 Linux 内核启动代码中，你会看到类似这样的调用：

```asm
// arch/x86/kernel/head_64.S:74
call	__pi_startup_64_setup_gdt_idt
```

而实际的函数定义是：

```c
// arch/x86/boot/startup/gdt_idt.c:49
void __head startup_64_setup_gdt_idt(void)
{
    ...
}
```

**问题**：为什么调用 `__pi_startup_64_setup_gdt_idt`，而定义是 `startup_64_setup_gdt_idt`？

**答案**：`__pi_` 前缀是编译系统自动添加的，用于标识这是 **Position Independent Code（位置无关代码）**。

### 2. Position Independent Code（PIC）的定义

**位置无关代码**是指：
- 可以加载到内存的**任意地址**运行
- 不依赖于**绝对地址**
- 使用**相对寻址**（如 RIP 相对寻址）
- 不需要**重定位**就能正确执行

**对比**：

| 特性 | 位置相关代码 | 位置无关代码（PIC） |
|------|------------|------------------|
| **加载地址** | 必须是特定地址 | 任意地址 |
| **寻址方式** | 绝对地址 | 相对地址（RIP 相对） |
| **编译选项** | `-mcmodel=kernel` | `-fPIC -mcmodel=small` |
| **重定位** | 需要 | 不需要 |
| **典型用途** | 普通内核代码 | 启动代码、共享库 |

---

## 二、为什么内核启动需要 Position Independent Code？

### 1. 启动阶段的地址映射困境

**问题场景**：

```
【主内核的链接地址】
    └─ 虚拟地址：0xffffffff81000000（高地址映射）
       内核代码被链接到这个虚拟地址

【启动时的实际位置】
    ├─ 物理地址：0x1000000 (16MB)
    │   解压后的内核在这里
    └─ 当前映射：identity mapping（物理地址 = 虚拟地址）
       还没有切换到高地址映射

【冲突】
    ├─ 需要调用：startup_64_setup_gdt_idt()
    ├─ 函数链接地址：0xffffffff8xxxxxxx
    ├─ 当前可访问：0x0000000001000000
    └─ 问题：无法直接调用链接到虚拟地址的函数！
```

**时间线**：

```
1. 解压阶段（compressed kernel）
   ├─ 运行在：1MB 或 38MB（物理地址）
   ├─ 映射方式：identity mapping
   └─ 可以调用：压缩内核内的函数

2. 主内核 startup_64 开始
   ├─ 运行在：16MB（物理地址）
   ├─ 映射方式：identity mapping
   ├─ 链接地址：0xffffffff81000000
   └─ 问题：需要调用 startup_64_setup_gdt_idt，但它在高地址！

3. 切换到高地址映射后
   ├─ 运行在：0xffffffff81xxxxxx（虚拟地址）
   ├─ 映射方式：高地址映射
   └─ 可以调用：所有内核函数
```

### 2. 解决方案：Position Independent Code

**策略**：

1. **将启动代码编译为 PIC**：
   - 使用 `-fPIC` 选项
   - 代码使用相对寻址
   - 可以在任意地址运行

2. **添加 `__pi_` 前缀**：
   - 区分 PI 代码和普通代码
   - 强制隔离（启动代码只能调用启动代码）
   - 防止误调用未初始化的内核函数

3. **使用 RIP 相对寻址**：
   - x86-64 架构的特性
   - `leaq symbol(%rip), %rax`
   - 相对于当前指令的偏移

---

## 三、实现机制详解

### 1. 编译系统配置

**Makefile**（`arch/x86/boot/startup/Makefile`）：

```makefile
# 第 4 行：关键编译选项
KBUILD_CFLAGS += -D__DISABLE_EXPORTS -mcmodel=small -fPIC \
                 -Os -DDISABLE_BRANCH_PROFILING \
                 $(DISABLE_STACKLEAK_PLUGIN) \
                 $(DISABLE_LATENT_ENTROPY_PLUGIN) \
                 -fno-stack-protector -D__NO_FORTIFY \
                 -fno-jump-tables \
                 -include $(srctree)/include/linux/hidden.h

# 第 12-19 行：禁用所有 instrumentation
KBUILD_CFLAGS := $(subst $(CC_FLAGS_FTRACE),,$(KBUILD_CFLAGS))
KBUILD_CFLAGS := $(filter-out $(CC_FLAGS_LTO),$(KBUILD_CFLAGS))
KASAN_SANITIZE := n
KCSAN_SANITIZE := n
KMSAN_SANITIZE := n
UBSAN_SANITIZE := n
KCOV_INSTRUMENT := n

# 第 21-23 行：定义 PI 对象
obj-$(CONFIG_X86_64)     += gdt_idt.o map_kernel.o
obj-$(CONFIG_AMD_MEM_ENCRYPT) += sme.o sev-startup.o
pi-objs := $(patsubst %.o,$(obj)/%.o,$(obj-y))

# 第 42-49 行：符号前缀处理（核心机制）
#
# Confine the startup code by prefixing all symbols with __pi_ (for position
# independent). This ensures that startup code can only call other startup
# code, or code that has explicitly been made accessible to it via a symbol
# alias.
#
$(obj)/%.pi.o: OBJCOPYFLAGS := --prefix-symbols=__pi_
$(obj)/%.pi.o: $(obj)/%.o FORCE
	$(call if_changed,objcopy)

targets += $(obj-y)
obj-y := $(patsubst %.o,%.pi.o,$(obj-y))
```

**关键编译选项说明**：

| 选项 | 作用 |
|------|------|
| `-fPIC` | 生成位置无关代码（Position Independent Code） |
| `-mcmodel=small` | 小内存模型（代码+数据 < 2GB），适合相对寻址 |
| `-D__DISABLE_EXPORTS` | 禁用符号导出 |
| `-Os` | 优化代码大小（启动代码要小） |
| `-DDISABLE_BRANCH_PROFILING` | 禁用分支性能分析 |
| `-fno-stack-protector` | 禁用栈保护（栈保护需要 GS 段，但此时未初始化） |
| `-fno-jump-tables` | 禁用跳转表（避免绝对地址） |
| `KASAN_SANITIZE := n` | 禁用 KASAN（地址消毒器） |
| `KBUILD_CFLAGS := $(subst $(CC_FLAGS_FTRACE),,...)` | 移除 ftrace 标志 |

### 2. 符号前缀处理流程

**编译和链接流程**：

```
1. 源文件编译（使用 -fPIC）
   gdt_idt.c → gdt_idt.o

   符号：startup_64_setup_gdt_idt
   代码：使用 RIP 相对寻址

2. objcopy 处理（添加 __pi_ 前缀）
   gdt_idt.o → gdt_idt.pi.o

   命令：objcopy --prefix-symbols=__pi_ gdt_idt.o gdt_idt.pi.o

   结果：
   - startup_64_setup_gdt_idt → __pi_startup_64_setup_gdt_idt
   - startup_64_load_idt → __pi_startup_64_load_idt
   - bringup_idt_table → __pi_bringup_idt_table

3. 链接到内核
   gdt_idt.pi.o → vmlinux

   符号表中包含：
   - __pi_startup_64_setup_gdt_idt（地址：相对于 vmlinux）
```

**objcopy 命令效果示例**：

```bash
# 查看原始符号
$ nm gdt_idt.o
0000000000000000 T startup_64_setup_gdt_idt
0000000000000040 T startup_64_load_idt
0000000000000000 B bringup_idt_table

# objcopy 添加前缀
$ objcopy --prefix-symbols=__pi_ gdt_idt.o gdt_idt.pi.o

# 查看处理后的符号
$ nm gdt_idt.pi.o
0000000000000000 T __pi_startup_64_setup_gdt_idt
0000000000000040 T __pi_startup_64_load_idt
0000000000000000 B __pi_bringup_idt_table
```

### 3. SYM_PIC_ALIAS 宏机制

**宏定义**（`arch/x86/include/asm/linkage.h:144-152`）：

```c
/*
 * Expose 'sym' to the startup code in arch/x86/boot/startup/, by emitting an
 * alias prefixed with __pi_
 */
#ifdef __ASSEMBLER__
#define SYM_PIC_ALIAS(sym)	SYM_ALIAS(__pi_ ## sym, sym, SYM_L_GLOBAL)
#else
#define SYM_PIC_ALIAS(sym)	extern typeof(sym) __PASTE(__pi_, sym) __alias(sym)
#endif
```

**作用**：为主内核中的符号创建 `__pi_` 别名，让 PI 代码可以访问。

**使用示例**：

```c
// arch/x86/kernel/head64.c
unsigned int __pgtable_l5_enabled __ro_after_init;
SYM_PIC_ALIAS(__pgtable_l5_enabled);

unsigned int pgdir_shift __ro_after_init = 39;
SYM_PIC_ALIAS(pgdir_shift);

unsigned int ptrs_per_p4d __ro_after_init = 1;
SYM_PIC_ALIAS(ptrs_per_p4d);
```

**编译后的符号表**：

```
原始符号：
    __pgtable_l5_enabled  @ 0xffffffff82345678

通过 SYM_PIC_ALIAS 生成的别名：
    __pi___pgtable_l5_enabled = __pgtable_l5_enabled

效果：
    PI 代码可以通过 __pi___pgtable_l5_enabled 访问
    普通代码可以通过 __pgtable_l5_enabled 访问
    两者指向同一个内存位置
```

**汇编展开**（`SYM_ALIAS` 的实现）：

```asm
.globl __pi___pgtable_l5_enabled
.set __pi___pgtable_l5_enabled, __pgtable_l5_enabled
```

---

## 四、RIP 相对寻址详解

### 1. x86-64 的 RIP 相对寻址

**RIP 寄存器**：
- RIP = Instruction Pointer（指令指针，x86-64 的 PC）
- 始终指向**下一条**要执行的指令
- x86-64 支持 RIP 相对寻址模式

**寻址格式**：

```asm
leaq    symbol(%rip), %rax      # %rax = RIP + offset_to_symbol
movq    symbol(%rip), %rax      # %rax = *(RIP + offset_to_symbol)
```

**示例**：

```asm
# 假设当前指令地址：0x1000
# symbol 的地址：0x1100
# offset = 0x1100 - (0x1000 + instruction_length)

leaq    symbol(%rip), %rax
# 实际计算：%rax = 当前 RIP + offset
# 结果：%rax = 0x1100（symbol 的地址）
```

**优势**：
- 只需要知道相对偏移，不需要绝对地址
- 代码可以加载到任意位置运行
- 无需运行时重定位

### 2. rip_rel_ptr() 宏

**定义**（`arch/x86/include/asm/init.h`）：

```c
#define rip_rel_ptr(var) \
({ \
    unsigned long __ptr = (unsigned long)&(var); \
    asm("leaq %c1(%%rip), %0" : "=r"(__ptr) : "i"(__ptr)); \
    (typeof(&(var)))__ptr; \
})
```

**作用**：在编译时常量的基础上，使用 RIP 相对寻址获取变量的运行时地址。

**使用示例**：

```c
// arch/x86/boot/startup/gdt_idt.c:27-32
void startup_64_load_idt(void *vc_handler)
{
    struct desc_ptr desc = {
        .address = (unsigned long)rip_rel_ptr(bringup_idt_table),
        .size    = sizeof(bringup_idt_table) - 1,
    };
    ...
}
```

**宏展开过程**：

```c
// 源代码
rip_rel_ptr(bringup_idt_table)

// 展开后
({
    unsigned long __ptr = (unsigned long)&(bringup_idt_table);  // 编译时地址
    asm("leaq %c1(%%rip), %0" : "=r"(__ptr) : "i"(__ptr));      // 运行时计算
    (typeof(&(bringup_idt_table)))__ptr;
})
```

**生成的汇编**：

```asm
# 假设 bringup_idt_table 编译时地址是 0x12345678
leaq    0x12345678(%rip), %rax    # %rax = 运行时的 bringup_idt_table 地址
```

**为什么这样工作？**
1. 编译时：`&bringup_idt_table` 是一个编译时常量（假设 0x12345678）
2. 编译器：生成 `leaq 0x12345678(%rip), %rax`
3. 汇编器：计算相对偏移 `offset = 0x12345678 - (current_rip + instruction_length)`
4. 运行时：`%rax = current_rip + offset`，得到实际的运行时地址

### 3. -fPIC 生成的代码对比

**示例代码**：

```c
extern int global_var;

void set_var(void) {
    global_var = 42;
}
```

**非 PIC 编译**（`gcc -mcmodel=kernel`）：

```asm
set_var:
    movl    $42, global_var(%rip)    # 直接使用全局符号
    ret
```

**PIC 编译**（`gcc -fPIC -mcmodel=small`）：

```asm
set_var:
    movq    global_var@GOTPCREL(%rip), %rax    # 通过 GOT（Global Offset Table）
    movl    $42, (%rax)
    ret
```

**区别**：
- 非 PIC：直接使用符号的 RIP 相对地址
- PIC：通过 GOT 间接访问（但内核启动代码很简单，通常直接 RIP 相对就够了）

---

## 五、完整调用流程示例

### 1. 汇编调用 C 函数

**调用点**（`arch/x86/kernel/head_64.S:74`）：

```asm
SYM_CODE_START(startup_64)
    ...
    # 设置 GS_BASE
    movl    $MSR_GS_BASE, %ecx
    movl    %edx, %eax
    movl    %ebx, %edx
    wrmsr

    # 调用 PI 函数设置 GDT 和 IDT
    call    __pi_startup_64_setup_gdt_idt    # ← 这里调用

    # 切换到 __KERNEL_CS
    pushq   $__KERNEL_CS
    leaq    1f(%rip), %rax
    pushq   %rax
    lretq
1:
    ...
SYM_CODE_END(startup_64)
```

**符号解析**：

```
链接时：
    ├─ call __pi_startup_64_setup_gdt_idt
    ├─ 查找符号：__pi_startup_64_setup_gdt_idt
    ├─ 找到：gdt_idt.pi.o 中的符号
    └─ 计算偏移：offset = target - (current_rip + 5)
       （call 指令长度 = 5 字节）

运行时：
    ├─ 执行 call 指令
    ├─ RIP = current_rip + offset
    └─ 跳转到 __pi_startup_64_setup_gdt_idt
```

### 2. C 函数实现

**函数定义**（`arch/x86/boot/startup/gdt_idt.c:49`）：

```c
void __head startup_64_setup_gdt_idt(void)
{
    struct gdt_page *gp = rip_rel_ptr((void *)(__force unsigned long)&gdt_page);
    void *handler = NULL;

    struct desc_ptr startup_gdt_descr = {
        .address = (unsigned long)gp->gdt,
        .size    = GDT_SIZE - 1,
    };

    /* Load GDT */
    native_load_gdt(&startup_gdt_descr);

    /* New GDT is live - reload data segment registers */
    asm volatile("movl %%eax, %%ds\n"
                 "movl %%eax, %%ss\n"
                 "movl %%eax, %%es\n" : : "a"(__KERNEL_DS) : "memory");

    if (IS_ENABLED(CONFIG_AMD_MEM_ENCRYPT))
        handler = rip_rel_ptr(vc_no_ghcb);

    startup_64_load_idt(handler);
}
```

**编译后的符号**：
- 源代码中：`startup_64_setup_gdt_idt`
- objcopy 后：`__pi_startup_64_setup_gdt_idt`

### 3. 访问全局变量

**示例**（访问 `gdt_page`）：

```c
// arch/x86/kernel/cpu/common.c
DEFINE_PER_CPU_PAGE_ALIGNED(struct gdt_page, gdt_page) = { .gdt = {
    ...
} };
SYM_PIC_ALIAS(gdt_page);    // 创建 __pi_gdt_page 别名
```

**PI 代码访问**：

```c
// arch/x86/boot/startup/gdt_idt.c
struct gdt_page *gp = rip_rel_ptr((void *)&gdt_page);
```

**展开过程**：

```c
// 1. 宏展开
rip_rel_ptr((void *)&gdt_page)
↓
({
    unsigned long __ptr = (unsigned long)&gdt_page;
    asm("leaq %c1(%%rip), %0" : "=r"(__ptr) : "i"(__ptr));
    (struct gdt_page *)__ptr;
})

// 2. 编译时
&gdt_page 被解析为 __pi_gdt_page（因为在 PI 代码中）

// 3. 生成汇编
leaq    __pi_gdt_page(%rip), %rax    # 使用 RIP 相对寻址
```

### 4. 内存布局示例

**假设运行时地址**：

```
16MB (0x1000000) ──┬─── startup_64 代码段
                   │    0x1000000: startup_64 入口
                   │    0x1000100: call __pi_startup_64_setup_gdt_idt
                   │
                   ├─── __pi_startup_64_setup_gdt_idt
                   │    0x1000200: 函数入口
                   │    0x1000220: leaq __pi_gdt_page(%rip), %rax
                   │
                   ├─── __pi_bringup_idt_table
                   │    0x1001000: IDT 表（32 个条目）
                   │
                   └─── __pi_gdt_page
                        0x1002000: GDT 表
```

**RIP 相对寻址计算**：

```asm
# 当前指令：0x1000220
leaq    __pi_gdt_page(%rip), %rax

# __pi_gdt_page 地址：0x1002000
# RIP（执行此指令时）：0x1000220 + 指令长度(7) = 0x1000227
# offset = 0x1002000 - 0x1000227 = 0x1DD9

# 实际生成的指令编码：
# 48 8D 05 D9 1D 00 00    leaq 0x1dd9(%rip), %rax

# 运行时计算：
# %rax = RIP + 0x1DD9 = 0x1000227 + 0x1DD9 = 0x1002000 ✓
```

---

## 六、为什么这样设计？

### 1. 地址映射转换问题

**启动阶段的地址映射变化**：

```
阶段 1：压缩内核阶段
    ├─ 物理地址：1MB 或 38MB
    ├─ 虚拟地址：identity mapping（虚拟 = 物理）
    └─ 代码：完全独立，不需要访问主内核

阶段 2：主内核 startup_64（切换前）
    ├─ 物理地址：16MB
    ├─ 虚拟地址：identity mapping
    ├─ 链接地址：0xffffffff81000000（高地址）
    └─ 问题：需要调用函数，但链接到高地址！← 这里需要 PI 代码

阶段 3：切换到高地址映射后
    ├─ 物理地址：16MB
    ├─ 虚拟地址：0xffffffff81000000
    ├─ 链接地址：0xffffffff81000000
    └─ 问题解决：虚拟地址 = 链接地址，可以正常调用
```

**如果没有 PI 代码会怎样？**

```c
// 假设直接调用（非 PI）
call startup_64_setup_gdt_idt

// 链接时：
// startup_64_setup_gdt_idt @ 0xffffffff81234567

// 运行时（切换前）：
// 当前运行在物理地址 16MB（虚拟地址也是 16MB，identity mapping）
// call 指令尝试跳转到 0xffffffff81234567
// 但这个地址还没有映射！
// 结果：#PF（Page Fault）或 Triple Fault → 系统崩溃
```

### 2. 代码隔离和安全性

**符号前缀的强制隔离**：

```
启动代码（__pi_ 前缀）：
    ├─ 只能调用其他 __pi_ 函数
    ├─ 只能访问有 SYM_PIC_ALIAS 的全局变量
    └─ 防止误调用未初始化的内核函数

普通内核代码（无前缀）：
    ├─ 可以调用任何内核函数
    ├─ 可以访问任何全局变量
    └─ 但不能在启动早期使用
```

**如果误调用会怎样？**

```c
// arch/x86/boot/startup/gdt_idt.c（PI 代码）
void startup_64_setup_gdt_idt(void)
{
    // 假设误调用了普通内核函数
    some_kernel_function();    // ← 链接错误！
    // 链接器会报错：undefined reference to '__pi_some_kernel_function'
}
```

**好处**：
- 编译时检查：链接器会强制检查
- 防止未初始化访问：避免访问未初始化的数据结构
- 清晰的边界：明确哪些代码是启动代码

### 3. 支持 KASLR（内核地址空间布局随机化）

**KASLR 的需求**：
- 内核加载地址随机化（安全特性）
- 解压目标地址不固定
- 代码必须能在任意地址运行

**PI 代码天然支持 KASLR**：
- 无论加载到哪里，RIP 相对寻址都能正确工作
- 不需要运行时重定位
- 性能开销最小

### 4. 避免 instrumentation 干扰

**启动代码的特殊要求**：

```makefile
# arch/x86/boot/startup/Makefile

# 禁用所有 instrumentation
KASAN_SANITIZE := n        # 地址消毒器
KCSAN_SANITIZE := n        # 并发消毒器
KMSAN_SANITIZE := n        # 内存消毒器
UBSAN_SANITIZE := n        # 未定义行为消毒器
KCOV_INSTRUMENT := n       # 代码覆盖率

# 移除 ftrace 和 LTO
KBUILD_CFLAGS := $(subst $(CC_FLAGS_FTRACE),,$(KBUILD_CFLAGS))
KBUILD_CFLAGS := $(filter-out $(CC_FLAGS_LTO),$(KBUILD_CFLAGS))
```

**原因**：
- KASAN/KCSAN 等工具需要运行时支持
- ftrace 需要完整的内核基础设施
- LTO 可能改变代码布局
- 启动阶段这些都不可用

---

## 七、与其他架构的对比

### 1. x86-64 的优势

**x86-64 RIP 相对寻址**：
- 硬件直接支持
- 性能开销小
- 代码生成简单

**示例**：

```asm
# x86-64: 一条指令
leaq    symbol(%rip), %rax

# 其他架构（如 ARM）：需要多条指令
adrp    x0, symbol          # 获取页地址
add     x0, x0, :lo12:symbol # 加上页内偏移
```

### 2. 其他架构的实现

**ARM64**：

```asm
# Position Independent Code
adrp    x0, global_var           # 获取全局变量的页地址
ldr     w1, [x0, :lo12:global_var] # 加载数据
```

**RISC-V**：

```asm
# Position Independent Code
auipc   a0, %pcrel_hi(global_var)  # PC 相对高 20 位
addi    a0, a0, %pcrel_lo(global_var) # PC 相对低 12 位
```

---

## 八、实际代码分析

### 1. startup_64_setup_gdt_idt 完整流程

**源代码**（`arch/x86/boot/startup/gdt_idt.c:49-71`）：

```c
void __head startup_64_setup_gdt_idt(void)
{
    // 1. 使用 rip_rel_ptr 获取 gdt_page 的运行时地址
    struct gdt_page *gp = rip_rel_ptr((void *)(__force unsigned long)&gdt_page);
    void *handler = NULL;

    struct desc_ptr startup_gdt_descr = {
        .address = (unsigned long)gp->gdt,
        .size    = GDT_SIZE - 1,
    };

    /* Load GDT */
    native_load_gdt(&startup_gdt_descr);    // 2. 加载 GDT

    /* New GDT is live - reload data segment registers */
    asm volatile("movl %%eax, %%ds\n"       // 3. 重载段寄存器
                 "movl %%eax, %%ss\n"
                 "movl %%eax, %%es\n" : : "a"(__KERNEL_DS) : "memory");

    // 4. 如果启用 AMD SEV，获取 vc_no_ghcb 的地址
    if (IS_ENABLED(CONFIG_AMD_MEM_ENCRYPT))
        handler = rip_rel_ptr(vc_no_ghcb);

    // 5. 调用 startup_64_load_idt（也是 PI 代码）
    startup_64_load_idt(handler);
}
```

**编译后的汇编**（简化）：

```asm
__pi_startup_64_setup_gdt_idt:
    # 1. 获取 gdt_page 地址（RIP 相对）
    leaq    __pi_gdt_page(%rip), %rax

    # 2. 填充 desc_ptr
    movq    %rax, -0x10(%rsp)        # .address
    movl    $0x7f, -0x18(%rsp)       # .size = GDT_SIZE - 1

    # 3. lgdt
    leaq    -0x18(%rsp), %rax
    lgdt    (%rax)

    # 4. 重载段寄存器
    movl    $0x10, %eax              # __KERNEL_DS
    movl    %eax, %ds
    movl    %eax, %ss
    movl    %eax, %es

    # 5. 获取 vc_no_ghcb 地址（如果需要）
    leaq    __pi_vc_no_ghcb(%rip), %rdi

    # 6. 调用 startup_64_load_idt（RIP 相对）
    call    __pi_startup_64_load_idt

    ret
```

### 2. startup_64_load_idt 完整流程

**源代码**（`arch/x86/boot/startup/gdt_idt.c:27-44`）：

```c
void startup_64_load_idt(void *vc_handler)
{
    struct desc_ptr desc = {
        .address = (unsigned long)rip_rel_ptr(bringup_idt_table),
        .size    = sizeof(bringup_idt_table) - 1,
    };
    struct idt_data data;
    gate_desc idt_desc;

    /* @vc_handler is set only for a VMM Communication Exception */
    if (vc_handler) {
        init_idt_data(&data, X86_TRAP_VC, vc_handler);
        idt_init_desc(&idt_desc, &data);
        native_write_idt_entry((gate_desc *)desc.address, X86_TRAP_VC, &idt_desc);
    }

    native_load_idt(&desc);
}
```

**RIP 相对寻址的使用**：

```c
// 获取 bringup_idt_table 的运行时地址
.address = (unsigned long)rip_rel_ptr(bringup_idt_table)

// 展开后的汇编：
leaq    __pi_bringup_idt_table(%rip), %rax
```

### 3. 符号别名的实际例子

**定义别名**（`arch/x86/kernel/head64.c`）：

```c
unsigned int __pgtable_l5_enabled __ro_after_init;
SYM_PIC_ALIAS(__pgtable_l5_enabled);
```

**使用别名**（启动代码访问）：

```c
// 某个 PI 函数中
if (__pgtable_l5_enabled) {    // 编译器看到这个符号
    // 在 PI 代码中，这会被解析为 __pi___pgtable_l5_enabled
    ...
}
```

**符号表**：

```bash
$ nm vmlinux | grep pgtable_l5_enabled
ffffffff82345678 B __pgtable_l5_enabled
ffffffff82345678 B __pi___pgtable_l5_enabled
```

---

## 九、调试和验证

### 1. 查看符号表

**检查 PI 符号**：

```bash
# 查看 PI 对象文件的符号
$ nm arch/x86/boot/startup/gdt_idt.pi.o
0000000000000000 T __pi_startup_64_setup_gdt_idt
0000000000000040 T __pi_startup_64_load_idt
0000000000000000 B __pi_bringup_idt_table

# 查看完整内核的符号
$ nm vmlinux | grep __pi_
ffffffff81000200 T __pi_startup_64_setup_gdt_idt
ffffffff81000240 T __pi_startup_64_load_idt
ffffffff81001000 B __pi_bringup_idt_table
ffffffff82345678 B __pi___pgtable_l5_enabled
...
```

### 2. 反汇编验证

**查看生成的代码**：

```bash
# 反汇编 PI 函数
$ objdump -d arch/x86/boot/startup/gdt_idt.pi.o

0000000000000000 <__pi_startup_64_setup_gdt_idt>:
   0:   48 8d 05 00 00 00 00    leaq   0x0(%rip),%rax  # 需要重定位
   7:   48 89 44 24 f0          movq   %rax,-0x10(%rsp)
   c:   c7 44 24 e8 7f 00 00 00 movl   $0x7f,-0x18(%rsp)
  ...
```

**查看重定位记录**：

```bash
$ readelf -r arch/x86/boot/startup/gdt_idt.pi.o

Relocation section '.rela.text' at offset 0x... contains X entries:
  Offset          Type                 Sym. Name + Addend
000000000003  R_X86_64_PC32         __pi_gdt_page - 4
00000000001a  R_X86_64_PC32         __pi_vc_no_ghcb - 4
...
```

### 3. 运行时验证

**添加调试输出**：

```c
void startup_64_setup_gdt_idt(void)
{
    struct gdt_page *gp = rip_rel_ptr((void *)&gdt_page);

    // 早期启动无法用 printk，但可以用串口
    // early_printk("gdt_page @ %p\n", gp);

    ...
}
```

---

## 十、总结

### 1. 核心设计原理

**Position Independent Code 机制**：

| 方面 | 实现方式 | 目的 |
|------|---------|------|
| **编译** | `-fPIC -mcmodel=small` | 生成位置无关代码 |
| **符号** | `objcopy --prefix-symbols=__pi_` | 添加前缀，强制隔离 |
| **寻址** | RIP 相对寻址 | 访问数据使用相对偏移 |
| **别名** | `SYM_PIC_ALIAS` 宏 | 暴露主内核符号给 PI 代码 |
| **隔离** | 禁用 instrumentation | 避免未初始化的依赖 |

### 2. 为什么需要 PI 代码？

1. **地址映射转换**：启动时运行在物理地址，链接在虚拟地址
2. **KASLR 支持**：内核地址随机化要求代码位置无关
3. **代码隔离**：防止误调用未初始化的内核函数
4. **安全性**：避免 instrumentation 在早期阶段的干扰

### 3. 关键技术点

**RIP 相对寻址**：
- x86-64 硬件支持
- `leaq symbol(%rip), %rax`
- 相对于当前指令的偏移

**符号前缀机制**：
- `objcopy --prefix-symbols=__pi_`
- 编译时强制隔离
- 链接器检查依赖

**rip_rel_ptr 宏**：
- 编译时常量 + 运行时 RIP 相对
- 无需运行时重定位
- 性能开销最小

### 4. 适用范围

**只在启动早期使用**：

```
使用 PI 代码（__pi_）：
    ├─ arch/x86/kernel/head_64.S（startup_64 汇编代码）
    ├─ arch/x86/boot/startup/*.c（C 启动代码）
    └─ 直到切换到高地址映射

不使用 PI 代码：
    ├─ x86_64_start_kernel() 开始
    ├─ start_kernel() 及之后
    └─ 所有普通内核代码
```

**切换点**：

```asm
// arch/x86/kernel/head_64.S
startup_64:
    ...
    call    __pi_startup_64_setup_gdt_idt    # ← 最后一次使用 PI 代码

    # 切换到高地址映射
    pushq   $__KERNEL_CS
    leaq    1f(%rip), %rax
    pushq   %rax
    lretq
1:
    # 从这里开始，运行在虚拟地址空间
    # 可以直接调用普通内核函数（无需 __pi_ 前缀）
    ...
    call    x86_64_start_kernel              # ← 普通函数调用
```

---

## 参考资料

### Linux 内核源代码

- `arch/x86/boot/startup/` - https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/arch/x86/boot/startup
- `arch/x86/include/asm/linkage.h` - https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/arch/x86/include/asm/linkage.h
- `arch/x86/include/asm/init.h` - https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/arch/x86/include/asm/init.h

### ABI 规范文档

- **System V ABI - AMD64 Architecture Processor Supplement**
  - **在线版本**：https://refspecs.linuxfoundation.org/elf/x86_64-abi-0.99.pdf
  - **本地副本**：`reference-docs/x86_64-abi-0.99.pdf`
  - **相关章节**：
    - 第 3.2 节：函数调用序列（寄存器使用、参数传递）
    - 第 3.5 节：程序加载（Position Independent Code）
    - 第 3.6 节：RIP-relative addressing（PC 相对寻址）
  - **说明**：x86-64 ABI 定义了 RIP-relative addressing 的规范用法，这是实现位置无关代码的核心机制

### 相关文档

- Linux 内核文档：Position Independent Executables (PIE)
- [Linux 内核启动与初始化](LINUX_KERNEL_INIT.md) - 详细流程分析
- [Linux 内核函数修饰符与调用约定](LINUX_KERNEL_FUNCTION_ATTRIBUTES.md) - 调用约定与 ABI 规范详解
