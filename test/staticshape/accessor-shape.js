/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %shermes -O -exec -annotation-file=%S/accessor-shape.json %s | %FileCheck %s --match-full-lines
// RUN: %shermes -O -dump-ir -annotation-file=%S/accessor-shape.json %s | %FileCheckOrRegen %s --check-prefix=OPT --match-full-lines

// Creation and use are split across functions (makeObj builds, useObj consumes
// via a shape binding on its parameter). The shape mixes data and accessor
// properties: an accessor access (o.b) kills the shape fact, so a later data
// access (o.c) can no longer PrLoad even though c is itself data.
function makeObj() {
  var o = {a: 1, get b() { return 2; }, c: 3};
  return o;
}
function useObj(o) {
  return o.a + o.b + o.c;
}
print(useObj(makeObj()));

// CHECK: 6

// Auto-generated content below. Please do not modify manually.

// OPT:function global(): any
// OPT-NEXT:%BB0:
// OPT-NEXT:       DeclareGlobalVarInst "makeObj": string
// OPT-NEXT:       DeclareGlobalVarInst "useObj": string
// OPT-NEXT:  %2 = CreateFunctionInst (:object) empty: any, empty: any, %makeObj(): functionCode
// OPT-NEXT:       StorePropertyLooseInst %2: object, globalObject: object, "makeObj": string
// OPT-NEXT:  %4 = CreateFunctionInst (:object) empty: any, empty: any, %useObj(): functionCode
// OPT-NEXT:       StorePropertyLooseInst %4: object, globalObject: object, "useObj": string
// OPT-NEXT:  %6 = TryLoadGlobalPropertyInst (:any) globalObject: object, "print": string
// OPT-NEXT:  %7 = LoadPropertyInst (:any) globalObject: object, "useObj": string
// OPT-NEXT:  %8 = LoadPropertyInst (:any) globalObject: object, "makeObj": string
// OPT-NEXT:  %9 = CallInst (:any) %8: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined
// OPT-NEXT:  %10 = CallInst (:any) %7: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, %9: any
// OPT-NEXT:  %11 = CallInst (:any) %6: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, %10: any
// OPT-NEXT:        ReturnInst %11: any
// OPT-NEXT:function_end

// OPT:function makeObj(): object
// OPT-NEXT:%BB0:
// OPT-NEXT:  %0 = AllocObjectLiteralInst (:object) empty: any, "a": string, 1: number
// OPT-NEXT:  %1 = CreateFunctionInst (:object) empty: any, empty: any, %"get b"(): functionCode
// OPT-NEXT:       DefineOwnGetterSetterInst %1: object, undefined: undefined, %0: object, "b": string, true: boolean
// OPT-NEXT:       DefineOwnPropertyInst 3: number, %0: object, "c": string, true: boolean
// OPT-NEXT:       ReturnInst %0: object
// OPT-NEXT:function_end

// OPT:function useObj(o: any): string|number|bigint
// OPT-NEXT:%BB0:
// OPT-NEXT:  %0 = LoadParamInst (:any) %o: any
// OPT-NEXT:       TrySetStaticShapeInst %0: any, {a: number, b: any |accessor, c: number}: null [ann#0]
// OPT-NEXT:  %2 = HasStaticShapeInst (:boolean) %0: any, {a: number, b: any |accessor, c: number}: null [ann#0]
// OPT-NEXT:       CondBranchInst %2: boolean, %BB1, %BB2
// OPT-NEXT:%BB1:
// OPT-NEXT:  %4 = PrLoadInst (:number) %0: any, 0: number, "a": string
// OPT-NEXT:  %5 = LoadPropertyInst (:any) %0: any, "b": string
// OPT-NEXT:  %6 = BinaryAddInst (:string|number) %4: number, %5: any
// OPT-NEXT:  %7 = LoadPropertyInst (:any) %0: any, "c": string
// OPT-NEXT:  %8 = BinaryAddInst (:string|number) %6: string|number, %7: any
// OPT-NEXT:       ReturnInst %8: string|number
// OPT-NEXT:%BB2:
// OPT-NEXT:  %10 = LoadPropertyInst (:any) %0: any, "a": string
// OPT-NEXT:  %11 = LoadPropertyInst (:any) %0: any, "b": string
// OPT-NEXT:  %12 = BinaryAddInst (:string|number|bigint) %10: any, %11: any
// OPT-NEXT:  %13 = LoadPropertyInst (:any) %0: any, "c": string
// OPT-NEXT:  %14 = BinaryAddInst (:string|number|bigint) %12: string|number|bigint, %13: any
// OPT-NEXT:        ReturnInst %14: string|number|bigint
// OPT-NEXT:function_end

// OPT:function "get b"(): number
// OPT-NEXT:%BB0:
// OPT-NEXT:       ReturnInst 2: number
// OPT-NEXT:function_end
