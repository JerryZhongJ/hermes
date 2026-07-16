/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#define DEBUG_TYPE "staticshapeinference"

#include "StaticShapeInferenceRunner.h"

#include "hermes/IR/CFG.h"
#include "hermes/IR/Instrs.h"
#include "llvh/ADT/DenseMap.h"
#include "llvh/ADT/DenseSet.h"
#include "llvh/ADT/Optional.h"
#include "llvh/ADT/SmallPtrSet.h"
#include "llvh/ADT/SmallVector.h"
#include "llvh/Support/Debug.h"

using namespace hermes;

namespace hermes {
namespace static_shape_inference {

/// 复用 IR.h 的 StaticShapeInfo 作为格元素：
///   NoShape(⊥,不可达) ⊑ KnownStaticShape ⊑ AnyShapes(⊤,可达但未知)
/// 汇合用 join(⊔)：NoShape 幺元、AnyShapes 吸收元、两个不同 Known → Any。
/// 故 join 结果为具体 shape ⟺ 所有可达路径形状一致（must 级确定性）。

/// join ⊔（格汇合）：NoShape 幺元、AnyShapes 吸收元、两个不同 Known → Any。
/// 故 a | b 为具体 shape ⟺ 所有可达路径形状一致（must 级确定性）。
static inline StaticShapeInfo operator|(StaticShapeInfo a, StaticShapeInfo b) {
  if (a.status == StaticShapeInfo::NoShape)
    return b;
  if (b.status == StaticShapeInfo::NoShape)
    return a;
  if (a.status == StaticShapeInfo::AnyShapes ||
      b.status == StaticShapeInfo::AnyShapes)
    return StaticShapeInfo::createAnyShapes();
  if (a.desc == b.desc) // 均 KnownStaticShape
    return a;
  return StaticShapeInfo::createAnyShapes();
}

/// mov-like：单一 operand 的纯值传递，不写堆；shape 沿 operand 链传播。
static inline SingleOperandInst *isMovLikeInst(Instruction *inst) {
  if (llvh::isa<MovInst>(inst) || llvh::isa<ImplicitMovInst>(inst) ||
      llvh::isa<UnionNarrowTrustedInst>(inst))
    return static_cast<SingleOperandInst *>(inst);
  return nullptr;
}

static void setStaticShapeInfo(Instruction *inst, StaticShapeInfo shape) {
  if (auto *L = llvh::dyn_cast<BaseLoadPropertyInst>(inst))
    L->setObjOperandShape(shape);
  else if (auto *S = llvh::dyn_cast<BaseStorePropertyInst>(inst))
    S->setObjOperandShape(shape);
  else if (auto *H = llvh::dyn_cast<HasStaticShapeInst>(inst))
    H->setObjOperandShape(shape);
  else if (auto *T = llvh::dyn_cast<TrySetStaticShapeInst>(inst))
    T->setObjOperandShape(shape);
  else if (auto *LPN = llvh::dyn_cast<LoadParentNoTrapsInst>(inst))
    LPN->setObjOperandShape(shape);
}

/// edge 上 ShapeGuard 注入的 shape（CondBranch 真分支）。
struct EdgeFact {
  Instruction *object; // HasStaticShape 的 argument
  const StaticShapeDesc *shape; // 注入的 known shape
};

class Impl {
  friend class ::hermes::StaticShapeInferenceRunner;

  Function *F_;

  /// 分析范围：从各 HasStaticShape 的 argument 沿 propagator(mov-like/phi)
  /// 向下游可达的指令。划定 State 的 key 域——范围外指令查询恒返回 Any。
  /// 没 guard 的函数此集为空 → 分析近乎空跑。
  llvh::DenseSet<Instruction *> analysisScope_;

  /// 数据流状态：Instruction → StaticShapeInfo，封装 get/set。
  /// - get 用 find：读取绝不能插入默认值（StaticShapeInfo 默认 AnyShapes，
  ///   会与缺省 NoShape=不可达 语义冲突，冲掉注入的 Known shape）。
  /// - set 用 operator[]：纯覆盖写，插入的默认值立刻被 info 覆盖，安全。
  /// scope 引用 analysisScope_，供 get 判定范围（范围外 → Any）。
  struct State {
   private:
    llvh::DenseMap<Instruction *, StaticShapeInfo> map_;
    const llvh::DenseSet<Instruction *> &scope;
    /// map_ 中 status==AnyShapes 的条目数。set/setAll 维护，operator== 预检。
    unsigned anyCount_ = 0;

