/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %shermes -O0 -Xcustom-opt=functionanalysis -dump-ir -verify-ir -annotation-file=%S/closure-target-fold.json %s | %FileCheckOrRegen %s --check-prefix=ANALYSIS --match-full-lines
// RUN: %shermes -O0 -Xcustom-opt=functionanalysis,instsimplify -dump-ir -verify-ir -annotation-file=%S/closure-target-fold.json %s | %FileCheckOrRegen %s --check-prefix=SIMPLIFY --match-full-lines
// RUN: %shermes -O0 -Xcustom-opt=functionanalysis,insertguard,instsimplify,simplifycfg,dce -dump-ir -verify-ir -annotation-file=%S/closure-target-fold.json %s | %FileCheckOrRegen %s --check-prefix=BRANCH --match-full-lines

function Expected() {
  return 1;
}

function same() {
  function SameTarget() {
    return 2;
  }
  return SameTarget();
}

function different() {
  function DifferentTarget() {
    return 3;
  }
  return DifferentTarget();
}

function maybeNonClosure(flag) {
  function MaybeTarget() {
    return 4;
  }
  var fn = MaybeTarget;
  if (flag) {
    fn = 0;
  }
  return fn();
}

// Auto-generated content below. Please do not modify manually.

// ANALYSIS:scope %VS0 []

// ANALYSIS:function global(): any
// ANALYSIS-NEXT:%BB0:
// ANALYSIS-NEXT:  %0 = CreateScopeInst (:environment) %VS0: any, empty: any
// ANALYSIS-NEXT:       DeclareGlobalVarInst "Expected": string
// ANALYSIS-NEXT:       DeclareGlobalVarInst "same": string
// ANALYSIS-NEXT:       DeclareGlobalVarInst "different": string
// ANALYSIS-NEXT:       DeclareGlobalVarInst "maybeNonClosure": string
// ANALYSIS-NEXT:  %5 = CreateFunctionInst (:object) %0: environment, %VS0: any, %Expected(): functionCode
// ANALYSIS-NEXT:       StorePropertyLooseInst %5: object, globalObject: object, "Expected": string
// ANALYSIS-NEXT:  %7 = CreateFunctionInst (:object) %0: environment, %VS0: any, %same(): functionCode
// ANALYSIS-NEXT:       StorePropertyLooseInst %7: object, globalObject: object, "same": string
// ANALYSIS-NEXT:  %9 = CreateFunctionInst (:object) %0: environment, %VS0: any, %different(): functionCode
// ANALYSIS-NEXT:        StorePropertyLooseInst %9: object, globalObject: object, "different": string
// ANALYSIS-NEXT:  %11 = CreateFunctionInst (:object) %0: environment, %VS0: any, %maybeNonClosure(): functionCode
// ANALYSIS-NEXT:        StorePropertyLooseInst %11: object, globalObject: object, "maybeNonClosure": string
// ANALYSIS-NEXT:  %13 = AllocStackInst (:any) $?anon_0_ret: any
// ANALYSIS-NEXT:        StoreStackInst undefined: undefined, %13: any
// ANALYSIS-NEXT:  %15 = LoadStackInst (:any) %13: any
// ANALYSIS-NEXT:        ReturnInst %15: any
// ANALYSIS-NEXT:function_end

// ANALYSIS:scope %VS1 []

// ANALYSIS:function Expected(): any
// ANALYSIS-NEXT:%BB0:
// ANALYSIS-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// ANALYSIS-NEXT:  %1 = CreateScopeInst (:environment) %VS1: any, %0: environment
// ANALYSIS-NEXT:       ReturnInst 1: number
// ANALYSIS-NEXT:function_end

// ANALYSIS:scope %VS2 [SameTarget: any]

// ANALYSIS:function same(): any
// ANALYSIS-NEXT:%BB0:
// ANALYSIS-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// ANALYSIS-NEXT:  %1 = CreateScopeInst (:environment) %VS2: any, %0: environment
// ANALYSIS-NEXT:  %2 = CreateFunctionInst (:object) %1: environment, %VS2: any, %SameTarget(): functionCode
// ANALYSIS-NEXT:       StoreFrameInst %1: environment, %2: object, [%VS2.SameTarget]: any
// ANALYSIS-NEXT:  %4 = LoadFrameInst (:any) %1: environment, [%VS2.SameTarget]: any
// ANALYSIS-NEXT:  %5 = HasClosureTargetInst (:boolean) %4: any, %SameTarget(): functionCode, %SameTarget(): functionCode [ann#0] [closure:SameTarget]
// ANALYSIS-NEXT:  %6 = CallInst (:any) %4: any, %SameTarget(): functionCode, true: boolean, %1: environment, undefined: undefined, undefined: undefined
// ANALYSIS-NEXT:       ReturnInst %6: any
// ANALYSIS-NEXT:function_end

