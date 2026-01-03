# Linux 内核中断处理：Top Half 和 Bottom Half

在 Linux 内核中，为了高效、安全地处理硬件中断，内核将中断处理分为两个部分：**Top Half（上半部）** 和 **Bottom Half（下半部）**。这种设计的核心目的是**尽量缩短中断禁用时间**，保证系统的实时性和响应能力。

## 为什么需要 Top Half 和 Bottom Half？

硬件中断是异步发生的，处理时通常需要**关闭中断**（至少对同一中断线），以避免重入。如果整个中断处理都在关闭中断的状态下完成耗时较长的任务（如大量数据拷贝、网络协议栈处理），会导致：

- 其他中断（甚至更高优先级中断）无法及时响应
- 系统实时性变差
- 在多核系统中影响整体性能

因此，内核采用"**尽快结束上半部、把耗时工作推迟到下半部**"的策略。

## Top Half（上半部，也叫 Hard IRQ）

**重要理解：Top Half 都是处理硬件中断的**

- **Top Half 的定义**：Top Half 就是**硬件中断处理程序的上半部**
- **触发方式**：由**硬件中断（Hardware Interrupt）**触发
- **执行时机**：硬件中断到来时**立即执行**，在中断上下文（interrupt context）中运行
- **注册方式**：通过 `request_irq()` 注册的**中断处理函数（IRQ handler）**就是 Top Half

**Top Half 与硬件中断的关系：**

```c
// Top Half 就是硬件中断处理程序
irqreturn_t my_interrupt_handler(int irq, void *dev_id)
{
    // 这个函数就是 Top Half
    // 它由硬件中断触发（如网卡中断、键盘中断等）
    // irq 参数就是硬件中断号（IRQ number）
}
```

**关键点：**

1. **Top Half = 硬件中断处理程序的上半部**
   - 所有 Top Half 都是由硬件中断触发的
   - 没有硬件中断，就没有 Top Half

2. **CPU 异常不是 Top Half**
   - CPU 异常（如页错误、除零错误）虽然也是中断，但通常不称为 Top Half
   - CPU 异常有自己的处理机制

3. **软件中断不是 Top Half**
   - 软中断（softirq）是 Bottom Half 的一种机制
   - 软中断由硬件中断处理程序触发，但本身不是硬件中断

4. **系统调用不是 Top Half**
   - 系统调用虽然通过中断机制实现（如 `INT 0x80`），但不是硬件中断
   - 系统调用是主动触发的，不是硬件异步触发的

**总结：**
- ✅ **Top Half 都是处理硬件中断的**
- ✅ **Top Half 就是硬件中断处理程序的上半部**
- ✅ **所有 Top Half 都由硬件设备的中断请求（IRQ）触发**

- **特点**：
  - 关闭中断（至少当前 IRQ 线被屏蔽）
  - 不能睡眠、不能调度、不能访问用户空间
  - 执行时间必须极短（通常几微秒到几十微秒）
  - 不能调用可能引起进程调度的函数（如 `kmalloc()` 用 `GFP_KERNEL` 标志）

- **主要任务**：
  - 从硬件读取数据或状态寄存器
  - 清除中断源（向设备写寄存器确认）
  - 向中断控制器发送 EOI（End of Interrupt）
  - 标记有工作需要后续处理（唤醒下半部机制）

- **代码位置**：驱动程序中通过 `request_irq()` 注册的**中断处理函数（IRQ handler）** 就是 Top Half。

**示例（简化）：**

```c
irqreturn_t my_interrupt_handler(int irq, void *dev_id)
{
    // Top Half：必须快速完成
    u32 status = readl(dev->regs + STATUS);
    if (status & DATA_READY) {
        disable_device_interrupt(dev);  // 暂时屏蔽
        tasklet_schedule(&dev->tasklet);  // 触发 Bottom Half
    }
    return IRQ_HANDLED;
}
```

## Bottom Half（下半部）

- **执行时机**：在**中断返回后**的安全时机执行，通常开中断运行。

- **特点**：
  - 可以被抢占、可以睡眠（取决于具体机制）
  - 执行时间可以较长（毫秒级）
  - 运行在进程上下文或软中断上下文中

- **主要任务**：
  - 处理上半部收集到的数据（如网络包入队、块设备 I/O 完成）
  - 复杂协议处理、内存分配、拷贝到用户空间等耗时操作

- **Linux 内核提供的 Bottom Half 机制**（历史到现代演变）：

- **BH** (Bottom Half)
  - **引入时间**: 很早期（2.2 前）
  - **特点**: 最多 32 个，全局同步
  - **当前状态**: 已废弃
  - **典型用途**: -

- **Task Queue**
  - **引入时间**: 早期
  - **特点**: 队列形式，后被 workqueue 取代
  - **当前状态**: 已废弃
  - **典型用途**: -

- **Softirq**
  - **引入时间**: 2.3 起
  - **特点**: 高性能、静态注册、同一类型可在多核并行执行
  - **当前状态**: 仍在大量使用
  - **典型用途**: 网络（NET_RX/TX）、块设备、定时器

- **Tasklet**
  - **引入时间**: 2.3 起
  - **特点**: 基于 softirq，动态创建，同一 tasklet 不会并行
  - **当前状态**: 仍在使用，但不推荐新代码
  - **典型用途**: 许多老驱动

