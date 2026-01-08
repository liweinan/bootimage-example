# 用户空间虚拟地址到物理地址转换流程详解

本文档详细描述用户空间汇编代码访问虚拟内存时，内核如何将虚拟地址转换为物理地址的完整执行流程。

---

## 场景设定

假设用户空间有一个简单的汇编代码片段：

```asm
# 用户空间汇编代码示例
movq $0x7ffe1234, %rax    # 将虚拟地址加载到寄存器
movb (%rax), %bl          # 从虚拟地址读取一个字节
```

当CPU执行 `movb (%rax), %bl` 时，需要将虚拟地址 `0x7ffe1234` 转换为物理地址。

---

## 完整执行流程

### 阶段1：CPU硬件层面的地址转换尝试

#### 1.1 TLB查找（Translation Lookaside Buffer）

CPU首先在TLB（页表缓存）中查找虚拟地址到物理地址的映射：

```
虚拟地址 0x7ffe1234 → 查询TLB
```

- **TLB命中**：如果TLB中存在该映射，CPU直接使用缓存的物理地址，完成内存访问，流程结束。
- **TLB未命中**：继续执行硬件页表遍历。

#### 1.2 硬件页表遍历（x86_64架构）

如果TLB未命中，CPU硬件自动执行多级页表查找：

**虚拟地址分解（x86_64，4KB页）：**
```
虚拟地址: 0x7ffe1234
[47:39] → PML4索引 (9位)
[38:30] → PDP索引  (9位)
[29:21] → PD索引   (9位)
[20:12] → PT索引   (9位)
[11:0]  → 页内偏移 (12位)
```

**硬件查找流程：**
1. CPU从CR3寄存器读取当前进程的PML4表物理地址
2. 使用位[47:39]索引PML4表，得到PDP表物理地址
3. 使用位[38:30]索引PDP表，得到PD表物理地址
4. 使用位[29:21]索引PD表，得到PT表物理地址
5. 使用位[20:12]索引PT表，得到页表项（PTE）

**PTE检查：**
- 如果PTE的Present位为1且有效：提取物理页框号（PFN），拼接页内偏移得到物理地址，更新TLB，完成访问。
- 如果PTE的Present位为0或无效：触发**缺页异常（Page Fault）**，进入内核处理。

---

### 阶段2：缺页异常处理（内核介入）

#### 2.1 异常入口（x86_64）

当CPU检测到页表项无效时，触发缺页异常（中断向量14，`#PF`），CPU自动：

1. 保存当前执行状态到内核栈（`struct pt_regs`）
2. 跳转到异常处理入口：`asm_exc_page_fault`

相关代码位置：
- 异常处理入口定义在 `arch/x86/entry/entry_64.S` 或类似位置
- 最终调用到 `arch/x86/mm/fault.c` 中的处理函数

#### 2.2 用户空间缺页处理入口

在 `arch/x86/mm/fault.c` 中，`do_user_addr_fault` 函数处理用户空间的缺页异常：

```1208:1304:arch/x86/mm/fault.c
static inline
void do_user_addr_fault(struct pt_regs *regs,
			unsigned long error_code,
			unsigned long address)
{
	struct vm_area_struct *vma;
	struct task_struct *tsk;
	struct mm_struct *mm;
	vm_fault_t fault;
	unsigned int flags = FAULT_FLAG_DEFAULT;

	tsk = current;
	mm = tsk->mm;
	// ... 错误检查和权限验证 ...
	
	// 设置缺页标志
	if (error_code & X86_PF_WRITE)
		flags |= FAULT_FLAG_WRITE;
	if (user_mode(regs))
		flags |= FAULT_FLAG_USER;

	// 查找VMA（虚拟内存区域）
	vma = lock_mm_and_find_vma(mm, address, regs);
	if (unlikely(!vma)) {
		bad_area_nosemaphore(regs, error_code, address);
		return;
	}

	// 检查访问权限
	if (unlikely(access_error(error_code, vma))) {
		bad_area_access_error(regs, error_code, address, mm, vma);
		return;
	}

	// 调用核心缺页处理函数
	fault = handle_mm_fault(vma, address, flags, regs);
	// ... 后续处理 ...
}
```

**关键步骤：**
1. 获取当前进程的 `mm_struct`（内存描述符）
2. 根据虚拟地址查找对应的 `vm_area_struct`（VMA）
3. 检查访问权限（读/写/执行）
4. 调用 `handle_mm_fault` 进行实际处理

