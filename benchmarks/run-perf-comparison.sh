#!/bin/bash
# 性能对比测试脚本
# 对比 V8、Hermes HBC、Static Hermes HBC、Static Hermes SH 四个配置的性能

set -e

# 配置路径
V8_BIN="/home/zjc/js_engines/v8/out/x64.release/d8"
HERMES_BIN="/home/zjc/js_engines/build-release/bin/hermes"
SH_HBC_BIN="/home/zjc/js_engines/static-build-release/bin/hermes"
SH_SH_BIN="/home/zjc/js_engines/static-build-release/bin/shermes"

# 使用 clang 作为 C 编译器（bench-runner.py 调用 shermes 时会使用此环境变量）
export CC=clang

# 测试配置
CATEGORIES="v8 octane"  # v8有6个测试，octane有7个测试
COUNT=5                  # 每个测试运行5次
OUTPUT_DIR="./results_$(date +%Y%m%d_%H%M%S)"
SH_CACHE_DIR="./sh_cache"

# 创建输出目录并转换为绝对路径
mkdir -p "$OUTPUT_DIR"
mkdir -p "$SH_CACHE_DIR"
OUTPUT_DIR="$(realpath "$OUTPUT_DIR")"
SH_CACHE_DIR="$(realpath "$SH_CACHE_DIR")"

echo "========================================"
echo "性能对比测试"
echo "========================================"
echo "测试类别: $CATEGORIES"
echo "运行次数: $COUNT"
echo "结果目录: $OUTPUT_DIR"
echo "========================================"
echo ""

# 切换到bench-runner目录
cd "$(dirname "$0")/bench-runner"

# 1. V8
echo "[1/4] 运行 V8 测试..."
python3 bench-runner.py \
    --v8 \
    -b "$V8_BIN" \
    -l "v8" \
    -c "$COUNT" \
    --categories $CATEGORIES \
    --output-format json \
    --out "$OUTPUT_DIR/v8.json" \
    2>&1 | tee "$OUTPUT_DIR/v8.log"
echo ""

# 2. Hermes HBC
echo "[2/4] 运行 Hermes HBC 测试..."
python3 bench-runner.py \
    --hermes \
    -b "$HERMES_BIN" \
    -l "hermes-hbc" \
    -c "$COUNT" \
    --categories $CATEGORIES \
    --output-format json \
    --out "$OUTPUT_DIR/hermes-hbc.json" \
    2>&1 | tee "$OUTPUT_DIR/hermes-hbc.log"
echo ""

# 3. Static Hermes HBC
echo "[3/4] 运行 Static Hermes HBC 测试..."
python3 bench-runner.py \
    --hermes \
    -b "$SH_HBC_BIN" \
    -l "sh-hbc" \
    -c "$COUNT" \
    --categories $CATEGORIES \
    --output-format json \
    --out "$OUTPUT_DIR/sh-hbc.json" \
    2>&1 | tee "$OUTPUT_DIR/sh-hbc.log"
echo ""

# 4. Static Hermes SH (原生编译)
echo "[4/4] 运行 Static Hermes SH 测试..."
python3 bench-runner.py \
    --sh \
    -b "$SH_SH_BIN" \
    -l "sh-native" \
    -c "$COUNT" \
    --categories $CATEGORIES \
    --output-format json \
    --sh-cache-dir "$SH_CACHE_DIR" \
    --out "$OUTPUT_DIR/sh-native.json" \
    2>&1 | tee "$OUTPUT_DIR/sh-native.log"
echo ""

echo "========================================"
echo "所有测试完成！"
echo "========================================"
echo "结果文件位于: $OUTPUT_DIR"
echo ""
echo "可以使用以下命令查看对比结果："
echo "  cat $OUTPUT_DIR/*.json"
echo ""
echo "或者使用 bench-merge 工具合并结果（如果可用）："
echo "  bench-merge $OUTPUT_DIR/v8.json $OUTPUT_DIR/hermes-hbc.json $OUTPUT_DIR/sh-hbc.json $OUTPUT_DIR/sh-native.json"
echo ""
