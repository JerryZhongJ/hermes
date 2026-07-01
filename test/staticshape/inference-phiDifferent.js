// RUN: %shermes -O -dump-ir -Xdump-functions=phiDifferent -annotation-file=%S/inference-phiDifferent.json %s | %FileCheckOrRegen %s --match-full-lines

function phiDifferent(c, a, b) {
  var p;
  if (c) {
    p = a;
  } else {
    p = b;
  }
  return p.x;
}

// Auto-generated content below. Please do not modify manually.

// CHECK:function phiDifferent(c: any, a: any, b: any): any
// CHECK-NEXT:%BB0:
// CHECK-NEXT:  %0 = LoadParamInst (:any) %c: any
// CHECK-NEXT:  %1 = LoadParamInst (:any) %a: any
// CHECK-NEXT:  %2 = LoadParamInst (:any) %b: any
// CHECK-NEXT:       CondBranchInst %0: any, %BB2, %BB1
// CHECK-NEXT:%BB1:
// CHECK-NEXT:       BranchInst %BB2
// CHECK-NEXT:%BB2:
// CHECK-NEXT:  %5 = PhiInst (:any) %2: any, %BB1, %1: any, %BB0
// CHECK-NEXT:  %6 = LoadPropertyInst (:any) %5: any, "x": string
// CHECK-NEXT:       ReturnInst %6: any
// CHECK-NEXT:function_end
