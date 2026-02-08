# Linux 内核伙伴系统与 Slab 分配器详解

## 文档定位

本文档详细介绍 Linux 内核的**物理内存分配体系**，包括伙伴系统（Buddy Allocator）和 Slab 分配器（Slab/SLUB/SLOB）的实现原理、数据结构和使用方法。

**核心内容**：
- 内核内存分配的层次结构
- 伙伴系统的原理与实现
- Slab 分配器的设计与优化
- 从 memblock 到 buddy allocator 的过渡

**适合读者**：
- 想深入理解内核内存管理的开发者
- 需要优化内存分配性能的系统程序员
- 对操作系统底层实现感兴趣的学习者

**相关文档**：
- [Slab 分配器原理与实践](SLAB_ALLOCATOR_EXPLAINED.md) - Slab 分配器的原理教学（推荐先读）
- [Linux 内核分页机制完整指南](LINUX_PAGING_COMPLETE_GUIDE.md) - 页表管理与物理内存分配的关系
- [Linux 内核启动流程](LINUX_KERNEL_INIT.md) - memblock 和 buddy 系统的初始化时机

---

## 一、内核内存分配层次概览

### 1.1 完整的分配层次

```
┌─────────────────────────────────────────────────────────┐
│  应用层                                                  │
│  ├─ kmalloc() / kzalloc()    ← 内核通用分配             │
│  ├─ kmem_cache_alloc()       ← 特定类型对象分配         │
│  └─ __get_free_pages()       ← 直接分配整页             │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│  Slab 分配器层（SLUB/SLAB/SLOB）                        │
│  ├─ 小对象分配（< PAGE_SIZE）                           │
│  ├─ 对象缓存（task_struct, inode, dentry 等）          │
│  └─ Per-CPU 缓存优化                                     │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│  伙伴系统层（Buddy Allocator）                          │
│  ├─ 物理页框分配（2^0 到 2^10 页）                      │
│  ├─ 反碎片化管理（MIGRATE_UNMOVABLE/MOVABLE/RECLAIMABLE）│
│  └─ zone 管理（ZONE_DMA/ZONE_DMA32/ZONE_NORMAL）       │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│  物理内存层                                              │
│  └─ 实际的 RAM 页框                                     │
└─────────────────────────────────────────────────────────┘
```

### 1.2 各层职责

| 层次 | 职责 | 粒度 | 典型使用场景 |
|------|------|------|------------|
| **Slab 分配器** | 小对象分配、对象缓存、减少碎片 | 几十字节到 PAGE_SIZE | 内核数据结构（task_struct、inode） |
| **伙伴系统** | 物理页框分配、反碎片化 | 2^n 页（4KB 到 4MB） | 页表、大块缓冲区、Slab 后端 |
| **物理内存** | 实际 RAM 存储 | 字节级 | 硬件层面 |

---

## 二、伙伴系统（Buddy Allocator）

### 2.1 核心原理

**伙伴系统**是一种经典的动态内存分配算法，用于管理**物理页框**。其核心思想是：

1. **2 的幂次分配**：将可用内存按 2^n 页大小组织（n = 0 到 MAX_ORDER-1）
2. **伙伴关系**：两个大小相同、地址连续且对齐的块互为"伙伴"（buddy）
3. **分裂与合并**：
   - **分配**：找不到合适大小的块时，将更大的块分裂成两个伙伴
   - **释放**：如果伙伴也空闲，则合并成更大的块

```
伙伴关系示例（4KB 页大小）：

Order 2 (16KB):
┌────────────────┐
│ 块 A (16KB)    │ ← 分裂
└────────────────┘

Order 1 (8KB):
┌────────┬────────┐
│ 块 B   │ 块 C   │ ← B 和 C 互为伙伴
└────────┴────────┘

Order 0 (4KB):
┌────┬────┬────┬────┐
│ D  │ E  │ F  │ G  │ ← D 和 E 互为伙伴，F 和 G 互为伙伴
└────┴────┴────┴────┘
```

### 2.2 核心数据结构

#### 2.2.1 zone 结构

