# About annotations

These annotations insert runtime checks that let the compiler specialize hot
JavaScript while preserving normal behavior on every failed check. On a pass the
specialized fast path runs; on a fail normal unoptimized behavior runs. A wrong
guard is therefore safe but useless, not a correctness failure.

## Concepts

- **Target expression** identifies the value an annotation describes. Parameter
  declarations and actual `this` expressions can be targets too.
- **Type** is a concrete type, a union, or `any`. Concrete types are
  boolean, closure, null, number, string, undefined. `any` means unknown, not absent.
  `closure` represents one known target function and cannot be in a union.
- **Static shape** describes an object's own properties, in order: their type,
  data/accessor kind, descriptor flags, and a target function for a closure.
  It does NOT cover inherited properties — those live on the prototype object
  and need their own prototype shape (see Prototype shapes below).
- At runtime a static shape corresponds to a hidden class. A known shape fixes
  data-property slot offsets and bypasses inline caches even when every property
  type is `any`. Concrete property types additionally enable typed operations,
  checked typed stores, and closure-call inlining.

## Shape and type mechanisms

A **shape binding** is the only operation that attempts to give an object a
static shape. It validates the object then sets its matching hidden class. A
binding is a one-time cost that can benefit later consumers of the same object.
A binding automatically creates its immediate shape guard; never rely on a bare
binding as a fast-path fact. The target range always covers the expression that
produces the object, never an enclosing assignment. When construction is
completed by a property write, target that write's receiver; do not put bindings
on receivers that are only read.

A **shape guard** verifies that an object already has a shape established by a
binding. Given a `prototype shape`, it additionally verifies the object's
direct prototype carries that prototype's shape — so the prototype must be
bound too, or the prototype half always fails. A guard cannot create a shape:
guarding an unbound object always fails. Guard facts are local to their
containing function: a callee needs its own guard even when the caller guarded
the corresponding argument. A binding, conversely, changes the object's hidden
class and can be consumed in any later function. Shape checks are cheap; add
enough guards to preserve useful facts and let the compiler remove redundancy.

A **type guard** is independent of shapes. It narrows a target expression so
arithmetic, string, and comparison operations can avoid generic dispatch and
coercion. A scalar `closure` type guard additionally requires the exact `target
function` range; it guards function-code identity and may enable direct-call
analysis/inlining. `closure` is forbidden in unions, and non-closure guards must
not carry `target function`.

## Shape facts, effects, and costs

A shape fact reaches a use only when every path to that use preserves it.
Function calls, global-property loads, `in`, and `instanceof` always remain
side-effecting. Unknown generic operations and unknown-shape property accesses
can become side-effect-free only after suitable type/shape knowledge. A later
guard may re-establish a fact after a compiler-conservative kill.

A shape guard enables direct data-property slot access — on the object, and on
its direct prototype when a `prototype shape` is given. Accessors still invoke
their getter/setter. Concrete property types also let downstream operations use
typed paths.

A `closure` property is the highest-value annotation: it carries one known
target function, so a call to that property can be **inlined**. Inlining
removes the call entirely (no dispatch, no argument shuffling, no frame setup)
and folds the callee body into the caller, so constant folding, CSE,
dead-code elimination, and register allocation all cross the old call
boundary. For hot small helpers — math/vector ops, getters, predicate
callbacks — this is often the largest win any annotation can buy, and a type
guard alone can never produce it. So prefer `closure` whenever a property
holds a function whose definition is statically known.

A binding creates a write guard only if its shape has at least one non-`any`
property (`closure` counts). A fully-`any` shape still gets direct slot access
but has no typed write-guard overhead. Typed property writes are checked unless
both a shape guard covers the write and the stored type is proven compatible;
a mismatch silently degrades that property to untyped rather than throwing.
Choose typed shapes only where their extra optimization benefit outweighs this
per-write cost.

## Property and prototype constraints

- Accessor properties are always type `any`.
- A prototype shape begins with a non-enumerable `constructor` data property of
  type `any`.
- A known closure property must be `data`, type `closure`, and name its target
  function range. A method assigned as `Cls.prototype.m = function (...) Ellipsis`
  is exactly a `data`/`closure` property — its `target function` is the range of
  that function expression.
- Add a `prototype shape` to a guard only when the guarded code reads a data
  property (including a `closure` method) on the object's DIRECT prototype, and
  that prototype has its own binding to the prototype shape. Omit it when only
  own properties are touched; chains deeper than the direct prototype are
  unsupported.

