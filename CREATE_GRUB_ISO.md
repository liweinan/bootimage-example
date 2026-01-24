# 使用 grub-mkrescue 生成 GRUB ISO 镜像教程

**目标**：在 QEMU 中启动 GRUB2（BIOS 模式），无需完整操作系统，常用于 bootloader 开发、测试或学习。

**适用系统**：Ubuntu / Debian / Pop!_OS 等使用 apt 的发行版  
**当前日期参考**：2026 年 1 月（包名与安装方式基本保持稳定）

## 1. 安装所有必要依赖包

一次性安装所有需要的工具（包含之前遇到的所有缺失依赖）：

```bash
sudo apt update
sudo apt install -y \
    grub-common          \
    grub-pc-bin          \
    grub-efi-amd64-bin   \   # 可选：如果你想测试 UEFI
    xorriso              \
    mtools               \
    qemu-system-x86      \
    qemu-utils
```

- `grub-common` / `grub-pc-bin`：提供 `grub-mkrescue`、`grub-mkstandalone` 等命令
- `xorriso`：生成 ISO 镜像的核心工具
- `mtools`：提供 `mformat` 等命令，用于创建 EFI FAT 分区镜像
- `qemu-system-x86`：QEMU x86_64 模拟器

安装完成后，建议验证：

```bash
grub-mkrescue --version
xorriso --version
mformat -v
qemu-system-x86_64 --version
```

## 2. 方法一：最简单方式 —— 使用 grub-mkrescue 生成 ISO（推荐）

### 步骤

1. 创建工作目录结构

```bash
mkdir -p iso/boot/grub
```

2. （可选）创建一个简单的 grub.cfg 文件

```bash
cat > iso/boot/grub/grub.cfg << 'EOF'
set timeout=3
set default=0

menuentry "GRUB2 Test Mode" {
    echo "Welcome to GRUB2 Shell!"
    echo "You can type commands like ls, cat, multiboot, etc. to test."
}
EOF
```

3. 生成可引导 ISO

```bash
grub-mkrescue -o grub.iso iso
```

### 添加 Linux 内核并配置启动

如果要包含 Linux 内核文件并配置好 grub.cfg 来启动 Linux，有两种方式：

#### 方式 A：使用自动化脚本（推荐）

项目根目录提供了自动化脚本 `create_grub_iso_with_kernel.sh`，可以自动下载所有所需文件并生成完整的 ISO：

```bash
# 运行脚本（假设已安装依赖工具）
./create_grub_iso_with_kernel.sh
```

脚本功能：
- 自动检查依赖工具（grub-mkrescue, wget）
- 自动下载 Linux 内核文件（vmlinuz）和 initrd
- 自动创建目录结构和 grub.cfg 配置
- 自动生成 ISO 文件
- 提供详细的进度输出和使用说明

生成的 ISO 文件：`grub-linux.iso`

#### 方式 B：手动步骤

如果要手动创建，需要以下步骤：

#### 步骤 1：获取 Linux 内核文件

**方法 A：从已安装的 Linux 系统复制**

```bash
# 从当前系统复制内核文件（如果已安装 Linux）
cp /boot/vmlinuz-$(uname -r) iso/boot/vmlinuz
cp /boot/initrd.img-$(uname -r) iso/boot/initrd.img
```

**方法 B：下载预编译的内核（推荐用于测试）**

```bash
# 下载 Debian/Ubuntu 的内核文件（示例）
# 注意：需要下载对应架构的内核（x86_64）
wget -O iso/boot/vmlinuz https://mirrors.kernel.org/debian/dists/stable/main/installer-amd64/current/images/netboot/debian-installer/amd64/linux
wget -O iso/boot/initrd.img https://mirrors.kernel.org/debian/dists/stable/main/installer-amd64/current/images/netboot/debian-installer/amd64/initrd.gz
```

**方法 C：使用 QEMU 测试内核（最小化内核）**

```bash
# 下载或编译一个最小化的 Linux 内核用于测试
# 例如：使用 Linux 内核源码编译，或使用预编译的测试内核
```

#### 步骤 2：配置 grub.cfg 启动 Linux

创建包含 Linux 启动项的 grub.cfg：

```bash
cat > iso/boot/grub/grub.cfg << 'EOF'
set timeout=5
set default=0

menuentry "Linux Kernel" {
    # 设置根设备为 ISO（iso9660 文件系统）
    set root='cd0'
    
    # 加载内核
    linux /boot/vmlinuz root=/dev/ram0 rw console=ttyS0,115200
    
    # 加载初始 RAM 磁盘（如果使用）
    initrd /boot/initrd.img
}

menuentry "GRUB2 Shell" {
    echo "Welcome to GRUB2 Shell!"
    echo "You can type commands like ls, cat, multiboot, etc. to test."
}
EOF
```

