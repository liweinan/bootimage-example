# SeaBIOS entry_13_official 实现详细分析

本文档详细分析 SeaBIOS 中 `entry_13_official` 函数的完整实现，包括从中断入口到磁盘操作完成的整个流程。

## 概述

`entry_13_official` 是 SeaBIOS 中 INT 13h（磁盘服务）中断的入口点。当程序调用 `int 0x13` 时，CPU 会跳转到 IVT 中向量 0x13 指向的地址，即 `entry_13_official`。

## 源代码位置

- **入口点定义**：`seabios/src/romlayout.S:606-608`
- **实际处理函数**：`seabios/src/disk.c:740-780`
- **磁盘操作分发**：`seabios/src/disk.c:620-655`
- **底层磁盘操作**：`seabios/src/block.c:620-639`

## 完整调用链

```
用户程序调用 int 0x13
    ↓
IVT[0x13] → entry_13_official (romlayout.S:606)
    ↓
entry_13 (romlayout.S:566, 通过 IRQ_ENTRY_ARG 13 宏生成)
    ↓
irqentry_arg (romlayout.S:531)
    ↓
handle_13 (disk.c:740)
    ↓
handle_legacy_disk (disk.c:701) 或 CD 模拟处理
    ↓
disk_13 (disk.c:621) 或 floppy_13 (disk.c:659)
    ↓
disk_13XX (根据 AH 功能号分发到具体函数)
    ├─ disk_1302 (读扇区)
    ├─ disk_1303 (写扇区)
    ├─ disk_1308 (获取磁盘参数)
    └─ ... (其他功能)
    ↓
basic_access (disk.c:120) 或 extended_access (disk.c:163)
    ↓
send_disk_op (disk.c:107)
    ↓
process_op (block.c:620)
    ↓
process_op_32 (block.c:572) 或 process_op_16 (block.c:601)
    ↓
具体磁盘驱动处理函数
    ├─ ata_process_op (ATA 硬盘)
    ├─ ahci_process_op (AHCI 硬盘)
    ├─ floppy_process_op (软盘)
    ├─ virtio_blk_process_op (VirtIO 块设备)
    └─ ... (其他驱动)
```

## 详细实现分析

### 1. 入口点：entry_13_official

**位置**：`seabios/src/romlayout.S:606-608`

```asm
ORG 0xe3fe
.global entry_13_official
entry_13_official:
    jmp entry_13
```

**说明**：
- `entry_13_official` 位于固定地址 `0xe3fe`（这是为了兼容某些旧软件）
- 它只是一个跳转指令，跳转到 `entry_13`
- 使用 `ORG 0xe3fe` 确保该函数位于 BIOS ROM 的特定位置

### 2. entry_13 的生成

**位置**：`seabios/src/romlayout.S:566`

```asm
DECL_IRQ_ENTRY_ARG 13
```

**宏展开**：

```asm
.macro DECL_IRQ_ENTRY_ARG num
    DECLFUNC entry_\num
    IRQ_ENTRY_ARG \num
.endm

.macro IRQ_ENTRY_ARG num
    .global entry_\num
    entry_\num:
    pushl $ handle_\num
#if CONFIG_ENTRY_EXTRASTACK
    jmp irqentry_arg_extrastack
#else
    jmp irqentry_arg
#endif
.endm
```

**展开后的代码**：

```asm
.section .text.asm.entry_13
.global entry_13
entry_13:
    pushl $ handle_13        // 将 handle_13 函数地址压入栈
    jmp irqentry_arg         // 跳转到通用中断入口处理
```

**说明**：
- `DECLFUNC entry_13` 声明函数并设置代码段
- `IRQ_ENTRY_ARG 13` 生成实际的入口代码
- 将 `handle_13` 函数地址压入栈，然后跳转到 `irqentry_arg`

### 3. irqentry_arg：通用中断入口处理

**位置**：`seabios/src/romlayout.S:531-533`

```asm
DECLFUNC irqentry_arg
irqentry_arg:
    ENTRY_ARG_ST
    iretw
```

**ENTRY_ARG_ST 宏展开**（来自 `entryfuncs.S:117-138`）：

```asm
.macro ENTRY_ARG_ST
    cli                      // 禁用中断
    cld                      // 清除方向标志
    pushl %ecx
    pushl %edx
    pushl %ebx
    pushl %ebp
    pushl %esi
    pushl %edi
    pushw %es
    pushw %ds
    movw %ss, %cx            // 将 SS 复制到 DS
    movw %cx, %ds
    movl %esp, %ebx          // 备份 ESP
    movzwl %sp, %esp         // 清除 ESP 高16位（实模式限制）
    movl 28(%esp), %ecx      // 从栈中获取调用函数（handle_13）
    movl %eax, 28(%esp)      // 保存 EAX
    movl %esp, %eax          // EAX = 指向 struct bregs 的指针
    calll *%ecx              // 调用 handle_13(regs)
    movl %ebx, %esp          // 恢复 ESP
    POPBREGS                 // 恢复所有寄存器
.endm
```

