#!/bin/bash
# 验证引导扇区 boot.bin 在内存地址 0x7C00 位置的代码
#
# 引导扇区会被 BIOS 加载到内存地址 0x7C00 处执行。
# 这个脚本验证 boot.bin 文件的内容，确认其符合引导扇区的要求。

set -euo pipefail

BOOT_FILE="${1:-boot.bin}"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查文件是否存在
if [ ! -f "$BOOT_FILE" ]; then
    echo -e "${RED}错误: 文件 $BOOT_FILE 不存在${NC}"
    echo "请先运行 'make build' 编译 boot.asm"
    exit 1
fi

echo "======================================================================"
echo "验证引导扇区文件: $BOOT_FILE"
echo "======================================================================"

# 获取文件大小
FILE_SIZE=$(stat -f%z "$BOOT_FILE" 2>/dev/null || stat -c%s "$BOOT_FILE" 2>/dev/null)
echo -e "\n文件大小: $FILE_SIZE 字节"

# 验证文件大小
if [ "$FILE_SIZE" -ne 512 ]; then
    echo -e "${YELLOW}⚠️  警告: 引导扇区应该是 512 字节，但文件是 $FILE_SIZE 字节${NC}"
    if [ "$FILE_SIZE" -gt 512 ]; then
        echo "   文件过大，可能无法作为引导扇区使用"
        exit 1
    fi
else
    echo -e "${GREEN}✅ 文件大小正确 (512 字节)${NC}"
fi

# 验证引导扇区签名（最后两个字节应该是 0x55 0xAA）
SIG_BYTE1=$(od -An -tx1 -j 510 -N 1 "$BOOT_FILE" | tr -d ' \n')
SIG_BYTE2=$(od -An -tx1 -j 511 -N 1 "$BOOT_FILE" | tr -d ' \n')

echo -e "\n引导扇区签名 (偏移 0x1FE-0x1FF):"
echo "  实际值: 0x$SIG_BYTE1 0x$SIG_BYTE2"
echo "  期望值: 0x55 0xAA (0xAA55 小端序)"

if [ "$SIG_BYTE1" = "55" ] && [ "$SIG_BYTE2" = "aa" ]; then
    echo -e "${GREEN}✅ 引导扇区签名正确${NC}"
else
    echo -e "${RED}❌ 引导扇区签名错误！BIOS 不会执行此引导扇区${NC}"
    exit 1
fi

# 显示文件内容（十六进制）
echo -e "\n======================================================================"
echo "文件内容 (十六进制，对应内存地址 0x7C00-0x7DFF):"
echo "======================================================================"

# 使用 hexdump 显示，每行 16 字节
hexdump -C "$BOOT_FILE" | while IFS= read -r line; do
    # 提取偏移量
    offset=$(echo "$line" | awk '{print $1}' | sed 's/^0*//')
    if [ -z "$offset" ]; then
        echo "$line"
        continue
    fi
    
    # 转换为十进制
    offset_dec=$((0x$offset))
    # 计算内存地址
    mem_addr=$((0x7C00 + offset_dec))
    
    # 替换偏移量为内存地址
    echo "$line" | sed "s/^0*$offset/0x$(printf "%04X" $mem_addr) (+0x$(printf "%03X" $offset_dec))/"
done

# 分析关键代码位置
echo -e "\n======================================================================"
echo "关键代码位置分析:"
echo "======================================================================"

# 检查开头的代码（应该是 mov ax, 0x0003 = B8 03 00）
FIRST_BYTE=$(od -An -tx1 -j 0 -N 1 "$BOOT_FILE" | tr -d ' \n')
SECOND_BYTE=$(od -An -tx1 -j 1 -N 1 "$BOOT_FILE" | tr -d ' \n')
THIRD_BYTE=$(od -An -tx1 -j 2 -N 1 "$BOOT_FILE" | tr -d ' \n')

echo -e "\n地址 0x7C00 (文件偏移 0x000): $FIRST_BYTE $SECOND_BYTE $THIRD_BYTE"
if [ "$FIRST_BYTE" = "b8" ] && [ "$SECOND_BYTE" = "03" ] && [ "$THIRD_BYTE" = "00" ]; then
    echo -e "  ${GREEN}✅ 检测到: mov ax, 0x0003 (B8 03 00)${NC}"
else
    echo -e "  ${YELLOW}⚠️  未识别的指令: $FIRST_BYTE $SECOND_BYTE $THIRD_BYTE${NC}"
fi

# 查找字符串 "Hello from Boot Sector!"
SEARCH_STR="Hello from Boot Sector!"
STR_POS=$(strings -a -t x "$BOOT_FILE" | grep -i "$SEARCH_STR" | head -1 | awk '{print $1}' || echo "")

if [ -n "$STR_POS" ]; then
    STR_POS_DEC=$((0x$STR_POS))
    STR_ADDR=$((0x7C00 + STR_POS_DEC))
    echo -e "\n字符串位置:"
    echo "  文件偏移: 0x$(printf "%03X" $STR_POS_DEC)"
    echo "  内存地址: 0x$(printf "%04X" $STR_ADDR)"
    echo "  内容: \"$SEARCH_STR\""
    echo -e "  ${GREEN}✅ 找到消息字符串${NC}"
