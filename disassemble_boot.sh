#!/bin/bash
# 生成 boot.bin 的 Intel 格式反汇编

BOOT_FILE="${1:-boot.bin}"

if [ ! -f "$BOOT_FILE" ]; then
    echo "错误: 文件 $BOOT_FILE 不存在"
    echo "用法: $0 [boot.bin]"
    exit 1
fi

echo "=" | head -c 70; echo
echo "Intel 格式反汇编: $BOOT_FILE"
echo "内存地址映射: 文件偏移 + 0x7C00"
echo "=" | head -c 70; echo
echo ""

# 使用 objdump 生成 Intel 格式反汇编
objdump -D -b binary -m i8086 -M intel "$BOOT_FILE" | \
    awk '
    /^[0-9a-f]+ <\.data>:/ {
        print $0
        next
    }
    /^[[:space:]]*[0-9a-f]+:/ {
        # 提取文件偏移地址
        match($0, /^[[:space:]]*([0-9a-f]+):/, addr)
        if (addr[1] != "") {
            # 转换为十六进制并计算内存地址
            file_offset = strtonum("0x" addr[1])
            mem_addr = file_offset + 0x7C00
            # 替换地址显示
            gsub(/^[[:space:]]*[0-9a-f]+:/, sprintf("  0x%04X:", mem_addr))
        }
        print $0
    }
    !/^[[:space:]]*[0-9a-f]+:/ {
        print $0
    }
    '

echo ""
echo "=" | head -c 70; echo
echo "说明:"
echo "  - 左侧地址为内存地址 (0x7C00 + 文件偏移)"
echo "  - 使用 Intel 语法格式"
echo "  - 查看 BOOT_SECTOR_ANALYSIS.md 了解详细分析"
echo "=" | head -c 70; echo
