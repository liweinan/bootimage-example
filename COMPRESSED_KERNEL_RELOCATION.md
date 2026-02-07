# 压缩内核重定位与原地解压详解

本文档深入分析 Linux 内核启动过程中压缩内核（compressed kernel）的重定位拷贝机制和原地解压（in-place decompression）设计。

> **相关文档**：
> - 主流程：[LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md) - Linux 内核启动与初始化完整流程
> - 原地解压专题：[SOLUTION_ICACHE_MYSTERY.md](SOLUTION_ICACHE_MYSTERY.md) - extract_kernel 代码为何不被覆盖的完整答案
> - KASLR 分析：[WHY_RELOCATE_COMPRESSED_KERNEL.md](WHY_RELOCATE_COMPRESSED_KERNEL.md) - 为什么要重定位压缩内核
> - 调查过程：[INVESTIGATION_SUMMARY.md](INVESTIGATION_SUMMARY.md) - I-cache 理论验证与完整调查过程

---

## 一、压缩内核的位置变化（时间线）

**源代码位置**：`arch/x86/boot/compressed/head_64.S:278-476`

**完整时间线**：

```
T1: GRUB 加载阶段
    ├─ GRUB 将压缩内核（bzImage）加载到临时缓冲区（prot_mode_mem，通常在 16MB+）
    ├─ relocator 将其从临时缓冲区复制到 0x100000 (1MB)（prot_mode_target）
    └─ 跳转到 code32_start（0x100000，即 startup_32）
    └─ 说明：GRUB 使用 relocator 机制（grub_relocator32_boot）两步完成：
       先读取到 GRUB 可访问的临时缓冲区，boot 时再复制到目标地址并跳转

T2: startup_32/startup_64 执行阶段（在 1MB 处执行）
    └─ 压缩内核仍在 1MB (0x100000) 处
    └─ 计算重定位目标地址 %rbx（通常 16MB 以上，约 38MB）

T3: 重定位拷贝阶段（rep movsq，419-425行）
    └─ 将压缩内核从 1MB 拷贝到 %rbx（通常 38MB，为什么？见下文）
    └─ 跳转到新位置（%rbx 处）继续执行

T4: 解压阶段（在 %rbx 处执行）
    └─ 从 %rbx 处调用 extract_kernel()
    └─ 解压内核到 16MB (0x1000000)
    └─ 跳转到解压后的主内核
```

---

## 二、为何需要重定位拷贝？

**重要前提**：此重定位拷贝机制**仅适用于 BIOS/GRUB 启动路径**，UEFI 启动路径**完全不经过此流程**（详见 [UEFI_VS_BIOS_BOOT.md](UEFI_VS_BIOS_BOOT.md)）。

### BIOS/GRUB 路径的重定位原因

**问题场景**：
- **初始执行位置**：压缩内核开始执行时在 **1MB (0x100000)**（GRUB relocator 复制后的位置）
  - 注：GRUB 实际先加载到临时缓冲区（prot_mode_mem，通常 16MB+），boot 时 relocator 复制到 1MB
- **解压目标**：需要解压到 **16MB (0x1000000)**（CONFIG_PHYSICAL_ADDR 配置，可能因 KASLR 而不同）

**为什么看起来 1MB 和 16MB 不重叠仍需重定位？**

1. **栈和数据结构**：解压器代码在 1MB 处执行时，其栈、全局变量、临时数据都在附近（可能延伸到几 MB）

2. **解压器代码自身**：`extract_kernel()` 函数本身在 1MB 处，解压到 16MB 时可能覆盖执行路径

3. **CONFIG_RELOCATABLE + KASLR**：解压目标不总是 16MB，可能是任意对齐地址
   - 极端情况：KASLR 可能选择 8MB 作为解压目标，这会直接覆盖 1MB 的执行代码
   - 通用性：一套代码需要支持所有场景（固定地址、KASLR、kexec）

4. **自解压困境**：解压器代码和压缩数据都在同一个 bzImage 中
   - 如果直接在 1MB 处解压，可能覆盖正在执行的 `extract_kernel()` 函数
   - 需要确保解压过程不会破坏执行代码

**解决方案**：
先将整个压缩内核（包括解压器代码和压缩数据）从 1MB 拷贝到安全位置（%rbx，通常在 16MB 以上，例如约 38MB），然后从那里执行解压操作。

