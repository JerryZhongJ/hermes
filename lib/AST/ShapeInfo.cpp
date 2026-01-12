/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#include "hermes/AST/ShapeInfo.h"
#include "hermes/AST/Context.h"
#include "hermes/Parser/JSONParser.h"
#include "hermes/Support/SourceErrorManager.h"

#include "llvh/Support/Debug.h"
#include "llvh/Support/MemoryBuffer.h"

#define DEBUG_TYPE "shapeinfo"

namespace hermes {

using namespace parser;

bool ShapeInfoManager::loadFromJSON(const std::string &jsonPath) {
  LLVM_DEBUG(llvh::dbgs() << "ShapeInfo: Loading from " << jsonPath << "\n");

  auto fileBuf = llvh::MemoryBuffer::getFile(jsonPath);
  if (!fileBuf) {
    llvh::errs() << "Failed to read Shape JSON file: " << jsonPath << "\n";
    return false;
  }

  JSLexer::Allocator alloc;
  JSONFactory factory(alloc);
  SourceErrorManager sm;
  JSONParser parser(factory, **fileBuf, sm);

  auto rootOpt = parser.parse();
  if (!rootOpt) {
    llvh::errs() << "Failed to parse Shape JSON file: " << jsonPath << "\n";
    return false;
  }

  JSONValue *root = rootOpt.getValue();
  if (!root || !llvh::isa<JSONObject>(root)) {
    llvh::errs() << "Shape JSON root is not an object\n";
    return false;
  }

  auto *rootObj = llvh::cast<JSONObject>(root);

  auto *shapesValue = rootObj->get("shapes");
  if (!shapesValue || !llvh::isa<JSONArray>(shapesValue)) {
    llvh::errs() << "Shape JSON missing 'shapes' array\n";
    return false;
  }

  auto *shapesArray = llvh::cast<JSONArray>(shapesValue);

  for (int shapeId = 0; shapeId < (int)shapesArray->size(); ++shapeId) {
    auto shapeDef = std::make_unique<ShapeDefinition>();
    auto *shapeObj = llvh::cast<JSONObject>((*shapesArray)[shapeId]);
    if (!llvh::isa<JSONObject>(shapeObj)) {
      llvh::errs() << "Shape at index " << shapeId << " is not an object\n";
      continue;
    }

    // 解析 properties 数组
    auto *propertiesValue = shapeObj->get("properties");
    if (!propertiesValue || !llvh::isa<JSONArray>(propertiesValue)) {
      llvh::errs() << "Shape " << shapeId << " missing 'properties' array\n";
      continue;
    }

    auto *propsArray = llvh::cast<JSONArray>(propertiesValue);

    for (auto *propValue : *propsArray) {
      if (!llvh::isa<JSONObject>(propValue)) {
        continue;
      }

      auto *propObj = llvh::cast<JSONObject>(propValue);

      // 解析属性名
      auto *nameValue = propObj->get("name");
      if (!nameValue || !llvh::isa<JSONString>(nameValue)) {
        continue;
      }
      std::string propName = llvh::cast<JSONString>(nameValue)->str();
      Identifier propIdent = context_->getIdentifier(propName);

      // 解析 slot
      auto *slotValue = propObj->get("slot");
      uint32_t slot = 0;
      if (slotValue && llvh::isa<JSONNumber>(slotValue)) {
        slot = static_cast<uint32_t>(
            llvh::cast<JSONNumber>(slotValue)->getValue());
      }

      // 解析 type 或 shapeId（互斥）
      auto *typeValue = propObj->get("type");
      auto *shapeIdValue = propObj->get("shapeId");

      if (typeValue && llvh::isa<JSONString>(typeValue)) {
        // 基础类型：存储字符串
        std::string typeStr = llvh::cast<JSONString>(typeValue)->str();
        shapeDef->properties.emplace_back(propIdent, typeStr, slot);
      } else if (shapeIdValue && llvh::isa<JSONNumber>(shapeIdValue)) {
        // Shape 引用：存储索引
        uint32_t refShapeId = static_cast<uint32_t>(
            llvh::cast<JSONNumber>(shapeIdValue)->getValue());

        if (refShapeId >= shapeDefinitions_.size()) {
          llvh::errs() << "Invalid shapeId: " << refShapeId << "\n";
          continue;
        }

        shapeDef->properties.emplace_back(propIdent, refShapeId, slot);
      } else {
        llvh::errs() << "Property '" << propName
                     << "' missing 'type' or 'shapeId'\n";
        continue;
      }
    }
    shapeDefinitions_.push_back(std::move(shapeDef));
  }

  LLVM_DEBUG(
      llvh::dbgs() << "ShapeInfo: Loaded " << shapeDefinitions_.size()
                   << " shape definitions\n");

  // 4. 解析 annotations 部分
  auto *annotationsValue = rootObj->get("annotations");
  if (!annotationsValue || !llvh::isa<JSONArray>(annotationsValue)) {
    // annotations 是可选的
    return true;
  }

  auto *annotationsArray = llvh::cast<JSONArray>(annotationsValue);

  for (auto *annValue : *annotationsArray) {
    if (!llvh::isa<JSONObject>(annValue)) {
      continue;
    }

    auto *annObj = llvh::cast<JSONObject>(annValue);

    // 解析 location
    auto *locValue = annObj->get("location");
    if (!locValue || !llvh::isa<JSONObject>(locValue)) {
      continue;
    }

    auto *locObj = llvh::cast<JSONObject>(locValue);

    // 解析文件名（暂时忽略，假设单文件编译）
    auto *fileValue = locObj->get("file");
    if (!fileValue || !llvh::isa<JSONString>(fileValue)) {
      continue;
    }
    // std::string fileName = llvh::cast<JSONString>(fileValue)->str();

    // 解析 start 位置
    auto *startValue = locObj->get("start");
    if (!startValue || !llvh::isa<JSONObject>(startValue)) {
      continue;
    }
    auto *startObj = llvh::cast<JSONObject>(startValue);

    auto *startLineValue = startObj->get("line");
    auto *startColValue = startObj->get("column");
    if (!startLineValue || !llvh::isa<JSONNumber>(startLineValue) ||
        !startColValue || !llvh::isa<JSONNumber>(startColValue)) {
      continue;
    }

    uint32_t startLine = static_cast<uint32_t>(
        llvh::cast<JSONNumber>(startLineValue)->getValue());
    uint32_t startCol = static_cast<uint32_t>(
        llvh::cast<JSONNumber>(startColValue)->getValue());

    // 解析 end 位置
    auto *endValue = locObj->get("end");
    if (!endValue || !llvh::isa<JSONObject>(endValue)) {
      continue;
    }
    auto *endObj = llvh::cast<JSONObject>(endValue);

    auto *endLineValue = endObj->get("line");
    auto *endColValue = endObj->get("column");
    if (!endLineValue || !llvh::isa<JSONNumber>(endLineValue) || !endColValue ||
        !llvh::isa<JSONNumber>(endColValue)) {
      continue;
    }

    uint32_t endLine =
        static_cast<uint32_t>(llvh::cast<JSONNumber>(endLineValue)->getValue());
    uint32_t endCol =
        static_cast<uint32_t>(llvh::cast<JSONNumber>(endColValue)->getValue());

    // 解析 targetExpression
    auto *targetValue = annObj->get("targetExpression");
    if (!targetValue || !llvh::isa<JSONString>(targetValue)) {
      continue;
    }
    std::string targetStr = llvh::cast<JSONString>(targetValue)->str();

    ShapeAnnotation::TargetKind targetKind;
    if (targetStr == "AllocObject") {
      targetKind = ShapeAnnotation::TargetKind::AllocObject;
    } else if (targetStr == "Parameter") {
      targetKind = ShapeAnnotation::TargetKind::Parameter;
    } else if (targetStr == "Call") {
      targetKind = ShapeAnnotation::TargetKind::Call;
    } else if (targetStr == "LoadProperty") {
      targetKind = ShapeAnnotation::TargetKind::LoadProperty;
    } else {
      llvh::errs() << "Unknown targetExpression: " << targetStr << "\n";
      continue;
    }

    // 解析 shapeId
    auto *shapeIdValue = annObj->get("shapeId");
    if (!shapeIdValue || !llvh::isa<JSONNumber>(shapeIdValue)) {
      llvh::errs() << "Annotation missing 'shapeId'\n";
      continue;
    }
    uint32_t annotationShapeId =
        static_cast<uint32_t>(llvh::cast<JSONNumber>(shapeIdValue)->getValue());

    // 验证 shapeId 有效性
    if (annotationShapeId >= shapeDefinitions_.size()) {
      llvh::errs() << "Invalid shapeId: " << annotationShapeId << "\n";
      continue;
    }

    // 将行列号转换为 SMRange
    // 注意：第一个源文件的 bufId 通常是 2（bufId 1 可能被预定义内容占用）
    SourceErrorManager &sm = context_->getSourceErrorManager();
    unsigned bufId = 2;

    LLVM_DEBUG(
        llvh::dbgs() << "ShapeInfo: Converting coords (" << startLine << ":"
                     << startCol << ") to (" << endLine << ":" << endCol
                     << ") using bufId=" << bufId << "\n");

    SourceErrorManager::SourceCoords startCoords{bufId, startLine, startCol};
    SourceErrorManager::SourceCoords endCoords{bufId, endLine, endCol};

    SMLoc startLoc = sm.findSMLocFromCoords(startCoords);
    SMLoc endLoc = sm.findSMLocFromCoords(endCoords);

    if (!startLoc.isValid() || !endLoc.isValid()) {
      LLVM_DEBUG(
          llvh::dbgs() << "ShapeInfo: Failed to convert coordinates to SMLoc"
                       << " (startLoc valid=" << startLoc.isValid()
                       << ", endLoc valid=" << endLoc.isValid() << ")\n");
      continue;
    }

    SMRange range(startLoc, endLoc);

    // 添加到映射
    annotationMap_.try_emplace(range, targetKind, annotationShapeId);
    LLVM_DEBUG(
        llvh::dbgs() << "ShapeInfo: Added annotation at line " << startLine
                     << ":" << startCol << " -> shapeId " << annotationShapeId
                     << "\n");
  }

  LLVM_DEBUG(
      llvh::dbgs() << "ShapeInfo: Loaded " << annotationMap_.size()
                   << " annotations\n");

  return true;
}

const ShapeAnnotation *ShapeInfoManager::getAnnotationAt(
    llvh::SMRange range) const {
  // 直接在 map 中查找
  auto it = annotationMap_.find(range);
  if (it != annotationMap_.end()) {
    LLVM_DEBUG(
        llvh::dbgs() << "ShapeInfo: Found annotation at range -> shapeId "
                     << it->second.shapeId << "\n");
    return &it->second;
  }
  LLVM_DEBUG(llvh::dbgs() << "ShapeInfo: No annotation found at range\n");
  return nullptr;
}

} // namespace hermes
