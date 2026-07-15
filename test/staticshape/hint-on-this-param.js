/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// Minimal repro: when a `this` shape hint AND a parameter type hint are both
// present on a function, the parameter stays pinned to the scope frame
// (StoreFrame/LoadFrame) instead of being promoted to a stack slot / register.
// Either hint alone does not trigger it; the two must coexist.
//
// Root cause: emitFunctionPrologue applied the `this` annotation (emitting the
// HasStaticShape shape guard) before makeNewScope (the CreateScopeInst), so the
// shape guard was the first split point and spanned the scope's creation.
// InsertGuard then duplicated the CreateScopeInst into both paths and formed a
// scope-phi at the type guard's merge, which blocked SimpleStackPromotion. The
// fix applies the `this` annotation after the scope is created, so the guard
// sits after the single CreateScopeInst and no scope-phi is generated.

// RUN: %shermes -O0 -dump-ir -annotation-file=%S/hint-on-this-param.json %s | %FileCheckOrRegen %s --check-prefix=IRGEN --match-full-lines
// RUN: %shermes -O0 -Xcustom-opt=insertguard -dump-ir -verify-ir -annotation-file=%S/hint-on-this-param.json %s | %FileCheckOrRegen %s --check-prefix=INSERT --match-full-lines
// RUN: %shermes -O -dump-lir -annotation-file=%S/hint-on-this-param.json %s | %FileCheckOrRegen %s --check-prefix=OPT --match-full-lines

function Vec(x) {
  this.x = x;
}
Vec.prototype.mul = function(p) {
  if (p === undefined) p = 0;
  this.x *= p;
};
new Vec(1).mul(3);

// Auto-generated content below. Please do not modify manually.

// IRGEN:scope %VS0 []

// IRGEN:function global(): any
// IRGEN-NEXT:%BB0:
// IRGEN-NEXT:  %0 = CreateScopeInst (:environment) %VS0: any, empty: any
// IRGEN-NEXT:       DeclareGlobalVarInst "Vec": string
// IRGEN-NEXT:  %2 = CreateFunctionInst (:object) %0: environment, %VS0: any, %Vec(): functionCode
// IRGEN-NEXT:       StorePropertyLooseInst %2: object, globalObject: object, "Vec": string
// IRGEN-NEXT:  %4 = AllocStackInst (:any) $?anon_0_ret: any
// IRGEN-NEXT:       StoreStackInst undefined: undefined, %4: any
// IRGEN-NEXT:  %6 = LoadPropertyInst (:any) globalObject: object, "Vec": string
// IRGEN-NEXT:  %7 = LoadPropertyInst (:any) %6: any, "prototype": string
// IRGEN-NEXT:  %8 = CreateFunctionInst (:object) %0: environment, %VS0: any, %""(): functionCode
// IRGEN-NEXT:       StorePropertyLooseInst %8: object, %7: any, "mul": string
// IRGEN-NEXT:        StoreStackInst %8: object, %4: any
// IRGEN-NEXT:  %11 = LoadPropertyInst (:any) globalObject: object, "Vec": string
// IRGEN-NEXT:  %12 = CreateThisInst (:any) %11: any, %11: any, empty: any
// IRGEN-NEXT:  %13 = CallInst (:any) %11: any, empty: any, false: boolean, empty: any, %11: any, %12: any, 1: number
// IRGEN-NEXT:  %14 = GetConstructedObjectInst (:object) %12: any, %13: any
// IRGEN-NEXT:  %15 = LoadPropertyInst (:any) %14: object, "mul": string
// IRGEN-NEXT:  %16 = CallInst (:any) %15: any, empty: any, false: boolean, empty: any, undefined: undefined, %14: object, 3: number
// IRGEN-NEXT:        StoreStackInst %16: any, %4: any
// IRGEN-NEXT:  %18 = LoadStackInst (:any) %4: any
// IRGEN-NEXT:        ReturnInst %18: any
// IRGEN-NEXT:function_end