---

## 三、地址计算详解

### 解压目标地址 %rbp

**解压后内核的最终位置**：通常为 `LOAD_PHYSICAL_ADDR` (0x1000000，即 16MB)

- **来源**：`arch/x86/boot/compressed/head_64.S:325` 设置 `%rbp = LOAD_PHYSICAL_ADDR`
- **配置**：`LOAD_PHYSICAL_ADDR` 由 `CONFIG_PHYSICAL_START` 配置（默认 0x1000000）
- **KASLR 影响**：如果启用 KASLR，会在此基础上加随机偏移

### 重定位目标地址 %rbx

**压缩内核的安全位置**，计算公式见源代码 328-331 行：

```asm
movl    BP_init_size(%rsi), %ebx     # BP_init_size：内核初始化需要的总大小
subl    $ rva(_end), %ebx             # 减去压缩内核代码段的大小
addq    %rbp, %rbx                    # 加上解压目标地址（16MB）
# 结果：%rbx = 0x1000000 + BP_init_size - rva(_end)
```

**计算逻辑**：

```
%rbx = %rbp + BP_init_size - rva(_end)
     = 解压目标 + 初始化总大小 - 压缩内核大小
     = 0x1000000 + 0x20de000 - 0x9e8400
     = 0x26f5c00 (38.96 MB)
```

**参数说明**：
- **BP_init_size**：来自 boot_params，表示内核镜像初始化需要的总内存大小
  - 包括：解压后的内核 (VO) + 压缩内核 (ZO) + BSS + brk + 安全间隔
  - 典型值：32.87 MB
- **rva(_end)**：压缩内核代码段的结束位置（相对地址）
  - 即 ZO（compressed kernel）的总大小
  - 典型值：9.91 MB

**为何这样计算？**

将压缩内核放在**解压目标地址之后**的安全位置：

```
16 MB                    38.96 MB                     48.87 MB
 ↓                           ↓                            ↓
[====== VO（解压目标）======][====== ZO（压缩源）======]
        22.96 MB                     9.91 MB

解压写入：16MB → 38.96MB（不会到达 ZO）
解压读取：从 38.96MB 开始的 ZO
```

这样确保：
- 解压时不会覆盖正在执行的代码
- VO 和 ZO 完全分离，有明确边界

---

## 四、拷贝过程详解

**源代码**（`arch/x86/boot/compressed/head_64.S:419-425`）：

```asm
/* Copy the compressed kernel to the end of our buffer
 * where decompression in place becomes safe. */
	leaq	(_bss-8)(%rip), %rsi          /* 源：当前运行位置 */
	leaq	rva(_bss-8)(%rbx), %rdi       /* 目标：%rbx 处（安全地址） */
	movl	$(_bss - startup_32), %ecx    /* 大小：整个压缩内核 */
	shrl	$3, %ecx                      /* 转换为8字节单位 */
	std                                   /* 方向标志：向下拷贝（避免覆盖） */
	rep	movsq                             /* 执行拷贝 */
	cld                                   /* 清除方向标志 */
```

### 拷贝的内容

只拷贝**压缩内核**这一段（startup_32～_bss）：
- 解压器代码（.head.text、.text、.rodata、.data）
- 压缩的内核数据（Payload）
- **不包含 initrd**（initrd 由引导程序单独加载到另一块内存）

### 拷贝的方向

使用 `std`（方向标志 = 1）从高地址向低地址拷贝，原因：
- 源地址（1MB）< 目标地址（38MB）
- 如果从低向高拷贝，可能覆盖尚未拷贝的源数据
- 从高向低拷贝确保不会发生覆盖

### 拷贝的目标

%rbx 指向的地址，通常是 **38.96 MB**（具体公式见上文）

这个位置确保：
- 解压到 16MB 时不会覆盖正在执行的重定位后的代码
- 有足够的空间容纳整个压缩内核（9.91 MB）
- VO 和 ZO 完全分离

---

## 五、跳转到新位置

**源代码**（`arch/x86/boot/compressed/head_64.S:432-441`）：

