# 最小引导扇区程序示例

引导扇区（Boot Sector）是存储在磁盘第一个扇区（512 字节）的特殊程序。BIOS 完成初始化后，会调用 INT 19h 服务加载并执行引导扇区程序。

> **相关文档**：
> - 关于 BIOS 如何通过 `call_boot_entry()` 函数将驱动器号传递到 DL 寄存器，请参见 [BOOT_FLOW.md - BIOS 如何传递驱动器号给引导扇区程序](BOOT_FLOW.md#bios-如何传递驱动器号给引导扇区程序)
> - 关于 GRUB 引导扇区代码的实现和如何使用 DL 寄存器，请参见 [BOOT_FLOW.md - 阶段 2：GRUB 引导扇区加载 GRUB Core](BOOT_FLOW.md#阶段-2grub-引导扇区加载-grub-core)
> - 关于最小引导扇区程序（`boot.asm`）与 GRUB 引导扇区代码（`boot.S`）的详细对比分析，请参见 [boot.asm 与 GRUB boot.S 对比分析](BOOTSECTOR_COMPARISON.md)

## 最小引导扇区程序代码

```asm
; boot.asm - 最小引导扇区程序
org 0x7C00
bits 16

start:
    mov ax, 0x0003      ; 设置80x25文本模式
    int 0x10

    mov si, msg
    mov ah, 0x0E        ; BIOS 视频服务：TTY 模式显示字符

.print:
    lodsb               ; 从字符串加载一个字节到 al
    test al, al         ; 检查是否为字符串结束符
    jz .halt
    int 0x10            ; 显示字符
    jmp .print

.halt:
    jmp $               ; 无限循环

msg db "Hello from Boot Sector!", 0
times 510-($-$$) db 0   ; 填充到 510 字节
dw 0xAA55               ; 引导扇区标志
```

> **详细说明**：关于 `boot.asm` 的完整代码注释和逐行解释，请参见 [技术细节说明 - Note 5: boot.asm 完整代码注释](BOOT_FLOW_NOTES.md#note-5-bootasm-完整代码注释)。

## 关键内存地址和中断服务

| 地址/中断 | 说明 | 用途 |
|-----------|------|------|
| `0x7C00` | 引导扇区加载地址 | BIOS 将引导扇区加载到此地址 |
| `0x07C0:0x0000` | 引导扇区段:偏移格式 | 等价于物理地址 0x7C00 |
| `INT 10h` | BIOS 视频服务 | 设置显示模式、显示字符 |
| `INT 13h` | BIOS 磁盘服务 | 读取/写入磁盘扇区 |
| `INT 19h` | BIOS 引导加载服务 | 加载并执行引导扇区 |

> **详细说明**：关于在 QEMU 中测试引导扇区的方法，请参见 [技术细节说明 - Note 6: 在 QEMU 中测试引导扇区](BOOT_FLOW_NOTES.md#note-6-在-qemu-中测试引导扇区)。
