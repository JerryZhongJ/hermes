/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %shermes -O -dump-ir -annotation-file=%S/heap_load_opts.json %s | %FileCheckOrRegen %s --check-prefix=IR

function f(o) {
  var a = o.x;
  var b = o.x;
  return a + b;
}

var obj = {x:1, y:2};
print(f(obj));

// Auto-generated content below. Please do not modify manually.

// IR:function global(): any
// IR-NEXT:%BB0:
// IR-NEXT:       DeclareGlobalVarInst "f": string
// IR-NEXT:       DeclareGlobalVarInst "obj": string
// IR-NEXT:  %2 = CreateFunctionInst (:object) empty: any, empty: any, %f(): functionCode
// IR-NEXT:       StorePropertyLooseInst %2: object, globalObject: object, "f": string
// IR-NEXT:  %4 = AllocObjectLiteralInst (:object) empty: any, "x": string, 1: number, "y": string, 2: number
// IR-NEXT:       StorePropertyLooseInst %4: object, globalObject: object, "obj": string
// IR-NEXT:       TrySetStaticShapeInst %4: object, {x: number, y: number}: null [ann#1]
// IR-NEXT:  %7 = TryLoadGlobalPropertyInst (:any) globalObject: object, "print": string
// IR-NEXT:  %8 = LoadPropertyInst (:any) globalObject: object, "f": string
// IR-NEXT:  %9 = LoadPropertyInst (:any) globalObject: object, "obj": string
// IR-NEXT:  %10 = CallInst (:any) %8: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, %9: any
// IR-NEXT:  %11 = CallInst (:any) %7: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, %10: any
// IR-NEXT:        ReturnInst %11: any
// IR-NEXT:function_end

// IR:function f(o: any): string|number|bigint
// IR-NEXT:%BB0:
// IR-NEXT:  %0 = LoadParamInst (:any) %o: any
// IR-NEXT:  %1 = HasStaticShapeInst (:boolean) %0: any, {x: number, y: number}: null [ann#0]
// IR-NEXT:       CondBranchInst %1: boolean, %BB1, %BB2
// IR-NEXT:%BB1:
// IR-NEXT:  %3 = PrLoadInst (:number) %0: any, 0: number, "x": string
// IR-NEXT:  %4 = FAddInst (:number) %3: number, %3: number
// IR-NEXT:       ReturnInst %4: number
// IR-NEXT:%BB2:
// IR-NEXT:  %6 = LoadPropertyInst (:any) %0: any, "x": string
// IR-NEXT:  %7 = LoadPropertyInst (:any) %0: any, "x": string
// IR-NEXT:  %8 = BinaryAddInst (:string|number|bigint) %6: any, %7: any
// IR-NEXT:       ReturnInst %8: string|number|bigint
// IR-NEXT:function_end