**重要说明：**

1. **根设备设置**：`set root='cd0'` 表示从 CD-ROM（ISO）启动
2. **内核参数**：
   - `root=/dev/ram0`：使用 RAM 作为根文件系统（适用于 initrd）
   - `rw`：以读写模式挂载
   - `console=ttyS0,115200`：设置串口控制台（QEMU 中可用 `-serial stdio` 查看）
3. **文件路径**：确保 `vmlinuz` 和 `initrd.img` 在 ISO 的 `/boot/` 目录下

#### 步骤 3：重新生成 ISO

```bash
grub-mkrescue -o grub.iso iso
```

#### 步骤 4：使用 QEMU 启动并测试

```bash
# 基本启动
qemu-system-x86_64 -cdrom grub.iso -boot d -m 512

# 带串口输出（可以看到内核启动日志）
qemu-system-x86_64 -cdrom grub.iso -boot d -m 512 -serial stdio

# 如果需要网络支持（某些内核需要）
qemu-system-x86_64 -cdrom grub.iso -boot d -m 512 -netdev user,id=net0 -device e1000,netdev=net0
```

#### 完整示例脚本

```bash
#!/bin/bash
# create_grub_iso_with_kernel.sh

# 创建工作目录
mkdir -p iso/boot/grub

# 复制内核文件（从当前系统，如果存在）
if [ -f /boot/vmlinuz-$(uname -r) ]; then
    echo "复制内核文件..."
    cp /boot/vmlinuz-$(uname -r) iso/boot/vmlinuz
    cp /boot/initrd.img-$(uname -r) iso/boot/initrd.img 2>/dev/null || echo "警告：未找到 initrd.img"
else
    echo "错误：未找到内核文件，请手动下载或复制内核到 iso/boot/"
    exit 1
fi

# 创建 grub.cfg
cat > iso/boot/grub/grub.cfg << 'EOF'
set timeout=5
set default=0

menuentry "Linux Kernel" {
    set root='cd0'
    linux /boot/vmlinuz root=/dev/ram0 rw console=ttyS0,115200
    initrd /boot/initrd.img
}

menuentry "GRUB2 Shell" {
    echo "Welcome to GRUB2 Shell!"
}
EOF

# 生成 ISO
echo "生成 ISO..."
grub-mkrescue -o grub.iso iso

echo "完成！使用以下命令启动："
echo "qemu-system-x86_64 -cdrom grub.iso -boot d -m 512 -serial stdio"
```

#### 常见问题

1. **内核无法启动**：
   - 检查内核文件是否正确复制到 `iso/boot/`
   - 确认内核架构匹配（x86_64）
   - 检查 grub.cfg 中的路径是否正确

2. **找不到根文件系统**：
   - 如果使用 initrd，确保 `initrd.img` 存在
   - 调整内核参数中的 `root=` 参数

3. **内核参数调整**：
   - 根据实际需求调整内核命令行参数
   - 例如：`quiet`（静默启动）、`nomodeset`（禁用图形模式）等

**常见错误及解决**：

- `xorriso not found` → 安装 `xorriso`
- `mformat invocation failed` → 安装 `mtools`

4. 使用 QEMU 启动

```bash
qemu-system-x86_64 -cdrom grub.iso -boot d -m 512
```

- `-boot d`：强制从 CD-ROM 引导
- `-m 512`：分配 512MB 内存（可根据需要调整）

你应该看到 GRUB 菜单或直接进入 `grub>` 提示符。

## 3. 方法二：生成 Standalone GRUB 镜像（内存加载，无需 ISO）

适用于快速测试 GRUB 命令行或嵌入式场景。

```bash
mkdir -p memdisk/boot/grub

# 可选：创建简单配置
cat > memdisk/boot/grub/grub.cfg << 'EOF'
echo "Standalone GRUB2 已加载！"
insmod all_video
insmod gfxterm
terminal_output gfxterm
EOF

# 生成 standalone 镜像（BIOS 模式）
grub-mkstandalone -O i386-pc \
    -o grub-standalone.img \
    --modules="part_msdos ext2 fat iso9660 normal linux all_video gfxterm" \
    /boot/grub/grub.cfg=memdisk/boot/grub/grub.cfg
```

启动：

