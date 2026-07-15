/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %shermes -O -exec -annotation-file=%S/accessor-shape-store.json %s | %FileCheck %s --match-full-lines
// RUN: %shermes -O -dump-ir -annotation-file=%S/accessor-shape-store.json %s | %FileCheckOrRegen %s --check-prefix=OPT --match-full-lines

// Store path: a data property store must become PrStore; an accessor property
// store (setter invocation) must stay StoreProperty, never PrStore.
function test() {
  var o = {count: 0, get log() { return this.count; }, set log(v) {}};
  o.count = 5;
  o.log = 9;
  return o.count;
}
print(test());

// CHECK: 5

// Auto-generated content below. Please do not modify manually.

// OPT:function global(): any
// OPT-NEXT:%BB0:
// OPT-NEXT:       DeclareGlobalVarInst "test": string
// OPT-NEXT:  %1 = CreateFunctionInst (:object) empty: any, empty: any, %test(): functionCode
// OPT-NEXT:       StorePropertyLooseInst %1: object, globalObject: object, "test": string
// OPT-NEXT:  %3 = TryLoadGlobalPropertyInst (:any) globalObject: object, "print": string
// OPT-NEXT:  %4 = LoadPropertyInst (:any) globalObject: object, "test": string
// OPT-NEXT:  %5 = CallInst (:any) %4: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined
// OPT-NEXT:  %6 = CallInst (:any) %3: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, %5: any
// OPT-NEXT:       ReturnInst %6: any
// OPT-NEXT:function_end

// OPT:function test(): any
// OPT-NEXT:%BB0:
// OPT-NEXT:  %0 = AllocObjectLiteralInst (:object) empty: any, "count": string, 0: number
// OPT-NEXT:  %1 = CreateFunctionInst (:object) empty: any, empty: any, %"get log"(): functionCode
// OPT-NEXT:  %2 = CreateFunctionInst (:object) empty: any, empty: any, %"set log"(): functionCode
// OPT-NEXT:       DefineOwnGetterSetterInst %1: object, %2: object, %0: object, "log": string, true: boolean
// OPT-NEXT:       TrySetStaticShapeInst %0: object, {count: number, log: any |accessor}: null [ann#0]
// OPT-NEXT:  %5 = HasStaticShapeInst (:boolean) %0: object, {count: number, log: any |accessor}: null [ann#0]
// OPT-NEXT:       CondBranchInst %5: boolean, %BB1, %BB2
// OPT-NEXT:%BB1:
// OPT-NEXT:       PrStoreInst 5: number, %0: object, 0: number, "count": string
// OPT-NEXT:       StorePropertyLooseInst 9: number, %0: object, "log": string
// OPT-NEXT:  %9 = LoadPropertyInst (:any) %0: object, "count": string
// OPT-NEXT:        ReturnInst %9: any
// OPT-NEXT:%BB2:
// OPT-NEXT:        StorePropertyLooseInst 5: number, %0: object, "count": string
// OPT-NEXT:        StorePropertyLooseInst 9: number, %0: object, "log": string
// OPT-NEXT:  %13 = LoadPropertyInst (:any) %0: object, "count": string
// OPT-NEXT:        ReturnInst %13: any
// OPT-NEXT:function_end

// OPT:function "get log"(): any
// OPT-NEXT:%BB0:
// OPT-NEXT:  %0 = LoadParamInst (:any) %<this>: any
// OPT-NEXT:  %1 = CoerceThisNSInst (:object) %0: any
// OPT-NEXT:  %2 = LoadPropertyInst (:any) %1: object, "count": string
// OPT-NEXT:       ReturnInst %2: any
// OPT-NEXT:function_end

// OPT:function "set log"(v: any): undefined
// OPT-NEXT:%BB0:
// OPT-NEXT:       ReturnInst undefined: undefined
// OPT-NEXT:function_end
