#!/bin/bash
# 独立纯 JS 测试性能对比脚本
# 对比 V8、Hermes HBC、Static Hermes HBC、Static Hermes SH 四个配置的性能

set -e

# 配置路径
V8_BIN="/home/zjc/js_engines/v8/out/x64.release/d8"
HERMES_BIN="/home/zjc/js_engines/build-release/bin/hermes"
SH_HBC_BIN="/home/zjc/js_engines/static-build-release/bin/hermes"
SHERMES_BIN="/home/zjc/js_engines/static-build-release/bin/shermes"

# 使用 clang 作为 C 编译器（shermes 会使用此环境变量）
export CC=clang

# 测试配置
COUNT=5                  # 每个测试运行5次
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"  # 脚本所在的绝对路径
BENCHMARKS_DIR="$SCRIPT_DIR"                  # benchmarks 目录
OUTPUT_DIR="$SCRIPT_DIR/standalone_results_$(date +%Y%m%d_%H%M%S)"
SH_CACHE_DIR="$OUTPUT_DIR/sh_binaries"

# 创建输出目录
mkdir -p "$OUTPUT_DIR"
mkdir -p "$SH_CACHE_DIR"

# 测试列表（路径相对于 benchmarks/ 目录）
declare -a TESTS=(
    "nbody/original/nbody.js"
    "raytracer/original/raytracer.js"
    "map-strings/map-strings-untyped.js"
    "map-objects/map-objects-untyped.js"
    "jit-benches/idisp.js"
    "jit-benches/idispn.js"
    "string-switch/plain/bench.js"
    "many-subclasses/many.js"
    "widgets/original/es5/widgets.js"
)

echo "========================================"
echo "独立纯 JS 测试性能对比"
echo "========================================"
echo "测试数量: ${#TESTS[@]}"
echo "每个测试运行: $COUNT 次"
echo "结果目录: $OUTPUT_DIR"
echo "SH 缓存目录: $SH_CACHE_DIR"
echo "========================================"
echo ""

# 函数：运行单个测试（V8/Hermes/SH-HBC）
run_test_js() {
    local engine_name=$1
    local engine_bin=$2
    local test_file=$3
    local test_dir=$(dirname "$test_file")
    local test_basename=$(basename "$test_file")

    local total_time=0
    local success_count=0

    for i in $(seq 1 $COUNT); do
        cd "$BENCHMARKS_DIR/$test_dir"

        # 运行测试并提取时间
        local start_time=$(date +%s%3N)  # 毫秒级时间戳
        local output
        if output=$($engine_bin "$test_basename" 2>&1); then
            local end_time=$(date +%s%3N)

            # 尝试多种时间格式：
            # 1. "Time: XXX" 格式
            local time=$(echo "$output" | grep -oP 'Time:\s*\K[0-9.]+' | head -1)

            # 2. "XXX ms" 格式（不含 Time:）
            if [ -z "$time" ]; then
                time=$(echo "$output" | grep -oP '^[0-9.]+(?=\s+ms)' | head -1)
            fi

            # 3. 如果都没有，使用外部计时（end - start）
            if [ -z "$time" ]; then
                time=$((end_time - start_time))
            fi

            if [ -n "$time" ]; then
                total_time=$(echo "$total_time + $time" | bc)
                success_count=$((success_count + 1))
                echo -n "."
            else
                echo -n "!"
            fi
        else
            echo -n "X"
        fi
    done

    # 计算平均值
    if [ $success_count -gt 0 ]; then
        local avg_time=$(echo "scale=2; $total_time / $success_count" | bc)
        echo " ${avg_time}ms (${success_count}/${COUNT})"
        echo "$avg_time"
    else
        echo " FAILED"
        echo "N/A"
    fi
}

