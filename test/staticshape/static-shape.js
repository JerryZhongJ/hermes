/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %shermes -O -dump-lir -annotation-file=%S/static-shape.json %s | %FileCheckOrRegen %s --check-prefix=LIR --match-full-lines
// RUN: %shermes -O -emit-c -o - -annotation-file=%S/static-shape.json %s | %FileCheck %s --check-prefix=C

var o = {x:1, y:2};
print(o.x);

// C: _sh_ljs_try_set_static_shape(shr,
// C-SAME: shUnit, 0
// C: _sh_ljs_has_static_shape(shr,
// C-SAME: shUnit, 0
// C: static const SHStaticShapeProp s_static_shape_props[] = {
// C: { .name_index = {{[0-9]+}}, .type = 1, .kind = 0, .attrs = 7 },
// C: { .name_index = {{[0-9]+}}, .type = 1, .kind = 0, .attrs = 7 },
// C: static const SHStaticShapeTableEntry s_static_shape_table[] = {
// C: { .prop_offset = 0, .num_props = 2, .typed = 1 },
// C: SHCompressedPointer static_shape_class_cache[1];
// C: .static_shape_table_count = 1

// Auto-generated content below. Please do not modify manually.

// LIR:function global(): any
// LIR-NEXT:%BB0:
// LIR-NEXT:       DeclareGlobalVarInst "o": string
// LIR-NEXT:  %1 = LIRAllocObjectFromBufferInst (:object) empty: any, "x": string, 1: number, "y": string, 2: number
// LIR-NEXT:  %2 = LIRGetGlobalObjectInst (:object)
// LIR-NEXT:       StorePropertyLooseInst %1: object, %2: object, "o": string
// LIR-NEXT:       TrySetStaticShapeInst %1: object, {x: number, y: number}: null [ann#1]
// LIR-NEXT:  %5 = TryLoadGlobalPropertyInst (:any) %2: object, "print": string
// LIR-NEXT:  %6 = LoadPropertyInst (:any) %2: object, "o": string
// LIR-NEXT:  %7 = HasStaticShapeInst (:boolean) %6: any, {x: number, y: number}: null [ann#0]
// LIR-NEXT:       CondBranchInst %7: boolean, %BB1, %BB2
// LIR-NEXT:%BB1:
// LIR-NEXT:  %9 = PrLoadInst (:number) %6: any, 0: number, "x": string
// LIR-NEXT:  %10 = LIRLoadConstInst (:undefined) undefined: undefined
// LIR-NEXT:  %11 = CallInst (:any) %5: any, empty: any, false: boolean, empty: any, %10: undefined, %10: undefined, %9: number
// LIR-NEXT:        ReturnInst %11: any
// LIR-NEXT:%BB2:
// LIR-NEXT:  %13 = LoadPropertyInst (:any) %6: any, "x": string
// LIR-NEXT:  %14 = LIRLoadConstInst (:undefined) undefined: undefined
// LIR-NEXT:  %15 = CallInst (:any) %5: any, empty: any, false: boolean, empty: any, %14: undefined, %14: undefined, %13: any
// LIR-NEXT:        ReturnInst %15: any
// LIR-NEXT:function_end
