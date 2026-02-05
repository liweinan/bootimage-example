/*
 * 测试程序：验证 CPU 指令缓存是否允许代码在被覆盖后继续执行
 *
 * 测试场景：
 * 1. 函数 test_function 包含一系列指令
 * 2. 执行过程中，代码会覆盖自己的后半部分
 * 3. 如果依赖 I-cache：即使内存被覆盖，仍执行原始指令
 * 4. 如果不依赖 I-cache：会执行新指令或崩溃
 */

.section .data
msg_start:
    .ascii "Starting test: executing code that will be overwritten\n"
msg_start_len = . - msg_start

msg_before_overwrite:
    .ascii "Before overwrite: counter = "
msg_before_len = . - msg_before_overwrite

msg_after_overwrite:
    .ascii "\nAfter overwrite: counter = "
msg_after_len = . - msg_after_overwrite

msg_original:
    .ascii "\nOriginal code executed! (I-cache working)\n"
msg_original_len = . - msg_original

msg_modified:
    .ascii "\nModified code executed! (I-cache NOT working)\n"
msg_modified_len = . - msg_modified

newline:
    .ascii "\n"

.section .bss
    .lcomm counter, 8

.section .text
.globl _start

_start:
    # 打印开始消息
    movq $1, %rax                # sys_write
    movq $1, %rdi                # stdout
    leaq msg_start(%rip), %rsi
    movq $msg_start_len, %rdx
    syscall

    # 获取 test_function 的地址（需要可写权限）
    leaq test_function(%rip), %r12

    # 初始化计数器
    movq $0, counter(%rip)

    # 调用测试函数（第一次，未覆盖）
    call test_function

    # 打印 "Before overwrite: counter = "
    movq $1, %rax
    movq $1, %rdi
    leaq msg_before_overwrite(%rip), %rsi
    movq $msg_before_len, %rdx
    syscall

    # 打印计数器值
    movq counter(%rip), %rax
    call print_number

    # === 关键测试：覆盖 test_function 的后半部分 ===
    # 将 increment_and_return 部分覆盖为 modified_increment_and_return
    leaq increment_and_return(%rip), %rdi      # 目标地址
    leaq modified_increment_and_return(%rip), %rsi  # 源地址
    movq $64, %rcx                              # 覆盖64字节
    rep movsb                                   # 执行覆盖

    # 重置计数器
    movq $0, counter(%rip)

    # 再次调用 test_function（代码已被覆盖）
    call test_function

    # 打印 "After overwrite: counter = "
    movq $1, %rax
    movq $1, %rdi
    leaq msg_after_overwrite(%rip), %rsi
    movq $msg_after_len, %rdx
    syscall

    # 打印计数器值
    movq counter(%rip), %rax
    call print_number

    # 打印结果消息
    movq counter(%rip), %rax
    cmpq $10, %rax               # 原始代码: counter = 10
    je original_executed

modified_executed:
    movq $1, %rax
    movq $1, %rdi
    leaq msg_modified(%rip), %rsi
    movq $msg_modified_len, %rdx
    syscall
    jmp exit_program

original_executed:
    movq $1, %rax
    movq $1, %rdi
    leaq msg_original(%rip), %rsi
    movq $msg_original_len, %rdx
    syscall

exit_program:
    # 退出程序
    movq $60, %rax               # sys_exit
    xorq %rdi, %rdi              # exit code 0
    syscall

# 测试函数：会调用后面的代码段
test_function:
    pushq %rbp
    movq %rsp, %rbp

    # 循环10次，每次调用 increment_and_return
    movq $0, %r13                # 循环计数器
loop:
    cmpq $10, %r13
    jge loop_end

    call increment_and_return    # 这部分代码会被覆盖！

    incq %r13
    jmp loop

loop_end:
    popq %rbp
    ret

# 原始版本：递增计数器（每次+1）
increment_and_return:
    movq counter(%rip), %rax
    incq %rax                    # +1
    movq %rax, counter(%rip)
    ret
    .space 50                    # 填充空间，确保有足够空间被覆盖

# 修改后的版本：递增计数器（每次+100）
modified_increment_and_return:
    movq counter(%rip), %rax
    addq $100, %rax              # +100 (不同的行为)
    movq %rax, counter(%rip)
    ret
    .space 50

# 辅助函数：打印数字
print_number:
    pushq %rbp
    movq %rsp, %rbp
    subq $32, %rsp               # 栈空间存储数字字符串

    movq %rax, %r10              # 保存数字
    leaq 31(%rsp), %rsi          # 字符串末尾
    movb $0, (%rsi)              # null terminator
    decq %rsi
    movb $10, (%rsi)             # newline
    decq %rsi

    movq $10, %rcx               # 除数

convert_loop:
    xorq %rdx, %rdx
    movq %r10, %rax
    divq %rcx                    # rax = rax / 10, rdx = rax % 10
    movq %rax, %r10

    addb $'0', %dl               # 转换为ASCII
    movb %dl, (%rsi)
    decq %rsi

    testq %r10, %r10
    jnz convert_loop

    incq %rsi                    # 调整到第一个数字

    # 计算长度
    leaq 32(%rsp), %rax
    subq %rsi, %rax
    movq %rax, %rdx

    # 打印
    movq $1, %rax                # sys_write
    movq $1, %rdi                # stdout
    syscall

    addq $32, %rsp
    popq %rbp
    ret
