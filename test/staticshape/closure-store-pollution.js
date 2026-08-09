/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %shermes -O -exec -annotation-file=%S/closure-store-pollution.json %s | %FileCheckOrRegen %s --match-full-lines
// RUN: %shermes -O -dump-ir -annotation-file=%S/closure-store-pollution.json %s | %FileCheckOrRegen %s --check-prefix=OPT --match-full-lines

// A closure-property store is polluting even when the replacement has the
// statically compatible Object type. The intervening n store prevents direct
// store-to-load forwarding, so the call must not reuse oldTarget from the shape
// fact established by the binding guard.

function oldTarget() {
  return 42;
}

function test() {
  var o = {method: oldTarget, n: 0};
  o.method = function replacement() {
    return 99;
  };
  o.n = 1;
  return o.method();
}

print(test());

// Auto-generated content below. Please do not modify manually.

// CHECK:99

// OPT:function global(): any
// OPT-NEXT:%BB0:
// OPT-NEXT:       DeclareGlobalVarInst "oldTarget": string
// OPT-NEXT:       DeclareGlobalVarInst "test": string
// OPT-NEXT:  %2 = CreateFunctionInst (:object) empty: any, empty: any, %oldTarget(): functionCode
// OPT-NEXT:       StorePropertyLooseInst %2: object, globalObject: object, "oldTarget": string
// OPT-NEXT:  %4 = CreateFunctionInst (:object) empty: any, empty: any, %test(): functionCode
// OPT-NEXT:       StorePropertyLooseInst %4: object, globalObject: object, "test": string
// OPT-NEXT:  %6 = TryLoadGlobalPropertyInst (:any) globalObject: object, "print": string
// OPT-NEXT:  %7 = LoadPropertyInst (:any) globalObject: object, "test": string
// OPT-NEXT:  %8 = CallInst (:any) %7: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined
// OPT-NEXT:  %9 = CallInst (:any) %6: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, %8: any
// OPT-NEXT:        ReturnInst %9: any
// OPT-NEXT:function_end

// OPT:function oldTarget(): number
// OPT-NEXT:%BB0:
// OPT-NEXT:       ReturnInst 42: number
// OPT-NEXT:function_end

// OPT:function test(): any
// OPT-NEXT:%BB0:
// OPT-NEXT:  %0 = AllocObjectLiteralInst (:object) empty: any, "method": string, null: null, "n": string, 0: number
// OPT-NEXT:  %1 = LoadPropertyInst (:any) globalObject: object, "oldTarget": string
// OPT-NEXT:       PrStoreInst %1: any, %0: object, 0: number, "method": string
// OPT-NEXT:       TrySetStaticShapeInst %0: object, {method: object |closure:oldTarget, n: number}: null [ann#0]
// OPT-NEXT:  %4 = HasStaticShapeInst (:boolean) %0: object, {method: object |closure:oldTarget, n: number}: null [ann#0]
// OPT-NEXT:       CondBranchInst %4: boolean, %BB1, %BB2
// OPT-NEXT:%BB1:
// OPT-NEXT:  %6 = CreateFunctionInst (:object) empty: any, empty: any, %replacement(): functionCode
// OPT-NEXT:       PrStoreInst %6: object, %0: object, 0: number, "method": string
// OPT-NEXT:       StorePropertyLooseInst 1: number, %0: object, "n": string
// OPT-NEXT:  %9 = LoadPropertyInst (:any) %0: object, "method": string
// OPT-NEXT:  %10 = CallInst (:any) %9: any, empty: any, false: boolean, empty: any, undefined: undefined, %0: object
// OPT-NEXT:        ReturnInst %10: any
// OPT-NEXT:%BB2:
// OPT-NEXT:  %12 = CreateFunctionInst (:object) empty: any, empty: any, %replacement(): functionCode
// OPT-NEXT:        StorePropertyLooseInst %12: object, %0: object, "method": string
// OPT-NEXT:        StorePropertyLooseInst 1: number, %0: object, "n": string
// OPT-NEXT:  %15 = LoadPropertyInst (:any) %0: object, "method": string
// OPT-NEXT:  %16 = CallInst (:any) %15: any, empty: any, false: boolean, empty: any, undefined: undefined, %0: object
// OPT-NEXT:        ReturnInst %16: any
// OPT-NEXT:function_end

// OPT:function replacement(): number
// OPT-NEXT:%BB0:
// OPT-NEXT:       ReturnInst 99: number
// OPT-NEXT:function_end
