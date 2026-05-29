/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#include "hermes/IRGen/AnnotationLoader.h"
#include "hermes/IR/IR.h"

#include "llvh/Support/Debug.h"
#include "llvh/Support/JSON.h"
#include "llvh/Support/MemoryBuffer.h"
#include "llvh/Support/raw_ostream.h"

#define DEBUG_TYPE "annotation-loader"

namespace hermes {

namespace {

/// Extract type name strings from a JSON value that is either a single string
/// (e.g. "number") or an array of strings (e.g. ["number", "string"]).
std::vector<std::string> extractTypeStrings(const llvh::json::Value &val) {
  std::vector<std::string> result;
  if (auto *arr = val.getAsArray()) {
    for (const auto &elem : *arr) {
      if (auto s = elem.getAsString())
        result.push_back(s->str());
    }
  } else if (auto s = val.getAsString()) {
    result.push_back(s->str());
  }
  return result;
}

/// Resolve a JSON location object to an SMRange.
llvh::Optional<llvh::SMRange> resolveLocation(
    const llvh::json::Object *loc,
    SourceErrorManager &sm) {
  auto file = loc->getString("file");
  const llvh::json::Object *start = loc->getObject("start");
  const llvh::json::Object *end = loc->getObject("end");
  if (!file || !start || !end)
    return llvh::None;

  auto startLine = start->getInteger("line");
  auto startCol = start->getInteger("column");
  auto endLine = end->getInteger("line");
  auto endCol = end->getInteger("column");
  if (!startLine || !startCol || !endLine || !endCol)
    return llvh::None;

  SourceErrorManager::SourceCoords startCoords(
      2, static_cast<unsigned>(*startLine), static_cast<unsigned>(*startCol));
  SourceErrorManager::SourceCoords endCoords(
      2, static_cast<unsigned>(*endLine), static_cast<unsigned>(*endCol));

  llvh::SMLoc startLoc = sm.findSMLocFromCoords(startCoords);
  llvh::SMLoc endLoc = sm.findSMLocFromCoords(endCoords);
  if (!startLoc.isValid() || !endLoc.isValid())
    return llvh::None;

  return llvh::SMRange(startLoc, endLoc);
}

/// Load typed shape definitions from the "typed shapes" JSON array.
/// Each entry is an object with a "properties" array; each element in that
/// array is {"name": string, "type": string|[string]}. Property order in the
/// array is significant: different order means a different shape.
void loadTypedShapes(
    const llvh::json::Array &arr,
    llvh::SmallVectorImpl<TypedShapeDefinition> &defs) {
  for (unsigned i = 0, e = arr.size(); i < e; ++i) {
    const llvh::json::Object *shapeObj = arr[i].getAsObject();
    if (!shapeObj) {
      llvh::errs() << "Warning: invalid typed shape entry at index " << i
                   << "\n";
      continue;
    }
    auto *propsArr = shapeObj->getArray("properties");
    if (!propsArr) {
      llvh::errs()
          << "Warning: missing 'properties' array in typed shape entry " << i
          << "\n";
      continue;
    }
    TypedShapeDefinition def;
    for (const auto &elem : *propsArr) {
      const llvh::json::Object *propObj = elem.getAsObject();
      if (!propObj) {
        llvh::errs() << "Warning: invalid property in typed shape entry " << i
                     << "\n";
        continue;
      }
      auto name = propObj->getString("name");
      auto *typeVal = propObj->get("type");
      if (!name || !typeVal) {
        llvh::errs()
            << "Warning: missing name or type in typed shape property\n";
        continue;
      }
      auto typeStrs = extractTypeStrings(*typeVal);
      if (typeStrs.empty()) {
        llvh::errs() << "Warning: invalid type for property \"" << name->str()
                     << "\"\n";
        continue;
      }
      def.properties.push_back({name->str(), std::move(typeStrs)});
    }
    defs.push_back(std::move(def));
  }
  LLVM_DEBUG(
      llvh::dbgs() << "Loaded " << defs.size() << " typed shape definitions\n");
}

/// Load type guards from the "type guards" JSON array.
void loadTypeGuards(
    const llvh::json::Array &arr,
    SourceErrorManager &sm,
    llvh::DenseMap<llvh::SMRange, std::vector<std::string>, SMRangeInfo>
        &typeGuards,
    llvh::DenseMap<llvh::SMRange, unsigned, SMRangeInfo> &typeGuardIds) {
  unsigned failCount = 0;

  for (unsigned i = 0, e = arr.size(); i < e; ++i) {
    const llvh::json::Object *annot = arr[i].getAsObject();
    if (!annot) {
      failCount++;
      continue;
    }

    const llvh::json::Object *loc = annot->getObject("location");
    if (!loc) {
      failCount++;
      continue;
    }

    // "types" (array) or "type" (single string).
    std::vector<std::string> typeStrs;
    if (auto *v = annot->get("types"))
      typeStrs = extractTypeStrings(*v);
    if (typeStrs.empty())
      if (auto *v = annot->get("type"))
        typeStrs = extractTypeStrings(*v);
    if (typeStrs.empty()) {
      failCount++;
      continue;
    }

    auto range = resolveLocation(loc, sm);
    if (!range.hasValue()) {
      failCount++;
      continue;
    }

    typeGuards.insert({range.getValue(), std::move(typeStrs)});
    typeGuardIds.insert({range.getValue(), i});
  }

  if (failCount > 0)
    llvh::errs() << "Warning: " << failCount << " type guards failed to load\n";
}

/// Load shape guards from the "shape guards" JSON array.
void loadShapeGuards(
    const llvh::json::Array &arr,
    SourceErrorManager &sm,
    llvh::ArrayRef<TypedShapeDefinition> typedShapeDefs,
    llvh::DenseMap<
        llvh::SMRange,
        llvh::SmallVector<ShapeGuardEntry, 2>,
        SMRangeInfo> &shapeGuards) {
  unsigned failCount = 0;

  for (unsigned i = 0, e = arr.size(); i < e; ++i) {
    const llvh::json::Object *sa = arr[i].getAsObject();
    if (!sa) {
      failCount++;
      continue;
    }

    const llvh::json::Object *objLoc = sa->getObject("object location");
    const llvh::json::Object *guardLoc = sa->getObject("guard location");
    if (!objLoc || !guardLoc) {
      failCount++;
      continue;
    }

    auto shapeIdx = sa->getInteger("shape");
    if (!shapeIdx || *shapeIdx < 0 ||
        static_cast<unsigned>(*shapeIdx) >= typedShapeDefs.size()) {
      llvh::errs() << "Warning: invalid shape index in shape guard\n";
      failCount++;
      continue;
    }

    auto objectRange = resolveLocation(objLoc, sm);
    auto guardRange = resolveLocation(guardLoc, sm);
    if (!objectRange.hasValue() || !guardRange.hasValue()) {
      failCount++;
      continue;
    }

    shapeGuards[guardRange.getValue()].push_back(
        {objectRange.getValue(), static_cast<unsigned>(*shapeIdx), i});
  }

  if (failCount > 0)
    llvh::errs() << "Warning: " << failCount
                 << " shape guards failed to load\n";
}

/// Load shape promotions from the "shape promotions" JSON array.
void loadShapePromotions(
    const llvh::json::Array &arr,
    SourceErrorManager &sm,
    llvh::ArrayRef<TypedShapeDefinition> typedShapeDefs,
    llvh::DenseMap<llvh::SMRange, ShapePromotionEntry, SMRangeInfo>
        &shapePromotions) {
  unsigned failCount = 0;

  for (unsigned i = 0, e = arr.size(); i < e; ++i) {
    const llvh::json::Object *sp = arr[i].getAsObject();
    if (!sp) {
      failCount++;
      continue;
    }

    const llvh::json::Object *objLoc = sp->getObject("object location");
    const llvh::json::Object *promoteLoc = sp->getObject("promote location");
    if (!objLoc || !promoteLoc) {
      failCount++;
      continue;
    }

    auto shapeIdx = sp->getInteger("shape");
    if (!shapeIdx || *shapeIdx < 0 ||
        static_cast<unsigned>(*shapeIdx) >= typedShapeDefs.size()) {
      llvh::errs() << "Warning: invalid shape index in shape promotion\n";
      failCount++;
      continue;
    }

    auto objectRange = resolveLocation(objLoc, sm);
    auto promoteRange = resolveLocation(promoteLoc, sm);
    if (!objectRange.hasValue() || !promoteRange.hasValue()) {
      failCount++;
      continue;
    }

    shapePromotions.insert(
        {promoteRange.getValue(),
         {objectRange.getValue(), static_cast<unsigned>(*shapeIdx)}});
  }

  if (failCount > 0)
    llvh::errs() << "Warning: " << failCount
                 << " shape promotions failed to load\n";
}

} // namespace

llvh::Optional<Type> Annotations::parseTypeNames(
    const std::vector<std::string> &typeNames) {
  if (typeNames.empty())
    return llvh::None;

  llvh::Optional<Type> result;
  for (const auto &name : typeNames) {
    llvh::Optional<Type> t = parseTypeName(name);
    if (!t.hasValue())
      return llvh::None;
    if (!result.hasValue()) {
      result = t.getValue();
    } else {
      result = Type::unionTy(result.getValue(), t.getValue());
    }
  }
  return result;
}

llvh::Optional<Type> Annotations::parseTypeName(llvh::StringRef typeName) {
  if (typeName == "number")
    return Type::createNumber();
  if (typeName == "string")
    return Type::createString();
  if (typeName == "boolean")
    return Type::createBoolean();
  if (typeName == "object")
    return Type::createObject();
  if (typeName == "null")
    return Type::createNull();
  if (typeName == "undefined")
    return Type::createUndefined();
  if (typeName == "bigint")
    return Type::createBigInt();
  if (typeName == "symbol")
    return Type::createSymbol();
  return llvh::None;
}

bool Annotations::loadFromFile(
    llvh::StringRef jsonPath,
    SourceErrorManager &sm) {
  auto fileBufOrErr = llvh::MemoryBuffer::getFile(jsonPath);
  if (!fileBufOrErr) {
    llvh::errs() << "Failed to open annotation file: " << jsonPath << "\n";
    return false;
  }

  llvh::Expected<llvh::json::Value> jsonOrErr =
      llvh::json::parse(fileBufOrErr.get()->getBuffer());
  if (!jsonOrErr) {
    llvh::errs() << "Failed to parse JSON: "
                 << llvh::toString(jsonOrErr.takeError()) << "\n";
    return false;
  }

  const llvh::json::Object *root = jsonOrErr->getAsObject();
  if (!root) {
    llvh::errs() << "JSON root is not an object\n";
    return false;
  }

  // 1. Typed shapes
  if (auto *arr = root->getArray("typed shapes"))
    loadTypedShapes(*arr, typedShapeDefs_);

  // 2. Type guards
  if (auto *arr = root->getArray("type guards"))
    loadTypeGuards(*arr, sm, typeGuards_, typeGuardIds_);

  // 3. Shape guards
  if (auto *arr = root->getArray("shape guards"))
    loadShapeGuards(*arr, sm, typedShapeDefs_, shapeGuards_);

  // 4. Shape promotions
  if (auto *arr = root->getArray("shape promotions"))
    loadShapePromotions(*arr, sm, typedShapeDefs_, shapePromotions_);

  return true;
}

llvh::Optional<std::vector<std::string>> Annotations::getTypeGuard(
    llvh::SMRange range) const {
  auto it = typeGuards_.find(range);
  if (it != typeGuards_.end()) {
    matchedTypeGuardIds_.insert(typeGuardIds_.find(range)->second);
    return it->second;
  }
  return llvh::None;
}

int Annotations::getTypeGuardId(llvh::SMRange range) const {
  auto it = typeGuardIds_.find(range);
  if (it != typeGuardIds_.end()) {
    return static_cast<int>(it->second);
  }
  return -1;
}

void Annotations::getShapeGuards(
    llvh::SMRange range,
    llvh::SmallVectorImpl<ShapeGuardEntry> &guards) const {
  auto it = shapeGuards_.find(range);
  if (it != shapeGuards_.end()) {
    for (const auto &entry : it->second) {
      matchedShapeGuardIds_.insert(entry.annotationId);
      guards.push_back(entry);
    }
  }
}

llvh::Optional<ShapePromotionEntry> Annotations::getShapePromotion(
    llvh::SMRange promoteRange) const {
  auto it = shapePromotions_.find(promoteRange);
  if (it != shapePromotions_.end())
    return it->second;
  return llvh::None;
}

void Annotations::reportUnmatched() const {
  unsigned total = typeGuardIds_.size();
  if (typeGuards_.empty() || matchedTypeGuardIds_.size() == total)
    return;

  unsigned unmatched = total - matchedTypeGuardIds_.size();
  LLVM_DEBUG({
    llvh::dbgs() << "Warning: " << unmatched << " of " << total
                 << " type guards were never matched by any IR instruction.\n";
    llvh::dbgs() << "  Unmatched: ";
    bool first = true;
    for (auto &kv : typeGuardIds_) {
      if (!matchedTypeGuardIds_.count(kv.second)) {
        if (!first)
          llvh::dbgs() << ", ";
        llvh::dbgs() << "guard#" << kv.second;
        first = false;
      }
    }
    llvh::dbgs() << "\n";
  });
}

} // namespace hermes
