// RUN: %shermes -O -dump-ir -Xdump-functions=phiSame -annotation-file=%S/inference-phiSame.json %s | %FileCheckOrRegen %s --match-full-lines

function phiSame(c, a, b) {
  var p;
  if (c) {
    p = a;
  } else {
    p = b;
  }
  return p.x;
}

// Auto-generated content below. Please do not modify manually.

// CHECK:function phiSame(c: any, a: any, b: any): any
// CHECK-NEXT:%BB0:
// CHECK-NEXT:  %0 = LoadParamInst (:any) %c: any
// CHECK-NEXT:  %1 = LoadParamInst (:any) %a: any
// CHECK-NEXT:  %2 = LoadParamInst (:any) %b: any
// CHECK-NEXT:       CondBranchInst %0: any, %BB1, %BB2
// CHECK-NEXT:%BB1:
// CHECK-NEXT:  %4 = HasStaticShapeInst (:boolean) %1: any, {x: number}: null
// CHECK-NEXT:       CondBranchInst %4: boolean, %BB3, %BB4
// CHECK-NEXT:%BB2:
// CHECK-NEXT:  %6 = HasStaticShapeInst (:boolean) %2: any, {x: number}: null
// CHECK-NEXT:       CondBranchInst %6: boolean, %BB3, %BB4
// CHECK-NEXT:%BB3:
// CHECK-NEXT:  %8 = PhiInst (:any) %2: any, %BB2, %1: any, %BB1
// CHECK-NEXT:  %9 = PrLoadInst (:number) %8: any, 0: number, "x": string
// CHECK-NEXT:        ReturnInst %9: number
// CHECK-NEXT:%BB4:
// CHECK-NEXT:  %11 = PhiInst (:any) %2: any, %BB2, %1: any, %BB1
// CHECK-NEXT:  %12 = LoadPropertyInst (:any) %11: any, "x": string
// CHECK-NEXT:        ReturnInst %12: any
// CHECK-NEXT:function_end
