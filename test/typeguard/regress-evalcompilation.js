/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %shermes -type-annotation-file=%annotation_file -emit-c -o - -g %s

// This used to crash because EvalCompilationDataInst was
// passed through the compiler pipeline when -g was passed.
const MyError = function () {};
try {
  throw new MyError();
} catch {
  e instanceof '';
}