```asm
	/* 重新加载 GDT，指向新位置 */
	leaq	rva(gdt64)(%rbx), %rax
	leaq	rva(gdt)(%rbx), %rdx
	movq	%rdx, 2(%rax)
	lgdt	(%rax)

	/* 跳转到新地址的 .Lrelocated */
	leaq	rva(.Lrelocated)(%rbx), %rax
	jmp	*%rax
```

### 重要说明："新地址"指的是什么？

这里的 `jmp *%rax` **不是跳转到主内核**，而是跳转到**同一个文件内**（`arch/x86/boot/compressed/head_64.S`）的 `.Lrelocated` 标签（第445行）。

**跳转目标**：`.Lrelocated`（`arch/x86/boot/compressed/head_64.S:445`）

```asm
440:    leaq    rva(.Lrelocated)(%rbx), %rax
441:    jmp    *%rax              ← 跳转到下面的 .Lrelocated
442: SYM_CODE_END(startup_64)
443:
444:    .text
445: SYM_FUNC_START_LOCAL_NOALIGN(.Lrelocated)  ← 跳转目标在这里！
446:    /* Clear BSS */
       ...
469:    call    extract_kernel      ← 在这里解压内核
       ...
475:    jmp    *%rax               ← 这里才跳转到主内核！
476: SYM_FUNC_END(.Lrelocated)
```

### 为什么需要这次跳转？

1. 前面的 `rep movsq`（419-425行）已将整个压缩内核拷贝到 %rbx 处（新内存位置）
2. 但当前指令仍在**旧位置**（1MB）执行
3. 必须跳转到**新位置的 .Lrelocated** 继续执行
4. 这样后续 `call extract_kernel()` 解压到 16MB 时，不会覆盖正在执行的代码

### "新地址"的含义

- **不是**指主内核（`arch/x86/kernel/head_64.S`）
- **而是**指重定位后的新内存位置（%rbx 处的 `.Lrelocated`）
- 只有在 `.Lrelocated` 内执行完 `extract_kernel()` 后的 `jmp *%rax`（第475行）才真正跳转到【阶段3】主内核

---

## 六、extract_kernel() 函数

**源代码位置**：`arch/x86/boot/compressed/misc.c:405`

在 **重定位拷贝完成后**被调用，完成以下工作：

1. **找到压缩负载**：根据 bzImage 布局找到 `input_data` 和 `input_len`
2. **确定解压目标**：`choose_random_location()`（可选 KASLR）确定解压目标地址
3. **执行解压**：`decompress_kernel()` 解压到 `output`（%rbp 指定，通常 0x1000000）
4. **解析 ELF**：解析解压后的 ELF 格式
5. **处理重定位**：`handle_relocations()` 处理内核重定位
6. **返回入口**：返回主内核入口地址（通过 %rax）

**与主内核的衔接**：
`extract_kernel()` 返回后，`.Lrelocated` 中执行 `jmp *%rax`（第475行），跳转到**主内核**的 `startup_64`（`arch/x86/kernel/head_64.S:38`），此时 %rsi（即 %r15）仍保存着 boot_params 指针。

---

## 七、原地解压（In-Place Decompression）的精妙设计

### 问题的提出

在前面的分析中，我们知道：
- 解压目标：从 16MB（%rbp）开始，向上扩展
- 压缩内核位置：重定位到 %rbx (通常 38MB ~ 48MB，由 init_size 决定)
- 解压后内核大小：通常 20MB ~ 30MB

**关键问题**：extract_kernel() 代码在解压过程中会被覆盖吗？

### vmlinuz 文件结构（重要发现）

通过分析实际的 vmlinuz 文件（Linux 6.6.110），发现其结构：

```
vmlinuz 文件布局：

[Boot + Setup]  [.head.text]  [Payload (gzip vmlinux)]  [.text + .rodata + .data]
   16 KB          0.69 KB            9.85 MB                    55.25 KB

   0x0-0x4000    0x4000-0x42c4    0x42c4-0x9de704          0x9de704-0x9ec400
                                ↑                          ↑
                          压缩的 vmlinux              extract_kernel 等函数
```

**关键发现**：
1. **Payload** (0x42c4-0x9de704): 压缩的 vmlinux（ELF 格式），9.85 MB
2. **.text 段** (0x9de704-0x9ec400): extract_kernel、decompress_kernel 等函数，55.25 KB
3. **Payload 是压缩后的解压目标（VO）**，不包含解压程序本身

