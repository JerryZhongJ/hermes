/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %shermes -O -emit-c -o - -annotation-file=%S/untyped-static-shape.json %s | %FileCheck %s --check-prefix=C
// RUN: %shermes -O -exec -annotation-file=%S/untyped-static-shape.json %s
// A shape whose properties are all "any" builds an untyped hidden class.
var o = {x:1, y:2};
print(o.x);

// C: static const SHStaticShapeProp s_static_shape_props[] = {
// C: { .name_index = {{[0-9]+}}, .type = 15, .kind = 0, .attrs = 7, .target_func = NULL },
// C: { .name_index = {{[0-9]+}}, .type = 15, .kind = 0, .attrs = 7, .target_func = NULL },
// C: static const SHStaticShapeTableEntry s_static_shape_table[] = {
// C: { .prop_offset = 0, .num_props = 2, .typed = 0 },
// C: SHCompressedPointer static_shape_class_cache[1];
// C: .static_shape_table_count = 1
