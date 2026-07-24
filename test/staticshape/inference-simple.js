// RUN: %shermes -O -dump-ir -Xdump-functions=simple -annotation-file=%S/inference-simple.json %s | %FileCheckOrRegen %s --match-full-lines

function simple(o) {
  return o.x;
}

// Auto-generated content below. Please do not modify manually.

// CHECK:function simple(o: any): any
// CHECK-NEXT:%BB0:
// CHECK-NEXT:  %0 = LoadParamInst (:any) %o: any
// CHECK-NEXT:  %1 = LoadPropertyInst (:any) %0: any, "x": string
// CHECK-NEXT:       ReturnInst %1: any
// CHECK-NEXT:function_end
