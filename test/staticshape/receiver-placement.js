// RUN: %shermes -O0 -dump-ir -annotation-file=%S/receiver-placement.json %s | %FileCheckOrRegen %s --check-prefix=CHK --match-full-lines

function sideEffect() {
  return 1;
}

function simpleStore(obj) {
  obj.x = sideEffect();
}

function computedStore(obj, key) {
  obj[key()] = sideEffect();
}

function compoundStore(obj) {
  obj.x += sideEffect();
}

function updateStore(obj) {
  obj.x++;
}

function methodLoad(obj) {
  return obj.m();
}

function ternaryLoad(cond, a, b) {
  return (cond ? a : b).x;
}

function directLoad(obj) {
  return obj.x;
}

function logicalStore(obj) {
  obj.x ||= sideEffect();
}

function optionalLoad(obj, key) {
  return obj?.[key()];
}

function taggedLoad(obj) {
  return obj.m`x`;
}

class PrivateBox {
  #x;
  read(obj) {
    return obj.#x;
  }
}

function deleteMember(obj) {
  return delete obj.x;
}

function deleteNestedOptional(obj) {
  return delete obj?.x.y;
}

// RUN: %shermes -O0 -Xcustom-opt=insertguard -instrument-guards -emit-c -o - -annotation-file=%S/receiver-placement.json %s | %FileCheck %s --check-prefix=RANGE
// RUN: %shermes -O0 -Xcustom-opt=insertguard -instrument-guards-details=2 -emit-c -o - -annotation-file=%S/receiver-placement.json %s | %FileCheck %s --check-prefix=DETAILS
// RANGE: ann#2 [shape guard X] @16:3-16:6: success=%llu, fail=%llu
// RANGE-NOT: _sh_record_guard_detail
// DETAILS: SHLegacyValue __hss_arg_
// DETAILS: _sh_record_guard_detail(shr, __hss_arg_
// DETAILS: _sh_dump_clear_guard_details(shr);

// Auto-generated content below. Please do not modify manually.

// CHK:scope %VS0 [PrivateBox: any, PrivateBox#1: any, #x: privateName, ?PrivateBox.prototype: object, ?PrivateBox: object, <instElemInitFunc:PrivateBox>: object]

