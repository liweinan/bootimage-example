/*
 * I-cache 测试程序 v2 - 增强调试版本
 * 添加详细的执行跟踪，查看覆盖操作的影响
 */

.section .data
msg_start:
    .ascii "=== I-Cache Test v2 ===\n"
msg_start_len = . - msg_start

msg_test1:
    .ascii "\n[Test 1] Before overwrite - calling original code\n"
msg_test1_len = . - msg_test1

msg_test2:
    .ascii "\n[Test 2] After overwrite - calling modified memory\n"
msg_test2_len = . - msg_test2

msg_call:
    .ascii "  Calling increment function (iteration "
msg_call_len = . - msg_call

msg_counter:
    .ascii "  Counter value: "
msg_counter_len = . - msg_counter

msg_overwrite_start:
    .ascii "\n[Overwrite] Copying modified code over original...\n"
msg_overwrite_len = . - msg_overwrite_start

msg_overwrite_done:
    .ascii "[Overwrite] Done. Verifying first 16 bytes:\n"
msg_overwrite_done_len = . - msg_overwrite_done

msg_original_bytes:
    .ascii "  Original bytes: "
msg_original_bytes_len = . - msg_original_bytes

msg_modified_bytes:
    .ascii "  Modified bytes: "
msg_modified_bytes_len = . - msg_modified_bytes

msg_memory_bytes:
    .ascii "  Memory now:     "
msg_memory_bytes_len = . - msg_memory_bytes

msg_result_original:
    .ascii "\n=== RESULT: I-cache is working (original code executed) ===\n"
msg_result_original_len = . - msg_result_original

msg_result_modified:
    .ascii "\n=== RESULT: I-cache NOT working (modified code executed) ===\n"
msg_result_modified_len = . - msg_result_modified

msg_result_broken:
    .ascii "\n=== RESULT: Code execution broken (counter = 0) ===\n"
msg_result_broken_len = . - msg_result_broken

newline:
    .ascii "\n"

.section .bss
    .lcomm counter, 8
    .lcomm iteration, 8
    .lcomm original_bytes, 16
    .lcomm modified_bytes, 16

.section .text
.globl _start

_start:
    # 打印标题
    movq $1, %rax
    movq $1, %rdi
    leaq msg_start(%rip), %rsi
    movq $msg_start_len, %rdx
    syscall

    # === 保存原始代码的前16字节 ===
    leaq increment_and_return(%rip), %rsi
    leaq original_bytes(%rip), %rdi
    movq $16, %rcx
    rep movsb

    # === 保存修改代码的前16字节 ===
    leaq modified_increment_and_return(%rip), %rsi
    leaq modified_bytes(%rip), %rdi
    movq $16, %rcx
    rep movsb

    # === Test 1: 原始代码 ===
    movq $1, %rax
    movq $1, %rdi
    leaq msg_test1(%rip), %rsi
    movq $msg_test1_len, %rdx
    syscall

    movq $0, counter(%rip)
    call test_function_verbose

    # 打印 Test 1 结果
    movq $1, %rax
    movq $1, %rdi
    leaq msg_counter(%rip), %rsi
    movq $msg_counter_len, %rdx
    syscall
    movq counter(%rip), %rax
    call print_number

    # === 覆盖操作 ===
    movq $1, %rax
    movq $1, %rdi
    leaq msg_overwrite_start(%rip), %rsi
    movq $msg_overwrite_len, %rdx
    syscall

    # 执行覆盖
    leaq increment_and_return(%rip), %rdi
    leaq modified_increment_and_return(%rip), %rsi
    movq $64, %rcx
    rep movsb

    # 验证覆盖结果
    movq $1, %rax
    movq $1, %rdi
    leaq msg_overwrite_done(%rip), %rsi
    movq $msg_overwrite_done_len, %rdx
    syscall

    # 打印原始字节
    movq $1, %rax
    movq $1, %rdi
    leaq msg_original_bytes(%rip), %rsi
    movq $msg_original_bytes_len, %rdx
    syscall
    leaq original_bytes(%rip), %rdi
    call print_hex_bytes

    # 打印修改字节
    movq $1, %rax
    movq $1, %rdi
    leaq msg_modified_bytes(%rip), %rsi
    movq $msg_modified_bytes_len, %rdx
    syscall
    leaq modified_bytes(%rip), %rdi
    call print_hex_bytes

    # 打印当前内存字节
    movq $1, %rax
    movq $1, %rdi
    leaq msg_memory_bytes(%rip), %rsi
    movq $msg_memory_bytes_len, %rdx
    syscall
    leaq increment_and_return(%rip), %rdi
    call print_hex_bytes

    # === Test 2: 覆盖后的代码 ===
    movq $1, %rax
    movq $1, %rdi
    leaq msg_test2(%rip), %rsi
    movq $msg_test2_len, %rdx
    syscall

    movq $0, counter(%rip)
    call test_function_verbose

    # 打印 Test 2 结果
    movq $1, %rax
    movq $1, %rdi
    leaq msg_counter(%rip), %rsi
    movq $msg_counter_len, %rdx
    syscall
    movq counter(%rip), %rax
    call print_number

    # === 判断结果 ===
    movq counter(%rip), %rax
    testq %rax, %rax
    jz result_broken
    cmpq $10, %rax
    je result_original
    jmp result_modified

