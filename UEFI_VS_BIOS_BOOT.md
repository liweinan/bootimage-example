# UEFI 与 BIOS 在引导机制上的根本差异

本文档详细对比了 UEFI 和 BIOS 两种引导机制的根本差异，帮助理解现代引导系统与传统引导系统的区别。

---

**重要说明：** 上述设计模式（固定大小、固定地址、实模式等）**仅适用于 BIOS 模式**。UEFI 采用了完全不同的引导机制，从根本上避免了这些限制。

**UEFI 引导机制：**

1. **不使用引导扇区**：
   - UEFI **不使用** 512 字节的 MBR 引导扇区
   - UEFI 使用 **EFI 系统分区（ESP）**，这是一个 FAT32 文件系统分区
   - 引导加载程序是标准的 **PE 格式可执行文件**（.efi），大小不受限制

2. **文件系统引导**：
   - UEFI 固件内置文件系统驱动（支持 FAT12/16/32）
   - 直接从文件系统读取引导加载程序（如 `\EFI\BOOT\BOOTX64.EFI`）
   - 不需要手动解析磁盘扇区

3. **保护模式/长模式启动**：
   - **UEFI 固件本身已经在保护模式（32位）或长模式（64位）下运行**
   - **UEFI 不使用实模式**，引导加载程序直接以保护模式/长模式启动
   - 无需模式切换，无需启用 A20 地址线

4. **统一接口（EFI 服务）**：
   - 不通过 INT 指令调用硬件服务
   - 使用 **EFI 服务**（函数调用接口）
   - 提供统一的硬件抽象层（HAL）

5. **参数传递**：
   - 通过栈传递参数（EFI_HANDLE, EFI_SYSTEM_TABLE）
   - 不依赖寄存器传递启动信息

**UEFI vs BIOS 引导对比：**

| 特性 | BIOS 模式 | UEFI 模式 |
|------|----------|-----------|
| **引导扇区** | 512 字节 MBR，固定地址 0x7C00 | 无引导扇区，使用文件系统 |
| **引导加载程序格式** | 原始二进制代码 | PE 格式可执行文件（.efi） |
| **初始运行模式** | 实模式（16 位） | 保护模式（32 位）或长模式（64 位） |
| **模式切换** | 需要（real_to_prot） | 不需要 |
| **A20 地址线** | 需要手动启用 | 已启用 |
| **GDT/IDT** | 需要手动设置 | 已由 UEFI 设置 |
| **硬件访问** | 通过 INT 指令调用 BIOS 服务 | 通过 EFI 服务（函数调用） |
| **文件系统** | 引导加载程序需要自己实现 | UEFI 内置文件系统驱动 |
| **代码大小限制** | 512 字节（引导扇区） | 无限制（标准可执行文件） |
| **参数传递** | 通过寄存器（%edx = 启动驱动器） | 通过栈（EFI_HANDLE, EFI_SYSTEM_TABLE） |

**UEFI 引导流程：**

```
1. UEFI 固件启动（保护模式/长模式）
   ├─ 初始化硬件
   ├─ 加载 EFI 系统分区（ESP）
   └─ 查找引导加载程序（\EFI\BOOT\BOOTX64.EFI）
    ↓
2. UEFI 加载引导加载程序（PE 格式）
   ├─ 解析 PE 文件格式
   ├─ 加载到内存（任意地址）
   └─ 传递 EFI_HANDLE 和 EFI_SYSTEM_TABLE
    ↓
3. 引导加载程序执行（保护模式/长模式）
   ├─ 直接调用 EFI 服务（无需 INT 指令）
   ├─ 读取配置文件（通过文件系统）
   ├─ 加载内核镜像
   └─ 调用 ExitBootServices() 退出 UEFI 环境
    ↓
4. 跳转到内核（保护模式/长模式）
   └─ 内核继续在保护模式/长模式下运行
```

**为什么 UEFI 不使用实模式？**

1. **现代设计**：UEFI 设计于 2000 年代，直接面向现代 CPU（支持保护模式和长模式）
2. **固件实现**：UEFI 固件本身就在保护模式/长模式下运行，没有实模式阶段
3. **性能考虑**：保护模式/长模式提供更好的内存管理和性能
4. **安全性**：保护模式提供内存保护，提高系统安全性
5. **兼容性**：现代硬件（64 位 CPU）主要使用长模式，实模式主要用于兼容性

**总结：**

- **BIOS 模式**：必须遵循 512 字节引导扇区的限制，从实模式启动，需要手动切换到保护模式
- **UEFI 模式**：完全不同的机制，使用文件系统和标准可执行文件，直接在保护模式/长模式下运行，**不使用实模式**

