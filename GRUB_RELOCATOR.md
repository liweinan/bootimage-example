# GRUB Relocator 详细分析

本文档从 [GRUB_KERNEL_LOADING.md](GRUB_KERNEL_LOADING.md) 提取，为 relocator 机制的详细实现与源码分析。主线流程（内核加载、boot 命令、code32_start 传递等）见 GRUB_KERNEL_LOADING.md。**相关文档与对齐**：与 GRUB_KERNEL_LOADING.md 在 BIOS/Legacy 下不执行 Setup、直接跳 code32_start、关分页/内嵌 GDT 等表述一致；模块加载见 [GRUB_MODULE_LOADING_ANALYSIS.md](GRUB_MODULE_LOADING_ANALYSIS.md)。**调用关系**：`grub_relocator32_boot()` 由 `grub_linux_boot()` 在隐式或显式 `boot` 时调用；`grub_linux_boot()` 由用户选择菜单项并执行该条目脚本体、脚本结束后触发。从 `grub_main` 到 `grub_cmd_menuentry` 的完整调用链（磁盘 grub.cfg：grub_main → grub_load_normal_mode → normal → grub_enter_normal_mode → read_config_file → grub_normal_parse_line → grub_script_execute → grub_cmd_menuentry）见 GRUB_KERNEL_LOADING.md「从 grub_main 到 grub_cmd_menuentry 的调用链」。

**文档结构概览：**

| 小节 | 内容 |
|------|------|
| **为什么在 BIOS/Legacy 下一定要有 relocate 过程？** | 0x100000 冲突、为何必须两阶段、为何 relocator 必须在 1MB 以下、与 UEFI 对比 |
| **Relocator 执行总览** | 从 boot 到内核的完整流程（含构建时 vs 运行时、步骤 1–5）、两处代码来源对照表 |
| **grub_relocator32_boot() 函数** | 入口函数、安全区分配、设置 eip/esi、拷贝 relocator32、调用 prepare_relocs、跳转 movers_chunk |
| **Relocator 数据结构与分配** | allocate_pages、0x100000 分配失败原因、16MB+ 临时缓冲区、relocator_alloc_chunk_align |
| **grub_relocator_prepare_relocs() 与动态生成** | movers_chunk 生成、forward/backward 模板、C 侧设置全局变量与拷贝、jumper、执行顺序 |
| **关键问题解答** | 问题 1：relocator 代码对应文件、**relocator32.S 完整源代码分析**、GDT 说明；问题 2 起：为何要复制、UEFI 不需要 relocator、bzImage 与 UEFI 不矛盾、涉及代码一览等 |

**编译与运行时**：relocator32.S、relocator_asm.S、relocator_common_c.c 在 **GRUB 构建时**（make）编译并链接进 GRUB；**boot 时不编译**，只拷贝已编译好的机器码并写 jumper。详见 [GRUB_RELOCATOR_BUILD_AND_RUNTIME.md](GRUB_RELOCATOR_BUILD_AND_RUNTIME.md)。

**从 GRUB 到内核的流程概览（BIOS/Legacy，本文档所述路径）：**

```
GRUB 保护模式代码（0x100000 (1MB)+）
    ↓
复制 relocator 代码到安全区（0x1000–0x9a000）；生成 movers_chunk（16MB+）
    ↓
跳转到 movers_chunk → 复制内核到 0x100000 (1MB) → jumper 跳到安全区
    ↓
安全区中 relocator32 副本执行：
    1. 关分页、加载 relocator 内嵌的 GDT（平坦段，供内核入口用；非 GRUB 的 GDT），切换到内核期望的 32 位保护模式状态
    2. 设置段寄存器（CS/DS/ES/SS 等）、栈指针 ESP、ESI = boot_params
    3. ljmp 到 code32_start
    ↓
内核入口点（code32_start @ 0x100000 (1MB)，32 位保护模式，如 startup_32）
```

**说明**：bzImage 内虽有实模式 setup 代码（`arch/x86/boot/`），但从 GRUB 启动时**不执行**该段；GRUB 自填 boot_params 后**直接**跳转到 code32_start（压缩内核的 32 位保护模式入口）。从扇区 0 启动时才会先跑 setup 再切保护模式跳 code32_start。

**内核入口点：BIOS 与 UEFI 不同**——**BIOS/Legacy**：bootloader 跳转到 **code32_start**（32 位保护模式，如 `linux/arch/x86/boot/compressed/head_64.S` 的 startup_32）；**UEFI**：固件按 PE 入口跳转到 **EFI stub**（如 `linux/arch/x86/boot/startup/efi-mixed.S` 的 efi_pe_entry），不经过 code32_start。详见下文「bzImage 必须放在 0x100000 与 UEFI 不矛盾」及「涉及代码一览」。

---

## 为什么在 BIOS/Legacy 下一定要有 relocate 过程？

**结论：** 在 BIOS/Legacy 下（GRUB 在保护模式，交给内核的入口为 code32_start，即 32 位保护模式），**内核约定放在 0x100000 (1MB)**，而 **GRUB 自身也运行在 0x100000 (1MB)+**，同一块物理地址不能同时放两套代码；因此必须先在内核“别处”（临时缓冲区）加载，等用户执行 boot 后，再由一段**位于 1MB 以下、不会被覆盖**的代码（relocator）把内核**复制**到 0x100000 并跳转。这段“先搬到 0x100000 再跳”的过程就是 **relocate**；没有它，要么覆盖 GRUB 导致无法跳转，要么内核不在约定地址无法正确执行。

**1. GRUB 自身加载在 0x100000 (1MB)+（源码依据）**

- **GRUB 约定**：i386 PC 上“1MB 以上”的起始地址为 `GRUB_MEMORY_MACHINE_UPPER_START = 0x100000`（1 MiB），GRUB 解压/运行时代码与数据在此之上。
- **源码**：`grub/include/grub/i386/memory.h` 定义 `GRUB_MEMORY_MACHINE_UPPER_START 0x100000`；`grub/include/grub/i386/pc/memory.h` 有 `GRUB_MEMORY_MACHINE_DECOMPRESSION_ADDR 0x100000`，即解压后 GRUB 使用的机器内存从 1MB 开始。
- **结果**：GRUB 的代码段、数据段、堆等都在 0x100000 及以上，**0x100000 这块物理地址被 GRUB 占用**。

**2. Linux bzImage 协议规定内核放在 0x100000 (1MB)（源码依据）**

- **GRUB 侧**：bzImage 的“建议/最终”加载地址为 `GRUB_LINUX_BZIMAGE_ADDR = 0x100000`。
- **源码**：`grub/include/grub/i386/linux.h` 定义 `#define GRUB_LINUX_BZIMAGE_ADDR 0x100000`；`grub-core/loader/i386/linux.c` 中 `preferred_address = GRUB_LINUX_BZIMAGE_ADDR`，`code32_start` 等按“镜像在 0x100000”来算。
- **Linux 侧**：内核期望自己（setup + 压缩镜像）被放在约定物理地址；`arch/x86/include/asm/page_types.h` 中 `LOAD_PHYSICAL_ADDR` 由 `CONFIG_PHYSICAL_START` 对齐得到，boot protocol 下 bzImage 的加载地址即为 0x100000；`arch/x86/kernel/kexec-bzimage64.c` 中有 `MIN_KERNEL_LOAD_ADDR 0x100000`。
- **结果**：**内核“最终”必须在 0x100000**，否则 setup、code32_start、解压等地址计算都会错。

**3. 冲突与“必须先 relocate”的必然性**

- 若 bootloader **直接把** bzImage 读到 0x100000：会**立刻覆盖**正在运行的 GRUB 代码，GRUB 还没执行“跳转到内核”就会崩溃，不可行。
- 若 bootloader 把内核放在“别处”（如 16MB+）且**不搬**：内核不在 0x100000，违反协议，无法正确执行。
- **因此**：只能采用 **两阶段**：  
  (1) 加载阶段：把内核放到**临时缓冲区**（如 16MB+，与 GRUB 不重叠）；  
  (2) boot 阶段：用一段**不在 0x100000 以上**的代码（即 1MB 以下的 **relocator**）把内核从临时区**复制**到 0x100000，再跳转到 `code32_start`。  
  这段“复制到 0x100000 + 跳转”就是 **relocate 过程**；在 BIOS/Legacy 下（GRUB 在保护模式、交给内核的入口为 code32_start）**必须有**，否则无法既保留 GRUB 的跳转能力又满足内核对 0x100000 的约定。

**4. 为何 relocator 代码必须在 1MB 以下？**

- 执行“复制到 0x100000”的代码若也在 0x100000+，复制时会**先覆盖自己**（或覆盖 GRUB），无法执行完再跳转。
- 因此 GRUB 把“做复制 + 关分页/加载内嵌 GDT/设段 + 跳内核”的代码**拷贝到安全区 0x1000–0x9a000**（1MB 以下），这段区域不会被“复制到 0x100000”的操作覆盖，relocator 执行完复制后再从安全区跳转到 0x100000 处的内核入口。详见下文「Relocator 执行总览」与「问题 2：为什么要复制？」。

**5. 与 UEFI 的对比（为何 UEFI 不需要这套 relocate）**

- UEFI 下：GRUB 和内核都运行在固件提供的环境；内核常由 EFI `LoadImage`/`StartImage` 加载到**任意地址**，由固件完成跳转；GRUB 不必占用 0x100000，也没有“同一地址两用”的问题，因此**不需要**“先放别处再搬到 0x100000”的 relocate 过程。详见下文「⚠️ UEFI 启动方式完全不同」与「bzImage 必须放在 0x100000 与 UEFI 不矛盾」。

---

## Relocator 执行总览

**重要**：movers_chunk 与 0x100000 (1MB) 是两块不同内存——movers_chunk 在 1MB 之上的某处（如 16MB+）单独分配，0x100000 仅是复制写入目标，因此复制不会覆盖 movers_chunk。

内存位置与 [BIOS_MEMORY_LAYOUT.md](BIOS_MEMORY_LAYOUT.md) 一致：**安全区** 0x1000–0x9a000（1MB 以下）、**movers_chunk** 与 **内核/initrd 临时缓冲区 (src)** 由 GRUB 空闲内存池动态分配（常在 16MB+ 或 modend 以上）、**复制目标** 0x100000 (1MB)。以下为从 boot 到内核的完整执行过程，并标明每步所在内存、源码文件与函数。

