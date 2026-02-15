# Linux 内核函数修饰符与调用约定

## 文档简介

本文档深入解释 Linux 内核中常见的函数修饰符（function attributes）如何影响编译器代码生成和汇编输出。

**核心内容**：
- 🔧 调用约定（Calling Convention）
- 📝 函数修饰符详解（`asmlinkage`, `__visible`, `__init`, `__noreturn` 等）
- 💻 对汇编代码的影响
- 📊 实际代码示例对比
- 🎯 常见组合模式

**典型函数签名示例**：
```c
asmlinkage __visible void __init __noreturn x86_64_start_kernel(char *real_mode_data)
asmlinkage __visible __init __no_sanitize_address __noreturn __no_stack_protector void start_kernel(void)
```

**参考源码**：`~/works/linux/`

---

## 目录

- [一、x86 调用约定基础](#一x86-调用约定基础)
- [二、函数修饰符详解](#二函数修饰符详解)
- [三、汇编代码影响分析](#三汇编代码影响分析)
- [四、实际示例对比](#四实际示例对比)
- [五、常见组合模式](#五常见组合模式)
- [六、与汇编代码交互](#六与汇编代码交互)
- [七、参考资料](#七参考资料)

---

## 一、x86 调用约定基础

### 1.1 什么是调用约定？

**调用约定**（Calling Convention）定义了函数调用时参数如何传递、返回值如何返回、谁负责清理栈等规则。

**为什么重要？**
- C 代码和汇编代码互相调用时必须遵守相同的约定
- 不同的编译器可能使用不同的默认约定
- 内核需要与汇编代码（bootloader、BIOS）交互

### 1.2 x86-64 System V ABI（Linux 标准）

**64 位 Linux 默认使用的调用约定**。

#### 参数传递规则

| 参数位置 | 寄存器 | 备注 |
|---------|--------|------|
| **第 1 个参数** | `RDI` | 64 位整数或指针 |
| **第 2 个参数** | `RSI` | 64 位整数或指针 |
| **第 3 个参数** | `RDX` | 64 位整数或指针 |
| **第 4 个参数** | `RCX` | 64 位整数或指针 |
| **第 5 个参数** | `R8` | 64 位整数或指针 |
| **第 6 个参数** | `R9` | 64 位整数或指针 |
| **第 7+ 个参数** | **栈** | 从右向左压栈 |

**浮点参数**：使用 `XMM0`-`XMM7` 寄存器

**返回值**：
- 整数/指针：`RAX`
- 浮点数：`XMM0`
- 大型结构体：通过隐藏的第一个参数传递指针

#### 寄存器保存规则

| 类型 | 寄存器 | 谁负责保存？ |
|------|--------|------------|
| **Caller-saved** | `RAX, RCX, RDX, RSI, RDI, R8-R11` | 调用者保存（如需要） |
| **Callee-saved** | `RBX, RBP, R12-R15` | 被调用者保存（必须恢复） |
| **特殊** | `RSP` | 栈指针（必须恢复） |

**示例**：

```c
// C 代码
long add(long a, long b, long c) {
    return a + b + c;
}

// 对应的汇编（x86-64 System V ABI）
add:
    // a in RDI, b in RSI, c in RDX
    lea rax, [rdi + rsi]  // RAX = a + b
    add rax, rdx          // RAX = RAX + c
    ret                   // 返回值在 RAX
```

### 1.3 x86-32 调用约定（cdecl）

**32 位 Linux 默认使用的调用约定**。

#### 参数传递规则

| 参数位置 | 传递方式 | 压栈顺序 |
|---------|---------|---------|
| **所有参数** | **栈** | **从右向左** |

**返回值**：
- `EAX`（32 位整数）
- `EDX:EAX`（64 位整数，高 32 位在 EDX）

**栈清理**：
- **Caller 清理**（调用者负责）

**示例**：

```c
// C 代码
int add(int a, int b, int c) {
    return a + b + c;
}

// 对应的汇编（x86-32 cdecl）
add:
    push ebp
    mov  ebp, esp
    mov  eax, [ebp+8]   // a (第 1 个参数)
    add  eax, [ebp+12]  // b (第 2 个参数)
    add  eax, [ebp+16]  // c (第 3 个参数)
    pop  ebp
    ret

// 调用代码
push 3      // c
push 2      // b
push 1      // a
call add
add esp, 12 // 调用者清理栈（3 个参数 × 4 字节）
```

### 1.4 为什么需要 asmlinkage？

在某些架构（尤其是 **x86-32**）上，编译器可能使用**寄存器传参优化**（如 GCC 的 `-mregparm=N`）：

```c
// 默认情况（GCC 可能优化）
int foo(int a, int b);  // 可能使用 EAX, EDX 传参

// 强制栈传参（汇编兼容）
asmlinkage int foo(int a, int b);  // 必须使用栈传参
```

**asmlinkage 的作用**：
- ✅ 强制使用**栈传参**（x86-32）
- ✅ 确保与**汇编代码兼容**
- ✅ 在 x86-64 上通常是空宏（因为 System V ABI 已经使用寄存器）

---

## 二、函数修饰符详解

### 2.1 asmlinkage - 调用约定

#### 定义（内核源码）

**文件**：`include/linux/linkage.h:22`

```c
#ifdef __cplusplus
#define CPP_ASMLINKAGE extern "C"
#else
#define CPP_ASMLINKAGE
#endif

#ifndef asmlinkage
#define asmlinkage CPP_ASMLINKAGE
#endif
```

**文件**：`arch/x86/include/asm/linkage.h`（x86-32 专用）

```c
#ifdef CONFIG_X86_32
#define asmlinkage CPP_ASMLINKAGE __attribute__((regparm(0)))
#endif
```

#### 含义

| 架构 | 定义 | 作用 |
|------|------|------|
| **x86-32** | `__attribute__((regparm(0)))` | **强制栈传参**，禁用寄存器优化 |
| **x86-64** | （空宏） | 无额外作用（System V ABI 已定义） |
| **C++** | `extern "C"` | 禁用 C++ 名称修饰（name mangling） |

#### 使用场景

1. **从汇编调用的 C 函数**
   ```c
   asmlinkage void x86_64_start_kernel(char *real_mode_data);
   ```
   - 汇编代码：`call x86_64_start_kernel`
   - 必须使用栈传参，汇编才能正确传递参数

2. **系统调用表**
   ```c
   asmlinkage const sys_call_ptr_t sys_call_table[];
   ```
   - 系统调用从用户态进入，参数在栈上
   - 所有系统调用处理函数必须使用 `asmlinkage`

3. **中断处理函数**
   ```c
   asmlinkage void do_page_fault(struct pt_regs *regs, unsigned long error_code);
   ```
   - CPU 触发中断时，寄存器状态已保存到栈
   - 处理函数必须从栈读取参数

#### 反例：不使用 asmlinkage 的后果

```c
// ❌ 错误：没有 asmlinkage
void x86_64_start_kernel(char *real_mode_data) {
    // 编译器可能期望参数在 RDI
    // 但汇编代码可能将参数压栈
    // 导致参数错位！
}

// ✅ 正确：使用 asmlinkage
asmlinkage void x86_64_start_kernel(char *real_mode_data) {
    // 强制从栈读取参数
    // 与汇编代码约定一致
}
```

---

### 2.2 __visible - 符号可见性

#### 定义（内核源码）

**文件**：`include/linux/compiler_attributes.h:149`

```c
#if __has_attribute(__externally_visible__)
# define __visible  __attribute__((__externally_visible__))
#else
# define __visible
#endif
```

#### 含义

**GCC 属性**：`__attribute__((__externally_visible__))`

**作用**：
- ✅ **防止 LTO（Link Time Optimization）优化掉符号**
- ✅ 确保符号在**链接时可见**
- ✅ 即使函数看起来"未使用"，也不会被删除

#### 为什么需要？

**问题场景**：

```c
// arch/x86/kernel/head64.c
void x86_64_start_kernel(char *real_mode_data) {
    // 这个函数从汇编调用，C 代码中没有显式调用
    // LTO 优化器可能认为它"未使用"
}

// arch/x86/kernel/head_64.S
call x86_64_start_kernel  // ← 链接时找不到符号！💥
```

**解决方案**：

```c
// ✅ 正确：使用 __visible
__visible void x86_64_start_kernel(char *real_mode_data) {
    // LTO 优化器知道这个符号必须保留
}
```

#### 使用场景

1. **汇编入口函数**
   ```c
   asmlinkage __visible void __init __noreturn x86_64_start_kernel(char *real_mode_data)
   ```

2. **全局符号表**
   ```c
   __visible const sys_call_ptr_t ia32_sys_call_table[]
   ```

3. **外部链接的符号**
   ```c
   __visible void start_kernel(void)
   ```

---

### 2.3 __init - 初始化后释放

#### 定义（内核源码）

**文件**：`include/linux/init.h:54`

```c
#define __init  __section(".init.text") __cold __latent_entropy  \
                __noinitretpoline __no_sanitize_coverage
```

#### 含义

| 组成部分 | 作用 |
|---------|------|
| `__section(".init.text")` | **放入 .init.text 段** |
| `__cold` | 标记为"冷代码"（不常执行） |
| `__latent_entropy` | 增加内核熵池（安全） |
| `__noinitretpoline` | 禁用 Retpoline（初始化代码不需要） |
| `__no_sanitize_coverage` | 禁用代码覆盖率检测 |

#### 核心机制：.init.text 段

**内存布局**：

```
内核镜像：
┌──────────────────────┐
│  .text (内核代码)     │ ← 永久驻留
├──────────────────────┤
│  .data (内核数据)     │ ← 永久驻留
├──────────────────────┤
│  .init.text           │ ← 初始化代码（启动后释放）
│  .init.data           │ ← 初始化数据（启动后释放）
└──────────────────────┘
```

**生命周期**：

```c
start_kernel()
    ↓
... 各种 __init 函数执行 ...
    ↓
rest_init()
    ↓
kernel_init()
    ↓
free_initmem()  // ← 释放所有 .init.* 段
    ↓
__init 函数的内存被回收
```

**实际代码**：`init/main.c`

```c
static int __ref kernel_init(void *unused)
{
    // ... 初始化工作 ...

    free_initmem();  // 释放 .init.text 和 .init.data

    // 此后调用 __init 函数会导致 Page Fault！
}
```

#### 使用场景

1. **一次性初始化函数**
   ```c
   static void __init setup_arch(char **cmdline_p)
   ```

2. **早期设备初始化**
   ```c
   static int __init pci_init(void)
   ```

3. **模块初始化**
   ```c
   module_init(my_driver_init);  // 展开后包含 __init
   ```

#### 节省的内存

**示例计算**：

```bash
# 查看 .init.text 段大小
$ size vmlinux
   text    data     bss     dec     hex filename
2356789  456123   89456 2902368  2c4b60 vmlinux

# .init.text 通常占 5-10% 的代码段
# 假设 100KB，释放后节省 100KB 内存
```

#### 相关修饰符

| 修饰符 | 段 | 用途 |
|-------|----|----|
| `__init` | `.init.text` | 初始化函数 |
| `__initdata` | `.init.data` | 初始化数据 |
| `__initconst` | `.init.rodata` | 初始化只读数据 |
| `__exit` | `.exit.text` | 模块卸载函数（内置模块忽略） |

---

### 2.4 __noreturn - 永不返回

#### 定义（内核源码）

**文件**：`include/linux/compiler_attributes.h:262`

```c
#define __noreturn  __attribute__((__noreturn__))
```

#### 含义

**GCC 属性**：`__attribute__((__noreturn__))`

**作用**：
- ✅ 告诉编译器函数**永不返回**
- ✅ 编译器可以省略**返回地址保存**
- ✅ 编译器可以省略**尾部清理代码**
- ✅ 调用者可以假设后续代码**不会执行**

#### 汇编代码影响

**无 __noreturn**：

```c
void normal_function(void) {
    while (1) {
        // 无限循环
    }
}

// 生成的汇编
normal_function:
    push rbp
    mov  rbp, rsp
.L1:
    jmp .L1         // 无限循环
    pop  rbp        // ← 死代码，但编译器仍生成
    ret             // ← 死代码
```

**有 __noreturn**：

```c
void __noreturn noreturn_function(void) {
    while (1) {
        // 无限循环
    }
}

// 生成的汇编
noreturn_function:
    // 省略了栈帧设置（不需要返回）
.L1:
    jmp .L1         // 无限循环
    // 没有 ret 指令
```

#### 使用场景

1. **内核入口（永不返回）**
   ```c
   asmlinkage __visible void __init __noreturn x86_64_start_kernel(char *real_mode_data)
   {
       // ... 初始化 ...
       start_kernel();  // 调用另一个 __noreturn 函数
   }
   ```

2. **panic 函数**
   ```c
   void __noreturn panic(const char *fmt, ...)
   {
       // ... 打印错误 ...
       while (1)
           cpu_relax();
   }
   ```

3. **do_exit（进程退出）**
   ```c
   void __noreturn do_exit(long code)
   {
       // ... 清理资源 ...
       // 切换到其他进程，永不返回
   }
   ```

#### 编译器优化

**调用 __noreturn 函数后的代码优化**：

```c
void foo(void) {
    if (error) {
        panic("Fatal error!");  // __noreturn
        // 编译器知道永不返回
    }
    // 编译器知道 error == false 时才会执行到这里
    do_something();
}

// 优化后的逻辑
void foo(void) {
    if (!error) {
        do_something();
    } else {
        panic("Fatal error!");
    }
}
```

---

### 2.5 __no_sanitize_address - 禁用 KASAN

#### 定义（内核源码）

**文件**：`include/linux/compiler-clang.h:29`（Clang）

```c
#define __no_sanitize_address \
    __attribute__((no_sanitize("address", "hwaddress")))
```

**文件**：`include/linux/compiler-gcc.h:72`（GCC）

```c
#define __no_sanitize_address __attribute__((__no_sanitize_address__))
```

#### 含义

**KASAN（Kernel Address Sanitizer）**：内核地址检测工具
- 检测**越界访问**
- 检测**use-after-free**
- 检测**double-free**

**为什么要禁用？**

某些**极早期代码**在 KASAN 初始化之前运行：
- 页表初始化
- 内存管理器初始化
- KASAN 自身的初始化

如果这些代码使用 KASAN，会导致**递归依赖**或**未定义行为**。

#### 使用场景

```c
asmlinkage __visible __init __no_sanitize_address __noreturn __no_stack_protector
void start_kernel(void)
{
    // 这是内核第一个 C 函数
    // 此时 KASAN 尚未初始化
    // 必须禁用 KASAN 检测
}
```

---

### 2.6 __no_stack_protector - 禁用栈保护

#### 定义（内核源码）

**文件**：`include/linux/compiler_attributes.h:270`

```c
#if __has_attribute(__no_stack_protector__)
# define __no_stack_protector  __attribute__((__no_stack_protector__))
#else
# define __no_stack_protector
#endif
```

#### 含义

**栈保护（Stack Protector）**：编译器插入的安全机制
- 在栈上放置**Canary 值**
- 函数返回前**检查 Canary**
- 如果被篡改，说明发生**栈溢出攻击**

**栈保护的汇编代码**：

```c
// 无栈保护
void foo(void) {
    char buf[16];
    // ...
}

// 有栈保护
void foo(void) {
    char buf[16];
    // 编译器插入代码：
    // mov rax, fs:[0x28]  // 读取 Canary
    // mov [rsp+24], rax   // 存到栈上
    // ...
    // mov rax, [rsp+24]   // 读回 Canary
    // xor rax, fs:[0x28]  // 检查是否被篡改
    // jne __stack_chk_fail // 如果不同，调用错误处理
}
```

#### 为什么要禁用？

**极早期代码**没有栈保护基础设施：
- `fs:[0x28]` 尚未初始化
- `__stack_chk_fail` 函数不可用

```c
asmlinkage __visible __init __no_sanitize_address __noreturn __no_stack_protector
void start_kernel(void)
{
    // 此时 per-CPU 变量（包括 Canary）尚未初始化
    // 必须禁用栈保护
}
```

---

### 2.7 其他常见修饰符

#### __cold - 冷代码标记

```c
#define __cold  __attribute__((__cold__))
```

**作用**：
- 告诉编译器这段代码**很少执行**
- 编译器可能将其移到代码段末尾
- 提高**热代码的缓存命中率**

**使用场景**：
- 错误处理路径
- 初始化代码（`__init` 自动包含）

---

#### __used - 防止优化删除

```c
#define __used  __attribute__((__used__))
```

**作用**：
- 即使符号看起来"未使用"，也**不删除**
- 类似 `__visible`，但不影响链接可见性

**使用场景**：
- 模块导出的符号
- 通过特殊方式调用的函数（如 `.initcall` 段）

---

#### __attribute__((section("name"))) - 指定段

**作用**：
- 将函数/数据放到**指定的 ELF 段**

**示例**：

```c
__attribute__((section(".init.text"))) void foo(void)
// 等价于
__init void foo(void)
```

---

## 三、汇编代码影响分析

### 3.1 asmlinkage 对汇编的影响（x86-32）

#### 无 asmlinkage（寄存器传参）

```c
// C 代码
int add(int a, int b, int c) {
    return a + b + c;
}

// 编译器可能生成（GCC -mregparm=3）
add:
    // a in EAX, b in EDX, c in ECX
    lea eax, [eax + edx]
    add eax, ecx
    ret

// 调用代码
mov eax, 1  // a
mov edx, 2  // b
mov ecx, 3  // c
call add
// 没有栈操作！
```

#### 有 asmlinkage（栈传参）

```c
// C 代码
asmlinkage int add(int a, int b, int c) {
    return a + b + c;
}

// 必然生成（强制栈传参）
add:
    push ebp
    mov  ebp, esp
    mov  eax, [ebp+8]   // a
    add  eax, [ebp+12]  // b
    add  eax, [ebp+16]  // c
    pop  ebp
    ret

// 调用代码（汇编兼容）
push 3  // c
push 2  // b
push 1  // a
call add
add esp, 12
```

---

### 3.2 __visible 对链接的影响

#### 无 __visible（LTO 可能删除）

```c
// foo.c
void internal_function(void) {
    // C 代码中没有调用
    // LTO 优化器：这个函数没用，删掉！
}

// bar.S
.global _start
_start:
    call internal_function  // ← 链接错误！undefined reference
```

#### 有 __visible（强制保留）

```c
// foo.c
__visible void internal_function(void) {
    // LTO 优化器：这个符号被标记为外部可见，必须保留
}

// bar.S
.global _start
_start:
    call internal_function  // ✅ 链接成功
```

---

### 3.3 __init 对内存布局的影响

#### 链接器脚本（vmlinux.lds）

```ld
SECTIONS
{
    .text : {
        *(.text)           /* 普通代码 */
    }

    .init.text : {
        __init_begin = .;
        *(.init.text)      /* __init 标记的代码 */
        __init_end = .;
    }
}
```

#### 运行时释放

```c
void free_initmem(void)
{
    unsigned long start = (unsigned long)&__init_begin;
    unsigned long end = (unsigned long)&__init_end;

    free_reserved_area(start, end, -1, "unused kernel");
    // .init.text 段的内存被释放，回到物理内存池
}
```

---

### 3.4 __noreturn 对代码生成的影响

#### 无 __noreturn

```c
void infinite_loop(void) {
    while (1)
        cpu_relax();
}

// 生成的汇编
infinite_loop:
    push rbp
    mov  rbp, rsp
.L1:
    pause               // cpu_relax()
    jmp  .L1
    pop  rbp            // ← 死代码
    ret                 // ← 死代码
```

#### 有 __noreturn

```c
void __noreturn infinite_loop(void) {
    while (1)
        cpu_relax();
}

// 生成的汇编
infinite_loop:
    // 省略了栈帧
.L1:
    pause
    jmp .L1
    // 没有返回代码
```

**节省的字节数**：
- `push rbp` (1 字节)
- `mov rbp, rsp` (3 字节)
- `pop rbp` (1 字节)
- `ret` (1 字节)
- **总计：6 字节**

---

## 四、实际示例对比

### 4.1 x86_64_start_kernel 函数

#### 完整签名

**文件**：`arch/x86/kernel/head64.c:219`

```c
asmlinkage __visible void __init __noreturn x86_64_start_kernel(char *real_mode_data)
{
    // ... 初始化代码 ...
    start_kernel();  // 调用另一个 __noreturn 函数
}
```

#### 修饰符分析

| 修饰符 | 作用 | 原因 |
|-------|------|------|
| `asmlinkage` | 强制栈传参（x86-32）| 从汇编 `call` 指令调用 |
| `__visible` | 防止 LTO 删除符号 | 汇编代码需要链接到此符号 |
| `__init` | 放入 .init.text 段 | 只在启动时执行一次，后续释放 |
| `__noreturn` | 永不返回 | 最终调用 `start_kernel()`（也是 __noreturn） |

#### 汇编调用代码

**文件**：`arch/x86/kernel/head_64.S`

```asm
SYM_CODE_START_NOALIGN(startup_64)
    // ... 早期设置 ...

    // 准备参数
    movq	initial_code(%rip), %rax
    pushq	$__KERNEL_CS
    pushq	%rax

    // 跳转到 x86_64_start_kernel
    lretq

SYM_DATA(initial_code, .quad x86_64_start_kernel)
```

#### 如果没有这些修饰符会怎样？

```c
// ❌ 错误版本
void x86_64_start_kernel(char *real_mode_data)
{
    // ...
}
```

**问题**：
1. **没有 asmlinkage**：编译器可能期望参数在 `RDI`，但汇编可能用栈
2. **没有 __visible**：LTO 可能删除符号，链接失败
3. **没有 __init**：代码留在 .text 段，浪费内存
4. **没有 __noreturn**：生成无用的返回代码

---

### 4.2 start_kernel 函数

#### 完整签名

**文件**：`init/main.c:856`

```c
asmlinkage __visible __init __no_sanitize_address __noreturn __no_stack_protector
void start_kernel(void)
{
    char *command_line;
    char *after_dashes;

    // ... 大量初始化代码 ...

    arch_call_rest_init();  // 永不返回
}
```

#### 修饰符分析

| 修饰符 | 作用 | 原因 |
|-------|------|------|
| `asmlinkage` | 栈传参 | 从 `x86_64_start_kernel` 调用 |
| `__visible` | 符号可见 | 防止 LTO 删除 |
| `__init` | 初始化后释放 | 只执行一次 |
| `__no_sanitize_address` | 禁用 KASAN | KASAN 尚未初始化 |
| `__noreturn` | 永不返回 | 最终调用 `cpu_startup_entry()` |
| `__no_stack_protector` | 禁用栈保护 | per-CPU 变量尚未初始化 |

#### 为什么需要这么多修饰符？

**start_kernel 是内核的第一个 C 函数**：
- ⚠️ 此时**几乎所有基础设施都未初始化**
- ⚠️ 不能依赖任何运行时检测工具（KASAN、栈保护）
- ⚠️ 必须与汇编代码兼容
- ⚠️ 只执行一次，代码应该被释放

---

### 4.3 系统调用表

#### 完整定义

**文件**：`arch/x86/entry/syscall_64.c`

```c
asmlinkage const sys_call_ptr_t sys_call_table[] = {
    [0] = __x64_sys_read,
    [1] = __x64_sys_write,
    [2] = __x64_sys_open,
    // ... 共 400+ 个系统调用
};
```

**文件**：`arch/x86/entry/syscall_32.c`（32 位兼容）

```c
__visible const sys_call_ptr_t ia32_sys_call_table[] = {
    [0] = __ia32_sys_restart_syscall,
    [1] = __ia32_sys_exit,
    // ...
};
```

#### 修饰符分析

| 修饰符 | 作用 | 原因 |
|-------|------|------|
| `asmlinkage` | 栈传参约定 | 系统调用参数从栈传递 |
| `__visible` | 符号可见 | 汇编代码需要访问此表 |
| `const` | 只读数据 | 防止篡改系统调用表 |

#### 汇编代码访问

**文件**：`arch/x86/entry/entry_64.S`

```asm
SYM_CODE_START(entry_SYSCALL_64)
    // ... 保存寄存器 ...

    // 查找系统调用表
    movq  sys_call_table(, %rax, 8), %rax  // 读取 sys_call_table[syscall_nr]
    call  *%rax                             // 调用系统调用处理函数

    // ... 恢复寄存器 ...
SYM_CODE_END(entry_SYSCALL_64)
```

---

## 五、常见组合模式

### 5.1 内核入口函数

**模式**：
```c
asmlinkage __visible void __init __noreturn x86_64_start_kernel(char *real_mode_data)
asmlinkage __visible __init __no_sanitize_address __noreturn __no_stack_protector void start_kernel(void)
```

**使用场景**：
- 从汇编调用的 C 入口点
- 系统初始化的第一个 C 函数
- 只执行一次，永不返回

**关键特点**：
- ✅ 与汇编兼容（`asmlinkage`）
- ✅ 防止优化删除（`__visible`）
- ✅ 初始化后释放（`__init`）
- ✅ 禁用运行时检测（`__no_sanitize_address`, `__no_stack_protector`）
- ✅ 优化尾部代码（`__noreturn`）

---

### 5.2 系统调用处理函数

**模式**：
```c
asmlinkage long sys_read(unsigned int fd, char __user *buf, size_t count)
asmlinkage long sys_write(unsigned int fd, const char __user *buf, size_t count)
```

**使用场景**：
- 系统调用入口点
- 从用户态通过 `syscall` 指令进入

**关键特点**：
- ✅ 栈传参约定（`asmlinkage`）
- ✅ 参数标记（`__user`：用户空间指针）

---

### 5.3 中断/异常处理函数

**模式**：
```c
asmlinkage void do_page_fault(struct pt_regs *regs, unsigned long error_code)
asmlinkage void do_general_protection(struct pt_regs *regs, long error_code)
```

**使用场景**：
- CPU 异常处理入口
- 从 IDT 跳转到的 C 函数

**关键特点**：
- ✅ 栈传参（`asmlinkage`）
- ✅ 参数是保存的寄存器状态（`struct pt_regs *`）

---

### 5.4 早期初始化函数

**模式**：
```c
void __init setup_arch(char **cmdline_p)
static int __init pci_init(void)
```

**使用场景**：
- 设备初始化
- 子系统初始化
- 只在启动时执行一次

**关键特点**：
- ✅ 初始化后释放（`__init`）
- ✅ 节省内存

---

### 5.5 永不返回的函数

**模式**：
```c
void __noreturn panic(const char *fmt, ...)
void __noreturn do_exit(long code)
void __noreturn cpu_startup_entry(enum cpuhp_state state)
```

**使用场景**：
- 内核 panic
- 进程退出
- CPU 空闲循环

**关键特点**：
- ✅ 永不返回（`__noreturn`）
- ✅ 编译器优化

---

## 六、与汇编代码交互

### 6.1 从汇编调用 C 函数

#### 步骤 1：C 函数定义

```c
// arch/x86/kernel/head64.c
asmlinkage __visible void __init setup_idt(void)
{
    // 设置 IDT
}
```

#### 步骤 2：汇编代码调用

```asm
# arch/x86/kernel/head_64.S
.global startup_64
startup_64:
    # ... 早期设置 ...

    # 调用 C 函数
    call setup_idt

    # ... 继续执行 ...
```

#### 关键点

1. **必须使用 `asmlinkage`**（确保参数传递约定一致）
2. **必须使用 `__visible`**（确保符号在链接时可见）
3. **参数传递**：
   - x86-64：前 6 个参数在寄存器（RDI, RSI, RDX, RCX, R8, R9）
   - x86-32：所有参数在栈

---

### 6.2 从 C 调用汇编函数

#### 步骤 1：汇编函数定义

```asm
# arch/x86/lib/copy_user_64.S
SYM_FUNC_START(copy_user_generic_unrolled)
    # RDI = dest
    # RSI = src
    # RDX = len

    # ... 复制内存 ...

    ret
SYM_FUNC_END(copy_user_generic_unrolled)
```

#### 步骤 2：C 函数声明

```c
// arch/x86/include/asm/uaccess_64.h
unsigned long copy_user_generic_unrolled(void *to, const void *from, unsigned len);
```

#### 步骤 3：C 代码调用

```c
unsigned long copy_to_user(void __user *to, const void *from, unsigned long n)
{
    return copy_user_generic_unrolled(to, from, n);
}
```

#### 关键点

1. **C 声明不需要 `asmlinkage`**（System V ABI 默认使用寄存器）
2. **汇编函数必须遵守调用约定**（保存 callee-saved 寄存器）

---

### 6.3 参数传递示例

#### x86-64 参数传递

```c
// C 函数
asmlinkage long foo(int a, int b, int c, int d, int e, int f, int g);

// 汇编调用
mov edi, 1      // a -> RDI
mov esi, 2      // b -> RSI
mov edx, 3      // c -> RDX
mov ecx, 4      // d -> RCX
mov r8d, 5      // e -> R8
mov r9d, 6      // f -> R9
push 7          // g -> 栈
call foo
add rsp, 8      // 清理栈
```

#### x86-32 参数传递（asmlinkage）

```c
// C 函数
asmlinkage int bar(int a, int b, int c);

// 汇编调用
push 3          // c
push 2          // b
push 1          // a
call bar
add esp, 12     // 清理栈（3 × 4 字节）
```

---

## 七、参考资料

### 7.1 Linux 内核源码

> **参考源码目录**：`~/works/linux/`

**函数修饰符定义**：
- `include/linux/linkage.h` - asmlinkage 定义
- `include/linux/compiler_attributes.h` - __visible, __noreturn, __cold 等
- `include/linux/init.h` - __init, __initdata, __exit 等
- `arch/x86/include/asm/linkage.h` - x86 特定的 asmlinkage

**实际使用示例**：
- `arch/x86/kernel/head64.c:219` - x86_64_start_kernel
- `init/main.c:856` - start_kernel
- `arch/x86/entry/syscall_64.c` - sys_call_table
- `arch/x86/kernel/traps.c` - 异常处理函数

### 7.2 GCC 文档

**函数属性**：
- https://gcc.gnu.org/onlinedocs/gcc/Function-Attributes.html
  - `__attribute__((__noreturn__))`
  - `__attribute__((__externally_visible__))`
  - `__attribute__((__cold__))`
  - `__attribute__((regparm(N)))`

**ABI 文档**：
- **x86-64 System V ABI**: https://refspecs.linuxfoundation.org/elf/x86_64-abi-0.99.pdf
  - 第 3 章：低级系统信息
  - 第 3.2 节：函数调用序列
  - 寄存器使用、参数传递、栈布局

### 7.3 项目文档

**相关主题**：
- [LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md) - start_kernel 详解
- [LINUX_MEMORY_MANAGEMENT_CODE_GUIDE.md](LINUX_MEMORY_MANAGEMENT_CODE_GUIDE.md) - x86_64_start_kernel 内存初始化
- [LINUX_KERNEL_SYSCALL_INIT.md](LINUX_KERNEL_SYSCALL_INIT.md) - 系统调用表与 entry_SYSCALL_64
- [LINUX_KERNEL_IDT_EVOLUTION.md](LINUX_KERNEL_IDT_EVOLUTION.md) - 异常处理函数

**汇编交互**：
- [GRUB_KERNEL_LOADING.md](GRUB_KERNEL_LOADING.md) - GRUB 如何跳转到内核
- [LINUX_INTERRUPT_GUIDE.md](LINUX_INTERRUPT_GUIDE.md) - 中断处理流程

### 7.4 在线资源

**x86 调用约定**：
- OSDev Wiki: https://wiki.osdev.org/Calling_Conventions
- x86-64 ABI: https://github.com/hjl-tools/x86-psABI/wiki/x86-64-psABI-1.0.pdf

**Linux 内核文档**：
- https://www.kernel.org/doc/html/latest/
  - Documentation/process/coding-style.rst
  - Documentation/kbuild/makefiles.rst

---

## 附录：快速参考表

### A.1 函数修饰符速查

| 修饰符 | 定义 | 主要作用 | 典型场景 |
|-------|------|---------|---------|
| `asmlinkage` | `__attribute__((regparm(0)))` (x86-32) | 强制栈传参 | 汇编调用、系统调用 |
| `__visible` | `__attribute__((__externally_visible__))` | 防止 LTO 删除 | 汇编入口、全局符号 |
| `__init` | `__section(".init.text") ...` | 初始化后释放 | 一次性初始化函数 |
| `__noreturn` | `__attribute__((__noreturn__))` | 永不返回 | panic、do_exit、入口函数 |
| `__cold` | `__attribute__((__cold__))` | 冷代码标记 | 错误处理、初始化代码 |
| `__used` | `__attribute__((__used__))` | 防止删除 | 特殊调用的符号 |
| `__no_sanitize_address` | `__attribute__((no_sanitize("address")))` | 禁用 KASAN | 早期代码、KASAN 自身 |
| `__no_stack_protector` | `__attribute__((__no_stack_protector__))` | 禁用栈保护 | 早期代码 |

### A.2 调用约定速查

#### x86-64 System V ABI

| 参数 | 寄存器 | 返回值 | 寄存器 |
|------|--------|--------|--------|
| 1 | RDI | 整数/指针 | RAX |
| 2 | RSI | 浮点 | XMM0 |
| 3 | RDX | - | - |
| 4 | RCX | - | - |
| 5 | R8 | - | - |
| 6 | R9 | - | - |
| 7+ | 栈 | - | - |

**Callee-saved**：`RBX, RBP, R12-R15, RSP`

#### x86-32 cdecl

| 参数 | 传递方式 | 返回值 | 寄存器 |
|------|---------|--------|--------|
| 所有 | 栈（从右向左） | 32 位 | EAX |
| - | - | 64 位 | EDX:EAX |

**Callee-saved**：`EBX, ESI, EDI, EBP, ESP`

---

**文档版本**：v1.0 (2026-02-15)
**维护说明**：本文档基于 Linux v6.x 内核源码，定义可能随内核版本变化。
