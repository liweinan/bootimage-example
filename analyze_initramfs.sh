#!/bin/bash
# analyze_initramfs.sh
# 分析 initramfs 内容，查找 BusyBox 启动配置

set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Initramfs 内容分析工具 ===${NC}"
echo ""

# 查找 initrd.img 文件
INITRD_FILE=""
CACHE_DIR=".grub_iso_cache"
ISO_DIR="iso/boot"

# 创建临时目录（需要先创建才能使用）
TMP_DIR=$(mktemp -d)
trap "rm -rf ${TMP_DIR}" EXIT
mkdir -p "${TMP_DIR}"

# 支持从命令行参数指定文件
if [ -n "$1" ]; then
    if [ -f "$1" ]; then
        INITRD_FILE="$1"
        echo -e "${YELLOW}使用指定的文件: ${INITRD_FILE}${NC}"
    else
        echo -e "${RED}错误: 指定的文件不存在: $1${NC}"
        exit 1
    fi
else
    # 支持从 ISO 文件中提取
    ISO_FILE=""
    for iso in grub-linux.iso *.iso; do
        if [ -f "$iso" ]; then
            ISO_FILE="$iso"
            break
        fi
    done

    # 优先级：1. 当前目录的 *.img 文件 2. 缓存目录 3. ISO 目录 4. 当前目录的 initrd.img 5. 从 ISO 提取
    # 首先查找当前目录的 *.img 文件（如 initrd-alpine-v3.19.img）
    CURRENT_IMG=$(ls *.img 2>/dev/null | head -1)
    if [ -n "${CURRENT_IMG}" ] && [ -f "${CURRENT_IMG}" ]; then
        INITRD_FILE="${CURRENT_IMG}"
        echo -e "${YELLOW}使用当前目录中的 img 文件: ${INITRD_FILE}${NC}"
    elif [ -f "${CACHE_DIR}/initrd-alpine-v3.19.img" ]; then
        INITRD_FILE="${CACHE_DIR}/initrd-alpine-v3.19.img"
        echo -e "${YELLOW}使用缓存目录中的 initrd: ${INITRD_FILE}${NC}"
    elif [ -f "${ISO_DIR}/initrd.img" ]; then
        INITRD_FILE="${ISO_DIR}/initrd.img"
        echo -e "${YELLOW}使用 ISO 目录中的 initrd: ${INITRD_FILE}${NC}"
    elif [ -f "initrd.img" ]; then
        INITRD_FILE="initrd.img"
        echo -e "${YELLOW}使用当前目录中的 initrd: ${INITRD_FILE}${NC}"
    elif [ -n "${ISO_FILE}" ]; then
        echo -e "${YELLOW}从 ISO 文件中提取 initrd.img...${NC}"
        # 尝试使用 7z 提取（最通用）
        if command -v 7z &> /dev/null; then
            7z e -o"${TMP_DIR}" "${ISO_FILE}" "boot/initrd.img" 2>/dev/null && \
            INITRD_FILE="${TMP_DIR}/initrd.img" && \
            echo -e "${GREEN}✓ 从 ISO 提取成功${NC}" || {
                echo -e "${YELLOW}尝试其他方法...${NC}"
                # 尝试使用 isoinfo
                if command -v isoinfo &> /dev/null; then
                    isoinfo -i "${ISO_FILE}" -x "/BOOT/INITRD.IMG;1" > "${TMP_DIR}/initrd.img" 2>/dev/null || \
                    isoinfo -i "${ISO_FILE}" -x "/boot/initrd.img" > "${TMP_DIR}/initrd.img" 2>/dev/null
                    if [ -f "${TMP_DIR}/initrd.img" ] && [ -s "${TMP_DIR}/initrd.img" ]; then
                        INITRD_FILE="${TMP_DIR}/initrd.img"
                        echo -e "${GREEN}✓ 从 ISO 提取成功${NC}"
                    fi
                fi
            }
        fi
        
        if [ -z "${INITRD_FILE}" ] || [ ! -f "${INITRD_FILE}" ]; then
            echo -e "${RED}错误: 无法从 ISO 提取 initrd.img${NC}"
            echo "请手动提取或提供 initrd.img 文件"
            echo "使用方法: $0 [initrd.img文件路径]"
            exit 1
        fi
    else
        echo -e "${RED}错误: 未找到 initrd.img 文件${NC}"
        echo "使用方法: $0 [initrd.img文件路径]"
        echo "或者确保已运行 create_grub_iso_with_kernel.sh 脚本"
        exit 1
    fi
fi

echo ""

echo -e "${YELLOW}解压 initramfs 到临时目录: ${TMP_DIR}${NC}"

# 检查文件类型
FILE_TYPE=$(file "${INITRD_FILE}" | cut -d: -f2)

if echo "${FILE_TYPE}" | grep -q "gzip"; then
    echo -e "${BLUE}检测到 gzip 压缩${NC}"
    # 解压 gzip
    gunzip -c "${INITRD_FILE}" > "${TMP_DIR}/initramfs.cpio" 2>/dev/null || {
        # 如果不是标准的 gzip，尝试其他方法
        echo -e "${YELLOW}尝试其他解压方法...${NC}"
        zcat "${INITRD_FILE}" > "${TMP_DIR}/initramfs.cpio" 2>/dev/null || {
            echo -e "${RED}错误: 无法解压 gzip 文件${NC}"
            exit 1
        }
    }