```c
// Linux Kernel - include/linux/mmzone.h:100

struct zone {
    /* 伙伴系统核心 */
    struct free_area free_area[MAX_ORDER];  // MAX_ORDER = 11

    /* zone 统计信息 */
    unsigned long managed_pages;   // 可管理的页面数
    unsigned long spanned_pages;   // zone 跨越的总页面数（包括空洞）
    unsigned long present_pages;   // 物理存在的页面数

    /* zone 标识 */
    const char *name;              // "DMA", "DMA32", "Normal", etc.

    /* 水位线（watermark） */
    unsigned long watermark[NR_WMARK];  // min, low, high

    /* Per-CPU 页面缓存 */
    struct per_cpu_pageset __percpu *pageset;

    /* ... 更多字段 ... */
} ____cacheline_internodealigned_in_smp;
```

#### 2.2.2 free_area 结构

```c
// Linux Kernel - include/linux/mmzone.h:95

struct free_area {
    /* 空闲链表（按迁移类型分组） */
    struct list_head free_list[MIGRATE_TYPES];

    /* 空闲页面数 */
    unsigned long nr_free;
};

/* MAX_ORDER = 11，表示 2^0 到 2^10 页 */
#define MAX_ORDER 11

/* 迁移类型 */
enum migratetype {
    MIGRATE_UNMOVABLE,    // 不可移动（内核数据）
    MIGRATE_MOVABLE,      // 可移动（用户页面）
    MIGRATE_RECLAIMABLE,  // 可回收（页缓存）
    MIGRATE_PCPTYPES,     // Per-CPU 类型数量
    MIGRATE_HIGHATOMIC = MIGRATE_PCPTYPES,
#ifdef CONFIG_CMA
    MIGRATE_CMA,          // Contiguous Memory Allocator
#endif
    MIGRATE_ISOLATE,      // 隔离页面
    MIGRATE_TYPES
};
```

#### 2.2.3 page 结构（部分字段）

```c
// Linux Kernel - include/linux/mm_types.h:65

struct page {
    unsigned long flags;          // 页面标志（PG_locked, PG_buddy 等）
    atomic_t _refcount;           // 引用计数
    atomic_t _mapcount;           // 映射计数

    union {
        /* 伙伴系统使用的字段 */
        struct {
            struct list_head lru;  // 链接到 free_list
            unsigned long private; // 存储 order
        };

        /* Slab 分配器使用的字段 */
        struct {
            void *freelist;
            union {
                void *s_mem;
                struct {
                    unsigned inuse:16;
                    unsigned objects:15;
                    unsigned frozen:1;
                };
            };
        };

        /* ... 其他用途 ... */
    };
} _struct_page_alignment;
```

### 2.3 伙伴系统算法

#### 2.3.1 分配算法

```c
// Linux Kernel - mm/page_alloc.c

/*
 * 伙伴系统分配流程（简化版）
 *
 * 参数：
 *   zone: 目标 zone
 *   order: 请求的 order（2^order 页）
 *   migratetype: 迁移类型
 */
struct page *__rmqueue(struct zone *zone, unsigned int order,
                        int migratetype)
{
    struct page *page;

    /* 尝试从当前 order 的空闲链表分配 */
    page = __rmqueue_smallest(zone, order, migratetype);
    if (likely(page))
        return page;

    /* 当前 order 无空闲块，尝试从其他迁移类型窃取 */
    return __rmqueue_fallback(zone, order, migratetype);
}

/*
 * 从指定 order 或更大的 order 分配
 */
static inline struct page *__rmqueue_smallest(struct zone *zone,
                                                unsigned int order,
                                                int migratetype)
{
    unsigned int current_order;
    struct free_area *area;
    struct page *page;

    /* 从 order 开始向上查找 */
    for (current_order = order; current_order < MAX_ORDER; ++current_order) {
        area = &(zone->free_area[current_order]);

        /* 检查该 order 是否有空闲块 */
        page = list_first_entry_or_null(&area->free_list[migratetype],
                                         struct page, lru);
        if (!page)
            continue;  // 该 order 无空闲块，继续向上查找

        /* 找到空闲块，从链表移除 */
        list_del(&page->lru);
        area->nr_free--;

        /* 如果找到的块比请求的大，需要分裂 */
        expand(zone, page, order, current_order, area, migratetype);

        return page;
    }

    return NULL;  // 所有 order 都无空闲块
}

/*
 * 分裂大块
 *
 * 示例：请求 order=1 (2 页)，找到 order=3 (8 页) 的块
 * 分裂过程：
 *   8 页 → 4 页 + 4 页  (order 3 → order 2，保留一个 4 页块到 free_area[2])
 *   4 页 → 2 页 + 2 页  (order 2 → order 1，保留一个 2 页块到 free_area[1])
 *   返回 2 页块给调用者
 */
static inline void expand(struct zone *zone, struct page *page,
                          int low_order, int high_order,
                          struct free_area *area, int migratetype)
{
    unsigned long size = 1 << high_order;

    while (high_order > low_order) {
        area--;
        high_order--;
        size >>= 1;  // 每次减半

        /* 将伙伴块加入 free_area[high_order] */
        list_add(&page[size].lru, &area->free_list[migratetype]);
        area->nr_free++;

        /* 标记为 buddy 页 */
        set_page_order(&page[size], high_order);
    }
}
```

