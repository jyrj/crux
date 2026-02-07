.PHONY: install dev test clean yosys-slang opentitan-setup

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

test:
	pytest tests/ -v

# Build yosys-slang plugin for SystemVerilog support
# Requires: yosys-devel cmake ninja-build gcc-c++ boost-devel
yosys-slang:
	cd extern/yosys-slang && git submodule update --init --recursive
	cd extern/yosys-slang && mkdir -p build && cd build && \
		cmake .. -G Ninja \
			-DCMAKE_BUILD_TYPE=Release && \
		ninja

# Set up OpenTitan sparse checkout for validation
opentitan-setup:
	@if [ ! -d extern/opentitan/.git ]; then \
		mkdir -p extern/opentitan && \
		cd extern/opentitan && \
		git init && \
		git remote add origin https://github.com/lowRISC/opentitan.git && \
		git sparse-checkout init --cone && \
		git sparse-checkout set hw/ip/prim hw/ip/prim_generic hw/ip/aon_timer hw/ip/usbdev hw/ip/tlul hw/top_earlgrey/cdc && \
		git fetch --depth=1 origin master && \
		git checkout master; \
	else \
		echo "OpenTitan already set up"; \
	fi

OT_PRIM = extern/opentitan/hw/ip/prim_generic/rtl
OT_PRIM2 = extern/opentitan/hw/ip/prim/rtl
OT_FLAGS = -I$(OT_PRIM2) -DSYNTHESIS

# Validate against real OpenTitan CDC primitives
validate-opentitan:
	@echo "=== Validating against OpenTitan prim_pulse_sync ==="
	python -m crux --top prim_pulse_sync $(OT_FLAGS) \
		$(OT_PRIM)/prim_flop.sv \
		$(OT_PRIM)/prim_flop_2sync.sv \
		$(OT_PRIM2)/prim_pulse_sync.sv
	@echo ""
	@echo "=== Validating against OpenTitan prim_fifo_async ==="
	python -m crux --top prim_fifo_async $(OT_FLAGS) \
		$(OT_PRIM)/prim_flop.sv \
		$(OT_PRIM)/prim_flop_2sync.sv \
		$(OT_PRIM2)/prim_fifo_async.sv
	@echo ""
	@echo "=== Validating against OpenTitan prim_sync_reqack ==="
	python -m crux --top prim_sync_reqack $(OT_FLAGS) \
		$(OT_PRIM)/prim_flop.sv \
		$(OT_PRIM)/prim_flop_2sync.sv \
		$(OT_PRIM2)/prim_sync_reqack.sv

clean:
	rm -rf build/ dist/ *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -name "*.pyc" -delete
