# GRUB 模块加载机制详细分析

本文档详细分析 GRUB 如何从 `core.img` 中加载嵌入的模块，包括 `FOR_MODULES` 宏的工作原理、模块数据结构、内存布局等。

> **相关文档与对齐**：内核加载流程、relocator、code32_start 等见 [GRUB_KERNEL_LOADING.md](GRUB_KERNEL_LOADING.md)；relocator 机制细节（安全区、movers_chunk、GDT、BIOS/Legacy 下不执行 Setup）见 [GRUB_RELOCATOR.md](GRUB_RELOCATOR.md)。本文档仅涉及 core.img 内模块加载（FOR_MODULES、grub_modbase），与上述两篇在 scope 上互补。

## 概述

GRUB 的 `grub_load_modules()` 函数通过 `FOR_MODULES` 宏遍历 `core.img` 中嵌入的所有模块，并加载 ELF 格式的模块。这个过程涉及：

1. **模块列表定义**：模块列表在构建 `core.img` 时通过 `grub-mkimage` 或 `grub-install` 指定
2. **模块信息结构**（`grub_module_info`）：位于 `grub_modbase`，包含模块区域的元数据
3. **模块头部结构**（`grub_module_header`）：每个模块都有一个头部，包含类型和大小
4. **FOR_MODULES 宏**：遍历所有模块的循环宏
5. **模块加载**：使用 `grub_dl_load_core()` 从内存加载模块

## 模块列表的定义位置

**关键问题**：`FOR_MODULES` 宏遍历的模块列表是在哪里定义的？

**答案**：模块列表在构建 `core.img` 时通过 `grub-mkimage` 或 `grub-install` 指定，并嵌入到 `core.img` 中。

### 1. 模块列表的构建过程

**源代码位置**：`grub/util/mkimage.c:883-1065`

> ⚠️ **注意**：以下是简化版本，省略了32位/64位区分、字节序转换、对齐处理等实现细节，便于理解整体流程。

```c
void
grub_install_generate_image (const char *dir, const char *prefix,
                             FILE *out, const char *outname, char *mods[],
                             ...)  // 省略了大量其他参数
{
    // mods[] 是模块名称数组（如 ["ext2", "part_msdos", "linux", NULL]）

    // 步骤 1: 解析模块依赖关系（第910行）
    path_list = grub_util_resolve_dependencies (dir, "moddep.lst", mods);
    // 读取 moddep.lst 文件，解析每个模块的依赖关系
    // 返回完整的模块文件路径列表（包括依赖模块）

    // 步骤 2: 计算总大小（第914-992行）
    // 根据平台选择 grub_module_info32 或 grub_module_info64
    total_module_size = sizeof(struct grub_module_info);  // 简化表示
    for (p = path_list; p; p = p->next)
        total_module_size += grub_util_get_image_size(p->name) + sizeof(struct grub_module_header);
    // 实际代码使用 ALIGN_ADDR() 进行对齐

    // 步骤 3: 构建模块信息头部（第1020-1049行）
    modinfo->magic = GRUB_MODULE_MAGIC;
    modinfo->offset = sizeof(struct grub_module_info);
    modinfo->size = total_module_size;
    // 实际代码区分32位/64位，并使用 grub_host_to_target32/addr() 转换字节序

    // 步骤 4: 追加每个模块（第1051-1065行）
    for (p = path_list; p; p = p->next)
    {
        struct grub_module_header *header = (kernel_img + offset);
        header->type = OBJ_TYPE_ELF;
        header->size = mod_size + sizeof(*header);
        offset += sizeof(*header);

        // 复制模块文件内容
        grub_util_load_image(p->name, kernel_img + offset);
        offset += mod_size;
    }
}
```

**实际实现细节：**

1. **32位/64位平台区分**（第997-1049行）：
   - 64位平台：使用 `struct grub_module_info64`
   - 32位平台：使用 `struct grub_module_info32`

2. **对齐处理**（第991行）：
   ```c
   total_module_size += ALIGN_ADDR (grub_util_get_image_size (p->name))
   ```

3. **字节序转换**（第1059-1060行）：
   ```c
   header->type = grub_host_to_target32 (OBJ_TYPE_ELF);
   header->size = grub_host_to_target32 (mod_size + sizeof (*header));
   ```

### 2. 模块列表的来源

#### 方式 1：通过 grub-mkimage 命令行参数

**用户直接指定**（模块名作为位置参数）：
```bash
grub-mkimage -O i386-pc -o /boot/grub/i386-pc/core.img -d /usr/lib/grub/i386-pc \
             ext2 part_msdos biosdisk normal linux search ls
```

**源代码位置**：`grub/util/grub-mkimage.c:272-273`
```c
// 解析位置参数（模块名）
case ARGP_KEY_ARG:
    assert (arguments->nmodules < arguments->modules_max);
    arguments->modules[arguments->nmodules++] = xstrdup(arg);  // 每个模块名作为独立参数
    break;
```

**命令行格式**：`grub/util/grub-mkimage.c:283`
```c
N_("[OPTION]... [MODULES]"),  // 模块作为位置参数，不是选项
```

#### 方式 2：通过 grub-install（自动检测）

**grub-install 会根据以下信息自动添加模块**：

1. **平台特定模块**（根据 `--target` 参数）：
   - **i386-pc**：`biosdisk`（BIOS 磁盘驱动）
   - **x86_64-efi**：`efidisk`（EFI 磁盘驱动）

