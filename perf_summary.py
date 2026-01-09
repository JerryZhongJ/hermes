#!/usr/bin/env python3
"""
生成简洁的性能对比总表
"""

import json
from pathlib import Path

def load_json_results(result_dir):
    """加载标准基准测试的 JSON 结果"""
    results = {}
    result_path = Path(result_dir)

    for json_file in result_path.glob("*.json"):
        with open(json_file, 'r') as f:
            data = json.load(f)
            runtime = data['runtime']
            results[runtime] = data['results']

    return results

def generate_summary_table():
    """生成汇总表"""

    print("=" * 150)
    print("Static Hermes 性能测试汇总表")
    print("=" * 150)
    print()

    # 第一部分：标准基准测试
    print("## 标准基准测试（V8 + Octane）")
    print()

    standard_result_dir = "/home/zjc/js_engines/static_hermes/results_20260107_231114"
    results = load_json_results(standard_result_dir)

    # 提取所有测试名称
    test_names = set()
    for runtime_results in results.values():
        test_names.update(runtime_results.keys())
    test_names = sorted(test_names)

    # 表头
    print(f"{'测试名称':<20} {'V8 (ms)':>10} {'Hermes':>10} {'SH-HBC':>10} {'SH-Native':>10} {'vs V8':>12} {'最快':>12}")
    print("-" * 150)

    total_v8 = 0
    total_hermes = 0
    total_sh_hbc = 0
    total_sh_native = 0

    v8_wins = 0
    sh_native_wins = 0

    for test_name in test_names:
        v8_time = results.get('v8 (v8)', {}).get(test_name, {}).get('totalTime', {}).get('mean', 0)
        hermes_time = results.get('hermes (hermes-hbc)', {}).get(test_name, {}).get('totalTime', {}).get('mean', 0)
        sh_hbc_time = results.get('hermes (sh-hbc)', {}).get(test_name, {}).get('totalTime', {}).get('mean', 0)
        sh_native_time = results.get('sh (sh-native)', {}).get(test_name, {}).get('totalTime', {}).get('mean', 0)

        total_v8 += v8_time
        total_hermes += hermes_time
        total_sh_hbc += sh_hbc_time
        total_sh_native += sh_native_time

        # 计算 vs V8 的比例
        if v8_time > 0:
            vs_v8 = sh_native_time / v8_time
            vs_v8_str = f"{vs_v8:.2f}x"
        else:
            vs_v8_str = "N/A"

        # 找最快的
        min_time = min(v8_time, hermes_time, sh_hbc_time, sh_native_time)
        if min_time == v8_time:
            fastest = "V8"
            v8_wins += 1
        elif min_time == sh_native_time:
            fastest = "SH-Native"
            sh_native_wins += 1
        elif min_time == sh_hbc_time:
            fastest = "SH-HBC"
        else:
            fastest = "Hermes"

        print(f"{test_name:<20} {v8_time:>10.1f} {hermes_time:>10.1f} {sh_hbc_time:>10.1f} {sh_native_time:>10.1f} {vs_v8_str:>12} {fastest:>12}")

    print("-" * 150)
    print(f"{'总计':<20} {total_v8:>10.1f} {total_hermes:>10.1f} {total_sh_hbc:>10.1f} {total_sh_native:>10.1f} {total_sh_native/total_v8:>11.2f}x")
    print()
    print(f"获胜统计: V8 {v8_wins}/{len(test_names)}, SH-Native {sh_native_wins}/{len(test_names)}")
    print()
    print()

    # 第二部分：独立基准测试
    print("## 独立基准测试")
    print()

    # 手动定义测试结果
    standalone_results = [
        {"name": "nbody", "v8": 115.0, "hermes": 1994.2, "sh_hbc": 744.2, "sh_native": 588.6},
        {"name": "raytracer", "v8": None, "hermes": None, "sh_hbc": None, "sh_native": None},
        {"name": "map-strings-untyped", "v8": 777.4, "hermes": 3076.2, "sh_hbc": 1304.8, "sh_native": 1301.8},
        {"name": "map-objects-untyped", "v8": 580.0, "hermes": 2157.6, "sh_hbc": 1030.4, "sh_native": 961.4},
        {"name": "idisp", "v8": 482.2, "hermes": 3080.6, "sh_hbc": 2508.6, "sh_native": 2212.6},
        {"name": "idispn", "v8": 477.2, "hermes": 3122.8, "sh_hbc": 2798.8, "sh_native": 432.2},
        {"name": "string-switch", "v8": 523.2, "hermes": 10105.2, "sh_hbc": 1581.8, "sh_native": 6328.0},
        {"name": "many-subclasses", "v8": 5935.6, "hermes": None, "sh_hbc": 22585.4, "sh_native": 19830.0},
        {"name": "widgets", "v8": 648.2, "hermes": 5194.8, "sh_hbc": 2481.8, "sh_native": 2236.4},
    ]

    print(f"{'测试名称':<25} {'V8 (ms)':>10} {'Hermes':>10} {'SH-HBC':>10} {'SH-Native':>10} {'vs V8':>12} {'最快':>12}")
    print("-" * 150)

    total_v8 = 0
    total_hermes = 0
    total_sh_hbc = 0
    total_sh_native = 0

    v8_wins = 0
    sh_native_wins = 0
    valid_tests = 0

    for result in standalone_results:
        name = result['name']
        v8 = result['v8']
        hermes = result['hermes']
        sh_hbc = result['sh_hbc']
        sh_native = result['sh_native']

        # 跳过全部失败的测试
        if all(x is None for x in [v8, hermes, sh_hbc, sh_native]):
            print(f"{name:<25} {'FAILED':>10} {'FAILED':>10} {'FAILED':>10} {'FAILED':>10} {'-':>12} {'-':>12}")
            continue

        valid_tests += 1

        if v8: total_v8 += v8
        if hermes: total_hermes += hermes
        if sh_hbc: total_sh_hbc += sh_hbc
        if sh_native: total_sh_native += sh_native

        # 计算 vs V8
        if v8 and sh_native:
            vs_v8 = sh_native / v8
            vs_v8_str = f"{vs_v8:.2f}x"
        else:
            vs_v8_str = "N/A"

        # 找最快的
        times = []
        if v8: times.append(('V8', v8))
        if hermes: times.append(('Hermes', hermes))
        if sh_hbc: times.append(('SH-HBC', sh_hbc))
        if sh_native: times.append(('SH-Native', sh_native))

        if times:
            fastest_name, _ = min(times, key=lambda x: x[1])
            if fastest_name == 'V8':
                v8_wins += 1
            elif fastest_name == 'SH-Native':
                sh_native_wins += 1
        else:
            fastest_name = "N/A"

        v8_str = f"{v8:.1f}" if v8 else "FAILED"
        hermes_str = f"{hermes:.1f}" if hermes else "FAILED"
        sh_hbc_str = f"{sh_hbc:.1f}" if sh_hbc else "FAILED"
        sh_native_str = f"{sh_native:.1f}" if sh_native else "FAILED"

        print(f"{name:<25} {v8_str:>10} {hermes_str:>10} {sh_hbc_str:>10} {sh_native_str:>10} {vs_v8_str:>12} {fastest_name:>12}")

    print("-" * 150)
    print(f"{'总计':<25} {total_v8:>10.1f} {total_hermes:>10.1f} {total_sh_hbc:>10.1f} {total_sh_native:>10.1f} {total_sh_native/total_v8:>11.2f}x")
    print()
    print(f"获胜统计: V8 {v8_wins}/{valid_tests}, SH-Native {sh_native_wins}/{valid_tests}")
    print()
    print()

    # 汇总
    print("=" * 150)
    print("总体汇总")
    print("=" * 150)
    print()
    print("标准基准测试: SH-Native vs V8 = {:.2f}x (慢 {:.1f} 倍)".format(22074.8/3910.8, 3910.8/22074.8))
    print("独立基准测试: SH-Native vs V8 = {:.2f}x (慢 {:.1f} 倍)".format(total_sh_native/total_v8, total_v8/total_sh_native))
    print()
    print("🏆 SH-Native 获胜的测试: idispn (432.2ms vs 477.2ms, 快 1.10x)")
    print("⚠️  SH-Native 最慢的测试: string-switch (6328.0ms vs 523.2ms, 慢 12.1x)")
    print()

if __name__ == "__main__":
    generate_summary_table()