**说明**：
- **保存寄存器**：保存所有可能被 C 代码修改的寄存器
- **设置 DS**：将 DS 设置为 SS，以便访问栈上的数据
- **准备参数**：将栈指针（指向保存的寄存器）作为参数传递给 C 函数
- **调用 C 函数**：从栈中获取 `handle_13` 地址并调用
- **恢复寄存器**：从 `struct bregs` 恢复所有寄存器
- **返回**：使用 `iretw` 返回到调用者

### 4. handle_13：主处理函数

**位置**：`seabios/src/disk.c:740-780`

```c
void VISIBLE16
handle_13(struct bregs *regs)
{
    debug_enter(regs, DEBUG_HDL_13);
    u8 extdrive = regs->dl;

    // CD 模拟处理（如果启用）
    if (CONFIG_CDROM_EMU) {
        if (regs->ah == 0x4b) {
            cdemu_134b(regs);
            return;
        }
        if (GET_LOW(CDEmu.media)) {
            u8 emudrive = GET_LOW(CDEmu.emulated_drive);
            if (extdrive == emudrive) {
                // 访问模拟驱动器
                struct drive_s *cdemu_gf = GET_GLOBAL(cdemu_drive_gf);
                if (regs->ah > 0x16) {
                    // 只支持旧式命令
                    disk_13XX(regs, cdemu_gf);
                    return;
                }
                disk_13(regs, cdemu_gf);
                return;
            }
            if (extdrive < EXTSTART_CD && ((emudrive ^ extdrive) & 0x80) == 0)
                // 调整驱动器号以为模拟驱动器腾出空间
                extdrive--;
        }
    }
    
    // 处理传统磁盘访问
    handle_legacy_disk(regs, extdrive);
}
```

**功能**：
1. **调试支持**：记录中断调用（如果启用调试）
2. **CD 模拟**：如果启用了 CD 模拟，处理模拟驱动器的访问
3. **驱动器号处理**：从 `regs->dl` 获取驱动器号
4. **分发处理**：调用 `handle_legacy_disk` 处理实际的磁盘访问

### 5. handle_legacy_disk：驱动器类型识别

**位置**：`seabios/src/disk.c:701-730`

```c
static void
handle_legacy_disk(struct bregs *regs, u8 extdrive)
{
    if (! CONFIG_DRIVES) {
        disk_ret(regs, DISK_RET_EPARAM);
        return;
    }

    // 软盘处理（驱动器号 < 0x80）
    if (extdrive < EXTSTART_HD) {
        struct drive_s *drive_fl = getDrive(EXTTYPE_FLOPPY, extdrive);
        if (!drive_fl)
            goto fail;
        floppy_13(regs, drive_fl);
        return;
    }

    // 硬盘或 CD 处理
    struct drive_s *drive_fl;
    if (extdrive >= EXTSTART_CD)
        drive_fl = getDrive(EXTTYPE_CD, extdrive - EXTSTART_CD);
    else
        drive_fl = getDrive(EXTTYPE_HD, extdrive - EXTSTART_HD);
    if (!drive_fl)
        goto fail;
    disk_13(regs, drive_fl);
    return;

fail:
    disk_ret(regs, DISK_RET_EPARAM);
}
```

**功能**：
1. **驱动器类型判断**：
   - `extdrive < 0x80`：软盘（EXTTYPE_FLOPPY）
   - `0x80 <= extdrive < EXTSTART_CD`：硬盘（EXTTYPE_HD）
   - `extdrive >= EXTSTART_CD`：CD-ROM（EXTTYPE_CD）
2. **获取驱动器结构**：通过 `getDrive()` 获取对应的 `drive_s` 结构
3. **分发处理**：
   - 软盘 → `floppy_13()`
   - 硬盘/CD → `disk_13()`

### 6. disk_13：功能号分发

**位置**：`seabios/src/disk.c:621-656`

```c
static void
disk_13(struct bregs *regs, struct drive_s *drive_fl)
{
    // 清除完成标志
    SET_BDA(disk_interrupt_flag, 0);

    switch (regs->ah) {
    case 0x00: disk_1300(regs, drive_fl); break;  // 复位磁盘
    case 0x01: disk_1301(regs, drive_fl); break;  // 读取磁盘状态
    case 0x02: disk_1302(regs, drive_fl); break;  // 读扇区（CHS）
    case 0x03: disk_1303(regs, drive_fl); break;  // 写扇区（CHS）
    case 0x04: disk_1304(regs, drive_fl); break;  // 验证扇区
    case 0x05: disk_1305(regs, drive_fl); break;  // 格式化磁道
    case 0x08: disk_1308(regs, drive_fl); break;  // 获取磁盘参数
    case 0x09: disk_1309(regs, drive_fl); break;  // 初始化驱动器对
    case 0x0c: disk_130c(regs, drive_fl); break;  // 寻道
    case 0x0d: disk_130d(regs, drive_fl); break;  // 复位硬盘
    case 0x10: disk_1310(regs, drive_fl); break;  // 检查驱动器就绪
    case 0x11: disk_1311(regs, drive_fl); break;  // 重新校准
    case 0x14: disk_1314(regs, drive_fl); break;  // 控制器诊断
    case 0x15: disk_1315(regs, drive_fl); break;  // 获取磁盘类型
    case 0x16: disk_1316(regs, drive_fl); break;  // 检测磁盘变化
    case 0x41: disk_1341(regs, drive_fl); break;  // 检查扩展功能
    case 0x42: disk_1342(regs, drive_fl); break;  // 扩展读（LBA）
    case 0x43: disk_1343(regs, drive_fl); break;  // 扩展写（LBA）
    case 0x44: disk_1344(regs, drive_fl); break;  // 扩展验证（LBA）
    case 0x45: disk_1345(regs, drive_fl); break;  // 锁定/解锁驱动器
    case 0x46: disk_1346(regs, drive_fl); break;  // 弹出媒体
    case 0x47: disk_1347(regs, drive_fl); break;  // 扩展寻道
    case 0x48: disk_1348(regs, drive_fl); break;  // 获取扩展磁盘参数
    case 0x49: disk_1349(regs, drive_fl); break;  // 获取媒体类型
    case 0x4e: disk_134e(regs, drive_fl); break;  // 设置硬件配置
    default:   disk_13XX(regs, drive_fl); break;   // 不支持的功能
    }
}
```