2. **文件系统检测**（`probe_mods()` 函数）：
   - 检测根文件系统的文件系统类型
   - 自动添加对应的文件系统模块（如 `ext2`, `xfs`, `btrfs` 等）
   - **源代码位置**：`grub/util/grub-install.c:420-477`

3. **分区表检测**（`push_partmap_module()` 函数）：
   - 检测分区表类型（MBR、GPT 等）
   - 自动添加对应的分区表模块（如 `part_msdos`, `part_gpt`）
   - **源代码位置**：`grub/util/grub-install.c:399-411`

4. **压缩算法模块**（`decompressors()` 函数）：
   - 根据压缩算法自动添加（如 `gzio`, `xzio`, `lzopio`）
   - **源代码位置**：`grub/util/grub-install-common.c:596-617`

5. **其他必需模块**：
   - `normal`：normal 模式（菜单显示）
   - `linux`：Linux 内核加载器
   - `search`：search 命令
   - `ls`：ls 命令

**源代码位置**：`grub/util/grub-install-common.c:726-730`
```c
grub_install_generate_image (dir, prefix, fp, outname,
                             modules.entries,  // ← 模块列表
                             memdisk_path, ...);
```

**modules.entries 的构建过程**：
```c
// grub/util/grub-install-common.c:359-360
struct install_list modules = { 1, 0, 0, 0 };  // is_default=1, entries=NULL

// 如果用户通过 --modules 参数指定
grub_install_push_module("ext2");  // modules.is_default = 0, 添加模块

// 或者 grub-install 自动检测并添加
probe_mods(disk);  // 检测文件系统、分区表等，自动添加模块
```

### 3. 模块依赖关系解析

**源代码位置**：`grub/util/resolve.c:236-276`

```c
struct grub_util_path_list *
grub_util_resolve_dependencies (const char *prefix,
                                const char *dep_list_file,  // "moddep.lst"
                                char *modules[])            // 模块名称数组
{
    // 步骤 1: 读取 moddep.lst 文件
    // moddep.lst 包含每个模块的依赖关系
    // 格式示例：
    //   ext2: part_msdos
    //   linux: relocator
    //   normal: search ls
    dep_list = read_dep_list(fp);
    
    // 步骤 2: 解析每个模块及其依赖
    while (*modules)
    {
        add_module(prefix, dep_list, &mod_list, &path_list, *modules);
        // add_module 会递归添加依赖模块
        modules++;
    }
    
    // 步骤 3: 返回完整的模块文件路径列表（包括依赖）
    return path_list;
}
```

**moddep.lst 文件位置**：
- 构建时：`/usr/lib/grub/<platform>/moddep.lst`
- 运行时：`/boot/grub/<platform>/moddep.lst`

**示例 moddep.lst 内容**：
```
ext2: part_msdos
fat: part_msdos part_gpt
linux: relocator
normal: search ls configfile
search: ls
```

### 4. 模块在 core.img 中的嵌入过程

**源代码位置**：`grub/util/mkimage.c:1051-1065`

```c
// 遍历解析后的模块路径列表
for (p = path_list; p; p = p->next)
{
    struct grub_module_header *header;
    size_t mod_size;
    
    // 获取模块文件大小
    mod_size = ALIGN_ADDR(grub_util_get_image_size(p->name));
    
    // 创建模块头部
    header = (struct grub_module_header *)(kernel_img + offset);
    header->type = grub_host_to_target32(OBJ_TYPE_ELF);
    header->size = grub_host_to_target32(mod_size + sizeof(*header));
    offset += sizeof(*header);
    
    // 复制模块文件内容（ELF 格式的 .mod 文件）
    grub_util_load_image(p->name, kernel_img + offset);
    offset += mod_size;
}
```

### 5. 总结：模块列表的定义流程

```
1. 用户或 grub-install 指定模块列表
   ├─ 方式 1: grub-mkimage [选项] ext2 part_msdos linux
   └─ 方式 2: grub-install（自动检测文件系统、分区表等）
       ├─ probe_mods() 检测文件系统 → 添加 ext2, xfs 等
       ├─ push_partmap_module() 检测分区表 → 添加 part_msdos, part_gpt
       ├─ decompressors() 根据压缩算法 → 添加 gzio, xzio
       └─ 添加必需模块：normal, linux, search, ls
   
2. grub_util_resolve_dependencies() 解析依赖
   ├─ 读取 moddep.lst 文件
   ├─ 解析每个模块的依赖关系
   └─ 返回完整的模块文件路径列表（包括依赖）
   
3. grub_install_generate_image() 构建 core.img
   ├─ 计算所有模块的总大小
   ├─ 创建 grub_module_info 头部
   └─ 为每个模块创建头部并追加模块数据
   
4. 模块被嵌入到 core.img 中
   └─ 位于 GRUB 核心代码之后（grub_modbase）
   
5. 运行时 grub_load_modules() 加载
   └─ FOR_MODULES 宏遍历所有嵌入的模块
       └─ 加载 OBJ_TYPE_ELF 类型的模块
```

### 6. 关键源代码文件位置

