# GRUB UEFI 长模式启动与 Linux Kernel 配合支持分析

> 本文档分析 GRUB bootloader 对 UEFI 长模式（64位）启动的支持，以及 Linux kernel 如何配合实现完整的 UEFI 启动流程。

## 目录

1. [总体结论](#总体结论)
2. [GRUB UEFI 长模式支持](#grub-uefi-长模式支持)
3. [Linux Kernel UEFI 启动支持](#linux-kernel-uefi-启动支持)
4. [完整启动流程](#完整启动流程)
5. [关键源码位置](#关键源码位置)

---

## 总体结论

**结论：GRUB 和 Linux kernel 都完全支持 UEFI 长模式启动** ✅

- **GRUB**: 提供成熟的 x86_64 UEFI bootloader 实现
- **Linux**: 通过 EFI Stub 支持直接从 UEFI 或 GRUB 在长模式下启动
- **整个启动链都是 64位原生的**

---

## GRUB UEFI 长模式支持

### 1. UEFI 启动入口点

#### x86_64 EFI 启动入口
**文件**: `grub-core/kern/x86_64/efi/startup.S`

```asm
/* startup.S - bootstrap GRUB itself */
.code64
start:
_start:
	movq	%rcx, EXT_C(grub_efi_image_handle)(%rip)
	movq	%rdx, EXT_C(grub_efi_system_table)(%rip)
	andq	$~0xf, %rsp
	call	EXT_C(grub_main)
```

**关键特性**:
- 在 64位代码模式（`.code64`）下运行
- 从 UEFI 固件接收参数：
  - `%rcx`: EFI image handle
  - `%rdx`: EFI system table
- 对齐栈指针（16字节对齐，符合 UEFI 规范）
- 直接调用 C 语言的 `grub_main()` 函数

### 2. EFI 初始化流程

#### EFI 通用初始化
**文件**: `grub-core/kern/efi/init.c`

```c
void
grub_efi_init (void)
{
  grub_modbase = grub_efi_section_addr ("mods");

  /* 初始化控制台 */
  grub_console_init ();

  /* 初始化内存管理系统 */
  grub_efi_mm_init ();

  /* Secure Boot 验证 */
  if (grub_efi_get_secureboot () == GRUB_EFI_SECUREBOOT_MODE_ENABLED)
    {
      grub_lockdown ();
      grub_shim_lock_verifier_setup ();
    }

  /* 禁用看门狗定时器 */
  grub_efi_system_table->boot_services->set_watchdog_timer (0, 0, 0, NULL);

  /* 初始化 EFI 磁盘 */
  grub_efidisk_init ();
  grub_efi_register_debug_commands ();
}
```

#### x86 特定初始化
**文件**: `grub-core/kern/i386/efi/init.c`

```c
void
grub_machine_init (void)
{
  grub_efi_init ();
  grub_tsc_init ();  /* 初始化 TSC 计时器 */
}

void
grub_machine_fini (int flags)
{
  if (!(flags & GRUB_LOADER_FLAG_NORETURN))
    return;

  grub_efi_fini ();

  if (!(flags & GRUB_LOADER_FLAG_EFI_KEEP_ALLOCATED_MEMORY))
    grub_efi_memory_fini ();
}
```

### 3. 长模式切换实现

#### 64位重定位器（Relocator）
**文件**: `grub-core/lib/i386/relocator64.S`

这是最关键的长模式切换代码：

```asm
#ifndef __x86_64__
	/* 从 32位 切换到 64位 */
	DISABLE_PAGING

	/* Step 1: 开启 PAE (Physical Address Extension) */
	movl	%cr4, %eax
	orl	$(GRUB_MEMORY_CPU_CR4_PAE_ON | GRUB_MEMORY_CPU_CR4_PSE_ON), %eax
	movl	%eax, %cr4

	/* Step 2: 设置 CR3（页表基址） */
	.byte	0xb8
	.long	grub_relocator64_cr3
	movl	%eax, %cr3

	/* Step 3: 启用 AMD64 扩展（设置 EFER.LME） */
	movl	$GRUB_MEMORY_CPU_AMD64_MSR, %ecx    /* EFER MSR = 0xc0000080 */
	rdmsr
	orl	$GRUB_MEMORY_CPU_AMD64_MSR_ON, %eax  /* 设置 LME 位 */
	wrmsr

	/* Step 4: 启用分页 */
	movl	%cr0, %eax
	orl	$GRUB_MEMORY_CPU_CR0_PAGING_ON, %eax
	movl	%eax, %cr0

	/* Step 5: 重新加载 GDT */
	RELOAD_GDT
#endif

#ifdef GRUB_MACHINE_EFI
	/* UEFI 特定：对齐栈 */
	.byte 0x48
	.byte 0x83
	.byte 0xe4
	.byte 0xf0    /* andq $~15, %rsp */
#endif

	/* Step 6: 设置 64位寄存器并跳转 */
	.byte 0x48
	.byte 0xb8
	.quad	grub_relocator64_rsp
	movq	%rax, %rsp

	/* ... 设置其他寄存器 ... */

	jmp *LOCAL(jump_addr) (%rip)
```

#### 关键常量定义
**文件**: `include/grub/i386/memory.h`

```c
/* CR0 标志 */
#define GRUB_MEMORY_CPU_CR0_PE_ON           0x1          /* 保护模式 */
#define GRUB_MEMORY_CPU_CR0_PAGING_ON       0x80000000   /* 分页 */

/* CR4 标志 */
#define GRUB_MEMORY_CPU_CR4_PAE_ON          0x00000020   /* PAE */
#define GRUB_MEMORY_CPU_CR4_PSE_ON          0x00000010   /* PSE */

/* AMD64 扩展 */
#define GRUB_MEMORY_CPU_AMD64_MSR           0xc0000080   /* EFER MSR */
#define GRUB_MEMORY_CPU_AMD64_MSR_ON        0x00000100   /* LME 位 */
```

### 4. EFI 64位启动函数

**文件**: `grub-core/lib/x86_64/efi/relocator.c`

```c
grub_err_t
grub_relocator64_efi_boot (struct grub_relocator *rel,
			   struct grub_relocator64_efi_state state)
{
  grub_err_t err;
  void *relst;
  grub_relocator_chunk_t ch;

  /* 分配重定位器代码空间（在 4GB 以下） */
  err = grub_relocator_alloc_chunk_align_safe (rel, &ch, 0, 0x100000000,
				       RELOCATOR_SIZEOF (64_efi), 16,
				       GRUB_RELOCATOR_PREFERENCE_NONE, 1);
  if (err)
    return err;

  /* 设置 64位寄存器状态（不修改 %rsp，使用 EFI 栈） */
  grub_relocator64_rax = state.rax;
  grub_relocator64_rbx = state.rbx;
  grub_relocator64_rcx = state.rcx;
  grub_relocator64_rdx = state.rdx;
  grub_relocator64_rip = state.rip;  /* 目标入口点 */
  grub_relocator64_rsi = state.rsi;

  /* 复制重定位器代码 */
  grub_memmove (get_virtual_current_address (ch), &grub_relocator64_efi_start,
		RELOCATOR_SIZEOF (64_efi));

  /* 准备重定位 */
  err = grub_relocator_prepare_relocs (rel, get_physical_target_address (ch),
				       &relst, NULL);
  if (err)
    return err;

  /* 执行重定位器 */
  ((void (*) (void)) relst) ();

  /* 不会到达这里 */
  return GRUB_ERR_NONE;
}
```

### 5. EFI Boot Services 退出

**文件**: `grub-core/kern/efi/mm.c`

```c
grub_err_t
grub_efi_finish_boot_services (grub_efi_uintn_t *outbuf_size, void *outbuf,
			       grub_efi_uintn_t *map_key,
			       grub_efi_uintn_t *efi_desc_size,
			       grub_efi_uint32_t *efi_desc_version)
{
  grub_efi_boot_services_t *b;
  grub_efi_status_t status;

  while (1)
    {
      /* 获取 EFI 内存映射 */
      if (grub_efi_get_memory_map (&finish_mmap_size, finish_mmap_buf,
                                   &finish_key, &finish_desc_size,
                                   &finish_desc_version) < 0)
	return grub_error (GRUB_ERR_IO, "couldn't retrieve memory map");

      finish_mmap_buf = grub_malloc (finish_mmap_size);
      if (!finish_mmap_buf)
	return grub_errno;

      if (grub_efi_get_memory_map (&finish_mmap_size, finish_mmap_buf,
                                   &finish_key, &finish_desc_size,
                                   &finish_desc_version) <= 0)
	{
	  grub_free (finish_mmap_buf);
	  return grub_error (GRUB_ERR_IO, "couldn't retrieve memory map");
	}

      /* 关键：退出 EFI Boot Services */
      b = grub_efi_system_table->boot_services;
      status = b->exit_boot_services (grub_efi_image_handle, finish_key);
      if (status == GRUB_EFI_SUCCESS)
	break;

      if (status != GRUB_EFI_INVALID_PARAMETER)
	{
	  grub_free (finish_mmap_buf);
	  return grub_error (GRUB_ERR_IO, "couldn't terminate EFI services");
	}

      grub_free (finish_mmap_buf);
      grub_printf ("Trying to terminate EFI services again\n");
    }

  grub_efi_is_finished = 1;  /* 标记 Boot Services 已退出 */

  /* 返回内存映射信息 */
  if (outbuf_size && outbuf && map_key)
    {
      *outbuf_size = finish_mmap_size;
      grub_memcpy (outbuf, finish_mmap_buf, finish_mmap_size);
      *map_key = finish_key;
      if (efi_desc_size)
	*efi_desc_size = finish_desc_size;
      if (efi_desc_version)
	*efi_desc_version = finish_desc_version;
    }

  return GRUB_ERR_NONE;
}
```

### 6. Linux 内核加载（EFI 方式）

**文件**: `grub-core/loader/efi/linux.c`

```c
grub_err_t
grub_arch_efi_linux_boot_image (grub_addr_t addr, grub_size_t size, char *args)
{
  grub_efi_memory_mapped_device_path_t *mempath;
  grub_efi_handle_t image_handle;
  grub_efi_status_t status;
  grub_efi_loaded_image_t *loaded_image;

  /* 创建内存映射设备路径 */
  mempath = grub_malloc (2 * sizeof (grub_efi_memory_mapped_device_path_t));

  mempath[0].header.type = GRUB_EFI_HARDWARE_DEVICE_PATH_TYPE;
  mempath[0].memory_type = GRUB_EFI_LOADER_DATA;
  mempath[0].start_address = addr;
  mempath[0].end_address = addr + size;

  mempath[1].header.type = GRUB_EFI_END_DEVICE_PATH_TYPE;

  /* 使用 UEFI 加载镜像 */
  status = grub_efi_load_image (0, grub_efi_image_handle,
				(grub_efi_device_path_t *) mempath,
				(void *) addr, size, &image_handle);
  if (status != GRUB_EFI_SUCCESS)
    return grub_error (GRUB_ERR_BAD_OS, "cannot load image");

  /* 设置命令行参数 */
  loaded_image = grub_efi_get_loaded_image (image_handle);
  /* ... 转换命令行为 UTF-16 ... */

  /* 启动内核镜像 */
  grub_efi_start_image (image_handle, &exit_data_size, &exit_data);

  return GRUB_ERR_NONE;
}
```

**关键特性**:
- 支持 UEFI stub 内核（PE/COFF 格式）
- 使用 `grub_efi_load_image()` 加载内核镜像
- 使用 `grub_efi_start_image()` 执行内核
- 支持 LoadFile2 协议加载 initrd
- 转换命令行为 UTF-16 格式

### 7. GRUB 目录结构

```
grub/
├── grub-core/kern/
│   ├── efi/                          # EFI 通用实现
│   │   ├── init.c                    # EFI 初始化
│   │   ├── efi.c                     # EFI 功能
│   │   ├── mm.c                      # 内存管理和 Boot Services 退出
│   │   ├── sb.c                      # Secure Boot 支持
│   │   └── debug.c                   # 调试功能
│   ├── x86_64/efi/
│   │   └── startup.S                 # x86_64 EFI 启动入口（64位）
│   ├── i386/efi/
│   │   ├── startup.S                 # i386 EFI 启动入口（32位）
│   │   └── init.c                    # x86 特定初始化
│   └── main.c                        # GRUB 主程序入口
│
├── grub-core/loader/
│   └── efi/
│       ├── linux.c                   # UEFI Linux 加载器
│       ├── chainloader.c             # EFI chainloader
│       └── appleloader.c             # Apple EFI 加载器
│
├── grub-core/lib/
│   ├── i386/
│   │   ├── relocator64.S             # 64位模式切换代码（关键！）
│   │   ├── relocator_common.S        # 通用重定位器宏
│   │   ├── relocator.c               # 重定位器 C 实现
│   │   └── relocator32.S             # 32位重定位器
│   └── x86_64/efi/
│       └── relocator.c               # x86_64 EFI 引导实现
│
└── include/grub/
    ├── efi/
    │   ├── efi.h                     # EFI 声明
    │   ├── api.h                     # EFI API 定义（56KB）
    │   └── memory.h                  # EFI 内存管理
    ├── i386/
    │   ├── memory.h                  # x86 内存和 CR 寄存器定义
    │   └── relocator.h               # 重定位器状态结构
    └── x86_64/
        ├── efi/memory.h              # x86_64 EFI 内存配置
        └── memory.h                  # x86_64 内存定义
```

---

## Linux Kernel UEFI 启动支持

### 1. UEFI 启动架构概览

Linux kernel 提供两种 UEFI 启动入口点：

#### a) PE 入口点（推荐方式）
**文件**: `arch/x86/boot/header.S:86`

```c
// PE 头中定义的入口点
AddressOfEntryPoint = setup_size + ZO_efi_pe_entry
```

**实现**: `drivers/firmware/efi/libstub/x86-stub.c:943-947`

```c
efi_status_t __efiapi efi_pe_entry(efi_handle_t handle,
                                   efi_system_table_t *sys_table_arg)
{
    efi_stub_entry(handle, sys_table_arg, NULL);
}
```

#### b) 握手协议入口点（兼容模式）
**配置**: `CONFIG_EFI_HANDOVER_PROTOCOL`

**实现**: `drivers/firmware/efi/libstub/x86-stub.c:950-955`

```c
void efi_handover_entry(efi_handle_t handle, efi_system_table_t *sys_table_arg,
                        struct boot_params *boot_params)
{
    memset(_bss, 0, _ebss - _bss);
    efi_stub_entry(handle, sys_table_arg, boot_params);
}
```

### 2. EFI Stub 核心实现

#### EFI Stub 主入口
**文件**: `drivers/firmware/efi/libstub/x86-stub.c:808-941`

```c
void __noreturn efi_stub_entry(efi_handle_t handle,
			       efi_system_table_t *sys_table_arg,
			       struct boot_params *boot_params)
{
    // 1. 验证 EFI 系统表签名
    if (sys_table_arg->hdr.signature != EFI_SYSTEM_TABLE_SIGNATURE) {
        efi_exit(handle, EFI_INVALID_PARAMETER);
    }

    // 2. 分配或使用提供的 boot_params
    if (!boot_params) {
        status = efi_allocate_bootparams(handle, &boot_params);
        if (status != EFI_SUCCESS) {
            efi_err("Failed to allocate boot params\n");
            efi_exit(handle, status);
        }
    }

    // 3. 解析命令行选项
    efi_parse_options(boot_params);

    // 4. 检查 SEV-SNP 功能
    if (efi_sev_snp_enabled())
        efi_sev_snp_init();

    // 5. 分解内核镜像
    status = efi_decompress_kernel(&kernel_addr);
    if (status != EFI_SUCCESS)
        goto fail;

    // 6. 处理初始化盘（initrd）
    status = efi_load_initrd(boot_params);
    if (status != EFI_SUCCESS)
        goto fail;

    // 7. 设置安全启动状态
    efi_set_secure_boot(boot_params);

    // 8. 配置 EFI 运行时服务
    efi_configure_runtime_services(boot_params);

    // 9. 退出启动服务
    status = exit_boot(boot_params, handle);
    if (status != EFI_SUCCESS)
        goto fail;

    // 10. 跳转到解压后的内核
    enter_kernel(kernel_addr, boot_params);

    // 不会到达这里
}
```

#### Boot Parameters 分配
**文件**: `drivers/firmware/efi/libstub/x86-stub.c:405-447`

```c
static efi_status_t efi_allocate_bootparams(efi_handle_t handle,
                                            struct boot_params **bp)
{
    efi_status_t status;
    efi_loaded_image_t *image;
    struct boot_params *boot_params;

    // 1. 获取 LOADED_IMAGE_PROTOCOL
    status = efi_bs_call(handle_protocol, handle,
                        &LOADED_IMAGE_PROTOCOL_GUID,
                        (void **)&image);
    if (status != EFI_SUCCESS)
        return status;

    // 2. 分配 boot_params 内存
    status = efi_allocate_pages(sizeof(*boot_params),
                               (unsigned long *)&boot_params,
                               ULONG_MAX);
    if (status != EFI_SUCCESS)
        return status;

    // 3. 初始化启动头字段
    memset(boot_params, 0, sizeof(*boot_params));
    boot_params->hdr = hdr;  // 从镜像复制 setup_header

    // 4. 转换 Unicode 命令行为 ASCII
    status = efi_convert_cmdline(image, boot_params);
    if (status != EFI_SUCCESS)
        goto fail_free_params;

    // 5. 设置命令行指针
    boot_params->hdr.cmd_line_ptr = (unsigned long)boot_params->cmdline;

    *bp = boot_params;
    return EFI_SUCCESS;

fail_free_params:
    efi_free_pages((unsigned long)boot_params, sizeof(*boot_params));
    return status;
}
```

### 3. x86_64 长模式启动

#### 压缩内核 64位启动头
**文件**: `arch/x86/boot/compressed/head_64.S`

**关键部分**:
```asm
/* 第132-135行: CPU 长模式验证 */
	testl	$(1 << 29), %edx	/* LM bit */
	jz	.Lno_longmode

/* 第257-278行: 从保护模式切换到长模式 */
	/* 启用 PAE */
	movl	$X86_CR4_PAE, %eax
	movl	%eax, %cr4

	/* 加载页表 */
	leal	rva(pgtable)(%ebx), %eax
	movl	%eax, %cr3

	/* 启用长模式 */
	movl	$MSR_EFER, %ecx
	rdmsr
	btsl	$_EFER_LME, %eax
	wrmsr

	/* 启用分页 */
	movl	%cr0, %eax
	btsl	$X86_CR0_PG_BIT, %eax
	movl	%eax, %cr0

	/* 长跳转到 64位代码 */
	ljmp	$__KERNEL64_CS, $1f

/* 第278行: 64位代码入口 */
	.code64
SYM_CODE_START(startup_64)
	/* ... 64位启动代码 ... */
```

#### PE/COFF 头定义
**文件**: `arch/x86/boot/header.S`

**PE 头结构** (第44-215行):
```asm
	.word	0x5a4d                  # MZ 签名
	# ... DOS stub ...

pe_header:
	.long	0x00004550              # PE 签名 "PE\0\0"

coff_header:
#ifdef CONFIG_X86_32
	.word	0x014c                  # Machine: i386
#else
	.word	0x8664                  # Machine: x86_64
#endif
	.word	section_count           # NumberOfSections
	.long	0                       # TimeDateStamp
	.long	0                       # PointerToSymbolTable
	.long	0                       # NumberOfSymbols
	.word	section_table - optional_header  # SizeOfOptionalHeader
	.word	0x206                   # Characteristics: IMAGE_FILE_EXECUTABLE_IMAGE

optional_header:
#ifdef CONFIG_X86_32
	.word	0x10b                   # PE32 format
#else
	.word	0x20b                   # PE32+ format (64位)
#endif
	.byte	0x02                    # MajorLinkerVersion
	.byte	0x14                    # MinorLinkerVersion

	# ... 各种大小字段 ...

	# 入口点地址
	.long	setup_size + ZO_efi_pe_entry    # AddressOfEntryPoint
```

### 4. Boot Parameters 结构

#### EFI 信息结构
**文件**: `arch/x86/include/uapi/asm/bootparam.h`

```c
/* EFI 信息（在 boot_params 中的偏移 0x1c0） */
struct efi_info {
	__u32 efi_loader_signature;     /* "EL32" 或 "EL64" */
	__u32 efi_systab;               /* EFI 系统表物理地址（低32位） */
	__u32 efi_memdesc_size;         /* EFI 内存描述符大小 */
	__u32 efi_memdesc_version;      /* EFI 内存描述符版本 */
	__u32 efi_memmap;               /* EFI 内存映射物理地址（低32位） */
	__u32 efi_memmap_size;          /* EFI 内存映射大小 */
	__u32 efi_systab_hi;            /* EFI 系统表高32位（64位） */
	__u32 efi_memmap_hi;            /* EFI 内存映射高32位（64位） */
};

/* boot_params 结构（"zeropage"） */
struct boot_params {
	struct screen_info screen_info;              /* 0x000 */
	struct apm_bios_info apm_bios_info;          /* 0x040 */
	__u8  _pad2[4];                              /* 0x054 */
	__u64  tboot_addr;                           /* 0x058 */
	struct ist_info ist_info;                    /* 0x060 */
	__u64 acpi_rsdp_addr;                        /* 0x070 */
	__u8  _pad3[8];                              /* 0x078 */
	__u32 ext_ramdisk_image;                     /* 0x080 */
	__u32 ext_ramdisk_size;                      /* 0x084 */
	__u32 ext_cmd_line_ptr;                      /* 0x088 */
	__u8  _pad4[112];                            /* 0x08c */
	__u32 cc_blob_address;                       /* 0x0fc */
	struct edid_info edid_info;                  /* 0x100 */
	struct efi_info efi_info;                    /* 0x1c0 */
	__u32 alt_mem_k;                             /* 0x1e0 */
	__u32 scratch;                               /* 0x1e4 */
	__u8  e820_entries;                          /* 0x1e8 */
	__u8  eddbuf_entries;                        /* 0x1e9 */
	__u8  edd_mbr_sig_buf_entries;               /* 0x1ea */
	__u8  kbd_status;                            /* 0x1eb */
	__u8  secure_boot;                           /* 0x1ec */
	__u8  _pad5[2];                              /* 0x1ed */
	__u8  sentinel;                              /* 0x1ef */
	__u8  _pad6[1];                              /* 0x1f0 */
	struct setup_header hdr;                     /* 0x1f1 */
	__u8  _pad7[0x290-0x1f1-sizeof(struct setup_header)];
	__u32 edd_mbr_sig_buffer[EDD_MBR_SIG_MAX];   /* 0x290 */
	struct boot_e820_entry e820_table[E820_MAX_ENTRIES_ZEROPAGE]; /* 0x2d0 */
	__u8  _pad8[48];                             /* 0xcd0 */
	struct edd_info eddbuf[EDDMAXNR];            /* 0xd00 */
	__u8  _pad9[276];                            /* 0xeec */
} __attribute__((packed));
```

### 5. EFI 参数提取

#### EFI 类型检测
**文件**: `arch/x86/boot/compressed/efi.c`

```c
enum efi_type efi_get_type(struct boot_params *bp)
{
	if (bp->efi_info.efi_loader_signature == EFI32_LOADER_SIGNATURE)
		return EFI_TYPE_32;
	if (bp->efi_info.efi_loader_signature == EFI64_LOADER_SIGNATURE)
		return EFI_TYPE_64;
	return EFI_TYPE_NONE;
}

unsigned long efi_get_system_table(struct boot_params *bp)
{
	unsigned long sys_tbl_pa;
	enum efi_type et;

	et = efi_get_type(bp);
	if (et == EFI_TYPE_NONE)
		return 0;

	/* 获取 64位 EFI 系统表物理地址 */
	sys_tbl_pa = bp->efi_info.efi_systab;
	if (et == EFI_TYPE_64)
		sys_tbl_pa |= ((__u64)bp->efi_info.efi_systab_hi << 32);

	return sys_tbl_pa;
}

int efi_get_conf_table(struct boot_params *bp,
                      unsigned long *cfg_tbl_pa,
                      unsigned int *cfg_tbl_len)
{
	unsigned long sys_tbl_pa;
	enum efi_type et;

	sys_tbl_pa = efi_get_system_table(bp);
	if (!sys_tbl_pa)
		return -1;

	et = efi_get_type(bp);

	/* 从系统表读取配置表地址和条目数 */
	if (et == EFI_TYPE_64) {
		efi_system_table_64_t *stbl = (efi_system_table_64_t *)sys_tbl_pa;
		*cfg_tbl_pa = stbl->tables;
		*cfg_tbl_len = stbl->nr_tables;
	} else {
		efi_system_table_32_t *stbl = (efi_system_table_32_t *)sys_tbl_pa;
		*cfg_tbl_pa = stbl->tables;
		*cfg_tbl_len = stbl->nr_tables;
	}

	return 0;
}

unsigned long efi_find_vendor_table(struct boot_params *bp,
                                   unsigned long cfg_tbl_pa,
                                   unsigned int cfg_tbl_len,
                                   efi_guid_t guid)
{
	unsigned int i;
	enum efi_type et;

	et = efi_get_type(bp);

	/* 遍历配置表查找匹配的 GUID */
	for (i = 0; i < cfg_tbl_len; i++) {
		unsigned long tbl_pa;

		if (et == EFI_TYPE_64) {
			efi_config_table_64_t *tbl = (efi_config_table_64_t *)cfg_tbl_pa;
			if (!efi_guidcmp(guid, tbl[i].guid))
				return tbl[i].table;
		} else {
			efi_config_table_32_t *tbl = (efi_config_table_32_t *)cfg_tbl_pa;
			if (!efi_guidcmp(guid, tbl[i].guid))
				return tbl[i].table;
		}
	}

	return 0;
}
```

### 6. EFI Mixed Mode（混合模式）

#### 32位 UEFI 在 64位内核上运行
**文件**: `arch/x86/boot/startup/efi-mixed.S`

**32位入口点**:
```asm
SYM_FUNC_START(efi32_stub_entry)          # 32位 EFI 入口
	call	1f
1:	popl	%ecx

	/* 清除 BSS */
	xorl	%eax, %eax
	leal	(_bss - 1b)(%ecx), %edi
	leal	(_ebss - 1b)(%ecx), %ecx
	subl	%edi, %ecx
	shrl	$2, %ecx
	cld
	rep	stosl

	add	$0x4, %esp
	movl	8(%esp), %ebx               # boot_params 指针
	jmp	efi32_startup
SYM_FUNC_END(efi32_stub_entry)
```

**长模式切换** (第109-127行):
```asm
SYM_FUNC_START_LOCAL(efi32_enable_long_mode)
	/* 启用 PAE */
	movl	%cr4, %eax
	btsl	$X86_CR4_PAE_BIT, %eax
	movl	%eax, %cr4

	/* 加载页表 */
	leal	rva(gdt64)(%ebp), %eax
	movl	%eax, 2(%eax)
	lgdt	(%eax)

	/* 启用 EFER.LME */
	movl	$MSR_EFER, %ecx
	rdmsr
	btsl	$_EFER_LME, %eax
	wrmsr

	/* 启用分页 */
	movl	%cr0, %eax
	btsl	$X86_CR0_PG_BIT, %eax
	movl	%eax, %cr0

	/* 禁用中断（固件 IDT 不适用于长模式） */
	cli

	ret
SYM_FUNC_END(efi32_enable_long_mode)
```

### 7. Setup Data 链表

#### 可扩展参数传递
**文件**: `arch/x86/include/uapi/asm/setup_data.h`

```c
/* Setup data 类型 */
#define SETUP_NONE                      0
#define SETUP_E820_EXT                  1
#define SETUP_DTB                       2
#define SETUP_PCI                       3
#define SETUP_EFI                       4
#define SETUP_APPLE_PROPERTIES          5
#define SETUP_JAILHOUSE                 6
#define SETUP_CC_BLOB                   7
#define SETUP_IMA                       8
#define SETUP_RNG_SEED                  9

/* Setup data 结构 */
struct setup_data {
	__u64 next;             /* 下一个 setup_data 的物理地址（0 表示结束） */
	__u32 type;             /* 数据类型 */
	__u32 len;              /* 数据长度 */
	__u8 data[];            /* 具体数据 */
};

/* 用于 SETUP_EFI 类型 */
struct setup_efi_info {
	__u32 efi_loader_signature;
	__u32 efi_systab;
	__u32 efi_memdesc_size;
	__u32 efi_memdesc_version;
	__u32 efi_memmap;
	__u32 efi_memmap_size;
	__u32 efi_systab_hi;
	__u32 efi_memmap_hi;
};
```

### 8. EFI 运行时服务

#### 运行时服务映射
**文件**: `arch/x86/platform/efi/efi_64.c`

```c
void __init efi_map_region(efi_memory_desc_t *md, u64 *addr)
{
	unsigned long size = md->num_pages << EFI_PAGE_SHIFT;
	u64 pa = md->phys_addr;

	if (!(md->attribute & EFI_MEMORY_RUNTIME))
		return;

	/* 映射 EFI 内存区域 */
	*addr = (u64)__va(pa);

	if (kernel_map_pages_in_pgd(pgd, pa, *addr, size,
				    __pgprot(PAGE_KERNEL)))
		pr_err("Error mapping PA 0x%llx -> VA 0x%llx!\n", pa, *addr);
}

int __init efi_setup_page_tables(void)
{
	/* 为 EFI 运行时服务设置页表 */
	pgd = __pa(pgd_alloc(&init_mm));
	if (!pgd)
		return -ENOMEM;

	/* 同步内核映射 */
	efi_sync_low_kernel_mappings();

	return 0;
}
```

### 9. Linux Kernel 目录结构

```
linux/
├── arch/x86/boot/
│   ├── header.S                      # PE/COFF 头和 UEFI 入口点
│   ├── compressed/
│   │   ├── head_64.S                 # 64位压缩内核启动
│   │   ├── efi.c                     # EFI 参数提取
│   │   └── efi.h                     # EFI 类型定义
│   └── startup/
│       └── efi-mixed.S               # EFI 混合模式支持
│
├── arch/x86/include/
│   ├── asm/
│   │   └── efi.h                     # x86 EFI 定义
│   └── uapi/asm/
│       ├── bootparam.h               # boot_params 结构
│       └── setup_data.h              # setup_data 链表
│
├── arch/x86/platform/efi/
│   ├── efi.c                         # EFI 初始化
│   ├── efi_64.c                      # 64位 EFI 运行时服务
│   └── quirks.c                      # EFI 固件怪癖处理
│
└── drivers/firmware/efi/libstub/
    ├── x86-stub.c                    # x86 EFI stub 实现
    ├── efi-stub-helper.c             # EFI stub 辅助函数
    └── efistub.h                     # EFI stub 头文件
```

---

## 完整启动流程

### UEFI 长模式启动时序图

```
┌─────────────────────────────────────────────────────────────────┐
│ UEFI Firmware (Long Mode)                                       │
│   - 已在 64位长模式                                             │
│   - 初始化硬件和内存                                            │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ├─ 加载 GRUB EFI 应用
                                │
┌───────────────────────────────▼─────────────────────────────────┐
│ GRUB x86_64 EFI                                                  │
│   grub-core/kern/x86_64/efi/startup.S                           │
│   - .code64 模式启动                                            │
│   - 接收 image_handle (%rcx) 和 system_table (%rdx)            │
│   - 对齐栈指针（16字节）                                        │
│   - 调用 grub_main()                                            │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ├─ grub_efi_init()
                                │   • 初始化控制台
                                │   • 初始化内存管理
                                │   • 检查 Secure Boot
                                │   • 初始化磁盘
                                │
                                ├─ 用户选择启动项
                                │
                                ├─ grub_efi_load_image()
                                │   • 加载 Linux 内核（PE/COFF 格式）
                                │   • 设置 boot_params
                                │
                                ├─ grub_efi_finish_boot_services()
                                │   • 获取内存映射
                                │   • 调用 ExitBootServices()
                                │
                                ├─ grub_efi_start_image()
                                │
┌───────────────────────────────▼─────────────────────────────────┐
│ Linux Kernel - EFI Stub                                          │
│   drivers/firmware/efi/libstub/x86-stub.c                       │
│                                                                  │
│   efi_pe_entry(handle, sys_table_arg)                           │
│     ↓                                                            │
│   efi_stub_entry(handle, sys_table_arg, boot_params)            │
│     │                                                            │
│     ├─ 1. 验证 EFI 系统表签名                                  │
│     ├─ 2. 分配 boot_params（如果需要）                         │
│     ├─ 3. 解析命令行选项                                       │
│     ├─ 4. 检查 SEV-SNP 功能                                    │
│     ├─ 5. efi_decompress_kernel() - 解压内核                   │
│     ├─ 6. efi_load_initrd() - 加载 initrd                      │
│     ├─ 7. efi_set_secure_boot() - 设置安全启动状态             │
│     ├─ 8. 配置 EFI 运行时服务                                  │
│     ├─ 9. exit_boot() - 退出 EFI Boot Services                 │
│     │      • 记录 EFI 参数到 boot_params.efi_info              │
│     │      • 获取内存映射                                      │
│     │      • 调用 ExitBootServices()                           │
│     └─ 10. enter_kernel(kernel_addr, boot_params)              │
│                                                                  │
└───────────────────────────────┬─────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────┐
│ Linux Kernel - 压缩内核启动                                     │
│   arch/x86/boot/compressed/head_64.S                            │
│                                                                  │
│   startup_32 (32位入口 - 如果从 32位模式进入)                  │
│     ├─ 验证 CPU 支持长模式                                     │
│     ├─ 启用 PAE (CR4.PAE)                                      │
│     ├─ 设置页表 (CR3)                                          │
│     ├─ 启用长模式 (EFER.LME)                                   │
│     ├─ 启用分页 (CR0.PG)                                       │
│     └─ 长跳转到 startup_64                                     │
│                                                                  │
│   startup_64 (64位入口)                                         │
│     ├─ 设置 GDT 和段寄存器                                     │
│     ├─ 设置栈指针                                              │
│     ├─ extract_kernel() - 解压内核到最终位置                  │
│     └─ 跳转到解压后的内核                                      │
│                                                                  │
└───────────────────────────────┬─────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────┐
│ Linux Kernel - 主内核                                           │
│   arch/x86/kernel/head_64.S                                     │
│                                                                  │
│   startup_64                                                    │
│     ├─ 设置初始页表                                            │
│     ├─ 启用 5级分页（如果支持）                                │
│     └─ 跳转到 secondary_startup_64                             │
│                                                                  │
│   secondary_startup_64                                          │
│     ├─ 设置最终页表                                            │
│     ├─ 设置 IDT                                                │
│     └─ 调用 x86_64_start_kernel()                              │
│                                                                  │
│   arch/x86/kernel/head64.c                                      │
│   x86_64_start_kernel()                                         │
│     ├─ 复制 boot_params 到安全位置                             │
│     ├─ 解析 boot_params.efi_info                               │
│     ├─ 设置早期控制台                                          │
│     ├─ 初始化页表                                              │
│     └─ 调用 start_kernel()                                     │
│                                                                  │
│   init/main.c                                                   │
│   start_kernel()                                                │
│     ├─ setup_arch()                                            │
│     │   ├─ efi_init() - 初始化 EFI 运行时服务                 │
│     │   ├─ 解析 e820 内存映射                                 │
│     │   └─ 设置内存管理                                        │
│     ├─ rest_init()                                             │
│     └─ ... 启动 init 进程 ...                                  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 关键数据流

```
UEFI Firmware
    ↓ [传递]
    • EFI System Table
    • Image Handle
    ↓
GRUB
    ↓ [填充]
    • boot_params.efi_info.efi_loader_signature = "EL64"
    • boot_params.efi_info.efi_systab = system_table 地址
    • boot_params.efi_info.efi_memmap = 内存映射地址
    • boot_params.efi_info.efi_memmap_size = 内存映射大小
    • boot_params.hdr.cmd_line_ptr = 命令行地址
    • boot_params.e820_table = E820 内存表
    ↓ [传递给]
Linux EFI Stub
    ↓ [使用]
    • 读取 EFI 系统表
    • 调用 EFI Boot Services
    • 解压内核
    • 加载 initrd
    • 退出 Boot Services
    ↓ [传递给]
Linux Kernel
    ↓ [解析]
    • efi_get_type(boot_params) → EFI_TYPE_64
    • efi_get_system_table(boot_params) → 系统表地址
    • 映射 EFI 运行时服务
    • 初始化内存管理
```

---

## 关键源码位置

### GRUB 关键文件

| 功能 | 文件路径 | 重要性 |
|------|---------|--------|
| x86_64 EFI 启动入口 | `grub-core/kern/x86_64/efi/startup.S` | ⭐⭐⭐⭐⭐ |
| 64位模式切换 | `grub-core/lib/i386/relocator64.S` | ⭐⭐⭐⭐⭐ |
| EFI 64位启动 | `grub-core/lib/x86_64/efi/relocator.c` | ⭐⭐⭐⭐⭐ |
| EFI 初始化 | `grub-core/kern/efi/init.c` | ⭐⭐⭐⭐ |
| 内存管理和 Boot Services | `grub-core/kern/efi/mm.c` | ⭐⭐⭐⭐ |
| EFI Linux 加载器 | `grub-core/loader/efi/linux.c` | ⭐⭐⭐⭐ |
| CPU 模式常量 | `include/grub/i386/memory.h` | ⭐⭐⭐ |
| UEFI API 定义 | `include/grub/efi/api.h` | ⭐⭐⭐ |

### Linux Kernel 关键文件

| 功能 | 文件路径 | 重要性 |
|------|---------|--------|
| PE/COFF 头 | `arch/x86/boot/header.S` | ⭐⭐⭐⭐⭐ |
| EFI Stub 主逻辑 | `drivers/firmware/efi/libstub/x86-stub.c` | ⭐⭐⭐⭐⭐ |
| 压缩内核 64位启动 | `arch/x86/boot/compressed/head_64.S` | ⭐⭐⭐⭐⭐ |
| EFI 参数提取 | `arch/x86/boot/compressed/efi.c` | ⭐⭐⭐⭐ |
| EFI 混合模式 | `arch/x86/boot/startup/efi-mixed.S` | ⭐⭐⭐⭐ |
| Boot Parameters | `arch/x86/include/uapi/asm/bootparam.h` | ⭐⭐⭐⭐ |
| Setup Data | `arch/x86/include/uapi/asm/setup_data.h` | ⭐⭐⭐ |
| EFI 运行时服务 | `arch/x86/platform/efi/efi_64.c` | ⭐⭐⭐ |
| EFI 类型定义 | `arch/x86/boot/compressed/efi.h` | ⭐⭐⭐ |
| x86 EFI 头定义 | `arch/x86/include/asm/efi.h` | ⭐⭐⭐ |

---

## 相关文档

- [UEFI vs BIOS Boot](UEFI_VS_BIOS_BOOT.md) - UEFI 和 BIOS 启动方式对比
- [GRUB Mode Switching](GRUB_MODE_SWITCHING.md) - GRUB 模式切换详解
- [Linux Kernel Setup Flow](LINUX_KERNEL_SETUP_FLOW.md) - Linux 内核启动流程
- [X86 CPU Modes](X86_CPU_MODES.md) - x86 CPU 模式说明
- [GRUB Architecture and Init](GRUB_ARCHITECTURE_AND_INIT.md) - GRUB 架构和初始化
- [Linux Kernel Init](LINUX_KERNEL_INIT.md) - Linux 内核初始化

---

## 总结

GRUB 和 Linux kernel 的 UEFI 长模式启动配合是完美的：

1. **GRUB 端**:
   - 提供成熟的 x86_64 UEFI bootloader 实现
   - 完整的长模式切换逻辑（PAE、EFER.LME、分页）
   - 优雅的 Boot Services 退出机制
   - 支持 Secure Boot 和各种 UEFI 特性

2. **Linux 端**:
   - EFI stub 支持直接从 UEFI 启动
   - PE/COFF 格式内核镜像
   - 完善的 boot_params 参数传递
   - EFI 运行时服务的虚拟映射
   - 混合模式支持（32位 UEFI 在 64位内核）

3. **整体流程**:
   - 整个启动链都是 64位原生的
   - 参数传递机制完善（boot_params.efi_info）
   - 内存映射管理清晰
   - 支持现代安全特性（Secure Boot、SEV-SNP）

这是一个高质量、经过充分测试的实现，支持现代 UEFI 固件环境中的 64位操作系统启动。