**功能**：
- 根据 `regs->ah`（功能号）分发到对应的处理函数
- 最常用的功能：
  - **0x02**：读扇区（CHS 模式）
  - **0x42**：扩展读（LBA 模式）

### 7. disk_1302：读扇区实现（CHS 模式）

**位置**：`seabios/src/disk.c:226-229`

```c
// read disk sectors
static void
disk_1302(struct bregs *regs, struct drive_s *drive_fl)
{
    basic_access(regs, drive_fl, CMD_READ);
}
```

**说明**：
- `disk_1302` 是 INT 13h AH=0x02（读扇区）的处理函数
- 调用 `basic_access()` 执行实际的读取操作

### 8. basic_access：CHS 到 LBA 转换

**位置**：`seabios/src/disk.c:120-159`

```c
// Perform read/write/verify using old-style chs accesses
static void noinline
basic_access(struct bregs *regs, struct drive_s *drive_fl, u16 command)
{
    struct disk_op_s dop;
    dop.drive_fl = drive_fl;
    dop.command = command;

    // 从寄存器中提取 CHS 参数
    u8 count = regs->al;                    // 扇区数
    u16 cylinder = regs->ch | ((((u16)regs->cl) << 2) & 0x300);  // 柱面号
    u16 sector = regs->cl & 0x3f;           // 扇区号（低6位）
    u16 head = regs->dh;                    // 磁头号

    // 参数验证
    if (count > 128 || count == 0 || sector == 0) {
        warn_invalid(regs);
        disk_ret(regs, DISK_RET_EPARAM);
        return;
    }
    dop.count = count;

    // 获取驱动器的逻辑 CHS 参数
    struct chs_s chs = getLCHS(drive_fl);
    u16 nlc=chs.cylinder, nlh=chs.head, nls=chs.sector;

    // 检查 CHS 参数是否在有效范围内
    if (cylinder >= nlc || head >= nlh || sector > nls) {
        warn_invalid(regs);
        disk_ret(regs, DISK_RET_EPARAM);
        return;
    }

    // CHS 到 LBA 转换
    dop.lba = (((((u32)cylinder * (u32)nlh) + (u32)head) * (u32)nls)
               + (u32)sector - 1);

    // 计算缓冲区地址（ES:BX → 物理地址）
    dop.buf_fl = MAKE_FLATPTR(regs->es, regs->bx);

    // 执行磁盘操作
    int status = send_disk_op(&dop);

    // 更新实际传输的扇区数
    regs->al = dop.count;

    disk_ret(regs, status);
}
```

**关键步骤**：

1. **参数提取**：
   - `AL`：扇区数
   - `CH`：柱面号低8位
   - `CL`：柱面号高2位（位6-7）+ 扇区号（位0-5）
   - `DH`：磁头号
   - `ES:BX`：目标缓冲区地址

2. **CHS 到 LBA 转换**：
   ```
   LBA = (cylinder × heads_per_cylinder + head) × sectors_per_track + sector - 1
   ```

3. **地址转换**：
   ```
   物理地址 = ES × 16 + BX
   ```

4. **执行操作**：调用 `send_disk_op()` 执行实际的磁盘 I/O

### 9. send_disk_op：磁盘操作分发

**位置**：`seabios/src/disk.c:107-116`

```c
// Execute a "disk_op_s" request (using the extra 16bit stack).
static int
send_disk_op(struct disk_op_s *op)
{
    ASSERT16();
    if (! CONFIG_DRIVES)
        return -1;
    if (!CONFIG_ENTRY_EXTRASTACK)
        // 跳转到额外栈
        return stack_hop(__send_disk_op, op, GET_SEG(SS));
    return process_op(op);
}
```

**说明**：
- 如果启用了额外栈（`CONFIG_ENTRY_EXTRASTACK`），直接调用 `process_op()`
- 否则，使用 `stack_hop()` 切换到额外栈再调用

### 10. process_op：磁盘操作核心处理

**位置**：`seabios/src/block.c:620-639`

