// there's no error handling in here, but whatever - hopefully nothing breaks yeehaw

import { copy } from "./clipboard.js";
import { DB_PATH, SOUNDS_PATH } from "./config.js";
import {
  alphaSort,
  getCanonicalString,
  getDisplayDate,
  numericSort,
} from "./util.js";

const mainAudio = document.createElement("audio");
const buttonAudio: Array<HTMLAudioElement> = [];

interface Sound {
  name: string;
  filename: string;
  modified: number;
  count: number;
  tags: Array<string>;
}

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

    this.fetchSounds().then((sounds) => {
      this.sounds = sounds as Array<Sound>;
      this.updateSoundButtons();
    });
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

  updateSoundButtons() {
    if (!this.grid) return;

    // reset children
    this.grid.textContent = "";

    this.sounds
      .filter(
        ({ name }) =>
          !this.filter || getCanonicalString(name).includes(this.filter)
      )
      .sort((a, b) => this.sortSounds(a, b))
      .forEach((sound) => {
        const button = document.createElement("soundboard-button");
        button.setAttribute("sound", JSON.stringify(sound));
        button.setAttribute("sort", this.sort ?? "");
        if (this.singlePlay) button.setAttribute("singleplay", "true");
        button.dataset.copyText = `!${sound.name}`;
        this.grid?.appendChild(button);
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
    if (property === "singleplay") this.singlePlay = !!newValue;

    this.updateSoundButtons();
  }

  static get observedAttributes() {
    return ["filter", "sort", "sortorder", "singleplay"];
  }

  async fetchSounds() {
    const dbRes = await fetch(DB_PATH);
    const db = await dbRes.json();
    return db.sounds;
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

    if (soundData) {
      this.sound = JSON.parse(soundData) as Sound;

      this.updateLabel();

      this.onclick = (e) => {
        const soundPath = this.getSoundPath();
        if (!soundPath) return;

        if (
          this.singlePlay &&
          this.getActiveAudioElements().includes(mainAudio)
        ) {
          mainAudio.pause();
          this.updateIndicators();
          return;
        }

        let audioElement = mainAudio;

        if (this.singlePlay) {
          audioElement.src = soundPath;
          audioElement.play();
        } else {
          audioElement = document.createElement("audio");
          audioElement.src = soundPath;

          buttonAudio.push(audioElement);

          audioElement.addEventListener("ended", (e) => {
            buttonAudio.splice(
              buttonAudio.indexOf(e.currentTarget as HTMLAudioElement),
              1
            );
          });

          audioElement.play();
        }

        ["pause", "play", "ended"].forEach((eventType) => {
          audioElement.addEventListener(eventType, () => {
            this.updateIndicators();
          });
        });

        this.updateIndicators();

        const currentTarget = e.currentTarget;
        if (!(currentTarget instanceof HTMLElement)) return;

        copy(
          currentTarget,
          currentTarget.querySelector(".sortDisplay") as HTMLElement | null
        );
      };
    }
  }

  getSoundPath() {
    return this.sound && `${SOUNDS_PATH}/${this.sound.filename}`;
  }

  getActiveAudioElements() {
    const soundPath = this.getSoundPath();
    return soundPath
      ? [mainAudio, ...buttonAudio].filter(
          (audioElement) =>
            !audioElement.paused && audioElement.src.endsWith(soundPath)
        )
      : [];
  }

  updateIndicators() {
    const isPlaying = this.getActiveAudioElements().length > 0;

    this.style.backgroundColor =
      this.singlePlay && isPlaying ? "var(--stop-color)" : "";

    const icon = this.querySelector(".icon");
    if (!(icon instanceof HTMLElement)) return;

    icon.style.visibility = isPlaying ? "initial" : "hidden";
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
      <span class="icon">&#x1F50A;</span>
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

  function stopButtonAudio() {
    buttonAudio.forEach((audio) => {
      audio.pause();
    });
    buttonAudio.splice(0, buttonAudio.length);
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

  searchInput?.addEventListener("input", (e) => {
    setFilter((e.currentTarget as HTMLInputElement).value);
  });

  stopButton?.addEventListener("click", () => {
    mainAudio.pause();
    stopButtonAudio();
  });

  singlePlayCheckbox?.addEventListener("input", (e) => {
    if ((e.currentTarget as HTMLInputElement).matches(":checked")) {
      stopButtonAudio();
      if (stopButton) stopButton.innerText = "Stop";
      setSinglePlay(true);
    } else {
      if (stopButton) stopButton.innerText = "Stop All";
      setSinglePlay(false);
    }
  });

  sortSelect?.addEventListener("input", (e) => {
    setSort((e.currentTarget as HTMLSelectElement).value);
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
