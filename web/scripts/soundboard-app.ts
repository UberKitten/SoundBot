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
import { GROUPS_API_PATH, SOUNDS_API_PATH, getRandomPrefix } from "config";
import { showGroupContextMenu } from "context-menu";
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

/** A sortable item: either a sound or a group. */
interface SortableItem {
  name: string;
  created: string | null;
  totalPlays: number;
  type: "sound" | "group";
  sound?: Sound;
  group?: SoundGroup;
}

function soundToSortable(sound: Sound): SortableItem {
  return {
    name: sound.name,
    created: sound.created,
    totalPlays: sound.discord_plays + sound.twitch_plays + sound.web_plays,
    type: "sound",
    sound,
  };
}

function groupToSortable(group: SoundGroup): SortableItem {
  return {
    name: group.name,
    created: group.created,
    totalPlays: group.discord_plays + group.twitch_plays + group.web_plays,
    type: "group",
    group,
  };
}

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
        this.handleDeepLink();
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
    const { group_name, members, action, created, discord_plays, twitch_plays, web_plays } = event;
    const groupData: SoundGroup = { name: group_name, members, created, discord_plays, twitch_plays, web_plays };

    if (action === "delete") {
      this.groups = this.groups.filter((g) => g.name !== group_name);
      const button = this.grid.querySelector(`.group-button[data-group-name="${group_name}"]`);
      if (button) button.remove();
      return;
    }

    if (action === "add") {
      this.groups.push(groupData);
      this.addGroupButton(groupData);
    } else {
      const idx = this.groups.findIndex((g) => g.name === group_name);
      if (idx !== -1) {
        this.groups[idx] = groupData;
      } else {
        this.groups.push(groupData);
      }
      // Update existing button
      const button = this.grid.querySelector(`.group-button[data-group-name="${group_name}"]`) as HTMLElement | null;
      if (button) {
        button.dataset.group = JSON.stringify(groupData);
        this.updateGroupButtonLabel(button as HTMLButtonElement, groupData);
      }
    }
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
    const sortable = soundToSortable(sound);
    const existingButtons = Array.from(
      this.grid.children as HTMLCollectionOf<HTMLElement>
    ).filter((btn) => !btn.classList.contains("no-display"));

    let insertBefore: HTMLElement | null = null;
    for (const existingButton of existingButtons) {
      const existingItem = this.getSortableFromButton(existingButton);
      if (!existingItem) continue;
      if (this.sortItems(sortable, existingItem) < 0) {
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

  sortItems(a: SortableItem, b: SortableItem) {
    if (!this.sortOrder) return 0;

    if (this.sort === "count") {
      return numericSort(a.totalPlays, b.totalPlays, this.sortOrder);
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

  sortSounds(a: Sound, b: Sound) {
    return this.sortItems(soundToSortable(a), soundToSortable(b));
  }

  filterSoundButtons(soundBtn: HTMLElement) {
    if (!this.filter) return true;

    // Group buttons
    const groupAttr = soundBtn.dataset.group;
    if (groupAttr) {
      const group = JSON.parse(groupAttr) as SoundGroup;
      return getCanonicalString(group.name)?.includes(this.filter) ?? false;
    }

    const soundAttr = soundBtn.getAttribute("sound");
    if (!soundAttr) return false;

    const sound = JSON.parse(soundAttr) as Sound;
    if (getCanonicalString(sound.name).includes(this.filter)) return true;
    return sound.aliases?.some((alias) =>
      getCanonicalString(alias)?.includes(this.filter)
    ) ?? false;
  }

  getSortableFromButton(button: HTMLElement): SortableItem | null {
    const groupAttr = button.dataset.group;
    if (groupAttr) {
      return groupToSortable(JSON.parse(groupAttr) as SoundGroup);
    }
    const soundAttr = button.getAttribute("sound");
    if (soundAttr) {
      return soundToSortable(JSON.parse(soundAttr) as Sound);
    }
    return null;
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
          this.grid.children as HTMLCollectionOf<HTMLElement>
        )
          .filter((button) => this.filterSoundButtons(button))
          .sort((a, b) => {
            const itemA = this.getSortableFromButton(a);
            const itemB = this.getSortableFromButton(b);
            if (!itemA || !itemB) return 0;
            return this.sortItems(itemA, itemB);
          });

        buttons.forEach((button) => button.classList.add("no-display"));

        const renderSliceSize = 50;
        let iButton = 0;
        const renderSlices: Array<{slice: HTMLElement[], startIndex: number}>  = [];

        while (iButton < buttons.length) {
          renderSlices.push({
            slice: buttons.slice(iButton, iButton + renderSliceSize),
            startIndex: iButton
          });
          iButton += renderSliceSize;
        }

        const renderSlice = (sliceData: {slice: HTMLElement[], startIndex: number}) => {
          sliceData.slice.forEach((sortedButton, indexInSlice) => {
            if (updatedProp === "sort") {
              // Update sort display for sound buttons
              if (sortedButton.getAttribute("sound")) {
                sortedButton.setAttribute("sort", this.sort ?? "");
              }
              // Update sort display for group buttons
              const groupAttr = sortedButton.dataset.group;
              if (groupAttr) {
                this.updateGroupButtonLabel(sortedButton as HTMLButtonElement, JSON.parse(groupAttr) as SoundGroup);
              }
            }

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
          this.grid.children as HTMLCollectionOf<HTMLElement>
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

      // Build unified sorted list of sounds and groups
      const items: SortableItem[] = [
        ...this.sounds.map(soundToSortable),
        ...this.groups.filter((g) => g.members.length > 0).map(groupToSortable),
      ].sort((a, b) => this.sortItems(a, b));

      const renderSliceSize = 50;
      let iItem = 0;
      const renderSlices: Array<SortableItem[]> = [];

      while (iItem < items.length) {
        renderSlices.push(items.slice(iItem, iItem + renderSliceSize));
        iItem += renderSliceSize;
      }

      const renderSlice = (slice: SortableItem[]) => {
        slice.forEach((item) => {
          let button: HTMLElement;

          if (item.type === "sound" && item.sound) {
            button = document.createElement("soundboard-button");
            button.setAttribute("sound", JSON.stringify(item.sound));
            button.setAttribute("sort", this.sort ?? "");
            if (this.singlePlay) button.setAttribute("singleplay", "true");
            if (
              this.filter &&
              !getCanonicalString(item.sound.name).includes(this.filter)
            )
              button.classList.add("no-display");
            button.dataset.copyText = `${getRandomPrefix()}${item.sound.name}`;
          } else if (item.type === "group" && item.group) {
            button = this.createGroupButton(item.group);
            if (this.filter && !getCanonicalString(item.group.name)?.includes(this.filter)) {
              button.classList.add("no-display");
            }
          } else {
            return;
          }

          button.classList.add("fade-in");
          button.style.animationDelay = `${buttonDelay(items.indexOf(item))}s`;

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
    }
  }

  getGroupSortDisplay(group: SoundGroup): string {
    if (this.sort === "count") {
      const totalPlays = group.discord_plays + group.twitch_plays + group.web_plays;
      return totalPlays === 1 ? "1 Play" : `${totalPlays} Plays`;
    } else if (this.sort === "date") {
      if (!group.created) return "";
      const createdDate = new Date(group.created);
      return createdDate.toLocaleDateString(undefined, {
        year: "numeric",
        month: "long",
        day: "numeric",
      });
    }
    return "\u00A0";
  }

  updateGroupButtonLabel(button: HTMLButtonElement, group: SoundGroup) {
    const sortDisplay = button.querySelector<HTMLElement>(".sortDisplay");
    if (sortDisplay) {
      sortDisplay.textContent = this.getGroupSortDisplay(group);
    }
    if (this.sort === "count" || this.sort === "date") {
      button.classList.remove("no-sublabel");
    } else {
      button.classList.add("no-sublabel");
    }
  }

  createGroupButton(group: SoundGroup): HTMLButtonElement {
    const button = document.createElement("button");
    button.className = "group-button";
    button.innerHTML = `
      <span class="icon hidden">&#x1F3B2;</span>
      <span>${group.name}</span>
      <span class="sortDisplay">${this.getGroupSortDisplay(group)}</span>`;
    button.dataset.groupName = group.name;
    button.dataset.group = JSON.stringify(group);
    button.dataset.copyText = `${getRandomPrefix()}${group.name}`;

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

    button.addEventListener("contextmenu", (e) => {
      showGroupContextMenu(e, group);
    });

    button.addEventListener("click", () => {
      const member = this.pickFromGroup(group);
      const sound = this.sounds.find((s) => s.name === member);
      if (sound) {
        button.dataset.playingSound = sound.name;
        playMainAudio(sound);
        startProgress();
        // Record group play
        fetch(`${GROUPS_API_PATH}/${encodeURIComponent(group.name)}/play`, {
          method: "POST",
        }).catch(() => {});
      }
      copy(button, button.querySelector<HTMLElement>(".sortDisplay"));
    });

    return button;
  }

  addGroupButton(group: SoundGroup) {
    if (group.members.length === 0) return;

    const button = this.createGroupButton(group);
    button.classList.add("fade-in");

    if (this.filter && !getCanonicalString(group.name)?.includes(this.filter)) {
      button.classList.add("no-display");
    }

    // Find the correct position based on current sort
    const sortable = groupToSortable(group);
    const existingButtons = Array.from(
      this.grid.children as HTMLCollectionOf<HTMLElement>
    ).filter((btn) => !btn.classList.contains("no-display"));

    let insertBefore: HTMLElement | null = null;
    for (const existingButton of existingButtons) {
      const existingItem = this.getSortableFromButton(existingButton);
      if (!existingItem) continue;
      if (this.sortItems(sortable, existingItem) < 0) {
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

  handleDeepLink() {
    const params = new URLSearchParams(window.location.search);
    const soundParam = params.get("sound");
    if (!soundParam) return;

    // Clean up the URL immediately
    const cleanUrl = new URL(window.location.href);
    cleanUrl.searchParams.delete("sound");
    history.replaceState(null, "", cleanUrl.pathname + cleanUrl.search);

    // Try to find as a sound first, then as a group
    const sound = this.sounds.find((s) => s.name === soundParam);
    const group = !sound ? this.groups.find((g) => g.name === soundParam) : undefined;

    if (!sound && !group) return;

    const displayName = sound ? sound.name : group!.name;
    const isGroup = !sound;

    // Show the deep link modal
    const overlay = document.createElement("div");
    overlay.className = "modal-overlay";

    const modal = document.createElement("div");
    modal.className = "modal deep-link-modal";

    const header = document.createElement("div");
    header.className = "modal-header";

    const title = document.createElement("h2");
    title.textContent = displayName;

    const closeBtn = document.createElement("button");
    closeBtn.className = "modal-close";
    closeBtn.textContent = "\u00d7";

    header.appendChild(title);
    header.appendChild(closeBtn);
    modal.appendChild(header);

    const body = document.createElement("div");
    body.className = "modal-body deep-link-body";

    const typeLabel = document.createElement("div");
    typeLabel.className = "deep-link-type";
    typeLabel.textContent = isGroup ? "🎲 Group" : "🔊 Sound";
    body.appendChild(typeLabel);

    const playBtn = document.createElement("button");
    playBtn.className = "deep-link-play";
    playBtn.textContent = "▶ Play";
    body.appendChild(playBtn);

    modal.appendChild(body);
    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    const close = () => overlay.remove();

    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) close();
    });

    closeBtn.addEventListener("click", close);

    document.addEventListener("keydown", function handler(e) {
      if (e.key === "Escape") {
        close();
        document.removeEventListener("keydown", handler);
      }
    });

    playBtn.addEventListener("click", () => {
      if (sound) {
        playMainAudio(sound);
      } else if (group) {
        const member = this.pickFromGroup(group);
        const memberSound = this.sounds.find((s) => s.name === member);
        if (memberSound) {
          playMainAudio(memberSound);
          // Record group play
          fetch(`${GROUPS_API_PATH}/${encodeURIComponent(group.name)}/play`, {
            method: "POST",
          }).catch(() => {});
        }
      }
      close();
    });
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
          ? {
              sounds: json.sounds as Sound[],
              groups: (Array.isArray(json.groups) ? json.groups : []) as SoundGroup[],
            }
          : undefined,
    });
  }
}