// IRGEN:scope %VS1 [x: any]

// IRGEN:function Vec(x: any): any
// IRGEN-NEXT:%BB0:
// IRGEN-NEXT:  %0 = LoadParamInst (:any) %<this>: any
// IRGEN-NEXT:  %1 = CoerceThisNSInst (:object) %0: any
// IRGEN-NEXT:  %2 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// IRGEN-NEXT:  %3 = CreateScopeInst (:environment) %VS1: any, %2: environment
// IRGEN-NEXT:  %4 = LoadParamInst (:any) %x: any
// IRGEN-NEXT:       StoreFrameInst %3: environment, %4: any, [%VS1.x]: any
// IRGEN-NEXT:  %6 = LoadFrameInst (:any) %3: environment, [%VS1.x]: any
// IRGEN-NEXT:       StorePropertyLooseInst %6: any, %1: object, "x": string
// IRGEN-NEXT:       ReturnInst undefined: undefined
// IRGEN-NEXT:function_end

// IRGEN:scope %VS2 [p: any]

// IRGEN:function ""(p: any): any
// IRGEN-NEXT:%BB0:
// IRGEN-NEXT:  %0 = LoadParamInst (:any) %<this>: any
// IRGEN-NEXT:  %1 = CoerceThisNSInst (:object) %0: any
// IRGEN-NEXT:  %2 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// IRGEN-NEXT:  %3 = CreateScopeInst (:environment) %VS2: any, %2: environment
// IRGEN-NEXT:  %4 = HasStaticShapeInst (:boolean) %1: object, {x: number}: null [ann#1]
// IRGEN-NEXT:  %5 = LoadParamInst (:any) %p: any
// IRGEN-NEXT:  %6 = TypeOfIsInst (:boolean) %5: any, typeOfIs(Number) [ann#0]
// IRGEN-NEXT:       StoreFrameInst %3: environment, %5: any, [%VS2.p]: any
// IRGEN-NEXT:  %8 = LoadFrameInst (:any) %3: environment, [%VS2.p]: any
// IRGEN-NEXT:  %9 = BinaryStrictlyEqualInst (:boolean) %8: any, undefined: undefined
// IRGEN-NEXT:        CondBranchInst %9: boolean, %BB1, %BB2
// IRGEN-NEXT:%BB1:
// IRGEN-NEXT:        StoreFrameInst %3: environment, 0: number, [%VS2.p]: any
// IRGEN-NEXT:        BranchInst %BB3
// IRGEN-NEXT:%BB2:
// IRGEN-NEXT:        BranchInst %BB3
// IRGEN-NEXT:%BB3:
// IRGEN-NEXT:  %14 = LoadPropertyInst (:any) %1: object, "x": string
// IRGEN-NEXT:  %15 = LoadFrameInst (:any) %3: environment, [%VS2.p]: any
// IRGEN-NEXT:  %16 = BinaryMultiplyInst (:any) %14: any, %15: any
// IRGEN-NEXT:        StorePropertyLooseInst %16: any, %1: object, "x": string
// IRGEN-NEXT:        ReturnInst undefined: undefined
// IRGEN-NEXT:function_end

// INSERT:scope %VS0 []