result_broken:
    movq $1, %rax
    movq $1, %rdi
    leaq msg_result_broken(%rip), %rsi
    movq $msg_result_broken_len, %rdx
    syscall
    jmp exit_program

result_original:
    movq $1, %rax
    movq $1, %rdi
    leaq msg_result_original(%rip), %rsi
    movq $msg_result_original_len, %rdx
    syscall
    jmp exit_program

result_modified:
    movq $1, %rax
    movq $1, %rdi
    leaq msg_result_modified(%rip), %rsi
    movq $msg_result_modified_len, %rdx
    syscall

exit_program:
    movq $60, %rax
    xorq %rdi, %rdi
    syscall

# 带调试输出的测试函数
test_function_verbose:
    pushq %rbp
    movq %rsp, %rbp

    movq $0, iteration(%rip)
loop_verbose:
    cmpq $3, iteration(%rip)     # 只循环3次，减少输出
    jge loop_verbose_end

    # 打印当前迭代
    movq $1, %rax
    movq $1, %rdi
    leaq msg_call(%rip), %rsi
    movq $msg_call_len, %rdx
    syscall

    movq iteration(%rip), %rax
    call print_number

    # 调用增量函数
    call increment_and_return

    # 打印当前counter值
    movq $1, %rax
    movq $1, %rdi
    leaq msg_counter(%rip), %rsi
    movq $msg_counter_len, %rdx
    syscall
    movq counter(%rip), %rax
    call print_number

    incq iteration(%rip)
    jmp loop_verbose

loop_verbose_end:
    popq %rbp
    ret

# 原始版本：counter += 1
increment_and_return:
    movq counter(%rip), %rax
    incq %rax
    movq %rax, counter(%rip)
    ret
    .space 50

# 修改版本：counter += 100
modified_increment_and_return:
    movq counter(%rip), %rax
    addq $100, %rax
    movq %rax, counter(%rip)
    ret
    .space 50

# 打印16个字节的十六进制
print_hex_bytes:
    pushq %rbp
    movq %rsp, %rbp
    pushq %r12
    pushq %r13

    movq %rdi, %r12              # 保存地址
    movq $16, %r13               # 计数器

print_hex_loop:
    testq %r13, %r13
    jz print_hex_done

    movzbl (%r12), %eax          # 读取一个字节
    pushq %r13
    pushq %r12
    call print_hex_byte
    popq %r12
    popq %r13

    # 打印空格
    movq $1, %rax
    movq $1, %rdi
    leaq space(%rip), %rsi
    movq $1, %rdx
    syscall

    incq %r12
    decq %r13
    jmp print_hex_loop

print_hex_done:
    # 打印换行
    movq $1, %rax
    movq $1, %rdi
    leaq newline(%rip), %rsi
    movq $1, %rdx
    syscall

    popq %r13
    popq %r12
    popq %rbp
    ret

space:
    .ascii " "

# 打印一个字节的十六进制 (输入: %eax = byte)
print_hex_byte:
    pushq %rbp
    movq %rsp, %rbp
    subq $16, %rsp

    movl %eax, %r10d

    # 高4位
    movl %r10d, %eax
    shrl $4, %eax
    andl $0xF, %eax
    cmpb $10, %al
    jl hex_digit1
    addb $('a' - 10), %al
    jmp hex_store1
hex_digit1:
    addb $'0', %al
hex_store1:
    movb %al, (%rsp)

    # 低4位
    movl %r10d, %eax
    andl $0xF, %eax
    cmpb $10, %al
    jl hex_digit2
    addb $('a' - 10), %al
    jmp hex_store2
hex_digit2:
    addb $'0', %al
hex_store2:
    movb %al, 1(%rsp)

    # 打印
    movq $1, %rax
    movq $1, %rdi
    movq %rsp, %rsi
    movq $2, %rdx
    syscall

    addq $16, %rsp
    popq %rbp
    ret

# 打印数字
print_number:
    pushq %rbp
    movq %rsp, %rbp
    subq $32, %rsp

    movq %rax, %r10
    leaq 31(%rsp), %rsi
    movb $0, (%rsi)
    decq %rsi
    movb $10, (%rsi)
    decq %rsi

    movq $10, %rcx

convert_loop:
    xorq %rdx, %rdx
    movq %r10, %rax
    divq %rcx
    movq %rax, %r10

    addb $'0', %dl
    movb %dl, (%rsi)
    decq %rsi

    testq %r10, %r10
    jnz convert_loop

    incq %rsi

    leaq 32(%rsp), %rax
    subq %rsi, %rax
    movq %rax, %rdx

    movq $1, %rax
    movq $1, %rdi
    syscall

    addq $32, %rsp
    popq %rbp
    ret
