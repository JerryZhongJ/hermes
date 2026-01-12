/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#ifndef HERMES_AST_SHAPEDEFINITION_H
#define HERMES_AST_SHAPEDEFINITION_H

#include "hermes/Support/StringTable.h"
#include "llvh/ADT/StringRef.h"

#include <string>
#include <vector>

namespace hermes {

struct ShapePropertyDef {
  Identifier name;
  uint32_t slot;

  enum class Kind { Primitive, ShapeRef };
  Kind kind;

  std::string typeString; // kind == Primitive: "number", "string", etc.
  uint32_t shapeId; // kind == ShapeRef: 引用的 Shape 索引

  ShapePropertyDef(Identifier n, llvh::StringRef typeStr, uint32_t s)
      : name(n),
        slot(s),
        kind(Kind::Primitive),
        typeString(typeStr.str()),
        shapeId(0) {}

  ShapePropertyDef(Identifier n, uint32_t refId, uint32_t s)
      : name(n), slot(s), kind(Kind::ShapeRef), typeString(), shapeId(refId) {}
};

struct ShapeDefinition {
  std::vector<ShapePropertyDef> properties;

  ShapeDefinition() = default;
};

} // namespace hermes

#endif // HERMES_AST_SHAPEDEFINITION_H