   public:
    State(const llvh::DenseSet<Instruction *> &scope_) : scope(scope_) {}

    State(const State &o)
        : map_(o.map_), scope(o.scope), anyCount_(o.anyCount_) {}
    State(State &&o)
        : map_(std::move(o.map_)), scope(o.scope), anyCount_(o.anyCount_) {}
    State &operator=(const State &o) {
      assert(&scope == &o.scope && "State assigned across different scopes");
      map_ = o.map_;
      anyCount_ = o.anyCount_;
      return *this;
    }
    State &operator=(State &&o) {
      assert(&scope == &o.scope && "State assigned across different scopes");
      map_ = std::move(o.map_);
      anyCount_ = o.anyCount_;
      return *this;
    }
    /// 取 inst 的 shape：null 或不在 scope_(范围外) → Any；
    /// 范围内但不在 map → NoShape(不可达)；否则 map 值。
    StaticShapeInfo get(Instruction *inst) const {
      if (!inst || !scope.count(inst))
        return StaticShapeInfo::createAnyShapes();
      auto it = map_.find(inst);
      return it != map_.end() ? it->second : StaticShapeInfo::createNoShape();
    }

    void set(Instruction *inst, StaticShapeInfo info) {
      auto it = map_.find(inst);
      bool oldAny = false;
      bool newAny = info.status == StaticShapeInfo::AnyShapes;
      if (it != map_.end()) {
        oldAny = it->second.status == StaticShapeInfo::AnyShapes;
        it->second = info;
      } else
        map_.try_emplace(inst, info);

      if (oldAny && !newAny)
        --anyCount_;
      else if (!oldAny && newAny)
        ++anyCount_;
    }

    void setAll(StaticShapeInfo info) {
      for (auto &kv : map_)
        kv.second = info;
      anyCount_ = (info.status == StaticShapeInfo::AnyShapes) ? map_.size() : 0;
    }

    bool contains(Instruction *inst) const {
      return map_.find(inst) != map_.end();
    }

    bool operator==(const State &o) const {
      // 快速预检：AnyShapes 条目数不同必不等。
      if (map_.size() != o.map_.size())
        return false;
      if (anyCount_ != o.anyCount_)
        return false;
      for (const auto &kv : map_) {
        auto it = o.map_.find(kv.first);
        if (it == o.map_.end() || !(it->second == kv.second))
          return false;
      }
      return true;
    }
    bool operator!=(const State &o) const {
      return !(*this == o);
    }

    // 只读遍历，供数据流汇合枚举 pred 的 OUT。
    using const_iterator =
        llvh::DenseMap<Instruction *, StaticShapeInfo>::const_iterator;
    const_iterator begin() const {
      return map_.begin();
    }
    const_iterator end() const {
      return map_.end();
    }
  };
  using BBStateMap = llvh::DenseMap<BasicBlock *, State>;

  /// 块出口状态。缺失 = 空 State(全 NoShape)。IN 不缓存，computeIn 现算。
  BBStateMap out_;

  /// 关键指令(load/store/hasStaticShape/trySetStaticShape)的 object
  /// 操作数；非关键指令返回 null。
  static inline bool isTargetInst(Instruction *inst) {
    return llvh::isa<BaseLoadPropertyInst>(inst) ||
        llvh::isa<BaseStorePropertyInst>(inst) ||
        llvh::isa<HasStaticShapeInst>(inst) ||
        llvh::isa<TrySetStaticShapeInst>(inst) ||
        llvh::isa<LoadParentNoTrapsInst>(inst);
  }

