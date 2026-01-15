#!/usr/bin/env python3
"""
反汇编分析 core.img，判断是指令还是压缩数据
"""

import struct
import sys

def disassemble_simple(data, start_offset=0, max_bytes=256):
    """简单的 x86 指令反汇编（仅识别常见指令）"""
    
    # 常见 x86 指令模式
    instructions = {
        0x90: ('NOP', 1),
        0xEB: ('JMP rel8', 2),
        0xE8: ('CALL rel32', 5),
        0xE9: ('JMP rel32', 5),
        0xCD: ('INT imm8', 2),
        0x31: ('XOR r/m, r', 2),
        0x89: ('MOV r/m, r', 2),
        0x8B: ('MOV r, r/m', 2),
        0x66: ('Operand size prefix', 1),  # 需要与下一条指令结合
        0x0F: ('Two-byte opcode prefix', 2),
        0xC3: ('RET', 1),
        0xC2: ('RET imm16', 3),
        0x50: ('PUSH AX', 1),
        0x51: ('PUSH CX', 1),
        0x52: ('PUSH DX', 1),
        0x53: ('PUSH BX', 1),
        0x54: ('PUSH SP', 1),
        0x55: ('PUSH BP', 1),
        0x56: ('PUSH SI', 1),
        0x57: ('PUSH DI', 1),
        0x58: ('POP AX', 1),
        0x59: ('POP CX', 1),
        0x5A: ('POP DX', 1),
        0x5B: ('POP BX', 1),
        0x5C: ('POP SP', 1),
        0x5D: ('POP BP', 1),
        0x5E: ('POP SI', 1),
        0x5F: ('POP DI', 1),
        0xB4: ('MOV AH, imm8', 2),
        0xB5: ('MOV CH, imm8', 2),
        0xB6: ('MOV DH, imm8', 2),
        0xB8: ('MOV AX, imm16', 3),
        0xB9: ('MOV CX, imm16', 3),
        0xBA: ('MOV DX, imm16', 3),
        0xBB: ('MOV BX, imm16', 3),
        0xBC: ('MOV SP, imm16', 3),
        0xBD: ('MOV BP, imm16', 3),
        0xBE: ('MOV SI, imm16', 3),
        0xBF: ('MOV DI, imm16', 3),
    }
    
    i = 0
    output = []
    while i < min(max_bytes, len(data) - start_offset):
        offset = start_offset + i
        byte = data[offset]
        
        if byte in instructions:
            inst_name, inst_len = instructions[byte]
            
            # 读取指令字节
            inst_bytes = data[offset:offset+inst_len]
            hex_str = ' '.join(f'{b:02x}' for b in inst_bytes)
            
            # 解析操作数（简化版）
            operands = ''
            if inst_len > 1:
                if inst_name == 'JMP rel8':
                    rel = struct.unpack('b', inst_bytes[1:2])[0]
                    target = offset + inst_len + rel
                    operands = f'0x{target:04x}'
                elif inst_name == 'CALL rel32':
                    rel = struct.unpack('<i', inst_bytes[1:5])[0]
                    target = offset + inst_len + rel
                    operands = f'0x{target:04x}'
                elif inst_name == 'INT imm8':
                    imm = inst_bytes[1]
                    operands = f'0x{imm:02x}'
            
            output.append(f"{offset:04x}: {hex_str:<20} {inst_name:<20} {operands}")
            i += inst_len
        else:
            # 未知指令，显示为 DB
            hex_str = f'{byte:02x}'
            output.append(f"{offset:04x}: {hex_str:<20} DB                  0x{byte:02x}")
            i += 1
    
    return output

