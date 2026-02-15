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
- [八、扩展阅读：权威参考文档](#八扩展阅读权威参考文档)

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

#### 规范定义

> 📖 **权威引述**（System V ABI AMD64 Architecture Processor Supplement, Draft Version 0.99.6, Figure 3.4）
>
> **Register Usage**:
>
> | Register | Usage | Preserved across function calls |
> |----------|-------|--------------------------------|
> | `%rax` | temporary register; return value | No |
> | `%rbx` | callee-saved register | Yes |
> | `%rcx` | 4th argument to functions | No |
> | `%rdx` | 3rd argument to functions; return register | No |
> | `%rsi` | 2nd argument to functions | No |
> | `%rdi` | 1st argument to functions | No |
> | `%rbp` | callee-saved register; frame pointer | Yes |
> | `%rsp` | stack pointer | Yes |
> | `%r8` | 5th argument to functions | No |
> | `%r9` | 6th argument to functions | No |
> | `%r10`-`%r11` | temporary registers | No |
> | `%r12`-`%r15` | callee-saved registers | Yes |
>
> **来源**：`reference-docs/x86_64-abi-0.99.pdf`, Page 21, Figure 3.4

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

#### Red Zone（红区）

> 📖 **权威引述**（Agner Fog, "Calling conventions", Section 7, Page 20）
>
> **64 bit Linux, BSD and Mac**:
>
> "There is no shadow space on the stack. Instead there is a **'red zone'** below the stack pointer that can be used for temporary storage. The red zone is the space from `[rsp-128]` to `[rsp-8]`. A function can rely on this space being untouched by interrupt and exception handlers (except in kernel code). It is therefore safe to use this space for temporary storage **as long as you don't do any `push` or `call` instructions**. Everything stored in the red zone is destroyed by function calls. **The red zone is not available in Windows**."
>
> **来源**：`reference-docs/agner_calling_conventions.pdf`, Page 20

**Red Zone 要点**：
- ✅ **128 字节临时存储空间**（位于 `RSP-128` 到 `RSP-8`）
- ✅ 无需调整栈指针即可使用
- ✅ 中断处理器不会破坏此区域（内核模式除外）
- ⚠️ **不能在 Red Zone 使用后再调用 `call` 或 `push`**
- ⚠️ **Windows 上不存在 Red Zone**

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

#### 规范定义

> 📖 **权威引述**（System V ABI Intel386 Architecture Processor Supplement, Fourth Edition, Page 37-38）
>
> **Function Calling Sequence**:
>
> "The **calling function** pushes arguments onto the stack in **reverse order** (i.e., right to left), and the **called function** is responsible for removing them from the stack.
>
> Registers `%ebp`, `%ebx`, `%edi`, `%esi`, and `%esp` are **callee-saved** and must be preserved by the function if they are used.
>
> All other registers, including `%eax`, `%edx`, and `%ecx`, are **caller-saved** and may be modified by the called function.
>
> The return value is placed in register `%eax`, or in registers `%edx:%eax` for 64-bit values."
>
> **来源**：`reference-docs/abi386-4.pdf`, Page 37-38

> 📖 **栈布局**（i386 ABI, Figure 3-16, Page 40）
>
> ```
> +---------------------+
> | argument word N     |  ← [ebp + 4N + 8]
> +---------------------+
> | ...                 |
> +---------------------+
> | argument word 1     |  ← [ebp + 12]
> +---------------------+
> | argument word 0     |  ← [ebp + 8]
> +---------------------+
> | return address      |  ← [ebp + 4]
> +---------------------+
> | previous %ebp       |  ← [ebp]  (栈帧基址)
> +---------------------+
> | local variables     |  ← [ebp - N]
> +---------------------+
> ```

#### 参数传递规则

| 参数位置 | 传递方式 | 压栈顺序 |
|---------|---------|---------|
| **所有参数** | **栈** | **从右向左** |

**返回值**：
- `EAX`（32 位整数）
- `EDX:EAX`（64 位整数，高 32 位在 EDX）

**栈清理**：
- **Caller 清理**（调用者负责）

#### 寄存器保存规则

| 类型 | 寄存器 | 谁负责保存？ |
|------|--------|------------|
| **Caller-saved** | `EAX, EDX, ECX` | 调用者保存（如需要） |
| **Callee-saved** | `EBX, ESI, EDI, EBP, ESP` | 被调用者保存（必须恢复） |

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

---

### 1.4 不同平台调用约定对比

> 📖 **权威引述**（Agner Fog, "Calling conventions", Table 5, Page 19）
>
> **Function calling conventions for different C++ compilers and operating systems**:

| 平台/编译器 | 参数传递（整数） | 参数传递（浮点） | 栈清理 | Red Zone |
|-----------|----------------|----------------|--------|----------|
| **64-bit Linux/BSD/Mac** | RDI, RSI, RDX, RCX, R8, R9, stack | XMM0-XMM7, stack | Caller | 有（128字节） |
| **64-bit Windows** | RCX, RDX, R8, R9, stack | XMM0-XMM3, stack | Caller | 无 |
| **32-bit Linux/BSD/Mac** | 栈（从右向左） | 栈（从右向左） | Caller | 无 |
| **32-bit Windows (cdecl)** | 栈（从右向左） | 栈（从右向左） | Caller | 无 |
| **32-bit Windows (stdcall)** | 栈（从右向左） | 栈（从右向左） | **Callee** | 无 |

**来源**：`reference-docs/agner_calling_conventions.pdf`, Table 5, Page 19

**关键差异**：
1. **64 位 Linux vs Windows**：
   - Linux：使用 6 个寄存器（RDI, RSI, RDX, RCX, R8, R9）
   - Windows：使用 4 个寄存器（RCX, RDX, R8, R9），且顺序不同
   - Linux 有 Red Zone（128 字节），Windows 有 Shadow Space（32 字节）

2. **32 位 cdecl vs stdcall**：
   - cdecl：调用者清理栈（Linux 标准）
   - stdcall：被调用者清理栈（Windows API 常用）

3. **为什么 Linux 内核需要 asmlinkage**：
   - GCC 可以用 `-mregparm=N` 启用寄存器传参优化
   - `asmlinkage` 强制使用栈传参，确保与汇编代码兼容
   - 在 x86-64 上，`asmlinkage` 通常是空宏（ABI 已定义寄存器传参）

---

### 1.5 调用约定的规范来源

**重要说明**：调用约定不是由处理器硬件定义的，而是软件层面的约定。

#### 规范层级

| 层级 | 文档类型 | 定义内容 | 示例 |
|------|---------|---------|------|
| **硬件层** | Intel SDM, AMD APM | 寄存器、指令、中断机制 | `CALL`, `RET`, `SYSCALL` 指令的行为 |
| **ABI 层** | System V ABI | 调用约定、链接格式 | 参数用哪些寄存器传递 |
| **实现层** | Linux 内核源码 | 具体实现与注解 | `asmlinkage` 宏定义 |

#### Intel SDM 的角色

**Intel SDM（Software Developer's Manual）提供**：
- ✅ 寄存器的定义和用途（RAX, RDI, RSI 等）
- ✅ 指令的行为（`CALL`, `RET`, `PUSH`, `POP`）
- ✅ 系统调用指令（`SYSCALL`, `SYSRET`）
- ✅ 中断和异常的硬件机制（IDT, 错误码压栈）

**Intel SDM 不提供**：
- ❌ 哪个寄存器传递第几个参数（这是 ABI 定义的）
- ❌ 谁负责清理栈（这是调用约定的一部分）
- ❌ 函数属性的使用方法（这是编译器和内核实现）

**相关章节**（参考 Intel SDM Volume 3A）：
- **Volume 1, Chapter 3**：基本执行环境（寄存器）
- **Volume 2**：指令集参考（`CALL`, `RET`, `SYSCALL` 等）
- **Volume 3, Chapter 6**：中断和异常处理
  - 6.12 节：异常和中断处理
  - 6.14 节：错误码（Error Code）
  - 说明了哪些异常会压入错误码，这影响了中断处理函数的调用约定

**参考**：
- Intel SDM：https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html
- 本地文档：`~/Desktop/64-ia-32-architectures-software-developer-vol-3a-part-1-manual.pdf`
- Linux 内核文档：`Documentation/arch/x86/entry_64.rst` 明确引用了 Intel SDM Volume 3, Chapter 6

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

> 📖 **GCC 官方文档**（Common Function Attributes - externally_visible）
>
> "This attribute, attached to a global variable or function, **nullifies the effect of the `-fwhole-program` command-line option**, so the object remains visible outside the current compilation unit.
>
> If `-fwhole-program` is used together with `-flto` and `gold` is used as the linker plugin, `externally_visible` attributes are automatically added to functions (not variable yet due to a current gold issue) that are accessed outside of LTO objects according to resolution file produced by gold. For other linkers that cannot generate resolution file, explicit `externally_visible` attributes are still necessary."
>
> **来源**：`reference-docs/gcc_common_function_attributes.html` (GCC Documentation)

**作用**：
- ✅ **防止 LTO（Link Time Optimization）优化掉符号**
- ✅ 确保符号在**链接时可见**
- ✅ 即使函数看起来"未使用"，也不会被删除
- ✅ 在使用 `-fwhole-program` 优化时保留符号

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

> 📖 **GCC 官方文档**（Common Function Attributes - noreturn）
>
> "A few standard library functions, such as `abort` and `exit`, cannot return. GCC knows this automatically. Some programs define their own functions that never return. You can declare them `noreturn` to tell the compiler this fact."
>
> **示例**：
> ```c
> void fatal () __attribute__ ((noreturn));
>
> void
> fatal (/* ... */)
> {
>   /* ... */ /* Print error message. */ /* ... */
>   exit (1);
> }
> ```
>
> **来源**：`reference-docs/gcc_common_function_attributes.html` (GCC Documentation)

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

> 📖 **GCC 官方文档**（Common Function Attributes - cold）
>
> "The `cold` attribute on functions is used to inform the compiler that the function is **unlikely to be executed**. The function is **optimized for size rather than speed** and on many targets it is placed into a **special subsection of the text section** so all cold functions appear close together, **improving code locality of non-cold parts of program**. The paths leading to calls of cold functions within code are **marked as unlikely by the branch prediction mechanism**. It is thus useful to mark functions used to handle unlikely conditions, such as `perror`, as cold to improve optimization of hot functions that do call marked functions in rare occasions.
>
> When profile feedback is available, via `-fprofile-use`, cold functions are automatically detected and this attribute is ignored."
>
> **来源**：`reference-docs/gcc_common_function_attributes.html` (GCC Documentation)

**作用**：
- 告诉编译器这段代码**很少执行**
- 编译器将其**优化为小代码体积而非高速度**
- 编译器可能将其移到代码段末尾（特殊子段）
- 提高**热代码的缓存命中率**（代码局部性）
- 分支预测器将调用路径标记为"不太可能"

**使用场景**：
- 错误处理路径
- 初始化代码（`__init` 自动包含）

---

#### __used - 防止优化删除

```c
#define __used  __attribute__((__used__))
```

> 📖 **GCC 官方文档**（Common Function Attributes - used）
>
> "This attribute, attached to a function, means that **code must be emitted for the function even if it appears that the function is not referenced**. This is useful, for example, when the function is referenced only in inline assembly.
>
> When applied to a member function of a C++ class template, the attribute also means that the function is instantiated if the class itself is instantiated."
>
> **来源**：`reference-docs/gcc_common_function_attributes.html` (GCC Documentation)

**作用**：
- 即使符号看起来"未使用"，也**必须生成代码**
- 类似 `__visible`，但侧重于代码生成而非链接可见性

**使用场景**：
- 仅在内联汇编中引用的函数
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

#### 函数修饰符定义

**调用约定（asmlinkage）**：
- `include/linux/linkage.h:15-23` - 通用 asmlinkage 定义
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

- `arch/x86/include/asm/linkage.h:19-21` - **x86-32 专用定义（关键！）**
  ```c
  #ifdef CONFIG_X86_32
  #define asmlinkage CPP_ASMLINKAGE __attribute__((regparm(0)))
  #endif /* CONFIG_X86_32 */
  ```
  > 说明：`regparm(0)` 强制使用栈传参，这是 x86-32 上与汇编代码兼容的关键

**其他修饰符**：
- `include/linux/compiler_attributes.h` - `__visible`, `__noreturn`, `__cold`, `__used` 等
  - 第 149 行：`#define __visible  __attribute__((__externally_visible__))`
  - 第 262 行：`#define __noreturn  __attribute__((__noreturn__))`
- `include/linux/init.h:54` - `__init`, `__initdata`, `__exit` 等
  ```c
  #define __init  __section(".init.text") __cold __latent_entropy  \
                  __noinitretpoline __no_sanitize_coverage
  ```

#### 实际使用示例

**内核入口函数**：
- `arch/x86/kernel/head64.c:219` - `x86_64_start_kernel`
  ```c
  asmlinkage __visible void __init __noreturn x86_64_start_kernel(char *real_mode_data)
  ```

- `init/main.c:897-898` - `start_kernel`（**最关键的示例**）
  ```c
  asmlinkage __visible __init __no_sanitize_address __noreturn __no_stack_protector
  void start_kernel(void)
  ```
  > 这是内核的第一个 C 函数，展示了几乎所有关键修饰符的组合使用

**系统调用与中断**：
- `arch/x86/entry/syscall_64.c` - `sys_call_table` 系统调用表
- `arch/x86/kernel/traps.c` - 异常处理函数（`do_page_fault` 等）
- `arch/x86/entry/entry_64.S` - 汇编入口点

**汇编符号注解**：
- `include/linux/linkage.h:78-353` - `SYM_FUNC_START`, `SYM_CODE_START` 等宏定义
- `arch/x86/include/asm/linkage.h:115-154` - x86 特定的符号注解

#### 内核文档注释

**关于调用约定的重要注释**：

1. **linkage.h 中关于 asmlinkage_protect 的注释**（`include/linux/linkage.h:51-63`）：
   ```c
   /*
    * This is used by architectures to keep arguments on the stack
    * untouched by the compiler by keeping them live until the end.
    * The argument stack may be owned by the assembly-language
    * caller, not the callee, and gcc doesn't always understand
    * that.
    *
    * We have the return value, and a maximum of six arguments.
    */
   ```
   > 说明了为什么需要特殊处理汇编调用的 C 函数的参数

2. **汇编注解的用途**（`include/linux/linkage.h:176-191`）：
   ```c
   /*
    * FUNC -- C-like functions (proper stack frame etc.)
    * CODE -- non-C code (e.g. irq handlers with different, special stack etc.)
    *
    * Objtool validates stack for FUNC, but not for CODE.
    * Objtool generates debug info for both FUNC & CODE, but needs special
    * annotations for each CODE's start (to describe the actual stack frame).
    */
   ```
   > 区分了标准 C 调用约定（FUNC）和特殊调用约定（CODE，如中断处理函数）

### 7.2 ABI 规范文档（已下载到本地）

**说明**：调用约定（Calling Convention）不是由处理器手册（Intel SDM）定义的，而是由操作系统和编译器层面的 **ABI（Application Binary Interface）规范** 定义的。

> 📁 **本地参考文档目录**：`reference-docs/`

#### x86-64 System V ABI（Linux/Unix 标准）

**官方规范**：
- 在线版本：https://refspecs.linuxfoundation.org/elf/x86_64-abi-0.99.pdf
- **本地副本**：`reference-docs/x86_64-abi-0.99.pdf` (557 KB)
- GitHub 镜像：https://github.com/hjl-tools/x86-psABI/wiki/x86-64-psABI-1.0.pdf

**核心章节**：
- **第 3 章：低级系统信息**（Low-Level System Information）
  - 第 3.1 节：机器接口（Machine Interface）
  - 第 3.2 节：**函数调用序列**（Function Calling Sequence）
  - **Figure 3.4: Register Usage**（寄存器使用表）— 被本文档 1.2 节引用
- **第 3.3 节**：操作系统接口

**关键内容**：
- ✅ 寄存器使用和保存约定（Caller-saved vs Callee-saved）
- ✅ 参数传递规则（前 6 个整数参数用寄存器，浮点用 XMM0-7）
- ✅ 返回值约定（RAX, XMM0）
- ✅ 栈对齐要求（16 字节对齐）
- ✅ Red Zone（128 字节临时区域）

#### i386 System V ABI（x86-32 标准）

**官方规范**：
- 在线版本：https://refspecs.linuxbase.org/elf/abi386-4.pdf
- **本地副本**：`reference-docs/abi386-4.pdf` (1.0 MB)

**核心章节**：
- **第 3 章：低级系统信息**
  - 第 3.4 节：**函数调用序列**（Function Calling Sequence, Page 37-42）
  - **Figure 3-16: Stack Frame**（栈帧布局图）— 被本文档 1.3 节引用

**关键内容**：
- ✅ cdecl 调用约定（所有参数压栈，从右向左）
- ✅ 调用者清理栈（Caller cleans up）
- ✅ 寄存器保存规则（EBP, EBX, ESI, EDI, ESP 必须保存）
- ✅ 栈帧结构（EBP 作为帧指针）

#### Agner Fog's Calling Conventions（性能分析视角）

**官方文档**：
- 在线版本：https://www.agner.org/optimize/calling_conventions.pdf
- **本地副本**：`reference-docs/agner_calling_conventions.pdf` (1.0 MB)
- 版本：2023年7月1日更新

**核心章节**：
- **第 7 章：64 位系统上的调用约定**（Calling conventions for 64-bit systems, Page 17-22）
  - **Table 5: Function calling conventions for different compilers and OS**（被本文档 1.4 节引用）
  - Linux vs Windows 调用约定对比
  - Red Zone vs Shadow Space 对比

**关键内容**：
- ✅ 多平台调用约定对比（Linux, Windows, Mac, BSD）
- ✅ 不同编译器的差异（GCC, Clang, MSVC, ICC）
- ✅ 性能优化建议
- ✅ 特殊约定（如 `-mregparm` 优化）

#### 其他参考

- **OSDev Wiki - Calling Conventions**: https://wiki.osdev.org/Calling_Conventions
  - 系统编程视角的调用约定总结
  - 多种架构和约定的对比

### 7.3 GCC 文档（已下载到本地）

**函数属性**：
- 在线版本：https://gcc.gnu.org/onlinedocs/gcc/Function-Attributes.html
- **本地副本**：
  - `reference-docs/gcc_function_attributes.html` (9.9 KB) — 函数属性索引页
  - `reference-docs/gcc_common_function_attributes.html` (127 KB) — 通用函数属性详细说明

**关键属性说明**（已被本文档引用）：
- `__attribute__((__noreturn__))` — 2.4 节引用
- `__attribute__((__externally_visible__))` — 2.2 节引用
- `__attribute__((__cold__))` — 2.7 节引用
- `__attribute__((__used__))` — 2.7 节引用
- `__attribute__((regparm(N)))` — 2.1 节提及（x86-32 专用）
- `__attribute__((__no_sanitize_address__))` — 2.5 节
- `__attribute__((__no_stack_protector__))` — 2.6 节

**其他重要属性**：
- `__attribute__((__section__("name")))` — 指定 ELF 段
- `__attribute__((__aligned__(N)))` — 对齐要求
- `__attribute__((__packed__))` — 紧凑布局
- `__attribute__((__weak__))` — 弱符号

### 7.4 Intel 处理器手册

**说明**：虽然 Intel SDM 不定义调用约定，但提供了底层硬件机制的权威说明。

**Intel® 64 and IA-32 Architectures Software Developer's Manual**：
- **Volume 1: Basic Architecture**
  - 第 3 章：基本执行环境（寄存器、数据类型）
  - 第 5 章：指令集概述
- **Volume 2: Instruction Set Reference**
  - `CALL`、`RET`、`PUSH`、`POP` 等指令详解
  - `SYSCALL`/`SYSRET` 系统调用指令
- **Volume 3A: System Programming Guide, Part 1**
  - 第 6 章：中断和异常处理
  - 中断门、陷阱门的参数传递机制

**下载地址**：
- https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html
- 本地参考：`~/Desktop/64-ia-32-architectures-software-developer-vol-3a-part-1-manual.pdf`

### 7.5 项目文档

**相关主题**：
- [LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md) - start_kernel 详解
- [LINUX_MEMORY_MANAGEMENT_CODE_GUIDE.md](LINUX_MEMORY_MANAGEMENT_CODE_GUIDE.md) - x86_64_start_kernel 内存初始化
- [LINUX_KERNEL_SYSCALL_INIT.md](LINUX_KERNEL_SYSCALL_INIT.md) - 系统调用表与 entry_SYSCALL_64
- [LINUX_KERNEL_IDT_EVOLUTION.md](LINUX_KERNEL_IDT_EVOLUTION.md) - 异常处理函数

**汇编交互**：
- [GRUB_KERNEL_LOADING.md](GRUB_KERNEL_LOADING.md) - GRUB 如何跳转到内核
- [LINUX_INTERRUPT_GUIDE.md](LINUX_INTERRUPT_GUIDE.md) - 中断处理流程

### 7.6 Linux 内核官方文档

**汇编与调用约定**：

- **Documentation/core-api/asm-annotations.rst**（源码：`~/works/linux/Documentation/core-api/asm-annotations.rst`）
  - **SYM_FUNC_\* vs SYM_CODE_\* 的区别**（第 76-94 行）：
    - `SYM_FUNC_*`：标准 C 调用约定的函数（栈帧规范）
    - `SYM_CODE_*`：特殊调用约定的代码（中断处理、trampoline、启动代码）
  - 汇编符号的正确注解方法
  - 与 objtool 工具的集成

- **Documentation/arch/x86/entry_64.rst**（源码：`~/works/linux/Documentation/arch/x86/entry_64.rst`）
  - **不同入口点的调用约定**（第 44-51 行）：
    ```
    The different x86-64 entries have different calling conventions.
    The syscall and sysenter instructions have their own peculiar
    calling conventions. Some of the IDT entries push an error code
    onto the stack; others don't.
    ```
  - 引用了 **AMD APM Volume 2, Chapter 8** 和 **Intel SDM Volume 3, Chapter 6**
  - 系统调用、中断、异常处理的入口机制
  - SWAPGS 指令与栈切换

**内核通用文档**：
- https://www.kernel.org/doc/html/latest/
  - **Documentation/process/coding-style.rst** - 内核编码风格
  - **Documentation/kbuild/makefiles.rst** - 构建系统
  - **Documentation/arch/x86/boot.rst** - x86-64 启动协议（原路径：`x86/x86_64/boot.rst`）

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

## 八、扩展阅读：权威参考文档

本节列出本文档引用的所有权威规范，包括原始下载链接、主要内容概述和推荐阅读目标。所有文档已下载到 `reference-docs/` 目录，可离线查阅。

### 8.1 ABI 规范文档（核心必读）

#### 📘 System V ABI - AMD64 Architecture Processor Supplement

**官方链接**：https://refspecs.linuxfoundation.org/elf/x86_64-abi-0.99.pdf

**文档概述**：
这是定义 Linux/Unix 64 位系统调用约定的**权威规范**。所有 Linux x86-64 程序的函数调用、参数传递、寄存器使用都必须遵循此规范。

**主要内容**：
- **第 3 章：低级系统信息**（Low-Level System Information）
  - 3.1 节：机器接口（寄存器、数据类型）
  - 3.2 节：**函数调用序列**（Function Calling Sequence）⭐ 核心章节
    - Figure 3.4: Register Usage（寄存器使用表）
    - 参数传递规则（前 6 个参数用寄存器）
    - 返回值约定（RAX, XMM0）
    - Caller-saved vs Callee-saved 寄存器
  - 3.3 节：操作系统接口
- **第 3.4 节**：栈帧布局（Stack Frame）
  - Red Zone（128 字节临时区域）
  - 栈对齐要求（16 字节）

**阅读目标**：
- ✅ **初学者**：阅读 3.2 节和 Figure 3.4，理解 x86-64 如何传递参数
- ✅ **进阶**：理解 Red Zone 机制，为什么内核代码需要禁用它
- ✅ **高级**：对比不同 ABI（Windows vs Linux）的差异

**本文档引用位置**：1.2 节（寄存器使用表）

---

#### 📘 System V ABI - Intel386 Architecture Processor Supplement

**官方链接**：https://refspecs.linuxbase.org/elf/abi386-4.pdf

**文档概述**：
定义 Linux/Unix 32 位系统调用约定的**权威规范**。虽然现代系统主要使用 64 位，但理解 32 位 cdecl 约定有助于：
- 理解 `asmlinkage` 的作用（强制栈传参）
- 理解为什么 32 位和 64 位调用约定差异巨大
- 分析兼容层（如 ia32_sys_call_table）

**主要内容**：
- **第 3 章：低级系统信息**
  - 3.4 节：**函数调用序列**（Page 37-42）⭐ 核心章节
    - Figure 3-16: Stack Frame（栈帧布局图）
    - cdecl 约定详解（所有参数压栈，从右向左）
    - 调用者清理栈（Caller cleans up）
  - 3.5 节：寄存器使用
    - Callee-saved: EBP, EBX, ESI, EDI, ESP
    - Caller-saved: EAX, EDX, ECX

**阅读目标**：
- ✅ **初学者**：阅读 Figure 3-16，理解 32 位栈帧结构
- ✅ **进阶**：对比 x86-64，理解为什么寄存器传参更高效
- ✅ **高级**：研究 Linux 内核如何支持 32 位兼容模式

**本文档引用位置**：1.3 节（栈帧布局图、cdecl 约定说明）

---

### 8.2 性能分析文档（跨平台对比）

#### 📙 Calling Conventions for Different C++ Compilers and Operating Systems

**作者**：Agner Fog（丹麦技术大学教授，性能优化专家）
**官方链接**：https://www.agner.org/optimize/calling_conventions.pdf
**版本**：2023年7月1日更新

**文档概述**：
这是一份从**性能优化角度**分析调用约定的技术文档，对比了 Linux、Windows、Mac、BSD 等多个平台的调用约定差异。不同于 ABI 规范的"规定性"，本文档从"为什么这样设计"的角度解释调用约定。

**主要内容**：
- **第 7 章：64 位系统调用约定**（Page 17-22）⭐ 核心章节
  - Table 5: Function calling conventions comparison（多平台对比表）
  - Linux vs Windows vs Mac 的参数传递差异
  - Red Zone（Linux）vs Shadow Space（Windows）
  - 性能影响分析
- **第 5 章**：32 位调用约定（cdecl, stdcall, fastcall）
- **第 9 章**：优化建议

**阅读目标**：
- ✅ **初学者**：阅读 Table 5，快速了解不同平台的调用约定差异
- ✅ **进阶**：理解 Red Zone 的性能优势（无需调整栈指针）
- ✅ **高级**：如何编写跨平台代码（处理调用约定差异）

**本文档引用位置**：
- 1.2 节（Red Zone 说明）
- 1.4 节（调用约定对比表）

**为什么阅读此文档**：
- ABI 规范告诉你"是什么"，Agner Fog 告诉你"为什么"
- 包含大量性能测试数据和优化技巧
- 作者是 CPU 微架构研究专家，视角独特

---

### 8.3 GCC 编译器文档（函数属性参考）

#### 📗 GCC Function Attributes

**官方链接**：https://gcc.gnu.org/onlinedocs/gcc/Function-Attributes.html

**文档概述**：
GCC 编译器官方文档，详细说明了所有函数属性（`__attribute__`）的语法、语义和用法。

**主要内容**：
- **Common Function Attributes**（通用函数属性）⭐ 核心章节
  - `noreturn` — 永不返回函数
  - `externally_visible` — 防止 LTO 优化删除
  - `cold` — 冷代码标记（优化代码局部性）
  - `used` — 强制生成代码（即使看似未使用）
  - `section("name")` — 指定 ELF 段
  - `aligned(N)` — 对齐要求
- **x86 Function Attributes**（x86 特定属性）
  - `regparm(N)` — 指定寄存器传参数量
  - `fastcall`, `thiscall`, `ms_abi` 等调用约定

**阅读目标**：
- ✅ **初学者**：查询不熟悉的属性（如 `__noreturn`）
- ✅ **进阶**：理解属性如何影响代码生成
- ✅ **高级**：使用属性进行性能优化

**本文档引用位置**：
- 2.2 节（`externally_visible`）
- 2.4 节（`noreturn`）
- 2.7 节（`cold`, `used`）

**使用建议**：
- 配合本文档使用：先读本文档理解概念，再查 GCC 文档了解细节
- HTML 版本支持搜索，快速定位属性说明
- 可下载 PDF 版本：https://gcc.gnu.org/onlinedocs/gcc.pdf

---

### 8.4 Intel 处理器手册（硬件机制参考）

#### 📕 Intel® 64 and IA-32 Architectures Software Developer's Manual

**官方链接**：https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html

**重要说明**：Intel SDM **不定义调用约定**（调用约定由 ABI 规范定义），但提供了底层硬件机制的权威说明。

**相关卷册**：
- **Volume 1: Basic Architecture**
  - 第 3 章：基本执行环境（寄存器定义、数据类型）
  - 第 5 章：指令集概述
- **Volume 2: Instruction Set Reference**
  - `CALL`, `RET`, `PUSH`, `POP` 指令详解
  - `SYSCALL`, `SYSRET` 系统调用指令
  - `INT`, `IRET` 中断指令
- **Volume 3A: System Programming Guide, Part 1**
  - 第 6 章：中断和异常处理 ⭐ 与调用约定相关
    - 6.12 节：异常和中断处理
    - 6.14 节：错误码（Error Code）
    - 说明哪些异常会压入错误码（影响中断处理函数的调用约定）

**阅读目标**：
- ✅ **理解硬件行为**：中断时 CPU 如何压栈、如何传递错误码
- ✅ **指令级优化**：`CALL` vs `JMP`，`RET` 的微架构行为
- ✅ **系统编程**：如何使用 `SYSCALL` 指令（内核入口）

**与调用约定的关系**：
```
硬件层（Intel SDM）→ 定义寄存器和指令行为
    ↓
ABI 层（System V ABI）→ 规定如何使用这些寄存器传参
    ↓
实现层（Linux 内核）→ 通过 asmlinkage 等宏实现约定
```

**本文档提及位置**：
- 1.5 节（调用约定的规范来源）
- 7.4 节（Intel 处理器手册）

---

### 8.5 Linux 内核官方文档

#### 📖 Documentation/core-api/asm-annotations.rst

**在线链接**：https://www.kernel.org/doc/html/latest/core-api/asm-annotations.html

**内容概述**：
说明 Linux 内核汇编代码的符号注解规范（`SYM_FUNC_START`, `SYM_CODE_START` 等宏）。

**阅读目标**：
- ✅ 理解 `SYM_FUNC_*`（标准 C 调用约定）vs `SYM_CODE_*`（特殊调用约定）
- ✅ 学习如何正确注解汇编代码
- ✅ 理解 objtool 工具的作用

---

#### 📖 Documentation/arch/x86/entry_64.rst

**在线链接**：https://www.kernel.org/doc/html/latest/arch/x86/entry_64.html

**内容概述**：
详细说明 x86-64 内核入口点（系统调用、中断、异常）的实现机制。

**关键引述**：
> "The different x86-64 entries have different calling conventions. The syscall and sysenter instructions have their own peculiar calling conventions."

**阅读目标**：
- ✅ 理解系统调用入口（`entry_SYSCALL_64`）的调用约定
- ✅ 理解中断/异常处理的栈切换机制
- ✅ 理解 SWAPGS 指令的作用

---

### 8.6 阅读路径建议

#### 🎯 路径 1：快速入门（30分钟）

1. **阅读本文档 1.1-1.4 节**（理解调用约定概念）
2. **查看 x86_64-abi-0.99.pdf Figure 3.4**（记住寄存器使用规则）
3. **查看 Agner Fog Table 5**（了解平台差异）
4. **完成**：能够理解 Linux 内核函数签名中的 `asmlinkage`

---

#### 🎯 路径 2：深入理解（2小时）

1. **阅读 x86_64-abi-0.99.pdf 第 3 章**（完整理解 64 位调用约定）
2. **阅读 abi386-4.pdf 第 3.4 节**（对比 32 位调用约定）
3. **阅读本文档第 2 章**（理解函数修饰符）
4. **查阅 GCC 文档**（查询不熟悉的属性）
5. **完成**：能够正确使用函数修饰符编写内核代码

---

#### 🎯 路径 3：内核开发者（1周）

1. **通读本文档所有章节**
2. **精读 x86_64-abi-0.99.pdf 和 abi386-4.pdf**
3. **阅读 Agner Fog 全文**（理解性能优化）
4. **阅读 Linux 内核源码**：
   - `include/linux/linkage.h`
   - `arch/x86/include/asm/linkage.h`
   - `init/main.c:start_kernel`
5. **阅读 Intel SDM Volume 3A 第 6 章**（中断机制）
6. **完成**：能够编写高质量的内核汇编/C 混合代码

---

### 8.7 本地文档清单

所有参考文档已下载到 `reference-docs/` 目录：

| 文件名 | 大小 | 原始链接 |
|-------|------|---------|
| `x86_64-abi-0.99.pdf` | 557 KB | https://refspecs.linuxfoundation.org/elf/x86_64-abi-0.99.pdf |
| `abi386-4.pdf` | 1.0 MB | https://refspecs.linuxbase.org/elf/abi386-4.pdf |
| `agner_calling_conventions.pdf` | 1.0 MB | https://www.agner.org/optimize/calling_conventions.pdf |
| `gcc_function_attributes.html` | 9.9 KB | https://gcc.gnu.org/onlinedocs/gcc/Function-Attributes.html |
| `gcc_common_function_attributes.html` | 127 KB | https://gcc.gnu.org/onlinedocs/gcc/Common-Function-Attributes.html |

---

**文档版本**：v2.0 (2026-02-15)
**维护说明**：本文档基于 Linux v6.x 内核源码，定义可能随内核版本变化。

**更新日志**：
- **v2.0 (2026-02-15)**：
  - ✅ 添加权威规范引述（ABI、GCC、Agner Fog）
  - ✅ 下载所有参考文档到本地（`reference-docs/`）
  - ✅ 新增第 8 章：扩展阅读指南
  - ✅ 新增 1.4 节：不同平台调用约定对比
  - ✅ 新增 1.5 节：调用约定的规范来源
- **v1.0**：初始版本，基于内核源码分析
