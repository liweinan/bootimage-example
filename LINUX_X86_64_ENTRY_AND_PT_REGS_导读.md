# 《Linux x86-64：sp0、cpu_current_top_of_stack 与 pt_regs》导读

面向：**已能区分用户态/内核态、大致知道 TSS/IDT/syscall 名词**，希望把 **Intel 手册中的 SYSCALL 行为** 与 **Linux x86-64 入口代码** 对齐阅读的读者。

主文路径：[LINUX_X86_64_ENTRY_AND_PT_REGS.md](./LINUX_X86_64_ENTRY_AND_PT_REGS.md)

---

## 1. 阅读目标自查

读完后应能独立回答：

1. **特权级切换时**，内核栈顶信息来自 **TSS.sp0** 还是 **per-CPU 的 `cpu_current_top_of_stack`**，各自在什么路径被使用。
2. **`SYSCALL` 指令**在硬件上保存/改写了哪些状态，与 **`pt_regs`** 里哪些字段对应。
3. **设备中断**与 **CPU 异常**路径上，`pt_regs` 是 **硬件 IRET 帧** 加 **汇编补齐** 如何得到；**`sync_regs`** 在什么叙事里出现。
4. **`entry_SYSCALL_64`** 与 **`asm_common_interrupt` / `asm_exc_*`** 在「谁压栈、谁切栈」上的差异。

若以上任一条仍模糊，按下面顺序重读主文对应节。

---

## 2. 建议阅读顺序（主文章节）

| 轮次 | 主文章节 | 侧重点 |
|------|-----------|--------|
| 第一轮 | §1、§2 | 先建立 **sp0 ≠ 当前线程内核栈顶** 的心智模型；记住 **`cpu_current_top_of_stack` 在 `__switch_to` 更新**。 |
| 第一轮 | §3 | **`pt_regs` 字段名是 C  ABI**（`ax`/`ip`/`flags`），读内核与读 Intel 助记符时不要混用。 |
| 第二轮 | §4、§8.3 | **SYSCALL**：硬件只保证 RCX/R11 等；**完整 `pt_regs` 靠 `entry_SYSCALL_64`**；对照 SDM（见 §4 本导读）。 |
| 第二轮 | §5 | 需要对照 `calling.h` 时读：**通用寄存器压栈顺序与 `struct pt_regs` 布局一致**。 |
| 第三轮 | §6、§8.1–8.2（外部 IRQ 相关行）、§8 末「IRQ 源码路径」小条 | **IDT → `irq_entries_start` → `asm_common_interrupt`**；**`orig_ax` 与向量号** 的约定。 |
| 第三轮 | §7 | **异常与 CR2 / `regs->ip` 分工**（#PF）；**`error_get_trap_addr`** 叙事（#DE）。 |
| 第四轮 | §8 总览表与出口表 | 把 **syscall / int80 / IRQ / 异常** 收口成一张「进/出**内核**」对照；需要时再进 `entry_64.S` 跟 `error_return`。 |
| 查索引 | §10、参考文件索引 | 用 **`rg`/`read_file`** 在本地内核树验证符号；主文里的路径以你检出的 `linux` 为准。 |

---

## 3. 与 Intel SDM（System Programming Guide）的对照

主文不写满手册细节；下列条目便于你 **打开 Vol 3A** 时知道「该翻哪一节」。

| 主题 | SDM Vol 3A（典型位置） | 与主文的连接 |
|------|-------------------------|--------------|
| SYSCALL/SYSRET 设计意图与模式限制 | §5.8.8 *Fast System Calls in 64-Bit Mode* | 主文 §4、§8.3：**长模式**、**平坦模型**；**兼容/保护模式无 SYSCALL**。 |
| 使能位 | `IA32_EFER.SCE`（§2、Table 2-1） | 内核 boot 阶段会配置 EFER 与 STAR/LSTAR/FMASK（主文默认读者已知「已启用」）。 |
| 目标 RIP / CS / SS / RFLAGS 掩码 | `IA32_LSTAR`、`IA32_STAR`、`IA32_FMASK`，Figure 5-14 | **RCX←次条 RIP、R11←RFLAGS**；**内核入口地址在 LSTAR**（主文 `entry_SYSCALL_64`）。 |
| 栈 | 手册明确 **SYSCALL 不保存 RSP，SYSRET 不恢复 RSP** | 主文 §4：**用户 RSP 进 TSS.sp2 再写入 `pt_regs->sp`**；**切到 `cpu_current_top_of_stack`**。 |
| 虚拟化 | VMX 章节中 *Handling SYSCALL/SYSRET*（目录约 §31.10.4.3） | 仅在写 Hypervisor/嵌套虚拟化时需要；读主文可不读。 |

更细的 **单条指令操作**（异常码、边界条件）以 **SDM Volume 2（指令集卷）** 中 SYSCALL/SYSRET 条目为准。

---

## 4. 内核树阅读提示

- **主文默认内核根**：`/Users/weli/works/linux`（若与你环境不一致，只替换路径，**符号名**仍以同名文件为准）。
- **syscall 入口**：`arch/x86/entry/entry_64.S` 中 `entry_SYSCALL_64`、`syscall_return_via_sysret`、`common_interrupt_return` 一带与主文 §4、§8.2 对照。
- **IRQ stub**：`arch/x86/include/asm/idtentry.h` 中 `irq_entries_start` 与主文 §6.2 一致；**不要**假设 IDT 直接指向一个大写的 `common_interrupt` 手写函数——多为 **宏展开**。
- **版本差异**：主线会调整 FRED、PTI、paranoid 等分支；主文已单列 **FRED** 与 **IST/paranoid** 的提醒，你那棵树的 `#ifdef` 以实际代码为准。

---

## 5. 常见误读（读主文时可对照纠正）

1. **「sp0 = 当前进程内核栈顶」**：主文 §1、§2 说明在常见原生 x86-64 上 **不成立**；**sp0 更像 entry trampoline 锚点**。
2. **「syscall 像中断一样压 IRET 帧」**：主文 §4、§8.3：**硬件不压完整帧**；**`pt_regs` 由入口汇编搭建**。
3. **「设备 IRQ 的向量号在某个专用寄存器」**：主文 §6：**stub `push imm8` 占位，与 `pt_regs.orig_ax` 布局对齐**，C 层再解释为 `u8` 向量号。

---

读完主文 §1–§4 后，若愿意动手验证，可按主文 **§10** 在运行中的系统上看 `kallsyms` 与 `/proc/interrupts`；与静态主文互补。
