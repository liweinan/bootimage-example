# 参考文档目录

本目录包含《Linux 内核函数修饰符与调用约定》文档引用的所有权威规范。

## 文件清单

### ABI 规范

#### 1. x86_64-abi-0.99.pdf (557 KB)
- **标题**: System V Application Binary Interface - AMD64 Architecture Processor Supplement (Draft Version 0.99.6)
- **来源**: https://refspecs.linuxfoundation.org/elf/x86_64-abi-0.99.pdf
- **日期**: 2015年1月29日
- **关键章节**:
  - 第 3 章：低级系统信息（Low-Level System Information）
  - 第 3.2 节：函数调用序列（Function Calling Sequence）
  - Figure 3.4: Register Usage（寄存器使用表）

**本文档引用位置**:
- 1.2 节：x86-64 System V ABI 调用约定
- 寄存器使用表（Figure 3.4）

#### 2. abi386-4.pdf (1.0 MB)
- **标题**: System V Application Binary Interface - Intel386 Architecture Processor Supplement, Fourth Edition
- **来源**: https://refspecs.linuxbase.org/elf/abi386-4.pdf
- **日期**: 2015年1月29日
- **关键章节**:
  - 第 3 章：低级系统信息
  - 第 3.4 节：函数调用序列（Page 37-42）
  - Figure 3-16: Stack Frame（栈帧布局）

**本文档引用位置**:
- 1.3 节：x86-32 cdecl 调用约定
- 栈帧布局图（Figure 3-16）

### 技术分析文档

#### 3. agner_calling_conventions.pdf (1.0 MB)
- **标题**: Calling conventions for different C++ compilers and operating systems
- **作者**: Agner Fog
- **来源**: https://www.agner.org/optimize/calling_conventions.pdf
- **版本**: 2023年7月1日更新
- **关键章节**:
  - 第 7 章：64 位系统上的调用约定（Page 17-22）
  - Table 5: Function calling conventions comparison
  - Red Zone 说明（Page 20）

**本文档引用位置**:
- 1.2 节：Red Zone 机制
- 1.4 节：不同平台调用约定对比表

### GCC 编译器文档

#### 4. gcc_function_attributes.html (9.9 KB)
- **标题**: Function Attributes - Using the GNU Compiler Collection (GCC)
- **来源**: https://gcc.gnu.org/onlinedocs/gcc/Function-Attributes.html
- **日期**: 2026年2月15日下载
- **内容**: GCC 函数属性索引页

#### 5. gcc_common_function_attributes.html (127 KB)
- **标题**: Common Function Attributes - GCC Documentation
- **来源**: https://gcc.gnu.org/onlinedocs/gcc/Common-Function-Attributes.html
- **日期**: 2026年2月15日下载
- **关键属性说明**:
  - `noreturn` - 永不返回函数
  - `externally_visible` - 防止 LTO 优化删除
  - `cold` - 冷代码标记
  - `used` - 防止未使用符号删除

**本文档引用位置**:
- 2.2 节：__visible (externally_visible)
- 2.4 节：__noreturn
- 2.7 节：__cold, __used

## 使用指南

### 快速查找

1. **学习 x86-64 调用约定**:
   ```bash
   # 打开 x86_64-abi-0.99.pdf，跳转到第 3 章（约第 14 页）
   open x86_64-abi-0.99.pdf
   ```

2. **学习 x86-32 调用约定**:
   ```bash
   # 打开 abi386-4.pdf，跳转到第 3.4 节（约第 37 页）
   open abi386-4.pdf
   ```

3. **跨平台对比**:
   ```bash
   # 查看 Table 5（约第 19 页）
   open agner_calling_conventions.pdf
   ```

4. **查询 GCC 属性**:
   ```bash
   # 在浏览器中打开 HTML 文档，可以搜索关键字
   open gcc_common_function_attributes.html
   ```

### 命令行搜索

```bash
# 在 PDF 中搜索关键字（需要 pdfgrep 工具）
pdfgrep -i "register" x86_64-abi-0.99.pdf

# 在 HTML 中搜索属性
grep -i "noreturn" gcc_common_function_attributes.html
```

### 推荐阅读顺序

对于初学者：
1. 先读主文档的 1.1-1.3 节（调用约定基础）
2. 打开 `x86_64-abi-0.99.pdf` 第 3 章，对照阅读
3. 查看 `agner_calling_conventions.pdf` Table 5，理解不同平台差异
4. 阅读主文档的第 2 章（函数修饰符）
5. 需要时查询 GCC HTML 文档的具体属性说明

对于进阶读者：
1. 直接阅读 ABI 规范的原文
2. 对比 i386 和 x86-64 的差异
3. 研究 Agner Fog 的性能分析
4. 查看内核源码中的实际应用

## 版权说明

- **System V ABI 文档**: Copyright © 1997-2015 The Santa Cruz Operation, Inc. / Free Standards Group
- **Agner Fog 文档**: Copyright © 2004-2023 Agner Fog (允许免费分发)
- **GCC 文档**: Copyright © 1988-2026 Free Software Foundation, Inc. (GNU FDL 许可证)

这些文档仅用于学习和参考目的。

## 更新记录

- 2026-02-15: 初始下载，包含 5 个权威参考文档