// ANALYSIS:scope %VS3 [DifferentTarget: any]

// ANALYSIS:function different(): any
// ANALYSIS-NEXT:%BB0:
// ANALYSIS-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// ANALYSIS-NEXT:  %1 = CreateScopeInst (:environment) %VS3: any, %0: environment
// ANALYSIS-NEXT:  %2 = CreateFunctionInst (:object) %1: environment, %VS3: any, %DifferentTarget(): functionCode
// ANALYSIS-NEXT:       StoreFrameInst %1: environment, %2: object, [%VS3.DifferentTarget]: any
// ANALYSIS-NEXT:  %4 = LoadFrameInst (:any) %1: environment, [%VS3.DifferentTarget]: any
// ANALYSIS-NEXT:  %5 = HasClosureTargetInst (:boolean) %4: any, %Expected(): functionCode, %DifferentTarget(): functionCode [ann#1] [closure:Expected]
// ANALYSIS-NEXT:  %6 = CallInst (:any) %4: any, %DifferentTarget(): functionCode, true: boolean, %1: environment, undefined: undefined, undefined: undefined
// ANALYSIS-NEXT:       ReturnInst %6: any
// ANALYSIS-NEXT:function_end

// ANALYSIS:scope %VS4 [flag: any, MaybeTarget: any, fn: any]

// ANALYSIS:function maybeNonClosure(flag: any): any
// ANALYSIS-NEXT:%BB0:
// ANALYSIS-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// ANALYSIS-NEXT:  %1 = CreateScopeInst (:environment) %VS4: any, %0: environment
// ANALYSIS-NEXT:  %2 = LoadParamInst (:any) %flag: any
// ANALYSIS-NEXT:       StoreFrameInst %1: environment, %2: any, [%VS4.flag]: any
// ANALYSIS-NEXT:       StoreFrameInst %1: environment, undefined: undefined, [%VS4.fn]: any
// ANALYSIS-NEXT:  %5 = CreateFunctionInst (:object) %1: environment, %VS4: any, %MaybeTarget(): functionCode
// ANALYSIS-NEXT:       StoreFrameInst %1: environment, %5: object, [%VS4.MaybeTarget]: any
// ANALYSIS-NEXT:  %7 = LoadFrameInst (:any) %1: environment, [%VS4.MaybeTarget]: any
// ANALYSIS-NEXT:       StoreFrameInst %1: environment, %7: any, [%VS4.fn]: any
// ANALYSIS-NEXT:  %9 = LoadFrameInst (:any) %1: environment, [%VS4.flag]: any
// ANALYSIS-NEXT:        CondBranchInst %9: any, %BB1, %BB2
// ANALYSIS-NEXT:%BB1:
// ANALYSIS-NEXT:        StoreFrameInst %1: environment, 0: number, [%VS4.fn]: any
// ANALYSIS-NEXT:        BranchInst %BB3
// ANALYSIS-NEXT:%BB2:
// ANALYSIS-NEXT:        BranchInst %BB3
// ANALYSIS-NEXT:%BB3:
// ANALYSIS-NEXT:  %14 = LoadFrameInst (:any) %1: environment, [%VS4.fn]: any
// ANALYSIS-NEXT:  %15 = HasClosureTargetInst (:boolean) %14: any, %MaybeTarget(): functionCode, empty: any [ann#2] [closure:MaybeTarget]
// ANALYSIS-NEXT:  %16 = CallInst (:any) %14: any, %MaybeTarget(): functionCode, false: boolean, %1: environment, undefined: undefined, undefined: undefined
// ANALYSIS-NEXT:        ReturnInst %16: any
// ANALYSIS-NEXT:function_end

// ANALYSIS:scope %VS5 []

