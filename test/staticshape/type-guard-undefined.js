/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %shermes -exec -O -annotation-file=%S/type-guard-undefined.json %s | %FileCheck %s --check-prefix=EXEC
// RUN: %shermes -O0 -Xcustom-opt=insertguard -dump-ir -verify-ir -annotation-file=%S/type-guard-undefined.json %s | %FileCheck %s --check-prefix=INSERT

// Regression: an undefined type hint must not introduce the internal Uninit
// type into the user-visible value produced by UnionNarrowTrustedInst.

function guardUndefined(x) {
  if (!x)
    throw "error";
  return x;
}

try {
  guardUndefined();
} catch (e) {
  print(e);
}
print(guardUndefined(1));

// EXEC: error
// EXEC-NEXT: 1

// INSERT-LABEL:function guardUndefined(x: any):
// INSERT: = TypeOfIsInst (:boolean) {{.*}}: any, typeOfIs(Undefined) [ann#0]
// INSERT: = UnionNarrowTrustedInst (:undefined) {{.*}}: any
