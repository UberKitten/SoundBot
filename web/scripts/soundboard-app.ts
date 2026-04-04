import {
  Sound,
  SoundGroup,
  addMainAudioChangeListener,
  getMainAudioProgress,
  isSoundObject,
  isMainAudioActive,
  playMainAudio,
} from "audio";
import { copy } from "clipboard";
import { SOUNDS_API_PATH, getRandomPrefix } from "config";
import { init } from "dom-init";
import {
  alphaSort,
  cancelBackgroundTasks,
  clearError,
  clearInfo,
  fetchJson,
  getCanonicalString,
  getElement,
  numericSort,
  scheduleBackgroundTask,
  setError,
  setInfo,
} from "utils";
import { GroupUpdateEvent, SoundUpdateEvent, onGroupUpdate, onSoundUpdate } from "websocket";

export class SoundboardApp extends HTMLElement {
  sounds: Array<Sound> = [];
  groups: Array<SoundGroup> = [];
  filter = "";
  sort: string | null = null;
  sortOrder: "asc" | "desc" | null = null;
  singlePlay: boolean = true;
  grid: HTMLElement;
  activeRenders: number[] = [];
  firstRenderCompleted = false;
  unsubscribeWebSocket: (() => void) | null = null;
  unsubscribeGroupWebSocket: (() => void) | null = null;
  groupShuffleBags: Map<string, string[]> = new Map();

  constructor() {
    super();

    try {
      init();
      this.grid = getElement(".grid");
    } catch (e) {
      setError(new Error("Could not initialize UI - missing elements"));
      throw e;
    }
  }

  connectedCallback() {
    const sortOrder = this.getAttribute("sortorder");
    this.singlePlay = !(this.getAttribute("singleplay") === "no");

    this.filter = this.getAttribute("filter") ?? "";
    this.sort = this.getAttribute("sort") ?? "";
    this.sortOrder =
      sortOrder === "asc" || sortOrder === "desc" ? sortOrder : null;

    clearError();

    this.fetchSounds()
      .then((result) => {
        const { sounds, groups } = result as { sounds: Array<Sound>; groups: Array<SoundGroup> };
        this.sounds = sounds;
        this.groups = groups;
        this.updateSoundButtons();
      })
      .catch((error) => setError(error));

    // Subscribe to real-time updates
    this.unsubscribeWebSocket = onSoundUpdate((event) => this.handleSoundUpdate(event));
    this.unsubscribeGroupWebSocket = onGroupUpdate((event) => this.handleGroupUpdate(event));
  }

  disconnectedCallback() {
    if (this.unsubscribeWebSocket) {
      this.unsubscribeWebSocket();
      this.unsubscribeWebSocket = null;
    }
    if (this.unsubscribeGroupWebSocket) {
      this.unsubscribeGroupWebSocket();
      this.unsubscribeGroupWebSocket = null;
    }
  }

  /**
   * Handle real-time sound update from WebSocket.
   * Updates the sound's modified timestamp to bust the cache.
   */
  handleSoundUpdate(event: SoundUpdateEvent) {
    const soundName = event.sound_name;
    const newModified = event.modified;

    if (event.action === "delete") {
      // Remove the sound from our list
      const index = this.sounds.findIndex((s) => s.name === soundName);
      if (index !== -1) {
        this.sounds.splice(index, 1);
      }

      // Remove the button from the grid
      const button = this.grid.querySelector(
        `soundboard-button[sound*='"name":"${soundName}"']`
      ) as HTMLElement | null;
      if (button) {
        button.remove();
      }
      console.log(`[ws] Removed sound button: ${soundName}`);
      return;
    }

    if (event.action === "add") {
      // For new sounds, fetch the sound data and add it
      console.log(`[ws] Adding new sound: ${soundName}`);
      this.fetchSingleSound(soundName)
        .then((sound) => {
          if (sound) {
            this.sounds.push(sound);
            this.addSoundButton(sound);
            console.log(`[ws] Added sound button: ${soundName}`);
          } else {
            console.warn(`[ws] Could not fetch sound data for: ${soundName}`);
          }
        })
        .catch((e) => {
          console.error(`[ws] Error adding sound ${soundName}:`, e);
        });
      return;
    }

    // For edit actions, update the modified timestamp
    const sound = this.sounds.find((s) => s.name === soundName);
    if (sound) {
      sound.modified = newModified;

      // Update the button's sound attribute to trigger cache bust
      const button = this.grid.querySelector(
        `soundboard-button[sound*='"name":"${soundName}"']`
      ) as HTMLElement | null;
      if (button) {
        button.setAttribute("sound", JSON.stringify(sound));
      }
    }
  }

