/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#ifndef HERMES_IRGEN_TYPEANNOTATIONLOADER_H
#define HERMES_IRGEN_TYPEANNOTATIONLOADER_H

#include "hermes/Parser/PreParser.h"
#include "hermes/Support/SourceErrorManager.h"

#include "llvh/ADT/DenseMap.h"
#include "llvh/ADT/Optional.h"
#include "llvh/ADT/StringRef.h"
#include "llvh/Support/SMLoc.h"

#include <string>

namespace hermes {

// Forward declaration
class Type;

/// Allow using \p SMRange in \p llvh::DenseMaps, reusing SMLocInfo.
struct SMRangeInfo {
  static inline llvh::SMRange getEmptyKey() {
    llvh::SMLoc emptyLoc = parser::SMLocInfo::getEmptyKey();
    return llvh::SMRange(emptyLoc, emptyLoc);
  }

  static inline llvh::SMRange getTombstoneKey() {
    llvh::SMLoc tombstoneLoc = parser::SMLocInfo::getTombstoneKey();
    return llvh::SMRange(tombstoneLoc, tombstoneLoc);
  }

  static inline bool isEqual(const llvh::SMRange &a, const llvh::SMRange &b) {
    return parser::SMLocInfo::isEqual(a.Start, b.Start) &&
        parser::SMLocInfo::isEqual(a.End, b.End);
  }

  static unsigned getHashValue(const llvh::SMRange &range) {
    return llvh::hash_combine(
        parser::SMLocInfo::getHashValue(range.Start),
        parser::SMLocInfo::getHashValue(range.End));
  }
};

/// Stores type annotations loaded from a JSON file.
/// Maps source code ranges (SMRange) to their annotated type strings.
class TypeAnnotations {
 private:
  /// 类型标注映射: SMRange -> type string (e.g., "number", "string")
  /// 使用SMRangeInfo作为DenseMap的KeyInfo
  llvh::DenseMap<llvh::SMRange, std::string, SMRangeInfo> annotations_;

 public:
  /// Load type annotations from a JSON file.
  /// \param jsonPath path to the JSON file containing annotations
  /// \param sm SourceErrorManager for coordinate conversion
  /// \return TypeAnnotations if successful, None otherwise
  bool loadFromFile(llvh::StringRef jsonPath, SourceErrorManager &sm);

  /// Query the type annotation string for a given source range.
  /// \param range the source range to query
  /// \return the annotated type string if found, None otherwise
  llvh::Optional<std::string> getAnnotation(llvh::SMRange range) const;

  /// Check if there are any annotations.
  bool empty() const {
    return annotations_.empty();
  }

  /// Get all annotations (for debugging).
  const llvh::DenseMap<llvh::SMRange, std::string, SMRangeInfo> &
  getAnnotations() const {
    return annotations_;
  }

  /// Parse a type name string to a Type object.
  /// \param typeName the type name string (e.g., "number", "string")
  /// \return the Type object if recognized, None otherwise
  static llvh::Optional<Type> parseTypeName(llvh::StringRef typeName);
};

} // namespace hermes

#endif // HERMES_IRGEN_TYPEANNOTATIONLOADER_H