// ANALYSIS:function SameTarget(): any [allCallsitesKnownInStrictMode]
// ANALYSIS-NEXT:%BB0:
// ANALYSIS-NEXT:  %0 = GetParentScopeInst (:environment) %VS2: any, %parentScope: environment
// ANALYSIS-NEXT:  %1 = CreateScopeInst (:environment) %VS5: any, %0: environment
// ANALYSIS-NEXT:       ReturnInst 2: number
// ANALYSIS-NEXT:function_end

// ANALYSIS:scope %VS6 []

// ANALYSIS:function DifferentTarget(): any [allCallsitesKnownInStrictMode]
// ANALYSIS-NEXT:%BB0:
// ANALYSIS-NEXT:  %0 = GetParentScopeInst (:environment) %VS3: any, %parentScope: environment
// ANALYSIS-NEXT:  %1 = CreateScopeInst (:environment) %VS6: any, %0: environment
// ANALYSIS-NEXT:       ReturnInst 3: number
// ANALYSIS-NEXT:function_end

// ANALYSIS:scope %VS7 []

// ANALYSIS:function MaybeTarget(): any [allCallsitesKnownInStrictMode]
// ANALYSIS-NEXT:%BB0:
// ANALYSIS-NEXT:  %0 = GetParentScopeInst (:environment) %VS4: any, %parentScope: environment
// ANALYSIS-NEXT:  %1 = CreateScopeInst (:environment) %VS7: any, %0: environment
// ANALYSIS-NEXT:       ReturnInst 4: number
// ANALYSIS-NEXT:function_end

// SIMPLIFY:scope %VS0 []

// SIMPLIFY:function global(): any
// SIMPLIFY-NEXT:%BB0:
// SIMPLIFY-NEXT:  %0 = CreateScopeInst (:environment) %VS0: any, empty: any
// SIMPLIFY-NEXT:       DeclareGlobalVarInst "Expected": string
// SIMPLIFY-NEXT:       DeclareGlobalVarInst "same": string
// SIMPLIFY-NEXT:       DeclareGlobalVarInst "different": string
// SIMPLIFY-NEXT:       DeclareGlobalVarInst "maybeNonClosure": string
// SIMPLIFY-NEXT:  %5 = CreateFunctionInst (:object) %0: environment, %VS0: any, %Expected(): functionCode
// SIMPLIFY-NEXT:       StorePropertyLooseInst %5: object, globalObject: object, "Expected": string
// SIMPLIFY-NEXT:  %7 = CreateFunctionInst (:object) %0: environment, %VS0: any, %same(): functionCode
// SIMPLIFY-NEXT:       StorePropertyLooseInst %7: object, globalObject: object, "same": string
// SIMPLIFY-NEXT:  %9 = CreateFunctionInst (:object) %0: environment, %VS0: any, %different(): functionCode
// SIMPLIFY-NEXT:        StorePropertyLooseInst %9: object, globalObject: object, "different": string
// SIMPLIFY-NEXT:  %11 = CreateFunctionInst (:object) %0: environment, %VS0: any, %maybeNonClosure(): functionCode
// SIMPLIFY-NEXT:        StorePropertyLooseInst %11: object, globalObject: object, "maybeNonClosure": string
// SIMPLIFY-NEXT:  %13 = AllocStackInst (:any) $?anon_0_ret: any
// SIMPLIFY-NEXT:        StoreStackInst undefined: undefined, %13: any
// SIMPLIFY-NEXT:  %15 = LoadStackInst (:any) %13: any
// SIMPLIFY-NEXT:        ReturnInst %15: any
// SIMPLIFY-NEXT:function_end

// SIMPLIFY:scope %VS1 []

// SIMPLIFY:function Expected(): any
// SIMPLIFY-NEXT:%BB0:
// SIMPLIFY-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// SIMPLIFY-NEXT:  %1 = CreateScopeInst (:environment) %VS1: any, %0: environment
// SIMPLIFY-NEXT:       ReturnInst 1: number
// SIMPLIFY-NEXT:function_end

// SIMPLIFY:scope %VS2 [SameTarget: any]

// SIMPLIFY:function same(): any
// SIMPLIFY-NEXT:%BB0:
// SIMPLIFY-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// SIMPLIFY-NEXT:  %1 = CreateScopeInst (:environment) %VS2: any, %0: environment
// SIMPLIFY-NEXT:  %2 = CreateFunctionInst (:object) %1: environment, %VS2: any, %SameTarget(): functionCode
// SIMPLIFY-NEXT:       StoreFrameInst %1: environment, %2: object, [%VS2.SameTarget]: any
// SIMPLIFY-NEXT:  %4 = LoadFrameInst (:any) %1: environment, [%VS2.SameTarget]: any
// SIMPLIFY-NEXT:  %5 = CallInst (:any) %4: any, %SameTarget(): functionCode, true: boolean, %1: environment, undefined: undefined, undefined: undefined
// SIMPLIFY-NEXT:       ReturnInst 2: number
// SIMPLIFY-NEXT:function_end

