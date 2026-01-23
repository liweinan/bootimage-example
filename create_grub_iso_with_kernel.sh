#!/bin/bash
# create_grub_iso_with_kernel.sh
# 自动下载 Linux 内核文件并生成包含完整启动配置的 GRUB ISO

set -e  # 遇到错误立即退出

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 配置变量
ISO_NAME="grub-linux.iso"
WORK_DIR="iso"
BOOT_DIR="${WORK_DIR}/boot"
GRUB_DIR="${BOOT_DIR}/grub"
KERNEL_DIR="${BOOT_DIR}"

# Alpine Linux 镜像源（轻量级，启动后直接进入 shell）
ALPINE_MIRROR="https://dl-cdn.alpinelinux.org/alpine"
ALPINE_VERSION="v3.19"  # 可以根据需要修改版本
ARCH="x86_64"

# 内核文件下载 URL（使用 Alpine Linux 标准内核，启动后进入 shell）
KERNEL_URL="${ALPINE_MIRROR}/${ALPINE_VERSION}/releases/${ARCH}/alpine-standard-${ALPINE_VERSION#v}-${ARCH}.iso"
# 注意：Alpine ISO 包含内核，我们需要提取它，或者直接下载内核文件
# 更简单的方式：使用 Alpine 的 netboot 内核
KERNEL_URL="https://dl-cdn.alpinelinux.org/alpine/${ALPINE_VERSION}/releases/${ARCH}/netboot/vmlinuz-virt"
INITRD_URL="https://dl-cdn.alpinelinux.org/alpine/${ALPINE_VERSION}/releases/${ARCH}/netboot/initramfs-virt"

# 临时文件
KERNEL_TMP="vmlinuz.tmp"
INITRD_TMP="initrd.gz.tmp"

# 本地缓存目录（用于保存已下载的文件）
CACHE_DIR=".grub_iso_cache"

echo -e "${GREEN}=== GRUB ISO 生成脚本 ===${NC}"
echo ""

# 检查是否使用本地内核文件
USE_LOCAL_KERNEL=false
if [ "$1" = "--local" ] || [ "$1" = "-l" ]; then
    USE_LOCAL_KERNEL=true
    echo -e "${YELLOW}使用本地系统内核文件模式${NC}"
    if [ ! -f /boot/vmlinuz-$(uname -r) ]; then
        echo -e "${RED}错误: 未找到本地内核文件 /boot/vmlinuz-$(uname -r)${NC}"
        exit 1
    fi
    echo ""
fi

# 检查依赖工具
echo -e "${YELLOW}检查依赖工具...${NC}"
for cmd in grub-mkrescue wget; do
    if ! command -v $cmd &> /dev/null; then
        echo -e "${RED}错误: 未找到 $cmd，请先安装${NC}"
        echo "Ubuntu/Debian: sudo apt install grub-pc-bin wget"
        exit 1
    fi
done
echo -e "${GREEN}✓ 依赖工具检查通过${NC}"
echo ""

# 清理旧文件（保留缓存目录）
echo -e "${YELLOW}清理旧文件...${NC}"
rm -rf "${WORK_DIR}"
rm -f "${ISO_NAME}" "${KERNEL_TMP}" "${INITRD_TMP}"
echo -e "${GREEN}✓ 清理完成${NC}"
echo ""

# 创建缓存目录（如果不存在）
mkdir -p "${CACHE_DIR}"

# 创建目录结构
echo -e "${YELLOW}创建目录结构...${NC}"
mkdir -p "${GRUB_DIR}"
echo -e "${GREEN}✓ 目录结构创建完成${NC}"
echo ""

