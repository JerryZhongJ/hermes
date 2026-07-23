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
#include "hermes/Support/StaticShapePropertyFlags.h"

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

/// A single property in a static shape definition (before Type resolution).
struct StaticShapePropertyDefinition {
  std::string name;
  std::vector<std::string> typeNames;
  /// True if this is an accessor (getter/setter) property. Accessor properties
  /// are always treated as type "any" — the getter/setter can produce/accept
  /// anything, so a static value type is meaningless.
  bool accessor = false;
  /// JS descriptor attributes. JSON defaults them to on and lists only attrs to
  /// turn off; no VM bit encoding is implied here.
  StaticShapePropertyAttrs attrs;
  /// For closure-typed properties: source range of the target function
  /// definition (loaded from the JSON "target function" field, same format as
  /// target range). Invalid for non-closure properties. Resolved to a
  /// Function* during IRGen (ESTreeIRGen::applyClosureTarget) by matching
  /// Function::getSourceRange.
  llvh::SMRange targetFuncRange;
};

/// Static shape definition loaded from JSON. Uses type name strings
/// instead of resolved Type objects to avoid depending on IR.
struct StaticShapeDefinition {
  llvh::SmallVector<StaticShapePropertyDefinition, 8> properties;
};

/// Entry in the shape bindings array.
struct ShapeBindingEntry {
  /// Source range of the expression that produces the object.
  llvh::SMRange objectRange;
  /// Name of the static shape in the JSON "static shapes" object.
  std::string shapeName;
  /// Globally-unique annotation id; tags the Has guard emitted after the
  /// TrySet so the binding is tracked like a shape hint.
  unsigned annotationId;
};

/// Entry in the shape hints array.
struct ShapeGuardEntry {
  /// Source range of the expression that produces the object to hint.
  llvh::SMRange objectRange;
  /// Name of the static shape in the JSON "static shapes" object.
  std::string shapeName;
  /// Optional: static shape name of the object's direct prototype. Empty =
  /// none. A refinement of "shape" (shape-guard only); when set, IRGen emits
  /// getparent + HasStaticShape(parent, P).
  std::string prototypeShapeName;
  /// Globally-unique annotation id for the object's own shape guard.
  unsigned annotationId;
  /// Annotation id for the prototype guard; distinct from annotationId so the
  /// two guards report separately. Equals annotationId when no prototype.
  unsigned prototypeAnnotationId;
};

/// Descriptor for a single annotation (type hint / shape hint / shape
/// binding), indexed by its globally-unique annotation id. Built at load time
/// so guard instrumentation (SH.cpp) can report each annotation's kind and
/// detail without re-encoding or reaching back into the loader's maps.
struct AnnotationDescriptor {
  enum Kind { Type, ShapeHint, PrototypeShapeHint, ShapeBinding } kind;
  /// Human-readable detail: type names joined by '|' (e.g. "number|string"),
  /// or the shape name (e.g. "XNumber").
  std::string detail;
  /// Source range (1-based, end column EXCLUSIVE — matches annotation JSON)
  /// of the annotated expression, captured at load time.
  unsigned line = 0;
  unsigned col = 0;
  unsigned endLine = 0;
  unsigned endCol = 0;
  /// True when a shape guard/binding carries a "guard after"/"bind after"
  /// point. In that case the match key is the after range (not the target
  /// range), so reportMatchStatus locates the unmatched warning at
  /// insertLine/insertCol instead of the target range.
  bool hasAfterPoint = false;
  /// Report location: start of the after range when hasAfterPoint, else the
  /// target range start (== line/col).
  unsigned insertLine = 0;
  unsigned insertCol = 0;
};

/// Display label for an annotation kind — matches the prompt/JSON terminology
/// ("type guard", "shape guard", "shape binding").
inline llvh::StringRef annotationKindLabel(AnnotationDescriptor::Kind k) {
  switch (k) {
    case AnnotationDescriptor::Type:
      return "type guard";
    case AnnotationDescriptor::ShapeHint:
      return "shape guard";
    case AnnotationDescriptor::PrototypeShapeHint:
      return "prototype shape guard";
    case AnnotationDescriptor::ShapeBinding:
      return "shape binding";
  }
  return "?";
}

/// Stores type hints, shape hints, and shape bindings loaded from a JSON file.
/// Annotation ids are globally unique across all three categories.
class Annotations {
 private:
  /// Type hint map: SMRange -> type strings (e.g., ["number", "string"]).
  llvh::DenseMap<llvh::SMRange, std::vector<std::string>, SMRangeInfo>
      typeGuards_;

