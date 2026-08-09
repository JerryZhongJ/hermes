/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %shermes -O0 -dump-ir -annotation-file=%S/closure-type-guard.json %s | %FileCheckOrRegen %s --check-prefix=IRGEN --match-full-lines
// RUN: %shermes -O0 -Xcustom-opt=insertguard -dump-ir -verify-ir -annotation-file=%S/closure-type-guard.json %s | %FileCheckOrRegen %s --check-prefix=INSERT --match-full-lines
// RUN: %shermes -O -dump-ir -annotation-file=%S/closure-type-guard.json %s | %FileCheckOrRegen %s --check-prefix=OPT --match-full-lines
// RUN: %shermes -O -exec -annotation-file=%S/closure-type-guard.json %s | %FileCheckOrRegen %s --check-prefix=EXEC --match-full-lines

// F is deliberately defined after guardedCall. IRGen must defer this guard
// until F's exact source range has been resolved, without moving its placement.
function guardedCall(fn) {
  return fn();
}

function make(value) {
  function F() {
    return value;
  }
  return F;
}

function G() {
  return 99;
}

var one = make(1);
var two = make(2);
print(guardedCall(one));
print(guardedCall(two));
print(guardedCall(G));

// The pending guard remains at the annotated parameter read, after parameter
// initialization has stored fn in its frame slot.

// InsertGuard branches at the exact-closure check. The successful continuation
// narrows fn with F's identity; the failed continuation retains the general call.

// The fast path uses the guarded closure's own environment while inlining F;
// the slow path still contains an indirect call for G.

// Auto-generated content below. Please do not modify manually.

// IRGEN:scope %VS0 []

// IRGEN:function global(): any
// IRGEN-NEXT:%BB0:
// IRGEN-NEXT:  %0 = CreateScopeInst (:environment) %VS0: any, empty: any
// IRGEN-NEXT:       DeclareGlobalVarInst "guardedCall": string
// IRGEN-NEXT:       DeclareGlobalVarInst "make": string
// IRGEN-NEXT:       DeclareGlobalVarInst "G": string
// IRGEN-NEXT:       DeclareGlobalVarInst "one": string
// IRGEN-NEXT:       DeclareGlobalVarInst "two": string
// IRGEN-NEXT:  %6 = CreateFunctionInst (:object) %0: environment, %VS0: any, %guardedCall(): functionCode
// IRGEN-NEXT:       StorePropertyLooseInst %6: object, globalObject: object, "guardedCall": string
// IRGEN-NEXT:  %8 = CreateFunctionInst (:object) %0: environment, %VS0: any, %make(): functionCode
// IRGEN-NEXT:       StorePropertyLooseInst %8: object, globalObject: object, "make": string
// IRGEN-NEXT:  %10 = CreateFunctionInst (:object) %0: environment, %VS0: any, %G(): functionCode
// IRGEN-NEXT:        StorePropertyLooseInst %10: object, globalObject: object, "G": string
// IRGEN-NEXT:  %12 = AllocStackInst (:any) $?anon_0_ret: any
// IRGEN-NEXT:        StoreStackInst undefined: undefined, %12: any
// IRGEN-NEXT:  %14 = LoadPropertyInst (:any) globalObject: object, "make": string
// IRGEN-NEXT:  %15 = CallInst (:any) %14: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, 1: number
// IRGEN-NEXT:        StorePropertyLooseInst %15: any, globalObject: object, "one": string
// IRGEN-NEXT:  %17 = LoadPropertyInst (:any) globalObject: object, "make": string
// IRGEN-NEXT:  %18 = CallInst (:any) %17: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, 2: number
// IRGEN-NEXT:        StorePropertyLooseInst %18: any, globalObject: object, "two": string
// IRGEN-NEXT:  %20 = TryLoadGlobalPropertyInst (:any) globalObject: object, "print": string
// IRGEN-NEXT:  %21 = LoadPropertyInst (:any) globalObject: object, "guardedCall": string
// IRGEN-NEXT:  %22 = LoadPropertyInst (:any) globalObject: object, "one": string
// IRGEN-NEXT:  %23 = CallInst (:any) %21: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, %22: any
// IRGEN-NEXT:  %24 = CallInst (:any) %20: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, %23: any
// IRGEN-NEXT:        StoreStackInst %24: any, %12: any
// IRGEN-NEXT:  %26 = TryLoadGlobalPropertyInst (:any) globalObject: object, "print": string
// IRGEN-NEXT:  %27 = LoadPropertyInst (:any) globalObject: object, "guardedCall": string
// IRGEN-NEXT:  %28 = LoadPropertyInst (:any) globalObject: object, "two": string
// IRGEN-NEXT:  %29 = CallInst (:any) %27: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, %28: any
// IRGEN-NEXT:  %30 = CallInst (:any) %26: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, %29: any
// IRGEN-NEXT:        StoreStackInst %30: any, %12: any
// IRGEN-NEXT:  %32 = TryLoadGlobalPropertyInst (:any) globalObject: object, "print": string
// IRGEN-NEXT:  %33 = LoadPropertyInst (:any) globalObject: object, "guardedCall": string
// IRGEN-NEXT:  %34 = LoadPropertyInst (:any) globalObject: object, "G": string
// IRGEN-NEXT:  %35 = CallInst (:any) %33: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, %34: any
// IRGEN-NEXT:  %36 = CallInst (:any) %32: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, %35: any
// IRGEN-NEXT:        StoreStackInst %36: any, %12: any
// IRGEN-NEXT:  %38 = LoadStackInst (:any) %12: any
// IRGEN-NEXT:        ReturnInst %38: any
// IRGEN-NEXT:function_end

