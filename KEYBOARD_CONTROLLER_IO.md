# 键盘控制器 I/O 端口映射与汇编实现

本文档详细说明键盘控制器（8042/PS2）的 I/O 端口地址映射机制、汇编代码实现，以及 CPU 如何访问这些端口。

## 目录

1. [键盘控制器端口地址](#1-键盘控制器端口地址)
2. [I/O 端口 vs 内存地址](#2-io-端口-vs-内存地址)
3. [地址总线与对应硬件](#3-地址总线与对应硬件)
4. [地址解码机制](#4-地址解码机制)
5. [汇编代码实现](#5-汇编代码实现)
6. [完整的 I/O 访问流程](#6-完整的-io-访问流程)
7. [键盘中断处理中的 I/O 操作](#7-键盘中断处理中的-io-操作)
8. [I/O 地址的学习资源与硬件实现](#8-io-地址的学习资源与硬件实现)

---

## 1. 键盘控制器端口地址

### 端口地址定义

**源代码位置**：`seabios/src/hw/ps2port.h:7-8`

```c
#define PORT_PS2_DATA          0x0060  // 键盘数据端口
#define PORT_PS2_STATUS        0x0064  // 键盘状态/控制端口
```

**端口地址说明**：

| 端口地址 | 名称 | 方向 | 功能 |
|---------|------|------|------|
| **0x60** | 键盘数据端口（Keyboard Data Port） | 读/写 | 读取扫描码，发送键盘命令 |
| **0x64** | 键盘控制端口（Keyboard Control Port） | 读/写 | 读取状态，发送控制命令 |

### 端口地址的硬件固定性

**这些端口地址是硬件固定的，不是 CPU 决定的！**

- **0x60**：键盘数据端口（8042 键盘控制器）
- **0x64**：键盘控制端口（8042 键盘控制器）
- 这些地址由 **IBM PC/AT 架构标准**决定，是 8042 键盘控制器芯片的硬件设计
- 所有兼容 IBM PC/AT 的系统都必须使用这些端口地址

**其他相关 I/O 端口地址**：

| 端口范围 | 设备 | 说明 |
|---------|------|------|
| **0x20-0x3F** | 主 PIC（8259A） | 中断控制器 |
| **0xA0-0xBF** | 从 PIC（8259A） | 中断控制器 |
| **0x60-0x6F** | 键盘控制器（8042） | 键盘和鼠标 |
| **0x70-0x7F** | CMOS/RTC | 实时时钟和 CMOS 配置 |

---

## 2. I/O 端口 vs 内存地址

### 关键区别

**I/O 端口不是内存地址，而是独立的 I/O 地址空间！**

| 特性 | 内存地址 | I/O 端口 |
|------|---------|---------|
| **地址空间** | 内存地址空间（Memory Address Space） | I/O 地址空间（I/O Address Space） |
| **地址范围** | 0x00000000 - 0xFFFFFFFF（32位系统） | 0x0000 - 0xFFFF（16位，64K 端口） |
| **访问指令** | `mov [0x1000], al` | `inb 0x60, al` / `outb al, 0x60` |
| **地址总线** | 使用内存地址总线 | 使用 I/O 地址总线（低 16 位） |
| **控制信号** | MEMR#/MEMW#（内存读写） | IOR#/IOW#（I/O 读写） |

### 为什么使用 I/O 端口而不是内存映射？

**I/O 端口（Port-Mapped I/O，PMIO）的优势**：
- **独立地址空间**：不与内存地址冲突
- **专用指令**：`IN`/`OUT` 指令明确表示 I/O 操作
- **硬件简化**：不需要复杂的地址映射
- **兼容性**：x86 架构的传统设计

**内存映射 I/O（Memory-Mapped I/O，MMIO）**：
- 现代系统（如 PCI 设备）也使用内存映射 I/O
- 将设备寄存器映射到内存地址空间
- 使用普通的内存访问指令（`mov`）访问设备
- 但键盘控制器（8042）使用传统的 I/O 端口方式

---

## 3. 地址总线与对应硬件

### 地址总线的定义

**地址总线（Address Bus）**是 CPU 用来指定内存或 I/O 设备地址的一组信号线。CPU 通过地址总线发送地址信息，告诉系统要访问哪个内存位置或 I/O 设备。

**关键特性**：
- **单向总线**：地址信息从 CPU 流向外部设备（CPU → 设备）
- **宽度决定寻址能力**：地址总线宽度决定 CPU 可以访问的最大地址空间
- **与数据总线独立**：地址总线宽度和数据总线宽度可以不同

### 地址总线宽度与寻址能力

| CPU 型号 | 地址总线宽度 | 最大寻址空间 | 说明 |
|---------|------------|------------|------|
| **8086/8088** | 20 位 | 1MB（0x00000 - 0xFFFFF） | 最早的 x86 CPU |
| **80286** | 24 位 | 16MB（0x000000 - 0xFFFFFF） | 引入保护模式 |
| **80386/80486** | 32 位 | 4GB（0x00000000 - 0xFFFFFFFF） | 32 位 x86 架构 |
| **Pentium+（64位）** | 36-52 位 | 64GB - 4PB | 物理地址扩展（PAE） |

**计算公式**：
```
最大寻址空间 = 2^(地址总线宽度)
例如：20 位地址总线 = 2^20 = 1,048,576 字节 = 1MB
```

### 地址总线 vs 数据总线 vs 控制总线

**三种总线的区别**：

| 总线类型 | 方向 | 宽度 | 功能 | 示例 |
|---------|------|------|------|------|
| **地址总线** | CPU → 设备 | 20-52 位 | 指定访问的地址 | A0-A31（32位系统） |
| **数据总线** | 双向 | 8/16/32/64 位 | 传输实际数据 | D0-D63（64位系统） |
| **控制总线** | 双向 | 多条信号线 | 控制操作类型 | MEMR#、MEMW#、IOR#、IOW# |

**总线信号示例（32位系统）**：

```
地址总线（32 位）：
A0, A1, A2, ..., A31  →  32 根地址线，可寻址 4GB

数据总线（32 位）：
D0, D1, D2, ..., D31  →  32 根数据线，一次传输 4 字节

控制总线（多条信号线）：
MEMR#  →  内存读信号（Memory Read）
MEMW#  →  内存写信号（Memory Write）
IOR#   →  I/O 读信号（I/O Read）
IOW#   →  I/O 写信号（I/O Write）
M/IO#  →  内存/I/O 选择信号（Memory/I/O）
```

### 地址总线连接的硬件设备

**地址总线连接到所有需要寻址的设备**：

```
CPU
 │
 ├─ 地址总线（A0-A31）
 │  │
 │  ├─→ 内存控制器（Memory Controller）
 │  │   └─→ RAM（内存条）
 │  │
 │  ├─→ 芯片组（Chipset）
 │  │   ├─→ 地址解码器（Address Decoder）
 │  │   │   ├─→ BIOS Flash ROM（0xF0000-0xFFFFF）
 │  │   │   ├─→ I/O 设备（通过 I/O 地址空间）
 │  │   │   │   ├─→ PIC（0x20-0x3F, 0xA0-0xBF）
 │  │   │   │   ├─→ 键盘控制器（0x60-0x6F）
 │  │   │   │   ├─→ CMOS/RTC（0x70-0x7F）
 │  │   │   │   └─→ 其他 I/O 设备
 │  │   │   └─→ PCI 设备（通过 PCI 配置空间）
 │  │   │
 │  │   └─→ 其他控制器
 │  │
 │  └─→ 其他设备（如显卡、网卡等）
```

### 地址总线的物理实现

**物理连接方式**：

1. **CPU 引脚**：
   - CPU 芯片有专门的地址引脚（Address Pins）
   - 例如：32 位 CPU 有 A0-A31 共 32 根地址引脚
   - 这些引脚通过主板上的印刷电路板（PCB）走线连接到各个设备

2. **主板走线**：
   - 地址总线信号通过主板上的**印刷电路板（PCB）走线**传输
   - 走线长度和阻抗需要精确设计，确保信号完整性
   - 所有连接到地址总线的设备都"监听"地址信号

3. **地址解码器**：
   - **位置**：通常集成在芯片组（Chipset）中
   - **功能**：根据地址总线的值，决定哪个设备应该响应
   - **实现**：硬件逻辑电路（如门电路、多路选择器等）

### 地址总线的实际工作示例

#### 示例 1：CPU 访问内存地址 0x1000

```
1. CPU 执行指令：mov ax, [0x1000]
   ↓
2. CPU 将地址 0x1000 放在地址总线上：
   A0-A31 = 0x00001000
   （二进制：0000 0000 0000 0000 0001 0000 0000 0000）
   ↓
3. CPU 发出控制信号：
   MEMR# = 0（有效，表示内存读）
   M/IO# = 1（表示内存访问，不是 I/O）
   ↓
4. 内存控制器检测到：
   - 地址在 RAM 范围内（0x00000000 - 0xFFFFFFFF，排除 ROM 区域）
   - MEMR# 有效
   - M/IO# = 1（内存访问）
   ↓
5. 内存控制器访问 RAM：
   - 解码地址 0x1000
   - 从 RAM 的物理地址 0x1000 读取数据
   - 将数据放在数据总线上
   ↓
6. CPU 从数据总线读取数据到 AX 寄存器
```

#### 示例 2：CPU 访问 I/O 端口 0x60（键盘数据端口）

```
1. CPU 执行指令：in al, 0x60
   ↓
2. CPU 将端口地址 0x60 放在地址总线上：
   A0-A15 = 0x0060（I/O 地址空间，只使用低 16 位）
   （二进制：0000 0000 0110 0000）
   ↓
3. CPU 发出控制信号：
   IOR# = 0（有效，表示 I/O 读）
   M/IO# = 0（表示 I/O 访问，不是内存）
   ↓
4. 地址解码器检测到：
   - 地址在 I/O 地址空间（0x0000 - 0xFFFF）
   - IOR# 有效
   - M/IO# = 0（I/O 访问）
   - 地址范围 0x60-0x6F → 键盘控制器
   ↓
5. 地址解码器将信号路由到键盘控制器（8042）：
   - 将地址总线信号连接到 8042 的地址引脚
   - 将 IOR# 信号连接到 8042 的控制引脚
   - 将数据总线连接到 8042 的数据引脚
   ↓
6. 8042 键盘控制器响应：
   - 检测到读取请求（IOR# 有效）
   - 检查输出缓冲区（OBF）
   - 如果有数据，将扫描码放在数据总线上
   ↓
7. CPU 从数据总线读取数据到 AL 寄存器
```

### 地址总线的硬件连接细节

#### 1. CPU 到内存控制器的连接

```
CPU（地址引脚 A0-A31）
    ↓
主板 PCB 走线（32 根地址线）
    ↓
内存控制器（芯片组中）
    ↓
地址解码逻辑
    ↓
RAM 芯片（内存条）
```

**物理实现**：
- CPU 的地址引脚通过**主板上的印刷电路板（PCB）走线**连接到内存控制器
- 走线长度需要匹配，确保所有地址线同时到达（时序同步）
- 走线阻抗需要精确控制，确保信号完整性

#### 2. CPU 到 I/O 设备的连接

```
CPU（地址引脚 A0-A15，用于 I/O）
    ↓
主板 PCB 走线（16 根地址线）
    ↓
芯片组（地址解码器）
    ↓
地址范围匹配逻辑
    ├─ 0x20-0x3F → PIC（8259A）
    ├─ 0x60-0x6F → 键盘控制器（8042）
    ├─ 0x70-0x7F → CMOS/RTC
    └─ 其他范围 → 其他 I/O 设备
    ↓
对应的硬件设备芯片
```

**物理实现**：
- CPU 的地址引脚（低 16 位）连接到芯片组
- 芯片组中的地址解码器根据地址范围路由到对应设备
- 每个 I/O 设备芯片都有地址引脚，连接到地址总线

#### 3. 地址解码器的硬件实现

**地址解码器是硬件逻辑电路**，不是软件：

```
输入：
  - 地址总线（A0-A15）
  - 控制信号（M/IO#、IOR#、IOW#）

逻辑电路：
  - 地址范围比较器（比较器电路）
  - 多路选择器（MUX）
  - 门电路（AND、OR、NOT）

输出：
  - 设备选择信号（Device Select）
  - 路由到对应的硬件设备
```

**示例：键盘控制器地址解码逻辑**：

```
地址解码逻辑（硬件电路）：
  IF (A0-A15 >= 0x0060) AND (A0-A15 <= 0x006F) AND (M/IO# = 0)
  THEN
    选择键盘控制器（8042）
    将地址总线信号路由到 8042
    将控制信号（IOR#/IOW#）路由到 8042
    将数据总线连接到 8042
  END IF
```

### 地址总线的时序

**地址总线的时序特性**：

```
时钟周期 1：CPU 将地址放在地址总线上
时钟周期 2：地址稳定，设备解码地址
时钟周期 3：设备响应，数据放在数据总线上
时钟周期 4：CPU 读取数据，地址总线可以用于下一个操作
```

**关键点**：
- **地址建立时间（Address Setup Time）**：地址必须在控制信号有效前稳定
- **地址保持时间（Address Hold Time）**：地址必须在控制信号无效后保持一段时间
- **传播延迟（Propagation Delay）**：地址信号从 CPU 传播到设备需要时间

### 地址总线的实际硬件示例

#### 8086 CPU（20 位地址总线）

```
CPU 引脚：
  A0, A1, A2, ..., A19  →  20 根地址引脚

连接：
  A0-A19  →  主板 PCB 走线
           →  内存控制器
           →  RAM（1MB 地址空间）
           →  BIOS ROM（0xF0000-0xFFFFF）
```

#### 80386 CPU（32 位地址总线）

```
CPU 引脚：
  A0, A1, A2, ..., A31  →  32 根地址引脚

连接：
  A0-A31  →  主板 PCB 走线
           →  内存控制器（芯片组）
           →  RAM（4GB 地址空间）
           →  BIOS ROM（0xFFFC0000-0xFFFFFFFF）
           →  I/O 设备（通过 I/O 地址空间，A0-A15）
```

### 地址总线与内存控制器的关系

**内存控制器的作用**：

1. **地址解码**：
   - 根据地址总线的值，决定访问哪个设备（RAM、ROM、I/O）
   - 实现地址范围到物理设备的映射

2. **总线仲裁**：
   - 管理多个设备对总线的访问
   - 确保同一时间只有一个设备使用总线

3. **访问控制**：
   - 控制读写权限（如 ROM 只读）
   - 管理缓存一致性

4. **时序控制**：
   - 管理访问时序
   - 处理不同速度的设备（如 RAM 快，ROM 慢）

### 总结

**地址总线的关键要点**：

1. **地址总线是硬件信号线**：物理上通过主板 PCB 走线连接
2. **地址总线宽度决定寻址能力**：20 位 = 1MB，32 位 = 4GB
3. **地址总线连接到所有需要寻址的设备**：RAM、ROM、I/O 设备
4. **地址解码器负责路由**：根据地址值选择对应的设备
5. **地址总线与数据总线、控制总线配合工作**：共同完成数据传输

**相关硬件**：
- **CPU**：地址总线的源头，发出地址信号
- **内存控制器**：管理内存访问，解码地址
- **芯片组**：包含地址解码器，路由信号到各个设备
- **硬件设备**：RAM、ROM、PIC、键盘控制器等，都连接到地址总线

---

## 4. 地址解码机制（基于地址总线）

### CPU 访问 I/O 端口的完整流程

```
┌─────────────────────────────────────────────────────────┐
│ 1. CPU 执行 inb(0x60) 或 outb(0x60, value)              │
│    - 编译为 IN/OUT 指令                                  │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ 2. CPU 将端口地址 0x60 放在地址总线上（I/O 地址空间）     │
│    - 地址总线低 16 位 = 0x0060                           │
│    - 地址总线高 16 位 = 0x0000（I/O 地址空间）           │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ 3. CPU 发出 I/O 控制信号                                 │
│    - 读取：IOR#（I/O Read）信号有效                      │
│    - 写入：IOW#（I/O Write）信号有效                     │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ 4. 主板上的地址解码电路（Address Decoder）检测到：        │
│    - 地址总线 = 0x0060                                   │
│    - I/O 信号有效（IOR# 或 IOW#）                        │
│    - 地址解码器查找地址映射表：                          │
│      0x60-0x6F → 键盘控制器（8042）                     │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ 5. 地址解码电路将信号路由到对应的硬件设备                  │
│    - 将地址总线信号路由到 8042 键盘控制器芯片             │
│    - 将数据总线连接到 8042 的数据引脚                    │
│    - 将控制信号（IOR#/IOW#）连接到 8042 的控制引脚        │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ 6. 8042 键盘控制器芯片响应                               │
│    - 读取操作（IN）：8042 将数据放在数据总线上            │
│    - 写入操作（OUT）：8042 从数据总线读取数据             │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ 7. CPU 读取数据总线（读取操作）或完成写入（写入操作）      │
└─────────────────────────────────────────────────────────┘
```

### 地址解码电路的工作原理

**地址解码器（Address Decoder）**位于主板上（或芯片组中），负责将 CPU 的地址总线信号路由到对应的硬件设备。

**地址映射表（示例）**：

```
地址范围         设备                说明
─────────────────────────────────────────────────────
0x0000-0x001F    DMA 控制器         直接内存访问控制器
0x0020-0x003F    主 PIC（8259A）    中断控制器
0x0040-0x005F    定时器（8253/8254） 系统定时器
0x0060-0x006F    键盘控制器（8042）  键盘和鼠标 ← 这里！
0x0070-0x007F    CMOS/RTC           实时时钟和配置
0x0080-0x009F    DMA 页面寄存器      DMA 页面地址
0x00A0-0x00BF    从 PIC（8259A）    中断控制器
0x00C0-0x00DF    DMA 控制器 2       第二个 DMA 控制器
0x00E0-0x00EF    保留
0x00F0-0x00FF    数学协处理器        浮点运算单元
```

**关键点**：
- **地址解码器是硬件电路**，不是软件
- **地址映射是固定的**，由主板设计决定
- **不同地址范围路由到不同设备**，不会冲突
- **I/O 地址空间与内存地址空间完全独立**

---

## 5. 汇编代码实现

### C 语言函数定义

**源代码位置**：`seabios/src/x86.h:150-163`

```c
// 输出字节到 I/O 端口
static inline void outb(u8 value, u16 port) {
    __asm__ __volatile__("outb %b0, %w1" : : "a"(value), "Nd"(port));
}

// 从 I/O 端口读取字节
static inline u8 inb(u16 port) {
    u8 value;
    __asm__ __volatile__("inb %w1, %b0" : "=a"(value) : "Nd"(port));
    return value;
}
```

### 汇编指令说明

#### `inb` 指令（从 I/O 端口读取字节）

**语法**：`inb port, al` 或 `in al, port`

**GCC 内联汇编格式**：
```c
__asm__ __volatile__("inb %w1, %b0" : "=a"(value) : "Nd"(port));
```

**展开后的汇编代码**：
```asm
; 假设 port = 0x60（键盘数据端口）
mov dx, 0x0060      ; 将端口地址加载到 DX 寄存器
in al, dx           ; 从端口 0x60 读取一个字节到 AL 寄存器
; AL 现在包含从键盘控制器读取的数据（扫描码）
```

**指令说明**：
- `in al, dx`：从 DX 寄存器指定的 I/O 端口读取一个字节到 AL 寄存器
- `%w1`：表示第二个操作数（port）作为 16 位值（word）
- `%b0`：表示第一个输出操作数（value）作为 8 位值（byte）
- `"=a"`：输出约束，表示结果存储在 EAX/AL 寄存器
- `"Nd"`：输入约束，表示端口地址可以是立即数（N）或 DX 寄存器（d）

#### `outb` 指令（向 I/O 端口写入字节）

**语法**：`outb al, port` 或 `out port, al`

**GCC 内联汇编格式**：
```c
__asm__ __volatile__("outb %b0, %w1" : : "a"(value), "Nd"(port));
```

**展开后的汇编代码**：
```asm
; 假设 value = 0xAE（启用键盘命令），port = 0x64（控制端口）
mov al, 0xAE        ; 将命令值加载到 AL 寄存器
mov dx, 0x0064     ; 将端口地址加载到 DX 寄存器
out dx, al         ; 将 AL 寄存器的值写入端口 0x64
```

**指令说明**：
- `out dx, al`：将 AL 寄存器的值写入 DX 寄存器指定的 I/O 端口
- `%b0`：表示第一个操作数（value）作为 8 位值（byte）
- `%w1`：表示第二个操作数（port）作为 16 位值（word）
- `"a"`：输入约束，表示值存储在 EAX/AL 寄存器
- `"Nd"`：输入约束，表示端口地址可以是立即数（N）或 DX 寄存器（d）

### 完整的汇编示例

#### 示例 1：从键盘数据端口读取扫描码

```asm
; 读取键盘扫描码
mov dx, 0x0060      ; DX = 键盘数据端口地址
in al, dx           ; 从端口 0x60 读取一个字节到 AL
; AL 现在包含扫描码（例如：0x1E = 'a' 键）
```

#### 示例 2：读取键盘状态端口

```asm
; 读取键盘状态
mov dx, 0x0064      ; DX = 键盘控制端口地址
in al, dx           ; 从端口 0x64 读取状态字节到 AL
; AL 现在包含状态位：
;   bit 0 (OBF): 输出缓冲区满（有数据可读）
;   bit 1 (IBF): 输入缓冲区满（正在写入）
;   bit 2-7: 其他状态位
```

#### 示例 3：发送键盘命令

```asm
; 发送键盘启用命令（0xAE）到控制端口
mov al, 0xAE        ; AL = 键盘启用命令
mov dx, 0x0064      ; DX = 键盘控制端口地址
out dx, al         ; 将命令写入端口 0x64
```

#### 示例 4：等待键盘数据就绪

```asm
; 等待键盘数据就绪（轮询状态端口）
wait_keyboard:
    mov dx, 0x0064      ; DX = 键盘控制端口
    in al, dx           ; 读取状态
    test al, 0x01      ; 检查 OBF 位（输出缓冲区满）
    jz wait_keyboard    ; 如果 OBF=0，继续等待
    
    ; 数据就绪，读取扫描码
    mov dx, 0x0060      ; DX = 键盘数据端口
    in al, dx           ; 读取扫描码到 AL
```

---

## 6. 完整的 I/O 访问流程

### 读取键盘扫描码的完整流程

**C 代码**：
```c
// seabios/src/hw/ps2port.c:404
v = inb(PORT_PS2_DATA);  // PORT_PS2_DATA = 0x60
```

**编译后的汇编代码**：
```asm
; 1. 函数调用准备
push bp
mov bp, sp

; 2. 加载端口地址到 DX
mov dx, 0x0060      ; PORT_PS2_DATA = 0x60

; 3. 执行 IN 指令
in al, dx           ; 从端口 0x60 读取一个字节到 AL

; 4. 存储结果
mov [bp-1], al      ; 将 AL 的值存储到局部变量 v

; 5. 函数返回
mov sp, bp
pop bp
ret
```

**硬件执行流程**：

```
CPU 执行 in al, dx
    ↓
CPU 将 DX 的值（0x0060）放在地址总线上
    ↓
CPU 发出 IOR#（I/O Read）信号
    ↓
地址解码器检测到：
  - 地址 = 0x0060
  - IOR# 有效
  - 地址范围 0x60-0x6F → 键盘控制器
    ↓
地址解码器将信号路由到 8042 键盘控制器
    ↓
8042 检测到读取请求：
  - 检查输出缓冲区（OBF）
  - 如果有数据，将扫描码放在数据总线上
    ↓
CPU 从数据总线读取数据到 AL 寄存器
    ↓
指令完成，AL 包含扫描码
```

### 写入键盘命令的完整流程

**C 代码**：
```c
// seabios/src/hw/ps2port.c:413
i8042_command(I8042_CMD_KBD_ENABLE, NULL);  // 0xAE
```

**内部实现**（简化）：
```c
outb(0xAE, PORT_PS2_STATUS);  // PORT_PS2_STATUS = 0x64
```

**编译后的汇编代码**：
```asm
; 1. 加载命令值到 AL
mov al, 0xAE        ; I8042_CMD_KBD_ENABLE = 0xAE

; 2. 加载端口地址到 DX
mov dx, 0x0064      ; PORT_PS2_STATUS = 0x64

; 3. 执行 OUT 指令
out dx, al         ; 将 AL 的值写入端口 0x64
```

**硬件执行流程**：

```
CPU 执行 out dx, al
    ↓
CPU 将 DX 的值（0x0064）放在地址总线上
CPU 将 AL 的值（0xAE）放在数据总线上
    ↓
CPU 发出 IOW#（I/O Write）信号
    ↓
地址解码器检测到：
  - 地址 = 0x0064
  - IOW# 有效
  - 地址范围 0x60-0x6F → 键盘控制器
    ↓
地址解码器将信号路由到 8042 键盘控制器
    ↓
8042 检测到写入请求：
  - 从数据总线读取命令（0xAE）
  - 执行命令（启用键盘）
    ↓
指令完成，键盘已启用
```

---

## 7. 键盘中断处理中的 I/O 操作

### handle_09() 中的 I/O 操作

**源代码位置**：`seabios/src/hw/ps2port.c:389-417`

```c
void VISIBLE16
handle_09(void)
{
    // ... 省略检查代码 ...
    
    // 1. 读取键盘状态端口
    u8 v = inb(PORT_PS2_STATUS);  // PORT_PS2_STATUS = 0x64
    // 汇编：mov dx, 0x0064; in al, dx
    
    if (v & I8042_STR_AUXDATA) {
        // 检查是否为鼠标数据（bit 5）
        goto done;
    }
    
    // 2. 读取键盘数据端口（扫描码）
    v = inb(PORT_PS2_DATA);  // PORT_PS2_DATA = 0x60
    // 汇编：mov dx, 0x0060; in al, dx
    
    // ... 处理扫描码 ...
    
    // 3. 发送键盘启用命令
    i8042_command(I8042_CMD_KBD_ENABLE, NULL);  // 内部调用 outb(0xAE, 0x64)
    // 汇编：mov al, 0xAE; mov dx, 0x0064; out dx, al
    
done:
    pic_eoi1();  // 发送 EOI 到 PIC
}
```

### 完整的汇编代码示例

**完整的键盘中断处理程序（汇编版本）**：

```asm
; 键盘中断处理程序（INT 09h）
keyboard_handler:
    ; ========== 保存寄存器 ==========
    push ax
    push dx
    push ds
    
    ; ========== 设置数据段 ==========
    push cs
    pop ds
    
    ; ========== 1. 读取键盘状态端口 ==========
    mov dx, 0x0064      ; PORT_PS2_STATUS = 0x64
    in al, dx           ; 读取状态字节
    mov bl, al          ; 保存状态到 BL
    
    ; ========== 检查是否为鼠标数据 ==========
    test bl, 0x20       ; I8042_STR_AUXDATA = 0x20 (bit 5)
    jnz .done           ; 如果是鼠标数据，跳转
    
    ; ========== 2. 读取键盘数据端口（扫描码）==========
    mov dx, 0x0060      ; PORT_PS2_DATA = 0x60
    in al, dx           ; 读取扫描码到 AL
    mov cl, al          ; 保存扫描码到 CL
    
    ; ========== 检查中断是否启用 ==========
    ; （这里省略检查代码，实际代码会检查 Ps2ctr 变量）
    
    ; ========== 处理扫描码 ==========
    ; 调用 process_key(cl) 处理扫描码
    ; （这里省略处理代码）
    
    ; ========== 3. 发送键盘启用命令 ==========
    mov al, 0xAE        ; I8042_CMD_KBD_ENABLE = 0xAE
    mov dx, 0x0064      ; PORT_PS2_STATUS = 0x64
    out dx, al         ; 写入命令到控制端口
    
.done:
    ; ========== 发送 EOI 到 PIC ==========
    mov al, 0x20        ; EOI 命令
    out 0x20, al       ; 发送到主 PIC
    
    ; ========== 恢复寄存器 ==========
    pop ds
    pop dx
    pop ax
    
    ; ========== 中断返回 ==========
    iret
```

### I/O 操作的关键点

**1. 端口地址是立即数或 DX 寄存器**：
- `in al, 0x60`：端口地址是立即数（仅适用于 0x00-0xFF）
- `in al, dx`：端口地址在 DX 寄存器中（适用于 0x0000-0xFFFF）

**2. 数据方向**：
- `in al, dx`：从端口读取数据到 AL
- `out dx, al`：将 AL 的数据写入端口

**3. 状态检查**：
- 读取数据前应检查状态端口（0x64）的 OBF 位
- 写入命令前应检查状态端口的 IBF 位

**4. 指令执行时间**：
- I/O 操作可能需要等待硬件响应
- 某些操作需要轮询状态端口直到完成

---

## 总结

### 关键要点

1. **键盘控制器使用 I/O 端口，不是内存映射**：
   - 端口 0x60：数据端口（读取扫描码，发送命令）
   - 端口 0x64：控制端口（读取状态，发送控制命令）

2. **I/O 端口地址是硬件固定的**：
   - 由 IBM PC/AT 架构标准决定
   - 所有兼容系统必须使用相同的端口地址

3. **地址解码器负责路由**：
   - CPU 的地址总线信号由地址解码器路由到对应设备
   - 地址解码器是硬件电路，不是软件

4. **汇编指令**：
   - `in al, dx`：从 I/O 端口读取
   - `out dx, al`：向 I/O 端口写入

5. **I/O 地址空间独立于内存地址空间**：
   - 使用不同的指令（IN/OUT vs MOV）
   - 使用不同的控制信号（IOR#/IOW# vs MEMR#/MEMW#）

### 相关文档

- [BIOS_INTERRUPT_COMPLETE.md](BIOS_INTERRUPT_COMPLETE.md) - BIOS 中断处理完整详解
- [APPENDIX_A_KEYBOARD_INTERRUPT.md](APPENDIX_A_KEYBOARD_INTERRUPT.md) - 键盘中断处理代码分析
- [QEMU_VS_HARDWARE_BIOS.md](QEMU_VS_HARDWARE_BIOS.md) - QEMU vs 真实硬件的 BIOS 加载对比
- [BOOT_FLOW_NOTES.md](BOOT_FLOW_NOTES.md) - BIOS 128KB 内存映射的硬件实现

---

## 8. I/O 地址的学习资源与硬件实现

### 8.1 I/O 地址的学习资源

#### 官方文档和规范

1. **Intel x86 架构手册**
   - **文档名称**：《Intel® 64 and IA-32 Architectures Software Developer's Manual》
   - **关键章节**：
     - Volume 1, Chapter 3: "Basic Execution Environment" - I/O 端口寻址
     - Volume 1, Chapter 5: "Instruction Set Reference" - IN/OUT 指令说明
     - Volume 3, Chapter 7: "I/O Ports" - I/O 端口访问机制
   - **下载地址**：https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html

2. **IBM PC/AT 技术参考手册**
   - **文档名称**：《IBM Personal Computer AT Technical Reference》
   - **关键内容**：
     - I/O 端口地址分配表
     - 8042 键盘控制器规范
     - 8259A PIC 规范
   - **在线资源**：https://www.minuszerodegrees.net/manuals/IBM_5150_5160_Technical_Reference_6025005_AUG84.pdf

3. **8042 键盘控制器数据手册**
   - **文档名称**：《Intel 8042 Microcontroller Data Sheet》
   - **关键内容**：
     - 8042 芯片引脚定义
     - I/O 端口寄存器说明
     - 命令和状态位定义
   - **在线资源**：可通过 Intel 官方网站或技术文档库查找

#### 在线学习资源

1. **OSDev Wiki**
   - **网址**：https://wiki.osdev.org/
   - **相关页面**：
     - https://wiki.osdev.org/I/O_Ports - I/O 端口基础
     - https://wiki.osdev.org/Keyboard_Controller - 键盘控制器
     - https://wiki.osdev.org/8259_PIC - 8259A PIC
   - **特点**：实用性强，包含代码示例

2. **PCjs Machines**
   - **网址**：https://www.pcjs.org/
   - **特点**：在线模拟 IBM PC，可以查看 I/O 端口使用

3. **FreeDOS 文档**
   - **网址**：https://www.freedos.org/
   - **特点**：开源 DOS 实现，包含 I/O 端口使用示例

#### 开源项目学习

1. **SeaBIOS**
   - **项目地址**：https://github.com/coreboot/seabios
   - **关键文件**：
     - `src/hw/ps2port.c` - 键盘控制器 I/O 操作
     - `src/hw/pic.c` - PIC I/O 操作
     - `src/x86.h` - I/O 端口访问函数

2. **QEMU**
   - **项目地址**：https://github.com/qemu/qemu
   - **关键文件**：
     - `hw/input/pckbd.c` - 键盘控制器模拟
     - `hw/isa/isa-bus.c` - ISA 总线 I/O 端口注册
     - `system/ioport.c` - I/O 端口访问实现

3. **FreeDOS**
   - **项目地址**：https://github.com/FDOS/kernel
   - **特点**：DOS 内核实现，包含 I/O 端口使用示例

### 8.2 I/O 设备的地址总线与硬件实现

#### I/O 地址总线的特点

**I/O 地址总线与内存地址总线的区别**：

| 特性 | 内存地址总线 | I/O 地址总线 |
|------|------------|------------|
| **宽度** | 20-52 位（取决于 CPU） | 16 位（固定） |
| **地址范围** | 0x00000000 - 0xFFFFFFFF（32位） | 0x0000 - 0xFFFF（64K 端口） |
| **控制信号** | MEMR#/MEMW# | IOR#/IOW# |
| **选择信号** | M/IO# = 1 | M/IO# = 0 |
| **访问指令** | `mov [addr], al` | `in al, port` / `out port, al` |

**关键点**：
- **I/O 地址总线只使用地址总线的低 16 位**（A0-A15）
- **CPU 通过 M/IO# 信号区分内存访问和 I/O 访问**
- **I/O 地址空间与内存地址空间完全独立**

#### I/O 地址解码器的硬件实现

**I/O 地址解码器是硬件逻辑电路**，位于芯片组中：

```
CPU 执行 IN/OUT 指令
    ↓
地址总线（A0-A15）= I/O 端口地址（如 0x0060）
控制信号：
    - M/IO# = 0（表示 I/O 访问）
    - IOR# 或 IOW#（读/写信号）
    ↓
I/O 地址解码器（芯片组中）
    ├─ 地址范围比较器
    │   ├─ 0x0020-0x003F → PIC
    │   ├─ 0x0060-0x006F → 键盘控制器
    │   ├─ 0x0070-0x007F → CMOS/RTC
    │   └─ 其他范围 → 其他设备
    ├─ 多路选择器（MUX）
    └─ 设备选择信号生成
    ↓
路由到对应的硬件设备芯片
```

**硬件电路实现（简化 Verilog 伪代码）**：

```verilog
// I/O 地址解码器（硬件电路）
module io_address_decoder(
    input [15:0] address,      // I/O 地址总线（A0-A15）
    input io_read,              // IOR# 信号
    input io_write,             // IOW# 信号
    input m_io,                 // M/IO# 信号（0 = I/O）
    output pic_select,          // PIC 选择信号
    output kbd_select,         // 键盘控制器选择信号
    output rtc_select          // RTC 选择信号
);

// 地址范围匹配逻辑（硬件电路）
assign pic_select = (address >= 16'h0020) && 
                    (address <= 16'h003F) && 
                    !m_io && (io_read || io_write);

assign kbd_select = (address >= 16'h0060) && 
                    (address <= 16'h006F) && 
                    !m_io && (io_read || io_write);

assign rtc_select = (address >= 16'h0070) && 
                    (address <= 16'h007F) && 
                    !m_io && (io_read || io_write);

endmodule
```

**实际硬件实现细节**：

1. **地址范围比较器**：
   - 使用**比较器电路**（Comparator）比较地址总线值与预设范围
   - 例如：检测 `address >= 0x60 AND address <= 0x6F`
   - 输出：设备选择信号（如 KBD_SELECT）

2. **控制信号检测**：
   - 检测 M/IO# 信号（必须为 0，表示 I/O 访问）
   - 检测 IOR#/IOW# 信号（读/写操作）
   - 只有所有条件满足时才生成设备选择信号

3. **多路选择器（MUX）**：
   - 根据地址范围选择对应的数据源
   - 如果 `KBD_SELECT = 1`，则从键盘控制器读取/写入数据
   - 如果 `PIC_SELECT = 1`，则从 PIC 读取/写入数据

4. **设备芯片连接**：
   - 设备选择信号连接到硬件设备芯片的 CS（Chip Select）引脚
   - 地址总线信号连接到设备芯片的地址引脚
   - 数据总线连接到设备芯片的数据引脚
   - 控制信号（IOR#/IOW#）连接到设备芯片的控制引脚

#### 键盘控制器（8042）的硬件连接

**8042 芯片的物理连接**：

```
CPU
 │
 ├─ 地址总线（A0-A15）
 │  │
 │  └─→ 芯片组（I/O 地址解码器）
 │      │
 │      ├─ 检测地址范围 0x60-0x6F
 │      ├─ 生成 KBD_SELECT 信号
 │      │
 │      └─→ 8042 键盘控制器芯片（主板上的物理芯片）
 │          ├─ CS（Chip Select）引脚 ← KBD_SELECT
 │          ├─ A0-A2 地址引脚 ← 地址总线低 3 位（端口选择）
 │          ├─ D0-D7 数据引脚 ← 数据总线
 │          ├─ RD#（Read）引脚 ← IOR# 信号
 │          ├─ WR#（Write）引脚 ← IOW# 信号
 │          └─ IRQ1 引脚 → PIC（中断请求）
```

**8042 内部端口选择**：

- **地址位 A0**：选择数据端口（0x60）或控制端口（0x64）
  - `A0 = 0`：数据端口（0x60）
  - `A0 = 1`：控制端口（0x64）

**硬件实现**：

```verilog
// 8042 芯片内部端口选择逻辑
module i8042_chip(
    input [2:0] address,       // 地址总线低 3 位（A0-A2）
    input chip_select,         // CS 信号（来自地址解码器）
    input io_read,             // IOR# 信号
    input io_write,            // IOW# 信号
    inout [7:0] data_bus       // 数据总线
);

// 端口选择：A0 = 0 选择数据端口，A0 = 1 选择控制端口
wire data_port = chip_select && (address[0] == 0);
wire ctrl_port = chip_select && (address[0] == 1);

// 数据端口（0x60）访问
if (data_port && io_read) begin
    // 读取扫描码到数据总线
    data_bus = output_buffer;
end
if (data_port && io_write) begin
    // 从数据总线写入命令到键盘
    keyboard_command = data_bus;
end

// 控制端口（0x64）访问
if (ctrl_port && io_read) begin
    // 读取状态寄存器到数据总线
    data_bus = status_register;
end
if (ctrl_port && io_write) begin
    // 从数据总线写入控制器命令
    controller_command = data_bus;
end

endmodule
```

### 8.3 QEMU 源代码实现分析

#### QEMU I/O 端口注册机制

**QEMU 通过软件模拟硬件地址解码器**，使用内存区域（MemoryRegion）机制实现 I/O 端口映射。

#### 1. I/O 端口注册流程

**源代码位置**：`qemu/hw/input/pckbd.c:834-879`

```c
// 步骤 1: 初始化 I/O 内存区域（i8042_initfn）
static void i8042_initfn(Object *obj)
{
    ISAKBDState *isa_s = I8042(obj);
    KBDState *s = &isa_s->kbd;

    // 创建数据端口内存区域（0x60）
    memory_region_init_io(isa_s->io + 0, obj, &i8042_data_ops, s,
                          "i8042-data", 1);
    // ↑ 创建 1 字节的内存区域，绑定 i8042_data_ops 操作函数

    // 创建控制端口内存区域（0x64）
    memory_region_init_io(isa_s->io + 1, obj, &i8042_cmd_ops, s,
                          "i8042-cmd", 1);
    // ↑ 创建 1 字节的内存区域，绑定 i8042_cmd_ops 操作函数
}

// 步骤 2: 注册 I/O 端口到 ISA 总线（i8042_realizefn）
static void i8042_realizefn(DeviceState *dev, Error **errp)
{
    ISADevice *isadev = ISA_DEVICE(dev);
    ISAKBDState *isa_s = I8042(dev);

    // 注册数据端口（0x60）
    isa_register_ioport(isadev, isa_s->io + 0, 0x60);
    // ↑ 将内存区域 isa_s->io[0] 注册到 I/O 地址空间 0x60

    // 注册控制端口（0x64）
    isa_register_ioport(isadev, isa_s->io + 1, 0x64);
    // ↑ 将内存区域 isa_s->io[1] 注册到 I/O 地址空间 0x64
}
```

**关键函数说明**：

1. **`memory_region_init_io()`**：
   - **功能**：创建 I/O 内存区域，绑定读写操作函数
   - **参数**：
     - `isa_s->io + 0`：内存区域对象
     - `&i8042_data_ops`：操作函数表（包含 read/write 回调）
     - `s`：传递给回调函数的不透明指针（KBDState）
     - `"i8042-data"`：内存区域名称
     - `1`：内存区域大小（1 字节）

2. **`isa_register_ioport()`**：
   - **功能**：将内存区域注册到 ISA 总线的 I/O 地址空间
   - **实现**：`memory_region_add_subregion(isa_address_space_io(dev), start, io)`
   - **效果**：当 CPU 访问 I/O 端口 `start` 时，QEMU 会调用对应的读写函数

#### 2. I/O 端口操作函数

**源代码位置**：`qemu/hw/input/pckbd.c:789-807`

```c
// 数据端口（0x60）操作函数
static const MemoryRegionOps i8042_data_ops = {
    .read = kbd_read_data,      // 读取函数：从键盘读取扫描码
    .write = kbd_write_data,    // 写入函数：向键盘发送命令
    .impl = {
        .min_access_size = 1,   // 最小访问大小：1 字节
        .max_access_size = 1,   // 最大访问大小：1 字节
    },
    .endianness = DEVICE_LITTLE_ENDIAN,  // 小端序
};

// 控制端口（0x64）操作函数
static const MemoryRegionOps i8042_cmd_ops = {
    .read = kbd_read_status,    // 读取函数：读取控制器状态
    .write = kbd_write_command, // 写入函数：发送控制器命令
    .impl = {
        .min_access_size = 1,
        .max_access_size = 1,
    },
    .endianness = DEVICE_LITTLE_ENDIAN,
};
```

**读写函数实现**：

**源代码位置**：`qemu/hw/input/pckbd.c:399-421, 423-469`

```c
// 读取数据端口（0x60）：读取键盘扫描码
static uint64_t kbd_read_data(void *opaque, hwaddr addr, unsigned size)
{
    KBDState *s = opaque;  // KBDState 包含键盘状态和缓冲区

    // 检查输出缓冲区满标志（OBF）
    if (s->status & KBD_STAT_OBF) {
        kbd_deassert_irq(s);  // 清除中断
        
        // 根据数据来源读取
        if (s->obsrc & KBD_OBSRC_KBD) {
            // 从键盘设备读取扫描码
            s->obdata = ps2_read_data(PS2_DEVICE(&s->ps2kbd));
        } else if (s->obsrc & KBD_OBSRC_MOUSE) {
            // 从鼠标设备读取数据
            s->obdata = ps2_read_data(PS2_DEVICE(&s->ps2mouse));
        } else if (s->obsrc & KBD_OBSRC_CTRL) {
            // 从控制器缓冲区读取
            s->obdata = kbd_dequeue(s);
        }
    }

    return s->obdata;  // 返回读取的数据（扫描码）
}

// 写入数据端口（0x60）：向键盘发送命令
static void kbd_write_data(void *opaque, hwaddr addr,
                           uint64_t val, unsigned size)
{
    KBDState *s = opaque;

    switch (s->write_cmd) {
    case 0:
        // 直接写入键盘命令
        ps2_write_keyboard(&s->ps2kbd, val);
        s->mode &= ~KBD_MODE_DISABLE_KBD;
        kbd_safe_update_irq(s);
        break;
    case KBD_CCMD_WRITE_MODE:
        // 写入模式寄存器
        s->mode = val;
        break;
    // ... 其他命令处理 ...
    }
}

// 读取控制端口（0x64）：读取控制器状态
static uint64_t kbd_read_status(void *opaque, hwaddr addr, unsigned size)
{
    KBDState *s = opaque;
    return s->status;  // 返回状态寄存器值
}

// 写入控制端口（0x64）：发送控制器命令
static void kbd_write_command(void *opaque, hwaddr addr,
                              uint64_t val, unsigned size)
{
    KBDState *s = opaque;

    switch (val) {
    case KBD_CCMD_KBD_ENABLE:  // 0xAE：启用键盘
        s->mode &= ~KBD_MODE_DISABLE_KBD;
        kbd_safe_update_irq(s);
        break;
    case KBD_CCMD_KBD_DISABLE:  // 0xAD：禁用键盘
        s->mode |= KBD_MODE_DISABLE_KBD;
        break;
    // ... 其他命令处理 ...
    }
}
```

#### 3. QEMU I/O 地址空间管理

**源代码位置**：`qemu/hw/isa/isa-bus.c:128-132`

```c
// isa_register_ioport 的实现
void isa_register_ioport(ISADevice *dev, MemoryRegion *io, uint16_t start)
{
    // 将内存区域添加到 ISA 总线的 I/O 地址空间
    memory_region_add_subregion(isa_address_space_io(dev), start, io);
    // ↑ 这相当于硬件地址解码器的功能，但是用软件实现的
    //   当 CPU 访问 I/O 端口 start 时，QEMU 会调用 io 内存区域的读写函数
    
    isa_init_ioport(dev, start);  // 初始化 I/O 端口 ID
}
```

**I/O 地址空间结构**：

```
QEMU I/O 地址空间（address_space_io）
    ├─ 0x0020-0x003F → PIC 内存区域
    ├─ 0x0060 → i8042 数据端口内存区域（i8042_data_ops）
    ├─ 0x0064 → i8042 控制端口内存区域（i8042_cmd_ops）
    ├─ 0x0070-0x007F → CMOS/RTC 内存区域
    └─ 其他 I/O 设备...
```

**CPU 访问 I/O 端口的 QEMU 处理流程**：

```
1. 客户机 CPU 执行：in al, 0x60
    ↓
2. QEMU TCG 翻译器将指令翻译为 QEMU 内部函数调用
    ↓
3. 调用 cpu_inb(0x60)
    ↓
4. address_space_read(&address_space_io, 0x60, ...)
    ↓
5. 查找 I/O 地址空间 0x60 对应的内存区域
    ↓
6. 找到 i8042 数据端口内存区域（isa_s->io[0]）
    ↓
7. 调用内存区域的 read 函数：i8042_data_ops.read
    ↓
8. 执行 kbd_read_data(s, 0x60, 1)
    ↓
9. 从 PS2 键盘设备读取扫描码
    ↓
10. 返回数据给客户机 CPU
```

#### 4. QEMU vs 真实硬件的对比

| 方面 | 真实硬件 | QEMU 软件实现 |
|------|---------|--------------|
| **地址解码** | 硬件电路（地址解码器） | 软件查找（内存区域树） |
| **响应时间** | 纳秒级别（硬件电路） | 微秒级别（软件处理） |
| **实现位置** | 芯片组/主板 | QEMU 进程内存管理 |
| **I/O 端口注册** | 硬件设计时确定（固定） | 软件动态注册（灵活） |
| **设备模拟** | 物理芯片（8042） | 软件状态机（KBDState） |
| **数据来源** | 硬件键盘 | QEMU 输入子系统 |

**QEMU 的优势**：
- **灵活性**：可以动态注册/注销 I/O 端口
- **可调试性**：可以添加日志、断点等调试功能
- **可扩展性**：可以模拟不存在的硬件设备

**真实硬件的优势**：
- **性能**：硬件电路响应速度快
- **可靠性**：硬件电路稳定可靠
- **标准化**：符合 IBM PC/AT 架构标准

### 8.4 学习路径建议

**阶段 1：理解 I/O 端口基础（1-2 周）**
1. 阅读 Intel x86 架构手册 Volume 1, Chapter 3（I/O 端口寻址）
2. 理解 IN/OUT 指令的工作原理
3. 查看 SeaBIOS 的 I/O 端口访问代码（`src/x86.h`）

**阶段 2：理解硬件实现（2-3 周）**
1. 阅读 IBM PC/AT 技术参考手册（I/O 端口地址分配）
2. 理解地址解码器的硬件实现原理
3. 查看 8042 键盘控制器数据手册

**阶段 3：理解 QEMU 实现（2-3 周）**
1. 阅读 QEMU 源代码：`hw/input/pckbd.c`
2. 理解 `memory_region_init_io()` 和 `isa_register_ioport()` 的工作原理
3. 跟踪 CPU 执行 `in al, 0x60` 的完整流程

**阶段 4：实践项目（持续）**
1. 在 QEMU 中添加自定义 I/O 端口设备
2. 编写简单的键盘控制器模拟器
3. 分析其他 I/O 设备的实现（PIC、定时器等）

### 相关文档

- [BIOS_INTERRUPT_COMPLETE.md](BIOS_INTERRUPT_COMPLETE.md) - BIOS 中断处理完整详解
- [APPENDIX_A_KEYBOARD_INTERRUPT.md](APPENDIX_A_KEYBOARD_INTERRUPT.md) - 键盘中断处理代码分析
- [QEMU_VS_HARDWARE_BIOS.md](QEMU_VS_HARDWARE_BIOS.md) - QEMU vs 真实硬件的 BIOS 加载对比
- [BOOT_FLOW_NOTES.md](BOOT_FLOW_NOTES.md) - BIOS 128KB 内存映射的硬件实现

