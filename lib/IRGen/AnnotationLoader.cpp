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

#include <algorithm>

#define DEBUG_TYPE "annotation-loader"

namespace hermes {

namespace {

/// Extract strings from a JSON value that is either a single string
/// (e.g. "number") or an array of strings (e.g. ["number", "string"]).
std::vector<std::string> extractStrings(const llvh::json::Value &val) {
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
      sm.warning(
          llvh::SMLoc{},
          "invalid static shape entry '" + shapeName.str() + "'");
      continue;
    }
    auto *propsArr = shapeObj->getArray("properties");
    if (!propsArr) {
      sm.warning(
          llvh::SMLoc{},
          "missing 'properties' in static shape '" + shapeName.str() + "'");
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
        sm.warning(
            llvh::SMLoc{},
            "invalid property in static shape '" + shapeName.str() + "'");
        ok = false;
        break;
      }
      auto name = propObj->getString("name");
      if (!name) {
        sm.warning(
            llvh::SMLoc{},
            "missing name in static shape '" + shapeName.str() + "'");
        ok = false;
        break;
      }
      // "kind" defaults to "data"; "accessor" marks a getter/setter property.
      bool accessor = false;
      if (auto kindStr = propObj->getString("kind")) {
        if (*kindStr == "data") {
          accessor = false;
        } else if (*kindStr == "accessor") {
          accessor = true;
        } else {
          sm.warning(
              llvh::SMLoc{},
              "invalid kind '" + kindStr->str() + "' for property \"" +
                  name->str() + "\" in static shape '" + shapeName.str() +
                  "' (expected 'data' or 'accessor')");
          ok = false;
          break;
        }
      }
      StaticShapePropertyAttrs attrs;
      if (auto *flagsOffVal = propObj->get("flags off")) {
        auto flagsOff = extractStrings(*flagsOffVal);
        if (flagsOff.empty()) {
          sm.warning(
              llvh::SMLoc{},
              "invalid 'flags off' for property \"" + name->str() +
                  "\" in static shape '" + shapeName.str() + "'");
          ok = false;
          break;
        }
        for (const auto &flag : flagsOff) {
          if (flag == "writable")
            attrs.writable = false;
          else if (flag == "enumerable")
            attrs.enumerable = false;
          else if (flag == "configurable")
            attrs.configurable = false;
          else {
            sm.warning(
                llvh::SMLoc{},
                "invalid flag '" + flag + "' in 'flags off' for property \"" +
                    name->str() + "\" in static shape '" + shapeName.str() +
                    "'");
            ok = false;
            break;
          }
        }
        if (!ok)
          break;
      }
      if (accessor)
        attrs.writable = false;
      // "type" is optional and defaults to "any".
      std::vector<std::string> typeStrs = {"any"};
      if (auto *typeVal = propObj->get("type")) {
        typeStrs = extractStrings(*typeVal);
        if (typeStrs.empty()) {
          sm.warning(
              llvh::SMLoc{},
              "invalid type for property \"" + name->str() +
                  "\" in static shape '" + shapeName.str() + "'");
          ok = false;
          break;
        }
      }
      // Accessor properties are always "any"; warn if a non-any type was given.
      if (accessor) {
        for (const auto &s : typeStrs)
          if (s != "any") {
            sm.warning(
                llvh::SMLoc{},
                "accessor property \"" + name->str() + "\" in static shape '" +
                    shapeName.str() +
                    "' must be type 'any'; ignoring declared type");
            break;
          }
        typeStrs = {"any"};
      }
      // "closure" is a single-valued type marking a property whose value is a
      // known function. It cannot be part of a union.
      bool isClosureType = false;
      for (const auto &s : typeStrs) {
        if (s == "closure") {
          isClosureType = true;
          if (typeStrs.size() != 1) {
            sm.warning(
                llvh::SMLoc{},
                "property \"" + name->str() + "\" in static shape '" +
                    shapeName.str() +
                    "': 'closure' cannot be part of a union type");
            ok = false;
          }
          break;
        }
      }
      if (!ok)
        break;
      // "target function" gives the definition range of a closure property's
      // known target function. Required when type is "closure"; allowed only
      // then. Mutually exclusive with accessor.
      llvh::SMRange targetFuncRange;
      if (auto *targetFuncVal = propObj->get("target function")) {
        if (accessor) {
          sm.warning(
              llvh::SMLoc{},
              "property \"" + name->str() + "\" in static shape '" +
                  shapeName.str() + "' cannot be both accessor and closure");
          ok = false;
          break;
        }
        if (!isClosureType) {
          sm.warning(
              llvh::SMLoc{},
              "property \"" + name->str() + "\" in static shape '" +
                  shapeName.str() +
                  "' has 'target function' but is not typed 'closure'");
          ok = false;
          break;
        }
        auto targetFuncObj = targetFuncVal->getAsObject();
        if (!targetFuncObj) {
          sm.warning(
              llvh::SMLoc{},
              "invalid 'target function' range for property \"" + name->str() +
                  "\" in static shape '" + shapeName.str() + "'");
          ok = false;
          break;
        }
        auto resolved = resolveLocation(targetFuncObj, sm);
        if (!resolved) {
          sm.warning(
              llvh::SMLoc{},
              "unresolved 'target function' range for property \"" +
                  name->str() + "\" in static shape '" + shapeName.str() + "'");
          ok = false;
          break;
        }
        targetFuncRange = *resolved;
      } else if (isClosureType) {
        sm.warning(
            llvh::SMLoc{},
            "closure property \"" + name->str() + "\" in static shape '" +
                shapeName.str() + "' is missing 'target function'");
        ok = false;
        break;
      }
      def.properties.push_back(
          {name->str(), std::move(typeStrs), accessor, attrs, targetFuncRange});
    }
    if (ok)
      defs[shapeName] = std::move(def);
  }
  LLVM_DEBUG(
      llvh::dbgs() << "Loaded " << defs.size()
                   << " static shape definitions\n");
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
    sm.warning(
        llvh::SMLoc{},
        "unknown shape name '" + shapeName->str() + "' in " + context.str());
    return llvh::None;
  }

  return shapeName->str();
}

