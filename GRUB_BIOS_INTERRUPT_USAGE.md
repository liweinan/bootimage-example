# GRUB 在保护模式下调用 BIOS 服务的使用场景

## grub_bios_interrupt 函数的使用位置

**函数定义：** `grub/grub-core/kern/i386/int.S:19-134`

`grub_bios_interrupt` 是 GRUB 在保护模式下调用 BIOS 中断服务的核心函数。该函数通过 `prot_to_real` 和 `real_to_prot` 在保护模式和实模式之间切换，从而能够调用 BIOS 提供的实模式中断服务。

## 主要使用场景

### 1. 磁盘操作（INT 13h）

**使用位置：** `grub/grub-core/disk/i386/pc/biosdisk.c`

**功能：**
- 重置磁盘系统
- 获取磁盘类型
- 读取/写入磁盘扇区（标准模式和扩展模式）
- 获取磁盘参数

**调用时机：**
- GRUB 初始化时检测可用磁盘
- 加载内核镜像时读取磁盘
- 加载 initramfs 时读取磁盘
- 访问配置文件（`grub.cfg`）时读取磁盘

**示例代码：**
```c
// 重置磁盘系统
regs.eax = 0;
regs.edx = 0;
regs.flags = GRUB_CPU_INT_FLAGS_DEFAULT;
grub_bios_interrupt (0x13, &regs);

// 读取磁盘扇区（扩展模式）
regs.eax = 0x4200;  // AH=0x42: Extended Read
regs.edx = drive;
regs.ds = (dap_address >> 4);
regs.esi = (dap_address & 0xffff);
grub_bios_interrupt (0x13, &regs);
```

### 2. 内存映射查询（INT 12h, INT 15h）

**使用位置：** `grub/grub-core/kern/i386/pc/mmap.c`

**功能：**
- **INT 12h**：获取常规内存大小（1MB 以下）
- **INT 15h, AH=0x88**：获取扩展内存大小（1MB-16MB）
- **INT 15h, AX=0xE801**：获取 EISA 内存映射（1MB-16MB 和 16MB 以上）
- **INT 15h, AX=0xE820**：获取完整内存映射（E820 表）

**调用时机：**
- `grub_stub_init()` 初始化时获取内存信息
- 构建 E820 内存映射表传递给内核
- 确定可用内存范围

**示例代码：**
```c
// 获取常规内存大小
regs.flags = GRUB_CPU_INT_FLAGS_DEFAULT;
grub_bios_interrupt (0x12, &regs);
return regs.eax & 0xffff;  // 返回 KB 数

// 获取扩展内存大小
regs.eax = 0x8800;
regs.flags = GRUB_CPU_INT_FLAGS_DEFAULT;
grub_bios_interrupt (0x15, &regs);
return regs.eax & 0xffff;  // 返回 KB 数
```

### 3. 视频服务（INT 10h）

**使用位置：**
- `grub/grub-core/term/i386/pc/console.c` - 控制台输出
- `grub/grub-core/term/i386/pc/vga_text.c` - VGA 文本模式
- `grub/grub-core/video/i386/pc/vga.c` - VGA 图形模式
- `grub/grub-core/video/i386/pc/vbe.c` - VBE（VESA BIOS Extensions）

**功能：**
- 设置显示模式
- 显示字符
- 获取/设置光标位置
- 清屏
- VBE 模式查询和设置

**调用时机：**
- 初始化显示设备
- 显示 GRUB 菜单
- 显示启动信息
- 用户交互（菜单选择）

**示例代码：**
```c
// 显示字符
regs.eax = ch | 0x0900;  // AH=0x09: Write Character and Attribute
regs.ebx = color;
regs.ecx = n;  // 重复次数
grub_bios_interrupt (0x10, &regs);

// 获取光标位置
regs.eax = 0x0300;  // AH=0x03: Get Cursor Position
regs.ebx = 0;
grub_bios_interrupt (0x10, &regs);
```

### 4. 键盘服务（INT 16h）

**使用位置：** `grub/grub-core/term/i386/pc/console.c`

**功能：**
- 读取按键输入
- 检查按键状态
- 等待按键

**调用时机：**
- 用户选择 GRUB 菜单项
- 用户输入命令
- 等待用户确认

**示例代码：**
```c
// 读取按键（不等待）
regs.eax = 0x0100;  // AH=0x01: Check Keyboard Status
grub_bios_interrupt (0x16, &regs);

// 读取按键（等待）
regs.eax = 0x0000;  // AH=0x00: Read Character
grub_bios_interrupt (0x16, &regs);
```

