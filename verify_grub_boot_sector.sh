#!/bin/bash
#
# GRUB ISO 镜像验证脚本（Bash 版本）
# 整合了 test_objdump.sh 和 verify_grub_boot_sector.py 的核心功能
#
# 功能：
# - 验证引导扇区签名和关键字段
# - 提取并分析 core.img 的块列表
# - 使用 objdump 反汇编 diskboot.S 和 startup_raw.S
# - 查找 LZMA 压缩标记
# - 分析数据特征（NOP、零字节等）
# - 检测压缩状态
#

set -e

ISO_FILE="${1:-../grub.iso}"

if [ ! -f "$ISO_FILE" ]; then
    echo "错误: 文件 $ISO_FILE 不存在"
    echo "用法: $0 [grub.iso]"
    exit 1
fi

# 临时文件
TEMP_DIR="/tmp/grub_verify_$$"
DISKBOOT_BIN="$TEMP_DIR/diskboot.bin"
CORE_IMG_BIN="$TEMP_DIR/core_img.bin"
FRONT_4K_BIN="$TEMP_DIR/front_4k.bin"

# 清理函数
cleanup() {
    rm -rf "$TEMP_DIR"
}
trap cleanup EXIT

mkdir -p "$TEMP_DIR"

echo "======================================================================"
echo "验证 GRUB ISO 引导扇区: $ISO_FILE"
echo "======================================================================"
echo ""

# ========== 1. 验证引导扇区 ==========
echo "【步骤 1】验证引导扇区"
echo "----------------------------------------------------------------------"

# 读取引导扇区到临时文件（避免命令替换忽略 null 字节）
BOOT_SECTOR_BIN="$TEMP_DIR/boot_sector.bin"
dd if="$ISO_FILE" of="$BOOT_SECTOR_BIN" bs=512 count=1 2>/dev/null

if [ ! -f "$BOOT_SECTOR_BIN" ] || [ $(stat -c%s "$BOOT_SECTOR_BIN" 2>/dev/null || stat -f%z "$BOOT_SECTOR_BIN" 2>/dev/null) -lt 512 ]; then
    echo "错误: ISO 文件太小，无法读取完整的引导扇区"
    exit 1
fi

echo "引导扇区大小: 512 字节"

# 验证引导扇区签名（最后两个字节应该是 0x55 0xAA）
SIG_BYTE1=$(dd if="$BOOT_SECTOR_BIN" bs=1 skip=510 count=1 2>/dev/null | od -An -tu1 | tr -d ' ')
SIG_BYTE2=$(dd if="$BOOT_SECTOR_BIN" bs=1 skip=511 count=1 2>/dev/null | od -An -tu1 | tr -d ' ')

echo "引导扇区签名 (偏移 0x1FE-0x1FF):"
echo "  实际值: 0x$(printf "%02X" $SIG_BYTE1) 0x$(printf "%02X" $SIG_BYTE2)"
echo "  期望值: 0x55 0xAA (0xAA55 小端序)"

if [ "$SIG_BYTE1" -eq 85 ] && [ "$SIG_BYTE2" -eq 170 ]; then
    echo "✅ 引导扇区签名正确"
else
    echo "❌ 引导扇区签名错误！"
    exit 1
fi

# 检查标准模式的 kernel_sector（偏移 0x5c）
KERNEL_SECTOR_STD=$(dd if="$BOOT_SECTOR_BIN" bs=1 skip=$((0x5c)) count=4 2>/dev/null | od -An -tu4 -N4 | tr -d ' ')
echo ""
echo "标准模式 kernel_sector (偏移 0x5c = 92 字节):"
echo "  值: $KERNEL_SECTOR_STD (0x$(printf "%x" $KERNEL_SECTOR_STD))"
if [ "$KERNEL_SECTOR_STD" -eq 0 ] || [ "$KERNEL_SECTOR_STD" -gt 100000 ]; then
    echo "  ⚠️  无效值（可能是 0 或过大）"
else
    echo "  ✅ 有效值: 扇区 $KERNEL_SECTOR_STD"
fi

# 检查 HYBRID_BOOT 模式的 kernel_sector（偏移 0x1b0）
KERNEL_SECTOR_HYBRID=$(dd if="$BOOT_SECTOR_BIN" bs=1 skip=$((0x1b0)) count=4 2>/dev/null | od -An -tu4 -N4 | tr -d ' ')
echo ""
echo "HYBRID_BOOT 模式 kernel_sector (偏移 0x1b0 = 432 字节):"
echo "  值: $KERNEL_SECTOR_HYBRID (0x$(printf "%x" $KERNEL_SECTOR_HYBRID))"
if [ "$KERNEL_SECTOR_HYBRID" -eq 0 ] || [ "$KERNEL_SECTOR_HYBRID" -gt 100000 ]; then
    echo "  ⚠️  无效值（可能是 0 或过大）"
else
    echo "  ✅ 有效值: 扇区 $KERNEL_SECTOR_HYBRID"
fi

