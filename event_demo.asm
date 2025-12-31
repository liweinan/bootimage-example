; event_demo.asm - 事件机制演示程序
; 演示现代操作系统中的事件订阅和触发机制
; 在引导扇区环境中实现简单的事件系统
;
; 本程序展示了事件驱动编程的核心概念：
; 1. 事件订阅：将事件处理器函数地址保存到数组中
; 2. 事件触发：遍历数组，依次调用所有已注册的处理器
; 3. 事件广播：一个事件可以触发多个处理器的执行
;
; 这种机制是现代操作系统和应用程序中事件处理的基础，
; 类似于 JavaScript 的 addEventListener() 或 Node.js 的 EventEmitter

org 0x7C00
; org 指令：设置程序的起始地址为 0x7C00
; BIOS 会将引导扇区加载到内存地址 0x7C00 处执行
; 这样后续的标签和变量地址才能正确计算

bits 16
; bits 指令：指定汇编器生成 16 位代码
; 引导扇区程序运行在实模式下，使用 16 位寄存器

start:
    ; ========== 程序入口点 ==========
    ; BIOS 会从引导扇区的第一个字节开始执行，所以这里就是程序的开始
    
    ; 初始化显示
    mov ax, 0x0003      ; 设置 80x25 文本模式
    ; ax 是累加寄存器（16位），0x0003 表示设置显示模式为 80x25 文本模式
    ; 这是 BIOS 视频服务（INT 0x10）的功能号
    int 0x10
    ; int 指令：调用 BIOS 中断 0x10（视频服务中断）
    ; 配合 ax=0x0003，这个中断调用会设置显示模式为 80 列 x 25 行的文本模式
    ; 清空屏幕并准备显示文本
    
    ; 显示标题
    mov si, msg_title
    ; mov 指令：将 msg_title 标签的地址移动到寄存器 si
    ; si 是源索引寄存器（Source Index），用于字符串操作
    ; msg_title 是后面定义的消息字符串的地址
    call print_string
    ; call 指令：调用 print_string 函数
    ; 函数会从 si 指向的地址读取字符串并显示
    
    ; ========== 初始化事件系统 ==========
    ; 在开始使用事件系统之前，需要初始化相关数据结构
    mov si, msg_init
    call print_string
    
    ; 初始化事件处理器计数
    mov word [handler_count], 0
    ; 将 handler_count 变量设置为 0
    ; handler_count 用于跟踪当前已注册的事件处理器数量
    ; 这个值会在每次订阅事件时递增，在取消订阅时递减
    
    ; ========== 订阅事件处理器 ==========
    ; 事件订阅：将事件处理器函数的地址注册到事件系统中
    ; 当事件被触发时，所有已注册的处理器都会被调用
    mov si, msg_subscribe
    call print_string
    
    ; 订阅处理器 1
    mov ax, handler1
    ; 将 handler1 函数的地址加载到 ax 寄存器
    ; handler1 是一个事件处理器函数，当事件触发时会被调用
    call subscribe_event
    ; 调用 subscribe_event 函数，将 handler1 的地址添加到处理器数组
    ; subscribe_event 函数会：
    ;   1. 检查数组是否已满（最多 10 个处理器）
    ;   2. 计算数组中的插入位置
    ;   3. 将处理器地址保存到数组中
    ;   4. 增加处理器计数
    mov si, msg_handler1_registered
    call print_string
    ; 显示注册成功的消息
    
    ; 订阅处理器 2
    mov ax, handler2
    ; 将 handler2 函数的地址加载到 ax 寄存器
    call subscribe_event
    ; 将 handler2 添加到处理器数组
    mov si, msg_handler2_registered
    call print_string
    
    ; 订阅处理器 3
    mov ax, handler3
    ; 将 handler3 函数的地址加载到 ax 寄存器
    call subscribe_event
    ; 将 handler3 添加到处理器数组
    ; 现在数组中有 3 个处理器：handler1, handler2, handler3
    mov si, msg_handler3_registered
    call print_string
    
    call newline
    
    ; ========== 触发事件 ==========
    ; 事件触发：调用所有已注册的事件处理器
    ; 这是事件系统的核心功能，类似于 JavaScript 的 emit() 或 dispatchEvent()
    mov si, msg_trigger
    call print_string
    
    ; 触发事件（会调用所有已注册的处理器）
    call trigger_event
    ; trigger_event 函数会：
    ;   1. 获取当前已注册的处理器数量
    ;   2. 遍历处理器数组
    ;   3. 依次调用每个处理器函数
    ;   4. 所有处理器按注册顺序执行
    ; 在这个例子中，会依次调用：handler1 -> handler2 -> handler3
    
    call newline
    ; 换行，使输出更清晰
    
    ; ========== 再次触发事件 ==========
    ; 演示可以多次触发同一事件
    ; 每次触发都会调用所有已注册的处理器
    mov si, msg_trigger_again
    call print_string
    
    call trigger_event
    ; 再次触发事件，所有处理器会再次执行
    ; 这展示了事件可以多次触发，每次都会通知所有监听器
    
    call newline
    
    ; 显示完成信息
    mov si, msg_done
    call print_string
    
    jmp $