**从 boot 到内核的完整执行流程：**

```
执行顺序：GRUB → movers_chunk → 安全区 relocator32 副本 → 内核（movers_chunk 执行完后 jumper 跳入 relocator32 副本，而非 relocator32 跳去 movers_chunk）。**全程保护模式**，无实模式：GRUB、movers_chunk、安全区 relocator32、code32_start（如 startup_32）均在 32 位保护模式下执行；relocator32 仅关分页、加载内嵌 GDT、设段后 ljmp，未切回实模式。

grub_relocator32_boot(...)     [relocator.c]，执行于 GRUB 0x100000 (1MB)+
    ↓
步骤 1：在安全区 0x1000-0x9a000 分配 chunk
    └─ grub_relocator_alloc_chunk_align_safe()  [relocator.c]
    ↓
步骤 2：设置 grub_relocator32_eip、grub_relocator32_esi 等
    ↓
步骤 3：将 relocator32 已编译机器码拷贝到安全区 0x1000-0x9a000
    └─ grub_memmove(安全区, &grub_relocator32_start, RELOCATOR_SIZEOF(32))
    └─ 源：GRUB 二进制中已有（relocator32.S 在 GRUB 构建时编译、链接进 core，boot 时不编译）
    ↓
步骤 4：grub_relocator_prepare_relocs() 生成 movers_chunk（无编译，仅拷贝模板 + 写 jumper）
    内存：movers_chunk 在 16MB+ 或 modend 以上分配 [relocator.c]
    ├─ preamble   [relocator_common_c.c 写入，i386-pc 为空]
    ├─ forward/backward  [relocator_asm.S 在构建时已编译；运行时 C 侧设全局变量并拷贝模板机器码到 movers_chunk]
    ├─ jumper     [relocator_common_c.c 写入机器码：mov + jmp]
    └─ relst = movers_chunk 起始
    （编译过程与“C 侧”含义见 [GRUB_RELOCATOR_BUILD_AND_RUNTIME.md](GRUB_RELOCATOR_BUILD_AND_RUNTIME.md)）
    ↓
步骤 5：GRUB 调用 ((void (*)(void)) relst)() → 跳转到 movers_chunk（非 relocator32 跳转）
    ↓
┌── movers_chunk  内存：16MB+ 或 modend 以上 ─────────────────────────────────┐
│ preamble → forward/backward（src→0x100000 (1MB)）→ jumper                     │
│ jumper：jmp 到安全区（relocator32 副本入口）                                 │
└─────────────────────────────────────────────────────────────────────────────┘
    ↓
┌── 安全区 0x1000-0x9a000  relocator32 副本  [relocator32.S] ──────────────────┐
│ PREAMBLE → DISABLE_PAGING → 加载内嵌 GDT → 设段与寄存器 → ljmp code32_start   │
└─────────────────────────────────────────────────────────────────────────────┘
    ↓
0x100000 (1MB)：复制目标（由 movers_chunk 内 forward/backward 写入）；此处为内核镜像后，relocator32 的 ljmp 跳入
    ↓
内核入口点（code32_start @ 0x100000 (1MB)）
```

**两处 relocator 代码来源对照（与 BIOS_MEMORY_LAYOUT 一致）：**

| 内存位置 | 来源 | 源码文件 | 符号/函数 |
|----------|------|----------|-----------|
| **安全区 0x1000-0x9a000**（1MB 以下） | relocator32 编译后代码的副本（**构建时**编译进 GRUB，**boot 时**仅拷贝到安全区） | `grub-core/lib/i386/relocator32.S` | `grub_relocator32_start`～`_end`；由 `grub_relocator32_boot()` 里 `grub_memmove(..., &grub_relocator32_start, RELOCATOR_SIZEOF(32))` 拷贝到此 |
| **movers_chunk**（16MB+ 或 modend 以上，GRUB 空闲内存池动态分配；与 0x100000 (1MB) 为不同块） | preamble + forward/backward + jumper | 见下 | 见下 |
| ↳ preamble（movers_chunk 内） | C 写入 | `grub-core/lib/i386/relocator_common_c.c` | `grub_cpu_relocator_preamble(rels)`（i386-pc 为空） |
| ↳ forward/backward（movers_chunk 内） | relocator_asm.S 模板拷贝进 movers_chunk（**构建时**已编译进 GRUB，**boot 时** C 侧设全局变量并拷贝模板到 movers_chunk） | `grub-core/lib/i386/relocator_asm.S` | `grub_relocator_forward_start`～`_end`、`grub_relocator_backward_start`～`_end`；由 `grub_cpu_relocator_forward/backward(rels, ...)` 拷贝 |
| ↳ jumper（movers_chunk 内） | C 写入机器码 | `grub-core/lib/i386/relocator_common_c.c` | `grub_cpu_relocator_jumper(rels, addr)` |

relocator32.S 的执行顺序与**具体代码分析**见下文「关键问题解答」问题 1 内「relocator32.S 完整源代码分析」。

---

### grub_relocator32_boot() 函数

**源代码位置：** `grub/grub-core/lib/i386/relocator.c:75-117`

**功能：**
- 设置寄存器值（`grub_relocator32_eip`、`grub_relocator32_esi`）
- 准备 relocator 代码（拷贝 relocator32 到安全区、生成 movers_chunk）
- 跳转到 movers_chunk，最终由安全区 relocator32 ljmp 到内核入口点（`code32_start`）

**完整源代码分析：**

```c
// grub/grub-core/lib/i386/relocator.c:75-117
grub_err_t
grub_relocator32_boot (struct grub_relocator *rel, struct grub_relocator32_state state,
                       int avoid_efi_bootservices)
{
    grub_err_t err;
    void *relst;
    grub_relocator_chunk_t ch;

    // 步骤 1: 在安全区域（0x1000-0x9a000）分配 chunk
    err = grub_relocator_alloc_chunk_align_safe (rel, &ch,
        0x1000,   // 最小地址
        0x9a000,  // 最大地址（1MB 以下的安全区域）
        RELOCATOR_SIZEOF (32),  // relocator 代码大小
        16,       // 对齐
        GRUB_RELOCATOR_PREFERENCE_LOW,
        avoid_efi_bootservices);
    // 功能：
    //   - 在 1MB 以下的常规内存中分配一块，用于存放 relocator32 的副本
    //   - 该区域不会被“复制到 0x100000”的内核覆盖，relocator32 执行时安全
    //   - 地址与大小符合 Linux/x86 Boot Protocol 对 real_mode 区的约定
    // 源代码位置：grub-core/lib/relocator.c:grub_relocator_alloc_chunk_align_safe()

    if (err)
        return err;

    // 步骤 2: 设置 relocator32 将使用的寄存器值（写入全局变量，安全区执行时读取）
    grub_relocator32_eax = state.eax;
    grub_relocator32_ebx = state.ebx;
    grub_relocator32_ecx = state.ecx;
    grub_relocator32_edx = state.edx;
    grub_relocator32_eip = state.eip;   // 内核入口点（code32_start）
    grub_relocator32_esp = state.esp;
    grub_relocator32_ebp = state.ebp;
    grub_relocator32_esi = state.esi;   // boot_params 地址
    grub_relocator32_edi = state.edi;
    // 功能：
    //   - 上述变量在 relocator32.S 中通过 VARIABLE() 引用，编译为“mov imm32, reg”的立即数
    //   - 安全区中 relocator32 执行时从这些“位置”读入 esp/ebp/esi/edi/eax/ebx/ecx/edx 和 ljmp 目标
    // 源代码位置：grub-core/lib/i386/relocator32.S（VARIABLE(grub_relocator32_*)）

    // 步骤 3: 将 relocator32.S 编译后的机器码复制到安全区域
    grub_memmove (get_virtual_current_address (ch), &grub_relocator32_start,
                  RELOCATOR_SIZEOF (32));
    // 功能：
    //   - 把 GRUB 二进制中已有的 relocator32 机器码拷贝到步骤 1 分配的安全区
    //   - 此时尚未执行；先执行的是步骤 5 跳入的 movers_chunk，jumper 再跳入此处
    // ⚠️ 注意：boot 时不编译，仅拷贝构建时已编入 core 的机器码
    // 源代码位置：grub-core/lib/i386/relocator32.S（grub_relocator32_start～_end）

    // 步骤 4: 组装 movers_chunk（分配缓冲区、排序 chunk、拷贝 forward/backward 模板、写 jumper）
    err = grub_relocator_prepare_relocs (rel, get_physical_target_address (ch), &relst, NULL);
    // 功能：
    //   - 在 16MB+ 或 modend 以上分配 movers 缓冲区
    //   - 对 rel->chunks 按 src 排序，按序写入 preamble（i386-pc 为空）、forward/backward 模板、jumper
    //   - forward/backward 为构建时已编译模板，boot 时仅拷贝并设全局变量 dest/src/size；jumper 由 C 写机器码（mov + jmp）
    //   - relst 输出为 movers_chunk 起始地址，步骤 5 将跳入此处，入口不是安全区 relocator32
    // ⚠️ 注意：无运行时编译；执行顺序为 movers_chunk（复制到 0x100000）→ jumper 跳安全区 → relocator32（关分页/加载 GDT/设段/ljmp 到 code32_start）
    // 源代码位置：grub-core/lib/relocator.c:grub_relocator_prepare_relocs()；模板见 relocator_asm.S、relocator_common_c.c

    if (err)
        return err;

    // 步骤 5: 关可屏蔽中断并跳转到 movers_chunk（relst）
    asm volatile ("cli");
    ((void (*) (void)) relst) ();
    // 功能：
    //   - cli：过渡期内（离开 GRUB → 复制到 0x100000 → relocator32 关分页/换 GDT → 跳内核）禁止可屏蔽中断，避免 IDT/处理程序失效时发生中断导致未定义行为
    //   - relst()：跳转到 movers_chunk 执行，入口不是 relocator32；relocator32 在 jumper 跳入安全区后才执行
    // ⚠️ 注意：与 GRUB 是否默认开中断无关，属过渡期安全措施
    // 源代码位置：relocator.c 同上；relocator 执行顺序见本文「Relocator 执行总览」

    /* Not reached.  */
    return GRUB_ERR_NONE;
}
```

