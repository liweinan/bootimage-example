#!/usr/bin/env python3
"""
手动解压 GRUB core.img 中的 LZMA 压缩数据

GRUB 使用的 LZMA 格式省略了标准 LZMA 流的 13 字节头部。
需要手动添加头部才能使用标准工具解压。
"""

import sys
import os
import struct
import subprocess

def add_lzma_header(compressed_data):
    """
    为 GRUB 的 LZMA 数据添加标准 LZMA 流头部
    
    GRUB 的 LZMA 格式省略了标准头部，需要添加：
    - 5 字节属性（固定值：5D 00 00 01 00）
    - 8 字节未压缩大小（小端序，64位）
    """
    
    # 标准 LZMA 流头部格式：
    # - 属性字节：5D (lc=3, lp=0, pb=2)
    # - 字典大小：00 00 01 00 (65536 字节，小端序)
    # - 未压缩大小：8 字节，小端序（我们不知道确切大小，使用 0xFFFFFFFFFFFFFFFF 表示未知）
    
    # 方法 1：使用固定头部（未知未压缩大小）
    # 属性：5D (lc=3, lp=0, pb=2)
    # 字典大小：00 00 01 00 (65536 字节)
    # 未压缩大小：FF FF FF FF FF FF FF FF (未知)
    header1 = bytes([0x5D, 0x00, 0x00, 0x01, 0x00]) + b'\xFF' * 8
    
    # 方法 2：尝试不同的属性值
    # 常见的 LZMA 属性：5D 00 00 00 01
    header2 = bytes([0x5D, 0x00, 0x00, 0x00, 0x01]) + b'\xFF' * 8
    
    return header1, header2

def decompress_with_xz(data_with_header, output_file):
    """使用 xz 工具解压 LZMA 数据"""
    
    try:
        # 写入临时文件
        temp_file = output_file + '.lzma'
        with open(temp_file, 'wb') as f:
            f.write(data_with_header)
        
        # 使用 xz 解压
        result = subprocess.run(
            ['xz', '--format=lzma', '--decompress', '--stdout', temp_file],
            capture_output=True,
            check=True
        )
        
        # 保存解压结果
        with open(output_file, 'wb') as f:
            f.write(result.stdout)
        
        os.remove(temp_file)
        return True, len(result.stdout)
        
    except subprocess.CalledProcessError as e:
        if os.path.exists(temp_file):
            os.remove(temp_file)
        return False, str(e)
    except FileNotFoundError:
        return False, "xz 工具未找到，请安装 xz-utils"

