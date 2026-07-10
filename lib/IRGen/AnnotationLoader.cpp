/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#include "hermes/IRGen/AnnotationLoader.h"
#include "hermes/IR/IR.h"

#include "llvh/ADT/StringExtras.h"
#include "llvh/ADT/StringMap.h"
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
  const llvh::json::Object *start = loc->getObject("start");
  const llvh::json::Object *end = loc->getObject("end");
  if (!start || !end)
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

/// Read the 1-based start line/col from a JSON location object into \p line /
/// \p col. Returns false (leaving the outputs untouched) if the start position
/// is missing, so callers can record a best-effort position on the descriptor
/// for debug logs independently of resolveLocation's SMRange resolution.
/// Read the 1-based line/column under \p key ("start" or "end") of a JSON
/// location object. Returns false if the sub-object or either field is absent.
bool readPos(
    const llvh::json::Object *loc,
    llvh::StringRef key,
    unsigned &line,
    unsigned &col) {
  const llvh::json::Object *pos = loc->getObject(key);
  if (!pos)
    return false;
  auto l = pos->getInteger("line");
  auto c = pos->getInteger("column");
  if (!l || !c)
    return false;
  line = static_cast<unsigned>(*l);
  col = static_cast<unsigned>(*c);
  return true;
}

/// Look up a JSON array under \p key, falling back to \p alias when \p key is
/// absent. Annotation JSON accepts both "type hints" and its alias "type
/// guards" (likewise "shape hints" / "shape guards"); the primary key wins
/// when both happen to be present.
const llvh::json::Array *getArrayWithAlias(
    const llvh::json::Object &obj,
    llvh::StringRef key,
    llvh::StringRef alias) {
  if (auto *arr = obj.getArray(key))
    return arr;
  return obj.getArray(alias);
}

/// Load static shape definitions from the "shapes" JSON object.
/// Each entry maps a shape name to an object with a "properties" array; each
/// property is {"name": string, "type": string|[string]}. Property order in
/// the array is significant: different order means a different shape.
void loadStaticShapes(
    const llvh::json::Object &shapesObj,
    llvh::StringMap<StaticShapeDefinition> &defs,
    SourceErrorManager &sm) {
  for (const auto &entry : shapesObj) {
    llvh::StringRef shapeName = entry.first;
    const llvh::json::Object *shapeObj = entry.second.getAsObject();
    if (!shapeObj) {
      sm.warning(llvh::SMLoc{},
                 "invalid static shape entry '" + shapeName.str() + "'");
      continue;
    }
    auto *propsArr = shapeObj->getArray("properties");
    if (!propsArr) {
      sm.warning(llvh::SMLoc{},
                 "missing 'properties' in static shape '" + shapeName.str() +
                     "'");
      continue;
    }
    // Build the shape as a whole: any malformed property discards the entire
    // shape — a partial shape would be misleading. Warn (not error): a bad
    // shape definition just means that shape's guards won't bind.
    StaticShapeDefinition def;
    bool ok = true;
    for (const auto &elem : *propsArr) {
      const llvh::json::Object *propObj = elem.getAsObject();
      if (!propObj) {
        sm.warning(llvh::SMLoc{},
                   "invalid property in static shape '" + shapeName.str() + "'");
        ok = false;
        break;
      }
      auto name = propObj->getString("name");
      auto *typeVal = propObj->get("type");
      if (!name || !typeVal) {
        sm.warning(llvh::SMLoc{},
                   "missing name or type in static shape '" + shapeName.str() +
                       "'");
        ok = false;
        break;
      }
      auto typeStrs = extractTypeStrings(*typeVal);
      if (typeStrs.empty()) {
        sm.warning(llvh::SMLoc{},
                   "invalid type for property \"" + name->str() +
                       "\" in static shape '" + shapeName.str() + "'");
        ok = false;
        break;
      }
      def.properties.push_back({name->str(), std::move(typeStrs)});
    }
    if (ok)
      defs[shapeName] = std::move(def);
  }
  LLVM_DEBUG(
      llvh::dbgs() << "Loaded " << defs.size() << " static shape definitions\n");
}

