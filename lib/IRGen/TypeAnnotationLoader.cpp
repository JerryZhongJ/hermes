/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#include "hermes/IRGen/TypeAnnotationLoader.h"
#include "hermes/IR/IR.h"

#include "llvh/Support/Debug.h"
#include "llvh/Support/JSON.h"
#include "llvh/Support/MemoryBuffer.h"
#include "llvh/Support/raw_ostream.h"

#define DEBUG_TYPE "type-annotation"

namespace hermes {

llvh::Optional<Type> TypeAnnotations::parseTypeName(llvh::StringRef typeName) {
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
  if (typeName == "empty")
    return Type::createEmpty();
  if (typeName == "uninit")
    return Type::createUninit();
  return llvh::None;
}

bool TypeAnnotations::loadFromFile(
    llvh::StringRef jsonPath,
    SourceErrorManager &sm) {
  // 1. 读取JSON文件
  auto fileBufOrErr = llvh::MemoryBuffer::getFile(jsonPath);
  if (!fileBufOrErr) {
    llvh::errs() << "Failed to open type annotation file: " << jsonPath << "\n";
    return false;
  }

  // 2. 解析JSON
  llvh::Expected<llvh::json::Value> jsonOrErr =
      llvh::json::parse(fileBufOrErr.get()->getBuffer());
  if (!jsonOrErr) {
    llvh::errs() << "Failed to parse JSON: "
                 << llvh::toString(jsonOrErr.takeError()) << "\n";
    return false;
  }

  // 3. 提取annotations数组
  const llvh::json::Object *root = jsonOrErr->getAsObject();
  if (!root) {
    llvh::errs() << "JSON root is not an object\n";
    return false;
  }

  const llvh::json::Array *annotArr = root->getArray("annotations");
  if (!annotArr) {
    llvh::errs() << "Missing 'annotations' array\n";
    return false;
  }

  // 4. 解析每个标注并直接转换为SMRange

  unsigned successCount = 0;
  unsigned failCount = 0;

  for (const auto &item : *annotArr) {
    const llvh::json::Object *annot = item.getAsObject();
    if (!annot) {
      failCount++;
      continue;
    }

    // 提取location
    const llvh::json::Object *loc = annot->getObject("location");
    if (!loc) {
      failCount++;
      continue;
    }

    auto file = loc->getString("file");
    const llvh::json::Object *start = loc->getObject("start");
    const llvh::json::Object *end = loc->getObject("end");
    auto typeStr = annot->getString("type");

    if (!file || !start || !end || !typeStr) {
      llvh::errs() << "Warning: Incomplete annotation entry\n";
      failCount++;
      continue;
    }

    // 提取行列号
    auto startLine = start->getInteger("line");
    auto startCol = start->getInteger("column");
    auto endLine = end->getInteger("line");
    auto endCol = end->getInteger("column");

    if (!startLine || !startCol || !endLine || !endCol) {
      llvh::errs() << "Warning: Invalid coordinates\n";
      failCount++;
      continue;
    }

    // 转换坐标为SMLoc（bufId固定为2）
    SourceErrorManager::SourceCoords startCoords(
        2, static_cast<unsigned>(*startLine), static_cast<unsigned>(*startCol));
    SourceErrorManager::SourceCoords endCoords(
        2, static_cast<unsigned>(*endLine), static_cast<unsigned>(*endCol));

    LLVM_DEBUG(
        llvh::dbgs() << "Converting coordinates: " << file->str() << ":"
                     << *startLine << ":" << *startCol << " - " << *endLine
                     << ":" << *endCol << "\n");

    llvh::SMLoc startLoc = sm.findSMLocFromCoords(startCoords);
    llvh::SMLoc endLoc = sm.findSMLocFromCoords(endCoords);

    if (!startLoc.isValid() || !endLoc.isValid()) {
      llvh::errs() << "Warning: Failed to resolve coordinates for "
                   << file->str() << ":" << *startLine << ":" << *startCol
                   << "\n";
      failCount++;
      continue;
    }

    LLVM_DEBUG(
        llvh::dbgs() << "  Resolved to SMLoc: "
                     << "start=" << startLoc.getPointer()
                     << ", end=" << endLoc.getPointer() << "\n");

    // 存储到map中（存储类型字符串，延迟到IRGen时转换）
    llvh::SMRange range(startLoc, endLoc);
    annotations_.insert({range, typeStr->str()});

    LLVM_DEBUG(
        llvh::dbgs() << "  Stored annotation for SMRange ["
                     << range.Start.getPointer() << ", "
                     << range.End.getPointer() << "), type: " << typeStr->str()
                     << "\n");

    successCount++;
  }

  if (failCount > 0) {
    llvh::errs() << "Warning: " << failCount << " annotations failed to load\n";
  }

  return true;
}

llvh::Optional<std::string> TypeAnnotations::getAnnotation(
    llvh::SMRange range) const {
  auto it = annotations_.find(range);
  if (it != annotations_.end()) {
    return it->second;
  }
  return llvh::None;
}

} // namespace hermes