| 功能 | 文件路径 | 说明 |
|------|---------|------|
| 模块列表构建 | `grub/util/mkimage.c:883-1065` | `grub_install_generate_image()` |
| 依赖关系解析 | `grub/util/resolve.c:236-276` | `grub_util_resolve_dependencies()` |
| 模块添加函数 | `grub/util/grub-install-common.c:394-407` | `grub_install_push_module()` |
| 文件系统检测 | `grub/util/grub-install.c:420-477` | `probe_mods()` |
| 分区表检测 | `grub/util/grub-install.c:399-411` | `push_partmap_module()` |
| 压缩模块添加 | `grub/util/grub-install-common.c:596-617` | `decompressors()` |
| 模块加载 | `grub/grub-core/kern/main.c:58-75` | `grub_load_modules()` |
| FOR_MODULES 宏 | `grub/include/grub/kernel.h:104-110` | 遍历宏定义 |

## 两种模块加载方式的区别

**关键问题**：通过 `grub_load_modules()` 加载的模块和通过 `insmod` 命令加载的模块有什么区别？

### 1. 加载方式对比

| 特性 | `grub_load_modules()`（嵌入模块） | `insmod` 命令（文件系统模块） |
|------|--------------------------------|---------------------------|
| **模块来源** | 嵌入在 `core.img` 中 | 存储在文件系统中（`/boot/grub/i386-pc/*.mod`） |
| **加载时机** | 启动时自动加载（`grub_main()` 中） | 运行时按需加载（`grub.cfg` 中指定） |
| **加载函数** | `grub_dl_load_core(addr, size)` | `grub_dl_load_file(filename)` 或 `grub_dl_load(name)` |
| **数据来源** | 内存（`core.img` 的模块区域） | 文件系统（需要文件系统驱动已加载） |
| **指定方式** | 构建 `core.img` 时通过 `--modules` 参数 | `grub.cfg` 中通过 `insmod` 命令 |
| **依赖关系** | 构建时解析（`moddep.lst`） | 运行时解析（需要文件系统可访问） |
| **内存占用** | 永久占用（直到系统重启） | 动态分配（可卸载） |
| **可用性** | 始终可用（启动时已加载） | 需要文件系统驱动先加载 |

### 2. 源代码实现对比

#### 2.1 `grub_load_modules()` - 嵌入模块加载

**源代码位置**：`grub/grub-core/kern/main.c:58-75`

```c
static void
grub_load_modules (void)
{
    struct grub_module_header *header;
    
    // 遍历 core.img 中嵌入的所有模块
    FOR_MODULES (header)
    {
        // 只加载 ELF 格式的模块
        if (header->type != OBJ_TYPE_ELF)
            continue;
        
        // 从内存加载模块（不需要文件系统）
        if (! grub_dl_load_core ((char *) header + sizeof (struct grub_module_header),
                                 (header->size - sizeof (struct grub_module_header))))
            grub_fatal ("%s", grub_errmsg);
    }
}
```

**关键点**：
- 使用 `FOR_MODULES` 宏遍历 `grub_modbase` 到 `modend` 之间的所有模块
- 直接调用 `grub_dl_load_core(addr, size)`，数据已经在内存中
- **不需要文件系统支持**（此时文件系统驱动可能还未加载）

#### 2.2 `insmod` 命令 - 文件系统模块加载

**源代码位置**：`grub/grub-core/kern/corecmd.c:76-93`

```c
grub_core_cmd_insmod (struct grub_command *cmd, int argc, char *argv[])
{
    grub_dl_t mod;
    
    if (argc == 0)
        return grub_error (GRUB_ERR_BAD_ARGUMENT, "one argument expected");
    
    // 判断是路径还是模块名
    if (argv[0][0] == '/' || argv[0][0] == '(' || argv[0][0] == '+')
        // 路径格式：insmod /boot/grub/i386-pc/ext2.mod
        mod = grub_dl_load_file (argv[0]);
    else
        // 模块名格式：insmod linux（自动查找 $prefix/i386-pc/linux.mod）
        mod = grub_dl_load (argv[0]);
    
    if (mod)
        grub_dl_ref (mod);  // 增加引用计数，防止模块被卸载
    
    return 0;
}
```

**关键点**：
- 支持两种格式：路径（`/boot/grub/i386-pc/ext2.mod`）或模块名（`linux`）
- 模块名格式会自动查找 `$prefix/i386-pc/<name>.mod`
- **需要文件系统支持**（需要读取 `.mod` 文件）

#### 2.3 `grub_dl_load_file()` - 从文件系统加载

**源代码位置**：`grub/grub-core/kern/dl.c:825-865`

```c
grub_dl_t
grub_dl_load_file (const char *filename)
{
    grub_file_t file = NULL;
    grub_ssize_t size;
    void *core = 0;
    grub_dl_t mod = 0;
    
    // 步骤 1: 打开文件（需要文件系统驱动）
    file = grub_file_open (filename, GRUB_FILE_TYPE_GRUB_MODULE);
    if (! file)
        return 0;
    
    // 步骤 2: 读取文件大小
    size = grub_file_size (file);
    
    // 步骤 3: 分配内存
    core = grub_malloc (size);
    if (! core)
    {
        grub_file_close (file);
        return 0;
    }
    
    // 步骤 4: 读取文件内容到内存
    if (grub_file_read (file, core, size) != (int) size)
    {
        grub_file_close (file);
        grub_free (core);
        return 0;
    }
    
    // 步骤 5: 关闭文件（必须在处理依赖之前关闭）
    grub_file_close (file);
    
    // 步骤 6: 从内存加载模块（调用 grub_dl_load_core）
    mod = grub_dl_load_core (core, size);
    
    // 步骤 7: 释放临时缓冲区
    grub_free (core);
    
    if (! mod)
        return 0;
    
    // 步骤 8: 减少引用计数（因为 grub_dl_load_core 会增加引用）
    mod->ref_count--;
    
    return mod;
}
```

