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
#include "llvh/ADT/StringMap.h"
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

/// Entry in the shape assignments array.
struct ShapePromotionEntry {
  /// Source range of the expression that produces the object.
  llvh::SMRange objectRange;
  /// Name of the typed shape in the JSON "shapes" object.
  std::string shapeName;
};

/// Entry in the shape hints array.
struct ShapeGuardEntry {
  /// Source range of the expression that produces the object to hint.
  llvh::SMRange objectRange;
  /// Name of the typed shape in the JSON "shapes" object.
  std::string shapeName;
  /// Index in the JSON "shape hints" array.
  unsigned annotationId;
};

/// Stores type hints, shape hints, and shape assignments loaded from a JSON
/// file.
class Annotations {
 private:
  /// Type hint map: SMRange -> type strings (e.g., ["number", "string"]).
  llvh::DenseMap<llvh::SMRange, std::vector<std::string>, SMRangeInfo>
      typeGuards_;

  /// Type hint index map: SMRange -> index in JSON "type hints" array.
  llvh::DenseMap<llvh::SMRange, unsigned, SMRangeInfo> typeGuardIds_;

  /// Track which type hint IDs have been matched during IRGen.
  mutable llvh::DenseSet<unsigned> matchedTypeGuardIds_;

  /// Typed shape definitions loaded from JSON, keyed by shape name.
  llvh::StringMap<TypedShapeDefinition> shapeDefs_;

  /// Shape hint map: hint-after range -> hint entries. A single annotation can
  /// describe one object-to-shape hint with multiple hint-after ranges.
  llvh::DenseMap<
      llvh::SMRange,
      llvh::SmallVector<ShapeGuardEntry, 2>,
      SMRangeInfo>
      shapeGuards_;

  /// Track which shape hint IDs have been matched.
  mutable llvh::DenseSet<unsigned> matchedShapeGuardIds_;

  /// Shape assignment map: assign-after range -> assignment entry.
  llvh::DenseMap<llvh::SMRange, ShapePromotionEntry, SMRangeInfo>
      shapePromotions_;

 public:
  /// Load type hints, shape hints, and shape assignments from a JSON file.
  bool loadFromFile(llvh::StringRef jsonPath, SourceErrorManager &sm);

  /// Query the type hint strings for a given source range.
  llvh::Optional<std::vector<std::string>> getTypeGuard(
      llvh::SMRange range) const;

  /// Query the type hint index for a given source range.
  /// Returns -1 if not found.
  int getTypeGuardId(llvh::SMRange range) const;

  /// Check if there are any type hints.
  bool empty() const {
    return typeGuards_.empty();
  }

  /// Get all type hints (for debugging).
  const llvh::DenseMap<llvh::SMRange, std::vector<std::string>, SMRangeInfo> &
  getAnnotations() const {
    return typeGuards_;
  }

  /// Report type hints that were loaded but never matched by any IR
  /// instruction during IRGen.
  void reportUnmatched() const;

  /// Parse a type name string to a Type object.
  static llvh::Optional<Type> parseTypeName(llvh::StringRef typeName);

  /// Parse multiple type name strings to a union Type object.
  static llvh::Optional<Type> parseTypeNames(
      const std::vector<std::string> &typeNames);

  /// Return all typed shape definitions loaded from JSON.
  const llvh::StringMap<TypedShapeDefinition> &getShapeDefs() const {
    return shapeDefs_;
  }

  /// Query the shape hints for a given hint-after source range.
  void getShapeGuards(
      llvh::SMRange range,
      llvh::SmallVectorImpl<ShapeGuardEntry> &guards) const;

  /// Query the shape assignment for a given assign-after source range.
  /// Returns None if not found.
  llvh::Optional<ShapePromotionEntry> getShapePromotion(
      llvh::SMRange promoteRange) const;

  /// Return all expression ranges referenced by shape annotations.
  llvh::SmallVector<llvh::SMRange, 4> getShapeAnnotationObjectRanges() const;
};

} // namespace hermes

#endif // HERMES_IRGEN_ANNOTATIONLOADER_H
