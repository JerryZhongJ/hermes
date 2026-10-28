/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#ifndef HERMES_BCGEN_SH_CALLGRAPHRUNTIME_H
#define HERMES_BCGEN_SH_CALLGRAPHRUNTIME_H

namespace hermes {
namespace sh {

// Emitted into the generated C translation unit. No VM ABI changes or
// allocation of GC objects are needed. Metadata is indexed by register-stack
// offset, rather than a shadow call stack, so JS exception unwinding needs no
// matching profiling pops. Validate a candidate caller against its live VM
// closure before using a slot: native frames may reuse an unwound SH slot.
static constexpr const char *callGraphRuntime = R"DCG(
#include <stdio.h>
#include <string.h>

typedef struct {
  uint32_t function_plus_one;
  uint32_t site_plus_one;
} SHDCGFrame;

typedef struct SHDCGState {
  SHRuntime *runtime;
  SHDCGFrame *frames;
  size_t capacity;
  struct SHDCGState *next;
} SHDCGState;

typedef struct {
  uint32_t caller_plus_one, site_plus_one, callee_plus_one, bridges;
  unsigned long long count;
} SHDCGEdge;

static SHDCGState *__dcg_states;
static SHDCGEdge *__dcg_edges;
static size_t __dcg_edge_capacity, __dcg_edge_size;
static bool __dcg_registered;
static void __dcg_dump(void);

static void *__dcg_alloc(size_t count, size_t size) {
  void *ptr = calloc(count, size);
  if (!ptr) {
    fputs("SH call graph: out of memory\n", stderr);
    abort();
  }
  return ptr;
}

static uint64_t __dcg_hash(SHDCGEdge edge) {
  uint64_t h = ((uint64_t)edge.site_plus_one << 32) | edge.callee_plus_one;
  h ^= (uint64_t)edge.caller_plus_one * UINT64_C(0x9e3779b97f4a7c15);
  h ^= (uint64_t)edge.bridges * UINT64_C(0xbf58476d1ce4e5b9);
  h = (h ^ (h >> 30)) * UINT64_C(0xbf58476d1ce4e5b9);
  h = (h ^ (h >> 27)) * UINT64_C(0x94d049bb133111eb);
  return h ^ (h >> 31);
}

static size_t __dcg_find(SHDCGEdge key, SHDCGEdge *table, size_t capacity) {
  size_t i = (size_t)__dcg_hash(key) & (capacity - 1);
  while (table[i].callee_plus_one &&
         (table[i].caller_plus_one != key.caller_plus_one ||
          table[i].site_plus_one != key.site_plus_one ||
          table[i].callee_plus_one != key.callee_plus_one ||
          table[i].bridges != key.bridges))
    i = (i + 1) & (capacity - 1);
  return i;
}

static void __dcg_add_edge(SHDCGEdge key) {
  if ((__dcg_edge_size + 1) * 4 >= __dcg_edge_capacity * 3) {
    size_t capacity = __dcg_edge_capacity ? __dcg_edge_capacity * 2 : 1024;
    SHDCGEdge *table = (SHDCGEdge *)__dcg_alloc(capacity, sizeof(*table));
    for (size_t i = 0; i < __dcg_edge_capacity; ++i)
      if (__dcg_edges[i].callee_plus_one)
        table[__dcg_find(__dcg_edges[i], table, capacity)] = __dcg_edges[i];
    free(__dcg_edges);
    __dcg_edges = table;
    __dcg_edge_capacity = capacity;
  }
  size_t i = __dcg_find(key, __dcg_edges, __dcg_edge_capacity);
  if (!__dcg_edges[i].callee_plus_one) {
    __dcg_edges[i] = key;
    ++__dcg_edge_size;
  }
  ++__dcg_edges[i].count;
}

static __attribute__((noinline)) SHDCGState *__dcg_enter(
    SHRuntime *shr, SHLegacyValue *frame, uint32_t function_id) {
  if (!__dcg_registered) {
    if (atexit(__dcg_dump)) abort();
    __dcg_registered = true;
  }
  SHDCGState *state = __dcg_states;
  while (state && state->runtime != shr) state = state->next;
  if (!state) {
    state = (SHDCGState *)__dcg_alloc(1, sizeof(*state));
    state->runtime = shr;
    state->next = __dcg_states;
    __dcg_states = state;
  }

  SHDCGEdge edge = {0, 0, function_id + 1, 0, 0};
  SHLegacyValue *caller = _sh_stackframe_get_previous_frame_pointer(frame);
  // registerStackStart is the VM's end-of-stack sentinel, not a real frame.
  while (caller && caller > shr->registerStackStart && caller < frame) {
    size_t index = (size_t)(caller - shr->registerStackStart);
    if (index < state->capacity) {
      SHDCGFrame candidate = state->frames[index];
      if (candidate.function_plus_one &&
          _sh_ljs_has_closure_target(shr,
              *_sh_stackframe_CalleeClosureOrCB_ptr(caller),
              __dcg_functions[candidate.function_plus_one - 1])) {
        edge.caller_plus_one = candidate.function_plus_one;
        edge.site_plus_one = candidate.site_plus_one;
        break;
      }
    }
    ++edge.bridges;
    SHLegacyValue *previous = _sh_stackframe_get_previous_frame_pointer(caller);
    if (!previous || previous >= caller) break;
    caller = previous;
  }
  __dcg_add_edge(edge);
  ++__dcg_entries[function_id];

  size_t index = (size_t)(frame - shr->registerStackStart);
  if (index >= state->capacity) {
    size_t capacity = state->capacity ? state->capacity : 1024;
    while (index >= capacity) capacity *= 2;
    SHDCGFrame *frames = (SHDCGFrame *)__dcg_alloc(capacity, sizeof(*frames));
    if (state->capacity)
      memcpy(frames, state->frames, state->capacity * sizeof(*frames));
    free(state->frames);
    state->frames = frames;
    state->capacity = capacity;
  }
  state->frames[index] = (SHDCGFrame){function_id + 1, 0};
  return state;
}

static void __dcg_dump(void) {
  const char *path = getenv("SH_CALL_GRAPH");
  FILE *out = path && *path ? fopen(path, "a") : stderr;
  if (!out) {
    perror("SH_CALL_GRAPH");
    abort();
  }
  fprintf(out, "{\"type\":\"summary\",\"schema\":1,\"functions\":%zu,"
      "\"sites\":%zu,\"edges\":%zu}\n", __dcg_function_count,
      __dcg_site_count, __dcg_edge_size);
  for (size_t i = 0; i < __dcg_function_count; ++i)
    fprintf(out, "%s,\"entries\":%llu}\n", __dcg_function_metadata[i],
        __dcg_entries[i]);
  for (size_t i = 0; i < __dcg_site_count; ++i)
    fprintf(out, "%s,\"executions\":%llu}\n", __dcg_site_metadata[i],
        __dcg_site_executions[i]);
  for (size_t i = 0; i < __dcg_edge_capacity; ++i) {
    SHDCGEdge edge = __dcg_edges[i];
    if (edge.callee_plus_one)
      fprintf(out, "{\"type\":\"edge\",\"caller\":%lld,\"site\":%lld,"
          "\"callee\":%u,\"bridges\":%u,\"count\":%llu}\n",
          (long long)edge.caller_plus_one - 1,
          (long long)edge.site_plus_one - 1, edge.callee_plus_one - 1,
          edge.bridges, edge.count);
  }
  if (ferror(out) || fflush(out)) abort();
  if (out != stderr && fclose(out)) abort();
}
)DCG";

} // namespace sh
} // namespace hermes

#endif