## Prototype shapes and method inlining

A prototype object (`Cls.prototype`, `Cls.prototype.sub = Ellipsis`, etc.) is just
another object — it gets its own `static_shape` and `shape_binding`. The recipe
for a prototype with a method `m`:

1. Define the prototype shape: a non-enumerable `constructor` property (type
   `any`), then each hot method as `{"name": "m", "type": "closure",
   "target function": <range of the function expression>}`.
2. Bind it with a `shape_binding` targeting the expression that produces the
   prototype object. For `Cls.prototype.m = function...`, target the LHS receiver
   `Cls.prototype`, not the whole assignment; the binding is applied after the
   method store. For `Cls.prototype = Ellipsis`, target the object literal.
3. Guard hot instances with both `shape` (the instance shape) and
   `prototype shape`. On pass, prototype property reads become direct slot
   access and calls to `closure` methods inline.

This is what makes prototype method dispatch on hot instances fast — look for
`X.prototype.method = function` patterns (very common in ported/compiled JS)
and apply the recipe to the hot ones.

## Annotation schema

Each `add_annotation` call takes a kind and one annotation body:

- `static_shape`: `{"properties": [Property, ...]}`; pass the shape name as
  the separate `shape` argument. Add the shape before references to it.
- `shape_binding`: `{"target range": RangeKey, "shape": string}`.
- `shape_guard`: `{"target range": RangeKey, "shape": string,
  "prototype shape"?: string}`.
- `type_guard`: `{"target range": RangeKey, "type": TypeName,
  "target function"?: RangeKey}`; `target function` is required exactly when
  `type` is the scalar string `"closure"`.

`RangeKey` is the string `"startLine:startCol:endLine:endCol"` (e.g.
`"3:25:3:66"`) — 1-based lines and columns, EXCLUSIVE end column. It addresses
an arbitrary expression range; do not confuse it with a function loc_key
`"31:1"` (two parts), which is an ID identifying one whole function. Every
range you pass to the annotation tools — `target range`, `target function`,
ranges inside an `update_annotation` patch — is a `RangeKey` string, never a
`{start, end}` object.
`TypeName` is one concrete type ("boolean" | "closure" | "null" | "number" | "string" | "undefined"), `"any"`, or an array
of concrete types. `Property` supports `name`, optional `type`, optional
`kind` (`data` or `accessor`), optional `flags off`, and `target function` (a
`RangeKey`) only for a `closure`. Types default to `any`, kinds default to
`data`, and descriptor flags default to enabled.

For a parameter target range use its declaration. For `this`, target an actual
`this` expression at the operation you want to optimize. Use source-tool ranges
exactly: end columns are exclusive. Prefer `locate`'s AST role queries
(`what="param"/"callee"/"def"/"ref"/"member"`) over text matches — they return
the exact semantic range (e.g. a callee identifier without the `(`) with no
column hand-counting.

## Worked example

Source:
  L1:  function Point(x, y) { this.x = x; this.y = y; }
  L3:  Point.prototype.scale = function(k) { this.x *= k; this.y *= k; };
  L5:  const opts = { get tag() { return "p"; }, inner: { n: 3 } };
  L7:  function process(p, k, cb) {
  L8:    p.scale(k);
  L9:    const r = p.x + opts.inner.n;
  L10:   if (cb) cb(r);
  L11:   return opts.tag + r;
  L12: }