```bash
qemu-system-x86_64 -drive file=grub-standalone.img,format=raw -boot c
# 或直接作为 BIOS：
qemu-system-x86_64 -bios grub-standalone.img -m 128
```

## 4. 方法三：模拟真实硬盘安装 GRUB2（最接近真实环境）

1. 创建虚拟硬盘

```bash
qemu-img create -f raw disk.img 128M
```

2. 分区、格式化并安装 GRUB（需要 root 权限）

```bash
sudo losetup -fP disk.img          # 通常得到 /dev/loop0
sudo losetup -a                    # 确认设备

sudo parted /dev/loop0 mklabel msdos
sudo parted /dev/loop0 mkpart primary ext2 1MiB 100%
sudo parted /dev/loop0 set 1 boot on

sudo mkfs.ext2 /dev/loop0p1

mkdir -p mnt
sudo mount /dev/loop0p1 mnt
sudo mkdir -p mnt/boot/grub

# 安装 GRUB 到磁盘
sudo grub-install --root-directory=mnt --no-floppy /dev/loop0

# 创建简单配置
sudo bash -c 'cat > mnt/boot/grub/grub.cfg << EOF
set timeout=5
menuentry "GRUB2 硬盘测试" {
    echo "GRUB2 从虚拟硬盘成功加载！"
}
EOF'

# 清理
sudo umount mnt
sudo losetup -d /dev/loop0
rmdir mnt
```

3. 启动

```bash
qemu-system-x86_64 -drive file=disk.img,format=raw -m 512
```

## 5. 快速调试技巧

- 想直接进入 GRUB shell（无菜单）：
  在 grub.cfg 第一行加：`set pager=1` 和 `normal` 改为 `terminal_input console; terminal_output console`

- UEFI 测试（可选）：
  ```bash
  sudo apt install ovmf
  grub-mkrescue -O x86_64-efi -o grub-uefi.iso iso
  qemu-system-x86_64 -bios /usr/share/OVMF/OVMF.fd -cdrom grub-uefi.iso
  ```

- 增加图形支持：在 grub.cfg 开头加入：
  ```
  insmod all_video
  insmod gfxterm
  terminal_output gfxterm
  ```

## 6. 总结 - 推荐流程（最常用）

```bash
# 一次性安装所有依赖
sudo apt update && sudo apt install -y grub-common grub-pc-bin xorriso mtools qemu-system-x86 qemu-utils

# 创建并生成 ISO
mkdir -p iso/boot/grub
# （可选）echo 'echo Hello GRUB!' > iso/boot/grub/grub.cfg
grub-mkrescue -o grub.iso iso

# 运行
qemu-system-x86_64 -cdrom grub.iso -boot d -m 512
```

完成以上步骤，你就可以自由地在 QEMU 中玩转 GRUB2 了！  

## 7. 快速生成包含 Linux 内核的 ISO（一键脚本）

### 7.1 脚本简介

项目提供了自动化脚本 `create_grub_iso_with_kernel.sh`，可以一键完成所有步骤：
- 自动检查依赖工具
- 自动下载 Linux 内核和 initrd 文件
- 自动创建目录结构和配置文件
- 自动生成可启动的 ISO 文件

### 7.2 使用方法

**基本使用：**

```bash
# 确保脚本有执行权限
chmod +x create_grub_iso_with_kernel.sh

# 运行脚本
./create_grub_iso_with_kernel.sh
```

**脚本执行流程：**

1. **检查依赖**：验证 `grub-mkrescue` 和 `wget` 是否已安装
2. **清理旧文件**：删除之前生成的 ISO 和工作目录
3. **创建目录结构**：创建 `iso/boot/grub` 目录结构
4. **下载内核文件**：
   - 从 Debian 镜像站下载 Linux 内核（vmlinuz）
   - 下载初始 RAM 磁盘（initrd.gz）
5. **创建配置文件**：生成包含多个启动项的 `grub.cfg`
6. **生成 ISO**：使用 `grub-mkrescue` 生成 `grub-linux.iso`

### 7.3 脚本配置选项

脚本中的可配置变量（位于脚本开头）：

```bash
# ISO 文件名
ISO_NAME="grub-linux.iso"

# Debian 镜像源（可以根据网络情况修改）
DEBIAN_MIRROR="https://mirrors.kernel.org/debian"

# Debian 版本（可选：stable, bookworm, testing 等）
DEBIAN_VERSION="bookworm"

# 架构（amd64 或 i386）
ARCH="amd64"
```

**修改配置示例：**

