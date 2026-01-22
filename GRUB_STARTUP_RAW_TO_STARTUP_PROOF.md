# GRUB startup_raw.S 解压后跳转到 startup.S 的证明

## 问题

如何证明 `startup_raw.S` 解压缩后跳转的代码是 `startup.S`？

## 证明过程

### 1. 解压目标地址的设置

**源代码位置**：`grub/grub-core/boot/i386/pc/startup_raw.S:335`

```asm
#ifdef ENABLE_LZMA
	movl	$GRUB_MEMORY_MACHINE_DECOMPRESSION_ADDR, %edi
```

**解压目标地址定义**：`grub/include/grub/i386/pc/memory.h:36`

```c
#define GRUB_MEMORY_MACHINE_DECOMPRESSION_ADDR	0x100000
```

**证明点 1**：解压目标地址是 `0x100000`（1MB）。

---

### 2. %esi 寄存器的设置

**源代码位置**：`grub/grub-core/boot/i386/pc/startup_raw.S:341-349`

```asm
	pushl	%edi                    // 将 %edi (0x100000) 压入栈
	movl	LOCAL (uncompressed_size), %ecx
	leal	(%edi, %ecx), %ebx
	/* Don't remove this push: it's an argument.  */
	push 	%ecx
	call	_LzmaDecodeA            // 调用 LZMA 解压函数
	pop	%ecx
	/* _LzmaDecodeA clears DF, so no need to run cld */
	popl	%esi                    // 将之前压入的 %edi (0x100000) 弹出到 %esi
```

**执行流程**：
1. `%edi` 被设置为 `0x100000`（解压目标地址）
2. `%edi` 被压入栈（作为解压函数的参数或用于后续恢复）
3. 调用 `_LzmaDecodeA` 解压函数，将压缩代码解压到 `%edi` 指向的地址（`0x100000`）
4. `popl %esi` 将之前压入的 `%edi`（即 `0x100000`）弹出到 `%esi`

**证明点 2**：解压完成后，`%esi` 寄存器的值是 `0x100000`（解压后的代码基址）。

---

### 3. 跳转指令

**源代码位置**：`grub/grub-core/boot/i386/pc/startup_raw.S:356`

```asm
	jmp	*%esi                   // 间接跳转到 %esi 指向的地址（0x100000）
```

**证明点 3**：`startup_raw.S` 执行 `jmp *%esi`，跳转到 `0x100000`。

---

### 4. startup.S 的入口点定义

**源代码位置**：`grub/grub-core/kern/i386/pc/startup.S:55-58`

```asm
	.globl	start, _start, __start
start:
_start:
__start:
```

**证明点 4**：`startup.S` 定义了全局符号 `_start`，这是解压后代码的入口点。

---

### 5. 链接顺序的保证

**构建系统配置**：`grub/grub-core/Makefile.core.def:116`

```
i386_pc_startup = kern/i386/pc/startup.S;
```

**链接标志**：`grub/grub-core/Makefile.core.def:85`

```
i386_pc_ldflags = '$(TARGET_IMG_BASE_LDOPT),0x9000';
```

**为什么链接地址是 `0x9000` 而不是 `0x100000`？**

这是**链接地址（Link Address）**和**运行地址（Runtime Address）**的区别：

### 链接基地址的作用

**链接基地址（Link Base Address）**是链接器在编译时使用的基址，主要作用包括：

#### 链接器的工作原理

**你的理解是正确的！** 链接器确实会根据相对位置连接所有编译出来的代码，并按照位置分配地址，保证相对位置正确。更准确的描述如下：

**链接器的主要工作步骤：**

1. **合并目标文件**：
   - 将多个 `.o` 目标文件合并成一个可执行文件
   - 每个目标文件包含代码段（`.text`）、数据段（`.data`）、BSS 段（`.bss`）等

2. **分配地址（基于链接基址）**：
   - 从链接基址（如 `0x9000`）开始，按顺序为每个段分配地址
   - 例如：
     ```
     链接基址：0x9000
     _start（startup.S）:     0x9000
     grub_main（main.c）:     0x9100  （假设 startup.S 占用 0x100 字节）
     grub_boot_device（变量）: 0x9200  （假设 main.c 占用 0x100 字节）
     ```
   - **不是"填0"**，而是**分配地址空间**，确保每个符号都有明确的地址

3. **解析符号引用**：
   - 查找所有未定义的符号（如函数调用、变量引用）
   - 将符号引用替换为实际地址或相对偏移
   - 例如：`call grub_main` → `call 0x9100` 或 `call +0x100`（相对偏移）

4. **计算相对偏移**：
   - 链接器计算符号之间的相对偏移（如 `grub_main - _start = 0x100`）
   - 这些相对偏移在位置无关代码中用于运行时地址计算
   - **相对偏移在链接时和运行时都保持不变**

