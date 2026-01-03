# VNC Server 配置指南 - 使用 fvwm

## 安装 TigerVNC Server

```bash
sudo apt update
sudo apt install tigervnc-standalone-server tigervnc-common
```

## 安装 fvwm 窗口管理器

```bash
sudo apt install fvwm
```

## 安装 xterm 终端

```bash
sudo apt install xterm
```

xterm 是一个轻量级的 X11 终端模拟器，适合在 VNC 环境中使用。

## 首次启动 VNC Server（设置密码）

```bash
vncserver :1
```

首次运行时会提示设置 VNC 密码（用于远程连接）。

## 停止 VNC Server（如果正在运行）

```bash
vncserver -kill :1
```

## 配置 xterm 主题（可选）

### 创建 X 资源文件

编辑 `~/.Xresources` 文件来配置 xterm 主题：

```bash
nano ~/.Xresources
```

### Solarized Dark 主题示例

```bash
! xterm 主题配置 - Solarized Dark

xterm*background: #002b36
xterm*foreground: #839496
xterm*color0: #073642
xterm*color1: #dc322f
xterm*color2: #859900
xterm*color3: #b58900
xterm*color4: #268bd2
xterm*color5: #d33682
xterm*color6: #2aa198
xterm*color7: #eee8d5
xterm*color8: #002b36
xterm*color9: #cb4b16
xterm*color10: #586e75
xterm*color11: #657b83
xterm*color12: #839496
xterm*color13: #6c71c4
xterm*color14: #93a1a1
xterm*color15: #fdf6e3

! 字体设置
xterm*font: xft:DejaVu Sans Mono:size=12

! 光标设置
xterm*cursorColor: #839496
xterm*cursorBlink: true

! 滚动条
xterm*scrollBar: true
xterm*rightScrollBar: true

! 其他设置
xterm*saveLines: 10000
xterm*scrollTtyOutput: false
xterm*scrollKey: true
```

### Solarized Light 主题示例

```bash
! xterm 主题配置 - Solarized Light

xterm*background: #fdf6e3
xterm*foreground: #657b83
xterm*color0: #eee8d5
xterm*color1: #dc322f
xterm*color2: #859900
xterm*color3: #b58900
xterm*color4: #268bd2
xterm*color5: #d33682
xterm*color6: #2aa198
xterm*color7: #073642
```

### Monokai 主题示例

```bash
! xterm 主题配置 - Monokai

xterm*background: #272822
xterm*foreground: #f8f8f2
xterm*color0: #272822
xterm*color1: #f92672
xterm*color2: #a6e22e
xterm*color3: #f4bf75
xterm*color4: #66d9ef
xterm*color5: #ae81ff
xterm*color6: #a1efe4
xterm*color7: #f8f8f0
```

### 应用配置

保存文件后，加载配置：

```bash
xrdb ~/.Xresources
```

**注意：** 在 VNC 环境中，`~/.vnc/xstartup` 文件中的 `xrdb $HOME/.Xresources` 行会自动加载这些配置。

### 使用命令行参数启动（临时配置）

如果不想修改配置文件，可以在启动 xterm 时直接指定参数：

```bash
xterm -bg "#002b36" -fg "#839496" -fn "xft:DejaVu Sans Mono:size=12" &
```

## 配置 VNC 使用 fvwm

编辑 `~/.vnc/xstartup` 文件：

```bash
nano ~/.vnc/xstartup
```

将内容替换为（推荐使用简洁版本，避免卡住问题）：

**基础配置（不自动启动 xterm）：**
```bash
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
export PATH=/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin
xrdb $HOME/.Xresources
xsetroot -solid grey
exec fvwm
```

**自动启动 xterm 的配置：**
```bash
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
export PATH=/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin
xrdb $HOME/.Xresources
xsetroot -solid grey
xterm &
exec fvwm
```

**重要提示：** 添加 `export PATH` 行确保 fvwm 菜单中的程序（如 xterm）能够正确启动。

这样启动 VNC 时会自动打开一个 xterm 终端窗口。

