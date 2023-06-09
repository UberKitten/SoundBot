import {
  Sound,
  addMainAudioChangeListener,
  getActiveAudioGroups,
  isMainAudioActive,
  isSoundObject,
  playButtonAudio,
  playMainAudio,
  setVolume,
  stopAllButtonAudio,
  stopMainAudio,
} from "audio";
import { copy } from "clipboard";
import { DB_PATH, SOUNDS_PATH } from "config";
import {
  alphaSort,
  clearError,
  fetchJson,
  getCanonicalString,
  getDisplayDate,
  numericSort,
  setError,
} from "utils";

class Soundboard extends HTMLElement {
  sounds: Array<Sound> = [];
  filter = "";
  sort: string | null = null;
  sortOrder: "asc" | "desc" | null = null;
  singlePlay: boolean = false;
  grid?: HTMLElement | null;

  connectedCallback() {
    const gridContainer = this.querySelector(".grid") as HTMLElement | null;
    const sortOrder = this.getAttribute("sortorder");
    this.singlePlay = !!this.getAttribute("singleplay");

    this.filter = this.getAttribute("filter") ?? "";
    this.sort = this.getAttribute("sort") ?? "";
    this.sortOrder =
      sortOrder === "asc" || sortOrder === "desc" ? sortOrder : null;
    this.grid = gridContainer;

    clearError();

    this.fetchSounds()
      .then((sounds) => {
        this.sounds = sounds as Array<Sound>;
        this.updateSoundButtons();
      })
      .catch((error) => setError(error));
  }

  sortSounds(a: Sound, b: Sound) {
    if (!this.sortOrder) return 0;

    if (this.sort === "count") {
      return numericSort(a.count, b.count, this.sortOrder);
    } else if (this.sort === "date") {
      return numericSort(a.modified, b.modified, this.sortOrder);
    } else if (this.sort === "alpha") {
      return alphaSort(a.name, b.name, this.sortOrder);
    } else {
      return 0;
    }
  }

  updateSoundButtons(updatedProp?: string) {
    if (!this.grid) return;

    // this is ok for now since we only load sounds once
    if (this.grid.children.length === this.sounds.length && updatedProp) {
      // update

      if (updatedProp === "sortorder" || updatedProp === "sort") {
        Array.from(this.grid.children)
          .sort((a, b) => {
            const soundA: Sound = JSON.parse(a.getAttribute("sound")!);
            const soundB: Sound = JSON.parse(b.getAttribute("sound")!);
            return this.sortSounds(soundA, soundB);
          })
          .forEach((sortedButton) => {
            if (updatedProp === "sort")
              sortedButton.setAttribute("sort", this.sort ?? "");

            // Calling appendChild with an existing node reorders it, no need to clone!
            this.grid?.appendChild(sortedButton);
          });
      } else {
        Array.from(this.grid.children).forEach((button) => {
          if (updatedProp === "singleplay" && this.singlePlay)
            button.setAttribute(updatedProp, "true");

          if (updatedProp === "singleplay" && !this.singlePlay)
            button.removeAttribute(updatedProp);

          if (updatedProp === "filter") {
            const sound: Sound = JSON.parse(button.getAttribute("sound")!);

            if (
              this.filter &&
              !getCanonicalString(sound.name).includes(this.filter)
            ) {
              button.classList.add("no-display");
            } else {
              button.classList.remove("no-display");
            }
          }
        });
      }
    } else {
      // first render with real data

      this.sounds
        .sort((a, b) => this.sortSounds(a, b))
        .forEach((sound) => {
          const button = document.createElement("soundboard-button");
          button.setAttribute("sound", JSON.stringify(sound));
          button.setAttribute("sort", this.sort ?? "");
          if (this.singlePlay) button.setAttribute("singleplay", "true");
          if (
            this.filter &&
            !getCanonicalString(sound.name).includes(this.filter)
          )
            button.classList.add("no-display");
          button.dataset.copyText = `!${sound.name}`;
          this.grid?.appendChild(button);
        });
    }
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
    if (property === "singleplay") this.singlePlay = !!newValue;

    this.updateSoundButtons(property);
  }

  static get observedAttributes() {
    return ["filter", "sort", "sortorder", "singleplay"];
  }

  async fetchSounds() {
    return await fetchJson({
      url: DB_PATH,
      parser: (json) =>
        json &&
        typeof json === "object" &&
        !Array.isArray(json) &&
        Array.isArray(json.sounds) &&
        !json.sounds.find((sound: unknown) => !isSoundObject(sound))
          ? json.sounds
          : undefined,
    });
  }
}

customElements.define("soundboard-app", Soundboard);

class SoundboardButton extends HTMLElement {
  sound?: Sound;
  sort: string | null = null;
  singlePlay: boolean | null = null;