```bash
# 使用国内镜像源（如果下载速度慢）
# 编辑脚本，修改 DEBIAN_MIRROR 变量：
DEBIAN_MIRROR="https://mirrors.tuna.tsinghua.edu.cn/debian"

# 使用稳定版
DEBIAN_VERSION="stable"
```

### 7.4 脚本输出说明

脚本运行时会显示：

- **绿色输出**：成功完成的操作
- **黄色输出**：进行中的操作和提示信息
- **红色输出**：错误信息

**示例输出：**

```
=== GRUB ISO 生成脚本 ===

检查依赖工具...
✓ 依赖工具检查通过

清理旧文件...
✓ 清理完成

创建目录结构...
✓ 目录结构创建完成

下载 Linux 内核文件...
内核 URL: https://mirrors.kernel.org/debian/...
✓ 内核文件下载完成: iso/boot/vmlinuz

下载 initrd 文件...
✓ initrd 文件下载完成: iso/boot/initrd.img

创建 grub.cfg 配置文件...
✓ grub.cfg 创建完成

生成 ISO 文件...
✓ ISO 文件生成成功: grub-linux.iso
文件大小: 15M
```

### 7.5 生成的 ISO 内容

生成的 `grub-linux.iso` 包含：

1. **Linux - Boot to Shell**：使用 Alpine Linux 内核，启动后直接进入 shell 环境
2. **Linux - Boot to Shell (Verbose)**：详细模式启动，显示更多调试信息
3. **Debug: List Files**：调试菜单，用于检查文件系统访问和文件是否存在

**重要说明：**
- 脚本使用 Alpine Linux netboot 内核（非安装器），启动后直接进入可用的 shell 环境
- 支持使用 `--local` 参数使用本地系统内核
- 所有启动项都需要 initrd，确保系统能正常启动

### 7.6 启动生成的 ISO

**基本启动（推荐）：**

```bash
qemu-system-x86_64 -cdrom grub-linux.iso -boot d -m 1024 -serial stdio
```

**使用 SDL 图形显示（推荐）：**

```bash
qemu-system-x86_64 -display sdl -cdrom grub-linux.iso -boot d -m 1024 -serial stdio
```

**参数说明：**
- `-cdrom grub-linux.iso`：指定 ISO 文件
- `-boot d`：从 CD-ROM 启动
- `-m 1024`：分配 1024MB 内存（Alpine 建议至少 512MB，推荐 1GB）
- `-serial stdio`：**必须使用此参数**，将串口输出到终端（可以看到内核启动日志和 shell）
- `-display sdl`：使用 SDL 图形显示（可选，提供更好的图形界面体验）

**重要提示：**
- **必须使用 `-serial stdio` 参数**：内核输出会显示在终端，而不是 QEMU 窗口
- `-display sdl` 提供独立的图形窗口，适合需要同时查看图形界面和终端输出的场景
- 如果看到黑屏，检查是否使用了 `-serial stdio` 参数
- 内核启动后，Alpine Linux 会显示 shell 提示符，可以直接使用

**启动流程：**

```
1. GRUB 菜单显示（5 秒超时）
   ↓
2. 用户选择 "Linux - Boot to Shell" 菜单项
   ↓
3. GRUB 执行 linux 命令
   ├─ 加载 vmlinuz（Linux 内核）到内存（0x100000）
   ├─ 设置内核启动参数（boot_params）
   └─ 注册启动函数
   ↓
4. GRUB 执行 initrd 命令
   ├─ 加载 initrd.img（Alpine 的 initramfs）到内存
   └─ 在 boot_params 中设置 ramdisk_image 和 ramdisk_size
   ↓
5. GRUB 跳转到内核入口点（code32_start）
   ↓
6. Linux 内核开始执行
   ├─ Setup 代码（实模式）
   ├─ 解压内核代码
   ├─ 切换到保护模式/长模式
   └─ 执行 startup_64（内核入口点）
   ↓
7. 内核初始化
   ├─ 初始化基本系统
   ├─ 从 boot_params 读取 initrd 位置
   └─ 挂载 initramfs 作为根文件系统（/）
   ↓
8. 内核执行 initramfs 中的 /init 脚本
   ├─ Alpine 的 initramfs 包含完整的 Alpine Linux 系统
   ├─ /init 脚本初始化系统（加载驱动、设置网络等）
   └─ /init 脚本最后启动 shell（通常是 /bin/sh 或 /bin/ash）
   ↓
9. 进入 Alpine Linux shell 环境
   └─ **shell 运行在 initramfs 的虚拟文件系统中（RAM 文件系统）**
   └─ 用户可以直接使用 shell 命令
```

**关键点说明：**