#### 2.3.2 释放算法

```c
// Linux Kernel - mm/page_alloc.c

/*
 * 伙伴系统释放流程
 *
 * 核心思想：
 * 1. 找到伙伴块
 * 2. 如果伙伴也空闲，合并成更大的块
 * 3. 重复步骤 1-2，直到无法继续合并
 */
static inline void __free_one_page(struct page *page,
                                    unsigned long pfn,
                                    struct zone *zone,
                                    unsigned int order,
                                    int migratetype)
{
    unsigned long combined_pfn;
    unsigned long uninitialized_var(buddy_pfn);
    struct page *buddy;
    unsigned int max_order = MAX_ORDER;

    /* 持续合并，直到达到最大 order 或伙伴不空闲 */
    while (order < max_order - 1) {
        /* 计算伙伴块的 PFN */
        buddy_pfn = __find_buddy_pfn(pfn, order);
        buddy = page + (buddy_pfn - pfn);

        /* 检查伙伴是否空闲且 order 相同 */
        if (!page_is_buddy(page, buddy, order))
            goto done_merging;

        /* 伙伴空闲，从链表移除 */
        list_del(&buddy->lru);
        zone->free_area[order].nr_free--;
        clear_page_guard_flag(buddy);

        /* 合并：计算合并后的 PFN */
        combined_pfn = buddy_pfn & pfn;
        page = page + (combined_pfn - pfn);
        pfn = combined_pfn;
        order++;
    }

done_merging:
    /* 将合并后的块加入 free_area[order] */
    list_add(&page->lru, &zone->free_area[order].free_list[migratetype]);
    zone->free_area[order].nr_free++;
    set_page_order(page, order);
}

/*
 * 计算伙伴块的 PFN
 *
 * 伙伴关系：
 * - 对于 order=n 的块，伙伴块与它的距离是 2^n 页
 * - 通过异或操作快速计算伙伴 PFN
 */
static inline unsigned long __find_buddy_pfn(unsigned long page_pfn,
                                               unsigned int order)
{
    return page_pfn ^ (1 << order);
}

/* 示例：
 * PFN 0x1000, order=2 (4 页)
 * 伙伴 PFN = 0x1000 ^ (1 << 2) = 0x1000 ^ 0x4 = 0x1004
 *
 * PFN 0x1004, order=2
 * 伙伴 PFN = 0x1004 ^ 0x4 = 0x1000
 *
 * → 0x1000 和 0x1004 互为伙伴
 */
```

### 2.4 反碎片化机制

Linux 内核使用**按迁移类型分组**的策略减少碎片化：

```
zone->free_area[order] 的组织：

free_area[2] (16KB blocks):
┌─────────────────────────────────────────┐
│ MIGRATE_UNMOVABLE:  [block1] → [block2] │
│ MIGRATE_MOVABLE:    [block3] → [block4] │
│ MIGRATE_RECLAIMABLE:[block5]            │
└─────────────────────────────────────────┘

优势：
- 不可移动的内核数据聚集在一起
- 可移动的用户页面聚集在一起
- 需要大块连续内存时，可以迁移 MOVABLE 页面
```

**迁移类型的作用**：

| 类型 | 用途 | 是否可移动 | 示例 |
|------|------|----------|------|
| **UNMOVABLE** | 内核数据 | 否 | 内核栈、页表、kmalloc 分配 |
| **MOVABLE** | 用户页面 | 是 | 匿名页、文件映射页 |
| **RECLAIMABLE** | 可回收 | 是（通过回收） | 页缓存、dentry 缓存 |
| **CMA** | 连续内存分配器 | 是 | DMA 缓冲区（需要连续物理内存） |