# 下载或复制内核文件
if [ "$USE_LOCAL_KERNEL" = "true" ]; then
    echo -e "${YELLOW}复制本地内核文件...${NC}"
    KERNEL_VERSION=$(uname -r)
    cp /boot/vmlinuz-${KERNEL_VERSION} "${KERNEL_DIR}/vmlinuz"
    echo -e "${GREEN}✓ 内核文件复制完成: ${KERNEL_DIR}/vmlinuz${NC}"
    echo ""
    
    # 尝试复制 initrd
    if [ -f /boot/initrd.img-${KERNEL_VERSION} ]; then
        cp /boot/initrd.img-${KERNEL_VERSION} "${KERNEL_DIR}/initrd.img"
        echo -e "${GREEN}✓ initrd 文件复制完成: ${KERNEL_DIR}/initrd.img${NC}"
        HAS_INITRD=true
    elif [ -f /boot/initramfs-${KERNEL_VERSION}.img ]; then
        cp /boot/initramfs-${KERNEL_VERSION}.img "${KERNEL_DIR}/initrd.img"
        echo -e "${GREEN}✓ initrd 文件复制完成: ${KERNEL_DIR}/initrd.img${NC}"
        HAS_INITRD=true
    else
        echo -e "${RED}错误: 未找到本地 initrd 文件${NC}"
        echo "请确保系统有 initrd 或 initramfs 文件"
        exit 1
    fi
    echo ""
else
    # 下载 Alpine Linux 内核文件
    CACHED_KERNEL="${CACHE_DIR}/vmlinuz-alpine-${ALPINE_VERSION}"
    CACHED_INITRD="${CACHE_DIR}/initrd-alpine-${ALPINE_VERSION}.img"
    
    # 检查本地缓存
    if [ -f "${CACHED_KERNEL}" ]; then
        echo -e "${YELLOW}使用本地缓存的内核文件...${NC}"
        cp "${CACHED_KERNEL}" "${KERNEL_DIR}/vmlinuz"
        echo -e "${GREEN}✓ 内核文件复制完成: ${KERNEL_DIR}/vmlinuz${NC}"
    else
        echo -e "${YELLOW}下载 Alpine Linux 内核文件...${NC}"
        echo "内核 URL: ${KERNEL_URL}"
        if wget --progress=bar:force -O "${KERNEL_TMP}" "${KERNEL_URL}" 2>&1 | grep -q "200 OK\|saved"; then
            mv "${KERNEL_TMP}" "${KERNEL_DIR}/vmlinuz"
            # 保存到缓存
            cp "${KERNEL_DIR}/vmlinuz" "${CACHED_KERNEL}"
            echo -e "${GREEN}✓ 内核文件下载完成: ${KERNEL_DIR}/vmlinuz${NC}"
        else
            echo -e "${RED}错误: 内核文件下载失败${NC}"
            rm -f "${KERNEL_TMP}"
            exit 1
        fi
    fi
    echo ""
    
    # 下载 initrd 文件
    if [ -f "${CACHED_INITRD}" ]; then
        echo -e "${YELLOW}使用本地缓存的 initrd 文件...${NC}"
        cp "${CACHED_INITRD}" "${KERNEL_DIR}/initrd.img"
        echo -e "${GREEN}✓ initrd 文件复制完成: ${KERNEL_DIR}/initrd.img${NC}"
        HAS_INITRD=true
    else
        echo -e "${YELLOW}下载 initrd 文件...${NC}"
        echo "initrd URL: ${INITRD_URL}"
        if wget --progress=bar:force -O "${INITRD_TMP}" "${INITRD_URL}" 2>&1 | grep -q "200 OK\|saved"; then
            mv "${INITRD_TMP}" "${KERNEL_DIR}/initrd.img"
            # 保存到缓存
            cp "${KERNEL_DIR}/initrd.img" "${CACHED_INITRD}"
            echo -e "${GREEN}✓ initrd 文件下载完成: ${KERNEL_DIR}/initrd.img${NC}"
            HAS_INITRD=true
        else
            echo -e "${RED}错误: initrd 文件下载失败${NC}"
            rm -f "${INITRD_TMP}"
            exit 1
        fi
    fi
    echo ""
fi

# 创建 grub.cfg
echo -e "${YELLOW}创建 grub.cfg 配置文件...${NC}"
cat > "${GRUB_DIR}/grub.cfg" << 'GRUB_EOF'
set timeout=5
set default=0

# 加载必要的模块以支持 ISO 文件系统
insmod iso9660
insmod part_msdos
insmod part_gpt
insmod loopback

# 自动探测并设置根设备（通过查找 grub.cfg 文件）
# 这会自动找到包含 /boot/grub/grub.cfg 的设备
search --no-floppy --set=root --file /boot/grub/grub.cfg

