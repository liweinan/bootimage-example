/*
 * I-cache 测试程序 v3 - 修正 RIP-relative 寻址问题
 *
 * 策略：使用绝对地址（通过寄存器传递），避免 RIP-relative 寻址
 */

.section .data
msg_start:
    .ascii "=== I-Cache Test v3 (Fixed RIP-relative issue) ===\n"
msg_start_len = . - msg_start

msg_test1:
    .ascii "\n[Test 1] Before overwrite\n"
msg_test1_len = . - msg_test1

msg_test2:
    .ascii "\n[Test 2] After overwrite\n"
msg_test2_len = . - msg_test2

msg_counter:
    .ascii "  Counter value: "
msg_counter_len = . - msg_counter

msg_bytes_before:
    .ascii "  Code bytes before overwrite: "
msg_bytes_before_len = . - msg_bytes_before

msg_bytes_after:
    .ascii "  Code bytes after overwrite:  "
msg_bytes_after_len = . - msg_bytes_after

msg_result_original:
    .ascii "\n=== RESULT: I-cache WORKS (executed cached instructions) ===\n"
msg_result_original_len = . - msg_result_original

msg_result_modified:
    .ascii "\n=== RESULT: I-cache FAILS (executed new instructions) ===\n"
msg_result_modified_len = . - msg_result_modified

msg_result_broken:
    .ascii "\n=== RESULT: Execution broken (counter = 0) ===\n"
msg_result_broken_len = . - msg_result_broken

newline:
    .ascii "\n"
space:
    .ascii " "

.section .bss
    .lcomm counter, 8

.section .text
.globl _start

_start:
    # 打印标题
    movq $1, %rax
    movq $1, %rdi
    leaq msg_start(%rip), %rsi
    movq $msg_start_len, %rdx
    syscall

    # === Test 1: 原始代码 ===
    movq $1, %rax
    movq $1, %rdi
    leaq msg_test1(%rip), %rsi
    movq $msg_test1_len, %rdx
    syscall

    # 打印代码字节
    movq $1, %rax
    movq $1, %rdi
    leaq msg_bytes_before(%rip), %rsi
    movq $msg_bytes_before_len, %rdx
    syscall
    leaq test_code(%rip), %rdi
    call print_hex_bytes

    # 初始化 counter
    movq $0, counter(%rip)

    # 获取 counter 的绝对地址（避免 RIP-relative）
    leaq counter(%rip), %r15

    # 执行测试代码
    call run_test

    # 打印结果
    movq $1, %rax
    movq $1, %rdi
    leaq msg_counter(%rip), %rsi
    movq $msg_counter_len, %rdx
    syscall
    movq counter(%rip), %rax
    call print_number

    # === 覆盖代码 ===
    # 将 modified_test_code 复制到 test_code
    leaq test_code(%rip), %rdi
    leaq modified_test_code(%rip), %rsi
    movq $64, %rcx
    rep movsb

    # === Test 2: 覆盖后 ===
    movq $1, %rax
    movq $1, %rdi
    leaq msg_test2(%rip), %rsi
    movq $msg_test2_len, %rdx
    syscall

    # 打印代码字节
    movq $1, %rax
    movq $1, %rdi
    leaq msg_bytes_after(%rip), %rsi
    movq $msg_bytes_after_len, %rdx
    syscall
    leaq test_code(%rip), %rdi
    call print_hex_bytes

    # 重置 counter
    movq $0, counter(%rip)
    leaq counter(%rip), %r15

    # 再次执行（代码已被覆盖）
    call run_test

    # 打印结果
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
    cmpq $10, %rax           # 原始: +1 * 10 = 10
    je result_original
    cmpq $1000, %rax         # 修改: +100 * 10 = 1000
    je result_modified
    jmp result_broken

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

# 运行测试：循环10次调用 test_code
# 输入：%r15 = counter 的地址
run_test:
    pushq %rbp
    movq %rsp, %rbp

    movq $0, %r14            # 循环计数器
test_loop:
    cmpq $10, %r14
    jge test_loop_end

    call test_code           # 调用被测试的代码

    incq %r14
    jmp test_loop

test_loop_end:
    popq %rbp
    ret

# 测试代码区域（会被覆盖）
# 使用 %r15 作为 counter 地址（绝对寻址）
# 原始版本：counter += 1
test_code:
    movq (%r15), %rax        # 使用绝对地址
    incq %rax                # +1
    movq %rax, (%r15)
    ret
    .space 50                # 填充空间

# 修改版本：counter += 100
modified_test_code:
    movq (%r15), %rax        # 使用绝对地址
    addq $100, %rax          # +100
    movq %rax, (%r15)
    ret
    .space 50

# 打印16字节的十六进制
print_hex_bytes:
    pushq %rbp
    movq %rsp, %rbp
    pushq %r12
    pushq %r13

    movq %rdi, %r12
    movq $16, %r13

print_hex_loop:
    testq %r13, %r13
    jz print_hex_done

    movzbl (%r12), %eax
    pushq %r13
    pushq %r12
    call print_hex_byte
    popq %r12
    popq %r13

    movq $1, %rax
    movq $1, %rdi
    leaq space(%rip), %rsi
    movq $1, %rdx
    syscall

    incq %r12
    decq %r13
    jmp print_hex_loop

print_hex_done:
    movq $1, %rax
    movq $1, %rdi
    leaq newline(%rip), %rsi
    movq $1, %rdx
    syscall

    popq %r13
    popq %r12
    popq %rbp
    ret

# 打印一个字节的十六进制
print_hex_byte:
    pushq %rbp
    movq %rsp, %rbp
    subq $16, %rsp

    movl %eax, %r10d

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
