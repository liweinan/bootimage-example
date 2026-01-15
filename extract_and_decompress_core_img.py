#!/usr/bin/env python3
"""
从 grub.iso 中提取压缩的 core.img 并解压

功能：
1. 从 grub.iso 中提取 core.img（通过 kernel_sector 和 blocklist）
2. 检测压缩状态（LZMA）
3. 解压压缩部分（C 代码部分）
4. 保存压缩和解压后的文件
"""

import sys
import os
import struct
import lzma
import math

def calculate_entropy(data):
    """计算数据的熵值（用于检测压缩状态）"""
    if len(data) == 0:
        return 0
    
    byte_freq = [0] * 256
    for byte in data:
        byte_freq[byte] += 1
    
    entropy = 0
    for freq in byte_freq:
        if freq > 0:
            p = freq / len(data)
            entropy -= p * math.log2(p)
    
    return entropy

def extract_core_img(iso_file):
    """从 ISO 文件中提取 core.img"""
    
    print("="*70)
    print(f"从 {iso_file} 提取 core.img")
    print("="*70)
    
    # 检查文件是否存在
    if not os.path.exists(iso_file):
        print(f"错误: 文件 {iso_file} 不存在")
        return None, None
    
    # 读取引导扇区
    with open(iso_file, 'rb') as f:
        boot_sector = f.read(512)
    
    if len(boot_sector) < 512:
        print(f"错误: ISO 文件太小")
        return None, None
    
    # 检查标准模式和 HYBRID_BOOT 模式的 kernel_sector
    kernel_sector_std = 0
    kernel_sector_hybrid = 0
    
    if len(boot_sector) >= 0x5c + 4:
        kernel_sector_std = struct.unpack('<I', boot_sector[0x5c:0x5c+4])[0]
    
    if len(boot_sector) >= 0x1b0 + 4:
        kernel_sector_hybrid = struct.unpack('<I', boot_sector[0x1b0:0x1b0+4])[0]
    
    # 确定使用的模式
    kernel_sector = 0
    if kernel_sector_hybrid != 0 and kernel_sector_hybrid < 100000:
        kernel_sector = kernel_sector_hybrid
        print(f"✅ 使用 HYBRID_BOOT 模式: kernel_sector = {kernel_sector}")
    elif kernel_sector_std != 0 and kernel_sector_std < 100000:
        kernel_sector = kernel_sector_std
        print(f"✅ 使用标准模式: kernel_sector = {kernel_sector}")
    else:
        print("❌ 无法确定 kernel_sector")
        return None, None
    
    # 读取 core.img 的第一个扇区
    with open(iso_file, 'rb') as f:
        f.seek(kernel_sector * 512)
        core_img_first_sector = f.read(512)
    
    if len(core_img_first_sector) < 512:
        print("❌ 无法读取 core.img 第一个扇区")
        return None, None
    
    print(f"✅ 成功读取 core.img 第一个扇区")
    
    # 从块列表计算总大小
    # 块列表通常在 diskboot.S 的末尾，从 0x1F4 倒序查找
    blocklist_start_offset = 0x1F4
    blocklist_entry_size = 12
    
    total_sectors = 0
    entry_count = 0
    
    for i in range(20):  # 最多检查 20 个条目
        offset = blocklist_start_offset - (i * blocklist_entry_size)
        if offset < 0:
            break
        
        if offset + blocklist_entry_size > len(core_img_first_sector):
            continue
        
        entry = core_img_first_sector[offset:offset+blocklist_entry_size]
        len_val = struct.unpack('<H', entry[8:10])[0]
        
        if len_val == 0:
            break
        
        total_sectors += len_val
        entry_count += 1
    
    if total_sectors == 0:
        print("❌ 无法从块列表确定 core.img 大小")
        return None, None
    
    core_img_size = total_sectors * 512
    print(f"✅ core.img 大小: {total_sectors} 扇区 = {core_img_size} 字节 ({core_img_size/1024:.1f} KB)")
    
    # 提取完整的 core.img
    with open(iso_file, 'rb') as f:
        f.seek(kernel_sector * 512)
        core_img = f.read(core_img_size)
    
    if len(core_img) != core_img_size:
        print(f"❌ 提取的 core.img 大小不匹配（期望 {core_img_size}，实际 {len(core_img)}）")
        return None, None
    
    print(f"✅ 成功提取完整的 core.img")
    
    return core_img, kernel_sector

