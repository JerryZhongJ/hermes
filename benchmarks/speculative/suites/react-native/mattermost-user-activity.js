// Extracted from https://github.com/mattermost/mattermost-mobile at 8a9427f25ad9f16ed333b1865eff9c4b057cb093.
// Workload: mattermost-user-activity. See README.md, manifest.json and licenses/.
// Type/module syntax and formatting adapted; application algorithms retained.
// Copyright (c) 2015-present Mattermost, Inc. Apache-2.0.
const PostTypes = {
  CHANNEL_DELETED: "system_channel_deleted",
  CHANNEL_UNARCHIVED: "system_channel_restored",
  DISPLAYNAME_CHANGE: "system_displayname_change",
  CONVERT_CHANNEL: "system_convert_channel",
  EPHEMERAL: "system_ephemeral",
  EPHEMERAL_ADD_TO_CHANNEL: "system_ephemeral_add_to_channel",
  HEADER_CHANGE: "system_header_change",
  PURPOSE_CHANGE: "system_purpose_change",
  SYSTEM_MESSAGE_PREFIX: "system_",
  JOIN_LEAVE: "system_join_leave",
  JOIN_CHANNEL: "system_join_channel",
  GUEST_JOIN_CHANNEL: "system_guest_join_channel",
  LEAVE_CHANNEL: "system_leave_channel",
  ADD_REMOVE: "system_add_remove",
  ADD_TO_CHANNEL: "system_add_to_channel",
  ADD_GUEST_TO_CHANNEL: "system_add_guest_to_chan",
  REMOVE_FROM_CHANNEL: "system_remove_from_channel",
  JOIN_TEAM: "system_join_team",
  LEAVE_TEAM: "system_leave_team",
  ADD_TO_TEAM: "system_add_to_team",
  REMOVE_FROM_TEAM: "system_remove_from_team",
  COMBINED_USER_ACTIVITY: "system_combined_user_activity",
  SHARED_CHANNEL_STATE: "system_shared_chan_state",
  ME: "me",
  ADD_BOT_TEAMS_CHANNELS: "add_bot_teams_channels",
  SYSTEM_AUTO_RESPONDER: "system_auto_responder",
  CUSTOM_CALLS: "custom_calls",
  CUSTOM_CALLS_RECORDING: "custom_calls_recording",
  CUSTOM_LLMBOT: "custom_llmbot",
  CUSTOM_LLM_POSTBACK: "custom_llm_postback",
  BURN_ON_READ: "burn_on_read",
};
const Post = {
  POST_TYPES: PostTypes,
  USER_ACTIVITY_POST_TYPES: [
    PostTypes.ADD_TO_CHANNEL,
    PostTypes.JOIN_CHANNEL,
    PostTypes.LEAVE_CHANNEL,
    PostTypes.REMOVE_FROM_CHANNEL,
    PostTypes.ADD_TO_TEAM,
    PostTypes.JOIN_TEAM,
    PostTypes.LEAVE_TEAM,
    PostTypes.REMOVE_FROM_TEAM,
  ],
};
function ensureString(v) {
  return typeof v === "string" ? v : "";
}
function includes(array, value) {
  return array.includes(value);
}
function secureGetFromRecord(v, key) {
  return typeof v === "object" && v && Object.prototype.hasOwnProperty.call(v, key)
    ? v[key]
    : void 0;
}
function isArrayOf(v, check) {
  if (!Array.isArray(v)) {
    return false;
  }
  return v.every(check);
}
function isStringArray(v) {
  return isArrayOf(v, (e) => typeof e === "string");
}
const postTypePriority = {
  [Post.POST_TYPES.JOIN_TEAM]: 0,
  [Post.POST_TYPES.ADD_TO_TEAM]: 1,
  [Post.POST_TYPES.LEAVE_TEAM]: 2,
  [Post.POST_TYPES.REMOVE_FROM_TEAM]: 3,
  [Post.POST_TYPES.JOIN_CHANNEL]: 4,
  [Post.POST_TYPES.ADD_TO_CHANNEL]: 5,
  [Post.POST_TYPES.LEAVE_CHANNEL]: 6,
  [Post.POST_TYPES.REMOVE_FROM_CHANNEL]: 7,
  [Post.POST_TYPES.PURPOSE_CHANGE]: 8,
  [Post.POST_TYPES.HEADER_CHANGE]: 9,
  [Post.POST_TYPES.JOIN_LEAVE]: 10,
  [Post.POST_TYPES.DISPLAYNAME_CHANGE]: 11,
  [Post.POST_TYPES.CONVERT_CHANNEL]: 12,
  [Post.POST_TYPES.CHANNEL_DELETED]: 13,
  [Post.POST_TYPES.CHANNEL_UNARCHIVED]: 14,
  [Post.POST_TYPES.ADD_REMOVE]: 15,
  [Post.POST_TYPES.EPHEMERAL]: 16,
};
const COMBINED_USER_ACTIVITY = "user-activity-";
const MAX_COMBINED_SYSTEM_POSTS = 100;
function combineUserActivityPosts(orderedPosts) {
  let lastPostIsUserActivity = false;
  let combinedCount = 0;
  const out = [];
  let changed = false;
  for (let i = 0; i < orderedPosts.length; i++) {
    const item = orderedPosts[i];
    if (
      item.type === "start-of-new-messages" ||
      item.type === "date" ||
      item.type === "thread-overview"
    ) {
      out.push(item);
      lastPostIsUserActivity = false;
      combinedCount = 0;
      continue;
    } else if (item.type === "post" && item.value.currentPost.deleteAt) {
      out.push(item);
      lastPostIsUserActivity = false;
      combinedCount = 0;
    } else {
      const postIsUserActivity =
        item.type === "post" &&
        includes(Post.USER_ACTIVITY_POST_TYPES, item.value.currentPost.type);
      if (
        postIsUserActivity &&
        lastPostIsUserActivity &&
        combinedCount < MAX_COMBINED_SYSTEM_POSTS
      ) {
        out[out.length - 1].value += "_" + item.value.currentPost.id;
      } else if (postIsUserActivity) {
        out.push({
          type: "user-activity",
          value: `${COMBINED_USER_ACTIVITY}${item.value.currentPost.id}`,
        });
        combinedCount = 1;
        changed = true;
      } else {
        out.push(item);
        combinedCount = 0;
      }
      lastPostIsUserActivity = postIsUserActivity;
    }
  }
  if (!changed) {
    return orderedPosts;
  }
  return out;
}
function comparePostTypes(a, b) {
  const aPriority = secureGetFromRecord(postTypePriority, a.postType) ?? 99;
  const bPriority = secureGetFromRecord(postTypePriority, b.postType) ?? 99;
  return aPriority - bPriority;
}
function extractUserActivityData(userActivities) {
  const messageData = [];
  const allUserIds = [];
  const allUsernames = [];
  Object.entries(userActivities).forEach(([postType, values]) => {
    if (
      postType === Post.POST_TYPES.ADD_TO_TEAM ||
      postType === Post.POST_TYPES.ADD_TO_CHANNEL ||
      postType === Post.POST_TYPES.REMOVE_FROM_CHANNEL
    ) {
      if (Array.isArray(values)) {
        throw new Error("Invalid Post activity data");
      }
      Object.entries(values).forEach(([actorId, users]) => {
        if (Array.isArray(users)) {
          throw new Error("Invalid Post activity data");
        }
        const { ids, usernames } = users;
        messageData.push({ postType, userIds: [...usernames, ...ids], actorId });
        if (ids.length > 0) {
          allUserIds.push(...ids);
        }
        if (usernames.length > 0) {
          allUsernames.push(...usernames);
        }
        allUserIds.push(actorId);
      });
    } else {
      if (!Array.isArray(values)) {
        throw new Error("Invalid Post activity data");
      }
      messageData.push({ postType, userIds: values });
      allUserIds.push(...values);
    }
  });
  messageData.sort(comparePostTypes);
  function reduceUsers(acc, curr) {
    if (!acc.has(curr)) {
      acc.add(curr);
    }
    return acc;
  }
  return {
    allUserIds: Array.from(allUserIds.reduce(reduceUsers, /* @__PURE__ */ new Set())),
    allUsernames: Array.from(allUsernames.reduce(reduceUsers, /* @__PURE__ */ new Set())),
    messageData,
  };
}
function combineUserActivitySystemPost(systemPosts) {
  const userActivities = systemPosts.reduce((acc, post) => {
    const postType = post.type;
    const userActivityProps = acc;
    const combinedPostType = userActivityProps[postType];
    if (
      postType === Post.POST_TYPES.ADD_TO_TEAM ||
      postType === Post.POST_TYPES.ADD_TO_CHANNEL ||
      postType === Post.POST_TYPES.REMOVE_FROM_CHANNEL
    ) {
      const userId =
        ensureString(post.props?.addedUserId) || ensureString(post.props?.removedUserId);
      const username =
        ensureString(post.props?.addedUsername) || ensureString(post.props?.removedUsername);
      if (combinedPostType) {
        if (Array.isArray(combinedPostType)) {
          throw new Error("Invalid Post activity data");
        }
        const userCombinedPostType = combinedPostType[post.userId];
        const users = userCombinedPostType || { ids: [], usernames: [] };
        if (userId) {
          if (!users.ids.includes(userId)) {
            users.ids.push(userId);
          }
        } else if (username && !users.usernames.includes(username)) {
          users.usernames.push(username);
        }
        combinedPostType[post.userId] = users;
      } else {
        const users = {
          ids: [],
          usernames: [],
        };
        if (userId) {
          users.ids.push(userId);
        } else if (username) {
          users.usernames.push(username);
        }
        userActivityProps[postType] = {
          [post.userId]: users,
        };
      }
    } else {
      const propsUserId = post.userId;
      if (combinedPostType) {
        if (!Array.isArray(combinedPostType)) {
          throw new Error("Invalid Post activity data");
        }
        if (!combinedPostType.includes(propsUserId)) {
          userActivityProps[postType] = [...combinedPostType, propsUserId];
        }
      } else {
        userActivityProps[postType] = [propsUserId];
      }
    }
    return userActivityProps;
  }, {});
  return extractUserActivityData(userActivities);
}
function generateCombinedPost(combinedId, systemPosts) {
  const channelId = systemPosts[0].channelId;
  const createAt = systemPosts[systemPosts.length - 1].createAt;
  const messages = systemPosts.map((post) => post.message);
  const message = messages.join("\n");
  return {
    id: combinedId,
    root_id: "",
    original_id: "",
    channel_id: channelId,
    create_at: createAt,
    delete_at: 0,
    edit_at: 0,
    update_at: 0,
    is_pinned: false,
    message,
    hashtags: "",
    pending_post_id: "",
    reply_count: 0,
    props: {
      messages,
      user_activity: combineUserActivitySystemPost(systemPosts),
      user_activity_posts: systemPosts,
      system_post_ids: systemPosts.map((post) => post.id),
    },
    type: Post.POST_TYPES.COMBINED_USER_ACTIVITY,
    user_id: "",
    metadata: {},
  };
}
const joinLeavePostTypes = [
  Post.POST_TYPES.JOIN_LEAVE,
  Post.POST_TYPES.JOIN_CHANNEL,
  Post.POST_TYPES.LEAVE_CHANNEL,
  Post.POST_TYPES.ADD_REMOVE,
  Post.POST_TYPES.ADD_TO_CHANNEL,
  Post.POST_TYPES.REMOVE_FROM_CHANNEL,
  Post.POST_TYPES.JOIN_TEAM,
  Post.POST_TYPES.LEAVE_TEAM,
  Post.POST_TYPES.ADD_TO_TEAM,
  Post.POST_TYPES.REMOVE_FROM_TEAM,
  Post.POST_TYPES.COMBINED_USER_ACTIVITY,
];
function isJoinLeavePostForUsername(post, currentUsername) {
  if (!post.props || !currentUsername) {
    return false;
  }
  if (Array.isArray(post.props.user_activity_posts)) {
    for (const childPost of post.props.user_activity_posts) {
      if (childPost && isJoinLeavePostForUsername(childPost, currentUsername)) {
        return true;
      }
    }
  }
  return (
    post.props.username === currentUsername ||
    post.props.addedUsername === currentUsername ||
    post.props.removedUsername === currentUsername
  );
}
function getPostIdsForCombinedUserActivityPost(item) {
  if (!item.startsWith(COMBINED_USER_ACTIVITY)) {
    throw new Error(`Invalid prefix, expected string to start with '${COMBINED_USER_ACTIVITY}'`);
  }
  return item.substring(COMBINED_USER_ACTIVITY.length).split("_");
}
function shouldFilterJoinLeavePost(post, showJoinLeave, currentUsername) {
  if (showJoinLeave) {
    return false;
  }
  if (!includes(joinLeavePostTypes, post.type)) {
    return false;
  }
  return !isJoinLeavePostForUsername(post, currentUsername);
}
function isMessageData(v) {
  if (typeof v !== "object" || !v) {
    return false;
  }
  if ("actorId" in v && typeof v.actorId !== "string") {
    return false;
  }
  if (!("postType" in v) || typeof v.postType !== "string") {
    return false;
  }
  if (!("userIds" in v) || !isStringArray(v.userIds)) {
    return false;
  }
  return true;
}
function isUserActivityProp(v) {
  if (typeof v !== "object" || !v) {
    return false;
  }
  if (!("allUserIds" in v) || !isStringArray(v.allUserIds)) {
    return false;
  }
  if (!("allUsernames" in v) || !isStringArray(v.allUsernames)) {
    return false;
  }
  if (!("messageData" in v) || !isArrayOf(v.messageData, isMessageData)) {
    return false;
  }
  return true;
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
const RN_ITERATIONS = 80;
function rnCreateFixtures() {
  const random = rnRandom(1296127060);
  const types = Post.USER_ACTIVITY_POST_TYPES;
  const fixtures = [];
  for (let variant = 0; variant < 4; variant++) {
    const ordered = [];
    const systemPosts = [];
    for (let i = 0; i < 4096; i++) {
      const activity = i % 160 < 145;
      const type = activity ? types[random() % types.length] : "";
      const props = {};
      if (i % 3 === 0) props.addedUserId = "member-" + (random() % 32);
      else if (i % 3 === 1) props.addedUsername = "guest-" + (random() % 16);
      else props.removedUserId = "member-" + (random() % 32);
      const post = {
        id: "post-" + variant + "-" + i,
        channelId: "channel-" + variant,
        createAt: 17672256e5 + i * 1e3,
        deleteAt: i % 311 === 0 ? 17672256e5 : 0,
        userId: "actor-" + (random() % 24),
        type,
        message: "Activity message " + i,
        props,
      };
      if (i % 512 === 0) ordered.push({ type: "date", value: "date-" + i });
      if (i === 1024)
        ordered.push({ type: "start-of-new-messages", value: "start-of-new-messages" });
      if (i === 2048) ordered.push({ type: "thread-overview", value: "thread-overview" });
      ordered.push({ type: "post", value: { currentPost: post } });
      if (activity && systemPosts.length < 256) systemPosts.push(post);
    }
    fixtures.push({ ordered, systemPosts, combinedId: "combined-" + variant });
  }
  const posts = fixtures[0].systemPosts;
  fixtures.push({
    ordered: [
      { type: "date", value: "date-edge" },
      { type: "post", value: { currentPost: posts[0] } },
    ],
    systemPosts: [posts[0]],
    combinedId: "combined-edge",
  });
  return fixtures;
}
function rnExecute(fixture) {
  const grouped = combineUserActivityPosts(fixture.ordered);
  const combined = generateCombinedPost(fixture.combinedId, fixture.systemPosts);
  return {
    grouped,
    combined,
    ids: grouped
      .filter(function (row) {
        return row.type === "user-activity";
      })
      .map(function (row) {
        return getPostIdsForCombinedUserActivityPost(row.value);
      }),
    validActivity: isUserActivityProp(combined.props.user_activity),
    filtered: grouped.map(function (row) {
      if (row.type !== "post") return false;
      return shouldFilterJoinLeavePost(row.value.currentPost, false, "guest-1");
    }),
  };
}
function rnObserve(result) {
  const activity = result.combined.props.user_activity;
  return (
    result.grouped.length +
    activity.allUserIds.length +
    activity.allUsernames.length +
    activity.messageData.length +
    result.ids.length +
    result.filtered.filter(Boolean).length
  );
}
function rnFingerprint(result) {
  const grouped = result.grouped.map(function (item) {
    return item.type === "post"
      ? [item.type, item.value.currentPost.id, item.value.currentPost.deleteAt]
      : [item.type, item.value];
  });
  rnAssert(
    result.combined.type === Post.POST_TYPES.COMBINED_USER_ACTIVITY,
    "Invalid combined type"
  );
  rnAssert(
    result.validActivity && !isUserActivityProp({ messageData: [{}] }),
    "Invalid user activity structure"
  );
  return rnHash(JSON.stringify([grouped, result.combined, result.ids, result.filtered]));
}
rnBenchmark([
  { "fingerprint": 3616681284, "observation": 555 },
  { "fingerprint": 1962851515, "observation": 554 },
  { "fingerprint": 4024372499, "observation": 555 },
  { "fingerprint": 3613158829, "observation": 555 },
  { "fingerprint": 4069736705, "observation": 6 },
]);
