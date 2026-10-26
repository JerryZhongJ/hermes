// Extracted from https://github.com/Expensify/App at 0eff10433514a9be0faa2a568d5779dc06e05d44.
// Workload: expensify-report-sort. See README.md, manifest.json and licenses/.
// Type/module syntax and formatting adapted; application algorithms retained.
// Copyright (c) 2020 Expensify Inc. MIT License.
const CONST = {
  "REPORT": {
    "ACTIONS": {
      "TYPE": {
        "IOU": "IOU",
        "DEW_APPROVE_FAILED": "DEWAPPROVEFAILED",
        "CREATED": "CREATED",
        "REPORT_PREVIEW": "REPORTPREVIEW",
        "ADD_COMMENT": "ADDCOMMENT",
        "SUBMITTED": "SUBMITTED",
        "APPROVED": "APPROVED",
        "FORWARDED": "FORWARDED",
        "RETRACTED": "RETRACTED",
        "REOPENED": "REOPENED",
        "DEW_SUBMIT_FAILED": "DEWSUBMITFAILED",
      },
    },
  },
  "IOU": { "REPORT_ACTION_TYPE": { "TRACK": "track", "PAY": "pay", "CREATE": "create" } },
  "RED_BRICK_ROAD_PENDING_ACTION": { "DELETE": "delete" },
  "ACCOUNT_ID": { "CONCIERGE": 8392101 },
  "MODERATION": {
    "MODERATOR_DECISION_APPROVED": "approved",
    "MODERATOR_DECISION_PENDING": "pending",
    "MODERATOR_DECISION_PENDING_REMOVE": "pendingRemove",
  },
  "EXPENSE_PENDING_ACTION": { "SUBMIT": "SUBMIT", "APPROVE": "APPROVE" },
};
function getOriginalMessage(reportAction) {
  const candidate = !Array.isArray(reportAction?.message)
    ? (reportAction?.message ?? reportAction?.originalMessage)
    : reportAction?.originalMessage;
  if (candidate === null || typeof candidate !== "object") {
    return void 0;
  }
  return candidate;
}
function getReportActionMessage(reportAction) {
  return Array.isArray(reportAction?.message) ? reportAction?.message.at(0) : reportAction?.message;
}
function isActionOfType(action, actionName) {
  return action?.actionName === actionName;
}
function isMoneyRequestAction(reportAction) {
  return isActionOfType(reportAction, CONST.REPORT.ACTIONS.TYPE.IOU);
}
function isDynamicExternalWorkflowApproveFailedAction(reportAction) {
  return isActionOfType(reportAction, CONST.REPORT.ACTIONS.TYPE.DEW_APPROVE_FAILED);
}
function getSortedReportActions(reportActions, shouldSortInDescendingOrder = false) {
  if (!Array.isArray(reportActions)) {
    throw new Error(
      `ReportActionsUtils.getSortedReportActions requires an array, received ${typeof reportActions}`
    );
  }
  const invertedMultiplier = shouldSortInDescendingOrder ? -1 : 1;
  const sortedActions = reportActions?.filter(Boolean).sort((first, second) => {
    if (
      (first.actionName === CONST.REPORT.ACTIONS.TYPE.CREATED ||
        second.actionName === CONST.REPORT.ACTIONS.TYPE.CREATED) &&
      first.actionName !== second.actionName
    ) {
      return (first.actionName === CONST.REPORT.ACTIONS.TYPE.CREATED ? -1 : 1) * invertedMultiplier;
    }
    if (first.created === void 0 || second.created === void 0) {
      return (first.created === void 0 ? -1 : 1) * invertedMultiplier;
    }
    if (first.created !== second.created) {
      return (first.created < second.created ? -1 : 1) * invertedMultiplier;
    }
    if (
      (first.actionName === CONST.REPORT.ACTIONS.TYPE.REPORT_PREVIEW ||
        second.actionName === CONST.REPORT.ACTIONS.TYPE.REPORT_PREVIEW) &&
      first.actionName !== second.actionName
    ) {
      return (
        (first.actionName === CONST.REPORT.ACTIONS.TYPE.REPORT_PREVIEW ? 1 : -1) *
        invertedMultiplier
      );
    }
    return (first.reportActionID < second.reportActionID ? -1 : 1) * invertedMultiplier;
  });
  return sortedActions;
}
function getCombinedReportActions(
  reportActions,
  transactionThreadReportID,
  transactionThreadReportActions,
  isSelfDM = false
) {
  const isSentMoneyReport = reportActions.some((action) => isSentMoneyReportAction(action));
  if (isSentMoneyReport) {
    return reportActions.filter((action) => !isIOUCreateAction(action));
  }
  if (!transactionThreadReportID) {
    return reportActions;
  }
  const transactionThreadCreatedAction = transactionThreadReportActions?.find(
    (action) => action.actionName === CONST.REPORT.ACTIONS.TYPE.CREATED
  );
  const parentReportCreatedAction = reportActions?.find(
    (action) => action.actionName === CONST.REPORT.ACTIONS.TYPE.CREATED
  );
  let filteredTransactionThreadReportActions = transactionThreadReportActions;
  let filteredParentReportActions = reportActions;
  if (
    transactionThreadCreatedAction &&
    parentReportCreatedAction &&
    transactionThreadCreatedAction.created > parentReportCreatedAction.created
  ) {
    filteredTransactionThreadReportActions = transactionThreadReportActions?.filter(
      (action) => action.actionName !== CONST.REPORT.ACTIONS.TYPE.CREATED
    );
  } else if (transactionThreadCreatedAction) {
    filteredParentReportActions = reportActions?.filter(
      (action) => action.actionName !== CONST.REPORT.ACTIONS.TYPE.CREATED
    );
  }
  const filteredReportActions = [
    ...filteredParentReportActions,
    ...filteredTransactionThreadReportActions,
  ].filter((action) => {
    if (isIOUCreateAction(action)) {
      return false;
    }
    if (!isMoneyRequestAction(action)) {
      return true;
    }
    if (isSelfDM) {
      return true;
    }
    return getOriginalMessage(action)?.type !== CONST.IOU.REPORT_ACTION_TYPE.TRACK;
  });
  return getSortedReportActions(filteredReportActions, true);
}
function isSentMoneyReportAction(reportAction) {
  return (
    isActionOfType(reportAction, CONST.REPORT.ACTIONS.TYPE.IOU) &&
    getOriginalMessage(reportAction)?.type === CONST.IOU.REPORT_ACTION_TYPE.PAY &&
    !!getOriginalMessage(reportAction)?.IOUDetails
  );
}
function isIOUCreateAction(action) {
  return (
    isMoneyRequestAction(action) &&
    getOriginalMessage(action)?.type === CONST.IOU.REPORT_ACTION_TYPE.CREATE
  );
}
function findPreviousAction(reportActions, actionIndex, isOffline) {
  for (let i = actionIndex + 1; i < reportActions.length; i++) {
    const action = reportActions.at(i);
    if (!isOffline && action?.pendingAction === CONST.RED_BRICK_ROAD_PENDING_ACTION.DELETE) {
      continue;
    }
    if (action?.shouldShow === false) {
      continue;
    }
    return action;
  }
  return void 0;
}
function findNextAction(reportActions, actionIndex, isOffline) {
  for (let i = actionIndex - 1; i >= 0; i--) {
    const action = reportActions.at(i);
    if (!isOffline && action?.pendingAction === CONST.RED_BRICK_ROAD_PENDING_ACTION.DELETE) {
      continue;
    }
    if (action?.shouldShow === false) {
      continue;
    }
    return action;
  }
  return void 0;
}
function isNewerReportAction(a, b) {
  if (a.actionName === CONST.REPORT.ACTIONS.TYPE.CREATED) {
    return false;
  }
  if (b.actionName === CONST.REPORT.ACTIONS.TYPE.CREATED) {
    return true;
  }
  if (a.created === void 0 && b.created !== void 0) {
    return false;
  }
  if (a.created !== void 0 && b.created === void 0) {
    return true;
  }
  if (a.created !== b.created) {
    return a.created > b.created;
  }
  if (
    a.actionName === CONST.REPORT.ACTIONS.TYPE.REPORT_PREVIEW &&
    b.actionName !== CONST.REPORT.ACTIONS.TYPE.REPORT_PREVIEW
  ) {
    return true;
  }
  if (
    b.actionName === CONST.REPORT.ACTIONS.TYPE.REPORT_PREVIEW &&
    a.actionName !== CONST.REPORT.ACTIONS.TYPE.REPORT_PREVIEW
  ) {
    return false;
  }
  return a.reportActionID > b.reportActionID;
}
function isOlderReportAction(a, b) {
  return isNewerReportAction(b, a);
}
function getDelegateAccountIDFromReportAction(reportAction) {
  if (!reportAction || reportAction?.actorAccountID === CONST.ACCOUNT_ID.CONCIERGE) {
    return void 0;
  }
  if (reportAction.delegateAccountID) {
    return reportAction.delegateAccountID;
  }
  const originalMessage = getOriginalMessage(reportAction);
  if (!originalMessage) {
    return void 0;
  }
  if ("delegateAccountID" in originalMessage) {
    return originalMessage.delegateAccountID;
  }
  return void 0;
}
function getHumanAgentAccountIDFromReportAction(reportAction) {
  if (!reportAction || reportAction?.actorAccountID !== CONST.ACCOUNT_ID.CONCIERGE) {
    return void 0;
  }
  const originalMessage = getOriginalMessage(reportAction);
  if (!originalMessage) {
    return void 0;
  }
  if (
    "humanAgentAccountID" in originalMessage &&
    typeof originalMessage.humanAgentAccountID === "number"
  ) {
    return originalMessage.humanAgentAccountID;
  }
  return void 0;
}
function getModerationFlagState(reportAction) {
  if (reportAction?.actionName !== CONST.REPORT.ACTIONS.TYPE.ADD_COMMENT) {
    return { latestDecision: void 0, hasBeenFlagged: false };
  }
  const latestDecision = getReportActionMessage(reportAction)?.moderationDecision?.decision;
  const hasBeenFlagged =
    !!latestDecision &&
    ![
      CONST.MODERATION.MODERATOR_DECISION_APPROVED,
      CONST.MODERATION.MODERATOR_DECISION_PENDING,
    ].some((item) => item === latestDecision) &&
    !isPendingRemove(reportAction);
  return { latestDecision, hasBeenFlagged };
}
function isPendingRemove(reportAction) {
  return (
    getReportActionMessage(reportAction)?.moderationDecision?.decision ===
    CONST.MODERATION.MODERATOR_DECISION_PENDING_REMOVE
  );
}
function isSubmittedAction(reportAction) {
  return isActionOfType(reportAction, CONST.REPORT.ACTIONS.TYPE.SUBMITTED);
}
function isApprovedAction(reportAction) {
  return isActionOfType(reportAction, CONST.REPORT.ACTIONS.TYPE.APPROVED);
}
function isForwardedAction(reportAction) {
  return isActionOfType(reportAction, CONST.REPORT.ACTIONS.TYPE.FORWARDED);
}
function isRetractedAction(reportAction) {
  return isActionOfType(reportAction, CONST.REPORT.ACTIONS.TYPE.RETRACTED);
}
function isReopenedAction(reportAction) {
  return isActionOfType(reportAction, CONST.REPORT.ACTIONS.TYPE.REOPENED);
}
function isDynamicExternalWorkflowSubmitFailedAction(reportAction) {
  return isActionOfType(reportAction, CONST.REPORT.ACTIONS.TYPE.DEW_SUBMIT_FAILED);
}
function getMostRecentActiveDEWSubmitFailedAction(reportActions) {
  const actionsArray = Array.isArray(reportActions)
    ? reportActions
    : Object.values(reportActions ?? {});
  let mostRecentDewSubmitFailedAction;
  let mostRecentSubmittedAction;
  for (const action of actionsArray) {
    if (isDynamicExternalWorkflowSubmitFailedAction(action)) {
      if (
        !mostRecentDewSubmitFailedAction ||
        (action.created &&
          mostRecentDewSubmitFailedAction.created &&
          action.created > mostRecentDewSubmitFailedAction.created)
      ) {
        mostRecentDewSubmitFailedAction = action;
      }
    } else if (isSubmittedAction(action)) {
      if (
        !mostRecentSubmittedAction ||
        (action.created &&
          mostRecentSubmittedAction.created &&
          action.created > mostRecentSubmittedAction.created)
      ) {
        mostRecentSubmittedAction = action;
      }
    }
  }
  if (!mostRecentDewSubmitFailedAction) {
    return void 0;
  }
  if (
    !mostRecentSubmittedAction ||
    mostRecentDewSubmitFailedAction.created > mostRecentSubmittedAction.created
  ) {
    return mostRecentDewSubmitFailedAction;
  }
  return void 0;
}
function isActionThatSupersedesDEWApproveFailure(action) {
  return (
    isApprovedAction(action) ||
    isForwardedAction(action) ||
    isRetractedAction(action) ||
    isReopenedAction(action)
  );
}
function getMostRecentActiveDEWApproveFailedAction(reportActions) {
  const actionsArray = Array.isArray(reportActions)
    ? reportActions
    : Object.values(reportActions ?? {});
  let mostRecentDewApproveFailedAction;
  let mostRecentSupersedingAction;
  for (const action of actionsArray) {
    if (isDynamicExternalWorkflowApproveFailedAction(action)) {
      if (
        !mostRecentDewApproveFailedAction ||
        (action.created &&
          mostRecentDewApproveFailedAction.created &&
          action.created > mostRecentDewApproveFailedAction.created)
      ) {
        mostRecentDewApproveFailedAction = action;
      }
    } else if (isActionThatSupersedesDEWApproveFailure(action)) {
      if (
        !mostRecentSupersedingAction ||
        (action.created &&
          mostRecentSupersedingAction.created &&
          action.created > mostRecentSupersedingAction.created)
      ) {
        mostRecentSupersedingAction = action;
      }
    }
  }
  if (!mostRecentDewApproveFailedAction) {
    return void 0;
  }
  if (
    !mostRecentSupersedingAction ||
    mostRecentDewApproveFailedAction.created > mostRecentSupersedingAction.created
  ) {
    return mostRecentDewApproveFailedAction;
  }
  return void 0;
}
function hasPendingDEWSubmit(reportMetadata, isDEWPolicy) {
  return (
    isDEWPolicy && reportMetadata?.pendingExpenseAction === CONST.EXPENSE_PENDING_ACTION.SUBMIT
  );
}
function hasPendingDEWApprove(reportMetadata, isDEWPolicy) {
  return (
    isDEWPolicy && reportMetadata?.pendingExpenseAction === CONST.EXPENSE_PENDING_ACTION.APPROVE
  );
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
const RN_ITERATIONS = 8;
function rnCreateFixtures() {
  const random = rnRandom(1163415621);
  const actions = [];
  const kinds = [
    "ADDCOMMENT",
    "IOU",
    "REPORTPREVIEW",
    "MODIFIEDEXPENSE",
    "CLOSED",
    CONST.REPORT.ACTIONS.TYPE.DEW_SUBMIT_FAILED,
    CONST.REPORT.ACTIONS.TYPE.DEW_APPROVE_FAILED,
    CONST.REPORT.ACTIONS.TYPE.SUBMITTED,
    CONST.REPORT.ACTIONS.TYPE.APPROVED,
    CONST.REPORT.ACTIONS.TYPE.FORWARDED,
    CONST.REPORT.ACTIONS.TYPE.RETRACTED,
    CONST.REPORT.ACTIONS.TYPE.REOPENED,
  ];
  const base = Date.UTC(2026, 0, 1);
  for (let i = 0; i < 1e4; i++) {
    const action = {
      actionName: kinds[random() % kinds.length],
      reportActionID: String(1e5 + i),
      actorAccountID: random() % 128,
      created: new Date(base + (random() % 512) * 1e3).toISOString(),
      message: [{ type: "COMMENT", text: "Expense discussion " + i }],
      originalMessage: {
        type: ["create", "track", "pay"][i % 3],
        IOUDetails: i % 17 === 0 ? { amount: 1e3 } : void 0,
        delegateAccountID: i % 7 === 0 ? 42 : void 0,
        humanAgentAccountID: i % 5 === 0 ? 99 : void 0,
      },
      pendingAction: i % 13 === 0 ? CONST.RED_BRICK_ROAD_PENDING_ACTION.DELETE : void 0,
      shouldShow: i % 11 !== 0,
    };
    if (i % 19 === 0) action.actorAccountID = CONST.ACCOUNT_ID.CONCIERGE;
    if (i % 23 === 0)
      action.message[0].moderationDecision = {
        decision: [
          CONST.MODERATION.MODERATOR_DECISION_APPROVED,
          CONST.MODERATION.MODERATOR_DECISION_PENDING,
          CONST.MODERATION.MODERATOR_DECISION_PENDING_REMOVE,
          "rejected",
        ][i % 4],
      };
    actions.push(action);
  }
  actions[0].actionName = "CREATED";
  actions[0].created = new Date(base + 1e6).toISOString();
  actions[1].created = void 0;
  actions.push(null, void 0);
  const requestedActions = actions.filter(Boolean).map(function (action) {
    return Object.assign({}, action, {
      originalMessage: Object.assign({}, action.originalMessage, { IOUDetails: void 0 }),
    });
  });
  const edge = [
    { actionName: "REPORTPREVIEW", reportActionID: "15", created: "2026-01-01" },
    { actionName: "ADDCOMMENT", reportActionID: "12", created: "2026-01-01" },
    { actionName: "ADDCOMMENT", reportActionID: "11", created: "2026-01-01" },
    { actionName: "CREATED", reportActionID: "13", created: "2026-02-01" },
    { actionName: "IOU", reportActionID: "14" },
    null,
  ];
  return [
    { actions, descending: false },
    { actions, descending: true },
    { actions: requestedActions, descending: false },
    { actions: requestedActions, descending: true },
    { actions: edge, descending: false },
    { actions: edge, descending: true },
    { actions: [], descending: false },
    {
      actions: [
        {
          actionName: "CREATED",
          reportActionID: "21",
          created: "2026-01-01",
          message: "legacy notification",
        },
        {
          actionName: "IOU",
          reportActionID: "22",
          created: "2026-01-02",
          message: { type: "create" },
        },
        {
          actionName: "ADDCOMMENT",
          reportActionID: "23",
          created: "2026-01-03",
          message: { text: "Modern message", moderationDecision: { decision: "pendingRemove" } },
        },
        {
          actionName: "ADDCOMMENT",
          reportActionID: "24",
          created: "2026-01-04",
          message: { text: "Flagged comment", moderationDecision: { decision: "rejected" } },
        },
      ],
      descending: true,
    },
  ];
}
function rnExecute(fixture) {
  const actions = getSortedReportActions(fixture.actions, fixture.descending);
  const split = Math.floor(actions.length / 2);
  const parent = actions.slice(0, split);
  const thread = actions.slice(split);
  const combined = getCombinedReportActions(parent, "thread-1", thread, fixture.descending);
  const noThread = getCombinedReportActions(parent, null, thread);
  const annotations = actions.map(function (action, index) {
    const previous = findPreviousAction(actions, index, fixture.descending);
    const next = findNextAction(actions, index, fixture.descending);
    return {
      previous: previous ? previous.reportActionID : "",
      next: next ? next.reportActionID : "",
      newer: previous ? isNewerReportAction(action, previous) : false,
      older: next ? isOlderReportAction(action, next) : false,
      delegate: getDelegateAccountIDFromReportAction(action),
      agent: getHumanAgentAccountIDFromReportAction(action),
      moderation: getModerationFlagState(action),
    };
  });
  const metadata = {
    pendingExpenseAction: fixture.descending
      ? CONST.EXPENSE_PENDING_ACTION.SUBMIT
      : CONST.EXPENSE_PENDING_ACTION.APPROVE,
  };
  return {
    actions: actions.map(function (action) {
      return action.reportActionID;
    }),
    combined: combined.map(function (action) {
      return action.reportActionID;
    }),
    annotations,
    noThread: noThread.length,
    submitFailed: getMostRecentActiveDEWSubmitFailedAction(actions)?.reportActionID,
    approveFailed: getMostRecentActiveDEWApproveFailedAction(Object.assign({}, actions))
      ?.reportActionID,
    pendingSubmit: hasPendingDEWSubmit(metadata, true),
    pendingApprove: hasPendingDEWApprove(metadata, true),
  };
}
function rnObserve(result) {
  return (
    result.actions.length +
    result.combined.length +
    result.annotations.length +
    result.noThread +
    (result.actions.length ? Number(result.actions[0]) : 0)
  );
}
function rnFingerprint(result) {
  rnAssert(result.actions.length === result.annotations.length, "Lost timeline metadata");
  return rnHash(JSON.stringify(result));
}
rnBenchmark([
  { "fingerprint": 2928002405, "observation": 129726 },
  { "fingerprint": 1722725710, "observation": 139209 },
  { "fingerprint": 3216595838, "observation": 134451 },
  { "fingerprint": 581648625, "observation": 144214 },
  { "fingerprint": 3272133014, "observation": 30 },
  { "fingerprint": 3047869656, "observation": 32 },
  { "fingerprint": 3465039162, "observation": 0 },
  { "fingerprint": 566139655, "observation": 37 },
]);