; ========== 事件订阅函数 ==========
; 功能：将事件处理器添加到处理器数组
; 输入：ax = 处理器函数地址（16位偏移地址）
; 输出：无
; 
; 工作原理：
; 1. 检查数组是否已满（最多 MAX_HANDLERS 个处理器）
; 2. 计算新处理器在数组中的位置（索引 = handler_count）
; 3. 将处理器地址保存到数组的相应位置
; 4. 增加处理器计数
;
; 数组结构：
; - event_handlers 是一个固定大小的数组，最多存储 MAX_HANDLERS 个地址
; - 每个地址占 2 字节（16位模式）
; - 数组按顺序存储，handler_count 指向下一个可用位置
;
; 示例：
;   如果 handler_count = 2，表示已有 2 个处理器
;   新处理器将存储在 event_handlers[2] 位置
subscribe_event:
    ; ========== 保存寄存器 ==========
    ; 保存所有会被修改的寄存器，确保函数不会影响调用者
    push bx              ; 保存 bx（用于存储处理器数量）
    push cx              ; 保存 cx（用于计算数组索引）
    push si              ; 保存 si（用于数组指针）
    
    ; ========== 获取当前处理器数量 ==========
    mov bx, [handler_count]
    ; 从内存读取 handler_count 变量的值
    ; bx 现在包含当前已注册的处理器数量（0 到 MAX_HANDLERS-1）
    
    ; ========== 检查数组是否已满 ==========
    cmp bx, MAX_HANDLERS
    ; 比较当前数量与最大数量（MAX_HANDLERS = 10）
    jge .full
    ; 如果 bx >= MAX_HANDLERS，跳转到 .full 标签
    ; 这样可以防止数组溢出，保护系统安全
    
    ; ========== 计算数组索引位置 ==========
    mov cx, bx
    ; 将处理器数量复制到 cx
    shl cx, 1
    ; 左移 1 位，相当于乘以 2
    ; 因为每个地址占 2 字节（16位模式），所以索引需要乘以 2
    ; 例如：索引 0 -> 偏移 0，索引 1 -> 偏移 2，索引 2 -> 偏移 4
    
    ; ========== 保存处理器地址到数组 ==========
    mov si, event_handlers
    ; 将数组起始地址加载到 si（Source Index 寄存器）
    ; event_handlers 是数组的起始地址
    add si, cx
    ; 将计算出的偏移量加到数组起始地址
    ; si 现在指向数组中要插入新处理器的位置
    ; si = event_handlers + (handler_count * 2)
    mov [si], ax
    ; 将处理器地址（ax）保存到数组的相应位置
    ; [si] 表示 si 指向的内存地址
    ; 这样就将新处理器的地址存储到数组中了
    
    ; ========== 增加处理器计数 ==========
    inc word [handler_count]
    ; 将 handler_count 变量加 1
    ; word 关键字指定操作 16 位数据
    ; 现在数组中有 handler_count 个处理器（包括刚添加的这个）
    
.full:
    ; ========== 恢复寄存器并返回 ==========
    ; 如果数组已满，直接跳转到这里
    ; 如果成功添加，也会执行到这里
    pop si               ; 恢复 si
    pop cx               ; 恢复 cx
    pop bx               ; 恢复 bx
    ; 注意：恢复顺序与保存顺序相反（栈是后进先出）
    ret
    ; ret 指令：从函数返回
    ; 会将栈顶的返回地址弹出到 IP（指令指针），继续执行调用者

