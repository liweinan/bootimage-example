# GRUB Relocator：编译与运行时行为

本文档说明 relocator 相关代码**在何时、如何编译**，以及 **boot 时做了哪些事（不涉及再编译）**。执行流程、内存布局、为何必须 relocate 等见 [GRUB_RELOCATOR.md](GRUB_RELOCATOR.md)。

---

## 总览图（编译 vs 运行时）

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ GRUB 构建时（make，在开发/打包机器上完成）                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│  relocator32.S          relocator_asm.S        relocator_common_c.c         │
│  relocator.c            (forward/backward)    (grub_cpu_relocator_*)        │
│       │                        │                         │                   │
│       ▼                        ▼                         ▼                   │
│  [as/gcc 编译]  ────────► [链接进 relocator 模块] ────────► 编入 GRUB core   │
│                                                                              │
│  产物：GRUB 二进制中已有                                                     │
│    • grub_relocator32_start ～ _end（relocator32.S 的机器码）                │
│    • grub_relocator_forward_start ～ _end（forward 模板机器码）              │
│    • grub_relocator_backward_start ～ _end（backward 模板机器码）             │
│    • 全局变量：grub_relocator_*_dest/_src/_chunk_size 等                     │
└─────────────────────────────────────────────────────────────────────────────┘

