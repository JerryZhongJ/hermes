// RUN: %shermes -O -dump-ir -Xdump-functions=loopDifferent -annotation-file=%S/inference-loopDifferent.json %s | %FileCheckOrRegen %s --match-full-lines

function loopDifferent(n, a, b) {
  var p = a;
  for (var i = 0; i < n; i = i + 1) {
    p = b;
  }
  return p.x;
}

// Auto-generated content below. Please do not modify manually.

// CHECK:function loopDifferent(n: any, a: any, b: any): any
// CHECK-NEXT:%BB0:
// CHECK-NEXT:  %0 = LoadParamInst (:any) %n: any
// CHECK-NEXT:  %1 = LoadParamInst (:any) %a: any
// CHECK-NEXT:  %2 = LoadParamInst (:any) %b: any
// CHECK-NEXT:  %3 = BinaryLessThanInst (:boolean) 0: number, %0: any
// CHECK-NEXT:       CondBranchInst %3: boolean, %BB1, %BB2
// CHECK-NEXT:%BB1:
// CHECK-NEXT:  %5 = PhiInst (:number) 0: number, %BB0, %6: number, %BB1
// CHECK-NEXT:  %6 = FAddInst (:number) %5: number, 1: number
// CHECK-NEXT:  %7 = BinaryLessThanInst (:boolean) %6: number, %0: any
// CHECK-NEXT:       CondBranchInst %7: boolean, %BB1, %BB2
// CHECK-NEXT:%BB2:
// CHECK-NEXT:  %9 = PhiInst (:any) %1: any, %BB0, %2: any, %BB1
// CHECK-NEXT:  %10 = LoadPropertyInst (:any) %9: any, "x": string
// CHECK-NEXT:        ReturnInst %10: any
// CHECK-NEXT:function_end