// IRGEN:scope %VS1 [fn: any]

// IRGEN:function guardedCall(fn: any): any
// IRGEN-NEXT:%BB0:
// IRGEN-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// IRGEN-NEXT:  %1 = CreateScopeInst (:environment) %VS1: any, %0: environment
// IRGEN-NEXT:  %2 = LoadParamInst (:any) %fn: any
// IRGEN-NEXT:       StoreFrameInst %1: environment, %2: any, [%VS1.fn]: any
// IRGEN-NEXT:  %4 = LoadFrameInst (:any) %1: environment, [%VS1.fn]: any
// IRGEN-NEXT:  %5 = HasClosureTargetInst (:boolean) %4: any, %F(): functionCode, empty: any [ann#0] [closure:F]
// IRGEN-NEXT:  %6 = CallInst (:any) %4: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined
// IRGEN-NEXT:       ReturnInst %6: any
// IRGEN-NEXT:function_end

// IRGEN:scope %VS2 [value: any, F: any]

// IRGEN:function make(value: any): any
// IRGEN-NEXT:%BB0:
// IRGEN-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// IRGEN-NEXT:  %1 = CreateScopeInst (:environment) %VS2: any, %0: environment
// IRGEN-NEXT:  %2 = LoadParamInst (:any) %value: any
// IRGEN-NEXT:       StoreFrameInst %1: environment, %2: any, [%VS2.value]: any
// IRGEN-NEXT:  %4 = CreateFunctionInst (:object) %1: environment, %VS2: any, %F(): functionCode
// IRGEN-NEXT:       StoreFrameInst %1: environment, %4: object, [%VS2.F]: any
// IRGEN-NEXT:  %6 = LoadFrameInst (:any) %1: environment, [%VS2.F]: any
// IRGEN-NEXT:       ReturnInst %6: any
// IRGEN-NEXT:function_end

// IRGEN:scope %VS3 []

// IRGEN:function G(): any
// IRGEN-NEXT:%BB0:
// IRGEN-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// IRGEN-NEXT:  %1 = CreateScopeInst (:environment) %VS3: any, %0: environment
// IRGEN-NEXT:       ReturnInst 99: number
// IRGEN-NEXT:function_end

// IRGEN:scope %VS4 []

// IRGEN:function F(): any
// IRGEN-NEXT:%BB0:
// IRGEN-NEXT:  %0 = GetParentScopeInst (:environment) %VS2: any, %parentScope: environment
// IRGEN-NEXT:  %1 = CreateScopeInst (:environment) %VS4: any, %0: environment
// IRGEN-NEXT:  %2 = LoadFrameInst (:any) %0: environment, [%VS2.value]: any
// IRGEN-NEXT:       ReturnInst %2: any
// IRGEN-NEXT:function_end

