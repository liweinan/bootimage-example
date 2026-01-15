#!/bin/bash
# 分析 GRUB 引导扇区，查找 kernel_sector 字段和 core.img 位置
# 支持标准模式和 HYBRID_BOOT 模式

set -e

ISO_FILE="${1:-grub.iso}"
BOOT_SECTOR_FILE="boot_sector.bin"

# 支持相对路径和绝对路径
if [ ! -f "$ISO_FILE" ]; then
    # 尝试在当前目录查找
    if [ -f "./$ISO_FILE" ]; then
        ISO_FILE="./$ISO_FILE"
    # 尝试在常见位置查找
    elif [ -f "../$ISO_FILE" ]; then
        ISO_FILE="../$ISO_FILE"
    else
        echo "错误: 找不到文件 $ISO_FILE"
        echo "用法: $0 [iso文件路径]"
        echo ""
        echo "提示: 脚本会在以下位置查找文件:"
        echo "  - 当前目录: ./$ISO_FILE"
        echo "  - 上级目录: ../$ISO_FILE"
        echo "  - 指定路径: $ISO_FILE"
        exit 1
    fi
fi

echo "=========================================="
echo "分析 GRUB 引导扇区"
echo "=========================================="
echo "ISO 文件: $ISO_FILE"
echo ""

# 提取引导扇区
echo "1. 提取引导扇区（512 字节）"
echo "----------------------------------------"
dd if="$ISO_FILE" of="$BOOT_SECTOR_FILE" bs=512 count=1 2>/dev/null
file "$BOOT_SECTOR_FILE"
echo ""

# 检查引导扇区签名
echo "2. 验证引导扇区签名"
echo "----------------------------------------"
signature=$(od -An -tx2 -j 510 -N 2 "$BOOT_SECTOR_FILE" 2>/dev/null | tr -d ' ')
if [ "$signature" = "aa55" ]; then
    echo "✅ 引导扇区签名正确: 0x$signature"
else
    echo "⚠️  引导扇区签名异常: 0x$signature (期望: 0xaa55)"
fi
echo ""

# 检查标准模式（偏移 0x5c）
echo "3. 检查标准模式 kernel_sector（偏移 0x5c = 92 字节）"
echo "----------------------------------------"
kernel_sector_std=$(od -An -tu4 -j 92 -N 4 "$BOOT_SECTOR_FILE" 2>/dev/null | tr -d ' ')
kernel_sector_std_hex=$(od -An -tx4 -j 92 -N 4 "$BOOT_SECTOR_FILE" 2>/dev/null | tr -d ' ')
echo "kernel_sector (标准模式): $kernel_sector_std (0x$kernel_sector_std_hex)"
echo ""

# 检查 HYBRID_BOOT 模式（偏移 0x1b0）
echo "4. 检查 HYBRID_BOOT 模式 kernel_sector（偏移 0x1b0 = 432 字节）"
echo "----------------------------------------"
kernel_sector_hybrid=$(od -An -tu4 -j 432 -N 4 "$BOOT_SECTOR_FILE" 2>/dev/null | tr -d ' ')
kernel_sector_hybrid_hex=$(od -An -tx4 -j 432 -N 4 "$BOOT_SECTOR_FILE" 2>/dev/null | tr -d ' ')
kernel_sector_hybrid_high=$(od -An -tu4 -j 436 -N 4 "$BOOT_SECTOR_FILE" 2>/dev/null | tr -d ' ')
echo "kernel_sector (HYBRID_BOOT 模式): $kernel_sector_hybrid (0x$kernel_sector_hybrid_hex)"
echo "kernel_sector_high: $kernel_sector_hybrid_high"
echo ""

# 确定使用哪个 kernel_sector
echo "5. 确定 kernel_sector 值"
echo "----------------------------------------"
if [ "$kernel_sector_std" != "0" ] && [ "$kernel_sector_std" -lt 100000 ]; then
    KERNEL_SECTOR=$kernel_sector_std
    MODE="标准模式"
    echo "使用标准模式: kernel_sector = $KERNEL_SECTOR"
elif [ "$kernel_sector_hybrid" != "0" ] && [ "$kernel_sector_hybrid" -lt 100000 ]; then
    KERNEL_SECTOR=$kernel_sector_hybrid
    MODE="HYBRID_BOOT 模式"
    echo "使用 HYBRID_BOOT 模式: kernel_sector = $KERNEL_SECTOR"