; ========== 事件触发函数 ==========
; 功能：调用所有已注册的事件处理器
; 输入：无
; 输出：无
;
; 工作原理：
; 1. 获取当前已注册的处理器数量
; 2. 遍历处理器数组，从索引 0 开始
; 3. 依次调用每个处理器函数
; 4. 所有处理器按注册顺序执行（FIFO：先进先出）
;
; 执行流程：
;   handler_count = 3 时：
;     1. 调用 event_handlers[0] -> handler1
;     2. 调用 event_handlers[2] -> handler2
;     3. 调用 event_handlers[4] -> handler3
;
; 注意事项：
; - 处理器函数必须自己保存和恢复它使用的寄存器
; - 如果某个处理器修改了全局状态，可能影响后续处理器
; - 处理器按注册顺序执行，不能保证执行时间
trigger_event:
    ; ========== 保存寄存器 ==========
    ; 保存所有会被修改的寄存器，确保函数不会影响调用者
    push ax              ; 保存 ax（可能被处理器使用）
    push bx              ; 保存 bx（用于存储处理器数量）
    push cx              ; 保存 cx（用于循环计数器）
    push si              ; 保存 si（用于数组指针）
    push dx              ; 保存 dx（用于存储处理器地址）
    
    ; ========== 获取处理器数量 ==========
    mov bx, [handler_count]
    ; 从内存读取 handler_count 变量的值
    ; bx 现在包含当前已注册的处理器数量
    
    ; ========== 检查是否有处理器 ==========
    cmp bx, 0
    ; 比较处理器数量是否为 0
    je .done
    ; 如果 bx == 0，跳转到 .done 标签（没有处理器，直接返回）
    ; 这样可以避免不必要的循环，提高效率
    
    ; ========== 初始化循环 ==========
    mov cx, 0
    ; 将循环计数器初始化为 0
    ; cx 用于跟踪当前处理的处理器索引（0 到 handler_count-1）
    mov si, event_handlers
    ; 将数组起始地址加载到 si
    ; si 现在指向数组的第一个元素（event_handlers[0]）
    
.loop:
    ; ========== 循环开始 ==========
    ; 这个循环会遍历数组中的所有处理器并依次调用它们
    
    ; 检查是否处理完所有处理器
    cmp cx, bx
    ; 比较当前索引（cx）与处理器数量（bx）
    jge .done
    ; 如果 cx >= bx，表示已经处理完所有处理器，跳转到 .done
    ; jge 表示 "jump if greater or equal"（大于等于时跳转）
    
    ; ========== 获取处理器地址 ==========
    mov dx, [si]
    ; 从数组读取处理器地址到 dx 寄存器
    ; [si] 表示 si 指向的内存地址中的值
    ; 例如：如果 si 指向 event_handlers[0]，则 dx = handler1 的地址
    
    ; ========== 调用处理器函数 ==========
    ; 注意：处理器函数会自己保存和恢复它使用的寄存器
    ; 这是函数调用约定的一部分，确保处理器不会破坏调用者的状态
    call dx
    ; call 指令：调用 dx 中存储的地址指向的函数
    ; 执行流程：
    ;   1. 将下一条指令的地址（call 后的地址）压入栈
    ;   2. 跳转到 dx 指向的地址（处理器函数）
    ;   3. 处理器函数执行完毕后，使用 ret 指令返回
    ;   4. ret 指令从栈中弹出返回地址，继续执行 call 后的指令
    ; 这样处理器函数就可以正常执行并返回到这里
    
    ; ========== 移动到下一个处理器 ==========
    add si, 2
    ; 将数组指针向前移动 2 字节
    ; 因为每个地址占 2 字节（16位模式），所以每次移动 2 字节
    ; si 现在指向数组中的下一个元素
    inc cx
    ; 将循环计数器加 1
    ; cx 现在表示已处理的处理器数量
    jmp .loop
    ; 无条件跳转回 .loop 标签，继续处理下一个处理器
    ; 这形成了一个循环，直到所有处理器都被调用
    
.done:
    ; ========== 恢复寄存器并返回 ==========
    ; 当所有处理器都被调用后，或者没有处理器时，执行这里
    pop dx               ; 恢复 dx（注意：恢复顺序与保存顺序相反）
    pop si               ; 恢复 si
    pop cx               ; 恢复 cx
    pop bx               ; 恢复 bx
    pop ax               ; 恢复 ax
    ; 所有寄存器都已恢复到函数调用前的状态
    ret
    ; ret 指令：从函数返回
    ; 会将栈顶的返回地址弹出到 IP（指令指针），继续执行调用者

