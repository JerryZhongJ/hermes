// RUN: %shermes -O -dump-ir -Xdump-functions=loopSame -annotation-file=%S/inference-loopSame.json %s | %FileCheckOrRegen %s --match-full-lines

function loopSame(n, a, b) {
  var p = a;
  for (var i = 0; i < n; i = i + 1) {
    p = b;
  }
  return p.x;
}

// Auto-generated content below. Please do not modify manually.

// CHECK:function loopSame(n: any, a: any, b: any): any
// CHECK-NEXT:%BB0:
// CHECK-NEXT:  %0 = LoadParamInst (:any) %n: any
// CHECK-NEXT:  %1 = TypeOfIsInst (:boolean) %0: any, typeOfIs(Number) [ann#0]
// CHECK-NEXT:       CondBranchInst %1: boolean, %BB5, %BB6
// CHECK-NEXT:%BB1:
// CHECK-NEXT:  %3 = PhiInst (:number) 0: number, %BB5, %4: number, %BB1
// CHECK-NEXT:  %4 = FAddInst (:number) %3: number, 1: number
// CHECK-NEXT:  %5 = FLessThanInst (:boolean) %4: number, %17: number
// CHECK-NEXT:       CondBranchInst %5: boolean, %BB1, %BB2
// CHECK-NEXT:%BB2:
// CHECK-NEXT:  %7 = PhiInst (:any) %18: any, %BB5, %19: any, %BB1
// CHECK-NEXT:  %8 = LoadPropertyInst (:any) %7: any, "x": string
// CHECK-NEXT:       ReturnInst %8: any
// CHECK-NEXT:%BB3:
// CHECK-NEXT:  %10 = PhiInst (:number) 0: number, %BB6, %11: number, %BB3
// CHECK-NEXT:  %11 = FAddInst (:number) %10: number, 1: number
// CHECK-NEXT:  %12 = BinaryLessThanInst (:boolean) %11: number, %0: any
// CHECK-NEXT:        CondBranchInst %12: boolean, %BB3, %BB4
// CHECK-NEXT:%BB4:
// CHECK-NEXT:  %14 = PhiInst (:any) %22: any, %BB6, %23: any, %BB3
// CHECK-NEXT:  %15 = LoadPropertyInst (:any) %14: any, "x": string
// CHECK-NEXT:        ReturnInst %15: any
// CHECK-NEXT:%BB5:
// CHECK-NEXT:  %17 = UnionNarrowTrustedInst (:number) %0: any
// CHECK-NEXT:  %18 = LoadParamInst (:any) %a: any
// CHECK-NEXT:  %19 = LoadParamInst (:any) %b: any
// CHECK-NEXT:  %20 = FLessThanInst (:boolean) 0: number, %17: number
// CHECK-NEXT:        CondBranchInst %20: boolean, %BB1, %BB2
// CHECK-NEXT:%BB6:
// CHECK-NEXT:  %22 = LoadParamInst (:any) %a: any
// CHECK-NEXT:  %23 = LoadParamInst (:any) %b: any
// CHECK-NEXT:  %24 = BinaryLessThanInst (:boolean) 0: number, %0: any
// CHECK-NEXT:        CondBranchInst %24: boolean, %BB3, %BB4
// CHECK-NEXT:function_end
