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
import { showContextMenu, showContextMenuAt } from "context-menu";
import { attachLongPress } from "long-press";
import { mergeSoundRepresentation } from "sound-live-update";
import {
  showClipForSoundClick,
  stopClipDisplayForSound,
} from "video-popover";

export class SoundboardButton extends HTMLElement {
  sound?: Sound;
  sort: string | null = null;
  singlePlay: boolean | null = null;
  displayDate: string = "";
  audioChangeListener: (event: Event) => void;
  progressAnimationId: number | null = null;
  longPressAttached = false;

  constructor() {
    super();

    this.audioChangeListener = (event) => {
      this.updateIndicators();
      if (
        this.sound &&
        (event.type === "pause" || event.type === "ended") &&
        getActiveAudioGroups(this.sound).size === 0
      ) {
        stopClipDisplayForSound(this.sound);
      }
    };
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

    // Touch long-press opens the same menu (iOS never fires contextmenu for a
    // long-press). Registered BEFORE the contextmenu handler so its Android
    // double-fire suppression listener runs first at the target phase.
    if (!this.longPressAttached) {
      this.longPressAttached = true;
      attachLongPress(this, (x, y) => {
        if (!this.sound) return;
        showContextMenuAt(x, y, this.sound);
      });
    }

    this.oncontextmenu = (e) => {
      if (!this.sound) return;
      showContextMenu(e, this.sound);
    };

    this.onclick = (e) => {
      if (!this.sound) return;

      if (this.singlePlay && isMainAudioActive(this.sound)) {
        stopMainAudio();
        stopClipDisplayForSound(this.sound);
        this.updateIndicators();
        return;
      }

      showClipForSoundClick(this.sound);
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
      const unavailable = document.createElement("span");
      unavailable.textContent = "Sound unavailable";
      const spacer = document.createElement("span");
      spacer.textContent = "\u00A0";
      this.replaceChildren(unavailable, spacer);
      this.removeAttribute("title");
      this.removeAttribute("aria-label");
      return;
    }

    const totalPlays =
      this.sound.discord_plays +
      this.sound.twitch_plays +
      this.sound.web_plays;
    const sublabels: Record<string, string> = {
      count: totalPlays === 1 ? "1 Play" : `${totalPlays} Plays`,
      date: this.displayDate,
    };
    const sublabel = this.sort ? sublabels[this.sort] : undefined;

    const icon = document.createElement("span");
    icon.className = "icon hidden";
    icon.textContent = "🔊";

    const nameLabel = document.createElement("span");
    nameLabel.className = "sound-name-label";
    nameLabel.textContent = this.sound.name;
    nameLabel.title = this.sound.name;

    const sortDisplay = document.createElement("span");
    sortDisplay.className = "sortDisplay";
    sortDisplay.textContent = sublabel ?? "\u00A0";

    this.replaceChildren(icon, nameLabel, sortDisplay);
    this.title = this.sound.name;
    this.setAttribute("aria-label", `Play sound ${this.sound.name}`);
    this.classList.toggle("no-sublabel", !sublabel);
  }

  attributeChangedCallback(
    property: string,
    oldValue: string | null,
    newValue: string | null
  ) {
    if (oldValue === newValue) return;

    if (property === "sound") {
      const nextSound = newValue ? (JSON.parse(newValue) as Sound) : undefined;
      if (this.sound && nextSound && this.sound.name === nextSound.name) {
        mergeSoundRepresentation(this.sound, nextSound);
      } else {
        this.sound = nextSound;
      }
    }
    if (property === "sort") this.sort = newValue;
    if (property === "singleplay") this.singlePlay = !!newValue;

    this.updateLabel();
    this.updateIndicators();
  }

  static get observedAttributes() {
    return ["sound", "sort", "singleplay"];
  }
}