---

### 阶段3：内核页表遍历与建立映射

#### 3.1 缺页处理主函数

`handle_mm_fault` 是缺页处理的核心函数，定义在 `mm/memory.c`：

```6346:6410:mm/memory.c
vm_fault_t handle_mm_fault(struct vm_area_struct *vma, unsigned long address,
			   unsigned int flags, struct pt_regs *regs)
{
	struct mm_struct *mm = vma->vm_mm;
	vm_fault_t ret;
	// ... 权限检查 ...

	if (unlikely(is_vm_hugetlb_page(vma)))
		ret = hugetlb_fault(vma->vm_mm, vma, address, flags);
	else
		ret = __handle_mm_fault(vma, address, flags);

	// ... 统计和清理 ...
	return ret;
}
```

#### 3.2 页表逐级查找与分配

`__handle_mm_fault` 函数执行实际的页表遍历和映射建立：

```6119:6213:mm/memory.c
static vm_fault_t __handle_mm_fault(struct vm_area_struct *vma,
		unsigned long address, unsigned int flags)
{
	struct vm_fault vmf = {
		.vma = vma,
		.address = address & PAGE_MASK,
		.real_address = address,
		.flags = flags,
		.pgoff = linear_page_index(vma, address),
		.gfp_mask = __get_fault_gfp_mask(vma),
	};
	struct mm_struct *mm = vma->vm_mm;
	pgd_t *pgd;
	p4d_t *p4d;
	vm_fault_t ret;

	// 步骤1: 获取PGD（页全局目录）
	pgd = pgd_offset(mm, address);
	p4d = p4d_alloc(mm, pgd, address);
	if (!p4d)
		return VM_FAULT_OOM;

	// 步骤2: 获取PUD（页上级目录）
	vmf.pud = pud_alloc(mm, p4d, address);
	if (!vmf.pud)
		return VM_FAULT_OOM;

	// 步骤3: 获取PMD（页中间目录）
	vmf.pmd = pmd_alloc(mm, vmf.pud, address);
	if (!vmf.pmd)
		return VM_FAULT_OOM;

	// 步骤4: 处理PTE级别
	return handle_pte_fault(&vmf);
}
```

**内核页表遍历过程：**

1. **PGD查找**：`pgd_offset(mm, address)` 从进程的 `mm->pgd` 获取页全局目录项
   ```c
   // include/linux/pgtable.h
   #define pgd_offset(mm, address) pgd_offset_pgd((mm)->pgd, (address))
   ```

2. **P4D/PUD/PMD分配**：如果中间页表级不存在，调用 `p4d_alloc`、`pud_alloc`、`pmd_alloc` 分配新页表页

3. **PTE处理**：最终调用 `handle_pte_fault` 处理页表项级别

#### 3.3 PTE级别处理

`handle_pte_fault` 函数处理具体的页表项：

```6025:6111:mm/memory.c
static vm_fault_t handle_pte_fault(struct vm_fault *vmf)
{
	pte_t entry;

	// 获取PTE指针
	vmf->pte = pte_offset_map_rw_nolock(vmf->vma->vm_mm, vmf->pmd,
					    vmf->address, &dummy_pmdval,
					    &vmf->ptl);
	vmf->orig_pte = ptep_get_lockless(vmf->pte);

	// 情况1: PTE不存在（未分配）
	if (!vmf->pte || pte_none(vmf->orig_pte))
		return do_pte_missing(vmf);

	// 情况2: PTE存在但页被换出（swap）
	if (!pte_present(vmf->orig_pte))
		return do_swap_page(vmf);

	// 情况3: PTE存在且有效，但需要更新访问位
	spin_lock(vmf->ptl);
	entry = vmf->orig_pte;
	if (vmf->flags & (FAULT_FLAG_WRITE|FAULT_FLAG_UNSHARE)) {
		if (!pte_write(entry))
			return do_wp_page(vmf);  // 写时复制
		else if (likely(vmf->flags & FAULT_FLAG_WRITE))
			entry = pte_mkdirty(entry);
	}
	entry = pte_mkyoung(entry);
	ptep_set_access_flags(vmf->vma, vmf->address, vmf->pte, entry,
				vmf->flags & FAULT_FLAG_WRITE);
	// ...
}
```