```c
// Execute a disk_op_s request.
int
process_op(struct disk_op_s *op)
{
    dprintf(DEBUG_HDL_13, "disk_op d=%p lba=%d buf=%p count=%d cmd=%d\n"
            , op->drive_fl, (u32)op->lba, op->buf_fl
            , op->count, op->command);

    int ret, origcount = op->count;
    
    // 检查操作大小（不能超过64KB）
    if (origcount * GET_FLATPTR(op->drive_fl->blksize) > 64*1024) {
        op->count = 0;
        return DISK_RET_EBOUNDARY;
    }
    
    // 根据运行模式选择处理函数
    if (MODESEGMENT)
        ret = process_op_16(op);  // 16位模式
    else
        ret = process_op_32(op);  // 32位模式
    
    // 如果出错且计数未改变，假设没有数据传输
    if (ret && op->count == origcount)
        op->count = 0;
    return ret;
}
```

**功能**：
1. **大小检查**：确保操作不超过 64KB 限制
2. **模式选择**：根据当前运行模式（16位/32位）选择处理函数
3. **错误处理**：如果出错，更新传输计数

### 11. process_op_32 / process_op_16：驱动分发

**位置**：`seabios/src/block.c:572-616`

```c
// Command dispatch for disk drivers that only run in 32bit mode
int VISIBLE32FLAT
process_op_32(struct disk_op_s *op)
{
    ASSERT32FLAT();
    switch (op->drive_fl->type) {
    case DTYPE_VIRTIO_BLK:
        return virtio_blk_process_op(op);
    case DTYPE_AHCI:
        return ahci_process_op(op);
    case DTYPE_AHCI_ATAPI:
        return ahci_atapi_process_op(op);
    case DTYPE_SDCARD:
        return sdcard_process_op(op);
    case DTYPE_USB_32:
        return usb_process_op(op);
    case DTYPE_UAS_32:
        return uas_process_op(op);
    case DTYPE_VIRTIO_SCSI:
        return virtio_scsi_process_op(op);
    case DTYPE_PVSCSI:
        return pvscsi_process_op(op);
    case DTYPE_NVME:
        return nvme_process_op(op);
    default:
        return process_op_both(op);
    }
}

// Command dispatch for disk drivers that only run in 16bit mode
static int
process_op_16(struct disk_op_s *op)
{
    ASSERT16();
    switch (GET_FLATPTR(op->drive_fl->type)) {
    case DTYPE_FLOPPY:
        return floppy_process_op(op);
    case DTYPE_ATA:
        return ata_process_op(op);
    case DTYPE_RAMDISK:
        return ramdisk_process_op(op);
    case DTYPE_CDEMU:
        return cdemu_process_op(op);
    default:
        return process_op_both(op);
    }
}
```

**功能**：
- 根据驱动器类型（`drive_fl->type`）分发到对应的驱动处理函数
- **32位模式驱动**：VirtIO、AHCI、USB、NVMe 等现代接口
- **16位模式驱动**：ATA、软盘等传统接口

### 12. 底层驱动处理（以 ATA 为例）

**位置**：`seabios/src/hw/ata.c:556-576`

```c
// 16bit command demuxer for ATA harddrives.
int
ata_process_op(struct disk_op_s *op)
{
    if (!CONFIG_ATA)
        return 0;

    struct atadrive_s *adrive_gf = container_of(
        op->drive_fl, struct atadrive_s, drive);
    switch (op->command) {
    case CMD_READ:
        return ata_readwrite(op, 0);      // 读操作
    case CMD_WRITE:
        return ata_readwrite(op, 1);     // 写操作
    case CMD_RESET:
        ata_reset(adrive_gf);            // 复位驱动器
        return DISK_RET_SUCCESS;
    case CMD_ISREADY:
        return isready(adrive_gf);       // 检查就绪状态
    default:
        return default_process_op(op);   // 其他命令
    }
}
```

**ata_readwrite 实现**（`seabios/src/hw/ata.c:507-552`）：

```c
ata_readwrite(struct disk_op_s *op, int iswrite)
{
    u64 lba = op->lba;

    // 尝试使用 DMA，如果失败则使用 PIO
    int usepio = ata_try_dma(op, iswrite, DISK_SECTOR_SIZE);

    struct ata_pio_command cmd;
    memset(&cmd, 0, sizeof(cmd));

    // 判断是否使用扩展 LBA（48位）
    if (op->count >= (1<<8) || lba + op->count >= (1<<28)) {
        // 48位 LBA（扩展命令）
        cmd.sector_count2 = op->count >> 8;
        cmd.lba_low2 = lba >> 24;
        cmd.lba_mid2 = lba >> 32;
        cmd.lba_high2 = lba >> 40;
        lba &= 0xffffff;

        if (usepio)
            cmd.command = (iswrite ? ATA_CMD_WRITE_SECTORS_EXT
                           : ATA_CMD_READ_SECTORS_EXT);
        else
            cmd.command = (iswrite ? ATA_CMD_WRITE_DMA_EXT
                           : ATA_CMD_READ_DMA_EXT);
    } else {
        // 28位 LBA（标准命令）
        if (usepio)
            cmd.command = (iswrite ? ATA_CMD_WRITE_SECTORS
                           : ATA_CMD_READ_SECTORS);
        else
            cmd.command = (iswrite ? ATA_CMD_WRITE_DMA
                           : ATA_CMD_READ_DMA);
    }

    // 设置 LBA 地址和扇区数
    cmd.sector_count = op->count;
    cmd.lba_low = lba;
    cmd.lba_mid = lba >> 8;
    cmd.lba_high = lba >> 16;
    cmd.device = ((lba >> 24) & 0xf) | ATA_CB_DH_LBA;

    // 执行命令
    int ret;
    if (usepio)
        ret = ata_pio_cmd_data(op, iswrite, &cmd);  // PIO 模式
    else
        ret = ata_dma_cmd_data(op, &cmd);            // DMA 模式
    
    if (ret)
        return DISK_RET_EBADTRACK;
    return DISK_RET_SUCCESS;
}
```

