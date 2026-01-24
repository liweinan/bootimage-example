# BusyBox sh 执行 /init 脚本的实现细节

## 相关文档

- **[INITRAMFS_ANALYSIS.md](INITRAMFS_ANALYSIS.md)** - Initramfs 内容分析与 BusyBox 启动设置（通用指南）
- **[INITRAMFS_ANALYSIS_RESULT.md](INITRAMFS_ANALYSIS_RESULT.md)** - Alpine Linux Initramfs 实际分析结果
- **[ALPINE_INIT_PROCESS_ANALYSIS.md](ALPINE_INIT_PROCESS_ANALYSIS.md)** - Alpine Linux Initramfs Init 启动过程详细分析（基于 mkinitfs 源代码）

## 关键发现：内核默认会尝试执行 `/init`

根据 Linux 内核源代码（`linux/init/main.c`），**内核默认会优先尝试执行 `/init`**！

### 源代码证据

**第 164 行**：
```c
static char *ramdisk_execute_command = "/init";
```

**第 1499-1504 行**（`kernel_init()` 函数）：
```c
if (ramdisk_execute_command) {
    ret = run_init_process(ramdisk_execute_command);
    if (!ret)
        return 0;
    pr_err("Failed to execute %s (error %d)\n",
           ramdisk_execute_command, ret);
}
```

**第 1595-1598 行**（`kernel_init_freeable()` 函数）：
```c
/*
 * check if there is an early userspace init.  If yes, let it do all
 * the work
 */
if (init_eaccess(ramdisk_execute_command) != 0) {
    ramdisk_execute_command = NULL;
    prepare_namespace();
}
```

## 完整的执行流程

### 内核执行 init 的完整顺序

```
内核初始化完成
   ↓
kernel_init_freeable() 阶段
   ├─ 检查 ramdisk_execute_command（默认 "/init"）是否可以访问
   │  ├─ 如果可访问：保留 ramdisk_execute_command = "/init"
   │  └─ 如果不可访问：设置 ramdisk_execute_command = NULL
   └─ 如果 ramdisk_execute_command 为 NULL，调用 prepare_namespace()
   ↓
kernel_init() 阶段
   ├─ 1. 如果 ramdisk_execute_command 存在（且可访问）
   │     └─ 执行 run_init_process(ramdisk_execute_command)
   │         └─ 即：run_init_process("/init")
   │
   ├─ 2. 如果 execute_command 存在（由 init= 参数设置）
   │     └─ 执行 run_init_process(execute_command)
   │
   ├─ 3. 如果 CONFIG_DEFAULT_INIT 配置了默认 init
   │     └─ 执行 run_init_process(CONFIG_DEFAULT_INIT)
   │
   └─ 4. 按顺序尝试：
       ├─ /sbin/init
       ├─ /etc/init
       ├─ /bin/init
       └─ /bin/sh
```

### 关键函数：`run_init_process()`

**第 1383-1396 行**：
```c
static int run_init_process(const char *init_filename)
{
    const char *const *p;

    argv_init[0] = init_filename;
    pr_info("Run %s as init process\n", init_filename);
    pr_debug("  with arguments:\n");
    for (p = argv_init; *p; p++)
        pr_debug("    %s\n", *p);
    pr_debug("  with environment:\n");
    for (p = envp_init; *p; p++)
        pr_debug("    %s\n", *p);
    return kernel_execve(init_filename, argv_init, envp_init);
}
```

**关键点**：
- `argv_init[0] = init_filename`：将 init 文件路径设置为 `argv[0]`
- 调用 `kernel_execve(init_filename, argv_init, envp_init)` 执行文件

### 当内核执行 `/init` 时的详细流程

```
内核调用 run_init_process("/init")
   ↓
设置 argv_init[0] = "/init"
   ↓
调用 kernel_execve("/init", argv_init, envp_init)
   ↓
内核的 execve 系统调用处理：
   ├─ 打开文件 /init
   ├─ 读取文件前 256 字节到 bprm->buf
   ├─ 检测到 bprm->buf[0] == '#' && bprm->buf[1] == '!'
   └─ 识别为脚本文件
   ↓
内核的 binfmt_script 模块处理（fs/binfmt_script.c）：
   ├─ load_script() 函数被调用
   ├─ 解析 shebang: #!/bin/sh
   ├─ 提取解释器: i_name = "/bin/sh"
   ├─ 重新构建 argv:
   │  ├─ argv[0] = "/bin/sh"  （解释器路径）
   │  └─ argv[1] = "/init"     （脚本文件路径）
   ├─ 打开解释器文件: open_exec("/bin/sh")
   └─ 递归调用 search_binary_handler() 执行解释器
   ↓
内核执行 /bin/sh（解析符号链接）
   ├─ /bin/sh -> /bin/busybox
   ├─ 加载 /bin/busybox
   ├─ 设置 argv[0] = "/bin/sh"
   ├─ 设置 argv[1] = "/init"  （脚本文件路径）
   └─ 跳转到用户空间
   ↓
BusyBox sh 功能执行
   ├─ 检查 argv[0] = "/bin/sh"，执行 sh 功能
   ├─ 检查 argv[1] = "/init"，打开并读取文件
   ├─ 读取 /init 文件内容
   └─ 解释执行脚本内容
```