**关键点**：
- 需要先打开文件（`grub_file_open`），这需要文件系统驱动已加载
- 读取文件内容到临时缓冲区
- 然后调用 `grub_dl_load_core()` 从内存加载（与嵌入模块使用相同的函数）
- 最后释放临时缓冲区

#### 2.4 `grub_dl_load()` - 通过模块名加载

**源代码位置**：`grub/grub-core/kern/dl.c:869-902`

```c
grub_dl_t
grub_dl_load (const char *name)
{
    char *filename;
    grub_dl_t mod;
    const char *grub_dl_dir = grub_env_get ("prefix");
    
    // 步骤 1: 检查模块是否已加载
    mod = grub_dl_get (name);
    if (mod)
        return mod;
    
    // 步骤 2: 检查是否禁用模块加载
    if (grub_no_modules)
        return 0;
    
    // 步骤 3: 获取 prefix 环境变量（通常是 /boot/grub）
    if (! grub_dl_dir)
    {
        grub_error (GRUB_ERR_FILE_NOT_FOUND, "variable `prefix' isn't set");
        return 0;
    }
    
    // 步骤 4: 构建完整路径（如 /boot/grub/i386-pc/linux.mod）
    filename = grub_xasprintf ("%s/" GRUB_TARGET_CPU "-" GRUB_PLATFORM "/%s.mod",
                               grub_dl_dir, name);
    if (! filename)
        return 0;
    
    // 步骤 5: 从文件系统加载
    mod = grub_dl_load_file (filename);
    grub_free (filename);
    
    if (! mod)
        return 0;
    
    // 步骤 6: 验证模块名称是否匹配
    if (grub_strcmp (mod->name, name) != 0)
        grub_error (GRUB_ERR_BAD_MODULE, "mismatched names");
    
    return mod;
}
```

**关键点**：
- 自动构建模块文件路径：`$prefix/i386-pc/<name>.mod`
- 检查模块是否已加载（避免重复加载）
- 需要 `prefix` 环境变量已设置

#### 2.5 `grub_dl_load_core()` - 核心加载函数（两种方式共用）

**源代码位置**：`grub/grub-core/kern/dl.c:805-821`

```c
grub_dl_load_core (void *addr, grub_size_t size)
{
    grub_dl_t mod;
    
    // 步骤 1: 解析 ELF 文件（不初始化）
    mod = grub_dl_load_core_noinit (addr, size);
    
    if (!mod)
        return NULL;
    
    // 步骤 2: 调用模块初始化函数
    grub_dl_init (mod);  // 调用 mod->init，注册命令等
    
    return mod;
}
```

**关键点**：
- **两种加载方式最终都调用这个函数**
- 区别在于数据来源：
  - 嵌入模块：数据已经在内存中（`core.img` 的模块区域）
  - 文件系统模块：需要先从文件系统读取到临时缓冲区

### 3. 实际使用场景

#### 场景 1：模块嵌入在 core.img 中

```bash
# 构建 core.img 时嵌入 linux 模块
grub-mkimage -O i386-pc -o /boot/grub/i386-pc/core.img -d /usr/lib/grub/i386-pc \
             ext2 part_msdos biosdisk normal linux search ls

# grub.cfg 中无需 insmod
menuentry "Linux" {
    linux /boot/vmlinuz root=/dev/sda1
    initrd /boot/initrd.img
}
```

**流程**：
1. `grub_main()` → `grub_load_modules()` 自动加载所有嵌入模块
2. `linux` 命令立即可用（无需 `insmod linux`）

#### 场景 2：模块不在 core.img 中

```bash
# 构建 core.img 时不包含 linux 模块
grub-mkimage -O i386-pc -o /boot/grub/i386-pc/core.img -d /usr/lib/grub/i386-pc \
             ext2 part_msdos biosdisk normal search ls

