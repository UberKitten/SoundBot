import {
  Sound,
  addMainAudioChangeListener,
  getActiveAudioGroups,
  getMainAudioProgress,
  isMainAudioActive,
  playButtonAudio,
  playMainAudio,
  stopMainAudio,
} from "audio";
import { copy } from "clipboard";
import { showContextMenu } from "context-menu";
import { getDisplayDate, scheduleBackgroundTask } from "utils";

export class SoundboardButton extends HTMLElement {
  sound?: Sound;
  sort: string | null = null;
  singlePlay: boolean | null = null;
  displayDate: string = "";
  audioChangeListener: () => void;
  progressAnimationId: number | null = null;

  constructor() {
    super();

    this.audioChangeListener = () => this.updateIndicators();
    addMainAudioChangeListener(this.audioChangeListener);
  }

  connectedCallback() {
    this.sort = this.getAttribute("sort");
    this.singlePlay = !!this.getAttribute("singleplay");

    if (!this.sound) {
      const soundData = this.getAttribute("sound");
      if (!soundData) return;
      this.sound = JSON.parse(soundData) as Sound;
    }

    if (!this.displayDate) {
      // Convert ISO string to Date for display
      const createdDate = this.sound.created ? new Date(this.sound.created) : new Date();
      this.displayDate = createdDate.toLocaleDateString(undefined, {
        year: "numeric",
        month: "long",
        day: "numeric",
      });
    }

    this.updateLabel();
    this.updateIndicators();

    this.oncontextmenu = (e) => {
      if (!this.sound) return;
      showContextMenu(e, this.sound);
    };

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
        playButtonAudio(this.sound, this.audioChangeListener);
      }

      this.updateIndicators();

      const currentTarget = e.currentTarget;
      if (!(currentTarget instanceof HTMLElement)) return;

      copy(
        currentTarget,
        currentTarget.querySelector<HTMLElement>(".sortDisplay")
      );
    };
  }

  updateIndicators() {
    const isPlaying = getActiveAudioGroups(this.sound).size > 0;

    this.singlePlay && isPlaying
      ? this.classList.add("single-playing")
      : this.classList.remove("single-playing");

    if (this.singlePlay && isPlaying) {
      this.startProgressAnimation();
    } else {
      this.stopProgressAnimation();
    }

    const icon = this.querySelector(".icon");
    if (!(icon instanceof HTMLElement)) return;

    isPlaying ? icon.classList.remove("hidden") : icon.classList.add("hidden");
  }

  startProgressAnimation() {
    if (this.progressAnimationId !== null) return;

    const tick = () => {
      const progress = getMainAudioProgress();
      this.style.setProperty("--progress", `${progress * 100}%`);
      this.progressAnimationId = requestAnimationFrame(tick);
    };
    this.progressAnimationId = requestAnimationFrame(tick);
  }

  stopProgressAnimation() {
    if (this.progressAnimationId !== null) {
      cancelAnimationFrame(this.progressAnimationId);
      this.progressAnimationId = null;
    }
    this.style.removeProperty("--progress");
  }

  updateLabel() {
    if (!this.sound) {
      this.innerHTML = `
        <span>Sound unavilable</span>
        <span>&nbsp;</span>`;

      return;
    }

    const totalPlays = this.sound.discord_plays + this.sound.twitch_plays + this.sound.web_plays;
    const sublabels: Map<string | null, string> = new Map([
      [
        "count",
        `${totalPlays === 1 ? "1 Play" : totalPlays.toString().concat(" Plays")}`,
      ],
      ["date", this.displayDate],
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
