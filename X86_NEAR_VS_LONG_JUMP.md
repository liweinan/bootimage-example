# x86 Near Jump 与 Long Jump（及 Long Mode 下 CS 的作用）

本文档说明 near jump 与 long jump（far jump）的区别，以及 long mode 下段寄存器（尤其 CS）仍起什么作用。

> **相关文档**：[LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md) 中压缩内核 startup_32 用 lret 进入 64 位 startup_64 的流程；[X86_CPU_MODES.md](X86_CPU_MODES.md) CPU 模式与长模式。

---

## 1. Near jump 与 Long jump 的区别

### 1.1 Near jump（一般说的 jump）

- **只改 EIP/RIP**，不碰 CS。
- 目标还在**当前代码段**里（同一 CS）。
- **指令举例**：`jmp rel8` / `jmp rel32`（相对）、`jmp r/m`（间接）、`ret`（近返回）、`call rel32`（近调用）。
- **操作**：EIP/RIP = 目标地址。

### 1.2 Long jump（Far jump）

- **同时改 CS 和 EIP/RIP**。
- 目标在**另一个段**，或要用**新的段选择子**（例如从 32 位段换到 64 位段）。
- **指令举例**：`ljmp`（jmp far）、`lcall`、**`lret`**（远返回：从栈弹 EIP 再弹 CS，然后跳到 CS:EIP）。
- **操作**：CS = 新选择子，EIP/RIP = 目标偏移；可能还会**切换模式**（如 32 位 ↔ 64 位）。

### 1.3 对比表

| 对比项 | Jump（near） | Long jump（far） |
|--------|----------------|-------------------|
| 改什么 | 只改 EIP/RIP | 改 CS + EIP/RIP |
| 段 | 仍在当前 CS | 换到新 CS |
| 典型指令 | jmp rel32, ret | ljmp, lret, lcall |
| 典型用途 | 函数内/同段跳转 | 换段、换模式（如进 64 位） |

---

## 2. Long mode 下 CS 仍起什么作用

常说“long mode 下不用段”，指的是**不再用段来做线性地址计算**；CS 仍被加载且仍参与 **CPL** 和 **64/32 模式** 的判定。

### 2.1 Long mode 里“不用段”指什么

- **基址/界限**：CS/DS/ES/SS 的 **base 被强制为 0**，**limit 不起作用**，线性地址 = 有效地址（平坦模型），所以**不再用 CS 做“段基址+偏移”的寻址**。
- 因此“long mode 下不用段” = **不再用段来做地址计算**。

### 2.2 Long mode 里 CS 仍然起什么作用

1. **CPL（当前特权级）**  
   CS 的 RPL = 当前特权级（0=内核，3=用户）。权限检查、栈切换（SS.RPL）等仍然看 CS。

2. **L / D 位（决定 64 位还是 32 位兼容）**  
   代码段描述符中：
   - **L=1**：64 位代码段 → CPU 以 **64 位模式** 取指、执行（默认操作数 32 位、地址 64 位等）。
   - **L=0, D=1**：32 位兼容代码段 → CPU 以 **32 位兼容模式** 运行。

从 32 位兼容模式“跳到 64 位”，就是通过 **lret**（或 ljmp）加载一个 **L=1** 的 CS，CPU 据此切换到 64 位。这里“用”的是 CS 选中的**描述符属性（L/D）**，不是基址/界限。

### 2.3 总结

| 说法 | 含义 |
|------|------|
| “Long mode 下不用 CS” | 不用 CS 做**段基址/段界限**的寻址。 |
| “Long jump 要换 CS” | 换**段选择子**，从而换 **CPL** 和 **L/D**（64 位 vs 32 位兼容）。 |
| Long mode 下 CS 的用途 | 表示**特权级**和 **64/32 模式**，不参与线性地址计算。 |

---

## 3. 与 LINUX_KERNEL_INIT 的衔接

压缩内核 `startup_32` 在设置 CR0.PG 前将 **__KERNEL_CS** 和 **startup_64 的地址** 压栈，然后执行 **lret**：从栈弹出 EIP 和 CS，CS 为 __KERNEL_CS（GDT 中 L=1 的 64 位代码段），故 CPU 进入 64 位并从 startup_64 取指。这是一次 **long jump**（远转移），详见 [LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md) 第二节「startup_32 关键步骤」与「关键步骤说明」表。