**PTE处理分支：**

- **PTE不存在**：调用 `do_pte_missing`，进一步可能调用 `do_anonymous_page` 或 `do_fault`
- **页被换出**：调用 `do_swap_page` 从swap空间换入
- **PTE有效**：更新访问位（Accessed）和脏位（Dirty）

---

### 阶段4：物理页分配与映射建立

#### 4.1 匿名页分配

如果访问的是匿名内存（如堆、栈），`do_anonymous_page` 函数分配物理页：

```5022:5135:mm/memory.c
static vm_fault_t do_anonymous_page(struct vm_fault *vmf)
{
	struct vm_area_struct *vma = vmf->vma;
	unsigned long addr = vmf->address;
	struct folio *folio;
	pte_t entry;

	// 为PMD分配PTE表（如果不存在）
	if (pte_alloc(vma->vm_mm, vmf->pmd))
		return VM_FAULT_OOM;

	// 只读访问：使用零页（zero page）
	if (!(vmf->flags & FAULT_FLAG_WRITE) &&
			!mm_forbids_zeropage(vma->vm_mm)) {
		entry = pte_mkspecial(pfn_pte(my_zero_pfn(vmf->address),
						vma->vm_page_prot));
		goto setpte;
	}

	// 分配新的匿名页
	folio = alloc_anon_folio(vmf);
	if (!folio)
		goto oom;

	// 创建PTE项
	entry = folio_mk_pte(folio, vma->vm_page_prot);
	entry = pte_sw_mkyoung(entry);
	if (vma->vm_flags & VM_WRITE)
		entry = pte_mkwrite(pte_mkdirty(entry), vma);

	// 获取PTE指针并加锁
	vmf->pte = pte_offset_map_lock(vma->vm_mm, vmf->pmd, addr, &vmf->ptl);

	// 建立映射：将PTE写入页表
	set_ptes(vma->vm_mm, addr, vmf->pte, entry, nr_pages);

	// 更新MMU缓存（可能刷新TLB）
	update_mmu_cache_range(vmf, vma, addr, vmf->pte, nr_pages);

	pte_unmap_unlock(vmf->pte, vmf->ptl);
	return 0;
}
```

**关键操作：**

1. **分配物理页**：`alloc_anon_folio` 通过伙伴系统分配物理页框
2. **创建PTE**：`folio_mk_pte` 将物理页框号（PFN）和权限标志组合成PTE值
3. **写入页表**：`set_ptes` 将PTE写入页表的对应位置
4. **更新TLB**：`update_mmu_cache_range` 可能触发TLB刷新

#### 4.2 从虚拟地址到物理地址的转换

在 `do_anonymous_page` 中，关键转换发生在：

```c
// 1. 分配物理页，得到 struct folio
folio = alloc_anon_folio(vmf);

// 2. 从 folio 获取物理页框号（PFN）
// folio 内部包含 page，page 有物理地址信息

// 3. 创建PTE，将PFN编码到PTE中
entry = folio_mk_pte(folio, vma->vm_page_prot);
// 等价于：entry = pfn_pte(page_to_pfn(page), prot);

// 4. 将PTE写入页表
set_ptes(vma->vm_mm, addr, vmf->pte, entry, nr_pages);
```

**PTE结构（x86_64，64位）：**
```
[63:12] 物理页框号（PFN），共52位
[11:0]  标志位：Present, R/W, U/S, Accessed, Dirty等
```

**最终物理地址计算：**
```
物理地址 = (PTE中的PFN << 12) + (虚拟地址的页内偏移[11:0])
```

例如，如果虚拟地址是 `0x7ffe1234`：
- 页内偏移 = `0x234`
- 假设PTE中的PFN = `0x54321`
- 物理地址 = `(0x54321 << 12) + 0x234 = 0x54321000 + 0x234 = 0x54321234`

---

### 阶段5：返回用户空间

#### 5.1 异常返回

缺页异常处理完成后，内核通过 `iret` 指令返回用户空间：

1. 恢复用户空间寄存器状态（从 `pt_regs`）
2. 恢复用户空间栈指针
3. 跳转回触发缺页的指令（`movb (%rax), %bl`）

#### 5.2 重新执行指令

CPU重新执行 `movb (%rax), %bl`：