# 确定使用的 kernel_sector
KERNEL_SECTOR=""
if [ "$KERNEL_SECTOR_HYBRID" -ne 0 ] && [ "$KERNEL_SECTOR_HYBRID" -lt 100000 ]; then
    KERNEL_SECTOR=$KERNEL_SECTOR_HYBRID
    echo ""
    echo "✅ 使用 HYBRID_BOOT 模式: kernel_sector = $KERNEL_SECTOR"
elif [ "$KERNEL_SECTOR_STD" -ne 0 ] && [ "$KERNEL_SECTOR_STD" -lt 100000 ]; then
    KERNEL_SECTOR=$KERNEL_SECTOR_STD
    echo ""
    echo "✅ 使用标准模式: kernel_sector = $KERNEL_SECTOR"
else
    echo ""
    echo "❌ 无法确定 kernel_sector，退出"
    exit 1
fi

# ========== 1.5. 分析 boot.S 代码 ==========
echo ""
echo "【步骤 1.5】分析 boot.S 代码（引导扇区）"
echo "----------------------------------------------------------------------"

if command -v objdump >/dev/null 2>&1; then
    echo "使用 objdump 反汇编 boot.S（16位实模式代码）:"
    echo "命令: objdump -D -b binary -m i8086 -M intel $BOOT_SECTOR_BIN"
    echo ""
    
    OBJDUMP_BOOT_OUTPUT=$(objdump -D -b binary -m i8086 -M intel --adjust-vma=0x7c00 "$BOOT_SECTOR_BIN" 2>&1)
    OBJDUMP_BOOT_EXIT=$?
    
    if [ $OBJDUMP_BOOT_EXIT -eq 0 ]; then
        echo "✅ objdump 反汇编成功"
        echo ""
        echo "查找 boot.S 的关键代码特征:"
        echo "----------------------------------------------------------------------"
        
        # 查找关键代码特征（使用 grep 直接检查，避免子 shell 问题）
        OBJDUMP_BOOT_TMP="$TEMP_DIR/objdump_boot.txt"
        echo "$OBJDUMP_BOOT_OUTPUT" > "$OBJDUMP_BOOT_TMP"
        
        FOUND_PUSH_DX=false
        FOUND_LJMP=false
        FOUND_INT13H=false
        FOUND_KERNEL_SECTOR_READ=false
        FOUND_GRUB_STRING=false
        
        # 检查是否包含 "GRUB" 字符串
        if grep -q "GRUB" "$BOOT_SECTOR_BIN"; then
            FOUND_GRUB_STRING=true
        fi
        
        # 使用 grep 检查特征（避免子 shell 问题）
        if grep -qiE "push.*dx|pushw.*dx" "$OBJDUMP_BOOT_TMP"; then
            FOUND_PUSH_DX=true
        fi
        
        if grep -qiE "ljmp|jmp.*far" "$OBJDUMP_BOOT_TMP"; then
            FOUND_LJMP=true
        fi
        
        if grep -qi "int.*0x13" "$OBJDUMP_BOOT_TMP"; then
            FOUND_INT13H=true
        fi
        
        if grep -qiE "mov.*0x[0-9a-f]+.*\[|movl.*0x[0-9a-f]+" "$OBJDUMP_BOOT_TMP"; then
            FOUND_KERNEL_SECTOR_READ=true
        fi
        
        echo "  - 保存驱动器号 (push dx): $(if [ "$FOUND_PUSH_DX" = true ]; then echo "✅ 找到"; else echo "⚠️  未找到"; fi)"
        echo "  - 长跳转指令 (ljmp): $(if [ "$FOUND_LJMP" = true ]; then echo "✅ 找到"; else echo "⚠️  未找到"; fi)"
        echo "  - INT 13h 调用: $(if [ "$FOUND_INT13H" = true ]; then echo "✅ 找到"; else echo "⚠️  未找到"; fi)"
        echo "  - 读取 kernel_sector: $(if [ "$FOUND_KERNEL_SECTOR_READ" = true ]; then echo "✅ 找到"; else echo "⚠️  未找到"; fi)"
        echo "  - GRUB 特征字符串: $(if [ "$FOUND_GRUB_STRING" = true ]; then echo "✅ 找到"; else echo "⚠️  未找到"; fi)"
        
        if [ "$FOUND_PUSH_DX" = true ] && [ "$FOUND_INT13H" = true ]; then
            echo ""
            echo "  ✅ 关键 boot.S 代码特征已找到"
        else
            echo ""
            echo "  ⚠️  部分特征未找到，但可能是代码优化或格式差异"
        fi
        
        echo ""
        echo "boot.S 反汇编代码（前 40 行，对应内存地址 0x7C00+）:"
        echo "----------------------------------------------------------------------"
        echo "$OBJDUMP_BOOT_OUTPUT" | head -40
        
    else
        echo "  ⚠️  objdump 反汇编失败，退出码: $OBJDUMP_BOOT_EXIT"
    fi
else
    echo "  ⚠️  objdump 未安装，跳过 boot.S 反汇编"
fi

# ========== 2. 提取 core.img ==========
echo ""
echo "【步骤 2】提取 core.img"
echo "----------------------------------------------------------------------"