else
    echo "⚠️  无法确定有效的 kernel_sector"
    echo "标准模式: $kernel_sector_std"
    echo "HYBRID_BOOT 模式: $kernel_sector_hybrid"
    exit 1
fi
echo ""

# 查看 core.img 的起始位置
echo "6. 查看 core.img 的起始位置（扇区 $KERNEL_SECTOR）"
echo "----------------------------------------"
echo "core.img 起始扇区: $KERNEL_SECTOR (模式: $MODE)"
echo ""

# 提取并查看 core.img 的第一个扇区
echo "7. 提取 core.img 的第一个扇区（diskboot.S）"
echo "----------------------------------------"
dd if="$ISO_FILE" bs=512 skip=$KERNEL_SECTOR count=1 2>/dev/null > core_img_first_sector.bin
file core_img_first_sector.bin
echo ""

# 查看前 64 字节（diskboot.S 代码）
echo "前 64 字节（diskboot.S 代码）:"
hexdump -C core_img_first_sector.bin | head -5
echo ""

# 查看末尾 16 字节（可能包含块列表）
echo "末尾 16 字节（可能包含块列表）:"
hexdump -C core_img_first_sector.bin | tail -2
echo ""

# 分析 core.img 的完整大小
echo "8. 分析 core.img 的完整大小"
echo "----------------------------------------"

# 方法1: 从块列表计算总大小
BLOCKLIST_START=0x1F4  # 500 字节
BLOCKLIST_ENTRY_SIZE=12

TOTAL_SECTORS=0
ENTRY_COUNT=0

# 读取块列表条目
for i in 0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19; do
    OFFSET=$((BLOCKLIST_START - (i * BLOCKLIST_ENTRY_SIZE)))
    if [ $OFFSET -lt 0 ]; then
        break
    fi
    
    # 读取块列表条目（12 字节）
    ENTRY_DATA=$(dd if=core_img_first_sector.bin bs=1 skip=$OFFSET count=12 2>/dev/null | od -An -tu1 -v)
    
    # 解析字段（小端序）
    # start 低 32 位 (0-3), start 高 32 位 (4-7), len (8-9), segment (10-11)
    START_LOW_B0=$(echo $ENTRY_DATA | awk '{print $1}')
    START_LOW_B1=$(echo $ENTRY_DATA | awk '{print $2}')
    START_LOW_B2=$(echo $ENTRY_DATA | awk '{print $3}')
    START_LOW_B3=$(echo $ENTRY_DATA | awk '{print $4}')
    START_LOW=$((START_LOW_B0 + (START_LOW_B1 * 256) + (START_LOW_B2 * 65536) + (START_LOW_B3 * 16777216)))
    
    LEN_B0=$(echo $ENTRY_DATA | awk '{print $9}')
    LEN_B1=$(echo $ENTRY_DATA | awk '{print $10}')
    LEN=$((LEN_B0 + (LEN_B1 * 256)))
    
    if [ "$LEN" -eq 0 ]; then
        echo "  条目 $i: len=0 (结束标记)"
        break
    fi
    
    TOTAL_SECTORS=$((TOTAL_SECTORS + LEN))
    ENTRY_COUNT=$((ENTRY_COUNT + 1))
    
    SEG_B0=$(echo $ENTRY_DATA | awk '{print $11}')
    SEG_B1=$(echo $ENTRY_DATA | awk '{print $12}')
    SEG=$((SEG_B0 + (SEG_B1 * 256)))
    
    echo "  条目 $i: start=$START_LOW, len=$LEN 扇区, segment=0x$(printf '%04x' $SEG)"
done

