# I-Cache 测试程序

## 目的

验证 CPU 指令缓存（I-cache）是否允许代码在内存被覆盖后继续执行原始指令。

## 测试原理

1. **原始代码**：`increment_and_return` 函数每次将计数器 +1
2. **修改代码**：`modified_increment_and_return` 函数每次将计数器 +100
3. **测试流程**：
   - 第一次调用：执行原始代码，循环10次，counter = 10
   - 覆盖代码：将 `increment_and_return` 的内存覆盖为 `modified_increment_and_return`
   - 第二次调用：如果 I-cache 有效，仍执行原始代码（counter = 10）；否则执行新代码（counter = 1000）

## 编译和运行

```bash
# 编译
make -f Makefile.icache

# 运行
make -f Makefile.icache run

# 或直接运行
./test_icache
```

## 预期结果

### 场景 1：I-cache 有效（支持理论）

```
Starting test: executing code that will be overwritten
Before overwrite: counter = 10
After overwrite: counter = 10
Original code executed! (I-cache working)
```

**解释**：即使内存被覆盖，CPU 仍从 I-cache 中执行原始指令。

### 场景 2：I-cache 无效（不支持理论）

```
Starting test: executing code that will be overwritten
Before overwrite: counter = 10
After overwrite: counter = 1000
Modified code executed! (I-cache NOT working)
```

**解释**：CPU 从内存读取了被覆盖后的新指令。

### 场景 3：可能的其他结果

- **程序崩溃**：现代 CPU 有缓存一致性机制，可能检测到代码修改并触发异常
- **不确定行为**：部分指令来自缓存，部分来自内存

## 重要说明

1. **编译选项 `-Wl,-N`**：设置代码段可写，允许程序修改自己的代码
2. **自我修改代码**：现代操作系统通常保护代码段，需要特殊权限
3. **CPU 缓存一致性**：现代 CPU 有复杂的缓存一致性协议，可能会检测到代码修改
4. **Linux kernel 场景**：kernel 引导时没有这些保护机制，环境更原始

## 与 Linux Kernel 的关联

如果此测试显示 I-cache 有效，那么可以推断：
- Linux kernel 的 `extract_kernel` 代码被覆盖后仍能执行
- CPU 从 I-cache 中执行已缓存的指令
- 这解释了为什么 kernel 不需要保护 `.text` 段

如果此测试显示 I-cache 无效，那么：
- Linux kernel 必定有其他机制保护 `extract_kernel` 代码
- 需要进一步研究 kernel 的内存布局和执行流程

## 进一步测试

如果需要更精确的测试，可以：
1. 使用 `mprotect()` 系统调用动态修改内存权限
2. 使用 `mmap()` 创建可执行和可写的内存区域
3. 添加 CPU 序列化指令（如 `cpuid`）强制刷新流水线
4. 使用 `clflush` 指令手动刷新缓存行
