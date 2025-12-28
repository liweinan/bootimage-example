# Makefile for boot sector project

ASM = nasm
ASMFLAGS = -f bin
QEMU = qemu-system-x86_64
QEMUFLAGS = -drive format=raw,file=boot.bin

BOOT_BIN = boot.bin
BOOT_ASM = boot.asm

.PHONY: all build run clean help

all: build

build: $(BOOT_BIN)

$(BOOT_BIN): $(BOOT_ASM)
	$(ASM) $(ASMFLAGS) $(BOOT_ASM) -o $(BOOT_BIN)
	@echo "编译完成: $(BOOT_BIN)"
	@ls -lh $(BOOT_BIN)

run: $(BOOT_BIN)
	@echo "在 QEMU 中启动引导扇区..."
	$(QEMU) $(QEMUFLAGS)

clean:
	rm -f $(BOOT_BIN)
	@echo "已清理生成的文件"

help:
	@echo "可用目标:"
	@echo "  make build  - 编译 boot.asm 生成 boot.bin"
	@echo "  make run    - 在 QEMU 中运行引导扇区"
	@echo "  make clean  - 删除生成的文件"
	@echo "  make help   - 显示此帮助信息"