llvh::Optional<std::string> resolveShapeName(
    const llvh::json::Object &annotation,
    const llvh::StringMap<StaticShapeDefinition> &shapeDefs,
    llvh::StringRef context,
    SourceErrorManager &sm) {
  auto shapeName = annotation.getString("shape");
  if (!shapeName) {
    sm.warning(llvh::SMLoc{}, "missing shape name in " + context.str());
    return llvh::None;
  }

  auto it = shapeDefs.find(*shapeName);
  if (it == shapeDefs.end()) {
    sm.warning(llvh::SMLoc{},
               "unknown shape name '" + shapeName->str() + "' in " +
                   context.str());
    return llvh::None;
  }

  return shapeName->str();
}

/// Load type hints from the "type hints" JSON array.
void loadTypeGuards(
    const llvh::json::Array &arr,
    SourceErrorManager &sm,
    llvh::DenseMap<llvh::SMRange, std::vector<std::string>, SMRangeInfo>
        &typeGuards,
    llvh::DenseMap<llvh::SMRange, unsigned, SMRangeInfo> &typeGuardIds,
    unsigned &nextAnnotationId,
    std::vector<AnnotationDescriptor> &annotationDescriptors) {
  for (unsigned i = 0, e = arr.size(); i < e; ++i) {
    const llvh::json::Object *annot = arr[i].getAsObject();
    if (!annot) {
      sm.warning(llvh::SMLoc{},
                 "type guard entry #" + std::to_string(i) +
                     ": not an object");
      continue;
    }

    const llvh::json::Object *loc = annot->getObject("target range");
    if (!loc) {
      sm.warning(llvh::SMLoc{},
                 "type guard entry #" + std::to_string(i) +
                     ": missing 'target range'");
      continue;
    }

    unsigned line = 0, col = 0;
    readPos(loc, "start", line, col);
    unsigned endLine = 0, endCol = 0;
    readPos(loc, "end", endLine, endCol);
    std::string at = std::to_string(line) + ":" + std::to_string(col);

    // "type": a single type string or an array of type strings (union).
    std::vector<std::string> typeStrs;
    if (auto *v = annot->get("type"))
      typeStrs = extractTypeStrings(*v);
    if (typeStrs.empty()) {
      sm.warning(llvh::SMLoc{},
                 "type guard at " + at + ": missing or invalid 'type'");
      continue;
    }

    auto range = resolveLocation(loc, sm);
    if (!range.hasValue()) {
      sm.warning(llvh::SMLoc{},
                 "type guard at " + at + ": target range unresolved");
      continue;
    }

    // Assign a globally-unique id shared across all annotation categories.
    unsigned id = nextAnnotationId++;
    std::string detail = llvh::join(typeStrs, "|");
    typeGuards.insert({range.getValue(), std::move(typeStrs)});
    typeGuardIds.insert({range.getValue(), id});
    annotationDescriptors.push_back(
        {AnnotationDescriptor::Type, std::move(detail), line, col, endLine, endCol});
  }
}