// INSERT:scope %VS0 []

// INSERT:function global(): any
// INSERT-NEXT:%BB0:
// INSERT-NEXT:  %0 = CreateScopeInst (:environment) %VS0: any, empty: any
// INSERT-NEXT:       DeclareGlobalVarInst "guardedCall": string
// INSERT-NEXT:       DeclareGlobalVarInst "make": string
// INSERT-NEXT:       DeclareGlobalVarInst "G": string
// INSERT-NEXT:       DeclareGlobalVarInst "one": string
// INSERT-NEXT:       DeclareGlobalVarInst "two": string
// INSERT-NEXT:  %6 = CreateFunctionInst (:object) %0: environment, %VS0: any, %guardedCall(): functionCode
// INSERT-NEXT:       StorePropertyLooseInst %6: object, globalObject: object, "guardedCall": string
// INSERT-NEXT:  %8 = CreateFunctionInst (:object) %0: environment, %VS0: any, %make(): functionCode
// INSERT-NEXT:       StorePropertyLooseInst %8: object, globalObject: object, "make": string
// INSERT-NEXT:  %10 = CreateFunctionInst (:object) %0: environment, %VS0: any, %G(): functionCode
// INSERT-NEXT:        StorePropertyLooseInst %10: object, globalObject: object, "G": string
// INSERT-NEXT:  %12 = AllocStackInst (:any) $?anon_0_ret: any
// INSERT-NEXT:        StoreStackInst undefined: undefined, %12: any
// INSERT-NEXT:  %14 = LoadPropertyInst (:any) globalObject: object, "make": string
// INSERT-NEXT:  %15 = CallInst (:any) %14: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, 1: number
// INSERT-NEXT:        StorePropertyLooseInst %15: any, globalObject: object, "one": string
// INSERT-NEXT:  %17 = LoadPropertyInst (:any) globalObject: object, "make": string
// INSERT-NEXT:  %18 = CallInst (:any) %17: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, 2: number
// INSERT-NEXT:        StorePropertyLooseInst %18: any, globalObject: object, "two": string
// INSERT-NEXT:  %20 = TryLoadGlobalPropertyInst (:any) globalObject: object, "print": string
// INSERT-NEXT:  %21 = LoadPropertyInst (:any) globalObject: object, "guardedCall": string
// INSERT-NEXT:  %22 = LoadPropertyInst (:any) globalObject: object, "one": string
// INSERT-NEXT:  %23 = CallInst (:any) %21: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, %22: any
// INSERT-NEXT:  %24 = CallInst (:any) %20: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, %23: any
// INSERT-NEXT:        StoreStackInst %24: any, %12: any
// INSERT-NEXT:  %26 = TryLoadGlobalPropertyInst (:any) globalObject: object, "print": string
// INSERT-NEXT:  %27 = LoadPropertyInst (:any) globalObject: object, "guardedCall": string
// INSERT-NEXT:  %28 = LoadPropertyInst (:any) globalObject: object, "two": string
// INSERT-NEXT:  %29 = CallInst (:any) %27: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, %28: any
// INSERT-NEXT:  %30 = CallInst (:any) %26: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, %29: any
// INSERT-NEXT:        StoreStackInst %30: any, %12: any
// INSERT-NEXT:  %32 = TryLoadGlobalPropertyInst (:any) globalObject: object, "print": string
// INSERT-NEXT:  %33 = LoadPropertyInst (:any) globalObject: object, "guardedCall": string
// INSERT-NEXT:  %34 = LoadPropertyInst (:any) globalObject: object, "G": string
// INSERT-NEXT:  %35 = CallInst (:any) %33: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, %34: any
// INSERT-NEXT:  %36 = CallInst (:any) %32: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, %35: any
// INSERT-NEXT:        StoreStackInst %36: any, %12: any
// INSERT-NEXT:  %38 = LoadStackInst (:any) %12: any
// INSERT-NEXT:        ReturnInst %38: any
// INSERT-NEXT:function_end

// INSERT:scope %VS1 [fn: any]

