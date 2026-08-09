// RUN: %shermes -O0 -Xcustom-opt=insertguard -dump-ir -annotation-file=%S/tryset-redundant.json %s | %FileCheck %s --check-prefix=INSERT
// RUN: %shermes -O -dump-ir -annotation-file=%S/tryset-redundant.json %s | %FileCheck %s --check-prefix=OPT

function diffShape() {
  var obj = {x: 0};
  obj.x = 1;
  obj.x = 2;
  return obj.x;
}

// The first store binds obj to {x:number}. The second x store preserves that
// known shape, then its binding emits a TrySet targeting the different shape
// {y:number}. Its operandShape (Known {x:number}) != target, so InstSimplify
// must delete it: the {y:number} TrySet is present right after InsertGuard
// (INSERT) but gone after optimization (OPT).
// INSERT: TrySetStaticShapeInst {{.*}} {y: number}
// OPT: function diffShape
// OPT-NOT: TrySetStaticShapeInst {{.*}} {y: number}
// OPT: function_end
