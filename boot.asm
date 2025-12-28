; boot.asm - 最小引导扇区程序
org 0x7C00
bits 16

start:
    mov ax, 0x0003      ; 设置80x25文本模式
    int 0x10
    
    mov si, msg
    mov ah, 0x0E
.print:
    lodsb
    test al, al
    jz .halt
    int 0x10
    jmp .print

.halt:
    jmp $

msg db "Hello from Boot Sector!", 0

times 510-($-$$) db 0
dw 0xAA55          ; 引导扇区标志

