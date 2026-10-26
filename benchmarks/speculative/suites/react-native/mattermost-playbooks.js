// Extracted from https://github.com/mattermost/mattermost-mobile at 8a9427f25ad9f16ed333b1865eff9c4b057cb093.
// Workload: mattermost-playbooks. See README.md, manifest.json and licenses/.
// Type/module syntax and formatting adapted; application algorithms retained.
// Copyright (c) 2015-present Mattermost, Inc. Apache-2.0.
const DEFAULT_TASK_FILTERS = {
  showChecked: true,
  showSkipped: true,
  showUnchecked: true,
  showAssignedToMe: false,
  showUnassigned: false,
  showAssignedToOthers: false,
};
const NO_TASK_FILTERS = {
  showChecked: false,
  showSkipped: false,
  showUnchecked: false,
  showAssignedToMe: false,
  showUnassigned: false,
  showAssignedToOthers: false,
};
const areDefaultTaskFilters = (filters) =>
  filters.showChecked &&
  filters.showSkipped &&
  filters.showUnchecked &&
  !filters.showAssignedToMe &&
  !filters.showUnassigned &&
  !filters.showAssignedToOthers;
const getAssigneeId = (item) => ("assigneeId" in item ? item.assigneeId : item.assignee_id);
const getConditionAction = (item) =>
  "conditionAction" in item ? item.conditionAction : item.condition_action;
const getCompletedAt = (item) => ("completedAt" in item ? item.completedAt : item.completed_at);
const getState = (item) => item.state;
const isItemVisible = (item) => !(getConditionAction(item) === "hidden" && !getCompletedAt(item));
const matchesTaskState = (item, filters) => {
  const state = getState(item);
  if (state === "closed") {
    return filters.showChecked;
  }
  if (state === "skipped") {
    return filters.showSkipped;
  }
  return filters.showUnchecked;
};
const hasAssigneeFilter = (filters) =>
  filters.showAssignedToMe || filters.showUnassigned || filters.showAssignedToOthers;
const matchesAssignee = (item, filters, currentUserId) => {
  if (!hasAssigneeFilter(filters)) {
    return true;
  }
  const assigneeId = getAssigneeId(item);
  if (!assigneeId) {
    return filters.showUnassigned;
  }
  if (assigneeId === currentUserId) {
    return filters.showAssignedToMe;
  }
  return filters.showAssignedToOthers;
};
const itemMatchesFilters = (item, filters, currentUserId) =>
  matchesTaskState(item, filters) && matchesAssignee(item, filters, currentUserId);