  bool knownShapeStorePolluting(
      BaseStorePropertyInst *store,
      const StaticShapeDesc *shape) const {
    auto *prop = llvh::dyn_cast<LiteralString>(store->getProperty());
    if (!prop)
      return false;
    Identifier name = prop->getValue();
    int idx = shape->getPropertyIndex(name);
    if (idx < 0)
      return false;
    // Writing an accessor property invokes its setter (arbitrary JS), so it is
    // never a precise, non-polluting slot store.
    if (shape->getPropertyKind(idx) == PropertyKind::Accessor)
      return false;
    Type expectedType = shape->getPropertyType(idx);
    Type storedType = store->getStoredValue()->getType();
    return storedType.isSubsetOf(expectedType);
  }

  /// 指令是否 pollute（写堆且不精确兼容）。依赖指令成员 objOperandShape_。
  bool polluting(Instruction *inst) const {
    auto se = inst->getSideEffect();
    if (!se.getWriteHeap())
      return false;
    if (auto *store = llvh::dyn_cast<BaseStorePropertyInst>(inst)) {
      switch (store->getObjOperandShape().status) {
        case StaticShapeInfo::KnownStaticShape:
          return !knownShapeStorePolluting(
              store, store->getObjOperandShape().desc);
        case StaticShapeInfo::NoShape:
          return false;
        case StaticShapeInfo::AnyShapes:
          return true;
      }
    }
    if (auto *store = llvh::dyn_cast<PrStoreInst>(inst))
      return !store->getStoredValue()->getType().isSubsetOf(
          store->getExpectedType());
    // TrySet switches obj's hidden class to a static shape's class only — it
    // touches no other object and invalidates no existing static shape fact, so
    // it never pollutes.
    if (llvh::isa<TrySetStaticShapeInst>(inst))
      return false;
    return true;
  }

  /// ShapeGuard = CondBranch 以 HasStaticShape 为 condition 且紧挨它。
  /// 真分支上注入 (argument, shape)。assert HasStaticShape 紧邻 CondBranch。
  llvh::Optional<EdgeFact> getEdgeFact(BasicBlock *pred, BasicBlock *succ)
      const {
    auto *condBr = llvh::dyn_cast<CondBranchInst>(pred->getTerminator());
    if (!condBr || condBr->getTrueDest() != succ)
      return llvh::None;
    auto *hss = llvh::dyn_cast<HasStaticShapeInst>(condBr->getCondition());
    if (!hss)
      return llvh::None;
    assert(
        hss->getParent() == pred &&
        "ShapeGuard: HasStaticShape must be in the same block as CondBranch");
    assert(
        std::next(hss->getIterator()) == condBr->getIterator() &&
        "ShapeGuard: HasStaticShape must immediately precede CondBranch");
    auto *object = llvh::dyn_cast<Instruction>(hss->getArgument());
    if (!object)
      return llvh::None;
    return EdgeFact{object, hss->getShape()->getData()};
  }

  //===------------------------------------------------------------------===//
  // Step 1: 收集 analysisScope_ + 重置 objOperandShape_
  //===------------------------------------------------------------------===//
  void collectAnalysisScope() {
    // 正向：从 argument 沿 propagator 向下游 BFS。
    llvh::SmallVector<Instruction *, 16> wl;
    for (auto &BB : *F_) {
      for (auto &I : BB) {
        auto *hss = llvh::dyn_cast<HasStaticShapeInst>(&I);
        if (!hss)
          continue;
        auto *arg = llvh::dyn_cast<Instruction>(hss->getArgument());
        if (!arg)
          continue;
        wl.push_back(arg);
      }
    }

    while (!wl.empty()) {
      auto *v = wl.pop_back_val();
      if (!analysisScope_.insert(v).second)
        continue;
      for (auto *U : v->getUsers()) {
        auto *user = llvh::dyn_cast<Instruction>(U);
        if (user && (isMovLikeInst(user) || llvh::isa<PhiInst>(user)))
          wl.push_back(user);
      }
    }
  }

  void resetShapes() {
    for (auto &BB : *F_) {
      for (auto &I : BB) {
        // 仅关键指令有 objOperandShape_ 成员。
        if (isTargetInst(&I))
          setStaticShapeInfo(&I, StaticShapeInfo::createNoShape());
      }
    }
  }