---

### Relocator 数据结构与分配

**Relocator 数据结构（`grub-core/lib/relocator.c:56-65`）：**

```c
struct grub_relocator_chunk {
    grub_phys_addr_t src;     // 当前物理地址（临时位置）
    void *srcv;               // 当前虚拟地址（GRUB 访问用）
    grub_phys_addr_t target;  // 目标物理地址（最终位置）
    grub_size_t size;         // 大小
    // ...
};
```

**Relocator 分配逻辑（`grub-core/loader/i386/linux.c:172-202`）：**

```c
if (relocatable)
{
    // 第一次尝试：在 preferred_address (0x100000 (1MB)) 分配；失败后回退到 16MB+。原因见下文「两个关键问题的详细解答」。
    err = grub_relocator_alloc_chunk_align(relocator, &ch,
                                            preferred_address,  // min_addr = 0x100000 (1MB)
                                            preferred_address,  // max_addr = 0x100000 (1MB)
                                            prot_size, 1,
                                            GRUB_RELOCATOR_PREFERENCE_LOW, 1);
    
    // 如果失败，循环尝试在 0x1000000 (16MB) 以上分配（逐步降低对齐要求）
    for (; err && *align + 1 > min_align; (*align)--)
    {
        grub_errno = GRUB_ERR_NONE;
        err = grub_relocator_alloc_chunk_align(relocator, &ch,
                                                0x1000000 (16MB),           // min_addr = 16MB (硬编码)
                                                UP_TO_TOP32(prot_size), // max_addr = 4GB - size
                                                prot_size, 1 << *align,
                                                GRUB_RELOCATOR_PREFERENCE_LOW, 1);
    }
}
else
{
    // 非可重定位内核：拷贝目标必须为 preferred_address (0x100000 (1MB))
    err = grub_relocator_alloc_chunk_addr(relocator, &ch,
                                            preferred_address,  // target = 0x100000（拷贝目标，见下说明）
                                            prot_size);
    // 如果失败，内核无法加载（无法在 0x100000 或更高处取得一块用于加载，或无法保证 boot 时复制到 0x100000）
}

prot_mode_mem = get_virtual_current_address(ch);    // 临时位置（src，内核先加载到此）
prot_mode_target = get_physical_target_address(ch); // 最终位置（target），boot 时 forward/backward 复制到此
```

**内核 chunk 与 initrd chunk 的创建时机**

- **内核 chunk**：在 **`linux` 命令**第一次加载内核时创建。执行顺序为：读 bzImage 头部 → 算 `prot_size` → 调用 **`allocate_pages(prot_size, ...)`** → 在 `allocate_pages` 内调用 `grub_relocator_alloc_chunk_align` 或 `grub_relocator_alloc_chunk_addr`，**此时即创建内核 chunk 并挂到 `rel->chunks`**，随后才把内核文件（保护模式部分）读进该块内存。因此：**在把内核文件读进内存之前，内核对应的 chunk 已经创建好**。
- **initrd chunk**：**不是在 `grub_initrd_init` 里创建的**。执行 **`initrd` 命令**时顺序为：先 **`grub_initrd_init`**（只算 `initrd_ctx->size`、打开各文件，**不分配 relocator、不创建 chunk**）→ 再 `grub_get_initrd_size`、算 `aligned_size` → 再 **`grub_relocator_alloc_chunk_align(..., aligned_size, ...)`**，**此处才创建 initrd chunk** → 最后 `grub_initrd_load` 把 initrd 写进该块内存。因此：**`grub_initrd_init` 执行时尚未创建任何 chunk；initrd chunk 在同一条 initrd 命令内、在 `grub_initrd_init` 返回之后才创建**。
- **小结**：**linux** 第一次加载内核时，会先创建内核 chunk，再读内核；**grub_initrd_init** 执行时不创建 chunk（此时内核 chunk 已存在，来自之前的 `linux`），initrd chunk 要等到后面的 `grub_relocator_alloc_chunk_align` 才创建。

**拷贝目标 0x100000 的源码依据：**

- **preferred_address 来源**：`grub-core/loader/i386/linux.c` 第 686 行 `preferred_address = GRUB_LINUX_BZIMAGE_ADDR`；`grub/include/grub/i386/linux.h` 定义 `GRUB_LINUX_BZIMAGE_ADDR 0x100000`。即 loader 显式把“最终希望内核所在地址”设为 0x100000。
- **grub_relocator_alloc_chunk_addr 的 target 参数**：非可重定位内核走 `grub_relocator_alloc_chunk_addr(relocator, &ch, preferred_address, prot_size)`（linux.c:195-196）。该函数**第三形参**即 **target**（拷贝目标物理地址）。relocator 内部在 `grub-core/lib/relocator.c:1319` 执行 `chunk->target = target;`，故 `chunk->target = 0x100000`。随后 `get_physical_target_address(ch)` 返回 `chunk->target`（relocator.c:96-98），故 `prot_mode_target = 0x100000`。movers_chunk 里的 forward/backward 按各 chunk 的 `src`/`target` 复制，因此**拷贝目标 0x100000** 即由此 target 参数与 `chunk->target` 决定。
- **grub_relocator_alloc_chunk_align 时 target 的取值**：可重定位内核用 `grub_relocator_alloc_chunk_align(..., preferred_address, preferred_address, ...)` 先尝试在 0x100000 分配；若成功则 `chunk->src = chunk->target = 0x100000`（relocator.c 首段分配逻辑），此时无需复制。若失败并改在 16MB+ 分配，则 `chunk->target` 为本次分配到的地址（16MB+），内核最终运行于该处，不复制到 0x100000。

**kernel 与 initrd 拷贝尺寸的计算（源码依据）**

relocator 为每个 chunk 复制的字节数由 loader 在分配 chunk 时传入的 **size** 决定；该 size 即“需要拷贝的 kernel/initrd 的尺寸”，计算方式如下。

**1. 内核（kernel）拷贝尺寸：prot_size、prot_init_space**

源码：`grub-core/loader/i386/linux.c`（grub_cmd_linux 内，约 751–791 行）。先读 bzImage 头部 `lh`，再算：

```c
// grub-core/loader/i386/linux.c（节选）

setup_sects = lh.setup_sects;   // 头部 setup_sects，未设则默认 4
if (! setup_sects)
  setup_sects = GRUB_LINUX_DEFAULT_SETUP_SECTS;

real_size = setup_sects << GRUB_DISK_SECTOR_BITS;
// real_size = setup 段字节数（1 扇区 = 512）

prot_file_size = grub_file_size (file) - real_size - GRUB_DISK_SECTOR_SIZE;
// 保护模式部分在文件中的长度 = 文件总长 - setup - 1 扇区（boot sector）

if (grub_le_to_cpu16 (lh.version) >= 0x020a) {
  // 2.10+ 协议：使用头部 init_size（内核解压后需要的缓冲区大小）
  prot_size = grub_le_to_cpu32 (lh.init_size);
  prot_init_space = page_align (prot_size);
  if (relocatable)
    preferred_address = grub_le_to_cpu64 (lh.pref_address);
} else {
  // 旧协议：用文件中的保护模式部分长度，并按约 50% 压缩比预留解压空间
  prot_size = prot_file_size;
  prot_init_space = page_align (prot_size) * 3;
}

// 分配时传入的 size = prot_size → chunk->size = prot_size，拷贝字节数即 prot_size
if (allocate_pages (prot_size, &align, min_align, relocatable, preferred_address))
  goto fail;
```

- **prot_size**：传给 `allocate_pages(prot_size, ...)`，即**内核 chunk 的 size**；forward/backward 复制的字节数 = `chunk->size = prot_size`。
  - **协议 ≥ 2.10**：`prot_size = lh.init_size`（boot protocol 头中的 `init_size`，见 `grub/include/grub/i386/linux.h`），表示“解压/运行所需缓冲区大小”。
  - **协议 &lt; 2.10**：`prot_size = prot_file_size`（文件中保护模式部分长度 = 文件大小 − setup − 1 扇区）。
- **prot_init_space**：`page_align(prot_size)` 或旧协议下 `page_align(prot_size) * 3`；用于计算 initrd 允许的起始地址（`addr_min = prot_mode_target + prot_init_space`），**不**直接作为拷贝尺寸。

**2. initrd 拷贝尺寸：initrd_ctx->size、aligned_size**

源码：`grub-core/loader/linux.c`（`grub_initrd_init` 累加 `initrd_ctx->size`）、`grub-core/loader/i386/linux.c`（`grub_cmd_initrd` 内，约 1089–1140 行）。

```c
// grub-core/loader/linux.c: grub_initrd_init() 内

initrd_ctx->size = 0;
for (i = 0; i < argc; i++) {
  initrd_ctx->size = ALIGN_UP (initrd_ctx->size, 4);
  // newc 格式：目录项、newc_head + 文件名、TRAILER 等会累加到 size
  if (grub_memcmp (argv[i], "newc:", 5) == 0) {
    // ... insert_dir、newc_head + name_len、dir_size ...
    grub_add (initrd_ctx->size, ALIGN_UP (sizeof (struct newc_head) + name_len, 4), &initrd_ctx->size);
    grub_add (initrd_ctx->size, dir_size, &initrd_ctx->size);
  } else if (newc) {
    grub_add (initrd_ctx->size, ALIGN_UP (sizeof (struct newc_head) + sizeof ("TRAILER!!!"), 4), &initrd_ctx->size);
  }
  initrd_ctx->components[i].size = grub_file_size (initrd_ctx->components[i].file);
  grub_add (initrd_ctx->size, initrd_ctx->components[i].size, &initrd_ctx->size);
}
// 若有 newc，最后再加 TRAILER 头
if (newc)
  grub_add (initrd_ctx->size, ALIGN_UP (sizeof (struct newc_head) + sizeof ("TRAILER!!!"), 4), &initrd_ctx->size);

// grub-core/loader/linux.c: grub_get_initrd_size()
return initrd_ctx->size;

// grub-core/loader/i386/linux.c: grub_cmd_initrd() 内
size = grub_get_initrd_size (&initrd_ctx);
aligned_size = ALIGN_UP (size, 4096);
// 分配 initrd chunk 时传入 size = aligned_size → chunk->size = aligned_size，拷贝字节数 = aligned_size
err = grub_relocator_alloc_chunk_align (relocator, &ch, addr_min, addr, aligned_size, 0x1000, ...);
```

