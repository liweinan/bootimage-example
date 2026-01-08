# 引导扇区代码手工分析指南

本文档介绍如何手工查看和分析引导扇区代码，理解 boot.bin 在内存地址 0x7C00 处的代码结构。

## 目录

1. [文件与内存地址对应关系](#文件与内存地址对应关系)
2. [使用工具查看代码](#使用工具查看代码)
3. [手工分析代码结构](#手工分析代码结构)
4. [指令详解](#指令详解)
5. [内存布局分析](#内存布局分析)

---

## 文件与内存地址对应关系

### 关键概念

- **文件偏移**：boot.bin 文件中的字节位置（从 0 开始）
- **内存地址**：BIOS 加载后的物理内存地址（从 0x7C00 开始）
- **对应关系**：`内存地址 = 0x7C00 + 文件偏移`

### 地址映射表

| 文件偏移 | 内存地址 | 内容说明 |
|---------|---------|---------|
| 0x000   | 0x7C00  | 程序入口点（第一条指令） |
| 0x015   | 0x7C15  | 消息字符串 "Hello from Boot Sector!" |
| 0x1FE   | 0x7DFE  | 引导扇区签名（0x55） |
| 0x1FF   | 0x7DFF  | 引导扇区签名（0xAA） |

---

## 使用工具查看代码

### 1. 使用 objdump（Intel 格式）

```bash
# Intel 格式反汇编
objdump -D -b binary -m i8086 -M intel boot.bin

# 或者只查看前 64 字节
objdump -D -b binary -m i8086 -M intel boot.bin | head -30
```

**输出示例（Intel 格式）：**
```
00000000 <.data>:
   0:   b8 03 00              mov    ax,0x3
   3:   cd 10                 int    0x10
   5:   be 15 7c              mov    si,0x7c15
   8:   b4 0e                 mov    ah,0xe
   a:   ac                    lods   al,BYTE PTR ds:[si]
   b:  84 c0                 test   al,al
   d:  74 04                 je     0x13
   f:   cd 10                 int    0x10
  11:   eb f7                 jmp    0xa
  13:   eb fe                 jmp    0x13
```

### 2. 使用 hexdump 查看原始字节

```bash
# 十六进制 + ASCII 格式
hexdump -C boot.bin

# 只查看前 64 字节
hexdump -C boot.bin | head -5
```

**输出示例：**
```
00000000  b8 03 00 cd 10 be 15 7c  b4 0e ac 84 c0 74 04 cd  |.......|.....t..|
00000010  10 eb f7 eb fe 48 65 6c  6c 6f 20 66 72 6f 6d 20  |.....Hello from |
00000020  42 6f 6f 74 20 53 65 63  74 6f 72 21 00 00 00 00  |Boot Sector!....|
```

### 3. 使用 Python 脚本验证

```bash
python3 verify_boot_sector.py
```

---

## 手工分析代码结构

### 完整代码布局

```
地址范围          大小    内容
─────────────────────────────────────────────────────────
0x7C00-0x7C14    21 字节  程序代码
0x7C15-0x7C2C    24 字节  消息字符串 "Hello from Boot Sector!"
0x7C2D-0x7DFD   463 字节  填充（零字节）
0x7DFE-0x7DFF     2 字节  引导扇区签名 0xAA55
─────────────────────────────────────────────────────────
总计             512 字节
```

### 逐字节分析（前 32 字节）

#### 偏移 0x00-0x02: `mov ax, 0x0003`

```
字节序列: B8 03 00
地址:     0x7C00-0x7C02

B8 = mov ax, imm16 的操作码
03 00 = 立即数 0x0003（小端序：低字节在前）
        - 0x03 是低字节
        - 0x00 是高字节
        - 组合：0x0003

功能：设置显示模式为 80x25 文本模式
```

#### 偏移 0x03-0x04: `int 0x10`

```
字节序列: CD 10
地址:     0x7C03-0x7C04

CD = int 指令的操作码
10 = 中断号 0x10（BIOS 视频服务）

功能：调用 BIOS 中断 0x10，设置显示模式
```

#### 偏移 0x05-0x07: `mov si, 0x7C15`

```
字节序列: BE 15 7C
地址:     0x7C05-0x7C07

BE = mov si, imm16 的操作码
15 7C = 立即数 0x7C15（小端序）
        - 0x15 是低字节
        - 0x7C 是高字节
        - 组合：0x7C15

功能：将消息字符串的地址加载到 SI 寄存器
注意：0x7C15 是相对于段地址 0x0000 的偏移
     实际物理地址 = 0x0000 * 16 + 0x7C15 = 0x7C15
```

#### 偏移 0x08-0x09: `mov ah, 0x0E`

```
字节序列: B4 0E
地址:     0x7C08-0x7C09

B4 = mov ah, imm8 的操作码
0E = 立即数 0x0E

功能：设置 BIOS 视频服务功能号（TTY 模式显示字符）
```

#### 偏移 0x0A: `lodsb`

```
字节序列: AC
地址:     0x7C0A

AC = lodsb 指令的操作码

功能：从 DS:SI 读取一个字节到 AL，然后 SI++
     等价于：
     - AL = [DS:SI]
     - SI = SI + 1
```

#### 偏移 0x0B-0x0C: `test al, al`

```
字节序列: 84 C0
地址:     0x7C0B-0x7C0C

84 = test r8, r/m8 的操作码
C0 = 操作数编码（AL, AL）

功能：测试 AL 是否为零（检查字符串结束符）
```

#### 偏移 0x0D-0x0E: `je 0x13` (jz 0x13)

```
字节序列: 74 04
地址:     0x7C0D-0x7C0E

74 = je/jz 指令的操作码（条件跳转：如果 ZF=1）
04 = 相对偏移量（有符号 8 位）

跳转目标计算：
  目标地址 = 当前指令地址 + 指令长度 + 偏移量
          = 0x7C0D + 2 + 0x04
          = 0x7C13

功能：如果 AL == 0（字符串结束），跳转到 .halt
```

#### 偏移 0x0F-0x10: `int 0x10`

```
字节序列: CD 10
地址:     0x7C0F-0x7C10

功能：显示 AL 中的字符（ah=0x0E 已设置）
```

#### 偏移 0x11-0x12: `jmp 0x0A`

```
字节序列: EB F7
地址:     0x7C11-0x7C12

EB = jmp short 指令的操作码
F7 = 相对偏移量（有符号 8 位：0xF7 = -9）

跳转目标计算：
  目标地址 = 0x7C11 + 2 + (-9)
          = 0x7C0A

功能：跳回 .print 循环开始
```

#### 偏移 0x13-0x14: `jmp 0x13` (无限循环)

```
字节序列: EB FE
地址:     0x7C13-0x7C14

EB = jmp short 指令的操作码
FE = 相对偏移量（有符号 8 位：0xFE = -2）

跳转目标计算：
  目标地址 = 0x7C13 + 2 + (-2)
          = 0x7C13

功能：无限循环（程序结束）
```

#### 偏移 0x15-0x2C: 消息字符串

```
字节序列: 48 65 6C 6C 6F 20 66 72 6F 6D 20 42 6F 6F 74 20 53 65 63 74 6F 72 21 00
地址:     0x7C15-0x7C2C

ASCII 解码：
48 = 'H'
65 = 'e'
6C = 'l'
6C = 'l'
6F = 'o'
20 = ' ' (空格)
66 = 'f'
72 = 'r'
6F = 'o'
6D = 'm'
20 = ' ' (空格)
42 = 'B'
6F = 'o'
6F = 'o'
74 = 't'
20 = ' ' (空格)
53 = 'S'
65 = 'e'
63 = 'c'
74 = 't'
6F = 'o'
72 = 'r'
21 = '!'
00 = '\0' (字符串结束符)

内容： "Hello from Boot Sector!"
```

---

## 指令详解

### 指令编码格式

#### 1. MOV 指令

```
MOV 目标, 源

格式 1: MOV reg16, imm16
操作码: B8 + 寄存器编码
示例: mov ax, 0x0003
编码: B8 03 00
      │  └─┘
      │    └─ 立即数（小端序）
      └─ MOV AX, imm16

格式 2: MOV reg8, imm8
操作码: B0-B7 (根据寄存器)
示例: mov ah, 0x0E
编码: B4 0E
      │  └─ 立即数
      └─ MOV AH, imm8

格式 3: MOV reg16, imm16 (SI)
操作码: BE
示例: mov si, 0x7C15
编码: BE 15 7C
      │  └───┘
      │      └─ 立即数（小端序）
      └─ MOV SI, imm16
```

#### 2. INT 指令

```
INT 中断号

操作码: CD
示例: int 0x10
编码: CD 10
      │  └─ 中断号
      └─ INT 指令
```

#### 3. LODSB 指令

```
LODSB (Load String Byte)

操作码: AC
功能: AL = [DS:SI], SI = SI + 1
编码: AC
```

#### 4. TEST 指令

```
TEST 操作数1, 操作数2

格式: TEST reg8, reg8
操作码: 84
示例: test al, al
编码: 84 C0
      │  └─ 操作数编码（AL, AL）
      └─ TEST r8, r/m8
```

#### 5. 条件跳转指令

```
JE/JZ (Jump if Equal/Zero)

操作码: 74
格式: je 目标地址
编码: 74 偏移量（有符号 8 位）

跳转计算：
  如果 ZF = 1:
    IP = IP + 2 + 偏移量
```

#### 6. 无条件跳转指令

```
JMP SHORT

操作码: EB
格式: jmp 目标地址
编码: EB 偏移量（有符号 8 位）

跳转计算：
  IP = IP + 2 + 偏移量
```

---

## 内存布局分析

### 完整内存映射

```
物理地址    文件偏移  内容                    说明
─────────────────────────────────────────────────────────────
0x7C00      0x000     mov ax, 0x0003         程序入口
0x7C03      0x003     int 0x10               设置显示模式
0x7C05      0x005     mov si, 0x7C15         加载字符串地址
0x7C08      0x008     mov ah, 0x0E            设置功能号
0x7C0A      0x00A     lodsb                   读取字符
0x7C0B      0x00B     test al, al             检查结束符
0x7C0D      0x00D     je 0x7C13               如果结束则跳转
0x7C0F      0x00F     int 0x10                显示字符
0x7C11      0x011     jmp 0x7C0A              循环
0x7C13      0x013     jmp 0x7C13              无限循环
0x7C15      0x015     "Hello from Boot..."    消息字符串
0x7C2D      0x02D     0x00 (填充)              零填充
...         ...       0x00 (填充)              零填充
0x7DFD      0x1FD     0x00 (填充)              零填充
0x7DFE      0x1FE     0x55                     签名低字节
0x7DFF      0x1FF     0xAA                     签名高字节
```

### 控制流图

```
0x7C00: start
  │
  ├─> mov ax, 0x0003
  ├─> int 0x10              (设置显示模式)
  ├─> mov si, 0x7C15        (字符串地址)
  ├─> mov ah, 0x0E          (功能号)
  │
  └─> 0x7C0A: .print
        │
        ├─> lodsb            (读取字符到 AL)
        ├─> test al, al      (检查是否为零)
        │
        ├─> [ZF=1] ──> je 0x7C13 ──> 0x7C13: .halt
        │                              │
        │                              └─> jmp 0x7C13 (无限循环)
        │
        └─> [ZF=0] ──> int 0x10        (显示字符)
                        │
                        └─> jmp 0x7C0A (循环)
```

---

## 验证方法

### 1. 验证文件大小

```bash
ls -lh boot.bin
# 应该显示 512 字节
```

### 2. 验证引导签名

```bash
hexdump -C boot.bin | tail -1
# 最后两个字节应该是: 55 aa
```

### 3. 验证代码内容

```bash
# Intel 格式反汇编
objdump -D -b binary -m i8086 -M intel boot.bin

# 查看特定地址
objdump -D -b binary -m i8086 -M intel boot.bin | grep "7c00\|7c15\|7dfe"
```

### 4. 在 QEMU 中验证

```bash
# 启动 QEMU
qemu-system-x86_64 -drive format=raw,file=boot.bin -monitor stdio

# 在 QEMU monitor 中：
(qemu) x/32xb 0x7c00    # 查看 0x7C00 处的 32 字节
(qemu) x/16i 0x7c00     # 反汇编 0x7C00 处的指令
(qemu) x/s 0x7c15       # 查看字符串内容
```

---

## 常见问题

### Q1: 为什么 mov si, 0x7C15 中的地址是 0x7C15？

**A:** 因为 `org 0x7C00` 指令告诉汇编器，程序将从地址 0x7C00 开始执行。字符串 `msg` 定义在代码之后，汇编器计算其地址为相对于程序起始地址的偏移。由于代码部分占用约 21 字节（0x00-0x14），所以字符串从 0x7C15 开始。

### Q2: 为什么跳转指令使用相对偏移？

**A:** 相对跳转指令（如 `je`、`jmp short`）使用有符号 8 位偏移量，这样可以：
- 节省空间（只需要 2 字节）
- 支持位置无关代码
- 在引导扇区这种空间受限的环境中很重要

### Q3: 如何验证代码确实在 0x7C00 执行？

**A:** 
1. 使用 QEMU monitor 查看内存：`x/16i 0x7c00`
2. 在代码中添加调试输出，打印当前 IP 寄存器值
3. 使用调试器（如 GDB）连接到 QEMU 进行调试

---

## 参考资料

- [x86 指令编码参考](https://www.felixcloutier.com/x86/)
- [BIOS 中断服务](https://en.wikipedia.org/wiki/BIOS_interrupt_call)
- [引导扇区规范](https://en.wikipedia.org/wiki/Master_boot_record)