if [ "$TOTAL_SECTORS" -gt 0 ]; then
    TOTAL_BYTES=$((TOTAL_SECTORS * 512))
    TOTAL_KB=$((TOTAL_BYTES * 10 / 1024))
    TOTAL_KB_INT=$((TOTAL_KB / 10))
    TOTAL_KB_FRAC=$((TOTAL_KB % 10))
    TOTAL_MB=$((TOTAL_BYTES * 100 / 1048576))
    TOTAL_MB_INT=$((TOTAL_MB / 100))
    TOTAL_MB_FRAC=$((TOTAL_MB % 100))
    
    echo ""
    echo "core.img 完整大小:"
    echo "  - 扇区数: $TOTAL_SECTORS"
    echo "  - 字节数: $TOTAL_BYTES 字节"
    echo "  - 大小: ${TOTAL_KB_INT}.${TOTAL_KB_FRAC} KB (${TOTAL_MB_INT}.${TOTAL_MB_FRAC} MB)"
    echo "  - 块列表条目数: $ENTRY_COUNT"
    
    # 提取完整的 core.img
    echo ""
    echo "9. 提取完整的 core.img"
    echo "----------------------------------------"
    dd if="$ISO_FILE" bs=512 skip=$KERNEL_SECTOR count=$TOTAL_SECTORS 2>/dev/null > core_img_full.bin
    FULL_SIZE=$(stat -f%z core_img_full.bin 2>/dev/null || stat -c%s core_img_full.bin 2>/dev/null)
    FULL_KB=$((FULL_SIZE * 10 / 1024))
    FULL_KB_INT=$((FULL_KB / 10))
    FULL_KB_FRAC=$((FULL_KB % 10))
    echo "已提取完整的 core.img: core_img_full.bin"
    echo "文件大小: $FULL_SIZE 字节 (${FULL_KB_INT}.${FULL_KB_FRAC} KB)"
    echo ""
else
    echo "⚠️  无法从块列表确定 core.img 大小"
    echo "  尝试提取较大的区域进行分析..."
    # 提取前 128 个扇区作为样本
    dd if="$ISO_FILE" bs=512 skip=$KERNEL_SECTOR count=128 2>/dev/null > core_img_sample.bin
    SAMPLE_SIZE=$(stat -f%z core_img_sample.bin 2>/dev/null || stat -c%s core_img_sample.bin 2>/dev/null)
    echo "  已提取样本: core_img_sample.bin ($SAMPLE_SIZE 字节)"
    echo ""
fi

# 查找 GRUB 特征字符串
echo "10. 查找 GRUB 特征字符串"
echo "----------------------------------------"
if strings core_img_first_sector.bin | grep -q "loading\|Geom\|Read\|Error"; then
    echo "✅ 找到 GRUB 特征字符串:"
    strings core_img_first_sector.bin | grep -E "loading|Geom|Read|Error" | head -5
else
    echo "⚠️  未找到典型的 GRUB 特征字符串"
fi
echo ""

# 提取更多 core.img 数据用于压缩检测
echo "11. 提取 core.img 数据（用于压缩检测）"
echo "----------------------------------------"
# 使用完整的 core.img 或样本
if [ -f "core_img_full.bin" ]; then
    CORE_IMG_FILE="core_img_full.bin"
    CORE_SIZE=$(stat -f%z "$CORE_IMG_FILE" 2>/dev/null || stat -c%s "$CORE_IMG_FILE" 2>/dev/null)
    CORE_KB=$((CORE_SIZE * 10 / 1024))
    CORE_KB_INT=$((CORE_KB / 10))
    CORE_KB_FRAC=$((CORE_KB % 10))
    echo "使用完整的 core.img: $CORE_SIZE 字节 (${CORE_KB_INT}.${CORE_KB_FRAC} KB)"
else
    CORE_IMG_FILE="core_img_sample.bin"
    CORE_SIZE=$(stat -f%z "$CORE_IMG_FILE" 2>/dev/null || stat -c%s "$CORE_IMG_FILE" 2>/dev/null)
    CORE_KB=$((CORE_SIZE * 10 / 1024))
    CORE_KB_INT=$((CORE_KB / 10))
    CORE_KB_FRAC=$((CORE_KB % 10))
    echo "使用 core.img 样本: $CORE_SIZE 字节 (${CORE_KB_INT}.${CORE_KB_FRAC} KB)"
fi
echo ""

# 检测压缩状态
echo "12. 检测 core.img 压缩状态"
echo "----------------------------------------"

# 方法1: 查找 LZMA 相关的函数调用或字符串
HAS_LZMA=0
if strings "$CORE_IMG_FILE" | grep -qi "lzma\|LzmaDecode"; then
    HAS_LZMA=1
    echo "✅ 找到 LZMA 相关字符串（可能使用 LZMA 压缩）"
    strings "$CORE_IMG_FILE" | grep -i "lzma\|LzmaDecode" | head -3
else
    echo "⚠️  未找到 LZMA 相关字符串"