- **initrd_ctx->size**：所有 initrd 组件在 **cpio newc** 镜像中的总长度（每个文件前有 newc 头 + 4 字节对齐，多文件时可能有 TRAILER 等）。
- **aligned_size**：`ALIGN_UP(size, 4096)`，作为 **initrd chunk 的 size** 传入 `grub_relocator_alloc_chunk_align(..., aligned_size, ...)`；forward/backward 复制的字节数 = `chunk->size = aligned_size`。实际有效载荷为 `size`，多出的为对齐填充。

**3. 小结**

| 对象 | 拷贝尺寸（chunk->size） | 计算来源 | 源码位置 |
|------|-------------------------|----------|----------|
| 内核 | prot_size | 协议 ≥2.10：lh.init_size；否则：grub_file_size(file) − real_size − 1 扇区 | linux.c:757-791 |
| initrd | aligned_size = ALIGN_UP(size, 4096) | size = initrd_ctx->size（grub_initrd_init 累加：各文件大小 + newc 头/目录/TRAILER） | linux.c:1089-1090、1141；loader/linux.c:180-251、265-267 |

**`grub_relocator_alloc_chunk_align()` 内部逻辑（`grub-core/lib/relocator.c:1375-1508`）：**

```c
grub_relocator_alloc_chunk_align(rel, out, min_addr, max_addr, size, align, ...)
{
    // 步骤 1: 尝试在 [min_addr, max_addr] 范围内直接分配
    // 调用 malloc_in_range() 扫描 GRUB 内存管理器的空闲块
    if (malloc_in_range(rel, min_addr, max_addr, align, size, chunk, ...))
    {
        // 成功：src = target = 分配到的地址
        chunk->target = chunk->src;
        return GRUB_ERR_NONE;
    }
    
    // 步骤 2: 如果直接分配失败，调整范围避开已分配的 chunk
    adjust_limits(rel, &min_addr2, &max_addr2, min_addr, max_addr);
    
    // 步骤 3: 在调整后的范围内分配临时位置（src）
    malloc_in_range(rel, min_addr2, max_addr2, align, size, chunk, ...);
    
    // 步骤 4: 通过 mmap 迭代器查找合适的目标位置（target）
    // target 可能与 src 不同
    grub_mmap_iterate(grub_relocator_alloc_chunk_align_iter, &ctx);
    
    // 步骤 5: 如果 src != target，记录需要的 relocator 代码大小
    if (chunk->src < chunk->target)
        rel->relocators_size += grub_relocator_backward_size;
    if (chunk->src > chunk->target)
        rel->relocators_size += grub_relocator_forward_size;
}
```

**为什么在 0x100000 (1MB) 分配会失败？**

关键在于 GRUB 内存初始化时**根本不会将 0x100000 (1MB) 区域添加到空闲内存池**。

**GRUB 内存布局（`grub-core/kern/i386/pc/init.c`）：**

```
0x100000 (1MB) ─────────────────────────────────┐
│ GRUB 代码（_start 到 _edata）            │ ← GRUB_MEMORY_MACHINE_DECOMPRESSION_ADDR
│ （解压后约 20-50 KB）                    │
├─ grub_modbase ─────────────────────────┤ ← 0x100000 (1MB) + (_edata - _start)
│ GRUB 内置模块数据                        │   例如：0x100000 (1MB) + 0x8000 = 0x108000
│ （大小取决于加载的模块数量）              │
├─ modend ───────────────────────────────┤ ← grub_modbase + modinfo->size
│                                         │   例如：0x108000 + 0x10000 = 0x118000（约 1.1MB）
│ 空闲内存（由 grub_mm_init_region 管理）  │ ← 只有这部分被添加到内存池！
└─────────────────────────────────────────┘

注意：modend 通常在 0x100000 (1MB) + 几百 KB 范围内（约 1.1-1.5 MB），
      而不是 16MB。16MB 是 relocator 分配临时缓冲区时的最小地址。
```

**内存池初始化代码（`grub-core/kern/i386/pc/init.c:259-268`）：**

```c
// grub_machine_init() 中的关键代码
modend = grub_modules_get_end ();  // 获取 GRUB 模块的结束地址

for (i = 0; i < num_regions; i++)
{
    grub_addr_t beg = mem_regions[i].addr;
    grub_addr_t fin = mem_regions[i].addr + mem_regions[i].size;
    
    // ⚠️ 关键：将起始地址调整到 modend 之后
    if (modend && beg < modend)
        beg = modend;
    
    if (beg >= fin)
        continue;
    
    // 只初始化 modend 之后的区域为空闲内存
    grub_mm_init_region ((void *) beg, fin - beg);
}
```

**两个关键问题的详细解答：**

**问题 1：既然 GRUB 代码在 0x100000 (1MB)，为什么还要尝试 preferred_address？**

虽然 GRUB 代码确实在 0x100000 (1MB)，但代码仍会尝试在这个地址分配，原因如下：

1. **代码路径统一**：
   - 可重定位内核（`relocatable = true`）理论上可以在不同地址加载
   - 代码逻辑统一处理，先尝试首选地址，失败后再回退
   - 这样代码更简洁，不需要特殊判断

2. **兼容性考虑**：
   - 某些特殊系统配置可能允许在 0x100000 (1MB) 分配（例如 GRUB 代码已被清理）
   - 某些嵌入式系统或特殊引导场景可能有不同的内存布局
   - 保持代码的通用性，不假设所有情况都会失败

3. **实际运行情况**：
   - **在标准 PC 系统上，这个尝试几乎总是失败**（因为 GRUB 代码占用）
   - 但代码仍会执行这个尝试，然后立即回退到 16MB 以上
   - 性能影响可忽略（只是一次内存分配尝试）

4. **非可重定位内核的情况**：
   - 如果内核不可重定位（`relocatable = false`），必须精确在 0x100000 (1MB)
   - 这种情况下，如果 0x100000 (1MB) 被占用，分配会直接失败，内核无法加载
   - 可重定位内核的优势就是可以回退到其他地址

**问题 2：如何分析代码得出 16MB？**

16MB 是**硬编码在源代码中的值**，分析过程如下：

1. **源代码位置**：
   ```c
   // grub-core/loader/i386/linux.c:805
   err = grub_relocator_alloc_chunk_align(relocator, &ch,
                                           0x1000000 (16MB),  // ← 这里就是 16MB
                                           UP_TO_TOP32(prot_size),
                                           ...);
   ```

2. **数值计算**：
   ```
   0x1000000 (16MB) = 16 * 1024 * 1024 = 16,777,216 字节 = 16 MB
   ```

3. **为什么选择 16MB？**
   - **避开 GRUB 区域**：GRUB 代码在 0x100000 (1MB) 到约 0x118000（约 1.1MB），16MB 远高于此
   - **避开系统保留区域**：BIOS 可能在某些低地址区域保留内存（如 ACPI、BIOS 数据等）
   - **安全边界**：16MB 是一个常见的"安全边界"，确保有足够的连续内存空间
   - **历史原因**：早期 Linux 内核解压目标地址通常是 16MB（`CONFIG_PHYSICAL_START` 默认值）
   - **对齐考虑**：16MB 是 2^24，便于内存对齐和地址计算

4. **代码分析步骤**：
   - 在 GRUB 源代码中搜索 `0x1000000 (16MB)`
   - 找到 `grub-core/loader/i386/linux.c` 中的分配逻辑
   - 查看上下文，理解这是 fallback 地址
   - 计算 `0x1000000 (16MB)` 的十进制值：16 * 1024 * 1024 = 16 MB

5. **实际验证**：
   - 可以通过调试 GRUB 或查看内存映射来验证
   - 在 GRUB 命令行执行 `lsmem` 或查看内存布局
   - 确认临时缓冲区确实在 16MB 以上

**`grub_modules_get_end()` 实现（`grub-core/kern/main.c:44-54`）：**

```c
grub_addr_t
grub_modules_get_end (void)
{
    modinfo = (struct grub_module_info *) grub_modbase;
    if ((modinfo == 0) || modinfo->magic != GRUB_MODULE_MAGIC)
        return grub_modbase;
    return grub_modbase + modinfo->size;  // GRUB 模块结束地址
}
```

**`grub_modbase` 初始化（`grub-core/kern/i386/pc/init.c:229`）：**

```c
grub_modbase = GRUB_MEMORY_MACHINE_DECOMPRESSION_ADDR + (_edata - _start);
// = 0x100000 (1MB) + GRUB 代码大小
```

**总结**：0x100000 (1MB) 到 `modend` 之间的区域**从未被 `grub_mm_init_region()` 添加到空闲内存池**，
所以 `malloc_in_range()` 在扫描空闲块列表时找不到这个区域，分配自然失败。

**Relocator 内存布局总结：**

| 项目 | 位置 | 说明 |
|------|------|------|
| **临时缓冲区** | 通常 0x1000000 (16MB) 以上 | 因为 GRUB 占用 0x100000 (1MB) |
| **最终目标** | 0x100000 (1MB) | `GRUB_LINUX_BZIMAGE_ADDR` |
| **大小** | `prot_size`（内核压缩大小） | 由内核头部 `init_size` 字段决定 |

**⚠️ 内核解压不由 relocator 完成：** relocator 只把**仍为压缩状态**的内核复制到 0x100000 并跳转到 `code32_start`；gzip 解压由内核自身的代码（如 `arch/x86/boot/compressed/` 中的 startup_32）在跳转之后执行。详见 [GRUB_KERNEL_LOADING.md](GRUB_KERNEL_LOADING.md) 中「内核文件的解压缩在哪一步完成」。

---

### 关键问题解答

**问题 1：relocator 代码具体对应哪个文件？**

