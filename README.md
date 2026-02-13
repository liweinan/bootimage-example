# 计算机底层系统学习项目

这是一个深入学习计算机底层系统的完整知识库，涵盖从 BIOS 到 Linux 内核的启动流程、内存管理、中断机制等核心主题。

项目包含：
- 100+ 篇深入技术文档，详细分析系统底层机制
- 引导扇区示例程序，演示裸机代码运行
- 完整的学习路径指南，适合不同层次的学习者
- 分析工具和验证脚本，帮助理解底层实现

<img width="2296" height="1410" alt="fe4f9ff229c104aee6d03f53d2dbee6c" src="https://github.com/user-attachments/assets/170fbdec-6b11-4e7a-8272-fccfcdb35d1e" />

---

## 📚 文档导读

**本项目包含 100+ 篇技术文档，涵盖从 BIOS 到 Linux 内核的完整启动流程。**

👉 **首次访问？请先阅读** [📖 文档导读指南 (READING_GUIDE.md)](READING_GUIDE.md)

导读包含：
- 🎯 **快速导航**：我想了解...（按主题快速定位）
- 🛤️ **学习路径推荐**：入门 → 进阶 → 专家（4条完整学习路径）
- 📊 **核心文档关系图**：理解文档间的依赖关系
- 🔍 **主题索引**：A-Z 快速查找

**推荐学习路径**：
- 💡 **入门**：启动流程基础（2-3天） → [查看路径](READING_GUIDE.md#-路径-1入门路径理解启动流程)
- 🧠 **进阶**：深入内存管理（1-2周） → [查看路径](READING_GUIDE.md#-路径-2进阶路径深入内存管理)
- 🔬 **专家**：中断与系统调用（1周） → [查看路径](READING_GUIDE.md#-路径-3专家路径中断与系统调用)
- 🔧 **专题**：GRUB 详解（5-7天） → [查看路径](READING_GUIDE.md#-路径-4grub-专题路径)

---

## 🚀 快速开始

想尝试运行引导扇区示例程序？

**前置要求：** 安装 NASM 和 QEMU
```bash
sudo apt update && sudo apt install nasm qemu-system-x86
```

**快速运行：**
```bash
make build    # 编译引导扇区程序
make run      # 在 QEMU 中运行
```

📖 **详细说明**：查看 [快速开始指南 (QUICKSTART.md)](QUICKSTART.md) 了解完整的编译、运行和退出方法。

---

## 📚 完整文档索引

本项目包含 100+ 篇技术文档，涵盖 BIOS、启动流程、中断、内存管理、GRUB、Linux 内核等各个主题。

完整的文档分类索引请查看：**[📑 文档索引 (DOCUMENT_INDEX.md)](DOCUMENT_INDEX.md)**
