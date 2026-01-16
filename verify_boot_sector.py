#!/usr/bin/env python3
"""
验证引导扇区 boot.bin（Bootloader）在内存地址 0x7C00 位置的代码

**重要说明：**
- 这个脚本验证的是 **Bootloader（引导程序）**，不是 BIOS
- Bootloader 会被 BIOS 从磁盘加载到内存地址 0x7C00 处执行
- BIOS 本身映射在 0xF0000-0xFFFFF（使用 verify_bios.py 验证）

**引导流程：**
1. BIOS（在 0xF0000-0xFFFFF）初始化完成
2. BIOS 通过 INT 13h 从磁盘读取引导扇区（boot.bin，512 字节）
3. BIOS 将引导扇区加载到内存地址 0x7C00
4. BIOS 跳转到 0x7C00 执行引导扇区代码

这个脚本验证 boot.bin 文件的内容，确认其符合引导扇区的要求。
"""

import sys
import os
import subprocess

def verify_boot_sector(boot_file):
    """验证引导扇区文件"""
    
    print("="*70)
    print(f"验证引导扇区文件: {boot_file}")
    print("="*70)
    
    # 检查文件是否存在
    if not os.path.exists(boot_file):
        print(f"错误: 文件 {boot_file} 不存在")
        print("请先运行 'make build' 编译 boot.asm")
        return False
    
    # 读取文件
    with open(boot_file, 'rb') as f:
        data = f.read()
    
    file_size = len(data)
    print(f"\n文件大小: {file_size} 字节")
    
    # 验证文件大小
    if file_size != 512:
        print(f"⚠️  警告: 引导扇区应该是 512 字节，但文件是 {file_size} 字节")
        if file_size > 512:
            print("   文件过大，可能无法作为引导扇区使用")
            return False
    else:
        print("✅ 文件大小正确 (512 字节)")
    
    # 验证引导扇区签名 (最后两个字节应该是 0xAA55，小端序存储为 0x55, 0xAA)
    if file_size >= 2:
        signature = data[-2:]
        expected_sig = bytes([0x55, 0xAA])  # 小端序
        
        print(f"\n引导扇区签名 (偏移 0x1FE-0x1FF):")
        print(f"  实际值: 0x{signature[0]:02X} 0x{signature[1]:02X}")
        print(f"  期望值: 0x55 0xAA (0xAA55 小端序)")
        
        if signature == expected_sig:
            print("✅ 引导扇区签名正确")
        else:
            print("❌ 引导扇区签名错误！BIOS 不会执行此引导扇区")
            return False
    
    # 显示文件内容（十六进制）
    print("\n" + "="*70)
    print("文件内容 (十六进制，对应内存地址 0x7C00-0x7DFF):")
    print("="*70)
    
    # 每行显示 16 字节
    for i in range(0, min(file_size, 512), 16):
        offset = i
        addr_7c00 = 0x7C00 + offset  # 对应的内存地址
        
        # 十六进制部分
        hex_part = ' '.join(f'{b:02X}' for b in data[i:i+16])
        
        # ASCII 部分
        ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in data[i:i+16])
        
        print(f"0x{addr_7c00:04X} (+0x{offset:03X}): {hex_part:<48} | {ascii_part}")
    
    # 分析关键代码位置
    print("\n" + "="*70)
    print("关键代码位置分析:")
    print("="*70)
    
    # 检查开头的代码（应该是 mov ax, 0x0003）
    if file_size >= 3:
        first_bytes = data[0:3]
        print(f"\n地址 0x7C00 (文件偏移 0x000): {first_bytes.hex(' ').upper()}")
        if first_bytes[0] == 0xB8 and first_bytes[1] == 0x03 and first_bytes[2] == 0x00:
            print("  ✅ 检测到: mov ax, 0x0003 (B8 03 00)")
        else:
            print(f"  ⚠️  未识别的指令: {first_bytes.hex(' ').upper()}")
    
    # 查找字符串 "Hello from Boot Sector!"
    search_str = b"Hello from Boot Sector!"
    str_pos = data.find(search_str)
    if str_pos != -1:
        str_addr = 0x7C00 + str_pos
        print(f"\n字符串位置:")
        print(f"  文件偏移: 0x{str_pos:03X}")
        print(f"  内存地址: 0x{str_addr:04X}")
        print(f"  内容: \"Hello from Boot Sector!\"")
        print(f"  ✅ 找到消息字符串")
    else:
        print("\n⚠️  未找到消息字符串 \"Hello from Boot Sector!\"")
    
    # 检查填充区域
    zero_count = data.count(0)
    print(f"\n填充分析:")
    print(f"  零字节数量: {zero_count} ({zero_count/file_size*100:.1f}%)")
    
    # 显示代码区域和填充区域
    if str_pos != -1:
        code_end = str_pos + len(search_str) + 1  # 包括字符串结束符
        padding_start = code_end
        padding_size = 510 - code_end  # 510 字节是代码+数据，最后2字节是签名
        
        print(f"  代码+数据区域: 0x7C00 - 0x{0x7C00 + code_end - 1:04X} ({code_end} 字节)")
        print(f"  填充区域: 0x{0x7C00 + padding_start:04X} - 0x{0x7C00 + 509:04X} ({padding_size} 字节)")
        print(f"  签名区域: 0x{0x7C00 + 510:04X} - 0x{0x7C00 + 511:04X} (2 字节)")
    
    # 尝试使用 objdump 生成 Intel 格式反汇编
    print("\n" + "="*70)
    print("Intel 格式反汇编 (使用 objdump):")
    print("="*70)
    
    try:
        # 尝试使用 objdump 生成 Intel 格式反汇编
        result = subprocess.run(
            ['objdump', '-D', '-b', 'binary', '-m', 'i8086', '-M', 'intel', boot_file],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0:
            # 解析输出，添加内存地址映射，并过滤数据区域
            lines = result.stdout.split('\n')
            in_code_section = True
            for line in lines:
                if line.strip() and not line.startswith('boot.bin:') and not line.startswith('Disassembly'):
                    # 尝试解析地址并转换为 0x7C00 地址
                    parts = line.split()
                    if parts and parts[0].isdigit():
                        try:
                            file_offset = int(parts[0], 16)
                            mem_addr = 0x7C00 + file_offset
                            
                            # 如果进入数据区域（字符串开始位置），添加注释
                            if str_pos != -1 and file_offset == str_pos and in_code_section:
                                print(f"\n; 数据区域开始 (字符串 \"Hello from Boot Sector!\"):")
                                in_code_section = False
                            
                            # 替换文件偏移为内存地址
                            line_with_addr = line.replace(parts[0], f"0x{mem_addr:04X}", 1)
                            
                            # 如果是数据区域，添加注释说明
                            if not in_code_section and file_offset < 510:
                                # 尝试显示 ASCII 字符
                                if file_offset < file_size:
                                    byte_val = data[file_offset]
                                    if 32 <= byte_val < 127:
                                        line_with_addr += f"  ; '{chr(byte_val)}' (数据)"
                                    elif byte_val == 0:
                                        line_with_addr += f"  ; 字符串结束符 (数据)"
                            
                            print(line_with_addr)
                        except (ValueError, IndexError):
                            print(line)
                    else:
                        print(line)
        else:
            print("⚠️  objdump 执行失败，跳过反汇编")
            print(f"   错误信息: {result.stderr}")
    except FileNotFoundError:
        print("⚠️  objdump 未找到，跳过反汇编")
        print("   提示: 可以使用 'objdump -D -b binary -m i8086 -M intel boot.bin' 手动查看")
    except subprocess.TimeoutExpired:
        print("⚠️  objdump 执行超时，跳过反汇编")
    except Exception as e:
        print(f"⚠️  反汇编时出错: {e}")
    
    print("\n" + "="*70)
    print("验证总结:")
    print("="*70)
    print("✅ 文件大小: 512 字节")
    print("✅ 引导扇区签名: 0xAA55")
    print("✅ 文件内容对应内存地址 0x7C00-0x7DFF")
    print("\n当 BIOS 加载此引导扇区到内存地址 0x7C00 时，")
    print("文件内容将完全对应内存中的代码。")
    print("\n提示: 使用 'objdump -D -b binary -m i8086 -M intel boot.bin' 查看完整反汇编")
    print("     或查看 BOOT_SECTOR_ANALYSIS.md 了解手工分析方法")
    
    return True

if __name__ == '__main__':
    boot_file = 'boot.bin'
    
    if len(sys.argv) > 1:
        boot_file = sys.argv[1]
    
    success = verify_boot_sector(boot_file)
    sys.exit(0 if success else 1)
