/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %shermes -O -Xinline-max-size=0 -dump-ir -verify-ir %s | %FileCheck %s --check-prefix=IR
// RUN: %shermes -O -Xinline-max-size=0 -dump-ir -verify-ir -annotation-file=%S/closure-guard-recover-inline.json %s | %FileCheck %s --check-prefix=IR
// RUN: %shermes -O -Xinline-max-size=0 -exec -annotation-file=%S/closure-guard-recover-inline.json %s | %FileCheck %s --check-prefix=EXEC --match-full-lines

// All callees are statically known and have one source callsite. Force the
// single-callsite inlining heuristic, rather than the small-function heuristic.
// Guard insertion duplicates the main/run calls and merges step/finish values
// through fallback PHIs. Folding the checks must clean up those paths before
// inlining analyzes the call graph again.
'use strict';
(function main() {
  var total = 0;

  function step(dt) {
    for (var j = 0; j < 3; ++j) {
      total += dt;
    }
  }

  function finish() {
    return total * 2 + 1;
  }

  function run() {
    for (var i = 0; i < 4; ++i) {
      step(1);
    }
    return finish();
  }

  print(run());
})();

// IR-LABEL: function global()
// IR-NOT: HasClosureTargetInst
// IR-NOT: CallInst {{.*}}%step()
// IR-NOT: CallInst {{.*}}%finish()
// IR-NOT: CallInst {{.*}}%run()
// IR-NOT: CallInst {{.*}}%main()
// IR: function_end
// IR-NOT: function {{[a-zA-Z_]}}

// EXEC: 25
