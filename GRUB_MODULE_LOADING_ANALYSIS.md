# GRUB 模块加载机制详细分析

本文档详细分析 GRUB 如何从 `core.img` 中加载嵌入的模块，包括 `FOR_MODULES` 宏的工作原理、模块数据结构、内存布局等。

> **相关文档**：关于 GRUB 内核加载流程，请参见 [GRUB_KERNEL_LOADING.md](GRUB_KERNEL_LOADING.md)。

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

**源代码位置**：`grub/util/mkimage.c:883-910`

```c
void
grub_install_generate_image (const char *dir, const char *prefix,
                             FILE *out, const char *outname, char *mods[],
                             ...)
{
    // mods[] 是模块名称数组（如 ["ext2", "part_msdos", "linux", NULL]）
    
    // 步骤 1: 解析模块依赖关系
    path_list = grub_util_resolve_dependencies (dir, "moddep.lst", mods);
    // 读取 moddep.lst 文件，解析每个模块的依赖关系
    // 返回完整的模块文件路径列表（包括依赖模块）
    
    // 步骤 2: 计算总大小
    total_module_size = sizeof(struct grub_module_info);
    for (p = path_list; p; p = p->next)
        total_module_size += grub_util_get_image_size(p->name) + sizeof(struct grub_module_header);
    
    // 步骤 3: 构建模块信息头部
    modinfo->magic = GRUB_MODULE_MAGIC;
    modinfo->offset = sizeof(struct grub_module_info);
    modinfo->size = total_module_size;
    
    // 步骤 4: 追加每个模块
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

### 2. 模块列表的来源

#### 方式 1：通过 grub-mkimage 命令行参数

**用户直接指定**：
```bash
grub-mkimage --modules "ext2 part_msdos biosdisk normal linux search ls" \
             --output /boot/grub/i386-pc/core.img
```

**源代码位置**：`grub/util/grub-mkimage.c:273`
```c
// 解析 --modules 参数
if (strcmp(arg, "--modules") == 0)
{
    arguments->modules[arguments->nmodules++] = xstrdup(next_arg);
}
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
   ├─ 方式 1: grub-mkimage --modules "ext2 part_msdos linux"
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