  connectedCallback() {
    this.sort = this.getAttribute("sort");
    this.singlePlay = !!this.getAttribute("singleplay");

    const soundData = this.getAttribute("sound");

    if (!soundData) return;

    this.sound = JSON.parse(soundData) as Sound;

    this.updateLabel();
    this.updateIndicators();
    addMainAudioChangeListener(() => this.updateIndicators());

    this.onclick = (e) => {
      if (!this.sound) return;

      if (this.singlePlay && isMainAudioActive(this.sound)) {
        stopMainAudio();
        this.updateIndicators();
        return;
      }

      if (this.singlePlay) {
        playMainAudio(this.sound);
      } else {
        playButtonAudio(this.sound, () => this.updateIndicators());
      }

      this.updateIndicators();

      const currentTarget = e.currentTarget;
      if (!(currentTarget instanceof HTMLElement)) return;

      copy(
        currentTarget,
        currentTarget.querySelector(".sortDisplay") as HTMLElement | null
      );
    };
  }

  updateIndicators() {
    const isPlaying = getActiveAudioGroups(this.sound).size > 0;

    this.singlePlay && isPlaying
      ? this.classList.add("single-playing")
      : this.classList.remove("single-playing");

    const icon = this.querySelector(".icon");
    if (!(icon instanceof HTMLElement)) return;

    isPlaying ? icon.classList.remove("hidden") : icon.classList.add("hidden");
  }

  updateLabel() {
    if (!this.sound) {
      this.innerHTML = `
        <span>Sound unavilable</span>
        <span>&nbsp;</span>`;

      return;
    }

    const sublabels: Map<string | null, string> = new Map([
      [
        "count",
        `${
          this.sound.count === 1
            ? "1 Play"
            : this.sound.count.toString().concat(" Plays")
        }`,
      ],
      ["date", getDisplayDate(this.sound.modified)],
    ]);

    this.innerHTML = `
      <span class="icon hidden">&#x1F50A;</span>
      <span>${this.sound.name}</span>
      <span class="sortDisplay">${sublabels.get(this.sort) ?? "&nbsp;"}</span>`;

    if (sublabels.get(this.sort)) {
      this.classList.remove("no-sublabel");
    } else {
      this.classList.add("no-sublabel");
    }
  }

  attributeChangedCallback(
    property: string,
    oldValue: string | null,
    newValue: string | null
  ) {
    if (oldValue === newValue) return;

    if (property === "sound")
      this.sound = newValue ? JSON.parse(newValue) : undefined;
    if (property === "sort") this.sort = newValue;
    if (property === "singleplay") this.singlePlay = !!newValue;

    this.updateLabel();
    this.updateIndicators();
  }

  static get observedAttributes() {
    return ["sound", "sort", "singleplay"];
  }
}

customElements.define("soundboard-button", SoundboardButton);

function init() {
  const app = document.querySelector("soundboard-app") as HTMLElement;

  const searchInput = document.querySelector(
    "input[type=search]"
  ) as HTMLInputElement | null;

  const sortSelect = document.querySelector(
    "#sort"
  ) as HTMLSelectElement | null;

  const singlePlayCheckbox = document.querySelector(
    "input#single-sound"
  ) as HTMLInputElement | null;

  const volumeSlider = document.querySelector(
    "input#volume"
  ) as HTMLInputElement | null;

  const stopButton = document.querySelector(
    "button#stop"
  ) as HTMLButtonElement | null;

  const sortOrderRadios = document.querySelectorAll(
    "input[name=sortorder]"
  ) as NodeListOf<HTMLInputElement>;

  function getSelectedSortOrderRadio() {
    return Array.from(sortOrderRadios).find((radio) =>
      radio.matches(":checked")
    ) as HTMLInputElement | null;
  }

  if (!app) {
    console.error("Couldn't find app mount point");
    return;
  }

  function setFilter(search: string) {
    app.setAttribute("filter", search);
  }

  function setSort(sortBy: string) {
    app.setAttribute("sort", sortBy);
  }

  function setSortOrder(order: string) {
    app.setAttribute("sortorder", order);
  }

  function setSinglePlay(singlePlay: boolean) {
    if (singlePlay) {
      app.setAttribute("singleplay", "true");
    } else {
      app.removeAttribute("singleplay");
    }
  }

  searchInput?.addEventListener("input", () => {
    setFilter(searchInput.value);
  });

  volumeSlider?.addEventListener("input", () => {
    setVolume(volumeSlider.value);
  });

  stopButton?.addEventListener("click", () => {
    stopMainAudio();
    stopAllButtonAudio();
  });

  singlePlayCheckbox?.addEventListener("input", () => {
    if (singlePlayCheckbox.matches(":checked")) {
      stopAllButtonAudio();
      if (stopButton) stopButton.innerText = "Stop";
      setSinglePlay(true);
    } else {
      if (stopButton) stopButton.innerText = "Stop All";
      setSinglePlay(false);
    }
  });

  sortSelect?.addEventListener("input", () => {
    setSort(sortSelect.value);
  });

  document.querySelectorAll("input[name=sortorder]").forEach((radiobox) => {
    radiobox.addEventListener("input", (e) => {
      setSortOrder((e.currentTarget as HTMLInputElement).value);
    });
  });

  setFilter(searchInput?.value ?? "");
  setSort(sortSelect?.value ?? "");
  setSortOrder(getSelectedSortOrderRadio()?.value ?? "");
  setSinglePlay(!!singlePlayCheckbox?.matches(":checked"));
}

init();