elif echo "${FILE_TYPE}" | grep -q "cpio"; then
    echo -e "${BLUE}检测到 cpio 归档${NC}"
    cp "${INITRD_FILE}" "${TMP_DIR}/initramfs.cpio"
else
    echo -e "${YELLOW}未知格式，尝试直接解压...${NC}"
    # 尝试解压
    gunzip -c "${INITRD_FILE}" > "${TMP_DIR}/initramfs.cpio" 2>/dev/null || \
    zcat "${INITRD_FILE}" > "${TMP_DIR}/initramfs.cpio" 2>/dev/null || \
    cp "${INITRD_FILE}" "${TMP_DIR}/initramfs.cpio"
fi

# 提取 cpio 归档
EXTRACT_DIR="${TMP_DIR}/extract"
mkdir -p "${EXTRACT_DIR}"
cd "${EXTRACT_DIR}"
cpio -id < "${TMP_DIR}/initramfs.cpio" 2>/dev/null || {
    echo -e "${YELLOW}尝试使用 -F 选项...${NC}"
    cpio -id -F "${TMP_DIR}/initramfs.cpio" 2>/dev/null || {
        echo -e "${RED}错误: 无法提取 cpio 归档${NC}"
        exit 1
    }
}

echo -e "${GREEN}✓ 解压完成${NC}"
echo ""

# 分析内容
echo -e "${GREEN}=== Initramfs 内容分析 ===${NC}"
echo ""

# 1. 显示目录结构
echo -e "${YELLOW}1. 目录结构:${NC}"
find . -type d | head -20
echo ""

# 2. 查找 /init 文件
echo -e "${YELLOW}2. /init 文件分析:${NC}"
if [ -f "./init" ]; then
    echo -e "${GREEN}找到 /init 文件${NC}"
    ls -lh ./init
    echo ""
    echo -e "${BLUE}文件类型:${NC}"
    file ./init
    echo ""
    echo -e "${BLUE}前 50 行内容:${NC}"
    head -50 ./init
    echo ""
else
    echo -e "${RED}未找到 /init 文件${NC}"
fi
echo ""

# 3. 查找 BusyBox
echo -e "${YELLOW}3. BusyBox 相关文件:${NC}"
find . -name "*busybox*" -o -name "busybox" 2>/dev/null | while read file; do
    if [ -f "$file" ]; then
        echo -e "${GREEN}找到: $file${NC}"
        ls -lh "$file"
        file "$file"
        echo ""
    fi
done

# 查找 busybox 符号链接
echo -e "${BLUE}BusyBox 符号链接:${NC}"
find . -type l -exec ls -l {} \; 2>/dev/null | grep -i busybox || echo "未找到 busybox 符号链接"
echo ""

# 4. 查找 /sbin/init
echo -e "${YELLOW}4. /sbin/init 分析:${NC}"
if [ -f "./sbin/init" ] || [ -L "./sbin/init" ]; then
    echo -e "${GREEN}找到 /sbin/init${NC}"
    ls -lh ./sbin/init
    if [ -L "./sbin/init" ]; then
        echo -e "${BLUE}符号链接指向:${NC}"
        readlink ./sbin/init
    fi
    file ./sbin/init
    echo ""
else
    echo -e "${RED}未找到 /sbin/init${NC}"
fi
echo ""

# 5. 查找配置文件
echo -e "${YELLOW}5. 启动配置文件:${NC}"
for config in "./etc/inittab" "./etc/init.d/rcS" "./etc/rc.d" "./etc/init.d"; do
    if [ -e "$config" ]; then
        echo -e "${GREEN}找到: $config${NC}"
        if [ -f "$config" ]; then
            ls -lh "$config"
            echo -e "${BLUE}内容:${NC}"
            cat "$config"
            echo ""
        elif [ -d "$config" ]; then
            ls -la "$config"
            echo ""
        fi
    fi
done
echo ""

# 6. 查找 /bin/sh
echo -e "${YELLOW}6. /bin/sh 分析:${NC}"
if [ -f "./bin/sh" ] || [ -L "./bin/sh" ]; then
    echo -e "${GREEN}找到 /bin/sh${NC}"
    ls -lh ./bin/sh
    if [ -L "./bin/sh" ]; then
        echo -e "${BLUE}符号链接指向:${NC}"
        readlink ./bin/sh
    fi
    file ./bin/sh
    echo ""
else
    echo -e "${RED}未找到 /bin/sh${NC}"
fi
echo ""

# 7. 显示所有可执行文件
echo -e "${YELLOW}7. 主要可执行文件:${NC}"
find ./bin ./sbin ./usr/bin ./usr/sbin -type f -o -type l 2>/dev/null | head -30
echo ""

# 8. 显示文件系统结构
echo -e "${YELLOW}8. 完整文件系统结构:${NC}"
tree -L 3 . 2>/dev/null || find . -maxdepth 3 -type d | sort
echo ""

# 9. 查找启动脚本
echo -e "${YELLOW}9. 启动脚本查找:${NC}"
find . -name "*init*" -o -name "*rc*" 2>/dev/null | grep -E "(init|rc)" | head -20
echo ""

echo -e "${GREEN}=== 分析完成 ===${NC}"
echo ""
echo -e "${YELLOW}临时目录: ${TMP_DIR}${NC}"
echo "分析完成后会自动清理"
