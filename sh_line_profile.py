#!/usr/bin/env python3
"""
SH 后端行级性能分析工具
用法: ./sh_line_profile.py <js_file> [--source {c,js}] [--top N]
"""

import os
import sys
import re
import subprocess
import argparse
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple
from collections import defaultdict

# 设置使用 clang 作为 C 编译器（shermes 会使用此环境变量）
os.environ['CC'] = 'clang'


class HotSpot:
    """热点代码"""
    def __init__(self, file: str, line: int, percentage: float, code: str):
        self.file = file
        self.line = line
        self.percentage = percentage
        self.code = code


def find_shermes() -> Optional[str]:
    """查找 shermes 可执行文件"""
    possible_paths = [
        "../static-build-release/bin/shermes",
        "../static-build-profiling/bin/shermes",
        "./static-build-release/bin/shermes",
        "../static_build/bin/shermes",
    ]

    for path in possible_paths:
        if os.path.exists(path):
            return os.path.abspath(path)
    return None


def get_build_paths(shermes: str) -> Tuple[str, List[str], List[str]]:
    """获取编译所需的路径（从 shermes 的安装位置推断）"""
    shermes_dir = Path(shermes).parent.parent

    include_paths = [
        str(shermes_dir / "lib" / "config"),
        str(shermes_dir.parent / "static_hermes" / "include"),
    ]

    lib_paths = [
        str(shermes_dir / "lib"),
        str(shermes_dir / "jsi"),
        str(shermes_dir / "tools" / "shermes"),
    ]

    return str(shermes_dir), include_paths, lib_paths


def compile_c_mode(shermes: str, js_file: str) -> Optional[Tuple[str, str]]:
    """两步编译：JS → C → binary（用于分析 C 源代码）"""
    basename = Path(js_file).stem

    # 步骤 1: 生成 C 代码到临时文件
    c_file = f"{basename}_profiled.c"
    result = subprocess.run(
        [shermes, "-emit-c", js_file, "-o", c_file],
        capture_output=True,
        text=True,
        timeout=30
    )

    if result.returncode != 0:
        print(f"生成 C 代码失败: {result.stderr}", file=sys.stderr)
        return None

    # 步骤 2: 使用 clang 编译 C 代码
    binary_path = f"{basename}_profiled"
    build_dir, include_paths, lib_paths = get_build_paths(shermes)

    gcc_args = ["clang", "-O2", "-g", "-DNDEBUG",
                "-fno-strict-aliasing", "-fno-strict-overflow"]

    # 添加 include 路径
    for inc in include_paths:
        gcc_args.append(f"-I{inc}")

    # 添加库搜索路径
    for lib in lib_paths:
        gcc_args.append(f"-L{lib}")

    gcc_args.append(c_file)

    # 添加链接库
    gcc_args.extend(["-lshermes_console", "-lhermesvm", "-lm"])

    # 添加 rpath
    for lib in lib_paths:
        gcc_args.append(f"-Wl,-rpath={lib}")

    gcc_args.extend(["-o", binary_path])

    result = subprocess.run(
        gcc_args,
        capture_output=True,
        text=True,
        timeout=180  # 增加到3分钟，应对大型测试文件
    )

    if result.returncode != 0:
        print(f"clang 编译失败: {result.stderr}", file=sys.stderr)
        return None

    # 添加执行权限
    os.chmod(binary_path, 0o755)

    return binary_path, c_file


def compile_js_mode(shermes: str, js_file: str) -> Optional[str]:
    """直接编译：JS → binary（用于分析 JS 源代码）"""
    basename = Path(js_file).stem
    binary_path = f"{basename}_profiled"

    result = subprocess.run(
        [shermes, "-O", "-g", "-Xline-directives", "-o", binary_path, js_file],
        capture_output=True,
        text=True,
        timeout=30
    )

    if result.returncode != 0:
        print(f"编译失败: {result.stderr}", file=sys.stderr)
        return None

    # 添加执行权限
    os.chmod(binary_path, 0o755)

    return binary_path


