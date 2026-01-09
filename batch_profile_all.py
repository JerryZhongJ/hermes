#!/usr/bin/env python3
"""
批量运行所有性能测试的行级性能分析

对项目中所有可运行的性能测试进行 profile，并生成汇总报告
"""

import os
import sys
import subprocess
import json
import re
from pathlib import Path
from typing import List, Dict, Tuple
from datetime import datetime
from collections import defaultdict


class Colors:
    """终端颜色"""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


def log(message: str, level: str = "INFO"):
    """打印日志"""
    color = {
        "INFO": Colors.CYAN,
        "SUCCESS": Colors.GREEN,
        "WARNING": Colors.YELLOW,
        "ERROR": Colors.RED,
    }.get(level, "")

    print(f"{color}[{level}]{Colors.ENDC} {message}")


# 测试文件列表（只包含可以独立运行的测试）
TEST_FILES = [
    # JIT benchmarks - 简单的独立测试
    "benchmarks/jit-benches/idisp.js",
    "benchmarks/jit-benches/idispn.js",

    # nbody - 物理模拟测试（无类型标注版本）
    "benchmarks/nbody/original/nbody.js",

    # raytracer - 光线追踪测试
    "benchmarks/raytracer/original/raytracer.js",

    # Map benchmarks - Map 数据结构性能测试
    "benchmarks/map-strings/map-strings-untyped.js",
    "benchmarks/map-objects/map-objects-untyped.js",

    # String switch - 字符串 switch 性能测试
    "benchmarks/string-switch/plain/bench.js",

    # Many subclasses - 多子类继承测试
    "benchmarks/many-subclasses/many.js",

    # Widgets - UI 组件测试
    "benchmarks/widgets/original/es5/widgets.js",

    # Octane benchmarks - 标准性能测试套件
    "benchmarks/octane/box2d.js",
    "benchmarks/octane/crypto.js",
    "benchmarks/octane/deltablue.js",
    "benchmarks/octane/earley-boyer.js",
    "benchmarks/octane/gbemu.js",
    "benchmarks/octane/navier-stokes.js",
    "benchmarks/octane/pdfjs.js",
    "benchmarks/octane/raytrace.js",
    "benchmarks/octane/regexp.js",
    "benchmarks/octane/richards.js",
    "benchmarks/octane/splay.js",
    "benchmarks/octane/typescript.js",
    "benchmarks/octane/zlib.js",
]


class TestResult:
    """单个测试的结果"""
    def __init__(self, test_file: str):
        self.test_file = test_file
        self.test_name = Path(test_file).stem
        self.success = False
        self.hotspots = []  # [(location, percentage, c_code), ...] - C 代码热点
        self.vm_hotspots = []  # [(function_name, percentage), ...] - VM 运行时热点
        self.total_percentage = 0.0
        self.total_vm_percentage = 0.0
        self.error_message = ""