  handleGroupUpdate(event: GroupUpdateEvent) {
    const { group_name, members, action } = event;

    if (action === "delete") {
      this.groups = this.groups.filter((g) => g.name !== group_name);
    } else if (action === "add") {
      this.groups.push({ name: group_name, members });
    } else {
      const group = this.groups.find((g) => g.name === group_name);
      if (group) {
        group.members = members;
      } else {
        this.groups.push({ name: group_name, members });
      }
    }

    this.renderGroupButtons();
  }

  /**
   * Fetch a single sound by name from the sounds API.
   */
  async fetchSingleSound(name: string): Promise<Sound | null> {
    try {
      // Fetch all sounds and find the one we need
      // This reuses the existing fetchSounds logic which properly parses the response
      const allSounds = await this.fetchSounds() as Sound[];
      const sound = allSounds.find((s) => s.name === name);
      if (sound) {
        return sound;
      }
      console.warn(`[ws] Sound "${name}" not found in API response`);
      return null;
    } catch (e) {
      console.error(`[ws] Error fetching sound "${name}":`, e);
      return null;
    }
  }

  /**
   * Add a single sound button to the grid in the correct sorted position.
   */
  addSoundButton(sound: Sound) {
    const button = document.createElement("soundboard-button");
    button.setAttribute("sound", JSON.stringify(sound));
    button.setAttribute("sort", this.sort ?? "");
    if (this.singlePlay) button.setAttribute("singleplay", "true");
    button.classList.add("fade-in");
    button.dataset.copyText = `${getRandomPrefix()}${sound.name}`;

    // Hide if it doesn't match the current filter
    if (this.filter && !getCanonicalString(sound.name)?.includes(this.filter) &&
        !sound.aliases?.some((alias) => getCanonicalString(alias)?.includes(this.filter))) {
      button.classList.add("no-display");
    }

    // Find the correct position to insert based on current sort
    const existingButtons = Array.from(
      this.grid.children as HTMLCollectionOf<HTMLElement>
    ).filter((btn) => !btn.classList.contains("no-display"));

    let insertBefore: HTMLElement | null = null;
    for (const existingButton of existingButtons) {
      const existingSoundAttr = existingButton.getAttribute("sound");
      if (!existingSoundAttr) continue;

      const existingSound = JSON.parse(existingSoundAttr) as Sound;
      // If new sound should come before this one, insert here
      if (this.sortSounds(sound, existingSound) < 0) {
        insertBefore = existingButton;
        break;
      }
    }

    if (insertBefore) {
      this.grid.insertBefore(button, insertBefore);
    } else {
      this.grid.appendChild(button);
    }
  }

  sortSounds(a: Sound, b: Sound) {
    if (!this.sortOrder) return 0;

    if (this.sort === "count") {
      const aPlays = a.discord_plays + a.twitch_plays + a.web_plays;
      const bPlays = b.discord_plays + b.twitch_plays + b.web_plays;
      return numericSort(aPlays, bPlays, this.sortOrder);
    } else if (this.sort === "date") {
      const aTime = a.created ? new Date(a.created).getTime() : 0;
      const bTime = b.created ? new Date(b.created).getTime() : 0;
      return numericSort(aTime, bTime, this.sortOrder);
    } else if (this.sort === "alpha") {
      return alphaSort(a.name, b.name, this.sortOrder);
    } else {
      return 0;
    }
  }

  filterSoundButtons(soundBtn: HTMLButtonElement) {
    if (!this.filter) return true;

    // Group buttons
    const groupName = soundBtn.dataset.groupName;
    if (groupName) {
      return getCanonicalString(groupName)?.includes(this.filter) ?? false;
    }

    const soundAttr = soundBtn.getAttribute("sound");
    if (!soundAttr) return false;

    const sound = JSON.parse(soundAttr) as Sound;
    if (getCanonicalString(sound.name).includes(this.filter)) return true;
    return sound.aliases?.some((alias) =>
      getCanonicalString(alias)?.includes(this.filter)
    ) ?? false;
  }