**ATA PIO 数据传输**（`seabios/src/hw/ata.c:276-336`）：

```c
// Transfer 'op->count' blocks (of 'blocksize' bytes) to/from drive
static int
ata_pio_transfer(struct disk_op_s *op, int iswrite, int blocksize)
{
    struct atadrive_s *adrive_gf = container_of(
        op->drive_fl, struct atadrive_s, drive);
    struct ata_channel_s *chan_gf = GET_GLOBALFLAT(adrive_gf->chan_gf);
    u16 iobase1 = GET_GLOBALFLAT(chan_gf->iobase1);
    u16 iobase2 = GET_GLOBALFLAT(chan_gf->iobase2);
    int count = op->count;
    void *buf_fl = op->buf_fl;
    int status;
    
    for (;;) {
        if (iswrite) {
            // 写入数据到控制器
            if (CONFIG_ATA_PIO32)
                outsl_fl(iobase1, buf_fl, blocksize / 4);  // 32位 PIO
            else
                outsw_fl(iobase1, buf_fl, blocksize / 2); // 16位 PIO
        } else {
            // 从控制器读取数据
            if (CONFIG_ATA_PIO32)
                insl_fl(iobase1, buf_fl, blocksize / 4);  // 32位 PIO
            else
                insw_fl(iobase1, buf_fl, blocksize / 2);  // 16位 PIO
        }
        buf_fl += blocksize;

        // 等待控制器就绪
        status = pause_await_not_bsy(iobase1, iobase2);
        if (status < 0) {
            op->count -= count;
            return status;
        }

        count--;
        if (!count)
            break;
            
        // 检查状态，确保还有更多扇区要传输
        status &= (ATA_CB_STAT_BSY | ATA_CB_STAT_DRQ | ATA_CB_STAT_ERR);
        if (status != ATA_CB_STAT_DRQ) {
            op->count -= count;
            return -6;
        }
    }

    return 0;
}
```

#### 内存地址和磁盘数据传输机制

**1. 内存地址的来源**

在 `ata_pio_transfer` 中使用的 `buf_fl` 内存地址来源于用户程序通过 INT 13h 调用时指定的 ES:BX 寄存器：

```c
// seabios/src/disk.c:152
dop.buf_fl = MAKE_FLATPTR(regs->es, regs->bx);
```

**地址转换过程**：
- **用户程序调用**：`INT 13h AH=0x02` 时，设置 `ES:BX` 指向目标缓冲区（例如 `ES=0x07C0, BX=0x0000` → 物理地址 `0x07C00`）
- **地址转换**：`MAKE_FLATPTR(regs->es, regs->bx)` 将段地址:偏移地址转换为平坦地址（flat pointer）
- **传递到驱动**：`buf_fl` 作为 `disk_op_s` 结构的一部分，传递到 `ata_pio_transfer`

**示例**：
- 如果用户程序设置 `ES=0x07C0, BX=0x0000`，则 `buf_fl = 0x07C00`
- 如果用户程序设置 `ES=0x1000, BX=0x0000`，则 `buf_fl = 0x10000`

**2. 磁盘数据如何传输到内存（PIO 模式）**

**重要概念**：磁盘数据**不是映射**到内存地址，而是通过 **I/O 端口**（Port I/O）**传输**到内存。

**传输流程**：

```
磁盘扇区 → ATA 控制器内部缓冲区 → I/O 端口（ATA_CB_DATA） → CPU 寄存器 → 内存缓冲区
```

**详细步骤**：

1. **ATA 命令发送**：
   ```c
   // 发送 READ SECTORS 命令到 ATA 控制器
   send_cmd(adrive_gf, &cmd);
   // 命令写入 I/O 端口：iobase1 + ATA_CB_CMD (0x1F7)
   ```

2. **等待数据就绪**：
   ```c
   // 等待 ATA 控制器将磁盘数据读取到内部缓冲区
   ata_wait_data(iobase1);
   // 检查状态寄存器 (iobase1 + ATA_CB_STAT) 的 DRQ 位
   ```

3. **PIO 数据传输**（读操作）：
   ```c
   // 从 I/O 端口读取数据到内存
   insl_fl(iobase1, buf_fl, blocksize / 4);
   // 或
   insw_fl(iobase1, buf_fl, blocksize / 2);
   ```

**底层实现**（`seabios/src/x86.h:179-185`）：