fi
echo ""

# 方法2: 检查数据特征（压缩数据通常熵值较高）
echo "13. 分析数据特征（压缩检测）"
echo "----------------------------------------"

# 计算数据的熵值（简单方法：检查字节分布的均匀性）
# 压缩数据通常有较高的熵值（字节分布更均匀）
# 未压缩的代码数据通常有较低的熵值（某些字节值更常见）

# 提取 startup_raw.S 区域的数据（通常在 0x8200 之后，即第二个扇区开始）
# 在 core.img 中，startup_raw.S 通常在 diskboot.S（第一个扇区）之后
if [ "$CORE_SIZE" -ge 2048 ]; then
    # 提取第二个扇区开始的数据（startup_raw.S 区域）
    dd if="$CORE_IMG_FILE" bs=512 skip=1 count=4 2>/dev/null > core_img_startup_raw.bin
    
    # 计算数据特征
    STARTUP_RAW_BYTES=$(stat -f%z core_img_startup_raw.bin 2>/dev/null || stat -c%s core_img_startup_raw.bin 2>/dev/null)
    
    # 统计 NOP (0x90) 字节数量
    NOP_COUNT=$(od -An -tx1 core_img_startup_raw.bin | tr -d '\n ' | grep -o '90' | wc -l | tr -d ' ')
    
    # 统计零字节数量
    ZERO_COUNT=$(od -An -tx1 core_img_startup_raw.bin | tr -d '\n ' | grep -o '00' | wc -l | tr -d ' ')
    
    # 计算比例（使用 awk 避免依赖 bc）
    NOP_RATIO=$(awk "BEGIN {printf \"%.1f\", $NOP_COUNT * 100 / $STARTUP_RAW_BYTES}")
    ZERO_RATIO=$(awk "BEGIN {printf \"%.1f\", $ZERO_COUNT * 100 / $STARTUP_RAW_BYTES}")
    
    # 检查是否有可打印字符串（未压缩代码通常有更多字符串）
    PRINTABLE_STRINGS=$(strings -n 3 core_img_startup_raw.bin 2>/dev/null | wc -l | tr -d ' ')
    
