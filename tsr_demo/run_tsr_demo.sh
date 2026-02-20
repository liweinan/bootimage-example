#!/bin/bash
# ============================================================================
# TSR Demo - 一键启动脚本
# 自动安装依赖、编译 TSR 程序、启动 DOSBox
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================"
echo "  TSR (Terminate and Stay Resident) Demo"
echo "============================================"
echo

# 检测系统
if [[ "$(uname)" != "Darwin" ]]; then
    echo "Warning: This script is designed for macOS."
    echo "On Linux, you may need to adjust package manager commands."
fi

# 检查并安装 Homebrew (如果需要)
check_brew() {
    if ! command -v brew &> /dev/null; then
        echo "Homebrew not found. Installing..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    fi
}

# 检查并安装 DOSBox
check_dosbox() {
    # 检查多种可能的安装位置
    if command -v dosbox &> /dev/null; then
        echo "DOSBox found: $(which dosbox)"
    elif [[ -d "/Applications/DOSBox.app" ]]; then
        echo "DOSBox found: /Applications/DOSBox.app"
    elif [[ -d "/opt/homebrew/Caskroom/dosbox" ]]; then
        echo "DOSBox found: /opt/homebrew/Caskroom/dosbox (Homebrew cask)"
    else
        echo "DOSBox not found. Installing via Homebrew..."
        
        # DOSBox 是 Intel 程序，需要 Rosetta 2 (Apple Silicon)
        if [[ "$(uname -m)" == "arm64" ]]; then
            echo "Checking for Rosetta 2 (required for DOSBox on Apple Silicon)..."
            if ! /usr/bin/pgrep -q oahd 2>/dev/null; then
                echo "Installing Rosetta 2..."
                softwareupdate --install-rosetta --agree-to-license
            fi
        fi
        
        brew install --cask dosbox
        echo "DOSBox installed successfully!"
    fi
}

# 检查并安装 NASM
check_nasm() {
    if ! command -v nasm &> /dev/null; then
        echo "NASM not found. Installing via Homebrew..."
        brew install nasm
        echo "NASM installed successfully!"
    else
        echo "NASM found: $(which nasm)"
    fi
}

# 编译 TSR 程序
compile_tsr() {
    echo
    echo "Compiling TSR programs..."
    
    # 编译时钟 TSR
    if [[ -f "clock_tsr.asm" ]]; then
        echo "  Compiling clock_tsr.asm -> CLOCK.COM"
        nasm -f bin -o CLOCK.COM clock_tsr.asm
    fi
    
    # 编译热键 TSR
    if [[ -f "hotkey_tsr.asm" ]]; then
        echo "  Compiling hotkey_tsr.asm -> HOTKEY.COM"
        nasm -f bin -o HOTKEY.COM hotkey_tsr.asm
    fi
    
    echo "Compilation complete!"
}

# 启动 DOSBox
run_dosbox() {
    echo
    echo "Starting DOSBox..."
    echo "============================================"
    echo
    echo "In DOSBox, type:"
    echo "  CLOCK   - to load the clock TSR"
    echo "  HOTKEY  - to load the hotkey TSR (press F12)"
    echo "  DIR     - to see available files"
    echo "  EXIT    - to quit DOSBox"
    echo
    echo "============================================"
    echo
    
    # 检查 DOSBox 的安装方式并启动
    if command -v dosbox &> /dev/null; then
        # 命令行版本（Linux 或手动安装）
        dosbox -conf dosbox.conf "$SCRIPT_DIR" -c "mount c $SCRIPT_DIR" -c "c:"
    elif [[ -d "/Applications/dosbox.app" ]]; then
        # macOS 应用程序版本（Homebrew cask 安装，小写）
        open /Applications/dosbox.app --args -c "mount c $SCRIPT_DIR" -c "c:"
    elif [[ -d "/Applications/DOSBox.app" ]]; then
        # macOS 应用程序版本（手动安装，大写）
        open /Applications/DOSBox.app --args -c "mount c $SCRIPT_DIR" -c "c:"
    else
        echo "Error: DOSBox not found. Please install it:"
        echo "  brew install --cask dosbox"
        exit 1
    fi
}

# 主流程
main() {
    echo "Step 1: Checking dependencies..."
    check_brew
    check_dosbox
    check_nasm
    
    echo
    echo "Step 2: Compiling TSR programs..."
    compile_tsr
    
    echo
    echo "Step 3: Launching DOSBox..."
    run_dosbox
}

# 运行
main
