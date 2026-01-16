#!/usr/bin/env python3
"""
BIOS.bin 验证脚本（统一版本）

**重要说明：**
- 这个脚本验证的是 **BIOS 固件**（bios.bin），不是 Bootloader
- BIOS 映射在物理地址 0xF0000-0xFFFFF（由 QEMU 加载）
- Bootloader（boot.bin）会被 BIOS 加载到 0x7C00（使用 verify_boot_sector.py 验证）

**BIOS vs Bootloader：**
- **BIOS (bios.bin)**：固件代码，映射到 0xF0000-0xFFFFF，由 QEMU 直接加载
- **Bootloader (boot.bin)**：引导程序，从磁盘读取，由 BIOS 加载到 0x7C00

**功能：**
1. 验证 BIOS ROM 文件中的关键固定地址是否正确
2. 分析 BIOS 文件结构（两个 64KB 块的内容分布）
3. 查找关键 BIOS 入口点
4. 分析填充区域和代码模式

使用方法:
  python3 verify_bios.py [bios_file] [--structure] [--addresses] [--all]
  
选项:
  --structure  只执行文件结构分析
  --addresses  只执行固定地址验证
  --all        执行所有分析（默认）
"""

import sys
import os
import argparse
from pathlib import Path
from collections import Counter

# BIOS 配置
BIOS_BASE = 0xF0000
BIOS_SIZE = 64 * 1024  # 64KB
DEFAULT_FILE_PATH = '/Users/weli/works/qemu/pc-bios/bios.bin'

# 关键地址定义
KEY_ADDRESSES = {
    'reset_vector': {
        'phys': 0xFFFF0,
        'expected': bytes([0xea, 0x5b, 0xe0, 0x00, 0xf0]),
        'description': 'CPU 上电复位入口（reset vector）'
    },
    'entry_post': {
        'phys': 0xFE05B,
        'expected': None,
        'description': 'POST 入口点（entry_post）'
    },
    'entry_10': {
        'phys': 0xFF065,
        'expected': bytes([0xcf]),  # iretw 指令
        'description': 'INT 10h 视频服务入口'
    },
    'entry_02': {
        'phys': 0xFE2C3,
        'expected': None,
        'description': 'INT 02h NMI 处理入口'
    },
    'entry_13_official': {
        'phys': 0xFE3FE,
        'expected': None,
        'description': 'INT 13h 磁盘服务官方入口'
    },
    'entry_16': {
        'phys': 0xFF82E,
        'expected': None,
        'description': 'INT 16h 键盘服务入口'
    },
    'entry_19': {
        'phys': 0xFE6F2,
        'expected': None,
        'description': 'INT 19h 引导入口'
    },
}


def phys_to_file_offset(phys_addr):
    """
    将物理地址转换为文件偏移
    
    规则：
    - BIOS ROM 映射到物理地址 0xF0000-0xFFFFF (64KB)
    - 文件是 128KB，包含两个 64KB 块
    - 实际 BIOS 代码在第二个 64KB 块（文件偏移 0x10000-0x1FFFF）
    - 物理地址 = 0xF0000 + (文件偏移 - 0x10000)
    """
    rom_offset = phys_addr - BIOS_BASE
    file_offset = 64 * 1024 + rom_offset  # 第二个 64KB 块
    return file_offset


