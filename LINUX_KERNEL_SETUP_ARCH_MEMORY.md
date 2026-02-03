# Linux 内核 setup_arch() 内存接管详解

本文档展开说明 `start_kernel()` 中 **setup_arch(&command_line)** 与**内核对物理内存的接管**相关的步骤，基于 x86（含 x86_64）内核源码：`arch/x86/kernel/setup.c`、`arch/x86/kernel/e820.c`、`arch/x86/mm/init.c`、`arch/x86/mm/init_64.c` 等。

> **相关文档**：setup_arch() 及完整启动链见 [LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md)；MMU、分页与内核页表分工见 [MMU_AND_PAGING.md](MMU_AND_PAGING.md)。

## 1. 调用顺序概览

`setup_arch()` 中与内存接管相关的主要调用顺序（x86_64，简化）如下：

```
setup_arch()（arch/x86/kernel/setup.c）
    ├─ early_reserve_memory()           // 在加入 memblock 前预留区域
    ├─ e820__memory_setup()             // 解析 E820，填充 e820_table
    ├─ ...（max_pfn、e820__finish_early_params、e820__memblock_setup 前诸多步骤）
    ├─ max_pfn = e820__end_of_ram_pfn()
    ├─ e820__memblock_setup()           // 将 E820 RAM 加入 memblock
    ├─ init_mem_mapping()               // 建立直接映射（内核页表）
    ├─ ...
    ├─ initmem_init()                   // NUMA/memblock 节点（init_64.c）
    ├─ x86_init.paging.pagetable_init() // 实际调用 paging_init()
    └─ ...
```

- **e820**：固件/引导程序提供的物理内存布局（E820 表）。
- **memblock**：早期物理内存分配器，在伙伴系统之前使用。
- **init_mem_mapping**：为物理 RAM 建立内核直接映射（页表），使内核能访问全部可用物理页。
- **paging_init**：在 x86_64 上初始化 sparse 与 zone（sparse_init、zone_sizes_init），为后续伙伴系统做准备。

以下按上述顺序分步说明。

## 2. e820__memory_setup()：解析 E820 表

**作用**：从固件/引导程序得到物理内存布局，填充内核的 **e820_table**，供后续 e820__memblock_setup 和 max_pfn 等使用。

**源码位置**：`arch/x86/kernel/setup.c` 中调用 `e820__memory_setup()`；实现与默认入口在 `arch/x86/kernel/e820.c`。

- **e820__memory_setup()**（e820.c 约 1224 行）  
  - 通过 `x86_init.resources.memory_setup()` 获取 E820 并写入 `e820_table`（默认实现为 `e820__memory_setup_default()`，从 `boot_params.e820_table` 等读取）。  
  - 拷贝到 `e820_table_kexec`、`e820_table_firmware`，并打印 “BIOS-provided physical RAM map”。

- **E820 表来源**：BIOS/固件或引导程序（如 GRUB）通过 boot protocol 传入；EFI 下可由 EFI 的 GetMemoryMap 等转换得到。

- **e820 表项类型**：常见有 `E820_TYPE_RAM`（可用 RAM）、`E820_TYPE_RESERVED`（保留）等；只有 `E820_TYPE_RAM` 会在 e820__memblock_setup 中加入 memblock 供分配。

**要点**：e820__memory_setup 只负责“解析并记录”物理内存布局，尚未建立 memblock 或页表。

## 3. max_pfn 与 e820__memblock_setup()：早期分配器

**max_pfn**：在 setup_arch() 中由 `e820__end_of_ram_pfn()` 得到，表示物理 RAM 的末尾页帧号，后续 init_mem_mapping 和 paging_init 都会用到。

**e820__memblock_setup()**（e820.c 约 1240 行）：

- **作用**：把 E820 中的可用 RAM 导入 **memblock**，建立早期物理内存分配器。
- **主要逻辑**：
  - 对 e820_table 中每个 `E820_TYPE_RAM` 调用 `memblock_add(addr, size)`，将物理区间加入 memblock 的 memory 区域。
  - `E820_TYPE_SOFT_RESERVED` 调用 `memblock_reserve`。
  - 设置 `memblock_set_current_limit(ISA_END_ADDRESS)` 等，在 init_mem_mapping 完成前限制分配范围；之后会再放宽。
