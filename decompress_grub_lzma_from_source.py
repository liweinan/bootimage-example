#!/usr/bin/env python3
"""
基于 GRUB 源代码的 LZMA 解压器

根据 GRUB 源代码中的 lzma_decode.S 实现：
- 使用固定的 LZMA 属性：LC=3, LP=0, PB=2
- 压缩数据没有标准 LZMA 流头部
- 需要知道未压缩大小

参考：
- grub/grub-core/boot/i386/pc/lzma_decode.S
- grub/grub-core/boot/i386/pc/startup_raw.S
"""

import sys
import os
import struct
import subprocess

# GRUB 使用的固定 LZMA 属性（来自 lzma_decode.S）
FIXED_LC = 3
FIXED_LP = 0
FIXED_PB = 2

def find_uncompressed_size(core_img):
    """
    在 core.img 的 startup_raw.S 区域查找 uncompressed_size
    
    根据 GRUB 源代码，uncompressed_size 存储在特定偏移处
    """
    if len(core_img) < 4096:
        return None
    
    # startup_raw.S 从 512 字节开始
    startup_raw = core_img[512:4096]
    
    # 查找可能的 uncompressed_size 值（4 字节，小端序）
    # 应该在合理的范围内（40-150 KB）
    candidates = []
    
    for i in range(0, len(startup_raw) - 4, 4):
        val = struct.unpack('<I', startup_raw[i:i+4])[0]
        if 40000 <= val <= 150000:  # 40KB - 150KB
            offset = i + 512
            candidates.append((offset, val))
    
    # 返回最可能的值（通常在 48-52 KB 范围内）
    likely_candidates = [c for c in candidates if 48000 <= c[1] <= 55000]
    if likely_candidates:
        # 返回第一个最可能的值
        return likely_candidates[0][1]
    
    # 如果没有找到，返回所有候选中最接近 50KB 的
    if candidates:
        candidates.sort(key=lambda x: abs(x[1] - 50000))
        return candidates[0][1]
    
    return None