// SIMPLIFY:scope %VS3 [DifferentTarget: any]

// SIMPLIFY:function different(): any
// SIMPLIFY-NEXT:%BB0:
// SIMPLIFY-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// SIMPLIFY-NEXT:  %1 = CreateScopeInst (:environment) %VS3: any, %0: environment
// SIMPLIFY-NEXT:  %2 = CreateFunctionInst (:object) %1: environment, %VS3: any, %DifferentTarget(): functionCode
// SIMPLIFY-NEXT:       StoreFrameInst %1: environment, %2: object, [%VS3.DifferentTarget]: any
// SIMPLIFY-NEXT:  %4 = LoadFrameInst (:any) %1: environment, [%VS3.DifferentTarget]: any
// SIMPLIFY-NEXT:  %5 = CallInst (:any) %4: any, %DifferentTarget(): functionCode, true: boolean, %1: environment, undefined: undefined, undefined: undefined
// SIMPLIFY-NEXT:       ReturnInst 3: number
// SIMPLIFY-NEXT:function_end

// SIMPLIFY:scope %VS4 [flag: any, MaybeTarget: any, fn: any]

// SIMPLIFY:function maybeNonClosure(flag: any): any
// SIMPLIFY-NEXT:%BB0:
// SIMPLIFY-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// SIMPLIFY-NEXT:  %1 = CreateScopeInst (:environment) %VS4: any, %0: environment
// SIMPLIFY-NEXT:  %2 = LoadParamInst (:any) %flag: any
// SIMPLIFY-NEXT:       StoreFrameInst %1: environment, %2: any, [%VS4.flag]: any
// SIMPLIFY-NEXT:       StoreFrameInst %1: environment, undefined: undefined, [%VS4.fn]: any
// SIMPLIFY-NEXT:  %5 = CreateFunctionInst (:object) %1: environment, %VS4: any, %MaybeTarget(): functionCode
// SIMPLIFY-NEXT:       StoreFrameInst %1: environment, %5: object, [%VS4.MaybeTarget]: any
// SIMPLIFY-NEXT:  %7 = LoadFrameInst (:any) %1: environment, [%VS4.MaybeTarget]: any
// SIMPLIFY-NEXT:       StoreFrameInst %1: environment, %7: any, [%VS4.fn]: any
// SIMPLIFY-NEXT:  %9 = LoadFrameInst (:any) %1: environment, [%VS4.flag]: any
// SIMPLIFY-NEXT:        CondBranchInst %9: any, %BB1, %BB2
// SIMPLIFY-NEXT:%BB1:
// SIMPLIFY-NEXT:        StoreFrameInst %1: environment, 0: number, [%VS4.fn]: any
// SIMPLIFY-NEXT:        BranchInst %BB3
// SIMPLIFY-NEXT:%BB2:
// SIMPLIFY-NEXT:        BranchInst %BB3
// SIMPLIFY-NEXT:%BB3:
// SIMPLIFY-NEXT:  %14 = LoadFrameInst (:any) %1: environment, [%VS4.fn]: any
// SIMPLIFY-NEXT:  %15 = HasClosureTargetInst (:boolean) %14: any, %MaybeTarget(): functionCode, empty: any [ann#2] [closure:MaybeTarget]
// SIMPLIFY-NEXT:  %16 = CallInst (:any) %14: any, %MaybeTarget(): functionCode, false: boolean, %1: environment, undefined: undefined, undefined: undefined
// SIMPLIFY-NEXT:        ReturnInst 4: number
// SIMPLIFY-NEXT:function_end

// SIMPLIFY:scope %VS5 []

// SIMPLIFY:function SameTarget(): any [allCallsitesKnownInStrictMode]
// SIMPLIFY-NEXT:%BB0:
// SIMPLIFY-NEXT:  %0 = GetParentScopeInst (:environment) %VS2: any, %parentScope: environment
// SIMPLIFY-NEXT:  %1 = CreateScopeInst (:environment) %VS5: any, %0: environment
// SIMPLIFY-NEXT:       ReturnInst 2: number
// SIMPLIFY-NEXT:function_end

