# i386_pc_startup 变量的使用说明

## 问题

`i386_pc_startup` 变量在哪里被使用？

## 答案

`i386_pc_startup` 变量在 GRUB 的构建系统中被使用，用于确保 `startup.S` 是第一个链接的文件。

## 使用位置

### 1. 定义位置

**源代码位置**：`grub/grub-core/Makefile.core.def:116`

```def
kernel = {
  name = kernel;
  ...
  i386_pc_startup = kern/i386/pc/startup.S;
  ...
}
```

### 2. 使用位置（构建系统）

**源代码位置**：`grub/gentpl.py:640, 719`

**函数定义**（第 640 行）：
```python
def platform_startup(defn, p): 
    return platform_specific_values(defn, p, "_startup", "startup")
```

**使用位置**（第 719 行，在 `kernel` 函数中）：
```python
def kernel(defn, platform):
    name = defn['name']
    ...
    var_set(cname(defn) + "_SOURCES", platform_startup(defn, platform))
    var_add(cname(defn) + "_SOURCES", platform_sources(defn, platform))
    ...
```

## 工作原理

### 构建流程

1. **定义文件**（`Makefile.core.def`）：
   - `i386_pc_startup = kern/i386/pc/startup.S;` 定义了 i386_pc 平台的启动文件

2. **生成脚本**（`gentpl.py`）：
   - `platform_startup(defn, "i386_pc")` 函数读取 `i386_pc_startup` 的值
   - 返回 `"kern/i386/pc/startup.S"`

3. **生成的 Makefile**：
   - `var_set(cname(defn) + "_SOURCES", platform_startup(...))` 设置源文件列表
   - 对于 `kernel` 目标，生成的 Makefile 中会有：
     ```makefile
     kernel_SOURCES = kern/i386/pc/startup.S
     kernel_SOURCES += kern/buffer.c kern/command.c ...
     ```
   - **关键点**：`startup.S` 是第一个源文件，确保链接时它是第一个链接的文件

## 为什么重要？

### 链接顺序的重要性

1. **入口点位置**：
   - `startup.S` 包含 `_start` 符号，这是代码的入口点
   - 链接器会将第一个链接的文件放在代码段的开始位置
   - 因此 `_start` 会位于链接基址（`0x9000`）的位置

2. **相对偏移计算**：
   - 链接器需要知道 `_start` 的位置来计算其他符号的相对偏移
   - 如果 `startup.S` 不是第一个文件，`_start` 的位置会改变，导致相对偏移计算错误

3. **位置无关代码**：
   - 虽然代码是位置无关的，但链接器仍然需要知道 `_start` 的位置
   - 所有相对偏移都是相对于 `_start` 计算的

## 生成的 Makefile 示例

**生成的 Makefile 片段**（示例）：

```makefile
# 对于 i386_pc 平台
kernel_SOURCES = kern/i386/pc/startup.S \
                 kern/buffer.c \
                 kern/command.c \
                 kern/corecmd.c \
                 ...
```

**链接命令**（示例）：

```bash
ld -Ttext 0x9000 \
   kern/i386/pc/startup.S.o \
   kern/buffer.c.o \
   kern/command.c.o \
   ... \
   -o kernel.exec
```

**关键点**：
- `startup.S.o` 是第一个目标文件
- 链接器会将 `_start` 符号放在 `0x9000`（链接基址）
- 其他符号的相对偏移都是相对于 `_start` 计算的

## 总结

**`i386_pc_startup` 变量的使用链：**

```
Makefile.core.def (定义)
    ↓
gentpl.py (读取)
    ↓
platform_startup() 函数
    ↓
生成的 Makefile (使用)
    ↓
链接器 (确保 startup.S 是第一个文件)
    ↓
_start 符号位于链接基址 (0x9000)
```

**关键点：**
- ✅ **定义**：`i386_pc_startup = kern/i386/pc/startup.S;` 在 `Makefile.core.def` 中定义
- ✅ **使用**：`gentpl.py` 的 `platform_startup()` 函数读取这个值
- ✅ **生成**：生成的 Makefile 中，`startup.S` 是 `kernel_SOURCES` 的第一个文件
- ✅ **链接**：链接器将 `startup.S` 作为第一个链接的文件，确保 `_start` 位于链接基址

---

## 相关文档

- [GRUB startup_raw.S 解压后跳转到 startup.S 的证明](GRUB_STARTUP_RAW_TO_STARTUP_PROOF.md) - 详细说明 `startup.S` 的作用和链接过程