// INSERT:function guardedCall(fn: any): any
// INSERT-NEXT:%BB0:
// INSERT-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// INSERT-NEXT:  %1 = CreateScopeInst (:environment) %VS1: any, %0: environment
// INSERT-NEXT:  %2 = LoadParamInst (:any) %fn: any
// INSERT-NEXT:       StoreFrameInst %1: environment, %2: any, [%VS1.fn]: any
// INSERT-NEXT:  %4 = LoadFrameInst (:any) %1: environment, [%VS1.fn]: any
// INSERT-NEXT:  %5 = HasClosureTargetInst (:boolean) %4: any, %F(): functionCode, empty: any [ann#0] [closure:F]
// INSERT-NEXT:       CondBranchInst %5: boolean, %BB1, %BB2
// INSERT-NEXT:%BB1:
// INSERT-NEXT:  %7 = UnionNarrowTrustedInst (:object) %4: any [closure:F]
// INSERT-NEXT:  %8 = CallInst (:any) %7: object, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined
// INSERT-NEXT:       ReturnInst %8: any
// INSERT-NEXT:%BB2:
// INSERT-NEXT:  %10 = CallInst (:any) %4: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined
// INSERT-NEXT:        ReturnInst %10: any
// INSERT-NEXT:function_end

// INSERT:scope %VS2 [value: any, F: any]

// INSERT:function make(value: any): any
// INSERT-NEXT:%BB0:
// INSERT-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// INSERT-NEXT:  %1 = CreateScopeInst (:environment) %VS2: any, %0: environment
// INSERT-NEXT:  %2 = LoadParamInst (:any) %value: any
// INSERT-NEXT:       StoreFrameInst %1: environment, %2: any, [%VS2.value]: any
// INSERT-NEXT:  %4 = CreateFunctionInst (:object) %1: environment, %VS2: any, %F(): functionCode
// INSERT-NEXT:       StoreFrameInst %1: environment, %4: object, [%VS2.F]: any
// INSERT-NEXT:  %6 = LoadFrameInst (:any) %1: environment, [%VS2.F]: any
// INSERT-NEXT:       ReturnInst %6: any
// INSERT-NEXT:function_end

// INSERT:scope %VS3 []

// INSERT:function G(): any
// INSERT-NEXT:%BB0:
// INSERT-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// INSERT-NEXT:  %1 = CreateScopeInst (:environment) %VS3: any, %0: environment
// INSERT-NEXT:       ReturnInst 99: number
// INSERT-NEXT:function_end

// INSERT:scope %VS4 []

// INSERT:function F(): any
// INSERT-NEXT:%BB0:
// INSERT-NEXT:  %0 = GetParentScopeInst (:environment) %VS2: any, %parentScope: environment
// INSERT-NEXT:  %1 = CreateScopeInst (:environment) %VS4: any, %0: environment
// INSERT-NEXT:  %2 = LoadFrameInst (:any) %0: environment, [%VS2.value]: any
// INSERT-NEXT:       ReturnInst %2: any
// INSERT-NEXT:function_end

