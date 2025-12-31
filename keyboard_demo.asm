; keyboard_demo.asm - 键盘输入处理演示程序
; 演示如何处理键盘中断，并在用户按下按键时显示消息
; 当用户按下按键时，显示：'x' was pressed!

org 0x7C00
bits 16

start:
    ; 初始化显示
    mov ax, 0x0003      ; 设置 80x25 文本模式
    int 0x10
    
    ; 显示欢迎消息
    mov si, msg_welcome
    call print_string
    
    ; 显示提示消息
    mov si, msg_instruction
    call print_string
    
    ; ========== 设置键盘中断处理程序 ==========
    call setup_keyboard_handler
    
    ; 显示设置完成消息
    mov si, msg_handler_setup
    call print_string
    
    ; ========== 主循环：等待键盘输入 ==========
    ; 在引导扇区程序中，我们进入无限循环等待中断
    ; 当用户按下按键时，键盘中断会自动触发我们的处理程序
main_loop:
    ; 这里可以执行其他任务，或者只是等待
    ; 由于中断是异步的，我们不需要主动轮询键盘
    hlt                 ; 暂停 CPU，等待中断（节省电力）
    jmp main_loop       ; 如果从 hlt 唤醒，继续循环

; ========== 设置键盘中断处理程序 ==========
; 功能：挂钩键盘中断（INT 09h），使其调用我们的处理程序
; 输入：无
; 输出：无
;
; 工作原理：
; 1. 保存原始的 INT 09h 中断向量（以便后续恢复或调用）
; 2. 设置新的 INT 09h 中断向量，指向我们的处理程序
; 3. 这样当键盘中断发生时，CPU 会自动调用我们的处理程序
setup_keyboard_handler:
    push ax
    push es
    push bx
    
    cli                 ; 关中断，防止在设置过程中被中断
    
    ; 保存原始中断向量
    mov ax, 0
    mov es, ax          ; es = 0（中断向量表在段 0）
    mov bx, 0x09 * 4    ; INT 09h 向量地址 = 0x0024
    
    ; 读取原始向量
    mov ax, [es:bx]     ; 读取偏移地址（低 2 字节）
    mov [old_int09_offset], ax
    mov ax, [es:bx+2]   ; 读取段地址（高 2 字节）
    mov [old_int09_segment], ax
    
    ; 设置新的中断向量
    mov word [es:bx], keyboard_handler
    ; 设置偏移地址为我们的处理程序地址
    mov [es:bx+2], cs
    ; 设置段地址为当前代码段（cs）
    
    sti                 ; 开中断，允许中断处理
    
    pop bx
    pop es
    pop ax
    ret