def decompress_core_img(core_img):
    """解压 core.img 的压缩部分"""
    
    print("\n" + "="*70)
    print("分析 core.img 压缩状态")
    print("="*70)
    
    if len(core_img) < 4096:
        print("❌ core.img 太小，无法分析")
        return None
    
    # 分析前 4KB（通常是未压缩的汇编代码）
    first_4kb = core_img[:4096]
    first_4kb_entropy = calculate_entropy(first_4kb)
    
    # 分析剩余部分（通常是压缩的 C 代码）
    remaining_data = core_img[4096:]
    remaining_entropy = calculate_entropy(remaining_data)
    
    print(f"前 4KB 熵值: {first_4kb_entropy:.2f} bits/byte")
    print(f"剩余 {len(remaining_data)} 字节熵值: {remaining_entropy:.2f} bits/byte")
    
    # 检测 LZMA 压缩
    # LZMA 压缩数据通常具有高熵值（> 7.0），而未压缩代码熵值较低（< 7.0）
    # 如果剩余部分的熵值明显高于前 4KB，很可能是压缩的
    has_lzma = False
    entropy_diff = remaining_entropy - first_4kb_entropy
    
    if remaining_entropy > 7.0 and entropy_diff > 0.5:
        has_lzma = True
        print(f"✅ 检测到混合格式（前 4KB 未压缩，后部分 LZMA 压缩）")
        print(f"   熵值差异: {entropy_diff:.2f} bits/byte（压缩数据熵值明显更高）")
    elif remaining_entropy > 7.5:
        # 即使前 4KB 熵值较高，如果剩余部分熵值非常高，也可能是压缩的
        has_lzma = True
        print(f"✅ 检测到 LZMA 压缩（剩余部分熵值 {remaining_entropy:.2f} > 7.5）")
    elif remaining_entropy < 6.5:
        print("⚠️  未检测到 LZMA 压缩（代码可能未压缩）")
    else:
        print("⚠️  压缩状态不确定（可能需要手动检查）")
    
    if not has_lzma:
        print("⚠️  未检测到压缩，返回原始 core.img")
        return core_img
    
    # 尝试解压
    print("\n" + "="*70)
    print("解压 core.img 的压缩部分")
    print("="*70)
    
    # GRUB 的 LZMA 解压需要特定的格式
    # 通常压缩数据在 4096 字节之后
    compressed_data = core_img[4096:]
    
    print(f"压缩数据大小: {len(compressed_data)} 字节")
    print(f"压缩数据前 32 字节（十六进制）: {compressed_data[:32].hex()}")
    
    # 尝试使用 Python 的 lzma 模块解压
    # 注意：GRUB 使用的 LZMA 格式可能与标准 LZMA 格式略有不同
    # 可能需要使用 GRUB 特定的解压器
    
    decompressed = None
    
    # 方法 1：尝试直接使用 lzma.decompress（标准 LZMA 格式）
    print("\n方法 1: 尝试标准 LZMA 格式解压...")
    try:
        decompressed = lzma.decompress(compressed_data)
        print(f"✅ 成功解压: {len(compressed_data)} 字节 -> {len(decompressed)} 字节")
    except Exception as e:
        print(f"⚠️  标准 LZMA 格式解压失败: {e}")
    
    # 方法 2：尝试查找 LZMA 头部并手动构造
    if decompressed is None:
        print("\n方法 2: 尝试查找 LZMA 头部...")
        # LZMA 格式通常以属性字节开始（5D 00 00 00 01 是常见的）
        # 查找可能的 LZMA 头部位置
        lzma_markers = [
            b'\x5d\x00\x00\x00\x01',  # 常见的 LZMA 属性
            b'\x5d\x00\x00',          # 简化的 LZMA 属性
        ]
        
        for marker in lzma_markers:
            pos = compressed_data.find(marker)
            if pos != -1:
                print(f"   找到可能的 LZMA 头部在偏移 {pos}")
                try:
                    # 从标记位置开始解压
                    decompressed = lzma.decompress(compressed_data[pos:])
                    print(f"✅ 从偏移 {pos} 成功解压: {len(compressed_data[pos:])} 字节 -> {len(decompressed)} 字节")
                    break
                except Exception as e:
                    print(f"   ⚠️  从偏移 {pos} 解压失败: {e}")
    
    # 方法 3：尝试不同的 LZMA 格式（LZMA1, LZMA2）
    if decompressed is None:
        print("\n方法 3: 尝试不同的 LZMA 格式...")
        # LZMA1 格式（FORMAT_AUTO）
        try:
            decompressed = lzma.decompress(compressed_data, format=lzma.FORMAT_AUTO)
            print(f"✅ 使用 FORMAT_AUTO 成功解压: {len(compressed_data)} 字节 -> {len(decompressed)} 字节")
        except Exception as e:
            print(f"   ⚠️  FORMAT_AUTO 解压失败: {e}")
    
    # 如果所有方法都失败
    if decompressed is None:
        print("\n" + "="*70)
        print("⚠️  无法使用标准 LZMA 格式解压")
        print("="*70)
        print("可能的原因：")
        print("1. GRUB 使用自定义的 LZMA 格式")
        print("2. 压缩数据需要特定的头部信息")
        print("3. 需要使用 GRUB 特定的解压器")
        print("\n建议：")
        print("- 查看 GRUB 源代码中的 LZMA 解压实现")
        print("- 使用 GRUB 工具（如 grub-mkimage）来解压")
        print("- 或者使用调试器在实际运行环境中查看解压后的代码")
        print("\n已保存压缩的 core.img，可以手动分析:")
        print(f"  hexdump -C core_img_compressed.bin | less")
        return None
    
    # 组合未压缩部分和解压部分
    decompressed_core_img = first_4kb + decompressed
    
    print("\n" + "="*70)
    print("解压完成")
    print("="*70)
    print(f"原始大小: {len(core_img)} 字节 ({len(core_img)/1024:.1f} KB)")
    print(f"解压后大小: {len(decompressed_core_img)} 字节 ({len(decompressed_core_img)/1024:.1f} KB)")
    print(f"压缩比: {len(core_img)/len(decompressed_core_img):.2f}:1")
    print(f"未压缩部分: {len(first_4kb)} 字节 (diskboot.S + startup_raw.S)")
    print(f"压缩部分: {len(compressed_data)} 字节 -> {len(decompressed)} 字节 (C 代码)")
    
    return decompressed_core_img