  /// Type hint index map: SMRange -> globally-unique annotation id.
  llvh::DenseMap<llvh::SMRange, unsigned, SMRangeInfo> typeGuardIds_;

  /// Static shape definitions loaded from JSON, keyed by shape name.
  llvh::StringMap<StaticShapeDefinition> shapeDefs_;

  /// Shape hint map: guard-after (or target) range -> hint entries. The map
  /// key is where the HasStaticShape check is inserted; the checked object is
  /// always the target expression (ShapeGuardEntry.objectRange).
  llvh::DenseMap<
      llvh::SMRange,
      llvh::SmallVector<ShapeGuardEntry, 2>,
      SMRangeInfo>
      shapeGuards_;

  /// Shape binding map: bind-after (or target) range -> binding entry.
  llvh::DenseMap<llvh::SMRange, ShapeBindingEntry, SMRangeInfo>
      shapeBindings_;

  /// Global counter assigning globally-unique annotation ids across all
  /// categories (type hints, shape hints, shape bindings). Replaces the old
  /// per-category JSON array index, which could collide across categories.
  unsigned nextAnnotationId_ = 0;

  /// Per-annotation descriptors, indexed by globally-unique id.
  std::vector<AnnotationDescriptor> annotationDescriptors_;

  /// Globally-unique annotation ids that were matched to an IR instruction
  /// during IRGen (across all categories). Used by reportMatchStatus().
  mutable llvh::DenseSet<unsigned> matchedAnnotationIds_;

 public:
  /// Load type hints, shape hints, and shape bindings from a JSON file.
  bool loadFromFile(llvh::StringRef jsonPath, SourceErrorManager &sm);

  /// Query the type hint strings for a given source range.
  llvh::Optional<std::vector<std::string>> getTypeGuard(
      llvh::SMRange range) const;

  /// Query the type hint index for a given source range.
  /// Returns -1 if not found.
  int getTypeGuardId(llvh::SMRange range) const;

  /// Total number of annotations loaded (== one past the largest annotation
  /// id). Used by guard instrumentation to size the counter array.
  unsigned getAnnotationCount() const {
    return annotationDescriptors_.size();
  }

  /// Look up an annotation's descriptor by its globally-unique id.
  /// Returns nullptr if \p id is out of range.
  const AnnotationDescriptor *getAnnotationDescriptor(unsigned id) const {
    return id < annotationDescriptors_.size() ? &annotationDescriptors_[id]
                                              : nullptr;
  }

  /// Check if there are any type hints.
  bool empty() const {
    return typeGuards_.empty();
  }

  /// Get all type hints (for debugging).
  const llvh::DenseMap<llvh::SMRange, std::vector<std::string>, SMRangeInfo> &
  getAnnotations() const {
    return typeGuards_;
  }

  /// After IRGen, warn (via \p sm) about every loaded annotation that no IR
  /// instruction consumed (unmatched — its target range didn't hit a target
  /// AST node). Goes through the compiler's standard warning path.
  void reportMatchStatus(SourceErrorManager &sm) const;

  /// Parse a type name string to a Type object.
  static llvh::Optional<Type> parseTypeName(llvh::StringRef typeName);

  /// Parse multiple type name strings to a union Type object. When \p
  /// unsupported is non-null, every name parseTypeName cannot resolve is
  /// appended to it (joined by ", "); the result is None if any name is bad,
  /// so callers can report exactly which names failed.
  static llvh::Optional<Type> parseTypeNames(
      const std::vector<std::string> &typeNames,
      std::string *unsupported = nullptr);

  /// Return all static shape definitions loaded from JSON.
  const llvh::StringMap<StaticShapeDefinition> &getShapeDefs() const {
    return shapeDefs_;
  }

  /// Query the shape hints whose insertion (guard-after, or target) range
  /// equals \p range.
  void getShapeGuards(
      llvh::SMRange range,
      llvh::SmallVectorImpl<ShapeGuardEntry> &guards) const;

  /// Query the shape binding whose insertion (bind-after, or target) range
  /// equals \p range. Returns None if not found.
  llvh::Optional<ShapeBindingEntry> getShapeBinding(
      llvh::SMRange bindRange) const;

  /// Return all expression ranges referenced by shape annotations.
  llvh::SmallVector<llvh::SMRange, 4> getShapeAnnotationObjectRanges() const;
};

} // namespace hermes

#endif // HERMES_IRGEN_ANNOTATIONLOADER_H
