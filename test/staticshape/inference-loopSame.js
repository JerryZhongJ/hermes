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
// CHECK-NEXT:       CondBranchInst %1: boolean, %BB9, %BB10
// CHECK-NEXT:%BB1:
// CHECK-NEXT:  %3 = PhiInst (:number) 0: number, %BB7, %17: number, %BB5
// CHECK-NEXT:  %4 = HasStaticShapeInst (:boolean) %37: any, {x: number}: null [ann#2]
// CHECK-NEXT:       CondBranchInst %4: boolean, %BB5, %BB6
// CHECK-NEXT:%BB2:
// CHECK-NEXT:  %6 = PhiInst (:any) %36: any, %BB7, %37: any, %BB5
// CHECK-NEXT:  %7 = PrLoadInst (:number) %6: any, 0: number, "x": string
// CHECK-NEXT:       ReturnInst %7: number
// CHECK-NEXT:%BB3:
// CHECK-NEXT:  %9 = PhiInst (:number) 0: number, %BB8, %25: number, %BB6
// CHECK-NEXT:  %10 = PhiInst (:any) %30: any, %BB8, %21: any, %BB6
// CHECK-NEXT:  %11 = PhiInst (:any) %31: any, %BB8, %22: any, %BB6
// CHECK-NEXT:  %12 = PhiInst (:any) %32: any, %BB8, %24: any, %BB6
// CHECK-NEXT:        BranchInst %BB6
// CHECK-NEXT:%BB4:
// CHECK-NEXT:  %14 = PhiInst (:any) %32: any, %BB8, %23: any, %BB6
// CHECK-NEXT:  %15 = LoadPropertyInst (:any) %14: any, "x": string
// CHECK-NEXT:        ReturnInst %15: any
// CHECK-NEXT:%BB5:
// CHECK-NEXT:  %17 = FAddInst (:number) %3: number, 1: number
// CHECK-NEXT:  %18 = FLessThanInst (:boolean) %17: number, %35: number
// CHECK-NEXT:        CondBranchInst %18: boolean, %BB1, %BB2
// CHECK-NEXT:%BB6:
// CHECK-NEXT:  %20 = PhiInst (:number) %9: number, %BB3, %3: number, %BB1
// CHECK-NEXT:  %21 = PhiInst (:any) %10: any, %BB3, %37: any, %BB1
// CHECK-NEXT:  %22 = PhiInst (:any) %11: any, %BB3, %35: number, %BB1
// CHECK-NEXT:  %23 = PhiInst (:any) %10: any, %BB3, %37: any, %BB1
// CHECK-NEXT:  %24 = PhiInst (:any) %12: any, %BB3, %36: any, %BB1
// CHECK-NEXT:  %25 = FAddInst (:number) %20: number, 1: number
// CHECK-NEXT:  %26 = BinaryLessThanInst (:boolean) %25: number, %22: any
// CHECK-NEXT:        CondBranchInst %26: boolean, %BB3, %BB4
// CHECK-NEXT:%BB7:
// CHECK-NEXT:  %28 = FLessThanInst (:boolean) 0: number, %35: number
// CHECK-NEXT:        CondBranchInst %28: boolean, %BB1, %BB2
// CHECK-NEXT:%BB8:
// CHECK-NEXT:  %30 = PhiInst (:any) %41: any, %BB10, %37: any, %BB9
// CHECK-NEXT:  %31 = PhiInst (:any) %0: any, %BB10, %35: number, %BB9
// CHECK-NEXT:  %32 = PhiInst (:any) %40: any, %BB10, %36: any, %BB9
// CHECK-NEXT:  %33 = BinaryLessThanInst (:boolean) 0: number, %31: any
// CHECK-NEXT:        CondBranchInst %33: boolean, %BB3, %BB4
// CHECK-NEXT:%BB9:
// CHECK-NEXT:  %35 = UnionNarrowTrustedInst (:number) %0: any
// CHECK-NEXT:  %36 = LoadParamInst (:any) %a: any
// CHECK-NEXT:  %37 = LoadParamInst (:any) %b: any
// CHECK-NEXT:  %38 = HasStaticShapeInst (:boolean) %36: any, {x: number}: null [ann#1]
// CHECK-NEXT:        CondBranchInst %38: boolean, %BB7, %BB8
// CHECK-NEXT:%BB10:
// CHECK-NEXT:  %40 = LoadParamInst (:any) %a: any
// CHECK-NEXT:  %41 = LoadParamInst (:any) %b: any
// CHECK-NEXT:        BranchInst %BB8
// CHECK-NEXT:function_end