**重要提示：** 不要使用包含 `exec /etc/vnc/xstartup` 或 `[ -x /etc/vnc/xstartup ] && exec /etc/vnc/xstartup` 的配置，这可能导致 VNC server 启动时卡住。

设置执行权限：

```bash
chmod +x ~/.vnc/xstartup
```

## 启动 VNC Server

### 基本启动
```bash
vncserver :1
```

### 使用详细模式启动（推荐用于调试）
```bash
vncserver :1 -verbose
```

### 使用详细模式并指定参数
```bash
vncserver :1 -verbose -geometry 1920x1080 -depth 24
```

### 前台运行模式（用于调试）
```bash
vncserver :1 -fg -verbose
```

**参数说明：**
- `-verbose` 或 `-v`：启用详细调试输出，显示启动过程的详细信息
- `-fg`：前台运行，不进入后台，方便查看实时输出
- `-geometry <width>x<height>`：设置桌面分辨率，如 `1920x1080`
- `-depth <number>`：设置颜色深度，常用值：16, 24, 32
- `-desktop <name>`：设置 VNC 桌面名称
- `-localhost [yes|no]`：是否只允许本地连接（默认 no）

## 配置 VNC Server 参数（可选）

编辑 `~/.vnc/config` 文件来设置分辨率等参数：

```bash
nano ~/.vnc/config
```

示例配置：

```
geometry=1920x1080
depth=24
dpi=96
```

## 连接 VNC

### 本地连接
```bash
# 如果已安装 vncviewer
vncviewer localhost:1
# 或
vncviewer :1
```

### 远程连接
```bash
vncviewer <服务器IP>:1
```

