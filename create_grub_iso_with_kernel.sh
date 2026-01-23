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

# Debian 镜像源（可以根据需要修改）
DEBIAN_MIRROR="https://mirrors.kernel.org/debian"
DEBIAN_VERSION="bookworm"  # 可以根据需要修改为 stable, testing 等
ARCH="amd64"

# 内核文件下载 URL（使用 Debian 安装器的内核）
KERNEL_URL="${DEBIAN_MIRROR}/dists/${DEBIAN_VERSION}/main/installer-${ARCH}/current/images/netboot/debian-installer/${ARCH}/linux"
INITRD_URL="${DEBIAN_MIRROR}/dists/${DEBIAN_VERSION}/main/installer-${ARCH}/current/images/netboot/debian-installer/${ARCH}/initrd.gz"

# 临时文件
KERNEL_TMP="vmlinuz.tmp"
INITRD_TMP="initrd.gz.tmp"

echo -e "${GREEN}=== GRUB ISO 生成脚本 ===${NC}"
echo ""

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

# 清理旧文件
echo -e "${YELLOW}清理旧文件...${NC}"
rm -rf "${WORK_DIR}"
rm -f "${ISO_NAME}" "${KERNEL_TMP}" "${INITRD_TMP}"
echo -e "${GREEN}✓ 清理完成${NC}"
echo ""

# 创建目录结构
echo -e "${YELLOW}创建目录结构...${NC}"
mkdir -p "${GRUB_DIR}"
echo -e "${GREEN}✓ 目录结构创建完成${NC}"
echo ""

# 下载内核文件
echo -e "${YELLOW}下载 Linux 内核文件...${NC}"
echo "内核 URL: ${KERNEL_URL}"
if wget --progress=bar:force -O "${KERNEL_TMP}" "${KERNEL_URL}" 2>&1 | grep -q "200 OK\|saved"; then
    mv "${KERNEL_TMP}" "${KERNEL_DIR}/vmlinuz"
    echo -e "${GREEN}✓ 内核文件下载完成: ${KERNEL_DIR}/vmlinuz${NC}"
else
    echo -e "${RED}错误: 内核文件下载失败${NC}"
    rm -f "${KERNEL_TMP}"
    exit 1
fi
echo ""

# 下载 initrd 文件
echo -e "${YELLOW}下载 initrd 文件...${NC}"
echo "initrd URL: ${INITRD_URL}"
if wget --progress=bar:force -O "${INITRD_TMP}" "${INITRD_URL}" 2>&1 | grep -q "200 OK\|saved"; then
    mv "${INITRD_TMP}" "${KERNEL_DIR}/initrd.img"
    echo -e "${GREEN}✓ initrd 文件下载完成: ${KERNEL_DIR}/initrd.img${NC}"
else
    echo -e "${YELLOW}警告: initrd 文件下载失败，将创建不包含 initrd 的配置${NC}"
    rm -f "${INITRD_TMP}"
    HAS_INITRD=false
fi
echo ""

# 创建 grub.cfg
echo -e "${YELLOW}创建 grub.cfg 配置文件...${NC}"
cat > "${GRUB_DIR}/grub.cfg" << 'GRUB_EOF'
set timeout=5
set default=0

# 设置 ISO 根设备
set root='cd0'

menuentry "Linux Kernel (Debian Installer)" {
    set root='cd0'
    linux /boot/vmlinuz root=/dev/ram0 rw console=ttyS0,115200
    initrd /boot/initrd.img
}

menuentry "Linux Kernel (No Initrd)" {
    set root='cd0'
    linux /boot/vmlinuz root=/dev/ram0 rw console=ttyS0,115200
}

menuentry "GRUB2 Shell" {
    echo "Welcome to GRUB2 Shell!"
    echo ""
    echo "Available commands:"
    echo "  ls          - List files"
    echo "  cat         - Display file contents"
    echo "  set         - Set environment variables"
    echo "  insmod      - Load module"
    echo "  multiboot   - Load multiboot kernel"
    echo ""
    echo "Type 'exit' to return to menu"
}
GRUB_EOF

# 如果没有 initrd，移除包含 initrd 的菜单项
if [ "${HAS_INITRD:-true}" = "false" ]; then
    sed -i '/menuentry "Linux Kernel (Debian Installer)"/,/^}$/d' "${GRUB_DIR}/grub.cfg"
    echo -e "${YELLOW}已移除需要 initrd 的菜单项${NC}"
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
echo -e "${YELLOW}qemu-system-x86_64 -cdrom ${ISO_NAME} -boot d -m 512 -serial stdio${NC}"
echo ""
echo "参数说明:"
echo "  -cdrom ${ISO_NAME}  : 指定 ISO 文件"
echo "  -boot d            : 从 CD-ROM 启动"
echo "  -m 512             : 分配 512MB 内存"
echo "  -serial stdio      : 将串口输出到终端（可以看到内核启动日志）"
echo ""
echo "可选参数:"
echo "  -netdev user,id=net0 -device e1000,netdev=net0  : 启用网络支持"
echo "  -vga std            : 使用标准 VGA 显示"
echo ""