1. **TLB查找**：此时TLB中已有新建立的映射（或通过硬件页表查找）
2. **地址转换**：虚拟地址 `0x7ffe1234` → 物理地址（如 `0x54321234`）
3. **内存访问**：从物理地址读取数据到 `%bl` 寄存器
4. **完成**：指令执行成功

---

## 内核代码关键函数调用链

完整的函数调用链如下：

```
用户空间: movb (%rax), %bl
    ↓
CPU硬件: TLB查找失败 → 页表遍历 → PTE无效 → 触发#PF异常
    ↓
arch/x86/entry/entry_64.S: asm_exc_page_fault
    ↓
arch/x86/mm/fault.c: do_user_addr_fault()
    ↓
mm/memory.c: handle_mm_fault()
    ↓
mm/memory.c: __handle_mm_fault()
    ├─ pgd_offset()        # 获取PGD
    ├─ p4d_alloc()          # 分配P4D（如需要）
    ├─ pud_alloc()          # 分配PUD（如需要）
    ├─ pmd_alloc()          # 分配PMD（如需要）
    └─ handle_pte_fault()
        ├─ pte_offset_map_rw_nolock()  # 获取PTE指针
        ├─ do_pte_missing()            # PTE不存在
        │   └─ do_anonymous_page()     # 分配匿名页
        │       ├─ alloc_anon_folio()   # 通过伙伴系统分配物理页
        │       ├─ folio_mk_pte()      # 创建PTE（包含PFN）
        │       └─ set_ptes()          # 写入页表
        └─ update_mmu_cache_range()    # 更新TLB
    ↓
返回用户空间，重新执行指令
    ↓
CPU硬件: TLB命中或页表查找成功 → 完成内存访问
```

---

## 关键数据结构

### 1. 页表项（PTE）

```c
// arch/x86/include/asm/pgtable_types.h
typedef struct { pteval_t pte; } pte_t;

// PTE位域含义（x86_64）：
// [63]   NX (No Execute)
// [62]   Software bit
// [11]   N (PAT)
// [10]   G (Global)
// [9]    PS (Page Size, 仅用于大页)
// [8]    D (Dirty)
// [7]    A (Accessed)
// [6]    PCD (Page Cache Disable)
// [5]    PWT (Page Write Through)
// [4]    U/S (User/Supervisor)
// [3]    R/W (Read/Write)
// [2]    P (Present)
// [1:0]  保留
// [51:12] 物理页框号（PFN）
```

### 2. 内存描述符

```c
// include/linux/mm_types.h
struct mm_struct {
    pgd_t *pgd;                    // 页全局目录基址
    struct vm_area_struct *mmap;   // VMA链表
    // ...
};

struct vm_area_struct {
    unsigned long vm_start;        // 虚拟地址起始
    unsigned long vm_end;          // 虚拟地址结束
    pgprot_t vm_page_prot;         // 页保护权限
    unsigned long vm_flags;        // 标志（共享、私有等）
    // ...
};
```

### 3. 缺页故障描述符

```c
// include/linux/mm.h
struct vm_fault {
    struct vm_area_struct *vma;    // 对应的VMA
    unsigned long address;          // 故障地址
    pte_t *pte;                    // PTE指针
    pmd_t *pmd;                    // PMD指针
    pud_t *pud;                    // PUD指针
    pte_t orig_pte;                // 原始PTE值
    unsigned int flags;            // 故障标志
    // ...
};
```

---

## 地址转换示例（完整流程）

假设用户空间访问虚拟地址 `0x7ffe1234`：

### 步骤1：虚拟地址分解
```
虚拟地址: 0x000000007ffe1234
二进制:   0000 0000 0000 0000 0111 1111 1111 1110 0001 0010 0011 0100

分解：
- PML4索引 [47:39]: 0x000 (位47-39 = 0)
- PDP索引  [38:30]: 0x0FF (位38-30 = 0x0FF)
- PD索引   [29:21]: 0x1FC (位29-21 = 0x1FC)
- PT索引   [20:12]: 0x123 (位20-12 = 0x123)
- 页内偏移 [11:0]:  0x234 (位11-0 = 0x234)
```

### 步骤2：内核页表遍历