- **Workqueue**
  - **引入时间**: 2.5 起
  - **特点**: 在进程上下文中执行，可睡眠，行为最像普通函数
  - **当前状态**: 强烈推荐新代码使用
  - **典型用途**: 大多数现代驱动的下半部

## 三种主流 Bottom Half 机制对比

- **执行上下文**
  - **Softirq**: 软中断上下文（原子上下文）
  - **Tasklet**: 软中断上下文（原子上下文）
  - **Workqueue**: 进程上下文（可睡眠）

- **是否可睡眠**
  - **Softirq**: 不可
  - **Tasklet**: 不可
  - **Workqueue**: 可以

- **并行执行**
  - **Softirq**: 同一类型可在不同 CPU 并行执行
  - **Tasklet**: 同一 tasklet 不会在多 CPU 并行
  - **Workqueue**: 可并行（取决于队列类型）

- **优先级**
  - **Softirq**: 最高（高于 tasklet 和 workqueue）
  - **Tasklet**: 次于 softirq
  - **Workqueue**: 最低

- **注册方式**
  - **Softirq**: 静态（内核编译时确定，只有 10 种）
  - **Tasklet**: 动态（tasklet_init）
  - **Workqueue**: 动态（create_workqueue 或 schedule_work）

- **典型场景**
  - **Softirq**: 高吞吐量场景（如网卡收包）
  - **Tasklet**: 中断处理中中等复杂度的任务
  - **Workqueue**: 需要睡眠或大量计算的任务

## 执行时机示意图

```
硬件中断到来
    │
    ▼
Top Half（Hard IRQ） ←── 立即执行，关中断，极短时间
    │                     标记需要处理的数据
    ▼
触发 Bottom Half（softirq / tasklet / work）
    │
    ▼
中断返回 → 开中断 → 系统继续运行其他任务
    │
    ▼（稍后）
Bottom Half 执行（开中断，相对安全的环境）
```

## Top Half 如何将任务交给 Bottom Half？

**答案：取决于使用的 Bottom Half 机制。Top Half 不会"创建"新的任务，而是通过不同的方式标记/调度工作：**

### Softirq 机制：标记位图

**Softirq 是静态的**，Top Half 只是**标记**需要处理的软中断类型，而不是创建新任务。

```c
// Top Half 中触发软中断
irqreturn_t network_interrupt_handler(int irq, void *dev_id)
{
    // 快速处理：读取硬件状态
    struct net_device *dev = dev_id;
    u32 status = readl(dev->regs + STATUS);
    
    if (status & RX_READY) {
        // 将数据包从硬件缓冲区移到内核缓冲区（快速操作）
        enqueue_packet_to_skb_list(dev);
        
        // 标记软中断待处理（不是创建任务，只是设置位图）
        raise_softirq(NET_RX_SOFTIRQ);  // 设置 __softirq_pending 位图对应位
    }
    
    return IRQ_HANDLED;
}
```

**内部实现：**

```c
// linux/kernel/softirq.c
void raise_softirq(unsigned int nr)
{
    unsigned long flags;
    
    local_irq_save(flags);
    __raise_softirq_irqoff(nr);  // 设置当前 CPU 的软中断位图
    local_irq_restore(flags);
}

void __raise_softirq_irqoff(unsigned int nr)
{
    // 设置 per-CPU 位图：__softirq_pending[nr/32] |= (1 << (nr % 32))
    trace_softirq_raise(nr);
    or_softirq_pending(1UL << nr);
}
```

**特点：**
- Softirq 处理函数是**编译时静态注册**的（`open_softirq()`）
- Top Half 只是**设置位图标志**，表示"这个软中断类型需要处理"
- 中断返回时，内核检查位图，调用对应的处理函数
- **没有创建新任务，只是标记待处理的工作**

### Tasklet 机制：调度已存在的 Tasklet

**Tasklet 是预先创建好的**，Top Half 只是**调度**它执行，而不是创建新任务。

```c
// 驱动初始化时创建 tasklet（不是 Top Half 中创建）
static void my_tasklet_func(unsigned long data)
{
    // Bottom Half 处理函数
    struct my_device *dev = (struct my_device *)data;
    process_data(dev);
}

static struct tasklet_struct my_tasklet;

// 驱动初始化
static int my_driver_init(void)
{
    // 初始化 tasklet（预先创建）
    tasklet_init(&my_tasklet, my_tasklet_func, (unsigned long)dev);
    return 0;
}

// Top Half 中调度 tasklet
irqreturn_t my_interrupt_handler(int irq, void *dev_id)
{
    struct my_device *dev = dev_id;
    
    // 快速处理：读取硬件数据
    read_hardware_data(dev);
    
    // 调度 tasklet（不是创建，只是标记为待处理并加入队列）
    tasklet_schedule(&my_tasklet);  // 将 tasklet 加入 per-CPU 队列
    
    return IRQ_HANDLED;
}
```

**内部实现：**

```c
// linux/include/linux/interrupt.h
static inline void tasklet_schedule(struct tasklet_struct *t)
{
    if (!test_and_set_bit(TASKLET_STATE_SCHED, &t->state))
        __tasklet_schedule(t);  // 将 tasklet 加入 per-CPU 链表
}

// linux/kernel/softirq.c
void __tasklet_schedule(struct tasklet_struct *t)
{
    unsigned long flags;
    
    local_irq_save(flags);
    t->next = NULL;
    *__this_cpu_read(tasklet_vec.tail) = t;  // 加入 per-CPU 链表
    __this_cpu_write(tasklet_vec.tail, &(t->next));
    raise_softirq_irqoff(TASKLET_SOFTIRQ);  // 触发 TASKLET_SOFTIRQ
    local_irq_restore(flags);
}
```