// SIMPLIFY:scope %VS6 []

// SIMPLIFY:function DifferentTarget(): any [allCallsitesKnownInStrictMode]
// SIMPLIFY-NEXT:%BB0:
// SIMPLIFY-NEXT:  %0 = GetParentScopeInst (:environment) %VS3: any, %parentScope: environment
// SIMPLIFY-NEXT:  %1 = CreateScopeInst (:environment) %VS6: any, %0: environment
// SIMPLIFY-NEXT:       ReturnInst 3: number
// SIMPLIFY-NEXT:function_end

// SIMPLIFY:scope %VS7 []

// SIMPLIFY:function MaybeTarget(): any [allCallsitesKnownInStrictMode]
// SIMPLIFY-NEXT:%BB0:
// SIMPLIFY-NEXT:  %0 = GetParentScopeInst (:environment) %VS4: any, %parentScope: environment
// SIMPLIFY-NEXT:  %1 = CreateScopeInst (:environment) %VS7: any, %0: environment
// SIMPLIFY-NEXT:       ReturnInst 4: number
// SIMPLIFY-NEXT:function_end

// BRANCH:scope %VS0 []

// BRANCH:function global(): any
// BRANCH-NEXT:%BB0:
// BRANCH-NEXT:  %0 = CreateScopeInst (:environment) %VS0: any, empty: any
// BRANCH-NEXT:       DeclareGlobalVarInst "Expected": string
// BRANCH-NEXT:       DeclareGlobalVarInst "same": string
// BRANCH-NEXT:       DeclareGlobalVarInst "different": string
// BRANCH-NEXT:       DeclareGlobalVarInst "maybeNonClosure": string
// BRANCH-NEXT:  %5 = CreateFunctionInst (:object) %0: environment, %VS0: any, %Expected(): functionCode
// BRANCH-NEXT:       StorePropertyLooseInst %5: object, globalObject: object, "Expected": string
// BRANCH-NEXT:  %7 = CreateFunctionInst (:object) %0: environment, %VS0: any, %same(): functionCode
// BRANCH-NEXT:       StorePropertyLooseInst %7: object, globalObject: object, "same": string
// BRANCH-NEXT:  %9 = CreateFunctionInst (:object) %0: environment, %VS0: any, %different(): functionCode
// BRANCH-NEXT:        StorePropertyLooseInst %9: object, globalObject: object, "different": string
// BRANCH-NEXT:  %11 = CreateFunctionInst (:object) %0: environment, %VS0: any, %maybeNonClosure(): functionCode
// BRANCH-NEXT:        StorePropertyLooseInst %11: object, globalObject: object, "maybeNonClosure": string
// BRANCH-NEXT:  %13 = AllocStackInst (:any) $?anon_0_ret: any
// BRANCH-NEXT:        StoreStackInst undefined: undefined, %13: any
// BRANCH-NEXT:  %15 = LoadStackInst (:any) %13: any
// BRANCH-NEXT:        ReturnInst %15: any
// BRANCH-NEXT:function_end

// BRANCH:function Expected(): any
// BRANCH-NEXT:%BB0:
// BRANCH-NEXT:       ReturnInst 1: number
// BRANCH-NEXT:function_end

// BRANCH:scope %VS1 [SameTarget: any]

// BRANCH:function same(): any
// BRANCH-NEXT:%BB0:
// BRANCH-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// BRANCH-NEXT:  %1 = CreateScopeInst (:environment) %VS1: any, %0: environment
// BRANCH-NEXT:  %2 = CreateFunctionInst (:object) %1: environment, %VS1: any, %SameTarget(): functionCode
// BRANCH-NEXT:       StoreFrameInst %1: environment, %2: object, [%VS1.SameTarget]: any
// BRANCH-NEXT:  %4 = LoadFrameInst (:any) %1: environment, [%VS1.SameTarget]: any
// BRANCH-NEXT:  %5 = UnionNarrowTrustedInst (:object) %4: any [closure:SameTarget]
// BRANCH-NEXT:  %6 = CallInst (:any) %5: object, %SameTarget(): functionCode, true: boolean, %1: environment, undefined: undefined, undefined: undefined
// BRANCH-NEXT:       ReturnInst 2: number
// BRANCH-NEXT:function_end

// BRANCH:scope %VS2 [DifferentTarget: any]

