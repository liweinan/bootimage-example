# SYSCALL 与 INT 0x80：入口阶段、TSS 与 pt_regs

本文档整理「用户态→内核态」两条路径（SYSCALL 与 INT 0x80）的**入口差异**、**TSS 使用**、**内核栈来源**、以及**进内核后统一的 pt_regs 与返回流程**。

---

## 1. SYSCALL 是否用到 TSS？

- **SYSCALL 指令本身**：不用 TSS。CPU 只按 MSR（如 IA32_LSTAR、IA32_STAR）取入口和 CS/SS，不读 IDT，也不读 TSS。
- **内核的 SYSCALL 入口代码**：会用到 TSS，且**只用 TSS.sp2**，作为临时存放**用户 RSP** 的“草稿本”：
  - 切到内核栈前，先把当前 RSP（用户栈顶）存到 TSS.sp2；
  - 再从 per-CPU 变量加载内核栈到 RSP；
  - 之后把 TSS.sp2 里的值抄到 **pt_regs**，返回时从 pt_regs 恢复用户 RSP。

**结论**：syscall 这条指令本身不用 TSS；内核的 syscall 入口会用到 TSS，且只用 TSS.sp2 当临时存用户 RSP。

---

## 2. 入口阶段：SYSCALL 与 INT 0x80 的差异

进内核、切栈、保存用户 RSP 这一段，两条路径**不一样**。

| 步骤 | SYSCALL | INT 0x80 |
|------|---------|----------|
| **内核栈从哪来** | 内核从 **per-CPU 变量**取，不用 TSS | **CPU** 从 **TSS.RSP0** 取 |
| **用户 RSP 怎么保存** | 内核先写到 **TSS.sp2**，再抄到 pt_regs | **CPU** 在切栈时**自动**把用户 SS/RSP 压到新内核栈上（中断帧） |
| **TSS 用在哪** | 只用 **sp2** 当临时草稿 | 用 **RSP0** 提供内核栈，不依赖 sp2 |

- **syscall 入口** = per-CPU 栈 + TSS.sp2 暂存用户 RSP。
- **int 0x80 入口** = TSS.RSP0 换栈 + CPU 压栈保存用户 RSP。

**本质总结**：两条路径**都会用到 TSS**——int 0x80 由 CPU 用 **TSS.RSP0** 取内核栈，syscall 由内核入口用 **TSS.sp2** 暂存用户 RSP。syscall 少的那次“查表”指的是**不查 IDT**：int 0x80 要先用向量号查 IDT 取门描述符，再根据门做栈切换等；syscall 不经过 IDT，直接用 MSR 里的入口和段信息，所以少一次 IDT 查表。因此：两者最终都会用 TSS（一个用 RSP0，一个用 sp2），但 syscall 少了 IDT 这一次查表。

---

## 3. 内核栈地址是否一致？

**是，指向同一块内核栈。**

Linux 对“当前在跑的进程”会保证：

- **TSS.RSP0**：在进程切换时（如 `__switch_to`）被更新成**该进程的内核栈顶**，供 int 0x80 / 中断从用户态进内核时用。
- **syscall 入口用的 per-CPU 变量**：存的也是**当前进程的内核栈指针**（或等价信息），供 syscall 进内核时用。

两种入口用的栈指针**最终都指向当前进程的内核栈**；只是**取这个地址的途径**不同（TSS.RSP0 vs per-CPU 变量），内核在调度/切换时会让两者一致。

---

## 4. 用户 RSP 与现场：都用 pt_regs

两条路径**最后都是用 pt_regs（或等价结构）**保存用户态现场（含用户 RSP），只是**怎么填进 pt_regs** 的路径不同。

### 4.1 SYSCALL

- 用户 RSP 先暂存到 TSS.sp2，再和别的寄存器一起被写进 **pt_regs**。
- 内核栈上就是一份 **pt_regs**，全程用这一份。

### 4.2 INT 0x80 / 中断

- CPU 先按硬件约定在内核栈上压**中断帧**（SS、RSP、RFLAGS、CS、RIP 等）。
- 内核入口代码把这些内容**整理/拷贝进 pt_regs**（或等价布局），后续和返回路径都按 **pt_regs** 访问。
- 栈上最终也是一份 pt_regs（或与 pt_regs 兼容的布局），里面同样包含用户 RSP 等。

### 4.3 小结

| 路径 | 用户 RSP 怎么到栈上 | 是否用 pt_regs |
|------|---------------------|----------------|
| SYSCALL | 经 TSS.sp2 抄到 pt_regs | 是，直接填 pt_regs |
| INT 0x80 | CPU 压中断帧 → 内核整理进 pt_regs | 是，从帧整理成 pt_regs |

两种入口最后都是通过 **pt_regs（或等价结构）** 保存用户 RSP 和其余现场，返回时也从 pt_regs 恢复，再 SYSRET/IRET。

---

## 5. “抄到 pt_regs” 实际就是在栈上建 pt_regs

“抄到 pt_regs” 在实现上就是在**内核栈上**做出一个 pt_regs 的布局，也就是在栈上“摆好”这些寄存器，等价于往栈上写/压栈。

典型做法：

- 先在内核栈上**预留一块空间**（如 `sub rsp, sizeof(pt_regs)` 或等价方式）；
- 再把各寄存器按 **pt_regs** 的成员偏移**存到这块栈内存**里（如 `mov [rsp+pt_regs.rsp], rax` 等）。

因此：

- **int 0x80**：用户 RSP 等是 **CPU 自动压栈**（中断帧），内核再按 pt_regs 布局去解读/整理；
- **syscall**：用户 RSP（从 TSS.sp2 读出）和别的寄存器是**内核代码按 pt_regs 布局写到栈上**。

两种方式最终都是：**栈上有一块内存的布局等于 pt_regs**；“抄到 pt_regs” = 在栈上建 pt_regs，本质都是对栈的写入（可理解为 push/存栈）。

---

## 6. 进内核之后：流程一致

一旦已经：

- 站在内核栈上，并且  
- 用户态现场（RIP、RSP、RFLAGS、通用寄存器等）都保存在 **pt_regs** 或等价的中断帧里，

后面的流程是同一套：

1. 根据系统调用号分发、执行内核里的 syscall 逻辑；
2. 把结果写回 pt_regs / 栈；
3. 用 **SYSRET**（syscall 进的就 SYSRET）或 **IRET**（int 0x80 进的就 IRET）从 pt_regs 恢复用户 RSP/CS 等并返回用户态。

因此：**入口阶段** SYSCALL 与 INT 0x80 不同；**进内核、建好 pt_regs 之后的处理和返回**与 syscall 进内核之后的过程是一样的。

---

## 相关文档

- [X86_TSS_STACK_SWITCH_AND_DESIGN.md](X86_TSS_STACK_SWITCH_AND_DESIGN.md) — TSS、RSP0/sp2、GDT 与成本
- [X86_64_TSS_AND_IST.md](X86_64_TSS_AND_IST.md) — TSS/IST/TR 与栈切换细节