### 5. 实时时钟服务（INT 1Ah）

**使用位置：**
- `grub/grub-core/kern/i386/pc/init.c` - 获取 RTC 时间
- `grub/grub-core/net/drivers/i386/pc/pxe.c` - PXE 网络启动

**功能：**
- 获取系统时间（RTC）
- PXE 网络配置

**调用时机：**
- `grub_rtc_get_time_ms()` 获取当前时间
- PXE 网络启动时获取网络配置

**示例代码：**
```c
// 获取 RTC 时间
regs.eax = 0;  // AH=0x00: Read RTC Time
regs.flags = GRUB_CPU_INT_FLAGS_DEFAULT;
grub_bios_interrupt (0x1a, &regs);
return ((regs.ecx << 16) | (regs.edx & 0xffff)) * 55ULL;  // 转换为毫秒
```

### 6. 电源管理服务（INT 15h）

**使用位置：**
- `grub/grub-core/commands/i386/pc/halt.c` - 系统关机
- `grub/grub-core/commands/i386/pc/lsapm.c` - APM 信息查询

**功能：**
- APM（Advanced Power Management）电源管理
- 系统关机/重启
- 查询 APM 信息

**调用时机：**
- 用户选择关机/重启
- 查询系统电源管理能力

## 调用时机总结

**在 `grub_stub_init()` 执行期间：**
1. **内存映射查询**（INT 12h, INT 15h）- 初始化内存管理
2. **RTC 时间获取**（INT 1Ah）- 初始化时间服务
3. **磁盘检测**（INT 13h）- 初始化磁盘驱动
4. **显示初始化**（INT 10h）- 初始化控制台

**在 `grub_main()` 执行期间：**
1. **读取配置文件**（INT 13h）- 从磁盘读取 `grub.cfg`
2. **显示菜单**（INT 10h）- 显示 GRUB 启动菜单
3. **用户交互**（INT 16h）- 处理用户输入
4. **加载内核**（INT 13h）- 从磁盘读取内核镜像和 initramfs
5. **传递内存映射**（INT 15h）- 构建 E820 表传递给内核

## 关键点

1. **所有调用都在保护模式下进行**：
   - GRUB 在 `real_to_prot()` 后进入保护模式
   - 所有 `grub_bios_interrupt` 调用都发生在保护模式下
   - 函数内部通过 `prot_to_real` 切换回实模式调用 BIOS 服务

2. **频繁的模式切换**：
   - 每次调用 BIOS 服务都需要切换两次模式（保护→实→保护）
   - 这是 GRUB 能够同时利用保护模式优势（访问 1MB 以上内存）和 BIOS 服务的关键机制

3. **性能考虑**：
   - 模式切换有性能开销，但这是必要的权衡
   - GRUB 尽量减少不必要的 BIOS 调用
   - 大部分工作（文件系统解析、配置解析等）在保护模式下完成

4. **与内核的对比**：
   - GRUB 在保护模式下仍依赖 BIOS 服务
   - Linux 内核在建立自己的 IDT 后完全脱离 BIOS
   - 内核使用自己的设备驱动，不再调用 BIOS 中断服务

## 使用统计

根据 GRUB 源代码分析，`grub_bios_interrupt` 的主要使用情况：

| BIOS 中断 | 使用次数 | 主要用途 | 关键文件 |
|----------|---------|---------|---------|
| **INT 10h** | ~30+ | 视频服务、显示 | `vbe.c`, `console.c`, `vga.c` |
| **INT 13h** | ~10+ | 磁盘读写 | `biosdisk.c` |
| **INT 15h** | ~10+ | 内存映射、电源管理 | `mmap.c`, `halt.c`, `lsapm.c` |
| **INT 16h** | ~5 | 键盘输入 | `console.c` |
| **INT 1Ah** | ~3 | RTC 时间、PXE | `init.c`, `pxe.c` |
| **INT 12h** | ~1 | 常规内存大小 | `mmap.c` |

**总结：** `grub_bios_interrupt` 是 GRUB 在保护模式下访问 BIOS 服务的唯一途径，贯穿整个 GRUB 执行过程，从初始化到加载内核的每个阶段都会使用。

> **相关文档**：关于 `grub_bios_interrupt` 的实现细节和模式切换机制，请参见 [GRUB 模式切换函数详解](GRUB_MODE_SWITCHING.md)。
