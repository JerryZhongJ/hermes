/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %shermes -O -Xinline-max-size=0 -dump-ir -verify-ir %s | %FileCheck %s --check-prefix=IR
// RUN: %shermes -O -Xinline-max-size=0 -exec %s | %FileCheck %s --check-prefix=EXEC --match-full-lines

// Only inlining select exposes the constant condition. Before the second
// inlining round, remove the dead branch so step has a single callsite and
// satisfies the size-independent inlining heuristic. No annotations are used.
"use strict";
(function main() {
  var total = 0;

  function select(x) {
    return x + 1;
  }

  function step(dt) {
    for (var i = 0; i < 3; ++i) {
      total += dt;
    }
  }

  if (select(1) === 2) {
    step(1);
  } else {
    print("unreachable");
    step(2);
  }
  print(total);
})();

// IR-LABEL: function global()
// IR-NOT: CallInst {{.*}}%select()
// IR-NOT: CallInst {{.*}}%step()
// IR: function_end
// IR-NOT: function {{[a-zA-Z_]}}

// EXEC: 3