**说明**：构建时 relocator 只是编进 GRUB 二进制，都在 0x100000+ 的 GRUB 镜像内，**没有**在内存里分成两块。**分成两块**是 **boot 时** 才发生：relocator32 被拷贝到安全区（0x1000–0x9a000），forward/backward+jumper 被组装到 16MB+ 的 movers_chunk。
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ boot 时（用户执行 boot 命令，无编译）                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│  1. 在安全区 0x1000–0x9a000 分配 chunk                                       │
│  2. grub_memmove(安全区, &grub_relocator32_start, RELOCATOR_SIZEOF(32))     │
│     → 把 GRUB 里已编译好的 relocator32 机器码 拷贝到安全区                    │
│  3. 在 16MB+ 分配 movers_chunk                                               │
│  4. C 侧（relocator_common_c.c 中的函数）：                                  │
│     • 对每个要复制的块：设全局变量 dest/src/size → 拷贝 forward/backward     │
│       模板（&grub_relocator_forward_start 等）到 movers_chunk                 │
│     • 写 jumper 机器码（mov + jmp）到 movers_chunk 末尾                      │
│  5. 跳转到 movers_chunk 执行 → 复制内核到 0x100000 → jumper 跳到安全区      │
│     → 安全区中 relocator32 副本执行 → ljmp 到内核                            │
└─────────────────────────────────────────────────────────────────────────────┘
```

**要点**：**编译只发生在 GRUB 构建时**；boot 时只是**拷贝已编译好的机器码**（relocator32 到安全区，forward/backward 模板到 movers_chunk）并**写少量机器码**（jumper），没有调用编译器或汇编器。

---

## 1. 编译过程（GRUB 构建时）

### 1.1 在哪里完成

- **位置**：GRUB 源码树，构建时由 **Makefile** 驱动（如 `grub-core/Makefile.core.def` 中 relocator 模块定义）。
- **时机**：执行 `./configure && make` 等构建 GRUB 时；与 boot 时无关。

### 1.2 如何编译（源码与产物）

| 源码文件 | 说明 | 编译方式 | 产物/符号 |
|----------|------|----------|-----------|
| `grub-core/lib/i386/relocator32.S` | 安全区中执行的代码（关分页、加载内嵌 GDT、设段、ljmp 到内核）；GDT 为 4 项平坦段（NULL/Reserved/Code/Data），非空表、无“服务”，详见 [GRUB_RELOCATOR.md](GRUB_RELOCATOR.md)「relocator32 内嵌 GDT 说明」 | 随 relocator 模块一起编译、链接进 core | `grub_relocator32_start`～`grub_relocator32_end`（在 GRUB 二进制中） |
| `grub-core/lib/i386/relocator_asm.S` | forward/backward 复制模板（含 VARIABLE 引用全局变量） | 同上 | `grub_relocator_forward_start`～`_end`、`grub_relocator_backward_start`～`_end`；全局变量 `*_dest`/`*_src`/`*_chunk_size` |
| `grub-core/lib/i386/relocator_common_c.c` | C 侧：preamble、设置全局变量、拷贝模板、写 jumper | 同上 | `grub_cpu_relocator_preamble`、`grub_cpu_relocator_forward`、`grub_cpu_relocator_backward`、`grub_cpu_relocator_jumper` 等 |
| `grub-core/lib/i386/relocator.c` | 通用 relocator 逻辑（分配、prepare_relocs、grub_relocator32_boot） | 同上 | `grub_relocator32_boot`、`grub_relocator_prepare_relocs` 等 |

**Makefile 依据**（`grub-core/Makefile.core.def` 中 relocator 模块，约 1739–1777 行）：

```text
module = {
  name = relocator;
  common = lib/relocator.c;
  x86 = lib/i386/relocator32.S;      # 与平台相关，x86 时编入
  i386 = lib/i386/relocator_asm.S;
  x86 = lib/i386/relocator_common_c.c;
  x86 = lib/i386/relocator.c;
  ...
};
```

构建时这些源文件被编译成目标文件并**链接进 GRUB core**（或 relocator 模块），因此运行时 GRUB 二进制里已经包含 relocator32 与 forward/backward 的**机器码**以及 C 侧函数。

---

## 2. “C 侧”含义

**“C 侧”**：指 **relocator_common_c.c 中的 C 代码**，与 **relocator_asm.S 中的汇编模板**相对。

- **汇编侧**（relocator_asm.S）：提供 forward/backward 的**机器码模板**，指令从**全局变量**（`grub_relocator_*_dest`、`*_src`、`*_chunk_size`）读取本次复制的 dest/src/size；模板在构建时编译好，boot 时整段拷贝到 movers_chunk。
- **C 侧**（relocator_common_c.c）：  
  - 在 **boot 时**被 `grub_relocator_prepare_relocs()` 调用；  
  - **设置**上述全局变量为当前块的 dest/src/size；  
  - **拷贝**对应汇编模板（`&grub_relocator_forward_start` 等）到 movers_chunk；  
  - **写入** jumper 的机器码（mov + jmp）到 movers_chunk 末尾。  

因此“C 侧：设置全局变量并拷贝模板到 rels”指的是：**由 C 代码负责**在运行时填好参数并把已编译好的模板拷贝到 movers_chunk，**没有**在运行时重新编译汇编或 C。

---

## 3. boot 时做了什么（无编译）

| 步骤 | 动作 | 是否编译 |
|------|------|----------|
| 在安全区分配 | `grub_relocator_alloc_chunk_align_safe()` | 否 |
| 拷贝 relocator32 到安全区 | `grub_memmove(安全区, &grub_relocator32_start, RELOCATOR_SIZEOF(32))` | 否，拷贝已有机器码 |
| 分配 movers_chunk | `malloc_in_range` / relocator 分配逻辑 | 否 |
| 生成 movers_chunk 内容 | C 侧：设全局变量 + `grub_memmove(rels, &grub_relocator_forward_start, ...)` 等 | 否，拷贝已有模板 + 写固定格式的 jumper 机器码 |
| 跳转执行 | `((void (*)(void)) relst)()` | 否 |

**“动态生成”的含义**：movers_chunk 的**内容**是运行时组装的（选哪几段 forward/backward、填哪个 dest/src/size、jumper 跳哪），但**不是**运行时编译源码得到的；用的是构建时已编译好的模板机器码 + 运行时写入的立即数（jumper 目标地址等）。

---

## 4. grub_relocator_prepare_relocs() 具体实现（运行时细节）

以下为 **boot 时** `grub_relocator_prepare_relocs()` 的详细过程（无编译，仅分配、排序、拷贝模板、写 jumper）。源码位置：本地 `grub/`（如 `grub/` 或 `/Users/weli/works/grub`）。

### 4.1 入口：分配 movers 缓冲区并对 chunk 按 src 排序

```c
// grub-core/lib/relocator.c:1529-1605
grub_err_t
grub_relocator_prepare_relocs (struct grub_relocator *rel, grub_addr_t addr,
			       void **relstart, grub_size_t *relsize)
{
  grub_uint8_t *rels;
  grub_uint8_t *rels0;
  struct grub_relocator_chunk *sorted;
  grub_size_t nchunks = 0;
  unsigned j;
  struct grub_relocator_chunk movers_chunk;

  // 步骤 1: 按 relocators_size 分配一块内存，用于存放“preamble + 复制代码 + jumper”
  if (!malloc_in_range (rel, 0, ~(grub_addr_t)0 - rel->relocators_size + 1,
			grub_relocator_align,
			rel->relocators_size, &movers_chunk, 1, 1))
    return grub_error (GRUB_ERR_OUT_OF_MEMORY, N_("out of memory"));
  movers_chunk.srcv = rels = rels0
    = grub_map_memory (movers_chunk.src, movers_chunk.size);

  // 步骤 2: 按 chunk->src 对 rel->chunks 做基数排序，得到 sorted[]
  // 目的：复制时按源地址顺序执行，避免重叠区被先覆盖
  {
    unsigned i;
    grub_size_t count[257];
    struct grub_relocator_chunk *from, *to, *tmp;
    // ... 基数排序：先按 src 低 8 位，再按下一字节，共 GRUB_CPU_SIZEOF_VOID_P 轮
    for (chunk = rel->chunks; chunk; chunk = chunk->next)
      from[count[chunk->src & 0xff]++] = *chunk;
    for (i = 1; i < GRUB_CPU_SIZEOF_VOID_P; i++) { ... }
    sorted = from;
  }
```

**分析**：`addr` 为安全区物理地址（relocator32 被复制到的位置），最终由 jumper 写回；`relstart` 输出 movers 缓冲区起始（即 `rels0`）。排序保证先搬的块不会覆盖未搬的数据（src 小则可能用 backward，src 大则用 forward）。

### 4.2 写入 preamble，再按 sorted 顺序写入 forward/backward 与 jumper

```c
// grub-core/lib/relocator.c:1606-1627
  grub_cpu_relocator_preamble (rels);
  rels += grub_relocator_preamble_size;

  for (j = 0; j < nchunks; j++)
    {
      if (sorted[j].src < sorted[j].target)
	{
	  grub_cpu_relocator_backward ((void *) rels,
				       sorted[j].srcv,
				       grub_map_memory (sorted[j].target,
							sorted[j].size),
				       sorted[j].size);
	  rels += grub_relocator_backward_size;
	}
      if (sorted[j].src > sorted[j].target)
	{
	  grub_cpu_relocator_forward ((void *) rels,
				      sorted[j].srcv,
				      grub_map_memory (sorted[j].target,
						       sorted[j].size),
				      sorted[j].size);
	  rels += grub_relocator_forward_size;
	}
      if (sorted[j].src == sorted[j].target)
	grub_arch_sync_caches (sorted[j].srcv, sorted[j].size);
    }
  grub_cpu_relocator_jumper ((void *) rels, (grub_addr_t) addr);
  *relstart = rels0;
  return GRUB_ERR_NONE;
}
```

**分析**：先写 preamble（i386-pc 下为空），再对每个 chunk：`src < target` 写一段 backward 复制代码，`src > target` 写一段 forward 复制代码，`src == target` 只做 cache 同步。最后在 `rels` 处写 jumper，跳转到 `addr`（安全区），即 relocator32 的入口。

### 4.3 Preamble：i386-pc 为空，x86_64-efi 为页表恒等映射

```c
// grub-core/lib/i386/relocator_common_c.c:147-152（i386 非 EFI）
#else
void
grub_cpu_relocator_preamble (void *rels __attribute__((unused)))
{
}
#endif
```

**分析**：i386-pc 不启用分页，preamble 不写入任何指令；`grub_relocator_preamble_size` 为 0。x86_64-efi 下该函数会向 `rels` 写入建立恒等映射的页表代码并设置 `grub_relocator_preamble_size`。

### 4.4 Forward/Backward 模板：汇编中的固定指令序列

```asm
// grub-core/lib/i386/relocator_asm.S:24-79
VARIABLE(grub_relocator_backward_start)
	.byte	0xb8
