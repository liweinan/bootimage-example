; ============================================================================
; clock_tsr.asm - TSR 时钟演示程序
; 在屏幕右上角显示实时时钟
; 通过钩住 INT 1Ch (用户定时器中断) 实现
; ============================================================================
; 编译: nasm -f bin -o clock.com clock_tsr.asm
; 运行: 在 DOS/DOSBox 中执行 clock.com

org 100h                        ; COM 文件格式，从偏移 100h 开始

section .text

start:
    ; 显示安装消息
    mov ah, 09h
    mov dx, install_msg
    int 21h

    ; 获取并保存原 INT 1Ch 向量
    mov ax, 351Ch               ; AH=35h 获取中断向量, AL=1Ch
    int 21h
    mov [old_int1c_off], bx     ; 保存偏移
    mov [old_int1c_seg], es     ; 保存段

    ; 设置新的 INT 1Ch 处理程序
    mov ax, 251Ch               ; AH=25h 设置中断向量
    mov dx, new_int1c           ; DS:DX = 新处理程序
    int 21h

    ; 终止并驻留 (TSR)
    mov ax, 3100h               ; AH=31h 终止并驻留
    mov dx, (resident_end - start + 256 + 15) / 16  ; 驻留段落数
    int 21h

; ============================================================================
; 驻留代码段 - 这部分会留在内存中
; ============================================================================

new_int1c:
    ; 保存所有可能被修改的寄存器
    push ax
    push bx
    push cx
    push dx
    push si
    push di
    push ds
    push es

    ; 设置 DS 指向我们的数据段
    push cs
    pop ds

    ; 计数器：每 18 次中断更新一次（约1秒，因为 18.2Hz）
    inc byte [tick_count]
    cmp byte [tick_count], 18
    jb .skip_update
    mov byte [tick_count], 0

    ; 获取 BIOS 时间
    mov ah, 02h                 ; 读取 RTC 时间
    int 1Ah
    ; CH = 小时 (BCD), CL = 分钟 (BCD), DH = 秒 (BCD)

    ; 保存时间到缓冲区
    mov [bcd_hour], ch
    mov [bcd_min], cl
    mov [bcd_sec], dh

    ; 设置 ES 指向视频内存
    mov ax, 0B800h
    mov es, ax

    ; 在屏幕右上角显示时间 (第0行，第71列开始)
    ; 位置计算: row * 160 + col * 2 = 0 * 160 + 71 * 2 = 142
    mov di, 142

    ; 显示小时
    mov al, [bcd_hour]
    call display_bcd

    ; 显示冒号
    mov al, ':'
    mov ah, 0x1E                ; 黄色前景，蓝色背景
    stosw

    ; 显示分钟
    mov al, [bcd_min]
    call display_bcd

    ; 显示冒号
    mov al, ':'
    mov ah, 0x1E
    stosw

    ; 显示秒
    mov al, [bcd_sec]
    call display_bcd

.skip_update:
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
    jmp far [cs:old_int1c_off]

; ----------------------------------------------------------------------------
; display_bcd: 显示 BCD 数字 (AL = BCD 值)
; ----------------------------------------------------------------------------
display_bcd:
    push ax
    ; 高4位
    mov ah, al
    shr al, 4
    add al, '0'
    mov ah, 0x1E                ; 黄色前景，蓝色背景
    stosw
    ; 低4位
    pop ax
    and al, 0x0F
    add al, '0'
    mov ah, 0x1E
    stosw
    ret

; ============================================================================
; 驻留数据段
; ============================================================================

old_int1c_off   dw 0
old_int1c_seg   dw 0
tick_count      db 0
bcd_hour        db 0
bcd_min         db 0
bcd_sec         db 0

resident_end:                   ; 驻留部分结束标记

; ============================================================================
; 非驻留部分 - 安装后会被释放
; ============================================================================

install_msg:
    db '===================================', 13, 10
    db '  TSR Clock Demo - Now Installed!  ', 13, 10
    db '===================================', 13, 10
    db 'Look at the top-right corner of the screen.', 13, 10
    db 'The clock will update every second.', 13, 10
    db 'This TSR hooks INT 1Ch (Timer Tick).', 13, 10
    db '$'
