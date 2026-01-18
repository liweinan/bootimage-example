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

后续如果要加载自己的 kernel/initrd，可直接在 `grub.cfg` 中添加 `multiboot` / `linux` / `initrd` 条目。

如有其他报错，欢迎贴出完整输出继续排查。祝开发愉快！