VARIABLE(grub_relocator_backward_dest)
	.long	0
	movl	%eax, %edi
	.byte	0xb8
VARIABLE(grub_relocator_backward_src)
	.long	0
	movl	%eax, %esi
	.byte	0xb9
VARIABLE(grub_relocator_backward_chunk_size)
	.long	0
	add	%ecx, %esi
	add	%ecx, %edi
	sub	$1, %esi
	sub	$1, %edi
	std
	rep
	movsb
VARIABLE(grub_relocator_backward_end)

VARIABLE(grub_relocator_forward_start)
	.byte	0xb8
VARIABLE(grub_relocator_forward_dest)
	.long	0
	movl	%eax, %edi
	.byte	0xb8
VARIABLE(grub_relocator_forward_src)
	.long	0
	movl	%eax, %esi
	.byte	0xb9
VARIABLE(grub_relocator_forward_chunk_size)
	.long	0
	cld
	rep
	movsb
VARIABLE(grub_relocator_forward_end)
```

**分析**：`VARIABLE(grub_relocator_*_dest/src/chunk_size)` 在链接后对应 GRUB 数据段中的全局变量；指令中的 `.long 0` 会被重定位成“从该全局变量地址取数”。Backward 模板：把 dest/src/size 从全局变量装入 edi/esi/ecx，将 esi/edi 加到块末尾再减 1（`rep movsb` 从高往低），然后 `std; rep movsb`。Forward 模板：装入后直接 `cld; rep movsb`。运行时这些全局变量在 C 里被赋值为本次 chunk 的 dest/src/size，复制到 movers 的只是模板的机器码，执行时仍从 GRUB 数据段读当前值。

### 4.5 C 侧：设置全局变量并拷贝模板到 rels

```c
// grub-core/lib/i386/relocator_common_c.c:192-211
void
grub_cpu_relocator_backward (void *ptr, void *src, void *dest,
			     grub_size_t size)
{
  grub_relocator_backward_dest = dest;
  grub_relocator_backward_src = src;
  grub_relocator_backward_chunk_size = size;
  grub_memmove (ptr,
		&grub_relocator_backward_start, RELOCATOR_SIZEOF (_backward));
}