**特点：**
- Tasklet 是**预先创建**的数据结构（`struct tasklet_struct`）
- Top Half 只是将 tasklet **加入 per-CPU 队列**，标记为待处理
- **没有创建新任务**，只是调度已存在的 tasklet

### Workqueue 机制：创建 Work 并加入队列

**Workqueue 是唯一真正"创建"工作项的机制**，Top Half 可以动态创建 `work_struct` 并加入工作队列。

```c
// 方式1：使用预定义的 work（推荐）
static void my_work_func(struct work_struct *work)
{
    // Bottom Half 处理函数
    struct my_device *dev = container_of(work, struct my_device, work);
    process_data(dev);
}

struct my_device {
    struct work_struct work;  // 预先定义的工作结构
    // ...
};

// 驱动初始化
static int my_driver_init(void)
{
    INIT_WORK(&dev->work, my_work_func);  // 初始化 work
    return 0;
}

// Top Half 中调度 work
irqreturn_t my_interrupt_handler(int irq, void *dev_id)
{
    struct my_device *dev = dev_id;
    
    // 快速处理
    read_hardware_data(dev);
    
    // 将 work 加入工作队列（不是创建新 work，而是调度已存在的 work）
    schedule_work(&dev->work);  // 加入系统默认工作队列
    
    return IRQ_HANDLED;
}
```

**内部实现：**

```c
// linux/kernel/workqueue.c
bool schedule_work(struct work_struct *work)
{
    return queue_work(system_wq, work);  // 加入系统默认工作队列
}

bool queue_work(struct workqueue_struct *wq, struct work_struct *work)
{
    bool ret = false;
    unsigned long flags;
    
    // 将 work 加入工作队列的链表
    raw_spin_lock_irqsave(&wq->pool->lock, flags);
    if (!list_empty(&work->entry))  // work 已经在队列中
        goto out;
    
    // 将 work 加入队列链表
    insert_work(pwq, work, &pwq->pool->worklist, work_flags);
    
    // 唤醒工作线程处理
    wake_up_worker(pwq->pool);
out:
    raw_spin_unlock_irqrestore(&wq->pool->lock, flags);
    return ret;
}
```

**特点：**
- Workqueue 可以**动态创建** `work_struct`（但通常预先创建）
- Top Half 将 work **加入工作队列的链表**
- 工作线程（worker thread）从队列中取出 work 并执行
- **这是最接近"创建任务放入队列"的机制**

## 三种机制的对比总结

- **Softirq**
  - **Top Half 的操作**: `raise_softirq()`
  - **是否创建新任务**: ❌ 否，只是标记位图
  - **队列/数据结构**: per-CPU 位图 `__softirq_pending`
  - **执行者**: 软中断处理程序（中断返回时或 ksoftirqd 线程）

- **Tasklet**
  - **Top Half 的操作**: `tasklet_schedule()`
  - **是否创建新任务**: ❌ 否，调度已存在的 tasklet
  - **队列/数据结构**: per-CPU 链表 `tasklet_vec`
  - **执行者**: TASKLET_SOFTIRQ 处理程序

- **Workqueue**
  - **Top Half 的操作**: `schedule_work()`
  - **是否创建新任务**: ⚠️ 可以动态创建，但通常预先创建
  - **队列/数据结构**: 工作队列链表 `pool->worklist`
  - **执行者**: 工作线程（worker thread）

## 完整示例：网络数据包接收

```c
// 网卡驱动 Top Half
irqreturn_t e1000_interrupt(int irq, void *dev_id)
{
    struct net_device *netdev = dev_id;
    struct e1000_adapter *adapter = netdev_priv(netdev);
    u32 icr;
    
    // 1. 快速读取硬件状态（Top Half）
    icr = er32(ICR);
    if (!icr)
        return IRQ_NONE;
    
    // 2. 快速处理：将数据包从硬件缓冲区移到内核缓冲区
    if (icr & (E1000_ICR_RXT0 | E1000_ICR_RXSEQ)) {
        // 将数据包加入接收队列（快速操作）
        e1000_clean_rx_irq(adapter);
    }
    
    // 3. 标记软中断待处理（不是创建任务，只是设置位图）
    if (likely(napi_schedule_prep(&adapter->napi))) {
        __raise_softirq_irqoff(NET_RX_SOFTIRQ);  // 标记网络接收软中断
    }
    
    return IRQ_HANDLED;
}

// 软中断处理程序（Bottom Half）- 这是编译时注册的
static void net_rx_action(struct softirq_action *h)
{
    struct softnet_data *sd = &__get_cpu_var(softnet_data);
    unsigned long time_limit = jiffies + 2;
    int budget = netdev_budget;
    void *have;
    
    local_irq_disable();
    while (!list_empty(&sd->poll_list)) {
        struct napi_struct *n;
        
        // 从队列中取出 napi 结构（代表一个网络设备）
        n = list_first_entry(&sd->poll_list, struct napi_struct, poll_list);
        
        // 处理数据包（耗时操作）
        budget -= n->poll(n, budget);
        
        // ...
    }
}
```

## 总结

**Top Half 是否创建任务放入队列？**

