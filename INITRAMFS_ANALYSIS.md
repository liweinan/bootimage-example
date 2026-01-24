# Initramfs 内容分析与 BusyBox 启动设置

本文档详细说明如何分析 initramfs 内容，查找 BusyBox 的启动配置和脚本。

## 相关文档

- **[INITRAMFS_ANALYSIS_RESULT.md](INITRAMFS_ANALYSIS_RESULT.md)** - Alpine Linux Initramfs 实际分析结果
- **[BUSYBOX_SH_EXEC_INIT_DETAILS.md](BUSYBOX_SH_EXEC_INIT_DETAILS.md)** - BusyBox sh 执行 /init 脚本的实现细节（基于 Linux 内核源代码）
- **[ALPINE_INIT_PROCESS_ANALYSIS.md](ALPINE_INIT_PROCESS_ANALYSIS.md)** - Alpine Linux Initramfs Init 启动过程详细分析（基于 mkinitfs 源代码）

## 分析工具

项目提供了分析工具来查看 initramfs 的内容：

### 分析脚本

**[analyze_initramfs.sh](analyze_initramfs.sh)** - 分析本地 initramfs 文件：

```bash
# 使用分析脚本（自动查找 initrd.img）
# 脚本会按顺序查找：
# 1. 当前目录的 *.img 文件（如 initrd-alpine-v3.19.img）
# 2. .grub_iso_cache/ 目录中的 initrd.img
# 3. iso/boot/ 目录中的 initrd.img
# 4. 从 ISO 文件中提取（如果存在）
./analyze_initramfs.sh

# 或指定 initrd.img 文件路径
./analyze_initramfs.sh /path/to/initrd.img
```

## 在运行系统中查找 BusyBox 启动相关文件

在运行系统中查找 BusyBox 的启动配置和脚本：

```bash
# 1. 检查 BusyBox init 的配置文件
ls -l /etc/inittab
cat /etc/inittab  # 如果存在，查看内容

# 2. 检查启动脚本目录
ls -la /etc/init.d/
ls -la /etc/rc.d/  # 某些系统可能使用这个目录

# 3. 检查主启动脚本
ls -l /etc/init.d/rcS
cat /etc/init.d/rcS  # 如果存在，查看内容

# 4. 检查 BusyBox 的符号链接
find /bin /sbin /usr/bin /usr/sbin -type l -exec ls -l {} \; | grep busybox
# 或者
ls -la /bin/ | grep busybox
ls -la /sbin/ | grep busybox

# 5. 检查 /init 脚本（initramfs 中的）
cat /init  # 查看完整的 /init 脚本内容
head -20 /init  # 查看前 20 行
file /init  # 检查文件类型

# 6. 检查环境变量
env | grep -i init
cat /proc/1/environ | tr '\0' '\n'  # 查看 PID 1 的环境变量

# 7. 检查 BusyBox 的版本和配置
/bin/busybox --help
/bin/busybox init --help  # 查看 init 功能的帮助

# 8. 检查是否有其他启动脚本
find /etc -name "*init*" -o -name "*rc*" 2>/dev/null
find / -maxdepth 3 -name "rcS" 2>/dev/null
find / -maxdepth 3 -name "inittab" 2>/dev/null

# 9. 检查当前运行的进程树
ps auxf  # 查看进程树，看 init 启动了哪些进程
pstree  # 如果可用，显示进程树

# 10. 检查系统日志（如果有）
dmesg | grep -i init
cat /proc/cmdline  # 查看内核命令行参数
```

## BusyBox init 的配置文件说明

### 1. `/etc/inittab`（可选）

- BusyBox init 会读取此文件来配置启动行为
- 如果不存在，BusyBox init 使用默认行为
- 格式：`id:runlevels:action:process`
- 示例：
  ```
  ::sysinit:/etc/init.d/rcS
  ::askfirst:/bin/sh
  ::ctrlaltdel:/sbin/reboot
  ::shutdown:/sbin/swapoff -a
  ::shutdown:/bin/umount -a -r
  ```

### 2. `/etc/init.d/rcS`（可选）

