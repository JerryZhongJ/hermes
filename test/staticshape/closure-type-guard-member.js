/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %shermes -O0 -dump-ir -annotation-file=%S/closure-type-guard-member.json %s | %FileCheckOrRegen %s --check-prefix=IRGEN --match-full-lines
// RUN: %shermes -O -dump-ir -annotation-file=%S/closure-type-guard-member.json %s | %FileCheckOrRegen %s --check-prefix=OPT --match-full-lines
// RUN: %shermes -O -exec -annotation-file=%S/closure-type-guard-member.json %s | %FileCheckOrRegen %s --check-prefix=EXEC --match-full-lines

// A closure-target guard on a member-expression callee (o.m) must still emit
// and inline. genCall bypasses genExpression for member callees, so the guard
// is applied directly on the loaded callee value in the member-callee path.

function F() {
  return 42;
}

function call(o) {
  return o.m();
}

var obj = {m: F};
print(call(obj));

// Auto-generated content below. Please do not modify manually.

// IRGEN:scope %VS0 []

// IRGEN:function global(): any
// IRGEN-NEXT:%BB0:
// IRGEN-NEXT:  %0 = CreateScopeInst (:environment) %VS0: any, empty: any
// IRGEN-NEXT:       DeclareGlobalVarInst "F": string
// IRGEN-NEXT:       DeclareGlobalVarInst "call": string
// IRGEN-NEXT:       DeclareGlobalVarInst "obj": string
// IRGEN-NEXT:  %4 = CreateFunctionInst (:object) %0: environment, %VS0: any, %F(): functionCode
// IRGEN-NEXT:       StorePropertyLooseInst %4: object, globalObject: object, "F": string
// IRGEN-NEXT:  %6 = CreateFunctionInst (:object) %0: environment, %VS0: any, %call(): functionCode
// IRGEN-NEXT:       StorePropertyLooseInst %6: object, globalObject: object, "call": string
// IRGEN-NEXT:  %8 = AllocStackInst (:any) $?anon_0_ret: any
// IRGEN-NEXT:       StoreStackInst undefined: undefined, %8: any
// IRGEN-NEXT:  %10 = AllocObjectLiteralInst (:object) empty: any
// IRGEN-NEXT:  %11 = LoadPropertyInst (:any) globalObject: object, "F": string
// IRGEN-NEXT:        DefineOwnPropertyInst %11: any, %10: object, "m": string, true: boolean
// IRGEN-NEXT:        StorePropertyLooseInst %10: object, globalObject: object, "obj": string
// IRGEN-NEXT:  %14 = TryLoadGlobalPropertyInst (:any) globalObject: object, "print": string
// IRGEN-NEXT:  %15 = LoadPropertyInst (:any) globalObject: object, "call": string
// IRGEN-NEXT:  %16 = LoadPropertyInst (:any) globalObject: object, "obj": string
// IRGEN-NEXT:  %17 = CallInst (:any) %15: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, %16: any
// IRGEN-NEXT:  %18 = CallInst (:any) %14: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, %17: any
// IRGEN-NEXT:        StoreStackInst %18: any, %8: any
// IRGEN-NEXT:  %20 = LoadStackInst (:any) %8: any
// IRGEN-NEXT:        ReturnInst %20: any
// IRGEN-NEXT:function_end

// IRGEN:scope %VS1 []

// IRGEN:function F(): any
// IRGEN-NEXT:%BB0:
// IRGEN-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// IRGEN-NEXT:  %1 = CreateScopeInst (:environment) %VS1: any, %0: environment
// IRGEN-NEXT:       ReturnInst 42: number
// IRGEN-NEXT:function_end

// IRGEN:scope %VS2 [o: any]

