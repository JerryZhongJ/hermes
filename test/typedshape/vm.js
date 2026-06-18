/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %shermes -O -exec -annotation-file=%S/vm.json %s | %FileCheck %s --match-full-lines
// RUN: %shermes -O -dump-ir -annotation-file=%S/vm.json %s | %FileCheck %s --check-prefix=OPT

function storePropertyOk() {
  var o = {x: 1};
  o.x = 2;
  return o.x;
}

function storePropertyBad() {
  var o = {x: 1};
  o.x = "bad";
  return o.x;
}

function makeTypedObject(v) {
  return {x: v};
}

function trySetSuccess() {
  var o = {x: 4};
  return o.x;
}

function trySetFailure() {
  var o = {x: "bad"};
  return o.x;
}

print("storePropertyOk", storePropertyOk());
print("storePropertyBad", storePropertyBad());
print("prStoreOk", makeTypedObject(3).x);
print("prStoreBad", makeTypedObject("bad").x);
print("trySetSuccess", trySetSuccess());
print("trySetFailure", trySetFailure());

// CHECK:storePropertyOk 2
// CHECK-NEXT:storePropertyBad bad
// CHECK-NEXT:prStoreOk 3
// CHECK-NEXT:prStoreBad bad
// CHECK-NEXT:trySetSuccess 4
// CHECK-NEXT:trySetFailure bad

// OPT:function storePropertyOk(): any
// OPT:       TrySetTypedShapeInst {{.*}}, {x: number}: null
// OPT:       StorePropertyLooseInst {{.*}}, "x": string
// OPT:  {{.*}} = LoadPropertyInst (:any) {{.*}}, "x": string

// OPT:function storePropertyBad(): any
// OPT:       TrySetTypedShapeInst {{.*}}, {x: number}: null
// OPT:       StorePropertyLooseInst {{.*}}, "x": string
// OPT:  {{.*}} = LoadPropertyInst (:any) {{.*}}, "x": string

// OPT:function makeTypedObject(v: any): object
// OPT:       PrStoreInst {{.*}}, 0: number, "x": string
// OPT:       ReturnInst {{.*}}: object

// OPT:function trySetSuccess(): any
// OPT:       TrySetTypedShapeInst {{.*}}, {x: number}: null
// OPT:  {{.*}} = LoadPropertyInst (:any) {{.*}}, "x": string

// OPT:function trySetFailure(): any
// OPT:       TrySetTypedShapeInst {{.*}}, {x: number}: null
// OPT:  {{.*}} = LoadPropertyInst (:any) {{.*}}, "x": string