```c
// 1. 获取PGD
pgd = pgd_offset(mm, 0x7ffe1234);
// pgd = mm->pgd + (address >> 39) & 0x1FF

// 2. 获取P4D
p4d = p4d_offset(pgd, 0x7ffe1234);

// 3. 获取PUD
pud = pud_offset(p4d, 0x7ffe1234);

// 4. 获取PMD
pmd = pmd_offset(pud, 0x7ffe1234);

// 5. 获取PTE
pte = pte_offset_map(pmd, 0x7ffe1234);
// pte = (pmd指向的页表页) + ((address >> 12) & 0x1FF) * sizeof(pte_t)
```

### 步骤3：分配物理页并建立映射

```c
// 1. 分配物理页（假设得到PFN = 0x54321）
folio = alloc_anon_folio(vmf);
// 物理页地址 = 0x54321 * 4096 = 0x54321000

// 2. 创建PTE
entry = folio_mk_pte(folio, vma->vm_page_prot);
// entry.pte = (0x54321 << 12) | _PAGE_PRESENT | _PAGE_RW | _PAGE_USER

// 3. 写入页表
set_ptes(mm, 0x7ffe1000, pte, entry, 1);
// 将entry写入pte指向的位置
```

### 步骤4：物理地址计算

```
PTE值 = 0x0000000005432123 (假设)
PFN = 0x54321 (从PTE提取)
物理页基址 = 0x54321 << 12 = 0x54321000
页内偏移 = 0x234
最终物理地址 = 0x54321000 + 0x234 = 0x54321234
```

---

## 性能优化机制

### 1. TLB缓存

TLB缓存最近使用的虚拟地址到物理地址的映射，避免每次访问都遍历页表。

### 2. 每CPU页框缓存

内核维护每CPU的页框缓存（per-CPU page cache），加速单页分配。

### 3. 大页支持

使用2MB或1GB的大页减少TLB压力，提高性能。

### 4. 预取优化

CPU和内核可能预取相邻页，减少缺页异常次数。

---

## 总结

从用户空间汇编代码访问虚拟内存到内核完成地址转换的完整流程：

1. **CPU硬件尝试**：TLB查找 → 硬件页表遍历
2. **触发异常**：PTE无效时触发缺页异常
3. **内核处理**：查找VMA → 遍历页表 → 分配物理页 → 建立映射
4. **返回执行**：内核返回用户空间，CPU重新执行指令
5. **完成访问**：TLB命中或页表查找成功，完成内存访问

整个过程涉及硬件MMU、内核页表管理、物理内存分配等多个子系统，体现了Linux内核内存管理的复杂性和高效性。

---

# 是的，这些 `.org` 地址（在 SeaBIOS 代码中写作大写的 `ORG addr` 宏）**不是随意写的，也不是汇编器随意计算出来的，而是严格按照 IBM PC/AT 兼容 BIOS 的历史遗留布局固定下来的**。它们是 SeaBIOS（以及几乎所有传统 Legacy BIOS 实现，如 Award、AMI、Phoenix）必须遵守的**固定位置约定**，以保证操作系统、引导程序和旧软件的兼容性。

### 1. 为什么必须固定这些地址？
从 1981 年 IBM PC 5150 开始，BIOS ROM（大小通常为 128KB 或 1MB）被映射到物理内存的最高地址：**0xF0000 ~ 0xFFFFF**（有时扩展到 0xE0000 ~ 0xEFFFF）。

早期操作系统（如 DOS）和许多软件**直接硬编码跳转到这些固定地址**来调用 BIOS 服务。例如：
- DOS 的 INT 10h 视频服务会跳转到 **0xF065**（视频初始化入口）。
- INT 13h 磁盘服务会跳转到 **0xEC59**（在某些 BIOS 中）。
- 开机上电后 CPU 从 **0xFFFF0** 开始执行（reset vector）。

为了保持向后兼容，所有现代 BIOS 实现（包括 SeaBIOS、coreboot 的 payload）都必须在这些经典位置提供相同的入口点，否则大量旧软件和引导程序会崩溃。

### 2. 你代码中这些 ORG 地址的含义和来源

