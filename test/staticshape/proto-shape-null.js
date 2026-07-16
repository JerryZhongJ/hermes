// RUN: %shermes -O -exec -annotation-file=%S/proto-shape-null.json %s | %FileCheck %s --match-full-lines
// RUN: %shermes -O -dump-ir -annotation-file=%S/proto-shape-null.json %s | %FileCheckOrRegen %s --check-prefix=OPT --match-full-lines

// Wrong prototype-shape annotation on a null-prototype object. o = Object.create
// (null) so [[Prototype]]==null, but read() is annotated as if o's prototype were
// shape Proto. TrySet refuses to give o a static shape (non-null prototype
// required), so the shape guard fails at runtime and reads fall through to the
// general path — no crash, undefined (property absent on a null prototype).

(function () {
  function makeChild() {
    var o = Object.create(null);
    o.own = 1;
    return o;
  }

  function read(o) {
    return o.inherited;
  }

  print(read(makeChild()));
})();

// CHECK: undefined

// Auto-generated content below. Please do not modify manually.

// OPT:function global(): undefined
// OPT-NEXT:%BB0:
// OPT-NEXT:  %0 = TryLoadGlobalPropertyInst (:any) globalObject: object, "print": string
// OPT-NEXT:  %1 = TryLoadGlobalPropertyInst (:any) globalObject: object, "Object": string
// OPT-NEXT:  %2 = LoadPropertyInst (:any) %1: any, "create": string
// OPT-NEXT:  %3 = CallInst (:any) %2: any, empty: any, false: boolean, empty: any, undefined: undefined, %1: any, null: null
// OPT-NEXT:       StorePropertyLooseInst 1: number, %3: any, "own": string
// OPT-NEXT:       TrySetStaticShapeInst %3: any, {own: number}: null [ann#2]
// OPT-NEXT:  %6 = HasStaticShapeInst (:boolean) %3: any, {own: number}: null [ann#0]
// OPT-NEXT:       CondBranchInst %6: boolean, %BB3, %BB1
// OPT-NEXT:%BB1:
// OPT-NEXT:  %8 = LoadPropertyInst (:any) %3: any, "inherited": string
// OPT-NEXT:       BranchInst %BB2
// OPT-NEXT:%BB2:
// OPT-NEXT:  %10 = PhiInst (:any) %8: any, %BB1, %16: number, %BB4
// OPT-NEXT:  %11 = CallInst (:any) %0: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, %10: any
// OPT-NEXT:        ReturnInst undefined: undefined
// OPT-NEXT:%BB3:
// OPT-NEXT:  %13 = TypedLoadParentInst (:object) %3: any
// OPT-NEXT:  %14 = HasStaticShapeInst (:boolean) %13: object, {inherited: number}: null [ann#1]
// OPT-NEXT:        CondBranchInst %14: boolean, %BB4, %BB1
// OPT-NEXT:%BB4:
// OPT-NEXT:  %16 = PrLoadInst (:number) %13: object, 0: number, "inherited": string
// OPT-NEXT:        BranchInst %BB2
// OPT-NEXT:function_end
