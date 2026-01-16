#!/usr/bin/env python3
"""
验证 GRUB ISO 镜像的引导扇区和 core.img 分析

从 grub.iso 中提取引导扇区（第一个扇区，512 字节），
验证其是否符合 GRUB 引导扇区的特征。
分析 core.img 的结构、压缩状态和代码入口点（grub_stub_init）。

功能：
- 验证引导扇区签名和关键字段
- 提取并分析 core.img 的块列表
- 检测 core.img 的压缩状态（LZMA 压缩 vs 未压缩）
- 分析数据特征（熵值、NOP 字节、零字节等）
- 查找代码入口点（grub_stub_init）

注意：此脚本只进行分析，不执行实际的解压操作。
解压过程由 GRUB 在运行时通过 startup_raw.S 中的 _LzmaDecodeA 函数完成。
"""

import sys
import os
import struct
import subprocess
import tempfile
import re
import math

def verify_grub_boot_sector(iso_file):
    """验证 GRUB ISO 镜像的引导扇区"""
    
    print("="*70)
    print(f"验证 GRUB ISO 引导扇区: {iso_file}")
    print("="*70)
    
    # 检查文件是否存在
    if not os.path.exists(iso_file):
        print(f"错误: 文件 {iso_file} 不存在")
        return False
    
    # 读取引导扇区（第一个 512 字节）
    with open(iso_file, 'rb') as f:
        boot_sector = f.read(512)
    
    if len(boot_sector) < 512:
        print(f"错误: ISO 文件太小，无法读取完整的引导扇区")
        return False
    
    print(f"\n引导扇区大小: {len(boot_sector)} 字节")
    
    # 验证引导扇区签名 (最后两个字节应该是 0xAA55)
    signature = boot_sector[-2:]
    expected_sig = bytes([0x55, 0xAA])  # 小端序
    
    print(f"\n引导扇区签名 (偏移 0x1FE-0x1FF):")
    print(f"  实际值: 0x{signature[0]:02X} 0x{signature[1]:02X}")
    print(f"  期望值: 0x55 0xAA (0xAA55 小端序)")
    
    if signature != expected_sig:
        print("❌ 引导扇区签名错误！")
        return False
    else:
        print("✅ 引导扇区签名正确")
    
    # 检查标准模式的 kernel_sector（偏移 0x5c）
    print(f"\n标准模式 kernel_sector (偏移 0x5c = {0x5c} 字节):")
    if len(boot_sector) >= 0x5c + 4:
        kernel_sector_std = struct.unpack('<I', boot_sector[0x5c:0x5c+4])[0]
        print(f"  值: {kernel_sector_std} (0x{kernel_sector_std:x})")
        if kernel_sector_std == 0 or kernel_sector_std > 100000:
            print("  ⚠️  无效值（可能是 0 或过大）")
        else:
            print(f"  ✅ 有效值: 扇区 {kernel_sector_std}")
    else:
        print("  ⚠️  无法读取（文件太小）")
    
    # 检查 HYBRID_BOOT 模式的 kernel_sector（偏移 0x1b0）
    print(f"\nHYBRID_BOOT 模式 kernel_sector (偏移 0x1b0 = {0x1b0} 字节):")
    if len(boot_sector) >= 0x1b0 + 4:
        kernel_sector_hybrid = struct.unpack('<I', boot_sector[0x1b0:0x1b0+4])[0]
        print(f"  值: {kernel_sector_hybrid} (0x{kernel_sector_hybrid:x})")
        if kernel_sector_hybrid == 0 or kernel_sector_hybrid > 100000:
            print("  ⚠️  无效值（可能是 0 或过大）")
        else:
            print(f"  ✅ 有效值: 扇区 {kernel_sector_hybrid}")
    else:
        print("  ⚠️  无法读取（文件太小）")
    
    # 检查 kernel_address（偏移 0x1b4，HYBRID_BOOT 模式）
    print(f"\nkernel_address (偏移 0x1b4 = {0x1b4} 字节，HYBRID_BOOT 模式):")
    if len(boot_sector) >= 0x1b4 + 2:
        kernel_address = struct.unpack('<H', boot_sector[0x1b4:0x1b4+2])[0]
        print(f"  值: 0x{kernel_address:04x} ({kernel_address})")
        if kernel_address == 0x8000:
            print("  ✅ 正确值: 0x8000 (GRUB Core 加载地址)")
        else:
            print(f"  ⚠️  非标准值（期望 0x8000）")
    else:
        print("  ⚠️  无法读取（文件太小）")
    
    # 查找 GRUB 特征字符串
    print(f"\n查找 GRUB 特征字符串:")
    grub_strings = [
        b"GRUB",
        b"Geom",
        b"Read",
        b"Error",
        b"loading"
    ]
    found_strings = []
    for s in grub_strings:
        pos = boot_sector.find(s)
        if pos != -1:
            found_strings.append((s.decode('ascii', errors='ignore'), pos))
            print(f"  ✅ 找到 \"{s.decode('ascii', errors='ignore')}\" 在偏移 0x{pos:03x}")
    
    if not found_strings:
        print("  ⚠️  未找到典型的 GRUB 特征字符串")
        print("  （这可能是正常的，因为引导扇区代码很小）")
    
    # 显示引导扇区内容（前 256 字节）
    print("\n" + "="*70)
    print("引导扇区内容 (前 256 字节，十六进制):")
    print("="*70)
    
    for i in range(0, min(256, len(boot_sector)), 16):
        offset = i
        hex_part = ' '.join(f'{b:02X}' for b in boot_sector[i:i+16])
        ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in boot_sector[i:i+16])
        print(f"0x{offset:03X}: {hex_part:<48} | {ascii_part}")
    
    # 分析关键字段位置
    print("\n" + "="*70)
    print("关键字段位置分析:")
    print("="*70)
    
    # 检查开头的代码（通常是跳转指令或 NOP）
    if len(boot_sector) >= 16:
        first_bytes = boot_sector[0:16]
        print(f"\n开头 16 字节 (偏移 0x000):")
        print(f"  {first_bytes.hex(' ').upper()}")
        
        # 检查是否是跳转指令
        if first_bytes[0] == 0xEB:  # JMP short
            offset = first_bytes[1]
            target = 2 + offset
            print(f"  ✅ 检测到: JMP short (EB {offset:02X}) -> 偏移 +{offset} (目标: 0x{target:03x})")
        elif first_bytes[0] == 0xE9:  # JMP near
            offset = struct.unpack('<h', first_bytes[1:3])[0]
            target = 3 + offset
            print(f"  ✅ 检测到: JMP near (E9 {offset:04X}) -> 偏移 +{offset} (目标: 0x{target:03x})")
        elif first_bytes[0:2] == b'\x90\x90':  # NOP NOP
            print(f"  ✅ 检测到: NOP NOP (可能是填充)")
        else:
            print(f"  ⚠️  未识别的指令开头")
    
    # 确定使用的模式
    print(f"\n引导模式判断:")
    if len(boot_sector) >= 0x1b0 + 4:
        kernel_sector_hybrid = struct.unpack('<I', boot_sector[0x1b0:0x1b0+4])[0]
        kernel_sector_std = struct.unpack('<I', boot_sector[0x5c:0x5c+4])[0] if len(boot_sector) >= 0x5c + 4 else 0
        
        if kernel_sector_hybrid != 0 and kernel_sector_hybrid < 100000:
            print(f"  ✅ HYBRID_BOOT 模式: kernel_sector = {kernel_sector_hybrid}")
        elif kernel_sector_std != 0 and kernel_sector_std < 100000:
            print(f"  ✅ 标准模式: kernel_sector = {kernel_sector_std}")
        else:
            print(f"  ⚠️  无法确定模式（两个字段都无效）")
    
    # 分析 core.img 入口点（grub_stub_init）
    print("\n" + "="*70)
    print("分析 core.img 代码入口点（grub_stub_init）")
    print("="*70)
    
    # 确定 kernel_sector
    kernel_sector = None
    if len(boot_sector) >= 0x1b0 + 4:
        kernel_sector_hybrid = struct.unpack('<I', boot_sector[0x1b0:0x1b0+4])[0]
        kernel_sector_std = struct.unpack('<I', boot_sector[0x5c:0x5c+4])[0] if len(boot_sector) >= 0x5c + 4 else 0
        
        if kernel_sector_hybrid != 0 and kernel_sector_hybrid < 100000:
            kernel_sector = kernel_sector_hybrid
        elif kernel_sector_std != 0 and kernel_sector_std < 100000:
            kernel_sector = kernel_sector_std
    
    if kernel_sector:
        print(f"\n提取 core.img（从扇区 {kernel_sector}）...")
        
        # 提取 core.img 的第一个扇区（diskboot.S）
        try:
            with open(iso_file, 'rb') as f:
                f.seek(kernel_sector * 512)
                core_img_first = f.read(512)
            
            if len(core_img_first) == 512:
                print("✅ 成功提取 core.img 第一个扇区")
                
                # 从块列表计算 core.img 大小
                # 块列表在扇区末尾，从偏移 0x1F4 开始向前
                BLOCKLIST_START = 0x1F4
                BLOCKLIST_ENTRY_SIZE = 12
                
                total_sectors = 0
                entry_count = 0
                blocklist_entries = []
                
                # 读取块列表条目（最多 20 个）
                print(f"\n块列表详细分析:")
                print("-" * 70)
                for i in range(20):
                    offset = BLOCKLIST_START - (i * BLOCKLIST_ENTRY_SIZE)
                    if offset < 0:
                        break
                    
                    if offset + 12 <= len(core_img_first):
                        # 读取块列表条目（12 字节）
                        entry = core_img_first[offset:offset+12]
                        
                        # 解析字段（小端序）
                        # start 低 32 位 (0-3), start 高 32 位 (4-7), len (8-9), segment (10-11)
                        start_low = struct.unpack('<I', entry[0:4])[0]
                        start_high = struct.unpack('<I', entry[4:8])[0]
                        len_val = struct.unpack('<H', entry[8:10])[0]
                        segment = struct.unpack('<H', entry[10:12])[0]
                        
                        if len_val == 0:
                            print(f"  条目 {i}: len=0 (结束标记)")
                            break
                        
                        total_sectors += len_val
                        entry_count += 1
                        blocklist_entries.append({
                            'index': i,
                            'start_low': start_low,
                            'start_high': start_high,
                            'len': len_val,
                            'segment': segment
                        })
                        
                        print(f"  条目 {i}: start={start_low} (0x{start_low:x}), len={len_val} 扇区, segment=0x{segment:04x}")
                
                if total_sectors > 0:
                    core_img_size = total_sectors * 512
                    print(f"\n✅ core.img 大小: {total_sectors} 扇区 = {core_img_size} 字节 ({core_img_size/1024:.1f} KB)")
                    print(f"   块列表条目数: {entry_count}")
                    
                    # 提取完整的 core.img
                    try:
                        with open(iso_file, 'rb') as f:
                            f.seek(kernel_sector * 512)
                            core_img = f.read(core_img_size)
                        
                        if len(core_img) == core_img_size:
                            print(f"✅ 成功提取完整的 core.img")
                            
                            # ========== 完整分析 diskboot.S 和 startup_raw.S 的实际大小 ==========
                            print(f"\n" + "="*70)
                            print("完整分析 diskboot.S 和 startup_raw.S 的实际大小")
                            print("="*70)
                            
                            # 1. 分析 diskboot.S 的实际大小
                            print(f"\n【1】分析 diskboot.S 的实际大小")
                            print("-" * 70)
                            
                            diskboot_sector = core_img[:512]
                            
                            # 查找块列表位置（在扇区末尾，偏移 0x1F4）
                            blocklist_offset = 0x1F4
                            if blocklist_offset + 12 <= len(diskboot_sector):
                                blocklist_entry = diskboot_sector[blocklist_offset:blocklist_offset+12]
                                # 检查是否是有效的块列表（len != 0）
                                len_val = struct.unpack('<H', blocklist_entry[8:10])[0]
                                if len_val > 0:
                                    print(f"  ✅ 找到块列表位置：文件偏移 0x{blocklist_offset:x}，内存地址 0x{0x8000 + blocklist_offset:x}")
                                    print(f"  ✅ diskboot.S 代码区域：0x0000 - 0x{blocklist_offset-1:x}（约 {blocklist_offset} 字节）")
                                    print(f"  ✅ 块列表数据区域：0x{blocklist_offset:x} - 0x1FF（12 字节）")
                            
                            # 使用 objdump 反汇编 diskboot.S，查找实际代码边界
                            diskboot_code_end = blocklist_offset
                            tmp_file_path = None
                            try:
                                with tempfile.NamedTemporaryFile(delete=False, suffix='.bin') as tmp_file:
                                    tmp_file.write(diskboot_sector)
                                    tmp_file_path = tmp_file.name
                                
                                result = subprocess.run(
                                    ['objdump', '-D', '-b', 'binary', '-m', 'i8086', '-M', 'intel', tmp_file_path],
                                    capture_output=True,
                                    text=True,
                                    timeout=10
                                )
                                
                                if result.returncode == 0 and result.stdout:
                                    # 查找最后一个有效的指令位置
                                    lines = result.stdout.split('\n')
                                    last_valid_addr = 0
                                    for line in lines:
                                        # Linux objdump 格式：空格 + 十六进制数字 + 冒号（例如 "   0:" 或 "   a:"）
                                        # 也支持 0x0000: 格式
                                        addr_match = re.search(r'(?:^\s+|0x)([0-9a-fA-F]+):', line)
                                        if addr_match:
                                            try:
                                                addr = int(addr_match.group(1), 16)
                                                if addr < blocklist_offset and addr > last_valid_addr:
                                                    # 检查是否是有效指令（不是填充）
                                                    line_lower = line.lower()
                                                    if 'nop' not in line_lower or addr < blocklist_offset - 20:
                                                        last_valid_addr = addr
                                            except:
                                                pass
                                    
                                    if last_valid_addr > 0:
                                        diskboot_code_end = min(last_valid_addr + 20, blocklist_offset)  # 留一些余量
                                        print(f"  ✅ 通过 objdump 分析：diskboot.S 代码实际结束位置约 0x{diskboot_code_end:x}")
                                        print(f"     实际代码大小：约 {diskboot_code_end} 字节")
                            except Exception as e:
                                print(f"  ⚠️  objdump 分析失败: {e}")
                            finally:
                                if tmp_file_path and os.path.exists(tmp_file_path):
                                    try:
                                        os.unlink(tmp_file_path)
                                    except:
                                        pass
                            
                            # 2. 分析 startup_raw.S 的实际大小
                            print(f"\n【2】分析 startup_raw.S 的实际大小")
                            print("-" * 70)
                            
                            # 方法 1：查找 LZMA 压缩标记（0x5D 0x00 0x00）来确定压缩代码的起始位置
                            lzma_marker = b'\x5d\x00\x00'
                            lzma_start_pos = -1
                            
                            print(f"  方法 1：查找 LZMA 压缩标记（0x5D 0x00 0x00）...")
                            
                            # 在整个 core.img 中查找 LZMA 标记（压缩代码应该在 startup_raw.S 之后）
                            # 但优先在前 12KB 中搜索（通常在前 4KB 之后）
                            search_range = min(len(core_img), 12288)  # 扩大到 12KB
                            for i in range(512, search_range - 2):  # 从 diskboot.S 之后开始搜索
                                if core_img[i:i+3] == lzma_marker:
                                    lzma_start_pos = i
                                    print(f"  ✅ 找到 LZMA 压缩标记：文件偏移 0x{i:x}，内存地址 0x{0x8000 + i:x}")
                                    print(f"     这表示压缩的 C 代码从 0x{i:x} 开始")
                                    print(f"     startup_raw.S 的实际大小：约 {i - 512} 字节（0x{i - 512:x} 字节）")
                                    break
                            
                            # 如果在前 12KB 中没找到，但在后面的分析中找到了（has_lzma_back），说明标记在 4096 之后
                            if lzma_start_pos <= 0:
                                # 检查是否在 4096 之后有 LZMA 标记（通过后续分析会检测到）
                                print(f"  ⚠️  在前 12KB 中未找到 LZMA 压缩标记（0x5D 0x00 0x00）")
                                print(f"     将在后续分析中检查 4096 字节之后的位置...")
                            elif lzma_start_pos < 1024:
                                # 如果找到的位置太早（< 1KB），可能是误报
                                print(f"  ⚠️  警告：LZMA 标记位置 0x{lzma_start_pos:x} 似乎太早（< 1KB）")
                                print(f"     这可能是数据中的巧合，不是真正的 LZMA 压缩标记")
                                print(f"     将在后续分析中验证 4096 字节之后是否有真正的 LZMA 标记...")
                                # 暂时不更新 lzma_start_pos，等待后续验证
                                lzma_start_pos = -1
                            
                            # 方法 2：使用 objdump 反汇编前 4KB，查找代码边界
                            startup_raw_end = 4096  # 默认假设 4KB
                            if lzma_start_pos > 0:
                                startup_raw_end = lzma_start_pos
                                print(f"\n  方法 2：使用 objdump 反汇编验证（LZMA 标记已找到，startup_raw_end = 0x{startup_raw_end:x}）...")
                            else:
                                print(f"\n  方法 2：使用 objdump 反汇编查找代码边界...")
                            
                            tmp_file_path2 = None
                            try:
                                front_4k_data = core_img[:min(4096, len(core_img))]
                                with tempfile.NamedTemporaryFile(delete=False, suffix='.bin') as tmp_file:
                                    tmp_file.write(front_4k_data)
                                    tmp_file_path2 = tmp_file.name
                                
                                result = subprocess.run(
                                    ['objdump', '-D', '-b', 'binary', '-m', 'i386', '-M', 'intel', tmp_file_path2],
                                    capture_output=True,
                                    text=True,
                                    timeout=10
                                )
                                
                                if result.returncode == 0 and result.stdout:
                                    lines = result.stdout.split('\n')
                                    last_code_addr = 512  # diskboot.S 之后
                                    consecutive_padding = 0
                                    
                                    for line in lines:
                                        # Linux objdump 格式：空格 + 十六进制数字 + 冒号（例如 "   0:" 或 "  200:"）
                                        # 也支持 0x0000: 格式
                                        addr_match = re.search(r'(?:^\s+|0x)([0-9a-fA-F]+):', line)
                                        if addr_match:
                                            try:
                                                addr = int(addr_match.group(1), 16)
                                                if addr >= 512:  # startup_raw.S 区域
                                                    # 检查是否是填充字节（nop 或 0x00）
                                                    line_lower = line.lower()
                                                    if 'nop' in line_lower or ('00' in line_lower and '0x' not in line_lower):
                                                        consecutive_padding += 1
                                                        if consecutive_padding > 50:  # 连续 50 个填充字节，可能是代码结束
                                                            break
                                                    else:
                                                        consecutive_padding = 0
                                                        if addr > last_code_addr:
                                                            last_code_addr = addr
                                            except:
                                                pass
                                    
                                    if last_code_addr > 512:
                                        # 如果找到了 LZMA 标记，使用较小的值
                                        if lzma_start_pos > 0:
                                            startup_raw_end = min(last_code_addr + 100, lzma_start_pos)
                                        else:
                                            startup_raw_end = last_code_addr + 100
                                        print(f"  ✅ 通过 objdump 分析：startup_raw.S 代码实际结束位置约 0x{startup_raw_end:x}")
                                        print(f"     实际代码大小：约 {startup_raw_end - 512} 字节（0x{startup_raw_end - 512:x} 字节）")
                            except Exception as e:
                                print(f"  ⚠️  objdump 分析失败: {e}")
                            finally:
                                if tmp_file_path2 and os.path.exists(tmp_file_path2):
                                    try:
                                        os.unlink(tmp_file_path2)
                                    except:
                                        pass
                            
                            # 方法 3：查找填充字节模式来确定代码边界
                            if lzma_start_pos <= 0:
                                print(f"\n  方法 3：查找填充字节模式（LZMA 标记未找到）...")
                                # 查找连续的填充字节（0x00 或 0x90）
                                padding_threshold = 100  # 连续 100 个填充字节认为是代码结束
                                for i in range(512, min(len(core_img), 8192)):
                                    if core_img[i] in [0x00, 0x90]:
                                        consecutive = 1
                                        for j in range(i+1, min(i+padding_threshold, len(core_img))):
                                            if core_img[j] in [0x00, 0x90]:
                                                consecutive += 1
                                            else:
                                                break
                                        if consecutive >= padding_threshold:
                                            startup_raw_end = i
                                            print(f"  ✅ 通过填充字节分析：发现连续 {consecutive} 个填充字节从 0x{i:x}")
                                            print(f"     startup_raw.S 的实际大小：约 {i - 512} 字节（0x{i - 512:x} 字节）")
                                            break
                            
                            # 3. 总结分析结果
                            print(f"\n【3】分析结果总结")
                            print("-" * 70)
                            print(f"  diskboot.S:")
                            print(f"    - 文件偏移：0x0000 - 0x{blocklist_offset-1:x}")
                            print(f"    - 内存地址：0x8000 - 0x{0x8000 + blocklist_offset - 1:x}")
                            print(f"    - 实际代码大小：约 {diskboot_code_end} 字节")
                            print(f"    - 块列表：0x{blocklist_offset:x} - 0x1FF（12 字节）")
                            
                            print(f"\n  startup_raw.S:")
                            print(f"    - 文件偏移：0x0200 (512) - 0x{startup_raw_end:x}")
                            print(f"    - 内存地址：0x8200 - 0x{0x8000 + startup_raw_end:x}")
                            print(f"    - 实际代码大小：约 {startup_raw_end - 512} 字节（0x{startup_raw_end - 512:x} 字节）")
                            
                            if lzma_start_pos > 0:
                                print(f"\n  压缩 C 代码:")
                                print(f"    - 文件偏移：0x{lzma_start_pos:x} - 0x{len(core_img):x}")
                                print(f"    - 内存地址：0x{0x8000 + lzma_start_pos:x} - 0x{0x8000 + len(core_img):x}")
                                print(f"    - 压缩大小：约 {len(core_img) - lzma_start_pos} 字节（{(len(core_img) - lzma_start_pos)/1024:.1f} KB）")
                            else:
                                print(f"\n  压缩 C 代码:")
                                print(f"    - ⚠️  未找到 LZMA 压缩标记，无法确定压缩代码的起始位置")
                                print(f"    - 假设压缩代码从 0x{startup_raw_end:x} 开始（基于默认 4KB 边界）")
                                if startup_raw_end < len(core_img):
                                    print(f"    - 文件偏移：0x{startup_raw_end:x} - 0x{len(core_img):x}")
                                    print(f"    - 内存地址：0x{0x8000 + startup_raw_end:x} - 0x{0x8000 + len(core_img):x}")
                                    print(f"    - 压缩大小：约 {len(core_img) - startup_raw_end} 字节（{(len(core_img) - startup_raw_end)/1024:.1f} KB）")
                            
                            print(f"\n  前 4KB 未压缩区域:")
                            uncompressed_size = startup_raw_end
                            print(f"    - 总大小：{uncompressed_size} 字节（{uncompressed_size/1024:.1f} KB）")
                            print(f"    - 组成：diskboot.S ({diskboot_code_end} 字节) + 块列表 (12 字节) + startup_raw.S ({startup_raw_end - 512} 字节)")
                            
                            # 显示分析方法总结
                            print(f"\n  分析方法总结:")
                            if lzma_start_pos > 0:
                                print(f"    ✅ 方法 1（LZMA 标记）：成功，startup_raw.S 结束于 0x{lzma_start_pos:x}")
                            else:
                                print(f"    ⚠️  方法 1（LZMA 标记）：未找到标记")
                            
                            if startup_raw_end == 4096:
                                print(f"    ⚠️  方法 2（objdump）：失败或未执行，使用默认值 4KB")
                            else:
                                if lzma_start_pos > 0 and startup_raw_end == lzma_start_pos:
                                    print(f"    ✅ 方法 2（objdump）：验证了 LZMA 标记位置")
                                else:
                                    print(f"    ✅ 方法 2（objdump）：成功，startup_raw.S 结束于 0x{startup_raw_end:x}")
                            
                            if lzma_start_pos <= 0 and startup_raw_end == 4096:
                                print(f"    ⚠️  方法 3（填充字节）：未找到足够的填充字节，使用默认值")
                            
                            # 更新分析数据
                            startup_raw_data = core_img[512:startup_raw_end] if startup_raw_end <= len(core_img) else core_img[512:4096]
                            
                            # ========== 继续原有的分析流程 ==========
                            
                            # 查找代码入口点特征
                            # 1. 更准确地检测 LZMA 压缩
                            # LZMA 压缩数据通常：
                            # - 有特定的头部标记（5D 00 00 开头）
                            # - 高熵值（字节分布均匀）
                            # - 在 core.img 的后半部分
                            
                            # 检查前 4KB（通常是未压缩的汇编代码）
                            # 和后 24KB（可能是压缩的 C 代码）
                            front_4k = core_img[:4096]
                            back_24k = core_img[4096:] if len(core_img) > 4096 else b''
                            
                            # 在前 4KB 中查找 LZMA 标记（不应该有）
                            has_lzma_front = b'\x5d\x00\x00' in front_4k or b'LZMA' in front_4k
                            
                            # 在后 24KB 中查找 LZMA 标记（应该有）
                            has_lzma_back = False
                            lzma_back_pos = -1
                            if back_24k:
                                # 查找 LZMA 标记的精确位置
                                lzma_marker = b'\x5d\x00\x00'
                                for i in range(min(len(back_24k), 2048)):  # 检查前 2KB
                                    if back_24k[i:i+3] == lzma_marker:
                                        lzma_back_pos = 4096 + i  # 转换为 core_img 中的绝对位置
                                        has_lzma_back = True
                                        break
                                
                                # 如果没找到标记，检查是否有 LZMA 字符串
                                if not has_lzma_back:
                                    has_lzma_back = b'LZMA' in back_24k[:1024]
                                
                                # 如果找到了 LZMA 标记，更新 lzma_start_pos（如果之前没找到或找到的位置太早）
                                if lzma_back_pos > 0:
                                    if lzma_start_pos <= 0 or lzma_start_pos < 1024:
                                        # 如果之前没找到，或者找到的位置太早（可能是误报），使用后续分析的结果
                                        old_pos = lzma_start_pos
                                        lzma_start_pos = lzma_back_pos
                                        if old_pos > 0:
                                            print(f"\n  ✅ 在后续分析中找到真正的 LZMA 压缩标记：文件偏移 0x{lzma_start_pos:x}（之前找到的 0x{old_pos:x} 可能是误报）")
                                        else:
                                            print(f"\n  ✅ 在后续分析中找到 LZMA 压缩标记：文件偏移 0x{lzma_start_pos:x}，内存地址 0x{0x8000 + lzma_start_pos:x}")
                                        print(f"     这表示压缩的 C 代码从 0x{lzma_start_pos:x} 开始")
                                        print(f"     startup_raw.S 的实际大小：约 {lzma_start_pos - 512} 字节（0x{lzma_start_pos - 512:x} 字节）")
                                        # 更新 startup_raw_end
                                        if startup_raw_end == 4096 or (old_pos > 0 and old_pos < 1024):
                                            startup_raw_end = lzma_start_pos
                                            print(f"     已更新 startup_raw_end = 0x{startup_raw_end:x}")
                                
                                # 计算后 24KB 的熵值
                                byte_freq = [0] * 256
                                sample_size = min(len(back_24k), 8192)  # 采样 8KB
                                for byte in back_24k[:sample_size]:
                                    byte_freq[byte] += 1
                                
                                entropy = 0
                                for freq in byte_freq:
                                    if freq > 0:
                                        p = freq / sample_size
                                        entropy -= p * math.log2(p)
                                
                                # 高熵值（> 7.0）通常表示压缩数据
                                high_entropy = entropy > 7.0
                                
                                # 数据特征分析（startup_raw.S 区域）
                                # 使用实际分析得到的 startup_raw_end，如果还没确定则使用默认值
                                startup_raw_analysis_end = startup_raw_end if startup_raw_end <= len(core_img) else min(2048, len(core_img))
                                if len(core_img) >= startup_raw_analysis_end:
                                    startup_raw_data = core_img[512:startup_raw_analysis_end]  # startup_raw.S 区域
                                    nop_count = startup_raw_data.count(0x90)
                                    zero_count = startup_raw_data.count(0x00)
                                    startup_raw_bytes = len(startup_raw_data)
                                    nop_ratio = (nop_count * 100.0) / startup_raw_bytes if startup_raw_bytes > 0 else 0
                                    zero_ratio = (zero_count * 100.0) / startup_raw_bytes if startup_raw_bytes > 0 else 0
                                    
                                    # 统计可打印字符串
                                    printable_strings = []
                                    current_string = b''
                                    for byte in startup_raw_data:
                                        if 32 <= byte < 127:
                                            current_string += bytes([byte])
                                        else:
                                            if len(current_string) >= 3:
                                                printable_strings.append(current_string.decode('ascii', errors='ignore'))
                                            current_string = b''
                                    if len(current_string) >= 3:
                                        printable_strings.append(current_string.decode('ascii', errors='ignore'))
                                    printable_count = len(printable_strings)
                            
                            # 数据特征分析（startup_raw.S 区域）
                            nop_count = 0
                            zero_count = 0
                            nop_ratio = 0
                            zero_ratio = 0
                            printable_count = 0
                            compression_score = 0
                            
                            # 使用实际分析得到的 startup_raw_end，如果还没确定则使用默认值
                            startup_raw_analysis_end = startup_raw_end if startup_raw_end <= len(core_img) else min(2048, len(core_img))
                            if len(core_img) >= startup_raw_analysis_end:
                                startup_raw_data = core_img[512:startup_raw_analysis_end]  # startup_raw.S 区域
                                nop_count = startup_raw_data.count(0x90)
                                zero_count = startup_raw_data.count(0x00)
                                startup_raw_bytes = len(startup_raw_data)
                                nop_ratio = (nop_count * 100.0) / startup_raw_bytes if startup_raw_bytes > 0 else 0
                                zero_ratio = (zero_count * 100.0) / startup_raw_bytes if startup_raw_bytes > 0 else 0
                                
                                # 统计可打印字符串
                                printable_strings = []
                                current_string = b''
                                for byte in startup_raw_data:
                                    if 32 <= byte < 127:
                                        current_string += bytes([byte])
                                    else:
                                        if len(current_string) >= 3:
                                            printable_strings.append(current_string.decode('ascii', errors='ignore'))
                                        current_string = b''
                                if len(current_string) >= 3:
                                    printable_strings.append(current_string.decode('ascii', errors='ignore'))
                                printable_count = len(printable_strings)
                                
                                # 检查是否有 LZMA 解压函数调用模式（call _LzmaDecodeA）
                                has_lzma_call = False
                                if b'\xe8' in startup_raw_data:  # CALL 指令
                                    # 查找多个连续的 CALL 指令（可能是 LZMA 解压相关）
                                    call_positions = [i for i, b in enumerate(startup_raw_data) if b == 0xE8]
                                    if len(call_positions) >= 3:
                                        has_lzma_call = True
                                
                                # 压缩评分系统
                                if has_lzma_back or b'LZMA' in back_24k[:1024] if back_24k else False:
                                    compression_score += 3
                                if has_lzma_call:
                                    compression_score += 2
                                if zero_ratio < 15:
                                    compression_score += 1
                                if nop_count > 30 or printable_count > 8:
                                    compression_score -= 1
                            
                            # 判断压缩状态
                            # 混合格式：前 4KB 未压缩，后 24KB 压缩
                            is_mixed = not has_lzma_front and (has_lzma_back or (back_24k and high_entropy))
                            is_fully_compressed = has_lzma_back
                            is_uncompressed = not has_lzma_front and not has_lzma_back
                            
                            has_lzma = is_mixed or is_fully_compressed
                            
                            # 2. 查找可能的初始化函数模式
                            # grub_stub_init 通常会调用 grub_main
                            # 查找 CALL 指令后跟可能的 grub_main 地址
                            
                            # 计算实际分析的 startup_raw.S 大小
                            actual_startup_size = startup_raw_end - 512 if startup_raw_end > 512 else (startup_raw_analysis_end - 512 if 'startup_raw_analysis_end' in locals() else 1536)
                            print(f"\n数据特征分析（startup_raw.S 区域，实际大小 {actual_startup_size} 字节）:")
                            if 'startup_raw_data' in locals() and len(startup_raw_data) > 0:
                                print(f"  - 总字节数: {len(startup_raw_data)}")
                                print(f"  - NOP (0x90) 字节数量: {nop_count} ({nop_ratio:.1f}%)")
                                print(f"  - 零字节 (0x00) 数量: {zero_count} ({zero_ratio:.1f}%)")
                                print(f"  - 可打印字符串数量: {printable_count}")
                            else:
                                print(f"  ⚠️  无法分析 startup_raw.S 数据特征（数据未提取）")
                            
                            print(f"\n压缩状态检测:")
                            if compression_score >= 3:
                                print("  ✅ **使用 LZMA 压缩**")
                                print("     - 检测到 LZMA 压缩特征")
                                if has_lzma_back:
                                    print("     - ✅ 已分析到 LZMA 压缩代码部分（在 core.img 的后 24KB 区域）")
                                if has_lzma_call:
                                    print("     - 检测到可能的 LZMA 解压函数调用（在 startup_raw.S 中）")
                                print("     - 解压过程：")
                                print("       1. startup_raw.S 切换到保护模式并启用 A20 地址线")
                                print("       2. 调用 _LzmaDecodeA 函数解压压缩的 C 代码部分")
                                print("       3. 解压目标地址: 0x100000 (1MB)")
                                print("       4. 解压后跳转到 grub_stub_init（解压后的代码入口点）")
                            elif compression_score <= 0 and zero_ratio >= 15:
                                print("  ⚠️  **可能未压缩**")
                                print("     - 检测到未压缩代码特征")
                                if nop_count > 30:
                                    print(f"     - NOP 指令较多 ({nop_count})，符合未压缩代码特征")
                                if printable_count > 8:
                                    print(f"     - 可打印字符串较多 ({printable_count})，符合未压缩代码特征")
                                print(f"     - 零字节比例: {zero_ratio:.1f}% (未压缩代码常有填充的零字节)")
                                print("     - core.img 可能直接在前 1MB 中执行，不需要解压")
                                print("     - 代码位置: 0x8000+ (前 1MB)")
                            elif is_mixed:
                                print("  ✅ 检测到混合格式（前 4KB 未压缩，后 24KB 压缩）")
                                print("  → 前 4KB: diskboot.S + startup_raw.S（未压缩，在 0x8000+）")
                                print("  → 后 24KB: C 代码（LZMA 压缩）")
                                print("  → ✅ 已分析到 LZMA 压缩代码部分（core.img 的后 24KB 区域）")
                                print("  → 解压过程：")
                                print("     1. startup_raw.S 切换到保护模式并启用 A20 地址线")
                                print("     2. 调用 _LzmaDecodeA 函数解压后 24KB 的压缩代码")
                                print("     3. 解压目标地址: 0x100000 (1MB)")
                                print("     4. 解压后跳转到 grub_stub_init（解压后的代码入口点）")
                                print("  → grub_stub_init 在解压后的代码中（0x100000），不在压缩的 core.img 中")
                            elif is_fully_compressed:
                                print("  ✅ 检测到 LZMA 压缩")
                                print("  → 运行时代码入口点: 0x100000 (1MB)")
                                print("  → startup_raw.S 的 jmp *%esi 会跳转到 0x100000")
                            elif is_uncompressed:
                                print("  ⚠️  未检测到 LZMA 压缩（代码未压缩）")
                                print("  → 代码入口点可能在 0x8000+ (前 1MB)")
                                print("  → grub_stub_init 可能在 core.img 的 C 代码区域")
                            else:
                                print("  ❓ **无法确定**")
                                print("     - 数据特征不明显，需要进一步分析")
                                print(f"     - 压缩评分: {compression_score} (>=3 表示压缩，<=0 表示未压缩)")
                                print(f"     - NOP 比例: {nop_ratio:.1f}%")
                                print(f"     - 零字节比例: {zero_ratio:.1f}%")
                                print(f"     - 字符串数量: {printable_count}")
                                print("     - 提示:")
                                print("       * 如果零字节比例 < 15%，可能是压缩的")
                                print("       * 如果零字节比例 >= 15% 且 NOP/字符串较多，可能是未压缩的")
                            
                            # 查找可能的初始化函数特征
                            # 初始化函数通常会：
                            # 1. 调用 grub_mm_init（内存管理初始化）
                            # 2. 调用 grub_main
                            # 3. 包含特定的函数序言（push ebp; mov ebp, esp）
                            
                            print(f"\n查找初始化函数特征:")
                            
                            # 查找 "grub_main" 字符串（如果未压缩）
                            grub_main_pos = core_img.find(b'grub_main')
                            if grub_main_pos != -1:
                                print(f"  ✅ 找到 'grub_main' 字符串在偏移 0x{grub_main_pos:x}")
                                print(f"     → 说明代码可能未压缩，或包含符号信息")
                            
                            # 查找常见的初始化函数序言模式
                            # push ebp; mov ebp, esp (55 8B EC)
                            init_prologue = b'\x55\x8B\xEC'
                            prologue_count = core_img.count(init_prologue)
                            if prologue_count > 0:
                                print(f"  ✅ 找到 {prologue_count} 个函数序言模式 (push ebp; mov ebp, esp)")
                                print(f"     → 说明包含未压缩的 C 代码")
                            
                            # 查找 CALL 指令模式（E8 后跟相对偏移）
                            # 这可能是调用 grub_main 的代码
                            call_patterns = []
                            for i in range(min(len(core_img) - 5, 10000)):  # 只检查前 10KB
                                if core_img[i] == 0xE8:  # CALL rel32
                                    # 读取相对偏移
                                    rel_offset = struct.unpack('<i', core_img[i+1:i+5])[0]
                                    target = i + 5 + rel_offset
                                    if 0 <= target < len(core_img):
                                        call_patterns.append((i, target))
                            
                            if call_patterns:
                                print(f"  ✅ 找到 {len(call_patterns)} 个 CALL 指令模式")
                                print(f"     → 可能包含调用 grub_main 的代码")
                            
                            # 详细反汇编分析
                            print(f"\n" + "="*70)
                            print("详细反汇编分析（查找 grub_stub_init 入口点）")
                            print("="*70)
                            
                            # 尝试使用 objdump 进行反汇编
                            import tempfile
                            with tempfile.NamedTemporaryFile(delete=False, suffix='.bin') as tmp_file:
                                tmp_file.write(core_img)
                                tmp_file_path = tmp_file.name
                            
                            objdump_success = False
                            try:
                                # 使用 objdump 反汇编（32位保护模式代码）
                                # Linux 上的 objdump 使用 -b binary 选项
                                result = subprocess.run(
                                    ['objdump', '-D', '-b', 'binary', '-m', 'i386', '-M', 'intel', tmp_file_path],
                                    capture_output=True,
                                    text=True,
                                    timeout=10
                                )
                                
                                if result.returncode == 0 and result.stdout:
                                    print("\n使用 objdump 反汇编（前 2KB，查找入口点）:")
                                    print("-" * 70)
                                    
                                    lines = result.stdout.split('\n')
                                    printed_lines = 0
                                    max_lines = 100  # 只显示前 100 行
                                    valid_lines_found = False
                                    
                                    # 查找可能的入口点模式
                                    # 1. 函数序言：push ebp; mov ebp, esp
                                    # 2. CALL 指令（可能调用 grub_main）
                                    # 3. 初始化代码模式
                                    
                                    entry_candidates = []
                                    
                                    for i, line in enumerate(lines):
                                        if printed_lines >= max_lines:
                                            break
                                        
                                        # 跳过空行和标题行
                                        if not line.strip():
                                            continue
                                        if line.startswith('Disassembly of section') or line.startswith('file format'):
                                            continue
                                        
                                        # 查找函数序言模式（支持多种格式）
                                        line_lower = line.lower()
                                        if ('push' in line_lower and 'ebp' in line_lower) or ('push' in line_lower and '%ebp' in line_lower):
                                            # 检查下一行是否有 mov ebp, esp
                                            if i+1 < len(lines):
                                                next_line_lower = lines[i+1].lower()
                                                if ('mov' in next_line_lower and 'ebp' in next_line_lower and 'esp' in next_line_lower):
                                                    # 提取地址（Linux objdump 格式：空格 + 数字 + 冒号 或 0x0000:）
                                                    addr_match = re.search(r'(?:^\s+|0x)([0-9a-fA-F]+):', line)
                                                    if addr_match:
                                                        try:
                                                            addr = int(addr_match.group(1), 16)
                                                            entry_candidates.append(addr)
                                                        except:
                                                            pass
                                        
                                        # 查找 CALL 指令（可能调用 grub_main）
                                        if 'call' in line_lower:
                                            parts = line.split()
                                            for part in parts:
                                                if 'call' in part.lower():
                                                    # 找到 CALL 指令，检查目标地址
                                                        if i+1 < len(lines):
                                                            next_line = lines[i+1]
                                                            if 'push' in next_line.lower() or 'mov' in next_line.lower():
                                                                # 可能是函数调用序列
                                                                # Linux objdump 格式：空格 + 数字 + 冒号 或 0x0000:
                                                                addr_match = re.search(r'(?:^\s+|0x)([0-9a-fA-F]+):', line)
                                                                if addr_match:
                                                                    try:
                                                                        addr = int(addr_match.group(1), 16)
                                                                        if addr not in entry_candidates:
                                                                            entry_candidates.append(addr)
                                                                    except:
                                                                        pass
                                        
                                        # 显示前几行反汇编（Linux objdump 格式）
                                        if printed_lines < 50:
                                            # Linux objdump 格式：空格 + 十六进制数字 + 冒号（例如 "   0:" 或 "  200:"）
                                            # 也支持 0x0000: 格式
                                            addr_match = re.search(r'(?:^\s+|0x)([0-9a-fA-F]+):', line)
                                            if addr_match:
                                                try:
                                                    file_offset = int(addr_match.group(1), 16)
                                                    # 如果是压缩的，运行时在 0x100000
                                                    # 如果未压缩，在 0x8000+
                                                    if has_lzma:
                                                        mem_addr = 0x100000 + file_offset
                                                    else:
                                                        mem_addr = 0x8000 + file_offset
                                                    
                                                    # 替换地址为内存地址（支持两种格式）
                                                    # 格式1: "   0:" -> "  0x8000:"
                                                    # 格式2: "0x0000:" -> "0x8000:"
                                                    if line.strip().startswith('0x'):
                                                        line_with_addr = re.sub(r'0x[0-9a-fA-F]+:', f'0x{mem_addr:06x}:', line, count=1)
                                                    else:
                                                        # 匹配开头的空格 + 数字 + 冒号
                                                        line_with_addr = re.sub(r'^\s+([0-9a-fA-F]+):', f'  0x{mem_addr:06x}:', line, count=1)
                                                    print(line_with_addr)
                                                    printed_lines += 1
                                                    valid_lines_found = True
                                                except:
                                                    # 如果解析失败，直接显示原行（前20行）
                                                    if printed_lines < 20:
                                                        print(line)
                                                        printed_lines += 1
                                                        valid_lines_found = True
                                            elif printed_lines < 20 and line.strip() and not line.startswith('Disassembly'):
                                                # 如果没有地址格式，但看起来像反汇编行，也显示
                                                print(line)
                                                printed_lines += 1
                                                valid_lines_found = True
                                    
                                    if not valid_lines_found:
                                        print("⚠️  objdump 输出格式无法解析，回退到简单反汇编分析")
                                        objdump_success = False
                                    else:
                                        objdump_success = True
                                        if entry_candidates:
                                            print(f"\n找到 {len(entry_candidates)} 个可能的入口点候选:")
                                            for addr in entry_candidates[:5]:  # 只显示前5个
                                                if has_lzma:
                                                    mem_addr = 0x100000 + addr
                                                else:
                                                    mem_addr = 0x8000 + addr
                                                print(f"  - 文件偏移 0x{addr:04x} -> 内存地址 0x{mem_addr:06x}")
                                
                                else:
                                    # objdump 执行失败或没有输出
                                    objdump_success = False
                                    if result.stderr:
                                        print(f"⚠️  objdump 错误: {result.stderr[:200]}")
                                    if result.returncode != 0:
                                        print(f"⚠️  objdump 退出码: {result.returncode}")
                                    if not result.stdout:
                                        print("⚠️  objdump 没有输出")
                                    print("使用简单反汇编分析")
                            
                            except FileNotFoundError:
                                objdump_success = False
                                print("⚠️  objdump 未找到，使用简单分析")
                            except Exception as e:
                                objdump_success = False
                                if "objdump output format not recognized" not in str(e):
                                    print(f"⚠️  反汇编时出错: {e}")
                            finally:
                                # 清理临时文件
                                try:
                                    if 'tmp_file_path' in locals():
                                        os.unlink(tmp_file_path)
                                except:
                                    pass
                            
                            # 如果 objdump 失败或输出无法解析，使用简单反汇编
                            if not objdump_success:
                                print("\n简单反汇编分析（查找函数入口点）:")
                                print("-" * 70)
                                
                                # 查找函数序言（push ebp; mov ebp, esp）
                                # 这是 32 位 C 函数的典型序言
                                # 注意：有两种编码方式
                                # - 55 8B EC (Intel 语法)
                                # - 55 89 E5 (AT&T 语法，但二进制相同)
                                prologue_positions = []
                                
                                # 如果代码是压缩的，grub_stub_init 在运行时代码中（0x100000），
                                # 不在压缩的 core.img 中，所以无法直接找到
                                # 只能在前 4KB（未压缩部分）查找
                                
                                search_range = 4096 if is_mixed else min(len(core_img) - 3, 16384)
                                for i in range(search_range):
                                    # 查找两种可能的函数序言模式
                                    if (core_img[i:i+3] == b'\x55\x8B\xEC' or  # push ebp; mov ebp, esp (Intel)
                                        core_img[i:i+3] == b'\x55\x89\xE5'):   # push ebp; mov ebp, esp (AT&T，但二进制相同)
                                        prologue_positions.append(i)
                                
                                if prologue_positions:
                                    print(f"  找到 {len(prologue_positions)} 个函数序言 (push ebp; mov ebp, esp):")
                                    for pos in prologue_positions[:10]:  # 只显示前10个
                                        # 内存地址取决于压缩状态
                                        if is_mixed or is_fully_compressed:
                                            # 压缩的代码：这些函数序言在未压缩的前 4KB 中（startup_raw.S 的辅助函数）
                                            # 真正的 grub_stub_init 在解压后的代码中（0x100000），不在压缩的 core.img 中
                                            mem_addr = 0x8000 + pos
                                        else:
                                            mem_addr = 0x8000 + pos
                                        print(f"    - 偏移 0x{pos:04x} -> 内存地址 0x{mem_addr:06x}")
                                    
                                    if is_mixed or is_fully_compressed:
                                        print(f"\n  ⚠️  注意：这些函数序言在未压缩的前 4KB 中（startup_raw.S 的辅助函数）")
                                        print(f"     grub_stub_init 在运行时代码中（0x100000），不在压缩的 core.img 中")
                                        print(f"     要找到 grub_stub_init，需要在实际运行时查看 0x100000 处的代码")
                                
                                # 查找可能的 grub_stub_init 入口点
                                # 通常在 startup_raw.S 之后，C 代码开始的地方
                                # 查找模式：函数序言后跟 CALL 指令（可能调用 grub_mm_init 或 grub_main）
                                print(f"\n  分析可能的 grub_stub_init 入口点:")
                                print(f"  - 查找函数序言后跟 CALL 指令的模式")
                                print(f"  - 查找调用 grub_main 的代码")
                                
                                # 分析 core.img 的结构
                                # diskboot.S: 0-512 字节
                                # startup_raw.S: 512-4096 字节（约 3.5KB）
                                # C 代码: 4096+ 字节（如果未压缩）或压缩数据
                                
                                # 查找所有函数序言的位置
                                print(f"\n  函数序言位置分析:")
                                diskboot_end = 512
                                startup_raw_end = 4096  # startup_raw.S 大约 3-4KB
                                
                                diskboot_funcs = [p for p in prologue_positions if p < diskboot_end]
                                startup_funcs = [p for p in prologue_positions if diskboot_end <= p < startup_raw_end]
                                c_funcs = [p for p in prologue_positions if p >= startup_raw_end]
                                
                                print(f"    - diskboot.S 区域 (0-512): {len(diskboot_funcs)} 个")
                                print(f"    - startup_raw.S 区域 (512-4096): {len(startup_funcs)} 个")
                                print(f"    - C 代码区域 (4096+): {len(c_funcs)} 个")
                                
                                # 查找第一个 C 函数（可能是 grub_stub_init）
                                first_c_function = None
                                if c_funcs:
                                    first_c_function = c_funcs[0]
                                elif startup_funcs:
                                    # 如果 C 代码区域没有找到，可能在 startup_raw.S 的末尾
                                    # 检查最后一个 startup_raw.S 函数
                                    last_startup = startup_funcs[-1]
                                    # 如果这个函数后面有足够的空间，可能是 C 代码
                                    if last_startup + 100 < len(core_img):
                                        first_c_function = last_startup
                                
                                # 分析找到的函数序言
                                if c_funcs:
                                    first_c_function = c_funcs[0]
                                    if has_lzma:
                                        mem_addr = 0x100000 + first_c_function
                                        print(f"  ✅ 可能的 grub_stub_init 入口点（运行时）:")
                                    else:
                                        mem_addr = 0x8000 + first_c_function
                                        print(f"  ✅ 可能的 grub_stub_init 入口点（未压缩）:")
                                    
                                    print(f"     文件偏移: 0x{first_c_function:04x}")
                                    print(f"     内存地址: 0x{mem_addr:06x}")
                                    print(f"     说明: 这是 startup_raw.S 之后的第一个 C 函数序言")
                                    
                                    # 显示该函数的前几行代码（反汇编）
                                    print(f"\n     函数开头代码（前 128 字节，反汇编）:")
                                    func_start = first_c_function
                                    func_end = min(func_start + 128, len(core_img))
                                    
                                    # 简单反汇编
                                    i = func_start
                                    disasm_lines = []
                                    while i < func_end and len(disasm_lines) < 20:
                                        byte = core_img[i]
                                        if has_lzma:
                                            mem_addr = 0x100000 + i
                                        else:
                                            mem_addr = 0x8000 + i
                                        
                                        # 识别常见指令
                                        if byte == 0x55 and i+2 < len(core_img) and core_img[i+1] in [0x8B, 0x89] and core_img[i+2] == 0xE5:
                                            disasm_lines.append(f"       0x{mem_addr:06x}: 55 89 e5          push ebp; mov ebp, esp")
                                            i += 3
                                        elif byte == 0x83 and i+2 < len(core_img) and core_img[i+1] == 0xEC:
                                            imm = core_img[i+2]
                                            disasm_lines.append(f"       0x{mem_addr:06x}: 83 ec {imm:02x}          sub esp, 0x{imm:x}")
                                            i += 3
                                        elif byte == 0xE8 and i+4 < len(core_img):  # CALL rel32
                                            rel_offset = struct.unpack('<i', core_img[i+1:i+5])[0]
                                            target = i + 5 + rel_offset
                                            if has_lzma:
                                                target_mem = 0x100000 + target
                                            else:
                                                target_mem = 0x8000 + target
                                            disasm_lines.append(f"       0x{mem_addr:06x}: e8 {core_img[i+1]:02x} {core_img[i+2]:02x} {core_img[i+3]:02x} {core_img[i+4]:02x}    call 0x{target_mem:06x}")
                                            i += 5
                                        elif byte == 0xC3:  # RET
                                            disasm_lines.append(f"       0x{mem_addr:06x}: c3                   ret")
                                            i += 1
                                        elif byte == 0x31 and i+1 < len(core_img):  # XOR
                                            modrm = core_img[i+1]
                                            disasm_lines.append(f"       0x{mem_addr:06x}: 31 {modrm:02x}                xor ...")
                                            i += 2
                                        elif byte == 0x89 and i+1 < len(core_img):  # MOV
                                            modrm = core_img[i+1]
                                            disasm_lines.append(f"       0x{mem_addr:06x}: 89 {modrm:02x}                mov ...")
                                            i += 2
                                        elif byte == 0x8B and i+1 < len(core_img):  # MOV
                                            modrm = core_img[i+1]
                                            disasm_lines.append(f"       0x{mem_addr:06x}: 8b {modrm:02x}                mov ...")
                                            i += 2
                                        else:
                                            hex_str = f'{byte:02x}'
                                            disasm_lines.append(f"       0x{mem_addr:06x}: {hex_str}                   db 0x{byte:02x}")
                                            i += 1
                                    
                                    for line in disasm_lines:
                                        print(line)
                                    
                                    # 查找该函数中的 CALL 指令
                                    call_in_func = []
                                    for i in range(first_c_function, min(first_c_function + 500, len(core_img) - 5)):
                                        if core_img[i] == 0xE8:  # CALL rel32
                                            rel_offset = struct.unpack('<i', core_img[i+1:i+5])[0]
                                            target = i + 5 + rel_offset
                                            if 0 <= target < len(core_img):
                                                call_in_func.append((i, target))
                                    
                                    if call_in_func:
                                        print(f"\n     函数中的 CALL 指令（可能调用 grub_main 或其他函数）:")
                                        for call_idx, (call_pos, target_pos) in enumerate(call_in_func[:5], 1):
                                            if has_lzma:
                                                call_mem = 0x100000 + call_pos
                                                target_mem = 0x100000 + target_pos
                                            else:
                                                call_mem = 0x8000 + call_pos
                                                target_mem = 0x8000 + target_pos
                                            print(f"       CALL {call_idx}: 0x{call_mem:06x} -> 0x{target_mem:06x}")
                                            # 检查目标地址附近是否有函数序言（可能是被调用的函数）
                                            if target_pos + 3 < len(core_img):
                                                if (core_img[target_pos:target_pos+3] == b'\x55\x8B\xEC' or
                                                    core_img[target_pos:target_pos+3] == b'\x55\x89\xE5'):
                                                    print(f"         → 目标地址有函数序言，可能是函数入口点")
                                elif startup_funcs:
                                    # 如果 C 代码区域没有找到，但 startup_raw.S 区域有函数序言
                                    # 可能是内联函数或辅助函数
                                    print(f"  ⚠️  在 startup_raw.S 区域找到 {len(startup_funcs)} 个函数序言")
                                    print(f"     这些可能是 startup_raw.S 中的辅助函数，不是 grub_stub_init")
                                    print(f"     如果代码被压缩，grub_stub_init 在运行时代码中（0x100000）")
                                else:
                                    print(f"  ⚠️  未找到函数序言")
                                    print(f"     可能原因:")
                                    print(f"     1. 代码被压缩，grub_stub_init 在运行时代码中（0x100000）")
                                    print(f"     2. 使用不同的函数序言模式")
                                    print(f"     3. 代码是混合格式（前部分未压缩，后部分压缩）")
                                
                                # 显示前 512 字节的十六进制（diskboot.S，内存地址 0x8000）
                                print(f"\n前 512 字节（diskboot.S 区域，内存地址 0x8000）:")
                                for i in range(0, min(512, len(core_img)), 16):
                                    hex_part = ' '.join(f'{b:02x}' for b in core_img[i:i+16])
                                    ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in core_img[i:i+16])
                                    mem_addr = 0x8000 + i
                                    print(f"  0x{mem_addr:06x}: {hex_part:<48} | {ascii_part}")
                                
                                # 显示 startup_raw.S 区域（512-4096 字节，内存地址 0x8200+）
                                if len(core_img) > 512:
                                    print(f"\n512-2048 字节（startup_raw.S 区域，内存地址 0x8200+）:")
                                    for i in range(512, min(2048, len(core_img)), 16):
                                        hex_part = ' '.join(f'{b:02x}' for b in core_img[i:i+16])
                                        ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in core_img[i:i+16])
                                        mem_addr = 0x8000 + i
                                        print(f"  0x{mem_addr:06x}: {hex_part:<48} | {ascii_part}")
                                
                                # 如果代码是压缩的，说明 grub_stub_init 的位置
                                if is_mixed or is_fully_compressed:
                                    print(f"\n⚠️  重要说明：")
                                    print(f"   - core.img 的后 24KB 是 LZMA 压缩的 C 代码")
                                    print(f"   - grub_stub_init 在运行时代码中，不在压缩的 core.img 中")
                                    print(f"   - 运行时代码位置: 0x100000 (1MB)")
                                    print(f"   - startup_raw.S 的 jmp *%esi 会跳转到运行时代码（0x100000）")
                                    print(f"   - 要查看 grub_stub_init 的具体指令，需要在实际运行时查看 0x100000 处的代码")
                                    print(f"   - 运行时代码入口点（grub_stub_init）通常在 0x100000 附近")
                            
                            # 查找可能的 grub_stub_init 特征
                            print(f"\n查找 grub_stub_init 特征:")
                            print("-" * 70)
                            
                            # 1. 查找调用 grub_main 的模式
                            # grub_stub_init 通常会调用 grub_main
                            # 查找 CALL 指令，然后检查目标地址附近是否有 grub_main 相关代码
                            
                            # 2. 查找初始化序列
                            # 通常初始化函数会：
                            # - push ebp; mov ebp, esp (函数序言)
                            # - 调用 grub_mm_init
                            # - 调用 grub_main
                            
                            init_sequences = []
                            for i in range(min(len(core_img) - 10, 8192)):  # 检查前 8KB
                                # 查找函数序言
                                if core_img[i:i+3] == b'\x55\x8B\xEC':  # push ebp; mov ebp, esp
                                    # 检查后续是否有 CALL 指令
                                    for j in range(i+3, min(i+100, len(core_img) - 5)):
                                        if core_img[j] == 0xE8:  # CALL rel32
                                            rel_offset = struct.unpack('<i', core_img[j+1:j+5])[0]
                                            target = j + 5 + rel_offset
                                            if 0 <= target < len(core_img):
                                                init_sequences.append((i, j, target))
                                                if len(init_sequences) >= 5:
                                                    break
                                    if len(init_sequences) >= 5:
                                        break
                            
                            if init_sequences:
                                print(f"  找到 {len(init_sequences)} 个可能的初始化函数序列:")
                                for seq_idx, (prologue_addr, call_addr, target_addr) in enumerate(init_sequences[:3], 1):
                                    if has_lzma:
                                        prologue_mem = 0x100000 + prologue_addr
                                        call_mem = 0x100000 + call_addr
                                        target_mem = 0x100000 + target_addr
                                    else:
                                        prologue_mem = 0x8000 + prologue_addr
                                        call_mem = 0x8000 + call_addr
                                        target_mem = 0x8000 + target_addr
                                    
                                    print(f"\n  候选 {seq_idx}:")
                                    print(f"    函数序言: 偏移 0x{prologue_addr:04x} (内存 0x{prologue_mem:06x})")
                                    print(f"    CALL 指令: 偏移 0x{call_addr:04x} (内存 0x{call_mem:06x})")
                                    print(f"    目标地址: 偏移 0x{target_addr:04x} (内存 0x{target_mem:06x})")
                                    print(f"    → 这可能是 grub_stub_init() 调用 grub_main() 的位置")
                            
                            # 总结
                            print(f"\n" + "="*70)
                            print("入口点验证总结:")
                            print("="*70)
                            
                            if is_mixed:
                                print("  ✅ 检测到混合格式（前 4KB 未压缩，后 24KB 压缩）")
                                print("  ✅ 运行时代码入口点: 0x100000 (1MB)")
                                print("  ✅ startup_raw.S 的 jmp *%esi 会跳转到运行时代码（0x100000）")
                                print("  ⚠️  grub_stub_init 在运行时代码中，不在压缩的 core.img 中")
                                print("  ⚠️  无法在压缩的 core.img 中直接查看 grub_stub_init 的指令")
                                print("  💡 要查看 grub_stub_init 的具体指令，需要：")
                                print("     1. 在实际运行环境中使用调试器查看 0x100000 处的代码")
                                print("     2. 或者查看 GRUB 源代码：grub/grub-core/kern/i386/pc/init.c")
                            elif is_fully_compressed:
                                print("  ✅ 使用 LZMA 压缩")
                                print("  ✅ 运行时代码入口点: 0x100000 (1MB)")
                                print("  ✅ startup_raw.S 的 jmp *%esi 会跳转到运行时代码")
                                print("  ⚠️  grub_stub_init 在运行时代码中，不在压缩的 core.img 中")
                            elif is_uncompressed:
                                print("  ✅ 代码未压缩")
                                print("  ✅ 代码入口点: 0x8000+ (前 1MB)")
                                if init_sequences:
                                    prologue_addr = init_sequences[0][0]
                                    mem_addr = 0x8000 + prologue_addr
                                    print(f"  ✅ 可能的 grub_stub_init 入口点: 0x{mem_addr:06x} (文件偏移 0x{prologue_addr:04x})")
                                else:
                                    print("  ✅ 入口点通常是 grub_stub_init() 或类似的初始化函数")
                            else:
                                print("  ⚠️  压缩状态不确定")
                                print("  ✅ 代码入口点可能在 0x8000+ 或 0x100000")
                            
                            print(f"\n  📝 说明：")
                            print(f"     - startup_raw.S 的 jmp *%esi 跳转到运行时代码入口点")
                            print(f"     - 入口点通常是 grub_stub_init() 或类似的初始化函数")
                            print(f"     - grub_stub_init 会调用 grub_main()（main.c）")
                            print(f"     - grub_main() 会解析 grub.cfg 并调用 grub_cmd_linux()（linux.c）")
                            
                        else:
                            print(f"  ⚠️  提取的 core.img 大小不匹配（期望 {core_img_size}，实际 {len(core_img)}）")
                    except Exception as e:
                        print(f"  ⚠️  提取完整 core.img 时出错: {e}")
                else:
                    print("  ⚠️  无法从块列表确定 core.img 大小")
            else:
                print("  ⚠️  无法读取 core.img 第一个扇区")
        except Exception as e:
            print(f"  ⚠️  提取 core.img 时出错: {e}")
    else:
        print("  ⚠️  无法确定 kernel_sector，跳过 core.img 验证")
    
    print("\n" + "="*70)
    print("验证总结:")
    print("="*70)
    print("✅ 引导扇区签名: 0xAA55")
    print("✅ 引导扇区大小: 512 字节")
    if kernel_sector:
        print(f"✅ kernel_sector: {kernel_sector}")
        print("✅ core.img 入口点验证完成")
    print("\n提示: 所有 GRUB 分析功能已整合到此脚本中")
    
    return True

if __name__ == '__main__':
    iso_file = '../grub.iso'
    
    if len(sys.argv) > 1:
        iso_file = sys.argv[1]
    
    success = verify_grub_boot_sector(iso_file)
    sys.exit(0 if success else 1)