### 2.5 水位线（Watermark）

每个 zone 有三个水位线，控制内存分配行为：

```
zone 内存水位线：

  Total pages
      │
      │   ┌─────────────────┐
      │   │                 │
      │   │   高水位 (high)  │ ← kswapd 停止回收
      │   ├─────────────────┤
      │   │                 │
      │   │   低水位 (low)   │ ← kswapd 开始回收
      │   ├─────────────────┤
      │   │                 │
      │   │   最小水位 (min) │ ← 普通分配失败，只允许 PF_MEMALLOC
      │   ├─────────────────┤
      │   │   紧急预留       │
      ▼   └─────────────────┘
```

**水位线的作用**：

```c
// Linux Kernel - mm/page_alloc.c

/*
 * 分配路径根据水位线的不同行为
 */
static struct page *__alloc_pages_nodemask(gfp_t gfp_mask,
                                            unsigned int order,
                                            struct zonelist *zonelist,
                                            nodemask_t *nodemask)
{
    /* 快速路径：从 high watermark 分配 */
    page = get_page_from_freelist(gfp_mask, order, alloc_flags, &ac);
    if (likely(page))
        return page;

    /* 慢速路径：从 low watermark 分配，并唤醒 kswapd */
    alloc_flags = gfp_to_alloc_flags(gfp_mask);
    if (gfp_mask & __GFP_KSWAPD_RECLAIM)
        wake_all_kswapds(order, &ac);

    page = get_page_from_freelist(gfp_mask, order, alloc_flags, &ac);
    if (page)
        return page;

    /* 紧急路径：从 min watermark 分配（需要 PF_MEMALLOC） */
    page = __alloc_pages_direct_reclaim(...);
    if (page)
        return page;

    /* OOM killer */
    page = __alloc_pages_may_oom(...);
    return page;
}
```

---

## 三、Slab 分配器

### 3.1 Slab 的必要性

**为什么需要 Slab 分配器？**

伙伴系统只能分配 **2^n 页**的内存块（最小 4KB），但内核经常需要分配**小于 4KB 的对象**：

| 数据结构 | 大小 | 使用频率 |
|---------|------|---------|
| `task_struct` | ~1.7KB | 每个进程一个 |
| `inode` | ~600B | 每个打开的文件一个 |
| `dentry` | ~192B | 每个目录项一个 |
| `mm_struct` | ~1KB | 每个进程地址空间一个 |

如果直接用伙伴系统分配：
- **内部碎片严重**：分配 192B 的 dentry 需要 4KB 页，浪费 ~95%
- **频繁分配释放**：性能低下
- **无法缓存**：每次都重新初始化对象

**Slab 分配器的解决方案**：
1. **对象缓存**：为每种类型预先分配好的对象池
2. **批量分配**：从伙伴系统一次申请多页，切割成多个小对象
3. **Per-CPU 缓存**：减少锁竞争
4. **对象重用**：保持对象初始化状态

### 3.2 Slab 核心概念

```
Slab 分配器架构：

┌─────────────────────────────────────────────────────────┐
│  kmem_cache (对象缓存)                                   │
│  ├─ name: "task_struct"                                 │
│  ├─ object_size: 1728 bytes                             │
│  ├─ ctor: 构造函数（初始化对象）                         │
│  └─ Per-CPU slab:                                       │
│      CPU 0: [obj1] [obj2] [obj3] ...                    │
│      CPU 1: [obj4] [obj5] [obj6] ...                    │
├─────────────────────────────────────────────────────────┤
│  Slab (物理页容器)                                       │
│  ├─ 从伙伴系统申请的连续物理页（1-8 页）                 │
│  ├─ 切割成固定大小的对象                                 │
│  └─ 状态：满/部分满/空                                   │
│      ┌──────┬──────┬──────┬──────┬──────┐              │
│      │ obj1 │ obj2 │ obj3 │ obj4 │ obj5 │              │
│      └──────┴──────┴──────┴──────┴──────┘              │
└─────────────────────────────────────────────────────────┘
```

**核心数据结构关系**：