5. **生成最终文件**：
   - 将所有代码和数据按照分配的地址排列
   - 生成可执行文件或二进制镜像

**关键点：**
- ✅ **相对位置正确**：链接器确保符号之间的相对位置（偏移）是正确的
- ✅ **地址分配**：基于链接基址分配绝对地址，但相对偏移才是关键
- ✅ **位置无关代码**：即使代码在不同地址运行，相对偏移仍然有效

---

### 详细回答：链接器如何保证相对位置正确

#### 问题 1：如何保证相对位置正确？是否需要填0？

**答案：是的，需要填充（padding），但不一定是填0。**

**链接器保证相对位置正确的机制：**

1. **段对齐（Section Alignment）**：
   - 链接器会按照段的对齐要求（如 4 字节、16 字节对齐）分配地址
   - 如果某个段需要 16 字节对齐，链接器会在前一个段后填充字节（通常是 0）以满足对齐要求
   - 例如：
     ```
     代码段（.text）: 0x9000 - 0x90FF（256 字节，已对齐）
     数据段（.data）: 需要 16 字节对齐
     → 如果代码段结束在 0x90FF，链接器会填充到 0x9100（16 字节对齐）
     → 数据段从 0x9100 开始
     ```

2. **符号地址计算**：
   - 链接器根据每个符号在段内的偏移和段的起始地址计算绝对地址
   - 例如：
     ```
     链接基址：0x9000
     _start 在代码段偏移 0x0000 → 绝对地址 0x9000
     grub_main 在代码段偏移 0x0100 → 绝对地址 0x9100
     ```

3. **相对偏移计算**：
   - 链接器计算符号之间的相对偏移（这些偏移在运行时保持不变）
   - 例如：`grub_main - _start = 0x100`（无论代码加载到哪里，这个偏移都是 0x100）

4. **填充字节的作用**：
   - **对齐填充**：确保段按照对齐要求排列（通常是 0 填充）
   - **空间预留**：为 BSS 段预留空间（未初始化的全局变量，运行时清零）

**示例：链接器如何分配地址**

```
链接基址：0x9000

代码段（.text）：
  0x9000: _start（startup.S）
  0x9100: grub_main（main.c）
  0x9200: 其他函数...
  
数据段（.data）：
  0x9300: 已初始化的全局变量（需要 16 字节对齐，所以从 0x9300 开始）
  
BSS 段（.bss）：
  0x9400: grub_boot_device（未初始化的全局变量，运行时清零）
  0x9404: 其他未初始化变量...
```

**关键点：**
- ✅ **填充是必要的**：用于对齐和空间预留
- ✅ **填充通常是 0**：但也可以是其他值（取决于链接器脚本）
- ✅ **相对偏移不变**：无论代码加载到哪里，符号之间的相对偏移保持不变

---

#### 问题 2：数据需要加载位置，是否受基地址影响？

**答案：是的，数据地址受基地址影响，但通过位置无关访问方式解决。**

**数据地址的计算：**

1. **链接时的地址计算**：
   - 数据地址 = 链接基址 + 数据在段内的偏移
   - 例如：
     ```
     链接基址：0x9000
     grub_boot_device 在数据段偏移 0x0400
     → 链接时地址：0x9000 + 0x0400 = 0x9400
     ```

2. **运行时的地址计算**：
   - 如果代码是位置无关的，运行时地址 = 运行基址 + 数据在段内的偏移
   - 例如：
     ```
     运行基址：0x100000（解压后的地址）
     grub_boot_device 在数据段偏移 0x0400
     → 运行时地址：0x100000 + 0x0400 = 0x100400
     ```

**GRUB 如何访问数据（位置无关方式）：**

**源代码位置**：`grub/grub-core/kern/i386/pc/startup.S:119`

```asm
movl    %edx, EXT_C(grub_boot_device)
```

**关键点：**
- `EXT_C(grub_boot_device)` 是一个宏，展开为相对于 `_start` 的偏移
- 链接器会计算 `grub_boot_device - _start` 的相对偏移
- 运行时，通过 `%esi`（指向 `_start` 的地址）加上相对偏移来访问数据

**位置无关访问的实现：**

```asm
// 假设 grub_boot_device 相对于 _start 的偏移是 0x400
// 链接时：grub_boot_device = 0x9400, _start = 0x9000
// 相对偏移 = 0x9400 - 0x9000 = 0x400

// 运行时：
// %esi = 0x100000（_start 的实际地址）
// grub_boot_device 的实际地址 = 0x100000 + 0x400 = 0x100400

// 访问方式（通过相对偏移）：
movl    %edx, (grub_boot_device - _start) (%esi)
// 展开为：
movl    %edx, 0x400(%esi)  // 0x400 是链接时计算的相对偏移
```

