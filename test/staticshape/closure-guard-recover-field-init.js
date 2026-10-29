/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %shermes -O -dump-ir -verify-ir %s | %FileCheck %s --check-prefix=IR
// RUN: %shermes -O -dump-ir -verify-ir -annotation-file=%S/closure-guard-recover-field-init.json %s | %FileCheck %s --check-prefix=IR
// RUN: %shermes -O -exec -annotation-file=%S/closure-guard-recover-field-init.json %s | %FileCheck %s --check-prefix=EXEC --match-full-lines

// An early guard duplicates the global class initializer closure stores.
// Folding it allows FunctionAnalysis to resolve the hidden field initializer
// before the first inlining round. The existing ObjectMergeNewStores pass
// must merge the exposed field definitions, just as in the unannotated build.
const setup = function () {
  return null;
};

var holder = {__proto__: setup()};

class Point {
  x = 0;
  y = 0;
  z = 0;

  constructor(x, y, z) {
    this.x = x;
    this.y = y;
    this.z = z;
  }
}

var point = new Point(1, 2, 3);
print(point.x, point.y, point.z);

// IR-LABEL: base constructor Point(
// IR: AllocObjectLiteralInst (:object) {{.*}}, "x": string, 0: number, "y": string, 0: number, "z": string, 0: number
// IR-NOT: DefineOwnPropertyInst
// IR: function_end

// EXEC: 1 2 3