### 运行时内存布局（基于 Linux 6.6.110）

**关键参数**：
```
init_size = 0x20de000 (32.87 MB)  // BP_init_size
ZO 总大小  = 0x9e8400 (9.91 MB)    // vmlinuz 中的压缩内核总大小
Payload  = 0x9da440 (9.85 MB)    // 其中的压缩 vmlinux
.text段   = 55.25 KB              // extract_kernel 等函数
```

**内存布局计算**：
```
%rbp = 0x1000000 (16 MB)           // 解压目标起始
%rbx = %rbp + init_size - ZO_size
     = 0x1000000 + 0x20de000 - 0x9e8400
     = 0x26f5c00 (38.96 MB)        // ZO 重定位位置
```

**ZO 在运行时的布局**（重定位到 38.96 MB后）：

```
38.96 MB (%rbx) ──┬─── ZO_startup_32 (.head.text 起始)
                  │    0.69 KB
38.96 MB + 0x2c4 ─┼─── Payload 起始 (压缩的 vmlinux)
                  │    9.85 MB
48.81 MB ─────────┼─── .text 段起始 (extract_kernel 代码)
                  │    55.25 KB
48.87 MB ─────────┴─── ZO__end
```

### 解压过程详细分析

**关键理解**：init_size 不等于解压后的内核大小（VO_size）！

```
init_size (32.87 MB) 包含：
1. VO (解压后的 vmlinux)：约 22.96 MB
2. ZO (压缩内核)：9.91 MB
3. 安全间隔空间
```

**解压目标大小**（VO_size）：
```
VO_size ≈ init_size - ZO_size
        = 32.87 MB - 9.91 MB
        = 22.96 MB
```

**实际内存布局**：

```
16 MB (%rbp) ──────┬─── VO__text (解压目标起始)
                   │
                   │    解压写入区域
                   │    (output_len ≈ 22.96 MB)
                   │
38.96 MB ──────────┼─── VO__end (解压结束位置)
                   │
                   │    安全间隔
                   │
38.96 MB (%rbx) ───┼─── ZO_startup_32 (.head.text)
                   │    0.69 KB
                   ├─── Payload (压缩 vmlinux)
                   │    9.85 MB
48.81 MB ──────────┼─── .text 段 (extract_kernel 代码)
                   │    55.25 KB
48.87 MB ──────────┴─── ZO__end
```

**解压过程**：
1. 从 Payload (38.96-48.81 MB) 读取压缩数据
2. 向 output (16-38.96 MB) 写入解压数据
3. 解压结束于 38.96 MB

**结论**：
- ✅ **extract_kernel 代码（48.81-48.87 MB）完全不在解压范围（16-38.96 MB）内**
- ✅ **解压过程不会覆盖 extract_kernel 代码**
- ✅ **这是通过精确的内存布局计算实现的**

### 设计精妙之处

**源代码注释**（`arch/x86/boot/compressed/misc.c:389-403`）：

```c
/*
 * The compressed kernel image (ZO), has been moved so that its position
 * is against the end of the buffer used to hold the uncompressed kernel
 * image (VO) and the execution environment (.bss, .brk), which makes sure
 * there is room to do the in-place decompression.
 *
 *                             |-----compressed kernel image------|
 *                             V                                  V
 * 0                       extract_offset                      +INIT_SIZE
 * |-----------|---------------|-------------------------|--------|
 *             |               |                         |        |
 *           VO__text      startup_32 of ZO          VO__end    ZO__end
 *             ^                                         ^
 *             |-------uncompressed kernel image---------|
 */
```

**关键点**：
1. **ZO 放在缓冲区末尾**：确保 VO 和 ZO 有合理的间隔
2. **VO_size < init_size**：解压目标小于总缓冲区大小
3. **extract_kernel 在 ZO 的最后**：位于 Payload 之后，完全在 VO 范围外

**INIT_SIZE 的计算**（`arch/x86/boot/header.S:502-509`）：

```c
#define ZO_INIT_SIZE    (ZO__end - ZO_startup_32 + ZO_z_min_extract_offset)
#define VO_INIT_SIZE    (VO__end - VO__text)
#if ZO_INIT_SIZE > VO_INIT_SIZE
# define INIT_SIZE ZO_INIT_SIZE  ← 通常取这个值
#else
# define INIT_SIZE VO_INIT_SIZE
#endif
```