## binfmt_script.c 的详细工作流程

### load_script() 函数（第 34-138 行）

```c
static int load_script(struct linux_binprm *bprm)
{
    // 1. 检查是否以 #! 开头
    if ((bprm->buf[0] != '#') || (bprm->buf[1] != '!'))
        return -ENOEXEC;
    
    // 2. 解析 shebang 行
    // 例如: #!/bin/sh
    // 提取: i_name = "/bin/sh"
    
    // 3. 重新构建 argv
    retval = remove_arg_zero(bprm);  // 移除原来的 argv[0]
    retval = copy_string_kernel(bprm->interp, bprm);  // 添加解释器路径
    bprm->argc++;
    
    if (i_arg) {
        // 如果有解释器参数，添加它
        retval = copy_string_kernel(i_arg, bprm);
        bprm->argc++;
    }
    
    // 4. 添加脚本文件路径作为参数
    retval = copy_string_kernel(i_name, bprm);
    bprm->argc++;
    
    // 5. 打开解释器文件
    file = open_exec(i_name);  // 打开 /bin/sh
    bprm->interpreter = file;
    
    return 0;
}
```

### 关键点

1. **`bprm->buf`**: 包含文件的前 256 字节（`BINPRM_BUF_SIZE`）
2. **shebang 解析**: 提取解释器路径和可选参数
3. **argv 重建**: 
   - 移除原来的 `argv[0]`（脚本文件路径）
   - 添加解释器路径作为新的 `argv[0]`
   - 添加脚本文件路径作为 `argv[1]`（或 `argv[2]`，如果有解释器参数）
4. **递归执行**: 内核递归调用 `search_binary_handler()` 执行解释器

## 完整的执行流程总结

### 对于 Alpine Linux initramfs（有 `/init` 文件）

```
1. 内核初始化完成
   ↓
2. kernel_init_freeable() 阶段
   ├─ init_eaccess("/init") 检查 /init 是否可以访问
   └─ 如果可访问，保留 ramdisk_execute_command = "/init"
   ↓
3. kernel_init() 阶段
   ├─ 检查 ramdisk_execute_command = "/init"（存在）
   └─ 调用 run_init_process("/init")
       ↓
4. kernel_execve("/init", ...)
   ├─ 打开 /init 文件
   ├─ 读取前 256 字节: "#!/bin/sh\n..."
   ├─ 检测到 #! 开头
   └─ binfmt_script 模块处理
       ↓
5. load_script() 处理
   ├─ 解析 shebang: #!/bin/sh
   ├─ 提取解释器: /bin/sh
   ├─ 重建 argv:
   │  ├─ argv[0] = "/bin/sh"
   │  └─ argv[1] = "/init"
   └─ 打开 /bin/sh 文件
       ↓
6. 内核执行 /bin/sh（递归调用 search_binary_handler）
   ├─ 解析符号链接: /bin/sh -> /bin/busybox
   ├─ 加载 /bin/busybox
   ├─ 设置 argv[0] = "/bin/sh"
   ├─ 设置 argv[1] = "/init"
   └─ 跳转到用户空间
       ↓
7. BusyBox sh 功能执行
   ├─ 检查 argv[0] = "/bin/sh"，执行 sh 功能
   ├─ 检查 argv[1] = "/init"，打开文件
   ├─ 读取 /init 文件内容
   └─ 解释执行脚本
```

## 关键代码位置总结

| 功能 | 文件 | 行号 | 说明 |
|------|------|------|------|
| 默认 ramdisk init | `init/main.c` | 164 | `ramdisk_execute_command = "/init"` |
| 检查 /init 可访问性 | `init/main.c` | 1595 | `init_eaccess(ramdisk_execute_command)` |
| 执行 ramdisk init | `init/main.c` | 1499-1504 | `run_init_process(ramdisk_execute_command)` |
| 执行 init 程序 | `init/main.c` | 1383-1396 | `run_init_process()` → `kernel_execve()` |
| Shebang 处理 | `fs/binfmt_script.c` | 34-138 | `load_script()` 解析 shebang 并执行解释器 |

## 答案

**BusyBox sh 执行 /init 脚本的实现细节**：

1. **内核默认会尝试执行 `/init`**：
   - `ramdisk_execute_command` 的默认值是 `"/init"`
   - 在 `kernel_init()` 中，如果 `ramdisk_execute_command` 存在且可访问，会优先执行它

2. **内核通过 shebang 处理执行脚本**：
   - 内核调用 `kernel_execve("/init", ...)`
   - 内核的 `binfmt_script` 模块检测到 `#!/bin/sh` shebang
   - 内核解析 shebang，提取解释器 `/bin/sh`
   - 内核执行 `/bin/sh /init`（将 `/init` 作为参数传递）

3. **BusyBox sh 接收脚本路径**：
   - BusyBox sh 的 `argv[0] = "/bin/sh"`
   - BusyBox sh 的 `argv[1] = "/init"`（脚本文件路径）
   - sh 打开并读取 `/init` 文件，解释执行

**总结**：内核**会**尝试执行 `/init`（通过 `ramdisk_execute_command`），然后通过 shebang 机制执行 `/bin/sh /init`，BusyBox sh 接收到 `/init` 作为参数并执行它。
