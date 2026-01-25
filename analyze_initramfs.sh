#!/bin/bash
# analyze_initramfs.sh
# 分析 initramfs 内容，查找 BusyBox 启动配置

# 确保使用 bash 运行
if [ -z "$BASH_VERSION" ]; then
    echo "错误: 此脚本需要使用 bash 运行" >&2
    echo "请使用: bash $0 或 ./$0" >&2
    exit 1
fi

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

printf "%b" "${GREEN}=== Initramfs 内容分析工具 ===${NC}\n"
printf "\n"

# 查找 initrd.img 文件
INITRD_FILE=""
CACHE_DIR=".grub_iso_cache"
ISO_DIR="iso/boot"

# 创建临时目录
TMP_DIR=$(mktemp -d)
trap "rm -rf ${TMP_DIR}" EXIT
mkdir -p "${TMP_DIR}"
EXTRACT_DIR="${TMP_DIR}/extract"
mkdir -p "${EXTRACT_DIR}"

# 支持从命令行参数指定文件
if [ -n "$1" ]; then
    if [ -f "$1" ]; then
        INITRD_FILE="$1"
        printf "%b" "${YELLOW}使用指定的文件: ${INITRD_FILE}${NC}\n"
    else
        printf "%b" "${RED}错误: 指定的文件不存在: $1${NC}\n"
        exit 1
    fi
else
    # 优先级：1. 当前目录的 *.img 文件 2. 缓存目录 3. ISO 目录 4. 当前目录的 initrd.img 5. 从 ISO 提取
    CURRENT_IMG=$(ls *.img 2>/dev/null | head -1)
    if [ -n "${CURRENT_IMG}" ] && [ -f "${CURRENT_IMG}" ]; then
        INITRD_FILE="${CURRENT_IMG}"
        printf "%b" "${YELLOW}使用当前目录中的 img 文件: ${INITRD_FILE}${NC}\n"
    elif [ -f "${CACHE_DIR}/initrd-alpine-v3.19.img" ]; then
        INITRD_FILE="${CACHE_DIR}/initrd-alpine-v3.19.img"
        printf "%b" "${YELLOW}使用缓存目录中的 initrd: ${INITRD_FILE}${NC}\n"
    elif [ -f "${ISO_DIR}/initrd.img" ]; then
        INITRD_FILE="${ISO_DIR}/initrd.img"
        printf "%b" "${YELLOW}使用 ISO 目录中的 initrd: ${INITRD_FILE}${NC}\n"
    elif [ -f "initrd.img" ]; then
        INITRD_FILE="initrd.img"
        printf "%b" "${YELLOW}使用当前目录中的 initrd: ${INITRD_FILE}${NC}\n"
    else
        printf "%b" "${RED}错误: 未找到 initrd.img 文件${NC}\n"
        echo "使用方法: $0 [initrd.img文件路径]"
        exit 1
    fi
fi

printf "\n"
printf "%b" "${YELLOW}解压 initramfs 到临时目录: ${TMP_DIR}${NC}\n"

# 步骤 1: 解压 gzip
printf "%b" "${BLUE}步骤 1: 解压 gzip...${NC}\n"
if ! gunzip -c "${INITRD_FILE}" > "${TMP_DIR}/initramfs.cpio" 2>/dev/null; then
    printf "%b" "${RED}错误: 无法解压 gzip 文件${NC}\n"
    exit 1
fi
ls -lh "${TMP_DIR}/initramfs.cpio"
echo ""

# 步骤 2: 提取 cpio
printf "%b" "${BLUE}步骤 2: 提取 cpio 归档...${NC}\n"
cd "${EXTRACT_DIR}"
if ! cpio -id < "${TMP_DIR}/initramfs.cpio" >/dev/null 2>&1; then
    printf "%b" "${RED}错误: 无法提取 cpio 归档${NC}\n"
    exit 1
fi
printf "%b" "${GREEN}解压成功，文件数: $(find . | wc -l)${NC}\n"
printf "\n"

# 分析内容
printf "%b" "${GREEN}=== Initramfs 内容分析 ===${NC}\n"
printf "\n"

# 步骤 3: /init 文件
printf "%b" "${YELLOW}步骤 3: /init 文件分析${NC}\n"
if [ -f "./init" ]; then
    printf "%b" "${GREEN}找到 /init 文件${NC}\n"
    ls -lh ./init
    file ./init
    printf "\n"
    printf "%b" "${BLUE}前 20 行内容:${NC}\n"
    head -20 ./init
else
    printf "%b" "${RED}未找到 /init 文件${NC}\n"
fi
printf "\n"

# 步骤 4: BusyBox
printf "%b" "${YELLOW}步骤 4: BusyBox 分析${NC}\n"
if [ -f "./bin/busybox" ]; then
    printf "%b" "${GREEN}找到 BusyBox${NC}\n"
    ls -lh ./bin/busybox
    file ./bin/busybox
else
    echo "未找到 /bin/busybox"
fi
printf "\n"

# 步骤 5: /bin/sh 符号链接
printf "%b" "${YELLOW}步骤 5: /bin/sh 符号链接${NC}\n"
if [ -L "./bin/sh" ]; then
    printf "%b" "${GREEN}找到 /bin/sh${NC}\n"
    ls -lh ./bin/sh
    printf "%b" "${BLUE}符号链接指向:${NC}\n"
    readlink ./bin/sh
else
    echo "未找到 /bin/sh 符号链接"
fi
printf "\n"

# 步骤 6: /sbin/init
printf "%b" "${YELLOW}步骤 6: /sbin/init 分析${NC}\n"
if [ -e "./sbin/init" ]; then
    printf "%b" "${GREEN}找到 /sbin/init${NC}\n"
    ls -lh ./sbin/init
    if [ -L "./sbin/init" ]; then
        printf "%b" "${BLUE}符号链接指向:${NC}\n"
        readlink ./sbin/init
    fi
    file ./sbin/init
else
    printf "%b" "${RED}未找到 /sbin/init${NC}\n"
fi
printf "\n"

# 步骤 7: 配置文件
printf "%b" "${YELLOW}步骤 7: 启动配置文件${NC}\n"
for config in "./etc/inittab" "./etc/init.d/rcS"; do
    if [ -f "$config" ]; then
        printf "%b" "${GREEN}找到: $config${NC}\n"
        ls -lh "$config"
        printf "%b" "${BLUE}内容（前 20 行）:${NC}\n"
        head -20 "$config"
        echo ""
    fi
done
if [ -d "./etc/init.d" ]; then
    printf "%b" "${GREEN}找到目录: ./etc/init.d${NC}\n"
    ls -la "./etc/init.d" | head -10
    printf "\n"
fi
printf "\n"

# 步骤 8: 主要可执行文件
printf "%b" "${YELLOW}步骤 8: 主要可执行文件（前 15 个）${NC}\n"
find ./bin ./sbin \( -type f -o -type l \) 2>/dev/null | head -15
printf "\n"

# 步骤 9: 基本目录结构
printf "%b" "${YELLOW}步骤 9: 基本目录结构${NC}\n"
ls -la . | head -20
printf "\n"

printf "%b" "${GREEN}=== 分析完成 ===${NC}\n"
printf "\n"
printf "%b" "${YELLOW}临时目录: ${TMP_DIR}${NC}\n"
echo "分析完成后会自动清理"
