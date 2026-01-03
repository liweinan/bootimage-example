# UEFI 中断处理机制

本文档详细介绍了 UEFI 固件的中断处理机制，包括与 BIOS 中断处理的根本差异。

---

**重要说明：UEFI 与 BIOS 在中断处理机制上有根本性差异。**

**UEFI 中断处理的特点：**

1. **不使用传统 IVT**：
   - UEFI **不使用**实模式下的中断向量表（IVT）
   - UEFI 固件本身在保护模式（32位）或长模式（64位）下运行
   - 使用 **IDT（中断描述符表）**，而不是 IVT

2. **事件驱动机制**：
   - UEFI 采用**事件驱动**的方式处理硬件和软件事件
   - 通过 **EFI_BOOT_SERVICES** 提供事件注册和处理机制
   - 不使用传统的 `INT` 指令调用服务，而是使用**函数调用**

3. **IDT 设置**：
   - UEFI 固件在启动时建立自己的 IDT
   - IDT 位置由 UEFI 固件指定（通过 IDTR 寄存器）
   - 主要用于处理 CPU 异常和硬件中断

4. **中断服务接口**：
   - **不提供软件中断服务**（如 BIOS 的 INT 10h, INT 13h）
   - 使用 **EFI 服务**（函数调用接口）替代传统中断服务
   - 通过 `EFI_SYSTEM_TABLE` 访问各种服务

**UEFI 中断处理流程：**

```
1. UEFI 固件启动（保护模式/长模式）
   ├─ 建立 IDT（中断描述符表）
   ├─ 设置 CPU 异常处理程序
   ├─ 设置硬件中断处理程序（通过 APIC）
   └─ 初始化 EFI_BOOT_SERVICES
    ↓
2. UEFI 驱动程序/应用程序注册事件处理程序
   ├─ 使用 CreateEvent() 创建事件
   ├─ 使用 RegisterProtocolNotify() 注册协议通知
   └─ 使用 SetTimer() 设置定时器事件
    ↓
3. 事件发生时，UEFI 调用注册的处理程序
   ├─ 硬件中断 → APIC → IDT → 中断处理程序 → 事件处理程序
   ├─ 定时器事件 → 定时器中断 → 事件处理程序
   └─ 协议事件 → 协议通知 → 事件处理程序
    ↓
4. 操作系统加载后，调用 ExitBootServices()
   ├─ 退出 UEFI Boot Services
   ├─ 释放 UEFI 控制的内存
   └─ 操作系统接管中断处理
```

**UEFI vs BIOS 中断处理对比：**

| 特性 | BIOS（SeaBIOS） | UEFI |
|------|----------------|------|
| **中断表类型** | IVT（中断向量表，实模式） | IDT（中断描述符表，保护模式/长模式） |
| **中断表位置** | 固定地址 `0x0000:0000` | 由 IDTR 寄存器指定（不固定） |
| **运行模式** | 实模式（16位） | 保护模式（32位）或长模式（64位） |
| **软件中断服务** | ✅ 提供（INT 10h, 13h, 15h 等） | ❌ 不提供（使用 EFI 服务） |
| **服务调用方式** | `INT` 指令（软件中断） | 函数调用（通过 EFI_SYSTEM_TABLE） |
| **硬件中断处理** | 通过 PIC + IVT | 通过 APIC + IDT |
| **事件处理机制** | 中断驱动 | 事件驱动（CreateEvent, RegisterProtocolNotify） |
| **中断处理程序设置** | `ivt_init()` 设置 IVT 条目 | UEFI 固件内部设置 IDT |

**UEFI 中断处理的关键接口：**

```c
// UEFI Boot Services 提供的事件处理接口
EFI_BOOT_SERVICES {
    // 创建事件
    EFI_CREATE_EVENT (
        IN UINT32 Type,              // 事件类型
        IN EFI_TPL NotifyTpl,        // 通知优先级
        IN EFI_EVENT_NOTIFY NotifyFunction,  // 通知函数
        IN VOID *NotifyContext,      // 通知上下文
        OUT EFI_EVENT *Event         // 返回的事件句柄
    );
    
    // 注册协议通知
    EFI_REGISTER_PROTOCOL_NOTIFY (
        IN EFI_GUID *Protocol,       // 协议 GUID
        IN EFI_EVENT_NOTIFY Event,   // 事件通知函数
        OUT VOID **Registration      // 注册句柄
    );
    
    // 设置定时器
    EFI_SET_TIMER (
        IN EFI_EVENT Event,          // 事件句柄
        IN EFI_TIMER_DELAY Type,     // 定时器类型
        IN UINT64 TriggerTime       // 触发时间
    );
}
```

**UEFI 中断处理示例：**

```c
// UEFI 驱动程序注册硬件中断处理程序
EFI_STATUS
MyDriverInterruptHandler (
    IN EFI_EXCEPTION_TYPE InterruptType,
    IN EFI_SYSTEM_CONTEXT SystemContext
)
{
    // 处理硬件中断
    // ...
    return EFI_SUCCESS;
}

// 注册中断处理程序（通过 UEFI 固件）
// UEFI 固件内部会设置 IDT 条目，指向这个处理程序
```

**关键点总结：**

1. **UEFI 不使用 IVT**：UEFI 在保护模式/长模式下运行，使用 IDT 而不是 IVT
2. **事件驱动**：UEFI 使用事件驱动机制，而不是传统的中断驱动
3. **函数调用**：UEFI 使用函数调用（EFI 服务）而不是 `INT` 指令
4. **固件管理**：UEFI 固件内部管理 IDT 的设置，应用程序通过 EFI 服务访问
5. **操作系统接管**：操作系统加载后调用 `ExitBootServices()` 退出 UEFI 环境，接管中断处理

**与 BIOS 的根本差异：**

- **BIOS**：实模式 → IVT → `INT` 指令 → 中断服务程序
- **UEFI**：保护模式/长模式 → IDT → 事件驱动 → EFI 服务（函数调用）

UEFI 的设计更加现代化，提供了更好的抽象和模块化，但不再提供传统的软件中断服务（如 INT 10h, INT 13h）。