; ========== 事件处理器示例 ==========
; 事件处理器是用户定义的函数，当事件被触发时会被调用
; 每个处理器可以执行任何需要的操作
;
; 处理器函数约定：
; - 必须保存和恢复所有使用的寄存器（除了返回值寄存器）
; - 使用 ret 指令返回
; - 可以调用其他函数（如 print_string）
; - 可以访问全局变量和字符串
;
; 在这个示例中，每个处理器只是显示一条消息
; 在实际应用中，处理器可以执行更复杂的操作：
; - 更新数据结构
; - 发送网络请求
; - 更新用户界面
; - 记录日志
; - 等等

; 处理器 1：显示消息 1
; 这是第一个注册的处理器，会第一个被执行
handler1:
    ; ========== 保存寄存器 ==========
    push ax              ; 保存 ax（print_string 会使用 ax）
    push si              ; 保存 si（print_string 会使用 si）
    ; 注意：必须保存所有会被修改的寄存器
    ; 这样可以确保处理器不会影响调用者（trigger_event）的状态
    
    ; ========== 处理器逻辑 ==========
    mov si, msg_handler1_executed
    ; 将消息字符串的地址加载到 si
    ; msg_handler1_executed 是一个以 0 结尾的字符串
    call print_string
    ; 调用 print_string 函数显示消息
    ; print_string 会从 si 指向的地址读取字符串并显示
    
    ; ========== 恢复寄存器并返回 ==========
    pop si               ; 恢复 si（注意：恢复顺序与保存顺序相反）
    pop ax               ; 恢复 ax
    ret
    ; ret 指令：从函数返回
    ; 返回到 trigger_event 函数中的 call dx 指令之后

; 处理器 2：显示消息 2
; 这是第二个注册的处理器，会在 handler1 之后执行
handler2:
    push ax              ; 保存 ax
    push si              ; 保存 si
    
    mov si, msg_handler2_executed
    ; 将消息字符串的地址加载到 si
    call print_string
    ; 显示处理器 2 的执行消息
    
    pop si               ; 恢复 si
    pop ax               ; 恢复 ax
    ret
    ; 返回到 trigger_event 函数

; 处理器 3：显示消息 3
; 这是第三个注册的处理器，会在 handler2 之后执行
handler3:
    push ax              ; 保存 ax
    push si              ; 保存 si
    
    mov si, msg_handler3_executed
    ; 将消息字符串的地址加载到 si
    call print_string
    ; 显示处理器 3 的执行消息
    
    pop si               ; 恢复 si
    pop ax               ; 恢复 ax
    ret
    ; 返回到 trigger_event 函数
    ; 当所有处理器都执行完毕后，trigger_event 函数会返回

; ========== 辅助函数 ==========
; 这些函数提供常用的功能，可以被主程序和事件处理器调用

; 打印字符串
; 功能：在屏幕上显示一个以 0 结尾的字符串
; 输入：si = 字符串地址（字符串必须以 0 结尾）
; 输出：无（字符串显示在屏幕上）
;
; 工作原理：
; 1. 从 si 指向的地址开始读取字符
; 2. 使用 BIOS 中断 0x10 显示每个字符
; 3. 遇到 0 字符时停止（字符串结束符）
;
; 使用的 BIOS 功能：
; - INT 0x10, AH=0x0E：TTY 模式显示字符
;   - AL = 要显示的字符
;   - 功能：在当前光标位置显示字符，并自动移动光标
print_string:
    ; ========== 保存寄存器 ==========
    push ax              ; 保存 ax（函数会修改 ax）
    push si              ; 保存 si（函数会修改 si，但需要恢复原始值）
    ; 注意：虽然函数会修改 si，但我们保存的是调用者传入的值
    ; 实际上，lodsb 会修改 si，但我们在循环中使用的是修改后的 si
    ; 这里保存 si 是为了符合函数调用约定
    
    ; ========== 设置 BIOS 功能 ==========
    mov ah, 0x0E
    ; 将 0x0E 加载到 ah（ax 的高 8 位）
    ; ah=0x0E 是 BIOS 视频服务的功能号，表示"在 TTY 模式下显示字符"
    ; 这个功能会在当前光标位置显示字符，并自动移动光标到下一个位置
    