def create_lzma_stream(compressed_data, uncompressed_size):
    """
    为 GRUB 的 LZMA 数据创建标准 LZMA 流格式
    
    GRUB 的压缩数据没有标准头部，需要添加：
    - 属性字节：LC=3, LP=0, PB=2
    - 字典大小：65536 字节 (0x00010000)
    - 未压缩大小：8 字节，小端序
    
    注意：GRUB 使用固定的 LZMA 属性（LC=3, LP=0, PB=2）
    标准 LZMA 属性字节格式：LC (5 bits) | LP (3 bits) | PB (5 bits)
    对于 LC=3, LP=0, PB=2: (3) | (0 << 5) | (2 << 8) = 0x0203
    但标准 LZMA 是单字节属性，所以需要计算正确的值
    """
    
    # 标准 LZMA 属性字节计算：
    # 属性字节 = LC | (LP << 5) | (PB << 8)
    # 但这是错误的，标准格式是：
    # 属性字节 = LC | (LP << 5) | (PB << 8)，但 PB 只有 4 位
    # 实际上：属性字节 = LC (5 bits) | LP (3 bits) | PB (5 bits)
    # 对于 LC=3, LP=0, PB=2: 
    #   属性 = 3 | (0 << 5) | (2 << 8) = 3 | 512 = 515 = 0x0203
    # 但这是 2 字节，标准 LZMA 是单字节
    # 实际上标准 LZMA 属性字节是：LC (5 bits) | LP (3 bits) | PB (5 bits)
    # 但 PB 只有 4 位有效，所以：属性 = LC | (LP << 5) | (PB << 8)
    # 对于 LC=3, LP=0, PB=2: 这需要特殊处理
    
    # 根据 LZMA 规范，属性字节是：
    # bits 0-4: lc (literal context bits)
    # bits 5-7: lp (literal position bits)  
    # bits 8-12: pb (position bits)
    # 但这是 13 bits，标准格式使用单字节，所以：
    # 属性字节 = lc | (lp << 5) | (pb << 8)
    # 但 pb 只有 4 位，所以实际是：lc | (lp << 5) | ((pb & 0xF) << 8)
    
    # 实际上，标准 LZMA 属性字节格式是：
    # 单字节：lc (5 bits) | lp (3 bits) | pb (5 bits)
    # 但 pb 只有 4 位有效，所以：lc | (lp << 5) | (pb << 8)
    # 这需要 2 字节，但标准格式是单字节
    
    # 让我查看实际的 LZMA 规范：
    # 标准 LZMA 属性字节是单字节：lc (5 bits) | lp (3 bits) | pb (5 bits)
    # 对于 LC=3, LP=0, PB=2:
    #   属性 = 3 | (0 << 5) | (2 << 8) = 3 | 512 = 515
    # 但这是错误的，因为单字节只能存储 0-255
    
    # 正确的计算应该是：
    # 属性字节 = lc | (lp << 5) | (pb << 8)
    # 但 pb 只有 4 位，所以：lc | (lp << 5) | ((pb & 0xF) << 8)
    # 对于 LC=3, LP=0, PB=2: 3 | 0 | (2 << 8) = 515，这需要 2 字节
    
    # 实际上，标准 LZMA 格式中，属性字节是单字节：
    # bits 0-4: lc
    # bits 5-7: lp
    # bits 8-12: pb (但只有 4 位有效)
    # 所以：属性 = lc | (lp << 5) | ((pb & 0xF) << 8)
    # 但这是 13 bits，标准格式使用单字节，所以需要特殊编码
    
    # 让我使用常见的 LZMA 属性值：
    # 0x5D 是常见的值，对应 LC=3, LP=0, PB=2（在某些编码中）
    # 但根据 LZMA 规范，需要正确计算
    
    # 尝试多种属性值组合
    headers = []
    
    # 方法 1: 0x5D (常见的 LZMA 属性值)
    header1 = struct.pack('<B', 0x5D)  # 属性
    header1 += struct.pack('<I', 0x10000)  # 字典大小 65536
    header1 += struct.pack('<Q', uncompressed_size)  # 未压缩大小
    headers.append(('0x5D, 字典64KB', header1))
    
    # 方法 2: 0x5D, 字典 256KB
    header2 = struct.pack('<B', 0x5D)  # 属性
    header2 += struct.pack('<I', 0x40000)  # 字典大小 256KB
    header2 += struct.pack('<Q', uncompressed_size)  # 未压缩大小
    headers.append(('0x5D, 字典256KB', header2))
    
    # 方法 3: 尝试计算正确的属性值
    # LC=3, LP=0, PB=2
    # 如果属性字节是单字节，可能需要：3 | (0 << 5) = 3
    # 但 PB=2 无法在单字节中表示，可能需要特殊处理
    # 尝试使用 0x03
    header3 = struct.pack('<B', 0x03)  # 属性（仅 LC=3）
    header3 += struct.pack('<I', 0x10000)  # 字典大小
    header3 += struct.pack('<Q', uncompressed_size)  # 未压缩大小
    headers.append(('0x03, 字典64KB', header3))
    
    # 方法 4: 尝试 0x1C (LC=3, LP=1, PB=0) 或其他组合
    header4 = struct.pack('<B', 0x1C)  # 属性
    header4 += struct.pack('<I', 0x10000)  # 字典大小
    header4 += struct.pack('<Q', uncompressed_size)  # 未压缩大小
    headers.append(('0x1C, 字典64KB', header4))
    
    # 方法 5: 尝试未知大小（使用 0xFFFFFFFFFFFFFFFF）
    header5 = struct.pack('<B', 0x5D)  # 属性
    header5 += struct.pack('<I', 0x10000)  # 字典大小
    header5 += struct.pack('<Q', 0xFFFFFFFFFFFFFFFF)  # 未知大小
    headers.append(('0x5D, 字典64KB, 未知大小', header5))
    
    return headers

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
            check=True,
            timeout=10
        )
        
        # 保存解压结果
        with open(output_file, 'wb') as f:
            f.write(result.stdout)
        
        os.remove(temp_file)
        return True, len(result.stdout)
        
    except subprocess.CalledProcessError as e:
        if os.path.exists(temp_file):
            os.remove(temp_file)
        return False, f"xz 解压失败: {e.stderr.decode('utf-8', errors='ignore')}"
    except FileNotFoundError:
        return False, "xz 工具未找到，请安装 xz-utils"
    except Exception as e:
        if os.path.exists(temp_file):
            os.remove(temp_file)
        return False, str(e)

