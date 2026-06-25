/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %shermes -O -dump-lir -annotation-file=%S/typed-shape-annotations.json %s | %FileCheck %s --check-prefix=LIR
// RUN: %shermes -O -emit-c -o - -annotation-file=%S/typed-shape-annotations.json %s | %FileCheck %s --check-prefix=C

var o = {x:1, y:2};
print(o.x);

// LIR: TrySetTypedShapeInst
// LIR-SAME: {x: number, y: number}
// LIR: HasTypedShapeInst
// LIR-SAME: {x: number, y: number}
// LIR: PrLoadInst

// C: _sh_ljs_try_set_typed_shape(shr,
// C-SAME: shUnit, 0
// C: _sh_ljs_has_typed_shape(shr,
// C-SAME: shUnit, 0
// C: static const SHTypedShapeProp s_typed_shape_props[] = {
// C: { .name_index = {{[0-9]+}}, .type = 1 },
// C: { .name_index = {{[0-9]+}}, .type = 1 },
// C: static const SHTypedShapeTableEntry s_typed_shape_table[] = {
// C: { .prop_offset = 0, .num_props = 2 },
// C: SHCompressedPointer typed_shape_class_cache[1];
// C: .typed_shape_table_count = 1