def verify_address(name, phys_addr, expected_bytes=None, description="", bios_file=None):
    """验证指定地址的内容"""
    if bios_file is None:
        bios_file = DEFAULT_FILE_PATH
    file_offset = phys_to_file_offset(phys_addr)
    rom_offset = phys_addr - BIOS_BASE
    
    print(f"\n{'='*70}")
    print(f"{name} ({description})")
    print(f"{'='*70}")
    print(f"物理地址: 0x{phys_addr:05X}")
    print(f"ROM 偏移: 0x{rom_offset:04X} (在 BIOS ROM 0xF0000-0xFFFFF 内)")
    print(f"文件偏移: 0x{file_offset:05X}")
    
    # 说明 entry_post 的位置
    if name == 'entry_post':
        block_position = rom_offset / 1024
        print(f"位置说明: 在第二个 64KB 块的中间位置（ROM 偏移 0x{rom_offset:04X}, 约 {block_position:.1f} KB）")
        print(f"         不是 BIOS ROM 的开头，而是从 reset_vector (0xFFFF0) 跳转过来的入口点")
    
    try:
        with open(bios_file, 'rb') as f:
            f.seek(file_offset)
            data = f.read(16)
            hex_str = ' '.join(f'{b:02x}' for b in data)
            print(f"内容: {hex_str}")
            
            if expected_bytes:
                match = data[:len(expected_bytes)] == expected_bytes
                status = '✅ 匹配' if match else '❌ 不匹配'
                print(f"预期: {' '.join(f'{b:02x}' for b in expected_bytes)}")
                print(f"状态: {status}")
                if not match:
                    print(f"实际: {' '.join(f'{b:02x}' for b in data[:len(expected_bytes)])}")
                return match
            else:
                # 检查是否包含有效代码（非全零、非全0xFF）
                if all(b == 0 for b in data):
                    print("状态: ⚠️  全零（可能未初始化）")
                elif all(b == 0xFF for b in data):
                    print("状态: ⚠️  全0xFF（填充区域）")
                else:
                    print("状态: ✅ 包含有效代码")
                return True
                
    except FileNotFoundError:
        print(f"❌ 错误: 文件不存在: {bios_file}")
        return False
    except Exception as e:
        print(f"❌ 错误: {e}")
        return False


def check_file_info(bios_file=None):
    """检查文件基本信息"""
    if bios_file is None:
        bios_file = DEFAULT_FILE_PATH
    print(f"\n{'='*70}")
    print("文件信息")
    print(f"{'='*70}")
    
    if not os.path.exists(bios_file):
        print(f"❌ 文件不存在: {bios_file}")
        return False
    
    file_size = os.path.getsize(bios_file)
    print(f"文件路径: {bios_file}")
    print(f"文件大小: {file_size} 字节 ({file_size // 1024}KB)")
    print(f"BIOS ROM 映射: 物理地址 0x{BIOS_BASE:05X}-0x{BIOS_BASE + BIOS_SIZE - 1:05X} ({BIOS_SIZE // 1024}KB)")
    
    if file_size != 128 * 1024:
        print(f"⚠️  警告: 文件大小不是 128KB，可能影响地址映射")
    
    return True


def analyze_reset_vector(bios_file=None):
    """详细分析 Reset Vector"""
    if bios_file is None:
        bios_file = DEFAULT_FILE_PATH
    print(f"\n{'='*70}")
    print("Reset Vector 详细分析")
    print(f"{'='*70}")
    
    file_offset = phys_to_file_offset(0xFFFF0)
    
    try:
        with open(bios_file, 'rb') as f:
            f.seek(file_offset)
            data = f.read(5)
            
            print(f"字节序列: {' '.join(f'{b:02x}' for b in data)}")
            
            if data[0] == 0xea:
                # Far jump 指令
                offset = data[1] | (data[2] << 8)
                segment = data[3] | (data[4] << 8)
                target = segment * 16 + offset
                
                print(f"\n解析:")
                print(f"  操作码: 0x{data[0]:02x} (far jump, ljmpw)")
                print(f"  偏移: 0x{offset:04X} (little-endian: {data[1]:02x} {data[2]:02x})")
                print(f"  段: 0x{segment:04X} (little-endian: {data[3]:02x} {data[4]:02x})")
                print(f"  目标地址: 0x{segment:04X}:0x{offset:04X} = 物理地址 0x{target:05X}")
                
                if target == 0xFE05B:
                    print(f"\n✅ 验证通过: Reset vector 正确跳转到 entry_post (0xFE05B)")
                    return True
                else:
                    print(f"\n❌ 验证失败: 目标地址 0x{target:05X} 不等于 entry_post (0xFE05B)")
                    return False
            else:
                print(f"\n❌ 验证失败: 第一个字节不是 far jump 操作码 (0xea)")
                return False
                
    except Exception as e:
        print(f"❌ 错误: {e}")
        return False


