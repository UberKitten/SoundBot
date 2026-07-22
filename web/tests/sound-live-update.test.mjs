import assert from "node:assert/strict";
import test from "node:test";

import {
  applySoundLiveUpdate,
  findSoundInSnapshot,
  mergeSoundRepresentation,
  replaceSoundRepresentation,
  soundMatchesFilter,
} from "../scripts/sound-live-update.ts";

function deferred() {
  let resolve;
  const promise = new Promise((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

function sound(overrides = {}) {
  return {
    name: "airhorn",
    audio_path: "/sounds/airhorn.ogg",
    modified: "2026-07-20T12:00:00Z",
    aliases: ["old-alias"],
    volume_adjust: 0,
    web_plays: 4,
    ...overrides,
  };
}

test("finds a sound inside the API snapshot envelope", () => {
  const wanted = sound({ modified: "2026-07-21T12:00:00Z" });
  const snapshot = {
    sounds: [sound({ name: "applause" }), wanted],
    groups: [{ name: "favorites", members: ["airhorn"] }],
  };

  assert.strictEqual(findSoundInSnapshot(snapshot, "airhorn"), wanted);
  assert.equal(findSoundInSnapshot(snapshot, "missing"), null);
});

test("same-name full merges preserve cached and active playback identity", () => {
  const activePlaybackSound = sound({ obsolete_field: true });
  const freshSound = sound({
    audio_path: "/sounds/airhorn-new.ogg",
    modified: "2026-07-21T12:00:00Z",
    aliases: ["new-alias"],
    volume_adjust: 2,
    web_plays: 5,
  });
  const cachedSounds = [activePlaybackSound];
  let renderedSound = null;

  assert.equal(
    replaceSoundRepresentation(
      cachedSounds,
      "airhorn",
      freshSound,
      (updatedSound) => {
        renderedSound = updatedSound;
      }
    ),
    true
  );

  assert.strictEqual(cachedSounds[0], activePlaybackSound);
  assert.strictEqual(renderedSound, activePlaybackSound);
  assert.deepEqual(activePlaybackSound, freshSound);
  assert.equal("obsolete_field" in activePlaybackSound, false);
  assert.equal(activePlaybackSound.volume_adjust, 2);

  const buttonPlaybackSound = sound();
  const buttonIdentity = buttonPlaybackSound;
  mergeSoundRepresentation(buttonPlaybackSound, freshSound);
  assert.strictEqual(buttonPlaybackSound, buttonIdentity);
  assert.deepEqual(buttonPlaybackSound, freshSound);
});

test("edit handler awaits the snapshot, applies full state, and reapplies alias filtering", async () => {
  const staleSound = sound();
  const cachedSounds = [staleSound];
  let buttonSoundAttribute = JSON.stringify(staleSound);
  let hidden = true;
  let info = 'no sounds match "fresh-alias"';
  const fetched = deferred();

  const update = applySoundLiveUpdate(
    {
      action: "edit",
      sound_name: "airhorn",
      modified: "2026-07-21T12:00:00Z",
    },
    {
      sounds: cachedSounds,
      generations: new Map(),
      fetchSound: () => fetched.promise,
      addRenderedSound: () => assert.fail("edit must not add a button"),
      updateRenderedSound: (updatedSound) => {
        buttonSoundAttribute = JSON.stringify(updatedSound);
      },
      removeRenderedSound: () => assert.fail("edit must not remove a button"),
      reapplyFilter: () => {
        const renderedSound = JSON.parse(buttonSoundAttribute);
        hidden = !soundMatchesFilter(
          renderedSound,
          "fresh-alias",
          (value) => value.toLowerCase()
        );
        info = hidden ? 'no sounds match "fresh-alias"' : null;
      },
    }
  );

  assert.deepEqual(cachedSounds[0], staleSound);
  fetched.resolve(
    sound({
      audio_path: "/sounds/airhorn-edited.ogg",
      modified: "2026-07-21T12:00:00Z",
      aliases: ["fresh-alias"],
      volume_adjust: -2,
      web_plays: 9,
    })
  );
  assert.equal(await update, "edited");

  assert.strictEqual(cachedSounds[0], staleSound);
  assert.deepEqual(JSON.parse(buttonSoundAttribute), cachedSounds[0]);
  assert.equal(cachedSounds[0].audio_path, "/sounds/airhorn-edited.ogg");
  assert.deepEqual(cachedSounds[0].aliases, ["fresh-alias"]);
  assert.equal(cachedSounds[0].volume_adjust, -2);
  assert.equal(cachedSounds[0].web_plays, 9);
  assert.equal(hidden, false);
  assert.equal(info, null);
});

test("an alias-removing edit hides the button and restores empty-result info", async () => {
  const cachedSounds = [sound({ aliases: ["fresh-alias"] })];
  let buttonSoundAttribute = JSON.stringify(cachedSounds[0]);
  let hidden = false;
  let info = null;

  const result = await applySoundLiveUpdate(
    {
      action: "edit",
      sound_name: "airhorn",
      modified: "2026-07-21T13:00:00Z",
    },
    {
      sounds: cachedSounds,
      generations: new Map(),
      fetchSound: async () =>
        sound({
          modified: "2026-07-21T13:00:00Z",
          aliases: [],
        }),
      addRenderedSound: () => assert.fail("edit must not add a button"),
      updateRenderedSound: (updatedSound) => {
        buttonSoundAttribute = JSON.stringify(updatedSound);
      },
      removeRenderedSound: () => assert.fail("edit must not remove a button"),
      reapplyFilter: () => {
        hidden = !soundMatchesFilter(
          JSON.parse(buttonSoundAttribute),
          "fresh-alias",
          (value) => value.toLowerCase()
        );
        info = hidden ? 'no sounds match "fresh-alias"' : null;
      },
    }
  );

  assert.equal(result, "edited");
  assert.equal(hidden, true);
  assert.equal(info, 'no sounds match "fresh-alias"');
});

test("a slower edit response cannot overwrite a newer edit", async () => {
  const cachedSounds = [sound()];
  const firstFetch = deferred();
  const secondFetch = deferred();
  const fetches = [firstFetch, secondFetch];
  const generations = new Map();
  let renderedSound = null;
  const bindings = {
    sounds: cachedSounds,
    generations,
    fetchSound: () => fetches.shift().promise,
    addRenderedSound: () => assert.fail("edit must not add a button"),
    updateRenderedSound: (updatedSound) => {
      renderedSound = structuredClone(updatedSound);
    },
    removeRenderedSound: () => assert.fail("edit must not remove a button"),
    reapplyFilter: () => {},
  };

  const firstUpdate = applySoundLiveUpdate(
    { action: "edit", sound_name: "airhorn", modified: "first-event" },
    bindings
  );
  const secondUpdate = applySoundLiveUpdate(
    { action: "edit", sound_name: "airhorn", modified: "second-event" },
    bindings
  );

  const newestSound = sound({
    audio_path: "/sounds/newest.ogg",
    modified: "second-response",
    aliases: ["newest"],
    volume_adjust: 3,
  });
  secondFetch.resolve(newestSound);
  assert.equal(await secondUpdate, "edited");

  firstFetch.resolve(
    sound({
      audio_path: "/sounds/stale.ogg",
      modified: "first-response",
      aliases: ["stale"],
      volume_adjust: -5,
    })
  );
  assert.equal(await firstUpdate, "stale");
  assert.deepEqual(cachedSounds[0], newestSound);
  assert.deepEqual(renderedSound, newestSound);
});

for (const laterAction of ["add", "delete", "edit"]) {
  test(`a later ${laterAction} action invalidates a pending edit`, async () => {
    const cachedSounds = [sound()];
    const oldFetch = deferred();
    const latestFetch = deferred();
    const fetches = [oldFetch, latestFetch];
    const generations = new Map();
    let renderedUpdates = 0;
    const bindings = {
      sounds: cachedSounds,
      generations,
      fetchSound: () => fetches.shift().promise,
      addRenderedSound: () => {},
      updateRenderedSound: () => {
        renderedUpdates += 1;
      },
      removeRenderedSound: () => {},
      reapplyFilter: () => {},
    };

    const pendingEdit = applySoundLiveUpdate(
      { action: "edit", sound_name: "airhorn", modified: "old-event" },
      bindings
    );
    const laterUpdate = applySoundLiveUpdate(
      { action: laterAction, sound_name: "airhorn", modified: "latest-event" },
      bindings
    );

    if (laterAction !== "delete") {
      latestFetch.resolve(
        sound({
          modified: "latest-response",
          aliases: ["latest"],
          volume_adjust: 1,
        })
      );
      await laterUpdate;
    } else {
      assert.equal(await laterUpdate, "deleted");
    }

    oldFetch.resolve(
      sound({
        modified: "stale-response",
        aliases: ["stale"],
        volume_adjust: -4,
      })
    );
    assert.equal(await pendingEdit, "stale");
    assert.equal(
      cachedSounds.some((candidate) => candidate.modified === "stale-response"),
      false
    );
    assert.equal(renderedUpdates, laterAction === "edit" ? 1 : 0);
  });
}

test("a delete invalidates a pending add so it cannot resurrect the sound", async () => {
  const pendingFetch = deferred();
  const cachedSounds = [];
  const generations = new Map();
  let added = false;
  const bindings = {
    sounds: cachedSounds,
    generations,
    fetchSound: () => pendingFetch.promise,
    addRenderedSound: () => {
      added = true;
    },
    updateRenderedSound: () => {},
    removeRenderedSound: () => {},
    reapplyFilter: () => {},
  };

  const pendingAdd = applySoundLiveUpdate(
    { action: "add", sound_name: "airhorn", modified: "add-event" },
    bindings
  );
  assert.equal(
    await applySoundLiveUpdate(
      { action: "delete", sound_name: "airhorn", modified: "delete-event" },
      bindings
    ),
    "deleted"
  );
  pendingFetch.resolve(sound({ modified: "stale-add-response" }));

  assert.equal(await pendingAdd, "stale");
  assert.deepEqual(cachedSounds, []);
  assert.equal(added, false);
});