// CHK:function global(): any
// CHK-NEXT:%BB0:
// CHK-NEXT:  %0 = CreateScopeInst (:environment) %VS0: any, empty: any
// CHK-NEXT:       DeclareGlobalVarInst "sideEffect": string
// CHK-NEXT:       DeclareGlobalVarInst "simpleStore": string
// CHK-NEXT:       DeclareGlobalVarInst "computedStore": string
// CHK-NEXT:       DeclareGlobalVarInst "compoundStore": string
// CHK-NEXT:       DeclareGlobalVarInst "updateStore": string
// CHK-NEXT:       DeclareGlobalVarInst "methodLoad": string
// CHK-NEXT:       DeclareGlobalVarInst "ternaryLoad": string
// CHK-NEXT:       DeclareGlobalVarInst "directLoad": string
// CHK-NEXT:       DeclareGlobalVarInst "logicalStore": string
// CHK-NEXT:        DeclareGlobalVarInst "optionalLoad": string
// CHK-NEXT:        DeclareGlobalVarInst "taggedLoad": string
// CHK-NEXT:        StoreFrameInst %0: environment, undefined: undefined, [%VS0.PrivateBox]: any
// CHK-NEXT:        DeclareGlobalVarInst "deleteMember": string
// CHK-NEXT:        DeclareGlobalVarInst "deleteNestedOptional": string
// CHK-NEXT:  %15 = CreateFunctionInst (:object) %0: environment, %VS0: any, %sideEffect(): functionCode
// CHK-NEXT:        StorePropertyLooseInst %15: object, globalObject: object, "sideEffect": string
// CHK-NEXT:  %17 = CreateFunctionInst (:object) %0: environment, %VS0: any, %simpleStore(): functionCode
// CHK-NEXT:        StorePropertyLooseInst %17: object, globalObject: object, "simpleStore": string
// CHK-NEXT:  %19 = CreateFunctionInst (:object) %0: environment, %VS0: any, %computedStore(): functionCode
// CHK-NEXT:        StorePropertyLooseInst %19: object, globalObject: object, "computedStore": string
// CHK-NEXT:  %21 = CreateFunctionInst (:object) %0: environment, %VS0: any, %compoundStore(): functionCode
// CHK-NEXT:        StorePropertyLooseInst %21: object, globalObject: object, "compoundStore": string
// CHK-NEXT:  %23 = CreateFunctionInst (:object) %0: environment, %VS0: any, %updateStore(): functionCode
// CHK-NEXT:        StorePropertyLooseInst %23: object, globalObject: object, "updateStore": string
// CHK-NEXT:  %25 = CreateFunctionInst (:object) %0: environment, %VS0: any, %methodLoad(): functionCode
// CHK-NEXT:        StorePropertyLooseInst %25: object, globalObject: object, "methodLoad": string
// CHK-NEXT:  %27 = CreateFunctionInst (:object) %0: environment, %VS0: any, %ternaryLoad(): functionCode
// CHK-NEXT:        StorePropertyLooseInst %27: object, globalObject: object, "ternaryLoad": string
// CHK-NEXT:  %29 = CreateFunctionInst (:object) %0: environment, %VS0: any, %directLoad(): functionCode
// CHK-NEXT:        StorePropertyLooseInst %29: object, globalObject: object, "directLoad": string
// CHK-NEXT:  %31 = CreateFunctionInst (:object) %0: environment, %VS0: any, %logicalStore(): functionCode
// CHK-NEXT:        StorePropertyLooseInst %31: object, globalObject: object, "logicalStore": string
// CHK-NEXT:  %33 = CreateFunctionInst (:object) %0: environment, %VS0: any, %optionalLoad(): functionCode
// CHK-NEXT:        StorePropertyLooseInst %33: object, globalObject: object, "optionalLoad": string
// CHK-NEXT:  %35 = CreateFunctionInst (:object) %0: environment, %VS0: any, %taggedLoad(): functionCode
// CHK-NEXT:        StorePropertyLooseInst %35: object, globalObject: object, "taggedLoad": string
// CHK-NEXT:  %37 = CreateFunctionInst (:object) %0: environment, %VS0: any, %deleteMember(): functionCode
// CHK-NEXT:        StorePropertyLooseInst %37: object, globalObject: object, "deleteMember": string
// CHK-NEXT:  %39 = CreateFunctionInst (:object) %0: environment, %VS0: any, %deleteNestedOptional(): functionCode
// CHK-NEXT:        StorePropertyLooseInst %39: object, globalObject: object, "deleteNestedOptional": string
// CHK-NEXT:  %41 = AllocStackInst (:any) $?anon_0_ret: any
// CHK-NEXT:        StoreStackInst undefined: undefined, %41: any
// CHK-NEXT:        StoreFrameInst %0: environment, undefined: undefined, [%VS0.PrivateBox#1]: any
// CHK-NEXT:  %44 = CreatePrivateNameInst (:privateName) "#x": string
// CHK-NEXT:        StoreFrameInst %0: environment, %44: privateName, [%VS0.#x]: privateName
// CHK-NEXT:  %46 = CreateFunctionInst (:object) %0: environment, %VS0: any, %<instance_members_initializer:PrivateBox>(): functionCode
// CHK-NEXT:        StoreFrameInst %0: environment, %46: object, [%VS0.<instElemInitFunc:PrivateBox>]: object
// CHK-NEXT:  %48 = AllocStackInst (:object) $?anon_1_clsPrototype: any
// CHK-NEXT:  %49 = CreateClassInst (:object) %0: environment, %VS0: any, %PrivateBox(): functionCode, empty: any, %48: object
// CHK-NEXT:  %50 = LoadStackInst (:object) %48: object
// CHK-NEXT:  %51 = CreateFunctionInst (:object) %0: environment, %VS0: any, %read(): functionCode
// CHK-NEXT:        DefineOwnPropertyInst %51: object, %50: object, "read": string, false: boolean
// CHK-NEXT:        StoreFrameInst %0: environment, %49: object, [%VS0.PrivateBox#1]: any
// CHK-NEXT:        StoreFrameInst %0: environment, %49: object, [%VS0.?PrivateBox]: object
// CHK-NEXT:        StoreFrameInst %0: environment, %50: object, [%VS0.?PrivateBox.prototype]: object
// CHK-NEXT:        StoreFrameInst %0: environment, %49: object, [%VS0.PrivateBox]: any
// CHK-NEXT:  %57 = LoadStackInst (:any) %41: any
// CHK-NEXT:        ReturnInst %57: any
// CHK-NEXT:function_end

