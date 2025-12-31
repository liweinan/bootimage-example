# 手动实现 INT 指令示例

这个示例演示了如何用普通指令替代 `int` 指令，手动实现 BIOS 中断调用。

## 文件说明

- `manual_int_demo.asm` - 演示手动实现 `int 0x10` 的完整示例
- 展示了三种方法：
  1. 使用标准的 `int` 指令
  2. 手动实现 `int` 指令的功能
  3. 直接调用 BIOS（如果知道地址）

## 编译和运行

### 方法 1：使用 Makefile（推荐）

```bash
# 编译
make manual-int

# 在图形窗口中运行
make manual-int-gui

# 在终端中运行（适合 SSH 或无图形界面）
make manual-int-term
```

### 方法 2：手动编译和运行

```bash
# 编译
nasm -f bin manual_int_demo.asm -o manual_int_demo.bin

# 在 QEMU 图形窗口中运行
qemu-system-x86_64 -display sdl -drive format=raw,file=manual_int_demo.bin

# 在终端中运行
qemu-system-x86_64 -display curses -drive format=raw,file=manual_int_demo.bin
```

## 程序功能

程序会依次演示：

1. **方法 1：使用 INT 指令**
   - 使用标准的 `int 0x10` 指令显示字符 "ABC"
   - 这是最常见和推荐的方法

2. **方法 2：手动实现 INT**
   - 手动模拟 `int 0x10` 的所有步骤：
     - 保存 FLAGS、CS、IP
     - 查找中断向量表
     - 跳转到 BIOS 处理程序
     - 恢复执行
   - 显示字符 "XYZ"

3. **方法 3：直接调用 BIOS**
   - 尝试直接调用 BIOS（如果知道地址）
   - 如果地址不正确，会回退到使用 `int` 指令
   - 显示字符 "123"

## 代码说明

### 手动实现 INT 的核心函数

```nasm
manual_int10:
    pushf               ; 1. 保存 FLAGS
    push cs             ; 2. 保存当前代码段
    push .return        ; 3. 保存返回地址
    
    ; 4. 查找中断向量表
    mov ax, 0
    mov es, ax          ; es = 0（中断向量表在段 0）
    mov bx, 0x10 * 4    ; INT 10h 向量地址 = 0x0040
    
    ; 5. 读取向量并跳转
    push word [es:bx+2] ; 读取段地址
    push word [es:bx]   ; 读取偏移地址
    
    cli                 ; 6. 清除 IF 标志
    retf                ; 7. 远返回跳转到 BIOS 处理程序
    
.return:
    sti                 ; 恢复中断
    ret                 ; 返回到调用者
```

### 关键步骤

1. **保存状态**：`pushf`、`push cs`、`push .return`
2. **查找向量**：从地址 `0x0040` 读取 4 字节
3. **跳转执行**：使用 `retf` 跳转到 BIOS 处理程序
4. **恢复执行**：BIOS 执行 `iret` 后返回到 `.return`

## 学习要点

### 为什么通常不替代 `int` 指令？

1. **复杂性**：需要手动实现多个步骤，容易出错
2. **兼容性**：直接调用地址会失去可移植性
3. **性能**：`int` 是单条指令，硬件优化；手动实现需要多条指令
4. **功能完整性**：`int` 指令会正确处理所有标志位和状态

### 什么时候需要手动实现？

1. **挂钩中断（Hook）**：在调用原始处理程序前后添加自定义代码
2. **调试目的**：理解中断机制的工作原理
3. **特殊需求**：需要更精细控制中断处理流程

## 预期输出

运行程序后，你应该看到：

```
=== Manual INT Instruction Demo ===
Method 1: Using INT instruction
  Displaying ABC using INT 0x10: ABC
Method 2: Manual INT implementation
  Displaying XYZ using manual INT: XYZ
Method 3: Direct BIOS call (fallback to INT)
  Displaying 123 using direct call: 123

Demo completed!
```

## 注意事项

1. **方法 3 可能不工作**：直接调用 BIOS 需要知道确切的地址，不同系统可能不同
2. **这只是演示**：实际开发中应该使用标准的 `int` 指令
3. **理解原理**：这个示例主要用于理解 `int` 指令的工作原理

## 退出 QEMU

- **图形窗口模式**：按 `Ctrl+Alt+G` 释放鼠标，然后关闭窗口
- **终端模式**：按 `Ctrl+A`，松开后按 `X`（大写）

## 相关文档

- 查看 `GUIDE.md` 了解中断机制的完整说明
- 查看 `BIOS_INTERRUPT_STUDY.md` 了解 BIOS 中断的学习资源