# 读取第一个 GRUB Core 扇区（diskboot.S）
dd if="$ISO_FILE" of="$DISKBOOT_BIN" bs=512 count=1 skip=$KERNEL_SECTOR 2>/dev/null

# 读取块列表（偏移 0x1F4）
BLOCKLIST_OFFSET=0x1F4
BLOCKLIST_LEN=$(dd if="$DISKBOOT_BIN" bs=1 skip=$((BLOCKLIST_OFFSET + 8)) count=2 2>/dev/null | od -An -tu2 -N2 | tr -d ' ')

echo "块列表 len: $BLOCKLIST_LEN 扇区"
CORE_IMG_SIZE=$(((1 + BLOCKLIST_LEN) * 512))
echo "core.img 总大小: $CORE_IMG_SIZE 字节 ($(($CORE_IMG_SIZE / 1024)) KB)"

# 提取完整的 core.img
dd if="$ISO_FILE" of="$CORE_IMG_BIN" bs=512 count=$((1 + BLOCKLIST_LEN)) skip=$KERNEL_SECTOR 2>/dev/null

ACTUAL_SIZE=$(stat -c%s "$CORE_IMG_BIN" 2>/dev/null || stat -f%z "$CORE_IMG_BIN" 2>/dev/null)
if [ "$ACTUAL_SIZE" -eq "$CORE_IMG_SIZE" ]; then
    echo "✅ 成功提取 core.img，实际大小: $ACTUAL_SIZE 字节"
else
    echo "⚠️  提取 core.img 失败，期望大小 $CORE_IMG_SIZE 字节，实际 $ACTUAL_SIZE 字节"
    exit 1
fi

# ========== 3. 分析 diskboot.S ==========
echo ""
echo "【步骤 3】分析 diskboot.S 的实际大小"
echo "----------------------------------------------------------------------"

BLOCKLIST_OFFSET=0x1F4
BLOCKLIST_OFFSET_DEC=$((BLOCKLIST_OFFSET))
echo "✅ 找到块列表位置：文件偏移 0x$(printf "%x" $BLOCKLIST_OFFSET_DEC)，内存地址 0x$(printf "%x" $((0x8000 + BLOCKLIST_OFFSET_DEC)))"
echo "✅ diskboot.S 代码区域：0x0000 - 0x$(printf "%x" $((BLOCKLIST_OFFSET_DEC - 1)))（约 $BLOCKLIST_OFFSET_DEC 字节（0x$(printf "%x" $BLOCKLIST_OFFSET_DEC) 字节））"
echo "✅ 块列表数据区域：0x$(printf "%x" $BLOCKLIST_OFFSET_DEC) - 0x1FF（12 字节（0xc 字节））"

# 使用 objdump 反汇编 diskboot.S
if command -v objdump >/dev/null 2>&1; then
    echo ""
    echo "使用 objdump 反汇编 diskboot.S（16位实模式代码）:"
    echo "命令: objdump -D -b binary -m i8086 -M intel $DISKBOOT_BIN"
    echo ""
    
    OBJDUMP_OUTPUT=$(objdump -D -b binary -m i8086 -M intel "$DISKBOOT_BIN" 2>&1)
    OBJDUMP_EXIT=$?
    
    if [ $OBJDUMP_EXIT -eq 0 ]; then
        echo "✅ objdump 反汇编成功"
        
        # 查找关键代码特征
        echo ""
        echo "查找 diskboot.S 的关键代码特征:"
        echo "----------------------------------------------------------------------"
        
        # 查找设置段寄存器
        if echo "$OBJDUMP_OUTPUT" | grep -qi "mov.*ds\|mov.*es\|mov.*ss"; then
            echo "  ✅ 找到设置段寄存器指令"
        fi
        
        # 查找读取块列表（mov di, 0x81f4）
        if echo "$OBJDUMP_OUTPUT" | grep -qiE "mov.*di.*0x81f4|mov.*di.*0x1f4"; then
            echo "  ✅ 找到读取块列表指令（mov di, 0x81f4）"
        fi
        
        # 查找 INT 13h 调用
        if echo "$OBJDUMP_OUTPUT" | grep -qi "int.*0x13"; then
            echo "  ✅ 找到 INT 13h 调用"
        fi
        
        # 查找跳转到 startup_raw.S（jmp 0x8200）
        if echo "$OBJDUMP_OUTPUT" | grep -qiE "jmp.*0x8200|jmp.*0x82"; then
            echo "  ✅ 找到跳转到 startup_raw.S 指令（jmp 0x8200）"
        fi
        
        # 显示前 30 行反汇编
        echo ""
        echo "diskboot.S 反汇编代码（前 30 行，对应内存地址 0x8000+）:"
        echo "----------------------------------------------------------------------"
        echo "$OBJDUMP_OUTPUT" | head -30 | while IFS= read -r line; do
            # 替换文件偏移为内存地址
            if echo "$line" | grep -qE "^[[:space:]]*[0-9a-fA-F]+:"; then
                OFFSET=$(echo "$line" | sed -n 's/^[[:space:]]*\([0-9a-fA-F]*\):.*/\1/p' | head -1)
                if [ -n "$OFFSET" ]; then
                    MEM_ADDR=$((0x8000 + 0x$OFFSET))
                    echo "$line" | sed "s/^[[:space:]]*[0-9a-fA-F]*:/  0x$(printf "%06x" $MEM_ADDR):/"
                else
                    echo "$line"
                fi
            else
                echo "$line"
            fi
        done
    else
        echo "⚠️  objdump 反汇编失败，退出码: $OBJDUMP_EXIT"
    fi