def run_profile(test_file: str, top_n: int = 5) -> TestResult:
    """对单个测试文件运行 profile"""
    result = TestResult(test_file)

    log(f"分析: {test_file}")

    try:
        # 运行 sh_line_profile.py
        proc = subprocess.run(
            ["./sh_line_profile.py", test_file, "--top", str(top_n)],
            capture_output=True,
            text=True,
            timeout=300  # 5分钟超时
        )

        if proc.returncode != 0:
            result.error_message = f"运行失败: {proc.stderr[:200]}"
            log(f"  ✗ {test_file} 失败", "ERROR")
            return result

        # 解析输出，提取热点信息
        output = proc.stdout

        # 移除 ANSI 颜色码
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        clean_output = ansi_escape.sub('', output)

        # 标记当前解析的部分（C 代码热点 vs VM 运行时热点）
        current_section = None

        # 查找热点行
        # C 代码热点格式: "1     67.32    % idispn_profiled.c:164  np10 = ..."
        c_hotspot_pattern = r'^\s*(\d+)\s+([\d.]+)\s*%\s+(\S+?):(\d+)(.*)$'

        # VM 运行时热点格式: "1     11.69    % hermes::vm::JSObject::getNamedDescriptorUnsafe"
        vm_hotspot_pattern = r'^\s*(\d+)\s+([\d.]+)\s*%\s+([a-zA-Z0-9_:~<>]+.*)$'

        for line in clean_output.split('\n'):
            # 检测区块标题
            if '## 生成代码热点' in line:
                current_section = 'c_code'
                continue
            elif '## VM 运行时热点' in line:
                current_section = 'vm_runtime'
                continue

            # 跳过表头行
            if '热度' in line or '代码' in line or '排名' in line or '函数名' in line:
                continue

            # 尝试匹配 C 代码热点
            if current_section == 'c_code':
                match = re.match(c_hotspot_pattern, line)
                if match:
                    rank = int(match.group(1))
                    percentage = float(match.group(2))
                    c_file = match.group(3)
                    line_num = int(match.group(4))
                    c_code = match.group(5).strip()

                    result.hotspots.append((f"{c_file}:{line_num}", percentage, c_code))
                    result.total_percentage += percentage

            # 尝试匹配 VM 运行时热点
            elif current_section == 'vm_runtime':
                match = re.match(vm_hotspot_pattern, line)
                if match:
                    rank = int(match.group(1))
                    percentage = float(match.group(2))
                    function_name = match.group(3).strip()

                    result.vm_hotspots.append((function_name, percentage))
                    result.total_vm_percentage += percentage

        if result.hotspots or result.vm_hotspots:
            result.success = True
            c_info = f"C热点{len(result.hotspots)}项={result.total_percentage:.2f}%" if result.hotspots else ""
            vm_info = f"VM热点{len(result.vm_hotspots)}项={result.total_vm_percentage:.2f}%" if result.vm_hotspots else ""
            info_parts = [p for p in [c_info, vm_info] if p]
            log(f"  ✓ {test_file} 成功 ({', '.join(info_parts)})", "SUCCESS")
        else:
            result.error_message = "未找到热点数据"
            log(f"  ✗ {test_file} 未找到热点", "WARNING")

    except subprocess.TimeoutExpired:
        result.error_message = "超时"
        log(f"  ✗ {test_file} 超时", "ERROR")
    except Exception as e:
        result.error_message = str(e)
        log(f"  ✗ {test_file} 异常: {e}", "ERROR")

    return result