def main():
    """主函数"""
    
    iso_file = 'grub.iso'
    
    if len(sys.argv) > 1:
        iso_file = sys.argv[1]
    
    # 提取 core.img
    core_img, kernel_sector = extract_core_img(iso_file)
    
    if core_img is None:
        print("❌ 无法提取 core.img")
        return 1
    
    # 保存压缩的 core.img
    compressed_file = 'core_img_compressed.bin'
    with open(compressed_file, 'wb') as f:
        f.write(core_img)
    print(f"\n✅ 已保存压缩的 core.img 到: {compressed_file}")
    
    # 解压 core.img
    decompressed_core_img = decompress_core_img(core_img)
    
    if decompressed_core_img is not None:
        # 保存解压后的 core.img
        decompressed_file = 'core_img_decompressed.bin'
        with open(decompressed_file, 'wb') as f:
            f.write(decompressed_core_img)
        print(f"\n✅ 已保存解压后的 core.img 到: {decompressed_file}")
        
        # 显示文件信息
        print("\n" + "="*70)
        print("文件信息")
        print("="*70)
        print(f"压缩文件: {compressed_file} ({len(core_img)} 字节, {len(core_img)/1024:.1f} KB)")
        print(f"解压文件: {decompressed_file} ({len(decompressed_core_img)} 字节, {len(decompressed_core_img)/1024:.1f} KB)")
        print(f"压缩比: {len(core_img)/len(decompressed_core_img):.2f}:1")
        
        # 提示如何使用
        print("\n" + "="*70)
        print("使用提示")
        print("="*70)
        print(f"查看压缩文件: hexdump -C {compressed_file} | less")
        print(f"查看解压文件: hexdump -C {decompressed_file} | less")
        print(f"反汇编解压文件: objdump -D -b binary -m i386 {decompressed_file} | less")
        print(f"查找字符串: strings {decompressed_file} | grep -i grub")
    else:
        print("\n" + "="*70)
        print("解压状态")
        print("="*70)
        print("⚠️  无法使用标准 LZMA 格式解压 core.img")
        print(f"✅ 压缩文件已成功提取并保存到: {compressed_file}")
        print(f"   文件大小: {len(core_img)} 字节 ({len(core_img)/1024:.1f} KB)")
        
        # 分析 core.img 结构
        print("\n" + "="*70)
        print("core.img 结构分析")
        print("="*70)
        if len(core_img) >= 512:
            print(f"前 512 字节: diskboot.S（块列表加载代码）")
            print(f"  位置: 0x0000 - 0x01FF")
            print(f"  内存地址: 0x8000 - 0x81FF")
        if len(core_img) >= 4096:
            print(f"512 - 4096 字节: startup_raw.S（模式切换、解压代码）")
            print(f"  位置: 0x0200 - 0x0FFF")
            print(f"  内存地址: 0x8200 - 0x8FFF")
        if len(core_img) > 4096:
            compressed_size = len(core_img) - 4096
            print(f"4096+ 字节: C 代码（LZMA 压缩）")
            print(f"  位置: 0x1000 - 0x{len(core_img)-1:04X}")
            print(f"  大小: {compressed_size} 字节 ({compressed_size/1024:.1f} KB)")
            print(f"  内存地址: 0x9000+ (压缩状态)")
            print(f"  解压后地址: 0x100000+ (1MB 以上)")
        
        # 提供替代方案
        print("\n" + "="*70)
        print("替代方案")
        print("="*70)
        print("GRUB 使用自定义的 LZMA 格式，标准工具无法直接解压。")
        print("可以使用以下方法查看解压后的代码：")
        print("\n1. 使用 QEMU + GDB 调试:")
        print("   qemu-system-x86_64 -cdrom grub.iso -s -S")
        print("   然后在 GDB 中查看 0x100000 处的代码")
        print("\n2. 查看 GRUB 源代码:")
        print("   - grub/grub-core/boot/i386/pc/startup_raw.S (解压代码)")
        print("   - grub/grub-core/kern/i386/pc/init.c (grub_stub_init)")
        print("   - grub/grub-core/kern/main.c (grub_main)")
        print("\n3. 手动分析压缩文件:")
        print(f"   hexdump -C {compressed_file} | less")
        print(f"   strings {compressed_file} | grep -i grub")
        print(f"   objdump -D -b binary -m i386 {compressed_file} | less")
        print("\n4. 使用 GRUB 工具（如果可用）:")
        print("   grub-mkimage 或 grub-install 可能包含解压功能")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