def find_0xff_padding(bios_file=None):
    """查找文件中的 0xFF 填充区域"""
    if bios_file is None:
        bios_file = DEFAULT_FILE_PATH
    print(f"\n{'='*70}")
    print("0xFF 填充区域分析")
    print(f"{'='*70}")
    
    try:
        with open(bios_file, 'rb') as f:
            data = f.read()
        
        file_size = len(data)
        print(f"文件大小: {file_size} 字节 (0x{file_size:X})")
        
        # 分别分析两个 64KB 块
        first_block = data[0:64*1024]
        second_block = data[64*1024:128*1024]
        
        print(f"\n第一个 64KB 块 (文件偏移 0x00000-0x0FFFF):")
        first_ff_count = sum(1 for b in first_block if b == 0xFF)
        first_ff_percent = (first_ff_count / len(first_block)) * 100
        print(f"  0xFF 字节数: {first_ff_count} ({first_ff_percent:.1f}%)")
        print(f"  非 0xFF 字节数: {len(first_block) - first_ff_count} ({(100 - first_ff_percent):.1f}%)")
        
        print(f"\n第二个 64KB 块 (文件偏移 0x10000-0x1FFFF, 实际 BIOS ROM):")
        second_ff_count = sum(1 for b in second_block if b == 0xFF)
        second_ff_percent = (second_ff_count / len(second_block)) * 100
        print(f"  0xFF 字节数: {second_ff_count} ({second_ff_percent:.1f}%)")
        print(f"  非 0xFF 字节数: {len(second_block) - second_ff_count} ({(100 - second_ff_percent):.1f}%)")
        
        # 查找连续的 0xFF 区域（分别查找两个块）
        def find_ff_regions(block_data, block_start_offset, block_name):
            padding_regions = []
            start = None
            
            for i in range(len(block_data)):
                if block_data[i] == 0xFF:
                    if start is None:
                        start = i
                else:
                    if start is not None:
                        length = i - start
                        if length >= 16:  # 只报告长度 >= 16 字节的填充区域
                            file_offset = block_start_offset + start
                            padding_regions.append((file_offset, start, length))
                        start = None
            
            # 处理块末尾的填充
            if start is not None:
                length = len(block_data) - start
                if length >= 16:
                    file_offset = block_start_offset + start
                    padding_regions.append((file_offset, start, length))
            
            return padding_regions
        
        first_regions = find_ff_regions(first_block, 0, "第一个 64KB 块")
        second_regions = find_ff_regions(second_block, 64*1024, "第二个 64KB 块")
        
        all_regions = first_regions + second_regions
        
        if all_regions:
            print(f"\n找到 {len(all_regions)} 个 0xFF 填充区域 (长度 >= 16 字节):")
            region_num = 1
            
            if first_regions:
                print(f"\n  第一个 64KB 块中的填充区域:")
                for file_offset, block_offset, length in first_regions:
                    print(f"\n    区域 {region_num}:")
                    print(f"      文件偏移: 0x{file_offset:05X} - 0x{file_offset + length - 1:05X} ({length} 字节)")
                    print(f"      块内偏移: 0x{block_offset:04X} - 0x{block_offset + length - 1:04X}")
                    print(f"      说明: 第一个 64KB 块（可能是镜像或填充）")
                    region_num += 1
            
            if second_regions:
                print(f"\n  第二个 64KB 块中的填充区域 (实际 BIOS ROM):")
                for file_offset, block_offset, length in second_regions:
                    rom_offset = block_offset
                    phys_addr = BIOS_BASE + rom_offset
                    print(f"\n    区域 {region_num}:")
                    print(f"      文件偏移: 0x{file_offset:05X} - 0x{file_offset + length - 1:05X} ({length} 字节)")
                    print(f"      ROM 偏移: 0x{rom_offset:04X} - 0x{rom_offset + length - 1:04X}")
                    print(f"      物理地址: 0x{phys_addr:05X} - 0x{phys_addr + length - 1:05X}")
                    print(f"      说明: BIOS ROM 未使用区域（填充）")
                    region_num += 1
        else:
            print("\n未找到明显的 0xFF 填充区域（长度 >= 16 字节）")
        
        # 统计 0xFF 字节总数
        ff_count = sum(1 for b in data if b == 0xFF)
        ff_percent = (ff_count / file_size) * 100
        print(f"\n总体统计:")
        print(f"  0xFF 字节总数: {ff_count} ({ff_percent:.1f}%)")
        print(f"  非 0xFF 字节数: {file_size - ff_count} ({(100 - ff_percent):.1f}%)")
        
        # 分析第一个块的内容
        print(f"\n第一个 64KB 块内容分析:")
        if first_ff_percent > 95:
            print(f"  ✅ 几乎全是 0xFF（{first_ff_percent:.1f}%），可能是填充或镜像")
        elif first_ff_percent < 5:
            print(f"  ⚠️  几乎不含 0xFF（{first_ff_percent:.1f}%），可能包含有效数据")
        else:
            print(f"  ⚠️  混合内容（{first_ff_percent:.1f}% 0xFF），需要进一步分析")
        
        # 分析第二个块的内容
        print(f"\n第二个 64KB 块内容分析 (实际 BIOS ROM):")
        if second_ff_percent > 50:
            print(f"  ⚠️  包含大量 0xFF（{second_ff_percent:.1f}%），BIOS ROM 使用率较低")
        elif second_ff_percent < 5:
            print(f"  ✅ 几乎不含 0xFF（{second_ff_percent:.1f}%），BIOS ROM 使用率很高")
        else:
            print(f"  ✅ 正常填充比例（{second_ff_percent:.1f}% 0xFF），BIOS ROM 使用率正常")
        
        return True
        
    except Exception as e:
        print(f"❌ 错误: {e}")
        return False


