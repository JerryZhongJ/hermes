/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#ifndef HERMES_IRGEN_ANNOTATIONLOADER_H
#define HERMES_IRGEN_ANNOTATIONLOADER_H

#include "hermes/Parser/PreParser.h"
#include "hermes/Support/SourceErrorManager.h"

#include "llvh/ADT/DenseMap.h"
#include "llvh/ADT/DenseSet.h"
#include "llvh/ADT/Optional.h"
#include "llvh/ADT/SmallVector.h"
#include "llvh/ADT/StringRef.h"
#include "llvh/Support/SMLoc.h"

#include <string>
#include <vector>

namespace hermes {

// Forward declarations
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

/// A single property in a typed shape definition (before Type resolution).
struct TypedShapePropertyDefinition {
  std::string name;
  std::vector<std::string> typeNames;
};

/// Typed shape definition loaded from JSON. Uses type name strings
/// instead of resolved Type objects to avoid depending on IR.
struct TypedShapeDefinition {
  llvh::SmallVector<TypedShapePropertyDefinition, 8> properties;
};

/// Entry in the shape promotions array.
struct ShapePromotionEntry {
  /// Source range of the expression that produces the object.
  llvh::SMRange objectRange;
  /// Index into typedShapeDefs_.
  unsigned shapeIdx;
};

/// Stores type guards, shape guards, and shape promotions loaded from a JSON
/// file.
class Annotations {
 private:
  /// Type guard map: SMRange -> type strings (e.g., ["number", "string"]).
  llvh::DenseMap<llvh::SMRange, std::vector<std::string>, SMRangeInfo>
      typeGuards_;

  /// Type guard index map: SMRange -> index in JSON "type guards" array.
  llvh::DenseMap<llvh::SMRange, unsigned, SMRangeInfo> typeGuardIds_;

  /// Track which type guard IDs have been matched during IRGen.
  mutable llvh::DenseSet<unsigned> matchedTypeGuardIds_;

  /// Typed shape definitions loaded from JSON (type names, not Type objects).
  llvh::SmallVector<TypedShapeDefinition, 4> typedShapeDefs_;

  /// Shape guard map: SMRange -> shape index into typedShapeDefs_.
  llvh::DenseMap<llvh::SMRange, unsigned, SMRangeInfo> shapeGuards_;

  /// Track which shape guard IDs have been matched.
  mutable llvh::DenseSet<unsigned> matchedShapeGuardIds_;

  /// Shape promotion map: promote location -> promotion entry.
  llvh::DenseMap<llvh::SMRange, ShapePromotionEntry, SMRangeInfo>
      shapePromotions_;

 public:
  /// Load type guards, shape guards, and shape promotions from a JSON file.
  bool loadFromFile(llvh::StringRef jsonPath, SourceErrorManager &sm);

  /// Query the type guard strings for a given source range.
  llvh::Optional<std::vector<std::string>> getTypeGuard(
      llvh::SMRange range) const;

  /// Query the type guard index for a given source range.
  /// Returns -1 if not found.
  int getTypeGuardId(llvh::SMRange range) const;

  /// Check if there are any type guards.
  bool empty() const {
    return typeGuards_.empty();
  }

  /// Get all type guards (for debugging).
  const llvh::DenseMap<llvh::SMRange, std::vector<std::string>, SMRangeInfo> &
  getAnnotations() const {
    return typeGuards_;
  }

  /// Report type guards that were loaded but never matched by any IR
  /// instruction during IRGen.
  void reportUnmatched() const;

  /// Parse a type name string to a Type object.
  static llvh::Optional<Type> parseTypeName(llvh::StringRef typeName);

  /// Parse multiple type name strings to a union Type object.
  static llvh::Optional<Type> parseTypeNames(
      const std::vector<std::string> &typeNames);

  /// Return all typed shape definitions loaded from JSON.
  llvh::ArrayRef<TypedShapeDefinition> getTypedShapeDefs() const {
    return typedShapeDefs_;
  }

  /// Query the shape guard index for a given source range.
  /// Returns -1 if not found.
  int getShapeGuard(llvh::SMRange range) const;

  /// Query the shape promotion for a given promote-location source range.
  /// Returns None if not found.
  llvh::Optional<ShapePromotionEntry> getShapePromotion(
      llvh::SMRange promoteRange) const;

  /// Collect all object location ranges from shape promotions.
  void getShapePromotionObjectRanges(
      llvh::SmallVectorImpl<llvh::SMRange> &ranges) const {
    for (const auto &kv : shapePromotions_)
      ranges.push_back(kv.second.objectRange);
  }
};

} // namespace hermes

#endif // HERMES_IRGEN_ANNOTATIONLOADER_H
