/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %hermes -type-annotation-file=%annotation_file -O -target=HBC %s
// RUN: %hermes -type-annotation-file=%annotation_file -O -target=HBC -lazy %s
// RUN: %hermes -type-annotation-file=%annotation_file -O -target=HBC -emit-binary -out %t.hbc %s && %hermes -type-annotation-file=%annotation_file %t.hbc
// RUN: %shermes -type-annotation-file=%annotation_file -exec %s
''['']