**答案：** 安全区中执行的是 **由 relocator32.S 编译得到的机器码** 的副本（源码文件 `grub-core/lib/i386/relocator32.S`）。**复制内核**的代码来自 **relocator_asm.S**（forward/backward 模板）；movers_chunk 内的 preamble 与 jumper 由 **relocator_common_c.c** 写入。二者均在 movers_chunk 中，详见上文「两处 relocator 代码来源对照」。relocator32.S 的执行顺序与具体代码分析见下文本问题内「relocator32.S 完整源代码分析」。

**编译过程**：relocator32.S 在 **GRUB 构建时**（`make`）由 Makefile 纳入 relocator 相关模块（见 `grub-core/Makefile.core.def` 中 relocator 相关项），经 as/gcc 编译、链接进 GRUB core，生成 relocator32 代码段（入口符号 `grub_relocator32_start`，大小由宏 `RELOCATOR_SIZEOF(32)` 给出）。**boot 时不编译**；在 `grub_relocator32_boot()` 中通过 `grub_memmove(安全区, &grub_relocator32_start, RELOCATOR_SIZEOF(32))` 将上述机器码拷贝到安全区，该函数还负责分配安全区、设置寄存器状态、组装 movers_chunk 并跳转等。编译与运行时的完整区分见 [GRUB_RELOCATOR_BUILD_AND_RUNTIME.md](GRUB_RELOCATOR_BUILD_AND_RUNTIME.md)。

**relocator32 内嵌 GDT 说明（源码依据）**

relocator32 加载的 GDT **不是空表**，也不提供“基础服务”；只包含**最小平坦段**（NULL、Reserved、代码段、数据段），供内核入口（code32_start）期望的 32 位保护模式使用。

- **定义文件**：`grub-core/lib/i386/relocator32.S` 第 118–132 行（注释写 “GDT. Copied from loader/i386/linux.c”，实际 GDT 表体在该文件中内联定义）；加载逻辑在 `grub-core/lib/i386/relocator_common.S` 的 **RELOAD_GDT** 宏（计算拷贝后 GDT 地址、填 gdtdesc、`lgdt`、`ljmp` 更新 CS）。
- **表内容**（4 项，每项 8 字节；Intel 段描述符布局：Limit[0:15]、Base[0:15]、Base[16:23]、Access、Limit[16:19]+Flags、Base[24:31]）：

| 索引 | 选择子 | 源码字节（relocator32.S） | 含义 |
|------|--------|---------------------------|------|
| 0 | — | 全 0 | **NULL**：空描述符，不可用。 |
| 1 | — | 全 0 | **Reserved**：保留，未用。 |
| 2 | 0x10 | `FF FF 00 00 00 9A CF 00` | **Code**：基址=0，界限=0xFFFFF，粒度 G=1（×4KB⇒ 4GB），D=1（32 位），类型=0x9A（可执行+可读、非一致、DPL=0）。 |
| 3 | 0x18 | `FF FF 00 00 00 92 CF 00` | **Data**：基址=0，界限=0xFFFFF，G=1⇒4GB，D=1，类型=0x92（可读+可写、向上扩展、DPL=0）。 |

- **与 GDT 的关系**：Code 段和 Data 段**就是 GDT 表里的两项**。GDT 是一块连续内存，每项 8 字节为一段描述符。选择子 0x10、0x18 是**索引**（0x10÷8＝2、0x18÷8＝3）：CS＝0x10 时 CPU 用 **GDT[2]** 作为当前代码段，DS/ES/SS 等＝0x18 时 CPU 用 **GDT[3]** 作为当前数据段。取指或访存时 CPU 用段寄存器里的选择子查 GDT，取出对应描述符得到基址/界限/属性；真正定义“基址 0、4GB”的是 GDT 里这两项，0x10/0x18 只是指向它们的下标。
- **这两项的用途**：**Code 段（0x10）** 给 **CS** 用——relocator 用 `ljmp` 把 CS 设为 0x10，之后内核入口（code32_start）的取指就用 GDT[2]，基址 0、4GB，等于“整个 32 位地址空间都是代码段”。**Data 段（0x18）** 给 **DS、ES、FS、GS、SS** 用——relocator32 里 `movl $DATA_SEGMENT, %eax` 再赋给这些段寄存器，内核用它们访问数据、栈；同样是基址 0、4GB，线性地址＝有效地址。合起来：关分页并加载此 GDT、设好 CS/DS/SS 后，CPU 处于 32 位保护模式下的平坦段状态，relocator 再 `ljmp` 到 code32_start，内核即可按协议运行；没有这两个描述符或不是平坦段，跳过去会出错。
- **结论**：仅满足内核 32 位入口对段寄存器的要求（平坦代码段 + 平坦数据段），无其它服务。

**relocator32.S 完整源代码分析**

源码文件：`grub-core/lib/i386/relocator32.S`（含 `#include "relocator_common.S"`）；宏 PREAMBLE、RELOAD_GDT、DISABLE_PAGING 定义在 `grub-core/lib/i386/relocator_common.S`。jumper 跳入安全区后从 `grub_relocator32_start` 执行，顺序如下。

```asm
# grub-core/lib/i386/relocator32.S（节选，与 relocator_common.S 宏展开对应）
	.p2align	4
VARIABLE(grub_relocator32_start)
	PREAMBLE              # 步骤 1：见下 relocator_common.S

	RELOAD_GDT            # 步骤 2：见下 relocator_common.S
	.code32
	/* Update other registers. */
	movl	$DATA_SEGMENT, %eax   # 步骤 3：设数据段选择子
	movl	%eax, %ds
	movl	%eax, %es
	movl	%eax, %fs
	movl	%eax, %gs
	movl	%eax, %ss

	DISABLE_PAGING        # 步骤 4：见下 relocator_common.S

	# 步骤 5（可选）：__x86_64__ 时关 amd64 MSR；然后关 PAE（cr4）
	# 步骤 6：从 VARIABLE(grub_relocator32_*) 读值赋给 esp/ebp/esi/edi/eax/ebx/ecx/edx
	.byte	0xb8
VARIABLE(grub_relocator32_esp)
	.long	0
	movl	%eax, %esp
	# … 同理 ebp、esi、edi、eax、ebx、ecx、edx …

	cld                   # 步骤 7：清方向标志
	.byte	0xea            # 步骤 8：JMP far（远跳转）操作码，见下说明
VARIABLE(grub_relocator32_eip)
	.long	0               # 偏移：由 C 侧写入，见下说明
	.word	CODE_SEGMENT    # 段选择子 0x10

LOCAL(gdt):               # 文件末尾：内联 GDT，由 RELOAD_GDT 中 lgdt 加载
	.byte 0x00, 0x00, ...  # NULL、Reserved、Code 0x10、Data 0x18
LOCAL(gdt_end):
VARIABLE(grub_relocator32_end)
```

**步骤 8 说明（0xea 与 grub_relocator32_eip）：**

- **0xea**：x86 操作码，对应 **JMP far**（远跳转，Intel 手册中的 JMP ptr16:32）。指令为 6 字节：`0xea` + 4 字节偏移（EIP）+ 2 字节段选择子（CS）；执行后 CS ← CODE_SEGMENT（0x10），EIP ← 偏移，即跳转到 (段:偏移) 处（内核 32 位入口）。
- **grub_relocator32_eip 的值来源**：在 `grub_relocator32_boot()` 的步骤 2 中，C 侧执行 `grub_relocator32_eip = state.eip`；`state.eip` 由调用方（如 `grub_linux_boot()`）传入，为内核入口点 **code32_start**。该全局变量在 relocator32 代码段内对应上述 `.long 0` 槽位；写入后，步骤 3 的 `grub_memmove(安全区, &grub_relocator32_start, ...)` 会把已含 code32_start 的这段机器码拷贝到安全区，故安全区执行到此处时远跳转目标即为 code32_start。源代码位置：`grub-core/lib/i386/relocator.c` 中 `grub_relocator32_eip = state.eip`；`state.eip` 在 `grub-core/loader/i386/linux.c` 的 `grub_linux_boot()` 里按 boot protocol 计算并传入。

**确认 state.eip（grub_relocator32_eip）以 0x100000 为基址的过程**

“按约定应该是 0x100000”指的是**镜像加载基址**为 0x100000，**state.eip = code32_start = 0x100000 + 偏移**（32 位入口的物理地址）。确认过程如下（源码：`grub-core/loader/i386/linux.c`）：

1. **state.eip 的赋值**（约 660 行）：`state.eip = ctx.params->hdr.code32_start`。`ctx.params` 是 boot_params 的副本（整块 `linux_params` 在 `grub_linux_boot()` 里拷入 real_mode 区），故 **state.eip = linux_params.hdr.code32_start**。
2. **code32_start 的计算**（约 824 行，在 `grub_cmd_linux()` 中）：  
   `linux_params.hdr.code32_start = prot_mode_target + lh.code32_start - GRUB_LINUX_BZIMAGE_ADDR`。  
   - **prot_mode_target**：来自 `get_physical_target_address(ch)`，即内核 chunk 的 **target**（拷贝目标）。非可重定位内核时由 `grub_relocator_alloc_chunk_addr(..., preferred_address, ...)` 传入 **0x100000**，故 **prot_mode_target = 0x100000**（见上文「拷贝目标 0x100000 的源码依据」）。  
   - **GRUB_LINUX_BZIMAGE_ADDR**：`grub/include/grub/i386/linux.h` 定义为 **0x100000**。  
   - **lh.code32_start**：bzImage 头部字段，表示“镜像**按协议默认加载在 0x100000 时**，32 位入口相对该基址的偏移”或“该情形下的入口物理地址”（即 0x100000 + 偏移）。  
   因此 **code32_start = 0x100000 + (lh.code32_start - 0x100000) = 0x100000 + 偏移**，即 **state.eip 以 0x100000 为基址**。
3. **结论**：**grub_relocator32_eip = state.eip = code32_start = 0x100000 + 偏移**；基址 0x100000 由 **prot_mode_target = 0x100000** 与 **GRUB_LINUX_BZIMAGE_ADDR = 0x100000** 保证，与“内核最终放在 0x100000”的约定一致。

**relocator_common.S 宏（节选）：**