- **Softirq**：❌ **不创建**，只是设置位图标志
- **Tasklet**：❌ **不创建**，只是将已存在的 tasklet 加入队列
- **Workqueue**：⚠️ **可以创建**，但通常预先创建 work，Top Half 只是将其加入队列

**关键理解：**
- Top Half 的职责是**快速响应硬件**，**标记需要后续处理的工作**
- Bottom Half 机制负责**实际执行这些工作**
- 大多数情况下，Bottom Half 的处理函数和数据结构都是**预先准备好的**，Top Half 只是**触发/调度**它们执行
- 只有 Workqueue 支持动态创建 work，但即使这样，通常也预先创建以提高效率

## Top Half 和 Bottom Half 总结

- **Top Half**：快速响应硬件、做最小必要工作，目的是尽快返回。
- **Bottom Half**：完成剩余的耗时工作，利用 softirq、tasklet 或 workqueue 等机制延迟执行。
- 现代内核开发推荐优先使用 **workqueue**（尤其是可睡眠场景），只有在对性能要求极高的场景才使用 **softirq** 或 **tasklet**。

这种分层设计是 Linux 内核中断子系统高效、稳定的核心原因之一。

## 键盘驱动示例：Top Half 和 Bottom Half 设计

下面以键盘驱动为例，展示如何设计 Top Half 和 Bottom Half 代码。键盘使用 IRQ1，当用户按下按键时，键盘控制器会产生硬件中断。

### 键盘驱动数据结构设计

```c
#include <linux/interrupt.h>
#include <linux/workqueue.h>
#include <linux/input.h>
#include <linux/slab.h>

// 键盘扫描码缓冲区（用于 Top Half 和 Bottom Half 之间的数据传递）
#define KEYBOARD_BUFFER_SIZE 256

struct keyboard_device {
    struct input_dev *input_dev;      // 输入设备结构
    struct work_struct work;           // Bottom Half 工作项
    u8 scan_code_buffer[KEYBOARD_BUFFER_SIZE];  // 扫描码缓冲区
    int buffer_head;                   // 缓冲区头指针
    int buffer_tail;                   // 缓冲区尾指针
    spinlock_t buffer_lock;            // 保护缓冲区的自旋锁
    int irq;                           // 中断号（IRQ1）
    void __iomem *iobase;              // I/O 端口基地址（0x60/0x64）
};
```

### Top Half：快速响应硬件中断

**设计原则：**
- 执行时间极短（微秒级）
- 只做最小必要工作：读取扫描码、确认中断
- 将耗时操作（扫描码转换、放入输入子系统）推迟到 Bottom Half

```c
// Top Half：硬件中断处理函数
static irqreturn_t keyboard_interrupt_handler(int irq, void *dev_id)
{
    struct keyboard_device *kbd = dev_id;
    u8 scan_code;
    unsigned long flags;
    
    // ========== Top Half 开始：必须快速完成 ==========
    
    // 1. 从键盘控制器读取扫描码（I/O 端口 0x60）
    // 这是硬件操作，必须立即完成
    scan_code = inb(0x60);
    
    // 2. 读取状态寄存器（可选，用于错误检测）
    // u8 status = inb(0x64);
    
    // 3. 向键盘控制器发送 EOI（End of Interrupt）
    // 对于 x86 PIC，这通常由内核自动处理，但某些情况下需要手动确认
    // outb(0x20, 0x20);  // 向主 PIC 发送 EOI（如果需要）
    
    // 4. 将扫描码快速放入缓冲区（临界区操作）
    // 注意：这里使用自旋锁，因为是在中断上下文中
    spin_lock_irqsave(&kbd->buffer_lock, flags);
    
    // 检查缓冲区是否已满
    int next_head = (kbd->buffer_head + 1) % KEYBOARD_BUFFER_SIZE;
    if (next_head == kbd->buffer_tail) {
        // 缓冲区满，丢弃扫描码（或记录错误）
        printk(KERN_WARNING "keyboard: buffer full, dropping scan code\n");
        spin_unlock_irqrestore(&kbd->buffer_lock, flags);
        return IRQ_HANDLED;
    }
    
    // 将扫描码放入缓冲区
    kbd->scan_code_buffer[kbd->buffer_head] = scan_code;
    kbd->buffer_head = next_head;
    
    spin_unlock_irqrestore(&kbd->buffer_lock, flags);
    
    // 5. 调度 Bottom Half 处理（将 work 加入工作队列）
    // 这是 Top Half 的最后一步，也是唯一"慢"的操作（但仍然是原子操作）
    schedule_work(&kbd->work);
    
    // ========== Top Half 结束：总耗时 < 10 微秒 ==========
    
    return IRQ_HANDLED;
}
```

**Top Half 的关键点：**
- ✅ **快速读取硬件数据**：`inb(0x60)` 读取扫描码
- ✅ **最小化临界区**：只保护缓冲区操作
- ✅ **立即返回**：不进行任何耗时操作（如扫描码转换、内存分配）
- ✅ **触发 Bottom Half**：通过 `schedule_work()` 调度后续处理

### Bottom Half：处理扫描码转换和输入事件

**设计原则：**
- 在进程上下文中执行，可以睡眠
- 可以调用可能阻塞的函数（如 `kmalloc(GFP_KERNEL)`）
- 处理所有耗时操作：扫描码转换、输入事件生成

