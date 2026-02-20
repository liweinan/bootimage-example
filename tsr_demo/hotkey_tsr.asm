; ============================================================================
; hotkey_tsr.asm - TSR 热键演示程序
; 按 F12 键时在屏幕上显示消息
; 通过钩住 INT 09h (键盘中断) 实现
; ============================================================================
; 编译: nasm -f bin -o hotkey.com hotkey_tsr.asm
; 运行: 在 DOS/DOSBox 中执行 hotkey.com

org 100h

section .text

start:
    ; 显示安装消息
    mov ah, 09h
    mov dx, install_msg
    int 21h

    ; 获取并保存原 INT 09h 向量
    mov ax, 3509h               ; AH=35h 获取中断向量, AL=09h
    int 21h
    mov [old_int09_off], bx
    mov [old_int09_seg], es

    ; 设置新的 INT 09h 处理程序
    mov ax, 2509h               ; AH=25h 设置中断向量
    mov dx, new_int09
    int 21h

    ; 终止并驻留 (TSR)
    mov ax, 3100h
    mov dx, (resident_end - start + 256 + 15) / 16
    int 21h

; ============================================================================
; 驻留代码段
; ============================================================================

new_int09:
    push ax
    push bx
    push cx
    push dx
    push si
    push di
    push ds
    push es

    ; 读取键盘扫描码
    in al, 60h

    ; 检查是否是 ESC 键 (扫描码 01h)
    cmp al, 01h
    jne .chain

    ; F12 被按下！显示消息框
    push cs
    pop ds

    ; 保存当前光标位置
    mov ah, 03h
    mov bh, 0
    int 10h
    push dx                     ; 保存光标位置

    ; 设置 ES 指向视频内存
    mov ax, 0B800h
    mov es, ax

    ; 在屏幕中央绘制消息框 (第10行开始)
    ; 位置: 10 * 160 + 25 * 2 = 1650
    mov di, 1650

    ; 绘制顶部边框
    mov cx, 30
    mov ax, 0x4FDB              ; 白色前景红色背景，块字符
.top_border:
    stosw
    loop .top_border

    ; 换行
    add di, 160 - 60

    ; 绘制消息行
    mov si, popup_msg
    mov ah, 0x4F                ; 白色前景红色背景
.msg_loop:
    lodsb
    cmp al, 0
    je .msg_done
    stosw
    jmp .msg_loop
.msg_done:

    ; 换行
    add di, 160 - 60

    ; 绘制底部边框
    mov cx, 30
    mov ax, 0x4FDB
.bottom_border:
    stosw
    loop .bottom_border

    ; 恢复光标位置
    pop dx
    mov ah, 02h
    mov bh, 0
    int 10h

    ; 增加计数器
    inc byte [cs:hotkey_count]

.chain:
    ; 恢复寄存器
    pop es
    pop ds
    pop di
    pop si
    pop dx
    pop cx
    pop bx
    pop ax

    ; 链式调用原中断处理程序
    jmp far [cs:old_int09_off]

; ============================================================================
; 驻留数据段
; ============================================================================

old_int09_off   dw 0
old_int09_seg   dw 0
hotkey_count    db 0

popup_msg:
    db '  ESC Hotkey Activated!   ', 0

resident_end:

; ============================================================================
; 非驻留部分
; ============================================================================

install_msg:
    db '=====================================', 13, 10
    db '  TSR Hotkey Demo - Now Installed!   ', 13, 10
    db '=====================================', 13, 10
    db 'Press ESC to see the popup message.', 13, 10
    db 'This TSR hooks INT 09h (Keyboard).', 13, 10
    db '$'
