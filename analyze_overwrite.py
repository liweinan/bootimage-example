#!/usr/bin/env python3
"""
分析 extract_kernel 代码被覆盖的时间点
"""

# 实际数据（Linux 6.6.110）
init_size = 0x20de000          # 32.87 MB
compressed_size = 0x9e8400     # 9.91 MB
decompressed_size = 0x1fde000  # 31.84 MB (init_size - compressed_size)

# 内存布局
decompression_start = 0x1000000        # 16 MB (%rbp)
decompression_end = decompression_start + init_size  # 48.87 MB
compressed_start = decompression_start + (init_size - compressed_size)  # 38.96 MB (%rbx)
compressed_end = decompression_end     # 48.87 MB

# extract_kernel 代码位置（相对于压缩内核起始）
ZO_ehead_offset = 0x1b000      # .head.text 结束位置（从 ZO 起始算）
ZO_text_start = ZO_ehead_offset
ZO_text_end = 0xa00000         # 假设 .text 段约 10MB（估计值）

extract_kernel_start = compressed_start + ZO_text_start
extract_kernel_end = compressed_start + ZO_text_end

print("=" * 70)
print("内存布局分析")
print("=" * 70)
print(f"解压目标区域:    0x{decompression_start:08x} - 0x{decompression_end:08x}")
print(f"                 ({decompression_start/(1024*1024):.2f} MB - {decompression_end/(1024*1024):.2f} MB)")
print(f"\n压缩源区域:      0x{compressed_start:08x} - 0x{compressed_end:08x}")
print(f"                 ({compressed_start/(1024*1024):.2f} MB - {compressed_end/(1024*1024):.2f} MB)")
print(f"\nextract_kernel:  0x{extract_kernel_start:08x} - 0x{extract_kernel_end:08x}")
print(f"                 ({extract_kernel_start/(1024*1024):.2f} MB - {extract_kernel_end/(1024*1024):.2f} MB)")

print("\n" + "=" * 70)
print("覆盖时间点分析")
print("=" * 70)

# 计算解压到 extract_kernel_start 需要解压多少数据
bytes_to_overwrite = extract_kernel_start - decompression_start
print(f"\n覆盖 extract_kernel 需要解压: {bytes_to_overwrite/(1024*1024):.2f} MB")

# 估计压缩率
compression_ratio = compressed_size / decompressed_size
print(f"压缩率: {compression_ratio:.2%}")

# 计算需要读取多少压缩数据
compressed_data_read = int(bytes_to_overwrite * compression_ratio)
compressed_data_position = compressed_start + compressed_data_read
print(f"此时需要读取压缩数据: {compressed_data_read/(1024*1024):.2f} MB")
print(f"读取位置到达: 0x{compressed_data_position:08x} ({compressed_data_position/(1024*1024):.2f} MB)")

print("\n" + "=" * 70)
print("关键问题")
print("=" * 70)
print("\n问题: 当解压写入到达 extract_kernel 代码位置时，")
print("     extract_kernel 函数是否还在执行？")
print("\n答案:")
if compressed_data_position < extract_kernel_start:
    print("  YES! 压缩数据还没有被读取到 extract_kernel 位置，")
    print("       所以 extract_kernel 代码会在自己还在执行时被覆盖！")
    print(f"  覆盖时刻：解压进度 {bytes_to_overwrite/(1024*1024):.2f} MB / {decompressed_size/(1024*1024):.2f} MB")
    print(f"  完成度：{100*bytes_to_overwrite/decompressed_size:.1f}%")
else:
    print("  NO. 压缩数据已经读取过 extract_kernel 位置，")
    print("      理论上不会覆盖正在执行的代码。")