# 函数：运行 SH 静态编译测试
run_test_sh() {
    local test_file=$1
    local test_name=$(basename "$test_file" .js)
    local test_dir=$(dirname "$test_file")
    local binary_file="$SH_CACHE_DIR/${test_name}.bin"

    # 编译（如果还未编译）
    if [ ! -f "$binary_file" ]; then
        echo -n "  [编译] "
        cd "$BENCHMARKS_DIR/$test_dir"
        if $SHERMES_BIN -O -o "$binary_file" "$(basename "$test_file")" 2>&1 > /dev/null; then
            echo "成功 ($(du -h "$binary_file" | cut -f1))"
        else
            echo "失败"
            echo "COMPILE_FAILED"
            return
        fi
    else
        echo "  [使用缓存的二进制]"
    fi

    # 运行测试
    local total_time=0
    local success_count=0

    echo -n "  [运行] "
    for i in $(seq 1 $COUNT); do
        local start_time=$(date +%s%3N)
        local output
        if output=$($binary_file 2>&1); then
            local end_time=$(date +%s%3N)

            # 尝试多种时间格式：
            # 1. "Time: XXX" 格式
            local time=$(echo "$output" | grep -oP 'Time:\s*\K[0-9.]+' | head -1)

            # 2. "XXX ms" 格式（不含 Time:）
            if [ -z "$time" ]; then
                time=$(echo "$output" | grep -oP '^[0-9.]+(?=\s+ms)' | head -1)
            fi

            # 3. 如果都没有，使用外部计时（end - start）
            if [ -z "$time" ]; then
                time=$((end_time - start_time))
            fi

            if [ -n "$time" ]; then
                total_time=$(echo "$total_time + $time" | bc)
                success_count=$((success_count + 1))
                echo -n "."
            else
                echo -n "!"
            fi
        else
            echo -n "X"
        fi
    done

    # 计算平均值
    if [ $success_count -gt 0 ]; then
        local avg_time=$(echo "scale=2; $total_time / $success_count" | bc)
        echo " ${avg_time}ms (${success_count}/${COUNT})"
        echo "$avg_time"
    else
        echo " FAILED"
        echo "N/A"
    fi
}

# 创建 CSV 结果文件
RESULTS_CSV="$OUTPUT_DIR/results.csv"
echo "测试名称,V8 (ms),Hermes HBC (ms),Static Hermes HBC (ms),Static Hermes SH (ms)" > "$RESULTS_CSV"

# 运行所有测试
test_num=0
for test_file in "${TESTS[@]}"; do
    test_num=$((test_num + 1))
    test_name=$(basename "$test_file" .js)

    echo ""
    echo "[$test_num/${#TESTS[@]}] 测试: $test_name"
    echo "  文件: $test_file"
    echo "----------------------------------------"

    # V8
    echo -n "[1/4] V8: "
    v8_time=$(run_test_js "V8" "$V8_BIN" "$test_file")

    # Hermes HBC
    echo -n "[2/4] Hermes HBC: "
    hermes_time=$(run_test_js "Hermes HBC" "$HERMES_BIN" "$test_file")

    # Static Hermes HBC
    echo -n "[3/4] Static Hermes HBC: "
    sh_hbc_time=$(run_test_js "Static Hermes HBC" "$SH_HBC_BIN" "$test_file")

    # Static Hermes SH (静态编译)
    echo "[4/4] Static Hermes SH:"
    sh_sh_time=$(run_test_sh "$test_file")

    # 写入 CSV
    echo "$test_name,$v8_time,$hermes_time,$sh_hbc_time,$sh_sh_time" >> "$RESULTS_CSV"
done

echo ""
echo "========================================"
echo "所有测试完成！"
echo "========================================"
echo "结果文件: $RESULTS_CSV"
echo "SH 二进制缓存: $SH_CACHE_DIR"
echo ""

# 生成格式化的汇总报告
echo "性能对比汇总"
echo "========================================"
column -t -s, "$RESULTS_CSV"
echo ""

# 使用 Python 生成更详细的分析（如果可用）
if command -v python3 &> /dev/null; then
    python3 - "$RESULTS_CSV" <<'EOF'
import sys
import csv

csv_file = sys.argv[1]

with open(csv_file, 'r') as f:
    reader = csv.DictReader(f)
    rows = list(reader)

print("\n详细性能分析")
print("=" * 100)
print(f"{'测试名称':<25} {'V8':<12} {'Hermes':<12} {'SH-HBC':<12} {'SH-SH':<12} {'最快':<10}")
print("-" * 100)

for row in rows:
    name = row['测试名称']
    times = {}
    for engine in ['V8 (ms)', 'Hermes HBC (ms)', 'Static Hermes HBC (ms)', 'Static Hermes SH (ms)']:
        val = row[engine]
        try:
            times[engine] = float(val) if val != 'N/A' else float('inf')
        except:
            times[engine] = float('inf')

    v8 = row['V8 (ms)']
    hermes = row['Hermes HBC (ms)']
    sh_hbc = row['Static Hermes HBC (ms)']
    sh_sh = row['Static Hermes SH (ms)']

    fastest = min(times.items(), key=lambda x: x[1])
    fastest_name = fastest[0].split()[0]  # 取第一个词

    print(f"{name:<25} {v8:<12} {hermes:<12} {sh_hbc:<12} {sh_sh:<12} {fastest_name:<10}")

print("=" * 100)
EOF
fi

echo ""
echo "提示："
echo "  - 查看原始数据: cat $RESULTS_CSV"
echo "  - 查看格式化表格: column -t -s, $RESULTS_CSV"
echo "  - SH 二进制文件已缓存在 $SH_CACHE_DIR，下次运行会更快"
echo ""