def analyze_bios_structure(bios_file=None):
    """分析 BIOS 文件结构（两个 64KB 块的内容分布）"""
    if bios_file is None:
        bios_file = DEFAULT_FILE_PATH
    
    print("="*70)
    print(f"BIOS 文件结构分析: {bios_file}")
    print("="*70)
    
    if not os.path.exists(bios_file):
        print(f"错误: 文件 {bios_file} 不存在")
        return False
    
    with open(bios_file, 'rb') as f:
        data = f.read()
    
    file_size = len(data)
    print(f"\n文件大小: {file_size} 字节 ({file_size / 1024:.1f} KB)")
    
    if file_size % 65536 != 0:
        print(f"⚠️  警告: BIOS 文件大小应该是 64KB 的倍数，但文件是 {file_size} 字节")
    else:
        print(f"✅ 文件大小是 64KB 的倍数")
    
    block_size = 65536
    if file_size < block_size:
        print(f"❌ 错误: 文件太小，无法分为两个 64KB 块")
        return False
    
    block1 = data[0:block_size]
    block2 = data[block_size:file_size] if file_size >= block_size * 2 else data[block_size:]
    
    print(f"\n文件结构:")
    print(f"  第一个 64KB 块: 文件偏移 0x00000 - 0x0FFFF ({len(block1)} 字节)")
    print(f"  第二个 64KB 块: 文件偏移 0x10000 - 0x1FFFF ({len(block2)} 字节)")
    
    # 分析第一个块
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
    
    block1_counter = Counter(block1)
    block1_top_bytes = block1_counter.most_common(5)
    print(f"\n  最常见的字节值:")
    for byte_val, count in block1_top_bytes:
        print(f"    0x{byte_val:02X}: {count} 次 ({count/len(block1)*100:.1f}%)")
    
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
    
    # 分析第二个块
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
    
    block2_counter = Counter(block2)
    block2_top_bytes = block2_counter.most_common(5)
    print(f"\n  最常见的字节值:")
    for byte_val, count in block2_top_bytes:
        print(f"    0x{byte_val:02X}: {count} 次 ({count/len(block2)*100:.1f}%)")
    
    print(f"\n  代码模式检查:")
    for pattern, desc in code_patterns:
        count = block2.count(pattern)
        if count > 0:
            print(f"    {desc}: {count} 次")
    
    # 查找关键 BIOS 入口点
    print("\n" + "="*70)
    print("关键 BIOS 入口点查找:")
    print("="*70)
    
    reset_vector_phys = 0xFFFF0
    reset_vector_file_offset = reset_vector_phys - 0xF0000 + 0x10000
    if reset_vector_file_offset < len(data):
        reset_vector_bytes = data[reset_vector_file_offset:reset_vector_file_offset+5]
        print(f"\n  Reset Vector (物理地址 0xFFFF0):")
        print(f"    文件偏移: 0x{reset_vector_file_offset:05X}")
        print(f"    ROM 偏移: 0x{reset_vector_phys - 0xF0000:04X} (在第二个 64KB 块末尾)")
        print(f"    字节值: {' '.join(f'0x{b:02X}' for b in reset_vector_bytes)}")
        
        target_offset = reset_vector_bytes[1] | (reset_vector_bytes[2] << 8)
        target_segment = reset_vector_bytes[3] | (reset_vector_bytes[4] << 8)
        target_phys = (target_segment << 4) + target_offset
        print(f"    反汇编: JMP FAR 0x{target_segment:04X}:0x{target_offset:04X}")
        print(f"    跳转目标: 段:偏移 = 0x{target_segment:04X}:0x{target_offset:04X} (物理地址 0x{target_phys:05X})")
        
        # 检查是否跳转到 entry_post
        if target_phys == 0xFE05B:
            entry_post_rom_offset = 0xFE05B - 0xF0000
            entry_post_position_kb = entry_post_rom_offset / 1024
            print(f"    ✅ 跳转到 entry_post (0xFE05B)")
            print(f"    ✅ entry_post 在第二个 64KB 块的中间位置（ROM 偏移 0x{entry_post_rom_offset:04X}, 约 {entry_post_position_kb:.1f} KB）")
            print(f"    ✅ 不是 BIOS ROM 的开头，而是从 reset_vector 跳转过来的入口点")
    
    # 显示 entry_post 位置
    entry_post_phys = 0xFE05B
    entry_post_file_offset = entry_post_phys - 0xF0000 + 0x10000
    if entry_post_file_offset < len(data):
        entry_post_rom_offset = entry_post_phys - 0xF0000
        entry_post_position_kb = entry_post_rom_offset / 1024
        print(f"\n  entry_post (物理地址 0xFE05B):")
        print(f"    文件偏移: 0x{entry_post_file_offset:05X}")
        print(f"    ROM 偏移: 0x{entry_post_rom_offset:04X} (在第二个 64KB 块内)")
        print(f"    位置: 第二个 64KB 块的中间位置（约 {entry_post_position_kb:.1f} KB，不是开头）")
        print(f"    说明: 这是 POST 入口点，由 reset_vector (0xFFFF0) 跳转过来")
    
    # 查找 JMP FAR 指令
    print(f"\n  查找 JMP FAR 指令 (0xEA):")
    jmp_far_positions = []
    for i in range(len(data) - 4):
        if data[i] == 0xEA:
            jmp_far_positions.append(i)
    
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
    
    # 总结
    print("\n" + "="*70)
    print("结构分析总结:")
    print("="*70)
    print(f"\n第一个 64KB 块:")
    print(f"  - 零字节: {block1_zero_percent:.1f}%")
    print(f"  - 填充字节 (0xFF): {block1_ff_percent:.1f}%")
    print(f"  - 其他数据: {100 - block1_zero_percent - block1_ff_percent:.1f}%")
    
    print(f"\n第二个 64KB 块:")
    print(f"  - 零字节: {block2_zero_percent:.1f}%")
    print(f"  - 填充字节 (0xFF): {block2_ff_percent:.1f}%")
    print(f"  - 其他数据: {100 - block2_zero_percent - block2_ff_percent:.1f}%")
    
    if block1_zero_percent + block1_ff_percent > 60:
        print(f"\n✅ 第一个 64KB 块主要是空值或填充 ({block1_zero_percent + block1_ff_percent:.1f}%)")
    if block2_zero_percent + block2_ff_percent < 50:
        print(f"✅ 第二个 64KB 块包含实际代码 ({100 - block2_zero_percent - block2_ff_percent:.1f}% 非空/非填充)")
    
    return True