Create shapes first, then bindings, shape guards, and type guards:
```
add_annotation({"kind": "static_shape", "annotation": {"properties": [{"name": "x", "type": "number"}, {"name": "y", "type": "number"}]}, "shape": "Point"})
add_annotation({"kind": "static_shape", "annotation": {"properties": [{"name": "constructor", "flags off": ["enumerable"]}, {"name": "scale", "type": "closure", "target function": "3:25:3:66"}]}, "shape": "PointProto"})
add_annotation({"kind": "static_shape", "annotation": {"properties": [{"name": "tag", "kind": "accessor"}, {"name": "inner"}]}, "shape": "Opts"})
add_annotation({"kind": "static_shape", "annotation": {"properties": [{"name": "n", "type": "number"}]}, "shape": "Inner"})
add_annotation({"kind": "shape_binding", "annotation": {"target range": "1:36:1:40", "shape": "Point"}})
add_annotation({"kind": "shape_binding", "annotation": {"target range": "3:1:3:16", "shape": "PointProto"}})
add_annotation({"kind": "shape_binding", "annotation": {"target range": "5:14:5:60", "shape": "Opts"}})
add_annotation({"kind": "shape_binding", "annotation": {"target range": "5:50:5:58", "shape": "Inner"}})
add_annotation({"kind": "shape_guard", "annotation": {"target range": "7:18:7:19", "shape": "Point", "prototype shape": "PointProto"}})
add_annotation({"kind": "shape_guard", "annotation": {"target range": "9:13:9:14", "shape": "Point", "prototype shape": "PointProto"}})
add_annotation({"kind": "shape_guard", "annotation": {"target range": "9:17:9:21", "shape": "Opts"}})
add_annotation({"kind": "shape_guard", "annotation": {"target range": "9:17:9:27", "shape": "Inner"}})
add_annotation({"kind": "type_guard", "annotation": {"target range": "3:34:3:35", "type": "number"}})
add_annotation({"kind": "type_guard", "annotation": {"target range": "7:24:7:26", "type": ["null", "undefined"]}})
add_annotation({"kind": "type_guard", "annotation": {"target range": "10:12:10:14", "type": "closure", "target function": "3:25:3:66"}})
add_annotation({"kind": "type_guard", "annotation": {"target range": "11:8:11:16", "type": "string"}})
```

This scenario exercises most features. Here is why each annotation is written
the way it is, and what it buys:

Shapes
- Point {x:number, y:number}: a 2D point; typing x/y `number` lets arithmetic
  on them (e.g. `*=` in `scale`) skip ToPrimitive and take the number fast path.
- PointProto (the prototype object):
  - `constructor`: typed `any` (not on a hot arithmetic path) with `flags off:
    ["enumerable"]`, since every prototype has a non-enumerable constructor by
    JS default.
  - `scale`: typed `closure` with its target function (the L3 definition), so
    `p.scale(k)` can be inlined.
- Opts {tag:accessor, inner:any}: an all-`any` shape (no write guard, since no
  property is non-`any`). `tag` is a getter, hence `accessor` (accessors are always `any`);
  `inner` is another object with its own shape (Inner). Field accesses still go
  through the shape fast path (direct slot offset) even with every property
  `any`.
- Inner {n:number}: the object nested inside `opts`; typing `n` number lets the
  `+` into `r` take the number fast path.

Bindings (one-time cost each; every later guard on the same object benefits)
- The `this` receiver in the final `this.y = y` write → Point: the constructor
  writes this.x then this.y one by one, so select the object expression in the
  write that completes the shape, not the whole assignment.
- The `Point.prototype` receiver in the L3 method write → PointProto: select the
  object expression in the write that completes the prototype shape, so a later
  prototype-shape guard on Point instances can pass.
- `opts` → Opts: a plain object literal (not `this`, not a prototype) bound so
  its fields can be shape-accessed.
- `opts.inner` → Inner: the nested literal {n:3} is bound too, so a shape guard
  on `opts.inner` can pass.

Type guards
- `k` (scale's parameter): number — lets `*=` inside `scale` take the number
  fast path.
- `cb`: ["null","undefined"] — cb is an optional callback, usually absent/null;
  this lets `if (cb)` (L10) be folded away on the no-callback path (both falsy).
- `cb`: closure targeting the L3 function — on the callback-present path this
  exact identity guard can make `cb(r)` directly analyzable and inlineable.
- `opts.tag`: string — `tag` is an accessor (a getter), so its value is `any`
  in the shape (accessors always are) and unknown to the compiler; the guard
  narrows the getter's return at this use so the `+ r` concat takes the string
  fast path.

Shape guards
- `p` (L7) → Point + PointProto: verifies p's hidden class is Point's; on pass,
  `p.scale(k)` (L8) takes the shape fast path and `scale` can inline.
- `p` (L9) → Point + PointProto: the `p.scale(k)` call on L8 kills the shape
  fact (a call may mutate shape), so the `p.x` read on L9 needs its own fresh
  guard here to stay fast.
- `opts` (L9) → Opts (no prototype shape): on pass, the `inner` field is a
  direct slot read (`tag` is an accessor, so it still runs the getter).
- `opts.inner` (L9) → Inner: `inner` holds another object with its own shape,
  so reading `opts.inner.n` needs this SECOND guard — the one on `opts` only
  yields the `inner` reference, not its fields. Note its target is the
  expression `opts.inner`; a shape guard can target any expression that
  evaluates to the object.