```c
// Bottom Half：工作队列处理函数
static void keyboard_work_handler(struct work_struct *work)
{
    struct keyboard_device *kbd = container_of(work, struct keyboard_device, work);
    u8 scan_code;
    unsigned long flags;
    int key_code;
    bool key_pressed;
    
    // ========== Bottom Half 开始：可以执行耗时操作 ==========
    
    // 循环处理缓冲区中的所有扫描码
    while (1) {
        // 1. 从缓冲区取出扫描码（临界区操作）
        spin_lock_irqsave(&kbd->buffer_lock, flags);
        
        if (kbd->buffer_tail == kbd->buffer_head) {
            // 缓冲区为空，退出循环
            spin_unlock_irqrestore(&kbd->buffer_lock, flags);
            break;
        }
        
        scan_code = kbd->scan_code_buffer[kbd->buffer_tail];
        kbd->buffer_tail = (kbd->buffer_tail + 1) % KEYBOARD_BUFFER_SIZE;
        
        spin_unlock_irqrestore(&kbd->buffer_lock, flags);
        
        // 2. 解析扫描码（耗时操作，但 Bottom Half 中可以安全执行）
        // 扫描码格式：
        // - 普通按键：0x01-0x7F（按下），0x81-0xFF（释放，最高位为1）
        // - 特殊按键：可能有多个字节（如 0xE0 前缀）
        
        if (scan_code == 0xE0) {
            // 扩展键前缀，需要读取下一个字节
            // 这里简化处理，实际需要维护状态机
            continue;
        }
        
        // 判断是按下还是释放
        key_pressed = !(scan_code & 0x80);
        if (!key_pressed) {
            scan_code &= 0x7F;  // 清除最高位，获取原始扫描码
        }
        
        // 3. 扫描码转换为 Linux 输入子系统键码（耗时操作）
        // 这里使用简化的映射表，实际驱动需要完整的扫描码到键码映射
        key_code = scan_code_to_keycode(scan_code);
        
        if (key_code == KEY_RESERVED) {
            // 未知扫描码，跳过
            continue;
        }
        
        // 4. 生成输入事件并上报（可以调用可能阻塞的函数）
        input_report_key(kbd->input_dev, key_code, key_pressed ? 1 : 0);
        input_sync(kbd->input_dev);  // 同步事件
        
        // 5. 可以执行其他耗时操作
        // 例如：记录日志、更新统计信息、触发其他事件等
        // printk(KERN_DEBUG "keyboard: key %d %s\n", key_code, 
        //        key_pressed ? "pressed" : "released");
    }
    
    // ========== Bottom Half 结束 ==========
}

// 扫描码到键码的转换函数（简化版）
static int scan_code_to_keycode(u8 scan_code)
{
    // 简化的映射表，实际驱动需要完整的映射
    static const u8 scan_to_key[] = {
        [0x01] = KEY_ESC,
        [0x02] = KEY_1,
        [0x03] = KEY_2,
        // ... 更多映射
    };
    
    if (scan_code >= ARRAY_SIZE(scan_to_key))
        return KEY_RESERVED;
    
    return scan_to_key[scan_code];
}
```

**Bottom Half 的关键点：**
- ✅ **批量处理**：一次处理缓冲区中的所有扫描码
- ✅ **可以睡眠**：在进程上下文中，可以调用 `kmalloc(GFP_KERNEL)` 等可能阻塞的函数
- ✅ **耗时操作**：扫描码转换、输入事件生成都在这里完成
- ✅ **安全操作**：可以访问用户空间、执行文件 I/O 等

### 驱动初始化和清理

```c
// 驱动初始化
static int keyboard_driver_probe(struct platform_device *pdev)
{
    struct keyboard_device *kbd;
    int ret;
    
    // 1. 分配设备结构（可以睡眠）
    kbd = kzalloc(sizeof(*kbd), GFP_KERNEL);
    if (!kbd)
        return -ENOMEM;
    
    // 2. 初始化缓冲区锁
    spin_lock_init(&kbd->buffer_lock);
    kbd->buffer_head = 0;
    kbd->buffer_tail = 0;
    
    // 3. 初始化 Bottom Half 工作项
    INIT_WORK(&kbd->work, keyboard_work_handler);
    
    // 4. 注册输入设备
    kbd->input_dev = input_allocate_device();
    if (!kbd->input_dev) {
        ret = -ENOMEM;
        goto err_free_kbd;
    }
    
    kbd->input_dev->name = "Example Keyboard";
    kbd->input_dev->id.bustype = BUS_I8042;
    kbd->input_dev->evbit[0] = BIT_MASK(EV_KEY) | BIT_MASK(EV_REP);
    kbd->input_dev->keybit[BIT_WORD(KEY_SPACE)] = BIT_MASK(KEY_SPACE);
    // ... 设置支持的键码位图
    
    ret = input_register_device(kbd->input_dev);
    if (ret)
        goto err_free_input;
    
    // 5. 注册中断处理程序（Top Half）
    kbd->irq = 1;  // IRQ1 是键盘
    ret = request_irq(kbd->irq, keyboard_interrupt_handler,
                     IRQF_SHARED, "keyboard", kbd);
    if (ret)
        goto err_unregister_input;
    
    // 6. 保存设备指针
    platform_set_drvdata(pdev, kbd);
    
    printk(KERN_INFO "keyboard: driver initialized\n");
    return 0;
    
err_unregister_input:
    input_unregister_device(kbd->input_dev);
err_free_input:
    input_free_device(kbd->input_dev);
err_free_kbd:
    kzfree(kbd);
    return ret;
}

// 驱动清理
static int keyboard_driver_remove(struct platform_device *pdev)
{
    struct keyboard_device *kbd = platform_get_drvdata(pdev);
    
    // 1. 释放中断
    free_irq(kbd->irq, kbd);
    
    // 2. 取消待处理的工作（确保 Bottom Half 不会在设备移除后执行）
    cancel_work_sync(&kbd->work);
    
    // 3. 注销输入设备
    input_unregister_device(kbd->input_dev);
    input_free_device(kbd->input_dev);
    
    // 4. 释放设备结构
    kzfree(kbd);
    
    printk(KERN_INFO "keyboard: driver removed\n");
    return 0;
}
```