def main():
    """主函数"""
    
    core_img_file = 'core_img_compressed.bin'
    
    if len(sys.argv) > 1:
        core_img_file = sys.argv[1]
    
    if not os.path.exists(core_img_file):
        print(f"错误: 文件 {core_img_file} 不存在")
        print(f"提示: 先运行 extract_and_decompress_core_img.py 提取 core.img")
        return 1
    
    print("="*70)
    print(f"基于 GRUB 源代码的 LZMA 解压器")
    print("="*70)
    
    # 读取 core.img
    with open(core_img_file, 'rb') as f:
        core_img = f.read()
    
    print(f"core.img 大小: {len(core_img)} 字节 ({len(core_img)/1024:.1f} KB)")
    
    # 查找 uncompressed_size
    print("\n查找 uncompressed_size...")
    uncompressed_size = find_uncompressed_size(core_img)
    
    if uncompressed_size:
        print(f"✅ 找到可能的 uncompressed_size: {uncompressed_size} 字节 ({uncompressed_size/1024:.1f} KB)")
    else:
        print("⚠️  无法自动找到 uncompressed_size")
        print("   尝试使用常见值...")
        # 尝试几个常见值
        uncompressed_size = 50000  # 50 KB
    
    # 提取压缩部分（4096 字节之后）
    if len(core_img) < 4096:
        print("❌ core.img 太小")
        return 1
    
    compressed_data = core_img[4096:]
    print(f"\n压缩数据大小: {len(compressed_data)} 字节 ({len(compressed_data)/1024:.1f} KB)")
    
    # 创建 LZMA 流
    print("\n创建 LZMA 流格式...")
    headers = create_lzma_stream(compressed_data, uncompressed_size)
    
    print(f"将尝试 {len(headers)} 种方法:")
    for i, (name, header) in enumerate(headers, 1):
        print(f"  方法 {i}: {name}")
    
    # 尝试所有方法
    success_count = 0
    successful_methods = []
    
    for i, (name, header) in enumerate(headers, 1):
        print("\n" + "="*70)
        print(f"尝试方法 {i}: {name}")
        print("="*70)
        
        data_with_header = header + compressed_data
        output_file = f'decompressed_grub_method{i}.bin'
        
        success, result = decompress_with_xz(data_with_header, output_file)
        
        if success:
            print(f"✅ 解压成功!")
            print(f"   输出文件: {output_file}")
            print(f"   解压后大小: {result} 字节 ({result/1024:.1f} KB)")
            print(f"   压缩比: {len(compressed_data)/result:.2f}:1")
            
            # 验证结果
            with open(output_file, 'rb') as f:
                decompressed = f.read(min(1024, result))
            
            # 检查是否包含 x86 指令模式
            common_instructions = [0x55, 0x89, 0xE8, 0x8B, 0x83, 0xC3, 0x90, 0xC9, 0x5D, 0xC2]
            instruction_count = sum(1 for b in decompressed if b in common_instructions)
            print(f"   前 1024 字节中常见 x86 指令: {instruction_count}/1024 ({instruction_count/10.24:.1f}%)")
            
            # 检查是否包含可读字符串
            try:
                strings = decompressed.decode('ascii', errors='ignore')
                readable = ''.join(c if 32 <= ord(c) < 127 else '.' for c in strings[:200])
                if any(c.isalnum() for c in readable):
                    print(f"   包含可读字符串: {readable[:100]}...")
            except:
                pass
            
            if instruction_count > 50:
                print("   ✅ 看起来像有效的 x86 代码!")
                success_count += 1
                successful_methods.append((i, name, output_file, result))
            else:
                print("   ⚠️  可能不是有效的代码")
        else:
            print(f"❌ 解压失败: {result}")
    
    # 总结
    print("\n" + "="*70)
    print("总结")
    print("="*70)
    
    if success_count > 0:
        print(f"✅ {success_count} 种方法成功解压!")
        print("\n成功的方法:")
        for method_num, name, output_file, size in successful_methods:
            print(f"   方法 {method_num} ({name}): {output_file} ({size/1024:.1f} KB)")
        print("\n可以进一步分析:")
        print(f"   strings decompressed_grub_method*.bin | grep -i grub")
        print(f"   objdump -D -b binary -m i386 decompressed_grub_method*.bin | less")
    else:
        print("❌ 所有方法都失败")
        print("\n可能的原因:")
        print("1. uncompressed_size 值不正确（当前使用: {} 字节）".format(uncompressed_size))
        print("2. GRUB 使用的 LZMA 格式与标准格式仍有差异")
        print("3. 可能需要实现完整的 GRUB LZMA 解压器")
        print("\n建议:")
        print("- 尝试不同的 uncompressed_size 值")
        print("- 使用 QEMU + GDB 在实际运行环境中查看解压后的代码")
        print("- 或者编译 GRUB 源代码中的解压器")
    
    return 0 if success_count > 0 else 1

if __name__ == '__main__':
    sys.exit(main())
