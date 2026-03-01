# Linux 内核中的进程与线程：统一用 task_struct 表示

本文档基于 Linux 内核源码分析：**进程（process）与线程（thread）在内核里都用同一套结构 `struct task_struct` 表示**，通过若干字段和共享结构区分“进程”与“线程”。源码路径以 `linux/` 表示（如 `/Users/weli/works/linux`）。

---

## 1. 结论概览

- **唯一表示**：调度与生命周期的最小单位是 **`struct task_struct`**（`include/linux/sched.h`）。没有单独的 “process 结构” 或 “thread 结构”。
- **进程 vs 线程**：
  - **进程**（用户态意义上的“一个进程”）= **线程组（thread group）** = 一组共享同一 `signal_struct`（以及通常同一 `mm_struct`）的 `task_struct`，其中**主线程**为 **thread group leader**。
  - **线程** = 同一线程组内除 leader 外的其它 `task_struct`；每个线程仍有自己的 `pid`（内核中的 task ID），但共享 `tgid`（线程组 ID，即用户态看到的“进程 ID”）。
- **共享与区分**：通过 **`tgid`、`group_leader`、`signal`、`mm`** 以及 **`signal_struct::thread_head`** 表达“同一进程的多线程”。

---

## 2. task_struct 中与进程/线程相关的关键字段

以下字段均来自 `include/linux/sched.h` 中的 `struct task_struct`。

| 字段 | 类型 | 含义 |
|------|------|------|
| **pid** | pid_t | 内核中该**任务**的 ID（每个 task_struct 唯一）。用户态线程的 “thread ID” 即对应此 pid。 |
| **tgid** | pid_t | **Thread Group ID**。对 thread group leader 而言 tgid == pid（即用户态“进程 ID”）；对同组其它线程，tgid == group_leader->pid。 |
| **group_leader** | struct task_struct * | 本线程所属**线程组的主线程**。Leader 的 group_leader 指向自己；其它线程指向该组的 leader。 |
| **mm** | struct mm_struct * | 进程地址空间。**同一进程的所有线程共享同一 mm**（由 clone(CLONE_VM) 或 CLONE_THREAD 隐含）；内核线程为 NULL。 |
| **signal** | struct signal_struct * | **同一线程组共享**。信号、线程组统计、thread_head 等都在此结构内。 |
| **sighand** | struct sighand_struct * | 信号处理表。与 signal 一起，同组线程共享。 |
| **thread_node** | struct list_head | 挂到 **signal->thread_head** 上，用于遍历该线程组的全部 task_struct。 |
| **exit_signal** | int | Leader 为 >=0（用于 wait 等）；**非 leader 线程为 -1**（`kernel/fork.c` 中 CLONE_THREAD 时设置）。 |

---

## 3. 线程组与 signal_struct

线程组共享的 `struct signal_struct`（`include/linux/sched/signal.h`）中与“线程列表”直接相关的是：

```c
struct signal_struct {
	// ...
	int			nr_threads;      // 本组线程数
	struct list_head	thread_head;    // 本组所有 task 通过 task->thread_node 链在此
	// ...
};
```

- **thread_head**：该进程（线程组）内**所有** `task_struct` 的 **thread_node** 都链在此链表上。
- **同一线程组** 的判定：`p1->signal == p2->signal`（`same_thread_group()`，`include/linux/sched/signal.h`）。
- **Thread group leader** 的判定：`p->exit_signal >= 0`（`thread_group_leader()`）。Leader 是“进程”的主线程，其 `tgid == pid`，`group_leader == p`。

遍历同组下一个线程可使用 `next_thread(p)`，内部通过 `p->signal->thread_head` 与 `p->thread_node` 实现。

---

## 4. 创建“进程”与“线程”时的差异（fork.c）

在 `kernel/fork.c` 的 `copy_process()` 中，是否传入 **CLONE_THREAD** 决定新任务是“新进程”还是“同一进程的新线程”：

- **CLONE_THREAD 未设**（新建进程 / 主线程）：
  - `p->group_leader = p`
  - `p->tgid = p->pid`
  - 分配新的 **signal_struct**（及 sighand 等），新任务成为 thread group leader，`exit_signal >= 0`，并走 `children/sibling` 等进程树逻辑。
