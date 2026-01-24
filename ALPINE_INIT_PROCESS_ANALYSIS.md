# Alpine Linux Initramfs Init 启动过程详细分析

## 相关文档

- **[INITRAMFS_ANALYSIS.md](INITRAMFS_ANALYSIS.md)** - Initramfs 内容分析与 BusyBox 启动设置（通用指南）
- **[INITRAMFS_ANALYSIS_RESULT.md](INITRAMFS_ANALYSIS_RESULT.md)** - Alpine Linux Initramfs 实际分析结果
- **[BUSYBOX_SH_EXEC_INIT_DETAILS.md](BUSYBOX_SH_EXEC_INIT_DETAILS.md)** - BusyBox sh 执行 /init 脚本的实现细节（基于 Linux 内核源代码）

## 源代码位置

- **仓库**: `mkinitfs` (Alpine Linux initramfs 生成工具)
- **文件**: `initramfs-init.in` (init 脚本模板)
- **路径**: `/Users/weli/works/mkinitfs/initramfs-init.in`
- **行数**: 1125 行

## 启动流程概览

```
内核执行 /bin/sh (BusyBox) 或直接执行 /init（通过 shebang）
   ↓
BusyBox sh 读取并执行 /init 脚本
   ↓
/init 脚本初始化阶段
   ├─ 创建目录结构
   ├─ 安装 BusyBox 符号链接
   ├─ 挂载虚拟文件系统 (sysfs, devtmpfs, proc, devpts)
   ├─ 解析内核命令行参数
   ↓
/init 脚本主要逻辑
   ├─ 加载内核模块
   ├─ 配置网络（如果需要）
   ├─ 挂载根文件系统
   ├─ 安装 Alpine 系统
   └─ 切换到真正的根文件系统
```

## 详细启动流程分析

### 阶段 1: 初始化和环境设置 (行 471-515)

```bash
# 471-485: 创建基本目录结构
/bin/busybox mkdir -p \
    "$ROOT"/bin \
    "$ROOT"/sbin \
    "$ROOT"/usr/bin \
    "$ROOT"/usr/sbin \
    "$ROOT"/proc \
    "$ROOT"/sys \
    "$ROOT"/dev \
    "$sysroot" \
    "$ROOT"/media/cdrom \
    "$ROOT"/media/usb \
    "$ROOT"/tmp \
    "$ROOT"/etc \
    "$ROOT"/run/cryptsetup

# 487: 安装 BusyBox 符号链接
/bin/busybox --install -s

# 488: 设置 PATH
export PATH="$PATH:/usr/bin:/bin:/usr/sbin:/sbin"
```

**关键点**:
- `$ROOT` 变量：在 initramfs 中通常是空字符串，表示根目录 `/`
- `$sysroot` 变量：真正的根文件系统挂载点，默认是 `$ROOT/sysroot`
- `busybox --install -s`：创建所有 BusyBox 工具的符号链接

### 阶段 2: 挂载虚拟文件系统 (行 494-513)

```bash
# 494: 确保 /dev/null 存在
[ -c /dev/null ] || $MOCK mknod -m 666 /dev/null c 1 3

# 496: 挂载 sysfs
$MOCK mount -t sysfs -o noexec,nosuid,nodev sysfs /sys

# 497-498: 挂载 devtmpfs 或 tmpfs 作为 /dev
$MOCK mount -t devtmpfs -o exec,nosuid,mode=0755,size=2M devtmpfs /dev 2>/dev/null \
    || $MOCK mount -t tmpfs -o exec,nosuid,mode=0755,size=2M tmpfs /dev

# 503: 确保 /dev/kmsg 存在（用于内核日志）
[ -c /dev/kmsg ] || $MOCK mknod -m 660 /dev/kmsg c 1 11

# 505: 挂载 proc
$MOCK mount -t proc -o noexec,nosuid,nodev proc /proc

# 507-509: 设置 pty 设备
[ -c /dev/ptmx ] || $MOCK mknod -m 666 /dev/ptmx c 5 2
[ -d /dev/pts ] || $MOCK mkdir -m 755 /dev/pts
$MOCK mount -t devpts -o gid=5,mode=0620,noexec,nosuid devpts /dev/pts

# 512-513: 挂载共享内存
mkdir -p "$ROOT"/dev/shm
$MOCK mount -t tmpfs -o nodev,nosuid,noexec shm /dev/shm
```

**关键点**:
- 这些虚拟文件系统是 Linux 内核提供的，用于系统管理和设备访问
- `/dev/kmsg` 用于写入内核日志（`echo "message" > /dev/kmsg`）

### 阶段 3: 解析内核命令行参数 (行 516-589)

