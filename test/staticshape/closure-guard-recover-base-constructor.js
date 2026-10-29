/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %shermes -O -fstatic-builtins -Xinline-max-size=0 -dump-ir -verify-ir %s | %FileCheck %s --check-prefix=IR
// RUN: %shermes -O -fstatic-builtins -Xinline-max-size=0 -dump-ir -verify-ir -annotation-file=%S/closure-guard-recover-base-constructor.json %s | %FileCheck %s --check-prefix=IR
// RUN: %shermes -O -fstatic-builtins -Xinline-max-size=0 -exec -annotation-file=%S/closure-guard-recover-base-constructor.json %s | %FileCheck %s --check-prefix=EXEC --match-full-lines

// Guards on class-definition IIFEs must not delay their inlining until the
// second round, leaving no inlining round for the exposed base constructors.
// Force IIFEs to use the single-callsite heuristic while keeping constructors
// inlinable regardless of their size.
var Types = {};
(function (Types) {
  var Span = (function () {
    function Span() {
      "inline";
      this.start = -1;
      this.end = -1;
    }
    return Span;
  })();
  Types.Span = Span;

  var Node = (function (_super) {
    function Node(kind) {
      "inline";
      _super.call(this);
      this.kind = kind;
    }
    return Node;
  })(Span);
  Types.Node = Node;

  var Expression = (function (_super) {
    function Expression(kind) {
      _super.call(this, kind);
    }
    return Expression;
  })(Node);
  Types.Expression = Expression;
})(Types);

var expr = new Types.Expression(7);
print(expr.start, expr.end, expr.kind);

// IR-LABEL: function Expression(
// IR-NOT: CallInst {{.*}}%Node()
// IR-NOT: CallInst {{.*}}%Span()
// IR: StorePropertyLooseInst {{.*}}, "kind": string
// IR-NOT: CallInst {{.*}}%Node()
// IR-NOT: CallInst {{.*}}%Span()
// IR: StorePropertyLooseInst -1: number, {{.*}}, "start": string
// IR: StorePropertyLooseInst -1: number, {{.*}}, "end": string
// IR: function_end

// EXEC: -1 -1 7