因此，上述引导扇区程序的设计模式（固定大小、固定地址、实模式等）**仅适用于 BIOS 模式**，UEFI 模式采用了更现代、更灵活的引导机制。

---

## Linux Kernel UEFI 启动详细流程

> **重要**：UEFI 启动 Linux kernel 时，**完全跳过** `arch/x86/boot/compressed/head_64.S` 中的 `startup_32` 和 `startup_64`，直接通过 EFI stub 进行解压和跳转。

### UEFI 启动路径 vs BIOS 启动路径

| 阶段 | BIOS/GRUB 路径 | UEFI 路径 |
|------|---------------|-----------|
| **固件** | BIOS（实模式） | UEFI（长模式） |
| **bootloader** | GRUB（需要模式切换） | UEFI 直接加载 PE 文件 |
| **入口点** | compressed/head_64.S::startup_32 | drivers/firmware/efi/libstub/x86-stub.c::efi_pe_entry |
| **模式切换** | ✅ 需要（实模式→保护模式→长模式） | ❌ 不需要（已在长模式） |
| **重定位** | ✅ 需要（rep movsq 从 1MB → %rbx） | ❌ 不需要（EFI 分配内存） |
| **解压函数** | compressed/misc.c::extract_kernel() | 同一个 decompress_kernel()，但由 EFI stub 调用 |
| **跳转到内核** | compressed/head_64.S::jmp *%rax | efi stub::enter_kernel() |
| **目标地址** | kernel/head_64.S::startup_64 | kernel/head_64.S::startup_64（相同） |

### 详细执行流程（UEFI 路径）

#### 1. UEFI 固件阶段

```
UEFI 固件启动（已在 64位长模式）
├─ 初始化硬件
├─ 加载 EFI 系统分区（ESP，FAT32 文件系统）
├─ 读取引导配置（\EFI\BOOT\BOOTX64.EFI 或其他）
└─ 加载 vmlinuz（PE 格式可执行文件）
```

**关键特性**：
- UEFI 固件已经设置好 GDT、IDT、页表
- CPU 已在 64位长模式
- 提供 EFI Boot Services 和 Runtime Services

#### 2. efi_pe_entry() - PE 入口点

**源代码**：`drivers/firmware/efi/libstub/x86-stub.c:943-947`

```c
efi_status_t __efiapi efi_pe_entry(efi_handle_t handle,
                                   efi_system_table_t *sys_table_arg)
{
    efi_stub_entry(handle, sys_table_arg, NULL);
}
```

**参数**：
- `handle`：EFI 镜像句柄（由 UEFI 固件传递）
- `sys_table_arg`：EFI 系统表指针

**作用**：
- 这是 vmlinuz 的 PE 入口点（PE header 中指定）
- 立即调用 `efi_stub_entry()` 进行实际工作

#### 3. efi_stub_entry() - EFI Stub 主函数

**源代码**：`drivers/firmware/efi/libstub/x86-stub.c:808-941`

```c
void __noreturn efi_stub_entry(efi_handle_t handle,
                               efi_system_table_t *sys_table_arg,
                               struct boot_params *boot_params)
{
    unsigned long kernel_entry;
    struct setup_header *hdr;
    efi_status_t status;

    efi_system_table = sys_table_arg;

    /* 分配或使用 boot_params */
    if (!boot_params) {
        status = efi_allocate_bootparams(handle, &boot_params);
        ...
    }

    hdr = &boot_params->hdr;

    /* 处理命令行参数 */
    status = efi_parse_options(...);
    ...

    /* 关键：解压内核 */
    status = efi_decompress_kernel(&kernel_entry, boot_params);
    if (status != EFI_SUCCESS) {
        efi_err("Failed to decompress kernel\n");
        goto fail;
    }

    /* 加载 initrd */
    status = efi_load_initrd(...);
    ...

    /* 设置内存映射 */
    status = efi_allocate_pages(...);
    ...

    /* 退出 UEFI Boot Services */
    status = efi_exit_boot_services(...);
    ...

    /* 5级页表切换（如果需要） */
    efi_5level_switch();

    /* 跳转到解压后的内核 */
    enter_kernel(kernel_entry, boot_params);
}
```

**关键步骤**：

1. **初始化 boot_params**
   - 分配或使用传入的 boot_params 结构
   - 这是传递给内核的参数结构

2. **解析命令行参数**
   - 处理 `efi=` 等参数
   - 处理 `nokaslr` 等选项