// CHK:scope %VS1 []

// CHK:function sideEffect(): any
// CHK-NEXT:%BB0:
// CHK-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// CHK-NEXT:  %1 = CreateScopeInst (:environment) %VS1: any, %0: environment
// CHK-NEXT:       ReturnInst 1: number
// CHK-NEXT:function_end

// CHK:scope %VS2 [obj: any]

// CHK:function simpleStore(obj: any): any
// CHK-NEXT:%BB0:
// CHK-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// CHK-NEXT:  %1 = CreateScopeInst (:environment) %VS2: any, %0: environment
// CHK-NEXT:  %2 = LoadParamInst (:any) %obj: any
// CHK-NEXT:       StoreFrameInst %1: environment, %2: any, [%VS2.obj]: any
// CHK-NEXT:  %4 = LoadFrameInst (:any) %1: environment, [%VS2.obj]: any
// CHK-NEXT:  %5 = LoadPropertyInst (:any) globalObject: object, "sideEffect": string
// CHK-NEXT:  %6 = CallInst (:any) %5: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined
// CHK-NEXT:  %7 = HasStaticShapeInst (:boolean) %4: any, {x: any}: null [ann#0]
// CHK-NEXT:       StorePropertyLooseInst %6: any, %4: any, "x": string
// CHK-NEXT:       TrySetStaticShapeInst %4: any, {x: any}: null [ann#13]
// CHK-NEXT:  %10 = HasStaticShapeInst (:boolean) %4: any, {x: any}: null [ann#13]
// CHK-NEXT:        ReturnInst undefined: undefined
// CHK-NEXT:function_end

// CHK:scope %VS3 [obj: any, key: any]

// CHK:function computedStore(obj: any, key: any): any
// CHK-NEXT:%BB0:
// CHK-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// CHK-NEXT:  %1 = CreateScopeInst (:environment) %VS3: any, %0: environment
// CHK-NEXT:  %2 = LoadParamInst (:any) %obj: any
// CHK-NEXT:       StoreFrameInst %1: environment, %2: any, [%VS3.obj]: any
// CHK-NEXT:  %4 = LoadParamInst (:any) %key: any
// CHK-NEXT:       StoreFrameInst %1: environment, %4: any, [%VS3.key]: any
// CHK-NEXT:  %6 = LoadFrameInst (:any) %1: environment, [%VS3.obj]: any
// CHK-NEXT:  %7 = LoadFrameInst (:any) %1: environment, [%VS3.key]: any
// CHK-NEXT:  %8 = CallInst (:any) %7: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined
// CHK-NEXT:  %9 = LoadPropertyInst (:any) globalObject: object, "sideEffect": string
// CHK-NEXT:  %10 = CallInst (:any) %9: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined
// CHK-NEXT:  %11 = HasStaticShapeInst (:boolean) %6: any, {x: any}: null [ann#1]
// CHK-NEXT:        StorePropertyLooseInst %10: any, %6: any, %8: any
// CHK-NEXT:        TrySetStaticShapeInst %6: any, {x: any}: null [ann#14]
// CHK-NEXT:  %14 = HasStaticShapeInst (:boolean) %6: any, {x: any}: null [ann#14]
// CHK-NEXT:        ReturnInst undefined: undefined
// CHK-NEXT:function_end

// CHK:scope %VS4 [obj: any]

