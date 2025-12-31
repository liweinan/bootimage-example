; manual_int_demo.asm - 演示手动实现 int 指令的功能
; 这个程序展示了如何用普通指令替代 int 0x10 指令
; 可以对比使用 int 指令和手动实现的区别

org 0x7C00
bits 16

start:
    ; 首先用标准的 int 指令设置显示模式
    mov ax, 0x0003      ; 设置 80x25 文本模式
    int 0x10
    
    ; 显示标题
    mov si, msg_title
    call print_string
    
    ; ========== 方法 1：使用标准的 int 指令 ==========
    mov si, msg_method1
    call print_string
    
    mov si, msg_using_int
    call print_string
    
    mov ah, 0x0E        ; TTY 模式显示字符
    mov al, 'A'
    int 0x10            ; 使用标准 int 指令显示字符 'A'
    
    mov al, 'B'
    int 0x10            ; 显示字符 'B'
    
    mov al, 'C'
    int 0x10            ; 显示字符 'C'
    
    call newline
    
    ; ========== 方法 2：手动实现 int 指令 ==========
    mov si, msg_method2
    call print_string
    
    mov si, msg_manual_impl
    call print_string
    
    ; 手动实现 int 0x10 的功能
    ; 设置参数：ah=0x0E (TTY模式), al='X'
    mov ah, 0x0E
    mov al, 'X'
    call manual_int10   ; 手动调用 INT 10h
    
    mov al, 'Y'
    call manual_int10   ; 手动调用 INT 10h
    
    mov al, 'Z'
    call manual_int10   ; 手动调用 INT 10h
    
    call newline
    
    ; ========== 方法 3：直接调用已知地址（如果知道BIOS地址）==========
    mov si, msg_method3
    call print_string
    
    mov si, msg_direct_call
    call print_string
    
    ; 注意：这个方法需要知道 BIOS 的实际地址
    ; 在真实环境中，BIOS 地址可能不同
    ; 这里只是演示概念，实际可能不会工作
    mov ah, 0x0E
    mov al, '1'
    call direct_bios_call
    
    mov al, '2'
    call direct_bios_call
    
    mov al, '3'
    call direct_bios_call
    
    call newline
    
    ; 显示结束信息
    mov si, msg_done
    call print_string
    
    jmp $

; ========== 手动实现 int 0x10 的函数 ==========
; 功能：手动模拟 int 0x10 指令的行为
; 输入：ah = 功能号, al = 字符（如果功能是 0x0E）
manual_int10:
    ; 保存参数（ax 包含功能号和字符）
    push ax
    
    ; 1. 查找中断向量表
    mov ax, 0
    mov es, ax          ; es = 0（中断向量表在段 0）
    mov bx, 0x10 * 4    ; INT 10h 向量地址 = 0x0040
    
    ; 2. 读取向量（先读取偏移地址，再读取段地址）
    mov dx, [es:bx]     ; 读取偏移地址（低 2 字节）到 dx
    mov cx, [es:bx+2]   ; 读取段地址（高 2 字节）到 cx
    
    ; 3. 恢复参数
    pop ax              ; 恢复 ax（包含功能号和字符）
    
    ; 4. 保存状态（模拟 int 指令的行为）
    pushf               ; 保存 FLAGS（模拟 int 指令）
    push cs             ; 保存当前代码段
    push .return        ; 保存返回地址
    
    ; 5. 清除 IF 标志（模拟 int 指令）
    cli                 ; 关中断（int 指令会自动清除 IF）
    
    ; 6. 准备跳转到 BIOS（将 BIOS 地址压入栈）
    push cx             ; BIOS 段地址（cx）
    push dx             ; BIOS 偏移地址（dx）
    
    ; 7. 远返回跳转到 BIOS 处理程序
    retf                ; 远返回，跳转到 BIOS
    ; 注意：retf 会从栈中弹出段地址和偏移地址，然后跳转
    ; BIOS 处理程序会使用 ax 中的参数（ah=功能号, al=字符）
    
.return:
    ; BIOS 处理程序执行 IRET 后会返回到这里
    sti                 ; 恢复中断（虽然 IRET 已经恢复了，但这里确保状态正确）
    ret                 ; 返回到调用者

; ========== 直接调用 BIOS（如果知道地址）==========
; 注意：这个方法假设 BIOS 地址，实际可能不工作
direct_bios_call:
    pushf
    push cs
    push .return
    
    ; 尝试直接调用 BIOS（地址可能因系统而异）
    ; 这里使用一个常见的 BIOS 地址（不保证在所有系统上工作）
    push 0xF000          ; BIOS 代码段（常见值）
    push 0x1234          ; 假设的处理程序偏移（实际值可能不同）
    
    pop ax               ; 这里只是演示，实际需要正确的地址
    pop ax               ; 清理栈
    
    ; 如果不知道确切地址，回退到使用 int 指令
    int 0x10
    
.return:
    ret

; ========== 辅助函数：打印字符串 ==========
; 输入：si = 字符串地址（以 0 结尾）
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

; ========== 辅助函数：换行 ==========
newline:
    push ax
    mov ah, 0x0E
    mov al, 0x0D        ; 回车
    int 0x10
    mov al, 0x0A        ; 换行
    int 0x10
    pop ax
    ret

; ========== 数据定义 ==========
msg_title:
    db "=== Manual INT Instruction Demo ===", 0x0D, 0x0A, 0

msg_method1:
    db "Method 1: Using INT instruction", 0x0D, 0x0A, 0

msg_using_int:
    db "  Displaying ABC using INT 0x10: ", 0

msg_method2:
    db "Method 2: Manual INT implementation", 0x0D, 0x0A, 0

msg_manual_impl:
    db "  Displaying XYZ using manual INT: ", 0

msg_method3:
    db "Method 3: Direct BIOS call (fallback to INT)", 0x0D, 0x0A, 0

msg_direct_call:
    db "  Displaying 123 using direct call: ", 0

msg_done:
    db 0x0D, 0x0A, "Demo completed!", 0x0D, 0x0A, 0

; 填充到 510 字节
times 510-($-$$) db 0

; 引导扇区标志
dw 0xAA55