; ========== 键盘中断处理程序 ==========
; 功能：处理键盘中断，读取按键并显示消息
; 输入：无（由硬件中断自动调用）
; 输出：无
;
; 工作原理：
; 1. 从键盘端口读取扫描码
; 2. 判断是按下还是释放（扫描码最高位：0=按下，1=释放）
; 3. 如果是按下，将扫描码转换为 ASCII 码
; 4. 显示消息：'x' was pressed!
; 5. 调用原始 BIOS 键盘处理程序（保持系统兼容性）
;
; 注意事项：
; - 这是中断处理程序，必须快速执行
; - 必须保存和恢复所有使用的寄存器
; - 必须发送 EOI（End of Interrupt）到 PIC
; - 必须使用 iret 返回
keyboard_handler:
    ; ========== 保存所有寄存器 ==========
    push ax
    push bx
    push cx
    push dx
    push si
    push ds
    push es
    
    ; ========== 设置数据段 ==========
    push cs
    pop ds              ; ds = cs（使我们可以访问程序中的数据）
    
    ; ========== 读取键盘扫描码 ==========
    in al, 0x60
    ; in 指令：从 I/O 端口读取数据
    ; 0x60 是键盘数据端口（Keyboard Data Port）
    ; al 现在包含按键的扫描码（Scan Code）
    ; 扫描码范围：0x01-0x83（不同按键有不同的扫描码）
    
    ; ========== 检查是否是按键释放 ==========
    test al, 0x80
    ; test 指令：执行 al AND 0x80 操作
    ; 扫描码的最高位（bit 7）表示按键状态：
    ;   - 0 = 按键按下（Make Code）
    ;   - 1 = 按键释放（Break Code）
    jnz .key_release
    ; jnz 指令：如果结果不为零（最高位为1），跳转到 .key_release
    ; 我们只处理按键按下事件，忽略按键释放
    
    ; ========== 保存扫描码 ==========
    mov [last_scancode], al
    ; 保存扫描码，以便后续使用
    
    ; ========== 将扫描码转换为 ASCII ==========
    ; 注意：这是一个简化的转换，只处理部分按键
    ; 实际应用中应该使用完整的扫描码到 ASCII 转换表
    call scancode_to_ascii
    ; 调用转换函数，结果在 al 中
    
    ; ========== 检查转换是否成功 ==========
    cmp al, 0
    ; 如果 al = 0，表示无法转换（可能是特殊键）
    je .skip_display
    ; 跳过显示，直接调用原始处理程序
    
    ; ========== 显示按键消息 ==========
    ; 格式：'x' was pressed!（x 是实际按下的按键字符）
    ; 例如：按下 'a' 键会显示 "'a' was pressed!"
    mov ah, 0x0E        ; TTY 模式显示字符
    
    ; 显示左单引号
    mov al, 0x27       ; 单引号 '（ASCII 码 0x27）
    int 0x10
    
    ; 显示实际按下的按键字符
    mov al, [last_ascii]
    ; 从 last_ascii 变量读取转换后的 ASCII 码
    ; 这个值是由 scancode_to_ascii 函数根据扫描码转换得到的
    int 0x10
    ; 显示按键字符（例如：'a', 'b', '1', '2' 等）
    
    ; 显示右单引号
    mov al, 0x27       ; 单引号 '
    int 0x10
    
    ; 显示 " was pressed!" 消息
    mov si, msg_was_pressed
    ; msg_was_pressed 包含字符串 " was pressed!"
    call print_string_interrupt
    ; 最终显示效果：'a' was pressed!（如果按下的是 'a' 键）
    
    ; ========== 发送 EOI 到 PIC ==========
.skip_display:
    ; 发送 EOI（End of Interrupt）到可编程中断控制器（PIC）
    ; 这告诉 PIC 中断已经被处理，可以处理下一个中断
    mov al, 0x20
    ; 0x20 是 EOI 命令
    out 0x20, al
    ; out 指令：向 I/O 端口写入数据
    ; 0x20 是主 PIC 的命令端口
    
    ; ========== 调用原始 BIOS 键盘处理程序 ==========
    ; 为了保持系统兼容性，我们调用原始的 BIOS 处理程序
    ; 这样 BIOS 可以更新键盘缓冲区等
    pushf
    ; pushf 指令：将 FLAGS 压入栈（模拟中断调用）
    call far [old_int09_offset]
    ; call far 指令：远调用原始处理程序
    ; 这会调用 BIOS 的键盘处理程序，完成标准的键盘处理
    
.key_release:
    ; ========== 处理按键释放 ==========
    ; 对于按键释放，我们只需要发送 EOI 并调用原始处理程序
    mov al, 0x20
    out 0x20, al        ; 发送 EOI
    
    pushf
    call far [old_int09_offset]
    ; 调用原始处理程序
    
    ; ========== 恢复寄存器并返回 ==========
.done:
    pop es
    pop ds
    pop si
    pop dx
    pop cx
    pop bx
    pop ax
    iret
    ; iret 指令：中断返回
    ; 功能：
    ;   1. 从栈弹出 IP（恢复指令指针）
    ;   2. 从栈弹出 CS（恢复代码段）
    ;   3. 从栈弹出 FLAGS（恢复所有标志位，包括 IF）
    ;   4. 继续执行被中断的程序