// CHK:function compoundStore(obj: any): any
// CHK-NEXT:%BB0:
// CHK-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// CHK-NEXT:  %1 = CreateScopeInst (:environment) %VS4: any, %0: environment
// CHK-NEXT:  %2 = LoadParamInst (:any) %obj: any
// CHK-NEXT:       StoreFrameInst %1: environment, %2: any, [%VS4.obj]: any
// CHK-NEXT:  %4 = LoadFrameInst (:any) %1: environment, [%VS4.obj]: any
// CHK-NEXT:  %5 = HasStaticShapeInst (:boolean) %4: any, {x: any}: null [ann#2]
// CHK-NEXT:  %6 = LoadPropertyInst (:any) %4: any, "x": string
// CHK-NEXT:  %7 = LoadPropertyInst (:any) globalObject: object, "sideEffect": string
// CHK-NEXT:  %8 = CallInst (:any) %7: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined
// CHK-NEXT:  %9 = BinaryAddInst (:any) %6: any, %8: any
// CHK-NEXT:  %10 = HasStaticShapeInst (:boolean) %4: any, {x: any}: null [ann#2]
// CHK-NEXT:        StorePropertyLooseInst %9: any, %4: any, "x": string
// CHK-NEXT:        TrySetStaticShapeInst %4: any, {x: any}: null [ann#15]
// CHK-NEXT:  %13 = HasStaticShapeInst (:boolean) %4: any, {x: any}: null [ann#15]
// CHK-NEXT:        ReturnInst undefined: undefined
// CHK-NEXT:function_end

// CHK:scope %VS5 [obj: any]

// CHK:function updateStore(obj: any): any
// CHK-NEXT:%BB0:
// CHK-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// CHK-NEXT:  %1 = CreateScopeInst (:environment) %VS5: any, %0: environment
// CHK-NEXT:  %2 = LoadParamInst (:any) %obj: any
// CHK-NEXT:       StoreFrameInst %1: environment, %2: any, [%VS5.obj]: any
// CHK-NEXT:  %4 = LoadFrameInst (:any) %1: environment, [%VS5.obj]: any
// CHK-NEXT:  %5 = HasStaticShapeInst (:boolean) %4: any, {x: any}: null [ann#3]
// CHK-NEXT:  %6 = LoadPropertyInst (:any) %4: any, "x": string
// CHK-NEXT:  %7 = AsNumericInst (:number|bigint) %6: any
// CHK-NEXT:  %8 = UnaryIncInst (:number|bigint) %7: number|bigint
// CHK-NEXT:  %9 = HasStaticShapeInst (:boolean) %4: any, {x: any}: null [ann#3]
// CHK-NEXT:        StorePropertyLooseInst %8: number|bigint, %4: any, "x": string
// CHK-NEXT:        TrySetStaticShapeInst %4: any, {x: any}: null [ann#16]
// CHK-NEXT:  %12 = HasStaticShapeInst (:boolean) %4: any, {x: any}: null [ann#16]
// CHK-NEXT:        ReturnInst undefined: undefined
// CHK-NEXT:function_end

// CHK:scope %VS6 [obj: any]

// CHK:function methodLoad(obj: any): any
// CHK-NEXT:%BB0:
// CHK-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// CHK-NEXT:  %1 = CreateScopeInst (:environment) %VS6: any, %0: environment
// CHK-NEXT:  %2 = LoadParamInst (:any) %obj: any
// CHK-NEXT:       StoreFrameInst %1: environment, %2: any, [%VS6.obj]: any
// CHK-NEXT:  %4 = LoadFrameInst (:any) %1: environment, [%VS6.obj]: any
// CHK-NEXT:  %5 = HasStaticShapeInst (:boolean) %4: any, {m: any}: null [ann#4]
// CHK-NEXT:  %6 = LoadPropertyInst (:any) %4: any, "m": string
// CHK-NEXT:  %7 = CallInst (:any) %6: any, empty: any, false: boolean, empty: any, undefined: undefined, %4: any
// CHK-NEXT:       ReturnInst %7: any
// CHK-NEXT:function_end

// CHK:scope %VS7 [cond: any, a: any, b: any]