def generate_summary_report(results: List[TestResult], output_file: str):
    """生成汇总报告"""

    # 统计
    total_tests = len(results)
    successful_tests = sum(1 for r in results if r.success)
    failed_tests = total_tests - successful_tests

    # 生成报告
    report_lines = []
    report_lines.append("=" * 120)
    report_lines.append("SH 后端性能测试批量分析汇总报告")
    report_lines.append("=" * 120)
    report_lines.append("")
    report_lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append(f"总测试数: {total_tests}")
    report_lines.append(f"成功: {successful_tests}, 失败: {failed_tests}")
    report_lines.append("")
    report_lines.append("=" * 120)
    report_lines.append("")

    # 成功的测试
    if successful_tests > 0:
        report_lines.append("## 成功的测试 - Top 热点汇总")
        report_lines.append("")
        report_lines.append(f"{'测试名称':<25} {'热点类型':<15} {'Top 1 热点':<30} {'热度':<10} {'详情'}")
        report_lines.append("-" * 120)

        for result in results:
            if result.success:
                # 优先显示 C 代码热点，如果没有则显示 VM 热点
                if result.hotspots:
                    top1_location, top1_percentage, top1_code = result.hotspots[0]
                    code_snippet = top1_code[:45] if len(top1_code) > 45 else top1_code
                    report_lines.append(
                        f"{result.test_name:<25} {'C代码':<15} {top1_location:<30} {top1_percentage:>7.2f}%  {code_snippet}"
                    )
                elif result.vm_hotspots:
                    top1_func, top1_percentage = result.vm_hotspots[0]
                    func_snippet = top1_func[:45] if len(top1_func) > 45 else top1_func
                    report_lines.append(
                        f"{result.test_name:<25} {'VM运行时':<15} {func_snippet:<30} {top1_percentage:>7.2f}%  (VM热点)"
                    )

        report_lines.append("")
        report_lines.append("-" * 120)
        report_lines.append("")

        # 详细热点列表
        report_lines.append("## 详细热点分析")
        report_lines.append("")

        for result in results:
            if result.success:
                report_lines.append(f"### {result.test_name} ({result.test_file})")
                report_lines.append("")

                # C 代码热点
                if result.hotspots:
                    report_lines.append("#### 生成代码热点")
                    report_lines.append("")
                    report_lines.append(f"{'排名':<6} {'热度':<10} {'位置':<25} {'C 代码'}")
                    report_lines.append("-" * 120)

                    for idx, (location, percentage, c_code) in enumerate(result.hotspots, 1):
                        code_snippet = c_code[:60] if len(c_code) > 60 else c_code
                        report_lines.append(
                            f"{idx:<6} {percentage:>7.2f}%  {location:<25} {code_snippet}"
                        )

                    report_lines.append(f"\nTop {len(result.hotspots)} 总热度: {result.total_percentage:.2f}%")
                    report_lines.append("")

                # VM 运行时热点
                if result.vm_hotspots:
                    report_lines.append("#### VM 运行时热点")
                    report_lines.append("")
                    report_lines.append(f"{'排名':<6} {'热度':<10} {'函数名'}")
                    report_lines.append("-" * 120)

                    for idx, (func_name, percentage) in enumerate(result.vm_hotspots, 1):
                        report_lines.append(f"{idx:<6} {percentage:>7.2f}%  {func_name}")

                    report_lines.append(f"\nTop {len(result.vm_hotspots)} 总热度: {result.total_vm_percentage:.2f}%")
                    report_lines.append("")

                report_lines.append("-" * 120)
                report_lines.append("")

    # 失败的测试
    if failed_tests > 0:
        report_lines.append("## 失败的测试")
        report_lines.append("")
        report_lines.append(f"{'测试名称':<30} {'错误信息'}")
        report_lines.append("-" * 120)

        for result in results:
            if not result.success:
                error_msg = result.error_message[:80] if len(result.error_message) > 80 else result.error_message
                report_lines.append(f"{result.test_name:<30} {error_msg}")

        report_lines.append("")
        report_lines.append("-" * 120)
        report_lines.append("")

    # 热点模式统计
    report_lines.append("## 热点模式统计")
    report_lines.append("")

    # 统计最常见的热点操作类型
    operation_counts = defaultdict(int)

    for result in results:
        if result.success:
            for location, percentage, c_code in result.hotspots:
                # 简单分类
                if '- _sh_ljs_get_double' in c_code:
                    operation_counts['浮点减法'] += 1
                elif '* _sh_ljs_get_double' in c_code:
                    operation_counts['浮点乘法'] += 1
                elif '+ _sh_ljs_get_double' in c_code:
                    operation_counts['浮点加法'] += 1
                elif '_sh_ljs_call' in c_code:
                    operation_counts['函数调用'] += 1
                elif '_sh_ljs_get_by_id' in c_code or '_sh_ljs_put_by_id' in c_code:
                    operation_counts['属性访问'] += 1
                else:
                    operation_counts['其他'] += 1

    report_lines.append(f"{'操作类型':<20} {'出现次数'}")
    report_lines.append("-" * 50)

    for op_type, count in sorted(operation_counts.items(), key=lambda x: x[1], reverse=True):
        report_lines.append(f"{op_type:<20} {count}")

    report_lines.append("")
    report_lines.append("=" * 120)

    # 写入文件
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report_lines))

    # 同时打印到控制台
    print()
    print('\n'.join(report_lines))

    log(f"汇总报告已保存到: {output_file}", "SUCCESS")


def main():
    """主函数"""
    print()
    print("=" * 120)
    print(f"{Colors.BOLD}{Colors.HEADER}SH 后端性能测试批量分析{Colors.ENDC}")
    print("=" * 120)
    print()

    # 检查 sh_line_profile.py 是否存在
    if not os.path.exists("./sh_line_profile.py"):
        log("找不到 sh_line_profile.py", "ERROR")
        return 1

    log(f"将分析 {len(TEST_FILES)} 个测试文件")
    print()

    # 运行所有测试
    results = []

    for idx, test_file in enumerate(TEST_FILES, 1):
        log(f"[{idx}/{len(TEST_FILES)}] 开始分析: {test_file}", "INFO")

        if not os.path.exists(test_file):
            log(f"  文件不存在: {test_file}", "WARNING")
            result = TestResult(test_file)
            result.error_message = "文件不存在"
            results.append(result)
            continue

        result = run_profile(test_file, top_n=5)
        results.append(result)
        print()

    # 生成汇总报告
    output_file = f"profile_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    generate_summary_report(results, output_file)

    # 统计摘要
    successful = sum(1 for r in results if r.success)
    failed = len(results) - successful

    print()
    log(f"批量分析完成！成功: {successful}, 失败: {failed}", "SUCCESS")
    log(f"详细报告: {output_file}", "INFO")

    return 0


if __name__ == "__main__":
    sys.exit(main())