/// Load type hints from the "type hints" JSON array.
void loadTypeGuards(
    const llvh::json::Array &arr,
    SourceErrorManager &sm,
    llvh::DenseMap<llvh::SMRange, TypeGuardEntry, SMRangeInfo> &typeGuards,
    unsigned &nextAnnotationId,
    std::vector<AnnotationDescriptor> &annotationDescriptors) {
  for (unsigned i = 0, e = arr.size(); i < e; ++i) {
    const llvh::json::Object *annot = arr[i].getAsObject();
    if (!annot) {
      sm.warning(
          llvh::SMLoc{},
          "type guard entry #" + std::to_string(i) + ": not an object");
      continue;
    }

    const llvh::json::Object *loc = annot->getObject("target range");
    if (!loc) {
      sm.warning(
          llvh::SMLoc{},
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
      typeStrs = extractStrings(*v);
    if (typeStrs.empty()) {
      sm.warning(
          llvh::SMLoc{}, "type guard at " + at + ": missing or invalid 'type'");
      continue;
    }

    // A closure guard identifies one exact function and therefore must be the
    // scalar string "closure", never an array/union. Its target is forbidden on
    // every other type guard.
    auto scalarType = annot->getString("type");
    bool isClosureType = scalarType && *scalarType == "closure";
    if (!isClosureType &&
        std::find(typeStrs.begin(), typeStrs.end(), "closure") !=
            typeStrs.end()) {
      sm.warning(
          llvh::SMLoc{},
          "type guard at " + at +
              ": 'closure' must be a scalar type and cannot be in a union");
      continue;
    }

    llvh::SMRange targetFuncRange;
    if (auto *targetFuncVal = annot->get("target function")) {
      if (!isClosureType) {
        sm.warning(
            llvh::SMLoc{},
            "type guard at " + at +
                ": 'target function' is only valid for type 'closure'");
        continue;
      }
      auto *targetFuncObj = targetFuncVal->getAsObject();
      auto resolved = targetFuncObj
          ? resolveLocation(targetFuncObj, sm)
          : llvh::Optional<llvh::SMRange>{};
      if (!resolved) {
        sm.warning(
            llvh::SMLoc{},
            "type guard at " + at + ": invalid 'target function' range");
        continue;
      }
      targetFuncRange = *resolved;
    } else if (isClosureType) {
      sm.warning(
          llvh::SMLoc{},
          "closure type guard at " + at + " is missing 'target function'");
      continue;
    }

    auto range = resolveLocation(loc, sm);
    if (!range.hasValue()) {
      sm.warning(
          llvh::SMLoc{}, "type guard at " + at + ": target range unresolved");
      continue;
    }

    if (typeGuards.count(range.getValue())) {
      sm.warning(
          llvh::SMLoc{},
          "type guard at " + at +
              ": duplicate target range; annotation skipped");
      continue;
    }

    // Assign a globally-unique id shared across all annotation categories.
    unsigned id = nextAnnotationId++;
    std::string detail = llvh::join(typeStrs, "|");
    typeGuards.insert(
        {range.getValue(), {std::move(typeStrs), targetFuncRange, id}});
    annotationDescriptors.push_back(
        {AnnotationDescriptor::Type,
         std::move(detail),
         line,
         col,
         endLine,
         endCol});
  }
}

/// Load shape hints from the "shape hints" JSON array. Each hint checks the
/// target expression at its context-sensitive use point during IRGen.
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
      sm.warning(
          llvh::SMLoc{},
          "shape guard entry #" + std::to_string(i) + ": not an object");
      continue;
    }

    const llvh::json::Object *targetLoc = sa->getObject("target range");
    if (!targetLoc) {
      sm.warning(
          llvh::SMLoc{},
          "shape guard entry #" + std::to_string(i) +
              ": missing 'target range'");
      continue;
    }

    unsigned line = 0, col = 0;
    readPos(targetLoc, "start", line, col);
    unsigned endLine = 0, endCol = 0;
    readPos(targetLoc, "end", endLine, endCol);
    std::string at = std::to_string(line) + ":" + std::to_string(col);

    if (sa->get("guard after")) {
      sm.warning(
          llvh::SMLoc{},
          "shape guard at " + at +
              ": legacy 'guard after' is unsupported; annotation skipped");
      continue;
    }

    auto shapeName =
        resolveShapeName(*sa, shapeDefs, "shape guard at " + at, sm);
    if (!shapeName.hasValue()) {
      continue;
    }

    auto targetRange = resolveLocation(targetLoc, sm);
    if (!targetRange.hasValue()) {
      sm.warning(
          llvh::SMLoc{}, "shape guard at " + at + ": target range unresolved");
      continue;
    }

    // Optional "prototype shape": defined shape name of the object's direct
    // prototype (a refinement of "shape", so shape-guard only).
    std::string protoShapeName;
    if (auto protoOpt = sa->getString("prototype shape")) {
      if (shapeDefs.find(*protoOpt) == shapeDefs.end()) {
        sm.warning(
            llvh::SMLoc{},
            "shape guard at " + at + ": unknown 'prototype shape' '" +
                protoOpt->str() + "'");
        continue;
      }
      protoShapeName = protoOpt->str();
    }

    // Own-shape and prototype-shape get distinct ids (reported separately).
    // Descriptor push order must match id order (indexed by id).
    unsigned id = nextAnnotationId++;
    unsigned protoId = id;
    if (!protoShapeName.empty())
      protoId = nextAnnotationId++;
    annotationDescriptors.push_back(
        {AnnotationDescriptor::ShapeHint,
         shapeName.getValue(),
         line,
         col,
         endLine,
         endCol});
    if (!protoShapeName.empty())
      annotationDescriptors.push_back(
          {AnnotationDescriptor::PrototypeShapeHint,
           protoShapeName,
           line,
           col,
           endLine,
           endCol});
    shapeGuards[targetRange.getValue()].push_back(
        {shapeName.getValue(), std::move(protoShapeName), id, protoId});
  }
}