def analyze_core_img(iso_file, kernel_sector):
    """分析 core.img"""
    
    print("=" * 70)
    print("core.img 反汇编分析")
    print("=" * 70)
    print(f"ISO 文件: {iso_file}")
    print(f"起始扇区: {kernel_sector}")
    print()
    
    with open(iso_file, 'rb') as f:
        f.seek(kernel_sector * 512)
        
        # 读取第一个扇区（diskboot.S）
        first_sector = f.read(512)
        
        # 从块列表计算总大小
        blocklist_start = 0x1F4
        blocklist_entry_size = 12
        
        total_sectors = 0
        entries = []
        for i in range(20):
            offset = blocklist_start - (i * blocklist_entry_size)
            if offset < 0:
                break
            
            start_low = struct.unpack('<I', first_sector[offset:offset+4])[0]
            length = struct.unpack('<H', first_sector[offset+8:offset+10])[0]
            
            if length == 0:
                break
            
            entries.append((start_low, length))
            total_sectors += length
        
        total_bytes = total_sectors * 512
        total_kb = total_bytes / 1024
        
        print(f"core.img 大小: {total_sectors} 扇区 = {total_bytes} 字节 = {total_kb:.1f} KB")
        print()
        
        # 读取完整的 core.img
        f.seek(kernel_sector * 512)
        core_img = f.read(total_bytes)
        
        print("=" * 70)
        print("1. 数据特征分析")
        print("=" * 70)
        
        # 计算熵值
        import math
        byte_freq = [0] * 256
        for byte in core_img:
            byte_freq[byte] += 1
        
        entropy = 0
        for freq in byte_freq:
            if freq > 0:
                p = freq / len(core_img)
                entropy -= p * math.log2(p)
        
        print(f"数据熵值: {entropy:.2f} bits/byte")
        print("  - 压缩数据: 通常 > 7.0 bits/byte")
        print("  - 未压缩代码: 通常 < 6.5 bits/byte")
        print("  - 零填充数据: 通常 < 2.0 bits/byte")
        
        if entropy > 7.0:
            print("  → 结论: 高熵值，可能是压缩数据")
        elif entropy < 6.5:
            print("  → 结论: 低熵值，可能是未压缩代码 ✅")
        else:
            print("  → 结论: 中等熵值，需要进一步分析")
        
        # 统计指令字节
        common_instructions = {
            0x90: 'NOP', 0xEB: 'JMP', 0xE8: 'CALL', 0xCD: 'INT',
            0x31: 'XOR', 0x89: 'MOV', 0x8B: 'MOV', 0x66: 'PREFIX',
            0x50: 'PUSH', 0x51: 'PUSH', 0x52: 'PUSH', 0x53: 'PUSH',
            0x58: 'POP', 0x59: 'POP', 0x5A: 'POP', 0x5B: 'POP',
        }
        
        inst_count = {}
        for byte in core_img:
            if byte in common_instructions:
                inst = common_instructions[byte]
                inst_count[inst] = inst_count.get(inst, 0) + 1
        
        print(f"\n常见指令统计（前 {len(core_img)} 字节）:")
        for inst, count in sorted(inst_count.items(), key=lambda x: -x[1])[:10]:
            percentage = count * 100 / len(core_img)
            print(f"  {inst:10s}: {count:6d} 次 ({percentage:.2f}%)")
        
        print()
        print("=" * 70)
        print("2. 反汇编分析（前 256 字节，diskboot.S）")
        print("=" * 70)
        
        disasm = disassemble_simple(core_img, 0, 256)
        for line in disasm:
            print(line)
        
        print()
        print("=" * 70)
        print("3. 内存空间分析")
        print("=" * 70)
        
        available_1mb = 640 * 1024  # 前 1MB 中约 640KB 可用
        print(f"core.img 大小: {total_kb:.1f} KB")
        print(f"1MB 空间可用: {available_1mb/1024:.0f} KB")
        
        if total_bytes < available_1mb:
            print(f"✅ 可以加载到 1MB 空间内")
            print(f"   需要: {total_kb:.1f} KB")
            print(f"   可用: {available_1mb/1024:.0f} KB")
            print(f"   剩余: {(available_1mb - total_bytes)/1024:.1f} KB")
        else:
            print(f"❌ 无法加载到 1MB 空间内")
            print(f"   需要: {total_kb:.1f} KB")
            print(f"   可用: {available_1mb/1024:.0f} KB")
            print(f"   缺少: {(total_bytes - available_1mb)/1024:.1f} KB")
        
        print()
        print("=" * 70)
        print("4. 结论")
        print("=" * 70)
        
        if entropy < 6.5 and len(inst_count) > 5:
            print("✅ core.img 是未压缩的 x86 指令代码")
            print(f"   - 大小: {total_kb:.1f} KB")
            print(f"   - 可以加载到 1MB 空间内（0x8000+）")
            print(f"   - 不需要 LZMA 解压")
        elif entropy > 7.0:
            print("✅ core.img 是压缩数据（可能是 LZMA）")
            print(f"   - 大小: {total_kb:.1f} KB（压缩后）")
            print(f"   - 需要解压到 0x100000 (1MB) 以上")
        else:
            print("❓ 无法确定 core.img 的状态")
            print(f"   - 大小: {total_kb:.1f} KB")
            print(f"   - 熵值: {entropy:.2f} bits/byte")

if __name__ == '__main__':
    iso_file = sys.argv[1] if len(sys.argv) > 1 else '../grub.iso'
    kernel_sector = int(sys.argv[2]) if len(sys.argv) > 2 else 11916
    
    analyze_core_img(iso_file, kernel_sector)
