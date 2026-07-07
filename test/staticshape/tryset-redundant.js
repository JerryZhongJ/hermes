// RUN: %shermes -O0 -Xcustom-opt=insertguard -dump-ir -annotation-file=%S/tryset-redundant.json %s | %FileCheck %s --check-prefix=INSERT
// RUN: %shermes -O -dump-ir -annotation-file=%S/tryset-redundant.json %s | %FileCheck %s --check-prefix=OPT

function diffShape() {
  var obj = {x: 1};
  var a = obj.x;
  var b = obj.x;
  return a + b;
}

// obj is established as {x:number} by the first (XNumber) guard's true edge.
// The second binding emits a TrySet targeting the *different* shape {y:number}
// on that same edge, so its operandShape (Known {x:number}) != target. The
// speculation has failed and InstSimplify must delete it: the {y:number} TrySet
// is present right after InsertGuard (INSERT) but gone after optimization (OPT).
// INSERT: TrySetStaticShapeInst {{.*}} {y: number}
// OPT: function diffShape
// OPT-NOT: TrySetStaticShapeInst {{.*}} {y: number}
// OPT: function_end
