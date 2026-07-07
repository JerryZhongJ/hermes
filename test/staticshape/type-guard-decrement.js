/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %shermes -exec -O -annotation-file=%S/type-guard-decrement.json %s | %FileCheck %s --check-prefix=EXEC
// RUN: %shermes -O0 -Xcustom-opt=insertguard -dump-ir -verify-ir -annotation-file=%S/type-guard-decrement.json %s | %FileCheck %s --check-prefix=INSERT --match-full-lines

// Regression: a type hint on a prefix decrement `--n`. IRGen emits
// UnaryDec -> StoreFrame(writeback) -> TypeOfIsInst, so the guard does NOT
// immediately follow its operand. InsertGuard must take the dominator-tree
// slow path, which keeps the StoreFrame on the original operand instead of
// redirecting it to the post-check UnionNarrowTrusted. Without that, the
// StoreFrame forms a use-before-def and the loop reads undefined -> result 0.

function dec(n) {
  var sum = 0;
  while (--n > 0) {
    sum += n;
  }
  return sum;
}

print(dec(10));

// EXEC: 45

// After InsertGuard, the StoreFrame writeback of `--n` must still reference the
// original operand ([[DEC]]) and NOT the post-check UnionNarrowTrusted. The
// guard does not immediately follow its operand (StoreFrame is between them),
// so this exercises the dominator-tree slow path.
// INSERT:function dec(n: any): any
// INSERT:  [[DEC:%[0-9]+]] = UnaryDecInst (:number|bigint) {{.*}}
// INSERT-NEXT:       StoreFrameInst {{%[0-9]+}}: environment, [[DEC]]: number|bigint, {{.*}}
// INSERT-NEXT:  [[CHK:%[0-9]+]] = TypeOfIsInst (:boolean) [[DEC]]: number|bigint, typeOfIs(Number) [ann#0]
// INSERT-NEXT:        CondBranchInst [[CHK]]: boolean, {{%BB[0-9]+}}, {{%BB[0-9]+}}