```bash
# 518: 读取内核命令行
set -- $(cat "$ROOT"/proc/cmdline)

# 520-566: 定义支持的内核参数列表
myopts="BOOTIF
    alpine_repo
    apkovl
    init
    init_args
    ip
    modules
    root
    rootfstype
    ..."

# 568-589: 解析参数
for opt; do
    case "$opt" in
    s|single|1)
        SINGLEMODE=yes
        continue
        ;;
    console=*)
        # 处理控制台参数
        ;;
    esac
    
    # 解析其他参数
    for i in $myopts; do
        case "$opt" in
        $i=*)  eval "KOPT_${i}"='${opt#*=}';;
        $i)    eval "KOPT_${i}=yes";;
        no$i)  eval "KOPT_${i}=no";;
        esac
    done
done
```

**关键参数**:
- `root=`: 指定根文件系统设备（如 `root=/dev/ram0` 或 `root=/dev/sda1`）
- `init=`: 指定 init 程序路径（默认 `/sbin/init`）
- `modules=`: 预加载的内核模块
- `alpine_repo=`: Alpine 软件源
- `ip=`: 网络配置

### 阶段 4: 加载内核模块 (行 688-703)

```bash
# 689-698: 加载启动驱动
ebegin "Loading boot drivers"

$MOCK modprobe -a $(echo "$KOPT_modules $rootfstype" | tr ',' ' ' ) loop squashfs simpledrm 2> /dev/null

# 从 /etc/modules 加载模块
if [ -f "$ROOT"/etc/modules ] ; then
    sed 's/\#.*//g' < /etc/modules |
    while read module args; do
        $MOCK modprobe -q $module $args
    done
fi
eend 0
```

**关键点**:
- 加载 `loop` 和 `squashfs` 模块（用于挂载 modloop）
- 加载用户指定的模块（通过 `modules=` 参数）
- 加载根文件系统类型对应的模块（如 `ext4`, `xfs` 等）

### 阶段 5: 根文件系统处理

#### 情况 A: 指定了 `root=` 参数（行 763-835）

```bash
if [ -n "$KOPT_root" ]; then
    # 765-768: 使用 nlplug-findfs 挂载根文件系统
    ebegin "Mounting root"
    $MOCK nlplug-findfs $cryptopts -p /sbin/mdev ${KOPT_debug_init:+-d} \
        ${KOPT_uevent_buf_size:+-U $KOPT_uevent_buf_size} \
        $KOPT_root
    
    # 770-773: 单用户模式
    if [ "$SINGLEMODE" = "yes" ]; then
        echo "Entering single mode. Type 'exit' to continue booting."
        sh  # 启动 shell
    fi
    
    # 775-778: Btrfs 文件系统扫描
    if echo "$KOPT_modules $rootfstype" | grep -qw btrfs; then
        /sbin/btrfs device scan >/dev/null
    fi
    
    # 780: 从磁盘恢复（休眠恢复）
    resume_from_disk
    
    # 782-805: 挂载根文件系统
    if [ "$KOPT_overlaytmpfs" = "yes" ]; then
        # 使用 overlay 文件系统
        # ...
    else
        if [ "$rootfstype" = "zfs" ]; then
            prepare_zfs_root
        fi
        # 挂载根文件系统到 $sysroot
        $MOCK mount ${rootfstype:+-t} ${rootfstype} \
            -o ${KOPT_rootflags:-ro} \
            ${KOPT_root#ZFS=} $sysroot
    fi
    
    # 809-825: 挂载 /usr（如果 fstab 中指定）
    if [ -r "$sysroot/etc/fstab" ] && [ "$KOPT_usrflags" != "disable" ]; then
        while read dev mnt fs mntopts chk; do
            if [ "$mnt" = "/usr" ]; then
                ebegin "Mounting /usr"
                # ...
                $MOCK mount -t $fs -o ${KOPT_usrflags:-ro} $dev $sysroot/usr
            fi
        done < $sysroot/etc/fstab
    fi
    
    # 827-834: 移动挂载点并切换到新根
    cat "$ROOT"/proc/mounts 2>/dev/null | while read DEV DIR TYPE OPTS ; do
        if [ "$DIR" != "/" -a "$DIR" != "$sysroot" -a "$DIR" != "$sysroot/usr" -a -d "$DIR" ]; then
            mkdir -p $sysroot/$DIR
            $MOCK mount -o move $DIR $sysroot/$DIR
        fi
    done
    $MOCK sync
    
    # 834: 切换到真正的根文件系统
    exec switch_root $switch_root_opts $sysroot $chart_init "$KOPT_init" $KOPT_init_args
    recovery_shell
fi
```

**关键点**:
- `nlplug-findfs`: 用于查找和挂载根文件系统设备
- `switch_root`: 切换到真正的根文件系统并执行 `/sbin/init`
- 如果 `root=/dev/ram0`，会挂载 initramfs 本身作为根文件系统