```asm
# grub-core/lib/i386/relocator_common.S

	.macro DISABLE_PAGING
	movl	%cr0, %eax
	andl	$(~GRUB_MEMORY_CPU_CR0_PAGING_ON), %eax
	movl	%eax, %cr0
	.endm

	.macro PREAMBLE
LOCAL(base):
	mov	RAX, RSI                    # 保存“当前基址”（jumper 跳入时由调用约定传入）
	add	$(LOCAL(cont0) - LOCAL(base)), RAX
	jmp	*RAX                         # 跳到 cont0，使后续指令使用拷贝后的地址
LOCAL(cont0):
	.endm

	.macro RELOAD_GDT
	lea	(LOCAL(cont1) - LOCAL(base)) (RSI, 1), RAX
	movl	%eax, (LOCAL(jump_vector) - LOCAL(base)) (RSI, 1)   # 填 ljmp 目标
	lea	(LOCAL(gdt) - LOCAL(base)) (RSI, 1), RAX
	mov	RAX, (LOCAL(gdt_addr) - LOCAL(base)) (RSI, 1)       # 填 GDT 基址（拷贝后）
	lgdt	(LOCAL(gdtdesc) - LOCAL(base)) (RSI, 1)            # 加载 GDT
	ljmp	*(LOCAL(jump_vector) - LOCAL(base)) (RSI, 1)       # 更新 CS 到 CODE_SEGMENT
	# gdtdesc: .word gdt_end - gdt；gdt_addr / jump_vector 占位
LOCAL(cont1):
	.endm
```

**步骤与功能简述：**

| 步骤 | 代码/宏 | 功能 | 源代码位置 |
|------|---------|------|------------|
| 1 | PREAMBLE | 以“当前基址”做相对跳转到 cont0，使后续指令在拷贝后的安全区地址下执行（位置无关） | relocator_common.S:37-52 |
| 2 | RELOAD_GDT | 计算拷贝后 GDT 与 cont1 的地址，填 gdtdesc/gdt_addr/jump_vector，`lgdt` 后 `ljmp` 更新 CS 到 CODE_SEGMENT | relocator_common.S:54-110；GDT 表体在 relocator32.S:120-132 |
| 3 | movl $DATA_SEGMENT, %eax 及 ds/es/fs/gs/ss | 设置数据段选择子为 0x18（GDT 第 3 项） | relocator32.S:34-39 |
| 4 | DISABLE_PAGING | 清 CR0 分页位，关闭分页 | relocator_common.S:31-36 |
| 5 | 可选关 PAE/amd64 MSR | 关 CR4 PAE；x86_64 构建时再关 amd64 长模式 MSR | relocator32.S:44-55 |
| 6 | VARIABLE(grub_relocator32_*)、mov 到 reg | 从 C 侧写入的全局变量位置读 esp/ebp/esi/edi/eax/ebx/ecx/edx（含 ESI=boot_params、EIP 目标=code32_start） | relocator32.S:61-109 |
| 7 | cld | 清方向标志，满足内核入口约定 | relocator32.S:113 |
| 8 | .byte 0xea（JMP far）+ VARIABLE(grub_relocator32_eip)（.long 偏移）+ .word CODE_SEGMENT | 远跳转到 code32_start；0xea 为 JMP far 操作码，偏移值由 C 侧在拷贝前写入（grub_relocator32_eip = state.eip），见上「步骤 8 说明」 | relocator32.S:115-118 |

不负责复制内核；复制由 movers_chunk 内 forward/backward 完成。GDT 表内容与 Code/Data 段用途见上「relocator32 内嵌 GDT 说明」。

**问题 2：为什么要复制？**

**答案：** 因为 GRUB 的代码在 0x100000 (1MB)+，复制到 0x100000 的内核会覆盖 GRUB；relocator 必须在 1MB 以下运行才能先完成复制再跳转。详见上文「为什么在 BIOS/Legacy 下一定要有 relocate 过程？」（尤其是「3. 冲突与必须先 relocate」「4. 为何 relocator 代码必须在 1MB 以下」）。

**⚠️ UEFI 启动方式完全不同：**

**UEFI 不需要 relocator 机制**，原因如下：

1. **运行模式不同**：
   - **BIOS 启动**：GRUB 在保护模式下运行，内核入口点（code32_start）为 32 位保护模式，需 relocator 关分页、加载内嵌 GDT、设段后再跳转
   - **UEFI 启动**：GRUB 和内核都在保护模式/长模式下运行，不需要模式切换

2. **启动方式不同**：
   - **BIOS 启动**：使用 relocator 代码手动跳转到内核入口点
   - **UEFI 启动**：使用 EFI 的 `StartImage` 服务（`grub_efi_system_table->boot_services->start_image()`）

3. **源代码位置**：
   - **BIOS 启动**：`grub/grub-core/loader/i386/linux.c` → `grub_relocator32_boot()`
   - **UEFI 启动**：`grub/grub-core/loader/efi/linux.c` → `grub_arch_efi_linux_boot_image()` → `grub_efi_start_image()`

4. **UEFI 启动流程**（`grub/grub-core/loader/efi/linux.c:194-280`）：
   ```c
   grub_arch_efi_linux_boot_image (grub_addr_t addr, grub_size_t size, char *args)
   {
       // 步骤 1: 创建内存映射设备路径
       mempath = grub_malloc (2 * sizeof (grub_efi_memory_mapped_device_path_t));
       mempath[0].start_address = addr;  // 内核地址
       mempath[0].end_address = addr + size;
       
       // 步骤 2: 使用 EFI LoadImage 服务加载内核
       status = grub_efi_load_image (0, grub_efi_image_handle,
                                     (grub_efi_device_path_t *) mempath,
                                     (void *) addr, size, &image_handle);
       
       // 步骤 3: 设置命令行参数（转换为 UTF-16）
       loaded_image = grub_efi_get_loaded_image (image_handle);
       loaded_image->load_options = ...;  // 内核命令行参数
       
       // 步骤 4: 使用 EFI StartImage 服务启动内核
       // ⚠️ 关键：这是 EFI 固件提供的服务，不需要 relocator
       status = grub_efi_start_image (image_handle, 0, NULL);
       // 如果成功，不会返回（控制权转移到内核）
   }
   ```

5. **为什么 UEFI 不需要 relocator？**
   - **EFI 服务处理**：`StartImage` 服务由 EFI 固件实现，负责：
     - 设置正确的 CPU 状态（寄存器、段、分页等）
     - 准备内核执行环境
     - 跳转到内核入口点
   - **内存管理**：EFI 使用 `ExitBootServices()` 将内存控制权交给内核，GRUB 代码可以被覆盖
   - **标准协议**：UEFI 定义了标准的启动协议，内核以 EFI 可执行文件格式加载

6. **UEFI 是否需要复制内核？** 不需要。内核由 EFI 分配到任意地址，经 `LoadImage`/`StartImage` 启动，不要求 0x100000。Legacy 与 UEFI 下 bzImage 的两种用法与涉及代码见下文「bzImage 必须放在 0x100000 与 UEFI 不矛盾」及「涉及代码一览」。

7. **对比总结**：

| 特性 | BIOS 启动 | UEFI 启动 |
|------|----------|----------|
| **GRUB 运行模式** | 保护模式 | 保护模式/长模式 |
| **内核入口点模式** | 32 位保护模式（如 startup_32） | 保护模式/长模式（EFI stub） |
| **是否需要模式切换** | ✅ 是（GRUB 保护模式→关分页/加载 relocator 内嵌 GDT→跳 code32_start） | ❌ 否 |
| **跳转方式** | relocator 代码手动跳转 | EFI `StartImage` 服务 |
| **relocator 机制** | ✅ 需要 | ❌ 不需要 |
| **源代码文件** | `loader/i386/linux.c` | `loader/efi/linux.c` |
| **关键函数** | `grub_relocator32_boot()` | `grub_efi_start_image()` |

**bzImage 必须放在 0x100000 与 UEFI 不矛盾（源码依据）**

“bzImage 必须放在 0x100000”指的是 **Legacy BIOS 启动协议**下的约定；**UEFI 启动走的是另一套协议、另一种入口**，同一份磁盘上的 vmlinuz 在两种路径下被当作**两种“镜像形态”**使用，因此不矛盾。

1. **同一文件、两种用法**  
   磁盘上的 vmlinuz 是 **hybrid**：既有 Legacy 用的 boot sector + setup + 压缩镜像，也有 **PE/COFF 头 + EFI stub**（需内核配置 `CONFIG_EFI_STUB`）。  
   - **Legacy 路径**：GRUB 用 `grub-core/loader/i386/linux.c`，按 **Linux 实模式/保护模式 boot protocol** 加载；协议规定 setup + 压缩镜像放在 **0x100000**，`code32_start` 等按此地址算，故必须先 relocate 到 0x100000。  
   - **UEFI 路径**：GRUB 用 `grub-core/loader/efi/linux.c`，**先检查 PE 魔数**（`GRUB_PE32_MAGIC`）；若不是 PE/COFF 则直接报错 "plain image kernel not supported - rebuild with CONFIG_(U)EFI_STUB enabled"（`efi/linux.c` 约 106–107 行）。即：UEFI 下 **只认“带 EFI stub 的 PE 镜像”**，不按“放在 0x100000 的 bzImage”那一套来。

2. **GRUB UEFI 加载方式（源码）**  
   - `grub-core/loader/efi/linux.c`：`kernel_addr = grub_efi_allocate_any_pages (...)`（约 537 行）→ 内核被分配到**任意可用页**，**不是**固定 0x100000。  
   - `grub_file_read (file, kernel_addr, kernel_size)` 把整个文件读入该缓冲区。  
   - `grub_arch_efi_linux_boot_image ((grub_addr_t) kernel_addr, kernel_size, linux_args)` 里调用 `grub_efi_load_image (0, ..., (void *) addr, size, &image_handle)`（约 220–223 行），即告诉固件“镜像已在 `addr`”；再 `grub_efi_start_image (image_handle, 0, NULL)`（约 255 行），固件从 **PE 头里的 AddressOfEntryPoint** 跳转，**不是**从 Legacy 的 setup/code32_start 跳转。