def main():
    """主函数"""
    
    compressed_file = 'compressed_part.bin'
    
    if len(sys.argv) > 1:
        compressed_file = sys.argv[1]
    
    if not os.path.exists(compressed_file):
        print(f"错误: 文件 {compressed_file} 不存在")
        print(f"提示: 先运行 extract_and_decompress_core_img.py 提取压缩部分")
        return 1
    
    print("="*70)
    print(f"解压 GRUB LZMA 数据: {compressed_file}")
    print("="*70)
    
    # 读取压缩数据
    with open(compressed_file, 'rb') as f:
        compressed_data = f.read()
    
    print(f"压缩数据大小: {len(compressed_data)} 字节 ({len(compressed_data)/1024:.1f} KB)")
    
    # 添加 LZMA 头部
    print("\n添加 LZMA 标准流头部...")
    header1, header2 = add_lzma_header(compressed_data)
    
    print(f"方法 1 头部: {header1.hex()}")
    print(f"方法 2 头部: {header2.hex()}")
    
    # 尝试方法 1
    print("\n" + "="*70)
    print("尝试方法 1: 标准 LZMA 头部 (5D 00 00 01 00)")
    print("="*70)
    
    data_with_header1 = header1 + compressed_data
    output_file1 = 'decompressed_part_method1.bin'
    
    success1, result1 = decompress_with_xz(data_with_header1, output_file1)
    
    if success1:
        print(f"✅ 解压成功!")
        print(f"   输出文件: {output_file1}")
        print(f"   解压后大小: {result1} 字节 ({result1/1024:.1f} KB)")
        print(f"   压缩比: {len(compressed_data)/result1:.2f}:1")
        
        # 验证解压结果
        print("\n验证解压结果:")
        with open(output_file1, 'rb') as f:
            decompressed = f.read(min(1024, result1))
        
        # 检查是否包含可读字符串
        try:
            strings = decompressed.decode('ascii', errors='ignore')
            readable = ''.join(c if 32 <= ord(c) < 127 else '.' for c in strings[:200])
            print(f"   前 200 字节（ASCII）: {readable[:100]}...")
        except:
            pass
        
        # 检查是否包含 x86 指令模式
        # 常见的 x86 指令：55 (push ebp), 89 E5 (mov ebp, esp), E8 (call)
        common_instructions = [0x55, 0x89, 0xE8, 0x8B, 0x83, 0xC3]
        instruction_count = sum(1 for b in decompressed[:200] if b in common_instructions)
        print(f"   前 200 字节中常见 x86 指令数量: {instruction_count}/200 ({instruction_count/2:.1f}%)")
        
        if instruction_count > 10:
            print("   ✅ 看起来像有效的 x86 代码")
        else:
            print("   ⚠️  可能不是有效的代码")
    else:
        print(f"❌ 解压失败: {result1}")
    
    # 尝试方法 2
    print("\n" + "="*70)
    print("尝试方法 2: 替代 LZMA 头部 (5D 00 00 00 01)")
    print("="*70)
    
    data_with_header2 = header2 + compressed_data
    output_file2 = 'decompressed_part_method2.bin'
    
    success2, result2 = decompress_with_xz(data_with_header2, output_file2)
    
    if success2:
        print(f"✅ 解压成功!")
        print(f"   输出文件: {output_file2}")
        print(f"   解压后大小: {result2} 字节 ({result2/1024:.1f} KB)")
        print(f"   压缩比: {len(compressed_data)/result2:.2f}:1")
        
        # 验证解压结果
        print("\n验证解压结果:")
        with open(output_file2, 'rb') as f:
            decompressed = f.read(min(1024, result2))
        
        # 检查是否包含可读字符串
        try:
            strings = decompressed.decode('ascii', errors='ignore')
            readable = ''.join(c if 32 <= ord(c) < 127 else '.' for c in strings[:200])
            print(f"   前 200 字节（ASCII）: {readable[:100]}...")
        except:
            pass
        
        # 检查是否包含 x86 指令模式
        common_instructions = [0x55, 0x89, 0xE8, 0x8B, 0x83, 0xC3]
        instruction_count = sum(1 for b in decompressed[:200] if b in common_instructions)
        print(f"   前 200 字节中常见 x86 指令数量: {instruction_count}/200 ({instruction_count/2:.1f}%)")
        
        if instruction_count > 10:
            print("   ✅ 看起来像有效的 x86 代码")
        else:
            print("   ⚠️  可能不是有效的代码")
    else:
        print(f"❌ 解压失败: {result2}")
    
    # 总结
    print("\n" + "="*70)
    print("总结")
    print("="*70)
    
    if success1 or success2:
        print("✅ 至少一种方法成功解压")
        if success1:
            print(f"   推荐使用: {output_file1}")
        if success2:
            print(f"   或使用: {output_file2}")
        print("\n可以进一步分析解压后的文件:")
        print(f"   strings decompressed_part_method*.bin | grep -i grub")
        print(f"   objdump -D -b binary -m i386 decompressed_part_method*.bin | less")
    else:
        print("❌ 所有方法都失败")
        print("\n可能的原因:")
        print("1. GRUB 使用的 LZMA 格式与标准格式差异较大")
        print("2. 需要知道确切的未压缩大小")
        print("3. 可能需要使用 GRUB 特定的解压器")
        print("\n建议:")
        print("- 查看 GRUB 源代码中的 LZMA 解压实现")
        print("- 使用 QEMU + GDB 在实际运行环境中查看解压后的代码")
    
    return 0 if (success1 or success2) else 1

if __name__ == '__main__':
    sys.exit(main())