1. **`linux` 命令的作用**：
   - `linux` 是 GRUB 的命令，用于加载 Linux 内核到内存
   - 它只是将内核文件从磁盘复制到内存，并设置启动参数
   - **`linux` 命令本身不启动 shell**

2. **`vmlinuz`（内核）的作用**：
   - `vmlinuz` 是 Linux 内核本身
   - 内核启动后负责初始化系统、挂载文件系统
   - **内核本身也不直接启动 shell**

3. **shell 的启动过程**：
   - 内核挂载 initramfs 后，会查找并执行 `/init` 脚本（或 `/linuxrc`）
   - **Alpine 的 initramfs 中的 `/init` 脚本负责启动 shell**
   - `/init` 脚本会：
     - 初始化系统环境
     - 加载必要的驱动模块
     - 设置网络（如果需要）
     - **最后执行 `/bin/sh` 或 `/bin/ash` 启动 shell**

**init 脚本的类型和执行机制：**

**1. init 脚本的类型：**

**在 initramfs 中：**
- **`/init`**：通常是 shell 脚本（文本文件，以 `#!/bin/sh` 或 `#!/bin/ash` 开头）
- **示例**（Alpine netboot）：
  ```bash
  #!/bin/sh
  # Alpine Linux init script
  mount -t proc proc /proc
  mount -t sysfs sysfs /sys
  # ... 初始化系统 ...
  exec /bin/sh  # 启动 shell
  ```
- **执行方式**：
  1. 内核查找 `/sbin/init`、`/etc/init`、`/bin/init`、`/bin/sh`（按顺序）
  2. 如果这些都不存在，但存在 `/init`，内核会执行 `/init`
  3. 如果 `/init` 是 shell 脚本，内核执行 `/bin/sh`，然后 sh 解释执行脚本内容

**在真正的根文件系统中：**
- **`/sbin/init`**：通常是二进制可执行文件（C 程序），如 systemd、sysvinit、openrc 等
- **执行方式**：内核直接执行二进制文件

**Alpine netboot 的 initramfs：**
- 包含 `/init` 脚本（shell 脚本）
- 由于使用 `root=/dev/ram0`，不会切换到真正的根文件系统
- `/init` 脚本执行完后启动 shell
- 如果切换到真正的根文件系统，`/sbin/init`（二进制程序）会接管

**2. 内核如何执行 init 过程：**

**内核执行 init 的流程：**

```
内核初始化完成
   ↓
内核挂载 initramfs 到 /（根目录）
   ↓
内核按顺序查找并尝试执行 init 程序：
   1. /sbin/init
   2. /etc/init
   3. /bin/init
   4. /bin/sh
   （找到第一个存在的就执行，不再继续查找）
   ↓
内核调用 kernel_execve() 系统调用
   ├─ 这是内核空间到用户空间的过渡点
   ├─ 内核创建第一个用户空间进程（PID 1）
   └─ 执行找到的 init 程序
   ↓
init 程序开始执行
   ├─ 如果是 shell 脚本：内核执行 /bin/sh，sh 解释执行脚本
   └─ 如果是二进制：内核直接执行二进制文件
   ↓
init 成为 PID 1 进程（用户空间的第一个进程）
   └─ 所有后续进程都是 init 的子进程
```

**关键代码位置（Linux 内核）：**

```c
// linux/init/main.c:kernel_init()
static int __ref kernel_init(void *unused)
{
    // ... 内核初始化 ...
    
    // 如果指定了 rdinit= 参数，优先执行（用于 initramfs）
    if (ramdisk_execute_command) {
        ret = run_init_process(ramdisk_execute_command);
        if (!ret)
            return 0;
    }
    
    // 按顺序尝试执行 init 程序
    // 注意：根据实际源代码，内核只尝试这些路径，不包含 /init
    if (!try_to_run_init_process("/sbin/init") ||
        !try_to_run_init_process("/etc/init") ||
        !try_to_run_init_process("/bin/init") ||
        !try_to_run_init_process("/bin/sh"))
        return 0;
    
    // 如果都不存在，内核会 panic
    panic("No working init found.  Try passing init= option to kernel.");
}

// linux/init/main.c:try_to_run_init_process()
static int try_to_run_init_process(const char *init_filename)
{
    int ret;
    
    // 使用 kernel_execve() 执行 init 程序
    ret = kernel_execve(init_filename, argv_init, envp_init);
    
    return ret;
}
```

**关于 `/init` 的执行代码：**

**问题 1：内核会尝试执行 `/init` 的具体代码在哪里？**

