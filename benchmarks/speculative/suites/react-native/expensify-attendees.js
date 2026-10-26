// Extracted from https://github.com/Expensify/App at 0eff10433514a9be0faa2a568d5779dc06e05d44.
// Workload: expensify-attendees. See README.md, manifest.json and licenses/.
// Type/module syntax and formatting adapted; application algorithms retained.
// Copyright (c) 2020 Expensify Inc. MIT License.
const CONST = {
  "VIOLATIONS": { "MISSING_ATTENDEES": "missingAttendees" },
  "VIOLATION_TYPES": { "VIOLATION": "violation" },
  "DEFAULT_NUMBER_ID": 0,
};
function sortAlphabetically(items, key, localeCompare) {
  return items.sort((a, b) =>
    localeCompare(a[key]?.toLowerCase() ?? "", b[key]?.toLowerCase() ?? "")
  );
}
function isEmptyObject(obj) {
  return Object.keys(obj ?? {}).length === 0;
}
function getNormalizedString(value) {
  const normalizedValue = value?.trim();
  if (normalizedValue) {
    return normalizedValue;
  }
  return void 0;
}
function normalizeAttendee(attendee) {
  const { email, displayName: attendeeDisplayName, ...rest } = attendee;
  const normalizedEmail = getNormalizedString(email);
  const displayName = getNormalizedString(attendeeDisplayName) ?? normalizedEmail ?? "";
  return {
    ...rest,
    displayName,
    ...(normalizedEmail ? { email: normalizedEmail } : {}),
  };
}
function normalizeAttendees(attendees) {
  return (attendees ?? []).map(normalizeAttendee);
}
function convertAttendeesToArray(rawAttendees) {
  if (Array.isArray(rawAttendees)) {
    return rawAttendees;
  }
  if (rawAttendees && typeof rawAttendees === "object") {
    return Object.values(rawAttendees);
  }
  return [];
}
function getIsMissingAttendeesViolation(
  policyCategories,
  category,
  iouAttendees,
  userPersonalDetails,
  isAttendeeTrackingEnabled = false,
  isControlPolicy = false
) {
  if (!isControlPolicy) {
    return false;
  }
  const areAttendeesRequired = !!policyCategories?.[category ?? ""]?.areAttendeesRequired;
  if (!isAttendeeTrackingEnabled || !areAttendeesRequired) {
    return false;
  }
  const creatorLogin = userPersonalDetails.login ?? "";
  const creatorEmail = userPersonalDetails.email ?? "";
  const attendees = convertAttendeesToArray(iouAttendees);
  const attendeesMinusCreatorCount = attendees.filter((a) => {
    const attendeeIdentifier = a?.email;
    return attendeeIdentifier !== creatorLogin && attendeeIdentifier !== creatorEmail;
  }).length;
  if (attendees.length === 0 || attendeesMinusCreatorCount === 0) {
    return true;
  }
  return false;
}
function syncMissingAttendeesViolation(
  violations,
  policyCategories,
  category,
  attendees,
  userPersonalDetails,
  isAttendeeTrackingEnabled,
  isControlPolicy,
  isInvoice = false
) {
  if (isInvoice) {
    return violations.filter((violation) => violation.name !== CONST.VIOLATIONS.MISSING_ATTENDEES);
  }
  const hasMissingAttendeesViolation = violations.some(
    (v) => v.name === CONST.VIOLATIONS.MISSING_ATTENDEES
  );
  const shouldShowMissingAttendees =
    isControlPolicy &&
    getIsMissingAttendeesViolation(
      policyCategories ?? {},
      category ?? "",
      attendees ?? [],
      userPersonalDetails,
      isAttendeeTrackingEnabled,
      isControlPolicy
    );
  if (!hasMissingAttendeesViolation && shouldShowMissingAttendees) {
    return [
      ...violations,
      {
        name: CONST.VIOLATIONS.MISSING_ATTENDEES,
        type: CONST.VIOLATION_TYPES.VIOLATION,
        showInReview: true,
      },
    ];
  }
  if (hasMissingAttendeesViolation && !shouldShowMissingAttendees) {
    return violations.filter((v) => v.name !== CONST.VIOLATIONS.MISSING_ATTENDEES);
  }
  return violations;
}
function enrichAndSortAttendees(
  attendees,
  loginToAccountIDMap,
  personalDetailsList,
  localeCompare
) {
  if (!Array.isArray(attendees)) {
    return attendees;
  }
  return sortAlphabetically(
    attendees.map((a) => {
      const accountID = loginToAccountIDMap?.[a.email ?? ""] ?? CONST.DEFAULT_NUMBER_ID;
      const pd = personalDetailsList?.[accountID];
      const freshAvatar = typeof pd?.avatar === "string" ? pd.avatar : void 0;
      return {
        ...a,
        accountID,
        // intentional || to fall back when personalDetails has an empty string
        displayName: pd?.displayName || a?.displayName,
        // intentional || to fall back when personalDetails has an empty string
        avatarUrl: freshAvatar || a?.avatarUrl,
      };
    }),
    "displayName",
    localeCompare
  );
}
const INPUT_IDS = {
  LEGAL_FIRST_NAME: "legalFirstName",
  LEGAL_LAST_NAME: "legalLastName",
  DATE_OF_BIRTH: "dob",
  ADDRESS_LINE_1: "addressLine1",
  ADDRESS_LINE_2: "addressLine2",
  COUNTRY: "country",
  STATE: "state",
  CITY: "city",
  ZIP_POST_CODE: "zipPostCode",
  PHONE_NUMBER: "phoneNumber",
};
function getPersonalDetailsByID(accountID, personalDetailsList) {
  return accountID ? (personalDetailsList?.[accountID] ?? void 0) : void 0;
}
function getPersonalDetailsByIDs(accountIDs, personalDetails) {
  if (!accountIDs) {
    return [];
  }
  const result = [];
  for (const accountID of accountIDs) {
    const detail = getPersonalDetailsByID(accountID, personalDetails);
    if (!detail) {
      continue;
    }
    result.push(detail);
  }
  return result;
}
function getPersonalDetailsListByIDs(accountIDs, personalDetails) {
  return (
    accountIDs?.reduce((acc, accountID) => {
      if (!accountID) {
        return acc;
      }
      const detail = personalDetails?.[accountID];
      if (!detail) {
        return acc;
      }
      acc[accountID] = detail;
      return acc;
    }, {}) ?? {}
  );
}
function getParticipantsPersonalDetails(accountIDs, personalDetails) {
  const result = {};
  for (const accountID of accountIDs) {
    result[accountID] = personalDetails?.[accountID] ?? null;
  }
  return result;
}
function getLoginByAccountID(accountID, personalDetails) {
  return accountID ? personalDetails?.[accountID]?.login : void 0;
}
function getLoginsByAccountIDs(accountIDs, personalDetailsList) {
  return (
    accountIDs?.reduce((foundLogins, accountID) => {
      const currentLogin = getLoginByAccountID(accountID, personalDetailsList);
      if (currentLogin) {
        foundLogins.push(currentLogin);
      }
      return foundLogins;
    }, []) ?? []
  );
}
function createDisplayName(login, passedPersonalDetails, formatPhoneNumber) {
  const userLogin = formatPhoneNumber(login);
  if (!passedPersonalDetails) {
    return userLogin;
  }
  const firstName = passedPersonalDetails.firstName ?? "";
  const lastName = passedPersonalDetails.lastName ?? "";
  const fullName = `${firstName} ${lastName}`.trim();
  return fullName || userLogin;
}
function getDisplayNameOrYou(displayName, accountID, currentUserAccountID, translate) {
  if (accountID === currentUserAccountID) {
    return translate("common.you");
  }
  return displayName;
}
function formatPiece(piece) {
  return piece ? `${piece}, ` : "";
}
function getStreetLines(street = "") {
  const streets = street.split("\n");
  return [streets.at(0), streets.at(1)];
}
function getFormattedStreet(street1 = "", street2 = "") {
  return `${street1}
${street2}`;
}
function getCurrentAddress(privatePersonalDetails) {
  const { addresses } = privatePersonalDetails ?? {};
  const currentAddress = addresses?.find((address) => address.current);
  return currentAddress ?? addresses?.[addresses.length - 1];
}
function getFormattedAddress(privatePersonalDetails) {
  const address = getCurrentAddress(privatePersonalDetails);
  const [street1, street2] = getStreetLines(address?.street);
  const formattedAddress =
    formatPiece(street1) +
    formatPiece(street2) +
    formatPiece(address?.city) +
    formatPiece(address?.state) +
    formatPiece(address?.zip) +
    formatPiece(address?.country);
  return formattedAddress.trim().replaceAll(/,$/g, "");
}
function arePersonalDetailsMissing(privatePersonalDetails) {
  return (
    !privatePersonalDetails?.legalFirstName ||
    !privatePersonalDetails?.legalLastName ||
    !privatePersonalDetails?.dob ||
    !privatePersonalDetails?.phoneNumber ||
    isEmptyObject(privatePersonalDetails?.addresses) ||
    privatePersonalDetails.addresses.length === 0
  );
}
function areTravelPersonalDetailsMissing(privatePersonalDetails) {
  return !privatePersonalDetails?.legalFirstName || !privatePersonalDetails?.legalLastName;
}
function getPrivatePersonalDetailsFormValues(privatePersonalDetails, draftValues) {
  const address = getCurrentAddress(privatePersonalDetails);
  const [street1, street2] = getStreetLines(address?.street);
  return {
    [INPUT_IDS.LEGAL_FIRST_NAME]:
      draftValues?.[INPUT_IDS.LEGAL_FIRST_NAME] ?? privatePersonalDetails?.legalFirstName ?? "",
    [INPUT_IDS.LEGAL_LAST_NAME]:
      draftValues?.[INPUT_IDS.LEGAL_LAST_NAME] ?? privatePersonalDetails?.legalLastName ?? "",
    [INPUT_IDS.DATE_OF_BIRTH]:
      draftValues?.[INPUT_IDS.DATE_OF_BIRTH] ?? privatePersonalDetails?.dob ?? "",
    [INPUT_IDS.PHONE_NUMBER]:
      draftValues?.[INPUT_IDS.PHONE_NUMBER] ?? privatePersonalDetails?.phoneNumber ?? "",
    [INPUT_IDS.ADDRESS_LINE_1]: draftValues?.[INPUT_IDS.ADDRESS_LINE_1] ?? street1 ?? "",
    [INPUT_IDS.ADDRESS_LINE_2]:
      draftValues?.[INPUT_IDS.ADDRESS_LINE_2] ?? address?.street2 ?? street2 ?? "",
    [INPUT_IDS.CITY]: draftValues?.[INPUT_IDS.CITY] ?? address?.city ?? "",
    [INPUT_IDS.STATE]: draftValues?.[INPUT_IDS.STATE] ?? address?.state ?? "",
    [INPUT_IDS.ZIP_POST_CODE]: draftValues?.[INPUT_IDS.ZIP_POST_CODE] ?? address?.zip ?? "",
    [INPUT_IDS.COUNTRY]: draftValues?.[INPUT_IDS.COUNTRY] ?? address?.country ?? "",
  };
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
const RN_ITERATIONS = 24;
function rnCreateFixtures() {
  return Array.from({ length: 8 }, function (_, variant) {
    const attendees = [];
    const logins = {};
    const personal = {};
    for (let i = 0; i < 512; i++) {
      const email = "user" + i + "@example.com";
      attendees.push({
        email: i % 11 ? email : void 0,
        displayName: i % 5 ? " Person " + (511 - i) + " " : "  ",
        avatarUrl: "fixture-avatar-" + i,
      });
      if (i % 3) logins[email] = i + 1;
      if (i % 2)
        personal[i + 1] = {
          accountID: i + 1,
          login: email,
          firstName: "Person",
          lastName: String(i),
          displayName: "Live " + i,
          avatar: i % 7 ? "live-" + i : "",
        };
    }
    return {
      attendees: variant % 3 ? attendees : Object.assign({}, attendees),
      logins,
      personal,
      categories: { Travel: { areAttendeesRequired: variant % 2 === 0 } },
      tracking: variant % 4 !== 0,
      violations:
        variant % 2
          ? [{ name: "other" }, { name: CONST.VIOLATIONS.MISSING_ATTENDEES }]
          : [{ name: "other" }],
      invoice: variant === 7,
      privateDetails: {
        legalFirstName: "Alice",
        legalLastName: variant % 2 ? "" : "Wang",
        dob: "1990-01-01",
        phoneNumber: "+12025550123",
        addresses: [
          {
            street: getFormattedStreet("12 Main St", "Unit " + variant),
            city: "Example",
            zip: "10000",
            country: "US",
            current: variant % 2 === 0,
          },
          { street: "34 Second St", city: "Other", zip: "20000", country: "JP" },
        ],
      },
    };
  });
}
function rnExecute(fixture) {
  const attendees = normalizeAttendees(convertAttendeesToArray(fixture.attendees));
  const user = { login: "user1@example.com", email: "user1@example.com" };
  const sorted = enrichAndSortAttendees(
    attendees,
    fixture.logins,
    fixture.personal,
    function (a, b) {
      return a < b ? -1 : a > b ? 1 : 0;
    }
  );
  const ids = sorted.map(function (attendee) {
    return attendee.accountID;
  });
  const participants = getParticipantsPersonalDetails(ids, fixture.personal);
  const available = getPersonalDetailsByIDs(ids, participants);
  const list = getPersonalDetailsListByIDs(ids, fixture.personal);
  const displayNames = available.map(function (details) {
    const login = getLoginByAccountID(details.accountID, list) || "";
    const name = createDisplayName(login, details, function (email) {
      return email;
    });
    return getDisplayNameOrYou(name, details.accountID, 2, function () {
      return "You";
    });
  });
  return {
    attendees: sorted,
    profiles: {
      displayNames,
      logins: getLoginsByAccountIDs(ids, list),
      sample: getPersonalDetailsByID(ids[0], list),
      missing: Object.values(participants).filter(function (p) {
        return p === null;
      }).length,
    },
    address: getFormattedAddress(fixture.privateDetails),
    profileForm: getPrivatePersonalDetailsFormValues(fixture.privateDetails),
    draftForm: getPrivatePersonalDetailsFormValues(fixture.privateDetails, {
      legalLastName: "Draft name",
      city: "Draft city",
    }),
    missingPersonalDetails: arePersonalDetailsMissing(fixture.privateDetails),
    missingTravelDetails: areTravelPersonalDetailsMissing(fixture.privateDetails),
    missing: getIsMissingAttendeesViolation(
      fixture.categories,
      "Travel",
      attendees,
      user,
      fixture.tracking,
      true
    ),
    violations: syncMissingAttendeesViolation(
      fixture.violations,
      fixture.categories,
      "Travel",
      attendees,
      user,
      fixture.tracking,
      true,
      fixture.invoice
    ),
  };
}
function rnObserve(result) {
  return (
    result.attendees.reduce(function (n, a) {
      return n + a.displayName.length + a.accountID;
    }, 0) +
    result.violations.length +
    (result.missing ? 1 : 0) +
    result.profiles.displayNames.join("").length +
    result.address.length +
    result.profiles.logins.length +
    result.profiles.missing
  );
}
function rnFingerprint(result) {
  rnAssert(result.attendees.length === 512, "Attendee count changed");
  rnAssert(
    result.attendees.every(function (a) {
      return a.displayName === a.displayName.trim();
    }),
    "Untrimmed attendee"
  );
  rnAssert(
    result.profiles.displayNames.length === result.profiles.logins.length,
    "Profile/login lookup mismatch"
  );
  rnAssert(
    result.draftForm.legalLastName === "Draft name" && result.draftForm.city === "Draft city",
    "Profile draft did not override stored values"
  );
  return rnHash(JSON.stringify(result));
}
rnBenchmark([
  { "fingerprint": 3145222810, "observation": 86623 },
  { "fingerprint": 762515115, "observation": 86615 },
  { "fingerprint": 1276772172, "observation": 86623 },
  { "fingerprint": 762515115, "observation": 86615 },
  { "fingerprint": 4171946894, "observation": 86623 },
  { "fingerprint": 762515115, "observation": 86615 },
  { "fingerprint": 3167971088, "observation": 86623 },
  { "fingerprint": 762515115, "observation": 86615 },
]);