- BusyBox init 的默认行为会执行此脚本（如果存在）
- 通常用于执行系统初始化任务
- 必须可执行，第一行通常是 `#!/bin/sh`

### 3. `/init`（initramfs 中）

- 在 initramfs 系统中，内核直接执行 `/init` 作为 PID 1
- `/init` 可能是 shell 脚本，使用 `#!/bin/sh` 或 `#!/bin/busybox sh`
- `/init` 脚本负责初始化系统，可能不会使用 `/etc/inittab`

## 在 initramfs 中的情况

在 initramfs 系统中（如 Alpine netboot）：
- 内核直接执行 `/init`（不是 `/sbin/init`）
- `/init` 脚本可能不依赖 `/etc/inittab`
- `/init` 脚本直接执行初始化任务
- 如果 `/init` 脚本启动 shell，shell 成为 PID 1 的子进程（或通过 exec 成为 PID 1）

## 关于 `/init` 的执行

### 内核代码行为

根据实际的 Linux 内核源代码（`init/main.c`），内核代码按顺序尝试：
1. `/sbin/init`
2. `/etc/init`
3. `/bin/init`
4. `/bin/sh`

> **重要更新**：根据 Linux 内核源代码（`linux/init/main.c`），内核**默认会优先尝试执行 `/init`**！
> 
> 详细说明请参见 [BUSYBOX_SH_EXEC_INIT_DETAILS.md](BUSYBOX_SH_EXEC_INIT_DETAILS.md)。

### `/init` 如何被执行？

**根据 Linux 内核源代码**（`linux/init/main.c`）：

1. **默认执行 `/init`**：
   - 内核有一个默认变量：`ramdisk_execute_command = "/init"`（第 164 行）
   - 在 `kernel_init()` 函数中，如果 `ramdisk_execute_command` 存在且可访问，会优先执行它（第 1499-1504 行）
   - 这意味着内核**默认会尝试执行 `/init`**

2. **通过 `rdinit=` 参数**：
   - 可以通过内核命令行参数 `rdinit=/init` 明确指定
   - 如果指定了 `rdinit=`，会覆盖默认值

3. **Shebang 处理**：
   - 如果 `/init` 是脚本文件（以 `#!/bin/sh` 开头），内核的 `binfmt_script` 模块会处理
   - 内核执行 `/bin/sh /init`（将 `/init` 作为参数传递给 sh）

详细实现细节请参见 [BUSYBOX_SH_EXEC_INIT_DETAILS.md](BUSYBOX_SH_EXEC_INIT_DETAILS.md)。

### 实际验证方法

在运行中的系统检查：
```bash
# 检查 /init 的类型
file /init
ls -l /init

# 检查是否是符号链接
readlink /init

# 检查 /sbin/init 的类型
file /sbin/init
ls -l /sbin/init

# 检查 /bin/sh 是否存在及其类型
file /bin/sh
ls -l /bin/sh

# 检查当前运行的 init 进程
ps aux | grep -E "^.*1.*init"
ls -l /proc/1/exe  # 查看 PID 1 进程的实际可执行文件
cat /proc/1/cmdline  # 查看 PID 1 的命令行参数
```

## `/init` 和 `/sbin/init` 的关系和区别

| 特性 | `/init`（initramfs） | `/sbin/init`（根文件系统） |
|------|---------------------|-------------------------|
| **位置** | initramfs 中 | 真正的根文件系统中 |
| **类型** | 可能是 shell 脚本、二进制文件或符号链接 | 通常是二进制可执行文件（C 程序） |
| **源代码位置** | **不在内核源代码中** | **不在内核源代码中**（用户空间程序） |
| **提供者** | 发行版的 initramfs 构建工具 | 发行版或第三方（systemd、sysvinit 等） |
| **执行时机** | initramfs 阶段（早期启动） | 真正的根文件系统挂载后 |
| **作用** | 初始化系统、加载驱动、准备根文件系统 | 系统主 init 进程、管理服务 |
| **PID** | 通常是 PID 1（如果执行） | 通常是 PID 1（切换根文件系统后） |