**答案**：根据你提供的实际源代码，内核**不会直接尝试执行 `/init`**。

内核代码只按顺序尝试：
1. `/sbin/init`
2. `/etc/init`
3. `/bin/init`
4. `/bin/sh`

**那么 `/init` 是如何被执行的？可能的机制：**

1. **通过 `rdinit=` 参数**（最明确的方式）：
   ```c
   // 如果指定了 rdinit= 参数，优先执行
   if (ramdisk_execute_command) {
       ret = run_init_process(ramdisk_execute_command);
       if (!ret)
           return 0;
   }
   ```
   - 内核命令行参数：`rdinit=/init`
   - 内核会优先执行 `rdinit=` 指定的程序
   - 这是执行 `/init` 的明确方式

2. **通过符号链接（BusyBox 的情况）**：
   - 如果 `/sbin/init` 是符号链接指向 `/bin/busybox`，内核执行 `/sbin/init` 时实际上会执行 `/bin/busybox`
   - BusyBox 根据 `argv[0]`（程序名）决定执行哪个功能
   - 如果 `/sbin/init` 指向 `/bin/busybox`，busybox 会执行 `init` 功能
   - **但是，如果 initramfs 中有 `/init` 脚本，busybox 的 init 功能可能会执行 `/init` 脚本**

3. **通过 `/bin/sh` 执行脚本**：
   - 如果 `/bin/sh` 存在，内核执行 `/bin/sh`
   - 然后 `/bin/sh` 可能会执行 `/init` 脚本（如果 `/init` 存在且 `/bin/sh` 知道要执行它）

**实际运行系统的发现：**

根据你的观察，实际运行系统中 `/sbin/init` 指向 `/bin/busybox`。

**BusyBox 的工作原理：**

BusyBox 是一个"多合一"的二进制文件，包含多个 Unix 工具的功能（如 `sh`、`init`、`mount`、`ls` 等）。

**BusyBox 如何决定执行哪个功能：**

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

**内核如何设置 `argv[0]`：**

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

**实际执行流程：**

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

**总结：内核设置 `argv[0]` 的规则：**

1. **内核调用 `kernel_execve(path, argv, envp)` 时**：
   - `argv[0]` 由调用者传入（通常是路径）
   - 如果通过符号链接执行，`argv[0]` 是符号链接的路径，不是实际文件的路径

2. **内核代码示例（简化）**：
   ```c
   // linux/init/main.c:try_to_run_init_process()
   static int try_to_run_init_process(const char *init_filename)
   {
       // init_filename = "/sbin/init"
       // argv_init[0] = "/sbin/init"  （即使 /sbin/init 是符号链接）
       return kernel_execve(init_filename, argv_init, envp_init);
   }
   ```

3. **BusyBox 的行为**：
   - BusyBox 检查 `argv[0]`，提取 basename（文件名部分）
   - 如果 `argv[0]` 是 `/sbin/init`，提取得到 `init`，执行 init 功能
   - 如果 `argv[0]` 是 `/bin/sh`，提取得到 `sh`，执行 sh 功能

**`/init` 在 initramfs 中的执行机制：**

**情况 1：`/init` 是 shell 脚本**
```bash
#!/bin/busybox sh
# 或者
#!/bin/sh
```
- 内核执行 `/sbin/init`（指向 `/bin/busybox`）
- BusyBox 的 init 功能启动
- BusyBox init 可能会查找并执行 `/init` 脚本（如果存在）
- 或者内核直接执行 `/bin/sh`（如果 `/bin/sh` 存在），然后 sh 执行 `/init` 脚本

**情况 2：`/init` 是符号链接指向 `/bin/busybox`**
```bash
/init -> /bin/busybox
```
- 如果内核尝试执行 `/init`（通过 `rdinit=/init` 或其他方式），会执行 `/bin/busybox`
- BusyBox 检查 `argv[0]`，发现是 `init`，执行 init 功能

**情况 3：`/init` 是二进制可执行文件**
- 内核直接执行 `/init`（如果是可执行的二进制文件）

**实际运行系统的执行流程（推测）：**

```
内核挂载 initramfs
   ↓
内核查找并执行 init 程序
   ├─ 尝试 /sbin/init
   │  └─ /sbin/init -> /bin/busybox
   │     └─ BusyBox 执行 init 功能
   │        └─ BusyBox init 可能会查找并执行 /init 脚本（如果存在）
   │
   └─ 或者尝试 /bin/sh
      └─ /bin/sh -> /bin/busybox
         └─ BusyBox 执行 sh 功能
            └─ sh 可能会执行 /init 脚本（如果存在）
```