/// Load shape hints from the "shape hints" JSON array. Each hint checks the
/// target expression right after evaluation, or after the optional "guard
/// after" point if given.
void loadShapeGuards(
    const llvh::json::Array &arr,
    SourceErrorManager &sm,
    const llvh::StringMap<StaticShapeDefinition> &shapeDefs,
    llvh::DenseMap<
        llvh::SMRange,
        llvh::SmallVector<ShapeGuardEntry, 2>,
        SMRangeInfo> &shapeGuards,
    unsigned &nextAnnotationId,
    std::vector<AnnotationDescriptor> &annotationDescriptors) {
  for (unsigned i = 0, e = arr.size(); i < e; ++i) {
    const llvh::json::Object *sa = arr[i].getAsObject();
    if (!sa) {
      sm.warning(llvh::SMLoc{},
                 "shape guard entry #" + std::to_string(i) +
                     ": not an object");
      continue;
    }

    const llvh::json::Object *targetLoc = sa->getObject("target range");
    if (!targetLoc) {
      sm.warning(llvh::SMLoc{},
                 "shape guard entry #" + std::to_string(i) +
                     ": missing 'target range'");
      continue;
    }

    unsigned line = 0, col = 0;
    readPos(targetLoc, "start", line, col);
    unsigned endLine = 0, endCol = 0;
    readPos(targetLoc, "end", endLine, endCol);
    std::string at = std::to_string(line) + ":" + std::to_string(col);

    auto shapeName =
        resolveShapeName(*sa, shapeDefs, "shape guard at " + at, sm);
    if (!shapeName.hasValue()) {
      continue;
    }

    auto targetRange = resolveLocation(targetLoc, sm);
    if (!targetRange.hasValue()) {
      sm.warning(llvh::SMLoc{},
                 "shape guard at " + at + ": target range unresolved");
      continue;
    }

    // The checked object is always the target expression. The insertion point
    // (map key) is the optional "guard after" location; if omitted the guard
    // runs right after the target expression.
    llvh::SMRange insertRange = targetRange.getValue();
    if (const llvh::json::Object *guardAfter = sa->getObject("guard after")) {
      auto guardAfterRange = resolveLocation(guardAfter, sm);
      if (!guardAfterRange.hasValue()) {
        sm.warning(llvh::SMLoc{},
                   "shape guard at " + at + ": 'guard after' unresolved");
        continue;
      }
      insertRange = guardAfterRange.getValue();
    }

    unsigned id = nextAnnotationId++;
    shapeGuards[insertRange].push_back(
        {targetRange.getValue(), shapeName.getValue(), id});
    annotationDescriptors.push_back(
        {AnnotationDescriptor::ShapeHint, shapeName.getValue(), line, col, endLine, endCol});
  }
}

/// Load shape bindings from the "shape bindings" JSON array. A binding sets a
/// static shape on an object and then guards it; the binding runs right after
/// the target expression, or after the optional "bind after" point.
void loadShapeBindings(
    const llvh::json::Array &arr,
    SourceErrorManager &sm,
    const llvh::StringMap<StaticShapeDefinition> &shapeDefs,
    llvh::DenseMap<llvh::SMRange, ShapeBindingEntry, SMRangeInfo>
        &shapeBindings,
    unsigned &nextAnnotationId,
    std::vector<AnnotationDescriptor> &annotationDescriptors) {
  for (unsigned i = 0, e = arr.size(); i < e; ++i) {
    const llvh::json::Object *sp = arr[i].getAsObject();
    if (!sp) {
      sm.warning(llvh::SMLoc{},
                 "shape binding entry #" + std::to_string(i) +
                     ": not an object");
      continue;
    }

    const llvh::json::Object *targetLoc = sp->getObject("target range");
    if (!targetLoc) {
      sm.warning(llvh::SMLoc{},
                 "shape binding entry #" + std::to_string(i) +
                     ": missing 'target range'");
      continue;
    }

    unsigned line = 0, col = 0;
    readPos(targetLoc, "start", line, col);
    unsigned endLine = 0, endCol = 0;
    readPos(targetLoc, "end", endLine, endCol);
    std::string at = std::to_string(line) + ":" + std::to_string(col);

    auto shapeName =
        resolveShapeName(*sp, shapeDefs, "shape binding at " + at, sm);
    if (!shapeName.hasValue()) {
      continue;
    }

    auto targetRange = resolveLocation(targetLoc, sm);
    if (!targetRange.hasValue()) {
      sm.warning(llvh::SMLoc{},
                 "shape binding at " + at + ": target range unresolved");
      continue;
    }

    // The bound object is always the target expression. The insertion point
    // (map key) is the optional "bind after" location; if omitted the binding
    // runs right after the target expression.
    llvh::SMRange insertRange = targetRange.getValue();
    if (const llvh::json::Object *bindAfter = sp->getObject("bind after")) {
      auto bindAfterRange = resolveLocation(bindAfter, sm);
      if (!bindAfterRange.hasValue()) {
        sm.warning(llvh::SMLoc{},
                   "shape binding at " + at + ": 'bind after' unresolved");
        continue;
      }
      insertRange = bindAfterRange.getValue();
    }

    unsigned id = nextAnnotationId++;
    shapeBindings.insert(
        {insertRange, {targetRange.getValue(), shapeName.getValue(), id}});
    annotationDescriptors.push_back(
        {AnnotationDescriptor::ShapeBinding, shapeName.getValue(), line, col, endLine, endCol});
  }
}

} // namespace

