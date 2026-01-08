#!/usr/bin/env python3
"""
BIOS.bin 文件结构详细分析

分析 128KB BIOS 文件的两个 64KB 块的内容和用途
"""

import sys

FILE_PATH = '/Users/weli/works/qemu/pc-bios/bios.bin'
BIOS_BASE = 0xF0000

def analyze_first_block():
    """分析第一个 64KB 块"""
    print("="*70)
    print("第一个 64KB 块分析（文件偏移 0x00000-0x0FFFF）")
    print("="*70)
    
    with open(FILE_PATH, 'rb') as f:
        first_block = f.read(64 * 1024)
    
    # 统计
    zero_count = sum(1 for b in first_block if b == 0x00)
    ff_count = sum(1 for b in first_block if b == 0xFF)
    other_count = len(first_block) - zero_count - ff_count
    
    print(f"\n字节统计:")
    print(f"  0x00 字节: {zero_count} ({zero_count*100//len(first_block):.1f}%)")
    print(f"  0xFF 字节: {ff_count} ({ff_count*100//len(first_block):.1f}%)")
    print(f"  其他字节: {other_count} ({other_count*100//len(first_block):.1f}%)")
    
    # 查找第一个非零区域
    first_nonzero = None
    for i, b in enumerate(first_block):
        if b != 0x00:
            first_nonzero = i
            break
    
    if first_nonzero is not None:
        print(f"\n第一个非零字节位置: 0x{first_nonzero:05x}")
        
        # 分析 0x8260 附近的数据
        print(f"\n0x8260 附近的数据分析（可能是符号表或重定位表）:")
        addr_table_start = 0x8260
        addr_table_end = min(0x8260 + 512, len(first_block))
        
        print(f"  位置: 0x{addr_table_start:05x} - 0x{addr_table_end:05x}")
        print(f"  内容: 32 位小端序地址值")
        print(f"  示例值:")
        
        for i in range(addr_table_start, min(addr_table_start + 64, addr_table_end), 4):
            if i + 3 < len(first_block):
                addr = (first_block[i] | 
                       (first_block[i+1] << 8) | 
                       (first_block[i+2] << 16) | 
                       (first_block[i+3] << 24))
                print(f"    0x{i:05x}: 0x{addr:08x} (可能是偏移地址)")
        
        print(f"\n  分析:")
        print(f"    - 这些地址值都很小（< 0x10000），可能是相对于 BIOS 基址的偏移")
        print(f"    - 可能是链接器生成的符号表或重定位表")
        print(f"    - 或者用于调试/反汇编的元数据")
    
    # 查找数据区域
    data_regions = []
    in_data = False
    start = None
    
    for i in range(len(first_block)):
        if first_block[i] != 0x00 and first_block[i] != 0xFF:
            if not in_data:
                start = i
                in_data = True
        else:
            if in_data:
                length = i - start
                if length >= 16:
                    data_regions.append((start, length))
                in_data = False
    
    if data_regions:
        print(f"\n找到 {len(data_regions)} 个数据区域（非 0x00/0xFF，长度 >= 16 字节）:")
        for i, (start, length) in enumerate(data_regions[:5], 1):  # 只显示前5个
            print(f"  区域 {i}: 0x{start:05x} - 0x{start+length-1:05x} ({length} 字节)")
        if len(data_regions) > 5:
            print(f"  ... 还有 {len(data_regions) - 5} 个区域")