# grub.cfg 中需要 insmod
menuentry "Linux" {
    insmod linux        # ← 从文件系统加载 linux.mod
    linux /boot/vmlinuz root=/dev/sda1
    initrd /boot/initrd.img
}
```

**流程**：
1. `grub_main()` → `grub_load_modules()` 加载嵌入模块（不包含 `linux`）
2. 执行 `insmod linux` → `grub_dl_load("linux")` → 从 `/boot/grub/i386-pc/linux.mod` 加载
3. `linux` 命令现在可用

#### 场景 3：按需加载可选模块

```bash
# grub.cfg
menuentry "Graphical Menu" {
    insmod gfxterm      # 图形终端（可选模块）
    insmod gfxmenu      # 图形菜单（可选模块）
    insmod png          # PNG 图像支持（可选模块）
    # ... 使用图形菜单
}
```

**说明**：
- 这些模块通常不嵌入在 `core.img` 中（节省空间）
- 只在需要时通过 `insmod` 加载

### 4. 内存和性能对比

| 特性 | 嵌入模块 | 文件系统模块 |
|------|---------|------------|
| **内存占用** | 永久占用（在 `core.img` 中） | 动态分配（可卸载） |
| **加载速度** | 快（数据已在内存） | 较慢（需要文件 I/O） |
| **文件系统依赖** | 无（启动时加载） | 有（需要文件系统驱动） |
| **core.img 大小** | 较大（包含所有模块） | 较小（只包含必需模块） |
| **灵活性** | 低（构建时确定） | 高（运行时选择） |

### 5. 依赖关系处理

#### 嵌入模块的依赖

**构建时解析**：
```bash
# grub-mkimage 或 grub-install 解析依赖
grub_util_resolve_dependencies(dir, "moddep.lst", mods)
# 读取 moddep.lst，自动添加依赖模块
```

**示例**：
- 指定 `linux` → 自动添加 `relocator`（依赖）
- 指定 `normal` → 自动添加 `search`, `ls`, `configfile`（依赖）

#### 文件系统模块的依赖

**运行时解析**：
```c
// grub/grub-core/kern/dl.c:grub_dl_load_core_noinit()
// 解析 ELF 文件的依赖关系（.dynamic 段）
// 递归加载依赖模块
```

**示例**：
- `insmod linux` → 自动加载 `relocator`（如果未加载）

### 6. 总结

**关键区别**：

1. **数据来源**：
   - 嵌入模块：数据在 `core.img` 中（内存）
   - 文件系统模块：数据在文件系统中（需要 I/O）

2. **加载时机**：
   - 嵌入模块：启动时自动加载（`grub_main()`）
   - 文件系统模块：运行时按需加载（`insmod` 命令）

3. **文件系统依赖**：
   - 嵌入模块：不需要文件系统（启动时加载）
   - 文件系统模块：需要文件系统驱动已加载

4. **灵活性**：
   - 嵌入模块：构建时确定，灵活性低
   - 文件系统模块：运行时选择，灵活性高

5. **最终加载函数**：
   - 两种方式最终都调用 `grub_dl_load_core(addr, size)`
   - 区别在于数据来源和加载时机

## 数据结构定义

### 1. 模块类型枚举

**源代码位置**：`grub/include/grub/kernel.h:25-36`

```c
enum
{
  OBJ_TYPE_ELF,              // ELF 格式的可执行模块（如 ext2.mod, linux.mod）
  OBJ_TYPE_MEMDISK,          // 内存磁盘镜像
  OBJ_TYPE_CONFIG,          // 嵌入的配置文件（grub.cfg）
  OBJ_TYPE_PREFIX,          // 前缀路径信息
  OBJ_TYPE_GPG_PUBKEY,      // GPG 公钥
  OBJ_TYPE_X509_PUBKEY,     // X.509 公钥
  OBJ_TYPE_DTB,             // 设备树（Device Tree）
  OBJ_TYPE_DISABLE_SHIM_LOCK,  // 禁用 Shim Lock
  OBJ_TYPE_DISABLE_CLI      // 禁用命令行界面
};
```

### 2. 模块头部结构

**源代码位置**：`grub/include/grub/kernel.h:39-45`

```c
struct grub_module_header
{
  grub_uint32_t type;  // 模块类型（OBJ_TYPE_ELF, OBJ_TYPE_CONFIG 等）
  grub_uint32_t size;  // 模块大小（包括头部本身）
};
```

**内存布局**：
```
+------------------+
| type (4 bytes)   |  ← 模块类型
+------------------+
| size (4 bytes)   |  ← 模块总大小（包括头部）
+------------------+
| 模块数据         |  ← 实际模块内容（ELF 文件、配置文件等）
| ...              |
+------------------+
```

### 3. 模块信息结构

**源代码位置**：`grub/include/grub/kernel.h:50-69`

**32 位版本**（`grub_module_info32`）：
```c
struct grub_module_info32
{
  grub_uint32_t magic;   // 魔数：GRUB_MODULE_MAGIC (0x676d696d = "gmim")
  grub_uint32_t offset;   // 第一个模块的偏移（相对于 grub_modbase）
  grub_uint32_t size;     // 所有模块的总大小（包括此头部）
};
```

**64 位版本**（`grub_module_info64`）：
```c
struct grub_module_info64
{
  grub_uint32_t magic;      // 魔数：GRUB_MODULE_MAGIC
  grub_uint32_t padding;    // 填充（对齐到 8 字节）
  grub_uint64_t offset;     // 第一个模块的偏移
  grub_uint64_t size;       // 所有模块的总大小
};
```

**根据平台选择**：
```c
#if GRUB_TARGET_SIZEOF_VOID_P == 8
#define grub_module_info grub_module_info64
#else
#define grub_module_info grub_module_info32
#endif
```

**魔数定义**：
```c
/* "gmim" (GRUB Module Info Magic).  */
#define GRUB_MODULE_MAGIC 0x676d696d
```

**内存布局**：
```
grub_modbase (例如 0x108000)
+------------------+
| magic (4 bytes)  |  ← 0x676d696d ("gmim")
+------------------+
| offset (4/8)     |  ← 第一个模块的偏移（通常是 sizeof(grub_module_info)）
+------------------+
| size (4/8)       |  ← 所有模块的总大小
+------------------+
| 模块 1 头部      |  ← grub_modbase + offset
| 模块 1 数据      |
+------------------+
| 模块 2 头部      |
| 模块 2 数据      |
+------------------+
| ...              |
+------------------+
| modend           |  ← grub_modbase + size
+------------------+
```

## grub_modbase 初始化

### i386-pc 平台（BIOS）

**源代码位置**：`grub/grub-core/kern/i386/pc/init.c:229`

```c
grub_addr_t grub_modbase;  // 全局变量，存储模块区域的基址
extern grub_uint8_t _start[], _edata[];