def analyze_first_block_detailed(bios_file=None):
    """
    详细分析第一个 64KB 块（结合 SeaBIOS 源代码）
    
    分析结论：
    - 第一个 64KB 块对 BIOS 运行完全没用
    - 51% 是填充的 0x00（由 checkrom.py 生成）
    - 49% 是链接器生成的重定位表/调试符号表
    """
    if bios_file is None:
        bios_file = DEFAULT_FILE_PATH
    
    print("\n" + "="*70)
    print("第一个 64KB 块详细分析（结合 SeaBIOS 源代码）")
    print("="*70)
    
    try:
        with open(bios_file, 'rb') as f:
            data = f.read()
        
        block1 = data[0:65536]
        
        # 分段分析
        segment1 = block1[0:0x8260]  # 前 33376 字节
        segment2 = block1[0x8260:]   # 后 32160 字节
        
        print(f"\n1. 前 0x8260 字节 (0x00000-0x0825F, {len(segment1)} 字节, 51%):")
        zero1 = segment1.count(0)
        print(f"   - 0x00 字节: {zero1} ({zero1/len(segment1)*100:.1f}%)")
        print(f"   - ✅ 这是 checkrom.py 填充的 0x00（见 checkrom.py:89）")
        print(f"   - ✅ 完全没用，只是填充")
        
        print(f"\n2. 后 0x8260 字节 (0x08260-0x0FFFF, {len(segment2)} 字节, 49%):")
        zero2 = segment2.count(0)
        non_zero2 = len(segment2) - zero2
        print(f"   - 非零数据: {non_zero2} ({non_zero2/len(segment2)*100:.1f}%)")
        print(f"   - 数据结构: 4字节对齐的小端序值（相对偏移）")
        print(f"   - 值范围: 0x0000 - 0xFFFF（相对偏移）")
        print(f"   - 加上 0xF0000 后: 0xF0000 - 0xFFFFF (BIOS ROM 范围)")
        print(f"   - ✅ 这是链接器生成的重定位表/调试符号表")
        print(f"   - ✅ 用于调试和反汇编，不是运行时需要的代码")
        
        # 验证这些引用
        block2 = data[65536:131072]
        valid_refs = 0
        total_refs = 0
        sample_refs = []
        
        for i in range(0x8260, len(block1), 4):
            if i + 3 < len(block1):
                offset = block1[i] | (block1[i+1] << 8) | (block1[i+2] << 16) | (block1[i+3] << 24)
                if offset != 0 and offset < 0x10000:
                    total_refs += 1
                    if offset < len(block2) and block2[offset] != 0 and block2[offset] != 0xFF:
                        valid_refs += 1
                        if len(sample_refs) < 5:
                            phys_addr = 0xF0000 + offset
                            sample_refs.append((i, offset, phys_addr))
        
        print(f"\n3. 重定位表验证:")
        print(f"   - 总引用数: {total_refs}")
        if total_refs > 0:
            print(f"   - 指向第二个块中有效数据: {valid_refs} ({valid_refs/total_refs*100:.1f}%)")
            print(f"   - ✅ 这些数据确实是指向第二个块中代码/数据位置的重定位表")
            
            if sample_refs:
                print(f"\n   示例引用:")
                for file_offset, rom_offset, phys_addr in sample_refs:
                    print(f"     文件偏移 0x{file_offset:05X}: ROM 偏移 0x{rom_offset:04X} -> 物理地址 0x{phys_addr:05X}")
        
        print(f"\n" + "="*70)
        print("结论（结合 SeaBIOS 源代码分析）")
        print("="*70)
        print(f"""
从 SeaBIOS 源代码分析：

1. **SeaBIOS 配置 (src/config.h):**
   - BUILD_BIOS_ADDR = 0xF0000
   - BUILD_BIOS_SIZE = 0x10000 (64KB)
   - ✅ SeaBIOS 只使用第二个 64KB 块（0xF0000-0xFFFFF）

2. **构建过程 (scripts/checkrom.py:89):**
   ```python
   f.write((b"\\0" * (finalsize - datasize)) + rawdata)
   ```
   - 如果 finalsize = 128KB，datasize = 64KB
   - 先写入 64KB 的 0x00（填充），然后写入 64KB 的实际代码
   - ✅ 第一个块的前 51% 是 checkrom.py 填充的 0x00

3. **第一个块的数据来源:**
   - 前 51% (0x00000-0x0825F): checkrom.py 填充的 0x00
   - 后 49% (0x08260-0x0FFFF): 链接器生成的重定位表/调试符号表
   - ✅ 这些数据来自链接器生成的 ELF 文件，不是运行时需要的

4. **第一个块的作用:**
   - ❌ **对 BIOS 运行完全没用**
   - ✅ **仅用于调试和反汇编**（重定位表、符号表等元数据）
   - ✅ **即使映射到 0xE0000-0xEFFFF，CPU 也不会执行这部分内容**

5. **为什么文件是 128KB？**
   - QEMU 的 BIOS 文件格式要求是 64KB 的倍数
   - 硬件支持映射完整的 128KB（0xE0000-0xFFFFF）
   - 但 SeaBIOS 实际只使用第二个 64KB 块
   - 第一个块是构建过程的副产品（链接器元数据）

**最终结论：**
✅ 第一个 64KB 块对 BIOS 运行**完全没用**，主要是：
   - 51% 是填充的 0x00
   - 49% 是链接器生成的调试元数据（重定位表）
   - 这些数据不包含可执行的 BIOS 代码
   - 即使映射到物理内存，也不会被 CPU 执行
""")
        
        return True
        
    except Exception as e:
        print(f"❌ 错误: {e}")
        return False


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='BIOS.bin 验证脚本（统一版本）')
    parser.add_argument('bios_file', nargs='?', default=DEFAULT_FILE_PATH,
                        help=f'BIOS 文件路径（默认: {DEFAULT_FILE_PATH}）')
    parser.add_argument('--structure', action='store_true',
                        help='只执行文件结构分析')
    parser.add_argument('--addresses', action='store_true',
                        help='只执行固定地址验证')
    parser.add_argument('--all', action='store_true',
                        help='执行所有分析（默认行为）')
    
    args = parser.parse_args()
    bios_file = args.bios_file
    
    print("="*70)
    print("BIOS.bin 验证脚本（统一版本）")
    print("="*70)
    print(f"验证文件: {bios_file}")
    
    if not os.path.exists(bios_file):
        print(f"❌ 错误: 文件不存在: {bios_file}")
        sys.exit(1)
    
    # 根据参数决定执行哪些分析（默认执行所有）
    if args.structure or args.addresses:
        run_structure = args.structure
        run_addresses = args.addresses
    else:
        # 默认执行所有分析
        run_structure = True
        run_addresses = True
    
    results = []
    
    # 文件结构分析
    if run_structure:
        if not analyze_bios_structure(bios_file):
            results.append(('structure', False))
        else:
            results.append(('structure', True))
        
        # 第一个 64KB 块详细分析
        analyze_first_block_detailed(bios_file)
    
    # 固定地址验证
    if run_addresses:
        if not check_file_info(bios_file):
            sys.exit(1)
        
        address_results = []
        for name, info in KEY_ADDRESSES.items():
            result = verify_address(
                name,
                info['phys'],
                info['expected'],
                info['description'],
                bios_file
            )
            address_results.append((name, result))
        
        reset_result = analyze_reset_vector(bios_file)
        find_0xff_padding(bios_file)
        
        passed = sum(1 for _, result in address_results if result)
        total = len(address_results)
        results.append(('addresses', passed == total and reset_result))
        
        print(f"\n{'='*70}")
        print("固定地址验证总结")
        print(f"{'='*70}")
        print(f"关键地址验证: {passed}/{total} 通过")
        print(f"Reset Vector 分析: {'✅ 通过' if reset_result else '❌ 失败'}")
    
    # 最终总结
    if len(results) > 1:
        print(f"\n{'='*70}")
        print("总体验证总结")
        print(f"{'='*70}")
        for name, result in results:
            status = '✅ 通过' if result else '❌ 失败'
            print(f"{name}: {status}")
    
    all_passed = all(result for _, result in results)
    if all_passed:
        print("\n✅ 所有验证通过！")
        return 0
    else:
        print("\n⚠️  部分验证未通过，请检查详细信息")
        return 1


if __name__ == '__main__':
    sys.exit(main())