```
kmem_cache (缓存)
    ├─ cpu_slab (Per-CPU)
    │   ├─ freelist: 空闲对象链表
    │   └─ page: 当前使用的 slab 页面
    ├─ node[N] (Per-NUMA-Node)
    │   ├─ partial: 部分满的 slab 链表
    │   ├─ full: 满的 slab 链表（SLUB 不维护）
    │   └─ nr_partial: 部分满 slab 数量
    └─ 对象元数据
        ├─ size: 对象大小
        ├─ align: 对齐要求
        ├─ ctor: 构造函数
        └─ flags: 缓存标志
```

### 3.3 SLUB 分配器（当前主流）

Linux 内核目前主要使用 **SLUB** 分配器（SL: 前缀来自 Slab，UB: Unqueued Buddy）。

#### 3.3.1 SLUB 核心数据结构

```c
// Linux Kernel - include/linux/slub_def.h

struct kmem_cache {
    /* Per-CPU slab */
    struct kmem_cache_cpu __percpu *cpu_slab;

    /* Per-Node slab 链表 */
    struct kmem_cache_node *node[MAX_NUMNODES];

    /* 对象属性 */
    unsigned int size;          // 对象大小（包括元数据）
    unsigned int object_size;   // 实际对象大小
    unsigned int offset;        // freelist 指针偏移
    unsigned int align;         // 对齐要求

    /* Slab 分配参数 */
    gfp_t allocflags;           // 分配标志
    int refcount;               // 引用计数
    void (*ctor)(void *);       // 构造函数

    /* 缓存名称 */
    const char *name;

    /* 链表节点（所有缓存的链表） */
    struct list_head list;

    /* ... 更多字段 ... */
};

struct kmem_cache_cpu {
    void **freelist;            // 空闲对象链表
    unsigned long tid;          // Transaction ID（检测竞态）
    struct page *page;          // 当前 slab 页面
    struct page *partial;       // 本地部分满 slab 链表
};

struct kmem_cache_node {
    spinlock_t list_lock;       // 保护链表的锁
    unsigned long nr_partial;   // 部分满 slab 数量
    struct list_head partial;   // 部分满 slab 链表
    atomic_long_t nr_slabs;     // 总 slab 数量
    atomic_long_t total_objects;// 总对象数量
};
```

#### 3.3.2 SLUB 分配流程

```c
// Linux Kernel - mm/slub.c

/*
 * SLUB 分配流程（快速路径）
 */
void *kmem_cache_alloc(struct kmem_cache *s, gfp_t gfpflags)
{
    void *ret;

    /* 快速路径：从 Per-CPU freelist 分配 */
    ret = slab_alloc(s, gfpflags, _RET_IP_);
    return ret;
}

static __always_inline void *slab_alloc(struct kmem_cache *s,
                                          gfp_t gfpflags,
                                          unsigned long addr)
{
    void **object;
    struct kmem_cache_cpu *c;
    unsigned long tid;

    /* 获取 Per-CPU slab */
    c = this_cpu_ptr(s->cpu_slab);
    tid = c->tid;

    /* 快速路径：freelist 非空 */
    object = c->freelist;
    if (unlikely(!object || !node_match(c, node)))
        goto slow_path;  // freelist 为空，进入慢速路径

    /* 从 freelist 取出对象 */
    c->freelist = get_freepointer(s, object);
    c->tid = next_tid(tid);

    return object;

slow_path:
    /* 慢速路径：重新加载 slab 或分配新 slab */
    return __slab_alloc(s, gfpflags, node, addr, c);
}

/*
 * SLUB 分配流程（慢速路径）
 */
static void *__slab_alloc(struct kmem_cache *s, gfp_t gfpflags, int node,
                           unsigned long addr, struct kmem_cache_cpu *c)
{
    void *freelist;
    struct page *page;

    /* 尝试从 Per-CPU partial 链表获取 slab */
    page = c->page;
    if (!page) {
        if (c->partial) {
            page = c->partial;
            c->partial = page->next;
            c->page = page;
            goto load_freelist;
        }
    }

    /* 尝试从 Per-Node partial 链表获取 slab */
    freelist = get_partial(s, gfpflags, node, c);
    if (freelist)
        return freelist;

    /* 都没有，从伙伴系统分配新 slab */
    page = new_slab(s, gfpflags, node);
    if (unlikely(!page)) {
        /* OOM */
        return NULL;
    }

    c->page = page;

load_freelist:
    freelist = page->freelist;
    page->freelist = NULL;
    c->freelist = get_freepointer(s, freelist);
    return freelist;
}

/*
 * 从伙伴系统分配新 slab
 */
static struct page *new_slab(struct kmem_cache *s, gfp_t flags, int node)
{
    struct page *page;
    void *start;
    void *p;
    int order;

    /* 计算需要多少页（通常 1-2 页） */
    order = oo_order(s->oo);

    /* 从伙伴系统分配 */
    page = alloc_slab_page(s, flags, node, order);
    if (!page)
        return NULL;

    /* 初始化 slab 页面 */
    start = page_address(page);

    /* 构建 freelist：将所有对象链接起来 */
    for (p = start; p < start + s->size * s->objects; p += s->size) {
        set_freepointer(s, p, p + s->size);
    }
    set_freepointer(s, p - s->size, NULL);  // 最后一个指向 NULL

    page->freelist = start;
    page->inuse = 0;
    page->frozen = 1;

    return page;
}
```

