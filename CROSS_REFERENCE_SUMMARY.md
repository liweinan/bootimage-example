# 文档交叉引用总结

## 新增文档及其交叉引用

### 1. SOLUTION_ICACHE_MYSTERY.md
**主题**：extract_kernel 代码为什么不会被覆盖的完整解答

**被引用位置**：
- `LINUX_KERNEL_INIT.md` - 顶部"相关文档"部分
- `LINUX_KERNEL_INIT.md` - "原地解压"章节开头
- `LINUX_KERNEL_INIT.md` - 流程图中 extract_kernel() 调用处
- `LINUX_KERNEL_INIT.md` - "参考资料"部分
- `INVESTIGATION_SUMMARY.md` - 相关文档列表

**核心内容**：
- I-cache 理论的实验验证（证伪）
- vmlinuz 文件结构分析
- 运行时内存布局详解
- 最终答案：extract_kernel 在 VO 范围外，不会被覆盖

### 2. WHY_RELOCATE_COMPRESSED_KERNEL.md
**主题**：为什么压缩内核要从1MB重定位到高地址（KASLR 分析）

**被引用位置**：
- `LINUX_KERNEL_INIT.md` - 顶部"相关文档"部分
- `LINUX_KERNEL_INIT.md` - "关键地址说明"部分
- `LINUX_KERNEL_INIT.md` - 流程图中 rep movsq 处（多处）
- `LINUX_KERNEL_INIT.md` - "原地解压"章节开头
- `LINUX_KERNEL_INIT.md` - 寄存器说明表（%ebx）
- `LINUX_KERNEL_INIT.md` - "参考资料"部分

**核心内容**：
- KASLR 场景分析
- CONFIG_RELOCATABLE 配置详解
- 重定位的必要性分析
- 代码流程详解

### 3. INVESTIGATION_SUMMARY.md
**主题**：I-cache 理论验证与完整调查过程

**被引用位置**：
- `LINUX_KERNEL_INIT.md` - 顶部"相关文档"部分
- `LINUX_KERNEL_INIT.md` - "原地解压"章节开头
- `LINUX_KERNEL_INIT.md` - "参考资料"部分
- `SOLUTION_ICACHE_MYSTERY.md` - 相关文档列表

**核心内容**：
- 调查时间线
- I-cache 测试程序设计与结果
- 错误假设的分析
- 真相发现过程

## LINUX_KERNEL_INIT.md 中的更新

### 顶部"相关文档"部分
新增"原地解压专题"分类，包含三个新文档的链接，并附简短说明。

### 关键地址说明
更新了 %rbx 的描述，从"约 22MB"修正为"约 38MB"，并添加链接到 WHY_RELOCATE_COMPRESSED_KERNEL.md。

### 流程图部分
在多处提到重定位（rep movsq）的地方添加了指向 WHY_RELOCATE_COMPRESSED_KERNEL.md 的链接。

### 寄存器说明表
在 %ebx 行添加了链接，说明为什么是 38MB 而不是之前认为的 22MB。

### 原地解压章节
- 章节开头添加了醒目的提示框，指向三个详细分析文档
- "参考资料"部分新增"详细分析专题"分类

## 文档间的引用关系图

```
LINUX_KERNEL_INIT.md（主文档）
    ├─→ SOLUTION_ICACHE_MYSTERY.md（为什么不覆盖）
    │   └─→ test_icache_v3.S（测试程序）
    │   └─→ README_ICACHE_TEST.md（测试说明）
    ├─→ WHY_RELOCATE_COMPRESSED_KERNEL.md（为什么重定位）
    │   └─→ CONFIG_RELOCATABLE 分析
    │   └─→ KASLR 场景分析
    └─→ INVESTIGATION_SUMMARY.md（调查过程）
        └─→ SOLUTION_ICACHE_MYSTERY.md
        └─→ test_icache_*.S（v1、v2、v3）
```

## 其他相关文档

### 已有文档
- `BOOT_FLOW.md` - 启动概述
- `GRUB_KERNEL_LOADING.md` - GRUB 加载内核
- `GRUB_UEFI_LONG_MODE_ANALYSIS.md` - GRUB UEFI 长模式
- `UEFI_VS_BIOS_BOOT.md` - UEFI vs BIOS
- `LINUX_KERNEL_SETUP_FLOW.md` - Setup 流程
- `LINUX_KERNEL_SETUP_ARCH_MEMORY.md` - setup_arch 内存
- `MMU_AND_PAGING.md` - MMU 与分页
- `X86_NEAR_VS_LONG_JUMP.md` - 跳转指令

### 测试程序
- `test_icache.S` - v1 版本（发现 RIP-relative 问题）
- `test_icache_v2.S` - v2 调试版本
- `test_icache_v3.S` - v3 最终版本（证伪 I-cache）
- `Makefile.icache` - 编译脚本
- `README_ICACHE_TEST.md` - 测试说明

## 更新统计

### 新增文档
- 3 个详细分析文档
- 3 个测试程序
- 1 个测试 Makefile
- 1 个测试说明文档

### 更新的文档
- `LINUX_KERNEL_INIT.md`：
  - 顶部相关文档列表：新增 3 个链接
  - 关键地址说明：1 处更新
  - 寄存器说明表：1 处更新
  - 流程图：4 处添加链接
  - 原地解压章节：章节开头 + 参考资料

### 交叉引用总数
- `LINUX_KERNEL_INIT.md` → 新文档：约 10 处引用
- 新文档间相互引用：约 3 处

## 验证清单

- [x] 顶部"相关文档"包含新文档
- [x] "关键地址说明"更新为正确的值
- [x] 流程图中的重定位步骤有链接
- [x] 寄存器说明表中的 %ebx 有说明
- [x] "原地解压"章节有醒目提示
- [x] "参考资料"部分完整
- [x] 新文档相互引用正确
- [x] 所有链接可点击（Markdown 格式正确）

## 建议的阅读顺序

**初次阅读**：
1. `LINUX_KERNEL_INIT.md` - 主流程
2. `WHY_RELOCATE_COMPRESSED_KERNEL.md` - 理解为什么重定位
3. `SOLUTION_ICACHE_MYSTERY.md` - 理解解压安全性

**深入研究**：
4. `INVESTIGATION_SUMMARY.md` - 了解调查过程
5. 测试程序（`test_icache_v3.S`）- 实验验证

**全面理解**：
6. 其他相关文档（GRUB、UEFI、MMU 等）
