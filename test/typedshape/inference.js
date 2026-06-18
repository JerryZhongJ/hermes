/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %shermes -O -dump-ir -annotation-file=%S/inference.json %s | %FileCheck %s --match-full-lines

function simple(o) {
  return o.x;
}

function phiSame(c, a, b) {
  var p;
  if (c) {
    p = a;
  } else {
    p = b;
  }
  return p.x;
}

function phiDifferent(c, a, b) {
  var p;
  if (c) {
    p = a;
  } else {
    p = b;
  }
  return p.x;
}

function loopSame(n, a, b) {
  var p = a;
  for (var i = 0; i < n; i = i + 1) {
    p = b;
  }
  return p.x;
}

function loopDifferent(n, a, b) {
  var p = a;
  for (var i = 0; i < n; i = i + 1) {
    p = b;
  }
  return p.x;
}

// CHECK:function simple(o: any): any
// CHECK:       CondBranchInst {{.*}}, %BB1, %BB2
// CHECK:%BB1:
// CHECK:  {{.*}} = PrLoadInst (:number) {{.*}}, 0: number, "x": string
// CHECK:%BB2:
// CHECK:  {{.*}} = LoadPropertyInst (:any) {{.*}}, "x": string

// CHECK:function phiSame(c: any, a: any, b: any): any
// CHECK:       CondBranchInst {{.*}}
// CHECK:{{.*}}HasTypedShapeInst {{.*}}, {x: number}: null
// CHECK:{{.*}}HasTypedShapeInst {{.*}}, {x: number}: null
// CHECK:  {{.*}} = PhiInst {{.*}}
// CHECK:  {{.*}} = PrLoadInst (:number) {{.*}}, 0: number, "x": string

// CHECK:function phiDifferent(c: any, a: any, b: any): any
// CHECK-NOT:  {{.*}} = PrLoadInst (:number) {{.*}}, 0: number, "x": string
// CHECK:  {{.*}} = LoadPropertyInst (:any) {{.*}}, "x": string

// CHECK:function loopSame(n: any, a: any, b: any): any
// CHECK:{{.*}}HasTypedShapeInst {{.*}}, {x: number}: null
// CHECK:{{.*}}HasTypedShapeInst {{.*}}, {x: number}: null
// CHECK:  {{.*}} = PhiInst {{.*}}
// CHECK:  {{.*}} = LoadPropertyInst (:any) {{.*}}, "x": string

// CHECK:function loopDifferent(n: any, a: any, b: any): any
// CHECK:{{.*}}HasTypedShapeInst {{.*}}, {x: number}: null
// CHECK:{{.*}}HasTypedShapeInst {{.*}}, {x: string}: null
// CHECK-NOT:  {{.*}} = PrLoadInst (:number) {{.*}}, 0: number, "x": string
// CHECK:  {{.*}} = LoadPropertyInst (:any) {{.*}}, "x": string