3. **解压内核**（核心步骤）
   - 调用 `efi_decompress_kernel()`
   - 详见下一节

4. **加载 initrd**
   - 从 LINUX_EFI_INITRD_MEDIA_GUID 设备路径加载
   - 或从命令行 `initrd=` 参数加载

5. **退出 Boot Services**
   - 调用 `ExitBootServices()`
   - 之后不能再使用 EFI Boot Services
   - 只能使用 Runtime Services

6. **跳转到内核**
   - 调用 `enter_kernel()`
   - 永不返回

#### 4. efi_decompress_kernel() - 解压内核

**源代码**：`drivers/firmware/efi/libstub/x86-stub.c:733-792`

```c
static efi_status_t efi_decompress_kernel(unsigned long *kernel_entry,
                                          struct boot_params *boot_params)
{
    unsigned long virt_addr = LOAD_PHYSICAL_ADDR;  // 默认 16MB
    unsigned long addr, alloc_size, entry;
    efi_status_t status;
    u32 seed[2] = {};

    /* 计算所需内存大小 */
    alloc_size = ALIGN(max_t(unsigned long, output_len, kernel_total_size),
                       MIN_KERNEL_ALIGN);

    /* KASLR（地址随机化） */
    if (IS_ENABLED(CONFIG_RANDOMIZE_BASE) && !efi_nokaslr) {
        u64 range = KERNEL_IMAGE_SIZE - LOAD_PHYSICAL_ADDR - kernel_total_size;

        efi_get_seed(seed, sizeof(seed));  // 获取随机种子

        virt_addr += (range * seed[1]) >> 32;  // 随机化地址
        virt_addr &= ~(CONFIG_PHYSICAL_ALIGN - 1);  // 对齐

        boot_params->hdr.loadflags |= KASLR_FLAG;
    }

    /* 通过 EFI 分配内存 */
    status = efi_random_alloc(alloc_size, CONFIG_PHYSICAL_ALIGN, &addr,
                              seed[0], EFI_LOADER_CODE,
                              LOAD_PHYSICAL_ADDR,
                              EFI_X86_KERNEL_ALLOC_LIMIT);
    if (status != EFI_SUCCESS)
        return status;

    /* 解压内核（调用共享的 decompress_kernel）*/
    entry = decompress_kernel((void *)addr, virt_addr, error);
    if (entry == ULONG_MAX) {
        efi_free(alloc_size, addr);
        return EFI_LOAD_ERROR;
    }

    *kernel_entry = addr + entry;

    /* 设置内存保护 */
    return efi_adjust_memory_range_protection(addr, kernel_text_size);
}
```

**关键点**：

1. **不需要重定位**
   - BIOS 路径：需要从 1MB 拷贝到 %rbx（通常 38MB）
   - UEFI 路径：直接通过 EFI 分配合适的内存
   - **省略了 rep movsq 步骤！**

2. **KASLR 支持**
   - 随机化解压目标地址
   - 使用 EFI 的随机数服务

3. **调用相同的 decompress_kernel()**
   - 与 BIOS 路径使用相同的解压函数
   - 位于 `arch/x86/boot/compressed/misc.c::decompress_kernel()`

4. **内存分配**
   - 使用 EFI Boot Services 分配内存
   - 类型：`EFI_LOADER_CODE`
   - 对齐：`CONFIG_PHYSICAL_ALIGN`（通常 2MB）

#### 5. enter_kernel() - 跳转到内核

**源代码**：`drivers/firmware/efi/libstub/x86-stub.c:794-801`

```c
static void __noreturn enter_kernel(unsigned long kernel_addr,
                                    struct boot_params *boot_params)
{
    /* enter decompressed kernel with boot_params pointer in RSI/ESI */
    asm("jmp *%0"::"r"(kernel_addr), "S"(boot_params));

    unreachable();
}
```

**作用**：
- 直接跳转到解压后内核的入口点
- 目标：`arch/x86/kernel/head_64.S::startup_64`
- 传递参数：
  - `%rax` = kernel_addr（跳转目标）
  - `%rsi` = boot_params 指针

**与 BIOS 路径的区别**：
- BIOS 路径：从 `compressed/head_64.S::startup_64` → `kernel/head_64.S::startup_64`
- UEFI 路径：**直接跳到** `kernel/head_64.S::startup_64`
- **跳过了整个 compressed/head_64.S！**

#### 6. kernel/head_64.S::startup_64 - 主内核入口

从这里开始，UEFI 路径和 BIOS 路径**完全相同**。

