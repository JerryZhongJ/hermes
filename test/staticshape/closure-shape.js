/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %shermes -O -exec -annotation-file=%S/closure-shape.json %s | %FileCheck %s --match-full-lines
// RUN: %shermes -O -dump-ir -annotation-file=%S/closure-shape.json %s | %FileCheckOrRegen %s --check-prefix=OPT --match-full-lines

// Construction (make) and use (use) are split so the receiver is a parameter,
// not a global load. The method slot holds methodFunc, so o.method() inlines
// to 42.

function methodFunc() {
  return 42;
}

function make() {
  var o = {method: methodFunc};
  return o;
}

function use(o) {
  return o.method();
}

print(use(make()));

// CHECK: 42

// Auto-generated content below. Please do not modify manually.

// OPT:function global(): any
// OPT-NEXT:%BB0:
// OPT-NEXT:       DeclareGlobalVarInst "methodFunc": string
// OPT-NEXT:       DeclareGlobalVarInst "make": string
// OPT-NEXT:       DeclareGlobalVarInst "use": string
// OPT-NEXT:  %3 = CreateFunctionInst (:object) empty: any, empty: any, %methodFunc(): functionCode
// OPT-NEXT:       StorePropertyLooseInst %3: object, globalObject: object, "methodFunc": string
// OPT-NEXT:  %5 = CreateFunctionInst (:object) empty: any, empty: any, %make(): functionCode
// OPT-NEXT:       StorePropertyLooseInst %5: object, globalObject: object, "make": string
// OPT-NEXT:  %7 = CreateFunctionInst (:object) empty: any, empty: any, %use(): functionCode
// OPT-NEXT:       StorePropertyLooseInst %7: object, globalObject: object, "use": string
// OPT-NEXT:  %9 = TryLoadGlobalPropertyInst (:any) globalObject: object, "print": string
// OPT-NEXT:  %10 = LoadPropertyInst (:any) globalObject: object, "use": string
// OPT-NEXT:  %11 = LoadPropertyInst (:any) globalObject: object, "make": string
// OPT-NEXT:  %12 = CallInst (:any) %11: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined
// OPT-NEXT:  %13 = CallInst (:any) %10: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, %12: any
// OPT-NEXT:  %14 = CallInst (:any) %9: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, %13: any
// OPT-NEXT:        ReturnInst %14: any
// OPT-NEXT:function_end

// OPT:function methodFunc(): number
// OPT-NEXT:%BB0:
// OPT-NEXT:       ReturnInst 42: number
// OPT-NEXT:function_end

// OPT:function make(): object
// OPT-NEXT:%BB0:
// OPT-NEXT:  %0 = AllocObjectLiteralInst (:object) empty: any, "method": string, null: null
// OPT-NEXT:  %1 = LoadPropertyInst (:any) globalObject: object, "methodFunc": string
// OPT-NEXT:       PrStoreInst %1: any, %0: object, 0: number, "method": string
// OPT-NEXT:       TrySetStaticShapeInst %0: object, {method: object |closure:methodFunc}: null [ann#1]
// OPT-NEXT:  %4 = HasStaticShapeInst (:boolean) %0: object, {method: object |closure:methodFunc}: null [ann#1]
// OPT-NEXT:       CondBranchInst %4: boolean, %BB1, %BB2
// OPT-NEXT:%BB1:
// OPT-NEXT:       ReturnInst %0: object
// OPT-NEXT:%BB2:
// OPT-NEXT:       ReturnInst %0: object
// OPT-NEXT:function_end

// OPT:function use(o: any): any
// OPT-NEXT:%BB0:
// OPT-NEXT:  %0 = LoadParamInst (:any) %o: any
// OPT-NEXT:  %1 = HasStaticShapeInst (:boolean) %0: any, {method: object |closure:methodFunc}: null [ann#0]
// OPT-NEXT:       CondBranchInst %1: boolean, %BB2, %BB1
// OPT-NEXT:%BB1:
// OPT-NEXT:  %3 = LoadPropertyInst (:any) %0: any, "method": string
// OPT-NEXT:  %4 = CallInst (:any) %3: any, empty: any, false: boolean, empty: any, undefined: undefined, %0: any
// OPT-NEXT:       ReturnInst %4: any
// OPT-NEXT:%BB2:
// OPT-NEXT:       ReturnInst 42: number
// OPT-NEXT:function_end