// BRANCH:function different(): any
// BRANCH-NEXT:%BB0:
// BRANCH-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// BRANCH-NEXT:  %1 = CreateScopeInst (:environment) %VS2: any, %0: environment
// BRANCH-NEXT:  %2 = CreateFunctionInst (:object) %1: environment, %VS2: any, %DifferentTarget(): functionCode
// BRANCH-NEXT:       StoreFrameInst %1: environment, %2: object, [%VS2.DifferentTarget]: any
// BRANCH-NEXT:  %4 = LoadFrameInst (:any) %1: environment, [%VS2.DifferentTarget]: any
// BRANCH-NEXT:  %5 = CallInst (:any) %4: any, %DifferentTarget(): functionCode, true: boolean, %1: environment, undefined: undefined, undefined: undefined
// BRANCH-NEXT:       ReturnInst 3: number
// BRANCH-NEXT:function_end

// BRANCH:scope %VS3 [flag: any, MaybeTarget: any, fn: any]

// BRANCH:function maybeNonClosure(flag: any): any
// BRANCH-NEXT:%BB0:
// BRANCH-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// BRANCH-NEXT:  %1 = CreateScopeInst (:environment) %VS3: any, %0: environment
// BRANCH-NEXT:  %2 = LoadParamInst (:any) %flag: any
// BRANCH-NEXT:       StoreFrameInst %1: environment, %2: any, [%VS3.flag]: any
// BRANCH-NEXT:       StoreFrameInst %1: environment, undefined: undefined, [%VS3.fn]: any
// BRANCH-NEXT:  %5 = CreateFunctionInst (:object) %1: environment, %VS3: any, %MaybeTarget(): functionCode
// BRANCH-NEXT:       StoreFrameInst %1: environment, %5: object, [%VS3.MaybeTarget]: any
// BRANCH-NEXT:  %7 = LoadFrameInst (:any) %1: environment, [%VS3.MaybeTarget]: any
// BRANCH-NEXT:       StoreFrameInst %1: environment, %7: any, [%VS3.fn]: any
// BRANCH-NEXT:  %9 = LoadFrameInst (:any) %1: environment, [%VS3.flag]: any
// BRANCH-NEXT:        CondBranchInst %9: any, %BB1, %BB2
// BRANCH-NEXT:%BB1:
// BRANCH-NEXT:        StoreFrameInst %1: environment, 0: number, [%VS3.fn]: any
// BRANCH-NEXT:        BranchInst %BB2
// BRANCH-NEXT:%BB2:
// BRANCH-NEXT:  %13 = LoadFrameInst (:any) %1: environment, [%VS3.fn]: any
// BRANCH-NEXT:  %14 = HasClosureTargetInst (:boolean) %13: any, %MaybeTarget(): functionCode, empty: any [ann#2] [closure:MaybeTarget]
// BRANCH-NEXT:        CondBranchInst %14: boolean, %BB3, %BB4
// BRANCH-NEXT:%BB3:
// BRANCH-NEXT:  %16 = UnionNarrowTrustedInst (:object) %13: any [closure:MaybeTarget]
// BRANCH-NEXT:  %17 = CallInst (:any) %16: object, %MaybeTarget(): functionCode, false: boolean, %1: environment, undefined: undefined, undefined: undefined
// BRANCH-NEXT:        ReturnInst 4: number
// BRANCH-NEXT:%BB4:
// BRANCH-NEXT:  %19 = CallInst (:any) %13: any, %MaybeTarget(): functionCode, false: boolean, %1: environment, undefined: undefined, undefined: undefined
// BRANCH-NEXT:        ReturnInst 4: number
// BRANCH-NEXT:function_end

// BRANCH:function SameTarget(): any [allCallsitesKnownInStrictMode]
// BRANCH-NEXT:%BB0:
// BRANCH-NEXT:       ReturnInst 2: number
// BRANCH-NEXT:function_end

// BRANCH:function DifferentTarget(): any [allCallsitesKnownInStrictMode]
// BRANCH-NEXT:%BB0:
// BRANCH-NEXT:       ReturnInst 3: number
// BRANCH-NEXT:function_end

// BRANCH:function MaybeTarget(): any [allCallsitesKnownInStrictMode]
// BRANCH-NEXT:%BB0:
// BRANCH-NEXT:       ReturnInst 4: number
// BRANCH-NEXT:function_end