void
grub_machine_init (void)
{
    // grub_modbase 初始化为 GRUB 代码结束后的地址
    grub_modbase = GRUB_MEMORY_MACHINE_DECOMPRESSION_ADDR + (_edata - _start);
    // GRUB_MEMORY_MACHINE_DECOMPRESSION_ADDR = 0x100000 (1MB)
    // _edata - _start = GRUB 代码大小（约 20-50 KB）
    // 因此 grub_modbase ≈ 0x100000 + 0x8000 = 0x108000
}
```

**内存布局示例**：
```
0x100000 (1MB)
+------------------+
| GRUB 代码        |  ← _start 到 _edata（约 20-50 KB）
| (_start 到 _edata)|
+------------------+
| grub_modbase     |  ← 0x108000（GRUB 代码结束后）
| (模块区域开始)    |
+------------------+
| grub_module_info |  ← 模块信息头部
| (magic, offset, size)|
+------------------+
| 模块 1 头部      |  ← grub_modbase + offset
| 模块 1 数据      |
+------------------+
| 模块 2 头部      |
| 模块 2 数据      |
+------------------+
| ...              |
+------------------+
| modend           |  ← grub_modbase + size（约 0x118000，1.1-1.5 MB）
+------------------+
```

## FOR_MODULES 宏详解

### 宏定义

**源代码位置**：`grub/include/grub/kernel.h:104-110`

```c
#define FOR_MODULES(var)  for (\
  var = (grub_modbase && ((((struct grub_module_info *) grub_modbase)->magic) == GRUB_MODULE_MAGIC)) ? (struct grub_module_header *) \
    (grub_modbase + (((struct grub_module_info *) grub_modbase)->offset)) : 0;\
  var && (grub_addr_t) var \
    < (grub_modbase + (((struct grub_module_info *) grub_modbase)->size));    \
  var = (struct grub_module_header *)					\
    (((grub_uint32_t *) var) + ((((struct grub_module_header *) var)->size + sizeof (grub_addr_t) - 1) / sizeof (grub_addr_t)) * (sizeof (grub_addr_t) / sizeof (grub_uint32_t))))
```

### 宏展开分析

这个宏展开为一个 `for` 循环，包含三个部分：

#### 1. 初始化部分（循环变量初始值）

```c
var = (grub_modbase && 
       ((((struct grub_module_info *) grub_modbase)->magic) == GRUB_MODULE_MAGIC)) 
    ? (struct grub_module_header *) 
      (grub_modbase + (((struct grub_module_info *) grub_modbase)->offset)) 
    : 0;
```

**逻辑分析**：
1. **检查 `grub_modbase` 是否有效**：`grub_modbase && ...`
2. **验证魔数**：`((struct grub_module_info *) grub_modbase)->magic == GRUB_MODULE_MAGIC`
   - 将 `grub_modbase` 强制转换为 `struct grub_module_info *`
   - 读取 `magic` 字段，检查是否为 `0x676d696d`（"gmim"）
3. **如果有效**：计算第一个模块的地址
   - `grub_modbase + offset` = 第一个模块头部的地址
   - 转换为 `struct grub_module_header *`
4. **如果无效**：返回 `0`（NULL），循环不执行

**示例计算**：
```
假设：
- grub_modbase = 0x108000
- offset = sizeof(grub_module_info32) = 12 字节
- 第一个模块头部地址 = 0x108000 + 12 = 0x10800C
```

#### 2. 循环条件（继续条件）

```c
var && (grub_addr_t) var < (grub_modbase + (((struct grub_module_info *) grub_modbase)->size))
```

**逻辑分析**：
1. **检查 `var` 是否有效**：`var && ...`
2. **检查是否超出范围**：`(grub_addr_t) var < (grub_modbase + size)`
   - `grub_modbase + size` = 模块区域的结束地址（`modend`）
   - 如果当前模块头部地址 < `modend`，继续循环

**示例计算**：
```
假设：
- grub_modbase = 0x108000
- size = 0x10000 (64 KB)
- modend = 0x108000 + 0x10000 = 0x118000
- 如果 var = 0x10800C < 0x118000，继续循环
```

#### 3. 循环增量（下一个模块）

```c
var = (struct grub_module_header *)
    (((grub_uint32_t *) var) + 
     ((((struct grub_module_header *) var)->size + sizeof (grub_addr_t) - 1) / sizeof (grub_addr_t)) * 
     (sizeof (grub_addr_t) / sizeof (grub_uint32_t)))
```

**逻辑分析**（简化后）：
1. **读取当前模块的大小**：`((struct grub_module_header *) var)->size`
2. **对齐到 `grub_addr_t` 边界**：
   - `(size + sizeof(grub_addr_t) - 1) / sizeof(grub_addr_t)` = 向上取整到地址对齐
   - 例如：如果 `size = 1000` 字节，`sizeof(grub_addr_t) = 4`，则 `(1000 + 3) / 4 = 250` 个 `grub_addr_t` 单位
3. **转换为 `grub_uint32_t` 单位**：
   - `* (sizeof(grub_addr_t) / sizeof(grub_uint32_t))` = 乘以 1（如果两者大小相同）
4. **移动到下一个模块头部**：
   - `((grub_uint32_t *) var) + 对齐后的单位数`

**简化理解**：
```c
// 实际上就是：
var = (struct grub_module_header *)
    ((char *) var + ALIGN_UP(header->size, sizeof(grub_addr_t)));
