# 事件机制演示程序

这个示例演示了现代操作系统中事件订阅和触发机制的底层实现原理。

## 文件说明

- `event_demo.asm` - 完整的事件机制演示程序
- 实现了事件订阅、事件触发、多个处理器调用等功能

## 程序功能

程序演示了以下功能：

1. **事件系统初始化**
   - 初始化事件处理器数组
   - 初始化处理器计数器

2. **事件订阅**
   - 注册多个事件处理器（Handler 1, 2, 3）
   - 将处理器地址保存到数组中

3. **事件触发**
   - 触发事件时，依次调用所有已注册的处理器
   - 演示了事件广播机制

## 编译和运行

### 方法 1：使用 Makefile（推荐）

```bash
# 编译
make event-demo

# 在图形窗口中运行
make event-demo-gui

# 在终端中运行（适合 SSH 或无图形界面）
make event-demo-term
```

### 方法 2：手动编译和运行

```bash
# 编译
nasm -f bin event_demo.asm -o event_demo.bin

# 在 QEMU 图形窗口中运行
qemu-system-x86_64 -display sdl -drive format=raw,file=event_demo.bin

# 在终端中运行
qemu-system-x86_64 -display curses -drive format=raw,file=event_demo.bin
```

## 代码说明

### 核心数据结构

```nasm
; 事件处理器数组（最多10个处理器，每个2字节）
MAX_HANDLERS equ 10
event_handlers times MAX_HANDLERS dw 0

; 当前处理器数量
handler_count dw 0
```

### 事件订阅函数

```nasm
subscribe_event:
    ; 获取当前处理器数量
    mov bx, [handler_count]
    
    ; 计算数组索引位置（每个地址占2字节）
    mov cx, bx
    shl cx, 1           ; cx = bx * 2
    
    ; 保存处理器地址到数组
    mov si, event_handlers
    add si, cx
    mov [si], ax        ; 保存处理器地址
    
    ; 增加处理器计数
    inc word [handler_count]
    ret
```

### 事件触发函数

```nasm
trigger_event:
    ; 获取处理器数量
    mov bx, [handler_count]
    
    ; 循环调用所有处理器
    mov cx, 0
    mov si, event_handlers
.loop:
    mov dx, [si]        ; 获取处理器地址
    call dx             ; 调用处理器
    add si, 2           ; 移动到下一个地址
    inc cx
    cmp cx, bx
    jl .loop
    ret
```

## 预期输出

运行程序后，你应该看到：

```
=== Event System Demo ===
Initializing event system...

Subscribing event handlers:
  [OK] Handler 1 registered
  [OK] Handler 2 registered
  [OK] Handler 3 registered

Triggering event...
  -> Handler 1 executed!
  -> Handler 2 executed!
  -> Handler 3 executed!

Triggering event again...
  -> Handler 1 executed!
  -> Handler 2 executed!
  -> Handler 3 executed!

Demo completed!
```

## 工作原理

### 事件订阅流程

```
用户调用 subscribe_event(handler_address)
    ↓
检查是否超过最大数量
    ↓
计算数组索引位置
    ↓
保存处理器地址到数组
    ↓
增加处理器计数
```

### 事件触发流程

```
用户调用 trigger_event()
    ↓
获取处理器数量
    ↓
循环遍历处理器数组
    ↓
依次调用每个处理器
    ↓
所有处理器执行完毕
```

### 与现代操作系统的关系

这个示例展示了现代操作系统中事件机制的底层实现：

- **事件订阅**：类似于 `addEventListener()` 或 `subscribe()`
- **事件触发**：类似于 `dispatchEvent()` 或 `emit()`
- **处理器数组**：类似于事件监听器列表

## 扩展功能

你可以尝试添加以下功能：

1. **事件取消订阅**
   ```nasm
   unsubscribe_event:
       ; 从数组中移除指定的处理器
       ; 移动后续处理器填补空隙
       ; 减少处理器计数
   ```

2. **事件优先级**
   ```nasm
   ; 为每个处理器添加优先级字段
   ; 触发时按优先级排序调用
   ```

3. **事件参数传递**
   ```nasm
   ; 在触发事件时传递参数
   ; 处理器可以通过寄存器或栈接收参数
   ```

4. **事件过滤**
   ```nasm
   ; 只触发特定类型的事件
   ; 处理器可以注册特定的事件类型
   ```

## 学习要点

### 与现代操作系统的对比

| 特性 | 本示例 | 现代操作系统 |
|------|--------|------------|
| **事件订阅** | `subscribe_event()` | `addEventListener()` |
| **事件触发** | `trigger_event()` | `dispatchEvent()` |
| **处理器存储** | 数组 | 链表/数组 |
| **处理器调用** | 直接调用 | 通过调度器 |
| **参数传递** | 寄存器 | 事件对象 |

### 关键概念

1. **函数指针数组**：存储处理器地址的数组
2. **回调机制**：通过函数指针调用处理器
3. **事件广播**：一个事件触发多个处理器
4. **动态注册**：运行时添加/移除处理器

## 退出 QEMU

- **图形窗口模式**：按 `Ctrl+Alt+G` 释放鼠标，然后关闭窗口
- **终端模式**：按 `Ctrl+A`，松开后按 `X`（大写）

## 相关文档

- 查看 `GUIDE.md` 了解中断机制的完整说明
- 查看 `manual_int_demo.asm` 了解如何手动实现中断调用