## 源代码位置说明

### `/sbin/init` 的源代码

**不在** Linux 内核源代码中（`linux/` 目录）。

- 是用户空间的程序，由各个发行版或第三方提供
- 源代码位置（示例）：
  - **systemd**：`systemd/src/core/main.c`（systemd 项目，不在内核中）
  - **sysvinit**：`sysvinit/src/init.c`（sysvinit 项目，不在内核中）
  - **busybox**：`busybox/init/init.c`（busybox 项目，不在内核中）
- 这些程序编译后安装到系统的 `/sbin/init`
- **总结**：`/sbin/init` 是用户空间程序，源代码在各自的用户空间项目中，不在内核源代码中

### `/init` 的源代码

**也不在内核源代码中**

- 由发行版的 initramfs 构建工具生成
- 源代码位置（示例）：
  - **Alpine**：Alpine 的 initramfs 构建脚本（在 Alpine 的构建系统中，不在内核中）
  - **Debian/Ubuntu**：`mkinitramfs` 工具生成的脚本（不在内核中）
  - **Red Hat/CentOS**：`dracut` 工具生成的脚本（不在内核中）
- **总结**：`/init` 是用户空间的脚本或程序，源代码在发行版的构建系统中，不在内核源代码中

### 内核源代码中的相关代码

- **`linux/init/main.c:kernel_init()`**：内核查找并执行 init 的代码
- **`linux/init/main.c:try_to_run_init_process()`**：尝试执行 init 程序的函数
- **`linux/init/main.c:run_init_process()`**：执行 init 程序的函数（用于 `rdinit=` 参数）
- 这些代码**不包含** `/sbin/init` 或 `/init` 的实现，只是负责执行它们
- **总结**：内核源代码只包含**执行** init 的代码，不包含 init 程序本身的实现

## `/init` 脚本和 `/sbin/init` 的关系

### 执行顺序和关系（包含 BusyBox 的情况）

```
启动流程：
├─ 内核挂载 initramfs 到 /（根目录）
├─ 内核查找并执行 init 程序
│  ├─ 如果指定了 rdinit=/init，执行 /init
│  └─ 否则按顺序尝试：/sbin/init, /etc/init, /bin/init, /bin/sh
│
├─ 如果 /sbin/init 指向 /bin/busybox：
│  ├─ 内核执行 /sbin/init（实际上是 /bin/busybox）
│  ├─ BusyBox 检查 argv[0]，发现是 init，执行 init 功能
│  ├─ BusyBox init 可能会查找并执行 /init 脚本（如果存在）
│  └─ 或者 BusyBox init 直接执行初始化任务
│
├─ 如果执行了 /init（initramfs 中的脚本）：
│  ├─ /init 脚本初始化系统
│  ├─ 加载驱动模块
│  ├─ 准备真正的根文件系统
│  └─ 如果 root=/dev/ram0：启动 shell，不切换根文件系统
│  └─ 如果 root=/dev/sda1：执行 pivot_root，切换到真正的根文件系统
│
└─ 如果切换到真正的根文件系统：
   ├─ /init 脚本执行 pivot_root
   ├─ 卸载 initramfs
   └─ 执行 /sbin/init（真正的根文件系统中的 init 程序）
       └─ 如果 /sbin/init 指向 /bin/busybox，BusyBox 执行 init 功能
```

### 关系和区别

| 特性 | `/init`（initramfs） | `/sbin/init`（根文件系统） |
|------|---------------------|-------------------------|
| **执行时机** | initramfs 阶段（早期启动） | 真正的根文件系统挂载后 |
| **执行顺序** | 先执行（如果存在） | 后执行（切换根文件系统后） |
| **关系** | `/init` 负责准备系统，可能会切换到 `/sbin/init` | `/sbin/init` 是系统的主 init 进程 |
| **切换机制** | `/init` 脚本执行 `pivot_root` 切换到真正的根文件系统 | 切换后，`/sbin/init` 接管成为新的 PID 1 |
| **源代码位置** | 不在内核中，在发行版的构建系统中 | 不在内核中，在用户空间项目中（systemd、sysvinit 等） |