llvh::Optional<Type> Annotations::parseTypeNames(
    const std::vector<std::string> &typeNames,
    std::string *unsupported) {
  if (typeNames.empty())
    return llvh::None;

  llvh::Optional<Type> result;
  for (const auto &name : typeNames) {
    llvh::Optional<Type> t = parseTypeName(name);
    if (!t.hasValue()) {
      if (unsupported) {
        if (!unsupported->empty())
          *unsupported += ", ";
        *unsupported += name;
      }
      continue;
    }
    if (!result.hasValue()) {
      result = t.getValue();
    } else {
      result = Type::unionTy(result.getValue(), t.getValue());
    }
  }
  if (unsupported && !unsupported->empty())
    return llvh::None;
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
  if (typeName == "any")
    return Type::createAnyType();
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

  // 1. Static shapes
  if (auto *shapesObj = root->getObject("static shapes"))
    loadStaticShapes(*shapesObj, shapeDefs_, sm);

  // 2. Type hints (alias: "type guards")
  if (auto *arr = getArrayWithAlias(*root, "type hints", "type guards"))
    loadTypeGuards(*arr, sm, typeGuards_, typeGuardIds_, nextAnnotationId_,
                   annotationDescriptors_);

  // 3. Shape hints (alias: "shape guards")
  if (auto *arr = getArrayWithAlias(*root, "shape hints", "shape guards"))
    loadShapeGuards(*arr, sm, shapeDefs_, shapeGuards_, nextAnnotationId_,
                    annotationDescriptors_);

  // 4. Shape bindings
  if (auto *arr = root->getArray("shape bindings"))
    loadShapeBindings(*arr, sm, shapeDefs_, shapeBindings_, nextAnnotationId_,
                      annotationDescriptors_);

  return true;
}

llvh::Optional<std::vector<std::string>> Annotations::getTypeGuard(
    llvh::SMRange range) const {
  auto it = typeGuards_.find(range);
  if (it != typeGuards_.end()) {
    matchedAnnotationIds_.insert(typeGuardIds_.find(range)->second);
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
      matchedAnnotationIds_.insert(entry.annotationId);
      guards.push_back(entry);
    }
  }
}

llvh::Optional<ShapeBindingEntry> Annotations::getShapeBinding(
    llvh::SMRange bindRange) const {
  auto it = shapeBindings_.find(bindRange);
  if (it != shapeBindings_.end()) {
    matchedAnnotationIds_.insert(it->second.annotationId);
    return it->second;
  }
  return llvh::None;
}

llvh::SmallVector<llvh::SMRange, 4>
Annotations::getShapeAnnotationObjectRanges() const {
  llvh::SmallVector<llvh::SMRange, 4> ranges;
  for (const auto &kv : shapeBindings_)
    ranges.push_back(kv.second.objectRange);
  for (const auto &kv : shapeGuards_)
    for (const auto &entry : kv.second)
      ranges.push_back(entry.objectRange);
  return ranges;
}

void Annotations::reportMatchStatus(SourceErrorManager &sm) const {
  // Warn about annotations that loaded OK but produced no IR guard — their
  // target range didn't hit a target AST node. Goes through the compiler's
  // standard warning path so annotation-dryrun / shermes surface it like
  // other diagnostics. bufId 2 = main source buffer (matches resolveLocation).
  unsigned total = annotationDescriptors_.size();
  for (unsigned id = 0; id < total; ++id) {
    const auto &desc = annotationDescriptors_[id];
    if (matchedAnnotationIds_.count(id))
      continue;
    SourceErrorManager::SourceCoords coords(2, desc.line, desc.col);
    llvh::SMLoc loc = sm.findSMLocFromCoords(coords);
    sm.warning(
        loc,
        "annotation [" + std::string(annotationKindLabel(desc.kind)) + " \"" +
            desc.detail +
            "\"] unmatched: target range didn't hit a target AST node "
            "(fix the range, not the annotation content)");
  }
}

} // namespace hermes