**验证方法：**

在运行中的系统检查：
```bash
# 检查 /sbin/init 的指向
ls -l /sbin/init
readlink /sbin/init

# 检查 /init 的类型和内容
file /init
ls -l /init
head -n 5 /init  # 查看前几行，看是否是脚本

# 检查 /bin/busybox
file /bin/busybox
ls -l /bin/busybox

# 检查当前运行的 PID 1 进程
ps aux | grep -E "^.*1.*"
ls -l /proc/1/exe  # 查看 PID 1 的实际可执行文件
cat /proc/1/cmdline  # 查看 PID 1 的命令行参数

# 检查 busybox 支持的功能
/bin/busybox --list  # 列出 busybox 支持的所有功能
```

> **详细说明**：关于 initramfs 内容分析和 BusyBox 启动设置的完整文档，请参见 [INITRAMFS_ANALYSIS.md](INITRAMFS_ANALYSIS.md)。

**带网络支持：**

```bash
qemu-system-x86_64 -cdrom grub-linux.iso -boot d -m 1024 -serial stdio \
    -netdev user,id=net0 -device e1000,netdev=net0
```

**使用图形界面（VGA 显示）：**

```bash
# 注意：即使使用 VGA，也建议同时使用 -serial stdio 查看内核日志
qemu-system-x86_64 -cdrom grub-linux.iso -boot d -m 1024 -vga std -serial stdio
```

**使用 SDL 图形显示（推荐图形界面）：**

```bash
# SDL 提供更好的图形界面体验，同时保留终端输出
qemu-system-x86_64 -display sdl -cdrom grub-linux.iso -boot d -m 1024 -serial stdio
```

**显示选项说明：**
- `-display sdl`：使用 SDL 图形显示（推荐，提供独立窗口）
- `-vga std`：使用标准 VGA 显示（传统方式）
- `-nographic`：无图形界面，所有输出到串口（适合服务器环境）

### 7.7 故障排除

**问题 1：下载失败**

```
错误: 内核文件下载失败
```

**解决方案：**
- 检查网络连接
- 尝试修改脚本中的 `DEBIAN_MIRROR` 为其他镜像源
- 手动下载文件到 `iso/boot/` 目录

**问题 2：依赖工具未找到**

```
错误: 未找到 grub-mkrescue，请先安装
```

**解决方案：**
```bash
sudo apt install grub-pc-bin wget
```

**问题 3：ISO 生成失败**

```
错误: ISO 文件生成失败
```

**解决方案：**
- 检查 `xorriso` 和 `mtools` 是否已安装：`sudo apt install xorriso mtools`
- 检查工作目录是否有写权限
- 查看详细错误信息

**问题 4：内核无法启动或黑屏**

**解决方案：**
- **确认使用了 `-serial stdio` 参数**：内核输出显示在终端，不是 QEMU 窗口
- 确认内核文件已正确下载（检查 `iso/boot/vmlinuz` 文件大小）
- 检查 grub.cfg 中的路径是否正确
- 尝试使用 "Linux - Boot to Shell (Verbose)" 菜单项查看详细启动日志
- 增加内存分配：使用 `-m 1024` 或更多

**问题 5：GRUB 无法访问文件系统（"no server is specified" 错误）**

**解决方案：**
- 使用 "Debug: List Files" 菜单项检查文件系统访问
- 确认文件确实存在于 ISO 中（参见下面的"挂载 ISO 查看文件"部分）
- 检查 GRUB 模块是否正确加载（iso9660, loopback 等）

### 7.9 调试方法

#### 方法 1：使用 GRUB 调试菜单

生成的 ISO 包含 "Debug: List Files" 菜单项，可以：
- 检查根设备是否正确识别
- 列出文件系统中的文件
- 验证内核和 initrd 文件是否存在

**使用步骤：**
1. 启动 ISO
2. 在 GRUB 菜单中选择 "Debug: List Files"
3. 查看文件列表和访问状态

#### 方法 2：在 GRUB 命令行手动调试

如果菜单无法正常工作，可以在 GRUB 启动时按 `c` 进入命令行模式：

```bash
# 在 GRUB 菜单界面按 'c' 进入命令行
grub> insmod iso9660
grub> insmod loopback
grub> search --file /boot/grub/grub.cfg
grub> set root=$root
grub> ls /
grub> ls /boot/
grub> ls /boot/vmlinuz
grub> ls /boot/initrd.img
```

#### 方法 3：使用详细模式启动

