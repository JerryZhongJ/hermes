/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %shermes -O -dump-ir -annotation-file=%S/type-guard-prstore.json %s | %FileCheck %s --check-prefix=OPT

// A number guard enables PrStore to omit its runtime type check when the
// property's expected type contains number. It must survive RemoveUseless.
function retain(x) {
  var o = {n: 0};
  o.n = x;
  return o.n;
}

// A number guard does not help a string property store, which still requires a
// runtime type check. RemoveUseless should delete it.
function remove(x) {
  var o = {s: ""};
  o.s = x;
  return o.s;
}

function closureTarget() {
  return 0;
}

// A closure slot always needs its function-identity check. An object guard must
// not be reported as a PrStore optimization by annotation-dryrun.
function closure(x) {
  var o = {method: closureTarget};
  o.method = x;
  return o.method;
}

// OPT-LABEL:function retain(
// OPT: TypeOfIsInst {{.*}}typeOfIs(Number) [ann#0]
// OPT: PrStoreInst %{{[0-9]+}}: number, %{{[0-9]+}}: object, 0: number, "n": string
// OPT: UnionNarrowTrustedInst (:number)
// OPT-LABEL:function remove(
// OPT-NOT: TypeOfIsInst
// OPT-NOT: UnionNarrowTrustedInst
// OPT: PrStoreInst %{{[0-9]+}}: any, %{{[0-9]+}}: object, 0: number, "s": string
// OPT-LABEL:function closure(
// OPT: TypeOfIsInst {{.*}}typeOfIs(Object,Function) [ann#2]
// OPT: PrStoreInst %{{[0-9]+}}: object, %{{[0-9]+}}: object, 0: number, "method": string
// OPT: UnionNarrowTrustedInst (:object)
