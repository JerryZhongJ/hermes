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
// IRGEN-NEXT:  %3 = TypeOfIsInst (:boolean) %2: any, typeOfIs(Number) [ann#0]
// IRGEN-NEXT:       StoreFrameInst %1: environment, %2: any, [%VS1.x]: any
// IRGEN-NEXT:  %5 = LoadFrameInst (:any) %1: environment, [%VS1.x]: any
// IRGEN-NEXT:  %6 = BinaryAddInst (:any) %5: any, 1: number
// IRGEN-NEXT:       ReturnInst %6: any
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
// INSERT-NEXT:  %3 = TypeOfIsInst (:boolean) %2: any, typeOfIs(Number) [ann#0]
// INSERT-NEXT:       CondBranchInst %3: boolean, %BB1, %BB2
// INSERT-NEXT:%BB1:
// INSERT-NEXT:  %5 = UnionNarrowTrustedInst (:number) %2: any
// INSERT-NEXT:       StoreFrameInst %1: environment, %5: number, [%VS1.x]: any
// INSERT-NEXT:  %7 = LoadFrameInst (:any) %1: environment, [%VS1.x]: any
// INSERT-NEXT:  %8 = BinaryAddInst (:any) %7: any, 1: number
// INSERT-NEXT:       ReturnInst %8: any
// INSERT-NEXT:%BB2:
// INSERT-NEXT:        StoreFrameInst %1: environment, %2: any, [%VS1.x]: any
// INSERT-NEXT:  %11 = LoadFrameInst (:any) %1: environment, [%VS1.x]: any
// INSERT-NEXT:  %12 = BinaryAddInst (:any) %11: any, 1: number
// INSERT-NEXT:        ReturnInst %12: any
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

// OPT:function global(): undefined
// OPT-NEXT:%BB0:
// OPT-NEXT:       DeclareGlobalVarInst "typeGuard": string
// OPT-NEXT:       DeclareGlobalVarInst "shapeStatement": string
// OPT-NEXT:  %2 = CreateFunctionInst (:object) empty: any, empty: any, %typeGuard(): functionCode
// OPT-NEXT:       StorePropertyLooseInst %2: object, globalObject: object, "typeGuard": string
// OPT-NEXT:  %4 = CreateFunctionInst (:object) empty: any, empty: any, %shapeStatement(): functionCode
// OPT-NEXT:       StorePropertyLooseInst %4: object, globalObject: object, "shapeStatement": string
// OPT-NEXT:       ReturnInst undefined: undefined
// OPT-NEXT:function_end

// OPT:function typeGuard(x: any): string|number
// OPT-NEXT:%BB0:
// OPT-NEXT:  %0 = LoadParamInst (:any) %x: any
// OPT-NEXT:  %1 = TypeOfIsInst (:boolean) %0: any, typeOfIs(Number) [ann#0]
// OPT-NEXT:       CondBranchInst %1: boolean, %BB1, %BB2
// OPT-NEXT:%BB1:
// OPT-NEXT:  %3 = UnionNarrowTrustedInst (:number) %0: any
// OPT-NEXT:  %4 = FAddInst (:number) %3: number, 1: number
// OPT-NEXT:       ReturnInst %4: number
// OPT-NEXT:%BB2:
// OPT-NEXT:  %6 = BinaryAddInst (:string|number) %0: any, 1: number
// OPT-NEXT:       ReturnInst %6: string|number
// OPT-NEXT:function_end

// OPT:function shapeStatement(): any
// OPT-NEXT:%BB0:
// OPT-NEXT:  %0 = AllocObjectLiteralInst (:object) empty: any, "x": string, 1: number
// OPT-NEXT:  %1 = HasStaticShapeInst (:boolean) %0: object, {x: number}: null
// OPT-NEXT:       CondBranchInst %1: boolean, %BB1, %BB2
// OPT-NEXT:%BB1:
// OPT-NEXT:  %3 = PrLoadInst (:number) %0: object, 0: number, "x": string
// OPT-NEXT:       ReturnInst %3: number
// OPT-NEXT:%BB2:
// OPT-NEXT:       TrySetStaticShapeInst %0: object, {x: number}: null
// OPT-NEXT:  %6 = LoadPropertyInst (:any) %0: object, "x": string
// OPT-NEXT:       ReturnInst %6: any
// OPT-NEXT:function_end