```assembly
/* arch/x86/kernel/head_64.S::startup_64 */
startup_64:
    /* 此时 %rsi = boot_params */
    movq    %rsi, %r15          // 保存 boot_params

    /* 设置早期页表 */
    /* 设置 GDT */
    /* 跳转到 C 代码 */
    call    x86_64_start_kernel
    ...
```

后续流程：
```
startup_64 (kernel/head_64.S)
    ↓
x86_64_start_kernel() (arch/x86/kernel/head64.c)
    ↓
start_kernel() (init/main.c)
    ↓
rest_init() → kernel_init() → init 进程
```

### 内存布局对比

#### BIOS/GRUB 路径

```
1 MB (0x100000)     ← GRUB 加载位置（初始）
                    ← startup_32/startup_64 最初在这里执行
                    ← rep movsq 将整个压缩内核拷贝走
                    ↓
16 MB (0x1000000)   ← 解压目标（%rbp）
                    ↓
38.96 MB            ← 重定位后的压缩内核（%rbx）
                    ← extract_kernel() 在这里执行
                    ← 从这里解压到 16MB
                    ↓
48.87 MB            ← ZO 结束
```

#### UEFI 路径

```
任意地址（由 EFI 分配）
    ├─ vmlinuz (PE 格式) 加载在这里
    ├─ efi_pe_entry() 从这里开始执行
    └─ efi_stub_entry() 处理解压
        ↓
16 MB 或随机地址（KASLR）
    └─ 解压后的内核直接写入这里
       （不需要先拷贝压缩内核）
```

**关键区别**：
- BIOS：加载到 1MB → 拷贝到 38MB → 解压到 16MB（三步）
- UEFI：EFI 分配 → 直接解压到目标（两步，省略重定位）

### 代码路径总结

**BIOS/GRUB 路径**：
```
GRUB
    ↓
arch/x86/boot/compressed/head_64.S::startup_32
    ↓ (lret 切换到长模式)
arch/x86/boot/compressed/head_64.S::startup_64
    ↓ (rep movsq 重定位)
arch/x86/boot/compressed/head_64.S::.Lrelocated
    ↓ (call extract_kernel)
arch/x86/boot/compressed/misc.c::extract_kernel()
    ↓ (调用 decompress_kernel)
    ↓ (jmp *%rax)
arch/x86/kernel/head_64.S::startup_64
    ↓
x86_64_start_kernel() → start_kernel()
```

**UEFI 路径**：
```
UEFI 固件
    ↓
drivers/firmware/efi/libstub/x86-stub.c::efi_pe_entry()
    ↓
drivers/firmware/efi/libstub/x86-stub.c::efi_stub_entry()
    ↓
drivers/firmware/efi/libstub/x86-stub.c::efi_decompress_kernel()
    ↓ (调用相同的 decompress_kernel)
arch/x86/boot/compressed/misc.c::decompress_kernel()
    ↓
drivers/firmware/efi/libstub/x86-stub.c::enter_kernel()
    ↓ (jmp 直接跳转)
arch/x86/kernel/head_64.S::startup_64
    ↓
x86_64_start_kernel() → start_kernel()
```

### 为什么 UEFI 更简单？

1. **已在长模式**
   - 不需要实模式→保护模式→长模式的切换
   - 省略了整个 startup_32

2. **内存管理**
   - 使用 EFI Boot Services 分配内存
   - 不需要手动重定位压缩内核
   - 省略了 rep movsq 步骤

3. **文件系统**
   - UEFI 内置 FAT32 驱动
   - 可以直接加载 initrd 等文件
   - 不需要自己解析文件系统

4. **硬件抽象**
   - 使用 EFI 服务访问硬件
   - 不需要 BIOS INT 中断
   - 不需要手动探测硬件

5. **PE 格式**
   - 标准的可执行文件格式
   - 没有大小限制（vs BIOS 的 512 字节）
   - UEFI 自动处理加载和重定位

---

## 相关文档

- [LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md) - Linux 内核启动与初始化（BIOS/GRUB 详细流程）
- [GRUB UEFI 长模式启动分析](GRUB_UEFI_LONG_MODE_ANALYSIS.md) - GRUB 和 Linux kernel 的 UEFI 长模式启动详细实现
- [GRUB 模式切换](GRUB_MODE_SWITCHING.md) - GRUB 在不同模式间的切换机制
- [X86_CPU_MODES.md](X86_CPU_MODES.md) - x86 CPU 的实模式、保护模式和长模式详解
- [WHY_RELOCATE_COMPRESSED_KERNEL.md](WHY_RELOCATE_COMPRESSED_KERNEL.md) - 为什么 BIOS 路径需要重定位（UEFI 路径不需要）
