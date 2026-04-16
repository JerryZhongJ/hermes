/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %hermes -type-annotation-file=%annotation_file -hermes-parser -dump-ra %s
// RUN: %shermes -type-annotation-file=%annotation_file -exec %s


// Make sure that we are not crashing on this one:
print("hello world")
parseInt(10)

