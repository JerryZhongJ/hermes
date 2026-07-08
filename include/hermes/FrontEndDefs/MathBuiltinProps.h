/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#ifndef HERMES_FRONTENDDEFS_MATHBUILTINPROPS_H
#define HERMES_FRONTENDDEFS_MATHBUILTINPROPS_H

#include "hermes/FrontEndDefs/Builtins.h"

namespace hermes {

/// Properties of a pure-numeric Math.* builtin method. This is the single
/// source of truth shared by SH code generation (C fast-path emission) and the
/// optimizer (number type guard consumer analysis, type inference).
struct MathBuiltinProp {
  BuiltinMethod::Enum method;

  /// Number of mathematical arguments, excluding the implicit `this`
  /// (which is getArgument(0)). 1 = unary (Math.abs(x)),
  /// 2 = binary (Math.pow(x, y)), 0 = variadic, whose count is
  /// getNumArguments() - 1 (Math.max(...)).
  unsigned numMathArgs;

  /// C library function name used by the SH fast-path, or nullptr if the
  /// builtin has no direct C mapping (round/imul/hypot/max/min) and must fall
  /// back to the generic _sh_ljs_call_builtin path.
  const char *cFunc;
};

/// Declare one kMathBuiltinProps row. \p arity is numMathArgs (1/2/0); \p cFunc
/// may be nullptr. Defined locally so the table stays close to its only use.
#define MATH_BUILTIN(name, arity, cFunc) \
  { BuiltinMethod::Math_##name, arity, cFunc }

/// All 20 Math.* builtins. Every entry ToNumbers its arguments, so each is a
/// consumer of a number type guard; only rows with a non-null cFunc lower to a
/// SH C fast-path.
constexpr MathBuiltinProp kMathBuiltinProps[] = {
    MATH_BUILTIN(abs, 1, "fabs"),
    MATH_BUILTIN(acos, 1, "acos"),
    MATH_BUILTIN(asin, 1, "asin"),
    MATH_BUILTIN(atan, 1, "atan"),
    MATH_BUILTIN(ceil, 1, "ceil"),
    MATH_BUILTIN(cos, 1, "cos"),
    MATH_BUILTIN(exp, 1, "exp"),
    MATH_BUILTIN(floor, 1, "floor"),
    MATH_BUILTIN(log, 1, "log"),
    MATH_BUILTIN(round, 1, nullptr), // half-toward-+Inf, not C round
    MATH_BUILTIN(sin, 1, "sin"),
    MATH_BUILTIN(sqrt, 1, "sqrt"),
    MATH_BUILTIN(tan, 1, "tan"),
    MATH_BUILTIN(trunc, 1, "trunc"),
    MATH_BUILTIN(atan2, 2, "atan2"),
    MATH_BUILTIN(imul, 2, nullptr), // needs ToInt32
    MATH_BUILTIN(pow, 2, "pow"),
    MATH_BUILTIN(hypot, 0, nullptr), // variadic
    MATH_BUILTIN(max, 0, nullptr), // variadic
    MATH_BUILTIN(min, 0, nullptr), // variadic
};

#undef MATH_BUILTIN

/// \return the property row for a Math builtin, or nullptr if \p m is not a
/// pure-numeric Math.* builtin.
inline const MathBuiltinProp *lookupMathBuiltinProp(BuiltinMethod::Enum m) {
  for (const auto &p : kMathBuiltinProps) {
    if (p.method == m)
      return &p;
  }
  return nullptr;
}

/// \return whether \p m is a pure-numeric Math.* builtin (all arguments are
/// ToNumber'd), i.e. a useful consumer of a number type guard.
inline bool isPureNumericMathBuiltin(BuiltinMethod::Enum m) {
  return lookupMathBuiltinProp(m) != nullptr;
}

} // namespace hermes

#endif // HERMES_FRONTENDDEFS_MATHBUILTINPROPS_H