  updateSoundButtons(updatedProp?: string) {
    function buttonDelay(i: number) {
      return Math.min(i * 0.0025, 0.5);
    }

    // this is ok for now since we only load sounds once
    if (this.firstRenderCompleted && updatedProp) {
      // update

      if (updatedProp === "sortorder" || updatedProp === "sort") {
        cancelBackgroundTasks(this.activeRenders);

        const buttons = Array.from(
          this.grid.children as HTMLCollectionOf<HTMLButtonElement>
        )
          .filter((button) => this.filterSoundButtons(button))
          .sort((a, b) => {
            const soundA: Sound = JSON.parse(a.getAttribute("sound")!);
            const soundB: Sound = JSON.parse(b.getAttribute("sound")!);
            return this.sortSounds(soundA, soundB);
          });

        buttons.forEach((button) => button.classList.add("no-display"));

        const renderSliceSize = 50;
        let iButton = 0;
        const renderSlices: Array<{slice: HTMLButtonElement[], startIndex: number}>  = [];

        while (iButton < buttons.length) {
          renderSlices.push({
            slice: buttons.slice(iButton, iButton + renderSliceSize),
            startIndex: iButton
          });
          iButton += renderSliceSize;
        }

        const renderSlice = (sliceData: {slice: HTMLButtonElement[], startIndex: number}) => {
          sliceData.slice.forEach((sortedButton, indexInSlice) => {
            if (updatedProp === "sort")
              sortedButton.setAttribute("sort", this.sort ?? "");

            const absoluteIndex = sliceData.startIndex + indexInSlice;
            sortedButton.style.animationDelay = `${buttonDelay(absoluteIndex)}s`;
            sortedButton.classList.remove("no-display");

            // Calling appendChild with an existing node reorders it, no need to clone!
            this.grid.appendChild(sortedButton);
          });
        };

        const sliceIterator = renderSlices.entries();
        let nextSlice = sliceIterator.next();

        while (!nextSlice.done) {
          const slice = nextSlice.value[1];
          this.activeRenders.push(
            scheduleBackgroundTask(() => renderSlice(slice))
          );
          nextSlice = sliceIterator.next();
        }
      } else {
        const buttons = Array.from(
          this.grid.children as HTMLCollectionOf<HTMLButtonElement>
        );

        const filteredButtons = buttons.filter((button) =>
          this.filterSoundButtons(button)
        );

        buttons.forEach((button) => {
          if (updatedProp === "singleplay" && this.singlePlay)
            button.setAttribute(updatedProp, "true");

          if (updatedProp === "singleplay" && !this.singlePlay)
            button.removeAttribute(updatedProp);

          if (updatedProp === "filter") {
            button.classList.add("no-display");

            if (filteredButtons.includes(button)) {
              button.style.animationDelay = `${buttonDelay(
                filteredButtons.indexOf(button)
              )}s`;
              button.classList.remove("no-display");
            }

            if (filteredButtons.length > 0) {
              clearInfo();
            } else {
              setInfo(`no sounds match "${this.filter}"`);
            }
          }
        });
      }
    } else {
      // first render with real data

      cancelBackgroundTasks(this.activeRenders);
      this.grid.innerText = "";

      const sounds = this.sounds.sort((a, b) => this.sortSounds(a, b));

      const renderSliceSize = 50;
      let iSound = 0;
      const renderSlices: Array<Sound[]> = [];

      while (iSound < sounds.length) {
        renderSlices.push(sounds.slice(iSound, iSound + renderSliceSize));
        iSound += renderSliceSize;
      }

      const renderSlice = (slice: Sound[]) => {
        slice.forEach((sound) => {
          const button = document.createElement("soundboard-button");
          button.setAttribute("sound", JSON.stringify(sound));
          button.setAttribute("sort", this.sort ?? "");
          if (this.singlePlay) button.setAttribute("singleplay", "true");
          if (
            this.filter &&
            !getCanonicalString(sound.name).includes(this.filter)
          )
            button.classList.add("no-display");

          button.classList.add("fade-in");
          button.style.animationDelay = `${buttonDelay(
            sounds.indexOf(sound)
          )}s`;
          button.dataset.copyText = `${getRandomPrefix()}${sound.name}`;

          this.grid.appendChild(button);
        });

        this.firstRenderCompleted =
          renderSlices[renderSlices.length - 1] === slice;
      };

      const sliceIterator = renderSlices.entries();
      let nextSlice = sliceIterator.next();

      while (!nextSlice.done) {
        const slice = nextSlice.value[1];
        this.activeRenders.push(
          scheduleBackgroundTask(() => renderSlice(slice))
        );
        nextSlice = sliceIterator.next();
      }

      // Render group buttons
      this.activeRenders.push(
        scheduleBackgroundTask(() => this.renderGroupButtons())
      );
    }
  }

