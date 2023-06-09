import { Sound, isSoundObject } from "audio";
import { DB_PATH } from "config";
import { init } from "dom-init";
import {
  alphaSort,
  clearError,
  fetchJson,
  getCanonicalString,
  getElement,
  numericSort,
  scheduleBackgroundTask,
  setError,
} from "utils";

export class SoundboardApp extends HTMLElement {
  sounds: Array<Sound> = [];
  filter = "";
  sort: string | null = null;
  sortOrder: "asc" | "desc" | null = null;
  singlePlay: boolean = true;
  grid: HTMLElement;

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
    // this is ok for now since we only load sounds once
    if (this.grid.children.length === this.sounds.length && updatedProp) {
      // update

      if (updatedProp === "sortorder" || updatedProp === "sort") {
        scheduleBackgroundTask(() => {
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
              this.grid.appendChild(sortedButton);
            });
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
    if (property === "singleplay") this.singlePlay = !(newValue === "no");

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