### 完整执行流程

```
用户按下键盘按键 'A'
    │
    ▼
键盘控制器产生 IRQ1 硬件中断
    │
    ▼
CPU 跳转到中断向量（如 0x21）
    │
    ▼
【Top Half 执行】keyboard_interrupt_handler()
    ├─ 读取扫描码 0x1E（约 1 微秒）
    ├─ 放入缓冲区（约 1 微秒）
    ├─ schedule_work(&kbd->work)（约 1 微秒）
    └─ 返回 IRQ_HANDLED（总耗时 < 10 微秒）
    │
    ▼
中断返回，CPU 继续执行其他任务
    │
    ▼
【稍后，在进程上下文中】
    │
    ▼
【Bottom Half 执行】keyboard_work_handler()
    ├─ 从缓冲区取出扫描码 0x1E
    ├─ 转换为键码 KEY_A
    ├─ 生成输入事件
    ├─ 上报到输入子系统
    └─ 应用层可以读取按键（总耗时可能数毫秒）
    │
    ▼
应用层通过 /dev/input/eventX 读取按键事件
```

### 设计要点总结

- **执行上下文**
  - **Top Half**: 中断上下文
  - **Bottom Half**: 进程上下文

- **执行时间**
  - **Top Half**: < 10 微秒
  - **Bottom Half**: 可以数毫秒

- **可以睡眠**
  - **Top Half**: ❌ 否
  - **Bottom Half**: ✅ 是

- **可以调度**
  - **Top Half**: ❌ 否
  - **Bottom Half**: ✅ 是

- **主要任务**
  - **Top Half**: 读取硬件、确认中断、放入缓冲区
  - **Bottom Half**: 数据处理、事件生成、系统调用

- **使用的机制**
  - **Top Half**: 硬件中断
  - **Bottom Half**: Workqueue（推荐）或 Tasklet

### 错误实践：将 Bottom Half 逻辑放到 Top Half 的后果

**问题：如果我在实现驱动程序的时候把本该放在 bottom half 的一些逻辑放到了 top half 会产生什么后果？**

**答案：会产生严重的系统问题，包括系统响应性下降、中断丢失、系统不稳定等。**

#### 具体后果分析

**后果 1：阻塞其他中断，导致中断丢失**

```c
// ❌ 错误示例：在 Top Half 中执行耗时操作
irqreturn_t bad_interrupt_handler(int irq, void *dev_id)
{
    struct my_device *dev = dev_id;
    u8 data;
    
    // 读取硬件数据（正确）
    data = readl(dev->regs + DATA_REG);
    
    // ❌ 错误：在 Top Half 中执行耗时操作
    // 1. 复杂的数据处理（应该放在 Bottom Half）
    process_complex_data(data);  // 耗时 100 微秒
    
    // 2. 内存分配（可能阻塞，应该放在 Bottom Half）
    char *buffer = kmalloc(1024, GFP_KERNEL);  // ❌ 错误！可能睡眠
    
    // 3. 文件 I/O（绝对不能在 Top Half）
    file_write(dev->log_file, data);  // ❌ 严重错误！会睡眠
    
    return IRQ_HANDLED;
}
```

**问题：**
- Top Half 执行时间过长（如 100 微秒），在此期间**同一 IRQ 线的其他中断被屏蔽**
- 如果硬件在 Top Half 执行期间产生新的中断，**中断会丢失**
- 其他设备的中断也可能被延迟响应

**后果 2：系统响应性严重下降**

```c
// ❌ 错误示例：在 Top Half 中进行网络协议处理
irqreturn_t network_interrupt_handler(int irq, void *dev_id)
{
    struct net_device *dev = dev_id;
    
    // 读取数据包（正确）
    struct sk_buff *skb = read_packet_from_hardware(dev);
    
    // ❌ 错误：在 Top Half 中处理协议栈
    // 这可能需要数毫秒！
    ip_rcv(skb);  // IP 层处理
    tcp_rcv(skb); // TCP 层处理
    // ... 更多协议处理
    
    return IRQ_HANDLED;
}
```

**问题：**
- Top Half 执行时间从几微秒增加到数毫秒
- **整个系统的中断响应时间变慢**
- 键盘输入延迟、鼠标移动卡顿、定时器不准确
- **系统感觉"卡顿"**

**后果 3：可能导致系统崩溃或死锁**

```c
// ❌ 严重错误：在 Top Half 中调用可能睡眠的函数
irqreturn_t bad_interrupt_handler(int irq, void *dev_id)
{
    struct my_device *dev = dev_id;
    
    // ❌ 严重错误：可能睡眠的函数
    mutex_lock(&dev->lock);  // 如果锁被占用，会睡眠！导致系统崩溃
    
    // ❌ 严重错误：可能睡眠的内存分配
    char *buf = kmalloc(1024, GFP_KERNEL);  // GFP_KERNEL 可能睡眠！
    
    // ❌ 严重错误：文件操作（会睡眠）
    copy_to_user(user_buf, buf, 1024);  // 可能触发页错误，睡眠！
    
    return IRQ_HANDLED;
}
```