def profile(binary: str) -> Optional[str]:
    """使用 perf 采集性能数据"""
    perf_data = "perf.data"

    # 确保 binary 路径正确
    if not binary.startswith('./') and not binary.startswith('/'):
        binary = './' + binary

    try:
        result = subprocess.run(
            ["perf", "record", "-g", "--call-graph", "dwarf", "-F", "997", "-o", perf_data, binary],
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode != 0:
            print(f"perf record 失败: {result.stderr}", file=sys.stderr)
            return None

        return perf_data

    except subprocess.TimeoutExpired:
        print("性能采集超时", file=sys.stderr)
        return None
    except Exception as e:
        print(f"性能采集异常: {e}", file=sys.stderr)
        return None


def get_api_entry_points(perf_data: str, top_n: int = 10) -> List[Tuple[str, float]]:
    """
    获取API入口点列表（按VM函数Children时间排序）

    Children时间 = 函数自身执行时间 + 所有子函数调用时间
    这反映了该API函数及其被调用链的总体性能开销

    用于识别哪些VM API函数的累积开销最高，
    从而指导优化方向（是优化该函数本身，还是优化它的子函数）
    """
    try:
        result = subprocess.run(
            ["perf", "report", "-i", perf_data, "--stdio",
             "--sort=overhead_children,overhead,symbol", "-n"],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            return []

        api_entries = []
        # 解析格式：Children% Self% Samples [.] 函数名
        # 注意：使用overhead_children排序时，第一列是Children%，第二列是Self%
        pattern = r'^\s*([\d.]+)%\s+([\d.]+)%\s+\d+\s+\[\.\]\s+(\S+)'

        for line in result.stdout.split('\n'):
            match = re.match(pattern, line)
            if match:
                children_pct = float(match.group(1))  # Children百分比
                # self_pct = float(match.group(2))   # Self百分比（暂不使用）
                function = match.group(3)
                # 只保留 > 1.0% 的API入口点（Children时间通常较高）
                if children_pct > 1.0:
                    api_entries.append((function, children_pct))
                    if len(api_entries) >= top_n:
                        break

        return api_entries

    except Exception as e:
        print(f"获取API入口点异常: {e}", file=sys.stderr)
        return []


def get_hot_functions(perf_data: str, top_n: int = 10) -> List[Tuple[str, float]]:
    """获取热点函数列表（包括 VM 运行时函数）"""
    try:
        result = subprocess.run(
            ["perf", "report", "-i", perf_data, "--stdio", "--sort=overhead,symbol", "-n"],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            return []

        hot_functions = []
        pattern = r'^\s*([\d.]+)%\s+\d+\s+\[\.\]\s+(\S+)'

        for line in result.stdout.split('\n'):
            match = re.match(pattern, line)
            if match:
                percentage = float(match.group(1))
                function = match.group(2)
                if percentage > 0.5:  # 只保留 > 0.5% 的函数
                    hot_functions.append((function, percentage))
                    if len(hot_functions) >= top_n * 2:  # 获取足够多的函数
                        break

        return hot_functions

    except Exception as e:
        print(f"获取热点函数异常: {e}", file=sys.stderr)
        return []


def analyze_hotspots(perf_data: str, binary: str, source_file: str, top_n: int) -> Tuple[List[HotSpot], List[Tuple[str, float]], List[Tuple[str, float]]]:
    """分析热点代码，返回 (C源代码热点, VM运行时热点Self, VM函数Children)"""

    # 1. 获取所有热点函数（按Self时间）
    hot_functions = get_hot_functions(perf_data, top_n)

    # 获取API入口点（按Children时间）
    api_entry_points = get_api_entry_points(perf_data, top_n)

    if not hot_functions:
        print("未找到热点函数", file=sys.stderr)
        return [], [], []

    # 分离 VM 运行时热点
    vm_hotspots = []
    code_functions = []

    for func_name, percentage in hot_functions:
        # VM 运行时函数通常包含这些特征
        if any(prefix in func_name for prefix in ['hermes::', 'llvh::', 'std::', '__', 'malloc', 'free']):
            # 解析函数名，去掉参数和模板
            clean_name = func_name.split('(')[0] if '(' in func_name else func_name
            vm_hotspots.append((clean_name, percentage))
        else:
            code_functions.append(func_name)

    # 2. 分析生成的 C 代码热点（使用第一个非 VM 函数）
    source_hotspots = []

    for hot_function in code_functions[:3]:  # 尝试前3个函数
        try:
            result = subprocess.run(
                ["perf", "annotate", "-i", perf_data, "--stdio", hot_function],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0:
                continue

            # 解析 perf annotate 输出，提取地址和热度
            addr_percentages = {}
            addr_pattern = r'^\s*([\d.]+)\s+:\s+([0-9a-f]+):'

            for line in result.stdout.split('\n'):
                match = re.match(addr_pattern, line)
                if match:
                    percentage = float(match.group(1))
                    addr = match.group(2)
                    if percentage > 0.1:
                        addr_percentages[addr] = percentage

            # 使用 addr2line 映射地址到源代码位置
            hotspots_dict = defaultdict(float)

            for addr, percentage in addr_percentages.items():
                result = subprocess.run(
                    ["addr2line", "-e", binary, f"0x{addr}"],
                    capture_output=True,
                    text=True
                )

                location = result.stdout.strip()
                match = re.match(r'^(.+):(\d+)', location)
                if match:
                    file_path = match.group(1)
                    line_num = int(match.group(2))

                    # 只保留与目标源文件相关的热点
                    if source_file in file_path or Path(file_path).name == Path(source_file).name:
                        hotspots_dict[line_num] += percentage

            if hotspots_dict:
                # 读取源代码内容
                try:
                    with open(source_file, 'r') as f:
                        source_lines = f.readlines()

                    for line_num, percentage in hotspots_dict.items():
                        if 0 < line_num <= len(source_lines):
                            code = source_lines[line_num - 1].strip()
                            source_hotspots.append(HotSpot(source_file, line_num, percentage, code))
                except:
                    pass

        except Exception:
            continue

    # 按热度排序
    source_hotspots.sort(key=lambda x: x.percentage, reverse=True)

    return source_hotspots[:top_n], vm_hotspots[:top_n], api_entry_points


def print_report(source_file: str, source_type: str, hotspots: List[HotSpot], vm_hotspots: List[Tuple[str, float]], api_entries: List[Tuple[str, float]], top_n: int):
    """生成简洁的热度报告"""
    print()
    print("=" * 80)
    print(f"SH 后端行级性能分析报告 - Top {top_n} ({source_type.upper()} 源代码)")
    print("=" * 80)
    print()
    print(f"源文件: {source_file}")
    print()
    print("-" * 80)

    # 显示API入口点（按Children时间排序）
    if api_entries:
        print(f"\n## API入口点分析（VM函数Children时间）\n")
        print(f"{'排名':<6}{'热度':<10}{'函数名'}")
        print("-" * 80)

        total_api_percentage = 0.0
        for rank, (func_name, percentage) in enumerate(api_entries, 1):
            total_api_percentage += percentage

            # 截断过长的函数名
            display_name = func_name
            if len(display_name) > 65:
                display_name = display_name[:62] + "..."

            print(f"{rank:<6}{percentage:<9.2f}% {display_name}")

        print("-" * 80)
        print(f"注：Children时间包含子函数，总和可能>100%（累积）")
    else:
        print(f"\n## API入口点分析（VM函数Children时间）\n")
        print("未找到API入口点数据")

    # 显示源代码热点
    if hotspots:
        print(f"\n## 生成代码热点\n")
        print(f"{'排名':<6}{'热度':<10}{'位置':<20}{'代码'}")
        print("-" * 80)

        total_percentage = 0.0
        for rank, hotspot in enumerate(hotspots, 1):
            total_percentage += hotspot.percentage

            # 截断过长的代码
            code = hotspot.code
            if len(code) > 45:
                code = code[:42] + "..."

            location = f"{Path(hotspot.file).name}:{hotspot.line}"
            print(f"{rank:<6}{hotspot.percentage:<9.2f}% {location:<20}{code}")

        print("-" * 80)
        print(f"Top {len(hotspots)} 总热度: {total_percentage:.2f}%")
    else:
        print("\n## 生成代码热点\n")
        print("未找到热点数据")

    print("=" * 80)
    print()


def main():
    parser = argparse.ArgumentParser(
        description="SH 后端行级性能分析自动化工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    # 分析 C 源代码热度（默认）
    ./sh_line_profile.py benchmarks/jit-benches/idispn.js

    # 分析 JavaScript 源代码热度
    ./sh_line_profile.py benchmarks/jit-benches/idispn.js --source js

    # 显示 Top 20
    ./sh_line_profile.py benchmarks/jit-benches/idispn.js --top 20
        """
    )
    parser.add_argument("js_file", help="要分析的 JavaScript 文件")
    parser.add_argument("--source", choices=['c', 'js'], default='c',
                        help="源代码类型: c=C源代码(默认), js=JavaScript源代码")
    parser.add_argument("--top", type=int, default=10, help="显示热度前 N 行 (默认: 10)")

    args = parser.parse_args()

    if not os.path.exists(args.js_file):
        print(f"文件不存在: {args.js_file}", file=sys.stderr)
        return 1

    # 查找 shermes
    shermes = find_shermes()
    if not shermes:
        print("找不到 shermes 可执行文件", file=sys.stderr)
        print("请确保在 static_hermes 项目目录中运行此脚本", file=sys.stderr)
        return 1

    # 编译（根据模式选择不同的编译方式）
    binary = None
    c_file = None
    source_file = args.js_file

    if args.source == 'c':
        # C 模式：两步编译
        result = compile_c_mode(shermes, args.js_file)
        if not result:
            return 1
        binary, c_file = result
        source_file = c_file
    else:
        # JS 模式：直接编译
        binary = compile_js_mode(shermes, args.js_file)
        if not binary:
            return 1

    # 性能采集
    perf_data = profile(binary)
    if not perf_data:
        return 1

    # 分析热点
    source_hotspots, vm_hotspots, api_entries = analyze_hotspots(perf_data, binary, source_file, args.top)

    # 生成报告
    print_report(source_file, args.source, source_hotspots, vm_hotspots, api_entries, args.top)

    # 清理
    if os.path.exists(binary):
        os.remove(binary)
    if c_file and os.path.exists(c_file):
        os.remove(c_file)
    if os.path.exists(perf_data):
        os.remove(perf_data)

    return 0


if __name__ == "__main__":
    sys.exit(main())
