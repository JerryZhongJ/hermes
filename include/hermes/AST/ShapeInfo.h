/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#ifndef HERMES_AST_SHAPEINFO_H
#define HERMES_AST_SHAPEINFO_H

#include "hermes/AST/ShapeDefinition.h"
#include "hermes/Parser/PreParser.h" // SMLocInfo
#include "llvh/ADT/DenseMap.h"
#include "llvh/ADT/StringMap.h"
#include "llvh/ADT/StringRef.h"
#include "llvh/Support/SMLoc.h"

#include <memory>
#include <string>
#include <vector>

namespace hermes {

class Context;

/// DenseMapInfo for SMRange (复用 SMLocInfo)
struct SMRangeInfo {
  static inline llvh::SMRange getEmptyKey() {
    return llvh::SMRange(
        parser::SMLocInfo::getEmptyKey(), parser::SMLocInfo::getEmptyKey());
  }

  static inline llvh::SMRange getTombstoneKey() {
    return llvh::SMRange(
        parser::SMLocInfo::getTombstoneKey(),
        parser::SMLocInfo::getTombstoneKey());
  }

  static inline bool isEqual(const llvh::SMRange &a, const llvh::SMRange &b) {
    return a.Start == b.Start && a.End == b.End;
  }

  static unsigned getHashValue(const llvh::SMRange &val) {
    return llvh::hash_combine(
        parser::SMLocInfo::getHashValue(val.Start),
        parser::SMLocInfo::getHashValue(val.End));
  }
};

struct ShapeAnnotation {
  enum class TargetKind { AllocObject, Parameter, Call, LoadProperty };

  TargetKind targetKind;
  uint32_t shapeId;

  ShapeAnnotation(TargetKind kind, uint32_t sid)
      : targetKind(kind), shapeId(sid) {}
};

/// Shape 信息管理器
class ShapeInfoManager {
  std::vector<std::unique_ptr<ShapeDefinition>> shapeDefinitions_;

  llvh::DenseMap<llvh::SMRange, ShapeAnnotation, SMRangeInfo> annotationMap_;

  Context *context_;

 public:
  explicit ShapeInfoManager(Context *ctx) : context_(ctx) {}

  /// \return true 表示成功，false 表示失败
  bool loadFromJSON(const std::string &jsonPath);

  /// \param range 源代码范围
  /// \return 找到的标注，如果没有返回 nullptr
  const ShapeAnnotation *getAnnotationAt(llvh::SMRange range) const;

  const std::vector<std::unique_ptr<ShapeDefinition>> &getShapeDefinitions()
      const {
    return shapeDefinitions_;
  }

  /// \param shapeId Shape 索引
  /// \return Shape 定义指针，如果索引无效返回 nullptr
  const ShapeDefinition *getShapeDefinition(uint32_t shapeId) const {
    if (shapeId < shapeDefinitions_.size()) {
      return shapeDefinitions_[shapeId].get();
    }
    return nullptr;
  }
};

} // namespace hermes

#endif // HERMES_AST_SHAPEINFO_H