3. **内核侧：PE 入口是 EFI stub，不是 setup**  
   - Linux `arch/x86/boot/header.S`（约 86 行）：PE 可选头里 **AddressOfEntryPoint** = `setup_size + ZO_efi_pe_entry`（64 位）或 `.compat` 里 `setup_size + ZO_efi32_pe_entry`（32 位 stub）。即 **PE 入口是压缩镜像内的 efi_pe_entry/efi32_pe_entry**，不是实模式 setup。  
   - `arch/x86/boot/startup/efi-mixed.S`：`efi32_pe_entry` / `efi_stub_entry` 等是 EFI 环境下的入口，接收 (image_handle, system_table)，不依赖“镜像必须位于 0x100000”；stub 里再切长模式、解压、交权给 vmlinux。  
   - 因此：**0x100000** 在 Legacy 协议里是“setup + 压缩镜像”的加载地址；在 UEFI 协议里 **PE 镜像可放在任意地址**，固件按 PE 入口跳转到 stub，stub 与后续解压代码自会处理重定位（如 `LOAD_PHYSICAL_ADDR` 等用于解压后的内核，与“bzImage 文件放在哪”无关）。

4. **小结**  
   - **0x100000** 是 **Legacy boot protocol** 的约定，只约束 `loader/i386/linux.c` 那条路径。  
   - **UEFI 路径** 约束的是“带 EFI stub 的 PE 镜像 + LoadImage/StartImage”，加载地址由固件/GRUB 分配（`allocate_any_pages`），不要求 0x100000。  
   - 因此：“bzImage 必须放在 0x100000”与“UEFI 下内核可放在任意地址”**不矛盾**——前者指 Legacy 协议下的必须行为，后者指 UEFI 协议下的行为；同一文件在不同路径下被用成两种形态。

**涉及代码一览（两套协议对应的 GRUB / 内核代码）：**

| 路径 | 项目 | 文件 / 符号 / 函数 | 说明 |
|------|------|--------------------|------|
| **Legacy** | GRUB 0x100000 约定 | `grub/include/grub/i386/linux.h`：`GRUB_LINUX_BZIMAGE_ADDR` | 定义为 0x100000 |
| **Legacy** | GRUB 加载与 relocate | `grub-core/loader/i386/linux.c`：`grub_cmd_linux`、`allocate_pages`、`preferred_address`、`prot_mode_target`、`code32_start` 计算 | 见 [GRUB_KERNEL_LOADING.md](GRUB_KERNEL_LOADING.md) grub_cmd_linux / grub_linux_boot |
| **Legacy** | GRUB 跳转 | `grub-core/loader/i386/linux.c`：`grub_linux_boot` → `grub_relocator32_boot` | 复制到 0x100000 后跳 code32_start |
| **Legacy** | 内核入口 | Linux 源码 `linux/arch/x86/boot/header.S`（setup）、`linux/arch/x86/boot/compressed/head_64.S`（code32_start 指向的压缩内核入口 startup_32 等） | 协议约定镜像在 0x100000 |
| **UEFI** | GRUB PE 检查 | `grub-core/loader/efi/linux.c`：`grub_arch_efi_linux_load_image_header`，`GRUB_PE32_MAGIC`（约 105–107 行） | 非 PE 则报错或回退 legacy |
| **UEFI** | GRUB 分配与读入 | `grub-core/loader/efi/linux.c`：`grub_efi_allocate_any_pages`（约 537 行）、`grub_file_read (file, kernel_addr, kernel_size)` | 任意地址，非 0x100000 |
| **UEFI** | GRUB 启动 | `grub-core/loader/efi/linux.c`：`grub_arch_efi_linux_boot_image`，`grub_efi_load_image`（约 220–223 行），`grub_efi_start_image`（约 255 行） | 固件按 PE 入口跳转 |
| **UEFI** | 内核 PE 入口 | Linux 源码 `linux/arch/x86/boot/header.S`：PE 可选头 `AddressOfEntryPoint` = `setup_size + ZO_efi_pe_entry` / `ZO_efi32_pe_entry`（约 86、176 行） | 入口为 EFI stub，非 setup |
| **UEFI** | 内核 stub 实现 | Linux 源码 `linux/arch/x86/boot/startup/efi-mixed.S`：`efi32_pe_entry`、`efi_stub_entry` 等 | 接收 (image_handle, system_table)，不依赖 0x100000 |

以上在本文「为什么在 BIOS/Legacy 下一定要有 relocate 过程？」「bzImage 必须放在 0x100000 与 UEFI 不矛盾」及 [GRUB_KERNEL_LOADING.md](GRUB_KERNEL_LOADING.md) 的 grub_cmd_linux（i386/efi）、grub_linux_boot、UEFI 启动流程等小节中均有说明。

**问题 3：直接跳转到内核入口点地址（code32_start）不行吗？**

**答案：** 不行。原因如下：

1. **运行状态不匹配**：
   - GRUB 在保护模式下运行，其 GDT、分页、段与内核约定可能不同
   - 内核入口点（`code32_start`，如 startup_32）期望 32 位保护模式下的特定状态（关分页、平坦段、ESI = boot_params 等）
   - 不能直接 jmp，需要 relocator 先关分页、加载内嵌 GDT、设段与寄存器再 ljmp

2. **段与分页状态**：GRUB 的 GDT/分页与内核期望不同；跳转前需禁用分页、加载 relocator 内嵌的 GDT、设段与栈。

3. **栈和寄存器状态**：
   - 内核期望特定的寄存器状态（如 `ESI` 包含 `boot_params` 地址）
   - 需要设置正确的栈指针（ESP）
   - relocator 代码负责设置这些状态

**relocator 代码的组成与作用：**

- **movers_chunk**（由 `grub_relocator_prepare_relocs()` 在步骤 4 生成）：`preamble` + `forward/backward` 复制代码（若 src ≠ target，每 chunk 一段）+ `jumper`（跳转到安全区）。负责把内核从临时区（16MB+）复制到 0x100000，再跳入安全区。
- **安全区 relocator32 副本**：关分页、加载内嵌 GDT、设段与寄存器、设置 ESI = boot_params、ljmp 到 code32_start。执行顺序见上文「Relocator 执行总览」。

**为什么要动态生成？**

1. **src/target 每次启动都不同**：内核、initrd 的临时缓冲区（src）由本次启动的内存分配决定（例如 0x1000000 (16MB) 或 0x2000000）；目标（target）固定为 0x100000 (1MB) 等，但“要不要搬、从哪搬到哪”是运行时才知道的。
2. **chunk 数量和顺序不固定**：有内核 chunk、可能有 initrd chunk 等；每个 chunk 的 src/target/size 不同，需要为每个“src ≠ target”的 chunk 生成一段复制代码。
3. **必须选 forward 或 backward**：若 src < target 只能从高向低复制（backward），否则会覆盖未复制区域；若 src > target 用从低向高（forward）。选哪种、以及多段复制的顺序（按 src 排序后依次执行）都要在运行时根据当前 rel 里的 chunk 决定。
4. **无法用一段静态代码写死**：若用静态代码，无法在编译期填入“本次启动”的 src/target/size，也无法在编译期决定要几段、每段是 forward 还是 backward。因此必须在运行时把“模板代码 + 本次的 src/target/size”组合成实际要执行的指令序列。

**`grub_relocator_prepare_relocs()` 概要**（源码：本地 `grub/`，如 `grub/` 或 `/Users/weli/works/grub`）：

- **入口**：按 `rel->relocators_size` 分配 movers 缓冲区（`malloc_in_range`），对 `rel->chunks` 按 `chunk->src` 做基数排序得到 `sorted[]`，保证复制顺序不覆盖未搬数据。
- **写入**：先 `grub_cpu_relocator_preamble(rels)`（i386-pc 为空），再对每个 sorted chunk：`src < target` 调用 `grub_cpu_relocator_backward` 拷贝 backward 模板到 movers_chunk，`src > target` 调用 `grub_cpu_relocator_forward` 拷贝 forward 模板，`src == target` 只做 cache 同步；最后 `grub_cpu_relocator_jumper(rels, addr)` 写入 jumper 机器码（mov + jmp），`addr` 为安全区物理地址。
- **C 侧**：`grub_cpu_relocator_forward/backward` 先设全局变量 `*_dest`/`*_src`/`*_chunk_size`，再 `grub_memmove(ptr, &grub_relocator_*_start, ...)` 把已编译好的汇编模板拷贝到 movers_chunk；jumper 由 C 直接写机器码。boot 时无编译，仅拷贝模板 + 写 jumper。

**chunk 数量与顺序、复制代码生成的计算过程（源码解读）**

以下依据 `grub-core/lib/relocator.c` 中 `grub_relocator_prepare_relocs()` 及分配路径的源码，说明“chunk 数量与顺序不固定”时，relocators_size 如何累加、排序如何做、以及如何为每个 src ≠ target 的 chunk 生成一段复制代码。**关键逻辑已在下列源码片段中用注释标出。**

**1. chunk 的加入与 relocators_size 的累加**

- **chunk 来源**：loader 多次调用 `grub_relocator_alloc_chunk_align` 或 `grub_relocator_alloc_chunk_addr`；每次成功在链表头插入：`chunk->next = rel->chunks; rel->chunks = chunk;`，链表顺序为**后加入的在前**。
- **relocators_size 累加**：每加入一个 chunk 后按 src 与 target 关系累加（见下代码）；`src == target` 不累加。
- **总大小**：初始为 preamble_size + jumper_size（见 grub_relocator_new），再加所有“需要复制”的 chunk 的 forward/backward 段大小。

```c
// grub-core/lib/relocator.c

// 初始 relocators_size（grub_relocator_new，约 113 行）
ret->relocators_size = grub_relocator_jumper_size + grub_relocator_preamble_size;

// 每加入一个 chunk 后累加（grub_relocator_alloc_chunk_addr，约 1311-1322 行）
if (chunk->src < target)
  rel->relocators_size += grub_relocator_backward_size;   // src < target → 需要 backward 段
if (chunk->src > target)
  rel->relocators_size += grub_relocator_forward_size;    // src > target → 需要 forward 段
// src == target 不累加
chunk->target = target;
chunk->next = rel->chunks;   // 链表头插入
rel->chunks = chunk;
```

