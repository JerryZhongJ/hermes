/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#ifndef HERMES_UTILS_OPTIONS_H
#define HERMES_UTILS_OPTIONS_H

#include "llvh/ADT/StringRef.h"

#include <algorithm>
#include <vector>

namespace hermes {

enum OutputFormatKind {
  DumpNone,
  DumpAST,
  DumpTransformedAST,
  DumpSema,
  DumpJS,
  DumpTransformedJS,
  ViewCFG,
  DumpIR,
  DumpLIR,
  DumpRA,
  DumpLRA,
  DumpBytecode,
  EmitBundle,
  Execute,
};

/// \return true if \p name is a valid unit name. That is, it is non-empty and
/// only consists of alphanumeric characters and underscores.
inline bool isValidSHUnitName(llvh::StringRef name) {
  return !name.empty() && llvh::all_of(name, [](char c) {
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
        (c >= '0' && c <= '9') || c == '_';
  });
}

/// Options controlling the type of output to generate.
/// TODO: Split these options for bytecode and SH code generation.
struct BytecodeGenerationOptions {
  /// The format of the output.
  OutputFormatKind format = Execute;

  /// Whether optimizations are enabled.
  bool optimizationEnabled = false;

  /// The name of the unit emitted by the SH backend. This can only contain
  /// alphanumeric characters and underscores.
  llvh::StringRef unitName = "this_unit";

  /// Whether the SH backend should emit a main function that executes the
  /// generated unit.
  bool emitMain = true;

  /// Whether the SH backend should emit small C code. If false, will inline
  /// more fast paths.
  bool smallC = false;

  /// Whether to strip the debug info in the bytecode binary.
  bool stripDebugInfoSection = false;

  /// Whether to enable basic block profiling or not.
  bool basicBlockProfiling = false;

  /// Whether static builtins are enabled.
  bool staticBuiltinsEnabled = false;

  /// Whether the IR should be verified.
  bool verifyIR = false;

  /// Strip all function names to reduce string table size.
  bool stripFunctionNames = false;

  /// Whether to run the HBC ReorderRegisters pass.
  bool reorderRegisters = true;

  /// Add this much garbage after each function body (relative to its size).
  unsigned padFunctionBodiesPercent = 0;

  /// Strip the source map URL.
  bool stripSourceMappingURL = false;

  // Emit source locations in the resulting output.
  bool emitSourceLocations = false;

  // Emit #line directives in the resulting output.
  bool emitLineDirectives = false;

  // Emit asserts in the bytecode.
  bool emitAsserts = false;

  // Instrument type/shape guard branches.
  bool instrumentGuards = false;

  // Record shape miss details only for these annotation IDs.
  std::vector<unsigned> instrumentGuardDetailIDs;

  bool isGuardCountingEnabled() const {
    return instrumentGuards || !instrumentGuardDetailIDs.empty();
  }

  bool isGuardDetailsEnabled() const {
    return !instrumentGuardDetailIDs.empty();
  }

  bool shouldRecordGuardDetails(int annotationId) const {
    return annotationId >= 0 &&
        std::binary_search(
               instrumentGuardDetailIDs.begin(),
               instrumentGuardDetailIDs.end(),
               static_cast<unsigned>(annotationId));
  }

  // Instrument each JS function entry with a call counter; dump on exit.
  bool instrumentFunctionCalls = false;

  // Instrument each dynamic StoreProperty: count {typed-hc hits, total} per
  // store site; dump on exit. Covers put_by_id / put_by_val / with_receiver.
  bool instrumentStoreProperty = false;

  /* implicit */ BytecodeGenerationOptions(OutputFormatKind format)
      : format(format) {}

  static BytecodeGenerationOptions defaults() {
    return {Execute};
  }
};

} // namespace hermes

#endif