// CHK:function ternaryLoad(cond: any, a: any, b: any): any
// CHK-NEXT:%BB0:
// CHK-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// CHK-NEXT:  %1 = CreateScopeInst (:environment) %VS7: any, %0: environment
// CHK-NEXT:  %2 = LoadParamInst (:any) %cond: any
// CHK-NEXT:       StoreFrameInst %1: environment, %2: any, [%VS7.cond]: any
// CHK-NEXT:  %4 = LoadParamInst (:any) %a: any
// CHK-NEXT:       StoreFrameInst %1: environment, %4: any, [%VS7.a]: any
// CHK-NEXT:  %6 = LoadParamInst (:any) %b: any
// CHK-NEXT:       StoreFrameInst %1: environment, %6: any, [%VS7.b]: any
// CHK-NEXT:  %8 = LoadFrameInst (:any) %1: environment, [%VS7.cond]: any
// CHK-NEXT:       CondBranchInst %8: any, %BB2, %BB1
// CHK-NEXT:%BB1:
// CHK-NEXT:  %10 = LoadFrameInst (:any) %1: environment, [%VS7.b]: any
// CHK-NEXT:        BranchInst %BB3
// CHK-NEXT:%BB2:
// CHK-NEXT:  %12 = LoadFrameInst (:any) %1: environment, [%VS7.a]: any
// CHK-NEXT:        BranchInst %BB3
// CHK-NEXT:%BB3:
// CHK-NEXT:  %14 = PhiInst (:any) %12: any, %BB2, %10: any, %BB1
// CHK-NEXT:  %15 = HasStaticShapeInst (:boolean) %14: any, {x: any}: null [ann#5]
// CHK-NEXT:  %16 = LoadPropertyInst (:any) %14: any, "x": string
// CHK-NEXT:        ReturnInst %16: any
// CHK-NEXT:function_end

// CHK:scope %VS8 [obj: any]

// CHK:function directLoad(obj: any): any
// CHK-NEXT:%BB0:
// CHK-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// CHK-NEXT:  %1 = CreateScopeInst (:environment) %VS8: any, %0: environment
// CHK-NEXT:  %2 = LoadParamInst (:any) %obj: any
// CHK-NEXT:       StoreFrameInst %1: environment, %2: any, [%VS8.obj]: any
// CHK-NEXT:  %4 = LoadFrameInst (:any) %1: environment, [%VS8.obj]: any
// CHK-NEXT:  %5 = HasStaticShapeInst (:boolean) %4: any, {x: any}: null [ann#6]
// CHK-NEXT:  %6 = LoadPropertyInst (:any) %4: any, "x": string
// CHK-NEXT:       ReturnInst %6: any
// CHK-NEXT:function_end

// CHK:scope %VS9 [obj: any]

// CHK:function logicalStore(obj: any): any
// CHK-NEXT:%BB0:
// CHK-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// CHK-NEXT:  %1 = CreateScopeInst (:environment) %VS9: any, %0: environment
// CHK-NEXT:  %2 = LoadParamInst (:any) %obj: any
// CHK-NEXT:       StoreFrameInst %1: environment, %2: any, [%VS9.obj]: any
// CHK-NEXT:  %4 = LoadFrameInst (:any) %1: environment, [%VS9.obj]: any
// CHK-NEXT:  %5 = HasStaticShapeInst (:boolean) %4: any, {x: any}: null [ann#7]
// CHK-NEXT:  %6 = LoadPropertyInst (:any) %4: any, "x": string
// CHK-NEXT:       CondBranchInst %6: any, %BB2, %BB1
// CHK-NEXT:%BB1:
// CHK-NEXT:  %8 = LoadPropertyInst (:any) globalObject: object, "sideEffect": string
// CHK-NEXT:  %9 = CallInst (:any) %8: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined
// CHK-NEXT:  %10 = HasStaticShapeInst (:boolean) %4: any, {x: any}: null [ann#7]
// CHK-NEXT:        StorePropertyLooseInst %9: any, %4: any, "x": string
// CHK-NEXT:        TrySetStaticShapeInst %4: any, {x: any}: null [ann#17]
// CHK-NEXT:  %13 = HasStaticShapeInst (:boolean) %4: any, {x: any}: null [ann#17]
// CHK-NEXT:        BranchInst %BB2
// CHK-NEXT:%BB2:
// CHK-NEXT:  %15 = PhiInst (:any) %6: any, %BB0, %9: any, %BB1
// CHK-NEXT:        ReturnInst undefined: undefined
// CHK-NEXT:function_end

// CHK:scope %VS10 [obj: any, key: any]

