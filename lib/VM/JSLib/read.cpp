/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#include "JSLibInternal.h"

#include "hermes/VM/JSTypedArray.h"
#include "hermes/VM/Operations.h"
#include "hermes/VM/StringView.h"
#include "hermes/VM/TwineChar16.h"

#include "llvh/Support/ConvertUTF.h"
#include "llvh/Support/MemoryBuffer.h"

namespace hermes {
namespace vm {

/// read(filename, mode) - Read a file and return its contents.
/// Without mode or mode != "binary": returns the file content as a string.
/// With mode == "binary": returns the file content as a Uint8Array.
CallResult<HermesValue> read(void *, Runtime &runtime) {
  NativeArgs args = runtime.getCurrentFrame().getNativeArgs();
  GCScope scope(runtime);

  // Get the file path argument (JS string is UTF-16).
  auto pathRes = toString_RJS(runtime, args.getArgHandle(0));
  if (LLVM_UNLIKELY(pathRes == ExecutionStatus::EXCEPTION)) {
    return ExecutionStatus::EXCEPTION;
  }
  auto pathView = StringPrimitive::createStringView(
      runtime, runtime.makeHandle(std::move(*pathRes)));
  llvh::SmallVector<char16_t, 128> pathBuf;
  std::string pathUTF8;
  convertUTF16ToUTF8WithReplacements(
      pathUTF8, pathView.getUTF16Ref(pathBuf));

  // Check for optional "binary" mode argument.
  bool binary = false;
  if (args.getArgCount() > 1) {
    auto modeRes = toString_RJS(runtime, args.getArgHandle(1));
    if (LLVM_UNLIKELY(modeRes == ExecutionStatus::EXCEPTION)) {
      return ExecutionStatus::EXCEPTION;
    }
    auto modeView = StringPrimitive::createStringView(
        runtime, runtime.makeHandle(std::move(*modeRes)));
    llvh::SmallVector<char16_t, 16> modeBuf;
    UTF16Ref modeUTF16 = modeView.getUTF16Ref(modeBuf);
    // Compare with "binary" (6 chars).
    binary = (modeUTF16.size() == 6 &&
              modeUTF16[0] == 'b' && modeUTF16[1] == 'i' &&
              modeUTF16[2] == 'n' && modeUTF16[3] == 'a' &&
              modeUTF16[4] == 'r' && modeUTF16[5] == 'y');
  }

  // Read the file from disk (requires UTF-8 path).
  auto fileBufRes = llvh::MemoryBuffer::getFile(pathUTF8);
  if (!fileBufRes) {
    return runtime.raiseTypeError(
        TwineChar16("Cannot open file: ") +
        TwineChar16(pathView.getUTF16Ref(pathBuf)));
  }

  llvh::MemoryBuffer &buf = **fileBufRes;

  if (binary) {
    // Binary mode: return Uint8Array.
    auto taRes = JSTypedArray<uint8_t, CellKind::Uint8ArrayKind>::allocate(
        runtime, buf.getBufferSize());
    if (LLVM_UNLIKELY(taRes == ExecutionStatus::EXCEPTION)) {
      return ExecutionStatus::EXCEPTION;
    }
    Handle<JSTypedArrayBase> ta = *taRes;

    // Copy file data into the TypedArray.
    uint8_t *data = ta->data(runtime);
    std::copy(
        buf.getBufferStart(),
        buf.getBufferEnd(),
        data);

    return ta.getHermesValue();
  }

  // Text mode: return string (UTF-8 → JS string).
  const uint8_t *utf8 =
      reinterpret_cast<const uint8_t *>(buf.getBufferStart());
  auto strRes = StringPrimitive::createEfficient(
      runtime, llvh::makeArrayRef(utf8, buf.getBufferSize()));
  if (LLVM_UNLIKELY(strRes == ExecutionStatus::EXCEPTION)) {
    return ExecutionStatus::EXCEPTION;
  }
  return *strRes;
}

} // namespace vm
} // namespace hermes
