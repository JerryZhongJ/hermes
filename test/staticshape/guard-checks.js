/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %shermes -O0 -dump-ir -annotation-file=%S/guard-checks.json %s | %FileCheckOrRegen %s --check-prefix=IRGEN --match-full-lines
// RUN: %shermes -O0 -Xcustom-opt=insertguard -dump-ir -verify-ir -annotation-file=%S/guard-checks.json %s | %FileCheckOrRegen %s --check-prefix=INSERT --match-full-lines
// RUN: %shermes -O -dump-ir -annotation-file=%S/guard-checks.json %s | %FileCheckOrRegen %s --check-prefix=OPT --match-full-lines

function typeGuard(x) {
  return x + 1;
}

function shapeStatement() {
  var obj = {x: 1};
  return obj.x;
}

// Auto-generated content below. Please do not modify manually.

// IRGEN:scope %VS0 []

// IRGEN:function global(): any
// IRGEN-NEXT:%BB0:
// IRGEN-NEXT:  %0 = CreateScopeInst (:environment) %VS0: any, empty: any
// IRGEN-NEXT:       DeclareGlobalVarInst "typeGuard": string
// IRGEN-NEXT:       DeclareGlobalVarInst "shapeStatement": string
// IRGEN-NEXT:  %3 = CreateFunctionInst (:object) %0: environment, %VS0: any, %typeGuard(): functionCode
// IRGEN-NEXT:       StorePropertyLooseInst %3: object, globalObject: object, "typeGuard": string
// IRGEN-NEXT:  %5 = CreateFunctionInst (:object) %0: environment, %VS0: any, %shapeStatement(): functionCode
// IRGEN-NEXT:       StorePropertyLooseInst %5: object, globalObject: object, "shapeStatement": string
// IRGEN-NEXT:  %7 = AllocStackInst (:any) $?anon_0_ret: any
// IRGEN-NEXT:       StoreStackInst undefined: undefined, %7: any
// IRGEN-NEXT:  %9 = LoadStackInst (:any) %7: any
// IRGEN-NEXT:        ReturnInst %9: any
// IRGEN-NEXT:function_end

// IRGEN:scope %VS1 [x: any]

// IRGEN:function typeGuard(x: any): any
// IRGEN-NEXT:%BB0:
// IRGEN-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// IRGEN-NEXT:  %1 = CreateScopeInst (:environment) %VS1: any, %0: environment
// IRGEN-NEXT:  %2 = LoadParamInst (:any) %x: any
// IRGEN-NEXT:       StoreFrameInst %1: environment, %2: any, [%VS1.x]: any
// IRGEN-NEXT:  %4 = LoadFrameInst (:any) %1: environment, [%VS1.x]: any
// IRGEN-NEXT:  %5 = BinaryAddInst (:any) %4: any, 1: number
// IRGEN-NEXT:  %6 = TypeOfIsInst (:boolean) %5: any, typeOfIs(Number) [ann#0]
// IRGEN-NEXT:       ReturnInst %5: any
// IRGEN-NEXT:function_end

// IRGEN:scope %VS2 [obj: any]

// IRGEN:function shapeStatement(): any
// IRGEN-NEXT:%BB0:
// IRGEN-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// IRGEN-NEXT:  %1 = CreateScopeInst (:environment) %VS2: any, %0: environment
// IRGEN-NEXT:       StoreFrameInst %1: environment, undefined: undefined, [%VS2.obj]: any
// IRGEN-NEXT:  %3 = AllocObjectLiteralInst (:object) empty: any
// IRGEN-NEXT:       DefineOwnPropertyInst 1: number, %3: object, "x": string, true: boolean
// IRGEN-NEXT:  %5 = HasStaticShapeInst (:boolean) %3: object, {x: number}: null
// IRGEN-NEXT:       StoreFrameInst %1: environment, %3: object, [%VS2.obj]: any
// IRGEN-NEXT:       TrySetStaticShapeInst %3: object, {x: number}: null
// IRGEN-NEXT:  %8 = HasStaticShapeInst (:boolean) %3: object, {x: number}: null
// IRGEN-NEXT:  %9 = LoadFrameInst (:any) %1: environment, [%VS2.obj]: any
// IRGEN-NEXT:  %10 = LoadPropertyInst (:any) %9: any, "x": string
// IRGEN-NEXT:        ReturnInst %10: any
// IRGEN-NEXT:function_end

// INSERT:scope %VS0 []

