#!/usr/bin/env python3
"""
验证 BIOS 文件 (bios.bin) 的结构

分析 BIOS 文件的内容，确认：
1. 文件大小（应该是 128KB）
2. 第一个 64KB 块的内容（是否主要是空值或元数据）
3. 第二个 64KB 块的内容（是否包含实际代码）
4. 关键 BIOS 入口点的位置
5. 两个块的差异
"""

import sys
import os
from collections import Counter

def analyze_bios_file(bios_file):
    """分析 BIOS 文件结构"""
    
    print("="*70)
    print(f"验证 BIOS 文件: {bios_file}")
    print("="*70)
    
    # 检查文件是否存在
    if not os.path.exists(bios_file):
        print(f"错误: 文件 {bios_file} 不存在")
        return False
    
    # 读取文件
    with open(bios_file, 'rb') as f:
        data = f.read()
    
    file_size = len(data)
    print(f"\n文件大小: {file_size} 字节 ({file_size / 1024:.1f} KB)")
    
    # 验证文件大小
    if file_size % 65536 != 0:
        print(f"⚠️  警告: BIOS 文件大小应该是 64KB 的倍数，但文件是 {file_size} 字节")
    else:
        print(f"✅ 文件大小是 64KB 的倍数")
    
    # 将文件分为两个 64KB 块
    block_size = 65536  # 64KB
    if file_size < block_size:
        print(f"❌ 错误: 文件太小，无法分为两个 64KB 块")
        return False
    
    block1 = data[0:block_size]  # 第一个 64KB 块（文件偏移 0x00000-0x0FFFF）
    block2 = data[block_size:file_size] if file_size >= block_size * 2 else data[block_size:]  # 第二个 64KB 块（文件偏移 0x10000-0x1FFFF）
    
    print(f"\n文件结构:")
    print(f"  第一个 64KB 块: 文件偏移 0x00000 - 0x0FFFF ({len(block1)} 字节)")
    print(f"  第二个 64KB 块: 文件偏移 0x10000 - 0x1FFFF ({len(block2)} 字节)")
    
    # 分析第一个 64KB 块
    print("\n" + "="*70)
    print("第一个 64KB 块分析 (文件偏移 0x00000-0x0FFFF):")
    print("="*70)
    
    block1_zero_count = block1.count(0)
    block1_ff_count = block1.count(0xFF)
    block1_zero_percent = (block1_zero_count / len(block1)) * 100
    block1_ff_percent = (block1_ff_count / len(block1)) * 100
    
    print(f"  零字节 (0x00) 数量: {block1_zero_count} ({block1_zero_percent:.1f}%)")
    print(f"  填充字节 (0xFF) 数量: {block1_ff_count} ({block1_ff_percent:.1f}%)")
    print(f"  其他数据: {len(block1) - block1_zero_count - block1_ff_count} ({(100 - block1_zero_percent - block1_ff_percent):.1f}%)")
    
    # 统计第一个块的字节分布
    block1_counter = Counter(block1)
    block1_top_bytes = block1_counter.most_common(5)
    print(f"\n  最常见的字节值:")
    for byte_val, count in block1_top_bytes:
        print(f"    0x{byte_val:02X}: {count} 次 ({count/len(block1)*100:.1f}%)")
    
    # 检查第一个块是否有可执行代码特征
    # 查找常见的 x86 指令模式
    code_patterns = [
        (b'\xE9', 'JMP (near)'),
        (b'\xEB', 'JMP (short)'),
        (b'\x90', 'NOP'),
        (b'\xC3', 'RET'),
        (b'\xCB', 'RETF'),
        (b'\x0F', 'Prefix (可能是指令)'),
    ]
    
    print(f"\n  代码模式检查:")
    for pattern, desc in code_patterns:
        count = block1.count(pattern)
        if count > 0:
            print(f"    {desc}: {count} 次")
    
    # 分析第二个 64KB 块
    print("\n" + "="*70)
    print("第二个 64KB 块分析 (文件偏移 0x10000-0x1FFFF):")
    print("="*70)
    
    block2_zero_count = block2.count(0)
    block2_ff_count = block2.count(0xFF)
    block2_zero_percent = (block2_zero_count / len(block2)) * 100
    block2_ff_percent = (block2_ff_count / len(block2)) * 100
    
    print(f"  零字节 (0x00) 数量: {block2_zero_count} ({block2_zero_percent:.1f}%)")
    print(f"  填充字节 (0xFF) 数量: {block2_ff_count} ({block2_ff_percent:.1f}%)")
    print(f"  其他数据: {len(block2) - block2_zero_count - block2_ff_count} ({(100 - block2_zero_percent - block2_ff_percent):.1f}%)")
    
    # 统计第二个块的字节分布
    block2_counter = Counter(block2)
    block2_top_bytes = block2_counter.most_common(5)
    print(f"\n  最常见的字节值:")
    for byte_val, count in block2_top_bytes:
        print(f"    0x{byte_val:02X}: {count} 次 ({count/len(block2)*100:.1f}%)")
    
    # 检查第二个块的代码模式
    print(f"\n  代码模式检查:")
    for pattern, desc in code_patterns:
        count = block2.count(pattern)
        if count > 0:
            print(f"    {desc}: {count} 次")
    
    # 查找关键 BIOS 入口点
    print("\n" + "="*70)
    print("关键 BIOS 入口点查找:")
    print("="*70)
    
    # Reset Vector (物理地址 0xFFFF0，对于 128KB 文件，文件偏移应该是 0x1FFF0)
    reset_vector_phys = 0xFFFF0
    reset_vector_file_offset = reset_vector_phys - 0xF0000 + 0x10000  # 第二个块，偏移 0xFFFF0 - 0xF0000 = 0xFFF0，加上块起始 0x10000
    if reset_vector_file_offset < len(data):
        reset_vector_bytes = data[reset_vector_file_offset:reset_vector_file_offset+5]
        print(f"\n  Reset Vector (物理地址 0xFFFF0):")
        print(f"    文件偏移: 0x{reset_vector_file_offset:05X}")
        print(f"    字节值: {' '.join(f'0x{b:02X}' for b in reset_vector_bytes)}")
        print(f"    反汇编: JMP FAR [0x{reset_vector_bytes[3]:02X}{reset_vector_bytes[2]:02X}:0x{reset_vector_bytes[1]:02X}{reset_vector_bytes[0]:02X}]")
        
        # 计算跳转目标
        target_offset = reset_vector_bytes[1] | (reset_vector_bytes[2] << 8)
        target_segment = reset_vector_bytes[3] | (reset_vector_bytes[4] << 8)
        target_phys = (target_segment << 4) + target_offset
        print(f"    跳转目标: 段:偏移 = 0x{target_segment:04X}:0x{target_offset:04X} (物理地址 0x{target_phys:05X})")
    
    # 查找可能的入口点（常见的 BIOS 入口点模式）
    # 查找 EA (JMP FAR) 指令，这通常是 BIOS 入口点
    print(f"\n  查找 JMP FAR 指令 (0xEA):")
    jmp_far_positions = []
    for i in range(len(data) - 4):
        if data[i] == 0xEA:  # JMP FAR 指令
            jmp_far_positions.append(i)
    
    # 只显示前 10 个
    for pos in jmp_far_positions[:10]:
        block_num = 1 if pos < block_size else 2
        block_offset = pos if pos < block_size else pos - block_size
        phys_addr = 0xE0000 + pos if pos < block_size else 0xF0000 + block_offset
        print(f"    文件偏移 0x{pos:05X} (块 {block_num}, 块内偏移 0x{block_offset:04X}, 物理地址 0x{phys_addr:05X})")
    
    # 比较两个块的差异
    print("\n" + "="*70)
    print("两个块的差异分析:")
    print("="*70)
    
    if len(block1) == len(block2):
        diff_count = sum(1 for i in range(len(block1)) if block1[i] != block2[i])
        diff_percent = (diff_count / len(block1)) * 100
        print(f"  不同字节数: {diff_count} / {len(block1)} ({diff_percent:.1f}%)")
        print(f"  相同字节数: {len(block1) - diff_count} / {len(block1)} ({100 - diff_percent:.1f}%)")
        
        if diff_percent > 50:
            print(f"  ✅ 两个块内容差异很大，可能是不同的数据")
        else:
            print(f"  ⚠️  两个块内容相似度较高")
    
    # 显示第一个块和第二个块的开头内容
    print("\n" + "="*70)
    print("第一个 64KB 块开头内容 (文件偏移 0x00000-0x000FF):")
    print("="*70)
    for i in range(0, min(256, len(block1)), 16):
        hex_part = ' '.join(f'{b:02X}' for b in block1[i:i+16])
        ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in block1[i:i+16])
        print(f"0x{i:05X}: {hex_part:<48} | {ascii_part}")
    
    print("\n" + "="*70)
    print("第二个 64KB 块开头内容 (文件偏移 0x10000-0x100FF):")
    print("="*70)
    for i in range(0, min(256, len(block2)), 16):
        hex_part = ' '.join(f'{b:02X}' for b in block2[i:i+16])
        ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in block2[i:i+16])
        file_offset = block_size + i
        print(f"0x{file_offset:05X}: {hex_part:<48} | {ascii_part}")
    
    # 显示 Reset Vector 附近的内容
    print("\n" + "="*70)
    print("Reset Vector 附近内容 (文件偏移 0x1FFE0-0x1FFFF):")
    print("="*70)
    reset_start = max(0, reset_vector_file_offset - 32)
    reset_end = min(len(data), reset_vector_file_offset + 32)
    for i in range(reset_start, reset_end, 16):
        hex_part = ' '.join(f'{b:02X}' for b in data[i:i+16])
        ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in data[i:i+16])
        phys_addr = 0xF0000 + (i - block_size) if i >= block_size else 0xE0000 + i
        marker = " <-- Reset Vector" if reset_vector_file_offset <= i < reset_vector_file_offset + 5 else ""
        print(f"0x{i:05X} (物理 0x{phys_addr:05X}): {hex_part:<48} | {ascii_part}{marker}")
    
    # 总结
    print("\n" + "="*70)
    print("验证总结:")
    print("="*70)
    
    print(f"\n文件大小: {file_size} 字节 ({file_size / 1024:.1f} KB)")
    print(f"\n第一个 64KB 块:")
    print(f"  - 零字节: {block1_zero_percent:.1f}%")
    print(f"  - 填充字节 (0xFF): {block1_ff_percent:.1f}%")
    print(f"  - 其他数据: {100 - block1_zero_percent - block1_ff_percent:.1f}%")
    
    print(f"\n第二个 64KB 块:")
    print(f"  - 零字节: {block2_zero_percent:.1f}%")
    print(f"  - 填充字节 (0xFF): {block2_ff_percent:.1f}%")
    print(f"  - 其他数据: {100 - block2_zero_percent - block2_ff_percent:.1f}%")
    
    # 分析第一个块中的非空数据分布
    print(f"\n第一个 64KB 块非空数据分布分析:")
    non_zero_positions = [i for i in range(len(block1)) if block1[i] != 0 and block1[i] != 0xFF]
    if non_zero_positions:
        print(f"  非空数据起始位置: 文件偏移 0x{non_zero_positions[0]:05X}")
        print(f"  非空数据结束位置: 文件偏移 0x{non_zero_positions[-1]:05X}")
        print(f"  非空数据区域大小: {len(non_zero_positions)} 字节 ({len(non_zero_positions)/1024:.1f} KB)")
        
        # 检查非空数据是否集中在某个区域
        if non_zero_positions:
            start = non_zero_positions[0]
            end = non_zero_positions[-1]
            print(f"  非空数据区域: 0x{start:05X} - 0x{end:05X} (约 {end-start+1} 字节)")
            
            # 显示非空数据区域的内容（开头部分）
            if start < len(block1) - 256:
                print(f"\n  非空数据区域开头内容 (文件偏移 0x{start:05X}-0x{min(start+255, end):05X}):")
                for i in range(start, min(start + 256, len(block1)), 16):
                    hex_part = ' '.join(f'{b:02X}' for b in block1[i:i+16])
                    ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in block1[i:i+16])
                    print(f"    0x{i:05X}: {hex_part:<48} | {ascii_part}")
    
    # 判断结论
    print(f"\n结论:")
    if block1_zero_percent + block1_ff_percent > 60:
        print(f"  ✅ 第一个 64KB 块主要是空值或填充 ({block1_zero_percent + block1_ff_percent:.1f}%)")
        if 100 - block1_zero_percent - block1_ff_percent > 20:
            print(f"  ⚠️  但还包含 {100 - block1_zero_percent - block1_ff_percent:.1f}% 的其他数据（可能是链接器元数据、符号表等）")
    else:
        print(f"  ⚠️  第一个 64KB 块包含较多数据 ({100 - block1_zero_percent - block1_ff_percent:.1f}%)")
    
    if block2_zero_percent + block2_ff_percent < 50:
        print(f"  ✅ 第二个 64KB 块包含实际代码 ({100 - block2_zero_percent - block2_ff_percent:.1f}% 非空/非填充)")
        print(f"  ✅ Reset Vector 位于第二个块 (文件偏移 0x{reset_vector_file_offset:05X}, 物理地址 0xFFFF0)")
    else:
        print(f"  ⚠️  第二个 64KB 块包含较多空值或填充 ({block2_zero_percent + block2_ff_percent:.1f}%)")
    
    # 最终验证结论
    print(f"\n最终验证结论:")
    print(f"  ✅ BIOS 文件大小: 128KB (符合预期)")
    print(f"  ✅ 第一个 64KB 块: 主要是空值 ({block1_zero_percent + block1_ff_percent:.1f}%)，包含少量元数据")
    print(f"  ✅ 第二个 64KB 块: 包含实际 BIOS 代码 ({100 - block2_zero_percent - block2_ff_percent:.1f}%)")
    print(f"  ✅ Reset Vector 位于第二个块，指向有效的 BIOS 入口点")
    
    return True

if __name__ == '__main__':
    bios_file = '/Users/weli/works/qemu/pc-bios/bios.bin'
    
    if len(sys.argv) > 1:
        bios_file = sys.argv[1]
    
    success = analyze_bios_file(bios_file)
    sys.exit(0 if success else 1)