### 3.4 kmalloc() 与通用对象缓存

`kmalloc()` 是内核最常用的分配接口，基于**按大小组织的通用缓存**：

```c
// Linux Kernel - mm/slab_common.c

/*
 * kmalloc 通用缓存（按大小）
 */
struct kmem_cache *kmalloc_caches[NR_KMALLOC_TYPES][KMALLOC_SHIFT_HIGH + 1];

/*
 * 大小类别：
 * 8, 16, 32, 64, 96, 128, 192, 256, 512, 1024, 2048, 4096, 8192, ...
 */
static struct {
    const char *name;
    unsigned int size;
} const kmalloc_info[] __initconst = {
    {NULL,                      0},     {"kmalloc-8",           8},
    {"kmalloc-16",             16},     {"kmalloc-32",          32},
    {"kmalloc-64",             64},     {"kmalloc-96",          96},
    {"kmalloc-128",           128},     {"kmalloc-192",        192},
    {"kmalloc-256",           256},     {"kmalloc-512",        512},
    {"kmalloc-1k",           1024},     {"kmalloc-2k",        2048},
    {"kmalloc-4k",           4096},     {"kmalloc-8k",        8192},
    // ...
};

/*
 * kmalloc 实现
 */
void *kmalloc(size_t size, gfp_t flags)
{
    struct kmem_cache *s;
    void *ret;

    /* 大于 KMALLOC_MAX_CACHE_SIZE，直接用伙伴系统 */
    if (unlikely(size > KMALLOC_MAX_CACHE_SIZE))
        return kmalloc_large(size, flags);

    /* 找到合适的大小类别 */
    s = kmalloc_slab(size, flags);
    if (unlikely(ZERO_OR_NULL_PTR(s)))
        return s;

    /* 从对应缓存分配 */
    ret = slab_alloc(s, flags, _RET_IP_);
    return ret;
}

/*
 * 选择合适的 kmalloc 缓存
 */
static __always_inline struct kmem_cache *kmalloc_slab(size_t size,
                                                         gfp_t flags)
{
    int index;

    /* 计算索引（向上取整到 2 的幂） */
    if (size <= 192)
        index = size_index[size_index_elem(size)];
    else
        index = fls(size - 1);

    return kmalloc_caches[kmalloc_type(flags)][index];
}
```

**kmalloc 示例**：

```c
/* 分配 100 字节 */
ptr = kmalloc(100, GFP_KERNEL);
// 实际从 kmalloc-128 缓存分配（内部碎片 28 字节）

/* 分配 5000 字节 */
ptr = kmalloc(5000, GFP_KERNEL);
// 实际从 kmalloc-8k 缓存分配（内部碎片 ~3KB）

/* 分配 10000 字节 */
ptr = kmalloc(10000, GFP_KERNEL);
// 超过 KMALLOC_MAX_CACHE_SIZE，直接从伙伴系统分配 3 页（12KB）
```

---

## 四、从 memblock 到 buddy allocator 的过渡

### 4.1 启动时的内存分配器演化

