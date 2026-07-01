// RUN: %shermes -O -dump-ir -Xdump-functions=simple -annotation-file=%S/inference-simple.json %s | %FileCheckOrRegen %s --match-full-lines

function simple(o) {
  return o.x;
}

// Auto-generated content below. Please do not modify manually.

// CHECK:function simple(o: any): any
// CHECK-NEXT:%BB0:
// CHECK-NEXT:  %0 = LoadParamInst (:any) %o: any
// CHECK-NEXT:  %1 = HasStaticShapeInst (:boolean) %0: any, {x: number}: null
// CHECK-NEXT:       CondBranchInst %1: boolean, %BB1, %BB2
// CHECK-NEXT:%BB1:
// CHECK-NEXT:  %3 = PrLoadInst (:number) %0: any, 0: number, "x": string
// CHECK-NEXT:       ReturnInst %3: number
// CHECK-NEXT:%BB2:
// CHECK-NEXT:  %5 = LoadPropertyInst (:any) %0: any, "x": string
// CHECK-NEXT:       ReturnInst %5: any
// CHECK-NEXT:function_end