```c
// 16位 PIO 读：从 I/O 端口读取到内存
static inline void insw(u16 port, u16 *data, u32 count) {
    asm volatile("rep insw (%%dx), %%es:(%%edi)"
                 : "+c"(count), "+D"(data) : "d"(port) : "memory");
}

// 32位 PIO 读：从 I/O 端口读取到内存
static inline void insl(u16 port, u32 *data, u32 count) {
    asm volatile("rep insl (%%dx), %%es:(%%edi)"
                 : "+c"(count), "+D"(data) : "d"(port) : "memory");
}
```

**汇编指令说明**：
- `rep insw`：重复执行 `insw` 指令，从端口 `DX` 读取 16 位数据，写入 `ES:EDI` 指向的内存
- `rep insl`：重复执行 `insl` 指令，从端口 `DX` 读取 32 位数据，写入 `ES:EDI` 指向的内存
- `port`：ATA 数据寄存器端口地址（`iobase1 + ATA_CB_DATA = 0x1F0`）
- `data`：目标内存地址（`buf_fl`）
- `count`：传输次数（`blocksize / 2` 或 `blocksize / 4`）

**写操作流程**（`outsl_fl` / `outsw_fl`）：

```c
// 从内存写入数据到 I/O 端口
outsl_fl(iobase1, buf_fl, blocksize / 4);
// 或
outsw_fl(iobase1, buf_fl, blocksize / 2);
```

**底层实现**（`seabios/src/x86.h:192-199`）：

```c
// 16位 PIO 写：从内存写入到 I/O 端口
static inline void outsw(u16 port, u16 *data, u32 count) {
    asm volatile("rep outsw %%es:(%%esi), (%%dx)"
                 : "+c"(count), "+S"(data) : "d"(port) : "memory");
}

// 32位 PIO 写：从内存写入到 I/O 端口
static inline void outsl(u16 port, u32 *data, u32 count) {
    asm volatile("rep outsl %%es:(%%esi), (%%dx)"
                 : "+c"(count), "+S"(data) : "d"(port) : "memory");
}
```

**3. I/O 端口地址映射**

**ATA 控制器 I/O 端口**（Primary Channel）：
- **数据寄存器**：`0x1F0` (`iobase1 + ATA_CB_DATA`)
- **状态寄存器**：`0x1F7` (`iobase1 + ATA_CB_STAT`)
- **命令寄存器**：`0x1F7` (`iobase1 + ATA_CB_CMD`)

**地址空间**：
- **内存地址空间**：CPU 通过内存总线访问 RAM（例如 `0x07C00`）
- **I/O 地址空间**：CPU 通过 I/O 总线访问设备寄存器（例如 `0x1F0`）
- **两者独立**：I/O 端口地址和内存地址在不同的地址空间中

**4. 完整数据传输示例**

假设用户程序调用 `INT 13h AH=0x02` 读取 1 个扇区到 `0x07C00`：

```
1. 用户程序：设置 ES=0x07C0, BX=0x0000, 调用 INT 13h
2. BIOS：basic_access() 转换 ES:BX → buf_fl = 0x07C00
3. BIOS：send_cmd() 发送 READ SECTORS 命令到 0x1F7
4. ATA 控制器：从磁盘读取扇区数据到内部缓冲区
5. ATA 控制器：设置 DRQ 位，表示数据就绪
6. BIOS：ata_wait_data() 检测到 DRQ 位
7. BIOS：insw_fl(0x1F0, 0x07C00, 256) 执行 rep insw
   - 从 I/O 端口 0x1F0 读取 256 次（每次 16 位 = 512 字节）
   - 写入内存地址 0x07C00-0x07DFF
8. 完成：磁盘数据已传输到内存 0x07C00
```

**5. 与内存映射 I/O (MMIO) 的区别**

- **PIO（Port I/O）**：使用独立的 I/O 地址空间，通过 `in/out` 指令访问
- **MMIO（Memory-Mapped I/O）**：设备寄存器映射到内存地址空间，通过普通内存访问指令访问

ATA 控制器使用 **PIO**，而不是 MMIO。

**ATA 命令发送**（`seabios/src/hw/ata.c:190-208`）：

```c
// Send an ata command to the controller
static int
send_cmd(struct atadrive_s *adrive_gf, struct ata_pio_command *cmd)
{
    struct ata_channel_s *chan_gf = GET_GLOBALFLAT(adrive_gf->chan_gf);
    u8 slave = GET_GLOBALFLAT(adrive_gf->slave);
    u16 iobase1 = GET_GLOBALFLAT(chan_gf->iobase1);
    u16 iobase2 = GET_GLOBALFLAT(chan_gf->iobase2);

    // 等待驱动器就绪
    int ret = await_rdy(iobase1);
    if (ret < 0)
        return ret;

    // 选择驱动器（主/从）
    outb((slave ? ATA_CB_DH_DEV1 : ATA_CB_DH_DEV0) | ATA_CB_DH_LBA,
         iobase1 + ATA_CB_DH);

    // 写入命令参数到 ATA 寄存器
    outb(cmd->feature, iobase1 + ATA_CB_FR);      // Feature 寄存器
    outb(cmd->sector_count, iobase1 + ATA_CB_SC); // 扇区数
    outb(cmd->lba_low, iobase1 + ATA_CB_SN);      // LBA 低8位
    outb(cmd->lba_mid, iobase1 + ATA_CB_CL);      // LBA 中8位
    outb(cmd->lba_high, iobase1 + ATA_CB_CH);     // LBA 高8位
    outb(cmd->command, iobase1 + ATA_CB_CMD);     // 命令寄存器

    return 0;
}
```