// INSERT:function global(): any
// INSERT-NEXT:%BB0:
// INSERT-NEXT:  %0 = CreateScopeInst (:environment) %VS0: any, empty: any
// INSERT-NEXT:       DeclareGlobalVarInst "typeGuard": string
// INSERT-NEXT:       DeclareGlobalVarInst "shapeStatement": string
// INSERT-NEXT:  %3 = CreateFunctionInst (:object) %0: environment, %VS0: any, %typeGuard(): functionCode
// INSERT-NEXT:       StorePropertyLooseInst %3: object, globalObject: object, "typeGuard": string
// INSERT-NEXT:  %5 = CreateFunctionInst (:object) %0: environment, %VS0: any, %shapeStatement(): functionCode
// INSERT-NEXT:       StorePropertyLooseInst %5: object, globalObject: object, "shapeStatement": string
// INSERT-NEXT:  %7 = AllocStackInst (:any) $?anon_0_ret: any
// INSERT-NEXT:       StoreStackInst undefined: undefined, %7: any
// INSERT-NEXT:  %9 = LoadStackInst (:any) %7: any
// INSERT-NEXT:        ReturnInst %9: any
// INSERT-NEXT:function_end

// INSERT:scope %VS1 [x: any]

// INSERT:function typeGuard(x: any): any
// INSERT-NEXT:%BB0:
// INSERT-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// INSERT-NEXT:  %1 = CreateScopeInst (:environment) %VS1: any, %0: environment
// INSERT-NEXT:  %2 = LoadParamInst (:any) %x: any
// INSERT-NEXT:       StoreFrameInst %1: environment, %2: any, [%VS1.x]: any
// INSERT-NEXT:  %4 = LoadFrameInst (:any) %1: environment, [%VS1.x]: any
// INSERT-NEXT:  %5 = BinaryAddInst (:any) %4: any, 1: number
// INSERT-NEXT:  %6 = TypeOfIsInst (:boolean) %5: any, typeOfIs(Number) [ann#0]
// INSERT-NEXT:       CondBranchInst %6: boolean, %BB1, %BB2
// INSERT-NEXT:%BB1:
// INSERT-NEXT:  %8 = UnionNarrowTrustedInst (:number) %5: any
// INSERT-NEXT:       ReturnInst %8: number
// INSERT-NEXT:%BB2:
// INSERT-NEXT:        ReturnInst %5: any
// INSERT-NEXT:function_end

// INSERT:scope %VS2 [obj: any]

// INSERT:function shapeStatement(): any
// INSERT-NEXT:%BB0:
// INSERT-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// INSERT-NEXT:  %1 = CreateScopeInst (:environment) %VS2: any, %0: environment
// INSERT-NEXT:       StoreFrameInst %1: environment, undefined: undefined, [%VS2.obj]: any
// INSERT-NEXT:  %3 = AllocObjectLiteralInst (:object) empty: any
// INSERT-NEXT:       DefineOwnPropertyInst 1: number, %3: object, "x": string, true: boolean
// INSERT-NEXT:  %5 = HasStaticShapeInst (:boolean) %3: object, {x: number}: null
// INSERT-NEXT:       CondBranchInst %5: boolean, %BB3, %BB4
// INSERT-NEXT:%BB1:
// INSERT-NEXT:  %7 = LoadFrameInst (:any) %1: environment, [%VS2.obj]: any
// INSERT-NEXT:  %8 = LoadPropertyInst (:any) %7: any, "x": string
// INSERT-NEXT:       ReturnInst %8: any
// INSERT-NEXT:%BB2:
// INSERT-NEXT:  %10 = LoadFrameInst (:any) %1: environment, [%VS2.obj]: any
// INSERT-NEXT:  %11 = LoadPropertyInst (:any) %10: any, "x": string
// INSERT-NEXT:        ReturnInst %11: any
// INSERT-NEXT:%BB3:
// INSERT-NEXT:        StoreFrameInst %1: environment, %3: object, [%VS2.obj]: any
// INSERT-NEXT:        TrySetStaticShapeInst %3: object, {x: number}: null
// INSERT-NEXT:  %15 = HasStaticShapeInst (:boolean) %3: object, {x: number}: null
// INSERT-NEXT:        CondBranchInst %15: boolean, %BB1, %BB2
// INSERT-NEXT:%BB4:
// INSERT-NEXT:        StoreFrameInst %1: environment, %3: object, [%VS2.obj]: any
// INSERT-NEXT:        TrySetStaticShapeInst %3: object, {x: number}: null
// INSERT-NEXT:  %19 = HasStaticShapeInst (:boolean) %3: object, {x: number}: null
// INSERT-NEXT:        BranchInst %BB2
// INSERT-NEXT:function_end