### Alpine netboot initramfs 的具体情况

1. **initramfs 中有 `/init`**：
   - 通常是 shell 脚本（`#!/bin/sh`）或可执行文件
   - 由 Alpine 的 initramfs 构建工具生成
   - 源代码不在内核中，在 Alpine 的构建系统中

2. **执行流程**：
   - 内核挂载 initramfs 后，查找 `/sbin/init`、`/etc/init`、`/bin/init`、`/bin/sh`
   - 如果 initramfs 中有 `/bin/sh`，内核执行 `/bin/sh`
   - 然后 `/bin/sh` 可能会执行 `/init` 脚本（如果 `/init` 存在）
   - 或者通过 `rdinit=/init` 参数直接指定执行 `/init`
   - 或者 `/init` 是符号链接指向 `/bin/sh`

3. **不会切换到真正的根文件系统**：
   - 由于使用 `root=/dev/ram0`，`/init` 脚本不会执行 `pivot_root` 切换
   - `/init` 脚本执行完后启动 shell，shell 继续运行在 initramfs 中
   - **不会执行 `/sbin/init`**（因为真正的根文件系统没有挂载，`/sbin/init` 不存在）

### 如果切换到真正的根文件系统的情况

```
/init 脚本执行流程：
├─ 初始化系统
├─ 加载驱动模块
├─ 挂载真正的根文件系统（如 /dev/sda1）到临时目录
├─ 执行 pivot_root，切换到真正的根文件系统
├─ 卸载 initramfs
└─ 执行 /sbin/init（真正的根文件系统中的 init 程序）
    ├─ 如果 /sbin/init 是二进制文件（如 systemd）：直接执行
    └─ 如果 /sbin/init 指向 /bin/busybox：BusyBox 执行 init 功能
        └─ /sbin/init 成为新的 PID 1，接管系统
```

### BusyBox 在 initramfs 和根文件系统中的角色

**在 initramfs 中：**
- `/bin/busybox`：包含多个工具的功能（sh、init、mount、ls 等）
- `/sbin/init -> /bin/busybox`：BusyBox 的 init 功能
- `/bin/sh -> /bin/busybox`：BusyBox 的 sh 功能
- `/init`：可能是 shell 脚本（使用 `#!/bin/busybox sh` 或 `#!/bin/sh`）

**在真正的根文件系统中：**
- `/bin/busybox`：同样包含多个工具的功能
- `/sbin/init -> /bin/busybox`：BusyBox 的 init 功能作为系统的主 init 进程
- 其他工具也可能指向 `/bin/busybox`

## BusyBox 的工作原理

### BusyBox 如何决定执行哪个功能

1. **通过符号链接**：
   ```bash
   /sbin/init -> /bin/busybox
   /bin/sh -> /bin/busybox
   /bin/ls -> /bin/busybox
   ```
   - 当内核执行 `/sbin/init` 时：
     - 内核解析符号链接，找到实际文件 `/bin/busybox`
     - 内核加载并执行 `/bin/busybox`
     - **关键**：内核设置 `argv[0]` 为 `/sbin/init`（符号链接的路径），而不是 `/bin/busybox`
   - BusyBox 检查 `argv[0]`（程序名），发现是 `/sbin/init`
   - BusyBox 从 `argv[0]` 中提取 basename（文件名部分），得到 `init`
   - BusyBox 根据 `init` 执行 init 功能

2. **通过硬链接**：
   ```bash
   # 创建多个硬链接指向同一个 busybox 文件
   ln /bin/busybox /sbin/init
   ln /bin/busybox /bin/sh
   ```
   - 当执行 `/sbin/init` 时，内核加载 `/bin/busybox`
   - 内核设置 `argv[0]` 为 `/sbin/init`（调用时使用的路径）
   - BusyBox 检查 `argv[0]`，提取 basename `init`，执行 init 功能