**2. 排序：按 chunk->src 升序（基数排序）**

- **目的**：按 src 升序处理，避免“先复制到的 target”覆盖“尚未复制的 src”。
- **实现**：对 `rel->chunks` 按 `chunk->src` 做 LSB 优先基数排序（低 8 位 → 次 8 位 → …，共 GRUB_CPU_SIZEOF_VOID_P 轮），得到 `sorted[]`。

```c
// grub-core/lib/relocator.c:1554-1604（prepare_relocs 内）

grub_memset (count, 0, sizeof (count));
// ① 统计 nchunks，并按 (chunk->src & 0xff) 做计数排序的 count 前缀和
for (chunk = rel->chunks; chunk; chunk = chunk->next) {
  nchunks++;
  count[(chunk->src & 0xff) + 1]++;   // 键：src 低 8 位
}
for (j = 0; j < 256; j++)
  count[j+1] += count[j];
for (chunk = rel->chunks; chunk; chunk = chunk->next)
  from[count[chunk->src & 0xff]++] = *chunk;   // 第一轮：按低 8 位排入 from[]

// ② 按 (src >> 8*i) & 0xff 再排 GRUB_CPU_SIZEOF_VOID_P-1 轮，得到按 src 升序的 sorted
for (i = 1; i < GRUB_CPU_SIZEOF_VOID_P; i++) {
  // ... count 前缀和按第 i 字节 ...
  to[count[(from[j].src >> (8 * i)) & 0xff]++] = from[j];
  swap(from, to);
}
sorted = from;   // sorted[j] 按 chunk->src 升序
```

**3. 为每个“src ≠ target”的 chunk 生成一段复制代码**

- **分配**：按 `rel->relocators_size` 分配 movers 缓冲区；`rels` 指向当前写入位置。
- **写入顺序**：preamble → 对 sorted[0..nchunks-1] 依次写 backward/forward 或只做 cache 同步 → jumper。

```c
// grub-core/lib/relocator.c:1543-1550, 1606-1636（prepare_relocs 内）

// ① 按累加好的 relocators_size 分配 movers 缓冲区
if (!malloc_in_range (rel, 0, ~(grub_addr_t)0 - rel->relocators_size + 1,
                      grub_relocator_align, rel->relocators_size, &movers_chunk, 1, 1))
  return grub_error (...);
rels = rels0 = grub_map_memory (movers_chunk.src, movers_chunk.size);

// ② preamble（i386-pc 为空）
grub_cpu_relocator_preamble (rels);
rels += grub_relocator_preamble_size;

// ③ 按 sorted 顺序为每个 chunk 写一段复制代码或做 cache 同步
for (j = 0; j < nchunks; j++) {
  if (sorted[j].src < sorted[j].target) {
    grub_cpu_relocator_backward ((void *) rels, sorted[j].srcv,
                                 grub_map_memory (sorted[j].target, sorted[j].size),
                                 sorted[j].size);
    rels += grub_relocator_backward_size;   // 写入 backward 段，rels 后移
  }
  if (sorted[j].src > sorted[j].target) {
    grub_cpu_relocator_forward ((void *) rels, sorted[j].srcv,
                                grub_map_memory (sorted[j].target, sorted[j].size),
                                sorted[j].size);
    rels += grub_relocator_forward_size;   // 写入 forward 段，rels 后移
  }
  if (sorted[j].src == sorted[j].target)
    grub_arch_sync_caches (sorted[j].srcv, sorted[j].size);   // 无复制，仅 cache 同步
}

// ④ jumper：写跳转到安全区 relocator32 的机器码
grub_cpu_relocator_jumper ((void *) rels, (grub_addr_t) addr);
*relstart = rels0;
```

**4. 小结（与“为什么要动态生成？”对应）**

| 项目 | 计算/来源 | 源码位置 |
|------|-----------|----------|
| chunk 数量 | 遍历 `rel->chunks` 计数 `nchunks` | relocator.c:1563-1568 |
| chunk 顺序（执行顺序） | 按 `chunk->src` 升序基数排序得到 `sorted[]` | relocator.c:1556-1604 |
| relocators_size | 初始 preamble+jumper；每 chunk 若 src&lt;target 加 backward_size，若 src&gt;target 加 forward_size | relocator.c:113、1311-1314、1488-1491 |
| 每段复制代码 | src&lt;target → backward 模板；src&gt;target → forward 模板；src==target → 无复制、仅 cache 同步 | relocator.c:1616-1635 |
| movers 布局 | preamble → [sorted[0] 的 forward/backward 或空] → … → [sorted[nchunks-1] 的 …] → jumper | relocator.c:1606-1636 |

**具体实现（入口与排序、preamble/forward/backward/jumper 源码、C 侧与汇编模板、执行顺序小结）**见 [GRUB_RELOCATOR_BUILD_AND_RUNTIME.md](GRUB_RELOCATOR_BUILD_AND_RUNTIME.md) 的「4. grub_relocator_prepare_relocs() 具体实现（运行时细节）」。

**⚠️ 为什么必须复制内核？不能直接跳转到临时缓冲区吗？**

**答案：** 理论上，如果内核是可重定位的（`relocatable = true`），可以跳转到临时缓冲区，但**实际实现中仍然需要复制**，原因如下：

1. **地址计算基于 0x100000 (1MB)**：
   ```c
   // grub/grub-core/loader/i386/linux.c:1178-1180
   linux_params.code32_start = prot_mode_target + 
                               grub_le_to_cpu32 (lh.code32_start) - 
                               GRUB_LINUX_BZIMAGE_ADDR;
   // 其中：
   // - prot_mode_target = 0x100000 (1MB)（最终目标地址）
   // - lh.code32_start：内核头部中的字段，表示当镜像加载在 0x100000 时 32 位入口的物理地址（即 0x100000 或 0x100000+偏移）
   // - GRUB_LINUX_BZIMAGE_ADDR = 0x100000 (1MB)
   ```
   - `code32_start` 的计算假设内核在 `prot_mode_target`（0x100000 (1MB)）
   - 如果跳转到临时缓冲区（16MB+），`code32_start` 的地址会错误

2. **boot_params 中的地址均按镜像在 0x100000 (1MB) 为基址计算得到的物理地址**：
   - `boot_params.cmd_line_ptr`：命令行参数地址
   - `boot_params.ramdisk_image`：initramfs 地址
   - `boot_params.code32_start`：内核入口点物理地址
   - 这些地址均假设内核加载在 0x100000 (1MB)，为绝对物理地址

3. **Legacy 协议下镜像须在 0x100000 (1MB)**：
   - **Legacy/GRUB 路径**：GRUB 不执行 bzImage 的实模式 Setup，直接跳 **code32_start**（压缩内核入口）。**code32_start** 是 boot protocol 头里的**字段**，定义在 Linux `arch/x86/boot/header.S`（标签 `code32_start:`，默认 `.long 0x100000`）；其**值**为 32 位入口物理地址，该地址处的代码在 `arch/x86/boot/compressed/head_64.S`（如 startup_32），**不是** setup。从扇区 0 启动时先跑 Setup（`arch/x86/boot/`），再由 **pm.c** 调用 `protected_mode_jump(boot_params.hdr.code32_start, ...)` 切保护模式并跳转到该地址。`code32_start` 与 boot_params 中的地址均按“镜像在 0x100000”计算，故必须把镜像放在 0x100000。
   - **从扇区 0 启动**时才会先跑 Setup（`arch/x86/boot/`），再在 pm.c 中 `protected_mode_jump(boot_params.hdr.code32_start, ...)` 切保护模式跳转；此时同样约定镜像在 0x100000。
   - **UEFI 模式**：入口为 EFI stub（`arch/x86/boot/startup/efi-mixed.S`），不经过 code32_start
     - EFI stub 是**位置无关的**（使用相对地址，如 `call 1f; popl %ecx`）
     - EFI stub 可以加载到任意地址，不需要在 0x100000 (1MB)
     - EFI stub 会调用 `efi32_startup`，然后跳转到 `efi_stub_entry`
     - 解压代码（`head_64.S`）会处理地址重定位：
       - 如果是可重定位内核：计算实际加载地址
       - 如果不是：使用 `LOAD_PHYSICAL_ADDR`（通常是 0x100000 (1MB)）

4. **如果跳转到临时缓冲区需要大量调整**：
   - 需要重新计算所有 `boot_params` 中的地址
   - 需要调整内核头部中的地址字段
   - 需要确保内核的解压代码能正确处理地址
   - 这增加了复杂性和出错风险

5. **复制操作是安全的**：
   - 复制操作在 relocator 代码中执行，非常快速（通常几毫秒）
   - 复制发生在模式切换之前，不会影响执行流程
   - 复制后，所有地址计算都是正确的，不需要额外调整

**结论**：
- **Legacy/GRUB 路径**：即使内核是可重定位的，GRUB 仍复制到 0x100000 (1MB)，因为：Legacy 协议约定镜像在 0x100000；`code32_start` 与 `boot_params` 中的地址均按此计算；且为最简、最稳妥的兼容方式。
- **UEFI 模式**：不需要复制到 0x100000 (1MB)，因为：
  1. EFI stub 是位置无关的，可以加载到任意地址
  2. EFI 固件通过 `LoadImage` 和 `StartImage` 服务处理地址重定位
  3. 解压代码会处理后续的地址重定位（如果是可重定位内核）

**如果直接跳转会发生什么？**

```c
// ❌ 错误做法：直接跳转
asm volatile ("jmp *%0" : : "r" (code32_start));

// 问题：
// 1. 段寄存器、GDT、分页与内核期望状态可能不一致
// 2. 寄存器状态（ESI = boot_params、ESP 等）可能未按协议设置
// 3. 内核入口（code32_start）期望 32 位保护模式下特定环境
// 结果：系统崩溃或不可预测的行为
```

**正确流程**见文档开头「从 GRUB 到内核的流程概览（BIOS/Legacy）」；relocator32 在安全区执行关分页、加载其内嵌的 GDT（非 GRUB 提供）、设段与寄存器后 ljmp 到 code32_start（32 位保护模式，如 startup_32）。