/// Load shape bindings from the "shape bindings" JSON array. A binding sets a
/// static shape on an object and then guards it at its context-sensitive use
/// point during IRGen.
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
      sm.warning(
          llvh::SMLoc{},
          "shape binding entry #" + std::to_string(i) + ": not an object");
      continue;
    }

    const llvh::json::Object *targetLoc = sp->getObject("target range");
    if (!targetLoc) {
      sm.warning(
          llvh::SMLoc{},
          "shape binding entry #" + std::to_string(i) +
              ": missing 'target range'");
      continue;
    }

    unsigned line = 0, col = 0;
    readPos(targetLoc, "start", line, col);
    unsigned endLine = 0, endCol = 0;
    readPos(targetLoc, "end", endLine, endCol);
    std::string at = std::to_string(line) + ":" + std::to_string(col);

    if (sp->get("bind after")) {
      sm.warning(
          llvh::SMLoc{},
          "shape binding at " + at +
              ": legacy 'bind after' is unsupported; annotation skipped");
      continue;
    }

    auto shapeName =
        resolveShapeName(*sp, shapeDefs, "shape binding at " + at, sm);
    if (!shapeName.hasValue()) {
      continue;
    }

    auto targetRange = resolveLocation(targetLoc, sm);
    if (!targetRange.hasValue()) {
      sm.warning(
          llvh::SMLoc{},
          "shape binding at " + at + ": target range unresolved");
      continue;
    }

    if (shapeBindings.count(targetRange.getValue())) {
      sm.warning(
          llvh::SMLoc{},
          "shape binding at " + at +
              ": duplicate target range; annotation skipped");
      continue;
    }

    unsigned id = nextAnnotationId++;
    shapeBindings.insert({targetRange.getValue(), {shapeName.getValue(), id}});
    annotationDescriptors.push_back(
        {AnnotationDescriptor::ShapeBinding,
         shapeName.getValue(),
         line,
         col,
         endLine,
         endCol});
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
  if (typeName == "object" || typeName == "closure")
    // "closure" maps to object: a closure is a callable object in the IR.
    // Closure-ness itself is carried by StaticShapeProperty::targetFunc
    // (resolved from the "target function" range), not by the type.
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
    loadTypeGuards(
        *arr,
        sm,
        typeGuards_,
        nextAnnotationId_,
        annotationDescriptors_);

  // 3. Shape hints (alias: "shape guards")
  if (auto *arr = getArrayWithAlias(*root, "shape hints", "shape guards"))
    loadShapeGuards(
        *arr,
        sm,
        shapeDefs_,
        shapeGuards_,
        nextAnnotationId_,
        annotationDescriptors_);

  // 4. Shape bindings
  if (auto *arr = root->getArray("shape bindings"))
    loadShapeBindings(
        *arr,
        sm,
        shapeDefs_,
        shapeBindings_,
        nextAnnotationId_,
        annotationDescriptors_);

  return true;
}