- **结果**：memblock 已知“哪些物理地址是可用 RAM”，后续 init_mem_mapping 等可从 memblock 分配页表用页。

**要点**：e820__memblock_setup 之后，内核对“哪些物理页属于 RAM”已有统一描述，并可通过 memblock 做早期分配，但尚未为这些 RAM 建立直接映射。

## 4. init_mem_mapping()：建立直接映射（内核页表）

**作用**：为物理 RAM 建立**直接映射**（物理地址与内核虚拟地址线性对应），使内核可以访问全部由 e820/memblock 描述的可用物理内存。

**源码位置**：`arch/x86/mm/init.c` 中 `init_mem_mapping()`（约 758 行）。

**主要步骤**（x86_64）：

1. **ISA 区**：`init_memory_mapping(0, ISA_END_ADDRESS, PAGE_KERNEL)`，先映射 0～ISA_END_ADDRESS（如 1MB 以下）。
2. **trampoline**：`init_trampoline()`，为实模式 trampoline 等做准备（可能与 KASLR 有关）。
3. **整段 RAM 的直接映射**：根据 `memblock_bottom_up()` 选择自顶向下或自底向上：
   - **自底向上**：先 `memory_map_bottom_up(kernel_end, end)`，再 `memory_map_bottom_up(ISA_END_ADDRESS, kernel_end)`，使页表分配在内核之上。
   - **自顶向下**：`memory_map_top_down(ISA_END_ADDRESS, end)`。
4. 内部通过 **init_range_memory_mapping()** 遍历 memblock 的 PFN 区间，对每段 RAM 调用 **init_memory_mapping(start, end, PAGE_KERNEL)**，最终走到 **kernel_physical_mapping_init()** 填充页表（PML4/PDPT/PD/PT）。
5. `load_cr3(swapper_pg_dir)` 并 `__flush_tlb_all()`，使当前内核使用新的全局页表。

**要点**：init_mem_mapping() 完成后，内核已为 E820 中的 RAM 建立完整直接映射，并切换到 swapper_pg_dir，内核对物理内存的“可见性”接管完成；后续可安全使用 memblock 和即将初始化的 zone。

## 5. initmem_init() 与 paging_init()：NUMA 与 zone

**initmem_init()**（arch/x86/mm/init_64.c）：  
- 在 x86_64 上主要调用 `x86_numa_init()`，将 memblock 与 NUMA 节点关联（memblock_set_node 等），为后续按节点初始化 zone 做准备。

**paging_init()**（arch/x86_64）：  
- 在 setup_arch() 中通过 **x86_init.paging.pagetable_init()** 调用（native 下即 `native_pagetable_init` → `paging_init()`，见 `arch/x86/mm/init_64.c` 约 819 行）。  
- **paging_init()** 主要做：
  - **sparse_init()**：初始化稀疏内存模型（struct page 与 section 等）。
  - **zone_sizes_init()**：根据物理内存与 NUMA 信息计算并初始化各 zone（ZONE_DMA、ZONE_DMA32、ZONE_NORMAL 等），为伙伴系统提供物理页划分。

**要点**：paging_init() 不再次建立直接映射，而是基于 init_mem_mapping() 已建立的映射，把物理内存纳入 zone 和稀疏模型，完成从“早期 memblock”到“伙伴系统可管理内存”的过渡。

## 6. 小结：内核接管内存的“关键一步”落在哪里？

- **“知道有哪些物理内存”**：**e820__memory_setup()** + **e820__memblock_setup()**（E820 → e820_table → memblock）。  
- **“能访问这些物理内存”**：**init_mem_mapping()**（建立直接映射并切换 CR3）。  
- **“能按页分配与管理”**：**paging_init()**（sparse_init + zone_sizes_init），为伙伴系统准备好 zone。

因此，**setup_arch() 中内核对物理内存的完整接管**是由 **e820 解析 → memblock 建立 → init_mem_mapping → paging_init** 这一整条链完成的；若只选“一步”作为“关键”，通常是 **init_mem_mapping()**（建立直接映射并切换页表），因为此前内核还不能线性访问全部 RAM，此后才可以。内核与 MMU 在页表上的分工（内核维护页表、MMU 查表与缺页协作）见 [MMU_AND_PAGING.md](MMU_AND_PAGING.md)。

本文档基于 Linux 内核 x86 源码整理；具体行号与条件编译可能随版本略有变化，以实际源码为准。
