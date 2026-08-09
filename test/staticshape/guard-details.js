// RUN: %shermes -O0 -Xcustom-opt=insertguard -instrument-guards -exec -annotation-file=%S/guard-details.json %s 2>&1 | %FileCheck %s --check-prefix=COUNT --implicit-check-not=HERMES_GUARD_DETAIL
// RUN: %shermes -O0 -Xcustom-opt=insertguard -instrument-guards-details=0 -exec -annotation-file=%S/guard-details.json %s 2>&1 | %FileCheck %s --check-prefix=DETAIL

function read(o) {
  return o.x;
}

var good = {x: 1};
print(read(good));
print(read({x: 2}));
print(read({y: 3}));
print(read(1));

// COUNT: 1
// COUNT-NEXT: 2
// COUNT-NEXT: undefined
// COUNT-NEXT: undefined
// COUNT: ann#0 [shape guard X] @5:10-5:11: success=1, fail=3
// COUNT: ann#1 [shape binding X] @8:12-8:18: success=1, fail=0

// DETAIL: 1
// DETAIL-NEXT: 2
// DETAIL-NEXT: undefined
// DETAIL-NEXT: undefined
// DETAIL: HERMES_GUARD_DETAIL {"version":1,"annotationId":0,"targetShapeIndex":0,"reason":"non_object","count":1,"actual":null,"target":null}
// DETAIL: HERMES_GUARD_DETAIL {"version":1,"annotationId":0,"targetShapeIndex":0,"reason":"identity_mismatch_structurally_compatible","count":1,"actual":{{.*}}"name":"x"{{.*}}"target":{{.*}}"name":"x"{{.*}}}
// DETAIL: HERMES_GUARD_DETAIL {"version":1,"annotationId":0,"targetShapeIndex":0,"reason":"structurally_incompatible","count":1,"actual":{{.*}}"name":"y"{{.*}}"target":{{.*}}"name":"x"{{.*}}}
// DETAIL: ann#0 [shape guard X] @5:10-5:11: success=1, fail=3
// DETAIL: ann#1 [shape binding X] @8:12-8:18: success=1, fail=0
