/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#ifndef HERMES_SUPPORT_STATICSHAPEPROPERTYFLAGS_H
#define HERMES_SUPPORT_STATICSHAPEPROPERTYFLAGS_H

namespace hermes {

/// JS descriptor attributes carried by a static shape property. This is a
/// semantic representation; backend/runtime code decides how to encode it.
struct StaticShapePropertyAttrs {
  bool writable = true;
  bool enumerable = true;
  bool configurable = true;
};

} // namespace hermes

#endif // HERMES_SUPPORT_STATICSHAPEPROPERTYFLAGS_H