void
grub_cpu_relocator_forward (void *ptr, void *src, void *dest,
			    grub_size_t size)
{
  grub_relocator_forward_dest = dest;
  grub_relocator_forward_src = src;
  grub_relocator_forward_chunk_size = size;
  grub_memmove (ptr,
		&grub_relocator_forward_start, RELOCATOR_SIZEOF (_forward));
}
```

**分析**：先给 GRUB 数据段中的 `*_dest`/`*_src`/`*_chunk_size` 赋成本次 chunk 的 dest/src/size，再把对应汇编模板（`grub_relocator_*_start`～`_end`）整段拷贝到 `ptr`（即 movers 中的当前 `rels`）。模板里的指令是“从符号地址加载”，执行时仍在 GRUB 地址空间，因此读到的是刚设置的值。动态性体现在：每次循环用不同的 (src, dest, size) 设置全局变量并拷贝同一段模板，得到多段“复制代码”。

### 4.6 Jumper：写入“mov addr, %eax; jmp *%eax”

```c
// grub-core/lib/i386/relocator_common_c.c:164-188
void
grub_cpu_relocator_jumper (void *rels, grub_addr_t addr)
{
  grub_uint8_t *ptr = rels;
#ifdef __x86_64__
  *(grub_uint8_t *) ptr = 0x48;
  ptr++;
  *(grub_uint8_t *) ptr = 0xb8;
  ptr++;
  *(grub_uint64_t *) ptr = addr;
  ptr += sizeof (grub_uint64_t);
#else
  *(grub_uint8_t *) ptr = 0xb8;
  ptr++;
  *(grub_uint32_t *) ptr = addr;
  ptr += sizeof (grub_uint32_t);
#endif
  *(grub_uint8_t *) ptr = 0xff;
  ptr++;
  *(grub_uint8_t *) ptr = 0xe0;
  ptr++;
}
```

**分析**：向 `rels` 写入 `movl addr, %eax`（0xb8 + 4 字节）和 `jmp *%eax`（0xff 0xe0）。`addr` 即安全区物理地址（relocator32 副本所在位置）。执行完所有 forward/backward 后，跳转到安全区，从 relocator32 副本的 PREAMBLE 继续执行（关分页、加载 relocator 内嵌的 GDT、设段与寄存器、`ljmp` 到内核）。

### 4.7 执行顺序小结

- GRUB 调用 `((void (*)(void)) relst)()` 时，`relst` 指向 **movers_chunk** 起始（preamble）。
- 实际顺序：**preamble**（i386-pc 为空）→ 多段 **forward/backward**（按 sorted 顺序，每段从 GRUB 全局变量读本段 src/dest/size）→ **jumper** 跳到安全区 → **安全区中的 relocator32 副本**（关分页、设段、设寄存器、`ljmp` 到内核）。

---

## 5. 与 GRUB_RELOCATOR.md 的对应关系

- **执行顺序、内存布局、为何必须 relocate**：见 [GRUB_RELOCATOR.md](GRUB_RELOCATOR.md) 的「Relocator 执行总览」「为什么在 BIOS/Legacy 下一定要有 relocate 过程？」。
- **grub_relocator32_boot()**、**为何要复制、UEFI、涉及代码一览** 等：见 [GRUB_RELOCATOR.md](GRUB_RELOCATOR.md) 的「grub_relocator32_boot() 函数」「关键问题解答」等小节。
- **编译在何处、如何编译、C 侧含义、grub_relocator_prepare_relocs() 具体实现（运行时细节）**：本文档。