// IRGEN:function call(o: any): any
// IRGEN-NEXT:%BB0:
// IRGEN-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// IRGEN-NEXT:  %1 = CreateScopeInst (:environment) %VS2: any, %0: environment
// IRGEN-NEXT:  %2 = LoadParamInst (:any) %o: any
// IRGEN-NEXT:       StoreFrameInst %1: environment, %2: any, [%VS2.o]: any
// IRGEN-NEXT:  %4 = LoadFrameInst (:any) %1: environment, [%VS2.o]: any
// IRGEN-NEXT:  %5 = LoadPropertyInst (:any) %4: any, "m": string
// IRGEN-NEXT:  %6 = HasClosureTargetInst (:boolean) %5: any, %F(): functionCode, empty: any [ann#0] [closure:F]
// IRGEN-NEXT:  %7 = CallInst (:any) %5: any, empty: any, false: boolean, empty: any, undefined: undefined, %4: any
// IRGEN-NEXT:       ReturnInst %7: any
// IRGEN-NEXT:function_end

// OPT:function global(): any
// OPT-NEXT:%BB0:
// OPT-NEXT:       DeclareGlobalVarInst "F": string
// OPT-NEXT:       DeclareGlobalVarInst "call": string
// OPT-NEXT:       DeclareGlobalVarInst "obj": string
// OPT-NEXT:  %3 = CreateFunctionInst (:object) empty: any, empty: any, %F(): functionCode
// OPT-NEXT:       StorePropertyLooseInst %3: object, globalObject: object, "F": string
// OPT-NEXT:  %5 = CreateFunctionInst (:object) empty: any, empty: any, %call(): functionCode
// OPT-NEXT:       StorePropertyLooseInst %5: object, globalObject: object, "call": string
// OPT-NEXT:  %7 = AllocObjectLiteralInst (:object) empty: any, "m": string, null: null
// OPT-NEXT:  %8 = LoadPropertyInst (:any) globalObject: object, "F": string
// OPT-NEXT:       PrStoreInst %8: any, %7: object, 0: number, "m": string
// OPT-NEXT:        StorePropertyLooseInst %7: object, globalObject: object, "obj": string
// OPT-NEXT:  %11 = TryLoadGlobalPropertyInst (:any) globalObject: object, "print": string
// OPT-NEXT:  %12 = LoadPropertyInst (:any) globalObject: object, "call": string
// OPT-NEXT:  %13 = LoadPropertyInst (:any) globalObject: object, "obj": string
// OPT-NEXT:        BranchIfBuiltinInst [HermesBuiltin.functionPrototypeCall]: number, %12: any, %BB2, %BB3
// OPT-NEXT:%BB1:
// OPT-NEXT:  %15 = PhiInst (:any) %18: any, %BB2, %20: any, %BB3
// OPT-NEXT:  %16 = CallInst (:any) %11: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, %15: any
// OPT-NEXT:        ReturnInst %16: any
// OPT-NEXT:%BB2:
// OPT-NEXT:  %18 = CallInst (:any) undefined: undefined, empty: any, false: boolean, empty: any, undefined: undefined, %13: any
// OPT-NEXT:        BranchInst %BB1
// OPT-NEXT:%BB3:
// OPT-NEXT:  %20 = CallInst (:any) %12: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, %13: any
// OPT-NEXT:        BranchInst %BB1
// OPT-NEXT:function_end

// OPT:function F(): number
// OPT-NEXT:%BB0:
// OPT-NEXT:       ReturnInst 42: number
// OPT-NEXT:function_end

// OPT:function call(o: any): any
// OPT-NEXT:%BB0:
// OPT-NEXT:  %0 = LoadParamInst (:any) %o: any
// OPT-NEXT:  %1 = LoadPropertyInst (:any) %0: any, "m": string
// OPT-NEXT:  %2 = HasClosureTargetInst (:boolean) %1: any, %F(): functionCode, empty: any [ann#0] [closure:F]
// OPT-NEXT:       CondBranchInst %2: boolean, %BB2, %BB1
// OPT-NEXT:%BB1:
// OPT-NEXT:  %4 = CallInst (:any) %1: any, empty: any, false: boolean, empty: any, undefined: undefined, %0: any
// OPT-NEXT:       ReturnInst %4: any
// OPT-NEXT:%BB2:
// OPT-NEXT:       ReturnInst 42: number
// OPT-NEXT:function_end

// EXEC:42