3. **通过直接调用**：
   ```bash
   busybox init
   busybox sh
   ```
   - 当执行 `busybox init` 时，`argv[0]` 是 `busybox`，`argv[1]` 是 `init`
   - BusyBox 检查 `argv[1]`（第一个参数），执行相应的功能

### 内核如何设置 `argv[0]`

根据 Linux 内核的行为：
- 当内核调用 `kernel_execve()` 执行程序时，`argv[0]` 被设置为**调用时使用的路径**
- 如果通过符号链接执行，`argv[0]` 是符号链接的路径，而不是实际文件的路径
- 例如：
  ```c
  // 内核代码（简化）
  kernel_execve("/sbin/init", argv_init, envp_init);
  // 即使 /sbin/init 是符号链接指向 /bin/busybox
  // argv[0] 仍然是 "/sbin/init"
  ```

### 实际执行流程

```
内核执行 /sbin/init
   ↓
内核解析符号链接：/sbin/init -> /bin/busybox
   ↓
内核加载 /bin/busybox 到内存
   ↓
内核设置进程的 argv：
   argv[0] = "/sbin/init"  （符号链接的路径）
   argv[1] = NULL
   ↓
内核跳转到用户空间，执行 /bin/busybox
   ↓
BusyBox 程序开始执行
   ↓
BusyBox 检查 argv[0] = "/sbin/init"
   ↓
BusyBox 提取 basename：init
   ↓
BusyBox 执行 init 功能
```

### 内核代码示例

```c
// linux/init/main.c:try_to_run_init_process()
static int try_to_run_init_process(const char *init_filename)
{
    // init_filename = "/sbin/init"
    // argv_init[0] = "/sbin/init"  （即使 /sbin/init 是符号链接）
    return kernel_execve(init_filename, argv_init, envp_init);
}
```

## kernel_execve() 的作用

- 这是内核提供的系统调用，用于从内核空间执行用户空间程序
- 它会：
  1. 加载可执行文件（ELF 格式解析）
  2. 创建用户空间进程（分配进程描述符）
  3. 设置进程内存空间（代码段、数据段、栈等）
  4. 跳转到用户空间执行程序
  5. **这是从内核空间到用户空间的唯一过渡点**

### 对于 shell 脚本（如 `/init`）

> **重要**：根据 Linux 内核源代码，内核**默认会优先尝试执行 `/init`**（通过 `ramdisk_execute_command`，默认值为 `"/init"`）。

- 内核首先检查 `ramdisk_execute_command`（默认 `/init`）是否可以访问
- 如果 `/init` 存在且可访问，内核会执行它
- 如果 `/init` 是 shell 脚本（以 `#!/bin/sh` 开头），内核的 `binfmt_script` 模块会处理
- 内核执行 `/bin/sh /init`（将 `/init` 作为参数传递给 sh）
- sh 读取并解释执行脚本内容

详细实现细节请参见 [BUSYBOX_SH_EXEC_INIT_DETAILS.md](BUSYBOX_SH_EXEC_INIT_DETAILS.md)。

### 对于二进制程序（如 `/sbin/init`）

- 内核直接执行 ELF 二进制文件
- 程序通过系统调用与内核交互

## 总结

- **内核代码**：**默认会优先尝试执行 `/init`**（通过 `ramdisk_execute_command`），然后才尝试 `/sbin/init`、`/etc/init`、`/bin/init`、`/bin/sh`
- **`/sbin/init` 源代码**：不在内核源代码中，是用户空间程序（systemd、sysvinit 等）
- **`/init` 源代码**：不在内核源代码中，由 initramfs 构建工具生成
- **关系**：`/init` 在 initramfs 阶段执行，`/sbin/init` 在真正的根文件系统挂载后执行
- **BusyBox**：一个二进制文件提供多个工具功能，通过符号链接或硬链接实现
- **`argv[0]` 设置**：内核设置 `argv[0]` 为调用时使用的路径（符号链接的路径），BusyBox 通过 `argv[0]` 的 basename 决定执行哪个功能
- **Shebang 处理**：内核的 `binfmt_script` 模块处理脚本文件的 shebang，执行解释器并将脚本路径作为参数传递