```

**示例计算**：
```
假设：
- 当前 var = 0x10800C（模块 1 头部）
- header->size = 0x2000 (8192 字节)
- sizeof(grub_addr_t) = 4
- 对齐后大小 = (0x2000 + 3) / 4 * 4 = 0x2000
- 下一个模块头部 = 0x10800C + 0x2000 = 0x10820C
```

## 完整遍历过程示例

假设 `core.img` 中嵌入了以下模块：

```
grub_modbase = 0x108000

0x108000: grub_module_info
  magic = 0x676d696d
  offset = 12 (sizeof(grub_module_info32))
  size = 0x10000 (64 KB)

0x10800C: 模块 1 头部（ext2.mod）
  type = OBJ_TYPE_ELF (0)
  size = 0x2000 (8192 字节)
  数据：ELF 文件内容...

0x10820C: 模块 2 头部（part_msdos.mod）
  type = OBJ_TYPE_ELF (0)
  size = 0x1000 (4096 字节)
  数据：ELF 文件内容...

0x10830C: 模块 3 头部（grub.cfg）
  type = OBJ_TYPE_CONFIG (2)
  size = 0x500 (1280 字节)
  数据：配置文件内容...

0x10880C: 模块 4 头部（linux.mod）
  type = OBJ_TYPE_ELF (0)
  size = 0x3000 (12288 字节)
  数据：ELF 文件内容...

0x108B0C: 结束（modend = 0x118000）
```

**遍历过程**：

```c
// 第一次循环
var = 0x10800C  // 第一个模块头部
header->type = OBJ_TYPE_ELF
header->size = 0x2000
// 加载 ext2.mod
var = 0x10800C + 0x2000 = 0x10820C  // 下一个模块

// 第二次循环
var = 0x10820C  // 第二个模块头部
header->type = OBJ_TYPE_ELF
header->size = 0x1000
// 加载 part_msdos.mod
var = 0x10820C + 0x1000 = 0x10830C  // 下一个模块

// 第三次循环
var = 0x10830C  // 第三个模块头部
header->type = OBJ_TYPE_CONFIG  // 不是 ELF，跳过
header->size = 0x500
// 跳过（不是 OBJ_TYPE_ELF）
var = 0x10830C + 0x500 = 0x10880C  // 下一个模块

// 第四次循环
var = 0x10880C  // 第四个模块头部
header->type = OBJ_TYPE_ELF
header->size = 0x3000
// 加载 linux.mod
var = 0x10880C + 0x3000 = 0x108B0C  // 下一个模块

// 第五次循环
var = 0x108B0C
// 检查：0x108B0C < 0x118000？是，继续
// 但可能没有有效模块头部，循环结束
```

## grub_load_modules() 函数详解

**源代码位置**：`grub/grub-core/kern/main.c:58-75`

```c
/* Load all modules in core.  */
static void
grub_load_modules (void)
{
  struct grub_module_header *header;
  
  FOR_MODULES (header)  // 遍历所有模块
  {
    /* Not an ELF module, skip.  */
    if (header->type != OBJ_TYPE_ELF)
      continue;

    // 加载模块
    // header + sizeof(header) = 模块数据开始地址
    // header->size - sizeof(header) = 模块数据大小
    if (! grub_dl_load_core ((char *) header + sizeof (struct grub_module_header),
			     (header->size - sizeof (struct grub_module_header))))
      grub_fatal ("%s", grub_errmsg);

    if (grub_errno)
      grub_print_error ();
  }
}
```

**关键点**：

1. **遍历所有模块**：`FOR_MODULES` 宏遍历 `grub_modbase` 到 `modend` 之间的所有模块
2. **只加载 ELF 模块**：`if (header->type != OBJ_TYPE_ELF) continue;`
   - 跳过 `OBJ_TYPE_CONFIG`（配置文件）
   - 跳过 `OBJ_TYPE_PREFIX`（前缀信息）
   - 跳过其他非 ELF 类型的对象
3. **计算模块数据地址和大小**：
   - **数据地址**：`(char *) header + sizeof(struct grub_module_header)`
     - 跳过 8 字节的头部，指向实际的 ELF 文件数据
   - **数据大小**：`header->size - sizeof(struct grub_module_header)`
     - 总大小减去头部大小，得到实际数据大小
4. **加载模块**：`grub_dl_load_core(addr, size)`
   - 从内存地址 `addr` 加载大小为 `size` 的 ELF 模块
   - 解析 ELF 头部、符号表、重定位表
   - 调用模块的 `grub_mod_init()` 函数注册命令

## grub_modules_get_end() 函数

**源代码位置**：`grub/grub-core/kern/main.c:43-55`

```c
grub_addr_t
grub_modules_get_end (void)
{
  struct grub_module_info *modinfo;

  modinfo = (struct grub_module_info *) grub_modbase;

  /* Check if there are any modules.  */
  if ((modinfo == 0) || modinfo->magic != GRUB_MODULE_MAGIC)
    return grub_modbase;  // 没有模块，返回起始地址

  return grub_modbase + modinfo->size;  // 返回结束地址（modend）
}
```

**功能**：
- 获取模块区域的结束地址（`modend`）
- 用于内存管理，确定哪些内存区域被 GRUB 模块占用
- 在 `grub_machine_init()` 中用于初始化内存池（排除模块区域）

**使用场景**：
```c
// grub/grub-core/kern/i386/pc/init.c:259-268
modend = grub_modules_get_end ();  // 获取 modend

