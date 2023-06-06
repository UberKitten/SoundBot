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
  grid?: HTMLElement | null;

  connectedCallback() {
    const gridContainer = this.querySelector(".grid") as HTMLElement | null;
    const sortOrder = this.getAttribute("sortorder");

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

    this.updateSoundButtons();
  }

  static get observedAttributes() {
    return ["filter", "sort", "sortorder"];
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

  connectedCallback() {
    this.sort = this.getAttribute("sort");

    const soundData = this.getAttribute("sound");

    if (soundData) {
      this.sound = JSON.parse(soundData) as Sound;

      this.updateLabel();

      this.onclick = (e) => {
        if (!this.sound) return;

        if (document.querySelector("input#single-sound:checked")) {
          mainAudio.src = `${SOUNDS_PATH}/${this.sound.filename}`;
          mainAudio.play();
        } else {
          const btnAudio = document.createElement("audio");
          btnAudio.src = `${SOUNDS_PATH}/${this.sound.filename}`;

          buttonAudio.push(btnAudio);
          btnAudio.addEventListener("ended", (e) => {
            buttonAudio.splice(
              buttonAudio.indexOf(e.target as HTMLAudioElement),
              1
            );
          });
          btnAudio.play();
        }

        const currentTarget = e.currentTarget;
        if (!(currentTarget instanceof HTMLElement)) return;

        copy(
          currentTarget,
          currentTarget.querySelector(".sortDisplay") as HTMLElement | null
        );
      };
    }
  }

  updateLabel() {
    if (!this.sound) {
      this.innerHTML = `
        <div>
          <span>Sound unavilable</span>
        </div>
        <div>
          <span>&nbsp;</span>
        </div>`;

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
      <div>
        <span class="icon">&#x1F50A;</span>
        <span>${this.sound.name}</span>
      </div>
      <div>
        <span class="sortDisplay">${sublabels.get(this.sort) ?? "&nbsp;"}</span>
      </div>`;

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

    this.updateLabel();
  }

  static get observedAttributes() {
    return ["sound", "sort"];
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
    } else {
      if (stopButton) stopButton.innerText = "Stop All";
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
  setSortOrder(
    singlePlayCheckbox && singlePlayCheckbox.matches(":checked")
      ? singlePlayCheckbox.value
      : ""
  );
}

init();