; ========== 扫描码转 ASCII 码 ==========
; 功能：将键盘扫描码转换为 ASCII 码
; 输入：al = 扫描码
; 输出：al = ASCII 码（如果无法转换，返回 0）
;
; 注意：这是一个简化的转换表，只处理部分按键
; 实际应用中应该使用完整的转换表，包括：
; - 字母键（A-Z, a-z）
; - 数字键（0-9）
; - 符号键（!@#$%等）
; - 功能键（F1-F12）
; - 控制键（Shift, Ctrl, Alt等）
scancode_to_ascii:
    push bx
    push si
    
    ; 使用查找表转换
    mov bx, scancode_table
    mov si, 0
    
.loop:
    ; 检查是否到达表末尾
    cmp byte [bx + si], 0
    je .not_found
    
    ; 比较扫描码
    cmp al, [bx + si]
    je .found
    
    ; 移动到下一个条目（每个条目 2 字节：扫描码 + ASCII）
    add si, 2
    jmp .loop
    
.found:
    ; 找到匹配的扫描码，读取对应的 ASCII 码
    mov al, [bx + si + 1]
    ; si 指向扫描码，si+1 指向 ASCII 码
    jmp .done
    
.not_found:
    ; 未找到匹配的扫描码，返回 0
    mov al, 0
    
.done:
    mov [last_ascii], al
    ; 保存 ASCII 码
    pop si
    pop bx
    ret

; ========== 在中断处理程序中打印字符串 ==========
; 功能：在中断处理程序中安全地打印字符串
; 输入：si = 字符串地址（以 0 结尾）
; 输出：无
;
; 注意：这个函数专门用于中断处理程序
; 它只使用 ax 和 si，并且会恢复它们
print_string_interrupt:
    push ax
    push si
    
    mov ah, 0x0E        ; TTY 模式显示字符
.loop:
    lodsb               ; 从 [si] 加载字符到 al，si++
    test al, al         ; 检查是否为 0（字符串结束）
    jz .done
    int 0x10            ; 显示字符
    jmp .loop
.done:
    pop si
    pop ax
    ret

; ========== 普通打印字符串函数 ==========
; 功能：打印字符串（用于非中断上下文）
; 输入：si = 字符串地址（以 0 结尾）
; 输出：无
print_string:
    push ax
    push si
    
    mov ah, 0x0E        ; TTY 模式显示字符
.loop:
    lodsb               ; 从 [si] 加载字符到 al，si++
    test al, al         ; 检查是否为 0（字符串结束）
    jz .done
    int 0x10            ; 显示字符
    jmp .loop
.done:
    pop si
    pop ax
    ret

; ========== 数据定义 ==========

; 原始中断向量（用于调用原始 BIOS 处理程序）
old_int09_offset   dw 0
old_int09_segment dw 0

; 最后接收到的扫描码和 ASCII 码
last_scancode db 0
last_ascii    db 0