// INSERT:function global(): any
// INSERT-NEXT:%BB0:
// INSERT-NEXT:  %0 = CreateScopeInst (:environment) %VS0: any, empty: any
// INSERT-NEXT:       DeclareGlobalVarInst "Vec": string
// INSERT-NEXT:  %2 = CreateFunctionInst (:object) %0: environment, %VS0: any, %Vec(): functionCode
// INSERT-NEXT:       StorePropertyLooseInst %2: object, globalObject: object, "Vec": string
// INSERT-NEXT:  %4 = AllocStackInst (:any) $?anon_0_ret: any
// INSERT-NEXT:       StoreStackInst undefined: undefined, %4: any
// INSERT-NEXT:  %6 = LoadPropertyInst (:any) globalObject: object, "Vec": string
// INSERT-NEXT:  %7 = LoadPropertyInst (:any) %6: any, "prototype": string
// INSERT-NEXT:  %8 = CreateFunctionInst (:object) %0: environment, %VS0: any, %""(): functionCode
// INSERT-NEXT:       StorePropertyLooseInst %8: object, %7: any, "mul": string
// INSERT-NEXT:        StoreStackInst %8: object, %4: any
// INSERT-NEXT:  %11 = LoadPropertyInst (:any) globalObject: object, "Vec": string
// INSERT-NEXT:  %12 = CreateThisInst (:any) %11: any, %11: any, empty: any
// INSERT-NEXT:  %13 = CallInst (:any) %11: any, empty: any, false: boolean, empty: any, %11: any, %12: any, 1: number
// INSERT-NEXT:  %14 = GetConstructedObjectInst (:object) %12: any, %13: any
// INSERT-NEXT:  %15 = LoadPropertyInst (:any) %14: object, "mul": string
// INSERT-NEXT:  %16 = CallInst (:any) %15: any, empty: any, false: boolean, empty: any, undefined: undefined, %14: object, 3: number
// INSERT-NEXT:        StoreStackInst %16: any, %4: any
// INSERT-NEXT:  %18 = LoadStackInst (:any) %4: any
// INSERT-NEXT:        ReturnInst %18: any
// INSERT-NEXT:function_end

// INSERT:scope %VS1 [x: any]

// INSERT:function Vec(x: any): any
// INSERT-NEXT:%BB0:
// INSERT-NEXT:  %0 = LoadParamInst (:any) %<this>: any
// INSERT-NEXT:  %1 = CoerceThisNSInst (:object) %0: any
// INSERT-NEXT:  %2 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// INSERT-NEXT:  %3 = CreateScopeInst (:environment) %VS1: any, %2: environment
// INSERT-NEXT:  %4 = LoadParamInst (:any) %x: any
// INSERT-NEXT:       StoreFrameInst %3: environment, %4: any, [%VS1.x]: any
// INSERT-NEXT:  %6 = LoadFrameInst (:any) %3: environment, [%VS1.x]: any
// INSERT-NEXT:       StorePropertyLooseInst %6: any, %1: object, "x": string
// INSERT-NEXT:       ReturnInst undefined: undefined
// INSERT-NEXT:function_end

// INSERT:scope %VS2 [p: any]

