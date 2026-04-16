/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %hermes -type-annotation-file=%annotation_file -O -gc-max-heap=1M %s
// RUN: %hermes -type-annotation-file=%annotation_file -O -gc-max-heap=2M %s
// RUN: %hermes -type-annotation-file=%annotation_file -O -gc-max-heap=2Mib %s
// RUN: %hermes -type-annotation-file=%annotation_file -O -gc-max-heap=2Kib %s
// RUN: %hermes -type-annotation-file=%annotation_file -O -gc-max-heap=2KiB %s
// RUN: %hermes -type-annotation-file=%annotation_file -O -gc-max-heap=2KB %s
// RUN: %hermes -type-annotation-file=%annotation_file -O -gc-max-heap=2G %s
// RUN: ! %hermes -type-annotation-file=%annotation_file -O -gc-max-heap=2Mg %s
// RUN: ! %hermes -type-annotation-file=%annotation_file -O -gc-max-heap=2Miib %s
// RUN: ! %hermes -type-annotation-file=%annotation_file -O -gc-max-heap=2i %s
// RUN: ! %hermes -type-annotation-file=%annotation_file -O -gc-max-heap=2Ki %s