- **CLONE_THREAD 设置**（新建线程）：
  - `p->group_leader = current->group_leader`
  - `p->tgid = current->tgid`
  - `p->exit_signal = -1`
  - **不**新建 signal_struct，沿用 current 的 **signal**（及 sighand）。
  - 通过 `list_add_tail_rcu(&p->thread_node, &p->signal->thread_head)` 把新 task 挂到同一线程组的 **thread_head** 上，并增加 `signal->nr_threads` 等。

用户态 `pthread_create` 等会通过 `clone(..., CLONE_THREAD | CLONE_VM | ...)` 创建线程，对应到上述“新线程”路径。

---

## 5. 简要对照表

| 概念 | 内核表示 |
|------|----------|
| 调度单位 / 可执行实体 | 一个 **task_struct**（无论进程还是线程） |
| 用户态“进程” | 一个 **线程组**：同一 **signal_struct**、同一 **tgid**、一个 **group_leader** |
| 用户态“进程 ID”（getpid()） | **tgid**（即 group_leader->pid） |
| 用户态“线程 ID” | **pid**（每个 task_struct 一个） |
| 线程组内主线程 | **group_leader**，且 **thread_group_leader(p) == true**（exit_signal >= 0） |
| 同组线程链表 | **signal->thread_head**，节点为各 task 的 **thread_node** |

---

## 6. 小结

- 内核**没有**单独的 “process 结构” 和 “thread 结构”，**统一用 `struct task_struct`** 表示可调度实体。
- “进程” = 以 **thread group leader** 为代表的一个 **线程组**，通过共享 **signal_struct**（及通常 **mm_struct**）和相同的 **tgid**、**group_leader** 关联在一起；**thread_head / thread_node** 把同组所有 task 串成链表。
- 创建方式上，**CLONE_THREAD** 决定新 task 是加入当前线程组（线程）还是新建线程组（进程/主线程）。  
这样，一套 **task_struct** 就同时表达了“进程”与“线程”两种视图。

---

## 7. 与用户态轻量级并发（Goroutine / Virtual Thread）的对比

**Go 的 goroutine** 和 **Java 的 virtual thread** 在设计上比**内核线程（kernel thread，即 task_struct）**更轻量，通常**开销更小**。

### 7.1 为何更小？

| 维度 | 内核线程（OS thread） | Goroutine / Virtual thread |
|------|------------------------|-----------------------------|
| **创建** | 需进内核（clone/syscall）、分配内核栈、填 task_struct、挂调度器等 | **用户态**分配栈和描述符，一般不新建内核线程，只向运行时登记 |
| **切换** | **内核态**调度：保存/恢复大量寄存器、可能换页表、跑内核调度器、可能换 CPU | **用户态**切换：运行时在固定少量内核线程上切换栈/上下文，多数情况**不进出内核** |
| **内存** | 每线程一个**内核栈**（常 8KB～1MB）+ task_struct 等 | 小栈起步（goroutine 约 2KB 起、可扩；virtual thread 类似），可成千上万而不增加同等数量的内核线程 |
| **数量** | 受内核栈和 task 数量限制，通常数千到数万量级就有压力 | 可轻松到数十万、百万级（由运行时在少量 OS 线程上做 M:N 调度） |

因此：**创建更便宜、切换更便宜、每“逻辑线程”占的内存更少**，整体开销小于“一个逻辑并发单位对应一个 kernel thread”的模型。

### 7.2 本质区别

- **Kernel thread**：调度单位是 OS 的 **task_struct**，由内核调度，每次调度都可能做完整的内核上下文切换。
- **Goroutine / Virtual thread**：是**用户态**的调度单位，由 **Go runtime** 或 **JVM** 在**少量**内核线程上做 **M:N 映射**；只有当他们要执行阻塞系统调用等时，才会占住或换用内核线程，多数“逻辑切换”不经过内核。

所以：**goroutine 和 virtual thread 都比“一个逻辑并发对应一个 kernel thread”的开销更小**；它们正是用“用户态调度 + 少用内核线程”来换取这一点的。

---

## 参考源码路径（linux 树）

- `include/linux/sched.h` — `struct task_struct`，pid/tgid/group_leader/mm/signal/sighand/thread_node
- `include/linux/sched/signal.h` — `struct signal_struct`（thread_head）、`thread_group_leader()`、`same_thread_group()`、`next_thread()`
- `include/uapi/linux/sched.h` — `CLONE_THREAD`、`CLONE_VM`
- `kernel/fork.c` — `copy_process()` 中设置 group_leader/tgid、exit_signal，以及 thread_node 加入 thread_head 的逻辑