// INSERT:function ""(p: any): any
// INSERT-NEXT:%BB0:
// INSERT-NEXT:  %0 = LoadParamInst (:any) %<this>: any
// INSERT-NEXT:  %1 = CoerceThisNSInst (:object) %0: any
// INSERT-NEXT:  %2 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// INSERT-NEXT:  %3 = CreateScopeInst (:environment) %VS2: any, %2: environment
// INSERT-NEXT:  %4 = HasStaticShapeInst (:boolean) %1: object, {x: number}: null [ann#1]
// INSERT-NEXT:       CondBranchInst %4: boolean, %BB7, %BB8
// INSERT-NEXT:%BB1:
// INSERT-NEXT:       StoreFrameInst %3: environment, 0: number, [%VS2.p]: any
// INSERT-NEXT:       BranchInst %BB3
// INSERT-NEXT:%BB2:
// INSERT-NEXT:       BranchInst %BB3
// INSERT-NEXT:%BB3:
// INSERT-NEXT:  %9 = LoadPropertyInst (:any) %1: object, "x": string
// INSERT-NEXT:  %10 = LoadFrameInst (:any) %3: environment, [%VS2.p]: any
// INSERT-NEXT:  %11 = BinaryMultiplyInst (:any) %9: any, %10: any
// INSERT-NEXT:        StorePropertyLooseInst %11: any, %1: object, "x": string
// INSERT-NEXT:        ReturnInst undefined: undefined
// INSERT-NEXT:%BB4:
// INSERT-NEXT:        StoreFrameInst %3: environment, 0: number, [%VS2.p]: any
// INSERT-NEXT:        BranchInst %BB6
// INSERT-NEXT:%BB5:
// INSERT-NEXT:        BranchInst %BB6
// INSERT-NEXT:%BB6:
// INSERT-NEXT:  %17 = LoadPropertyInst (:any) %1: object, "x": string
// INSERT-NEXT:  %18 = LoadFrameInst (:any) %3: environment, [%VS2.p]: any
// INSERT-NEXT:  %19 = BinaryMultiplyInst (:any) %17: any, %18: any
// INSERT-NEXT:        StorePropertyLooseInst %19: any, %1: object, "x": string
// INSERT-NEXT:        ReturnInst undefined: undefined
// INSERT-NEXT:%BB7:
// INSERT-NEXT:  %22 = LoadParamInst (:any) %p: any
// INSERT-NEXT:  %23 = TypeOfIsInst (:boolean) %22: any, typeOfIs(Number) [ann#0]
// INSERT-NEXT:        CondBranchInst %23: boolean, %BB9, %BB10
// INSERT-NEXT:%BB8:
// INSERT-NEXT:  %25 = LoadParamInst (:any) %p: any
// INSERT-NEXT:  %26 = TypeOfIsInst (:boolean) %25: any, typeOfIs(Number) [ann#0]
// INSERT-NEXT:        BranchInst %BB10
// INSERT-NEXT:%BB9:
// INSERT-NEXT:  %28 = UnionNarrowTrustedInst (:number) %22: any
// INSERT-NEXT:        StoreFrameInst %3: environment, %28: number, [%VS2.p]: any
// INSERT-NEXT:  %30 = LoadFrameInst (:any) %3: environment, [%VS2.p]: any
// INSERT-NEXT:  %31 = BinaryStrictlyEqualInst (:boolean) %30: any, undefined: undefined
// INSERT-NEXT:        CondBranchInst %31: boolean, %BB1, %BB2
// INSERT-NEXT:%BB10:
// INSERT-NEXT:  %33 = PhiInst (:any) %25: any, %BB8, %22: any, %BB7
// INSERT-NEXT:        StoreFrameInst %3: environment, %33: any, [%VS2.p]: any
// INSERT-NEXT:  %35 = LoadFrameInst (:any) %3: environment, [%VS2.p]: any
// INSERT-NEXT:  %36 = BinaryStrictlyEqualInst (:boolean) %35: any, undefined: undefined
// INSERT-NEXT:        CondBranchInst %36: boolean, %BB4, %BB5
// INSERT-NEXT:function_end

// OPT:function global(): any [noReturn]
// OPT-NEXT:%BB0:
// OPT-NEXT:       DeclareGlobalVarInst "Vec": string
// OPT-NEXT:  %1 = LIRGetGlobalObjectInst (:object)
// OPT-NEXT:  %2 = CreateFunctionInst (:object) empty: any, empty: any, %Vec(): functionCode
// OPT-NEXT:       StorePropertyLooseInst %2: object, %1: object, "Vec": string
// OPT-NEXT:  %4 = LoadPropertyInst (:any) %1: object, "Vec": string
// OPT-NEXT:  %5 = LoadPropertyInst (:any) %4: any, "prototype": string
// OPT-NEXT:  %6 = CreateFunctionInst (:object) empty: any, empty: any, %""(): functionCode
// OPT-NEXT:       StorePropertyLooseInst %6: object, %5: any, "mul": string
// OPT-NEXT:  %8 = LoadPropertyInst (:any) %1: object, "Vec": string
// OPT-NEXT:  %9 = CreateThisInst (:undefined|object) %8: any, %8: any, empty: any
// OPT-NEXT:  %10 = LIRLoadConstInst (:number) 1: number
// OPT-NEXT:  %11 = CallInst (:any) %8: any, empty: any, false: boolean, empty: any, %8: any, %9: undefined|object, %10: number
// OPT-NEXT:  %12 = GetConstructedObjectInst (:object) %9: undefined|object, %11: any
// OPT-NEXT:  %13 = LoadPropertyInst (:any) %12: object, "mul": string
// OPT-NEXT:  %14 = LIRLoadConstInst (:number) 3: number
// OPT-NEXT:  %15 = LIRLoadConstInst (:undefined) undefined: undefined
// OPT-NEXT:  %16 = CallInst (:any) %13: any, empty: any, false: boolean, empty: any, %15: undefined, %12: object, %14: number
// OPT-NEXT:        ReturnInst %16: any
// OPT-NEXT:function_end

