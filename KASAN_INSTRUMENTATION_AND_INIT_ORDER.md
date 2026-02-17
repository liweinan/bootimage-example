# KASAN 插桩机制与初始化顺序深度分析

**版本**: 1.0
**日期**: 2026-02-17
**作者**: Linux 内核启动文档项目

> 📚 **文档导航**: [返回总索引](DOCUMENT_INDEX.md) | [阅读指南](READING_GUIDE.md) | [IDT 演进](LINUX_KERNEL_IDT_EVOLUTION.md) | [内核启动](LINUX_KERNEL_INIT.md)

---

## 目录

1. [问题的核心：为什么必须先初始化 KASAN？](#1-问题的核心为什么必须先初始化-kasan)
2. [编译时插桩 vs 运行时初始化](#2-编译时插桩-vs-运行时初始化)
3. [KASAN 插桩机制详解](#3-kasan-插桩机制详解)
4. [如果 KASAN 未初始化会发生什么？](#4-如果-kasan-未初始化会发生什么)
5. [内核源代码证据](#5-内核源代码证据)
6. [为什么不让 KASAN 自动跳过检查？](#6-为什么不让-kasan-自动跳过检查)
7. [启动顺序的强制约束](#7-启动顺序的强制约束)
8. [__head 和 KASAN_SANITIZE 的作用](#8-__head-和-kasan_sanitize-的作用)
9. [总结与设计原则](#9-总结与设计原则)

---

## 1. 问题的核心：为什么必须先初始化 KASAN？

### 1.1 表面现象

在 `x86_64_start_kernel()` 中，**初始化顺序**是这样的（`arch/x86/kernel/head64.c:219-289`）：

```c
asmlinkage __visible void __init __noreturn x86_64_start_kernel(char *real_mode_data)
{
    // ... 前置步骤 ...

    kasan_early_init();              // ← 第 1 步：KASAN 初始化（行 261）

    // 注释说明：必须在 KASAN 初始化之后！
    __native_tlb_flush_global(...);  // ← 第 2 步：刷新 TLB（行 271）

    idt_setup_early_handler();       // ← 第 3 步：设置 IDT（行 273）
}
```

**关键注释**（`head64.c:263-270`）：

```c
/*
 * Flush global TLB entries which could be left over from the trampoline page
 * table.
 *
 * This needs to happen *after* kasan_early_init() as KASAN-enabled .configs
 * instrument native_write_cr4() so KASAN must be initialized for that
 * instrumentation to work.
 */
__native_tlb_flush_global(this_cpu_read(cpu_tlbstate.cr4));
```

### 1.2 核心困惑

你可能会问：

> **"如果 KASAN 还没初始化，它应该是'关闭'状态，为什么函数里的内存访问还会被插桩？"**

这是一个**非常精准**的问题，触及了问题的核心。答案在于：

**插桩（instrumentation）是编译时决定的，不是运行时决定的。**

---

## 2. 编译时插桩 vs 运行时初始化

### 2.1 什么是 KASAN 插桩？

**KASAN** (Kernel Address Sanitizer) 是一个**内存错误检测工具**，用于发现：
- 内存越界访问（buffer overflow）
- Use-after-free（访问已释放的内存）
- Use-after-scope（访问已失效的局部变量）
- 双重释放（double free）

**工作原理**：
1. **影子内存**（Shadow Memory）：为每 8 字节内存维护 1 字节的"影子"状态
2. **编译时插桩**：在**每次内存访问**前后插入检查代码
3. **运行时检查**：访问影子内存，判断目标地址是否合法

### 2.2 编译时插桩：代码转换

当你配置内核时启用 `CONFIG_KASAN=y`，编译器（GCC/Clang）会在**编译阶段**自动插入检查代码。

**原始 C 代码**：

```c
void foo(int *ptr) {
    *ptr = 42;  // 简单的内存写入
}
```

**KASAN 启用后的等效代码**（编译器自动生成）：

```c
void foo(int *ptr) {
    __asan_store4(ptr);  // ← 编译器自动插入的检查函数
    *ptr = 42;           // 原始的内存写入
}
```

**关键点**：
- ✅ 插桩代码**永久性地存在于目标文件**（.o 文件）中
- ✅ 这是**编译时决定**的，不是运行时决定的
- ❌ 无法在运行时"开关" KASAN 插桩（代码已经生成了）

### 2.3 运行时初始化：影子内存准备

**`kasan_early_init()` 的作用**（`arch/x86/mm/kasan_init_64.c:287-322`）：

```c
void __init kasan_early_init(void)
{
    int i;
    pteval_t pte_val = __pa_nodebug(kasan_early_shadow_page) |
                __PAGE_KERNEL | _PAGE_ENC;
    pmdval_t pmd_val = __pa_nodebug(kasan_early_shadow_pte) | _KERNPG_TABLE;
    pudval_t pud_val = __pa_nodebug(kasan_early_shadow_pmd) | _KERNPG_TABLE;
    p4dval_t p4d_val = __pa_nodebug(kasan_early_shadow_pud) | _KERNPG_TABLE;

    /* Mask out unsupported __PAGE_KERNEL bits */
    pte_val &= __default_kernel_pte_mask;

    /* 设置早期影子内存的页表映射 */
    for (i = 0; i < PTRS_PER_PTE; i++)
        kasan_early_shadow_pte[i] = __pte(pte_val);

    for (i = 0; i < PTRS_PER_PMD; i++)
        kasan_early_shadow_pmd[i] = __pmd(pmd_val);

    for (i = 0; i < PTRS_PER_PUD; i++)
        kasan_early_shadow_pud[i] = __pud(pud_val);

    /* 建立 KASAN 影子内存区域的映射 */
    kasan_map_early_shadow(early_top_pgt);
    kasan_map_early_shadow(init_top_pgt);
}
```

**关键工作**：
1. **建立影子内存的页表映射**（否则访问影子内存会触发 Page Fault）
2. **初始化影子页表**（PTE/PMD/PUD）
3. **映射到顶级页表**（early_top_pgt、init_top_pgt）

### 2.4 时间线对比

```
┌───────────────────────────────────────────────────────────────┐
│  编译时（内核构建阶段）                                        │
├───────────────────────────────────────────────────────────────┤
│                                                                │
│  1. GCC/Clang 编译 idt.c                                      │
│     ├─ CONFIG_KASAN=y 被检测到                                │
│     ├─ 编译器在每次内存访问前插入 __asan_loadXX/storeXX     │
│     └─ 生成 idt.o（已包含插桩代码）                           │
│                                                                │
│  2. 链接器生成 vmlinux                                         │
│     └─ idt.o 中的插桩代码被链接到内核镜像                    │
│                                                                │
└───────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────┐
│  运行时（内核启动阶段）                                        │
├───────────────────────────────────────────────────────────────┤
│                                                                │
│  时刻 T0: startup_64                                           │
│           └─ 加载 bringup_idt_table                           │
│                                                                │
│  时刻 T1: x86_64_start_kernel() 开始                           │
│           ├─ 此时 idt.c 中的代码已经在内存中                 │
│           ├─ 代码中的 __asan_storeXX 指令也在内存中          │
│           └─ 但影子内存还没准备好！❌                         │
│                                                                │
│  时刻 T2: kasan_early_init()                                   │
│           ├─ 建立影子内存页表映射                             │
│           ├─ 初始化影子内存区域                               │
│           └─ 现在可以安全执行插桩代码 ✅                      │
│                                                                │
│  时刻 T3: __native_tlb_flush_global()                          │
│           ├─ 调用 native_write_cr4()                          │
│           ├─ 函数被 KASAN 插桩（编译时决定）                 │
│           ├─ __asan_storeXX 访问影子内存                     │
│           └─ 成功（因为 T2 已经初始化）✅                     │
│                                                                │
│  时刻 T4: idt_setup_early_handler()                            │
│           ├─ 调用 idt.c 中的函数                             │
│           ├─ 函数被 KASAN 插桩                                │
│           └─ 成功（因为 T2 已经初始化）✅                     │
│                                                                │
└───────────────────────────────────────────────────────────────┘
```

**关键结论**：
- 无论 KASAN 是否初始化，**插桩代码都会执行**（因为是编译时决定的）
- 如果在 T2 之前执行插桩代码 → **崩溃**
- 如果在 T2 之后执行插桩代码 → **正常工作**

---

## 3. KASAN 插桩机制详解

### 3.1 插桩函数：__asan_loadXX 和 __asan_storeXX

**编译器插入的函数**（`mm/kasan/generic.c`）：

```c
// 检查 1 字节读取
void __asan_load1(const void *addr)
{
    if (!check_region_inline(addr, 1, false, _RET_IP_))
        kasan_report(addr, 1, false, _RET_IP_);
}

// 检查 4 字节写入
void __asan_store4(const void *addr)
{
    if (!check_region_inline(addr, 4, true, _RET_IP_))
        kasan_report(addr, 4, true, _RET_IP_);
}

// 类似的函数：
// __asan_load2, __asan_load4, __asan_load8, __asan_load16
// __asan_store2, __asan_store8, __asan_store16
```

**check_region_inline() 的核心逻辑**（简化版）：

```c
static __always_inline bool check_region_inline(const void *addr,
                                                  size_t size,
                                                  bool write,
                                                  unsigned long ret_ip)
{
    // 1. 计算影子内存地址
    void *shadow_addr = kasan_mem_to_shadow(addr);

    // 2. 读取影子内存的值（关键！）
    u8 shadow_value = *(u8 *)shadow_addr;  // ← 访问影子内存！

    // 3. 检查影子值是否表明地址可访问
    if (unlikely(shadow_value)) {
        // 不合法的访问
        return false;
    }

    return true;  // 合法的访问
}
```

**影子内存地址计算**（`include/linux/kasan.h`）：

```c
#define KASAN_SHADOW_SCALE_SHIFT 3  // 每 8 字节对应 1 字节影子

static inline void *kasan_mem_to_shadow(const void *addr)
{
    return (void *)((unsigned long)addr >> KASAN_SHADOW_SCALE_SHIFT)
            + KASAN_SHADOW_OFFSET;
    //       ↑ 地址右移 3 位（除以 8）
}
```

**影子内存值的含义**：

| 影子值 | 含义 |
|--------|------|
| 0 | 全部 8 字节都可访问 |
| 1-7 | 前 N 字节可访问，后续字节不可访问 |
| 0xFE | Redzone（栈溢出检测区域） |
| 0xFB | Free 后的内存 |
| 0xF9 | 栈外内存 |

### 3.2 实际插桩示例

**原始代码**（`arch/x86/kernel/idt.c:325`）：

```c
void __init idt_setup_early_handler(void)
{
    int i;

    for (i = 0; i < NUM_EXCEPTION_VECTORS; i++)
        set_intr_gate(i, early_idt_handler_array[i]);
    load_idt(&idt_descr);
}
```

**KASAN 插桩后的等效汇编**（简化版）：

```asm
idt_setup_early_handler:
    push    %rbp
    mov     %rsp, %rbp
    sub     $16, %rsp

    ; 初始化 i = 0
    movl    $0, -4(%rbp)

.L_loop:
    ; 检查 i < NUM_EXCEPTION_VECTORS
    movl    -4(%rbp), %eax
    cmpl    $32, %eax
    jge     .L_end

    ; ★ KASAN 插桩：检查栈上的 i 变量访问
    lea     -4(%rbp), %rdi          ; &i
    call    __asan_load4            ; 检查读取 4 字节
    ; ↑ 如果 KASAN 未初始化，这里会访问无效的影子内存！

    ; 原始代码：加载 i 的值
    movl    -4(%rbp), %eax

    ; ... set_intr_gate 调用 ...

    ; i++
    addl    $1, -4(%rbp)

    ; ★ KASAN 插桩：检查写入
    lea     -4(%rbp), %rdi
    call    __asan_store4           ; 检查写入 4 字节

    jmp     .L_loop

.L_end:
    ; load_idt(&idt_descr)
    ; ★ KASAN 插桩：检查 idt_descr 访问
    lea     idt_descr(%rip), %rdi
    call    __asan_load8            ; 检查读取 idt_descr 结构体

    ; 实际调用 load_idt
    lea     idt_descr(%rip), %rdi
    call    load_idt

    leave
    ret
```

**关键点**：
- 每次读取变量 `i` → 插入 `__asan_load4()`
- 每次写入变量 `i` → 插入 `__asan_store4()`
- 访问全局变量 `idt_descr` → 插入 `__asan_load8()`
- **这些插桩代码是编译时生成的，运行时无法移除**

---

## 4. 如果 KASAN 未初始化会发生什么？

### 4.1 灾难性的执行路径

**场景**：如果在 `kasan_early_init()` 之前调用 `idt_setup_early_handler()`：

```
[T0] idt_setup_early_handler() 被调用
    ↓
[T1] 执行到 __asan_load4(&i)
    ↓
[T2] 计算影子内存地址：
     shadow_addr = (unsigned long)&i >> 3 + KASAN_SHADOW_OFFSET
    ↓
[T3] 访问影子内存：
     shadow_value = *(u8 *)shadow_addr;
    ↓
[T4] ❌ Page Fault！（影子内存页表未建立）
    ↓
[T5] CPU 查找 IDT 来处理 #PF 异常
    ↓
[T6] 调用 Page Fault 处理函数：asm_exc_page_fault
    ↓
[T7] 处理函数内部也被 KASAN 插桩！
     → 再次访问影子内存
     → 再次 Page Fault！
    ↓
[T8] 递归 Page Fault → Double Fault (#DF)
    ↓
[T9] CPU 查找 IDT[8] 处理 Double Fault
    ↓
[T10] Double Fault 处理函数也被插桩！
      → 再次 Page Fault
      → Triple Fault
    ↓
[T11] 💥 CPU 重启（Triple Fault 无法恢复）
```

### 4.2 为什么会递归崩溃？

**核心问题**：异常处理函数本身也被 KASAN 插桩！

**Page Fault 处理函数**（`arch/x86/mm/fault.c`）：

```c
// 这个函数也会被 KASAN 插桩！
DEFINE_IDTENTRY_RAW_ERRORCODE(exc_page_fault)
{
    unsigned long address = read_cr2();  // ← __asan_load8() 被插入
    // ...
    handle_page_fault(regs, error_code, address);  // ← 更多插桩
}
```

**递归崩溃的原因**：
1. 访问未初始化的影子内存 → Page Fault
2. 调用 Page Fault 处理函数 → 函数内有 KASAN 插桩
3. 插桩代码访问影子内存 → 再次 Page Fault
4. **无限递归** → Double Fault → Triple Fault → 重启

### 4.3 实际错误信息

如果你强行调换顺序（先 `idt_setup_early_handler()`，后 `kasan_early_init()`），启动日志可能是：

```
[    0.000000] Linux version 6.x.x ...
[    0.000000] Command line: ...
[    0.000000] x86/fpu: ...
[    0.000000] Memory: ...
[    0.000000] KASAN: ...

(系统在这里直接重启，没有任何错误信息)
```

或者（如果运气好，捕获到 early printk）：

```
early console in extract_kernel
triple fault detected - rebooting
```

---

## 5. 内核源代码证据

### 5.1 head64.c 中的明确注释

**文件**：`arch/x86/kernel/head64.c:263-271`

```c
/*
 * Flush global TLB entries which could be left over from the trampoline page
 * table.
 *
 * This needs to happen *after* kasan_early_init() as KASAN-enabled .configs
 * instrument native_write_cr4() so KASAN must be initialized for that
 * instrumentation to work.
 */
__native_tlb_flush_global(this_cpu_read(cpu_tlbstate.cr4));
```

**解读**：
- ✅ 明确说明 `native_write_cr4()` 被 KASAN 插桩
- ✅ 必须在 `kasan_early_init()` 之后调用
- ✅ 否则插桩代码会崩溃

### 5.2 native_write_cr4() 的插桩

**文件**：`arch/x86/include/asm/tlbflush.h`（内联函数）

```c
static inline void native_write_cr4(unsigned long val)
{
    asm volatile("mov %0,%%cr4": : "r" (val) : "memory");
    //            ↑ 这行汇编代码前后会被插入 __asan_loadXX/storeXX
}
```

**为什么会被插桩**：
- 虽然是内联汇编，但**函数参数** `val` 的访问会被插桩
- `asm volatile` 本身不会被插桩，但**传递参数**的 C 代码会被插桩

**实际生成的代码**（简化）：

```asm
native_write_cr4:
    ; KASAN 插桩：检查参数访问
    lea     val(%rbp), %rdi
    call    __asan_load8

    ; 实际的 CR4 写入
    mov     val(%rbp), %rax
    mov     %rax, %cr4

    ret
```

### 5.3 idt.c 编译时的 KASAN 配置

**文件**：`arch/x86/kernel/Makefile`

```makefile
# 注意：idt.o 没有被排除在 KASAN 之外！
# （如果要排除，应该有：KASAN_SANITIZE_idt.o := n）

obj-y += idt.o
# idt.o 会被 KASAN 插桩
```

**对比**：`arch/x86/boot/startup/Makefile`

```makefile
# 早期启动代码明确禁用 KASAN
KASAN_SANITIZE := n
KCOV_INSTRUMENT := n

obj-y += gdt_idt.o
# gdt_idt.o 不会被 KASAN 插桩
```

### 5.4 __head 宏的作用

**文件**：`arch/x86/include/asm/init.h:6-8`

```c
#if defined(CONFIG_CC_IS_CLANG) && CONFIG_CLANG_VERSION < 170000
#define __head  __section(".head.text") __no_sanitize_undefined __no_stack_protector
#else
#define __head  __section(".head.text") __no_sanitize_undefined __no_sanitize_coverage
#endif
```

**__no_sanitize_undefined 的定义**（`include/linux/compiler_attributes.h`）：

```c
/*
 * Optional: only supported since GCC >= 4.9
 * Optional: not supported by icc
 *
 *   gcc: https://gcc.gnu.org/onlinedocs/gcc/Common-Function-Attributes.html#index-no_005fsanitize_005fundefined-function-attribute
 * clang: https://clang.llvm.org/docs/UndefinedBehaviorSanitizer.html#disabling-instrumentation-with-attribute-no-sanitize-undefined
 */
#if __has_attribute(__no_sanitize_undefined__)
# define __no_sanitize_undefined        __attribute__((__no_sanitize_undefined__))
#else
# define __no_sanitize_undefined
#endif
```

**作用**：
- `__no_sanitize_undefined` 禁用 **UBSAN**（Undefined Behavior Sanitizer）
- `__no_sanitize_coverage` 禁用 **KCOV**（代码覆盖率工具）
- **但不禁用 KASAN！**（需要 `__no_sanitize_address`）

**为什么 gdt_idt.c 不需要 __no_sanitize_address**：

因为 **整个 Makefile** 已经禁用了 KASAN：

```makefile
KASAN_SANITIZE := n  # ← 整个目录都禁用 KASAN
```

---

## 6. 为什么不让 KASAN 自动跳过检查？

### 6.1 理论上的解决方案

你可能会想：KASAN 为什么不加一个判断，如果未初始化就跳过检查？

**伪代码**：

```c
static bool kasan_initialized = false;

void __asan_load4(const void *addr)
{
    if (unlikely(!kasan_initialized))
        return;  // 跳过检查

    // 正常的 KASAN 检查
    void *shadow_addr = kasan_mem_to_shadow(addr);
    u8 shadow_value = *(u8 *)shadow_addr;
    if (shadow_value)
        kasan_report(...);
}

void kasan_early_init(void)
{
    // ... 初始化影子内存 ...
    kasan_initialized = true;  // 标记为已初始化
}
```

### 6.2 为什么内核不这么做？

#### 原因 1：性能开销不可接受

**问题**：在**每一个**内存访问前都加全局判断，性能损失巨大。

**数据**：
- 典型内核代码每秒执行数百万次内存访问
- 每次访问增加一个分支判断 → 增加 1-2 个时钟周期
- KASAN 本身已经造成 **2-3倍性能损失**
- 再加全局判断 → 可能达到 **4-5倍性能损失**

**实测对比**（假设）：

| 配置 | 相对性能 |
|------|---------|
| 无 KASAN | 100% |
| 当前 KASAN | 33-50% |
| 带全局判断的 KASAN | 20-25% |

#### 原因 2：Chicken-and-Egg 问题

**问题**：如何安全地访问 `kasan_initialized` 变量本身？

```c
void __asan_load4(const void *addr)
{
    // ← 访问 kasan_initialized 变量
    //    这个访问本身也会被 KASAN 插桩！
    //    形成无限递归：
    //    __asan_load4 → 检查 kasan_initialized → __asan_load4 → ...
    if (unlikely(!kasan_initialized))
        return;

    // ...
}
```

**解决方法**：需要特殊标记 `kasan_initialized` 为不被插桩：

```c
bool kasan_initialized __attribute__((no_sanitize_address)) = false;
```

但这又引入了新的复杂性和维护负担。

#### 原因 3：违背 KASAN 的设计哲学

**KASAN 的哲学**：
- "要么全有，要么全无"（All or Nothing）
- 初始化前调用插桩代码 = **内核 bug**
- **直接崩溃**反而有助于尽早发现问题

**设计原则**：
- 工具应该暴露问题，而不是隐藏问题
- 如果 KASAN 未初始化就悄悄跳过检查 → 可能隐藏真正的初始化顺序 bug

#### 原因 4：影子内存基址依赖初始化

即使加了 `if (!kasan_initialized)` 判断，KASAN 未初始化时也不知道影子内存的基址：

```c
static unsigned long kasan_shadow_start;  // 在 kasan_early_init() 中设置

void *kasan_mem_to_shadow(const void *addr)
{
    return (void *)((unsigned long)addr >> 3) + kasan_shadow_start;
    //                                          ↑ 未初始化时是 0！
}
```

**结果**：
- 影子地址计算错误
- 访问无效地址
- 仍然会 Page Fault

### 6.3 正确的解决方案

**内核采用的方案**：

```
┌─────────────────────────────────────────────────────┐
│  方案 1：在早期启动代码中禁用 KASAN                │
│                                                      │
│  • 使用 __head 宏（或 KASAN_SANITIZE := n）        │
│  • 早期代码不被插桩                                 │
│  • 运行时代码保留完整的 KASAN 保护                 │
│                                                      │
│  优点：✅ 零性能开销                               │
│        ✅ 无 Chicken-and-Egg 问题                  │
│        ✅ 设计清晰                                  │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│  方案 2：严格的初始化顺序                           │
│                                                      │
│  • kasan_early_init() 必须最早调用                 │
│  • 任何可能被插桩的代码都在之后                    │
│  • 使用编译时检查和代码审查保证顺序                │
│                                                      │
│  优点：✅ 所有运行时代码都有 KASAN 保护           │
│        ✅ 无性能开销                                │
│        ✅ 符合"全有全无"哲学                        │
└─────────────────────────────────────────────────────┘
```

**实际采用**：**两种方案结合**

- 早期启动代码（`gdt_idt.c`）：禁用 KASAN
- 运行时代码（`idt.c`）：保留 KASAN，但保证 `kasan_early_init()` 先执行

---

## 7. 启动顺序的强制约束

### 7.1 完整的初始化依赖链

```
x86_64_start_kernel()
    ↓
┌───────────────────────────────────────────────────┐
│ 第 0 步：编译时检查                               │
│ BUILD_BUG_ON(MODULES_VADDR < __START_KERNEL_map)  │
└───────────────────────────────────────────────────┘
    ↓
┌───────────────────────────────────────────────────┐
│ 第 1 步：CR4 初始化                               │
│ cr4_init_shadow()                                 │
│ • 不涉及复杂内存访问                             │
│ • 可以在 KASAN 初始化前执行                      │
└───────────────────────────────────────────────────┘
    ↓
┌───────────────────────────────────────────────────┐
│ 第 2 步：清除早期页表                             │
│ reset_early_page_tables()                         │
│ • memset 操作，但目标地址简单                    │
│ • 可能被插桩，但访问的内存区域已映射             │
└───────────────────────────────────────────────────┘
    ↓
┌───────────────────────────────────────────────────┐
│ 第 3 步：5 级页表支持                             │
│ if (pgtable_l5_enabled()) { ... }                │
└───────────────────────────────────────────────────┘
    ↓
┌───────────────────────────────────────────────────┐
│ 第 4 步：清零 BSS 段                              │
│ clear_bss()                                       │
└───────────────────────────────────────────────────┘
    ↓
┌───────────────────────────────────────────────────┐
│ 第 5 步：清空顶级页表                             │
│ clear_page(init_top_pgt)                          │
│ • 注释：必须在 kasan_early_init() 之前          │
│ • 原因：KASAN 会往这个页面映射内容               │
└───────────────────────────────────────────────────┘
    ↓
┌───────────────────────────────────────────────────┐
│ 第 6 步：AMD SME 加密支持                         │
│ sme_early_init()                                  │
│ • 注释：必须在可能触发 Page Fault 之前           │
│ • 设置 early_pmd_flags（可能添加加密位）         │
└───────────────────────────────────────────────────┘
    ↓
┌───────────────────────────────────────────────────┐
│ ★ 第 7 步：KASAN 初始化（关键！）                 │
│ kasan_early_init()                                │
│ • 建立影子内存页表映射                           │
│ • 初始化影子内存区域                             │
│ • 设置 kasan_shadow_start                        │
│ ────────────────────────────                     │
│ ✅ 从这里开始，所有插桩代码都可以安全执行        │
└───────────────────────────────────────────────────┘
    ↓
┌───────────────────────────────────────────────────┐
│ 第 8 步：刷新全局 TLB                             │
│ __native_tlb_flush_global(...)                    │
│ • 调用 native_write_cr4()                        │
│ • ★ 这个函数被 KASAN 插桩！                      │
│ • 注释明确说明必须在 kasan_early_init() 之后    │
└───────────────────────────────────────────────────┘
    ↓
┌───────────────────────────────────────────────────┐
│ 第 9 步：设置早期 IDT 处理程序                    │
│ idt_setup_early_handler()                         │
│ • 调用 idt.c 中的函数                            │
│ • ★ idt.c 中的代码被 KASAN 插桩！               │
│ • 必须在 kasan_early_init() 之后                │
└───────────────────────────────────────────────────┘
    ↓
（后续初始化...）
```

### 7.2 依赖关系矩阵

| 步骤 | 函数 | 被 KASAN 插桩？ | 依赖 KASAN 初始化？ | 原因 |
|------|------|----------------|--------------------|----- |
| 1 | `cr4_init_shadow()` | 可能 | ❌ 否 | 简单寄存器操作 |
| 2 | `reset_early_page_tables()` | 可能 | ❌ 否 | 访问的页表已映射 |
| 3-5 | `clear_bss()`, `clear_page()` | 可能 | ❌ 否 | memset/memcpy 可能被优化或标记为不插桩 |
| 6 | `sme_early_init()` | 可能 | ❌ 否 | 必须在 Page Fault 前，可能在特殊编译单元 |
| 7 | `kasan_early_init()` | ❌ 否 | N/A | **KASAN 自身不能被插桩** |
| 8 | `__native_tlb_flush_global()` | ✅ 是 | ✅ **是** | 注释明确说明 |
| 9 | `idt_setup_early_handler()` | ✅ 是 | ✅ **是** | idt.c 被插桩 |

### 7.3 为什么 KASAN 自身不能被插桩？

**问题**：如果 `kasan_early_init()` 本身也被 KASAN 插桩，会怎样？

**递归死锁**：

```c
void kasan_early_init(void)
{
    // ← 函数开始，KASAN 插桩检查
    __asan_load4(&kasan_early_shadow_pte);  // ← 访问影子内存
    //                                          ↑ 但影子内存还没初始化！
    //                                          → Page Fault
    //                                          → 递归崩溃

    // 实际的初始化代码（永远无法执行）
    for (i = 0; i < PTRS_PER_PTE; i++)
        kasan_early_shadow_pte[i] = __pte(pte_val);
}
```

**解决方案**：

**文件**：`arch/x86/mm/Makefile`

```makefile
# 禁用 KASAN 对 kasan_init_64.o 的插桩
KASAN_SANITIZE_kasan_init_64.o := n

obj-$(CONFIG_KASAN) += kasan_init_64.o
```

**验证**：

```bash
$ cd /Users/weli/works/linux
$ grep -n "KASAN_SANITIZE_kasan" arch/x86/mm/Makefile
```

---

## 8. __head 和 KASAN_SANITIZE 的作用

### 8.1 __head 宏的完整定义

**文件**：`arch/x86/include/asm/init.h:6-8`

```c
#if defined(CONFIG_CC_IS_CLANG) && CONFIG_CLANG_VERSION < 170000
#define __head  __section(".head.text") __no_sanitize_undefined __no_stack_protector
#else
#define __head  __section(".head.text") __no_sanitize_undefined __no_sanitize_coverage
#endif
```

**组成部分**：

1. `__section(".head.text")`
   - 将函数放入特殊的 `.head.text` section
   - 这个 section 在链接时会被放在内核镜像的最前面
   - 确保这些代码最早被执行

2. `__no_sanitize_undefined`
   - 禁用 **UBSAN**（Undefined Behavior Sanitizer）
   - UBSAN 检测未定义行为（除零、整数溢出等）

3. `__no_stack_protector` (Clang < 17) 或 `__no_sanitize_coverage` (其他)
   - 禁用**栈保护**（-fstack-protector）
   - 或禁用**代码覆盖率**（KCOV）

**缺少的部分**：
- ❌ **没有** `__no_sanitize_address`（禁用 KASAN）

**为什么 gdt_idt.c 不需要 __no_sanitize_address**：

因为 **Makefile 级别已经禁用**：

```makefile
# arch/x86/boot/startup/Makefile
KASAN_SANITIZE := n  # ← 整个目录禁用 KASAN
KCOV_INSTRUMENT := n

obj-y += gdt_idt.o
```

### 8.2 Makefile 级别的 KASAN 控制

**全局禁用 KASAN 的方法**：

```makefile
# 方法 1：禁用整个目录
KASAN_SANITIZE := n

# 方法 2：禁用特定文件
KASAN_SANITIZE_filename.o := n
```

**示例对比**：

| 文件 | Makefile 设置 | 函数标记 | KASAN 插桩 |
|------|--------------|---------|-----------|
| `arch/x86/boot/startup/gdt_idt.c` | `KASAN_SANITIZE := n` | `__head` | ❌ 否 |
| `arch/x86/kernel/idt.c` | （无特殊设置） | `__init` | ✅ 是 |
| `arch/x86/mm/kasan_init_64.c` | `KASAN_SANITIZE_kasan_init_64.o := n` | `__init` | ❌ 否 |

### 8.3 函数级别的 KASAN 控制

**__no_sanitize_address 宏定义**（`include/linux/compiler_attributes.h`）：

```c
/*
 *   gcc: https://gcc.gnu.org/onlinedocs/gcc/Common-Function-Attributes.html#index-no_005fsanitize_005faddress-function-attribute
 * clang: https://clang.llvm.org/docs/AddressSanitizer.html#disabling-instrumentation-with-attribute-no-sanitize-address
 */
#if __has_attribute(__no_sanitize_address__)
# define __no_sanitize_address __attribute__((__no_sanitize_address__))
#else
# define __no_sanitize_address
#endif
```

**使用示例**：

```c
// 禁用 KASAN 对特定函数的插桩
void __no_sanitize_address my_early_function(void)
{
    // 这个函数不会被 KASAN 插桩
    // 可以在 KASAN 初始化前安全调用
}
```

**实际使用**：

```bash
$ cd /Users/weli/works/linux
$ grep -r "__no_sanitize_address" --include="*.c" arch/x86/ | head -5
```

---

## 9. 总结与设计原则

### 9.1 核心要点总结

1. **编译时插桩 vs 运行时初始化**
   - KASAN 插桩是**编译时决定**的，无法在运行时"关闭"
   - 插桩代码**永久性地存在于目标文件**中
   - 运行时初始化只是准备影子内存，不影响插桩代码的存在

2. **插桩代码的执行路径**
   - 编译器自动插入 `__asan_loadXX` 和 `__asan_storeXX`
   - 这些函数访问**影子内存**来检查内存访问合法性
   - 如果影子内存未初始化 → Page Fault → 递归崩溃

3. **为什么必须先初始化 KASAN**
   - 任何被插桩的函数都需要访问影子内存
   - 影子内存需要**页表映射** + **正确的基址**
   - `kasan_early_init()` 负责建立这些前提条件

4. **为什么不能自动跳过检查**
   - 性能开销不可接受（每次访问都需要全局判断）
   - Chicken-and-Egg 问题（判断变量本身也会被插桩）
   - 违背 KASAN 的"全有全无"哲学
   - 影子内存基址依赖初始化

5. **正确的解决方案**
   - **早期启动代码**：使用 `KASAN_SANITIZE := n` 禁用插桩
   - **运行时代码**：保留 KASAN 保护，但严格保证初始化顺序
   - **KASAN 自身**：禁用对 `kasan_init_64.o` 的插桩

### 9.2 设计原则

#### 原则 1：最小可信计算基（Minimal TCB）

**定义**：系统中必须正确工作才能保证安全的最小代码集合。

**应用**：
- 早期启动代码属于 TCB
- TCB 代码应尽可能简单、不依赖复杂工具
- `gdt_idt.c` 只有 **71 行**，极易审计

#### 原则 2：分离关注点（Separation of Concerns）

**应用**：
- **bringup_idt_table**：临时、极简、早期
- **idt_table**：正式、完整、运行时
- 两者完全独立，不相互影响

#### 原则 3：防御性编程（Defensive Programming）

**应用**：
- 使用编译时检查（`BUILD_BUG_ON`）
- 明确的依赖注释（`/* This needs to happen *after* ... */`）
- 失败即崩溃（Fail-Fast），不隐藏问题

#### 原则 4：工具正交性（Tool Orthogonality）

**KASAN 的职责**：
- 检测内存错误
- **不负责**：适应未初始化的环境

**启动代码的职责**：
- 正确初始化系统
- **不负责**：绕过工具的限制

**结果**：
- KASAN 不需要知道启动顺序
- 启动代码不需要修改 KASAN
- 通过**禁用插桩** + **正确顺序**实现协作

### 9.3 类比理解

**KASAN 就像建筑的消防喷淋系统**：

1. **编译时插桩 = 安装管道**
   - 在建房时，管道已经埋在墙里
   - 管道是永久性的，无法拆除

2. **运行时初始化 = 连接水源**
   - 管道存在，但还没通水
   - 必须先连接水源，才能启用喷淋

3. **未初始化时触发 = 干烧**
   - 发生火灾时，喷淋系统尝试喷水
   - 但水源未连接 → 管道爆裂 → 更大的灾难

4. **正确的做法**：
   - 在入住（启动）前，先连接水源（`kasan_early_init()`）
   - 然后才允许使用各种设施（调用插桩的函数）

---

## 10. 参考文献

### 10.1 Linux 内核源代码

1. **arch/x86/kernel/head64.c**
   - `x86_64_start_kernel()` 函数（行 219-289）
   - 关键注释：行 263-270

2. **arch/x86/mm/kasan_init_64.c**
   - `kasan_early_init()` 函数（行 287-322）

3. **arch/x86/kernel/idt.c**
   - `idt_setup_early_handler()` 函数（行 320-331）

4. **mm/kasan/generic.c**
   - `__asan_loadXX` 和 `__asan_storeXX` 函数

5. **arch/x86/include/asm/init.h**
   - `__head` 宏定义（行 6-8）

6. **arch/x86/boot/startup/Makefile**
   - `KASAN_SANITIZE := n`

7. **arch/x86/mm/Makefile**
   - `KASAN_SANITIZE_kasan_init_64.o := n`

### 10.2 KASAN 文档

8. **The Kernel Address Sanitizer (KASAN)**
   Documentation/dev-tools/kasan.rst

9. **GCC AddressSanitizer**
   https://gcc.gnu.org/onlinedocs/gcc/Instrumentation-Options.html#index-fsanitize_003daddress

10. **Clang AddressSanitizer**
    https://clang.llvm.org/docs/AddressSanitizer.html

### 10.3 相关文档

11. [LINUX_KERNEL_IDT_EVOLUTION.md](LINUX_KERNEL_IDT_EVOLUTION.md)
    - IDT 表的演进流程详解
    - 为什么需要两个独立的 IDT 表

12. [LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md)
    - Linux 内核启动与初始化
    - x86_64_start_kernel() 详解

13. [LINUX_KERNEL_FUNCTION_ATTRIBUTES.md](LINUX_KERNEL_FUNCTION_ATTRIBUTES.md)
    - 函数修饰符与调用约定
    - `__init`, `__head` 等宏的详细说明

---

## 附录 A：KASAN 影子内存布局

### A.1 影子内存映射规则

**基本规则**：
- 每 **8 字节**内存对应 **1 字节**影子内存
- 内核虚拟地址范围：`0xffff888000000000` - `0xffffc87fffffffff`
- 影子内存地址范围：`0xffffec0000000000` - `0xfffffbffffffffff`

**地址转换公式**：

```c
shadow_addr = (mem_addr >> 3) + KASAN_SHADOW_OFFSET

// x86-64 上：
#define KASAN_SHADOW_OFFSET _AC(0xffffec0000000000, UL)
```

### A.2 影子内存值含义

| 影子值 | 十六进制 | 含义 |
|--------|---------|------|
| 0 | 0x00 | 全部 8 字节可访问 |
| 1-7 | 0x01-0x07 | 前 N 字节可访问 |
| -1 | 0xFF | 栈左侧 Redzone |
| -2 | 0xFE | 栈中间 Redzone |
| -3 | 0xFD | 栈右侧 Redzone |
| -4 | 0xFC | 栈使用后的 poison |
| -5 | 0xFB | 堆 free 后的 poison |
| -9 | 0xF7 | 全局 Redzone |
| -10 | 0xF6 | 全局初始化顺序 |

### A.3 示例：栈上的变量

```c
void foo(void) {
    int a = 1;       // 栈地址：0xffffc90000001000
    int b = 2;       // 栈地址：0xffffc90000001004
    // ... 使用 a 和 b ...
}
```

**影子内存布局**：

```
内存地址             | 内容       | 影子地址           | 影子值 | 含义
---------------------|-----------|-------------------|--------|------
0xffffc90000001000   | a (4B)    | 0xffffec0000000200| 0x04   | 前4字节可访问
0xffffc90000001004   | b (4B)    | 0xffffec0000000200| (同上) | 后4字节不可访问
0xffffc90000001008   | (padding) | 0xffffec0000000201| 0xFE   | Redzone
```

---

**文档结束**