// CHK:function optionalLoad(obj: any, key: any): any
// CHK-NEXT:%BB0:
// CHK-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// CHK-NEXT:  %1 = CreateScopeInst (:environment) %VS10: any, %0: environment
// CHK-NEXT:  %2 = LoadParamInst (:any) %obj: any
// CHK-NEXT:       StoreFrameInst %1: environment, %2: any, [%VS10.obj]: any
// CHK-NEXT:  %4 = LoadParamInst (:any) %key: any
// CHK-NEXT:       StoreFrameInst %1: environment, %4: any, [%VS10.key]: any
// CHK-NEXT:  %6 = LoadFrameInst (:any) %1: environment, [%VS10.obj]: any
// CHK-NEXT:  %7 = BinaryEqualInst (:any) %6: any, null: null
// CHK-NEXT:       CondBranchInst %7: any, %BB2, %BB3
// CHK-NEXT:%BB1:
// CHK-NEXT:  %9 = PhiInst (:any) undefined: undefined, %BB2, %16: any, %BB3
// CHK-NEXT:  %10 = PhiInst (:any) undefined: undefined, %BB2, %6: any, %BB3
// CHK-NEXT:        ReturnInst %9: any
// CHK-NEXT:%BB2:
// CHK-NEXT:        BranchInst %BB1
// CHK-NEXT:%BB3:
// CHK-NEXT:  %13 = LoadFrameInst (:any) %1: environment, [%VS10.key]: any
// CHK-NEXT:  %14 = CallInst (:any) %13: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined
// CHK-NEXT:  %15 = HasStaticShapeInst (:boolean) %6: any, {x: any}: null [ann#8]
// CHK-NEXT:  %16 = LoadPropertyInst (:any) %6: any, %14: any
// CHK-NEXT:        BranchInst %BB1
// CHK-NEXT:function_end

// CHK:scope %VS11 [obj: any]

// CHK:function taggedLoad(obj: any): any
// CHK-NEXT:%BB0:
// CHK-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// CHK-NEXT:  %1 = CreateScopeInst (:environment) %VS11: any, %0: environment
// CHK-NEXT:  %2 = LoadParamInst (:any) %obj: any
// CHK-NEXT:       StoreFrameInst %1: environment, %2: any, [%VS11.obj]: any
// CHK-NEXT:  %4 = GetTemplateObjectInst (:any) 0: number, true: boolean, "x": string
// CHK-NEXT:  %5 = LoadFrameInst (:any) %1: environment, [%VS11.obj]: any
// CHK-NEXT:  %6 = HasStaticShapeInst (:boolean) %5: any, {m: any}: null [ann#9]
// CHK-NEXT:  %7 = LoadPropertyInst (:any) %5: any, "m": string
// CHK-NEXT:  %8 = CallInst (:any) %7: any, empty: any, false: boolean, empty: any, undefined: undefined, %5: any, %4: any
// CHK-NEXT:       ReturnInst %8: any
// CHK-NEXT:function_end

// CHK:scope %VS12 [obj: any]

// CHK:function deleteMember(obj: any): any
// CHK-NEXT:%BB0:
// CHK-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// CHK-NEXT:  %1 = CreateScopeInst (:environment) %VS12: any, %0: environment
// CHK-NEXT:  %2 = LoadParamInst (:any) %obj: any
// CHK-NEXT:       StoreFrameInst %1: environment, %2: any, [%VS12.obj]: any
// CHK-NEXT:  %4 = LoadFrameInst (:any) %1: environment, [%VS12.obj]: any
// CHK-NEXT:  %5 = HasStaticShapeInst (:boolean) %4: any, {x: any}: null [ann#11]
// CHK-NEXT:  %6 = DeletePropertyLooseInst (:any) %4: any, "x": string
// CHK-NEXT:       ReturnInst %6: any
// CHK-NEXT:function_end

// CHK:scope %VS13 [obj: any]

