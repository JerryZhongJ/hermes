/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %shermes -O -exec -annotation-file=%S/vm.json %s | %FileCheck %s --match-full-lines
// RUN: %shermes -O -dump-ir -annotation-file=%S/vm.json %s | %FileCheckOrRegen %s --check-prefix=OPT --match-full-lines

function storePropertyOk() {
  var o = {x: 1};
  o.x = 2;
  return o.x;
}

function storePropertyBad() {
  var o = {x: 1};
  o.x = "bad";
  return o.x;
}

function makeTypedObject(v) {
  return {x: v};
}

function trySetSuccess() {
  var o = {x: 4};
  return o.x;
}

function trySetFailure() {
  var o = {x: "bad"};
  return o.x;
}

print("storePropertyOk", storePropertyOk());
print("storePropertyBad", storePropertyBad());
print("prStoreOk", makeTypedObject(3).x);
print("prStoreBad", makeTypedObject("bad").x);
print("trySetSuccess", trySetSuccess());
print("trySetFailure", trySetFailure());

// CHECK:storePropertyOk 2
// CHECK-NEXT:storePropertyBad bad
// These two calls share the same TrySet call site and ordinary source HC. The
// second call must still reject its string value after a structural cache hit.
// CHECK-NEXT:prStoreOk 3
// CHECK-NEXT:prStoreBad bad
// CHECK-NEXT:trySetSuccess 4
// CHECK-NEXT:trySetFailure bad

// Auto-generated content below. Please do not modify manually.

// OPT:function global(): any
// OPT-NEXT:%BB0:
// OPT-NEXT:       DeclareGlobalVarInst "storePropertyOk": string
// OPT-NEXT:       DeclareGlobalVarInst "storePropertyBad": string
// OPT-NEXT:       DeclareGlobalVarInst "makeTypedObject": string
// OPT-NEXT:       DeclareGlobalVarInst "trySetSuccess": string
// OPT-NEXT:       DeclareGlobalVarInst "trySetFailure": string
// OPT-NEXT:  %5 = CreateFunctionInst (:object) empty: any, empty: any, %storePropertyOk(): functionCode
// OPT-NEXT:       StorePropertyLooseInst %5: object, globalObject: object, "storePropertyOk": string
// OPT-NEXT:  %7 = CreateFunctionInst (:object) empty: any, empty: any, %storePropertyBad(): functionCode
// OPT-NEXT:       StorePropertyLooseInst %7: object, globalObject: object, "storePropertyBad": string
// OPT-NEXT:  %9 = CreateFunctionInst (:object) empty: any, empty: any, %makeTypedObject(): functionCode
// OPT-NEXT:        StorePropertyLooseInst %9: object, globalObject: object, "makeTypedObject": string
// OPT-NEXT:  %11 = CreateFunctionInst (:object) empty: any, empty: any, %trySetSuccess(): functionCode
// OPT-NEXT:        StorePropertyLooseInst %11: object, globalObject: object, "trySetSuccess": string
// OPT-NEXT:  %13 = CreateFunctionInst (:object) empty: any, empty: any, %trySetFailure(): functionCode
// OPT-NEXT:        StorePropertyLooseInst %13: object, globalObject: object, "trySetFailure": string
// OPT-NEXT:  %15 = TryLoadGlobalPropertyInst (:any) globalObject: object, "print": string
// OPT-NEXT:  %16 = LoadPropertyInst (:any) globalObject: object, "storePropertyOk": string
// OPT-NEXT:  %17 = CallInst (:any) %16: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined
// OPT-NEXT:  %18 = CallInst (:any) %15: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, "storePropertyOk": string, %17: any
// OPT-NEXT:  %19 = TryLoadGlobalPropertyInst (:any) globalObject: object, "print": string
// OPT-NEXT:  %20 = LoadPropertyInst (:any) globalObject: object, "storePropertyBad": string
// OPT-NEXT:  %21 = CallInst (:any) %20: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined
// OPT-NEXT:  %22 = CallInst (:any) %19: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, "storePropertyBad": string, %21: any
// OPT-NEXT:  %23 = TryLoadGlobalPropertyInst (:any) globalObject: object, "print": string
// OPT-NEXT:  %24 = LoadPropertyInst (:any) globalObject: object, "makeTypedObject": string
// OPT-NEXT:  %25 = CallInst (:any) %24: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, 3: number
// OPT-NEXT:  %26 = LoadPropertyInst (:any) %25: any, "x": string
// OPT-NEXT:  %27 = CallInst (:any) %23: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, "prStoreOk": string, %26: any
// OPT-NEXT:  %28 = TryLoadGlobalPropertyInst (:any) globalObject: object, "print": string
// OPT-NEXT:  %29 = LoadPropertyInst (:any) globalObject: object, "makeTypedObject": string
// OPT-NEXT:  %30 = CallInst (:any) %29: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, "bad": string
// OPT-NEXT:  %31 = LoadPropertyInst (:any) %30: any, "x": string
// OPT-NEXT:  %32 = CallInst (:any) %28: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, "prStoreBad": string, %31: any
// OPT-NEXT:  %33 = TryLoadGlobalPropertyInst (:any) globalObject: object, "print": string
// OPT-NEXT:  %34 = LoadPropertyInst (:any) globalObject: object, "trySetSuccess": string
// OPT-NEXT:  %35 = CallInst (:any) %34: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined
// OPT-NEXT:  %36 = CallInst (:any) %33: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, "trySetSuccess": string, %35: any
// OPT-NEXT:  %37 = TryLoadGlobalPropertyInst (:any) globalObject: object, "print": string
// OPT-NEXT:  %38 = LoadPropertyInst (:any) globalObject: object, "trySetFailure": string
// OPT-NEXT:  %39 = CallInst (:any) %38: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined
// OPT-NEXT:  %40 = CallInst (:any) %37: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, "trySetFailure": string, %39: any
// OPT-NEXT:        ReturnInst %40: any
// OPT-NEXT:function_end