**ATA 驱动处理流程**：

1. **命令分发**：`ata_process_op()` 根据命令类型分发
2. **LBA 地址处理**：`ata_readwrite()` 处理 28位或 48位 LBA
3. **传输模式选择**：尝试 DMA，失败则使用 PIO
4. **命令发送**：`send_cmd()` 将命令写入 ATA 寄存器
5. **数据传输**：
   - **PIO 模式**：通过 `inw/outw` 或 `inl/outl` 逐字/双字传输
   - **DMA 模式**：通过 DMA 控制器自动传输
6. **状态检查**：等待驱动器就绪，检查错误标志

## 数据结构

### struct bregs：寄存器结构

```c
// seabios/src/bregs.h
struct bregs {
    u32 edi;
    u32 esi;
    u32 ebp;
    u32 esp;
    u32 ebx;
    u32 edx;
    u32 ecx;
    u32 eax;
    u16 ds;
    u16 es;
    u16 flags;
};
```

**说明**：
- 保存所有通用寄存器和段寄存器
- 用于在汇编和 C 代码之间传递参数

### struct disk_op_s：磁盘操作结构

```c
// seabios/src/block.h
struct disk_op_s {
    struct drive_s *drive_fl;  // 驱动器结构指针
    u64 lba;                   // 逻辑块地址（LBA）
    void *buf_fl;              // 缓冲区地址（平坦地址）
    u16 count;                 // 扇区数
    u8 command;                // 命令（CMD_READ, CMD_WRITE 等）
};
```

**说明**：
- 封装磁盘操作的所有参数
- 在函数调用链中传递

### struct drive_s：驱动器结构

```c
// seabios/src/block.h
struct drive_s {
    u8 type;                   // 驱动器类型（DTYPE_ATA, DTYPE_AHCI 等）
    u8 cntl_id;                // 控制器 ID
    u16 blksize;               // 块大小（通常为512）
    u64 sectors;               // 总扇区数
    struct chs_s pchs;         // 物理 CHS
    struct chs_s lchs;         // 逻辑 CHS
    u8 translation;            // 转换模式
    // ... 其他字段
};
```

## 关键宏和函数

### ENTRY_ARG_ST 宏

**位置**：`seabios/src/entryfuncs.S:117-138`

**功能**：
- 保存所有寄存器到栈
- 设置 DS 段寄存器
- 调用 C 函数（从栈中获取函数地址）
- 恢复所有寄存器

### MAKE_FLATPTR 宏

**功能**：将段:偏移地址转换为平坦地址（32位）

```c
#define MAKE_FLATPTR(seg, off) \
    ((void*)(((u32)(seg) << 4) + (u32)(off)))
```

**示例**：
- `ES:BX = 0x07C0:0x0000` → `0x7C00`

### disk_ret 宏

**位置**：`seabios/src/disk.c:56-57`

```c
#define disk_ret(regs, code) \
    __disk_ret((regs), (code) | (__LINE__ << 8), __func__)
```

**功能**：
- 设置返回状态码
- 更新 BDA 中的磁盘状态
- 设置进位标志（CF）表示成功/失败

## 执行流程示例：读取 MBR

以下是一个完整的示例，展示如何读取 MBR（磁盘扇区 0）到内存地址 0x7C00：

```
1. 用户程序调用：
   mov ah, 0x02        // 功能：读扇区
   mov al, 1           // 读取1个扇区
   mov dl, 0x80        // 驱动器：第一块硬盘
   mov dh, 0           // 磁头：0
   mov ch, 0           // 柱面：0
   mov cl, 1           // 扇区：1（CHS格式，扇区从1开始）
   mov es, 0x07C0      // 目标段：0x07C0
   mov bx, 0x0000      // 目标偏移：0x0000
   int 0x13            // 调用 INT 13h

2. CPU 跳转到 IVT[0x13] → entry_13_official

3. entry_13_official → entry_13 → irqentry_arg
   - 保存所有寄存器到栈
   - 设置 DS = SS
   - 调用 handle_13(regs)

4. handle_13(regs)
   - extdrive = regs->dl = 0x80
   - 调用 handle_legacy_disk(regs, 0x80)

5. handle_legacy_disk(regs, 0x80)
   - 判断：0x80 >= EXTSTART_HD → 硬盘
   - getDrive(EXTTYPE_HD, 0x80 - 0x80) → 获取硬盘驱动器结构
   - 调用 disk_13(regs, drive_fl)

6. disk_13(regs, drive_fl)
   - regs->ah = 0x02 → 调用 disk_1302(regs, drive_fl)

7. disk_1302(regs, drive_fl)
   - 调用 basic_access(regs, drive_fl, CMD_READ)

8. basic_access(regs, drive_fl, CMD_READ)
   - 提取参数：
     * count = regs->al = 1
     * cylinder = 0
     * head = 0
     * sector = 1
   - CHS → LBA 转换：
     * LBA = (0 × heads + 0) × sectors_per_track + 1 - 1 = 0
   - 缓冲区地址：
     * buf_fl = MAKE_FLATPTR(0x07C0, 0x0000) = 0x7C00
   - 构造 disk_op_s：
     * dop.drive_fl = drive_fl
     * dop.lba = 0
     * dop.buf_fl = 0x7C00
     * dop.count = 1
     * dop.command = CMD_READ
   - 调用 send_disk_op(&dop)

9. send_disk_op(&dop)
   - 调用 process_op(&dop)

10. process_op(&dop)
    - 检查大小：1 × 512 = 512 字节 < 64KB ✓
    - 调用 process_op_32(&dop) 或 process_op_16(&dop)
    - 假设是 ATA 硬盘 → 调用 ata_process_op(&dop)

11. ata_process_op(&dop)
    - 准备 ATA 命令（LBA=0, 读取1个扇区）
    - 写入 ATA 命令寄存器
    - 等待磁盘就绪
    - 从 ATA 数据寄存器读取512字节到缓冲区 0x7C00
    - 返回状态

12. 返回路径：
    - process_op() → send_disk_op() → basic_access()
    - basic_access() 更新 regs->al = 实际传输的扇区数
    - disk_ret(regs, status) 设置返回状态
    - 返回到 irqentry_arg
    - 恢复所有寄存器
    - iretw 返回到用户程序

13. 用户程序检查结果：
    - CF = 0：成功
    - AL = 1：实际传输了1个扇区
    - 内存地址 0x7C00 现在包含 MBR 的512字节数据
```

