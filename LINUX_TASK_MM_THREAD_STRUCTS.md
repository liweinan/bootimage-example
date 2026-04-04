# Linux 内核里 process / thread 相关结构怎么摆

调度与资源的大致关系：**没有单独的 `struct process`**；**用户态的「一条线程」≈ 一个 `task_struct`**；**同一进程里的多条线程** = 多个 `task_struct` **共享** `mm_struct`（以及通常的 `files`、`signal` 等）。

字段位置以 **`include/linux/sched.h`** 里 `struct task_struct` 为准（`mm`、`files`、`signal`、`thread` 等）。

---

## 图 1：单个 `task_struct` 里有什么（内嵌 + 指针）

```mermaid
flowchart TB
  subgraph task["struct task_struct（一个调度实体）"]
    direction TB
    s["void *stack（内核栈等）"]
    m["struct mm_struct *mm"]
    f["struct files_struct *files"]
    sig["struct signal_struct *signal"]
    th["struct thread_struct thread（按架构内嵌）"]
  end

  MM["mm_struct\n地址空间 / 页表"]
  FILES["files_struct\n打开文件描述符表"]
  SIGNAL["signal_struct\n信号、session 等进程级状态"]

  m --> MM
  f --> FILES
  sig --> SIGNAL

  th -.->|x86: 寄存器现场、sp 等| ARCH["arch 私有字段\n见 arch/.../processor.h"]
```

**读图要点**

- **`thread_struct`**：不是「另一个调度对象」，而是 **`task_struct` 的子对象**，保存 CPU/架构相关现场。
- **`mm`**：有用户地址空间时指向 **`mm_struct`**；纯内核线程常见 **`mm == NULL`**（运行用户态时可能用 **`active_mm`** 借用某地址空间，不画在图里）。

---

## 图 2：多线程进程 —— 多个 `task_struct` 共享 `mm`

```mermaid
flowchart LR
  subgraph proc["同一进程（线程组）"]
    direction TB
    T1["task_struct\n线程 1"]
    T2["task_struct\n线程 2"]
    Tn["task_struct\n…"]
  end

  MM["mm_struct\n共享同一地址空间"]

  T1 --> MM
  T2 --> MM
  Tn --> MM
```

**读图要点**

- **每个线程**各自 **`task_struct`**，各自 **`thread_struct`**，各自 **`stack`**。
- **同一进程**内多线程通常 **`mm` 指向同一 `mm_struct`**（`files` / `signal` 也常共享，具体见 `copy_process` / `clone` 标志）。

---

## 图 3：和「进程」口语的对应关系（概念轴）

```mermaid
flowchart TB
  subgraph user["用户态说法"]
    P["进程（多线程时 = 一组线程）"]
    U1["线程 1"]
    U2["线程 2"]
  end

  subgraph kernel["内核对象"]
    MM["mm_struct（常共享）"]
    K1["task_struct #1 + thread #1"]
    K2["task_struct #2 + thread #2"]
  end

  U1 --- K1
  U2 --- K2
  P --- MM
  K1 --> MM
  K2 --> MM
```

---

## 最小对照表

| 用户态习惯说法     | 内核里主要对应 |
|--------------------|----------------|
| 一条线程           | 一个 `task_struct`（含内嵌 `thread_struct`） |
| 进程（地址空间）   | 一个 `mm_struct`，多线程共享同一指针 |
| 打开的文件、信号等 | `files_struct`、`signal_struct` 等，多在同一线程组内共享 |

更细的字段与 `clone()` 标志位有关；读 **`kernel/fork.c`** / **`copy_process()`** 可追踪新建线程时哪些结构是 `dup`、哪些是共享。
