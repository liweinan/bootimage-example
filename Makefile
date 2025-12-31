# Makefile for boot sector project

ASM = nasm
ASMFLAGS = -f bin
QEMU = qemu-system-x86_64
QEMUFLAGS = -drive format=raw,file=boot.bin

BOOT_BIN = boot.bin
BOOT_ASM = boot.asm
MANUAL_INT_BIN = manual_int_demo.bin
MANUAL_INT_ASM = manual_int_demo.asm

.PHONY: all build run run-gui run-term clean help manual-int manual-int-gui manual-int-term

all: build

build: $(BOOT_BIN)

$(BOOT_BIN): $(BOOT_ASM)
	$(ASM) $(ASMFLAGS) $(BOOT_ASM) -o $(BOOT_BIN)
	@echo "编译完成: $(BOOT_BIN)"
	@ls -lh $(BOOT_BIN)

run: run-gui

run-gui: $(BOOT_BIN)
	@echo "在 QEMU 图形窗口中启动引导扇区（使用 SDL 显示）..."
	@echo "提示: 如果没有看到窗口，请尝试 'make run-term' 在终端中运行"
	$(QEMU) -display sdl $(QEMUFLAGS)

run-term: $(BOOT_BIN)
	@echo "在 QEMU 终端模式中启动引导扇区..."
	@echo "提示: 退出方法 - 按 Ctrl+A，松开后按 X（大写）"
	@echo "      如果不起作用，尝试 Ctrl+A 然后按 C，输入 quit 后回车"
	$(QEMU) -display curses $(QEMUFLAGS)

clean:
	rm -f $(BOOT_BIN) $(MANUAL_INT_BIN)
	@echo "已清理生成的文件"

# 手动实现 INT 指令的示例
manual-int: $(MANUAL_INT_BIN)

$(MANUAL_INT_BIN): $(MANUAL_INT_ASM)
	$(ASM) $(ASMFLAGS) $(MANUAL_INT_ASM) -o $(MANUAL_INT_BIN)
	@echo "编译完成: $(MANUAL_INT_BIN)"
	@ls -lh $(MANUAL_INT_BIN)

manual-int-gui: $(MANUAL_INT_BIN)
	@echo "在 QEMU 图形窗口中运行手动 INT 实现示例..."
	@echo "提示: 如果没有看到窗口，请尝试 'make manual-int-term' 在终端中运行"
	$(QEMU) -display sdl -drive format=raw,file=$(MANUAL_INT_BIN)

manual-int-term: $(MANUAL_INT_BIN)
	@echo "在 QEMU 终端模式中运行手动 INT 实现示例..."
	@echo "提示: 退出方法 - 按 Ctrl+A，松开后按 X（大写）"
	@echo "      如果不起作用，尝试 Ctrl+A 然后按 C，输入 quit 后回车"
	$(QEMU) -display curses -drive format=raw,file=$(MANUAL_INT_BIN)

help:
	@echo "可用目标:"
	@echo "  make build           - 编译 boot.asm 生成 boot.bin"
	@echo "  make run             - 在 QEMU 图形窗口中运行引导扇区（默认）"
	@echo "  make run-gui         - 在 QEMU 图形窗口中运行引导扇区"
	@echo "  make run-term        - 在终端中运行引导扇区（适合 SSH 或无图形界面）"
	@echo ""
	@echo "手动 INT 实现示例:"
	@echo "  make manual-int      - 编译 manual_int_demo.asm"
	@echo "  make manual-int-gui  - 在图形窗口中运行手动 INT 示例"
	@echo "  make manual-int-term - 在终端中运行手动 INT 示例"
	@echo ""
	@echo "  make clean           - 删除生成的文件"
	@echo "  make help            - 显示此帮助信息"