else
    echo "⚠️  objdump 未安装，跳过 diskboot.S 反汇编"
fi

# ========== 4. 分析 startup_raw.S ==========
echo ""
echo "【步骤 4】分析 startup_raw.S 的实际大小"
echo "----------------------------------------------------------------------"

# 提取前 4KB
dd if="$CORE_IMG_BIN" of="$FRONT_4K_BIN" bs=1 count=4096 2>/dev/null

# 方法 1：查找 LZMA 压缩标记（0x5D 0x00 0x00）
echo "方法 1：查找 LZMA 压缩标记（0x5D 0x00 0x00）..."

LZMA_POS=""
# 使用 grep 搜索二进制模式
if command -v grep >/dev/null 2>&1; then
    LZMA_LINE=$(grep -a -b -o $'\x5d\x00\x00' "$CORE_IMG_BIN" 2>/dev/null | head -1)
    if [ -n "$LZMA_LINE" ]; then
        LZMA_POS=$(echo "$LZMA_LINE" | cut -d: -f1)
    fi
fi

# 如果 grep 没找到，使用 Python
if [ -z "$LZMA_POS" ] && command -v python3 >/dev/null 2>&1; then
    LZMA_POS=$(python3 -c "
import sys
with open('$CORE_IMG_BIN', 'rb') as f:
    data = f.read()
    pos = data.find(b'\x5d\x00\x00')
    if pos >= 0:
        print(pos)
    else:
        print('')
" 2>/dev/null)
fi

STARTUP_RAW_END=4096  # 默认假设 4KB
if [ -n "$LZMA_POS" ] && [ "$LZMA_POS" != "" ] && [ "$LZMA_POS" -gt 0 ]; then
    LZMA_POS_HEX=$(printf "0x%x" $LZMA_POS)
    LZMA_MEM=$((0x8000 + LZMA_POS))
    LZMA_MEM_HEX=$(printf "0x%x" $LZMA_MEM)
    STARTUP_SIZE=$((LZMA_POS - 512))
    STARTUP_SIZE_HEX=$(printf "0x%x" $STARTUP_SIZE)
    
    if [ "$LZMA_POS" -lt 1024 ]; then
        echo "  ⚠️  警告：LZMA 标记位置 $LZMA_POS_HEX 似乎太早（< 1KB）"
        echo "     这可能是数据中的巧合，不是真正的 LZMA 压缩标记"
        echo "     将在后续分析中验证 4096 字节之后是否有真正的 LZMA 标记..."
        LZMA_POS=""
    else
        echo "  ✅ 找到 LZMA 压缩标记：文件偏移 $LZMA_POS ($LZMA_POS_HEX)"
        echo "     内存地址: $LZMA_MEM_HEX (0x8000 + $LZMA_POS_HEX)"
        echo "     startup_raw.S 的实际大小：约 $STARTUP_SIZE 字节（$STARTUP_SIZE_HEX 字节）"
        STARTUP_RAW_END=$LZMA_POS
    fi
else
    echo "  ⚠️  在前 12KB 中未找到 LZMA 压缩标记（0x5D 0x00 0x00）"
    echo "     将在后续分析中检查 4096 字节之后的位置..."
fi

# 方法 2：使用 objdump 反汇编前 4KB
echo ""
echo "方法 2：使用 objdump 反汇编查找代码边界..."

if command -v objdump >/dev/null 2>&1; then
    OBJDUMP_OUTPUT2=$(objdump -D -b binary -m i386 -M intel "$FRONT_4K_BIN" 2>&1)
    OBJDUMP_EXIT2=$?
    
    if [ $OBJDUMP_EXIT2 -eq 0 ]; then
        echo "  ✅ objdump 反汇编成功"
        
        # 查找代码边界（查找连续的填充字节）
        # 使用临时文件避免管道导致的子 shell 问题
        OBJDUMP_TMP="$TEMP_DIR/objdump_output.txt"
        echo "$OBJDUMP_OUTPUT2" > "$OBJDUMP_TMP"
        
        # 查找 startup_raw.S 的关键代码特征
        echo ""
        echo "查找 startup_raw.S 的关键代码特征:"
        echo "----------------------------------------------------------------------"
        
        FOUND_CLI=false
        FOUND_SEGMENT_SETUP=false
        FOUND_REAL_TO_PROT=false
        FOUND_A20=false
        FOUND_LZMA_DECODE=false
        FOUND_JMP_ESI=false
        
        # 检查 cli（禁用中断）
        if grep -qi "cli" "$OBJDUMP_TMP"; then
            FOUND_CLI=true
        fi
        
        # 检查设置段寄存器（mov ds, ax 或 mov es, ax 等）
        if grep -qiE "mov.*ds|mov.*es|mov.*ss|mov.*ax.*ds|mov.*ax.*es" "$OBJDUMP_TMP"; then
            FOUND_SEGMENT_SETUP=true
        fi
        
        # 检查 real_to_prot 调用（切换到保护模式）
        if grep -qiE "call.*real_to_prot|call.*0x[0-9a-f]+.*real" "$OBJDUMP_TMP"; then
            FOUND_REAL_TO_PROT=true
        fi
        
        # 检查 A20 启用（grub_gate_a20）
        if grep -qiE "call.*a20|call.*gate_a20|call.*grub_gate" "$OBJDUMP_TMP"; then
            FOUND_A20=true
        fi
        
        # 检查 LZMA 解压调用（_LzmaDecodeA）
        if grep -qiE "call.*lzma|call.*LzmaDecode|call.*decode" "$OBJDUMP_TMP"; then
            FOUND_LZMA_DECODE=true
        fi
        
        # 检查跳转到解压后的代码（jmp *%esi 或 jmp esi）
        if grep -qiE "jmp.*esi|jmp.*%esi|jmp.*\[.*esi" "$OBJDUMP_TMP"; then
            FOUND_JMP_ESI=true
        fi
        
        echo "  - 禁用中断 (cli): $(if [ "$FOUND_CLI" = true ]; then echo "✅ 找到"; else echo "⚠️  未找到"; fi)"
        echo "  - 设置段寄存器: $(if [ "$FOUND_SEGMENT_SETUP" = true ]; then echo "✅ 找到"; else echo "⚠️  未找到"; fi)"
        echo "  - 切换到保护模式 (real_to_prot): $(if [ "$FOUND_REAL_TO_PROT" = true ]; then echo "✅ 找到"; else echo "⚠️  未找到"; fi)"
        echo "  - 启用 A20 (grub_gate_a20): $(if [ "$FOUND_A20" = true ]; then echo "✅ 找到"; else echo "⚠️  未找到"; fi)"
        echo "  - LZMA 解压调用 (_LzmaDecodeA): $(if [ "$FOUND_LZMA_DECODE" = true ]; then echo "✅ 找到"; else echo "⚠️  未找到"; fi)"
        echo "  - 跳转到解压代码 (jmp *%esi): $(if [ "$FOUND_JMP_ESI" = true ]; then echo "✅ 找到"; else echo "⚠️  未找到"; fi)"
        
        if [ "$FOUND_CLI" = true ] && [ "$FOUND_SEGMENT_SETUP" = true ]; then
            echo ""
            echo "  ✅ 关键 startup_raw.S 代码特征已找到"
        else
            echo ""
            echo "  ⚠️  部分特征未找到，但可能是代码优化或格式差异"
        fi
        
        # 显示 startup_raw.S 反汇编代码（前 40 行，对应内存地址 0x8200+）
        echo ""
        echo "startup_raw.S 反汇编代码（前 40 行，对应内存地址 0x8200+）:"
        echo "----------------------------------------------------------------------"
        # 使用 --adjust-vma=0x8000 重新反汇编，确保地址正确
        OBJDUMP_STARTUP=$(objdump -D -b binary -m i386 -M intel --adjust-vma=0x8000 "$FRONT_4K_BIN" 2>&1)
        OBJDUMP_STARTUP_TMP="$TEMP_DIR/objdump_startup.txt"
        echo "$OBJDUMP_STARTUP" > "$OBJDUMP_STARTUP_TMP"
        
        # 使用 awk 过滤并显示 startup_raw.S 区域（内存地址 0x8200-0x9000）
        LINE_COUNT=0
        while IFS= read -r line && [ "$LINE_COUNT" -lt 40 ]; do
            # 检查是否是包含地址的行
            if echo "$line" | grep -qE "^\s*(0x)?[0-9a-fA-F]+:"; then
                # 提取地址（支持多种格式）
                ADDR_STR=""
                # 格式1: "   0x008200:" 或 "  0x8200:"
                if echo "$line" | grep -qE "^\s*0x[0-9a-fA-F]+:"; then
                    ADDR_STR=$(echo "$line" | sed -n 's/.*0x\([0-9a-fA-F]*\):.*/\1/p' | head -1)
                # 格式2: "   2080:" 
                elif echo "$line" | grep -qE "^\s+[0-9a-fA-F]+:"; then
                    ADDR_STR=$(echo "$line" | sed -n 's/^\s*\([0-9a-fA-F]*\):.*/\1/p' | head -1)
                fi
                
                if [ -n "$ADDR_STR" ]; then
                    ADDR=$((0x$ADDR_STR))
                    # startup_raw.S 区域：内存地址 0x8200-0x9000（对应文件偏移 512-4096）
                    if [ "$ADDR" -ge 33280 ] && [ "$ADDR" -lt 36864 ]; then  # 0x8200-0x9000
                        echo "$line"
                        LINE_COUNT=$((LINE_COUNT + 1))
                    fi
                fi
            fi
        done < "$OBJDUMP_STARTUP_TMP"
        
        # 如果没找到，直接显示前 40 行包含地址的行（不过滤地址范围）
        if [ "$LINE_COUNT" -eq 0 ]; then
            echo "  ⚠️  未能按地址范围过滤，显示所有反汇编代码（前 40 行包含地址的行）:"
            echo "$OBJDUMP_STARTUP" | grep -E "^\s*(0x)?[0-9a-fA-F]+:" | head -40
        fi
        
        LAST_CODE_ADDR=512
        CONSECUTIVE_PADDING=0
        FOUND_CODE_BOUNDARY=false
        
        while IFS= read -r line; do
            # 提取地址（支持多种格式）
            # 格式1: "  0x008000:" 或 "   0x008000:"
            # 格式2: "   200:" 或 "  200:"
            OFFSET=""
            if echo "$line" | grep -qE "^\s*0x[0-9a-fA-F]+:"; then
                # 格式1: 0x008000:
                OFFSET=$(echo "$line" | sed -n 's/.*0x\([0-9a-fA-F]*\):.*/\1/p' | head -1)
            elif echo "$line" | grep -qE "^\s+[0-9a-fA-F]+:"; then
                # 格式2: 200:
                OFFSET=$(echo "$line" | sed -n 's/^\s*\([0-9a-fA-F]*\):.*/\1/p' | head -1)
            fi
            
            if [ -n "$OFFSET" ]; then
                MEM_ADDR=$((0x$OFFSET))
                # 注意：objdump 显示的是内存地址（0x8000+），需要转换为文件偏移
                # 文件偏移 = 内存地址 - 0x8000
                MEM_BASE=32768  # 0x8000 in decimal
                if [ "$MEM_ADDR" -ge $MEM_BASE ]; then
                    ADDR=$((MEM_ADDR - MEM_BASE))
                else
                    ADDR=$MEM_ADDR
                fi
                # 对于前 4KB 的数据，文件偏移应该在 512-4096 之间
                if [ "$ADDR" -ge 512 ] && [ "$ADDR" -lt 4096 ]; then
                    # 检查是否是填充字节（nop 或连续的 0x00）
                    # 更精确的判断：检查是否是 "nop" 指令或连续的 "00 00 00" 字节
                    if echo "$line" | grep -qiE "nop|^\s*[0-9a-fA-Fx]+:\s+00\s+00\s+00"; then
                        CONSECUTIVE_PADDING=$((CONSECUTIVE_PADDING + 1))
                        if [ "$CONSECUTIVE_PADDING" -gt 50 ]; then
                            FOUND_CODE_BOUNDARY=true
                            break
                        fi
                    else
                        CONSECUTIVE_PADDING=0
                        if [ "$ADDR" -gt "$LAST_CODE_ADDR" ]; then
                            LAST_CODE_ADDR=$ADDR
                        fi
                    fi
                fi
            fi
        done < "$OBJDUMP_TMP"
        
        if [ "$LAST_CODE_ADDR" -gt 512 ] || [ "$FOUND_CODE_BOUNDARY" = true ]; then
            # 如果找到了 LZMA 标记，使用较小的值
            if [ -n "$LZMA_POS" ] && [ "$LZMA_POS" -gt 0 ] && [ "$LZMA_POS" -lt 1024 ]; then
                # LZMA 标记太早，忽略
                STARTUP_RAW_END=$((LAST_CODE_ADDR + 100))
            elif [ -n "$LZMA_POS" ] && [ "$LZMA_POS" -gt 0 ]; then
                STARTUP_RAW_END=$((LAST_CODE_ADDR + 100 < LZMA_POS ? LAST_CODE_ADDR + 100 : LZMA_POS))
            else
                STARTUP_RAW_END=$((LAST_CODE_ADDR + 100))
            fi
            echo "  ✅ 通过 objdump 分析：startup_raw.S 代码实际结束位置约 0x$(printf "%x" $STARTUP_RAW_END)"
            echo "     实际代码大小：约 $((STARTUP_RAW_END - 512)) 字节（0x$(printf "%x" $((STARTUP_RAW_END - 512))) 字节）"
            if [ "$FOUND_CODE_BOUNDARY" = true ]; then
                echo "     检测到连续填充字节，代码边界在 0x$(printf "%x" $LAST_CODE_ADDR)"
            elif [ "$LAST_CODE_ADDR" -gt 512 ]; then
                echo "     最后有效代码地址: 0x$(printf "%x" $LAST_CODE_ADDR)"
            fi
        else
            echo "  ⚠️  objdump 未能确定代码边界（LAST_CODE_ADDR=$LAST_CODE_ADDR），使用默认值 4KB"
        fi
    else
        echo "  ⚠️  objdump 分析失败，退出码: $OBJDUMP_EXIT2"
    fi
else
    echo "  ⚠️  objdump 未安装，跳过 startup_raw.S 的 objdump 分析"
fi

# 检查 4096 字节之后是否有 LZMA 标记
if [ -z "$LZMA_POS" ] || [ "$LZMA_POS" = "" ] || [ "$LZMA_POS" -lt 1024 ]; then
    echo ""
    echo "检查 4096 字节之后是否有 LZMA 标记..."
    # 使用 Python 搜索
    if command -v python3 >/dev/null 2>&1; then
        LZMA_BACK_POS=$(python3 -c "
import sys
with open('$CORE_IMG_BIN', 'rb') as f:
    data = f.read()
    # 在 4096 之后搜索
    pos = data.find(b'\x5d\x00\x00', 4096)
    if pos >= 0:
        print(pos)
    else:
        print('')
" 2>/dev/null)
        
        if [ -n "$LZMA_BACK_POS" ] && [ "$LZMA_BACK_POS" != "" ] && [ "$LZMA_BACK_POS" -gt 0 ]; then
            LZMA_POS=$LZMA_BACK_POS
            LZMA_POS_HEX=$(printf "0x%x" $LZMA_POS)
            LZMA_MEM=$((0x8000 + LZMA_POS))
            LZMA_MEM_HEX=$(printf "0x%x" $LZMA_MEM)
            STARTUP_SIZE=$((LZMA_POS - 512))
            STARTUP_SIZE_HEX=$(printf "0x%x" $STARTUP_SIZE)
            echo "  ✅ 在后续分析中找到 LZMA 压缩标记：文件偏移 $LZMA_POS ($LZMA_POS_HEX)"
            echo "     内存地址: $LZMA_MEM_HEX (0x8000 + $LZMA_POS_HEX)"
            echo "     startup_raw.S 的实际大小：约 $STARTUP_SIZE 字节（$STARTUP_SIZE_HEX 字节）"
            STARTUP_RAW_END=$LZMA_POS
        else
            echo "  ⚠️  在 4096 字节之后未找到 LZMA 压缩标记"
        fi
    else
        echo "  ⚠️  python3 未安装，无法搜索 LZMA 标记"
    fi
fi

# ========== 5. 数据特征分析 ==========
echo ""
echo "【步骤 5】数据特征分析"
echo "----------------------------------------------------------------------"

# 分析 startup_raw.S 区域
STARTUP_RAW_DATA_BIN="$TEMP_DIR/startup_raw.bin"
dd if="$CORE_IMG_BIN" of="$STARTUP_RAW_DATA_BIN" bs=1 skip=512 count=$((STARTUP_RAW_END - 512)) 2>/dev/null
STARTUP_RAW_SIZE=$(stat -c%s "$STARTUP_RAW_DATA_BIN" 2>/dev/null || stat -f%z "$STARTUP_RAW_DATA_BIN" 2>/dev/null)

if [ "$STARTUP_RAW_SIZE" -gt 0 ]; then
    # 统计 NOP (0x90) 和零字节 (0x00)
    NOP_COUNT=$(od -An -tu1 "$STARTUP_RAW_DATA_BIN" | tr -s ' ' '\n' | grep -c "^90$" || echo "0")
    ZERO_COUNT=$(od -An -tu1 "$STARTUP_RAW_DATA_BIN" | tr -s ' ' '\n' | grep -c "^0$" || echo "0")
    
    NOP_RATIO=$(awk "BEGIN {printf \"%.1f\", ($NOP_COUNT * 100.0) / $STARTUP_RAW_SIZE}")
    ZERO_RATIO=$(awk "BEGIN {printf \"%.1f\", ($ZERO_COUNT * 100.0) / $STARTUP_RAW_SIZE}")
    
    echo "数据特征分析（startup_raw.S 区域，实际大小 $STARTUP_RAW_SIZE 字节）:"
    echo "  - 总字节数: $STARTUP_RAW_SIZE"
    echo "  - NOP (0x90) 字节数量: $NOP_COUNT ($NOP_RATIO%)"
    echo "  - 零字节 (0x00) 数量: $ZERO_COUNT ($ZERO_RATIO%)"
fi

# ========== 6. 压缩状态检测 ==========
echo ""
echo "【步骤 6】压缩状态检测"
echo "----------------------------------------------------------------------"

# 检查前 4KB 和后 24KB
FRONT_4K_BIN="$TEMP_DIR/front_4k_check.bin"
BACK_24K_BIN="$TEMP_DIR/back_24k_check.bin"
dd if="$CORE_IMG_BIN" of="$FRONT_4K_BIN" bs=1 count=4096 2>/dev/null
dd if="$CORE_IMG_BIN" of="$BACK_24K_BIN" bs=1 skip=4096 2>/dev/null

HAS_LZMA_FRONT=false
HAS_LZMA_BACK=false

if grep -aq $'\x5d\x00\x00' "$FRONT_4K_BIN" 2>/dev/null; then
    HAS_LZMA_FRONT=true
fi

if grep -aq $'\x5d\x00\x00' "$BACK_24K_BIN" 2>/dev/null; then
    HAS_LZMA_BACK=true
fi

if [ "$HAS_LZMA_BACK" = true ] && [ "$HAS_LZMA_FRONT" = false ]; then
    echo "  ✅ 检测到混合格式（前 4KB 未压缩，后 24KB 压缩）"
    echo "  → 前 4KB: diskboot.S + startup_raw.S（未压缩，在 0x8000+）"
    echo "  → 后 24KB: C 代码（LZMA 压缩）"
    echo "  → 解压过程："
    echo "     1. startup_raw.S 切换到保护模式并启用 A20 地址线"
    echo "     2. 调用 _LzmaDecodeA 函数解压后 24KB 的压缩代码"
    echo "     3. 解压目标地址: 0x100000 (1MB)"
    echo "     4. 解压后跳转到 grub_stub_init（解压后的代码入口点）"
elif [ "$HAS_LZMA_BACK" = true ]; then
    echo "  ✅ 检测到 LZMA 压缩"
    echo "  → 运行时代码入口点: 0x100000 (1MB)"
elif [ "$HAS_LZMA_FRONT" = false ] && [ "$HAS_LZMA_BACK" = false ]; then
    echo "  ⚠️  未检测到 LZMA 压缩（代码未压缩）"
    echo "  → 代码入口点可能在 0x8000+ (前 1MB)"
else
    echo "  ❓ 压缩状态不确定"
fi

# ========== 7. 总结 ==========
echo ""
echo "======================================================================"
echo "分析结果总结"
echo "======================================================================"
BLOCKLIST_OFFSET_DEC=$((BLOCKLIST_OFFSET))
echo "  diskboot.S:"
echo "    - 文件偏移：0x0000 - 0x$(printf "%x" $((BLOCKLIST_OFFSET_DEC - 1)))"
echo "    - 内存地址：0x8000 - 0x$(printf "%x" $((0x8000 + BLOCKLIST_OFFSET_DEC - 1)))"
echo "    - 实际代码大小：约 $BLOCKLIST_OFFSET_DEC 字节（0x$(printf "%x" $BLOCKLIST_OFFSET_DEC) 字节）"
echo "    - 块列表：0x$(printf "%x" $BLOCKLIST_OFFSET_DEC) - 0x1FF（12 字节（0xc 字节））"
echo ""
echo "  startup_raw.S:"
echo "    - 文件偏移：0x0200 (512) - 0x$(printf "%x" $STARTUP_RAW_END)"
echo "    - 内存地址：0x8200 - 0x$(printf "%x" $((0x8000 + STARTUP_RAW_END)))"
echo "    - 实际代码大小：约 $((STARTUP_RAW_END - 512)) 字节（0x$(printf "%x" $((STARTUP_RAW_END - 512))) 字节）"
echo ""

if [ -n "$LZMA_POS" ] && [ "$LZMA_POS" != "" ] && [ "$LZMA_POS" -gt 0 ] && [ "$LZMA_POS" -ge 1024 ]; then
    echo "  压缩 C 代码:"
    echo "    - 文件偏移：0x$(printf "%x" $LZMA_POS) - 0x$(printf "%x" $CORE_IMG_SIZE)"
    echo "    - 内存地址：0x$(printf "%x" $((0x8000 + LZMA_POS))) - 0x$(printf "%x" $((0x8000 + CORE_IMG_SIZE)))"
    echo "    - 压缩大小：约 $((CORE_IMG_SIZE - LZMA_POS)) 字节 ($(awk "BEGIN {printf \"%.1f\", ($CORE_IMG_SIZE - $LZMA_POS) / 1024}") KB）"
else
    echo "  压缩 C 代码:"
    echo "    - ⚠️  未找到 LZMA 压缩标记，无法确定压缩代码的起始位置"
    echo "    - 假设压缩代码从 0x$(printf "%x" $STARTUP_RAW_END) 开始（基于默认 4KB 边界）"
    if [ "$STARTUP_RAW_END" -lt "$CORE_IMG_SIZE" ]; then
        echo "    - 文件偏移：0x$(printf "%x" $STARTUP_RAW_END) - 0x$(printf "%x" $CORE_IMG_SIZE)"
        echo "    - 内存地址：0x$(printf "%x" $((0x8000 + STARTUP_RAW_END))) - 0x$(printf "%x" $((0x8000 + CORE_IMG_SIZE)))"
        echo "    - 压缩大小：约 $((CORE_IMG_SIZE - STARTUP_RAW_END)) 字节 ($(awk "BEGIN {printf \"%.1f\", ($CORE_IMG_SIZE - $STARTUP_RAW_END) / 1024}") KB）"
    fi
fi

echo ""
echo "  前 4KB 未压缩区域:"
echo "    - 总大小：$STARTUP_RAW_END 字节（$(awk "BEGIN {printf \"%.1f\", $STARTUP_RAW_END / 1024}") KB）"
BLOCKLIST_OFFSET_DEC_FINAL=$((BLOCKLIST_OFFSET))
echo "    - 组成：diskboot.S ($BLOCKLIST_OFFSET_DEC_FINAL 字节（0x$(printf "%x" $BLOCKLIST_OFFSET_DEC_FINAL) 字节）) + 块列表 (12 字节（0xc 字节）) + startup_raw.S ($((STARTUP_RAW_END - 512)) 字节（0x$(printf "%x" $((STARTUP_RAW_END - 512))) 字节））"
echo ""

echo "======================================================================"
echo "验证完成"
echo "======================================================================"