  /// 预填所有 BB 的 OUT 为空 State（全 NoShape），并清掉上一轮残留。
  /// 之后 out_.find(pred) 必命中，computeIn/transferPhi/runToFixpoint 无需再判
  /// end()；不可达 BB 的 OUT 保持空 State，get 返回 NoShape（join 幺元）。
  void initOut() {
    out_.clear();
    for (auto &BB : *F_)
      out_.try_emplace(&BB, analysisScope_);
  }

  //===------------------------------------------------------------------===//
  // Step 2: 前向数据流（join）
  //===------------------------------------------------------------------===//

  /// IN[b] = ⊔_pred edge(pred→b)(OUT[pred])，edge 在真分支注入 guard shape。
  State computeIn(BasicBlock *BB) {
    State in(analysisScope_);
    for (auto *pred : predecessors(BB)) {
      const State &predOut = out_.find(pred)->second; // 预填保证命中
      auto edge = getEdgeFact(pred, BB);
      if (edge)
        in.set(
            edge->object,
            in.get(edge->object) |
                StaticShapeInfo::createKnownStaticShape(edge->shape));
      for (const auto &kv : predOut) {
        if (edge && kv.first == edge->object)
          continue;

        in.set(kv.first, in.get(kv.first) | kv.second);
      }
    }
    return in;
  }

  /// phi：s[phi] = ⊔_k edge(pred_k→BB)(OUT[pred_k])[incoming_k]。
  /// 平行语义：第 k 个 incoming 仅在 pred_k 可达时有效。不可达 pred 的 OUT
  /// 缺失 → NoShape（⊥，join 幺元自动吸收），不会用别的 pred 的值污染。
  /// 故必须 per-pred 取 OUT，而非用当前 BB 已 join 全部 pred 的全局 IN——
  /// 后者会把 incoming 在「其它 pred 的 OUT」里的 Any/NoShape 误并入。
  void transferPhi(State &s, PhiInst *phi) const {
    BasicBlock *BB = phi->getParent();
    StaticShapeInfo ph = StaticShapeInfo::createNoShape();
    for (unsigned k = 0, e = phi->getNumEntries(); k < e; ++k) {
      auto entry = phi->getEntry(k);
      auto *vI = llvh::dyn_cast<Instruction>(entry.first);
      StaticShapeInfo shape = out_.find(entry.second)->second.get(vI);
      auto edge = getEdgeFact(entry.second, BB);
      if (edge && edge->object == vI)
        shape = StaticShapeInfo::createKnownStaticShape(edge->shape);
      ph = ph | shape;
    }
    s.set(phi, ph);
  }

  /// mov-like：s[mov] = s[src]（src 范围外/字面量 → Any）。
  void transferMovLike(State &s, SingleOperandInst *movLike) const {
    auto *src = llvh::dyn_cast<Instruction>(movLike->getSingleOperand());
    s.set(movLike, s.get(src));
  }

  /// 源头（范围内非 propagator，如 argument）→ Any。
  void transferObjectSource(State &s, Instruction *inst) const {
    s.set(inst, StaticShapeInfo::createAnyShapes());
  }

  /// pollute → ⊤_p：dom(s) 全置 AnyShapes（缺省 NoShape 不动）。
  void transferPolluting(State &s) const {
    s.setAll(StaticShapeInfo::createAnyShapes());
  }

  /// 关键指令：把 s[object] 同步到指令成员 objOperandShape_（只读 State）。
  void syncObjOperandShape(Instruction *inst, const State &s) const {
    Instruction *obj = nullptr;
    if (auto *load = llvh::dyn_cast<BaseLoadPropertyInst>(inst))
      obj = llvh::dyn_cast<Instruction>(load->getObject());
    else if (auto *store = llvh::dyn_cast<BaseStorePropertyInst>(inst))
      obj = llvh::dyn_cast<Instruction>(store->getObject());
    else if (auto *hss = llvh::dyn_cast<HasStaticShapeInst>(inst))
      obj = llvh::dyn_cast<Instruction>(hss->getArgument());
    else if (auto *tss = llvh::dyn_cast<TrySetStaticShapeInst>(inst))
      obj = llvh::dyn_cast<Instruction>(tss->getObject());
    else if (auto *lpn = llvh::dyn_cast<LoadParentNoTrapsInst>(inst))
      obj = llvh::dyn_cast<Instruction>(lpn->getObject());
    setStaticShapeInfo(inst, s.get(obj));
  }