```mermaid
flowchart LR
    Bootloader["Bootloader<br>（GRUB 堆栈）"]
    Memblock["memblock<br>（早期分配器）"]
    Buddy["Buddy Allocator<br>（主分配器）"]
    Slab["Slab/SLUB<br>（小对象分配器）"]

    Bootloader -->|"e820__memblock_setup()"| Memblock
    Memblock -->|"free_area_init()<br>memblock_free_all()"| Buddy
    Buddy -->|"kmem_cache_init()"| Slab

    style Bootloader fill:#FFE4B5
    style Memblock fill:#90EE90
    style Buddy fill:#87CEEB
    style Slab fill:#98FB98
```

### 4.2 memblock 的作用与限制

**memblock** 是内核启动早期的临时分配器：

| 特性 | memblock | Buddy Allocator |
|------|----------|----------------|
| **使用时期** | setup_arch() 到 mem_init() | mem_init() 之后 |
| **分配粒度** | 任意大小（字节级） | 2^n 页（页级） |
| **是否支持释放** | 否（简化设计） | 是 |
| **性能** | 线性搜索，慢 | 对数时间，快 |
| **用途** | 页表、early 数据结构 | 所有内核内存分配 |

### 4.3 过渡流程

```c
// Linux Kernel - mm/page_alloc.c & mm/memblock.c

/*
 * Step 1: setup_arch() 中初始化 memblock
 */
void __init setup_arch(char **cmdline_p)
{
    /* 解析 E820，初始化 memblock */
    e820__memory_setup();
    max_pfn = e820__end_of_ram_pfn();
    e820__memblock_setup();  // 将 E820_TYPE_RAM 加入 memblock.memory

    /* 使用 memblock 分配页表、early 数据结构 */
    init_mem_mapping();      // 从 memblock 分配页表页
    initmem_init();
    paging_init();           // 初始化 zone
}

/*
 * Step 2: start_kernel() → mm_init() → mem_init() 转交给 buddy
 */
void __init mem_init(void)
{
    /* 将 memblock 中的空闲内存全部转交给 buddy allocator */
    memblock_free_all();

    /* 释放 memblock 自身 */
    memblock_discard();

    /* 此后 memblock 不再可用 */
}

/*
 * Step 3: memblock_free_all() 实现
 */
unsigned long __init memblock_free_all(void)
{
    unsigned long pages = 0;
    struct memblock_region *r;

    /* 遍历 memblock.memory 中的所有区域 */
    for_each_free_mem_range(i, NUMA_NO_NODE, MEMBLOCK_NONE, &start, &end, NULL) {
        /* 计算页框号 */
        unsigned long start_pfn = PFN_UP(start);
        unsigned long end_pfn = PFN_DOWN(end);

        /* 将每个页框加入 buddy allocator */
        for (pfn = start_pfn; pfn < end_pfn; pfn++) {
            if (!memblock_is_reserved(pfn)) {
                __free_pages_bootmem(pfn_to_page(pfn), pfn, 0);
                pages++;
            }
        }
    }

    return pages;
}

/*
 * Step 4: 将单个页加入 buddy allocator
 */
void __init __free_pages_bootmem(struct page *page, unsigned long pfn,
                                  unsigned int order)
{
    /* 初始化 page 结构 */
    __ClearPageReserved(page);
    set_page_count(page, 0);
    set_page_refcounted(page);

    /* 加入 buddy allocator 的 free_area */
    __free_pages(page, order);
}
```

---

## 五、性能优化与最佳实践

### 5.1 Per-CPU 缓存

Per-CPU 缓存是 Slab 分配器的关键优化：

```
Per-CPU 缓存优势：

传统方式（全局锁）：
CPU 0: lock → alloc → unlock
CPU 1: lock (wait) → alloc → unlock  ← 锁竞争

Per-CPU 缓存（无锁）：
CPU 0: alloc (from CPU 0 cache)  ← 无锁
CPU 1: alloc (from CPU 1 cache)  ← 无锁
```

**实现细节**：

```c
/*
 * Per-CPU 分配（无锁快速路径）
 */
static __always_inline void *slab_alloc(struct kmem_cache *s, gfp_t gfpflags)
{
    struct kmem_cache_cpu *c;

    /* 禁用抢占（不禁用中断） */
    local_irq_save(flags);

    /* 获取当前 CPU 的缓存 */
    c = this_cpu_ptr(s->cpu_slab);

    /* 从 freelist 分配（无需加锁） */
    object = c->freelist;
    if (likely(object)) {
        c->freelist = get_freepointer(s, object);
        local_irq_restore(flags);
        return object;
    }

    local_irq_restore(flags);

    /* freelist 为空，进入慢速路径（可能需要加锁） */
    return __slab_alloc(s, gfpflags, node, addr, c);
}
```