menuentry "Linux - Boot to Shell" {
    # 重新探测设备（确保在菜单项中也能访问）
    search --no-floppy --set=root --file /boot/grub/grub.cfg
    linux /boot/vmlinuz root=/dev/ram0 rw console=ttyS0,115200n8 console=tty0 alpine_repo=https://dl-cdn.alpinelinux.org/alpine/v3.19/main modules=loop,squashfs,sd-mod,usb-storage
    initrd /boot/initrd.img
}

menuentry "Linux - Boot to Shell (Verbose)" {
    # 重新探测设备（确保在菜单项中也能访问）
    search --no-floppy --set=root --file /boot/grub/grub.cfg
    linux /boot/vmlinuz root=/dev/ram0 rw console=ttyS0,115200n8 console=tty0 alpine_repo=https://dl-cdn.alpinelinux.org/alpine/v3.19/main modules=loop,squashfs,sd-mod,usb-storage
    initrd /boot/initrd.img
}

menuentry "Debug: List Files" {
    search --no-floppy --set=root --file /boot/grub/grub.cfg
    echo "Current root: $root"
    echo ""
    echo "Listing devices:"
    ls
    echo ""
    echo "Trying to list root directory:"
    ls /
    echo ""
    echo "Trying to list /boot directory:"
    ls /boot/
    echo ""
    echo "Trying to list /boot/grub directory:"
    ls /boot/grub/
    echo ""
    echo "Testing file access:"
    ls -l /boot/vmlinuz
    ls -l /boot/initrd.img
    echo ""
    echo "Press any key to return to menu..."
    read
}

GRUB_EOF

# 检查是否有 initrd，如果没有则报错
if [ "${HAS_INITRD:-true}" = "false" ]; then
    echo -e "${RED}错误: 未找到 initrd 文件，无法创建启动配置${NC}"
    exit 1
fi

echo -e "${GREEN}✓ grub.cfg 创建完成${NC}"
echo ""

# 显示文件结构
echo -e "${YELLOW}文件结构:${NC}"
tree -L 3 "${WORK_DIR}" 2>/dev/null || find "${WORK_DIR}" -type f | sed 's|[^/]*/| |g'
echo ""

# 生成 ISO
echo -e "${YELLOW}生成 ISO 文件...${NC}"
if grub-mkrescue -o "${ISO_NAME}" "${WORK_DIR}" 2>&1; then
    echo ""
    echo -e "${GREEN}✓ ISO 文件生成成功: ${ISO_NAME}${NC}"
    
    # 显示文件大小
    ISO_SIZE=$(du -h "${ISO_NAME}" | cut -f1)
    echo -e "${GREEN}文件大小: ${ISO_SIZE}${NC}"
else
    echo -e "${RED}错误: ISO 文件生成失败${NC}"
    exit 1
fi
echo ""

# 显示使用说明
echo -e "${GREEN}=== 完成 ===${NC}"
echo ""
echo "使用以下命令在 QEMU 中启动:"
echo -e "${YELLOW}qemu-system-x86_64 -cdrom ${ISO_NAME} -boot d -m 1024 -serial stdio${NC}"
echo ""
echo "参数说明:"
echo "  -cdrom ${ISO_NAME}  : 指定 ISO 文件"
echo "  -boot d            : 从 CD-ROM 启动"
echo "  -m 1024            : 分配 1024MB 内存（Alpine 建议至少 512MB，推荐 1GB）"
echo "  -serial stdio      : 将串口输出到终端（可以看到内核启动日志）"
echo ""
echo "重要提示:"
echo "  - 必须使用 -serial stdio 才能看到内核启动日志和 shell 输出"
echo "  - 如果黑屏，检查是否使用了 -serial stdio 参数"
echo "  - 内核输出会显示在终端，而不是 QEMU 窗口"
echo ""
echo "可选参数:"
echo "  -netdev user,id=net0 -device e1000,netdev=net0  : 启用网络支持"
echo "  -vga std            : 使用标准 VGA 显示"
echo ""
echo "使用说明:"
echo "  - 默认使用 Alpine Linux 内核（轻量级，启动后进入 shell）"
echo "  - 使用 --local 或 -l 参数可使用本地系统内核:"
echo "    ${YELLOW}./create_grub_iso_with_kernel.sh --local${NC}"
echo ""