这确保了：
- `init_size` 足够大，包含 VO + ZO + 安全间隔
- VO 不会扩展到 ZO 的范围

### 原地解压（In-Place Decompression）示意图

```
源代码注释中的图（arch/x86/boot/compressed/misc.c:389-403）：

                             |-----compressed kernel image------|
                             V                                  V
 0                       extract_offset                      +INIT_SIZE
 |-----------|---------------|-------------------------|--------|
             |               |                         |        |
           VO__text      startup_32 of ZO          VO__end    ZO__end
             ^                                         ^
             |-------uncompressed kernel image---------|

实际内存地址（Linux 6.6.110）：

16 MB        38.96 MB    48.81 MB     48.87 MB
 |------------|-----------|-----------|
 |            |           |           |
 VO__text     VO__end     .text段     ZO__end
 (%rbp)                   (extract_kernel)

 |←  VO  →| 安全间隔  |←     ZO     →|
 |← 22.96MB →|        |← 9.91 MB  →|

 解压写入: 16MB → 38.96MB (不会到达 extract_kernel)
           ↑
         output_len ≈ 22.96 MB
```

**关键设计**：
- VO 结束于 38.96 MB
- ZO 开始于 38.96 MB
- extract_kernel 代码在 48.81-48.87 MB（ZO 的最后 55 KB）
- **解压写入永远不会到达 extract_kernel 代码区域**

---

## 八、总结：精妙的内存布局设计

### 核心设计原理

1. **分离 VO 和 ZO**：
   - `init_size` 的计算确保 VO + ZO 可以共存
   - VO（解压目标）在前，ZO（压缩源）在后
   - 两者有明确的边界

2. **extract_kernel 代码的安全位置**：
   - 位于 Payload（压缩的 vmlinux）之后
   - 完全在 VO 范围之外
   - **永远不会被解压过程覆盖**

3. **不需要任何特殊机制**：
   - ❌ 不依赖 CPU 指令缓存
   - ❌ 不需要特殊的编译器指令
   - ✅ 纯粹通过数学计算保证安全

### 实际数据验证（Linux 6.6.110）

```
vmlinuz 结构：
  .head.text:   0.69 KB
  Payload:      9.85 MB  (压缩的 vmlinux)
  .text段:      55.25 KB (extract_kernel 等函数)

运行时布局：
  解压目标 (VO):   16 MB - 38.96 MB (22.96 MB)
  压缩源 (ZO):     38.96 MB - 48.87 MB (9.91 MB)
  extract_kernel:  48.81 MB - 48.87 MB (55 KB)

结论：完全不重叠！
```

### 为什么这个设计如此精妙？

1. **自解压困境的完美解决**：
   - 问题：解压器代码和压缩数据在同一个镜像中
   - 解决：通过重定位和精确的地址计算，确保两者完全分离

2. **零额外开销**：
   - 不需要额外的临时缓冲区
   - 不需要两次拷贝
   - 仅需一次重定位 + 一次解压

3. **支持所有启动场景**：
   - 固定地址启动
   - KASLR 随机地址
   - kexec 热启动
   - 所有场景使用同一套代码

4. **数学上的确定性**：
   - 通过 `init_size` 的计算公式确保安全
   - 编译时就已确定所有边界
   - 运行时只需简单的地址计算

---

## 参考资料

- Linux 源代码：`arch/x86/boot/compressed/head_64.S`
- Linux 源代码：`arch/x86/boot/compressed/misc.c:389-403`
- Linux 源代码：`arch/x86/boot/header.S:428-509`
- 详细分析专题：
  - [SOLUTION_ICACHE_MYSTERY.md](SOLUTION_ICACHE_MYSTERY.md) - 完整答案：为什么 extract_kernel 不被覆盖
  - [WHY_RELOCATE_COMPRESSED_KERNEL.md](WHY_RELOCATE_COMPRESSED_KERNEL.md) - KASLR 与重定位的必要性
  - [INVESTIGATION_SUMMARY.md](INVESTIGATION_SUMMARY.md) - 调查过程与实验验证
