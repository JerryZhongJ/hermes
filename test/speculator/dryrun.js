/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: echo %S/dryrun.hints.json | %speculator -O --annotate %s 2>/dev/null | %FileCheck %s

// Dry-run a shape hint on parameter o: every property access specializes to
// PrLoad/PrStore. Requires building with -DHERMES_SOURCE_RANGE_IN_IR=ON and
// pointing %speculator at that build's speculator binary.

function f(o) {
  o.x = 1;
  o.y = 2;
  return o.x + o.y;
}

// CHECK: "function":"f"
// CHECK: "loadToPrLoad":2
// CHECK: "storeToPrStore":2
// CHECK: "netInstructions":3
