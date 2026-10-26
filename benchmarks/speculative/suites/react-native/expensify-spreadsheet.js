// Extracted from https://github.com/Expensify/App at 0eff10433514a9be0faa2a568d5779dc06e05d44.
// Workload: expensify-spreadsheet. See README.md, manifest.json and licenses/.
// Type/module syntax and formatting adapted; application algorithms retained.
// Copyright (c) 2020 Expensify Inc. MIT License.
const CONST = {
  "CSV_IMPORT_COLUMNS": {
    "EMAIL": "email",
    "CATEGORY": "category",
    "COMMENT": "comment",
    "GL_CODE": "glCode",
    "SUBMIT_TO": "submitTo",
    "APPROVE_TO": "approveTo",
    "CUSTOM_FIELD_2": "customField2",
    "CUSTOM_FIELD_1": "customField1",
    "ROLE": "role",
    "REPORT_THRESHOLD": "reportThreshold",
    "APPROVE_TO_ALTERNATE": "approveToAlternate",
    "DESTINATION": "destination",
    "SUBRATE": "subRate",
    "AMOUNT": "amount",
    "CARD_NUMBER": "cardNumber",
    "CURRENCY": "currency",
    "POSTED_DATE": "postedDate",
    "DATE": "date",
    "MERCHANT": "merchant",
    "MERCHANT_IS": "merchantIs",
    "MERCHANT_CONTAINS": "merchantContains",
    "UPDATED_MERCHANT": "updatedMerchant",
    "TAG": "tag",
    "VENDOR": "vendor",
    "REIMBURSABLE": "reimbursable",
    "BILLABLE": "billable",
    "RATE_ID": "rateID",
    "ENABLED": "enabled",
    "MAX_AMOUNT_NO_RECEIPT": "maxAmountNoReceipt",
    "MAX_AMOUNT_NO_ITEMIZED_RECEIPT": "maxAmountNoItemizedReceipt",
    "ARE_COMMENTS_REQUIRED": "areCommentsRequired",
    "COMMENT_HINT": "commentHint",
    "MAX_EXPENSE_AMOUNT": "maxExpenseAmount",
    "EXPENSE_LIMIT_TYPE": "expenseLimitType",
    "PAYROLL_CODE": "payrollCode",
    "NAME": "name",
    "IGNORE": "ignore",
    "EXTERNAL_ID": "externalID",
  },
  "IOU": { "AMOUNT_MAX_LENGTH": 10 },
};
function findColumnName(header, columnRoles) {
  let attribute = "";
  const formattedHeader = String(header).toLowerCase().trim().replaceAll(" ", "");
  switch (formattedHeader) {
    case "email":
    case "emailaddress":
    case "emailaddresses":
    case "e-mail":
    case "e-mailaddress":
    case "e-mailaddresses":
      attribute = CONST.CSV_IMPORT_COLUMNS.EMAIL;
      break;
    case "category":
    case "categories":
    case "updatedcategory":
      attribute = CONST.CSV_IMPORT_COLUMNS.CATEGORY;
      break;
    case "updateddescription":
      attribute = CONST.CSV_IMPORT_COLUMNS.COMMENT;
      break;
    case "glcode":
    case "gl":
      attribute = CONST.CSV_IMPORT_COLUMNS.GL_CODE;
      break;
    case "tag":
    case "tags":
    case "project":
    case "projectcode":
    case "customer":
    case "name":
      attribute = "name";
      break;
    case "submitto":
    case "submitsto":
      attribute = CONST.CSV_IMPORT_COLUMNS.SUBMIT_TO;
      break;
    case "approveto":
    case "approvesto":
      attribute = CONST.CSV_IMPORT_COLUMNS.APPROVE_TO;
      break;
    case "payroll":
    case "payrollid":
    case "payrolls":
    case "payrol":
    case "payrollcode":
    case "customfield2":
      attribute = CONST.CSV_IMPORT_COLUMNS.CUSTOM_FIELD_2;
      break;
    case "userid":
    case "customfield1":
      attribute = CONST.CSV_IMPORT_COLUMNS.CUSTOM_FIELD_1;
      break;
    case "role":
      attribute = CONST.CSV_IMPORT_COLUMNS.ROLE;
      break;
    case "total":
    case "threshold":
    case "reporttotal":
    case "reporttotalthreshold":
    case "approvallimit":
      attribute = CONST.CSV_IMPORT_COLUMNS.REPORT_THRESHOLD;
      break;
    case "alternate":
    case "alternateapprove":
    case "alternateapproveto":
    case "overlimitforwardsto":
      attribute = CONST.CSV_IMPORT_COLUMNS.APPROVE_TO_ALTERNATE;
      break;
    case "destination":
      attribute = CONST.CSV_IMPORT_COLUMNS.DESTINATION;
      break;
    case "subrate":
      attribute = CONST.CSV_IMPORT_COLUMNS.SUBRATE;
      break;
    case "amount":
    case "postedamount":
    case "posted_amount":
      attribute = CONST.CSV_IMPORT_COLUMNS.AMOUNT;
      break;
    case "cardnumber":
    case "card":
    case "number":
      attribute = CONST.CSV_IMPORT_COLUMNS.CARD_NUMBER;
      break;
    case "currency":
    case "postedcurrency":
    case "posted_currency":
      attribute = CONST.CSV_IMPORT_COLUMNS.CURRENCY;
      break;
    case "posteddate":
    case "posted_date":
    case "postingdate":
    case "posting_date":
      attribute = CONST.CSV_IMPORT_COLUMNS.POSTED_DATE;
      break;
    case "date":
    case "transactiondate":
    case "transaction_date":
      attribute = CONST.CSV_IMPORT_COLUMNS.DATE;
      break;
    case "merchant":
    case "merchants":
    case "vendor":
    case "vendors":
      attribute = CONST.CSV_IMPORT_COLUMNS.MERCHANT;
      break;
    case "merchantis":
      attribute = CONST.CSV_IMPORT_COLUMNS.MERCHANT_IS;
      break;
    case "merchantcontains":
      attribute = CONST.CSV_IMPORT_COLUMNS.MERCHANT_CONTAINS;
      break;
    case "updatedmerchant":
    case "newmerchant":
      attribute = CONST.CSV_IMPORT_COLUMNS.UPDATED_MERCHANT;
      break;
    case "updatedtag":
    case "newtag":
    case "label":
    case "labels":
      attribute = CONST.CSV_IMPORT_COLUMNS.TAG;
      break;
    case "updatedvendor":
    case "updatedsupplier":
      attribute = CONST.CSV_IMPORT_COLUMNS.VENDOR;
      break;
    case "reimbursable":
    case "reimburseable":
      attribute = CONST.CSV_IMPORT_COLUMNS.REIMBURSABLE;
      break;
    case "preferredmerchantname":
    case "preferredmerchant(vendor)name":
    case "preferredvendorname":
      attribute = CONST.CSV_IMPORT_COLUMNS.MERCHANT_IS;
      break;
    case "billable":
      attribute = CONST.CSV_IMPORT_COLUMNS.BILLABLE;
      break;
    case "rateid":
      attribute = CONST.CSV_IMPORT_COLUMNS.RATE_ID;
      break;
    case "enabled":
    case "enable":
      attribute = CONST.CSV_IMPORT_COLUMNS.ENABLED;
      break;
    case "receiptsrequired":
    case "requirereceiptsover":
    case "maxamountnoreceipt":
      attribute = CONST.CSV_IMPORT_COLUMNS.MAX_AMOUNT_NO_RECEIPT;
      break;
    case "itemisedreceiptrequirement":
    case "itemizedreceiptrequirement":
    case "itemisedreceiptsrequired":
    case "itemizedreceiptsrequired":
    case "requireitemizedreceiptsover":
    case "maxamountnoitemizedreceipt":
      attribute = CONST.CSV_IMPORT_COLUMNS.MAX_AMOUNT_NO_ITEMIZED_RECEIPT;
      break;
    case "comments":
    case "requiredescription":
      attribute = CONST.CSV_IMPORT_COLUMNS.ARE_COMMENTS_REQUIRED;
      break;
    case "commenthint":
    case "descriptionhint":
      attribute = CONST.CSV_IMPORT_COLUMNS.COMMENT_HINT;
      break;
    case "maxexpenseamount":
    case "flagamountsover":
      attribute = CONST.CSV_IMPORT_COLUMNS.MAX_EXPENSE_AMOUNT;
      break;
    case "expenselimittype":
      attribute = CONST.CSV_IMPORT_COLUMNS.EXPENSE_LIMIT_TYPE;
      break;
    default:
      break;
  }
  if (
    !attribute &&
    formattedHeader === "description" &&
    columnRoles?.some((role) => role.value === CONST.CSV_IMPORT_COLUMNS.MERCHANT_IS)
  ) {
    attribute = CONST.CSV_IMPORT_COLUMNS.COMMENT;
  }
  if (columnRoles && attribute) {
    const isAvailable = columnRoles.some((role) => role.value === attribute);
    if (!isAvailable) {
      if (
        attribute === CONST.CSV_IMPORT_COLUMNS.DATE &&
        columnRoles.some((role) => role.value === CONST.CSV_IMPORT_COLUMNS.POSTED_DATE)
      ) {
        return CONST.CSV_IMPORT_COLUMNS.POSTED_DATE;
      }
      if (
        attribute === CONST.CSV_IMPORT_COLUMNS.MERCHANT &&
        columnRoles.some((role) => role.value === CONST.CSV_IMPORT_COLUMNS.UPDATED_MERCHANT)
      ) {
        return CONST.CSV_IMPORT_COLUMNS.UPDATED_MERCHANT;
      }
      if (
        attribute === CONST.CSV_IMPORT_COLUMNS.CUSTOM_FIELD_2 &&
        columnRoles.some((role) => role.value === CONST.CSV_IMPORT_COLUMNS.PAYROLL_CODE)
      ) {
        return CONST.CSV_IMPORT_COLUMNS.PAYROLL_CODE;
      }
      if (
        attribute === CONST.CSV_IMPORT_COLUMNS.NAME &&
        ["tag", "tags"].includes(formattedHeader) &&
        columnRoles.some((role) => role.value === CONST.CSV_IMPORT_COLUMNS.TAG)
      ) {
        return CONST.CSV_IMPORT_COLUMNS.TAG;
      }
      return "";
    }
  }
  return attribute;
}
function getCompanyCardColumnMappings(spreadsheetData, savedColumnMappings, availableColumnRoles) {
  const numColumns = spreadsheetData.length;
  const validRoles = new Set(availableColumnRoles);
  const rolesForDetection = availableColumnRoles.map((value) => ({ text: "", value }));
  const columns = {};
  const usedRoles = /* @__PURE__ */ new Set();
  for (let index = 0; index < numColumns; index++) {
    columns[index] = CONST.CSV_IMPORT_COLUMNS.IGNORE;
  }
  for (let index = 0; index < numColumns; index++) {
    const header = spreadsheetData.at(index)?.at(0) ?? "";
    const detectedRole = findColumnName(header, rolesForDetection);
    if (
      !detectedRole ||
      detectedRole === CONST.CSV_IMPORT_COLUMNS.IGNORE ||
      !validRoles.has(detectedRole) ||
      usedRoles.has(detectedRole)
    ) {
      continue;
    }
    columns[index] = detectedRole;
    usedRoles.add(detectedRole);
  }
  for (const [role, indexValue] of Object.entries(savedColumnMappings ?? {})) {
    if (role === CONST.CSV_IMPORT_COLUMNS.IGNORE || !validRoles.has(role) || usedRoles.has(role)) {
      continue;
    }
    if (role === CONST.CSV_IMPORT_COLUMNS.EXTERNAL_ID) {
      continue;
    }
    const index = Number(indexValue);
    if (
      !Number.isInteger(index) ||
      index < 0 ||
      index >= numColumns ||
      columns[index] !== CONST.CSV_IMPORT_COLUMNS.IGNORE
    ) {
      continue;
    }
    columns[index] = role;
    usedRoles.add(role);
  }
  return columns;
}
function findDuplicate(array) {
  const frequencyCounter = {};
  for (const item of array) {
    if (item !== CONST.CSV_IMPORT_COLUMNS.IGNORE) {
      if (frequencyCounter[item]) {
        return item;
      }
      frequencyCounter[item] = (frequencyCounter[item] || 0) + 1;
    }
  }
  return null;
}
function numberToColumn(index) {
  let column = "";
  let number = index;
  while (number >= 0) {
    column = String.fromCharCode((number % 26) + 65) + column;
    number = Math.floor(number / 26) - 1;
  }
  return column;
}
function generateColumnNames(length) {
  return Array.from({ length }, (_, i) => numberToColumn(i));
}
function normalizeImportedAmount(value, currencySymbol, currencyCode) {
  const tokens = [currencySymbol, currencyCode]
    .filter((token) => !!token)
    .map((token) => StringUtils.escapeRegExp(token));
  const withoutCurrency =
    tokens.length > 0
      ? value
          .trim()
          .replace(new RegExp(`^(?:${tokens.join("|")})\\s*|\\s*(?:${tokens.join("|")})$`, "i"), "")
      : value;
  return stripCommaFromAmount(stripSpacesFromAmount(withoutCurrency.replaceAll(/\p{Sc}/gu, "")));
}
function escapeRegExp(str) {
  return str.replaceAll(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
const StringUtils = { escapeRegExp };
function stripCommaFromAmount(amount) {
  return amount.replaceAll(",", "");
}
function stripSpacesFromAmount(amount) {
  return amount.replaceAll(/\s+/g, "");
}
function addLeadingZero(amount, shouldAllowNegative = false) {
  if (shouldAllowNegative && amount.startsWith("-.")) {
    return `-0${amount}`;
  }
  return amount.startsWith(".") ? `0${amount}` : amount;
}
function validateAmount(
  amount,
  decimals,
  amountMaxLength = CONST.IOU.AMOUNT_MAX_LENGTH,
  shouldAllowNegative = false
) {
  const regexString =
    decimals === 0
      ? `^${shouldAllowNegative ? "-?" : ""}\\d{1,${amountMaxLength}}$`
      : `^${shouldAllowNegative ? "-?" : ""}\\d{1,${amountMaxLength}}(\\.\\d{0,${decimals}})?$`;
  const decimalNumberRegex = new RegExp(regexString, "i");
  if (shouldAllowNegative) {
    return amount === "" || amount === "-" || decimalNumberRegex.test(amount);
  }
  return amount === "" || decimalNumberRegex.test(amount);
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
const RN_ITERATIONS = 120;
function rnCreateFixtures() {
  const headers = [
    "Date",
    "Posted Date",
    "Merchant",
    "Description",
    "Amount",
    "Total",
    "Currency",
    "Card Number",
    "Category",
    "GL Code",
    "Email Address",
    "Payroll Code",
    "Tags",
    "Billable",
    "Enabled",
    "unknown",
    "",
    "MAX Expense Amount",
    "Receipt Requirement",
    "Comment Hint",
  ];
  const roles = Object.values(CONST.CSV_IMPORT_COLUMNS).filter(function (value) {
    return typeof value === "string";
  });
  return Array.from({ length: 8 }, function (_, variant) {
    const columns = [];
    for (let i = 0; i < 80; i++)
      columns.push([headers[(i + variant) % headers.length], "value-" + i]);
    return {
      columns,
      roles:
        variant % 2
          ? roles.filter(function (role) {
              return role !== "date" && role !== "merchant";
            })
          : roles,
      saved: {
        amount: "2",
        currency: "4",
        externalID: "79",
        name: "78",
        cardNumber: "-1",
        email: "999",
      },
      amounts: [
        "$ 1,234.56",
        "USD 98.10",
        " -12.50 USD",
        "\u20AC 1 234.00",
        "0",
        "1.2345",
        ".50",
        "-.25",
        "invalid",
      ],
    };
  });
}
function rnExecute(fixture) {
  const mapping = getCompanyCardColumnMappings(fixture.columns, fixture.saved, fixture.roles);
  const roleObjects = fixture.roles.map(function (value) {
    return { text: value, value };
  });
  return {
    mapping,
    names: generateColumnNames(fixture.columns.length),
    detected: fixture.columns.map(function (column) {
      return findColumnName(column[0], roleObjects);
    }),
    duplicate: findDuplicate(Object.values(mapping)),
    amounts: fixture.amounts.map(function (value) {
      const amount = addLeadingZero(normalizeImportedAmount(value, "$", "USD"), true);
      return { amount, valid: validateAmount(amount, 2, 12, true) };
    }),
  };
}
function rnObserve(result) {
  return (
    Object.keys(result.mapping).length +
    result.names.length +
    result.detected.reduce(function (n, text) {
      return n + text.length;
    }, 0) +
    result.amounts.reduce(function (n, row) {
      return n + row.amount.length + (row.valid ? 1 : 0);
    }, 0)
  );
}
function rnFingerprint(result) {
  rnAssert(result.duplicate === null, "Column roles must be unique");
  rnAssert(
    result.amounts[0].amount === "1234.56" && result.amounts[0].valid,
    "Currency normalization failed"
  );
  return rnHash(JSON.stringify(result));
}
rnBenchmark([
  { "fingerprint": 3487248626, "observation": 795 },
  { "fingerprint": 1348226757, "observation": 847 },
  { "fingerprint": 1854185864, "observation": 795 },
  { "fingerprint": 1586742109, "observation": 847 },
  { "fingerprint": 3400368460, "observation": 795 },
  { "fingerprint": 3222811627, "observation": 847 },
  { "fingerprint": 530867566, "observation": 795 },
  { "fingerprint": 1025484227, "observation": 847 },
]);