// OPT:function global(): any
// OPT-NEXT:%BB0:
// OPT-NEXT:       DeclareGlobalVarInst "guardedCall": string
// OPT-NEXT:       DeclareGlobalVarInst "make": string
// OPT-NEXT:       DeclareGlobalVarInst "G": string
// OPT-NEXT:       DeclareGlobalVarInst "one": string
// OPT-NEXT:       DeclareGlobalVarInst "two": string
// OPT-NEXT:  %5 = CreateFunctionInst (:object) empty: any, empty: any, %guardedCall(): functionCode
// OPT-NEXT:       StorePropertyLooseInst %5: object, globalObject: object, "guardedCall": string
// OPT-NEXT:  %7 = CreateFunctionInst (:object) empty: any, empty: any, %make(): functionCode
// OPT-NEXT:       StorePropertyLooseInst %7: object, globalObject: object, "make": string
// OPT-NEXT:  %9 = CreateFunctionInst (:object) empty: any, empty: any, %G(): functionCode
// OPT-NEXT:        StorePropertyLooseInst %9: object, globalObject: object, "G": string
// OPT-NEXT:  %11 = LoadPropertyInst (:any) globalObject: object, "make": string
// OPT-NEXT:  %12 = CallInst (:any) %11: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, 1: number
// OPT-NEXT:        StorePropertyLooseInst %12: any, globalObject: object, "one": string
// OPT-NEXT:  %14 = LoadPropertyInst (:any) globalObject: object, "make": string
// OPT-NEXT:  %15 = CallInst (:any) %14: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, 2: number
// OPT-NEXT:        StorePropertyLooseInst %15: any, globalObject: object, "two": string
// OPT-NEXT:  %17 = TryLoadGlobalPropertyInst (:any) globalObject: object, "print": string
// OPT-NEXT:  %18 = LoadPropertyInst (:any) globalObject: object, "guardedCall": string
// OPT-NEXT:  %19 = LoadPropertyInst (:any) globalObject: object, "one": string
// OPT-NEXT:  %20 = CallInst (:any) %18: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, %19: any
// OPT-NEXT:  %21 = CallInst (:any) %17: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, %20: any
// OPT-NEXT:  %22 = TryLoadGlobalPropertyInst (:any) globalObject: object, "print": string
// OPT-NEXT:  %23 = LoadPropertyInst (:any) globalObject: object, "guardedCall": string
// OPT-NEXT:  %24 = LoadPropertyInst (:any) globalObject: object, "two": string
// OPT-NEXT:  %25 = CallInst (:any) %23: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, %24: any
// OPT-NEXT:  %26 = CallInst (:any) %22: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, %25: any
// OPT-NEXT:  %27 = TryLoadGlobalPropertyInst (:any) globalObject: object, "print": string
// OPT-NEXT:  %28 = LoadPropertyInst (:any) globalObject: object, "guardedCall": string
// OPT-NEXT:  %29 = LoadPropertyInst (:any) globalObject: object, "G": string
// OPT-NEXT:  %30 = CallInst (:any) %28: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, %29: any
// OPT-NEXT:  %31 = CallInst (:any) %27: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, %30: any
// OPT-NEXT:        ReturnInst %31: any
// OPT-NEXT:function_end

// OPT:scope %VS0 [value: any]

// OPT:function guardedCall(fn: any): any
// OPT-NEXT:%BB0:
// OPT-NEXT:  %0 = LoadParamInst (:any) %fn: any
// OPT-NEXT:  %1 = HasClosureTargetInst (:boolean) %0: any, %F(): functionCode, empty: any [ann#0] [closure:F]
// OPT-NEXT:       CondBranchInst %1: boolean, %BB1, %BB2
// OPT-NEXT:%BB1:
// OPT-NEXT:  %3 = UnionNarrowTrustedInst (:object) %0: any [closure:F]
// OPT-NEXT:  %4 = GetClosureScopeInst (:environment) %VS0: any, %F(): functionCode, %3: object
// OPT-NEXT:  %5 = LoadFrameInst (:any) %4: environment, [%VS0.value]: any
// OPT-NEXT:       ReturnInst %5: any
// OPT-NEXT:%BB2:
// OPT-NEXT:  %7 = CallInst (:any) %0: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined
// OPT-NEXT:       ReturnInst %7: any
// OPT-NEXT:function_end

// OPT:function make(value: any): object
// OPT-NEXT:%BB0:
// OPT-NEXT:  %0 = CreateScopeInst (:environment) %VS0: any, empty: any
// OPT-NEXT:  %1 = LoadParamInst (:any) %value: any
// OPT-NEXT:       StoreFrameInst %0: environment, %1: any, [%VS0.value]: any
// OPT-NEXT:  %3 = CreateFunctionInst (:object) %0: environment, %VS0: any, %F(): functionCode
// OPT-NEXT:       ReturnInst %3: object
// OPT-NEXT:function_end

// OPT:function G(): number
// OPT-NEXT:%BB0:
// OPT-NEXT:       ReturnInst 99: number
// OPT-NEXT:function_end

// OPT:function F(): any
// OPT-NEXT:%BB0:
// OPT-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// OPT-NEXT:  %1 = LoadFrameInst (:any) %0: environment, [%VS0.value]: any
// OPT-NEXT:       ReturnInst %1: any
// OPT-NEXT:function_end

// EXEC:1
// EXEC-NEXT:2
// EXEC-NEXT:99