**总结：**
- ✅ **数据地址受基地址影响**：链接时和运行时的基址不同
- ✅ **通过相对偏移解决**：使用 `(symbol - _start) (%esi)` 的方式访问
- ✅ **类似 .org 指令**：但这里是运行时计算，而不是编译时固定地址

---

#### 问题 3：GRUB 源代码中是否有 relocator 表来保证最终加载地址的正确性？

**答案：GRUB 的 `startup.S` 不使用 relocator 表，而是使用位置无关代码（PIC）。**

**GRUB 的两种机制：**

1. **GRUB Core（startup.S）**：使用位置无关代码
   - **不使用 relocator 表**
   - 通过 `%esi` 基址寄存器 + 相对偏移访问所有符号
   - 代码可以在任何地址运行，只要 `%esi` 指向代码基址

2. **加载内核时**：使用 relocator 机制
   - **使用 relocator**：`grub_relocator32_boot()` 用于加载和跳转到内核
   - **目的**：切换到保护模式并跳转到内核入口点
   - **不用于 GRUB 自己的代码**：只用于加载其他代码（如 Linux 内核）

**为什么 GRUB Core 不使用 relocator 表？**

1. **位置无关代码更简单**：
   - 不需要重定位表
   - 不需要运行时重定位处理
   - 代码可以在任何地址运行

2. **性能更好**：
   - 不需要遍历重定位表并修改地址
   - 直接通过相对偏移访问

3. **代码更紧凑**：
   - 不需要存储重定位信息
   - 减少二进制文件大小

**GRUB 的位置无关代码实现：**

**源代码位置**：`grub/grub-core/kern/i386/pc/startup.S:64-66`

```asm
movl	%ecx, (LOCAL(real_to_prot_addr) - _start) (%esi)
movl	%edi, (LOCAL(prot_to_real_addr) - _start) (%esi)
movl	%eax, (EXT_C(grub_realidt) - _start) (%esi)
```

**关键点：**
- `(%esi)` 是基址寄存器，指向 `_start` 的实际地址（运行时是 `0x100000`）
- `(symbol - _start)` 是链接时计算的相对偏移（如 `0x400`）
- 运行时地址 = `%esi` + 相对偏移 = `0x100000 + 0x400 = 0x100400`

**总结：**
- ❌ **GRUB Core 不使用 relocator 表**：使用位置无关代码
- ✅ **GRUB 加载内核时使用 relocator**：但只用于加载其他代码，不用于 GRUB 自己
- ✅ **位置无关代码的优势**：更简单、更快、更紧凑

#### 链接基地址的具体作用

1. **计算符号地址**：
   - 链接器需要知道代码的预期加载地址来计算每个符号（函数、变量）的地址
   - 例如：如果 `_start` 在链接基址 `0x9000`，`grub_main` 在 `0x9000 + 0x100`，链接器会计算出 `grub_main` 的地址是 `0x9100`

2. **计算相对偏移**：
   - 链接器计算符号之间的相对偏移（如 `grub_main - _start = 0x100`）
   - 这些相对偏移在位置无关代码中用于运行时地址计算

3. **生成重定位信息**：
   - 如果代码不是完全位置无关的，链接器会生成重定位表
   - 重定位表告诉加载器哪些地址需要在运行时修改

4. **验证地址范围**：
   - 链接器可以检查代码是否超出了预期的地址范围
   - 例如：如果代码太大，超出了 `0x9000` 到某个上限的范围，链接器会报错

**示例：链接器如何使用基址**

假设链接基址是 `0x9000`：

```
链接时计算的地址（基于 0x9000）：
_start:      0x9000
grub_main:   0x9100
grub_boot_device: 0x9200

相对偏移（这些值在运行时仍然有效）：
grub_main - _start = 0x100
grub_boot_device - _start = 0x200
```

运行时，代码被加载到 `0x100000`，但相对偏移保持不变：

```
运行时实际地址（基于 0x100000）：
_start:      0x100000
grub_main:   0x100000 + 0x100 = 0x100100
grub_boot_device: 0x100000 + 0x200 = 0x100200
```

1. **链接地址（`0x9000`）**：
   - 这是链接器在编译时使用的基址
   - 链接器需要这个地址来计算符号之间的相对偏移
   - `0x9000` 是一个合理的链接基址，位于实模式可访问范围内
   - **即使代码是位置无关的，链接器仍然需要一个基址来计算符号偏移**

2. **运行地址（`0x100000`）**：
   - 这是代码实际运行时的地址
   - 代码被解压到 `0x100000`（1MB 以上）
   - 代码必须是**位置无关的（PIC - Position Independent Code）**

3. **位置无关代码的实现**：
   - `startup.S` 使用 `%esi` 作为基址寄存器
   - 所有地址计算都是相对于 `%esi` 的（如 `(%esi)`、`(_start - _start) (%esi)`）
   - 这样代码可以在任何地址运行，只要 `%esi` 指向代码的基址

