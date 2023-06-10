import { Sound, isSoundObject } from "audio";
import { DB_PATH } from "config";
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

export class SoundboardApp extends HTMLElement {
  sounds: Array<Sound> = [];
  filter = "";
  sort: string | null = null;
  sortOrder: "asc" | "desc" | null = null;
  singlePlay: boolean = true;
  grid: HTMLElement;
  activeRenders: number[] = [];
  firstRenderCompleted = false;

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
        ).sort((a, b) => {
          const soundA: Sound = JSON.parse(a.getAttribute("sound")!);
          const soundB: Sound = JSON.parse(b.getAttribute("sound")!);
          return this.sortSounds(soundA, soundB);
        });

        buttons.forEach((button) => button.classList.add("no-display"));

        const renderSliceSize = 50;
        let iButton = 0;
        const renderSlices: Array<HTMLButtonElement[]> = [];

        while (iButton < buttons.length) {
          renderSlices.push(buttons.slice(iButton, iButton + renderSliceSize));
          iButton += renderSliceSize;
        }

        const renderSlice = (slice: HTMLButtonElement[]) => {
          slice.forEach((sortedButton) => {
            if (updatedProp === "sort")
              sortedButton.setAttribute("sort", this.sort ?? "");

            sortedButton.style.animationDelay = `${buttonDelay(
              buttons.indexOf(sortedButton)
            )}s`;
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

        const sounds: Map<HTMLButtonElement, Sound> = new Map();

        const filteredButtons = buttons.filter((button) => {
          if (!this.filter) return true;
          const sound = JSON.parse(button.getAttribute("sound")!) as Sound;
          sounds.set(button, sound);
          return getCanonicalString(sound.name).includes(this.filter);
        });

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
          button.dataset.copyText = `!${sound.name}`;

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