#### 情况 B: 没有指定 `root=` 参数（Diskless 模式，行 838-1124）

这是 Alpine Linux 的 **Diskless 模式**，用于从网络或可移动媒体启动：

```bash
# 840-844: 确定是否需要网络
if $do_networking; then
    repoopts="-n"
else
    repoopts="-b $repofile"
fi

# 847-852: 挂载启动媒体
ebegin "Mounting boot media"
$MOCK nlplug-findfs $cryptopts -p /sbin/mdev ${KOPT_debug_init:+-d} \
    ${KOPT_usbdelay:+-t $(( $KOPT_usbdelay * 1000 ))} \
    ${KOPT_uevent_buf_size:+-U $KOPT_uevent_buf_size} \
    $repoopts -a "$ROOT"/tmp/apkovls
eend $?

# 854-857: 配置网络（如果需要）
if $do_networking; then
    configure_ip
fi

# 860-863: 单用户模式
if [ "$SINGLEMODE" = "yes" ]; then
    echo "Entering single mode. Type 'exit' to continue booting."
    sh
fi

# 865-876: 挂载 tmpfs 作为 sysroot
rootflags="mode=0755"
if [ -n "$KOPT_root_size" ]; then
    rootflags="$rootflags,size=$KOPT_root_size"
fi
$MOCK mount -t tmpfs -o $rootflags tmpfs $sysroot

# 882-896: 处理 apkovl（Alpine overlay 文件）
# ...

# 1023-1074: 安装 Alpine 系统到 sysroot
ebegin "Installing packages to root filesystem"
# 使用 apk 安装包到 $sysroot
$MOCK apk add --root $sysroot $repo_opt $apkflags $pkgs
eend 0

# 1110-1121: 切换到新根
cat "$ROOT"/proc/mounts 2>/dev/null | while read DEV DIR TYPE OPTS ; do
    if [ "$DIR" != "/" -a "$DIR" != "$sysroot" -a -d "$DIR" ]; then
        mkdir -p $sysroot/$DIR
        $MOCK mount -o move $DIR $sysroot/$DIR
    fi
done
sync

[ "$KOPT_splash" = "init" ] && echo exit > $sysroot/$splashfile
echo ""
exec switch_root $switch_root_opts $sysroot $chart_init "$KOPT_init" $KOPT_init_args
```

**关键点**:
- Diskless 模式会创建一个临时的 tmpfs 根文件系统
- 使用 `apk` 包管理器安装 Alpine 系统到 tmpfs
- 最后同样使用 `switch_root` 切换到新根

### 阶段 6: 错误处理和恢复 Shell (行 36-44)

```bash
recovery_shell() {
    if [ -n "$KOPT_panic" ]; then
        # 紧急 shell 被禁用，让内核 panic
        exit
    fi
    echo "Launching initramfs emergency recovery shell."
    echo "$1"
    /bin/busybox sh  # 启动恢复 shell
}
```

**调用场景**:
- `eend()` 函数在任务失败时调用 `recovery_shell`
- 如果 `$KOPT_init` 不存在，调用 `recovery_shell`
- 如果 `switch_root` 失败，执行到脚本末尾的 `recovery_shell`

### 阶段 7: 切换到真正的根文件系统 (行 834, 1121)

```bash
exec switch_root $switch_root_opts $sysroot $chart_init "$KOPT_init" $KOPT_init_args
```

**`switch_root` 的作用**:
- 切换到 `$sysroot`（真正的根文件系统）
- 卸载 initramfs
- 执行 `$KOPT_init`（默认 `/sbin/init`）
- 传递 `$KOPT_init_args` 作为参数

**关键变量**:
- `$sysroot`: 真正的根文件系统挂载点（通常是 `/sysroot`）
- `$KOPT_init`: init 程序路径（默认 `/sbin/init`）
- `$switch_root_opts`: switch_root 的选项（如 `-c /dev/ttyS0` 用于控制台）

## 关键函数说明

### 1. `ebegin()` 和 `eend()` (行 12-34)

用于显示任务进度和结果：

```bash
ebegin() {
    last_emsg="$*"
    echo "$last_emsg..." > "$ROOT"/dev/kmsg
    [ "$KOPT_quiet" = yes ] && return 0
    echo -n " * $last_emsg: "
}

eend() {
    if [ "$1" = 0 ] || [ $# -lt 1 ] ; then
        echo "$last_emsg: ok." > "$ROOT"/dev/kmsg
        [ "$KOPT_quiet" = yes ] && return 0
        echo "ok."
    else
        # 失败时启动恢复 shell
        recovery_shell
    fi
}
```

### 2. `recovery_shell()` (行 36-44)

启动紧急恢复 shell：

