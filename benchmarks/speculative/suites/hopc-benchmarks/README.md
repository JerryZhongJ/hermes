# Hop compiler benchmarks

The benchmark inputs originate from
[`manuel-serrano/jsbench`](https://github.com/manuel-serrano/jsbench) at commit
`7c8fc4e58d2a5c7980c207d302b1d1cb18308a5c`.
[hopc-manifest.json](../../hopc-manifest.json) records upstream paths, current
default workload counts, and smoke-test counts.

The current files use the old top-level harness:

| Directory | Retained old benchmarks | Additional benchmarks |
| --- | --- | --- |
| `../bglstone/` | 11 from former `bglstone-old/` | None |
| `./` | 13 from former `hopc-npm-old/` | `js-beautify` |

The 24 shared files are copied byte-for-byte from the old directories. This
restores their implementations, fixed `N` expressions, `console` logging,
runtime adaptations, and formatting, as well as their harnesses. The duplicate
`bglstone-old/` and `hopc-npm-old/` source directories have been removed. Matching
historical annotations use the `bglstone/` and `hopc-benchmarks/` subdirectories
under `annotations/jelly-old/` and `annotations/coverage-guided-old/`. The
corresponding annotations for the former imported versions have been removed
from `annotations/jelly/` and `annotations/coverage-guided/`.

The additional `js-beautify` benchmark retains its imported algorithm, input,
checks, and fixed workload count. Only its outer harness has changed. It still
bundles version 1.8.9 and the original `test.js` input string.

`moment.js` is the retained Moment benchmark, retained from the former `hopc-npm-old/` directory.
The redundant `moment-full.js` entry has been removed.

## Harness

The previous imported version wrapped each entire program in an IIFE, started
timing before payload initialization, used `performance.now()` directly, and
used `print()` for workload logging. The old versions have no outer harness
IIFE, start timing immediately before the workload, and include a `Date.now`
fallback. Library-internal IIFEs remain in both versions.

All 25 current files use this timing pattern at top level:

```js
// Static Hermes benchmark runner: fixed N, timed with performance.now
const N = 12;

var __performance = globalThis.performance ?? (globalThis.performance = {});
__performance.now ??= Date.now;
var __start = __performance.now();
// Call main(..., N), or execute the N-iteration workload.
var __end = __performance.now();
print("Time: " + (__end - __start));
```

Each file retains its own fixed `N`, which can be an arithmetic expression.
The timer excludes earlier payload initialization and the final timing print.
Workload output within the measured call or loop remains included. The
additional `js-beautify` entry retains its existing `print()` logging.

## Running

From `benchmarks/speculative/`, run every entry without annotations:

```sh
python3 run_hopc.py --shermes /path/to/shermes
```

Run shorter workloads:

```sh
python3 run_hopc.py --shermes /path/to/shermes --smoke \
  --json /tmp/hopc-smoke.json
```

Use `--only bglstone` or `--only hopc-benchmarks/minimatch` to select entries.
`--build-dir /tmp/hopc-build` retains binaries and compiler inputs for
inspection. The runner uses `-O -fstatic-builtins`, `TZ=UTC`, and `LC_ALL=C`.
`--smoke` replaces `const N` only in temporary compiler inputs using the counts
in the manifest.

Individual entries also compile directly:

```sh
shermes -O -fstatic-builtins suites/hopc-benchmarks/minimatch.js -o /tmp/minimatch
TZ=UTC /tmp/minimatch
```

Each program prints one `Time: <milliseconds>` line, compatible with
`bench.py`'s timing parser. `bench.py` additionally requires corresponding
annotation files for A/B discovery. Annotations must match the restored source
locations before use.

## Historical imports, timings, and licenses

[`hopc-timings.json`](../../hopc-timings.json) records measurements and hashes
from the former imported/formatted sources. Those results do not describe
the current sources: workload counts, scope, and timing boundaries have
changed. No runtime target is claimed for the restored workloads.

`box2d`, `navier-stokes`, and `moment-full` have been removed from this suite
and its manifest.
`import_hopc.py` skips them on future imports. Otherwise it retains the original
import procedure: running it again overwrites these restored files and
reintroduces the outer IIFE and former harness. Likewise, running the formatter
can change the restored files' formatting and source locations; see [FORMATTING.md](../../FORMATTING.md).

Original copyright and license notices are retained inside the payloads.
The inputs come from multiple projects and retain their respective licenses.
In particular, `z80.js` is GPL-3.0-or-later (the GPLv3 text is provided in
`Z80-COPYING.txt`), while the bundled js-beautify library is MIT.