.loop:
    ; ========== 读取字符 ==========
    lodsb
    ; lodsb 指令：Load String Byte
    ; 功能：
    ;   1. 从 [si] 指向的内存地址读取一个字节到 al 寄存器
    ;   2. 自动将 si 加 1（指向下一个字节）
    ; al 是 ax 的低 8 位，用于存储单个字符（ASCII 码）
    
    ; ========== 检查字符串结束 ==========
    test al, al
    ; test 指令：执行 al AND al 操作（逻辑与）
    ; 功能：检查 al 是否为零，但不修改 al 的值
    ; 如果 al 为零，零标志位（ZF）会被设置
    jz .done
    ; jz 指令：Jump if Zero，如果零标志位被设置则跳转
    ; 如果 al 为零（字符串结束符），跳转到 .done 标签
    ; 否则继续执行下一条指令
    
    ; ========== 显示字符 ==========
    int 0x10
    ; int 指令：调用 BIOS 中断 0x10（视频服务中断）
    ; 此时 ah=0x0E（之前设置的），al 包含要显示的字符
    ; 这个中断调用会在屏幕上显示 al 中的字符
    ; BIOS 会自动处理光标移动、换行等操作
    
    jmp .loop
    ; 无条件跳转回 .loop 标签
    ; 继续读取并显示下一个字符
    ; 这形成了一个循环，直到遇到字符串结束符（0）
    
.done:
    ; ========== 恢复寄存器并返回 ==========
    pop si               ; 恢复 si（虽然 si 已被修改，但这是调用约定）
    pop ax               ; 恢复 ax
    ret
    ; ret 指令：从函数返回
    ; 返回到调用者（主程序或事件处理器）

; 换行函数
; 功能：在屏幕上输出回车和换行，使光标移动到下一行
; 输入：无
; 输出：无（光标移动到下一行）
;
; 工作原理：
; 1. 输出回车符（0x0D）：将光标移动到当前行的开头
; 2. 输出换行符（0x0A）：将光标移动到下一行
; 这两个字符组合使用可以实现换行效果
newline:
    push ax              ; 保存 ax
    
    ; ========== 设置 BIOS 功能 ==========
    mov ah, 0x0E
    ; 设置 BIOS 视频服务功能号为 0x0E（TTY 模式显示字符）
    
    ; ========== 输出回车符 ==========
    mov al, 0x0D
    ; 将回车符（Carriage Return, CR）的 ASCII 码加载到 al
    ; 0x0D = 13（十进制），表示回车符
    ; 功能：将光标移动到当前行的开头（最左侧）
    int 0x10
    ; 调用 BIOS 中断显示回车符
    
    ; ========== 输出换行符 ==========
    mov al, 0x0A
    ; 将换行符（Line Feed, LF）的 ASCII 码加载到 al
    ; 0x0A = 10（十进制），表示换行符
    ; 功能：将光标移动到下一行（垂直向下移动一行）
    int 0x10
    ; 调用 BIOS 中断显示换行符
    ; 现在光标已经移动到下一行的开头
    
    pop ax               ; 恢复 ax
    ret
    ; ret 指令：从函数返回

; ========== 数据定义 ==========
; 这些变量存储在程序的数据段中，在程序执行期间可以读写

; 事件处理器数组
; 功能：存储已注册的事件处理器函数地址
; 大小：最多 MAX_HANDLERS 个处理器
; 每个元素：2 字节（16位模式下的地址偏移量）
;
; 数组结构：
;   event_handlers[0]  : 第一个处理器的地址（2 字节）
;   event_handlers[2]  : 第二个处理器的地址（2 字节）
;   event_handlers[4]  : 第三个处理器的地址（2 字节）
;   ...
;   event_handlers[18] : 第十个处理器的地址（2 字节）
;
; 访问方式：
;   - 通过索引访问：event_handlers + (index * 2)
;   - 例如：event_handlers[2] 的地址 = event_handlers + 2
;
; 初始化：
;   - 所有元素初始化为 0（表示未使用）
;   - 当处理器被注册时，其地址会被写入相应的数组位置
MAX_HANDLERS equ 10
; equ 指令：定义常量，MAX_HANDLERS = 10
; 这定义了事件处理器数组的最大容量
; 可以根据需要修改这个值（但要注意引导扇区只有 512 字节的限制）
event_handlers times MAX_HANDLERS dw 0
; times 指令：重复指定次数的操作
; MAX_HANDLERS：重复次数（10 次）
; dw 0：每次定义一个 16 位（2 字节）的字，初始值为 0
; 结果：创建一个包含 10 个元素的数组，每个元素 2 字节，总共 20 字节
; 所有元素初始化为 0，表示没有处理器注册