| ORG 地址     | 物理地址       | 功能描述                                     | 历史来源 / 兼容要求 |
|--------------|----------------|----------------------------------------------|---------------------|
| 0xe05b       | 0xFE05B       | POST（Power-On Self Test）入口，正常开机进入点 | 许多 DOS 和早期 Windows 引导程序跳转到这里 |
| 0xe2c3       | 0xFE2C3       | INT 02h（NMI 非屏蔽中断）处理入口            | IBM PC/AT 标准      |
| 0xe3fe       | 0xFE3FE       | 官方 INT 13h 磁盘服务入口（跳转到实际处理）  | 部分旧软件直接 jmp 这里 |
| 0xe6f2       | 0xFE6F2       | 官方 INT 19h 引导入口（引导加载程序）         | 经典引导入口        |
| 0xe739       | 0xFE739       | INT 14h 串口服务入口                         | IBM 标准            |
| 0xe82e       | 0xFE82E       | INT 16h 键盘服务入口                         | IBM 标准            |
| 0xe987       | 0xFE987       | INT 09h 键盘硬件中断入口                     | IBM 标准            |
| 0xec59       | 0xFEC59       | INT 40h（磁盘重定向）入口                    | 旧软盘 BIOS 重定向  |
| 0xef57       | 0xFEF57       | INT 0Eh（从盘控制器中断）                    | IBM 标准            |
| 0xefd2       | 0xFEFD2       | INT 17h 打印机服务入口                       | IBM 标准            |
| 0xf065       | 0xFF065       | 标准 INT 10h 视频服务主入口                  | **最著名的地址**，几乎所有显示操作都到这里 |
| 0xf841       | 0xFF841       | INT 12h 内存大小服务                         | IBM 标准            |
| 0xf84d       | 0xFF84D       | INT 11h 设备列表服务                         | IBM 标准            |
| 0xf859       | 0xFF859       | INT 15h 扩展服务主入口（包括 AH=0xC0、AH=0x87 等） | IBM AT 标准         |
| 0xfea5       | 0xFFEA5       | INT 08h 系统定时器中断入口                   | IBM 标准            |
| 0xff53       | 0xFFF53       | 简单的 IRET（某些中断直接返回）              | 填充用途            |
| 0xff54       | 0xFFF54       | INT 05h 打印屏幕入口                         | IBM 标准            |
| 0xfff0       | 0xFFFF0       | **CPU 上电复位入口（reset vector）**          | **硬件硬性规定**，CPU 强制从这里开始执行 |
| 0xffff       | 0xFFFFF       | 机器型号 ID（通常 0xFC 表示 AT）             | IBM 标准            |

### 3. 这些地址是怎么“计算”出来的？
- 不是计算，而是**历史约定 + 标准文档**：
  - IBM 发布的《IBM Personal Computer Technical Reference Manual》（1981/1984）中明确列出了这些入口地址。
  - 后续 IBM PC/AT、PS/2 等机型延续并扩展了这些位置。
  - 第三方 BIOS 厂商（Award、AMI、Phoenix）为了兼容，也严格遵守。
  - Ralf Brown’s Interrupt List（著名的中断列表）详细记录了所有这些固定地址。
- SeaBIOS 作为开源 BIOS，必须**100% 复制这些经典入口**，否则：
  - DOS 游戏无法显示。
  - Windows 9x 引导失败。
  - 某些诊断工具崩溃。
  - 甚至一些现代引导加载器（如旧版 GRUB）也会出错。

### 4. 代码中 ORG 宏的实现方式
在 SeaBIOS 中，`ORG addr` 是一个自定义宏（在 build.c 或汇编头中定义），作用是：
```asm
.macro ORG addr
    .section .fixedaddr.\addr   // 创建一个特定名字的 section
    .org \addr                  // 强制当前位置为指定地址
.endm
```
链接器脚本（romlayout.ld 等）会把这些 `.fixedaddr.xxxx` section 精确放置到 ROM 镜像的对应偏移，从而确保最终生成的 BIOS ROM 文件在 0xF0000 + offset 处正好有这些入口代码。

### 总结
你看到的这些 `ORG 0xe05b`、`ORG 0xf065`、`ORG 0xffff0` 等地址：
- **不是随意或计算出来的**。
- 是 **30~40 年历史的 IBM PC BIOS 兼容性铁律**。
- SeaBIOS 必须严格遵守，否则就不能称为“兼容 BIOS”。
- 它们是 x86 实模式生态中少数几个真正“神圣不可侵犯”的固定地址之一（另一个著名的是引导扇区 0x7C00）。

这就是为什么 SeaBIOS 代码里会出现这么多看起来“奇怪”的硬编码地址——它们不是 bug，而是兼容性的基石。