## 关键设计特点

### 1. 分层架构

```
应用层（用户程序）
    ↓ int 0x13
BIOS 服务层（entry_13_official → handle_13）
    ↓ 功能分发
磁盘抽象层（disk_13 → basic_access）
    ↓ 操作封装
驱动分发层（process_op → process_op_32/16）
    ↓ 驱动选择
硬件驱动层（ata_process_op, ahci_process_op 等）
    ↓ 硬件访问
硬件层（ATA 控制器、AHCI 控制器等）
```

### 2. 模式切换支持

- **实模式入口**：`entry_13_official` 在实模式下执行
- **保护模式处理**：`handle_13` 等函数可以在保护模式下执行
- **自动切换**：通过 `call32()` 和 `call16()` 在模式间切换

### 3. 驱动器抽象

- **统一接口**：所有驱动器类型使用相同的 `disk_op_s` 结构
- **驱动分发**：根据驱动器类型自动选择对应的驱动处理函数
- **支持多种接口**：ATA、AHCI、USB、VirtIO、NVMe 等

### 4. 地址转换

- **段:偏移 → 平坦地址**：`MAKE_FLATPTR(es, bx)`
- **CHS → LBA**：在 `basic_access()` 中转换
- **LBA → 物理扇区**：由底层驱动处理

## 错误处理

### 错误码定义

```c
// seabios/src/std/disk.h
#define DISK_RET_SUCCESS      0x00  // 成功
#define DISK_RET_EPARAM       0x01  // 参数错误
#define DISK_RET_EBOUNDARY    0x02  // 边界错误
#define DISK_RET_ECHANGED     0x06  // 媒体改变
#define DISK_RET_EBADTRACK    0x07  // 坏磁道
#define DISK_RET_ETIMEOUT     0x80  // 超时
// ... 更多错误码
```

### 错误返回机制

```c
static void
__disk_ret(struct bregs *regs, u32 linecode, const char *fname)
{
    u8 code = linecode;
    if (regs->dl < EXTSTART_HD)
        SET_BDA(floppy_last_status, code);  // 软盘状态
    else
        SET_BDA(disk_last_status, code);    // 硬盘状态
    
    if (code)
        __set_code_invalid(regs, linecode, fname);  // 设置 CF=1
    else
        set_code_success(regs);                      // 设置 CF=0
}
```

**说明**：
- 错误码存储在 BDA（BIOS Data Area）中
- 通过设置 CF（进位标志）表示成功/失败
- 用户程序通过检查 CF 判断操作是否成功

## 性能优化

### 1. 栈切换优化

- **额外栈**：使用独立的栈避免栈溢出
- **条件编译**：`CONFIG_ENTRY_EXTRASTACK` 控制是否使用额外栈

### 2. 模式选择

- **16位模式**：传统驱动（ATA、软盘）在16位模式下执行，避免模式切换开销
- **32位模式**：现代驱动（AHCI、VirtIO）在32位模式下执行，性能更好

### 3. 缓冲区管理

- **bounce buffer**：对于需要对齐的缓冲区，使用 bounce buffer
- **直接访问**：对于已对齐的缓冲区，直接访问

## 总结

`entry_13_official` 的实现展示了 SeaBIOS 的以下特点：

1. **模块化设计**：清晰的函数分层和职责划分
2. **兼容性**：支持传统 CHS 和现代 LBA 访问方式
3. **可扩展性**：易于添加新的驱动器类型和接口
4. **错误处理**：完善的错误码和状态报告机制
5. **性能优化**：模式切换、栈管理、缓冲区优化等

整个实现从汇编入口到 C 函数处理，再到底层驱动，形成了一个完整的磁盘服务处理链，为引导程序和早期系统软件提供了可靠的磁盘访问接口。

