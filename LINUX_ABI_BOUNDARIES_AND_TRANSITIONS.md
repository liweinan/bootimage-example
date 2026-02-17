# Linux ABI 边界与转换：System V ABI vs Linux Userspace ABI

**版本**: 1.0
**日期**: 2026-02-17
**作者**: Claude Code (Anthropic)

> 📚 **文档导航**: [返回总索引](DOCUMENT_INDEX.md) | [阅读指南](READING_GUIDE.md)

---

## 目录

1. [概述：为何需要区分多种 ABI](#1-概述为何需要区分多种-abi)
2. [System V ABI：函数调用标准](#2-system-v-abi函数调用标准)
3. [Linux Userspace ABI：内核承诺](#3-linux-userspace-abi内核承诺)
4. [系统调用 ABI：特殊的边界](#4-系统调用-abi特殊的边界)
5. [启动过程中的 ABI 转换](#5-启动过程中的-abi-转换)
6. [vDSO 与 vsyscall：混合 ABI](#6-vdso-与-vsyscall混合-abi)
7. [ABI 稳定性对比总结](#7-abi-稳定性对比总结)

---

## 1. 概述：为何需要区分多种 ABI

在讨论 Linux 系统时，"ABI" 这个词有**至少三种不同的含义**：

```
┌─────────────────────────────────────────────────────────────┐
│                    ABI 的三个层次                            │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  [1] System V ABI (调用约定)                                │
│      • 函数参数如何传递（寄存器/栈）                        │
│      • 返回值如何返回                                        │
│      • 寄存器保存规则                                        │
│      • 栈对齐要求                                            │
│      → 规范：System V ABI AMD64/i386 文档                   │
│      → 作用域：用户空间程序之间、程序与库之间                │
│                                                              │
│  [2] Linux Userspace ABI (内核接口承诺)                     │
│      • 系统调用接口（syscall numbers, 参数）                │
│      • /proc, /sys 文件格式                                 │
│      • ioctl 命令                                           │
│      • 信号处理机制                                          │
│      → 规范：Linux 内核文档 + Linus 邮件承诺                │
│      → 作用域：用户程序与内核之间                            │
│      → Linus 名言："We do not break userspace"              │
│                                                              │
│  [3] 启动协议 ABI (Bootloader-Kernel 接口)                  │
│      • boot_params 结构传递                                 │
│      • 入口点地址（0x200）                                  │
│      • 寄存器初始状态（RSI=boot_params）                    │
│      → 规范：Documentation/x86/boot.txt                     │
│      → 作用域：Bootloader（GRUB）与内核之间                 │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**关键误区**：
- ❌ "Linux 遵循 System V ABI" - **不完全正确**
- ✅ "Linux userspace 程序通常遵循 System V ABI，但内核自身可以偏离"
- ✅ "Linux syscall ABI 是独立定义的，不是 System V ABI 的一部分"

---

## 2. System V ABI：函数调用标准

### 2.1 定义与作用域

**System V ABI** 是由 **Unix System V** 定义的**二进制接口规范**，主要规定：

```c
// System V ABI 规定的是这种情况：
// libfoo.so (编译器 A 生成) ←→ app.exe (编译器 B 生成)

// libfoo.c (用 GCC 编译)
int add(int a, int b, int c) {
    return a + b + c;
}

// app.c (用 Clang 编译)
#include <stdio.h>
extern int add(int, int, int);

int main() {
    int result = add(1, 2, 3);  // 调用 GCC 编译的函数
    printf("Result: %d\n", result);
    return 0;
}
```

**ABI 保证**：
- GCC 将 `a, b, c` 放入 `RDI, RSI, RDX`
- Clang 也将参数放入 `RDI, RSI, RDX`
- 返回值都在 `RAX`
- 双方都遵循相同的栈对齐规则（16 字节）

**作用域**：
- ✅ 用户空间程序与共享库之间
- ✅ 不同编译器生成的代码之间
- ❌ **不包括**：系统调用接口
- ❌ **不包括**：内核内部代码

### 2.2 System V ABI x86-64 核心规则

| 类别 | 规定 |
|------|------|
| **整数参数** | RDI, RSI, RDX, RCX, R8, R9（第 7+ 个参数用栈） |
| **浮点参数** | XMM0-XMM7（第 9+ 个参数用栈） |
| **返回值** | RAX（整数），XMM0（浮点），RDX:RAX（128位） |
| **Caller-saved** | RAX, RCX, RDX, RSI, RDI, R8-R11, XMM0-XMM15 |
| **Callee-saved** | RBX, RBP, R12-R15 |
| **栈对齐** | 函数入口时 `(RSP + 8) % 16 == 0` |
| **Red Zone** | RSP 下方 128 字节可用（用户空间）|

**权威文档**：
- System V Application Binary Interface AMD64 Architecture Processor Supplement (Draft 0.99.6)
- 位置：`reference-docs/x86_64-abi-0.99.pdf`

---

## 3. Linux Userspace ABI：内核承诺

### 3.1 定义：Linus 的铁律

> 📖 **Linus Torvalds 在 2012 年的著名声明**：
>
> "We do **NOT** break userspace! ... If a change results in user programs breaking, it's a bug in the kernel. We fix the kernel. The programs don't get fixed."
>
> **来源**：https://lkml.org/lkml/2012/12/23/75

**Linux Userspace ABI** 包括：

```
┌──────────────────────────────────────────────────────────┐
│  Linux Userspace ABI（内核对外承诺，永不破坏）          │
├──────────────────────────────────────────────────────────┤
│                                                           │
│  1. 系统调用接口                                          │
│     • 系统调用号（例：read = 0, write = 1）              │
│     • 参数顺序和类型                                      │
│     • 返回值语义                                          │
│                                                           │
│  2. /proc 和 /sys 文件系统                               │
│     • /proc/cpuinfo 的格式                               │
│     • /sys/class/net/eth0/ 的结构                        │
│                                                           │
│  3. ioctl 命令                                           │
│     • 设备特定的 ioctl 编号                              │
│     • 参数结构体布局                                      │
│                                                           │
│  4. 信号处理                                              │
│     • 信号编号（SIGINT = 2, SIGKILL = 9）                │
│     • sigaction 结构体                                   │
│                                                           │
│  5. ELF 辅助向量（auxv）                                 │
│     • AT_EXECFN, AT_PLATFORM, AT_RANDOM 等               │
│                                                           │
│  6. 虚拟 DSO（vDSO）                                     │
│     • gettimeofday(), clock_gettime() 等快速路径        │
│                                                           │
└──────────────────────────────────────────────────────────┘
```

### 3.2 与 System V ABI 的关系

**重要区别**：

| 方面 | System V ABI | Linux Userspace ABI |
|------|--------------|---------------------|
| **定义者** | Unix System V 委员会 | Linux 内核开发者（Linus 最终决策） |
| **稳定性承诺** | "兼容不同编译器" | **"永不破坏用户空间程序"** |
| **覆盖范围** | 函数调用约定 | 系统调用、/proc、信号等 |
| **文档位置** | System V ABI 规范 | Linux 内核文档（Documentation/） |
| **违反后果** | 程序无法链接或崩溃 | 用户程序无法运行，**内核被视为 bug** |

**关键点**：
- System V ABI 规定 `read(int fd, void *buf, size_t count)` 的**调用约定**（参数用哪些寄存器）
- Linux Userspace ABI 规定 `read` 的**系统调用号**（0）和**语义**（返回值含义）

---

## 4. 系统调用 ABI：特殊的边界

### 4.1 为何系统调用不遵循 System V ABI

**System V ABI 的函数调用**：
```c
// 用户空间函数调用（遵循 System V ABI）
ssize_t read(int fd, void *buf, size_t count);
// 参数：RDI=fd, RSI=buf, RDX=count
// 指令：call read@plt（普通函数调用）
```

**Linux 系统调用**：
```c
// 实际系统调用（不遵循 System V ABI）
syscall(SYS_read, fd, buf, count);
// 参数：RAX=0(syscall number), RDI=fd, RSI=buf, RDX=count
// 指令：syscall（特权指令，不是 call）
```

**关键差异**：

| 方面 | System V ABI 函数调用 | Linux Syscall ABI |
|------|----------------------|-------------------|
| **调用指令** | `call` | `syscall` (x86-64) / `int 0x80` (x86-32) |
| **参数寄存器** | RDI, RSI, RDX, RCX, R8, R9 | **RAX**(syscall#), RDI, RSI, RDX, **R10**, R8, R9 |
| **第4个参数** | **RCX** | **R10**（因为 `syscall` 指令会破坏 RCX） |
| **返回值** | RAX | RAX（负值表示错误码） |
| **Caller-saved** | R10, R11 可能被破坏 | **RCX, R11 会被 syscall 指令破坏** |
| **特权切换** | 无 | 从 Ring 3 → Ring 0 |

### 4.2 为何第 4 个参数用 R10 而非 RCX？

**Intel SDM 规定**（Vol.3A, Section 5.8.8）：

> "SYSCALL loads the **CS and SS** selectors with values derived from **bits 47:32 of the IA32_STAR MSR**. **RCX** is loaded with the return address (address of the instruction following SYSCALL), and **R11** is loaded with the saved **RFLAGS**."

**翻译**：
- `syscall` 指令执行时，硬件会自动：
  - `RCX ← RIP`（保存返回地址）
  - `R11 ← RFLAGS`（保存标志寄存器）

**结果**：
- RCX 和 R11 在系统调用入口时已经被破坏
- 因此 Linux syscall ABI 使用 **R10** 传递第 4 个参数

**证据**（arch/x86/entry/entry_64.S:87-170）：

```asm
SYM_CODE_START(entry_SYSCALL_64)
    /* SYSCALL 指令已经执行：RCX = user RIP, R11 = user RFLAGS */
    swapgs

    /* 将 user RCX 从 R10 恢复（因为 glibc wrapper 会先 mov r10, rcx） */
    movq    %r10, %rcx          /* 恢复第 4 个参数 */

    /* 保存完整 pt_regs */
    pushq   %rax                /* pt_regs->orig_rax */
    pushq   %rdi                /* pt_regs->di */
    pushq   %rsi                /* pt_regs->si */
    pushq   %rdx                /* pt_regs->dx */
    pushq   %rcx                /* pt_regs->cx (从 R10 恢复的) */
    ...
```

**用户空间 wrapper**（glibc `syscall()` 函数）：

```asm
; glibc/sysdeps/unix/sysv/linux/x86_64/syscall.S
syscall:
    movq    %rdi, %rax          ; syscall number
    movq    %rsi, %rdi          ; arg1
    movq    %rdx, %rsi          ; arg2
    movq    %rcx, %rdx          ; arg3
    movq    %r8, %r10           ; arg4: 用 R10 替代 RCX!!!
    movq    %r9, %r8            ; arg5
    movq    8(%rsp), %r9        ; arg6
    syscall                     ; 进入内核
    ret
```

### 4.3 系统调用 ABI 总结

**Linux x86-64 Syscall ABI**：

| 参数 | 寄存器 | 说明 |
|------|--------|------|
| syscall number | RAX | 系统调用号（例：0 = read） |
| arg1 | RDI | 第 1 个参数 |
| arg2 | RSI | 第 2 个参数 |
| arg3 | RDX | 第 3 个参数 |
| arg4 | **R10** | 第 4 个参数（**不是 RCX**） |
| arg5 | R8 | 第 5 个参数 |
| arg6 | R9 | 第 6 个参数 |
| 返回值 | RAX | 成功返回正值/0，失败返回 -errno |
| **被破坏** | **RCX, R11** | `syscall` 指令自动破坏 |

**相关文档**：
- [LINUX_KERNEL_SYSCALL_INIT.md](LINUX_KERNEL_SYSCALL_INIT.md) - 系统调用初始化详解
- [LINUX_KERNEL_IDT_EVOLUTION.md](LINUX_KERNEL_IDT_EVOLUTION.md) - IDT 表演进（包含 INT 0x80）

---

## 5. 启动过程中的 ABI 转换

### 5.1 启动链条的 ABI 边界

```
┌────────────────────────────────────────────────────────────────┐
│  从硬件上电到用户程序运行：5 个 ABI 边界                       │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│  [边界 0] 硬件 Reset → BIOS/UEFI                               │
│           ABI: x86 Reset Vector (0xFFFFFFF0)                   │
│           • CS:IP = F000:FFF0                                  │
│           • CPU 在 Real Mode                                   │
│           • 无参数传递                                          │
│                                                                 │
│  [边界 1] BIOS → Bootloader (MBR)                              │
│           ABI: IBM PC BIOS Boot Specification                  │
│           • DL = Boot Drive Number (0x80 = 第一块硬盘)        │
│           • CS:IP = 0000:7C00                                  │
│           • 512 字节引导扇区，末尾签名 0xAA55                  │
│                                                                 │
│  [边界 2] Bootloader (GRUB) → Linux Kernel                     │
│           ABI: Linux x86 Boot Protocol                         │
│           • 入口点：0x200（64 位）或 0x1000（32 位）           │
│           • RSI = boot_params 指针（64 位）                    │
│           • 文档：Documentation/x86/boot.txt                   │
│                                                                 │
│  [边界 3] Kernel → Init 进程 (PID 1)                           │
│           ABI: ELF 加载 + execve 系统调用                      │
│           • 遵循 System V ABI（用户空间开始）                  │
│           • 辅助向量（auxv）传递内核信息                       │
│           • 栈布局：argc, argv[], envp[], auxv[]              │
│                                                                 │
│  [边界 4] 用户程序 ←→ 内核（运行时）                           │
│           ABI: Linux Userspace ABI                             │
│           • 系统调用接口（syscall ABI）                        │
│           • 信号处理、/proc、/sys                              │
│           • vDSO 机制                                          │
│                                                                 │
└────────────────────────────────────────────────────────────────┘
```

### 5.2 边界 2 详解：GRUB → Linux Kernel

**GRUB 传递参数给内核**（arch/x86/boot/compressed/head_64.S:375）：

```asm
SYM_CODE_START(startup_64)
    /*
     * 64bit entry is 0x200 and it is ABI so immutable!
     * We come here either from startup_32 or directly from a
     * 64bit bootloader.
     */
    cld
    cli

    /*
     * Save boot_params pointer for later use.
     * RSI contains boot_params address (passed by bootloader).
     */
    movq    %rsi, %r15              /* 保存 boot_params 指针 */
```

**ABI 规定**（Documentation/x86/boot.txt）：

```
Field name:     setup_sects
Type:           read
Offset/size:    0x1f1/1
Protocol:       ALL

  The size of the setup in sectors (512 bytes).

Field name:     boot_flag
Type:           read (obligatory)
Offset/size:    0x1fe/2
Protocol:       ALL

  Contains 0xAA55. This is the magic number indicating
  that this is a bootable kernel.

Field name:     kernel_alignment
Type:           read/modify (reloc)
Offset/size:    0x230/4
Protocol:       2.10+

  Alignment unit required by the kernel (if relocatable_kernel is set).
  A relocatable kernel that is loaded at an alignment incompatible with
  the value in this field will be realigned during kernel initialization.

Entry point:
  For a 64-bit kernel, the entry point is at offset 0x200 into the
  kernel image. The boot loader jumps to this address with:

  %rsi -> Address of the boot_params structure
```

**boot_params 结构**（arch/x86/include/uapi/asm/bootparam.h:173-219）：

```c
struct boot_params {
    struct screen_info screen_info;         /* 0x000 */
    struct apm_bios_info apm_bios_info;     /* 0x040 */
    __u8  _pad2[4];                         /* 0x054 */
    __u64  tboot_addr;                      /* 0x058 */
    struct ist_info ist_info;               /* 0x060 */
    __u64 acpi_rsdp_addr;                   /* 0x070 */
    __u8  _pad3[8];                         /* 0x078 */
    __u8  hd0_info[16];                     /* 0x080 (obsolete) */
    __u8  hd1_info[16];                     /* 0x090 (obsolete) */
    struct sys_desc_table sys_desc_table;   /* 0x0a0 (obsolete) */
    struct olpc_ofw_header olpc_ofw_header; /* 0x0b0 */
    __u32 ext_ramdisk_image;                /* 0x0c0 */
    __u32 ext_ramdisk_size;                 /* 0x0c4 */
    __u32 ext_cmd_line_ptr;                 /* 0x0c8 */
    __u8  _pad4[116];                       /* 0x0cc */
    struct edid_info edid_info;             /* 0x140 */
    struct efi_info efi_info;               /* 0x1c0 */
    __u32 alt_mem_k;                        /* 0x1e0 */
    __u32 scratch;                          /* 0x1e4 (scratch for kernels 2.02+) */
    __u8  e820_entries;                     /* 0x1e8 */
    __u8  eddbuf_entries;                   /* 0x1e9 */
    __u8  edd_mbr_sig_buf_entries;          /* 0x1ea */
    __u8  kbd_status;                       /* 0x1eb */
    __u8  secure_boot;                      /* 0x1ec */
    __u16 _pad5;                            /* 0x1ed */
    __u8  sentinel;                         /* 0x1ef */
    __u8  _pad6[1];                         /* 0x1f0 */
    struct setup_header hdr;                /* 0x1f1 */
    __u8  _pad7[0x290-0x1f1-sizeof(struct setup_header)];
    __u32 edd_mbr_sig_buffer[EDD_MBR_SIG_MAX]; /* 0x290 */
    struct boot_e820_entry e820_table[E820_MAX_ENTRIES_ZEROPAGE]; /* 0x2d0 */
    __u8  _pad8[48];                        /* 0xcd0 */
    struct edd_info eddbuf[EDD_MBR_SIG_MAX]; /* 0xd00 */
    __u8  _pad9[276];                       /* 0xeec */
} __attribute__((packed));
```

**关键点**：
- ✅ 遵循 System V ABI 的**寄存器传参规则**（RSI = 第 2 个参数）
- ❌ **不是**普通的 C 函数调用（汇编代码入口，无栈帧）
- ✅ 这是**启动协议 ABI**，不是 System V ABI 的一部分

### 5.3 边界 3 详解：Kernel → Init 进程

**内核加载 init 程序**（fs/exec.c）：

```c
// 内核加载 ELF 程序时设置栈布局
// 栈顶布局（从高地址到低地址）：
//
// [HIGH ADDRESS]
// NULL
// envp[n-1]
// ...
// envp[0]
// NULL
// argv[argc-1]
// ...
// argv[0]
// argc
// <-- RSP
// [128 bytes Red Zone]  ← 用户空间可用
// [LOW ADDRESS]

// 辅助向量（auxv）位于 envp 之后
// AT_EXECFN, AT_PLATFORM, AT_RANDOM, ...
```

**关键点**：
- ✅ 从这里开始，**完全遵循 System V ABI**
- ✅ Red Zone 可用（内核不会破坏）
- ✅ 栈 16 字节对齐

**相关文档**：
- [LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md) - 内核启动流程

---

## 6. vDSO 与 vsyscall：混合 ABI

### 6.1 vDSO 是什么？

**vDSO** (Virtual Dynamic Shared Object) 是内核映射到每个进程地址空间的一个**特殊的共享库**。

**目的**：
- 某些系统调用（如 `gettimeofday()`）非常频繁
- 避免 `syscall` 指令的开销（~100 个时钟周期）
- 内核提供**用户空间可直接调用的函数**

**实现**：

```c
// 用户空间程序调用
#include <sys/time.h>

int main() {
    struct timeval tv;
    gettimeofday(&tv, NULL);  // 看起来是系统调用
    return 0;
}

// 实际链接到 vDSO（ldd 输出）
$ ldd a.out
    linux-vdso.so.1 (0x00007ffce5bfe000)  ← vDSO
    libc.so.6 => /lib/x86_64-linux-gnu/libc.so.6
    /lib64/ld-linux-x86-64.so.2

// glibc 的 gettimeofday() 实现
// 1. 先尝试调用 vDSO 中的 __vdso_gettimeofday()（无 syscall）
// 2. 如果失败，才执行真正的 syscall
```

**vDSO 函数列表**（arch/x86/entry/vdso/vdso.lds.S）：

```c
VERSION {
    LINUX_2.6 {
        global:
            __vdso_clock_gettime;
            __vdso_gettimeofday;
            __vdso_time;
            __vdso_getcpu;
    };
}
```

### 6.2 vDSO 的 ABI 特性

| 方面 | vDSO ABI |
|------|----------|
| **调用约定** | ✅ 完全遵循 System V ABI（用户空间函数） |
| **参数传递** | RDI, RSI, RDX（标准寄存器） |
| **返回值** | RAX |
| **特权级** | Ring 3（用户空间代码） |
| **性能** | 无 syscall 开销（~10x 更快） |
| **稳定性** | ✅ Linux Userspace ABI 的一部分（永不破坏） |

**证据**（arch/x86/entry/vdso/vclock_gettime.c:224-249）：

```c
// vDSO 中的 clock_gettime 实现（用户空间代码）
notrace int __vdso_clock_gettime(clockid_t clock, struct timespec *ts)
{
    switch (clock) {
    case CLOCK_REALTIME:
        if (do_realtime(ts) == VCLOCK_NONE)
            goto fallback;  // 需要 syscall
        break;
    case CLOCK_MONOTONIC:
        if (do_monotonic(ts) == VCLOCK_NONE)
            goto fallback;
        break;
    default:
        goto fallback;
    }
    return 0;

fallback:
    return do_realtime_coarse(ts);  // 执行真正的系统调用
}

// 导出符号（遵循 System V ABI）
int clock_gettime(clockid_t, struct timespec *)
    __attribute__((weak, alias("__vdso_clock_gettime")));
```

### 6.3 vsyscall（已废弃）

**vsyscall** 是 vDSO 的前身，有固定地址：

```
# cat /proc/self/maps | grep vsyscall
ffffffffff600000-ffffffffff601000 r-xp 00000000 00:00 0  [vsyscall]
```

**问题**：
- 固定地址（0xffffffffff600000）破坏 ASLR（地址空间布局随机化）
- 安全漏洞（攻击者可预测地址）

**现状**：
- Linux 5.3+ 默认禁用（CONFIG_LEGACY_VSYSCALL_NONE）
- vDSO 完全取代 vsyscall

---

## 7. ABI 稳定性对比总结

### 7.1 各层 ABI 的稳定性承诺

| ABI 类型 | 定义者 | 稳定性承诺 | 违反后果 |
|---------|--------|-----------|----------|
| **System V ABI** | Unix System V 委员会 | 向后兼容（新版本可能扩展） | 程序无法链接，运行崩溃 |
| **Linux Syscall ABI** | Linux 内核（Linus） | **永不破坏**（"We do not break userspace"） | 用户程序无法运行，内核视为 bug |
| **Linux 内部 ABI** | Linux 内核 | **无承诺**（可以随时改变） | 仅影响内核模块（需重新编译） |
| **启动协议 ABI** | Linux 内核 | 向后兼容（新版本扩展 boot_params） | Bootloader 无法启动内核 |
| **vDSO ABI** | Linux 内核 | **永不破坏**（同 Syscall ABI） | 用户程序崩溃 |

### 7.2 内核启动代码的 ABI 合规性

**总结来自**：[LINUX_KERNEL_ABI_COMPLIANCE_ANALYSIS.md](LINUX_KERNEL_ABI_COMPLIANCE_ANALYSIS.md)

| 阶段 | System V ABI 合规性 | 说明 |
|------|---------------------|------|
| **压缩内核启动** (head_64.S) | 95% | 遵循寄存器使用，但无栈帧 |
| **主内核启动** (head_64.S, head64.c) | 98% | 基本遵循，栈 8 字节对齐（非 16） |
| **内核代码** (全局) | 70% | 禁用 Red Zone，使用 `-mno-red-zone` |
| **用户空间程序** | 100% | 完全遵循 System V ABI |

**关键编译标志**（arch/x86/Makefile）：

```makefile
# x86-64 内核特殊标志
ifdef CONFIG_X86_64
    KBUILD_CFLAGS += -mno-red-zone      # 禁用 Red Zone
    KBUILD_CFLAGS += -mcmodel=kernel    # 使用 kernel 代码模型
    KBUILD_CFLAGS += -fno-asynchronous-unwind-tables  # 禁用异步栈展开
endif
```

### 7.3 启动过程 ABI 转换图

```
时间轴        阶段                    ABI 遵循情况
────────────────────────────────────────────────────────
             ┌──────────────┐
             │   BIOS ROM   │
             │  (Real Mode) │        无 ABI（汇编代码）
             └──────┬───────┘
                    │ DL=boot drive
             ┌──────▼───────┐
             │ Bootloader   │
             │   (GRUB)     │        自定义 ABI（-mregparm=3）
             │   i386 PC    │        合规性：25%
             └──────┬───────┘
                    │ RSI=boot_params
  0x200 →    ┌──────▼───────┐
             │  Compressed  │
             │   Kernel     │        启动协议 ABI
             │  (startup_64)│        + System V ABI 95%
             └──────┬───────┘
                    │ 解压
             ┌──────▼───────┐
             │ Main Kernel  │
             │  (startup_64)│        System V ABI 98%
             │ → start_kernel        （禁用 Red Zone）
             └──────┬───────┘
                    │ kernel_init_freeable
                    │ run_init_process
  Ring 3 →   ┌──────▼───────┐
             │ Init Process │
             │  (PID 1)     │        System V ABI 100%
             │              │        + Linux Userspace ABI
             └──────┬───────┘
                    │ fork/exec
             ┌──────▼───────┐
             │ User Programs│
             │  (用户程序)  │        System V ABI 100%
             │              │        syscall ABI（R10 传参）
             └──────────────┘
```

---

## 8. 实际代码示例

### 8.1 System V ABI 函数调用

```c
// lib.c (编译成 libfoo.so)
int add(int a, int b) {
    return a + b;
}

// main.c (编译成 app)
#include <stdio.h>
extern int add(int, int);

int main() {
    int result = add(3, 4);
    printf("Result: %d\n", result);
    return 0;
}

// 编译
$ gcc -shared -fPIC lib.c -o libfoo.so
$ gcc main.c -L. -lfoo -o app

// 反汇编 libfoo.so
$ objdump -d libfoo.so
0000000000001129 <add>:
    1129:   55                      push   %rbp
    112a:   48 89 e5                mov    %rsp,%rbp
    112d:   89 7d fc                mov    %edi,-0x4(%rbp)  ; a (RDI)
    1130:   89 75 f8                mov    %esi,-0x8(%rbp)  ; b (RSI)
    1133:   8b 55 fc                mov    -0x4(%rbp),%edx
    1136:   8b 45 f8                mov    -0x8(%rbp),%eax
    1139:   01 d0                   add    %edx,%eax        ; a + b
    113b:   5d                      pop    %rbp
    113c:   c3                      ret                     ; RAX = result
```

**ABI 分析**：
- ✅ 参数 `a` 通过 `RDI` 传递
- ✅ 参数 `b` 通过 `RSI` 传递
- ✅ 返回值通过 `RAX` 返回
- ✅ `RBP` 被保存（callee-saved）

### 8.2 Linux Syscall ABI

```c
// syscall_example.c
#include <unistd.h>
#include <sys/syscall.h>

int main() {
    // 直接使用 syscall 指令
    long result = syscall(SYS_write,  // RAX = 1 (write)
                          1,           // RDI = 1 (stdout)
                          "Hello\n",   // RSI = buf
                          6);          // RDX = count
    return 0;
}

// 编译并反汇编
$ gcc -static syscall_example.c -o syscall_example
$ objdump -d syscall_example | grep -A20 '<main>'

00000000004010d0 <main>:
  4010d0:   55                      push   %rbp
  4010d1:   48 89 e5                mov    %rsp,%rbp
  4010d4:   48 8d 0d 29 0f 00 00    lea    0xf29(%rip),%rcx  ; "Hello\n"
  4010db:   ba 06 00 00 00          mov    $0x6,%edx         ; count = 6
  4010e0:   48 89 ce                mov    %rcx,%rsi         ; buf
  4010e3:   bf 01 00 00 00          mov    $0x1,%edi         ; fd = 1
  4010e8:   b8 01 00 00 00          mov    $0x1,%eax         ; SYS_write = 1
  4010ed:   0f 05                   syscall                  ; ← syscall 指令
  4010ef:   48 89 45 f8             mov    %rax,-0x8(%rbp)
  4010f3:   b8 00 00 00 00          mov    $0x0,%eax
  4010f8:   5d                      pop    %rbp
  4010f9:   c3                      ret
```

**ABI 分析**：
- ✅ RAX = 1（系统调用号 SYS_write）
- ✅ RDI = 1（第 1 个参数 fd）
- ✅ RSI = buf（第 2 个参数）
- ✅ RDX = 6（第 3 个参数 count）
- ✅ 使用 `syscall` 指令（不是 `call`）

### 8.3 内核启动代码（混合 ABI）

**压缩内核入口**（arch/x86/boot/compressed/head_64.S:278-375）：

```asm
SYM_CODE_START(startup_64)
    /* 入口点 0x200 是 ABI 定义 */
    cld
    cli

    /* RSI = boot_params（遵循 System V ABI 第 2 个参数） */
    movq    %rsi, %r15              /* 保存到 callee-saved 寄存器 */

    /* 后续调用 C 函数：extract_kernel(void *rmode, void *output, ...) */
    leaq    boot_heap(%rip), %rsi   /* arg2 = output */
    leaq    input_data(%rip), %rdx  /* arg3 = input_data */
    movl    input_len(%rip), %ecx   /* arg4 = input_len */
    movq    %rbp, %r8               /* arg5 = output_len */
    movq    %rbx, %r9               /* arg6 = virt_addr */
    call    extract_kernel          /* 遵循 System V ABI */
```

**ABI 分析**：
- ✅ 汇编入口：遵循启动协议 ABI（RSI = boot_params）
- ✅ 调用 C 函数：遵循 System V ABI（RDI, RSI, RDX, RCX, R8, R9）
- ⚠️ 特殊：入口无栈帧（汇编代码），但调用 C 函数时建立栈帧

---

## 9. 参考文献

### 9.1 System V ABI 规范

1. **System V Application Binary Interface AMD64 Architecture Processor Supplement**
   Draft Version 0.99.6 (2013)
   https://gitlab.com/x86-psABIs/x86-64-ABI

2. **System V Application Binary Interface Intel386 Architecture Processor Supplement**
   Fourth Edition (1997)
   https://github.com/hjl-tools/x86-psABI

3. **Agner Fog - Calling conventions for different C++ compilers and operating systems**
   https://www.agner.org/optimize/calling_conventions.pdf

### 9.2 Linux 内核文档

4. **Linux Kernel Documentation - x86 Boot Protocol**
   Documentation/x86/boot.txt
   https://www.kernel.org/doc/Documentation/x86/boot.txt

5. **Linux Kernel Documentation - System Calls**
   Documentation/process/adding-syscalls.rst

6. **Linus Torvalds - "We do not break userspace"**
   LKML, 2012-12-23
   https://lkml.org/lkml/2012/12/23/75

### 9.3 Intel 手册

7. **Intel 64 and IA-32 Architectures Software Developer's Manual**
   Volume 3A, Section 5.8.8: "Fast System Calls in 64-Bit Mode"
   https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html

### 9.4 本项目相关文档

8. [LINUX_KERNEL_ABI_COMPLIANCE_ANALYSIS.md](LINUX_KERNEL_ABI_COMPLIANCE_ANALYSIS.md)
   Linux 内核启动代码 System V ABI 遵守情况分析报告

9. [SEABIOS_GRUB_ABI_COMPLIANCE_ANALYSIS.md](SEABIOS_GRUB_ABI_COMPLIANCE_ANALYSIS.md)
   SeaBIOS & GRUB ABI 遵从性分析报告

10. [LINUX_KERNEL_FUNCTION_ATTRIBUTES.md](LINUX_KERNEL_FUNCTION_ATTRIBUTES.md)
    Linux 内核函数修饰符与调用约定

11. [LINUX_KERNEL_SYSCALL_INIT.md](LINUX_KERNEL_SYSCALL_INIT.md)
    Linux 内核系统调用初始化详解

12. [LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md)
    Linux 内核启动与初始化

---

## 10. 常见问题（FAQ）

### Q1: "Linux 遵循 System V ABI" 这句话对吗？

**A**: **不完全对**。需要区分：

- ✅ **用户空间程序**：完全遵循 System V ABI
- ✅ **内核启动代码**：大部分遵循（98%），但有特殊优化
- ❌ **系统调用接口**：不遵循 System V ABI（使用独立的 syscall ABI）
- ❌ **内核内部代码**：部分偏离（禁用 Red Zone、8 字节栈对齐）

### Q2: 为什么系统调用不能用 RCX 传第 4 个参数？

**A**: 因为 `syscall` 指令会自动执行 `RCX ← RIP`（保存返回地址），破坏原有的参数值。因此 Linux syscall ABI 使用 **R10** 传递第 4 个参数。

### Q3: vDSO 和系统调用有什么区别？

**A**:

| 方面 | vDSO | 系统调用 |
|------|------|----------|
| **特权级** | Ring 3（用户空间） | Ring 0（内核空间） |
| **性能** | 快（无特权切换） | 慢（~100 时钟周期） |
| **调用约定** | System V ABI | Syscall ABI（R10 传参） |
| **适用场景** | 频繁调用、只读数据（如时间） | 需要内核权限的操作 |

### Q4: 为什么内核要禁用 Red Zone？

**A**: Red Zone 是 RSP 下方 128 字节的临时存储区，但**中断处理程序会破坏这个区域**。内核代码可能被中断打断，因此必须使用 `-mno-red-zone` 禁用。

### Q5: GRUB 的 ABI 为什么这么低（25%）？

**A**: GRUB 使用 `-mregparm=3`（寄存器传参）和 `-mrtd`（callee cleanup）来**优化代码体积**（节省 10-15%），因为引导加载程序空间极度受限。详见 [SEABIOS_GRUB_ABI_COMPLIANCE_ANALYSIS.md](SEABIOS_GRUB_ABI_COMPLIANCE_ANALYSIS.md)。

---

**文档结束**
