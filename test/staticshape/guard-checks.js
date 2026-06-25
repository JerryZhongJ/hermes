/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %shermes -O0 -dump-ir -annotation-file=%S/guard-checks.json %s | %FileCheck %s --check-prefix=IRGEN --match-full-lines
// RUN: %shermes -O0 -Xcustom-opt=insertguard -dump-ir -verify-ir -annotation-file=%S/guard-checks.json %s | %FileCheck %s --check-prefix=INSERT --match-full-lines

function typeGuard(x) {
  return x + 1;
}

function shapeStatement() {
  var obj = {x: 1};
  return obj.x;
}

// IRGEN:function typeGuard(x: any): any
// IRGEN:  [[TYPEVAL:%[0-9]+]] = BinaryAddInst (:any) {{.*}}
// IRGEN-NEXT:  {{%[0-9]+}} = TypeOfIsInst (:boolean) [[TYPEVAL]]: any, typeOfIs(Number) [ann#0]
// IRGEN-NEXT:       ReturnInst [[TYPEVAL]]: any

// IRGEN:function shapeStatement(): any
// IRGEN:       TrySetTypedShapeInst [[OBJ:%[0-9]+]]: object, {x: number}: null
// IRGEN-NEXT:  {{%[0-9]+}} = HasTypedShapeInst (:boolean) [[OBJ]]: object, {x: number}: null

// INSERT:function typeGuard(x: any): any
// INSERT:  [[GUARDED:%[0-9]+]] = BinaryAddInst (:any) {{.*}}
// INSERT-NEXT:  [[TYPECHECK:%[0-9]+]] = TypeOfIsInst (:boolean) [[GUARDED]]: any, typeOfIs(Number) [ann#0]
// INSERT-NEXT:       CondBranchInst [[TYPECHECK]]: boolean, %BB1, %BB2
// INSERT:%BB1:
// INSERT-NEXT:  {{%[0-9]+}} = UnionNarrowTrustedInst (:number) [[GUARDED]]: any

// INSERT:function shapeStatement(): any
// INSERT:  [[SHAPECHECK:%[0-9]+]] = HasTypedShapeInst (:boolean) [[SHAPEOBJ:%[0-9]+]]: object, {x: number}: null
// INSERT-NEXT:       CondBranchInst [[SHAPECHECK]]: boolean, %BB1, %BB2