echo "数据区域分析（startup_raw.S 区域，约 2KB）:"
echo "- 总字节数: $STARTUP_RAW_BYTES"
    echo "- NOP (0x90) 字节数量: $NOP_COUNT (${NOP_RATIO}%)"
    echo "- 零字节 (0x00) 数量: $ZERO_COUNT (${ZERO_RATIO}%)"
    echo "- 可打印字符串数量: $PRINTABLE_STRINGS"
    
    # 检查是否有明显的 LZMA 压缩数据特征
    # LZMA 压缩数据通常：
    # - 字节分布更均匀（高熵值）
    # - 较少的重复模式
    # - 较少的零字节和 NOP 指令
    
    # 检查是否有 ENABLE_LZMA 相关的代码模式
    # 在 startup_raw.S 中，如果有 LZMA 压缩，会有特定的代码模式
    # 检查是否有 call _LzmaDecodeA 的调用模式（通常是 e8 xx xx xx xx，call 指令）
    HAS_LZMA_CALL=0
    if hexdump -C core_img_startup_raw.bin | grep -q "e8.*e8.*e8"; then
        # 查找可能的 call 指令模式（LZMA 解压函数调用）
        LZMA_PATTERN=$(hexdump -C core_img_startup_raw.bin | grep -o "e8 [0-9a-f][0-9a-f] [0-9a-f][0-9a-f] [0-9a-f][0-9a-f] [0-9a-f][0-9a-f]" | head -1)
        if [ -n "$LZMA_PATTERN" ]; then
            HAS_LZMA_CALL=1
        fi
    fi
    
    # 综合判断压缩状态
    COMPRESSION_SCORE=0
    if [ "$HAS_LZMA" -eq 1 ]; then
        COMPRESSION_SCORE=$((COMPRESSION_SCORE + 3))
    fi
    if [ "$HAS_LZMA_CALL" -eq 1 ]; then
        COMPRESSION_SCORE=$((COMPRESSION_SCORE + 2))
    fi
    if [ "$(awk "BEGIN {print ($ZERO_RATIO < 15) ? 1 : 0}")" -eq 1 ]; then
        COMPRESSION_SCORE=$((COMPRESSION_SCORE + 1))
    fi
    if [ "$NOP_COUNT" -gt 30 ] || [ "$PRINTABLE_STRINGS" -gt 8 ]; then
        COMPRESSION_SCORE=$((COMPRESSION_SCORE - 1))
    fi
    
    # 判断压缩状态（使用 awk 进行浮点数比较）
    echo ""
    echo "压缩状态判断:"
    if [ "$COMPRESSION_SCORE" -ge 3 ]; then
        echo "✅ **使用 LZMA 压缩**"
        echo "   - 检测到 LZMA 压缩特征"
        if [ "$HAS_LZMA" -eq 1 ]; then
            echo "   - 找到 LZMA 相关字符串"
        fi
        if [ "$HAS_LZMA_CALL" -eq 1 ]; then
            echo "   - 检测到可能的 LZMA 解压函数调用"
        fi
        echo "   - core.img 需要解压到 0x100000 (1MB) 才能执行"
        echo "   - 解压函数: _LzmaDecodeA (在 startup_raw.S 中调用)"
    elif [ "$COMPRESSION_SCORE" -le 0 ] && [ "$(awk "BEGIN {print ($ZERO_RATIO >= 15) ? 1 : 0}")" -eq 1 ]; then
        echo "⚠️  **可能未压缩**"
        echo "   - 检测到未压缩代码特征"
        if [ "$NOP_COUNT" -gt 30 ]; then
            echo "   - NOP 指令较多 ($NOP_COUNT)，符合未压缩代码特征"
        fi
        if [ "$PRINTABLE_STRINGS" -gt 8 ]; then
            echo "   - 可打印字符串较多 ($PRINTABLE_STRINGS)，符合未压缩代码特征"
        fi
        echo "   - 零字节比例: ${ZERO_RATIO}% (未压缩代码常有填充的零字节)"
        echo "   - core.img 可能直接在前 1MB 中执行，不需要解压"
        echo "   - 代码位置: 0x8000+ (前 1MB)"
    else
        echo "❓ **无法确定**"
        echo "   - 数据特征不明显，需要进一步分析"
        echo "   - 压缩评分: $COMPRESSION_SCORE (>=3 表示压缩，<=0 表示未压缩)"
        echo "   - NOP 比例: ${NOP_RATIO}%"
        echo "   - 零字节比例: ${ZERO_RATIO}%"
        echo "   - 字符串数量: $PRINTABLE_STRINGS"
        echo "   - 提示:"
        echo "     * 如果零字节比例 < 15%，可能是压缩的"
        echo "     * 如果零字节比例 >= 15% 且 NOP/字符串较多，可能是未压缩的"
    fi
else
    echo "⚠️  core.img 数据不足，无法进行压缩检测"
fi
echo ""

# 总结
echo "=========================================="
echo "分析总结"
echo "=========================================="
echo "引导扇区: $BOOT_SECTOR_FILE (512 字节)"
echo "kernel_sector: $KERNEL_SECTOR (模式: $MODE)"
echo "core.img 起始扇区: $KERNEL_SECTOR"
if [ "$TOTAL_SECTORS" -gt 0 ]; then
    TOTAL_KB_DISPLAY=$((TOTAL_BYTES * 10 / 1024))
    TOTAL_KB_INT_DISPLAY=$((TOTAL_KB_DISPLAY / 10))
    TOTAL_KB_FRAC_DISPLAY=$((TOTAL_KB_DISPLAY % 10))
    echo "core.img 完整大小: $TOTAL_SECTORS 扇区 = $TOTAL_BYTES 字节 = ${TOTAL_KB_INT_DISPLAY}.${TOTAL_KB_FRAC_DISPLAY} KB"
    echo "core.img 完整文件: core_img_full.bin"
else
    echo "core.img 大小: 无法确定（块列表解析失败）"
fi
echo "core.img 第一个扇区: core_img_first_sector.bin"
echo ""
echo "说明:"
echo "- 标准模式: kernel_sector 在偏移 0x5c (92 字节)"
echo "- HYBRID_BOOT 模式: kernel_sector 在偏移 0x1b0 (432 字节)"
echo "- ISO 镜像通常使用 HYBRID_BOOT 模式"
echo "- core.img 不在 ISO 文件系统中，而是嵌入在 ISO 镜像的特定扇区位置"
echo "- core.img 大小通过块列表计算得出"
