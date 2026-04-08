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
  /// Type annotation map: SMRange -> type string (e.g., "number", "string").
  llvh::DenseMap<llvh::SMRange, std::string, SMRangeInfo> annotations_;

  /// Annotation index map: SMRange -> index in JSON annotations array.
  llvh::DenseMap<llvh::SMRange, unsigned, SMRangeInfo> annotationIds_;

  /// Track which annotation IDs have been matched during IRGen.
  mutable llvh::DenseSet<unsigned> matchedIds_;

 public:
  /// Load type annotations from a JSON file.
  bool loadFromFile(llvh::StringRef jsonPath, SourceErrorManager &sm);

  /// Query the type annotation string for a given source range.
  llvh::Optional<std::string> getAnnotation(llvh::SMRange range) const;

  /// Query the annotation index for a given source range.
  /// Returns -1 if not found.
  int getAnnotationId(llvh::SMRange range) const;

  /// Check if there are any annotations.
  bool empty() const {
    return annotations_.empty();
  }

  /// Get all annotations (for debugging).
  const llvh::DenseMap<llvh::SMRange, std::string, SMRangeInfo> &
  getAnnotations() const {
    return annotations_;
  }

  /// Report annotations that were loaded but never matched by any IR
  /// instruction during IRGen.
  void reportUnmatched() const;

  /// Parse a type name string to a Type object.
  static llvh::Optional<Type> parseTypeName(llvh::StringRef typeName);
};

} // namespace hermes

#endif // HERMES_IRGEN_TYPEANNOTATIONLOADER_H