**问题：**
- 在中断上下文中**不能睡眠**，如果调用可能睡眠的函数会导致：
  - **内核 BUG**：内核会检测到在中断上下文中睡眠，触发 `BUG_ON()`
  - **系统崩溃**：可能导致内核 panic
  - **死锁**：如果等待的资源被其他进程持有，可能导致死锁

**后果 4：CPU 占用率过高**

```c
// ❌ 错误示例：在 Top Half 中进行大量计算
irqreturn_t bad_interrupt_handler(int irq, void *dev_id)
{
    struct my_device *dev = dev_id;
    u8 data[1024];
    
    // 读取数据（正确）
    read_data_from_hardware(dev, data, 1024);
    
    // ❌ 错误：在 Top Half 中进行大量计算
    for (int i = 0; i < 1000000; i++) {
        complex_calculation(data);  // 耗时数毫秒
    }
    
    return IRQ_HANDLED;
}
```

**问题：**
- 如果中断频率高（如网卡每秒数千个数据包），Top Half 执行时间过长会导致：
  - **CPU 大部分时间在中断上下文中**
  - **用户进程无法获得 CPU 时间**
  - **系统负载过高**

**后果 5：实时性要求无法满足**

```c
// ❌ 错误示例：在 Top Half 中处理实时任务
irqreturn_t realtime_interrupt_handler(int irq, void *dev_id)
{
    // 实时任务需要极快的响应
    // 但如果 Top Half 执行时间过长，会延迟其他实时任务
    process_realtime_data();  // 如果耗时，会影响其他实时中断
}
```

**问题：**
- 实时系统要求中断响应时间在微秒级
- Top Half 执行时间过长会导致**实时任务延迟**
- 可能违反实时性要求

#### 实际案例：网络驱动性能问题

**错误实现：**

```c
// ❌ 错误：在 Top Half 中处理所有网络数据包
irqreturn_t e1000_interrupt(int irq, void *dev_id)
{
    struct net_device *netdev = dev_id;
    struct e1000_adapter *adapter = netdev_priv(netdev);
    
    // 读取所有数据包
    while (has_packets(adapter)) {
        struct sk_buff *skb = read_packet(adapter);
        
        // ❌ 错误：在 Top Half 中处理协议栈
        netif_rx(skb);  // 这会处理整个协议栈，耗时数毫秒！
    }
    
    return IRQ_HANDLED;
}
```

**后果：**
- 高负载时，Top Half 执行时间可能达到数毫秒
- 其他中断（如键盘、鼠标）被延迟
- 系统响应变慢，用户体验差

**正确实现：**

```c
// ✅ 正确：Top Half 只做最小必要工作
irqreturn_t e1000_interrupt(int irq, void *dev_id)
{
    struct net_device *netdev = dev_id;
    struct e1000_adapter *adapter = netdev_priv(netdev);
    
    // 快速处理：只读取数据包到缓冲区
    if (likely(napi_schedule_prep(&adapter->napi))) {
        __raise_softirq_irqoff(NET_RX_SOFTIRQ);  // 标记软中断
    }
    
    return IRQ_HANDLED;  // 立即返回，耗时 < 10 微秒
}

// ✅ 正确：在 Bottom Half 中处理协议栈
static void net_rx_action(struct softirq_action *h)
{
    // 在软中断上下文中处理数据包
    // 可以执行耗时操作，不会阻塞其他中断
    process_packets();
}
```

#### 如何避免这些错误

**检查清单：**

1. **Top Half 中不能做的事情：**
   - ❌ 调用可能睡眠的函数（`kmalloc(GFP_KERNEL)`, `mutex_lock()`, `copy_to_user()` 等）
   - ❌ 执行耗时操作（复杂计算、协议处理等）
   - ❌ 文件 I/O 操作
   - ❌ 网络协议栈处理
   - ❌ 长时间循环

2. **Top Half 中应该做的事情：**
   - ✅ 读取硬件寄存器
   - ✅ 确认中断（发送 EOI）
   - ✅ 将数据快速放入缓冲区
   - ✅ 标记软中断或调度工作队列
   - ✅ 立即返回

3. **Bottom Half 中可以做的事情：**
   - ✅ 所有耗时操作
   - ✅ 可能睡眠的操作
   - ✅ 复杂的数据处理
   - ✅ 协议栈处理
   - ✅ 文件 I/O

#### 总结

**将 Bottom Half 逻辑放到 Top Half 的后果：**

| 后果 | 严重程度 | 影响 |
|------|---------|------|
| **阻塞其他中断** | ⚠️ 高 | 中断丢失、设备无响应 |
| **系统响应性下降** | ⚠️ 高 | 键盘延迟、鼠标卡顿、系统感觉"慢" |
| **系统崩溃/死锁** | 🔴 严重 | 内核 BUG、系统 panic |
| **CPU 占用过高** | ⚠️ 中 | 用户进程无法获得 CPU |
| **实时性无法满足** | ⚠️ 高 | 实时任务延迟 |

**核心原则：**
- **Top Half 必须极快**（< 10 微秒）
- **所有耗时操作必须在 Bottom Half**
- **在中断上下文中绝对不能睡眠**
- **遵循"快速响应，延迟处理"的原则**