  /// OUT[b] = transfer(IN[b])。
  State transfer(BasicBlock *BB, State s) {
    for (auto &I : *BB) {
      Instruction *inst = &I;
      if (isTargetInst(inst))
        syncObjOperandShape(inst, s);
      // pollute 对每条指令都判（写堆的不止关键指令，如 CallBuiltin）。
      if (polluting(inst))
        transferPolluting(s);
      // 范围外指令不进 State。
      if (!analysisScope_.count(inst))
        continue;
      // 范围内：propagator 传播；源头置 Any。
      if (auto *phi = llvh::dyn_cast<PhiInst>(inst)) {
        transferPhi(s, phi);
        continue;
      }
      if (auto *movLike = isMovLikeInst(inst)) {
        transferMovLike(s, movLike);
        continue;
      }
      transferObjectSource(s, inst);
    }
    return s;
  }

  /// worklist 不动点：从 entry 起传播，仅重算 OUT 变化的后继。
  /// 不可达块永不被处理，其 out_ 保持空(全 NoShape)。
  bool runToFixpoint() {
    bool changed = false;
    llvh::SmallVector<BasicBlock *, 16> wl;
    // 全量入队：保证首轮覆盖所有 BB（含循环 back-edge pred），避免因处理
    // 顺序使首轮 IN 基于未更新的 pred OUT。
    for (auto &BB : *F_)
      wl.push_back(&BB);
    while (!wl.empty()) {
      auto *BB = wl.pop_back_val();
      State newIn = computeIn(BB);
      State newOut = transfer(BB, std::move(newIn));
      auto itOut = out_.find(BB); // 预填保证命中
      if (itOut->second != newOut) {
        itOut->second = std::move(newOut);
        changed = true;
        for (auto *succ : successors(BB))
          wl.push_back(succ);
      }
    }
    return changed;
  }

 public:
  explicit Impl(Function *F) : F_(F) {}

  /// After convergence: replay transfer and collect every Known shape fact
  /// each polluting instruction truly killed (polluter + the object whose fact
  /// died). Reuses the real dataflow (join/pollute/propagator) — precise, not
  /// approximate: no false positives (a fact dead at a join is already Any, so
  /// a polluter doesn't count it), no false negatives (a guard's shape reaches
  /// State via mov-like/phi, so a polluter killing it is recorded).
  llvh::SmallVector<ShapeKill, 8> collectKills() {
    llvh::SmallVector<ShapeKill, 8> kills;
    for (BasicBlock &BB : *F_) {
      State s = computeIn(&BB);
      for (Instruction &I : BB) {
        Instruction *inst = &I;
        if (polluting(inst)) {
          for (const auto &kv : s)
            if (kv.second.status == StaticShapeInfo::KnownStaticShape)
              kills.push_back({inst, kv.first});
          transferPolluting(s);
        }
        if (!analysisScope_.count(inst))
          continue;
        if (auto *phi = llvh::dyn_cast<PhiInst>(inst)) {
          transferPhi(s, phi);
          continue;
        }
        if (auto *movLike = isMovLikeInst(inst)) {
          transferMovLike(s, movLike);
          continue;
        }
        transferObjectSource(s, inst);
      }
    }
    return kills;
  }
};

} // namespace static_shape_inference

StaticShapeInferenceRunner::StaticShapeInferenceRunner(Function *F)
    : impl_(new static_shape_inference::Impl(F)) {}
StaticShapeInferenceRunner::~StaticShapeInferenceRunner() = default;

void StaticShapeInferenceRunner::preIteration() {
  impl_->collectAnalysisScope();
  impl_->resetShapes();
  impl_->initOut();
}

bool StaticShapeInferenceRunner::step() {
  return impl_->runToFixpoint();
}

llvh::SmallVector<ShapeKill, 8> StaticShapeInferenceRunner::collectKills() {
  return impl_->collectKills();
}

} // namespace hermes

#undef DEBUG_TYPE