function getChecklistProgress(items) {
  const visibleItems = items.filter((item) => {
    const conditionAction =
      "conditionAction" in item ? item.conditionAction : item.condition_action;
    const completedAt = "completedAt" in item ? item.completedAt : item.completed_at;
    if (conditionAction === "hidden" && !completedAt) {
      return false;
    }
    return true;
  });
  const skippedCount = visibleItems.filter((item) => item.state === "skipped").length;
  const completedCount = visibleItems.filter((item) => item.state === "closed").length;
  const totalCount = visibleItems.length - skippedCount;
  const progress = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0;
  return {
    progress,
    skipped: Boolean(skippedCount),
    completed: completedCount,
    totalNumber: totalCount,
  };
}
function getProgressFromRun(run) {
  const allItems = run.checklists.reduce((acc, checklist) => {
    acc.push(...checklist.items);
    return acc;
  }, []);
  return getChecklistProgress(allItems).progress;
}
function areItemsOrdersEqual(fromRaw, fromRecord) {
  if (!fromRecord) {
    return false;
  }
  const rawLength = fromRaw.length;
  const recordLength = fromRecord.length;
  if (rawLength !== recordLength) {
    return false;
  }
  for (let i = 0; i < rawLength; i++) {
    if (fromRaw[i] !== fromRecord[i]) {
      return false;
    }
  }
  return true;
}
function safeParseJSON(rawJson) {
  let data = rawJson;
  try {
    if (typeof rawJson == "string") {
      data = JSON.parse(rawJson);
    }
  } catch {}
  return data;
}
const getSelectedOptionIds = (value, fieldType) => {
  if (!value) {
    return [];
  }
  if (fieldType === "select") {
    return [value];
  }
  if (fieldType === "multiselect") {
    try {
      const parsed = safeParseJSON(value);
      if (Array.isArray(parsed)) {
        return parsed;
      }
      return value
        .split(",")
        .map((id) => id.trim())
        .filter((id) => id !== "");
    } catch (error) {
      return value
        .split(",")
        .map((id) => id.trim())
        .filter((id) => id !== "");
    }
  }
  return [];
};
const parsePropertyFieldAttrs = (attrs) => {
  if (!attrs) {
    return null;
  }
  try {
    const parsed = safeParseJSON(attrs);
    if (!parsed || typeof parsed !== "object") {
      return null;
    }
    const options = Array.isArray(parsed.options) ? parsed.options : void 0;
    const parent_id = typeof parsed.parent_id === "string" ? parsed.parent_id : void 0;
    const sort_order = typeof parsed.sort_order === "number" ? parsed.sort_order : 999;
    const value_type = typeof parsed.value_type === "string" ? parsed.value_type : "";
    return { options, parent_id, sort_order, value_type };
  } catch {
    return null;
  }
};
const getPropertyFieldSortOrder = (propertyField) => {
  const attrs = parsePropertyFieldAttrs(propertyField.attrs);
  if (!attrs || typeof attrs.sort_order !== "number") {
    return 999;
  }
  return attrs.sort_order;
};
const sortPropertyFieldsByOrder = (propertyFields) => {
  return [...propertyFields].sort(
    (a, b) => getPropertyFieldSortOrder(a) - getPropertyFieldSortOrder(b)
  );
};
const formatPropertyFieldOptionsForSelector = (propertyField) => {
  if (propertyField.type !== "select" && propertyField.type !== "multiselect") {
    return [];
  }
  const attrs = parsePropertyFieldAttrs(propertyField.attrs);
  const options = attrs?.options;
  if (!options || !Array.isArray(options)) {
    return [];
  }
  return options.map((o) => ({ text: o.name, value: o.id }));
};
const getOptionNameById = (options, optionId) => {
  const found = options.find((o) => o.id === optionId);
  return found ? found.name : optionId;
};
const getPropertyValueDisplay = (propertyField, value) => {
  if (!value) {
    return "";
  }
  const rawValue = value.value || "";
  if (propertyField.type === "text") {
    return rawValue;
  }
  const attrs = parsePropertyFieldAttrs(propertyField.attrs);
  const options = attrs?.options || [];
  if (propertyField.type === "select") {
    if (!rawValue) {
      return "";
    }
    return getOptionNameById(options, rawValue);
  }
  if (propertyField.type === "multiselect") {
    const selectedIds = getSelectedOptionIds(rawValue, "multiselect");
    if (!selectedIds.length) {
      return "";
    }
    const names = selectedIds.map((id) => getOptionNameById(options, id));
    return names.join(", ");
  }
  logWarning("Unknown playbook run propertyField type, will use raw value", propertyField.type);
  return rawValue;
};
function getRunScheduledTimestamp(run) {
  const endAt = "endAt" in run ? run.endAt : run.end_at;
  const lastStatusUpdateAt =
    "lastStatusUpdateAt" in run ? run.lastStatusUpdateAt : run.last_status_update_at;
  const previousReminder = "previousReminder" in run ? run.previousReminder : run.previous_reminder;
  const isNextUpdateScheduled = previousReminder !== 0;
  const isFinished = isRunFinished(run);
  let timestamp = lastStatusUpdateAt;
  if (isFinished) {
    timestamp = endAt;
  } else if (isNextUpdateScheduled) {
    const previousReminderMillis = Math.floor(previousReminder / 1e6);
    timestamp = lastStatusUpdateAt + previousReminderMillis;
  }
  return timestamp;
}
function isRunFinished(run) {
  if (!run) {
    return true;
  }
  const currentStatus = "currentStatus" in run ? run.currentStatus : run.current_status;
  return currentStatus === "Finished";
}
function getMaxRunUpdateAt(runs) {
  let max = 0;
  for (const run of runs) {
    if (run.update_at > max) {
      max = run.update_at;
    }
  }
  return max;
}
function isPending(item) {
  return item.state === "" || item.state === "in_progress";
}
function isPostStatusUpdateProps(props) {
  if (typeof props !== "object" || props === null) {
    return false;
  }
  if (!("authorUsername" in props) || typeof props.authorUsername !== "string") {
    return false;
  }
  if (!("numTasks" in props) || typeof props.numTasks !== "number") {
    return false;
  }
  if (!("numTasksChecked" in props) || typeof props.numTasksChecked !== "number") {
    return false;
  }
  if (!("participantIds" in props) || !Array.isArray(props.participantIds)) {
    return false;
  }
  if (!props.participantIds.every((id) => typeof id === "string")) {
    return false;
  }
  if (!("playbookRunId" in props) || typeof props.playbookRunId !== "string") {
    return false;
  }
  if (!("runName" in props) || typeof props.runName !== "string") {
    return false;
  }
  return true;
}
const rnLogs = [];
function logWarning() {
  rnLogs.push(["warning"].concat(Array.from(arguments, String)));
}
function logError() {
  rnLogs.push(["error"].concat(Array.from(arguments, String)));
}
const rnPrint = typeof print === "function" ? print : console.log.bind(console);
function rnNow() {
  return typeof performance === "object" && typeof performance.now === "function"
    ? performance.now()
    : Date.now();
}
function rnAssert(condition, message) {
  if (!condition) throw new Error(message);
}
function rnHash(text) {
  let hash = 2166136261;
  for (let i = 0; i < text.length; i++) {
    hash = Math.imul(hash ^ text.charCodeAt(i), 16777619);
  }
  return hash >>> 0;
}
function rnRandom(seed) {
  return function () {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return seed;
  };
}
function rnValidate(fixtures, references) {
  rnAssert(fixtures.length === references.length, "Fixture count changed");
  let observation = 0;
  for (let i = 0; i < fixtures.length; i++) {
    const result = rnExecute(fixtures[i]);
    const actual = rnFingerprint(result);
    rnAssert(actual === references[i].fingerprint, "Result mismatch in fixture " + i);
    rnAssert(
      rnObserve(result) === references[i].observation,
      "Observation mismatch in fixture " + i
    );
    observation += references[i].observation;
  }
  return observation;
}
function rnCaptureReferences() {
  return rnCreateFixtures().map(function (fixture) {
    const result = rnExecute(fixture);
    return { fingerprint: rnFingerprint(result), observation: rnObserve(result) };
  });
}
function rnBenchmark(references) {
  const fixtures = rnCreateFixtures();
  const expectedPerIteration = rnValidate(fixtures, references);
  let checksum = 0;
  const start = rnNow();
  for (let iteration = 0; iteration < RN_ITERATIONS; iteration++) {
    for (let i = 0; i < fixtures.length; i++) {
      checksum += rnObserve(rnExecute(fixtures[i]));
    }
  }
  const elapsed = rnNow() - start;
  rnAssert(checksum === expectedPerIteration * RN_ITERATIONS, "Timed result checksum mismatch");
  rnValidate(fixtures, references);
  rnAssert(Number.isFinite(elapsed) && elapsed >= 0, "Invalid benchmark timer");
  rnPrint("Checksum: " + checksum);
  rnPrint("Time: " + Math.max(1, elapsed));
}
const RN_ITERATIONS = 60;
function rnCreateFixtures() {
  return Array.from({ length: 8 }, function (_, variant) {
    const checklists = [];
    for (let j = 0; j < 8; j++) {
      const items = [];
      for (let i = 0; i < 128; i++) {
        const item = {
          id: "item-" + j + "-" + i,
          state: ["", "in_progress", "closed", "skipped"][i % 4],
        };
        const assignee = i % 3 ? "user-" + (i % 5) : "";
        if (variant % 2)
          Object.assign(item, {
            assigneeId: assignee,
            conditionAction: i % 7 ? "" : "hidden",
            completedAt: i % 4 === 2 ? 1 : 0,
          });
        else
          Object.assign(item, {
            assignee_id: assignee,
            condition_action: i % 7 ? "" : "hidden",
            completed_at: i % 4 === 2 ? 1 : 0,
          });
        items.push(item);
      }
      checklists.push({ id: "list-" + j, items });
    }
    const filters = {
      ...DEFAULT_TASK_FILTERS,
      showChecked: variant % 3 !== 0,
      showSkipped: variant % 2 === 0,
      showAssignedToMe: variant > 3,
      showUnassigned: variant === 7,
    };
    const fields = [];
    const values = {};
    for (let i = 0; i < 32; i++) {
      const type = ["text", "select", "multiselect", "future-type"][i % 4];
      const id = "field-" + i;
      const attrs = {
        sort_order: (i * 7) % 32,
        value_type: "",
        parent_id: "run-" + variant,
        options: [
          { id: "a", name: "Alpha" },
          { id: "b", name: "Beta" },
        ],
      };
      fields.push({ id, type, attrs: i % 13 === 0 ? "invalid JSON" : JSON.stringify(attrs) });
      values[id] = {
        value: type === "text" ? "Text " + i : type === "select" ? "b" : '["a","missing"]',
      };
    }
    const run = { checklists, update_at: 1e5 + variant };
    if (variant % 2)
      Object.assign(run, {
        endAt: 2e5,
        lastStatusUpdateAt: 1e5,
        previousReminder: variant * 1e9,
        currentStatus: variant % 3 ? "InProgress" : "Finished",
      });
    else
      Object.assign(run, {
        end_at: 2e5,
        last_status_update_at: 1e5,
        previous_reminder: variant * 1e9,
        current_status: variant % 3 ? "InProgress" : "Finished",
      });
    return { run, filters, fields, values };
  });
}
function rnExecute(fixture) {
  rnLogs.length = 0;
  const rows = fixture.run.checklists.map(function (checklist) {
    const visible = checklist.items.filter(function (item) {
      return isItemVisible(item) && itemMatchesFilters(item, fixture.filters, "user-1");
    });
    const ids = visible.map(function (item) {
      return item.id;
    });
    return {
      ids,
      progress: getChecklistProgress(visible),
      same: areItemsOrdersEqual(ids, ids.slice()),
      pending: visible.filter(isPending).length,
    };
  });
  const properties = sortPropertyFieldsByOrder(fixture.fields).map(function (field) {
    return {
      id: field.id,
      order: getPropertyFieldSortOrder(field),
      options: formatPropertyFieldOptionsForSelector(field),
      display: getPropertyValueDisplay(field, fixture.values[field.id]),
    };
  });
  const itemCount = fixture.run.checklists.reduce(function (n, checklist) {
    return n + checklist.items.length;
  }, 0);
  const status = {
    authorUsername: "user-1",
    numTasks: itemCount,
    numTasksChecked: rows.reduce(function (n, row) {
      return n + row.progress.completed;
    }, 0),
    participantIds: ["user-1", "user-2"],
    playbookRunId: "run-1",
    runName: "Fixture run",
  };
  const invalidStatus = Object.assign({}, status, { participantIds: ["user-1", 42] });
  return {
    rows,
    progress: getProgressFromRun(fixture.run),
    defaultFilters: areDefaultTaskFilters(fixture.filters),
    properties,
    scheduled: getRunScheduledTimestamp(fixture.run),
    finished: isRunFinished(fixture.run),
    latestUpdate: getMaxRunUpdateAt([fixture.run, { update_at: 1 }]),
    logs: rnLogs.slice(),
    status,
    validStatus: isPostStatusUpdateProps(status),
    invalidStatusAccepted: isPostStatusUpdateProps(invalidStatus),
  };
}
function rnObserve(result) {
  return (
    result.rows.reduce(function (n, row) {
      return n + row.ids.length + row.progress.progress + row.pending;
    }, result.progress) +
    result.properties.reduce(function (n, field) {
      return n + field.display.length + field.options.length;
    }, 0) +
    result.scheduled +
    result.latestUpdate +
    result.logs.length
  );
}
function rnFingerprint(result) {
  rnAssert(
    result.rows.every(function (row) {
      return row.same;
    }),
    "Checklist order mismatch"
  );
  rnAssert(!areItemsOrdersEqual(["a"], ["b"]), "Different checklist orders accepted");
  rnAssert(
    result.properties.length === 32 && result.logs.length === 8,
    "Playbook property conversion mismatch"
  );
  rnAssert(result.validStatus && !result.invalidStatusAccepted, "Invalid playbook status accepted");
  return rnHash(JSON.stringify(result));
}
rnBenchmark([
  { "fingerprint": 3710610048, "observation": 301479 },
  { "fingerprint": 3793699891, "observation": 202816 },
  { "fingerprint": 2866914108, "observation": 204033 },
  { "fingerprint": 4219274951, "observation": 301266 },
  { "fingerprint": 3799153729, "observation": 204835 },
  { "fingerprint": 11951249, "observation": 205812 },
  { "fingerprint": 4217806754, "observation": 300541 },
  { "fingerprint": 1789630299, "observation": 208214 },
]);