else
    echo -e "\n${YELLOW}⚠️  未找到消息字符串 \"$SEARCH_STR\"${NC}"
    STR_POS_DEC=""
fi

# 填充分析
ZERO_COUNT=$(od -An -tx1 "$BOOT_FILE" | tr -d ' \n' | grep -o "00" | wc -l | tr -d ' ')
ZERO_PERCENT=$(awk "BEGIN {printf \"%.1f\", ($ZERO_COUNT / $FILE_SIZE) * 100}")

echo -e "\n填充分析:"
echo "  零字节数量: $ZERO_COUNT ($ZERO_PERCENT%)"

if [ -n "$STR_POS_DEC" ]; then
    STR_LEN=${#SEARCH_STR}
    CODE_END=$((STR_POS_DEC + STR_LEN + 1))  # 包括字符串结束符
    PADDING_START=$CODE_END
    PADDING_SIZE=$((510 - CODE_END))
    
    CODE_END_ADDR=$((0x7C00 + CODE_END - 1))
    PADDING_START_ADDR=$((0x7C00 + PADDING_START))
    PADDING_END_ADDR=$((0x7C00 + 509))
    SIG_START_ADDR=$((0x7C00 + 510))
    SIG_END_ADDR=$((0x7C00 + 511))
    
    echo "  代码+数据区域: 0x7C00 - 0x$(printf "%04X" $CODE_END_ADDR) ($CODE_END 字节)"
    echo "  填充区域: 0x$(printf "%04X" $PADDING_START_ADDR) - 0x$(printf "%04X" $PADDING_END_ADDR) ($PADDING_SIZE 字节)"
    echo "  签名区域: 0x$(printf "%04X" $SIG_START_ADDR) - 0x$(printf "%04X" $SIG_END_ADDR) (2 字节)"
fi

# 使用 objdump 生成 Intel 格式反汇编
echo -e "\n======================================================================"
echo "Intel 格式反汇编 (使用 objdump):"
echo "======================================================================"

if ! command -v objdump &> /dev/null; then
    echo -e "${YELLOW}⚠️  objdump 未找到，跳过反汇编${NC}"
    echo "   提示: 可以使用 'objdump -D -b binary -m i8086 -M intel $BOOT_FILE' 手动查看"
else
    # 使用 objdump 反汇编，并处理输出
    objdump -D -b binary -m i8086 -M intel "$BOOT_FILE" 2>/dev/null | while IFS= read -r line; do
        # 跳过头部信息
        if [[ "$line" =~ ^"$BOOT_FILE": ]] || [[ "$line" =~ ^"Disassembly" ]]; then
            continue
        fi
        
        # 处理反汇编行
        if [[ "$line" =~ ^[[:space:]]*([0-9a-f]+): ]]; then
            file_offset="${BASH_REMATCH[1]}"
            file_offset_dec=$((0x$file_offset))
            mem_addr=$((0x7C00 + file_offset_dec))
            
            # 如果进入数据区域（字符串开始位置），添加注释
            if [ -n "$STR_POS_DEC" ] && [ "$file_offset_dec" -eq "$STR_POS_DEC" ]; then
                echo ""
                echo "; 数据区域开始 (字符串 \"$SEARCH_STR\"):"
            fi
            
            # 替换文件偏移为内存地址
            line_with_addr=$(echo "$line" | sed "s/^[[:space:]]*$file_offset/0x$(printf "%04X" $mem_addr)/")
            
            # 如果是数据区域，尝试添加 ASCII 注释
            if [ -n "$STR_POS_DEC" ] && [ "$file_offset_dec" -ge "$STR_POS_DEC" ] && [ "$file_offset_dec" -lt 510 ]; then
                byte_val=$(od -An -tx1 -j "$file_offset_dec" -N 1 "$BOOT_FILE" | tr -d ' \n')
                byte_val_dec=$((0x$byte_val))
                if [ "$byte_val_dec" -ge 32 ] && [ "$byte_val_dec" -lt 127 ]; then
                    char=$(printf "\\$(printf "%03o" $byte_val_dec)")
                    line_with_addr="$line_with_addr  ; '$char' (数据)"
                elif [ "$byte_val_dec" -eq 0 ]; then
                    line_with_addr="$line_with_addr  ; 字符串结束符 (数据)"
                fi
            fi
            
            echo "$line_with_addr"
        else
            # 其他行（如空行、注释等）直接输出
            echo "$line"
        fi
    done
fi

echo -e "\n======================================================================"
echo "验证总结:"
echo "======================================================================"
echo -e "${GREEN}✅ 文件大小: 512 字节${NC}"
echo -e "${GREEN}✅ 引导扇区签名: 0xAA55${NC}"
echo -e "${GREEN}✅ 文件内容对应内存地址 0x7C00-0x7DFF${NC}"
echo -e "\n当 BIOS 加载此引导扇区到内存地址 0x7C00 时，"
echo "文件内容将完全对应内存中的代码。"
echo -e "\n提示: 使用 'objdump -D -b binary -m i8086 -M intel $BOOT_FILE' 查看完整反汇编"
echo "     或查看 BOOT_SECTOR_ANALYSIS.md 了解手工分析方法"

exit 0