; 当前处理器数量
; 功能：跟踪当前已注册的事件处理器数量
; 大小：2 字节（16位）
; 范围：0 到 MAX_HANDLERS（0 到 10）
;
; 使用方式：
;   - 初始化为 0（没有处理器）
;   - 每次订阅事件时递增（inc word [handler_count]）
;   - 每次取消订阅时递减（dec word [handler_count]）
;   - 用于计算数组中的下一个可用位置
;
; 示例：
;   handler_count = 0：没有处理器
;   handler_count = 3：有 3 个处理器，存储在 event_handlers[0], [2], [4]
handler_count dw 0
; dw 指令：Define Word，定义一个 16 位（2 字节）的字
; 0：初始值为 0，表示开始时没有注册任何处理器

; 消息字符串
msg_title:
    db "=== Event System Demo ===", 0x0D, 0x0A, 0

msg_init:
    db "Initializing event system...", 0x0D, 0x0A, 0

msg_subscribe:
    db 0x0D, 0x0A, "Subscribing event handlers:", 0x0D, 0x0A, 0

msg_handler1_registered:
    db "  [OK] Handler 1 registered", 0x0D, 0x0A, 0

msg_handler2_registered:
    db "  [OK] Handler 2 registered", 0x0D, 0x0A, 0

msg_handler3_registered:
    db "  [OK] Handler 3 registered", 0x0D, 0x0A, 0

msg_trigger:
    db 0x0D, 0x0A, "Triggering event...", 0x0D, 0x0A, 0

msg_trigger_again:
    db 0x0D, 0x0A, "Triggering event again...", 0x0D, 0x0A, 0

msg_handler1_executed:
    db "  -> Handler 1 executed!", 0x0D, 0x0A, 0

msg_handler2_executed:
    db "  -> Handler 2 executed!", 0x0D, 0x0A, 0

msg_handler3_executed:
    db "  -> Handler 3 executed!", 0x0D, 0x0A, 0

msg_done:
    db 0x0D, 0x0A, "Demo completed!", 0x0D, 0x0A, 0

; ========== 引导扇区填充 ==========
; 引导扇区必须是 512 字节，最后 2 字节必须是 0xAA55

; 填充到 510 字节
times 510-($-$$) db 0
; times 指令：重复指定次数的操作
; 
; 为什么是 510 字节？
; - 引导扇区的总大小必须是 512 字节（一个扇区的大小）
; - 最后 2 字节（第 511-512 字节）必须存储引导扇区标志 0xAA55
; - 因此，程序代码和数据部分最多只能占用前 510 字节（第 1-510 字节）
;
; 计算过程：
; - $ 表示当前地址（msg_done 字符串定义后的地址）
; - $$ 表示程序起始地址（org 0x7C00，即 0x7C00）
; - ($-$$) 计算从程序开始到当前位置已经使用的字节数
; - 510-($-$$) 计算还需要填充多少个 0 字节，才能让程序部分正好是 510 字节
;
; 示例：如果程序已经用了 200 字节，那么 510-200=310，需要填充 310 个 0
; 这样：200 字节程序 + 310 字节填充 = 510 字节，再加上 2 字节标志 = 512 字节
;
; db 0：每个字节填充为 0（空字节）

; 引导扇区标志（魔数）
dw 0xAA55
; dw 指令：Define Word，定义一个字（2 字节）的数据
; 0xAA55 是引导扇区的魔数（magic number）
; BIOS 会检查引导扇区的最后两个字节是否为 0xAA55
; 如果不是这个值，BIOS 会认为这不是有效的引导扇区，不会执行
; 注意：x86 是小端序（Little Endian），所以：
;   - 低地址（第 511 字节）存储 0x55
;   - 高地址（第 512 字节）存储 0xAA
; 在内存中的布局：0x55 0xAA（从低地址到高地址）