llvh::Optional<TypeGuardEntry> Annotations::getTypeGuard(
    llvh::SMRange range) const {
  auto it = typeGuards_.find(range);
  return it != typeGuards_.end() ? llvh::Optional<TypeGuardEntry>(it->second)
                                : llvh::None;
}

void Annotations::getShapeGuards(
    llvh::SMRange range,
    llvh::SmallVectorImpl<ShapeGuardEntry> &guards) const {
  auto it = shapeGuards_.find(range);
  if (it != shapeGuards_.end())
    guards.append(it->second.begin(), it->second.end());
}

llvh::Optional<ShapeBindingEntry> Annotations::getShapeBinding(
    llvh::SMRange range) const {
  auto it = shapeBindings_.find(range);
  return it != shapeBindings_.end()
      ? llvh::Optional<ShapeBindingEntry>(it->second)
      : llvh::None;
}

void Annotations::reportMatchStatus(SourceErrorManager &sm) const {
  // Warn about annotations that loaded OK but produced no IR guard. Goes
  // through the compiler's standard warning path so annotation-dryrun /
  // shermes surface it like other diagnostics. bufId 2 = main source buffer
  // (matches resolveLocation).
  unsigned total = annotationDescriptors_.size();
  for (unsigned id = 0; id < total; ++id) {
    const auto &desc = annotationDescriptors_[id];
    if (matchedAnnotationIds_.count(id))
      continue;
    llvh::SMLoc loc = sm.findSMLocFromCoords(
        SourceErrorManager::SourceCoords(2, desc.line, desc.col));
    sm.warning(
        loc,
        "annotation [" + std::string(annotationKindLabel(desc.kind)) + " \"" +
            desc.detail +
            "\"] unmatched: target range didn't emit annotation IR");
  }
}

} // namespace hermes