def analyze_second_block():
    """分析第二个 64KB 块（实际 BIOS ROM）"""
    print("\n" + "="*70)
    print("第二个 64KB 块分析（文件偏移 0x10000-0x1FFFF，实际 BIOS ROM）")
    print("="*70)
    
    with open(FILE_PATH, 'rb') as f:
        f.seek(64 * 1024)
        second_block = f.read(64 * 1024)
    
    # 统计
    zero_count = sum(1 for b in second_block if b == 0x00)
    ff_count = sum(1 for b in second_block if b == 0xFF)
    other_count = len(second_block) - zero_count - ff_count
    
    print(f"\n字节统计:")
    print(f"  0x00 字节: {zero_count} ({zero_count*100//len(second_block):.1f}%)")
    print(f"  0xFF 字节: {ff_count} ({ff_count*100//len(second_block):.1f}%)")
    print(f"  其他字节: {other_count} ({other_count*100//len(second_block):.1f}%)")
    
    # 分析关键地址
    print(f"\n关键地址验证:")
    key_addresses = {
        'entry_post': 0xE05B,
        'entry_02': 0xE2C3,
        'entry_13': 0xE3FE,
        'entry_19': 0xE6F2,
        'entry_10': 0xF065,
        'entry_16': 0xF82E,
        'reset_vector': 0xFFF0,
    }
    
    for name, offset in key_addresses.items():
        if offset < len(second_block):
            data = second_block[offset:offset+4]
            hex_str = ' '.join(f'{b:02x}' for b in data)
            print(f"  {name:20} (ROM偏移 0x{offset:04x}): {hex_str}")
    
    # Reset vector 详细分析
    reset_offset = 0xFFF0
    if reset_offset < len(second_block):
        reset_data = second_block[reset_offset:reset_offset+16]
        print(f"\nReset Vector 详细分析 (ROM偏移 0x{reset_offset:04x}):")
        print(f"  字节序列: {' '.join(f'{b:02x}' for b in reset_data[:5])}")
        
        if reset_data[0] == 0xea:
            offset = reset_data[1] | (reset_data[2] << 8)
            segment = reset_data[3] | (reset_data[4] << 8)
            target = segment * 16 + offset
            print(f"  解析: Far jump to 0x{segment:04x}:0x{offset:04x} = 物理地址 0x{target:05x}")
        
        # 日期字符串
        date_bytes = reset_data[5:13]
        date_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in date_bytes)
        print(f"  BIOS 日期: {date_str}")
        
        # 型号 ID
        model_id = second_block[0xFFFF] if len(second_block) > 0xFFFF else 0
        print(f"  型号 ID (0xFFFF): 0x{model_id:02x}")


def compare_blocks():
    """对比两个块的内容"""
    print("\n" + "="*70)
    print("两个 64KB 块对比")
    print("="*70)
    
    with open(FILE_PATH, 'rb') as f:
        first_block = f.read(64 * 1024)
        second_block = f.read(64 * 1024)
    
    print(f"\n第一个块 vs 第二个块:")
    print(f"  第一个块: 主要用于存储元数据（符号表、重定位表等）")
    print(f"     - 如果映射，应该映射到 0xE0000-0xEFFFF（硬件支持128KB映射）")
    print(f"     - 但内容主要是元数据，不是可执行的 BIOS 代码")
    print(f"  第二个块: 实际 BIOS ROM 代码（必须映射到 0xF0000-0xFFFFF）")
    print(f"     - 包含所有 BIOS 入口点（reset vector、entry_post等）")
    print(f"     - 这是 CPU 复位后执行的实际代码")
    
    # 检查是否第一个块是第二个块的镜像
    print(f"\n是否第一个块是第二个块的镜像？")
    if first_block == second_block:
        print(f"  ✅ 是，两个块完全相同")
    else:
        diff_count = sum(1 for i in range(len(first_block)) 
                        if first_block[i] != second_block[i])
        print(f"  ❌ 否，有 {diff_count} 个字节不同 ({diff_count*100//len(first_block):.1f}%)")
        print(f"  第一个块包含不同的内容（可能是元数据）")


def main():
    """主函数"""
    print("="*70)
    print("BIOS.bin 文件结构详细分析")
    print("="*70)
    print(f"文件: {FILE_PATH}")
    print(f"大小: 131072 字节 (128KB)")
    
    analyze_first_block()
    analyze_second_block()
    compare_blocks()
    
    print("\n" + "="*70)
    print("总结")
    print("="*70)
    print("""
1. 第一个 64KB 块（文件偏移 0x00000-0x0FFFF）:
   - 大部分是 0x00（填充）
   - 从 0x8260 开始包含数据（可能是符号表或重定位表）
   - 这些数据是链接器生成的元数据，用于调试或反汇编
   - **硬件支持映射到 0xE0000-0xEFFFF**（128KB映射区域的一部分）
   - 但内容主要是元数据，不是可执行的 BIOS 代码

2. 第二个 64KB 块（文件偏移 0x10000-0x1FFFF）:
   - 实际 BIOS ROM 代码
   - **必须映射到物理地址 0xF0000-0xFFFFF**（包含复位向量）
   - 包含所有 BIOS 入口点和代码
   - 使用率很高（96.5% 有效代码）

3. 为什么文件是 128KB？
   - QEMU 的 BIOS 文件格式包含两个 64KB 块
   - **硬件支持映射完整的128KB（0xE0000-0xFFFFF）**
   - 第一个块可能映射到 0xE0000-0xEFFFF（但主要是元数据）
   - 第二个块必须映射到 0xF0000-0xFFFFF（包含可执行代码）
   - 这种格式便于调试和分析

**重要纠正：**
- ❌ **错误**："硬件限制只允许映射64KB"
- ✅ **正确**：硬件支持映射完整的128KB（0xE0000-0xFFFFF）
- ✅ **最小要求**：高64KB（0xF0000-0xFFFFF）必须包含有效的 BIOS 代码
    """)


if __name__ == '__main__':
    main()