### 5.2 对象重用与缓存效应

Slab 分配器保持对象的**构造状态**，提升缓存命中率：

```c
/*
 * 创建专用缓存
 */
struct kmem_cache *my_cache = kmem_cache_create(
    "my_object",                // 缓存名称
    sizeof(struct my_object),   // 对象大小
    0,                          // 对齐（0 = 默认）
    SLAB_HWCACHE_ALIGN,         // 标志：cache-line 对齐
    my_object_ctor              // 构造函数（可选）
);

/*
 * 构造函数：只在对象首次分配时调用
 */
void my_object_ctor(void *obj)
{
    struct my_object *o = obj;

    /* 初始化不变的字段 */
    spin_lock_init(&o->lock);
    INIT_LIST_HEAD(&o->list);
    o->magic = MY_MAGIC;

    /* 可变字段在 alloc 时初始化 */
}

/*
 * 分配对象（构造函数已调用，字段已初始化）
 */
struct my_object *obj = kmem_cache_alloc(my_cache, GFP_KERNEL);

/* 只需初始化可变字段 */
obj->data = NULL;
obj->refcount = 1;

/*
 * 释放对象（不销毁，保持构造状态）
 */
kmem_cache_free(my_cache, obj);
// 对象回到 freelist，lock/list/magic 仍然有效

/*
 * 下次分配（重用对象，cache 热度高）
 */
obj = kmem_cache_alloc(my_cache, GFP_KERNEL);
// 对象的 lock/list/magic 仍在 CPU cache 中，访问更快
```

### 5.3 内存分配标志（GFP Flags）

```c
/*
 * 常用 GFP 标志
 */
#define GFP_KERNEL      (__GFP_RECLAIM | __GFP_IO | __GFP_FS)
#define GFP_ATOMIC      __GFP_HIGH
#define GFP_USER        (__GFP_RECLAIM | __GFP_IO | __GFP_FS | __GFP_HARDWALL)
#define GFP_DMA         __GFP_DMA
#define GFP_DMA32       __GFP_DMA32

/*
 * 使用场景
 */

/* 场景 1：进程上下文，可睡眠 */
ptr = kmalloc(size, GFP_KERNEL);  // 可以触发内存回收、I/O

/* 场景 2：中断上下文，不可睡眠 */
ptr = kmalloc(size, GFP_ATOMIC);  // 不能睡眠，失败率高

/* 场景 3：需要 DMA 的内存（< 16MB） */
ptr = kmalloc(size, GFP_KERNEL | GFP_DMA);

/* 场景 4：32 位 DMA 的内存（< 4GB） */
ptr = kmalloc(size, GFP_KERNEL | GFP_DMA32);
```

---

## 六、参考文档与进一步阅读

### 核心文档

- **[Linux 内核分页机制完整指南](LINUX_PAGING_COMPLETE_GUIDE.md)** - 分页机制与物理内存管理的关系
- **[LINUX_KERNEL_INIT.md](LINUX_KERNEL_INIT.md)** - 内核启动流程中的内存管理初始化

### 源码参考

| 文件 | 说明 |
|------|------|
| `mm/page_alloc.c` | 伙伴系统核心实现 |
| `mm/slub.c` | SLUB 分配器实现 |
| `mm/memblock.c` | memblock 早期分配器 |
| `include/linux/mmzone.h` | zone 和 free_area 数据结构 |
| `include/linux/slub_def.h` | SLUB 数据结构定义 |
| `include/linux/gfp.h` | GFP 标志定义 |

### 延伸主题

- **内存回收（Page Reclaim）**：kswapd、LRU 算法、页面回收策略
- **内存压缩（Memory Compaction）**：减少外部碎片
- **巨页（Huge Pages）**：2MB/1GB 大页支持
- **CMA（Contiguous Memory Allocator）**：连续内存分配器
- **Memcg（Memory Control Group）**：内存控制组

---

**文档版本**：基于 Linux 内核 v6.x 源码整理
**最后更新**：2026-02
**维护者**：Linux 内核启动文档项目