; 扫描码到 ASCII 码转换表
; 格式：每个条目 2 字节 [扫描码, ASCII码]
; 注意：这是一个简化的表，只包含部分按键
scancode_table:
    db 0x02, '1'        ; 扫描码 0x02 -> ASCII '1'
    db 0x03, '2'        ; 扫描码 0x03 -> ASCII '2'
    db 0x04, '3'        ; 扫描码 0x04 -> ASCII '3'
    db 0x05, '4'        ; 扫描码 0x05 -> ASCII '4'
    db 0x06, '5'        ; 扫描码 0x06 -> ASCII '5'
    db 0x07, '6'        ; 扫描码 0x07 -> ASCII '6'
    db 0x08, '7'        ; 扫描码 0x08 -> ASCII '7'
    db 0x09, '8'        ; 扫描码 0x09 -> ASCII '8'
    db 0x0A, '9'        ; 扫描码 0x0A -> ASCII '9'
    db 0x0B, '0'        ; 扫描码 0x0B -> ASCII '0'
    db 0x10, 'q'        ; 扫描码 0x10 -> ASCII 'q'
    db 0x11, 'w'        ; 扫描码 0x11 -> ASCII 'w'
    db 0x12, 'e'        ; 扫描码 0x12 -> ASCII 'e'
    db 0x13, 'r'        ; 扫描码 0x13 -> ASCII 'r'
    db 0x14, 't'        ; 扫描码 0x14 -> ASCII 't'
    db 0x15, 'y'        ; 扫描码 0x15 -> ASCII 'y'
    db 0x16, 'u'        ; 扫描码 0x16 -> ASCII 'u'
    db 0x17, 'i'        ; 扫描码 0x17 -> ASCII 'i'
    db 0x18, 'o'        ; 扫描码 0x18 -> ASCII 'o'
    db 0x19, 'p'        ; 扫描码 0x19 -> ASCII 'p'
    db 0x1E, 'a'        ; 扫描码 0x1E -> ASCII 'a'
    db 0x1F, 's'        ; 扫描码 0x1F -> ASCII 's'
    db 0x20, 'd'        ; 扫描码 0x20 -> ASCII 'd'
    db 0x21, 'f'        ; 扫描码 0x21 -> ASCII 'f'
    db 0x22, 'g'        ; 扫描码 0x22 -> ASCII 'g'
    db 0x23, 'h'        ; 扫描码 0x23 -> ASCII 'h'
    db 0x24, 'j'        ; 扫描码 0x24 -> ASCII 'j'
    db 0x25, 'k'        ; 扫描码 0x25 -> ASCII 'k'
    db 0x26, 'l'        ; 扫描码 0x26 -> ASCII 'l'
    db 0x2C, 'z'        ; 扫描码 0x2C -> ASCII 'z'
    db 0x2D, 'x'        ; 扫描码 0x2D -> ASCII 'x'
    db 0x2E, 'c'        ; 扫描码 0x2E -> ASCII 'c'
    db 0x2F, 'v'        ; 扫描码 0x2F -> ASCII 'v'
    db 0x30, 'b'        ; 扫描码 0x30 -> ASCII 'b'
    db 0x31, 'n'        ; 扫描码 0x31 -> ASCII 'n'
    db 0x32, 'm'        ; 扫描码 0x32 -> ASCII 'm'
    db 0x39, ' '        ; 扫描码 0x39 -> ASCII ' ' (空格键)
    db 0x0C, '-'        ; 扫描码 0x0C -> ASCII '-'
    db 0x0D, '='        ; 扫描码 0x0D -> ASCII '='
    db 0x1A, '['        ; 扫描码 0x1A -> ASCII '['
    db 0x1B, ']'        ; 扫描码 0x1B -> ASCII ']'
    db 0x27, ';'        ; 扫描码 0x27 -> ASCII ';'
    db 0x28, 0x27       ; 扫描码 0x28 -> ASCII ''' (单引号)
    db 0x29, '`'        ; 扫描码 0x29 -> ASCII '`'
    db 0x2B, '\'        ; 扫描码 0x2B -> ASCII '\'
    db 0x33, ','        ; 扫描码 0x33 -> ASCII ','
    db 0x34, '.'        ; 扫描码 0x34 -> ASCII '.'
    db 0x35, '/'        ; 扫描码 0x35 -> ASCII '/'
    db 0x0E, 0x08       ; 扫描码 0x0E -> ASCII 0x08 (退格键)
    db 0x1C, 0x0D       ; 扫描码 0x1C -> ASCII 0x0D (回车键)
    db 0x0F, 0x09       ; 扫描码 0x0F -> ASCII 0x09 (Tab键)
    db 0                ; 表结束标记

; 消息字符串
msg_welcome:
    db "=== Keyboard Input Demo ===", 0x0D, 0x0A, 0

msg_instruction:
    db "Press any key to see the message...", 0x0D, 0x0A, 0x0A, 0

msg_handler_setup:
    db "Keyboard handler installed. Waiting for input...", 0x0D, 0x0A, 0x0A, 0

msg_was_pressed:
    db " was pressed!", 0x0D, 0x0A, 0

; 填充到 510 字节
times 510-($-$$) db 0

; 引导扇区标志
dw 0xAA55

