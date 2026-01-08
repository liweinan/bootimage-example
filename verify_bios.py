#!/usr/bin/env python3
"""
BIOS.bin 固定地址验证脚本

基于 bios_verification_report.md 生成的自动化验证脚本
用于验证 BIOS ROM 文件中的关键固定地址是否正确
"""

import sys
import os
from pathlib import Path

# BIOS 配置
BIOS_BASE = 0xF0000
BIOS_SIZE = 64 * 1024  # 64KB
FILE_PATH = '/Users/weli/works/qemu/pc-bios/bios.bin'

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


def verify_address(name, phys_addr, expected_bytes=None, description=""):
    """验证指定地址的内容"""
    file_offset = phys_to_file_offset(phys_addr)
    
    print(f"\n{'='*70}")
    print(f"{name} ({description})")
    print(f"{'='*70}")
    print(f"物理地址: 0x{phys_addr:05X}")
    print(f"ROM 偏移: 0x{phys_addr - BIOS_BASE:04X}")
    print(f"文件偏移: 0x{file_offset:05X}")
    
    try:
        with open(FILE_PATH, 'rb') as f:
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
        print(f"❌ 错误: 文件不存在: {FILE_PATH}")
        return False
    except Exception as e:
        print(f"❌ 错误: {e}")
        return False


def check_file_info():
    """检查文件基本信息"""
    print(f"\n{'='*70}")
    print("文件信息")
    print(f"{'='*70}")
    
    if not os.path.exists(FILE_PATH):
        print(f"❌ 文件不存在: {FILE_PATH}")
        return False
    
    file_size = os.path.getsize(FILE_PATH)
    print(f"文件路径: {FILE_PATH}")
    print(f"文件大小: {file_size} 字节 ({file_size // 1024}KB)")
    print(f"BIOS ROM 映射: 物理地址 0x{BIOS_BASE:05X}-0x{BIOS_BASE + BIOS_SIZE - 1:05X} ({BIOS_SIZE // 1024}KB)")
    
    if file_size != 128 * 1024:
        print(f"⚠️  警告: 文件大小不是 128KB，可能影响地址映射")
    
    return True


def analyze_reset_vector():
    """详细分析 Reset Vector"""
    print(f"\n{'='*70}")
    print("Reset Vector 详细分析")
    print(f"{'='*70}")
    
    file_offset = phys_to_file_offset(0xFFFF0)
    
    try:
        with open(FILE_PATH, 'rb') as f:
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


def find_0xff_padding():
    """查找文件中的 0xFF 填充区域"""
    print(f"\n{'='*70}")
    print("0xFF 填充区域分析")
    print(f"{'='*70}")
    
    try:
        with open(FILE_PATH, 'rb') as f:
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


def main():
    """主函数"""
    print("="*70)
    print("BIOS.bin 固定地址验证脚本")
    print("="*70)
    print(f"基于 bios_verification_report.md 生成")
    print(f"验证文件: {FILE_PATH}")
    
    # 检查文件
    if not check_file_info():
        sys.exit(1)
    
    # 验证所有关键地址
    results = []
    for name, info in KEY_ADDRESSES.items():
        result = verify_address(
            name,
            info['phys'],
            info['expected'],
            info['description']
        )
        results.append((name, result))
    
    # 详细分析 Reset Vector
    reset_result = analyze_reset_vector()
    
    # 查找 0xFF 填充
    find_0xff_padding()
    
    # 总结
    print(f"\n{'='*70}")
    print("验证总结")
    print(f"{'='*70}")
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    print(f"关键地址验证: {passed}/{total} 通过")
    print(f"Reset Vector 分析: {'✅ 通过' if reset_result else '❌ 失败'}")
    
    if passed == total and reset_result:
        print("\n✅ 所有验证通过！")
        return 0
    else:
        print("\n⚠️  部分验证未通过，请检查详细信息")
        return 1


if __name__ == '__main__':
    sys.exit(main())

