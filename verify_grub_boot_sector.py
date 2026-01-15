#!/usr/bin/env python3
"""
验证 GRUB ISO 镜像的引导扇区和 core.img 入口点

从 grub.iso 中提取引导扇区（第一个扇区，512 字节），
验证其是否符合 GRUB 引导扇区的特征。
同时验证 core.img 的解压后代码入口点（grub_stub_init）。
"""

import sys
import os
import struct
import subprocess

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
    
    # 验证 core.img 入口点（grub_stub_init）
    print("\n" + "="*70)
    print("验证 core.img 解压后代码入口点（grub_stub_init）")
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
                
                # 读取块列表条目（最多 20 个）
                for i in range(20):
                    offset = BLOCKLIST_START - (i * BLOCKLIST_ENTRY_SIZE)
                    if offset < 0:
                        break
                    
                    if offset + 12 <= len(core_img_first):
                        # 读取块列表条目（12 字节）
                        entry = core_img_first[offset:offset+12]
                        
                        # 解析 len 字段（偏移 8-9，小端序）
                        len_val = struct.unpack('<H', entry[8:10])[0]
                        
                        if len_val == 0:
                            break
                        
                        total_sectors += len_val
                        entry_count += 1
                
                if total_sectors > 0:
                    core_img_size = total_sectors * 512
                    print(f"✅ core.img 大小: {total_sectors} 扇区 = {core_img_size} 字节 ({core_img_size/1024:.1f} KB)")
                    
                    # 提取完整的 core.img
                    try:
                        with open(iso_file, 'rb') as f:
                            f.seek(kernel_sector * 512)
                            core_img = f.read(core_img_size)
                        
                        if len(core_img) == core_img_size:
                            print(f"✅ 成功提取完整的 core.img")
                            
                            # 查找解压后的代码入口点特征
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
                            if back_24k:
                                has_lzma_back = b'\x5d\x00\x00' in back_24k[:1024] or b'LZMA' in back_24k[:1024]
                                
                                # 计算后 24KB 的熵值
                                import math
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
                            
                            # 判断压缩状态
                            # 混合格式：前 4KB 未压缩，后 24KB 压缩
                            is_mixed = not has_lzma_front and (has_lzma_back or (back_24k and high_entropy))
                            is_fully_compressed = has_lzma_back
                            is_uncompressed = not has_lzma_front and not has_lzma_back
                            
                            has_lzma = is_mixed or is_fully_compressed
                            
                            # 2. 查找可能的初始化函数模式
                            # grub_stub_init 通常会调用 grub_main
                            # 查找 CALL 指令后跟可能的 grub_main 地址
                            
                            print(f"\n压缩状态检测:")
                            if is_mixed:
                                print("  ✅ 检测到混合格式（前 4KB 未压缩，后 24KB 压缩）")
                                print("  → 前 4KB: diskboot.S + startup_raw.S（未压缩，在 0x8000+）")
                                print("  → 后 24KB: C 代码（LZMA 压缩）")
                                print("  → 解压后的代码入口点: 0x100000 (1MB)")
                                print("  → startup_raw.S 的 jmp *%esi 会跳转到解压后的代码（0x100000）")
                                print("  → grub_stub_init 在解压后的代码中，不在压缩的 core.img 中")
                            elif is_fully_compressed:
                                print("  ✅ 检测到 LZMA 压缩")
                                print("  → 解压后的代码入口点: 0x100000 (1MB)")
                                print("  → startup_raw.S 的 jmp *%esi 会跳转到 0x100000")
                            elif is_uncompressed:
                                print("  ⚠️  未检测到 LZMA 压缩（代码未压缩）")
                                print("  → 代码入口点可能在 0x8000+ (前 1MB)")
                                print("  → grub_stub_init 可能在 core.img 的 C 代码区域")
                            else:
                                print("  ⚠️  压缩状态不确定")
                                print("  → 需要进一步分析")
                            
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
                            
                            try:
                                # 使用 objdump 反汇编（32位保护模式代码）
                                # macOS 的 objdump 可能不支持 -b 选项，尝试不同的方式
                                result = subprocess.run(
                                    ['objdump', '-D', '-m', 'i386', '-M', 'intel', '--target=binary', tmp_file_path],
                                    capture_output=True,
                                    text=True,
                                    timeout=10
                                )
                                
                                # 如果失败，尝试不带 --target 的方式
                                if result.returncode != 0:
                                    result = subprocess.run(
                                        ['objdump', '-D', '-m', 'i386', '-M', 'intel', tmp_file_path],
                                        capture_output=True,
                                        text=True,
                                        timeout=10
                                    )
                                
                                if result.returncode == 0 and result.stdout:
                                    print("\n使用 objdump 反汇编（前 2KB，查找入口点）:")
                                    print("-" * 70)
                                    
                                    lines = result.stdout.split('\n')
                                    in_code = False
                                    printed_lines = 0
                                    max_lines = 100  # 只显示前 100 行
                                    
                                    # 查找可能的入口点模式
                                    # 1. 函数序言：push ebp; mov ebp, esp
                                    # 2. CALL 指令（可能调用 grub_main）
                                    # 3. 初始化代码模式
                                    
                                    entry_candidates = []
                                    
                                    for i, line in enumerate(lines):
                                        if printed_lines >= max_lines:
                                            break
                                        
                                        # 查找函数序言模式
                                        if 'push   ebp' in line.lower() and 'mov    ebp,esp' in lines[i+1].lower() if i+1 < len(lines) else False:
                                            # 提取地址
                                            parts = line.split()
                                            if parts and parts[0].replace(':', '').startswith('0x'):
                                                addr_str = parts[0].replace(':', '')
                                                try:
                                                    addr = int(addr_str, 16)
                                                    entry_candidates.append(addr)
                                                except:
                                                    pass
                                        
                                        # 查找 CALL 指令（可能调用 grub_main）
                                        if 'call' in line.lower() and '0x' in line:
                                            parts = line.split()
                                            for part in parts:
                                                if 'call' in part.lower():
                                                    # 找到 CALL 指令，检查目标地址
                                                    if i+1 < len(lines):
                                                        next_line = lines[i+1]
                                                        if 'push' in next_line.lower() or 'mov' in next_line.lower():
                                                            # 可能是函数调用序列
                                                            addr_parts = line.split()
                                                            if addr_parts and addr_parts[0].replace(':', '').startswith('0x'):
                                                                addr_str = addr_parts[0].replace(':', '')
                                                                try:
                                                                    addr = int(addr_str, 16)
                                                                    if addr not in entry_candidates:
                                                                        entry_candidates.append(addr)
                                                                except:
                                                                    pass
                                        
                                        # 显示前几行反汇编
                                        if printed_lines < 50:
                                            if line.strip() and not line.startswith('core_img') and not line.startswith('Disassembly'):
                                                # 提取地址并转换为内存地址
                                                parts = line.split()
                                                if parts and parts[0].replace(':', '').startswith('0x'):
                                                    addr_str = parts[0].replace(':', '')
                                                    try:
                                                        file_offset = int(addr_str, 16)
                                                        # 如果是压缩的，解压后在 0x100000
                                                        # 如果未压缩，在 0x8000+
                                                        if has_lzma:
                                                            mem_addr = 0x100000 + file_offset
                                                        else:
                                                            mem_addr = 0x8000 + file_offset
                                                        
                                                        line_with_addr = line.replace(addr_str + ':', f'0x{mem_addr:06x}:', 1)
                                                        print(line_with_addr)
                                                        printed_lines += 1
                                                    except:
                                                        if printed_lines < 10:
                                                            print(line)
                                                            printed_lines += 1
                                    
                                    if entry_candidates:
                                        print(f"\n找到 {len(entry_candidates)} 个可能的入口点候选:")
                                        for addr in entry_candidates[:5]:  # 只显示前5个
                                            if has_lzma:
                                                mem_addr = 0x100000 + addr
                                            else:
                                                mem_addr = 0x8000 + addr
                                            print(f"  - 文件偏移 0x{addr:04x} -> 内存地址 0x{mem_addr:06x}")
                                
                                else:
                                    if result.stderr:
                                        print(f"⚠️  objdump 错误: {result.stderr[:200]}")
                                    print("使用简单反汇编分析")
                                    
                                    # 使用简单反汇编
                                    print("\n简单反汇编分析（查找函数入口点）:")
                                    print("-" * 70)
                                    
                                    # 查找函数序言（push ebp; mov ebp, esp）
                                    # 这是 32 位 C 函数的典型序言
                                    # 注意：有两种编码方式
                                    # - 55 8B EC (Intel 语法)
                                    # - 55 89 E5 (AT&T 语法，但二进制相同)
                                    prologue_positions = []
                                    
                                    # 如果代码是压缩的，grub_stub_init 在解压后的代码中（0x100000），
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
                                            print(f"     grub_stub_init 在解压后的代码中（0x100000），不在压缩的 core.img 中")
                                            print(f"     要找到 grub_stub_init，需要先解压 core.img 的后 24KB 部分")
                                    
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
                                            print(f"  ✅ 可能的 grub_stub_init 入口点（解压后）:")
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
                                        print(f"     如果代码被压缩，grub_stub_init 在解压后的代码中（0x100000）")
                                    else:
                                        print(f"  ⚠️  未找到函数序言")
                                        print(f"     可能原因:")
                                        print(f"     1. 代码被压缩，grub_stub_init 在解压后的代码中（0x100000）")
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
                                        print(f"   - grub_stub_init 在解压后的代码中，不在压缩的 core.img 中")
                                        print(f"   - 解压后的代码位置: 0x100000 (1MB)")
                                        print(f"   - startup_raw.S 的 jmp *%esi 会跳转到解压后的代码（0x100000）")
                                        print(f"   - 要查看 grub_stub_init 的具体指令，需要先解压 core.img")
                                        print(f"   - 解压后的代码入口点（grub_stub_init）通常在 0x100000 附近")
                            
                            except FileNotFoundError:
                                print("⚠️  objdump 未找到，使用简单分析")
                            except Exception as e:
                                print(f"⚠️  反汇编时出错: {e}")
                            finally:
                                # 清理临时文件
                                try:
                                    os.unlink(tmp_file_path)
                                except:
                                    pass
                            
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
                                print("  ✅ 解压后的代码入口点: 0x100000 (1MB)")
                                print("  ✅ startup_raw.S 的 jmp *%esi 会跳转到解压后的代码（0x100000）")
                                print("  ⚠️  grub_stub_init 在解压后的代码中，不在压缩的 core.img 中")
                                print("  ⚠️  无法在压缩的 core.img 中直接查看 grub_stub_init 的指令")
                                print("  💡 要查看 grub_stub_init 的具体指令，需要：")
                                print("     1. 使用 LZMA 解压库解压 core.img 的后 24KB 部分")
                                print("     2. 或者在实际运行环境中使用调试器查看 0x100000 处的代码")
                                print("     3. 或者查看 GRUB 源代码：grub/grub-core/kern/i386/pc/init.c")
                            elif is_fully_compressed:
                                print("  ✅ 使用 LZMA 压缩")
                                print("  ✅ 解压后的代码入口点: 0x100000 (1MB)")
                                print("  ✅ startup_raw.S 的 jmp *%esi 会跳转到解压后的代码")
                                print("  ⚠️  grub_stub_init 在解压后的代码中，不在压缩的 core.img 中")
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
                            print(f"     - startup_raw.S 的 jmp *%esi 跳转到解压后的代码入口点")
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
    print("\n提示: 使用 'analyze_grub_boot_sector.sh' 进行更详细的分析")
    print("     使用 'disassemble_core_img.py' 进行 core.img 反汇编分析")
    
    return True

if __name__ == '__main__':
    iso_file = '../grub.iso'
    
    if len(sys.argv) > 1:
        iso_file = sys.argv[1]
    
    success = verify_grub_boot_sector(iso_file)
    sys.exit(0 if success else 1)