### 使用其他 VNC 客户端
- Windows: TightVNC Viewer, RealVNC Viewer
- macOS: 内置的 Screen Sharing (vnc://服务器IP:5901)
- Linux: Remmina, TigerVNC Viewer

## 常用命令

```bash
# 启动 VNC server（显示 :1，端口 5901）
vncserver :1

# 启动 VNC server（详细模式，推荐用于调试）
vncserver :1 -verbose

# 启动 VNC server（前台运行，实时查看输出）
vncserver :1 -fg -verbose

# 启动 VNC server（指定分辨率和颜色深度）
vncserver :1 -geometry 1920x1080 -depth 24 -verbose

# 列出所有运行的 VNC server
vncserver -list

# 查看运行的 VNC server 进程
ps aux | grep vnc

# 停止 VNC server
vncserver -kill :1

# 停止 VNC server（详细模式）
vncserver -kill :1 -verbose

# 停止所有 VNC server
vncserver -kill :*

# 清理过期的 VNC server 实例
vncserver -cleanstale

# 查看 VNC server 版本信息
vncserver -version

# 查看帮助信息
vncserver --help
vncserver -h
vncserver -?

# 查看 VNC server 日志
cat ~/.vnc/*:1.log

# 实时跟踪日志
tail -f ~/.vnc/*:1.log
```

## 防火墙配置（如果需要远程访问）

```bash
# Ubuntu UFW
sudo ufw allow 5901/tcp

# 或者使用 iptables
sudo iptables -A INPUT -p tcp --dport 5901 -j ACCEPT
```

## 设置开机自启动（可选）

创建 systemd 服务文件：

```bash
sudo nano /etc/systemd/system/vncserver@.service
```

内容：

```ini
[Unit]
Description=Start TightVNC server at startup
After=syslog.target network.target

[Service]
Type=forking
User=YOUR_USERNAME
PAMName=login
PIDFile=/home/YOUR_USERNAME/.vnc/%H:%i.pid
ExecStartPre=-/usr/bin/vncserver -kill :%i > /dev/null 2>&1
ExecStart=/usr/bin/vncserver :%i -geometry 1920x1080 -depth 24
ExecStop=/usr/bin/vncserver -kill :%i

[Install]
WantedBy=multi-user.target
```

替换 `YOUR_USERNAME` 为你的用户名，然后：

```bash
sudo systemctl daemon-reload
sudo systemctl enable vncserver@1.service
sudo systemctl start vncserver@1.service
```

## 故障排除

### 如果 vncserver 命令卡住

**问题：** `vncserver :1` 命令执行后没有返回，卡住了。

**解决方法：**

1. **按 Ctrl+C 中断命令**

2. **检查是否已有 VNC server 在运行：**
   ```bash
   ps aux | grep vnc
   vncserver -list
   ```

3. **如果已有运行，先停止：**
   ```bash
   vncserver -kill :1
   ```

4. **检查并修复 xstartup 文件：**
   
   问题可能出在 xstartup 文件中的 `exec /etc/vnc/xstartup` 这行。使用更简洁的版本：
   
   ```bash
   nano ~/.vnc/xstartup
   ```
   
   替换为：
   ```bash
   #!/bin/sh
   unset SESSION_MANAGER
   unset DBUS_SESSION_BUS_ADDRESS
   export PATH=/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin
   xrdb $HOME/.Xresources
   xsetroot -solid grey
   exec fvwm
   ```
   
   确保有执行权限：
   ```bash
   chmod +x ~/.vnc/xstartup
   ```

5. **使用详细模式启动查看错误（推荐）：**
   ```bash
   vncserver :1 -verbose
   ```
   这会显示详细的启动过程信息，包括：
   - X server 启动状态
   - 字体路径
   - 显示配置
   - 错误信息（如果有）

6. **前台运行模式（实时查看输出）：**
   ```bash
   vncserver :1 -fg -verbose
   ```
   使用 `-fg` 参数让 VNC server 在前台运行，可以实时看到所有输出信息。

7. **查看日志文件：**
   ```bash
   # 查看完整日志
   cat ~/.vnc/*:1.log
   
   # 实时跟踪日志
   tail -f ~/.vnc/*:1.log
   
   # 查看最近的错误
   tail -n 50 ~/.vnc/*:1.log | grep -i error
   ```

7. **如果首次启动需要设置密码，使用交互模式：**
   ```bash
   vncpasswd
   vncserver :1
   ```

### 如果 fvwm 菜单中的 xterm 无法启动

**问题：** 在 fvwm 菜单中点击 xterm 没有反应，无法启动终端。

**解决方法：**

1. **检查 xterm 是否已安装：**
   ```bash
   which xterm
   /usr/bin/xterm
   ```

2. **检查 PATH 环境变量：**
   
   在 VNC 会话中，PATH 可能没有正确设置。更新 `~/.vnc/xstartup` 文件：
   ```bash
   nano ~/.vnc/xstartup
   ```
   
   在文件开头添加 PATH 设置：
   ```bash
   #!/bin/sh
   unset SESSION_MANAGER
   unset DBUS_SESSION_BUS_ADDRESS
   export PATH=/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin
   xrdb $HOME/.Xresources
   xsetroot -solid grey
   exec fvwm
   ```

3. **或者使用完整路径：**
   
   如果 PATH 设置不起作用，可以创建自定义 fvwm 配置文件 `~/.fvwm/config`，在菜单中使用完整路径：
   ```
   AddToMenu "Terminals"
   + "XTerm" Exec exec /usr/bin/xterm
   ```

4. **重启 VNC server：**
   ```bash
   vncserver -kill :1
   vncserver :1
   ```

5. **测试 xterm：**
   
   在 VNC 会话中，打开终端（如果已配置自动启动），运行：
   ```bash
   which xterm
   xterm &
   ```
   
   如果命令行可以启动 xterm，但菜单不行，说明是 fvwm 配置问题。

### 如果 fvwm 没有启动
1. 检查 fvwm 是否已安装：`which fvwm`
2. 检查 xstartup 文件权限：`ls -l ~/.vnc/xstartup`
3. 查看日志：`cat ~/.vnc/*:1.log`

### 如果连接后看到灰色屏幕
- 检查 xstartup 文件是否正确配置
- 确保 fvwm 已安装
- 查看 VNC 日志文件
- 尝试使用更简洁的 xstartup 配置（去掉 `exec /etc/vnc/xstartup` 这行）

### 如果无法连接
- 检查防火墙设置
- 确认 VNC server 正在运行：`ps aux | grep vnc`
- 检查端口是否监听：`netstat -tlnp | grep 5901` 或 `ss -tlnp | grep 5901`