// CHK:function deleteNestedOptional(obj: any): any
// CHK-NEXT:%BB0:
// CHK-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// CHK-NEXT:  %1 = CreateScopeInst (:environment) %VS13: any, %0: environment
// CHK-NEXT:  %2 = LoadParamInst (:any) %obj: any
// CHK-NEXT:       StoreFrameInst %1: environment, %2: any, [%VS13.obj]: any
// CHK-NEXT:  %4 = LoadFrameInst (:any) %1: environment, [%VS13.obj]: any
// CHK-NEXT:  %5 = BinaryEqualInst (:any) %4: any, null: null
// CHK-NEXT:       CondBranchInst %5: any, %BB2, %BB3
// CHK-NEXT:%BB1:
// CHK-NEXT:  %7 = PhiInst (:any) undefined: undefined, %BB2, %13: any, %BB3
// CHK-NEXT:  %8 = PhiInst (:any) undefined: undefined, %BB2, %11: any, %BB3
// CHK-NEXT:       ReturnInst %7: any
// CHK-NEXT:%BB2:
// CHK-NEXT:        BranchInst %BB1
// CHK-NEXT:%BB3:
// CHK-NEXT:  %11 = LoadPropertyInst (:any) %4: any, "x": string
// CHK-NEXT:  %12 = HasStaticShapeInst (:boolean) %11: any, {x: any}: null [ann#12]
// CHK-NEXT:  %13 = DeletePropertyLooseInst (:any) %11: any, "y": string
// CHK-NEXT:        BranchInst %BB1
// CHK-NEXT:function_end

// CHK:scope %VS14 []

// CHK:function <instance_members_initializer:PrivateBox>(): undefined
// CHK-NEXT:%BB0:
// CHK-NEXT:  %0 = LoadParamInst (:any) %<this>: any
// CHK-NEXT:  %1 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// CHK-NEXT:  %2 = CreateScopeInst (:environment) %VS14: any, %1: environment
// CHK-NEXT:  %3 = LoadFrameInst (:privateName) %1: environment, [%VS0.#x]: privateName
// CHK-NEXT:  %4 = BinaryPrivateInInst (:any) %3: privateName, %0: any
// CHK-NEXT:       CondBranchInst %4: any, %BB2, %BB1
// CHK-NEXT:%BB1:
// CHK-NEXT:       AddOwnPrivateFieldInst undefined: undefined, %0: any, %3: privateName
// CHK-NEXT:       ReturnInst undefined: undefined
// CHK-NEXT:%BB2:
// CHK-NEXT:       ThrowTypeErrorInst "Cannot initialize private field twice.": string
// CHK-NEXT:function_end

// CHK:scope %VS15 [this: object]

// CHK:base constructor PrivateBox(): object
// CHK-NEXT:%BB0:
// CHK-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// CHK-NEXT:  %1 = CreateScopeInst (:environment) %VS15: any, %0: environment
// CHK-NEXT:  %2 = GetNewTargetInst (:object) %new.target: object
// CHK-NEXT:  %3 = LoadPropertyInst (:any) %2: object, "prototype": string
// CHK-NEXT:  %4 = AllocObjectLiteralInst (:object) %3: any
// CHK-NEXT:       StoreFrameInst %1: environment, %4: object, [%VS15.this]: object
// CHK-NEXT:  %6 = LoadFrameInst (:object) %0: environment, [%VS0.<instElemInitFunc:PrivateBox>]: object
// CHK-NEXT:  %7 = LoadFrameInst (:object) %1: environment, [%VS15.this]: object
// CHK-NEXT:  %8 = CallInst (:undefined) %6: object, empty: any, true: boolean, empty: any, undefined: undefined, %7: object
// CHK-NEXT:  %9 = LoadFrameInst (:object) %1: environment, [%VS15.this]: object
// CHK-NEXT:        ReturnInst %9: object
// CHK-NEXT:function_end

// CHK:scope %VS16 [obj: any]

// CHK:method read(obj: any): any
// CHK-NEXT:%BB0:
// CHK-NEXT:  %0 = GetParentScopeInst (:environment) %VS0: any, %parentScope: environment
// CHK-NEXT:  %1 = CreateScopeInst (:environment) %VS16: any, %0: environment
// CHK-NEXT:  %2 = LoadParamInst (:any) %obj: any
// CHK-NEXT:       StoreFrameInst %1: environment, %2: any, [%VS16.obj]: any
// CHK-NEXT:  %4 = LoadFrameInst (:any) %1: environment, [%VS16.obj]: any
// CHK-NEXT:  %5 = LoadFrameInst (:privateName) %0: environment, [%VS0.#x]: privateName
// CHK-NEXT:  %6 = HasStaticShapeInst (:boolean) %4: any, {x: any}: null [ann#10]
// CHK-NEXT:  %7 = LoadOwnPrivateFieldInst (:any) %4: any, %5: privateName
// CHK-NEXT:       ReturnInst %7: any
// CHK-NEXT:function_end