```bash
recovery_shell() {
    if [ -n "$KOPT_panic" ]; then
        exit  # 如果设置了 panic 参数，直接退出让内核 panic
    fi
    echo "Launching initramfs emergency recovery shell."
    echo "$1"
    /bin/busybox sh  # 启动 BusyBox shell
}
```

### 3. `configure_ip()` (行 219-298)

配置网络接口和 IP 地址：

```bash
configure_ip() {
    # 解析 ip= 参数
    # 配置 DHCP 或静态 IP
    # 设置 DNS
}
```

### 4. `nlplug-findfs` (行 766, 848)

Alpine Linux 的工具，用于：
- 查找文件系统设备（通过 UUID、LABEL 等）
- 处理加密设备
- 挂载设备

## 启动流程对比

### 情况 1: `root=/dev/ram0` (当前配置)

```
1. 内核执行 /bin/sh (BusyBox)
2. BusyBox sh 执行 /init 脚本
3. /init 解析 root=/dev/ram0
4. nlplug-findfs 挂载 /dev/ram0 到 $sysroot
5. 由于 /dev/ram0 就是 initramfs，实际上没有真正的"切换"
6. 如果 $KOPT_init 不存在，启动恢复 shell
7. 或者执行 switch_root（但可能失败，因为已经是根文件系统）
```

### 情况 2: `root=/dev/sda1` (真实硬盘)

```
1. 内核执行 /bin/sh (BusyBox)
2. BusyBox sh 执行 /init 脚本
3. /init 解析 root=/dev/sda1
4. nlplug-findfs 挂载 /dev/sda1 到 $sysroot
5. 挂载 /usr（如果 fstab 中指定）
6. 移动所有挂载点到 $sysroot 下
7. exec switch_root $sysroot /sbin/init
8. 切换到真正的根文件系统，执行 /sbin/init
```

### 情况 3: 没有 `root=` 参数 (Diskless 模式)

```
1. 内核执行 /bin/sh (BusyBox)
2. BusyBox sh 执行 /init 脚本
3. /init 检测到没有 root= 参数
4. 挂载启动媒体（CD、USB 等）
5. 配置网络（如果需要）
6. 创建 tmpfs 作为 $sysroot
7. 使用 apk 安装 Alpine 系统到 $sysroot
8. exec switch_root $sysroot /sbin/init
9. 切换到新安装的系统，执行 /sbin/init
```

## 为什么启动后会进入 Shell？

### 对于 `root=/dev/ram0` 配置

1. **如果 `$KOPT_init` 不存在**:
   - 脚本在第 1104-1108 行检查 `$KOPT_init` 是否存在
   - 如果不存在，调用 `recovery_shell`，启动 `/bin/busybox sh`

2. **如果 `switch_root` 失败**:
   - 脚本在第 1121 行执行 `exec switch_root`
   - 如果失败，执行到第 1124 行的 `recovery_shell`

3. **单用户模式**:
   - 如果指定了 `single` 或 `1` 参数，在第 770-773 行启动 shell

### 对于 Diskless 模式

- 如果安装失败或 `switch_root` 失败，会启动恢复 shell

## 关键代码位置

| 功能 | 行号 | 说明 |
|------|------|------|
| 创建目录结构 | 471-485 | 创建基本目录 |
| 安装 BusyBox 符号链接 | 487 | `busybox --install -s` |
| 挂载虚拟文件系统 | 494-513 | sysfs, devtmpfs, proc, devpts |
| 解析内核参数 | 516-589 | 从 `/proc/cmdline` 读取 |
| 加载内核模块 | 688-698 | 加载驱动模块 |
| 挂载根文件系统 | 765-805 | 使用 nlplug-findfs |
| 切换到新根 | 834, 1121 | `exec switch_root` |
| 恢复 shell | 36-44, 1124 | `/bin/busybox sh` |

## 总结

Alpine Linux 的 initramfs init 脚本是一个复杂的 shell 脚本，负责：

1. **初始化环境**: 创建目录、挂载虚拟文件系统、安装 BusyBox 工具
2. **解析参数**: 从内核命令行读取配置
3. **加载驱动**: 加载必要的内核模块
4. **挂载根文件系统**: 使用 `nlplug-findfs` 查找并挂载
5. **安装系统** (Diskless 模式): 使用 `apk` 安装 Alpine 系统
6. **切换根**: 使用 `switch_root` 切换到真正的根文件系统
7. **错误处理**: 在失败时启动恢复 shell

对于 `root=/dev/ram0` 配置，脚本会尝试挂载 `/dev/ram0` 作为根文件系统，但由于 `/dev/ram0` 实际上就是 initramfs 本身，最终可能会启动恢复 shell 或直接使用 initramfs 作为根文件系统。