// OPT:function Vec(x: any): undefined
// OPT-NEXT:%BB0:
// OPT-NEXT:  %0 = LoadParamInst (:any) %x: any
// OPT-NEXT:  %1 = LIRGetThisNSInst (:object)
// OPT-NEXT:       StorePropertyLooseInst %0: any, %1: object, "x": string
// OPT-NEXT:  %3 = LIRLoadConstInst (:undefined) undefined: undefined
// OPT-NEXT:       ReturnInst %3: undefined
// OPT-NEXT:function_end

// OPT:function ""(p: any): undefined
// OPT-NEXT:%BB0:
// OPT-NEXT:  %0 = LIRGetThisNSInst (:object)
// OPT-NEXT:  %1 = HasStaticShapeInst (:boolean) %0: object, {x: number}: null [ann#1]
// OPT-NEXT:  %2 = LoadParamInst (:any) %p: any
// OPT-NEXT:       CondBranchInst %1: boolean, %BB3, %BB4
// OPT-NEXT:%BB1:
// OPT-NEXT:  %4 = LIRLoadConstInst (:number) 0: number
// OPT-NEXT:       BranchInst %BB2
// OPT-NEXT:%BB2:
// OPT-NEXT:  %6 = PhiInst (:any) %4: number, %BB1, %20: any, %BB6
// OPT-NEXT:  %7 = LoadPropertyInst (:any) %0: object, "x": string
// OPT-NEXT:  %8 = BinaryMultiplyInst (:number|bigint) %7: any, %6: any
// OPT-NEXT:       StorePropertyLooseInst %8: number|bigint, %0: object, "x": string
// OPT-NEXT:        ReturnInst %21: undefined
// OPT-NEXT:%BB3:
// OPT-NEXT:  %11 = TypeOfIsInst (:boolean) %2: any, typeOfIs(Number) [ann#0]
// OPT-NEXT:        CondBranchInst %11: boolean, %BB5, %BB6
// OPT-NEXT:%BB4:
// OPT-NEXT:        BranchInst %BB6
// OPT-NEXT:%BB5:
// OPT-NEXT:  %14 = PrLoadInst (:number) %0: object, 0: number, "x": string
// OPT-NEXT:  %15 = UnionNarrowTrustedInst (:number) %2: any
// OPT-NEXT:  %16 = FMultiplyInst (:number) %14: number, %15: number
// OPT-NEXT:        PrStoreInst %16: number, %0: object, 0: number, "x": string
// OPT-NEXT:  %18 = LIRLoadConstInst (:undefined) undefined: undefined
// OPT-NEXT:        ReturnInst %18: undefined
// OPT-NEXT:%BB6:
// OPT-NEXT:  %20 = PhiInst (:any) %2: any, %BB4, %2: any, %BB3
// OPT-NEXT:  %21 = LIRLoadConstInst (:undefined) undefined: undefined
// OPT-NEXT:  %22 = BinaryStrictlyEqualInst (:boolean) %20: any, %21: undefined
// OPT-NEXT:        CondBranchInst %22: boolean, %BB1, %BB2
// OPT-NEXT:function_end