**关键设计原则：**

1. **Top Half 最小化**：
   - 只做硬件必须立即完成的操作
   - 使用自旋锁保护共享数据（不能使用互斥锁，因为不能睡眠）
   - 快速返回，避免阻塞其他中断

2. **Bottom Half 处理所有耗时操作**：
   - 数据转换、协议处理
   - 内存分配（可以使用 `GFP_KERNEL`）
   - 系统调用、文件 I/O

3. **数据传递**：
   - 使用循环缓冲区在 Top Half 和 Bottom Half 之间传递数据
   - 使用自旋锁保护缓冲区（Top Half 和 Bottom Half 都需要访问）

4. **错误处理**：
   - Top Half 中缓冲区满时，可以丢弃数据或记录错误
   - Bottom Half 中可以执行更复杂的错误恢复

这个设计确保了键盘驱动能够快速响应硬件中断，同时将耗时操作推迟到安全的进程上下文中执行。

## 硬件中断的"立即执行"机制

**"立即执行"不是内核完全控制的，而是硬件机制与内核协作的结果。**

硬件中断的发生和进入处理程序的时机主要由 **CPU 和中断控制器硬件** 决定，内核只能在有限范围内影响或延迟这个"立即性"。

### 硬件中断的发生时机（完全由硬件决定）

- 外部设备（如网卡、键盘、定时器）产生中断请求信号 → 发送到中断控制器（I/O APIC 或 legacy PIC）。
- 中断控制器根据配置将信号转发到某个 CPU 的 Local APIC。
- CPU 的 Local APIC 收到中断请求后，会根据中断优先级和当前状态决定是否立即向 CPU 核心发出中断。

**这个过程完全是硬件行为，内核无法干预。**

### CPU 何时真正"立即"响应中断（硬件主导，内核可部分影响）

CPU 只在**特定时机点**检查并接受中断：

- **指令边界**：CPU 在每条指令执行完成、准备取下一条指令时，会检查是否有待处理的中断（pending interrupt）。
- **不允许在指令中间打断**（除非是不可屏蔽中断 NMI 或某些致命故障）。

影响"立即性"的关键因素：

- **当前是否允许中断（IF 标志）**
  - **谁控制**: 内核可控制
  - **说明**: x86 的 EFLAGS 寄存器中有 IF（Interrupt Flag）位。内核执行 `cli`（关中断）时清除 IF，`sti`（开中断）时置位 IF。**关中断期间，硬件中断会被挂起（pending），不会立即交付给 CPU**。

- **当前任务优先级（Task Priority Level, TPR）**
  - **谁控制**: 内核可通过 APIC 控制
  - **说明**: 在 APIC 模式下，内核可以设置当前 CPU 的任务优先级。如果新中断优先级低于当前 TPR，CPU 会延迟响应。

- **中断屏蔽（Mask）**
  - **谁控制**: 内核可控制
  - **说明**: 内核可以在中断控制器（I/O APIC）或设备寄存器中屏蔽特定 IRQ。屏蔽后硬件不会向上发送中断请求。

- **CPU 是否在执行更高优先级中断**
  - **谁控制**: 硬件 + 内核配置
  - **说明**: 高优先级中断可以抢占低优先级中断（中断嵌套）。内核决定是否允许嵌套。

### 内核实际能控制的范围（有限延迟或禁止）

内核**不能让中断"提前"执行**，但可以做到：

- **延迟执行**：
  - 通过 `cli` / `local_irq_disable()` 关闭中断（常用于临界区保护）。
  - 在进入 Top Half 处理前，同一 IRQ 线通常会被自动屏蔽，防止重入。
  - 在多核系统中，通过 IRQ affinity 把中断定向到特定 CPU，避免打扰其他核。

- **完全禁止某些中断**：
  - 在 `request_irq()` 时指定 `IRQF_DISABLED`（已废弃）或手动屏蔽。
  - 卸载驱动时 `free_irq`，解除中断绑定。

### 典型执行流程（结合硬件和内核）

```
硬件设备产生中断请求
    │
    ▼
中断控制器（I/O APIC） → Local APIC → 标记 pending
    │
    ▼
CPU 在指令边界检查：
    ├── IF 标志为 0（关中断）？ → 中断挂起（pending），等待内核开中断
    ├── 当前优先级不允许？     → 挂起，等待条件满足
    └── 允许交付            → CPU 保存现场 → 从 IDT 跳转到内核通用入口（common_interrupt）
                                   │
                                   ▼
                              内核注册的 Top Half 处理函数立即执行
```

### 总结：内核对"立即执行"的控制程度

- **不能控制中断何时产生**（完全硬件异步）。
- **不能强制中断立刻打断正在执行的指令**（CPU 硬件只在指令边界检查）。
- **可以延迟或阻止中断交付**：
  - 关闭全局中断（cli）
  - 屏蔽特定 IRQ
  - 调整优先级
- 一旦条件满足（开中断 + 指令边界 + 优先级允许），**Top Half 就会被硬件强制立即执行**，这时内核只能被动接受并运行已注册的处理函数。

因此，"硬件中断到来时立即执行"中的"立即"是指**在硬件允许的最近指令边界，且内核没有关闭中断的情况下**，CPU 会强制切换到中断处理。这个"立即性"的核心控制权在 **CPU 硬件**，内核只能通过开关 IF 标志或屏蔽等方式进行**有限干预**（主要是延迟或禁止，不能加速）。