选择 "Linux - Boot to Shell (Verbose)" 菜单项，可以看到：
- 内核加载过程
- 驱动加载信息
- 系统初始化日志
- 错误信息（如果有）

#### 方法 4：检查 QEMU 启动参数

确保使用正确的启动参数：

```bash
# 正确：使用 -serial stdio 查看输出
qemu-system-x86_64 -cdrom grub-linux.iso -boot d -m 1024 -serial stdio

# 错误：没有 -serial stdio，输出不可见
qemu-system-x86_64 -cdrom grub-linux.iso -boot d -m 1024
```

### 7.10 挂载 ISO 查看文件内容

在生成 ISO 后，可以挂载 ISO 文件来检查其中的内容：

#### 方法 1：使用 mount 命令（Linux/macOS）

```bash
# 创建挂载点
mkdir -p /tmp/iso_mount

# 挂载 ISO（Linux）
sudo mount -o loop grub-linux.iso /tmp/iso_mount

# 挂载 ISO（macOS）
hdiutil attach grub-linux.iso -mountpoint /tmp/iso_mount

# 查看文件结构
ls -la /tmp/iso_mount/
ls -la /tmp/iso_mount/boot/
ls -la /tmp/iso_mount/boot/grub/

# 检查关键文件
ls -lh /tmp/iso_mount/boot/vmlinuz
ls -lh /tmp/iso_mount/boot/initrd.img
cat /tmp/iso_mount/boot/grub/grub.cfg

# 卸载 ISO（Linux）
sudo umount /tmp/iso_mount

# 卸载 ISO（macOS）
hdiutil detach /tmp/iso_mount

# 清理挂载点
rmdir /tmp/iso_mount
```

#### 方法 2：使用 7z 或 unzip（跨平台）

```bash
# 使用 7z 查看 ISO 内容（如果已安装）
7z l grub-linux.iso

# 使用 unzip 提取文件（某些 ISO 格式支持）
unzip -l grub-linux.iso
```

#### 方法 3：使用 isoinfo（Linux）

```bash
# 查看 ISO 文件系统信息
isoinfo -i grub-linux.iso -d

# 列出 ISO 中的文件
isoinfo -i grub-linux.iso -f

# 提取特定文件
isoinfo -i grub-linux.iso -x /BOOT/GRUB/GRUB.CFG
```

#### 验证文件完整性

挂载 ISO 后，可以验证：

1. **检查文件是否存在**：
   ```bash
   [ -f /tmp/iso_mount/boot/vmlinuz ] && echo "内核文件存在" || echo "内核文件缺失"
   [ -f /tmp/iso_mount/boot/initrd.img ] && echo "initrd 文件存在" || echo "initrd 文件缺失"
   [ -f /tmp/iso_mount/boot/grub/grub.cfg ] && echo "grub.cfg 存在" || echo "grub.cfg 缺失"
   ```

2. **检查文件大小**：
   ```bash
   ls -lh /tmp/iso_mount/boot/vmlinuz    # 应该显示几 MB 到几十 MB
   ls -lh /tmp/iso_mount/boot/initrd.img # 应该显示几 MB 到几十 MB
   ```

3. **检查 grub.cfg 内容**：
   ```bash
   cat /tmp/iso_mount/boot/grub/grub.cfg
   # 确认包含正确的启动项和文件路径
   ```

#### 常见问题排查

**如果挂载后看不到文件：**
- 确认 ISO 文件已正确生成（检查文件大小）
- 尝试使用不同的挂载方法
- 检查 ISO 文件是否损坏

**如果文件大小异常：**
- 内核文件（vmlinuz）通常为 5-50 MB
- initrd 文件通常为 5-100 MB
- 如果文件大小为 0 或异常小，说明下载或生成过程有问题

### 7.8 自定义脚本

如果需要自定义脚本行为，可以：

1. **修改内核来源**：编辑脚本中的 `KERNEL_URL` 和 `INITRD_URL`
2. **修改 grub.cfg**：编辑脚本中生成 grub.cfg 的部分
3. **添加更多启动项**：在 grub.cfg 生成部分添加新的 menuentry

**示例：添加自定义启动项**

编辑脚本，在 grub.cfg 生成部分添加：

```bash
menuentry "My Custom Kernel" {
    set root='cd0'
    linux /boot/my-kernel root=/dev/sda1 ro
    initrd /boot/my-initrd
}
```

后续如果要加载自己的 kernel/initrd，可直接在 `grub.cfg` 中添加 `multiboot` / `linux` / `initrd` 条目。

如有其他报错，欢迎贴出完整输出继续排查。祝开发愉快！