for (i = 0; i < num_regions; i++)
{
    grub_addr_t beg = mem_regions[i].addr;
    grub_addr_t fin = mem_regions[i].addr + mem_regions[i].size;
    
    // ⚠️ 关键：将起始地址调整到 modend 之后
    if (modend && beg < modend)
        beg = modend;  // 跳过模块区域
    
    // 只将 modend 之后的内存添加到内存池
    if (beg < fin)
        grub_mm_init_region ((void *) beg, fin - beg);
}
```

## 模块在 core.img 中的构建

### grub-mkimage 构建过程

**源代码位置**：`grub/util/mkimage.c`

`grub-mkimage` 在构建 `core.img` 时，会：

1. **收集模块文件**：根据 `--modules` 参数指定的模块列表
2. **构建模块信息头部**：
   ```c
   struct grub_module_info *modinfo = ...;
   modinfo->magic = GRUB_MODULE_MAGIC;
   modinfo->offset = sizeof(struct grub_module_info);
   modinfo->size = total_size;  // 所有模块的总大小
   ```
3. **追加模块**：按顺序追加每个模块
   ```c
   for (each module) {
       struct grub_module_header *header = ...;
       header->type = OBJ_TYPE_ELF;  // 或其他类型
       header->size = module_size + sizeof(header);
       // 追加模块数据（ELF 文件内容）
   }
   ```
4. **嵌入到 core.img**：将模块区域追加到 GRUB 核心代码之后

### 模块在内存中的位置

**BIOS 模式（i386-pc）**：

```
0x100000 (1MB)
+------------------+
| GRUB 核心代码    |  ← _start 到 _edata
| (约 20-50 KB)    |
+------------------+
| grub_modbase     |  ← 0x108000（GRUB 代码结束后）
|                  |
| grub_module_info |  ← 模块信息头部
| (12 字节)        |
+------------------+
| 模块 1 头部      |  ← grub_modbase + offset
| (8 字节)         |
| 模块 1 数据      |
| (ELF 文件)       |
+------------------+
| 模块 2 头部      |
| (8 字节)         |
| 模块 2 数据      |
| (ELF 文件)       |
+------------------+
| ...              |
+------------------+
| modend           |  ← grub_modbase + size（约 0x118000）
+------------------+
| 空闲内存         |  ← 从这里开始添加到内存池
+------------------+
```

## 总结

### 关键数据结构

| 结构 | 位置 | 大小 | 说明 |
|------|------|------|------|
| `grub_module_info` | `grub_modbase` | 12/16 字节 | 模块区域的元数据（魔数、偏移、大小） |
| `grub_module_header` | 每个模块开头 | 8 字节 | 模块头部（类型、大小） |
| 模块数据 | 头部之后 | 可变 | 实际的模块内容（ELF 文件、配置文件等） |

### 关键变量

| 变量 | 类型 | 说明 |
|------|------|------|
| `grub_modbase` | `grub_addr_t` | 模块区域的基址（例如 0x108000） |
| `modend` | `grub_addr_t` | 模块区域的结束地址（例如 0x118000） |

### 关键宏和函数

| 宏/函数 | 位置 | 功能 |
|---------|------|------|
| `FOR_MODULES(var)` | `grub/include/grub/kernel.h:104` | 遍历所有模块的循环宏 |
| `grub_load_modules()` | `grub/grub-core/kern/main.c:58` | 加载所有 ELF 格式的模块 |
| `grub_modules_get_end()` | `grub/grub-core/kern/main.c:43` | 获取模块区域的结束地址 |

### 模块加载流程

```
1. grub_machine_init()
   └─ grub_modbase = 0x100000 + (_edata - _start)  // 初始化模块基址

2. grub_load_modules()
   └─ FOR_MODULES (header)  // 遍历所有模块
       ├─ 检查 header->type == OBJ_TYPE_ELF
       └─ grub_dl_load_core(header + 8, header->size - 8)
           ├─ 解析 ELF 文件
           ├─ 解析符号表
           ├─ 重定位符号
           └─ 调用 grub_mod_init() 注册命令
```

### 内存布局总结

```
0x100000 ─────────────────────────────────┐
│ GRUB 代码（_start 到 _edata）            │ ← 约 20-50 KB
├─ grub_modbase ─────────────────────────┤ ← 0x108000
│ grub_module_info                        │ ← 12/16 字节
│ ├─ magic: 0x676d696d                     │
│ ├─ offset: sizeof(grub_module_info)    │
│ └─ size: 所有模块总大小                  │
├─ 模块 1 头部 + 数据                      │
├─ 模块 2 头部 + 数据                      │
├─ ...                                    │
├─ modend ───────────────────────────────┤ ← 约 0x118000（1.1-1.5 MB）
│                                         │
│ 空闲内存（由 grub_mm_init_region 管理）  │ ← 从这里开始添加到内存池
└─────────────────────────────────────────┘
```

## 源代码文件位置

| 文件 | 路径 | 说明 |
|------|------|------|
| 数据结构定义 | `grub/include/grub/kernel.h` | `grub_module_info`, `grub_module_header`, `FOR_MODULES` 宏 |
| 模块加载函数 | `grub/grub-core/kern/main.c:58-75` | `grub_load_modules()` |
| 模块结束地址 | `grub/grub-core/kern/main.c:43-55` | `grub_modules_get_end()` |
| 模块基址初始化 | `grub/grub-core/kern/i386/pc/init.c:229` | `grub_modbase` 初始化（BIOS 模式） |
| 模块构建 | `grub/util/mkimage.c` | `grub-mkimage` 构建模块区域 |