// OPT:function storePropertyOk(): any
// OPT-NEXT:%BB0:
// OPT-NEXT:  %0 = AllocObjectLiteralInst (:object) empty: any, "x": string, 1: number
// OPT-NEXT:       TrySetStaticShapeInst %0: object, {x: number}: null [ann#0]
// OPT-NEXT:  %2 = HasStaticShapeInst (:boolean) %0: object, {x: number}: null [ann#0]
// OPT-NEXT:       CondBranchInst %2: boolean, %BB1, %BB2
// OPT-NEXT:%BB1:
// OPT-NEXT:       PrStoreInst 2: number, %0: object, 0: number, "x": string
// OPT-NEXT:       ReturnInst 2: number
// OPT-NEXT:%BB2:
// OPT-NEXT:       StorePropertyLooseInst 2: number, %0: object, "x": string
// OPT-NEXT:  %7 = LoadPropertyInst (:any) %0: object, "x": string
// OPT-NEXT:       ReturnInst %7: any
// OPT-NEXT:function_end

// OPT:function storePropertyBad(): any
// OPT-NEXT:%BB0:
// OPT-NEXT:  %0 = AllocObjectLiteralInst (:object) empty: any, "x": string, 1: number
// OPT-NEXT:       TrySetStaticShapeInst %0: object, {x: number}: null [ann#1]
// OPT-NEXT:  %2 = HasStaticShapeInst (:boolean) %0: object, {x: number}: null [ann#1]
// OPT-NEXT:       CondBranchInst %2: boolean, %BB1, %BB2
// OPT-NEXT:%BB1:
// OPT-NEXT:       PrStoreInst "bad": string, %0: object, 0: number, "x": string
// OPT-NEXT:  %5 = LoadPropertyInst (:any) %0: object, "x": string
// OPT-NEXT:       ReturnInst %5: any
// OPT-NEXT:%BB2:
// OPT-NEXT:       StorePropertyLooseInst "bad": string, %0: object, "x": string
// OPT-NEXT:  %8 = LoadPropertyInst (:any) %0: object, "x": string
// OPT-NEXT:       ReturnInst %8: any
// OPT-NEXT:function_end

// OPT:function makeTypedObject(v: any): object
// OPT-NEXT:%BB0:
// OPT-NEXT:  %0 = LoadParamInst (:any) %v: any
// OPT-NEXT:  %1 = AllocObjectLiteralInst (:object) empty: any, "x": string, null: null
// OPT-NEXT:       PrStoreInst %0: any, %1: object, 0: number, "x": string
// OPT-NEXT:       TrySetStaticShapeInst %1: object, {x: number}: null [ann#2]
// OPT-NEXT:  %4 = HasStaticShapeInst (:boolean) %1: object, {x: number}: null [ann#2]
// OPT-NEXT:       CondBranchInst %4: boolean, %BB1, %BB2
// OPT-NEXT:%BB1:
// OPT-NEXT:       ReturnInst %1: object
// OPT-NEXT:%BB2:
// OPT-NEXT:       ReturnInst %1: object
// OPT-NEXT:function_end

// OPT:function trySetSuccess(): any
// OPT-NEXT:%BB0:
// OPT-NEXT:  %0 = AllocObjectLiteralInst (:object) empty: any, "x": string, 4: number
// OPT-NEXT:       TrySetStaticShapeInst %0: object, {x: number}: null [ann#3]
// OPT-NEXT:  %2 = HasStaticShapeInst (:boolean) %0: object, {x: number}: null [ann#3]
// OPT-NEXT:       CondBranchInst %2: boolean, %BB1, %BB2
// OPT-NEXT:%BB1:
// OPT-NEXT:  %4 = PrLoadInst (:number) %0: object, 0: number, "x": string
// OPT-NEXT:       ReturnInst %4: number
// OPT-NEXT:%BB2:
// OPT-NEXT:  %6 = LoadPropertyInst (:any) %0: object, "x": string
// OPT-NEXT:       ReturnInst %6: any
// OPT-NEXT:function_end

// OPT:function trySetFailure(): any
// OPT-NEXT:%BB0:
// OPT-NEXT:  %0 = AllocObjectLiteralInst (:object) empty: any, "x": string, "bad": string
// OPT-NEXT:       TrySetStaticShapeInst %0: object, {x: number}: null [ann#4]
// OPT-NEXT:  %2 = HasStaticShapeInst (:boolean) %0: object, {x: number}: null [ann#4]
// OPT-NEXT:       CondBranchInst %2: boolean, %BB1, %BB2
// OPT-NEXT:%BB1:
// OPT-NEXT:  %4 = PrLoadInst (:number) %0: object, 0: number, "x": string
// OPT-NEXT:       ReturnInst %4: number
// OPT-NEXT:%BB2:
// OPT-NEXT:  %6 = LoadPropertyInst (:any) %0: object, "x": string
// OPT-NEXT:       ReturnInst %6: any
// OPT-NEXT:function_end