  renderGroupButtons() {
    // Remove existing group buttons
    this.grid.querySelectorAll(".group-button").forEach((el) => el.remove());

    for (const group of this.groups) {
      if (group.members.length === 0) continue;

      const button = document.createElement("button");
      button.className = "group-button fade-in";
      button.innerHTML = `
        <span class="icon hidden">&#x1F3B2;</span>
        <span>${group.name}</span>
        <span class="sortDisplay">${group.members.length} sound${group.members.length === 1 ? "" : "s"}</span>`;
      button.dataset.groupName = group.name;
      button.dataset.copyText = `${getRandomPrefix()}${group.name}`;

      // Filter visibility
      if (this.filter && !getCanonicalString(group.name)?.includes(this.filter)) {
        button.classList.add("no-display");
      }

      let progressId: number | null = null;

      const stopProgress = () => {
        if (progressId !== null) {
          cancelAnimationFrame(progressId);
          progressId = null;
        }
        button.style.removeProperty("--progress");
        button.classList.remove("single-playing");
      };

      const startProgress = () => {
        if (progressId !== null) return;
        button.classList.add("single-playing");
        const tick = () => {
          button.style.setProperty("--progress", `${getMainAudioProgress() * 100}%`);
          progressId = requestAnimationFrame(tick);
        };
        progressId = requestAnimationFrame(tick);
      };

      addMainAudioChangeListener(() => {
        if (button.dataset.playingSound && isMainAudioActive()) {
          startProgress();
        } else {
          stopProgress();
          delete button.dataset.playingSound;
        }
      });

      button.addEventListener("click", () => {
        const member = this.pickFromGroup(group);
        const sound = this.sounds.find((s) => s.name === member);
        if (sound) {
          button.dataset.playingSound = sound.name;
          playMainAudio(sound);
          startProgress();
        }
        copy(button, button.querySelector<HTMLElement>(".sortDisplay"));
      });

      this.grid.appendChild(button);
    }
  }

  pickFromGroup(group: SoundGroup): string {
    let bag = this.groupShuffleBags.get(group.name);
    if (!bag || bag.length === 0) {
      // Refill and shuffle (Fisher-Yates)
      bag = [...group.members];
      for (let i = bag.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [bag[i], bag[j]] = [bag[j], bag[i]];
      }
      this.groupShuffleBags.set(group.name, bag);
    }
    return bag.pop()!;
  }

  attributeChangedCallback(
    property: string,
    oldValue: string | null,
    newValue: string | null
  ) {
    if (oldValue === newValue) return;

    if (property === "filter") this.filter = getCanonicalString(newValue) ?? "";
    if (property === "sort") this.sort = newValue;
    if (property === "sortorder")
      this.sortOrder =
        newValue === "asc" || newValue === "desc" ? newValue : null;
    if (property === "singleplay") this.singlePlay = !(newValue === "no");

    this.updateSoundButtons(property);
  }

  static get observedAttributes() {
    return ["filter", "sort", "sortorder", "singleplay"];
  }

  async fetchSounds() {
    return await fetchJson({
      url: SOUNDS_API_PATH,
      parser: (json) =>
        json &&
        typeof json === "object" &&
        !Array.isArray(json) &&
        Array.isArray(json.sounds) &&
        !json.sounds.find((sound: unknown) => !isSoundObject(sound))
          ? { sounds: json.sounds, groups: Array.isArray(json.groups) ? json.groups : [] }
          : undefined,
    });
  }
}
