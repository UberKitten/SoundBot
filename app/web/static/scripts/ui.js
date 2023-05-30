// there's no error handling in here, but whatever - hopefully nothing breaks yeehaw

const mainAudio = document.createElement("audio");
const buttonAudio = [];

class Soundboard extends HTMLElement {
  sounds = [];
  filter = "";
  sort = "";
  sortOrder = "";

  connectedCallback() {
    this.filter = this.getAttribute("filter");
    this.sort = this.getAttribute("sort");
    this.sortOrder = this.getAttribute("sortorder");

    this.fetchSounds().then((sounds) => {
      this.sounds = sounds;
      this.updateSoundButtons();
    });
  }

  sortSounds(a, b) {
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
    // reset children
    this.textContent = "";

    this.sounds
      .filter(
        ({ name }) =>
          !this.filter || getCanonicalString(name).includes(this.filter)
      )
      .sort((a, b) => this.sortSounds(a, b))
      .forEach((sound) => {
        const button = document.createElement("soundboard-button");
        button.setAttribute("sound", JSON.stringify(sound));
        button.setAttribute("sort", this.sort);
        button.dataset.copyText = `!${sound.name}`;
        this.appendChild(button);
      });
  }

  attributeChangedCallback(property, oldValue, newValue) {
    if (oldValue === newValue) return;

    if (property === "filter") this.filter = getCanonicalString(newValue);
    if (property === "sort") this.sort = newValue;
    if (property === "sortorder") this.sortOrder = newValue;

    this.updateSoundButtons();
  }

  static get observedAttributes() {
    return ["filter", "sort", "sortorder"];
  }

  fetchSounds() {
    return fetch(DB_PATH)
      .then((dbRes) => dbRes.json())
      .then((db) => db.sounds);
  }
}

customElements.define("soundboard-app", Soundboard);

class SoundboardButton extends HTMLElement {
  sound = null;
  sort = "";

  connectedCallback() {
    this.sound = JSON.parse(this.getAttribute("sound"));
    this.sort = this.getAttribute("sort");

    this.updateLabel();

    this.onclick = (e) => {
      if (document.querySelector("input#single-sound:checked")) {
        mainAudio.src = `${SOUNDS_PATH}/${this.sound.filename}`;
        mainAudio.play();
      } else {
        const btnAudio = document.createElement("audio");
        btnAudio.src = `${SOUNDS_PATH}/${this.sound.filename}`;

        buttonAudio.push(btnAudio);
        btnAudio.addEventListener("ended", (e) => {
          buttonAudio.splice(buttonAudio.indexOf(e.target), 1);
        });
        btnAudio.play();
      }

      copy(e.currentTarget, e.currentTarget.querySelector("span:last-child"));
    };
  }

  updateLabel() {
    const sublabels = {
      count: `${this.sound.count} Plays`,
      date: getDisplayDate(this.sound.modified),
    };

    this.innerHTML = `
      <span>${this.sound.name}</span>
      <span>${sublabels[this.sort] ?? "&nbsp;"}</span>`;

    if (sublabels[this.sort]) {
      this.classList.remove("no-sublabel");
    } else {
      this.classList.add("no-sublabel");
    }
  }

  attributeChangedCallback(property, oldValue, newValue) {
    if (oldValue === newValue) return;

    if (property === "sound") this.sound = JSON.parse(newValue);
    if (property === "sort") this.sort = newValue;

    this.updateLabel();
  }

  static get observedAttributes() {
    return ["sound", "sort"];
  }
}

customElements.define("soundboard-button", SoundboardButton);

function getDisplayDate(timestamp_ns) {
  // convert ns timestamp to ms timestamp then to Date
  const date = new Date(timestamp_ns / 1000 / 1000);

  // format date (undefined means use local system preference)
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

function getCanonicalString(str) {
  // normalize to decompose unicode sequences into compatible strings
  // convert to upper case then lower case to trigger case folding
  // trim whitespace
  return str?.normalize("NFKD").toUpperCase().toLowerCase().trim();
}

function numericSort(a, b, order) {
  return order === "asc" ? a - b : b - a;
}

function alphaSort(rawA, rawB, order) {
  const a = getCanonicalString(rawA);
  const b = getCanonicalString(rawB);

  return order === "asc" ? a.localeCompare(b) : b.localeCompare(a);
}

function stopButtonAudio() {
  buttonAudio.forEach((audio) => {
    audio.pause();
  });
  buttonAudio.splice(0, buttonAudio.length);
}

function setFilter(search) {
  app.setAttribute("filter", search);
}

function setSort(sortBy) {
  app.setAttribute("sort", sortBy);
}

function setSortOrder(order) {
  app.setAttribute("sortorder", order);
}

const app = document.querySelector("soundboard-app");

document.querySelector("input[type=search]").addEventListener("input", (e) => {
  setFilter(e.target.value);
});

document.querySelector("button#stop").addEventListener("click", () => {
  mainAudio.pause();
  stopButtonAudio();
});

document.querySelector("input#single-sound").addEventListener("input", () => {
  if (document.querySelector("input#single-sound:checked")) {
    stopButtonAudio();
  }
});

document.querySelector("#sort").addEventListener("input", (e) => {
  setSort(e.target.value);
});

document.querySelectorAll("input[name=sortorder]").forEach((radiobox) => {
  radiobox.addEventListener("input", (e) => {
    setSortOrder(e.target.value);
  });
});

function init() {
  setFilter(document.querySelector("input[type=search]").value);
  setSort(document.querySelector("#sort").value);
  setSortOrder(document.querySelector("input[name=sortorder]:checked").value);
}

init();