4. **为什么选择 `0x9000` 作为链接地址**：
   - `0x9000` 位于实模式可访问范围内（前 1MB）
   - 避免与 `0x8000`（GRUB Core 压缩状态加载地址）冲突
   - 链接器只需要一个基址来计算相对偏移，实际运行地址由解压过程决定

**关键点**：
- `startup.S` 被明确指定为 `i386_pc_startup`，这是 i386_pc 平台的启动文件
- 链接器会将 `startup.S` 作为第一个链接的文件（因为它是启动文件）
- `_start` 符号是 `startup.S` 的第一个符号，因此会被放在代码段的开始位置
- 虽然链接地址是 `0x9000`，但代码是位置无关的，可以在 `0x100000` 运行

**证明点 5**：构建系统确保 `startup.S` 是第一个链接的文件，`_start` 符号位于代码段的开始。链接地址 `0x9000` 用于计算符号偏移，但代码是位置无关的，实际运行在 `0x100000`。

---

### 6. 解压后代码的布局

**解压过程**：
1. `startup_raw.S` 将压缩的 C 代码解压到 `0x100000`
2. 解压后的代码包含：
   - `startup.S`（第一个文件，入口点是 `_start`）
   - 其他 C 代码文件（`main.c`、`disk.c`、`file.c` 等）

**链接顺序**：
- `startup.S` 是第一个链接的文件
- `_start` 是 `startup.S` 的第一个符号
- 因此，`_start` 位于解压后代码的 `0x100000` 位置

**证明点 6**：解压后，`_start` 符号位于 `0x100000`，这是解压目标地址。

---

### 7. startup.S 接收参数的方式

**源代码位置**：`grub/grub-core/kern/i386/pc/startup.S:64-66`

```asm
	movl	%ecx, (LOCAL(real_to_prot_addr) - _start) (%esi)
	movl	%edi, (LOCAL(prot_to_real_addr) - _start) (%esi)
	movl	%eax, (EXT_C(grub_realidt) - _start) (%esi)
```

**关键观察**：
- `startup.S` 的 `_start` 函数使用 `%esi` 作为基址寄存器
- 这证明 `_start` 期望 `%esi` 指向自己的位置（`0x100000`）
- 这与 `startup_raw.S` 中 `popl %esi` 后 `%esi = 0x100000` 完全一致

**证明点 7**：`startup.S` 的 `_start` 函数使用 `%esi` 作为基址，证明它期望 `%esi` 指向 `0x100000`（即自己的位置）。

---

## 完整证明链

```
1. startup_raw.S:335
   movl $GRUB_MEMORY_MACHINE_DECOMPRESSION_ADDR, %edi
   → %edi = 0x100000（解压目标地址）

2. startup_raw.S:341
   pushl %edi
   → 将 0x100000 压入栈

3. startup_raw.S:346
   call _LzmaDecodeA
   → 将压缩代码解压到 0x100000

4. startup_raw.S:349
   popl %esi
   → %esi = 0x100000（解压后的代码基址）

5. startup_raw.S:356
   jmp *%esi
   → 跳转到 0x100000

6. 链接器保证
   → startup.S 是第一个链接的文件
   → _start 是 startup.S 的第一个符号
   → _start 位于 0x100000

7. startup.S:57
   _start:
   → 这是解压后代码的入口点，位于 0x100000

8. startup.S:64
   movl %ecx, (LOCAL(real_to_prot_addr) - _start) (%esi)
   → 使用 %esi 作为基址，证明 %esi 指向 _start 的位置（0x100000）
```

## 结论

**证明完成**：`startup_raw.S` 解压缩后跳转的代码确实是 `startup.S` 的 `_start` 函数。

**证明依据**：
1. ✅ 解压目标地址是 `0x100000`
2. ✅ 解压后 `%esi` 被设置为 `0x100000`
3. ✅ `jmp *%esi` 跳转到 `0x100000`
4. ✅ `startup.S` 定义了 `_start` 符号
5. ✅ 构建系统确保 `startup.S` 是第一个链接的文件
6. ✅ `_start` 位于解压后代码的 `0x100000` 位置
7. ✅ `startup.S` 的代码使用 `%esi` 作为基址，证明它期望 `%esi = 0x100000`

---

## 相关文档

- [GRUB 引导流程详解](BOOT_FLOW.md) - 包含 `startup_raw.S` 到 `startup.S` 的完整流程
- [GRUB 模式切换函数详解](GRUB_MODE_SWITCHING.md) - 包含 `real_to_prot` 和 `prot_to_real` 的详细说明
- [BIOS 内存布局与地址映射详解](BIOS_MEMORY_LAYOUT.md) - 包含 GRUB Core 解压后的内存布局
